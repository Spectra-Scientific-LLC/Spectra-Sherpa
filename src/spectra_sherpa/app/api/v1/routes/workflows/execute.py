"""
Execution endpoints: execute / trial / validate.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from spectra_sherpa.app.api.deps import get_current_user, get_session
from spectra_sherpa.app.core.config import settings
from spectra_sherpa.app.models.execution_run import ExecutionRun
from spectra_sherpa.app.models.project_data_source import ProjectDataSource
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
from spectra_sherpa.app.services.run_params import build_effective_params_snapshot
from spectra_sherpa.app.services.serialization import serialize_result
from spectra_sherpa.app.services.workflow_access import validate_workflow_execution_access

from ._helpers import (
    TERMINAL_RUN_STATUSES,
    _auto_persist_run,
    _build_source_metadata,
    _compact_diagnostics_for_run_history,
    _compact_results_for_run_history,
    _raise_execution_persistence_error,
    _reserve_run,
    _validate_edge_refs,
    contains_run_history_truncation,
    finalize_orphan_reservation_if_running,
    find_any_idempotent_run,
    find_idempotent_run,
    validate_idempotency_key,
)


def _collect_input_ports(workflow: Workflow, initial_data: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Capture the input ports + data-source linkage for the
    reproducibility record.

    Phase 1 contract: each entry is at minimum
    ``{"port_name": str, "data_source_id": int | None}``. Phase 3 will
    add per-port ``dataset_hash``, ``file_hashes``, ``target_hash`` etc.
    once the multi-port abstraction lands. Returns an empty list when
    no inputs are present so the reproducibility record's input-ports
    field is always set (per v0.5 spec).

    Important: this helper deliberately consumes only **scalar columns**
    on ``workflow`` — touching relationships like ``data_source_links``
    here triggers lazy-loading from inside an async route, which fires
    a synchronous DB round-trip outside the greenlet context and
    breaks the request. Multi-data-source coverage moves to Phase 3
    alongside an explicit eager-load.
    """
    ports: list[dict[str, Any]] = []
    if workflow.primary_data_source_id is not None:
        ports.append(
            {
                "port_name": "primary",
                "data_source_id": workflow.primary_data_source_id,
            }
        )
    if initial_data:
        for node_id, payload in initial_data.items():
            payload_keys = sorted(payload.keys()) if isinstance(payload, dict) else []
            ports.append(
                {
                    "port_name": f"initial:{node_id}",
                    "payload_keys": payload_keys,
                }
            )
    return ports


async def _training_dataset_id_from_workflow(
    session: AsyncSession,
    workflow: Workflow,
) -> int | None:
    """Resolve the workflow's primary My Dataset/Experiment id, when known."""
    if workflow.primary_data_source_id is None:
        return None
    result = await session.execute(
        select(ProjectDataSource).where(ProjectDataSource.id == workflow.primary_data_source_id)
    )
    source = result.scalar_one_or_none()
    if source is None or not source.source_ref:
        return None
    parts = source.source_ref.split(":")
    if len(parts) >= 2 and parts[0] in {"experiment", "dataset"}:
        try:
            return int(parts[1])
        except (TypeError, ValueError):
            return None
    return None


logger = logging.getLogger(__name__)

router = APIRouter(prefix="/workflows")

# Re-export helpers so existing imports (e.g. from .execute import _validate_edge_refs) keep working
__all__ = ["router", "_auto_persist_run", "_raise_execution_persistence_error", "_validate_edge_refs"]

ADVISOR_CONTEXT_NODE_TYPES = {"analysis.peak_id"}


def _reachable_node_types(nodes: list[Any], edges: list[Any], target_node_id: str | None = None) -> set[str]:
    """Return node types that will execute for a full run or one target node."""
    node_by_id = {node.node_id: node for node in nodes}
    if target_node_id is None:
        return {node.node_type for node in nodes}

    incoming: dict[str, list[str]] = {}
    for edge in edges:
        incoming.setdefault(edge.to_node_id, []).append(edge.from_node_id)

    reachable_ids: set[str] = set()

    def visit(node_id: str) -> None:
        if node_id in reachable_ids:
            return
        reachable_ids.add(node_id)
        for upstream_id in incoming.get(node_id, []):
            visit(upstream_id)

    visit(target_node_id)
    return {node_by_id[node_id].node_type for node_id in reachable_ids if node_id in node_by_id}


