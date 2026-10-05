"""Optional hosted campaign/package provenance without an OSS server import."""

from collections.abc import Awaitable, Callable

from sqlalchemy.ext.asyncio import AsyncSession

HostedProvenanceProvider = Callable[[AsyncSession, int, int], Awaitable[dict[str, dict]]]
_provider: HostedProvenanceProvider | None = None


def set_hosted_project_provenance_provider(provider: HostedProvenanceProvider | None) -> None:
    global _provider
    _provider = provider


async def hosted_project_provenance(session: AsyncSession, project_id: int, actor_id: int) -> dict[str, dict]:
    return await _provider(session, project_id, actor_id) if _provider else {}
