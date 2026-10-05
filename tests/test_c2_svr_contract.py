"""C2h canonical epsilon-SVR scientific and contract proofs."""

from __future__ import annotations

import copy

import numpy as np
import pytest
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.svm import SVR

import spectra_sherpa.app.services.dag.nodes  # noqa: F401 - populate built-ins
from spectra_sherpa.app.lib.fitted_state import SVRExtract
from spectra_sherpa.app.lib.sherpa_dataset import SampleAxis, SherpaDataset, SpectralAxis, TargetContext
from spectra_sherpa.app.services.dag.node_base import node_registry
from spectra_sherpa.app.services.dag.nodes.modeling.regression_nodes import (
    SVRNode,
    _canonical_svr_parameters,
    _svr_execute,
)
from spectra_sherpa.execution_contract_vocabulary import LifecycleKind, ManagedOptimizationEligibility, RuntimeFamily
from tests.performance_contract import PerformanceCeiling


def _dataset(*, targets: int = 2) -> tuple[SherpaDataset, np.ndarray]:
    rng = np.random.default_rng(1997)
    matrix = rng.normal(size=(48, 8))
    response = np.column_stack(
        [
            np.sin(matrix[:, 0]) + 0.6 * matrix[:, 1] - 0.2 * matrix[:, 2],
            matrix[:, 3] ** 2 - 0.4 * matrix[:, 4] + 0.1 * matrix[:, 5],
        ]
    )[:, :targets]
    if targets == 1:
        response = response[:, 0]
    names = [f"property-{index + 1}" for index in range(targets)]
    return (
        SherpaDataset(
            X=matrix,
            feature_axis=SpectralAxis(values=np.linspace(900.0, 1800.0, matrix.shape[1]), units="cm-1"),
            sample_axis=SampleAxis(labels=[f"sample-{index}" for index in range(matrix.shape[0])]),
            target=response,
            target_context=TargetContext(target_type="continuous", target_names=names),
        ),
        response,
    )


def _parameters(**overrides: object) -> dict[str, object]:
    values: dict[str, object] = {
        "kernel": "rbf",
        "C": 3.0,
        "epsilon": 0.05,
        "gamma": "scale",
        "degree": 3,
        "coef0": 0.0,
        "target_index": 1,
        "scale": True,
    }
    values.update(overrides)
    return values


def test_svr_has_one_exact_local_fitted_model_contract() -> None:
    contract = node_registry.get_metadata("model.svr").resolved_execution_contract()
    assert contract is not None
    assert contract.payload["operation_id"] == "model.svr"
    assert contract.payload["runtime_family"] == RuntimeFamily.SHERPA_NATIVE.value
    assert contract.payload["lifecycle_kind"] == LifecycleKind.FITTED_MODEL.value
    assert contract.payload["managed_optimization_eligibility"] == (ManagedOptimizationEligibility.LOCAL.value,)
    assert contract.payload["target_access"] == "fit_only"
    assert contract.payload["fitted_state_serializer"] == "spectrasherpa.model-artifact.svr/1"
    assert any("e1071" in item for item in contract.payload["citations"])
    assert any("10.1145/1961189.1961199" in item for item in contract.payload["citations"])


def test_svr_parameter_contract_is_closed() -> None:
    assert _canonical_svr_parameters(_parameters()) == _parameters()
    for invalid in (
        {},
        _parameters(kernel="precomputed"),
        _parameters(C=0),
        _parameters(epsilon=-0.1),
        _parameters(coef0=-1.1),
        _parameters(gamma=0.2),
        _parameters(degree=2.5),
        _parameters(target_index=True),
        _parameters(scale=1),
        {**_parameters(), "shrinking": False},
    ):
        with pytest.raises(ValueError):
            _canonical_svr_parameters(invalid)


