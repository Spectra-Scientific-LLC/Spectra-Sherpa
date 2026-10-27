"""Execution ownership revokes late writers without treating age as abort proof."""

import asyncio
import weakref
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import numpy as np
import pytest
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from spectra_sherpa.app.models.model_artifact import ModelArtifact
from spectra_sherpa.app.models.model_publication import ModelPublication
from spectra_sherpa.app.services import storage_custody as custody
from spectra_sherpa.app.services.model_store import (
    ModelArtifactCollisionError,
    ModelStore,
    durable_publication_recovery_supported,
    persist_model_artifact_records,
)


async def expired(session, uid):
    await session.execute(
        update(ModelPublication)
        .where(ModelPublication.artifact_uid == uid)
        .values(lease_expires_at=datetime.now(timezone.utc) - timedelta(days=1))
    )
    await session.commit()


async def publication(session, user, root):
    await session.commit()
    store = ModelStore(root)
    writer = custody.OwnedModelWriter(store, async_sessionmaker(session.bind, expire_on_commit=False), user.id)
    uid = str(uuid4())
    digest = await writer.save(uid, {}, {"scores": np.eye(2)})
    return (
        store,
        writer,
        uid,
        {
            "artifact_uid": uid,
            "artifact_dir": store.artifact_directory(uid),
            "integrity_hash": digest,
            "publication_attempt_id": writer.attempt_id,
        },
    )


@pytest.mark.asyncio
@pytest.mark.skipif(
    not durable_publication_recovery_supported(),
    reason="Automatic crash recovery requires directory durability; unsupported platforms retain custody",
)
async def test_expired_owned_claim_reclaims_scratch_and_permanently_fences_identity(test_session, test_user, tmp_path):
    store, writer, uid, artifact = await publication(test_session, test_user, tmp_path)
    scratch = store.models_dir / f".staging-{uid}-crashed"
    scratch.mkdir()
    (scratch / "partial").write_bytes(b"partial compression")
    # Retain this stale ORM instance to prove registration reloads the fence.
    stale = await test_session.get(ModelPublication, uid)
    await expired(test_session, uid)
    async with writer.factory() as other:
        await custody.reconcile_terminal_publications(other, store=store)
    assert stale.cleanup_requested is False
    assert not scratch.exists()
    assert not (store.models_dir / uid).exists()
    with pytest.raises(ValueError, match="ownership expired"):
        await persist_model_artifact_records(test_session, [artifact], test_user.id)
    await test_session.rollback()
    claim = await test_session.get(ModelPublication, uid, populate_existing=True)
    assert claim.cleanup_requested and claim.reclaimed_at is not None
    for save in (store.save, store.save_new):
        with pytest.raises(ModelArtifactCollisionError, match="reclaimed"):
            save(uid, {}, {})
    assert not list(store.models_dir.glob(f".staging-{uid}-*"))


@pytest.mark.asyncio
async def test_legacy_unowned_claim_is_not_reclaimed_by_age(test_session, test_user, tmp_path):
    store = ModelStore(tmp_path)
    uid = str(uuid4())
    store.save_new(uid, {}, {})
    test_session.add(
        ModelPublication(artifact_uid=uid, user_id=test_user.id, artifact_dir=store.artifact_directory(uid))
    )
    await test_session.commit()
    await expired(test_session, uid)
    await custody.reconcile_terminal_publications(test_session, store=store)
    assert (store.models_dir / uid / "manifest.json").exists()
    assert not (await test_session.get(ModelPublication, uid)).cleanup_requested


@pytest.mark.asyncio
@pytest.mark.parametrize("mutation", ["missing", "wrong_attempt", "wrong_path"])
async def test_registration_requires_matching_execution_receipt(test_session, test_user, tmp_path, mutation):
    store, writer, uid, artifact = await publication(test_session, test_user, tmp_path)
    if mutation == "missing":
        artifact.pop("publication_attempt_id")
    elif mutation == "wrong_attempt":
        artifact["publication_attempt_id"] = str(uuid4())
    else:
        artifact["artifact_dir"] = str(tmp_path / "elsewhere")
    with pytest.raises(ValueError, match="execution ownership"):
        await persist_model_artifact_records(test_session, [artifact], test_user.id)
    assert await test_session.scalar(select(ModelArtifact)) is None
    assert (store.models_dir / uid / "arrays.npz").exists()


