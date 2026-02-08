"""
API endpoints for workflow export and documentation.
"""

from __future__ import annotations

from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import PlainTextResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.deps import get_current_user, get_session
from app.core.security import check_export_allowed
from app.models.user import User
from app.models.workflow import Workflow

router = APIRouter(prefix="/workflows")


@router.get("/{workflow_id}/export/markdown", response_class=PlainTextResponse)
async def export_workflow_to_markdown(
    workflow_id: int,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> str:
    """
    Export a workflow as a comprehensive Markdown document.

    Includes workflow metadata, nodes, edges, annotations, and documentation.
    """
    if not await check_export_allowed(current_user):
        raise HTTPException(status_code=403, detail="Export not permitted for this user")

    user_id = current_user.id

    # Load workflow with all relationships
    query = (
        select(Workflow)
        .where(Workflow.id == workflow_id)
        .where(Workflow.user_id == user_id)
        .options(
            selectinload(Workflow.nodes),
            selectinload(Workflow.edges),
            selectinload(Workflow.tags),
            selectinload(Workflow.folder),
            selectinload(Workflow.versions),
        )
    )
    result = await session.execute(query)
    workflow = result.scalar_one_or_none()

    if workflow is None:
        raise HTTPException(status_code=404, detail="Workflow not found")

    # Generate markdown documentation
    md_lines = []

    # Title and metadata
    md_lines.append(f"# {workflow.name}\n")

    if workflow.description:
        md_lines.append(f"{workflow.description}\n")

    md_lines.append("## Metadata\n")
    md_lines.append(f"- **Status**: {workflow.status}")
    md_lines.append(f"- **Created**: {workflow.created_at.strftime('%Y-%m-%d %H:%M:%S')}")
    md_lines.append(f"- **Updated**: {workflow.updated_at.strftime('%Y-%m-%d %H:%M:%S')}")

    if workflow.last_executed_at:
        md_lines.append(
            f"- **Last Executed**: {workflow.last_executed_at.strftime('%Y-%m-%d %H:%M:%S')}"
        )

    if workflow.folder:
        md_lines.append(f"- **Folder**: {workflow.folder.name}")

    if workflow.tags:
        tags_str = ", ".join([tag.name for tag in workflow.tags])
        md_lines.append(f"- **Tags**: {tags_str}")

    if workflow.integrity_hash:
        md_lines.append(f"- **Integrity Hash**: `{workflow.integrity_hash}`")

    md_lines.append(f"- **Nodes**: {len(workflow.nodes)}")
    md_lines.append(f"- **Edges**: {len(workflow.edges)}")

    # Version history
    if workflow.versions:
        md_lines.append(f"\n## Version History\n")
        md_lines.append(f"Total versions: {len(workflow.versions)}\n")
        md_lines.append("| Version | Date | Description |")
        md_lines.append("|---------|------|-------------|")
        for version in workflow.versions[:5]:  # Show last 5 versions
            date_str = version.created_at.strftime("%Y-%m-%d %H:%M")
            desc = version.change_description or "No description"
            md_lines.append(f"| {version.version_number} | {date_str} | {desc} |")

    # Workflow notes
    if workflow.notes:
        md_lines.append(f"\n## Workflow Notes\n")
        md_lines.append(workflow.notes)

    # Nodes
    md_lines.append(f"\n## Workflow Nodes\n")
    md_lines.append(f"Total nodes: {len(workflow.nodes)}\n")

    # Group nodes by type
    nodes_by_type: dict[str, list] = {}
    for node in workflow.nodes:
        node_category = node.node_type.split(".")[0]  # e.g., "model" from "model.pca"
        if node_category not in nodes_by_type:
            nodes_by_type[node_category] = []
        nodes_by_type[node_category].append(node)

    for category, nodes in sorted(nodes_by_type.items()):
        md_lines.append(f"### {category.capitalize()} Nodes\n")

        for node in nodes:
            label = node.label or node.node_type
            md_lines.append(f"#### {label}\n")
            md_lines.append(f"- **Type**: `{node.node_type}`")
            md_lines.append(f"- **ID**: `{node.node_id}`")
            md_lines.append(f"- **Status**: {node.status}")

            if node.parameters:
                md_lines.append("- **Parameters**:")
                for key, value in node.parameters.items():
                    md_lines.append(f"  - `{key}`: {value}")

            if node.annotation:
                md_lines.append(f"\n**Annotation**:\n{node.annotation}\n")

            md_lines.append("")  # Blank line

    # Edges (connections)
    if workflow.edges:
        md_lines.append(f"\n## Workflow Connections\n")
        md_lines.append(f"Total connections: {len(workflow.edges)}\n")
        md_lines.append("| From | To | Ports |")
        md_lines.append("|------|-----|-------|")

        for edge in workflow.edges:
            from_label = next(
                (n.label or n.node_type for n in workflow.nodes if n.node_id == edge.from_node_id),
                edge.from_node_id,
            )
            to_label = next(
                (n.label or n.node_type for n in workflow.nodes if n.node_id == edge.to_node_id),
                edge.to_node_id,
            )
            ports = f"{edge.from_output} → {edge.to_input}"
            md_lines.append(f"| {from_label} | {to_label} | {ports} |")

    # Footer
    md_lines.append(f"\n---\n")
    md_lines.append(
        f"*Exported from Workflow Builder on {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC*"
    )

    return "\n".join(md_lines)


@router.get("/{workflow_id}/export/report-data")
async def get_report_data(
    workflow_id: int,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> dict:
    """
    Structural data for provenance report.

    Returns workflow metadata, topologically sorted nodes with parameters,
    edges, and integrity hash. Plots are generated client-side.
    """
    if not await check_export_allowed(current_user):
        raise HTTPException(status_code=403, detail="Export not permitted for this user")

    user_id = current_user.id

    query = (
        select(Workflow)
        .where(Workflow.id == workflow_id)
        .where(Workflow.user_id == user_id)
        .options(
            selectinload(Workflow.nodes),
            selectinload(Workflow.edges),
        )
    )
    result = await session.execute(query)
    workflow = result.scalar_one_or_none()

    if workflow is None:
        raise HTTPException(status_code=404, detail="Workflow not found")

    # Topological sort via Kahn's algorithm
    deps: dict[str, list[str]] = {n.node_id: [] for n in workflow.nodes}
    for edge in workflow.edges:
        if edge.to_node_id in deps:
            deps[edge.to_node_id].append(edge.from_node_id)

    in_degree = {nid: len(d) for nid, d in deps.items()}
    reverse_deps: dict[str, list[str]] = {nid: [] for nid in deps}
    for nid, dep_list in deps.items():
        for dep in dep_list:
            if dep in reverse_deps:
                reverse_deps[dep].append(nid)

    queue = [nid for nid, deg in in_degree.items() if deg == 0]
    sorted_ids: list[str] = []
    while queue:
        nid = queue.pop(0)
        sorted_ids.append(nid)
        for dependent in reverse_deps.get(nid, []):
            in_degree[dependent] -= 1
            if in_degree[dependent] == 0:
                queue.append(dependent)

    node_map = {n.node_id: n for n in workflow.nodes}
    sorted_nodes = [
        {
            "node_id": node_map[nid].node_id,
            "node_type": node_map[nid].node_type,
            "label": node_map[nid].label or node_map[nid].node_type,
            "parameters": node_map[nid].parameters or {},
            "position_x": node_map[nid].position_x,
            "position_y": node_map[nid].position_y,
        }
        for nid in sorted_ids
        if nid in node_map
    ]

    return {
        "workflow_id": workflow.id,
        "name": workflow.name,
        "description": workflow.description,
        "integrity_hash": workflow.integrity_hash,
        "created_at": workflow.created_at.isoformat() if workflow.created_at else None,
        "updated_at": workflow.updated_at.isoformat() if workflow.updated_at else None,
        "nodes": sorted_nodes,
        "edges": [
            {
                "from_node_id": e.from_node_id,
                "to_node_id": e.to_node_id,
                "from_output": e.from_output,
                "to_input": e.to_input,
            }
            for e in workflow.edges
        ],
    }
