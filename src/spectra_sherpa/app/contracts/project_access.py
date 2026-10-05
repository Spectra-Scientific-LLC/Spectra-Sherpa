"""Project authorization hook; standalone deployments retain owner isolation.

Callers must explicitly admit shared reads/writes. The default operation never
widens a legacy route to another project member.
"""

from collections.abc import Awaitable, Callable
from typing import Literal

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from spectra_sherpa.app.core.config import app_config
from spectra_sherpa.app.models.project import Project

ProjectOperation = Literal["owner", "read", "write"]
AccessProvider = Callable[[AsyncSession, int, Project, ProjectOperation], Awaitable[bool]]
CandidateProvider = Callable[[AsyncSession, int, bool, int, int], Awaitable[list[Project]]]
_provider: AccessProvider | None = None
_candidates: CandidateProvider | None = None


def set_project_access_provider(provider: AccessProvider | None, candidates: CandidateProvider | None = None) -> None:
    global _provider, _candidates
    _provider, _candidates = provider, candidates


def uses_managed_project_access() -> bool:
    # Unclassified hosted profiles never inherit owner-only access.
    return app_config.site_profile not in {None, "local", "demo", "org"}


async def project_access_allowed(
    session: AsyncSession, user_id: int, project: Project, operation: ProjectOperation = "owner"
) -> bool:
    if project.deleted_at is not None:
        return False
    if uses_managed_project_access():
        if app_config.site_profile != "pro" or _provider is None:
            return False
        return await _provider(session, user_id, project, operation)
    return project.user_id == user_id


async def accessible_project_ids(
    session: AsyncSession, user_id: int, *, archived: bool = False, limit: int | None = None, offset: int = 0
) -> list[int]:
    if (limit is not None and not 1 <= limit <= 100) or offset < 0:
        raise HTTPException(422, "Invalid project page")
    if uses_managed_project_access():
        if app_config.site_profile != "pro" or _candidates is None:
            return []
        projects = await _candidates(session, user_id, archived, limit if limit is not None else 100, offset)
    else:
        query = (
            select(Project)
            .where(
                Project.user_id == user_id,
                Project.deleted_at.is_(None),
                Project.parent_id.is_(None),
                Project.archived_at.is_not(None) if archived else Project.archived_at.is_(None),
            )
            .order_by(Project.updated_at.desc(), Project.id)
            .limit(limit)
            .offset(offset)
        )
        projects = list((await session.scalars(query.execution_options(populate_existing=True))).all())
    return [project.id for project in projects if await project_access_allowed(session, user_id, project, "read")]


async def require_project_access(
    session: AsyncSession, user_id: int, project: Project, operation: ProjectOperation = "owner"
) -> None:
    if not await project_access_allowed(session, user_id, project, operation):
        raise HTTPException(status_code=404, detail="Project not found")
