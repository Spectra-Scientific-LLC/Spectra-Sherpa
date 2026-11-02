"""One training-source binding across storage, project export and ID remapping."""

import hashlib
import io
import json
import zipfile
from copy import deepcopy
from types import SimpleNamespace

import numpy as np
import pytest
from fastapi import HTTPException
from sqlalchemy import select

from spectra_sherpa.core.model_artifact import (
    ModelArtifactIntegrityError,
    experiment_training_dataset_id,
    experiment_training_source_step,
    require_experiment_training_dataset_id,
)


def _chain(source):
    return [
        {"op_id": "data.attach_target", "parameters": {"target_column": "Moisture"}},
        source,
        {"op_id": "data.train_test_split", "parameters": {"test_size": 0.25, "random_state": 42}},
    ]


@pytest.mark.parametrize(
    "operation,key", [("spectrasherpa.experiment_dataset_read/2", "dataset_id"), ("data.file_load", "experiment_id")]
)
def test_resolver_finds_decorated_source_without_mutating_history(operation, key):
    source = {"op_id": operation, "parameters": {key: 209}}
    manifest = {"preprocessing_chain": _chain(source)}
    original = deepcopy(manifest)
    assert experiment_training_source_step(manifest) is source
    assert experiment_training_dataset_id(manifest) == 209
    assert require_experiment_training_dataset_id(manifest, 209) == 209
    with pytest.raises(ModelArtifactIntegrityError, match="stale"):
        require_experiment_training_dataset_id(manifest, 210)
    assert manifest == original


@pytest.mark.parametrize("value", [None, True, False, 0, -1, "209", 209.0])
def test_resolver_rejects_invalid_source_after_decorator(value):
    manifest = {
        "preprocessing_chain": _chain(
            {"op_id": "spectrasherpa.experiment_dataset_read/2", "parameters": {"dataset_id": value}}
        )
    }
    with pytest.raises(ModelArtifactIntegrityError, match="invalid"):
        experiment_training_dataset_id(manifest)


@pytest.mark.parametrize(
    "second",
    [
        {"op_id": "spectrasherpa.experiment_dataset_read/2", "parameters": {"dataset_id": 209}},
        {"op_id": "spectrasherpa.experiment_dataset_read/2", "parameters": {"dataset_id": 210}},
        {"op_id": "data.file_load", "parameters": {"experiment_id": 209, "file_id": 1}},
    ],
)
def test_resolver_refuses_multiple_source_operations_even_with_same_id(second):
    manifest = {
        "preprocessing_chain": _chain(
            {"op_id": "spectrasherpa.experiment_dataset_read/2", "parameters": {"dataset_id": 209}}
        )
        + [second]
    }
    with pytest.raises(ModelArtifactIntegrityError, match="ambiguous"):
        experiment_training_dataset_id(manifest)


def test_unrelated_history_is_not_an_invented_experiment_source():
    assert experiment_training_source_step({"preprocessing_chain": [{"op_id": "import.matlab_dso"}]}) is None
    assert experiment_training_dataset_id({}) is None


