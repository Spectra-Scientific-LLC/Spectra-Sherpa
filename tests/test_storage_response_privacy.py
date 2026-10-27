"""Storage diagnostics stay server-side; scientific validation stays useful."""

import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from spectra_sherpa.app.api.error_details import validation_or_storage_detail

PRIVATE_PATH = "/private/operator-data/retained-model.npz"


def wrapped_storage_error(*, suppressed=False):
    try:
        raise OSError(13, "Permission denied", PRIVATE_PATH)
    except OSError as cause:
        try:
            if suppressed:
                raise ValueError(f"Cannot read saved evidence: {cause}") from None
            raise ValueError(f"Cannot read saved evidence: {cause}") from cause
        except ValueError as exc:
            return exc


@pytest.mark.parametrize("kind", ["direct", "wrapped", "suppressed", "unexpected", "cycle", "group"])
def test_storage_detail_redacts_diagnostics_but_logs_them(kind, caplog):
    caplog.set_level(logging.WARNING)
    error = OSError(13, "Permission denied", PRIVATE_PATH)
    if kind in {"wrapped", "suppressed"}:
        error = wrapped_storage_error(suppressed=kind == "suppressed")
    elif kind == "unexpected":
        error = RuntimeError(PRIVATE_PATH)
    elif kind == "cycle":
        error.__cause__ = error
    elif kind == "group":
        wrapped = ValueError(f"Cannot load {PRIVATE_PATH}")
        wrapped.__cause__ = ExceptionGroup("Storage failures", [error])
        error = wrapped
    message = validation_or_storage_detail(error, fallback="Check saved evidence.", logger=logging.getLogger(__name__))
    assert message == "Check saved evidence."
    assert PRIVATE_PATH not in message
    assert PRIVATE_PATH in caplog.text


def test_validation_refusal_is_preserved():
    reason = "Held-out evaluation requires the same split's training branch."
    assert (
        validation_or_storage_detail(ValueError(reason), fallback="Unavailable", logger=logging.getLogger(__name__))
        == reason
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "site", ["folder", "handle", "update_binding", "update_lock", "enable_binding", "enable_lock", "dry_run"]
)
@pytest.mark.parametrize("storage", [False, True])
async def test_watch_boundaries_preserve_refusals_not_storage_paths(site, storage, monkeypatch, caplog):
    caplog.set_level(logging.WARNING)
    from spectra_sherpa.app.api.v1.routes import deploy
    from spectra_sherpa.app.core import mode_policy
    from spectra_sherpa.app.models.folder_watch import FolderWatch
    from spectra_sherpa.app.schemas.deploy import FolderWatchUpdate
    from spectra_sherpa.app.services import batch_predict, watch_dry_run

    refusal = "Watch changed while saving. Reload it and retry."
    error = wrapped_storage_error() if storage else ValueError(refusal)
    watch = FolderWatch(id=1, user_id=1, workflow_id=1, is_enabled=False)
    session = AsyncMock()
    user = SimpleNamespace(id=1)
    monkeypatch.setattr(deploy, "_get_user_watch", AsyncMock(return_value=watch))
    monkeypatch.setattr(watch_dry_run, "mutation_snapshot", lambda _: {})
    monkeypatch.setattr(mode_policy, "is_local", lambda: True)
    monkeypatch.setattr(mode_policy, "is_multi_user", lambda: False)
    monkeypatch.setattr(deploy, "_require_deployment_release", AsyncMock())
    monkeypatch.setattr(deploy, "resolve_deployment_binding", AsyncMock())
    monkeypatch.setattr(watch_dry_run, "lock_unchanged_watch", AsyncMock())
    kwargs = {"session": session, "current_user": user}
    with pytest.raises(HTTPException) as caught:
        if site == "dry_run":
            monkeypatch.setattr(watch_dry_run, "run_dry_run", AsyncMock(side_effect=error))
            await deploy.dry_run_watch(1, deploy.WatchDryRunRequest(file_name="sample.csv"), **kwargs)
        elif site.startswith("enable"):
            owner, method = (
                (deploy, "resolve_deployment_binding")
                if site.endswith("binding")
                else (watch_dry_run, "lock_unchanged_watch")
            )
            monkeypatch.setattr(owner, method, AsyncMock(side_effect=error))
            await deploy.enable_watch(1, **kwargs)
        else:
            payload = {}
            if site == "folder":
                payload = {"folder_path": "/source"}
                monkeypatch.setattr(batch_predict, "validate_user_folder_path", AsyncMock(side_effect=error))
            elif site == "handle":
                payload = {"application_handle": "application-1"}
                monkeypatch.setattr(deploy, "_resolve_application_handle", AsyncMock(side_effect=error))
            elif site == "update_binding":
                payload = {"is_enabled": True}
                monkeypatch.setattr(deploy, "resolve_deployment_binding", AsyncMock(side_effect=error))
            else:
                monkeypatch.setattr(watch_dry_run, "lock_unchanged_watch", AsyncMock(side_effect=error))
            await deploy.update_watch(1, FolderWatchUpdate(**payload), **kwargs)
    assert caught.value.status_code == (409 if site.endswith("lock") else 422)
    assert PRIVATE_PATH not in caught.value.detail
    if site == "folder":
        assert caught.value.detail == "Choose an existing folder you can access."
    elif storage:
        assert "Check source and model availability" in caught.value.detail
        assert PRIVATE_PATH in caplog.text
    else:
        assert caught.value.detail == refusal
    session.commit.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["create", "update"])
async def test_watch_path_containment_hides_configured_root(mode, tmp_path, monkeypatch, caplog):
    from spectra_sherpa.app.api.v1.routes import deploy
    from spectra_sherpa.app.core import config, mode_policy
    from spectra_sherpa.app.models.folder_watch import FolderWatch
    from spectra_sherpa.app.schemas.deploy import FolderWatchCreate, FolderWatchUpdate
    from spectra_sherpa.app.services import watch_dry_run

    caplog.set_level(logging.WARNING)
    private_root = tmp_path / "private-server-root"
    private_root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    monkeypatch.setattr(config, "settings", SimpleNamespace(data_dir=private_root))
    monkeypatch.setattr(mode_policy, "is_multi_user", lambda: True)
    monkeypatch.setattr(deploy, "_get_user_watch", AsyncMock(return_value=FolderWatch(id=1, user_id=1, workflow_id=1)))
    monkeypatch.setattr(watch_dry_run, "mutation_snapshot", lambda _: {})
    session = AsyncMock()
    user = SimpleNamespace(id=1)
    with pytest.raises(HTTPException) as caught:
        if mode == "create":
            await deploy.create_watch(
                FolderWatchCreate(name="Watch", workflow_id=1, folder_path=str(outside), application_handle="app-1"),
                session=session,
                current_user=user,
            )
        else:
            await deploy.update_watch(
                1, FolderWatchUpdate(folder_path=str(outside)), session=session, current_user=user
            )
    assert caught.value.status_code == 422
    assert caught.value.detail == "Choose an existing folder under one of your experiment data directories."
    assert str(private_root) not in caught.value.detail
    assert str(private_root) in caplog.text
    session.commit.assert_not_awaited()
