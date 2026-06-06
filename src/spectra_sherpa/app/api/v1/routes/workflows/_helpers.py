"""
Shared helpers for workflow route sub-modules.
"""

from __future__ import annotations

import logging
import math
import re
from datetime import datetime, timedelta
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
    "cancelled": "workflow.run.failed",
}

# Statuses that mean "this row will not change again." Idempotency replay
# only fires for terminal rows; a reservation row sitting in ``running``
# means another request is mid-execute and a retry should NOT replay yet.
TERMINAL_RUN_STATUSES: frozenset[str] = frozenset({"completed", "partial", "error", "failed", "cancelled"})

_PERSISTED_DATASET_PREVIEW_ROWS = 20
_PERSISTED_DATASET_PREVIEW_COLS = 128
_PERSISTED_METADATA_SEQUENCE_PREVIEW = 24
_PERSISTED_DIAGNOSTIC_SEQUENCE_PREVIEW = 32
_SHERPA_DATASET_TYPE = "SherpaDataset"
_LEGACY_DATASET_TYPE = "ND" + "Dataset"
_COMPACTED_DATASET_TYPES = frozenset({_SHERPA_DATASET_TYPE, _LEGACY_DATASET_TYPE})


def _run_action_from_status(status: str) -> str:
    """Map an ExecutionRun final-status string to an audit action verb.

    Unknown statuses fall back to ``workflow.run.completed`` so we never
    emit a corrupted action verb; the unknown status itself is recorded
    in the event's ``after_state``.
    """
    return _RUN_ACTION_BY_STATUS.get(status, "workflow.run.completed")


def _build_source_metadata(
    *,
    executor_status: str,
    had_serialization_errors: bool,
    exception_class: str | None = None,
) -> dict[str, Any]:
    """Compose the ``source_metadata`` blob persisted on an auto-saved run.

    Captures the request id (so logs can be correlated with the row) and a
    compact summary of what happened during execution. The summary lets
    triage tell a "serialization failed" run apart from an "execution
    failed" run without parsing the free-form ``error`` field.
    """
    payload: dict[str, Any] = {
        "executor_status": executor_status,
        "had_serialization_errors": had_serialization_errors,
    }
    request_id = get_request_id()
    if request_id:
        payload["request_id"] = request_id
    if exception_class:
        payload["exception_class"] = exception_class
    return payload


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


def _is_scalar_sequence(value: Any) -> bool:
    return isinstance(value, list) and all(v is None or isinstance(v, (str, int, float, bool)) for v in value)


def _summarize_long_sequence(value: list[Any], *, preview: int) -> dict[str, Any]:
    tail = value[-1] if value else None
    return {
        "_truncated_sequence": True,
        "length": len(value),
        "preview": value[:preview],
        "last": tail,
    }


def _compact_metadata_for_run_history(value: Any) -> Any:
    """Keep metadata useful while avoiding large embedded axes/spectra."""
    if isinstance(value, dict):
        return {k: _compact_metadata_for_run_history(v) for k, v in value.items()}
    if isinstance(value, list):
        if len(value) > _PERSISTED_METADATA_SEQUENCE_PREVIEW and _is_scalar_sequence(value):
            return _summarize_long_sequence(value, preview=_PERSISTED_METADATA_SEQUENCE_PREVIEW)
        if len(value) > _PERSISTED_METADATA_SEQUENCE_PREVIEW and all(isinstance(v, list) for v in value):
            return {
                "_truncated_matrix": True,
                "rows": len(value),
                "preview": [
                    _compact_metadata_for_run_history(row)
                    for row in value[: min(3, _PERSISTED_METADATA_SEQUENCE_PREVIEW)]
                ],
            }
        return [_compact_metadata_for_run_history(v) for v in value]
    return value


def _compact_axis_for_run_history(axis: Any, *, limit: int) -> Any:
    if not isinstance(axis, dict):
        return _compact_metadata_for_run_history(axis)
    compacted: dict[str, Any] = {}
    for key, value in axis.items():
        if key in {"data", "labels"} and isinstance(value, list) and len(value) > limit:
            compacted[key] = value[:limit]
            compacted[f"{key}_truncated"] = True
            compacted[f"{key}_original_length"] = len(value)
            if key == "data" and value:
                compacted["data_min"] = value[0]
                compacted["data_max"] = value[-1]
        else:
            compacted[key] = _compact_metadata_for_run_history(value)
    return compacted


