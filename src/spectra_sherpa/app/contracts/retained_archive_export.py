"""Host disclosure transaction for explicitly selected retained archive results.

Standalone exports retain local ownership rules. A managed host must positively
supply a qualified disclosure context; project membership alone is insufficient.
The context exits before archive bytes are released to the browser.
"""

from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager

from fastapi import HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from spectra_sherpa.app.contracts.project_access import uses_managed_project_access
from spectra_sherpa.app.schemas.execution_runs import ExecutionRunOut

Provider = Callable[[AsyncSession, int, int, tuple[ExecutionRunOut, ...], Request], AbstractAsyncContextManager[None]]
_provider: Provider | None = None


def set_retained_archive_export_provider(provider: Provider | None = None) -> None:
    global _provider
    _provider = provider


@asynccontextmanager
async def retained_archive_export_admission(
    session: AsyncSession, user_id: int, project_id: int, runs: tuple[ExecutionRunOut, ...], request: Request
) -> AsyncIterator[None]:
    if not runs or not uses_managed_project_access():
        yield
        return
    if _provider is None:
        raise HTTPException(409, "Retained-result archive export is not available for this managed project")
    async with _provider(session, user_id, project_id, runs, request):
        yield
