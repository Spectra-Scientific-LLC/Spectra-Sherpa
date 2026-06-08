from __future__ import annotations

import re
import shutil
import uuid
from pathlib import Path
from typing import Any, Literal

import numpy as np
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from spectra_sherpa.app.api.deps import (
    consume_reserved_demo_upload_quota_if_needed,
    demo_guard,
    get_current_user,
    get_session,
    release_demo_upload_quota_reservation_if_needed,
    reserve_demo_upload_quota_or_429,
)
from spectra_sherpa.app.core.config import settings
from spectra_sherpa.app.lib.data_formats import ensure_reader_available
from spectra_sherpa.app.lib.domain_flags import infer_is_spectra
from spectra_sherpa.app.lib.sample_labels import clean_sample_labels
from spectra_sherpa.app.lib.sherpa_dataset import FeatureAxis, SampleAxis, SherpaDataset, SpectralAxis, TargetContext
from spectra_sherpa.app.models.calibration import Calibration
from spectra_sherpa.app.models.experiment import Experiment
from spectra_sherpa.app.models.experiment_file import ExperimentFile
from spectra_sherpa.app.models.user import User
from spectra_sherpa.app.schemas.builder import (
    BlendRequest,
    BlendResponse,
    ConcentrationGenerateRequest,
    ConcentrationGenerateResponse,
    CurveDefaultsResponse,
    CurvePointsRequest,
    CurvePointsResponse,
    PreprocessRequest,
    PreprocessResponse,
    SpectrumPayload,
    SynthesizeRequest,
    SynthesizeResponse,
)
from spectra_sherpa.app.services.builder import BuilderService
from spectra_sherpa.app.services.experiments import ALLOWED_STAGES, add_experiment_file, experiment_dir
from spectra_sherpa.app.services.file_storage import FileValidationError, sanitize_filename, save_upload_file
from spectra_sherpa.app.services.prepared_data import (
    PreparedDataOverrides,
    apply_dataset_prepared_data_overrides,
    apply_serialized_prepared_data_overrides,
    load_prepared_data_overrides,
    save_prepared_data_overrides,
)


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
    # Resolve path relative to data_dir
    if Path(file_path).is_absolute():
        # This route immediately enforces data_dir containment and ownership
        # below before any read is allowed.
        # lgtm[py/path-injection]
        resolved = Path(file_path).resolve()
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


class DataMatrixRequest(BaseModel):
    kind: Literal["reference", "experiment_file", "staged"]
    source: str | None = None
    name: str | None = None
    experiment_id: int | None = None
    file_id: int | None = None
    staging_id: str | None = None
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


async def _validate_payload_file_paths(
    items: list[Any],
    session: AsyncSession,
    current_user: User,
) -> None:
    """Validate all file_path entries in a list of spectrum/species payloads."""
    for item in items:
        item_dict = item.model_dump() if hasattr(item, "model_dump") else item
        file_path = item_dict.get("file_path")
        if file_path:
            await _validate_file_path_ownership(file_path, session, current_user)


