from __future__ import annotations

import sys
import types

import pytest


@pytest.mark.asyncio
async def test_revoke_stale_release_after_model_deactivation(test_session, test_user):
    from spectra_sherpa.app.models.application_release import ApplicationRelease
    from spectra_sherpa.app.models.model_artifact import ModelArtifact
    from spectra_sherpa.app.models.project import Project
    from spectra_sherpa.app.models.workflow import Workflow
    from spectra_sherpa.app.services.application_release import revoke_stale_releases

    project = Project(user_id=test_user.id, name="Release cleanup")
    test_session.add(project)
    await test_session.flush()
    workflow = Workflow(user_id=test_user.id, project_id=project.id, name="Reviewed workflow")
    test_session.add(workflow)
    await test_session.flush()
    model = ModelArtifact(
        artifact_uid="model-release-cleanup",
        user_id=test_user.id,
        project_id=project.id,
        workflow_id=workflow.id,
        node_id="fit",
        model_type="pls",
        name="Reviewed model",
        artifact_dir="missing",
        integrity_hash="a" * 64,
        n_features=2,
        is_active=False,
        is_deploy_ready=True,
    )
    release = ApplicationRelease(
        handle="app_release_cleanup",
        user_id=test_user.id,
        project_id=project.id,
        workflow_id=workflow.id,
        model_artifact_uid=model.artifact_uid,
        origin="saved_run",
        state="released",
        label="Reviewed model",
    )
    test_session.add_all([model, release])
    await test_session.flush()

    changed = await revoke_stale_releases(
        test_session,
        user_id=test_user.id,
        project_id=project.id,
    )

    assert changed is True
    assert release.state == "revoked"
    assert release.readiness == {"ready": False, "blockers": ["model artifact is inactive"]}
    assert release.revoked_at is not None


@pytest.mark.asyncio
async def test_revoke_stale_release_when_canonical_readiness_fails(test_session, test_user, monkeypatch):
    from spectra_sherpa.app.models.application_release import ApplicationRelease
    from spectra_sherpa.app.models.project import Project
    from spectra_sherpa.app.models.workflow import Workflow
    from spectra_sherpa.app.services.application_release import revoke_stale_releases

    project = Project(user_id=test_user.id, name="Canonical cleanup")
    test_session.add(project)
    await test_session.flush()
    workflow = Workflow(user_id=test_user.id, project_id=project.id, name="Imported workflow")
    test_session.add(workflow)
    await test_session.flush()
    release = ApplicationRelease(
        handle="app_canonical_cleanup",
        user_id=test_user.id,
        project_id=project.id,
        workflow_id=workflow.id,
        canonical_artifact_id=123,
        origin="campaign_solution",
        state="released",
        label="Imported campaign",
    )
    test_session.add(release)
    await test_session.flush()

    async def unavailable(*args, **kwargs):
        raise ValueError("certified runtime is unavailable")

    fake_binding = types.ModuleType("spectra_sherpa.app.services.deployment_binding")
    fake_binding.resolve_deployment_binding = unavailable
    monkeypatch.setitem(sys.modules, "spectra_sherpa.app.services.deployment_binding", fake_binding)
    changed = await revoke_stale_releases(
        test_session,
        user_id=test_user.id,
        project_id=project.id,
    )

    assert changed is True
    assert release.state == "revoked"
    assert release.readiness == {"ready": False, "blockers": ["certified runtime is unavailable"]}
