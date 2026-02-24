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
"""

from . import blending, curves, io, preprocessing, spectral

__all__ = [
    "spectral",
    "blending",
    "preprocessing",
    "curves",
    "io",
]