@pytest.mark.asyncio
@pytest.mark.parametrize("landed", [False, True])
async def test_unknown_fence_commit_only_reclaims_if_durable(test_session, test_user, tmp_path, landed):
    store, writer, uid, artifact = await publication(test_session, test_user, tmp_path)
    await expired(test_session, uid)

    class LostAcknowledgement(AsyncSession):
        async def commit(self):
            if landed:
                await super().commit()
            raise RuntimeError("lost fence acknowledgement")

    async with async_sessionmaker(test_session.bind, class_=LostAcknowledgement)() as session:
        await custody._fence_expired_publications(session)
    # Fencing alone never removes bytes, irrespective of COMMIT outcome.
    assert (store.models_dir / uid / "arrays.npz").exists()
    claim = await test_session.get(ModelPublication, uid, populate_existing=True)
    assert claim.cleanup_requested == landed
    if landed:
        with pytest.raises(ValueError, match="ownership expired"):
            await persist_model_artifact_records(test_session, [artifact], test_user.id)
    else:
        await persist_model_artifact_records(test_session, [artifact], test_user.id)
        await test_session.commit()


@pytest.mark.asyncio
async def test_renewal_is_scoped_to_execution_and_never_revives_fenced_claim(
    test_session, test_user, tmp_path, monkeypatch
):
    store, writer, uid, artifact = await publication(test_session, test_user, tmp_path)
    writer._renewal_task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await writer._renewal_task
    await expired(test_session, uid)
    monkeypatch.setattr(custody, "PUBLICATION_RENEWAL_SECONDS", 0.01)
    owner = asyncio.create_task(asyncio.Event().wait())
    renewal = asyncio.create_task(
        custody._renew_while_executing(writer.factory, test_user.id, writer.attempt_id, weakref.ref(owner))
    )
    try:
        for _ in range(100):
            await asyncio.sleep(0.01)
            claim = await test_session.get(ModelPublication, uid, populate_existing=True)
            if claim.lease_expires_at.replace(tzinfo=timezone.utc) > datetime.now(timezone.utc):
                break
        else:
            pytest.fail("live execution failed to renew")
        await test_session.rollback()
        await custody.reconcile_terminal_publications(test_session, store=store)
        assert (store.models_dir / uid).exists()
        await writer.discard_trial()
        await asyncio.wait_for(renewal, 2)
        claim = await test_session.get(ModelPublication, uid, populate_existing=True)
        assert (claim.reclaimed_at is not None) == durable_publication_recovery_supported()
    finally:
        owner.cancel()
        renewal.cancel()
        await asyncio.gather(owner, renewal, return_exceptions=True)


@pytest.mark.asyncio
async def test_expired_claim_never_deletes_other_owners_scratch_path(test_session, test_user, tmp_path):
    store, writer, uid, artifact = await publication(test_session, test_user, tmp_path)
    scratch = store.models_dir / f".staging-{uid}-protected"
    scratch.mkdir()
    test_session.add(
        ModelArtifact(
            artifact_uid=str(uuid4()),
            user_id=test_user.id,
            node_id="other",
            model_type="pca",
            name="retained",
            artifact_dir=str(scratch),
            integrity_hash="a" * 64,
            n_features=2,
        )
    )
    await test_session.commit()
    await expired(test_session, uid)
    await custody.reconcile_terminal_publications(test_session, store=store)
    claim = await test_session.get(ModelPublication, uid, populate_existing=True)
    assert claim.cleanup_requested and claim.reclaimed_at is None
    assert scratch.exists() and (store.models_dir / uid).exists()


@pytest.mark.asyncio
async def test_fenced_identity_never_recovers_backup(test_session, test_user, tmp_path):
    from spectra_sherpa.app.services.model_store import reconcile_orphan_artifacts

    store, writer, uid, _ = await publication(test_session, test_user, tmp_path)
    backup = store.models_dir / f"{uid}.old-preserved"
    (store.models_dir / uid).rename(backup)
    await expired(test_session, uid)
    await reconcile_orphan_artifacts(test_session, store=store, grace_seconds=0)
    assert backup.exists() and not (store.models_dir / uid).exists()
    assert (backup / "arrays.npz").exists()


@pytest.mark.asyncio
async def test_missing_claim_cannot_downgrade_owned_registration_to_legacy(test_session, test_user, tmp_path):
    from sqlalchemy import delete

    store, writer, uid, artifact = await publication(test_session, test_user, tmp_path)
    await test_session.execute(delete(ModelPublication).where(ModelPublication.artifact_uid == uid))
    await test_session.commit()
    with pytest.raises(ValueError, match="ownership is missing"):
        await persist_model_artifact_records(test_session, [artifact], test_user.id)
    assert await test_session.scalar(select(ModelArtifact)) is None


