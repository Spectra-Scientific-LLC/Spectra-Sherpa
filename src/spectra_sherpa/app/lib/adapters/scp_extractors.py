"""
Typed extraction classes for SpectroChemPy model outputs.

Centralizes version-specific API logic for PCA, PLS, MCR, EFA, SIMPLISMA,
PLS-DA, KNN, and SIMCA.  All defensive hasattr checks, try-except cascades,
and normalization heuristics live HERE — not scattered across node callsites.

When SCP 0.9 ships, fix one extractor class, not N nodes.

Each Extract also provides:
- to_artifact() / from_artifact(): Serialize to/from ModelStore format
- predict() or transform(): Pure-numpy inference (no SCP/sklearn required)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import numpy as np

from spectra_sherpa.app.lib.scp_compat import require_scp

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _safe_getattr(obj: Any, names: tuple[str, ...]) -> Any | None:
    """Try attribute names in order, returning first non-None.

    Catches exceptions from property descriptors that may raise
    (e.g. SCP wraps _coef in a property that can fail on some versions).
    """
    for name in names:
        try:
            val = getattr(obj, name, None)
            if val is not None:
                return val
        except Exception:
            continue
    return None


def _unwrap_to_numpy(value: Any, name: str = "value") -> np.ndarray:
    """Safely unwrap NDDataset or array-like to numpy array."""
    if value is None:
        raise ValueError(f"{name} is None")

    # Extract .data attribute if present (NDDataset)
    if hasattr(value, "data") and not isinstance(value, np.ndarray):
        raw = value.data
    else:
        raw = value

    return np.asarray(raw)


def _to_numpy_2d(value: Any, name: str = "value") -> np.ndarray:
    """Convert to strict 2D float64 array."""
    arr = _unwrap_to_numpy(value, name)
    if arr.ndim == 0:
        raise ValueError(f"{name} must be 1D or 2D, got scalar")
    if arr.ndim == 1:
        arr = arr.reshape(-1, 1)
    if arr.ndim != 2:
        raise ValueError(f"{name} must be 1D or 2D, got {arr.ndim}D")
    return arr.astype(np.float64)


def _to_numpy_1d(value: Any, name: str = "value") -> np.ndarray:
    """Convert to strict 1D float64 array."""
    arr = _unwrap_to_numpy(value, name)
    if arr.ndim == 0:
        arr = arr.reshape(1)
    return arr.reshape(-1).astype(np.float64)


def _as_optional_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if np.isfinite(out) else None


# ---------------------------------------------------------------------------
# PCAExtract
# ---------------------------------------------------------------------------


@dataclass
class PCAExtract:
    """Version-aware extraction of PCA model outputs.

    Attributes:
        scores: Transformed scores (n_samples, n_components)
        loadings: Principal component loadings (n_components, n_features)
        explained_variance_ratio: Variance ratio 0-1 (n_components,)
        explained_variance: Eigenvalues (n_components,)
        n_components: Actual number of fitted components
        mean: Training data mean for centering (n_features,)
        scale: Training data divisor for standardized/min-max scaled PCA (n_features,)
        offset: Training data offset for min-max scaled PCA (n_features,)
        center: Training data center after min-max scaling (n_features,)
        scale_mode: "standard" for std scaling, "minmax" for SCP scaled=True, or None
    """

    scores: np.ndarray  # 2D float64
    loadings: np.ndarray  # 2D float64
    explained_variance_ratio: np.ndarray  # 1D float64, 0-1 ratio
    explained_variance: np.ndarray  # 1D float64
    n_components: int
    mean: np.ndarray | None = None  # 1D float64
    scale: np.ndarray | None = None  # 1D float64
    offset: np.ndarray | None = None  # 1D float64
    center: np.ndarray | None = None  # 1D float64
    scale_mode: str | None = None

    @classmethod
    def from_scp(
        cls,
        pca_model: Any,
        input_ndd: Any,
        *,
        standardized: bool = False,
        scaled: bool = False,
    ) -> PCAExtract:
        """Extract from fitted SCP PCA model.

        All hasattr/try-except logic lives HERE. When SCP changes its API,
        update this method, not 15 callsites.

        Args:
            pca_model: Fitted scp.PCA instance
            input_ndd: Input NDDataset (for row count validation)

        Returns:
            PCAExtract with normalized outputs

        Raises:
            ValueError: If required attributes are missing
        """
        require_scp("PCAExtract.from_scp")

        # Extract scores — pca.transform() returns NDDataset
        try:
            scores_ndd = pca_model.transform()
            scores = _to_numpy_2d(scores_ndd, name="scores")
        except Exception as e:
            raise ValueError(f"Could not extract PCA scores: {e}") from e

        # Extract loadings — pca.components is NDDataset
        try:
            loadings_ndd = pca_model.components
            loadings = _to_numpy_2d(loadings_ndd, name="loadings")
        except Exception as e:
            raise ValueError(f"Could not extract PCA components: {e}") from e

        n_components = scores.shape[1]

        # Extract explained variance ratio — NORMALIZE to 0-1
        # SCP sometimes returns percentages (0-100), sometimes ratios (0-1)
        evr_raw = getattr(pca_model, "explained_variance_ratio", None)
        if evr_raw is None:
            raise ValueError("PCA model missing explained_variance_ratio")

        evr = _to_numpy_1d(evr_raw, name="explained_variance_ratio")

        # Normalize to ratio form (0-1)
        max_evr = evr.max() if len(evr) > 0 else 0
        if max_evr > 1.0:
            logger.debug("[PCAExtract] Normalizing EVR from percentage to ratio (max=%.2f)", max_evr)
            evr = evr / 100.0

        # Pad if needed (edge case: SCP returns fewer EVR values than components)
        if len(evr) < n_components:
            logger.warning("[PCAExtract] EVR length %d < n_components %d, padding with zeros", len(evr), n_components)
            evr = np.pad(evr, (0, n_components - len(evr)), mode="constant", constant_values=0)

        # Extract eigenvalues (explained_variance)
        ev_raw = getattr(pca_model, "explained_variance", None)
        if ev_raw is not None:
            eigenvalues = _to_numpy_1d(ev_raw, name="explained_variance")
        else:
            # Fallback: compute from score variances
            logger.debug("[PCAExtract] explained_variance missing, computing from scores")
            eigenvalues = np.var(scores, axis=0)

        # Ensure eigenvalues match n_components
        if len(eigenvalues) < n_components:
            eigenvalues = np.pad(
                eigenvalues, (0, n_components - len(eigenvalues)), mode="constant", constant_values=1e-12
            )

        # Compute training data preprocessing state for deploy-time transform.
        #
        # SCP's default PCA path mean-centers. standardized=True centers and
        # divides by per-feature std. scaled=True first min-max scales each
        # variable as (X - min) / ptp and then centers the scaled matrix
        # before SVD. Persist those raw-space and scaled-space parameters
        # because load_apply has only raw inference data and loadings in PCA
        # space.
        mean = None
        scale = None
        offset = None
        center = None
        scale_mode = None
        try:
            input_array = _unwrap_to_numpy(input_ndd, "input_ndd")
            raw_mean = np.mean(input_array, axis=0).astype(np.float64).reshape(-1)
            raw_std = np.std(input_array, axis=0).astype(np.float64).reshape(-1)
            raw_std[(raw_std == 0) | ~np.isfinite(raw_std)] = 1.0
            raw_min = np.min(input_array, axis=0).astype(np.float64).reshape(-1)
            raw_ptp = np.ptp(input_array, axis=0).astype(np.float64).reshape(-1)
            raw_ptp[(raw_ptp == 0) | ~np.isfinite(raw_ptp)] = 1.0
            if standardized:
                mean = raw_mean
                scale = raw_std
                scale_mode = "standard"
            elif scaled:
                offset = raw_min
                scale = raw_ptp
                scaled_array = (input_array - raw_min) / raw_ptp
                center = np.mean(scaled_array, axis=0).astype(np.float64).reshape(-1)
                center[~np.isfinite(center)] = 0.0
                scale_mode = "minmax"
            else:
                mean = raw_mean
        except Exception as e:
            logger.warning("[PCAExtract] Could not compute training preprocessing state: %s", e)

        return cls(
            scores=scores,
            loadings=loadings,
            explained_variance_ratio=evr[:n_components],
            explained_variance=eigenvalues[:n_components],
            n_components=n_components,
            mean=mean,
            scale=scale,
            offset=offset,
            center=center,
            scale_mode=scale_mode,
        )

    def to_artifact(self) -> tuple[dict, dict[str, np.ndarray]]:
        """Serialize to (metadata, named_arrays) for ModelStore.save()."""
        metadata = {
            "model_type": "pca",
            "n_components": self.n_components,
            "standardized": self.scale_mode == "standard" or bool(self.mean is not None and self.scale is not None),
            "scaled": self.scale_mode == "minmax" or bool(self.mean is None and self.scale is not None),
            "scale_mode": self.scale_mode,
        }
        arrays: dict[str, np.ndarray] = {
            "loadings": self.loadings,
            "explained_variance_ratio": self.explained_variance_ratio,
            "explained_variance": self.explained_variance,
        }
        if self.mean is not None:
            arrays["mean"] = self.mean
        if self.scale is not None:
            arrays["scale"] = self.scale
        if self.offset is not None:
            arrays["offset"] = self.offset
        if self.center is not None:
            arrays["center"] = self.center
        if self.scores is not None and self.scores.size > 0:
            arrays["scores"] = self.scores
        return metadata, arrays

    @classmethod
    def from_artifact(cls, metadata: dict, arrays: dict[str, np.ndarray]) -> PCAExtract:
        """Reconstruct from ModelStore.load() output."""
        loadings = arrays["loadings"]
        n_components = metadata.get("n_components", loadings.shape[0])
        scale_mode = metadata.get("scale_mode")
        if scale_mode is None and metadata.get("standardized") and "scale" in arrays:
            scale_mode = "standard"
        elif scale_mode is None and metadata.get("scaled") and "scale" in arrays:
            scale_mode = "minmax" if "offset" in arrays and "center" in arrays else "minmax_incomplete"
        return cls(
            scores=arrays.get("scores", np.empty((0, n_components))),
            loadings=loadings,
            explained_variance_ratio=arrays.get("explained_variance_ratio", np.zeros(n_components)),
            explained_variance=arrays.get("explained_variance", np.zeros(n_components)),
            n_components=n_components,
            mean=arrays.get("mean"),
            scale=arrays.get("scale"),
            offset=arrays.get("offset"),
            center=arrays.get("center"),
            scale_mode=scale_mode,
        )

    def transform(self, X: np.ndarray) -> np.ndarray:
        """Project new data into PC space, replaying persisted PCA preprocessing."""
        X = np.asarray(X, dtype=np.float64)
        if X.ndim == 1:
            X = X.reshape(1, -1)
        if self.scale_mode == "minmax_incomplete" or (
            self.scale_mode == "minmax" and (self.offset is None or self.scale is None or self.center is None)
        ):
            raise ValueError(
                "PCA artifact was created with scaled=True but does not include the training min-max "
                "offset, range, and post-scale center needed to replay SpectroChemPy's transform."
            )
        if self.mean is not None:
            X = X - self.mean
        if self.offset is not None:
            X = X - self.offset
        if self.scale is not None:
            scale = np.asarray(self.scale, dtype=np.float64)
            scale = np.where(np.abs(scale) > 1e-12, scale, 1.0)
            X = X / scale
        if self.center is not None:
            X = X - self.center
        return X @ self.loadings.T


# ---------------------------------------------------------------------------
# PLSExtract
# ---------------------------------------------------------------------------


@dataclass
class PLSExtract:
    """Version-aware extraction of PLS regression outputs.

    Attributes:
        x_scores: X block scores (n_samples, n_components)
        y_scores: Y block scores (n_samples, n_components)
        x_loadings: X block loadings (n_features, n_components)
        y_loadings: Y block loadings (n_targets, n_components)
        coef: Regression coefficients (n_features, n_targets)
        n_components: Number of components
        x_mean: Training X mean for centering (n_features,)
        y_mean: Training Y mean for centering (n_targets,)
        x_scale: Training X scale for latent-space diagnostics (n_features,)
        t2_limit: Hotelling T² critical limit from the training set
        q_limit: Q-residual critical limit from the training set
    """

    x_scores: np.ndarray | None  # 2D float64
    y_scores: np.ndarray | None  # 2D float64
    x_loadings: np.ndarray | None  # 2D float64
    y_loadings: np.ndarray | None  # 2D float64
    coef: np.ndarray | None  # (n_features, n_targets) float64
    n_components: int
    x_mean: np.ndarray | None = None  # 1D float64
    y_mean: np.ndarray | None = None  # 1D float64
    x_scale: np.ndarray | None = None  # 1D float64, diagnostics only
    t2_limit: float | None = None
    q_limit: float | None = None
    t2_q_method: str | None = None

    @classmethod
    def from_scp(cls, pls_model: Any, X_ndd: Any, *, Y_ndd: Any = None) -> PLSExtract:
        """Extract from fitted SCP PLS model.

        Uses _safe_getattr with fallback chains to handle SCP version
        differences (0.8.x uses x_scores/coef, older uses x_scores_/coef_).
        Falls back to .transform() for x_scores when all attribute names miss.

        Args:
            pls_model: Fitted scp.PLSRegression instance
            X_ndd: Input X NDDataset (for transform fallback)
            Y_ndd: Input Y NDDataset (optional, for y_mean computation)

        Returns:
            PLSExtract with all extractable outputs
        """
        require_scp("PLSExtract.from_scp")

        n_components = pls_model.n_components

        # Extract X scores — try public/private/legacy names, then transform()
        x_scores = None
        raw = _safe_getattr(pls_model, ("x_scores", "_x_scores", "x_scores_"))
        if raw is not None:
            try:
                x_scores = _to_numpy_2d(raw, name="x_scores")
            except Exception:
                pass

        # Fallback: use transform()
        if x_scores is None and hasattr(pls_model, "transform"):
            try:
                transformed = pls_model.transform(X_ndd)
                x_scores = _to_numpy_2d(transformed, name="transform(X)")
                logger.debug("[PLSExtract] Derived x_scores from transform()")
            except Exception as e:
                logger.warning("[PLSExtract] Could not derive x_scores: %s", e)

        # Extract Y scores
        y_scores = None
        raw = _safe_getattr(pls_model, ("y_scores", "_y_scores", "y_scores_"))
        if raw is not None:
            try:
                y_scores = _to_numpy_2d(raw, name="y_scores")
            except Exception:
                pass

        # Extract X loadings
        x_loadings = None
        raw = _safe_getattr(pls_model, ("x_loadings", "_x_loadings", "x_loadings_"))
        if raw is not None:
            try:
                x_loadings = _to_numpy_2d(raw, name="x_loadings")
            except Exception:
                pass

        # Extract Y loadings
        y_loadings = None
        raw = _safe_getattr(pls_model, ("y_loadings", "_y_loadings", "y_loadings_"))
        if raw is not None:
            try:
                y_loadings = _to_numpy_2d(raw, name="y_loadings")
            except Exception:
                pass

        # Extract coefficients — prefer raw _coef (ndarray) over coef
        # property (NDDataset wrapper that may raise on some SCP versions)
        coef = None
        raw = _safe_getattr(pls_model, ("_coef", "coef_", "coef"))
        if raw is not None:
            try:
                coef = _unwrap_to_numpy(raw, name="coef")
            except Exception:
                pass

        # Compute X mean from training data
        x_mean = None
        x_scale = None
        x_train = None
        try:
            x_train = np.asarray(_unwrap_to_numpy(X_ndd, "X_ndd"), dtype=np.float64)
            x_mean = np.mean(x_train, axis=0).astype(np.float64).reshape(-1)
        except Exception as e:
            logger.warning("[PLSExtract] Could not compute x_mean: %s", e)

        scale_enabled = False
        scale_attr = _safe_getattr(pls_model, ("scale", "_scale"))
        if scale_attr is not None:
            try:
                scale_enabled = bool(np.asarray(scale_attr).item())
            except Exception:
                scale_enabled = bool(scale_attr)
        if scale_enabled and x_train is not None:
            try:
                # SpectroChemPy's internal PLS coefficients are already in
                # native feature units for prediction replay. Persist the scale
                # only so saved-model applicability diagnostics can reconstruct
                # the same centered/scaled X space used by training diagnostics.
                x_scale = np.std(x_train, axis=0, ddof=0).astype(np.float64).reshape(-1)
                x_scale = np.where(np.abs(x_scale) > 1e-12, x_scale, 1.0)
            except Exception as e:
                logger.warning("[PLSExtract] Could not compute x_scale: %s", e)

        # Compute Y mean from training data (if provided)
        y_mean = None
        if Y_ndd is not None:
            try:
                y_mean = np.mean(_unwrap_to_numpy(Y_ndd, "Y_ndd"), axis=0).astype(np.float64).reshape(-1)
            except Exception as e:
                logger.warning("[PLSExtract] Could not compute y_mean: %s", e)

        return cls(
            x_scores=x_scores,
            y_scores=y_scores,
            x_loadings=x_loadings,
            y_loadings=y_loadings,
            coef=coef,
            n_components=n_components,
            x_mean=x_mean,
            y_mean=y_mean,
            x_scale=x_scale,
        )

    def to_artifact(self) -> tuple[dict, dict[str, np.ndarray]]:
        """Serialize to (metadata, named_arrays) for ModelStore.save()."""
        metadata = {
            "model_type": "pls",
            "n_components": self.n_components,
        }
        if self.t2_limit is not None:
            metadata["t2_limit"] = float(self.t2_limit)
        if self.q_limit is not None:
            metadata["q_limit"] = float(self.q_limit)
        if self.t2_q_method is not None:
            metadata["t2_q_method"] = self.t2_q_method
        arrays: dict[str, np.ndarray] = {}
        if self.coef is not None:
            arrays["coef"] = np.asarray(self.coef, dtype=np.float64)
        if self.x_mean is not None:
            arrays["x_mean"] = self.x_mean
        if self.y_mean is not None:
            arrays["y_mean"] = self.y_mean
        if self.x_scale is not None:
            metadata["scaled"] = True
            arrays["x_scale"] = self.x_scale
        if self.x_loadings is not None:
            arrays["x_loadings"] = self.x_loadings
        if self.y_loadings is not None:
            arrays["y_loadings"] = self.y_loadings
        if self.x_scores is not None and self.x_scores.size > 0:
            arrays["x_scores"] = self.x_scores
        if self.y_scores is not None and self.y_scores.size > 0:
            arrays["y_scores"] = self.y_scores
        return metadata, arrays

    @classmethod
    def from_artifact(cls, metadata: dict, arrays: dict[str, np.ndarray]) -> PLSExtract:
        """Reconstruct from ModelStore.load() output."""
        n_components = metadata.get("n_components", 1)
        metrics = metadata.get("metrics") if isinstance(metadata.get("metrics"), dict) else {}
        return cls(
            x_scores=arrays.get("x_scores"),
            y_scores=arrays.get("y_scores"),
            x_loadings=arrays.get("x_loadings"),
            y_loadings=arrays.get("y_loadings"),
            coef=arrays.get("coef"),
            n_components=n_components,
            x_mean=arrays.get("x_mean"),
            y_mean=arrays.get("y_mean"),
            x_scale=arrays.get("x_scale"),
            t2_limit=_as_optional_float(metadata.get("t2_limit", metrics.get("t2_limit"))),
            q_limit=_as_optional_float(metadata.get("q_limit", metrics.get("q_limit"))),
            t2_q_method=metadata.get("t2_q_method", metrics.get("t2_q_method")),
        )

    def predict(self, X: np.ndarray) -> np.ndarray:
        """Predict Y from new X data: y_pred = (X - x_mean) @ coef + y_mean

        Requires coef to be stored as (n_features, n_targets).
        """
        if self.coef is None:
            raise ValueError("Cannot predict: coef is None")
        X = np.asarray(X, dtype=np.float64)
        if X.ndim == 1:
            X = X.reshape(1, -1)
        if self.x_mean is not None:
            X = X - self.x_mean
        y_pred = X @ self.coef
        if self.y_mean is not None:
            y_pred = y_pred + self.y_mean
        return y_pred

    def applicability_diagnostics(self, X: np.ndarray) -> dict[str, Any] | None:
        """Estimate PLS T²/Q diagnostics for new samples from stored state.

        The saved coefficient matrix replays prediction in native feature units.
        For applicability diagnostics we reconstruct the latent-variable
        preprocessing space, project onto stored X loadings by least squares,
        then compare T² and Q against the training-set limits when present.
        """
        if self.x_loadings is None or self.x_scores is None:
            return None
        X_pre = self._center_scale_for_diagnostics(X)
        P = np.asarray(self.x_loadings, dtype=np.float64)
        if P.ndim != 2:
            return None
        if P.shape[1] == X_pre.shape[1]:
            p_components_features = P
        elif P.shape[0] == X_pre.shape[1]:
            p_components_features = P.T
        else:
            return None

        try:
            scores = X_pre @ np.linalg.pinv(p_components_features)
            reconstructed = scores @ p_components_features
            residual = X_pre - reconstructed
            q_residuals = np.sum(residual**2, axis=1)

            train_scores = np.asarray(self.x_scores, dtype=np.float64)
            if train_scores.ndim != 2 or train_scores.shape[1] != scores.shape[1] or train_scores.shape[0] < 2:
                t2 = np.full(scores.shape[0], np.nan, dtype=np.float64)
            else:
                score_cov = (train_scores.T @ train_scores) / float(train_scores.shape[0] - 1)
                inv_cov = np.linalg.pinv(score_cov)
                t2 = np.einsum("ij,jk,ik->i", scores, inv_cov, scores)
        except Exception:
            logger.debug("[PLSExtract] Could not compute applicability diagnostics", exc_info=True)
            return None

        t2_outlier = (
            (np.asarray(t2, dtype=np.float64) > float(self.t2_limit)).tolist()
            if self.t2_limit is not None
            else [False] * int(scores.shape[0])
        )
        q_outlier = (
            (np.asarray(q_residuals, dtype=np.float64) > float(self.q_limit)).tolist()
            if self.q_limit is not None
            else [False] * int(scores.shape[0])
        )
        out_of_domain = [bool(a or b) for a, b in zip(t2_outlier, q_outlier, strict=False)]
        return {
            "type": "pls_applicability",
            "method": self.t2_q_method or "pls_loadings_projection",
            "hotelling_t2": np.asarray(t2, dtype=np.float64).tolist(),
            "q_residuals": np.asarray(q_residuals, dtype=np.float64).tolist(),
            "t2_limit": self.t2_limit,
            "q_limit": self.q_limit,
            "t2_outlier": t2_outlier,
            "q_outlier": q_outlier,
            "out_of_domain": out_of_domain,
            "n_out_of_domain": int(sum(out_of_domain)),
        }

    def _center_scale_for_diagnostics(self, X: np.ndarray) -> np.ndarray:
        X_arr = np.asarray(X, dtype=np.float64)
        if X_arr.ndim == 1:
            X_arr = X_arr.reshape(1, -1)
        if self.x_mean is not None:
            X_arr = X_arr - np.asarray(self.x_mean, dtype=np.float64)
        if self.x_scale is not None:
            scale = np.asarray(self.x_scale, dtype=np.float64)
            scale = np.where(np.abs(scale) > 1e-12, scale, 1.0)
            X_arr = X_arr / scale
        return X_arr


# ---------------------------------------------------------------------------
# PCRExtract
# ---------------------------------------------------------------------------


@dataclass
class PCRExtract:
    """Pure-numpy Principal Component Regression artifact."""

    pca_components: np.ndarray
    pca_mean: np.ndarray
    reg_coef: np.ndarray
    reg_intercept: np.ndarray
    n_components: int
    scaler_mean: np.ndarray | None = None
    scaler_scale: np.ndarray | None = None

    @classmethod
    def from_sklearn(cls, model: Any) -> PCRExtract:
        """Extract replayable state from the PCR sklearn pipeline."""
        pca = model.named_steps["pca"]
        regressor = model.named_steps["regressor"]
        scaler = model.named_steps.get("scaler") if hasattr(model, "named_steps") else None
        return cls(
            pca_components=np.asarray(pca.components_, dtype=np.float64),
            pca_mean=np.asarray(getattr(pca, "mean_", np.zeros(pca.components_.shape[1])), dtype=np.float64),
            reg_coef=np.asarray(regressor.coef_, dtype=np.float64),
            reg_intercept=np.asarray(regressor.intercept_, dtype=np.float64).reshape(-1),
            n_components=int(pca.components_.shape[0]),
            scaler_mean=(
                np.asarray(getattr(scaler, "mean_", None), dtype=np.float64)
                if scaler is not None and getattr(scaler, "mean_", None) is not None
                else None
            ),
            scaler_scale=(
                np.asarray(getattr(scaler, "scale_", None), dtype=np.float64)
                if scaler is not None and getattr(scaler, "scale_", None) is not None
                else None
            ),
        )

    def to_artifact(self) -> tuple[dict, dict[str, np.ndarray]]:
        metadata = {
            "model_type": "pcr",
            "n_components": self.n_components,
        }
        arrays: dict[str, np.ndarray] = {
            "pca_components": self.pca_components,
            "pca_mean": self.pca_mean,
            "reg_coef": self.reg_coef,
            "reg_intercept": self.reg_intercept,
        }
        if self.scaler_mean is not None:
            arrays["scaler_mean"] = self.scaler_mean
        if self.scaler_scale is not None:
            arrays["scaler_scale"] = self.scaler_scale
        return metadata, arrays

    @classmethod
    def from_artifact(cls, metadata: dict, arrays: dict[str, np.ndarray]) -> PCRExtract:
        return cls(
            pca_components=arrays["pca_components"],
            pca_mean=arrays["pca_mean"],
            reg_coef=arrays["reg_coef"],
            reg_intercept=arrays["reg_intercept"],
            n_components=metadata.get("n_components", arrays["pca_components"].shape[0]),
            scaler_mean=arrays.get("scaler_mean"),
            scaler_scale=arrays.get("scaler_scale"),
        )

    def predict(self, X: np.ndarray) -> np.ndarray:
        X = np.asarray(X, dtype=np.float64)
        if X.ndim == 1:
            X = X.reshape(1, -1)
        if self.scaler_mean is not None and self.scaler_scale is not None:
            scale = np.where(np.abs(self.scaler_scale) > 1e-12, self.scaler_scale, 1.0)
            X = (X - self.scaler_mean) / scale
        scores = (X - self.pca_mean) @ self.pca_components.T
        coef = np.asarray(self.reg_coef, dtype=np.float64)
        if coef.ndim == 1:
            return (scores @ coef + float(self.reg_intercept[0])).reshape(-1, 1)
        return scores @ coef.T + self.reg_intercept


# ---------------------------------------------------------------------------
# LinearRegressionExtract
# ---------------------------------------------------------------------------


@dataclass
class LinearRegressionExtract:
    """Pure-numpy sklearn LinearRegression artifact."""

    coef: np.ndarray
    intercept: np.ndarray

    @classmethod
    def from_sklearn(cls, model: Any) -> LinearRegressionExtract:
        return cls(
            coef=np.asarray(model.coef_, dtype=np.float64),
            intercept=np.asarray(model.intercept_, dtype=np.float64).reshape(-1),
        )

    def to_artifact(self) -> tuple[dict, dict[str, np.ndarray]]:
        return {"model_type": "linear_regression"}, {"coef": self.coef, "intercept": self.intercept}

    @classmethod
    def from_artifact(cls, metadata: dict, arrays: dict[str, np.ndarray]) -> LinearRegressionExtract:
        return cls(coef=arrays["coef"], intercept=arrays["intercept"])

    def predict(self, X: np.ndarray) -> np.ndarray:
        X = np.asarray(X, dtype=np.float64)
        if X.ndim == 1:
            X = X.reshape(1, -1)
        coef = np.asarray(self.coef, dtype=np.float64)
        if coef.ndim == 1:
            return (X @ coef + float(self.intercept[0])).reshape(-1, 1)
        return X @ coef.T + self.intercept


# ---------------------------------------------------------------------------
# SVRExtract
# ---------------------------------------------------------------------------


@dataclass
class SVRExtract:
    """Pure-numpy sklearn SVR artifact for single-target regression."""

    support_vectors: np.ndarray
    dual_coef: np.ndarray
    intercept: float
    kernel: str
    gamma: float
    degree: int
    coef0: float
    scaler_mean: np.ndarray | None = None
    scaler_scale: np.ndarray | None = None

    @classmethod
    def from_sklearn(cls, model: Any) -> SVRExtract:
        if hasattr(model, "named_steps"):
            svr = model.named_steps["estimator"]
            scaler = model.named_steps.get("scaler")
        else:
            svr = model
            scaler = None
        return cls(
            support_vectors=np.asarray(svr.support_vectors_, dtype=np.float64),
            dual_coef=np.asarray(svr.dual_coef_, dtype=np.float64).reshape(-1),
            intercept=float(np.asarray(svr.intercept_, dtype=np.float64).reshape(-1)[0]),
            kernel=str(svr.kernel),
            gamma=float(getattr(svr, "_gamma", 1.0)),
            degree=int(svr.degree),
            coef0=float(svr.coef0),
            scaler_mean=(
                np.asarray(getattr(scaler, "mean_", None), dtype=np.float64)
                if scaler is not None and getattr(scaler, "mean_", None) is not None
                else None
            ),
            scaler_scale=(
                np.asarray(getattr(scaler, "scale_", None), dtype=np.float64)
                if scaler is not None and getattr(scaler, "scale_", None) is not None
                else None
            ),
        )

    def to_artifact(self) -> tuple[dict, dict[str, np.ndarray]]:
        metadata = {
            "model_type": "svr",
            "kernel": self.kernel,
            "gamma": self.gamma,
            "degree": self.degree,
            "coef0": self.coef0,
        }
        arrays: dict[str, np.ndarray] = {
            "support_vectors": self.support_vectors,
            "dual_coef": self.dual_coef,
            "intercept": np.asarray([self.intercept], dtype=np.float64),
        }
        if self.scaler_mean is not None:
            arrays["scaler_mean"] = self.scaler_mean
        if self.scaler_scale is not None:
            arrays["scaler_scale"] = self.scaler_scale
        return metadata, arrays

    @classmethod
    def from_artifact(cls, metadata: dict, arrays: dict[str, np.ndarray]) -> SVRExtract:
        return cls(
            support_vectors=arrays["support_vectors"],
            dual_coef=arrays["dual_coef"],
            intercept=float(arrays["intercept"][0]),
            kernel=metadata.get("kernel", "rbf"),
            gamma=float(metadata.get("gamma", 1.0)),
            degree=int(metadata.get("degree", 3)),
            coef0=float(metadata.get("coef0", 0.0)),
            scaler_mean=arrays.get("scaler_mean"),
            scaler_scale=arrays.get("scaler_scale"),
        )

    def predict(self, X: np.ndarray) -> np.ndarray:
        X = np.asarray(X, dtype=np.float64)
        if X.ndim == 1:
            X = X.reshape(1, -1)
        if self.scaler_mean is not None and self.scaler_scale is not None:
            scale = np.where(np.abs(self.scaler_scale) > 1e-12, self.scaler_scale, 1.0)
            X = (X - self.scaler_mean) / scale
        K = self._kernel_matrix(X, self.support_vectors)
        return (K @ self.dual_coef + self.intercept).reshape(-1, 1)

    def _kernel_matrix(self, X: np.ndarray, Y: np.ndarray) -> np.ndarray:
        if self.kernel == "linear":
            return X @ Y.T
        if self.kernel == "poly":
            return (self.gamma * (X @ Y.T) + self.coef0) ** self.degree
        if self.kernel == "sigmoid":
            return np.tanh(self.gamma * (X @ Y.T) + self.coef0)
        # rbf/default
        x2 = np.sum(X**2, axis=1, keepdims=True)
        y2 = np.sum(Y**2, axis=1, keepdims=True).T
        return np.exp(-self.gamma * np.maximum(x2 + y2 - 2 * (X @ Y.T), 0.0))


# ---------------------------------------------------------------------------
# MCRExtract
# ---------------------------------------------------------------------------


@dataclass
class MCRExtract:
    """Version-aware extraction of MCR-ALS outputs.

    Attributes:
        C: Concentration profiles (n_samples, n_components)
        St: Pure component spectra (n_components, n_features)
        n_components: Number of components
    """

    C: np.ndarray  # 2D float64
    St: np.ndarray  # 2D float64
    n_components: int

    @classmethod
    def from_scp(cls, mcr_model: Any) -> MCRExtract:
        """Extract from fitted SCP MCR-ALS model.

        Args:
            mcr_model: Fitted scp.MCRALS instance

        Returns:
            MCRExtract with C and St matrices

        Raises:
            ValueError: If C or St are missing
        """
        require_scp("MCRExtract.from_scp")

        if not hasattr(mcr_model, "C") or mcr_model.C is None:
            raise ValueError("MCR model missing C attribute")
        if not hasattr(mcr_model, "St") or mcr_model.St is None:
            raise ValueError("MCR model missing St attribute")

        C = _to_numpy_2d(mcr_model.C, name="mcr.C")
        St = _to_numpy_2d(mcr_model.St, name="mcr.St")

        n_components = C.shape[1]

        return cls(
            C=C,
            St=St,
            n_components=n_components,
        )

    def to_artifact(self) -> tuple[dict, dict[str, np.ndarray]]:
        """Serialize to (metadata, named_arrays) for ModelStore.save()."""
        metadata = {
            "model_type": "mcr",
            "n_components": self.n_components,
        }
        arrays = {
            "C": self.C,
            "St": self.St,
        }
        return metadata, arrays

    @classmethod
    def from_artifact(cls, metadata: dict, arrays: dict[str, np.ndarray]) -> MCRExtract:
        """Reconstruct from ModelStore.load() output."""
        C = arrays["C"]
        St = arrays["St"]
        return cls(
            C=C,
            St=St,
            n_components=metadata.get("n_components", C.shape[1]),
        )

    def transform(self, X: np.ndarray) -> np.ndarray:
        """Project new data onto pure components: C_new = X @ pinv(St)"""
        X = np.asarray(X, dtype=np.float64)
        if X.ndim == 1:
            X = X.reshape(1, -1)
        return X @ np.linalg.pinv(self.St)


# ---------------------------------------------------------------------------
# NMFExtract
# ---------------------------------------------------------------------------


@dataclass
class NMFExtract:
    """Replayable NMF basis spectra with sklearn-style transform."""

    H: np.ndarray
    n_components: int

    def to_artifact(self) -> tuple[dict, dict[str, np.ndarray]]:
        return {
            "model_type": "nmf",
            "n_components": self.n_components,
        }, {"H": self.H}

    @classmethod
    def from_artifact(cls, metadata: dict, arrays: dict[str, np.ndarray]) -> NMFExtract:
        H = arrays["H"]
        return cls(H=H, n_components=metadata.get("n_components", H.shape[0]))

    def transform(self, X: np.ndarray) -> np.ndarray:
        """Estimate non-negative concentrations for new spectra against H."""
        X = np.asarray(X, dtype=np.float64)
        if X.ndim == 1:
            X = X.reshape(1, -1)
        try:
            from scipy.optimize import nnls

            return np.vstack([nnls(self.H.T, row)[0] for row in X])
        except Exception:
            coefs = X @ np.linalg.pinv(self.H)
            return np.maximum(coefs, 0.0)


# ---------------------------------------------------------------------------
# FastICAExtract
# ---------------------------------------------------------------------------


@dataclass
class FastICAExtract:
    """Replayable FastICA unmixing state with sklearn-style transform."""

    components: np.ndarray
    mean: np.ndarray | None
    mixing: np.ndarray | None
    n_components: int

    def to_artifact(self) -> tuple[dict, dict[str, np.ndarray]]:
        metadata = {
            "model_type": "fastica",
            "n_components": self.n_components,
        }
        arrays: dict[str, np.ndarray] = {"components": self.components}
        if self.mean is not None:
            arrays["mean"] = self.mean
        if self.mixing is not None:
            arrays["mixing"] = self.mixing
        return metadata, arrays

    @classmethod
    def from_artifact(cls, metadata: dict, arrays: dict[str, np.ndarray]) -> FastICAExtract:
        components = arrays["components"]
        return cls(
            components=components,
            mean=arrays.get("mean"),
            mixing=arrays.get("mixing"),
            n_components=metadata.get("n_components", components.shape[0]),
        )

    def transform(self, X: np.ndarray) -> np.ndarray:
        X = np.asarray(X, dtype=np.float64)
        if X.ndim == 1:
            X = X.reshape(1, -1)
        if self.mean is not None:
            X = X - self.mean
        return X @ self.components.T


# ---------------------------------------------------------------------------
# EFAExtract
# ---------------------------------------------------------------------------


@dataclass
class EFAExtract:
    """Version-aware extraction of EFA outputs.

    EFA is a diagnostic technique — it does not produce a predictive model.

    Attributes:
        forward_ev: Forward eigenvalues (n_samples, n_components)
        backward_ev: Backward eigenvalues (n_samples, n_components)
        n_components: Number of components
    """

    forward_ev: np.ndarray | None  # 2D float64
    backward_ev: np.ndarray | None  # 2D float64
    n_components: int

    @classmethod
    def from_scp(cls, efa_model: Any) -> EFAExtract:
        """Extract from fitted SCP EFA model.

        Args:
            efa_model: Fitted scp.EFA instance

        Returns:
            EFAExtract with forward and backward eigenvalues
        """
        require_scp("EFAExtract.from_scp")

        n_components = efa_model.n_components

        # Extract forward eigenvalues
        forward_ev = None
        if hasattr(efa_model, "f_ev") and efa_model.f_ev is not None:
            try:
                forward_ev = _to_numpy_2d(efa_model.f_ev, name="efa.f_ev")
            except Exception as e:
                logger.warning("[EFAExtract] Could not extract f_ev: %s", e)

        # Extract backward eigenvalues
        backward_ev = None
        if hasattr(efa_model, "b_ev") and efa_model.b_ev is not None:
            try:
                backward_ev = _to_numpy_2d(efa_model.b_ev, name="efa.b_ev")
            except Exception as e:
                logger.warning("[EFAExtract] Could not extract b_ev: %s", e)

        return cls(
            forward_ev=forward_ev,
            backward_ev=backward_ev,
            n_components=n_components,
        )

    def to_artifact(self) -> tuple[dict, dict[str, np.ndarray]]:
        """Serialize to (metadata, named_arrays) for ModelStore.save()."""
        metadata = {
            "model_type": "efa",
            "n_components": self.n_components,
        }
        arrays: dict[str, np.ndarray] = {}
        if self.forward_ev is not None:
            arrays["forward_ev"] = self.forward_ev
        if self.backward_ev is not None:
            arrays["backward_ev"] = self.backward_ev
        return metadata, arrays

    @classmethod
    def from_artifact(cls, metadata: dict, arrays: dict[str, np.ndarray]) -> EFAExtract:
        """Reconstruct from ModelStore.load() output."""
        return cls(
            forward_ev=arrays.get("forward_ev"),
            backward_ev=arrays.get("backward_ev"),
            n_components=metadata.get("n_components", 0),
        )


# ---------------------------------------------------------------------------
# SIMPLISMAExtract
# ---------------------------------------------------------------------------


@dataclass
class SIMPLISMAExtract:
    """Version-aware extraction of SIMPLISMA outputs.

    Attributes:
        C: Concentration profiles (n_samples, n_components)
        St: Pure component spectra (n_components, n_features)
        purities: Purity values for each component (if available)
        n_components: Number of components
    """

    C: np.ndarray  # 2D float64
    St: np.ndarray  # 2D float64
    purities: np.ndarray | None  # 1D float64
    n_components: int

    @classmethod
    def from_scp(cls, simplisma_model: Any) -> SIMPLISMAExtract:
        """Extract from fitted SCP SIMPLISMA model.

        Args:
            simplisma_model: Fitted scp.SIMPLISMA instance

        Returns:
            SIMPLISMAExtract with C, St, and purities

        Raises:
            ValueError: If C or St are missing
        """
        require_scp("SIMPLISMAExtract.from_scp")

        if not hasattr(simplisma_model, "C") or simplisma_model.C is None:
            raise ValueError("SIMPLISMA model missing C attribute")
        if not hasattr(simplisma_model, "St") or simplisma_model.St is None:
            raise ValueError("SIMPLISMA model missing St attribute")

        C = _to_numpy_2d(simplisma_model.C, name="simplisma.C")
        St = _to_numpy_2d(simplisma_model.St, name="simplisma.St")

        n_components = C.shape[1]

        # Extract purities if available
        purities = None
        if hasattr(simplisma_model, "purities") and simplisma_model.purities is not None:
            try:
                purities = _to_numpy_1d(simplisma_model.purities, name="purities")
            except Exception as e:
                logger.debug("[SIMPLISMAExtract] Could not extract purities: %s", e)

        return cls(
            C=C,
            St=St,
            purities=purities,
            n_components=n_components,
        )

    def to_artifact(self) -> tuple[dict, dict[str, np.ndarray]]:
        """Serialize to (metadata, named_arrays) for ModelStore.save()."""
        metadata = {
            "model_type": "simplisma",
            "n_components": self.n_components,
        }
        arrays: dict[str, np.ndarray] = {
            "C": self.C,
            "St": self.St,
        }
        if self.purities is not None:
            arrays["purities"] = self.purities
        return metadata, arrays

    @classmethod
    def from_artifact(cls, metadata: dict, arrays: dict[str, np.ndarray]) -> SIMPLISMAExtract:
        """Reconstruct from ModelStore.load() output."""
        C = arrays["C"]
        St = arrays["St"]
        return cls(
            C=C,
            St=St,
            purities=arrays.get("purities"),
            n_components=metadata.get("n_components", C.shape[1]),
        )

    def transform(self, X: np.ndarray) -> np.ndarray:
        """Project new data onto pure components: C_new = X @ pinv(St)"""
        X = np.asarray(X, dtype=np.float64)
        if X.ndim == 1:
            X = X.reshape(1, -1)
        return X @ np.linalg.pinv(self.St)


# ---------------------------------------------------------------------------
# PLSDAExtract — PLS-DA classification
# ---------------------------------------------------------------------------


@dataclass
class PLSDAExtract:
    """Extraction of PLS-DA classification outputs.

    PLS-DA uses PLS regression on dummy-encoded class labels, then converts
    continuous predictions to class assignments via softmax + argmax.

    Attributes:
        coef: Regression coefficients (n_features, n_classes)
        x_mean: Training X mean (n_features,)
        y_mean: Training dummy-Y mean (n_classes,)
        classes: Ordered class labels
        x_loadings: X block loadings (n_features, n_components), optional
        y_loadings: Y block loadings (n_classes, n_components), optional
        n_components: Number of PLS components
    """

    coef: np.ndarray  # (n_features, n_classes) float64
    x_mean: np.ndarray  # (n_features,) float64
    y_mean: np.ndarray  # (n_classes,) float64
    classes: list[str]
    x_loadings: np.ndarray | None = None
    y_loadings: np.ndarray | None = None
    n_components: int = 1

    def to_artifact(self) -> tuple[dict, dict[str, np.ndarray]]:
        """Serialize to (metadata, named_arrays) for ModelStore.save()."""
        metadata = {
            "model_type": "plsda",
            "n_components": self.n_components,
            "classes": self.classes,
        }
        arrays: dict[str, np.ndarray] = {
            "coef": self.coef,
            "x_mean": self.x_mean,
            "y_mean": self.y_mean,
        }
        if self.x_loadings is not None:
            arrays["x_loadings"] = self.x_loadings
        if self.y_loadings is not None:
            arrays["y_loadings"] = self.y_loadings
        return metadata, arrays

    @classmethod
    def from_artifact(cls, metadata: dict, arrays: dict[str, np.ndarray]) -> PLSDAExtract:
        """Reconstruct from ModelStore.load() output."""
        return cls(
            coef=arrays["coef"],
            x_mean=arrays["x_mean"],
            y_mean=arrays["y_mean"],
            classes=metadata.get("classes", []),
            x_loadings=arrays.get("x_loadings"),
            y_loadings=arrays.get("y_loadings"),
            n_components=metadata.get("n_components", 1),
        )

    def predict(self, X: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """Predict class labels from new X data.

        Returns:
            (labels, probabilities) where labels is 1D string array and
            probabilities is (n_samples, n_classes) softmax output.
        """
        from scipy.special import softmax

        X = np.asarray(X, dtype=np.float64)
        if X.ndim == 1:
            X = X.reshape(1, -1)
        # PLS regression on centered data
        y_raw = (X - self.x_mean) @ self.coef + self.y_mean
        probs = softmax(y_raw, axis=1)
        label_indices = np.argmax(probs, axis=1)
        labels = np.array([self.classes[i] for i in label_indices])
        return labels, probs


# ---------------------------------------------------------------------------
# KNNExtract — K-Nearest Neighbors classification
# ---------------------------------------------------------------------------


@dataclass
class KNNExtract:
    """Extraction of KNN classification model.

    KNN IS the training data — the "model" is the stored reference samples
    plus the distance metric and voting scheme.

    Attributes:
        X_train: Training feature matrix (n_train, n_features)
        y_train_encoded: Integer-encoded training labels (n_train,)
        classes: Ordered class labels (index matches y_train_encoded values)
        k: Number of neighbors
        metric: Distance metric name
        weights: Weighting scheme ("uniform" or "distance")
    """

    X_train: np.ndarray  # (n_train, n_features) float64
    y_train_encoded: np.ndarray  # (n_train,) int
    classes: list[str]
    k: int = 5
    metric: str = "euclidean"
    weights: str = "uniform"
    x_mean: np.ndarray | None = None
    x_scale: np.ndarray | None = None

    def to_artifact(self) -> tuple[dict, dict[str, np.ndarray]]:
        """Serialize to (metadata, named_arrays) for ModelStore.save()."""
        n_train = self.X_train.shape[0]
        estimated_bytes = self.X_train.nbytes + self.y_train_encoded.nbytes
        if estimated_bytes > 10 * 1024 * 1024:  # 10 MB
            logger.warning(
                "[KNNExtract] Large KNN artifact: %d training samples, "
                "~%.1f MB uncompressed. Consider reducing training set size.",
                n_train,
                estimated_bytes / (1024 * 1024),
            )
        metadata = {
            "model_type": "knn",
            "k": self.k,
            "metric": self.metric,
            "weights": self.weights,
            "classes": self.classes,
            "n_train_samples": n_train,
        }
        arrays = {
            "X_train": self.X_train,
            "y_train_encoded": self.y_train_encoded.astype(np.int64),
        }
        if self.x_mean is not None:
            arrays["x_mean"] = self.x_mean
        if self.x_scale is not None:
            arrays["x_scale"] = self.x_scale
        return metadata, arrays

    @classmethod
    def from_artifact(cls, metadata: dict, arrays: dict[str, np.ndarray]) -> KNNExtract:
        """Reconstruct from ModelStore.load() output."""
        return cls(
            X_train=arrays["X_train"],
            y_train_encoded=arrays["y_train_encoded"].astype(np.int64),
            classes=metadata.get("classes", []),
            k=metadata.get("k", 5),
            metric=metadata.get("metric", "euclidean"),
            weights=metadata.get("weights", "uniform"),
            x_mean=arrays.get("x_mean"),
            x_scale=arrays.get("x_scale"),
        )

    def predict(self, X: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """Predict class labels using k-nearest neighbor voting.

        Returns:
            (labels, probabilities) where labels is 1D string array and
            probabilities is (n_samples, n_classes) vote fractions.
        """
        from scipy.spatial.distance import cdist

        X = np.asarray(X, dtype=np.float64)
        if X.ndim == 1:
            X = X.reshape(1, -1)
        if self.x_mean is not None and self.x_scale is not None:
            safe_scale = np.where(np.abs(self.x_scale) > 1e-12, self.x_scale, 1.0)
            X = (X - self.x_mean) / safe_scale

        n_samples = X.shape[0]
        n_classes = len(self.classes)
        dists = cdist(X, self.X_train, metric=self.metric)

        # For each sample, find k nearest neighbors
        n_train = self.X_train.shape[0]
        k = min(self.k, n_train)
        if k >= n_train:
            # Use all training samples (no need to partition)
            k_nearest_idx = np.tile(np.arange(n_train), (n_samples, 1))
        else:
            k_nearest_idx = np.argpartition(dists, k, axis=1)[:, :k]

        labels = np.empty(n_samples, dtype=object)
        probs = np.zeros((n_samples, n_classes), dtype=np.float64)

        for i in range(n_samples):
            neighbor_idx = k_nearest_idx[i]
            neighbor_labels = self.y_train_encoded[neighbor_idx]
            neighbor_dists = dists[i, neighbor_idx]

            if self.weights == "distance":
                w = 1.0 / (neighbor_dists + 1e-10)
            else:
                w = np.ones_like(neighbor_dists)

            for j in range(n_classes):
                mask = neighbor_labels == j
                probs[i, j] = w[mask].sum()

            # Normalize to probabilities
            total = probs[i].sum()
            if total > 0:
                probs[i] /= total

            labels[i] = self.classes[int(np.argmax(probs[i]))]

        return labels, probs


# ---------------------------------------------------------------------------
# SIMCAExtract — SIMCA classification
# ---------------------------------------------------------------------------


@dataclass
class SIMCAExtract:
    """Extraction of SIMCA classification model.

    SIMCA builds per-class PCA models and classifies new samples by their
    T² and Q residual distances to each class model.

    Attributes:
        class_loadings: {label: (n_components, n_features)} PCA loadings per class
        class_eigenvalues: {label: (n_components,)} eigenvalues per class
        class_means: {label: (n_features,)} class mean spectra
        classes: Ordered class labels
        T2_limits: {label: float} Hotelling T² confidence limits
        Q_limits: {label: float} SPE confidence limits
        n_components: Number of PCA components per class model
    """

    class_loadings: dict[str, np.ndarray]  # label → (n_comp, n_feat)
    class_eigenvalues: dict[str, np.ndarray]  # label → (n_comp,)
    class_means: dict[str, np.ndarray]  # label → (n_feat,)
    classes: list[str]
    T2_limits: dict[str, float]
    Q_limits: dict[str, float]
    class_scales: dict[str, np.ndarray] | None = None
    pca_means: dict[str, np.ndarray] | None = None
    n_components: int = 3

    def to_artifact(self) -> tuple[dict, dict[str, np.ndarray]]:
        """Serialize to (metadata, named_arrays) for ModelStore.save().

        Per-class arrays use keys like ``class_0_loadings``, ``class_0_mean``
        where the index matches the position in ``classes``.
        """
        metadata = {
            "model_type": "simca",
            "n_components": self.n_components,
            "classes": self.classes,
            "T2_limits": {label: float(v) for label, v in self.T2_limits.items()},
            "Q_limits": {label: float(v) for label, v in self.Q_limits.items()},
        }
        arrays: dict[str, np.ndarray] = {}
        for idx, label in enumerate(self.classes):
            if label in self.class_loadings:
                arrays[f"class_{idx}_loadings"] = self.class_loadings[label]
            if label in self.class_eigenvalues:
                arrays[f"class_{idx}_eigenvalues"] = self.class_eigenvalues[label]
            if label in self.class_means:
                arrays[f"class_{idx}_mean"] = self.class_means[label]
            if self.class_scales and label in self.class_scales:
                arrays[f"class_{idx}_scale"] = self.class_scales[label]
            if self.pca_means and label in self.pca_means:
                arrays[f"class_{idx}_pca_mean"] = self.pca_means[label]
        return metadata, arrays

    @classmethod
    def from_artifact(cls, metadata: dict, arrays: dict[str, np.ndarray]) -> SIMCAExtract:
        """Reconstruct from ModelStore.load() output."""
        classes = metadata.get("classes", [])
        class_loadings: dict[str, np.ndarray] = {}
        class_eigenvalues: dict[str, np.ndarray] = {}
        class_means: dict[str, np.ndarray] = {}
        class_scales: dict[str, np.ndarray] = {}
        pca_means: dict[str, np.ndarray] = {}

        for idx, label in enumerate(classes):
            key_load = f"class_{idx}_loadings"
            key_ev = f"class_{idx}_eigenvalues"
            key_mean = f"class_{idx}_mean"
            key_scale = f"class_{idx}_scale"
            key_pca_mean = f"class_{idx}_pca_mean"
            if key_load in arrays:
                class_loadings[label] = arrays[key_load]
            if key_ev in arrays:
                class_eigenvalues[label] = arrays[key_ev]
            if key_mean in arrays:
                class_means[label] = arrays[key_mean]
            if key_scale in arrays:
                class_scales[label] = arrays[key_scale]
            if key_pca_mean in arrays:
                pca_means[label] = arrays[key_pca_mean]

        return cls(
            class_loadings=class_loadings,
            class_eigenvalues=class_eigenvalues,
            class_means=class_means,
            classes=classes,
            T2_limits=metadata.get("T2_limits", {}),
            Q_limits=metadata.get("Q_limits", {}),
            class_scales=class_scales or None,
            pca_means=pca_means or None,
            n_components=metadata.get("n_components", 3),
        )

    def predict(self, X: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """Classify new samples by minimum combined distance to class models.

        For each class:
        1. Center: X_c = X - class_mean
        2. Project: scores = X_c @ loadings.T
        3. Reconstruct: X_hat = scores @ loadings + class_mean
        4. T² = sum((scores / sqrt(eigenvalues))²)
        5. Q = sum((X - X_hat)²)  (SPE residual)
        6. Combined distance = T²/T²_limit + Q/Q_limit

        Returns:
            (labels, probabilities) where labels is 1D string array and
            probabilities is (n_samples, n_classes) array of inverse-distance
            scores normalized to sum to 1 (higher = closer to class).
        """
        X = np.asarray(X, dtype=np.float64)
        if X.ndim == 1:
            X = X.reshape(1, -1)

        n_samples = X.shape[0]
        n_classes = len(self.classes)
        labels = np.empty(n_samples, dtype=object)
        dist_matrix = np.zeros((n_samples, n_classes), dtype=np.float64)

        for i in range(n_samples):
            sample = X[i]

            for j, label in enumerate(self.classes):
                loadings = self.class_loadings[label]
                eigenvalues = self.class_eigenvalues[label]
                class_mean = self.class_means[label]
                class_scale = self.class_scales.get(label) if self.class_scales else None
                pca_mean = self.pca_means.get(label) if self.pca_means else None
                T2_lim = self.T2_limits.get(label, 1.0)
                Q_lim = self.Q_limits.get(label, 1.0)

                if class_scale is not None:
                    safe_scale = np.maximum(class_scale, 1e-12)
                    working = (sample - class_mean) / safe_scale
                    pca_center = pca_mean if pca_mean is not None else np.zeros_like(working)
                    centered = working - pca_center
                else:
                    centered = sample - class_mean
                    pca_center = np.zeros_like(centered)
                scores = centered @ loadings.T  # (n_comp,)
                reconstructed = scores @ loadings + pca_center  # (n_feat,)
                residual = (working if class_scale is not None else sample - class_mean) - reconstructed

                # T² statistic
                safe_ev = np.maximum(eigenvalues, 1e-12)
                t2 = float(np.sum((scores**2) / safe_ev))

                # Q statistic (SPE)
                q = float(np.sum(residual**2))

                # Combined normalized distance
                combined = t2 / max(T2_lim, 1e-12) + q / max(Q_lim, 1e-12)
                dist_matrix[i, j] = combined

            accepted = []
            for j, label in enumerate(self.classes):
                t2_limit = max(float(self.T2_limits.get(label, 1.0)), 1e-12)
                q_limit = max(float(self.Q_limits.get(label, 1.0)), 1e-12)
                loadings = self.class_loadings[label]
                class_mean = self.class_means[label]
                class_scale = self.class_scales.get(label) if self.class_scales else None
                pca_mean = self.pca_means.get(label) if self.pca_means else None
                if class_scale is not None:
                    safe_scale = np.maximum(class_scale, 1e-12)
                    working = (sample - class_mean) / safe_scale
                    pca_center = pca_mean if pca_mean is not None else np.zeros_like(working)
                    centered = working - pca_center
                    scores = centered @ loadings.T
                    reconstructed = scores @ loadings + pca_center
                    residual = working - reconstructed
                else:
                    centered = sample - class_mean
                    scores = centered @ loadings.T
                    residual = centered - scores @ loadings
                safe_ev = np.maximum(self.class_eigenvalues[label], 1e-12)
                t2 = float(np.sum((scores**2) / safe_ev))
                q = float(np.sum(residual**2))
                if t2 <= t2_limit and q <= q_limit:
                    accepted.append((label, dist_matrix[i, j]))

            if accepted:
                labels[i] = min(accepted, key=lambda item: item[1])[0]
            else:
                labels[i] = "unassigned"

        # Convert distances to probabilities: inverse distance, normalized
        inv_dist = 1.0 / (dist_matrix + 1e-12)
        row_sums = inv_dist.sum(axis=1, keepdims=True)
        probs = inv_dist / row_sums

        return labels, probs


# ---------------------------------------------------------------------------
# Extract registry — maps model_type → Extract class
# ---------------------------------------------------------------------------

EXTRACT_REGISTRY: dict[str, type] = {
    "pca": PCAExtract,
    "pls": PLSExtract,
    "pcr": PCRExtract,
    "linear_regression": LinearRegressionExtract,
    "svr": SVRExtract,
    "mcr": MCRExtract,
    "nmf": NMFExtract,
    "fastica": FastICAExtract,
    "efa": EFAExtract,
    "simplisma": SIMPLISMAExtract,
    "plsda": PLSDAExtract,
    "knn": KNNExtract,
    "simca": SIMCAExtract,
}


__all__ = [
    "PCAExtract",
    "PLSExtract",
    "PCRExtract",
    "LinearRegressionExtract",
    "SVRExtract",
    "MCRExtract",
    "NMFExtract",
    "FastICAExtract",
    "EFAExtract",
    "SIMPLISMAExtract",
    "PLSDAExtract",
    "KNNExtract",
    "SIMCAExtract",
    "EXTRACT_REGISTRY",
]
