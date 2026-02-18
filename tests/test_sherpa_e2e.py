"""
End-to-end Sherpa Advisor pipeline test.

Tests the full flow:
  1. Load a workflow with dataset + processing nodes
  2. Sync workflow state to Sherpa (sherpa_sync)
  3. Receive recommendations back
  4. Ask a follow-up question (sherpa_chat)
  5. Stream response chunks back

The cloud Sherpa service is mocked — the test verifies the local
pipeline from frontend payload → backend handler → advisor service →
response formatting.
"""
from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from spectra_sherpa.app.schemas.sherpa import (
    EgressTier,
    SherpaRecommendation,
    SuggestionCategory,
    SuggestionStatus,
    WorkflowContextEdge,
    WorkflowContextNode,
    WorkflowStateSync,
)
from spectra_sherpa.app.services.sherpa_advisor import (
    SherpaAdvisorService,
    filter_workflow_for_tier,
)


# ── Fixtures ──────────────────────────────────────────────────────

SAMPLE_WORKFLOW_PAYLOAD = {
    "workflow_id": 42,
    "workflow_name": "IR Preprocessing + PCA",
    "tier": "structure",
    "nodes": [
        {
            "node_id": "1",
            "node_type": "data.source",
            "label": "DATA",
            "parameters": {"source": "experiment"},
        },
        {
            "node_id": "2",
            "node_type": "baseline.penalized_ls",
            "label": "BASELINE",
            "parameters": {"method": "als", "lam": 100000, "p": 0.001},
        },
        {
            "node_id": "3",
            "node_type": "normalize.snv",
            "label": "SNV",
            "parameters": {},
        },
        {
            "node_id": "4",
            "node_type": "model.pca",
            "label": "PCA",
            "parameters": {"n_components": 5},
        },
    ],
    "edges": [
        {"from_node_id": "1", "to_node_id": "2"},
        {"from_node_id": "2", "to_node_id": "3"},
        {"from_node_id": "3", "to_node_id": "4"},
    ],
}

CLOUD_RECOMMENDATION_RESPONSE = {
    "recommendations": [
        {
            "suggestion_id": "rec-001",
            "workflow_id": 42,
            "category": "preprocessing",
            "title": "Consider adding derivative before PCA",
            "explanation": (
                "Your baseline-corrected spectra may still contain broad "
                "spectral features. A first derivative (Savitzky-Golay, "
                "window=15, poly=2) can enhance peaks and reduce baseline "
                "drift, often improving PCA separation."
            ),
            "confidence": 0.82,
            "status": "pending",
            "patch": {
                "nodes": [
                    {
                        "node_id": "5",
                        "action": "add",
                        "node_type": "derivative.first",
                        "label": "1st Derivative",
                        "parameters": {"size": 15, "order": 2},
                    }
                ],
                "edges": [
                    {"action": "remove", "from_node_id": "3", "to_node_id": "4"},
                    {"action": "add", "from_node_id": "3", "to_node_id": "5"},
                    {"action": "add", "from_node_id": "5", "to_node_id": "4"},
                ],
            },
        },
        {
            "suggestion_id": "rec-002",
            "workflow_id": 42,
            "category": "diagnostics",
            "title": "Check explained variance",
            "explanation": (
                "With 5 components, verify that cumulative explained "
                "variance exceeds 95%. If not, consider increasing "
                "n_components or review preprocessing."
            ),
            "confidence": 0.65,
            "status": "pending",
            "patch": None,
        },
    ]
}

CHAT_STREAM_LINES = [
    "The PCA node (node 4) performs dimensionality reduction ",
    "on your SNV-normalized spectra. With 5 components, ",
    "it captures the main spectral variation patterns.\n\n",
    "Looking at your preprocessing chain (baseline → SNV → PCA), ",
    "the scores plot would show sample groupings, while loadings ",
    "reveal which wavenumber regions drive the separation.",
]


# ── Unit Tests: Tier Filtering ────────────────────────────────────

