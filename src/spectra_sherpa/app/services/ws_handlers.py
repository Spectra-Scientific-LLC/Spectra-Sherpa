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

from spectra_sherpa.app.core.security import check_egress_permission
from spectra_sherpa.app.db.session import async_session
from spectra_sherpa.app.services.llm import LLMService
from spectra_sherpa.app.services.rate_limiter import RateLimiter
from spectra_sherpa.app.services.websocket_manager import ws_manager

logger = logging.getLogger(__name__)


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
        await ws.send_json({"type": "error", "detail": "Missing or unauthorized channel"})
        return
    await ws_manager.subscribe(ws, channel)
    await ws.send_json({"type": "subscribed", "channel": channel})


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
        await ws.send_json({"type": "error", "detail": "Missing or unauthorized channel"})
        return
    await ws_manager.unsubscribe(ws, channel)
    await ws.send_json({"type": "unsubscribed", "channel": channel})


# ---------------------------------------------------------------------------
# LLM Chat
# ---------------------------------------------------------------------------


async def handle_llm_chat(
    ws: WebSocket,
    payload: dict,
    user: Any,
    rate_limiter: RateLimiter,
) -> None:
    try:
        message = payload.get("message") or ""
        if not message:
            await ws.send_json({"type": "error", "detail": "Missing message"})
            return

        # Per-user permission check (skip global egress flag — BYOK is user-initiated consent)
        async with async_session() as permission_session:
            allowed = await check_egress_permission(
                user,
                "allow_llm_context",
                data_type="metadata",
                destination="llm_context",
                session=permission_session,
                skip_global_check=True,
            )
        if not allowed:
            await ws.send_json({"type": "error", "detail": "LLM access is disabled for this user"})
            return

        # Rate limit
        user_key = f"user_{user.id}" if user and user.id else "anonymous"
        if not rate_limiter.allow(user_key):
            await ws.send_json({"type": "error", "detail": "LLM rate limit exceeded. Try again later."})
            return

        conversation_id = payload.get("conversation_id")
        metadata = payload.get("metadata")

        async with async_session() as session:
            service = LLMService(session, user=user)

            try:
                convo_id, stream = await service.stream_chat(
                    message=message,
                    conversation_id=conversation_id,
                    metadata=metadata,
                )
            except ValueError as exc:
                await ws.send_json({"type": "error", "detail": str(exc)})
                return
            await ws.send_json({"type": "llm_start", "conversation_id": convo_id})
            async for chunk in stream:
                await ws.send_json({"type": "llm_chunk", "conversation_id": convo_id, "chunk": chunk})
            await ws.send_json({"type": "llm_done", "conversation_id": convo_id})
    except Exception as exc:
        logger.exception("llm_chat failed: %s", exc)
        await ws.send_json({"type": "error", "detail": "LLM request failed. Check server logs for details."})


# ---------------------------------------------------------------------------
# Sherpa Sync / Decide / Chat
# ---------------------------------------------------------------------------


async def _check_demo_sherpa_limit(ws: WebSocket, user: Any) -> bool:
    """Check demo Sherpa interaction quota. Returns False (and sends error) if exhausted."""
    from spectra_sherpa.app.core.demo_limits import check_demo_sherpa, demo_limit_error_detail

    user_id = getattr(user, "id", None) if user else None
    allowed, remaining = check_demo_sherpa(user_id)
    if not allowed:
        detail = demo_limit_error_detail("sherpa", remaining)
        await ws.send_json({"type": "sherpa_error", **detail})
        return False
    return True


