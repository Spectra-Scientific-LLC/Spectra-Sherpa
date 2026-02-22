"""
Typed extraction classes for SpectroChemPy model outputs.

Centralizes version-specific API logic for PCA, PLS, MCR, EFA, and SIMPLISMA.
All defensive hasattr checks, try-except cascades, and normalization heuristics
live HERE — not scattered across 15 node callsites.

When SCP 0.9 ships, fix one extractor class, not N nodes.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import numpy as np

from spectra_sherpa.app.lib.scp_compat import require_scp

logger = logging.getLogger(__name__)


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


@dataclass
class PCAExtract:
    """Version-aware extraction of PCA model outputs.

    Attributes:
        scores: Transformed scores (n_samples, n_components)
        loadings: Principal component loadings (n_components, n_features)
        explained_variance_ratio: Variance ratio 0-1 (n_components,)
        explained_variance: Eigenvalues (n_components,)
        n_components: Actual number of fitted components
    """
    scores: np.ndarray  # 2D float64
    loadings: np.ndarray  # 2D float64
    explained_variance_ratio: np.ndarray  # 1D float64, 0-1 ratio
    explained_variance: np.ndarray  # 1D float64
    n_components: int

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
            logger.warning(
                "[PCAExtract] EVR length %d < n_components %d, padding with zeros",
                len(evr), n_components
            )
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
                eigenvalues, (0, n_components - len(eigenvalues)),
                mode="constant", constant_values=1e-12
            )

        return cls(
            scores=scores,
            loadings=loadings,
            explained_variance_ratio=evr[:n_components],
            explained_variance=eigenvalues[:n_components],
            n_components=n_components,
        )


@dataclass
class PLSExtract:
    """Version-aware extraction of PLS regression outputs.

    Attributes:
        x_scores: X block scores (n_samples, n_components)
        y_scores: Y block scores (n_samples, n_components)
        x_loadings: X block loadings (n_features, n_components)
        y_loadings: Y block loadings (n_targets, n_components)
        coef: Regression coefficients
        n_components: Number of components
    """
    x_scores: np.ndarray | None  # 2D float64
    y_scores: np.ndarray | None  # 2D float64
    x_loadings: np.ndarray | None  # 2D float64
    y_loadings: np.ndarray | None  # 2D float64
    coef: np.ndarray | None  # array
    n_components: int

    @classmethod
    def from_scp(cls, pls_model: Any, X_ndd: Any) -> PLSExtract:
        """Extract from fitted SCP PLS model.

        SCP 0.8.x does not always populate x_scores_ attributes; this method
        handles fallback to .transform() when attributes are missing.

        Args:
            pls_model: Fitted scp.PLSRegression instance
            X_ndd: Input X NDDataset (for transform fallback)

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

        return cls(
            x_scores=x_scores,
            y_scores=y_scores,
            x_loadings=x_loadings,
            y_loadings=y_loadings,
            coef=coef,
            n_components=n_components,
        )


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


@dataclass
class EFAExtract:
    """Version-aware extraction of EFA outputs.

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


__all__ = [
    "PCAExtract",
    "PLSExtract",
    "MCRExtract",
    "EFAExtract",
    "SIMPLISMAExtract",
]
