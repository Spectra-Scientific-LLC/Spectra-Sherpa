"""A failed on-disk purge must not report success."""

from __future__ import annotations

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from spectra_sherpa.app.api.v1.routes import models as models_route
from spectra_sherpa.app.models.folder_watch import FolderWatch
from spectra_sherpa.app.models.model_artifact import ModelArtifact
from spectra_sherpa.app.models.project import Project
from spectra_sherpa.app.models.workflow import Workflow


async def _seed(test_session, test_user) -> str:
    uid = "uid-purge-test"
    test_session.add(
        ModelArtifact(
            artifact_uid=uid,
            user_id=test_user.id,
            node_id="n",
            model_type="pls",
            name="m",
            artifact_dir="/tmp/whatever",
            integrity_hash="x",
            n_features=3,
        )
    )
    await test_session.commit()
    return uid


@pytest.fixture(autouse=True)
def _silence_audit(monkeypatch):
    # This test is about the purge-failure path, not auditing.
    from spectra_sherpa.app.services import audit

    monkeypatch.setattr(audit.audit_emitter, "emit", lambda **_kw: None)


class _Store:
    def __init__(self, exc: Exception | None):
        self._exc = exc
        self.called = False

    def delete(self, _uid: str) -> None:
        self.called = True
        if self._exc is not None:
            raise self._exc


async def test_purge_failure_surfaces_500_not_204(test_session, test_user, monkeypatch):
    uid = await _seed(test_session, test_user)
    store = _Store(OSError("disk gone"))
    monkeypatch.setattr("spectra_sherpa.app.services.model_store.get_model_store", lambda: store)

    with pytest.raises(HTTPException) as ei:
        await models_route.delete_model(
            artifact_uid=uid, purge=True, _dg=None, session=test_session, current_user=test_user
        )

    assert ei.value.status_code == 500
    assert "purge" in ei.value.detail.lower()
    assert store.called is True
    # The soft-delete is still durable (retry-safe): the row remains,
    # now inactive, so a re-issued delete?purge=true can retry the disk
    # removal.
    refreshed = await test_session.get(ModelArtifact, (await _row_id(test_session, uid)))
    assert refreshed.is_active is False


async def test_purge_success_returns_204(test_session, test_user, monkeypatch):
    uid = await _seed(test_session, test_user)
    store = _Store(None)
    monkeypatch.setattr("spectra_sherpa.app.services.model_store.get_model_store", lambda: store)

    resp = await models_route.delete_model(
        artifact_uid=uid, purge=True, _dg=None, session=test_session, current_user=test_user
    )

    assert resp.status_code == 204
    assert store.called is True


async def test_model_bound_to_folder_watch_cannot_be_deleted(test_session, test_user, monkeypatch):
    uid = await _seed(test_session, test_user)
    project = Project(user_id=test_user.id, name="Watch project")
    test_session.add(project)
    await test_session.flush()
    workflow = Workflow(user_id=test_user.id, project_id=project.id, name="Watch workflow")
    test_session.add(workflow)
    await test_session.flush()
    artifact = (await test_session.execute(select(ModelArtifact).where(ModelArtifact.artifact_uid == uid))).scalar_one()
    artifact.project_id = project.id
    artifact.workflow_id = workflow.id
    test_session.add(
        FolderWatch(
            user_id=test_user.id,
            workflow_id=workflow.id,
            artifact_uid=uid,
            name="JF prediction watch",
            folder_path="/srv/spectra/jf",
            is_enabled=True,
        )
    )
    await test_session.commit()
    store = _Store(None)
    monkeypatch.setattr("spectra_sherpa.app.services.model_store.get_model_store", lambda: store)

    with pytest.raises(HTTPException) as exc:
        await models_route.delete_model(
            artifact_uid=uid, purge=True, _dg=None, session=test_session, current_user=test_user
        )

    assert exc.value.status_code == 409
    assert "JF prediction watch" in exc.value.detail
    assert store.called is False


async def _row_id(test_session, uid: str) -> int:
    from sqlalchemy import select

    res = await test_session.execute(select(ModelArtifact.id).where(ModelArtifact.artifact_uid == uid))
    return int(res.scalar_one())
