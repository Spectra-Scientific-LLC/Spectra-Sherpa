"""Snap species onto the median wavenumber grid.

NIST Quant IR spectra for different compounds at the same resolution come
back on grids with the *same spacing* but offset by a small fraction of a
cm^-1 (e.g. Benzene 575.171 vs iso-Propyl/Methyl-bromide 575.169 — a
~0.002 cm^-1 rigid shift). The basket must not be rejected, and the fix is
NOT a union + interpolation (that resamples intensity).

Instead, species are matched position-by-position (they share spacing) and
the reference grid is the *element-wise median* of their wavenumbers — the
"majority" is the calculated median, robust to a single offset outlier.
Every species keeps its absorbance unchanged; only its wavenumber labels
move to the median grid. Species sitting away from the median are
"shifted"; the central cluster is not. Matching is only valid when the
spacings match, so a genuine spacing mismatch raises instead.
"""

from __future__ import annotations

import numpy as np

# A species whose largest displacement from the median grid exceeds this is
# reported as "shifted". NIST wavenumbers are quoted to ~1e-3 cm^-1 and real
# inter-compound offsets (~2e-3+) sit above it.
SAME_GRID_EPS_CM1 = 1e-3


def median_spacing(values: np.ndarray) -> float:
    """Median spacing between unique sorted points.

    The per-compound number the UI compares: snapping to the median grid is
    only meaningful when these are nearly equal across the basket.
    """
    unique = np.unique(np.sort(np.asarray(values, dtype=float)))
    diffs = np.diff(unique)
    positive = diffs[diffs > 0]
    return float(np.median(positive)) if positive.size else 0.0


def _nearest_indices(x: np.ndarray, targets: np.ndarray) -> np.ndarray:
    """Index in sorted ``x`` of the nearest value to each target."""
    pos = np.searchsorted(x, targets)
    left = np.clip(pos - 1, 0, x.size - 1)
    right = np.clip(pos, 0, x.size - 1)
    choose_left = np.abs(targets - x[left]) <= np.abs(x[right] - targets)
    return np.where(choose_left, left, right)


def align_to_median_grid(
    grids: list[tuple[np.ndarray, np.ndarray]],
    *,
    common_min: float,
    common_max: float,
    tolerance: float,
) -> tuple[np.ndarray, list[np.ndarray], list[float]]:
    """Match species position-by-position and snap onto their median grid.

    ``grids`` is a list of ``(x_sorted, y_sorted)``. Positions are
    enumerated from the densest species over the overlap; every species
    must supply a unique point within ``tolerance`` of each position (the
    signature of a shared spacing — otherwise ``ValueError``). The
    reference grid is the element-wise median of the matched wavenumbers;
    each species' absorbance is carried over unchanged.

    Returns ``(reference_grid, [y_on_reference, ...], [max_shift_cm1, ...])``.
    """
    if not grids:
        raise ValueError("no grids provided")

    overlaps = [x[(x >= common_min) & (x <= common_max)] for x, _ in grids]
    anchor = int(np.argmax([o.size for o in overlaps]))
    anchor_x = np.unique(overlaps[anchor])
    if anchor_x.size < 2:
        raise ValueError("overlapping range is too small to align grids")

    matched_x: list[np.ndarray] = []
    matched_y: list[np.ndarray] = []
    for x, y in grids:
        idx = _nearest_indices(x, anchor_x)
        dist = np.abs(x[idx] - anchor_x)
        if np.any(dist > tolerance):
            raise ValueError(
                f"nearest point is {float(np.max(dist)):.5g} cm^-1 away "
                f"(> tolerance {tolerance:g}); spacings likely differ"
            )
        if np.any(np.diff(idx) <= 0):
            raise ValueError("point assignment is not one-to-one; native spacing differs")
        matched_x.append(x[idx])
        matched_y.append(y[idx])

    reference = np.median(np.vstack(matched_x), axis=0)
    max_shifts = [float(np.max(np.abs(mx - reference))) for mx in matched_x]
    return reference, matched_y, max_shifts


__all__ = ["median_spacing", "align_to_median_grid", "SAME_GRID_EPS_CM1"]
