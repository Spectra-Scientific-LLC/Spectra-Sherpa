"""M4.3's intentionally small native/SpectroChemPy contract wedge."""

from __future__ import annotations

import hashlib
import multiprocessing
import os
import subprocess
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np
import pytest

import spectra_sherpa.app.services.dag.nodes.preprocessing  # noqa: F401
from spectra_sherpa.app.lib.sherpa_dataset import DomainContext, Provenance, SampleAxis, SherpaDataset, SpectralAxis
from spectra_sherpa.app.services.dag.executor_pool import WorkerExecutionContext, _run_node_in_worker
from spectra_sherpa.app.services.dag.executor_types import WorkflowEdge, WorkflowNode
from spectra_sherpa.app.services.dag.node_base import node_registry
from spectra_sherpa.app.services.dag.stable_execution_contract import (
    ensure_registered_execution_contract,
    implementation_digest_for_components,
)
from spectra_sherpa.app.services.dag.workflow_preflight import preflight_workflow
from spectra_sherpa.app.types import type_registry
from spectra_sherpa.core.execution_runtime import ExecutionRuntime
from spectra_sherpa.execution_contract_vocabulary import LifecycleKind, RuntimeFamily, WorkerCapability
from spectra_sherpa.sdk.execution_contract import NodeExecutionContract
from tests._optional_scp import HAS_SCP


@pytest.fixture(autouse=True)
def _semantic_registry() -> None:
    if not type_registry.is_loaded:
        type_registry.load(Path(__file__).resolve().parents[1] / "src" / "spectra_sherpa" / "app" / "types")


@pytest.mark.parametrize(
    ("node_type", "runtime_family", "implementation_id"),
    [
        ("preprocess.smooth", RuntimeFamily.SHERPA_NATIVE, "spectrasherpa.preprocess.smooth"),
        ("baseline.rubberband", RuntimeFamily.SHERPA_NATIVE, "spectrasherpa.baseline.rubberband"),
    ],
)
def test_vertical_slice_nodes_declare_complete_certified_transform_contracts(
    node_type: str, runtime_family: RuntimeFamily, implementation_id: str
) -> None:
    metadata = node_registry.get_metadata(node_type)
    contract = metadata.resolved_execution_contract()
    assert contract is not None
    assert contract.payload["runtime_family"] == runtime_family.value
    assert contract.payload["lifecycle_kind"] == LifecycleKind.STATELESS_TRANSFORM.value
    assert contract.payload["implementation_id"] == implementation_id
    assert contract.payload["required_worker_capabilities"] == (WorkerCapability.READ_DATASET.value,)
    assert metadata.policy is not None
    assert metadata.policy.required_worker_capabilities == []
    assert metadata.resolved_required_worker_capabilities() == (WorkerCapability.READ_DATASET.value,)
    assert metadata.input_ports and metadata.output_ports
    assert metadata.input_ports[0].type_ref == metadata.output_ports[0].type_ref


def test_native_to_scp_vertical_edge_is_authoritatively_typed() -> None:
    report = preflight_workflow(
        [
            WorkflowNode("smooth", "preprocess.smooth", {"method": "gaussian", "sigma": 1.0}),
            WorkflowNode("rubberband", "baseline.rubberband", {}),
        ],
        [WorkflowEdge("smooth", "rubberband")],
    )

    assert report.is_valid is False  # smooth still requires its upstream input
    assert report.edges[0].status == "typed_valid"
    assert not any(issue.code == "incompatible_semantic_edge" for issue in report.issues)


def test_vertical_slice_metadata_is_bound_to_one_immutable_execution_contract() -> None:
    contracts = []
    for node_type in ("preprocess.smooth", "baseline.rubberband"):
        metadata = node_registry.get_metadata(node_type)
        contract = ensure_registered_execution_contract(metadata)
        contracts.append(contract)

        assert contract.payload["operation_id"] == node_type
        assert [port["type_ref"] for port in contract.payload["semantic_inputs"]] == [
            "spectrasherpa://types/SpectralDataset/1.0"
        ]
        assert [port["type_ref"] for port in contract.payload["semantic_outputs"]] == [
            "spectrasherpa://types/SpectralDataset/1.0"
        ]
        assert contract.payload["parameter_schema_digest"]
        assert contract.payload["implementation_digest"]
        assert contract.payload["implementation_components"]
        assert contract.payload["deterministic"] is True

    assert contracts[0].digest != contracts[1].digest


