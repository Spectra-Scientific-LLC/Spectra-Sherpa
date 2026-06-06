"""Median-grid snapping is single-sourced in app.lib.wavenumber_grid.

Frozen behavior: the reference is the element-wise median of species
wavenumbers, absorbance is carried over unchanged (no interpolation), and
a genuine spacing mismatch is rejected rather than silently resampled.
"""

from __future__ import annotations

import numpy as np
import pytest

from spectra_sherpa.app.lib.wavenumber_grid import align_to_median_grid, median_spacing


def test_median_spacing() -> None:
    assert median_spacing(np.arange(1000.0, 1010.0, 1.0)) == pytest.approx(1.0)
    assert median_spacing(np.arange(1000.0, 1010.0, 0.5)) == pytest.approx(0.5)
    assert median_spacing(np.array([1000.0])) == 0.0


def test_reference_is_elementwise_median_and_absorbance_unchanged() -> None:
    base = np.arange(1000.0, 1010.0, 1.0)
    ya = np.linspace(0.1, 1.0, base.size)
    yc = np.linspace(0.5, 0.9, base.size)
    grids = [
        (base, ya),
        (base, ya),
        (base + 0.02, yc),  # offset minority
    ]
    ref, ys, shifts = align_to_median_grid(grids, common_min=1000.02, common_max=1009.0, tolerance=0.05)

    # median([v, v, v+0.02]) == v  → reference is the unshifted majority grid.
    np.testing.assert_allclose(ref, base[1:])
    assert shifts[0] == pytest.approx(0.0, abs=1e-12)
    assert shifts[1] == pytest.approx(0.0, abs=1e-12)
    assert shifts[2] == pytest.approx(0.02, abs=1e-9)
    # Absorbance carried over verbatim (the matched native subset), not blended.
    np.testing.assert_allclose(ys[0], ya[1:])
    np.testing.assert_allclose(ys[2], yc[1:])


def test_single_species_is_its_own_reference() -> None:
    x = np.arange(1000.0, 1005.0, 1.0)
    y = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
    ref, ys, shifts = align_to_median_grid([(x, y)], common_min=1000.0, common_max=1004.0, tolerance=0.05)
    np.testing.assert_allclose(ref, x)
    np.testing.assert_allclose(ys[0], y)
    assert shifts[0] == pytest.approx(0.0)


def test_spacing_mismatch_raises() -> None:
    coarse = np.arange(1000.0, 1010.0, 1.0)
    fine = np.arange(1000.0, 1010.0, 0.5)
    with pytest.raises(ValueError, match="tolerance|one-to-one"):
        align_to_median_grid(
            [(coarse, coarse * 0 + 1.0), (fine, fine * 0 + 1.0)],
            common_min=1000.0,
            common_max=1009.0,
            tolerance=0.05,
        )


def test_offset_beyond_tolerance_raises() -> None:
    base = np.arange(1000.0, 1010.0, 1.0)
    with pytest.raises(ValueError, match="away"):
        align_to_median_grid(
            [(base, base * 0 + 1.0), (base + 0.2, base * 0 + 1.0)],
            common_min=1000.2,
            common_max=1009.0,
            tolerance=0.05,
        )
