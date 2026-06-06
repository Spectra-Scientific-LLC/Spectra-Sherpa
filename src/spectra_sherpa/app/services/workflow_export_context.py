from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from spectra_sherpa.app.core.config import settings
from spectra_sherpa.app.lib.scp_compat import resolve_scp_path
from spectra_sherpa.app.models.experiment_file import ExperimentFile
from spectra_sherpa.app.services.dag.nodes.data._utils import _SCP_KNOWN_DEFAULTS
from spectra_sherpa.app.services.prepared_data import (
    PreparedDataOverrides,
    load_prepared_data_overrides_for_source,
    normalize_relative_data_path,
)

if TYPE_CHECKING:
    from spectra_sherpa.app.models.workflow import Workflow


@dataclass(frozen=True)
class BundledSourceFile:
    absolute_path: Path
    source_relative_path: str
    bundle_relative_path: str


@dataclass(frozen=True)
class SourceExportSpec:
    node_id: str
    source: str
    loader_mode: str
    overrides: PreparedDataOverrides = field(default_factory=PreparedDataOverrides)
    bundle_files: tuple[BundledSourceFile, ...] = ()


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


async def build_workflow_export_context(workflow: Workflow, session: AsyncSession) -> WorkflowExportContext:
    specs: dict[str, SourceExportSpec] = {}

    for node in workflow.nodes:
        if node.node_type not in {"data.source", "data.my_dataset"}:
            continue

        source, parameters = _source_export_parameters(node.node_type, node.parameters or {})
        bundle_files = await _resolve_bundle_files(node.node_id, parameters, session)
        overrides = load_prepared_data_overrides_for_source(
            source=source,
            parameters=parameters,
            resolved_file_paths=[bundle.source_relative_path for bundle in bundle_files],
        )

        if bundle_files:
            loader_mode = "multi_file" if len(bundle_files) > 1 else "single_file"
        else:
            loader_mode = "builtin"

        specs[node.node_id] = SourceExportSpec(
            node_id=node.node_id,
            source=source,
            loader_mode=loader_mode,
            overrides=overrides,
            bundle_files=tuple(bundle_files),
        )

    return WorkflowExportContext(source_specs=specs)


def _source_export_parameters(node_type: str, parameters: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    if node_type == "data.my_dataset":
        dataset_id = parameters.get("dataset_id")
        source_parameters: dict[str, Any] = {
            "source": "experiment",
            "stage": parameters.get("stage") or "raw",
        }
        if dataset_id is not None:
            source_parameters["experiment_id"] = dataset_id
        return "experiment", source_parameters
    return str(parameters.get("source") or ""), parameters


async def _resolve_bundle_files(
    node_id: str,
    parameters: dict[str, Any],
    session: AsyncSession,
) -> list[BundledSourceFile]:
    source = str(parameters.get("source") or "")
    safe_node_dir = _safe_bundle_dir(node_id)

    if source == "experiment" and parameters.get("experiment_id") is not None:
        experiment_id = int(parameters["experiment_id"])
        stage = str(parameters.get("stage") or "raw")
        query = (
            select(ExperimentFile)
            .where(ExperimentFile.experiment_id == experiment_id, ExperimentFile.stage == stage)
            .order_by(ExperimentFile.created_at, ExperimentFile.id)
        )
        if parameters.get("file_id") is not None:
            query = query.where(ExperimentFile.id == int(parameters["file_id"]))
        result = await session.execute(query)
        files = list(result.scalars().all())
        return _bundle_specs_for_files(safe_node_dir, (_experiment_path(file) for file in files))

    if source == "file" and parameters.get("file_path"):
        return _bundle_specs_for_files(
            safe_node_dir,
            [normalize_relative_data_path(str(parameters["file_path"]))],
        )

    if source == "spectrochempy":
        return _resolve_scp_bundle_files(safe_node_dir, parameters)

    return []


def _resolve_scp_bundle_files(node_dir: str, parameters: dict[str, Any]) -> list[BundledSourceFile]:
    """Resolve a SpectroChemPy example dataset to a bundleable file.

    Mirrors the file-resolution logic in ``DataSourceNode._load_spectrochempy_example``
    and ``_gen_spectrochempy`` so the ZIP export includes the actual data file rather
    than relying on the user having SCP testdata installed.
    """
    example_dataset = str(parameters.get("example_dataset") or "irdata")
    example_file = str(parameters.get("example_file") or "")

    if example_file:
        scp_rel = f"{example_dataset}/{example_file}" if "/" not in example_file else example_file
    elif example_dataset in _SCP_KNOWN_DEFAULTS:
        scp_rel, _ = _SCP_KNOWN_DEFAULTS[example_dataset]
    else:
        # Unknown dataset and no explicit file — cannot resolve on disk.
        return []

    resolved = resolve_scp_path(scp_rel)
    if resolved is None or not resolved.exists():
        return []

    bundle_name = resolved.name
    return [
        BundledSourceFile(
            absolute_path=resolved,
            source_relative_path=scp_rel,
            bundle_relative_path=f"{node_dir}/{bundle_name}",
        )
    ]


def _bundle_specs_for_files(node_dir: str, source_relative_paths: list[str] | Any) -> list[BundledSourceFile]:
    rel_paths = list(source_relative_paths)
    counts: dict[str, int] = {}
    bundled: list[BundledSourceFile] = []

    for rel_path in rel_paths:
        normalized = normalize_relative_data_path(str(rel_path))
        source_path = (
            (settings.data_dir / normalized).resolve() if not Path(normalized).is_absolute() else Path(normalized)
        )
        name = Path(normalized).name
        count = counts.get(name, 0)
        counts[name] = count + 1
        bundle_name = name if count == 0 else f"{Path(name).stem}_{count}{Path(name).suffix}"
        bundled.append(
            BundledSourceFile(
                absolute_path=source_path,
                source_relative_path=normalized,
                bundle_relative_path=f"{node_dir}/{bundle_name}",
            )
        )
    return bundled


def _experiment_path(file: ExperimentFile) -> str:
    exp_dir = settings.data_dir / "experiments" / f"exp_{file.experiment_id:03d}"
    return normalize_relative_data_path(str((exp_dir / file.file_path).resolve()))


def _safe_bundle_dir(node_id: str) -> str:
    return "".join(ch if ch.isalnum() or ch in {"_", "-"} else "_" for ch in node_id) or "source"
