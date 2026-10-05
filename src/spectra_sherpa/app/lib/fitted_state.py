"""
Typed fitted-state extraction and artifact classes.

Centralizes fitted-model projection for regression, decomposition,
classification, and the three optional EFA/MCR-ALS/SIMPLISMA operations.
The optional runtime is loaded only by the private interoperability adapter;
this module imports no optional runtime and owns only native NumPy state.

Each Extract also provides:
- to_artifact() / from_artifact(): Serialize to/from ModelStore format
- predict() or transform(): Pure-numpy inference (no SCP/sklearn required)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, ClassVar

import numpy as np

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _safe_getattr(obj: Any, names: tuple[str, ...]) -> Any | None:
    """Try attribute names in order, returning first non-None.

    Catches exceptions from property descriptors that may raise
    (external estimators may wrap state in properties that can fail).
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
    """Safely unwrap an external model value or array-like to NumPy."""
    if value is None:
        raise ValueError(f"{name} is None")

    # External scientific model values expose their numerical state as .data.
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
        # Local import avoids making the broad artifact-schema module a
        # package-initialization dependency of the canonical node registry.
        from spectra_sherpa.app.services.dag.nodes.modeling.pls_core import apply_pls_affine_state

        coefficients = np.asarray(self.coef, dtype=np.float64)
        if coefficients.ndim == 1:
            coefficients = coefficients.reshape(-1, 1)
        return apply_pls_affine_state(
            X,
            coefficients=coefficients,
            feature_offset=(np.zeros(coefficients.shape[0], dtype=np.float64) if self.x_mean is None else self.x_mean),
            prediction_offset=(
                np.zeros(coefficients.shape[1], dtype=np.float64) if self.y_mean is None else self.y_mean
            ),
        )

    def applicability_diagnostics(self, X: np.ndarray) -> dict[str, Any]:
        """Legacy point state lacks exact projection and qualified limit authority.

        Stored loadings do not establish the SIMPLS application projection.
        Preserve historical artifacts, but never turn absent limits into passes.
        """
        matrix = np.asarray(X)
        rows = 1 if matrix.ndim == 1 else matrix.shape[0]
        return {
            "type": "pls_applicability",
            "claim_scope": "unavailable_legacy_authority",
            "unavailable_reason": "refit_required_for_exact_projection_and_screening_authority",
            "method": None,
            "hotelling_t2": None,
            "q_residuals": None,
            "t2_limit": None,
            "q_limit": None,
            "t2_outlier": [None] * rows,
            "q_outlier": [None] * rows,
            "out_of_domain": [None] * rows,
            "n_out_of_domain": None,
            "applicability_status": "unqualified",
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
        coefficient_matrix = np.asarray(self.reg_coef, dtype=np.float64)
        targets = 1 if coefficient_matrix.ndim == 1 else int(coefficient_matrix.shape[0])
        metadata = {
            "model_type": "pcr",
            "serializer": "spectrasherpa.model-artifact.pcr/1",
            "n_components": self.n_components,
            "scale": self.scaler_mean is not None,
            "features": int(self.pca_components.shape[1]),
            "target_count": targets,
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
        if metadata.get("model_type") != "pcr" or metadata.get("serializer") != "spectrasherpa.model-artifact.pcr/1":
            raise ValueError("PCR artifact has an invalid model or serializer identity")
        for name in ("n_components", "features", "target_count"):
            if type(metadata.get(name)) is not int or metadata[name] < 1:
                raise ValueError(f"PCR artifact has invalid {name}")
        if not isinstance(metadata.get("scale"), bool):
            raise ValueError("PCR artifact has an invalid scale flag")
        fitted_parameters = metadata.get("fitted_parameters")
        if fitted_parameters is not None and fitted_parameters != {
            "n_components": metadata["n_components"],
            "scale": metadata["scale"],
        }:
            raise ValueError("PCR artifact fitted parameters contradict its replay state")
        required_arrays = {"pca_components", "pca_mean", "reg_coef", "reg_intercept"}
        if metadata["scale"]:
            required_arrays.update({"scaler_mean", "scaler_scale"})
        if set(arrays) != required_arrays:
            raise ValueError("PCR artifact arrays do not match its closed serializer schema")
        components = np.asarray(arrays["pca_components"], dtype=np.float64)
        pca_mean = np.asarray(arrays["pca_mean"], dtype=np.float64)
        coefficients = np.asarray(arrays["reg_coef"], dtype=np.float64)
        intercept = np.asarray(arrays["reg_intercept"], dtype=np.float64)
        expected_coef = (
            (metadata["n_components"],)
            if coefficients.ndim == 1 and metadata["target_count"] == 1
            else (metadata["target_count"], metadata["n_components"])
        )
        if (
            components.shape != (metadata["n_components"], metadata["features"])
            or pca_mean.shape != (metadata["features"],)
            or coefficients.shape != expected_coef
            or intercept.shape != (metadata["target_count"],)
            or not all(np.isfinite(value).all() for value in (components, pca_mean, coefficients, intercept))
        ):
            raise ValueError("PCR artifact state dimensions or values are invalid")
        scaler_mean = arrays.get("scaler_mean")
        scaler_scale = arrays.get("scaler_scale")
        if metadata["scale"]:
            if scaler_mean is None or scaler_scale is None:
                raise ValueError("autoscaled PCR artifact is missing scaler state")
            scaler_mean = np.asarray(scaler_mean, dtype=np.float64)
            scaler_scale = np.asarray(scaler_scale, dtype=np.float64)
            if (
                scaler_mean.shape != (metadata["features"],)
                or scaler_scale.shape != (metadata["features"],)
                or not np.isfinite(scaler_mean).all()
                or not np.isfinite(scaler_scale).all()
                or np.any(scaler_scale <= 0)
            ):
                raise ValueError("PCR artifact scaler state is invalid")
        elif scaler_mean is not None or scaler_scale is not None:
            raise ValueError("unscaled PCR artifact must not carry scaler state")
        return cls(
            pca_components=components,
            pca_mean=pca_mean,
            reg_coef=coefficients,
            reg_intercept=intercept,
            n_components=metadata["n_components"],
            scaler_mean=scaler_mean,
            scaler_scale=scaler_scale,
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
    fit_intercept: bool = True

    @classmethod
    def from_sklearn(cls, model: Any) -> LinearRegressionExtract:
        coef = np.asarray(model.coef_, dtype=np.float64)
        target_count = 1 if coef.ndim == 1 else int(coef.shape[0])
        intercept = np.asarray(model.intercept_, dtype=np.float64).reshape(-1)
        if intercept.size == 1 and target_count > 1 and not bool(model.fit_intercept):
            intercept = np.zeros(target_count, dtype=np.float64)
        return cls(
            coef=coef,
            intercept=intercept,
            fit_intercept=bool(model.fit_intercept),
        )

    def to_artifact(self) -> tuple[dict, dict[str, np.ndarray]]:
        return {
            "model_type": "linear_regression",
            "fit_intercept": self.fit_intercept,
            "target_count": 1 if self.coef.ndim == 1 else int(self.coef.shape[0]),
        }, {"coef": self.coef, "intercept": self.intercept}

    @classmethod
    def from_artifact(cls, metadata: dict, arrays: dict[str, np.ndarray]) -> LinearRegressionExtract:
        if not isinstance(metadata.get("fit_intercept"), bool):
            raise ValueError("linear-regression artifact is missing its fit_intercept identity")
        target_count = metadata.get("target_count")
        if type(target_count) is not int or target_count < 1:
            raise ValueError("linear-regression artifact has an invalid target count")
        coef = np.asarray(arrays["coef"], dtype=np.float64)
        if coef.ndim not in {1, 2} or coef.shape[-1] < 1 or not np.isfinite(coef).all():
            raise ValueError("linear-regression artifact has invalid coefficients")
        actual_targets = 1 if coef.ndim == 1 else int(coef.shape[0])
        if actual_targets != target_count:
            raise ValueError("linear-regression artifact target count does not match its coefficients")
        intercept = np.asarray(arrays["intercept"], dtype=np.float64)
        if intercept.ndim != 1 or intercept.shape != (target_count,) or not np.isfinite(intercept).all():
            raise ValueError("linear-regression artifact intercept does not match its target count")
        if not metadata["fit_intercept"] and np.any(intercept != 0.0):
            raise ValueError("through-origin linear-regression artifact must have zero intercepts")
        return cls(
            coef=coef,
            intercept=intercept,
            fit_intercept=metadata["fit_intercept"],
        )

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
            "serializer": "spectrasherpa.model-artifact.svr/1",
            "kernel": self.kernel,
            "gamma": self.gamma,
            "degree": self.degree,
            "coef0": self.coef0,
            "scale": self.scaler_mean is not None,
            "features": int(self.support_vectors.shape[1]),
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
        if metadata.get("model_type") != "svr" or metadata.get("serializer") != "spectrasherpa.model-artifact.svr/1":
            raise ValueError("SVR artifact has an invalid model or serializer identity")
        kernel = metadata.get("kernel")
        if kernel not in {"linear", "poly", "rbf", "sigmoid"}:
            raise ValueError("SVR artifact has an unsupported kernel")
        gamma = metadata.get("gamma")
        coef0 = metadata.get("coef0")
        if (
            isinstance(gamma, bool)
            or not isinstance(gamma, (int, float))
            or not np.isfinite(gamma)
            or float(gamma) <= 0
            or isinstance(coef0, bool)
            or not isinstance(coef0, (int, float))
            or not np.isfinite(coef0)
        ):
            raise ValueError("SVR artifact has invalid kernel parameters")
        degree = metadata.get("degree")
        features = metadata.get("features")
        if type(degree) is not int or degree < 1 or type(features) is not int or features < 1:
            raise ValueError("SVR artifact has invalid dimensions or degree")
        if not isinstance(metadata.get("scale"), bool):
            raise ValueError("SVR artifact has an invalid scale flag")
        fitted_parameters = metadata.get("fitted_parameters")
        if fitted_parameters is not None:
            if not isinstance(fitted_parameters, dict) or set(fitted_parameters) != {
                "kernel",
                "C",
                "epsilon",
                "gamma",
                "degree",
                "coef0",
                "target_index",
                "scale",
            }:
                raise ValueError("SVR artifact has invalid fitted parameters")
            fitted_C = fitted_parameters["C"]
            fitted_epsilon = fitted_parameters["epsilon"]
            fitted_gamma = fitted_parameters["gamma"]
            fitted_target_index = fitted_parameters["target_index"]
            if (
                isinstance(fitted_C, bool)
                or not isinstance(fitted_C, (int, float))
                or not np.isfinite(fitted_C)
                or float(fitted_C) <= 0
                or isinstance(fitted_epsilon, bool)
                or not isinstance(fitted_epsilon, (int, float))
                or not np.isfinite(fitted_epsilon)
                or float(fitted_epsilon) < 0
                or not isinstance(fitted_gamma, str)
                or fitted_gamma not in {"scale", "auto"}
                or type(fitted_target_index) is not int
                or fitted_target_index < 1
            ):
                raise ValueError("SVR artifact has invalid fitted parameters")
            if (
                fitted_parameters["kernel"] != kernel
                or fitted_parameters["degree"] != degree
                or fitted_parameters["coef0"] != coef0
                or fitted_parameters["scale"] is not metadata["scale"]
            ):
                raise ValueError("SVR artifact fitted parameters contradict its replay state")
        required_arrays = {"support_vectors", "dual_coef", "intercept"}
        if metadata["scale"]:
            required_arrays.update({"scaler_mean", "scaler_scale"})
        if set(arrays) != required_arrays:
            raise ValueError("SVR artifact arrays do not match its closed serializer schema")
        support_vectors = np.asarray(arrays["support_vectors"], dtype=np.float64)
        dual_coef = np.asarray(arrays["dual_coef"], dtype=np.float64)
        intercept_array = np.asarray(arrays["intercept"], dtype=np.float64)
        if (
            support_vectors.ndim != 2
            or support_vectors.shape[0] < 1
            or support_vectors.shape[1] != features
            or dual_coef.shape != (support_vectors.shape[0],)
            or intercept_array.shape != (1,)
            or not all(np.isfinite(value).all() for value in (support_vectors, dual_coef, intercept_array))
        ):
            raise ValueError("SVR artifact state dimensions or values are invalid")
        scaler_mean = arrays.get("scaler_mean")
        scaler_scale = arrays.get("scaler_scale")
        if metadata["scale"]:
            if scaler_mean is None or scaler_scale is None:
                raise ValueError("autoscaled SVR artifact is missing scaler state")
            scaler_mean = np.asarray(scaler_mean, dtype=np.float64)
            scaler_scale = np.asarray(scaler_scale, dtype=np.float64)
            if (
                scaler_mean.shape != (features,)
                or scaler_scale.shape != (features,)
                or not np.isfinite(scaler_mean).all()
                or not np.isfinite(scaler_scale).all()
                or np.any(scaler_scale <= 0)
            ):
                raise ValueError("SVR artifact scaler state is invalid")
        elif scaler_mean is not None or scaler_scale is not None:
            raise ValueError("unscaled SVR artifact must not carry scaler state")
        return cls(
            support_vectors=support_vectors,
            dual_coef=dual_coef,
            intercept=float(intercept_array[0]),
            kernel=kernel,
            gamma=float(gamma),
            degree=degree,
            coef0=float(coef0),
            scaler_mean=scaler_mean,
            scaler_scale=scaler_scale,
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
    concentration_solver: str = "nnls"

    SERIALIZER = "spectrasherpa.model-artifact.mcr-als/1"

    def to_artifact(self) -> tuple[dict, dict[str, np.ndarray]]:
        """Serialize to (metadata, named_arrays) for ModelStore.save()."""
        metadata = {
            "model_type": "mcr",
            "n_components": self.n_components,
            "serializer": self.SERIALIZER,
            "concentration_solver": self.concentration_solver,
        }
        arrays = {
            "C": self.C,
            "St": self.St,
        }
        return metadata, arrays

    @classmethod
    def from_artifact(cls, metadata: dict, arrays: dict[str, np.ndarray]) -> MCRExtract:
        """Reconstruct from ModelStore.load() output."""
        if metadata.get("model_type") != "mcr" or metadata.get("serializer") != cls.SERIALIZER:
            raise ValueError("MCR artifact has an unsupported model or serializer identity")
        concentration_solver = metadata.get("concentration_solver")
        if concentration_solver not in {"nnls", "lstsq"}:
            raise ValueError("MCR artifact has an unsupported concentration solver")
        if set(arrays) != {"C", "St"}:
            raise ValueError("MCR artifact arrays must contain exactly C and St")
        C = _to_numpy_2d(arrays["C"], name="mcr.C")
        St = _to_numpy_2d(arrays["St"], name="mcr.St")
        n_components = metadata.get("n_components")
        if type(n_components) is not int or n_components < 2:
            raise ValueError("MCR artifact has an invalid component count")
        if C.shape[1] != n_components or St.shape[0] != n_components:
            raise ValueError("MCR artifact component dimensions are inconsistent")
        if not np.isfinite(C).all() or not np.isfinite(St).all():
            raise ValueError("MCR artifact arrays must be finite")
        return cls(
            C=C,
            St=St,
            n_components=n_components,
            concentration_solver=concentration_solver,
        )

    def transform(self, X: np.ndarray) -> np.ndarray:
        """Resolve concentrations with the solver policy recorded at fit time."""
        X = np.asarray(X, dtype=np.float64)
        if X.ndim == 1:
            X = X.reshape(1, -1)
        if X.shape[1] != self.St.shape[1] or not np.isfinite(X).all():
            raise ValueError("MCR application matrix does not match the fitted spectral axis")
        if self.concentration_solver == "nnls":
            from scipy.optimize import nnls

            return np.vstack([nnls(self.St.T, row)[0] for row in X])
        if self.concentration_solver == "lstsq":
            return np.linalg.lstsq(self.St.T, X.T, rcond=None)[0].T
        raise ValueError("MCR artifact has an unsupported concentration solver")


# ---------------------------------------------------------------------------
# NMFExtract
# ---------------------------------------------------------------------------


@dataclass
class NMFExtract:
    """Replayable NMF basis spectra with sklearn-style transform."""

    H: np.ndarray
    n_components: int
    solver: str
    max_iter: int
    tol: float
    random_state: int

    def to_artifact(self) -> tuple[dict, dict[str, np.ndarray]]:
        return {
            "model_type": "nmf",
            "n_components": self.n_components,
            "solver": self.solver,
            "max_iter": self.max_iter,
            "tol": self.tol,
            "random_state": self.random_state,
        }, {"H": self.H}

    @classmethod
    def from_artifact(cls, metadata: dict, arrays: dict[str, np.ndarray]) -> NMFExtract:
        from spectra_sherpa.app.lib.nmf_core import canonical_nmf_parameters

        H = arrays["H"]
        parameters = canonical_nmf_parameters(
            {
                "n_components": metadata.get("n_components"),
                "solver": metadata.get("solver"),
                "max_iter": metadata.get("max_iter"),
                "tol": metadata.get("tol"),
                "random_state": metadata.get("random_state"),
            }
        )
        return cls(H=H, **parameters)

    def transform(self, X: np.ndarray) -> np.ndarray:
        """Estimate non-negative concentrations for new spectra against H."""
        from spectra_sherpa.app.lib.nmf_core import apply_nmf_basis

        return apply_nmf_basis(
            X,
            components=self.H,
            parameters={
                "n_components": self.n_components,
                "solver": self.solver,
                "max_iter": self.max_iter,
                "tol": self.tol,
                "random_state": self.random_state,
            },
        )


# ---------------------------------------------------------------------------
# FastICAExtract
# ---------------------------------------------------------------------------


@dataclass
class FastICAExtract:
    """Replayable FastICA unmixing state with sklearn-style transform."""

    SERIALIZER: ClassVar[str] = "spectrasherpa.model-artifact.fastica/1"

    components: np.ndarray
    mean: np.ndarray
    mixing: np.ndarray
    n_components: int
    n_features: int
    algorithm: str
    fun: str
    whiten: str
    random_seed: int
    sign_rule: str = "largest_absolute_mixing_loading_positive"
    order_rule: str = "descending_reconstruction_contribution"

    def __post_init__(self) -> None:
        self.components = np.asarray(self.components, dtype=np.float64)
        self.mean = np.asarray(self.mean, dtype=np.float64)
        self.mixing = np.asarray(self.mixing, dtype=np.float64)
        if type(self.n_components) is not int or self.n_components < 2:
            raise ValueError("FastICA artifact n_components must be an integer >= 2")
        if type(self.n_features) is not int or self.n_features < self.n_components:
            raise ValueError("FastICA artifact n_features must be an integer >= n_components")
        if self.components.shape != (self.n_components, self.n_features):
            raise ValueError("FastICA artifact has an invalid unmixing-matrix shape")
        if self.mean.shape != (self.n_features,):
            raise ValueError("FastICA artifact has an invalid mean-vector shape")
        if self.mixing.shape != (self.n_features, self.n_components):
            raise ValueError("FastICA artifact has an invalid mixing-matrix shape")
        if not all(np.isfinite(value).all() for value in (self.components, self.mean, self.mixing)):
            raise ValueError("FastICA artifact arrays must be finite")
        if self.algorithm not in {"parallel", "deflation"}:
            raise ValueError("FastICA artifact algorithm is unsupported")
        if self.fun not in {"logcosh", "exp", "cube"}:
            raise ValueError("FastICA artifact contrast function is unsupported")
        if self.whiten not in {"unit-variance", "arbitrary-variance"}:
            raise ValueError("FastICA artifact whitening policy is unsupported")
        if type(self.random_seed) is not int or not 0 <= self.random_seed <= 2_147_483_647:
            raise ValueError("FastICA artifact random seed is invalid")
        if self.sign_rule != "largest_absolute_mixing_loading_positive":
            raise ValueError("FastICA artifact sign convention is unsupported")
        if self.order_rule != "descending_reconstruction_contribution":
            raise ValueError("FastICA artifact component ordering is unsupported")

    def to_artifact(self) -> tuple[dict, dict[str, np.ndarray]]:
        metadata = {
            "model_type": "fastica",
            "serializer": self.SERIALIZER,
            "n_components": self.n_components,
            "n_features": self.n_features,
            "algorithm": self.algorithm,
            "fun": self.fun,
            "whiten": self.whiten,
            "random_seed": self.random_seed,
            "sign_rule": self.sign_rule,
            "order_rule": self.order_rule,
        }
        arrays: dict[str, np.ndarray] = {
            "components": self.components,
            "mean": self.mean,
            "mixing": self.mixing,
        }
        return metadata, arrays

    @classmethod
    def from_artifact(cls, metadata: dict, arrays: dict[str, np.ndarray]) -> FastICAExtract:
        required_metadata = {
            "model_type",
            "serializer",
            "n_components",
            "n_features",
            "algorithm",
            "fun",
            "whiten",
            "random_seed",
            "sign_rule",
            "order_rule",
        }
        if not required_metadata.issubset(metadata):
            raise ValueError("FastICA artifact metadata is incomplete")
        if metadata["model_type"] != "fastica" or metadata["serializer"] != cls.SERIALIZER:
            raise ValueError("FastICA artifact identity is invalid")
        if set(arrays) != {"components", "mean", "mixing"}:
            raise ValueError("FastICA artifact arrays are not closed")
        return cls(
            components=arrays["components"],
            mean=arrays["mean"],
            mixing=arrays["mixing"],
            n_components=metadata["n_components"],
            n_features=metadata["n_features"],
            algorithm=metadata["algorithm"],
            fun=metadata["fun"],
            whiten=metadata["whiten"],
            random_seed=metadata["random_seed"],
            sign_rule=metadata["sign_rule"],
            order_rule=metadata["order_rule"],
        )

    def transform(self, X: np.ndarray) -> np.ndarray:
        X = np.asarray(X, dtype=np.float64)
        if X.ndim == 1:
            X = X.reshape(1, -1)
        if X.ndim != 2 or X.shape[1] != self.n_features or not np.isfinite(X).all():
            raise ValueError("FastICA application data must be finite and match the fitted feature count")
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
    scale: bool = False
    x_mean: np.ndarray | None = None
    x_scale: np.ndarray | None = None

    def _validated_state(self) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
        """Return the closed replay state after scientific validation."""

        training = np.asarray(self.X_train, dtype=np.float64)
        encoded = np.asarray(self.y_train_encoded)
        if training.ndim != 2 or training.shape[0] < 2 or training.shape[1] < 1 or not np.isfinite(training).all():
            raise ValueError("KNN artifact has an invalid training matrix")
        if encoded.ndim != 1 or encoded.shape[0] != training.shape[0] or not np.issubdtype(encoded.dtype, np.integer):
            raise ValueError("KNN artifact has invalid encoded training labels")
        encoded = encoded.astype(np.int64, copy=False)
        if (
            not isinstance(self.classes, list)
            or len(self.classes) < 2
            or any(not isinstance(label, str) or not label for label in self.classes)
            or len(set(self.classes)) != len(self.classes)
            or set(encoded.tolist()) != set(range(len(self.classes)))
        ):
            raise ValueError("KNN artifact has invalid class identity")
        if type(self.k) is not int or self.k < 1 or self.k > training.shape[0]:
            raise ValueError("KNN artifact has an invalid neighbor count")
        if not isinstance(self.weights, str) or self.weights not in {"uniform", "distance"}:
            raise ValueError("KNN artifact has an unsupported weight rule")
        if not isinstance(self.metric, str) or self.metric not in {"euclidean", "manhattan", "chebyshev", "minkowski"}:
            raise ValueError("KNN artifact has an unsupported distance metric")
        if not isinstance(self.scale, bool):
            raise ValueError("KNN artifact has an invalid scaling rule")
        if (self.x_mean is None) != (self.x_scale is None):
            raise ValueError("KNN artifact scaling state is incomplete")
        if self.x_mean is None and self.x_scale is None:
            if self.scale:
                raise ValueError("scaled KNN artifact must carry fitted scaling vectors")
            mean = np.zeros(training.shape[1], dtype=np.float64)
            scale = np.ones(training.shape[1], dtype=np.float64)
        else:
            mean = np.asarray(self.x_mean, dtype=np.float64)
            scale = np.asarray(self.x_scale, dtype=np.float64)
        if (
            mean.shape != (training.shape[1],)
            or scale.shape != (training.shape[1],)
            or not np.isfinite(mean).all()
            or not np.isfinite(scale).all()
            or np.any(scale <= 0.0)
        ):
            raise ValueError("KNN artifact has invalid scaling state")
        if not self.scale and (
            not np.array_equal(mean, np.zeros(training.shape[1], dtype=np.float64))
            or not np.array_equal(scale, np.ones(training.shape[1], dtype=np.float64))
        ):
            raise ValueError("KNN unscaled artifact must carry identity scaling vectors")
        return training, encoded, mean, scale

    def to_artifact(self) -> tuple[dict, dict[str, np.ndarray]]:
        """Serialize to (metadata, named_arrays) for ModelStore.save()."""
        training, encoded, x_mean, x_scale = self._validated_state()
        n_train = training.shape[0]
        estimated_bytes = training.nbytes + encoded.nbytes
        if estimated_bytes > 10 * 1024 * 1024:  # 10 MB
            logger.warning(
                "[KNNExtract] Large KNN artifact: %d training samples, "
                "~%.1f MB uncompressed. Consider reducing training set size.",
                n_train,
                estimated_bytes / (1024 * 1024),
            )
        metadata = {
            "model_type": "knn",
            "serializer": "spectrasherpa.model-artifact.knn/1",
            "k": self.k,
            "metric": self.metric,
            "weights": self.weights,
            "classes": self.classes,
            "n_train_samples": n_train,
            "feature_count": int(training.shape[1]),
            "scale": self.scale,
        }
        arrays = {
            "X_train": np.array(training, dtype=np.float64, copy=True),
            "y_train_encoded": np.array(encoded, dtype=np.int64, copy=True),
            "x_mean": np.array(x_mean, dtype=np.float64, copy=True),
            "x_scale": np.array(x_scale, dtype=np.float64, copy=True),
        }
        return metadata, arrays

    @classmethod
    def from_artifact(cls, metadata: dict, arrays: dict[str, np.ndarray]) -> KNNExtract:
        """Reconstruct from ModelStore.load() output."""
        if metadata.get("model_type") != "knn" or metadata.get("serializer") != "spectrasherpa.model-artifact.knn/1":
            raise ValueError("KNN artifact has an unsupported scientific identity")
        required_arrays = {"X_train", "y_train_encoded", "x_mean", "x_scale"}
        if set(arrays) != required_arrays:
            raise ValueError("KNN artifact does not contain the closed array set")
        training = np.asarray(arrays["X_train"], dtype=np.float64)
        if metadata.get("feature_count") != (training.shape[1] if training.ndim == 2 else None):
            raise ValueError("KNN artifact feature metadata does not match its training matrix")
        if metadata.get("n_train_samples") != (training.shape[0] if training.ndim == 2 else None):
            raise ValueError("KNN artifact sample metadata does not match its training matrix")
        if not isinstance(metadata.get("scale"), bool):
            raise ValueError("KNN artifact must declare its scaling rule")
        extract = cls(
            X_train=training,
            y_train_encoded=arrays["y_train_encoded"],
            classes=metadata.get("classes"),
            k=metadata.get("k"),
            metric=metadata.get("metric"),
            weights=metadata.get("weights"),
            scale=metadata["scale"],
            x_mean=arrays["x_mean"],
            x_scale=arrays["x_scale"],
        )
        extract._validated_state()
        return extract

    def predict(self, X: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """Predict class labels using k-nearest neighbor voting.

        Returns:
            (labels, probabilities) where labels is 1D string array and
            probabilities is (n_samples, n_classes) vote fractions.
        """
        from spectra_sherpa.app.services.dag.nodes.classification.knn_core import apply_knn_artifact_state

        training, encoded, mean, scale = self._validated_state()
        return apply_knn_artifact_state(
            X,
            training=training,
            encoded_labels=encoded,
            classes=tuple(self.classes),
            n_neighbors=self.k,
            weights=self.weights,
            metric=self.metric,
            mean=mean,
            scale=scale,
        )


# ---------------------------------------------------------------------------
# SIMCAExtract — SIMCA classification
# ---------------------------------------------------------------------------


def _validated_simca_applicability(value: Any) -> dict[str, dict[str, Any]] | None:
    if value is None:
        return None
    from spectra_sherpa.sdk.canonical_applicability import validate_applicability_evidence

    return {str(label): validate_applicability_evidence(evidence) for label, evidence in value.items()}


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
    applicability: dict[str, dict[str, Any]] | None = None
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
        if self.applicability is not None:
            from spectra_sherpa.sdk.canonical_applicability import validate_applicability_evidence

            metadata["applicability"] = {
                label: validate_applicability_evidence(evidence) for label, evidence in self.applicability.items()
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
            applicability=_validated_simca_applicability(metadata.get("applicability")),
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
    "pls": PLSExtract,
    "pcr": PCRExtract,
    "linear_regression": LinearRegressionExtract,
    "svr": SVRExtract,
    "mcr": MCRExtract,
    "nmf": NMFExtract,
    "fastica": FastICAExtract,
    "knn": KNNExtract,
    "simca": SIMCAExtract,
}


__all__ = [
    "PLSExtract",
    "PCRExtract",
    "LinearRegressionExtract",
    "SVRExtract",
    "MCRExtract",
    "NMFExtract",
    "FastICAExtract",
    "EFAExtract",
    "SIMPLISMAExtract",
    "KNNExtract",
    "SIMCAExtract",
    "EXTRACT_REGISTRY",
]
