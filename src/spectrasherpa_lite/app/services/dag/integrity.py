"""
Workflow integrity hash — SHA-256 of semantic content.

Produces a deterministic hash from the execution-relevant parts of a
workflow (node types, parameters, connections). UI-only fields
(positions, labels, annotations, canvas_state) are excluded so that
moving a node on the canvas does not change the hash.

Usage:
    from app.services.dag.integrity import compute_workflow_hash

    h = compute_workflow_hash(nodes_list, edges_list)
"""

from __future__ import annotations

import hashlib
import json
from typing import Any


def _canonical_node(node: dict[str, Any]) -> dict[str, Any]:
    """Extract semantically meaningful fields from a node dict."""
    return {
        "node_id": node["node_id"],
        "node_type": node["node_type"],
        "parameters": node.get("parameters", {}),
    }


def _canonical_edge(edge: dict[str, Any]) -> dict[str, Any]:
    """Extract semantically meaningful fields from an edge dict."""
    return {
        "from_node_id": edge["from_node_id"],
        "to_node_id": edge["to_node_id"],
        "from_output": edge.get("from_output", "default"),
        "to_input": edge.get("to_input", "default"),
    }


def compute_workflow_hash(
    nodes: list[dict[str, Any]],
    edges: list[dict[str, Any]],
) -> str:
    """
    Compute SHA-256 integrity hash of a workflow definition.

    Only execution-semantic content is included: node types, parameters,
    and connections. UI-only fields (positions, labels, annotations) are
    excluded so cosmetic changes don't invalidate the hash.

    Args:
        nodes: List of node dicts, each with at least ``node_id``,
               ``node_type``, and ``parameters``.
        edges: List of edge dicts with ``from_node_id``, ``to_node_id``,
               ``from_output``, ``to_input``.

    Returns:
        Hex-encoded SHA-256 hash string (64 characters).
    """
    canonical = {
        "nodes": sorted(
            [_canonical_node(n) for n in nodes],
            key=lambda n: n["node_id"],
        ),
        "edges": sorted(
            [_canonical_edge(e) for e in edges],
            key=lambda e: (
                e["from_node_id"],
                e["to_node_id"],
                e["from_output"],
                e["to_input"],
            ),
        ),
    }
    payload = json.dumps(canonical, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
