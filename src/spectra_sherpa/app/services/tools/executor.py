"""
Tool invocation engine.

Responsibilities:
1. Resolve tool from registry
2. Validate arguments against JSON Schema
3. Check access scope (public / admin / internal)
4. Check egress: global flag AND per-user permission
5. Inject context (session, user) if required by the tool
6. Call handler (sync or async)
7. Wrap result in ToolResult
"""

from __future__ import annotations

import asyncio
import inspect
import logging
from typing import Any, Optional

from spectra_sherpa.app.services.tools.registry import tool_registry
from spectra_sherpa.app.services.tools.schemas import ToolInvocation, ToolResult, ToolScope

logger = logging.getLogger(__name__)


class ToolExecutionContext:
    """
    Optional context passed to tools that declare ``requires_session``
    or ``requires_user``.
    """

    def __init__(
        self,
        session: Any = None,
        user: Any = None,
    ) -> None:
        self.session = session
        self.user = user


def _validate_arguments(schema: dict[str, Any], arguments: dict[str, Any]) -> str | None:
    """
    Validate arguments against a JSON Schema.

    Returns an error message string on failure, or None on success.
    Uses ``jsonschema`` if available, otherwise falls back to
    required-field checking only.
    """
    try:
        import jsonschema

        jsonschema.validate(instance=arguments, schema=schema)
        return None
    except ImportError:
        # Fallback: check required fields only
        required = schema.get("required", [])
        properties = schema.get("properties", {})
        missing = [r for r in required if r not in arguments]
        if missing:
            return f"Missing required arguments: {', '.join(missing)}"
        # Check for unexpected arguments
        if properties:
            unknown = [k for k in arguments if k not in properties]
            if unknown:
                return f"Unknown arguments: {', '.join(unknown)}"
        return None
    except jsonschema.ValidationError as exc:
        return exc.message


async def execute_tool(
    invocation: ToolInvocation,
    context: Optional[ToolExecutionContext] = None,
    *,
    allow_internal: bool = False,
) -> ToolResult:
    """
    Execute a tool invocation and return a ToolResult.

    This is the single entry point for all tool calls — whether from
    the LLM function-calling loop or from WebSocket ``tool_invoke``.

    Args:
        allow_internal: When ``True``, ``scope=internal`` tools are
            allowed.  The LLM function-calling loop sets this; the
            WS ``tool_invoke`` handler does not, so users cannot
            directly invoke internal tools.
    """
    entry = tool_registry.get(invocation.tool_name)
    if entry is None:
        available = ", ".join(d.name for d in tool_registry.list_definitions())
        return ToolResult(
            invocation_id=invocation.invocation_id,
            tool_name=invocation.tool_name,
            success=False,
            error=f"Unknown tool: {invocation.tool_name!r}. Available: {available}",
        )

    defn, handler = entry

    # ---- Scope check ----
    if defn.scope == ToolScope.internal and not allow_internal:
        return ToolResult(
            invocation_id=invocation.invocation_id,
            tool_name=invocation.tool_name,
            success=False,
            error=f"Tool {invocation.tool_name!r} is internal and cannot be invoked directly",
        )

    if defn.scope == ToolScope.admin:
        user = context.user if context else None
        # v0.4.1 Phase 2: is_superuser moved to ManagedUserAccount; OSS
        # asks the server-registered admin resolver. Local mode (no
        # server) has no superusers, so this fail-closes as before.
        from spectra_sherpa.app.contracts.auth_resolver import is_admin_user

        if not user or not await is_admin_user(user):
            return ToolResult(
                invocation_id=invocation.invocation_id,
                tool_name=invocation.tool_name,
                success=False,
                error=f"Tool {invocation.tool_name!r} requires admin access",
            )

    # ---- Validate arguments against JSON Schema ----
    validation_error = _validate_arguments(defn.parameters, invocation.arguments)
    if validation_error:
        return ToolResult(
            invocation_id=invocation.invocation_id,
            tool_name=invocation.tool_name,
            success=False,
            error=f"Invalid arguments: {validation_error}",
        )

    # Build kwargs from invocation arguments
    kwargs: dict[str, Any] = dict(invocation.arguments)

    # ---- Inject context if the tool requires it ----
    if defn.requires_session:
        if context is None or context.session is None:
            return ToolResult(
                invocation_id=invocation.invocation_id,
                tool_name=invocation.tool_name,
                success=False,
                error=f"Tool {invocation.tool_name!r} requires a database session",
            )
        kwargs["session"] = context.session

    if defn.requires_user:
        if context is None or context.user is None:
            return ToolResult(
                invocation_id=invocation.invocation_id,
                tool_name=invocation.tool_name,
                success=False,
                error=f"Tool {invocation.tool_name!r} requires a user context",
            )
        kwargs["user"] = context.user

    # ---- Egress checks: global + per-user ----
    if defn.requires_egress:
        from spectra_sherpa.app.core.security import is_egress_enabled

        if not is_egress_enabled():
            return ToolResult(
                invocation_id=invocation.invocation_id,
                tool_name=invocation.tool_name,
                success=False,
                error="Tool requires network egress but egress is disabled",
            )

    if defn.egress_permission:
        # Per-user egress permission check (requires session + user)
        from spectra_sherpa.app.core.security import check_egress_permission

        user = context.user if context else None
        session = context.session if context else None
        allowed = await check_egress_permission(
            user,
            defn.egress_permission,
            data_type="tool",
            destination=f"tool:{invocation.tool_name}",
            session=session,
        )
        if not allowed:
            return ToolResult(
                invocation_id=invocation.invocation_id,
                tool_name=invocation.tool_name,
                success=False,
                error=f"Egress permission '{defn.egress_permission}' denied for this user",
            )

    # ---- Call handler ----
    try:
        logger.info(
            "Executing tool %s (id=%s, origin=%s)",
            invocation.tool_name,
            invocation.invocation_id,
            defn.origin.value,
        )

        if inspect.iscoroutinefunction(handler):
            result = await handler(**kwargs)
        else:
            # Run sync handlers in a thread to avoid blocking the event loop
            result = await asyncio.to_thread(handler, **kwargs)

        logger.info("Tool %s completed successfully", invocation.tool_name)
        return ToolResult(
            invocation_id=invocation.invocation_id,
            tool_name=invocation.tool_name,
            success=True,
            result=result,
        )
    except Exception as e:
        logger.exception("Tool %s failed", invocation.tool_name)
        return ToolResult(
            invocation_id=invocation.invocation_id,
            tool_name=invocation.tool_name,
            success=False,
            error=str(e),
        )
