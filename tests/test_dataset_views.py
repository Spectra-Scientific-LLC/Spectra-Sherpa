"""Named My Dataset views preserve exact cohort/source identity without mutating history."""

from datetime import datetime, timezone
from types import SimpleNamespace

import numpy as np
import pytest
from fastapi import HTTPException
from sqlalchemy import select

from spectra_sherpa.app.api.v1.routes.runs import ArtifactBatchRunRequest, RunDatasetRef, _load_batch_dataset
from spectra_sherpa.app.models.dataset_view import DatasetView
from spectra_sherpa.app.models.experiment import Experiment
from spectra_sherpa.app.models.project import Project
from spectra_sherpa.app.models.workflow import Workflow
from spectra_sherpa.app.models.workflow_data_selection_revision import WorkflowDataSelectionRevision
from spectra_sherpa.app.models.workflow_node import WorkflowNode
from spectra_sherpa.app.schemas.workflow_data_selection import WorkflowSourceSelection
from spectra_sherpa.app.services.dataset_views import receipt_sha256, selection_receipt
from spectra_sherpa.app.services.model_application import LoadedProjectDataset
from spectra_sherpa.app.services.workflow_data_selections import (
    execution_selection_revisions,
    source_parameters,
    validate_selection,
)


@pytest.mark.asyncio
async def test_dataset_view_lifecycle_detects_drift_and_retains_deleted_history(
    auth_client, test_session, test_user, monkeypatch
):
    project = Project(user_id=test_user.id, name="Corn")
    test_session.add(project)
    await test_session.flush()
    experiment = Experiment(
        user_id=test_user.id,
        project_id=project.id,
        name="M5",
        metadata_path="metadata.json",
    )
    test_session.add(experiment)
    await test_session.commit()

    state = {"source": "a" * 64, "mask": [True, False, True]}

    async def load(_session, *, user_id, experiment_id, stage, file_ids, asset_id):
        assert user_id == test_user.id
        assert experiment_id == experiment.id
        assert stage == "raw"
        assert file_ids == [17]
        assert asset_id == "spectra"
        source = state["source"]
        dataset = SimpleNamespace(
            n_samples=3,
            sample_axis=SimpleNamespace(include_mask=np.asarray(state["mask"], dtype=bool)),
            meta={"source_collection": {"files": [{"file_name": "corn.mat", "sha256": source}]}},
        )
        return LoadedProjectDataset(
            dataset=dataset,
            experiment_id=experiment.id,
            experiment_name="M5",
            project_id=project.id,
            file_ids=[17],
            stage="raw",
            asset_id="spectra",
            source_manifest_sha256=source,
        )

    monkeypatch.setattr("spectra_sherpa.app.api.v1.routes.dataset_views.load_project_dataset", load)
    base = f"/api/v1/experiments/{experiment.id}/dataset-views"
    payload = {"name": "M5 moisture", "stage": "raw", "selected_file_ids": [17], "asset_id": "spectra"}

    created = await auth_client.post(base, json=payload)
    assert created.status_code == 201, created.text
    view = created.json()
    assert view["selection"]["included_sample_mask_hex"] == "05"
    assert view["selection"]["source_files"][0]["sha256"] == "a" * 64
    assert len(view["selection_sha256"]) == 64
    assert (await auth_client.get(f"{base}/{view['id']}")).status_code == 200
    assert (await auth_client.post(base, json={**payload, "name": "m5 MOISTURE"})).status_code == 409
    # The local router and hosted wrapper differ in 404 vs 405 for an
    # unsupported method; neither may mutate an immutable definition.
    assert (await auth_client.put(f"{base}/{view['id']}", json=payload)).status_code in {404, 405}

    stored = await test_session.scalar(select(DatasetView).where(DatasetView.id == view["id"]))
    assert stored is not None
    assert stored.selection == view["selection"]
    stored.selection = {**stored.selection, "included_count": 3}
    await test_session.commit()
    assert (await auth_client.get(f"{base}/{view['id']}")).status_code == 409
    stored.selection = view["selection"]
    await test_session.commit()

    state["mask"] = [True, True, True]
    assert (await auth_client.get(f"{base}/{view['id']}")).status_code == 409
    state["mask"] = [True, False, True]
    state["source"] = "b" * 64
    assert (await auth_client.get(f"{base}/{view['id']}")).status_code == 409
    state["source"] = "a" * 64

    assert (await auth_client.delete(f"{base}/{view['id']}")).status_code == 204
    assert (await auth_client.get(base)).json() == []
    assert (await auth_client.get(f"{base}/{view['id']}")).status_code == 404
    assert (await auth_client.post(base, json=payload)).status_code == 409