def _compact_matrix_preview(value: Any) -> tuple[Any, bool, int | None, int | None]:
    if not isinstance(value, list):
        return value, False, None, None
    rows = len(value)
    cols = max((len(row) for row in value if isinstance(row, list)), default=None)
    truncated = rows > _PERSISTED_DATASET_PREVIEW_ROWS or (cols is not None and cols > _PERSISTED_DATASET_PREVIEW_COLS)
    if not truncated:
        return value, False, rows, cols
    preview_rows = value[:_PERSISTED_DATASET_PREVIEW_ROWS]
    compacted = [row[:_PERSISTED_DATASET_PREVIEW_COLS] if isinstance(row, list) else row for row in preview_rows]
    return compacted, True, rows, cols


def _compact_sherpa_dataset_for_run_history(dataset: dict[str, Any]) -> dict[str, Any]:
    """Persist a dataset preview, not a full matrix copy.

    The live execute response still carries full node results. This helper is
    only for ExecutionRun.results_summary, where large spectral matrices make
    run persistence fragile and duplicate data already stored elsewhere.
    """
    compacted: dict[str, Any] = {}
    data_truncated = False

    for key, value in dataset.items():
        if key == "data":
            compacted_data, data_truncated, original_rows, original_cols = _compact_matrix_preview(value)
            compacted[key] = compacted_data
            if data_truncated:
                compacted["persisted_preview"] = True
                compacted["data_truncated"] = True
                compacted["stored_rows"] = len(compacted_data) if isinstance(compacted_data, list) else None
                compacted["stored_cols"] = (
                    max((len(row) for row in compacted_data if isinstance(row, list)), default=None)
                    if isinstance(compacted_data, list)
                    else None
                )
                compacted["original_rows"] = original_rows
                compacted["original_cols"] = original_cols
            continue
        if key == "x_axis":
            compacted[key] = _compact_axis_for_run_history(value, limit=_PERSISTED_DATASET_PREVIEW_COLS)
            continue
        if key == "y_axis":
            compacted[key] = _compact_axis_for_run_history(value, limit=_PERSISTED_DATASET_PREVIEW_ROWS)
            continue
        if key == "target":
            compacted_target, target_truncated, original_rows, original_cols = _compact_matrix_preview(value)
            compacted[key] = compacted_target
            if target_truncated:
                compacted["target_truncated"] = True
                compacted["target_original_rows"] = original_rows
                compacted["target_original_cols"] = original_cols
            continue
        if key in {"metadata", "extra"}:
            compacted[key] = _compact_metadata_for_run_history(value)
            continue
        compacted[key] = _compact_results_for_run_history(value, _path=(key,))

    if compacted.get("type") in _COMPACTED_DATASET_TYPES:
        compacted.setdefault("persisted_summary", data_truncated)
    return compacted


def _preserve_large_result_lists(path: tuple[str, ...]) -> bool:
    return any(part in {"visualization", "plots"} for part in path)


def _compact_results_for_run_history(value: Any, *, _path: tuple[str, ...] = ()) -> Any:
    """Reduce persisted run results while preserving output plots/tables.

    ExecutionRun.results_summary is used for run history, comparison, Advisor
    context, and post-refresh restoration. It should carry shapes, scalar
    metrics, tables, and final visualization payloads, but not duplicate every
    raw spectral matrix and intermediate matrix inline.
    """
    if isinstance(value, dict):
        if value.get("type") in _COMPACTED_DATASET_TYPES:
            return _compact_sherpa_dataset_for_run_history(value)
        return {k: _compact_results_for_run_history(v, _path=(*_path, k)) for k, v in value.items()}
    if isinstance(value, list):
        if not _preserve_large_result_lists(_path):
            if len(value) > _PERSISTED_METADATA_SEQUENCE_PREVIEW and _is_scalar_sequence(value):
                return _summarize_long_sequence(value, preview=_PERSISTED_METADATA_SEQUENCE_PREVIEW)
            if len(value) > _PERSISTED_METADATA_SEQUENCE_PREVIEW and all(isinstance(v, list) for v in value):
                return {
                    "_truncated_matrix": True,
                    "rows": len(value),
                    "preview": [
                        _compact_results_for_run_history(row, _path=_path)
                        for row in value[: min(3, _PERSISTED_METADATA_SEQUENCE_PREVIEW)]
                    ],
                }
        return [_compact_results_for_run_history(v, _path=_path) for v in value]
    return value


