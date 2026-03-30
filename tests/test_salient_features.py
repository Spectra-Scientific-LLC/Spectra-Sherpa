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
# LLM integration: _extract_salient_features
# ============================================================================


class TestExtractSalientFeatures:
    """Test the LLM service's salient feature extraction (static method)."""

    @staticmethod
    def _make_metadata(salient_dict: dict) -> dict:
        return {
            "workflow_context": {
                "results_summary": {
                    "node_1": {"salient_features": salient_dict},
                },
            },
        }

    def test_extracts_peak_features(self):
        from spectra_sherpa.app.services.llm import LLMService

        sf = asdict(
            SalientFeatures(
                method="peak_finding",
                features=[
                    SalientFeature(position=1720.0, importance=0.95, label="consensus peak (5/5)"),
                    SalientFeature(position=2950.0, importance=0.80),
                ],
                x_units="cm-1",
                selection_context={"n_samples": 5, "technique": "IR"},
            )
        )
        result = LLMService._extract_salient_features(self._make_metadata(sf))
        assert result is not None
        assert "1720.0 cm-1" in result
        assert "2950.0 cm-1" in result
        assert "C=O stretch" in result  # Rule-based assignment
        assert "C-H stretch (sp3)" in result
        assert "peak_finding" in result

    def test_returns_none_for_no_features(self):
        from spectra_sherpa.app.services.llm import LLMService

        metadata = {"workflow_context": {"results_summary": {"node_1": {"some_other_key": {}}}}}
        assert LLMService._extract_salient_features(metadata) is None

    def test_returns_none_for_empty_features(self):
        from spectra_sherpa.app.services.llm import LLMService

        sf = asdict(SalientFeatures(method="peak_finding", features=[]))
        assert LLMService._extract_salient_features(self._make_metadata(sf)) is None

    def test_returns_none_for_missing_workflow_context(self):
        from spectra_sherpa.app.services.llm import LLMService

        assert LLMService._extract_salient_features({}) is None
        assert LLMService._extract_salient_features({"workflow_context": None}) is None

    def test_includes_guidance_text(self):
        from spectra_sherpa.app.services.llm import LLMService

        sf = asdict(
            SalientFeatures(
                method="peak_finding",
                features=[SalientFeature(position=1720.0)],
                x_units="cm-1",
            )
        )
        result = LLMService._extract_salient_features(self._make_metadata(sf))
        assert "clarifying questions" in result
        assert "confidence" in result

    def test_silent_region_no_rule_match(self):
        """2000 cm-1 (silent region) should not have rule-based assignments."""
        from spectra_sherpa.app.services.llm import LLMService

        sf = asdict(
            SalientFeatures(
                method="peak_finding",
                features=[SalientFeature(position=2000.0, importance=0.5)],
                x_units="cm-1",
            )
        )
        result = LLMService._extract_salient_features(self._make_metadata(sf))
        assert result is not None
        assert "2000.0 cm-1" in result
        assert "Possible:" not in result  # No rule-based match for silent region

    def test_multiple_nodes_with_features(self):
        """Multiple nodes can each emit salient features."""
        from spectra_sherpa.app.services.llm import LLMService

        metadata = {
            "workflow_context": {
                "results_summary": {
                    "peak_node": {
                        "salient_features": asdict(
                            SalientFeatures(
                                method="peak_finding",
                                features=[SalientFeature(position=1720.0)],
                                x_units="cm-1",
                            )
                        )
                    },
                    "vip_node": {
                        "salient_features": asdict(
                            SalientFeatures(
                                method="vip",
                                features=[SalientFeature(position=42, importance=2.1)],
                                x_units="index",
                            )
                        )
                    },
                },
            },
        }
        result = LLMService._extract_salient_features(metadata)
        assert "peak_finding" in result
        assert "vip" in result


# ============================================================================
# Local mode metadata preparation
# ============================================================================


class TestPrepareMetadataForLocal:
    def test_preserves_salient_features_in_local_mode(self, monkeypatch):
        from spectra_sherpa.app.services.llm import LLMService

        # Simulate local mode
        class FakeConfig:
            mode = "local"

        import spectra_sherpa.app.core.config as cfg_mod

        monkeypatch.setattr(cfg_mod, "app_config", FakeConfig())

        metadata = {
            "workflow_context": {
                "results_summary": {
                    "node_1": {
                        "salient_features": {"method": "peak_finding", "features": [{"position": 1720.0}]},
                        "peaks": {"data": [{"lots": "of data"}]},
                    },
                },
                "nodes": [{"type": "analysis.peak_finding", "parameters": {"height": 0.1}}],
            },
            "experiments": [{"name": "My Experiment", "technique": "IR"}],
        }
        result = LLMService._prepare_metadata_for_local_chat(metadata)
        assert result is not None
        # Salient features preserved
        sf = result["workflow_context"]["results_summary"]["node_1"]["salient_features"]
        assert sf["method"] == "peak_finding"
        # Everything else stripped
        assert "experiments" not in result
        assert "nodes" not in result.get("workflow_context", {})
        assert "peaks" not in result["workflow_context"]["results_summary"]["node_1"]

    def test_returns_none_when_no_salient_features_local(self, monkeypatch):
        from spectra_sherpa.app.services.llm import LLMService

        class FakeConfig:
            mode = "local"

        import spectra_sherpa.app.core.config as cfg_mod

        monkeypatch.setattr(cfg_mod, "app_config", FakeConfig())

        metadata = {
            "workflow_context": {"results_summary": {"node_1": {"peaks": {"data": []}}}},
        }
        result = LLMService._prepare_metadata_for_local_chat(metadata)
        assert result is None

    def test_non_local_mode_passes_through(self, monkeypatch):
        from spectra_sherpa.app.services.llm import LLMService

        class FakeConfig:
            mode = "hybrid"

        import spectra_sherpa.app.core.config as cfg_mod

        monkeypatch.setattr(cfg_mod, "app_config", FakeConfig())

        metadata = {"workflow_context": {"results_summary": {}}, "experiments": []}
        result = LLMService._prepare_metadata_for_local_chat(metadata)
        assert result is metadata  # Passed through unchanged
