"""Abstract AI service provider protocol.

OSS ships a stub ``SherpaAdvisor`` that returns disabled/empty responses.
The server can inject a full implementation via ``set_sherpa_advisor()``.

This protocol formalizes the public surface that WebSocket handlers and
route code may call, so that both the stub and any server-provided
implementation satisfy the same type contract.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class AIServiceProvider(Protocol):
    """Minimal contract for the Sherpa AI advisor service.

    OSS WebSocket handlers and route code program against this protocol.
    The concrete ``SherpaAdvisor`` class (and any server override)
    must satisfy it.
    """

    @property
    def is_available(self) -> bool:
        """Whether the AI backend is configured and reachable."""
        ...

    def has_feature(self, feature: str) -> bool:
        """Check if a specific AI feature is enabled."""
        ...

    # ── Unary request/response methods ───────────────────────────────

    async def sync_workflow(self, sync_msg: Any, *, tier: Any) -> list[Any]:
        """Proxy workflow sync and return recommendations."""
        ...

    async def send_decision(self, decision: Any) -> bool:
        """Acknowledge a user decision."""
        ...

    async def identify_peaks(self, *, wavenumbers: list[float], absorbance: list[float]) -> dict[str, Any]:
        """Identify spectral peaks."""
        ...

    async def generate_code(self, *, task_description: str, context: dict[str, Any] | None = None) -> dict[str, Any]:
        """Generate code for a given task."""
        ...

    async def write_report(self, *, experiment: dict[str, Any]) -> dict[str, Any]:
        """Generate a report from experiment data."""
        ...

    async def generate_data_story(
        self,
        *,
        dataset_info: dict[str, Any],
        additional_context: str | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        """Stream a narrative data story. Yields {type: 'chunk', text: ...} events."""
        yield {}  # pragma: no cover — protocol stub

    # ── Streaming methods ────────────────────────────────────────────

    async def stream_llm_chat(
        self,
        *,
        message: str,
        conversation_id: str | None = None,
        workflow_context: dict[str, Any] | None = None,
        local_user_id: int | None = None,
        project_id: int | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        """Stream LLM chat events for the conversation UI.

        Yields dicts with ``type`` in {``start``, ``chunk``, ``done``, ``error``}.
        Each event carries a ``conversation_id`` for client-side correlation.
        """
        ...

    async def chat_followup(
        self,
        *,
        message: str,
        workflow_id: int | None = None,
        history: list[dict[str, str]] | None = None,
        workflow_context: dict[str, Any] | None = None,
    ) -> AsyncIterator[str]:
        """Stream follow-up chat text chunks."""
        ...

    async def chat_with_tools(
        self,
        *,
        message: str,
        history: list[dict[str, str]] | None = None,
        workflow_context: dict[str, Any] | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        """Stream agentic chat events."""
        ...
