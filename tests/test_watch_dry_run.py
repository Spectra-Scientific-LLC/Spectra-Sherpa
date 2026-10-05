"""Optional checks retain real predictions without gating local monitoring."""

import numpy as np
import pytest
from fastapi import HTTPException

from spectra_sherpa.app.api.v1.routes import deploy
from spectra_sherpa.app.core.config import app_config
from spectra_sherpa.app.lib.fitted_state import LinearRegressionExtract
from spectra_sherpa.app.models.folder_watch import FolderWatch
from spectra_sherpa.app.models.workflow import Workflow
from spectra_sherpa.app.schemas.deploy import FolderWatchUpdate
from spectra_sherpa.app.services.model_store import get_model_store
from spectra_sherpa.app.services.watch_dry_run import latest_receipt, run_dry_run


@pytest.fixture
async def ordinary_watch(test_session, test_user, deployment_artifact_factory, tmp_path, monkeypatch):
    monkeypatch.setattr(app_config, "mode", "local")
    workflow = Workflow(user_id=test_user.id, name="Dry run fixture")
    test_session.add(workflow)
    await test_session.flush()
    artifact = await deployment_artifact_factory(workflow)
    manifest, arrays = LinearRegressionExtract(coef=np.array([2.0, -1.0]), intercept=np.array([0.5])).to_artifact()
    manifest["n_features"] = 2
    store = get_model_store()
    artifact.integrity_hash = store.save_new(artifact.artifact_uid, manifest, arrays)
    artifact.artifact_dir = store.artifact_directory(artifact.artifact_uid)
    folder = tmp_path / "incoming"
    folder.mkdir()
    (folder / "sample.csv").write_text("1000,1100\n1,0\n2,0.5\n3,1\n")
    watch = FolderWatch(
        user_id=test_user.id,
        workflow_id=workflow.id,
        artifact_uid=artifact.artifact_uid,
        workflow_version_id=artifact.workflow_version_id,
        name="My model",
        folder_path=str(folder),
        file_pattern="*.csv",
        settle_time_seconds=0,
        poll_interval_sec=10,
        is_enabled=False,
        processed_files={},
    )
    test_session.add(watch)
    await test_session.commit()
    await test_session.refresh(watch)
    return watch


@pytest.mark.asyncio
@pytest.mark.parametrize("via_patch", [False, True])
async def test_enable_without_check_and_test_while_running(test_session, test_user, ordinary_watch, via_patch):
    watch = ordinary_watch
    if via_patch:
        enabled = await deploy.update_watch(
            watch.id, FolderWatchUpdate(is_enabled=True), session=test_session, current_user=test_user
        )
    else:
        enabled = await deploy.enable_watch(watch.id, session=test_session, current_user=test_user)
    assert enabled.is_enabled
    receipt = await run_dry_run(test_session, watch, "sample.csv")
    assert receipt["status"] == "completed", receipt
    np.testing.assert_allclose(receipt["result_preview"]["deployment_model"]["y_pred"], [[2.5], [4.0], [5.5]])
    assert watch.processed_files == {} and watch.is_enabled
    assert (await latest_receipt(test_session, watch))["run_id"] == receipt["run_id"]


@pytest.mark.asyncio
@pytest.mark.parametrize("failed", [False, True])
async def test_failed_or_stale_check_does_not_block_enable(test_session, test_user, ordinary_watch, failed):
    from pathlib import Path

    path = Path(ordinary_watch.folder_path, "sample.csv")
    if failed:
        path.write_text("1,2,3\n4,5,6\n7,8,9\n")
    receipt = await run_dry_run(test_session, ordinary_watch, "sample.csv")
    assert receipt["status"] == ("failed" if failed else "completed")
    path.write_text("1000,1100\n4,0\n5,1\n")
    enabled = await deploy.update_watch(
        ordinary_watch.id,
        FolderWatchUpdate(is_enabled=True, file_pattern="*"),
        session=test_session,
        current_user=test_user,
    )
    assert enabled.is_enabled


@pytest.mark.asyncio
async def test_live_timing_edit_preserves_poll_and_history(test_session, test_user, ordinary_watch):
    watch = ordinary_watch
    watch.is_enabled = True
    watch.active_poll_token = "ongoing"
    watch.processed_files = {"sample.csv": "done"}
    await test_session.commit()
    generation = watch.configuration_generation
    await deploy.update_watch(
        watch.id,
        FolderWatchUpdate(poll_interval_sec=1, settle_time_seconds=7200),
        session=test_session,
        current_user=test_user,
    )
    assert watch.is_enabled and watch.active_poll_token == "ongoing"
    assert watch.processed_files == {"sample.csv": "done"}
    assert watch.configuration_generation == generation


@pytest.mark.asyncio
async def test_live_source_edit_changes_generation(test_session, test_user, ordinary_watch):
    watch = ordinary_watch
    watch.is_enabled = True
    watch.active_poll_token = "old"
    await test_session.commit()
    generation = watch.configuration_generation
    await deploy.update_watch(
        watch.id, FolderWatchUpdate(file_pattern="*"), session=test_session, current_user=test_user
    )
    assert watch.is_enabled and watch.active_poll_token is None
    assert watch.configuration_generation == generation + 1


@pytest.mark.asyncio
async def test_local_unmarked_fitted_model_can_run(test_session, test_user, ordinary_watch):
    from sqlalchemy import select

    from spectra_sherpa.app.models.model_artifact import ModelArtifact

    model = await test_session.scalar(
        select(ModelArtifact).where(ModelArtifact.artifact_uid == ordinary_watch.artifact_uid)
    )
    model.is_deploy_ready = False
    await test_session.commit()
    assert (await deploy.enable_watch(ordinary_watch.id, session=test_session, current_user=test_user)).is_enabled


