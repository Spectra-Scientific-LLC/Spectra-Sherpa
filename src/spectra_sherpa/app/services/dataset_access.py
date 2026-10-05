"""HTTP-neutral dataset access authority shared by app admission paths."""

from __future__ import annotations

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from spectra_sherpa.app.contracts.project_access import uses_managed_project_access
from spectra_sherpa.app.contracts.scientific_access import require_scientific_access
from spectra_sherpa.app.models.experiment import Experiment
from spectra_sherpa.app.models.experiment_file import ExperimentFile


class DatasetAccessError(LookupError):
    """The requested experiment or exact file is unavailable to the actor."""


async def require_experiment_access(
    session: AsyncSession,
    experiment_id: int,
    user_id: int,
    workflow_project_id: int | None,
) -> None:
    result = await session.execute(
        select(Experiment.id, Experiment.project_id).where(
            Experiment.id == experiment_id,
            or_(Experiment.user_id == user_id, uses_managed_project_access()),
        )
    )
    row = result.one_or_none()
    if row is None:
        raise DatasetAccessError("Dataset not found")
    if workflow_project_id is not None and row.project_id != workflow_project_id:
        raise DatasetAccessError("Dataset not found in this project")
    if uses_managed_project_access():
        await require_scientific_access(session, user_id, row.project_id, "read")


async def require_file_access(
    session: AsyncSession,
    experiment_id: int,
    file_id: int,
    user_id: int,
    stage: str | None = None,
) -> None:
    if uses_managed_project_access():
        await require_experiment_access(session, experiment_id, user_id, None)
    query = (
        select(ExperimentFile.id)
        .join(Experiment, ExperimentFile.experiment_id == Experiment.id)
        .where(
            Experiment.id == experiment_id,
            or_(Experiment.user_id == user_id, uses_managed_project_access()),
            ExperimentFile.id == file_id,
        )
    )
    if stage:
        query = query.where(ExperimentFile.stage == stage)
    result = await session.execute(query)
    if result.scalar_one_or_none() is None:
        raise DatasetAccessError("Dataset file not found")
