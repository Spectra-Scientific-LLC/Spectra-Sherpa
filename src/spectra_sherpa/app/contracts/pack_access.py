"""Adapt trusted project authorization to installed pack operations."""

from collections.abc import Callable

from sqlalchemy.ext.asyncio import AsyncSession

from spectra_sherpa.app.contracts.scientific_access import ScientificAccessDenied
from spectra_sherpa.app.services.dag.pack_execution_access import (
    PackExecutionAuthorizer,
    PackExecutionDenied,
    require_pack_execution,
)
from spectra_sherpa.core.pack_manifest import PackReference

PackAuthorizerFactory = Callable[[AsyncSession, int, int | None, bool], PackExecutionAuthorizer]
_factory: PackAuthorizerFactory | None = None


def set_pack_authorizer_factory(factory: PackAuthorizerFactory | None = None) -> None:
    global _factory
    _factory = factory


async def authorize_project_packs(
    session: AsyncSession,
    actor_id: int,
    project_id: int | None,
    required: tuple[PackReference, ...],
    *,
    pending_project: bool = False,
) -> PackExecutionAuthorizer | None:
    """Check a project and return the live authorizer for subsequent execution.

    Import checks a freshly provisioned project inside the transaction which
    created it. That check must never be carried into a worker or later request.
    """
    authorize = _factory(session, actor_id, project_id, pending_project) if _factory is not None else None
    try:
        await require_pack_execution(required, authorize)
    except PackExecutionDenied as exc:
        raise ScientificAccessDenied(403, str(exc)) from exc
    return None if pending_project else authorize
