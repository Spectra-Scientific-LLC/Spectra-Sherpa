"""Saved diagnostics routes preserve project, model, and producing-run custody."""

from datetime import datetime, timezone

import pytest

from spectra_sherpa.app.models.execution_run import ExecutionRun
from spectra_sherpa.app.models.model_artifact import ModelArtifact
from spectra_sherpa.app.models.project import Project
from spectra_sherpa.app.models.workflow import Workflow


async def _seed(test_session, test_user, *, model_type: str, bound: bool = True):
    project = Project(user_id=test_user.id, name="diagnostic-project")
    test_session.add(project)
    await test_session.flush()
    workflow = Workflow(user_id=test_user.id, project_id=project.id, name="diagnostic-workflow")
    test_session.add(workflow)
    await test_session.flush()
    uid = f"test-{model_type}-diagnostics"
    run = ExecutionRun(
        user_id=test_user.id,
        project_id=project.id,
        workflow_id=workflow.id,
        name="producing-fit",
        status="completed",
        params_snapshot={},
        results_summary={},
        executed_at=datetime.now(timezone.utc),
        produced_artifact_uids=[uid] if bound else [],
    )
    test_session.add(run)
    await test_session.flush()
    model = ModelArtifact(
        artifact_uid=uid,
        user_id=test_user.id,
        project_id=project.id,
        workflow_id=workflow.id,
        source_run_id=run.id,
        node_id="fit",
        model_type=model_type,
        name="saved-fit",
        artifact_dir="/unused/in/route/test",
        integrity_hash="a" * 64,
        n_features=3,
        is_active=True,
    )
    test_session.add(model)
    await test_session.commit()
    return project.id, uid


@pytest.mark.asyncio
async def test_pca_diagnostics_route_requires_producing_run_binding(auth_client, test_session, test_user, monkeypatch):
    from spectra_sherpa.app.api.v1.routes import models as routes
    from spectra_sherpa.app.services import saved_model_diagnostics as service

    project_id, uid = await _seed(test_session, test_user, model_type="pca", bound=False)
    monkeypatch.setattr(routes, "_verify_canonical_detail_storage", lambda _model: None)
    called = False

    async def fake_service(_run, _node):
        nonlocal called
        called = True
        return {"receipt": {"model_kind": "pca", "rows": [{"id": "obs-1"}]}}

    monkeypatch.setattr(service, "saved_model_diagnostics", fake_service)
    response = await auth_client.get(f"/api/v1/models/{uid}/diagnostics", params={"project_id": project_id})
    assert response.status_code == 409
    assert not called


@pytest.mark.asyncio
async def test_plsda_diagnostics_route_uses_exact_saved_model_and_project(
    auth_client, test_session, test_user, monkeypatch
):
    from spectra_sherpa.app.api.v1.routes import models as routes
    from spectra_sherpa.app.services import saved_model_diagnostics as service

    project_id, uid = await _seed(test_session, test_user, model_type="plsda")
    monkeypatch.setattr(routes, "_verify_canonical_detail_storage", lambda _model: None)
    calls = []

    async def fake_service(run, model):
        calls.append((run.id, model.artifact_uid, model.node_id))
        return {"run_id": run.id, "receipt_sha256": "b" * 64, "receipt": {"model_kind": "plsda"}}

    monkeypatch.setattr(service, "saved_plsda_sample_diagnostics", fake_service)
    foreign = await auth_client.get(f"/api/v1/models/{uid}/plsda-diagnostics", params={"project_id": project_id + 1})
    assert foreign.status_code in (403, 404)
    assert not calls
    response = await auth_client.get(f"/api/v1/models/{uid}/plsda-diagnostics", params={"project_id": project_id})
    assert response.status_code == 200, response.text
    assert response.json()["receipt_sha256"] == "b" * 64
    assert len(calls) == 1 and calls[0][1:] == (uid, "fit")
