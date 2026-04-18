"""
WebSocket action handlers (OSS core).

Each handler is a standalone async function that processes a single WS action.
This keeps ``main.py`` as a thin dispatcher and makes individual handlers
independently testable.

Premium Sherpa handlers (sync, decide, chat, peaks, code, report, data story,
tools) live in ``spectrasherpa_server.ws_handlers`` and are registered by
the server's ``extra_ws_action_registrars`` hook.

All handlers follow the same signature::

    async def handle_<action>(
        ws: WebSocket,
        payload: dict,
        user: Any,
        rate_limiter: RateLimiter,
    ) -> None

Handlers send responses directly on the WebSocket. They never raise — all
exceptions are caught and turned into error messages.
"""

from __future__ import annotations

import logging
from typing import Any, Callable

from fastapi import WebSocket
from starlette.websockets import WebSocketState

from spectra_sherpa.app.core.security import check_egress_permission
from spectra_sherpa.app.db.session import async_session
from spectra_sherpa.app.services.rate_limiter import RateLimiter
from spectra_sherpa.app.services.websocket_manager import ws_manager

logger = logging.getLogger(__name__)


def _ws_is_connected(ws: WebSocket) -> bool:
    state = getattr(ws, "client_state", None)
    return state is None or state == WebSocketState.CONNECTED


async def _safe_ws_send_json(ws: WebSocket, payload: dict[str, Any]) -> bool:
    if not _ws_is_connected(ws):
        return False
    try:
        await ws.send_json(payload)
        return True
    except Exception:
        logger.debug("WebSocket send failed; client likely disconnected", exc_info=True)
        return False


# ---------------------------------------------------------------------------
# Subscribe / Unsubscribe
# ---------------------------------------------------------------------------


async def handle_subscribe(
    ws: WebSocket,
    payload: dict,
    user: Any,
    rate_limiter: RateLimiter,
    *,
    resolve_channel: Callable[[str | None], str | None],
) -> None:
    channel = resolve_channel(payload.get("channel"))
    if not channel:
        await _safe_ws_send_json(ws, {"type": "error", "detail": "Missing or unauthorized channel"})
        return
    await ws_manager.subscribe(ws, channel)
    await _safe_ws_send_json(ws, {"type": "subscribed", "channel": channel})


async def handle_unsubscribe(
    ws: WebSocket,
    payload: dict,
    user: Any,
    rate_limiter: RateLimiter,
    *,
    resolve_channel: Callable[[str | None], str | None],
) -> None:
    channel = resolve_channel(payload.get("channel"))
    if not channel:
        await _safe_ws_send_json(ws, {"type": "error", "detail": "Missing or unauthorized channel"})
        return
    await ws_manager.unsubscribe(ws, channel)
    await _safe_ws_send_json(ws, {"type": "unsubscribed", "channel": channel})


# ---------------------------------------------------------------------------
# LLM Chat
# ---------------------------------------------------------------------------


