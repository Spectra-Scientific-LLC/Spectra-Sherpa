"""Catmull-Rom curve math is single-sourced in app.lib.curves.

These tests freeze the sample-index evaluator so the Data-tab synthesis
trace can never silently drift, and assert that services.synthesis only
re-wraps it (no second implementation) while preserving the public
SynthesisError contract.
"""

from __future__ import annotations

import numpy as np
import pytest

from spectra_sherpa.app.lib.curves import evaluate_catmull_rom_samples
from spectra_sherpa.app.services.synthesis import SynthesisError, evaluate_catmull_rom_ppm

# Frozen golden: evaluate_catmull_rom_samples must produce exactly this for
# the fixed control points below. Regenerate intentionally only if the curve
# definition is deliberately changed.
_GOLDEN_POINTS = [(0, 0.0), (3, 10.0), (6, 2.0), (9, 8.0)]
_GOLDEN = np.array(
    [
        0.0,
        3.25925926,
        7.62962963,
        10.0,
        8.14814815,
        4.2962963,
        2.0,
        3.18518519,
        5.92592593,
        8.0,
    ]
)


def test_sample_evaluator_matches_frozen_golden() -> None:
    curve = evaluate_catmull_rom_samples(_GOLDEN_POINTS, n_samples=10)
    np.testing.assert_allclose(curve, _GOLDEN, rtol=0, atol=1e-7)


def test_synthesis_wrapper_is_numerically_identical() -> None:
    """services.synthesis must delegate, not re-implement."""
    via_wrapper = evaluate_catmull_rom_ppm(_GOLDEN_POINTS, n_samples=10)
    np.testing.assert_array_equal(via_wrapper, evaluate_catmull_rom_samples(_GOLDEN_POINTS, n_samples=10))


def test_endpoints_pad_flat_to_full_sample_grid() -> None:
    curve = evaluate_catmull_rom_samples([(2, 5.0), (4, 5.0)], n_samples=8)
    np.testing.assert_allclose(curve, np.full(8, 5.0))


def test_negative_values_are_clipped_but_magnitude_is_not() -> None:
    curve = evaluate_catmull_rom_samples([(0, 0.0), (5, 100000.0), (9, 0.0)], n_samples=10)
    assert curve.min() >= 0.0
    assert curve.max() >= 100000.0 - 1e-6  # absolute ppm magnitude preserved (no [0,1] clamp)


def test_wrapper_preserves_synthesis_error_contract() -> None:
    with pytest.raises(SynthesisError, match="strictly increasing"):
        evaluate_catmull_rom_ppm([(5, 1.0), (5, 2.0)], n_samples=4)
    with pytest.raises(SynthesisError, match="[Aa]t least two control points"):
        evaluate_catmull_rom_ppm([(0, 1.0)], n_samples=4)
    # SynthesisError is a ValueError subclass, so the API layer still maps to 4xx.
    assert issubclass(SynthesisError, ValueError)
