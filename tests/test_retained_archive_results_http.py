"""Uploaded archive evidence is read-only and preserves exact envelope bytes."""

from types import SimpleNamespace

import pytest
from fastapi import FastAPI, HTTPException
from httpx import ASGITransport, AsyncClient

from spectra_sherpa.app.api.deps import get_current_user
from spectra_sherpa.app.api.v1.routes import projects
from spectra_sherpa.app.services.retained_archive_inspection import archive_inspection_slot
from tests.test_retained_archive_results import archived  # noqa: F401


@pytest.fixture
async def archive_client(monkeypatch):
    app = FastAPI()
    app.include_router(projects.router)
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id=7)
    from spectra_sherpa.app.services.dag.node_base import node_registry

    def cannot_execute(*args, **kwargs):
        pytest.fail("Archive inspection constructed executable node code")

    monkeypatch.setattr(node_registry, "create_node", cannot_execute)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://archive.test") as client:
        yield app, client


async def test_archive_index_and_selected_output_preserve_original_values(archive_client, archived):
    _, client = archive_client
    build, encoded, _ = archived
    upload = {"file": ("history.sherpa", build(), "application/zip")}
    index = await client.post("/projects/objects/inspect-results", files=upload)
    assert index.status_code == 200
    assert index.json()["inspection_only"] is True
    assert index.json()["prior_unrecorded_history"] == "unknown"
    output = await client.post(
        "/projects/objects/inspect-output", files=upload, params={"run_id": 42, "node_id": "absent", "port": "record"}
    )
    assert output.status_code == 200
    assert output.content == encoded
    assert b"9007199254740993" in output.content
    assert output.headers["cache-control"] == "no-store"
    assert output.json()["value"]["role"] == "held_out"


@pytest.mark.parametrize(
    "selection",
    [
        {"run_id": 43, "node_id": "absent", "port": "record"},
        {"run_id": 42, "node_id": "absent", "port": "missing"},
        {"run_id": 42, "node_id": "other", "port": "record"},
    ],
)
async def test_unknown_selection_does_not_substitute_another_output(archive_client, archived, selection):
    _, client = archive_client
    build, _, _ = archived
    response = await client.post(
        "/projects/objects/inspect-output", files={"file": ("history.sherpa", build())}, params=selection
    )
    assert response.status_code == 400
    assert "value" not in response.json()


async def test_authentication_denial_precedes_parser(archive_client, monkeypatch):
    app, client = archive_client

    def denied():
        raise HTTPException(401, "Not authenticated")

    def cannot_parse(*args, **kwargs):
        pytest.fail("Unauthenticated request reached archive parser")

    app.dependency_overrides[get_current_user] = denied
    monkeypatch.setattr(projects, "read_archived_results", cannot_parse)
    response = await client.post("/projects/objects/inspect-results", files={"file": ("history.sherpa", b"invalid")})
    assert response.status_code == 401


async def test_capacity_refusal_precedes_upload_copy(archive_client, archived, monkeypatch):
    _, client = archive_client
    build, _, _ = archived

    def cannot_copy(*args, **kwargs):
        pytest.fail("Busy request copied archive into memory")

    monkeypatch.setattr(projects, "_read_upload_with_limit", cannot_copy)
    with archive_inspection_slot(), archive_inspection_slot():
        response = await client.post("/projects/objects/inspect-results", files={"file": ("history.sherpa", build())})
    assert response.status_code == 503
    assert response.headers["retry-after"] == "1"
