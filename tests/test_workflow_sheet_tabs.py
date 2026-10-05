from __future__ import annotations

from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from spectra_sherpa.app.models.execution_run import ExecutionRun
from spectra_sherpa.app.models.workflow import Workflow
from spectra_sherpa.app.models.workflow_edge import WorkflowEdge
from spectra_sherpa.app.models.workflow_node import WorkflowNode
from spectra_sherpa.app.models.workflow_version import WorkflowVersion
from spectra_sherpa.app.services.dag.saved_graph_admission import CURRENT_CLASSIFIER_VALIDATION_SEMANTICS


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
                    "node_type": "data.file_load",
                    "label": "Data",
                    "parameters": {"experiment_id": 1, "file_id": 1, "stage": "raw"},
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
                    "node_type": "data.file_load",
                    "label": "Experiment File",
                    "parameters": {"experiment_id": 7, "file_id": 11, "stage": "raw"},
                    "position_x": 10,
                    "position_y": 20,
                }
            ],
            "edges": [],
        },
    )
    assert response.status_code == 201
    return response.json()


async def test_candidate_authority_is_retained_but_not_an_interactive_sheet(
    auth_client: AsyncClient,
    test_session: AsyncSession,
) -> None:
    project_id = await _create_project(auth_client)
    first = await _create_workflow(auth_client, project_id, "Scientific PLS")
    second = await _create_workflow(auth_client, project_id, "Scientific PCA")
    analysis = await test_session.get(Workflow, first["id"])
    candidate = Workflow(
        user_id=analysis.user_id,
        project_id=project_id,
        name="Internal candidate",
        purpose="managed_candidate_authority",
        sheet_order=9,
        status="draft",
    )
    test_session.add(candidate)
    await test_session.commit()

    tabs = await auth_client.get("/api/v1/workflows", params={"project_id": project_id, "in_workbook": True})
    assert tabs.status_code == 200
    assert [row["id"] for row in tabs.json()] == [first["id"], second["id"]]
    reordered = await auth_client.put(
        f"/api/v1/workflows/reorder-sheets?project_id={project_id}",
        json={"ordered_ids": [second["id"], candidate.id, first["id"]]},
    )
    assert reordered.status_code == 200
    assert [row["id"] for row in reordered.json()] == [second["id"], first["id"]]
    await test_session.refresh(candidate)
    assert candidate.sheet_order == 9
    records = await auth_client.get("/api/v1/workflows", params={"project_id": project_id})
    assert candidate.id in {row["id"] for row in records.json()}
    detail = await auth_client.get(f"/api/v1/workflows/{candidate.id}")
    assert detail.status_code == 200
    assert detail.json()["purpose"] == "managed_candidate_authority"


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


async def test_create_refuses_retired_classifier_parameter_before_database_mutation(
    auth_client: AsyncClient,
    test_session: AsyncSession,
) -> None:
    project_id = await _create_project(auth_client)
    before = await test_session.scalar(select(func.count(Workflow.id)))

    response = await auth_client.post(
        "/api/v1/workflows",
        json={
            "name": "Retired local CV",
            "project_id": project_id,
            "nodes": [
                {
                    "node_id": "model",
                    "node_type": "classification.plsda",
                    "parameters": {"n_components": 2, "scale": True, "cv_folds": 5},
                }
            ],
            "edges": [],
        },
    )

    assert response.status_code == 400
    assert "cannot be auto-migrated" in response.json()["detail"]
    assert await test_session.scalar(select(func.count(Workflow.id))) == before


async def test_create_refuses_malformed_port_before_database_mutation(
    auth_client: AsyncClient,
    test_session: AsyncSession,
) -> None:
    project_id = await _create_project(auth_client)
    before = await test_session.scalar(select(func.count(Workflow.id)))

    response = await auth_client.post(
        "/api/v1/workflows",
        json={
            "name": "Malformed port",
            "project_id": project_id,
            "nodes": [
                {"node_id": "source_a", "node_type": "data.file_load", "parameters": {}},
                {"node_id": "source_b", "node_type": "data.file_load", "parameters": {}},
            ],
            "edges": [
                {
                    "from_node_id": "source_a",
                    "to_node_id": "source_b",
                    "from_output": "retired_cv_output",
                    "to_input": "default",
                }
            ],
        },
    )

    assert response.status_code == 400
    assert "does not name ports" in response.json()["detail"]
    assert await test_session.scalar(select(func.count(Workflow.id))) == before


