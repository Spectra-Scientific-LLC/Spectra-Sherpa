"""Explicit, app-scoped lifecycle composition for separately installed products.

The host never discovers or imports implementations. A product's application
factory supplies context managers; each receives the concrete application after
core startup and owns cleanup of its resources. This does not grant any HTTP,
WebSocket, scientific-access or egress authority.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable, Sequence
from contextlib import AbstractAsyncContextManager, AsyncExitStack, asynccontextmanager
from typing import TypeAlias

from fastapi import FastAPI

ApplicationLifespan: TypeAlias = Callable[[FastAPI], AbstractAsyncContextManager[None]]


def compose_lifespan(core: ApplicationLifespan, extensions: Sequence[ApplicationLifespan] = ()) -> ApplicationLifespan:
    """Enter core, then extensions; unwind in reverse order, including failures.

    Freeze the supplied sequence so callers cannot change a running app's
    composition by mutating the list used to construct it. Extension exceptions
    propagate: a product whose required extension fails never becomes ready.
    """
    declared = tuple(extensions)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        async with AsyncExitStack() as stack:
            await stack.enter_async_context(core(app))
            for extension in declared:
                await stack.enter_async_context(extension(app))
            yield

    return lifespan
