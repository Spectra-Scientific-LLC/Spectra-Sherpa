"""
Shared helpers for workflow route sub-modules.
"""

from __future__ import annotations

import logging
import math
from datetime import datetime
from typing import Any
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from spectra_sherpa.app.core.request_id import get_request_id
from spectra_sherpa.app.models.execution_run import ExecutionRun
from spectra_sherpa.app.services.audit import audit_emitter, build_reproducibility_record

logger = logging.getLogger(__name__)


_RUN_ACTION_BY_STATUS = {
    "completed": "workflow.run.completed",
    "partial": "workflow.run.partial",
    "error": "workflow.run.failed",
    "failed": "workflow.run.failed",
}


def _run_action_from_status(status: str) -> str:
    """Map an ExecutionRun final-status string to an audit action verb.

    Unknown statuses fall back to ``workflow.run.completed`` so we never
    emit a corrupted action verb; the unknown status itself is recorded
    in the event's ``after_state``.
    """
    return _RUN_ACTION_BY_STATUS.get(status, "workflow.run.completed")


def _build_run_reproducibility_record(
    run_data: dict[str, Any],
    model_ids: list[str] | None,
    *,
    input_ports: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Thin shim that feeds the auto-persist run data into the canonical
    :func:`build_reproducibility_record` helper.

    Phase 1d swapped the local field-by-field dict construction for the
    central builder so the execution-environment block (git sha, python
    runtime + lockfile hash, node-registry hash, runtime image,
    hostname / pid / container id) is captured uniformly across every
    workflow.run.* event.

    The follow-up patch added ``input_ports`` so the record carries the
    list of inputs that were bound at run time. Each entry is a dict
    with at least ``port_name``; richer per-port hashing
    (``dataset_hash``, ``file_hashes``, ``target_hash``) lands with the
    multi-port abstraction in Phase 3 — the v1 contract just requires
    the *list* to be present and identifiable.
    """
    return build_reproducibility_record(
        workflow_id=run_data.get("workflow_id"),
        workflow_version_id=run_data.get("workflow_version_id"),
        workflow_integrity_hash=run_data.get("integrity_hash"),
        parameter_set=run_data.get("params_snapshot"),
        model_artifact_uids=list(model_ids or []),
        input_ports=input_ports or [],
    )


def _sanitize_json(obj: Any) -> Any:
    """Replace NaN/Inf floats with None so PostgreSQL JSON accepts the payload."""
    if isinstance(obj, float) and (math.isnan(obj) or math.isinf(obj)):
        return None
    if isinstance(obj, dict):
        return {k: _sanitize_json(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_sanitize_json(v) for v in obj]
    return obj


async def emit_workflow_run_started(
    *,
    workflow_id: int,
    workflow_version_id: int | None,
    integrity_hash: str | None,
    params_snapshot: dict[str, Any] | None,
) -> None:
    """Emit a ``workflow.run.started`` audit event in its own transaction.

    Uses a dedicated session so the started event commits independently
    of the route's main execution session — the started record survives
    even when execution rolls back on failure. This is the pre-mirror
    of the §5.4 two-transaction pattern: started lives in its own TX
    at the top of the route; completed / failed live in the
    ``_auto_persist_run`` TX at the bottom.

    No-op when ``audit_enabled`` is False (the emitter short-circuits).
    Catches and logs any audit-side error so a flaky audit pipeline
    cannot block a real workflow run from starting — *the started
    event is informational; the workflow.run.completed / failed event
    at the end is the binding fail-closed record*.
    """
    # Cheap pre-check: when audit is disabled the entire helper is a
    # no-op. This avoids opening a fresh session + connection pool
    # round-trip on every workflow execution when the audit subsystem
    # is off (the OSS-Local default).
    from spectra_sherpa.app.core.config import app_config

    if not app_config.audit_enabled:
        return

    try:
        from spectra_sherpa.app.db.session import async_session

        async with async_session() as session:
            audit_emitter.emit(
                session=session,
                action="workflow.run.started",
                target_type="Workflow",
                target_id=workflow_id,
                after={
                    "workflow_version_id": workflow_version_id,
                    "integrity_hash": integrity_hash,
                },
                context={
                    "reproducibility_record": build_reproducibility_record(
                        workflow_id=workflow_id,
                        workflow_version_id=workflow_version_id,
                        workflow_integrity_hash=integrity_hash,
                        parameter_set=params_snapshot,
                    )
                },
            )
            await session.commit()
    except Exception:  # pragma: no cover - audit must never block exec
        logger.warning("Failed to emit workflow.run.started audit event", exc_info=True)


async def _auto_persist_run(
    session: AsyncSession,
    *,
    workflow_id: int,
    user_id: int,
    wf_version_id: int | None,
    serialized_results: dict[str, Any],
    diagnostics_serialized: dict[str, Any],
    node_statuses: dict[str, str],
    final_status: str,
    error_msg: str | None,
    integrity_hash: str | None,
    model_ids: list[str] | None,
    params_snapshot: dict[str, Any] | None = None,
    input_ports: list[dict[str, Any]] | None = None,
) -> bool:
    """Upsert an auto-saved ``ExecutionRun`` so results survive page refresh."""
    try:
        existing = (
            await session.execute(
                select(ExecutionRun).where(
                    ExecutionRun.workflow_id == workflow_id,
                    ExecutionRun.user_id == user_id,
                    ExecutionRun.source_type == "auto",
                )
            )
        ).scalar_one_or_none()

        run_data = dict(
            workflow_id=workflow_id,
            workflow_version_id=wf_version_id,
            user_id=user_id,
            name="__latest__",
            status=final_status,
            params_snapshot=params_snapshot or {},
            results_summary=_sanitize_json(serialized_results),
            diagnostics=_sanitize_json(diagnostics_serialized),
            node_statuses=node_statuses,
            error=error_msg,
            integrity_hash=integrity_hash,
            executed_at=datetime.utcnow(),
            source_type="auto",
            model_ids=model_ids or [],
        )

        if existing:
            for k, v in run_data.items():
                if k not in ("workflow_id", "user_id"):
                    setattr(existing, k, v)
            run_row = existing
        else:
            run_row = ExecutionRun(**run_data)
            session.add(run_row)

        # When audit is enabled, flush to assign the new ExecutionRun's
        # PK so the audit event can attach to it; then emit the
        # workflow.run.* event in the SAME transaction as the run-row
        # mutation. Fail-closed (decision #9): an audit row that fails
        # to insert rolls the whole transaction back, so the user sees
        # an error rather than a silent unaudited run.
        #
        # When audit is disabled, skip the flush + emit pair entirely
        # — this preserves the pre-Phase-1d hot path exactly (one
        # commit, no extra flush) and avoids touching session state
        # the route may not expect to be flushed at this point.
        from spectra_sherpa.app.core.config import app_config as _app_config

        if _app_config.audit_enabled:
            await session.flush()
            audit_emitter.emit(
                session=session,
                action=_run_action_from_status(final_status),
                target_type="ExecutionRun",
                target_id=run_row.id,
                after={
                    "status": final_status,
                    "workflow_id": workflow_id,
                    "workflow_version_id": wf_version_id,
                    "error": error_msg,
                    "model_artifact_count": len(model_ids or []),
                },
                context={
                    "reproducibility_record": _build_run_reproducibility_record(
                        run_data,
                        model_ids,
                        input_ports=input_ports,
                    )
                },
            )

        await session.commit()
        return True
    except Exception:
        logger.warning("Failed to auto-persist execution run", exc_info=True)
        try:
            await session.rollback()
        except Exception:
            pass
        return False


def _raise_execution_persistence_error() -> None:
    # See ``predict.py`` for the same pattern: full ID lands in the log
    # via the ``[req=%(request_id)s]`` formatter; the short form is for
    # the user-facing detail string.
    full_request_id = get_request_id() or uuid4().hex
    short_id = full_request_id[:8]
    logger.error("Workflow execution completed but results could not be persisted")
    raise HTTPException(
        status_code=500,
        detail=("Workflow execution completed but results could not be saved. " f"Reference request ID: {short_id}"),
    )


def _validate_edge_refs(
    nodes: list,
    edges: list,
) -> None:
    """Ensure all edge endpoints reference existing node IDs.

    Also rejects self-loops and duplicate edges.
    """
    node_ids = {n.node_id for n in nodes}
    errors: list[str] = []
    seen: set[tuple] = set()
    for i, e in enumerate(edges):
        if e.from_node_id not in node_ids:
            errors.append(f"Edge {i}: from_node_id '{e.from_node_id}' not in nodes")
        if e.to_node_id not in node_ids:
            errors.append(f"Edge {i}: to_node_id '{e.to_node_id}' not in nodes")
        if e.from_node_id == e.to_node_id:
            errors.append(f"Edge {i}: self-loop on '{e.from_node_id}'")
        key = (e.from_node_id, e.to_node_id, e.from_output, e.to_input)
        if key in seen:
            errors.append(f"Edge {i}: duplicate edge")
        seen.add(key)
    if errors:
        raise HTTPException(status_code=400, detail="; ".join(errors))