class TestTierFiltering:
    """Verify that privacy tiers correctly strip data."""

    def _make_sync(self) -> WorkflowStateSync:
        return WorkflowStateSync(
            workflow_id=1,
            workflow_name="Test",
            tier=EgressTier.FULL,
            nodes=[
                WorkflowContextNode(
                    node_id="1",
                    node_type="model.pca",
                    label="PCA",
                    parameters={"n_components": 5},
                    result_shape=[100, 5],
                    result_statistics={"mean": 0.5, "std": 0.1},
                    explained_variance=[0.4, 0.2, 0.15, 0.1, 0.05],
                )
            ],
            edges=[],
            raw_data={"spectra": [[1.0, 2.0], [3.0, 4.0]]},
            n_samples=100,
            n_features=1000,
        )

    def test_structure_tier_strips_results(self):
        sync = self._make_sync()
        filtered = filter_workflow_for_tier(sync, EgressTier.STRUCTURE)
        node = filtered.nodes[0]
        assert node.node_id == "1"
        assert node.node_type == "model.pca"
        assert node.parameters == {"n_components": 5}
        # Results must be stripped
        assert node.result_shape is None
        assert node.result_statistics is None
        assert node.explained_variance is None
        # Raw data must be stripped
        assert filtered.raw_data is None

    def test_summaries_tier_keeps_stats(self):
        sync = self._make_sync()
        filtered = filter_workflow_for_tier(sync, EgressTier.SUMMARIES)
        node = filtered.nodes[0]
        assert node.result_shape == [100, 5]
        assert node.result_statistics == {"mean": 0.5, "std": 0.1}
        assert node.explained_variance == [0.4, 0.2, 0.15, 0.1, 0.05]
        # Raw data still stripped at summaries
        assert filtered.raw_data is None

    def test_full_tier_keeps_everything(self):
        sync = self._make_sync()
        filtered = filter_workflow_for_tier(sync, EgressTier.FULL)
        node = filtered.nodes[0]
        assert node.result_shape == [100, 5]
        assert filtered.raw_data is not None


# ── Unit Tests: SherpaAdvisorService ──────────────────────────────

class TestSherpaAdvisorSync:
    """Test sync_workflow with mocked cloud responses."""

    @pytest.fixture
    def advisor(self):
        svc = SherpaAdvisorService()
        return svc

    @patch("spectra_sherpa.app.services.sherpa_advisor.app_config")
    @patch("spectra_sherpa.app.services.sherpa_advisor._sherpa_api_key", return_value="test-key")
    @patch("spectra_sherpa.app.core.security.is_egress_enabled", return_value=True)
    async def test_sync_returns_recommendations(
        self, mock_egress, mock_key, mock_config, advisor
    ):
        mock_config.mode = "hybrid"

        # Mock the httpx client — use MagicMock for response since
        # httpx Response.json() and .raise_for_status() are synchronous
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = CLOUD_RECOMMENDATION_RESPONSE

        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.is_closed = False
        mock_client.post = AsyncMock(return_value=mock_response)
        advisor._client = mock_client

        sync = WorkflowStateSync(
            workflow_id=42,
            workflow_name="Test PCA",
            nodes=[
                WorkflowContextNode(
                    node_id="1",
                    node_type="model.pca",
                    label="PCA",
                    parameters={"n_components": 5},
                )
            ],
            edges=[],
        )

        recs = await advisor.sync_workflow(sync, tier=EgressTier.STRUCTURE)

        # Should return 2 recommendations
        assert len(recs) == 2
        assert recs[0].suggestion_id == "rec-001"
        assert recs[0].title == "Consider adding derivative before PCA"
        assert recs[0].category == SuggestionCategory.PREPROCESSING
        assert recs[0].confidence == 0.82
        assert recs[0].patch is not None
        assert len(recs[0].patch.nodes) == 1

        assert recs[1].suggestion_id == "rec-002"
        assert recs[1].title == "Check explained variance"
        assert recs[1].patch is None

        # Recommendations should be cached
        assert "rec-001" in advisor._recommendations
        assert "rec-002" in advisor._recommendations

    @patch("spectra_sherpa.app.services.sherpa_advisor.app_config")
    @patch("spectra_sherpa.app.services.sherpa_advisor._sherpa_api_key", return_value="test-key")
    @patch("spectra_sherpa.app.core.security.is_egress_enabled", return_value=True)
    async def test_sync_graceful_on_connect_error(
        self, mock_egress, mock_key, mock_config, advisor
    ):
        mock_config.mode = "hybrid"

        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.is_closed = False
        mock_client.post = AsyncMock(side_effect=httpx.ConnectError("Connection refused"))
        advisor._client = mock_client

        sync = WorkflowStateSync(
            workflow_id=42,
            nodes=[
                WorkflowContextNode(
                    node_id="1", node_type="model.pca", parameters={}
                )
            ],
            edges=[],
        )

        recs = await advisor.sync_workflow(sync)
        # Should return empty list, not raise
        assert recs == []

    @patch("spectra_sherpa.app.services.sherpa_advisor.app_config")
    @patch("spectra_sherpa.app.services.sherpa_advisor._sherpa_api_key", return_value=None)
    async def test_sync_returns_empty_when_not_configured(
        self, mock_key, mock_config, advisor
    ):
        mock_config.mode = "local"

        sync = WorkflowStateSync(
            workflow_id=42,
            nodes=[],
            edges=[],
        )
        recs = await advisor.sync_workflow(sync)
        assert recs == []