def test_implementation_helpers_and_adapter_versions_are_in_the_contract_closure() -> None:
    smooth = ensure_registered_execution_contract(node_registry.get_metadata("preprocess.smooth"))
    baseline = ensure_registered_execution_contract(node_registry.get_metadata("baseline.rubberband"))

    smooth_components = {item["component_id"] for item in smooth.payload["implementation_components"]}
    baseline_components = {item["component_id"] for item in baseline.payload["implementation_components"]}

    assert "spectra_sherpa.app.services.dag.nodes.preprocessing.smooth_node" in smooth_components
    assert "spectra_sherpa.app.services.dag.nodes.preprocessing._shared" in smooth_components
    assert "spectra_sherpa.app.services.dag.nodes.preprocessing._transforms" not in smooth_components
    assert "spectra_sherpa.app.lib.preprocessing" not in smooth_components
    assert "distribution.numpy" in smooth_components
    assert "distribution.scipy" in smooth_components
    assert "spectra_sherpa.app.services.dag.nodes.preprocessing.baseline_nodes" in baseline_components
    assert "spectra_sherpa.app.services.dag.nodes.preprocessing._shared" in baseline_components
    assert "spectra_sherpa.app.lib.rubberband" in baseline_components
    assert "spectra_sherpa.app.lib.adapters.scp_adapter" not in baseline_components
    assert "distribution.numpy" in baseline_components
    assert "distribution.spectrochempy" not in baseline_components

    smooth_component_rows = {
        item["component_id"]: item["digest"] for item in smooth.payload["implementation_components"]
    }
    assert smooth_component_rows["distribution.numpy"] == hashlib.sha256(b"numpy=1.26.4").hexdigest()
    assert smooth_component_rows["distribution.scipy"] == hashlib.sha256(b"scipy=1.17.1").hexdigest()

    changed_components = [dict(component) for component in baseline.payload["implementation_components"]]
    for component in changed_components:
        if component["component_id"] == "spectra_sherpa.app.lib.rubberband":
            component["digest"] = "0" * 64
            break
    else:  # pragma: no cover - assertions above make this defensive.
        raise AssertionError("native rubberband authority was missing from the implementation closure")

    payload = baseline.as_dict()
    payload["implementation_components"] = changed_components
    payload["implementation_digest"] = implementation_digest_for_components(changed_components)
    changed = NodeExecutionContract.from_dict(payload)
    assert changed.digest != baseline.digest


