"""Short database custody locks around filesystem publication, not computation."""

import asyncio
import contextvars
import logging
import weakref
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager, suppress
from datetime import timedelta
from functools import partial
from pathlib import Path
from uuid import UUID, uuid4

from sqlalchemy import func, select, update

from spectra_sherpa.app.models.user import User

logger = logging.getLogger(__name__)
PUBLICATION_LEASE_SECONDS = 300
PUBLICATION_RENEWAL_SECONDS = 30
# File writers never wait on the compute executor or perform async database
# work. Separate bounded capacity avoids compute -> publication -> compute
# starvation when private execution loops occupy every default-pool worker.
# Threads are created lazily; Python joins this executor at process shutdown.
_FILE_PUBLICATION_POOL = ThreadPoolExecutor(max_workers=2, thread_name_prefix="scientific-publication")


async def lock_storage_owner(session, user_id: int) -> None:
    if session.get_bind().dialect.name == "sqlite":
        await session.execute(update(User).where(User.id == user_id).values(id=User.id, updated_at=User.updated_at))
    if await session.scalar(select(User.id).where(User.id == user_id).with_for_update()) is None:
        raise ValueError("Scientific storage account no longer exists")


async def await_thread_completion(function, *args, executor=None):
    """Cancellation must not release custody while a writing thread survives."""
    # A bare executor Future is not an asyncio Task. asyncio.run shutdown
    # cancels all Tasks directly, including a task wrapping to_thread, which
    # otherwise looks done even though its thread still writes. This Future
    # resolves only when the actual function exits; shield protects it from
    # cancellation of the caller while the database lock remains held.
    worker = asyncio.get_running_loop().run_in_executor(
        executor, partial(contextvars.copy_context().run, function, *args)
    )
    try:
        return await asyncio.shield(worker)
    except asyncio.CancelledError:
        while not worker.done():
            try:
                await asyncio.shield(worker)
            except asyncio.CancelledError:
                continue
            except Exception:
                break
        try:
            worker.result()
        except Exception:
            logger.exception("File writer failed while cancellation was pending")
        raise


async def await_file_writer(function, *args):
    return await await_thread_completion(function, *args, executor=_FILE_PUBLICATION_POOL)


async def _database_now(session):
    clock = func.clock_timestamp() if session.get_bind().dialect.name == "postgresql" else func.current_timestamp()
    return await session.scalar(select(clock))


async def _lease_deadline(session):
    return await _database_now(session) + timedelta(seconds=PUBLICATION_LEASE_SECONDS)


async def _renew_while_executing(factory, user_id, attempt_id, execution_task):
    """Renew only while the owning execution task lives, never while merely cached."""
    from spectra_sherpa.app.models.model_publication import ModelPublication

    while True:
        await asyncio.sleep(PUBLICATION_RENEWAL_SECONDS)
        owner = execution_task() if execution_task else None
        if owner is None or owner.done():
            return
        del owner  # Do not keep a completed execution alive through the renewal loop.
        try:
            async with factory() as session:
                await lock_storage_owner(session, user_id)
                owner = execution_task() if execution_task else None
                if owner is None or owner.done():
                    return
                del owner
                result = await session.execute(
                    update(ModelPublication)
                    .where(
                        ModelPublication.user_id == user_id,
                        ModelPublication.attempt_id == attempt_id,
                        ModelPublication.cleanup_requested.is_(False),
                    )
                    .values(lease_expires_at=await _lease_deadline(session))
                )
                await session.commit()
                if not result.rowcount:
                    return
        except Exception:
            # A failed renewal grants no authority. Fencing/registration still
            # serialize on the owner row even if the database stays unavailable.
            logger.exception("Model publication lease renewal failed")


