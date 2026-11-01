"""Fresh catalog materialization owns typed observation IDs, never specimen claims."""

from __future__ import annotations

import hashlib
import io

import numpy as np
import pandas as pd
import pytest
from sklearn import datasets
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from spectra_sherpa.app.db import session as db_session
from spectra_sherpa.app.lib.export_artifact import build_export_artifact
from spectra_sherpa.app.lib.io import load_csv_as_sherpa
from spectra_sherpa.app.lib.sample_identity import sample_ids
from spectra_sherpa.app.lib.sklearn_info import _LOADERS
from spectra_sherpa.app.models.execution_run import ExecutionRun
from spectra_sherpa.app.models.experiment_file import ExperimentFile
from spectra_sherpa.app.models.model_artifact import ModelArtifact
from spectra_sherpa.app.schemas.workflow_data_selection import WorkflowSourceSelection
from spectra_sherpa.app.services.dag.nodes.data.transforms import FilterSamplesNode
from spectra_sherpa.app.services.dag.nodes.modeling.pca_nodes import PCANode
from spectra_sherpa.app.services.dag.nodes.preprocessing.scale_node import ScaleNode
from spectra_sherpa.app.services.experiments import catalog_table_revision, experiment_dir
from spectra_sherpa.app.services.model_application import load_project_dataset
from spectra_sherpa.app.services.pca_review_evidence import sample_ids as review_sample_ids
from spectra_sherpa.app.services.workflow_data_selections import source_parameters


async def _experiment(client, project_id):
    response = await client.post("/api/v1/experiments", json={"name": "Catalog", "project_id": project_id})
    assert response.status_code == 201, response.text
    return response.json()["id"]


async def _import(client, experiment_id, name):
    response = await client.post(
        f"/api/v1/experiments/{experiment_id}/import-reference",
        json={"datasets": [{"source": "sklearn", "name": name}]},
    )
    assert response.status_code == 201, response.text
    assert response.json()["imported"] == 1
    return response.json()["files"][0]["id"]


