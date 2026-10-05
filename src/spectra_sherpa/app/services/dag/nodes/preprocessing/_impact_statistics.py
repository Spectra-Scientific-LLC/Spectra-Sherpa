"""Closed numerical summaries for canonical preprocessing impact records."""

from __future__ import annotations

import numpy as np


def finite_nonnegative_mean(values: np.ndarray) -> float:
    """Return a finite mean without overflowing the nonnegative sum.

    Scientific impact magnitudes are nonnegative. Scaling by their maximum
    keeps NumPy's reduction in ``[0, 1]`` even when multiple individually
    representable values would overflow a direct floating-point sum.
    """

    array = np.asarray(values, dtype=np.float64)
    if array.size == 0:
        return 0.0
    if not np.isfinite(array).all() or np.any(array < 0.0):
        raise ValueError("impact magnitudes must be finite and nonnegative")
    maximum = float(array.max())
    if maximum == 0.0:
        return 0.0
    mean = float(maximum * np.mean(array / maximum))
    if not np.isfinite(mean):
        raise ValueError("impact mean is not finitely representable")
    return mean


__all__ = ["finite_nonnegative_mean"]
