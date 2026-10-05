"""Project-level run operations that are not tied to authoring a workflow."""

from __future__ import annotations

import asyncio
import json
import logging
from asyncio import to_thread
from datetime import datetime, timezone
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import JSON, case, cast, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import load_only

from spectra_sherpa.app.api.deps import demo_guard, enforce_demo_execution_quota, get_current_user, get_session
from spectra_sherpa.app.contracts.demo_capabilities import MODEL_USE
from spectra_sherpa.app.contracts.project_access import uses_managed_project_access
from spectra_sherpa.app.contracts.scientific_access import require_scientific_access
from spectra_sherpa.app.models.background_job import BackgroundJob
from spectra_sherpa.app.models.dataset_view import DatasetView
from spectra_sherpa.app.models.execution_run import ExecutionRun
from spectra_sherpa.app.models.model_artifact import ModelArtifact
from spectra_sherpa.app.models.user import User
from spectra_sherpa.app.models.workflow import Workflow
from spectra_sherpa.app.schemas.deploy import BatchPredictRequest, BatchPredictResponse
from spectra_sherpa.app.schemas.execution_runs import (
    CompareRunsRequest,
    ComparisonResponse,
    ExecutionRunOut,
    RunKind,
    RunListItem,
    RunPage,
)
from spectra_sherpa.app.schemas.run_evidence import OutputEvidence, RunEvidence
from spectra_sherpa.app.services.dataset_views import receipt_sha256, verify_selection_receipt
from spectra_sherpa.app.services.deployment_binding import resolve_deployment_binding
from spectra_sherpa.app.services.job_manager import job_manager
from spectra_sherpa.app.services.model_application import apply_model_to_dataset, load_project_dataset
from spectra_sherpa.app.services.run_artifact_roles import attempted_artifact_fields
from spectra_sherpa.app.services.run_metrics import comparison_response
from spectra_sherpa.app.services.run_params import build_effective_params_snapshot

logger = logging.getLogger(__name__)


def _scientific_collection_fields(loaded: Any) -> dict[str, Any]:
    if not hasattr(loaded, "scientific_collection_sha256"):
        return {}
    return {
        "collection_definition_sha256": loaded.collection_definition_sha256,
        "scientific_collection_sha256": loaded.scientific_collection_sha256,
    }


router = APIRouter(prefix="/runs")


class RunDatasetRef(BaseModel):
    experiment_id: int = Field(..., description="My Dataset / Experiment id")
    file_id: int | None = Field(None, description="Optional single file id within the dataset")
    stage: Literal["raw", "preprocessed", "synthetic"] = Field(
        "raw", description="Dataset stage: raw, preprocessed, or synthetic"
    )
    asset_id: str | None = Field(None, min_length=1, max_length=255, description="Exact asset in every source")


class ArtifactBatchRunRequest(BaseModel):
    artifact_uids: list[str] = Field(..., min_length=1, max_length=8)
    dataset: RunDatasetRef
    dataset_view_id: int | None = Field(None, ge=1, description="Exact saved My Dataset definition")
    scope: str = Field("all", pattern="^(all|train|test)$")
    run_name: str | None = Field(None, min_length=1, max_length=255)
    notes: str | None = Field(None, max_length=2000)


class ArtifactBatchRunItemResult(BaseModel):
    artifact_uid: str
    status: Literal["completed", "failed"]
    metrics: dict[str, Any] | None = None
    n_samples: int | None = None
    error: str | None = None


class ArtifactBatchRunResponse(BaseModel):
    status: Literal["completed", "partial", "failed"]
    run: ExecutionRunOut | None = None
    results: list[ArtifactBatchRunItemResult]


