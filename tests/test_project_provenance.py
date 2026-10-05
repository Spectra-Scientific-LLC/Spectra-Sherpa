"""The project beacon reports explicit choices and newest generated evidence."""

from datetime import datetime, timezone
from types import SimpleNamespace

import numpy as np
import pytest

from spectra_sherpa.app.api.v1.routes.project_provenance import _run_uses_dataset_choice
from spectra_sherpa.app.models.dataset_view import DatasetView
from spectra_sherpa.app.models.execution_run import ExecutionRun
from spectra_sherpa.app.models.experiment import Experiment
from spectra_sherpa.app.models.model_artifact import ModelArtifact
from spectra_sherpa.app.models.project import Project
from spectra_sherpa.app.models.workflow import Workflow
from spectra_sherpa.app.services import model_store
from spectra_sherpa.app.services.dataset_views import receipt_sha256, selection_receipt
from spectra_sherpa.app.services.model_application import LoadedProjectDataset
from spectra_sherpa.app.services.model_store import ModelArtifactIntegrityError


@pytest.mark.asyncio
async def test_current_project_provenance_keeps_newest_failed_run_and_checks_named_dataset(
    auth_client, test_session, test_user, monkeypatch
):
    project = Project(user_id=test_user.id, name="Corn")
    test_session.add(project)
    await test_session.flush()
    experiment = Experiment(user_id=test_user.id, project_id=project.id, name="M5", metadata_path="metadata.json")
    workflow = Workflow(
        user_id=test_user.id,
        project_id=project.id,
        name="PLS",
        status="draft",
        purpose="analysis",
        integrity_hash="c" * 64,
    )
    test_session.add_all([experiment, workflow])
    await test_session.flush()

    state = {"sha": "a" * 64}

    async def load(_session, *, user_id, experiment_id, stage, file_ids, asset_id):
        assert user_id == test_user.id and experiment_id == experiment.id
        assert stage == "raw" and file_ids == [11] and asset_id is None
        return LoadedProjectDataset(
            dataset=SimpleNamespace(
                n_samples=2,
                sample_axis=SimpleNamespace(include_mask=np.asarray([True, False], dtype=bool)),
                meta={"source_collection": {"files": [{"file_name": "corn.mat", "sha256": state["sha"]}]}},
            ),
            experiment_id=experiment.id,
            experiment_name="M5",
            project_id=project.id,
            file_ids=[11],
            stage="raw",
            asset_id=None,
            source_manifest_sha256=state["sha"],
            scientific_collection_sha256="e" * 64,
        )

    for route in ("project_choices", "project_provenance"):
        monkeypatch.setattr(f"spectra_sherpa.app.api.v1.routes.{route}.load_project_dataset", load)
    loaded = await load(
        test_session, user_id=test_user.id, experiment_id=experiment.id, stage="raw", file_ids=[11], asset_id=None
    )
    receipt = selection_receipt(loaded, selected_file_ids=[11])
    view = DatasetView(
        project_id=project.id,
        experiment_id=experiment.id,
        created_by_user_id=test_user.id,
        name="M5 moisture",
        name_key="m5 moisture",
        selection=receipt,
        selection_sha256=receipt_sha256(receipt),
    )
    test_session.add(view)
    await test_session.commit()

    url = f"/api/v1/projects/{project.id}/provenance"
    initial = await auth_client.get(url)
    assert initial.status_code == 200
    assert all(item["state"] == "missing" for item in initial.json()["records"])
    choices_url = f"/api/v1/projects/{project.id}/choices"
    assert (
        await auth_client.post(
            choices_url,
            json={"kind": "dataset", "experiment_id": experiment.id, "dataset_view_id": view.id},
        )
    ).status_code == 201
    assert (
        await auth_client.post(choices_url, json={"kind": "workflow", "workflow_id": workflow.id})
    ).status_code == 201

    healthy = {item["kind"]: item for item in (await auth_client.get(url)).json()["records"]}
    assert healthy["source"]["digest"] == "a" * 64
    assert healthy["dataset"]["state"] == "healthy"
    assert healthy["dataset"]["availability"]["state"] == "healthy"
    assert healthy["workflow"]["digest"] == "c" * 64
    assert healthy["campaign"]["state"] == "missing"
    cached = {item["kind"]: item for item in (await auth_client.get(f"{url}?summary=true")).json()["records"]}
    assert cached["dataset"]["state"] == "healthy"
    state["sha"] = "b" * 64
    still_cached = {item["kind"]: item for item in (await auth_client.get(f"{url}?summary=true")).json()["records"]}
    assert still_cached["dataset"]["state"] == "healthy"
    checked = {item["kind"]: item for item in (await auth_client.get(url)).json()["records"]}
    assert checked["dataset"]["state"] == "faulty"
    state["sha"] = "a" * 64
    await auth_client.get(url)
    workflow.integrity_hash = "d" * 64
    await test_session.commit()
    changed_sheet = {item["kind"]: item for item in (await auth_client.get(url)).json()["records"]}
    assert changed_sheet["workflow"]["state"] == "faulty"
    assert changed_sheet["workflow"]["digest"] == "c" * 64
    workflow.integrity_hash = "c" * 64
    await test_session.commit()

    old = ExecutionRun(
        user_id=test_user.id,
        project_id=project.id,
        workflow_id=workflow.id,
        name="successful run",
        status="completed",
        params_snapshot={},
        results_summary={},
        executed_at=datetime.now(timezone.utc),
        evidence_completeness={"qualification": "qualified"},
    )
    new = ExecutionRun(
        user_id=test_user.id,
        project_id=project.id,
        workflow_id=workflow.id,
        name="failed run",
        status="failed",
        params_snapshot={},
        results_summary={},
        executed_at=datetime.now(timezone.utc),
        evidence_completeness={"qualification": "unverified"},
    )
    test_session.add(old)
    await test_session.flush()
    test_session.add(new)
    await test_session.commit()
    latest = {item["kind"]: item for item in (await auth_client.get(url)).json()["records"]}
    assert latest["run"]["name"] == "failed run" and latest["run"]["state"] == "faulty"

    state["sha"] = "b" * 64
    drifted = {item["kind"]: item for item in (await auth_client.get(url)).json()["records"]}
    assert drifted["dataset"]["state"] == "faulty"
    assert drifted["source"]["state"] == "faulty"

    state["sha"] = "a" * 64
    view.deleted_at = datetime.now(timezone.utc)
    await test_session.commit()
    deleted = {item["kind"]: item for item in (await auth_client.get(url)).json()["records"]}
    assert deleted["dataset"]["state"] == "faulty"
    assert deleted["dataset"]["name"] == "M5 moisture"
    assert deleted["dataset"]["record_id"] == view.id

    default = await auth_client.post(
        choices_url,
        json={"kind": "dataset", "experiment_id": experiment.id, "selected_file_ids": [11]},
    )
    assert default.status_code == 201, default.text
    current_default = {item["kind"]: item for item in (await auth_client.get(url)).json()["records"]}
    assert current_default["dataset"]["state"] == "healthy"
    assert current_default["dataset"]["availability"]["state"] == "healthy"
    assert current_default["dataset"]["dataset_view_id"] is None
    assert current_default["source"]["digest"] == "a" * 64

    completed = ExecutionRun(
        user_id=test_user.id,
        project_id=project.id,
        workflow_id=workflow.id,
        name="verified run",
        status="completed",
        integrity_hash="c" * 64,
        params_snapshot={},
        results_summary={},
        executed_at=datetime.now(timezone.utc),
        evidence_completeness={"qualification": "qualified"},
        source_metadata={
            "data_selection_revisions": [
                {
                    "selection": {
                        "experiment_id": experiment.id,
                        "stage": receipt["stage"],
                        "selected_file_ids": receipt["selected_file_ids"],
                        "asset_id": receipt["asset_id"],
                        "source_manifest_sha256": receipt["source_manifest_sha256"],
                        "collection_definition_sha256": receipt["collection_definition_sha256"],
                        "scientific_collection_sha256": receipt["scientific_collection_sha256"],
                        "target_authority": receipt["target_authority"],
                        "group_column": receipt["group_column"],
                        "dataset_view_id": None,
                        "dataset_view_sha256": None,
                    }
                }
            ]
        },
    )
    test_session.add(completed)
    await test_session.flush()
    model = ModelArtifact(
        artifact_uid="00000000-0000-4000-8000-000000000001",
        user_id=test_user.id,
        project_id=project.id,
        workflow_id=workflow.id,
        source_run_id=completed.id,
        training_dataset_id=experiment.id,
        node_id="pls-fit",
        model_type="pls",
        name="M5 PLS",
        artifact_dir="missing",
        integrity_hash="f" * 64,
        n_features=10,
        is_active=True,
    )
    test_session.add(model)
    await test_session.commit()

    def missing(_model):
        raise FileNotFoundError("artifact missing")

    monkeypatch.setattr(
        "spectra_sherpa.app.api.v1.routes.project_provenance.verify_model_artifact_storage_record", missing
    )
    missing_model = {item["kind"]: item for item in (await auth_client.get(url)).json()["records"]}
    assert missing_model["model"]["state"] == "faulty"

    def altered(_model):
        raise ModelArtifactIntegrityError("bytes changed")

    monkeypatch.setattr(
        "spectra_sherpa.app.api.v1.routes.project_provenance.verify_model_artifact_storage_record", altered
    )
    altered_model = {item["kind"]: item for item in (await auth_client.get(url)).json()["records"]}
    assert altered_model["model"]["state"] == "faulty"
    monkeypatch.setattr(
        "spectra_sherpa.app.api.v1.routes.project_provenance.verify_model_artifact_storage_record", lambda _model: None
    )
    verified_model = {item["kind"]: item for item in (await auth_client.get(url)).json()["records"]}
    assert verified_model["model"]["state"] == "healthy"
    assert verified_model["run"]["state"] == "healthy"

    batch = ExecutionRun(
        user_id=test_user.id,
        project_id=project.id,
        workflow_id=workflow.id,
        name="MP5 prediction",
        status="completed",
        run_kind="batch_inference",
        integrity_hash="c" * 64,
        succeeded_artifact_uids=[model.artifact_uid],
        params_snapshot={},
        results_summary={},
        executed_at=datetime.now(timezone.utc),
        evidence_completeness={"qualification": "qualified"},
    )
    test_session.add(batch)
    await test_session.commit()
    applied_model = {item["kind"]: item for item in (await auth_client.get(url)).json()["records"]}
    assert applied_model["model"]["state"] == "healthy"
    assert "applied by the latest batch run" in applied_model["model"]["detail"]


