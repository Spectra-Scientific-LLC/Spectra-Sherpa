"""Canonical contract and numerical-path tests for feature-range selection."""

from __future__ import annotations

import asyncio
import json
import multiprocessing
import os
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np
import pytest
import yaml

import spectra_sherpa.app.services.dag.nodes  # noqa: F401 - populate built-ins
from spectra_sherpa.app.lib.sherpa_dataset import SampleAxis, SherpaDataset, SpectralAxis, TimeAxis
from spectra_sherpa.app.services.dag.executor_pool import WorkerExecutionContext, _run_node_in_worker
from spectra_sherpa.app.services.dag.node_base import node_registry
from spectra_sherpa.app.services.dag.nodes.preprocessing.clip_range_node import (
    ClipRangeNode,
    _clip_range_dispatch,
)
from spectra_sherpa.core.execution_runtime import ExecutionRuntime
from spectra_sherpa.execution_contract_vocabulary import (
    LifecycleKind,
    ManagedOptimizationEligibility,
    RuntimeFamily,
    WorkerCapability,
)
from tests.performance_contract import PerformanceCeiling


def _spectra(*, descending: bool = False) -> SherpaDataset:
    coordinates = np.array([400.0, 800.0, 1200.0, 1600.0, 2000.0])
    X = np.arange(10.0).reshape(2, 5)
    if descending:
        coordinates = coordinates[::-1]
        X = X[:, ::-1]
    return SherpaDataset(
        X=X,
        target=np.array([1.0, 2.0]),
        feature_axis=SpectralAxis(values=coordinates, units="cm-1", title="Wavenumber"),
        sample_axis=SampleAxis(
            values=np.array([10.0, 11.0]),
            labels=["a", "b"],
            title="Sample",
            sample_table={"batch": ["A", "B"]},
        ),
        units="absorbance",
        data_role="X_spectra",
        title="Range fixture",
        is_time_series=True,
    )


def test_clip_range_has_a_representative_absolute_performance_ceiling() -> None:
    coordinates = np.linspace(400.0, 4_000.0, 1_600)

    with PerformanceCeiling("preprocess.clip_range", "1600-feature-axis", 5.0).measure():
        mask, diagnostics = _clip_range_dispatch(coordinates, minimum=650.0, maximum=3_750.0)

    assert 0 < int(mask.sum()) < coordinates.size
    assert diagnostics["input_features"] == 1_600


def test_clip_range_has_one_closed_local_contract() -> None:
    metadata = node_registry.get_metadata("preprocess.clip_range")
    contract = metadata.resolved_execution_contract()

    assert contract is not None
    assert contract.payload["operation_id"] == "preprocess.clip_range"
    assert contract.payload["runtime_family"] == RuntimeFamily.SHERPA_NATIVE.value
    assert contract.payload["lifecycle_kind"] == LifecycleKind.STATELESS_TRANSFORM.value
    assert contract.payload["implementation_id"] == "spectrasherpa.preprocess.clip_range"
    assert contract.payload["managed_optimization_eligibility"] == (ManagedOptimizationEligibility.LOCAL.value,)
    assert contract.payload["required_worker_capabilities"] == (WorkerCapability.READ_DATASET.value,)
    assert contract.payload["feature_effect"] == "filters_features"
    assert contract.payload["axis_effect"] == "changes_axis"
    assert metadata.input_types == ["SpectralDataset"]
    assert metadata.output_type == "SpectralDataset"
    assert metadata.input_ports[0].accepted_data_roles == ["X_spectra"]
    assert metadata.output_ports[0].accepted_data_roles == ["X_spectra"]


def test_clip_range_admission_preserves_exact_current_parameters() -> None:
    node = node_registry.create_node(
        "preprocess.clip_range",
        "range",
        {"minimum": 800, "maximum": 1600},
    )
    assert node.parameters == {"minimum": 800.0, "maximum": 1600.0}


