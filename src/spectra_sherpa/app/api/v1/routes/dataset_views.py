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


class CurationReviewOrigin(BaseModel):
    model_config = ConfigDict(extra="forbid")
    workflow_id: int = Field(ge=1)
    run_id: int = Field(ge=1)
    node_id: str
    revision: int = Field(ge=0)


class CurationSource(BaseModel):
    model_config = ConfigDict(extra="forbid")
    stage: Literal["raw", "preprocessed", "synthetic"] = "raw"
    selected_file_ids: list[int] | None = Field(default=None, min_length=1, max_length=512)
    asset_id: str | None = None
    target_authority: TargetAuthority | None = None
    group_column: str | None = None
    parent_view_id: int | None = Field(default=None, ge=1)
    parent_sha256: str | None = None
    source_manifest_sha256: str | None = None
    collection_definition_sha256: str | None = None
    scientific_collection_sha256: str | None = None
    seed_observations: list[dict] | None = Field(default=None, max_length=5000)
    review_origin: CurationReviewOrigin | None = None


class CurationDecision(CurationSource):
    name: str = Field(min_length=1, max_length=120)
    reason: str = Field(min_length=1, max_length=2000)
    action: Literal["exclude", "restore"]
    sample_ids: list[str] = Field(min_length=1, max_length=5000)
    expected_selection_sha256: str
    expected_observations_sha256: str


async def _curation_context(session, user, experiment_id, data):
    from spectra_sherpa.app.lib.collection_assembly import verified_source_observations
    from spectra_sherpa.app.services.dataset_views import _unpack_mask

    experiment = await _require_experiment(session, experiment_id, user.id, "read")
    if experiment.project_id is None:
        raise HTTPException(422, "Save the dataset in a project before curating observations")
    if (data.parent_view_id is None) != (data.parent_sha256 is None):
        raise HTTPException(422, "The parent definition and digest must be supplied together")
    parent = await _view_or_404(session, experiment_id, data.parent_view_id) if data.parent_view_id else None
    if parent is not None and (
        parent.selection_sha256 != data.parent_sha256 or receipt_sha256(parent.selection) != data.parent_sha256
    ):
        raise HTTPException(409, "Parent definition changed; reload before curating")
    source = parent.selection if parent else data.model_dump(mode="json")
    try:
        loaded = await load_project_dataset(
            session,
            user_id=user.id,
            experiment_id=experiment_id,
            stage=source["stage"],
            file_ids=source["selected_file_ids"],
            asset_id=source["asset_id"],
        )
        receipt = (
            parent.selection
            if parent
            else selection_receipt(
                loaded,
                selected_file_ids=source["selected_file_ids"],
                target_authority=source.get("target_authority"),
                group_column=source.get("group_column"),
            )
        )
        verify_selection_receipt(loaded, receipt)
        observations = verified_source_observations(loaded.dataset)
        if any(
            getattr(data, key) is not None and getattr(data, key) != receipt.get(key)
            for key in ("source_manifest_sha256", "collection_definition_sha256", "scientific_collection_sha256")
        ):
            raise ValueError("Reviewed source changed; rerun before transferring a selection")
        lookup = {row["sample_id"]: row for row in observations}
        if data.seed_observations is not None and any(
            lookup.get(row.get("sample_id")) != row for row in data.seed_observations
        ):
            raise ValueError("Reviewed observation identity changed; rerun before transferring a selection")
        original = _unpack_mask(receipt.get("source_selection", receipt))
        included = _unpack_mask(receipt)
        rows = [
            {
                **row,
                "included": bool(included[i]),
                "source_included": bool(original[i]),
                "status": "source_excluded" if not original[i] else "included" if included[i] else "curated_excluded",
            }
            for i, row in enumerate(observations)
        ]
        return loaded, receipt, observations, rows
    except (KeyError, ValueError, TypeError) as exc:
        raise HTTPException(409, str(exc)) from exc


