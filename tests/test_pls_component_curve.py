"""Numerical and refusal contracts for normal PLS component evidence."""

from __future__ import annotations

import numpy as np
import pytest
from sklearn.cross_decomposition import PLSRegression

from spectra_sherpa.app.lib.sherpa_dataset import SherpaDataset
from spectra_sherpa.app.services.dag.nodes.modeling.component_validation import cv_unavailable_reason
from spectra_sherpa.app.services.dag.nodes.modeling.pls_component_curve import build_pls_component_curve
from spectra_sherpa.app.services.dag.nodes.modeling.pls_core import fit_simpls
from spectra_sherpa.sdk.validate import make_split_plan


def _curve(X: np.ndarray, y: np.ndarray, *, groups: list[str] | None = None, folds: int = 5):
    return build_pls_component_curve(
        X,
        y,
        selected_components=2,
        maximum_components=3,
        scale=True,
        response_names=["Analyte"],
        response_units=["mg/L"],
        groups=groups,
        cv_folds=folds,
        fit_model=fit_simpls,
    )


@pytest.mark.parametrize("grouped", [False, True])
def test_curve_matches_independent_fold_fits(grouped: bool) -> None:
    rng = np.random.default_rng(621)
    X = rng.normal(size=(30, 5))
    y = X @ np.array([2.0, -1.0, 0.5, 0.0, 0.0]) + rng.normal(scale=0.2, size=30)
    groups = [f"specimen-{index // 3}" for index in range(30)] if grouped else None
    curve = _curve(X, y, groups=groups)
    cv = curve["cross_validation"]
    assert cv["status"] == "available"
    assert curve["response_names"] == ["Analyte"]
    assert curve["response_units"] == ["mg/L"]
    assert curve["selected_components"] == 2
    plan = make_split_plan(30, n_splits=5, groups=groups)
    assert cv["split_digest"] == plan.digest
    for components in range(1, 4):
        oracle = np.empty(30)
        fold_errors = []
        for fold in plan.folds:
            model = PLSRegression(n_components=components, scale=True).fit(X[fold.train], y[fold.train])
            oracle[fold.test] = model.predict(X[fold.test]).reshape(-1)
            fold_errors.append(np.sqrt(np.mean((oracle[fold.test] - y[fold.test]) ** 2)))
        row = cv["rows"][components - 1]
        np.testing.assert_allclose(row["rmsecv"][0], np.sqrt(np.mean((oracle - y) ** 2)), rtol=1e-10)
        np.testing.assert_allclose(row["fold_rmse_mean"][0], np.mean(fold_errors), rtol=1e-10)
        np.testing.assert_allclose(
            row["q2"][0],
            1 - np.sum((oracle - y) ** 2) / np.sum((y - y.mean()) ** 2),
            rtol=1e-10,
        )


def test_perturbed_held_out_spectrum_does_not_enter_its_fold_scaling() -> None:
    rng = np.random.default_rng(624)
    X = rng.normal(size=(30, 5))
    y = X @ np.array([1.5, -0.7, 0.2, 0.0, 0.0]) + rng.normal(scale=0.1, size=30)
    folds = make_split_plan(30, n_splits=5).folds
    held_out = folds[0].test[0]
    perturbed = X.copy()
    perturbed[held_out] += 1000.0

    curve = _curve(perturbed, y)
    assert curve["cross_validation"]["status"] == "available"
    # The chosen fold's training rows are unchanged. An independent model fit
    # must therefore reproduce the stored error even though an extreme held-out
    # spectrum changed the full-calibration fit and the other folds' training.
    fold = folds[0]
    oracle = PLSRegression(n_components=2, scale=True).fit(X[fold.train], y[fold.train])
    expected = np.sqrt(np.mean((oracle.predict(perturbed[fold.test]).reshape(-1) - y[fold.test]) ** 2))
    np.testing.assert_allclose(curve["cross_validation"]["rows"][1]["fold_rmse"][0][0], expected, rtol=1e-10)
    np.testing.assert_allclose(oracle._x_mean, X[fold.train].mean(axis=0), rtol=1e-12)


def test_insufficient_independent_groups_does_not_invalidate_calibration() -> None:
    rng = np.random.default_rng(122)
    X = rng.normal(size=(12, 5))
    y = X @ np.array([1.0, 2.0, 0.0, 0.0, 0.0])
    curve = _curve(X, y, groups=[f"group-{index // 4}" for index in range(12)])
    assert curve["calibration"][1]["status"] == "available"
    assert curve["cross_validation"]["status"] == "unavailable"
    assert "independent groups" in curve["cross_validation"]["reason"]


def test_unfittable_fold_does_not_invalidate_calibration() -> None:
    rng = np.random.default_rng(93)
    X = rng.normal(size=(10, 5))
    y = np.array([3.0, 5.0, *([1.0] * 8)])
    curve = _curve(X, y)
    assert curve["calibration"][0]["status"] == "available"
    assert curve["cross_validation"]["status"] == "unavailable"
    assert "fold" in curve["cross_validation"]["reason"]


