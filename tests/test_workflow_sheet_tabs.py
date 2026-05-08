from __future__ import annotations

from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from spectra_sherpa.app.models.execution_run import ExecutionRun
from spectra_sherpa.app.models.workflow import Workflow
from spectra_sherpa.app.models.workflow_version import WorkflowVersion


async def _create_project(auth_client: AsyncClient) -> int:
    response = await auth_client.post(
        "/api/v1/projects",
        json={"name": "Sheet Tab Project", "description": None},
    )
    assert response.status_code == 201
    return response.json()["id"]


async def _create_workflow(auth_client: AsyncClient, project_id: int, name: str) -> dict:
    response = await auth_client.post(
        "/api/v1/workflows",
        json={
            "name": name,
            "description": "",
            "status": "draft",
            "project_id": project_id,
            "tab_color": "#3b82f6",
            "nodes": [
                {
                    "node_id": "data_1",
                    "node_type": "data.source",
                    "label": "Data",
                    "parameters": {},
                    "position_x": 10,
                    "position_y": 20,
                }
            ],
            "edges": [],
        },
    )
    assert response.status_code == 201
    return response.json()


async def _create_data_workflow(auth_client: AsyncClient, project_id: int, name: str) -> dict:
    response = await auth_client.post(
        "/api/v1/workflows",
        json={
            "name": name,
            "description": "",
            "status": "draft",
            "project_id": project_id,
            "nodes": [
                {
                    "node_id": "data_1",
                    "node_type": "data.source",
                    "label": "Wine Data",
                    "parameters": {"source": "sklearn", "sklearn_dataset": "wine"},
                    "position_x": 10,
                    "position_y": 20,
                }
            ],
            "edges": [],
        },
    )
    assert response.status_code == 201
    return response.json()


async def test_save_without_version_suppresses_workflow_version(
    auth_client: AsyncClient,
    test_session: AsyncSession,
) -> None:
    project_id = await _create_project(auth_client)
    workflow = await _create_workflow(auth_client, project_id, "PCA")

    response = await auth_client.put(
        f"/api/v1/workflows/{workflow['id']}",
        json={"name": "PCA Renamed", "create_version": False},
    )
    assert response.status_code == 200

    version_count = await test_session.scalar(
        select(func.count(WorkflowVersion.id)).where(WorkflowVersion.workflow_id == workflow["id"])
    )
    assert version_count == 0


async def test_duplicate_workflow_creates_sheet_copy_without_runs_or_versions(
    auth_client: AsyncClient,
    test_session: AsyncSession,
) -> None:
    project_id = await _create_project(auth_client)
    workflow = await _create_workflow(auth_client, project_id, "PCA")

    response = await auth_client.post(f"/api/v1/workflows/{workflow['id']}/duplicate")
    assert response.status_code == 201
    duplicate = response.json()

    assert duplicate["id"] != workflow["id"]
    assert duplicate["name"] == "PCA (copy)"
    assert duplicate["project_id"] == project_id
    assert duplicate["sheet_order"] == 1
    assert duplicate["tab_color"] == "#3b82f6"
    assert len(duplicate["nodes"]) == 1
    assert duplicate["nodes"][0]["node_id"] == "data_1"
    assert duplicate["nodes"][0]["position_x"] == 10

    run_count = await test_session.scalar(
        select(func.count(ExecutionRun.id)).where(ExecutionRun.workflow_id == duplicate["id"])
    )
    version_count = await test_session.scalar(
        select(func.count(WorkflowVersion.id)).where(WorkflowVersion.workflow_id == duplicate["id"])
    )
    assert run_count == 0
    assert version_count == 0


async def test_reorder_sheets_persists_dense_order_and_tolerates_stale_payloads(
    auth_client: AsyncClient,
    test_session: AsyncSession,
) -> None:
    project_id = await _create_project(auth_client)
    first = await _create_workflow(auth_client, project_id, "First")
    second = await _create_workflow(auth_client, project_id, "Second")

    response = await auth_client.put(
        f"/api/v1/workflows/reorder-sheets?project_id={project_id}",
        json={"ordered_ids": [second["id"], first["id"]]},
    )
    assert response.status_code == 200
    assert [item["id"] for item in response.json()] == [second["id"], first["id"]]
    assert [item["sheet_order"] for item in response.json()] == [0, 1]

    rows = (
        await test_session.execute(
            select(Workflow.id, Workflow.sheet_order)
            .where(Workflow.project_id == project_id)
            .order_by(Workflow.sheet_order)
        )
    ).all()
    assert rows == [(second["id"], 0), (first["id"], 1)]

    # Stale-client tolerance: a partial payload (e.g. another tab added a sheet
    # between fetch and reorder) is accepted; missing known sheets are appended
    # in their existing order rather than 400-locking the UI.
    third = await _create_workflow(auth_client, project_id, "Third")
    partial_response = await auth_client.put(
        f"/api/v1/workflows/reorder-sheets?project_id={project_id}",
        json={"ordered_ids": [first["id"], second["id"]]},
    )
    assert partial_response.status_code == 200
    body = partial_response.json()
    assert [item["id"] for item in body] == [first["id"], second["id"], third["id"]]
    assert [item["sheet_order"] for item in body] == [0, 1, 2]

    # Unknown IDs in the payload (deleted between fetch and reorder, or from a
    # different project) are dropped; remaining sheets still reorder.
    unknown_id = third["id"] + 9999
    drop_response = await auth_client.put(
        f"/api/v1/workflows/reorder-sheets?project_id={project_id}",
        json={"ordered_ids": [third["id"], unknown_id, first["id"], second["id"]]},
    )
    assert drop_response.status_code == 200
    assert [item["id"] for item in drop_response.json()] == [third["id"], first["id"], second["id"]]

    # Duplicates remain a hard error — that's a client bug, not a stale view.
    dup_response = await auth_client.put(
        f"/api/v1/workflows/reorder-sheets?project_id={project_id}",
        json={"ordered_ids": [first["id"], first["id"], second["id"]]},
    )
    assert dup_response.status_code == 400


