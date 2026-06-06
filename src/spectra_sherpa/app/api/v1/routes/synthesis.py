from __future__ import annotations

import asyncio
from contextlib import suppress

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from spectra_sherpa.app.api.deps import get_current_user, get_session
from spectra_sherpa.app.core.config import app_config, settings
from spectra_sherpa.app.core.security import check_egress_permission
from spectra_sherpa.app.db.session import async_session
from spectra_sherpa.app.models.api_key import APIKey
from spectra_sherpa.app.models.background_job import BackgroundJob
from spectra_sherpa.app.models.data_egress import EgressDestination
from spectra_sherpa.app.models.user import User
from spectra_sherpa.app.schemas.synthesis import (
    SynthesisComponentSummary,
    SynthesisRequest,
    SynthesisResult,
    SynthesisSaveRequest,
    SynthesisSaveResponse,
    SynthesisSearchResponse,
    SynthesisSource,
    SynthesisSourcesResponse,
    SynthesisSpectrumLoadRequest,
    SynthesisSpectrumLoadResponse,
    SynthesisSpectrumResponse,
)
from spectra_sherpa.app.services import synthesis as synthesis_service
from spectra_sherpa.app.services.encryption import decrypt_value
from spectra_sherpa.app.services.job_manager import job_manager
from spectra_sherpa.app.services.rate_limiter import RateLimiter
from spectra_sherpa.app.services.synthesis import SynthesisError

router = APIRouter(prefix="/synthesis")
_nist_download_limiter = RateLimiter(
    max(settings.max_nist_downloads_per_hour, 1),
    3600,
    settings.data_dir / "rate_limits" / "nist_synthesis_downloads.json",
)
_HITRAN_SOURCES = {"hitran", "hitran_xsec"}


def _http_synthesis_error(exc: SynthesisError) -> HTTPException:
    return HTTPException(status_code=400, detail=str(exc))


async def _stored_api_key(session: AsyncSession, current_user: User, service_name: str) -> str | None:
    record = (
        await session.execute(
            select(APIKey).where(APIKey.user_id == current_user.id, APIKey.service_name == service_name).limit(1)
        )
    ).scalar_one_or_none()
    if record is None:
        return None
    return decrypt_value(record.key_encrypted)


def _enforce_nist_download_rate(current_user: User, *, cached: bool) -> None:
    if cached:
        return
    key = f"user:{current_user.id}:nist_quant_ir"
    if not _nist_download_limiter.allow(key):
        raise HTTPException(
            status_code=429,
            detail=(
                "NIST synthesis download rate limit exceeded. "
                f"Try again later or use cached spectra ({settings.max_nist_downloads_per_hour}/hour)."
            ),
        )


async def _check_synthesis_egress(
    current_user: User,
    permission: str,
    destination: str,
    session: AsyncSession,
) -> bool:
    # In local mode, the per-user Settings toggle is the explicit opt-in for
    # live source downloads.  Hybrid/enterprise deployments still honor the
    # global operator egress kill switch before per-user defaults.
    return await check_egress_permission(
        current_user,
        permission,
        destination=destination,
        session=session,
        skip_global_check=app_config.mode == "local",
    )


@router.get("/sources", response_model=SynthesisSourcesResponse)
async def list_synthesis_sources() -> SynthesisSourcesResponse:
    return SynthesisSourcesResponse(sources=synthesis_service.list_sources())


@router.get("/search", response_model=SynthesisSearchResponse)
async def search_synthesis_components(
    source: SynthesisSource = Query(...),
    query: str = Query("", max_length=100),
    limit: int = Query(25, ge=1, le=1000),
) -> SynthesisSearchResponse:
    try:
        components = synthesis_service.search_components(source, query, limit=limit)
    except SynthesisError as exc:
        raise _http_synthesis_error(exc) from exc
    return SynthesisSearchResponse(components=components)


@router.get("/component", response_model=SynthesisComponentSummary)
async def get_synthesis_component(
    source: SynthesisSource = Query(...),
    component_id: str = Query(..., min_length=1, max_length=120),
) -> SynthesisComponentSummary:
    try:
        return synthesis_service.get_component_summary(source, component_id)
    except SynthesisError as exc:
        raise _http_synthesis_error(exc) from exc