def _compact_diagnostics_for_run_history(value: Any) -> Any:
    """Diagnostics should be scalar-rich; large arrays are summarized."""
    if isinstance(value, dict):
        return {k: _compact_diagnostics_for_run_history(v) for k, v in value.items()}
    if isinstance(value, list):
        if len(value) > _PERSISTED_DIAGNOSTIC_SEQUENCE_PREVIEW and _is_scalar_sequence(value):
            return _summarize_long_sequence(value, preview=_PERSISTED_DIAGNOSTIC_SEQUENCE_PREVIEW)
        if len(value) > _PERSISTED_DIAGNOSTIC_SEQUENCE_PREVIEW:
            return {
                "_truncated_sequence": True,
                "length": len(value),
                "preview": [
                    _compact_diagnostics_for_run_history(v) for v in value[:_PERSISTED_DIAGNOSTIC_SEQUENCE_PREVIEW]
                ],
            }
        return [_compact_diagnostics_for_run_history(v) for v in value]
    return value


_RUN_HISTORY_TRUNCATION_FLAGS = {
    "_truncated_matrix",
    "_truncated_sequence",
    "data_truncated",
    "labels_truncated",
    "persisted_summary",
    "target_truncated",
}


def contains_run_history_truncation(value: Any) -> bool:
    """Return True when a persisted run payload carries compacted previews.

    Fresh execute responses return full in-memory results. Idempotency replay
    reads from ExecutionRun.results_summary/diagnostics, which are intentionally
    compacted for run history. Expose that difference explicitly so clients do
    not mistake a replayed corner preview for full spectral data.
    """

    if isinstance(value, dict):
        if any(bool(value.get(key)) for key in _RUN_HISTORY_TRUNCATION_FLAGS):
            return True
        return any(contains_run_history_truncation(item) for item in value.values())
    if isinstance(value, list):
        return any(contains_run_history_truncation(item) for item in value)
    return False


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


def _derive_run_display_name(
    workflow_name: str | None,
    integrity_hash: str | None,
    saved_artifacts: list[dict[str, Any]] | None = None,
) -> str:
    """Derive a human-readable default name for an auto-persisted run.

    Mirrors ``persist_model_artifact_records``'s artifact-naming pattern
    so a training run's name matches the artifact it produced (e.g. both
    show ``"SIMCA — 4a4b4c4d"`` in the GUI). Non-training runs fall back
    to ``"<workflow> — <hash[:8]>"`` so the Run History column is always
    readable even when no artifact is emitted.

    Note: the runtime sentinel for "this is an auto-saved run that the
    user has not explicitly named" is ``source_type == 'auto'``, not the
    legacy ``name == '__latest__'`` placeholder; callers that flip the
    run to ``'named'`` continue to overwrite this default.
    """
    if saved_artifacts:
        first = saved_artifacts[0]
        artifact_uid = first.get("artifact_uid") or ""
        model_type = (first.get("model_type") or "model").upper()
        if artifact_uid:
            return f"{model_type} — {artifact_uid[:8]}"
    suffix = (integrity_hash or "")[:8]
    base = workflow_name or "Workflow"
    if suffix:
        return f"{base} — {suffix}"
    return base


