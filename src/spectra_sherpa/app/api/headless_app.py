"""
Headless Prediction Server API.

A specialized, ultra-lightweight FastAPI application designed solely for
running predictions against a pre-defined (or frozen) workflow. It lacks
the UI, authentication, and standard exploratory routes of the main app.
"""

from __future__ import annotations

import json
import logging
import os
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import PlainTextResponse, Response
from sqlalchemy.ext.asyncio import AsyncSession

from spectra_sherpa.app.db.session import async_session
from spectra_sherpa.app.services.batch_predict import build_executor_from_workflow, load_workflow_with_graph
from spectra_sherpa.app.services.dag.io_contracts import coerce_to_sherpa

logger = logging.getLogger(__name__)

# Single global executor loaded at startup
_executor = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Load the workflow into memory on startup."""
    global _executor
    workflow_id_str = os.getenv("HEADLESS_WORKFLOW_ID")
    if not workflow_id_str:
        logger.warning("HEADLESS_WORKFLOW_ID not set. API will not function.")
        yield
        return

    workflow_id = int(workflow_id_str)
    # Note: Headless server runs with arbitrary permissions for the specified workflow for now.
    # In a full production env, you'd specify a token or valid user. 
    # For this implementation, we just get the first user or mock one if needed, 
    # but luckily `load_workflow_with_graph` requires a user_id. 
    # Let's read the workflow manually to bypass user check if it's strictly a "deployed" model.
    # Actually, we can just use the standard session to load the workflow directly.
    import sqlalchemy as sa
    from spectra_sherpa.app.models.workflow import Workflow
    from sqlalchemy.orm import selectinload

    async with async_session() as session:
        query = sa.select(Workflow).where(Workflow.id == workflow_id).options(
            selectinload(Workflow.nodes),
            selectinload(Workflow.edges),
        )
        result = await session.execute(query)
        workflow = result.scalar_one_or_none()
        if not workflow:
            raise RuntimeError(f"Workflow {workflow_id} not found in database.")

        logger.info(f"Loading '{workflow.name}' (ID: {workflow_id}) for headless prediction...")
        _executor = build_executor_from_workflow(workflow)

    yield
    # Cleanup on shutdown
    _executor = None


app = FastAPI(
    title="SpectraSherpa Headless Prediction API",
    description="Ultra-lightweight API for running predictions using deploy nodes.",
    version="1.0.0",
    docs_url="/docs",
    redoc_url=None,
    lifespan=lifespan,
)


@app.get("/health")
async def health_check():
    """Check API and model status."""
    return {"status": "ok", "model_loaded": _executor is not None}


@app.post("/predict")
async def predict(request: Request) -> Response:
    """
    Run a prediction.
    
    The request body must be JSON, where keys correspond to the `stream_name`
    of the `deploy.input` nodes in the workflow.
    """
    global _executor
    if not _executor:
        raise HTTPException(status_code=500, detail="Model executor not initialized.")

    # Only accept JSON for now to map to streams
    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON payload")

    # Clone the executor so concurrent requests don't mix state if we enable multithreading later
    import copy
    executor = copy.deepcopy(_executor)

    # Find the deploy entry nodes
    entry_nodes = executor.find_entry_nodes()
    deploy_input_nodes = [n for n in executor.nodes.values() if n.metadata.node_type == "deploy.input"]

    if not deploy_input_nodes:
        raise HTTPException(status_code=500, detail="Workflow does not contain any deploy.input nodes")

    # Inject data into the correct nodes based on stream_name
    for node in deploy_input_nodes:
        stream_name = node.parameters.get("stream_name", "sample")
        if stream_name not in payload:
            raise HTTPException(status_code=400, detail=f"Missing required stream: {stream_name}")

        # Convert raw JSON to SherpaDataset (allow arrays for headless predictions)
        data = payload[stream_name]
        try:
            dataset = coerce_to_sherpa(data, allow_array=True)
            executor.inject_result(node.node_id, dataset)
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Error parsing data for stream '{stream_name}': {e}")

    # Process workflow
    try:
        results = await executor.execute()
    except Exception as e:
        logger.exception("Graph execution failed")
        raise HTTPException(status_code=500, detail=f"Prediction error: {str(e)}")

    # Extract results from deploy.output node(s)
    deploy_output_nodes = [n for n in executor.nodes.values() if n.metadata.node_type == "deploy.output"]
    if not deploy_output_nodes:
        # Fallback to returning all exit node results if no specific deploy.output exists
        exit_nodes = executor.find_exit_nodes()
        out = {k: str(results[k]) for k in exit_nodes if k in results}
        return Response(content=json.dumps(out), media_type="application/json")

    # Aggregate ALL deploy.output nodes (multiple outputs for advanced workflows)
    if len(deploy_output_nodes) == 1:
        # Single output: return formatted result directly
        out_node_id = deploy_output_nodes[0].node_id
        if out_node_id not in results:
            raise HTTPException(status_code=500, detail="Deploy output node did not produce a result")

        fmt_result = results[out_node_id]  # Expected to be a dict from DeployOutputNode.execute()
        fmt_type = fmt_result.get("format", "json")
        content = fmt_result.get("content", "")

        if fmt_type == "json":
            return Response(content=json.dumps(content), media_type="application/json")
        elif fmt_type == "csv":
            return PlainTextResponse(content=content, media_type="text/csv")
        else:
            return PlainTextResponse(content=content, media_type="text/plain")
    else:
        # Multiple outputs: return dict keyed by node ID
        outputs = {}
        for node in deploy_output_nodes:
            out_node_id = node.node_id
            if out_node_id in results:
                fmt_result = results[out_node_id]
                outputs[out_node_id] = {
                    "format": fmt_result.get("format", "json"),
                    "content": fmt_result.get("content", ""),
                }
        return Response(content=json.dumps(outputs), media_type="application/json")
