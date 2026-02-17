"""
Deploy API — folder watches, batch prediction, labels, prediction history.

Batch prediction is triggered from the Experiments page (batch run tab).
Folder watches are managed from the Deploy page (monitoring tab).
Both share the same per-file execution engine in batch_predict.py.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from spectra_sherpa.app.api.deps import get_current_user, get_session
from spectra_sherpa.app.models.background_job import BackgroundJob
from spectra_sherpa.app.models.batch_prediction import BatchPrediction
from spectra_sherpa.app.models.execution_run import ExecutionRun
from spectra_sherpa.app.models.folder_watch import FolderWatch
from spectra_sherpa.app.models.user import User
from spectra_sherpa.app.schemas.deploy import (
    BatchPredictRequest,
    BatchPredictResponse,
    BatchPredictionList,
    BatchPredictionOut,
    FolderWatchCreate,
    FolderWatchOut,
    FolderWatchUpdate,
    UpdateLabelsRequest,
)
from spectra_sherpa.app.schemas.execution_runs import ExecutionRunList, ExecutionRunOut
from spectra_sherpa.app.services.job_manager import job_manager

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/deploy")


# ---------------------------------------------------------------------------
# Labels
# ---------------------------------------------------------------------------

@router.patch("/runs/{run_id}/labels", response_model=ExecutionRunOut)
async def update_labels(
    run_id: int,
    payload: UpdateLabelsRequest,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> ExecutionRunOut:
    """Update labels on any ExecutionRun owned by the current user."""
    query = select(ExecutionRun).where(
        ExecutionRun.id == run_id,
        ExecutionRun.user_id == current_user.id,
    )
    result = await session.execute(query)
    run = result.scalar_one_or_none()
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")

    run.labels = payload.labels
    await session.commit()
    await session.refresh(run)
    return ExecutionRunOut.model_validate(run)


# ---------------------------------------------------------------------------
# Batch Predict (called from Experiments page)
# ---------------------------------------------------------------------------

@router.post(
    "/workflows/{workflow_id}/predict/batch",
    response_model=BatchPredictResponse,
    status_code=201,
)
async def batch_predict(
    workflow_id: int,
    payload: BatchPredictRequest,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> BatchPredictResponse:
    """
    Start a batch prediction job.

    Discovers files in the given folder, creates an ExecutionRun and a
    BackgroundJob, then processes each file through the workflow.
    """
    from spectra_sherpa.app.services.batch_predict import (
        discover_files,
        load_workflow_with_graph,
        run_batch_prediction,
    )

    workflow = await load_workflow_with_graph(session, workflow_id, current_user.id)

    # Discover files
    try:
        files = discover_files(payload.folder_path, payload.file_pattern)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    if not files:
        raise HTTPException(
            status_code=422,
            detail=f"No files found matching '{payload.file_pattern}' in {payload.folder_path}",
        )

    # Build params snapshot from workflow nodes
    params_snapshot: dict = {}
    for node in workflow.nodes:
        if node.parameters:
            params_snapshot[node.node_id] = node.parameters

    # Get latest version
    latest_version_id = workflow.versions[0].id if workflow.versions else None

    # Create ExecutionRun
    run_name = payload.run_name or f"Batch: {payload.folder_path}"
    run = ExecutionRun(
        workflow_id=workflow_id,
        workflow_version_id=latest_version_id,
        user_id=current_user.id,
        name=run_name,
        status="running",
        params_snapshot=params_snapshot,
        results_summary={},
        executed_at=datetime.now(timezone.utc),
        source_type="batch",
        source_metadata={
            "folder_path": payload.folder_path,
            "file_pattern": payload.file_pattern,
            "file_count": len(files),
        },
        labels=[],
    )
    session.add(run)
    await session.flush()  # Get run.id

    # Create BackgroundJob
    job = BackgroundJob(
        user_id=current_user.id,
        job_type="batch_predict",
        status="pending",
    )
    session.add(job)
    await session.commit()
    await session.refresh(run)
    await session.refresh(job)

    # Launch async work
    async def _work() -> None:
        from spectra_sherpa.app.db.session import async_session

        async with async_session() as work_session:
            # Re-load workflow with graph in the work session
            wf = await load_workflow_with_graph(work_session, workflow_id, current_user.id)
            # Re-load run in the work session
            r = await work_session.get(ExecutionRun, run.id)
            await run_batch_prediction(work_session, job.id, r, wf, files)

    asyncio.create_task(job_manager.run_job(job.id, _work))

    return BatchPredictResponse(
        job_id=job.id,
        run_id=run.id,
        message=f"Batch prediction started: {len(files)} files",
    )


# ---------------------------------------------------------------------------
# Per-file prediction results
# ---------------------------------------------------------------------------

@router.get("/runs/{run_id}/predictions", response_model=BatchPredictionList)
async def list_predictions(
    run_id: int,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> BatchPredictionList:
    """List per-file prediction results for an execution run."""
    # Verify run ownership
    run_query = select(ExecutionRun).where(
        ExecutionRun.id == run_id,
        ExecutionRun.user_id == current_user.id,
    )
    run_result = await session.execute(run_query)
    if run_result.scalar_one_or_none() is None:
        raise HTTPException(status_code=404, detail="Run not found")

    query = (
        select(BatchPrediction)
        .where(BatchPrediction.run_id == run_id)
        .order_by(BatchPrediction.id)
    )
    result = await session.execute(query)
    predictions = list(result.scalars().all())

    return BatchPredictionList(
        predictions=[BatchPredictionOut.model_validate(p) for p in predictions],
        total=len(predictions),
    )


@router.get("/runs/{run_id}/predictions/{prediction_id}", response_model=BatchPredictionOut)
async def get_prediction(
    run_id: int,
    prediction_id: int,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> BatchPredictionOut:
    """Get a single per-file prediction result."""
    # Verify run ownership
    run_query = select(ExecutionRun).where(
        ExecutionRun.id == run_id,
        ExecutionRun.user_id == current_user.id,
    )
    run_result = await session.execute(run_query)
    if run_result.scalar_one_or_none() is None:
        raise HTTPException(status_code=404, detail="Run not found")

    query = select(BatchPrediction).where(
        BatchPrediction.id == prediction_id,
        BatchPrediction.run_id == run_id,
    )
    result = await session.execute(query)
    prediction = result.scalar_one_or_none()
    if prediction is None:
        raise HTTPException(status_code=404, detail="Prediction not found")

    return BatchPredictionOut.model_validate(prediction)


# ---------------------------------------------------------------------------
# Folder Watches
# ---------------------------------------------------------------------------

@router.post("/watches", response_model=FolderWatchOut, status_code=201)
async def create_watch(
    payload: FolderWatchCreate,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> FolderWatchOut:
    """Create a new folder watch (starts disabled)."""
    from spectra_sherpa.app.models.workflow import Workflow
    from spectra_sherpa.app.services.batch_predict import validate_folder_path

    # Validate folder path (prevents traversal in multi-user modes)
    try:
        validate_folder_path(payload.folder_path)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    # Verify workflow ownership
    wf_query = select(Workflow).where(
        Workflow.id == payload.workflow_id,
        Workflow.user_id == current_user.id,
    )
    wf_result = await session.execute(wf_query)
    if wf_result.scalar_one_or_none() is None:
        raise HTTPException(status_code=404, detail="Workflow not found")

    watch = FolderWatch(
        user_id=current_user.id,
        workflow_id=payload.workflow_id,
        name=payload.name,
        folder_path=payload.folder_path,
        file_pattern=payload.file_pattern,
        poll_interval_sec=payload.poll_interval_sec,
        is_enabled=False,
        processed_files={},
    )
    session.add(watch)
    await session.commit()
    await session.refresh(watch)
    logger.info("Created folder watch '%s' (id=%d)", watch.name, watch.id)
    return FolderWatchOut.model_validate(watch)


@router.get("/watches", response_model=list[FolderWatchOut])
async def list_watches(
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> list[FolderWatchOut]:
    """List the current user's folder watches."""
    query = (
        select(FolderWatch)
        .where(FolderWatch.user_id == current_user.id)
        .order_by(FolderWatch.created_at.desc())
    )
    result = await session.execute(query)
    watches = list(result.scalars().all())
    return [FolderWatchOut.model_validate(w) for w in watches]