@pytest.mark.asyncio
@pytest.mark.parametrize("name", ["wine", "iris", "breast_cancer"])
async def test_catalog_import_collection_fit_and_saved_diagnostics(
    auth_client, test_session, test_user, monkeypatch, tmp_path, name
):
    """Normal HTTP import/execute/read, real source bindings and retained model custody."""
    monkeypatch.setattr(db_session, "async_session", async_sessionmaker(test_session.bind, expire_on_commit=False))
    project = await auth_client.post("/api/v1/projects", json={"name": "Catalog observation identity"})
    assert project.status_code == 201, project.text
    pid = project.json()["id"]
    eid = await _experiment(auth_client, pid)
    fid = await _import(auth_client, eid, name)
    file = await test_session.get(ExperimentFile, fid)
    assert file.experiment_id == eid
    path = experiment_dir(eid) / file.file_path
    original_bytes = path.read_bytes()
    original_sha = hashlib.sha256(original_bytes).hexdigest()
    reference = getattr(datasets, _LOADERS[name])()
    expected_targets = np.asarray([reference.target_names[i] for i in reference.target])
    revision_table = pd.DataFrame(reference.data, columns=reference.feature_names)
    revision_table["target"] = expected_targets
    revision = catalog_table_revision(revision_table)

    # Repeated independent reads must recover IDs from persisted typed metadata.
    direct = load_csv_as_sherpa(path)
    ids = sample_ids(direct)
    assert ids is not None and len(ids) == len(set(ids)) == len(reference.data)
    assert ids == [f"sklearn:{name}:{revision}:row:{index + 1}" for index in range(len(reference.data))]
    assert sample_ids(load_csv_as_sherpa(path)) == ids
    np.testing.assert_array_equal(direct.X, reference.data)
    np.testing.assert_array_equal(direct.target, expected_targets)
    assert direct.feature_axis.labels == list(reference.feature_names)
    display_labels = [f"Sample {index + 1}" for index in range(len(reference.data))]
    assert direct.sample_axis.labels == display_labels
    assert set(display_labels).isdisjoint(ids)
    assert "specimen_id" not in direct.sample_axis.sample_table
    assert direct.target_context.class_names == sorted(reference.target_names)
    assert direct.target_context.target_type == "categorical"
    assert direct.target_context.target_names == ["target"]

    # Existing typed-axis transforms and portable export retain identities,
    # independent of editable display labels, filtering and row order.
    exported = build_export_artifact(direct, filename="roundtrip.csv", format="portable_csv")
    roundtrip = tmp_path / "roundtrip.csv"
    roundtrip.write_text(exported["content"], encoding="utf-8")
    recovered = load_csv_as_sherpa(roundtrip)
    assert sample_ids(recovered) == ids
    assert recovered.sample_axis.labels == display_labels
    np.testing.assert_array_equal(recovered.X, direct.X)
    np.testing.assert_array_equal(recovered.target, direct.target)
    renamed_axis = recovered.sample_axis
    renamed_axis.labels = [f"Renamed {index}" for index in range(len(ids))]
    recovered.sample_axis = renamed_axis
    assert recovered.sample_axis.labels == renamed_axis.labels
    assert sample_ids(recovered) == ids
    # Display labels do not change the exact PCA fitted state or its digest.
    unlabeled = direct.copy()
    unlabeled_axis = unlabeled.sample_axis
    unlabeled_axis.labels = None
    unlabeled.sample_axis = unlabeled_axis
    assert unlabeled.sample_axis.labels is None
    pca = PCANode("label-invariance", {"n_components": "3", "standardized": True})
    fitted = pca.fit_fitted_state(direct)
    assert fitted == pca.fit_fitted_state(unlabeled) == pca.fit_fitted_state(recovered)
    order = np.array([len(ids) - 1, 0, 2])
    reordered = recovered[order]
    assert sample_ids(reordered) == [ids[index] for index in order]
    np.testing.assert_array_equal(reordered.X, direct.X[order])
    np.testing.assert_array_equal(reordered.target, direct.target[order])
    scaled = (await ScaleNode("scale", {"method": "autoscale"}).execute(input_data=recovered)).outputs["default"]
    assert sample_ids(scaled) == ids
    filtered = await FilterSamplesNode(
        "filter",
        {"field": "sample_table", "sample_table_column": "sample_id", "filter_values": [ids[1]], "invert": True},
    ).execute(X=recovered)
    assert sample_ids(filtered["default"]) == ids[:1] + ids[2:]
    np.testing.assert_array_equal(filtered["default"].X, np.delete(direct.X, 1, axis=0))

    loaded = await load_project_dataset(test_session, user_id=test_user.id, experiment_id=eid)
    assert loaded.file_ids == [fid]
    assert loaded.dataset.meta["source_collection"]["files"][0]["sha256"] == original_sha
    assert sample_ids(loaded.dataset) == ids
    assert loaded.dataset.sample_axis.labels == display_labels
    np.testing.assert_array_equal(loaded.dataset.X, reference.data)
    np.testing.assert_array_equal(loaded.dataset.target, expected_targets)
    binding = source_parameters(
        WorkflowSourceSelection(
            experiment_id=eid,
            dataset_name="Catalog",
            stage="raw",
            selected_file_ids=loaded.file_ids,
            source_manifest_sha256=loaded.source_manifest_sha256,
            collection_definition_sha256=loaded.collection_definition_sha256,
            scientific_collection_sha256=loaded.scientific_collection_sha256,
            asset_id=loaded.asset_id,
        )
    )
    graph = {
        "nodes": [
            {"node_id": "source", "node_type": "data.collection_load", "parameters": binding},
            {"node_id": "pca", "node_type": "model.pca", "parameters": {"n_components": "3", "standardized": True}},
        ],
        "edges": [{"from_node_id": "source", "to_node_id": "pca", "from_output": "default", "to_input": "default"}],
    }
    workflow = await auth_client.post("/api/v1/workflows", json={"name": "Catalog PCA", "project_id": pid, **graph})
    assert workflow.status_code == 201, workflow.text
    wid = workflow.json()["id"]
    executed = await auth_client.post(f"/api/v1/workflows/{wid}/execute", json={})
    assert executed.status_code == 200, executed.text
    assert executed.json()["status"] == "completed", executed.text
    run = await test_session.scalar(select(ExecutionRun).where(ExecutionRun.workflow_id == wid))
    model = await test_session.scalar(select(ModelArtifact).where(ModelArtifact.source_run_id == run.id))
    assert model.artifact_uid in run.produced_artifact_uids
    assert model.project_id == pid and model.node_id == "pca"
    endpoint = f"/api/v1/models/{model.artifact_uid}/diagnostics?project_id={pid}"
    saved = await auth_client.get(endpoint)
    assert saved.status_code == 200, saved.text
    receipt = saved.json()["receipt"]
    assert receipt["model_kind"] == "pca"
    assert receipt["identity_field"] == "sample_id"
    assert [row["id"] for row in receipt["rows"]] == ids
    assert [row["display_label"] for row in receipt["rows"]] == display_labels
    assert receipt["n_calibration"] == len(reference.data)
    assert saved.json()["run_id"] == run.id
    assert (await auth_client.get(endpoint)).json() == saved.json()
    reloaded = await load_project_dataset(test_session, user_id=test_user.id, experiment_id=eid)
    assert reloaded.source_manifest_sha256 == loaded.source_manifest_sha256
    assert reloaded.scientific_collection_sha256 == loaded.scientific_collection_sha256
    assert sample_ids(reloaded.dataset) == ids
    assert reloaded.dataset.sample_axis.labels == display_labels
    assert path.read_bytes() == original_bytes
    assert hashlib.sha256(path.read_bytes()).hexdigest() == original_sha

    # The same catalog materialized afresh has the same observation identities;
    # they denote catalog rows, not new specimens or acquisition replicates.
    second_eid = await _experiment(auth_client, pid)
    second_fid = await _import(auth_client, second_eid, name)
    second = await test_session.get(ExperimentFile, second_fid)
    assert (experiment_dir(second_eid) / second.file_path).read_bytes() == original_bytes


