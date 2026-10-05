"""Project choices are explicit, scoped and append-only."""

from types import SimpleNamespace

import numpy as np
import pytest
from sqlalchemy import select, text

from spectra_sherpa.app.models.dataset_view import DatasetView
from spectra_sherpa.app.models.experiment import Experiment
from spectra_sherpa.app.models.project import Project
from spectra_sherpa.app.models.project_choice_event import ProjectChoiceEvent
from spectra_sherpa.app.models.user import User
from spectra_sherpa.app.models.workflow import Workflow
from spectra_sherpa.app.services.dataset_views import receipt_sha256, selection_receipt
from spectra_sherpa.app.services.model_application import LoadedProjectDataset


@pytest.mark.asyncio
async def test_project_choices_preserve_history_and_refuse_cross_project_targets(
    auth_client, test_session, test_user, monkeypatch
):
    first = Project(user_id=test_user.id, name="Corn")
    other = Project(user_id=test_user.id, name="Lavender")
    another_user = User(username="another_scientist")
    test_session.add(another_user)
    await test_session.flush()
    foreign_tenant = Project(user_id=another_user.id, name="Private")
    test_session.add_all([first, other, foreign_tenant])
    await test_session.flush()
    experiment = Experiment(user_id=test_user.id, project_id=first.id, name="M5", metadata_path="metadata.json")
    foreign_experiment = Experiment(
        user_id=test_user.id, project_id=other.id, name="Lavender", metadata_path="metadata.json"
    )
    workflow = Workflow(user_id=test_user.id, project_id=first.id, name="PLS", status="draft", purpose="analysis")
    foreign_workflow = Workflow(
        user_id=test_user.id, project_id=other.id, name="PLS-DA", status="draft", purpose="analysis"
    )
    test_session.add_all([experiment, foreign_experiment, workflow, foreign_workflow])
    await test_session.flush()
    source_state = {"sha": "a" * 64}

    async def load(_session, *, user_id, experiment_id, stage="raw", file_ids=None, asset_id=None):
        assert user_id == test_user.id and experiment_id == experiment.id
        assert stage == "raw" and file_ids in (None, [11]) and asset_id is None
        return LoadedProjectDataset(
            dataset=SimpleNamespace(
                n_samples=2,
                sample_axis=SimpleNamespace(include_mask=np.asarray([True, False], dtype=bool)),
                meta={"source_collection": {"files": [{"file_name": "corn.mat", "sha256": source_state["sha"]}]}},
            ),
            experiment_id=experiment.id,
            experiment_name="M5",
            project_id=first.id,
            file_ids=[11],
            stage="raw",
            asset_id=None,
            source_manifest_sha256=source_state["sha"],
        )

    monkeypatch.setattr("spectra_sherpa.app.api.v1.routes.project_choices.load_project_dataset", load)
    loaded = await load(
        test_session, user_id=test_user.id, experiment_id=experiment.id, stage="raw", file_ids=[11], asset_id=None
    )
    receipt = selection_receipt(loaded, selected_file_ids=[11])
    view = DatasetView(
        project_id=first.id,
        experiment_id=experiment.id,
        created_by_user_id=test_user.id,
        name="M5 moisture",
        name_key="m5 moisture",
        selection=receipt,
        selection_sha256=receipt_sha256(receipt),
    )
    test_session.add(view)
    await test_session.commit()

    url = f"/api/v1/projects/{first.id}/choices"
    assert (await auth_client.get(url)).json() == {"current": {}, "history": []}
    assert (await auth_client.get(f"{url}/current-dataset")).json() == {"dataset": None}
    foreign_url = f"/api/v1/projects/{foreign_tenant.id}/choices"
    assert (await auth_client.get(foreign_url)).status_code == 404
    assert (
        await auth_client.post(foreign_url, json={"kind": "workflow", "workflow_id": workflow.id})
    ).status_code == 404
    assert (
        await auth_client.post(url, json={"kind": "dataset", "experiment_id": foreign_experiment.id})
    ).status_code == 404
    assert (
        await auth_client.post(url, json={"kind": "workflow", "workflow_id": foreign_workflow.id})
    ).status_code == 404
    assert (
        await auth_client.post(
            url, json={"kind": "dataset", "experiment_id": experiment.id, "workflow_id": workflow.id}
        )
    ).status_code == 422

    default = await auth_client.post(url, json={"kind": "dataset", "experiment_id": experiment.id})
    first_default_event = await test_session.get(ProjectChoiceEvent, default.json()["id"])
    assert first_default_event is not None
    assert first_default_event.selected_definition["source_files"][0]["sha256"] == "a" * 64
    same_default = await auth_client.post(url, json={"kind": "dataset", "experiment_id": experiment.id})
    assert same_default.json()["id"] == default.json()["id"]
    source_state["sha"] = "b" * 64
    revised_default = await auth_client.post(url, json={"kind": "dataset", "experiment_id": experiment.id})
    assert revised_default.status_code == 201
    assert revised_default.json()["id"] != default.json()["id"]
    assert revised_default.json()["selected_digest"] != default.json()["selected_digest"]
    await test_session.refresh(first_default_event)
    assert first_default_event.selected_definition["source_files"][0]["sha256"] == "a" * 64
    source_state["sha"] = "a" * 64
    named = await auth_client.post(
        url,
        json={"kind": "dataset", "experiment_id": experiment.id, "dataset_view_id": view.id},
    )
    sheet = await auth_client.post(url, json={"kind": "workflow", "workflow_id": workflow.id})
    assert [default.status_code, named.status_code, sheet.status_code] == [201, 201, 201]
    assert default.json()["selected_digest"] == receipt_sha256(selection_receipt(loaded, selected_file_ids=None))
    repeated = await auth_client.post(url, json={"kind": "workflow", "workflow_id": workflow.id})
    assert repeated.status_code == 201 and repeated.json()["id"] == sheet.json()["id"]
    listed = (await auth_client.get(url)).json()
    assert listed["current"]["dataset"]["dataset_view_id"] == view.id
    assert listed["current"]["dataset"]["selected_dataset_view_id"] == view.id
    assert listed["current"]["dataset"]["selected_experiment_id"] == experiment.id
    assert listed["current"]["dataset"]["selected_name"] == "M5 moisture"
    assert listed["current"]["dataset"]["selected_digest"] == view.selection_sha256
    active = await auth_client.get(f"{url}/current-dataset")
    assert active.status_code == 200
    assert active.json()["dataset"]["id"] == named.json()["id"]
    assert active.json()["dataset"]["name"] == "M5 moisture"
    assert active.json()["dataset"]["definition"] == receipt
    assert (await auth_client.get(f"{foreign_url}/current-dataset")).status_code == 404
    assert listed["current"]["workflow"]["workflow_id"] == workflow.id
    assert listed["current"]["workflow"]["selected_name"] == "PLS"
    assert [event["id"] for event in listed["history"]] == [
        sheet.json()["id"],
        named.json()["id"],
        revised_default.json()["id"],
        default.json()["id"],
    ]

    workflow.integrity_hash = "c" * 64
    await test_session.commit()
    revised_sheet = await auth_client.post(url, json={"kind": "workflow", "workflow_id": workflow.id})
    assert revised_sheet.status_code == 201
    assert revised_sheet.json()["id"] != sheet.json()["id"]
    assert revised_sheet.json()["selected_digest"] == "c" * 64

    source_state["sha"] = "b" * 64
    assert (
        await auth_client.post(
            url, json={"kind": "dataset", "experiment_id": experiment.id, "dataset_view_id": view.id}
        )
    ).status_code == 409
    source_state["sha"] = "a" * 64

    view.deleted_at = view.created_at
    await test_session.commit()
    assert (await auth_client.get(f"{url}/current-dataset")).status_code == 409
    assert (
        await auth_client.post(
            url, json={"kind": "dataset", "experiment_id": experiment.id, "dataset_view_id": view.id}
        )
    ).status_code == 404
    # A deleted definition does not rewrite the scientist's last choice.
    assert (await auth_client.get(url)).json()["current"]["dataset"]["dataset_view_id"] == view.id
    # With SQLite FK enforcement on, hard deletion exercises the actual
    # ON DELETE SET NULL path rather than simulating it in the ORM.
    await test_session.execute(text("PRAGMA foreign_keys=ON"))
    await test_session.commit()
    named_event = await test_session.get(ProjectChoiceEvent, named.json()["id"])
    await test_session.delete(view)
    await test_session.commit()
    await test_session.refresh(named_event)
    after_delete = (await auth_client.get(url)).json()["current"]["dataset"]
    assert after_delete["dataset_view_id"] is None
    assert after_delete["selected_dataset_view_id"] == view.id
    assert after_delete["selected_name"] == "M5 moisture"
    assert after_delete["selected_digest"] == view.selection_sha256
    events = (await test_session.scalars(select(ProjectChoiceEvent).order_by(ProjectChoiceEvent.id))).all()
    assert len(events) == 5


