"""Sherpa-native rubberband baseline correction.

Scientific authority
--------------------
Rubberband correction models a spectrum's baseline as its lower convex
envelope and subtracts the piecewise-linear envelope.  Butler et al. describe
rubberband correction in spectroscopy; the lower hull is constructed with
Andrew's monotone-chain algorithm.

References
----------
Butler, H. J. et al. Using Raman spectroscopy to characterize biological
materials. *Analyst* 143 (2018). https://doi.org/10.1039/C8AN01384E

Andrew, A. M. Another efficient algorithm for convex hulls in two dimensions.
*Information Processing Letters* 9 (1979), 216-219.
https://doi.org/10.1016/0020-0190(79)90072-3
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class RubberbandResult:
    """Numerical result from one row-wise rubberband correction."""

    corrected: np.ndarray
    baseline: np.ndarray
    anchor_indices: tuple[tuple[int, ...], ...]


def _strictly_ordered_axis(axis: np.ndarray, *, n_features: int) -> tuple[np.ndarray, bool]:
    coordinates = np.asarray(axis, dtype=np.float64)
    if coordinates.ndim != 1 or coordinates.shape != (n_features,):
        raise ValueError(f"rubberband axis must have shape ({n_features},)")
    if not np.isfinite(coordinates).all():
        raise ValueError("rubberband axis must contain only finite coordinates")
    differences = np.diff(coordinates)
    if np.all(differences > 0.0):
        return coordinates, False
    if np.all(differences < 0.0):
        return coordinates[::-1], True
    raise ValueError("rubberband axis must be strictly monotonic with no duplicate coordinates")


def _lower_hull_indices(x: np.ndarray, y: np.ndarray) -> tuple[int, ...]:
    """Return lower-hull indices for finite, increasingly ordered points."""

    if x.size == 2:
        return (0, 1)

    # Positive affine scaling preserves hull orientation while avoiding
    # overflow and catastrophic cancellation for large physical axes or
    # detector offsets. Constant spectra need only their endpoints.
    with np.errstate(over="ignore", invalid="ignore"):
        x_span = float(x[-1] - x[0])
    if np.isfinite(x_span):
        x_scaled = (x - x[0]) / x_span
    else:
        x_unit = x / float(np.max(np.abs(x)))
        x_scaled = (x_unit - x_unit[0]) / (x_unit[-1] - x_unit[0])

    y_minimum = float(np.min(y))
    with np.errstate(over="ignore", invalid="ignore"):
        y_centered = y - y_minimum
    y_span = float(np.max(y_centered))
    if y_span == 0.0:
        return (0, int(x.size - 1))
    if np.isfinite(y_span):
        y_scaled = y_centered / y_span
    else:
        y_unit = y / float(np.max(np.abs(y)))
        y_scaled = (y_unit - np.min(y_unit)) / (np.max(y_unit) - np.min(y_unit))

    hull: list[int] = []
    for index in range(x.size):
        while len(hull) >= 2:
            first, second = hull[-2], hull[-1]
            cross = (x_scaled[second] - x_scaled[first]) * (y_scaled[index] - y_scaled[first]) - (
                y_scaled[second] - y_scaled[first]
            ) * (x_scaled[index] - x_scaled[first])
            if cross > 0.0:
                break
            hull.pop()
        hull.append(index)
    return tuple(hull)


def rubberband_correct(data: np.ndarray, axis: np.ndarray) -> RubberbandResult:
    """Subtract each spectrum's lower piecewise-linear convex envelope.

    Parameters
    ----------
    data:
        Finite two-dimensional matrix shaped ``(samples, spectral_features)``.
    axis:
        Finite, strictly monotonic spectral coordinates. Increasing and
        decreasing coordinates are equivalent; duplicate coordinates fail.
    """

    matrix = np.asarray(data, dtype=np.float64)
    if matrix.ndim != 2 or matrix.shape[0] < 1 or matrix.shape[1] < 2:
        raise ValueError("rubberband requires a non-empty 2D matrix with at least two spectral features")
    if not np.isfinite(matrix).all():
        raise ValueError("rubberband spectra must contain only finite intensities")

    ordered_axis, descending = _strictly_ordered_axis(axis, n_features=matrix.shape[1])
    ordered_matrix = matrix[:, ::-1] if descending else matrix
    baselines = np.empty_like(ordered_matrix)
    corrected = np.empty_like(ordered_matrix)
    ordered_anchors: list[tuple[int, ...]] = []

    for row_index, spectrum in enumerate(ordered_matrix):
        anchors = _lower_hull_indices(ordered_axis, spectrum)
        anchor_array = np.asarray(anchors, dtype=np.int64)
        baseline = np.interp(ordered_axis, ordered_axis[anchor_array], spectrum[anchor_array])
        residual = spectrum - baseline
        if not np.isfinite(baseline).all() or not np.isfinite(residual).all():
            raise ValueError("rubberband numerical range cannot be represented as finite float64 output")
        # Interpolation may exceed a hull point by a few representable ULPs.
        # Clamp only those negative round-off values. Positive residuals are
        # scientific signal and must never be erased merely because the raw
        # spectrum has a large detector offset.
        negative = residual < 0.0
        local_ulp = 8.0 * np.maximum(np.abs(np.spacing(spectrum)), np.abs(np.spacing(baseline)))
        if np.any(residual[negative] < -local_ulp[negative]):
            raise RuntimeError("rubberband baseline crossed above an observed spectrum")
        residual[negative] = 0.0
        residual[anchor_array] = 0.0
        baselines[row_index] = baseline
        corrected[row_index] = residual
        ordered_anchors.append(anchors)

    if descending:
        n_features = matrix.shape[1]
        anchors_original = tuple(
            tuple(n_features - 1 - index for index in reversed(anchors)) for anchors in ordered_anchors
        )
        return RubberbandResult(
            corrected=corrected[:, ::-1],
            baseline=baselines[:, ::-1],
            anchor_indices=anchors_original,
        )
    return RubberbandResult(
        corrected=corrected,
        baseline=baselines,
        anchor_indices=tuple(ordered_anchors),
    )


__all__ = ["RubberbandResult", "rubberband_correct"]
