"""Optional product evidence hooks; the standalone core has no hosted dependency."""

from collections.abc import Awaitable, Callable

from sqlalchemy.ext.asyncio import AsyncSession

RetentionProvider = Callable[..., Awaitable[bool]]
SnapshotProvider = Callable[[AsyncSession, int, int], Awaitable[dict]]
_retention: RetentionProvider | None = None
_snapshot: SnapshotProvider | None = None


def set_project_evidence_provider(
    retention: RetentionProvider | None, snapshot: SnapshotProvider | None = None
) -> None:
    global _retention, _snapshot
    _retention, _snapshot = retention, snapshot


async def has_extension_evidence(session: AsyncSession, **scope) -> bool:
    return await _retention(session, **scope) if _retention else False


async def project_evidence_snapshot(session: AsyncSession, project_id: int, actor_id: int) -> dict:
    return await _snapshot(session, project_id, actor_id) if _snapshot else {}
