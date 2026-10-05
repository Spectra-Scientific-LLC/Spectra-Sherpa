"""Published nonlinear absorbance-transition authority.

Rodionova and Pomerantsev define the transition in equation 13 of
doi:10.1039/C5AY02393A.  Keeping the numerical primitive below the DAG layer
lets every live, exported, and transitional caller share one implementation.
"""

from __future__ import annotations

import numpy as np


def apply_saturation_transition(
    ideal_absorbance: np.ndarray,
    saturation_level: np.ndarray | float,
    shape_exponent: np.ndarray | float,
) -> np.ndarray:
    """Return ``s * tanh((x / s) ** p) ** (1 / p)`` without repair."""

    ideal = np.asarray(ideal_absorbance, dtype=np.float64)
    level = np.asarray(saturation_level, dtype=np.float64)
    exponent = np.asarray(shape_exponent, dtype=np.float64)
    if ideal.size == 0 or not np.isfinite(ideal).all():
        raise ValueError("ideal absorbance must be non-empty and finite")
    if np.any(ideal < 0.0):
        raise ValueError("ideal absorbance must be non-negative")
    if level.size == 0 or not np.isfinite(level).all() or np.any(level <= 0.0):
        raise ValueError("saturation level must be finite and strictly positive")
    if exponent.size == 0 or not np.isfinite(exponent).all() or np.any(exponent <= 0.0):
        raise ValueError("shape exponent must be finite and strictly positive")
    try:
        # A positive power may overflow only in the fully saturated limit;
        # tanh(+inf) == 1 is the exact limiting value of the published model.
        # Division and invalid arithmetic remain hard failures.
        with np.errstate(over="ignore", divide="raise", invalid="raise"):
            transitioned = level * np.tanh(np.power(ideal / level, exponent)) ** (1.0 / exponent)
    except (FloatingPointError, ValueError) as exc:
        raise ValueError("saturation transition could not be evaluated for the declared shapes") from exc
    if not np.isfinite(transitioned).all():
        raise ValueError("saturation transition produced a non-finite result")
    return np.asarray(transitioned, dtype=np.float64)


__all__ = ["apply_saturation_transition"]
