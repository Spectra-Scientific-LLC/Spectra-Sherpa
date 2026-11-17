"""Optional stdio adapter for the closed local inspection interface."""

from __future__ import annotations

import json

from spectra_sherpa.mcp.bridge_client import BridgeUnavailable, Connection, inspect


def create_server(connection: Connection):
    # Kept behind the CLI subcommand: base Workbench imports never require MCP.
    import mcp.types as types
    from mcp.server import Server

    from spectra_sherpa import __version__
    from spectra_sherpa.app.services.inspection_bridge import NodeListArguments
    from spectra_sherpa.app.services.tools import builtin  # noqa: F401
    from spectra_sherpa.app.services.tools.catalog import project_tool_catalog
    from spectra_sherpa.app.services.tools.registry import tool_registry

    entry = project_tool_catalog(tool_registry, ["list_node_types"])[0]
    output_schema = {
        "type": "object",
        "properties": {
            "items": entry["output_schema"],
            "next_offset": {"type": ["integer", "null"], "description": "Offset of the next page, or null at the end."},
        },
        "required": ["items", "next_offset"],
        "additionalProperties": False,
    }
    tool = types.Tool(
        name=entry["name"],
        description=entry["description"],
        inputSchema=NodeListArguments.model_json_schema(),
        outputSchema=output_schema,
        annotations=types.ToolAnnotations(
            readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False
        ),
    )

    async def list_tools(context, params):
        # Client handshake names carry no authority. Revalidate the Workbench
        # connection before advertising this session's available operation.
        await inspect(connection, "list_node_types", {"limit": 1})
        return types.ListToolsResult(tools=[tool])

    async def call_tool(context, params):
        try:
            result = await inspect(connection, params.name, params.arguments or {})
            return types.CallToolResult(
                content=[types.TextContent(type="text", text=json.dumps(result, ensure_ascii=False))],
                structuredContent=result,
            )
        except BridgeUnavailable as exc:
            return types.CallToolResult(content=[types.TextContent(type="text", text=str(exc))], isError=True)

    return Server("spectra-sherpa-inspection", version=__version__, on_list_tools=list_tools, on_call_tool=call_tool)


async def serve(connection: Connection) -> None:
    import sys

    import anyio
    from mcp.server.stdio import stdio_server

    class BoundedInput:
        """Bound each JSON-RPC line before the SDK parses or allocates a model."""

        def __init__(self):
            self.stream = sys.stdin.buffer

        def __aiter__(self):
            return self

        async def __anext__(self):
            line = await anyio.to_thread.run_sync(self.stream.readline, 16385)
            if not line:
                raise StopAsyncIteration
            if len(line) > 16384:
                raise ValueError("MCP message exceeds limit")
            return line.decode("utf-8")

    server = create_server(connection)
    async with stdio_server(stdin=BoundedInput()) as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())
