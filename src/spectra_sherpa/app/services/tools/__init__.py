"""
MCP-compatible tool system for SpectraSherpa.

Provides a registry, executor, and built-in tools that can be:
1. Exposed to LLMs as function-calling definitions
2. Invoked via WebSocket (tool_list / tool_invoke actions)
3. Extended via the plugin system

Architecture
------------
- ``schemas``   — Pydantic models (ToolDefinition, ToolInvocation, ToolResult)
- ``registry``  — Central tool registry with decorator-based registration
- ``executor``  — Invocation engine with permission and error handling
- ``builtin/``  — Domain-specific tools shipped with the app
"""
from __future__ import annotations

from spectra_sherpa.app.services.tools.registry import register_plugin_tool, tool_registry  # noqa: F401
from spectra_sherpa.app.services.tools.schemas import (  # noqa: F401
    ToolDefinition,
    ToolInvocation,
    ToolOrigin,
    ToolResult,
)