class TestSherpaAdvisorChat:
    """Test chat_followup streaming with mocked cloud."""

    @pytest.fixture
    def advisor(self):
        return SherpaAdvisorService()

    @patch("spectra_sherpa.app.services.sherpa_advisor.app_config")
    @patch("spectra_sherpa.app.services.sherpa_advisor._sherpa_api_key", return_value="test-key")
    @patch("spectra_sherpa.app.core.security.is_egress_enabled", return_value=True)
    async def test_chat_streams_chunks(
        self, mock_egress, mock_key, mock_config, advisor
    ):
        mock_config.mode = "hybrid"

        # Create a mock streaming response
        async def mock_aiter_lines():
            for line in CHAT_STREAM_LINES:
                yield line

        mock_response = AsyncMock()
        mock_response.status_code = 200
        mock_response.raise_for_status = MagicMock()
        mock_response.aiter_lines = mock_aiter_lines

        # Mock client.stream as async context manager
        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.is_closed = False
        mock_stream_cm = AsyncMock()
        mock_stream_cm.__aenter__ = AsyncMock(return_value=mock_response)
        mock_stream_cm.__aexit__ = AsyncMock(return_value=False)
        mock_client.stream = MagicMock(return_value=mock_stream_cm)
        advisor._client = mock_client

        chunks = []
        async for chunk in advisor.chat_followup(
            message="How would you interpret the result from PCA?",
            workflow_id=42,
            history=[],
        ):
            chunks.append(chunk)

        # Should have received all chunks
        assert len(chunks) == len(CHAT_STREAM_LINES)
        full_response = "".join(chunks)
        assert "PCA node" in full_response
        assert "scores plot" in full_response

    @patch("spectra_sherpa.app.services.sherpa_advisor.app_config")
    @patch("spectra_sherpa.app.services.sherpa_advisor._sherpa_api_key", return_value="test-key")
    @patch("spectra_sherpa.app.core.security.is_egress_enabled", return_value=True)
    async def test_chat_fallback_on_404(
        self, mock_egress, mock_key, mock_config, advisor
    ):
        mock_config.mode = "hybrid"

        # Simulate 404 from cloud (endpoint not built yet)
        mock_response = MagicMock()
        mock_response.status_code = 404
        http_error = httpx.HTTPStatusError(
            "Not Found", request=MagicMock(), response=mock_response
        )

        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.is_closed = False

        mock_stream_cm = AsyncMock()
        mock_stream_cm.__aenter__ = AsyncMock(side_effect=http_error)
        mock_stream_cm.__aexit__ = AsyncMock(return_value=False)
        mock_client.stream = MagicMock(return_value=mock_stream_cm)
        advisor._client = mock_client

        chunks = []
        async for chunk in advisor.chat_followup(
            message="What does PCA show?",
            workflow_id=42,
        ):
            chunks.append(chunk)

        assert len(chunks) == 1
        assert "coming soon" in chunks[0].lower()

    @patch("spectra_sherpa.app.services.sherpa_advisor.app_config")
    @patch("spectra_sherpa.app.services.sherpa_advisor._sherpa_api_key", return_value="test-key")
    @patch("spectra_sherpa.app.core.security.is_egress_enabled", return_value=True)
    async def test_chat_fallback_on_connect_error(
        self, mock_egress, mock_key, mock_config, advisor
    ):
        mock_config.mode = "hybrid"

        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.is_closed = False

        mock_stream_cm = AsyncMock()
        mock_stream_cm.__aenter__ = AsyncMock(
            side_effect=httpx.ConnectError("Connection refused")
        )
        mock_stream_cm.__aexit__ = AsyncMock(return_value=False)
        mock_client.stream = MagicMock(return_value=mock_stream_cm)
        advisor._client = mock_client

        chunks = []
        async for chunk in advisor.chat_followup(
            message="What does PCA show?",
        ):
            chunks.append(chunk)

        assert len(chunks) == 1
        assert "unreachable" in chunks[0].lower()

    @patch("spectra_sherpa.app.services.sherpa_advisor.app_config")
    @patch("spectra_sherpa.app.services.sherpa_advisor._sherpa_api_key", return_value=None)
    async def test_chat_fallback_when_not_available(
        self, mock_key, mock_config, advisor
    ):
        mock_config.mode = "local"

        chunks = []
        async for chunk in advisor.chat_followup(message="Hello"):
            chunks.append(chunk)

        assert len(chunks) == 1
        assert "not currently available" in chunks[0].lower()