async def test_update_refuses_retired_classifier_parameter_before_any_mutation(
    auth_client: AsyncClient,
    test_session: AsyncSession,
) -> None:
    project_id = await _create_project(auth_client)
    workflow = await _create_workflow(auth_client, project_id, "Current graph")
    before = (await test_session.execute(select(Workflow).where(Workflow.id == workflow["id"]))).scalar_one()
    before_name = before.name
    before_integrity = before.integrity_hash

    response = await auth_client.put(
        f"/api/v1/workflows/{workflow['id']}",
        json={
            "name": "Must not persist",
            "create_version": False,
            "nodes": [
                {
                    "node_id": "model",
                    "node_type": "classification.knn",
                    "parameters": {"n_neighbors": 3, "cv_folds": 5},
                }
            ],
        },
    )

    assert response.status_code == 400
    await test_session.refresh(before)
    assert before.name == before_name
    assert before.integrity_hash == before_integrity
    observed_nodes = (
        (await test_session.execute(select(WorkflowNode).where(WorkflowNode.workflow_id == workflow["id"])))
        .scalars()
        .all()
    )
    assert [(node.node_id, node.node_type) for node in observed_nodes] == [("data_1", "data.file_load")]


async def test_update_edges_only_refuses_malformed_port_before_any_mutation(
    auth_client: AsyncClient,
    test_session: AsyncSession,
) -> None:
    project_id = await _create_project(auth_client)
    create = await auth_client.post(
        "/api/v1/workflows",
        json={
            "name": "Two sources",
            "project_id": project_id,
            "nodes": [
                {"node_id": "source_a", "node_type": "data.file_load", "parameters": {}},
                {"node_id": "source_b", "node_type": "data.file_load", "parameters": {}},
            ],
            "edges": [],
        },
    )
    assert create.status_code == 201
    workflow = create.json()

    response = await auth_client.put(
        f"/api/v1/workflows/{workflow['id']}",
        json={
            "name": "Must not persist",
            "create_version": False,
            "edges": [
                {
                    "from_node_id": "source_a",
                    "to_node_id": "source_b",
                    "from_output": "retired_cv_output",
                    "to_input": "default",
                }
            ],
        },
    )

    assert response.status_code == 400
    observed = (await test_session.execute(select(Workflow).where(Workflow.id == workflow["id"]))).scalar_one()
    assert observed.name == "Two sources"
    assert (
        await test_session.scalar(
            select(func.count()).select_from(WorkflowNode).where(WorkflowNode.workflow_id == workflow["id"])
        )
        == 2
    )
    assert (
        await test_session.scalar(
            select(func.count()).select_from(WorkflowEdge).where(WorkflowEdge.workflow_id == workflow["id"])
        )
        == 0
    )


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
    assert duplicate["purpose"] == "analysis"
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


async def test_duplicate_rejects_retired_graph_without_creating_a_sheet(
    auth_client: AsyncClient,
    test_session: AsyncSession,
) -> None:
    project_id = await _create_project(auth_client)
    workflow = await _create_workflow(auth_client, project_id, "Retired duplicate")
    node = (
        await test_session.execute(select(WorkflowNode).where(WorkflowNode.workflow_id == workflow["id"]))
    ).scalar_one()
    node.node_type = "data.source"
    await test_session.commit()
    before = await test_session.scalar(select(func.count(Workflow.id)))

    response = await auth_client.post(f"/api/v1/workflows/{workflow['id']}/duplicate")

    assert response.status_code == 409
    assert "not current" in response.json()["detail"]
    assert await test_session.scalar(select(func.count(Workflow.id))) == before


