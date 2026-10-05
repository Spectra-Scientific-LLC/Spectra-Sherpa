from __future__ import annotations

import asyncio
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from spectra_sherpa.app.core.config import settings
from spectra_sherpa.app.lib.registered_reference_storage import read_registered_reference_sidecar
from spectra_sherpa.app.models.experiment import Experiment
from spectra_sherpa.app.models.experiment_file import ExperimentFile
from spectra_sherpa.app.services.collection_definitions import read_collection_definition
from spectra_sherpa.app.services.prepared_data import (
    PreparedDataOverrides,
    bind_explicit_target_selection,
    load_prepared_data_overrides,
    load_prepared_data_overrides_for_source,
    normalize_relative_data_path,
)
from spectra_sherpa.core.target_authority import admit_target_authority

if TYPE_CHECKING:
    from spectra_sherpa.app.models.workflow import Workflow


@dataclass(frozen=True)
class BundledSourceFile:
    absolute_path: Path
    source_relative_path: str
    bundle_relative_path: str
    external_reference: Mapping[str, Any] | None = None
    ingestion_authority: Mapping[str, Any] | None = None
    prepared_overrides: PreparedDataOverrides = field(default_factory=PreparedDataOverrides)
    member_file_name: str | None = None


@dataclass(frozen=True)
class SourceExportSpec:
    node_id: str
    source: str
    loader_mode: str
    overrides: PreparedDataOverrides = field(default_factory=PreparedDataOverrides)
    bundle_files: tuple[BundledSourceFile, ...] = ()
    collection_title: str | None = None
    collection_definition: Mapping[str, Any] | None = None


@dataclass(frozen=True)
class WorkflowExportContext:
    source_specs: dict[str, SourceExportSpec] = field(default_factory=dict)
    data_env_var: str = "SHERPA_DATA_DIR"

    def source_spec_for(self, node_id: str) -> SourceExportSpec | None:
        return self.source_specs.get(node_id)

    def iter_bundle_files(self) -> list[BundledSourceFile]:
        files: list[BundledSourceFile] = []
        for spec in self.source_specs.values():
            files.extend(spec.bundle_files)
        return files

    def iter_embedded_bundle_files(self) -> list[BundledSourceFile]:
        """Return only sources whose bytes are authorized for redistribution."""

        return [bundle for bundle in self.iter_bundle_files() if bundle.external_reference is None]

    def iter_external_reference_files(self) -> list[BundledSourceFile]:
        """Return registered sources represented by portable identity only."""

        return [bundle for bundle in self.iter_bundle_files() if bundle.external_reference is not None]


async def build_workflow_export_context(
    workflow: Workflow,
    session: AsyncSession,
    *,
    actor_user_id: int,
) -> WorkflowExportContext:
    """Resolve export inputs under the authority of the requesting actor.

    A workflow is user-controlled data.  Its persisted experiment and file IDs
    must never become filesystem read authority merely because the actor owns
    the workflow containing them.
    """
    if workflow.user_id != actor_user_id:
        raise ValueError("Workflow export source is not available")

    specs: dict[str, SourceExportSpec] = {}

    for node in workflow.nodes:
        if node.node_type not in {"data.file_load", "data.collection_load"}:
            continue

        source, parameters = _source_export_parameters(node.node_type, node.parameters or {})
        bundle_files = await _resolve_bundle_files(
            node.node_id,
            parameters,
            session,
            actor_user_id=actor_user_id,
            workflow_project_id=workflow.project_id,
        )
        overrides = load_prepared_data_overrides_for_source(
            source=source,
            parameters=parameters,
            resolved_file_paths=[bundle.source_relative_path for bundle in bundle_files],
        )
        if node.node_type == "data.file_load":
            target_authority = admit_target_authority(parameters.get("target_authority"))
            overrides = bind_explicit_target_selection(
                overrides,
                selected_target=target_authority.column if target_authority is not None else None,
                target_type=target_authority.target_type if target_authority is not None else None,
            )

        if node.node_type == "data.collection_load":
            loader_mode = "collection"
        elif bundle_files:
            loader_mode = "multi_file" if len(bundle_files) > 1 else "single_file"
        else:
            loader_mode = "builtin"

        definition = None
        collection_title = None
        if node.node_type == "data.collection_load":
            experiment_id = int(parameters["experiment_id"])
            experiment = await session.get(Experiment, experiment_id)
            if (
                experiment is None
                or experiment.user_id != actor_user_id
                or experiment.project_id != workflow.project_id
            ):
                raise ValueError("Workflow export source is not available")
            loaded_definition = await asyncio.to_thread(read_collection_definition, experiment_id)
            definition = loaded_definition.payload if loaded_definition is not None else None
            collection_title = experiment.name

        specs[node.node_id] = SourceExportSpec(
            node_id=node.node_id,
            source=source,
            loader_mode=loader_mode,
            overrides=overrides,
            bundle_files=tuple(bundle_files),
            collection_title=collection_title,
            collection_definition=definition,
        )

    return WorkflowExportContext(source_specs=specs)


