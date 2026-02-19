"""
Tests for the connection validator (Phase 3).

Covers:
- can_connect() with same type, subtypes, version compat, cross-type

Run:
    PYTHONPATH=src/spectra_sherpa python -m pytest tests/test_connection_validator.py -v --no-cov
"""

from __future__ import annotations

from pathlib import Path

import pytest

from spectra_sherpa.app.types.validator import can_connect

TYPES_DIR = Path(__file__).resolve().parent.parent / "src" / "spectra_sherpa" / "app" / "types"


@pytest.fixture(autouse=True)
def _load_registry():
    """Ensure the singleton type_registry is loaded for every test."""
    from spectra_sherpa.app.types import type_registry

    if not type_registry.is_loaded:
        type_registry.load(TYPES_DIR)


class TestCanConnect:
    def test_same_type(self):
        ok, reason = can_connect(
            "spectrasherpa://types/SpectralDataset/1.0",
            "spectrasherpa://types/SpectralDataset/1.0",
        )
        assert ok is True
        assert reason == ""

    def test_same_type_minor_version_compatible(self):
        ok, reason = can_connect(
            "spectrasherpa://types/SpectralDataset/1.2",
            "spectrasherpa://types/SpectralDataset/1.0",
        )
        assert ok is True
        assert reason == ""

    def test_same_type_major_version_incompatible(self):
        ok, reason = can_connect(
            "spectrasherpa://types/SpectralDataset/2.0",
            "spectrasherpa://types/SpectralDataset/1.0",
        )
        assert ok is False
        assert "version mismatch" in reason.lower()

    def test_subtype_child_to_parent(self):
        """ScoreMatrix output can connect to Array2D input."""
        ok, reason = can_connect(
            "spectrasherpa://types/ScoreMatrix/1.0",
            "spectrasherpa://types/Array2D/1.0",
        )
        assert ok is True

    def test_subtype_parent_to_child_fails(self):
        """Array2D output cannot connect to ScoreMatrix input."""
        ok, reason = can_connect(
            "spectrasherpa://types/Array2D/1.0",
            "spectrasherpa://types/ScoreMatrix/1.0",
        )
        assert ok is False

    def test_cross_type_fails(self):
        """SpectralDataset cannot connect to FittedModel."""
        ok, reason = can_connect(
            "spectrasherpa://types/SpectralDataset/1.0",
            "spectrasherpa://types/FittedModel/1.0",
        )
        assert ok is False

    def test_model_subtype(self):
        """DecompositionResult can connect to FittedModel."""
        ok, reason = can_connect(
            "spectrasherpa://types/DecompositionResult/1.0",
            "spectrasherpa://types/FittedModel/1.0",
        )
        assert ok is True

    def test_spectrum_to_array1d(self):
        ok, reason = can_connect(
            "spectrasherpa://types/Spectrum/1.0",
            "spectrasherpa://types/Array1D/1.0",
        )
        assert ok is True

    def test_scalar_to_scalar(self):
        ok, reason = can_connect(
            "spectrasherpa://types/Scalar/1.0",
            "spectrasherpa://types/Scalar/1.0",
        )
        assert ok is True

    def test_scalar_to_array_fails(self):
        ok, reason = can_connect(
            "spectrasherpa://types/Scalar/1.0",
            "spectrasherpa://types/Array1D/1.0",
        )
        assert ok is False

    def test_spectral_dataset_to_snv_input(self):
        """Typical preprocessing connection."""
        ok, reason = can_connect(
            "spectrasherpa://types/SpectralDataset/1.0",
            "spectrasherpa://types/SpectralDataset/1.0",
        )
        assert ok is True

    def test_classification_model_to_fitted_model(self):
        ok, reason = can_connect(
            "spectrasherpa://types/ClassificationModel/1.0",
            "spectrasherpa://types/FittedModel/1.0",
        )
        assert ok is True
