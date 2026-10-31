"""Opt-in real PostgreSQL processes; every test owns a disposable database.

PUBLICATION_TEST_POSTGRES_URL must name an administrative disposable cluster.
No existing database/schema is changed. Lock waits are checked in pg_stat_activity.
"""

import asyncio
import json
import os
import sys
from contextlib import asynccontextmanager
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
pytestmark = pytest.mark.asyncio
requires_postgres = pytest.mark.skipif(not URL, reason="Disposable PostgreSQL not configured")


async def bounded(awaitable, label, timeout=20, settle_timeout=5):
    """Observe a test-owned operation without unbounded cancellation waiting."""
    task = asyncio.ensure_future(awaitable)
    try:
        done, _ = await asyncio.wait({task}, timeout=timeout)
        if not done:
            raise TimeoutError(f"{label} exceeded {timeout}s")
        return task.result()
    except BaseException as primary:
        if not task.done():
            task.cancel()
            done, pending = await asyncio.wait({task}, timeout=settle_timeout)
            if pending:
                task.add_done_callback(lambda t: report_late_failure(t, label))
                raise TimeoutError(f"{label} did not settle after cancellation") from primary
            if not task.cancelled():
                cleanup_error = task.exception()
                if cleanup_error is not None:
                    raise BaseExceptionGroup(f"{label}: observation and cleanup failed", [primary, cleanup_error])
        raise


def report_late_failure(task, label):
    if not task.cancelled():
        error = task.exception()
        if error is not None:
            task.get_loop().call_exception_handler(
                {"message": f"Late failure after {label} cleanup deadline", "exception": error, "task": task}
            )


@asynccontextmanager
async def controller_scope(manager, label):
    """Keep the real transaction/context semantics, including exceptional exit."""
    resource = await bounded(manager.__aenter__(), f"{label} enter")
    try:
        yield resource
    except BaseException:
        if not await bounded(manager.__aexit__(*sys.exc_info()), f"{label} exit"):
            raise
    else:
        await bounded(manager.__aexit__(None, None, None), f"{label} exit")


async def cleanup_steps(steps, timeout=20):
    """Attempt every independent cleanup even if an earlier stage fails."""
    errors = []
    for label, operation in steps:
        try:
            await bounded(operation(), label, timeout=timeout)
        except BaseException as exc:
            exc.add_note(label)
            errors.append(exc)
    if errors:
        raise BaseExceptionGroup("Publication proof cleanup failed", errors)


async def stop_workers(processes, timeout=20):
    errors = []
    # Signal every owned child before draining any one child's pipes.
    for process in processes:
        try:
            if process.returncode is None:
                process.kill()
        except ProcessLookupError:
            pass
        except Exception as exc:
            errors.append(exc)
    try:
        await cleanup_steps(
            [(f"worker {index} drain/reap", process.communicate) for index, process in enumerate(processes)],
            timeout=timeout,
        )
    except BaseException as exc:
        errors.append(exc)
    if errors:
        raise BaseExceptionGroup("Publication worker cleanup failed", errors)


@pytest_asyncio.fixture
async def pg(tmp_path):
    if not URL:
        pytest.skip("Disposable PostgreSQL not configured")
    name = "publication_proof_" + uuid4().hex
    url = make_url(URL).set(database=name).render_as_string(hide_password=False)
    # Controller-only deadlines: worker COMMIT/advisory/storage waits remain real.
    controller_args = {"timeout": 20, "command_timeout": 20}
    admin = create_async_engine(URL, isolation_level="AUTOCOMMIT", connect_args=controller_args, pool_timeout=20)
    engine = create_async_engine(url, connect_args=controller_args, pool_timeout=20)
    processes = []
    session = None

    async def setup():
        nonlocal session
        async with controller_scope(admin.connect(), "admin connection") as conn:
            await conn.execute(text(f'CREATE DATABASE "{name}"'))
        async with controller_scope(engine.begin(), "controller transaction") as conn:
            await conn.run_sync(Base.metadata.create_all)
        factory = async_sessionmaker(engine, expire_on_commit=False)
        session = factory()
        user = User(username="publication-proof", is_active=True)
        session.add(user)
        await session.commit()
        return factory, user

    async def drop_database():
        async with controller_scope(admin.connect(), "admin connection") as conn:
            await conn.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))

    try:
        factory, user = await bounded(setup(), "database setup", timeout=60)
        yield url, engine, factory, session, user, tmp_path, processes
    finally:
        steps = []
        if session is not None:
            steps.append(("controller session close", session.close))
        steps.extend(
            [
                ("test engine dispose", engine.dispose),
                ("disposable database drop", drop_database),
                ("admin engine dispose", admin.dispose),
            ]
        )
        # stop_workers has a per-child allowance; do not truncate it with a
        # shorter aggregate deadline before all children have been attempted.
        errors = []
        try:
            await stop_workers(processes)
        except BaseException as exc:
            errors.append(exc)
        try:
            await cleanup_steps(steps)
        except BaseException as exc:
            errors.append(exc)
        if errors:
            raise BaseExceptionGroup("Publication fixture cleanup failed", errors)


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