# ── Integration Test: Payload Roundtrip ───────────────────────────

class TestPayloadRoundtrip:
    """
    Simulate the full frontend→backend payload flow:
    frontend builds payload → backend parses → advisor processes → response formatted.
    """

    @patch("spectra_sherpa.app.services.sherpa_advisor.app_config")
    @patch("spectra_sherpa.app.services.sherpa_advisor._sherpa_api_key", return_value="test-key")
    @patch("spectra_sherpa.app.core.security.is_egress_enabled", return_value=True)
    async def test_sync_payload_roundtrip(
        self, mock_egress, mock_key, mock_config
    ):
        """Simulate: frontend payload → parse → advisor.sync_workflow → WS response."""
        mock_config.mode = "hybrid"

        advisor = SherpaAdvisorService()

        # Mock cloud response — MagicMock since httpx .json()/.raise_for_status() are sync
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = CLOUD_RECOMMENDATION_RESPONSE

        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.is_closed = False
        mock_client.post = AsyncMock(return_value=mock_response)
        advisor._client = mock_client

        # Step 1: Simulate what the frontend sends via WebSocket
        ws_payload = {
            "action": "sherpa_sync",
            "payload": SAMPLE_WORKFLOW_PAYLOAD.copy(),
        }

        # Step 2: Backend handler logic (from main.py)
        sync_data = dict(ws_payload["payload"])
        tier = EgressTier(sync_data.pop("tier", "structure"))
        sync_msg = WorkflowStateSync(**sync_data)

        # Verify parsing worked
        assert sync_msg.workflow_id == 42
        assert sync_msg.workflow_name == "IR Preprocessing + PCA"
        assert len(sync_msg.nodes) == 4
        assert len(sync_msg.edges) == 3
        assert sync_msg.nodes[0].node_type == "data.source"
        assert sync_msg.nodes[3].node_type == "model.pca"
        assert sync_msg.nodes[3].parameters == {"n_components": 5}

        # Step 3: Advisor processes
        recommendations = await advisor.sync_workflow(sync_msg, tier=tier)

        # Step 4: Format as WebSocket response (from main.py)
        ws_response = {
            "type": "sherpa_recommendations",
            "payload": [r.model_dump(mode="json") for r in recommendations],
        }

        # Verify response structure
        assert ws_response["type"] == "sherpa_recommendations"
        assert len(ws_response["payload"]) == 2

        rec1 = ws_response["payload"][0]
        assert rec1["suggestion_id"] == "rec-001"
        assert rec1["category"] == "preprocessing"
        assert rec1["confidence"] == 0.82
        assert rec1["patch"] is not None
        assert rec1["patch"]["nodes"][0]["action"] == "add"

        rec2 = ws_response["payload"][1]
        assert rec2["suggestion_id"] == "rec-002"
        assert rec2["patch"] is None

        await advisor.close()

    @patch("spectra_sherpa.app.services.sherpa_advisor.app_config")
    @patch("spectra_sherpa.app.services.sherpa_advisor._sherpa_api_key", return_value="test-key")
    @patch("spectra_sherpa.app.core.security.is_egress_enabled", return_value=True)
    async def test_chat_payload_roundtrip(
        self, mock_egress, mock_key, mock_config
    ):
        """Simulate: frontend chat payload → parse → advisor.chat_followup → WS chunks."""
        mock_config.mode = "hybrid"

        advisor = SherpaAdvisorService()

        # Mock streaming response
        async def mock_aiter_lines():
            for line in CHAT_STREAM_LINES:
                yield line

        mock_response = AsyncMock()
        mock_response.status_code = 200
        mock_response.raise_for_status = MagicMock()
        mock_response.aiter_lines = mock_aiter_lines

        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.is_closed = False
        mock_stream_cm = AsyncMock()
        mock_stream_cm.__aenter__ = AsyncMock(return_value=mock_response)
        mock_stream_cm.__aexit__ = AsyncMock(return_value=False)
        mock_client.stream = MagicMock(return_value=mock_stream_cm)
        advisor._client = mock_client

        # Step 1: Frontend sends sherpa_chat
        ws_payload = {
            "action": "sherpa_chat",
            "payload": {
                "message": "How would you interpret the result from PCA node?",
                "workflow_id": 42,
                "history": [
                    {"role": "user", "content": "Analyze my workflow"},
                    {"role": "assistant", "content": "Your workflow has 4 nodes..."},
                ],
            },
        }

        # Step 2: Backend handler extracts data
        chat_data = ws_payload["payload"]
        message = chat_data["message"]
        workflow_id = chat_data["workflow_id"]
        history = chat_data["history"]

        # Step 3: Collect streaming chunks (simulating WS sends)
        ws_messages: list[dict[str, Any]] = []
        ws_messages.append({"type": "sherpa_chat_start"})

        async for chunk in advisor.chat_followup(
            message=message, workflow_id=workflow_id, history=history
        ):
            ws_messages.append({"type": "sherpa_chat_chunk", "chunk": chunk})

        ws_messages.append({"type": "sherpa_chat_done"})

        # Step 4: Verify WS message sequence
        assert ws_messages[0]["type"] == "sherpa_chat_start"
        assert ws_messages[-1]["type"] == "sherpa_chat_done"

        # All middle messages are chunks
        chunk_messages = [m for m in ws_messages if m["type"] == "sherpa_chat_chunk"]
        assert len(chunk_messages) == len(CHAT_STREAM_LINES)

        # Reconstruct full response (what frontend would display)
        full_response = "".join(m["chunk"] for m in chunk_messages)
        assert "PCA node (node 4)" in full_response
        assert "dimensionality reduction" in full_response
        assert "scores plot" in full_response
        assert "wavenumber regions" in full_response

        await advisor.close()


