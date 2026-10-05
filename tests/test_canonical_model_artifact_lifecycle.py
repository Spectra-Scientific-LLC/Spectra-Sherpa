"""Product-level artifact coverage: a successful fit must survive its executor.

This is intentionally a closed census: adding a canonical model requires a
fixture and an explicit new-observation versus cohort-only disposition.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pytest

import spectra_sherpa.app.services.dag.nodes  # noqa: F401
from spectra_sherpa.app.lib.sherpa_dataset import SherpaDataset, SpectralAxis
from spectra_sherpa.app.services.dag.executor import DAGExecutor
from spectra_sherpa.app.services.dag.node_base import NodeResult, node_registry
from spectra_sherpa.app.services.dag.nodes.modeling.load_apply_node import _apply_model_artifact
from spectra_sherpa.app.services.execution_runtime import ApplicationModelArtifactReplay
from spectra_sherpa.app.services.model_store import ModelStore, persist_model_artifact_records
from spectra_sherpa.app.types import type_registry
from spectra_sherpa.core.execution_runtime import ExecutionRuntime

# All model-producing canonical operations, including retired-but-loadable
# identities. Preprocessing, selection and transfer state belongs to the
# pipeline, not to the standalone prediction-model list.
MODEL_CASES = {
    "model.fitted_pls": {"n_components": 2},
    "model.fitted_pcr": {"n_components": 2},
    "model.fitted_svr": {},
    "model.fitted_linear_regression": {},
    "model.pcr": {"n_components": 2},
    "model.svr": {},
    "model.linear_regression": {},
    "classification.knn": {"n_neighbors": 3},
    "classification.plsda": {"n_components": 2},
    "classification.simca": {"n_components": 2},
    "model.pca": {"n_components": "2"},
    "model.ica": {"n_components": 2, "max_iter": 1000},
    "model.nmf": {"n_components": 2, "max_iter": 1000},
    "model.mcr_als": {"n_components": 2, "max_iter": 500},
    "model.parafac": {"n_components": 2},
    "model.kmeans": {"n_clusters": 2},
    "model.hca": {"n_clusters": 2},
    "model.dbscan": {"eps": 2.0, "min_samples": 3},
}
COHORT_ONLY = {"model.hca", "model.dbscan"}
PIPELINE_STATE = {
    "selection.cars",
    "selection.ipls",
    "selection.mcuve",
    "selection.spa",
    "selection.stability",
    "preprocess.emsc",
    "preprocess.msc",
    "preprocess.osc",
    "preprocess.scale",
    "transfer.ds",
    "transfer.pds",
    "transfer.sws",
}


@pytest.fixture(autouse=True)
def types():
    if not type_registry.is_loaded:
        type_registry.load(Path(__file__).resolve().parents[1] / "src/spectra_sherpa/app/types")


def sample(node_type):
    rng = np.random.default_rng(431)
    data = SherpaDataset(
        X=rng.uniform(1, 3, (24, 6)),
        feature_axis=SpectralAxis(values=np.arange(6.0) + 1000, units="nm", title="Wavelength"),
        target=rng.normal(size=24),
    )
    if node_type.startswith("classification."):
        data.target = np.array(["A"] * 12 + ["B"] * 12)
    if node_type == "model.parafac":
        from tests.test_parafac_node import _tensor_dataset

        data = _tensor_dataset()
    return data


def test_registry_has_no_unqualified_model_artifact_lifecycle():
    producers = set()
    for meta in node_registry.list_nodes():
        contract = meta.resolved_execution_contract()
        if contract and contract.payload["lifecycle_kind"] in {"fitted_model", "fitted_transform"}:
            producers.add(meta.node_type)
    assert (
        producers == set(MODEL_CASES) | PIPELINE_STATE
    ), "Every new canonical model needs the complete saved-artifact journey fixture"


@pytest.mark.asyncio
@pytest.mark.parametrize("node_type", MODEL_CASES)
async def test_fit_persist_reopen_list_and_apply(node_type, tmp_path, test_session, test_user, monkeypatch):
    from spectra_sherpa.app.api.v1.routes.deploy import list_applications
    from spectra_sherpa.app.core.config import app_config
    from spectra_sherpa.app.models.execution_run import ExecutionRun
    from spectra_sherpa.app.models.project import Project
    from spectra_sherpa.app.models.workflow import Workflow
    from spectra_sherpa.app.models.workflow_version import WorkflowVersion
    from spectra_sherpa.app.services import model_store
    from spectra_sherpa.app.services.deployment_binding import resolve_deployment_binding

    monkeypatch.setattr(app_config, "mode", "local")
    store = ModelStore(tmp_path)
    monkeypatch.setattr(model_store, "get_model_store", lambda: store)
    from spectra_sherpa.app.models.experiment import Experiment
    from spectra_sherpa.app.services.dag.meta_helpers import add_processing_step

    if node_type == "model.mcr_als":
        pytest.importorskip("spectrochempy", reason="MCR-ALS requires the optional SCP adapter")

    project = Project(user_id=test_user.id, name="Artifact lifecycle")
    test_session.add(project)
    await test_session.flush()
    experiment = Experiment(user_id=test_user.id, project_id=project.id, name="Synthetic source", metadata_path="")
    test_session.add(experiment)
    await test_session.flush()
    data = sample(node_type)
    add_processing_step(data, "data.file_load", {"experiment_id": experiment.id, "stage": "raw"})
    node = node_registry.create_node(node_type, "fit", MODEL_CASES[node_type])
    result = await node.execute(data)
    outputs = result.outputs if isinstance(result, NodeResult) else result
    assert "_model_artifact" in outputs, f"{node_type} finished but did not produce a persistent model"
    executor = DAGExecutor(runtime=ExecutionRuntime(model_artifact_writer=store))
    executor.results["fit"] = outputs
    executor._process_model_artifact("fit")
    assert len(executor.saved_artifacts) == 1
    uid = executor.saved_artifacts[0]["artifact_uid"]
    assert outputs["model_id"] == uid
    workflow = Workflow(user_id=test_user.id, project_id=project.id, name=node_type)
    test_session.add(workflow)
    await test_session.flush()
    version = WorkflowVersion(workflow_id=workflow.id, version_number=1, created_by=test_user.id, snapshot={})
    test_session.add(version)
    await test_session.flush()
    run = ExecutionRun(
        user_id=test_user.id,
        project_id=project.id,
        workflow_id=workflow.id,
        workflow_version_id=version.id,
        name="Fitted run",
        status="completed",
        executed_at=datetime.now(timezone.utc),
        produced_artifact_uids=[uid],
        params_snapshot={"fit": node.parameters},
        results_summary={},
        diagnostics={},
        node_statuses={"fit": "completed"},
    )
    test_session.add(run)
    await test_session.flush()
    records = await persist_model_artifact_records(
        test_session,
        executor.saved_artifacts,
        user_id=test_user.id,
        project_id=project.id,
        workflow_id=workflow.id,
        workflow_version_id=version.id,
        source_run_id=run.id,
        training_dataset_id=experiment.id,
    )
    await test_session.commit()
    await test_session.refresh(records[0])
    assert records[0].source_run_id == run.id
    assert records[0].artifact_uid in run.produced_artifact_uids
    apps = await list_applications(project.id, test_session, test_user)
    if node_type in COHORT_ONLY:
        assert apps == []
        with pytest.raises(ValueError, match="does not predict"):
            await resolve_deployment_binding(
                test_session, user_id=test_user.id, workflow_id=workflow.id, artifact_uid=uid
            )
        return
    assert len(apps) == 1 and apps[0]["model_artifact_uid"] == uid
    assert apps[0]["source_run_id"] == run.id
    assert (await list_applications(project.id, test_session, test_user))[0]["handle"] == apps[0]["handle"]
    binding = await resolve_deployment_binding(
        test_session, user_id=test_user.id, workflow_id=workflow.id, artifact_uid=uid
    )
    assert binding.artifact.artifact_uid == uid
    # Reopen from a new store, never reuse the in-memory model. Application may
    # not call fit; predictions need no responses from incoming observations.
    manifest, arrays = ModelStore(tmp_path).load(uid)
    incoming = data.copy()
    incoming.target = None

    def no_refit(*args, **kwargs):
        raise AssertionError("Applying a saved artifact must not fit a model")

    monkeypatch.setattr(type(node), "fit_fitted_state", no_refit)
    replay = _apply_model_artifact(manifest, arrays, incoming, model_id=uid, replay=ApplicationModelArtifactReplay())
    assert np.isfinite(np.asarray(replay["result"])).all()
    expected = outputs.get("default")
    if node_type.startswith("model.fitted_"):
        np.testing.assert_allclose(replay["result"], expected, rtol=1e-12, atol=1e-12)
    if node_type == "model.kmeans":
        np.testing.assert_array_equal(replay["labels"], outputs["labels"])

    # Exercise the real public application consumer, including its scientific
    # interpretation. A lower-level adapter result alone is not acceptance.
    from spectra_sherpa.app.services import model_application

    monkeypatch.setattr(model_application, "get_model_store", lambda: ModelStore(tmp_path))
    applied = await model_application.apply_model_to_dataset(uid, incoming)
    assert applied["artifact_uid"] == uid
    assert applied["n_samples"] == len(incoming.X)
    assert applied["feature_indices"] == list(range(incoming.X.shape[-1]))
    if node_type == "model.kmeans":
        assert applied["output_type"] == "clustering"
        assert applied["cluster_assignments"] == outputs["labels"]
        assert "probabilities" not in applied
        assert "classification_output_semantics" not in applied
        assert applied["metrics"] is None
    elif replay["metadata"]["output_type"] == "decomposition":
        np.testing.assert_allclose(applied["transformed"], replay["result"], atol=1e-12)
    elif replay["metadata"]["output_type"] == "regression":
        np.testing.assert_allclose(applied["predictions"], replay["result"], atol=1e-12)
    else:
        assert applied["predictions"] == replay["labels"]


@pytest.mark.asyncio
async def test_native_artifact_rejects_changed_input_authority_and_corrupt_state(tmp_path):
    node = node_registry.create_node("model.fitted_pls", "fit", {"n_components": 2})
    data = sample("model.fitted_pls")
    outputs = (await node.execute(data)).outputs
    store = ModelStore(tmp_path)
    artifact = outputs["_model_artifact"]
    store.save("native", artifact["metadata"], artifact["arrays"])
    manifest, arrays = store.load("native")
    data.units = "counts"
    with pytest.raises(ValueError, match="input authority"):
        _apply_model_artifact(manifest, arrays, data, model_id="native", replay=ApplicationModelArtifactReplay())
    data.units = None
    payload = json.loads(arrays["native_fitted_state"].tobytes())
    payload["serializer"] = "invented"
    arrays["native_fitted_state"] = np.frombuffer(json.dumps(payload).encode(), dtype=np.uint8)
    with pytest.raises(ValueError, match="contract"):
        _apply_model_artifact(manifest, arrays, data, model_id="native", replay=ApplicationModelArtifactReplay())


@pytest.mark.asyncio
async def test_http_execution_automatically_registers_pls_for_runs_and_deploy(
    auth_client, test_engine, test_session, test_user, monkeypatch
):
    import io

    from sqlalchemy.ext.asyncio import async_sessionmaker

    from spectra_sherpa.app.db import session as db_session

    monkeypatch.setattr(db_session, "async_session", async_sessionmaker(test_engine, expire_on_commit=False))
    from spectra_sherpa.app.core.config import app_config

    monkeypatch.setattr(app_config, "mode", "local")

    async def post(path, **kwargs):
        response = await auth_client.post("/api/v1" + path, **kwargs)
        assert response.status_code < 300, response.text
        return response.json()

    project = await post("/projects", json={"name": "Automatic fitted artifact"})
    experiment = await post("/experiments", json={"name": "Synthetic regression", "project_id": project["id"]})
    data = sample("model.fitted_pls")
    import hashlib

    buffer = io.StringIO()
    np.savetxt(
        buffer,
        np.column_stack([data.X, data.target]),
        delimiter=",",
        header=",".join([*(f"v{i}" for i in range(data.X.shape[1])), "response"]),
        comments="",
    )
    content = buffer.getvalue().encode()
    uploaded = await post(
        f"/experiments/{experiment['id']}/files",
        data={"stage": "raw"},
        files={"file": ("calibration.csv", content, "text/csv")},
    )
    nodes = [
        {
            "node_id": "X",
            "node_type": "data.file_load",
            "parameters": {
                "experiment_id": experiment["id"],
                "file_id": uploaded["id"],
                "stage": "raw",
                "target_authority": {
                    "column": "response",
                    "target_type": "continuous",
                    "units": None,
                    "source_digest": hashlib.sha256(content).hexdigest(),
                },
            },
            "position_x": 0,
            "position_y": 0,
        },
        {
            "node_id": "fit",
            "node_type": "model.fitted_pls",
            "parameters": {"n_components": 2},
            "position_x": 200,
            "position_y": 0,
        },
    ]
    workflow = await post(
        "/workflows",
        json={
            "name": "PLS persistence",
            "project_id": project["id"],
            "nodes": nodes,
            "edges": [
                {"from_node_id": "X", "to_node_id": "fit", "from_output": output, "to_input": port}
                for output, port in [("default", "default"), ("target", "y")]
            ],
        },
    )
    execution = await post(f"/workflows/{workflow['id']}/execute", json={})
    assert execution["status"] == "completed", execution
    response = await auth_client.get(f"/api/v1/runs/{execution['run_id']}", params={"project_id": project["id"]})
    assert response.status_code == 200, response.text
    run = response.json()
    assert run["run_kind"] == "training"
    assert len(run["produced_artifact_uids"]) == 1
    uid = run["produced_artifact_uids"][0]
    response = await auth_client.get("/api/v1/models", params={"project_id": project["id"]})
    assert response.status_code == 200, response.text
    assert [model["artifact_uid"] for model in response.json()] == [uid]
    response = await auth_client.get("/api/v1/deploy/applications", params={"project_id": project["id"]})
    assert response.status_code == 200, response.text
    assert response.json()[0]["model_artifact_uid"] == uid
    assert response.json()[0]["source_run_id"] == run["id"]

    from spectra_sherpa.app.services.deployment_binding import resolve_deployment_binding

    binding = await resolve_deployment_binding(
        test_session, user_id=test_user.id, workflow_id=workflow["id"], artifact_uid=uid
    )
    assert binding.artifact.source_run_id == run["id"]


@pytest.mark.asyncio
async def test_saved_native_model_replays_fitted_scaling_without_refitting(tmp_path, monkeypatch):
    data = sample("model.fitted_pls")
    scale = node_registry.create_node("preprocess.scale", "scale", {"method": "autoscale"})
    scaled = (await scale.execute(data)).outputs["default"]
    node = node_registry.create_node("model.fitted_pls", "fit", {"n_components": 2})
    outputs = (await node.execute(scaled)).outputs
    artifact = outputs["_model_artifact"]
    store = ModelStore(tmp_path)
    store.save("scaled", artifact["metadata"], artifact["arrays"])
    manifest, arrays = ModelStore(tmp_path).load("scaled")

    def no_refit(*args, **kwargs):
        raise AssertionError("Saved pipeline application cannot refit scaling or regression")

    monkeypatch.setattr(type(scale), "fit_fitted_state", no_refit)
    monkeypatch.setattr(type(node), "fit_fitted_state", no_refit)
    incoming = data.copy()
    incoming.target = None
    result = _apply_model_artifact(
        manifest, arrays, incoming, model_id="scaled", replay=ApplicationModelArtifactReplay()
    )
    np.testing.assert_allclose(result["result"], outputs["default"], rtol=1e-12, atol=1e-12)


@pytest.mark.asyncio
async def test_artifact_write_failure_cannot_become_successful_model_registration(tmp_path, monkeypatch):
    node = node_registry.create_node("model.fitted_pls", "fit", {"n_components": 2})
    outputs = (await node.execute(sample("model.fitted_pls"))).outputs
    store = ModelStore(tmp_path)

    def disk_full(*args, **kwargs):
        raise OSError("synthetic disk full")

    monkeypatch.setattr(store, "save", disk_full)
    executor = DAGExecutor(runtime=ExecutionRuntime(model_artifact_writer=store))
    executor.results["fit"] = outputs
    with pytest.raises(OSError, match="disk full"):
        executor._process_model_artifact("fit")
    assert executor.saved_artifacts == []
    assert "model_id" not in outputs
    assert "_model_artifact" in outputs


@pytest.mark.asyncio
@pytest.mark.parametrize("node_type", ["model.fitted_pcr", "model.fitted_svr", "model.fitted_linear_regression"])
@pytest.mark.parametrize("typed_response", [False, True])
async def test_connected_response_overrides_unrelated_embedded_target(node_type, typed_response, tmp_path, monkeypatch):
    from spectra_sherpa.app.lib.sherpa_dataset import FeatureAxis, TargetContext
    from spectra_sherpa.app.services import model_application

    data = sample(node_type)
    data.target_context = TargetContext(target_names=["unrelated"], target_units="ppm")
    y = 3 * data.X[:, 0] + 2
    response = (
        SherpaDataset(X=y.reshape(-1, 1), feature_axis=FeatureAxis(labels=["response"]), units="mg/L")
        if typed_response
        else y
    )
    fit = node_registry.create_node(node_type, "fit", MODEL_CASES[node_type])
    outputs = (await fit.execute(data, y=response)).outputs
    artifact = outputs["_model_artifact"]
    metadata = artifact["metadata"]
    assert metadata["target_names"] == (["response"] if typed_response else None)
    assert metadata.get("target_units") == ("mg/L" if typed_response else None)
    assert metadata.get("selected_target") == ("response" if typed_response else None)
    store = ModelStore(tmp_path)
    store.save("response-authority", metadata, artifact["arrays"])
    monkeypatch.setattr(model_application, "get_model_store", lambda: store)
    incoming = data.copy()
    if typed_response:
        with pytest.raises(ValueError, match="target units"):
            await model_application.apply_model_to_dataset("response-authority", incoming)
        incoming.target = y
        incoming.target_context = TargetContext(target_names=["response"], target_units="mg/L")
    result = await model_application.apply_model_to_dataset("response-authority", incoming)
    np.testing.assert_allclose(result["predictions"], outputs["default"], atol=1e-12)
    if typed_response:
        assert result["metadata"]["target_names"] == ["response"]
        assert result["metrics"] is not None
    else:
        assert result["metrics"] is None
        assert any("no recorded target identity" in message for message in result["warnings"])


@pytest.mark.asyncio
async def test_multiway_application_does_not_drop_unreplayable_transformation(tmp_path):
    from spectra_sherpa.app.services.dag.meta_helpers import add_processing_step

    data = sample("model.parafac")
    add_processing_step(data, "preprocess.scale", {"method": "autoscale"})
    node = node_registry.create_node("model.parafac", "fit", MODEL_CASES["model.parafac"])
    artifact = (await node.execute(data)).outputs["_model_artifact"]
    store = ModelStore(tmp_path)
    store.save("multiway", artifact["metadata"], artifact["arrays"])
    manifest, arrays = store.load("multiway")
    with pytest.raises(ValueError, match="no multiway artifact replay"):
        _apply_model_artifact(manifest, arrays, data, model_id="multiway", replay=ApplicationModelArtifactReplay())


@pytest.mark.asyncio
async def test_svr_artifact_keeps_the_selected_connected_response(tmp_path, monkeypatch):
    from spectra_sherpa.app.lib.sherpa_dataset import FeatureAxis, TargetContext
    from spectra_sherpa.app.services import model_application

    data = sample("model.fitted_svr")
    targets = np.column_stack([data.X[:, 0], 3 * data.X[:, 1]])
    response = SherpaDataset(X=targets, feature_axis=FeatureAxis(labels=["first", "second"]), units="mg/L")
    node = node_registry.create_node("model.fitted_svr", "fit", {"target_index": 2})
    outputs = (await node.execute(data, y=response)).outputs
    artifact = outputs["_model_artifact"]
    assert artifact["metadata"]["selected_target"] == "second"
    assert artifact["metadata"]["target_names"] == ["second"]
    store = ModelStore(tmp_path)
    store.save("second-response", artifact["metadata"], artifact["arrays"])
    monkeypatch.setattr(model_application, "get_model_store", lambda: store)
    data.target = targets
    data.target_context = TargetContext(target_names=["first", "second"], target_units="mg/L")
    applied = await model_application.apply_model_to_dataset("second-response", data)
    np.testing.assert_allclose(applied["predictions"], outputs["default"], atol=1e-12)
    assert applied["metrics"] is not None
    assert applied["metadata"]["selected_target"] == "second"