async def handle_sherpa_sync(
    ws: WebSocket,
    payload: dict,
    user: Any,
    rate_limiter: RateLimiter,
) -> None:
    try:
        if not await _check_demo_sherpa_limit(ws, user):
            return

        from spectra_sherpa.app.schemas.sherpa import EgressTier, WorkflowStateSync

        # Cloud proxy (hybrid mode → remote SpectraSherpa server)
        from spectra_sherpa.app.services.sherpa_advisor import get_sherpa_advisor

        advisor = get_sherpa_advisor()
        if not advisor.is_available:
            await ws.send_json({"type": "sherpa_status", "payload": {"connected": False, "reason": "not_configured"}})
            return

        # Cloud proxy sends workflow data to SpectraSherpa — gate by allow_spectrasherpa_sync
        async with async_session() as permission_session:
            allowed = await check_egress_permission(
                user,
                "allow_spectrasherpa_sync",
                data_type="workflow",
                destination="spectrasherpa",
                session=permission_session,
            )
        if not allowed:
            await ws.send_json(
                {
                    "type": "sherpa_error",
                    "detail": "Sherpa sync not permitted. Enable cloud sync in Settings > Data & Privacy.",
                }
            )
            return

        sync_data = dict(payload.get("payload", {}))
        tier = EgressTier(sync_data.pop("tier", "structure"))
        sync_msg = WorkflowStateSync(**sync_data)
        recommendations = await advisor.sync_workflow(sync_msg, tier=tier)
        logger.info("sherpa_sync (proxy): %d nodes → %d recommendations", len(sync_msg.nodes), len(recommendations))
        await ws.send_json(
            {
                "type": "sherpa_recommendations",
                "payload": [r.model_dump(mode="json") for r in recommendations],
            }
        )
    except Exception as exc:
        logger.exception("sherpa_sync failed: %s", exc)
        await ws.send_json({"type": "sherpa_error", "detail": "Sherpa sync failed. Check server logs for details."})


async def handle_sherpa_decide(
    ws: WebSocket,
    payload: dict,
    user: Any,
    rate_limiter: RateLimiter,
) -> None:
    if not await _check_demo_sherpa_limit(ws, user):
        return

    from spectra_sherpa.app.schemas.sherpa import UserDecision
    from spectra_sherpa.app.services.sherpa_advisor import get_sherpa_advisor

    advisor = get_sherpa_advisor()
    try:
        decision = UserDecision(**payload.get("payload", {}))
        delivered = await advisor.send_decision(decision)
        await ws.send_json(
            {
                "type": "sherpa_decision_ack",
                "payload": {"delivered": delivered, "suggestion_id": decision.suggestion_id},
            }
        )
    except Exception as exc:
        logger.exception("sherpa_decide failed: %s", exc)
        await ws.send_json({"type": "sherpa_error", "detail": "Sherpa decision failed. Check server logs for details."})


async def handle_sherpa_chat(
    ws: WebSocket,
    payload: dict,
    user: Any,
    rate_limiter: RateLimiter,
) -> None:
    try:
        if not await _check_demo_sherpa_limit(ws, user):
            return

        chat_data = payload.get("payload", {})
        message = chat_data.get("message", "")
        history = chat_data.get("history", [])

        # Cloud proxy
        from spectra_sherpa.app.services.sherpa_advisor import get_sherpa_advisor

        advisor = get_sherpa_advisor()
        if not advisor.is_available:
            await ws.send_json({"type": "sherpa_status", "payload": {"connected": False, "reason": "not_configured"}})
            return

        # Cloud proxy sends chat to SpectraSherpa — gate by allow_spectrasherpa_sync
        async with async_session() as permission_session:
            allowed = await check_egress_permission(
                user,
                "allow_spectrasherpa_sync",
                data_type="chat",
                destination="spectrasherpa",
                session=permission_session,
            )
        if not allowed:
            await ws.send_json({"type": "sherpa_error", "detail": "Sherpa chat not permitted for this user"})
            return

        workflow_id = chat_data.get("workflow_id")
        # Forward workflow_context so server-side engine has graph for follow-up
        workflow_context_raw = chat_data.get("workflow_context")

        await ws.send_json({"type": "sherpa_chat_start"})
        async for chunk in advisor.chat_followup(
            message=message,
            workflow_id=workflow_id,
            history=history,
            workflow_context=workflow_context_raw,
        ):
            await ws.send_json({"type": "sherpa_chat_chunk", "chunk": chunk})
        await ws.send_json({"type": "sherpa_chat_done"})
    except Exception as exc:
        logger.exception("sherpa_chat failed: %s", exc)
        await ws.send_json({"type": "sherpa_error", "detail": "Sherpa chat failed. Check server logs for details."})


# ---------------------------------------------------------------------------
# Sherpa proxy — subscription-gated endpoints
# ---------------------------------------------------------------------------


