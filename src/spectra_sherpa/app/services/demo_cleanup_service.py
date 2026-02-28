"""
Demo user cleanup service — periodically deletes inactive demo users.

Follows the FolderWatchService singleton pattern. Runs as a background asyncio
task that checks for inactive users on a fixed interval.
Only active when SITE_PROFILE=demo.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from spectra_sherpa.app.db.session import async_session
from spectra_sherpa.app.models.user import User

logger = logging.getLogger(__name__)


class DemoCleanupService:
    """Background service that periodically deletes demo users
    who have been inactive for more than the configured threshold.

    Superusers are always exempt from cleanup.
    """

    TICK_INTERVAL = 3600  # 1 hour in seconds
    INACTIVE_THRESHOLD_DAYS = 7

    def __init__(self) -> None:
        self._running = False
        self._task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._poll_loop())
        logger.info(
            "Demo cleanup service started (interval=%ds, threshold=%dd)",
            self.TICK_INTERVAL,
            self.INACTIVE_THRESHOLD_DAYS,
        )

    async def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        logger.info("Demo cleanup service stopped")

    async def _poll_loop(self) -> None:
        try:
            while self._running:
                try:
                    await self._cleanup_inactive_users()
                except Exception:
                    logger.exception("Error in demo cleanup poll loop")
                await asyncio.sleep(self.TICK_INTERVAL)
        except asyncio.CancelledError:
            return

    async def _cleanup_inactive_users(self) -> None:
        cutoff = datetime.now(timezone.utc) - timedelta(days=self.INACTIVE_THRESHOLD_DAYS)

        async with async_session() as session:
            # Find non-superusers who are inactive:
            # - last_active is set and older than cutoff, OR
            # - last_active is NULL and created_at is older than cutoff
            #   (user registered but never made an authenticated request)
            query = select(User).where(
                User.is_superuser == False,  # noqa: E712
                (
                    (User.last_active.isnot(None) & (User.last_active < cutoff))
                    | (User.last_active.is_(None) & (User.created_at < cutoff))
                ),
            )
            result = await session.execute(query)
            stale_users = list(result.scalars().all())

            if not stale_users:
                return

            logger.info(
                "Demo cleanup: found %d inactive user(s) (threshold=%dd)",
                len(stale_users),
                self.INACTIVE_THRESHOLD_DAYS,
            )

            for user in stale_users:
                try:
                    await session.delete(user)
                    await session.commit()
                    logger.info(
                        "Demo cleanup: deleted user %s (id=%d, last_active=%s)",
                        user.username,
                        user.id,
                        user.last_active,
                    )
                except Exception:
                    await session.rollback()
                    logger.exception(
                        "Demo cleanup: failed to delete user %s (id=%d)",
                        user.username,
                        user.id,
                    )


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_service: DemoCleanupService | None = None


def get_demo_cleanup_service() -> DemoCleanupService:
    global _service
    if _service is None:
        _service = DemoCleanupService()
    return _service


async def start_demo_cleanup_service() -> None:
    service = get_demo_cleanup_service()
    await service.start()


async def stop_demo_cleanup_service() -> None:
    global _service
    if _service:
        await _service.stop()
        _service = None
