"""Shared upstream closure for partial-run admission and execution."""

from collections.abc import Iterable

from .executor_types import WorkflowEdge


def upstream_node_ids(node_ids: Iterable[str], edges: Iterable[WorkflowEdge], target: str) -> set[str]:
    known = set(node_ids)
    if target not in known:
        raise ValueError(f"Node {target} not found in workflow")
    incoming: dict[str, list[str]] = {}
    for edge in edges:
        incoming.setdefault(edge.to_node, []).append(edge.from_node)
    selected: set[str] = set()
    pending = [target]
    while pending:
        current = pending.pop()
        if current in selected:
            continue
        selected.add(current)
        # Retain missing upstream IDs so admission still sees dangling edges.
        pending.extend(incoming.get(current, []))
    return selected
