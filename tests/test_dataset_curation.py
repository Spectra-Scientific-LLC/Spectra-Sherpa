"""Dataset correction preserves original custody and requires explicit consumer updates."""

from copy import deepcopy
from types import SimpleNamespace

import numpy as np
import pytest
from sqlalchemy import select

from spectra_sherpa.app.lib.axes import FeatureAxis, SampleAxis, SpectralAxis
from spectra_sherpa.app.lib.collection_assembly import (
    CollectionMember,
    assemble_collection,
    verified_source_observations,
)
from spectra_sherpa.app.lib.collection_definition import scientific_collection_identity
from spectra_sherpa.app.lib.sherpa_dataset import SherpaDataset
from spectra_sherpa.app.models.dataset_view import DatasetView
from spectra_sherpa.app.models.experiment import Experiment
from spectra_sherpa.app.models.project import Project
from spectra_sherpa.app.models.workflow import Workflow
from spectra_sherpa.app.models.workflow_node import WorkflowNode
from spectra_sherpa.app.schemas.workflow_data_selection import WorkflowSourceSelection
from spectra_sherpa.app.services.dataset_views import (
    curation_receipt,
    materialize_selection_receipt,
    receipt_sha256,
    selection_receipt,
    verify_selection_receipt,
)
from spectra_sherpa.app.services.model_application import LoadedProjectDataset
from spectra_sherpa.app.services.workflow_data_selections import source_parameters
from spectra_sherpa.core.execution_runtime import ResolvedExperimentCollection


def test_unlabeled_singleton_feature_table_uses_exact_source_observation_identity() -> None:
    source = SherpaDataset(
        X=np.arange(600, dtype=float).reshape(150, 4),
        feature_axis=FeatureAxis(labels=["a", "b", "c", "d"]),
        sample_axis=SampleAxis(sample_table={"Target": ["setosa"] * 50 + ["versicolor"] * 50 + ["virginica"] * 50}),
        data_role="X_features",
    )
    member = CollectionMember(source, "raw/sklearn_iris.csv", 100, "a" * 64)
    dataset = assemble_collection([member], title="Iris")
    rows = verified_source_observations(dataset)
    assert len(rows) == 150
    assert len({row["sample_id"] for row in rows}) == 150
    assert rows[0]["sample_id"] == "sklearn_iris 001"


def loaded_dataset(experiment_id=1, project_id=1):
    members = []
    for number in range(2):
        ds = SherpaDataset(
            X=np.random.default_rng(6200 + number).normal(size=(4, 6)) + number * 100,
            sample_axis=SampleAxis(
                labels=[f"file{number}-row{i}" for i in range(4)],
                include_mask=np.asarray([True, True, True, number != 0]),
                sample_table={"batch": [number] * 4},
            ),
            feature_axis=SpectralAxis(values=np.arange(6.0), units="nm"),
            data_role="X_spectra",
        )
        members.append(CollectionMember(ds, f"raw/file{number}.csv", 100, str(number + 1) * 64))
    ds = assemble_collection(members, title="Two acquisitions")
    manifest = ds.meta["source_collection"]
    manifest.update(scientific_collection_identity(manifest, None, ds))
    return LoadedProjectDataset(
        ds,
        experiment_id,
        "Two acquisitions",
        project_id,
        [1, 2],
        "raw",
        None,
        manifest["manifest_digest"],
        None,
        manifest["scientific_collection_sha256"],
    )


def base_receipt(loaded):
    return selection_receipt(loaded, selected_file_ids=[1, 2])


