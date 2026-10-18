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


@pytest.mark.asyncio
async def test_canonical_listing_cannot_create_new_reviewed_readiness(test_session, test_user):
    from types import SimpleNamespace

    from spectra_sherpa.app.models.project import Project
    from spectra_sherpa.app.models.workflow import Workflow
    from spectra_sherpa.app.services.application_release import ensure_canonical_release

    project = Project(user_id=test_user.id, name="Review")
    test_session.add(project)
    await test_session.flush()
    workflow = Workflow(user_id=test_user.id, project_id=project.id, name="Imported")
    test_session.add(workflow)
    await test_session.flush()
    artifact = SimpleNamespace(
        id=555,
        project_id=project.id,
        workflow_id=workflow.id,
        artifact_digest="a" * 64,
        capsule_digest="b" * 64,
        application_plan_digest="c" * 64,
        package_sha256="d" * 64,
        application_plan_payload={},
    )
    kwargs = dict(artifact=artifact, user_id=test_user.id, label="Imported", readiness={"ready": True, "blockers": []})
    pending = await ensure_canonical_release(test_session, **kwargs)
    assert pending.state == "revoked"
    assert pending.readiness["review_state"] == "review_required"
    repeated = await ensure_canonical_release(test_session, **kwargs)
    assert repeated.handle == pending.handle and repeated.state == "revoked"
    reviewed = await ensure_canonical_release(
        test_session, **kwargs, promotion_review={"review_digest": "e" * 64, "protocol": "exploratory"}
    )
    assert reviewed.handle == pending.handle
    assert reviewed.state == "released"
    assert reviewed.readiness["review_state"] == "reviewed"
    assert (await ensure_canonical_release(test_session, **kwargs)).state == "released"


@pytest.mark.asyncio
async def test_local_executable_model_does_not_fabricate_new_readiness(test_session, test_user, monkeypatch):
    from types import SimpleNamespace

    from spectra_sherpa.app.models.project import Project
    from spectra_sherpa.app.models.workflow import Workflow
    from spectra_sherpa.app.services import application_release

    monkeypatch.setattr(application_release, "is_local", lambda: True)
    project = Project(user_id=test_user.id, name="Local scientific review")
    test_session.add(project)
    await test_session.flush()
    workflow = Workflow(user_id=test_user.id, project_id=project.id, name="Exploratory")
    test_session.add(workflow)
    await test_session.flush()
    model = SimpleNamespace(
        artifact_uid="unreviewed-local",
        project_id=project.id,
        workflow_id=workflow.id,
        workflow_version_id=1,
        source_run_id=None,
        model_type="pls",
        is_active=True,
        is_deploy_ready=False,
        display_name=None,
        name="Local model",
        training_dataset_id=None,
        training_data_hash=None,
        validation_evidence_digest=None,
    )
    pending = await application_release.ensure_model_release(test_session, model=model, user_id=test_user.id)
    assert pending.state == "revoked"
    assert pending.readiness["review_state"] == "review_required"
    assert not pending.readiness["ready"]
    assert (
        await application_release.ensure_model_release(test_session, model=model, user_id=test_user.id)
    ).state == "revoked"
    model.is_deploy_ready = True
    reviewed = await application_release.ensure_model_release(
        test_session,
        model=model,
        user_id=test_user.id,
        promotion_review={"review_digest": "a" * 64, "protocol": "exploratory"},
    )
    assert reviewed.handle == pending.handle and reviewed.state == "released"
    assert reviewed.readiness["review_state"] == "reviewed"
    model.is_deploy_ready = False
    withdrawn = await application_release.ensure_model_release(test_session, model=model, user_id=test_user.id)
    assert withdrawn.state == "revoked" and not withdrawn.readiness["ready"]


@pytest.mark.asyncio
async def test_canonical_watch_requires_released_identity_even_with_direct_id(test_session, test_user):
    from spectra_sherpa.app.api.v1.routes.deploy import _require_deployment_release
    from spectra_sherpa.app.models.application_release import ApplicationRelease
    from spectra_sherpa.app.models.project import Project
    from spectra_sherpa.app.models.workflow import Workflow

    project = Project(user_id=test_user.id, name="Direct canonical id")
    test_session.add(project)
    await test_session.flush()
    workflow = Workflow(user_id=test_user.id, project_id=project.id, name="Imported")
    test_session.add(workflow)
    await test_session.flush()
    args = dict(user_id=test_user.id, workflow_id=workflow.id, canonical_artifact_id=99)
    with pytest.raises(ValueError, match="Review for promotion"):
        await _require_deployment_release(test_session, **args)
    release = ApplicationRelease(
        handle="app_pending_direct",
        user_id=test_user.id,
        project_id=project.id,
        workflow_id=workflow.id,
        canonical_artifact_id=99,
        origin="campaign_solution",
        state="revoked",
        label="Pending",
    )
    test_session.add(release)
    await test_session.flush()
    with pytest.raises(ValueError, match="Review for promotion"):
        await _require_deployment_release(test_session, **args)
    release.state = "released"
    await test_session.flush()
    await _require_deployment_release(test_session, **args)
    with pytest.raises(ValueError, match="Review for promotion"):
        await _require_deployment_release(test_session, **{**args, "user_id": test_user.id + 1})
