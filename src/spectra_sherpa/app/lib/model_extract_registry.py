"""Closed native saved-model artifact application registry."""

from __future__ import annotations

from spectra_sherpa.app.lib.fitted_state import EXTRACT_REGISTRY as FITTED_STATE_REGISTRY
from spectra_sherpa.app.lib.pca import PCAExtract

if "pca" in FITTED_STATE_REGISTRY:  # pragma: no cover - import-time boundary assertion
    raise RuntimeError("PCA fitted state has its own native authority and cannot be registered twice")

EXTRACT_REGISTRY: dict[str, type] = {
    "pca": PCAExtract,
    **FITTED_STATE_REGISTRY,
}

__all__ = ["EXTRACT_REGISTRY"]
