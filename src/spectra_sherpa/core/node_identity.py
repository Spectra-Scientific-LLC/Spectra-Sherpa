"""Canonical public identities for workflow operations.

Operation identifiers are serialized into workflows, project archives, and run
evidence.  They therefore need a compatibility boundary when a public name is
cleaned up.  The registry and graph-admission paths use this module so legacy
bytes remain readable while every newly emitted graph uses the canonical name.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from copy import deepcopy
from typing import Any

SERIALIZED_NODE_TYPE_ALIASES: Mapping[str, str] = {
    "model.fitted_pls_v2": "model.fitted_pls",
    "model.apply_fitted_pls_v2": "model.apply_fitted_pls",
    "diagnostics.regression_evaluator_v2": "diagnostics.regression_evaluator",
    "diagnostics.classification_evaluator_v2": "diagnostics.classification_evaluator",
}

# These are the two data-free PLS producer contracts that shipped with the
# suffixed public operation ID.  Artifact bytes retain their original digest;
# compatibility is therefore exact and operation-scoped rather than a generic
# "old digest" bypass.
LEGACY_FITTED_PLS_CONTRACT_DIGESTS = frozenset(
    {
        "64bdf49b4d1cc289f43edca2e760037b3ce6c82e731bbb3c9aa1b7c7460028a8",
        "ac05f06a069e5551f5cd101dbaec0d40ff352860b360a98e367e1f17dbbaf98d",
    }
)


def canonical_node_type(node_type: str) -> str:
    """Resolve a historical serialized operation ID to its public identity."""

    return SERIALIZED_NODE_TYPE_ALIASES.get(node_type, node_type)


def node_contract_digest_is_compatible(
    node_type: str,
    serialized_digest: object,
    current_digest: str,
) -> bool:
    """Admit an exact identity-only predecessor without mutating artifacts."""

    return serialized_digest == current_digest or (
        canonical_node_type(node_type) == "model.fitted_pls"
        and isinstance(serialized_digest, str)
        and current_digest == "87a0e85157f008126f53af7f8945c7e730535431f866df628e9a226532440ff6"
        and serialized_digest in LEGACY_FITTED_PLS_CONTRACT_DIGESTS
    )


def _workflow_hash(
    nodes: list[dict[str, Any]],
    edges: list[dict[str, Any]],
    *,
    canonicalize: bool = True,
) -> str:
    canonical = {
        "nodes": sorted(
            (
                {
                    "node_id": node["node_id"],
                    "node_type": (canonical_node_type(node["node_type"]) if canonicalize else node["node_type"]),
                    "parameters": node.get("parameters", {}),
                }
                for node in nodes
            ),
            key=lambda node: node["node_id"],
        ),
        "edges": sorted(
            (
                {
                    "from_node_id": edge["from_node_id"],
                    "to_node_id": edge["to_node_id"],
                    "from_output": edge.get("from_output", "default"),
                    "to_input": edge.get("to_input", "default"),
                }
                for edge in edges
            ),
            key=lambda edge: (
                edge["from_node_id"],
                edge["to_node_id"],
                edge["from_output"],
                edge["to_input"],
            ),
        ),
    }
    payload = json.dumps(canonical, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _graph_contains_alias(nodes: list[Any]) -> bool:
    return any(
        isinstance(node, Mapping)
        and any(
            isinstance(node.get(key), str) and node[key] in SERIALIZED_NODE_TYPE_ALIASES
            for key in ("node_type", "operation_id", "type")
        )
        for node in nodes
    )


def require_valid_legacy_workflow_integrity(value: Any) -> None:
    """Reject an aliased serialized graph whose pre-migration hash is corrupt."""

    if isinstance(value, Mapping):
        nodes = value.get("nodes")
        edges = value.get("edges")
        integrity_hash = value.get("integrity_hash")
        if (
            isinstance(nodes, list)
            and isinstance(edges, list)
            and isinstance(integrity_hash, str)
            and _graph_contains_alias(nodes)
        ):
            try:
                expected = _workflow_hash(nodes, edges, canonicalize=False)
            except (KeyError, TypeError):
                expected = None
            if expected is None or integrity_hash != expected:
                raise ValueError("legacy serialized workflow integrity hash does not match")
        for item in value.values():
            require_valid_legacy_workflow_integrity(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            require_valid_legacy_workflow_integrity(item)


def canonicalize_serialized_workflow(value: Any) -> Any:
    """Return detached workflow-shaped JSON with operation aliases resolved.

    The traversal is deliberately key-directed: arbitrary strings in labels,
    parameters, notes, and scientific payloads must never be rewritten merely
    because they happen to equal an old operation ID.
    """

    if isinstance(value, dict):
        original_nodes = value.get("nodes")
        original_edges = value.get("edges")
        had_direct_alias = isinstance(original_nodes, list) and _graph_contains_alias(original_nodes)
        result = {key: canonicalize_serialized_workflow(item) for key, item in value.items()}
        looks_like_node = (
            "node_id" in result
            or "parameters" in result
            or ("id" in result and ("type" in result or "operation_id" in result))
        )
        node_type = result.get("node_type")
        if looks_like_node and isinstance(node_type, str):
            result["node_type"] = canonical_node_type(node_type)
        operation_id = result.get("operation_id")
        if looks_like_node and isinstance(operation_id, str):
            result["operation_id"] = canonical_node_type(operation_id)
        node_type_alias = result.get("type")
        if looks_like_node and isinstance(node_type_alias, str):
            result["type"] = canonical_node_type(node_type_alias)
        nodes = result.get("nodes")
        edges = result.get("edges")
        if had_direct_alias and "integrity_hash" in result and isinstance(nodes, list) and isinstance(edges, list):
            try:
                old_hash = _workflow_hash(original_nodes, original_edges, canonicalize=False)
                if value["integrity_hash"] == old_hash:
                    result["integrity_hash"] = _workflow_hash(nodes, edges)
            except (KeyError, TypeError):
                pass
        return result
    if isinstance(value, list):
        return [canonicalize_serialized_workflow(item) for item in value]
    if isinstance(value, tuple):
        return tuple(canonicalize_serialized_workflow(item) for item in value)
    return deepcopy(value)


__all__ = [
    "SERIALIZED_NODE_TYPE_ALIASES",
    "LEGACY_FITTED_PLS_CONTRACT_DIGESTS",
    "canonical_node_type",
    "canonicalize_serialized_workflow",
    "node_contract_digest_is_compatible",
    "require_valid_legacy_workflow_integrity",
]