async def test_duplicate_preserves_current_parameter_incomplete_draft(
    auth_client: AsyncClient,
) -> None:
    project_id = await _create_project(auth_client)
    create_response = await auth_client.post(
        "/api/v1/workflows",
        json={
            "name": "Unbound draft",
            "project_id": project_id,
            "nodes": [
                {
                    "node_id": "source",
                    "node_type": "data.file_load",
                    "parameters": {},
                }
            ],
            "edges": [],
        },
    )
    assert create_response.status_code == 201

    duplicate_response = await auth_client.post(f"/api/v1/workflows/{create_response.json()['id']}/duplicate")

    assert duplicate_response.status_code == 201
    assert duplicate_response.json()["nodes"][0]["parameters"] == {}


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
    assert project["data_sources"][0]["display_name"] == "Experiment 7 / File 11"
    assert project["data_sources"][0]["source_type"] == "upload"
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


async def test_open_version_as_new_sheet_clones_without_touching_original(
    auth_client: AsyncClient,
    test_session: AsyncSession,
) -> None:
    """Non-destructive counterpart to /restore.

    Opening a workflow version as a new sheet must create a fresh workflow
    row in the same project, populated from the version's snapshot, while
    leaving the original workflow + all its other versions untouched.
    """
    project_id = await _create_project(auth_client)
    workflow = await _create_workflow(auth_client, project_id, "PLS")

    # Save explicitly with create_version=true so we have a version row to
    # open.  The initial POST /workflows doesn't create one by itself.
    save_resp = await auth_client.put(
        f"/api/v1/workflows/{workflow['id']}",
        json={"name": "PLS", "create_version": True},
    )
    assert save_resp.status_code == 200

    versions_resp = await auth_client.get(f"/api/v1/workflows/{workflow['id']}/versions")
    assert versions_resp.status_code == 200
    versions = versions_resp.json()["versions"]
    assert len(versions) >= 1
    version_id = versions[0]["id"]
    version_number = versions[0]["version_number"]
    version = await test_session.get(WorkflowVersion, version_id)
    assert version is not None
    assert version.snapshot["classifier_validation_semantics"] == CURRENT_CLASSIFIER_VALIDATION_SEMANTICS

    open_resp = await auth_client.post(
        f"/api/v1/workflows/{workflow['id']}/versions/{version_id}/open-as-new-sheet",
    )
    assert open_resp.status_code == 201
    new_sheet = open_resp.json()

    # New sheet is a distinct workflow in the same project.
    assert new_sheet["id"] != workflow["id"]
    assert new_sheet["project_id"] == project_id
    assert new_sheet["purpose"] == "analysis"
    assert new_sheet["created_from_workflow_id"] == workflow["id"]
    assert new_sheet["name"] == f"PLS (from v{version_number})"
    assert new_sheet["sheet_order"] == 1
    assert len(new_sheet["nodes"]) == 1
    assert new_sheet["nodes"][0]["node_id"] == "data_1"

    # Original workflow's content is untouched.
    original_resp = await auth_client.get(f"/api/v1/workflows/{workflow['id']}")
    assert original_resp.status_code == 200
    assert original_resp.json()["id"] == workflow["id"]

    # The new sheet starts with zero version rows of its own — it's a fresh
    # workflow, the version history did not follow.
    new_version_count = await test_session.scalar(
        select(func.count(WorkflowVersion.id)).where(WorkflowVersion.workflow_id == new_sheet["id"])
    )
    assert new_version_count == 0

    # Opening the same version a second time disambiguates with " (2)".
    second_open_resp = await auth_client.post(
        f"/api/v1/workflows/{workflow['id']}/versions/{version_id}/open-as-new-sheet",
    )
    assert second_open_resp.status_code == 201
    assert second_open_resp.json()["name"] == f"PLS (from v{version_number}) (2)"