@pytest.mark.asyncio
@pytest.mark.skipif(
    not durable_publication_recovery_supported(),
    reason="Directory-fsync injection requires the native primitive; unsupported recovery has separate tests",
)
@pytest.mark.parametrize("failed_barrier", [1, 3])
async def test_cleanup_after_storage_fence_failure_is_retryable(
    test_session, test_user, tmp_path, monkeypatch, failed_barrier
):
    import os
    import stat

    from spectra_sherpa.app.services import model_store

    store, writer, uid, _ = await publication(test_session, test_user, tmp_path)
    await expired(test_session, uid)
    original = os.fsync
    calls = 0

    def fail_fence(fd):
        nonlocal calls
        if stat.S_ISDIR(os.fstat(fd).st_mode):
            calls += 1
            if calls == failed_barrier:
                raise OSError("injected directory durability failure")
        original(fd)

    monkeypatch.setattr(model_store.os, "fsync", fail_fence)
    await custody.reconcile_terminal_publications(test_session, store=store)
    assert calls == failed_barrier
    assert (store.models_dir / uid / "arrays.npz").exists() == (failed_barrier == 1)
    assert (await test_session.get(ModelPublication, uid, populate_existing=True)).reclaimed_at is None
    monkeypatch.setattr(model_store.os, "fsync", original)
    await custody.reconcile_terminal_publications(test_session, store=store)
    assert not (store.models_dir / uid).exists()
    assert (await test_session.get(ModelPublication, uid, populate_existing=True)).reclaimed_at is not None


@pytest.mark.asyncio
async def test_mixed_batch_preflights_every_claim_before_any_artifact_io(
    test_session, test_user, tmp_path, monkeypatch
):
    from spectra_sherpa.app.services import model_store

    store, writer, uid, artifact = await publication(test_session, test_user, tmp_path)
    bad = dict(artifact, publication_attempt_id="wrong")
    good_legacy = dict(artifact, artifact_uid=str(uuid4()))
    good_legacy.pop("publication_attempt_id")

    async def unexpected(*args, **kwargs):
        pytest.fail("durability side effect before complete admission")

    monkeypatch.setattr(model_store, "_persist_model_artifact_durably_if_configured", unexpected)
    with pytest.raises(ValueError, match="execution ownership"):
        await persist_model_artifact_records(test_session, [good_legacy, bad], test_user.id)
    assert await test_session.scalar(select(ModelArtifact)) is None


@pytest.mark.asyncio
async def test_recovery_loop_is_cancellable_and_survives_one_failed_pass(monkeypatch):
    from contextlib import asynccontextmanager

    passes = []
    reached = asyncio.Event()

    @asynccontextmanager
    async def factory():
        yield object()

    async def recover(*args, **kwargs):
        passes.append(True)
        if len(passes) == 1:
            raise OSError("transient database outage")
        reached.set()

    monkeypatch.setattr(custody, "reconcile_terminal_publications", recover)
    task = asyncio.create_task(custody.publication_recovery_loop(factory, object(), interval=0.001))
    await asyncio.wait_for(reached.wait(), 1)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert len(passes) >= 2


@pytest.mark.asyncio
async def test_standalone_headless_lifecycle_recovers_without_workbench(test_session, test_user, tmp_path, monkeypatch):
    from spectra_sherpa.app.api import headless_app
    from spectra_sherpa.app.services import model_store

    store, writer, uid, _ = await publication(test_session, test_user, tmp_path)
    await expired(test_session, uid)
    monkeypatch.setattr(headless_app, "async_session", writer.factory)
    monkeypatch.setattr(model_store, "init_model_store", lambda *args: None)
    monkeypatch.setattr(model_store, "get_model_store", lambda: store)
    monkeypatch.setattr(
        "spectra_sherpa.app.services.canonical_artifact_store.init_canonical_artifact_store", lambda *args: None
    )
    monkeypatch.delenv("HEADLESS_WORKFLOW_ID", raising=False)
    async with headless_app.lifespan(headless_app.app):
        assert (store.models_dir / uid).exists() == (not durable_publication_recovery_supported())
        tasks = [task for task in asyncio.all_tasks() if task.get_name() == "model-publication-recovery"]
        assert len(tasks) == 1 and not tasks[0].done()
    assert tasks[0].done()


def test_publication_migration_refuses_downgrade_with_owned_receipt(tmp_path):
    import sqlalchemy as sa

    from tests.test_init_db_bootstrap import _run_downgrade, _run_upgrade

    database = tmp_path / "owned.db"
    url = f"sqlite+aiosqlite:///{database}"
    _run_upgrade(url, "head")
    engine = sa.create_engine(f"sqlite:///{database}")
    with engine.begin() as connection:
        connection.execute(sa.text("INSERT INTO user(id,username,is_active) VALUES(1,'owned',1)"))
        connection.execute(sa.text("""INSERT INTO model_publication(artifact_uid,user_id,artifact_dir,attempt_id)
            VALUES('owned',1,'models/owned','attempt')"""))
    with pytest.raises(RuntimeError, match="offline custody reconciliation"):
        _run_downgrade(url, "q6r8s0t2u994")
    with engine.connect() as connection:
        assert connection.scalar(sa.text("SELECT attempt_id FROM model_publication")) == "attempt"
    engine.dispose()
