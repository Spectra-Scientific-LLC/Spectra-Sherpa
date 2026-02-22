"""Phase 3: LLM Integration + MCP tests."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

import numpy as np
import pytest

from spectra_sherpa.app.lib.sherpa_dataset import (
    DomainContext,
    EvaluationResult,
    SherpaDataset,
    SpectralAxis,
)
from spectra_sherpa.app.services.dataset_registry import dataset_registry

# ---------------------------------------------------------------------------
# Slice 1: write_data_story()
# ---------------------------------------------------------------------------


class TestWriteDataStory:
    @pytest.mark.asyncio
    async def test_with_dataset_info_uses_summarizer(self):
        """write_data_story uses JSON dict context."""
        dataset_info = {"name": "Corn NIR", "technique": "NIR"}

        with (
            patch(
                "spectra_sherpa.app.services.llm.LLMService._single_turn",
                new_callable=AsyncMock,
                return_value="NIR data story...",
            ) as mock_turn,
            patch(
                "spectra_sherpa.app.services.llm.LLMService.__init__",
                return_value=None,
            ),
        ):
            from spectra_sherpa.app.services.llm import LLMService

            svc = LLMService.__new__(LLMService)
            svc.user = None
            result = await svc.write_data_story(dataset_info=dataset_info)

            assert result == "NIR data story..."
            call_args = mock_turn.call_args[0][0]
            assert "Corn NIR" in call_args
            assert "NIR" in call_args


# ---------------------------------------------------------------------------
# Slice 1: _summarize_metadata
# ---------------------------------------------------------------------------


class TestSummarizeMetadata:
    def test_full_context_returns_full_json(self):
        """Full subscribers get complete JSON metadata."""
        from spectra_sherpa.app.services.llm import LLMService

        with patch.object(LLMService, "__init__", return_value=None):
            svc = LLMService.__new__(LLMService)

        metadata = {"experiments": [{"name": "Test", "nodes": [{"type": "model.pca"}]}]}
        with patch.object(LLMService, "_has_full_context", return_value=True):
            result = svc._summarize_metadata(metadata)
        assert "model.pca" in result
        parsed = json.loads(result)
        assert parsed["experiments"][0]["name"] == "Test"

    def test_basic_context_strips_details(self):
        """Free-tier users get only technique + node types."""
        from spectra_sherpa.app.services.llm import LLMService

        with patch.object(LLMService, "__init__", return_value=None):
            svc = LLMService.__new__(LLMService)

        metadata = {
            "experiments": [
                {
                    "name": "Test",
                    "technique": "IR",
                    "nodes": [{"type": "model.pca", "parameters": {"n_components": 5}}],
                }
            ]
        }
        with patch.object(LLMService, "_has_full_context", return_value=False):
            result = svc._summarize_metadata(metadata)
        parsed = json.loads(result)
        # Should have technique but not parameter values
        assert parsed["experiments"][0]["technique"] == "IR"
        assert "node_types" in parsed["experiments"][0]
        # Parameters should be stripped
        assert "nodes" not in parsed["experiments"][0]


# ---------------------------------------------------------------------------
# Slice 2: Dataset tool registration
# ---------------------------------------------------------------------------


class TestDatasetTools:
    def test_describe_dataset_registered(self):
        """describe_dataset tool is in the global registry."""
        import spectra_sherpa.app.services.tools.builtin  # noqa: F401
        from spectra_sherpa.app.services.tools.registry import tool_registry

        assert "describe_dataset" in tool_registry

    def test_get_dataset_quality_registered(self):
        """get_dataset_quality tool is in the global registry."""
        import spectra_sherpa.app.services.tools.builtin  # noqa: F401
        from spectra_sherpa.app.services.tools.registry import tool_registry

        assert "get_dataset_quality" in tool_registry

    def test_describe_dataset_returns_summary(self):
        """describe_dataset returns both summary and structured."""
        from spectra_sherpa.app.services.tools.builtin.datasets import describe_dataset

        ds = SherpaDataset(
            X=np.ones((5, 100)),
            spectral_axis=SpectralAxis(values=np.linspace(400, 4000, 100), units="cm-1"),
            domain=DomainContext(technique="IR"),
            title="Test Spectra",
        )
        dataset_id = dataset_registry.register(ds)
        result = describe_dataset(dataset_id=dataset_id, tier=1)

        assert "summary" in result
        assert "structured" in result
        assert "Test Spectra" in result["summary"]
        assert result["structured"]["domain"]["technique"] == "IR"
        assert result["dataset_id"] == dataset_id

    def test_describe_dataset_tier0(self):
        """Tier 0 returns shape and domain only."""
        from spectra_sherpa.app.services.tools.builtin.datasets import describe_dataset

        ds = SherpaDataset(
            X=np.zeros((3, 50)),
            domain=DomainContext(technique="NIR"),
            title="NIR Data",
        )
        dataset_id = dataset_registry.register(ds)
        result = describe_dataset(dataset_id=dataset_id, tier=0)
        assert "3 samples" in result["summary"]
        assert "NIR" in result["summary"]

    def test_get_dataset_quality_empty(self):
        """get_dataset_quality with no evaluations."""
        from spectra_sherpa.app.services.tools.builtin.datasets import get_dataset_quality

        ds = SherpaDataset(X=np.zeros((5, 10)))
        dataset_id = dataset_registry.register(ds)
        result = get_dataset_quality(dataset_id=dataset_id)
        assert result["n_evaluations"] == 0
        assert result["snr"] is None
        assert result["dataset_id"] == dataset_id

    def test_get_dataset_quality_with_evaluation(self):
        """get_dataset_quality returns latest evaluation."""
        from spectra_sherpa.app.services.tools.builtin.datasets import get_dataset_quality

        ds = SherpaDataset(X=np.zeros((5, 10)))
        ev = EvaluationResult(evaluation_id="ev1", model_type="PLS", r2=0.95)
        ds.quality.add_evaluation(ev)
        dataset_id = dataset_registry.register(ds)
        result = get_dataset_quality(dataset_id=dataset_id)
        assert result["n_evaluations"] == 1
        assert result["latest"]["model_type"] == "PLS"
        assert result["latest"]["r2"] == 0.95

    def test_tools_have_data_category(self):
        """Both tools are in the data category."""
        import spectra_sherpa.app.services.tools.builtin  # noqa: F401
        from spectra_sherpa.app.services.tools.registry import tool_registry

        defn1, _ = tool_registry.get("describe_dataset")
        defn2, _ = tool_registry.get("get_dataset_quality")
        assert defn1.category.value == "data"
        assert defn2.category.value == "data"


# ---------------------------------------------------------------------------
# Slice 3: WorkflowContextNode domain fields
# ---------------------------------------------------------------------------


class TestWorkflowContextNodeDomain:
    def test_new_fields_serialize(self):
        """New domain fields serialize correctly."""
        from spectra_sherpa.app.schemas.sherpa import WorkflowContextNode

        node = WorkflowContextNode(
            node_id="n1",
            node_type="data.eigenvector",
            domain_technique="IR",
            domain_data_quantity="Absorbance",
            processing_stage="preprocessed",
            processing_effects=["normalized", "baseline_corrected"],
        )
        d = node.model_dump()
        assert d["domain_technique"] == "IR"
        assert d["domain_data_quantity"] == "Absorbance"
        assert d["processing_stage"] == "preprocessed"
        assert d["processing_effects"] == ["normalized", "baseline_corrected"]

    def test_new_fields_default_none(self):
        """New domain fields default to None."""
        from spectra_sherpa.app.schemas.sherpa import WorkflowContextNode

        node = WorkflowContextNode(node_id="n1", node_type="model.pca")
        assert node.domain_technique is None
        assert node.domain_data_quantity is None
        assert node.processing_stage is None
        assert node.processing_effects is None

    def test_roundtrip_json(self):
        """Domain fields survive JSON round-trip."""
        from spectra_sherpa.app.schemas.sherpa import WorkflowContextNode

        node = WorkflowContextNode(
            node_id="n1",
            node_type="normalize.snv",
            domain_technique="NIR",
            processing_effects=["normalized"],
        )
        json_str = node.model_dump_json()
        restored = WorkflowContextNode.model_validate_json(json_str)
        assert restored.domain_technique == "NIR"
        assert restored.processing_effects == ["normalized"]

    def test_existing_fields_preserved(self):
        """Existing fields still work alongside new domain fields."""
        from spectra_sherpa.app.schemas.sherpa import WorkflowContextNode

        node = WorkflowContextNode(
            node_id="n1",
            node_type="model.pca",
            label="PCA",
            parameters={"n_components": 3},
            result_shape=[10, 3],
            domain_technique="IR",
        )
        assert node.label == "PCA"
        assert node.parameters == {"n_components": 3}
        assert node.result_shape == [10, 3]
        assert node.domain_technique == "IR"


# ---------------------------------------------------------------------------
# Slice 4: NodePolicy
# ---------------------------------------------------------------------------


class TestNodePolicy:
    def test_node_policy_defaults(self):
        """NodePolicy has safe defaults."""
        from spectra_sherpa.app.services.dag.node_base import NodePolicy

        policy = NodePolicy()
        assert policy.safe_for_auto_apply is False
        assert policy.requires_human_review is True
        assert policy.data_egress_risk == "none"

    def test_node_metadata_without_policy(self):
        """NodeMetadata without policy defaults to None."""
        from spectra_sherpa.app.services.dag.node_base import NodeMetadata

        meta = NodeMetadata(
            node_type="test.node",
            category="test",
            label="Test",
            description="A test node",
        )
        assert meta.policy is None

    def test_node_metadata_with_policy(self):
        """NodeMetadata accepts a policy."""
        from spectra_sherpa.app.services.dag.node_base import NodeMetadata, NodePolicy

        policy = NodePolicy(
            safe_for_auto_apply=True,
            requires_human_review=False,
            data_egress_risk="metadata",
        )
        meta = NodeMetadata(
            node_type="test.node",
            category="test",
            label="Test",
            description="A test node",
            policy=policy,
        )
        assert meta.policy.safe_for_auto_apply is True
        assert meta.policy.requires_human_review is False
        assert meta.policy.data_egress_risk == "metadata"

    def test_snv_node_has_preprocessing_policy(self):
        """SNV node is tagged as safe for auto-apply."""
        from spectra_sherpa.app.services.dag.node_base import node_registry

        meta = node_registry.get_metadata("normalize.snv")
        assert meta.policy is not None
        assert meta.policy.safe_for_auto_apply is True
        assert meta.policy.requires_human_review is False
        assert meta.policy.data_egress_risk == "none"

    def test_export_node_has_output_policy(self):
        """Export node requires human review with full data egress."""
        from spectra_sherpa.app.services.dag.node_base import node_registry

        meta = node_registry.get_metadata("output.export")
        assert meta.policy is not None
        assert meta.policy.safe_for_auto_apply is False
        assert meta.policy.requires_human_review is True
        assert meta.policy.data_egress_risk == "full_data"

    def test_pca_node_has_modeling_policy(self):
        """PCA node requires human review, no data egress."""
        from spectra_sherpa.app.services.dag.node_base import node_registry

        meta = node_registry.get_metadata("model.pca")
        assert meta.policy is not None
        assert meta.policy.safe_for_auto_apply is False
        assert meta.policy.requires_human_review is True
        assert meta.policy.data_egress_risk == "none"

    def test_untagged_node_no_policy(self):
        """Nodes without explicit policy have None."""
        from spectra_sherpa.app.services.dag.node_base import node_registry

        # Plot node should not have a policy
        meta = node_registry.get_metadata("output.plot")
        assert meta.policy is None