async def test_workflow_data_source_is_inferred_and_listed_in_project_details(
    auth_client: AsyncClient,
) -> None:
    project_id = await _create_project(auth_client)
    workflow = await _create_data_workflow(auth_client, project_id, "PLS")

    assert workflow["color_source"] == "data"
    assert workflow["tab_color"] == "#3b82f6"
    assert workflow["primary_data_source_id"] is not None
    assert workflow["data_source_ids"] == [workflow["primary_data_source_id"]]
    assert workflow["advisor_channel_id"] is not None

    project_response = await auth_client.get(f"/api/v1/projects/{project_id}")
    assert project_response.status_code == 200
    project = project_response.json()
    assert project["data_sources"][0]["display_name"] == "Sklearn: Wine"
    assert project["data_sources"][0]["source_type"] == "example"
    assert project["workflows"][0]["primary_data_source_id"] == workflow["primary_data_source_id"]
    assert project["workflows"][0]["data_source_ids"] == workflow["data_source_ids"]
    assert {channel["channel_type"] for channel in project["advisor_channels"]} == {"project", "sheet"}

    details_response = await auth_client.get(f"/api/v1/projects/{project_id}/details")
    assert details_response.status_code == 200
    assert details_response.json()["id"] == project_id

    channels_response = await auth_client.get(f"/api/v1/projects/{project_id}/advisor-channels")
    assert channels_response.status_code == 200
    assert {channel["channel_type"] for channel in channels_response.json()} == {"project", "sheet"}


async def test_resetting_tab_color_returns_to_primary_data_source_color(
    auth_client: AsyncClient,
) -> None:
    project_id = await _create_project(auth_client)
    workflow = await _create_data_workflow(auth_client, project_id, "PLS")

    override_response = await auth_client.put(
        f"/api/v1/workflows/{workflow['id']}",
        json={"tab_color": "#ef4444", "create_version": False},
    )
    assert override_response.status_code == 200
    assert override_response.json()["color_source"] == "manual"
    assert override_response.json()["tab_color"] == "#ef4444"

    reset_response = await auth_client.put(
        f"/api/v1/workflows/{workflow['id']}",
        json={"tab_color": None, "create_version": False},
    )
    assert reset_response.status_code == 200
    assert reset_response.json()["color_source"] == "data"
    assert reset_response.json()["tab_color"] == "#3b82f6"


async def test_explicit_workflow_data_source_and_color_endpoints(
    auth_client: AsyncClient,
) -> None:
    project_id = await _create_project(auth_client)
    workflow_response = await auth_client.post(
        "/api/v1/workflows",
        json={
            "name": "Manual Binding",
            "description": "",
            "status": "draft",
            "project_id": project_id,
            "nodes": [],
            "edges": [],
        },
    )
    assert workflow_response.status_code == 201
    workflow = workflow_response.json()

    data_source_response = await auth_client.post(
        f"/api/v1/projects/{project_id}/data-sources",
        json={
            "display_name": "Imported CSV",
            "source_type": "upload",
            "source_ref": "file:imported.csv",
            "fingerprint": "file:imported.csv",
            "color": "#22c55e",
        },
    )
    assert data_source_response.status_code == 201
    data_source = data_source_response.json()

    link_response = await auth_client.put(
        f"/api/v1/workflows/{workflow['id']}/data-sources",
        json={
            "data_source_ids": [data_source["id"]],
            "primary_data_source_id": data_source["id"],
        },
    )
    assert link_response.status_code == 200
    linked = link_response.json()
    assert linked["primary_data_source_id"] == data_source["id"]
    assert linked["data_source_ids"] == [data_source["id"]]
    assert linked["color_source"] == "data"
    assert linked["tab_color"] == "#22c55e"

    color_response = await auth_client.put(
        f"/api/v1/workflows/{workflow['id']}/tab-color",
        json={"tab_color": "#ef4444"},
    )
    assert color_response.status_code == 200
    assert color_response.json()["color_source"] == "manual"
    assert color_response.json()["tab_color"] == "#ef4444"

    reset_response = await auth_client.put(
        f"/api/v1/workflows/{workflow['id']}/tab-color",
        json={"tab_color": None},
    )
    assert reset_response.status_code == 200
    assert reset_response.json()["color_source"] == "data"
    assert reset_response.json()["tab_color"] == "#22c55e"


async def test_workflow_advisor_channel_endpoint_and_conversation_binding(
    auth_client: AsyncClient,
) -> None:
    project_id = await _create_project(auth_client)
    workflow = await _create_workflow(auth_client, project_id, "Advisor Binding")

    channel_response = await auth_client.post(f"/api/v1/workflows/{workflow['id']}/advisor-channel")
    assert channel_response.status_code == 201
    channel = channel_response.json()
    assert channel["workflow_id"] == workflow["id"]
    assert channel["channel_type"] == "sheet"

    update_response = await auth_client.put(
        f"/api/v1/projects/{project_id}/advisor-channels/{channel['id']}",
        json={"conversation_id": "conv-sheet-1"},
    )
    assert update_response.status_code == 200
    assert update_response.json()["conversation_id"] == "conv-sheet-1"
