"""Dependency-neutral construction of one common measured spectral grid."""

from __future__ import annotations

import math
from collections.abc import Sequence

import numpy as np


def build_common_overlap_grid(
    coordinate_arrays: Sequence[object],
    *,
    merge_tolerance: float,
) -> np.ndarray:
    """Merge measured coordinates inside every input's common coverage.

    The result is always ascending.  Clusters use a bounded diameter rather
    than single-link chaining, so their first and last measured coordinates
    can never differ by more than ``merge_tolerance``.
    """

    if isinstance(merge_tolerance, bool) or not isinstance(merge_tolerance, (int, float)):
        raise ValueError("golden-grid merge_tolerance must be a finite positive number")
    tolerance = float(merge_tolerance)
    if not math.isfinite(tolerance) or tolerance <= 0.0:
        raise ValueError("golden-grid merge_tolerance must be a finite positive number")
    if not coordinate_arrays:
        raise ValueError("golden-grid alignment requires at least one coordinate array")

    axes: list[np.ndarray] = []
    for index, coordinates in enumerate(coordinate_arrays):
        axis = np.asarray(coordinates, dtype=np.float64)
        if axis.ndim != 1 or axis.size < 2:
            raise ValueError(f"golden-grid input axis {index} must contain at least two coordinates")
        if not np.isfinite(axis).all():
            raise ValueError(f"golden-grid input axis {index} must contain only finite coordinates")
        differences = np.diff(axis)
        if not (np.all(differences > 0.0) or np.all(differences < 0.0)):
            raise ValueError(f"golden-grid input axis {index} must be strictly monotonic")
        axes.append(axis)

    overlap_minimum = max(float(axis.min()) for axis in axes)
    overlap_maximum = min(float(axis.max()) for axis in axes)
    if overlap_maximum <= overlap_minimum:
        raise ValueError("golden-grid inputs do not share a positive spectral overlap")

    measured = np.sort(np.concatenate([axis[(axis >= overlap_minimum) & (axis <= overlap_maximum)] for axis in axes]))
    if measured.size < 2:
        raise ValueError("golden-grid common overlap contains fewer than two measured coordinates")

    merged: list[float] = []
    cluster: list[float] = [float(measured[0])]
    for value in measured[1:]:
        candidate = float(value)
        if candidate - cluster[0] <= tolerance:
            cluster.append(candidate)
        else:
            merged.append(float(np.mean(cluster)))
            cluster = [candidate]
    merged.append(float(np.mean(cluster)))

    result = np.asarray(merged, dtype=np.float64)
    if result.size < 2 or not np.all(np.diff(result) > 0.0):
        raise ValueError("golden-grid merge did not produce at least two distinct coordinates")
    return result


__all__ = ["build_common_overlap_grid"]