@pytest.mark.asyncio
async def test_existing_untyped_catalog_bytes_and_binding_are_not_upgraded(auth_client, test_session, test_user):
    user_id = test_user.id
    project = await auth_client.post("/api/v1/projects", json={"name": "Preserved old materialization"})
    pid = project.json()["id"]
    eid = await _experiment(auth_client, pid)
    wine = datasets.load_wine()
    frame = pd.DataFrame(wine.data, columns=wine.feature_names)
    frame["target"] = [wine.target_names[i] for i in wine.target]
    old_bytes = frame.to_csv(index=False).encode()
    uploaded = await auth_client.post(
        f"/api/v1/experiments/{eid}/files",
        data={"stage": "raw"},
        files={"file": ("sklearn_wine.csv", old_bytes, "text/csv")},
    )
    assert uploaded.status_code == 201, uploaded.text
    before = await load_project_dataset(test_session, user_id=user_id, experiment_id=eid)
    assert sample_ids(before.dataset) is None
    blocked = await auth_client.post(
        f"/api/v1/experiments/{eid}/import-reference", json={"datasets": [{"source": "sklearn", "name": "wine"}]}
    )
    assert blocked.status_code == 400, blocked.text
    # The real rollback expires ORM instances; this test's auth dependency
    # reuses its actor whereas normal HTTP requests load a fresh actor.
    await test_session.refresh(test_user)
    fresh = await _experiment(auth_client, pid)
    await _import(auth_client, fresh, "wine")
    after = await load_project_dataset(test_session, user_id=user_id, experiment_id=eid)
    assert sample_ids(after.dataset) is None
    assert after.source_manifest_sha256 == before.source_manifest_sha256
    assert after.scientific_collection_sha256 == before.scientific_collection_sha256
    assert (experiment_dir(eid) / "raw/sklearn_wine.csv").read_bytes() == old_bytes
    np.testing.assert_array_equal(
        after.dataset.X, pd.read_csv(io.BytesIO(old_bytes)).select_dtypes("number").to_numpy()
    )


@pytest.mark.parametrize(
    "column,values",
    [
        (None, None),
        ("sample_id", ["first", "second", "third"]),
        ("sample_meta.sample_id", ["repeated", "repeated", "third"]),
        ("sample_meta.sample_id", ["first", "", "third"]),
        ("sample_meta.sample_id", ["first", " second ", "third"]),
    ],
)
def test_review_identity_guard_still_refuses_untyped_or_invalid_csv(tmp_path, column, values):
    frame = pd.DataFrame({"feature": [1.0, 2.0, 3.0], "target": ["a", "b", "a"]})
    if column:
        frame.insert(0, column, values)
    path = tmp_path / "invalid.csv"
    frame.to_csv(path, index=False)
    ds = load_csv_as_sherpa(path, data_role="X_features", target_column="target", target_type="categorical")
    with pytest.raises(ValueError, match="exact.*unique|unique.*exact"):
        review_sample_ids(ds)


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["row_order", "feature", "target"])
async def test_changed_catalog_revision_does_not_reuse_observation_ids(auth_client, test_session, monkeypatch, change):
    project = await auth_client.post("/api/v1/projects", json={"name": "Catalog revision"})
    pid = project.json()["id"]
    eid = await _experiment(auth_client, pid)
    fid = await _import(auth_client, eid, "wine")
    file = await test_session.get(ExperimentFile, fid)
    path = experiment_dir(eid) / file.file_path
    before = path.read_bytes()
    original_ids = sample_ids(load_csv_as_sherpa(path))
    changed = datasets.load_wine()
    if change == "row_order":
        changed.data = changed.data[::-1].copy()
        changed.target = changed.target[::-1].copy()
    elif change == "feature":
        changed.data[0, 0] += 1.0
    else:
        changed.target[0] = (changed.target[0] + 1) % len(changed.target_names)
    monkeypatch.setattr(datasets, "load_wine", lambda: changed)
    new_eid = await _experiment(auth_client, pid)
    new_fid = await _import(auth_client, new_eid, "wine")
    new_file = await test_session.get(ExperimentFile, new_fid)
    new = load_csv_as_sherpa(experiment_dir(new_eid) / new_file.file_path)
    assert set(original_ids).isdisjoint(sample_ids(new))
    np.testing.assert_array_equal(new.X, changed.data)
    np.testing.assert_array_equal(new.target, [changed.target_names[i] for i in changed.target])
    assert path.read_bytes() == before
    assert sample_ids(load_csv_as_sherpa(path)) == original_ids