def test_unknown_or_population_fitted_preprocessing_refuses_automatic_cv() -> None:
    dataset = SherpaDataset(X=np.arange(24, dtype=float).reshape(8, 3))
    assert cv_unavailable_reason(dataset) is None
    dataset.provenance.append("preprocess.normalize")
    assert cv_unavailable_reason(dataset) is None
    dataset.provenance.append("preprocess.scale")
    assert "preprocess.scale" in cv_unavailable_reason(dataset)


def test_normal_raw_load_attach_and_split_allow_cv_but_preprocessed_source_does_not() -> None:
    dataset = SherpaDataset(X=np.arange(36, dtype=float).reshape(12, 3))
    dataset.provenance.append(op_id="data.file_load", parameters={"stage": "raw"})
    dataset.provenance.append(op_id="data.attach_target", parameters={"target_source": "sample_table_column"})
    dataset.provenance.append(op_id="data.train_test_split", parameters={"split": "train"})
    assert cv_unavailable_reason(dataset) is None
    test_partition = SherpaDataset(X=np.arange(36, dtype=float).reshape(12, 3))
    test_partition.provenance.append(op_id="data.train_test_split", parameters={"split": "test"})
    assert "not verified as the training partition" in cv_unavailable_reason(test_partition)
    unknown_partition = SherpaDataset(X=np.arange(36, dtype=float).reshape(12, 3))
    unknown_partition.provenance.append(op_id="data.train_test_split", parameters={})
    assert "not verified as the training partition" in cv_unavailable_reason(unknown_partition)
    dataset.provenance.append(op_id="preprocess.scale", parameters={})
    assert "preprocess.scale" in cv_unavailable_reason(dataset)
    other = SherpaDataset(X=np.arange(36, dtype=float).reshape(12, 3))
    other.provenance.append(op_id="spectrasherpa.experiment_dataset_read/2", parameters={"stage": "preprocessed"})
    assert "not a verified raw stage" in cv_unavailable_reason(other)
    synthetic = SherpaDataset(X=np.arange(36, dtype=float).reshape(12, 3))
    synthetic.provenance.append(op_id="spectrasherpa.experiment_dataset_read/2", parameters={"stage": "synthetic"})
    synthetic.provenance.append(op_id="data.train_test_split", parameters={"split": "train"})
    assert cv_unavailable_reason(synthetic) is None
    unknown = SherpaDataset(X=np.arange(36, dtype=float).reshape(12, 3))
    unknown.provenance.append(op_id="import.future_scaled_source", parameters={})
    assert "import.future_scaled_source" in cv_unavailable_reason(unknown)


def test_rank_truncation_keeps_requested_and_effective_components_distinct() -> None:
    X = np.column_stack([np.linspace(0, 1, 16)] * 5)
    y = np.linspace(0, 1, 16)
    curve = build_pls_component_curve(
        X,
        y,
        selected_components=1,
        requested_components=4,
        maximum_components=4,
        scale=False,
        response_names=["Y"],
        response_units=[None],
        fit_model=fit_simpls,
    )
    assert curve["requested_components"] == 4
    assert curve["selected_components"] == curve["effective_calibration_components"] == 1
    assert curve["calibration"][1]["status"] == "unavailable_rank"


def test_oversized_automatic_curve_is_skipped_before_optional_refits() -> None:
    X = np.ones((250, 5000), dtype=float)
    y = np.arange(250, dtype=float)
    curve = build_pls_component_curve(
        X,
        y,
        selected_components=2,
        maximum_components=10,
        scale=False,
        response_names=["Y"],
        response_units=[None],
        fit_model=fit_simpls,
    )
    assert curve["calibration"] == []
    assert curve["cross_validation"]["status"] == "unavailable"
    assert "budget" in curve["cross_validation"]["reason"]


def test_recorded_choice_basis_is_checked_against_single_response_curve() -> None:
    rng = np.random.default_rng(40)
    X = rng.normal(size=(30, 5))
    y = 2 * X[:, 0] + rng.normal(scale=0.1, size=30)
    baseline = _curve(X, y)
    suggestion = baseline["cross_validation"]["suggestions"][0]["one_standard_error"]
    matched = build_pls_component_curve(
        X,
        y,
        selected_components=suggestion,
        maximum_components=3,
        scale=True,
        response_names=["Analyte"],
        response_units=["mg/L"],
        selection_rule="one_standard_error",
        fit_model=fit_simpls,
    )
    assert matched["selection_rule_status"] == "matches_curve"
    different = build_pls_component_curve(
        X,
        y,
        selected_components=1 if suggestion != 1 else 2,
        maximum_components=3,
        scale=True,
        response_names=["Analyte"],
        response_units=["mg/L"],
        selection_rule="one_standard_error",
        fit_model=fit_simpls,
    )
    assert different["selection_rule_status"] == "differs_from_curve"
