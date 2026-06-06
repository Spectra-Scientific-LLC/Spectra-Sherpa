"""
Prediction API — flat REST endpoint for external systems.

External consumers (spectrometers, LIMS, process controllers) POST raw
spectral data and get back results without needing to understand the
DAG structure.  The workflow is loaded from DB, entry nodes are injected
with the caller's data, the rest of the DAG executes normally, and only
exit-node results are returned.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

import numpy as np
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from spectra_sherpa.app.api.deps import get_current_user, get_session
from spectra_sherpa.app.core.request_id import get_request_id
from spectra_sherpa.app.lib.scp_compat import HAS_SCP
from spectra_sherpa.app.lib.sherpa_dataset import SherpaDataset, SpectralAxis
from spectra_sherpa.app.models.user import User
from spectra_sherpa.app.models.workflow import Workflow
from spectra_sherpa.app.services.workflow_access import validate_workflow_execution_access

router = APIRouter(prefix="/workflows")
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Request / Response schemas
# ---------------------------------------------------------------------------


class PredictRequest(BaseModel):
    """Payload for the flat prediction endpoint."""

    data: list[list[float]] = Field(
        ...,
        description="Spectral matrix [n_samples × n_features]",
    )
    wavenumbers: list[float] | None = Field(
        None,
        description="Optional X-axis values (wavenumbers / wavelengths). " "Length must match n_features.",
    )


class PredictResponse(BaseModel):
    """Result from a prediction run."""

    results: dict[str, Any] = Field(
        default_factory=dict,
        description="Serialized exit-node results keyed by node ID",
    )
    terminal_node_ids: list[str] = Field(
        default_factory=list,
        description="IDs of exit (terminal) nodes",
    )
    integrity_hash: str | None = Field(
        None,
        description="SHA-256 integrity hash of the workflow definition",
    )
    executed_at: str = Field(
        ...,
        description="ISO-8601 timestamp of execution",
    )


# ---------------------------------------------------------------------------
# Endpoint
# ---------------------------------------------------------------------------


@router.post("/{workflow_id}/predict", response_model=PredictResponse)
async def predict(
    workflow_id: int,
    payload: PredictRequest,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> PredictResponse:
    """
    Flat prediction endpoint — no graph knowledge required.

    1. Load the saved workflow (nodes + edges) from DB.
    2. Build a DAGExecutor with the full pipeline.
    3. Detect entry nodes (data.*) and exit nodes (no outgoing edges).
    4. Convert ``payload.data`` to a SherpaDataset and inject it into every
       entry node.
    5. Execute the rest of the DAG (entry nodes are skipped as cached).
    6. Collect and serialize only exit-node results.

    Errors:
        404 — Workflow not found
        422 — Shape mismatch between data and wavenumbers
        500 — Execution error
    """
    if not HAS_SCP:
        raise HTTPException(
            status_code=500,
            detail="SpectroChemPy is not installed — prediction requires SCP support.",
        )

    # --- 1. Load workflow ------------------------------------------------
    query = (
        select(Workflow)
        .where(Workflow.id == workflow_id)
        .where(Workflow.user_id == current_user.id)
        .options(
            selectinload(Workflow.nodes),
            selectinload(Workflow.edges),
        )
    )
    result = await session.execute(query)
    workflow = result.scalar_one_or_none()

    if workflow is None:
        raise HTTPException(status_code=404, detail="Workflow not found")

    if not workflow.nodes:
        raise HTTPException(status_code=422, detail="Workflow has no nodes")

    await validate_workflow_execution_access(
        workflow.nodes,
        None,
        current_user.id,
        workflow.project_id,
        session,
    )

    # --- 2. Validate payload ---------------------------------------------
    data_array = np.array(payload.data, dtype=np.float64)
    if data_array.ndim == 1:
        data_array = data_array.reshape(1, -1)
    if data_array.ndim != 2:
        raise HTTPException(
            status_code=422,
            detail=f"Expected 2-D data matrix, got shape {data_array.shape}",
        )

    n_features = data_array.shape[1]

    if payload.wavenumbers is not None:
        if len(payload.wavenumbers) != n_features:
            raise HTTPException(
                status_code=422,
                detail=(
                    f"Wavenumber length ({len(payload.wavenumbers)}) does not " f"match feature count ({n_features})"
                ),
            )

    # --- 3. Build SherpaDataset from payload ------------------------------
    feature_axis = None
    if payload.wavenumbers is not None:
        feature_axis = SpectralAxis(values=np.asarray(payload.wavenumbers), title="Wavenumbers")
    dataset = SherpaDataset(X=data_array, feature_axis=feature_axis)

    # --- 4. Build DAGExecutor --------------------------------------------
    from spectra_sherpa.app.services.dag import (
        DAGExecutor,
    )
    from spectra_sherpa.app.services.dag import (
        WorkflowEdge as DAGEdge,
    )
    from spectra_sherpa.app.services.dag import (
        WorkflowNode as DAGNode,
    )

    executor = DAGExecutor()

    for node in workflow.nodes:
        dag_node = DAGNode(
            node_id=node.node_id,
            node_type=node.node_type,
            parameters=node.parameters,
            position={"x": node.position_x, "y": node.position_y} if node.position_x and node.position_y else None,
        )
        executor.add_node(dag_node)

    for edge in workflow.edges:
        dag_edge = DAGEdge(
            from_node=edge.from_node_id,
            to_node=edge.to_node_id,
            from_output=edge.from_output,
            to_input=edge.to_input,
        )
        executor.add_edge(dag_edge)

    # --- 5. Inject data into entry nodes ---------------------------------
    entry_nodes = executor.find_entry_nodes()
    if not entry_nodes:
        raise HTTPException(
            status_code=422,
            detail="Workflow has no entry nodes (data sources) to inject data into",
        )

    for node_id in entry_nodes:
        executor.inject_result(node_id, dataset)

    # --- 6. Execute the DAG ----------------------------------------------
    try:
        results = await executor.execute()
    except Exception:
        # The full request ID is auto-injected into log lines via the
        # formatter (see ``app/core/request_id.py``); we surface a short
        # form to the user for support-ticket correlation. ``or uuid4``
        # is a defensive fallback for paths that bypass the middleware
        # (e.g. unit tests calling this route function directly).
        full_request_id = get_request_id() or uuid4().hex
        short_id = full_request_id[:8]
        logger.exception("Prediction execution failed")
        raise HTTPException(
            status_code=500,
            detail=f"Execution failed. Reference request ID: {short_id}",
        )

    # --- 7. Collect and serialize exit-node results ----------------------
    from spectra_sherpa.app.services.serialization import serialize_result

    exit_nodes = executor.find_exit_nodes()
    serialized: dict[str, Any] = {}

    for node_id in exit_nodes:
        if node_id in results:
            try:
                serialized[node_id] = serialize_result(results[node_id], owner_user_id=current_user.id)
            except Exception as ser_err:
                serialized[node_id] = {
                    "error": f"Serialization failed: {ser_err}",
                    "type": type(results[node_id]).__name__,
                }

    return PredictResponse(
        results=serialized,
        terminal_node_ids=exit_nodes,
        integrity_hash=workflow.integrity_hash,
        executed_at=datetime.now(timezone.utc).isoformat(),
    )
