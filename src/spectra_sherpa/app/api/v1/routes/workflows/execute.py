"""
Execution endpoints: execute / trial / validate.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from spectra_sherpa.app.api.deps import get_current_user, get_session
from spectra_sherpa.app.core.config import settings
from spectra_sherpa.app.models.user import User
from spectra_sherpa.app.models.workflow import Workflow
from spectra_sherpa.app.schemas.workflows import (
    TrialExecuteRequest,
    TrialExecuteResponse,
    WorkflowExecuteRequest,
    WorkflowExecuteResponse,
    WorkflowValidationIssue,
    WorkflowValidationResponse,
)
from spectra_sherpa.app.services.dag import DAGExecutor
from spectra_sherpa.app.services.dag import WorkflowEdge as DAGEdge
from spectra_sherpa.app.services.dag import WorkflowNode as DAGNode
from spectra_sherpa.app.services.serialization import serialize_result

from ._helpers import _auto_persist_run, _raise_execution_persistence_error, _validate_edge_refs

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/workflows")

# Re-export helpers so existing imports (e.g. from .execute import _validate_edge_refs) keep working
__all__ = ["router", "_auto_persist_run", "_raise_execution_persistence_error", "_validate_edge_refs"]


# IMPORTANT: This route must be defined BEFORE /{workflow_id} routes
# to avoid "trial" being parsed as a workflow_id
@router.post("/trial/execute", response_model=TrialExecuteResponse)
async def execute_trial(
    payload: TrialExecuteRequest,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> TrialExecuteResponse:
    """
    Execute a trial run of a node with trial parameters.

    This endpoint is used by the DetailView to run a node with temporary
    parameters without persisting anything to the database. It creates
    a fresh DAG executor for each trial run (no caching).

    The trial execution:
    1. Builds a temporary DAG from the provided nodes/edges
    2. Overrides the target node's parameters with trial_params
    3. Executes the target node and its dependencies
    4. Returns only the target node's result

    This is completely independent of any stored workflow state.
    """
    try:
        # Build a fresh DAG executor for this trial (no caching)
        executor = DAGExecutor()

        logger.debug(
            "[Trial Execution] Target node: %s (type: %s)", payload.target_node_id, type(payload.target_node_id)
        )
        logger.debug("[Trial Execution] Trial params: %s", payload.trial_params)
        logger.debug("[Trial Execution] Total nodes: %s", len(payload.nodes))

        # Add all nodes to the executor
        for node in payload.nodes:
            # Override params for target node with trial_params
            is_target = node.node_id == payload.target_node_id
            params = payload.trial_params if is_target else node.parameters

            logger.debug("[Trial Execution] Node %s (type: %s):", node.node_id, node.node_type)
            logger.debug("  - Is target: %s", is_target)
            logger.debug(
                "  - String comparison: '%s' == '%s': %s",
                node.node_id,
                payload.target_node_id,
                node.node_id == payload.target_node_id,
            )
            logger.debug("  - Node params from payload: %s", node.parameters)
            logger.debug("  - Params being used: %s", params)

            dag_node = DAGNode(
                node_id=node.node_id,
                node_type=node.node_type,
                parameters=params,
            )
            executor.add_node(dag_node)

        # Add all edges
        for edge in payload.edges:
            dag_edge = DAGEdge(
                from_node=edge.from_node_id,
                to_node=edge.to_node_id,
                from_output=edge.from_output,
                to_input=edge.to_input,
            )
            executor.add_edge(dag_edge)

        # Execute the target node (and its dependencies)
        results = await executor.execute_node(payload.target_node_id, initial_data=payload.initial_data)

        # Get the target node's result
        target_result = results.get(payload.target_node_id)

        # Serialize the result
        serialized_result = serialize_result(target_result, owner_user_id=current_user.id) if target_result else None

        return TrialExecuteResponse(
            target_node_id=payload.target_node_id,
            status="completed",
            result=serialized_result,
            error=None,
        )

    except Exception as e:
        return TrialExecuteResponse(
            target_node_id=payload.target_node_id,
            status="error",
            result=None,
            error=str(e),
        )


@router.post("/{workflow_id}/validate", response_model=WorkflowValidationResponse)
async def validate_workflow_endpoint(
    workflow_id: int,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> WorkflowValidationResponse:
    """Validate a workflow without executing it.

    Checks: graph structure, required parameters, port type compatibility.
    Returns structured list of errors and warnings.
    """
    user_id = current_user.id

    query = (
        select(Workflow)
        .where(Workflow.id == workflow_id)
        .where(Workflow.user_id == user_id)
        .options(
            selectinload(Workflow.nodes),
            selectinload(Workflow.edges),
        )
    )
    result = await session.execute(query)
    workflow = result.scalar_one_or_none()

    if workflow is None:
        raise HTTPException(status_code=404, detail="Workflow not found")

    # Build executor (same pattern as execute_workflow)
    executor = DAGExecutor()
    all_issues: list[WorkflowValidationIssue] = []

    for node in workflow.nodes:
        dag_node = DAGNode(
            node_id=node.node_id,
            node_type=node.node_type,
            parameters=node.parameters or {},
        )
        try:
            executor.add_node(dag_node)
        except KeyError as e:
            all_issues.append(
                WorkflowValidationIssue(
                    level="error",
                    node_id=node.node_id,
                    port=None,
                    message=f"Unknown node type: {e}",
                )
            )

    for edge in workflow.edges:
        dag_edge = DAGEdge(
            from_node=edge.from_node_id,
            to_node=edge.to_node_id,
            from_output=edge.from_output,
            to_input=edge.to_input,
        )
        try:
            executor.add_edge(dag_edge)
        except ValueError as e:
            all_issues.append(
                WorkflowValidationIssue(
                    level="error",
                    node_id=None,
                    port=None,
                    message=str(e),
                )
            )

    # Run structural + parameter + port type validation
    if not any(i.level == "error" for i in all_issues):
        validation = executor.validate_full()
        for issue in validation.issues:
            all_issues.append(
                WorkflowValidationIssue(
                    level=issue.level,
                    node_id=issue.node_id,
                    port=issue.port,
                    message=issue.message,
                )
            )

    errors = [i for i in all_issues if i.level == "error"]
    warnings = [i for i in all_issues if i.level == "warning"]

    return WorkflowValidationResponse(
        is_valid=len(errors) == 0,
        issues=all_issues,
        error_count=len(errors),
        warning_count=len(warnings),
    )


@router.post("/{workflow_id}/execute", response_model=WorkflowExecuteResponse)
async def execute_workflow(
    workflow_id: int,
    payload: WorkflowExecuteRequest,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> WorkflowExecuteResponse:
    """Execute a workflow for the authenticated user."""
    user_id = current_user.id

    # Load workflow with nodes and edges
    query = (
        select(Workflow)
        .where(Workflow.id == workflow_id)
        .where(Workflow.user_id == user_id)
        .options(
            selectinload(Workflow.nodes),
            selectinload(Workflow.edges),
            selectinload(Workflow.tags),
            selectinload(Workflow.folder),
        )
    )
    result = await session.execute(query)
    workflow = result.scalar_one_or_none()

    if workflow is None:
        raise HTTPException(status_code=404, detail="Workflow not found")

    node_types = [n.node_type for n in workflow.nodes]

    # Demo mode: block execution of workflows containing hidden node types.
    from spectra_sherpa.app.core.config import app_config as _cfg

    if _cfg.site_profile == "demo":
        from spectra_sherpa.app.contracts.demo_policy import get_demo_policy

        hidden = get_demo_policy().hidden_node_types
        for nt in node_types:
            if nt in hidden:
                raise HTTPException(
                    status_code=403,
                    detail=f"Node type '{nt}' is not available in demo mode.",
                )

    # Snapshot ORM attributes while session is clean (before execution may
    # dirty or expire them, making lazy loads fail in the error handler).
    wf_integrity_hash = workflow.integrity_hash
    wf_version_id = getattr(workflow, "current_version_id", None)
    wf_project_id = getattr(workflow, "project_id", None)

    executor = None
    try:
        # Build DAG executor
        executor = DAGExecutor()

        # Add nodes
        for node in workflow.nodes:
            dag_node = DAGNode(
                node_id=node.node_id,
                node_type=node.node_type,
                parameters=node.parameters,
                position={"x": node.position_x, "y": node.position_y} if node.position_x and node.position_y else None,
            )
            executor.add_node(dag_node)

        # Add edges
        for edge in workflow.edges:
            dag_edge = DAGEdge(
                from_node=edge.from_node_id,
                to_node=edge.to_node_id,
                from_output=edge.from_output,
                to_input=edge.to_input,
            )
            executor.add_edge(dag_edge)

        # Build per-node status broadcast callback
        import time as _time

        from spectra_sherpa.app.services.websocket_manager import ws_manager

        async def _broadcast_node_status(node_id: str, status: str, error: str | None = None) -> None:
            try:
                await ws_manager.broadcast(
                    f"workflow:{workflow_id}",
                    {
                        "type": "node_status",
                        "node_id": node_id,
                        "status": status,
                        "error": error,
                        "timestamp": _time.time(),
                    },
                )
            except Exception:
                pass  # Never let broadcast failure affect execution

        # Execute
        execution_timeout = max(1, int(settings.max_job_duration_sec))
        timeout_ctx = asyncio.timeout(execution_timeout)

        async with timeout_ctx:
            if payload.node_id:
                # Execute single node and its dependencies (with initial_data for DATA nodes)
                results = await executor.execute_node(payload.node_id, initial_data=payload.initial_data)
            else:
                # Execute entire workflow
                results = await executor.execute(
                    initial_data=payload.initial_data,
                    status_callback=_broadcast_node_status,
                )

        # Serialize results to JSON-safe format (per-node, so one failure doesn't lose all)
        logger.debug("[Serialization] Starting serialization of %s node results...", len(results))
        serialized_results = {}
        serialization_errors = []
        for node_id, node_result in results.items():
            result_type = type(node_result).__name__
            try:
                serialized_results[node_id] = serialize_result(node_result, owner_user_id=user_id)
                # Log summary of serialized result
                sr = serialized_results[node_id]
                if isinstance(sr, dict):
                    keys = list(sr.keys())[:8]
                    logger.debug("  Serialized node %s (%s): keys=%s", node_id, result_type, keys)
                else:
                    logger.debug("  Serialized node %s (%s): type=%s", node_id, result_type, type(sr).__name__)
            except Exception as ser_err:
                logger.warning(
                    "  Serialization failed for node %s (%s): %s", node_id, result_type, ser_err, exc_info=True
                )
                serialization_errors.append(f"Node {node_id}: {ser_err}")
                serialized_results[node_id] = {
                    "error": f"Serialization failed: {ser_err}",
                    "type": result_type,
                }

        # Persist model artifacts to DB (if any training nodes ran)
        if executor and getattr(executor, "saved_artifacts", None):
            from spectra_sherpa.app.services.model_store import persist_model_artifact_records

            await persist_model_artifact_records(
                session,
                executor.saved_artifacts,
                user_id=user_id,
                workflow_id=workflow_id,
                workflow_version_id=wf_version_id,
                project_id=wf_project_id,
            )

        # Update workflow execution timestamp
        workflow.last_executed_at = datetime.utcnow()
        await session.commit()

        error_msg = "; ".join(serialization_errors) if serialization_errors else None
        final_status = executor.status.value if not serialization_errors else "partial"
        node_statuses = executor.get_status()["node_statuses"]
        logger.debug(
            "[Serialization] Done. status=%s, result_keys=%s, node_statuses=%s",
            final_status,
            list(serialized_results.keys()),
            node_statuses,
        )
        if error_msg:
            logger.debug("[Serialization] Errors: %s", error_msg)

        diagnostics_serialized = serialize_result(getattr(executor, "diagnostics", {}), owner_user_id=user_id)

        # Auto-persist results so they survive page refresh
        persisted = await _auto_persist_run(
            session,
            workflow_id=workflow_id,
            user_id=user_id,
            workflow=workflow,
            wf_version_id=wf_version_id,
            serialized_results=serialized_results,
            diagnostics_serialized=diagnostics_serialized,
            node_statuses=node_statuses,
            final_status=final_status,
            error_msg=error_msg,
            integrity_hash=wf_integrity_hash,
            model_ids=[a["artifact_uid"] for a in (executor.saved_artifacts or [])],
        )
        if not persisted:
            _raise_execution_persistence_error()

        return WorkflowExecuteResponse(
            workflow_id=workflow_id,
            status=final_status,
            results=serialized_results,
            diagnostics=diagnostics_serialized,
            node_statuses=node_statuses,
            executed_at=datetime.utcnow(),
            error=error_msg,
            integrity_hash=wf_integrity_hash,
        )

    except asyncio.TimeoutError as e:
        logger.warning(
            "Workflow execution timed out for workflow_id=%s after %ss",
            workflow_id,
            settings.max_job_duration_sec,
        )
        raise HTTPException(
            status_code=504,
            detail=("Workflow execution timed out. " f"Reference limit: {settings.max_job_duration_sec}s"),
        ) from e

    except Exception as e:
        logger.debug("Workflow execution failed for workflow_id=%s", workflow_id, exc_info=True)

        # Persist any model artifacts that were saved to disk before the failure.
        # Without this, partial executions leave orphan files with no DB records.
        if executor and getattr(executor, "saved_artifacts", None):
            try:
                # Roll back any dirty state from the failed execution before
                # attempting new DB writes. This is safe even if session is clean.
                await session.rollback()

                from spectra_sherpa.app.services.model_store import persist_model_artifact_records

                await persist_model_artifact_records(
                    session,
                    executor.saved_artifacts,
                    user_id=user_id,
                    workflow_id=workflow_id,
                    workflow_version_id=wf_version_id,
                    project_id=wf_project_id,
                )
                await session.commit()
            except Exception as art_err:
                logger.warning("Could not persist model artifacts from partial run: %s", art_err)
                try:
                    await session.rollback()
                except Exception:
                    pass

        # Preserve successfully completed node outputs when later nodes fail.
        partial_results: dict[str, Any] = {}
        partial_serialization_errors: list[str] = []
        raw_results = executor.results if executor else {}
        for node_id, node_result in raw_results.items():
            result_type = type(node_result).__name__
            try:
                partial_results[node_id] = serialize_result(node_result, owner_user_id=user_id)
            except Exception as ser_err:
                partial_serialization_errors.append(f"Node {node_id}: {ser_err}")
                partial_results[node_id] = {
                    "error": f"Serialization failed: {ser_err}",
                    "type": result_type,
                }

        error_parts = [str(e)]
        if partial_serialization_errors:
            error_parts.append("; ".join(partial_serialization_errors))
        error_msg = " | ".join(part for part in error_parts if part)
        response_status = "partial" if partial_results else "error"

        partial_diagnostics = serialize_result(
            getattr(executor, "diagnostics", {}) if executor else {},
            owner_user_id=user_id,
        )
        partial_node_statuses = executor.get_status()["node_statuses"] if executor else {}

        # Auto-persist partial/error results too
        persisted = await _auto_persist_run(
            session,
            workflow_id=workflow_id,
            user_id=user_id,
            workflow=workflow,
            wf_version_id=wf_version_id,
            serialized_results=partial_results,
            diagnostics_serialized=partial_diagnostics,
            node_statuses=partial_node_statuses,
            final_status=response_status,
            error_msg=error_msg,
            integrity_hash=wf_integrity_hash,
            model_ids=[a["artifact_uid"] for a in (getattr(executor, "saved_artifacts", None) or [])],
        )
        if not persisted:
            _raise_execution_persistence_error()

        return WorkflowExecuteResponse(
            workflow_id=workflow_id,
            status=response_status,
            results=partial_results,
            diagnostics=partial_diagnostics,
            node_statuses=partial_node_statuses,
            executed_at=datetime.utcnow(),
            error=error_msg,
            integrity_hash=wf_integrity_hash,
        )
