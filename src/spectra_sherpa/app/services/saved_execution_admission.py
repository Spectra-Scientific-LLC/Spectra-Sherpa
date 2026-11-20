"""Request-local admission seam for the canonical saved-workflow executor.

These Python capabilities are not HTTP payloads or registry-dispatched tools.
The shared executor owns graph/source resolution and the canonical run row;
callers can bind their durable admission records in that same transaction.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from typing import Any, Protocol

from sqlalchemy.ext.asyncio import AsyncSession

from spectra_sherpa.app.models.execution_run import ExecutionRun
from spectra_sherpa.app.services.frozen_workflow_sources import FrozenWorkflowSources
from spectra_sherpa.core.captured_model_artifacts import CapturedModelArtifacts

# A trusted caller may bind evidence to the same transaction as the terminal run.
RetainCompletedRun = Callable[[AsyncSession, ExecutionRun], Awaitable[None]]


@dataclass(frozen=True)
class SavedRunOutputScope:
    """Explicit port allowlist for the trusted caller's visible run results."""

    ports: Mapping[str, frozenset[str]]

    def project(self, results: dict[str, Any]) -> dict[str, Any]:
        return {
            node_id: {port: output for port, output in outputs.items() if port in self.ports[node_id]}
            for node_id, outputs in results.items()
            if node_id in self.ports and isinstance(outputs, dict)
        }


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

    async def admit(self, session: AsyncSession, snapshot: SavedExecutionSnapshot) -> CapturedModelArtifacts | None:
        """Canonically materialize and verify source science before consumption.

        ``snapshot.sources`` freezes bytes and interpretation metadata, not a
        scientific approval. Callers must parse through canonical source/binding
        authorities using this resolver and compare their actual scientific
        identities before writing admission records. Raw hashes alone do not
        establish target, selection or scientific equivalence.

        A caller binding saved models may return concrete immutable captured
        model bytes. The executor requires exact admitted-ID equality before
        reserving a run and supplies those bytes to parent and worker readers.
        None preserves existing live-reader behavior. Model capture, ownership
        and comparison with the caller's approved identity belong to admission.
        """
        ...

    async def bind_run(self, session: AsyncSession, *, run_id: int) -> None: ...

    async def verify_current(self, session: AsyncSession) -> None: ...
