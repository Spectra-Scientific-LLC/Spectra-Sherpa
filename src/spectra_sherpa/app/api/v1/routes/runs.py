"""Project-level run operations that are not tied to authoring a workflow."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from spectra_sherpa.app.api.deps import demo_guard, enforce_demo_execution_quota, get_current_user, get_session
from spectra_sherpa.app.models.execution_run import ExecutionRun
from spectra_sherpa.app.models.model_artifact import ModelArtifact
from spectra_sherpa.app.models.user import User
from spectra_sherpa.app.schemas.execution_runs import (
    CompareRunsRequest,
    ComparisonResponse,
    ExecutionRunList,
    ExecutionRunOut,
    RunKind,
)
from spectra_sherpa.app.services.model_application import apply_model_to_dataset, load_project_dataset
from spectra_sherpa.app.services.run_metrics import comparison_response

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/runs")


class RunDatasetRef(BaseModel):
    experiment_id: int = Field(..., description="My Dataset / Experiment id")
    file_id: int | None = Field(None, description="Optional single file id within the dataset")
    stage: str = Field("raw", description="Dataset stage: raw, preprocessed, or synthetic")


class ArtifactBatchRunRequest(BaseModel):
    artifact_uids: list[str] = Field(..., min_length=1, max_length=8)
    dataset: RunDatasetRef
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


def _run_belongs_to_project_clause(user_id: int, project_id: int):
    return (
        ExecutionRun.user_id == user_id,
        ExecutionRun.project_id == project_id,
    )


@router.get("", response_model=ExecutionRunList)
async def list_project_runs(
    project_id: int = Query(..., description="Project whose runs should be listed"),
    kind: RunKind | None = Query(None, description="Optional run_kind filter"),
    artifact_uid: str | None = Query(None, description="Optional applied artifact filter"),
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> ExecutionRunList:
    """List every workflow/data/batch run for a project, newest first."""
    query = select(ExecutionRun).where(*_run_belongs_to_project_clause(current_user.id, project_id))
    if kind:
        query = query.where(ExecutionRun.run_kind == kind)
    query = query.order_by(ExecutionRun.executed_at.desc(), ExecutionRun.id.desc())
    result = await session.execute(query)
    runs = list(result.scalars().all())

    if artifact_uid:
        runs = [
            run
            for run in runs
            if artifact_uid in (run.applied_artifact_uids or []) or artifact_uid in (run.model_ids or [])
        ]

    return ExecutionRunList(
        runs=[ExecutionRunOut.model_validate(run) for run in runs],
        total=len(runs),
    )


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

    return comparison_response(runs)


async def _load_artifacts(
    session: AsyncSession,
    *,
    user_id: int,
    artifact_uids: list[str],
) -> list[ModelArtifact]:
    result = await session.execute(
        select(ModelArtifact).where(
            ModelArtifact.user_id == user_id,
            ModelArtifact.artifact_uid.in_(artifact_uids),
            ModelArtifact.is_active == True,  # noqa: E712
        )
    )
    artifacts = list(result.scalars().all())
    by_uid = {artifact.artifact_uid: artifact for artifact in artifacts}
    missing = [uid for uid in artifact_uids if uid not in by_uid]
    if missing:
        raise HTTPException(status_code=404, detail=f"Model artifact not found: {missing[0]}")
    return [by_uid[uid] for uid in artifact_uids]


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


@router.post("/batch", response_model=ArtifactBatchRunResponse, status_code=201)
async def batch_run_artifacts(
    payload: ArtifactBatchRunRequest,
    response: Response,
    _dg: None = Depends(demo_guard("artifact_batch_run")),
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> ArtifactBatchRunResponse:
    """Apply saved artifacts to a durable My Dataset and persist successful results.

    Returns HTTP 201 when every artifact succeeds and HTTP 207 when at least
    one artifact fails.  Each artifact has its own result object so a corrupt
    or incompatible artifact does not hide the other outcomes.
    """
    artifact_uids = list(dict.fromkeys(payload.artifact_uids))
    artifacts = await _load_artifacts(session, user_id=current_user.id, artifact_uids=artifact_uids)
    logger.info(
        "batch run requested user_id=%s artifact_count=%d dataset_id=%s scope=%s",
        current_user.id,
        len(artifact_uids),
        payload.dataset.experiment_id,
        payload.scope,
    )
    lineage_artifact = next((artifact for artifact in artifacts if artifact.workflow_id is not None), None)
    if lineage_artifact is None:
        raise HTTPException(status_code=400, detail="Selected artifacts have no producing workflow lineage")
    primary_workflow_id = lineage_artifact.workflow_id
    if primary_workflow_id is None:
        raise HTTPException(status_code=400, detail="Selected artifacts have no producing workflow lineage")

    try:
        loaded = await load_project_dataset(
            session,
            user_id=current_user.id,
            experiment_id=payload.dataset.experiment_id,
            file_id=payload.dataset.file_id,
            stage=payload.dataset.stage,
        )
        for artifact in artifacts:
            if artifact.project_id != loaded.project_id:
                raise ValueError("All selected artifacts and the dataset must belong to the same project")
        enforce_demo_execution_quota(current_user.id)
        applied_results: list[dict[str, Any]] = []
        item_results: list[ArtifactBatchRunItemResult] = []
        for artifact in artifacts:
            try:
                applied = apply_model_to_dataset(artifact.artifact_uid, loaded.dataset, scope=payload.scope)
                applied_results.append(applied)
                item_results.append(
                    ArtifactBatchRunItemResult(
                        artifact_uid=artifact.artifact_uid,
                        status="completed",
                        metrics=_compact_model_metrics(applied),
                        n_samples=applied.get("n_samples"),
                    )
                )
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
                        error=str(exc),
                    )
                )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    successful_uids = [result["artifact_uid"] for result in applied_results]
    failed_items = [item for item in item_results if item.status == "failed"]
    if not applied_results:
        from spectra_sherpa.app.services.audit import audit_emitter

        response.status_code = 207
        audit_emitter.emit(
            session=session,
            action="workflow.run.batch_failed",
            target_type="ExecutionRun",
            target_id="unpersisted",
            after={
                "artifact_uids": artifact_uids,
                "dataset_id": loaded.experiment_id,
                "scope": payload.scope,
                "failure_count": len(failed_items),
            },
            context={"results": [item.model_dump() for item in item_results]},
        )
        await session.commit()
        logger.info(
            "batch run failed user_id=%s artifact_count=%d dataset_id=%s",
            current_user.id,
            len(artifact_uids),
            loaded.experiment_id,
        )
        return ArtifactBatchRunResponse(status="failed", run=None, results=item_results)

    run_name = (
        payload.run_name
        or f"Batch inference — {len(successful_uids)} artifact{'s' if len(successful_uids) != 1 else ''}"
    )
    results_summary = {result["artifact_uid"]: _compact_model_metrics(result) for result in applied_results}
    source_metadata = {
        "dataset": {
            "experiment_id": loaded.experiment_id,
            "name": loaded.experiment_name,
            "project_id": loaded.project_id,
            "file_ids": loaded.file_ids,
            "stage": loaded.stage,
        },
        "scope": payload.scope,
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
    run = ExecutionRun(
        project_id=loaded.project_id,
        workflow_id=primary_workflow_id,
        workflow_version_id=lineage_artifact.workflow_version_id,
        user_id=current_user.id,
        name=run_name,
        status="partial" if failed_items else "completed",
        params_snapshot={},
        results_summary=results_summary,
        diagnostics=None,
        node_statuses=None,
        error=None,
        integrity_hash=None,
        executed_at=datetime.now(timezone.utc),
        notes=payload.notes,
        labels=[],
        source_type="batch",
        source_metadata=source_metadata,
        model_ids=successful_uids,
        run_kind="batch_inference",
        applied_artifact_uids=successful_uids,
    )
    session.add(run)
    await session.flush()

    from spectra_sherpa.app.services.audit import audit_emitter

    audit_emitter.emit(
        session=session,
        action="workflow.run.batch_completed" if not failed_items else "workflow.run.batch_partial",
        target_type="ExecutionRun",
        target_id=run.id,
        after={
            "run_id": run.id,
            "status": run.status,
            "artifact_uids": artifact_uids,
            "successful_artifact_uids": successful_uids,
            "failed_artifact_uids": [item.artifact_uid for item in failed_items],
            "dataset_id": loaded.experiment_id,
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
        status="partial" if failed_items else "completed",
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

    await session.delete(run)
    await session.commit()
    return Response(status_code=204)
