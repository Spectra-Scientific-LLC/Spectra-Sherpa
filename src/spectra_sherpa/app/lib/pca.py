"""Sherpa-native principal-component analysis state and numerical authority.

The fit uses scikit-learn's exact full-SVD PCA.  This module owns PCA numerical
preprocessing, fitting, portable state projection, artifact serialization, and replay.
It has no SpectroChemPy or application-service dependency.

Scientific reference
--------------------
Jolliffe, I. T. & Cadima, J. (2016). Principal component analysis: a review
and recent developments. Philosophical Transactions of the Royal Society A,
374, 20150202. https://doi.org/10.1098/rsta.2015.0202

Minka, T. P. (2000). Automatic choice of dimensionality for PCA. Advances in
Neural Information Processing Systems 13. This is the method used only when
``n_components='mle'`` is selected.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, ClassVar

import numpy as np
from sklearn.decomposition import PCA as SklearnPCA


def _finite_matrix(value: Any, *, name: str) -> np.ndarray:
    matrix = np.asarray(value, dtype=np.float64)
    if matrix.ndim == 1:
        matrix = matrix.reshape(1, -1)
    if matrix.ndim != 2 or min(matrix.shape) < 1 or not np.isfinite(matrix).all():
        raise ValueError(f"{name} must be a non-empty finite two-dimensional matrix")
    return matrix


def _safe_positive_scale(values: np.ndarray) -> np.ndarray:
    scale = np.asarray(values, dtype=np.float64).reshape(-1).copy()
    scale[(scale == 0.0) | ~np.isfinite(scale)] = 1.0
    return scale


@dataclass
class PCAExtract:
    """Closed portable PCA state used by live execution and artifact replay."""

    scores: np.ndarray
    loadings: np.ndarray
    explained_variance_ratio: np.ndarray
    explained_variance: np.ndarray
    n_components: int
    mean: np.ndarray | None = None
    scale: np.ndarray | None = None
    offset: np.ndarray | None = None
    center: np.ndarray | None = None
    scale_mode: str | None = None

    SERIALIZER: ClassVar[str] = "spectrasherpa.model-artifact.pca/3"

    @classmethod
    def from_sklearn(
        cls,
        model: SklearnPCA,
        raw_input: Any,
        *,
        fitted_scores: Any,
        standardized: bool = False,
        scaled: bool = False,
    ) -> PCAExtract:
        """Project one fitted exact-SVD sklearn PCA into the portable state."""

        if standardized and scaled:
            raise ValueError("PCA standardized and scaled modes are mutually exclusive")
        raw = _finite_matrix(raw_input, name="raw_input")
        scores = _finite_matrix(fitted_scores, name="fitted_scores")
        loadings = _finite_matrix(getattr(model, "components_", None), name="PCA loadings")
        variance_ratio = np.asarray(getattr(model, "explained_variance_ratio_", None), dtype=np.float64).reshape(-1)
        eigenvalues = np.asarray(getattr(model, "explained_variance_", None), dtype=np.float64).reshape(-1)
        model_mean = np.asarray(getattr(model, "mean_", None), dtype=np.float64).reshape(-1)
        components, features = loadings.shape
        if (
            scores.shape != (raw.shape[0], components)
            or variance_ratio.shape != (components,)
            or eigenvalues.shape != (components,)
            or model_mean.shape != (features,)
            or raw.shape[1] != features
            or not np.isfinite(variance_ratio).all()
            or not np.isfinite(eigenvalues).all()
            or not np.isfinite(model_mean).all()
        ):
            raise ValueError("fitted PCA outputs do not share one consistent finite shape")

        mean: np.ndarray | None = None
        scale: np.ndarray | None = None
        offset: np.ndarray | None = None
        center: np.ndarray | None = None
        scale_mode: str | None = None
        if standardized:
            raw_mean = np.mean(raw, axis=0)
            raw_scale = _safe_positive_scale(np.std(raw, axis=0))
            # Keep the two reference frames separate.  Folding sklearn's
            # standardized-space center into a large raw-space mean loses the
            # small correction through catastrophic cancellation.
            mean = raw_mean
            scale = raw_scale
            center = model_mean
            scale_mode = "standard"
        elif scaled:
            offset = np.min(raw, axis=0)
            scale = _safe_positive_scale(np.ptp(raw, axis=0))
            center = model_mean
            scale_mode = "minmax"
        else:
            mean = model_mean

        return cls(
            scores=np.asarray(scores, dtype=np.float64),
            loadings=np.asarray(loadings, dtype=np.float64),
            explained_variance_ratio=np.asarray(variance_ratio, dtype=np.float64),
            explained_variance=np.asarray(eigenvalues, dtype=np.float64),
            n_components=components,
            mean=None if mean is None else np.asarray(mean, dtype=np.float64),
            scale=None if scale is None else np.asarray(scale, dtype=np.float64),
            offset=None if offset is None else np.asarray(offset, dtype=np.float64),
            center=None if center is None else np.asarray(center, dtype=np.float64),
            scale_mode=scale_mode,
        )

    def to_artifact(self) -> tuple[dict[str, object], dict[str, np.ndarray]]:
        """Serialize to the closed ModelStore manifest and named arrays."""

        metadata: dict[str, object] = {
            "model_type": "pca",
            "serializer": self.SERIALIZER,
            "n_components": self.n_components,
            "n_features": int(self.loadings.shape[1]),
            "standardized": self.scale_mode == "standard",
            "scaled": self.scale_mode == "minmax",
            "scale_mode": self.scale_mode,
        }
        arrays = {
            "loadings": np.asarray(self.loadings, dtype=np.float64),
            "explained_variance_ratio": np.asarray(self.explained_variance_ratio, dtype=np.float64),
            "explained_variance": np.asarray(self.explained_variance, dtype=np.float64),
        }
        for name in ("mean", "scale", "offset", "center", "scores"):
            value = getattr(self, name)
            if value is not None and np.asarray(value).size > 0:
                arrays[name] = np.asarray(value, dtype=np.float64)
        return metadata, arrays

    @classmethod
    def from_artifact(cls, metadata: dict[str, object], arrays: dict[str, np.ndarray]) -> PCAExtract:
        """Reconstruct only the current closed PCA artifact."""

        if metadata.get("model_type") != "pca" or metadata.get("serializer") != cls.SERIALIZER:
            raise ValueError("PCA artifact does not use the current closed serializer")
        required_metadata = {"n_components", "n_features", "standardized", "scaled", "scale_mode"}
        required_arrays = {"loadings", "explained_variance_ratio", "explained_variance"}
        if not required_metadata.issubset(metadata) or not required_arrays.issubset(arrays):
            raise ValueError("PCA artifact is missing required current fields")
        loadings = np.asarray(arrays["loadings"], dtype=np.float64)
        variance_ratio = np.asarray(arrays["explained_variance_ratio"], dtype=np.float64)
        explained_variance = np.asarray(arrays["explained_variance"], dtype=np.float64)
        n_components = metadata["n_components"]
        n_features = metadata["n_features"]
        if (
            isinstance(n_components, bool)
            or not isinstance(n_components, int)
            or n_components < 1
            or isinstance(n_features, bool)
            or not isinstance(n_features, int)
            or n_features < 1
            or loadings.shape != (n_components, n_features)
            or not np.isfinite(loadings).all()
            or variance_ratio.shape != (n_components,)
            or not np.isfinite(variance_ratio).all()
            or np.any(variance_ratio < 0.0)
            or explained_variance.shape != (n_components,)
            or not np.isfinite(explained_variance).all()
            or np.any(explained_variance <= 0.0)
        ):
            raise ValueError("PCA artifact dimensions do not match its declared shape")
        standardized = metadata["standardized"]
        scaled = metadata["scaled"]
        scale_mode = metadata["scale_mode"]
        if not isinstance(standardized, bool) or not isinstance(scaled, bool) or (standardized and scaled):
            raise ValueError("PCA artifact has invalid preprocessing flags")
        expected_mode = "standard" if standardized else "minmax" if scaled else None
        if scale_mode != expected_mode:
            raise ValueError("PCA artifact has inconsistent preprocessing metadata")
        required_vectors = (
            {"mean", "scale", "center"} if standardized else {"offset", "scale", "center"} if scaled else {"mean"}
        )
        if not required_vectors.issubset(arrays):
            raise ValueError("PCA artifact is missing fitted preprocessing state")
        vectors: dict[str, np.ndarray | None] = {}
        for name in ("mean", "scale", "offset", "center"):
            raw = arrays.get(name)
            vector = None if raw is None else np.asarray(raw, dtype=np.float64)
            if vector is not None and (vector.shape != (n_features,) or not np.isfinite(vector).all()):
                raise ValueError(f"PCA artifact has invalid {name}")
            vectors[name] = vector
        if vectors["scale"] is not None and np.any(vectors["scale"] <= 0.0):
            raise ValueError("PCA artifact scale must be positive")
        scores = np.asarray(arrays.get("scores", np.empty((0, n_components))), dtype=np.float64)
        if scores.ndim != 2 or scores.shape[1] != n_components or not np.isfinite(scores).all():
            raise ValueError("PCA artifact has invalid fitted scores")
        return cls(
            scores=scores,
            loadings=loadings,
            explained_variance_ratio=variance_ratio,
            explained_variance=explained_variance,
            n_components=n_components,
            mean=vectors["mean"],
            scale=vectors["scale"],
            offset=vectors["offset"],
            center=vectors["center"],
            scale_mode=scale_mode,
        )

    def transform(self, X: Any) -> np.ndarray:
        """Project new observations through the exact persisted affine state."""

        matrix = _finite_matrix(X, name="PCA application data")
        if matrix.shape[1] != self.loadings.shape[1]:
            raise ValueError("PCA application data must match the fitted feature count")
        if self.mean is not None:
            matrix = matrix - self.mean
        if self.offset is not None:
            matrix = matrix - self.offset
        if self.scale is not None:
            matrix = matrix / self.scale
        if self.center is not None:
            matrix = matrix - self.center
        return np.asarray(matrix @ self.loadings.T, dtype=np.float64)


def fit_pca(
    X: Any,
    *,
    n_components: int | str | float,
    standardized: bool,
    scaled: bool,
) -> PCAExtract:
    """Fit the sole Sherpa PCA authority using deterministic exact full SVD."""

    if standardized and scaled:
        raise ValueError("PCA standardized and scaled modes are mutually exclusive")
    raw = _finite_matrix(X, name="PCA input")
    fit_matrix = raw
    if standardized:
        mean = np.mean(raw, axis=0)
        scale = _safe_positive_scale(np.std(raw, axis=0))
        fit_matrix = (raw - mean) / scale
    elif scaled:
        offset = np.min(raw, axis=0)
        scale = _safe_positive_scale(np.ptp(raw, axis=0))
        fit_matrix = (raw - offset) / scale
    model = SklearnPCA(n_components=n_components, svd_solver="full")
    scores = model.fit_transform(fit_matrix)
    return PCAExtract.from_sklearn(
        model,
        raw,
        fitted_scores=scores,
        standardized=standardized,
        scaled=scaled,
    )


__all__ = ["PCAExtract", "fit_pca"]