async def line(process, prefix, timeout=20):
    async def read_until_prefix():
        while True:
            raw = await process.stdout.readline()
            if not raw:
                # This read shares the SAME absolute readiness deadline; a
                # live child retaining stderr cannot defer the timeout.
                diagnostic = await process.stderr.read(65536)
                pytest.fail(f"Worker stdout closed before {prefix}: {diagnostic.decode(errors='replace')}")
            value = raw.decode().strip()
            if value.startswith(prefix):
                return value

    return await bounded(read_until_prefix(), f"worker readiness {prefix}", timeout=timeout)


async def complete(process):
    stdout, stderr = await bounded(process.communicate(), "worker completion")
    assert process.returncode == 0, stderr.decode()
    assert b"DONE" in stdout, stdout.decode()


async def wait_lock(engine, name, query=None):
    async def observe():
        for _ in range(200):
            async with controller_scope(engine.connect(), "controller connection") as conn:
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

    return await bounded(observe(), "PostgreSQL lock observation")


@pytest.mark.parametrize("commit_lands", [True, False])
@requires_postgres
async def test_held_registration_commit_serializes_with_reclamation(pg, commit_lands):
    _, engine, _, session, user, root, _ = pg
    store, writer, uid, artifact = await publication(session, user, root)
    await expired(session, uid)
    async with controller_scope(engine.begin(), "controller transaction") as conn:
        await conn.execute(text("""CREATE FUNCTION hold_publication_commit() RETURNS trigger LANGUAGE plpgsql AS $$
            BEGIN PERFORM pg_advisory_xact_lock(719351); RETURN NEW; END $$"""))
        await conn.execute(text("""CREATE CONSTRAINT TRIGGER hold_commit AFTER INSERT ON model_artifact
            DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION hold_publication_commit()"""))
    async with controller_scope(engine.connect(), "blocker connection") as blocker:
        await blocker.execute(text("select pg_advisory_lock(719351)"))
        registering = await worker(pg, "register", artifact=artifact)
        await line(registering, "REGISTERED")
        pid = await wait_lock(engine, "proof-register", "COMMIT")
        reaping = await worker(pg, "reap")
        await wait_lock(engine, "proof-reap")
        assert (store.models_dir / uid / "arrays.npz").exists()
        if not commit_lands:
            async with controller_scope(engine.connect(), "control connection") as control:
                await control.execute(text("select pg_terminate_backend(:pid)"), {"pid": pid})
        await blocker.execute(text("select pg_advisory_unlock(719351)"))
    if commit_lands:
        await complete(registering)
    else:
        await bounded(registering.communicate(), "terminated registration completion")
        assert registering.returncode != 0
    await complete(reaping)
    await session.rollback()
    assert bool(await session.scalar(select(ModelArtifact).where(ModelArtifact.artifact_uid == uid))) == commit_lands
    assert (store.models_dir / uid).exists() == commit_lands
    claim = await session.get(ModelPublication, uid, populate_existing=True)
    assert claim is None if commit_lands else claim.reclaimed_at is not None


