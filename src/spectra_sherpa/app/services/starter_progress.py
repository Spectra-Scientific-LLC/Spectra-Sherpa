"""Observe which Starter steps a project has completed.

The Starter checklist and ambient Guidance both read this, so the step the
user sees as next is the step Guidance nudges toward.
"""

from __future__ import annotations

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from spectra_sherpa.app.models.execution_run import ExecutionRun
from spectra_sherpa.app.models.experiment import Experiment
from spectra_sherpa.app.models.experiment_file import ExperimentFile
from spectra_sherpa.app.models.model_artifact import ModelArtifact
from spectra_sherpa.app.models.project_data_source import ProjectDataSource
from spectra_sherpa.app.models.workflow import Workflow
from spectra_sherpa.app.models.workflow_node import WorkflowNode

# Only a completed run is evidence that the workflow ran. Partial, failed and
# cancelled runs leave the Run step current so the user can recover.
SUCCESSFUL_RUN_STATUSES = frozenset({"completed"})
UNSUCCESSFUL_RUN_STATUSES = frozenset({"partial", "error", "failed", "cancelled"})


async def _count(session: AsyncSession, statement) -> int:  # noqa: ANN001
    return int((await session.scalar(statement)) or 0)


def _project_runs(project_id: int):  # noqa: ANN202
    workflow_ids = select(Workflow.id).where(Workflow.project_id == project_id).scalar_subquery()
    return or_(ExecutionRun.project_id == project_id, ExecutionRun.workflow_id.in_(workflow_ids))


async def latest_run_status(session: AsyncSession, project_id: int) -> str | None:
    """Status of the project's newest run, or ``None`` before the first run."""
    return await session.scalar(
        select(ExecutionRun.status)
        .where(_project_runs(project_id))
        .order_by(ExecutionRun.created_at.desc(), ExecutionRun.id.desc())
        .limit(1)
    )


async def project_progress(session: AsyncSession, project_id: int) -> dict[str, bool]:
    """Progress signals for one project; the caller has already checked access."""
    workflow_ids = select(Workflow.id).where(Workflow.project_id == project_id).scalar_subquery()

    has_data = bool(
        await _count(
            session, select(func.count(ProjectDataSource.id)).where(ProjectDataSource.project_id == project_id)
        )
        or await _count(
            session,
            select(func.count(ExperimentFile.id))
            .join(Experiment, Experiment.id == ExperimentFile.experiment_id)
            .where(Experiment.project_id == project_id),
        )
    )
    workflow_nodes = await _count(
        session, select(func.count(WorkflowNode.id)).where(WorkflowNode.workflow_id.in_(workflow_ids))
    )
    preprocessing_nodes = await _count(
        session,
        select(func.count(WorkflowNode.id)).where(
            WorkflowNode.workflow_id.in_(workflow_ids),
            or_(WorkflowNode.node_type.like("preprocess.%"), WorkflowNode.node_type.like("baseline.%")),
        ),
    )
    successful_runs = await _count(
        session,
        select(func.count(ExecutionRun.id)).where(
            _project_runs(project_id), ExecutionRun.status.in_(SUCCESSFUL_RUN_STATUSES)
        ),
    )
    models = await _count(
        session,
        select(func.count(ModelArtifact.id)).where(
            ModelArtifact.project_id == project_id,
            ModelArtifact.is_active.is_(True),
        ),
    )
    return {
        "has_project": True,
        "has_data": has_data,
        "has_workflow": workflow_nodes > 0,
        "has_preprocessing": preprocessing_nodes > 0,
        "has_executed": successful_runs > 0,
        "has_model": models > 0,
    }
