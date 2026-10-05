"""Operational files remain inspectable through the ordinary saved-run authority."""

from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pytest

from spectra_sherpa.app.lib.axes import FeatureAxis, SampleAxis
from spectra_sherpa.app.lib.fitted_state import LinearRegressionExtract
from spectra_sherpa.app.lib.sherpa_dataset import SherpaDataset
from spectra_sherpa.app.models.execution_run import ExecutionRun
from spectra_sherpa.app.models.workflow import Workflow
from spectra_sherpa.app.schemas.run_evidence import RunEvidence
from spectra_sherpa.app.services import run_output_retention as retention
from spectra_sherpa.app.services.batch_predict import execute_workflow_dataset
from spectra_sherpa.app.services.dag.nodes.classification.plsda_state import SherpaPLSDAArtifact
from spectra_sherpa.app.services.dag.nodes.modeling import pls_core
from spectra_sherpa.app.services.deployment_binding import resolve_deployment_binding
from spectra_sherpa.app.services.deployment_evidence import (
    append_deployment_evidence,
    begin_deployment_evidence,
    finalize_deployment_evidence,
)
from spectra_sherpa.app.services.model_store import get_model_store


def test_incremental_retention_preserves_budget_and_existing_outputs(tmp_path, monkeypatch):
    monkeypatch.setattr(retention, "settings", replace(retention.settings, data_dir=tmp_path))
    monkeypatch.setattr(retention, "RUN_BYTES_LIMIT", 1500)
    first = retention.retain_run_outputs(1, {"first": {"default": "x" * 1000}}, {})
    combined = retention.retain_run_outputs(1, {"second": {"default": "y" * 1000}}, {}, previous=first)
    assert combined["outputs"]["first"] == first["outputs"]["first"]
    assert combined["outputs"]["second"]["default"]["state"] == "missing"
    assert "limit" in combined["outputs"]["second"]["default"]["reason"]
    assert "second" not in first["outputs"]
    with pytest.raises(ValueError, match="immutable"):
        retention.retain_run_outputs(1, {"first": {"default": "replacement"}}, {}, previous=first)


def test_incremental_retention_preserves_incomplete_inventory_notice(tmp_path, monkeypatch):
    monkeypatch.setattr(retention, "settings", replace(retention.settings, data_dir=tmp_path))
    previous = RunEvidence(
        reason="Run exceeds the 1024-output retention inventory limit.",
    ).model_dump()
    combined = retention.retain_run_outputs(1, {"next": {"default": [1]}}, {}, previous=previous)
    assert combined["qualification"] == "unverified"
    assert combined["reason"] == previous["reason"]
    assert combined["outputs"]["next"]["default"]["state"] == "exact"


@pytest.mark.asyncio
async def test_real_application_retains_each_files_input_labels_predictions_and_failure(
    test_session,
    test_user,
    deployment_artifact_factory,
    tmp_path,
    monkeypatch,
):
    import spectra_sherpa.app.services.dag.nodes  # noqa: F401

    monkeypatch.setattr(retention, "settings", replace(retention.settings, data_dir=tmp_path))
    workflow = Workflow(user_id=test_user.id, name="Synthetic source")
    test_session.add(workflow)
    await test_session.flush()
    artifact = await deployment_artifact_factory(workflow)
    manifest, arrays = LinearRegressionExtract(coef=np.array([2.0, -1.0]), intercept=np.array([0.5])).to_artifact()
    manifest["n_features"] = 2
    store = get_model_store()
    artifact.integrity_hash = store.save_new(artifact.artifact_uid, manifest, arrays)
    artifact.artifact_dir = store.artifact_directory(artifact.artifact_uid)
    await test_session.commit()
    binding = await resolve_deployment_binding(
        test_session, user_id=test_user.id, workflow_id=workflow.id, artifact_uid=artifact.artifact_uid
    )
    run = ExecutionRun(
        user_id=test_user.id,
        workflow_id=workflow.id,
        workflow_version_id=artifact.workflow_version_id,
        name="Two files",
        run_kind="batch_inference",
        attempted_artifact_uids=[artifact.artifact_uid],
        executed_at=datetime.now(timezone.utc),
        status="running",
        params_snapshot={},
        results_summary={},
    )
    await begin_deployment_evidence(run, binding.workflow, [Path("first.csv"), Path("second.csv")])
    data = SherpaDataset(
        X=np.array([[1.0, 0.0], [2.0, 0.5], [3.0, 1.0]]),
        sample_axis=SampleAxis(labels=["sample-a", "sample-b", "sample-c"]),
    )
    execution = await execute_workflow_dataset(binding.workflow, data, owner_user_id=test_user.id)
    await append_deployment_evidence(run, binding.workflow, 0, execution=execution)
    await append_deployment_evidence(run, binding.workflow, 1, error=ValueError("revoked"))
    await finalize_deployment_evidence(run)
    evidence = RunEvidence.model_validate(run.evidence_completeness)
    saved = retention.read_output(test_user.id, evidence.outputs["file_0::deployment_model"]["y_pred"])
    np.testing.assert_allclose(saved, [[2.5], [4.0], [5.5]])
    input_data = retention.read_output(test_user.id, evidence.outputs["file_0::deployment_input"]["default"])
    assert input_data["y_axis"]["labels"] == ["sample-a", "sample-b", "sample-c"]
    assert run.node_statuses["file_0::deployment_model"] == "completed"
    assert run.node_statuses["file_1::deployment_model"] == "error"
    assert "file_1::deployment_model" in evidence.outputs["__diagnostics__"]
    graph = retention.read_output(test_user.id, evidence.outputs["__workflow__"]["definition"])
    assert len(graph["nodes"]) == 4
    assert graph["nodes"][2]["label"].startswith("second.csv")
    presentations = retention.read_output(
        test_user.id, evidence.outputs["__diagnostics__"]["_scientific_presentations"]
    )
    assert "file_0::deployment_model" in presentations


