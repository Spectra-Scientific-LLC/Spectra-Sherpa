"""Saved model source links follow canonical provenance, not sheet navigation."""

from uuid import uuid4

import numpy as np
import pytest

from spectra_sherpa.app.lib.axes import SampleAxis, SpectralAxis
from spectra_sherpa.app.lib.sherpa_dataset import SherpaDataset, TargetContext
from spectra_sherpa.app.models.experiment import Experiment
from spectra_sherpa.app.models.project import Project
from spectra_sherpa.app.services.dag.executor import DAGExecutor
from spectra_sherpa.app.services.dag.executor_types import WorkflowEdge, WorkflowNode
from spectra_sherpa.app.services.dag.meta_helpers import add_processing_step
from spectra_sherpa.app.services.model_store import ModelStore, persist_model_artifact_records
from spectra_sherpa.core.execution_runtime import ExecutionRuntime


async def fitted(store, source_id, monkeypatch, *, ambiguous=False):
    monkeypatch.setattr("spectra_sherpa.app.services.dag.executor.get_default_pool", lambda: None)
    rng = np.random.default_rng(91)
    values = rng.normal(size=(12, 4))
    data = SherpaDataset(
        X=values,
        target=values[:, 0] + 2 * values[:, 1],
        feature_axis=SpectralAxis(values=np.arange(4.0) + 1000, units="nm"),
        sample_axis=SampleAxis(labels=[f"specimen-{index}" for index in range(12)]),
        target_context=TargetContext(target_type="continuous", target_names=["response"]),
    )
    if source_id is not None:
        add_processing_step(data, "data.file_load", {"experiment_id": source_id, "stage": "raw"})
        if ambiguous:
            add_processing_step(data, "spectrasherpa.experiment_dataset_read/2", {"dataset_id": source_id})
    executor = DAGExecutor(runtime=ExecutionRuntime(model_artifact_writer=store))
    executor.add_node(WorkflowNode(node_id="source", node_type="deploy.input", parameters={"stream_name": "training"}))
    executor.add_node(WorkflowNode(node_id="fit", node_type="model.fitted_pls", parameters={"n_components": 1}))
    executor.add_edge(WorkflowEdge(from_node="source", to_node="fit", from_output="default", to_input="default"))
    executor.inject_deployment_input("source", data, stream_name="training")
    await executor.execute()
    return executor.saved_artifacts[0]


@pytest.mark.asyncio
async def test_model_source_survives_missing_or_conflicting_navigation_hint(
    test_session, test_user, tmp_path, monkeypatch
):
    from spectra_sherpa.app.services import model_store

    project = Project(user_id=test_user.id, name="Source custody")
    test_session.add(project)
    await test_session.flush()
    sources = [
        Experiment(user_id=test_user.id, project_id=project.id, name=f"Source {i}", metadata_path="") for i in range(2)
    ]
    test_session.add_all(sources)
    await test_session.flush()
    store = ModelStore(tmp_path)
    monkeypatch.setattr(model_store, "get_model_store", lambda: store)
    artifacts = [await fitted(store, source.id, monkeypatch) for source in sources]
    records = await persist_model_artifact_records(
        test_session, artifacts, test_user.id, project_id=project.id, training_dataset_id=sources[0].id
    )
    await test_session.commit()
    assert [record.training_dataset_id for record in records] == [source.id for source in sources]
    for record in records:
        model_store.verify_model_artifact_storage_record(record)
    # No optional workflow-primary hint is needed for another actual fitted artifact.
    artifact = await fitted(store, sources[1].id, monkeypatch)
    (record,) = await persist_model_artifact_records(test_session, [artifact], test_user.id, project_id=project.id)
    assert record.training_dataset_id == sources[1].id


@pytest.mark.asyncio
async def test_explicit_no_source_does_not_inherit_legacy_navigation_hint(
    test_session, test_user, tmp_path, monkeypatch
):
    source = Experiment(user_id=test_user.id, name="Legacy source", metadata_path="")
    test_session.add(source)
    await test_session.flush()
    artifact = await fitted(ModelStore(tmp_path), None, monkeypatch)
    assert "training_dataset_id" in artifact and artifact["training_dataset_id"] is None
    legacy = {"artifact_uid": str(uuid4()), "artifact_dir": "unused-legacy", "model_type": "pca"}
    records = await persist_model_artifact_records(
        test_session, [artifact, legacy], test_user.id, training_dataset_id=source.id
    )
    assert [record.training_dataset_id for record in records] == [None, source.id]


@pytest.mark.asyncio
async def test_ambiguous_model_provenance_is_refused_before_file_publication(tmp_path, monkeypatch):
    store = ModelStore(tmp_path)
    with pytest.raises(ValueError, match="ambiguous"):
        await fitted(store, 1, monkeypatch, ambiguous=True)
    assert store.list_artifacts() == []


@pytest.mark.asyncio
@pytest.mark.parametrize("source", [True, 0, "1", -1, 999999])
async def test_invalid_or_inaccessible_projection_is_refused(test_session, test_user, source):
    from spectra_sherpa.app.services.dataset_access import DatasetAccessError

    with pytest.raises((ValueError, DatasetAccessError)):
        await persist_model_artifact_records(
            test_session, [{"artifact_uid": str(uuid4()), "training_dataset_id": source}], test_user.id
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("foreign", ["owner", "project"])
async def test_real_foreign_source_cannot_be_bound(test_session, test_user, foreign):
    from spectra_sherpa.app.models.user import User
    from spectra_sherpa.app.services.dataset_access import DatasetAccessError

    other = User(username="other-source-owner", is_active=True)
    project = Project(user_id=test_user.id, name="Requested project")
    test_session.add_all([other, project])
    await test_session.flush()
    source = Experiment(
        user_id=other.id if foreign == "owner" else test_user.id,
        project_id=None,
        name="Unrelated source",
        metadata_path="",
    )
    test_session.add(source)
    await test_session.flush()
    with pytest.raises(DatasetAccessError):
        await persist_model_artifact_records(
            test_session,
            [{"artifact_uid": str(uuid4()), "training_dataset_id": source.id}],
            test_user.id,
            project_id=project.id if foreign == "project" else None,
        )


@pytest.mark.asyncio
async def test_idempotent_existing_registration_does_not_renew_source_access(test_session, test_user):
    artifact = {"artifact_uid": str(uuid4()), "training_dataset_id": None}
    await persist_model_artifact_records(test_session, [artifact], test_user.id)
    await test_session.commit()
    # Existing identity is skipped; no new row or source authority is granted.
    assert (
        await persist_model_artifact_records(test_session, [{**artifact, "training_dataset_id": 999999}], test_user.id)
        == []
    )
