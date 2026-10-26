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
            await session.commit()
            # Deletion can win between these transactions. Re-admit before any
            # byte is written. A lost claim-commit acknowledgement writes none.
            await lock_storage_owner(session, self.user_id)
            return await await_file_writer(self.store.save_new, artifact_uid, manifest, arrays)


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
