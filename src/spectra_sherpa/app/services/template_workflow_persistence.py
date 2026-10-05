"""Shared persistence boundary for one admitted template-derived workflow."""

from __future__ import annotations

from typing import Any, Literal

from sqlalchemy.ext.asyncio import AsyncSession

from spectra_sherpa.app.lib.workflow_purpose import WorkflowPurpose
from spectra_sherpa.app.models.workflow import Workflow
from spectra_sherpa.app.models.workflow_edge import WorkflowEdge
from spectra_sherpa.app.models.workflow_node import WorkflowNode
from spectra_sherpa.app.models.workflow_template import WorkflowTemplate
from spectra_sherpa.app.services.dag.integrity import compute_workflow_hash
from spectra_sherpa.app.services.project_data_sources import (
    ensure_sheet_advisor_channel,
    sync_workflow_data_sources,
)


async def persist_template_workflow(
    *,
    session: AsyncSession,
    template: WorkflowTemplate,
    template_version: str,
    user_id: int,
    project_id: int | None,
    name: str,
    description: str,
    nodes_data: list[dict[str, Any]],
    edges_data: list[dict[str, Any]],
    canvas_state: dict[str, Any],
    sheet_order: int,
    purpose: WorkflowPurpose,
    data_origin: Literal["current", "example"] | None = None,
    data_source_display_names: dict[str, str] | None = None,
) -> tuple[Workflow, list[WorkflowNode], list[WorkflowEdge]]:
    """Persist one exact template DAG with integrity and provenance."""

    workflow = Workflow(
        user_id=user_id,
        project_id=project_id,
        name=name,
        description=description,
        status="draft",
        purpose=purpose,
        canvas_state=canvas_state,
        created_from_template_id=template.id,
        created_from_template_name=template.name,
        created_from_template_version=template_version,
        sheet_order=sheet_order,
        data_origin=data_origin,
    )
    workflow.integrity_hash = compute_workflow_hash(nodes_data, edges_data)
    session.add(workflow)
    await session.flush()

    workflow_nodes: list[WorkflowNode] = []
    for node_data in nodes_data:
        node = WorkflowNode(
            workflow_id=workflow.id,
            node_id=node_data["node_id"],
            node_type=node_data["node_type"],
            label=node_data.get("label"),
            parameters=node_data.get("parameters", {}),
            position_x=node_data.get("position_x"),
            position_y=node_data.get("position_y"),
        )
        workflow_nodes.append(node)
        session.add(node)

    workflow_edges: list[WorkflowEdge] = []
    for edge_data in edges_data:
        edge = WorkflowEdge(
            workflow_id=workflow.id,
            from_node_id=edge_data["from_node_id"],
            to_node_id=edge_data["to_node_id"],
            from_output=edge_data.get("from_output", "default"),
            to_input=edge_data.get("to_input", "default"),
        )
        workflow_edges.append(edge)
        session.add(edge)

    await sync_workflow_data_sources(
        workflow,
        session,
        workflow_nodes,
        display_names_by_node=data_source_display_names,
    )
    await ensure_sheet_advisor_channel(workflow, session, color=workflow.tab_color)
    return workflow, workflow_nodes, workflow_edges


__all__ = ["persist_template_workflow"]
