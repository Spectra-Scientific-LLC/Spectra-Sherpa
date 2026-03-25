"""
WebSocket action handlers.

Each handler is a standalone async function that processes a single WS action.
This keeps ``main.py`` as a thin dispatcher and makes individual handlers
independently testable.

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
from spectra_sherpa.app.services.llm import LLMService
from spectra_sherpa.app.services.llm_rate_limits import allow_llm_request, has_llm_rate_limit_bypass
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


async def _handle_sherpa_access_error(ws: WebSocket, detail: str) -> None:
    await _safe_ws_send_json(ws, {"type": "sherpa_error", "detail": detail})


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


def _should_use_server_chat() -> bool:
    """Return True when LLM chat should be routed to the server engine."""
    from spectra_sherpa.app.core.config import app_config

    return app_config.mode in ("hybrid", "enterprise") or app_config.site_profile == "demo"


def _is_contextual_server_channel(use_server_chat: bool) -> bool:
    """Only the server-backed Sherpa channel is allowed to consume workflow context."""
    return use_server_chat


async def _proxy_server_chat(
    ws: WebSocket,
    message: str,
    conversation_id: str | None,
    metadata: dict | None,
    user: Any,
) -> None:
    """Proxy LLM chat to the server's /sherpa/chat endpoint via SSE.

    Uses ``SherpaAdvisor._stream_sse`` to reuse timeout config, connection
    pooling, and SSE parsing — avoiding the duplicated httpx logic that
    previously lived here.
    """
    from spectra_sherpa.app.services.sherpa_advisor import (
        SherpaAuthorizationError,
        SubscriptionRequiredError,
        get_sherpa_advisor,
    )

    advisor = get_sherpa_advisor()
    if not advisor.is_available:
        await _safe_ws_send_json(ws, {"type": "error", "detail": "Server chat not configured (no deployment key)"})
        return

    workflow_context = metadata.get("workflow_context") if metadata else None
    user_id = user.id if user else None

    body = {
        "message": message,
        "conversation_id": conversation_id,
        "workflow_context": workflow_context,
        "local_user_id": user_id,
        "project_id": metadata.get("project_id") if metadata else None,
    }

    try:
        started = False
        event_stream = advisor._stream_sse("/sherpa/chat", json_body=body)
        try:
            async for event in event_stream:
                etype = event.get("type")
                if etype == "start":
                    started = True
                    if not await _safe_ws_send_json(
                        ws,
                        {"type": "llm_start", "conversation_id": event.get("conversation_id")},
                    ):
                        return
                elif etype == "chunk":
                    if not started:
                        started = True
                        if not await _safe_ws_send_json(
                            ws,
                            {"type": "llm_start", "conversation_id": event.get("conversation_id")},
                        ):
                            return
                    if not await _safe_ws_send_json(
                        ws,
                        {
                            "type": "llm_chunk",
                            "conversation_id": event.get("conversation_id"),
                            "chunk": event.get("text", ""),
                        },
                    ):
                        return
                elif etype == "done":
                    await _safe_ws_send_json(
                        ws,
                        {"type": "llm_done", "conversation_id": event.get("conversation_id")},
                    )
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


async def _local_llm_chat(
    ws: WebSocket,
    message: str,
    conversation_id: str | None,
    metadata: dict | None,
    user: Any,
) -> None:
    """Local LLM chat via BYOK provider (OSS / local mode)."""
    async with async_session() as session:
        service = LLMService(session, user=user)
        try:
            convo_id, stream = await service.stream_chat(
                message=message,
                conversation_id=conversation_id,
                metadata=metadata,
            )
        except ValueError as exc:
            await _safe_ws_send_json(ws, {"type": "error", "detail": str(exc)})
            return
        if not await _safe_ws_send_json(ws, {"type": "llm_start", "conversation_id": convo_id}):
            return
        async for chunk in stream:
            if not await _safe_ws_send_json(ws, {"type": "llm_chunk", "conversation_id": convo_id, "chunk": chunk}):
                return
        await _safe_ws_send_json(ws, {"type": "llm_done", "conversation_id": convo_id})


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
        if not allow_llm_request(rate_limiter, user):
            await _safe_ws_send_json(ws, {"type": "error", "detail": "LLM rate limit exceeded. Try again later."})
            return

        conversation_id = payload.get("conversation_id")
        metadata = payload.get("metadata")
        use_server_chat = _should_use_server_chat()

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
        if _is_contextual_server_channel(use_server_chat) and metadata and metadata.get("workflow_context"):
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

        # Route: server-backed (hybrid/enterprise/demo) vs local BYOK
        if use_server_chat:
            await _proxy_server_chat(ws, message, conversation_id, metadata, user)
        else:
            await _local_llm_chat(ws, message, conversation_id, metadata, user)
    except Exception as exc:
        logger.exception("llm_chat failed: %s", exc)
        await _safe_ws_send_json(ws, {"type": "error", "detail": "LLM request failed. Check server logs for details."})


# ---------------------------------------------------------------------------
# Sherpa Sync / Decide / Chat
# ---------------------------------------------------------------------------


def _advisor_is_available(advisor: Any) -> bool:
    """Handle either a property-style or method-style availability check."""
    available = getattr(advisor, "is_available", False)
    return bool(available() if callable(available) else available)


async def _check_demo_sherpa_limit(ws: WebSocket, user: Any) -> bool:
    """Check demo Sherpa quota *without consuming*.  Returns False (and sends error) if exhausted."""
    from spectra_sherpa.app.core.demo_limits import check_demo_sherpa_available, demo_limit_error_detail

    user_id = getattr(user, "id", None) if user else None
    allowed, remaining = check_demo_sherpa_available(user_id)
    if not allowed:
        detail = demo_limit_error_detail("sherpa", remaining)
        await _safe_ws_send_json(ws, {"type": "sherpa_error", **detail})
        return False
    return True


def _consume_demo_sherpa(user: Any) -> None:
    """Consume one Sherpa interaction quota.  Call only after successful work."""
    from spectra_sherpa.app.core.demo_limits import consume_demo_sherpa

    user_id = getattr(user, "id", None) if user else None
    consume_demo_sherpa(user_id)


async def handle_sherpa_sync(
    ws: WebSocket,
    payload: dict,
    user: Any,
    rate_limiter: RateLimiter,
) -> None:
    from spectra_sherpa.app.services.sherpa_advisor import SherpaAuthorizationError, SubscriptionRequiredError

    try:
        if not await _sherpa_proxy_preamble(ws, user, rate_limiter, permission_name="allow_spectrasherpa_sync"):
            return

        from spectra_sherpa.app.schemas.sherpa import EgressTier, WorkflowStateSync

        # Cloud proxy (hybrid mode → remote SpectraSherpa server)
        from spectra_sherpa.app.services.sherpa_advisor import get_sherpa_advisor

        advisor = get_sherpa_advisor()
        sync_data = dict(payload.get("payload", {}))
        tier = EgressTier(sync_data.pop("tier", "structure"))
        sync_msg = WorkflowStateSync(**sync_data)
        recommendations = await advisor.sync_workflow(sync_msg, tier=tier)
        _consume_demo_sherpa(user)
        logger.info("sherpa_sync (proxy): %d nodes → %d recommendations", len(sync_msg.nodes), len(recommendations))
        await _safe_ws_send_json(
            ws,
            {
                "type": "sherpa_recommendations",
                "payload": [r.model_dump(mode="json") for r in recommendations],
            },
        )
    except SherpaAuthorizationError as exc:
        await _handle_sherpa_access_error(ws, exc.detail)
    except SubscriptionRequiredError as exc:
        await _safe_ws_send_json(ws, {"type": "sherpa_subscription_required", "detail": exc.detail})
    except Exception as exc:
        logger.exception("sherpa_sync failed: %s", exc)
        await _safe_ws_send_json(ws, {"type": "sherpa_error", "detail": "Sherpa sync failed. Check server logs."})


async def handle_sherpa_decide(
    ws: WebSocket,
    payload: dict,
    user: Any,
    rate_limiter: RateLimiter,
) -> None:
    from spectra_sherpa.app.services.sherpa_advisor import SherpaAuthorizationError, SubscriptionRequiredError

    try:
        if not await _sherpa_proxy_preamble(ws, user, rate_limiter):
            return

        from spectra_sherpa.app.schemas.sherpa import UserDecision
        from spectra_sherpa.app.services.sherpa_advisor import get_sherpa_advisor

        advisor = get_sherpa_advisor()
        decision = UserDecision(**payload.get("payload", {}))
        delivered = await advisor.send_decision(decision)
        _consume_demo_sherpa(user)
        await _safe_ws_send_json(
            ws,
            {
                "type": "sherpa_decision_ack",
                "payload": {"delivered": delivered, "suggestion_id": decision.suggestion_id},
            },
        )
    except SherpaAuthorizationError as exc:
        await _handle_sherpa_access_error(ws, exc.detail)
    except SubscriptionRequiredError as exc:
        await _safe_ws_send_json(ws, {"type": "sherpa_subscription_required", "detail": exc.detail})
    except Exception as exc:
        logger.exception("sherpa_decide failed: %s", exc)
        await _safe_ws_send_json(ws, {"type": "sherpa_error", "detail": "Sherpa decision failed. Check server logs."})


async def handle_sherpa_chat(
    ws: WebSocket,
    payload: dict,
    user: Any,
    rate_limiter: RateLimiter,
) -> None:
    from spectra_sherpa.app.services.sherpa_advisor import SherpaAuthorizationError, SubscriptionRequiredError

    try:
        if not await _sherpa_proxy_preamble(ws, user, rate_limiter):
            return

        chat_data = payload.get("payload", {})
        message = chat_data.get("message", "")
        if not message:
            await _safe_ws_send_json(ws, {"type": "sherpa_error", "detail": "Missing message"})
            return

        history = chat_data.get("history", [])

        from spectra_sherpa.app.services.sherpa_advisor import get_sherpa_advisor

        advisor = get_sherpa_advisor()

        workflow_id = chat_data.get("workflow_id")
        workflow_context_raw = await _filter_sherpa_workflow_context(
            user,
            chat_data.get("workflow_context"),
        )

        started = False
        async for chunk in advisor.chat_followup(
            message=message,
            workflow_id=workflow_id,
            history=history,
            workflow_context=workflow_context_raw,
        ):
            if not started:
                if not await _safe_ws_send_json(ws, {"type": "sherpa_chat_start"}):
                    return
                started = True
            if not await _safe_ws_send_json(ws, {"type": "sherpa_chat_chunk", "chunk": chunk}):
                return

        if started:
            _consume_demo_sherpa(user)
            await _safe_ws_send_json(ws, {"type": "sherpa_chat_done"})
        else:
            # Stream ended with no chunks — surface as empty completion
            if await _safe_ws_send_json(ws, {"type": "sherpa_chat_start"}):
                await _safe_ws_send_json(ws, {"type": "sherpa_chat_done"})
    except SherpaAuthorizationError as exc:
        await _handle_sherpa_access_error(ws, exc.detail)
    except SubscriptionRequiredError as exc:
        await _safe_ws_send_json(ws, {"type": "sherpa_subscription_required", "detail": exc.detail})
    except Exception as exc:
        logger.exception("sherpa_chat failed: %s", exc)
        await _safe_ws_send_json(ws, {"type": "sherpa_error", "detail": "Sherpa chat failed. Check server logs."})


# ---------------------------------------------------------------------------
# Sherpa proxy — subscription-gated endpoints
# ---------------------------------------------------------------------------


async def _sherpa_proxy_preamble(
    ws: WebSocket,
    user: Any,
    rate_limiter: RateLimiter,
    *,
    permission_name: str = "allow_llm_chat",
) -> bool:
    """Shared pre-checks for all subscription-gated Sherpa proxy handlers.

    Returns True if the request is allowed to proceed, False otherwise
    (error already sent on the WebSocket).
    """
    if not allow_llm_request(rate_limiter, user):
        await _safe_ws_send_json(ws, {"type": "sherpa_error", "detail": "Sherpa rate limit exceeded. Try again later."})
        return False

    if not has_llm_rate_limit_bypass(user) and not await _check_demo_sherpa_limit(ws, user):
        return False

    from spectra_sherpa.app.services.sherpa_advisor import get_sherpa_advisor

    advisor = get_sherpa_advisor()
    if not _advisor_is_available(advisor):
        await _safe_ws_send_json(
            ws,
            {
                "type": "sherpa_status",
                "payload": {"connected": False, "reason": "not_configured"},
            },
        )
        return False

    async with async_session() as permission_session:
        allowed = await check_egress_permission(
            user,
            permission_name,
            data_type="workflow" if permission_name == "allow_spectrasherpa_sync" else None,
            destination="spectrasherpa" if permission_name == "allow_spectrasherpa_sync" else None,
            session=permission_session,
            skip_global_check=True,
        )
    if not allowed:
        detail = (
            "Sherpa sync not permitted. Enable cloud sync in Settings > Data & Privacy."
            if permission_name == "allow_spectrasherpa_sync"
            else "Sherpa AI features are disabled in user privacy settings."
        )
        await _safe_ws_send_json(ws, {"type": "sherpa_error", "detail": detail})
        return False
    return True


async def _filter_sherpa_workflow_context(user: Any, workflow_context: Any) -> Any:
    """Apply the workflow-context privacy gate for server-backed Sherpa chat."""
    if workflow_context is None:
        return None

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
        return None
    return workflow_context


async def handle_sherpa_identify_peaks(
    ws: WebSocket,
    payload: dict,
    user: Any,
    rate_limiter: RateLimiter,
) -> None:
    from spectra_sherpa.app.services.sherpa_advisor import SherpaAuthorizationError, SubscriptionRequiredError

    try:
        if not await _sherpa_proxy_preamble(ws, user, rate_limiter):
            return

        from spectra_sherpa.app.services.sherpa_advisor import get_sherpa_advisor

        advisor = get_sherpa_advisor()
        data = payload.get("payload", {})
        result = await advisor.identify_peaks(
            wavenumbers=data.get("wavenumbers", data.get("wavenumber", [])),
            absorbance=data.get("absorbance", []),
        )
        if "error" in result:
            await _safe_ws_send_json(ws, {"type": "sherpa_peaks_error", "detail": result["error"]})
        else:
            _consume_demo_sherpa(user)
            await _safe_ws_send_json(ws, {"type": "sherpa_peaks_result", **result})
    except SherpaAuthorizationError as exc:
        await _handle_sherpa_access_error(ws, exc.detail)
    except SubscriptionRequiredError as exc:
        await _safe_ws_send_json(ws, {"type": "sherpa_subscription_required", "detail": exc.detail})
    except Exception as exc:
        logger.exception("sherpa_identify_peaks failed: %s", exc)
        await _safe_ws_send_json(ws, {"type": "sherpa_peaks_error", "detail": "Peak identification failed."})


async def handle_sherpa_generate_code(
    ws: WebSocket,
    payload: dict,
    user: Any,
    rate_limiter: RateLimiter,
) -> None:
    from spectra_sherpa.app.services.sherpa_advisor import SherpaAuthorizationError, SubscriptionRequiredError

    try:
        if not await _sherpa_proxy_preamble(ws, user, rate_limiter):
            return

        from spectra_sherpa.app.services.sherpa_advisor import get_sherpa_advisor

        advisor = get_sherpa_advisor()
        data = payload.get("payload", {})
        result = await advisor.generate_code(
            task_description=data.get("task_description", ""),
            context=data.get("context"),
        )
        if "error" in result:
            await _safe_ws_send_json(ws, {"type": "sherpa_code_error", "detail": result["error"]})
        else:
            _consume_demo_sherpa(user)
            await _safe_ws_send_json(ws, {"type": "sherpa_code_result", **result})
    except SherpaAuthorizationError as exc:
        await _handle_sherpa_access_error(ws, exc.detail)
    except SubscriptionRequiredError as exc:
        await _safe_ws_send_json(ws, {"type": "sherpa_subscription_required", "detail": exc.detail})
    except Exception as exc:
        logger.exception("sherpa_generate_code failed: %s", exc)
        await _safe_ws_send_json(ws, {"type": "sherpa_code_error", "detail": "Code generation failed."})


async def handle_sherpa_write_report(
    ws: WebSocket,
    payload: dict,
    user: Any,
    rate_limiter: RateLimiter,
) -> None:
    from spectra_sherpa.app.services.sherpa_advisor import SherpaAuthorizationError, SubscriptionRequiredError

    try:
        if not await _sherpa_proxy_preamble(ws, user, rate_limiter):
            return

        from spectra_sherpa.app.services.sherpa_advisor import get_sherpa_advisor

        advisor = get_sherpa_advisor()
        data = payload.get("payload", {})
        result = await advisor.write_report(experiment=data.get("experiment", {}))
        if "error" in result:
            await _safe_ws_send_json(ws, {"type": "sherpa_report_error", "detail": result["error"]})
        else:
            _consume_demo_sherpa(user)
            await _safe_ws_send_json(ws, {"type": "sherpa_report_result", **result})
    except SherpaAuthorizationError as exc:
        await _handle_sherpa_access_error(ws, exc.detail)
    except SubscriptionRequiredError as exc:
        await _safe_ws_send_json(ws, {"type": "sherpa_subscription_required", "detail": exc.detail})
    except Exception as exc:
        logger.exception("sherpa_write_report failed: %s", exc)
        await _safe_ws_send_json(ws, {"type": "sherpa_report_error", "detail": "Report generation failed."})


async def handle_sherpa_data_story(
    ws: WebSocket,
    payload: dict,
    user: Any,
    rate_limiter: RateLimiter,
) -> None:
    from spectra_sherpa.app.services.sherpa_advisor import SherpaAuthorizationError, SubscriptionRequiredError

    try:
        if not await _sherpa_proxy_preamble(ws, user, rate_limiter):
            return

        from spectra_sherpa.app.services.sherpa_advisor import get_sherpa_advisor

        advisor = get_sherpa_advisor()
        data = payload.get("payload", {})
        result = await advisor.generate_data_story(
            dataset_info=data.get("dataset_info", {}),
            additional_context=data.get("additional_context"),
        )
        _consume_demo_sherpa(user)
        await _safe_ws_send_json(ws, {"type": "sherpa_data_story_result", **result})
    except SherpaAuthorizationError as exc:
        await _handle_sherpa_access_error(ws, exc.detail)
    except SubscriptionRequiredError as exc:
        await _safe_ws_send_json(ws, {"type": "sherpa_subscription_required", "detail": exc.detail})
    except Exception as exc:
        logger.exception("sherpa_data_story failed: %s", exc)
        await _safe_ws_send_json(ws, {"type": "sherpa_data_story_error", "detail": "Data story generation failed."})


async def handle_sherpa_chat_with_tools(
    ws: WebSocket,
    payload: dict,
    user: Any,
    rate_limiter: RateLimiter,
) -> None:
    from spectra_sherpa.app.services.sherpa_advisor import (
        SherpaAuthorizationError,
        SubscriptionRequiredError,
        get_sherpa_advisor,
    )

    try:
        if not await _sherpa_proxy_preamble(ws, user, rate_limiter):
            return

        advisor = get_sherpa_advisor()
        data = payload.get("payload", {})
        message = data.get("message", "")
        if not message:
            await _safe_ws_send_json(ws, {"type": "sherpa_error", "detail": "Missing message"})
            return

        history = data.get("history", [])
        workflow_context = await _filter_sherpa_workflow_context(
            user,
            data.get("workflow_context", data.get("context")),
        )

        started = False
        event_stream = advisor.chat_with_tools(
            message=message,
            history=history,
            workflow_context=workflow_context,
        )
        try:
            async for event in event_stream:
                event_type = event.get("type", "chunk")
                if not started and event_type in ("chunk", "tool_start"):
                    if not await _safe_ws_send_json(ws, {"type": "sherpa_chat_start"}):
                        return
                    started = True
                if event_type == "chunk":
                    chunk_text = event.get("text", event.get("content", ""))
                    if not await _safe_ws_send_json(ws, {"type": "sherpa_chat_chunk", "chunk": chunk_text}):
                        return
                elif event_type == "tool_start":
                    if not await _safe_ws_send_json(
                        ws,
                        {
                            "type": "sherpa_tool_start",
                            "tool_name": event.get("tool", event.get("tool_name", "unknown")),
                            "round": event.get("round"),
                            "arguments": event.get("arguments"),
                        },
                    ):
                        return
                elif event_type == "tool_result":
                    if not await _safe_ws_send_json(
                        ws,
                        {
                            "type": "sherpa_tool_result",
                            "tool_name": event.get("tool", event.get("tool_name", "unknown")),
                            "success": event.get("success"),
                            "summary": event.get("summary"),
                        },
                    ):
                        return
                elif event_type == "done":
                    break
                elif event_type == "error":
                    await _safe_ws_send_json(
                        ws,
                        {"type": "sherpa_error", "detail": event.get("content", event.get("text", ""))},
                    )
                    return
        finally:
            aclose = getattr(event_stream, "aclose", None)
            if callable(aclose):
                await aclose()

        if started:
            _consume_demo_sherpa(user)
        await _safe_ws_send_json(ws, {"type": "sherpa_chat_done"})
    except SherpaAuthorizationError as exc:
        await _handle_sherpa_access_error(ws, exc.detail)
    except SubscriptionRequiredError as exc:
        await _safe_ws_send_json(ws, {"type": "sherpa_subscription_required", "detail": exc.detail})
    except Exception as exc:
        logger.exception("sherpa_chat_with_tools failed: %s", exc)
        await _safe_ws_send_json(ws, {"type": "sherpa_error", "detail": "Chat with tools failed."})