@pytest.mark.asyncio
@pytest.mark.parametrize("revoke_after_first", [False, True])
async def test_private_batch_reuses_exact_model_and_rechecks_access(
    test_session, test_user, deployment_artifact_factory, tmp_path, monkeypatch, revoke_after_first
):
    from unittest.mock import AsyncMock

    from fastapi import HTTPException
    from sqlalchemy import select

    from spectra_sherpa.app.api import deps
    from spectra_sherpa.app.contracts import prediction_access
    from spectra_sherpa.app.models.batch_prediction import BatchPrediction
    from spectra_sherpa.app.services import batch_predict, prediction_upload
    from spectra_sherpa.app.services.job_manager import job_manager

    monkeypatch.setattr(retention, "settings", replace(retention.settings, data_dir=tmp_path))
    monkeypatch.setattr(prediction_upload, "settings", replace(prediction_upload.settings, data_dir=tmp_path))
    workflow = Workflow(user_id=test_user.id, name="Frozen private prediction fixture")
    test_session.add(workflow)
    await test_session.flush()
    artifact = await deployment_artifact_factory(workflow)
    manifest, arrays = LinearRegressionExtract(coef=np.array([2.0, -1.0]), intercept=np.array([0.5])).to_artifact()
    manifest["n_features"] = 2
    store = get_model_store()
    artifact.integrity_hash = store.save_new(artifact.artifact_uid, manifest, arrays)
    artifact.artifact_dir = store.artifact_directory(artifact.artifact_uid)
    await test_session.commit()
    files, receipts = prediction_upload.persist_prediction_files(
        test_user.id, [("first.csv", b"first"), ("second.csv", b"second")]
    )
    run = ExecutionRun(
        user_id=test_user.id,
        workflow_id=workflow.id,
        workflow_version_id=artifact.workflow_version_id,
        name="Owned private batch",
        run_kind="batch_inference",
        attempted_artifact_uids=[artifact.artifact_uid],
        source_metadata=receipts,
        executed_at=datetime.now(timezone.utc),
        status="running",
        params_snapshot={},
        results_summary={},
    )
    test_session.add(run)
    await test_session.commit()
    checks = 0

    async def require_access(session, user_id):
        nonlocal checks
        assert user_id == test_user.id
        checks += 1
        if revoke_after_first and checks >= 3:
            raise HTTPException(403, "Prediction entitlement revoked")

    def forbidden_legacy_guard(capability):
        raise AssertionError("Private custody must use account admission, not the public trial source guard")

    monkeypatch.setattr(prediction_access, "require_private_prediction", require_access)
    monkeypatch.setattr(deps, "check_demo_capability", forbidden_legacy_guard)
    monkeypatch.setattr(job_manager, "update_progress", AsyncMock())
    monkeypatch.setattr(
        batch_predict,
        "load_single_file",
        lambda *args, **kwargs: SherpaDataset(
            X=np.array([[1.0, 0.0], [2.0, 0.5]]),
            sample_axis=SampleAxis(labels=["external-a", "external-b"]),
        ),
    )
    await batch_predict.run_batch_prediction(test_session, 1, run, workflow, files)
    predictions = (await test_session.scalars(select(BatchPrediction).where(BatchPrediction.run_id == run.id))).all()
    assert len(predictions) == 2
    assert predictions[0].status == "completed"
    assert predictions[1].status == ("error" if revoke_after_first else "completed")
    assert run.status == ("partial" if revoke_after_first else "completed")
    assert checks == 3
    assert run.succeeded_artifact_uids == [artifact.artifact_uid]
    evidence = RunEvidence.model_validate(run.evidence_completeness)
    saved = retention.read_output(test_user.id, evidence.outputs["file_0::deployment_model"]["y_pred"])
    np.testing.assert_allclose(saved, [[2.5], [4.0]])


