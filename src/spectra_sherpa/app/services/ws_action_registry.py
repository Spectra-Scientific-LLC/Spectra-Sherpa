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
from spectra_sherpa.app.services.ws_requests import CANCEL_REQUEST, RequestPolicy, WebSocketRequests
from spectra_sherpa.app.ws_actions import LLM_CHAT as LLM_CHAT_ACTION

WebSocketActionAuthorizer = Callable[[str, WebSocket, dict[str, Any], Any], Awaitable[bool]]

WebSocketActionHandler = Callable[[WebSocket, dict[str, Any], Any, Any], Awaitable[None]]


@dataclass(frozen=True)
class WebSocketActionSpec:
    name: str
    handler: WebSocketActionHandler
    capability: str | None = None
    source: str = "oss"
    error_event: str = "error"
    request_policy: RequestPolicy | None = None


class WebSocketActionRegistry:
    """Registry of WS actions for one concrete FastAPI app."""

    def __init__(self) -> None:
        self.requests = WebSocketRequests()
        self._actions: dict[str, WebSocketActionSpec] = {}
        self._authorizer: WebSocketActionAuthorizer | None = None

    def set_authorizer(self, authorizer: WebSocketActionAuthorizer) -> None:
        self._authorizer = authorizer

    def register(
        self,
        name: str,
        handler: WebSocketActionHandler,
        *,
        capability: str | None = None,
        source: str = "oss",
        replace: bool = False,
        error_event: str = "error",
        request_policy: RequestPolicy | None = None,
    ) -> None:
        if not replace and name in self._actions:
            raise ValueError(f"WebSocket action already registered: {name}")
        self._actions[name] = WebSocketActionSpec(
            name=name,
            handler=handler,
            capability=capability,
            source=source,
            error_event=error_event,
            request_policy=request_policy,
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
        *,
        background: bool = False,
    ) -> bool:
        if action == CANCEL_REQUEST:
            request_id = payload.get("request_id")
            if isinstance(request_id, str):
                self.requests.cancel(websocket, user, request_id)
            return True
        spec = self.get(action)
        if spec is None:
            return False
        if spec.capability is not None:
            allowed = False
            if self._authorizer is not None:
                try:
                    allowed = await self._authorizer(spec.capability, websocket, payload, user)
                except Exception:
                    allowed = False
            if not allowed:
                from spectra_sherpa.app.services.ws_handlers import _safe_ws_send_json

                error = {"type": spec.error_event, "detail": "Action capability is unavailable"}
                data = payload.get("payload")
                request_id = payload.get("request_id") or (data.get("request_id") if isinstance(data, dict) else None)
                if isinstance(request_id, str):
                    error["request_id"] = request_id
                await _safe_ws_send_json(websocket, error)
                return True
        if background and spec.request_policy is not None:
            await self.requests.start(spec, websocket, payload, user, rate_limiter)
        else:
            await spec.handler(websocket, payload, user, rate_limiter)
        return True


def build_default_ws_action_registry() -> WebSocketActionRegistry:
    registry = WebSocketActionRegistry()
    register_core_ws_actions(registry)
    registry.set_authorizer(_core_action_authorized)
    return registry


def register_core_ws_actions(registry: WebSocketActionRegistry) -> None:
    from spectra_sherpa.app.services.ws_handlers import handle_llm_chat

    registry.register(
        LLM_CHAT_ACTION,
        handle_llm_chat,
        capability=CHAT_ASSISTANT,
        source="spectra-sherpa",
        request_policy=RequestPolicy(status_event="llm_status"),
    )


async def _core_action_authorized(capability, websocket, payload, user) -> bool:
    from spectra_sherpa.app.core.config import app_config

    return capability == CHAT_ASSISTANT and app_config.to_client_safe()["features"].get(capability) is True