async def test_open_version_as_new_sheet_rejects_wrong_workflow_version_id(
    auth_client: AsyncClient,
) -> None:
    """A version that belongs to a different workflow must 404, not silently clone."""
    project_id = await _create_project(auth_client)
    workflow_a = await _create_workflow(auth_client, project_id, "Workflow A")
    workflow_b = await _create_workflow(auth_client, project_id, "Workflow B")

    save_resp = await auth_client.put(
        f"/api/v1/workflows/{workflow_a['id']}",
        json={"name": "Workflow A", "create_version": True},
    )
    assert save_resp.status_code == 200

    a_versions = await auth_client.get(f"/api/v1/workflows/{workflow_a['id']}/versions")
    a_version_id = a_versions.json()["versions"][0]["id"]

    # Try to open A's version via B's workflow id — must 404.
    resp = await auth_client.post(
        f"/api/v1/workflows/{workflow_b['id']}/versions/{a_version_id}/open-as-new-sheet",
    )
    assert resp.status_code == 404


async def test_version_restore_and_open_reject_retired_snapshot_before_mutation(
    auth_client: AsyncClient,
    test_session: AsyncSession,
) -> None:
    project_id = await _create_project(auth_client)
    workflow = await _create_workflow(auth_client, project_id, "Current workflow")
    save_response = await auth_client.put(
        f"/api/v1/workflows/{workflow['id']}",
        json={"name": "Current workflow", "create_version": True},
    )
    assert save_response.status_code == 200

    version = (
        await test_session.execute(select(WorkflowVersion).where(WorkflowVersion.workflow_id == workflow["id"]))
    ).scalar_one()
    snapshot = dict(version.snapshot)
    snapshot["name"] = "Retired snapshot name"
    snapshot["nodes"] = [dict(node) for node in snapshot["nodes"]]
    snapshot["nodes"][0]["node_type"] = "model.pls"
    version.snapshot = snapshot
    await test_session.commit()

    workflow_count = await test_session.scalar(select(func.count(Workflow.id)))
    version_count = await test_session.scalar(
        select(func.count(WorkflowVersion.id)).where(WorkflowVersion.workflow_id == workflow["id"])
    )

    restore_response = await auth_client.post(f"/api/v1/workflows/{workflow['id']}/versions/{version.id}/restore")
    assert restore_response.status_code == 409
    restored = await auth_client.get(f"/api/v1/workflows/{workflow['id']}")
    assert restored.status_code == 200
    assert restored.json()["name"] == "Current workflow"
    assert restored.json()["nodes"][0]["node_type"] == "data.file_load"
    assert (
        await test_session.scalar(
            select(func.count(WorkflowVersion.id)).where(WorkflowVersion.workflow_id == workflow["id"])
        )
        == version_count
    )

    open_response = await auth_client.post(
        f"/api/v1/workflows/{workflow['id']}/versions/{version.id}/open-as-new-sheet"
    )
    assert open_response.status_code == 409
    assert await test_session.scalar(select(func.count(Workflow.id))) == workflow_count


async def test_version_restore_refuses_default_omitted_legacy_classifier(
    auth_client: AsyncClient,
    test_session: AsyncSession,
) -> None:
    project_id = await _create_project(auth_client)
    workflow = await _create_workflow(auth_client, project_id, "Legacy classifier")
    assert (
        await auth_client.put(
            f"/api/v1/workflows/{workflow['id']}",
            json={"name": "Legacy classifier", "create_version": True},
        )
    ).status_code == 200

    version = (
        await test_session.execute(select(WorkflowVersion).where(WorkflowVersion.workflow_id == workflow["id"]))
    ).scalar_one()
    snapshot = dict(version.snapshot)
    snapshot.pop("classifier_validation_semantics")
    snapshot["nodes"] = [dict(node) for node in snapshot["nodes"]]
    snapshot["nodes"][0]["node_type"] = "classification.knn"
    snapshot["nodes"][0]["parameters"] = {"n_neighbors": 3}
    version.snapshot = snapshot
    await test_session.commit()

    response = await auth_client.post(f"/api/v1/workflows/{workflow['id']}/versions/{version.id}/restore")
    assert response.status_code == 409
    assert "no current classifier-validation authority" in response.json()["detail"]