@router.get("/watches/{watch_id}", response_model=FolderWatchOut)
async def get_watch(
    watch_id: int,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> FolderWatchOut:
    """Get a single folder watch."""
    watch = await _get_user_watch(session, watch_id, current_user.id)
    return FolderWatchOut.model_validate(watch)


@router.patch("/watches/{watch_id}", response_model=FolderWatchOut)
async def update_watch(
    watch_id: int,
    payload: FolderWatchUpdate,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> FolderWatchOut:
    """Update a folder watch configuration."""
    watch = await _get_user_watch(session, watch_id, current_user.id)

    update_data = payload.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(watch, key, value)

    watch.updated_at = datetime.now(timezone.utc)
    await session.commit()
    await session.refresh(watch)
    return FolderWatchOut.model_validate(watch)


@router.delete("/watches/{watch_id}", status_code=204, response_class=Response)
async def delete_watch(
    watch_id: int,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> Response:
    """Delete a folder watch."""
    watch = await _get_user_watch(session, watch_id, current_user.id)
    await session.delete(watch)
    await session.commit()
    logger.info("Deleted folder watch %d", watch_id)
    return Response(status_code=204)


@router.post("/watches/{watch_id}/enable", response_model=FolderWatchOut)
async def enable_watch(
    watch_id: int,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> FolderWatchOut:
    """Enable a folder watch for polling."""
    watch = await _get_user_watch(session, watch_id, current_user.id)
    watch.is_enabled = True
    watch.updated_at = datetime.now(timezone.utc)
    await session.commit()
    await session.refresh(watch)
    logger.info("Enabled folder watch '%s' (id=%d)", watch.name, watch.id)
    return FolderWatchOut.model_validate(watch)


@router.post("/watches/{watch_id}/disable", response_model=FolderWatchOut)
async def disable_watch(
    watch_id: int,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> FolderWatchOut:
    """Disable a folder watch (stops polling)."""
    watch = await _get_user_watch(session, watch_id, current_user.id)
    watch.is_enabled = False
    watch.updated_at = datetime.now(timezone.utc)
    await session.commit()
    await session.refresh(watch)
    logger.info("Disabled folder watch '%s' (id=%d)", watch.name, watch.id)
    return FolderWatchOut.model_validate(watch)


# ---------------------------------------------------------------------------
# Deploy runs (filtered view)
# ---------------------------------------------------------------------------

@router.get("/runs", response_model=ExecutionRunList)
async def list_deploy_runs(
    source_type: str | None = Query(None, description="Filter by source type"),
    label: str | None = Query(None, description="Filter by label"),
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> ExecutionRunList:
    """List execution runs filtered by source type and/or label."""
    query = (
        select(ExecutionRun)
        .where(ExecutionRun.user_id == current_user.id)
        .order_by(ExecutionRun.executed_at.desc())
    )

    if source_type:
        query = query.where(ExecutionRun.source_type == source_type)

    result = await session.execute(query)
    runs = list(result.scalars().all())

    # Filter by label in Python (portable across SQLite/PostgreSQL)
    if label:
        runs = [r for r in runs if r.labels and label in r.labels]

    return ExecutionRunList(
        runs=[ExecutionRunOut.model_validate(r) for r in runs],
        total=len(runs),
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _get_user_watch(
    session: AsyncSession, watch_id: int, user_id: int
) -> FolderWatch:
    """Load a folder watch with ownership check."""
    query = select(FolderWatch).where(
        FolderWatch.id == watch_id,
        FolderWatch.user_id == user_id,
    )
    result = await session.execute(query)
    watch = result.scalar_one_or_none()
    if watch is None:
        raise HTTPException(status_code=404, detail="Watch not found")
    return watch
