from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Awaitable, Callable

from sqlalchemy import func, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from spectra_sherpa.app.core.config import settings
from spectra_sherpa.app.db.session import async_session
from spectra_sherpa.app.models.background_job import BackgroundJob
from spectra_sherpa.app.services.websocket_manager import ws_manager


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
        self._job_owners: dict[int, int] = {}
        self._admission_lock_key = 0x53534A4D  # Stable lock key for PG advisory lock.

    @property
    def _uses_postgres(self) -> bool:
        return settings.database_url.lower().startswith("postgresql")

    async def _resolve_job_owner(self, job_id: int, session: AsyncSession | None = None) -> int | None:
        """Resolve and cache the owner user_id for a job."""
        owner_id = self._job_owners.get(job_id)
        if owner_id is not None:
            return owner_id

        if session is None:
            async with async_session() as lookup_session:
                return await self._resolve_job_owner(job_id, session=lookup_session)

        result = await session.execute(select(BackgroundJob.user_id).where(BackgroundJob.id == job_id))
        owner_id = result.scalar_one_or_none()
        if owner_id is not None:
            self._job_owners[job_id] = owner_id
        return owner_id

    async def _count_running_jobs(self, session: AsyncSession) -> int:
        """Count running jobs across all workers from database."""
        result = await session.execute(
            select(func.count()).select_from(BackgroundJob).where(BackgroundJob.status == "running")
        )
        return result.scalar() or 0

    async def _count_running_jobs_for_user(self, session: AsyncSession, user_id: int) -> int:
        """Count running jobs for a specific user."""
        result = await session.execute(
            select(func.count())
            .select_from(BackgroundJob)
            .where(
                BackgroundJob.status == "running",
                BackgroundJob.user_id == user_id,
            )
        )
        return result.scalar() or 0

    async def run_job(self, job_id: int, work: Callable[[], Awaitable[None]]) -> None:
        """Execute a background job with full session ownership.

        This method is designed to run as a detached ``asyncio.create_task``
        after the originating HTTP request has already returned, so it must
        never use a request-scoped session.  All DB access goes through
        ``async_session()`` which creates short-lived, self-contained sessions.
        """
        # --- Admission: check concurrency limits and claim the job ----------
        async with async_session() as session:
            if self._uses_postgres:
                await session.execute(
                    text("SELECT pg_advisory_xact_lock(:k)"),
                    {"k": self._admission_lock_key},
                )

            running_count = await self._count_running_jobs(session)
            if running_count >= settings.max_concurrent_jobs:
                block_result = await session.execute(
                    update(BackgroundJob)
                    .where(BackgroundJob.id == job_id)
                    .where(BackgroundJob.status == "pending")
                    .values(
                        status="failed",
                        error_message="Server busy — max concurrent jobs exceeded. Please try again shortly.",
                        completed_at=datetime.now(timezone.utc),
                    )
                )
                await session.commit()
                if (block_result.rowcount or 0) > 0:
                    await self._broadcast_job(
                        job_id,
                        status="failed",
                        message="Server busy — max concurrent jobs exceeded. Please try again shortly.",
                    )
                self._job_owners.pop(job_id, None)
                return

            # Per-user concurrency limit
            owner_id = await self._resolve_job_owner(job_id, session=session)
            if owner_id is not None:
                user_running = await self._count_running_jobs_for_user(session, owner_id)
                if user_running >= settings.max_concurrent_jobs_per_user:
                    block_result = await session.execute(
                        update(BackgroundJob)
                        .where(BackgroundJob.id == job_id)
                        .where(BackgroundJob.status == "pending")
                        .values(
                            status="failed",
                            error_message="You already have a job running. Please wait for it to finish.",
                            completed_at=datetime.now(timezone.utc),
                        )
                    )
                    await session.commit()
                    if (block_result.rowcount or 0) > 0:
                        await self._broadcast_job(
                            job_id,
                            status="failed",
                            message="You already have a job running. Please wait for it to finish.",
                        )
                    self._job_owners.pop(job_id, None)
                    return

            start_result = await session.execute(
                update(BackgroundJob)
                .where(BackgroundJob.id == job_id)
                .where(BackgroundJob.status == "pending")
                .values(
                    status="running",
                    started_at=datetime.now(timezone.utc),
                    last_heartbeat=datetime.now(timezone.utc),
                )
            )
            if (start_result.rowcount or 0) == 0:
                await session.rollback()
                self._job_owners.pop(job_id, None)
                return

            self._local_jobs.add(job_id)
            await session.commit()

        # Broadcast outside the admission session (uses its own session if needed)
        await self._broadcast_job(job_id, status="running", progress=0)

        heartbeat_task = asyncio.create_task(self._heartbeat_loop(job_id))
        self._heartbeat_tasks[job_id] = heartbeat_task

        # --- Execute work and record outcome --------------------------------
        try:
            await work()
            async with async_session() as done_session:
                await done_session.execute(
                    update(BackgroundJob)
                    .where(BackgroundJob.id == job_id)
                    .values(
                        status="completed",
                        progress=100,
                        completed_at=datetime.now(timezone.utc),
                    )
                )
                await done_session.commit()
            await self._broadcast_job(job_id, status="completed", progress=100)
        except Exception as exc:
            async with async_session() as err_session:
                await err_session.execute(
                    update(BackgroundJob)
                    .where(BackgroundJob.id == job_id)
                    .values(
                        status="failed",
                        error_message=str(exc),
                        completed_at=datetime.now(timezone.utc),
                    )
                )
                await err_session.commit()
            await self._broadcast_job(job_id, status="failed", message=str(exc))
        finally:
            self._local_jobs.discard(job_id)
            self._job_owners.pop(job_id, None)
            heartbeat_task = self._heartbeat_tasks.pop(job_id, None)
            if heartbeat_task:
                heartbeat_task.cancel()

    async def heartbeat(self, session: AsyncSession, job_id: int) -> None:
        await session.execute(
            update(BackgroundJob).where(BackgroundJob.id == job_id).values(last_heartbeat=datetime.now(timezone.utc))
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
        await self._broadcast_job(job_id, progress=progress, message=message, session=session)

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
        await self._broadcast_job(job_id, status="cancelled", message="Cancelled by user", session=session)
        self._job_owners.pop(job_id, None)

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
        session: AsyncSession | None = None,
    ) -> None:
        owner_id = await self._resolve_job_owner(job_id, session=session)
        if owner_id is None:
            return

        payload: dict[str, object] = {"job_id": job_id}
        if status is not None:
            payload["status"] = status
        if progress is not None:
            payload["progress"] = progress
        if message is not None:
            payload["message"] = message
        await ws_manager.broadcast(f"jobs:{owner_id}", payload)


job_manager = JobManager()