@requires_postgres
async def test_terminated_database_connection_cannot_release_live_storage_writer(pg):
    _, engine, factory, session, _, root, _ = pg
    uid = str(uuid4())
    store = ModelStore(root)
    writing = await worker(pg, "write", uid=uid)
    held = await line(writing, "WRITER_HELD")
    pid = int(held.split()[1])
    await expired(session, uid)
    async with controller_scope(engine.connect(), "control connection") as control:
        assert await control.scalar(text("select pg_terminate_backend(:pid)"), {"pid": pid})
    reaping = await worker(pg, "reap")

    # The committed DB fence proves the reaper passed the lost DB lock, while
    # storage custody still prevents deleting the live writer's staged bytes.
    async def observe_fence():
        for _ in range(200):
            async with controller_scope(factory(), "observer session") as observer:
                claim = await observer.get(ModelPublication, uid)
                if claim.cleanup_requested:
                    assert claim.reclaimed_at is None
                    break
            await asyncio.sleep(0.025)
        else:
            pytest.fail("reaper never committed the revocation fence")

    await bounded(observe_fence(), "PostgreSQL revocation fence observation")
    assert reaping.returncode is None
    assert list(store.models_dir.glob(f".staging-{uid}-*"))
    writing.stdin.write(b"release\n")
    await bounded(writing.stdin.drain(), "writer release")
    await complete(writing)
    await complete(reaping)
    assert not (store.models_dir / uid).exists()
    assert not list(store.models_dir.glob(f".staging-{uid}-*"))
    with pytest.raises(ModelArtifactCollisionError):
        store.save_new(uid, {}, {})


@requires_postgres
async def test_killed_writer_staging_is_reclaimed_only_after_revocation(pg):
    _, _, _, session, _, root, _ = pg
    uid = str(uuid4())
    store = ModelStore(root)
    writing = await worker(pg, "write", uid=uid)
    await line(writing, "WRITER_HELD")
    writing.kill()
    await bounded(writing.communicate(), "killed writer completion")
    assert list(store.models_dir.glob(f".staging-{uid}-*"))
    reaping = await worker(pg, "reap")
    await complete(reaping)
    assert list(store.models_dir.glob(f".staging-{uid}-*"))  # Lease not expired.
    await expired(session, uid)
    reaping = await worker(pg, "reap")
    await complete(reaping)
    assert not list(store.models_dir.glob(f".staging-{uid}-*"))
    assert (await session.get(ModelPublication, uid, populate_existing=True)).reclaimed_at is not None


