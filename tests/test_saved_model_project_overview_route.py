"""Project comparison uses only admitted, verified saved-model records."""

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from spectra_sherpa.app.models.execution_run import ExecutionRun
from spectra_sherpa.app.models.model_artifact import ModelArtifact
from spectra_sherpa.app.models.project import Project
from spectra_sherpa.app.models.workflow import Workflow
from spectra_sherpa.app.models.workflow_version import WorkflowVersion


@pytest.mark.asyncio
async def test_project_overview_keeps_unbound_run_evidence_out_of_model_row(
    auth_client, test_session, test_user, monkeypatch
):
    from spectra_sherpa.app.services import model_store

    project = Project(user_id=test_user.id, name="comparison-project")
    test_session.add(project)
    await test_session.flush()
    workflow = Workflow(user_id=test_user.id, project_id=project.id, name="comparison-workflow")
    test_session.add(workflow)
    await test_session.flush()
    run = ExecutionRun(
        user_id=test_user.id,
        project_id=project.id,
        workflow_id=workflow.id,
        name="different-producing-fit",
        status="completed",
        params_snapshot={},
        results_summary={},
        executed_at=datetime.now(timezone.utc),
        produced_artifact_uids=["another-model"],
        source_metadata={"data_selection_revisions": [{"source_node_id": "input", "revision_number": 1}]},
    )
    test_session.add(run)
    await test_session.flush()
    model = ModelArtifact(
        artifact_uid="comparison-model",
        user_id=test_user.id,
        project_id=project.id,
        workflow_id=workflow.id,
        source_run_id=run.id,
        node_id="fit",
        model_type="pls",
        name="saved-fit",
        artifact_dir="/unused/in/route/test",
        integrity_hash="a" * 64,
        n_features=3,
        n_components=2,
        is_active=True,
    )
    test_session.add(model)
    await test_session.commit()
    monkeypatch.setattr(model_store, "verify_model_artifact_storage_record", lambda _model: None)
    manifest = {
        "integrity_hash": "a" * 64,
        "artifact_uid": model.artifact_uid,
        "node_id": model.node_id,
        "model_type": model.model_type,
        "n_components": model.n_components,
        "response_identity": {"names": ["Protein"], "units": ["wt %"]},
        "metrics": {"rmse": 0.4},
    }
    monkeypatch.setattr(
        model_store,
        "get_model_store",
        lambda: SimpleNamespace(load=lambda _uid, verify: (manifest, {})),
    )

    denied = await auth_client.get("/api/v1/models/project-overview", params={"project_id": project.id + 1})
    assert denied.status_code in (403, 404)
    response = await auth_client.get("/api/v1/models/project-overview", params={"project_id": project.id})
    assert response.status_code == 200, response.text
    rows = response.json()["rows"]
    assert len(rows) == 1
    assert rows[0]["artifact_uid"] == model.artifact_uid
    assert rows[0]["metrics"]["rmsecv"] is None
    assert rows[0]["comparison_key"] is None
    assert rows[0]["evidence"]["source_view_sha256"] is None
    assert rows[0]["qualification"]["state"] == "unavailable"

    # A run can contain multiple fit nodes. Its artifact UID alone cannot
    # authorize a curve read from another node after metadata drift.
    manifest["node_id"] = "other-fit"
    mismatched = await auth_client.get("/api/v1/models/project-overview", params={"project_id": project.id})
    assert mismatched.status_code == 200
    assert mismatched.json()["rows"][0]["unavailable_reason"] == "Saved model artifact could not be verified."