@pytest.mark.asyncio
async def test_dataset_view_refuses_default_name(auth_client, test_session, test_user):
    project = Project(user_id=test_user.id, name="Corn")
    test_session.add(project)
    await test_session.flush()
    experiment = Experiment(user_id=test_user.id, project_id=project.id, name="M5", metadata_path="metadata.json")
    test_session.add(experiment)
    await test_session.commit()
    response = await auth_client.post(f"/api/v1/experiments/{experiment.id}/dataset-views", json={"name": " default "})
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_batch_uses_saved_definition_and_refuses_cohort_drift(test_session, test_user, monkeypatch):
    project = Project(user_id=test_user.id, name="Corn")
    test_session.add(project)
    await test_session.flush()
    experiment = Experiment(user_id=test_user.id, project_id=project.id, name="M5", metadata_path="metadata.json")
    test_session.add(experiment)
    await test_session.flush()
    state = {"mask": [True, False, True]}

    async def load(_session, *, user_id, experiment_id, file_ids, stage, asset_id, file_id=None):
        assert user_id == test_user.id
        assert experiment_id == experiment.id
        assert file_id is None and file_ids == [17] and stage == "raw" and asset_id == "spectra"
        return LoadedProjectDataset(
            dataset=SimpleNamespace(
                n_samples=3,
                sample_axis=SimpleNamespace(include_mask=np.asarray(state["mask"], dtype=bool)),
                meta={"source_collection": {"files": [{"file_name": "corn.mat", "sha256": "a" * 64}]}},
            ),
            experiment_id=experiment.id,
            experiment_name="M5",
            project_id=project.id,
            file_ids=[17],
            stage="raw",
            asset_id="spectra",
            source_manifest_sha256="a" * 64,
            scientific_collection_sha256="b" * 64,
        )

    monkeypatch.setattr("spectra_sherpa.app.api.v1.routes.runs.load_project_dataset", load)
    loaded = await load(
        test_session,
        user_id=test_user.id,
        experiment_id=experiment.id,
        file_id=None,
        file_ids=[17],
        stage="raw",
        asset_id="spectra",
    )
    receipt = selection_receipt(loaded, selected_file_ids=[17])
    view = DatasetView(
        project_id=project.id,
        experiment_id=experiment.id,
        created_by_user_id=test_user.id,
        name="M5 cohort",
        name_key="m5 cohort",
        selection=receipt,
        selection_sha256=receipt_sha256(receipt),
    )
    test_session.add(view)
    await test_session.commit()
    payload = ArtifactBatchRunRequest(
        artifact_uids=["model-1"],
        dataset=RunDatasetRef(experiment_id=experiment.id),
        dataset_view_id=view.id,
    )
    chosen, chosen_view = await _load_batch_dataset(test_session, test_user.id, payload)
    assert chosen.file_ids == [17] and chosen_view.id == view.id
    monkeypatch.setattr("spectra_sherpa.app.services.workflow_data_selections.load_project_dataset", load)
    workflow_selection = WorkflowSourceSelection(
        experiment_id=experiment.id,
        dataset_name="M5 cohort",
        stage="raw",
        selected_file_ids=[17],
        asset_id="spectra",
        source_manifest_sha256="a" * 64,
        scientific_collection_sha256="b" * 64,
        dataset_view_id=view.id,
        dataset_view_sha256=view.selection_sha256,
    )
    await validate_selection(
        test_session, selection=workflow_selection, user_id=test_user.id, workflow_project_id=project.id
    )
    view.deleted_at = datetime.now(timezone.utc)
    await test_session.commit()
    with pytest.raises(HTTPException) as archived_for_new_binding:
        await validate_selection(
            test_session, selection=workflow_selection, user_id=test_user.id, workflow_project_id=project.id
        )
    assert archived_for_new_binding.value.status_code == 404
    await validate_selection(
        test_session,
        selection=workflow_selection,
        user_id=test_user.id,
        workflow_project_id=project.id,
        allow_deleted_view=True,
    )
    workflow = Workflow(user_id=test_user.id, project_id=project.id, name="M5 analysis", status="draft")
    test_session.add(workflow)
    await test_session.flush()
    node = WorkflowNode(
        workflow_id=workflow.id,
        node_id="source",
        node_type="data.collection_load",
        parameters=source_parameters(workflow_selection),
    )
    test_session.add(node)
    test_session.add(
        WorkflowDataSelectionRevision(
            workflow_id=workflow.id,
            source_node_id="source",
            revision_number=1,
            created_by=test_user.id,
            origin="data_page",
            idempotency_key="saved-view-before-delete",
            selection=workflow_selection.model_dump(mode="json"),
            graph_digest="e" * 64,
        )
    )
    await test_session.commit()
    frozen = await execution_selection_revisions(
        test_session,
        workflow_id=workflow.id,
        graph_digest="e" * 64,
        source_nodes=[node],
        user_id=test_user.id,
        workflow_project_id=project.id,
    )
    assert len(frozen) == 1
    assert frozen[0]["selection"]["dataset_view_id"] == view.id
    view.deleted_at = None
    await test_session.commit()
    state["mask"] = [True, True, True]
    with pytest.raises(HTTPException) as refusal:
        await _load_batch_dataset(test_session, test_user.id, payload)
    assert refusal.value.status_code == 409
    with pytest.raises(HTTPException) as workflow_refusal:
        await validate_selection(
            test_session, selection=workflow_selection, user_id=test_user.id, workflow_project_id=project.id
        )
    assert workflow_refusal.value.status_code == 409
