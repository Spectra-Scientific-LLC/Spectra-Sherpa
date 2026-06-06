"""H3 — LoadApplyModelNode artifact access must be project + user scoped.

The DAG node's ``store.load(model_id)`` is purely filesystem-based and
skips all DB ownership checks. PR #161's HTTP routes enforce project/
user alignment via _require_models / _require_dataset_model_project_match;
the DAG node bypasses both.

The route-level validation block now mirrors the data-loader pattern: walk
every ``model.load_apply`` node, read its ``model_id`` param, and require
that the artifact (a) belongs to the current user AND (b) is project-aligned.
"""

from __future__ import annotations

import pytest
from fastapi import HTTPException

from spectra_sherpa.app.models.execution_run import ExecutionRun  # noqa: F401 - shared metadata setup
from spectra_sherpa.app.models.model_artifact import ModelArtifact
from spectra_sherpa.app.models.user import User
from spectra_sherpa.app.services.workflow_access import require_model_artifact_access


async def _make_project_and_workflow(test_session, user: User, *, name: str):
    from spectra_sherpa.app.models.project import Project
    from spectra_sherpa.app.models.workflow import Workflow

    project = Project(user_id=user.id, name=f"{name}-p")
    test_session.add(project)
    await test_session.flush()
    workflow = Workflow(user_id=user.id, project_id=project.id, name=name)
    test_session.add(workflow)
    await test_session.commit()
    return project, workflow


async def _seed_artifact(test_session, *, owner_id: int, project_id: int | None, uid: str = "art-1"):
    artifact = ModelArtifact(
        artifact_uid=uid,
        user_id=owner_id,
        project_id=project_id,
        workflow_id=None,
        workflow_version_id=None,
        node_id="train_1",
        model_type="pls",
        name="m",
        display_name="m",
        artifact_dir=f"/tmp/{uid}",
        integrity_hash="h",
        n_features=4,
        tags=[],
        is_active=True,
    )
    test_session.add(artifact)
    await test_session.commit()
    return artifact


@pytest.mark.asyncio
async def test_load_apply_allows_artifact_in_same_project(test_session, test_user: User):
    project_a, workflow_a = await _make_project_and_workflow(test_session, test_user, name="A")
    await _seed_artifact(test_session, owner_id=test_user.id, project_id=project_a.id, uid="art-same")

    # Same user, same project — must succeed (no raise).
    await require_model_artifact_access(
        test_session,
        "art-same",
        user_id=test_user.id,
        workflow_project_id=project_a.id,
    )


@pytest.mark.asyncio
async def test_load_apply_refuses_artifact_from_different_project(test_session, test_user: User):
    project_a, _ = await _make_project_and_workflow(test_session, test_user, name="A")
    project_b, workflow_b = await _make_project_and_workflow(test_session, test_user, name="B")
    # Artifact lives in project A; workflow lives in project B.
    await _seed_artifact(test_session, owner_id=test_user.id, project_id=project_a.id, uid="art-foreign")

    with pytest.raises(HTTPException) as exc:
        await require_model_artifact_access(
            test_session,
            "art-foreign",
            user_id=test_user.id,
            workflow_project_id=project_b.id,
        )
    assert exc.value.status_code == 404
    assert "not available in this project" in exc.value.detail


@pytest.mark.asyncio
async def test_load_apply_allows_artifact_with_null_project_id(test_session, test_user: User):
    """Legacy / cross-project library artifacts have project_id=None and are
    allowed in any project (this matches existing behavior for shared models)."""
    _, workflow = await _make_project_and_workflow(test_session, test_user, name="legacy")
    await _seed_artifact(test_session, owner_id=test_user.id, project_id=None, uid="art-legacy")

    await require_model_artifact_access(
        test_session,
        "art-legacy",
        user_id=test_user.id,
        workflow_project_id=workflow.project_id,
    )


@pytest.mark.asyncio
async def test_load_apply_refuses_artifact_owned_by_another_user(test_session, test_user: User):
    """Cross-user artifact access — even if the calling user knows the uid."""
    from spectra_sherpa.app.models.user import User as UserModel

    # Create a second user (User model has only `username` + flags, no
    # email / hashed_password — auth in OSS local mode doesn't use them).
    other_user = UserModel(username="other_user_test")
    test_session.add(other_user)
    await test_session.flush()

    _, workflow = await _make_project_and_workflow(test_session, test_user, name="cross")
    await _seed_artifact(test_session, owner_id=other_user.id, project_id=None, uid="art-other-user")

    with pytest.raises(HTTPException) as exc:
        await require_model_artifact_access(
            test_session,
            "art-other-user",
            user_id=test_user.id,
            workflow_project_id=workflow.project_id,
        )
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_load_apply_refuses_unknown_artifact_uid(test_session, test_user: User):
    _, workflow = await _make_project_and_workflow(test_session, test_user, name="unknown")
    with pytest.raises(HTTPException) as exc:
        await require_model_artifact_access(
            test_session,
            "does-not-exist",
            user_id=test_user.id,
            workflow_project_id=workflow.project_id,
        )
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_load_apply_refuses_soft_deleted_artifact(test_session, test_user: User):
    project, workflow = await _make_project_and_workflow(test_session, test_user, name="softdel")
    artifact = await _seed_artifact(test_session, owner_id=test_user.id, project_id=project.id, uid="art-deleted")
    artifact.is_active = False
    await test_session.commit()

    with pytest.raises(HTTPException) as exc:
        await require_model_artifact_access(
            test_session,
            "art-deleted",
            user_id=test_user.id,
            workflow_project_id=workflow.project_id,
        )
    assert exc.value.status_code == 404
