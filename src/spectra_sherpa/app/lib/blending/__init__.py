"""
Multi-species spectral blending with calibration models.

This module provides AnalysisDataset-native blending operations,
preserving the numerical algorithms from project0/blend.py.

Core algorithms:
- eval_linear_model: Linear calibration with saturation capping
- eval_saturation_model: Hyperbolic tangent saturation model
- apply_system_saturation: System-level detector saturation
- select_hybrid_model: Per-wavenumber model selection
"""

from .blend import (
    SAFE_MIN_THRESHOLD,
    # Settings
    BlendSettings,
    apply_system_saturation,
    # NDDataset-native blending
    blend_datasets,
    # Numerical functions
    eval_linear_model,
    eval_saturation_model,
    select_hybrid_model,
)

__all__ = [
    # Core numerical functions
    "eval_linear_model",
    "eval_saturation_model",
    "apply_system_saturation",
    "select_hybrid_model",
    "SAFE_MIN_THRESHOLD",
    # Settings
    "BlendSettings",
    # NDDataset-native blending
    "blend_datasets",
]
