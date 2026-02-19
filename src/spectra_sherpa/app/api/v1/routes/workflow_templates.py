"""
API endpoints for workflow templates.
"""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from spectra_sherpa.app.api.deps import get_current_user, get_session
from spectra_sherpa.app.models.user import User
from spectra_sherpa.app.models.workflow import Workflow
from spectra_sherpa.app.models.workflow_edge import WorkflowEdge
from spectra_sherpa.app.models.workflow_node import WorkflowNode
from spectra_sherpa.app.models.workflow_template import WorkflowTemplate
from spectra_sherpa.app.schemas.workflows import WorkflowDetail

router = APIRouter(prefix="/workflow-templates")


# Schemas for templates
class WorkflowTemplateOut(BaseModel):
    """Schema for workflow template response."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    description: str
    category: str
    template_data: dict
    is_active: bool
    created_at: datetime
    updated_at: datetime


class WorkflowTemplateListResponse(BaseModel):
    """Schema for list of workflow templates."""

    templates: list[WorkflowTemplateOut] = Field(..., description="Available templates")
    total: int = Field(..., description="Total number of templates")


class InstantiateTemplateRequest(BaseModel):
    """Schema for instantiating a template into a workflow."""

    workflow_name: str = Field(..., description="Name for the new workflow")
    workflow_description: str | None = Field(None, description="Optional description for the new workflow")


@router.get("", response_model=WorkflowTemplateListResponse)
async def list_templates(
    category: str | None = Query(None, description="Filter by category"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    session: AsyncSession = Depends(get_session),
) -> WorkflowTemplateListResponse:
    """List all active workflow templates, optionally filtered by category."""

    # Build query
    query = select(WorkflowTemplate).where(WorkflowTemplate.is_active.is_(True))

    if category:
        query = query.where(WorkflowTemplate.category == category)

    # Get total count
    count_query = select(func.count(WorkflowTemplate.id)).where(WorkflowTemplate.is_active.is_(True))
    if category:
        count_query = count_query.where(WorkflowTemplate.category == category)

    count_result = await session.execute(count_query)
    total = count_result.scalar() or 0

    # Get templates
    query = query.order_by(WorkflowTemplate.category, WorkflowTemplate.name).limit(limit).offset(offset)
    result = await session.execute(query)
    templates = result.scalars().all()

    return WorkflowTemplateListResponse(
        templates=[WorkflowTemplateOut.model_validate(t) for t in templates],
        total=total,
    )


@router.get("/categories", response_model=list[str])
async def list_template_categories(
    session: AsyncSession = Depends(get_session),
) -> list[str]:
    """Get a list of all template categories."""
    query = (
        select(WorkflowTemplate.category)
        .where(WorkflowTemplate.is_active.is_(True))
        .distinct()
        .order_by(WorkflowTemplate.category)
    )
    result = await session.execute(query)
    categories = result.scalars().all()
    return list(categories)


@router.get("/{template_id}", response_model=WorkflowTemplateOut)
async def get_template(
    template_id: int,
    session: AsyncSession = Depends(get_session),
) -> WorkflowTemplateOut:
    """Get a specific workflow template by ID."""
    query = (
        select(WorkflowTemplate).where(WorkflowTemplate.id == template_id).where(WorkflowTemplate.is_active.is_(True))
    )
    result = await session.execute(query)
    template = result.scalar_one_or_none()

    if template is None:
        raise HTTPException(status_code=404, detail="Template not found")

    return WorkflowTemplateOut.model_validate(template)


@router.post("/{template_id}/instantiate", response_model=WorkflowDetail, status_code=201)
async def instantiate_template(
    template_id: int,
    payload: InstantiateTemplateRequest,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> WorkflowDetail:
    """
    Instantiate a template into a new workflow for the current user.

    Creates a new workflow with nodes and edges from the template.
    The user can then customize the workflow as needed.
    """
    user_id = current_user.id

    # Get template
    template_query = (
        select(WorkflowTemplate).where(WorkflowTemplate.id == template_id).where(WorkflowTemplate.is_active.is_(True))
    )
    template_result = await session.execute(template_query)
    template = template_result.scalar_one_or_none()

    if template is None:
        raise HTTPException(status_code=404, detail="Template not found")

    # Create workflow from template
    template_data = template.template_data
    workflow = Workflow(
        user_id=user_id,
        name=payload.workflow_name,
        description=payload.workflow_description or f"Created from template: {template.name}",
        status="draft",
        canvas_state=template_data.get("canvas_state", {}),
    )
    session.add(workflow)
    await session.flush()  # Get workflow ID

    # Create nodes from template
    for node_data in template_data.get("nodes", []):
        node = WorkflowNode(
            workflow_id=workflow.id,
            node_id=node_data["node_id"],
            node_type=node_data["node_type"],
            label=node_data.get("label"),
            parameters=node_data.get("parameters", {}),
            position_x=node_data.get("position_x"),
            position_y=node_data.get("position_y"),
        )
        session.add(node)

    # Create edges from template
    for edge_data in template_data.get("edges", []):
        edge = WorkflowEdge(
            workflow_id=workflow.id,
            from_node_id=edge_data["from_node_id"],
            to_node_id=edge_data["to_node_id"],
            from_output=edge_data.get("from_output", "default"),
            to_input=edge_data.get("to_input", "default"),
        )
        session.add(edge)

    await session.commit()
    await session.refresh(workflow)

    # Reload with relationships
    from sqlalchemy.orm import selectinload

    reload_query = (
        select(Workflow)
        .where(Workflow.id == workflow.id)
        .options(selectinload(Workflow.nodes), selectinload(Workflow.edges))
    )
    reload_result = await session.execute(reload_query)
    workflow = reload_result.scalar_one()

    return WorkflowDetail.model_validate(workflow)