@pytest.mark.parametrize("mode", ["unrelated_lines", "stdout_eof"])
async def test_worker_readiness_has_one_deadline_even_with_noise_or_open_stderr(mode):
    # Both children have finite escape hatches, including if the observer regresses.
    scripts = {
        "unrelated_lines": (
            "import time; print('BOOT',flush=True); end=time.monotonic()+5\n"
            "while time.monotonic()<end:\n print('unrelated',flush=True); time.sleep(.01)\n"
        ),
        "stdout_eof": "import os,time; print('BOOT',flush=True); os.close(1); time.sleep(5)",
    }
    process = await asyncio.create_subprocess_exec(
        sys.executable, "-c", scripts[mode], stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    try:
        assert await bounded(process.stdout.readline(), "fixture boot", timeout=5) == b"BOOT" + os.linesep.encode()
        with pytest.raises(TimeoutError, match="worker readiness REGISTERED"):
            await line(process, "REGISTERED", timeout=0.1)
        assert process.returncode is None, "Observer must fail before the child's escape hatch"
    finally:
        await stop_workers([process])
    assert process.returncode is not None


async def test_worker_readiness_skips_blank_lines_without_treating_them_as_eof():
    process = await asyncio.create_subprocess_exec(
        sys.executable,
        "-c",
        "print('\\nnoise\\nREGISTERED exact',flush=True)",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        assert await line(process, "REGISTERED") == "REGISTERED exact"
    finally:
        await stop_workers([process])


async def test_worker_cleanup_signals_all_owned_children_and_continues_after_drain_failure(monkeypatch):
    processes = []
    original_drains = []
    kills = []
    try:
        for _ in range(3):
            process = await asyncio.create_subprocess_exec(
                sys.executable,
                "-c",
                "import time; print('BOOT',flush=True); time.sleep(5)",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            processes.append(process)
            original_drains.append(process.communicate)
            assert await bounded(process.stdout.readline(), "fixture boot", timeout=5) == b"BOOT" + os.linesep.encode()
        first, second, unrelated = processes
        for process in (first, second):
            original_kill = process.kill

            def record_kill(pid=process.pid, kill=original_kill):
                kills.append(pid)
                kill()  # Still kill the actual subprocess.

            monkeypatch.setattr(process, "kill", record_kill)

        async def failed_drain():
            assert kills == [first.pid, second.pid]
            raise RuntimeError("injected first drain failure")

        monkeypatch.setattr(first, "communicate", failed_drain)
        with pytest.raises(ExceptionGroup) as caught:
            await stop_workers([first, second])
        assert caught.value.subgroup(RuntimeError) is not None
        assert second.returncode is not None
        assert unrelated.returncode is None
    finally:
        # Restore only this test's injected boundary before the safety cleanup.
        for process, drain in zip(processes, original_drains):
            monkeypatch.setattr(process, "communicate", drain)
        await stop_workers(processes)
    assert all(process.returncode is not None for process in processes)


async def test_cleanup_attempts_later_stages_after_exception_and_timeout():
    attempted, settled = [], []

    async def fail():
        attempted.append("session close")
        raise RuntimeError("injected close failure")

    async def stall():
        attempted.append("engine dispose")
        try:
            await asyncio.sleep(1)  # Finite escape hatch if timeout handling regresses.
        finally:
            settled.append("engine dispose")

    async def drop():
        attempted.append("database drop")

    async def dispose():
        attempted.append("admin dispose")

    with pytest.raises(ExceptionGroup) as caught:
        await cleanup_steps([("close", fail), ("engine", stall), ("drop", drop), ("admin", dispose)], timeout=0.05)
    assert attempted == ["session close", "engine dispose", "database drop", "admin dispose"]
    assert settled == ["engine dispose"]
    assert caught.value.subgroup(RuntimeError) is not None
    assert caught.value.subgroup(TimeoutError) is not None


async def test_bounded_observer_reports_cancellation_resistance_without_waiting_for_it():
    release, started = asyncio.Event(), asyncio.Event()

    async def resistant():
        started.set()
        try:
            await release.wait()
        except asyncio.CancelledError:
            await release.wait()

    task = asyncio.create_task(resistant())
    escape = asyncio.get_running_loop().call_later(5, release.set)
    try:
        await bounded(started.wait(), "fixture start", timeout=1)
        with pytest.raises(TimeoutError, match="did not settle after cancellation"):
            await bounded(task, "resistant fixture", timeout=0.05, settle_timeout=0.05)
        assert not task.done(), "A resistant task must be reported, not silently awaited to completion"
    finally:
        release.set()
        done, pending = await asyncio.wait({task}, timeout=2)
        escape.cancel()
        assert not pending
        for finished in done:
            finished.result()


@pytest.mark.parametrize("fail_body", [False, True])
async def test_controller_scope_preserves_success_and_exception_exit(fail_body):
    events = []
    body_error = ValueError("body failure")

    @asynccontextmanager
    async def context():
        events.append("enter")
        try:
            yield "connection"
        except ValueError as exc:
            assert exc is body_error
            events.append("rollback path")
            raise
        else:
            events.append("commit path")
        finally:
            events.append("close")

    async def exercise():
        async with controller_scope(context(), "fixture context") as connection:
            assert connection == "connection"
            if fail_body:
                raise body_error

    if fail_body:
        with pytest.raises(ValueError) as caught:
            await exercise()
        assert caught.value is body_error
    else:
        await exercise()
    assert events == ["enter", "rollback path" if fail_body else "commit path", "close"]


async def test_observer_keeps_timeout_and_cancellation_cleanup_error():
    async def broken_cleanup():
        try:
            await asyncio.sleep(5)
        finally:
            raise ValueError("cancellation cleanup failed")

    with pytest.raises(ExceptionGroup) as caught:
        await bounded(broken_cleanup(), "failing cleanup", timeout=0.05)
    assert caught.value.subgroup(TimeoutError) is not None
    assert caught.value.subgroup(ValueError) is not None


async def test_late_cleanup_error_is_reported_after_settlement_deadline():
    loop = asyncio.get_running_loop()
    old_handler = loop.get_exception_handler()
    release, reported = asyncio.Event(), asyncio.Event()
    errors = []

    def record_error(_loop, context):
        errors.append(context)
        reported.set()

    async def delayed_failure():
        try:
            await release.wait()
        except asyncio.CancelledError:
            await release.wait()
            raise ValueError("late cleanup failure")

    task = asyncio.create_task(delayed_failure())
    escape = loop.call_later(5, release.set)
    loop.set_exception_handler(record_error)
    try:
        with pytest.raises(TimeoutError, match="did not settle"):
            await bounded(task, "late fixture", timeout=0.05, settle_timeout=0.05)
        release.set()
        await bounded(reported.wait(), "late error report", timeout=1)
        assert len(errors) == 1
        assert errors[0]["task"] is task
        assert isinstance(errors[0]["exception"], ValueError)
        assert "late fixture" in errors[0]["message"]
    finally:
        release.set()
        done, pending = await asyncio.wait({task}, timeout=2)
        escape.cancel()
        loop.set_exception_handler(old_handler)
        assert not pending
        for finished in done:
            if not finished.cancelled():
                finished.exception()
