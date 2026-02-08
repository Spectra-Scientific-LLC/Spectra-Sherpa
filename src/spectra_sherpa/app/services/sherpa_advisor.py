"""
Sherpa Advisor Service — local→cloud client for AI-guided workflow advice.

This service manages the bidirectional communication between the local
SpectraSherpa app and the cloud spectrasherpa-server Sherpa brain.

Responsibilities:
- Send workflow context to the cloud Sherpa (respecting the user's EgressTier)
- Receive and cache SherpaRecommendations
- Track suggestion lifecycle (pending → accepted/rejected/expired)
- Gracefully degrade when cloud is unreachable (no-op, not crash)

All outgoing data is filtered by the user's EgressTier *before* leaving
this module — the cloud never sees more than the user allowed.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

import httpx

from app.core.config import app_config, settings
from app.schemas.sherpa import (
    EgressTier,
    ExplorationResult,
    SherpaRecommendation,
    SuggestionStatus,
    UserDecision,
    WorkflowContextEdge,
    WorkflowContextNode,
    WorkflowStateSync,
)

logger = logging.getLogger(__name__)


# ── Configuration ────────────────────────────────────────────────────

SHERPA_TIMEOUT = 15.0  # seconds — slightly longer than standard for LLM calls


def _sherpa_base_url() -> str:
    """Resolve the Sherpa endpoint from the SpectraSherpa config."""
    from app.services.spectrasherpa import spectrasherpa_config

    base = spectrasherpa_config.api_base_url.rstrip("/")
    if not base.endswith("/api/v1"):
        base = f"{base}/api/v1"
    return base


def _sherpa_api_key() -> str | None:
    from app.services.spectrasherpa import spectrasherpa_config

    return spectrasherpa_config.api_key


# ── Tier-aware filtering ─────────────────────────────────────────────

def filter_workflow_for_tier(
    sync: WorkflowStateSync,
    tier: EgressTier,
) -> WorkflowStateSync:
    """
    Strip fields from *sync* that exceed the requested *tier*.

    This is the privacy gate — nothing above the tier leaves the machine.
    """
    if tier == EgressTier.FULL:
        return sync  # everything allowed

    # Start from a copy so we don't mutate the original
    filtered_nodes: list[WorkflowContextNode] = []
    for node in sync.nodes:
        if tier == EgressTier.STRUCTURE:
            # Strip all result data — keep only type, label, parameters
            filtered_nodes.append(
                WorkflowContextNode(
                    node_id=node.node_id,
                    node_type=node.node_type,
                    label=node.label,
                    parameters=node.parameters,
                )
            )
        elif tier == EgressTier.SUMMARIES:
            # Keep summaries but strip raw data references
            filtered_nodes.append(
                WorkflowContextNode(
                    node_id=node.node_id,
                    node_type=node.node_type,
                    label=node.label,
                    parameters=node.parameters,
                    result_shape=node.result_shape,
                    result_statistics=node.result_statistics,
                    explained_variance=node.explained_variance,
                )
            )

    return WorkflowStateSync(
        workflow_id=sync.workflow_id,
        workflow_name=sync.workflow_name,
        tier=tier,
        nodes=filtered_nodes,
        edges=sync.edges,
        raw_data=None if tier != EgressTier.FULL else sync.raw_data,
        spectral_technique=sync.spectral_technique,
        n_samples=sync.n_samples,
        n_features=sync.n_features,
        timestamp=sync.timestamp,
    )


# ── Service ──────────────────────────────────────────────────────────

class SherpaAdvisorService:
    """
    Client that talks to the cloud Sherpa brain on behalf of the local app.

    Usage::

        advisor = get_sherpa_advisor()

        # 1. Sync current workflow state
        recs = await advisor.sync_workflow(workflow_sync, tier=EgressTier.SUMMARIES)

        # 2. User accepts a suggestion
        await advisor.send_decision(UserDecision(...))

        # 3. Request autonomous exploration (opt-in)
        result = await advisor.request_exploration(workflow_id=42)
    """

    def __init__(self) -> None:
        self._client: httpx.AsyncClient | None = None
        # Local cache of pending recommendations (keyed by suggestion_id)
        self._recommendations: dict[str, SherpaRecommendation] = {}

    # ── lifecycle ──────────────────────────────────────────────────

    @property
    def is_available(self) -> bool:
        """True when the cloud Sherpa is configured and egress is on."""
        from app.core.security import is_egress_enabled

        return (
            app_config.mode in ("hybrid", "demo")
            and _sherpa_api_key() is not None
            and is_egress_enabled()
        )

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                base_url=_sherpa_base_url(),
                timeout=SHERPA_TIMEOUT,
                headers={
                    "X-API-Key": _sherpa_api_key() or "",
                    "User-Agent": f"SpectraSherpaLite/{settings.app_version}",
                    "X-Client-Mode": app_config.mode,
                },
            )
        return self._client

    async def close(self) -> None:
        if self._client and not self._client.is_closed:
            await self._client.aclose()
            self._client = None

    # ── core operations ───────────────────────────────────────────

    async def sync_workflow(
        self,
        sync: WorkflowStateSync,
        tier: EgressTier = EgressTier.STRUCTURE,
    ) -> list[SherpaRecommendation]:
        """
        Send the current workflow state to the cloud Sherpa.

        Returns a list of recommendations (may be empty if Sherpa has no
        suggestions or if the service is unreachable).
        """
        if not self.is_available:
            return []

        filtered = filter_workflow_for_tier(sync, tier)

        try:
            client = await self._get_client()
            response = await client.post(
                "/sherpa/sync",
                json=filtered.model_dump(mode="json"),
            )
            response.raise_for_status()
            data = response.json()

            recommendations = [
                SherpaRecommendation(**rec)
                for rec in data.get("recommendations", [])
            ]

            # Cache locally
            for rec in recommendations:
                self._recommendations[rec.suggestion_id] = rec

            # Expire any previous recommendations for this workflow
            self._expire_old(sync.workflow_id, keep=recommendations)

            return recommendations

        except httpx.ConnectError:
            logger.warning("Sherpa cloud unreachable — continuing in local mode")
            return []
        except httpx.TimeoutException:
            logger.warning("Sherpa cloud timed out — continuing in local mode")
            return []
        except httpx.HTTPStatusError as exc:
            logger.warning("Sherpa sync failed: HTTP %s", exc.response.status_code)
            return []
        except Exception:
            logger.exception("Unexpected error during Sherpa sync")
            return []

    async def send_decision(self, decision: UserDecision) -> bool:
        """
        Notify the cloud Sherpa that the user accepted or rejected a suggestion.

        Returns True if the decision was delivered.
        """
        if not self.is_available:
            return False

        # Update local cache
        rec = self._recommendations.get(decision.suggestion_id)
        if rec:
            rec.status = (
                SuggestionStatus.ACCEPTED if decision.accepted
                else SuggestionStatus.REJECTED
            )

        try:
            client = await self._get_client()
            response = await client.post(
                "/sherpa/decide",
                json=decision.model_dump(mode="json"),
            )
            response.raise_for_status()
            return True
        except Exception:
            logger.warning("Failed to send decision to Sherpa cloud")
            return False

    async def request_exploration(
        self,
        workflow_id: int,
        tier: EgressTier = EgressTier.SUMMARIES,
    ) -> ExplorationResult | None:
        """
        Ask Sherpa to autonomously explore parameter space for a workflow.

        This is an opt-in feature: the user must explicitly request it.
        Returns the exploration result or None if unavailable.
        """
        if not self.is_available:
            return None

        try:
            client = await self._get_client()
            response = await client.post(
                "/sherpa/explore",
                json={"workflow_id": workflow_id, "tier": tier.value},
            )
            response.raise_for_status()
            return ExplorationResult(**response.json())
        except Exception:
            logger.warning("Sherpa exploration request failed")
            return None

    async def health_check(self) -> tuple[bool, str]:
        """Check if the Sherpa endpoint is reachable."""
        if not self.is_available:
            return False, "Sherpa advisor not configured or egress disabled"

        try:
            client = await self._get_client()
            response = await client.get("/sherpa/health")
            if response.status_code == 200:
                return True, "Sherpa advisor is healthy"
            return False, f"Sherpa returned status {response.status_code}"
        except httpx.ConnectError:
            return False, "Cannot connect to Sherpa cloud"
        except httpx.TimeoutException:
            return False, "Sherpa cloud timed out"
        except Exception as exc:
            return False, f"Health check failed: {exc}"

    # ── local cache helpers ───────────────────────────────────────

    def get_pending(self, workflow_id: int | None = None) -> list[SherpaRecommendation]:
        """Return all pending recommendations, optionally filtered by workflow."""
        return [
            rec for rec in self._recommendations.values()
            if rec.status == SuggestionStatus.PENDING
            and (workflow_id is None or rec.workflow_id == workflow_id)
        ]

    def _expire_old(
        self,
        workflow_id: int,
        keep: list[SherpaRecommendation],
    ) -> None:
        """Mark previous pending recommendations as expired when new ones arrive."""
        keep_ids = {r.suggestion_id for r in keep}
        for rec in self._recommendations.values():
            if (
                rec.workflow_id == workflow_id
                and rec.status == SuggestionStatus.PENDING
                and rec.suggestion_id not in keep_ids
            ):
                rec.status = SuggestionStatus.EXPIRED


# ── Singleton ────────────────────────────────────────────────────────

_advisor_instance: SherpaAdvisorService | None = None


def get_sherpa_advisor() -> SherpaAdvisorService:
    """Get the singleton Sherpa advisor instance."""
    global _advisor_instance
    if _advisor_instance is None:
        _advisor_instance = SherpaAdvisorService()
    return _advisor_instance


async def close_sherpa_advisor() -> None:
    """Close the singleton advisor (call on app shutdown)."""
    global _advisor_instance
    if _advisor_instance:
        await _advisor_instance.close()
        _advisor_instance = None
