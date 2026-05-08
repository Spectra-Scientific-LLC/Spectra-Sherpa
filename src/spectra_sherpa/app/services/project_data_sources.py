"""Infer and synchronize project data-source associations for workflow sheets."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from spectra_sherpa.app.core.constants import AI_PURPLE
from spectra_sherpa.app.models.advisor_channel import AdvisorChannel
from spectra_sherpa.app.models.project_data_source import ProjectDataSource, WorkflowDataSource
from spectra_sherpa.app.models.workflow import Workflow

DATA_SOURCE_COLORS = ["#3b82f6", "#22c55e", "#f59e0b", "#ef4444", "#8b5cf6", "#64748b"]


@dataclass(frozen=True)
class DataSourceCandidate:
    display_name: str
    source_type: str
    source_ref: str
    fingerprint: str
    node_id: str
    metadata: dict[str, Any]


def effective_workflow_tab_color(workflow: Workflow) -> str | None:
    """Return the color the sheet tab should display today."""
    if workflow.tab_color_override:
        return workflow.tab_color_override
    if workflow.color_source == "ai":
        return AI_PURPLE
    if workflow.primary_data_source is not None:
        return workflow.primary_data_source.color
    return None


def _node_value(node: Any, attr: str, default: Any = None) -> Any:
    if isinstance(node, dict):
        return node.get(attr, default)
    return getattr(node, attr, default)


def _node_parameters(node: Any) -> dict[str, Any]:
    params = _node_value(node, "parameters", None)
    if params is None:
        params = _node_value(node, "params", None)
    return params if isinstance(params, dict) else {}


def _compact(parts: Iterable[Any], sep: str = ":") -> str:
    return sep.join(str(part) for part in parts if part not in (None, ""))


def _title_from_path(value: str | None, fallback: str) -> str:
    if not value:
        return fallback
    return Path(value).name or value


def describe_node_data_source(node: Any) -> DataSourceCandidate | None:
    """Extract a project data-source identity from a persisted or request node."""
    node_type = _node_value(node, "node_type", None) or _node_value(node, "type", None)
    node_id = str(_node_value(node, "node_id", None) or _node_value(node, "id", ""))
    params = _node_parameters(node)

    if node_type == "data.file_load":
        experiment_id = params.get("experiment_id")
        file_id = params.get("file_id")
        stage = params.get("stage") or "raw"
        if not experiment_id and not file_id:
            return None
        display = f"Experiment {experiment_id}"
        if file_id:
            display = f"{display} / File {file_id}"
        source_ref = _compact(("experiment", experiment_id, "file", file_id, stage))
        return DataSourceCandidate(
            display_name=display,
            source_type="upload",
            source_ref=source_ref,
            fingerprint=source_ref,
            node_id=node_id,
            metadata={"experiment_id": experiment_id, "file_id": file_id, "stage": stage},
        )

    if node_type == "data.my_dataset":
        dataset_id = params.get("dataset_id")
        if not dataset_id:
            return None
        source_ref = _compact(("dataset", dataset_id))
        return DataSourceCandidate(
            display_name=f"Dataset {dataset_id}",
            source_type="upload",
            source_ref=source_ref,
            fingerprint=source_ref,
            node_id=node_id,
            metadata={"dataset_id": dataset_id},
        )

    if node_type == "data.load_group":
        folder_path = str(params.get("folder_path") or "")
        pattern = str(params.get("pattern") or "*")
        if not folder_path:
            return None
        source_ref = _compact(("folder", folder_path, pattern))
        return DataSourceCandidate(
            display_name=params.get("group_title") or _title_from_path(folder_path, "Folder Data"),
            source_type="external",
            source_ref=source_ref,
            fingerprint=source_ref,
            node_id=node_id,
            metadata={"folder_path": folder_path, "pattern": pattern},
        )

    if node_type != "data.source":
        return None

    experiment_id = params.get("experiment_id")
    file_id = params.get("file_id")
    library_id = params.get("library_id")
    file_path = str(params.get("file_path") or "")
    source = str(params.get("source") or "spectrochempy")
    stage = params.get("stage") or "raw"

    if experiment_id or file_id:
        source_ref = _compact(("experiment", experiment_id, "file", file_id, stage))
        display = f"Experiment {experiment_id}" if experiment_id else "Experiment Data"
        if file_id:
            display = f"{display} / File {file_id}"
        return DataSourceCandidate(
            display_name=display,
            source_type="upload",
            source_ref=source_ref,
            fingerprint=source_ref,
            node_id=node_id,
            metadata={"experiment_id": experiment_id, "file_id": file_id, "stage": stage},
        )

    if library_id:
        source_ref = _compact(("library", library_id))
        return DataSourceCandidate(
            display_name=f"Library Entry {library_id}",
            source_type="external",
            source_ref=source_ref,
            fingerprint=source_ref,
            node_id=node_id,
            metadata={"library_id": library_id},
        )

    if source == "file" and file_path:
        source_ref = _compact(("file", file_path))
        return DataSourceCandidate(
            display_name=_title_from_path(file_path, "File Data"),
            source_type="external",
            source_ref=source_ref,
            fingerprint=source_ref,
            node_id=node_id,
            metadata={"file_path": file_path},
        )

    if source == "sklearn":
        dataset = str(params.get("sklearn_dataset") or "iris")
        source_ref = _compact(("sklearn", dataset))
        return DataSourceCandidate(
            display_name=f"Sklearn: {dataset.replace('_', ' ').title()}",
            source_type="example",
            source_ref=source_ref,
            fingerprint=source_ref,
            node_id=node_id,
            metadata={"source": source, "dataset": dataset},
        )

    if source == "eigenvector":
        dataset = str(params.get("eigenvector_dataset") or "")
        if not dataset:
            return None
        source_ref = _compact(("eigenvector", dataset))
        return DataSourceCandidate(
            display_name=f"Eigenvector: {dataset.replace('_', ' ').title()}",
            source_type="example",
            source_ref=source_ref,
            fingerprint=source_ref,
            node_id=node_id,
            metadata={"source": source, "dataset": dataset},
        )

    dataset = str(params.get("example_dataset") or "irdata")
    example_file = str(params.get("example_file") or "")
    source_ref = _compact(("spectrochempy", dataset, example_file))
    display_name = f"SpectroChemPy: {dataset}"
    if example_file:
        display_name = f"{display_name} / {_title_from_path(example_file, example_file)}"
    return DataSourceCandidate(
        display_name=display_name,
        source_type="example",
        source_ref=source_ref,
        fingerprint=source_ref,
        node_id=node_id,
        metadata={"source": source, "dataset": dataset, "example_file": example_file or None},
    )


async def _next_data_source_color(project_id: int, session: AsyncSession) -> str:
    count = await session.scalar(
        select(func.count(ProjectDataSource.id)).where(ProjectDataSource.project_id == project_id)
    )
    return DATA_SOURCE_COLORS[(count or 0) % len(DATA_SOURCE_COLORS)]


async def _find_or_create_data_source(
    project_id: int,
    candidate: DataSourceCandidate,
    session: AsyncSession,
) -> ProjectDataSource:
    result = await session.execute(
        select(ProjectDataSource).where(
            ProjectDataSource.project_id == project_id,
            ProjectDataSource.fingerprint == candidate.fingerprint,
        )
    )
    existing = result.scalar_one_or_none()
    if existing is not None:
        return existing

    sort_order = await session.scalar(
        select(func.count(ProjectDataSource.id)).where(ProjectDataSource.project_id == project_id)
    )
    data_source = ProjectDataSource(
        project_id=project_id,
        display_name=candidate.display_name,
        source_type=candidate.source_type,
        source_ref=candidate.source_ref,
        fingerprint=candidate.fingerprint,
        color=await _next_data_source_color(project_id, session),
        metadata_=candidate.metadata,
        sort_order=sort_order or 0,
    )
    session.add(data_source)
    await session.flush()
    return data_source


async def sync_workflow_data_sources(
    workflow: Workflow,
    session: AsyncSession,
    nodes: Iterable[Any] | None = None,
) -> list[ProjectDataSource]:
    """Synchronize workflow data bindings from its current source nodes."""
    if workflow.project_id is None:
        return []

    candidate_nodes = list(nodes if nodes is not None else workflow.nodes)
    candidates = [candidate for node in candidate_nodes if (candidate := describe_node_data_source(node)) is not None]
    deduped: dict[str, DataSourceCandidate] = {}
    for candidate in candidates:
        deduped.setdefault(candidate.fingerprint, candidate)

    await session.execute(delete(WorkflowDataSource).where(WorkflowDataSource.workflow_id == workflow.id))

    data_sources: list[ProjectDataSource] = []
    for index, candidate in enumerate(deduped.values()):
        data_source = await _find_or_create_data_source(workflow.project_id, candidate, session)
        data_sources.append(data_source)
        session.add(
            WorkflowDataSource(
                workflow_id=workflow.id,
                data_source_id=data_source.id,
                role="primary" if index == 0 else "secondary",
                first_seen_node_id=candidate.node_id,
            )
        )

    workflow.primary_data_source_id = data_sources[0].id if data_sources else None
    if workflow.tab_color_override:
        workflow.color_source = "manual"
        workflow.tab_color = workflow.tab_color_override
    elif workflow.color_source == "ai":
        from spectra_sherpa.app.core.constants import AI_PURPLE

        workflow.tab_color = AI_PURPLE
    elif data_sources:
        workflow.color_source = "data"
        workflow.tab_color = data_sources[0].color
    else:
        workflow.color_source = "blank"
        workflow.tab_color = None

    return data_sources


async def ensure_sheet_advisor_channel(
    workflow: Workflow,
    session: AsyncSession,
    color: str | None = None,
) -> AdvisorChannel | None:
    """Ensure a workflow sheet has one advisor channel; trial tabs reuse this."""
    if workflow.project_id is None:
        return None

    result = await session.execute(
        select(AdvisorChannel).where(
            AdvisorChannel.project_id == workflow.project_id,
            AdvisorChannel.workflow_id == workflow.id,
            AdvisorChannel.channel_type == "sheet",
        )
    )
    channel = result.scalar_one_or_none()
    if channel is not None:
        channel.title = workflow.name
        channel.color = color if color is not None else effective_workflow_tab_color(workflow)
        return channel

    channel = AdvisorChannel(
        project_id=workflow.project_id,
        workflow_id=workflow.id,
        channel_type="sheet",
        title=workflow.name,
        color=color if color is not None else effective_workflow_tab_color(workflow),
    )
    session.add(channel)
    await session.flush()
    return channel


async def ensure_project_advisor_channel(
    project_id: int,
    title: str,
    session: AsyncSession,
) -> AdvisorChannel:
    """Ensure the default project-level advisor channel exists."""
    result = await session.execute(
        select(AdvisorChannel).where(
            AdvisorChannel.project_id == project_id,
            AdvisorChannel.workflow_id.is_(None),
            AdvisorChannel.channel_type == "project",
        )
    )
    channel = result.scalar_one_or_none()
    if channel is not None:
        channel.title = "Project Advisor"
        return channel

    channel = AdvisorChannel(
        project_id=project_id,
        workflow_id=None,
        channel_type="project",
        title="Project Advisor",
        color=None,
    )
    session.add(channel)
    await session.flush()
    return channel
