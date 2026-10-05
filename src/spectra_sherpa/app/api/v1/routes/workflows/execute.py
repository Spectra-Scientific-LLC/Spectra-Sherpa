"""
Execution endpoints: execute / trial / validate.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from spectra_sherpa.app.api.deps import get_current_user, get_session
from spectra_sherpa.app.contracts.project_access import uses_managed_project_access
from spectra_sherpa.app.contracts.scientific_access import ScientificAccessDenied, require_scientific_access
from spectra_sherpa.app.core.config import settings
from spectra_sherpa.app.lib.workflow_purpose import MANAGED_CANDIDATE_AUTHORITY
from spectra_sherpa.app.models.execution_run import ExecutionRun
from spectra_sherpa.app.models.project_data_source import ProjectDataSource
from spectra_sherpa.app.models.user import User
from spectra_sherpa.app.models.workflow import Workflow
from spectra_sherpa.app.models.workflow_version import WorkflowVersion
from spectra_sherpa.app.schemas.workflows import (
    CanonicalProjectSourceBindingRequest,
    TrialExecuteRequest,
    TrialExecuteResponse,
    WorkflowExecuteRequest,
    WorkflowExecuteResponse,
    WorkflowPreflightEdge,
    WorkflowValidationIssue,
    WorkflowValidationResponse,
)
from spectra_sherpa.app.services.canonical_project_binding import (
    CanonicalProjectBindingError,
)
from spectra_sherpa.app.services.canonical_project_binding import (
    bind_canonical_project_source as bind_source,
)
from spectra_sherpa.app.services.canonical_project_custody import (
    CanonicalProjectCustodyError,
    resolve_canonical_application_plan_provenance,
)
from spectra_sherpa.app.services.canonical_project_dependencies import canonical_project_dependency_readiness
from spectra_sherpa.app.services.dag import DAGExecutor
from spectra_sherpa.app.services.dag import WorkflowEdge as DAGEdge
from spectra_sherpa.app.services.dag import WorkflowNode as DAGNode
from spectra_sherpa.app.services.dag.presentation_contract import describe_executed_presentations
from spectra_sherpa.app.services.dag.scientific_values import describe_node_outputs
from spectra_sherpa.app.services.dag.workflow_preflight import WorkflowPreflight, preflight_workflow
from spectra_sherpa.app.services.run_params import (
    build_effective_params_snapshot,
    build_saved_definition_snapshot,
    build_workflow_version_snapshot,
)
from spectra_sherpa.app.services.serialization import serialize_result
from spectra_sherpa.app.services.workflow_access import (
    admitted_model_artifact_ids,
    validate_canonical_application_graph,
    validate_canonical_artifact_bindings,
    validate_workflow_execution_access,
    workflow_requires_canonical_artifact_grant,
)
from spectra_sherpa.app.services.workflow_data_selections import execution_selection_revisions

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


def _index_ranges(indices: list[int]) -> list[list[int]]:
    """Losslessly compact ordered row indices into inclusive ranges."""
    if not indices:
        return []
    ranges: list[list[int]] = []
    start = previous = indices[0]
    for index in indices[1:]:
        if index == previous + 1:
            previous = index
            continue
        ranges.append([start, previous])
        start = previous = index
    ranges.append([start, previous])
    return ranges


def _execution_dataset_scientific_receipts(execution_results: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Project actual typed dataset results into bounded run evidence."""
    from spectra_sherpa.app.lib.sherpa_dataset import SherpaDataset

    receipts: list[dict[str, Any]] = []
    for node_id, value in sorted((execution_results or {}).items()):
        if not isinstance(value, SherpaDataset):
            continue
        labels = (
            [str(label) for label in value.sample_axis.labels]
            if value.sample_axis is not None and value.sample_axis.labels is not None
            else None
        )
        selection_lineage: list[dict[str, Any]] = []
        for step in value.provenance.to_list():
            if step.get("op_id") != "data.filter_samples":
                continue
            parameters = dict(step.get("parameters") or {})
            selected_indices = [int(index) for index in parameters.pop("selected_indices", [])]
            selection_lineage.append(
                {
                    "node_id": step.get("node_id"),
                    "operation": "data.filter_samples",
                    "parameters": parameters,
                    "selected_index_ranges": _index_ranges(selected_indices),
                    "selected_indices_sha256": hashlib.sha256(
                        json.dumps(selected_indices, separators=(",", ":")).encode("utf-8")
                    ).hexdigest(),
                    "input_shape": step.get("input_shape"),
                    "output_shape": step.get("output_shape"),
                }
            )
        receipts.append(
            {
                "node_id": str(node_id),
                "scientific_projection_schema": value.manifest.scientific_projection_schema,
                "scientific_digest": value.scientific_digest,
                "shape": [int(size) for size in value.shape],
                "title": value.title,
                "sample_identity": {
                    "count": int(value.shape[0]),
                    "labels_sha256": (
                        hashlib.sha256(
                            json.dumps(labels, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
                        ).hexdigest()
                        if labels is not None
                        else None
                    ),
                },
                "selection_lineage": selection_lineage,
            }
        )
    return receipts


def _collect_input_ports(
    workflow: Workflow,
    initial_data: dict[str, Any] | None,
    *,
    scientific_receipts: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
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
    for receipt in scientific_receipts or []:
        ports.append(
            {
                "port_name": f"dataset:{receipt['node_id']}",
                "scientific_projection_schema": receipt["scientific_projection_schema"],
                "scientific_digest": receipt["scientific_digest"],
                "shape": receipt["shape"],
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


def _workflow_preflight(workflow: Workflow, target_node_id: str | None = None) -> WorkflowPreflight:
    """Build the saved graph once for the authoritative semantic preflight."""

    return preflight_workflow(
        [
            DAGNode(
                node_id=node.node_id,
                node_type=node.node_type,
                parameters=node.parameters or {},
            )
            for node in workflow.nodes
        ],
        [
            DAGEdge(
                from_node=edge.from_node_id,
                to_node=edge.to_node_id,
                from_output=edge.from_output,
                to_input=edge.to_input,
            )
            for edge in workflow.edges
        ],
        target_node_id=target_node_id,
    )


def _preflight_response_fields(preflight: WorkflowPreflight) -> dict[str, object]:
    """Serialize the pure preflight result without giving the API a second policy."""

    return {
        "semantic_edges": [
            WorkflowPreflightEdge(
                from_node_id=edge.from_node_id,
                from_output=edge.from_output,
                to_node_id=edge.to_node_id,
                to_input=edge.to_input,
                status=edge.status,
                reason=edge.reason,
            )
            for edge in preflight.edges
        ],
    }


def _preflight_issues(preflight: WorkflowPreflight) -> list[WorkflowValidationIssue]:
    """Adapt the shared report to the stable workflow-validation wire shape."""

    return [
        WorkflowValidationIssue(
            level=issue.level,
            code=issue.code,
            node_id=issue.node_id,
            port=issue.port,
            message=issue.message,
        )
        for issue in preflight.issues
    ]


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


def _effective_trial_nodes(payload: TrialExecuteRequest) -> list[Any]:
    """Return the one node projection admitted and executed by a trial run.

    Access checks must see the target node's temporary parameters.  Building
    this projection once prevents a caller from validating one experiment and
    substituting a different experiment only when the DAG is constructed.
    """

    matched_target = False
    effective: list[Any] = []
    for node in payload.nodes:
        if node.node_id == payload.target_node_id:
            matched_target = True
            effective.append(node.model_copy(update={"parameters": dict(payload.trial_params)}))
        else:
            effective.append(node)
    if not matched_target:
        raise HTTPException(status_code=400, detail="Trial target node is not present in the submitted graph")
    return effective


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
    effective_nodes = _effective_trial_nodes(payload)
    preloaded_datasets = await validate_workflow_execution_access(
        effective_nodes,
        payload.initial_data,
        current_user.id,
        payload.project_id,
        session,
    )
    try:
        # Build a fresh DAG executor for this trial (no caching)
        from spectra_sherpa.app.services.execution_runtime import build_application_execution_runtime

        executor = DAGExecutor(
            runtime=build_application_execution_runtime(
                preloaded_datasets=preloaded_datasets,
                allowed_model_artifact_uids=admitted_model_artifact_ids(effective_nodes, payload.initial_data),
            )
        )

        logger.debug(
            "[Trial Execution] Target node: %s (type: %s)", payload.target_node_id, type(payload.target_node_id)
        )
        logger.debug("[Trial Execution] Trial params: %s", payload.trial_params)
        logger.debug("[Trial Execution] Total nodes: %s", len(payload.nodes))

        # Add all nodes to the executor
        for node in effective_nodes:
            is_target = node.node_id == payload.target_node_id
            params = node.parameters

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
        serialized_result = (
            serialize_result(target_result, owner_user_id=current_user.id, project_id=payload.project_id)
            if target_result
            else None
        )
        target_node = executor.nodes.get(payload.target_node_id)
        result_descriptor = (
            describe_node_outputs(target_node.metadata, target_result)
            if target_node is not None and target_result is not None
            else None
        )
        result_presentation = (
            describe_executed_presentations(target_node.metadata, result_descriptor)
            if target_node is not None and result_descriptor is not None
            else None
        )

        return TrialExecuteResponse(
            target_node_id=payload.target_node_id,
            status="completed",
            result=serialized_result,
            result_descriptor=result_descriptor,
            result_presentation=result_presentation,
            diagnostics=serialize_result(
                executor.diagnostics.get(payload.target_node_id, {}),
                owner_user_id=current_user.id,
                project_id=payload.project_id,
            ),
            error=None,
        )

    except Exception as e:
        return TrialExecuteResponse(
            target_node_id=payload.target_node_id,
            status="error",
            result=None,
            result_descriptor=None,
            result_presentation=None,
            error=str(e),
        )


@router.post("/{workflow_id}/preflight", response_model=WorkflowValidationResponse)
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
        .where(or_(Workflow.user_id == user_id, uses_managed_project_access()))
        .options(
            selectinload(Workflow.nodes),
            selectinload(Workflow.edges),
        )
    )
    result = await session.execute(query)
    workflow = result.scalar_one_or_none()

    if workflow is None:
        raise HTTPException(status_code=404, detail="Workflow not found")
    await require_scientific_access(
        session, user_id, workflow.project_id, "execute", resource_owner_id=workflow.user_id
    )

    preflight = _workflow_preflight(workflow)

    all_issues = _preflight_issues(preflight)
    if uses_managed_project_access():
        from spectra_sherpa.app.contracts.scientific_access import QUALIFIED_SCIENTIFIC_NODES

        if any(node.node_type not in QUALIFIED_SCIENTIFIC_NODES for node in workflow.nodes):
            all_issues.append(
                WorkflowValidationIssue(
                    level="error",
                    code="node_not_qualified",
                    message="This workflow contains a node not yet qualified for managed execution.",
                )
            )

    if workflow_requires_canonical_artifact_grant(workflow.nodes):
        try:
            provenance = await resolve_canonical_application_plan_provenance(
                session,
                user_id=user_id,
                workflow_id=workflow.id,
            )
            dependency_readiness = canonical_project_dependency_readiness(provenance.application_plan)
        except CanonicalProjectCustodyError:
            all_issues.append(
                WorkflowValidationIssue(
                    level="error",
                    code="canonical_dependency_provenance_unavailable",
                    message="Canonical project provenance is unavailable; this workflow cannot run.",
                )
            )
        else:
            if not dependency_readiness.ready:
                all_issues.append(
                    WorkflowValidationIssue(
                        level="error",
                        code="canonical_dependency_blocked",
                        message=dependency_readiness.remediation[0],
                    )
                )
    errors = [issue for issue in all_issues if issue.level == "error"]
    warnings = [issue for issue in all_issues if issue.level == "warning"]

    return WorkflowValidationResponse(
        workflow_id=workflow.id,
        is_valid=len(errors) == 0,
        issues=all_issues,
        error_count=len(errors),
        warning_count=len(warnings),
        **_preflight_response_fields(preflight),
    )


@router.put("/{workflow_id}/canonical-source")
async def bind_canonical_project_source(
    workflow_id: int,
    payload: CanonicalProjectSourceBindingRequest,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> dict[str, object]:
    """Persist the scientist-selected source for one canonical application workflow.

    The endpoint never accepts an artifact digest, model state, or arbitrary
    source path.  The workflow's immutable application nodes remain exactly
    those re-admitted from the canonical package.
    """

    try:
        binding = await bind_source(
            session,
            user_id=current_user.id,
            workflow_id=workflow_id,
            experiment_id=payload.experiment_id,
            file_id=payload.file_id,
            stage=payload.stage,
            asset_id=payload.asset_id,
        )
        await session.commit()
    except CanonicalProjectBindingError as exc:
        await session.rollback()
        raise HTTPException(status_code=409, detail="Canonical project source cannot be bound") from exc

    return {
        "workflow_id": binding.workflow_id,
        "source_node_id": binding.source_node_id,
        "integrity_hash": binding.integrity_hash,
        # Keep the established success vocabulary for clients that call this
        # endpoint after selecting data, while exposing the distinct blocked
        # state when the exact sealed runtime is not presently available.
        "status": "ready_for_application" if binding.status == "active" else binding.status,
    }


@router.get("/{workflow_id}/canonical-provenance")
async def get_canonical_project_provenance(
    workflow_id: int,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> dict[str, object]:
    """Read the sealed, data-free application plan without changing the graph.

    Fitted application nodes expose only executable artifact bindings.  This
    explicit endpoint lets the importing scientist inspect the admitted source
    operations and original fitted parameters without turning them into mutable
    workflow-node parameters or execution inputs.
    """

    try:
        provenance = await resolve_canonical_application_plan_provenance(
            session,
            user_id=current_user.id,
            workflow_id=workflow_id,
        )
    except CanonicalProjectCustodyError as exc:
        raise HTTPException(status_code=404, detail="Workflow not found") from exc
    return {
        "workflow_id": provenance.workflow_id,
        "project_id": provenance.project_id,
        "application_plan_digest": provenance.application_plan.application_plan_digest,
        "application_plan": provenance.application_plan.as_dict(),
    }


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
        .where(or_(Workflow.user_id == user_id, uses_managed_project_access()))
        .options(
            selectinload(Workflow.nodes),
            selectinload(Workflow.edges),
            selectinload(Workflow.tags),
            selectinload(Workflow.folder),
            selectinload(Workflow.primary_data_source),
        )
    )
    result = await session.execute(query)
    workflow = result.scalar_one_or_none()

    if workflow is None:
        raise HTTPException(status_code=404, detail="Workflow not found")
    await require_scientific_access(
        session, user_id, workflow.project_id, "execute", resource_owner_id=workflow.user_id
    )
    if workflow.purpose == MANAGED_CANDIDATE_AUTHORITY:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "managed_candidate_requires_harness",
                "message": (
                    "This workflow is the persisted managed-candidate authority. "
                    "It may be inspected here, but only the governed Harness may execute it."
                ),
            },
        )

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
    wf_project_id = getattr(workflow, "project_id", None)
    wf_name = workflow.name
    wf_params_snapshot = build_effective_params_snapshot(workflow.nodes)
    wf_definition_snapshot = build_saved_definition_snapshot(workflow)
    if payload.expected_definition is not None:
        from spectra_sherpa.app.services.dag.integrity import compute_workflow_hash, workflow_definitions_match

        expected = payload.expected_definition.model_dump()
        actual_hash = compute_workflow_hash(wf_definition_snapshot["nodes"], wf_definition_snapshot["edges"])
        if not workflow_definitions_match(expected, wf_definition_snapshot):
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "workflow_definition_changed",
                    "message": "The saved workflow changed before execution. Reload and review before retrying.",
                },
            )
        wf_integrity_hash = actual_hash
        wf_definition_snapshot["integrity_hash"] = actual_hash
    latest_version = await session.scalar(
        select(WorkflowVersion)
        .where(WorkflowVersion.workflow_id == workflow_id)
        .order_by(WorkflowVersion.version_number.desc())
        .limit(1)
    )
    if latest_version is not None:
        await session.refresh(workflow, attribute_names=["data_source_links"])
    wf_version_id = (
        latest_version.id
        if latest_version is not None and latest_version.snapshot == build_workflow_version_snapshot(workflow)
        else None
    )
    wf_data_selection_revisions = await execution_selection_revisions(
        session,
        workflow_id=workflow_id,
        graph_digest=wf_integrity_hash,
        source_nodes=list(workflow.nodes),
        user_id=current_user.id,
        workflow_project_id=workflow.project_id,
    )

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
                            "Another request with this Idempotency-Key is still executing; poll the run for completion."
                        ),
                        "run_id": row.id,
                    },
                )
            results = row.results_summary or {}
            diagnostics = row.diagnostics or {}
            descriptors = diagnostics.get("_scientific_values", {}) if isinstance(diagnostics, dict) else {}
            presentations = diagnostics.get("_scientific_presentations", {}) if isinstance(diagnostics, dict) else {}
            return WorkflowExecuteResponse(
                workflow_id=row.workflow_id or workflow_id,
                run_id=row.id,
                params_snapshot=row.params_snapshot or {},
                status=row.status,
                results=results,
                result_descriptors=descriptors if isinstance(descriptors, dict) else {},
                result_presentations=presentations if isinstance(presentations, dict) else {},
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

    canonical_artifact_read_grant = None

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
        execution_nodes = workflow.nodes
        if payload.node_id:
            from spectra_sherpa.app.services.dag.execution_scope import upstream_node_ids

            try:
                selected = upstream_node_ids(
                    (node.node_id for node in workflow.nodes),
                    [
                        DAGEdge(edge.from_node_id, edge.to_node_id, edge.from_output, edge.to_input)
                        for edge in workflow.edges
                    ],
                    payload.node_id,
                )
            except ValueError as exc:
                raise HTTPException(status_code=422, detail=str(exc)) from exc
            execution_nodes = [node for node in workflow.nodes if node.node_id in selected]
        preloaded_datasets = await validate_workflow_execution_access(
            execution_nodes,
            payload.initial_data,
            user_id,
            wf_project_id,
            session,
        )
        allowed_model_artifact_uids = admitted_model_artifact_ids(execution_nodes, payload.initial_data)
        if workflow_requires_canonical_artifact_grant(workflow.nodes):
            from spectra_sherpa.app.services.canonical_project_custody import (
                CanonicalProjectCustodyError,
                resolve_canonical_artifact_read_grant,
            )

            # A persisted local binding—not a request-time override—makes
            # the scientist's chosen starting data visible and reproducible.
            # DAGExecutor applies ``initial_data`` as node-parameter
            # overrides, so accepting it for *any* node here could alter an
            # admitted fitted-state binding in the same artifact.  Canonical
            # workflows therefore have no request-time override channel.
            if payload.initial_data:
                raise HTTPException(
                    status_code=422,
                    detail=(
                        "Canonical project data and application bindings must be changed through "
                        "persisted workflow state"
                    ),
                )

            # Prove the sealed plan's exact runtime is available before this
            # request receives any artifact-read authority.  A blocked project
            # remains inspectable and may retain its scientist-selected source,
            # but it must neither execute nor resolve the private grant that a
            # worker would use to load fitted model state.
            try:
                provenance = await resolve_canonical_application_plan_provenance(
                    session,
                    user_id=user_id,
                    workflow_id=workflow.id,
                )
                dependency_readiness = canonical_project_dependency_readiness(provenance.application_plan)
            except CanonicalProjectCustodyError as exc:
                raise HTTPException(
                    status_code=404,
                    detail="Canonical artifact is unavailable for this workflow",
                ) from exc
            if not dependency_readiness.ready:
                raise HTTPException(
                    status_code=409,
                    detail={
                        "code": "canonical_dependency_blocked",
                        "message": (
                            "Canonical project runtime dependencies are unavailable or do not match the certified pins."
                        ),
                        "remediation": list(dependency_readiness.remediation),
                    },
                )
            try:
                canonical_artifact_read_grant = await resolve_canonical_artifact_read_grant(
                    session,
                    user_id=user_id,
                    workflow_id=workflow.id,
                )
            except CanonicalProjectCustodyError as exc:
                raise HTTPException(
                    status_code=404,
                    detail="Canonical artifact is unavailable for this workflow",
                ) from exc
            validate_canonical_artifact_bindings(workflow.nodes, canonical_artifact_read_grant.artifact_digest)
            validate_canonical_application_graph(
                workflow.nodes,
                workflow.edges,
                canonical_artifact_read_grant.application_integrity_hash,
            )
        preflight = _workflow_preflight(workflow, target_node_id=payload.node_id)
        if not preflight.is_valid:
            raise HTTPException(
                status_code=422,
                detail={
                    "code": "workflow_preflight_failed",
                    "message": "Workflow is not admissible for execution; inspect validation for details.",
                    "issues": [
                        {
                            "code": issue.code,
                            "node_id": issue.node_id,
                            "port": issue.port,
                            "message": issue.message,
                        }
                        for issue in preflight.issues
                        if issue.level == "error"
                    ],
                },
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
                user_id=user_id,
                error_msg=f"Pre-execute validation failed: {exc.detail}",
                exception_class="HTTPException",
            )
        raise

    executor = None

    async def discard_withdrawn_output():
        await session.rollback()
        # Retain the failed attempt without converting revoked output into a
        # successful/partial response or materializing readable result blobs.
        await _auto_persist_run(
            session,
            workflow_id=workflow_id,
            workflow_name=wf_name,
            user_id=user_id,
            project_id=wf_project_id,
            wf_version_id=wf_version_id,
            serialized_results={},
            diagnostics_serialized={"authority_withdrawn": True},
            node_statuses={},
            final_status="cancelled",
            error_msg="Scientific authority was withdrawn during execution",
            integrity_hash=wf_integrity_hash,
            produced_artifact_uids=[],
            params_snapshot=wf_params_snapshot,
            idempotency_key=normalized_idempotency_key,
            reservation_id=reservation_id,
        )
        if executor and getattr(executor, "saved_artifacts", None):
            from spectra_sherpa.app.services.model_store import get_model_store

            for artifact in executor.saved_artifacts:
                try:
                    get_model_store().delete(artifact["artifact_uid"])
                except Exception:
                    logger.warning("Failed to remove withdrawn execution artifact", exc_info=True)

    try:
        # Build DAG executor
        from spectra_sherpa.app.services.execution_runtime import build_application_execution_runtime

        executor = DAGExecutor(
            runtime=build_application_execution_runtime(
                canonical_artifact_read_grant=canonical_artifact_read_grant,
                preloaded_datasets=preloaded_datasets,
                allowed_model_artifact_uids=allowed_model_artifact_uids,
            )
        )

        if wf_definition_snapshot.get("fold_validation_plan") is not None:
            from spectra_sherpa.app.services.dag.sheet_fold_validation import SheetFoldValidationPlan

            # A malformed retained plan is refused by execution, never ignored:
            # dropping it would silently change the sheet's validation scope.
            executor.fold_validation_plan = SheetFoldValidationPlan.from_dict(
                wf_definition_snapshot["fold_validation_plan"]
            )

        # Build from the frozen definition checked against the caller snapshot.
        # Later ORM refreshes/other clients cannot change this execution's graph.
        for node in wf_definition_snapshot["nodes"]:
            if payload.node_id and node["node_id"] not in selected:
                continue
            executor.add_node(
                DAGNode(
                    node_id=node["node_id"],
                    node_type=node["node_type"],
                    parameters=node["parameters"],
                )
            )
        for edge in wf_definition_snapshot["edges"]:
            if payload.node_id and edge["to_node_id"] not in selected:
                continue
            executor.add_edge(
                DAGEdge(
                    from_node=edge["from_node_id"],
                    to_node=edge["to_node_id"],
                    from_output=edge["from_output"],
                    to_input=edge["to_input"],
                )
            )

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

        await require_scientific_access(session, user_id, wf_project_id, "execute")
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

        # Authority may lapse during a run. Keep failure provenance, but do
        # not serialize or disclose output after access is withdrawn.
        await require_scientific_access(session, user_id, wf_project_id, "execute")
        # Serialize results to JSON-safe format (per-node, so one failure doesn't lose all)
        logger.debug("[Serialization] Starting serialization of %s node results...", len(results))
        serialized_results = {}
        result_descriptors: dict[str, dict[str, Any]] = {}
        result_presentations: dict[str, dict[str, Any]] = {}
        serialization_errors = []
        for node_id, node_result in results.items():
            result_type = type(node_result).__name__
            try:
                serialized_results[node_id] = serialize_result(
                    node_result, owner_user_id=user_id, project_id=wf_project_id
                )
                result_descriptors[node_id] = describe_node_outputs(
                    executor.nodes[node_id].metadata,
                    node_result,
                )
                result_presentations[node_id] = describe_executed_presentations(
                    executor.nodes[node_id].metadata,
                    result_descriptors[node_id],
                )
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

        diagnostics_serialized = serialize_result(
            getattr(executor, "diagnostics", {}), owner_user_id=user_id, project_id=wf_project_id
        )
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
        # Persist the descriptor ledger with diagnostics so page reload and
        # idempotent replay render the same scientific meanings as the live
        # response without duplicating any numerical payload.
        diagnostics_serialized["_scientific_values"] = result_descriptors
        diagnostics_serialized["_scientific_presentations"] = result_presentations

        # ISO 17025 reproducibility — capture input-port linkage so the
        # audit record can later answer "which data did this run consume?".
        # Phase 1 ships a port-name + data-source-id pair; per-port file
        # hashes / target hashes / fitted-state hashes land in Phase 3
        # alongside the multi-port abstraction.
        scientific_receipts = _execution_dataset_scientific_receipts(executor.results)
        input_ports_record = _collect_input_ports(
            workflow,
            payload.initial_data,
            scientific_receipts=scientific_receipts,
        )

        # Auto-persist results so they survive page refresh. Retention can
        # reject a large output after computation succeeds; carry that
        # warning back to the HTTP response so the GUI does not report a
        # fully completed run when durable evidence is incomplete.
        retention_feedback: dict[str, Any] = {}
        run_id = await _auto_persist_run(
            session,
            workflow_id=workflow_id,
            workflow_name=wf_name,
            project_id=wf_project_id,
            user_id=user_id,
            wf_version_id=wf_version_id,
            serialized_results=_compact_results_for_run_history(serialized_results),
            diagnostics_serialized=_compact_diagnostics_for_run_history(diagnostics_serialized),
            raw_outputs_for_retention=results,
            definition_for_retention=wf_definition_snapshot,
            diagnostics_for_retention=diagnostics_serialized,
            node_statuses=node_statuses,
            final_status=final_status,
            error_msg=error_msg,
            integrity_hash=wf_integrity_hash,
            produced_artifact_uids=list(dict.fromkeys(a["artifact_uid"] for a in (executor.saved_artifacts or []))),
            saved_artifacts=list(executor.saved_artifacts or []),
            params_snapshot=wf_params_snapshot,
            input_ports=input_ports_record,
            source_metadata=_build_source_metadata(
                executor_status=executor_status,
                had_serialization_errors=bool(serialization_errors),
                dataset_scientific_receipts=scientific_receipts,
                data_selection_revisions=wf_data_selection_revisions,
            ),
            idempotency_key=normalized_idempotency_key,
            reservation_id=reservation_id,
            retention_feedback=retention_feedback,
        )
        if run_id is None:
            _raise_execution_persistence_error()
        retention_warning = retention_feedback.get("warning")
        if retention_warning:
            final_status = "partial" if final_status == "completed" else final_status
            error_msg = f"{error_msg}; {retention_warning}" if error_msg else retention_warning

        return WorkflowExecuteResponse(
            workflow_id=workflow_id,
            run_id=run_id,
            params_snapshot=wf_params_snapshot,
            status=final_status,
            results=serialized_results,
            result_descriptors=result_descriptors,
            result_presentations=result_presentations,
            diagnostics=diagnostics_serialized,
            node_statuses=node_statuses,
            executed_at=datetime.utcnow(),
            error=error_msg,
            integrity_hash=wf_integrity_hash,
        )

    except ScientificAccessDenied:
        await discard_withdrawn_output()
        raise

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
                produced_artifact_uids=[],
                params_snapshot=wf_params_snapshot,
                source_metadata=_build_source_metadata(
                    executor_status="cancelled",
                    had_serialization_errors=False,
                    exception_class="TimeoutError",
                    data_selection_revisions=wf_data_selection_revisions,
                ),
                idempotency_key=normalized_idempotency_key,
                reservation_id=reservation_id,
            )
        except Exception:  # pragma: no cover - persistence must never mask the 504
            logger.warning("Failed to persist timeout ExecutionRun", exc_info=True)
        raise HTTPException(
            status_code=504,
            detail=(f"Workflow execution timed out. Reference limit: {settings.max_job_duration_sec}s"),
        ) from e

    except Exception as e:
        # A node failure must not turn revoked output into a partial response.
        if uses_managed_project_access():
            await session.rollback()
            try:
                await require_scientific_access(session, user_id, wf_project_id, "execute")
            except ScientificAccessDenied:
                await discard_withdrawn_output()
                raise
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
        partial_result_descriptors: dict[str, dict[str, Any]] = {}
        partial_result_presentations: dict[str, dict[str, Any]] = {}
        partial_serialization_errors: list[str] = []
        raw_results = executor.results if executor else {}
        for node_id, node_result in raw_results.items():
            result_type = type(node_result).__name__
            try:
                partial_results[node_id] = serialize_result(
                    node_result, owner_user_id=user_id, project_id=wf_project_id
                )
                partial_result_descriptors[node_id] = describe_node_outputs(
                    executor.nodes[node_id].metadata,
                    node_result,
                )
                partial_result_presentations[node_id] = describe_executed_presentations(
                    executor.nodes[node_id].metadata,
                    partial_result_descriptors[node_id],
                )
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
            project_id=wf_project_id,
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
        partial_diagnostics["_scientific_values"] = partial_result_descriptors
        partial_diagnostics["_scientific_presentations"] = partial_result_presentations
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
            raw_outputs_for_retention=raw_results,
            definition_for_retention=wf_definition_snapshot,
            diagnostics_for_retention=partial_diagnostics,
            node_statuses=partial_node_statuses,
            final_status=response_status,
            error_msg=error_msg,
            integrity_hash=wf_integrity_hash,
            produced_artifact_uids=list(
                dict.fromkeys(a["artifact_uid"] for a in (getattr(executor, "saved_artifacts", None) or []))
            ),
            saved_artifacts=list(getattr(executor, "saved_artifacts", None) or []),
            params_snapshot=wf_params_snapshot,
            source_metadata=_build_source_metadata(
                executor_status=executor_status_for_summary,
                had_serialization_errors=bool(partial_serialization_errors),
                exception_class=type(e).__name__,
                data_selection_revisions=wf_data_selection_revisions,
            ),
            idempotency_key=normalized_idempotency_key,
            reservation_id=reservation_id,
        )
        if run_id is None:
            _raise_execution_persistence_error()

        return WorkflowExecuteResponse(
            workflow_id=workflow_id,
            run_id=run_id,
            params_snapshot=wf_params_snapshot,
            status=response_status,
            results=partial_results,
            result_descriptors=partial_result_descriptors,
            result_presentations=partial_result_presentations,
            diagnostics=partial_diagnostics,
            node_statuses=partial_node_statuses,
            executed_at=datetime.utcnow(),
            error=error_msg,
            integrity_hash=wf_integrity_hash,
        )