@router.post("/preprocess", response_model=PreprocessResponse)
async def preprocess_spectra(
    payload: PreprocessRequest,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> PreprocessResponse:
    # Validate user has access to all file paths in the payload
    await _validate_payload_file_paths(payload.spectra, session, current_user)

    try:
        processed, metadata = service.preprocess(
            spectra=[item.model_dump() for item in payload.spectra],
            settings_dict=payload.settings,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    data = [SpectrumPayload(**service.to_payload(record)) for record in processed]
    return PreprocessResponse(status="ok", data=data, metadata=metadata)


def _load_synthetic_npz_as_sherpa(path: Path) -> Any:
    """Read a SpectraSherpa synthetic `.npz` and wrap it as a SherpaDataset.

    Mirrors the shape produced by `load_csv_as_sherpa` so the inspect
    endpoint can serialize it via `_serialize_sherpa_dataset` without
    branching downstream. The wavenumber grid stored on disk is wired
    into the SherpaDataset as the SpectralAxis values, so editing the
    X/Y axis titles in the Inspect window (which writes to the
    prepared-data overrides sidecar) does not strip the numeric grid —
    the dataset stays complete on every reload. Raises `ValueError`
    (handled upstream as 400) if the file lacks the synthesis signature.
    """
    import json as _json

    import numpy as _np

    from spectra_sherpa.app.lib.axes import SampleAxis, SpectralAxis
    from spectra_sherpa.app.lib.sherpa_dataset import DomainContext, SherpaDataset
    from spectra_sherpa.app.services.synthesis import is_synthetic_npz, load_synthetic_npz

    if not is_synthetic_npz(path):
        raise ValueError(
            "NPZ file is not a SpectraSherpa synthetic dataset; only synthesis-produced "
            "`.npz` files are inspectable."
        )

    data = load_synthetic_npz(path)
    X = _np.asarray(data["X"], dtype=float)
    wavenumber = _np.asarray(data["wavenumber"], dtype=float)
    sample_labels = data["sample_labels"]
    embedded_meta = data.get("metadata") if isinstance(data.get("metadata"), dict) else {}
    target_names: list[str] | None = None
    try:
        ground_truth = _json.loads(data["ground_truth_json"])
        if isinstance(ground_truth, dict):
            names = ground_truth.get("component_names")
            if isinstance(names, list) and names:
                target_names = [str(name) for name in names]
    except (ValueError, TypeError):
        target_names = None
    C = _np.asarray(data["C"], dtype=float)
    if target_names is None:
        target_names = [f"component_{index + 1}" for index in range(C.shape[1] if C.ndim == 2 else 1)]

    extra: dict[str, object] = {
        "source": "synthesis",
        "feature_units": data.get("feature_units"),
        "value_units": data.get("units"),
    }
    try:
        recipe = _json.loads(data["recipe_json"])
        if isinstance(recipe, dict):
            extra["recipe"] = recipe
    except (ValueError, TypeError):
        pass

    title = str(embedded_meta.get("title") or path.stem)
    value_units = str(embedded_meta.get("value_units") or data.get("units") or "absorbance")
    return SherpaDataset(
        X=X,
        feature_axis=SpectralAxis(
            values=wavenumber,
            title=str(embedded_meta.get("x_title") or "Wavenumber"),
            units=str(embedded_meta.get("x_units") or data.get("feature_units") or "cm^-1"),
        ),
        sample_axis=(
            SampleAxis(labels=sample_labels, title=str(embedded_meta.get("y_title") or "Sample"))
            if sample_labels
            else None
        ),
        target=C,
        target_context=TargetContext(
            target_type="continuous",
            target_name="synthetic concentration",
            target_names=target_names,
            target_units=str(data.get("concentration_units") or "ppm"),
        ),
        extra=extra,
        title=title,
        units=value_units,
        domain=DomainContext(
            technique=str(embedded_meta.get("spectral_technique") or "FTIR"),
            data_quantity=str(embedded_meta.get("data_quantity") or "Absorbance"),
        ),
        data_role=str(embedded_meta.get("data_role") or "X_spectra"),
        is_time_series=bool(embedded_meta.get("is_time_series", False)),
    )


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
    if X.ndim != 2:
        raise HTTPException(status_code=400, detail=f"Matrix preview supports 2D datasets, got shape {list(X.shape)}")

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

    x_title = getattr(feature_axis, "title", None) if feature_axis is not None else None
    x_units = getattr(feature_axis, "units", None) if feature_axis is not None else None
    y_title = getattr(sample_axis, "title", None) if sample_axis is not None else None

    return {
        "shape": [total_rows, total_cols],
        "shape_label": "samples x features",
        "x_title": x_title or ("Wavenumber" if dataset.data_role == "X_spectra" else "Feature"),
        "x_units": x_units,
        "y_title": y_title or "Sample",
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


def _reference_dataset_as_sherpa(source: str, name: str) -> SherpaDataset:
    if source == "synthetic":
        from spectra_sherpa.app.lib.synthetic_references import load_synthetic_reference_as_sherpa

        try:
            return load_synthetic_reference_as_sherpa(name)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=f"Dataset '{name}' not found") from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    if source == "eigenvector":
        from spectra_sherpa.app.lib.eigenvector import DATASET_CATALOG, load_eigenvector_dataset

        if name not in DATASET_CATALOG:
            raise HTTPException(status_code=404, detail=f"Dataset '{name}' not found")
        result = load_eigenvector_dataset(name)
        catalog = result["catalog_entry"]
        return SherpaDataset(
            X=np.asarray(result["spectra"], dtype=np.float64),
            feature_axis=SpectralAxis(
                values=(
                    np.asarray(result["wavelengths"], dtype=np.float64)
                    if result.get("wavelengths") is not None
                    else np.arange(result["spectra"].shape[1], dtype=np.float64)
                ),
                title=catalog.get("x_title") or "Feature",
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
    if source == "spectrochempy":
        from spectra_sherpa.app.lib.scp_catalog import load_scp_reference_as_sherpa

        try:
            return load_scp_reference_as_sherpa(name)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=f"Dataset '{name}' not found") from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    raise HTTPException(status_code=400, detail=f"Unknown source: {source}")


async def _experiment_file_as_sherpa(
    experiment_id: int,
    file_id: int,
    session: AsyncSession,
    current_user: User,
) -> SherpaDataset:
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
    return _file_as_sherpa(path)


async def _experiment_contents_as_sherpa(
    experiment_id: int,
    session: AsyncSession,
    current_user: User,
) -> tuple[SherpaDataset, list[ExperimentFile], str, str]:
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
            .order_by(ExperimentFile.created_at.asc(), ExperimentFile.id.asc())
        )
        files = list(files_result.scalars().all())
        if files:
            stage = candidate_stage
            break
    if not files:
        raise HTTPException(status_code=404, detail="No raw or synthetic files found in dataset")

    loaded = []
    for file in files:
        path = experiment_dir(experiment_id) / file.file_path
        dataset = _file_as_sherpa(path)
        overrides = load_prepared_data_overrides(file_path=str(path.resolve()))
        if not overrides.is_empty():
            dataset = apply_dataset_prepared_data_overrides(dataset, overrides)
        loaded.append((dataset, file))
    if len(loaded) == 1:
        return loaded[0][0], files, experiment.name, stage

    first = loaded[0][0]
    ref_axis = first.get_feature_axis()
    ref_values = ref_axis.values if ref_axis is not None else None
    ref_labels = ref_axis.labels if ref_axis is not None else None

    rows: list[np.ndarray] = []
    labels: list[str] = []
    targets: list[np.ndarray] = []
    all_targets_present = True
    for dataset, file_record in loaded:
        axis = dataset.get_feature_axis()
        axis_values = axis.values if axis is not None else None
        axis_labels = axis.labels if axis is not None else None
        aligned = dataset.n_features == first.n_features
        if ref_values is not None and axis_values is not None:
            aligned = aligned and np.allclose(axis_values, ref_values, equal_nan=True)
        elif ref_labels is not None and axis_labels is not None:
            aligned = aligned and list(axis_labels) == list(ref_labels)
        if not aligned:
            raise ValueError("Raw files must share the same feature axis to display combined dataset contents")

        rows.append(np.asarray(dataset.X, dtype=np.float64).reshape(dataset.n_samples, dataset.n_features))
        sample_axis = dataset.sample_axis
        sample_labels = sample_axis.labels if sample_axis and sample_axis.labels else None
        file_label = file_record.file_path.split("/")[-1]
        labels.extend(
            clean_sample_labels(
                sample_labels,
                dataset.n_samples,
                fallback_prefix=file_label if dataset.n_samples == 1 else "Sample",
                source_name=file_label,
            )
        )

        if dataset.target is None:
            all_targets_present = False
        else:
            targets.append(np.asarray(dataset.target))

    sample_axis = SampleAxis(labels=labels, title="Samples")
    target = np.concatenate(targets, axis=0) if all_targets_present and targets else None
    combined = SherpaDataset(
        np.vstack(rows),
        feature_axis=ref_axis,
        sample_axis=sample_axis,
        target=target,
        target_context=first.target_context,
        domain=first.domain,
        provenance=first.provenance,
        quality=first.quality,
        backend=first.backend,
        title=experiment.name,
        units=first.units,
        is_time_series=first.is_time_series,
        data_role=first.data_role,
    )
    return combined, files, experiment.name, stage


def _file_as_sherpa(path: Path) -> SherpaDataset:
    from spectra_sherpa.app.lib.adapters.scp_adapter import from_nddataset
    from spectra_sherpa.app.lib.io import load_csv_as_sherpa, load_open_spectral_file_as_sherpa, stack_datasets

    suffix = path.suffix.lower()
    if suffix == ".csv":
        return load_csv_as_sherpa(path)
    if suffix == ".npz":
        from spectra_sherpa.app.services.synthesis import is_synthetic_npz

        if is_synthetic_npz(path):
            return _load_synthetic_npz_as_sherpa(path)
    open_dataset = load_open_spectral_file_as_sherpa(path)
    if open_dataset is not None:
        return open_dataset
    ensure_reader_available(suffix)
    datasets = service._load_datasets_from_file({"file_path": str(path)})
    if not datasets:
        raise ValueError("No spectra found in file")
    stacked = stack_datasets(datasets) if len(datasets) > 1 else datasets[0]
    return from_nddataset(stacked)


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
    try:
        if payload.kind == "reference":
            if not payload.source or not payload.name:
                raise HTTPException(status_code=400, detail="source and name are required")
            dataset = _reference_dataset_as_sherpa(payload.source, payload.name)
        elif payload.kind == "experiment_file":
            if payload.experiment_id is None or payload.file_id is None:
                raise HTTPException(status_code=400, detail="experiment_id and file_id are required")
            dataset = await _experiment_file_as_sherpa(payload.experiment_id, payload.file_id, session, current_user)
        elif payload.kind == "staged":
            if not payload.staging_id:
                raise HTTPException(status_code=400, detail="staging_id is required")
            dataset = _file_as_sherpa(_resolve_staged_upload(payload.staging_id, current_user))
        else:
            raise HTTPException(status_code=400, detail="Unsupported matrix source")
        return _matrix_response(dataset, payload)
    except HTTPException:
        raise
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/upload/stage", dependencies=[Depends(demo_guard("data_upload"))])
async def stage_upload_file(
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Stage a local file for source-side preview before committing it to My Dataset."""
    user_id = current_user.id
    try:
        ensure_reader_available(file.filename or "")
    except (ImportError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    upload_reserved = reserve_demo_upload_quota_or_429(user_id)
    staging_id = uuid.uuid4().hex
    destination_dir = _staging_root(current_user) / staging_id
    saved_path: Path | None = None
    persisted = False
    try:
        saved_path = await save_upload_file(
            file,
            destination_dir=destination_dir,
            max_file_size_mb=settings.max_file_size_mb,
        )
        persisted = True
    except FileValidationError as exc:
        shutil.rmtree(destination_dir, ignore_errors=True)
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except BaseException:
        if saved_path is not None and saved_path.exists():
            saved_path.unlink()
        shutil.rmtree(destination_dir, ignore_errors=True)
        raise
    finally:
        if persisted:
            consume_reserved_demo_upload_quota_if_needed(user_id, upload_reserved)
        else:
            release_demo_upload_quota_reservation_if_needed(user_id, upload_reserved)
    return {
        "staging_id": staging_id,
        "filename": saved_path.name,
        "size_bytes": saved_path.stat().st_size,
    }


@router.delete("/upload/stage/{staging_id}", dependencies=[Depends(demo_guard("data_upload"))])
async def delete_staged_upload(
    staging_id: str,
    current_user: User = Depends(get_current_user),
) -> dict[str, str]:
    staged_path = _resolve_staged_upload(staging_id, current_user)
    shutil.rmtree(staged_path.parent, ignore_errors=True)
    return {"status": "deleted"}


@router.post("/upload/commit", dependencies=[Depends(demo_guard("data_upload"))])
async def commit_staged_uploads(
    payload: StagedUploadCommitRequest,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    user_id = current_user.id
    result = await session.execute(
        select(Experiment).where(Experiment.id == payload.experiment_id, Experiment.user_id == user_id)
    )
    experiment = result.scalar_one_or_none()
    if experiment is None:
        raise HTTPException(status_code=404, detail="Experiment not found")
    if payload.stage not in ALLOWED_STAGES:
        raise HTTPException(status_code=400, detail="Invalid stage")

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


@router.post("/file-info")
async def get_file_info(
    payload: FileInfoRequest,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> dict:
    """Inspect a file: load as SherpaDataset and return to_dict() format."""
    from spectra_sherpa.app.lib.adapters.scp_adapter import from_nddataset
    from spectra_sherpa.app.lib.io import load_csv_as_sherpa
    from spectra_sherpa.app.services.dag.serialize import _serialize_sherpa_dataset

    file_path = payload.file_path
    contents_file_count = 1
    contents_stage = "raw"
    contents_title: str | None = None
    if file_path is None:
        if payload.experiment_id is None:
            raise HTTPException(status_code=400, detail="Provide file_path or experiment_id")
        try:
            sd, files, contents_title, contents_stage = await _experiment_contents_as_sherpa(
                payload.experiment_id,
                session,
                current_user,
            )
            contents_file_count = len(files)
            result = _serialize_sherpa_dataset(sd, owner_user_id=current_user.id)
            data = result.get("data", [])
            if len(data) > 50:
                result["data"] = data[:50]
                y_axis = result.get("y_axis")
                if y_axis and y_axis.get("labels"):
                    result["y_axis"]["labels"] = y_axis["labels"][:50]
            metadata = result.setdefault("metadata", {})
            metadata["contents_file_count"] = contents_file_count
            metadata["contents_stage"] = contents_stage
            metadata["contents_title"] = contents_title
            return result
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    if payload.experiment_id is not None:
        stage_hint = Path(file_path).parts[0] if file_path else ""
        if stage_hint in ALLOWED_STAGES:
            contents_stage = stage_hint
        exp_dir = experiment_dir(payload.experiment_id)
        full_path = (exp_dir / file_path).resolve()
        file_path = str(full_path.relative_to(settings.data_dir))

    await _validate_file_path_ownership(file_path, session, current_user)

    resolved = service._resolve_payload_path(file_path)

    try:
        suffix = resolved.suffix.lower()
        if suffix == ".csv":
            sd = load_csv_as_sherpa(resolved)
        elif suffix == ".npz":
            # Synthesis writes its output as a SpectraSherpa-signed `.npz`
            # (X + wavenumber + recipe metadata) under the "synthetic" stage.
            # The generic `load_spectrum` dispatcher in lib/io raises
            # "Unsupported file format: .npz" because it only knows
            # SpectroChemPy-native binary formats; wire the synthetic-npz
            # reader in here so the magnifying glass works on every saved
            # synthetic dataset.
            sd = _load_synthetic_npz_as_sherpa(resolved)
        else:
            datasets = service._load_datasets_from_file({"file_path": file_path})
            if not datasets:
                raise ValueError("No spectra found in file")
            if len(datasets) > 1:
                from spectra_sherpa.app.lib.io import stack_datasets

                stacked = stack_datasets(datasets)
                sd = from_nddataset(stacked)
            else:
                sd = from_nddataset(datasets[0])

        result = _serialize_sherpa_dataset(sd, owner_user_id=current_user.id)

        # Cap traces at 50 (same as overlay in NodeDetailView)
        data = result.get("data", [])
        if len(data) > 50:
            result["data"] = data[:50]
            y_axis = result.get("y_axis")
            if y_axis and y_axis.get("labels"):
                result["y_axis"]["labels"] = y_axis["labels"][:50]

        # Apply persisted user overrides
        overrides = load_prepared_data_overrides(file_path=file_path)
        result = apply_serialized_prepared_data_overrides(result, overrides)
        metadata = result.setdefault("metadata", {})
        metadata["contents_file_count"] = contents_file_count
        metadata["contents_stage"] = contents_stage

        return result

    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.patch("/file-metadata")
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


@router.post("/blend", response_model=BlendResponse)
async def blend_spectra(
    payload: BlendRequest,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> BlendResponse:
    # Validate user has access to all file paths in species
    await _validate_payload_file_paths(payload.species, session, current_user)

    try:
        result = service.synthesize_spectra(
            species=[item.model_dump() for item in payload.species],
            concentrations=payload.concentration_timeseries,
            settings_dict=payload.settings,
            pathlength_m=payload.pathlength_m,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    # Extract data from NDDataset
    # blend_datasets returns NDDataset with:
    #   - x: wavenumber axis
    #   - y: time axis
    #   - data: absorbance matrix (n_times, n_wavenumbers)
    try:
        x_coord = result.x
    except (KeyError, AttributeError):
        x_coord = None
    try:
        y_coord = result.y
    except (KeyError, AttributeError):
        y_coord = None
    wavenumbers = x_coord.data.tolist() if x_coord is not None else []
    times = y_coord.data.tolist() if y_coord is not None else list(range(result.shape[0]))

    # Transpose: blend_datasets stores as (n_times, n_wn), BlendResponse expects (n_wn, n_times)
    absorbance_matrix = result.data.T.tolist()

    # Compute statistics
    statistics = {
        "min": float(np.min(result.data)),
        "max": float(np.max(result.data)),
        "mean": float(np.mean(result.data)),
        "std": float(np.std(result.data)),
    }

    return BlendResponse(
        status="ok",
        wavenumbers=wavenumbers,
        times=times,
        absorbance_matrix=absorbance_matrix,
        statistics=statistics,
    )


@router.get("/curves/default", response_model=CurveDefaultsResponse)
async def get_default_curves() -> CurveDefaultsResponse:
    points, segments = service.generate_curves(11)
    return CurveDefaultsResponse(
        curvePoints=points,
        curveSegments=segments,
        curveDefaultCount=11,
        curveSamplesPerSegment=80,
        curveSourceLabel="Seed Curve",
    )


@router.post("/curves/generate", response_model=CurvePointsResponse)
async def generate_curve_points(payload: CurvePointsRequest) -> CurvePointsResponse:
    points, segments = service.generate_curves(payload.count)
    return CurvePointsResponse(points=points, segments=segments)


# ═══════════════════════════════════════════════════════════════════════════════
# NEW SEPARATED ENDPOINTS: Concentration Generation + Spectral Synthesis
# ═══════════════════════════════════════════════════════════════════════════════


@router.post("/concentrations/generate", response_model=ConcentrationGenerateResponse)
async def generate_concentrations(payload: ConcentrationGenerateRequest) -> ConcentrationGenerateResponse:
    """
    Generate concentration curves for multiple species.

    This endpoint handles ONLY concentration generation - no spectral computation.
    Use /synthesize to apply these concentrations to species spectra.

    Supported curve types:
    - sigmoid: S-curve with configurable center and width
    - gaussian: Bell curve with configurable center and width
    - linear: Linear ramp from 0 to max_concentration
    - exponential: Exponential rise with configurable width
    - step: Step function at configurable center
    - constant: Flat line at max_concentration
    - catmull_rom: Smooth spline through control points
    """
    try:
        times, concentrations = service.generate_concentrations(
            curve_specs=[spec.model_dump() for spec in payload.curves],
            n_points=payload.n_points,
            time_min=payload.time_min,
            time_max=payload.time_max,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return ConcentrationGenerateResponse(
        status="ok",
        times=times.tolist(),
        time_unit=payload.time_unit,
        concentrations={label: conc.tolist() for label, conc in concentrations.items()},
        metadata={
            "n_species": len(concentrations),
            "n_points": payload.n_points,
            "time_range": [payload.time_min, payload.time_max],
        },
    )


@router.post("/synthesize", response_model=SynthesizeResponse)
async def synthesize_spectra(
    payload: SynthesizeRequest,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> SynthesizeResponse:
    """
    Synthesize blended spectra from species and concentration profiles.

    This endpoint handles ONLY spectral synthesis - it consumes pre-generated
    concentrations and produces absorbance spectra using calibration models.

    Use /concentrations/generate first to create the concentration profiles.
    """
    # Validate user has access to all file paths in species
    await _validate_payload_file_paths(payload.species, session, current_user)

    try:
        result = service.synthesize_spectra(
            species=[item.model_dump() for item in payload.species],
            concentrations=payload.concentrations,
            settings_dict=payload.settings,
            pathlength_m=payload.pathlength_m,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    # Extract data from NDDataset
    try:
        x_coord = result.x
    except (KeyError, AttributeError):
        x_coord = None
    try:
        y_coord = result.y
    except (KeyError, AttributeError):
        y_coord = None
    wavenumbers = x_coord.data.tolist() if x_coord is not None else []
    times = y_coord.data.tolist() if y_coord is not None else list(range(result.shape[0]))

    # Transpose: blend_datasets stores as (n_times, n_wn), response expects (n_wn, n_times)
    absorbance_matrix = result.data.T.tolist()

    # Compute statistics
    statistics = {
        "min": float(np.min(result.data)),
        "max": float(np.max(result.data)),
        "mean": float(np.mean(result.data)),
        "std": float(np.std(result.data)),
    }

    # Extract ground truth if available
    ground_truth = result.meta.get("blend_ground_truth") if hasattr(result, "meta") else None

    return SynthesizeResponse(
        status="ok",
        wavenumbers=wavenumbers,
        times=times,
        absorbance_matrix=absorbance_matrix,
        statistics=statistics,
        ground_truth=ground_truth,
    )


# ═══════════════════════════════════════════════════════════════════════════════
# Reference Dataset Catalog
# ═══════════════════════════════════════════════════════════════════════════════


@router.get("/reference-datasets")
async def list_reference_datasets() -> dict[str, list[dict[str, Any]]]:
    """List all available reference datasets across all sources."""
    from spectra_sherpa.app.lib.eigenvector import DATASET_CATALOG
    from spectra_sherpa.app.lib.oes_datasets import OES_CATALOG
    from spectra_sherpa.app.lib.scp_catalog import build_scp_catalog
    from spectra_sherpa.app.lib.sklearn_info import SKLEARN_CATALOG
    from spectra_sherpa.app.lib.synthetic_references import SYNTHETIC_REFERENCE_CATALOG

    # Note: `data_role` must be set on every entry — the wizard frontend
    # filter (`TemplateWizardModal.compatibleExampleDatasetsForNode`) uses
    # it to pass feature-tables through on dual-mode templates (PCA, PLS-DA,
    # KNN, SIMCA, HCA, Spectral Decomposition) that declare
    # `accepted_data_roles: [X_spectra, X_features]`. Without the field the
    # role-match short-circuits to false and sklearn:wine/iris stay
    # hidden even though the backend matching-datasets endpoint returns them.
    return {
        "synthetic": [
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
                "has_embedded_target": True,
                "target_type": v.get("target_type") or "continuous",
            }
            for k, v in SYNTHETIC_REFERENCE_CATALOG.items()
        ],
        "eigenvector": [
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
            }
            for k, v in DATASET_CATALOG.items()
        ],
        "oes": [
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
        ],
        "sklearn": [
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
                "task_type": v.get("task_type"),
            }
            for k, v in SKLEARN_CATALOG.items()
        ],
        "spectrochempy": [
            {
                "name": entry["name"],
                "source": "spectrochempy",
                "label": entry["label"],
                "technique": entry["technique"],
                "is_spectra": infer_is_spectra(technique=entry.get("technique")),
                "data_role": "X_spectra",
                "description": entry["description"],
                "category": entry["category"],
                "file_path": entry["file_path"],
                "files": entry.get("files", []),
                "file_count": entry["file_count"],
                "entry_type": entry["entry_type"],
                "has_embedded_target": False,
                "target_type": None,
            }
            for entry in build_scp_catalog()
        ],
    }


@router.get("/reference-datasets/{source}/{name:path}")
async def get_reference_dataset_info(source: str, name: str) -> dict[str, Any]:
    """Get full metadata + statistics for a reference dataset."""
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
        from spectra_sherpa.app.lib.eigenvector import DATASET_CATALOG, get_dataset_info

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

    elif source == "spectrochempy":
        from spectra_sherpa.app.lib.scp_catalog import get_scp_dataset_info

        try:
            info = get_scp_dataset_info(name)
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

    return info