async def _reserve_run(
    session: AsyncSession,
    *,
    workflow_id: int,
    user_id: int,
    project_id: int | None,
    wf_version_id: int | None,
    integrity_hash: str | None,
    idempotency_key: str,
    params_snapshot: dict[str, Any] | None,
    workflow_name: str | None = None,
) -> ExecutionRun | None:
    """Claim an Idempotency-Key by inserting a placeholder ExecutionRun.

    The reservation row is committed immediately on the caller's session
    so:
      * the unique partial index on ``(user_id, workflow_id, idempotency_key)``
        enforces single-flight atomicity across concurrent requests;
      * the row is visible to a losing-race caller that needs to replay
        via :func:`find_idempotent_run`.

    Committing on the route's session ends its current transaction; SQLAlchemy
    auto-begins a new one for subsequent queries, so downstream execute /
    serialize / finalize work continues normally.

    Returns the persisted row on success. Raises ``IntegrityError`` if the
    key is already claimed (the partial-unique index fires). The caller is
    responsible for catching that and dispatching via
    :func:`find_idempotent_run`.
    """
    from sqlalchemy.exc import IntegrityError  # local import — only this path needs it

    row = ExecutionRun(
        project_id=project_id,
        workflow_id=workflow_id,
        workflow_version_id=wf_version_id,
        user_id=user_id,
        # Provisional name — finalize will recompute with the artifacts
        # produced by the run. ``running`` is in the relaxed status
        # allowlist that b0c2d4e6f938 added.
        name=_derive_run_display_name(workflow_name, integrity_hash),
        status="running",
        params_snapshot=params_snapshot or {},
        results_summary={},
        executed_at=datetime.utcnow(),
        source_type="auto",
        integrity_hash=integrity_hash,
        idempotency_key=idempotency_key,
        # Run kind is provisional until finalize knows whether the
        # workflow saved a training artifact; ``data`` is the safe
        # default since the strict CHECK accepts it.
        run_kind="data",
    )
    session.add(row)
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        raise
    await session.refresh(row)
    return row


async def finalize_orphan_reservation_if_running(
    session: AsyncSession,
    *,
    reservation_id: int,
    error_msg: str,
    exception_class: str | None = None,
) -> bool:
    """Defensive cleanup for reservations that never reached _auto_persist_run.

    The route's reservation row is committed BEFORE the demo-quota /
    hidden-node / data-access validation block runs (and before the
    executor's own try/except). If any of those validation steps raises
    an HTTPException, the reservation row stays in ``status='running'``
    forever -- subsequent retries with the same Idempotency-Key then 409
    ``idempotency_in_progress`` for the entire 1-hour replay window,
    locking the user out of their workflow.

    This helper finalizes the row to ``status='error'`` ONLY when it is
    still in the running state, so it's safe to call from a ``finally``
    block on the success path too (the row is already terminal, the
    function is a no-op). Returns True if a finalize was performed.

    Failures inside this helper are logged and swallowed -- the caller's
    re-raise of the original exception must not be masked by a cleanup
    error.
    """
    try:
        row = (
            await session.execute(select(ExecutionRun).where(ExecutionRun.id == reservation_id))
        ).scalar_one_or_none()
        if row is None or row.status != "running":
            return False

        for k, v in {
            "status": "error",
            "error": error_msg,
            "executed_at": datetime.utcnow(),
            "source_metadata": _build_source_metadata(
                executor_status="error",
                had_serialization_errors=False,
                exception_class=exception_class,
            ),
        }.items():
            setattr(row, k, v)
        await session.commit()
        return True
    except Exception:  # pragma: no cover - cleanup must never mask the real exception
        logger.warning(
            "Failed to finalize orphan reservation id=%s; row may stay in 'running' until idempotency window expires",
            reservation_id,
            exc_info=True,
        )
        try:
            await session.rollback()
        except Exception:
            pass
        return False


