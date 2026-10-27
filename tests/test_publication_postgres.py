"""Opt-in real PostgreSQL processes; every test owns a disposable database.

PUBLICATION_TEST_POSTGRES_URL must name an administrative disposable cluster.
No existing database/schema is changed. Lock waits are checked in pg_stat_activity.
"""

import asyncio
import json
import os
import sys
from pathlib import Path
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import select, text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import spectra_sherpa.app.models  # noqa: F401
from spectra_sherpa.app.db.base import Base
from spectra_sherpa.app.models.model_artifact import ModelArtifact
from spectra_sherpa.app.models.model_publication import ModelPublication
from spectra_sherpa.app.models.user import User
from spectra_sherpa.app.services.model_store import ModelArtifactCollisionError, ModelStore
from tests.test_publication_lease import expired, publication

URL = os.environ.get("PUBLICATION_TEST_POSTGRES_URL", "")
if os.environ.get("REQUIRE_PUBLICATION_POSTGRES") == "1" and not URL:
    raise RuntimeError("PUBLICATION_TEST_POSTGRES_URL required")
if URL and make_url(URL).get_backend_name() != "postgresql":
    raise RuntimeError("Publication proof requires PostgreSQL")
pytestmark = [pytest.mark.asyncio, pytest.mark.skipif(not URL, reason="Disposable PostgreSQL not configured")]


@pytest_asyncio.fixture
async def pg(tmp_path):
    name = "publication_proof_" + uuid4().hex
    url = make_url(URL).set(database=name).render_as_string(hide_password=False)
    admin = create_async_engine(URL, isolation_level="AUTOCOMMIT")
    engine = create_async_engine(url)
    processes = []
    try:
        async with admin.connect() as conn:
            await conn.execute(text(f'CREATE DATABASE "{name}"'))
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        factory = async_sessionmaker(engine, expire_on_commit=False)
        async with factory() as session:
            user = User(username="publication-proof", is_active=True)
            session.add(user)
            await session.commit()
            yield url, engine, factory, session, user, tmp_path, processes
    finally:
        for process in processes:
            if process.returncode is None:
                process.kill()
            await process.communicate()
        await engine.dispose()
        async with admin.connect() as conn:
            await conn.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
        await admin.dispose()


