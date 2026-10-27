"""Temporary model custody ends explicitly, never through an age heuristic."""

from uuid import uuid4

import numpy as np
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from spectra_sherpa.app.models.model_publication import ModelPublication
from spectra_sherpa.app.services.model_store import ModelStore, reconcile_orphan_artifacts
from spectra_sherpa.app.services.storage_custody import OwnedModelWriter


@pytest.mark.asyncio
async def test_failed_duplicate_claim_never_grants_cleanup_custody(test_session, test_user, tmp_path):
    from sqlalchemy.exc import IntegrityError

    await test_session.commit()
    store = ModelStore(tmp_path)
    uid = str(uuid4())
    test_session.add(
        ModelPublication(artifact_uid=uid, user_id=test_user.id, artifact_dir=store.artifact_directory(uid))
    )
    await test_session.commit()
    factory = async_sessionmaker(test_session.bind, expire_on_commit=False)
    writer = OwnedModelWriter(store, factory, test_user.id)
    with pytest.raises(IntegrityError):
        await writer.save(uid, {}, {})
    store.save_new(uid, {"model_type": "pca"}, {"scores": np.eye(2)})
    await writer.discard_trial()
    assert not (await test_session.get(ModelPublication, uid)).cleanup_requested
    assert (store.models_dir / uid / "arrays.npz").exists()


@pytest.mark.asyncio
@pytest.mark.parametrize("child", [False, True])
@pytest.mark.parametrize("relative", [False, True])
async def test_other_owner_retained_path_prevents_terminal_cleanup(test_session, test_user, tmp_path, child, relative):
    from spectra_sherpa.app.models.model_artifact import ModelArtifact
    from spectra_sherpa.app.models.user import User

    await test_session.commit()
    factory = async_sessionmaker(test_session.bind, expire_on_commit=False)
    store = ModelStore(tmp_path)
    writer = OwnedModelWriter(store, factory, test_user.id)
    uid = str(uuid4())
    await writer.save(uid, {}, {"scores": np.eye(2)})
    other = User(username="other-retained-owner", is_active=True)
    test_session.add(other)
    await test_session.flush()
    path = store.models_dir / uid
    recorded_path = path / "child" if child else path
    if relative:
        recorded_path = recorded_path.relative_to(tmp_path)
    test_session.add(
        ModelArtifact(
            artifact_uid=str(uuid4()),
            user_id=other.id,
            node_id="retained",
            model_type="pca",
            name="Historical",
            artifact_dir=str(recorded_path),
            integrity_hash="a" * 64,
            n_features=2,
        )
    )
    await test_session.commit()
    await writer.discard_trial()
    assert (path / "arrays.npz").exists()
    assert await test_session.get(ModelPublication, uid) is not None


@pytest.mark.asyncio
async def test_cancelled_trial_waits_for_actual_writer_before_cleanup(test_session, test_user, tmp_path, monkeypatch):
    import asyncio
    import threading

    await test_session.commit()
    factory = async_sessionmaker(test_session.bind, expire_on_commit=False)
    store = ModelStore(tmp_path)
    writer = OwnedModelWriter(store, factory, test_user.id)
    entered, release = threading.Event(), threading.Event()
    original = store.save_new

    def held(*args):
        entered.set()
        assert release.wait(5)
        return original(*args)

    monkeypatch.setattr(store, "save_new", held)
    uid = str(uuid4())

    async def trial():
        try:
            await writer.save(uid, {}, {"scores": np.eye(2)})
        finally:
            await writer.discard_trial()

    task = asyncio.create_task(trial())
    try:
        assert await asyncio.to_thread(entered.wait, 5)
        task.cancel()
        await asyncio.sleep(0.05)
        assert not task.done()
    finally:
        release.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    claim = await test_session.get(ModelPublication, uid)
    assert claim.cleanup_requested and claim.reclaimed_at is not None
    assert not (store.models_dir / uid).exists()


def test_upgrade_existing_publication_defaults_to_protected(tmp_path):
    import sqlalchemy as sa

    from tests.test_init_db_bootstrap import _run_upgrade

    database = tmp_path / "upgrade.db"
    url = f"sqlite+aiosqlite:///{database}"
    _run_upgrade(url, "p5q7r9s1t883")
    engine = sa.create_engine(f"sqlite:///{database}")
    with engine.begin() as conn:
        conn.execute(sa.text("INSERT INTO user (id, username, is_active) VALUES (1, 'upgrade', 1)"))
        conn.execute(
            sa.text(
                "INSERT INTO model_publication (artifact_uid,user_id,artifact_dir) VALUES ('legacy',1,'models/legacy')"
            )
        )
    _run_upgrade(url, "head")
    with engine.connect() as conn:
        assert conn.execute(sa.text("SELECT cleanup_requested FROM model_publication")).scalar_one() == 0
        assert conn.execute(
            sa.text("SELECT attempt_id, lease_expires_at, reclaimed_at FROM model_publication")
        ).one() == (None, None, None)
    engine.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize("serialization_failure", [False, True])
