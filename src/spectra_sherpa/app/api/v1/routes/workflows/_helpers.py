"""
Shared helpers for workflow route sub-modules.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from spectra_sherpa.app.models.execution_run import ExecutionRun
from spectra_sherpa.app.models.workflow import Workflow

logger = logging.getLogger(__name__)


async def _auto_persist_run(
    session: AsyncSession,
    *,
    workflow_id: int,
    user_id: int,
    workflow: Workflow,
    wf_version_id: int | None,
    serialized_results: dict[str, Any],
    diagnostics_serialized: dict[str, Any],
    node_statuses: dict[str, str],
    final_status: str,
    error_msg: str | None,
    integrity_hash: str | None,
    model_ids: list[str] | None,
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
            params_snapshot={n.node_id: n.parameters for n in workflow.nodes if n.parameters},
            results_summary=serialized_results,
            diagnostics=diagnostics_serialized,
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
    request_id = uuid4().hex[:8]
    logger.error(
        "Workflow execution completed but results could not be persisted [req %s]",
        request_id,
    )
    raise HTTPException(
        status_code=500,
        detail=("Workflow execution completed but results could not be saved. " f"Reference request ID: {request_id}"),
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
