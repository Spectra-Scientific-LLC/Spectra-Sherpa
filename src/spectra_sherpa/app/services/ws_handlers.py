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
from typing import Any, Callable, Optional

from fastapi import WebSocket

from app.core.config import app_config
from app.core.security import check_egress_permission
from app.db.session import async_session
from app.services.llm import LLMService
from app.services.rate_limiter import RateLimiter
from app.services.websocket_manager import ws_manager

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
                user, "allow_llm_context",
                data_type="metadata", destination="llm_context",
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
        use_tools = payload.get("use_tools", False)

        async with async_session() as session:
            service = LLMService(session, user=user)

            if use_tools and app_config.to_client_safe()["features"].get("agenticWorkflow"):
                try:
                    convo_id, content, tool_calls_log = await service.chat_with_tools(
                        message=message,
                        conversation_id=conversation_id,
                        metadata=metadata,
                    )
                except ValueError as exc:
                    await ws.send_json({"type": "error", "detail": str(exc)})
                    return
                await ws.send_json({"type": "llm_start", "conversation_id": convo_id})
                await ws.send_json({"type": "llm_chunk", "conversation_id": convo_id, "chunk": content})
                done_payload: dict = {"type": "llm_done", "conversation_id": convo_id}
                if tool_calls_log:
                    done_payload["tool_calls"] = tool_calls_log
                await ws.send_json(done_payload)
            else:
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

async def handle_sherpa_sync(
    ws: WebSocket,
    payload: dict,
    user: Any,
    rate_limiter: RateLimiter,
) -> None:
    try:
        from app.schemas.sherpa import EgressTier, WorkflowStateSync
        from app.services.sherpa_engine import get_sherpa_engine

        engine = get_sherpa_engine()

        # Path 1: Local SherpaEngine (SHERPA_ENGINE_API_KEY set on this server)
        if engine.is_available:
            # Engine sends workflow context to Anthropic — gate by allow_llm_context.
            # skip_global_check: admin explicitly configured the Anthropic key;
            # degraded SpectraSherpa cloud should not block direct LLM calls.
            async with async_session() as permission_session:
                allowed = await check_egress_permission(
                    user, "allow_llm_context",
                    data_type="workflow", destination="llm_context",
                    session=permission_session,
                    skip_global_check=True,
                )
            if not allowed:
                await ws.send_json({"type": "sherpa_error", "detail": "Sherpa analysis requires LLM context permission. Enable it in Settings > Data & Privacy."})
                return

            sync_data = dict(payload.get("payload", {}))
            tier = EgressTier(sync_data.pop("tier", "structure"))
            sync_msg = WorkflowStateSync(**sync_data)
            logger.info("sherpa_sync (engine): %d nodes, technique=%s", len(sync_msg.nodes), sync_msg.spectral_technique)
            await ws.send_json({"type": "sherpa_chat_start"})
            async for chunk in engine.analyze_workflow(sync_msg):
                await ws.send_json({"type": "sherpa_chat_chunk", "chunk": chunk})
            await ws.send_json({"type": "sherpa_chat_done"})
            return

        # Path 2: Cloud proxy (hybrid mode → remote SpectraSherpa server)
        from app.services.sherpa_advisor import get_sherpa_advisor

        advisor = get_sherpa_advisor()
        if not advisor.is_available:
            await ws.send_json({"type": "sherpa_status", "payload": {"connected": False, "reason": "not_configured"}})
            return

        # Cloud proxy sends workflow data to SpectraSherpa — gate by allow_spectrasherpa_sync
        async with async_session() as permission_session:
            allowed = await check_egress_permission(
                user, "allow_spectrasherpa_sync",
                data_type="workflow", destination="spectrasherpa",
                session=permission_session,
            )
        if not allowed:
            await ws.send_json({"type": "sherpa_error", "detail": "Sherpa sync not permitted. Enable cloud sync in Settings > Data & Privacy."})
            return

        sync_data = dict(payload.get("payload", {}))
        tier = EgressTier(sync_data.pop("tier", "structure"))
        sync_msg = WorkflowStateSync(**sync_data)
        recommendations = await advisor.sync_workflow(sync_msg, tier=tier)
        logger.info("sherpa_sync (proxy): %d nodes → %d recommendations", len(sync_msg.nodes), len(recommendations))
        await ws.send_json({
            "type": "sherpa_recommendations",
            "payload": [r.model_dump(mode="json") for r in recommendations],
        })
    except Exception as exc:
        logger.exception("sherpa_sync failed: %s", exc)
        await ws.send_json({"type": "sherpa_error", "detail": "Sherpa sync failed. Check server logs for details."})


