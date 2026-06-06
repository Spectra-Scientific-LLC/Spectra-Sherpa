"""Workflow parameter snapshots for run reproducibility."""

from __future__ import annotations

from typing import Any, Iterable

from spectra_sherpa.app.services.dag import node_registry


def build_effective_params_snapshot(nodes: Iterable[Any]) -> dict[str, dict[str, Any]]:
    """Return per-node parameters with metadata defaults materialized.

    Saved workflows often store only values the user changed. Run comparison,
    however, needs the effective settings that were actually used. The DAG node
    resolver already defines that contract, so this helper mirrors execution
    by creating the node and asking it to resolve defaults.
    """
    snapshot: dict[str, dict[str, Any]] = {}
    for workflow_node in nodes:
        node_id = getattr(workflow_node, "node_id", None)
        node_type = getattr(workflow_node, "node_type", None)
        explicit_params = getattr(workflow_node, "parameters", None) or {}
        if not node_id:
            continue
        if not node_type:
            if explicit_params:
                snapshot[str(node_id)] = dict(explicit_params)
            continue
        try:
            node = node_registry.create_node(str(node_type), str(node_id), explicit_params)
            resolved = node._resolve_params()
            for key, value in explicit_params.items():
                resolved.setdefault(key, value)
        except Exception:
            resolved = dict(explicit_params)
        if resolved:
            snapshot[str(node_id)] = resolved
    return snapshot
