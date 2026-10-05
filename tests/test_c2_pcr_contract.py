"""C2h canonical Principal Components Regression scientific and contract proofs."""

from __future__ import annotations

import copy

import numpy as np
import pytest

import spectra_sherpa.app.services.dag.nodes  # noqa: F401 - populate built-ins
from spectra_sherpa.app.lib.fitted_state import PCRExtract
from spectra_sherpa.app.lib.sherpa_dataset import SampleAxis, SherpaDataset, SpectralAxis, TargetContext
from spectra_sherpa.app.services.dag.node_base import node_registry
from spectra_sherpa.app.services.dag.nodes.modeling.regression_nodes import (
    PCRNode,
    _canonical_pcr_parameters,
    _pcr_execute,
)
from spectra_sherpa.execution_contract_vocabulary import LifecycleKind, ManagedOptimizationEligibility, RuntimeFamily
from tests.performance_contract import PerformanceCeiling


def _dataset(*, targets: int = 2) -> tuple[SherpaDataset, np.ndarray]:
    rng = np.random.default_rng(1965)
    latent = rng.normal(size=(44, 4))
    mixing = rng.normal(size=(4, 12))
    matrix = latent @ mixing + rng.normal(scale=0.02, size=(44, 12))
    response = np.column_stack(
        [
            1.4 * latent[:, 0] - 0.6 * latent[:, 2] + 0.2,
            -0.8 * latent[:, 1] + 1.1 * latent[:, 3] - 0.4,
        ]
    )[:, :targets]
    if targets == 1:
        response = response[:, 0]
    names = [f"property-{index + 1}" for index in range(targets)]
    return (
        SherpaDataset(
            X=matrix,
            feature_axis=SpectralAxis(
                values=np.linspace(900.0, 1800.0, matrix.shape[1]),
                labels=[f"band-{index}" for index in range(matrix.shape[1])],
                units="cm-1",
            ),
            sample_axis=SampleAxis(labels=[f"sample-{index}" for index in range(matrix.shape[0])]),
            target=response,
            target_context=TargetContext(target_type="continuous", target_names=names),
        ),
        response,
    )


def _independent_pcr_predictions(
    matrix: np.ndarray, response: np.ndarray, *, n_components: int, scale: bool
) -> np.ndarray:
    predictors = np.asarray(matrix, dtype=np.float64)
    if scale:
        predictors = (predictors - predictors.mean(axis=0)) / predictors.std(axis=0, ddof=0)
    centered = predictors - predictors.mean(axis=0)
    _, _, right_vectors = np.linalg.svd(centered, full_matrices=False)
    scores = centered @ right_vectors[:n_components].T
    design = np.column_stack([np.ones(scores.shape[0]), scores])
    coefficients, *_ = np.linalg.lstsq(design, response, rcond=None)
    return design @ coefficients


def test_pcr_has_one_exact_local_fitted_model_contract() -> None:
    contract = node_registry.get_metadata("model.pcr").resolved_execution_contract()
    assert contract is not None
    assert contract.payload["operation_id"] == "model.pcr"
    assert contract.payload["runtime_family"] == RuntimeFamily.SHERPA_NATIVE.value
    assert contract.payload["lifecycle_kind"] == LifecycleKind.FITTED_MODEL.value
    assert contract.payload["managed_optimization_eligibility"] == (ManagedOptimizationEligibility.LOCAL.value,)
    assert contract.payload["target_access"] == "fit_only"
    assert contract.payload["fitted_state_serializer"] == "spectrasherpa.model-artifact.pcr/1"
    assert any("10.1080/01621459.1965.10480787" in item for item in contract.payload["citations"])


def test_pcr_parameter_contract_is_closed() -> None:
    assert _canonical_pcr_parameters({"n_components": 3, "scale": True}) == {
        "n_components": 3,
        "scale": True,
    }
    for invalid in (
        {},
        {"n_components": 0, "scale": True},
        {"n_components": 2.5, "scale": True},
        {"n_components": True, "scale": True},
        {"n_components": 2, "scale": 1},
        {"n_components": 2, "scale": True, "whiten": True},
    ):
        with pytest.raises(ValueError):
            _canonical_pcr_parameters(invalid)