def test_model_training_link_rejects_other_cohort_in_same_experiment():
    digest = "a" * 64
    receipt = {
        "stage": "raw",
        "selected_file_ids": [11],
        "asset_id": None,
        "source_manifest_sha256": digest,
        "collection_definition_sha256": None,
        "scientific_collection_sha256": "b" * 64,
        "target_authority": None,
        "group_column": None,
    }
    choice = SimpleNamespace(
        selected_experiment_id=7,
        selected_dataset_view_id=42,
        selected_digest="c" * 64,
        selected_definition=receipt,
    )
    selection = {
        "experiment_id": 7,
        **receipt,
        "dataset_view_id": 43,
        "dataset_view_sha256": "d" * 64,
    }
    run = SimpleNamespace(source_metadata={"data_selection_revisions": [{"selection": selection}]})
    assert not _run_uses_dataset_choice(run, choice)
    selection["dataset_view_id"] = 42
    selection["dataset_view_sha256"] = "c" * 64
    assert _run_uses_dataset_choice(run, choice)
    selection["scientific_collection_sha256"] = "e" * 64
    assert not _run_uses_dataset_choice(run, choice)


@pytest.mark.asyncio
async def test_project_provenance_does_not_disclose_other_project(auth_client, test_session, test_user):
    response = await auth_client.get("/api/v1/projects/999999/provenance")
    assert response.status_code == 404


def test_model_storage_verifier_cross_checks_database_digest(monkeypatch):
    stored = SimpleNamespace(load=lambda _uid, verify: ({"integrity_hash": "a" * 64}, {}))
    monkeypatch.setattr(model_store, "get_model_store", lambda: stored)
    model = SimpleNamespace(artifact_uid="model-id", integrity_hash="b" * 64)
    with pytest.raises(ModelArtifactIntegrityError, match="digest contradicts"):
        model_store.verify_model_artifact_storage_record(model)
