"""HTTP parity tests for the authoritative saved-workflow preflight."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from httpx import AsyncClient

import spectra_sherpa.app.services.dag.nodes.modeling  # noqa: F401


@pytest.mark.anyio
async def test_invalid_saved_workflow_is_rejected_by_preflight_and_run(auth_client: AsyncClient) -> None:
    """Run must not pass a graph that the visible preflight rejects.

    A PLS training node needs inputs, but this deliberately saved graph has
    none.  The test protects the admission order: no worker, audit-start event,
    or execution persistence may precede the composed preflight rejection.
    """

    created = await auth_client.post(
        "/api/v1/workflows",
        json={
            "name": "M4 preflight structural rejection",
            "nodes": [
                {
                    "node_id": "pls",
                    "node_type": "model.fitted_pls",
                    "parameters": {"n_components": 2},
                }
            ],
        },
    )
    assert created.status_code == 201, created.text
    workflow_id = created.json()["id"]

    validation = await auth_client.post(f"/api/v1/workflows/{workflow_id}/preflight")
    assert validation.status_code == 200, validation.text
    body = validation.json()
    assert body["workflow_id"] == workflow_id
    assert body["is_valid"] is False
    assert any(issue["code"] == "structural_validation" for issue in body["issues"])

    execution = await auth_client.post(f"/api/v1/workflows/{workflow_id}/execute", json={})
    assert execution.status_code == 422, execution.text
    assert execution.json()["detail"]["code"] == "workflow_preflight_failed"
    assert execution.json()["detail"]["issues"]


@pytest.mark.anyio
async def test_partial_route_scopes_admission_and_executor_but_full_run_stays_strict(auth_client, monkeypatch):
    from spectra_sherpa.app.api.v1.routes.workflows import execute as route

    created = await auth_client.post(
        "/api/v1/workflows",
        json={
            "name": "Partial inspection with unfinished evaluation",
            "nodes": [
                {"node_id": "source", "node_type": "data.file_load", "parameters": {"experiment_id": 1, "file_id": 1}},
                {"node_id": "table", "node_type": "output.data_table", "parameters": {}},
                {"node_id": "eval", "node_type": "diagnostics.labeled_regression_evaluator", "parameters": {}},
            ],
            "edges": [
                {"from_node_id": "source", "to_node_id": "table", "from_output": "default", "to_input": "default"}
            ],
        },
    )
    assert created.status_code == 201, created.text
    workflow_id = created.json()["id"]
    access = AsyncMock(return_value={})
    monkeypatch.setattr(route, "validate_workflow_execution_access", access)
    executed = []

    async def inspect_scope(self, node_id, **kwargs):
        executed.append((node_id, set(self.nodes)))
        return {}

    monkeypatch.setattr(route.DAGExecutor, "execute_node", inspect_scope)
    partial = await auth_client.post(f"/api/v1/workflows/{workflow_id}/execute", json={"node_id": "table"})
    assert partial.status_code == 200, partial.text
    assert executed == [("table", {"source", "table"})]
    assert {node.node_id for node in access.call_args.args[0]} == {"source", "table"}
    full = await auth_client.post(f"/api/v1/workflows/{workflow_id}/execute", json={})
    assert full.status_code == 422, full.text
    assert any(issue["node_id"] == "eval" for issue in full.json()["detail"]["issues"])
