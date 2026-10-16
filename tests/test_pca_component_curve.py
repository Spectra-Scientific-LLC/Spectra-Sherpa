"""Independent PCA reconstruction and CV design checks."""

from __future__ import annotations

import numpy as np
from sklearn.decomposition import PCA

from spectra_sherpa.app.services.dag.nodes.modeling.pca_component_curve import build_pca_component_curve
from spectra_sherpa.sdk.validate import make_split_plan


def test_pca_curve_matches_independent_fold_local_reconstruction() -> None:
    rng = np.random.default_rng(622)
    latent = rng.normal(size=(24, 3))
    X = latent @ rng.normal(size=(3, 7)) + rng.normal(scale=0.1, size=(24, 7))
    groups = [f"batch-{index // 3}" for index in range(24)]
    curve = build_pca_component_curve(
        X,
        selected_components=2,
        maximum_components=4,
        standardized=True,
        scaled=False,
        groups=groups,
        cv_folds=4,
    )
    cv = curve["cross_validation"]
    assert cv["status"] == "available"
    assert cv["split_digest"] == make_split_plan(24, n_splits=4, groups=groups).digest
    for count in (1, 2, 3, 4):
        squared = 0.0
        cells = 0
        for fold in make_split_plan(24, n_splits=4, groups=groups).folds:
            mean = X[fold.train].mean(axis=0)
            scale = X[fold.train].std(axis=0)
            fitted = (X[fold.train] - mean) / scale
            held = (X[fold.test] - mean) / scale
            model = PCA(n_components=count, svd_solver="full").fit(fitted)
            reconstructed = model.inverse_transform(model.transform(held))
            squared += float(np.sum((held - reconstructed) ** 2))
            cells += held.size
        np.testing.assert_allclose(
            cv["rows"][count - 1]["pooled_reconstruction_rmse"], np.sqrt(squared / cells), rtol=1e-10
        )
    assert curve["reconstruction_space"] == "autoscaled_X"


def test_pca_curve_reports_unavailable_grouped_cv_without_failing_calibration() -> None:
    rng = np.random.default_rng(623)
    X = rng.normal(size=(12, 5))
    curve = build_pca_component_curve(
        X,
        selected_components=2,
        maximum_components=3,
        standardized=False,
        scaled=False,
        groups=["A"] * 6 + ["B"] * 6,
        cv_folds=5,
    )
    assert curve["calibration"][1]["explained_x_cumulative"] > 0
    assert curve["cross_validation"]["status"] == "unavailable"
    assert "independent groups" in curve["cross_validation"]["reason"]