def _source_export_parameters(node_type: str, parameters: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    if node_type == "data.file_load":
        return "experiment", {"source": "experiment", **parameters}
    if node_type == "data.collection_load":
        return "experiment_collection", {"source": "experiment_collection", **parameters}
    raise ValueError(f"Unsupported workflow export source operation: {node_type}")


async def _resolve_bundle_files(
    node_id: str,
    parameters: dict[str, Any],
    session: AsyncSession,
    *,
    actor_user_id: int,
    workflow_project_id: int | None,
) -> list[BundledSourceFile]:
    source = str(parameters.get("source") or "")
    safe_node_dir = _safe_bundle_dir(node_id)

    if source in {"experiment", "experiment_collection"} and parameters.get("experiment_id") is not None:
        experiment_id = int(parameters["experiment_id"])
        stage = str(parameters.get("stage") or "raw")
        query = (
            select(ExperimentFile)
            .join(Experiment, Experiment.id == ExperimentFile.experiment_id)
            .where(ExperimentFile.experiment_id == experiment_id, ExperimentFile.stage == stage)
            .where(Experiment.user_id == actor_user_id)
            .where(Experiment.project_id == workflow_project_id)
            .order_by(ExperimentFile.created_at, ExperimentFile.id)
        )
        if parameters.get("file_id") is not None:
            query = query.where(ExperimentFile.id == int(parameters["file_id"]))
        selected_file_ids = parameters.get("selected_file_ids") or []
        if selected_file_ids:
            selected_ids = [int(value) for value in selected_file_ids]
            query = query.where(ExperimentFile.id.in_(selected_ids))
        result = await session.execute(query)
        files = list(result.scalars().all())
        if not files:
            raise ValueError("Workflow export source is not available")
        if selected_file_ids and {file.id for file in files} != set(selected_ids):
            raise ValueError("Workflow export selected member is not available")
        return _bundle_specs_for_files(
            safe_node_dir,
            ((_experiment_path(file), str(file.file_path)) for file in files),
        )

    if source == "file" and parameters.get("file_path"):
        # Prototype direct-path sources had no durable ownership identity.  Do
        # not infer authority from a path string; canonical sources bind an
        # exact owned experiment/file record instead.
        raise ValueError("Workflow export source is not available")

    return []


def _bundle_specs_for_files(node_dir: str, source_relative_paths: list[str] | Any) -> list[BundledSourceFile]:
    rel_paths = list(source_relative_paths)
    counts: dict[str, int] = {}
    bundled: list[BundledSourceFile] = []

    for entry in rel_paths:
        rel_path, member_file_name = entry if isinstance(entry, tuple) else (entry, None)
        normalized = normalize_relative_data_path(str(rel_path))
        source_path = (
            (settings.data_dir / normalized).resolve() if not Path(normalized).is_absolute() else Path(normalized)
        )
        external_reference = read_registered_reference_sidecar(source_path)
        name = (
            Path(str(external_reference["member_path"])).name
            if external_reference is not None
            else Path(normalized).name
        )
        count = counts.get(name, 0)
        counts[name] = count + 1
        bundle_name = name if count == 0 else f"{Path(name).stem}_{count}{Path(name).suffix}"
        bundled.append(
            BundledSourceFile(
                absolute_path=source_path,
                source_relative_path=normalized,
                bundle_relative_path=f"{node_dir}/{bundle_name}",
                external_reference=external_reference,
                prepared_overrides=load_prepared_data_overrides(file_path=normalized),
                member_file_name=member_file_name or Path(normalized).name,
            )
        )
    return bundled


def _experiment_path(file: ExperimentFile) -> str:
    exp_dir = settings.data_dir / "experiments" / f"exp_{file.experiment_id:03d}"
    return normalize_relative_data_path(str((exp_dir / file.file_path).resolve()))


def _safe_bundle_dir(node_id: str) -> str:
    return "".join(ch if ch.isalnum() or ch in {"_", "-"} else "_" for ch in node_id) or "source"
