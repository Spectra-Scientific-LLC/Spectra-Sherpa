"""
ProjectScript API endpoints — CRUD and generate-from-workflow.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from spectra_sherpa.app.api.deps import get_current_user, get_session
from spectra_sherpa.app.models.project import Project
from spectra_sherpa.app.models.project_script import ProjectScript
from spectra_sherpa.app.models.user import User
from spectra_sherpa.app.models.workflow import Workflow
from spectra_sherpa.app.schemas.project_scripts import (
    GenerateScriptRequest,
    ProjectScriptCreate,
    ProjectScriptDetail,
    ProjectScriptSummary,
    ProjectScriptUpdate,
)
from spectra_sherpa.app.services.python_export import generate_python_code

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/projects/{project_id}/scripts")


# ── Helpers ──────────────────────────────────────────────────────────

async def _get_project_for_user(
    project_id: int, user_id: int, session: AsyncSession
) -> Project:
    """Load project with ownership check."""
    result = await session.execute(
        select(Project).where(Project.id == project_id, Project.user_id == user_id)
    )
    project = result.scalar_one_or_none()
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


def _script_to_summary(script: ProjectScript) -> ProjectScriptSummary:
    """Build a ProjectScriptSummary (no code body)."""
    return ProjectScriptSummary(
        id=script.id,
        project_id=script.project_id,
        name=script.name,
        description=script.description,
        language=script.language,
        priority=script.priority,
        source_workflow_id=script.source_workflow_id,
        code_length=len(script.code),
        created_at=script.created_at,
        updated_at=script.updated_at,
    )


def _script_to_detail(script: ProjectScript) -> ProjectScriptDetail:
    """Build a ProjectScriptDetail (includes code)."""
    return ProjectScriptDetail(
        id=script.id,
        project_id=script.project_id,
        name=script.name,
        description=script.description,
        language=script.language,
        priority=script.priority,
        source_workflow_id=script.source_workflow_id,
        code_length=len(script.code),
        code=script.code,
        created_at=script.created_at,
        updated_at=script.updated_at,
    )


# ── CRUD ─────────────────────────────────────────────────────────────

@router.get("", response_model=list[ProjectScriptSummary])
async def list_scripts(
    project_id: int,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> list[ProjectScriptSummary]:
    """List scripts for a project (summaries, no code body)."""
    await _get_project_for_user(project_id, current_user.id, session)

    result = await session.execute(
        select(ProjectScript)
        .where(ProjectScript.project_id == project_id)
        .order_by(ProjectScript.priority)
    )
    return [_script_to_summary(s) for s in result.scalars().all()]


@router.post("", response_model=ProjectScriptDetail, status_code=201)
async def create_script(
    project_id: int,
    payload: ProjectScriptCreate,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> ProjectScriptDetail:
    """Create a script manually."""
    await _get_project_for_user(project_id, current_user.id, session)

    script = ProjectScript(
        project_id=project_id,
        user_id=current_user.id,
        source_workflow_id=payload.source_workflow_id,
        name=payload.name,
        description=payload.description,
        language=payload.language,
        code=payload.code,
        priority=payload.priority,
    )
    session.add(script)
    await session.commit()
    await session.refresh(script)
    logger.info("Created script '%s' (id=%s) in project %s", script.name, script.id, project_id)
    return _script_to_detail(script)


@router.post("/generate", response_model=ProjectScriptDetail, status_code=201)
async def generate_script(
    project_id: int,
    payload: GenerateScriptRequest,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> ProjectScriptDetail:
    """Generate a script from a workflow's Python export."""
    await _get_project_for_user(project_id, current_user.id, session)

    # Load workflow with nodes and edges
    result = await session.execute(
        select(Workflow)
        .where(Workflow.id == payload.workflow_id, Workflow.user_id == current_user.id)
        .options(selectinload(Workflow.nodes), selectinload(Workflow.edges))
    )
    workflow = result.scalar_one_or_none()
    if workflow is None:
        raise HTTPException(status_code=404, detail="Workflow not found")

    # Generate Python code
    try:
        code = generate_python_code(workflow)
    except Exception as exc:
        raise HTTPException(
            status_code=422,
            detail=f"Cannot export workflow: {exc}",
        )

    script = ProjectScript(
        project_id=project_id,
        user_id=current_user.id,
        source_workflow_id=workflow.id,
        name=payload.name,
        description=payload.description or f"Generated from workflow '{workflow.name}'",
        language="python",
        code=code,
        priority=payload.priority,
    )
    session.add(script)
    await session.commit()
    await session.refresh(script)
    logger.info(
        "Generated script '%s' (id=%s) from workflow '%s' (id=%s)",
        script.name, script.id, workflow.name, workflow.id,
    )
    return _script_to_detail(script)


@router.get("/{script_id}", response_model=ProjectScriptDetail)
async def get_script(
    project_id: int,
    script_id: int,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> ProjectScriptDetail:
    """Get a script with full code."""
    await _get_project_for_user(project_id, current_user.id, session)

    result = await session.execute(
        select(ProjectScript).where(
            ProjectScript.id == script_id, ProjectScript.project_id == project_id
        )
    )
    script = result.scalar_one_or_none()
    if script is None:
        raise HTTPException(status_code=404, detail="Script not found")
    return _script_to_detail(script)


@router.put("/{script_id}", response_model=ProjectScriptDetail)
async def update_script(
    project_id: int,
    script_id: int,
    payload: ProjectScriptUpdate,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> ProjectScriptDetail:
    """Update a script."""
    await _get_project_for_user(project_id, current_user.id, session)

    result = await session.execute(
        select(ProjectScript).where(
            ProjectScript.id == script_id, ProjectScript.project_id == project_id
        )
    )
    script = result.scalar_one_or_none()
    if script is None:
        raise HTTPException(status_code=404, detail="Script not found")

    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(script, key, value)

    await session.commit()
    await session.refresh(script)
    logger.info("Updated script '%s' (id=%s)", script.name, script.id)
    return _script_to_detail(script)


@router.delete("/{script_id}", status_code=204, response_class=Response)
async def delete_script(
    project_id: int,
    script_id: int,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> Response:
    """Delete a script."""
    await _get_project_for_user(project_id, current_user.id, session)

    result = await session.execute(
        select(ProjectScript).where(
            ProjectScript.id == script_id, ProjectScript.project_id == project_id
        )
    )
    script = result.scalar_one_or_none()
    if script is None:
        raise HTTPException(status_code=404, detail="Script not found")

    await session.delete(script)
    await session.commit()
    logger.info("Deleted script id=%s from project %s", script_id, project_id)
    return Response(status_code=204)
