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
    """

    scores: np.ndarray  # 2D float64
    loadings: np.ndarray  # 2D float64
    explained_variance_ratio: np.ndarray  # 1D float64, 0-1 ratio
    explained_variance: np.ndarray  # 1D float64
    n_components: int
    mean: np.ndarray | None = None  # 1D float64

    @classmethod
    def from_scp(cls, pca_model: Any, input_ndd: Any) -> PCAExtract:
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

        # Compute training data mean for centering
        mean = None
        try:
            mean = np.mean(_unwrap_to_numpy(input_ndd, "input_ndd"), axis=0).astype(np.float64)
            mean = mean.reshape(-1)
        except Exception as e:
            logger.warning("[PCAExtract] Could not compute training mean: %s", e)

        return cls(
            scores=scores,
            loadings=loadings,
            explained_variance_ratio=evr[:n_components],
            explained_variance=eigenvalues[:n_components],
            n_components=n_components,
            mean=mean,
        )

    def to_artifact(self) -> tuple[dict, dict[str, np.ndarray]]:
        """Serialize to (metadata, named_arrays) for ModelStore.save()."""
        metadata = {
            "model_type": "pca",
            "n_components": self.n_components,
        }
        arrays: dict[str, np.ndarray] = {
            "loadings": self.loadings,
            "explained_variance_ratio": self.explained_variance_ratio,
            "explained_variance": self.explained_variance,
        }
        if self.mean is not None:
            arrays["mean"] = self.mean
        if self.scores is not None and self.scores.size > 0:
            arrays["scores"] = self.scores
        return metadata, arrays

    @classmethod
    def from_artifact(cls, metadata: dict, arrays: dict[str, np.ndarray]) -> PCAExtract:
        """Reconstruct from ModelStore.load() output."""
        loadings = arrays["loadings"]
        n_components = metadata.get("n_components", loadings.shape[0])
        return cls(
            scores=arrays.get("scores", np.empty((0, n_components))),
            loadings=loadings,
            explained_variance_ratio=arrays.get("explained_variance_ratio", np.zeros(n_components)),
            explained_variance=arrays.get("explained_variance", np.zeros(n_components)),
            n_components=n_components,
            mean=arrays.get("mean"),
        )

    def transform(self, X: np.ndarray) -> np.ndarray:
        """Project new data into PC space: scores = (X - mean) @ loadings.T"""
        X = np.asarray(X, dtype=np.float64)
        if X.ndim == 1:
            X = X.reshape(1, -1)
        if self.mean is not None:
            X = X - self.mean
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
    """

    x_scores: np.ndarray | None  # 2D float64
    y_scores: np.ndarray | None  # 2D float64
    x_loadings: np.ndarray | None  # 2D float64
    y_loadings: np.ndarray | None  # 2D float64
    coef: np.ndarray | None  # (n_features, n_targets) float64
    n_components: int
    x_mean: np.ndarray | None = None  # 1D float64
    y_mean: np.ndarray | None = None  # 1D float64

    @classmethod
    def from_scp(cls, pls_model: Any, X_ndd: Any, *, Y_ndd: Any = None) -> PLSExtract:
        """Extract from fitted SCP PLS model.

        SCP 0.8.x does not always populate x_scores_ attributes; this method
        handles fallback to .transform() when attributes are missing.

        Args:
            pls_model: Fitted scp.PLSRegression instance
            X_ndd: Input X NDDataset (for transform fallback)
            Y_ndd: Input Y NDDataset (optional, for y_mean computation)

        Returns:
            PLSExtract with all extractable outputs
        """
        require_scp("PLSExtract.from_scp")

        n_components = pls_model.n_components

        # Extract X scores — try attribute first, then transform()
        x_scores = None
        if hasattr(pls_model, "x_scores_") and pls_model.x_scores_ is not None:
            try:
                x_scores = _to_numpy_2d(pls_model.x_scores_, name="x_scores_")
            except Exception:
                pass

        # Fallback: use transform()
        if x_scores is None and hasattr(pls_model, "transform"):
            try:
                transformed = pls_model.transform(X_ndd)
                x_scores = _to_numpy_2d(transformed, name="transform(X)")
                logger.debug("[PLSExtract] Derived x_scores from transform() (x_scores_ missing)")
            except Exception as e:
                logger.warning("[PLSExtract] Could not derive x_scores: %s", e)

        # Extract Y scores
        y_scores = None
        if hasattr(pls_model, "y_scores_") and pls_model.y_scores_ is not None:
            try:
                y_scores = _to_numpy_2d(pls_model.y_scores_, name="y_scores_")
            except Exception:
                pass

        # Extract X loadings
        x_loadings = None
        if hasattr(pls_model, "x_loadings_") and pls_model.x_loadings_ is not None:
            try:
                x_loadings = _to_numpy_2d(pls_model.x_loadings_, name="x_loadings_")
            except Exception:
                pass

        # Extract Y loadings
        y_loadings = None
        if hasattr(pls_model, "y_loadings_") and pls_model.y_loadings_ is not None:
            try:
                y_loadings = _to_numpy_2d(pls_model.y_loadings_, name="y_loadings_")
            except Exception:
                pass

        # Extract coefficients
        coef = None
        if hasattr(pls_model, "coef_") and pls_model.coef_ is not None:
            try:
                coef = _unwrap_to_numpy(pls_model.coef_, name="coef_")
            except Exception:
                pass

        # Compute X mean from training data
        x_mean = None
        try:
            x_mean = np.mean(_unwrap_to_numpy(X_ndd, "X_ndd"), axis=0).astype(np.float64).reshape(-1)
        except Exception as e:
            logger.warning("[PLSExtract] Could not compute x_mean: %s", e)

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
        )

    def to_artifact(self) -> tuple[dict, dict[str, np.ndarray]]:
        """Serialize to (metadata, named_arrays) for ModelStore.save()."""
        metadata = {
            "model_type": "pls",
            "n_components": self.n_components,
        }
        arrays: dict[str, np.ndarray] = {}
        if self.coef is not None:
            arrays["coef"] = np.asarray(self.coef, dtype=np.float64)
        if self.x_mean is not None:
            arrays["x_mean"] = self.x_mean
        if self.y_mean is not None:
            arrays["y_mean"] = self.y_mean
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
        return cls(
            x_scores=arrays.get("x_scores"),
            y_scores=arrays.get("y_scores"),
            x_loadings=arrays.get("x_loadings"),
            y_loadings=arrays.get("y_loadings"),
            coef=arrays.get("coef"),
            n_components=n_components,
            x_mean=arrays.get("x_mean"),
            y_mean=arrays.get("y_mean"),
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
        return metadata, arrays

    @classmethod
    def from_artifact(cls, metadata: dict, arrays: dict[str, np.ndarray]) -> SIMCAExtract:
        """Reconstruct from ModelStore.load() output."""
        classes = metadata.get("classes", [])
        class_loadings: dict[str, np.ndarray] = {}
        class_eigenvalues: dict[str, np.ndarray] = {}
        class_means: dict[str, np.ndarray] = {}

        for idx, label in enumerate(classes):
            key_load = f"class_{idx}_loadings"
            key_ev = f"class_{idx}_eigenvalues"
            key_mean = f"class_{idx}_mean"
            if key_load in arrays:
                class_loadings[label] = arrays[key_load]
            if key_ev in arrays:
                class_eigenvalues[label] = arrays[key_ev]
            if key_mean in arrays:
                class_means[label] = arrays[key_mean]

        return cls(
            class_loadings=class_loadings,
            class_eigenvalues=class_eigenvalues,
            class_means=class_means,
            classes=classes,
            T2_limits=metadata.get("T2_limits", {}),
            Q_limits=metadata.get("Q_limits", {}),
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
                T2_lim = self.T2_limits.get(label, 1.0)
                Q_lim = self.Q_limits.get(label, 1.0)

                centered = sample - class_mean
                scores = centered @ loadings.T  # (n_comp,)
                reconstructed = scores @ loadings  # (n_feat,)
                residual = centered - reconstructed

                # T² statistic
                safe_ev = np.maximum(eigenvalues, 1e-12)
                t2 = float(np.sum((scores**2) / safe_ev))

                # Q statistic (SPE)
                q = float(np.sum(residual**2))

                # Combined normalized distance
                combined = t2 / max(T2_lim, 1e-12) + q / max(Q_lim, 1e-12)
                dist_matrix[i, j] = combined

            # Assign to nearest class (minimum distance)
            labels[i] = self.classes[int(np.argmin(dist_matrix[i]))]

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
    "mcr": MCRExtract,
    "efa": EFAExtract,
    "simplisma": SIMPLISMAExtract,
    "plsda": PLSDAExtract,
    "knn": KNNExtract,
    "simca": SIMCAExtract,
}


__all__ = [
    "PCAExtract",
    "PLSExtract",
    "MCRExtract",
    "EFAExtract",
    "SIMPLISMAExtract",
    "PLSDAExtract",
    "KNNExtract",
    "SIMCAExtract",
    "EXTRACT_REGISTRY",
]