@pytest.mark.asyncio
async def test_parent_paths_still_rejected(test_session, ordinary_watch):
    with pytest.raises(ValueError, match="file name"):
        await run_dry_run(test_session, ordinary_watch, "../other.csv")


@pytest.mark.asyncio
async def test_interruption_retained_without_gating(test_session, test_user, ordinary_watch, monkeypatch):
    import asyncio

    from spectra_sherpa.app.services import watch_dry_run

    async def interrupted(*args, **kwargs):
        raise asyncio.CancelledError()

    monkeypatch.setattr(watch_dry_run, "execute_workflow_dataset", interrupted)
    with pytest.raises(asyncio.CancelledError):
        await run_dry_run(test_session, ordinary_watch, "sample.csv")
    assert (await latest_receipt(test_session, ordinary_watch))["status"] == "failed"
    assert (await deploy.enable_watch(ordinary_watch.id, session=test_session, current_user=test_user)).is_enabled


@pytest.mark.asyncio
async def test_live_model_replacement_invalidates_old_poll(
    test_session, test_user, ordinary_watch, deployment_artifact_factory
):
    workflow = await test_session.get(Workflow, ordinary_watch.workflow_id)
    model = await deployment_artifact_factory(workflow)
    ordinary_watch.is_enabled = True
    ordinary_watch.active_poll_token = "old-model"
    ordinary_watch.processed_files = {"sample.csv": "old-result"}
    generation = ordinary_watch.configuration_generation
    await test_session.commit()
    await deploy.update_watch(
        ordinary_watch.id,
        FolderWatchUpdate(artifact_uid=model.artifact_uid),
        session=test_session,
        current_user=test_user,
    )
    assert ordinary_watch.is_enabled and ordinary_watch.active_poll_token is None
    assert ordinary_watch.processed_files == {}
    assert ordinary_watch.configuration_generation == generation + 1


@pytest.mark.asyncio
async def test_optional_check_preserves_active_poll(test_session, ordinary_watch):
    ordinary_watch.is_enabled = True
    ordinary_watch.active_poll_token = "running-poll"
    ordinary_watch.processed_files = {"previous.csv": "done"}
    await test_session.commit()
    assert (await run_dry_run(test_session, ordinary_watch, "sample.csv"))["status"] == "completed"
    assert ordinary_watch.active_poll_token == "running-poll"
    assert ordinary_watch.processed_files == {"previous.csv": "done"}


@pytest.mark.asyncio
@pytest.mark.parametrize("via_patch", [False, True])
async def test_concurrent_edit_is_not_overwritten(test_session, test_user, ordinary_watch, monkeypatch, via_patch):
    from sqlalchemy import update

    original = deploy.resolve_deployment_binding

    async def concurrent(*args, **kwargs):
        binding = await original(*args, **kwargs)
        await test_session.execute(
            update(FolderWatch)
            .where(FolderWatch.id == ordinary_watch.id)
            .values(file_pattern="*.txt")
            .execution_options(synchronize_session=False)
        )
        await test_session.commit()
        return binding

    monkeypatch.setattr(deploy, "resolve_deployment_binding", concurrent)
    with pytest.raises(HTTPException) as exc:
        if via_patch:
            await deploy.update_watch(
                ordinary_watch.id, FolderWatchUpdate(is_enabled=True), session=test_session, current_user=test_user
            )
        else:
            await deploy.enable_watch(ordinary_watch.id, session=test_session, current_user=test_user)
    assert exc.value.status_code == 409
    await test_session.refresh(ordinary_watch)
    assert not ordinary_watch.is_enabled and ordinary_watch.file_pattern == "*.txt"


def test_campaign_star_requires_recorded_validation():
    from spectra_sherpa.app.models.application_release import ApplicationRelease
    from spectra_sherpa.app.services.application_release import release_payload

    release = ApplicationRelease(origin="campaign_solution", state="released", provenance={})
    assert not release_payload(release)["campaign_validation"]["recorded"]
    release.provenance = {"validation_execution_digest": "a" * 64}
    assert release_payload(release)["campaign_validation"]["recorded"]
    release.origin = "saved_run"
    assert not release_payload(release)["campaign_validation"]["recorded"]
    release.origin, release.state = "campaign_solution", "revoked"
    assert not release_payload(release)["campaign_validation"]["recorded"]


@pytest.mark.asyncio
@pytest.mark.parametrize("mode,expected", [("local", True), ("enterprise", False)])
async def test_unmarked_model_release_matches_profile(
    test_session, test_user, ordinary_watch, monkeypatch, mode, expected
):
    from sqlalchemy import select

    from spectra_sherpa.app.models.model_artifact import ModelArtifact
    from spectra_sherpa.app.services.application_release import ensure_model_release

    model = await test_session.scalar(
        select(ModelArtifact).where(ModelArtifact.artifact_uid == ordinary_watch.artifact_uid)
    )
    from spectra_sherpa.app.models.project import Project

    project = Project(user_id=test_user.id, name="Local application")
    test_session.add(project)
    await test_session.flush()
    model.project_id = project.id
    model.is_deploy_ready = False
    monkeypatch.setattr(app_config, "mode", mode)
    if expected:
        release = await ensure_model_release(test_session, model=model, user_id=test_user.id)
        assert release.state == "released"
    else:
        with pytest.raises(ValueError, match="not released"):
            await ensure_model_release(test_session, model=model, user_id=test_user.id)