@pytest.mark.parametrize(
    "parameters",
    [
        {"minimum": 800, "maximum": 1600, "swap": True},
        {"minimum": 1600, "maximum": 800},
        {"minimum": 800, "maximum": 800},
        {"minimum": True, "maximum": 1600},
        {"minimum": 800, "maximum": float("inf")},
        {"min_wavenumber": 800, "max_wavenumber": 1600},
    ],
)
def test_clip_range_rejects_hidden_coerced_reversed_and_retired_parameters(
    parameters: dict[str, object],
) -> None:
    with pytest.raises(ValueError):
        node_registry.create_node("preprocess.clip_range", "range", parameters)


def test_clip_range_resolves_declared_defaults_before_exact_admission() -> None:
    node = node_registry.create_node("preprocess.clip_range", "range", {})

    assert node.parameters == {"minimum": 400.0, "maximum": 4000.0}


@pytest.mark.parametrize("descending", [False, True])
def test_clip_range_selects_the_same_inclusive_coordinates_in_both_axis_directions(descending: bool) -> None:
    source = _spectra(descending=descending)
    mask, diagnostics = _clip_range_dispatch(
        source.feature_axis.values,
        minimum=800,
        maximum=1600,
    )

    np.testing.assert_array_equal(np.sort(source.feature_axis.values[mask]), np.array([800.0, 1200.0, 1600.0]))
    assert diagnostics == {
        "minimum": 800.0,
        "maximum": 1600.0,
        "inclusive_bounds": True,
        "axis_direction": "decreasing" if descending else "increasing",
        "input_features": 5,
        "output_features": 3,
        "removed_features": 2,
        "retained_fraction": 0.6,
        "selected_coordinate_minimum": 800.0,
        "selected_coordinate_maximum": 1600.0,
    }


@pytest.mark.parametrize(
    "coordinates",
    [
        np.array([]),
        np.array([[1.0, 2.0]]),
        np.array([1.0, float("nan")]),
        np.array([1.0, 1.0, 2.0]),
        np.array([1.0, 3.0, 2.0]),
    ],
)
def test_clip_range_rejects_invalid_feature_axes(coordinates: np.ndarray) -> None:
    with pytest.raises(ValueError):
        _clip_range_dispatch(coordinates, minimum=0.0, maximum=4.0)


def test_clip_range_rejects_an_interval_without_features() -> None:
    with pytest.raises(ValueError, match="excludes every"):
        _clip_range_dispatch(np.array([1.0, 2.0, 3.0]), minimum=4.0, maximum=5.0)


def test_live_and_generated_execution_share_data_metadata_diagnostics_and_impact() -> None:
    source = _spectra()
    node = ClipRangeNode("range", {"minimum": 800, "maximum": 1600})
    live = asyncio.run(node.execute(input_data=source))
    generated_source = "\n".join(node.generate_python({"default": "source"}, indent="", use_scp=False))
    namespace = {"results": {}, "source": source}
    exec(compile(generated_source, "<canonical range export>", "exec"), namespace)
    generated = namespace["results"]["range"]
    output = live.outputs["default"]

    np.testing.assert_array_equal(output.X, source.X[:, 1:4])
    np.testing.assert_array_equal(generated.X, output.X)
    np.testing.assert_array_equal(output.feature_axis.values, np.array([800.0, 1200.0, 1600.0]))
    np.testing.assert_array_equal(output.sample_axis.values, source.sample_axis.values)
    np.testing.assert_array_equal(output.target, source.target)
    assert output.feature_axis.units == "cm-1"
    assert output.feature_axis.title == "Wavenumber"
    assert output.sample_axis.labels == ["a", "b"]
    assert output.sample_axis.sample_table == {"batch": ["A", "B"]}
    assert output.is_time_series is True
    assert output.units == "absorbance"
    assert output.data_role == "X_spectra"
    assert output.provenance[-1].node_id == "range"
    assert dict(output.provenance[-1].parameters) == {"minimum": 800.0, "maximum": 1600.0}
    assert output.meta["clip_range_diagnostics"] == live.diagnostics
    assert dict(output.provenance[-1].impact or {}) == {
        "schema_version": "spectrasherpa-preprocess-clip-range-impact/1",
        **live.diagnostics,
    }
    generated_entry = generated.provenance.to_list()[-1]
    output_entry = output.provenance.to_list()[-1]
    assert generated_entry | {"timestamp": "ignored"} == output_entry | {"timestamp": "ignored"}
    assert generated.meta["clip_range_diagnostics"] == live.diagnostics
    with pytest.raises(TypeError):
        output.provenance[-1].impact["removed_features"] = 99  # type: ignore[index]
    json.dumps(output.provenance.to_list(), allow_nan=False)


