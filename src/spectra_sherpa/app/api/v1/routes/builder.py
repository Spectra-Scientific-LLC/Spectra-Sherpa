from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import re
import shutil
import tempfile
import uuid
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any, Literal, Mapping

import numpy as np
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import delete, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from spectra_sherpa.app.api.deps import (
    check_demo_capability,
    consume_reserved_demo_upload_quota_if_needed,
    demo_guard,
    get_current_user,
    get_session,
    release_demo_upload_quota_reservation_if_needed,
    reserve_demo_upload_quota_or_429,
)
from spectra_sherpa.app.api.v1.routes._http_utils import scientific_asset_warnings
from spectra_sherpa.app.contracts.hot_storage import get_hot_storage_checker
from spectra_sherpa.app.contracts.project_access import uses_managed_project_access
from spectra_sherpa.app.contracts.scientific_access import require_scientific_access
from spectra_sherpa.app.core.config import app_config, settings
from spectra_sherpa.app.lib.collection_assembly import (
    MAX_COLLECTION_MEMBERS,
    MAX_COLLECTION_SOURCE_BYTES,
    CollectionMember,
    prepared_data_digest,
    require_collection_budget,
    source_collection_manifest,
)
from spectra_sherpa.app.lib.collection_definition import (
    apply_collection_definition,
    scientific_collection_identity,
    validate_collection_definition,
)
from spectra_sherpa.app.lib.data_formats import ensure_reader_available
from spectra_sherpa.app.lib.dataset_compatibility import unavailable_dataset_analysis_readiness
from spectra_sherpa.app.lib.domain_flags import infer_is_spectra
from spectra_sherpa.app.lib.sample_labels import clean_sample_labels
from spectra_sherpa.app.lib.sherpa_dataset import FeatureAxis, SampleAxis, SherpaDataset, SpectralAxis, TargetContext
from spectra_sherpa.app.models.calibration import Calibration
from spectra_sherpa.app.models.dataset_analysis_binding import DatasetAnalysisBinding
from spectra_sherpa.app.models.experiment import Experiment
from spectra_sherpa.app.models.experiment_file import ExperimentFile
from spectra_sherpa.app.models.user import User
from spectra_sherpa.app.services.builder import BuilderService
from spectra_sherpa.app.services.dataset_analysis_readiness import (
    apply_saved_analysis_binding,
    dataset_analysis_readiness,
    validate_analysis_binding,
)
from spectra_sherpa.app.services.experiments import (
    ALLOWED_STAGES,
    add_experiment_file,
    experiment_dir,
    preferred_experiment_stage,
)
from spectra_sherpa.app.services.file_storage import FileValidationError, sanitize_filename, save_upload_file
from spectra_sherpa.app.services.prepared_data import (
    PreparedDataOverrides,
    apply_dataset_prepared_data_overrides,
    apply_serialized_prepared_data_overrides,
    load_prepared_data_overrides,
    save_prepared_data_overrides,
)
from spectra_sherpa.app.services.scientific_upload_batch import admit_scientific_upload_batch
from spectra_sherpa.core.prepared_data import parser_options_for_prepared_data

logger = logging.getLogger(__name__)


async def _validate_file_path_ownership(
    file_path: str,
    session: AsyncSession,
    current_user: User,
) -> None:
    """
    Validate that a file path is accessible by the current user.

    Checks:
    - If path is in experiments/exp_XXX/, verify experiment ownership
    - If path is in nist_library/, verify it's shared or owned by user
    - Rejects paths outside allowed directories

    Raises HTTPException 403 if access denied.
    """
    # Resolve path relative to data_dir.
    if os.path.isabs(file_path):
        resolved = Path(os.path.abspath(file_path)).resolve(strict=False)
    else:
        resolved = (settings.data_dir / file_path).resolve()

    # Must be within data_dir
    if not resolved.is_relative_to(settings.data_dir):
        raise HTTPException(status_code=403, detail="Access denied: path outside data directory")

    # Get relative path from data_dir
    rel_path = resolved.relative_to(settings.data_dir)
    parts = rel_path.parts

    if not parts:
        raise HTTPException(status_code=403, detail="Access denied: invalid path")

    # Check experiments directory
    if parts[0] == "experiments" and len(parts) >= 2:
        # Extract experiment ID from exp_XXX format
        exp_dir_match = re.match(r"exp_(\d+)", parts[1])
        if exp_dir_match:
            experiment_id = int(exp_dir_match.group(1))
            result = await session.execute(select(Experiment).where(Experiment.id == experiment_id))
            experiment = result.scalar_one_or_none()
            if not experiment or experiment.user_id != current_user.id:
                raise HTTPException(status_code=403, detail="Access denied: experiment not owned by user")
            return  # Access granted

    # Check NIST library directory — NIST spectra are shared public data
    # (no user_id on NistLibrary model), so any authenticated user can read.
    if parts[0] == "nist_library":
        return  # Access granted - NIST data is shared across all users

    # Check calibrations directory (user-specific, pattern: calibrations/cal_XXX/)
    if parts[0] == "calibrations" and len(parts) >= 2:
        # Extract calibration ID from cal_XXX format
        cal_dir_match = re.match(r"cal_(\d+)", parts[1])
        if cal_dir_match:
            calibration_id = int(cal_dir_match.group(1))
            result = await session.execute(select(Calibration).where(Calibration.id == calibration_id))
            calibration = result.scalar_one_or_none()
            if not calibration or calibration.user_id != current_user.id:
                raise HTTPException(status_code=403, detail="Access denied: calibration not owned by user")
            return  # Access granted

        raise HTTPException(status_code=403, detail="Access denied: invalid calibration path")

    # Reject bare calibrations/ access without cal_XXX subdirectory
    if parts[0] == "calibrations":
        raise HTTPException(status_code=403, detail="Access denied: calibration path must specify cal_XXX directory")

    # user/ directory is currently unused by builder endpoints
    # Block access to prevent unintended data exposure
    if parts[0] == "user":
        raise HTTPException(status_code=403, detail="Access denied: user directory not supported for builder")

    # Reject unknown top-level directories
    raise HTTPException(status_code=403, detail="Access denied: unauthorized directory")


# Router with authentication required for all endpoints
router = APIRouter(prefix="/builder", dependencies=[Depends(get_current_user)])
service = BuilderService()


class FileInfoRequest(BaseModel):
    file_path: str | None = None
    experiment_id: int | None = None
    file_ids: list[int] | None = Field(default=None, min_length=1, max_length=MAX_COLLECTION_MEMBERS)
    asset_id: str | None = Field(default=None, min_length=1, max_length=255)


def _validate_file_info_selection(payload: FileInfoRequest) -> None:
    """Refuse ambiguous subset requests before touching dataset custody."""

    if payload.file_path is not None and payload.file_ids is not None:
        raise HTTPException(status_code=400, detail="Provide file_path or file_ids, not both")
    if payload.file_ids is not None and payload.experiment_id is None:
        raise HTTPException(status_code=400, detail="Selected files require experiment_id")
    if payload.file_ids is not None and len(set(payload.file_ids)) != len(payload.file_ids):
        raise HTTPException(status_code=400, detail="Selected files contain duplicate identities")


class DatasetAnalysisBindingRequest(BaseModel):
    source_file_id: int = Field(gt=0)
    sample_table_file_id: int = Field(gt=0)
    expected_revision: str | None
    selected_target: str = Field(min_length=1, max_length=255)
    target_type: Literal["continuous", "categorical"]