async def _auto_persist_run(
    session: AsyncSession,
    *,
    workflow_id: int,
    workflow_name: str | None = None,
    user_id: int,
    project_id: int | None = None,
    wf_version_id: int | None,
    serialized_results: dict[str, Any],
    diagnostics_serialized: dict[str, Any],
    node_statuses: dict[str, str],
    final_status: str,
    error_msg: str | None,
    integrity_hash: str | None,
    model_ids: list[str] | None,
    saved_artifacts: list[dict[str, Any]] | None = None,
    params_snapshot: dict[str, Any] | None = None,
    input_ports: list[dict[str, Any]] | None = None,
    run_kind: str | None = None,
    applied_artifact_uids: list[str] | None = None,
    source_metadata: dict[str, Any] | None = None,
    idempotency_key: str | None = None,
    reservation_id: int | None = None,
) -> int | None:
    """Persist an auto-saved ``ExecutionRun`` so results survive page refresh.

    Two modes:

    * ``reservation_id is None`` — INSERT a fresh row (legacy behaviour).
      Used when no Idempotency-Key was supplied.
    * ``reservation_id is not None`` — UPDATE the existing reservation row
      that was claimed earlier via :func:`_reserve_run`. Atomic single-
      flight: the unique partial index on the key prevented another caller
      from inserting a duplicate, and this UPDATE finalizes that row in
      place so a follower waiting on ``find_idempotent_run`` sees the
      terminal result.

    Either mode emits the same audit event and returns the row id.
    """
    try:
        # Dedup model_ids while preserving order — a single workflow run may
        # save the same artifact_uid twice (e.g. the same model registered
        # from two ports) which would otherwise inflate audit counts and
        # source_run_id rebinding work below.
        deduped_model_ids = list(dict.fromkeys(model_ids or []))
        derived_name = _derive_run_display_name(workflow_name, integrity_hash, saved_artifacts)
        # Defensive normalization: the DAG executor's ``status.value`` can be
        # ``"idle"`` when a workflow has nodes that weren't reachable from
        # the actually-connected subgraph (Data Source → Scale Center, with
        # the rest of a template still on the canvas as "pending"). The
        # CHECK constraint ``ck_execution_run_status`` doesn't accept
        # ``"idle"``, so an otherwise-successful partial run would 500
        # with an IntegrityError. Treat anything outside the allowlist as
        # ``"partial"`` so the row persists and the user sees what ran.
        if final_status not in ExecutionRun.VALID_STATUSES:
            final_status = "partial"
        run_data = dict(
            project_id=project_id,
            workflow_id=workflow_id,
            workflow_version_id=wf_version_id,
            user_id=user_id,
            name=derived_name,
            status=final_status,
            params_snapshot=params_snapshot or {},
            results_summary=_sanitize_json(serialized_results),
            diagnostics=_sanitize_json(diagnostics_serialized),
            node_statuses=node_statuses,
            error=error_msg,
            integrity_hash=integrity_hash,
            executed_at=datetime.utcnow(),
            source_type="auto",
            source_metadata=source_metadata or None,
            model_ids=deduped_model_ids,
            run_kind=run_kind or ("training" if deduped_model_ids else "data"),
            applied_artifact_uids=applied_artifact_uids or [],
            idempotency_key=idempotency_key,
        )

        if reservation_id is not None:
            # Finalize-in-place: load the reservation row and overwrite its
            # mutable fields with the terminal values. Keep id/created_at;
            # everything else comes from run_data.
            run_row = (
                await session.execute(select(ExecutionRun).where(ExecutionRun.id == reservation_id))
            ).scalar_one_or_none()
            if run_row is None:
                # The reservation row vanished — fall back to an insert so
                # the run still lands and the user sees results.
                logger.warning("Reservation row id=%s missing; falling back to insert", reservation_id)
                run_row = ExecutionRun(**run_data)
                session.add(run_row)
            else:
                for k, v in run_data.items():
                    setattr(run_row, k, v)
        else:
            run_row = ExecutionRun(**run_data)
            session.add(run_row)

        await session.flush()

        if deduped_model_ids:
            from spectra_sherpa.app.models.model_artifact import ModelArtifact

            artifact_query = select(ModelArtifact).where(
                ModelArtifact.user_id == user_id,
                ModelArtifact.artifact_uid.in_(deduped_model_ids),
            )
            if project_id is not None:
                artifact_query = artifact_query.where(ModelArtifact.project_id == project_id)
            artifact_rows = (await session.execute(artifact_query)).scalars()
            for artifact in artifact_rows:
                artifact.source_run_id = run_row.id

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
            audit_emitter.emit(
                session=session,
                action=_run_action_from_status(final_status),
                target_type="ExecutionRun",
                target_id=run_row.id,
                after={
                    "status": final_status,
                    "workflow_id": workflow_id,
                    "project_id": project_id,
                    "workflow_version_id": wf_version_id,
                    "error": error_msg,
                    "model_artifact_count": len(deduped_model_ids),
                },
                context={
                    "reproducibility_record": _build_run_reproducibility_record(
                        run_data,
                        deduped_model_ids,
                        input_ports=input_ports,
                    )
                },
            )

        run_id = run_row.id
        await session.commit()
        return run_id
    except Exception:
        logger.warning("Failed to auto-persist execution run", exc_info=True)
        try:
            await session.rollback()
        except Exception:
            pass
        return None