async def handle_sherpa_decide(
    ws: WebSocket,
    payload: dict,
    user: Any,
    rate_limiter: RateLimiter,
) -> None:
    from app.services.sherpa_advisor import get_sherpa_advisor
    from app.schemas.sherpa import UserDecision

    advisor = get_sherpa_advisor()
    try:
        decision = UserDecision(**payload.get("payload", {}))
        delivered = await advisor.send_decision(decision)
        await ws.send_json({
            "type": "sherpa_decision_ack",
            "payload": {"delivered": delivered, "suggestion_id": decision.suggestion_id},
        })
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
        from app.services.sherpa_engine import get_sherpa_engine

        engine = get_sherpa_engine()
        chat_data = payload.get("payload", {})
        message = chat_data.get("message", "")
        history = chat_data.get("history", [])

        # Path 1: Local SherpaEngine
        if engine.is_available:
            # Engine sends context to Anthropic — gate by allow_llm_context.
            # skip_global_check: admin explicitly configured the Anthropic key;
            # degraded SpectraSherpa cloud should not block direct LLM calls.
            async with async_session() as permission_session:
                allowed = await check_egress_permission(
                    user, "allow_llm_context",
                    data_type="chat", destination="llm_context",
                    session=permission_session,
                    skip_global_check=True,
                )
            if not allowed:
                await ws.send_json({"type": "sherpa_error", "detail": "Sherpa chat requires LLM context permission."})
                return

            # Rebuild workflow context from payload if available
            workflow_context = None
            sync_payload = chat_data.get("workflow_context")
            if sync_payload:
                from app.schemas.sherpa import WorkflowStateSync
                workflow_context = WorkflowStateSync(**sync_payload)

            logger.info("sherpa_chat (engine): %s", message[:80])
            await ws.send_json({"type": "sherpa_chat_start"})
            async for chunk in engine.chat(
                message=message, workflow_context=workflow_context, history=history,
            ):
                await ws.send_json({"type": "sherpa_chat_chunk", "chunk": chunk})
            await ws.send_json({"type": "sherpa_chat_done"})
            return

        # Path 2: Cloud proxy
        from app.services.sherpa_advisor import get_sherpa_advisor

        advisor = get_sherpa_advisor()
        if not advisor.is_available:
            await ws.send_json({"type": "sherpa_status", "payload": {"connected": False, "reason": "not_configured"}})
            return

        # Cloud proxy sends chat to SpectraSherpa — gate by allow_spectrasherpa_sync
        async with async_session() as permission_session:
            allowed = await check_egress_permission(
                user, "allow_spectrasherpa_sync",
                data_type="chat", destination="spectrasherpa",
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
            message=message, workflow_id=workflow_id, history=history,
            workflow_context=workflow_context_raw,
        ):
            await ws.send_json({"type": "sherpa_chat_chunk", "chunk": chunk})
        await ws.send_json({"type": "sherpa_chat_done"})
    except Exception as exc:
        logger.exception("sherpa_chat failed: %s", exc)
        await ws.send_json({"type": "sherpa_error", "detail": "Sherpa chat failed. Check server logs for details."})


# ---------------------------------------------------------------------------
# MCP Tool actions
# ---------------------------------------------------------------------------

async def handle_tool_list(
    ws: WebSocket,
    payload: dict,
    user: Any,
    rate_limiter: RateLimiter,
) -> None:
    try:
        from app.services.tools import tool_registry
        from app.services.tools.schemas import ToolCategory, ToolScope

        category_filter = payload.get("category")
        if category_filter:
            try:
                cat = ToolCategory(category_filter)
            except ValueError:
                cat = None
        else:
            cat = None

        # Hide internal tools from WS callers; hide admin from non-superusers.
        hidden: set[ToolScope] = {ToolScope.internal}
        if not (user and getattr(user, "is_superuser", False)):
            hidden.add(ToolScope.admin)

        definitions = tool_registry.list_definitions(category=cat, exclude_scopes=hidden)
        await ws.send_json({
            "type": "tool_list",
            "payload": [d.model_dump(mode="json") for d in definitions],
        })
    except Exception as exc:
        logger.exception("tool_list failed: %s", exc)
        await ws.send_json({"type": "tool_error", "detail": "Failed to list tools"})


async def handle_tool_invoke(
    ws: WebSocket,
    payload: dict,
    user: Any,
    rate_limiter: RateLimiter,
) -> None:
    try:
        from app.services.tools.executor import ToolExecutionContext, execute_tool
        from app.services.tools.schemas import ToolInvocation

        # Rate limit
        user_key = f"user_{user.id}" if user and user.id else "anonymous"
        if not rate_limiter.allow(user_key):
            await ws.send_json({"type": "tool_error", "detail": "Tool rate limit exceeded. Try again later."})
            return

        tool_name = payload.get("tool_name")
        arguments = payload.get("arguments", {})
        invocation_id = payload.get("invocation_id")

        if not tool_name:
            await ws.send_json({"type": "tool_error", "detail": "Missing tool_name"})
            return

        invocation = ToolInvocation(
            tool_name=tool_name,
            arguments=arguments,
            **({"invocation_id": invocation_id} if invocation_id else {}),
        )

        async with async_session() as tool_session:
            ctx = ToolExecutionContext(session=tool_session, user=user)
            result = await execute_tool(invocation, ctx)

        await ws.send_json({
            "type": "tool_result",
            "payload": result.model_dump(mode="json"),
        })
    except Exception as exc:
        logger.exception("tool_invoke failed: %s", exc)
        await ws.send_json({"type": "tool_error", "detail": "Tool execution failed. Check server logs for details."})
