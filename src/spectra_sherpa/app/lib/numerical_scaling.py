"""Floating-point resolution of per-variable calibration variation."""

from __future__ import annotations

import numpy as np


def unresolved_variation(matrix: np.ndarray, variation: np.ndarray) -> np.ndarray:
    """Do not amplify centering/reduction roundoff into a unit-weight variable.

    The bound follows each column's own amplitude, so a genuinely small signal
    near zero remains usable. It is invariant under changes of signal units.
    """
    bound = matrix.shape[0] * np.finfo(np.float64).eps * np.max(np.abs(matrix), axis=0)
    return np.asarray(variation) <= bound
