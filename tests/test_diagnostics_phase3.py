"""Canonical PCA outlier-diagnostics contract and parity proofs."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
import yaml
from scipy.stats import f
from sklearn.decomposition import PCA

from spectra_sherpa.app.lib.pca import PCAExtract
from spectra_sherpa.app.lib.sherpa_dataset import SampleAxis, SherpaDataset
from spectra_sherpa.app.services.dag.nodes.diagnostics import (
    OutlierDetectionNode,
    _canonical_outlier_parameters,
    _outlier_dispatch,
)
from spectra_sherpa.app.services.dag.nodes.modeling.pca_nodes import (
    PCANode,
    _pca_diagnostic_state,
    _pca_state_from_extract,
    reconstruct_pca_fitted_state,
)
from spectra_sherpa.app.services.dag.rank_projection import input_axis_identity


@pytest.fixture
def pca_state() -> dict[str, object]:
    rng = np.random.default_rng(42)
    matrix = rng.normal(size=(30, 8))
    matrix[-1] += 7.0
    model = PCA(n_components=3).fit(matrix)
    scores = model.transform(matrix)
    dataset = SherpaDataset(matrix)
    fitted_state = _pca_state_from_extract(
        PCAExtract(
            scores=scores,
            loadings=model.components_.copy(),
            explained_variance_ratio=model.explained_variance_ratio_.copy(),
            explained_variance=model.explained_variance_.copy(),
            n_components=3,
            mean=model.mean_.copy(),
        ),
        dataset,
        input_shape=tuple(dataset.shape),
        input_axis_identity_sha256=input_axis_identity(dataset),
        rank_projection_strategy="none",
    )
    return _pca_diagnostic_state(
        model=fitted_state,
        scores=scores,
        eigenvalues=model.explained_variance_,
        input_data=matrix,
    )


def test_outlier_statistics_use_true_eigenvalues_and_declared_limits(pca_state):
    outputs, diagnostics = _outlier_dispatch(pca_state, confidence_level=0.95)
    scores = np.asarray(pca_state["scores"])
    eigenvalues = np.asarray(pca_state["eigenvalues"])
    expected_t2 = np.sum(scores**2 / eigenvalues, axis=1)
    n_observations, n_components = scores.shape
    expected_limit = (
        n_components
        * (n_observations - 1)
        * (n_observations + 1)
        / (n_observations * (n_observations - n_components))
        * f.ppf(0.95, n_components, n_observations - n_components)
    )

    np.testing.assert_allclose(outputs["T2"], expected_t2, rtol=0.0, atol=1e-12)
    assert outputs["T2_limit"] == pytest.approx(expected_limit)
    assert diagnostics["t2_limit_method"] == "nomikos_macgregor_f_distribution"
    assert diagnostics["q_limit_method"] == "empirical_calibration_quantile"
    assert diagnostics["q_residual_space"] == "preprocessed_model_space"


@pytest.mark.asyncio
async def test_autoscaled_pca_q_residuals_use_preprocessed_model_space():
    rng = np.random.default_rng(20260909)
    matrix = rng.normal(size=(48, 6)) * np.asarray([1.0, 3.0, 25.0, 200.0, 1500.0, 9000.0])
    result = await PCANode(
        "autoscaled-pca",
        {"n_components": "2", "standardized": True, "scaled": False},
    ).execute(input_data=matrix)
    state = result.outputs["diagnostic_state"]
    fitted_state = state["model"]
    arrays = fitted_state["arrays"]
    scores = np.asarray(state["scores"].data, dtype=np.float64)
    fitted_input = (matrix - np.asarray(arrays["mean"])) / np.asarray(arrays["scale"])
    fitted_input -= np.asarray(arrays["center"])
    fitted_reconstruction = scores @ np.asarray(arrays["loadings"])
    expected_q = np.sum((fitted_input - fitted_reconstruction) ** 2, axis=1)

    raw_reconstruction = reconstruct_pca_fitted_state(scores, fitted_state)
    raw_space_q = np.sum((matrix - raw_reconstruction) ** 2, axis=1)
    outputs, diagnostics = _outlier_dispatch(state, confidence_level=0.95)

    np.testing.assert_allclose(state["Q"], expected_q, rtol=1e-12, atol=1e-12)
    np.testing.assert_allclose(outputs["Q"], expected_q, rtol=1e-12, atol=1e-12)
    assert not np.allclose(expected_q, raw_space_q)
    assert outputs["Q_limit"] == pytest.approx(np.quantile(expected_q, 0.95))
    assert diagnostics["q_residual_space"] == "preprocessed_model_space"


def test_outlier_diagnostics_retain_sample_identity(pca_state):
    score_values = np.asarray(pca_state["scores"])
    labels = [f"Lavender sample {index + 1}" for index in range(score_values.shape[0])]
    pca_state["scores"] = SherpaDataset(
        X=score_values,
        sample_axis=SampleAxis(labels=labels, title="Sample"),
        data_role="X_features",
    )

    outputs, diagnostics = _outlier_dispatch(pca_state, confidence_level=0.95)

    assert outputs["sample_labels"] == labels
    assert outputs["outlier_sample_labels"] == [labels[index] for index in outputs["outlier_indices"]]
    assert diagnostics["sample_labels"] == labels
    assert diagnostics["outlier_sample_labels"] == [labels[index] for index in outputs["outlier_indices"]]


@pytest.mark.asyncio
async def test_outlier_generated_python_is_identical_to_live_execution(pca_state):
    node = OutlierDetectionNode("outliers", {"confidence_level": 0.95})
    live = await node.execute(pca_model=pca_state)
    namespace = {"state": pca_state, "results": {}}
    exec("\n".join(node.generate_python({"default": "state"}, indent="")), namespace)
    generated = namespace["results"]["outliers"]

    for field in ("T2", "Q", "flags", "outlier_indices"):
        np.testing.assert_array_equal(generated[field], live.outputs[field])
    assert generated["T2_limit"] == live.outputs["T2_limit"]
    assert generated["Q_limit"] == live.outputs["Q_limit"]
    assert generated["evaluation"].evaluation_id == live.outputs["evaluation"].evaluation_id


@pytest.mark.asyncio
async def test_real_pca_output_drives_real_outlier_consumer():
    rng = np.random.default_rng(731)
    matrix = rng.normal(size=(24, 12))
    matrix[-1] += 5.0

    pca_result = await PCANode("pca", {"n_components": "3"}).execute(input_data=matrix)
    state = pca_result.outputs["diagnostic_state"]
    outlier_result = await OutlierDetectionNode("outliers", {"confidence_level": 0.95}).execute(pca_model=state)

    assert state["n_observations"] == matrix.shape[0]
    assert state["n_components"] == 3
    assert len(state["eigenvalues"]) == 3
    assert len(outlier_result.outputs["T2"]) == matrix.shape[0]
    assert len(outlier_result.outputs["Q"]) == matrix.shape[0]
    assert np.isfinite(outlier_result.outputs["T2_limit"])
    assert np.isfinite(outlier_result.outputs["Q_limit"])
    assert outlier_result.diagnostics["q_limit_method"] == "empirical_calibration_quantile"
    assert set(pca_result.diagnostics) == {
        "explained_variance_ratio",
        "cumulative_variance",
        "n_components_95pct",
    }
    for duplicated_field in (
        "hotelling_t2",
        "q_residuals",
        "t2_critical_95",
        "q_critical_95",
    ):
        assert duplicated_field not in PCANode.metadata.diagnostics
        assert duplicated_field not in pca_result.diagnostics


def test_outlier_contract_is_local_evaluator_with_closed_parameters():
    contract = OutlierDetectionNode.metadata.resolved_execution_contract()
    assert contract is not None
    assert contract.payload["lifecycle_kind"] == "evaluator"
    assert contract.payload["managed_optimization_eligibility"] == ("local",)
    assert contract.payload["target_access"] == "none"
    assert _canonical_outlier_parameters({}) == {"confidence_level": 0.95}
    with pytest.raises(ValueError, match="accepts only"):
        _canonical_outlier_parameters({"confidence_level": 0.95, "fallback": True})
    for invalid in (True, np.nan, 0.79, 0.9991, 1.0):
        with pytest.raises(ValueError, match="confidence_level"):
            _canonical_outlier_parameters({"confidence_level": invalid})


@pytest.mark.parametrize(
    "mutation, message",
    [
        (lambda state: state.pop("eigenvalues"), "eigenvalues"),
        (lambda state: state.update(eigenvalues=[1.0]), "one finite positive value"),
        (lambda state: state["_internal"].pop("input_data"), "fitted-space input data"),
    ],
)
def test_outlier_rejects_incomplete_or_inconsistent_pca_state(pca_state, mutation, message):
    mutation(pca_state)
    with pytest.raises(ValueError, match=message):
        _outlier_dispatch(pca_state, confidence_level=0.95)


def test_pca_template_contains_real_typed_outlier_consumer():
    template_path = Path(__file__).resolve().parents[1] / "src/spectra_sherpa/data/templates/pca.yaml"
    document = yaml.safe_load(template_path.read_text(encoding="utf-8"))
    nodes = {node["node_id"]: node for node in document["template_data"]["nodes"]}
    assert nodes["outliers_1"]["node_type"] == "diagnostics.outliers"
    assert {
        "from_node_id": "model_1",
        "to_node_id": "outliers_1",
        "from_output": "diagnostic_state",
        "to_input": "default",
    } in document["template_data"]["edges"]