def test_dag_registry_import_does_not_initialize_the_sdk_facade() -> None:
    """The live registry must not pull in the *heavy* SDK import surface.

    ``spectra_sherpa.sdk`` lazily loads its domain namespaces (PEP 562), so
    merely reaching ``spectra_sherpa.sdk.validate`` -- a legitimate,
    lightweight execution-contract dependency declared by
    ``regression_evaluator_node`` and the canonical fold executor -- puts
    ``spectra_sherpa.sdk`` and ``spectra_sherpa.sdk.validate`` themselves in
    ``sys.modules``. That's expected. What this guards against is the
    registry load dragging in the *other*, unrelated-and-heavier namespaces
    (archive/export/reporting concerns) as a side effect of that lazy
    facade no longer being lazy.
    """

    script = """
import os
import sys
# This is the real registry loader: it imports every preprocessing node and
# executes the two reviewed top-level contract bindings.
import spectra_sherpa.app.services.dag.nodes.preprocessing  # noqa: F401
heavy = {'harness_archive', 'harness_project', 'report', 'explore'}
heavy_loaded = any(name == f'spectra_sherpa.sdk.{mod}' for mod in heavy for name in sys.modules)
# SpectroChemPy may leave optional background resources alive after the registry
# imports every built-in.  The probe needs only fresh-import module state, so
# bypass interpreter teardown once that state is observed.
os._exit(1 if heavy_loaded else 0)
"""
    completed = subprocess.run(
        [sys.executable, "-c", script],
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr


def test_native_vertical_node_runs_in_a_real_spawned_worker() -> None:
    """The initial Sherpa-native wedge uses the production worker boundary."""
    context = WorkerExecutionContext(
        execution_id="m4-native-vertical",
        runtime=ExecutionRuntime(),
        capabilities=("read_dataset",),
        origin_pid=os.getpid(),
    )
    dataset = SherpaDataset(X=np.array([[1.0, 2.0, 3.0, 4.0, 5.0]]))
    try:
        pool = ProcessPoolExecutor(max_workers=1, mp_context=multiprocessing.get_context("spawn"))
    except (NotImplementedError, PermissionError, OSError) as exc:
        pytest.skip(f"spawn worker unavailable: {exc}")
    try:
        result = pool.submit(
            _run_node_in_worker,
            "preprocess.smooth",
            "smooth",
            {"method": "gaussian", "sigma": 1.0},
            (dataset,),
            {},
            context,
        ).result(timeout=30)
    finally:
        pool.shutdown(wait=True)

    assert isinstance(result.outputs["default"], SherpaDataset)
    assert result.diagnostics["worker_execution"]["mode"] == "spawned_worker"
    assert result.diagnostics["worker_execution"]["origin_pid"] == os.getpid()
    assert result.diagnostics["worker_execution"]["worker_pid"] != os.getpid()


def test_native_vertical_node_requires_its_declared_dataset_capability() -> None:
    """A node cannot silently acquire the provisional data capability in a worker."""
    context = WorkerExecutionContext(
        execution_id="m4-native-no-capability", runtime=ExecutionRuntime(), origin_pid=os.getpid()
    )
    dataset = SherpaDataset(X=np.array([[1.0, 2.0, 3.0, 4.0, 5.0]]))

    with pytest.raises(PermissionError, match="worker capabilities are missing"):
        _run_node_in_worker(
            "preprocess.smooth",
            "smooth",
            {"method": "gaussian", "sigma": 1.0},
            (dataset,),
            {},
            context,
        )


@pytest.mark.asyncio
@pytest.mark.skipif(not HAS_SCP, reason="SpectroChemPy optional dependency is absent")
async def test_scp_vertical_node_returns_the_same_sherpa_dataset_boundary() -> None:
    """The adapter crosses into SCP and returns to the canonical dataset type."""
    node = node_registry.create_node("baseline.rubberband", "rubberband", {})
    result = await node.run(
        SherpaDataset(
            X=np.array(
                [
                    [3.0, 2.1, 2.7, 2.0, 3.2],
                    [2.8, 2.0, 2.5, 1.9, 3.0],
                ]
            ),
            feature_axis=SpectralAxis(values=np.arange(5, dtype=float), units="cm-1"),
        )
    )

    assert isinstance(result.outputs["default"], SherpaDataset)
    assert result.outputs["default"].X.shape == (2, 5)


@pytest.mark.asyncio
@pytest.mark.skipif(not HAS_SCP, reason="SpectroChemPy optional dependency is absent")
async def test_scp_vertical_node_preserves_scientific_context_and_appends_only_its_own_provenance() -> None:
    """The controlled SCP adapter must not turn a numerical transform into data loss."""

    input_data = SherpaDataset(
        X=np.array([[3.0, 2.1, 2.7, 2.0, 3.2], [2.8, 2.0, 2.5, 1.9, 3.0]]),
        feature_axis=SpectralAxis(values=np.arange(5, dtype=float), units="cm-1", title="wavenumber"),
        sample_axis=SampleAxis(
            values=np.array([10.0, 20.0]),
            include_mask=np.array([True, False]),
            sample_table={"batch": ["A", "B"]},
        ),
        target=np.array([0.25, 0.75]),
        domain=DomainContext(technique="FTIR", sample_type="fixture"),
        provenance=Provenance(),
        title="certified-SCP-fixture",
    )
    input_data.provenance.append("data.fixture", {"source": "M4.6"}, node_id="source")

    result = await node_registry.create_node("baseline.rubberband", "rubberband", {}).run(input_data)
    output = result.outputs["default"]

    assert isinstance(output, SherpaDataset)
    np.testing.assert_array_equal(output.target, input_data.target)
    assert output.feature_axis is not None
    np.testing.assert_array_equal(output.feature_axis.values, input_data.feature_axis.values)
    assert output.feature_axis.units == "cm-1"
    assert output.feature_axis.title == "wavenumber"
    assert output.sample_axis is not None
    np.testing.assert_array_equal(output.sample_axis.include_mask, [True, False])
    assert output.sample_axis.sample_table == {"batch": ["A", "B"]}
    assert output.domain == input_data.domain
    assert output.title == input_data.title
    assert output.provenance.operations == ["data.fixture", "baseline.rubberband"]
    assert output.provenance[-1].node_id == "rubberband"


@pytest.mark.asyncio
@pytest.mark.skipif(not HAS_SCP, reason="SpectroChemPy optional dependency is absent")
async def test_native_rubberband_requires_coordinates_but_accepts_unitless_axes() -> None:
    """Rubberband needs ordered coordinates, not a recognized physical unit."""
    node = node_registry.create_node("baseline.rubberband", "rubberband", {})

    with pytest.raises(ValueError, match="requires a SpectralAxis"):
        await node.run(SherpaDataset(X=np.array([[3.0, 2.1, 2.7, 2.0, 3.2]])))

    result = await node.run(
        SherpaDataset(
            X=np.array([[3.0, 2.1, 2.7, 2.0, 3.2]]),
            feature_axis=SpectralAxis(values=np.arange(5, dtype=float)),
        )
    )
    output = result.outputs["default"]
    assert output.X.shape == (1, 5)
    assert output.feature_axis.units is None
