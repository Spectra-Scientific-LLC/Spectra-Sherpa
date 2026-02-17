"""
Built-in workflow inspection tools.

These tools let the LLM inspect and validate the user's current
workflow state without requiring raw data egress.
"""
from __future__ import annotations

from typing import Any, Optional

from spectra_sherpa.app.services.tools.registry import register_tool
from spectra_sherpa.app.services.tools.schemas import ToolCategory


# ---------------------------------------------------------------------------
# get_workflow_summary
# ---------------------------------------------------------------------------

@register_tool(
    "get_workflow_summary",
    "Get a human-readable summary of a saved workflow's DAG structure "
    "(nodes, edges, parameters) from the database.",
    category=ToolCategory.workflow,
    parameters={
        "type": "object",
        "properties": {
            "workflow_id": {
                "type": "integer",
                "description": "Database ID of the workflow to inspect",
            },
        },
        "required": ["workflow_id"],
    },
    requires_session=True,
    requires_user=True,
)
async def get_workflow_summary(
    workflow_id: int,
    session: Any = None,
    user: Any = None,
) -> dict[str, Any]:
    """Load a workflow and return its structure as a compact dict."""
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload

    from spectra_sherpa.app.models.workflow import Workflow

    result = await session.execute(
        select(Workflow)
        .options(selectinload(Workflow.nodes), selectinload(Workflow.edges))
        .where(Workflow.id == workflow_id, Workflow.user_id == user.id)
    )
    wf = result.scalar_one_or_none()
    if wf is None:
        return {"error": f"Workflow {workflow_id} not found or access denied"}

    nodes = []
    for n in wf.nodes:
        nodes.append(
            {
                "node_id": n.node_id,
                "node_type": n.node_type,
                "label": n.label,
                "parameters": n.parameters or {},
            }
        )

    edges = []
    for e in wf.edges:
        edges.append(
            {
                "from": e.from_node_id,
                "to": e.to_node_id,
            }
        )

    return {
        "workflow_id": wf.id,
        "name": wf.name,
        "node_count": len(nodes),
        "edge_count": len(edges),
        "nodes": nodes,
        "edges": edges,
    }


# ---------------------------------------------------------------------------
# validate_workflow
# ---------------------------------------------------------------------------

