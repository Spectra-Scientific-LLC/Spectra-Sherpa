"""Duplicate real revision-backed sheets without inventing historical custody."""

from copy import deepcopy
from datetime import datetime, timezone

import pytest
from sqlalchemy import func, select

from spectra_sherpa.app.models.dataset_view import DatasetView
from spectra_sherpa.app.models.experiment import Experiment
from spectra_sherpa.app.models.experiment_file import ExperimentFile
from spectra_sherpa.app.models.project import Project
from spectra_sherpa.app.models.user import User
from spectra_sherpa.app.models.workflow import Workflow
from spectra_sherpa.app.models.workflow_data_selection_revision import WorkflowDataSelectionRevision
from spectra_sherpa.app.services.experiments import experiment_dir
from spectra_sherpa.app.services.workflow_data_selections import execution_selection_revisions, workflow_graph_digest


@pytest.fixture
async def selected_sheet(auth_client, test_session, test_user):
    project = Project(user_id=test_user.id, name="Duplicate selection")
    test_session.add(project)
    await test_session.flush()
    experiment = Experiment(
        user_id=test_user.id, project_id=project.id, name="Small spectrum", metadata_path="metadata.json"
    )
    test_session.add(experiment)
    await test_session.flush()
    directory = experiment_dir(experiment.id)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "source.csv"
    path.write_text("400,500,600\n1,2,3\n2,3,4\n3,5,7\n4,6,8\n", encoding="utf-8")
    file = ExperimentFile(
        experiment_id=experiment.id, file_path=path.name, stage="raw", file_size_bytes=path.stat().st_size
    )
    test_session.add(file)
    await test_session.commit()
    response = await auth_client.post(
        f"/api/v1/experiments/{experiment.id}/dataset-views",
        json={"name": "Exact portfolio", "stage": "raw", "selected_file_ids": [file.id]},
    )
    assert response.status_code == 201, response.text
    view = response.json()
    response = await auth_client.post(
        "/api/v1/workflows",
        json={
            "name": "Bound original",
            "project_id": project.id,
            "nodes": [{"node_id": "source", "node_type": "data.collection_load", "parameters": {}}],
            "edges": [],
        },
    )
    assert response.status_code == 201, response.text
    workflow_id = response.json()["id"]
    selection = {
        key: view["selection"][key]
        for key in (
            "stage",
            "selected_file_ids",
            "asset_id",
            "source_manifest_sha256",
            "collection_definition_sha256",
            "scientific_collection_sha256",
            "target_authority",
            "group_column",
        )
    }
    selection.update(
        experiment_id=experiment.id,
        dataset_name=view["name"],
        dataset_view_id=view["id"],
        dataset_view_sha256=view["selection_sha256"],
    )
    # Two real writes ensure duplication uses the latest receipt, not the
    # oldest one or a copied revision-number sequence.
    for number in (1, 2):
        response = await auth_client.put(
            f"/api/v1/workflows/{workflow_id}/data-selections/source",
            json={
                "expected_revision": number - 1 or None,
                "idempotency_key": f"original-selection-{number}",
                "origin": "canvas",
                "reason": f"Original selection {number}",
                "selection": selection,
            },
        )
        assert response.status_code == 200, response.text
    workflow = await test_session.get(Workflow, workflow_id)
    await test_session.refresh(workflow, attribute_names=["nodes", "edges"])
    return workflow, experiment, view, path, response.json()


async def _revision_snapshot(session, workflow_id):
    rows = (
        await session.scalars(
            select(WorkflowDataSelectionRevision)
            .where(WorkflowDataSelectionRevision.workflow_id == workflow_id)
            .order_by(WorkflowDataSelectionRevision.revision_number)
        )
    ).all()
    return [{column.name: deepcopy(getattr(row, column.name)) for column in row.__table__.columns} for row in rows]


