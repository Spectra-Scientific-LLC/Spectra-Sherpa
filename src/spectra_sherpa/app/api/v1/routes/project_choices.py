"""Explicit project choices; generated evidence is never manually promoted here."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from spectra_sherpa.app.api.deps import get_current_user, get_session, require_project
from spectra_sherpa.app.models.dataset_view import DatasetView
from spectra_sherpa.app.models.experiment import Experiment
from spectra_sherpa.app.models.project_choice_event import ProjectChoiceEvent
from spectra_sherpa.app.models.user import User
from spectra_sherpa.app.models.workflow import Workflow
from spectra_sherpa.app.services.dataset_views import receipt_sha256, selection_receipt, verify_selection_receipt
from spectra_sherpa.app.services.model_application import load_project_dataset

router = APIRouter(prefix="/projects/{project_id}/choices")


class DatasetChoice(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["dataset"]
    experiment_id: int
    dataset_view_id: int | None = None
    stage: Literal["raw", "preprocessed", "synthetic"] = "raw"
    selected_file_ids: list[int] | None = Field(default=None, min_length=1, max_length=512)
    asset_id: str | None = None


class WorkflowChoice(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["workflow"]
    workflow_id: int


def _event_response(event: ProjectChoiceEvent) -> dict:
    return {
        "id": event.id,
        "kind": event.kind,
        "experiment_id": event.experiment_id,
        "dataset_view_id": event.dataset_view_id,
        "workflow_id": event.workflow_id,
        "selected_experiment_id": event.selected_experiment_id,
        "selected_dataset_view_id": event.selected_dataset_view_id,
        "selected_workflow_id": event.selected_workflow_id,
        "selected_name": event.selected_name,
        "selected_digest": event.selected_digest,
        "selected_at": event.selected_at,
    }


@router.get("")
async def list_project_choices(
    project_id: int,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> dict:
    await require_project(project_id, current_user.id, session, operation="read")
    events = (
        await session.scalars(
            select(ProjectChoiceEvent)
            .where(ProjectChoiceEvent.project_id == project_id, ProjectChoiceEvent.user_id == current_user.id)
            .order_by(ProjectChoiceEvent.id.desc())
        )
    ).all()
    current: dict[str, dict] = {}
    for event in events:
        current.setdefault(event.kind, _event_response(event))
    return {"current": current, "history": [_event_response(event) for event in events]}


@router.get("/current-dataset")
async def current_project_dataset_choice(
    project_id: int,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> dict:
    """Return the verified active dataset binding for analysis starters.

    A workflow sheet may remain open after My Dataset changes. Returning the
    retained choice, rather than inferring it from that sheet, prevents a new
    starter from silently inheriting the previous source.
    """

    await require_project(project_id, current_user.id, session, operation="read")
    choice = await session.scalar(
        select(ProjectChoiceEvent)
        .where(
            ProjectChoiceEvent.project_id == project_id,
            ProjectChoiceEvent.user_id == current_user.id,
            ProjectChoiceEvent.kind == "dataset",
        )
        .order_by(ProjectChoiceEvent.id.desc())
        .limit(1)
    )
    if choice is None:
        return {"dataset": None}
    experiment = await session.scalar(
        select(Experiment).where(
            Experiment.id == choice.selected_experiment_id,
            Experiment.project_id == project_id,
        )
    )
    if experiment is None:
        raise HTTPException(409, "Active project dataset was removed. Select data in My Dataset again.")
    receipt = choice.selected_definition
    try:
        if not isinstance(receipt, dict) or receipt_sha256(receipt) != choice.selected_digest:
            raise ValueError("Active dataset choice changed")
        if choice.selected_dataset_view_id is not None:
            view = await session.scalar(
                select(DatasetView).where(
                    DatasetView.id == choice.selected_dataset_view_id,
                    DatasetView.project_id == project_id,
                    DatasetView.experiment_id == experiment.id,
                    DatasetView.deleted_at.is_(None),
                )
            )
            if view is None or view.selection_sha256 != choice.selected_digest:
                raise ValueError("Active named dataset definition changed")
        loaded = await load_project_dataset(
            session,
            user_id=current_user.id,
            experiment_id=experiment.id,
            stage=receipt["stage"],
            file_ids=receipt["selected_file_ids"],
            asset_id=receipt["asset_id"],
        )
        verify_selection_receipt(loaded, receipt)
    except (KeyError, ValueError) as exc:
        raise HTTPException(409, "Active project dataset is no longer exact. Select data in My Dataset again.") from exc
    return {
        "dataset": {
            "id": choice.id,
            "name": choice.selected_name,
            "digest": choice.selected_digest,
            "definition": receipt,
        }
    }


@router.post("", status_code=201)
async def select_project_choice(
    project_id: int,
    data: DatasetChoice | WorkflowChoice,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> dict:
    await require_project(project_id, current_user.id, session, operation="write")
    if data.kind == "dataset":
        experiment = await session.scalar(
            select(Experiment).where(Experiment.id == data.experiment_id, Experiment.project_id == project_id)
        )
        if experiment is None:
            raise HTTPException(404, "Dataset not found in this project")
        view = None
        selected_digest = None
        selected_definition = None
        if data.dataset_view_id is not None:
            view = await session.scalar(
                select(DatasetView).where(
                    DatasetView.id == data.dataset_view_id,
                    DatasetView.experiment_id == experiment.id,
                    DatasetView.project_id == project_id,
                    DatasetView.deleted_at.is_(None),
                )
            )
            if view is None:
                raise HTTPException(404, "Saved dataset definition not found in this project")
            try:
                receipt = view.selection
                if receipt_sha256(receipt) != view.selection_sha256:
                    raise ValueError("Saved dataset definition changed")
                loaded = await load_project_dataset(
                    session,
                    user_id=current_user.id,
                    experiment_id=experiment.id,
                    stage=receipt["stage"],
                    file_ids=receipt["selected_file_ids"],
                    asset_id=receipt["asset_id"],
                )
                verify_selection_receipt(loaded, receipt)
                selected_digest = view.selection_sha256
                selected_definition = receipt
            except (KeyError, ValueError) as exc:
                raise HTTPException(409, "Saved dataset definition no longer matches its source") from exc
        else:
            try:
                loaded = await load_project_dataset(
                    session,
                    user_id=current_user.id,
                    experiment_id=experiment.id,
                    stage=data.stage,
                    file_ids=data.selected_file_ids,
                    asset_id=data.asset_id,
                )
                selected_definition = selection_receipt(loaded, selected_file_ids=data.selected_file_ids)
                selected_digest = receipt_sha256(selected_definition)
            except (KeyError, ValueError) as exc:
                raise HTTPException(409, "Default dataset is not ready for selection") from exc
        event = ProjectChoiceEvent(
            project_id=project_id,
            user_id=current_user.id,
            kind="dataset",
            experiment_id=experiment.id,
            dataset_view_id=data.dataset_view_id,
            selected_experiment_id=experiment.id,
            selected_dataset_view_id=data.dataset_view_id,
            selected_name=view.name if view is not None else experiment.name,
            selected_digest=selected_digest,
            selected_definition=selected_definition,
        )
    else:
        workflow = await session.scalar(
            select(Workflow).where(Workflow.id == data.workflow_id, Workflow.project_id == project_id)
        )
        if workflow is None or workflow.purpose != "analysis":
            raise HTTPException(404, "Analysis workflow not found in this project")
        event = ProjectChoiceEvent(
            project_id=project_id,
            user_id=current_user.id,
            kind="workflow",
            workflow_id=workflow.id,
            selected_workflow_id=workflow.id,
            selected_name=workflow.name,
            selected_digest=workflow.integrity_hash,
        )
    previous = await session.scalar(
        select(ProjectChoiceEvent)
        .where(
            ProjectChoiceEvent.project_id == project_id,
            ProjectChoiceEvent.user_id == current_user.id,
            ProjectChoiceEvent.kind == event.kind,
        )
        .order_by(ProjectChoiceEvent.id.desc())
        .limit(1)
    )
    if previous is not None and (
        previous.selected_experiment_id,
        previous.selected_dataset_view_id,
        previous.selected_workflow_id,
        previous.selected_name,
        previous.selected_digest,
        previous.selected_definition,
    ) == (
        event.selected_experiment_id,
        event.selected_dataset_view_id,
        event.selected_workflow_id,
        event.selected_name,
        event.selected_digest,
        event.selected_definition,
    ):
        return _event_response(previous)
    session.add(event)
    await session.commit()
    await session.refresh(event)
    return _event_response(event)
