"""Host policy for dispatching a persisted workflow."""

from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING

from sqlalchemy.ext.asyncio import AsyncSession

if TYPE_CHECKING:
    from spectra_sherpa.app.models.workflow import Workflow
    from spectra_sherpa.app.services.saved_execution_admission import SavedExecutionAdmission

SavedWorkflowPolicy = Callable[
    [AsyncSession, int, "Workflow", "SavedExecutionAdmission | None"],
    Awaitable[None],
]
_policy: SavedWorkflowPolicy | None = None


def set_saved_workflow_policy(policy: SavedWorkflowPolicy | None) -> None:
    global _policy
    _policy = policy


async def require_saved_workflow_execution(
    session: AsyncSession,
    actor_id: int,
    workflow: "Workflow",
    admission: "SavedExecutionAdmission | None" = None,
) -> None:
    """Check host policy before dispatch or replay for an accessible saved graph."""
    if _policy is not None:
        await _policy(session, actor_id, workflow, admission)