@pytest.mark.parametrize("named_definition", [True, False])
async def test_duplicate_records_new_selection_and_passes_execution_admission(
    auth_client, test_session, test_user, selected_sheet, named_definition
):
    source, _, view, path, latest = selected_sheet
    if not named_definition:
        response = await auth_client.put(
            f"/api/v1/workflows/{source.id}/data-selections/source",
            json={
                "expected_revision": 2,
                "idempotency_key": "active-selection-0003",
                "origin": "canvas",
                "selection": {**latest["selection"], "dataset_view_id": None, "dataset_view_sha256": None},
            },
        )
        assert response.status_code == 200, response.text
        latest = response.json()
    before = await _revision_snapshot(test_session, source.id)
    source_bytes = path.read_bytes()
    source_parameters = deepcopy(source.nodes[0].parameters)
    response = await auth_client.post(f"/api/v1/workflows/{source.id}/duplicate")
    assert response.status_code == 201, response.text
    duplicate = await test_session.get(Workflow, response.json()["id"])
    await test_session.refresh(duplicate, attribute_names=["nodes", "edges"])
    context = await auth_client.get(f"/api/v1/workflows/{duplicate.id}/data-selections/source")
    assert context.status_code == 200
    revision = context.json()["current_revision"]
    assert revision is not None
    assert revision["workflow_id"] == duplicate.id
    assert revision["id"] not in {row["id"] for row in before}
    assert revision["revision_number"] == 1 and revision["parent_revision_id"] is None
    assert revision["created_by"] == test_user.id
    assert revision["origin"] == "workflow_duplicate"
    assert revision["reason"] == f"Copied workflow {source.id}, data-selection revision {latest['id']}"
    assert revision["selection"] == latest["selection"] == context.json()["saved_selection"]
    assert revision["graph_digest"] == workflow_graph_digest(duplicate)
    admitted = await execution_selection_revisions(
        test_session,
        workflow_id=duplicate.id,
        graph_digest=workflow_graph_digest(duplicate),
        source_nodes=list(duplicate.nodes),
        user_id=test_user.id,
        workflow_project_id=duplicate.project_id,
    )
    assert [row["revision_id"] for row in admitted] == [revision["id"]]
    assert admitted[0]["selection"]["dataset_view_id"] == (view["id"] if named_definition else None)
    assert await _revision_snapshot(test_session, source.id) == before
    assert source.nodes[0].parameters == source_parameters == duplicate.nodes[0].parameters
    assert path.read_bytes() == source_bytes
    stored_view = await test_session.get(DatasetView, view["id"])
    assert stored_view.selection == view["selection"]


async def test_duplicate_unbound_authoring_source_does_not_invent_a_selection(auth_client, selected_sheet):
    source, *_ = selected_sheet
    response = await auth_client.post(
        "/api/v1/workflows",
        json={
            "name": "Unbound",
            "project_id": source.project_id,
            "nodes": [{"node_id": "empty", "node_type": "data.collection_load", "parameters": {}}],
            "edges": [],
        },
    )
    assert response.status_code == 201, response.text
    response = await auth_client.post(f"/api/v1/workflows/{response.json()['id']}/duplicate")
    assert response.status_code == 201, response.text
    context = await auth_client.get(f"/api/v1/workflows/{response.json()['id']}/data-selections/empty")
    assert context.status_code == 200
    assert context.json()["saved_selection"] is None
    assert context.json()["current_revision"] is None


@pytest.mark.parametrize(
    ("damage", "status"),
    [
        ("changed_node", 409),
        ("changed_source", 409),
        ("changed_view", 409),
        ("cross_project_view", 404),
        ("cross_project_experiment", 409),
        ("foreign_experiment_owner", 404),
        ("foreign_workflow_owner", 404),
        ("deleted_view", 404),
        ("missing_revision", 409),
    ],
)
async def test_duplicate_refuses_stale_or_cross_scope_binding_before_persisting(
    auth_client, test_session, test_user, selected_sheet, damage, status
):
    source, experiment, view, path, _ = selected_sheet
    stored_view = await test_session.get(DatasetView, view["id"])
    if damage == "changed_node":
        source.nodes[0].parameters = {**source.nodes[0].parameters, "scientific_collection_sha256": "f" * 64}
    elif damage == "changed_source":
        path.write_text("400,500,600\n9,2,3\n2,3,4\n3,5,7\n4,6,8\n", encoding="utf-8")
    elif damage == "changed_view":
        stored_view.selection_sha256 = "f" * 64
    elif damage in {"cross_project_view", "cross_project_experiment"}:
        other = Project(user_id=test_user.id, name="Other project")
        test_session.add(other)
        await test_session.flush()
        if damage == "cross_project_view":
            stored_view.project_id = other.id
        else:
            experiment.project_id = other.id
    elif damage in {"foreign_experiment_owner", "foreign_workflow_owner"}:
        other = User(username="foreign-owner")
        test_session.add(other)
        await test_session.flush()
        if damage == "foreign_experiment_owner":
            experiment.user_id = other.id
        else:
            source.user_id = other.id
    elif damage == "deleted_view":
        stored_view.deleted_at = datetime.now(timezone.utc)
    elif damage == "missing_revision":
        rows = (await test_session.scalars(select(WorkflowDataSelectionRevision))).all()
        for row in rows:
            await test_session.delete(row)
    await test_session.commit()
    before = await _revision_snapshot(test_session, source.id)
    workflow_count = await test_session.scalar(select(func.count()).select_from(Workflow))
    revision_count = await test_session.scalar(select(func.count()).select_from(WorkflowDataSelectionRevision))
    response = await auth_client.post(f"/api/v1/workflows/{source.id}/duplicate")
    assert response.status_code == status, response.text
    assert await test_session.scalar(select(func.count()).select_from(Workflow)) == workflow_count
    assert await test_session.scalar(select(func.count()).select_from(WorkflowDataSelectionRevision)) == revision_count
    assert await _revision_snapshot(test_session, source.id) == before