def test_multifile_curation_materializes_and_restore_matches_original_population():
    loaded = loaded_dataset()
    original_x = loaded.dataset.X.copy()
    original_digest = loaded.dataset.scientific_digest
    observations = verified_source_observations(loaded.dataset)
    assert observations[4]["file_name"] == "raw/file1.csv"
    assert observations[4]["source_row"] == 0
    without_evidence = deepcopy(loaded.dataset)
    without_evidence.meta.pop("source_observations")
    assert without_evidence.scientific_digest == original_digest
    parent = base_receipt(loaded)
    curated = curation_receipt(
        loaded,
        parent,
        parent_view_id=None,
        action="exclude",
        sample_ids=["file0-row1", "file1-row2"],
        reason="Acquisition fault",
    )
    assert curated["included_count"] == 5
    inspected = curation_receipt(
        loaded,
        parent,
        parent_view_id=None,
        action="exclude",
        sample_ids=["file0-row1"],
        reason="Diagnostic inspection",
        review_origin={"post_review": True, "heldout_inspected": True},
    )
    descendant = curation_receipt(
        loaded, inspected, parent_view_id=4, action="restore", sample_ids=["file0-row1"], reason="Record corrected"
    )
    assert descendant["review_context"] == {"post_review": True, "heldout_inspected": True}
    verify_selection_receipt(loaded, descendant)

    result = materialize_selection_receipt(loaded, curated).dataset
    np.testing.assert_array_equal(result.X, original_x[[0, 2, 4, 5, 7]])
    assert result.sample_axis.sample_table["batch"] == [0, 0, 1, 1, 1]
    assert all(result.sample_axis.include_mask)
    restored = curation_receipt(
        loaded,
        curated,
        parent_view_id=7,
        action="restore",
        sample_ids=["file0-row1", "file1-row2"],
        reason="Acquisition cleared",
    )
    result = materialize_selection_receipt(loaded, restored).dataset
    np.testing.assert_array_equal(result.X, original_x[[0, 1, 2, 4, 5, 6, 7]])
    assert loaded.dataset.scientific_digest == original_digest
    np.testing.assert_array_equal(loaded.dataset.X, original_x)
    assert parent["included_count"] == 7
    with pytest.raises(ValueError, match="Original source exclusions"):
        curation_receipt(loaded, restored, parent_view_id=8, action="restore", sample_ids=["file0-row3"], reason="No")
    with pytest.raises(ValueError, match="at least one"):
        curation_receipt(
            loaded,
            parent,
            parent_view_id=None,
            action="exclude",
            sample_ids=[r["sample_id"] for i, r in enumerate(observations) if i != 3],
            reason="No",
        )
    corrupted = deepcopy(curated)
    corrupted["observations"][4]["source_row"] = 1
    with pytest.raises(ValueError, match="source rows"):
        verify_selection_receipt(loaded, corrupted)


@pytest.mark.asyncio
async def test_reader_materializes_saved_view_and_sdk_without_authority_fails_closed():
    from spectra_sherpa.app.services.dag.nodes.data.loaders import ExperimentDatasetReader

    loaded = loaded_dataset()
    receipt = curation_receipt(
        loaded,
        base_receipt(loaded),
        parent_view_id=None,
        action="exclude",
        sample_ids=["file1-row2"],
        reason="Bad acquisition",
    )
    collection = ResolvedExperimentCollection(
        experiment_id=1,
        experiment_name=loaded.experiment_name,
        files=tuple(SimpleNamespace(file_id=i) for i in [1, 2]),
        preloaded_dataset=loaded.dataset,
    )

    class Resolver:
        async def resolve_experiment_collection(self, **kwargs):
            return collection

        async def resolve_dataset_view(self, **kwargs):
            assert kwargs["selection_sha256"] == receipt_sha256(receipt)
            return {"selection": receipt, "project_id": 1}

    parameters = {
        "dataset_id": 1,
        "selected_file_ids": ["1", "2"],
        "stage": "raw",
        "dataset_view_id": 2,
        "dataset_view_sha256": receipt_sha256(receipt),
    }
    result = await ExperimentDatasetReader("source", parameters, source_resolver=Resolver()).execute()
    np.testing.assert_array_equal(result["default"].X, loaded.dataset.X[[0, 1, 2, 4, 5, 7]])

    class SDKResolver:
        async def resolve_experiment_collection(self, **kwargs):
            return collection

    with pytest.raises(ValueError, match="cannot verify saved dataset"):
        await ExperimentDatasetReader("source", parameters, source_resolver=SDKResolver()).execute()


