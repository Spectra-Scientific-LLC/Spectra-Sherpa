"""C2h canonical ordinary-least-squares scientific and contract proofs."""

from __future__ import annotations

import copy

import numpy as np
import pytest

import spectra_sherpa.app.services.dag.nodes  # noqa: F401 - populate built-ins
from spectra_sherpa.app.lib.fitted_state import LinearRegressionExtract
from spectra_sherpa.app.lib.sherpa_dataset import SampleAxis, SherpaDataset, SpectralAxis, TargetContext
from spectra_sherpa.app.services.dag.node_base import node_registry
from spectra_sherpa.app.services.dag.nodes.modeling.regression_nodes import (
    LinearRegressionNode,
    _canonical_linear_regression_parameters,
    _linear_regression_execute,
)
from spectra_sherpa.execution_contract_vocabulary import LifecycleKind, ManagedOptimizationEligibility, RuntimeFamily
from tests.performance_contract import PerformanceCeiling


def _dataset(*, targets: int = 1) -> tuple[SherpaDataset, np.ndarray]:
    rng = np.random.default_rng(1207)
    matrix = rng.normal(size=(36, 5))
    coefficients = np.array(
        [[1.8, -0.7, 0.0, 0.4, 1.1], [-0.3, 0.2, 1.4, 0.0, -0.8]],
        dtype=np.float64,
    )[:targets]
    response = matrix @ coefficients.T + np.arange(targets, dtype=np.float64) + 0.25
    if targets == 1:
        response = response[:, 0]
    names = [f"property-{index + 1}" for index in range(targets)]
    dataset = SherpaDataset(
        X=matrix,
        feature_axis=SpectralAxis(
            values=np.linspace(900.0, 1700.0, matrix.shape[1]),
            labels=[f"band-{index}" for index in range(matrix.shape[1])],
            units="cm-1",
        ),
        sample_axis=SampleAxis(labels=[f"sample-{index}" for index in range(matrix.shape[0])]),
        target=response,
        target_context=TargetContext(target_type="continuous", target_names=names),
    )
    return dataset, response


def test_linear_regression_has_one_exact_local_fitted_model_contract() -> None:
    contract = node_registry.get_metadata("model.linear_regression").resolved_execution_contract()
    assert contract is not None
    assert contract.payload["operation_id"] == "model.linear_regression"
    assert contract.payload["runtime_family"] == RuntimeFamily.SHERPA_NATIVE.value
    assert contract.payload["lifecycle_kind"] == LifecycleKind.FITTED_MODEL.value
    assert contract.payload["managed_optimization_eligibility"] == (ManagedOptimizationEligibility.LOCAL.value,)
    assert contract.payload["target_access"] == "fit_only"
    assert contract.payload["fitted_state_serializer"] == "spectrasherpa.model-artifact.linear-regression/1"
    assert {port["name"]: port["type_ref"] for port in contract.payload["semantic_outputs"]} == {
        "fitted_state": "spectrasherpa://types/RegressionModel/1.0",
        "population": "spectrasherpa://types/RegressionPopulation/1.0",
        "model": "spectrasherpa://types/RegressionModel/1.0",
        "predictions": "spectrasherpa://types/TargetMatrix/1.0",
        "residuals": "spectrasherpa://types/TargetMatrix/1.0",
    }
    assert any("rchemo/html/lmr.html" in item for item in contract.payload["citations"])
    component_ids = {item["component_id"] for item in contract.payload["implementation_components"]}
    assert "spectra_sherpa.app.lib.fitted_state" in component_ids
    assert "spectra_sherpa.app.services.dag.nodes.modeling._artifact_builder" in component_ids


def test_linear_regression_parameter_contract_is_closed() -> None:
    assert _canonical_linear_regression_parameters({"fit_intercept": True}) == {"fit_intercept": True}
    for invalid in ({}, {"fit_intercept": 1}, {"fit_intercept": True, "normalize": True}):
        with pytest.raises(ValueError):
            _canonical_linear_regression_parameters(invalid)


