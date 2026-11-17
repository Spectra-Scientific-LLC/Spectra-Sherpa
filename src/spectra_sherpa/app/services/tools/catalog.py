"""Detached interface projections for explicitly selected tool identities.

This module describes interfaces only. It neither discovers permitted tools nor
authorizes or dispatches calls; transports must supply reviewed selections and
enforce admission independently.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from spectra_sherpa.app.services.tools.registry import ToolRegistry
from spectra_sherpa.app.services.tools.schemas import ToolDefinition


def project_tool_catalog(registry: ToolRegistry, tool_names: Sequence[str]) -> list[dict[str, Any]]:
    """Project a closed selection, refusing incomplete or ambiguous interfaces.

    Registry ``name`` remains the operation identity. ``mcp_name`` is only the
    projected name; aliases never register handlers or change Advisor names.
    Returned dictionaries are detached from the mutable registry definitions.
    An empty selection yields an empty catalog, never all registered tools.
    """
    if isinstance(tool_names, (str, bytes)):
        raise ValueError("Tool selection must be a sequence of names")
    if len(set(tool_names)) != len(tool_names):
        raise ValueError("Duplicate tool identity in catalog selection")

    definitions = []
    projected_names: set[str] = set()
    for name in tool_names:
        entry = registry.get(name)
        if entry is None:
            raise ValueError(f"Unknown catalog tool: {name!r}")
        definition = ToolDefinition.model_validate(entry[0].model_dump())
        if definition.name != name:
            raise ValueError(f"Registry identity changed for {name!r}")
        required = ("version", "output_schema", "mutation", "disclosure", "distribution", "mcp_name")
        missing = [field for field in required if getattr(definition, field) is None]
        if missing:
            raise ValueError(f"Unclassified catalog tool {name!r}: {', '.join(missing)}")
        assert definition.mcp_name is not None
        if definition.mcp_name in projected_names:
            raise ValueError(f"Duplicate projected tool name: {definition.mcp_name!r}")
        projected_names.add(definition.mcp_name)
        definitions.append(definition)

    return [
        {
            "tool_id": definition.name,
            "name": definition.mcp_name,
            "version": definition.version,
            "description": definition.description,
            "input_schema": definition.parameters,
            "output_schema": definition.output_schema,
            "mutation": definition.mutation,
            "disclosure": definition.disclosure,
            "distribution": definition.distribution,
        }
        for definition in sorted(definitions, key=lambda item: item.mcp_name or "")
    ]
