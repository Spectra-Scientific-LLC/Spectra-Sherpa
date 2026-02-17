"""
Project API endpoints — CRUD, link/unlink, versioning, and export/import.
"""

from __future__ import annotations

import io
import json
import logging
import zipfile
from datetime import datetime

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import Response, StreamingResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from spectra_sherpa.app.api.deps import demo_guard, get_current_user, get_session
from spectra_sherpa.app.models.experiment import Experiment
from spectra_sherpa.app.models.experiment_file import ExperimentFile
from spectra_sherpa.app.models.project import Project, ProjectVersion
from spectra_sherpa.app.models.project_script import ProjectScript
from spectra_sherpa.app.models.user import User
from spectra_sherpa.app.models.workflow import Workflow
from spectra_sherpa.app.models.workflow_edge import WorkflowEdge
from spectra_sherpa.app.models.workflow_node import WorkflowNode
from spectra_sherpa.app.schemas.projects import (
    ExperimentBrief,
    ProjectCreate,
    ProjectDetail,
    ProjectSummary,
    ProjectUpdate,
    ProjectVersionDetail,
    ProjectVersionListResponse,
    ProjectVersionSummary,
    SaveProjectRequest,
    ScriptBrief,
    WorkflowBrief,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/projects")


# ── Helpers ──────────────────────────────────────────────────────────

async def _get_project_for_user(
    project_id: int, user_id: int, session: AsyncSession
) -> Project:
    """Load project with ownership check."""
    query = select(Project).where(
        Project.id == project_id, Project.user_id == user_id
    )
    result = await session.execute(query)
    project = result.scalar_one_or_none()
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


async def _project_to_summary(project: Project, session: AsyncSession) -> ProjectSummary:
    """Build a ProjectSummary with aggregated counts."""
    exp_count = await session.scalar(
        select(func.count(Experiment.id)).where(Experiment.project_id == project.id)
    )
    wf_count = await session.scalar(
        select(func.count(Workflow.id)).where(Workflow.project_id == project.id)
    )
    child_count = await session.scalar(
        select(func.count(Project.id)).where(Project.parent_id == project.id)
    )
    script_count = await session.scalar(
        select(func.count(ProjectScript.id)).where(ProjectScript.project_id == project.id)
    )
    ver_count = await session.scalar(
        select(func.count(ProjectVersion.id)).where(ProjectVersion.project_id == project.id)
    )
    return ProjectSummary(
        id=project.id,
        name=project.name,
        description=project.description,
        parent_id=project.parent_id,
        technique=project.technique,
        sample_type=project.sample_type,
        experiment_count=exp_count or 0,
        workflow_count=wf_count or 0,
        script_count=script_count or 0,
        children_count=child_count or 0,
        version_count=ver_count or 0,
        created_at=project.created_at,
        updated_at=project.updated_at,
    )


async def _project_to_detail(project: Project, session: AsyncSession) -> ProjectDetail:
    """Build a full ProjectDetail with related objects."""
    summary = await _project_to_summary(project, session)

    # Experiments
    exp_result = await session.execute(
        select(Experiment)
        .where(Experiment.project_id == project.id)
        .options(selectinload(Experiment.files))
    )
    experiments = [
        ExperimentBrief(
            id=e.id, name=e.name, description=e.description,
            file_count=len(e.files),
        )
        for e in exp_result.scalars().all()
    ]

    # Workflows
    wf_result = await session.execute(
        select(Workflow).where(Workflow.project_id == project.id)
    )
    workflows = [
        WorkflowBrief(
            id=w.id, name=w.name, description=w.description,
            status=w.status, integrity_hash=w.integrity_hash,
        )
        for w in wf_result.scalars().all()
    ]

    # Scripts
    script_result = await session.execute(
        select(ProjectScript)
        .where(ProjectScript.project_id == project.id)
        .order_by(ProjectScript.priority)
    )
    scripts = [
        ScriptBrief(
            id=s.id, name=s.name, description=s.description,
            language=s.language, priority=s.priority,
            source_workflow_id=s.source_workflow_id,
            code_length=len(s.code),
        )
        for s in script_result.scalars().all()
    ]

    # Children
    child_result = await session.execute(
        select(Project).where(Project.parent_id == project.id)
    )
    children = []
    for c in child_result.scalars().all():
        children.append(await _project_to_summary(c, session))

    return ProjectDetail(
        **summary.model_dump(),
        metadata=project.metadata_ or {},
        experiments=experiments,
        workflows=workflows,
        scripts=scripts,
        children=children,
    )


# ── CRUD ─────────────────────────────────────────────────────────────

@router.post("", response_model=ProjectDetail, status_code=201)
async def create_project(
    payload: ProjectCreate,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> ProjectDetail:
    """Create a new project (optionally under a parent)."""
    if payload.parent_id is not None:
        await _get_project_for_user(payload.parent_id, current_user.id, session)

    project = Project(
        user_id=current_user.id,
        parent_id=payload.parent_id,
        name=payload.name,
        description=payload.description,
        metadata_=payload.metadata,
        technique=payload.technique,
        sample_type=payload.sample_type,
    )
    session.add(project)
    await session.commit()
    await session.refresh(project)
    logger.info("Created project '%s' (id=%s)", project.name, project.id)
    return await _project_to_detail(project, session)


@router.get("", response_model=list[ProjectSummary])
async def list_projects(
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> list[ProjectSummary]:
    """List user's top-level projects (parent_id IS NULL)."""
    query = (
        select(Project)
        .where(Project.user_id == current_user.id, Project.parent_id.is_(None))
        .order_by(Project.updated_at.desc())
    )
    result = await session.execute(query)
    projects = result.scalars().all()
    return [await _project_to_summary(p, session) for p in projects]


@router.get("/{project_id}", response_model=ProjectDetail)
async def get_project(
    project_id: int,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> ProjectDetail:
    """Get full project detail (experiments, workflows, children)."""
    project = await _get_project_for_user(project_id, current_user.id, session)
    return await _project_to_detail(project, session)


@router.put("/{project_id}", response_model=ProjectDetail)
async def update_project(
    project_id: int,
    payload: ProjectUpdate,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> ProjectDetail:
    """Update project metadata."""
    project = await _get_project_for_user(project_id, current_user.id, session)

    if payload.parent_id is not None and payload.parent_id != project.parent_id:
        if payload.parent_id == project.id:
            raise HTTPException(status_code=400, detail="Cannot set project as its own parent")
        await _get_project_for_user(payload.parent_id, current_user.id, session)

    update_data = payload.model_dump(exclude_unset=True)
    if "metadata" in update_data:
        update_data["metadata_"] = update_data.pop("metadata")
    for key, value in update_data.items():
        setattr(project, key, value)

    await session.commit()
    await session.refresh(project)
    logger.info("Updated project '%s' (id=%s)", project.name, project.id)
    return await _project_to_detail(project, session)


@router.delete("/{project_id}", status_code=204, response_class=Response)
async def delete_project(
    project_id: int,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> Response:
    """Delete project (CASCADE children + versions, SET NULL experiments/workflows)."""
    project = await _get_project_for_user(project_id, current_user.id, session)

    # SET NULL on linked experiments and workflows before cascade delete
    await session.execute(
        select(Experiment)
        .where(Experiment.project_id == project_id)
        .execution_options(synchronize_session="fetch")
    )
    for exp in (await session.execute(
        select(Experiment).where(Experiment.project_id == project_id)
    )).scalars().all():
        exp.project_id = None

    for wf in (await session.execute(
        select(Workflow).where(Workflow.project_id == project_id)
    )).scalars().all():
        wf.project_id = None

    await session.delete(project)
    await session.commit()
    logger.info("Deleted project id=%s", project_id)
    return Response(status_code=204)


# ── Link / Unlink ────────────────────────────────────────────────────

@router.post("/{project_id}/experiments/{experiment_id}", response_model=ProjectDetail)
async def link_experiment(
    project_id: int,
    experiment_id: int,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> ProjectDetail:
    """Link an experiment to this project."""
    project = await _get_project_for_user(project_id, current_user.id, session)
    result = await session.execute(
        select(Experiment).where(
            Experiment.id == experiment_id, Experiment.user_id == current_user.id
        )
    )
    experiment = result.scalar_one_or_none()
    if experiment is None:
        raise HTTPException(status_code=404, detail="Experiment not found")

    experiment.project_id = project_id
    await session.commit()
    logger.info("Linked experiment %s to project %s", experiment_id, project_id)
    return await _project_to_detail(project, session)


@router.delete("/{project_id}/experiments/{experiment_id}", response_model=ProjectDetail)
async def unlink_experiment(
    project_id: int,
    experiment_id: int,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> ProjectDetail:
    """Unlink an experiment from this project."""
    project = await _get_project_for_user(project_id, current_user.id, session)
    result = await session.execute(
        select(Experiment).where(
            Experiment.id == experiment_id,
            Experiment.project_id == project_id,
            Experiment.user_id == current_user.id,
        )
    )
    experiment = result.scalar_one_or_none()
    if experiment is None:
        raise HTTPException(status_code=404, detail="Experiment not linked to this project")

    experiment.project_id = None
    await session.commit()
    logger.info("Unlinked experiment %s from project %s", experiment_id, project_id)
    return await _project_to_detail(project, session)


@router.post("/{project_id}/workflows/{workflow_id}", response_model=ProjectDetail)
async def link_workflow(
    project_id: int,
    workflow_id: int,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> ProjectDetail:
    """Link a workflow to this project."""
    project = await _get_project_for_user(project_id, current_user.id, session)
    result = await session.execute(
        select(Workflow).where(
            Workflow.id == workflow_id, Workflow.user_id == current_user.id
        )
    )
    workflow = result.scalar_one_or_none()
    if workflow is None:
        raise HTTPException(status_code=404, detail="Workflow not found")

    workflow.project_id = project_id
    await session.commit()
    logger.info("Linked workflow %s to project %s", workflow_id, project_id)
    return await _project_to_detail(project, session)


@router.delete("/{project_id}/workflows/{workflow_id}", response_model=ProjectDetail)
async def unlink_workflow(
    project_id: int,
    workflow_id: int,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> ProjectDetail:
    """Unlink a workflow from this project."""
    project = await _get_project_for_user(project_id, current_user.id, session)
    result = await session.execute(
        select(Workflow).where(
            Workflow.id == workflow_id,
            Workflow.project_id == project_id,
            Workflow.user_id == current_user.id,
        )
    )
    workflow = result.scalar_one_or_none()
    if workflow is None:
        raise HTTPException(status_code=404, detail="Workflow not linked to this project")

    workflow.project_id = None
    await session.commit()
    logger.info("Unlinked workflow %s from project %s", workflow_id, project_id)
    return await _project_to_detail(project, session)


# ── Versioning / Save All ────────────────────────────────────────────

async def _build_snapshot(project: Project, session: AsyncSession) -> dict:
    """Build a recursive snapshot of the project tree."""
    # Experiments with files
    exp_result = await session.execute(
        select(Experiment)
        .where(Experiment.project_id == project.id)
        .options(selectinload(Experiment.files))
    )
    experiments_snap = []
    for exp in exp_result.scalars().all():
        experiments_snap.append({
            "id": exp.id,
            "name": exp.name,
            "description": exp.description,
            "file_count": len(exp.files),
            "files": [
                {"id": f.id, "file_path": f.file_path, "stage": f.stage,
                 "file_type": f.file_type}
                for f in exp.files
            ],
        })

    # Workflows with nodes and edges
    wf_result = await session.execute(
        select(Workflow)
        .where(Workflow.project_id == project.id)
        .options(selectinload(Workflow.nodes), selectinload(Workflow.edges))
    )
    workflows_snap = []
    for wf in wf_result.scalars().all():
        workflows_snap.append({
            "id": wf.id,
            "name": wf.name,
            "description": wf.description,
            "status": wf.status,
            "integrity_hash": wf.integrity_hash,
            "technique": wf.technique,
            "sample_type": wf.sample_type,
            "nodes": [
                {
                    "node_id": n.node_id,
                    "node_type": n.node_type,
                    "label": n.label,
                    "parameters": n.parameters,
                    "position_x": n.position_x,
                    "position_y": n.position_y,
                }
                for n in wf.nodes
            ],
            "edges": [
                {
                    "from_node_id": e.from_node_id,
                    "to_node_id": e.to_node_id,
                    "from_output": e.from_output,
                    "to_input": e.to_input,
                }
                for e in wf.edges
            ],
        })

    # Scripts
    script_result = await session.execute(
        select(ProjectScript)
        .where(ProjectScript.project_id == project.id)
        .order_by(ProjectScript.priority)
    )
    scripts_snap = []
    for s in script_result.scalars().all():
        scripts_snap.append({
            "id": s.id,
            "name": s.name,
            "description": s.description,
            "language": s.language,
            "code": s.code,
            "priority": s.priority,
            "source_workflow_id": s.source_workflow_id,
        })

    # Recursive children
    child_result = await session.execute(
        select(Project).where(Project.parent_id == project.id)
    )
    children_snap = []
    for child in child_result.scalars().all():
        children_snap.append(await _build_snapshot(child, session))

    return {
        "id": project.id,
        "name": project.name,
        "description": project.description,
        "metadata": project.metadata_ or {},
        "technique": project.technique,
        "sample_type": project.sample_type,
        "experiments": experiments_snap,
        "workflows": workflows_snap,
        "scripts": scripts_snap,
        "children": children_snap,
    }


@router.post("/{project_id}/save", response_model=ProjectVersionSummary, status_code=201)
async def save_project(
    project_id: int,
    payload: SaveProjectRequest,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> ProjectVersionSummary:
    """'Save All' — snapshot current project state as a new version."""
    project = await _get_project_for_user(project_id, current_user.id, session)

    # Determine next version number
    max_ver = await session.scalar(
        select(func.max(ProjectVersion.version_number))
        .where(ProjectVersion.project_id == project_id)
    )
    next_ver = (max_ver or 0) + 1

    snapshot = await _build_snapshot(project, session)

    version = ProjectVersion(
        project_id=project_id,
        version_number=next_ver,
        created_by=current_user.id,
        change_description=payload.change_description,
        snapshot=snapshot,
        include_raw_data=payload.include_raw_data,
    )
    session.add(version)
    await session.commit()
    await session.refresh(version)

    logger.info(
        "Saved project '%s' version %s (id=%s)", project.name, next_ver, version.id
    )
    return ProjectVersionSummary.model_validate(version)


@router.get("/{project_id}/versions", response_model=ProjectVersionListResponse)
async def list_versions(
    project_id: int,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> ProjectVersionListResponse:
    """List version history for a project."""
    await _get_project_for_user(project_id, current_user.id, session)

    query = (
        select(ProjectVersion)
        .where(ProjectVersion.project_id == project_id)
        .order_by(ProjectVersion.version_number.desc())
    )
    result = await session.execute(query)
    versions = list(result.scalars().all())

    return ProjectVersionListResponse(
        versions=[ProjectVersionSummary.model_validate(v) for v in versions],
        total=len(versions),
    )


@router.get("/{project_id}/versions/{version_id}", response_model=ProjectVersionDetail)
async def get_version(
    project_id: int,
    version_id: int,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> ProjectVersionDetail:
    """Get a specific version with full snapshot."""
    await _get_project_for_user(project_id, current_user.id, session)

    query = select(ProjectVersion).where(
        ProjectVersion.id == version_id, ProjectVersion.project_id == project_id
    )
    result = await session.execute(query)
    version = result.scalar_one_or_none()
    if version is None:
        raise HTTPException(status_code=404, detail="Version not found")

    return ProjectVersionDetail.model_validate(version)


# ── Export / Import ──────────────────────────────────────────────────

@router.get("/{project_id}/export")
async def export_project(
    project_id: int,
    version_id: int | None = None,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> StreamingResponse:
    """Download project as a .spectrapy archive (ZIP with project.json)."""
    project = await _get_project_for_user(project_id, current_user.id, session)

    if version_id:
        query = select(ProjectVersion).where(
            ProjectVersion.id == version_id, ProjectVersion.project_id == project_id
        )
        result = await session.execute(query)
        version = result.scalar_one_or_none()
        if version is None:
            raise HTTPException(status_code=404, detail="Version not found")
        snapshot = version.snapshot
    else:
        snapshot = await _build_snapshot(project, session)

    # Build ZIP archive
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("project.json", json.dumps(snapshot, indent=2, default=str))

    buf.seek(0)
    safe_name = project.name.replace(" ", "_").replace("/", "_")
    return StreamingResponse(
        buf,
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="{safe_name}.spectrapy"'
        },
    )


@router.post("/import", response_model=ProjectDetail, status_code=201, dependencies=[Depends(demo_guard("project_import"))])
async def import_project(
    file: UploadFile = File(...),
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> ProjectDetail:
    """Import a .spectrapy archive to create a new project."""
    content = await file.read()
    try:
        with zipfile.ZipFile(io.BytesIO(content), "r") as zf:
            project_json = json.loads(zf.read("project.json"))
    except (zipfile.BadZipFile, KeyError, json.JSONDecodeError) as exc:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid .spectrapy archive: {exc}",
        )

    # Create root project from snapshot
    project = Project(
        user_id=current_user.id,
        name=project_json.get("name", "Imported Project"),
        description=project_json.get("description"),
        metadata_=project_json.get("metadata", {}),
        technique=project_json.get("technique"),
        sample_type=project_json.get("sample_type"),
    )
    session.add(project)
    await session.commit()
    await session.refresh(project)

    # Recreate scripts from snapshot
    for s_data in project_json.get("scripts", []):
        script = ProjectScript(
            project_id=project.id,
            user_id=current_user.id,
            name=s_data.get("name", "Imported Script"),
            description=s_data.get("description"),
            language=s_data.get("language", "python"),
            code=s_data.get("code", ""),
            priority=s_data.get("priority", 50.0),
        )
        session.add(script)
    await session.commit()

    # Save import snapshot as version 1
    version = ProjectVersion(
        project_id=project.id,
        version_number=1,
        created_by=current_user.id,
        change_description="Imported from .spectrapy archive",
        snapshot=project_json,
        include_raw_data=False,
    )
    session.add(version)
    await session.commit()

    logger.info("Imported project '%s' (id=%s)", project.name, project.id)
    return await _project_to_detail(project, session)