async def _proxy_server_chat(
    ws: WebSocket,
    message: str,
    conversation_id: str | None,
    metadata: dict | None,
    user: Any,
) -> None:
    """Proxy LLM chat through the AI provider's ``stream_llm_chat`` method.

    The concrete provider handles transport details (HTTP/SSE for deployment-key
    proxies, in-process engine calls for server mode).  This handler maps
    provider events to WebSocket messages.
    """
    from spectra_sherpa.app.contracts.ai_provider_errors import (
        SherpaAuthorizationError,
        SubscriptionRequiredError,
    )
    from spectra_sherpa.app.contracts.ai_provider_registry import get_sherpa_advisor

    advisor = get_sherpa_advisor()
    if not advisor.is_available:
        await _safe_ws_send_json(ws, {"type": "error", "detail": "Server chat not configured (no deployment key)"})
        return

    workflow_context = metadata.get("workflow_context") if metadata else None
    user_id = user.id if user else None

    try:
        started = False
        active_conversation_id = conversation_id
        event_stream = advisor.stream_llm_chat(
            message=message,
            conversation_id=conversation_id,
            workflow_context=workflow_context,
            local_user_id=user_id,
            project_id=metadata.get("project_id") if metadata else None,
        )
        try:
            async for event in event_stream:
                etype = event.get("type")
                event_conversation_id = event.get("conversation_id")
                if isinstance(event_conversation_id, str) and event_conversation_id.strip():
                    active_conversation_id = event_conversation_id
                if etype == "start":
                    started = True
                    if not await _safe_ws_send_json(
                        ws,
                        {"type": "llm_start", "conversation_id": active_conversation_id},
                    ):
                        return
                elif etype == "chunk":
                    if not started:
                        started = True
                        if not await _safe_ws_send_json(
                            ws,
                            {"type": "llm_start", "conversation_id": active_conversation_id},
                        ):
                            return
                    chunk_text = str(event.get("text", ""))
                    if not await _safe_ws_send_json(
                        ws,
                        {
                            "type": "llm_chunk",
                            "conversation_id": active_conversation_id,
                            "chunk": chunk_text,
                        },
                    ):
                        return
                elif etype == "done":
                    await _safe_ws_send_json(
                        ws,
                        {"type": "llm_done", "conversation_id": active_conversation_id},
                    )
                    return
                elif etype == "warning":
                    if not await _safe_ws_send_json(
                        ws,
                        {
                            "type": "llm_warning",
                            "conversation_id": active_conversation_id,
                            "detail": event.get("message", event.get("detail", "")),
                            "code": event.get("code"),
                        },
                    ):
                        return
                elif etype == "error":
                    await _safe_ws_send_json(ws, {"type": "error", "detail": event.get("detail", "")})
                    return
        finally:
            aclose = getattr(event_stream, "aclose", None)
            if callable(aclose):
                await aclose()
    except SherpaAuthorizationError as exc:
        logger.warning("Server chat authorization failed: %s", exc.detail)
        await _safe_ws_send_json(ws, {"type": "error", "detail": f"Server chat authorization failed: {exc.detail}"})
    except SubscriptionRequiredError as exc:
        await _safe_ws_send_json(ws, {"type": "error", "detail": f"Server chat subscription required: {exc.detail}"})
    except Exception as exc:
        logger.exception("Server chat proxy failed: %s", exc)
        await _safe_ws_send_json(ws, {"type": "error", "detail": f"Server chat failed: {exc}"})


def _allow_llm_request(limiter: RateLimiter, user: Any) -> bool:
    """Check quota consumption for a user, honoring admin bypass."""
    if user and getattr(user, "is_superuser", False):
        return True
    key = f"user_{user.id}" if user and getattr(user, "id", None) else "anonymous"
    return limiter.allow(key)


async def handle_llm_chat(
    ws: WebSocket,
    payload: dict,
    user: Any,
    rate_limiter: RateLimiter,
) -> None:
    try:
        message = payload.get("message") or ""
        if not message:
            await _safe_ws_send_json(ws, {"type": "error", "detail": "Missing message"})
            return

        # Rate limit
        if not _allow_llm_request(rate_limiter, user):
            await _safe_ws_send_json(ws, {"type": "error", "detail": "LLM rate limit exceeded. Try again later."})
            return

        conversation_id = payload.get("conversation_id")
        metadata = payload.get("metadata")

        async with async_session() as permission_session:
            if not await check_egress_permission(
                user,
                "allow_llm_chat",
                session=permission_session,
                skip_global_check=True,
            ):
                await _safe_ws_send_json(
                    ws,
                    {"type": "error", "detail": "AI chat is disabled in user privacy settings."},
                )
                return

        # Only the server-backed Sherpa channel consumes workflow context.
        if metadata and metadata.get("workflow_context"):
            async with async_session() as permission_session:
                include_context = await check_egress_permission(
                    user,
                    "allow_llm_context",
                    data_type="metadata",
                    destination="llm_context",
                    session=permission_session,
                    skip_global_check=True,
                )
            if not include_context:
                metadata = {k: v for k, v in metadata.items() if k != "workflow_context"}

        # All chat routes through the AI provider (server-injected or disabled default).
        await _proxy_server_chat(ws, message, conversation_id, metadata, user)
    except Exception as exc:
        logger.exception("llm_chat failed: %s", exc)
        await _safe_ws_send_json(ws, {"type": "error", "detail": "LLM request failed. Check server logs for details."})
