"""
Project API endpoints — CRUD, link/unlink, versioning, and export/import.
"""

from __future__ import annotations

import io
import json
import logging
import zipfile
from typing import Any

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import Response, StreamingResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from spectra_sherpa.app.api.deps import demo_guard, get_current_user, get_session, require_project
from spectra_sherpa.app.core.config import settings
from spectra_sherpa.app.models.advisor_channel import AdvisorChannel
from spectra_sherpa.app.models.experiment import Experiment
from spectra_sherpa.app.models.model_artifact import ModelArtifact
from spectra_sherpa.app.models.project import Project, ProjectVersion
from spectra_sherpa.app.models.project_data_source import ProjectDataSource
from spectra_sherpa.app.models.project_script import ProjectScript
from spectra_sherpa.app.models.user import User
from spectra_sherpa.app.models.workflow import Workflow
from spectra_sherpa.app.schemas.projects import (
    AdvisorChannelOut,
    AdvisorChannelUpdate,
    ExperimentBrief,
    ModelBrief,
    ProjectCreate,
    ProjectDataSourceCreate,
    ProjectDataSourceOut,
    ProjectDataSourceUpdate,
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
from spectra_sherpa.app.services.project_data_sources import (
    effective_workflow_tab_color,
    ensure_project_advisor_channel,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/projects")


# ── Helpers ──────────────────────────────────────────────────────────


def _safe_parse_metrics(metrics_json: str | None) -> dict | None:
    """Parse a JSON metrics blob, returning None on missing or malformed input."""
    if not metrics_json:
        return None
    try:
        return json.loads(metrics_json)
    except (json.JSONDecodeError, TypeError):
        return None


async def _read_upload_with_limit(file: UploadFile, *, max_bytes: int, chunk_size: int = 1024 * 1024) -> bytes:
    """Read an upload deterministically until EOF or size limit is exceeded."""
    chunks: list[bytes] = []
    total = 0
    limit = max_bytes + 1

    while total <= max_bytes:
        to_read = min(chunk_size, limit - total)
        if to_read <= 0:
            break
        chunk = await file.read(to_read)
        if not chunk:
            break
        chunks.append(chunk)
        total += len(chunk)

    return b"".join(chunks)


async def _project_to_summary(project: Project, session: AsyncSession) -> ProjectSummary:
    """Build a ProjectSummary with aggregated counts."""
    exp_count = await session.scalar(select(func.count(Experiment.id)).where(Experiment.project_id == project.id))
    wf_count = await session.scalar(select(func.count(Workflow.id)).where(Workflow.project_id == project.id))
    child_count = await session.scalar(select(func.count(Project.id)).where(Project.parent_id == project.id))
    script_count = await session.scalar(
        select(func.count(ProjectScript.id)).where(ProjectScript.project_id == project.id)
    )
    model_count = await session.scalar(
        select(func.count(ModelArtifact.id)).where(
            ModelArtifact.project_id == project.id, ModelArtifact.is_active == True  # noqa: E712
        )
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
        model_count=model_count or 0,
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
        select(Experiment).where(Experiment.project_id == project.id).options(selectinload(Experiment.files))
    )
    experiments = [
        ExperimentBrief(
            id=e.id,
            name=e.name,
            description=e.description,
            file_count=len(e.files),
        )
        for e in exp_result.scalars().all()
    ]

    # Project data sources
    data_source_result = await session.execute(
        select(ProjectDataSource)
        .where(ProjectDataSource.project_id == project.id)
        .order_by(ProjectDataSource.sort_order.asc(), ProjectDataSource.display_name.asc())
    )
    data_sources = [
        ProjectDataSourceOut(
            id=data_source.id,
            project_id=data_source.project_id,
            display_name=data_source.display_name,
            source_type=data_source.source_type,
            source_ref=data_source.source_ref,
            fingerprint=data_source.fingerprint,
            color=data_source.color,
            metadata=data_source.metadata_ or {},
            sort_order=data_source.sort_order,
            created_at=data_source.created_at,
            updated_at=data_source.updated_at,
        )
        for data_source in data_source_result.scalars().all()
    ]

    # Workflows
    wf_result = await session.execute(
        select(Workflow)
        .where(Workflow.project_id == project.id)
        .options(
            selectinload(Workflow.primary_data_source),
            selectinload(Workflow.data_source_links),
            selectinload(Workflow.advisor_channels),
        )
        .order_by(Workflow.sheet_order.asc(), Workflow.updated_at.desc())
    )
    workflow_models = list(wf_result.scalars().all())
    workflow_name_by_id = {workflow.id: workflow.name for workflow in workflow_models}
    workflows = [
        WorkflowBrief(
            id=w.id,
            name=w.name,
            description=w.description,
            status=w.status,
            integrity_hash=w.integrity_hash,
            tab_color=effective_workflow_tab_color(w),
            sheet_order=w.sheet_order,
            primary_data_source_id=w.primary_data_source_id,
            data_source_ids=w.data_source_ids,
            color_source=w.color_source,
            tab_color_override=w.tab_color_override,
            advisor_channel_id=w.advisor_channel_id,
            created_from_template_name=w.created_from_template_name,
            created_from_template_version=w.created_from_template_version,
            created_from_workflow_id=w.created_from_workflow_id,
            created_from_workflow_name=workflow_name_by_id.get(w.created_from_workflow_id),
        )
        for w in workflow_models
    ]

    advisor_result = await session.execute(
        select(AdvisorChannel)
        .where(AdvisorChannel.project_id == project.id)
        .order_by(AdvisorChannel.channel_type.asc(), AdvisorChannel.updated_at.desc())
    )
    advisor_channels = [AdvisorChannelOut.model_validate(channel) for channel in advisor_result.scalars().all()]

    # Scripts
    script_result = await session.execute(
        select(ProjectScript).where(ProjectScript.project_id == project.id).order_by(ProjectScript.priority)
    )
    scripts = [
        ScriptBrief(
            id=s.id,
            name=s.name,
            description=s.description,
            language=s.language,
            priority=s.priority,
            source_workflow_id=s.source_workflow_id,
            code_length=len(s.code),
        )
        for s in script_result.scalars().all()
    ]

    # Models
    model_result = await session.execute(
        select(ModelArtifact).where(
            ModelArtifact.project_id == project.id, ModelArtifact.is_active == True  # noqa: E712
        )
    )
    models = []
    for m in model_result.scalars().all():
        metrics = _safe_parse_metrics(m.metrics_json)
        models.append(
            ModelBrief(
                artifact_uid=m.artifact_uid,
                name=m.name,
                model_type=m.model_type,
                n_features=m.n_features,
                n_components=m.n_components,
                metrics=metrics,
                created_at=m.created_at,
            )
        )

    # Children
    child_result = await session.execute(select(Project).where(Project.parent_id == project.id))
    children = []
    for c in child_result.scalars().all():
        children.append(await _project_to_summary(c, session))

    return ProjectDetail(
        **summary.model_dump(),
        metadata=project.metadata_ or {},
        experiments=experiments,
        data_sources=data_sources,
        workflows=workflows,
        advisor_channels=advisor_channels,
        scripts=scripts,
        models=models,
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
        await require_project(payload.parent_id, current_user.id, session)

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
    await session.flush()
    await ensure_project_advisor_channel(project.id, project.name, session)

    # ISO 17025 audit — project.created (Phase 3 coverage expansion).
    from spectra_sherpa.app.services.audit import audit_emitter

    audit_emitter.emit(
        session=session,
        action="project.created",
        target_type="Project",
        target_id=project.id,
        after={
            "name": project.name,
            "parent_id": project.parent_id,
            "technique": project.technique,
            "sample_type": project.sample_type,
        },
    )

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
    project = await require_project(project_id, current_user.id, session)
    return await _project_to_detail(project, session)


@router.get("/{project_id}/details", response_model=ProjectDetail)
async def get_project_details(
    project_id: int,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> ProjectDetail:
    """Alias for full project detail used by project-context clients."""
    project = await require_project(project_id, current_user.id, session)
    return await _project_to_detail(project, session)


@router.get("/{project_id}/data-sources", response_model=list[ProjectDataSourceOut])
async def list_project_data_sources(
    project_id: int,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> list[ProjectDataSourceOut]:
    """List data sources registered for a project."""
    await require_project(project_id, current_user.id, session)
    result = await session.execute(
        select(ProjectDataSource)
        .where(ProjectDataSource.project_id == project_id)
        .order_by(ProjectDataSource.sort_order.asc(), ProjectDataSource.display_name.asc())
    )
    return [
        ProjectDataSourceOut(
            id=data_source.id,
            project_id=data_source.project_id,
            display_name=data_source.display_name,
            source_type=data_source.source_type,
            source_ref=data_source.source_ref,
            fingerprint=data_source.fingerprint,
            color=data_source.color,
            metadata=data_source.metadata_ or {},
            sort_order=data_source.sort_order,
            created_at=data_source.created_at,
            updated_at=data_source.updated_at,
        )
        for data_source in result.scalars().all()
    ]


@router.get("/{project_id}/advisor-channels", response_model=list[AdvisorChannelOut])
async def list_project_advisor_channels(
    project_id: int,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> list[AdvisorChannelOut]:
    """List project-level and sheet-level Sherpa Advisor channels."""
    await require_project(project_id, current_user.id, session)
    result = await session.execute(
        select(AdvisorChannel)
        .where(AdvisorChannel.project_id == project_id)
        .order_by(AdvisorChannel.channel_type.asc(), AdvisorChannel.updated_at.desc())
    )
    return [AdvisorChannelOut.model_validate(channel) for channel in result.scalars().all()]


@router.put("/{project_id}/advisor-channels/{channel_id}", response_model=AdvisorChannelOut)
async def update_project_advisor_channel(
    project_id: int,
    channel_id: int,
    payload: AdvisorChannelUpdate,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> AdvisorChannelOut:
    """Update sheet/project advisor channel metadata such as conversation binding."""
    await require_project(project_id, current_user.id, session)
    result = await session.execute(
        select(AdvisorChannel).where(
            AdvisorChannel.id == channel_id,
            AdvisorChannel.project_id == project_id,
        )
    )
    channel = result.scalar_one_or_none()
    if channel is None:
        raise HTTPException(status_code=404, detail="Advisor channel not found")

    update_data = payload.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(channel, key, value)

    await session.commit()
    await session.refresh(channel)
    return AdvisorChannelOut.model_validate(channel)


@router.post("/{project_id}/data-sources", response_model=ProjectDataSourceOut, status_code=201)
async def create_project_data_source(
    project_id: int,
    payload: ProjectDataSourceCreate,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> ProjectDataSourceOut:
    """Create a manually registered project data source."""
    await require_project(project_id, current_user.id, session)
    sort_order = await session.scalar(
        select(func.count(ProjectDataSource.id)).where(ProjectDataSource.project_id == project_id)
    )
    data_source = ProjectDataSource(
        project_id=project_id,
        display_name=payload.display_name,
        source_type=payload.source_type,
        source_ref=payload.source_ref,
        fingerprint=payload.fingerprint,
        color=payload.color,
        metadata_=payload.metadata,
        sort_order=sort_order or 0,
    )
    session.add(data_source)
    await session.flush()

    # ISO 17025 audit — project_data_source.created. Captures "what
    # data source was registered against project X" — answers a real
    # auditor question.
    from spectra_sherpa.app.services.audit import audit_emitter

    audit_emitter.emit(
        session=session,
        action="project_data_source.created",
        target_type="ProjectDataSource",
        target_id=data_source.id,
        after={
            "project_id": project_id,
            "display_name": data_source.display_name,
            "source_type": data_source.source_type,
            "source_ref": data_source.source_ref,
            "fingerprint": data_source.fingerprint,
        },
    )

    await session.commit()
    await session.refresh(data_source)
    return ProjectDataSourceOut(
        id=data_source.id,
        project_id=data_source.project_id,
        display_name=data_source.display_name,
        source_type=data_source.source_type,
        source_ref=data_source.source_ref,
        fingerprint=data_source.fingerprint,
        color=data_source.color,
        metadata=data_source.metadata_ or {},
        sort_order=data_source.sort_order,
        created_at=data_source.created_at,
        updated_at=data_source.updated_at,
    )


@router.put("/{project_id}/data-sources/{data_source_id}", response_model=ProjectDataSourceOut)
async def update_project_data_source(
    project_id: int,
    data_source_id: int,
    payload: ProjectDataSourceUpdate,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> ProjectDataSourceOut:
    """Update project data-source metadata such as display name or color."""
    await require_project(project_id, current_user.id, session)
    result = await session.execute(
        select(ProjectDataSource).where(
            ProjectDataSource.id == data_source_id,
            ProjectDataSource.project_id == project_id,
        )
    )
    data_source = result.scalar_one_or_none()
    if data_source is None:
        raise HTTPException(status_code=404, detail="Project data source not found")

    _audit_before = {
        "display_name": data_source.display_name,
        "source_type": data_source.source_type,
        "source_ref": data_source.source_ref,
        "fingerprint": data_source.fingerprint,
        "color": data_source.color,
        "metadata_": data_source.metadata_,
    }

    update_data = payload.model_dump(exclude_unset=True)
    if "metadata" in update_data:
        update_data["metadata_"] = update_data.pop("metadata")
    for key, value in update_data.items():
        setattr(data_source, key, value)

    _audit_after = {
        "display_name": data_source.display_name,
        "source_type": data_source.source_type,
        "source_ref": data_source.source_ref,
        "fingerprint": data_source.fingerprint,
        "color": data_source.color,
        "metadata_": data_source.metadata_,
    }

    # ISO 17025 audit — project_data_source.updated. Idempotent: idle
    # PUTs (no payload fields, or fields equal to current state) do
    # not emit. Matches the experiment.updated guard.
    if _audit_before != _audit_after:
        from spectra_sherpa.app.services.audit import audit_emitter

        audit_emitter.emit(
            session=session,
            action="project_data_source.updated",
            target_type="ProjectDataSource",
            target_id=data_source.id,
            before=_audit_before,
            after=_audit_after,
        )

    await session.commit()
    await session.refresh(data_source)
    return ProjectDataSourceOut(
        id=data_source.id,
        project_id=data_source.project_id,
        display_name=data_source.display_name,
        source_type=data_source.source_type,
        source_ref=data_source.source_ref,
        fingerprint=data_source.fingerprint,
        color=data_source.color,
        metadata=data_source.metadata_ or {},
        sort_order=data_source.sort_order,
        created_at=data_source.created_at,
        updated_at=data_source.updated_at,
    )


@router.put("/{project_id}", response_model=ProjectDetail)
async def update_project(
    project_id: int,
    payload: ProjectUpdate,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> ProjectDetail:
    """Update project metadata."""
    project = await require_project(project_id, current_user.id, session)

    if payload.parent_id is not None and payload.parent_id != project.parent_id:
        if payload.parent_id == project.id:
            raise HTTPException(status_code=400, detail="Cannot set project as its own parent")
        await require_project(payload.parent_id, current_user.id, session)

    # Capture before-state for audit — picked to support
    # reproducibility of "what changed" without dumping the whole row.
    _audit_before = {
        "name": project.name,
        "description": project.description,
        "parent_id": project.parent_id,
        "technique": project.technique,
        "sample_type": project.sample_type,
        "metadata_": project.metadata_,
    }

    update_data = payload.model_dump(exclude_unset=True)
    if "metadata" in update_data:
        update_data["metadata_"] = update_data.pop("metadata")
    for key, value in update_data.items():
        setattr(project, key, value)

    _audit_after = {
        "name": project.name,
        "description": project.description,
        "parent_id": project.parent_id,
        "technique": project.technique,
        "sample_type": project.sample_type,
        "metadata_": project.metadata_,
    }

    # ISO 17025 audit — project.updated. Idempotent: only emit when
    # something actually changed. Matches the experiment.updated guard.
    if _audit_before != _audit_after:
        from spectra_sherpa.app.services.audit import audit_emitter

        audit_emitter.emit(
            session=session,
            action="project.updated",
            target_type="Project",
            target_id=project.id,
            before=_audit_before,
            after=_audit_after,
        )

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
    project = await require_project(project_id, current_user.id, session)

    # SET NULL on linked experiments, workflows, and models before cascade delete
    for exp in (await session.execute(select(Experiment).where(Experiment.project_id == project_id))).scalars().all():
        exp.project_id = None

    for wf in (await session.execute(select(Workflow).where(Workflow.project_id == project_id))).scalars().all():
        wf.project_id = None

    for ma in (
        (await session.execute(select(ModelArtifact).where(ModelArtifact.project_id == project_id))).scalars().all()
    ):
        ma.project_id = None

    # ISO 17025 audit — emit BEFORE delete so before_state captures
    # the row identity. Commits in the same TX as the delete.
    from spectra_sherpa.app.services.audit import audit_emitter

    audit_emitter.emit(
        session=session,
        action="project.deleted",
        target_type="Project",
        target_id=project_id,
        before={
            "name": project.name,
            "parent_id": project.parent_id,
            "technique": project.technique,
        },
    )

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
    project = await require_project(project_id, current_user.id, session)
    result = await session.execute(
        select(Experiment).where(Experiment.id == experiment_id, Experiment.user_id == current_user.id)
    )
    experiment = result.scalar_one_or_none()
    if experiment is None:
        raise HTTPException(status_code=404, detail="Experiment not found")

    # ISO 17025 audit — experiment.project_linked. Project-membership
    # changes are state mutations on the entity (project_id flips), so
    # the audit row targets the experiment with before/after project_id.
    # Idempotent: if the experiment is already linked here, suppress the
    # event so idle re-POSTs don't pollute the trail.
    previous_project_id = experiment.project_id
    if previous_project_id != project_id:
        from spectra_sherpa.app.services.audit import audit_emitter

        audit_emitter.emit(
            session=session,
            action="experiment.project_linked",
            target_type="Experiment",
            target_id=experiment.id,
            before={"project_id": previous_project_id},
            after={"project_id": project_id},
        )

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
    project = await require_project(project_id, current_user.id, session)
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

    # ISO 17025 audit — experiment.project_unlinked. The 404 above
    # already proved project_id == project_id, so the transition is
    # always project_id → None.
    from spectra_sherpa.app.services.audit import audit_emitter

    audit_emitter.emit(
        session=session,
        action="experiment.project_unlinked",
        target_type="Experiment",
        target_id=experiment.id,
        before={"project_id": project_id},
        after={"project_id": None},
    )

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
    project = await require_project(project_id, current_user.id, session)
    result = await session.execute(
        select(Workflow).where(Workflow.id == workflow_id, Workflow.user_id == current_user.id)
    )
    workflow = result.scalar_one_or_none()
    if workflow is None:
        raise HTTPException(status_code=404, detail="Workflow not found")

    # ISO 17025 audit — workflow.project_linked (idempotent).
    previous_project_id = workflow.project_id
    if previous_project_id != project_id:
        from spectra_sherpa.app.services.audit import audit_emitter

        audit_emitter.emit(
            session=session,
            action="workflow.project_linked",
            target_type="Workflow",
            target_id=workflow.id,
            before={"project_id": previous_project_id},
            after={"project_id": project_id},
        )

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
    project = await require_project(project_id, current_user.id, session)
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

    # ISO 17025 audit — workflow.project_unlinked.
    from spectra_sherpa.app.services.audit import audit_emitter

    audit_emitter.emit(
        session=session,
        action="workflow.project_unlinked",
        target_type="Workflow",
        target_id=workflow.id,
        before={"project_id": project_id},
        after={"project_id": None},
    )

    workflow.project_id = None
    await session.commit()
    logger.info("Unlinked workflow %s from project %s", workflow_id, project_id)
    return await _project_to_detail(project, session)


@router.post("/{project_id}/models/{artifact_uid}", response_model=ProjectDetail)
async def link_model(
    project_id: int,
    artifact_uid: str,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> ProjectDetail:
    """Link a model artifact to this project."""
    project = await require_project(project_id, current_user.id, session)
    result = await session.execute(
        select(ModelArtifact).where(
            ModelArtifact.artifact_uid == artifact_uid,
            ModelArtifact.user_id == current_user.id,
            ModelArtifact.is_active == True,  # noqa: E712
        )
    )
    model = result.scalar_one_or_none()
    if model is None:
        raise HTTPException(status_code=404, detail="Model artifact not found")

    # ISO 17025 audit — model_artifact.project_linked. target_id uses
    # the row's integer PK so chains can join to the Phase 1 model
    # artifact lifecycle events; artifact_uid recorded in after_state.
    previous_project_id = model.project_id
    if previous_project_id != project_id:
        from spectra_sherpa.app.services.audit import audit_emitter

        audit_emitter.emit(
            session=session,
            action="model_artifact.project_linked",
            target_type="ModelArtifact",
            target_id=model.id,
            before={"project_id": previous_project_id, "artifact_uid": artifact_uid},
            after={"project_id": project_id, "artifact_uid": artifact_uid},
        )

    model.project_id = project_id
    await session.commit()
    logger.info("Linked model %s to project %s", artifact_uid, project_id)
    return await _project_to_detail(project, session)


@router.delete("/{project_id}/models/{artifact_uid}", response_model=ProjectDetail)
async def unlink_model(
    project_id: int,
    artifact_uid: str,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> ProjectDetail:
    """Unlink a model artifact from this project."""
    project = await require_project(project_id, current_user.id, session)
    result = await session.execute(
        select(ModelArtifact).where(
            ModelArtifact.artifact_uid == artifact_uid,
            ModelArtifact.project_id == project_id,
            ModelArtifact.user_id == current_user.id,
        )
    )
    model = result.scalar_one_or_none()
    if model is None:
        raise HTTPException(status_code=404, detail="Model not linked to this project")

    # ISO 17025 audit — model_artifact.project_unlinked.
    from spectra_sherpa.app.services.audit import audit_emitter

    audit_emitter.emit(
        session=session,
        action="model_artifact.project_unlinked",
        target_type="ModelArtifact",
        target_id=model.id,
        before={"project_id": project_id, "artifact_uid": artifact_uid},
        after={"project_id": None, "artifact_uid": artifact_uid},
    )

    model.project_id = None
    await session.commit()
    logger.info("Unlinked model %s from project %s", artifact_uid, project_id)
    return await _project_to_detail(project, session)


# ── Versioning / Save All ────────────────────────────────────────────


async def _build_snapshot(project: Project, session: AsyncSession) -> dict:
    """Build a recursive snapshot of the project tree."""
    # Experiments with files
    exp_result = await session.execute(
        select(Experiment).where(Experiment.project_id == project.id).options(selectinload(Experiment.files))
    )
    experiments_snap = []
    for exp in exp_result.scalars().all():
        experiments_snap.append(
            {
                "id": exp.id,
                "name": exp.name,
                "description": exp.description,
                "file_count": len(exp.files),
                "files": [
                    {"id": f.id, "file_path": f.file_path, "stage": f.stage, "file_type": f.file_type}
                    for f in exp.files
                ],
            }
        )

    # Workflows with nodes and edges
    wf_result = await session.execute(
        select(Workflow)
        .where(Workflow.project_id == project.id)
        .options(selectinload(Workflow.nodes), selectinload(Workflow.edges))
    )
    workflows_snap = []
    for wf in wf_result.scalars().all():
        workflows_snap.append(
            {
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
            }
        )

    # Scripts
    script_result = await session.execute(
        select(ProjectScript).where(ProjectScript.project_id == project.id).order_by(ProjectScript.priority)
    )
    scripts_snap = []
    for s in script_result.scalars().all():
        scripts_snap.append(
            {
                "id": s.id,
                "name": s.name,
                "description": s.description,
                "language": s.language,
                "code": s.code,
                "priority": s.priority,
                "source_workflow_id": s.source_workflow_id,
            }
        )

    # Models
    model_result = await session.execute(
        select(ModelArtifact).where(
            ModelArtifact.project_id == project.id, ModelArtifact.is_active == True  # noqa: E712
        )
    )
    models_snap = []
    for m in model_result.scalars().all():
        metrics = _safe_parse_metrics(m.metrics_json)
        models_snap.append(
            {
                "artifact_uid": m.artifact_uid,
                "name": m.name,
                "model_type": m.model_type,
                "node_id": m.node_id,
                "n_features": m.n_features,
                "n_components": m.n_components,
                "metrics": metrics,
                "integrity_hash": m.integrity_hash,
            }
        )

    # Recursive children
    child_result = await session.execute(select(Project).where(Project.parent_id == project.id))
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
        "models": models_snap,
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
    project = await require_project(project_id, current_user.id, session)

    # Determine next version number
    max_ver = await session.scalar(
        select(func.max(ProjectVersion.version_number)).where(ProjectVersion.project_id == project_id)
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

    logger.info("Saved project '%s' version %s (id=%s)", project.name, next_ver, version.id)
    return ProjectVersionSummary.model_validate(version)


@router.get("/{project_id}/versions", response_model=ProjectVersionListResponse)
async def list_versions(
    project_id: int,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> ProjectVersionListResponse:
    """List version history for a project."""
    await require_project(project_id, current_user.id, session)

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
    await require_project(project_id, current_user.id, session)

    query = select(ProjectVersion).where(ProjectVersion.id == version_id, ProjectVersion.project_id == project_id)
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
    """Download project as a .spectrapy archive (ZIP with project.json + model artifacts)."""
    project = await require_project(project_id, current_user.id, session)

    if version_id:
        query = select(ProjectVersion).where(ProjectVersion.id == version_id, ProjectVersion.project_id == project_id)
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

        # Include model artifact files (manifest.json + arrays.npz)
        model_uids = [m["artifact_uid"] for m in snapshot.get("models", [])]
        if model_uids:
            try:
                from spectra_sherpa.app.services.model_store import get_model_store

                store = get_model_store()
                for uid in model_uids:
                    manifest_path = store._artifact_dir(uid) / "manifest.json"
                    arrays_path = store._artifact_dir(uid) / "arrays.npz"
                    if manifest_path.exists():
                        zf.write(str(manifest_path), f"models/{uid}/manifest.json")
                    if arrays_path.exists():
                        zf.write(str(arrays_path), f"models/{uid}/arrays.npz")
            except RuntimeError:
                logger.warning("ModelStore not initialized — model files not included in export")

    buf.seek(0)
    safe_name = project.name.replace(" ", "_").replace("/", "_")
    return StreamingResponse(
        buf,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{safe_name}.spectrapy"'},
    )


def _remap_model_uids_in_snapshot(project_json: dict[str, Any], remap: dict[str, str]) -> None:
    """Rewrite artifact-uid references in an import snapshot after collisions.

    Audit DATA-4: when an imported model's uid collided with an existing
    artifact we saved it under a fresh server-generated uid.  The
    snapshot blob (persisted as ``ProjectVersion.snapshot``) must point
    at the new uid so a later version-restore + ``model.load_apply``
    resolves the imported model and not whatever happened to own the
    colliding uid.
    """
    if not remap:
        return
    for m in project_json.get("models", []):
        if isinstance(m, dict) and m.get("artifact_uid") in remap:
            m["artifact_uid"] = remap[m["artifact_uid"]]
    for wf in project_json.get("workflows", []):
        for node in wf.get("nodes", []) if isinstance(wf, dict) else []:
            params = node.get("parameters") if isinstance(node, dict) else None
            if isinstance(params, dict) and params.get("model_id") in remap:
                params["model_id"] = remap[params["model_id"]]


def _purge_artifacts(uids: list[str]) -> None:
    """Best-effort delete of artifacts written by a now-rolled-back import.

    Audit DATA-4 / DATA-2: ``store.save()`` writes files before the
    transaction commits.  If the import rolls back, the DB rows vanish
    but the files would leak as orphans — remove them here.
    """
    if not uids:
        return
    try:
        from spectra_sherpa.app.services.model_store import get_model_store

        store = get_model_store()
    except Exception:
        return
    for au in uids:
        try:
            store.delete(au)
        except Exception:  # pragma: no cover - best-effort cleanup
            logger.warning("Could not purge rolled-back import artifact %s", au)


@router.post(
    "/import", response_model=ProjectDetail, status_code=201, dependencies=[Depends(demo_guard("project_import"))]
)
async def import_project(
    file: UploadFile = File(...),
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> ProjectDetail:
    """Import a .spectrapy archive to create a new project."""
    max_bytes = settings.max_file_size_mb * 1024 * 1024
    declared_size = getattr(file, "size", None)
    if isinstance(declared_size, int) and declared_size > max_bytes:
        raise HTTPException(
            status_code=413,
            detail=f"Archive too large ({declared_size / (1024*1024):.1f} MB). "
            f"Maximum is {settings.max_file_size_mb} MB.",
        )

    upload_bytes = await _read_upload_with_limit(file, max_bytes=max_bytes)
    upload_size = len(upload_bytes)

    # Enforce upload size limit (same as experiment uploads) before reading ZIP content.
    if upload_size > max_bytes:
        raise HTTPException(
            status_code=413,
            detail=f"Archive too large ({upload_size / (1024*1024):.1f} MB). "
            f"Maximum is {settings.max_file_size_mb} MB.",
        )

    project: Project | None = None
    models_imported = 0
    # Artifacts written to disk during this import; purged if the
    # transaction rolls back so a failed import leaves no orphans (DATA-4).
    imported_artifact_uids: list[str] = []

    try:
        upload_stream = io.BytesIO(upload_bytes)
        with zipfile.ZipFile(upload_stream, "r") as zf:
            project_json = json.loads(zf.read("project.json"))
            zip_names = set(zf.namelist())

            # Restore model artifacts from ZIP (if present)
            import uuid as _uuid

            import numpy as np

            max_member_bytes = settings.max_file_size_mb * 1024 * 1024  # per-file limit
            max_total_model_bytes = max_member_bytes * 5  # total budget across all models
            max_compression_ratio = 200  # reject members with > 200:1 ratio (zip bomb indicator)
            total_model_bytes_extracted = 0
            total_model_member_bytes = 0

            # Pre-scan: validate all model entries and compute total uncompressed size
            # before extracting anything (fail-fast on budget overflow).
            model_entries: list[tuple[str, dict, bytes, bytes]] = []  # (uid, m_data, manifest_bytes, arrays_bytes)
            for m_data in project_json.get("models", []):
                uid = m_data.get("artifact_uid")
                if not uid:
                    continue

                # Validate artifact_uid is a proper UUID to prevent path traversal
                try:
                    _uuid.UUID(uid)
                except (ValueError, AttributeError):
                    logger.warning("Invalid artifact_uid '%s' in snapshot — skipping", uid)
                    continue

                manifest_zip_path = f"models/{uid}/manifest.json"
                arrays_zip_path = f"models/{uid}/arrays.npz"

                if manifest_zip_path not in zip_names or arrays_zip_path not in zip_names:
                    logger.warning("Model %s in snapshot but files missing from archive — skipping", uid)
                    continue

                # Per-member size + compression ratio check
                skip = False
                member_sizes = 0
                for member_path in (manifest_zip_path, arrays_zip_path):
                    info = zf.getinfo(member_path)
                    if info.file_size > max_member_bytes:
                        logger.warning(
                            "Model file %s too large (%.1f MB) — skipping model %s",
                            member_path,
                            info.file_size / (1024 * 1024),
                            uid,
                        )
                        skip = True
                        break
                    # Compression ratio guard: compressed_size of 0 means stored uncompressed
                    if info.compress_size > 0 and info.file_size / info.compress_size > max_compression_ratio:
                        logger.warning(
                            "Model file %s has suspicious compression ratio (%.0f:1) — skipping model %s",
                            member_path,
                            info.file_size / info.compress_size,
                            uid,
                        )
                        skip = True
                        break
                    member_sizes += info.file_size
                if skip:
                    continue

                total_model_member_bytes += member_sizes
                if total_model_member_bytes > max_total_model_bytes:
                    raise HTTPException(
                        status_code=413,
                        detail=(
                            f"Total model data too large ({total_model_member_bytes / (1024*1024):.1f} MB). "
                            f"Maximum is {max_total_model_bytes / (1024*1024):.0f} MB."
                        ),
                    )

                manifest_bytes = zf.read(manifest_zip_path)
                arrays_bytes = zf.read(arrays_zip_path)

                try:
                    with np.load(io.BytesIO(arrays_bytes), allow_pickle=False) as npz:
                        arrays_nbytes = sum(int(getattr(array, "nbytes", 0)) for array in npz.values())
                except Exception as exc:
                    logger.warning("Invalid model array archive %s: %s", arrays_zip_path, exc)
                    continue

                total_model_bytes_extracted += len(manifest_bytes) + arrays_nbytes
                model_entries.append((uid, m_data, manifest_bytes, arrays_bytes))

            # Total budget check across all models
            if total_model_bytes_extracted > max_total_model_bytes:
                raise HTTPException(
                    status_code=413,
                    detail=f"Total model data too large ({total_model_bytes_extracted / (1024*1024):.1f} MB). "
                    f"Maximum is {max_total_model_bytes / (1024*1024):.0f} MB.",
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
            await session.flush()

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

            # Audit DATA-4: an archive must never overwrite an artifact
            # that already exists (on disk or in the DB) — a crafted
            # archive could otherwise target a victim's known uid and
            # corrupt their model.  Pre-resolve which candidate uids are
            # already taken in the DB; the per-model loop also checks
            # disk (covers another project's files and intra-archive
            # duplicate uids).  Colliding models are saved under a fresh
            # server-generated uid and the snapshot is remapped to it.
            uid_remap: dict[str, str] = {}
            candidate_uids = [e[0] for e in model_entries]
            existing_db_uids: set[str] = set()
            if candidate_uids:
                _dup_res = await session.execute(
                    select(ModelArtifact.artifact_uid).where(ModelArtifact.artifact_uid.in_(candidate_uids))
                )
                existing_db_uids = set(_dup_res.scalars().all())

            # Extract and import validated models
            for uid, m_data, manifest_bytes, arrays_bytes in model_entries:
                try:
                    from spectra_sherpa.app.services.model_store import get_model_store

                    store = get_model_store()

                    manifest = json.loads(manifest_bytes)

                    # Load arrays from the npz bytes
                    arrays_buf = io.BytesIO(arrays_bytes)
                    with np.load(arrays_buf, allow_pickle=False) as npz:
                        arrays = dict(npz)

                    target_uid = uid
                    if uid in existing_db_uids or store._artifact_dir(uid).exists():
                        target_uid = str(_uuid.uuid4())
                        uid_remap[uid] = target_uid
                        logger.info(
                            "Import artifact uid %s collides with an existing artifact — " "remapped to fresh uid %s",
                            uid,
                            target_uid,
                        )

                    # Save via ModelStore (computes new integrity hash)
                    integrity_hash = store.save(target_uid, manifest, arrays)
                    imported_artifact_uids.append(target_uid)

                    # Create DB record
                    model_row = ModelArtifact(
                        artifact_uid=target_uid,
                        user_id=current_user.id,
                        project_id=project.id,
                        node_id=m_data.get("node_id", "imported"),
                        model_type=m_data.get("model_type", "unknown"),
                        name=m_data.get("name", f"Imported model {target_uid[:8]}"),
                        artifact_dir=str(store._artifact_dir(target_uid)),
                        integrity_hash=integrity_hash,
                        n_features=m_data.get("n_features", 0),
                        n_components=m_data.get("n_components"),
                    )
                    session.add(model_row)
                    models_imported += 1
                except RuntimeError:
                    logger.warning("ModelStore not initialized — cannot import model %s", uid)
                except Exception as exc:
                    logger.warning("Failed to import model %s: %s", uid, exc)

            # Keep the persisted snapshot internally consistent with the
            # uids we actually wrote (DATA-4).
            _remap_model_uids_in_snapshot(project_json, uid_remap)

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
    except HTTPException:
        await session.rollback()
        _purge_artifacts(imported_artifact_uids)
        raise
    except (zipfile.BadZipFile, KeyError, json.JSONDecodeError) as exc:
        await session.rollback()
        _purge_artifacts(imported_artifact_uids)
        raise HTTPException(
            status_code=400,
            detail=f"Invalid .spectrapy archive: {exc}",
        )
    except Exception:
        await session.rollback()
        _purge_artifacts(imported_artifact_uids)
        raise

    if project is None:
        raise HTTPException(status_code=500, detail="Project import failed")

    if models_imported:
        logger.info("Imported %d model artifact(s) for project '%s'", models_imported, project.name)

    logger.info("Imported project '%s' (id=%s)", project.name, project.id)
    return await _project_to_detail(project, session)
