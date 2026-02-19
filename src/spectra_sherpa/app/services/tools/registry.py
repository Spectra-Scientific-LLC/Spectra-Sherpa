"""
Central tool registry for SpectraSherpa.

Mirrors the DAG ``NodeRegistry`` pattern:
- ``@register_tool`` decorator for built-in tools
- Plugin tools registered via ``tool_registry.register()``
- Serialization helpers for LLM function-calling payloads
"""

from __future__ import annotations

import contextlib
import logging
from typing import Any, Callable, Iterator, Optional

from spectra_sherpa.app.services.tools.schemas import (
    ToolCategory,
    ToolDefinition,
    ToolHandler,
    ToolOrigin,
    ToolScope,
)

logger = logging.getLogger(__name__)


class ToolRegistry:
    """Thread-safe registry of available tools."""

    def __init__(self) -> None:
        self._tools: dict[str, tuple[ToolDefinition, ToolHandler]] = {}
        self._plugin_mode: bool = False

    # ---- Plugin loading context ----

    @contextlib.contextmanager
    def plugin_context(self) -> Iterator[None]:
        """Context manager that forces ``origin=plugin`` on all registrations.

        Used by the plugin loader to ensure any tool registered during
        plugin import — whether via ``@register_tool``, ``register_plugin_tool()``,
        or direct ``registry.register()`` — gets plugin trust constraints applied.

        Usage::

            with tool_registry.plugin_context():
                importlib.import_module("my_plugin")
        """
        self._plugin_mode = True
        try:
            yield
        finally:
            self._plugin_mode = False

    # ---- Registration ----

    def register(
        self,
        definition: ToolDefinition,
        handler: ToolHandler,
    ) -> None:
        """Register a tool (idempotent — last writer wins with a warning).

        Plugin-origin tools are automatically constrained:
        - ``scope`` cannot be ``internal`` (forced to ``public``)
        - ``requires_user`` is forced to ``True`` (per-user permissions always apply)

        When ``plugin_context()`` is active, all tools are forced to
        ``origin=plugin`` regardless of what the caller declares.
        """
        if definition.name in self._tools:
            logger.warning(
                "Tool %r re-registered (overwriting previous handler)",
                definition.name,
            )

        # Force plugin origin when inside plugin_context()
        if self._plugin_mode and definition.origin != ToolOrigin.plugin:
            definition = definition.model_copy(update={"origin": ToolOrigin.plugin})

        # ---- Plugin trust boundary enforcement ----
        if definition.origin == ToolOrigin.plugin:
            if definition.scope == ToolScope.internal:
                logger.warning(
                    "Plugin tool %r requested scope=internal — forced to public",
                    definition.name,
                )
                definition = definition.model_copy(update={"scope": ToolScope.public})
            if not definition.requires_user:
                definition = definition.model_copy(update={"requires_user": True})

        self._tools[definition.name] = (definition, handler)
        logger.debug("Registered tool: %s (origin=%s)", definition.name, definition.origin.value)

    def unregister(self, name: str) -> bool:
        """Remove a tool by name. Returns True if it was present."""
        return self._tools.pop(name, None) is not None

    # ---- Lookup ----

    def get(self, name: str) -> tuple[ToolDefinition, ToolHandler] | None:
        """Return (definition, handler) or None."""
        return self._tools.get(name)

    def __contains__(self, name: str) -> bool:
        return name in self._tools

    def __len__(self) -> int:
        return len(self._tools)

    # ---- Listing ----

    def list_definitions(
        self,
        category: Optional[ToolCategory] = None,
        exclude_scopes: Optional[set[ToolScope]] = None,
    ) -> list[ToolDefinition]:
        """Return all registered definitions, optionally filtered by category.

        Args:
            category: If set, only return tools matching this category.
            exclude_scopes: If set, hide tools with these scopes
                (e.g. ``{ToolScope.internal}`` to exclude LLM-only tools
                from the WS ``tool_list`` response).
        """
        defs = [defn for defn, _ in self._tools.values()]
        if category is not None:
            defs = [d for d in defs if d.category == category]
        if exclude_scopes:
            defs = [d for d in defs if d.scope not in exclude_scopes]
        return sorted(defs, key=lambda d: d.name)

    # ---- LLM format helpers ----

    def to_openai_tools(
        self,
        category: Optional[ToolCategory] = None,
    ) -> list[dict[str, Any]]:
        """Return all tools in OpenAI function-calling format."""
        return [d.to_openai_tool() for d in self.list_definitions(category)]

    def to_anthropic_tools(
        self,
        category: Optional[ToolCategory] = None,
    ) -> list[dict[str, Any]]:
        """Return all tools in Anthropic tool-use format."""
        return [d.to_anthropic_tool() for d in self.list_definitions(category)]


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------
tool_registry = ToolRegistry()


# ---------------------------------------------------------------------------
# Decorator for built-in tool registration
# ---------------------------------------------------------------------------
def register_tool(
    name: str,
    description: str,
    *,
    category: ToolCategory = ToolCategory.system,
    parameters: dict[str, Any] | None = None,
    requires_session: bool = False,
    requires_user: bool = False,
    requires_egress: bool = False,
    egress_permission: str | None = None,
    scope: ToolScope = ToolScope.public,
) -> Callable[[ToolHandler], ToolHandler]:
    """
    Decorator that registers a function as an MCP tool.

    Usage::

        @register_tool(
            "list_node_types",
            "List available DAG node types",
            category=ToolCategory.spectral,
            parameters={
                "type": "object",
                "properties": {
                    "category": {
                        "type": "string",
                        "description": "Filter by category",
                    }
                },
                "required": [],
            },
        )
        async def list_node_types(category: str | None = None) -> list[dict]:
            ...
    """

    def decorator(fn: ToolHandler) -> ToolHandler:
        defn = ToolDefinition(
            name=name,
            description=description,
            category=category,
            parameters=parameters or {"type": "object", "properties": {}, "required": []},
            requires_session=requires_session,
            requires_user=requires_user,
            requires_egress=requires_egress,
            egress_permission=egress_permission,
            scope=scope,
            origin=ToolOrigin.builtin,  # decorator is trusted code
        )
        tool_registry.register(defn, fn)
        return fn

    return decorator


def register_plugin_tool(
    definition: ToolDefinition,
    handler: ToolHandler,
) -> None:
    """Register a plugin-origin tool with enforced trust constraints.

    This is the recommended entry point for third-party plugins::

        from spectra_sherpa.app.services.tools.registry import register_plugin_tool
        from spectra_sherpa.app.services.tools.schemas import ToolDefinition, ToolCategory

        defn = ToolDefinition(
            name="my_plugin_tool",
            description="...",
            category=ToolCategory.spectral,
        )
        register_plugin_tool(defn, my_handler)

    The registry will automatically:
    - Set ``origin`` to ``plugin``
    - Force ``scope`` to ``public`` (cannot be ``internal``)
    - Force ``requires_user=True`` (per-user permissions always apply)
    """
    definition = definition.model_copy(update={"origin": ToolOrigin.plugin})
    tool_registry.register(definition, handler)
