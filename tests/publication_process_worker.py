"""Controlled separate-process publisher/reaper for real PostgreSQL proofs."""

import asyncio
import json
import sys

import numpy as np
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from spectra_sherpa.app.services import storage_custody as custody
from spectra_sherpa.app.services.model_store import ModelStore, persist_model_artifact_records


async def main():
    args = json.loads(sys.argv[1])
    engine = create_async_engine(args["url"], connect_args={"server_settings": {"application_name": args["name"]}})
    factory = async_sessionmaker(engine, expire_on_commit=False)
    store = ModelStore(args["root"])
    try:
        if args["mode"] == "reap":
            async with factory() as session:
                await custody.reconcile_terminal_publications(session, store=store)
        elif args["mode"] == "register":
            async with factory() as session:
                await persist_model_artifact_records(session, [args["artifact"]], args["user_id"])
                print("REGISTERED", flush=True)
                await session.commit()  # A deferred constraint trigger can hold actual COMMIT.
        else:
            original_lock = custody.lock_storage_owner
            pid = None

            async def locked(session, user_id):
                nonlocal pid
                await original_lock(session, user_id)
                pid = await session.scalar(text("select pg_backend_pid()"))

            custody.lock_storage_owner = locked
            original_promote = store._promote_new

            def held(staging, target):
                print(f"WRITER_HELD {pid}", flush=True)
                if sys.stdin.readline().strip() != "release":
                    raise RuntimeError("test controller disappeared")
                original_promote(staging, target)

            store._promote_new = held
            writer = custody.OwnedModelWriter(store, factory, args["user_id"])
            try:
                await writer.save(args["uid"], {}, {"scores": np.eye(2)})
            except Exception as exc:
                print(f"WRITER_CONNECTION_ENDED {type(exc).__name__}", flush=True)
        print("DONE", flush=True)
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
