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

logger = logging.getLogger(__name__)


def _sanitize_json(obj: Any) -> Any:
    """Replace NaN/Inf floats with None so PostgreSQL JSON accepts the payload."""
    if isinstance(obj, float) and (math.isnan(obj) or math.isinf(obj)):
        return None
    if isinstance(obj, dict):
        return {k: _sanitize_json(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_sanitize_json(v) for v in obj]
    return obj


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
        else:
            session.add(ExecutionRun(**run_data))

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
