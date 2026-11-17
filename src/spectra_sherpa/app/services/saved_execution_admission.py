"""Request-local admission seam for the canonical saved-workflow executor.

These Python capabilities are not HTTP payloads or registry-dispatched tools.
The shared executor owns graph/source resolution and the canonical run row;
callers can bind their durable admission records in that same transaction.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from sqlalchemy.ext.asyncio import AsyncSession

from spectra_sherpa.app.services.frozen_workflow_sources import FrozenWorkflowSources


@dataclass(frozen=True)
class SavedExecutionSnapshot:
    workflow_id: int
    actor_id: int
    project_id: int | None
    definition: dict[str, Any]
    params: dict[str, Any]
    selection_revisions: list[dict[str, Any]]
    review_provenance: dict[str, Any]
    sources: FrozenWorkflowSources


class SavedExecutionAdmission(Protocol):
    """Trusted caller; hooks must neither commit nor roll back the transaction.

    Lock ordering: actor/project authority before workflow/review, then caller's
    approval/budget records. ``verify_current`` runs before successful or partial
    output retention and must raise ScientificAccessDenied on withdrawal.
    """

    async def lock_authority(self, session: AsyncSession, *, actor_id: int, workflow_id: int) -> None: ...

    async def admit(self, session: AsyncSession, snapshot: SavedExecutionSnapshot) -> None:
        """Canonically materialize and verify source science before consumption.

        ``snapshot.sources`` freezes bytes and interpretation metadata, not a
        scientific approval. Callers must parse through canonical source/binding
        authorities using this resolver and compare their actual scientific
        identities before writing admission records. Raw hashes alone do not
        establish target, selection or scientific equivalence.
        """
        ...

    async def bind_run(self, session: AsyncSession, *, run_id: int) -> None: ...

    async def verify_current(self, session: AsyncSession) -> None: ...