async def worker(pg, mode, **extra):
    url, _, _, _, user, root, processes = pg
    args = dict(url=url, mode=mode, user_id=user.id, root=str(root), name="proof-" + mode, **extra)
    process = await asyncio.create_subprocess_exec(
        sys.executable,
        str(Path(__file__).with_name("publication_process_worker.py")),
        json.dumps(args),
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    processes.append(process)
    return process


async def line(process, prefix):
    while True:
        value = (await asyncio.wait_for(process.stdout.readline(), 20)).decode().strip()
        if value.startswith(prefix):
            return value
        if not value:
            pytest.fail((await process.stderr.read()).decode())


async def complete(process):
    stdout, stderr = await asyncio.wait_for(process.communicate(), 20)
    assert process.returncode == 0, stderr.decode()
    assert b"DONE" in stdout, stdout.decode()


async def wait_lock(engine, name, query=None):
    for _ in range(200):
        async with engine.connect() as conn:
            rows = (
                await conn.execute(
                    text("select pid,query,wait_event_type from pg_stat_activity where application_name=:name"),
                    {"name": name},
                )
            ).all()
        for pid, sql, event in rows:
            if event == "Lock" and (query is None or sql.strip().rstrip(";").upper() == query):
                return pid
        await asyncio.sleep(0.025)
    pytest.fail(f"{name} did not enter observed PostgreSQL lock wait: {rows}")


@pytest.mark.parametrize("commit_lands", [True, False])
async def test_held_registration_commit_serializes_with_reclamation(pg, commit_lands):
    _, engine, _, session, user, root, _ = pg
    store, writer, uid, artifact = await publication(session, user, root)
    await expired(session, uid)
    async with engine.begin() as conn:
        await conn.execute(text("""CREATE FUNCTION hold_publication_commit() RETURNS trigger LANGUAGE plpgsql AS $$
            BEGIN PERFORM pg_advisory_xact_lock(719351); RETURN NEW; END $$"""))
        await conn.execute(text("""CREATE CONSTRAINT TRIGGER hold_commit AFTER INSERT ON model_artifact
            DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION hold_publication_commit()"""))
    async with engine.connect() as blocker:
        await blocker.execute(text("select pg_advisory_lock(719351)"))
        registering = await worker(pg, "register", artifact=artifact)
        await line(registering, "REGISTERED")
        pid = await wait_lock(engine, "proof-register", "COMMIT")
        reaping = await worker(pg, "reap")
        await wait_lock(engine, "proof-reap")
        assert (store.models_dir / uid / "arrays.npz").exists()
        if not commit_lands:
            async with engine.connect() as control:
                await control.execute(text("select pg_terminate_backend(:pid)"), {"pid": pid})
        await blocker.execute(text("select pg_advisory_unlock(719351)"))
    if commit_lands:
        await complete(registering)
    else:
        await asyncio.wait_for(registering.communicate(), 20)
        assert registering.returncode != 0
    await complete(reaping)
    await session.rollback()
    assert bool(await session.scalar(select(ModelArtifact).where(ModelArtifact.artifact_uid == uid))) == commit_lands
    assert (store.models_dir / uid).exists() == commit_lands
    claim = await session.get(ModelPublication, uid, populate_existing=True)
    assert claim is None if commit_lands else claim.reclaimed_at is not None


async def test_terminated_database_connection_cannot_release_live_storage_writer(pg):
    _, engine, factory, session, _, root, _ = pg
    uid = str(uuid4())
    store = ModelStore(root)
    writing = await worker(pg, "write", uid=uid)
    held = await line(writing, "WRITER_HELD")
    pid = int(held.split()[1])
    await expired(session, uid)
    async with engine.connect() as control:
        assert await control.scalar(text("select pg_terminate_backend(:pid)"), {"pid": pid})
    reaping = await worker(pg, "reap")
    # The committed DB fence proves the reaper passed the lost DB lock, while
    # storage custody still prevents deleting the live writer's staged bytes.
    for _ in range(200):
        async with factory() as observer:
            claim = await observer.get(ModelPublication, uid)
            if claim.cleanup_requested:
                assert claim.reclaimed_at is None
                break
        await asyncio.sleep(0.025)
    else:
        pytest.fail("reaper never committed the revocation fence")
    assert reaping.returncode is None
    assert list(store.models_dir.glob(f".staging-{uid}-*"))
    writing.stdin.write(b"release\n")
    await writing.stdin.drain()
    await complete(writing)
    await complete(reaping)
    assert not (store.models_dir / uid).exists()
    assert not list(store.models_dir.glob(f".staging-{uid}-*"))
    with pytest.raises(ModelArtifactCollisionError):
        store.save_new(uid, {}, {})


async def test_killed_writer_staging_is_reclaimed_only_after_revocation(pg):
    _, _, _, session, _, root, _ = pg
    uid = str(uuid4())
    store = ModelStore(root)
    writing = await worker(pg, "write", uid=uid)
    await line(writing, "WRITER_HELD")
    writing.kill()
    await writing.communicate()
    assert list(store.models_dir.glob(f".staging-{uid}-*"))
    reaping = await worker(pg, "reap")
    await complete(reaping)
    assert list(store.models_dir.glob(f".staging-{uid}-*"))  # Lease not expired.
    await expired(session, uid)
    reaping = await worker(pg, "reap")
    await complete(reaping)
    assert not list(store.models_dir.glob(f".staging-{uid}-*"))
    assert (await session.get(ModelPublication, uid, populate_existing=True)).reclaimed_at is not None
