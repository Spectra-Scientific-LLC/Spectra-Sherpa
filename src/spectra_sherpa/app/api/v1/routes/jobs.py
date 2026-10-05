from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from spectra_sherpa.app.api.deps import get_current_user, get_session
from spectra_sherpa.app.contracts.scientific_access import require_scientific_access, scientific_project_ids
from spectra_sherpa.app.models.background_job import BackgroundJob
from spectra_sherpa.app.models.execution_run import ExecutionRun
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
    project_ids = await scientific_project_ids(session, current_user.id)
    if project_ids is not None:
        # A job is personal status history, but run-linked messages/paths must
        # not reveal a project's work after its commercial access is revoked.
        visible_runs = select(ExecutionRun.id).where(ExecutionRun.project_id.in_(project_ids))
        query = query.where(
            or_(BackgroundJob.execution_run_id.is_(None), BackgroundJob.execution_run_id.in_(visible_runs))
        )
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
    await _require_job_run_access(session, current_user.id, job, "read")
    return JobInfo.model_validate(job)


async def _require_job_run_access(session, user_id, job, operation):
    if job.execution_run_id is not None:
        run = await session.get(ExecutionRun, job.execution_run_id)
        if run is None:
            raise HTTPException(404, "Job not found")
        await require_scientific_access(session, user_id, run.project_id, operation, resource_owner_id=run.user_id)


@router.delete("/{job_id}", status_code=status.HTTP_204_NO_CONTENT)
async def cancel_job(
    job_id: int,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """Cancel a job for the authenticated user."""
    job = await session.scalar(
        select(BackgroundJob).where(BackgroundJob.id == job_id, BackgroundJob.user_id == current_user.id)
    )
    if job is None:
        raise HTTPException(404, "Job not found")
    await _require_job_run_access(session, current_user.id, job, "write")
    if not await job_manager.cancel_job(session, job_id, user_id=current_user.id):
        raise HTTPException(status_code=404, detail="Job not found")