@router.get("/spectrum", response_model=SynthesisSpectrumResponse)
async def get_synthesis_spectrum(
    source: SynthesisSource = Query(...),
    component_id: str = Query(..., min_length=1, max_length=120),
    resolution_cm1: float | None = Query(default=None, gt=0),
    apodization: str | None = Query(default=None, max_length=80),
    wavenumber_min: float | None = Query(default=None),
    wavenumber_max: float | None = Query(default=None),
    temperature_k: float = Query(default=293.0, gt=0),
    pressure_atm: float = Query(default=1.0, gt=0),
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> SynthesisSpectrumResponse:
    if source == "nist_quant_ir":
        try:
            cached = synthesis_service.is_component_spectrum_cached(
                source,
                component_id,
                resolution_cm1=resolution_cm1,
                apodization=apodization,
                wavenumber_min=wavenumber_min,
                wavenumber_max=wavenumber_max,
            )
        except SynthesisError as exc:
            raise _http_synthesis_error(exc) from exc
        if not cached:
            allowed = await _check_synthesis_egress(
                current_user,
                "allow_nist_queries",
                destination=EgressDestination.NIST,
                session=session,
            )
            if not allowed:
                raise HTTPException(status_code=403, detail="NIST synthesis requires NIST egress permission")
        _enforce_nist_download_rate(current_user, cached=cached)
    hitran_api_key: str | None = None
    if source in _HITRAN_SOURCES:
        try:
            cached = synthesis_service.is_component_spectrum_cached(
                source,
                component_id,
                resolution_cm1=resolution_cm1,
                wavenumber_min=wavenumber_min,
                wavenumber_max=wavenumber_max,
                temperature_k=temperature_k,
                pressure_atm=pressure_atm,
            )
        except SynthesisError as exc:
            raise _http_synthesis_error(exc) from exc
        if not cached:
            allowed = await _check_synthesis_egress(
                current_user,
                "allow_hitran_queries",
                destination=EgressDestination.HITRAN,
                session=session,
            )
            if not allowed:
                raise HTTPException(status_code=403, detail="HITRAN synthesis requires HITRAN egress permission")
            hitran_api_key = await _stored_api_key(session, current_user, "hitran")
            if not hitran_api_key:
                raise HTTPException(
                    status_code=400,
                    detail="HITRAN synthesis requires a HITRAN API key. Add it in Settings > API Keys.",
                )
    try:
        return await synthesis_service.get_component_spectrum(
            source,
            component_id,
            resolution_cm1=resolution_cm1,
            apodization=apodization,
            wavenumber_min=wavenumber_min,
            wavenumber_max=wavenumber_max,
            temperature_k=temperature_k,
            pressure_atm=pressure_atm,
            hitran_api_key=hitran_api_key,
        )
    except httpx.HTTPStatusError as exc:
        raise HTTPException(status_code=502, detail="Source spectrum download failed") from exc
    except httpx.RequestError as exc:
        raise HTTPException(
            status_code=502,
            detail="Source spectrum download failed. Check outbound network access to the selected spectral source.",
        ) from exc
    except SynthesisError as exc:
        raise _http_synthesis_error(exc) from exc


@router.post("/spectrum/load", response_model=SynthesisSpectrumLoadResponse)
async def load_synthesis_spectrum(
    payload: SynthesisSpectrumLoadRequest,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> SynthesisSpectrumLoadResponse:
    """Return cached spectra immediately; queue uncached HITRAN downloads.

    HITRAN line fetches and absorption coefficient calculations can exceed
    reverse-proxy read timeouts. This endpoint gives the UI a short request
    path and moves uncached HITRAN work into the background job system.
    """

    if payload.source not in _HITRAN_SOURCES:
        try:
            spectrum = await get_synthesis_spectrum(
                source=payload.source,
                component_id=payload.component_id,
                resolution_cm1=payload.resolution_cm1,
                apodization=payload.apodization,
                wavenumber_min=payload.wavenumber_min,
                wavenumber_max=payload.wavenumber_max,
                temperature_k=payload.temperature_k,
                pressure_atm=payload.pressure_atm,
                session=session,
                current_user=current_user,
            )
        except HTTPException:
            raise
        return SynthesisSpectrumLoadResponse(spectrum=spectrum)

    try:
        cached = synthesis_service.is_component_spectrum_cached(
            payload.source,
            payload.component_id,
            resolution_cm1=payload.resolution_cm1,
            wavenumber_min=payload.wavenumber_min,
            wavenumber_max=payload.wavenumber_max,
            temperature_k=payload.temperature_k,
            pressure_atm=payload.pressure_atm,
        )
    except SynthesisError as exc:
        raise _http_synthesis_error(exc) from exc

    if cached:
        try:
            spectrum = await synthesis_service.get_component_spectrum(
                payload.source,
                payload.component_id,
                resolution_cm1=payload.resolution_cm1,
                wavenumber_min=payload.wavenumber_min,
                wavenumber_max=payload.wavenumber_max,
                temperature_k=payload.temperature_k,
                pressure_atm=payload.pressure_atm,
            )
        except SynthesisError as exc:
            raise _http_synthesis_error(exc) from exc
        return SynthesisSpectrumLoadResponse(spectrum=spectrum)

    allowed = await _check_synthesis_egress(
        current_user,
        "allow_hitran_queries",
        destination=EgressDestination.HITRAN,
        session=session,
    )
    if not allowed:
        raise HTTPException(status_code=403, detail="HITRAN synthesis requires HITRAN egress permission")
    hitran_api_key = await _stored_api_key(session, current_user, "hitran")
    if not hitran_api_key:
        raise HTTPException(
            status_code=400,
            detail="HITRAN synthesis requires a HITRAN API key. Add it in Settings > API Keys.",
        )

    try:
        summary = synthesis_service.get_component_summary(payload.source, payload.component_id)
        label = summary.name
    except SynthesisError:
        label = payload.component_id
    job = BackgroundJob(
        user_id=current_user.id,
        job_type="synthesis_hitran_spectrum",
        status="pending",
        progress_message=f"HITRAN spectrum queued: {label}",
    )
    session.add(job)
    await session.commit()
    await session.refresh(job)
    job_id = job.id

    async def _work() -> None:
        await _run_hitran_spectrum_load_job(
            job_id=job_id,
            source=payload.source,
            component_id=payload.component_id,
            resolution_cm1=payload.resolution_cm1,
            wavenumber_min=payload.wavenumber_min,
            wavenumber_max=payload.wavenumber_max,
            temperature_k=payload.temperature_k,
            pressure_atm=payload.pressure_atm,
            hitran_api_key=hitran_api_key,
            label=label,
        )

    asyncio.create_task(job_manager.run_job(job_id, _work))
    return SynthesisSpectrumLoadResponse(
        queued=True,
        job_id=job_id,
        message=f"HITRAN spectrum queued: {label}",
    )


async def _run_hitran_spectrum_load_job(
    *,
    job_id: int,
    source: SynthesisSource,
    component_id: str,
    resolution_cm1: float | None,
    wavenumber_min: float | None,
    wavenumber_max: float | None,
    temperature_k: float,
    pressure_atm: float,
    hitran_api_key: str,
    label: str,
) -> None:
    async with async_session() as progress_session:
        await job_manager.update_progress(progress_session, job_id, 5, f"Loading HITRAN spectrum: {label}")
    progress_task = asyncio.create_task(_tick_hitran_spectrum_load_progress(job_id, label))
    try:
        await synthesis_service.get_component_spectrum(
            source,
            component_id,
            resolution_cm1=resolution_cm1,
            wavenumber_min=wavenumber_min,
            wavenumber_max=wavenumber_max,
            temperature_k=temperature_k,
            pressure_atm=pressure_atm,
            hitran_api_key=hitran_api_key,
        )
    finally:
        progress_task.cancel()
        with suppress(asyncio.CancelledError):
            await progress_task
    async with async_session() as done_session:
        await job_manager.update_progress(done_session, job_id, 99, f"HITRAN spectrum cached: {label}")


async def _tick_hitran_spectrum_load_progress(job_id: int, label: str) -> None:
    elapsed = 0
    while True:
        await asyncio.sleep(5)
        elapsed += 5
        progress = min(90, 5 + (elapsed // 5) * 2)
        async with async_session() as session:
            await job_manager.update_progress(
                session,
                job_id,
                progress,
                f"Fetching HITRAN data and computing spectrum: {label}",
            )


@router.post("/preview", response_model=SynthesisResult)
async def preview_synthesis(
    payload: SynthesisRequest,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> SynthesisResult:
    try:
        return synthesis_service.truncate_result_for_response(synthesis_service.synthesize(payload))
    except SynthesisError as exc:
        raise _http_synthesis_error(exc) from exc


@router.post("/synthesize", response_model=SynthesisResult)
async def synthesize(
    payload: SynthesisRequest,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> SynthesisResult:
    try:
        return synthesis_service.truncate_result_for_response(synthesis_service.synthesize(payload))
    except SynthesisError as exc:
        raise _http_synthesis_error(exc) from exc


@router.post("/save", response_model=SynthesisSaveResponse)
async def save_synthesis(
    payload: SynthesisSaveRequest,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> SynthesisSaveResponse:
    try:
        response = await synthesis_service.save_synthesis_result(session, current_user, payload)
        response.result = synthesis_service.truncate_result_for_response(response.result)
        return response
    except SynthesisError as exc:
        raise _http_synthesis_error(exc) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
