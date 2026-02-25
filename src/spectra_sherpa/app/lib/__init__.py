"""
Unified spectral processing library.

This module provides NDDataset-native operations for spectral data,
replacing the legacy project0/project1 implementations.

Submodules:
- spectral: Core dataset types, conversions, and serialization
- blending: Multi-species blending with calibration models
- preprocessing: Spectral preprocessing (alignment, smoothing, etc.)
- curves: Catmull-Rom and concentration curve utilities
- io: File I/O for various spectral formats

All submodules are imported lazily to keep ``import spectra_sherpa``
lightweight (no scipy, pandas, or spectrochempy on cold import).
"""

from __future__ import annotations

__all__ = [
    "spectral",
    "blending",
    "preprocessing",
    "curves",
    "io",
]


def __getattr__(name: str):
    if name in __all__:
        import importlib

        return importlib.import_module(f".{name}", __name__)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