async def _sherpa_proxy_preamble(ws: WebSocket, user: Any) -> bool:
    """Shared pre-checks for all subscription-gated Sherpa proxy handlers.

    Returns True if the request is allowed to proceed, False otherwise
    (error already sent on the WebSocket).
    """
    if not await _check_demo_sherpa_limit(ws, user):
        return False

    from spectra_sherpa.app.services.sherpa_advisor import get_sherpa_advisor

    advisor = get_sherpa_advisor()
    if not advisor.is_available:
        await ws.send_json(
            {
                "type": "sherpa_status",
                "payload": {"connected": False, "reason": "not_configured"},
            }
        )
        return False

    async with async_session() as permission_session:
        allowed = await check_egress_permission(
            user,
            "allow_spectrasherpa_sync",
            data_type="analysis",
            destination="spectrasherpa",
            session=permission_session,
        )
    if not allowed:
        await ws.send_json(
            {
                "type": "sherpa_error",
                "detail": "Sherpa features not permitted. Enable cloud sync in Settings > Data & Privacy.",
            }
        )
        return False
    return True


async def handle_sherpa_identify_peaks(
    ws: WebSocket,
    payload: dict,
    user: Any,
    rate_limiter: RateLimiter,
) -> None:
    try:
        if not await _sherpa_proxy_preamble(ws, user):
            return

        from spectra_sherpa.app.services.sherpa_advisor import (
            SubscriptionRequiredError,
            get_sherpa_advisor,
        )

        advisor = get_sherpa_advisor()
        data = payload.get("payload", {})
        result = await advisor.identify_peaks(
            wavenumbers=data.get("wavenumbers", data.get("wavenumber", [])),
            absorbance=data.get("absorbance", []),
        )
        if "error" in result:
            await ws.send_json({"type": "sherpa_peaks_error", "detail": result["error"]})
        else:
            await ws.send_json({"type": "sherpa_peaks_result", **result})
    except SubscriptionRequiredError as exc:
        await ws.send_json({"type": "sherpa_subscription_required", "detail": exc.detail})
    except Exception as exc:
        logger.exception("sherpa_identify_peaks failed: %s", exc)
        await ws.send_json({"type": "sherpa_peaks_error", "detail": "Peak identification failed."})


async def handle_sherpa_generate_code(
    ws: WebSocket,
    payload: dict,
    user: Any,
    rate_limiter: RateLimiter,
) -> None:
    try:
        if not await _sherpa_proxy_preamble(ws, user):
            return

        from spectra_sherpa.app.services.sherpa_advisor import (
            SubscriptionRequiredError,
            get_sherpa_advisor,
        )

        advisor = get_sherpa_advisor()
        data = payload.get("payload", {})
        result = await advisor.generate_code(
            task_description=data.get("task_description", ""),
            context=data.get("context"),
        )
        if "error" in result:
            await ws.send_json({"type": "sherpa_code_error", "detail": result["error"]})
        else:
            await ws.send_json({"type": "sherpa_code_result", **result})
    except SubscriptionRequiredError as exc:
        await ws.send_json({"type": "sherpa_subscription_required", "detail": exc.detail})
    except Exception as exc:
        logger.exception("sherpa_generate_code failed: %s", exc)
        await ws.send_json({"type": "sherpa_code_error", "detail": "Code generation failed."})


async def handle_sherpa_write_report(
    ws: WebSocket,
    payload: dict,
    user: Any,
    rate_limiter: RateLimiter,
) -> None:
    try:
        if not await _sherpa_proxy_preamble(ws, user):
            return

        from spectra_sherpa.app.services.sherpa_advisor import (
            SubscriptionRequiredError,
            get_sherpa_advisor,
        )

        advisor = get_sherpa_advisor()
        data = payload.get("payload", {})
        result = await advisor.write_report(experiment=data.get("experiment", {}))
        if "error" in result:
            await ws.send_json({"type": "sherpa_report_error", "detail": result["error"]})
        else:
            await ws.send_json({"type": "sherpa_report_result", **result})
    except SubscriptionRequiredError as exc:
        await ws.send_json({"type": "sherpa_subscription_required", "detail": exc.detail})
    except Exception as exc:
        logger.exception("sherpa_write_report failed: %s", exc)
        await ws.send_json({"type": "sherpa_report_error", "detail": "Report generation failed."})


