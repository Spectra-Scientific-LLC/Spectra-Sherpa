"""Phase 4: Frontend Wire Format tests.

Verify that SherpaDataset serializes correctly for the frontend,
including axis key remapping, metadata enrichment, and quality summary.
"""

from __future__ import annotations

import numpy as np
import pytest

from spectra_sherpa.app.lib.sherpa_dataset import (
    DomainContext,
    EvaluationResult,
    SherpaDataset,
    SpectralAxis,
    SampleAxis,
)
from spectra_sherpa.app.services.dag.serialize import serialize_for_api


# ---------------------------------------------------------------------------
# Axis key remapping
# ---------------------------------------------------------------------------


class TestAxisKeyRemapping:
    def test_spectral_axis_becomes_x_axis(self):
        """SherpaDataset with spectral_axis serializes as x_axis."""
        ds = SherpaDataset(
            X=np.zeros((3, 100)),
            spectral_axis=SpectralAxis(values=np.linspace(400, 4000, 100), units="cm-1"),
        )
        result = serialize_for_api(ds)
        assert "x_axis" in result
        assert "spectral_axis" not in result
        assert result["x_axis"]["units"] == "cm-1"

    def test_sample_axis_becomes_y_axis(self):
        """SherpaDataset with sample_axis serializes as y_axis."""
        ds = SherpaDataset(
            X=np.zeros((3, 10)),
            sample_axis=SampleAxis(labels=["A", "B", "C"]),
        )
        result = serialize_for_api(ds)
        assert "y_axis" in result
        assert "sample_axis" not in result
        assert result["y_axis"]["labels"] == ["A", "B", "C"]

    def test_both_axes_remapped(self):
        """Both spectral and sample axes are remapped."""
        ds = SherpaDataset(
            X=np.zeros((3, 50)),
            spectral_axis=SpectralAxis(values=np.linspace(400, 4000, 50), units="cm-1"),
            sample_axis=SampleAxis(labels=["S1", "S2", "S3"]),
        )
        result = serialize_for_api(ds)
        assert "x_axis" in result
        assert "y_axis" in result
        assert "spectral_axis" not in result
        assert "sample_axis" not in result


# ---------------------------------------------------------------------------
# Metadata enrichment (depends on axis remapping)
# ---------------------------------------------------------------------------


class TestMetadataEnrichment:
    def test_wavenumbers_in_metadata(self):
        """Frontend-compat metadata includes wavenumbers from spectral axis."""
        wn = np.linspace(400, 4000, 50)
        ds = SherpaDataset(
            X=np.zeros((3, 50)),
            spectral_axis=SpectralAxis(values=wn, units="cm-1"),
        )
        result = serialize_for_api(ds)
        metadata = result["metadata"]
        assert "wavenumbers" in metadata
        assert len(metadata["wavenumbers"]) == 50

    def test_x_title_in_metadata(self):
        """x_title is populated from spectral axis title."""
        ds = SherpaDataset(
            X=np.zeros((3, 50)),
            spectral_axis=SpectralAxis(
                values=np.linspace(400, 4000, 50),
                units="cm-1",
                title="Wavenumber",
            ),
        )
        result = serialize_for_api(ds)
        assert result["metadata"]["x_title"] == "Wavenumber"

    def test_x_units_in_metadata(self):
        """x_units is populated from spectral axis units."""
        ds = SherpaDataset(
            X=np.zeros((3, 50)),
            spectral_axis=SpectralAxis(values=np.linspace(400, 4000, 50), units="cm-1"),
        )
        result = serialize_for_api(ds)
        assert result["metadata"]["x_units"] == "cm-1"

    def test_sample_labels_in_metadata(self):
        """sample_labels populated from sample axis labels."""
        ds = SherpaDataset(
            X=np.zeros((3, 10)),
            sample_axis=SampleAxis(labels=["A", "B", "C"]),
        )
        result = serialize_for_api(ds)
        metadata = result["metadata"]
        assert "sample_labels" in metadata
        assert metadata["sample_labels"] == ["A", "B", "C"]


# ---------------------------------------------------------------------------
# Type field
# ---------------------------------------------------------------------------


class TestTypeField:
    def test_type_is_sherpa_dataset(self):
        """Serialized output has type='SherpaDataset'."""
        ds = SherpaDataset(X=np.zeros((3, 10)))
        result = serialize_for_api(ds)
        assert result["type"] == "SherpaDataset"


# ---------------------------------------------------------------------------
# Quality summary in metadata
# ---------------------------------------------------------------------------


class TestQualitySummary:
    def test_no_quality_when_no_evaluations(self):
        """No quality_summary key when dataset has no evaluations."""
        ds = SherpaDataset(X=np.zeros((3, 10)))
        result = serialize_for_api(ds)
        assert "quality_summary" not in result["metadata"]

    def test_quality_summary_with_evaluation(self):
        """quality_summary present in metadata when evaluations exist."""
        ds = SherpaDataset(X=np.zeros((5, 10)))
        ev = EvaluationResult(evaluation_id="ev1", model_type="PLS", r2=0.95, rmse=0.12)
        ds.quality.add_evaluation(ev)
        result = serialize_for_api(ds)
        qs = result["metadata"]["quality_summary"]
        assert qs["n_evaluations"] == 1
        assert qs["latest_model_type"] == "PLS"
        assert qs["latest_r2"] == 0.95
        assert qs["latest_rmse"] == 0.12


# ---------------------------------------------------------------------------
# Domain fields in metadata
# ---------------------------------------------------------------------------


class TestDomainInMetadata:
    def test_spectral_technique_detected(self):
        """IR technique detected from spectral axis range."""
        ds = SherpaDataset(
            X=np.zeros((3, 100)),
            spectral_axis=SpectralAxis(values=np.linspace(400, 4000, 100), units="cm-1"),
            domain=DomainContext(technique="IR"),
        )
        result = serialize_for_api(ds)
        assert result["metadata"]["spectral_technique"] == "IR"
        assert result["metadata"]["is_spectra"] is True

    def test_data_type_spectra(self):
        """data_type is 'spectra' for spectral data."""
        ds = SherpaDataset(
            X=np.zeros((3, 100)),
            spectral_axis=SpectralAxis(values=np.linspace(400, 4000, 100), units="cm-1"),
            domain=DomainContext(technique="IR"),
        )
        result = serialize_for_api(ds)
        assert result["metadata"]["data_type"] == "spectra"

    def test_data_type_generic_without_domain(self):
        """data_type is 'generic' for non-spectral data."""
        ds = SherpaDataset(X=np.zeros((3, 10)))
        result = serialize_for_api(ds)
        assert result["metadata"]["data_type"] == "generic"
