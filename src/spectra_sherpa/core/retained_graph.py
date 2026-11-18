"""Bounded inert workflow inspection, deliberately separate from graph admission.

No registry, node class, renderer, source file or Python expression is consulted.
This representation can display unknown historical operations but cannot become
an executable WorkflowSpec merely by passing structural inspection.
"""

from __future__ import annotations

import json
import math
from typing import Annotated, Literal

from pydantic import Field, JsonValue, computed_field

from spectra_sherpa.core.pack_manifest import Frozen
from spectra_sherpa.core.pack_requirements import PackGraphBinding, parse_pack_graph_binding

MAX_GRAPH_BYTES = 2 * 1024 * 1024
TextId = Annotated[str, Field(min_length=1, max_length=256)]


class RetainedNode(Frozen):
    node_id: TextId
    node_type: Annotated[str, Field(min_length=1, max_length=160)]
    label: Annotated[str, Field(max_length=1024)] | None = None
    parameters: dict[str, JsonValue] = Field(default_factory=dict)

    @computed_field
    @property
    def parameters_json(self) -> str:
        """Exact integer/text display without browser numeric coercion."""
        return json.dumps(self.parameters, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


class RetainedEdge(Frozen):
    from_node_id: TextId
    to_node_id: TextId
    from_output: TextId = "default"
    to_input: TextId = "default"


class RetainedGraph(Frozen):
    schema_version: Literal["spectra-retained-graph/1"] = "spectra-retained-graph/1"
    inspection_only: Literal[True] = True
    name: Annotated[str, Field(max_length=1024)] = "Retained workflow"
    nodes: Annotated[tuple[RetainedNode, ...], Field(max_length=1024)]
    edges: Annotated[tuple[RetainedEdge, ...], Field(max_length=16384)]
    pack_binding: PackGraphBinding | None = None


class RetainedGraphError(ValueError):
    """The evidence cannot be safely represented within the inspection bounds."""


def inspect_retained_graph(payload: bytes) -> RetainedGraph:
    if type(payload) is not bytes or len(payload) > MAX_GRAPH_BYTES:
        raise RetainedGraphError("Retained workflow exceeds the inspection size limit")

    def unique_object(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise RetainedGraphError("Retained workflow repeats a JSON field")
            result[key] = value
        return result

    def finite_number(value):
        raise RetainedGraphError("Retained workflow contains a non-finite JSON number")

    try:
        value = json.loads(payload, object_pairs_hook=unique_object, parse_constant=finite_number)
        pending = [(value, 0)]
        count = 0
        while pending:
            item, depth = pending.pop()
            count += 1
            if depth > 24 or count > 200000:
                raise RetainedGraphError("Retained workflow exceeds the inspection structure limit")
            if isinstance(item, float) and not math.isfinite(item):
                raise RetainedGraphError("Retained workflow contains a non-finite JSON number")
            if isinstance(item, dict):
                pending.extend((nested, depth + 1) for nested in item.values())
            elif isinstance(item, list):
                pending.extend((nested, depth + 1) for nested in item)
        if (
            not isinstance(value, dict)
            or not isinstance(value.get("nodes"), list)
            or not isinstance(value.get("edges"), list)
        ):
            raise RetainedGraphError("Retained workflow requires node and edge arrays")
        if len(value["nodes"]) > 1024 or len(value["edges"]) > 16384:
            raise RetainedGraphError("Retained workflow exceeds the inspection graph limit")
        # Only fields with an inert display meaning are projected. There is no
        # renderer/module/callable field and no graph canonicalization.
        nodes = tuple(
            RetainedNode.model_validate(
                {key: node[key] for key in ("node_id", "node_type", "label", "parameters") if key in node}
            )
            for node in value["nodes"]
        )
        edges = tuple(
            RetainedEdge.model_validate(
                {key: edge[key] for key in ("from_node_id", "to_node_id", "from_output", "to_input") if key in edge}
            )
            for edge in value["edges"]
        )
        ids = {node.node_id for node in nodes}
        if len(ids) != len(nodes) or any(edge.from_node_id not in ids or edge.to_node_id not in ids for edge in edges):
            raise RetainedGraphError("Retained workflow contains duplicate or dangling node identities")
        binding = None
        if value.get("pack_binding") is not None:
            binding = parse_pack_graph_binding(
                json.dumps(value["pack_binding"], ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode(
                    "utf-8"
                )
            )
            types = {node.node_id: node.node_type for node in nodes}
            if any(types.get(node.node_id) != node.node_type for node in binding.nodes):
                raise RetainedGraphError("Retained pack binding contradicts its graph")
        return RetainedGraph(
            name=value.get("name") or "Retained workflow", nodes=nodes, edges=edges, pack_binding=binding
        )
    except RetainedGraphError:
        raise
    except (ValueError, TypeError, KeyError, RecursionError) as exc:
        raise RetainedGraphError("Retained workflow is malformed") from exc
