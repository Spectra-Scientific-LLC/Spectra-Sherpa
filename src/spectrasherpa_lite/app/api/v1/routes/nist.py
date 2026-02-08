from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_session
from app.core.config import settings
from app.models.user import User
from app.db.session import async_session
from app.models.background_job import BackgroundJob
from app.schemas.nist import (
    NistDownloadRequest,
    NistDownloadResponse,
    NistLibraryEntry,
    NistSearchResult,
    NistSpectrumData,
)
from app.services.job_manager import job_manager
from app.services.nist import NISTService
from app.services.rate_limiter import RateLimiter

router = APIRouter(prefix="/nist")

# Per-user rate limiting for NIST requests (search + download)
# More lenient than LLM since NIST queries are cheaper
_nist_rate_limiter = RateLimiter(
    max_calls=settings.max_llm_requests_per_hour * 2,  # 2x LLM limit
    period_sec=3600,
    state_path=settings.data_dir / "nist_rate_limits.json",
)


def _check_nist_rate_limit(user: User) -> None:
    """Check and enforce per-user NIST rate limiting."""
    user_key = f"user_{user.id}" if user.id else "anonymous"
    if not _nist_rate_limiter.allow(user_key):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="NIST rate limit exceeded. Try again later.",
            headers={"Retry-After": "3600"},
        )


@router.get("/search", response_model=list[NistSearchResult])
async def search_nist(
    query: str = Query(..., min_length=1),
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> list[NistSearchResult]:
    _check_nist_rate_limit(current_user)
    service = NISTService(session, user=current_user)
    results = await service.search(query)
    return [NistSearchResult(**item) for item in results]


@router.post("/download", response_model=NistDownloadResponse)
async def download_nist(
    payload: NistDownloadRequest,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> NistDownloadResponse:
    _check_nist_rate_limit(current_user)
    # Check egress permission before queueing the job
    service = NISTService(session, user=current_user)
    service._check_nist_egress()

    user_id = current_user.id
    job = BackgroundJob(
        user_id=user_id,
        job_type="nist_download",
        status="pending",
        progress=0,
        compute_location="nist_api",
        compute_node="webbook.nist.gov",
        created_at=datetime.now(timezone.utc),
    )
    session.add(job)
    await session.commit()
    await session.refresh(job)

    asyncio.create_task(
        _run_download_job(
            job.id,
            payload.cas_number,
            payload.compound_name,
            payload.resolution,
            payload.index,
        )
    )
    return NistDownloadResponse(status="queued", job_id=job.id)


@router.get("/library", response_model=list[NistLibraryEntry])
async def list_library(
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> list[NistLibraryEntry]:
    # Library listing doesn't require egress (data is already local)
    service = NISTService(session, user=current_user)
    entries = await service.list_library(limit=limit, offset=offset)
    return [NistLibraryEntry.model_validate(entry) for entry in entries]


@router.get("/library/{library_id}/spectrum", response_model=NistSpectrumData)
async def get_spectrum_data(
    library_id: int,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> NistSpectrumData:
    """
    Parse and return spectrum data from a JCAMP-DX file for plotting.
    Returns wavenumbers and intensities arrays (from local files, no egress).
    """
    service = NISTService(session, user=current_user)
    spectrum_data = await service.parse_jcamp_spectrum(library_id)
    return NistSpectrumData(**spectrum_data)


async def _run_download_job(
    job_id: int,
    cas_number: str,
    compound_name: str | None,
    resolution: str | None,
    index: int | None,
) -> None:
    async with async_session() as session:
        service = NISTService(session)

        async def work() -> None:
            entry = await service.download(
                cas_number=cas_number,
                compound_name=compound_name,
                resolution=resolution,
                index=index,
            )
            await session.execute(
                update(BackgroundJob)
                .where(BackgroundJob.id == job_id)
                .values(result_path=entry.file_path)
            )
            await session.commit()

        await job_manager.run_job(session, job_id, work)