@pytest.mark.parametrize("scale", [False, True])
def test_pcr_matches_independent_svd_and_lstsq_oracle(scale: bool) -> None:
    dataset, response = _dataset(targets=2)
    result = _pcr_execute(
        dataset,
        response,
        node_id="pcr",
        parameters={"n_components": 3, "scale": scale},
    )
    expected = _independent_pcr_predictions(np.asarray(dataset.X), response, n_components=3, scale=scale)

    np.testing.assert_allclose(result.outputs["y_pred"], expected, rtol=1e-11, atol=1e-11)
    assert result.diagnostics["evidence_scope"] == "training_fit_only_not_predictive_validation"
    assert result.outputs["scores"].meta["evidence_scope"] == "training_fit_only_not_predictive_validation"


def test_pcr_artifact_replays_training_predictions_for_multiple_targets() -> None:
    dataset, response = _dataset(targets=2)
    result = _pcr_execute(
        dataset,
        response,
        node_id="pcr",
        parameters={"n_components": 4, "scale": True},
    )
    artifact = result.outputs["_model_artifact"]
    replay = PCRExtract.from_artifact(artifact["metadata"], artifact["arrays"])

    np.testing.assert_allclose(replay.predict(np.asarray(dataset.X)), result.outputs["y_pred"], atol=1e-12)
    assert artifact["metadata"]["fitted_parameters"] == {"n_components": 4, "scale": True}
    assert artifact["metadata"]["metrics_scope"] == "training_fit_only_not_predictive_validation"
    assert artifact["metadata"]["metrics"]["scope"] == "training_fit_only_not_predictive_validation"
    assert [item["target_name"] for item in artifact["metadata"]["metrics"]["per_target"]] == [
        "Target 1",
        "Target 2",
    ]


def test_pcr_artifact_rejects_dimension_and_scaler_contradictions() -> None:
    dataset, response = _dataset(targets=2)
    artifact = _pcr_execute(
        dataset,
        response,
        node_id="pcr",
        parameters={"n_components": 3, "scale": True},
    ).outputs["_model_artifact"]
    cases = (
        ({"model_type": "other"}, {}, "identity"),
        ({"serializer": "other/1"}, {}, "identity"),
        ({"fitted_parameters": {"n_components": 1, "scale": False}}, {}, "contradict"),
        ({"target_count": 3}, {}, "dimensions"),
        (
            {"scale": False, "fitted_parameters": {"n_components": 3, "scale": False}},
            {},
            "closed serializer",
        ),
        ({}, {"pca_mean": np.zeros(2)}, "dimensions"),
        ({}, {"reg_coef": np.full((2, 3), np.nan)}, "values"),
        ({}, {"scaler_scale": np.zeros(12)}, "scaler"),
        ({}, {"undeclared_state": np.zeros(1)}, "closed serializer"),
    )
    for metadata_patch, array_patch, message in cases:
        metadata = dict(artifact["metadata"])
        arrays = {name: np.array(values, copy=True) for name, values in artifact["arrays"].items()}
        metadata.update(metadata_patch)
        arrays.update(array_patch)
        with pytest.raises(ValueError, match=message):
            PCRExtract.from_artifact(metadata, arrays)


def test_pcr_fitted_state_is_closed_and_replays_single_and_multiple_targets() -> None:
    for targets in (1, 2):
        dataset, response = _dataset(targets=targets)
        node = PCRNode("pcr", {"n_components": 3, "scale": True})
        state = node.fit_fitted_state(dataset, response)
        replayed = node.apply_fitted_state(dataset, state)
        live = node._execute_sync(dataset, response).outputs["y_pred"]
        assert replayed.shape == np.asarray(live).shape
        np.testing.assert_allclose(replayed, live, rtol=1e-12, atol=1e-12)

        forged = dict(state)
        forged["unexpected"] = 1
        with pytest.raises(ValueError, match="closed serializer"):
            node.apply_fitted_state(dataset, forged)


