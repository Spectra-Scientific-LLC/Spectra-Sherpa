"""
Pydantic models for the MCP-compatible tool system.

These models define the contract between:
- Tool authors (built-in and plugin)
- The LLM function-calling layer
- The WebSocket tool_invoke / tool_result protocol
"""

from __future__ import annotations

import uuid
from enum import Enum
from typing import Any, Callable, Coroutine, Optional

from pydantic import BaseModel, Field


class ToolCategory(str, Enum):
    """Broad tool categories for filtering and UI grouping."""

    spectral = "spectral"
    workflow = "workflow"
    data = "data"
    system = "system"


class ToolScope(str, Enum):
    """Access scope controlling who can discover and invoke a tool."""

    public = "public"  # Any authenticated user
    admin = "admin"  # Superusers only
    internal = "internal"  # LLM function-calling only (hidden from tool_list)


class ToolOrigin(str, Enum):
    """Where a tool was registered from — used for trust boundaries."""

    builtin = "builtin"  # Core built-in tools (trusted)
    plugin = "plugin"  # Third-party plugin (constrained)


class ToolDefinition(BaseModel):
    """
    Declarative description of a callable tool.

    ``parameters`` uses JSON Schema (draft-07) format so it can be sent
    directly to OpenAI / Anthropic / Gemini function-calling APIs.
    """

    name: str = Field(
        ...,
        description="Unique tool identifier (e.g. 'list_node_types')",
        pattern=r"^[a-z][a-z0-9_]{0,63}$",
    )
    description: str = Field(..., description="Human-readable description shown to LLM and UI")
    category: ToolCategory = Field(
        default=ToolCategory.system,
        description="Broad category for filtering",
    )
    parameters: dict[str, Any] = Field(
        default_factory=lambda: {
            "type": "object",
            "properties": {},
            "required": [],
        },
        description="JSON Schema describing the tool's input parameters",
    )
    requires_session: bool = Field(
        default=False,
        description="Whether the handler needs a DB session",
    )
    requires_user: bool = Field(
        default=False,
        description="Whether the handler needs a User context",
    )
    requires_egress: bool = Field(
        default=False,
        description="Whether the tool performs outbound network calls",
    )
    egress_permission: Optional[str] = Field(
        default=None,
        description=(
            "Per-user egress permission name checked via check_egress_permission(). "
            "E.g. 'allow_llm_context', 'allow_nist_queries'. "
            "When set, both global egress AND user permission must pass."
        ),
    )
    scope: ToolScope = Field(
        default=ToolScope.public,
        description="Access scope controlling discovery and invocation",
    )
    origin: ToolOrigin = Field(
        default=ToolOrigin.builtin,
        description=(
            "Where this tool was registered from. " "Plugin-origin tools have restricted scope and forced user context."
        ),
    )

    # ---- LLM format helpers ----

    def to_openai_tool(self) -> dict[str, Any]:
        """Return OpenAI function-calling ``tools`` entry."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }

    def to_anthropic_tool(self) -> dict[str, Any]:
        """Return Anthropic tool-use ``tools`` entry."""
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.parameters,
        }


class ToolInvocation(BaseModel):
    """Request to invoke a registered tool."""

    invocation_id: str = Field(
        default_factory=lambda: str(uuid.uuid4()),
        description="Unique request ID for tracking",
    )
    tool_name: str = Field(..., description="Name of the tool to call")
    arguments: dict[str, Any] = Field(
        default_factory=dict,
        description="Arguments matching the tool's parameter schema",
    )


class ToolResult(BaseModel):
    """Result returned after tool execution."""

    invocation_id: str
    tool_name: str
    success: bool = True
    result: Any = None
    error: Optional[str] = None

    def to_openai_message(self, tool_call_id: str) -> dict[str, Any]:
        """Format as an OpenAI ``tool`` role message."""
        import json

        content = json.dumps(self.result) if self.success else (self.error or "Unknown error")
        return {
            "role": "tool",
            "tool_call_id": tool_call_id,
            "content": content,
        }

    def to_anthropic_block(self, tool_use_id: str) -> dict[str, Any]:
        """Format as an Anthropic ``tool_result`` content block."""
        import json

        if self.success:
            return {
                "type": "tool_result",
                "tool_use_id": tool_use_id,
                "content": json.dumps(self.result),
            }
        return {
            "type": "tool_result",
            "tool_use_id": tool_use_id,
            "is_error": True,
            "content": self.error or "Unknown error",
        }


# Type alias for tool handler functions.
# Handlers receive keyword arguments matching their tool's parameter schema.
# They may be sync or async.
ToolHandler = Callable[..., Any | Coroutine[Any, Any, Any]]
