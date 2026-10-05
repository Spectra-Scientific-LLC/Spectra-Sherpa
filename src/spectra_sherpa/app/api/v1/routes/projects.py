"""
Project API endpoints — CRUD, link/unlink, versioning, and export/import.
"""

from __future__ import annotations

import asyncio
import copy
import io
import json
import logging
import os
import re
import shutil
import stat
import tempfile
import uuid
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from types import SimpleNamespace
from typing import Annotated, Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, Response
from sqlalchemy import func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from starlette.background import BackgroundTask

from spectra_sherpa.app.api.deps import (
    consume_reserved_demo_upload_quota_if_needed,
    demo_guard,
    get_current_user,
    get_session,
    release_demo_upload_quota_reservation_if_needed,
    require_project,
    reserve_demo_upload_quota_or_429,
)
from spectra_sherpa.app.api.v1.routes._http_utils import attachment_headers, safe_download_stem
from spectra_sherpa.app.contracts.project_access import accessible_project_ids, uses_managed_project_access
from spectra_sherpa.app.contracts.scientific_access import require_scientific_access
from spectra_sherpa.app.core.config import app_config, settings
from spectra_sherpa.app.core.security import check_export_allowed
from spectra_sherpa.app.db.session import async_session
from spectra_sherpa.app.lib.collection_assembly import MAX_COLLECTION_MEMBERS, source_collection_manifest
from spectra_sherpa.app.lib.collection_definition import (
    MAX_COLLECTION_DEFINITION_BYTES,
    ValidatedCollectionDefinition,
    scientific_collection_identity_from_digest,
    scientific_dataset_projection,
    scientific_dataset_projection_sha256,
    validate_collection_definition,
)
from spectra_sherpa.app.lib.reference_materialization import (
    ReferenceMaterializationError,
    materialize_reference_projection,
    portable_reference_manifest,
)
from spectra_sherpa.app.lib.registered_reference_storage import (
    RegisteredReferenceStorageError,
    read_registered_reference_sidecar,
    write_registered_reference_sidecar,
)
from spectra_sherpa.app.lib.workflow_purpose import (
    MANAGED_CANDIDATE_AUTHORITY,
    WorkflowPurposeError,
    require_workflow_purpose,
)
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
from spectra_sherpa.app.models.workflow_version import WorkflowVersion
from spectra_sherpa.app.schemas.projects import (
    AdvisorChannelOut,
    AdvisorChannelUpdate,
    ExperimentBrief,
    ImportedApplicationIdentity,
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
from spectra_sherpa.app.services.collection_definitions import (
    read_collection_definition,
    write_collection_definition,
)
from spectra_sherpa.app.services.dag.canonical_workbench_baseline import (
    CanonicalWorkbenchBaselineError,
    canonical_workbench_baseline_from_records,
)
from spectra_sherpa.app.services.dag.saved_graph_admission import (
    CURRENT_CLASSIFIER_VALIDATION_SEMANTICS,
    SavedGraphAdmissionError,
    admit_saved_workflow_graph,
)
from spectra_sherpa.app.services.experiments import (
    ALLOWED_STAGES,
    add_experiment_file,
    delete_experiment_files,
    ensure_experiment_dirs,
    experiment_dir,
    metadata_path_for,
    read_metadata,
    relative_to_data_dir,
    resolve_data_path,
    write_metadata,
)
from spectra_sherpa.app.services.model_application import load_project_dataset
from spectra_sherpa.app.services.model_store import (
    ModelArtifactCollisionError,
    ModelManifestJSONError,
    parse_model_manifest_json,
)
from spectra_sherpa.app.services.prepared_data import (
    PREPARED_DATA_SIDECAR_MAX_BYTES,
    PreparedDataOverrides,
    load_prepared_data_overrides_strict,
    save_prepared_data_overrides,
    sidecar_path,
)
from spectra_sherpa.app.services.project_data_sources import (
    effective_workflow_tab_color,
    ensure_project_advisor_channel,
)
from spectra_sherpa.app.services.sherpa_object import (
    PROJECT_PAYLOAD,
    SHERPA_OBJECT_MANIFEST,
    ArchiveMember,
    SherpaObjectError,
    inspect_archive_bytes,
    preflight_zip_central_directory,
    sha256_bytes,
    validate_archive_bytes,
    write_archive_to_path,
)
from spectra_sherpa.core.node_identity import canonical_node_type
from spectra_sherpa.core.target_authority import admit_target_authority

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/projects")


# ── Helpers ──────────────────────────────────────────────────────────


def _admit_project_snapshot_graphs(project_json: dict[str, Any]) -> None:
    """Admit every archived workflow before project import mutates storage."""

    for workflow_index, workflow in enumerate(project_json.get("workflows") or []):
        if not isinstance(workflow, dict):
            raise HTTPException(status_code=400, detail=f"Archived workflow {workflow_index} must be an object")
        try:
            purpose = require_workflow_purpose(workflow.get("purpose"))
        except WorkflowPurposeError as exc:
            raise HTTPException(
                status_code=400,
                detail=f"Archived workflow {workflow_index} purpose is not current: {exc}",
            ) from exc
        try:
            admission = admit_saved_workflow_graph(
                workflow.get("nodes") or [],
                workflow.get("edges") or [],
                classifier_validation_semantics=workflow.get("classifier_validation_semantics"),
            )
        except SavedGraphAdmissionError as exc:
            raise HTTPException(
                status_code=400,
                detail=f"Archived workflow {workflow_index} is not current: {exc}",
            ) from exc
        workflow["nodes"] = list(admission.nodes)
        workflow["edges"] = list(admission.edges)
        workflow["classifier_validation_semantics"] = CURRENT_CLASSIFIER_VALIDATION_SEMANTICS
        if purpose == "managed_candidate_authority":
            try:
                canonical_workbench_baseline_from_records(
                    workflow_id=workflow.get("id"),
                    stored_integrity_hash=workflow.get("integrity_hash"),
                    nodes=[SimpleNamespace(**node) for node in workflow.get("nodes") or []],
                    edges=[SimpleNamespace(**edge) for edge in workflow.get("edges") or []],
                )
            except (CanonicalWorkbenchBaselineError, TypeError) as exc:
                raise HTTPException(
                    status_code=400,
                    detail=f"Archived managed workflow {workflow_index} is not admissible: {exc}",
                ) from exc
    for child_index, child in enumerate(project_json.get("children") or []):
        if not isinstance(child, dict):
            raise HTTPException(status_code=400, detail=f"Archived child project {child_index} must be an object")
        _admit_project_snapshot_graphs(child)


def _safe_parse_metrics(metrics_json: str | None) -> dict | None:
    """Parse a JSON metrics blob, returning None on missing or malformed input."""
    if not metrics_json:
        return None
    try:
        return json.loads(metrics_json)
    except (json.JSONDecodeError, TypeError):
        return None


def _safe_json_value(value: str | None) -> Any:
    """Parse stored JSON provenance while preserving readable legacy text."""
    if value is None:
        return None
    try:
        return json.loads(value)
    except (json.JSONDecodeError, TypeError):
        return value


def _json_text_or_none(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


_GENERIC_TEMPLATE_DATA_DESCRIPTION = "Bundled example data materialized from template"
PROJECT_DATA_PREFIX = "data/experiments"
PROJECT_PREPARED_DATA_MAX_BYTES = 64 * 1024
PROJECT_ARCHIVE_FORMAT_VERSION = "0.5"
PROJECT_STORAGE_SNAPSHOT_SCHEMA_VERSION = "spectrasherpa-project-storage-snapshot/2"
PROJECT_ARCHIVE_UNCOMPRESSED_MULTIPLIER = 10
PROJECT_ARCHIVE_RETAINED_BYTES_MAX = 256 * 1024 * 1024


class ProjectSnapshotStateError(ValueError):
    """Live private storage no longer equals the saved project snapshot."""


@dataclass(frozen=True)
class _BoundExperimentStorage:
    definition: ValidatedCollectionDefinition | None
    prepared_by_file: dict[str, PreparedDataOverrides]
    source_manifest_sha256: str


@dataclass
class _SnapshotBuildBudget:
    file_count: int = 0
    retained_bytes: int = 0

    def admit(self, *, files: int, retained_bytes: int) -> None:
        self.file_count += files
        self.retained_bytes += retained_bytes
        if self.file_count > MAX_COLLECTION_MEMBERS:
            raise ProjectSnapshotStateError("Project snapshot exceeds the portable file-count limit")
        if self.retained_bytes > PROJECT_ARCHIVE_RETAINED_BYTES_MAX:
            raise ProjectSnapshotStateError("Project snapshot exceeds the portable aggregate-byte limit")


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

            sample_count = entry.get("n_samples")
            if type(sample_count) is not int:
                sample_count = _count_from_label(label, "samples")
            if sample_count is not None:
                _append_fact(facts, f"{sample_count} samples")

            feature_count = entry.get("n_features")
            if type(feature_count) is int:
                axis_title = str(entry.get("x_title") or "").strip().lower()
                feature_noun = {
                    "channel": "channels",
                    "wavelength": "wavelengths",
                    "variable": "variables",
                }.get(axis_title, "features")
                _append_fact(facts, f"{feature_count} {feature_noun}")
            else:
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


def _as_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _normalize_archive_member_path(path: Any) -> str:
    raw = str(path or "").replace("\\", "/").strip()
    candidate = PurePosixPath(raw)
    parts = [part for part in candidate.parts if part not in {"", "."}]
    if not parts or candidate.is_absolute() or any(part == ".." for part in parts):
        raise ValueError("Unsafe archive member path")
    return "/".join(parts)


def _normalize_experiment_file_path(file_path: Any, stage: Any) -> str:
    stage_name = str(stage or "raw")
    if stage_name not in ALLOWED_STAGES:
        raise ValueError("Invalid experiment file stage")

    raw = str(file_path or "").replace("\\", "/").strip()
    candidate = PurePosixPath(raw)
    parts = [part for part in candidate.parts if part not in {"", "."}]
    if not parts or candidate.is_absolute() or any(part == ".." for part in parts):
        raise ValueError("Unsafe experiment file path")
    if parts[0] not in ALLOWED_STAGES:
        parts.insert(0, stage_name)
    return "/".join(parts)


def _experiment_file_path(experiment_id: int, file_path: Any, stage: Any) -> tuple[str, Path]:
    rel_path = _normalize_experiment_file_path(file_path, stage)
    exp_dir = experiment_dir(experiment_id).resolve()
    target_path = exp_dir / rel_path
    if not target_path.parent.resolve().is_relative_to(exp_dir) or target_path.is_symlink():
        raise ValueError("Unsafe experiment file path")
    return rel_path, target_path


def _project_data_archive_member(old_experiment_id: int, relative_file_path: str) -> str:
    return f"{PROJECT_DATA_PREFIX}/{old_experiment_id}/{relative_file_path}"


def _project_prepared_data_archive_member(old_experiment_id: int, relative_file_path: str) -> str:
    identity = sha256_bytes(relative_file_path.encode("utf-8"))
    return f"{PROJECT_DATA_PREFIX}/{old_experiment_id}/prepared/{identity}.json"


def _project_collection_definition_archive_member(old_experiment_id: int) -> str:
    return f"{PROJECT_DATA_PREFIX}/{old_experiment_id}/collection-definition.json"


def _canonical_prepared_data_bytes(overrides: PreparedDataOverrides) -> bytes:
    return json.dumps(
        overrides.to_sidecar_dict(),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def _read_bounded_regular_source(path: Path, *, expected_size: int | None = None) -> bytes:
    """Read one admitted project source without following links or over-allocating."""

    max_bytes = settings.max_file_size_mb * 1024 * 1024
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_BINARY", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise ProjectSnapshotStateError("Experiment snapshot source file is unavailable") from exc
    try:
        observed = os.fstat(descriptor)
        if not stat.S_ISREG(observed.st_mode):
            raise ProjectSnapshotStateError("Experiment snapshot source is not a regular file")
        if observed.st_size > max_bytes:
            raise ProjectSnapshotStateError("Experiment snapshot source exceeds the project file-size limit")
        if expected_size is not None and observed.st_size != expected_size:
            raise ProjectSnapshotStateError("Project source bytes changed after the saved version was created")
        chunks: list[bytes] = []
        remaining = max_bytes + 1
        while remaining:
            chunk = os.read(descriptor, min(1024 * 1024, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        data = b"".join(chunks)
        if len(data) > max_bytes:
            raise ProjectSnapshotStateError("Experiment snapshot source exceeds the project file-size limit")
        if expected_size is not None and len(data) != expected_size:
            raise ProjectSnapshotStateError("Project source bytes changed after the saved version was created")
        return data
    finally:
        os.close(descriptor)


def _registered_reference_for_source(
    source_path: Path,
    *,
    size_bytes: int,
    sha256: str,
) -> dict[str, Any] | None:
    """Classify only an exact, sidecar-authorized registered source.

    Byte identity alone is deliberately insufficient. A paid/local scientist
    may upload the same bytes through the ordinary upload path, in which case
    the project remains an ordinary byte-bearing project. Only the dedicated
    registered-reference admission path writes the validated sidecar that
    activates portable external-reference treatment.
    """

    try:
        reference = read_registered_reference_sidecar(source_path)
    except RegisteredReferenceStorageError as exc:
        raise ProjectSnapshotStateError("Registered-reference source authority is invalid") from exc
    if reference is None:
        return None
    if reference["member_size_bytes"] != size_bytes or reference["member_sha256"] != sha256:
        raise ProjectSnapshotStateError("Registered-reference source bytes differ from their authority")
    return reference


def _bind_experiment_storage_snapshot(
    experiment: dict[str, Any],
    budget: _SnapshotBuildBudget | None = None,
) -> _BoundExperimentStorage:
    """Bind exact live files, sidecars, and optional definition into a saved snapshot."""

    experiment_id = _as_int(experiment.get("id"))
    if experiment_id is None:
        raise ProjectSnapshotStateError("Experiment snapshot is missing its durable identity")
    files = experiment.get("files")
    if not isinstance(files, list) or len(files) > MAX_COLLECTION_MEMBERS:
        raise ProjectSnapshotStateError("Experiment snapshot exceeds the portable file-count limit")
    admitted: list[tuple[dict[str, Any], str, Path, bytes, dict[str, Any] | None]] = []
    aggregate_bytes = 0
    admitted_paths: set[str] = set()
    for file_data in files:
        if not isinstance(file_data, dict):
            raise ProjectSnapshotStateError("Experiment snapshot contains an invalid file record")
        try:
            rel_path, source_path = _experiment_file_path(
                experiment_id,
                file_data.get("file_path"),
                file_data.get("stage"),
            )
        except ValueError as exc:
            raise ProjectSnapshotStateError("Experiment snapshot contains an unsafe file path") from exc
        if rel_path.casefold() in admitted_paths:
            raise ProjectSnapshotStateError("Experiment snapshot contains a duplicate portable file path")
        admitted_paths.add(rel_path.casefold())
        try:
            observed = source_path.lstat()
        except OSError as exc:
            raise ProjectSnapshotStateError("Experiment snapshot source file is unavailable") from exc
        if stat.S_ISLNK(observed.st_mode) or not stat.S_ISREG(observed.st_mode):
            raise ProjectSnapshotStateError("Experiment snapshot source is not a regular file")
        data = _read_bounded_regular_source(source_path, expected_size=observed.st_size)
        source_sha = sha256_bytes(data)
        external_reference = _registered_reference_for_source(
            source_path,
            size_bytes=len(data),
            sha256=source_sha,
        )
        if external_reference is None:
            aggregate_bytes += observed.st_size
        if aggregate_bytes > PROJECT_ARCHIVE_RETAINED_BYTES_MAX:
            raise ProjectSnapshotStateError("Experiment snapshot exceeds the portable aggregate-byte limit")
        try:
            prepared_path = sidecar_path(file_path=str(source_path), source=None, name=None)
            prepared_observed = prepared_path.lstat()
        except FileNotFoundError:
            aggregate_bytes += len(_canonical_prepared_data_bytes(PreparedDataOverrides()))
        except (OSError, ValueError) as exc:
            raise ProjectSnapshotStateError("Prepared-data sidecar is invalid or unavailable") from exc
        else:
            if stat.S_ISLNK(prepared_observed.st_mode) or not stat.S_ISREG(prepared_observed.st_mode):
                raise ProjectSnapshotStateError("Prepared-data sidecar is invalid or unavailable")
            if prepared_observed.st_size > PREPARED_DATA_SIDECAR_MAX_BYTES:
                raise ProjectSnapshotStateError("Prepared-data sidecar exceeds the portable size limit")
            aggregate_bytes += prepared_observed.st_size
        if aggregate_bytes > PROJECT_ARCHIVE_RETAINED_BYTES_MAX:
            raise ProjectSnapshotStateError("Experiment snapshot exceeds the portable aggregate-byte limit")
        admitted.append((file_data, rel_path, source_path, data, external_reference))

    (budget or _SnapshotBuildBudget()).admit(files=len(admitted), retained_bytes=aggregate_bytes)

    captured: dict[str, dict[str, Any]] = {}
    prepared_by_file: dict[str, PreparedDataOverrides] = {}
    for file_data, rel_path, source_path, data, external_reference in admitted:
        try:
            prepared = load_prepared_data_overrides_strict(file_path=str(source_path))
        except ValueError as exc:
            raise ProjectSnapshotStateError("Prepared-data sidecar is invalid or unavailable") from exc
        prepared_data = _canonical_prepared_data_bytes(prepared)
        prepared_sha = sha256_bytes(prepared_data)
        source_sha = sha256_bytes(data)
        file_data.update(
            {
                "file_path": rel_path,
                "saved_size_bytes": len(data),
                "saved_sha256": source_sha,
                "saved_prepared_data_sha256": prepared_sha,
                "external_reference": external_reference,
            }
        )
        captured[rel_path] = {
            "file_name": rel_path,
            "size_bytes": len(data),
            "sha256": source_sha,
            "prepared_data_sha256": prepared_sha,
        }
        prepared_by_file[rel_path] = prepared

    try:
        definition = read_collection_definition(experiment_id)
    except ValueError as exc:
        raise ProjectSnapshotStateError("Saved collection definition is invalid") from exc
    experiment["collection_definition"] = definition.payload if definition is not None else None
    experiment["collection_definition_sha256"] = definition.sha256 if definition is not None else None
    experiment["collection_definition_size_bytes"] = len(definition.canonical_bytes) if definition is not None else 0
    experiment["collection_source_manifest_sha256"] = None
    experiment["scientific_collection_schema_version"] = None
    experiment["scientific_collection_sha256"] = None
    experiment["storage_snapshot_schema_version"] = PROJECT_STORAGE_SNAPSHOT_SCHEMA_VERSION
    ordered_names = list(captured)
    if definition is not None:
        ordered_names = []
        for row in definition.payload["rows"]:
            name = str(row["file_name"])
            if name not in ordered_names:
                ordered_names.append(name)
        if set(ordered_names) != set(captured):
            raise ProjectSnapshotStateError("Collection definition does not cover the saved file inventory")
    source_manifest = source_collection_manifest([captured[name] for name in ordered_names])
    return _BoundExperimentStorage(
        definition=definition,
        prepared_by_file=prepared_by_file,
        source_manifest_sha256=str(source_manifest["manifest_digest"]),
    )


def _require_bound_storage_still_current(
    experiment: dict[str, Any],
    bound: _BoundExperimentStorage,
) -> None:
    """Close the capture-to-scientific-load race before persisting a version."""

    experiment_id = _as_int(experiment.get("id"))
    if experiment_id is None:
        raise ProjectSnapshotStateError("Experiment snapshot is missing its durable identity")
    for file_data in experiment.get("files", []):
        rel_path, source_path = _experiment_file_path(
            experiment_id,
            file_data.get("file_path"),
            file_data.get("stage"),
        )
        data = _read_bounded_regular_source(source_path, expected_size=file_data.get("saved_size_bytes"))
        source_sha = sha256_bytes(data)
        if source_sha != file_data.get("saved_sha256"):
            raise ProjectSnapshotStateError("Project source changed while the snapshot was being created")
        current_reference = _registered_reference_for_source(
            source_path,
            size_bytes=len(data),
            sha256=source_sha,
        )
        if current_reference != file_data.get("external_reference"):
            raise ProjectSnapshotStateError(
                "Registered-reference authority changed while the snapshot was being created"
            )
        try:
            current_prepared = load_prepared_data_overrides_strict(file_path=str(source_path))
        except ValueError as exc:
            raise ProjectSnapshotStateError("Prepared-data sidecar is invalid or unavailable") from exc
        captured = bound.prepared_by_file.get(rel_path)
        if captured is None or _canonical_prepared_data_bytes(current_prepared) != _canonical_prepared_data_bytes(
            captured
        ):
            raise ProjectSnapshotStateError("Prepared-data semantics changed while the snapshot was being created")


def _prepare_project_export_snapshot(snapshot: dict[str, Any]) -> dict[str, Any]:
    """Return an export payload copy with an explicit project archive format marker."""
    export_snapshot = copy.deepcopy(snapshot)
    archive_format = export_snapshot.get("archive_format")
    if not isinstance(archive_format, dict):
        archive_format = {}
    archive_format.update(
        {
            "schema": "spectra_sherpa_project_archive",
            "version": PROJECT_ARCHIVE_FORMAT_VERSION,
            "data_members": PROJECT_DATA_PREFIX,
        }
    )
    export_snapshot["archive_format"] = archive_format
    return export_snapshot


def _project_archive_response_headers(filename: str, snapshot: dict[str, Any]) -> dict[str, str]:
    headers = attachment_headers(filename, fallback="project")
    metadata = snapshot.get("metadata")
    omissions = metadata.get("portable_export_omitted_models") if isinstance(metadata, dict) else None
    if isinstance(omissions, list) and omissions:
        headers["X-Spectra-Project-Model-Omissions"] = str(len(omissions))
    return headers


def _iter_project_snapshots(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    """Return a pre-order list of project snapshots in an exported project tree."""
    snapshots = [snapshot]
    for child in snapshot.get("children", []):
        if isinstance(child, dict):
            snapshots.extend(_iter_project_snapshots(child))
    return snapshots


def _iter_snapshot_models(snapshot: dict[str, Any]) -> list[tuple[dict[str, Any], dict[str, Any]]]:
    """Return ``(owning_project_snapshot, model_snapshot)`` pairs for a project tree."""
    models: list[tuple[dict[str, Any], dict[str, Any]]] = []
    for project_snapshot in _iter_project_snapshots(snapshot):
        for model_data in project_snapshot.get("models", []):
            if isinstance(model_data, dict):
                models.append((project_snapshot, model_data))
    return models


def _snapshot_experiment_index(snapshot: dict[str, Any]) -> dict[int, tuple[int, dict[str, Any]]]:
    """Return the exact archived experiment ownership census."""

    observed: dict[int, tuple[int, dict[str, Any]]] = {}
    for project_snapshot in _iter_project_snapshots(snapshot):
        project_id = _as_int(project_snapshot.get("id"))
        experiments = project_snapshot.get("experiments")
        if not isinstance(experiments, list) or (experiments and project_id is None):
            raise HTTPException(status_code=400, detail="Project experiment custody is invalid")
        for experiment in experiments:
            experiment_id = _as_int(experiment.get("id")) if isinstance(experiment, dict) else None
            if experiment_id is None or experiment_id in observed:
                raise HTTPException(status_code=400, detail="Project experiment identity is invalid")
            observed[experiment_id] = (project_id, experiment)
    return observed


def _bind_archived_model_training_source(
    manifest: dict[str, Any],
    model_record: dict[str, Any],
    *,
    owner_project_id: int | None,
    experiments: dict[int, tuple[int, dict[str, Any]]],
) -> None:
    """Admit or derive one exact model-to-experiment storage link."""

    from spectra_sherpa.core.model_artifact import (
        ModelArtifactIntegrityError,
        experiment_training_dataset_id,
    )

    try:
        linked_dataset_id = experiment_training_dataset_id(manifest)
    except ModelArtifactIntegrityError as exc:
        raise HTTPException(status_code=400, detail="Project model training source link is invalid") from exc
    declared_dataset_id = _as_int(model_record.get("training_dataset_id"))
    if linked_dataset_id is None:
        if declared_dataset_id is not None:
            raise HTTPException(status_code=400, detail="Project model training source provenance is missing")
        return
    archived = experiments.get(linked_dataset_id)
    if archived is None or owner_project_id is None or archived[0] != owner_project_id:
        raise HTTPException(status_code=400, detail="Project model training source is outside project custody")
    source = manifest["preprocessing_chain"][0]
    if source["op_id"] == "data.file_load":
        parameters = source["parameters"]
        file_id = parameters.get("file_id")
        files = archived[1].get("files", [])
        if (
            type(file_id) is not int
            or file_id < 1
            or not any(
                row.get("id") == file_id and row.get("stage") == parameters.get("stage", "raw")
                for row in files
                if isinstance(row, dict)
            )
        ):
            raise HTTPException(400, "Project model training file is outside experiment custody")
        if declared_dataset_id is not None and declared_dataset_id != linked_dataset_id:
            raise HTTPException(400, "Project model training source identities disagree")
        model_record["training_dataset_id"] = linked_dataset_id
        return
    if declared_dataset_id is not None:
        if declared_dataset_id != linked_dataset_id:
            raise HTTPException(status_code=400, detail="Project model training source identities disagree")
        return

    # A current archive may derive a historically omitted quick-link only
    # from the complete experiment-read scientific authority. An arbitrary
    # manifest integer is never enough.
    experiment = archived[1]
    source = manifest["preprocessing_chain"][0]
    parameters = source.get("parameters")
    definition = experiment.get("collection_definition")
    rows = definition.get("rows") if isinstance(definition, dict) else None
    asset_id = parameters.get("asset_id") if isinstance(parameters, dict) else None
    if (
        not isinstance(parameters, dict)
        or not isinstance(asset_id, str)
        or not asset_id
        or not isinstance(rows, list)
        or not rows
        or any(not isinstance(row, dict) or row.get("asset_id") != asset_id for row in rows)
        or parameters.get("file_count") != experiment.get("file_count")
        or parameters.get("collection_definition_sha256") != experiment.get("collection_definition_sha256")
        or parameters.get("source_manifest_sha256") != experiment.get("collection_source_manifest_sha256")
        or parameters.get("scientific_collection_sha256") != experiment.get("scientific_collection_sha256")
    ):
        raise HTTPException(status_code=400, detail="Project model training source cannot be derived exactly")
    model_record["training_dataset_id"] = linked_dataset_id


async def _project_experiment_ids(project_id: int, user_id: int, session: AsyncSession) -> set[int]:
    """Return experiment ids in a project tree owned by one user.

    The root has already passed ``require_project`` at the call site, but the
    recursive traversal still carries the owner predicate.  That protects
    export from malformed historical rows whose parent/project foreign key
    happens to point at another user's tree.
    """
    project_ids = {project_id}
    pending = [project_id]
    while pending:
        result = await session.execute(
            select(Project.id).where(
                Project.parent_id.in_(pending),
                or_(Project.user_id == user_id, uses_managed_project_access()),
            )
        )
        child_ids = [child_id for child_id in result.scalars().all() if child_id not in project_ids]
        project_ids.update(child_ids)
        pending = child_ids
    result = await session.execute(
        select(Experiment.id).where(
            Experiment.project_id.in_(project_ids),
            or_(Experiment.user_id == user_id, uses_managed_project_access()),
        )
    )
    return set(result.scalars().all())


async def _verify_saved_scientific_collections(
    snapshot: dict[str, Any],
    *,
    allowed_experiment_ids: set[int],
    user_id: int,
    session: AsyncSession,
) -> None:
    """Re-admit every saved definition and compare its complete decoded projection."""

    for project_snapshot in _iter_project_snapshots(snapshot):
        for experiment in project_snapshot.get("experiments", []):
            if not isinstance(experiment, dict):
                raise ProjectSnapshotStateError("Saved project experiment record is invalid")
            experiment_id = _as_int(experiment.get("id"))
            if experiment_id is None:
                raise ProjectSnapshotStateError("Saved project experiment identity is invalid")
            if experiment_id not in allowed_experiment_ids:
                raise ProjectSnapshotStateError("Saved project snapshot contains an experiment outside project custody")
            definition_payload = experiment.get("collection_definition")
            if definition_payload is None:
                if any(
                    experiment.get(field) is not None
                    for field in (
                        "collection_definition_sha256",
                        "collection_source_manifest_sha256",
                        "scientific_dataset_projection",
                        "scientific_dataset_projection_sha256",
                        "scientific_collection_schema_version",
                        "scientific_collection_sha256",
                    )
                ):
                    raise ProjectSnapshotStateError("Saved collection-absence identity is inconsistent")
                continue
            try:
                definition = validate_collection_definition(definition_payload)
                loaded = await load_project_dataset(
                    session,
                    user_id=user_id,
                    experiment_id=experiment_id,
                    stage="raw",
                    definition_override=definition,
                    strict_prepared_data=True,
                )
                observed_projection = scientific_dataset_projection(loaded.dataset)
                observed_projection_sha = scientific_dataset_projection_sha256(observed_projection)
            except ValueError as exc:
                raise ProjectSnapshotStateError("Saved scientific collection cannot be re-admitted") from exc
            if loaded.collection_definition_sha256 != definition.sha256:
                raise ProjectSnapshotStateError("Saved collection-definition identity is inconsistent")
            if loaded.source_manifest_sha256 != experiment.get("collection_source_manifest_sha256"):
                raise ProjectSnapshotStateError("Saved collection source identity is inconsistent")
            if experiment.get("scientific_dataset_projection") != observed_projection:
                raise ProjectSnapshotStateError("Saved decoded scientific projection changed")
            if experiment.get("scientific_dataset_projection_sha256") != observed_projection_sha:
                raise ProjectSnapshotStateError("Saved decoded scientific projection digest is inconsistent")
            if experiment.get("scientific_collection_schema_version") != loaded.dataset.meta["source_collection"].get(
                "scientific_collection_schema_version"
            ):
                raise ProjectSnapshotStateError("Saved scientific collection schema is inconsistent")
            if loaded.scientific_collection_sha256 != experiment.get("scientific_collection_sha256"):
                raise ProjectSnapshotStateError("Saved scientific collection identity changed")


def _preflight_project_data_members(
    snapshot: dict[str, Any],
    *,
    allowed_experiment_ids: set[int],
) -> tuple[int, int]:
    """Admit the complete retained export footprint before reading any member."""

    file_count = 0
    retained_bytes = 0
    seen_members: set[str] = set()
    for project_snapshot in _iter_project_snapshots(snapshot):
        experiments = project_snapshot.get("experiments")
        if not isinstance(experiments, list):
            raise ProjectSnapshotStateError("Saved project experiment inventory is invalid")
        for experiment in experiments:
            if not isinstance(experiment, dict):
                raise ProjectSnapshotStateError("Saved project experiment record is invalid")
            experiment_id = _as_int(experiment.get("id"))
            if experiment_id is None:
                raise ProjectSnapshotStateError("Saved project experiment identity is invalid")
            if experiment_id not in allowed_experiment_ids:
                raise ProjectSnapshotStateError("Saved project snapshot contains an experiment outside project custody")
            if experiment.get("storage_snapshot_schema_version") != PROJECT_STORAGE_SNAPSHOT_SCHEMA_VERSION:
                raise ProjectSnapshotStateError(
                    "Saved project version does not contain a current portable storage snapshot"
                )
            files = experiment.get("files")
            if not isinstance(files, list):
                raise ProjectSnapshotStateError("Saved project file inventory is invalid")
            file_count += len(files)
            if file_count > MAX_COLLECTION_MEMBERS:
                raise ProjectSnapshotStateError("Project archive exceeds the portable file-count limit")
            for file_data in files:
                if not isinstance(file_data, dict):
                    raise ProjectSnapshotStateError("Saved project file record is invalid")
                try:
                    rel_path, source_path = _experiment_file_path(
                        experiment_id,
                        file_data.get("file_path"),
                        file_data.get("stage"),
                    )
                    observed = source_path.lstat()
                except (OSError, ValueError) as exc:
                    raise ProjectSnapshotStateError(
                        "Project source file changed after the saved version was created"
                    ) from exc
                if stat.S_ISLNK(observed.st_mode) or not stat.S_ISREG(observed.st_mode):
                    raise ProjectSnapshotStateError("Project source file changed after the saved version was created")
                if observed.st_size > settings.max_file_size_mb * 1024 * 1024:
                    raise ProjectSnapshotStateError("Experiment snapshot source exceeds the project file-size limit")
                saved_size = file_data.get("saved_size_bytes")
                if not isinstance(saved_size, int) or isinstance(saved_size, bool) or saved_size != observed.st_size:
                    raise ProjectSnapshotStateError("Project source bytes changed after the saved version was created")
                # Preserve aggregate fail-fast admission before any source
                # materialization. Externalization is a packaging decision,
                # not permission to bypass the conservative project bound.
                retained_bytes += observed.st_size
                if retained_bytes > PROJECT_ARCHIVE_RETAINED_BYTES_MAX:
                    raise ProjectSnapshotStateError("Project archive exceeds the retained-byte limit")
                data = _read_bounded_regular_source(source_path, expected_size=saved_size)
                source_sha = sha256_bytes(data)
                if source_sha != file_data.get("saved_sha256"):
                    raise ProjectSnapshotStateError("Project source bytes changed after the saved version was created")
                external_reference = _registered_reference_for_source(
                    source_path,
                    size_bytes=len(data),
                    sha256=source_sha,
                )
                if external_reference != file_data.get("external_reference"):
                    raise ProjectSnapshotStateError(
                        "Registered-reference authority changed after the saved version was created"
                    )
                source_member = _project_data_archive_member(experiment_id, rel_path)
                prepared_member = _project_prepared_data_archive_member(experiment_id, rel_path)
                if prepared_member in seen_members or (external_reference is None and source_member in seen_members):
                    raise ProjectSnapshotStateError("Project archive contains duplicate portable members")
                seen_members.add(prepared_member)
                if external_reference is None:
                    seen_members.add(source_member)
                try:
                    prepared_path = sidecar_path(file_path=str(source_path), source=None, name=None)
                    prepared_observed = prepared_path.lstat()
                except FileNotFoundError:
                    retained_bytes += len(_canonical_prepared_data_bytes(PreparedDataOverrides()))
                except (OSError, ValueError) as exc:
                    raise ProjectSnapshotStateError("Prepared-data sidecar is invalid or unavailable") from exc
                else:
                    if stat.S_ISLNK(prepared_observed.st_mode) or not stat.S_ISREG(prepared_observed.st_mode):
                        raise ProjectSnapshotStateError("Prepared-data sidecar is invalid or unavailable")
                    if prepared_observed.st_size > PREPARED_DATA_SIDECAR_MAX_BYTES:
                        raise ProjectSnapshotStateError("Prepared-data sidecar exceeds the portable size limit")
                    retained_bytes += prepared_observed.st_size
                if retained_bytes > PROJECT_ARCHIVE_RETAINED_BYTES_MAX:
                    raise ProjectSnapshotStateError("Project archive exceeds the retained-byte limit")
            definition = experiment.get("collection_definition")
            if definition is not None:
                try:
                    admitted_definition = validate_collection_definition(definition)
                except ValueError as exc:
                    raise ProjectSnapshotStateError("Saved collection definition is invalid") from exc
                member = _project_collection_definition_archive_member(experiment_id)
                if member in seen_members:
                    raise ProjectSnapshotStateError("Project archive contains duplicate portable members")
                seen_members.add(member)
                retained_bytes += len(admitted_definition.canonical_bytes)
                if retained_bytes > PROJECT_ARCHIVE_RETAINED_BYTES_MAX:
                    raise ProjectSnapshotStateError("Project archive exceeds the retained-byte limit")
    return file_count, retained_bytes


def _collect_project_data_members(
    snapshot: dict[str, Any],
    *,
    allowed_experiment_ids: set[int] | None = None,
    seen_members: set[str] | None = None,
) -> list[ArchiveMember]:
    """Attach readable experiment files to an export snapshot as archive members."""
    members: list[ArchiveMember] = []
    if seen_members is None:
        seen_members = set()
    experiments = snapshot.get("experiments")
    if not isinstance(experiments, list):
        raise ProjectSnapshotStateError("Saved project experiment inventory is invalid")
    for experiment in experiments:
        if not isinstance(experiment, dict):
            raise ProjectSnapshotStateError("Saved project experiment record is invalid")
        old_experiment_id = _as_int(experiment.get("id"))
        if old_experiment_id is None:
            raise ProjectSnapshotStateError("Saved project experiment identity is invalid")
        if allowed_experiment_ids is not None and old_experiment_id not in allowed_experiment_ids:
            raise ProjectSnapshotStateError("Saved project snapshot contains an experiment outside project custody")

        storage_schema = experiment.get("storage_snapshot_schema_version")
        if storage_schema != PROJECT_STORAGE_SNAPSHOT_SCHEMA_VERSION:
            raise ProjectSnapshotStateError(
                "Saved project version does not contain a current portable storage snapshot"
            )

        files = experiment.get("files")
        if not isinstance(files, list) or experiment.get("file_count") != len(files):
            raise ProjectSnapshotStateError("Saved project file inventory is inconsistent")
        for file_data in files:
            if not isinstance(file_data, dict):
                raise ProjectSnapshotStateError("Saved project file record is invalid")
            try:
                rel_path, source_path = _experiment_file_path(
                    old_experiment_id,
                    file_data.get("file_path"),
                    file_data.get("stage"),
                )
            except ValueError as exc:
                raise ProjectSnapshotStateError(
                    "Project source path changed after the saved version was created"
                ) from exc

            if not source_path.exists() or not source_path.is_file() or source_path.is_symlink():
                raise ProjectSnapshotStateError("Project source file changed after the saved version was created")

            saved_size = file_data.get("saved_size_bytes")
            data = _read_bounded_regular_source(
                source_path,
                expected_size=saved_size if isinstance(saved_size, int) and not isinstance(saved_size, bool) else None,
            )
            member_path = _project_data_archive_member(old_experiment_id, rel_path)
            try:
                prepared = load_prepared_data_overrides_strict(file_path=str(source_path))
            except ValueError as exc:
                raise ProjectSnapshotStateError("Prepared-data sidecar is invalid or unavailable") from exc
            prepared_data = _canonical_prepared_data_bytes(prepared)
            prepared_member_path = _project_prepared_data_archive_member(old_experiment_id, rel_path)
            saved_sha = file_data.get("saved_sha256")
            saved_prepared_sha = file_data.get("saved_prepared_data_sha256")
            if storage_schema == PROJECT_STORAGE_SNAPSHOT_SCHEMA_VERSION and (
                not isinstance(saved_size, int)
                or isinstance(saved_size, bool)
                or saved_size < 0
                or not isinstance(saved_sha, str)
                or not isinstance(saved_prepared_sha, str)
            ):
                raise ProjectSnapshotStateError("Saved project storage identity is incomplete")
            if saved_size is not None and saved_size != len(data):
                raise ProjectSnapshotStateError("Project source bytes changed after the saved version was created")
            if saved_sha is not None and saved_sha != sha256_bytes(data):
                raise ProjectSnapshotStateError("Project source bytes changed after the saved version was created")
            if saved_prepared_sha is not None and saved_prepared_sha != sha256_bytes(prepared_data):
                raise ProjectSnapshotStateError("Prepared-data semantics changed after the saved version was created")
            external_reference = _registered_reference_for_source(
                source_path,
                size_bytes=len(data),
                sha256=sha256_bytes(data),
            )
            if external_reference != file_data.get("external_reference"):
                raise ProjectSnapshotStateError(
                    "Registered-reference authority changed after the saved version was created"
                )
            if prepared_member_path in seen_members or (external_reference is None and member_path in seen_members):
                raise ProjectSnapshotStateError("Project archive contains duplicate portable members")
            seen_members.add(prepared_member_path)
            if external_reference is None:
                seen_members.add(member_path)
            file_data["file_path"] = rel_path
            file_data["file_size_bytes"] = len(data)
            file_data["sha256"] = sha256_bytes(data)
            file_data["prepared_data_archive_member"] = prepared_member_path
            file_data["prepared_data_sha256"] = sha256_bytes(prepared_data)
            file_data["external_reference"] = external_reference
            if external_reference is None:
                file_data["archive_member"] = member_path
                file_data["archive_status"] = "included"
                members.append(ArchiveMember(member_path, data))
            else:
                file_data["archive_member"] = None
                file_data["archive_status"] = "external_reference"
            members.append(ArchiveMember(prepared_member_path, prepared_data))

        if "collection_definition" in experiment:
            expected_payload = experiment.get("collection_definition")
            try:
                current_definition = read_collection_definition(old_experiment_id)
            except ValueError as exc:
                raise ProjectSnapshotStateError("Live collection definition is invalid") from exc
            if expected_payload is None:
                experiment["collection_definition_archive_member"] = None
                if current_definition is not None:
                    raise ProjectSnapshotStateError(
                        "The collection definition changed after the saved version was created"
                    )
                if any(
                    experiment.get(field) is not None
                    for field in (
                        "collection_source_manifest_sha256",
                        "scientific_dataset_projection",
                        "scientific_dataset_projection_sha256",
                        "scientific_collection_schema_version",
                        "scientific_collection_sha256",
                    )
                ):
                    raise ProjectSnapshotStateError("Saved collection-absence identity is inconsistent")
            else:
                if not isinstance(expected_payload, dict):
                    raise ProjectSnapshotStateError("Saved collection definition is invalid")
                try:
                    expected_definition = validate_collection_definition(expected_payload)
                except ValueError as exc:
                    raise ProjectSnapshotStateError("Saved collection definition is invalid") from exc
                if (
                    current_definition is None
                    or current_definition.canonical_bytes != expected_definition.canonical_bytes
                ):
                    raise ProjectSnapshotStateError(
                        "The collection definition changed after the saved version was created"
                    )
                if experiment.get("collection_definition_sha256") != expected_definition.sha256:
                    raise ProjectSnapshotStateError("Saved collection definition digest is inconsistent")
                if experiment.get("collection_definition_size_bytes") != len(expected_definition.canonical_bytes):
                    raise ProjectSnapshotStateError("Saved collection definition size is inconsistent")
                try:
                    _require_digest_field(
                        experiment,
                        "collection_source_manifest_sha256",
                        "collection source-manifest",
                    )
                    _require_digest_field(
                        experiment,
                        "scientific_dataset_projection_sha256",
                        "scientific dataset projection",
                    )
                    _require_digest_field(
                        experiment,
                        "scientific_collection_sha256",
                        "scientific collection",
                    )
                except HTTPException as exc:
                    raise ProjectSnapshotStateError("Saved scientific collection identity is incomplete") from exc
                projection = experiment.get("scientific_dataset_projection")
                if not isinstance(projection, dict):
                    raise ProjectSnapshotStateError("Saved scientific dataset projection is invalid")
                try:
                    projection_sha = scientific_dataset_projection_sha256(projection)
                except ValueError as exc:
                    raise ProjectSnapshotStateError("Saved scientific dataset projection is invalid") from exc
                if experiment.get("scientific_dataset_projection_sha256") != projection_sha:
                    raise ProjectSnapshotStateError("Saved scientific dataset projection digest is inconsistent")
                definition_member_path = _project_collection_definition_archive_member(old_experiment_id)
                if definition_member_path in seen_members:
                    raise ProjectSnapshotStateError("Project collection definition member is duplicated")
                seen_members.add(definition_member_path)
                experiment["collection_definition_archive_member"] = definition_member_path
                members.append(ArchiveMember(definition_member_path, expected_definition.canonical_bytes))
    children = snapshot.get("children")
    if not isinstance(children, list):
        raise ProjectSnapshotStateError("Saved project child inventory is invalid")
    for child in children:
        if not isinstance(child, dict):
            raise ProjectSnapshotStateError("Saved child project record is invalid")
        members.extend(
            _collect_project_data_members(
                child,
                allowed_experiment_ids=allowed_experiment_ids,
                seen_members=seen_members,
            )
        )
    return members


def _temporary_archive_path(suffix: str) -> Path:
    handle = tempfile.NamedTemporaryFile(prefix="spectra-project-", suffix=suffix, delete=False)
    handle.close()
    return Path(handle.name)


def _cleanup_temporary_archive(path: Path) -> None:
    path.unlink(missing_ok=True)


def _sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def _remap_source_ref(value: Any, experiment_remap: dict[int, int], file_remap: dict[int, int]) -> str | None:
    if not isinstance(value, str) or not value:
        return value if isinstance(value, str) else None
    parts = value.split(":")
    if len(parts) >= 2 and parts[0] in {"experiment", "dataset"}:
        old_experiment_id = _as_int(parts[1])
        if old_experiment_id in experiment_remap:
            parts[1] = str(experiment_remap[old_experiment_id])
    if "file" in parts:
        file_index = parts.index("file") + 1
        if file_index < len(parts):
            old_file_id = _as_int(parts[file_index])
            if old_file_id in file_remap:
                parts[file_index] = str(file_remap[old_file_id])
    return ":".join(parts)


def _remap_project_local_ids(value: Any, experiment_remap: dict[int, int], file_remap: dict[int, int]) -> Any:
    if isinstance(value, dict):
        rewritten = {key: _remap_project_local_ids(item, experiment_remap, file_remap) for key, item in value.items()}
        for key in ("dataset_id", "experiment_id"):
            old_id = _as_int(rewritten.get(key))
            if old_id in experiment_remap:
                rewritten[key] = experiment_remap[old_id]
        old_file_id = _as_int(rewritten.get("file_id"))
        if old_file_id in file_remap:
            rewritten["file_id"] = file_remap[old_file_id]
        return rewritten
    if isinstance(value, list):
        return [_remap_project_local_ids(item, experiment_remap, file_remap) for item in value]
    return value


def _require_project_data_hash(file_data: dict[str, Any]) -> str:
    expected_hash = file_data.get("sha256")
    if not isinstance(expected_hash, str):
        raise HTTPException(status_code=400, detail="Project data file is missing integrity hash")
    normalized = expected_hash.strip().lower()
    if len(normalized) != 64 or any(char not in "0123456789abcdef" for char in normalized):
        raise HTTPException(status_code=400, detail="Project data file integrity hash is invalid")
    return normalized


def _expected_project_data_member(file_data: dict[str, Any], old_experiment_id: int, rel_path: str) -> str:
    expected_member = _project_data_archive_member(old_experiment_id, rel_path)
    try:
        provided_member = _normalize_archive_member_path(file_data.get("archive_member"))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid project data archive member") from exc
    if provided_member != expected_member:
        raise HTTPException(status_code=400, detail="Project data archive member does not match manifest path")
    return expected_member


def _prepared_data_from_archive(
    zf: zipfile.ZipFile,
    file_data: dict[str, Any],
    old_experiment_id: int,
    rel_path: str,
) -> PreparedDataOverrides:
    expected_member = _project_prepared_data_archive_member(old_experiment_id, rel_path)
    try:
        provided_member = _normalize_archive_member_path(file_data.get("prepared_data_archive_member"))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid prepared-data archive member") from exc
    if provided_member != expected_member:
        raise HTTPException(status_code=400, detail="Prepared-data archive member does not match source path")
    expected_hash = _require_digest_field(file_data, "prepared_data_sha256", "prepared-data")
    try:
        info = zf.getinfo(expected_member)
    except KeyError as exc:
        raise HTTPException(status_code=400, detail="Prepared-data record is missing from archive") from exc
    if info.file_size > PROJECT_PREPARED_DATA_MAX_BYTES:
        raise HTTPException(status_code=413, detail="Prepared-data record exceeds size limit")
    payload = zf.read(info)
    if len(payload) > PROJECT_PREPARED_DATA_MAX_BYTES:
        raise HTTPException(status_code=413, detail="Prepared-data record exceeds size limit")
    if sha256_bytes(payload) != expected_hash:
        raise HTTPException(status_code=400, detail="Prepared-data record hash mismatch")
    try:
        decoded = json.loads(payload)
        if not isinstance(decoded, dict):
            raise ValueError("prepared data must be an object")
        prepared = PreparedDataOverrides.from_sidecar_mapping(decoded)
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=400, detail="Prepared-data record is invalid") from exc
    if _canonical_prepared_data_bytes(prepared) != payload:
        raise HTTPException(status_code=400, detail="Prepared-data record is not canonical")
    return prepared


def _collection_definition_from_archive(
    zf: zipfile.ZipFile,
    experiment_data: dict[str, Any],
    old_experiment_id: int,
) -> ValidatedCollectionDefinition | None:
    """Validate one exact canonical definition before restoring project state."""

    if "collection_definition" not in experiment_data:
        return None
    payload = experiment_data.get("collection_definition")
    if payload is None:
        if any(
            experiment_data.get(field) is not None
            for field in (
                "collection_definition_sha256",
                "collection_definition_archive_member",
                "collection_source_manifest_sha256",
                "scientific_dataset_projection",
                "scientific_dataset_projection_sha256",
                "scientific_collection_schema_version",
                "scientific_collection_sha256",
            )
        ) or experiment_data.get("collection_definition_size_bytes") not in {0, None}:
            raise HTTPException(status_code=400, detail="Collection-definition absence record is inconsistent")
        return None
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="Collection-definition record is invalid")
    try:
        definition = validate_collection_definition(payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Collection-definition record is invalid") from exc
    expected_member = _project_collection_definition_archive_member(old_experiment_id)
    try:
        provided_member = _normalize_archive_member_path(experiment_data.get("collection_definition_archive_member"))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid collection-definition archive member") from exc
    if provided_member != expected_member:
        raise HTTPException(status_code=400, detail="Collection-definition archive member does not match experiment")
    if experiment_data.get("collection_definition_sha256") != definition.sha256:
        raise HTTPException(status_code=400, detail="Collection-definition record hash is inconsistent")
    if experiment_data.get("collection_definition_size_bytes") != len(definition.canonical_bytes):
        raise HTTPException(status_code=400, detail="Collection-definition record size is inconsistent")
    _require_digest_field(
        experiment_data,
        "collection_source_manifest_sha256",
        "collection source-manifest",
    )
    _require_digest_field(
        experiment_data,
        "scientific_dataset_projection_sha256",
        "scientific dataset projection",
    )
    _require_digest_field(
        experiment_data,
        "scientific_collection_sha256",
        "scientific collection",
    )
    try:
        info = zf.getinfo(expected_member)
    except KeyError as exc:
        raise HTTPException(status_code=400, detail="Collection definition is missing from archive") from exc
    if info.file_size > MAX_COLLECTION_DEFINITION_BYTES:
        raise HTTPException(status_code=413, detail="Collection definition exceeds size limit")
    observed = zf.read(info)
    if len(observed) > MAX_COLLECTION_DEFINITION_BYTES:
        raise HTTPException(status_code=413, detail="Collection definition exceeds size limit")
    if observed != definition.canonical_bytes:
        raise HTTPException(status_code=400, detail="Collection-definition archive bytes do not match the record")
    return definition


def _require_digest_field(file_data: dict[str, Any], field: str, label: str) -> str:
    value = file_data.get(field)
    if not isinstance(value, str):
        raise HTTPException(status_code=400, detail=f"Project {label} record is missing integrity hash")
    normalized = value.strip().lower()
    if len(normalized) != 64 or any(char not in "0123456789abcdef" for char in normalized):
        raise HTTPException(status_code=400, detail=f"Project {label} record integrity hash is invalid")
    return normalized


def _require_external_reference_identity(
    value: Any,
    *,
    saved_size: int,
    saved_sha256: str,
) -> dict[str, Any]:
    """Re-admit one path-free identity against the active closed registry."""

    if not isinstance(value, dict):
        raise HTTPException(status_code=400, detail="Project external-reference identity is invalid")
    projection_id = value.get("projection_id")
    if not isinstance(projection_id, str) or not projection_id:
        raise HTTPException(status_code=400, detail="Project external-reference projection is invalid")
    try:
        expected = portable_reference_manifest(projection_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Project external-reference projection is unsupported") from exc
    if value != expected:
        raise HTTPException(status_code=400, detail="Project external-reference identity differs from the registry")
    if expected["member_size_bytes"] != saved_size or expected["member_sha256"] != saved_sha256:
        raise HTTPException(status_code=400, detail="Project external-reference member binding is inconsistent")
    return expected


def _project_external_reference_requirements(project_json: dict[str, Any]) -> list[dict[str, Any]]:
    """Return the unique exact upstream artifacts needed to import a project."""

    by_artifact: dict[str, dict[str, Any]] = {}
    for project_snapshot in _iter_project_snapshots(project_json):
        for experiment in project_snapshot.get("experiments") or []:
            if not isinstance(experiment, dict):
                continue
            for file_data in experiment.get("files") or []:
                if not isinstance(file_data, dict) or file_data.get("archive_status") != "external_reference":
                    continue
                reference = _require_external_reference_identity(
                    file_data.get("external_reference"),
                    saved_size=int(file_data["saved_size_bytes"]),
                    saved_sha256=str(file_data["saved_sha256"]),
                )
                artifact_id = str(reference["artifact_id"])
                existing = by_artifact.get(artifact_id)
                artifact = {
                    "artifact_id": artifact_id,
                    "artifact_size_bytes": int(reference["artifact_size_bytes"]),
                    "artifact_sha256": str(reference["artifact_sha256"]),
                    "provider": str(reference["provider"]),
                    "provider_page": str(reference["provider_page"]),
                    "download_url": str(reference["download_url"]),
                }
                if existing is not None and existing != artifact:
                    raise HTTPException(status_code=400, detail="Project external-reference artifact is inconsistent")
                by_artifact[artifact_id] = artifact
    return [by_artifact[key] for key in sorted(by_artifact)]


def _reference_rebind_required_detail(requirements: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "code": "project_reference_rebind_required",
        "message": (
            "This project refers to provider-hosted reference data that is not redistributed in the archive. "
            "Download each required file from its provider, then select the downloaded file and import again. "
            "Filenames and directories do not matter; exact size and SHA-256 are verified."
        ),
        "required_artifacts": requirements,
    }


async def _stage_project_reference_artifacts(
    uploads: list[UploadFile],
    *,
    requirements: list[dict[str, Any]],
    destination: Path,
) -> dict[str, Path]:
    """Admit only exact required artifacts into one private import staging dir."""

    if not requirements:
        if uploads:
            raise HTTPException(status_code=400, detail="Project does not declare any external reference files")
        return {}
    if not uploads:
        raise HTTPException(status_code=409, detail=_reference_rebind_required_detail(requirements))
    if len(uploads) > len(requirements):
        raise HTTPException(status_code=400, detail="Too many project reference files were selected")

    max_bytes = settings.max_file_size_mb * 1024 * 1024
    by_identity = {
        (int(requirement["artifact_size_bytes"]), str(requirement["artifact_sha256"])): requirement
        for requirement in requirements
    }
    admitted: dict[str, Path] = {}
    destination.mkdir(parents=True, exist_ok=False)
    for index, upload in enumerate(uploads):
        raw = await _read_upload_with_limit(upload, max_bytes=max_bytes)
        identity = (len(raw), sha256_bytes(raw))
        requirement = by_identity.get(identity)
        if requirement is None:
            raise HTTPException(
                status_code=422,
                detail={
                    "code": "project_reference_mismatch",
                    "message": (
                        "A selected file does not match any reference artifact required by this project. "
                        "No selected reference data was retained."
                    ),
                },
            )
        artifact_id = str(requirement["artifact_id"])
        if artifact_id in admitted:
            raise HTTPException(status_code=400, detail="A project reference artifact was selected more than once")
        target = destination / f"artifact-{index}.zip"
        with target.open("xb") as writer:
            writer.write(raw)
        admitted[artifact_id] = target

    missing = [value for value in requirements if str(value["artifact_id"]) not in admitted]
    if missing:
        raise HTTPException(status_code=409, detail=_reference_rebind_required_detail(missing))
    return admitted


def _validate_experiment_storage_snapshot(experiment_data: dict[str, Any]) -> None:
    """Require one complete current portable experiment record."""

    if experiment_data.get("storage_snapshot_schema_version") != PROJECT_STORAGE_SNAPSHOT_SCHEMA_VERSION:
        raise HTTPException(status_code=400, detail="Project storage snapshot schema is unsupported")
    experiment_id = _as_int(experiment_data.get("id"))
    if experiment_id is None or experiment_id < 1:
        raise HTTPException(status_code=400, detail="Project storage snapshot experiment identity is invalid")
    if "collection_definition" not in experiment_data or "collection_definition_archive_member" not in experiment_data:
        raise HTTPException(status_code=400, detail="Project storage snapshot is incomplete")
    files = experiment_data.get("files")
    if (
        not isinstance(files, list)
        or experiment_data.get("file_count") != len(files)
        or len(files) > MAX_COLLECTION_MEMBERS
    ):
        raise HTTPException(status_code=400, detail="Project storage snapshot file inventory is invalid")
    seen_file_ids: set[int] = set()
    seen_members: set[str] = set()
    for file_data in files:
        if not isinstance(file_data, dict):
            raise HTTPException(status_code=400, detail="Project storage snapshot file record is invalid")
        file_id = _as_int(file_data.get("id"))
        if file_id is None or file_id < 1 or file_id in seen_file_ids:
            raise HTTPException(status_code=400, detail="Project storage snapshot file identity is invalid")
        seen_file_ids.add(file_id)
        size = file_data.get("saved_size_bytes")
        if not isinstance(size, int) or isinstance(size, bool) or size < 0:
            raise HTTPException(status_code=400, detail="Saved project data size is invalid")
        saved_sha = _require_digest_field(file_data, "saved_sha256", "saved source")
        saved_prepared_sha = _require_digest_field(file_data, "saved_prepared_data_sha256", "saved prepared-data")
        try:
            rel_path = _normalize_experiment_file_path(file_data.get("file_path"), file_data.get("stage"))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="Project data file path is invalid") from exc
        source_member = _project_data_archive_member(experiment_id, rel_path)
        prepared_member = _project_prepared_data_archive_member(experiment_id, rel_path)
        status = file_data.get("archive_status")
        external_reference = file_data.get("external_reference")
        if status == "included":
            source_binding_valid = (
                external_reference is None
                and file_data.get("archive_member") == source_member
                and source_member not in seen_members
            )
        elif status == "external_reference":
            _require_external_reference_identity(
                external_reference,
                saved_size=size,
                saved_sha256=saved_sha,
            )
            source_binding_valid = file_data.get("archive_member") is None
        else:
            source_binding_valid = False
        if (
            not source_binding_valid
            or file_data.get("prepared_data_archive_member") != prepared_member
            or file_data.get("file_size_bytes") != size
            or file_data.get("sha256") != saved_sha
            or file_data.get("prepared_data_sha256") != saved_prepared_sha
            or prepared_member in seen_members
        ):
            raise HTTPException(status_code=400, detail="Project storage snapshot member binding is incomplete")
        if status == "included":
            seen_members.add(source_member)
        seen_members.add(prepared_member)

    definition_payload = experiment_data.get("collection_definition")
    definition_member = experiment_data.get("collection_definition_archive_member")
    if definition_payload is None:
        if definition_member is not None or experiment_data.get("collection_definition_sha256") is not None:
            raise HTTPException(status_code=400, detail="Project collection-absence identity is inconsistent")
        if experiment_data.get("collection_definition_size_bytes") != 0 or any(
            experiment_data.get(field) is not None
            for field in (
                "collection_source_manifest_sha256",
                "scientific_dataset_projection",
                "scientific_dataset_projection_sha256",
                "scientific_collection_schema_version",
                "scientific_collection_sha256",
            )
        ):
            raise HTTPException(status_code=400, detail="Project collection-absence identity is inconsistent")
        return
    if not isinstance(definition_payload, dict):
        raise HTTPException(status_code=400, detail="Project collection definition is invalid")
    try:
        definition = validate_collection_definition(definition_payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Project collection definition is invalid") from exc
    expected_definition_member = _project_collection_definition_archive_member(experiment_id)
    if (
        definition_member != expected_definition_member
        or definition_member in seen_members
        or experiment_data.get("collection_definition_sha256") != definition.sha256
        or experiment_data.get("collection_definition_size_bytes") != len(definition.canonical_bytes)
    ):
        raise HTTPException(status_code=400, detail="Project collection-definition member binding is inconsistent")
    _require_digest_field(experiment_data, "collection_source_manifest_sha256", "collection source-manifest")
    projection_sha = _require_digest_field(
        experiment_data,
        "scientific_dataset_projection_sha256",
        "scientific dataset projection",
    )
    _require_digest_field(experiment_data, "scientific_collection_sha256", "scientific collection")
    projection = experiment_data.get("scientific_dataset_projection")
    if not isinstance(projection, dict):
        raise HTTPException(status_code=400, detail="Project scientific dataset projection is invalid")
    try:
        observed_projection_sha = scientific_dataset_projection_sha256(projection)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Project scientific dataset projection is invalid") from exc
    if projection_sha != observed_projection_sha:
        raise HTTPException(status_code=400, detail="Project scientific dataset projection digest is inconsistent")
    expected_identity = scientific_collection_identity_from_digest(
        {"manifest_digest": experiment_data["collection_source_manifest_sha256"]},
        definition.sha256,
        projection_sha,
    )
    if (
        experiment_data.get("scientific_collection_schema_version")
        != expected_identity["scientific_collection_schema_version"]
        or experiment_data.get("scientific_collection_sha256") != expected_identity["scientific_collection_sha256"]
    ):
        raise HTTPException(status_code=400, detail="Project scientific collection identity is inconsistent")


def _preflight_model_npz(
    payload: bytes,
    *,
    max_decoded_bytes: int,
) -> tuple[int, dict[str, tuple[tuple[int, ...], str]]]:
    """Admit one model NPZ from headers before NumPy materializes arrays."""

    import numpy as np
    from numpy.lib import format as npformat

    if max_decoded_bytes < 0:
        raise HTTPException(status_code=413, detail="Project model arrays exceed the decoded-byte limit")
    try:
        with zipfile.ZipFile(io.BytesIO(payload), "r") as archive:
            infos = archive.infolist()
            if not infos or len(infos) > 1024 or len(infos) != len({info.filename for info in infos}):
                raise ValueError("invalid model array inventory")
            declared_bytes = 0
            inventory: dict[str, tuple[tuple[int, ...], str]] = {}
            for info in infos:
                member_path = PurePosixPath(info.filename)
                if (
                    info.is_dir()
                    or member_path.name != info.filename
                    or member_path.suffix != ".npy"
                    or not member_path.stem
                    or info.flag_bits & 0x1
                    or info.compress_size <= 0
                    or info.file_size / info.compress_size > 1000
                ):
                    raise ValueError("invalid model array member")
                with archive.open(info, "r") as member:
                    header_stream = io.BytesIO(member.read(min(info.file_size, 64 * 1024)))
                version = npformat.read_magic(header_stream)
                if version == (1, 0):
                    shape, _fortran, dtype = npformat.read_array_header_1_0(header_stream)
                elif version in {(2, 0), (3, 0)}:
                    shape, _fortran, dtype = npformat.read_array_header_2_0(header_stream)
                else:
                    raise ValueError("unsupported model NPY version")
                dtype = np.dtype(dtype)
                if (
                    dtype.hasobject
                    or dtype.fields is not None
                    or dtype.subdtype is not None
                    or dtype.kind not in {"b", "i", "u", "f", "c"}
                    or dtype.itemsize <= 0
                ):
                    raise ValueError("unsupported model array dtype")
                count = 1
                remaining_elements = (max_decoded_bytes - declared_bytes) // int(dtype.itemsize)
                for raw_dimension in shape:
                    dimension = int(raw_dimension)
                    if dimension < 0 or (dimension and count > remaining_elements // dimension):
                        raise HTTPException(
                            status_code=413, detail="Project model arrays exceed the decoded-byte limit"
                        )
                    count *= dimension
                array_bytes = count * int(dtype.itemsize)
                if info.file_size != header_stream.tell() + array_bytes:
                    raise ValueError("model array member size contradicts its NPY header")
                declared_bytes += array_bytes
                if declared_bytes > max_decoded_bytes:
                    raise HTTPException(status_code=413, detail="Project model arrays exceed the decoded-byte limit")
                inventory[member_path.stem] = (tuple(int(value) for value in shape), dtype.str)
            if len(inventory) != len(infos):
                raise ValueError("duplicate model array identity")
            return declared_bytes, inventory
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=400, detail="Project model array archive is invalid") from exc


def _validate_received_model_manifest(
    manifest: dict[str, Any],
    *,
    artifact_uid: str,
    model_record: dict[str, Any],
    arrays_payload: bytes,
    array_inventory: dict[str, tuple[tuple[int, ...], str]],
) -> None:
    """Cross-bind one received model manifest before restoration or loading."""

    import numpy as np

    from spectra_sherpa.core.model_artifact import (
        ModelArtifactIntegrityError,
        experiment_training_dataset_id,
    )

    arrays_sha256 = sha256_bytes(arrays_payload)
    model_type = model_record.get("model_type")
    expected_arrays = {
        name: {
            "shape": list(shape),
            "dtype": str(np.dtype(dtype_string)),
        }
        for name, (shape, dtype_string) in array_inventory.items()
    }
    if (
        manifest.get("artifact_uid") != artifact_uid
        or not isinstance(model_type, str)
        or not model_type
        or manifest.get("model_type") != model_type
        or model_record.get("integrity_hash") != arrays_sha256
        or manifest.get("integrity_hash") != arrays_sha256
        or manifest.get("arrays") != expected_arrays
        or model_record.get("training_scientific_digest") != manifest.get("training_scientific_digest")
    ):
        raise HTTPException(status_code=400, detail="Project model manifest contradicts its artifact authority")
    try:
        linked_dataset_id = experiment_training_dataset_id(manifest)
    except ModelArtifactIntegrityError as exc:
        raise HTTPException(status_code=400, detail="Project model training source link is invalid") from exc
    if linked_dataset_id is not None and linked_dataset_id != model_record.get("training_dataset_id"):
        raise HTTPException(status_code=400, detail="Project model training source contradicts its artifact record")


def _validate_canonical_model_projection(
    manifest: dict[str, Any],
    arrays: dict[str, Any],
    model_record: dict[str, Any],
) -> None:
    """Cross-bind canonical scientific lineage and quick-inspection projections."""

    from spectra_sherpa.app.services.canonical_model_bridge import (
        CANONICAL_MODEL_ORIGIN,
        CanonicalModelBridgeError,
        validate_canonical_plsda_model_artifact,
    )

    declared_origin = model_record.get("artifact_origin")
    manifest_origin = manifest.get("artifact_origin")
    if declared_origin is None and manifest_origin is None:
        if (
            model_record.get("canonical_lineage_digest") is not None
            or model_record.get("validation_evidence_digest") is not None
        ):
            raise HTTPException(status_code=400, detail="Project model canonical identity is inconsistent")
        return
    if declared_origin != CANONICAL_MODEL_ORIGIN or manifest_origin != CANONICAL_MODEL_ORIGIN:
        raise HTTPException(status_code=400, detail="Project model canonical origin is inconsistent")
    try:
        lineage = validate_canonical_plsda_model_artifact(
            manifest,
            arrays,
            expected_training_dataset_id=model_record.get("training_dataset_id"),
        )
    except CanonicalModelBridgeError as exc:
        raise HTTPException(status_code=400, detail="Project canonical model lineage is invalid") from exc
    if (
        model_record.get("model_type") != "plsda"
        or model_record.get("node_id") != manifest.get("node_id")
        or isinstance(model_record.get("training_dataset_id"), bool)
        or not isinstance(model_record.get("training_dataset_id"), int)
        or model_record.get("training_dataset_id") < 1
        or model_record.get("n_features") != manifest.get("n_features")
        or model_record.get("n_components") != manifest.get("n_components")
        or model_record.get("classes") != manifest.get("classes")
        or model_record.get("feature_axis") != manifest.get("feature_axis")
        or model_record.get("training_data_hash") != manifest.get("training_data_hash")
        or model_record.get("preprocessing_summary") != manifest.get("preprocessing_chain")
        or model_record.get("canonical_lineage_digest") != lineage["lineage_digest"]
        or model_record.get("validation_evidence_digest") != lineage["validation_execution_digest"]
    ):
        raise HTTPException(status_code=400, detail="Project canonical model projection is inconsistent")


def _validate_current_project_archive(
    zf: zipfile.ZipFile,
    project_json: dict[str, Any],
    *,
    is_sherpa_object: bool,
) -> None:
    """Refuse any current object that omits part of the portable 0.5 schema."""

    archive_format = project_json.get("archive_format")
    if not is_sherpa_object and archive_format is None:
        # Legacy ``.spectrapy`` without embedded experiment data remains a
        # metadata-only import.  Every current ``.sherpa`` object is closed.
        if any(snapshot.get("experiments") for snapshot in _iter_project_snapshots(project_json)):
            raise HTTPException(status_code=400, detail="Legacy project archives cannot import experiment files")
        return
    if not isinstance(archive_format, dict) or archive_format != {
        "schema": "spectra_sherpa_project_archive",
        "version": PROJECT_ARCHIVE_FORMAT_VERSION,
        "data_members": PROJECT_DATA_PREFIX,
    }:
        raise HTTPException(status_code=400, detail="Project archive format is unsupported or incomplete")
    if len(zf.namelist()) != len(set(zf.namelist())):
        raise HTTPException(status_code=400, detail="Project archive contains duplicate members")
    if is_sherpa_object:
        try:
            object_manifest = json.loads(zf.read(SHERPA_OBJECT_MANIFEST))
        except (KeyError, json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise HTTPException(status_code=400, detail="Sherpa object manifest is invalid") from exc
        if object_manifest.get("project_payload_version") != PROJECT_ARCHIVE_FORMAT_VERSION:
            raise HTTPException(status_code=400, detail="Sherpa object project-payload version is inconsistent")

    total_source_files = 0
    retained_data_bytes = 0
    seen_experiment_ids: set[int] = set()
    seen_file_ids: set[int] = set()
    seen_referenced_members: set[str] = set()
    for project_snapshot in _iter_project_snapshots(project_json):
        experiments = project_snapshot.get("experiments")
        if not isinstance(experiments, list):
            raise HTTPException(status_code=400, detail="Project experiment inventory is invalid")
        for experiment in experiments:
            if not isinstance(experiment, dict):
                raise HTTPException(status_code=400, detail="Project experiment record is invalid")
            _validate_experiment_storage_snapshot(experiment)
            experiment_id = int(experiment["id"])
            if experiment_id in seen_experiment_ids:
                raise HTTPException(status_code=400, detail="Project experiment identity is duplicated")
            seen_experiment_ids.add(experiment_id)
            total_source_files += len(experiment["files"])
            if total_source_files > MAX_COLLECTION_MEMBERS:
                raise HTTPException(status_code=413, detail="Project archive exceeds the portable file-count limit")

            member_records: list[tuple[str, int | None, int]] = []
            for file_data in experiment["files"]:
                file_id = int(file_data["id"])
                if file_id in seen_file_ids:
                    raise HTTPException(status_code=400, detail="Project file identity is duplicated")
                seen_file_ids.add(file_id)
                if file_data["archive_status"] == "included":
                    member_records.append(
                        (
                            file_data["archive_member"],
                            int(file_data["saved_size_bytes"]),
                            settings.max_file_size_mb * 1024 * 1024,
                        )
                    )
                member_records.append(
                    (
                        file_data["prepared_data_archive_member"],
                        None,
                        PREPARED_DATA_SIDECAR_MAX_BYTES,
                    )
                )
                rel_path = _normalize_experiment_file_path(file_data.get("file_path"), file_data.get("stage"))
                _prepared_data_from_archive(zf, file_data, experiment_id, rel_path)
            definition_member = experiment.get("collection_definition_archive_member")
            if definition_member is not None:
                member_records.append(
                    (
                        definition_member,
                        int(experiment["collection_definition_size_bytes"]),
                        MAX_COLLECTION_DEFINITION_BYTES,
                    )
                )
            for member, expected_size, member_limit in member_records:
                if member in seen_referenced_members:
                    raise HTTPException(status_code=400, detail="Project portable member is referenced more than once")
                seen_referenced_members.add(member)
                try:
                    info = zf.getinfo(member)
                except KeyError as exc:
                    raise HTTPException(status_code=400, detail="Project portable member is missing") from exc
                if info.file_size > member_limit or (expected_size is not None and info.file_size != expected_size):
                    raise HTTPException(status_code=400, detail="Project portable member size is inconsistent")
                retained_data_bytes += info.file_size
                if retained_data_bytes > PROJECT_ARCHIVE_RETAINED_BYTES_MAX:
                    raise HTTPException(status_code=413, detail="Project archive exceeds the retained-byte limit")

    seen_model_uids: set[str] = set()
    seen_model_members: set[str] = set()
    for project_snapshot in _iter_project_snapshots(project_json):
        models = project_snapshot.get("models", [])
        if not isinstance(models, list):
            raise HTTPException(status_code=400, detail="Project model inventory is invalid")
        for model_data in models:
            if not isinstance(model_data, dict):
                raise HTTPException(status_code=400, detail="Project model record is invalid")
            artifact_uid = model_data.get("artifact_uid")
            if not isinstance(artifact_uid, str):
                raise HTTPException(status_code=400, detail="Project model identity is invalid")
            try:
                canonical_uid = str(uuid.UUID(artifact_uid))
            except ValueError as exc:
                raise HTTPException(status_code=400, detail="Project model identity is invalid") from exc
            if artifact_uid != canonical_uid:
                raise HTTPException(status_code=400, detail="Project model identity is not canonical")
            if canonical_uid in seen_model_uids:
                raise HTTPException(status_code=400, detail="Project model identity is duplicated")
            seen_model_uids.add(canonical_uid)
            for name in ("manifest.json", "arrays.npz"):
                member = f"models/{artifact_uid}/{name}"
                seen_model_members.add(member)
                try:
                    info = zf.getinfo(member)
                except KeyError as exc:
                    raise HTTPException(status_code=400, detail="Project model member is missing") from exc
                if info.file_size > settings.max_file_size_mb * 1024 * 1024:
                    raise HTTPException(status_code=413, detail="Project model member exceeds the file-size limit")
                if info.compress_size > 0 and info.file_size / info.compress_size > 200:
                    raise HTTPException(status_code=400, detail="Project model member compression ratio is invalid")
                retained_data_bytes += info.file_size
                if retained_data_bytes > PROJECT_ARCHIVE_RETAINED_BYTES_MAX:
                    raise HTTPException(status_code=413, detail="Project archive exceeds the retained-byte limit")

    actual_data_members: list[str] = []
    for raw_member in zf.namelist():
        try:
            normalized_member = _normalize_archive_member_path(raw_member)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="Project archive member path is invalid") from exc
        if normalized_member.startswith(f"{PROJECT_DATA_PREFIX}/"):
            if raw_member != normalized_member:
                raise HTTPException(status_code=400, detail="Project data archive member path is not canonical")
            actual_data_members.append(normalized_member)
    if len(actual_data_members) != len(set(actual_data_members)):
        raise HTTPException(status_code=400, detail="Project data archive member identity is duplicated")
    if set(actual_data_members) != seen_referenced_members:
        raise HTTPException(status_code=400, detail="Project archive contains unbound portable data members")
    actual_model_members: set[str] = set()
    for raw_member in zf.namelist():
        normalized_member = _normalize_archive_member_path(raw_member)
        if normalized_member.startswith("models/"):
            if raw_member != normalized_member:
                raise HTTPException(status_code=400, detail="Project model archive member path is not canonical")
            actual_model_members.add(normalized_member)
    if actual_model_members != seen_model_members:
        raise HTTPException(status_code=400, detail="Project archive contains unbound model members")


def _read_archive_member_to_path(
    zf: zipfile.ZipFile,
    member_name: str,
    target_path: Path,
    *,
    max_member_bytes: int,
) -> int:
    member_name = _normalize_archive_member_path(member_name)
    if not member_name.startswith(f"{PROJECT_DATA_PREFIX}/"):
        raise HTTPException(status_code=400, detail="Invalid project data archive member")

    try:
        info = zf.getinfo(member_name)
    except KeyError as exc:
        raise HTTPException(status_code=400, detail="Project data file is missing from archive") from exc
    if info.file_size > max_member_bytes:
        raise HTTPException(status_code=413, detail="Project data file exceeds size limit")

    target_path.parent.mkdir(parents=True, exist_ok=True)
    bytes_written = 0
    try:
        with zf.open(info, "r") as source, target_path.open("wb") as destination:
            while True:
                chunk = source.read(1024 * 1024)
                if not chunk:
                    break
                bytes_written += len(chunk)
                if bytes_written > max_member_bytes:
                    raise HTTPException(status_code=413, detail="Project data file exceeds size limit")
                destination.write(chunk)
    except BaseException:
        if target_path.exists():
            target_path.unlink()
        raise
    return bytes_written


async def _project_to_summary(project: Project, session: AsyncSession) -> ProjectSummary:
    """Build a ProjectSummary with aggregated counts."""
    exp_count = await session.scalar(
        select(func.count(Experiment.id)).where(
            Experiment.project_id == project.id,
            or_(Experiment.user_id == project.user_id, uses_managed_project_access()),
        )
    )
    wf_count = await session.scalar(
        select(func.count(Workflow.id)).where(
            Workflow.project_id == project.id,
            or_(Workflow.user_id == project.user_id, uses_managed_project_access()),
        )
    )
    child_count = await session.scalar(
        select(func.count(Project.id)).where(
            Project.parent_id == project.id,
            Project.user_id == project.user_id,
        )
    )
    script_count = await session.scalar(
        select(func.count(ProjectScript.id)).where(
            ProjectScript.project_id == project.id,
            or_(ProjectScript.user_id == project.user_id, uses_managed_project_access()),
        )
    )
    model_count = await session.scalar(
        select(func.count(ModelArtifact.id)).where(
            ModelArtifact.project_id == project.id,
            or_(ModelArtifact.user_id == project.user_id, uses_managed_project_access()),
            ModelArtifact.is_active == True,  # noqa: E712
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
        archived_at=project.archived_at,
    )


async def _project_to_detail(project: Project, session: AsyncSession) -> ProjectDetail:
    """Build a full ProjectDetail with related objects."""
    summary = await _project_to_summary(project, session)

    # Experiments
    exp_result = await session.execute(
        select(Experiment)
        .where(
            Experiment.project_id == project.id,
            or_(Experiment.user_id == project.user_id, uses_managed_project_access()),
        )
        .options(selectinload(Experiment.files))
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
        .where(
            Workflow.project_id == project.id,
            or_(Workflow.user_id == project.user_id, uses_managed_project_access()),
        )
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
            purpose=w.purpose,
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
        select(ProjectScript)
        .where(
            ProjectScript.project_id == project.id,
            or_(ProjectScript.user_id == project.user_id, uses_managed_project_access()),
        )
        .order_by(ProjectScript.priority)
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
            ModelArtifact.project_id == project.id,
            or_(ModelArtifact.user_id == project.user_id, uses_managed_project_access()),
            ModelArtifact.is_active == True,  # noqa: E712
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
    child_result = await session.execute(
        select(Project).where(
            Project.parent_id == project.id,
            Project.user_id == project.user_id,
        )
    )
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
    from spectra_sherpa.app.contracts.scientific_access import create_managed_project

    project = await create_managed_project(session, current_user.id, payload)
    if project is None:
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
    archived: bool = False,
    limit: Annotated[int | None, Query(ge=1, le=100)] = None,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[ProjectSummary]:
    """List active or archived top-level projects, excluding permanent tombstones."""
    query = (
        select(Project)
        .where(
            Project.id.in_(
                await accessible_project_ids(session, current_user.id, archived=archived, limit=limit, offset=offset)
            ),
            Project.parent_id.is_(None),
            Project.deleted_at.is_(None),
            Project.archived_at.is_not(None) if archived else Project.archived_at.is_(None),
        )
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
    project = await require_project(project_id, current_user.id, session, operation="read")
    return await _project_to_detail(project, session)


@router.post("/{project_id}/reproduce-campaign")
async def reproduce_imported_campaign(
    project_id: int,
    package: UploadFile = File(...),
    fixture: UploadFile = File(...),
    publisher_keys: UploadFile = File(...),
    projection_id: str = Form(...),
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> dict:
    """Independently reproduce an imported campaign with analyst-supplied reference bytes."""
    if app_config.mode != "local":
        raise HTTPException(status_code=403, detail="Independent reproduction runs in local OSS")
    await require_project(project_id, current_user.id, session, operation="read")
    from spectra_sherpa.app.models.canonical_project_artifact import CanonicalProjectArtifact
    from spectra_sherpa.app.services.campaign_reproduction import reproduce_reference_upload

    record = await session.scalar(
        select(CanonicalProjectArtifact).where(
            CanonicalProjectArtifact.project_id == project_id,
            CanonicalProjectArtifact.user_id == current_user.id,
        )
    )
    if record is None:
        raise HTTPException(status_code=404, detail="Imported campaign is unavailable")
    max_bytes = settings.max_file_size_mb * 1024 * 1024
    package_bytes = await _read_upload_with_limit(package, max_bytes=max_bytes)
    fixture_bytes = await _read_upload_with_limit(fixture, max_bytes=max_bytes)
    keys_bytes = await _read_upload_with_limit(publisher_keys, max_bytes=64 * 1024)
    try:
        return await asyncio.to_thread(
            reproduce_reference_upload,
            package_bytes=package_bytes,
            fixture_bytes=fixture_bytes,
            keys_bytes=keys_bytes,
            projection_id=projection_id,
            expected_package_sha256=record.package_sha256,
            max_bytes=max_bytes,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/{project_id}/details", response_model=ProjectDetail)
async def get_project_details(
    project_id: int,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> ProjectDetail:
    """Alias for full project detail used by project-context clients."""
    project = await require_project(project_id, current_user.id, session, operation="read")
    return await _project_to_detail(project, session)


@router.get("/{project_id}/data-sources", response_model=list[ProjectDataSourceOut])
async def list_project_data_sources(
    project_id: int,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> list[ProjectDataSourceOut]:
    """List data sources registered for a project."""
    await require_project(project_id, current_user.id, session, operation="read")
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


def _validate_data_source_metadata(metadata: dict | None) -> None:
    # Refuse before persistence without echoing NaN/Infinity in a validation
    # response: those values cannot be JSON-encoded by Starlette either.
    try:
        json.dumps(metadata, allow_nan=False)
    except (ValueError, TypeError) as exc:
        raise HTTPException(422, "Data-source metadata must contain only finite JSON values") from exc


@router.post(
    "/{project_id}/data-sources",
    response_model=ProjectDataSourceOut,
    status_code=201,
    dependencies=[Depends(demo_guard("external_data_source"))],
)
async def create_project_data_source(
    project_id: int,
    payload: ProjectDataSourceCreate,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> ProjectDataSourceOut:
    """Create a manually registered project data source."""
    _validate_data_source_metadata(payload.metadata)
    await require_project(project_id, current_user.id, session, operation="write")
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


@router.put(
    "/{project_id}/data-sources/{data_source_id}",
    response_model=ProjectDataSourceOut,
    dependencies=[Depends(demo_guard("external_data_source"))],
)
async def update_project_data_source(
    project_id: int,
    data_source_id: int,
    payload: ProjectDataSourceUpdate,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> ProjectDataSourceOut:
    """Update project data-source metadata such as display name or color."""
    _validate_data_source_metadata(payload.metadata)
    await require_project(project_id, current_user.id, session, operation="write")
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


@router.patch("/{project_id}", response_model=ProjectDetail)
@router.put("/{project_id}", response_model=ProjectDetail)
async def update_project(
    project_id: int,
    payload: ProjectUpdate,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> ProjectDetail:
    """Update project metadata."""
    if uses_managed_project_access():
        await require_scientific_access(session, current_user.id, project_id, "write")
        project = await session.get(Project, project_id)
        if "parent_id" in payload.model_fields_set and payload.parent_id != project.parent_id:
            raise HTTPException(409, "Project tree transfers require separate qualification")
    else:
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


@router.post("/{project_id}/archive", response_model=ProjectSummary)
async def archive_project(
    project_id: int,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> ProjectSummary:
    """Remove a top-level project from the active catalog without touching evidence."""
    project = await require_project(project_id, current_user.id, session)
    await session.refresh(project, with_for_update=True)
    if project.parent_id is not None:
        raise HTTPException(status_code=409, detail="Archive the top-level project instead")
    if project.archived_at is None:
        project.archived_at = datetime.now(timezone.utc)
        from spectra_sherpa.app.services.audit import audit_emitter

        audit_emitter.emit(
            session=session,
            action="project.archived",
            target_type="Project",
            target_id=project.id,
            before={"archived_at": None},
            after={"archived_at": project.archived_at.isoformat()},
        )
        await session.commit()
        await session.refresh(project)
    return await _project_to_summary(project, session)


@router.post("/{project_id}/restore", response_model=ProjectSummary)
async def restore_project(
    project_id: int,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> ProjectSummary:
    """Restore an archived project; permanently removed projects cannot return."""
    project = await require_project(project_id, current_user.id, session)
    await session.refresh(project, with_for_update=True)
    if project.parent_id is not None:
        raise HTTPException(status_code=409, detail="Restore the top-level project instead")
    if project.archived_at is not None:
        old_archived_at = project.archived_at
        project.archived_at = None
        from spectra_sherpa.app.services.audit import audit_emitter

        audit_emitter.emit(
            session=session,
            action="project.restored",
            target_type="Project",
            target_id=project.id,
            before={"archived_at": old_archived_at.isoformat()},
            after={"archived_at": None},
        )
        await session.commit()
        await session.refresh(project)
    return await _project_to_summary(project, session)


@router.delete("/{project_id}", status_code=204, response_class=Response)
async def delete_project(
    project_id: int,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
    confirm_name: str | None = None,
) -> Response:
    """Remove a project from the catalog; hosted qualification always retains evidence."""
    if uses_managed_project_access():
        await require_scientific_access(session, current_user.id, project_id, "write")
        project = await session.get(Project, project_id)
        if project.user_id != current_user.id:
            raise HTTPException(403, "Only the project owner may remove this project")
        if project.parent_id is not None:
            raise HTTPException(409, "Remove the top-level project instead")
        if confirm_name != project.name:
            raise HTTPException(400, "Type the exact project name to confirm removal")
        tree = select(Project.id).where(Project.id == project_id).cte("removed_projects", recursive=True)
        tree = tree.union(select(Project.id).where(Project.parent_id == tree.c.id))
        await session.execute(
            update(Project).where(Project.id.in_(select(tree.c.id))).values(deleted_at=datetime.now(timezone.utc))
        )
        from spectra_sherpa.app.services.audit import audit_emitter

        audit_emitter.emit(
            session=session,
            action="project.deleted",
            target_type="Project",
            target_id=project_id,
            before={"name": project.name},
            after={"retained_commercial_tombstone": True},
        )
        await session.commit()
        return Response(status_code=204)
    project = await require_project(project_id, current_user.id, session)
    await session.refresh(project, with_for_update=True)
    if project.archived_at is None:
        raise HTTPException(status_code=409, detail="Archive this project before permanent deletion")
    if confirm_name != project.name:
        raise HTTPException(status_code=400, detail="Type the exact archived project name to confirm deletion")

    from spectra_sherpa.app.services.run_provenance import (
        has_retained_source,
        provenance_cleanup,
        require_unretained_source,
    )

    if await has_retained_source(session, project_id=project_id):
        # A model can move projects, while its source run still points into
        # this tree. Preserve the complete scientific source as a hidden
        # internal provenance tombstone; it cannot be restored as a project.
        tree = select(Project.id).where(Project.id == project_id).cte("retained_projects", recursive=True)
        tree = tree.union_all(select(Project.id).where(Project.parent_id == tree.c.id))
        await session.execute(
            update(Project).where(Project.id.in_(select(tree.c.id))).values(deleted_at=datetime.now(timezone.utc))
        )
        from spectra_sherpa.app.services.audit import audit_emitter

        audit_emitter.emit(
            session=session,
            action="project.deleted",
            target_type="Project",
            target_id=project_id,
            before={"name": project.name, "archived_at": project.archived_at.isoformat()},
            after={"retained_provenance_tombstone": True},
        )
        await session.commit()
        return Response(status_code=204)

    await require_unretained_source(session, project_id=project_id)
    managed_workflows = []

    # SET NULL on linked experiments, workflows, and models before cascade delete
    for exp in (
        (
            await session.execute(
                select(Experiment).where(
                    Experiment.project_id == project_id,
                    Experiment.user_id == current_user.id,
                )
            )
        )
        .scalars()
        .all()
    ):
        exp.project_id = None

    for wf in (
        (
            await session.execute(
                select(Workflow).where(
                    Workflow.project_id == project_id,
                    Workflow.user_id == current_user.id,
                )
            )
        )
        .scalars()
        .all()
    ):
        if wf.purpose == MANAGED_CANDIDATE_AUTHORITY:
            # A managed candidate is frozen project custody, not an editable
            # user document. It must not survive as a source-dead orphan when
            # its containing project is deliberately deleted.
            managed_workflows.append(wf)
        else:
            wf.project_id = None

    for ma in (
        (
            await session.execute(
                select(ModelArtifact).where(
                    ModelArtifact.project_id == project_id,
                    ModelArtifact.user_id == current_user.id,
                )
            )
        )
        .scalars()
        .all()
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

    async with provenance_cleanup(session):
        for managed_workflow in managed_workflows:
            await session.delete(managed_workflow)
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
    destination_project_id: int | None = Query(None, gt=0),
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> ProjectDetail:
    """Unlink an experiment from this project."""
    project = await require_project(project_id, current_user.id, session)
    if destination_project_id is not None:
        await require_project(destination_project_id, current_user.id, session)
        if destination_project_id == project_id:
            raise HTTPException(422, "Choose a different destination project")
    elif uses_managed_project_access():
        raise HTTPException(422, "Choose a destination project")
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

    # Record the exact source and destination; hosted transfers never orphan
    # a resource, while standalone callers may still detach without a target.
    from spectra_sherpa.app.services.audit import audit_emitter

    audit_emitter.emit(
        session=session,
        action="experiment.project_unlinked",
        target_type="Experiment",
        target_id=experiment.id,
        before={"project_id": project_id},
        after={"project_id": destination_project_id},
    )

    experiment.project_id = destination_project_id
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
    if workflow.purpose == MANAGED_CANDIDATE_AUTHORITY:
        raise HTTPException(
            status_code=409,
            detail="Managed candidate authority cannot be moved between projects",
        )

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
    if uses_managed_project_access():
        channels = (
            await session.scalars(select(AdvisorChannel).where(AdvisorChannel.workflow_id == workflow.id))
        ).all()
        for channel in channels:
            channel.project_id = project_id
    await session.commit()
    logger.info("Linked workflow %s to project %s", workflow_id, project_id)
    return await _project_to_detail(project, session)


@router.delete("/{project_id}/workflows/{workflow_id}", response_model=ProjectDetail)
async def unlink_workflow(
    project_id: int,
    workflow_id: int,
    destination_project_id: int | None = Query(None, gt=0),
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> ProjectDetail:
    """Unlink a workflow from this project."""
    project = await require_project(project_id, current_user.id, session)
    if destination_project_id is not None:
        await require_project(destination_project_id, current_user.id, session)
        if destination_project_id == project_id:
            raise HTTPException(422, "Choose a different destination project")
    elif uses_managed_project_access():
        raise HTTPException(422, "Choose a destination project")
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
    if workflow.purpose == MANAGED_CANDIDATE_AUTHORITY:
        raise HTTPException(
            status_code=409,
            detail="Managed candidate authority cannot be unlinked from its project",
        )

    # ISO 17025 audit — workflow.project_unlinked.
    from spectra_sherpa.app.services.audit import audit_emitter

    audit_emitter.emit(
        session=session,
        action="workflow.project_unlinked",
        target_type="Workflow",
        target_id=workflow.id,
        before={"project_id": project_id},
        after={"project_id": destination_project_id},
    )

    workflow.project_id = destination_project_id
    if uses_managed_project_access():
        channels = (
            await session.scalars(select(AdvisorChannel).where(AdvisorChannel.workflow_id == workflow.id))
        ).all()
        for channel in channels:
            channel.project_id = destination_project_id
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


async def _preflight_live_project_storage(
    project: Project,
    session: AsyncSession,
    budget: _SnapshotBuildBudget,
) -> None:
    experiment_result = await session.execute(
        select(Experiment)
        .where(Experiment.project_id == project.id, Experiment.user_id == project.user_id)
        .options(selectinload(Experiment.files))
    )
    for experiment in experiment_result.scalars().all():
        retained = 0
        files = list(experiment.files)
        for file_row in files:
            try:
                _, source_path = _experiment_file_path(experiment.id, file_row.file_path, file_row.stage)
                observed = source_path.lstat()
            except (OSError, ValueError) as exc:
                raise ProjectSnapshotStateError("Experiment snapshot source file is unavailable") from exc
            if stat.S_ISLNK(observed.st_mode) or not stat.S_ISREG(observed.st_mode):
                raise ProjectSnapshotStateError("Experiment snapshot source is not a regular file")
            # Preflight the worst-case retained footprint before reading any
            # source bytes. Registered references may later be externalized,
            # but sidecar classification must not weaken this fail-fast bound.
            retained += observed.st_size
            try:
                prepared_path = sidecar_path(file_path=str(source_path), source=None, name=None)
                prepared_observed = prepared_path.lstat()
            except FileNotFoundError:
                retained += len(_canonical_prepared_data_bytes(PreparedDataOverrides()))
            except (OSError, ValueError) as exc:
                raise ProjectSnapshotStateError("Prepared-data sidecar is invalid or unavailable") from exc
            else:
                if stat.S_ISLNK(prepared_observed.st_mode) or not stat.S_ISREG(prepared_observed.st_mode):
                    raise ProjectSnapshotStateError("Prepared-data sidecar is invalid or unavailable")
                if prepared_observed.st_size > PREPARED_DATA_SIDECAR_MAX_BYTES:
                    raise ProjectSnapshotStateError("Prepared-data sidecar exceeds the portable size limit")
                retained += prepared_observed.st_size
        budget.admit(files=len(files), retained_bytes=retained)
    child_result = await session.execute(
        select(Project).where(Project.parent_id == project.id, Project.user_id == project.user_id)
    )
    for child in child_result.scalars().all():
        await _preflight_live_project_storage(child, session, budget)


async def _build_snapshot(
    project: Project,
    session: AsyncSession,
    *,
    actor_id: int | None = None,
    storage_budget: _SnapshotBuildBudget | None = None,
    storage_preflight_complete: bool = False,
) -> dict:
    """Build a recursive snapshot of the project tree."""
    if storage_budget is None:
        storage_budget = _SnapshotBuildBudget()
    if not storage_preflight_complete:
        await _preflight_live_project_storage(project, session, storage_budget)
        storage_preflight_complete = True
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
        select(Experiment)
        .where(
            Experiment.project_id == project.id,
            or_(Experiment.user_id == project.user_id, uses_managed_project_access()),
        )
        .options(selectinload(Experiment.files))
    )
    experiments_snap = []
    for exp in exp_result.scalars().all():
        metadata: dict[str, Any] = {}
        if exp.metadata_path:
            try:
                metadata = await asyncio.to_thread(read_metadata, resolve_data_path(exp.metadata_path))
            except Exception:
                logger.debug("Could not read experiment metadata for project export", exc_info=True)
        experiment_snapshot = {
            "id": exp.id,
            "name": exp.name,
            "description": exp.description,
            "metadata": metadata,
            "file_count": len(exp.files),
            "files": [
                {
                    "id": f.id,
                    "file_path": f.file_path,
                    "stage": f.stage,
                    "file_type": f.file_type,
                    "file_size_bytes": f.file_size_bytes,
                }
                for f in sorted(exp.files, key=lambda item: item.id)
            ],
        }
        bound_storage = await asyncio.to_thread(
            _bind_experiment_storage_snapshot,
            experiment_snapshot,
        )
        definition = bound_storage.definition
        if definition is not None:
            try:
                loaded = await load_project_dataset(
                    session,
                    user_id=actor_id if actor_id is not None else exp.user_id,
                    experiment_id=exp.id,
                    stage="raw",
                    definition_override=definition,
                    prepared_overrides_by_file=bound_storage.prepared_by_file,
                )
            except ValueError as exc:
                raise ProjectSnapshotStateError("Collection definition does not match the saved project data") from exc
            if (
                loaded.collection_definition_sha256 != definition.sha256
                or loaded.scientific_collection_sha256 is None
                or loaded.source_manifest_sha256 != bound_storage.source_manifest_sha256
            ):
                raise ProjectSnapshotStateError("Saved scientific collection identity is inconsistent")
            projection = scientific_dataset_projection(loaded.dataset)
            experiment_snapshot["collection_source_manifest_sha256"] = loaded.source_manifest_sha256
            experiment_snapshot["scientific_dataset_projection"] = projection
            experiment_snapshot["scientific_dataset_projection_sha256"] = scientific_dataset_projection_sha256(
                projection
            )
            experiment_snapshot["scientific_collection_schema_version"] = loaded.dataset.meta["source_collection"][
                "scientific_collection_schema_version"
            ]
            experiment_snapshot["scientific_collection_sha256"] = loaded.scientific_collection_sha256
        else:
            experiment_snapshot["scientific_dataset_projection"] = None
            experiment_snapshot["scientific_dataset_projection_sha256"] = None
            experiment_snapshot["scientific_collection_schema_version"] = None
        await asyncio.to_thread(_require_bound_storage_still_current, experiment_snapshot, bound_storage)
        experiments_snap.append(experiment_snapshot)

    # Workflows with nodes and edges
    wf_result = await session.execute(
        select(Workflow)
        .where(
            Workflow.project_id == project.id,
            or_(Workflow.user_id == project.user_id, uses_managed_project_access()),
        )
        .options(selectinload(Workflow.nodes), selectinload(Workflow.edges), selectinload(Workflow.data_source_links))
    )
    workflows_snap = []
    for wf in wf_result.scalars().all():
        workflows_snap.append(
            {
                "classifier_validation_semantics": CURRENT_CLASSIFIER_VALIDATION_SEMANTICS,
                "id": wf.id,
                "name": wf.name,
                "description": wf.description,
                "status": wf.status,
                "purpose": wf.purpose,
                "fold_validation_plan": wf.fold_validation_plan,
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
                        "node_type": canonical_node_type(n.node_type),
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
        select(ProjectScript)
        .where(
            ProjectScript.project_id == project.id,
            or_(ProjectScript.user_id == project.user_id, uses_managed_project_access()),
        )
        .order_by(ProjectScript.priority)
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
            ModelArtifact.project_id == project.id,
            or_(ModelArtifact.user_id == project.user_id, uses_managed_project_access()),
            ModelArtifact.is_active == True,  # noqa: E712
        )
    )
    models_snap = []
    for m in model_result.scalars().all():
        source_version = None
        if m.workflow_version_id is not None:
            version = await session.scalar(
                select(WorkflowVersion).where(
                    WorkflowVersion.id == m.workflow_version_id,
                    WorkflowVersion.workflow_id == m.workflow_id,
                )
            )
            if version is None:
                raise ProjectSnapshotStateError("Model source workflow version is unavailable")
            source_version = {
                "id": version.id,
                "workflow_id": version.workflow_id,
                "version_number": version.version_number,
                "snapshot": version.snapshot,
            }
        metrics = _safe_parse_metrics(m.metrics_json)
        models_snap.append(
            {
                "artifact_uid": m.artifact_uid,
                "name": m.name,
                "display_name": m.display_name,
                "description": m.description,
                "model_type": m.model_type,
                "node_id": m.node_id,
                "workflow_id": m.workflow_id,
                "source_workflow_version": source_version,
                "training_dataset_id": m.training_dataset_id,
                "n_features": m.n_features,
                "n_components": m.n_components,
                "classes": _safe_json_value(m.classes_json),
                "feature_axis": _safe_json_value(m.feature_axis_json),
                "metrics": metrics,
                "integrity_hash": m.integrity_hash,
                "training_data_hash": m.training_data_hash,
                "training_scientific_digest": m.training_scientific_digest,
                "artifact_origin": m.artifact_origin,
                "canonical_lineage_digest": m.canonical_lineage_digest,
                "validation_evidence_digest": m.validation_evidence_digest,
                "preprocessing_summary": _safe_json_value(m.preprocessing_summary),
                "tags": list(m.tags or []),
                "is_deploy_ready": bool(m.is_deploy_ready),
            }
        )

    # Recursive children
    child_result = await session.execute(
        select(Project).where(
            Project.parent_id == project.id,
            Project.user_id == project.user_id,
        )
    )
    children_snap = []
    for child in child_result.scalars().all():
        children_snap.append(
            await _build_snapshot(
                child,
                session,
                actor_id=actor_id,
                storage_budget=storage_budget,
                storage_preflight_complete=storage_preflight_complete,
            )
        )

    from spectra_sherpa.app.contracts.project_evidence import project_evidence_snapshot

    metadata = dict(project.metadata_ or {})
    extension_evidence = await project_evidence_snapshot(session, project.id, actor_id or project.user_id)
    if extension_evidence:
        metadata["source_managed_campaigns"] = extension_evidence

    return {
        "id": project.id,
        "name": project.name,
        "description": project.description,
        "metadata": metadata,
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

    try:
        snapshot = await _build_snapshot(project, session, actor_id=current_user.id)
    except ProjectSnapshotStateError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

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


@router.get(
    "/{project_id}/export",
    dependencies=[Depends(demo_guard("data_bearing_project_export"))],
)
async def export_project(
    project_id: int,
    version_id: int | None = None,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> FileResponse:
    """Download project as a .spectrapy archive (ZIP with project.json + model artifacts)."""
    if not await check_export_allowed(current_user, session):
        raise HTTPException(status_code=403, detail="Export not permitted for this user")

    if uses_managed_project_access():
        await require_scientific_access(session, current_user.id, project_id, "read")
        if version_id is not None:
            raise HTTPException(409, "Historical project export is not qualified")
        project = await session.get(Project, project_id)
    else:
        project = await require_project(project_id, current_user.id, session)

    if version_id:
        query = select(ProjectVersion).where(ProjectVersion.id == version_id, ProjectVersion.project_id == project_id)
        result = await session.execute(query)
        version = result.scalar_one_or_none()
        if version is None:
            raise HTTPException(status_code=404, detail="Version not found")
        snapshot = version.snapshot
    else:
        try:
            snapshot = await _build_snapshot(project, session, actor_id=current_user.id)
        except ProjectSnapshotStateError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    snapshot = _prepare_project_export_snapshot(snapshot)
    allowed_ids = await _project_experiment_ids(project.id, current_user.id, session)
    try:
        await asyncio.to_thread(
            _preflight_project_data_members,
            snapshot,
            allowed_experiment_ids=allowed_ids,
        )
        await _verify_saved_scientific_collections(
            snapshot,
            allowed_experiment_ids=allowed_ids,
            user_id=current_user.id,
            session=session,
        )
        data_members, model_members = await _collect_project_archive_members(
            snapshot,
            allowed_experiment_ids=allowed_ids,
        )
    except ProjectSnapshotStateError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    filename = f"{safe_download_stem(project.name, fallback='project')}.spectrapy"
    archive_path = _temporary_archive_path(".spectrapy")
    try:
        await asyncio.to_thread(
            write_archive_to_path,
            archive_path,
            project_payload=snapshot,
            members=[*data_members, *model_members],
            package_mode="legacy",
            payload_name="project.json",
            include_manifest=False,
        )
    except SherpaObjectError as exc:
        _cleanup_temporary_archive(archive_path)
        logger.warning("Could not build .spectrapy export for project %s: %s", project.id, exc)
        raise HTTPException(status_code=500, detail="Project export archive could not be built") from exc
    if uses_managed_project_access():
        try:
            await require_scientific_access(session, current_user.id, project_id, "read")
            from spectra_sherpa.app.models.data_egress import UserEgressDefaults

            privacy = await session.scalar(
                select(UserEgressDefaults)
                .where(UserEgressDefaults.user_id == current_user.id)
                .execution_options(populate_existing=True)
            )
            if privacy is not None and not privacy.allow_export:
                raise HTTPException(403, "Export permission was withdrawn")
        except BaseException:
            _cleanup_temporary_archive(archive_path)
            raise
    return FileResponse(
        archive_path,
        media_type="application/zip",
        filename=filename,
        headers=_project_archive_response_headers(filename, snapshot),
        background=BackgroundTask(_cleanup_temporary_archive, archive_path),
    )


def _read_bounded_regular_model_member(path: Path, *, max_bytes: int) -> bytes:
    """Read one preflighted model member without following a changed leaf."""

    if max_bytes < 0:
        raise ProjectSnapshotStateError("Project archive exceeds the retained-byte limit")
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_BINARY", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise ProjectSnapshotStateError("Project model artifact changed during export") from exc
    try:
        observed = os.fstat(descriptor)
        if not stat.S_ISREG(observed.st_mode):
            raise ProjectSnapshotStateError("Project model artifact is not a regular file")
        if observed.st_size > max_bytes:
            raise ProjectSnapshotStateError("Project archive exceeds the retained-byte limit")
        chunks: list[bytes] = []
        remaining = observed.st_size
        while remaining:
            chunk = os.read(descriptor, min(1024 * 1024, remaining))
            if not chunk:
                raise ProjectSnapshotStateError("Project model artifact changed during export")
            chunks.append(chunk)
            remaining -= len(chunk)
        if os.read(descriptor, 1):
            raise ProjectSnapshotStateError("Project model artifact changed during export")
        return b"".join(chunks)
    finally:
        os.close(descriptor)


def _model_members_for_snapshot(
    snapshot: dict[str, Any],
    *,
    max_total_bytes: int,
) -> list[ArchiveMember]:
    """Collect bounded, regular model artifact files for a portable object."""
    members: list[ArchiveMember] = []
    retained_bytes = 0
    decoded_bytes = 0
    model_records: list[tuple[str, dict[str, Any], dict[str, Any]]] = []
    seen_uids: set[str] = set()
    archived_experiments = _snapshot_experiment_index(snapshot)
    for owner_snapshot, model_data in _iter_snapshot_models(snapshot):
        artifact_uid = model_data.get("artifact_uid")
        if not isinstance(artifact_uid, str):
            raise ProjectSnapshotStateError("Project model identity is invalid")
        try:
            canonical_uid = str(uuid.UUID(artifact_uid))
        except ValueError as exc:
            raise ProjectSnapshotStateError("Project model identity is invalid") from exc
        if artifact_uid != canonical_uid or canonical_uid in seen_uids:
            raise ProjectSnapshotStateError("Project model identity is invalid")
        seen_uids.add(canonical_uid)
        model_records.append((canonical_uid, owner_snapshot, model_data))
    if not model_records:
        return members
    try:
        from spectra_sherpa.app.services.model_store import get_model_store

        store = get_model_store()
    except RuntimeError as exc:
        raise ProjectSnapshotStateError("Project model storage is unavailable") from exc
    for uid, owner_snapshot, model_record in model_records:
        owner_project_id = _as_int(owner_snapshot.get("id"))
        artifact_dir = store._artifact_dir(uid)
        manifest_path = artifact_dir / "manifest.json"
        arrays_path = artifact_dir / "arrays.npz"
        manifest_bytes = _read_bounded_regular_model_member(
            manifest_path,
            max_bytes=max_total_bytes - retained_bytes,
        )
        retained_bytes += len(manifest_bytes)
        arrays_bytes = _read_bounded_regular_model_member(
            arrays_path,
            max_bytes=max_total_bytes - retained_bytes,
        )
        retained_bytes += len(arrays_bytes)
        try:
            manifest = parse_model_manifest_json(manifest_bytes)
            declared_array_bytes, inventory = _preflight_model_npz(
                arrays_bytes,
                max_decoded_bytes=max_total_bytes - decoded_bytes - len(manifest_bytes),
            )
            _validate_received_model_manifest(
                manifest,
                artifact_uid=uid,
                model_record=model_record,
                arrays_payload=arrays_bytes,
                array_inventory=inventory,
            )
            # A legacy model without portable source authority cannot be
            # restored. Omit only that model, and mark the archive as partial;
            # all other custody failures remain fatal.
            try:
                _bind_archived_model_training_source(
                    manifest,
                    model_record,
                    owner_project_id=owner_project_id,
                    experiments=archived_experiments,
                )
            except HTTPException as exc:
                if exc.detail != "Project model training source provenance is missing":
                    raise
                owner_models = owner_snapshot["models"]
                owner_models[:] = [row for row in owner_models if row is not model_record]
                metadata = snapshot.get("metadata")
                if not isinstance(metadata, dict):
                    raise ProjectSnapshotStateError("Project metadata is invalid") from exc
                omissions = metadata.setdefault("portable_export_omitted_models", [])
                if not isinstance(omissions, list):
                    raise ProjectSnapshotStateError("Project export omissions are invalid") from exc
                if not any(isinstance(row, dict) and row.get("artifact_uid") == uid for row in omissions):
                    omissions.append(
                        {
                            "artifact_uid": uid,
                            "owner_project_id": owner_project_id,
                            "reason": "training_source_provenance_missing",
                        }
                    )
                continue
            if manifest.get("artifact_origin") is not None or model_record.get("artifact_origin") is not None:
                import numpy as np

                with np.load(io.BytesIO(arrays_bytes), allow_pickle=False) as npz:
                    canonical_arrays = {name: np.asarray(npz[name]) for name in npz.files}
                _validate_canonical_model_projection(manifest, canonical_arrays, model_record)
            decoded_bytes += len(manifest_bytes) + declared_array_bytes
            if decoded_bytes > max_total_bytes:
                raise HTTPException(status_code=413, detail="Project model arrays exceed the decoded-byte limit")
        except (HTTPException, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
            raise ProjectSnapshotStateError("Project model artifact is inconsistent") from exc
        members.extend(
            [
                ArchiveMember(f"models/{uid}/manifest.json", manifest_bytes),
                ArchiveMember(f"models/{uid}/arrays.npz", arrays_bytes),
            ]
        )
    return members


def _preflight_model_member_bytes(snapshot: dict[str, Any]) -> int:
    model_uids = [
        str(model_data["artifact_uid"])
        for _, model_data in _iter_snapshot_models(snapshot)
        if model_data.get("artifact_uid")
    ]
    model_uids = list(dict.fromkeys(model_uids))
    if not model_uids:
        return 0
    try:
        from spectra_sherpa.app.services.model_store import get_model_store

        store = get_model_store()
    except RuntimeError as exc:
        raise ProjectSnapshotStateError("Project model storage is unavailable") from exc
    retained = 0
    for uid in model_uids:
        artifact_dir = store._artifact_dir(uid)
        for name in ("manifest.json", "arrays.npz"):
            path = artifact_dir / name
            try:
                observed = path.lstat()
            except FileNotFoundError as exc:
                raise ProjectSnapshotStateError("Project model artifact changed during export") from exc
            if stat.S_ISLNK(observed.st_mode) or not stat.S_ISREG(observed.st_mode):
                raise ProjectSnapshotStateError("Project model artifact is not a regular file")
            retained += observed.st_size
            if retained > PROJECT_ARCHIVE_RETAINED_BYTES_MAX:
                raise ProjectSnapshotStateError("Project archive exceeds the retained-byte limit")
    return retained


async def _collect_project_archive_members(
    snapshot: dict[str, Any],
    *,
    allowed_experiment_ids: set[int],
) -> tuple[list[ArchiveMember], list[ArchiveMember]]:
    _, data_bytes = await asyncio.to_thread(
        _preflight_project_data_members,
        snapshot,
        allowed_experiment_ids=allowed_experiment_ids,
    )
    model_bytes = await asyncio.to_thread(_preflight_model_member_bytes, snapshot)
    if data_bytes + model_bytes > PROJECT_ARCHIVE_RETAINED_BYTES_MAX:
        raise ProjectSnapshotStateError("Project archive exceeds the retained-byte limit")
    data_members = await asyncio.to_thread(
        _collect_project_data_members,
        snapshot,
        allowed_experiment_ids=allowed_experiment_ids,
    )
    model_members = await asyncio.to_thread(
        _model_members_for_snapshot,
        snapshot,
        max_total_bytes=PROJECT_ARCHIVE_RETAINED_BYTES_MAX - data_bytes,
    )
    return data_members, model_members


def _public_archive_validation_error_detail(message: Any) -> dict[str, str]:
    """Map archive-parser details to stable, user-safe validation errors."""

    text = str(message)
    if text.startswith("Archive uncompressed payload exceeds limit"):
        return {
            "code": "archive_uncompressed_limit_exceeded",
            "message": "Archive uncompressed payload exceeds the configured upload limit.",
        }
    if text.startswith("Unsupported .sherpa object version"):
        return {
            "code": "unsupported_object_version",
            "message": "Unsupported .sherpa object version.",
        }
    if text.startswith("Unsafe archive member path"):
        return {
            "code": "unsafe_archive_member_path",
            "message": "Archive contains an unsafe member path.",
        }
    if text.startswith("Missing required payload:"):
        return {
            "code": "missing_required_payload",
            "message": "Archive is missing a required payload.",
        }
    if text.startswith("Missing required manifest:"):
        return {
            "code": "missing_required_manifest",
            "message": "Archive is missing the required manifest.",
        }
    if text.startswith("Duplicate archive member:"):
        return {
            "code": "duplicate_archive_member",
            "message": "Archive contains duplicate members.",
        }
    if text.startswith("Manifest member missing from archive:"):
        return {
            "code": "manifest_member_missing",
            "message": "Manifest references a missing archive member.",
        }
    if text.startswith("Manifest member entry is not an object:"):
        return {
            "code": "manifest_member_invalid",
            "message": "Manifest contains an invalid member entry.",
        }
    if text.startswith("SHA-256 mismatch for"):
        return {
            "code": "archive_member_hash_mismatch",
            "message": "Archive member hash does not match the manifest.",
        }
    if text.startswith("Size mismatch for"):
        return {
            "code": "archive_member_size_mismatch",
            "message": "Archive member size does not match the manifest.",
        }
    if text.startswith("Archive member missing from manifest:"):
        return {
            "code": "archive_member_not_in_manifest",
            "message": "Archive contains a member missing from the manifest.",
        }
    if text.startswith("Manifest content_hash does not match"):
        return {
            "code": "manifest_content_hash_mismatch",
            "message": "Manifest content hash does not match the archive payloads.",
        }
    if text.startswith("Manifest schema must be"):
        return {
            "code": "unsupported_manifest_schema",
            "message": "Archive manifest schema is unsupported.",
        }
    if text.startswith("Manifest must be"):
        return {
            "code": "invalid_manifest",
            "message": "Archive manifest is invalid.",
        }
    if text.startswith("Manifest payloads.members must be"):
        return {
            "code": "invalid_manifest_member_inventory",
            "message": "Archive manifest member inventory is invalid.",
        }
    if text.startswith("Only project .sherpa objects"):
        return {
            "code": "unsupported_object_type",
            "message": "Only project .sherpa objects are supported.",
        }
    if text.startswith("Invalid ZIP archive:"):
        return {
            "code": "invalid_zip_archive",
            "message": "File is not a valid ZIP archive.",
        }
    if text in {
        "Archive contains invalid JSON",
        f"{PROJECT_PAYLOAD} is not valid JSON",
        f"{SHERPA_OBJECT_MANIFEST} is invalid JSON",
    }:
        return {
            "code": "invalid_archive_json",
            "message": "Archive contains invalid JSON.",
        }
    if text in {f"{PROJECT_PAYLOAD} must contain a JSON object", "Archive project payload is invalid"}:
        return {
            "code": "invalid_project_payload",
            "message": "Archive project payload is invalid.",
        }
    return {
        "code": "archive_validation_failed",
        "message": "Archive validation failed. Check that the file is a valid SpectraSherpa object archive.",
    }


def _public_archive_report(report: dict[str, Any]) -> dict[str, Any]:
    """Remove parser/exception detail before returning archive reports over HTTP."""

    public = dict(report)
    errors = public.get("errors")
    if isinstance(errors, list):
        details = [_public_archive_validation_error_detail(error) for error in errors]
        public["errors"] = [detail["message"] for detail in details]
        public["error_details"] = details
    return public


@router.get(
    "/{project_id}/export/sherpa",
    dependencies=[Depends(demo_guard("data_bearing_project_export"))],
)
async def export_project_sherpa_object(
    project_id: int,
    version_id: int | None = None,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> FileResponse:
    """Download project as a portable .sherpa object with offline-verifiable manifest."""
    if not await check_export_allowed(current_user, session):
        raise HTTPException(status_code=403, detail="Export not permitted for this user")

    if uses_managed_project_access():
        await require_scientific_access(session, current_user.id, project_id, "read")
        if version_id is not None:
            raise HTTPException(409, "Historical project export is not qualified")
        project = await session.get(Project, project_id)
    else:
        project = await require_project(project_id, current_user.id, session)

    if version_id:
        query = select(ProjectVersion).where(ProjectVersion.id == version_id, ProjectVersion.project_id == project_id)
        result = await session.execute(query)
        version = result.scalar_one_or_none()
        if version is None:
            raise HTTPException(status_code=404, detail="Version not found")
        snapshot = version.snapshot
    else:
        try:
            snapshot = await _build_snapshot(project, session, actor_id=current_user.id)
        except ProjectSnapshotStateError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    snapshot = _prepare_project_export_snapshot(snapshot)
    allowed_ids = await _project_experiment_ids(project.id, current_user.id, session)
    try:
        await asyncio.to_thread(
            _preflight_project_data_members,
            snapshot,
            allowed_experiment_ids=allowed_ids,
        )
        await _verify_saved_scientific_collections(
            snapshot,
            allowed_experiment_ids=allowed_ids,
            user_id=current_user.id,
            session=session,
        )
        data_members, model_members = await _collect_project_archive_members(
            snapshot,
            allowed_experiment_ids=allowed_ids,
        )
    except ProjectSnapshotStateError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    filename = f"{safe_download_stem(project.name, fallback='project')}.sherpa"
    archive_path = _temporary_archive_path(".sherpa")
    try:
        await asyncio.to_thread(
            write_archive_to_path,
            archive_path,
            project_payload=snapshot,
            members=[*model_members, *data_members],
            package_mode="full",
        )
    except SherpaObjectError as exc:
        _cleanup_temporary_archive(archive_path)
        logger.warning("Could not build .sherpa export for project %s: %s", project.id, exc)
        raise HTTPException(status_code=500, detail="Project export archive could not be built") from exc
    if uses_managed_project_access():
        try:
            await require_scientific_access(session, current_user.id, project_id, "read")
            from spectra_sherpa.app.models.data_egress import UserEgressDefaults

            privacy = await session.scalar(
                select(UserEgressDefaults)
                .where(UserEgressDefaults.user_id == current_user.id)
                .execution_options(populate_existing=True)
            )
            if privacy is not None and not privacy.allow_export:
                raise HTTPException(403, "Export permission was withdrawn")
        except BaseException:
            _cleanup_temporary_archive(archive_path)
            raise
    return FileResponse(
        archive_path,
        media_type="application/vnd.spectrasherpa.object+zip",
        filename=filename,
        headers=_project_archive_response_headers(filename, snapshot),
        background=BackgroundTask(_cleanup_temporary_archive, archive_path),
    )


@router.post("/objects/inspect", dependencies=[Depends(demo_guard("project_import"))])
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


@router.post("/objects/validate", dependencies=[Depends(demo_guard("project_import"))])
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


async def _remap_imported_workflow_model_uids(
    session: AsyncSession,
    workflow_remap: dict[int, int],
    remap: dict[str, str],
) -> None:
    """Keep live imported load/apply nodes aligned after artifact UID collisions."""
    if not workflow_remap or not remap:
        return
    result = await session.execute(select(WorkflowNode).where(WorkflowNode.workflow_id.in_(workflow_remap.values())))
    for node in result.scalars().all():
        parameters = node.parameters
        if not isinstance(parameters, dict) or parameters.get("model_id") not in remap:
            continue
        node.parameters = {**parameters, "model_id": remap[parameters["model_id"]]}


async def _restore_project_data_sources(
    project: Project,
    project_json: dict[str, Any],
    experiment_remap: dict[int, int],
    file_remap: dict[int, int],
    session: AsyncSession,
) -> dict[int, int]:
    """Recreate project data source rows and return old-id -> new-id map."""
    remap: dict[int, int] = {}
    for source_data in project_json.get("data_sources", []):
        if not isinstance(source_data, dict):
            continue
        source_ref = _remap_source_ref(source_data.get("source_ref"), experiment_remap, file_remap)
        fingerprint = _remap_source_ref(source_data.get("fingerprint"), experiment_remap, file_remap)
        if fingerprint == source_data.get("fingerprint") and source_data.get("fingerprint") == source_data.get(
            "source_ref"
        ):
            fingerprint = source_ref
        data_source = ProjectDataSource(
            project_id=project.id,
            display_name=source_data.get("display_name") or "Imported Data Source",
            source_type=source_data.get("source_type") or "external",
            source_ref=source_ref,
            fingerprint=fingerprint,
            color=source_data.get("color") or "#3b82f6",
            metadata_=_remap_project_local_ids(source_data.get("metadata") or {}, experiment_remap, file_remap),
            sort_order=source_data.get("sort_order") or 0,
        )
        session.add(data_source)
        await session.flush()
        old_id = source_data.get("id")
        if isinstance(old_id, int):
            remap[old_id] = data_source.id
    return remap


async def _restore_project_experiments(
    project: Project,
    user_id: int,
    project_json: dict[str, Any],
    zf: zipfile.ZipFile,
    session: AsyncSession,
    restored_experiment_ids: list[int],
    restored_prepared_sidecars: list[Path],
    reference_artifacts: dict[str, Path],
) -> tuple[dict[int, int], dict[int, int]]:
    """Restore project experiments and bundled files before workflow remapping."""
    experiment_remap: dict[int, int] = {}
    file_remap: dict[int, int] = {}
    max_member_bytes = settings.max_file_size_mb * 1024 * 1024

    for exp_data in project_json.get("experiments", []):
        if not isinstance(exp_data, dict):
            raise HTTPException(status_code=400, detail="Project experiment record is invalid")
        _validate_experiment_storage_snapshot(exp_data)
        experiment = Experiment(
            user_id=user_id,
            project_id=project.id,
            name=exp_data.get("name") or "Imported Dataset",
            description=exp_data.get("description"),
            metadata_path="",
        )
        session.add(experiment)
        await session.flush()
        restored_experiment_ids.append(experiment.id)

        ensure_experiment_dirs(experiment.id)
        metadata_file = metadata_path_for(experiment.id)
        metadata = exp_data.get("metadata") if isinstance(exp_data.get("metadata"), dict) else {}
        write_metadata(metadata_file, metadata)
        experiment.metadata_path = relative_to_data_dir(metadata_file)

        old_experiment_id = _as_int(exp_data.get("id"))
        if old_experiment_id is None:
            raise HTTPException(status_code=400, detail="Project data file is missing experiment reference")
        experiment_remap[old_experiment_id] = experiment.id

        definition = _collection_definition_from_archive(zf, exp_data, old_experiment_id)

        for file_data in exp_data.get("files", []):
            if not isinstance(file_data, dict):
                raise HTTPException(status_code=400, detail="Project storage snapshot file record is invalid")
            try:
                rel_path = _normalize_experiment_file_path(file_data.get("file_path"), file_data.get("stage"))
            except ValueError as exc:
                raise HTTPException(status_code=400, detail="Invalid project data file path") from exc

            target_path = (experiment_dir(experiment.id) / rel_path).resolve()
            if not target_path.is_relative_to(experiment_dir(experiment.id).resolve()):
                raise HTTPException(status_code=400, detail="Invalid project data file path")

            expected_hash = _require_project_data_hash(file_data)
            prepared = _prepared_data_from_archive(zf, file_data, old_experiment_id, rel_path)
            if file_data.get("archive_status") == "external_reference":
                reference = _require_external_reference_identity(
                    file_data.get("external_reference"),
                    saved_size=int(file_data["saved_size_bytes"]),
                    saved_sha256=expected_hash,
                )
                artifact_path = reference_artifacts.get(str(reference["artifact_id"]))
                if artifact_path is None:
                    raise HTTPException(
                        status_code=409,
                        detail=_reference_rebind_required_detail(
                            _project_external_reference_requirements(project_json)
                        ),
                    )
                try:
                    materialized = await asyncio.to_thread(
                        materialize_reference_projection,
                        artifact_path,
                        str(reference["projection_id"]),
                        persist_member_to=target_path,
                    )
                except ReferenceMaterializationError as exc:
                    raise HTTPException(
                        status_code=422,
                        detail={
                            "code": "project_reference_mismatch",
                            "message": "The selected reference file could not reproduce the project's exact science.",
                        },
                    ) from exc
                if dict(materialized.portable_reference) != reference:
                    raise HTTPException(status_code=400, detail="Project reference materialization identity changed")
                write_registered_reference_sidecar(target_path, materialized.portable_reference)
                bytes_written = target_path.stat().st_size
            else:
                archive_member = file_data.get("archive_member")
                if not archive_member:
                    raise HTTPException(status_code=400, detail="Project data file is missing archive binding")
                expected_member = _expected_project_data_member(file_data, old_experiment_id, rel_path)
                bytes_written = _read_archive_member_to_path(
                    zf,
                    expected_member,
                    target_path,
                    max_member_bytes=max_member_bytes,
                )
            if await asyncio.to_thread(_sha256_file, target_path) != expected_hash:
                raise HTTPException(status_code=400, detail="Project data file hash mismatch")
            if file_data.get("saved_size_bytes") not in {None, bytes_written}:
                raise HTTPException(status_code=400, detail="Saved project data size does not match archive bytes")
            if file_data.get("saved_sha256") not in {None, expected_hash}:
                raise HTTPException(status_code=400, detail="Saved project data digest does not match archive bytes")
            prepared_sha = sha256_bytes(_canonical_prepared_data_bytes(prepared))
            if file_data.get("saved_prepared_data_sha256") not in {None, prepared_sha}:
                raise HTTPException(status_code=400, detail="Saved prepared-data digest does not match archive bytes")

            file_row = await add_experiment_file(
                session=session,
                experiment_id=experiment.id,
                stage=str(file_data.get("stage") or "raw"),
                file_path=rel_path,
                file_size_bytes=bytes_written,
                file_type=file_data.get("file_type") or target_path.suffix.lstrip(".") or None,
                flush_only=True,
            )
            old_file_id = _as_int(file_data.get("id"))
            if old_file_id is not None:
                file_remap[old_file_id] = file_row.id
            save_prepared_data_overrides(prepared, file_path=str(target_path))
            restored_prepared_sidecars.append(sidecar_path(file_path=str(target_path), source=None, name=None))

        if definition is not None:
            await session.flush()
            try:
                loaded = await load_project_dataset(
                    session,
                    user_id=user_id,
                    experiment_id=experiment.id,
                    stage="raw",
                    definition_override=definition,
                    strict_prepared_data=True,
                )
            except ValueError as exc:
                raise HTTPException(
                    status_code=400,
                    detail="Collection definition does not match the restored project data",
                ) from exc
            if loaded.collection_definition_sha256 != definition.sha256:
                raise HTTPException(status_code=400, detail="Restored collection-definition identity is inconsistent")
            if loaded.source_manifest_sha256 != exp_data.get("collection_source_manifest_sha256"):
                raise HTTPException(status_code=400, detail="Restored collection source identity is inconsistent")
            restored_projection = scientific_dataset_projection(loaded.dataset)
            if restored_projection != exp_data.get("scientific_dataset_projection"):
                raise HTTPException(status_code=400, detail="Restored decoded scientific projection is inconsistent")
            if scientific_dataset_projection_sha256(restored_projection) != exp_data.get(
                "scientific_dataset_projection_sha256"
            ):
                raise HTTPException(
                    status_code=400,
                    detail="Restored decoded scientific projection digest is inconsistent",
                )
            if exp_data.get("scientific_collection_schema_version") != loaded.dataset.meta["source_collection"].get(
                "scientific_collection_schema_version"
            ):
                raise HTTPException(status_code=400, detail="Restored scientific collection schema is inconsistent")
            if loaded.scientific_collection_sha256 != exp_data.get("scientific_collection_sha256"):
                raise HTTPException(status_code=400, detail="Restored scientific collection identity is inconsistent")
            await asyncio.to_thread(write_collection_definition, experiment.id, definition.payload)

    return experiment_remap, file_remap


def _remap_workflow_parameters(
    value: Any,
    data_source_remap: dict[int, int],
    experiment_remap: dict[int, int],
    file_remap: dict[int, int],
) -> Any:
    """Best-effort rewrite of known project-local IDs inside node parameters."""
    if isinstance(value, dict):
        rewritten = {
            key: _remap_workflow_parameters(item, data_source_remap, experiment_remap, file_remap)
            for key, item in value.items()
        }
        for key in ("data_source_id", "primary_data_source_id"):
            if isinstance(rewritten.get(key), int) and rewritten[key] in data_source_remap:
                rewritten[key] = data_source_remap[rewritten[key]]
        for key in ("dataset_id", "experiment_id"):
            old_id = _as_int(rewritten.get(key))
            if old_id in experiment_remap:
                rewritten[key] = experiment_remap[old_id]
        old_file_id = _as_int(rewritten.get("file_id"))
        if old_file_id in file_remap:
            rewritten["file_id"] = file_remap[old_file_id]
        return rewritten
    if isinstance(value, list):
        return [_remap_workflow_parameters(item, data_source_remap, experiment_remap, file_remap) for item in value]
    return value


async def _restore_workflows_from_snapshot(
    project: Project,
    user_id: int,
    project_json: dict[str, Any],
    data_source_remap: dict[int, int],
    experiment_remap: dict[int, int],
    file_remap: dict[int, int],
    session: AsyncSession,
    known_workflow_remap: dict[int, int] | None = None,
) -> dict[int, int]:
    """Recreate workflow rows from a project snapshot."""
    workflow_remap: dict[int, int] = {}
    pending_created_from: list[tuple[Workflow, int]] = []

    for wf_data in project_json.get("workflows", []):
        if not isinstance(wf_data, dict):
            continue
        fold_plan = wf_data.get("fold_validation_plan")
        if fold_plan is not None:
            from spectra_sherpa.app.services.dag.sheet_fold_validation import SheetFoldValidationPlan

            try:
                fold_plan = SheetFoldValidationPlan.from_dict(fold_plan).as_dict()
            except ValueError as exc:
                raise HTTPException(status_code=422, detail=str(exc)) from exc
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
            purpose=require_workflow_purpose(wf_data.get("purpose")),
            fold_validation_plan=fold_plan,
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
                    node_id=node_data["node_id"],
                    node_type=node_data["node_type"],
                    label=node_data.get("label"),
                    parameters=_remap_workflow_parameters(
                        node_data.get("parameters") or {},
                        data_source_remap,
                        experiment_remap,
                        file_remap,
                    ),
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
    combined_workflow_remap = {**(known_workflow_remap or {}), **workflow_remap}
    for workflow, old_parent_id in pending_created_from:
        workflow.created_from_workflow_id = combined_workflow_remap.get(old_parent_id)
    return workflow_remap


async def _restore_scripts_from_snapshot(
    project: Project,
    user_id: int,
    project_json: dict[str, Any],
    workflow_remap: dict[int, int],
    session: AsyncSession,
) -> None:
    """Recreate script rows for one project snapshot."""
    for s_data in project_json.get("scripts", []):
        if not isinstance(s_data, dict):
            continue
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


async def _restore_project_tree_from_snapshot(
    project_json: dict[str, Any],
    *,
    parent_project: Project | None,
    admitted_project: Project | None = None,
    user_id: int,
    zf: zipfile.ZipFile,
    session: AsyncSession,
    restored_experiment_ids: list[int],
    restored_prepared_sidecars: list[Path],
    reference_artifacts: dict[str, Path],
    project_remap: dict[int, int],
    experiment_remap: dict[int, int],
    file_remap: dict[int, int],
    data_source_remap: dict[int, int],
    workflow_remap: dict[int, int],
) -> Project:
    """Recreate one project snapshot and all descendants."""
    from spectra_sherpa.app.contracts.scientific_access import create_managed_project

    fields = dict(
        parent_id=parent_project.id if parent_project is not None else None,
        name=project_json.get("name", "Imported Project"),
        description=project_json.get("description"),
        metadata=project_json.get("metadata", {}),
        technique=project_json.get("technique"),
        sample_type=project_json.get("sample_type"),
    )
    project = admitted_project or await create_managed_project(session, user_id, ProjectCreate(**fields))
    if project is None:
        fields["metadata_"] = fields.pop("metadata")
        project = Project(user_id=user_id, **fields)
        session.add(project)
    await session.flush()

    old_project_id = _as_int(project_json.get("id"))
    if old_project_id is not None:
        project_remap[old_project_id] = project.id

    local_experiment_remap, local_file_remap = await _restore_project_experiments(
        project,
        user_id,
        project_json,
        zf,
        session,
        restored_experiment_ids,
        restored_prepared_sidecars,
        reference_artifacts,
    )
    experiment_remap.update(local_experiment_remap)
    file_remap.update(local_file_remap)

    local_data_source_remap = await _restore_project_data_sources(
        project,
        project_json,
        experiment_remap,
        file_remap,
        session,
    )
    data_source_remap.update(local_data_source_remap)

    local_workflow_remap = await _restore_workflows_from_snapshot(
        project,
        user_id,
        project_json,
        data_source_remap,
        experiment_remap,
        file_remap,
        session,
        known_workflow_remap=workflow_remap,
    )
    workflow_remap.update(local_workflow_remap)

    await _restore_scripts_from_snapshot(project, user_id, project_json, workflow_remap, session)

    for child in project_json.get("children", []):
        if isinstance(child, dict):
            await _restore_project_tree_from_snapshot(
                child,
                parent_project=project,
                user_id=user_id,
                zf=zf,
                session=session,
                restored_experiment_ids=restored_experiment_ids,
                restored_prepared_sidecars=restored_prepared_sidecars,
                reference_artifacts=reference_artifacts,
                project_remap=project_remap,
                experiment_remap=experiment_remap,
                file_remap=file_remap,
                data_source_remap=data_source_remap,
                workflow_remap=workflow_remap,
            )

    return project


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


def _purge_prepared_sidecars(paths: list[Path]) -> None:
    """Best-effort delete of prepared-data records from a rolled-back import."""

    for path in paths:
        try:
            path.unlink(missing_ok=True)
        except OSError:  # pragma: no cover - best-effort cleanup
            logger.warning("Could not purge rolled-back prepared-data record")


async def _import_campaign_review_bytes(
    *,
    archive: bytes,
    user_id: int,
    max_bytes: int,
    commercial_subscription_id: int | None = None,
    commercial_workspace_id: int | None = None,
    publisher_trust_anchors: UploadFile | None = None,
    publisher_trust_confirmed: bool = False,
) -> dict[str, object]:
    """Authenticate and import one content-identified Campaign Review Package."""

    from spectra_sherpa.app.services.canonical_project_import import (
        CanonicalProjectImportError,
        import_canonical_project,
    )
    from spectra_sherpa.sdk.campaign_review import CampaignReviewError, CampaignReviewPackage
    from spectra_sherpa.sdk.canonical_publisher_attestation import (
        CanonicalPublisherAttestationError,
        CanonicalPublisherTrustAnchors,
        LocalCanonicalPublisherTrustStore,
    )
    from spectra_sherpa.sdk.project import ProjectIOError, load_bounded_json_object

    trust_path = settings.campaign_review_publisher_trust_anchors_path
    supplied_anchors = None
    if publisher_trust_anchors is not None:
        if app_config.mode != "local" or trust_path:
            raise HTTPException(status_code=403, detail="Publisher trust is managed by this deployment")
        if not publisher_trust_confirmed:
            raise HTTPException(
                status_code=422, detail="Confirm the publisher verification key came from an independent trusted source"
            )
        key_bytes = await _read_upload_with_limit(publisher_trust_anchors, max_bytes=64 * 1024)
        try:
            supplied_anchors = json.loads(key_bytes)
        except (ValueError, UnicodeDecodeError) as exc:
            raise HTTPException(
                status_code=422, detail="Publisher verification keys must be a valid JSON document"
            ) from exc
    if not trust_path and supplied_anchors is None:
        raise HTTPException(
            status_code=503,
            detail={
                "code": "campaign_publisher_trust_required",
                "message": "Campaign import requires independently obtained publisher verification keys. "
                "In local OSS, select the publisher public-key JSON and confirm its source. "
                "Managed deployments configure CAMPAIGN_REVIEW_PUBLISHER_TRUST_ANCHORS_PATH.",
            },
        )
    if trust_path and not Path(trust_path).is_absolute():
        raise HTTPException(status_code=503, detail="Campaign Review publisher trust-anchor path is invalid")
    try:
        if supplied_anchors is None:
            assert trust_path is not None
            supplied_anchors = load_bounded_json_object(Path(trust_path), max_bytes=2 * 1024 * 1024)
        anchors = CanonicalPublisherTrustAnchors.from_dict(supplied_anchors)
        review_package = CampaignReviewPackage.from_archive(
            archive,
            max_uncompressed_bytes=max_bytes,
        )
        authentication_digest = LocalCanonicalPublisherTrustStore.from_document(anchors).verify(
            package=review_package.application,
            attestation=review_package.publisher_attestation,
        )
        imported = await import_canonical_project(
            async_session,
            user_id=user_id,
            archive=review_package.application.archive,
            data_dir=settings.data_dir,
            max_uncompressed_bytes=max_bytes,
            commercial_subscription_id=commercial_subscription_id,
            commercial_workspace_id=commercial_workspace_id,
        )
    except (
        CampaignReviewError,
        CanonicalProjectImportError,
        CanonicalPublisherAttestationError,
        ProjectIOError,
    ) as exc:
        raise HTTPException(
            status_code=400, detail="Campaign Review Package cannot be authenticated and imported"
        ) from exc
    return {
        "project_id": imported.project_id,
        "workflow_id": imported.workflow_id,
        "application_handle": imported.application_handle,
        "application": {
            # The release registry owns this opaque identity. Consumers must
            # treat it as opaque and use the returned handle verbatim.
            "handle": imported.application_handle,
            "origin": "campaign_solution",
            "project_id": imported.project_id,
            "workflow_id": imported.workflow_id,
            "artifact_digest": imported.artifact_digest,
            "application_plan_digest": imported.application_plan_digest,
            "status": imported.status,
        },
        "artifact_digest": imported.artifact_digest,
        "application_plan_digest": imported.application_plan_digest,
        "package_sha256": imported.package_sha256,
        "campaign_review_sha256": review_package.archive_sha256,
        "publisher_attestation_digest": review_package.publisher_attestation.digest,
        "publisher_authenticated": True,
        "publisher_authentication_digest": authentication_digest,
        "status": imported.status,
        "dependency_readiness": {
            "ready": imported.dependency_readiness.ready,
            "blockers": list(imported.dependency_readiness.blockers),
            "remediation": list(imported.dependency_readiness.remediation),
        },
    }


@router.post(
    "/canonical-import",
    status_code=201,
    dependencies=[Depends(demo_guard("project_import"))],
)
async def import_canonical_project_archive(
    file: UploadFile = File(...),
    publisher_trust_anchors: UploadFile | None = File(None),
    publisher_trust_confirmed: bool = Form(False),
    commercial_subscription_id: int | None = Form(None),
    commercial_workspace_id: int | None = Form(None),
    current_user: User = Depends(get_current_user),
) -> dict[str, object]:
    """Import one sealed, data-free Campaign Review Package.

    This deliberately bypasses the legacy snapshot importer.  The service
    re-admits archive bytes before it begins a database transaction and never
    accepts an artifact path, project snapshot, or mutable workflow from the
    client.
    """

    max_bytes = settings.max_file_size_mb * 1024 * 1024
    declared_size = getattr(file, "size", None)
    if isinstance(declared_size, int) and declared_size > max_bytes:
        raise HTTPException(status_code=413, detail="Canonical project package exceeds the upload limit")
    archive = await _read_upload_with_limit(file, max_bytes=max_bytes)
    return await _import_campaign_review_bytes(
        archive=archive,
        user_id=current_user.id,
        max_bytes=max_bytes,
        commercial_subscription_id=commercial_subscription_id,
        commercial_workspace_id=commercial_workspace_id,
        publisher_trust_anchors=publisher_trust_anchors,
        publisher_trust_confirmed=publisher_trust_confirmed,
    )


@router.post(
    "/import", response_model=ProjectDetail, status_code=201, dependencies=[Depends(demo_guard("project_import"))]
)
async def import_project(
    file: UploadFile = File(...),
    publisher_trust_anchors: UploadFile | None = File(None),
    publisher_trust_confirmed: bool = Form(False),
    reference_files: list[UploadFile] | None = File(None),
    commercial_subscription_id: int | None = Form(None),
    commercial_workspace_id: int | None = Form(None),
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> ProjectDetail:
    """Import a .spectrapy or .sherpa archive to create a new project."""
    max_bytes = settings.max_file_size_mb * 1024 * 1024
    # Portable project archives may contain several uploaded data files plus
    # model artifacts. Keep the per-file upload cap, but allow a bounded
    # aggregate project archive budget for full project round trips.
    max_archive_uncompressed_bytes = max_bytes * PROJECT_ARCHIVE_UNCOMPRESSED_MULTIPLIER
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
    imported_experiment_ids: list[int] = []
    imported_prepared_sidecars: list[Path] = []
    reference_uploads = list(reference_files or [])
    reference_stage_root = Path(tempfile.mkdtemp(prefix="spectra-project-reference-import-"))
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

        from spectra_sherpa.sdk.campaign_review import CampaignReviewPackage

        if CampaignReviewPackage.has_archive_identity(upload_bytes):
            if reference_uploads:
                raise HTTPException(
                    status_code=400,
                    detail="Campaign Review Packages do not accept project reference-file attachments",
                )
            canonical = await _import_campaign_review_bytes(
                archive=upload_bytes,
                user_id=user_id,
                max_bytes=max_bytes,
                commercial_subscription_id=commercial_subscription_id,
                commercial_workspace_id=commercial_workspace_id,
                publisher_trust_anchors=publisher_trust_anchors,
                publisher_trust_confirmed=publisher_trust_confirmed,
            )
            # Canonical import owns and commits its independent transaction.
            # From this point the upload was consumed even if the convenience
            # projection below fails; never release its quota reservation.
            committed = True
            session.expire_all()
            imported_project = await session.scalar(
                select(Project).where(
                    Project.id == canonical["project_id"],
                    Project.user_id == user_id,
                )
            )
            if imported_project is None:
                raise HTTPException(status_code=500, detail="Imported Campaign Review project is unavailable")
            detail = await _project_to_detail(imported_project, session)
            # Preserve the one-time hand-off identity on the convenience
            # /projects/import response. The subsequent normal project fetch
            # intentionally does not manufacture an import event.
            detail.application = ImportedApplicationIdentity(**canonical["application"])
            detail.application_handle = canonical["application_handle"]
            return detail

        if publisher_trust_anchors is not None:
            raise HTTPException(
                status_code=422, detail="Publisher verification keys apply only to Campaign Review Packages"
            )

        preflight = preflight_zip_central_directory(
            upload_bytes,
            max_members=10_000,
            max_directory_bytes=16 * 1024 * 1024,
            max_uncompressed_bytes=max_archive_uncompressed_bytes,
        )
        upload_stream = io.BytesIO(upload_bytes)
        with zipfile.ZipFile(upload_stream, "r") as zf:
            total_uncompressed = preflight.total_uncompressed_bytes
            if total_uncompressed > max_archive_uncompressed_bytes:
                raise HTTPException(
                    status_code=413,
                    detail=(
                        f"Archive uncompressed payload too large ({total_uncompressed / (1024*1024):.1f} MB). "
                        f"Maximum is {max_archive_uncompressed_bytes / (1024*1024):.0f} MB."
                    ),
                )
            zip_names = set(zf.namelist())
            is_sherpa_object = SHERPA_OBJECT_MANIFEST in zip_names
            if is_sherpa_object:
                validation = validate_archive_bytes(
                    upload_bytes,
                    max_uncompressed_bytes=max_archive_uncompressed_bytes,
                )
                if not validation.get("valid"):
                    raise HTTPException(
                        status_code=400,
                        detail={"message": "Invalid .sherpa object", **_public_archive_report(validation)},
                    )

            project_info = zf.getinfo(PROJECT_PAYLOAD)
            if project_info.file_size > max_bytes:
                raise HTTPException(status_code=413, detail="Project payload exceeds size limit")

            project_json = json.loads(zf.read(PROJECT_PAYLOAD))
            _validate_current_project_archive(
                zf,
                project_json,
                is_sherpa_object=is_sherpa_object,
            )
            _admit_project_snapshot_graphs(project_json)
            # Never restore commercial authority from archive metadata. Allocate
            # a new canonical binding in this transaction before any extraction.
            from spectra_sherpa.app.contracts.scientific_access import create_managed_project

            project = await create_managed_project(
                session,
                user_id,
                ProjectCreate(
                    commercial_subscription_id=commercial_subscription_id,
                    commercial_workspace_id=commercial_workspace_id,
                    name=project_json.get("name", "Imported Project"),
                    description=project_json.get("description"),
                    metadata=project_json.get("metadata", {}),
                    technique=project_json.get("technique"),
                    sample_type=project_json.get("sample_type"),
                ),
            )
            reference_requirements = _project_external_reference_requirements(project_json)
            reference_artifacts = await _stage_project_reference_artifacts(
                reference_uploads,
                requirements=reference_requirements,
                destination=reference_stage_root / "admitted",
            )
            if app_config.site_profile == "pro":
                from spectra_sherpa.app.contracts.hot_storage import get_hot_storage_checker

                checker = get_hot_storage_checker()
                if checker is not None:
                    await checker(
                        session=session,
                        user_id=user_id,
                        project_id=project.id if project else None,
                        incoming_bytes=total_uncompressed
                        + sum(path.stat().st_size for path in reference_artifacts.values()),
                    )

            # Restore model artifacts from ZIP (if present)
            import uuid as _uuid

            import numpy as np

            max_member_bytes = settings.max_file_size_mb * 1024 * 1024  # per-file limit
            max_total_model_bytes = min(max_member_bytes * 5, PROJECT_ARCHIVE_RETAINED_BYTES_MAX)
            max_compression_ratio = 200  # reject members with > 200:1 ratio (zip bomb indicator)
            total_model_bytes_extracted = 0
            total_model_member_bytes = 0

            # Pre-scan: validate all model entries and compute total uncompressed size
            # before extracting anything (fail-fast on budget overflow).
            model_entries: list[tuple[str, dict, int | None, dict[str, Any], dict[str, Any]]] = []
            snapshot_models = _iter_snapshot_models(project_json)
            archived_experiments = _snapshot_experiment_index(project_json) if snapshot_models else {}
            for owner_snapshot, m_data in snapshot_models:
                uid = m_data.get("artifact_uid")
                if not uid:
                    continue
                old_model_project_id = _as_int(owner_snapshot.get("id"))

                # Validate artifact_uid is a proper UUID to prevent path traversal
                try:
                    _uuid.UUID(uid)
                except (ValueError, AttributeError):
                    raise HTTPException(status_code=400, detail="Project model identity is invalid")

                manifest_zip_path = f"models/{uid}/manifest.json"
                arrays_zip_path = f"models/{uid}/arrays.npz"

                if manifest_zip_path not in zip_names or arrays_zip_path not in zip_names:
                    raise HTTPException(status_code=400, detail="Project model member is missing")

                # Per-member size + compression ratio check
                member_sizes = 0
                for member_path in (manifest_zip_path, arrays_zip_path):
                    info = zf.getinfo(member_path)
                    if info.file_size > max_member_bytes:
                        raise HTTPException(status_code=413, detail="Project model member exceeds the file-size limit")
                    # Compression ratio guard: compressed_size of 0 means stored uncompressed
                    if info.compress_size > 0 and info.file_size / info.compress_size > max_compression_ratio:
                        raise HTTPException(status_code=400, detail="Project model member compression ratio is invalid")
                    member_sizes += info.file_size

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
                    manifest = parse_model_manifest_json(manifest_bytes)
                except (ModelManifestJSONError, ValueError) as exc:
                    raise HTTPException(status_code=400, detail="Project model manifest is invalid") from exc
                _bind_archived_model_training_source(
                    manifest,
                    m_data,
                    owner_project_id=old_model_project_id,
                    experiments=archived_experiments,
                )

                declared_array_bytes, declared_inventory = _preflight_model_npz(
                    arrays_bytes,
                    max_decoded_bytes=max_total_model_bytes - total_model_bytes_extracted - len(manifest_bytes),
                )
                _validate_received_model_manifest(
                    manifest,
                    artifact_uid=uid,
                    model_record=m_data,
                    arrays_payload=arrays_bytes,
                    array_inventory=declared_inventory,
                )
                total_model_bytes_extracted += len(manifest_bytes) + declared_array_bytes
                if total_model_bytes_extracted > max_total_model_bytes:
                    raise HTTPException(
                        status_code=413,
                        detail=f"Total model data too large ({total_model_bytes_extracted / (1024*1024):.1f} MB). "
                        f"Maximum is {max_total_model_bytes / (1024*1024):.0f} MB.",
                    )
                try:
                    with np.load(io.BytesIO(arrays_bytes), allow_pickle=False) as npz:
                        arrays = {name: np.asarray(npz[name]) for name in npz.files}
                except Exception as exc:
                    raise HTTPException(status_code=400, detail="Project model array archive is invalid") from exc
                observed_inventory = {
                    name: (tuple(int(value) for value in array.shape), array.dtype.str)
                    for name, array in arrays.items()
                }
                if observed_inventory != declared_inventory or sum(array.nbytes for array in arrays.values()) != (
                    declared_array_bytes
                ):
                    raise HTTPException(status_code=400, detail="Project model array inventory is inconsistent")
                _validate_canonical_model_projection(manifest, arrays, m_data)
                source_version = m_data.get("source_workflow_version")
                if source_version is not None:
                    if (
                        not isinstance(source_version, dict)
                        or type(source_version.get("id")) is not int
                        or source_version["id"] <= 0
                        or type(source_version.get("workflow_id")) is not int
                        or source_version["workflow_id"] != m_data.get("workflow_id")
                        or type(source_version.get("version_number")) is not int
                        or source_version["version_number"] <= 0
                        or not isinstance(source_version.get("snapshot"), dict)
                        or not isinstance(source_version["snapshot"].get("nodes"), list)
                        or not isinstance(source_version["snapshot"].get("edges"), list)
                    ):
                        raise HTTPException(status_code=400, detail="Project model source workflow version is invalid")
                model_entries.append((uid, m_data, old_model_project_id, manifest, arrays))

            # Total budget check across all models
            if total_model_bytes_extracted > max_total_model_bytes:
                raise HTTPException(
                    status_code=413,
                    detail=f"Total model data too large ({total_model_bytes_extracted / (1024*1024):.1f} MB). "
                    f"Maximum is {max_total_model_bytes / (1024*1024):.0f} MB.",
                )

            store = None
            if model_entries:
                try:
                    from spectra_sherpa.app.services.model_store import get_model_store

                    store = get_model_store()
                except RuntimeError as exc:
                    raise HTTPException(status_code=503, detail="Model storage is unavailable") from exc

            # Create root project and descendants from snapshot.
            project_remap: dict[int, int] = {}
            experiment_remap: dict[int, int] = {}
            file_remap: dict[int, int] = {}
            data_source_remap: dict[int, int] = {}
            workflow_remap: dict[int, int] = {}
            project = await _restore_project_tree_from_snapshot(
                project_json,
                parent_project=None,
                admitted_project=project,
                user_id=user_id,
                zf=zf,
                session=session,
                restored_experiment_ids=imported_experiment_ids,
                restored_prepared_sidecars=imported_prepared_sidecars,
                reference_artifacts=reference_artifacts,
                project_remap=project_remap,
                experiment_remap=experiment_remap,
                file_remap=file_remap,
                data_source_remap=data_source_remap,
                workflow_remap=workflow_remap,
            )

            # Restore only explicitly retained model provenance, never infer a
            # training version from the current workflow canvas. Keep the exact
            # historical snapshot; it is evidence, not a promise of data replay.
            model_versions: dict[int, WorkflowVersion] = {}
            for _uid, model_data, _project_id, _manifest, _arrays in model_entries:
                source_version = model_data.get("source_workflow_version")
                if source_version is None:
                    continue
                local_workflow_id = workflow_remap.get(source_version["workflow_id"])
                if local_workflow_id is None:
                    raise HTTPException(status_code=400, detail="Project model source workflow is missing")
                old_version_id = source_version["id"]
                existing = model_versions.get(old_version_id)
                if existing is not None:
                    if (
                        existing.workflow_id != local_workflow_id
                        or existing.version_number != source_version["version_number"]
                        or existing.snapshot
                        != {**source_version["snapshot"], "replay_authority": "external_evidence_only"}
                    ):
                        raise HTTPException(status_code=400, detail="Project model source versions conflict")
                    continue
                version = WorkflowVersion(
                    workflow_id=local_workflow_id,
                    version_number=source_version["version_number"],
                    created_by=user_id,
                    change_description="Imported exact model source version (historical source identities retained)",
                    snapshot={
                        **copy.deepcopy(source_version["snapshot"]),
                        "replay_authority": "external_evidence_only",
                    },
                )
                session.add(version)
                await session.flush()
                model_versions[old_version_id] = version

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
            for uid, m_data, old_model_project_id, manifest, arrays in model_entries:
                assert store is not None
                canonical_origin = manifest.get("artifact_origin") is not None
                target_project_id = project_remap.get(old_model_project_id or -1, project.id)
                imported_training_dataset_id = experiment_remap.get(_as_int(m_data.get("training_dataset_id")) or -1)
                from spectra_sherpa.core.model_artifact import (
                    ModelArtifactIntegrityError,
                    experiment_training_dataset_id,
                    require_experiment_training_dataset_id,
                )

                try:
                    manifest_training_dataset_id = experiment_training_dataset_id(manifest)
                except ModelArtifactIntegrityError as exc:
                    raise HTTPException(
                        status_code=400,
                        detail="Project model training source link is invalid",
                    ) from exc
                has_experiment_training_source = manifest_training_dataset_id is not None
                if has_experiment_training_source:
                    if imported_training_dataset_id is None:
                        raise HTTPException(
                            status_code=400,
                            detail="Project model training source is unavailable",
                        )
                    source_parameters = manifest["preprocessing_chain"][0]["parameters"]
                    # This integer is a workspace-local storage link, not a
                    # scientific identity. Rebind every experiment-trained
                    # model, including ordinary PCA, before publication.
                    if manifest["preprocessing_chain"][0]["op_id"] == "data.file_load":
                        old_file_id = source_parameters["file_id"]
                        if old_file_id not in file_remap:
                            raise HTTPException(400, "Project model training file could not be remapped")
                        source_parameters["experiment_id"] = imported_training_dataset_id
                        source_parameters["file_id"] = file_remap[old_file_id]
                    else:
                        source_parameters["dataset_id"] = imported_training_dataset_id
                    try:
                        require_experiment_training_dataset_id(manifest, imported_training_dataset_id)
                    except ModelArtifactIntegrityError as exc:
                        raise HTTPException(
                            status_code=400,
                            detail="Project model training source link could not be remapped",
                        ) from exc
                if canonical_origin:
                    if imported_training_dataset_id is None:
                        raise HTTPException(
                            status_code=400,
                            detail="Project canonical model training source is unavailable",
                        )
                    from spectra_sherpa.app.services.canonical_model_bridge import (
                        CanonicalModelBridgeError,
                        validate_canonical_plsda_model_artifact,
                    )
                    from spectra_sherpa.app.services.dag.nodes.data.sample_preparation import (
                        attach_target_dataset,
                    )
                    from spectra_sherpa.app.services.model_application import load_project_dataset

                    lineage = manifest.get("canonical_training_lineage") or {}
                    binding = lineage.get("supervision_binding") or {}
                    target_authority = admit_target_authority(
                        binding.get("target_authority") if isinstance(binding, dict) else None,
                        optional=False,
                    )
                    assert target_authority is not None
                    preprocessing_chain = manifest.get("preprocessing_chain") or []
                    source_parameters = (
                        preprocessing_chain[0].get("parameters", {})
                        if isinstance(preprocessing_chain, list)
                        and preprocessing_chain
                        and isinstance(preprocessing_chain[0], dict)
                        else {}
                    )
                    if not isinstance(source_parameters, dict):
                        raise HTTPException(
                            status_code=400,
                            detail="Project canonical model training source is invalid",
                        )
                    training_asset_id = source_parameters.get("asset_id")
                    if not isinstance(training_asset_id, str) or not training_asset_id:
                        raise HTTPException(
                            status_code=400,
                            detail="Project canonical model training asset is invalid",
                        )
                    try:
                        restored_training = await load_project_dataset(
                            session,
                            user_id=user_id,
                            experiment_id=imported_training_dataset_id,
                            stage="raw",
                            asset_id=training_asset_id,
                            strict_prepared_data=True,
                        )
                        if restored_training.project_id != target_project_id:
                            raise CanonicalModelBridgeError(
                                "canonical model training source belongs to a different project"
                            )
                        attached_training = attach_target_dataset(
                            restored_training.dataset,
                            None,
                            target_type=target_authority.target_type,
                            node_id=lineage.get("supervision_attachment_node_id"),
                            target_source="sample_table_column",
                            target_column=target_authority.column,
                            group_column=binding.get("group_column"),
                            target_authority=target_authority,
                        )
                        validate_canonical_plsda_model_artifact(
                            manifest,
                            arrays,
                            training_dataset=attached_training,
                            expected_training_dataset_id=imported_training_dataset_id,
                        )
                    except (CanonicalModelBridgeError, TypeError, ValueError) as exc:
                        raise HTTPException(
                            status_code=400,
                            detail="Project canonical model training lineage is invalid",
                        ) from exc
                target_uid: str | None = None
                integrity_hash: str | None = None
                stored_manifest: dict[str, Any] | None = None
                for attempt in range(9):
                    candidate = uid if attempt == 0 else str(_uuid.uuid4())
                    if candidate in existing_db_uids:
                        continue
                    candidate_manifest = copy.deepcopy(manifest)
                    try:
                        candidate_integrity = store.save_new(candidate, candidate_manifest, arrays)
                    except ModelArtifactCollisionError:
                        continue
                    except Exception as exc:
                        raise HTTPException(
                            status_code=400,
                            detail="Project model artifact could not be imported",
                        ) from exc
                    target_uid = candidate
                    integrity_hash = candidate_integrity
                    stored_manifest = candidate_manifest
                    imported_artifact_uids.append(candidate)
                    break
                if target_uid is None or integrity_hash is None or stored_manifest is None:
                    raise HTTPException(
                        status_code=400, detail="Project model artifact identity could not be allocated"
                    )
                manifest = stored_manifest
                if target_uid != uid:
                    uid_remap[uid] = target_uid
                    logger.info(
                        "Import artifact uid %s collides with an existing artifact — remapped to fresh uid %s",
                        uid,
                        target_uid,
                    )

                imported_n_features = manifest.get("n_features", 0) if canonical_origin else m_data.get("n_features", 0)
                imported_n_components = manifest.get("n_components") if canonical_origin else m_data.get("n_components")
                source_version = m_data.get("source_workflow_version")
                imported_version = model_versions.get(source_version["id"]) if source_version else None
                model_row = ModelArtifact(
                    artifact_uid=target_uid,
                    user_id=user_id,
                    project_id=target_project_id,
                    workflow_id=workflow_remap.get(_as_int(m_data.get("workflow_id")) or -1),
                    workflow_version_id=imported_version.id if imported_version else None,
                    training_dataset_id=imported_training_dataset_id,
                    node_id=m_data.get("node_id", "imported"),
                    model_type=m_data.get("model_type", "unknown"),
                    name=m_data.get("name", f"Imported model {target_uid[:8]}"),
                    display_name=m_data.get("display_name"),
                    description=m_data.get("description"),
                    artifact_dir=str(store._artifact_dir(target_uid)),
                    integrity_hash=integrity_hash,
                    n_features=imported_n_features,
                    n_components=imported_n_components,
                    classes_json=_json_text_or_none(
                        manifest.get("classes") if canonical_origin else m_data.get("classes")
                    ),
                    feature_axis_json=_json_text_or_none(
                        manifest.get("feature_axis") if canonical_origin else m_data.get("feature_axis")
                    ),
                    metrics_json=_json_text_or_none(m_data.get("metrics")),
                    preprocessing_summary=_json_text_or_none(
                        manifest.get("preprocessing_chain")
                        if canonical_origin or has_experiment_training_source
                        else m_data.get("preprocessing_summary")
                    ),
                    training_data_hash=(
                        manifest.get("training_data_hash") if canonical_origin else m_data.get("training_data_hash")
                    ),
                    training_scientific_digest=manifest.get("training_scientific_digest"),
                    artifact_origin=manifest.get("artifact_origin"),
                    canonical_lineage_digest=(manifest.get("canonical_training_lineage") or {}).get("lineage_digest"),
                    validation_evidence_digest=(manifest.get("canonical_training_lineage") or {}).get(
                        "validation_execution_digest"
                    ),
                    tags=list(m_data.get("tags") or []),
                    is_deploy_ready=bool(m_data.get("is_deploy_ready", False)) and imported_version is not None,
                )
                session.add(model_row)
                models_imported += 1

            await _remap_imported_workflow_model_uids(session, workflow_remap, uid_remap)

            # Reconstruct the saved version from the restored durable state.
            # This binds remapped project/experiment/file/model identities and
            # proves the collection definition against the restored bytes;
            # retaining the received snapshot would leave old database ids in
            # the imported version and make versioned re-export non-portable.
            try:
                imported_snapshot = await _build_snapshot(project, session, actor_id=current_user.id)
            except ProjectSnapshotStateError as exc:
                raise HTTPException(status_code=400, detail="Imported project storage is inconsistent") from exc

            # Save import snapshot as version 1
            version = ProjectVersion(
                project_id=project.id,
                version_number=1,
                created_by=user_id,
                change_description=(
                    "Imported from .sherpa object" if is_sherpa_object else "Imported from .spectrapy archive"
                ),
                snapshot=imported_snapshot,
                include_raw_data=is_sherpa_object,
            )
            session.add(version)
            await session.commit()
            committed = True
    except HTTPException:
        await session.rollback()
        _purge_artifacts(imported_artifact_uids)
        _purge_prepared_sidecars(imported_prepared_sidecars)
        for experiment_id in imported_experiment_ids:
            delete_experiment_files(experiment_id)
        raise
    except (zipfile.BadZipFile, SherpaObjectError, KeyError, json.JSONDecodeError) as exc:
        await session.rollback()
        _purge_artifacts(imported_artifact_uids)
        _purge_prepared_sidecars(imported_prepared_sidecars)
        for experiment_id in imported_experiment_ids:
            delete_experiment_files(experiment_id)
        logger.warning("Invalid project archive upload rejected: %s", type(exc).__name__)
        raise HTTPException(
            status_code=400,
            detail={"code": "invalid_project_archive", "message": "Invalid project archive."},
        ) from None
    except Exception:
        await session.rollback()
        _purge_artifacts(imported_artifact_uids)
        _purge_prepared_sidecars(imported_prepared_sidecars)
        for experiment_id in imported_experiment_ids:
            delete_experiment_files(experiment_id)
        raise
    except BaseException:
        await session.rollback()
        _purge_artifacts(imported_artifact_uids)
        _purge_prepared_sidecars(imported_prepared_sidecars)
        for experiment_id in imported_experiment_ids:
            delete_experiment_files(experiment_id)
        raise
    finally:
        await asyncio.gather(*(upload.close() for upload in reference_uploads), return_exceptions=True)
        await asyncio.to_thread(shutil.rmtree, reference_stage_root, True)
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
