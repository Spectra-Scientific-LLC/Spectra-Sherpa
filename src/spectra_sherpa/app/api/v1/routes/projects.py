"""
Project API endpoints — CRUD, link/unlink, versioning, and export/import.
"""

from __future__ import annotations

import io
import json
import logging
import re
import zipfile
from typing import Any

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import Response, StreamingResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from spectra_sherpa.app.api.deps import (
    consume_reserved_demo_upload_quota_if_needed,
    demo_guard,
    get_current_user,
    get_session,
    release_demo_upload_quota_reservation_if_needed,
    require_project,
    reserve_demo_upload_quota_or_429,
)
from spectra_sherpa.app.core.config import settings
from spectra_sherpa.app.core.security import check_export_allowed
from spectra_sherpa.app.models.advisor_channel import AdvisorChannel
from spectra_sherpa.app.models.experiment import Experiment
from spectra_sherpa.app.models.model_artifact import ModelArtifact
from spectra_sherpa.app.models.project import Project, ProjectVersion
from spectra_sherpa.app.models.project_data_source import ProjectDataSource, WorkflowDataSource
from spectra_sherpa.app.models.project_script import ProjectScript
from spectra_sherpa.app.models.user import User
from spectra_sherpa.app.models.workflow import Workflow
from spectra_sherpa.app.models.workflow_edge import WorkflowEdge
from spectra_sherpa.app.models.workflow_node import WorkflowNode
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
from spectra_sherpa.app.services.experiments import read_metadata, resolve_data_path
from spectra_sherpa.app.services.project_data_sources import (
    effective_workflow_tab_color,
    ensure_project_advisor_channel,
)
from spectra_sherpa.app.services.sherpa_object import (
    PROJECT_PAYLOAD,
    SHERPA_OBJECT_MANIFEST,
    ArchiveMember,
    build_archive,
    inspect_archive_bytes,
    validate_archive_bytes,
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


_GENERIC_TEMPLATE_DATA_DESCRIPTION = "Bundled example data materialized from template"


def _first_sentence(text: str | None) -> str | None:
    """Return a compact first sentence for project record summaries."""
    if not text:
        return None
    cleaned = " ".join(text.split())
    if not cleaned:
        return None
    for marker in (". ", "! ", "? "):
        if marker in cleaned:
            return cleaned.split(marker, 1)[0] + marker.strip()
    return cleaned


def _humanize_dataset_name(name: str) -> str:
    return name.replace("_", " ").replace("-", " ").strip().title()


def _append_fact(facts: list[str], value: str | None) -> None:
    if value and value not in facts:
        facts.append(value)


def _count_from_label(label: str, noun: str) -> int | None:
    match = re.search(rf"(\d+)\s+{noun}", label, flags=re.IGNORECASE)
    if not match:
        return None
    return int(match.group(1))


def _reference_dataset_summary(source: str | None, dataset_name: str | None) -> str | None:
    """User-facing one-liner for template materialized datasets."""
    if not source or not dataset_name:
        return None

    if source == "eigenvector":
        try:
            from spectra_sherpa.app.lib.eigenvector import DATASET_CATALOG

            entry = DATASET_CATALOG.get(dataset_name, {})
            label = str(entry.get("label") or _humanize_dataset_name(dataset_name))
            first_sentence = _first_sentence(str(entry.get("description") or ""))
            return f"{label} — {first_sentence}" if first_sentence else label
        except Exception:
            logger.debug("Could not resolve Eigenvector dataset summary for %s", dataset_name, exc_info=True)

    if source == "sklearn":
        try:
            from spectra_sherpa.app.lib.sklearn_info import SKLEARN_CATALOG

            entry = SKLEARN_CATALOG.get(dataset_name, {})
            return str(entry.get("label") or _humanize_dataset_name(dataset_name))
        except Exception:
            logger.debug("Could not resolve sklearn dataset summary for %s", dataset_name, exc_info=True)

    if source == "spectrochempy":
        return f"SpectroChemPy example dataset: {_humanize_dataset_name(dataset_name)}"

    if source == "oes":
        return f"OES example dataset: {_humanize_dataset_name(dataset_name)}"

    return f"{source}: {_humanize_dataset_name(dataset_name)}"


def _reference_dataset_facts(source: str | None, dataset_name: str | None) -> list[str]:
    """Compact facts for Data cards: samples, features/channels, classes/targets."""
    if not source or not dataset_name:
        return []

    facts: list[str] = []

    if source == "eigenvector":
        try:
            from spectra_sherpa.app.lib.eigenvector import DATASET_CATALOG

            entry = DATASET_CATALOG.get(dataset_name, {})
            label = str(entry.get("label") or "")
            _append_fact(facts, str(entry.get("technique") or "") or None)

            sample_count = _count_from_label(label, "samples")
            if sample_count is not None:
                _append_fact(facts, f"{sample_count} samples")

            for noun in ("channels", "wavelengths", "features"):
                feature_count = _count_from_label(label, noun)
                if feature_count is not None:
                    _append_fact(facts, f"{feature_count} {noun}")
                    break

            prop_names = entry.get("prop_names")
            if isinstance(prop_names, list) and prop_names:
                _append_fact(facts, f"{len(prop_names)} targets")
        except Exception:
            logger.debug("Could not resolve Eigenvector dataset facts for %s", dataset_name, exc_info=True)

    elif source == "sklearn":
        try:
            from spectra_sherpa.app.lib.sklearn_info import get_sklearn_dataset_info

            info = get_sklearn_dataset_info(dataset_name)
            _append_fact(facts, str(info.get("technique") or "") or None)
            n_samples = info.get("n_samples")
            if isinstance(n_samples, int):
                _append_fact(facts, f"{n_samples} samples")
            n_features = info.get("n_features")
            if isinstance(n_features, int):
                _append_fact(facts, f"{n_features} features")
            target_names = info.get("target_names")
            if isinstance(target_names, list) and target_names:
                _append_fact(facts, f"{len(target_names)} classes")
        except Exception:
            logger.debug("Could not resolve sklearn dataset facts for %s", dataset_name, exc_info=True)

    else:
        _append_fact(facts, source)

    return facts


def _experiment_metadata_summary(metadata: dict[str, Any]) -> str | None:
    source = metadata.get("example_source")
    dataset_name = metadata.get("example_dataset")
    if isinstance(source, str) and isinstance(dataset_name, str):
        return _reference_dataset_summary(source, dataset_name)

    if metadata.get("source") == "synthesis":
        synthesis_source = metadata.get("synthesis_source")
        if isinstance(synthesis_source, str) and synthesis_source:
            return f"Synthetic FTIR dataset generated from {synthesis_source.replace('_', ' ')} component spectra"
        return "Synthetic FTIR dataset generated from component spectra"

    return None


def _experiment_metadata_facts(metadata: dict[str, Any]) -> list[str]:
    source = metadata.get("example_source")
    dataset_name = metadata.get("example_dataset")
    if isinstance(source, str) and isinstance(dataset_name, str):
        return _reference_dataset_facts(source, dataset_name)

    if metadata.get("source") == "synthesis":
        facts = ["Synthetic"]
        synthesis_source = metadata.get("synthesis_source")
        if isinstance(synthesis_source, str) and synthesis_source:
            facts.append(synthesis_source.replace("_", " "))
        return facts

    return []


def _experiment_brief_description(experiment: Experiment) -> str | None:
    """Prefer content summaries over generic template plumbing descriptions."""
    metadata: dict[str, Any] = {}
    if experiment.metadata_path:
        try:
            metadata = read_metadata(resolve_data_path(experiment.metadata_path))
        except Exception:
            logger.debug("Could not read experiment metadata for project summary", exc_info=True)

    metadata_summary = _experiment_metadata_summary(metadata)
    description = experiment.description
    if metadata_summary and (not description or description.startswith(_GENERIC_TEMPLATE_DATA_DESCRIPTION)):
        return metadata_summary
    return description or metadata_summary


def _experiment_brief_facts(experiment: Experiment) -> list[str]:
    if not experiment.metadata_path:
        return []
    try:
        metadata = read_metadata(resolve_data_path(experiment.metadata_path))
    except Exception:
        logger.debug("Could not read experiment metadata for project facts", exc_info=True)
        return []
    return _experiment_metadata_facts(metadata)


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
            description=_experiment_brief_description(e),
            file_count=len(e.files),
            facts=_experiment_brief_facts(e),
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
                display_name=m.display_name or m.name,
                model_type=m.model_type,
                n_features=m.n_features,
                n_components=m.n_components,
                metrics=metrics,
                source_run_id=m.source_run_id,
                training_dataset_id=m.training_dataset_id,
                is_deploy_ready=m.is_deploy_ready,
                tags=list(m.tags or []),
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
    # Project data sources
    data_source_result = await session.execute(
        select(ProjectDataSource)
        .where(ProjectDataSource.project_id == project.id)
        .order_by(ProjectDataSource.sort_order.asc(), ProjectDataSource.display_name.asc())
    )
    data_sources_snap = []
    for data_source in data_source_result.scalars().all():
        data_sources_snap.append(
            {
                "id": data_source.id,
                "display_name": data_source.display_name,
                "source_type": data_source.source_type,
                "source_ref": data_source.source_ref,
                "fingerprint": data_source.fingerprint,
                "color": data_source.color,
                "metadata": data_source.metadata_ or {},
                "sort_order": data_source.sort_order,
            }
        )

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
        .options(selectinload(Workflow.nodes), selectinload(Workflow.edges), selectinload(Workflow.data_source_links))
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
                "canvas_state": wf.canvas_state,
                "notes": wf.notes,
                "sheet_order": wf.sheet_order,
                "tab_color": wf.tab_color,
                "tab_color_override": wf.tab_color_override,
                "color_source": wf.color_source,
                "primary_data_source_id": wf.primary_data_source_id,
                "data_source_ids": wf.data_source_ids,
                "created_from_template_id": wf.created_from_template_id,
                "created_from_template_name": wf.created_from_template_name,
                "created_from_template_version": wf.created_from_template_version,
                "created_from_workflow_id": wf.created_from_workflow_id,
                "nodes": [
                    {
                        "node_id": n.node_id,
                        "node_type": n.node_type,
                        "label": n.label,
                        "parameters": n.parameters,
                        "annotation": n.annotation,
                        "position_x": n.position_x,
                        "position_y": n.position_y,
                        "execution_order": n.execution_order,
                        "status": n.status,
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
        "data_sources": data_sources_snap,
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
    if not await check_export_allowed(current_user, session):
        raise HTTPException(status_code=403, detail="Export not permitted for this user")

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


def _model_members_for_snapshot(snapshot: dict[str, Any]) -> list[ArchiveMember]:
    """Collect model artifact files for a portable object."""
    members: list[ArchiveMember] = []
    model_uids = [m["artifact_uid"] for m in snapshot.get("models", []) if m.get("artifact_uid")]
    if not model_uids:
        return members
    try:
        from spectra_sherpa.app.services.model_store import get_model_store

        store = get_model_store()
    except RuntimeError:
        logger.warning("ModelStore not initialized — model files not included in .sherpa export")
        return members
    for uid in model_uids:
        artifact_dir = store._artifact_dir(uid)
        manifest_path = artifact_dir / "manifest.json"
        arrays_path = artifact_dir / "arrays.npz"
        if manifest_path.exists():
            members.append(ArchiveMember(f"models/{uid}/manifest.json", manifest_path.read_bytes()))
        if arrays_path.exists():
            members.append(ArchiveMember(f"models/{uid}/arrays.npz", arrays_path.read_bytes()))
    return members


def _public_archive_validation_error(message: Any) -> str:
    """Map archive-parser details to user-safe validation messages."""

    text = str(message)
    if text.startswith("Archive uncompressed payload exceeds limit"):
        return "Archive uncompressed payload exceeds the configured upload limit."
    if text.startswith("Unsupported .sherpa object version"):
        return "Unsupported .sherpa object version."
    if text.startswith("Unsafe archive member path"):
        return "Archive contains an unsafe member path."
    if text.startswith("Missing required payload:"):
        return "Archive is missing a required payload."
    if text.startswith("Missing required manifest:"):
        return "Archive is missing the required manifest."
    if text.startswith("Duplicate archive member:"):
        return "Archive contains duplicate members."
    if text.startswith("Manifest member missing from archive:"):
        return "Manifest references a missing archive member."
    if text.startswith("Manifest member entry is not an object:"):
        return "Manifest contains an invalid member entry."
    if text.startswith("SHA-256 mismatch for"):
        return "Archive member hash does not match the manifest."
    if text.startswith("Size mismatch for"):
        return "Archive member size does not match the manifest."
    if text.startswith("Archive member missing from manifest:"):
        return "Archive contains a member missing from the manifest."
    if text.startswith("Manifest content_hash does not match"):
        return "Manifest content hash does not match the archive payloads."
    if text.startswith("Manifest schema must be"):
        return "Archive manifest schema is unsupported."
    if text.startswith("Manifest must be"):
        return "Archive manifest is invalid."
    if text.startswith("Manifest payloads.members must be"):
        return "Archive manifest member inventory is invalid."
    if text.startswith("Only project .sherpa objects"):
        return "Only project .sherpa objects are supported."
    if text.startswith("Invalid ZIP archive:"):
        return "File is not a valid ZIP archive."
    return "Archive validation failed. Check that the file is a valid SpectraSherpa object archive."


def _public_archive_report(report: dict[str, Any]) -> dict[str, Any]:
    """Remove parser/exception detail before returning archive reports over HTTP."""

    public = dict(report)
    errors = public.get("errors")
    if isinstance(errors, list):
        public["errors"] = [_public_archive_validation_error(error) for error in errors]
    return public


@router.get("/{project_id}/export/sherpa")
async def export_project_sherpa_object(
    project_id: int,
    version_id: int | None = None,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> StreamingResponse:
    """Download project as a portable .sherpa object with offline-verifiable manifest."""
    if not await check_export_allowed(current_user, session):
        raise HTTPException(status_code=403, detail="Export not permitted for this user")

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

    archive_bytes = build_archive(
        project_payload=snapshot,
        members=_model_members_for_snapshot(snapshot),
        package_mode="full",
    )
    safe_name = project.name.replace(" ", "_").replace("/", "_")
    return StreamingResponse(
        io.BytesIO(archive_bytes),
        media_type="application/vnd.spectrasherpa.object+zip",
        headers={"Content-Disposition": f'attachment; filename="{safe_name}.sherpa"'},
    )


@router.post("/objects/inspect")
async def inspect_sherpa_object(
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Inspect a .sherpa object without importing or executing it."""
    max_bytes = settings.max_file_size_mb * 1024 * 1024
    payload = await _read_upload_with_limit(file, max_bytes=max_bytes)
    if len(payload) > max_bytes:
        raise HTTPException(status_code=413, detail="Archive too large")
    try:
        report = inspect_archive_bytes(payload, max_uncompressed_bytes=max_bytes).to_dict()
    except Exception:
        logger.warning("Unexpected .sherpa archive inspection failure", exc_info=True)
        raise HTTPException(status_code=400, detail="Archive inspection failed") from None
    return _public_archive_report(report)


@router.post("/objects/validate")
async def validate_sherpa_object(
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Validate a .sherpa object without importing or executing it."""
    max_bytes = settings.max_file_size_mb * 1024 * 1024
    payload = await _read_upload_with_limit(file, max_bytes=max_bytes)
    if len(payload) > max_bytes:
        raise HTTPException(status_code=413, detail="Archive too large")
    try:
        report = validate_archive_bytes(payload, max_uncompressed_bytes=max_bytes)
    except Exception:
        logger.warning("Unexpected .sherpa archive validation failure", exc_info=True)
        raise HTTPException(status_code=400, detail="Archive validation failed") from None
    return _public_archive_report(report)


def _remap_model_uids_in_snapshot(project_json: dict[str, Any], remap: dict[str, str]) -> None:
    """Rewrite artifact-uid references in an import snapshot after collisions.

    When an imported model's uid collided with an existing artifact, we
    saved it under a fresh server-generated uid.  The
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


async def _restore_project_data_sources(
    project: Project,
    project_json: dict[str, Any],
    session: AsyncSession,
) -> dict[int, int]:
    """Recreate project data source rows and return old-id -> new-id map."""
    remap: dict[int, int] = {}
    for source_data in project_json.get("data_sources", []):
        if not isinstance(source_data, dict):
            continue
        data_source = ProjectDataSource(
            project_id=project.id,
            display_name=source_data.get("display_name") or "Imported Data Source",
            source_type=source_data.get("source_type") or "external",
            source_ref=source_data.get("source_ref"),
            fingerprint=source_data.get("fingerprint"),
            color=source_data.get("color") or "#3b82f6",
            metadata_=source_data.get("metadata") or {},
            sort_order=source_data.get("sort_order") or 0,
        )
        session.add(data_source)
        await session.flush()
        old_id = source_data.get("id")
        if isinstance(old_id, int):
            remap[old_id] = data_source.id
    return remap


def _remap_workflow_parameters(value: Any, data_source_remap: dict[int, int]) -> Any:
    """Best-effort rewrite of known project-local IDs inside node parameters."""
    if isinstance(value, dict):
        rewritten = {key: _remap_workflow_parameters(item, data_source_remap) for key, item in value.items()}
        for key in ("data_source_id", "primary_data_source_id"):
            if isinstance(rewritten.get(key), int) and rewritten[key] in data_source_remap:
                rewritten[key] = data_source_remap[rewritten[key]]
        return rewritten
    if isinstance(value, list):
        return [_remap_workflow_parameters(item, data_source_remap) for item in value]
    return value


async def _restore_workflows_from_snapshot(
    project: Project,
    user_id: int,
    project_json: dict[str, Any],
    data_source_remap: dict[int, int],
    session: AsyncSession,
) -> dict[int, int]:
    """Recreate workflow rows from a project snapshot."""
    workflow_remap: dict[int, int] = {}
    pending_created_from: list[tuple[Workflow, int]] = []

    for wf_data in project_json.get("workflows", []):
        if not isinstance(wf_data, dict):
            continue
        primary_data_source_id = wf_data.get("primary_data_source_id")
        if isinstance(primary_data_source_id, int):
            primary_data_source_id = data_source_remap.get(primary_data_source_id)
        else:
            primary_data_source_id = None

        workflow = Workflow(
            user_id=user_id,
            project_id=project.id,
            name=wf_data.get("name") or "Imported Workflow",
            description=wf_data.get("description"),
            status=wf_data.get("status") or "draft",
            canvas_state=wf_data.get("canvas_state"),
            notes=wf_data.get("notes"),
            integrity_hash=wf_data.get("integrity_hash"),
            technique=wf_data.get("technique"),
            sample_type=wf_data.get("sample_type"),
            tab_color=wf_data.get("tab_color"),
            primary_data_source_id=primary_data_source_id,
            tab_color_override=wf_data.get("tab_color_override"),
            color_source=wf_data.get("color_source") or "blank",
            created_from_template_id=wf_data.get("created_from_template_id"),
            created_from_template_name=wf_data.get("created_from_template_name"),
            created_from_template_version=wf_data.get("created_from_template_version"),
            sheet_order=wf_data.get("sheet_order") or 0,
        )
        session.add(workflow)
        await session.flush()

        old_wf_id = wf_data.get("id")
        if isinstance(old_wf_id, int):
            workflow_remap[old_wf_id] = workflow.id
        created_from = wf_data.get("created_from_workflow_id")
        if isinstance(created_from, int):
            pending_created_from.append((workflow, created_from))

        data_source_ids = wf_data.get("data_source_ids") or []
        ordered_data_source_ids = [
            data_source_remap[item] for item in data_source_ids if isinstance(item, int) and item in data_source_remap
        ]
        if primary_data_source_id is not None and primary_data_source_id not in ordered_data_source_ids:
            ordered_data_source_ids.insert(0, primary_data_source_id)
        for index, data_source_id in enumerate(dict.fromkeys(ordered_data_source_ids)):
            session.add(
                WorkflowDataSource(
                    workflow_id=workflow.id,
                    data_source_id=data_source_id,
                    role="primary" if index == 0 else "secondary",
                )
            )

        for node_data in wf_data.get("nodes", []):
            if not isinstance(node_data, dict):
                continue
            session.add(
                WorkflowNode(
                    workflow_id=workflow.id,
                    node_id=node_data.get("node_id") or "imported_node",
                    node_type=node_data.get("node_type") or "unknown",
                    label=node_data.get("label"),
                    parameters=_remap_workflow_parameters(node_data.get("parameters") or {}, data_source_remap),
                    annotation=node_data.get("annotation"),
                    position_x=node_data.get("position_x"),
                    position_y=node_data.get("position_y"),
                    execution_order=node_data.get("execution_order"),
                    status=node_data.get("status") or "pending",
                )
            )

        for edge_data in wf_data.get("edges", []):
            if not isinstance(edge_data, dict):
                continue
            session.add(
                WorkflowEdge(
                    workflow_id=workflow.id,
                    from_node_id=edge_data.get("from_node_id") or "",
                    to_node_id=edge_data.get("to_node_id") or "",
                    from_output=edge_data.get("from_output") or "default",
                    to_input=edge_data.get("to_input") or "default",
                )
            )

    await session.flush()
    for workflow, old_parent_id in pending_created_from:
        workflow.created_from_workflow_id = workflow_remap.get(old_parent_id)
    return workflow_remap


def _purge_artifacts(uids: list[str]) -> None:
    """Best-effort delete of artifacts written by a now-rolled-back import.

    ``store.save()`` writes files before the transaction commits.  If the
    import rolls back, the DB rows vanish but the files would leak as
    orphans — remove them here.
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
    """Import a .spectrapy or .sherpa archive to create a new project."""
    max_bytes = settings.max_file_size_mb * 1024 * 1024
    declared_size = getattr(file, "size", None)
    if isinstance(declared_size, int) and declared_size > max_bytes:
        raise HTTPException(
            status_code=413,
            detail=f"Archive too large ({declared_size / (1024*1024):.1f} MB). "
            f"Maximum is {settings.max_file_size_mb} MB.",
        )

    user_id = current_user.id
    upload_reserved = reserve_demo_upload_quota_or_429(user_id)
    project: Project | None = None
    models_imported = 0
    # Artifacts written to disk during this import; purged if the
    # transaction rolls back so a failed import leaves no orphans.
    imported_artifact_uids: list[str] = []
    committed = False

    try:
        upload_bytes = await _read_upload_with_limit(file, max_bytes=max_bytes)
        upload_size = len(upload_bytes)

        # Enforce upload size limit (same as experiment uploads) before reading ZIP content.
        if upload_size > max_bytes:
            raise HTTPException(
                status_code=413,
                detail=f"Archive too large ({upload_size / (1024*1024):.1f} MB). "
                f"Maximum is {settings.max_file_size_mb} MB.",
            )

        upload_stream = io.BytesIO(upload_bytes)
        with zipfile.ZipFile(upload_stream, "r") as zf:
            zip_names = set(zf.namelist())
            is_sherpa_object = SHERPA_OBJECT_MANIFEST in zip_names
            if is_sherpa_object:
                validation = validate_archive_bytes(upload_bytes)
                if not validation.get("valid"):
                    raise HTTPException(
                        status_code=400,
                        detail={
                            "message": "Invalid .sherpa object",
                            "errors": validation.get("errors", []),
                        },
                    )

            project_json = json.loads(zf.read(PROJECT_PAYLOAD))

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
                user_id=user_id,
                name=project_json.get("name", "Imported Project"),
                description=project_json.get("description"),
                metadata_=project_json.get("metadata", {}),
                technique=project_json.get("technique"),
                sample_type=project_json.get("sample_type"),
            )
            session.add(project)
            await session.flush()
            data_source_remap = await _restore_project_data_sources(project, project_json, session)
            workflow_remap = await _restore_workflows_from_snapshot(
                project,
                user_id,
                project_json,
                data_source_remap,
                session,
            )

            # Recreate scripts from snapshot
            for s_data in project_json.get("scripts", []):
                source_workflow_id = s_data.get("source_workflow_id")
                if isinstance(source_workflow_id, int):
                    source_workflow_id = workflow_remap.get(source_workflow_id)
                else:
                    source_workflow_id = None
                script = ProjectScript(
                    project_id=project.id,
                    user_id=user_id,
                    name=s_data.get("name", "Imported Script"),
                    description=s_data.get("description"),
                    language=s_data.get("language", "python"),
                    code=s_data.get("code", ""),
                    priority=s_data.get("priority", 50.0),
                    source_workflow_id=source_workflow_id,
                )
                session.add(script)

            # An archive must never overwrite an artifact that already
            # exists (on disk or in the DB) — a crafted archive could
            # otherwise target a victim's known uid and corrupt their
            # model. Pre-resolve which candidate uids are already taken
            # in the DB; the per-model loop also checks disk (covers
            # another project's files and intra-archive duplicate uids).
            # Colliding models are saved under a fresh server-generated
            # uid and the snapshot is remapped to it.
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
                        user_id=user_id,
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
            # uids we actually wrote.
            _remap_model_uids_in_snapshot(project_json, uid_remap)

            # Save import snapshot as version 1
            version = ProjectVersion(
                project_id=project.id,
                version_number=1,
                created_by=user_id,
                change_description=(
                    "Imported from .sherpa object" if is_sherpa_object else "Imported from .spectrapy archive"
                ),
                snapshot=project_json,
                include_raw_data=is_sherpa_object,
            )
            session.add(version)
            await session.commit()
            committed = True
    except HTTPException:
        await session.rollback()
        _purge_artifacts(imported_artifact_uids)
        raise
    except (zipfile.BadZipFile, KeyError, json.JSONDecodeError) as exc:
        await session.rollback()
        _purge_artifacts(imported_artifact_uids)
        raise HTTPException(
            status_code=400,
            detail=f"Invalid project archive: {exc}",
        )
    except Exception:
        await session.rollback()
        _purge_artifacts(imported_artifact_uids)
        raise
    except BaseException:
        await session.rollback()
        _purge_artifacts(imported_artifact_uids)
        raise
    finally:
        if committed:
            consume_reserved_demo_upload_quota_if_needed(user_id, upload_reserved)
        else:
            release_demo_upload_quota_reservation_if_needed(user_id, upload_reserved)

    if project is None:
        raise HTTPException(status_code=500, detail="Project import failed")

    if models_imported:
        logger.info("Imported %d model artifact(s) for project '%s'", models_imported, project.name)

    logger.info("Imported project '%s' (id=%s)", project.name, project.id)
    return await _project_to_detail(project, session)
