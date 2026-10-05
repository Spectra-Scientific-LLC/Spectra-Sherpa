"""The version endpoint exposes deployed identity, never an inferred git HEAD."""

from pathlib import Path

import pytest

from spectra_sherpa.app.api.v1.routes.health import app_version


@pytest.mark.asyncio
@pytest.mark.parametrize("revision", ["a" * 34 + "267376", "", "main", "0" * 40])
async def test_deployment_revision_comes_from_installed_artifact(monkeypatch, revision):
    original = Path.read_text

    def read(path, *args, **kwargs):
        if path == Path("/usr/local/share/spectra/source-revision"):
            return revision + "\n"
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", read)
    result = await app_version()
    if revision == "a" * 34 + "267376":
        assert result["build_commit"] == revision
    else:
        assert "build_commit" not in result


@pytest.mark.asyncio
@pytest.mark.parametrize("error", [FileNotFoundError(), UnicodeError("Invalid revision encoding")])
async def test_missing_deployment_artifact_keeps_version_available(monkeypatch, error):
    original = Path.read_text

    def read(path, *args, **kwargs):
        if path == Path("/usr/local/share/spectra/source-revision"):
            raise error
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", read)
    result = await app_version()
    assert result["backend_version"]
    assert "build_commit" not in result


@pytest.mark.asyncio
async def test_public_version_response_preserves_deployed_revision(monkeypatch):
    from fastapi import FastAPI
    from httpx import ASGITransport, AsyncClient

    from spectra_sherpa.app.api.v1.routes.health import router

    original = Path.read_text
    revision = "a" * 34 + "002676"

    def read(path, *args, **kwargs):
        if path == Path("/usr/local/share/spectra/source-revision"):
            return revision + "\n"
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", read)
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    async with AsyncClient(transport=ASGITransport(app), base_url="http://test") as client:
        response = await client.get("/api/v1/version")
    assert response.status_code == 200
    assert response.json()["build_commit"] == revision
