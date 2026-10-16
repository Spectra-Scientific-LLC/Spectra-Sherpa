"""PCA explained-X and fold-held-out reconstruction evidence by component."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import numpy as np

from spectra_sherpa.app.lib.pca import PCAExtract, fit_pca
from spectra_sherpa.sdk.validate import make_split_plan

from .component_validation import automatic_curve_workload_reason

SCHEMA_VERSION = "spectrasherpa-pca-component-curve/1"


def _fitted_space(raw: np.ndarray, fit: PCAExtract) -> np.ndarray:
    matrix = np.asarray(raw, dtype=np.float64)
    if fit.mean is not None:
        matrix = matrix - fit.mean
    if fit.offset is not None:
        matrix = matrix - fit.offset
    if fit.scale is not None:
        matrix = matrix / fit.scale
    if fit.center is not None:
        matrix = matrix - fit.center
    return matrix


def _reconstruction_rmse(raw: np.ndarray, fit: PCAExtract, components: int) -> float:
    fitted = _fitted_space(raw, fit)
    loadings = fit.loadings[:components]
    scores = fitted @ loadings.T
    residual = fitted - scores @ loadings
    return float(np.sqrt(np.mean(residual * residual)))


def build_pca_component_curve(
    X: object,
    *,
    selected_components: int,
    maximum_components: int,
    standardized: bool,
    scaled: bool,
    groups: Sequence[Any] | None = None,
    cv_folds: int = 5,
    cv_unavailable_reason: str | None = None,
) -> dict[str, object]:
    matrix = np.asarray(X, dtype=np.float64)
    if matrix.ndim != 2 or matrix.shape[0] < 2 or matrix.shape[1] < 1 or not np.isfinite(matrix).all():
        raise ValueError("PCA component evidence needs a finite two-dimensional calibration matrix")
    if not 1 <= selected_components <= min(matrix.shape) or not 1 <= maximum_components <= min(matrix.shape):
        raise ValueError("PCA component evidence exceeds calibration dimensions")
    if standardized and scaled or not 2 <= cv_folds <= 10:
        raise ValueError("PCA component-validation settings are invalid")

    workload_reason = automatic_curve_workload_reason(*matrix.shape, maximum_components, cv_folds)
    if workload_reason:
        return {
            "schema_version": SCHEMA_VERSION,
            "model_family": "pca",
            "selected_components": selected_components,
            "selected_in_curve": False,
            "selection_rule": "manual_parameter",
            "maximum_components": maximum_components,
            "n_calibration": int(matrix.shape[0]),
            "n_features": int(matrix.shape[1]),
            "reconstruction_space": (
                "autoscaled_X" if standardized else "minmax_scaled_X" if scaled else "mean_centered_X"
            ),
            "calibration": [],
            "cross_validation": {"status": "unavailable", "reason": workload_reason},
        }

    try:
        fit = fit_pca(matrix, n_components=maximum_components, standardized=standardized, scaled=scaled)
    except ValueError:
        if selected_components > maximum_components:
            raise
        maximum_components = selected_components
        fit = fit_pca(matrix, n_components=maximum_components, standardized=standardized, scaled=scaled)
    cumulative = np.cumsum(fit.explained_variance_ratio)
    calibration = [
        {
            "components": count,
            "explained_x_incremental": float(fit.explained_variance_ratio[count - 1]),
            "explained_x_cumulative": float(cumulative[count - 1]),
            "reconstruction_rmse": _reconstruction_rmse(matrix, fit, count),
        }
        for count in range(1, maximum_components + 1)
    ]
    cv: dict[str, object] = {"status": "unavailable", "reason": "Not evaluated."}
    if cv_unavailable_reason is not None:
        cv["reason"] = cv_unavailable_reason
    elif matrix.shape[0] < cv_folds + 2:
        cv["reason"] = "Too few calibration rows for the requested CV folds."
    elif matrix.shape[0] > 10_000:
        cv["reason"] = "This model exceeds the bounded 10,000-row automatic component CV."
    elif groups is not None and len(set(np.asarray(groups).tolist())) < cv_folds:
        cv["reason"] = "Too few independent groups for the requested CV folds."
    else:
        plan = make_split_plan(matrix.shape[0], n_splits=cv_folds, groups=groups)
        fold_limit = min(maximum_components, matrix.shape[1], min(len(fold.train) for fold in plan.folds))
        fold_squared = np.zeros((fold_limit, cv_folds), dtype=np.float64)
        fold_cells = np.zeros(cv_folds, dtype=np.int64)
        folds = []
        reason = None
        for fold_index, fold in enumerate(plan.folds):
            try:
                fold_fit = fit_pca(
                    matrix[fold.train],
                    n_components=fold_limit,
                    standardized=standardized,
                    scaled=scaled,
                )
            except ValueError as exc:
                reason = f"A CV training fold cannot be fitted: {exc}"
                break
            held = _fitted_space(matrix[fold.test], fold_fit)
            scores = held @ fold_fit.loadings.T
            fold_cells[fold_index] = held.size
            for count in range(1, fold_limit + 1):
                residual = held - scores[:, :count] @ fold_fit.loadings[:count]
                fold_squared[count - 1, fold_index] = float(np.sum(residual * residual))
            folds.append({"train": fold.train.astype(int).tolist(), "test": fold.test.astype(int).tolist()})
        if reason is not None:
            cv["reason"] = reason
        else:
            rows = []
            for count in range(1, maximum_components + 1):
                if count > fold_limit:
                    rows.append({"components": count, "status": "unavailable_rank"})
                    continue
                fold_rmse = np.sqrt(fold_squared[count - 1] / fold_cells)
                rows.append(
                    {
                        "components": count,
                        "status": "available",
                        "pooled_reconstruction_rmse": float(
                            np.sqrt(np.sum(fold_squared[count - 1]) / np.sum(fold_cells))
                        ),
                        "fold_reconstruction_rmse": fold_rmse.astype(float).tolist(),
                    }
                )
            cv = {
                "status": "available",
                "role": "development_tuning",
                "method": plan.method,
                "n_folds": cv_folds,
                "n_groups": None if groups is None else len(set(np.asarray(groups).tolist())),
                "split_digest": plan.digest,
                "folds": folds,
                "rows": rows,
                "caution": (
                    "Reconstruction CV is a development diagnostic, "
                    "not an independent test or a response prediction error."
                ),
            }
    return {
        "schema_version": SCHEMA_VERSION,
        "model_family": "pca",
        "selected_components": selected_components,
        "selection_rule": "manual_parameter",
        "selection_note": "The saved n_components parameter chose the PCA model; reconstruction CV did not change it.",
        "selected_in_curve": selected_components <= maximum_components,
        "maximum_components": maximum_components,
        "n_calibration": int(matrix.shape[0]),
        "n_features": int(matrix.shape[1]),
        "reconstruction_space": "autoscaled_X" if standardized else "minmax_scaled_X" if scaled else "mean_centered_X",
        "reconstruction_denominator": "all held-out row-feature cells across folds",
        "calibration": calibration,
        "cross_validation": cv,
    }