async def _fence_expired_publications(session, *, uids=None):
    """Expiry permits revocation, not deletion or a claim that execution failed."""
    from spectra_sherpa.app.models.model_artifact import ModelArtifact
    from spectra_sherpa.app.models.model_publication import ModelPublication

    query = select(ModelPublication.artifact_uid, ModelPublication.user_id).where(
        ModelPublication.attempt_id.is_not(None),
        ModelPublication.cleanup_requested.is_(False),
        ModelPublication.lease_expires_at <= await _database_now(session),
    )
    if uids is not None:
        query = query.where(ModelPublication.artifact_uid.in_(uids))
    candidates = list((await session.execute(query)).all())
    for uid, user_id in candidates:
        await session.rollback()
        try:
            await lock_storage_owner(session, user_id)
            claim = await session.scalar(
                select(ModelPublication)
                .where(
                    ModelPublication.artifact_uid == uid,
                    ModelPublication.user_id == user_id,
                    ModelPublication.attempt_id.is_not(None),
                    ModelPublication.cleanup_requested.is_(False),
                    ModelPublication.lease_expires_at <= await _database_now(session),
                )
                .with_for_update()
                .execution_options(populate_existing=True)
            )
            if claim is None or await session.scalar(select(ModelArtifact.id).where(ModelArtifact.artifact_uid == uid)):
                await session.rollback()
                continue
            claim.cleanup_requested = True
            # A separate committed fence must exist before any bytes are removed.
            # Lost acknowledgement leaves the original writer unable to proceed
            # if it landed, and leaves files intact if it did not.
            await session.commit()
        except Exception:
            logger.exception("Model publication fencing failed; retaining custody")
            await session.rollback()


async def publication_recovery_loop(factory, store, *, interval=60):
    """Retry fenced publications and recover crash-left leases without restarting."""
    while True:
        await asyncio.sleep(interval)
        try:
            async with factory() as session:
                await reconcile_terminal_publications(session, store=store)
        except Exception:
            logger.exception("Model publication recovery pass failed")


@asynccontextmanager
async def publication_recovery_service(factory, store, *, interval=60):
    """One recovery lifecycle for workbench and standalone headless servers."""
    try:
        async with factory() as session:
            await reconcile_terminal_publications(session, store=store)
    except Exception:
        logger.exception("Initial model publication recovery pass failed")
    task = asyncio.create_task(
        publication_recovery_loop(factory, store, interval=interval), name="model-publication-recovery"
    )
    try:
        yield
    finally:
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task


