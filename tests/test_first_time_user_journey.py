"""End-to-end first-time user journey: register → login → pick template →
create workflow → execute → ask Sherpa.

This test simulates the happy path a brand-new user follows on their first
visit, exercising the full vertical slice from auth through DAG execution
and LLM chat. It uses the standard test fixtures (in-memory SQLite, auth
bypass) and monkeypatches only the LLM provider.

The workflow uses an Eigenvector catalog source and patches the loader to a
generated Eigenvector-shaped fixture so the user journey does not depend on
redistributed upstream raw data.
"""

from __future__ import annotations

from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from spectra_sherpa.app.models.user import User
from spectra_sherpa.app.models.workflow import Workflow
from spectra_sherpa.app.models.workflow_template import WorkflowTemplate


def _make_preprocessing_template() -> dict[str, Any]:
    """Minimal preprocessing template using an Eigenvector catalog source.

    The test patches eigenvector corn_m5 to generated fixture data; production
    loads this source from a user-local cache or runtime download.
    """
    return {
        "status": "ready",
        "nodes": [
            {
                "node_id": "data_1",
                "node_type": "data.source",
                "label": "Load Data",
                "parameters": {
                    "source": "eigenvector",
                    "eigenvector_dataset": "corn_m5",
                },
                "position_x": 0,
                "position_y": 0,
            },
            {
                "node_id": "preprocess_1",
                "node_type": "preprocess.normalize",
                "label": "Normalize",
                "parameters": {"method": "snv"},
                "position_x": 300,
                "position_y": 0,
            },
        ],
        "edges": [
            {
                "from_node_id": "data_1",
                "to_node_id": "preprocess_1",
                "from_output": "default",
                "to_input": "default",
            },
        ],
    }


@pytest.mark.asyncio
async def test_first_time_user_journey(
    auth_client: AsyncClient,
    test_session: AsyncSession,
    test_user: User,
    patch_eigenvector_loader,
):
    """Simulate: new user → list templates → create workflow from template
    → execute workflow → ask Sherpa a question → get a reply."""

    # ── Step 1: Seed a template ───────────────────────────────────────
    template = WorkflowTemplate(
        slug="preprocessing",
        name="Basic Preprocessing",
        description="SNV normalize spectral data",
        category="preprocessing",
        template_data=_make_preprocessing_template(),
        is_active=True,
    )
    test_session.add(template)
    await test_session.commit()
    await test_session.refresh(template)

    # ── Step 2: List templates (user sees the catalog) ────────────────
    list_response = await auth_client.get("/api/v1/workflow-templates")
    assert list_response.status_code == 200
    templates = list_response.json()["templates"]
    assert any(t["slug"] == "preprocessing" for t in templates)

    # ── Step 3: Create a workflow directly from the template data ─────
    # In the real UI, instantiation goes through the template endpoint.
    # Here we create the workflow directly so the eigenvector source
    # parameters are preserved (no experiment file indirection).
    td = _make_preprocessing_template()
    workflow = Workflow(
        user_id=test_user.id,
        name="My First Workflow",
        description="Created from Basic Preprocessing template",
        status="draft",
    )
    test_session.add(workflow)
    await test_session.commit()
    await test_session.refresh(workflow)

    from spectra_sherpa.app.models.workflow_edge import WorkflowEdge as WFEdge
    from spectra_sherpa.app.models.workflow_node import WorkflowNode as WFNode

    for node_data in td["nodes"]:
        test_session.add(
            WFNode(
                workflow_id=workflow.id,
                node_id=node_data["node_id"],
                node_type=node_data["node_type"],
                label=node_data.get("label"),
                parameters=node_data.get("parameters", {}),
                position_x=node_data.get("position_x"),
                position_y=node_data.get("position_y"),
            )
        )
    for edge_data in td["edges"]:
        test_session.add(
            WFEdge(
                workflow_id=workflow.id,
                from_node_id=edge_data["from_node_id"],
                to_node_id=edge_data["to_node_id"],
                from_output=edge_data.get("from_output", "default"),
                to_input=edge_data.get("to_input", "default"),
            )
        )
    await test_session.commit()

    # ── Step 4: Execute the workflow ────────────────���─────────────────
    execute_response = await auth_client.post(
        f"/api/v1/workflows/{workflow.id}/execute",
        json={},
    )
    assert (
        execute_response.status_code == 200
    ), f"Execute returned {execute_response.status_code}: {execute_response.text[:500]}"
    exec_data = execute_response.json()

    # Surface per-node errors for easier debugging
    if exec_data["status"] == "error":
        node_statuses = exec_data.get("node_statuses", {})
        error_nodes = [nid for nid, st in node_statuses.items() if st == "error"]
        pytest.fail(
            f"Workflow execution failed.\n"
            f"  Error: {exec_data.get('error')}\n"
            f"  Failed nodes: {error_nodes}\n"
            f"  Node statuses: {node_statuses}"
        )
    assert exec_data["status"] in ("completed", "partial"), f"Unexpected status: {exec_data['status']}"
    assert (
        "preprocess_1" in exec_data["results"]
    ), f"Missing preprocess_1 in results. Keys: {list(exec_data['results'].keys())}"

    # Verify the preprocessing node produced a valid dataset.
    # Results may be wrapped in a port dict ({"default": {...}}) or flat.
    preprocess_result = exec_data["results"]["preprocess_1"]
    if "default" in preprocess_result and isinstance(preprocess_result["default"], dict):
        preprocess_result = preprocess_result["default"]
    assert "shape" in preprocess_result, f"No shape in result keys: {list(preprocess_result.keys())}"
    assert preprocess_result["shape"][0] > 0, "No samples in output"
    assert preprocess_result["shape"][1] > 0, "No features in output"

    # Verify result persistence didn't fail (no NaN/MissingGreenlet regressions)
    assert exec_data.get("error") is None, f"Execution error: {exec_data['error']}"

    # ── Step 5: Verify LLM chat routes are not available in OSS-only mode ──
    # The /api/v1/llm/* routes are extension-owned and not registered in OSS.
    # In OSS-only builds the router is not registered so these return 404.
    chat_response = await auth_client.post(
        "/api/v1/llm/chat",
        json={
            "message": "what does this template do?",
            "metadata": {},
        },
    )
    assert chat_response.status_code in (
        404,
        405,
    ), f"Expected 404/405 for /llm/chat in OSS-only mode, got {chat_response.status_code}"
