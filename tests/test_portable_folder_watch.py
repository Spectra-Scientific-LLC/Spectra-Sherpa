"""A portable fitted model executes incoming local files after project import."""

import uuid

import numpy as np
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from spectra_sherpa.app.lib.fitted_state import LinearRegressionExtract
from spectra_sherpa.app.models.batch_prediction import BatchPrediction
from spectra_sherpa.app.models.execution_run import ExecutionRun
from spectra_sherpa.app.models.folder_watch import FolderWatch
from spectra_sherpa.app.models.model_artifact import ModelArtifact
from spectra_sherpa.app.models.project import Project
from spectra_sherpa.app.models.workflow import Workflow
from spectra_sherpa.app.models.workflow_version import WorkflowVersion
from spectra_sherpa.app.schemas.run_evidence import RunEvidence
from spectra_sherpa.app.services import folder_watch_service
from spectra_sherpa.app.services.model_store import get_model_store
from spectra_sherpa.app.services.run_output_retention import read_output

pytestmark = pytest.mark.usefixtures("deny_inference_network")


@pytest.mark.asyncio
async def test_export_import_then_real_local_watch(auth_client, test_session, test_user, tmp_path, monkeypatch):
    import spectra_sherpa.app.services.dag.nodes  # noqa: F401

    project = Project(user_id=test_user.id, name="Cloud fitted model")
    test_session.add(project)
    await test_session.flush()
    workflow = Workflow(user_id=test_user.id, project_id=project.id, name="Training source", nodes=[], edges=[])
    test_session.add(workflow)
    await test_session.flush()
    version = WorkflowVersion(
        workflow_id=workflow.id,
        created_by=test_user.id,
        version_number=1,
        snapshot={"nodes": [], "edges": [], "purpose": "analysis"},
    )
    test_session.add(version)
    await test_session.flush()
    uid = str(uuid.uuid4())
    manifest, arrays = LinearRegressionExtract(coef=np.array([2.0, -1.0]), intercept=np.array([0.5])).to_artifact()
    manifest["n_features"] = 2
    store = get_model_store()
    digest = store.save_new(uid, manifest, arrays)
    test_session.add(
        ModelArtifact(
            artifact_uid=uid,
            user_id=test_user.id,
            project_id=project.id,
            workflow_id=workflow.id,
            workflow_version_id=version.id,
            node_id="fit",
            model_type="linear_regression",
            name="Portable linear model",
            artifact_dir=store.artifact_directory(uid),
            integrity_hash=digest,
            n_features=2,
            is_deploy_ready=True,
        )
    )
    await test_session.commit()
    exported = await auth_client.get(f"/api/v1/projects/{project.id}/export/sherpa")
    assert exported.status_code == 200, exported.text
    imported = await auth_client.post(
        "/api/v1/projects/import", files={"file": ("cloud.sherpa", exported.content, "application/zip")}
    )
    assert imported.status_code == 201, imported.text
    artifact = await test_session.scalar(select(ModelArtifact).where(ModelArtifact.project_id == imported.json()["id"]))
    assert artifact.artifact_uid != uid  # Existing local artifact is never overwritten.
    assert artifact.workflow_version_id != version.id
    incoming = tmp_path / "incoming"
    incoming.mkdir()
    (incoming / "sample.csv").write_text("1000,1100\n1,0\n2,0.5\n3,1\n")
    watch = FolderWatch(
        user_id=test_user.id,
        workflow_id=artifact.workflow_id,
        artifact_uid=artifact.artifact_uid,
        workflow_version_id=artifact.workflow_version_id,
        name="Imported model watch",
        folder_path=str(incoming),
        file_pattern="*.csv",
        poll_interval_sec=10,
        settle_time_seconds=0,
        is_enabled=True,
        processed_files={},
    )
    test_session.add(watch)
    await test_session.commit()
    monkeypatch.setattr(
        folder_watch_service, "async_session", async_sessionmaker(test_session.bind, expire_on_commit=False)
    )

    await folder_watch_service.FolderWatchService()._process_watch(watch)
    prediction = await test_session.scalar(select(BatchPrediction))
    assert prediction is not None
    assert prediction.status == "completed", prediction.error_message
    run = await test_session.get(ExecutionRun, prediction.run_id)
    assert run.workflow_version_id == artifact.workflow_version_id
    assert run.succeeded_artifact_uids == [artifact.artifact_uid]
    evidence = RunEvidence.model_validate(run.evidence_completeness)
    values = read_output(test_user.id, evidence.outputs["file_0::deployment_model"]["y_pred"])
    np.testing.assert_allclose(values, [[2.5], [4.0], [5.5]])

    await test_session.refresh(watch)
    (incoming / "incompatible.csv").write_text("1000,1100,1200\n1,2,3\n")
    await folder_watch_service.FolderWatchService()._process_watch(watch)
    failures = (await test_session.scalars(select(BatchPrediction).where(BatchPrediction.status == "error"))).all()
    assert len(failures) == 1
    assert "feature" in failures[0].error_message.lower()
    successful = (
        await test_session.scalars(select(BatchPrediction).where(BatchPrediction.status == "completed"))
    ).all()
    assert len(successful) == 1  # The original file is not processed twice.