@pytest.mark.parametrize("case", ["mismatch", "outside_project", "ambiguous", "foreign_file"])
def test_decorated_archived_source_keeps_custody_refusals(case):
    from spectra_sherpa.app.api.v1.routes.projects import _bind_archived_model_training_source

    source = {"op_id": "data.file_load", "parameters": {"experiment_id": 209, "file_id": 4, "stage": "raw"}}
    manifest = {"preprocessing_chain": _chain(source)}
    record = {"training_dataset_id": 210 if case == "mismatch" else 209}
    if case == "ambiguous":
        manifest["preprocessing_chain"].append(deepcopy(source))
    experiments = {
        209: (
            2 if case == "outside_project" else 1,
            {"files": [{"id": 5 if case == "foreign_file" else 4, "stage": "raw"}]},
        )
    }
    with pytest.raises(HTTPException) as error:
        _bind_archived_model_training_source(manifest, record, owner_project_id=1, experiments=experiments)
    assert error.value.status_code == 400


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["spectrasherpa.experiment_dataset_read/2", "data.file_load"])
@pytest.mark.parametrize("mode", ["local", "enterprise"])
@pytest.mark.parametrize("source_origin", ["none", "retained_run"])
@pytest.mark.parametrize("producer_node_type", ["model.fitted_pls", "classification.plsda"])
async def test_fresh_decorated_model_project_roundtrip_rebinds_only_source_ids(
    operation, mode, source_origin, producer_node_type, auth_client, test_session, test_user, monkeypatch
):
    from spectra_sherpa.app.models.experiment import Experiment
    from spectra_sherpa.app.models.experiment_file import ExperimentFile
    from spectra_sherpa.app.models.model_artifact import ModelArtifact
    from spectra_sherpa.app.models.project import Project
    from spectra_sherpa.app.models.workflow import Workflow
    from spectra_sherpa.app.services.experiments import (
        ensure_experiment_dirs,
        experiment_dir,
        metadata_path_for,
        relative_to_data_dir,
        write_metadata,
    )
    from spectra_sherpa.app.services.model_application import load_project_dataset
    from spectra_sherpa.app.services.model_store import get_model_store, verify_model_artifact_storage_record

    project = Project(user_id=test_user.id, name="Fresh source-bound model")
    test_session.add(project)
    await test_session.flush()
    experiment = Experiment(user_id=test_user.id, project_id=project.id, name="Fresh source", metadata_path="")
    workflow = Workflow(user_id=test_user.id, project_id=project.id, name="Source sheet")
    test_session.add_all([experiment, workflow])
    await test_session.flush()
    ensure_experiment_dirs(experiment.id)
    metadata = metadata_path_for(experiment.id)
    write_metadata(metadata, {})
    experiment.metadata_path = relative_to_data_dir(metadata)
    path = experiment_dir(experiment.id) / "raw/source.csv"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("Wavenumber (cm-1),s0,s1,s2,s3,s4,s5,s6,s7\n1000,1,2,3,4,5,6,7,8\n1001,4,1,5,3,8,6,7,2\n")
    file = ExperimentFile(
        experiment_id=experiment.id,
        file_path="raw/source.csv",
        file_type="csv",
        stage="raw",
        file_size_bytes=path.stat().st_size,
    )
    test_session.add(file)
    await test_session.commit()
    loaded = await load_project_dataset(test_session, user_id=test_user.id, experiment_id=experiment.id, stage="raw")
    if operation == "data.file_load":
        parameters = {"experiment_id": experiment.id, "file_id": file.id, "stage": "raw"}
    else:
        parameters = {
            "dataset_id": experiment.id,
            "stage": "raw",
            "file_count": 1,
            "asset_id": None,
            "source_manifest_sha256": loaded.source_manifest_sha256,
            "scientific_collection_sha256": loaded.scientific_collection_sha256,
            "collection_definition_sha256": loaded.collection_definition_sha256,
        }
    history = _chain({"op_id": operation, "parameters": parameters})
    store = get_model_store()
    from spectra_sherpa.app.lib.sherpa_dataset import TargetContext
    from spectra_sherpa.app.services.dag.executor import DAGExecutor
    from spectra_sherpa.app.services.dag.node_base import node_registry
    from spectra_sherpa.core.execution_runtime import ExecutionRuntime

    # Exercise the actual executor persistence boundary for both ordinary and
    # native extracts. Do not seed either dispatch or producer metadata.
    training = loaded.dataset.copy()
    training.target = (
        np.array(["A", "B"] * (training.shape[0] // 2))
        if producer_node_type == "classification.plsda"
        else np.arange(training.shape[0], dtype=float)
    )
    training.target_context = TargetContext(
        target_type="categorical" if producer_node_type == "classification.plsda" else "continuous",
        target_names=["response"],
    )
    native = node_registry.create_node(producer_node_type, "fit", {"n_components": 1, "scale": False})
    fitted = await native.execute(training)
    fitted_artifact = fitted.outputs["_model_artifact"]
    fitted_artifact["metadata"]["preprocessing_chain"] = deepcopy(history)
    executor = DAGExecutor(runtime=ExecutionRuntime(model_artifact_writer=store))
    executor.nodes["fit"] = native
    executor.results["fit"] = fitted.outputs
    await executor._process_model_artifact("fit", positional_inputs=[training])
    uid = executor.saved_artifacts[0]["artifact_uid"]
    manifest, fitted_arrays = store.load(uid, verify=True)
    digest = manifest["integrity_hash"]
    assert manifest["producer_node_type"] == producer_node_type
    if producer_node_type == "classification.plsda":
        from spectra_sherpa.app.services.dag.nodes.modeling.saved_native_model import has_native_model_state

        assert "native_node_type" not in manifest
        assert not has_native_model_state(manifest, fitted_arrays)
    producing_run = None
    from spectra_sherpa.app.services.run_params import build_saved_definition_snapshot

    retained_graph = build_saved_definition_snapshot(
        SimpleNamespace(
            name="Exact producer",
            integrity_hash=None,
            nodes=[
                SimpleNamespace(
                    node_id="fit",
                    node_type=producer_node_type,
                    label="Fitted model",
                    parameters={"n_components": 1, "scale": False},
                )
            ],
            edges=[],
        )
    )
    if source_origin == "retained_run":
        from datetime import datetime, timezone

        from spectra_sherpa.app.models.execution_run import ExecutionRun
        from spectra_sherpa.app.services.run_output_retention import retain_run_outputs

        producing_run = ExecutionRun(
            user_id=test_user.id,
            project_id=project.id,
            workflow_id=workflow.id,
            name="Exact producer",
            status="completed",
            run_kind="training",
            executed_at=datetime.now(timezone.utc),
            params_snapshot={},
            results_summary={},
            produced_artifact_uids=[uid],
            evidence_completeness=retain_run_outputs(
                test_user.id, {"__workflow__": {"definition": retained_graph}}, {}
            ),
        )
        test_session.add(producing_run)
        await test_session.flush()
    model = ModelArtifact(
        artifact_uid=uid,
        user_id=test_user.id,
        project_id=project.id,
        workflow_id=workflow.id,
        training_dataset_id=experiment.id,
        source_run_id=producing_run.id if producing_run else None,
        node_id="fit",
        model_type=manifest["model_type"],
        name="Fresh model",
        artifact_dir=str(store._artifact_dir(uid)),
        integrity_hash=digest,
        n_features=2,
        preprocessing_summary=json.dumps(history),
        training_scientific_digest=manifest.get("training_scientific_digest"),
    )
    test_session.add(model)
    await test_session.commit()
    verify_model_artifact_storage_record(model)
    # The storage authority must see the same non-leading link, too.
    wrong_record = SimpleNamespace(
        **{
            key: getattr(model, key)
            for key in ("artifact_uid", "integrity_hash", "artifact_origin", "training_scientific_digest")
        },
        training_dataset_id=experiment.id + 1,
    )
    with pytest.raises(ModelArtifactIntegrityError, match="training source"):
        verify_model_artifact_storage_record(wrong_record)
    if producing_run is not None and mode == "local" and operation == "spectrasherpa.experiment_dataset_read/2":
        from spectra_sherpa.app.services.run_output_retention import retain_run_outputs

        original_evidence = deepcopy(producing_run.evidence_completeness)
        producing_run.evidence_completeness = retain_run_outputs(
            test_user.id, {"__workflow__": {"definition": {"nodes": [], "edges": []}}}, {}
        )
        await test_session.commit()
        refused = await auth_client.get(f"/api/v1/projects/{project.id}/export/sherpa")
        assert refused.status_code == 409
        assert "producing workflow definition" in refused.text
        for record in (test_user, project, workflow, experiment, file, model, producing_run):
            await test_session.refresh(record)
        producing_run.evidence_completeness = original_evidence
        await test_session.commit()
    exported = await auth_client.get(f"/api/v1/projects/{project.id}/export/sherpa")
    assert exported.status_code == 200, exported.text
    assert exported.headers.get("x-spectra-project-model-omissions", "0") == "0"
    with zipfile.ZipFile(io.BytesIO(exported.content)) as archive:
        snapshot = json.loads(archive.read("project.json"))
        assert len(snapshot["models"]) == 1
        if producing_run is not None:
            source = snapshot["models"][0]["source_workflow_run"]
            assert source["run_id"] == producing_run.id
            assert source["snapshot"] == retained_graph
            assert snapshot["workflows"][0]["nodes"] == []  # different current canvas
        assert json.loads(archive.read(f"models/{uid}/manifest.json"))["preprocessing_chain"] == history
    if producing_run is not None and mode == "local" and operation == "spectrasherpa.experiment_dataset_read/2":
        from spectra_sherpa.app.services.sherpa_object import ArchiveMember, build_archive

        with zipfile.ZipFile(io.BytesIO(exported.content)) as archive:
            members = [
                ArchiveMember(name, archive.read(name))
                for name in archive.namelist()
                if name not in {"project.json", "sherpa-object.json"}
            ]
        for bad_nodes in (
            [],
            [{"node_id": "unrelated", "node_type": "model.fitted_pls", "parameters": {}}],
            [{"node_id": "fit", "node_type": "model.fitted_pcr", "parameters": {}}],
        ):
            changed = deepcopy(snapshot)
            origin = changed["models"][0]["source_workflow_run"]
            origin["snapshot"]["nodes"] = bad_nodes
            origin["definition_sha256"] = hashlib.sha256(
                json.dumps(origin["snapshot"], sort_keys=True, separators=(",", ":")).encode()
            ).hexdigest()
            rejected = await auth_client.post(
                "/api/v1/projects/import",
                files={
                    "file": (
                        "forged.sherpa",
                        build_archive(project_payload=changed, members=members),
                        "application/zip",
                    )
                },
            )
            assert rejected.status_code == 400
            assert "producing-run provenance" in rejected.text
            for record in (test_user, project, workflow, experiment, file, model, producing_run):
                await test_session.refresh(record)

    from spectra_sherpa.app.core.config import app_config

    monkeypatch.setattr(app_config, "mode", mode)
    if mode != "local":
        from dataclasses import replace

        from spectra_sherpa.app.core import security

        monkeypatch.setenv("ALLOW_SYSTEM_API_KEY_AUTH", "true")
        monkeypatch.setattr(security, "settings", replace(security.settings, api_key="local-test-key"))
        auth_client.headers["X-API-Key"] = "local-test-key"
    response = await auth_client.post(
        "/api/v1/projects/import", files={"file": ("source.sherpa", exported.content, "application/zip")}
    )
    assert response.status_code == 201, response.text
    imported = await test_session.scalar(select(ModelArtifact).where(ModelArtifact.project_id == response.json()["id"]))
    assert imported is not None and imported.training_dataset_id != experiment.id
    from spectra_sherpa.app.models.application_release import ApplicationRelease

    release = await test_session.scalar(
        select(ApplicationRelease).where(ApplicationRelease.model_artifact_uid == imported.artifact_uid)
    )
    if mode == "local":
        assert release is not None
        assert release.origin == "saved_run"
        assert release.provenance["package_trust"] == {
            "status": "unsigned",
            "source": "project_archive",
            "package_sha256": hashlib.sha256(exported.content).hexdigest(),
        }
        assert release.provenance.get("promotion_review") is None
        # This fixture intentionally has no retained version/run; import trust
        # cannot manufacture the missing technical source authority.
        if producing_run is None:
            assert release.state == "revoked"
            assert "model has no saved workflow version or source run" in release.readiness["blockers"]
        else:
            assert release.state == "released"
            from spectra_sherpa.app.models.workflow_version import WorkflowVersion

            version = await test_session.get(WorkflowVersion, imported.workflow_version_id)
            external_origin = {
                "run_id": producing_run.id,
                "project_id": project.id,
                "workflow_id": workflow.id,
                "definition_sha256": hashlib.sha256(
                    json.dumps(retained_graph, sort_keys=True, separators=(",", ":")).encode()
                ).hexdigest(),
            }
            assert version.snapshot == {
                **retained_graph,
                "replay_authority": "external_evidence_only",
                "external_source_run_provenance": external_origin,
            }
            assert imported.source_run_id is None  # no fabricated local run

    else:
        assert release is None  # no default non-local release or trust change
    remapped, arrays = store.load(imported.artifact_uid, verify=True)
    expected = deepcopy(history)
    key = "experiment_id" if operation == "data.file_load" else "dataset_id"
    expected[1]["parameters"][key] = imported.training_dataset_id
    if operation == "data.file_load":
        imported_file = await test_session.scalar(
            select(ExperimentFile).where(ExperimentFile.experiment_id == imported.training_dataset_id)
        )
        expected[1]["parameters"]["file_id"] = imported_file.id
        assert imported_file.id != file.id
    assert remapped["preprocessing_chain"] == expected
    assert json.loads(imported.preprocessing_summary) == expected
    assert imported.integrity_hash == digest
    assert set(arrays) == set(fitted_arrays)
    for name, values in fitted_arrays.items():
        np.testing.assert_array_equal(arrays[name], values)
    verify_model_artifact_storage_record(imported)
    assert store.load(uid)[0]["preprocessing_chain"] == history  # original immutable history unchanged
    reexported = await auth_client.get(f"/api/v1/projects/{imported.project_id}/export/sherpa")
    assert reexported.status_code == 200, reexported.text
    with zipfile.ZipFile(io.BytesIO(reexported.content)) as archive:
        assert len(json.loads(archive.read("project.json"))["models"]) == 1
        assert (
            json.loads(archive.read(f"models/{imported.artifact_uid}/manifest.json"))["preprocessing_chain"] == expected
        )

        if producing_run is not None and mode == "local":
            portable_model = json.loads(archive.read("project.json"))["models"][0]
            assert (
                portable_model["source_workflow_version"]["snapshot"]["external_source_run_provenance"]
                == external_origin
            )
    if producing_run is not None and mode == "local":
        again = await auth_client.post(
            "/api/v1/projects/import", files={"file": ("again.sherpa", reexported.content, "application/zip")}
        )
        assert again.status_code == 201, again.text
        again_model = await test_session.scalar(
            select(ModelArtifact).where(ModelArtifact.project_id == again.json()["id"])
        )
        again_version = await test_session.get(WorkflowVersion, again_model.workflow_version_id)
        assert again_version.snapshot["external_source_run_provenance"] == external_origin
        assert again_model.source_run_id is None


@pytest.mark.asyncio
@pytest.mark.parametrize("case", ["owner", "project", "workflow", "artifact", "missing", "checksum"])
async def test_export_does_not_substitute_canvas_for_bad_producing_run(case, test_session, test_user):
    from datetime import datetime, timezone

    from spectra_sherpa.app.api.v1.routes.projects import ProjectSnapshotStateError, _model_source_run_snapshot
    from spectra_sherpa.app.models.execution_run import ExecutionRun
    from spectra_sherpa.app.models.project import Project
    from spectra_sherpa.app.models.workflow import Workflow
    from spectra_sherpa.app.services import run_output_retention as retention

    project = Project(user_id=test_user.id, name="Producing run custody")
    test_session.add(project)
    await test_session.flush()
    workflow = Workflow(user_id=test_user.id, project_id=project.id, name="Mutable canvas")
    test_session.add(workflow)
    await test_session.flush()
    evidence = retention.retain_run_outputs(
        test_user.id, {"__workflow__": {"definition": {"nodes": [], "edges": []}}}, {}
    )
    run = ExecutionRun(
        user_id=test_user.id,
        project_id=project.id,
        workflow_id=workflow.id,
        name="Producer",
        status="completed",
        executed_at=datetime.now(timezone.utc),
        params_snapshot={},
        results_summary={},
        produced_artifact_uids=["model-source"],
        evidence_completeness=evidence,
    )
    test_session.add(run)
    await test_session.flush()
    model = SimpleNamespace(
        user_id=test_user.id,
        project_id=project.id,
        workflow_id=workflow.id,
        source_run_id=run.id,
        artifact_uid="model-source",
    )
    if case in {"owner", "project", "workflow"}:
        setattr(model, {"owner": "user_id", "project": "project_id", "workflow": "workflow_id"}[case], 999)
    elif case == "artifact":
        run.produced_artifact_uids = ["another-model"]
    elif case == "missing":
        run.evidence_completeness = {"qualification": "unverified", "outputs": {}}
    else:
        digest = evidence["outputs"]["__workflow__"]["definition"]["sha256"]
        (retention._user_directory(test_user.id) / f"{digest}.json").write_text("{}")
    with pytest.raises(ProjectSnapshotStateError, match="exact producing workflow definition"):
        await _model_source_run_snapshot(model, test_session)


@pytest.mark.parametrize(
    "field,value",
    [
        ("workflow_id", 2),
        ("project_id", 2),
        ("artifact_uid", "another-model"),
        ("run_id", True),
        ("definition_sha256", "0" * 64),
        ("snapshot", {"nodes": [{"node_id": "changed"}], "edges": []}),
    ],
)
def test_imported_producing_graph_keeps_exact_identity_and_digest(field, value):
    from spectra_sherpa.app.api.v1.routes.projects import _validate_model_source_run

    snapshot = {
        "nodes": [{"node_id": "fit", "node_type": "model.fitted_pls", "parameters": {"n_components": 1}}],
        "edges": [],
    }
    source = {
        "run_id": 727,
        "workflow_id": 1,
        "project_id": 1,
        "artifact_uid": "model-source",
        "snapshot": snapshot,
        "definition_sha256": hashlib.sha256(
            json.dumps(snapshot, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest(),
    }
    _validate_model_source_run(
        source,
        artifact_uid="model-source",
        workflow_id=1,
        project_id=1,
        node_id="fit",
        manifest={"producer_node_type": "model.fitted_pls"},
    )
    with pytest.raises(ValueError, match="producing-run provenance"):
        _validate_model_source_run(
            {**source, field: value},
            artifact_uid="model-source",
            workflow_id=1,
            project_id=1,
            node_id="fit",
            manifest={"producer_node_type": "model.fitted_pls"},
        )


@pytest.mark.parametrize(
    "mutation", ["empty", "unrelated_id", "wrong_type", "duplicate", "dangling_edge", "cycle", "missing_producer_type"]
)
def test_rehashed_producing_graph_requires_structural_and_native_producer_authority(mutation):
    from spectra_sherpa.app.api.v1.routes.projects import _validate_model_source_run

    node = {"node_id": "fit", "node_type": "model.fitted_pls", "parameters": {"n_components": 1}}
    snapshot = {"nodes": [deepcopy(node)], "edges": []}
    manifest = {"producer_node_type": "model.fitted_pls"}
    if mutation == "empty":
        snapshot["nodes"] = []
    elif mutation == "unrelated_id":
        snapshot["nodes"][0]["node_id"] = "unrelated"
    elif mutation == "wrong_type":
        snapshot["nodes"][0]["node_type"] = "model.fitted_pcr"
    elif mutation == "duplicate":
        snapshot["nodes"].append(deepcopy(node))
    elif mutation in {"dangling_edge", "cycle"}:
        snapshot["edges"] = [{"from_node_id": "fit", "to_node_id": "missing" if mutation == "dangling_edge" else "fit"}]
    else:
        manifest = {"model_type": "pls"}  # Never infer a node type from the storage label.
    source = {
        "run_id": 727,
        "workflow_id": 1,
        "project_id": 1,
        "artifact_uid": "model-source",
        "snapshot": snapshot,
        "definition_sha256": hashlib.sha256(
            json.dumps(snapshot, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest(),
    }
    with pytest.raises(ValueError, match="producing"):
        _validate_model_source_run(
            source, artifact_uid="model-source", workflow_id=1, project_id=1, node_id="fit", manifest=manifest
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("contradiction", ["producer_type", "node_id", "native_dispatch"])
async def test_executor_refuses_contradictory_producer_before_publication(contradiction):
    from unittest.mock import Mock

    from spectra_sherpa.app.services.dag.executor import DAGExecutor
    from spectra_sherpa.app.services.dag.node_base import node_registry
    from spectra_sherpa.core.execution_runtime import ExecutionRuntime

    writer = SimpleNamespace(save=Mock())
    executor = DAGExecutor(runtime=ExecutionRuntime(model_artifact_writer=writer))
    executor.nodes["fit"] = node_registry.create_node("classification.plsda", "fit", {"n_components": 1})
    metadata = {"model_type": "plsda"}
    if contradiction == "producer_type":
        metadata["producer_node_type"] = "model.fitted_pls"
    elif contradiction == "node_id":
        metadata["node_id"] = "other"
    else:
        metadata["native_node_type"] = "model.fitted_pls"
    executor.results["fit"] = {"_model_artifact": {"metadata": metadata, "arrays": {}}}
    with pytest.raises((ValueError, ModelArtifactIntegrityError)):
        await executor._process_model_artifact("fit")
    writer.save.assert_not_called()
    assert executor.saved_artifacts == []
    assert "model_id" not in executor.results["fit"]
    assert "_model_artifact" in executor.results["fit"]