class OwnedModelWriter:
    """Claim custody durably before writing, then serialize with account erasure.

    A claim is not a usable model or a success receipt. Failed/timed-out runs
    retain it until registration or durable revocation transfers custody.
    No lock is held while fitting. SDK writers remain caller-owned capabilities.
    """

    def __init__(self, store, factory, user_id: int):
        self.store = store
        self.factory = factory
        self.user_id = user_id
        self.claimed_uids: set[str] = set()
        self.attempt_id = str(uuid4())
        self._execution_task = None
        self._renewal_task = None
        self._trial_stopped = False
        self._active_saves = 0
        self._writers_idle = asyncio.Event()
        self._writers_idle.set()

    def bind_execution_task(self, task):
        """A cross-loop adapter binds the task that owns the complete execution."""
        if task is not None:
            self._execution_task = weakref.ref(task)

    def _start_renewal(self):
        if self._execution_task is None:
            self.bind_execution_task(asyncio.current_task())
        if self._renewal_task is None or self._renewal_task.done():
            self._renewal_task = asyncio.create_task(
                _renew_while_executing(self.factory, self.user_id, self.attempt_id, self._execution_task),
                name="model-publication-lease",
            )

    def artifact_directory(self, artifact_uid: str) -> str:
        return self.store.artifact_directory(artifact_uid)

    async def save(self, artifact_uid, manifest, arrays):
        if self._trial_stopped:
            raise ValueError("Trial execution has stopped; create a new execution to publish models")
        self._active_saves += 1
        self._writers_idle.clear()
        try:
            return await self._save_owned(artifact_uid, manifest, arrays)
        finally:
            self._active_saves -= 1
            if not self._active_saves:
                self._writers_idle.set()

    async def _save_owned(self, artifact_uid, manifest, arrays):
        from spectra_sherpa.app.models.model_artifact import ModelArtifact
        from spectra_sherpa.app.models.model_publication import ModelPublication

        if str(UUID(artifact_uid)) != artifact_uid:
            raise ValueError("Model publication requires its allocated UUID")
        async with self.factory() as session:
            await lock_storage_owner(session, self.user_id)
            directory = self.artifact_directory(artifact_uid)
            existing = await session.scalar(
                select(ModelArtifact.artifact_uid).where(ModelArtifact.artifact_uid == artifact_uid)
            )
            if existing is not None or Path(directory).exists() or Path(directory).is_symlink():
                raise FileExistsError("Cannot claim an existing model artifact")
            session.add(
                ModelPublication(
                    artifact_uid=artifact_uid,
                    user_id=self.user_id,
                    artifact_dir=directory,
                    attempt_id=self.attempt_id,
                    lease_expires_at=await _lease_deadline(session),
                )
            )
            # A failed INSERT must not grant custody over an existing claim.
            # After a successful flush, remember ownership before COMMIT so a
            # lost acknowledgement remains conservatively recoverable.
            await session.flush()
            self.claimed_uids.add(artifact_uid)
            await session.commit()
            self._start_renewal()
            # Deletion can win between these transactions. Re-admit before any
            # byte is written. A lost claim-commit acknowledgement writes none.
            await lock_storage_owner(session, self.user_id)
            claim = await session.get(ModelPublication, artifact_uid, populate_existing=True)
            if claim is None or claim.attempt_id != self.attempt_id or claim.cleanup_requested:
                raise ValueError("Model publication ownership expired; run the workflow again")
            return await await_file_writer(self.store.save_new, artifact_uid, manifest, arrays)

    async def discard_trial(self):
        """Called only after execution/writers stop, never for uncertain durable runs.

        Mark intent before deleting bytes. A crash during cleanup is recoverable;
        legacy unowned claims remain protected, regardless of their age.
        """
        from spectra_sherpa.app.models.model_artifact import ModelArtifact
        from spectra_sherpa.app.models.model_publication import ModelPublication

        self._trial_stopped = True
        await self._writers_idle.wait()
        async with self.factory() as session:
            await lock_storage_owner(session, self.user_id)
            for uid in self.claimed_uids:
                if await session.scalar(select(ModelArtifact.artifact_uid).where(ModelArtifact.artifact_uid == uid)):
                    continue
                await session.execute(
                    update(ModelPublication)
                    .where(
                        ModelPublication.artifact_uid == uid,
                        ModelPublication.user_id == self.user_id,
                        ModelPublication.attempt_id == self.attempt_id,
                    )
                    .values(cleanup_requested=True)
                )
            await session.commit()
            from spectra_sherpa.app.services.model_store import durable_publication_recovery_supported

            if durable_publication_recovery_supported():
                await reconcile_terminal_publications(session, store=self.store, uids=self.claimed_uids)
            else:
                for uid in self.claimed_uids:
                    await session.rollback()
                    try:
                        await _reclaim_terminal_publication(
                            session, self.store, uid, self.user_id, stopped_attempt=self.attempt_id
                        )
                    except Exception:
                        logger.exception("Stopped trial cleanup failed; retained custody: %s", uid)
                        await session.rollback()