async def handle_llm_chat_with_tools(
    ws: WebSocket,
    payload: dict,
    user: Any,
    rate_limiter: RateLimiter,
    *,
    event_prefix: str = "llm",
) -> None:
    """LLM chat with local tool-calling support for plugin generation.

    *event_prefix* controls the WS event type namespace so different
    frontend stores can listen independently (e.g. ``"llm"`` → ``llm_start``,
    ``"import"`` → ``import_start``).
    """
    try:
        error_type = f"{event_prefix}_error"

        message = payload.get("message") or ""
        if not message:
            await ws.send_json({"type": error_type, "detail": "Missing message"})
            return

        # Per-user permission check (skip global egress flag — BYOK is user-initiated consent)
        async with async_session() as permission_session:
            allowed = await check_egress_permission(
                user,
                "allow_llm_context",
                data_type="metadata",
                destination="llm_context",
                session=permission_session,
                skip_global_check=True,
            )
        if not allowed:
            await ws.send_json({"type": error_type, "detail": "LLM access is disabled for this user"})
            return

        # Rate limit
        user_key = f"user_{user.id}" if user and user.id else "anonymous"
        if not rate_limiter.allow(user_key):
            await ws.send_json({"type": error_type, "detail": "LLM rate limit exceeded. Try again later."})
            return

        conversation_id = payload.get("conversation_id")
        metadata = payload.get("metadata")

        async with async_session() as session:
            service = LLMService(session, user=user)

            try:
                convo_id, event_stream = await service.stream_chat_with_tools(
                    message=message,
                    conversation_id=conversation_id,
                    metadata=metadata,
                )
            except ValueError as exc:
                await ws.send_json({"type": error_type, "detail": str(exc)})
                return

            await ws.send_json({"type": f"{event_prefix}_start", "conversation_id": convo_id})

            async for event in event_stream:
                event_type = event.get("type", "")
                if event_type == "chunk":
                    await ws.send_json(
                        {
                            "type": f"{event_prefix}_chunk",
                            "conversation_id": convo_id,
                            "chunk": event.get("text", ""),
                        }
                    )
                elif event_type == "tool_start":
                    await ws.send_json(
                        {
                            "type": f"{event_prefix}_tool_start",
                            "tool_name": event.get("tool_name", ""),
                            "arguments": event.get("arguments"),
                        }
                    )
                elif event_type == "tool_result":
                    await ws.send_json(
                        {
                            "type": f"{event_prefix}_tool_result",
                            "tool_name": event.get("tool_name", ""),
                            "success": event.get("success", False),
                            "summary": event.get("summary", ""),
                        }
                    )

            await ws.send_json({"type": f"{event_prefix}_done", "conversation_id": convo_id})
    except Exception as exc:
        logger.exception("llm_chat_with_tools failed: %s", exc)
        await ws.send_json(
            {"type": f"{event_prefix}_error", "detail": "LLM request failed. Check server logs for details."}
        )


async def handle_sherpa_chat_with_tools(
    ws: WebSocket,
    payload: dict,
    user: Any,
    rate_limiter: RateLimiter,
) -> None:
    try:
        if not await _sherpa_proxy_preamble(ws, user):
            return

        from spectra_sherpa.app.services.sherpa_advisor import (
            SubscriptionRequiredError,
            get_sherpa_advisor,
        )

        advisor = get_sherpa_advisor()
        data = payload.get("payload", {})
        message = data.get("message", "")
        history = data.get("history", [])
        workflow_context = data.get("workflow_context", data.get("context"))

        await ws.send_json({"type": "sherpa_chat_start"})
        async for event in advisor.chat_with_tools(
            message=message,
            history=history,
            workflow_context=workflow_context,
        ):
            event_type = event.get("type", "chunk")
            if event_type == "chunk":
                # SSE contract uses "text"; fall back to "content" for compat
                chunk_text = event.get("text", event.get("content", ""))
                await ws.send_json({"type": "sherpa_chat_chunk", "chunk": chunk_text})
            elif event_type == "tool_start":
                # Flatten: surface tool_name at top level for frontend
                await ws.send_json(
                    {
                        "type": "sherpa_tool_start",
                        "tool_name": event.get("tool", event.get("tool_name", "unknown")),
                        "round": event.get("round"),
                        "arguments": event.get("arguments"),
                    }
                )
            elif event_type == "tool_result":
                await ws.send_json(
                    {
                        "type": "sherpa_tool_result",
                        "tool_name": event.get("tool", event.get("tool_name", "unknown")),
                        "success": event.get("success"),
                        "summary": event.get("summary"),
                    }
                )
            elif event_type == "error":
                await ws.send_json({"type": "sherpa_error", "detail": event.get("content", event.get("text", ""))})
        await ws.send_json({"type": "sherpa_chat_done"})
    except SubscriptionRequiredError as exc:
        await ws.send_json({"type": "sherpa_subscription_required", "detail": exc.detail})
    except Exception as exc:
        logger.exception("sherpa_chat_with_tools failed: %s", exc)
        await ws.send_json({"type": "sherpa_error", "detail": "Chat with tools failed."})