def test_linear_regression_matches_independent_lstsq_oracle() -> None:
    dataset, response = _dataset(targets=2)
    outputs = _linear_regression_execute(
        dataset,
        response,
        node_id="linear",
        parameters={"fit_intercept": True},
    )
    augmented = np.column_stack([np.ones(dataset.shape[0]), np.asarray(dataset.X)])
    oracle, *_ = np.linalg.lstsq(augmented, response, rcond=None)
    expected = augmented @ oracle

    np.testing.assert_allclose(outputs["predictions"], expected, rtol=1e-12, atol=1e-12)
    np.testing.assert_allclose(outputs["intercept"], oracle[0], rtol=1e-12, atol=1e-12)
    np.testing.assert_allclose(outputs["coef"], oracle[1:].T, rtol=1e-12, atol=1e-12)
    assert outputs["metadata"]["evidence_scope"] == "training_fit_only_not_predictive_validation"


def test_linear_regression_has_a_representative_absolute_performance_ceiling() -> None:
    rng = np.random.default_rng(503)
    matrix = rng.normal(size=(240, 400))
    response = matrix @ rng.normal(size=400) + rng.normal(scale=0.01, size=240)
    dataset = SherpaDataset(
        X=matrix,
        feature_axis=SpectralAxis(values=np.linspace(900.0, 1700.0, matrix.shape[1]), units="cm-1"),
        sample_axis=SampleAxis(labels=[f"sample-{index}" for index in range(matrix.shape[0])]),
        target=response,
        target_context=TargetContext(target_type="continuous", target_names=["response"]),
    )

    with PerformanceCeiling("model.linear_regression", "240x400-single-target-fit", 5.0).measure():
        outputs = _linear_regression_execute(
            dataset,
            response,
            node_id="linear",
            parameters={"fit_intercept": True},
        )

    assert np.asarray(outputs["predictions"]).shape == (240, 1)


def test_linear_regression_through_origin_matches_lstsq_oracle() -> None:
    dataset, response = _dataset()
    outputs = _linear_regression_execute(
        dataset,
        response,
        node_id="linear",
        parameters={"fit_intercept": False},
    )
    oracle, *_ = np.linalg.lstsq(np.asarray(dataset.X), response, rcond=None)
    np.testing.assert_allclose(
        outputs["predictions"],
        (np.asarray(dataset.X) @ oracle).reshape(-1, 1),
        rtol=1e-12,
        atol=1e-12,
    )
    assert outputs["intercept"] == 0.0


@pytest.mark.asyncio
async def test_linear_regression_live_and_generated_python_share_one_operation() -> None:
    dataset, response = _dataset(targets=2)
    node = LinearRegressionNode("linear", {"fit_intercept": True})
    live = await node.execute(X=dataset, y=response)
    namespace = {"dataset": dataset, "response": response, "results": {}}
    exec("\n".join(node.generate_python({"X": "dataset", "y": "response"}, indent="")), namespace)  # noqa: S102
    generated = namespace["results"]["linear"]

    np.testing.assert_allclose(generated["predictions"], live["predictions"], rtol=0.0, atol=0.0)
    np.testing.assert_allclose(generated["residuals"], live["residuals"], rtol=0.0, atol=0.0)
    np.testing.assert_allclose(generated["coef"], live["coef"], rtol=0.0, atol=0.0)
    assert generated["metadata"] == live["metadata"]


def test_linear_regression_fitted_state_replays_exact_multi_target_predictions() -> None:
    dataset, response = _dataset(targets=2)
    node = LinearRegressionNode("linear", {"fit_intercept": True})
    state = node.fit_fitted_state(dataset, response)

    replayed = node.apply_fitted_state(dataset, state)
    expected = _linear_regression_execute(
        dataset,
        response,
        node_id="linear",
        parameters={"fit_intercept": True},
    )["predictions"]

    assert state["serializer"] == "spectrasherpa.model-artifact.linear-regression/1"
    np.testing.assert_allclose(replayed, expected, rtol=1e-12, atol=1e-12)