async def test_real_pca_trial_releases_publication(
    test_session, test_user, tmp_path, monkeypatch, serialization_failure
):
    from unittest.mock import AsyncMock

    from spectra_sherpa.app.api.v1.routes.workflows import execute as route
    from spectra_sherpa.app.lib.sherpa_dataset import SherpaDataset
    from spectra_sherpa.app.schemas.workflows import TrialExecuteRequest
    from spectra_sherpa.app.services.dag.nodes.data.file_load_node import FileLoadNode

    await test_session.commit()
    store = ModelStore(tmp_path)
    monkeypatch.setattr("spectra_sherpa.app.services.execution_runtime.get_model_store", lambda: store)
    monkeypatch.setattr("spectra_sherpa.app.services.dag.executor.get_default_pool", lambda: None)
    monkeypatch.setattr(route, "validate_workflow_execution_access", AsyncMock(return_value={}))
    monkeypatch.setattr(route, "_enforce_demo_trial_execution_policy", lambda *args: None)

    async def fixture_source(*args, **kwargs):
        return {"default": SherpaDataset(np.random.default_rng(5).normal(size=(20, 4)))}

    monkeypatch.setattr(FileLoadNode, "execute", fixture_source)
    if serialization_failure:

        def refuse(*args, **kwargs):
            raise ValueError("synthetic post-publication serialization failure")

        monkeypatch.setattr(route, "serialize_result", refuse)
    request = TrialExecuteRequest(
        target_node_id="fit",
        trial_params={"n_components": "2"},
        nodes=[
            {"node_id": "input", "node_type": "data.file_load", "parameters": {"experiment_id": 1, "file_id": 1}},
            {"node_id": "fit", "node_type": "model.pca", "parameters": {"n_components": "2"}},
        ],
        edges=[{"from_node_id": "input", "to_node_id": "fit", "from_output": "default", "to_input": "default"}],
    )
    response = await route.execute_trial(request, session=test_session, current_user=test_user)
    assert response.status == ("error" if serialization_failure else "completed"), response.error
    if serialization_failure:
        assert "synthetic post-publication" in response.error
    claim = await test_session.scalar(select(ModelPublication))
    assert claim.cleanup_requested and claim.reclaimed_at is not None
    assert store.list_artifacts() == []


@pytest.mark.asyncio
async def test_terminal_cleanup_retries_after_file_failure_without_reaping_unknown_claims(
    test_session,
    test_user,
    tmp_path,
    monkeypatch,
):
    await test_session.commit()
    store = ModelStore(tmp_path)
    factory = async_sessionmaker(test_session.bind, expire_on_commit=False)
    terminal = OwnedModelWriter(store, factory, test_user.id)
    unknown = OwnedModelWriter(store, factory, test_user.id)
    a, b = str(uuid4()), str(uuid4())
    await terminal.save(a, {"model_type": "pca"}, {"scores": np.eye(2)})
    await unknown.save(b, {"model_type": "pca"}, {"scores": np.eye(2)})
    original = store.reclaim_publication

    def fail(*args):
        raise OSError("synthetic deletion interruption")

    monkeypatch.setattr(store, "reclaim_publication", fail)
    # The failure is logged per claim; the marked claim waits for the next pass.
    await terminal.discard_trial()
    async with factory() as session:
        assert (await session.get(ModelPublication, a)).cleanup_requested
        assert (await session.get(ModelPublication, a)).reclaimed_at is None
        assert (store.models_dir / a / "arrays.npz").exists()
        assert not (await session.get(ModelPublication, b)).cleanup_requested
    monkeypatch.setattr(store, "reclaim_publication", original)
    async with factory() as session:
        await reconcile_orphan_artifacts(session, store=store, grace_seconds=0)
    assert not (store.models_dir / a).exists()
    assert (store.models_dir / b / "arrays.npz").exists()
    async with factory() as session:
        assert (await session.get(ModelPublication, a)).reclaimed_at is not None
        assert await session.get(ModelPublication, b) is not None


@pytest.mark.asyncio
@pytest.mark.parametrize("damaged_first", [True, False])
async def test_one_damaged_terminal_claim_does_not_stall_the_batch_or_orphan_sweep(
    test_session, test_user, tmp_path, damaged_first
):
    from sqlalchemy import update

    await test_session.commit()
    store = ModelStore(tmp_path)
    factory = async_sessionmaker(test_session.bind, expire_on_commit=False)
    writer = OwnedModelWriter(store, factory, test_user.id)
    # Either claim may be processed first; both orders must reach the other.
    damaged, healthy = sorted(str(uuid4()) for _ in range(2))[:: 1 if damaged_first else -1]
    await writer.save(damaged, {"model_type": "pca"}, {"scores": np.eye(2)})
    await writer.save(healthy, {"model_type": "pca"}, {"scores": np.eye(2)})
    orphan = store.models_dir / str(uuid4())
    orphan.mkdir()
    async with factory() as session:
        await session.execute(
            update(ModelPublication)
            .where(ModelPublication.artifact_uid.in_([damaged, healthy]))
            .values(cleanup_requested=True)
        )
        await session.execute(
            update(ModelPublication)
            .where(ModelPublication.artifact_uid == damaged)
            .values(artifact_dir=str(tmp_path / "elsewhere"))
        )
        await session.commit()
    async with factory() as session:
        removed = await reconcile_orphan_artifacts(session, store=store, grace_seconds=0)
    assert (store.models_dir / damaged / "arrays.npz").exists()
    assert not (store.models_dir / healthy).exists()
    assert orphan.name in removed
    async with factory() as session:
        assert (await session.get(ModelPublication, damaged)).cleanup_requested
        assert (await session.get(ModelPublication, healthy)).reclaimed_at is not None