def test_pcr_explicit_response_identity_is_authoritative_and_continuous_only() -> None:
    dataset, response = _dataset(targets=1)
    dataset.target_context = TargetContext(
        target_type="continuous",
        target_names=["stale-property"],
        target_units="percent",
    )
    result = _pcr_execute(
        dataset,
        np.asarray(response),
        node_id="pcr",
        parameters={"n_components": 3, "scale": True},
    )
    metadata = result.outputs["_model_artifact"]["metadata"]
    assert metadata["target_names"] == ["Target 1"]
    assert "target_units" not in metadata

    categorical = SherpaDataset(
        X=np.asarray(response).reshape(-1, 1),
        sample_axis=dataset.sample_axis.copy(),
        target_context=TargetContext(target_type="categorical", target_names=["class"]),
    )
    with pytest.raises(ValueError, match="continuous"):
        _pcr_execute(
            dataset,
            categorical,
            node_id="pcr",
            parameters={"n_components": 3, "scale": True},
        )


def test_pcr_wide_matrix_uses_exact_deterministic_full_svd() -> None:
    rng = np.random.default_rng(1972)
    matrix = rng.normal(size=(40, 700))
    response = matrix[:, :4] @ np.array([1.0, -0.5, 0.25, 0.1])
    first = _pcr_execute(
        matrix,
        response,
        node_id="pcr",
        parameters={"n_components": 6, "scale": True},
    )
    second = _pcr_execute(
        matrix,
        response,
        node_id="pcr",
        parameters={"n_components": 6, "scale": True},
    )
    assert first.outputs["model"].named_steps["pca"].svd_solver == "full"
    np.testing.assert_array_equal(first.outputs["scores"].data, second.outputs["scores"].data)
    np.testing.assert_array_equal(first.outputs["y_pred"], second.outputs["y_pred"])


@pytest.mark.asyncio
async def test_pcr_live_and_generated_python_share_one_operation() -> None:
    dataset, response = _dataset(targets=2)
    node = PCRNode("pcr", {"n_components": 3, "scale": True})
    live = await node.execute(X=dataset, y=response)
    namespace = {"dataset": dataset, "response": response, "results": {}}
    exec("\n".join(node.generate_python({"X": "dataset", "y": "response"}, indent="")), namespace)  # noqa: S102
    generated = namespace["results"]["pcr"]

    np.testing.assert_allclose(generated["y_pred"], live.outputs["y_pred"], rtol=0.0, atol=0.0)
    np.testing.assert_allclose(generated["scores"].data, live.outputs["scores"].data, rtol=0.0, atol=0.0)
    np.testing.assert_allclose(generated["loadings"].data, live.outputs["loadings"].data, rtol=0.0, atol=0.0)
    assert generated["scores"].meta == live.outputs["scores"].meta
    for name, values in live.outputs["_model_artifact"]["arrays"].items():
        np.testing.assert_allclose(generated["_model_artifact"]["arrays"][name], values, rtol=0.0, atol=0.0)


def test_pcr_does_not_mutate_caller_data_target_or_context() -> None:
    dataset, response = _dataset(targets=2)
    matrix_before = np.array(dataset.X, copy=True)
    response_before = np.array(response, copy=True)
    context_before = copy.deepcopy(dataset.target_context)

    _pcr_execute(dataset, response, node_id="pcr", parameters={"n_components": 3, "scale": True})

    np.testing.assert_array_equal(dataset.X, matrix_before)
    np.testing.assert_array_equal(response, response_before)
    assert dataset.target_context == context_before


def test_pcr_rejects_nonfinite_and_unsupported_component_count() -> None:
    dataset, response = _dataset(targets=1)
    dataset.X[0, 0] = np.inf
    with pytest.raises(ValueError, match="infinity|finite"):
        _pcr_execute(dataset, response, node_id="pcr", parameters={"n_components": 3, "scale": True})

    dataset, response = _dataset(targets=1)
    with pytest.raises(ValueError, match="n_components must be <="):
        _pcr_execute(dataset, response, node_id="pcr", parameters={"n_components": 50, "scale": True})


def test_pcr_fixed_local_workload_stays_inside_reviewed_ceiling() -> None:
    rng = np.random.default_rng(443)
    matrix = rng.normal(size=(120, 400))
    response = matrix[:, :6] @ np.array([1.0, -0.7, 0.5, 0.3, -0.2, 0.1])

    with PerformanceCeiling("model.pcr", "120x400-six-components", 5.0).measure():
        _pcr_execute(
            matrix,
            response,
            node_id="pcr",
            parameters={"n_components": 6, "scale": True},
        )
