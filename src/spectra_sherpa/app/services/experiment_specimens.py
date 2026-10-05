"""Owned persistence boundary for mutable experiment specimens."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from spectra_sherpa.app.models.experiment import Experiment
from spectra_sherpa.app.models.experiment_specimen import ExperimentSpecimen


class ExperimentSpecimenNotFound(ValueError):
    """The experiment or specimen is outside the actor's owned scope."""


class ExperimentSpecimenKeyConflict(ValueError):
    """The experiment already uses the requested specimen key."""


async def _require_owned_experiment(session: AsyncSession, experiment_id: int, user_id: int) -> None:
    result = await session.execute(
        select(Experiment.id).where(Experiment.id == experiment_id, Experiment.user_id == user_id)
    )
    if result.scalar_one_or_none() is None:
        raise ExperimentSpecimenNotFound("Experiment not found")


async def list_experiment_specimens(
    session: AsyncSession, experiment_id: int, user_id: int
) -> list[ExperimentSpecimen]:
    await _require_owned_experiment(session, experiment_id, user_id)
    result = await session.execute(
        select(ExperimentSpecimen)
        .where(ExperimentSpecimen.experiment_id == experiment_id)
        .order_by(ExperimentSpecimen.specimen_key, ExperimentSpecimen.specimen_uid)
    )
    return list(result.scalars())


async def get_experiment_specimen(
    session: AsyncSession, experiment_id: int, specimen_uid: str, user_id: int
) -> ExperimentSpecimen:
    result = await session.execute(
        select(ExperimentSpecimen)
        .join(Experiment, Experiment.id == ExperimentSpecimen.experiment_id)
        .where(
            ExperimentSpecimen.experiment_id == experiment_id,
            ExperimentSpecimen.specimen_uid == specimen_uid,
            Experiment.user_id == user_id,
        )
    )
    specimen = result.scalar_one_or_none()
    if specimen is None:
        raise ExperimentSpecimenNotFound("Specimen not found")
    return specimen


async def create_experiment_specimen(
    session: AsyncSession,
    experiment_id: int,
    user_id: int,
    values: Mapping[str, Any],
) -> ExperimentSpecimen:
    await _require_owned_experiment(session, experiment_id, user_id)
    specimen = ExperimentSpecimen(experiment_id=experiment_id, **dict(values))
    try:
        async with session.begin_nested():
            session.add(specimen)
            await session.flush()
    except IntegrityError as exc:
        raise ExperimentSpecimenKeyConflict(
            f"Specimen key '{values['specimen_key']}' already exists in this experiment"
        ) from exc
    await session.commit()
    await session.refresh(specimen)
    return specimen


async def update_experiment_specimen(
    session: AsyncSession,
    experiment_id: int,
    specimen_uid: str,
    user_id: int,
    values: Mapping[str, Any],
) -> ExperimentSpecimen:
    specimen = await get_experiment_specimen(session, experiment_id, specimen_uid, user_id)
    try:
        async with session.begin_nested():
            for field, value in values.items():
                setattr(specimen, field, value)
            await session.flush()
    except IntegrityError as exc:
        raise ExperimentSpecimenKeyConflict("Specimen key already exists in this experiment") from exc
    await session.commit()
    await session.refresh(specimen)
    return specimen
