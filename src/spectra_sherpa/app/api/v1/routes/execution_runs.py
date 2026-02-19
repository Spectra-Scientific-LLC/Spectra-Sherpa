"""
Execution run API endpoints for saving and comparing workflow runs.
"""

from __future__ import annotations

import logging
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from spectra_sherpa.app.api.deps import get_current_user, get_session
from spectra_sherpa.app.models.execution_run import ExecutionRun
from spectra_sherpa.app.models.user import User
from spectra_sherpa.app.models.workflow import Workflow
from spectra_sherpa.app.schemas.execution_runs import (
    CompareRunsRequest,
    ComparisonResponse,
    ExecutionRunList,
    ExecutionRunOut,
    SaveRunRequest,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/workflows/{workflow_id}/runs")


async def _get_workflow_for_user(workflow_id: int, user_id: int, session: AsyncSession) -> Workflow:
    """Load workflow with ownership check."""
    query = (
        select(Workflow)
        .where(Workflow.id == workflow_id, Workflow.user_id == user_id)
        .options(selectinload(Workflow.nodes), selectinload(Workflow.versions))
    )
    result = await session.execute(query)
    workflow = result.scalar_one_or_none()
    if workflow is None:
        raise HTTPException(status_code=404, detail="Workflow not found")
    return workflow


@router.get("", response_model=ExecutionRunList)
async def list_runs(
    workflow_id: int,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> ExecutionRunList:
    """List all saved runs for a workflow, newest first."""
    await _get_workflow_for_user(workflow_id, current_user.id, session)

    query = (
        select(ExecutionRun).where(ExecutionRun.workflow_id == workflow_id).order_by(ExecutionRun.executed_at.desc())
    )
    result = await session.execute(query)
    runs = list(result.scalars().all())

    return ExecutionRunList(
        runs=[ExecutionRunOut.model_validate(r) for r in runs],
        total=len(runs),
    )


@router.get("/{run_id}", response_model=ExecutionRunOut)
async def get_run(
    workflow_id: int,
    run_id: int,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> ExecutionRunOut:
    """Get a single execution run."""
    await _get_workflow_for_user(workflow_id, current_user.id, session)

    query = select(ExecutionRun).where(ExecutionRun.id == run_id, ExecutionRun.workflow_id == workflow_id)
    result = await session.execute(query)
    run = result.scalar_one_or_none()
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")

    return ExecutionRunOut.model_validate(run)


@router.post("", response_model=ExecutionRunOut, status_code=201)
async def create_run(
    workflow_id: int,
    payload: SaveRunRequest,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> ExecutionRunOut:
    """Save an execution result as a named run."""
    workflow = await _get_workflow_for_user(workflow_id, current_user.id, session)

    # Build params_snapshot from current workflow node parameters
    params_snapshot: dict = {}
    for node in workflow.nodes:
        if node.parameters:
            params_snapshot[node.node_id] = node.parameters

    # Get latest version ID if any
    latest_version_id = None
    if workflow.versions:
        latest_version_id = workflow.versions[0].id

    # Parse executed_at timestamp
    try:
        executed_at = datetime.fromisoformat(payload.executed_at)
    except (ValueError, TypeError):
        executed_at = datetime.utcnow()

    run = ExecutionRun(
        workflow_id=workflow_id,
        workflow_version_id=latest_version_id,
        user_id=current_user.id,
        name=payload.name,
        status=payload.status,
        params_snapshot=params_snapshot,
        results_summary=payload.results_summary,
        diagnostics=payload.diagnostics,
        node_statuses=payload.node_statuses,
        error=payload.error,
        integrity_hash=payload.integrity_hash,
        executed_at=executed_at,
        notes=payload.notes,
        labels=payload.labels or [],
    )
    session.add(run)
    await session.commit()
    await session.refresh(run)

    logger.info("Saved execution run '%s' (id=%s) for workflow %s", run.name, run.id, workflow_id)
    return ExecutionRunOut.model_validate(run)


@router.delete("/{run_id}", status_code=204, response_class=Response)
async def delete_run(
    workflow_id: int,
    run_id: int,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> Response:
    """Delete an execution run."""
    await _get_workflow_for_user(workflow_id, current_user.id, session)

    query = select(ExecutionRun).where(ExecutionRun.id == run_id, ExecutionRun.workflow_id == workflow_id)
    result = await session.execute(query)
    run = result.scalar_one_or_none()
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")

    await session.delete(run)
    await session.commit()
    logger.info("Deleted execution run %s for workflow %s", run_id, workflow_id)
    return Response(status_code=204)


@router.post("/compare", response_model=ComparisonResponse)
async def compare_runs(
    workflow_id: int,
    payload: CompareRunsRequest,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> ComparisonResponse:
    """Compare multiple execution runs side-by-side."""
    await _get_workflow_for_user(workflow_id, current_user.id, session)

    query = (
        select(ExecutionRun)
        .where(
            ExecutionRun.workflow_id == workflow_id,
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

    # Collect all metric keys across all runs (node_id.metric_key)
    metric_keys: set[str] = set()
    for run in runs:
        for node_id, metrics in (run.results_summary or {}).items():
            if isinstance(metrics, dict):
                for key in metrics:
                    metric_keys.add(f"{node_id}.{key}")

    sorted_keys = sorted(metric_keys)

    # Build diff: {metric_key: {run_id: value}}
    diff: dict[str, dict[str, object]] = {}
    for key in sorted_keys:
        node_id, metric_name = key.split(".", 1)
        diff[key] = {}
        for run in runs:
            node_metrics = (run.results_summary or {}).get(node_id, {})
            if isinstance(node_metrics, dict) and metric_name in node_metrics:
                diff[key][str(run.id)] = node_metrics[metric_name]

    return ComparisonResponse(
        runs=[ExecutionRunOut.model_validate(r) for r in runs],
        metric_keys=sorted_keys,
        diff=diff,
    )
