"""Sole fitted-state application authority for canonical KNN classification."""

from __future__ import annotations

from typing import Any

import numpy as np


def build_knn_estimator(
    *,
    n_neighbors: int,
    weights: str,
    metric: str,
    scale: bool,
) -> Any:
    """Build the sole deterministic estimator used for KNN fit and replay."""

    from sklearn.neighbors import KNeighborsClassifier

    estimator = KNeighborsClassifier(
        n_neighbors=n_neighbors,
        weights=weights,
        metric=metric,
        algorithm="brute",
        n_jobs=1,
    )
    if not scale:
        return estimator

    from sklearn.pipeline import Pipeline
    from sklearn.preprocessing import StandardScaler

    return Pipeline([("scale", StandardScaler()), ("knn", estimator)])


def apply_knn_artifact_state(
    X: Any,
    *,
    training: np.ndarray,
    encoded_labels: np.ndarray,
    classes: tuple[str, ...],
    n_neighbors: int,
    weights: str,
    metric: str,
    mean: np.ndarray,
    scale: np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    """Apply one validated state with sklearn's exact voting semantics."""

    matrix = np.asarray(X, dtype=np.float64)
    if matrix.ndim == 1:
        matrix = matrix.reshape(1, -1)
    if matrix.ndim != 2 or matrix.shape[1] != training.shape[1] or not np.isfinite(matrix).all():
        raise ValueError("KNN application input does not match the fitted feature contract")
    matrix = (matrix - mean) / scale

    model = build_knn_estimator(
        n_neighbors=n_neighbors,
        weights=weights,
        metric=metric,
        scale=False,
    ).fit(training, encoded_labels)
    encoded_predictions = np.asarray(model.predict(matrix), dtype=np.int64)
    probabilities = np.asarray(model.predict_proba(matrix), dtype=np.float64)
    labels = np.asarray([classes[index] for index in encoded_predictions], dtype=object)
    return labels, probabilities


__all__ = ["apply_knn_artifact_state", "build_knn_estimator"]
