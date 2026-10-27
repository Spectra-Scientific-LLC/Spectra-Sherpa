"""Stopped-trial custody is distinct from automatic crash recovery authority."""

import asyncio
import logging
import threading
from uuid import uuid4

import pytest
from sqlalchemy import update

from spectra_sherpa.app.models.model_publication import ModelPublication
from spectra_sherpa.app.services import model_store, storage_custody
from tests.test_publication_lease import expired, publication


@pytest.fixture(autouse=True)
def unsupported_directory_durability(monkeypatch):
    # Exercise the Windows policy on every runner, without pretending POSIX
    # directory fsync is available on Windows or swallowing a genuine failure.
    monkeypatch.setattr(model_store, "durable_publication_recovery_supported", lambda: False)


@pytest.mark.asyncio
async def test_crash_recovery_preserves_files_but_joined_trial_can_clean(test_session, test_user, tmp_path, caplog):
    caplog.set_level(logging.WARNING)
    store, writer, uid, artifact = await publication(test_session, test_user, tmp_path)
    scratch = store.models_dir / f".staging-{uid}-partial"
    scratch.mkdir()
    sentinel = store.models_dir / "unrelated"
    sentinel.mkdir()
    await expired(test_session, uid)
    await storage_custody.reconcile_terminal_publications(test_session, store=store)
    claim = await test_session.get(ModelPublication, uid, populate_existing=True)
    assert claim.cleanup_requested and claim.reclaimed_at is None
    assert scratch.exists() and (store.models_dir / uid / "arrays.npz").exists()
    assert "Automatic publication recovery is unavailable" in caplog.text
    with pytest.raises(ValueError, match="ownership expired"):
        await model_store.persist_model_artifact_records(test_session, [artifact], writer.user_id)
    await test_session.rollback()
    await writer.discard_trial()
    assert not scratch.exists() and not (store.models_dir / uid).exists()
    assert sentinel.exists()
    claim = await test_session.get(ModelPublication, uid, populate_existing=True)
    assert claim.cleanup_requested and claim.reclaimed_at is None
    assert store._publication_fence(uid).exists()
    with pytest.raises(model_store.ModelArtifactCollisionError):
        store.save_new(uid, {}, {})
    with pytest.raises(ValueError, match="Trial execution has stopped"):
        await writer.save(str(uuid4()), {}, {})


@pytest.mark.asyncio
async def test_stopped_owner_cannot_clean_another_attempt(test_session, test_user, tmp_path):
    store, writer, uid, _ = await publication(test_session, test_user, tmp_path)
    _, other, other_uid, _ = await publication(test_session, test_user, tmp_path)
    await test_session.execute(
        update(ModelPublication).where(ModelPublication.artifact_uid == other_uid).values(cleanup_requested=True)
    )
    await test_session.commit()
    writer.claimed_uids.add(other_uid)
    await writer.discard_trial()
    assert not (store.models_dir / uid).exists()
    assert (store.models_dir / other_uid / "arrays.npz").exists()
    claim = await test_session.get(ModelPublication, other_uid, populate_existing=True)
    assert claim.attempt_id == other.attempt_id and claim.reclaimed_at is None


@pytest.mark.asyncio
@pytest.mark.parametrize("cancel_writer", [False, True])
async def test_terminal_cleanup_joins_writers_before_removal(
    test_session, test_user, tmp_path, monkeypatch, cancel_writer
):
    store, writer, uid, _ = await publication(test_session, test_user, tmp_path)
    next_uid = str(uuid4())
    entered, release = threading.Event(), threading.Event()
    original = store.save_new

    def held(*args):
        entered.set()
        if not release.wait(10):
            raise RuntimeError("test writer barrier not released")
        return original(*args)

    monkeypatch.setattr(store, "save_new", held)
    save = asyncio.create_task(writer.save(next_uid, {}, {}))
    cleanup = None
    try:
        assert await asyncio.to_thread(entered.wait, 5)
        if cancel_writer:
            save.cancel()
        cleanup = asyncio.create_task(writer.discard_trial())
        await asyncio.sleep(0)
        assert not cleanup.done()
        assert (store.models_dir / uid).exists()
        with pytest.raises(ValueError, match="Trial execution has stopped"):
            await writer.save(str(uuid4()), {}, {})
        release.set()
        if cancel_writer:
            with pytest.raises(asyncio.CancelledError):
                await save
        else:
            await save
        await asyncio.wait_for(cleanup, 5)
        assert not (store.models_dir / uid).exists()
        assert not (store.models_dir / next_uid).exists()
    finally:
        release.set()
        await asyncio.gather(save, *([cleanup] if cleanup else []), return_exceptions=True)


@pytest.mark.asyncio
async def test_terminal_cleanup_preserves_overlapping_retained_paths(test_session, test_user, tmp_path):
    from spectra_sherpa.app.models.model_artifact import ModelArtifact

    store, writer, uid, _ = await publication(test_session, test_user, tmp_path)
    test_session.add(
        ModelArtifact(
            artifact_uid=str(uuid4()),
            user_id=test_user.id,
            node_id="retained",
            model_type="pca",
            name="retained",
            artifact_dir=store.artifact_directory(uid),
            integrity_hash="a" * 64,
            n_features=2,
        )
    )
    await test_session.commit()
    await writer.discard_trial()
    assert (store.models_dir / uid / "arrays.npz").exists()
