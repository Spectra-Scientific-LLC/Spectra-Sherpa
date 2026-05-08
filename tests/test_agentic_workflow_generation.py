"""E2E tests for Sherpa Advisor agentic workflow generation.

Covers the full round-trip:
  1. POST /workflows/{parent}/ai-fork creates a PCA workflow from a prompt
  2. The propose_workflow WS interception path (via mocked LLM events)

Run:
    direnv exec . python -m pytest tests/test_agentic_workflow_generation.py -v --no-cov
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from spectra_sherpa.app.api.v1.routes.workflows.crud import _layout_dag_spec_nodes
from spectra_sherpa.app.core.constants import AI_PURPLE
from spectra_sherpa.app.models.advisor_channel import AdvisorChannel
from spectra_sherpa.app.models.workflow import Workflow
from spectra_sherpa.app.models.workflow_node import WorkflowNode
from spectra_sherpa.app.schemas.workflows import WorkflowDagSpecEdge, WorkflowDagSpecNode
from spectra_sherpa.app.services.tools.builtin.workflow import validate_workflow

# Patch target: get_sherpa_advisor lives in the registry and is lazily imported
# by both crud.py and ws_handlers.py inside function bodies. Patching at the
# source module is the only reliable approach.
_ADVISOR_REGISTRY_PATH = "spectra_sherpa.app.contracts.ai_provider_registry.get_sherpa_advisor"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _create_project(auth_client: AsyncClient) -> int:
    resp = await auth_client.post(
        "/api/v1/projects",
        json={"name": "Agentic Test Project", "description": None},
    )
    assert resp.status_code == 201
    return resp.json()["id"]


async def _create_parent_workflow(auth_client: AsyncClient, project_id: int) -> dict:
    """Workflow with a sklearn wine data source (auto-infers ProjectDataSource)."""
    resp = await auth_client.post(
        "/api/v1/workflows",
        json={
            "name": "Parent Workflow",
            "description": "",
            "status": "draft",
            "project_id": project_id,
            "nodes": [
                {
                    "node_id": "src_1",
                    "node_type": "data.source",
                    "label": "Wine Data",
                    "parameters": {"source": "sklearn", "sklearn_dataset": "wine"},
                    "position_x": 0,
                    "position_y": 0,
                }
            ],
            "edges": [],
        },
    )
    assert resp.status_code == 201
    return resp.json()


_PCA_DAG_SPEC = {
    "nodes": [
        {
            "id": "src_1",
            "type": "data.source",
            "parameters": {"source": "sklearn", "sklearn_dataset": "wine"},
        },
        {
            "id": "pca_1",
            "type": "model.pca",
            "parameters": {"n_components": 3},
        },
    ],
    "edges": [
        {
            "source": "src_1",
            "target": "pca_1",
            "from_output": "default",
            "to_input": "default",
        }
    ],
}


_PLSDA_HOLDOUT_NODES = [
    {
        "id": "data_1",
        "type": "data.source",
        "parameters": {"source": "sklearn", "sklearn_dataset": "iris"},
    },
    {
        "id": "partition_1",
        "type": "selection.sample_partition",
        "parameters": {"method": "stratified", "test_size": 0.25},
    },
    {
        "id": "preprocess_train",
        "type": "preprocess.scale",
        "parameters": {"method": "autoscale"},
    },
    {
        "id": "preprocess_test",
        "type": "preprocess.scale",
        "parameters": {"method": "autoscale"},
    },
    {
        "id": "model_1",
        "type": "classification.plsda",
        "parameters": {"n_components": 3},
    },
    {"id": "predict_1", "type": "classification.predict", "parameters": {}},
    {
        "id": "eval_1",
        "type": "diagnostics.holdout_evaluation",
        "parameters": {"task_type": "classification"},
    },
]

_PLSDA_HOLDOUT_EDGES = [
    {"source": "data_1", "target": "partition_1", "to_input": "X"},
    {
        "source": "partition_1",
        "target": "preprocess_train",
        "from_output": "X_train",
        "to_input": "default",
    },
    {
        "source": "partition_1",
        "target": "preprocess_test",
        "from_output": "X_test",
        "to_input": "default",
    },
    {
        "source": "partition_1",
        "target": "preprocess_test",
        "from_output": "X_train",
        "to_input": "reference",
    },
    {"source": "preprocess_train", "target": "model_1", "to_input": "X"},
    {"source": "preprocess_test", "target": "predict_1", "to_input": "X_new"},
    {
        "source": "model_1",
        "target": "predict_1",
        "from_output": "model",
        "to_input": "model",
    },
    {
        "source": "predict_1",
        "target": "eval_1",
        "from_output": "y_pred",
        "to_input": "y_pred",
    },
    {
        "source": "partition_1",
        "target": "eval_1",
        "from_output": "y_test",
        "to_input": "y_true",
    },
]


def _mock_available_provider():
    """Return a mock satisfying the `is_available` property check."""
    provider = MagicMock()
    type(provider).is_available = property(lambda self: True)
    provider.has_feature.return_value = True
    return provider


def _mock_provider_without_agentic_tools():
    provider = _mock_available_provider()
    provider.has_feature.return_value = False
    return provider


def test_ai_fork_layout_matches_vertical_classification_template_lanes() -> None:
    """Fallback positions should follow the train/test template layout convention."""
    nodes = [
        WorkflowDagSpecNode(id="data_1", type="data.source"),
        WorkflowDagSpecNode(id="partition_1", type="selection.sample_partition"),
        WorkflowDagSpecNode(id="preprocess_train", type="preprocess.scale"),
        WorkflowDagSpecNode(id="preprocess_test", type="preprocess.scale"),
        WorkflowDagSpecNode(id="model_1", type="classification.plsda"),
        WorkflowDagSpecNode(id="predict_1", type="classification.predict"),
        WorkflowDagSpecNode(id="eval_1", type="diagnostics.holdout_evaluation"),
        WorkflowDagSpecNode(id="table_1", type="output.data_table"),
        WorkflowDagSpecNode(id="viz_1", type="output.plot"),
    ]
    edges = [
        WorkflowDagSpecEdge(source="data_1", target="partition_1", to_input="X"),
        WorkflowDagSpecEdge(
            source="partition_1",
            target="preprocess_train",
            from_output="X_train",
            to_input="default",
        ),
        WorkflowDagSpecEdge(
            source="partition_1",
            target="preprocess_test",
            from_output="X_test",
            to_input="default",
        ),
        WorkflowDagSpecEdge(
            source="partition_1",
            target="preprocess_test",
            from_output="X_train",
            to_input="reference",
        ),
        WorkflowDagSpecEdge(source="preprocess_train", target="model_1", to_input="X"),
        WorkflowDagSpecEdge(source="preprocess_test", target="predict_1", to_input="X_new"),
        WorkflowDagSpecEdge(
            source="model_1",
            target="predict_1",
            from_output="model",
            to_input="model",
        ),
        WorkflowDagSpecEdge(
            source="predict_1",
            target="eval_1",
            from_output="y_pred",
            to_input="y_pred",
        ),
        WorkflowDagSpecEdge(
            source="partition_1",
            target="eval_1",
            from_output="y_test",
            to_input="y_true",
        ),
        WorkflowDagSpecEdge(
            source="eval_1",
            target="table_1",
            from_output="metrics",
        ),
        WorkflowDagSpecEdge(
            source="eval_1",
            target="viz_1",
            from_output="visualization",
        ),
    ]

    assert _layout_dag_spec_nodes(nodes, edges) == {
        "data_1": (175.0, 50.0),
        "partition_1": (175.0, 250.0),
        "preprocess_train": (175.0, 450.0),
        "preprocess_test": (500.0, 450.0),
        "model_1": (175.0, 650.0),
        "predict_1": (500.0, 650.0),
        "eval_1": (500.0, 850.0),
        "table_1": (175.0, 1050.0),
        "viz_1": (500.0, 1050.0),
    }


def test_validate_workflow_accepts_template_style_plsda_holdout_topology() -> None:
    result = validate_workflow(_PLSDA_HOLDOUT_NODES, _PLSDA_HOLDOUT_EDGES)

    assert result["valid"] is True
    assert [issue for issue in result["issues"] if issue["severity"] == "error"] == []


def test_validate_workflow_rejects_collapsed_classification_test_branch() -> None:
    collapsed_nodes = [node for node in _PLSDA_HOLDOUT_NODES if node["id"] != "preprocess_test"]
    collapsed_edges = [
        edge
        for edge in _PLSDA_HOLDOUT_EDGES
        if edge.get("target") != "preprocess_test" and edge.get("target") != "predict_1"
    ]
    collapsed_edges.extend(
        [
            {"source": "preprocess_train", "target": "predict_1", "to_input": "X_new"},
            {
                "source": "model_1",
                "target": "predict_1",
                "from_output": "model",
                "to_input": "model",
            },
        ]
    )

    result = validate_workflow(collapsed_nodes, collapsed_edges)
    codes = {issue.get("code") for issue in result["issues"]}

    assert result["valid"] is False
    assert "classification_predict_must_use_x_test" in codes


def test_validate_workflow_requires_training_reference_for_scaled_test_branch() -> None:
    missing_reference_edges = [
        edge
        for edge in _PLSDA_HOLDOUT_EDGES
        if not (
            edge.get("target") == "preprocess_test"
            and edge.get("from_output") == "X_train"
            and edge.get("to_input") == "reference"
        )
    ]

    result = validate_workflow(_PLSDA_HOLDOUT_NODES, missing_reference_edges)
    codes = {issue.get("code") for issue in result["issues"]}

    assert result["valid"] is False
    assert "classification_test_scale_requires_train_reference" in codes


def test_validate_workflow_requires_holdout_eval_to_use_y_test() -> None:
    wrong_eval_edges = [
        edge
        for edge in _PLSDA_HOLDOUT_EDGES
        if not (edge.get("target") == "eval_1" and edge.get("to_input") == "y_true")
    ]
    wrong_eval_edges.append(
        {
            "source": "partition_1",
            "target": "eval_1",
            "from_output": "y_train",
            "to_input": "y_true",
        }
    )

    result = validate_workflow(_PLSDA_HOLDOUT_NODES, wrong_eval_edges)
    codes = {issue.get("code") for issue in result["issues"]}

    assert result["valid"] is False
    assert "classification_eval_must_use_y_test" in codes


# ---------------------------------------------------------------------------
# Test 1 — HTTP endpoint: ai-fork creates a PCA workflow
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ai_fork_creates_pca_workflow(
    auth_client: AsyncClient,
    test_session: AsyncSession,
) -> None:
    """POST /workflows/{id}/ai-fork with a PCA dag_spec creates the forked sheet.

    Verifies:
    - HTTP 201 with new_workflow_id + new_channel_id
    - The forked workflow has a PCA node in the database
    - tab_color = AI_PURPLE and color_source = "ai"
    - An AdvisorChannel row is created with the supplied conversation_id
    - created_from_workflow_id points to the parent
    """
    project_id = await _create_project(auth_client)
    parent = await _create_parent_workflow(auth_client, project_id)
    parent_id = parent["id"]
    new_conversation_id = str(uuid.uuid4())

    with patch(_ADVISOR_REGISTRY_PATH, return_value=_mock_available_provider()):
        resp = await auth_client.post(
            f"/api/v1/workflows/{parent_id}/ai-fork",
            json={
                "dag_spec": _PCA_DAG_SPEC,
                "new_conversation_id": new_conversation_id,
                "suggested_name": "Sherpa: PCA on Wine",
            },
        )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    new_workflow_id = body["new_workflow_id"]
    new_channel_id = body["new_channel_id"]
    assert isinstance(new_workflow_id, int) and new_workflow_id > 0
    assert isinstance(new_channel_id, int) and new_channel_id > 0

    # Verify workflow record
    wf = await test_session.get(Workflow, new_workflow_id)
    assert wf is not None
    assert wf.name == "Sherpa: PCA on Wine"
    assert wf.tab_color == AI_PURPLE
    assert wf.color_source == "ai"
    assert wf.created_from_workflow_id == parent_id

    # Verify PCA node exists
    forked_nodes = (
        (await test_session.execute(select(WorkflowNode).where(WorkflowNode.workflow_id == new_workflow_id)))
        .scalars()
        .all()
    )
    forked_positions = {node.node_id: (node.position_x, node.position_y) for node in forked_nodes}
    assert len(set(forked_positions.values())) == len(forked_positions)
    assert forked_positions["src_1"] == (175.0, 50.0)
    assert forked_positions["pca_1"][0] == forked_positions["src_1"][0]
    assert forked_positions["pca_1"][1] > forked_positions["src_1"][1]

    pca_node = (
        await test_session.execute(
            select(WorkflowNode).where(
                WorkflowNode.workflow_id == new_workflow_id,
                WorkflowNode.node_type == "model.pca",
            )
        )
    ).scalar_one_or_none()
    assert pca_node is not None, "PCA node was not created in the forked workflow"
    assert pca_node.parameters.get("n_components") == 3

    # Verify advisor channel
    channel = (
        await test_session.execute(select(AdvisorChannel).where(AdvisorChannel.id == new_channel_id))
    ).scalar_one_or_none()
    assert channel is not None
    assert channel.conversation_id == new_conversation_id
    assert channel.workflow_id == new_workflow_id
    assert channel.channel_type == "sheet"
    assert channel.color == AI_PURPLE


@pytest.mark.asyncio
async def test_ai_fork_repairs_stacked_node_positions(
    auth_client: AsyncClient,
    test_session: AsyncSession,
) -> None:
    """AI-generated sheets must not preserve degenerate stacked coordinates."""
    project_id = await _create_project(auth_client)
    parent = await _create_parent_workflow(auth_client, project_id)
    stacked_dag_spec = {
        "nodes": [
            {**_PCA_DAG_SPEC["nodes"][0], "position": {"x": 0, "y": 0}},
            {**_PCA_DAG_SPEC["nodes"][1], "position": {"x": 0, "y": 0}},
        ],
        "edges": _PCA_DAG_SPEC["edges"],
    }

    with patch(_ADVISOR_REGISTRY_PATH, return_value=_mock_available_provider()):
        resp = await auth_client.post(
            f"/api/v1/workflows/{parent['id']}/ai-fork",
            json={
                "dag_spec": stacked_dag_spec,
                "new_conversation_id": str(uuid.uuid4()),
                "suggested_name": "Sherpa: Stacked Repair",
            },
        )

    assert resp.status_code == 200, resp.text
    new_workflow_id = resp.json()["new_workflow_id"]
    forked_nodes = (
        (await test_session.execute(select(WorkflowNode).where(WorkflowNode.workflow_id == new_workflow_id)))
        .scalars()
        .all()
    )
    forked_positions = {node.node_id: (node.position_x, node.position_y) for node in forked_nodes}
    assert len(set(forked_positions.values())) == len(forked_positions)
    assert forked_positions["pca_1"][0] == forked_positions["src_1"][0]
    assert forked_positions["pca_1"][1] > forked_positions["src_1"][1]


# ---------------------------------------------------------------------------
# Test 2 — Idempotency: second ai-fork with same conversation_id returns existing
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ai_fork_idempotent_on_same_conversation_id(
    auth_client: AsyncClient,
) -> None:
    """A second call with the same new_conversation_id returns the existing sheet."""
    project_id = await _create_project(auth_client)
    parent = await _create_parent_workflow(auth_client, project_id)
    conv_id = str(uuid.uuid4())

    with patch(_ADVISOR_REGISTRY_PATH, return_value=_mock_available_provider()):
        r1 = await auth_client.post(
            f"/api/v1/workflows/{parent['id']}/ai-fork",
            json={"dag_spec": _PCA_DAG_SPEC, "new_conversation_id": conv_id, "suggested_name": "PCA"},
        )
        r2 = await auth_client.post(
            f"/api/v1/workflows/{parent['id']}/ai-fork",
            json={"dag_spec": _PCA_DAG_SPEC, "new_conversation_id": conv_id, "suggested_name": "PCA"},
        )

    assert r1.status_code == 200
    assert r2.status_code == 200
    assert r1.json()["new_workflow_id"] == r2.json()["new_workflow_id"]
    assert r1.json()["new_channel_id"] == r2.json()["new_channel_id"]


# ---------------------------------------------------------------------------
# Test 3 — ai-fork rejected without an AI provider
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ai_fork_requires_advisor(auth_client: AsyncClient) -> None:
    """ai-fork returns 403 when the AI provider is not available (default state)."""
    project_id = await _create_project(auth_client)
    parent = await _create_parent_workflow(auth_client, project_id)

    # No patch → DisabledAIProvider → is_available = False → 403
    resp = await auth_client.post(
        f"/api/v1/workflows/{parent['id']}/ai-fork",
        json={"dag_spec": _PCA_DAG_SPEC, "new_conversation_id": str(uuid.uuid4())},
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_ai_fork_requires_agentic_tools_feature(auth_client: AsyncClient) -> None:
    """ai-fork returns 403 when the provider lacks agentic workflow generation."""
    project_id = await _create_project(auth_client)
    parent = await _create_parent_workflow(auth_client, project_id)

    with patch(_ADVISOR_REGISTRY_PATH, return_value=_mock_provider_without_agentic_tools()):
        resp = await auth_client.post(
            f"/api/v1/workflows/{parent['id']}/ai-fork",
            json={"dag_spec": _PCA_DAG_SPEC, "new_conversation_id": str(uuid.uuid4())},
        )

    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# Test 4 — ai-fork rejected when parent has no data source
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ai_fork_requires_parent_data_source(auth_client: AsyncClient) -> None:
    """ai-fork returns 400 when the parent workflow has no data sources."""
    project_id = await _create_project(auth_client)
    empty_resp = await auth_client.post(
        "/api/v1/workflows",
        json={
            "name": "Empty Workflow",
            "status": "draft",
            "project_id": project_id,
            "nodes": [],
            "edges": [],
        },
    )
    assert empty_resp.status_code == 201
    empty_id = empty_resp.json()["id"]

    with patch(_ADVISOR_REGISTRY_PATH, return_value=_mock_available_provider()):
        resp = await auth_client.post(
            f"/api/v1/workflows/{empty_id}/ai-fork",
            json={"dag_spec": _PCA_DAG_SPEC, "new_conversation_id": str(uuid.uuid4())},
        )

    assert resp.status_code == 400
    assert "data source" in resp.json()["detail"].lower()


# ---------------------------------------------------------------------------
# Test 5 — WS propose_workflow interception end-to-end
#
# Mocks the LLM event stream to emit a propose_workflow tool call, then
# verifies that _fork_conversation_and_workflow is called with the correct
# workflow_id extracted from the dict-shaped workflow_context.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_propose_workflow_interception_calls_fork(test_user) -> None:
    """WS handler intercepts propose_workflow and calls the fork helper.

    This exercises the two bugs that were fixed:
    1. propose_workflow required session/user → always returned success=False
    2. getattr(workflow_context_dict, "workflow_id") → always None

    With both fixes:
    - The tool returns success=True
    - parent_wf_id is correctly read via .get("workflow_id") on the dict
    - _fork_conversation_and_workflow is called with workflow_id=42
    - A SHERPA_WORKFLOW_PROPOSED event is emitted
    """
    ws_handlers_mod = pytest.importorskip(
        "spectrasherpa_server.ws_handlers",
        reason="spectrasherpa_server not installed in this environment",
    )
    from spectra_sherpa.app.ws_events import SHERPA_WORKFLOW_PROPOSED

    dag_spec = {
        "nodes": [
            {"id": "src_1", "type": "data.source", "parameters": {}},
            {"id": "pca_1", "type": "model.pca", "parameters": {"n_components": 3}},
        ],
        "edges": [{"source": "src_1", "target": "pca_1", "from_output": "default", "to_input": "default"}],
    }

    fork_result = {
        "new_conversation_id": str(uuid.uuid4()),
        "new_workflow_id": 999,
        "new_channel_id": 888,
    }
    mock_fork = AsyncMock(return_value=fork_result)

    messages_sent: list[dict] = []

    async def mock_send_or_raise(_ws, msg):
        messages_sent.append(msg)

    async def fake_event_stream():
        yield {"type": "start", "conversation_id": "conv-123"}
        yield {
            "type": "tool_start",
            "tool": "propose_workflow",
            "round": 1,
            "arguments": {
                "dag_spec": dag_spec,
                "suggested_name": "Sherpa: PCA",
                "human_explanation": "PCA is appropriate for this dataset.",
            },
        }
        yield {
            "type": "tool_result",
            "tool": "propose_workflow",
            "round": 1,
            "success": True,
            "summary": '{"status": "intercepted"}',
            "error": None,
            "error_category": None,
        }
        yield {"type": "chunk", "text": "I've generated a PCA workflow."}
        yield {"type": "done", "conversation_id": "conv-123", "tool_calls": []}

    mock_advisor = MagicMock()
    mock_advisor.chat_with_tools = MagicMock(return_value=fake_event_stream())

    payload = {
        "payload": {
            "request_id": str(uuid.uuid4()),
            "message": "Generate a PCA workflow for the wine dataset.",
            "conversation_id": None,
            "project_id": 1,
            "workflow_id": 42,
            "workflow_context": {
                "workflow_id": 42,
                "workflow_name": "Parent Workflow",
                "nodes": [],
                "edges": [],
            },
        }
    }

    with (
        patch.object(ws_handlers_mod, "_fork_conversation_and_workflow", mock_fork),
        patch.object(ws_handlers_mod, "_send_or_raise", mock_send_or_raise),
        patch.object(ws_handlers_mod, "_sherpa_proxy_preamble", AsyncMock(return_value=True)),
        patch(_ADVISOR_REGISTRY_PATH, return_value=mock_advisor),
    ):
        from spectrasherpa_server.ws_handlers import handle_sherpa_chat_with_tools

        fake_user = SimpleNamespace(id=test_user.id)
        mock_ws = MagicMock()
        rate_limiter = MagicMock()
        rate_limiter.check_rate_limit = AsyncMock(return_value=None)

        await handle_sherpa_chat_with_tools(mock_ws, payload, fake_user, rate_limiter)

    # The fork helper must have been called with workflow_id=42 (from dict context)
    mock_fork.assert_awaited_once()
    call_kwargs = mock_fork.call_args.kwargs
    assert call_kwargs["parent_workflow_id"] == 42, (
        f"parent_workflow_id was {call_kwargs.get('parent_workflow_id')!r}, expected 42. "
        "This indicates the dict-context getattr bug is still present."
    )

    # A SHERPA_WORKFLOW_PROPOSED event must have been sent
    proposed_events = [m for m in messages_sent if m.get("type") == SHERPA_WORKFLOW_PROPOSED]
    assert len(proposed_events) == 1, (
        f"Expected 1 SHERPA_WORKFLOW_PROPOSED event, got {len(proposed_events)}. "
        f"All event types seen: {[m.get('type') for m in messages_sent]}"
    )
    assert proposed_events[0]["new_workflow_id"] == 999
    assert proposed_events[0]["new_channel_id"] == 888
    assert proposed_events[0]["suggested_name"] == "Sherpa: PCA"