@pytest.mark.asyncio
async def test_private_batch_preserves_plsda_class_order_scores_and_fitted_scaling(
    test_session, test_user, deployment_artifact_factory, tmp_path, monkeypatch
):
    from unittest.mock import AsyncMock

    from sqlalchemy import select

    from spectra_sherpa.app.contracts import prediction_access
    from spectra_sherpa.app.models.batch_prediction import BatchPrediction
    from spectra_sherpa.app.services import batch_predict, prediction_upload
    from spectra_sherpa.app.services.job_manager import job_manager

    monkeypatch.setattr(retention, "settings", replace(retention.settings, data_dir=tmp_path))
    monkeypatch.setattr(prediction_upload, "settings", replace(prediction_upload.settings, data_dir=tmp_path))

    workflow = Workflow(user_id=test_user.id, name="Frozen PLS-DA application")
    test_session.add(workflow)
    await test_session.flush()
    artifact = await deployment_artifact_factory(workflow)

    classes = np.asarray(["angustifolia", "latifolia", "intermedia"], dtype=object)
    training = np.vstack(
        [
            np.tile([3.0, 0.0, 0.5, 1.0], (6, 1)),
            np.tile([0.0, 3.0, 0.5, 1.0], (6, 1)),
            np.tile([0.0, 0.5, 3.0, 1.0], (6, 1)),
        ]
    )
    training += np.random.default_rng(91).normal(scale=0.03, size=training.shape)
    dummy = np.eye(len(classes), dtype=np.float64)[np.repeat(np.arange(len(classes)), 6)]
    fitted = pls_core.fit_simpls(training, dummy, n_components=2, scale=True)
    feature_axis = FeatureAxis(labels=["marker-a", "marker-b", "marker-c", "baseline"])
    training_dataset = SherpaDataset(X=training, feature_axis=feature_axis)
    extract = SherpaPLSDAArtifact.from_fit(fitted, classes, training_dataset)
    manifest, arrays = extract.to_artifact()
    manifest["n_features"] = training.shape[1]

    artifact.model_type = "plsda"
    artifact.n_features = training.shape[1]
    artifact.classes_json = '["angustifolia", "latifolia", "intermedia"]'
    store = get_model_store()
    artifact.integrity_hash = store.save_new(artifact.artifact_uid, manifest, arrays)
    artifact.artifact_dir = store.artifact_directory(artifact.artifact_uid)
    await test_session.commit()

    incoming = np.asarray(
        [
            [2.9, 0.1, 0.5, 1.0],
            [0.1, 2.9, 0.5, 1.0],
            [0.1, 0.5, 2.9, 1.0],
        ],
        dtype=np.float64,
    )
    incoming_dataset = SherpaDataset(X=incoming, feature_axis=feature_axis)
    expected_labels, expected_scores = extract.predict(incoming_dataset)
    files, receipts = prediction_upload.persist_prediction_files(test_user.id, [("unknown.csv", b"unknown")])
    run = ExecutionRun(
        user_id=test_user.id,
        workflow_id=workflow.id,
        workflow_version_id=artifact.workflow_version_id,
        name="Owned PLS-DA batch",
        run_kind="batch_inference",
        attempted_artifact_uids=[artifact.artifact_uid],
        source_metadata=receipts,
        executed_at=datetime.now(timezone.utc),
        status="running",
        params_snapshot={},
        results_summary={},
    )
    test_session.add(run)
    await test_session.commit()

    monkeypatch.setattr(prediction_access, "require_private_prediction", AsyncMock())
    monkeypatch.setattr(job_manager, "update_progress", AsyncMock())
    monkeypatch.setattr(
        batch_predict,
        "load_single_file",
        lambda *args, **kwargs: SherpaDataset(
            X=incoming,
            sample_axis=SampleAxis(labels=["external-a", "external-b", "external-c"]),
            feature_axis=feature_axis,
        ),
    )

    await batch_predict.run_batch_prediction(test_session, 1, run, workflow, files)

    prediction = await test_session.scalar(select(BatchPrediction).where(BatchPrediction.run_id == run.id))
    assert prediction is not None and prediction.status == "completed"
    evidence = RunEvidence.model_validate(run.evidence_completeness)
    outputs = evidence.outputs["file_0::deployment_model"]
    saved_labels = retention.read_output(test_user.id, outputs["labels"])
    saved_scores = retention.read_output(test_user.id, outputs["result"])
    assert saved_labels == expected_labels.tolist()
    np.testing.assert_allclose(saved_scores, expected_scores, rtol=0.0, atol=0.0)

    saved_manifest, _saved_arrays = store.load(artifact.artifact_uid)
    assert saved_manifest["classes"] == classes.tolist()
    assert saved_manifest["scale"] is True
