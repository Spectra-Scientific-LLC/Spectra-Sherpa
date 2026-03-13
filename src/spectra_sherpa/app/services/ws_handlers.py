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
    """Proxy LLM chat to the server's /sherpa/chat endpoint via SSE."""
    import json

    workflow_context = metadata.get("workflow_context") if metadata else None
    user_id = user.id if user else None

    # ── Remote proxy path (httpx SSE to remote spectra-server) ──
    import httpx

    from spectra_sherpa.app.services.spectrasherpa import spectrasherpa_config

    base_url = spectrasherpa_config.api_base_url.rstrip("/")
    if not base_url.endswith("/api/v1"):
        base_url = f"{base_url}/api/v1"
    api_key = spectrasherpa_config.api_key

    if not api_key:
        await ws.send_json({"type": "error", "detail": "Server chat not configured (no deployment key)"})
        return

    body = {
        "message": message,
        "conversation_id": conversation_id,
        "workflow_context": workflow_context,
        "local_user_id": user_id,
        "project_id": metadata.get("project_id") if metadata else None,
    }

    try:
        async with httpx.AsyncClient(timeout=120.0) as client:
            async with client.stream(
                "POST",
                f"{base_url}/sherpa/chat",
                json=body,
                headers={"X-Deployment-Key": api_key},
            ) as response:
                if response.status_code != 200:
                    detail = f"Server returned {response.status_code}"
                    await ws.send_json({"type": "error", "detail": detail})
                    return
                async for line in response.aiter_lines():
                    if not line.startswith("data: "):
                        continue
                    try:
                        event = json.loads(line[6:])
                    except json.JSONDecodeError:
                        continue
                    etype = event.get("type")
                    if etype == "start":
                        await ws.send_json({"type": "llm_start", "conversation_id": event.get("conversation_id")})
                    elif etype == "chunk":
                        await ws.send_json(
                            {
                                "type": "llm_chunk",
                                "conversation_id": event.get("conversation_id"),
                                "chunk": event.get("text", ""),
                            }
                        )
                    elif etype == "done":
                        await ws.send_json({"type": "llm_done", "conversation_id": event.get("conversation_id")})
                    elif etype == "error":
                        await ws.send_json({"type": "error", "detail": event.get("detail", "")})
    except httpx.ConnectError:
        await ws.send_json({"type": "error", "detail": "Cannot connect to SpectraSherpa server"})
    except httpx.TimeoutException:
        await ws.send_json({"type": "error", "detail": "Server chat request timed out"})
    except Exception as exc:
        logger.exception("Server chat proxy failed: %s", exc)
        await ws.send_json({"type": "error", "detail": "Server chat proxy failed"})


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
            await ws.send_json({"type": "error", "detail": str(exc)})
            return
        await ws.send_json({"type": "llm_start", "conversation_id": convo_id})
        async for chunk in stream:
            await ws.send_json({"type": "llm_chunk", "conversation_id": convo_id, "chunk": chunk})
        await ws.send_json({"type": "llm_done", "conversation_id": convo_id})


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

        # Rate limit
        user_key = f"user_{user.id}" if user and user.id else "anonymous"
        if not rate_limiter.allow(user_key):
            await ws.send_json({"type": "error", "detail": "LLM rate limit exceeded. Try again later."})
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
                await ws.send_json({"type": "error", "detail": "AI chat is disabled in user privacy settings."})
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
        if not await _sherpa_proxy_preamble(ws, user):
            return

        chat_data = payload.get("payload", {})
        message = chat_data.get("message", "")
        history = chat_data.get("history", [])

        from spectra_sherpa.app.services.sherpa_advisor import get_sherpa_advisor

        advisor = get_sherpa_advisor()

        workflow_id = chat_data.get("workflow_id")
        # Forward workflow_context so server-side engine has graph for follow-up
        workflow_context_raw = await _filter_sherpa_workflow_context(
            user,
            chat_data.get("workflow_context"),
        )

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
            "allow_llm_chat",
            session=permission_session,
            skip_global_check=True,
        )
    if not allowed:
        await ws.send_json(
            {
                "type": "sherpa_error",
                "detail": "Sherpa AI features are disabled in user privacy settings.",
            }
        )
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
        workflow_context = await _filter_sherpa_workflow_context(
            user,
            data.get("workflow_context", data.get("context")),
        )

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