async def _enforce_advisor_node_egress_policy(
    nodes: list[Any],
    edges: list[Any],
    *,
    current_user: User,
    session: AsyncSession,
    target_node_id: str | None = None,
) -> None:
    """Block advisor-backed workflow nodes when LLM egress is disabled."""
    node_types = _reachable_node_types(nodes, edges, target_node_id)
    if not (node_types & ADVISOR_CONTEXT_NODE_TYPES):
        return

    from spectra_sherpa.app.core.security import check_egress_permission

    if not await check_egress_permission(current_user, "allow_llm_chat", session=session):
        raise HTTPException(status_code=403, detail="Peak ID requires AI chat to be enabled in privacy settings.")
    if not await check_egress_permission(
        current_user,
        "allow_llm_context",
        data_type="metadata",
        destination="llm_context",
        session=session,
    ):
        raise HTTPException(
            status_code=403,
            detail="Peak ID sends peak metadata to Sherpa Advisor. Enable LLM context sharing in privacy settings.",
        )


def _enforce_demo_trial_execution_policy(payload: TrialExecuteRequest, user_id: int | None) -> None:
    """Apply demo execution controls to ad-hoc trial DAGs.

    Trial execution accepts client-supplied node definitions instead of a
    persisted workflow, so it must enforce the same demo constraints before a
    DAGExecutor is constructed.
    """
    from spectra_sherpa.app.core.config import app_config as _cfg

    if _cfg.site_profile == "demo":
        from spectra_sherpa.app.contracts.demo_policy import get_demo_policy

        hidden = get_demo_policy().hidden_node_types
        for node in payload.nodes:
            if node.node_type in hidden:
                raise HTTPException(
                    status_code=403,
                    detail=f"Node type '{node.node_type}' is not available in demo mode.",
                )

    from spectra_sherpa.app.api.deps import enforce_demo_execution_quota

    enforce_demo_execution_quota(user_id)


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
    _enforce_demo_trial_execution_policy(payload, current_user.id)
    await validate_workflow_execution_access(
        payload.nodes,
        payload.initial_data,
        current_user.id,
        payload.project_id,
        session,
    )
    await _enforce_advisor_node_egress_policy(
        payload.nodes,
        payload.edges,
        current_user=current_user,
        session=session,
        target_node_id=payload.target_node_id,
    )

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
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> WorkflowExecuteResponse:
    """Execute a workflow for the authenticated user.

    Honors an optional ``Idempotency-Key`` header (8-64 chars, [A-Za-z0-9_-]).
    A retried POST with the same key replays the original 200 response from
    the persisted ExecutionRun row instead of running the workflow again —
    a network blip that drops the response no longer creates a duplicate
    run. Replay is scoped to ``(user_id, workflow_id, key)`` and bounded to
    a 1-hour window. Keys older than that stay reserved by the database and
    return 409 ``idempotency_key_expired``; clients must generate a new key
    for a new run.
    """
    user_id = current_user.id
    normalized_idempotency_key = validate_idempotency_key(idempotency_key)

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

    # Snapshot the workflow's ORM attributes BEFORE any commit / execute
    # may expire them. These were originally snapshotted further down,
    # but the idempotency + reservation path below needs the same values
    # AND has to run before quota / DAG build. workflow.nodes is eagerly
    # loaded via selectinload above.
    #
    # ``wf_name`` matters specifically for the error-handler call to
    # ``_auto_persist_run`` below: by the time that runs, the session has
    # been rolled back from a failed flush and accessing ``workflow.name``
    # there triggers an async lazy-load that can't acquire a greenlet,
    # masking the original error with MissingGreenlet.
    wf_integrity_hash = workflow.integrity_hash
    wf_version_id = getattr(workflow, "current_version_id", None)
    wf_project_id = getattr(workflow, "project_id", None)
    wf_name = workflow.name
    wf_params_snapshot = build_effective_params_snapshot(workflow.nodes)

    # Idempotency: ownership check has passed (so an unauthenticated /
    # cross-user probe still 404'd above). Before we burn demo quota or
    # build the DAG, handle the four key-bearing cases:
    #   1. row exists, terminal, hashes match  -> replay
    #   2. row exists, terminal, hash mismatch -> 409 (REM-5: key reused for
    #      a different workflow state)
    #   3. row exists, non-terminal (running)  -> 409 (REM-2: another
    #      concurrent request is mid-execute; client should poll the run)
    #   4. no row exists                       -> claim the key by inserting
    #      a reservation row (REM-2); IntegrityError on the partial-unique
    #      index means someone else won the race in the meantime, re-fetch
    #      and dispatch by their row's state.
    reservation_id: int | None = None
    if normalized_idempotency_key is not None:
        from sqlalchemy.exc import IntegrityError

        async def _replay_or_conflict(row: ExecutionRun) -> WorkflowExecuteResponse:
            """Compare row state vs the current request and either return
            the replayed response (200) or raise a 409 with a structured
            detail the client can dispatch on."""
            if row.integrity_hash is not None and row.integrity_hash != wf_integrity_hash:
                raise HTTPException(
                    status_code=409,
                    detail={
                        "code": "idempotency_workflow_changed",
                        "message": (
                            "Idempotency-Key was previously used for a different "
                            "workflow state. Refusing to replay stale results."
                        ),
                        "run_id": row.id,
                    },
                )
            if row.status not in TERMINAL_RUN_STATUSES:
                raise HTTPException(
                    status_code=409,
                    detail={
                        "code": "idempotency_in_progress",
                        "message": (
                            "Another request with this Idempotency-Key is still "
                            "executing; poll the run for completion."
                        ),
                        "run_id": row.id,
                    },
                )
            results = row.results_summary or {}
            diagnostics = row.diagnostics or {}
            return WorkflowExecuteResponse(
                workflow_id=row.workflow_id or workflow_id,
                run_id=row.id,
                status=row.status,
                results=results,
                diagnostics=diagnostics,
                node_statuses=row.node_statuses or {},
                executed_at=row.executed_at,
                error=row.error,
                integrity_hash=row.integrity_hash,
                results_truncated=contains_run_history_truncation(results),
                diagnostics_truncated=contains_run_history_truncation(diagnostics),
            )

        existing = await find_idempotent_run(
            session,
            user_id=user_id,
            workflow_id=workflow_id,
            idempotency_key=normalized_idempotency_key,
        )
        if existing is not None:
            return await _replay_or_conflict(existing)

        # No row yet — try to claim the key. The reservation insert
        # happens in its own session so it commits immediately and is
        # visible to a losing-race caller.
        try:
            reservation = await _reserve_run(
                session,
                workflow_id=workflow_id,
                workflow_name=wf_name,
                user_id=user_id,
                project_id=wf_project_id,
                wf_version_id=wf_version_id,
                integrity_hash=wf_integrity_hash,
                idempotency_key=normalized_idempotency_key,
                params_snapshot=wf_params_snapshot,
            )
            reservation_id = reservation.id if reservation is not None else None
        except IntegrityError:
            # Lost the race — another concurrent request claimed the key
            # between our lookup and our insert. Re-fetch and dispatch.
            winner = await find_idempotent_run(
                session,
                user_id=user_id,
                workflow_id=workflow_id,
                idempotency_key=normalized_idempotency_key,
            )
            if winner is None:
                expired = await find_any_idempotent_run(
                    session,
                    user_id=user_id,
                    workflow_id=workflow_id,
                    idempotency_key=normalized_idempotency_key,
                )
                if expired is not None:
                    raise HTTPException(
                        status_code=409,
                        detail={
                            "code": "idempotency_key_expired",
                            "message": (
                                "This Idempotency-Key was already used outside "
                                "the replay window. Generate a new key for a new run."
                            ),
                            "run_id": expired.id,
                        },
                    )
                # Vanishingly rare: the unique violation fired but no row is
                # visible to our session yet (replication lag or rollback).
                raise HTTPException(
                    status_code=503,
                    detail="Idempotency reservation race could not be resolved; retry shortly.",
                )
            return await _replay_or_conflict(winner)

    # Pre-execute validation block. If any of these raise an HTTPException
    # (403/429/404), an already-committed reservation row (set above) would
    # stay in ``status='running'`` until the 1-hour idempotency window
    # expires, locking out any retry with the same Idempotency-Key with a
    # 409 ``idempotency_in_progress``. Catch + finalize the orphan row
    # to ``status='error'`` before re-raising so retries can proceed.
    try:
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

        # Audit Item 2: enforce the per-session demo execution quota.  Done
        # after the hidden-node check so a rejected workflow doesn't burn a
        # slot; no-op outside demo.
        from spectra_sherpa.app.api.deps import enforce_demo_execution_quota

        enforce_demo_execution_quota(user_id)
        # wf_integrity_hash / wf_version_id / wf_project_id / wf_params_snapshot
        # are snapshotted earlier in the idempotency block (the reservation
        # path needs them before this point).
        await validate_workflow_execution_access(workflow.nodes, payload.initial_data, user_id, wf_project_id, session)
        await _enforce_advisor_node_egress_policy(
            workflow.nodes,
            workflow.edges,
            current_user=current_user,
            session=session,
            target_node_id=payload.node_id,
        )

        # ISO 17025 audit (Phase 1d): record workflow.run.started in its own
        # transaction so the started event survives even if the execution
        # session rolls back. No-op when audit_enabled is False. Failure of
        # the audit emit cannot block real workflow execution — the
        # informational started event is not the binding record (that's the
        # workflow.run.completed / failed emitted by _auto_persist_run).
        from spectra_sherpa.app.api.v1.routes.workflows._helpers import emit_workflow_run_started

        await emit_workflow_run_started(
            workflow_id=workflow_id,
            workflow_version_id=wf_version_id,
            integrity_hash=wf_integrity_hash,
            params_snapshot=wf_params_snapshot,
        )
    except HTTPException as exc:
        if reservation_id is not None:
            await finalize_orphan_reservation_if_running(
                session,
                reservation_id=reservation_id,
                error_msg=f"Pre-execute validation failed: {exc.detail}",
                exception_class="HTTPException",
            )
        raise

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
                results = await executor.execute_node(
                    payload.node_id,
                    initial_data=payload.initial_data,
                    status_callback=_broadcast_node_status,
                )
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

            training_dataset_id = await _training_dataset_id_from_workflow(session, workflow)
            await persist_model_artifact_records(
                session,
                executor.saved_artifacts,
                user_id=user_id,
                workflow_id=workflow_id,
                workflow_version_id=wf_version_id,
                project_id=wf_project_id,
                training_dataset_id=training_dataset_id,
            )

        # Update workflow execution timestamp.
        #
        # Audit-trail note (Phase 1d): this commit covers two writes —
        # ``workflow.last_executed_at`` (which has no audit event of its
        # own) and the artifact rows persisted by
        # ``persist_model_artifact_records`` (each carries a
        # ``model_artifact.created`` audit event in the same TX). The
        # binding workflow-run audit event lives in the
        # ``_auto_persist_run`` call below, which opens its own logical
        # transaction. The original Phase 1d patch attempted to collapse
        # both commits into one so the run audit covered everything;
        # that change broke route-level autoflush ordering and was
        # reverted. The denormalized ``last_executed_at`` field is
        # treated as derived metadata (not audit-critical); the
        # ExecutionRun row + workflow.run.* audit remain the binding
        # record of what ran.
        workflow.last_executed_at = datetime.utcnow()
        await session.commit()

        error_msg = "; ".join(serialization_errors) if serialization_errors else None
        executor_status = executor.status.value
        final_status = executor_status if not serialization_errors else "partial"
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
        # Audit-side run summary so triage can distinguish a serialization
        # failure (results object couldn't be JSON-encoded) from an actual
        # execution failure (node raised). Both used to collapse into
        # ``status="partial"`` with no way to tell which fired.
        if not isinstance(diagnostics_serialized, dict):
            diagnostics_serialized = {"value": diagnostics_serialized}
        diagnostics_serialized["_run_summary"] = {
            "executor_status": executor_status,
            "serialization_error_count": len(serialization_errors),
            "serialization_errors": serialization_errors,
        }

        # ISO 17025 reproducibility — capture input-port linkage so the
        # audit record can later answer "which data did this run consume?".
        # Phase 1 ships a port-name + data-source-id pair; per-port file
        # hashes / target hashes / fitted-state hashes land in Phase 3
        # alongside the multi-port abstraction.
        input_ports_record = _collect_input_ports(workflow, payload.initial_data)

        # Auto-persist results so they survive page refresh
        run_id = await _auto_persist_run(
            session,
            workflow_id=workflow_id,
            workflow_name=wf_name,
            project_id=wf_project_id,
            user_id=user_id,
            wf_version_id=wf_version_id,
            serialized_results=_compact_results_for_run_history(serialized_results),
            diagnostics_serialized=_compact_diagnostics_for_run_history(diagnostics_serialized),
            node_statuses=node_statuses,
            final_status=final_status,
            error_msg=error_msg,
            integrity_hash=wf_integrity_hash,
            model_ids=list(dict.fromkeys(a["artifact_uid"] for a in (executor.saved_artifacts or []))),
            saved_artifacts=list(executor.saved_artifacts or []),
            params_snapshot=wf_params_snapshot,
            input_ports=input_ports_record,
            source_metadata=_build_source_metadata(
                executor_status=executor_status,
                had_serialization_errors=bool(serialization_errors),
            ),
            idempotency_key=normalized_idempotency_key,
            reservation_id=reservation_id,
        )
        if run_id is None:
            _raise_execution_persistence_error()

        return WorkflowExecuteResponse(
            workflow_id=workflow_id,
            run_id=run_id,
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
        # Persist a terminal "cancelled" run for the timeout so the user
        # sees the failed attempt in run history AND so a retried POST with
        # the same Idempotency-Key replays the cancelled response instead
        # of silently re-executing. Pre-PR this raised 504 directly,
        # leaving only the started audit event.
        timeout_error_msg = f"Workflow execution timed out after {settings.max_job_duration_sec}s"
        try:
            # Roll back any dirty state the executor may have left in the
            # session before opening a fresh write for the cancelled run.
            await session.rollback()
            await _auto_persist_run(
                session,
                workflow_id=workflow_id,
                workflow_name=wf_name,
                project_id=wf_project_id,
                user_id=user_id,
                wf_version_id=wf_version_id,
                serialized_results={},
                diagnostics_serialized={},
                node_statuses=executor.get_status()["node_statuses"] if executor else {},
                final_status="cancelled",
                error_msg=timeout_error_msg,
                integrity_hash=wf_integrity_hash,
                model_ids=[],
                params_snapshot=wf_params_snapshot,
                source_metadata=_build_source_metadata(
                    executor_status="cancelled",
                    had_serialization_errors=False,
                    exception_class="TimeoutError",
                ),
                idempotency_key=normalized_idempotency_key,
                reservation_id=reservation_id,
            )
        except Exception:  # pragma: no cover - persistence must never mask the 504
            logger.warning("Failed to persist timeout ExecutionRun", exc_info=True)
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

                training_dataset_id = await _training_dataset_id_from_workflow(session, workflow)
                await persist_model_artifact_records(
                    session,
                    executor.saved_artifacts,
                    user_id=user_id,
                    workflow_id=workflow_id,
                    workflow_version_id=wf_version_id,
                    project_id=wf_project_id,
                    training_dataset_id=training_dataset_id,
                )
                await session.commit()
            except Exception as art_err:
                logger.warning("Could not persist model artifacts from partial run: %s", art_err)
                try:
                    await session.rollback()
                except Exception:
                    pass
                # The DB rows could not be committed, so
                # these artifacts are now unreachable files on disk with
                # no ModelArtifact row referencing them.  Compensating
                # cleanup — delete them so a failed run can't leak orphan
                # artifacts (the startup reconcile sweep is the backstop
                # for hard kills that skip this handler entirely).
                try:
                    from spectra_sherpa.app.services.model_store import get_model_store

                    orphan_store = get_model_store()
                    for art in executor.saved_artifacts:
                        try:
                            orphan_store.delete(art["artifact_uid"])
                        except Exception as del_err:  # pragma: no cover - best-effort
                            logger.warning(
                                "Could not clean orphan artifact %s: %s",
                                art.get("artifact_uid"),
                                del_err,
                            )
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
        if not isinstance(partial_diagnostics, dict):
            partial_diagnostics = {"value": partial_diagnostics}
        executor_status_for_summary = executor.status.value if executor else "error"
        partial_diagnostics["_run_summary"] = {
            "executor_status": executor_status_for_summary,
            "serialization_error_count": len(partial_serialization_errors),
            "serialization_errors": partial_serialization_errors,
            "exception_class": type(e).__name__,
        }
        partial_node_statuses = executor.get_status()["node_statuses"] if executor else {}

        # Auto-persist partial/error results too
        run_id = await _auto_persist_run(
            session,
            workflow_id=workflow_id,
            workflow_name=wf_name,
            project_id=wf_project_id,
            user_id=user_id,
            wf_version_id=wf_version_id,
            serialized_results=_compact_results_for_run_history(partial_results),
            diagnostics_serialized=_compact_diagnostics_for_run_history(partial_diagnostics),
            node_statuses=partial_node_statuses,
            final_status=response_status,
            error_msg=error_msg,
            integrity_hash=wf_integrity_hash,
            model_ids=list(
                dict.fromkeys(a["artifact_uid"] for a in (getattr(executor, "saved_artifacts", None) or []))
            ),
            saved_artifacts=list(getattr(executor, "saved_artifacts", None) or []),
            params_snapshot=wf_params_snapshot,
            source_metadata=_build_source_metadata(
                executor_status=executor_status_for_summary,
                had_serialization_errors=bool(partial_serialization_errors),
                exception_class=type(e).__name__,
            ),
            idempotency_key=normalized_idempotency_key,
            reservation_id=reservation_id,
        )
        if run_id is None:
            _raise_execution_persistence_error()

        return WorkflowExecuteResponse(
            workflow_id=workflow_id,
            run_id=run_id,
            status=response_status,
            results=partial_results,
            diagnostics=partial_diagnostics,
            node_statuses=partial_node_statuses,
            executed_at=datetime.utcnow(),
            error=error_msg,
            integrity_hash=wf_integrity_hash,
        )
