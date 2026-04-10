"""
CRUD endpoints: list / create / get / update / delete workflows.
"""

from __future__ import annotations

import logging
from datetime import datetime

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
    WorkflowCreate,
    WorkflowDetail,
    WorkflowSummary,
    WorkflowUpdate,
)
from spectra_sherpa.app.services.dag import node_registry
from spectra_sherpa.app.services.dag.integrity import compute_workflow_hash

from ._helpers import _validate_edge_refs

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/workflows")


@router.get("", response_model=list[WorkflowSummary])
async def list_workflows(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    status: str | None = Query(None, description="Filter by status"),
    search: str | None = Query(None, description="Search in workflow name and description"),
    folder_id: int | None = Query(None, description="Filter by folder ID"),
    tag_ids: list[int] | None = Query(None, description="Filter by tag IDs (workflows with ANY of these tags)"),
    created_after: datetime | None = Query(None, description="Filter workflows created after this date"),
    created_before: datetime | None = Query(None, description="Filter workflows created before this date"),
    updated_after: datetime | None = Query(None, description="Filter workflows updated after this date"),
    updated_before: datetime | None = Query(None, description="Filter workflows updated before this date"),
    sort_by: str = Query("updated_at", description="Sort by field: name, created_at, updated_at"),
    sort_order: str = Query("desc", description="Sort order: asc or desc"),
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> list[WorkflowSummary]:
    """
    List all workflows for the authenticated user with comprehensive search and filtering.

    Supports:
    - Full-text search on name and description
    - Filter by status, folder, and tags
    - Date range filtering
    - Custom sorting
    """
    user_id = current_user.id

    # Build base query with tags and folder relationships
    # Use DISTINCT count to handle potential duplicates from joins
    query = (
        select(
            Workflow,
            func.count(func.distinct(WorkflowNode.id)).label("node_count"),
            func.count(func.distinct(WorkflowEdge.id)).label("edge_count"),
        )
        .outerjoin(WorkflowNode)
        .outerjoin(WorkflowEdge)
        .where(Workflow.user_id == user_id)
        .group_by(Workflow.id)
        .options(selectinload(Workflow.tags), selectinload(Workflow.folder))
    )

    # Apply filters
    if status:
        query = query.where(Workflow.status == status)

    if search:
        # Full-text search on name and description
        search_pattern = f"%{search}%"
        query = query.where((Workflow.name.ilike(search_pattern)) | (Workflow.description.ilike(search_pattern)))

    if folder_id is not None:
        query = query.where(Workflow.folder_id == folder_id)

    if tag_ids:
        # Filter workflows that have ANY of the specified tags
        # Use subquery to avoid duplicate rows in count aggregation
        from spectra_sherpa.app.models.workflow_tag import workflow_tag_association

        tag_subquery = (
            select(workflow_tag_association.c.workflow_id)
            .where(workflow_tag_association.c.tag_id.in_(tag_ids))
            .distinct()
        )
        query = query.where(Workflow.id.in_(tag_subquery))

    if created_after:
        query = query.where(Workflow.created_at >= created_after)

    if created_before:
        query = query.where(Workflow.created_at <= created_before)

    if updated_after:
        query = query.where(Workflow.updated_at >= updated_after)

    if updated_before:
        query = query.where(Workflow.updated_at <= updated_before)

    # Apply sorting
    sort_field = {
        "name": Workflow.name,
        "created_at": Workflow.created_at,
        "updated_at": Workflow.updated_at,
    }.get(sort_by, Workflow.updated_at)

    if sort_order == "asc":
        query = query.order_by(sort_field.asc())
    else:
        query = query.order_by(sort_field.desc())

    query = query.limit(limit).offset(offset)

    result = await session.execute(query)
    rows = result.all()

    return [
        WorkflowSummary(
            **{
                "id": workflow.id,
                "user_id": workflow.user_id,
                "folder_id": workflow.folder_id,
                "name": workflow.name,
                "description": workflow.description,
                "status": workflow.status,
                "canvas_state": workflow.canvas_state,
                "created_at": workflow.created_at,
                "updated_at": workflow.updated_at,
                "last_executed_at": workflow.last_executed_at,
                "integrity_hash": workflow.integrity_hash,
                "technique": workflow.technique,
                "sample_type": workflow.sample_type,
                "node_count": node_count or 0,
                "edge_count": edge_count or 0,
                "tags": workflow.tags,
                "folder": workflow.folder,
            }
        )
        for workflow, node_count, edge_count in rows
    ]


@router.post("", response_model=WorkflowDetail, status_code=201)
async def create_workflow(
    payload: WorkflowCreate,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> WorkflowDetail:
    """Create a new workflow for the authenticated user."""
    user_id = current_user.id

    # Validate all node types exist in the registry
    unknown_types = [n.node_type for n in payload.nodes if n.node_type not in node_registry]
    if unknown_types:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown node type(s): {', '.join(unknown_types)}",
        )

    # Validate edge references point to actual nodes
    if payload.edges:
        _validate_edge_refs(payload.nodes, payload.edges)

    # Create workflow
    workflow = Workflow(
        user_id=user_id,
        name=payload.name,
        description=payload.description,
        status=payload.status,
        canvas_state=payload.canvas_state,
        technique=payload.technique,
        sample_type=payload.sample_type,
    )
    session.add(workflow)
    await session.flush()  # Get workflow ID

    # Create nodes
    for node_data in payload.nodes:
        node = WorkflowNode(
            workflow_id=workflow.id,
            node_id=node_data.node_id,
            node_type=node_data.node_type,
            label=node_data.label,
            parameters=node_data.parameters,
            position_x=node_data.position_x,
            position_y=node_data.position_y,
        )
        session.add(node)

    # Create edges
    for edge_data in payload.edges:
        edge = WorkflowEdge(
            workflow_id=workflow.id,
            from_node_id=edge_data.from_node_id,
            to_node_id=edge_data.to_node_id,
            from_output=edge_data.from_output,
            to_input=edge_data.to_input,
        )
        session.add(edge)

    # Compute integrity hash from nodes/edges
    node_dicts = [n.model_dump() for n in payload.nodes]
    edge_dicts = [e.model_dump() for e in payload.edges]
    workflow.integrity_hash = compute_workflow_hash(
        nodes=node_dicts,
        edges=edge_dicts,
    )

    await session.commit()
    await session.refresh(workflow)

    # Reload with relationships
    query = (
        select(Workflow)
        .where(Workflow.id == workflow.id)
        .options(
            selectinload(Workflow.nodes),
            selectinload(Workflow.edges),
            selectinload(Workflow.tags),
            selectinload(Workflow.folder),
        )
    )
    result = await session.execute(query)
    workflow = result.scalar_one()

    return WorkflowDetail.model_validate(workflow)


@router.get("/{workflow_id}", response_model=WorkflowDetail)
async def get_workflow(
    workflow_id: int,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> WorkflowDetail:
    """Get a specific workflow by ID for the authenticated user."""
    user_id = current_user.id

    query = (
        select(Workflow)
        .where(Workflow.id == workflow_id)
        .where(Workflow.user_id == user_id)
        .options(
            selectinload(Workflow.nodes),
            selectinload(Workflow.edges),
            selectinload(Workflow.tags),
            selectinload(Workflow.folder),
        )
    )
    result = await session.execute(query)
    workflow = result.scalar_one_or_none()

    if workflow is None:
        raise HTTPException(status_code=404, detail="Workflow not found")

    return WorkflowDetail.model_validate(workflow)


@router.put("/{workflow_id}", response_model=WorkflowDetail)
async def update_workflow(
    workflow_id: int,
    payload: WorkflowUpdate,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> WorkflowDetail:
    """Update a workflow for the authenticated user."""
    user_id = current_user.id

    query = (
        select(Workflow)
        .where(Workflow.id == workflow_id)
        .where(Workflow.user_id == user_id)
        .options(
            selectinload(Workflow.nodes),
            selectinload(Workflow.edges),
            selectinload(Workflow.tags),
        )
    )
    result = await session.execute(query)
    workflow = result.scalar_one_or_none()

    if workflow is None:
        raise HTTPException(status_code=404, detail="Workflow not found")

    if payload.nodes is not None:
        node_types = [n.node_type for n in payload.nodes]
        unknown_types = [node_type for node_type in node_types if node_type not in node_registry]
        if unknown_types:
            raise HTTPException(
                status_code=400,
                detail=f"Unknown node type(s): {', '.join(unknown_types)}",
            )

    # Update workflow fields
    if payload.name is not None:
        workflow.name = payload.name
    if payload.description is not None:
        workflow.description = payload.description
    if payload.status is not None:
        workflow.status = payload.status
    if payload.canvas_state is not None:
        workflow.canvas_state = payload.canvas_state
    if payload.notes is not None:
        workflow.notes = payload.notes
    if payload.folder_id is not None:
        workflow.folder_id = payload.folder_id
    if payload.technique is not None:
        workflow.technique = payload.technique
    if payload.sample_type is not None:
        workflow.sample_type = payload.sample_type

    # Update tags if provided
    if payload.tag_ids is not None:
        from spectra_sherpa.app.models.workflow_tag import WorkflowTag

        # Clear existing tags
        workflow.tags = []

        # Add new tags
        if payload.tag_ids:
            tag_query = (
                select(WorkflowTag).where(WorkflowTag.id.in_(payload.tag_ids)).where(WorkflowTag.user_id == user_id)
            )
            tag_result = await session.execute(tag_query)
            tags = tag_result.scalars().all()
            workflow.tags = list(tags)

    # Update nodes if provided
    if payload.nodes is not None:
        # Clear via ORM relationship (delete-orphan cascade handles DB deletion)
        workflow.nodes.clear()

        # Create new nodes through the relationship
        for node_data in payload.nodes:
            node = WorkflowNode(
                workflow_id=workflow.id,
                node_id=node_data.node_id,
                node_type=node_data.node_type,
                label=node_data.label,
                parameters=node_data.parameters,
                position_x=node_data.position_x,
                position_y=node_data.position_y,
            )
            workflow.nodes.append(node)

    # Update edges if provided
    if payload.edges is not None:
        # Validate edge references against the node set (new or existing)
        ref_nodes = payload.nodes if payload.nodes is not None else workflow.nodes
        _validate_edge_refs(ref_nodes, payload.edges)

        # Clear via ORM relationship (delete-orphan cascade handles DB deletion)
        workflow.edges.clear()

        # Create new edges through the relationship
        for edge_data in payload.edges:
            edge = WorkflowEdge(
                workflow_id=workflow.id,
                from_node_id=edge_data.from_node_id,
                to_node_id=edge_data.to_node_id,
                from_output=edge_data.from_output,
                to_input=edge_data.to_input,
            )
            workflow.edges.append(edge)

    # Recompute integrity hash if nodes or edges changed
    if payload.nodes is not None or payload.edges is not None:
        hash_nodes = (
            [n.model_dump() for n in payload.nodes]
            if payload.nodes
            else (
                [{"node_id": n.node_id, "node_type": n.node_type, "parameters": n.parameters} for n in workflow.nodes]
                if hasattr(workflow, "nodes")
                else []
            )
        )
        hash_edges = (
            [e.model_dump() for e in payload.edges]
            if payload.edges
            else (
                [
                    {
                        "from_node_id": e.from_node_id,
                        "to_node_id": e.to_node_id,
                        "from_output": e.from_output,
                        "to_input": e.to_input,
                    }
                    for e in workflow.edges
                ]
                if hasattr(workflow, "edges")
                else []
            )
        )
        workflow.integrity_hash = compute_workflow_hash(hash_nodes, hash_edges)

    # Flush changes to database before creating snapshot
    await session.flush()

    # Reload workflow with all current relationships to capture actual state
    snapshot_query = (
        select(Workflow)
        .where(Workflow.id == workflow_id)
        .options(
            selectinload(Workflow.nodes),
            selectinload(Workflow.edges),
            selectinload(Workflow.tags),
            selectinload(Workflow.folder),
        )
    )
    snapshot_result = await session.execute(snapshot_query)
    workflow_with_relationships = snapshot_result.scalar_one()

    # Create version snapshot from actual workflow state in database
    # Get the latest version number for this workflow
    latest_version_query = select(func.max(WorkflowVersion.version_number)).where(
        WorkflowVersion.workflow_id == workflow_id
    )
    latest_version_result = await session.execute(latest_version_query)
    latest_version = latest_version_result.scalar() or 0
    new_version_number = latest_version + 1

    # Create snapshot of current workflow state from database
    snapshot = {
        "name": workflow_with_relationships.name,
        "description": workflow_with_relationships.description,
        "status": workflow_with_relationships.status,
        "canvas_state": workflow_with_relationships.canvas_state,
        "notes": workflow_with_relationships.notes,
        "integrity_hash": workflow_with_relationships.integrity_hash,
        "technique": workflow_with_relationships.technique,
        "sample_type": workflow_with_relationships.sample_type,
        "nodes": [
            {
                "node_id": n.node_id,
                "node_type": n.node_type,
                "label": n.label,
                "parameters": n.parameters,
                "annotation": n.annotation,
                "position_x": n.position_x,
                "position_y": n.position_y,
            }
            for n in workflow_with_relationships.nodes
        ],
        "edges": [
            {
                "from_node_id": e.from_node_id,
                "to_node_id": e.to_node_id,
                "from_output": e.from_output,
                "to_input": e.to_input,
            }
            for e in workflow_with_relationships.edges
        ],
    }

    version = WorkflowVersion(
        workflow_id=workflow_id,
        version_number=new_version_number,
        created_by=user_id,
        change_description=payload.change_description if hasattr(payload, "change_description") else None,
        snapshot=snapshot,
    )
    session.add(version)

    await session.commit()

    # Reload with relationships for response
    query = (
        select(Workflow)
        .where(Workflow.id == workflow_id)
        .options(
            selectinload(Workflow.nodes),
            selectinload(Workflow.edges),
            selectinload(Workflow.tags),
            selectinload(Workflow.folder),
        )
    )
    result = await session.execute(query)
    workflow = result.scalar_one()

    return WorkflowDetail.model_validate(workflow)


@router.delete("/{workflow_id}", status_code=204)
async def delete_workflow(
    workflow_id: int,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """Delete a workflow for the authenticated user."""
    user_id = current_user.id

    query = select(Workflow).where(Workflow.id == workflow_id).where(Workflow.user_id == user_id)
    result = await session.execute(query)
    workflow = result.scalar_one_or_none()

    if workflow is None:
        raise HTTPException(status_code=404, detail="Workflow not found")

    await session.delete(workflow)
    await session.commit()
