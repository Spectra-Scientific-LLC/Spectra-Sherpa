"""AI provider registry plus OSS-safe defaults.

This module is intentionally thin: it owns the global provider registry,
shared exception types, and the disabled OSS fallback. The concrete
deployment-key transport lives in ``deployment_ai_provider.py`` and the
server can inject its own in-process implementation during startup.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from typing import Any

from spectra_sherpa.app.contracts.ai_provider import AIServiceProvider
from spectra_sherpa.app.services.deployment_ai_provider import DeploymentAIProvider

logger = logging.getLogger(__name__)


class DisabledAIProvider:
    """OSS-safe fallback provider when no deployment-backed AI is configured."""

    @property
    def is_available(self) -> bool:
        return False

    def has_feature(self, feature: str) -> bool:
        return False

    async def stream_llm_chat(
        self,
        *,
        message: str,
        conversation_id: str | None = None,
        workflow_context: dict[str, Any] | None = None,
        local_user_id: int | None = None,
        project_id: int | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        yield {"type": "error", "detail": "AI provider not configured"}

    async def sync_workflow(self, sync_msg: Any, *, tier: Any) -> list[Any]:
        return []

    async def send_decision(self, decision: Any) -> bool:
        return False

    async def identify_peaks(self, *, wavenumbers: list[float], absorbance: list[float]) -> dict[str, Any]:
        return {"response": ""}

    async def generate_code(self, *, task_description: str, context: dict[str, Any] | None = None) -> dict[str, Any]:
        return {"response": ""}

    async def write_report(self, *, experiment: dict[str, Any]) -> dict[str, Any]:
        return {"response": "", "report": ""}

    async def generate_data_story(
        self,
        *,
        dataset_info: dict[str, Any],
        additional_context: str | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        yield {"type": "error", "detail": "AI provider not configured"}

    async def chat_followup(
        self,
        *,
        message: str,
        workflow_id: int | None = None,
        history: list[dict[str, str]] | None = None,
        workflow_context: dict[str, Any] | None = None,
    ) -> AsyncIterator[str]:
        if False:
            yield ""
        return

    async def chat_with_tools(
        self,
        *,
        message: str,
        history: list[dict[str, str]] | None = None,
        workflow_context: dict[str, Any] | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        if False:
            yield {}
        return


# Global singleton instance
_advisor: AIServiceProvider | None = None


def _build_default_advisor() -> AIServiceProvider:
    from spectra_sherpa.app.services.spectrasherpa import spectrasherpa_config

    if spectrasherpa_config.api_key:
        return DeploymentAIProvider()
    return DisabledAIProvider()


def get_sherpa_advisor() -> AIServiceProvider:
    """Get the global Sherpa AI Advisor instance.

    Returns the OSS stub or a server-injected implementation.
    """
    global _advisor
    if _advisor is None:
        _advisor = _build_default_advisor()
    return _advisor


def set_sherpa_advisor(advisor: AIServiceProvider) -> None:
    """Inject a custom Sherpa AI Advisor implementation.

    Used by spectra-server to replace the OSS stub with a full
    cloud-connected implementation.  The injected object must
    satisfy the ``AIServiceProvider`` protocol.
    """
    global _advisor
    _advisor = advisor
    logger.info("SherpaAdvisor: custom implementation injected")


def reset_sherpa_advisor():
    """Reset to OSS stub mode (for testing)."""
    global _advisor
    _advisor = None
