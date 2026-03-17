from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import numpy as np
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from spectra_sherpa.app.api.deps import get_current_user, get_session
from spectra_sherpa.app.core.config import settings
from spectra_sherpa.app.lib.domain_flags import infer_is_spectra
from spectra_sherpa.app.models.calibration import Calibration
from spectra_sherpa.app.models.experiment import Experiment
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
from spectra_sherpa.app.services.experiments import experiment_dir
from spectra_sherpa.app.services.prepared_data import (
    PreparedDataOverrides,
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
    file_path: str
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
    if payload.experiment_id is not None:
        exp_dir = experiment_dir(payload.experiment_id)
        full_path = (exp_dir / file_path).resolve()
        file_path = str(full_path.relative_to(settings.data_dir))

    await _validate_file_path_ownership(file_path, session, current_user)

    resolved = service._resolve_payload_path(file_path)

    try:
        if resolved.suffix.lower() == ".csv":
            sd = load_csv_as_sherpa(resolved)
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

        result = _serialize_sherpa_dataset(sd)

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
        if payload.experiment_id is not None:
            exp_dir = experiment_dir(payload.experiment_id)
            full_path = (exp_dir / file_path).resolve()
            file_path = str(full_path.relative_to(settings.data_dir))
        await _validate_file_path_ownership(file_path, session, current_user)
        save_prepared_data_overrides(overrides, file_path=file_path)
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

    return {
        "eigenvector": [
            {
                "name": k,
                "source": "eigenvector",
                "label": v["label"],
                "technique": v["technique"],
                "is_spectra": infer_is_spectra(technique=v.get("technique"), x_units=v.get("x_units")),
                "description": v["description"],
                "featured": v.get("featured", False),
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
                "description": v["description"],
                "featured": v.get("featured", False),
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
                "description": entry["description"],
                "category": entry["category"],
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
    if source == "eigenvector":
        from spectra_sherpa.app.lib.eigenvector import DATASET_CATALOG, get_dataset_info

        if name not in DATASET_CATALOG:
            raise HTTPException(404, f"Dataset '{name}' not found")
        info = get_dataset_info(name)

    elif source == "sklearn":
        from spectra_sherpa.app.lib.sklearn_info import SKLEARN_CATALOG, get_sklearn_dataset_info

        if name not in SKLEARN_CATALOG:
            raise HTTPException(404, f"Dataset '{name}' not found")
        info = get_sklearn_dataset_info(name)

    elif source == "oes":
        from spectra_sherpa.app.lib.oes_datasets import OES_CATALOG, get_oes_dataset_info

        if name not in OES_CATALOG:
            raise HTTPException(404, f"Dataset '{name}' not found")
        info = get_oes_dataset_info(name)

    elif source == "spectrochempy":
        from spectra_sherpa.app.lib.scp_catalog import get_scp_dataset_info

        try:
            info = get_scp_dataset_info(name)
        except ValueError:
            raise HTTPException(404, f"Dataset '{name}' not found")
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
