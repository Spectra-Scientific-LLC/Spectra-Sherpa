"""Product extensions cannot leak across apps or survive a failed startup."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager

import pytest
from fastapi import FastAPI

from spectra_sherpa.app.contracts.application_lifecycle import compose_lifespan


def resource(name, events, *, fail=False):
    @asynccontextmanager
    async def lifespan(app):
        events.append((name, "start", app))
        try:
            if fail:
                raise RuntimeError("extension refused startup")
            yield
        finally:
            events.append((name, "stop", app))

    return lifespan


@pytest.mark.asyncio
async def test_extensions_are_app_scoped_and_unwind_before_core():
    events = []
    first, second = FastAPI(), FastAPI()
    core = resource("core", events)
    enabled = compose_lifespan(core, [resource("extension", events)])
    plain = compose_lifespan(core)
    async with enabled(first), plain(second):
        assert events == [("core", "start", first), ("extension", "start", first), ("core", "start", second)]
    assert events[3:] == [("core", "stop", second), ("extension", "stop", first), ("core", "stop", first)]


@pytest.mark.asyncio
async def test_failed_extension_never_serves_and_unwinds_started_resources():
    events = []
    app = FastAPI()
    lifecycle = compose_lifespan(
        resource("core", events), [resource("first", events), resource("bad", events, fail=True)]
    )
    with pytest.raises(RuntimeError, match="refused startup"):
        async with lifecycle(app):
            pytest.fail("failed extension must not admit application startup")
    assert [(name, phase) for name, phase, _ in events] == [
        ("core", "start"),
        ("first", "start"),
        ("bad", "start"),
        ("bad", "stop"),
        ("first", "stop"),
        ("core", "stop"),
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize("error", [RuntimeError, asyncio.CancelledError])
async def test_serving_error_or_cancellation_releases_extensions_and_core(error):
    events = []
    app = FastAPI()
    with pytest.raises(error):
        async with compose_lifespan(resource("core", events), [resource("extension", events)])(app):
            raise error()
    assert [(name, phase) for name, phase, _ in events][-2:] == [("extension", "stop"), ("core", "stop")]


@pytest.mark.asyncio
async def test_constructor_freezes_extension_list():
    events = []
    extensions = [resource("first", events)]
    lifecycle = compose_lifespan(resource("core", events), extensions)
    extensions.append(resource("late", events))
    async with lifecycle(FastAPI()):
        pass
    assert all(name != "late" for name, _, _ in events)


def test_app_factory_installs_declared_lifespan(monkeypatch):
    from fastapi.testclient import TestClient

    from spectra_sherpa.app import main

    events = []
    monkeypatch.setattr(main, "_make_lifespan", lambda *_: resource("core", events))
    app = main.create_app(extra_lifespans=[resource("extension", events)])
    with TestClient(app):
        assert [(name, phase) for name, phase, _ in events] == [("core", "start"), ("extension", "start")]
    assert all(instance is app for _, _, instance in events)
    assert [(name, phase) for name, phase, _ in events][-2:] == [("extension", "stop"), ("core", "stop")]
