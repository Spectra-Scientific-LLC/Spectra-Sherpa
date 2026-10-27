"""File ownership survives failed execution without claiming a usable model."""

from uuid import uuid4

import numpy as np
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from spectra_sherpa.app.models.model_artifact import ModelArtifact
from spectra_sherpa.app.models.model_publication import ModelPublication
from spectra_sherpa.app.services.model_store import ModelStore, persist_model_artifact_records
from spectra_sherpa.app.services.storage_custody import OwnedModelWriter


def model_workflow():
    from types import SimpleNamespace

    return SimpleNamespace(
        nodes=[
            SimpleNamespace(node_id=node_id, node_type=node_type, parameters=parameters, position_x=0, position_y=0)
            for node_id, node_type, parameters in (
                ("input", "deploy.input", {"stream_name": "sample"}),
                ("fit", "model.pca", {"n_components": "2"}),
                ("output", "deploy.output", {"output_format": "json"}),
            )
        ],
        edges=[
            SimpleNamespace(from_node_id=source, to_node_id=target, from_output="default", to_input="default")
            for source, target in (("input", "fit"), ("fit", "output"))
        ],
    )


@pytest.mark.asyncio
async def test_headless_model_graph_keeps_owned_publication(test_session, test_user, tmp_path, monkeypatch):
    from httpx import ASGITransport, AsyncClient

    from spectra_sherpa.app.api import headless_app
    from spectra_sherpa.app.services import model_store
    from spectra_sherpa.app.services.batch_predict import build_executor_from_workflow

    await test_session.commit()
    monkeypatch.setattr("spectra_sherpa.app.services.dag.executor.get_default_pool", lambda: None)
    monkeypatch.setattr(model_store, "get_model_store", lambda: ModelStore(tmp_path))
    monkeypatch.setattr(headless_app, "async_session", async_sessionmaker(test_session.bind, expire_on_commit=False))
    monkeypatch.setattr(headless_app, "_executor", build_executor_from_workflow(model_workflow()))
    monkeypatch.setattr(headless_app, "_executor_workflow_user_id", test_user.id)
    monkeypatch.setattr(headless_app, "_executor_workflow_id", None)
    monkeypatch.delenv("HEADLESS_API_KEY", raising=False)
    values = np.random.default_rng(14).normal(size=(20, 4))
    async with AsyncClient(transport=ASGITransport(app=headless_app.app), base_url="http://local") as client:
        response = await client.post("/predict", json={"sample": values.tolist()})
    assert response.status_code == 200, response.text
    rows = list(await test_session.scalars(select(ModelArtifact)))
    assert len(rows) == 1
    assert rows[0].user_id == test_user.id
    assert await test_session.scalar(select(ModelPublication)) is None
    assert (tmp_path / "models" / rows[0].artifact_uid / "arrays.npz").exists()


@pytest.mark.asyncio
async def test_private_compute_loop_publishes_using_owner_database_loop(test_session, test_user, tmp_path, monkeypatch):
    from spectra_sherpa.app.db import session as database
    from spectra_sherpa.app.lib.sherpa_dataset import SherpaDataset
    from spectra_sherpa.app.services import model_store
    from spectra_sherpa.app.services.batch_predict import execute_workflow_dataset

    await test_session.commit()
    monkeypatch.setattr("spectra_sherpa.app.services.dag.executor.get_default_pool", lambda: None)
    monkeypatch.setattr(model_store, "get_model_store", lambda: ModelStore(tmp_path))
    monkeypatch.setattr(database, "async_session", async_sessionmaker(test_session.bind, expire_on_commit=False))
    execution = await execute_workflow_dataset(
        model_workflow(), SherpaDataset(np.random.default_rng(14).normal(size=(20, 4))), owner_user_id=test_user.id
    )
    assert len(execution.executor.saved_artifacts) == 1
    uid = execution.executor.saved_artifacts[0]["artifact_uid"]
    claim = await test_session.get(ModelPublication, uid)
    assert claim is not None and claim.user_id == test_user.id
    assert (tmp_path / "models" / uid / "arrays.npz").exists()