@pytest.mark.asyncio
async def test_curation_http_history_drift_dependents_and_explicit_apply(
    auth_client, test_session, test_user, monkeypatch
):
    project = Project(user_id=test_user.id, name="Curation")
    test_session.add(project)
    await test_session.flush()
    experiment = Experiment(
        user_id=test_user.id, project_id=project.id, name="Two acquisitions", metadata_path="m.json"
    )
    test_session.add(experiment)
    await test_session.flush()
    loaded = loaded_dataset(experiment.id, project.id)

    async def load(*args, **kwargs):
        return deepcopy(loaded)

    monkeypatch.setattr("spectra_sherpa.app.api.v1.routes.dataset_views.load_project_dataset", load)
    monkeypatch.setattr("spectra_sherpa.app.services.workflow_data_selections.load_project_dataset", load)
    original_selection = WorkflowSourceSelection(
        **{
            k: base_receipt(loaded)[k]
            for k in (
                "experiment_id",
                "stage",
                "selected_file_ids",
                "asset_id",
                "source_manifest_sha256",
                "collection_definition_sha256",
                "scientific_collection_sha256",
                "target_authority",
                "group_column",
            )
        },
        dataset_name=loaded.experiment_name,
    )
    workflow = Workflow(user_id=test_user.id, project_id=project.id, name="PCA analysis", purpose="analysis")
    workflow.nodes = [
        WorkflowNode(
            node_id="source",
            node_type="data.collection_load",
            parameters=source_parameters(original_selection),
            position_x=0,
            position_y=0,
        )
    ]
    test_session.add(workflow)
    await test_session.commit()
    url = f"/api/v1/experiments/{experiment.id}/dataset-views"
    source = {"stage": "raw", "selected_file_ids": [1, 2]}
    response = await auth_client.post(f"{url}/curation-context", json=source)
    assert response.status_code == 200, response.text
    context = response.json()
    assert context["rows"][3]["status"] == "source_excluded"
    request = {
        **source,
        "name": "Acquisition correction",
        "reason": "Cracked cuvette",
        "action": "exclude",
        "sample_ids": ["file1-row2"],
        "expected_selection_sha256": context["selection_sha256"],
        "expected_observations_sha256": context["observations_sha256"],
    }
    bad = await auth_client.post(f"{url}/curations", json={**request, "expected_selection_sha256": "0" * 64})
    assert bad.status_code == 409
    response = await auth_client.post(f"{url}/curations", json=request)
    assert response.status_code == 201, response.text
    view = response.json()
    await test_session.refresh(workflow.nodes[0])
    assert workflow.nodes[0].parameters == source_parameters(original_selection)
    response = await auth_client.get(f"{url}/{view['id']}/dependents")
    assert response.status_code == 200, response.text
    dependent = response.json()[0]
    assert dependent["blocked_reason"] is None
    apply = {
        key: dependent[key] for key in ("workflow_id", "source_node_id", "expected_revision", "expected_graph_digest")
    }
    # The original source-selection endpoint must enforce the same campaign/fold custody.
    for purpose, folds in [("managed_candidate_authority", None), ("analysis", {"method": "kfold"})]:
        workflow.purpose = purpose
        workflow.fold_validation_plan = folds
        await test_session.commit()
        blocked = await auth_client.put(
            f"/api/v1/workflows/{workflow.id}/data-selections/source",
            json={
                "expected_revision": None,
                "idempotency_key": "blocked-curation-apply",
                "origin": "data_page",
                "selection": dependent["selection"],
            },
        )
        assert blocked.status_code == 409, blocked.text
    workflow.purpose = "analysis"
    workflow.fold_validation_plan = None
    await test_session.commit()
    apply["idempotency_key"] = "curation-apply-1"
    stale = await auth_client.post(f"{url}/{view['id']}/apply", json={**apply, "expected_graph_digest": "0" * 64})
    assert stale.status_code == 409
    response = await auth_client.post(f"{url}/{view['id']}/apply", json=apply)
    assert response.status_code == 200, response.text
    replay = await auth_client.post(f"{url}/{view['id']}/apply", json=apply)
    assert replay.status_code == 200, replay.text
    assert replay.json()["id"] == response.json()["id"]
    await test_session.refresh(workflow.nodes[0])
    assert workflow.nodes[0].parameters["dataset_view_id"] == view["id"]
    assert (await auth_client.get(f"{url}/{view['id']}/dependents")).json() == []
    # Removing a curated binding from a campaign must also fail through the old endpoint.
    workflow.purpose = "managed_candidate_authority"
    await test_session.commit()
    blocked = await auth_client.put(
        f"/api/v1/workflows/{workflow.id}/data-selections/source",
        json={
            "expected_revision": response.json()["revision_number"],
            "idempotency_key": "blocked-remove-curation",
            "origin": "data_page",
            "selection": original_selection.model_dump(mode="json"),
        },
    )
    assert blocked.status_code == 409, blocked.text
    from fastapi import HTTPException

    from spectra_sherpa.app.services.sample_review_custody import require_review_filters_preserved

    with pytest.raises(HTTPException, match="Campaign seeds"):
        await require_review_filters_preserved(test_session, workflow.id, [], [])
    workflow.purpose = "analysis"
    await test_session.commit()

    child_source = {"parent_view_id": view["id"], "parent_sha256": view["selection_sha256"]}
    context = (await auth_client.post(f"{url}/curation-context", json=child_source)).json()
    restore = {
        **child_source,
        "name": "Restored acquisitions",
        "reason": "Cuvette record corrected",
        "action": "restore",
        "sample_ids": ["file1-row2"],
        "expected_selection_sha256": context["selection_sha256"],
        "expected_observations_sha256": context["observations_sha256"],
    }
    response = await auth_client.post(f"{url}/curations", json=restore)
    assert response.status_code == 201, response.text
    child = response.json()
    assert child["selection"]["included_count"] == 7
    await auth_client.delete(f"{url}/{view['id']}")
    assert (await auth_client.get(f"{url}/{child['id']}")).status_code == 200
    old = await test_session.scalar(select(DatasetView).where(DatasetView.id == view["id"]))
    assert old.selection == view["selection"]
    # Batch uses the identical canonical materialization authority.
    from spectra_sherpa.app.api.v1.routes.runs import ArtifactBatchRunRequest, RunDatasetRef, _load_batch_dataset

    monkeypatch.setattr("spectra_sherpa.app.api.v1.routes.runs.load_project_dataset", load)
    payload = ArtifactBatchRunRequest(
        artifact_uids=["model-1"],
        dataset=RunDatasetRef(experiment_id=experiment.id),
        dataset_view_id=child["id"],
        scope="all",
    )
    batch_loaded, _ = await _load_batch_dataset(test_session, test_user.id, payload)
    np.testing.assert_array_equal(batch_loaded.dataset.X, loaded.dataset.X[[0, 1, 2, 4, 5, 6, 7]])