@pytest.mark.parametrize("kernel", ["linear", "poly", "rbf", "sigmoid"])
@pytest.mark.parametrize("scale", [False, True])
def test_svr_matches_direct_libsvm_backed_sklearn_oracle(kernel: str, scale: bool) -> None:
    dataset, response = _dataset(targets=2)
    parameters = _parameters(kernel=kernel, scale=scale, target_index=2, coef0=0.2)
    outputs = _svr_execute(dataset, response, node_id="svr", parameters=parameters)

    oracle = Pipeline(
        [
            ("scaler", StandardScaler(with_mean=scale, with_std=scale)),
            (
                "estimator",
                SVR(kernel=kernel, C=3.0, epsilon=0.05, gamma="scale", degree=3, coef0=0.2),
            ),
        ]
    )
    oracle.fit(np.asarray(dataset.X), response[:, 1])
    expected = oracle.predict(np.asarray(dataset.X))

    np.testing.assert_allclose(outputs["predictions"], expected.reshape(-1, 1), rtol=0.0, atol=0.0)
    assert outputs["metadata"]["selected_target_name"] == "Target 2"
    assert outputs["metadata"]["evidence_scope"] == "training_fit_only_not_predictive_validation"
    artifact = outputs["_model_artifact"]["metadata"]
    assert artifact["target_names"] == ["Target 2"]
    assert artifact["selected_target"] == "Target 2"
    assert artifact["metrics_scope"] == "training_fit_only_not_predictive_validation"
    assert artifact["metrics"]["per_target"][0]["target_name"] == "Target 2"


@pytest.mark.parametrize("kernel", ["linear", "poly", "rbf", "sigmoid"])
def test_svr_artifact_replays_training_predictions(kernel: str) -> None:
    dataset, response = _dataset(targets=1)
    outputs = _svr_execute(
        dataset,
        response,
        node_id="svr",
        parameters=_parameters(kernel=kernel, coef0=0.15),
    )
    artifact = outputs["_model_artifact"]
    replay = SVRExtract.from_artifact(artifact["metadata"], artifact["arrays"])
    np.testing.assert_allclose(replay.predict(np.asarray(dataset.X)), outputs["predictions"], atol=1e-12)


def test_svr_fitted_state_replays_and_rejects_open_schema() -> None:
    dataset, response = _dataset(targets=2)
    node = SVRNode("svr", _parameters(target_index=2))
    state = node.fit_fitted_state(dataset, response)
    replayed = node.apply_fitted_state(dataset, state)
    live = _svr_execute(dataset, response, node_id="svr", parameters=_parameters(target_index=2))["predictions"]
    np.testing.assert_allclose(replayed, live, rtol=0.0, atol=1e-12)

    forged = dict(state)
    forged["extra"] = "not admitted"
    with pytest.raises(ValueError, match="closed serializer"):
        node.apply_fitted_state(dataset, forged)


def test_svr_response_identity_is_selected_and_continuous_only() -> None:
    dataset, response = _dataset(targets=2)
    outputs = _svr_execute(dataset, response, node_id="svr", parameters=_parameters(target_index=2))
    assert outputs["_model_artifact"]["metadata"]["target_names"] == ["Target 2"]

    response_dataset = SherpaDataset(
        X=response,
        sample_axis=dataset.sample_axis.copy(),
        target_context=TargetContext(
            target_type="continuous",
            target_names=["moisture", "protein"],
            target_units="percent",
        ),
    )
    labeled = _svr_execute(dataset, response_dataset, node_id="svr", parameters=_parameters(target_index=2))
    artifact = labeled["_model_artifact"]["metadata"]
    assert artifact["target_names"] == ["protein"]
    assert artifact["target_units"] == "percent"

    response_dataset.target_context = TargetContext(target_type="categorical", target_names=["a", "b"])
    with pytest.raises(ValueError, match="continuous"):
        _svr_execute(dataset, response_dataset, node_id="svr", parameters=_parameters(target_index=1))


