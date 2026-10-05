"""Norris-Williams gap-segment derivative authority.

The operation is intentionally independent of application configuration and
optional parallel runtimes.  A canonical DAG node owns execution policy; this
module owns only the published numerical transform.

Reference
---------
Norris, K. H. and Williams, P. C. (1984). Optimization of mathematical
treatments of raw near-infrared signal in the measurement of protein in hard
red spring wheat. Cereal Chemistry 61, 158-165.
"""

from __future__ import annotations

import numpy as np


def norris_williams(
    data: np.ndarray,
    *,
    gap: int = 5,
    segment: int = 5,
    deriv: int = 1,
    delta: float = 1.0,
) -> np.ndarray:
    """Return the first or second Norris-Williams gap derivative.

    The two segment means are separated by ``gap`` feature points.  Their
    difference is divided by the physical distance between segment centers.
    Edge positions without two complete segments remain zero, as defined by
    the operation's explicit boundary policy.
    """

    matrix = np.asarray(data)
    was_1d = matrix.ndim == 1
    if was_1d:
        matrix = matrix.reshape(1, -1)
    if matrix.ndim != 2:
        raise ValueError("Norris-Williams derivative requires one- or two-dimensional data")
    if matrix.shape[0] == 0 or matrix.shape[1] == 0:
        raise ValueError("Norris-Williams derivative requires at least one sample and one feature")
    if not np.isfinite(matrix).all():
        raise ValueError("Norris-Williams derivative requires finite input values")
    if isinstance(gap, bool) or not isinstance(gap, int) or gap < 1:
        raise ValueError("gap must be a positive integer")
    if isinstance(segment, bool) or not isinstance(segment, int) or segment < 1:
        raise ValueError("segment must be a positive integer")
    if isinstance(deriv, bool) or deriv not in {1, 2}:
        raise ValueError("deriv must be 1 or 2")
    if isinstance(delta, bool) or not isinstance(delta, (int, float)) or not np.isfinite(delta):
        raise ValueError("delta must be a finite number")

    n_features = matrix.shape[1]
    center_spacing = (2 * gap + segment - 1) * float(delta)
    if abs(center_spacing) <= 1e-12:
        raise ValueError("Norris-Williams derivative requires a non-zero feature-axis spacing")

    def first_derivative(row: np.ndarray) -> np.ndarray:
        result = np.zeros(n_features, dtype=np.result_type(row.dtype, np.float64))
        for index in range(gap + segment - 1, n_features - gap - segment + 1):
            left = row[index - gap - segment + 1 : index - gap + 1]
            right = row[index + gap : index + gap + segment]
            result[index] = (np.mean(right) - np.mean(left)) / center_spacing
        return result

    output = np.empty(matrix.shape, dtype=np.result_type(matrix.dtype, np.float64))
    for row_index, row in enumerate(matrix):
        first = first_derivative(row)
        output[row_index] = first if deriv == 1 else first_derivative(first)
    return output[0] if was_1d else output


__all__ = ["norris_williams"]
