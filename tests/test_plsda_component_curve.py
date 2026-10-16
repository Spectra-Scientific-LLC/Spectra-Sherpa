"""Independent classification component-curve and refusal checks."""

from __future__ import annotations

import numpy as np
import pytest
from sklearn.cross_decomposition import PLSRegression
from sklearn.metrics import balanced_accuracy_score

from spectra_sherpa.app.services.dag.nodes.classification.plsda_component_curve import build_plsda_component_curve
from spectra_sherpa.app.services.dag.nodes.classification.plsda_nodes import _native_plsda_fit
from spectra_sherpa.sdk.validate import make_classification_split_plan


def _fit_model(X, Y, classes, n_components, scale):
    return _native_plsda_fit(X, Y, classes, n_components=n_components, scale=scale)[0]


@pytest.mark.parametrize("grouped", [False, True])
def test_classification_curve_matches_independent_fold_fits(grouped: bool) -> None:
    rng = np.random.default_rng(87)
    X = rng.normal(size=(36, 5))
    y = np.asarray(["A", "B", "C"] * 12)
    X[y == "A", 0] += 1.2
    X[y == "B", 1] += 1.2
    X[y == "C", 2] += 1.2
    groups = [f"specimen-{index // 3}" for index in range(36)] if grouped else None
    curve = build_plsda_component_curve(
        X,
        y,
        selected_components=2,
        maximum_components=3,
        scale=True,
        fit_model=_fit_model,
        groups=groups,
        cv_folds=3,
    )
    cv = curve["cross_validation"]
    assert cv["status"] == "available"
    plan = make_classification_split_plan(y, n_splits=3, groups=groups)
    assert cv["split_digest"] == plan.digest
    classes = np.unique(y)
    dummy = np.eye(classes.size)[np.searchsorted(classes, y)]
    for count in (1, 2, 3):
        oracle = np.empty_like(y)
        for fold in plan.folds:
            model = PLSRegression(n_components=count, scale=True).fit(X[fold.train], dummy[fold.train])
            oracle[fold.test] = classes[np.argmax(model.predict(X[fold.test]), axis=1)]
        np.testing.assert_allclose(
            cv["rows"][count - 1]["balanced_accuracy"],
            balanced_accuracy_score(y, oracle),
            rtol=1e-10,
        )


def test_invalid_stratified_design_keeps_calibration_and_marks_cv_unavailable() -> None:
    rng = np.random.default_rng(89)
    X = rng.normal(size=(12, 4))
    y = np.asarray(["A"] * 9 + ["B"] * 3)
    curve = build_plsda_component_curve(
        X,
        y,
        selected_components=2,
        maximum_components=3,
        scale=False,
        fit_model=_fit_model,
        cv_folds=5,
    )
    assert curve["calibration"][1]["status"] == "available"
    assert curve["cross_validation"]["status"] == "unavailable"
    assert "class" in curve["cross_validation"]["reason"]


def test_unverified_population_preprocessing_does_not_claim_cv() -> None:
    rng = np.random.default_rng(90)
    X = rng.normal(size=(18, 4))
    y = np.asarray(["A", "B"] * 9)
    curve = build_plsda_component_curve(
        X,
        y,
        selected_components=2,
        maximum_components=3,
        scale=False,
        fit_model=_fit_model,
        cv_unavailable_reason="Upstream scale was fitted on all rows.",
    )
    assert curve["cross_validation"] == {"status": "unavailable", "reason": "Upstream scale was fitted on all rows."}


def test_rank_truncation_marks_effective_classifier_not_unfitted_request() -> None:
    X = np.column_stack([np.linspace(0, 1, 16)] * 5)
    y = np.asarray(["A"] * 8 + ["B"] * 8)
    curve = build_plsda_component_curve(
        X,
        y,
        selected_components=1,
        requested_components=4,
        maximum_components=4,
        scale=False,
        fit_model=_fit_model,
        cv_folds=4,
    )
    assert curve["requested_components"] == 4
    assert curve["selected_components"] == curve["effective_calibration_components"] == 1
    assert curve["calibration"][1]["status"] == "unavailable_rank"
