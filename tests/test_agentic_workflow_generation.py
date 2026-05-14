"""E2E tests for OSS Sherpa Advisor agentic workflow generation.

Covers POST /workflows/{parent}/ai-fork creating a PCA workflow from a
prompt and the OSS-side validation rules.

The WS-handler interception test that lived here previously was moved to
the server package because it depends on spectrasherpa_server.ws_handlers
internals; keeping it here would leak the OSS / server boundary into the
public mirror.

Run:
    direnv exec . python -m pytest tests/test_agentic_workflow_generation.py -v --no-cov
"""

from __future__ import annotations

import uuid
from unittest.mock import MagicMock, patch

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


# Test 5 (propose_workflow WS interception) was moved to the server package
# because it directly imports spectrasherpa_server.ws_handlers and patches
# its private symbols. See:
#   packages/spectra-server/tests/test_agentic_workflow_propose_interception.py
