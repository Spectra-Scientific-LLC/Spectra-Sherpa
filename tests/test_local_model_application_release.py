"""Local use is distinct from Pro approval and preserves explicit withdrawal."""

from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from spectra_sherpa.app.models.application_release import ApplicationRelease
from spectra_sherpa.app.models.model_artifact import ModelArtifact
from spectra_sherpa.app.models.project import Project
from spectra_sherpa.app.models.workflow import Workflow
from spectra_sherpa.app.models.workflow_version import WorkflowVersion


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "mode,invalid",
    [("local", False), ("local", True), ("local", "integrity"), ("enterprise", False), ("hybrid", False)],
)
async def test_readiness_requires_current_binding_locally_and_review_in_managed_modes(
    test_session, test_user, monkeypatch, mode, invalid
):
    from spectra_sherpa.app.api.v1.routes.models import ModelUpdateRequest, update_model
    from spectra_sherpa.app.core import mode_policy
    from spectra_sherpa.app.services import application_release, deployment_binding

    monkeypatch.setattr(mode_policy, "is_local", lambda: mode == "local")
    monkeypatch.setattr(application_release, "is_local", lambda: mode == "local")
    project = Project(user_id=test_user.id, name="Local application control")
    test_session.add(project)
    await test_session.flush()
    workflow = Workflow(user_id=test_user.id, project_id=project.id, name="Exact producing workflow")
    test_session.add(workflow)
    await test_session.flush()
    version = WorkflowVersion(
        workflow_id=workflow.id, version_number=1, created_by=test_user.id, snapshot={"nodes": [], "edges": []}
    )
    test_session.add(version)
    await test_session.flush()
    model = ModelArtifact(
        artifact_uid="local-readiness-control",
        user_id=test_user.id,
        project_id=project.id,
        workflow_id=workflow.id,
        workflow_version_id=version.id,
        node_id="fit",
        model_type="pls",
        name="Saved fit",
        artifact_dir="test-only",
        integrity_hash="a" * 64,
        n_features=4,
        is_active=True,
        is_deploy_ready=False,
    )
    test_session.add(model)
    await test_session.flush()
    from spectra_sherpa.core.model_artifact import ModelArtifactIntegrityError

    failure = (
        ModelArtifactIntegrityError("digest mismatch")
        if invalid == "integrity"
        else ValueError("artifact unavailable") if invalid else None
    )
    binding = AsyncMock(side_effect=failure)
    monkeypatch.setattr(deployment_binding, "resolve_deployment_binding", binding)
    if mode != "local" or invalid:
        with pytest.raises(HTTPException) as caught:
            await update_model(model.artifact_uid, ModelUpdateRequest(is_deploy_ready=True), test_session, test_user)
        assert caught.value.status_code == (409 if invalid else 422)
        assert not model.is_deploy_ready
        assert await test_session.scalar(select(ApplicationRelease)) is None
        assert binding.await_count == int(mode == "local")
        return
    result = await update_model(model.artifact_uid, ModelUpdateRequest(is_deploy_ready=True), test_session, test_user)
    assert result.is_deploy_ready
    binding.assert_any_await(
        test_session, user_id=test_user.id, workflow_id=workflow.id, artifact_uid=model.artifact_uid
    )
    release = await test_session.scalar(select(ApplicationRelease))
    assert release.state == "released"
    assert release.provenance["promotion_review"] is None
    assert release.readiness["review_state"] == "not_required"
    await update_model(model.artifact_uid, ModelUpdateRequest(is_deploy_ready=False), test_session, test_user)
    assert release.state == "revoked"
    assert release.provenance["application_withdrawn"] is True
    await application_release.ensure_model_release(test_session, model=model, user_id=test_user.id)
    assert release.state == "revoked"
    binding.side_effect = ModelArtifactIntegrityError("digest mismatch")
    unavailable = await application_release.ensure_model_release(
        test_session, model=model, user_id=test_user.id, application_enabled=True
    )
    assert unavailable.state == "revoked"
    assert not unavailable.readiness["ready"]
