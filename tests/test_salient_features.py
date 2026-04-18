"""Tests for the SalientFeatures contract and LLM integration."""

from __future__ import annotations

from dataclasses import asdict

from spectra_sherpa.app.services.dag.node_base import SalientFeature, SalientFeatures

# ============================================================================
# SalientFeature / SalientFeatures dataclass basics
# ============================================================================


class TestSalientFeatureDataclass:
    def test_defaults(self):
        f = SalientFeature(position=1720.0)
        assert f.position == 1720.0
        assert f.importance == 1.0
        assert f.label == ""

    def test_with_all_fields(self):
        f = SalientFeature(position=2950.0, importance=0.88, label="consensus peak (4/5)")
        assert f.position == 2950.0
        assert f.importance == 0.88
        assert f.label == "consensus peak (4/5)"


class TestSalientFeaturesDataclass:
    def test_minimal(self):
        sf = SalientFeatures(method="peak_finding")
        assert sf.method == "peak_finding"
        assert sf.features == []
        assert sf.x_units == "cm-1"
        assert sf.n_total_variables == 0
        assert sf.selection_context == {}

    def test_full(self):
        sf = SalientFeatures(
            method="peak_finding",
            features=[
                SalientFeature(position=1720.0, importance=0.95, label="C=O region"),
                SalientFeature(position=2950.0, importance=0.88),
            ],
            x_units="cm-1",
            x_title="Wavenumber",
            n_total_variables=1000,
            selection_context={"n_samples": 50, "technique": "IR"},
        )
        assert len(sf.features) == 2
        assert sf.features[0].position == 1720.0
        assert sf.selection_context["technique"] == "IR"

    def test_asdict_roundtrip(self):
        """Serialization via asdict produces the expected dict shape."""
        sf = SalientFeatures(
            method="peak_finding",
            features=[SalientFeature(position=1720.0, importance=0.95)],
            x_units="cm-1",
            x_title="Wavenumber",
            n_total_variables=500,
            selection_context={"n_samples": 10, "technique": "IR"},
        )
        d = asdict(sf)
        assert d["method"] == "peak_finding"
        assert len(d["features"]) == 1
        assert d["features"][0]["position"] == 1720.0
        assert d["features"][0]["importance"] == 0.95
        assert d["x_units"] == "cm-1"
        assert d["selection_context"]["technique"] == "IR"

    def test_different_methods(self):
        """The contract supports arbitrary analysis methods."""
        for method in ("peak_finding", "spa", "cars", "vip", "pca_loadings"):
            sf = SalientFeatures(method=method)
            assert sf.method == method



# ============================================================================
# LLM integration tests removed — functionality moved to spectra-server
# (ADR-0001). See spectra-server/tests/ for LLMService and salient-feature
# extraction tests.
# ============================================================================
