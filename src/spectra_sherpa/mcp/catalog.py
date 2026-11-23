"""One construction of the read-tool catalog for every MCP surface.

The local OSS MCP, the hosted public MCP and the commercial MCP all project the
same canonical read operations. A surface may only replace an output schema or
the idempotency hint for named tools; names, descriptions and input schemas
always come from the shared catalog.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import Any

NODE_PAGE_OUTPUT_DESCRIPTION = "Next page offset, or null."


def read_catalog(
    names: Iterable[str] | None = None,
    *,
    output_schema: Callable[[str, dict[str, Any]], dict[str, Any]] | None = None,
    idempotent: Callable[[str], bool] | None = None,
) -> list[tuple[dict[str, Any], Any]]:
    """Return ``(catalog_entry, mcp.types.Tool)`` pairs for the read operations."""
    import mcp.types as types

    from spectra_sherpa.app.services.inspection_bridge import ARGUMENT_MODELS
    from spectra_sherpa.app.services.inspection_comparison import register_comparison_catalog
    from spectra_sherpa.app.services.inspection_science import register_scientific_catalog
    from spectra_sherpa.app.services.tools import builtin  # noqa: F401
    from spectra_sherpa.app.services.tools.builtin.runs import inspection_run_catalog
    from spectra_sherpa.app.services.tools.catalog import project_tool_catalog
    from spectra_sherpa.app.services.tools.registry import tool_registry

    selected = sorted(ARGUMENT_MODELS if names is None else names)
    if not set(selected) <= set(ARGUMENT_MODELS):
        raise ValueError("Unregistered inspection interface")
    registry = inspection_run_catalog()
    register_scientific_catalog(registry)
    register_comparison_catalog(registry)
    for name in selected:
        if registry.get(name) is None:
            entry = tool_registry.get(name)
            if entry is None:
                raise ValueError("Unregistered inspection interface")
            registry.register(*entry)
    catalog = []
    for entry in project_tool_catalog(registry, selected):
        if entry["mutation"] != "read" or entry["distribution"] != "oss":
            raise ValueError("Unreviewed MCP read contract")
        schema = entry["output_schema"]
        if entry["tool_id"] == "list_node_types":
            schema = {
                "type": "object",
                "properties": {
                    "items": schema,
                    "next_offset": {"type": ["integer", "null"], "description": NODE_PAGE_OUTPUT_DESCRIPTION},
                },
                "required": ["items", "next_offset"],
                "additionalProperties": False,
            }
        if output_schema is not None:
            schema = output_schema(entry["tool_id"], schema)
        catalog.append(
            (
                entry,
                types.Tool(
                    name=entry["name"],
                    description=entry["description"],
                    inputSchema=ARGUMENT_MODELS[entry["tool_id"]].model_json_schema(),
                    outputSchema=schema,
                    annotations=types.ToolAnnotations(
                        readOnlyHint=True,
                        destructiveHint=False,
                        idempotentHint=True if idempotent is None else idempotent(entry["tool_id"]),
                        openWorldHint=False,
                    ),
                ),
            )
        )
    return catalog