async def reconcile_terminal_publications(session, *, store, uids=None):
    """Reclaim only explicit terminal claims, serializing with account erasure."""
    from spectra_sherpa.app.models.model_publication import ModelPublication

    await _fence_expired_publications(session, uids=uids)
    query = select(ModelPublication.artifact_uid, ModelPublication.user_id).where(
        ModelPublication.cleanup_requested.is_(True), ModelPublication.reclaimed_at.is_(None)
    )
    if uids is not None:
        query = query.where(ModelPublication.artifact_uid.in_(uids))
    candidates = list((await session.execute(query)).all())
    for uid, user_id in candidates:
        await session.rollback()
        try:
            await _reclaim_terminal_publication(session, store, uid, user_id)
        except Exception:
            # One damaged claim must not stall the batch or the orphan sweep
            # behind it. The claim stays marked and is retried next pass.
            logger.exception("Terminal publication cleanup failed: %s", uid)
            await session.rollback()


async def _reclaim_terminal_publication(session, store, uid, user_id, *, stopped_attempt=None):
    from spectra_sherpa.app.models.model_artifact import ModelArtifact
    from spectra_sherpa.app.models.model_publication import ModelPublication
    from spectra_sherpa.app.services.model_store import durable_publication_recovery_supported

    try:
        await lock_storage_owner(session, user_id)
    except ValueError:
        await session.rollback()
        return  # Committed erasure owns its persisted plan.
    claim = await session.scalar(
        select(ModelPublication)
        .where(
            ModelPublication.artifact_uid == uid,
            ModelPublication.cleanup_requested.is_(True),
            ModelPublication.reclaimed_at.is_(None),
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if claim is None:
        return
    if stopped_attempt is not None and claim.attempt_id != stopped_attempt:
        raise ValueError("Stopped trial does not own this publication")
    durable = durable_publication_recovery_supported()
    if claim.attempt_id is not None and not durable and stopped_attempt is None:
        logger.warning(
            "Automatic publication recovery is unavailable on this platform; "
            "custody retained for offline reconciliation: %s",
            uid,
        )
        return
    if await session.scalar(select(ModelArtifact.artifact_uid).where(ModelArtifact.artifact_uid == uid)):
        return  # Never delete a retained model, even after inconsistent recovery.
    if claim.artifact_dir != store.artifact_directory(uid):
        raise ValueError("Publication cleanup path disagrees with its owned artifact")
    owned_path = Path(claim.artifact_dir).resolve()
    live_paths = list(await session.scalars(select(ModelArtifact.artifact_dir)))
    live_paths.extend(
        await session.scalars(select(ModelPublication.artifact_dir).where(ModelPublication.artifact_uid != uid))
    )
    if any(
        path == owned_path or path in owned_path.parents or owned_path in path.parents
        for path in (
            (Path(raw) if Path(raw).is_absolute() else store.models_dir.parent / raw).resolve() for raw in live_paths
        )
    ):
        logger.warning("Terminal publication cleanup blocked by overlapping retained custody: %s", uid)
        return
    protected_paths = [
        (Path(raw) if Path(raw).is_absolute() else store.models_dir.parent / raw).resolve() for raw in live_paths
    ]
    if claim.attempt_id is None:
        await await_file_writer(store.delete, uid)
    elif durable:
        await await_file_writer(store.reclaim_publication, uid, protected_paths)
    else:
        await await_file_writer(store.discard_stopped_trial, uid, protected_paths)
    if claim.attempt_id is None:
        await session.delete(claim)
    elif durable:
        claim.reclaimed_at = await session.scalar(select(func.current_timestamp()))
    await session.commit()


class LoopBoundModelWriter:
    """Route a private compute-loop publication back to its DB-owning loop."""

    def __init__(self, writer, loop):
        self.writer = writer
        self.loop = loop
        writer.bind_execution_task(asyncio.current_task())

    @property
    def attempt_id(self):
        return self.writer.attempt_id

    def artifact_directory(self, artifact_uid):
        return self.writer.artifact_directory(artifact_uid)

    async def save(self, artifact_uid, manifest, arrays):
        future = asyncio.run_coroutine_threadsafe(self.writer.save(artifact_uid, manifest, arrays), self.loop)
        return await asyncio.wrap_future(future)
