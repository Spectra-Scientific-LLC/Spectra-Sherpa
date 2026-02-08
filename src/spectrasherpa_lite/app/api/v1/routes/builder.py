from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import numpy as np
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_session
from app.core.config import settings
from app.models.calibration import Calibration
from app.models.experiment import Experiment
from app.models.nist_library import NistLibrary
from app.models.user import User
from app.schemas.builder import (
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
from app.services.builder import BuilderService

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
            result = await session.execute(
                select(Experiment).where(Experiment.id == experiment_id)
            )
            experiment = result.scalar_one_or_none()
            if not experiment or experiment.user_id != current_user.id:
                raise HTTPException(status_code=403, detail="Access denied: experiment not owned by user")
            return  # Access granted

    # Check NIST library directory
    if parts[0] == "nist_library":
        # Allow access to shared 'downloaded' folder (public NIST data)
        if len(parts) >= 2 and parts[1] == "downloaded":
            return  # Access granted - shared NIST downloads

        # For other nist_library paths, check if it matches a user-owned entry
        result = await session.execute(
            select(NistLibrary)
            .where(NistLibrary.user_id == current_user.id)
            .where(NistLibrary.file_path.contains(str(rel_path)))
        )
        if result.scalar_one_or_none():
            return  # Access granted - user owns this library entry

        raise HTTPException(status_code=403, detail="Access denied: NIST library entry not owned by user")

    # Check calibrations directory (user-specific, pattern: calibrations/cal_XXX/)
    if parts[0] == "calibrations" and len(parts) >= 2:
        # Extract calibration ID from cal_XXX format
        cal_dir_match = re.match(r"cal_(\d+)", parts[1])
        if cal_dir_match:
            calibration_id = int(cal_dir_match.group(1))
            result = await session.execute(
                select(Calibration).where(Calibration.id == calibration_id)
            )
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


class FileInfoResponse(BaseModel):
    status: str
    num_spectra: int
    num_wavenumbers: int
    wavenumber_min: float | None
    wavenumber_max: float | None
    absorbance_min: float | None
    absorbance_max: float | None
    labels: list[str]
    source: str


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


@router.post("/file-info", response_model=FileInfoResponse)
async def get_file_info(
    payload: FileInfoRequest,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> FileInfoResponse:
    """Get basic info about a spectral file without preprocessing."""
    # Validate user has access to this file path
    await _validate_file_path_ownership(payload.file_path, session, current_user)

    try:
        datasets = service._load_datasets_from_file({"file_path": payload.file_path})
        if not datasets:
            raise ValueError("No spectra found in file")

        # Compute stats across all spectra
        all_wavenumbers = []
        all_absorbances = []
        for ds in datasets:
            try:
                x_coord = ds.x
            except (KeyError, AttributeError):
                x_coord = None
            if x_coord is not None:
                all_wavenumbers.append(x_coord.data)
            else:
                all_wavenumbers.append(np.arange(ds.shape[-1]))
            all_absorbances.append(ds.data.flatten())

        wn_min = float(min(w.min() for w in all_wavenumbers))
        wn_max = float(max(w.max() for w in all_wavenumbers))
        abs_min = float(min(a.min() for a in all_absorbances))
        abs_max = float(max(a.max() for a in all_absorbances))

        # Extract labels
        labels = []
        for ds in datasets[:10]:
            label = ds.title if hasattr(ds, "title") and ds.title else "UNKNOWN"
            labels.append(label)

        # Get source type
        source = datasets[0].meta.get("source_type", "csv") if hasattr(datasets[0], "meta") else "csv"

        return FileInfoResponse(
            status="ok",
            num_spectra=len(datasets),
            num_wavenumbers=len(all_wavenumbers[0]),
            wavenumber_min=wn_min,
            wavenumber_max=wn_max,
            absorbance_min=abs_min,
            absorbance_max=abs_max,
            labels=labels,
            source=source,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/blend", response_model=BlendResponse)
async def blend_spectra(
    payload: BlendRequest,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> BlendResponse:
    # Validate user has access to all file paths in species
    await _validate_payload_file_paths(payload.species, session, current_user)

    try:
        result = service.blend(
            species=[item.model_dump() for item in payload.species],
            concentration_timeseries=payload.concentration_timeseries,
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
