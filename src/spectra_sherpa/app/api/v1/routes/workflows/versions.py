"""
Version endpoints: list / get / restore workflow versions.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from spectra_sherpa.app.api.deps import get_current_user, get_session
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
