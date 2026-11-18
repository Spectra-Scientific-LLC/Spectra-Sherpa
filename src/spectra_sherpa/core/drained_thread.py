"""Retain operation ownership until a cancelled synchronous read has finished."""

import asyncio
from contextlib import nullcontext


async def drained_read(function, *args):
    task = asyncio.create_task(asyncio.to_thread(function, *args))
    try:
        return await asyncio.shield(task)
    except asyncio.CancelledError:
        try:
            from anyio import CancelScope
        except ModuleNotFoundError as exc:
            if exc.name != "anyio":
                raise
            shield = nullcontext()
        else:
            shield = CancelScope(shield=True)
        with shield:
            while not task.done():
                try:
                    await asyncio.shield(task)
                except asyncio.CancelledError:
                    continue
                except Exception:
                    break
        if not task.cancelled():
            task.exception()
        raise