def test_linear_regression_fitted_state_fails_closed_on_schema_and_feature_drift() -> None:
    dataset, response = _dataset()
    node = LinearRegressionNode("linear", {"fit_intercept": True})
    state = node.fit_fitted_state(dataset, response)

    with pytest.raises(ValueError, match="closed schema"):
        node.apply_fitted_state(dataset, {**state, "unexpected": True})
    with pytest.raises(ValueError, match="unsupported serializer"):
        node.apply_fitted_state(dataset, {**state, "serializer": "prototype"})
    with pytest.raises(ValueError, match="feature count"):
        node.apply_fitted_state(SherpaDataset(X=np.asarray(dataset.X)[:, :-1]), state)


def test_linear_regression_does_not_mutate_inputs() -> None:
    dataset, response = _dataset(targets=2)
    matrix_before = np.array(dataset.X, copy=True)
    response_before = np.array(response, copy=True)
    context_before = copy.deepcopy(dataset.target_context)
    _linear_regression_execute(
        dataset,
        response,
        node_id="linear",
        parameters={"fit_intercept": True},
    )
    np.testing.assert_array_equal(dataset.X, matrix_before)
    np.testing.assert_array_equal(response, response_before)
    assert dataset.target_context == context_before


def test_linear_regression_does_not_enrich_caller_target_context() -> None:
    dataset, response = _dataset()
    dataset.target_context = TargetContext(target_type="continuous")
    context_before = dataset.target_context.model_copy(deep=True)
    _linear_regression_execute(
        dataset,
        response,
        node_id="linear",
        parameters={"fit_intercept": True},
    )
    assert dataset.target_context == context_before


def test_linear_regression_rejects_numeric_categorical_response() -> None:
    dataset, _ = _dataset()
    response = SherpaDataset(
        X=np.arange(dataset.shape[0], dtype=np.float64).reshape(-1, 1) % 2,
        sample_axis=dataset.sample_axis.copy(),
        target_context=TargetContext(
            target_type="categorical",
            target_names=["class"],
            class_names=["A", "B"],
        ),
    )
    with pytest.raises(ValueError, match="requires continuous targets"):
        _linear_regression_execute(
            dataset,
            response,
            node_id="linear",
            parameters={"fit_intercept": True},
        )


def test_connected_response_identity_controls_outputs_and_artifact() -> None:
    dataset, response_values = _dataset(targets=2)
    dataset.target_context = TargetContext(target_type="continuous", target_names=["stale-X-name"])
    response = SherpaDataset(
        X=response_values,
        sample_axis=dataset.sample_axis.copy(),
        target_context=TargetContext(
            target_type="continuous",
            target_names=["moisture", "protein"],
            target_units="percent",
        ),
    )

    outputs = _linear_regression_execute(
        dataset,
        response,
        node_id="linear",
        parameters={"fit_intercept": True},
    )
    assert outputs["metadata"]["target_names"] == ["moisture", "protein"]
    assert outputs["metadata"]["target_units"] == "percent"
    artifact = outputs["_model_artifact"]["metadata"]
    assert artifact["target_mode"] == "multi"
    assert artifact["target_names"] == ["moisture", "protein"]
    assert artifact["target_type"] == "continuous"
    assert artifact["target_units"] == "percent"


def test_explicit_unlabeled_response_does_not_inherit_stale_predictor_identity() -> None:
    dataset, response = _dataset()
    dataset.target_context = TargetContext(
        target_type="continuous",
        target_names=["stale-protein"],
        target_units="percent",
    )

    outputs = _linear_regression_execute(
        dataset,
        np.asarray(response),
        node_id="linear",
        parameters={"fit_intercept": True},
    )
    artifact = outputs["_model_artifact"]["metadata"]
    assert artifact["target_names"] == ["Target 1"]
    assert artifact["selected_target"] == "Target 1"
    assert "target_units" not in artifact