@register_tool(
    "validate_workflow",
    "Validate a workflow DAG for common issues: disconnected nodes, "
    "type mismatches, cycles, missing required parameters.",
    category=ToolCategory.workflow,
    parameters={
        "type": "object",
        "properties": {
            "nodes": {
                "type": "array",
                "description": "Array of node objects with node_id, node_type, parameters",
                "items": {
                    "type": "object",
                    "properties": {
                        "node_id": {"type": "string"},
                        "node_type": {"type": "string"},
                        "parameters": {"type": "object"},
                    },
                    "required": ["node_id", "node_type"],
                },
            },
            "edges": {
                "type": "array",
                "description": "Array of edge objects with from_node_id, to_node_id",
                "items": {
                    "type": "object",
                    "properties": {
                        "from_node_id": {"type": "string"},
                        "to_node_id": {"type": "string"},
                    },
                    "required": ["from_node_id", "to_node_id"],
                },
            },
        },
        "required": ["nodes", "edges"],
    },
)
def validate_workflow(
    nodes: list[dict[str, Any]],
    edges: list[dict[str, Any]],
) -> dict[str, Any]:
    """Run structural validation on a workflow graph."""
    from spectra_sherpa.app.services.dag.node_base import node_registry

    issues: list[dict[str, str]] = []
    node_ids = {n["node_id"] for n in nodes}

    # Check for unknown node types
    for n in nodes:
        if n["node_type"] not in node_registry._nodes:
            issues.append(
                {
                    "severity": "error",
                    "node_id": n["node_id"],
                    "message": f"Unknown node type: {n['node_type']}",
                }
            )

    # Check for missing required parameters
    for n in nodes:
        node_cls = node_registry._nodes.get(n["node_type"])
        if node_cls is None:
            continue
        params = n.get("parameters", {})
        for p in node_cls.metadata.parameters:
            if p.required and p.name not in params and p.default is None:
                issues.append(
                    {
                        "severity": "warning",
                        "node_id": n["node_id"],
                        "message": f"Missing required parameter: {p.name}",
                    }
                )

    # Check for dangling edge references
    for e in edges:
        if e["from_node_id"] not in node_ids:
            issues.append(
                {
                    "severity": "error",
                    "node_id": e["from_node_id"],
                    "message": f"Edge source not in node list: {e['from_node_id']}",
                }
            )
        if e["to_node_id"] not in node_ids:
            issues.append(
                {
                    "severity": "error",
                    "node_id": e["to_node_id"],
                    "message": f"Edge target not in node list: {e['to_node_id']}",
                }
            )

    # Check for disconnected nodes (no incoming or outgoing edges)
    connected = set()
    for e in edges:
        connected.add(e["from_node_id"])
        connected.add(e["to_node_id"])
    for n in nodes:
        if n["node_id"] not in connected and len(nodes) > 1:
            # Data source nodes are allowed to have no incoming edges
            if not n["node_type"].startswith("data."):
                issues.append(
                    {
                        "severity": "warning",
                        "node_id": n["node_id"],
                        "message": "Node is disconnected from the graph",
                    }
                )

    # Simple cycle detection (DFS)
    adj: dict[str, list[str]] = {n["node_id"]: [] for n in nodes}
    for e in edges:
        if e["from_node_id"] in adj:
            adj[e["from_node_id"]].append(e["to_node_id"])

    GRAY, BLACK = 1, 2
    color: dict[str, int] = {}

    def has_cycle(node: str) -> bool:
        color[node] = GRAY
        for neighbor in adj.get(node, []):
            c = color.get(neighbor, 0)
            if c == GRAY:
                return True
            if c == 0 and has_cycle(neighbor):
                return True
        color[node] = BLACK
        return False

    has_cycles = any(
        has_cycle(nid) for nid in adj if color.get(nid, 0) == 0
    )
    if has_cycles:
        issues.append(
            {
                "severity": "error",
                "node_id": "",
                "message": "Workflow contains a cycle — DAG execution requires acyclic graphs",
            }
        )

    return {
        "valid": all(i["severity"] != "error" for i in issues),
        "issue_count": len(issues),
        "issues": issues,
    }


# ---------------------------------------------------------------------------
# list_workflows
# ---------------------------------------------------------------------------

@register_tool(
    "list_workflows",
    "List the user's saved workflows with ID, name, and node count.",
    category=ToolCategory.workflow,
    parameters={
        "type": "object",
        "properties": {
            "limit": {
                "type": "integer",
                "description": "Max number of workflows to return (default 20)",
            },
        },
        "required": [],
    },
    requires_session=True,
    requires_user=True,
)
async def list_workflows(
    limit: int = 20,
    session: Any = None,
    user: Any = None,
) -> list[dict[str, Any]]:
    """Return a compact list of user's workflows."""
    from sqlalchemy import func, select

    from spectra_sherpa.app.models.workflow import Workflow, WorkflowNode

    # Subquery for node count
    node_count = (
        select(func.count(WorkflowNode.id))
        .where(WorkflowNode.workflow_id == Workflow.id)
        .correlate(Workflow)
        .scalar_subquery()
    )

    result = await session.execute(
        select(
            Workflow.id,
            Workflow.name,
            Workflow.created_at,
            Workflow.updated_at,
            node_count.label("node_count"),
        )
        .where(Workflow.user_id == user.id)
        .order_by(Workflow.updated_at.desc())
        .limit(limit)
    )

    return [
        {
            "workflow_id": row.id,
            "name": row.name,
            "node_count": row.node_count or 0,
            "updated_at": row.updated_at.isoformat() if row.updated_at else None,
        }
        for row in result
    ]