def test_svr_artifact_rejects_dimension_kernel_and_scaler_contradictions() -> None:
    dataset, response = _dataset(targets=1)
    artifact = _svr_execute(dataset, response, node_id="svr", parameters=_parameters()).get("_model_artifact")
    assert artifact is not None
    cases = (
        ({"model_type": "pcr"}, {}, "model or serializer identity"),
        ({"serializer": "spectrasherpa.model-artifact.svr/2"}, {}, "model or serializer identity"),
        ({"kernel": "precomputed"}, {}, "unsupported kernel"),
        ({"features": 99}, {}, "dimensions"),
        (
            {
                "scale": False,
                "fitted_parameters": {**artifact["metadata"]["fitted_parameters"], "scale": False},
            },
            {},
            "closed serializer schema",
        ),
        (
            {"fitted_parameters": {**artifact["metadata"]["fitted_parameters"], "kernel": "linear"}},
            {},
            "contradict",
        ),
        (
            {"fitted_parameters": {**artifact["metadata"]["fitted_parameters"], "C": "forged"}},
            {},
            "invalid fitted parameters",
        ),
        (
            {"fitted_parameters": {**artifact["metadata"]["fitted_parameters"], "epsilon": np.nan}},
            {},
            "invalid fitted parameters",
        ),
        (
            {"fitted_parameters": {**artifact["metadata"]["fitted_parameters"], "gamma": {"bad": 1}}},
            {},
            "invalid fitted parameters",
        ),
        (
            {"fitted_parameters": {**artifact["metadata"]["fitted_parameters"], "target_index": True}},
            {},
            "invalid fitted parameters",
        ),
        ({}, {"undeclared": np.ones(1)}, "closed serializer schema"),
        ({}, {"dual_coef": np.array([np.nan] * artifact["arrays"]["dual_coef"].size)}, "values"),
        ({}, {"scaler_scale": np.zeros(8)}, "scaler"),
    )
    for metadata_patch, array_patch, message in cases:
        metadata = dict(artifact["metadata"])
        arrays = {name: np.array(values, copy=True) for name, values in artifact["arrays"].items()}
        metadata.update(metadata_patch)
        arrays.update(array_patch)
        with pytest.raises(ValueError, match=message):
            SVRExtract.from_artifact(metadata, arrays)


@pytest.mark.asyncio
async def test_svr_live_and_generated_python_share_one_operation() -> None:
    dataset, response = _dataset(targets=2)
    node = SVRNode("svr", _parameters(target_index=2))
    live = await node.execute(X=dataset, y=response)
    namespace = {"dataset": dataset, "response": response, "results": {}}
    exec("\n".join(node.generate_python({"X": "dataset", "y": "response"}, indent="")), namespace)  # noqa: S102
    generated = namespace["results"]["svr"]

    np.testing.assert_allclose(generated["predictions"], live["predictions"], rtol=0.0, atol=0.0)
    np.testing.assert_allclose(generated["residuals"], live["residuals"], rtol=0.0, atol=0.0)
    assert generated["metadata"] == live["metadata"]


def test_svr_does_not_mutate_inputs_and_drops_only_incomplete_selected_target() -> None:
    dataset, response = _dataset(targets=2)
    response[3, 1] = np.nan
    matrix_before = np.array(dataset.X, copy=True)
    response_before = np.array(response, copy=True)
    context_before = copy.deepcopy(dataset.target_context)

    outputs = _svr_execute(dataset, response, node_id="svr", parameters=_parameters(target_index=2))

    assert len(outputs["predictions"]) == dataset.shape[0] - 1
    np.testing.assert_array_equal(dataset.X, matrix_before)
    np.testing.assert_array_equal(response, response_before)
    assert dataset.target_context == context_before


def test_svr_rejects_nonfinite_predictors_and_out_of_range_target() -> None:
    dataset, response = _dataset(targets=1)
    dataset.X[0, 0] = np.inf
    with pytest.raises(ValueError, match="finite"):
        _svr_execute(dataset, response, node_id="svr", parameters=_parameters())

    dataset, response = _dataset(targets=1)
    with pytest.raises(ValueError, match="out of range"):
        _svr_execute(dataset, response, node_id="svr", parameters=_parameters(target_index=2))


def test_svr_fixed_local_workload_stays_inside_reviewed_ceiling() -> None:
    rng = np.random.default_rng(2718)
    matrix = rng.normal(size=(120, 400))
    response = np.sin(matrix[:, 0]) + 0.5 * matrix[:, 1]
    with PerformanceCeiling("model.svr", "120x400-default", 5.0).measure():
        _svr_execute(matrix, response, node_id="svr", parameters=_parameters())
