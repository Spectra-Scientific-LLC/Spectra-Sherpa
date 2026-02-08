from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Awaitable, Callable

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.session import async_session
from app.models.background_job import BackgroundJob
from app.services.websocket_manager import ws_manager


class JobManager:
    """
    Background job manager with database-backed concurrency control.

    CONCURRENCY SAFETY:
    - Uses database COUNT query to track running jobs across all workers
    - The in-memory running_jobs set is only used for local heartbeat tracking
    - This ensures MAX_CONCURRENT_JOBS is enforced globally, not per-process
    """

    def __init__(self) -> None:
        # Local tracking for heartbeat tasks only - not used for concurrency control
        self._local_jobs: set[int] = set()
        self._heartbeat_tasks: dict[int, asyncio.Task] = {}

    async def _count_running_jobs(self, session: AsyncSession) -> int:
        """Count running jobs across all workers from database."""
        result = await session.execute(
            select(func.count()).select_from(BackgroundJob).where(
                BackgroundJob.status == "running"
            )
        )
        return result.scalar() or 0

    async def run_job(
        self, session: AsyncSession, job_id: int, work: Callable[[], Awaitable[None]]
    ) -> None:
        # Check concurrency limit from database (works across all workers)
        running_count = await self._count_running_jobs(session)
        if running_count >= settings.max_concurrent_jobs:
            await session.execute(
                update(BackgroundJob)
                .where(BackgroundJob.id == job_id)
                .values(
                    status="failed",
                    error_message="Max concurrent jobs exceeded",
                    completed_at=datetime.now(timezone.utc),
                )
            )
            await session.commit()
            await self._broadcast_job(
                job_id, status="failed", message="Max concurrent jobs exceeded"
            )
            return

        self._local_jobs.add(job_id)
        await session.execute(
            update(BackgroundJob)
            .where(BackgroundJob.id == job_id)
            .values(
                status="running",
                started_at=datetime.now(timezone.utc),
                last_heartbeat=datetime.now(timezone.utc),
            )
        )
        await session.commit()
        await self._broadcast_job(job_id, status="running", progress=0)

        heartbeat_task = asyncio.create_task(self._heartbeat_loop(job_id))
        self._heartbeat_tasks[job_id] = heartbeat_task

        try:
            await work()
            await session.execute(
                update(BackgroundJob)
                .where(BackgroundJob.id == job_id)
                .values(
                    status="completed",
                    progress=100,
                    completed_at=datetime.now(timezone.utc),
                )
            )
            await session.commit()
            await self._broadcast_job(job_id, status="completed", progress=100)
        except Exception as exc:
            await session.execute(
                update(BackgroundJob)
                .where(BackgroundJob.id == job_id)
                .values(
                    status="failed",
                    error_message=str(exc),
                    completed_at=datetime.now(timezone.utc),
                )
            )
            await session.commit()
            await self._broadcast_job(job_id, status="failed", message=str(exc))
        finally:
            self._local_jobs.discard(job_id)
            heartbeat_task = self._heartbeat_tasks.pop(job_id, None)
            if heartbeat_task:
                heartbeat_task.cancel()

    async def heartbeat(self, session: AsyncSession, job_id: int) -> None:
        await session.execute(
            update(BackgroundJob)
            .where(BackgroundJob.id == job_id)
            .values(last_heartbeat=datetime.now(timezone.utc))
        )
        await session.commit()
        await asyncio.sleep(0)

    async def update_progress(
        self, session: AsyncSession, job_id: int, progress: int, message: str | None = None
    ) -> None:
        await session.execute(
            update(BackgroundJob)
            .where(BackgroundJob.id == job_id)
            .values(
                progress=progress,
                progress_message=message,
                last_heartbeat=datetime.now(timezone.utc),
            )
        )
        await session.commit()
        await self._broadcast_job(job_id, progress=progress, message=message)

    async def cancel_job(self, session: AsyncSession, job_id: int) -> None:
        await session.execute(
            update(BackgroundJob)
            .where(BackgroundJob.id == job_id)
            .values(
                status="cancelled",
                error_message="Cancelled by user",
                completed_at=datetime.now(timezone.utc),
            )
        )
        await session.commit()
        await self._broadcast_job(job_id, status="cancelled", message="Cancelled by user")

    async def shutdown(self) -> None:
        """Cancel all locally-tracked jobs on shutdown."""
        if not self._local_jobs:
            return
        job_ids = list(self._local_jobs)
        async with async_session() as session:
            await session.execute(
                update(BackgroundJob)
                .where(BackgroundJob.id.in_(job_ids))
                .values(
                    status="cancelled",
                    error_message="Server shutting down",
                    completed_at=datetime.now(timezone.utc),
                )
            )
            await session.commit()
        for job_id in job_ids:
            heartbeat_task = self._heartbeat_tasks.pop(job_id, None)
            if heartbeat_task:
                heartbeat_task.cancel()
        self._local_jobs.clear()

    async def _heartbeat_loop(self, job_id: int) -> None:
        try:
            while True:
                async with async_session() as session:
                    await session.execute(
                        update(BackgroundJob)
                        .where(BackgroundJob.id == job_id)
                        .values(last_heartbeat=datetime.now(timezone.utc))
                    )
                    await session.commit()
                await asyncio.sleep(30)
        except asyncio.CancelledError:
            return

    async def _broadcast_job(
        self,
        job_id: int,
        status: str | None = None,
        progress: int | None = None,
        message: str | None = None,
    ) -> None:
        payload: dict[str, object] = {"job_id": job_id}
        if status is not None:
            payload["status"] = status
        if progress is not None:
            payload["progress"] = progress
        if message is not None:
            payload["message"] = message
        await ws_manager.broadcast("jobs", payload)


job_manager = JobManager()
