from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_session
from app.core.config import settings
from app.models.user import User
from app.db.session import async_session
from app.models.background_job import BackgroundJob
from app.models.cal_model import CalModel
from app.schemas.calibrations import (
    CalModelInfo,
    CalibrationCreate,
    CalibrationDetail,
    CalibrationFileOut,
    CalibrationFitRequest,
    CalibrationFitResponse,
    CalibrationSummary,
)
from app.services.calibrations import (
    add_measurement,
    calibration_dir,
    create_calibration,
    fit_model,
    get_active_model,
    get_calibration,
    list_calibrations,
    list_measurements,
    list_models,
    read_metadata,
)
from app.services.file_storage import FileValidationError, save_upload_file
from app.services.job_manager import job_manager

router = APIRouter(prefix="/calibrations")


@router.get("", response_model=list[CalibrationSummary])
async def list_calibrations_endpoint(
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> list[CalibrationSummary]:
    """List calibrations for the authenticated user."""
    calibrations = await list_calibrations(session, user_id=current_user.id)
    return [CalibrationSummary.model_validate(cal) for cal in calibrations]


@router.post("", response_model=CalibrationDetail, status_code=201)
async def create_calibration_endpoint(
    payload: CalibrationCreate,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> CalibrationDetail:
    """Create a calibration for the authenticated user."""
    calibration = await create_calibration(
        session,
        user_id=current_user.id,
        compound_name=payload.compound_name,
        concentration_mode=payload.concentration_mode,
        x_unit=payload.x_unit,
        pathlength_m=payload.pathlength_m,
        metadata=payload.metadata,
    )
    metadata = read_metadata(calibration_dir(calibration.id) / "metadata.json")
    return CalibrationDetail(
        **CalibrationSummary.model_validate(calibration).model_dump(), metadata=metadata
    )


@router.get("/{calibration_id}", response_model=CalibrationDetail)
async def get_calibration_endpoint(
    calibration_id: int,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> CalibrationDetail:
    """Get a calibration for the authenticated user."""
    calibration = await get_calibration(session, calibration_id)
    if calibration is None:
        raise HTTPException(status_code=404, detail="Calibration not found")
    # Ownership check
    if calibration.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Calibration not found")
    metadata = read_metadata(calibration_dir(calibration.id) / "metadata.json")
    return CalibrationDetail(
        **CalibrationSummary.model_validate(calibration).model_dump(), metadata=metadata
    )


@router.post("/{calibration_id}/measurements", response_model=CalibrationFileOut, status_code=201)
async def upload_measurement_file(
    calibration_id: int,
    concentration: float = Form(...),
    file: UploadFile = File(...),
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> CalibrationFileOut:
    """Upload a measurement file for a calibration owned by the authenticated user."""
    calibration = await get_calibration(session, calibration_id)
    if calibration is None:
        raise HTTPException(status_code=404, detail="Calibration not found")
    # Ownership check
    if calibration.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Calibration not found")

    destination_dir = calibration_dir(calibration_id) / "raw_measurements"
    try:
        saved_path = await save_upload_file(
            file,
            destination_dir=destination_dir,
            max_file_size_mb=settings.max_file_size_mb,
        )
    except FileValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    relative_path = saved_path.relative_to(settings.data_dir).as_posix()
    measurement = await add_measurement(
        session,
        calibration_id=calibration_id,
        file_path=relative_path,
        concentration=concentration,
    )
    return CalibrationFileOut.model_validate(measurement)


@router.get("/{calibration_id}/measurements", response_model=list[CalibrationFileOut])
async def list_measurements_endpoint(
    calibration_id: int,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> list[CalibrationFileOut]:
    """List measurements for a calibration owned by the authenticated user."""
    calibration = await get_calibration(session, calibration_id)
    if calibration is None:
        raise HTTPException(status_code=404, detail="Calibration not found")
    # Ownership check
    if calibration.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Calibration not found")
    measurements = await list_measurements(session, calibration_id)
    return [CalibrationFileOut.model_validate(item) for item in measurements]


@router.post("/{calibration_id}/fit", response_model=CalibrationFitResponse)
async def fit_calibration_endpoint(
    calibration_id: int,
    payload: CalibrationFitRequest,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> CalibrationFitResponse:
    """Fit a calibration model for the authenticated user."""
    calibration = await get_calibration(session, calibration_id)
    if calibration is None:
        raise HTTPException(status_code=404, detail="Calibration not found")
    # Ownership check
    if calibration.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Calibration not found")
    if payload.model_type not in {"linear", "saturation", "hybrid"}:
        raise HTTPException(status_code=400, detail="Invalid model_type")

    job = BackgroundJob(
        user_id=current_user.id,
        job_type="calibration_fit",
        status="pending",
        progress=0,
        compute_location="local",
        compute_node="localhost",
        created_at=datetime.now(timezone.utc),
    )
    session.add(job)
    await session.commit()
    await session.refresh(job)

    asyncio.create_task(
        _run_fit_job(job.id, calibration_id, payload.model_type, payload.settings, payload.version_name)
    )

    return CalibrationFitResponse(status="queued", job_id=job.id)


@router.get("/{calibration_id}/models", response_model=list[CalModelInfo])
async def list_models_endpoint(
    calibration_id: int,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> list[CalModelInfo]:
    """List models for a calibration owned by the authenticated user."""
    calibration = await get_calibration(session, calibration_id)
    if calibration is None:
        raise HTTPException(status_code=404, detail="Calibration not found")
    # Ownership check
    if calibration.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Calibration not found")
    models = await list_models(session, calibration_id)
    return [CalModelInfo.model_validate(model) for model in models]


@router.put("/{calibration_id}/models/{model_id}/activate", response_model=CalModelInfo)
async def activate_model_endpoint(
    calibration_id: int,
    model_id: int,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> CalModelInfo:
    """Activate a model for a calibration owned by the authenticated user."""
    calibration = await get_calibration(session, calibration_id)
    if calibration is None or calibration.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Calibration not found")
    try:
        model = await _activate_model(session, calibration_id, model_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return CalModelInfo.model_validate(model)


@router.get("/{calibration_id}/models/active", response_model=CalModelInfo)
async def get_active_model_endpoint(
    calibration_id: int,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> CalModelInfo:
    """Get active model for a calibration owned by the authenticated user."""
    calibration = await get_calibration(session, calibration_id)
    if calibration is None or calibration.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Calibration not found")
    model = await get_active_model(session, calibration_id)
    if model is None:
        raise HTTPException(status_code=404, detail="Active model not found")
    return CalModelInfo.model_validate(model)


async def _activate_model(
    session: AsyncSession, calibration_id: int, model_id: int
) -> CalModel:
    from app.services.calibrations import activate_model

    return await activate_model(session, calibration_id, model_id)


async def _run_fit_job(
    job_id: int,
    calibration_id: int,
    model_type: str,
    settings_dict: dict,
    version_name: str | None,
) -> None:
    async with async_session() as session:
        async def work() -> None:
            calibration = await get_calibration(session, calibration_id)
            if calibration is None:
                raise ValueError("Calibration not found")
            model = await fit_model(
                session,
                calibration=calibration,
                model_type=model_type,
                settings_dict=settings_dict,
                version_name=version_name,
            )
            await session.execute(
                update(BackgroundJob)
                .where(BackgroundJob.id == job_id)
                .values(result_path=model.model_path)
            )
            await session.commit()

        await job_manager.run_job(session, job_id, work)