# ── Decision Lifecycle Test ───────────────────────────────────────

class TestSuggestionLifecycle:
    """Test that accepting/rejecting suggestions updates state correctly."""

    @patch("spectra_sherpa.app.services.sherpa_advisor.app_config")
    @patch("spectra_sherpa.app.services.sherpa_advisor._sherpa_api_key", return_value="test-key")
    @patch("spectra_sherpa.app.core.security.is_egress_enabled", return_value=True)
    async def test_accept_recommendation(
        self, mock_egress, mock_key, mock_config
    ):
        mock_config.mode = "hybrid"

        advisor = SherpaAdvisorService()

        # Pre-populate cache with a recommendation
        from spectra_sherpa.app.schemas.sherpa import UserDecision

        rec = SherpaRecommendation(
            suggestion_id="rec-001",
            workflow_id=42,
            category=SuggestionCategory.PREPROCESSING,
            title="Test recommendation",
            explanation="Test explanation",
            confidence=0.8,
        )
        advisor._recommendations["rec-001"] = rec

        # Mock the cloud POST for decision — MagicMock since .raise_for_status() is sync
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.is_closed = False
        mock_client.post = AsyncMock(return_value=mock_response)
        advisor._client = mock_client

        decision = UserDecision(
            workflow_id=42,
            suggestion_id="rec-001",
            accepted=True,
            feedback="Looks good, applying it.",
        )

        delivered = await advisor.send_decision(decision)
        assert delivered is True
        assert advisor._recommendations["rec-001"].status == SuggestionStatus.ACCEPTED

        await advisor.close()