@router.post("/curation-context")
async def dataset_curation_context(
    experiment_id: int,
    data: CurationSource,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> dict:
    _, receipt, observations, rows = await _curation_context(session, current_user, experiment_id, data)
    return {
        "selection": receipt,
        "selection_sha256": receipt_sha256(receipt),
        "observations_sha256": receipt_sha256({"rows": observations}),
        "rows": rows,
    }


async def _verified_review_origin(session, user, experiment_id, data, parent, observations):
    if data.review_origin is None:
        return None
    from spectra_sherpa.app.api.v1.routes.workflows.sample_review import get_sample_review

    origin = data.review_origin
    review = await get_sample_review(origin.workflow_id, origin.node_id, session, user)
    binding = review.get("dataset_curation_source")
    if (
        review["run_id"] != origin.run_id
        or review["revision"] != origin.revision
        or review["stale"]
        or not binding
        or binding.get("experiment_id") != experiment_id
    ):
        raise HTTPException(409, "Originating diagnostic review changed; reload the workbench")
    keys = ("source_manifest_sha256", "collection_definition_sha256", "scientific_collection_sha256")
    if any(binding.get(k) != parent.get(k) for k in keys):
        raise HTTPException(409, "Diagnostic origin does not match this exact dataset")
    lookup = {r["sample_id"]: r for r in observations}
    captured = {r["sample_id"]: r for r in binding.get("observations", [])}
    roles = {r["id"]: r["role"] for r in review["rows"]}
    if any(identity not in roles or captured.get(identity) != lookup.get(identity) for identity in data.sample_ids):
        raise HTTPException(409, "Selected observations do not match the originating diagnostic review")
    return {
        **origin.model_dump(),
        "selected_roles": {i: roles[i] for i in data.sample_ids},
        "post_review": True,
        "heldout_inspected": any(roles[i] == "held_out_test" for i in data.sample_ids),
    }


@router.post("/curations", status_code=201)
async def curate_dataset_view(
    experiment_id: int,
    data: CurationDecision,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> dict:
    from spectra_sherpa.app.db.session import begin_serialized_sqlite_write
    from spectra_sherpa.app.services.audit import audit_emitter
    from spectra_sherpa.app.services.dataset_views import curation_receipt

    if current_user.principal_kind != "human":
        raise HTTPException(403, "Dataset curation requires a scientist account")
    await begin_serialized_sqlite_write(session)
    await _require_experiment(session, experiment_id, current_user.id)
    loaded, parent, observations, _ = await _curation_context(session, current_user, experiment_id, data)
    if (
        receipt_sha256(parent) != data.expected_selection_sha256
        or receipt_sha256({"rows": observations}) != data.expected_observations_sha256
    ):
        raise HTTPException(409, "Dataset or parent definition changed; reload before applying this decision")
    origin = await _verified_review_origin(session, current_user, experiment_id, data, parent, observations)
    name = data.name.strip()
    if not name or name.casefold() == "default":
        raise HTTPException(422, "Choose a new definition name other than Default")
    try:
        receipt = curation_receipt(
            loaded,
            parent,
            parent_view_id=data.parent_view_id,
            action=data.action,
            sample_ids=data.sample_ids,
            reason=data.reason,
            review_origin=origin,
        )
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    view = DatasetView(
        project_id=loaded.project_id,
        experiment_id=experiment_id,
        created_by_user_id=current_user.id,
        name=name,
        name_key=name.casefold(),
        selection=receipt,
        selection_sha256=receipt_sha256(receipt),
    )
    session.add(view)
    try:
        await session.flush()
        audit_emitter.emit(
            session=session,
            action="dataset.curation.created",
            target_type="DatasetView",
            target_id=view.id,
            after={"selection_sha256": view.selection_sha256, "decision": receipt["decision"]},
        )
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(409, "Choose a new name; this definition name already exists in retained history") from exc
    await session.refresh(view)
    return _response(view)


def _curated_selection(view, dataset_name):
    from spectra_sherpa.app.schemas.workflow_data_selection import WorkflowSourceSelection

    receipt = view.selection
    keys = (
        "experiment_id",
        "stage",
        "selected_file_ids",
        "asset_id",
        "source_manifest_sha256",
        "collection_definition_sha256",
        "scientific_collection_sha256",
        "target_authority",
        "group_column",
    )
    return WorkflowSourceSelection(
        **{k: receipt.get(k) for k in keys},
        dataset_name=dataset_name,
        dataset_view_id=view.id,
        dataset_view_sha256=view.selection_sha256,
    )


async def _dependent_state(session, user, view, workflow_id, source_node_id, *, write=False):
    from spectra_sherpa.app.lib.workflow_purpose import ANALYSIS_WORKFLOW
    from spectra_sherpa.app.services.sample_review_custody import require_review_source_preserved
    from spectra_sherpa.app.services.workflow_data_selections import (
        load_selection_context,
        source_parameters,
        workflow_graph_digest,
    )

    workflow, node, revision, saved = await load_selection_context(
        session,
        workflow_id=workflow_id,
        source_node_id=source_node_id,
        user_id=user.id,
        for_update=write,
    )
    if workflow.project_id != view.project_id or saved is None:
        raise HTTPException(404, "Dependent workflow not found")
    target = _curated_selection(view, saved.dataset_name)
    source_keys = (
        "experiment_id",
        "stage",
        "selected_file_ids",
        "asset_id",
        "source_manifest_sha256",
        "collection_definition_sha256",
        "scientific_collection_sha256",
        "target_authority",
        "group_column",
    )
    if any(getattr(saved, key) != getattr(target, key) for key in source_keys):
        raise HTTPException(409, "Workflow uses a different source or scientific selection")
    parent_id = view.selection.get("decision", {}).get("parent_view_id")
    parent_digest = view.selection.get("decision", {}).get("parent_sha256")
    if saved.dataset_view_id != parent_id or (parent_id is not None and saved.dataset_view_sha256 != parent_digest):
        raise HTTPException(409, "Workflow uses another saved definition; its binding is preserved")
    blocked = None
    if workflow.purpose != ANALYSIS_WORKFLOW or workflow.fold_validation_plan:
        blocked = "Campaign seeds and folds are preserved. Start a separate analysis to change the cohort."
    else:
        try:
            await require_review_source_preserved(session, workflow, node.node_id, source_parameters(target))
        except HTTPException as exc:
            blocked = str(exc.detail)
    return {
        "workflow_id": workflow.id,
        "workflow_name": workflow.name,
        "source_node_id": node.node_id,
        "expected_revision": revision.revision_number if revision else None,
        "expected_graph_digest": workflow_graph_digest(workflow),
        "blocked_reason": blocked,
        "selection": target.model_dump(mode="json"),
    }


@router.get("/{view_id}/dependents")
async def dataset_view_dependents(
    experiment_id: int,
    view_id: int,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> list[dict]:
    from spectra_sherpa.app.models.workflow import Workflow
    from spectra_sherpa.app.models.workflow_node import WorkflowNode

    await _require_experiment(session, experiment_id, current_user.id, "read")
    view = await _view_or_404(session, experiment_id, view_id)
    candidates = (
        await session.execute(
            select(Workflow.id, WorkflowNode.node_id)
            .join(WorkflowNode)
            .where(Workflow.project_id == view.project_id, WorkflowNode.node_type == "data.collection_load")
        )
    ).all()
    result = []
    for workflow_id, node_id in candidates:
        try:
            result.append(await _dependent_state(session, current_user, view, workflow_id, node_id))
        except HTTPException:
            continue  # Inaccessible or differently pinned analyses are not dependents.
    return result


class CurationApply(BaseModel):
    model_config = ConfigDict(extra="forbid")
    workflow_id: int = Field(ge=1)
    source_node_id: str
    expected_revision: int | None = None
    expected_graph_digest: str
    idempotency_key: str = Field(min_length=8, max_length=64)


@router.post("/{view_id}/apply")
async def apply_dataset_curation(
    experiment_id: int,
    view_id: int,
    data: CurationApply,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    from spectra_sherpa.app.api.v1.routes.workflows.data_selections import apply_workflow_data_selection
    from spectra_sherpa.app.db.session import begin_serialized_sqlite_write
    from spectra_sherpa.app.schemas.workflow_data_selection import WorkflowDataSelectionApply

    if current_user.principal_kind != "human":
        raise HTTPException(403, "Applying dataset curation requires a scientist account")
    await begin_serialized_sqlite_write(session)
    await _require_experiment(session, experiment_id, current_user.id)
    view = await _view_or_404(session, experiment_id, view_id)
    from spectra_sherpa.app.models.workflow_data_selection_revision import WorkflowDataSelectionRevision
    from spectra_sherpa.app.services.workflow_data_selections import load_selection_context

    workflow, node, _, saved = await load_selection_context(
        session,
        workflow_id=data.workflow_id,
        source_node_id=data.source_node_id,
        user_id=current_user.id,
        for_update=True,
    )
    replay = await session.scalar(
        select(WorkflowDataSelectionRevision).where(
            WorkflowDataSelectionRevision.workflow_id == data.workflow_id,
            WorkflowDataSelectionRevision.source_node_id == data.source_node_id,
            WorkflowDataSelectionRevision.idempotency_key == data.idempotency_key,
        )
    )
    if replay is not None:
        if workflow.project_id != view.project_id or saved is None:
            raise HTTPException(404, "Dependent workflow not found")
        return await apply_workflow_data_selection(
            data.workflow_id,
            data.source_node_id,
            WorkflowDataSelectionApply(
                expected_revision=data.expected_revision,
                idempotency_key=data.idempotency_key,
                origin="data_page",
                reason=f"Explicitly applied dataset curation: {view.name}",
                selection=_curated_selection(view, replay.selection["dataset_name"]),
            ),
            session,
            current_user,
        )
    state = await _dependent_state(session, current_user, view, data.workflow_id, data.source_node_id, write=True)
    if state["blocked_reason"]:
        raise HTTPException(409, state["blocked_reason"])
    if (
        state["expected_graph_digest"] != data.expected_graph_digest
        or state["expected_revision"] != data.expected_revision
    ):
        raise HTTPException(409, "Workflow changed; reload dependents before applying this definition")
    return await apply_workflow_data_selection(
        data.workflow_id,
        data.source_node_id,
        WorkflowDataSelectionApply(
            expected_revision=data.expected_revision,
            idempotency_key=data.idempotency_key,
            origin="data_page",
            reason=f"Explicitly applied dataset curation: {view.name}",
            selection=state["selection"],
        ),
        session,
        current_user,
    )


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