def _analysis_binding_revision(binding: DatasetAnalysisBinding | None) -> str | None:
    """Bind concurrency to the complete scientific supervision decision."""

    if binding is None:
        return None
    payload = {
        "source_file_id": binding.source_file_id,
        "sample_table_file_id": binding.sample_table_file_id,
        "selected_target": binding.selected_target,
        "target_type": binding.target_type,
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _analysis_binding_matches(binding: DatasetAnalysisBinding) -> tuple[Any, ...]:
    """Return the exact persisted state used by compare-and-swap writes."""

    return (
        DatasetAnalysisBinding.id == binding.id,
        DatasetAnalysisBinding.source_file_id == binding.source_file_id,
        DatasetAnalysisBinding.sample_table_file_id == binding.sample_table_file_id,
        DatasetAnalysisBinding.selected_target == binding.selected_target,
        DatasetAnalysisBinding.target_type == binding.target_type,
    )


class MetadataOverrideRequest(BaseModel):
    """User-supplied metadata overrides for a dataset on the Explore page."""

    # Identifies the dataset (one of file_path or reference source+name)
    file_path: str | None = None
    experiment_id: int | None = None
    source: str | None = None  # e.g. "oes", "eigenvector"
    name: str | None = None  # e.g. "uvspectra10"

    # Override fields
    x_title: str | None = None
    x_units: str | None = None
    y_title: str | None = None
    is_time_series: bool | None = None
    target_mode: str | None = None
    selected_target: str | None = None
    csv_layout: str | None = None


class DataMatrixRequest(BaseModel):
    project_id: int | None = Field(default=None, gt=0, strict=True)
    kind: Literal["reference", "experiment_file", "staged"]
    source: str | None = None
    name: str | None = None
    experiment_id: int | None = None
    file_id: int | None = None
    staging_id: str | None = None
    asset_id: str | None = Field(default=None, min_length=1, max_length=255)
    row_start: int = Field(default=0, ge=0)
    row_count: int | None = Field(default=None, ge=1)
    col_start: int = Field(default=0, ge=0)
    col_count: int | None = Field(default=None, ge=1)
    overrides: dict[str, Any] | None = None


class StagedUploadCommitItem(BaseModel):
    staging_id: str
    overrides: dict[str, Any] | None = None


class StagedUploadCommitRequest(BaseModel):
    experiment_id: int
    stage: str = "raw"
    files: list[StagedUploadCommitItem] = Field(..., min_length=1)


def _staging_root(current_user: User) -> Path:
    return settings.data_dir / "staged_uploads" / f"user_{current_user.id}"


def _validate_staging_id(staging_id: str) -> str:
    if not re.fullmatch(r"[a-f0-9]{32}", staging_id):
        raise HTTPException(status_code=400, detail="Invalid staging id")
    return staging_id


def _resolve_staged_upload(staging_id: str, current_user: User) -> Path:
    safe_id = _validate_staging_id(staging_id)
    stage_dir = (_staging_root(current_user) / safe_id).resolve()
    root = _staging_root(current_user).resolve()
    if not stage_dir.is_relative_to(root) or not stage_dir.is_dir():
        raise HTTPException(status_code=404, detail="Staged upload not found")
    files = [path for path in stage_dir.iterdir() if path.is_file()]
    if len(files) != 1:
        raise HTTPException(status_code=400, detail="Staged upload is incomplete")
    return files[0]


async def _staged_upload_response(
    staging_id: str,
    saved_path: Path,
    *,
    source_name: str | None = None,
) -> dict[str, Any]:
    csv_import_plan: dict[str, Any] | None = None
    if saved_path.suffix.lower() == ".csv":
        try:
            from spectra_sherpa.app.lib.io import inspect_csv_import_plan

            csv_import_plan = await asyncio.to_thread(inspect_csv_import_plan, saved_path)
        except Exception as exc:
            logger.info("CSV import inspection failed for staged upload %s: %s", staging_id, exc)
            csv_import_plan = {
                "layout": "unknown",
                "layout_label": "CSV",
                "confidence": "low",
                "role_sequence": "",
                "shape": {"rows": None, "columns": None, "samples": None, "features": None},
                "axis": None,
                "target": {"column": None, "type": None, "candidates": []},
                "columns": [],
                "warnings": ["Could not inspect this CSV before preview."],
            }

    suggested_overrides: dict[str, Any] = {}
    if csv_import_plan is not None:
        recommendation = csv_import_plan.get("recommended_layout")
        if isinstance(recommendation, str) and recommendation:
            suggested_overrides["csv_layout"] = recommendation

    from spectra_sherpa.io import ingest

    try:
        ingested = await asyncio.to_thread(
            ingest,
            saved_path,
            parser_options=parser_options_for_prepared_data(saved_path.name, suggested_overrides),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"Could not inspect scientific assets: {exc}") from exc

    return {
        "staging_id": staging_id,
        "filename": saved_path.name,
        "source_name": source_name or saved_path.name,
        "size_bytes": saved_path.stat().st_size,
        "csv_import_plan": csv_import_plan,
        "suggested_overrides": suggested_overrides,
        "format_id": ingested.format_id,
        "variant": ingested.variant,
        "assets": [
            {
                "asset_id": asset.asset_id,
                "title": asset.dataset.title,
                "shape": list(asset.dataset.shape),
                "dimension_roles": list(asset.dimension_roles),
                "data_role": asset.dataset.data_role,
                "x_title": _optional_text(asset.dataset.feature_axis.title),
                "x_units": _optional_text(asset.dataset.feature_axis.units),
                "data_quantity": _optional_text(asset.dataset.domain.data_quantity),
                "value_units": _optional_text(asset.dataset.units),
                "warnings": scientific_asset_warnings(ingested.warnings, asset.warnings),
            }
            for asset in ingested.assets
        ],
    }


def _json_safe_number(value: Any) -> float | int | str | None:
    if value is None:
        return None
    try:
        if isinstance(value, np.generic):
            value = value.item()
        if isinstance(value, (int, np.integer)):
            return int(value)
        numeric = float(value)
        return numeric if np.isfinite(numeric) else None
    except (TypeError, ValueError):
        return str(value)


def _json_safe_matrix(values: np.ndarray) -> list[list[float | int | str | None]]:
    if values.size == 0:
        return []
    if np.issubdtype(values.dtype, np.number):
        return np.where(np.isfinite(values), values, None).tolist()
    return [[_json_safe_number(cell) for cell in row] for row in values.tolist()]


def _optional_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _catalog_source_files(entry: dict[str, Any]) -> list[str]:
    """Return source filenames already declared by catalog metadata.

    This intentionally does not inspect archives or parse payloads. It only
    surfaces the original bundled filenames the loader metadata already knows.
    """
    files: list[str] = []
    seen: set[str] = set()
    for key in ("filename", "file", "spec_file", "prop_file", "mat_file"):
        raw = entry.get(key)
        values = raw if isinstance(raw, list) else [raw]
        for value in values:
            if not isinstance(value, str) or not value.strip():
                continue
            normalized = value.strip()
            if normalized in seen:
                continue
            seen.add(normalized)
            files.append(normalized)
    return files


def _axis_labels(axis: Any, count: int, *, values_as_labels: bool) -> list[str]:
    if axis is not None:
        labels = getattr(axis, "labels", None)
        if labels:
            return [str(label) for label in list(labels)[:count]]
        if values_as_labels:
            values = getattr(axis, "values", None)
            if values is not None:
                try:
                    return [f"{float(value):.6g}" for value in list(values)[:count]]
                except (TypeError, ValueError):
                    return [str(value) for value in list(values)[:count]]
    return [str(index + 1) for index in range(count)]


def _column_stats(X: np.ndarray, labels: list[str]) -> list[dict[str, Any]]:
    stats: list[dict[str, Any]] = []
    for index in range(X.shape[1]):
        column = X[:, index]
        finite = column[np.isfinite(column)]
        missing = int(column.size - finite.size)
        stats.append(
            {
                "label": labels[index] if index < len(labels) else str(index + 1),
                "count": int(finite.size),
                "missing": missing,
                "missing_pct": float((100 * missing / column.size) if column.size else 0.0),
                "min": float(np.min(finite)) if finite.size else None,
                "max": float(np.max(finite)) if finite.size else None,
                "mean": float(np.mean(finite)) if finite.size else None,
                "std": float(np.std(finite)) if finite.size else None,
            }
        )
    return stats


def _is_missing_target_value(value: Any) -> bool:
    if value is None:
        return True
    try:
        return not bool(np.isfinite(value))
    except (TypeError, ValueError):
        return False


def _target_label(value: Any, class_names: list[str]) -> str:
    try:
        index = int(value)
    except (TypeError, ValueError):
        return str(value)
    if 0 <= index < len(class_names):
        return class_names[index]
    return str(value)


def _target_summary(dataset: SherpaDataset) -> dict[str, Any] | None:
    target = getattr(dataset, "target", None)
    if target is None:
        return None

    values = np.asarray(target)
    if values.size == 0:
        return None

    context = dataset.target_context
    target_type = context.target_type or "auto"
    target_name = context.target_name or (context.target_names[0] if context.target_names else "Label")
    class_names = [str(item) for item in (context.class_names or [])]
    flat = values.reshape(-1)
    valid = np.asarray([item for item in flat.tolist() if not _is_missing_target_value(item)], dtype=object)
    missing = int(flat.size - valid.size)

    summary: dict[str, Any] = {
        "has_target": True,
        "target_type": target_type,
        "target_name": target_name,
        "target_names": context.target_names,
        "target_units": context.target_units,
        "n_targets": int(values.shape[1]) if values.ndim > 1 else 1,
        "count": int(valid.size),
        "missing": missing,
        "missing_pct": float((100 * missing / flat.size) if flat.size else 0.0),
        "class_names": class_names or None,
    }

    if target_type == "categorical" or class_names:
        unique, counts = np.unique(valid, return_counts=True)
        classes = []
        for value, count in zip(unique.tolist(), counts.tolist(), strict=False):
            classes.append(
                {
                    "value": _json_safe_number(value),
                    "label": _target_label(value, class_names),
                    "count": int(count),
                    "pct": float((100 * int(count) / valid.size) if valid.size else 0.0),
                }
            )
        summary["n_classes"] = int(context.n_classes or len(classes))
        summary["classes"] = classes
    else:
        try:
            numeric = valid.astype(np.float64)
        except (TypeError, ValueError):
            numeric = np.asarray([], dtype=np.float64)
        finite = numeric[np.isfinite(numeric)]
        if finite.size:
            summary["min"] = float(np.min(finite))
            summary["max"] = float(np.max(finite))
            summary["mean"] = float(np.mean(finite))
            summary["std"] = float(np.std(finite))

    return summary


def _matrix_response(dataset: SherpaDataset, payload: DataMatrixRequest) -> dict[str, Any]:
    prepared = PreparedDataOverrides.from_mapping(payload.overrides)
    if not prepared.is_empty():
        dataset = apply_dataset_prepared_data_overrides(dataset, prepared)

    X = np.asarray(dataset.X, dtype=np.float64)
    if X.ndim == 1:
        X = X.reshape(1, -1)
    if X.ndim > 2:
        return _nd_dataset_response(dataset, X)
    if X.ndim != 2:
        raise HTTPException(status_code=400, detail=f"Matrix preview cannot display shape {list(X.shape)}")

    total_rows, total_cols = int(X.shape[0]), int(X.shape[1])
    feature_axis = dataset.get_feature_axis()
    sample_axis = dataset.get_observation_axis()
    all_col_labels = _axis_labels(feature_axis, total_cols, values_as_labels=dataset.data_role == "X_spectra")
    all_row_labels = clean_sample_labels(
        _axis_labels(sample_axis, total_rows, values_as_labels=False),
        total_rows,
        fallback_prefix="Sample",
    )

    max_cells = 200_000
    col_start = min(payload.col_start, total_cols)
    requested_cols = payload.col_count if payload.col_count is not None else min(total_cols - col_start, 2_000)
    cols_shown = max(0, min(int(requested_cols), total_cols - col_start, 2_000))
    row_start = min(payload.row_start, total_rows)
    default_rows = max_cells // max(cols_shown, 1)
    requested_rows = payload.row_count if payload.row_count is not None else default_rows
    rows_shown = max(0, min(int(requested_rows), total_rows - row_start, default_rows))
    window = X[row_start : row_start + rows_shown, col_start : col_start + cols_shown]
    finite = X[np.isfinite(X)]
    missing_total = int(X.size - finite.size)

    x_title = _optional_text(getattr(feature_axis, "title", None)) if feature_axis is not None else None
    x_units = _optional_text(getattr(feature_axis, "units", None)) if feature_axis is not None else None
    x_quantity_value = getattr(feature_axis, "quantity", None) if feature_axis is not None else None
    x_quantity = _optional_text(getattr(x_quantity_value, "value", x_quantity_value))
    if feature_axis is None and total_cols:
        x_title = "Index"
    y_title = _optional_text(dataset.meta.get("data_quantity")) if isinstance(dataset.meta, dict) else None
    y_title = y_title or _optional_text(dataset.domain.data_quantity)

    return {
        "shape": [total_rows, total_cols],
        "shape_label": "samples x features",
        "x_title": x_title,
        "x_units": x_units,
        "x_quantity": x_quantity,
        "y_title": y_title,
        "data_role": dataset.data_role,
        "data_modality": dataset.data_modality,
        "is_spectra": dataset.data_role == "X_spectra",
        "row_start": row_start,
        "col_start": col_start,
        "rows_shown": rows_shown,
        "cols_shown": cols_shown,
        "total_rows": total_rows,
        "total_cols": total_cols,
        "truncated": rows_shown < total_rows or cols_shown < total_cols or row_start > 0 or col_start > 0,
        "row_labels": all_row_labels[row_start : row_start + rows_shown],
        "col_labels": all_col_labels[col_start : col_start + cols_shown],
        "matrix": _json_safe_matrix(window),
        "stats": {
            "per_column": _column_stats(X, all_col_labels),
            "summary": {
                "n_samples": total_rows,
                "n_features": total_cols,
                "global_min": float(np.min(finite)) if finite.size else None,
                "global_max": float(np.max(finite)) if finite.size else None,
                "global_mean": float(np.mean(finite)) if finite.size else None,
                "total_missing_pct": float((100 * missing_total / X.size) if X.size else 0.0),
            },
        },
        "target": _target_summary(dataset),
    }


def _nd_dataset_response(dataset: SherpaDataset, values: np.ndarray) -> dict[str, Any]:
    """Return a bounded, shape-preserving n-D Workbench preview."""

    from spectra_sherpa.app.services.dag.serialize import serialize_for_api

    shape = [int(value) for value in values.shape]
    finite_mask = np.isfinite(values)
    finite_count = int(np.count_nonzero(finite_mask))
    missing_total = int(values.size - finite_count)
    if finite_count:
        global_min = float(np.min(values, where=finite_mask, initial=np.inf))
        global_max = float(np.max(values, where=finite_mask, initial=-np.inf))
        global_mean = float(np.sum(values, where=finite_mask, dtype=np.float64) / finite_count)
    else:
        global_min = global_max = global_mean = None
    feature_axis = dataset.get_feature_axis()
    roles = list(dataset.layout.mode_roles)
    if len(roles) != values.ndim:
        roles = ["sample", *(f"mode-{dimension + 1}" for dimension in range(1, values.ndim - 1)), "feature"]
    preview = serialize_for_api(dataset)
    return {
        "kind": "nd_dataset",
        "shape": shape,
        "rank": int(values.ndim),
        "shape_label": " × ".join(str(value) for value in shape),
        "dimension_roles": roles,
        "projection_required": True,
        "projection_message": (
            "This dataset remains n-dimensional. Select explicit inner-dimension indices with "
            "Dimension Projection before using a two-dimensional matrix operation."
        ),
        "dataset_preview": preview,
        "x_title": _optional_text(getattr(feature_axis, "title", None)),
        "x_units": _optional_text(getattr(feature_axis, "units", None)),
        "x_quantity": _optional_text(
            getattr(
                getattr(feature_axis, "quantity", None),
                "value",
                getattr(feature_axis, "quantity", None),
            )
        ),
        "y_title": _optional_text(dataset.domain.data_quantity),
        "data_role": dataset.data_role,
        "data_modality": dataset.data_modality,
        "is_spectra": dataset.data_role == "X_spectra",
        "row_start": 0,
        "col_start": 0,
        "rows_shown": 0,
        "cols_shown": 0,
        "total_rows": shape[0],
        "total_cols": shape[-1],
        "truncated": True,
        "row_labels": [],
        "col_labels": [],
        "matrix": [],
        "stats": {
            "per_column": [],
            "summary": {
                "n_samples": shape[0],
                "n_features": shape[-1],
                "global_min": global_min,
                "global_max": global_max,
                "global_mean": global_mean,
                "total_missing_pct": float((100 * missing_total / values.size) if values.size else 0.0),
            },
        },
        "target": _target_summary(dataset),
    }


def _reference_dataset_as_sherpa(source: str, name: str) -> SherpaDataset:
    if source == "builtin":
        return _builtin_reference_dataset_as_sherpa(name)
    if source == "synthetic":
        from spectra_sherpa.app.lib.synthetic_references import load_synthetic_reference_as_sherpa

        try:
            return load_synthetic_reference_as_sherpa(name)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=f"Dataset '{name}' not found") from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    if source == "eigenvector":
        from spectra_sherpa.app.lib.eigenvector import DATASET_CATALOG
        from spectra_sherpa.app.services.eigenvector_datasets import load_eigenvector_dataset

        if name not in DATASET_CATALOG:
            raise HTTPException(status_code=404, detail=f"Dataset '{name}' not found")
        result = load_eigenvector_dataset(name)
        catalog = result["catalog_entry"]
        governed_dataset = result.get("dataset")
        if isinstance(governed_dataset, SherpaDataset):
            dataset = governed_dataset.copy()
            dataset.title = catalog.get("label") or name
            return dataset
        has_wavelengths = result.get("wavelengths") is not None
        return SherpaDataset(
            X=np.asarray(result["spectra"], dtype=np.float64),
            feature_axis=SpectralAxis(
                values=(
                    np.asarray(result["wavelengths"], dtype=np.float64)
                    if has_wavelengths
                    else np.arange(result["spectra"].shape[1], dtype=np.float64)
                ),
                title=catalog.get("x_title") or (None if has_wavelengths else "Index"),
                units=catalog.get("x_units"),
            ),
            sample_axis=SampleAxis(
                labels=clean_sample_labels(
                    result.get("sample_ids"), result["spectra"].shape[0], fallback_prefix="Sample"
                ),
                title="Sample",
            ),
            title=catalog.get("label") or name,
            data_role="X_spectra",
        )
    if source == "oes":
        from spectra_sherpa.app.lib.oes_datasets import OES_CATALOG, load_oes_dataset

        if name not in OES_CATALOG:
            raise HTTPException(status_code=404, detail=f"Dataset '{name}' not found")
        result = load_oes_dataset(name)
        catalog = result["catalog_entry"]
        return SherpaDataset(
            X=np.asarray(result["spectra"], dtype=np.float64),
            feature_axis=SpectralAxis(
                values=np.asarray(result["wavelengths"], dtype=np.float64),
                title=catalog.get("x_title") or "Wavelength",
                units=catalog.get("x_units"),
            ),
            sample_axis=SampleAxis(
                labels=clean_sample_labels(
                    result.get("sample_ids"), result["spectra"].shape[0], fallback_prefix="Sample"
                ),
                title="Sample",
            ),
            title=catalog.get("label") or name,
            data_role="X_spectra",
        )
    if source == "sklearn":
        from sklearn import datasets as sk_datasets

        from spectra_sherpa.app.lib.sklearn_info import _LOADERS, SKLEARN_CATALOG

        if name not in SKLEARN_CATALOG:
            raise HTTPException(status_code=404, detail=f"Dataset '{name}' not found")
        bunch = getattr(sk_datasets, _LOADERS[name])()
        target_names = [str(item) for item in getattr(bunch, "target_names", [])]
        target = np.asarray(bunch.target)
        return SherpaDataset(
            X=np.asarray(bunch.data, dtype=np.float64),
            feature_axis=FeatureAxis(
                labels=[str(item) for item in getattr(bunch, "feature_names", [])],
                title="Feature",
            ),
            sample_axis=SampleAxis(
                labels=clean_sample_labels(None, bunch.data.shape[0], fallback_prefix="Sample"),
                title="Sample",
            ),
            target=target,
            target_context=TargetContext(
                target_type="categorical",
                target_name="Label",
                n_classes=len(target_names) if target_names else int(len(np.unique(target))),
                class_names=target_names or None,
            ),
            title=SKLEARN_CATALOG[name]["label"],
            data_role="X_features",
        )
    raise HTTPException(status_code=400, detail=f"Unknown source: {source}")


