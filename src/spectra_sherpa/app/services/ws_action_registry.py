"""Per-app WebSocket action registry.

This keeps the OSS host generic while allowing distributions to register
different action sets on a concrete app instance.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from fastapi import WebSocket

from spectra_sherpa.app.contracts.capabilities import CHAT_ASSISTANT
from spectra_sherpa.app.ws_actions import LLM_CHAT as LLM_CHAT_ACTION

WebSocketActionHandler = Callable[[WebSocket, dict[str, Any], Any, Any], Awaitable[None]]


@dataclass(frozen=True)
class WebSocketActionSpec:
    name: str
    handler: WebSocketActionHandler
    capability: str | None = None
    source: str = "oss"


class WebSocketActionRegistry:
    """Registry of WS actions for one concrete FastAPI app."""

    def __init__(self) -> None:
        self._actions: dict[str, WebSocketActionSpec] = {}

    def register(
        self,
        name: str,
        handler: WebSocketActionHandler,
        *,
        capability: str | None = None,
        source: str = "oss",
        replace: bool = False,
    ) -> None:
        if not replace and name in self._actions:
            raise ValueError(f"WebSocket action already registered: {name}")
        self._actions[name] = WebSocketActionSpec(
            name=name,
            handler=handler,
            capability=capability,
            source=source,
        )

    def get(self, name: str) -> WebSocketActionSpec | None:
        return self._actions.get(name)

    def names(self) -> tuple[str, ...]:
        return tuple(sorted(self._actions))

    async def dispatch(
        self,
        action: str,
        websocket: WebSocket,
        payload: dict[str, Any],
        user: Any,
        rate_limiter: Any,
    ) -> bool:
        spec = self.get(action)
        if spec is None:
            return False
        await spec.handler(websocket, payload, user, rate_limiter)
        return True


def build_default_ws_action_registry() -> WebSocketActionRegistry:
    registry = WebSocketActionRegistry()
    register_core_ws_actions(registry)
    return registry


def register_core_ws_actions(registry: WebSocketActionRegistry) -> None:
    from spectra_sherpa.app.services.ws_handlers import handle_llm_chat

    registry.register(
        LLM_CHAT_ACTION,
        handle_llm_chat,
        capability=CHAT_ASSISTANT,
        source="spectra-sherpa",
    )


