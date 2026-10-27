"""Short database custody locks around filesystem publication, not computation."""

import asyncio
import contextvars
import logging
from concurrent.futures import ThreadPoolExecutor
from functools import partial
from pathlib import Path
from uuid import UUID

from sqlalchemy import select, update

from spectra_sherpa.app.models.user import User

logger = logging.getLogger(__name__)
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


class OwnedModelWriter:
    """Claim custody durably before writing, then serialize with account erasure.

    A claim is not a usable model or a success receipt. Failed/timed-out runs
    retain it until a completed artifact takes custody or the account is erased.
    No lock is held while fitting. SDK writers remain caller-owned capabilities.
    """

    def __init__(self, store, factory, user_id: int):
        self.store = store
        self.factory = factory
        self.user_id = user_id
        self.claimed_uids: set[str] = set()

    def artifact_directory(self, artifact_uid: str) -> str:
        return self.store.artifact_directory(artifact_uid)

    async def save(self, artifact_uid, manifest, arrays):
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
                )
            )
            # A failed INSERT must not grant custody over an existing claim.
            # After a successful flush, remember ownership before COMMIT so a
            # lost acknowledgement remains conservatively recoverable.
            await session.flush()
            self.claimed_uids.add(artifact_uid)
            await session.commit()
            # Deletion can win between these transactions. Re-admit before any
            # byte is written. A lost claim-commit acknowledgement writes none.
            await lock_storage_owner(session, self.user_id)
            return await await_file_writer(self.store.save_new, artifact_uid, manifest, arrays)

    async def discard_trial(self):
        """Called only after execution/writers stop, never for uncertain durable runs.

        Mark intent before deleting bytes. A crash during cleanup is recoverable;
        unmarked claims remain protected, regardless of their age.
        """
        from spectra_sherpa.app.models.model_artifact import ModelArtifact
        from spectra_sherpa.app.models.model_publication import ModelPublication

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
                    )
                    .values(cleanup_requested=True)
                )
            await session.commit()
            await reconcile_terminal_publications(session, store=self.store, uids=self.claimed_uids)


async def reconcile_terminal_publications(session, *, store, uids=None):
    """Reclaim only explicit terminal claims, serializing with account erasure."""
    from spectra_sherpa.app.models.model_publication import ModelPublication

    query = select(ModelPublication.artifact_uid, ModelPublication.user_id).where(
        ModelPublication.cleanup_requested.is_(True)
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


async def _reclaim_terminal_publication(session, store, uid, user_id):
    from spectra_sherpa.app.models.model_artifact import ModelArtifact
    from spectra_sherpa.app.models.model_publication import ModelPublication

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
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if claim is None:
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
    await await_file_writer(store.delete, uid)
    await session.delete(claim)
    await session.commit()


class LoopBoundModelWriter:
    """Route a private compute-loop publication back to its DB-owning loop."""

    def __init__(self, writer, loop):
        self.writer = writer
        self.loop = loop

    def artifact_directory(self, artifact_uid):
        return self.writer.artifact_directory(artifact_uid)

    async def save(self, artifact_uid, manifest, arrays):
        future = asyncio.run_coroutine_threadsafe(self.writer.save(artifact_uid, manifest, arrays), self.loop)
        return await asyncio.wrap_future(future)