@pytest.mark.asyncio
async def test_default_choice_records_exact_displayed_synthetic_file(auth_client, test_session, test_user, monkeypatch):
    project = Project(user_id=test_user.id, name="Synthetic")
    test_session.add(project)
    await test_session.flush()
    experiment = Experiment(
        user_id=test_user.id, project_id=project.id, name="Generated", metadata_path="metadata.json"
    )
    test_session.add(experiment)
    await test_session.commit()

    async def load(_session, *, user_id, experiment_id, stage, file_ids, asset_id):
        assert user_id == test_user.id and experiment_id == experiment.id
        assert (stage, file_ids, asset_id) == ("synthetic", [27], "spectra")
        return LoadedProjectDataset(
            dataset=SimpleNamespace(
                n_samples=2,
                sample_axis=None,
                meta={"source_collection": {"files": [{"file_name": "generated.csv", "sha256": "e" * 64}]}},
            ),
            experiment_id=experiment.id,
            experiment_name="Generated",
            project_id=project.id,
            file_ids=[27],
            stage="synthetic",
            asset_id="spectra",
            source_manifest_sha256="e" * 64,
        )

    monkeypatch.setattr("spectra_sherpa.app.api.v1.routes.project_choices.load_project_dataset", load)
    response = await auth_client.post(
        f"/api/v1/projects/{project.id}/choices",
        json={
            "kind": "dataset",
            "experiment_id": experiment.id,
            "stage": "synthetic",
            "selected_file_ids": [27],
            "asset_id": "spectra",
        },
    )
    assert response.status_code == 201, response.text
    event = await test_session.get(ProjectChoiceEvent, response.json()["id"])
    assert event is not None
    assert event.selected_definition["selected_file_ids"] == [27]
    assert event.selected_definition["stage"] == "synthetic"
    assert event.selected_definition["asset_id"] == "spectra"
