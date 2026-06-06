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

from spectra_sherpa.app.api.deps import get_current_user, get_session, require_workflow
from spectra_sherpa.app.models.execution_run import ExecutionRun
from spectra_sherpa.app.models.model_artifact import ModelArtifact
from spectra_sherpa.app.models.user import User
from spectra_sherpa.app.models.workflow import Workflow
from spectra_sherpa.app.schemas.execution_runs import (
    CompareRunsRequest,
    ComparisonResponse,
    ExecutionRunList,
    ExecutionRunOut,
    SaveRunRequest,
)
from spectra_sherpa.app.services.run_metrics import comparison_response
from spectra_sherpa.app.services.run_params import build_effective_params_snapshot

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/workflows/{workflow_id}/runs")


async def _get_workflow_for_user(workflow_id: int, user_id: int, session: AsyncSession) -> Workflow:
    """Load workflow with ownership check."""
    return await require_workflow(
        workflow_id,
        user_id,
        session,
        options=[selectinload(Workflow.nodes), selectinload(Workflow.versions)],
    )


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


@router.get("/latest", response_model=ExecutionRunOut | None)
async def get_latest_run(
    workflow_id: int,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> ExecutionRunOut | None:
    """Return the most recent auto-saved execution run, or null if none exists."""
    await _get_workflow_for_user(workflow_id, current_user.id, session)

    query = (
        select(ExecutionRun)
        .where(
            ExecutionRun.workflow_id == workflow_id,
            ExecutionRun.source_type == "auto",
        )
        .order_by(ExecutionRun.executed_at.desc())
        .limit(1)
    )
    result = await session.execute(query)
    run = result.scalar_one_or_none()
    if run is None:
        return None
    return ExecutionRunOut.model_validate(run)


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

    params_snapshot = build_effective_params_snapshot(workflow.nodes)

    # Get latest version ID if any
    latest_version_id = None
    if workflow.versions:
        latest_version_id = workflow.versions[0].id

    # Parse executed_at timestamp
    try:
        executed_at = datetime.fromisoformat(payload.executed_at)
    except (ValueError, TypeError):
        executed_at = datetime.utcnow()

    auto_query = select(ExecutionRun).where(
        ExecutionRun.workflow_id == workflow_id,
        ExecutionRun.user_id == current_user.id,
        ExecutionRun.source_type == "auto",
    )
    if payload.run_id is not None:
        auto_query = auto_query.where(ExecutionRun.id == payload.run_id)
    else:
        auto_query = auto_query.order_by(ExecutionRun.executed_at.desc(), ExecutionRun.id.desc()).limit(1)
    latest_auto = (await session.execute(auto_query.with_for_update())).scalar_one_or_none()
    if payload.run_id is not None and latest_auto is None:
        raise HTTPException(status_code=404, detail="Auto-saved run not found or already named")

    before_state = None
    if latest_auto is not None:
        # Saving a run is a naming act for the latest immutable auto-run.  Keep
        # the backend's full serialized results/diagnostics intact so refresh
        # restoration still has the complete node outputs.
        run = latest_auto
        before_state = {
            "name": run.name,
            "notes": run.notes,
            "labels": list(run.labels or []),
            "status": run.status,
            "run_kind": run.run_kind,
            "model_ids": list(run.model_ids or []),
            "applied_artifact_uids": list(run.applied_artifact_uids or []),
        }
        run.name = payload.name
        run.notes = payload.notes
        run.labels = payload.labels or run.labels or []
        run.status = payload.status or run.status
        run.error = payload.error
        run.integrity_hash = payload.integrity_hash or run.integrity_hash
        if payload.model_ids is not None:
            run.model_ids = payload.model_ids
        if payload.applied_artifact_uids is not None:
            run.applied_artifact_uids = payload.applied_artifact_uids
        if payload.run_kind is not None:
            run.run_kind = payload.run_kind
        if run.project_id is None:
            run.project_id = workflow.project_id
        run.source_type = "named"
    else:
        run = ExecutionRun(
            project_id=workflow.project_id,
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
            model_ids=payload.model_ids,
            run_kind=payload.run_kind or ("training" if payload.model_ids else "other"),
            applied_artifact_uids=payload.applied_artifact_uids or [],
        )
        session.add(run)

    await session.flush()

    from spectra_sherpa.app.services.audit import audit_emitter

    audit_emitter.emit(
        session=session,
        action="workflow.run.named" if latest_auto is not None else "workflow.run.saved",
        target_type="ExecutionRun",
        target_id=run.id,
        before=before_state,
        after={
            "run_id": run.id,
            "project_id": workflow.project_id,
            "workflow_id": workflow_id,
            "name": run.name,
            "notes": run.notes,
            "labels": list(run.labels or []),
            "status": run.status,
            "run_kind": run.run_kind,
            "model_ids": list(run.model_ids or []),
            "applied_artifact_uids": list(run.applied_artifact_uids or []),
        },
    )

    if payload.model_ids:
        artifact_result = await session.execute(
            select(ModelArtifact).where(
                ModelArtifact.user_id == current_user.id,
                ModelArtifact.artifact_uid.in_(payload.model_ids),
                ModelArtifact.workflow_id == workflow_id,
                ModelArtifact.project_id == workflow.project_id,
            )
        )
        artifacts = list(artifact_result.scalars().all())
        found_uids = {artifact.artifact_uid for artifact in artifacts}
        missing = [uid for uid in payload.model_ids if uid not in found_uids]
        if missing:
            raise HTTPException(
                status_code=400,
                detail="Model artifacts must belong to the workflow and project being named",
            )
        for artifact in artifacts:
            artifact.source_run_id = run.id
            if not artifact.display_name or artifact.display_name == artifact.name:
                node_part = f" — {artifact.node_id}" if artifact.node_id else ""
                artifact.display_name = f"{artifact.model_type.upper()} — {payload.name}{node_part}"

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

    return comparison_response(runs)