def test_large_collection_omits_bounded_review_receipt():
    ds = SherpaDataset(
        X=np.zeros((5001, 2)),
        sample_axis=SampleAxis(labels=[f"s{i}" for i in range(5001)]),
        feature_axis=SpectralAxis(values=np.arange(2.0), units="nm"),
    )
    result = assemble_collection([CollectionMember(ds, "large.csv", 100, "a" * 64)], title="Large")
    assert result.shape == (5001, 2)
    assert result.meta["source_observations"] is None
    with pytest.raises(ValueError, match="5,000"):
        verified_source_observations(result)


@pytest.mark.asyncio
async def test_diagnostic_origin_uses_server_roles_and_refuses_changed_run(monkeypatch):
    from fastapi import HTTPException

    from spectra_sherpa.app.api.v1.routes.dataset_views import CurationDecision, _verified_review_origin

    loaded = loaded_dataset()
    parent = base_receipt(loaded)
    rows = verified_source_observations(loaded.dataset)
    data = CurationDecision(
        name="Reviewed",
        reason="Acquisition",
        action="exclude",
        sample_ids=["file1-row2"],
        expected_selection_sha256=receipt_sha256(parent),
        expected_observations_sha256=receipt_sha256({"rows": rows}),
        review_origin={"workflow_id": 1, "run_id": 9, "node_id": "pls", "revision": 2},
    )
    review = {
        "run_id": 9,
        "revision": 2,
        "stale": False,
        "rows": [{"id": "file1-row2", "role": "held_out_test"}],
        "dataset_curation_source": {**parent, "observations": rows},
    }

    async def get_review(*args):
        return review

    monkeypatch.setattr("spectra_sherpa.app.api.v1.routes.workflows.sample_review.get_sample_review", get_review)
    origin = await _verified_review_origin(None, None, 1, data, parent, rows)
    assert origin["selected_roles"] == {"file1-row2": "held_out_test"}
    assert origin["heldout_inspected"] is True
    review["run_id"] = 10
    with pytest.raises(HTTPException, match="review changed"):
        await _verified_review_origin(None, None, 1, data, parent, rows)


