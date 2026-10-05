"""Project-scoped named dataset views; the Default view remains implicit."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from spectra_sherpa.app.api.deps import get_current_user, get_session
from spectra_sherpa.app.api.v1.routes.experiments import _require_experiment
from spectra_sherpa.app.models.dataset_view import DatasetView
from spectra_sherpa.app.models.user import User
from spectra_sherpa.app.services.dataset_views import receipt_sha256, selection_receipt, verify_selection_receipt
from spectra_sherpa.app.services.model_application import load_project_dataset
from spectra_sherpa.core.target_authority import TargetAuthority

router = APIRouter(prefix="/experiments/{experiment_id}/dataset-views")


class DatasetViewInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=120)
    stage: Literal["raw", "preprocessed", "synthetic"] = "raw"
    selected_file_ids: list[int] | None = Field(default=None, min_length=1, max_length=512)
    asset_id: str | None = Field(default=None, min_length=1, max_length=255)
    target_authority: TargetAuthority | None = None
    group_column: str | None = Field(default=None, max_length=255)


async def _load_receipt(session: AsyncSession, user_id: int, experiment_id: int, data: DatasetViewInput) -> dict:
    try:
        loaded = await load_project_dataset(
            session,
            user_id=user_id,
            experiment_id=experiment_id,
            stage=data.stage,
            file_ids=data.selected_file_ids,
            asset_id=data.asset_id,
        )
        return selection_receipt(
            loaded,
            selected_file_ids=data.selected_file_ids,
            target_authority=data.target_authority,
            group_column=data.group_column,
        )
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


def _response(view: DatasetView) -> dict:
    return {
        "id": view.id,
        "name": view.name,
        "experiment_id": view.experiment_id,
        "project_id": view.project_id,
        "selection": view.selection,
        "selection_sha256": view.selection_sha256,
        "created_at": view.created_at,
    }


async def _view_or_404(session: AsyncSession, experiment_id: int, view_id: int) -> DatasetView:
    view = await session.scalar(
        select(DatasetView).where(
            DatasetView.id == view_id,
            DatasetView.experiment_id == experiment_id,
            DatasetView.deleted_at.is_(None),
        )
    )
    if view is None:
        raise HTTPException(404, "Saved dataset view not found")
    return view


@router.get("")
async def list_dataset_views(
    experiment_id: int,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> list[dict]:
    await _require_experiment(session, experiment_id, current_user.id, "read")
    views = (
        await session.scalars(
            select(DatasetView)
            .where(DatasetView.experiment_id == experiment_id, DatasetView.deleted_at.is_(None))
            .order_by(DatasetView.id)
        )
    ).all()
    return [_response(view) for view in views]


@router.post("", status_code=201)
async def add_dataset_view(
    experiment_id: int,
    data: DatasetViewInput,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> dict:
    experiment = await _require_experiment(session, experiment_id, current_user.id)
    if experiment.project_id is None:
        raise HTTPException(422, "Save the dataset in a project before adding a reusable view")
    name = data.name.strip()
    if not name or name.casefold() == "default":
        raise HTTPException(422, "Choose a name other than Default")
    receipt = await _load_receipt(session, current_user.id, experiment_id, data)
    name_key = name.casefold()
    existing = await session.scalar(
        select(DatasetView).where(
            DatasetView.project_id == experiment.project_id,
            DatasetView.experiment_id == experiment_id,
            DatasetView.name_key == name_key,
        )
    )
    if existing is not None:
        raise HTTPException(409, "A view with this name already exists in this dataset, including deleted history")
    view = DatasetView(
        project_id=experiment.project_id,
        experiment_id=experiment_id,
        created_by_user_id=current_user.id,
        name=name,
        name_key=name_key,
        selection=receipt,
        selection_sha256=receipt_sha256(receipt),
    )
    session.add(view)
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(409, "A view with this name already exists in this dataset") from exc
    await session.refresh(view)
    return _response(view)


@router.get("/{view_id}")
async def show_dataset_view(
    experiment_id: int,
    view_id: int,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> dict:
    await _require_experiment(session, experiment_id, current_user.id, "read")
    view = await _view_or_404(session, experiment_id, view_id)
    try:
        receipt = view.selection
        if receipt_sha256(receipt) != view.selection_sha256:
            raise ValueError("Saved dataset view definition changed")
        loaded = await load_project_dataset(
            session,
            user_id=current_user.id,
            experiment_id=experiment_id,
            stage=receipt["stage"],
            file_ids=receipt["selected_file_ids"],
            asset_id=receipt["asset_id"],
        )
        verify_selection_receipt(loaded, receipt)
    except (KeyError, ValueError) as exc:
        raise HTTPException(409, "This saved view is stale; its exact source or sample cohort changed") from exc
    return _response(view)


@router.delete("/{view_id}", status_code=204)
async def delete_dataset_view(
    experiment_id: int,
    view_id: int,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> None:
    await _require_experiment(session, experiment_id, current_user.id)
    view = await _view_or_404(session, experiment_id, view_id)
    view.deleted_at = datetime.now(timezone.utc)
    await session.commit()