@pytest.mark.parametrize(
    ("targets", "fit_intercept"),
    [(1, True), (1, False), (2, True), (2, False)],
)
def test_linear_regression_artifact_replays_exact_shape_values_and_scope(
    targets: int,
    fit_intercept: bool,
) -> None:
    dataset, _response = _dataset(targets=targets)
    outputs = _linear_regression_execute(
        dataset,
        None,
        node_id="linear",
        parameters={"fit_intercept": fit_intercept},
    )
    artifact = outputs["_model_artifact"]
    replay = LinearRegressionExtract.from_artifact(artifact["metadata"], artifact["arrays"])
    replayed = replay.predict(np.asarray(dataset.X))
    live = np.asarray(outputs["predictions"])

    assert replayed.shape == live.shape
    np.testing.assert_allclose(replayed, live, rtol=1e-12, atol=1e-12)
    assert artifact["metadata"]["fit_intercept"] is fit_intercept
    assert artifact["metadata"]["fitted_parameters"] == {"fit_intercept": fit_intercept}
    assert artifact["metadata"]["metrics_scope"] == "training_fit_only_not_predictive_validation"
    assert artifact["metadata"]["metrics"]["scope"] == "training_fit_only_not_predictive_validation"
    assert [item["target_name"] for item in artifact["metadata"]["metrics"]["per_target"]] == [
        f"property-{index + 1}" for index in range(targets)
    ]
    if targets > 1 and not fit_intercept:
        assert outputs["intercept"] == [0.0] * targets
        assert artifact["arrays"]["intercept"].tolist() == [0.0] * targets


@pytest.mark.parametrize(
    ("metadata_patch", "array_patch", "message"),
    [
        ({"fit_intercept": False}, {"intercept": np.array([1.0, 0.0])}, "zero intercepts"),
        ({}, {"intercept": np.array([0.0])}, "target count"),
        ({}, {"coef": np.ones((1, 2, 3))}, "coefficients"),
        ({}, {"coef": np.array([[1.0, np.nan], [2.0, 3.0]])}, "coefficients"),
        ({}, {"intercept": np.array([0.0, np.inf])}, "intercept"),
    ],
)
def test_linear_regression_artifact_rejects_contradictory_or_malformed_state(
    metadata_patch: dict[str, object],
    array_patch: dict[str, np.ndarray],
    message: str,
) -> None:
    dataset, _response = _dataset(targets=2)
    artifact = _linear_regression_execute(
        dataset,
        None,
        node_id="linear",
        parameters={"fit_intercept": True},
    )["_model_artifact"]
    metadata = dict(artifact["metadata"])
    arrays = {name: np.array(values, copy=True) for name, values in artifact["arrays"].items()}
    metadata.update(metadata_patch)
    arrays.update(array_patch)
    with pytest.raises(ValueError, match=message):
        LinearRegressionExtract.from_artifact(metadata, arrays)


def test_single_response_artifact_is_explicitly_single() -> None:
    dataset, _response = _dataset()
    outputs = _linear_regression_execute(
        dataset,
        None,
        node_id="linear",
        parameters={"fit_intercept": True},
    )
    artifact = outputs["_model_artifact"]["metadata"]
    assert artifact["target_mode"] == "single"
    assert artifact["selected_target"] == "property-1"
    assert artifact["target_names"] == ["property-1"]


def test_linear_regression_rejects_nonfinite_training_values() -> None:
    dataset, response = _dataset()
    dataset.X[0, 0] = np.inf
    with pytest.raises(ValueError):
        _linear_regression_execute(
            dataset,
            response,
            node_id="linear",
            parameters={"fit_intercept": True},
        )
