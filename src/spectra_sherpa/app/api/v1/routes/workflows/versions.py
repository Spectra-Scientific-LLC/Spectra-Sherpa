"""
Version endpoints: list / get / restore workflow versions.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from spectra_sherpa.app.api.deps import get_current_user, get_session, require_project
from spectra_sherpa.app.models.user import User
from spectra_sherpa.app.models.workflow import Workflow
from spectra_sherpa.app.models.workflow_edge import WorkflowEdge
from spectra_sherpa.app.models.workflow_node import WorkflowNode
from spectra_sherpa.app.models.workflow_version import WorkflowVersion
from spectra_sherpa.app.schemas.workflows import (
    WorkflowDetail,
    WorkflowVersionDetail,
    WorkflowVersionListResponse,
    WorkflowVersionSummary,
)
from spectra_sherpa.app.services.dag.integrity import compute_workflow_hash
from spectra_sherpa.app.services.project_data_sources import (
    ensure_sheet_advisor_channel,
    sync_workflow_data_sources,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/workflows")


@router.get("/{workflow_id}/versions", response_model=WorkflowVersionListResponse)
async def list_workflow_versions(
    workflow_id: int,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> WorkflowVersionListResponse:
    """List all versions of a workflow for the authenticated user."""
    user_id = current_user.id

    # Verify workflow exists and user owns it
    workflow_query = select(Workflow).where(Workflow.id == workflow_id).where(Workflow.user_id == user_id)
    workflow_result = await session.execute(workflow_query)
    workflow = workflow_result.scalar_one_or_none()

    if workflow is None:
        raise HTTPException(status_code=404, detail="Workflow not found")

    # Get total count
    count_query = select(func.count(WorkflowVersion.id)).where(WorkflowVersion.workflow_id == workflow_id)
    count_result = await session.execute(count_query)
    total = count_result.scalar() or 0

    # Get versions (ordered newest first)
    query = (
        select(WorkflowVersion)
        .where(WorkflowVersion.workflow_id == workflow_id)
        .order_by(WorkflowVersion.version_number.desc())
        .limit(limit)
        .offset(offset)
    )
    result = await session.execute(query)
    versions = result.scalars().all()

    return WorkflowVersionListResponse(
        versions=[WorkflowVersionSummary.model_validate(v) for v in versions],
        total=total,
    )


@router.get("/{workflow_id}/versions/{version_id}", response_model=WorkflowVersionDetail)
async def get_workflow_version(
    workflow_id: int,
    version_id: int,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> WorkflowVersionDetail:
    """Get a specific workflow version with full snapshot for the authenticated user."""
    user_id = current_user.id

    # Verify workflow exists and user owns it
    workflow_query = select(Workflow).where(Workflow.id == workflow_id).where(Workflow.user_id == user_id)
    workflow_result = await session.execute(workflow_query)
    workflow = workflow_result.scalar_one_or_none()

    if workflow is None:
        raise HTTPException(status_code=404, detail="Workflow not found")

    # Get version
    query = (
        select(WorkflowVersion)
        .where(WorkflowVersion.id == version_id)
        .where(WorkflowVersion.workflow_id == workflow_id)
    )
    result = await session.execute(query)
    version = result.scalar_one_or_none()

    if version is None:
        raise HTTPException(status_code=404, detail="Version not found")

    return WorkflowVersionDetail.model_validate(version)


@router.post("/{workflow_id}/versions/{version_id}/restore", response_model=WorkflowDetail)
async def restore_workflow_version(
    workflow_id: int,
    version_id: int,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> WorkflowDetail:
    """Restore a workflow to a previous version for the authenticated user."""
    user_id = current_user.id

    # Verify workflow exists and user owns it (eager-load nodes/edges for ORM deletion)
    workflow_query = (
        select(Workflow)
        .where(Workflow.id == workflow_id)
        .where(Workflow.user_id == user_id)
        .options(selectinload(Workflow.nodes), selectinload(Workflow.edges))
    )
    workflow_result = await session.execute(workflow_query)
    workflow = workflow_result.scalar_one_or_none()

    if workflow is None:
        raise HTTPException(status_code=404, detail="Workflow not found")

    # Get version to restore
    version_query = (
        select(WorkflowVersion)
        .where(WorkflowVersion.id == version_id)
        .where(WorkflowVersion.workflow_id == workflow_id)
    )
    version_result = await session.execute(version_query)
    version = version_result.scalar_one_or_none()

    if version is None:
        raise HTTPException(status_code=404, detail="Version not found")

    # Restore workflow from snapshot
    snapshot = version.snapshot

    # Update workflow fields
    if "name" in snapshot:
        workflow.name = snapshot["name"]
    if "description" in snapshot:
        workflow.description = snapshot["description"]
    if "status" in snapshot:
        workflow.status = snapshot["status"]
    if "canvas_state" in snapshot:
        workflow.canvas_state = snapshot["canvas_state"]
    if "notes" in snapshot:
        workflow.notes = snapshot["notes"]
    if "technique" in snapshot:
        workflow.technique = snapshot["technique"]
    if "sample_type" in snapshot:
        workflow.sample_type = snapshot["sample_type"]

    # Clear existing nodes and edges via ORM (delete-orphan cascade handles DB deletion)
    workflow.nodes.clear()
    workflow.edges.clear()

    # Restore nodes from snapshot
    if "nodes" in snapshot:
        for node_data in snapshot["nodes"]:
            node = WorkflowNode(
                workflow_id=workflow_id,
                node_id=node_data["node_id"],
                node_type=node_data["node_type"],
                label=node_data.get("label"),
                parameters=node_data.get("parameters", {}),
                position_x=node_data.get("position_x"),
                position_y=node_data.get("position_y"),
            )
            workflow.nodes.append(node)

    # Restore edges from snapshot
    if "edges" in snapshot:
        for edge_data in snapshot["edges"]:
            edge = WorkflowEdge(
                workflow_id=workflow_id,
                from_node_id=edge_data["from_node_id"],
                to_node_id=edge_data["to_node_id"],
                from_output=edge_data.get("from_output", "default"),
                to_input=edge_data.get("to_input", "default"),
            )
            workflow.edges.append(edge)

    # Create a new version record for the restore action
    latest_version_query = select(func.max(WorkflowVersion.version_number)).where(
        WorkflowVersion.workflow_id == workflow_id
    )
    latest_version_result = await session.execute(latest_version_query)
    latest_version = latest_version_result.scalar() or 0
    new_version_number = latest_version + 1

    restore_version = WorkflowVersion(
        workflow_id=workflow_id,
        version_number=new_version_number,
        created_by=user_id,
        change_description=f"Restored from version {version.version_number}",
        snapshot=snapshot,
    )
    session.add(restore_version)

    await session.commit()

    # Reload with relationships
    reload_query = (
        select(Workflow)
        .where(Workflow.id == workflow_id)
        .options(
            selectinload(Workflow.nodes),
            selectinload(Workflow.edges),
            selectinload(Workflow.tags),
            selectinload(Workflow.folder),
        )
    )
    reload_result = await session.execute(reload_query)
    workflow = reload_result.scalar_one()

    return WorkflowDetail.model_validate(workflow)


async def _unique_version_open_name(
    source_name: str,
    version_number: int,
    project_id: int,
    user_id: int,
    session: AsyncSession,
) -> str:
    """Pick a unique sheet name for a version opened as a new sheet.

    Default form: ``"<original> (from v<n>)"``.  If a sheet with that name
    already exists in the project (e.g. the user opened the same version
    twice), append " (2)", " (3)", etc.
    """
    base_name = f"{source_name} (from v{version_number})"
    existing_result = await session.execute(
        select(Workflow.name).where(
            Workflow.user_id == user_id,
            Workflow.project_id == project_id,
        )
    )
    existing_names = set(existing_result.scalars().all())
    if base_name not in existing_names:
        return base_name
    suffix = 2
    while f"{base_name} ({suffix})" in existing_names:
        suffix += 1
    return f"{base_name} ({suffix})"


@router.post(
    "/{workflow_id}/versions/{version_id}/open-as-new-sheet",
    response_model=WorkflowDetail,
    status_code=201,
)
async def open_version_as_new_sheet(
    workflow_id: int,
    version_id: int,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> WorkflowDetail:
    """Open a workflow version as a new sheet in the same project.

    Non-destructive counterpart to ``/restore``: instead of replacing the
    current workflow's content with the snapshot, this creates a brand-new
    workflow row (a new sheet in the same project) populated from the
    snapshot.  The original workflow and all of its other versions are
    untouched.
    """
    user_id = current_user.id

    # Source workflow + ownership.
    source_query = (
        select(Workflow)
        .where(Workflow.id == workflow_id, Workflow.user_id == user_id)
        .options(selectinload(Workflow.nodes), selectinload(Workflow.edges))
    )
    source_result = await session.execute(source_query)
    source = source_result.scalar_one_or_none()
    if source is None:
        raise HTTPException(status_code=404, detail="Workflow not found")
    if source.project_id is None:
        raise HTTPException(
            status_code=400,
            detail="Only project workflows can be opened as a new sheet",
        )

    # Version exists and belongs to this workflow.
    version_query = (
        select(WorkflowVersion)
        .where(WorkflowVersion.id == version_id)
        .where(WorkflowVersion.workflow_id == workflow_id)
    )
    version_result = await session.execute(version_query)
    version = version_result.scalar_one_or_none()
    if version is None:
        raise HTTPException(status_code=404, detail="Version not found")

    await require_project(source.project_id, user_id, session)

    snapshot = version.snapshot or {}

    # Place the new sheet at the end of the workbook.
    max_order = await session.scalar(
        select(func.max(Workflow.sheet_order)).where(
            Workflow.project_id == source.project_id,
            Workflow.user_id == user_id,
        )
    )

    new_name = await _unique_version_open_name(
        source_name=snapshot.get("name") or source.name,
        version_number=version.version_number,
        project_id=source.project_id,
        user_id=user_id,
        session=session,
    )

    new_workflow = Workflow(
        user_id=user_id,
        project_id=source.project_id,
        name=new_name,
        description=snapshot.get("description") or source.description,
        status=snapshot.get("status") or source.status,
        canvas_state=snapshot.get("canvas_state") or source.canvas_state,
        notes=snapshot.get("notes"),
        technique=snapshot.get("technique") or source.technique,
        sample_type=snapshot.get("sample_type") or source.sample_type,
        tab_color=snapshot.get("tab_color") or source.tab_color,
        tab_color_override=snapshot.get("tab_color_override") or source.tab_color_override,
        color_source=snapshot.get("color_source") or source.color_source,
        created_from_template_id=source.created_from_template_id,
        created_from_template_name=source.created_from_template_name,
        created_from_template_version=source.created_from_template_version,
        sheet_order=(max_order if max_order is not None else -1) + 1,
    )
    session.add(new_workflow)
    await session.flush()

    node_dicts: list[dict] = []
    for node_data in snapshot.get("nodes") or []:
        node = WorkflowNode(
            workflow_id=new_workflow.id,
            node_id=node_data["node_id"],
            node_type=node_data["node_type"],
            label=node_data.get("label"),
            parameters=node_data.get("parameters", {}),
            annotation=node_data.get("annotation"),
            position_x=node_data.get("position_x"),
            position_y=node_data.get("position_y"),
        )
        session.add(node)
        node_dicts.append(
            {
                "node_id": node.node_id,
                "node_type": node.node_type,
                "label": node.label,
                "parameters": node.parameters,
                "annotation": node.annotation,
                "position_x": node.position_x,
                "position_y": node.position_y,
            }
        )

    edge_dicts: list[dict] = []
    for edge_data in snapshot.get("edges") or []:
        edge = WorkflowEdge(
            workflow_id=new_workflow.id,
            from_node_id=edge_data["from_node_id"],
            to_node_id=edge_data["to_node_id"],
            from_output=edge_data.get("from_output", "default"),
            to_input=edge_data.get("to_input", "default"),
        )
        session.add(edge)
        edge_dicts.append(
            {
                "from_node_id": edge.from_node_id,
                "to_node_id": edge.to_node_id,
                "from_output": edge.from_output,
                "to_input": edge.to_input,
            }
        )

    new_workflow.integrity_hash = compute_workflow_hash(nodes=node_dicts, edges=edge_dicts)

    # Reload the newly-added nodes so the data-source sync helper sees them.
    nodes_query = select(WorkflowNode).where(WorkflowNode.workflow_id == new_workflow.id)
    nodes_result = await session.execute(nodes_query)
    persisted_nodes = nodes_result.scalars().all()
    await sync_workflow_data_sources(new_workflow, session, persisted_nodes)
    await ensure_sheet_advisor_channel(new_workflow, session, new_workflow.tab_color)

    await session.commit()

    reload_query = (
        select(Workflow)
        .where(Workflow.id == new_workflow.id)
        .options(
            selectinload(Workflow.nodes),
            selectinload(Workflow.edges),
            selectinload(Workflow.tags),
            selectinload(Workflow.folder),
            selectinload(Workflow.primary_data_source),
            selectinload(Workflow.data_source_links),
            selectinload(Workflow.advisor_channels),
        )
    )
    reload_result = await session.execute(reload_query)
    new_workflow = reload_result.scalar_one()
    return WorkflowDetail.model_validate(new_workflow)
