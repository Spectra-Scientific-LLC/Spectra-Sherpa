"""Reference-fitted scale node tests for the canonical DAG wedge.

This deliberately tests the scientific seam rather than the future Runner:
the held-out data must be transformed by statistics fitted on training data,
never statistics recomputed from the held-out rows themselves.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import numpy as np
import pytest

import spectra_sherpa.app.services.dag.nodes.preprocessing  # noqa: F401
from spectra_sherpa.app.lib.sherpa_dataset import SherpaDataset
from spectra_sherpa.app.services.dag.executor_types import WorkflowNode
from spectra_sherpa.app.services.dag.fitted_input_identity import fitted_input_identity
from spectra_sherpa.app.services.dag.node_base import node_registry
from spectra_sherpa.app.services.dag.nodes.preprocessing.scale_node import (
    ScaleNode,
    _apply_scale_state,
    _fit_scale_state,
)
from spectra_sherpa.app.services.dag.stable_execution_contract import ensure_registered_execution_contract
from spectra_sherpa.app.services.dag.validation_graph import admit_validation_graph
from spectra_sherpa.app.types import type_registry
from spectra_sherpa.execution_contract_vocabulary import LifecycleKind, RuntimeFamily, WorkerCapability
from tests.performance_contract import PerformanceCeiling


def test_scale_metadata_names_the_shared_data_matrix_contract() -> None:
    assert ScaleNode.metadata.input_ports[0].label == "Input Data"
    assert ScaleNode.metadata.output_ports[0].label == "Scaled Data"
    assert ScaleNode.metadata.input_ports[0].accepted_data_roles == ["X_spectra", "X_features"]


@pytest.fixture(autouse=True)
def _load_type_registry() -> None:
    if not type_registry.is_loaded:
        type_registry.load(Path(__file__).resolve().parents[1] / "src" / "spectra_sherpa" / "app" / "types")


def _dataset(rows: list[list[float]]) -> SherpaDataset:
    return SherpaDataset(X=np.asarray(rows, dtype=np.float64))


def test_fit_on_training_rows_then_apply_to_held_out_rows_without_refitting() -> None:
    node = ScaleNode("reference-scale", {"method": "mean_center"})
    training = _dataset([[0.0, 2.0], [2.0, 6.0]])
    held_out = _dataset([[4.0, 10.0]])

    state = node.fit_fitted_state(training)
    applied = node.apply_fitted_state(held_out, state)

    assert state == {
        "serializer": "spectra.scale-reference-json.v2",
        "method": "mean_center",
        "center": True,
        "input_identity": fitted_input_identity(training, features=2),
        "mean": [1.0, 4.0],
        "scale": None,
    }
    np.testing.assert_allclose(applied.X, [[3.0, 6.0]])
    # The held-out mean is [4, 10], so refitting there would produce zeros.
    assert not np.allclose(applied.X, 0.0)


def test_autoscale_uses_only_fitted_reference_statistics_and_preserves_zero_variance_features() -> None:
    node = ScaleNode("reference-scale", {"method": "autoscale", "center": True})
    training = _dataset([[1.0, 5.0], [3.0, 5.0]])
    held_out = _dataset([[5.0, 5.0]])

    state = node.fit_fitted_state(training)
    applied = node.apply_fitted_state(held_out, state)

    assert state["scale"] == [1.0, 1.0]
    np.testing.assert_allclose(applied.X, [[3.0, 0.0]])
    assert applied.units == "dimensionless"


@pytest.mark.parametrize(
    "state",
    [
        {"serializer": "spectra.scale-reference-json.v2"},
        {
            "serializer": "spectra.scale-reference-json.v2",
            "method": "autoscale",
            "center": True,
            "mean": [1.0],
            "scale": [1.0],
        },
        {
            "serializer": "spectra.scale-reference-json.v2",
            "method": "scale_max",
            "center": True,
            "mean": [1.0, 2.0],
            "scale": [1.0, 1.0],
        },
        {
            "serializer": "spectra.scale-reference-json.v2",
            "method": "mean_center",
            "center": False,
            "mean": [1.0, 2.0],
            "scale": None,
        },
        {
            "serializer": "spectra.scale-reference-json.v2",
            "method": "mean_center",
            "center": True,
            "mean": [1.0, 2.0],
            "scale": [1.0, 1.0],
        },
        {
            "serializer": "spectra.scale-reference-json.v2",
            "method": "autoscale",
            "center": True,
            "mean": [1.0, 2.0],
            "scale": [0.0, 1.0],
        },
        {
            "serializer": "spectra.scale-reference-json.v2",
            "method": "pareto",
            "center": True,
            "mean": [1.0, 2.0],
            "scale": [-1.0, 1.0],
        },
    ],
)
def test_apply_rejects_malformed_or_feature_incompatible_fitted_state(state: dict[str, object]) -> None:
    node = ScaleNode("reference-scale", {"method": "autoscale"})
    with pytest.raises(ValueError, match="fitted scale state"):
        node.apply_fitted_state(_dataset([[1.0, 2.0]]), state)


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_fit_rejects_nonfinite_training_data_before_emitting_state(value: float) -> None:
    node = ScaleNode("reference-scale", {"method": "autoscale"})
    with pytest.raises(ValueError, match="finite two-dimensional training matrix"):
        node.fit_fitted_state(_dataset([[1.0, value], [2.0, 3.0]]))


def test_apply_rejects_nonfinite_input_data() -> None:
    node = ScaleNode("reference-scale", {"method": "mean_center"})
    state = node.fit_fitted_state(_dataset([[1.0, 2.0], [2.0, 3.0]]))
    with pytest.raises(ValueError, match="finite two-dimensional matrix"):
        node.apply_fitted_state(_dataset([[float("nan"), 2.0]]), state)


def test_local_execute_is_explicitly_one_shot_but_has_the_same_math() -> None:
    node = ScaleNode("reference-scale", {"method": "pareto", "center": False})
    dataset = _dataset([[1.0, 4.0], [5.0, 12.0]])

    expected = node.apply_fitted_state(dataset, node.fit_fitted_state(dataset))
    actual = asyncio.run(node.execute(input_data=dataset))

    output = actual.outputs["default"]
    np.testing.assert_allclose(output.X, expected.X)
    assert output.provenance[-1].op_id == "preprocess.scale"
    parameters = dict(output.provenance[-1].parameters)
    assert parameters["state_serializer"] == "spectra.scale-reference-json.v2"
    saved_state = dict(parameters["transform_state"])
    identity = dict(saved_state.pop("input_identity"))
    assert identity["features"] == 2
    assert identity["axis"] == (None, None, None, None)
    assert saved_state == {
        "serializer": "spectra.scale-reference-json.v2",
        "method": "pareto",
        "center": False,
        "mean": None,
        "scale": (np.sqrt(2.0), 2.0),
    }


def test_workbench_reference_port_fits_reference_and_transforms_only_the_main_input() -> None:
    node = ScaleNode("reference-scale", {"method": "autoscale", "center": True})
    training = _dataset([[1.0, 5.0], [3.0, 9.0]])
    application = _dataset([[5.0, 13.0]])

    execution = asyncio.run(node.execute(default=application, reference=training))

    np.testing.assert_allclose(execution.outputs["default"].X, [[3.0, 3.0]])
    saved_state = dict(execution.outputs["default"].provenance[-1].parameters["transform_state"])
    assert dict(saved_state.pop("input_identity"))["features"] == 2
    assert saved_state == {
        "serializer": "spectra.scale-reference-json.v2",
        "method": "autoscale",
        "center": True,
        "mean": (2.0, 7.0),
        "scale": (1.0, 2.0),
    }


def test_python_export_uses_the_canonical_dispatcher_and_optional_reference() -> None:
    node = ScaleNode("reference-scale", {"method": "pareto", "center": False})

    source = "\n".join(
        node.generate_python(
            {"default": "application_data", "reference": "training_data"},
            use_scp=False,
        )
    )

    compile(f"def exported(application_data, training_data):\n{source}", "<preprocess.scale export>", "exec")
    assert "scale_node import ScaleNode" in source
    assert "fit_fitted_state(training_data)" in source
    assert "apply_fitted_state(application_data, _state)" in source
    assert "np.std" not in source


def test_removed_duplicate_scale_operation_and_old_parameter_grammar_fail_closed() -> None:
    with pytest.raises(KeyError):
        node_registry.get_metadata("preprocess.fitted_scale")
    with pytest.raises(ValueError):
        node_registry.create_node("preprocess.scale", "scale", {"method": "scale_max"})
    with pytest.raises(ValueError):
        node_registry.create_node(
            "preprocess.scale",
            "scale",
            {"method": "autoscale", "target_max": 1.0},
        )


def test_scale_declares_a_complete_fitted_transform_contract() -> None:
    metadata = node_registry.get_metadata("preprocess.scale")
    contract = ensure_registered_execution_contract(metadata)

    assert contract.payload["runtime_family"] == RuntimeFamily.SHERPA_NATIVE.value
    assert contract.payload["lifecycle_kind"] == LifecycleKind.FITTED_TRANSFORM.value
    assert contract.payload["required_worker_capabilities"] == (WorkerCapability.READ_DATASET.value,)
    assert contract.payload["fitted_state_serializer"] == "spectra.scale-reference-json.v2"
    assert [port["type_ref"] for port in contract.payload["semantic_inputs"]] == [
        "spectrasherpa://types/SpectralDataset/1.0",
        "spectrasherpa://types/SpectralDataset/1.0",
    ]
    assert [port["type_ref"] for port in contract.payload["semantic_outputs"]] == [
        "spectrasherpa://types/SpectralDataset/1.0"
    ]
    assert contract.payload["semantic_inputs"][0]["accepted_data_roles"] == (
        "X_features",
        "X_spectra",
    )
    assert contract.payload["semantic_inputs"][1]["accepted_data_roles"] == (
        "X_features",
        "X_spectra",
    )
    assert contract.payload["unit_effect"] == "changes_units"


def test_scale_is_admitted_only_as_a_fitted_transform_identity() -> None:
    graph = admit_validation_graph([WorkflowNode("reference-scale", "preprocess.scale", {"method": "autoscale"})], [])
    assert graph.nodes[0].contract.payload["lifecycle_kind"] == "fitted_transform"


def test_scale_representative_fit_and_application_have_absolute_ceilings() -> None:
    matrix = np.random.default_rng(20260905).normal(size=(200, 1_600))

    with PerformanceCeiling("preprocess.scale", "autoscale-200x1600-fit-and-apply", 5.0).measure():
        state = _fit_scale_state(matrix, method="autoscale", center=True)
        scaled = _apply_scale_state(matrix, state)

    with PerformanceCeiling(
        "preprocess.apply_fitted_scale",
        "autoscale-200x1600-state-replay",
        5.0,
    ).measure():
        replayed = _apply_scale_state(matrix, state)

    assert scaled.shape == matrix.shape
    np.testing.assert_array_equal(replayed, scaled)
