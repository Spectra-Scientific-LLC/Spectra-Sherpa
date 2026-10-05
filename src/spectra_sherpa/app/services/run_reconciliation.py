"""Reconcile interrupted job-backed runs without rewriting terminal evidence."""

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from spectra_sherpa.app.models.background_job import BackgroundJob
from spectra_sherpa.app.models.execution_run import ExecutionRun


async def reconcile_job_runs(session: AsyncSession, *, job_id: int | None = None) -> None:
    for job_status, run_status in (("failed", "failed"), ("cancelled", "cancelled"), ("completed", "failed")):
        jobs = select(BackgroundJob.execution_run_id).where(
            BackgroundJob.status == job_status,
            BackgroundJob.execution_run_id.is_not(None),
        )
        if job_id is not None:
            jobs = jobs.where(BackgroundJob.id == job_id)
        reason = (
            "Background job completed without finalizing its run evidence."
            if job_status == "completed"
            else f"Background job {job_status} before the run was finalized. Inspect the linked job for details."
        )
        await session.execute(
            update(ExecutionRun)
            .where(ExecutionRun.id.in_(jobs), ExecutionRun.status.in_(("pending", "running")))
            .values(status=run_status, error=reason)
        )
