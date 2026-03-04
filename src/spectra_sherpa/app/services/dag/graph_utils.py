"""
Shared graph utilities for DAG workflow processing.

Provides topological sort, dependency mapping, and input resolution
used by both the DAG executor and the Python code exporter.
"""

from __future__ import annotations

from collections import deque
from typing import NamedTuple, Sequence


class Edge(NamedTuple):
    """Normalized directed edge between two nodes."""

    from_node: str
    to_node: str
    from_output: str = "default"
    to_input: str = "default"


def build_dependency_map(node_ids: Sequence[str], edges: Sequence[Edge]) -> dict[str, list[str]]:
    """
    Build a mapping of each node to the nodes it depends on.

    Args:
        node_ids: All node IDs in the graph
        edges: Directed edges (from_node -> to_node)

    Returns:
        Dict mapping node_id -> list of upstream node_ids
    """
    deps: dict[str, list[str]] = {nid: [] for nid in node_ids}
    for edge in edges:
        deps[edge.to_node].append(edge.from_node)
    return deps


def topological_sort(node_ids: Sequence[str], edges: Sequence[Edge]) -> list[str]:
    """
    Kahn's algorithm for topological ordering.

    Args:
        node_ids: All node IDs in the graph
        edges: Directed edges (from_node -> to_node)

    Returns:
        Node IDs in execution order (sources first)

    Raises:
        ValueError: If the graph contains a cycle
    """
    deps = build_dependency_map(node_ids, edges)
    in_degree = {nid: len(dep_list) for nid, dep_list in deps.items()}

    # Reverse map: node -> list of nodes that depend on it
    reverse_deps: dict[str, list[str]] = {nid: [] for nid in node_ids}
    for nid, dep_list in deps.items():
        for dep in dep_list:
            reverse_deps[dep].append(nid)

    queue = deque(nid for nid, degree in in_degree.items() if degree == 0)
    result: list[str] = []

    while queue:
        node_id = queue.popleft()
        result.append(node_id)
        for dependent in reverse_deps.get(node_id, []):
            in_degree[dependent] -= 1
            if in_degree[dependent] == 0:
                queue.append(dependent)

    if len(result) != len(node_ids):
        raise ValueError("Workflow contains cycles - not a valid DAG")

    return result


def build_input_map(
    node_id: str,
    edges: Sequence[Edge],
    *,
    dict_output_nodes: frozenset[str] = frozenset(),
) -> dict[str, str | list[str]]:
    """
    Build a mapping of input names to Python codegen expressions.

    Used by the Python exporter to generate ``results['upstream']``
    or ``results['upstream']['port']`` references for each input.

    When multiple edges target the same port (variadic), the value
    is a list of expression strings.

    Args:
        node_id: Target node ID
        edges: All edges in the graph
        dict_output_nodes: Node IDs whose ``generate_python()`` always
            emits a dict result (regardless of how many ports are wired).
            When an upstream node is in this set, all references are
            dict-qualified (e.g. ``results['pca']['default']``).

    Returns:
        Dict mapping port name -> expression string (or list for variadic).

        Example::

            {"X": "results['node_1']", "y": "results['node_2']['target']"}
            {"default": ["results['a']", "results['b']"]}  # variadic
    """
    incoming = sorted(
        (e for e in edges if e.to_node == node_id),
        key=lambda e: e.to_input,
    )

    if not incoming:
        return {}

    # Detect nodes that use more than one distinct output port across
    # all edges in the graph.  These must be dict-qualified so the
    # generated code matches the dict output.
    from_ports: dict[str, set[str]] = {}
    for e in edges:
        from_ports.setdefault(e.from_node, set()).add(e.from_output or "default")
    multi_port_nodes = {nid for nid, ports in from_ports.items() if len(ports) > 1}

    # Also include nodes known to always emit dict output in generate_python(),
    # even when only one port is wired downstream.
    multi_port_nodes |= dict_output_nodes

    def _expr(edge: Edge) -> str:
        base = f"results['{edge.from_node}']"
        port = edge.from_output or "default"
        if edge.from_node in multi_port_nodes:
            # Dict-emitting node: always qualify with port name
            return f"{base}['{port}']"
        if port != "default":
            return f"{base}['{port}']"
        return base

    result: dict[str, str | list[str]] = {}
    for e in incoming:
        expr = _expr(e)
        if e.to_input in result:
            existing = result[e.to_input]
            if isinstance(existing, list):
                existing.append(expr)
            else:
                result[e.to_input] = [existing, expr]
        else:
            result[e.to_input] = expr
    return result