@pytest.mark.asyncio
async def test_multifile_review_requires_captured_native_rows():
    import importlib.util
    from pathlib import Path

    spec = importlib.util.spec_from_file_location(
        "pca_curation_reference", Path(__file__).with_name("test_pca_sample_review.py")
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    run = module.run

    loaded = loaded_dataset()
    ds = loaded.dataset
    # The canonical review operates on the admitted population after source inclusion.
    restored = curation_receipt(
        loaded,
        base_receipt(loaded),
        parent_view_id=None,
        action="exclude",
        sample_ids=["file1-row2"],
        reason="Bad acquisition",
    )
    ds = materialize_selection_receipt(loaded, restored).dataset
    receipt = await run(ds)
    assert [row["id"] for row in receipt["rows"]] == list(ds.sample_axis.labels)
    ds.meta.pop("source_observations")
    with pytest.raises(ValueError, match="row identity"):
        await run(ds)


@pytest.mark.parametrize("member_count", [1, 2])
def test_row_custody_is_budgeted_before_receipt_allocation(monkeypatch, member_count):
    from spectra_sherpa.app.lib import collection_assembly as assembly

    members = [
        CollectionMember(
            SherpaDataset(
                X=np.zeros((8, 6)),
                sample_axis=SampleAxis(labels=[f"member-{i}-row-{j}" for j in range(8)]),
                feature_axis=SpectralAxis(values=np.arange(6.0), units="nm"),
                data_role="X_spectra",
            ),
            f"member-{i}.csv",
            384,
            str(i + 1) * 64,
        )
        for i in range(member_count)
    ]
    reserved = assembly._source_observation_retained_bytes(members)
    actual = assembly._retained_state_footprint([assembly.source_observations(members)])[1]
    assert reserved >= actual
    _, projected = assembly.collection_retained_footprint(members)
    monkeypatch.setattr(assembly, "MAX_COLLECTION_RETAINED_BYTES", projected - 1)
    monkeypatch.setattr(
        assembly, "source_observations", lambda _: pytest.fail("receipt allocated before memory admission")
    )
    with pytest.raises(ValueError, match="retained-data limit"):
        assembly.assemble_collection(members, title="Refused before row receipt")