@pytest.mark.asyncio
async def test_model_claim_transfers_only_with_committed_registration(test_session, test_user, tmp_path):
    await test_session.commit()
    user_id = test_user.id
    uid = str(uuid4())
    store = ModelStore(tmp_path)
    writer = OwnedModelWriter(store, async_sessionmaker(test_session.bind, expire_on_commit=False), user_id)
    digest = await writer.save(uid, {"model_type": "pca"}, {"scores": np.eye(2)})
    claim = await test_session.get(ModelPublication, uid)
    assert claim is not None
    assert claim.user_id == user_id
    from spectra_sherpa.app.services.model_store import reconcile_orphan_artifacts

    staging = tmp_path / "models" / f".staging-{uid}-interrupted"
    staging.mkdir()
    assert await reconcile_orphan_artifacts(test_session, store=store, grace_seconds=0) == []
    assert staging.exists()
    assert await test_session.scalar(select(ModelArtifact).where(ModelArtifact.artifact_uid == uid)) is None
    artifact = {"artifact_uid": uid, "artifact_dir": writer.artifact_directory(uid), "integrity_hash": digest}
    await persist_model_artifact_records(test_session, [artifact], user_id)
    await test_session.rollback()
    assert await test_session.get(ModelPublication, uid) is not None
    assert store.load(uid)[1]["scores"].shape == (2, 2)
    await persist_model_artifact_records(test_session, [artifact], user_id)
    await test_session.commit()
    assert await test_session.get(ModelPublication, uid) is None
    assert await test_session.scalar(select(ModelArtifact).where(ModelArtifact.artifact_uid == uid)) is not None


@pytest.mark.asyncio
@pytest.mark.parametrize("landed", [False, True])
async def test_unknown_claim_commit_never_writes_files(test_session, test_user, tmp_path, landed):
    await test_session.commit()
    user_id = test_user.id

    class LostAcknowledgement(AsyncSession):
        async def commit(self):
            if landed:
                await super().commit()
            raise RuntimeError("synthetic lost acknowledgement")

    uid = str(uuid4())
    store = ModelStore(tmp_path)
    writer = OwnedModelWriter(store, async_sessionmaker(test_session.bind, class_=LostAcknowledgement), user_id)
    with pytest.raises(RuntimeError, match="lost acknowledgement"):
        await writer.save(uid, {"model_type": "pca"}, {"scores": np.eye(2)})
    assert not (tmp_path / "models" / uid).exists()
    assert (await test_session.get(ModelPublication, uid) is not None) == landed


def test_application_runtime_does_not_grant_anonymous_writes():
    from spectra_sherpa.app.services.execution_runtime import build_application_execution_runtime
    from spectra_sherpa.core.execution_runtime import ExecutionCapabilityError

    with pytest.raises(ExecutionCapabilityError, match="write capability"):
        build_application_execution_runtime().require_model_artifact_writer()


@pytest.mark.parametrize("shared_pool", [False, True])
def test_publication_capacity_is_independent_of_saturated_compute_pool(shared_pool):
    import subprocess
    import sys

    # Bound a genuine negative control in a separate process: the broken
    # shared-pool variant cannot be safely drained/cancelled in this test loop.
    program = """
import asyncio
from concurrent.futures import ThreadPoolExecutor
from spectra_sherpa.app.services import storage_custody as custody

async def main():
    loop = asyncio.get_running_loop()
    loop.set_default_executor(ThreadPoolExecutor(max_workers=1))
    async def publication():
        print("publication-started-with-compute-occupied", flush=True)
        return await custody.await_file_writer(lambda: "published")
    def computation():
        return asyncio.run_coroutine_threadsafe(publication(), loop).result()
    assert await custody.await_thread_completion(computation) == "published"

if SHARED:
    custody._FILE_PUBLICATION_POOL = None
asyncio.run(main())
print("completed", flush=True)
""".replace("SHARED", repr(shared_pool))
    if shared_pool:
        with pytest.raises(subprocess.TimeoutExpired) as failure:
            subprocess.run([sys.executable, "-c", program], check=True, capture_output=True, timeout=5)
        assert b"publication-started-with-compute-occupied" in (failure.value.stdout or b"")
    else:
        result = subprocess.run([sys.executable, "-c", program], check=True, capture_output=True, timeout=10)
        assert result.stdout.strip().endswith(b"completed")


@pytest.mark.asyncio
async def test_publication_does_not_claim_preexisting_files(test_session, test_user, tmp_path):
    await test_session.commit()
    uid = str(uuid4())
    store = ModelStore(tmp_path)
    store.save(uid, {"model_type": "pca"}, {"scores": np.eye(2)})
    writer = OwnedModelWriter(store, async_sessionmaker(test_session.bind), test_user.id)
    with pytest.raises(FileExistsError, match="existing model"):
        await writer.save(uid, {"model_type": "pca"}, {"scores": np.zeros((2, 2))})
    assert await test_session.get(ModelPublication, uid) is None
    np.testing.assert_array_equal(store.load(uid)[1]["scores"], np.eye(2))