async def _resolve_owned_deployment_binding(session: AsyncSession, *, user_id: int, artifact_uid: str):
    artifact = await session.scalar(
        select(ModelArtifact).where(
            ModelArtifact.artifact_uid == artifact_uid,
            ModelArtifact.user_id == user_id,
        )
    )
    if artifact is None or artifact.workflow_id is None:
        raise HTTPException(status_code=404, detail="Model not found")
    try:
        return await resolve_deployment_binding(
            session,
            user_id=user_id,
            workflow_id=artifact.workflow_id,
            artifact_uid=artifact_uid,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


async def _start_file_batch(
    payload: BatchPredictRequest,
    binding,
    files,
    session: AsyncSession,
    current_user: User,
    *,
    input_metadata: dict[str, Any] | None = None,
) -> BatchPredictResponse:
    from spectra_sherpa.app.services.batch_predict import run_batch_prediction

    enforce_demo_execution_quota(current_user.id)
    workflow = binding.workflow
    artifact_uid = binding.artifact.artifact_uid
    run_name = payload.run_name or f"Batch: {payload.folder_path}"
    artifact_attempts = attempted_artifact_fields([artifact_uid])
    run = ExecutionRun(
        project_id=workflow.project_id,
        workflow_id=workflow.id,
        workflow_version_id=binding.artifact.workflow_version_id,
        user_id=current_user.id,
        name=run_name,
        status="running",
        params_snapshot=build_effective_params_snapshot(workflow.nodes),
        results_summary={},
        executed_at=datetime.now(timezone.utc),
        source_type="batch",
        run_kind="batch_inference",
        produced_artifact_uids=[],
        attempted_artifact_uids=artifact_attempts["attempted_artifact_uids"],
        succeeded_artifact_uids=[],
        model_ids=[],
        applied_artifact_uids=artifact_attempts["applied_artifact_uids"],
        source_metadata={
            "folder_path": payload.folder_path,
            "file_pattern": payload.file_pattern,
            "file_count": len(files),
            "asset_id": payload.asset_id,
            **(input_metadata or {}),
        },
        labels=[],
    )
    session.add(run)
    await session.flush()
    job = BackgroundJob(
        user_id=current_user.id,
        job_type="batch_predict",
        execution_run_id=run.id,
        status="pending",
    )
    session.add(job)
    await session.commit()
    await session.refresh(run)
    await session.refresh(job)

    async def _work() -> None:
        from spectra_sherpa.app.db.session import async_session

        async with async_session() as work_session:
            saved_run = await work_session.get(ExecutionRun, run.id)
            await run_batch_prediction(
                work_session,
                job.id,
                saved_run,
                workflow,
                files,
                asset_id=payload.asset_id,
            )

    asyncio.create_task(job_manager.run_job(job.id, _work))
    return BatchPredictResponse(
        job_id=job.id,
        run_id=run.id,
        message=f"Batch prediction started: {len(files)} files",
    )


@router.post(
    "/batch/folder",
    response_model=BatchPredictResponse,
    status_code=201,
    dependencies=[Depends(demo_guard("external_prediction_input"))],
)
async def batch_run_folder(
    payload: BatchPredictRequest,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> BatchPredictResponse:
    """Apply one saved model to files in an authorized server folder."""
    from spectra_sherpa.app.services.batch_predict import discover_files, validate_user_folder_path
    from spectra_sherpa.app.services.workflow_access import validate_workflow_execution_access

    binding = await _resolve_owned_deployment_binding(
        session, user_id=current_user.id, artifact_uid=payload.artifact_uid
    )
    await validate_workflow_execution_access(
        binding.workflow.nodes,
        None,
        current_user.id,
        binding.workflow.project_id,
        session,
    )
    try:
        folder_path = await validate_user_folder_path(session, payload.folder_path, current_user.id)
        files = await asyncio.to_thread(discover_files, str(folder_path), payload.file_pattern)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if not files:
        raise HTTPException(
            status_code=422,
            detail=f"No files found matching '{payload.file_pattern}' in {payload.folder_path}",
        )
    return await _start_file_batch(payload, binding, files, session, current_user)


@router.post("/batch/files/{artifact_uid}", response_model=BatchPredictResponse, status_code=201)
async def batch_run_uploaded_files(
    artifact_uid: str,
    request: Request,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> BatchPredictResponse:
    """Apply one saved model to privately uploaded files and save the run."""
    from spectra_sherpa.app.contracts.prediction_access import require_private_prediction
    from spectra_sherpa.app.services.prediction_upload import persist_prediction_files, read_prediction_files

    await require_private_prediction(session, current_user.id)
    binding = await _resolve_owned_deployment_binding(session, user_id=current_user.id, artifact_uid=artifact_uid)
    uploads = await read_prediction_files(request)
    await require_private_prediction(session, current_user.id)
    try:
        files, receipts = await asyncio.to_thread(persist_prediction_files, current_user.id, uploads)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    payload = BatchPredictRequest(
        folder_path=str(files[0].parent),
        artifact_uid=artifact_uid,
        run_name=f"Batch prediction: {binding.artifact.name}",
    )
    return await _start_file_batch(
        payload,
        binding,
        files,
        session,
        current_user,
        input_metadata=receipts,
    )


def _run_belongs_to_project_clause(user_id: int, project_id: int):
    return (
        ExecutionRun.user_id == user_id,
        ExecutionRun.project_id == project_id,
    )


def _workflow_name_query():
    # Never expose a workflow name across ownership or project boundaries.
    return (
        select(Workflow.name)
        .where(
            Workflow.id == ExecutionRun.workflow_id,
            Workflow.user_id == ExecutionRun.user_id,
            Workflow.project_id.is_not_distinct_from(ExecutionRun.project_id),
        )
        .scalar_subquery()
    )


def _run_navigation(run: ExecutionRun, workflow_name: str | None) -> RunListItem:
    item = RunListItem.model_validate(run)
    item.workflow_name = workflow_name
    item.display_name = workflow_name if workflow_name and run.source_type == "auto" else run.name
    return item


def _navigation_columns():
    return [
        getattr(ExecutionRun, name)
        for name in RunListItem.model_fields
        if name not in {"display_name", "workflow_name"}
    ] + [ExecutionRun.source_type]


@router.get("", response_model=RunPage)
async def list_project_runs(
    project_id: int = Query(..., description="Project whose runs should be listed"),
    kind: RunKind | None = Query(None, description="Optional run_kind filter"),
    artifact_uid: str | None = Query(None, description="Optional applied artifact filter"),
    sort_by: Annotated[Literal["name", "status", "run_kind", "executed_at"], Query()] = "executed_at",
    sort_order: Annotated[Literal["asc", "desc"], Query()] = "desc",
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> RunPage:
    """Page navigation metadata without loading matrices, graphs or diagnostics."""
    query = select(ExecutionRun).where(*_run_belongs_to_project_clause(current_user.id, project_id))
    if kind:
        query = query.where(ExecutionRun.run_kind == kind)
    if artifact_uid:
        json_items = func.json_each if session.get_bind().dialect.name == "sqlite" else func.json_array_elements_text
        filters = []
        for column in (
            ExecutionRun.produced_artifact_uids,
            ExecutionRun.attempted_artifact_uids,
            ExecutionRun.succeeded_artifact_uids,
        ):
            value = column
            if session.get_bind().dialect.name != "sqlite":
                value = case((func.json_typeof(column) == "array", column), else_=cast("[]", JSON))
            items = json_items(value).table_valued("value")
            if session.get_bind().dialect.name != "sqlite":
                items = items.render_derived()
            filters.append(select(1).select_from(items).where(items.c.value == artifact_uid).exists())
        query = query.where(or_(*filters))
    total = await session.scalar(select(func.count()).select_from(query.subquery()))
    sort_column = {
        "name": case(
            (ExecutionRun.source_type == "auto", func.coalesce(_workflow_name_query(), ExecutionRun.name)),
            else_=ExecutionRun.name,
        ),
        "status": ExecutionRun.status,
        "run_kind": ExecutionRun.run_kind,
        "executed_at": ExecutionRun.executed_at,
    }[sort_by]
    order = sort_column.asc if sort_order == "asc" else sort_column.desc
    id_order = ExecutionRun.id.asc if sort_order == "asc" else ExecutionRun.id.desc
    result = await session.execute(
        query.add_columns(_workflow_name_query())
        .options(load_only(*_navigation_columns()))
        .order_by(order(), id_order())
        .limit(limit)
        .offset(offset)
    )
    return RunPage(
        runs=[_run_navigation(run, workflow_name) for run, workflow_name in result.all()],
        total=total or 0,
        limit=limit,
        offset=offset,
    )


@router.get("/{run_id}", response_model=ExecutionRunOut)
async def get_project_run(
    run_id: int,
    project_id: int = Query(...),
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> ExecutionRunOut:
    run = await session.scalar(
        select(ExecutionRun).where(
            *_run_belongs_to_project_clause(current_user.id, project_id), ExecutionRun.id == run_id
        )
    )
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")
    return ExecutionRunOut.model_validate(run)


@router.post("/compare", response_model=ComparisonResponse)
async def compare_project_runs(
    payload: CompareRunsRequest,
    project_id: int = Query(..., description="Project whose runs should be compared"),
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> ComparisonResponse:
    """Compare selected runs across all workflows in a project."""
    query = (
        select(ExecutionRun)
        .where(
            *_run_belongs_to_project_clause(current_user.id, project_id),
            ExecutionRun.id.in_(payload.run_ids),
        )
        .order_by(ExecutionRun.id)
    )
    result = await session.execute(query)
    runs = list(result.scalars().all())

    if len(runs) < 2:
        raise HTTPException(
            status_code=400,
            detail=f"Need at least 2 runs to compare, found {len(runs)}",
        )
    if len(runs) != len(set(payload.run_ids)):
        raise HTTPException(status_code=404, detail="One or more selected runs are unavailable in this project.")

    if not set(payload.evaluation_selections).issubset(payload.run_ids):
        raise HTTPException(status_code=400, detail="Evaluation selections must belong to the selected runs.")
    return await to_thread(comparison_response, runs, payload.evaluation_selections)


def _validated_run_evidence(record: Any) -> RunEvidence:
    try:
        return RunEvidence.model_validate(record or {})
    except ValidationError as exc:
        raise HTTPException(status_code=409, detail="Run evidence metadata is invalid or unsupported.") from exc


async def _owned_run(run_id: int, project_id: int, session: AsyncSession, user: User) -> ExecutionRun:
    run = await session.scalar(
        select(ExecutionRun)
        .options(
            load_only(
                *_navigation_columns(),
                ExecutionRun.evidence_completeness,
                ExecutionRun.node_statuses,
                ExecutionRun.integrity_hash,
                ExecutionRun.error,
                ExecutionRun.notes,
                ExecutionRun.params_snapshot,
                ExecutionRun.environment_snapshot,
            )
        )
        .where(*_run_belongs_to_project_clause(user.id, project_id), ExecutionRun.id == run_id)
    )
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")
    return run


@router.get("/{run_id}/evidence")
async def inspect_run_evidence(
    run_id: int,
    project_id: int = Query(...),
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    from spectra_sherpa.app.services.run_output_retention import DETAIL_METADATA_BUDGET_BYTES

    run = await _owned_run(run_id, project_id, session, current_user)
    evidence = _validated_run_evidence(run.evidence_completeness)
    if not evidence.outputs:
        await session.refresh(run, attribute_names=["results_summary"])
        for node_id, value in (run.results_summary or {}).items():
            ports = value if isinstance(value, dict) and value.get("type") != "SherpaDataset" else {"default": value}
            evidence.outputs[node_id] = {
                port: OutputEvidence(
                    state="unverified",
                    reason="Historical output was saved before qualified retention; it may be compacted.",
                    role=port,
                )
                for port in ports
            }
    workflow_name = await session.scalar(
        select(_workflow_name_query()).select_from(ExecutionRun).where(ExecutionRun.id == run.id)
    )
    response = {
        "run": _run_navigation(run, workflow_name).model_dump(mode="json"),
        "evidence": evidence.model_dump(),
        "evidence_gaps": [item.model_dump() for item in evidence.gaps()],
        "node_statuses": run.node_statuses or {},
        "integrity_hash": run.integrity_hash,
        "error": run.error,
        "notes": run.notes,
        "params_snapshot": run.params_snapshot,
        "environment_snapshot": run.environment_snapshot,
    }
    if len(json.dumps(response, ensure_ascii=True, separators=(",", ":")).encode()) > DETAIL_METADATA_BUDGET_BYTES:
        raise HTTPException(
            status_code=413,
            detail=(
                "Run inspection metadata exceeds the 512 KiB response budget; "
                "individual retained outputs remain available."
            ),
        )
    return response


@router.get("/{run_id}/outputs/{node_id}/{port}")
async def get_retained_run_output(
    run_id: int,
    node_id: str,
    port: str,
    project_id: int = Query(...),
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    from spectra_sherpa.app.services.run_output_retention import read_output

    run = await _owned_run(run_id, project_id, session, current_user)
    evidence = _validated_run_evidence(run.evidence_completeness)
    item = evidence.outputs.get(node_id, {}).get(port)
    if item is None:
        raise HTTPException(
            status_code=410,
            detail="This output was not retained with a qualified identity; inspect historical completeness.",
        )
    if item.storage is None:
        raise HTTPException(status_code=410, detail=item.reason or "Output was not retained.")
    try:
        value = await to_thread(read_output, current_user.id, item)
    except FileNotFoundError as exc:
        raise HTTPException(
            status_code=410, detail="Retained output is missing; restore the run-output volume from backup."
        ) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail="Retained output failed integrity validation.") from exc
    return {"evidence": item.model_dump(), "value": value}


@router.post("/storage/reclaim")
async def reclaim_run_storage(
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> dict[str, int]:
    from spectra_sherpa.app.services.run_output_retention import prune_unreferenced_outputs, retained_storage_usage

    records = await session.scalars(
        select(ExecutionRun.evidence_completeness).where(ExecutionRun.user_id == current_user.id)
    )
    retained = set()
    for record in records:
        evidence = _validated_run_evidence(record)
        retained.update(item.sha256 for ports in evidence.outputs.values() for item in ports.values() if item.sha256)
    removed = await to_thread(prune_unreferenced_outputs, current_user.id, retained)
    usage = await to_thread(retained_storage_usage, current_user.id)
    return {"removed_files": removed, **usage}


async def _load_artifacts(
    session: AsyncSession,
    *,
    user_id: int,
    artifact_uids: list[str],
) -> list[ModelArtifact]:
    result = await session.execute(
        select(ModelArtifact)
        .where(
            or_(ModelArtifact.user_id == user_id, uses_managed_project_access()),
            ModelArtifact.artifact_uid.in_(artifact_uids),
            ModelArtifact.is_active == True,  # noqa: E712
        )
        .execution_options(populate_existing=True)
    )
    artifacts = list(result.scalars().all())
    by_uid = {artifact.artifact_uid: artifact for artifact in artifacts}
    missing = [uid for uid in artifact_uids if uid not in by_uid]
    if missing:
        raise HTTPException(status_code=404, detail=f"Model artifact not found: {missing[0]}")
    ordered = [by_uid[uid] for uid in artifact_uids]
    from spectra_sherpa.app.services.model_store import (
        ModelArtifactIntegrityError,
        verify_model_artifact_storage_record,
    )

    for artifact in ordered:
        await require_scientific_access(
            session, user_id, artifact.project_id, "execute", resource_owner_id=artifact.user_id
        )
        if uses_managed_project_access() and artifact.workflow_id is not None:
            from spectra_sherpa.app.models.workflow import Workflow

            workflow = await session.get(Workflow, artifact.workflow_id, populate_existing=True)
            if workflow is None or workflow.project_id != artifact.project_id:
                raise HTTPException(404, "Model is outside its workflow project custody")
    try:
        for artifact in ordered:
            verify_model_artifact_storage_record(artifact)
    except (FileNotFoundError, RuntimeError, ModelArtifactIntegrityError, ValueError) as exc:
        raise HTTPException(status_code=409, detail="Model artifact storage is unavailable or invalid") from exc
    return ordered


def _compact_model_metrics(result: dict[str, Any]) -> dict[str, Any]:
    metrics = result.get("metrics")
    if isinstance(metrics, dict):
        return metrics
    compact: dict[str, Any] = {"n_samples": result.get("n_samples")}
    if result.get("predictions") is not None:
        compact["prediction_count"] = len(result.get("predictions") or [])
    if result.get("transformed") is not None:
        transformed = result.get("transformed") or []
        compact["transformed_rows"] = len(transformed)
    return {k: v for k, v in compact.items() if v is not None}


async def _load_batch_dataset(session, user_id, payload):
    try:
        view = None
        if payload.dataset_view_id is not None:
            if payload.scope != "all" or payload.dataset.file_id is not None or payload.dataset.asset_id is not None:
                raise HTTPException(422, "Saved definitions use their exact cohort; choose Included samples")
            view = await session.scalar(
                select(DatasetView).where(
                    DatasetView.id == payload.dataset_view_id,
                    DatasetView.experiment_id == payload.dataset.experiment_id,
                    DatasetView.deleted_at.is_(None),
                )
            )
            if view is None:
                raise HTTPException(404, "Saved dataset definition not found")
            if receipt_sha256(view.selection) != view.selection_sha256:
                raise HTTPException(409, "Saved dataset definition changed after it was recorded")
        receipt = view.selection if view is not None else None
        loaded = await load_project_dataset(
            session,
            user_id=user_id,
            experiment_id=payload.dataset.experiment_id,
            file_id=payload.dataset.file_id if receipt is None else None,
            file_ids=receipt["selected_file_ids"] if receipt is not None else None,
            stage=payload.dataset.stage if receipt is None else receipt["stage"],
            asset_id=payload.dataset.asset_id if receipt is None else receipt["asset_id"],
        )
        if view is not None:
            if loaded.project_id != view.project_id:
                raise HTTPException(404, "Saved dataset definition is outside this project")
            try:
                verify_selection_receipt(loaded, receipt)
            except ValueError as exc:
                raise HTTPException(409, "Saved dataset definition no longer matches its source or cohort") from exc
        return loaded, view
    except KeyError as exc:
        raise HTTPException(409, "Saved dataset definition is incomplete") from exc
    except ValueError as exc:
        logger.warning("Batch dataset admission failed: %s", exc)
        detail = (
            "Dataset could not be loaded with the selected stage and scientific result. Check its source files."
            if uses_managed_project_access()
            else str(exc)
        )
        raise HTTPException(400, detail) from exc


@router.post("/batch", response_model=ArtifactBatchRunResponse, status_code=201)
async def batch_run_artifacts(
    payload: ArtifactBatchRunRequest,
    response: Response,
    _dg: None = Depends(demo_guard(MODEL_USE)),
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> ArtifactBatchRunResponse:
    """Apply saved artifacts to a durable My Dataset and persist every attempted batch.

    Returns HTTP 201 when every artifact succeeds and HTTP 207 when at least
    one artifact fails.  Each artifact has its own result object so a corrupt
    or incompatible artifact does not hide the other outcomes.
    """
    artifact_uids = list(dict.fromkeys(payload.artifact_uids))
    artifacts = await _load_artifacts(session, user_id=current_user.id, artifact_uids=artifact_uids)
    model_identity = [
        (a.artifact_uid, a.project_id, a.workflow_id, a.workflow_version_id, a.integrity_hash, a.training_dataset_id)
        for a in artifacts
    ]
    logger.info(
        "batch run requested user_id=%s artifact_count=%d dataset_id=%s scope=%s",
        current_user.id,
        len(artifact_uids),
        payload.dataset.experiment_id,
        payload.scope,
    )
    lineage_artifacts = [artifact for artifact in artifacts if artifact.workflow_id is not None]
    if not lineage_artifacts:
        raise HTTPException(status_code=400, detail="Selected artifacts have no producing workflow lineage")
    workflow_ids = {artifact.workflow_id for artifact in lineage_artifacts}
    has_complete_lineage = len(lineage_artifacts) == len(artifacts) and len(workflow_ids) == 1
    primary_workflow_id = next(iter(workflow_ids)) if has_complete_lineage else None
    workflow_version_ids = {artifact.workflow_version_id for artifact in lineage_artifacts}
    primary_workflow_version_id = (
        next(iter(workflow_version_ids)) if primary_workflow_id is not None and len(workflow_version_ids) == 1 else None
    )

    try:
        loaded, view = await _load_batch_dataset(session, current_user.id, payload)
        from spectra_sherpa.app.contracts.demo_policy import require_trial_dataset_access

        await require_trial_dataset_access(
            session=session,
            user_id=current_user.id,
            workflow_project_id=loaded.project_id,
            experiment_id=loaded.experiment_id,
            stage=loaded.stage,
            file_id=payload.dataset.file_id,
            file_ids=view.selection["selected_file_ids"] if view is not None else None,
            asset_id=loaded.asset_id,
            loaded_dataset=loaded,
        )
        for artifact in artifacts:
            if artifact.project_id != loaded.project_id:
                raise ValueError("All selected artifacts and the dataset must belong to the same project")
        from spectra_sherpa.app.services.dag.presentation_limits import require_bounded_presentation

        require_bounded_presentation(loaded.dataset, surface="Batch application", multiplier=len(artifacts))
        enforce_demo_execution_quota(current_user.id)
        applied_results: list[dict[str, Any]] = []
        item_results: list[ArtifactBatchRunItemResult] = []
        executions: dict[str, dict[str, Any]] = {}
        for artifact in artifacts:
            # Authorization failures are request failures, never partial science.
            await require_scientific_access(session, current_user.id, loaded.project_id, "execute")
            try:
                capture: dict[str, Any] = {}
                executions[artifact.artifact_uid] = capture
                applied = await apply_model_to_dataset(
                    artifact.artifact_uid,
                    loaded.dataset,
                    scope=payload.scope,
                    execution_evidence=capture,
                    presentation_multiplier=len(artifacts),
                )
                applied_results.append(applied)
                item_results.append(
                    ArtifactBatchRunItemResult(
                        artifact_uid=artifact.artifact_uid,
                        status="completed",
                        metrics=_compact_model_metrics(applied),
                        n_samples=applied.get("n_samples"),
                    )
                )
            except HTTPException:
                raise
            except Exception as exc:
                logger.warning(
                    "batch artifact apply failed user_id=%s artifact_uid=%s dataset_id=%s: %s",
                    current_user.id,
                    artifact.artifact_uid,
                    loaded.experiment_id,
                    exc,
                )
                item_results.append(
                    ArtifactBatchRunItemResult(
                        artifact_uid=artifact.artifact_uid,
                        status="failed",
                        error=(
                            "Model application refused: check feature axes, target roles, and sample scope."
                            if uses_managed_project_access()
                            else str(exc)
                        ),
                    )
                )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    # Re-admit after compute and before retention/publication. The write admission
    # serializes publication with managed account/project/grant mutations.
    await require_scientific_access(session, current_user.id, loaded.project_id, "write")
    current_artifacts = await _load_artifacts(session, user_id=current_user.id, artifact_uids=artifact_uids)
    if model_identity != [
        (a.artifact_uid, a.project_id, a.workflow_id, a.workflow_version_id, a.integrity_hash, a.training_dataset_id)
        for a in current_artifacts
    ]:
        raise HTTPException(404, "Model project authority changed during batch application")

    if uses_managed_project_access() or view is not None:
        current_dataset, current_view = await _load_batch_dataset(session, current_user.id, payload)
        if view is not None and (current_view is None or current_view.selection_sha256 != view.selection_sha256):
            raise HTTPException(409, "Saved dataset definition changed during batch application")
        if any(
            getattr(current_dataset, key) != getattr(loaded, key)
            for key in (
                "experiment_id",
                "project_id",
                "file_ids",
                "stage",
                "asset_id",
                "source_manifest_sha256",
                "collection_definition_sha256",
                "scientific_collection_sha256",
            )
        ):
            raise HTTPException(409, "Dataset authority changed during batch application; rerun the batch")

    successful_uids = [result["artifact_uid"] for result in applied_results]
    failed_items = [item for item in item_results if item.status == "failed"]
    outcome: Literal["failed", "partial", "completed"] = (
        "failed" if not applied_results else "partial" if failed_items else "completed"
    )

    run_name = (
        payload.run_name or f"Batch inference — {len(artifact_uids)} artifact{'s' if len(artifact_uids) != 1 else ''}"
    )
    results_summary = {result["artifact_uid"]: _compact_model_metrics(result) for result in applied_results}
    source_metadata = {
        "dataset": {
            "experiment_id": loaded.experiment_id,
            "name": loaded.experiment_name,
            "project_id": loaded.project_id,
            "file_ids": loaded.file_ids,
            "stage": loaded.stage,
            "asset_id": loaded.asset_id,
            "source_manifest_sha256": loaded.source_manifest_sha256,
            **_scientific_collection_fields(loaded),
        },
        "scope": payload.scope,
        "dataset_view": (
            {"id": view.id, "name": view.name, "selection_sha256": view.selection_sha256} if view is not None else None
        ),
        "artifact_uids": artifact_uids,
        "successful_artifact_uids": successful_uids,
        "artifact_lineage": [
            {
                "artifact_uid": artifact.artifact_uid,
                "workflow_id": artifact.workflow_id,
                "workflow_version_id": artifact.workflow_version_id,
                "source_run_id": artifact.source_run_id,
            }
            for artifact in artifacts
        ],
        "results": [item.model_dump() for item in item_results],
    }
    from spectra_sherpa.app.services.run_output_retention import retain_run_outputs

    # Preserve the loaded selection, not a pointer that reloads changed data.
    retained = {result["artifact_uid"]: {"default": result} for result in applied_results}
    for item in failed_items:
        retained[item.artifact_uid] = {"default": item.model_dump()}
    retained["__application__"] = {"input": loaded.dataset, "selection": source_metadata}
    definition: dict[str, Any] = {"schema_version": 1, "name": run_name, "nodes": [], "edges": []}
    diagnostics: dict[str, Any] = {"_scientific_values": {}, "_scientific_presentations": {}}
    node_statuses = {item.artifact_uid: "completed" if item.status == "completed" else "error" for item in item_results}
    for uid, capture in executions.items():

        def address(node_id: str) -> str:
            return f"{uid}::{node_id}"

        for node_id, output in capture.get("outputs", {}).items():
            retained[address(node_id)] = output
            node_statuses[address(node_id)] = "completed"
        for key, value in capture.get("diagnostics", {}).items():
            if key in {"_scientific_values", "_scientific_presentations"}:
                diagnostics[key].update({address(node_id): record for node_id, record in value.items()})
            else:
                diagnostics[address(key)] = value
        for node in capture.get("definition", {}).get("nodes", []):
            definition["nodes"].append({**node, "node_id": address(node["node_id"])})
            node_address = address(node["node_id"])
            node_statuses[node_address] = capture.get("node_statuses", {}).get(
                node["node_id"], node_statuses.get(node_address, "pending")
            )
        for edge in capture.get("definition", {}).get("edges", []):
            definition["edges"].append(
                {**edge, "from_node_id": address(edge["from_node_id"]), "to_node_id": address(edge["to_node_id"])}
            )
    if definition["nodes"]:
        retained["__workflow__"] = {"definition": definition}
    evidence = await to_thread(retain_run_outputs, current_user.id, retained, diagnostics)
    artifact_attempts = attempted_artifact_fields(artifact_uids)
    run = ExecutionRun(
        project_id=loaded.project_id,
        workflow_id=primary_workflow_id,
        workflow_version_id=primary_workflow_version_id,
        user_id=current_user.id,
        name=run_name,
        status="error" if outcome == "failed" else outcome,
        params_snapshot={node["node_id"]: node.get("parameters", {}) for node in definition["nodes"]},
        results_summary=results_summary,
        diagnostics=None,
        node_statuses=node_statuses,
        error="All selected model applications failed. See individual outcomes." if outcome == "failed" else None,
        integrity_hash=None,
        executed_at=datetime.now(timezone.utc),
        notes=payload.notes,
        labels=[],
        source_type="batch",
        source_metadata=source_metadata,
        produced_artifact_uids=[],
        attempted_artifact_uids=artifact_attempts["attempted_artifact_uids"],
        succeeded_artifact_uids=successful_uids,
        model_ids=successful_uids,
        run_kind="batch_inference",
        applied_artifact_uids=artifact_attempts["applied_artifact_uids"],
        evidence_completeness=evidence,
    )
    session.add(run)
    await session.flush()

    from spectra_sherpa.app.services.audit import audit_emitter

    batch_actions = {
        "completed": "workflow.run.batch_completed",
        "partial": "workflow.run.batch_partial",
        "failed": "workflow.run.batch_failed",
    }
    audit_emitter.emit(
        session=session,
        action=batch_actions[outcome],
        target_type="ExecutionRun",
        target_id=run.id,
        after={
            "run_id": run.id,
            "status": run.status,
            "artifact_uids": artifact_uids,
            "successful_artifact_uids": successful_uids,
            "failed_artifact_uids": [item.artifact_uid for item in failed_items],
            "dataset_id": loaded.experiment_id,
            "asset_id": loaded.asset_id,
            "source_manifest_sha256": loaded.source_manifest_sha256,
            **_scientific_collection_fields(loaded),
            "scope": payload.scope,
        },
        context={"results": [item.model_dump() for item in item_results]},
    )
    await session.commit()
    await session.refresh(run)
    logger.info(
        "batch run completed run_id=%s user_id=%s artifact_count=%d dataset_id=%s",
        run.id,
        current_user.id,
        len(artifact_uids),
        loaded.experiment_id,
    )
    if failed_items:
        response.status_code = 207
    else:
        response.status_code = 201
    return ArtifactBatchRunResponse(
        status=outcome,
        run=ExecutionRunOut.model_validate(run),
        results=item_results,
    )


@router.delete("/{run_id}", status_code=204, response_class=Response)
async def delete_project_run(
    run_id: int,
    project_id: int = Query(..., description="Project whose run should be deleted"),
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> Response:
    """Delete a saved run from a project-level run history."""
    query = select(ExecutionRun).where(
        *_run_belongs_to_project_clause(current_user.id, project_id),
        ExecutionRun.id == run_id,
    )
    result = await session.execute(query)
    run = result.scalar_one_or_none()
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")

    from spectra_sherpa.app.services.run_provenance import provenance_cleanup, require_unretained_source

    await require_unretained_source(session, run_id=run.id)
    async with provenance_cleanup(session):
        await session.delete(run)
        await session.commit()
    return Response(status_code=204)