def test_feature_only_selection_preserves_a_non_sample_observation_axis() -> None:
    source = _spectra()
    source._axes[source._SAMPLE_DIM] = TimeAxis(  # noqa: SLF001 - exercise the generic dim-0 contract
        values=np.array([0.0, 5.0]),
        units="min",
        title="Reaction time",
    )

    output = asyncio.run(ClipRangeNode("range", {"minimum": 800, "maximum": 1600}).execute(input_data=source)).outputs[
        "default"
    ]

    observation = output.get_observation_axis()
    assert isinstance(observation, TimeAxis)
    np.testing.assert_array_equal(observation.values, [0.0, 5.0])
    assert observation.units == "min"
    assert observation.title == "Reaction time"
    assert output.is_time_series is True


def test_clip_range_executes_in_a_real_spawned_worker() -> None:
    source = _spectra()
    context = WorkerExecutionContext(
        execution_id="canonical-range",
        runtime=ExecutionRuntime(),
        capabilities=(WorkerCapability.READ_DATASET.value,),
        origin_pid=os.getpid(),
    )
    try:
        pool = ProcessPoolExecutor(max_workers=1, mp_context=multiprocessing.get_context("spawn"))
    except (NotImplementedError, PermissionError, OSError) as exc:
        pytest.skip(f"spawn worker unavailable: {exc}")
    try:
        result = pool.submit(
            _run_node_in_worker,
            "preprocess.clip_range",
            "range",
            {"minimum": 800, "maximum": 1600},
            (source,),
            {},
            context,
        ).result(timeout=30)
    finally:
        pool.shutdown(wait=True)

    np.testing.assert_array_equal(result.outputs["default"].X, source.X[:, 1:4])
    worker = result.diagnostics["worker_execution"]
    assert worker["mode"] == "spawned_worker"
    assert worker["origin_pid"] == os.getpid()
    assert worker["worker_pid"] != os.getpid()


def test_clip_range_requires_its_declared_dataset_capability() -> None:
    context = WorkerExecutionContext(
        execution_id="canonical-range-denied", runtime=ExecutionRuntime(), origin_pid=os.getpid()
    )
    with pytest.raises(PermissionError, match="worker capabilities are missing"):
        _run_node_in_worker(
            "preprocess.clip_range",
            "range",
            {"minimum": 800, "maximum": 1600},
            (_spectra(),),
            {},
            context,
        )


def test_templates_and_runtime_have_no_retired_range_parameter_surface() -> None:
    package_root = Path(__file__).resolve().parents[1]
    templates = package_root / "src/spectra_sherpa/data/templates"
    for name in ("region_selection_pls.yaml",):
        payload = yaml.safe_load((templates / name).read_text(encoding="utf-8"))
        range_nodes = [
            node for node in payload["template_data"]["nodes"] if node["node_type"] == "preprocess.clip_range"
        ]
        assert len(range_nodes) == 1
        assert range_nodes[0]["parameters"] == {"minimum": 400, "maximum": 4000}

    cleaning_source = package_root / "src/spectra_sherpa/app/services/dag/nodes/preprocessing/cleaning_nodes.py"
    retired_builder_preprocessing = package_root / "src/spectra_sherpa/app/lib/preprocessing.py"
    workflow_builder_source = (
        package_root / "frontend/src/views/workflow-builder/WorkflowBuilderContent.vue"
    ).read_text(encoding="utf-8")
    assert not cleaning_source.exists()
    assert not retired_builder_preprocessing.exists()
    defaults = {parameter.name: parameter.default for parameter in ClipRangeNode.metadata.parameters}
    assert defaults == {"minimum": 400, "maximum": 4000}
    assert "workflowStore.getNodeMetadata(nodeType)?.parameters" in workflow_builder_source
    assert '"preprocess.clip_range": { min_wavenumber:' not in workflow_builder_source
