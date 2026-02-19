"""
Sherpa Protocol — typed message schema for local ↔ cloud advisor communication.

This defines the contract between the local SpectraSherpa app and the
cloud spectrasherpa-server Sherpa brain.  All messages flow through a dedicated
WebSocket action (``sherpa_*``) or HTTP endpoints on the server.

Data sharing tiers
------------------
- **structure**: Workflow graph only (node types, connections, parameters).
- **summaries**: + result shapes, statistics, explained variance, scores.
- **full**:     + raw spectral arrays.  Required for cloud-side computation.

The local app filters outgoing data to match the user's selected tier before
sending any ``WorkflowStateSync`` message.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field

# ── Enums ───────────────────────────────────────────────────────────


class EgressTier(str, Enum):
    """How much data the user allows Sherpa to see."""

    STRUCTURE = "structure"  # node types, connections, parameters only
    SUMMARIES = "summaries"  # + result shapes, statistics, scores
    FULL = "full"  # + raw spectral arrays


class SuggestionStatus(str, Enum):
    """Lifecycle of a suggestion."""

    PENDING = "pending"  # delivered, awaiting user decision
    ACCEPTED = "accepted"  # user applied the patch
    REJECTED = "rejected"  # user dismissed
    EXPIRED = "expired"  # superseded by workflow change


class SuggestionCategory(str, Enum):
    """What kind of advice Sherpa is giving."""

    PREPROCESSING = "preprocessing"
    MODELING = "modeling"
    DIAGNOSTICS = "diagnostics"
    PARAMETER_TUNING = "parameter_tuning"
    WORKFLOW_STRUCTURE = "workflow_structure"
    DATA_QUALITY = "data_quality"


# ── Workflow Patch (structured diff) ────────────────────────────────


class NodePatch(BaseModel):
    """A single node to add, modify, or remove."""

    node_id: str
    action: Literal["add", "modify", "remove"]
    node_type: str | None = None  # required for "add"
    label: str | None = None
    parameters: dict[str, Any] | None = None  # new/updated params
    position_x: float | None = None
    position_y: float | None = None


class EdgePatch(BaseModel):
    """A single edge to add or remove."""

    action: Literal["add", "remove"]
    from_node_id: str
    to_node_id: str
    from_output: str = "default"
    to_input: str = "default"


class WorkflowPatch(BaseModel):
    """Structured diff that can be previewed and applied atomically."""

    nodes: list[NodePatch] = Field(default_factory=list)
    edges: list[EdgePatch] = Field(default_factory=list)


# ── Messages: Local → Cloud ────────────────────────────────────────


class WorkflowContextNode(BaseModel):
    """Serialized node for Sherpa context (tier-aware)."""

    node_id: str
    node_type: str
    label: str | None = None
    parameters: dict[str, Any] = Field(default_factory=dict)
    # Tier 2+: result summaries
    result_shape: list[int] | None = None
    result_statistics: dict[str, float] | None = None  # mean, std, min, max
    explained_variance: list[float] | None = None
    # Tier 3: raw data included in separate field (not here)


class WorkflowContextEdge(BaseModel):
    """Serialized edge for Sherpa context."""

    from_node_id: str
    to_node_id: str
    from_output: str = "default"
    to_input: str = "default"


class WorkflowStateSync(BaseModel):
    """Local app sends current workflow state to Sherpa for analysis.

    The ``tier`` field controls how much data is included.  The local app
    is responsible for filtering before sending.
    """

    workflow_id: int
    workflow_name: str | None = None
    tier: EgressTier = EgressTier.STRUCTURE
    nodes: list[WorkflowContextNode]
    edges: list[WorkflowContextEdge]
    # Tier 2+: per-node result summaries embedded in nodes above
    # Tier 3: raw data (sent as separate binary or base64 payload)
    raw_data: dict[str, Any] | None = None
    # Context
    spectral_technique: str | None = None  # "IR", "NIR", "Raman", "UV-Vis"
    n_samples: int | None = None
    n_features: int | None = None
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class UserDecision(BaseModel):
    """User accepts or rejects a Sherpa suggestion."""

    workflow_id: int
    suggestion_id: str
    accepted: bool
    feedback: str | None = None  # optional free-text from user
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class SherpaChatRequest(BaseModel):
    """Follow-up question from user to Sherpa about the current workflow."""

    message: str
    workflow_id: int | None = None
    history: list[dict[str, str]] = Field(default_factory=list)


# ── Messages: Cloud → Local ────────────────────────────────────────


class SherpaRecommendation(BaseModel):
    """A single suggestion from Sherpa, with both explanation and action."""

    suggestion_id: str
    workflow_id: int
    category: SuggestionCategory
    title: str  # short summary (< 80 chars)
    explanation: str  # natural language rationale (markdown)
    patch: WorkflowPatch | None = None  # structured action (None = advice only)
    confidence: float = Field(ge=0.0, le=1.0, description="0-1 confidence score")
    status: SuggestionStatus = SuggestionStatus.PENDING
    created_at: datetime = Field(default_factory=datetime.utcnow)


class ExplorationResult(BaseModel):
    """Result from Sherpa's autonomous exploration (user opted in)."""

    workflow_id: int
    exploration_id: str
    summary: str  # what Sherpa tried and found
    recommendations: list[SherpaRecommendation] = Field(default_factory=list)
    metrics_before: dict[str, float] | None = None  # e.g., RMSECV, R²
    metrics_after: dict[str, float] | None = None
    created_at: datetime = Field(default_factory=datetime.utcnow)


# ── WebSocket Envelope ──────────────────────────────────────────────


class SherpaWSMessage(BaseModel):
    """Envelope for all Sherpa WebSocket messages.

    Usage on the ``/ws`` endpoint::

        # Local → Cloud
        {"action": "sherpa_sync",    "payload": WorkflowStateSync}
        {"action": "sherpa_decide",  "payload": UserDecision}
        {"action": "sherpa_chat",    "payload": SherpaChatRequest}

        # Cloud → Local (pushed via subscription)
        {"type": "sherpa_recommendations", "payload": [SherpaRecommendation]}
        {"type": "sherpa_chat_start"}
        {"type": "sherpa_chat_chunk", "chunk": "..."}
        {"type": "sherpa_chat_done"}
        {"type": "sherpa_status",          "payload": {"connected": true}}
    """

    action: str | None = None  # for client-sent messages
    type: str | None = None  # for server-sent messages
    payload: dict[str, Any] = Field(default_factory=dict)
