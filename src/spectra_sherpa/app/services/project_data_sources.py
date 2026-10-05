"""Infer and synchronize project data-source associations for workflow sheets."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, replace
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


def _bounded_fingerprint(source_ref: str) -> str:
    """Return a durable identity that fits the indexed database field.

    ``source_ref`` remains the readable, complete authority.  A grouped
    collection binds three independent SHA-256 values and can therefore exceed
    the historic 255-character fingerprint column on deployed PostgreSQL
    databases.  Persist a domain-qualified digest for equality and uniqueness
    instead of truncating any scientific authority.
    """

    return "source-ref-sha256:" + hashlib.sha256(source_ref.encode("utf-8")).hexdigest()


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
        asset_id = params.get("asset_id")
        asset_selection = str(asset_id) if asset_id not in (None, "") else "single-auto"
        if not experiment_id and not file_id:
            return None
        display = f"Experiment {experiment_id}"
        if file_id:
            display = f"{display} / File {file_id}"
        source_ref = _compact(("experiment", experiment_id, "file", file_id, stage, "asset", asset_selection))
        return DataSourceCandidate(
            display_name=display,
            source_type="upload",
            source_ref=source_ref,
            fingerprint=source_ref,
            node_id=node_id,
            metadata={
                "experiment_id": experiment_id,
                "file_id": file_id,
                "stage": stage,
                "asset_id": asset_id,
                "asset_selection": asset_selection,
            },
        )

    if node_type in {"data.collection_load", "data.load_group"}:
        if node_type == "data.collection_load":
            source_mode = "experiment_collection"
        else:
            source_mode = str(params.get("source_mode") or "local_folder")
        if source_mode == "experiment_collection":
            experiment_id = params.get("experiment_id")
            stage = str(params.get("stage") or "raw")
            asset_id = params.get("asset_id")
            asset_selection = str(asset_id) if asset_id not in (None, "") else "single-auto"
            selected_file_ids = params.get("selected_file_ids") or []
            selected_target = str(params.get("selected_target") or "")
            target_type = str(params.get("target_type") or "")
            group_column = str(params.get("group_column") or "")
            manifest_digest = str(params.get("source_manifest_sha256") or "")
            definition_digest = str(params.get("collection_definition_sha256") or "")
            scientific_digest = str(params.get("scientific_collection_sha256") or "")
            if (
                not isinstance(experiment_id, int)
                or isinstance(experiment_id, bool)
                or experiment_id < 1
                or stage not in {"raw", "preprocessed", "synthetic"}
                or not isinstance(selected_file_ids, list)
                or not all(isinstance(value, str) and value.isdigit() and int(value) > 0 for value in selected_file_ids)
                or not isinstance(asset_id, str)
                or asset_id != asset_id.strip()
                or len(manifest_digest) != 64
                or any(ch not in "0123456789abcdef" for ch in manifest_digest)
                or (
                    definition_digest
                    and (len(definition_digest) != 64 or any(ch not in "0123456789abcdef" for ch in definition_digest))
                )
                or (
                    scientific_digest
                    and (len(scientific_digest) != 64 or any(ch not in "0123456789abcdef" for ch in scientific_digest))
                )
                or (definition_digest and not scientific_digest)
            ):
                return None
            source_ref = _compact(
                (
                    "experiment",
                    experiment_id,
                    "collection",
                    stage,
                    "asset",
                    asset_selection,
                    "manifest",
                    manifest_digest,
                    "definition",
                    definition_digest or "absent",
                    "scientific",
                    scientific_digest or "unbound",
                    "members",
                    ",".join(selected_file_ids) or "all",
                    "target",
                    selected_target or "none",
                    "target-type",
                    target_type or "none",
                    "group",
                    group_column or "none",
                )
            )
            return DataSourceCandidate(
                display_name=params.get("group_title") or f"Experiment {experiment_id} collection",
                source_type="upload",
                source_ref=source_ref,
                fingerprint=_bounded_fingerprint(source_ref),
                node_id=node_id,
                metadata={
                    "source_mode": source_mode,
                    "experiment_id": experiment_id,
                    "stage": stage,
                    "asset_id": asset_id,
                    "asset_selection": asset_selection,
                    "source_manifest_sha256": manifest_digest,
                    "collection_definition_sha256": definition_digest or None,
                    "scientific_collection_sha256": scientific_digest or None,
                    "selected_file_ids": selected_file_ids,
                    "selected_target": selected_target or None,
                    "target_type": target_type or None,
                    "group_column": group_column or None,
                },
            )
        if source_mode != "local_folder":
            return None
        folder_path = str(params.get("folder_path") or "")
        pattern = str(params.get("pattern") or "*")
        recursive = params.get("recursive", False)
        sort_by = params.get("sort_by", "filename")
        asset_id = params.get("asset_id")
        asset_selection = str(asset_id) if asset_id not in (None, "") else "single-auto"
        if not folder_path:
            return None
        source_ref = _compact(("folder", folder_path, pattern, recursive, sort_by, "asset", asset_selection))
        return DataSourceCandidate(
            display_name=params.get("group_title") or _title_from_path(folder_path, "Folder Data"),
            source_type="external",
            source_ref=source_ref,
            fingerprint=source_ref,
            node_id=node_id,
            metadata={
                "folder_path": folder_path,
                "pattern": pattern,
                "recursive": recursive,
                "sort_by": sort_by,
                "asset_id": asset_id,
                "asset_selection": asset_selection,
            },
        )

    return None


async def _next_data_source_color(project_id: int, session: AsyncSession) -> str:
    count = await session.scalar(
        select(func.count(ProjectDataSource.id)).where(ProjectDataSource.project_id == project_id)
    )
    return DATA_SOURCE_COLORS[(count or 0) % len(DATA_SOURCE_COLORS)]


def _promote_generated_display_name(existing: ProjectDataSource, candidate: DataSourceCandidate) -> None:
    experiment_id = (existing.metadata_ or {}).get("experiment_id")
    placeholder = f"Experiment {experiment_id} collection" if experiment_id is not None else None
    if placeholder is not None and existing.display_name == placeholder and candidate.display_name != placeholder:
        existing.display_name = candidate.display_name


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
        _promote_generated_display_name(existing, candidate)
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
    *,
    display_names_by_node: dict[str, str] | None = None,
) -> list[ProjectDataSource]:
    """Synchronize workflow data bindings from its current source nodes."""
    if workflow.project_id is None:
        return []

    candidate_nodes = list(nodes if nodes is not None else workflow.nodes)
    candidates = [candidate for node in candidate_nodes if (candidate := describe_node_data_source(node)) is not None]
    if display_names_by_node:
        candidates = [
            replace(candidate, display_name=display_names_by_node.get(candidate.node_id, candidate.display_name))
            for candidate in candidates
        ]
    if candidates:
        if workflow.data_origin not in {"current", "example"}:
            workflow.data_origin = "current"
    else:
        workflow.data_origin = None
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