# ---------------------------------------------------------------------------
# Idempotency-Key replay
# ---------------------------------------------------------------------------

# Allowed character set for an Idempotency-Key header value. UUIDs (with or
# without dashes), opaque base64url tokens, and short alphanumeric keys all
# fit. Stricter than RFC-7240 to keep the column small + the index tight.
_IDEMPOTENCY_KEY_PATTERN = re.compile(r"^[A-Za-z0-9_\-]{8,64}$")

# How far back to replay an existing run when matching an Idempotency-Key.
# Keys remain permanently reserved by the DB unique index. Rows outside this
# window are not replayed, but a client that reuses the same key receives a
# clear 409 rather than an ambiguous reservation race.
IDEMPOTENCY_REPLAY_WINDOW_SEC = 3600


def validate_idempotency_key(raw: str | None) -> str | None:
    """Normalize + validate an ``Idempotency-Key`` header value.

    Returns the stripped key, ``None`` if no header was supplied, or
    raises ``HTTPException(400)`` if the value violates the format rules.
    Keeping the rules tight at the edge means downstream code can treat
    the key as a safe DB lookup token.
    """
    if raw is None:
        return None
    stripped = raw.strip()
    if not stripped:
        return None
    if not _IDEMPOTENCY_KEY_PATTERN.fullmatch(stripped):
        raise HTTPException(
            status_code=400,
            detail="Idempotency-Key must be 8-64 chars from [A-Za-z0-9_-]",
        )
    return stripped


async def find_idempotent_run(
    session: AsyncSession,
    *,
    user_id: int,
    workflow_id: int,
    idempotency_key: str,
) -> ExecutionRun | None:
    """Look up a recent ExecutionRun matching ``(user, workflow, key)``.

    Returns the row regardless of status — the route is responsible for
    distinguishing a terminal row (replay-eligible; see
    :data:`TERMINAL_RUN_STATUSES`) from a still-running reservation row
    (in-flight; should respond 409). Returns the row regardless of
    ``integrity_hash`` too — the route compares against the current
    workflow's hash and returns 409 on mismatch (per REM-5).

    Bounded by :data:`IDEMPOTENCY_REPLAY_WINDOW_SEC` so an old key cannot
    indefinitely resurrect a stale response. Returns the most recent
    matching row (``executed_at DESC``) or ``None``.
    """
    cutoff = datetime.utcnow() - timedelta(seconds=IDEMPOTENCY_REPLAY_WINDOW_SEC)
    query = (
        select(ExecutionRun)
        .where(
            ExecutionRun.user_id == user_id,
            ExecutionRun.workflow_id == workflow_id,
            ExecutionRun.idempotency_key == idempotency_key,
            ExecutionRun.executed_at >= cutoff,
        )
        .order_by(ExecutionRun.executed_at.desc())
        .limit(1)
    )
    return (await session.execute(query)).scalars().first()


async def find_any_idempotent_run(
    session: AsyncSession,
    *,
    user_id: int,
    workflow_id: int,
    idempotency_key: str,
) -> ExecutionRun | None:
    """Look up any ExecutionRun matching ``(user, workflow, key)``.

    Used after a unique-index conflict to distinguish an expired-key reuse
    from a true visibility/race problem.
    """
    query = (
        select(ExecutionRun)
        .where(
            ExecutionRun.user_id == user_id,
            ExecutionRun.workflow_id == workflow_id,
            ExecutionRun.idempotency_key == idempotency_key,
        )
        .order_by(ExecutionRun.executed_at.desc())
        .limit(1)
    )
    return (await session.execute(query)).scalars().first()


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
