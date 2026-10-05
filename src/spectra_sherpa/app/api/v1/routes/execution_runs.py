"""
Execution run API endpoints for saving and comparing workflow runs.
"""

from __future__ import annotations

import logging
from asyncio import to_thread

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from spectra_sherpa.app.api.deps import get_current_user, get_session
from spectra_sherpa.app.contracts.project_access import uses_managed_project_access
from spectra_sherpa.app.contracts.scientific_access import ScienceOperation, require_scientific_access
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

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/workflows/{workflow_id}/runs")


async def _get_workflow_for_user(
    workflow_id: int, user_id: int, session: AsyncSession, operation: ScienceOperation = "read"
) -> Workflow:
    """Load workflow with ownership check."""
    workflow = await session.scalar(
        select(Workflow)
        .where(Workflow.id == workflow_id)
        .options(selectinload(Workflow.nodes), selectinload(Workflow.versions))
    )
    if workflow is None:
        raise HTTPException(404, "Workflow not found")
    await require_scientific_access(
        session, user_id, workflow.project_id, operation, resource_owner_id=workflow.user_id
    )
    return workflow


@router.get("", response_model=ExecutionRunList)
async def list_runs(
    workflow_id: int,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> ExecutionRunList:
    """List all saved runs for a workflow, newest first."""
    workflow = await _get_workflow_for_user(workflow_id, current_user.id, session)

    query = (
        select(ExecutionRun)
        .where(
            ExecutionRun.workflow_id == workflow_id,
            or_(ExecutionRun.user_id == current_user.id, uses_managed_project_access()),
            or_(not uses_managed_project_access(), ExecutionRun.project_id == workflow.project_id),
        )
        .order_by(ExecutionRun.executed_at.desc())
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
    """Return the most recent authorized execution, preserving identity after naming."""
    workflow = await _get_workflow_for_user(workflow_id, current_user.id, session)

    query = (
        select(ExecutionRun)
        .where(
            ExecutionRun.workflow_id == workflow_id,
            or_(ExecutionRun.user_id == current_user.id, uses_managed_project_access()),
            or_(not uses_managed_project_access(), ExecutionRun.project_id == workflow.project_id),
            ExecutionRun.source_type.in_(["auto", "named"]),
        )
        .order_by(ExecutionRun.executed_at.desc(), ExecutionRun.id.desc())
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
    workflow = await _get_workflow_for_user(workflow_id, current_user.id, session)

    query = select(ExecutionRun).where(
        ExecutionRun.id == run_id,
        ExecutionRun.workflow_id == workflow_id,
        or_(ExecutionRun.user_id == current_user.id, uses_managed_project_access()),
        or_(not uses_managed_project_access(), ExecutionRun.project_id == workflow.project_id),
    )
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
    workflow = await _get_workflow_for_user(workflow_id, current_user.id, session, "write")

    auto_query = select(ExecutionRun).where(
        ExecutionRun.workflow_id == workflow_id,
        ExecutionRun.user_id == current_user.id,
        ExecutionRun.source_type == "auto",
        or_(not uses_managed_project_access(), ExecutionRun.project_id == workflow.project_id),
    )
    auto_query = auto_query.where(ExecutionRun.id == payload.run_id)
    latest_auto = (await session.execute(auto_query.with_for_update())).scalar_one_or_none()
    if latest_auto is None:
        raise HTTPException(
            status_code=404,
            detail="Auto-saved run not found or already named",
        )

    # Saving a run is a naming act for an immutable server-recorded execution.
    # Client result fields are compatibility inputs only and never create a
    # scientific record.
    run = latest_auto
    before_state = {
        "name": run.name,
        "notes": run.notes,
        "labels": list(run.labels or []),
        "status": run.status,
        "run_kind": run.run_kind,
        "produced_artifact_uids": list(run.produced_artifact_uids or []),
        "attempted_artifact_uids": list(run.attempted_artifact_uids or []),
        "succeeded_artifact_uids": list(run.succeeded_artifact_uids or []),
    }
    run.name = payload.name
    run.notes = payload.notes
    run.labels = payload.labels or run.labels or []
    if run.project_id is None:
        run.project_id = workflow.project_id
    run.source_type = "named"

    await session.flush()

    from spectra_sherpa.app.services.audit import audit_emitter

    audit_emitter.emit(
        session=session,
        action="workflow.run.named",
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
            "produced_artifact_uids": list(run.produced_artifact_uids or []),
            "attempted_artifact_uids": list(run.attempted_artifact_uids or []),
            "succeeded_artifact_uids": list(run.succeeded_artifact_uids or []),
        },
    )

    if payload.produced_artifact_uids:
        artifact_result = await session.execute(
            select(ModelArtifact).where(
                ModelArtifact.user_id == current_user.id,
                ModelArtifact.artifact_uid.in_(payload.produced_artifact_uids),
                ModelArtifact.workflow_id == workflow_id,
                ModelArtifact.project_id == workflow.project_id,
            )
        )
        artifacts = list(artifact_result.scalars().all())
        found_uids = {artifact.artifact_uid for artifact in artifacts}
        missing = [uid for uid in payload.produced_artifact_uids if uid not in found_uids]
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
    workflow = await _get_workflow_for_user(workflow_id, current_user.id, session, "write")

    query = select(ExecutionRun).where(
        ExecutionRun.id == run_id,
        ExecutionRun.workflow_id == workflow_id,
        ExecutionRun.user_id == current_user.id,
        or_(not uses_managed_project_access(), ExecutionRun.project_id == workflow.project_id),
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
    workflow = await _get_workflow_for_user(workflow_id, current_user.id, session)

    query = (
        select(ExecutionRun)
        .where(
            ExecutionRun.workflow_id == workflow_id,
            ExecutionRun.user_id == current_user.id,
            ExecutionRun.id.in_(payload.run_ids),
        )
        .order_by(ExecutionRun.id)
    )
    if uses_managed_project_access():
        query = query.where(ExecutionRun.project_id == workflow.project_id)
    result = await session.execute(query)
    runs = list(result.scalars().all())

    if len(runs) < 2:
        raise HTTPException(
            status_code=400,
            detail=f"Need at least 2 runs to compare, found {len(runs)}",
        )

    if len(runs) != len(set(payload.run_ids)):
        raise HTTPException(status_code=404, detail="One or more selected runs are unavailable in this workflow.")
    if not set(payload.evaluation_selections).issubset(payload.run_ids):
        raise HTTPException(status_code=400, detail="Evaluation selections must belong to the selected runs.")
    return await to_thread(comparison_response, runs, payload.evaluation_selections)