@pytest.mark.parametrize("retained_definition", [False, True])
@pytest.mark.asyncio
async def test_project_overview_binds_heldout_classification_to_producing_graph(
    auth_client, test_session, test_user, monkeypatch, retained_definition
):
    from spectra_sherpa.app.services import model_store, run_output_retention
    from spectra_sherpa.app.services.dag.integrity import compute_workflow_hash

    project = Project(user_id=test_user.id, name="classification-comparison")
    test_session.add(project)
    await test_session.flush()
    workflow = Workflow(user_id=test_user.id, project_id=project.id, name="classification-workflow")
    test_session.add(workflow)
    await test_session.flush()
    snapshot = {
        "nodes": [
            {"node_id": "fit", "node_type": "classification.plsda"},
            {"node_id": "apply", "node_type": "classification.apply_plsda"},
            {"node_id": "eval", "node_type": "diagnostics.classification_evaluator"},
            {"node_id": "unrelated", "node_type": "diagnostics.classification_evaluator"},
        ],
        "edges": [
            {
                "from_node_id": "fit",
                "to_node_id": "apply",
                "from_output": "fitted_state",
                "to_input": "fitted_state",
            },
            {"from_node_id": "apply", "to_node_id": "eval", "from_output": "y_pred", "to_input": "default"},
        ],
    }
    digest = compute_workflow_hash(snapshot["nodes"], snapshot["edges"])
    version = None
    if not retained_definition:
        version = WorkflowVersion(
            workflow_id=workflow.id,
            version_number=1,
            created_by=test_user.id,
            snapshot=snapshot,
        )
        test_session.add(version)
        await test_session.flush()

    def exact(digest):
        return {
            "state": "exact",
            "storage": "file",
            "sha256": digest,
            "byte_count": 100,
            "format_version": 1,
        }

    run = ExecutionRun(
        user_id=test_user.id,
        project_id=project.id,
        workflow_id=workflow.id,
        workflow_version_id=version.id if version else None,
        integrity_hash=digest if retained_definition else None,
        name="held-out classification",
        status="completed",
        params_snapshot={},
        results_summary={},
        executed_at=datetime.now(timezone.utc),
        produced_artifact_uids=["plsda-model"],
        evidence_completeness={
            "schema_version": 1,
            "qualification": "qualified",
            "outputs": {
                "fit": {"component_curve": exact("a" * 64)},
                "eval": {"default": exact("b" * 64)},
                "unrelated": {"default": exact("c" * 64)},
                **({"__workflow__": {"definition": exact("e" * 64)}} if retained_definition else {}),
            },
        },
    )
    test_session.add(run)
    await test_session.flush()
    model = ModelArtifact(
        artifact_uid="plsda-model",
        user_id=test_user.id,
        project_id=project.id,
        workflow_id=workflow.id,
        workflow_version_id=version.id if version else None,
        source_run_id=run.id,
        node_id="fit",
        model_type="plsda",
        name="Lavender PLS-DA",
        artifact_dir="/unused/in/route/test",
        integrity_hash="d" * 64,
        n_features=3,
        n_components=None if retained_definition else 2,
        is_active=True,
    )
    test_session.add(model)
    await test_session.commit()
    manifest = {
        "integrity_hash": "d" * 64,
        "artifact_uid": model.artifact_uid,
        "node_id": "fit",
        "model_type": "plsda",
        "n_components": None if retained_definition else 2,
        **({"effective_n_components": 2} if retained_definition else {}),
        "preprocessing_chain": [
            {"op_id": "data.attach_target", "parameters": {"target_column": "claimed_botanical_group"}}
        ],
    }
    curve = {
        "schema_version": "spectrasherpa-plsda-component-curve/1",
        "selected_components": 2,
        "n_calibration": 24,
        "calibration": [{"components": 2, "status": "available", "balanced_accuracy": 1}],
        "cross_validation": (
            {
                "status": "available",
                "role": "development_tuning",
                "method": "stratified_kfold",
                "n_folds": 5,
                "rows": [{"components": 2, "status": "available", "balanced_accuracy": 0.8}],
            }
            if retained_definition
            else {"status": "unavailable", "reason": "Too few independent groups"}
        ),
    }
    evaluation = {
        "schema_version": "spectrasherpa.classification-evaluation/1",
        "task_type": "classification",
        "n_samples": 9,
        "accuracy": 0.89,
        "balanced_accuracy": 0.83,
        "population_authority": {
            "schema_version": "spectrasherpa-population-authority/1",
            "role": "held_out_test",
            "qualification": "graph_verified",
        },
    }
    monkeypatch.setattr(model_store, "verify_model_artifact_storage_record", lambda _model: None)
    monkeypatch.setattr(
        model_store, "get_model_store", lambda: SimpleNamespace(load=lambda _uid, verify: (manifest, {}))
    )
    read = []

    def retained(_user_id, item):
        read.append(item.sha256)
        return {
            "a" * 64: curve,
            "b" * 64: evaluation,
            "c" * 64: evaluation,
            "e" * 64: {**snapshot, "integrity_hash": digest},
        }[item.sha256]

    monkeypatch.setattr(run_output_retention, "read_output", retained)

    response = await auth_client.get("/api/v1/models/project-overview", params={"project_id": project.id})
    assert response.status_code == 200, response.text
    row = response.json()["rows"][0]
    assert row["target_names"] == ["claimed_botanical_group"]
    assert row["classification_metrics"]["held_out_balanced_accuracy"] == 0.83
    assert row["classification_metrics"]["cv_balanced_accuracy"] == (0.8 if retained_definition else None)
    assert row["held_out_validation"]["count"] == 9
    assert "c" * 64 not in read
    if retained_definition:
        assert "e" * 64 in read
