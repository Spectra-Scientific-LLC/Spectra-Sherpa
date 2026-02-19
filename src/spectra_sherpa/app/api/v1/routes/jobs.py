from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from spectra_sherpa.app.api.deps import get_current_user, get_session
from spectra_sherpa.app.models.background_job import BackgroundJob
from spectra_sherpa.app.models.user import User
from spectra_sherpa.app.schemas.jobs import JobInfo
from spectra_sherpa.app.services.job_manager import job_manager

router = APIRouter(prefix="/jobs")


@router.get("", response_model=list[JobInfo])
async def list_jobs(
    status_filter: str | None = Query(default=None, alias="status"),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> list[JobInfo]:
    """List jobs for the authenticated user."""
    query = select(BackgroundJob).where(BackgroundJob.user_id == current_user.id)
    if status_filter:
        query = query.where(BackgroundJob.status == status_filter)
    query = query.order_by(BackgroundJob.created_at.desc()).limit(limit).offset(offset)
    result = await session.execute(query)
    return [JobInfo.model_validate(job) for job in result.scalars()]


@router.get("/{job_id}", response_model=JobInfo)
async def get_job(
    job_id: int,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> JobInfo:
    """Get a specific job for the authenticated user."""
    result = await session.execute(
        select(BackgroundJob).where(BackgroundJob.id == job_id).where(BackgroundJob.user_id == current_user.id)
    )
    job = result.scalar_one_or_none()
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return JobInfo.model_validate(job)


@router.delete("/{job_id}", status_code=status.HTTP_204_NO_CONTENT)
async def cancel_job(
    job_id: int,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """Cancel a job for the authenticated user."""
    result = await session.execute(
        select(BackgroundJob).where(BackgroundJob.id == job_id).where(BackgroundJob.user_id == current_user.id)
    )
    job = result.scalar_one_or_none()
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    await job_manager.cancel_job(session, job_id)