def _builtin_reference_dataset_as_sherpa(name: str) -> SherpaDataset:
    from spectra_sherpa.app.services.experiments import (
        _BUILTIN_LAVENDER_ARCHIVE_ENV,
        _BUILTIN_LAVENDER_DATASET_ID,
        _BUILTIN_LAVENDER_MANIFEST_SCHEMA,
        _BUILTIN_LAVENDER_NAME,
        _BUILTIN_LAVENDER_PACKAGE_ROOT,
        _BUILTIN_LAVENDER_SOURCE_AGGREGATE_BYTES_MAX,
        _BUILTIN_LAVENDER_SOURCE_FILE_BYTES_MAX,
        _builtin_lavender_archive_path,
        _normalized_lavender_member,
        _read_lavender_json,
        _sha256,
    )

    if name != _BUILTIN_LAVENDER_NAME:
        raise HTTPException(status_code=404, detail=f"Dataset '{name}' not found")

    archive_path = _builtin_lavender_archive_path()
    if not archive_path.exists():
        raise HTTPException(
            status_code=404,
            detail=(
                "Lavender Essential Oil FTIR Corpus v1 is not mounted on this server. "
                f"Set {_BUILTIN_LAVENDER_ARCHIVE_ENV} to the operator-installed archive."
            ),
        )

    try:
        with zipfile.ZipFile(archive_path) as archive, tempfile.TemporaryDirectory() as temp_dir:
            members = [_normalized_lavender_member(info) for info in archive.infolist()]
            if len(members) != len(set(members)):
                raise ValueError("Lavender reference archive contains duplicate members")

            manifest = _read_lavender_json(archive, "manifest.json")
            if manifest.get("schema_version") != _BUILTIN_LAVENDER_MANIFEST_SCHEMA:
                raise ValueError("Lavender reference archive manifest has an unsupported schema")
            if manifest.get("dataset_id") != _BUILTIN_LAVENDER_DATASET_ID:
                raise ValueError("Lavender reference archive has the wrong dataset identity")
            counts = manifest.get("counts")
            if not isinstance(counts, dict) or counts.get("files") != 33:
                raise ValueError("Lavender reference archive does not contain the qualified 33-file corpus")

            file_rows = manifest.get("files")
            if not isinstance(file_rows, list) or len(file_rows) != 33:
                raise ValueError("Lavender reference archive manifest file census is invalid")

            definition = validate_collection_definition(_read_lavender_json(archive, "collection-definition.json"))
            definition_file_names = {
                str(row.get("file_name")) for row in definition.payload.get("rows", []) if isinstance(row, dict)
            }
            raw_dir = Path(temp_dir) / "raw"
            raw_dir.mkdir()
            loaded: list[CollectionMember] = []
            total_size = 0
            seen_targets: set[str] = set()

            for row in file_rows:
                if not isinstance(row, dict):
                    raise ValueError("Lavender reference archive manifest file row is invalid")
                relative_path = row.get("path")
                expected_size = row.get("size_bytes")
                expected_sha256 = row.get("sha256")
                if not isinstance(relative_path, str) or not relative_path.startswith("data/"):
                    raise ValueError("Lavender reference archive manifest has an invalid source path")
                if not isinstance(expected_size, int) or expected_size < 0:
                    raise ValueError("Lavender reference archive manifest has an invalid source size")
                if not isinstance(expected_sha256, str) or len(expected_sha256) != 64:
                    raise ValueError("Lavender reference archive manifest has an invalid source digest")

                source_path = PurePosixPath(relative_path)
                if source_path.is_absolute() or ".." in source_path.parts or len(source_path.parts) != 2:
                    raise ValueError("Lavender reference archive manifest source path is unsafe")
                source_name = source_path.name
                if source_name in seen_targets:
                    raise ValueError("Lavender reference archive contains duplicate source file names")
                seen_targets.add(source_name)
                target_rel = f"raw/{source_name}"
                if target_rel not in definition_file_names:
                    raise ValueError("Lavender reference archive definition is not bound to its source files")

                try:
                    source_info = archive.getinfo(f"{_BUILTIN_LAVENDER_PACKAGE_ROOT}/{relative_path}")
                except KeyError as exc:
                    raise ValueError("Lavender reference archive manifest names a missing source file") from exc
                if source_info.file_size != expected_size:
                    raise ValueError("Lavender reference archive source size does not match its manifest")
                if source_info.file_size > _BUILTIN_LAVENDER_SOURCE_FILE_BYTES_MAX:
                    raise ValueError("Lavender reference archive source file exceeds its byte ceiling")
                total_size += source_info.file_size
                if total_size > _BUILTIN_LAVENDER_SOURCE_AGGREGATE_BYTES_MAX:
                    raise ValueError("Lavender reference archive exceeds its aggregate byte ceiling")

                content = archive.read(source_info)
                if len(content) != expected_size or _sha256(content) != expected_sha256:
                    raise ValueError("Lavender reference archive source bytes do not match their manifest")

                target_path = raw_dir / source_name
                target_path.write_bytes(content)
                loaded.append(
                    _file_as_collection_member(
                        target_path,
                        file_name=target_rel,
                        asset_id=None,
                        prepared_overrides=None,
                    )
                )

            require_collection_budget(loaded)
            return apply_collection_definition(loaded, definition)
    except zipfile.BadZipFile as exc:
        raise HTTPException(status_code=400, detail="Lavender reference archive is not a valid ZIP file") from exc
    except (FileNotFoundError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


async def _experiment_file_as_sherpa(
    experiment_id: int,
    file_id: int,
    session: AsyncSession,
    current_user: User,
    asset_id: str | None = None,
) -> SherpaDataset:
    if uses_managed_project_access():
        from spectra_sherpa.app.services.model_application import load_project_dataset

        record = await session.get(ExperimentFile, file_id)
        if record is None or record.experiment_id != experiment_id:
            raise HTTPException(404, "Experiment file not found")
        loaded = await load_project_dataset(
            session,
            user_id=current_user.id,
            experiment_id=experiment_id,
            stage=record.stage,
            file_ids=[file_id],
            asset_id=asset_id,
        )
        return loaded.dataset
    result = await session.execute(
        select(ExperimentFile)
        .join(Experiment, Experiment.id == ExperimentFile.experiment_id)
        .where(
            ExperimentFile.id == file_id,
            ExperimentFile.experiment_id == experiment_id,
            Experiment.user_id == current_user.id,
        )
    )
    file_record = result.scalar_one_or_none()
    if file_record is None:
        raise HTTPException(status_code=404, detail="Experiment file not found")
    path = experiment_dir(experiment_id) / file_record.file_path
    prepared = load_prepared_data_overrides(file_path=str(path))
    return _file_as_sherpa(path, asset_id=asset_id, prepared_overrides=prepared.to_sidecar_dict())


async def _experiment_contents_as_sherpa(
    experiment_id: int,
    session: AsyncSession,
    current_user: User,
    *,
    asset_id: str | None = None,
) -> tuple[SherpaDataset, list[ExperimentFile], str, str, dict[str, Any]]:
    result = await session.execute(
        select(Experiment).where(
            Experiment.id == experiment_id,
            Experiment.user_id == current_user.id,
        )
    )
    experiment = result.scalar_one_or_none()
    if experiment is None:
        raise HTTPException(status_code=404, detail="Experiment not found")

    files: list[ExperimentFile] = []
    stage = "raw"
    for candidate_stage in ("raw", "synthetic"):
        files_result = await session.execute(
            select(ExperimentFile)
            .where(
                ExperimentFile.experiment_id == experiment_id,
                ExperimentFile.stage == candidate_stage,
            )
            .order_by(ExperimentFile.id.asc())
        )
        files = list(files_result.scalars().all())
        if files:
            stage = candidate_stage
            break
    if not files:
        raise HTTPException(status_code=404, detail="No raw or synthetic files found in dataset")
    if len(files) > MAX_COLLECTION_MEMBERS:
        raise ValueError(f"scientific collection exceeds the {MAX_COLLECTION_MEMBERS}-member limit")
    if sum(int(file.file_size_bytes or 0) for file in files) > MAX_COLLECTION_SOURCE_BYTES:
        raise ValueError("scientific collection exceeds the 512 MiB source limit")

    by_name = {Path(file.file_path).name.casefold(): file for file in files}
    if set(by_name) == {"diesel_spec.csv", "diesel_prop.csv"}:
        from spectra_sherpa.app.lib.eigenvector import load_eigenvector_csv_pair_as_sherpa

        spec_file = by_name["diesel_spec.csv"]
        prop_file = by_name["diesel_prop.csv"]
        spec_path = experiment_dir(experiment_id) / spec_file.file_path
        prop_path = experiment_dir(experiment_id) / prop_file.file_path
        combined = await asyncio.to_thread(load_eigenvector_csv_pair_as_sherpa, spec_path, prop_path)
        entries = []
        for file, path in ((spec_file, spec_path), (prop_file, prop_path)):
            entries.append(
                {
                    "file_name": file.file_path,
                    "size_bytes": path.stat().st_size,
                    "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                    "prepared_data_sha256": prepared_data_digest(None),
                }
            )
        source_manifest = source_collection_manifest(entries)
        combined.meta["source_collection"] = source_manifest
        identity = scientific_collection_identity(source_manifest, None, combined)
        source_manifest.update(identity)
        return combined, files, experiment.name, stage, source_manifest

    # Inspection and workflow admission must assemble the same scientific
    # collection, including registered annotation authority and projection extras.
    from spectra_sherpa.app.services.model_application import load_project_dataset

    loaded = await load_project_dataset(
        session,
        user_id=current_user.id,
        experiment_id=experiment_id,
        stage=stage,
        asset_id=asset_id,
    )
    combined = loaded.dataset
    source_manifest = combined.meta["source_collection"]
    return combined, files, experiment.name, loaded.stage, source_manifest


def _registered_reference_projection(
    path: Path,
    *,
    asset_id: str | None,
) -> tuple[SherpaDataset, str, Mapping[str, Any]] | None:
    """Use the registered projection rather than an arbitrary MAT variable."""

    from spectra_sherpa.app.lib.reference_materialization import materialize_reference_member
    from spectra_sherpa.app.lib.registered_reference_storage import read_registered_reference_sidecar

    reference = read_registered_reference_sidecar(path)
    if reference is None:
        return None
    projection_id = str(reference["projection_id"])
    if asset_id is not None and asset_id != projection_id:
        raise ValueError("requested asset differs from the registered reference projection")
    materialized = materialize_reference_member(path, projection_id)
    if dict(materialized.portable_reference) != dict(reference):
        raise ValueError("registered reference identity changed during file preview")
    return materialized.dataset, projection_id, reference


def _file_as_sherpa(
    path: Path,
    *,
    asset_id: str | None = None,
    prepared_overrides: Mapping[str, Any] | None = None,
) -> SherpaDataset:
    from spectra_sherpa.io import ingest, select_asset

    suffix = path.suffix.lower()
    ensure_reader_available(suffix)
    registered = _registered_reference_projection(path, asset_id=asset_id)
    if registered is not None:
        return apply_dataset_prepared_data_overrides(registered[0], prepared_overrides or {})
    result = ingest(path, parser_options=parser_options_for_prepared_data(path.name, prepared_overrides))
    dataset = select_asset(result, asset_id=asset_id).dataset
    return apply_dataset_prepared_data_overrides(dataset, prepared_overrides or {})


def _file_as_collection_member(
    path: Path,
    *,
    file_name: str,
    asset_id: str | None,
    prepared_overrides: Mapping[str, Any] | None,
) -> CollectionMember:
    """Admit one member once and retain that immutable snapshot identity."""

    from spectra_sherpa.io import ingest, select_asset

    ensure_reader_available(path.suffix.lower())
    registered = _registered_reference_projection(path, asset_id=asset_id)
    if registered is not None:
        dataset, projection_id, reference = registered
        return CollectionMember(
            dataset=apply_dataset_prepared_data_overrides(dataset, prepared_overrides or {}),
            file_name=file_name,
            size_bytes=int(reference["member_size_bytes"]),
            sha256=str(reference["member_sha256"]),
            prepared_data_sha256=prepared_data_digest(prepared_overrides),
            asset_id=projection_id,
        )
    result = ingest(path, parser_options=parser_options_for_prepared_data(path.name, prepared_overrides))
    if len(result.source_members) != 1:
        raise ValueError(f"Collection member {file_name!r} must consume exactly one source")
    selected_asset = select_asset(result, asset_id=asset_id)
    dataset = selected_asset.dataset
    dataset = apply_dataset_prepared_data_overrides(dataset, prepared_overrides or {})
    source = result.source_members[0]
    return CollectionMember(
        dataset=dataset,
        file_name=file_name,
        size_bytes=source.size_bytes,
        sha256=source.sha256,
        prepared_data_sha256=prepared_data_digest(prepared_overrides),
        asset_id=selected_asset.asset_id,
    )


def _project_single_member_metadata(metadata: dict[str, Any], *, contents_file_count: int) -> None:
    """Preserve the established one-file inspection projection without ambiguity."""

    member_metadata = metadata.get("source_member_metadata")
    if contents_file_count != 1 or not isinstance(member_metadata, list) or len(member_metadata) != 1:
        return
    scoped_metadata = member_metadata[0].get("metadata")
    if isinstance(scoped_metadata, dict):
        for key, value in scoped_metadata.items():
            metadata.setdefault(key, value)


def _unique_destination_path(destination_dir: Path, filename: str) -> Path:
    candidate = (destination_dir / filename).resolve()
    stem = candidate.stem
    suffix = candidate.suffix
    counter = 2
    while candidate.exists():
        candidate = (destination_dir / f"{stem}_{counter}{suffix}").resolve()
        counter += 1
    return candidate


@router.post("/data-matrix")
async def get_data_matrix(
    payload: DataMatrixRequest,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Return a source-side matrix window plus full-column statistics.

    The returned shape is always the internal SherpaDataset contract:
    samples x features. For scientist CSVs with one shared x-axis column,
    that means condition columns become samples and the first column becomes
    the feature axis.
    """
    qualified_project_id = None
    local_catalog_preview = uses_managed_project_access() and payload.kind == "reference"
    if local_catalog_preview:
        from spectra_sherpa.app.api.v1.routes.experiments import _is_demo_server_reference_dataset

        if not _is_demo_server_reference_dataset(payload.source, payload.name):
            raise HTTPException(403, "Provider preview is unavailable; import an exact registered file first")
        qualified_project_id = payload.project_id
        await require_scientific_access(session, current_user.id, qualified_project_id, "read")
    if uses_managed_project_access() and not local_catalog_preview:
        if payload.kind == "staged" and payload.staging_id:
            staged = _resolve_staged_upload(payload.staging_id, current_user)
            try:
                qualified_project_id = json.loads(
                    (staged.parent.parent / f"{payload.staging_id}.scope.json").read_text()
                )["project_id"]
            except (OSError, ValueError, KeyError):
                raise HTTPException(409, "Staged upload must be admitted again") from None
        elif payload.kind == "experiment_file" and payload.experiment_id and payload.file_id:
            experiment = await session.get(Experiment, payload.experiment_id)
            qualified_project_id = experiment.project_id if experiment else None
        else:
            raise HTTPException(403, "Only project uploads have been qualified for matrix preview")
        await require_scientific_access(session, current_user.id, qualified_project_id, "read")
    try:
        if payload.kind == "reference":
            if not payload.source or not payload.name:
                raise HTTPException(status_code=400, detail="source and name are required")
            dataset = await asyncio.to_thread(
                _reference_dataset_as_sherpa,
                payload.source,
                payload.name,
            )
        elif payload.kind == "experiment_file":
            if payload.experiment_id is None or payload.file_id is None:
                raise HTTPException(status_code=400, detail="experiment_id and file_id are required")
            if app_config.site_profile == "demo":
                experiment = await session.scalar(
                    select(Experiment).where(
                        Experiment.id == payload.experiment_id,
                        Experiment.user_id == current_user.id,
                    )
                )
                if experiment is None:
                    raise HTTPException(status_code=404, detail="Experiment not found")
                file_record = await session.scalar(
                    select(ExperimentFile).where(
                        ExperimentFile.id == payload.file_id,
                        ExperimentFile.experiment_id == payload.experiment_id,
                    )
                )
                if file_record is None:
                    raise HTTPException(status_code=404, detail="Experiment file not found")
                from spectra_sherpa.app.contracts.demo_policy import require_trial_dataset_access

                admission = await require_trial_dataset_access(
                    session=session,
                    user_id=current_user.id,
                    workflow_project_id=experiment.project_id,
                    experiment_id=payload.experiment_id,
                    stage=file_record.stage,
                    file_id=payload.file_id,
                    asset_id=payload.asset_id,
                )
                loaded = admission.loaded_dataset
                dataset = loaded.dataset
            else:
                dataset = await _experiment_file_as_sherpa(
                    payload.experiment_id,
                    payload.file_id,
                    session,
                    current_user,
                    asset_id=payload.asset_id,
                )
        elif payload.kind == "staged":
            check_demo_capability("data_upload")
            if not payload.staging_id:
                raise HTTPException(status_code=400, detail="staging_id is required")
            dataset = await asyncio.to_thread(
                _file_as_sherpa,
                _resolve_staged_upload(payload.staging_id, current_user),
                asset_id=payload.asset_id,
                prepared_overrides=payload.overrides,
            )
        else:
            raise HTTPException(status_code=400, detail="Unsupported matrix source")
        result = _matrix_response(dataset, payload)
        if uses_managed_project_access():
            await require_scientific_access(session, current_user.id, qualified_project_id, "read")
        return result
    except HTTPException:
        raise
    except ValueError as exc:
        logger.info("Matrix preview rejected invalid input: %s", type(exc).__name__)
        raise HTTPException(status_code=400, detail="Matrix preview could not parse the selected data.") from None
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Selected data file was not found.") from None


async def _admit_qualified_staging(session, user, project_id, files):
    if not uses_managed_project_access():
        return
    await require_scientific_access(session, user.id, project_id, "write")
    if any(file.size is None for file in files):
        raise HTTPException(400, "Uploaded source size is required")
    incoming = sum(file.size for file in files)
    root = _staging_root(user)
    pending = (
        sum(
            path.stat().st_size
            for folder in root.glob("*")
            if folder.is_dir()
            for path in folder.iterdir()
            if path.is_file()
        )
        if root.exists()
        else 0
    )
    if pending + incoming > MAX_COLLECTION_SOURCE_BYTES:
        raise HTTPException(413, "Remove pending uploads before staging more data")
    checker = get_hot_storage_checker()
    if checker is None:
        raise HTTPException(503, "Storage accounting is unavailable")
    await checker(session, user_id=user.id, project_id=project_id, incoming_bytes=incoming)


def _bind_qualified_staging(user, staging_id, project_id):
    if uses_managed_project_access():
        (_staging_root(user) / f"{staging_id}.scope.json").write_text(json.dumps({"project_id": project_id}))


@router.post("/upload/stage", dependencies=[Depends(demo_guard("data_upload"))])
async def stage_upload_file(
    file: UploadFile = File(...),
    project_id: int | None = Form(None),
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Stage a local file for source-side preview before committing it to My Dataset."""
    await _admit_qualified_staging(session, current_user, project_id, [file])
    user_id = current_user.id
    try:
        ensure_reader_available(file.filename or "")
    except (ImportError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    upload_reserved = reserve_demo_upload_quota_or_429(user_id)
    staging_id = uuid.uuid4().hex
    destination_dir = _staging_root(current_user) / staging_id
    saved_path: Path | None = None
    scientifically_admitted = False
    try:
        saved_path = await save_upload_file(
            file,
            destination_dir=destination_dir,
            max_file_size_mb=settings.max_file_size_mb,
        )
        response = await _staged_upload_response(staging_id, saved_path)
        _bind_qualified_staging(current_user, staging_id, project_id)
        scientifically_admitted = True
        return response
    except FileValidationError as exc:
        shutil.rmtree(destination_dir, ignore_errors=True)
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except BaseException:
        if saved_path is not None and saved_path.exists():
            saved_path.unlink()
        shutil.rmtree(destination_dir, ignore_errors=True)
        raise
    finally:
        if scientifically_admitted:
            consume_reserved_demo_upload_quota_if_needed(user_id, upload_reserved)
        else:
            release_demo_upload_quota_reservation_if_needed(user_id, upload_reserved)


@router.post("/upload/stage-batch", dependencies=[Depends(demo_guard("data_upload"))])
async def stage_upload_batch(
    files: list[UploadFile] = File(...),
    project_id: int | None = Form(None),
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Stage every admissible source and report each refused selection member."""
    await _admit_qualified_staging(session, current_user, project_id, files)
    user_id = current_user.id
    upload_reserved = reserve_demo_upload_quota_or_429(user_id)
    batch_id = uuid.uuid4().hex
    root = _staging_root(current_user)
    temporary_root = root / f".batch-{batch_id}"
    staged_ids: list[str] = []
    published: list[Path] = []
    scientifically_admitted = False
    try:
        admitted = await admit_scientific_upload_batch(
            files,
            max_file_size_mb=settings.max_file_size_mb,
        )
        temporary_root.mkdir(parents=True, exist_ok=False)
        responses: list[dict[str, Any]] = []
        refusals = [{"source_name": refusal.source_name, "reason": refusal.reason} for refusal in admitted.refusals]
        for member in admitted.members:
            staging_id = uuid.uuid4().hex
            member_dir = temporary_root / staging_id
            member_dir.mkdir()
            member_path = member_dir / member.filename
            with member_path.open("xb") as stream:
                stream.write(member.payload)
                stream.flush()
                os.fsync(stream.fileno())
            try:
                response = await _staged_upload_response(
                    staging_id,
                    member_path,
                    source_name=member.source_name,
                )
            except HTTPException as exc:
                shutil.rmtree(member_dir, ignore_errors=True)
                detail = exc.detail if isinstance(exc.detail, str) else "Native parsing refused this source"
                refusals.append({"source_name": member.source_name, "reason": detail})
                continue
            staged_ids.append(staging_id)
            responses.append(response)

        if uses_managed_project_access():
            checker = get_hot_storage_checker()
            if checker is None:
                raise HTTPException(503, "Storage accounting is unavailable")
            await checker(
                session,
                user_id=user_id,
                project_id=project_id,
                incoming_bytes=sum(item["size_bytes"] for item in responses),
            )
        root.mkdir(parents=True, exist_ok=True)
        for staging_id in staged_ids:
            destination = root / staging_id
            if destination.exists():
                raise FileValidationError("Staging identity collision")
            os.replace(temporary_root / staging_id, destination)
            published.append(destination)
            _bind_qualified_staging(current_user, staging_id, project_id)
        shutil.rmtree(temporary_root, ignore_errors=True)
        scientifically_admitted = bool(responses)
        return {
            "file_count": len(responses),
            "total_size_bytes": sum(item["size_bytes"] for item in responses),
            "files": responses,
            "refused_count": len(refusals),
            "refusals": refusals,
        }
    except FileValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    finally:
        if not scientifically_admitted:
            for destination in published:
                shutil.rmtree(destination, ignore_errors=True)
            shutil.rmtree(temporary_root, ignore_errors=True)
        if scientifically_admitted:
            consume_reserved_demo_upload_quota_if_needed(user_id, upload_reserved)
        else:
            release_demo_upload_quota_reservation_if_needed(user_id, upload_reserved)


@router.delete("/upload/stage/{staging_id}", dependencies=[Depends(demo_guard("data_upload"))])
async def delete_staged_upload(
    staging_id: str,
    current_user: User = Depends(get_current_user),
) -> dict[str, str]:
    staged_path = _resolve_staged_upload(staging_id, current_user)
    shutil.rmtree(staged_path.parent, ignore_errors=True)
    (_staging_root(current_user) / f"{_validate_staging_id(staging_id)}.scope.json").unlink(missing_ok=True)
    return {"status": "deleted"}


@router.post("/upload/commit", dependencies=[Depends(demo_guard("data_upload"))])
async def commit_staged_uploads(
    payload: StagedUploadCommitRequest,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    user_id = current_user.id
    result = await session.execute(
        select(Experiment).where(
            Experiment.id == payload.experiment_id, or_(Experiment.user_id == user_id, uses_managed_project_access())
        )
    )
    experiment = result.scalar_one_or_none()
    if experiment is None:
        raise HTTPException(status_code=404, detail="Experiment not found")
    if payload.stage not in ALLOWED_STAGES:
        raise HTTPException(status_code=400, detail="Invalid stage")
    if uses_managed_project_access():
        await require_scientific_access(session, user_id, experiment.project_id, "write")
        if len({item.staging_id for item in payload.files}) != len(payload.files):
            raise HTTPException(400, "Duplicate staged upload")
        incoming = 0
        for item in payload.files:
            source = _resolve_staged_upload(item.staging_id, current_user)
            scope_file = _staging_root(current_user) / f"{item.staging_id}.scope.json"
            try:
                bound_project = json.loads(scope_file.read_text())["project_id"]
            except (OSError, ValueError, KeyError):
                raise HTTPException(409, "Staged upload must be admitted again") from None
            if bound_project != experiment.project_id:
                raise HTTPException(404, "Staged upload not found in this project")
            incoming += source.stat().st_size
        checker = get_hot_storage_checker()
        if checker is None:
            raise HTTPException(503, "Storage accounting is unavailable")
        await checker(session, user_id=user_id, project_id=experiment.project_id, incoming_bytes=0)

    exp_dir = experiment_dir(payload.experiment_id)
    destination_dir = exp_dir / payload.stage
    destination_dir.mkdir(parents=True, exist_ok=True)
    moved: list[Path] = []
    created: list[ExperimentFile] = []

    try:
        for item in payload.files:
            source_path = _resolve_staged_upload(item.staging_id, current_user)
            filename = sanitize_filename(source_path.name)
            destination = _unique_destination_path(destination_dir, filename)
            if not destination.is_relative_to(destination_dir.resolve()):
                raise HTTPException(status_code=400, detail="Invalid destination path")
            shutil.move(str(source_path), str(destination))
            moved.append(destination)

            prepared = PreparedDataOverrides.from_mapping(item.overrides)
            if not prepared.is_empty():
                save_prepared_data_overrides(prepared, file_path=str(destination))

            rel_path = destination.relative_to(exp_dir).as_posix()
            created.append(
                await add_experiment_file(
                    session=session,
                    experiment_id=payload.experiment_id,
                    stage=payload.stage,
                    file_path=rel_path,
                    file_size_bytes=destination.stat().st_size,
                    file_type=destination.suffix.lstrip(".") or None,
                    flush_only=True,
                )
            )
            shutil.rmtree(source_path.parent, ignore_errors=True)
            (_staging_root(current_user) / f"{item.staging_id}.scope.json").unlink(missing_ok=True)

        await session.commit()
    except BaseException:
        await session.rollback()
        for path in moved:
            if path.exists():
                path.unlink()
        raise

    for file_record in created:
        await session.refresh(file_record)

    return {"imported": len(created), "files": [file.id for file in created]}


async def _finalize_file_info(
    result: dict[str, Any],
    *,
    dataset: SherpaDataset,
    session: AsyncSession,
    binding: DatasetAnalysisBinding | None = None,
) -> dict[str, Any]:
    try:
        result["analysis_readiness"] = await dataset_analysis_readiness(dataset, session)
    except Exception:
        # Readiness is a derived navigation aid. A catalog/database defect must
        # never turn a successfully parsed scientific preview into a 500.
        logger.warning("Dataset analysis readiness projection failed", exc_info=True)
        result["analysis_readiness"] = unavailable_dataset_analysis_readiness(
            code="analysis_readiness_unavailable",
            message="The data preview is ready, but analysis matching is temporarily unavailable.",
            detail="Contact support if this persists.",
        )
    if binding is not None:
        result["analysis_binding"] = {
            "revision": _analysis_binding_revision(binding),
            "sample_table_file_id": binding.sample_table_file_id,
            "selected_target": binding.selected_target,
            "target_type": binding.target_type,
        }
    from spectra_sherpa.app.services.dag.serialize import finalize_api_dataset_response

    return finalize_api_dataset_response(result)


@router.get("/analysis-binding/{source_file_id}/revision")
async def get_dataset_analysis_binding_revision(
    source_file_id: int,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> dict[str, str | None]:
    """Return the nullable concurrency token without loading measured rows."""

    source_file = await session.scalar(
        select(ExperimentFile)
        .join(Experiment, Experiment.id == ExperimentFile.experiment_id)
        .where(
            ExperimentFile.id == source_file_id,
            Experiment.user_id == current_user.id,
        )
    )
    if source_file is None:
        raise HTTPException(status_code=404, detail="Source data was not found")
    binding = await session.scalar(
        select(DatasetAnalysisBinding).where(DatasetAnalysisBinding.source_file_id == source_file_id)
    )
    return {"revision": _analysis_binding_revision(binding)}


@router.get("/analysis-binding/{source_file_id}")
async def get_dataset_analysis_binding(
    source_file_id: int,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Return the exact bound measured-sample version for continued editing."""

    source_file = await session.scalar(
        select(ExperimentFile)
        .join(Experiment, Experiment.id == ExperimentFile.experiment_id)
        .where(
            ExperimentFile.id == source_file_id,
            Experiment.user_id == current_user.id,
        )
    )
    if source_file is None:
        raise HTTPException(status_code=404, detail="Source data was not found")
    binding = await session.scalar(
        select(DatasetAnalysisBinding).where(DatasetAnalysisBinding.source_file_id == source_file_id)
    )
    if binding is None:
        raise HTTPException(status_code=404, detail="Dataset analysis binding was not found")
    table_file = await session.scalar(
        select(ExperimentFile).where(
            ExperimentFile.id == binding.sample_table_file_id,
            ExperimentFile.experiment_id == source_file.experiment_id,
        )
    )
    if table_file is None:
        raise HTTPException(status_code=409, detail="Bound measured samples no longer resolve")
    from spectra_sherpa.app.services.dag.nodes.data.sample_table import (
        load_portable_sample_table_editor,
    )

    try:
        payload = await asyncio.to_thread(
            load_portable_sample_table_editor,
            experiment_dir(table_file.experiment_id) / table_file.file_path,
            selected_target=binding.selected_target,
            target_type=binding.target_type,
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if payload is None or payload["source_file_id"] != source_file_id:
        raise HTTPException(status_code=409, detail="Bound measured samples do not match their source")
    return {
        **payload,
        "revision": _analysis_binding_revision(binding),
        "sample_table_file_id": binding.sample_table_file_id,
    }


@router.post("/analysis-binding", dependencies=[Depends(demo_guard("prepared_data_authoring"))])
async def save_dataset_analysis_binding(
    payload: DatasetAnalysisBindingRequest,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Persist one explicit, source-identity-checked portable CSV binding."""

    if payload.source_file_id == payload.sample_table_file_id:
        raise HTTPException(status_code=400, detail="Source data and sample-table CSV must be different files")

    files = list(
        (
            await session.scalars(
                select(ExperimentFile)
                .join(Experiment, Experiment.id == ExperimentFile.experiment_id)
                .where(
                    Experiment.user_id == current_user.id,
                    ExperimentFile.id.in_([payload.source_file_id, payload.sample_table_file_id]),
                )
                .with_for_update()
            )
        ).all()
    )
    by_id = {item.id: item for item in files}
    source_file = by_id.get(payload.source_file_id)
    sample_table_file = by_id.get(payload.sample_table_file_id)
    if source_file is None or sample_table_file is None:
        raise HTTPException(status_code=404, detail="Source data or sample-table CSV was not found")
    binding = await session.scalar(
        select(DatasetAnalysisBinding).where(DatasetAnalysisBinding.source_file_id == source_file.id)
    )
    if _analysis_binding_revision(binding) != payload.expected_revision:
        raise HTTPException(
            status_code=409,
            detail="Measured samples changed after you opened them. Reload before saving.",
        )
    try:
        await asyncio.to_thread(
            validate_analysis_binding,
            source_file=source_file,
            sample_table_file=sample_table_file,
            selected_target=payload.selected_target.strip(),
            target_type=payload.target_type,
            load_source=_file_as_sherpa,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if binding is None:
        binding = DatasetAnalysisBinding(
            source_file_id=source_file.id,
            sample_table_file_id=sample_table_file.id,
            selected_target=payload.selected_target.strip(),
            target_type=payload.target_type,
        )
        session.add(binding)
        try:
            await session.commit()
        except IntegrityError as exc:
            await session.rollback()
            raise HTTPException(
                status_code=409,
                detail="Measured samples changed after you opened them. Reload before saving.",
            ) from exc
    else:
        result = await session.execute(
            update(DatasetAnalysisBinding)
            .where(*_analysis_binding_matches(binding))
            .values(
                sample_table_file_id=sample_table_file.id,
                selected_target=payload.selected_target.strip(),
                target_type=payload.target_type,
            )
            .execution_options(synchronize_session=False)
        )
        if (result.rowcount or 0) != 1:
            await session.rollback()
            raise HTTPException(
                status_code=409,
                detail="Measured samples changed after you opened them. Reload before saving.",
            )
        await session.commit()
    await session.refresh(binding)
    return {
        "status": "bound",
        "revision": _analysis_binding_revision(binding),
        "source_file_id": binding.source_file_id,
        "sample_table_file_id": binding.sample_table_file_id,
        "selected_target": binding.selected_target,
        "target_type": binding.target_type,
    }


@router.delete("/analysis-binding/{source_file_id}", dependencies=[Depends(demo_guard("prepared_data_authoring"))])
async def delete_dataset_analysis_binding(
    source_file_id: int,
    expected_revision: str,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Remove supervision metadata without deleting either source file."""

    source_file = await session.scalar(
        select(ExperimentFile)
        .join(Experiment, Experiment.id == ExperimentFile.experiment_id)
        .where(
            ExperimentFile.id == source_file_id,
            Experiment.user_id == current_user.id,
        )
        .with_for_update()
    )
    if source_file is None:
        raise HTTPException(status_code=404, detail="Source data was not found")
    binding = await session.scalar(
        select(DatasetAnalysisBinding).where(DatasetAnalysisBinding.source_file_id == source_file_id)
    )
    if binding is None:
        raise HTTPException(status_code=404, detail="Dataset analysis binding was not found")
    if _analysis_binding_revision(binding) != expected_revision:
        raise HTTPException(
            status_code=409,
            detail="Measured samples changed after you opened them. Reload before removing the binding.",
        )
    result = await session.execute(
        delete(DatasetAnalysisBinding)
        .where(*_analysis_binding_matches(binding))
        .execution_options(synchronize_session=False)
    )
    if (result.rowcount or 0) != 1:
        await session.rollback()
        raise HTTPException(
            status_code=409,
            detail="Measured samples changed after you opened them. Reload before removing the binding.",
        )
    await session.commit()
    return {"status": "unbound", "source_file_id": source_file_id}


async def _qualified_file_info(payload, session, current_user):
    from spectra_sherpa.app.services.model_application import load_project_dataset
    from spectra_sherpa.app.services.serialization import serialize_result

    experiment = await session.get(Experiment, payload.experiment_id) if payload.experiment_id else None
    if experiment is None:
        raise HTTPException(404, "Project experiment required")
    await require_scientific_access(session, current_user.id, experiment.project_id, "read")
    files_query = select(ExperimentFile).where(ExperimentFile.experiment_id == experiment.id)
    if payload.file_path is not None:
        files_query = files_query.where(ExperimentFile.file_path == payload.file_path)
    elif payload.file_ids is not None:
        files_query = files_query.where(ExperimentFile.id.in_(payload.file_ids))
    else:
        selected_stage = await preferred_experiment_stage(session, experiment.id) or "raw"
        files_query = files_query.where(ExperimentFile.stage == selected_stage)
    files = list((await session.scalars(files_query.order_by(ExperimentFile.id))).all())
    if not files or (payload.file_ids is not None and {file.id for file in files} != set(payload.file_ids)):
        raise HTTPException(404, "Experiment files not found")
    if len({file.stage for file in files}) != 1:
        raise HTTPException(400, "Selected files must share one stage")
    loaded = await load_project_dataset(
        session,
        user_id=current_user.id,
        experiment_id=experiment.id,
        stage=files[0].stage,
        file_ids=[file.id for file in files],
        asset_id=payload.asset_id,
    )
    result = serialize_result(loaded.dataset, owner_user_id=current_user.id, project_id=loaded.project_id)
    result.setdefault("metadata", {}).update(
        {"contents_file_count": len(files), "contents_stage": files[0].stage, "contents_title": experiment.name}
    )
    finalized = await _finalize_file_info(result, dataset=loaded.dataset, session=session)
    await require_scientific_access(session, current_user.id, experiment.project_id, "read")
    return finalized


@router.post("/file-info")
async def get_file_info(
    payload: FileInfoRequest,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> dict:
    """Inspect a file: load as SherpaDataset and return to_dict() format."""
    from spectra_sherpa.app.services.serialization import serialize_result

    _validate_file_info_selection(payload)
    if uses_managed_project_access():
        return await _qualified_file_info(payload, session, current_user)
    file_path = payload.file_path
    selected_file: ExperimentFile | None = None
    contents_file_count = 1
    contents_stage = "raw"
    contents_title: str | None = None
    if app_config.site_profile == "demo":
        if payload.experiment_id is None:
            raise HTTPException(
                status_code=403,
                detail=(
                    "The free trial can inspect only its server-issued Lavender data or an exact "
                    "registered reference file imported through Reference Datasets."
                ),
            )
        experiment = await session.scalar(
            select(Experiment).where(
                Experiment.id == payload.experiment_id,
                Experiment.user_id == current_user.id,
            )
        )
        if experiment is None:
            raise HTTPException(status_code=404, detail="Experiment not found")
        if payload.file_ids is not None:
            selected_files = list(
                (
                    await session.execute(
                        select(ExperimentFile)
                        .where(
                            ExperimentFile.experiment_id == payload.experiment_id,
                            ExperimentFile.id.in_(payload.file_ids),
                        )
                        .order_by(ExperimentFile.id.asc())
                    )
                )
                .scalars()
                .all()
            )
            if {int(file.id) for file in selected_files} != set(payload.file_ids):
                raise HTTPException(status_code=404, detail="Selected dataset view was not found")
            stages = {str(file.stage) for file in selected_files}
            if len(stages) != 1:
                raise HTTPException(status_code=400, detail="Selected dataset views must share one stage")

            from spectra_sherpa.app.contracts.demo_policy import require_trial_dataset_access

            selected_stage = stages.pop()
            try:
                admission = await require_trial_dataset_access(
                    session=session,
                    user_id=current_user.id,
                    workflow_project_id=experiment.project_id,
                    experiment_id=payload.experiment_id,
                    stage=selected_stage,
                    file_id=None,
                    file_ids=payload.file_ids,
                    asset_id=None,
                )
                loaded = admission.loaded_dataset
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
            result = serialize_result(loaded.dataset, owner_user_id=current_user.id, project_id=loaded.project_id)
            if not isinstance(result, dict):
                raise HTTPException(status_code=400, detail="Dataset inspection did not produce a typed response")
            metadata = result.setdefault("metadata", {})
            metadata["contents_file_count"] = len(loaded.file_ids)
            metadata["contents_stage"] = loaded.stage
            metadata["contents_title"] = loaded.experiment_name
            source_collection = loaded.dataset.meta.get("source_collection")
            if isinstance(source_collection, dict):
                metadata["source_collection"] = source_collection
            _project_single_member_metadata(metadata, contents_file_count=len(loaded.file_ids))
            return await _finalize_file_info(result, dataset=loaded.dataset, session=session)
        if file_path is not None:
            selected_file = await session.scalar(
                select(ExperimentFile).where(
                    ExperimentFile.experiment_id == payload.experiment_id,
                    ExperimentFile.file_path == file_path,
                )
            )
            if selected_file is None:
                raise HTTPException(status_code=404, detail="Experiment file not found")

        from spectra_sherpa.app.contracts.demo_policy import require_trial_dataset_access

        selected_stage = (
            str(selected_file.stage)
            if selected_file is not None
            else (await preferred_experiment_stage(session, payload.experiment_id) or "raw")
        )
        admission = await require_trial_dataset_access(
            session=session,
            user_id=current_user.id,
            workflow_project_id=experiment.project_id,
            experiment_id=payload.experiment_id,
            stage=selected_stage,
            file_id=selected_file.id if selected_file is not None else None,
            asset_id=payload.asset_id,
        )
        loaded = admission.loaded_dataset
        contents_file_count = len(loaded.file_ids)
        result = serialize_result(loaded.dataset, owner_user_id=current_user.id, project_id=loaded.project_id)
        if not isinstance(result, dict):
            raise HTTPException(status_code=400, detail="Dataset inspection did not produce a typed response")
        metadata = result.setdefault("metadata", {})
        metadata["contents_file_count"] = contents_file_count
        metadata["contents_stage"] = loaded.stage
        metadata["contents_title"] = loaded.experiment_name
        source_collection = loaded.dataset.meta.get("source_collection")
        if isinstance(source_collection, dict):
            metadata["source_collection"] = source_collection
        _project_single_member_metadata(metadata, contents_file_count=contents_file_count)
        return await _finalize_file_info(result, dataset=loaded.dataset, session=session)

    if file_path is None:
        if payload.experiment_id is None:
            raise HTTPException(status_code=400, detail="Provide file_path or experiment_id")
        try:
            if payload.file_ids is not None:
                from spectra_sherpa.app.services.model_application import load_project_dataset

                selected_files = list(
                    (
                        await session.execute(
                            select(ExperimentFile)
                            .join(Experiment, Experiment.id == ExperimentFile.experiment_id)
                            .where(
                                Experiment.user_id == current_user.id,
                                ExperimentFile.experiment_id == payload.experiment_id,
                                ExperimentFile.id.in_(payload.file_ids),
                            )
                        )
                    )
                    .scalars()
                    .all()
                )
                if {int(file.id) for file in selected_files} != set(payload.file_ids):
                    raise ValueError("Selected dataset view is outside the owned dataset")
                stages = {str(file.stage) for file in selected_files}
                if len(stages) != 1:
                    raise ValueError("Selected dataset views must share one stage")
                loaded = await load_project_dataset(
                    session,
                    user_id=current_user.id,
                    experiment_id=payload.experiment_id,
                    stage=stages.pop(),
                    file_ids=payload.file_ids,
                    asset_id=payload.asset_id,
                )
                sd = loaded.dataset
                contents_file_count = len(loaded.file_ids)
                contents_title = loaded.experiment_name
                contents_stage = loaded.stage
                source_collection = sd.meta.get("source_collection")
            else:
                sd, files, contents_title, contents_stage, source_collection = await _experiment_contents_as_sherpa(
                    payload.experiment_id,
                    session,
                    current_user,
                    asset_id=payload.asset_id,
                )
                contents_file_count = len(files)
            result = serialize_result(sd, owner_user_id=current_user.id)
            if not isinstance(result, dict):
                raise ValueError("dataset inspection did not produce a typed response")
            metadata = result.setdefault("metadata", {})
            metadata["contents_file_count"] = contents_file_count
            metadata["contents_stage"] = contents_stage
            metadata["contents_title"] = contents_title
            if isinstance(source_collection, dict):
                metadata["source_collection"] = source_collection
            # A one-file experiment historically exposed the source dataset's
            # metadata directly (for example, a saved synthesis recipe).  The
            # collection authority retains that metadata under the exact
            # member identity; preserve the established inspection wire
            # projection without flattening ambiguous multi-file metadata.
            _project_single_member_metadata(metadata, contents_file_count=contents_file_count)
            return await _finalize_file_info(result, dataset=sd, session=session)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    if payload.experiment_id is not None:
        selected_file = await session.scalar(
            select(ExperimentFile)
            .join(Experiment, Experiment.id == ExperimentFile.experiment_id)
            .where(
                Experiment.user_id == current_user.id,
                ExperimentFile.experiment_id == payload.experiment_id,
                ExperimentFile.file_path == file_path,
            )
        )
        if selected_file is None:
            raise HTTPException(status_code=404, detail="Experiment file not found")
        stage_hint = Path(file_path).parts[0] if file_path else ""
        if stage_hint in ALLOWED_STAGES:
            contents_stage = stage_hint
        exp_dir = experiment_dir(payload.experiment_id)
        full_path = (exp_dir / file_path).resolve()
        file_path = str(full_path.relative_to(settings.data_dir))

    await _validate_file_path_ownership(file_path, session, current_user)

    resolved = service._resolve_payload_path(file_path)

    try:
        overrides = load_prepared_data_overrides(file_path=file_path)
        sd = await asyncio.to_thread(
            _file_as_sherpa,
            resolved,
            asset_id=payload.asset_id,
            prepared_overrides=overrides.to_sidecar_dict(),
        )
        sd, analysis_binding = await apply_saved_analysis_binding(
            sd,
            source_file=selected_file,
            session=session,
        )

        result = serialize_result(sd, owner_user_id=current_user.id)
        if not isinstance(result, dict):
            raise ValueError("dataset inspection did not produce a typed response")

        # Apply persisted user overrides
        result = apply_serialized_prepared_data_overrides(result, overrides)
        metadata = result.setdefault("metadata", {})
        metadata["contents_file_count"] = contents_file_count
        metadata["contents_stage"] = contents_stage

        return await _finalize_file_info(
            result,
            dataset=sd,
            session=session,
            binding=analysis_binding,
        )

    except ValueError as exc:
        logger.info("File inspect rejected invalid input for %s: %s", file_path, type(exc).__name__)
        raise HTTPException(status_code=400, detail="File preview could not parse the selected data.") from None
    except Exception as exc:
        logger.warning("File inspect failed for %s: %s", file_path, type(exc).__name__, exc_info=True)
        raise HTTPException(status_code=500, detail="File preview failed.") from None


@router.patch("/file-metadata", dependencies=[Depends(demo_guard("prepared_data_authoring"))])
async def update_file_metadata(
    payload: MetadataOverrideRequest,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> dict[str, str]:
    """Persist user-supplied metadata overrides for a dataset."""
    overrides = PreparedDataOverrides(
        x_title=payload.x_title,
        x_units=payload.x_units,
        y_title=payload.y_title,
        is_time_series=payload.is_time_series,
        target_mode=payload.target_mode,
        selected_target=payload.selected_target,
        csv_layout=payload.csv_layout,
    )

    if overrides.is_empty():
        return {"status": "ok", "detail": "no changes"}

    if payload.source and payload.name:
        save_prepared_data_overrides(overrides, source=payload.source, name=payload.name)
    elif payload.file_path:
        file_path = payload.file_path
        full_path: Path | None = None
        if payload.experiment_id is not None:
            exp_dir = experiment_dir(payload.experiment_id)
            full_path = (exp_dir / file_path).resolve()
            file_path = str(full_path.relative_to(settings.data_dir))
        await _validate_file_path_ownership(file_path, session, current_user)
        save_prepared_data_overrides(overrides, file_path=file_path)
        resolved = full_path or service._resolve_payload_path(file_path)
        if resolved.suffix.lower() == ".npz":
            from spectra_sherpa.app.services.synthesis import is_synthetic_npz, update_synthetic_npz_metadata

            if is_synthetic_npz(resolved):
                update_synthetic_npz_metadata(resolved, overrides.to_sidecar_dict())
    else:
        raise HTTPException(400, "Provide file_path or source+name")

    return {"status": "ok"}


# ═══════════════════════════════════════════════════════════════════════════════
# Reference Dataset Catalog
# ═══════════════════════════════════════════════════════════════════════════════


def _registered_reference_dataset_options() -> list[dict[str, Any]]:
    """Project the closed upstream registry into path-free catalog cards."""

    from spectra_sherpa.app.lib.reference_artifacts import registered_reference_catalog

    return registered_reference_catalog()


def _builtin_dataset_options() -> list[dict[str, Any]]:
    """Project distributed references through the same model-neutral cards."""

    from spectra_sherpa.app.lib.reference_artifacts import builtin_dataset_catalog
    from spectra_sherpa.app.services.experiments import builtin_lavender_source_files

    options = builtin_dataset_catalog()
    available: list[dict[str, Any]] = []
    for option in options:
        if option["name"] == "lavender-essential-oil-v1":
            files = builtin_lavender_source_files()
            if not files:
                continue
            option["files"] = files
            option["file_count"] = len(files)
        available.append(option)
    return available


def _synthetic_dataset_options() -> list[dict[str, Any]]:
    from spectra_sherpa.app.lib.synthetic_references import SYNTHETIC_REFERENCE_CATALOG

    return [
        {
            "name": k,
            "source": "synthetic",
            "label": v["label"],
            "technique": v["technique"],
            "is_spectra": True,
            "data_role": "X_spectra",
            "description": v["description"],
            "featured": v.get("featured", False),
            "file_path": (_files[0] if (_files := _catalog_source_files(v)) else None),
            "files": _files,
            "has_embedded_target": bool(v.get("target_fields")),
            "target_type": v.get("target_type"),
            "target_fields": list(v.get("target_fields") or []),
        }
        for k, v in SYNTHETIC_REFERENCE_CATALOG.items()
    ]


def _eigenvector_dataset_options() -> list[dict[str, Any]]:
    from spectra_sherpa.app.lib.eigenvector import DATASET_CATALOG

    return [
        {
            "name": k,
            "source": "eigenvector",
            "label": v["label"],
            "technique": v["technique"],
            "is_spectra": infer_is_spectra(technique=v.get("technique"), x_units=v.get("x_units")),
            "data_role": "X_spectra",
            "description": v["description"],
            "featured": v.get("featured", False),
            "file_path": (_files[0] if (_files := _catalog_source_files(v)) else None),
            "files": _files,
            "requires_runtime_download": True,
            "download_page": "https://eigenvector.com/resources/data-sets/",
            "has_embedded_target": bool(v.get("prop_names")),
            "target_type": "continuous" if v.get("prop_names") else None,
            "target_fields": list(v.get("prop_names") or []),
        }
        for k, v in DATASET_CATALOG.items()
    ]


def _oes_dataset_options() -> list[dict[str, Any]]:
    from spectra_sherpa.app.lib.oes_datasets import OES_CATALOG

    return [
        {
            "name": k,
            "source": "oes",
            "label": v["label"],
            "technique": v["technique"],
            "is_spectra": infer_is_spectra(technique=v.get("technique"), x_units=v.get("x_units")),
            "data_role": "X_spectra",
            "description": v["description"],
            "featured": v.get("featured", False),
            "file_path": (_files[0] if (_files := _catalog_source_files(v)) else None),
            "files": _files,
            "has_embedded_target": False,
            "target_type": None,
        }
        for k, v in OES_CATALOG.items()
    ]


def _sklearn_dataset_options() -> list[dict[str, Any]]:
    from spectra_sherpa.app.lib.sklearn_info import SKLEARN_CATALOG

    return [
        {
            "name": k,
            "source": "sklearn",
            "label": v["label"],
            "technique": "ML/Statistics",
            "is_spectra": infer_is_spectra(v.get("is_spectra"), technique="ML/Statistics"),
            "data_role": "X_features",
            "description": f"Scikit-learn {k} dataset",
            "has_embedded_target": True,
            "target_type": "categorical" if v.get("task_type") == "classification" else "continuous",
            "target_fields": ["target"],
            "task_type": v.get("task_type"),
        }
        for k, v in SKLEARN_CATALOG.items()
    ]


def _enforce_reference_dataset_info_policy(_source: str) -> None:
    if app_config.site_profile != "demo":
        return
    # Reference dataset metadata and previews are read-only catalog inspection.
    # Hosted trial import policy is enforced at the mutating import boundary.
    return


@router.get("/reference-datasets")
async def list_reference_datasets() -> dict[str, list[dict[str, Any]]]:
    """List all available reference datasets across all sources."""
    registered = _registered_reference_dataset_options()
    builtin = _builtin_dataset_options()
    if app_config.site_profile in {"demo", "pro"}:
        # Hosted catalogs expose local references and exact user-acquired packages;
        # but server-issued references remain legitimate import choices.
        return {
            "builtin": builtin,
            "registered": registered,
            "synthetic": _synthetic_dataset_options(),
            "eigenvector": [],
            "oes": [],
            "sklearn": _sklearn_dataset_options(),
        }

    # Note: `data_role` must be set on every entry — the frontend's
    # example-dataset filter uses it to pass feature-tables through on
    # dual-mode templates (PCA, PLS-DA,
    # KNN, SIMCA, HCA, Spectral Decomposition) that declare
    # `accepted_data_roles: [X_spectra, X_features]`. Without the field the
    # role-match short-circuits to false and sklearn:wine/iris stay
    # hidden even though the backend matching-datasets endpoint returns them.
    return {
        "builtin": builtin,
        "registered": registered,
        "synthetic": _synthetic_dataset_options(),
        "eigenvector": _eigenvector_dataset_options(),
        "oes": _oes_dataset_options(),
        "sklearn": _sklearn_dataset_options(),
    }


@router.get("/reference-datasets/{source}/{name:path}")
async def get_reference_dataset_info(source: str, name: str) -> dict[str, Any]:
    """Get full metadata + statistics for a reference dataset."""
    _enforce_reference_dataset_info_policy(source)
    if source == "synthetic":
        from spectra_sherpa.app.lib.synthetic_references import (
            SYNTHETIC_REFERENCE_CATALOG,
            get_synthetic_reference_info,
        )

        if name not in SYNTHETIC_REFERENCE_CATALOG:
            raise HTTPException(404, f"Dataset '{name}' not found")
        try:
            info = get_synthetic_reference_info(name)
        except (FileNotFoundError, ValueError) as exc:
            raise HTTPException(404, f"Dataset '{name}' not found") from exc

    elif source == "eigenvector":
        from spectra_sherpa.app.lib.eigenvector import DATASET_CATALOG
        from spectra_sherpa.app.services.eigenvector_datasets import get_dataset_info

        if name not in DATASET_CATALOG:
            raise HTTPException(404, f"Dataset '{name}' not found")
        try:
            info = get_dataset_info(name)
        except (FileNotFoundError, ValueError) as exc:
            raise HTTPException(404, f"Dataset '{name}' not found") from exc

    elif source == "sklearn":
        from spectra_sherpa.app.lib.sklearn_info import SKLEARN_CATALOG, get_sklearn_dataset_info

        if name not in SKLEARN_CATALOG:
            raise HTTPException(404, f"Dataset '{name}' not found")
        try:
            info = get_sklearn_dataset_info(name)
        except (FileNotFoundError, ValueError) as exc:
            raise HTTPException(404, f"Dataset '{name}' not found") from exc

    elif source == "oes":
        from spectra_sherpa.app.lib.oes_datasets import OES_CATALOG, get_oes_dataset_info

        if name not in OES_CATALOG:
            raise HTTPException(404, f"Dataset '{name}' not found")
        try:
            info = get_oes_dataset_info(name)
        except (FileNotFoundError, ValueError) as exc:
            raise HTTPException(404, f"Dataset '{name}' not found") from exc

    else:
        raise HTTPException(400, f"Unknown source: {source}")

    # Apply persisted user overrides to reference dataset info
    overrides = load_prepared_data_overrides(source=source, name=name)
    if not overrides.is_empty():
        if overrides.x_title is not None:
            info["x_title"] = overrides.x_title
        if overrides.x_units is not None:
            info["x_units"] = overrides.x_units
        if overrides.y_title is not None:
            info["data_quantity"] = overrides.y_title
        if overrides.is_time_series is not None:
            info["is_time_series"] = overrides.is_time_series
            if "metadata" in info:
                info["metadata"]["is_time_series"] = overrides.is_time_series
        if overrides.target_mode is not None:
            info.setdefault("metadata", {})["target_mode"] = overrides.target_mode
        if overrides.selected_target is not None:
            info.setdefault("metadata", {})["selected_target"] = overrides.selected_target

    return info
