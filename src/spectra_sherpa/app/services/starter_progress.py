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


async def _count(session: AsyncSession, statement) -> int:  # noqa: ANN001
    return int((await session.scalar(statement)) or 0)


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
    runs = await _count(
        session,
        select(func.count(ExecutionRun.id)).where(
            or_(ExecutionRun.project_id == project_id, ExecutionRun.workflow_id.in_(workflow_ids))
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
        "has_executed": runs > 0,
        "has_model": models > 0,
    }
