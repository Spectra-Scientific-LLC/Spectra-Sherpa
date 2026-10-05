"""Experiment-scoped specimen catalog routes."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from spectra_sherpa.app.api.deps import demo_guard, get_current_user, get_session
from spectra_sherpa.app.models.experiment_specimen import ExperimentSpecimen
from spectra_sherpa.app.models.user import User
from spectra_sherpa.app.schemas.experiment_specimens import (
    ExperimentSpecimenCreate,
    ExperimentSpecimenOut,
    ExperimentSpecimenUpdate,
)
from spectra_sherpa.app.services.experiment_specimens import (
    ExperimentSpecimenKeyConflict,
    ExperimentSpecimenNotFound,
    create_experiment_specimen,
    get_experiment_specimen,
    list_experiment_specimens,
    update_experiment_specimen,
)

router = APIRouter(prefix="/experiments/{experiment_id}/specimens")


def _not_found(exc: ExperimentSpecimenNotFound) -> HTTPException:
    return HTTPException(status_code=404, detail=str(exc))


def _conflict(exc: ExperimentSpecimenKeyConflict) -> HTTPException:
    return HTTPException(status_code=409, detail=str(exc))


@router.get("", response_model=list[ExperimentSpecimenOut])
async def list_specimens_endpoint(
    experiment_id: int,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> list[ExperimentSpecimen]:
    try:
        return await list_experiment_specimens(session, experiment_id, current_user.id)
    except ExperimentSpecimenNotFound as exc:
        raise _not_found(exc) from exc


@router.post(
    "",
    response_model=ExperimentSpecimenOut,
    status_code=201,
    dependencies=[Depends(demo_guard("sample_table_authoring"))],
)
async def create_specimen_endpoint(
    experiment_id: int,
    payload: ExperimentSpecimenCreate,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> ExperimentSpecimen:
    try:
        return await create_experiment_specimen(
            session,
            experiment_id,
            current_user.id,
            payload.model_dump(),
        )
    except ExperimentSpecimenNotFound as exc:
        raise _not_found(exc) from exc
    except ExperimentSpecimenKeyConflict as exc:
        raise _conflict(exc) from exc


@router.get("/{specimen_uid}", response_model=ExperimentSpecimenOut)
async def get_specimen_endpoint(
    experiment_id: int,
    specimen_uid: UUID,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> ExperimentSpecimen:
    try:
        return await get_experiment_specimen(session, experiment_id, str(specimen_uid), current_user.id)
    except ExperimentSpecimenNotFound as exc:
        raise _not_found(exc) from exc


@router.patch(
    "/{specimen_uid}",
    response_model=ExperimentSpecimenOut,
    dependencies=[Depends(demo_guard("sample_table_authoring"))],
)
async def update_specimen_endpoint(
    experiment_id: int,
    specimen_uid: UUID,
    payload: ExperimentSpecimenUpdate,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> ExperimentSpecimen:
    try:
        return await update_experiment_specimen(
            session,
            experiment_id,
            str(specimen_uid),
            current_user.id,
            payload.model_dump(exclude_unset=True),
        )
    except ExperimentSpecimenNotFound as exc:
        raise _not_found(exc) from exc
    except ExperimentSpecimenKeyConflict as exc:
        raise _conflict(exc) from exc
