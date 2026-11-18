"""Unknown archived workflows remain inspectable without import-side mutation."""

import io
import json
import zipfile

import pytest

from spectra_sherpa.app.services.retained_archive_inspection import inspect_archive_workflow
from spectra_sherpa.core.retained_graph import RetainedGraphError


def archive(project):
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w", compression=zipfile.ZIP_DEFLATED) as zipped:
        zipped.writestr("project.json", json.dumps(project))
    return stream.getvalue()


def graph(name="Saved graph"):
    return {
        "name": name,
        "nodes": [{"node_id": "p", "node_type": "pro.absent.record", "parameters": {"units": "mg/L"}}],
        "edges": [],
    }


def test_unknown_root_and_child_graphs_are_read_only_evidence():
    payload = archive(
        {"name": "Root", "workflows": [graph()], "children": [{"name": "Child", "workflows": [graph("Historical")]}]}
    )
    first = inspect_archive_workflow(payload, max_uncompressed_bytes=100000)
    second = inspect_archive_workflow(payload, workflow_index=1, max_uncompressed_bytes=100000)
    assert first.graph.inspection_only and second.graph.inspection_only
    assert first.workflow_count == second.workflow_count == 2
    assert first.project_name == "Root" and second.project_name == "Child"
    assert second.graph.name == "Historical"
    assert second.graph.nodes[0].parameters == {"units": "mg/L"}
    with pytest.raises(RetainedGraphError, match="index"):
        inspect_archive_workflow(payload, workflow_index=2, max_uncompressed_bytes=100000)


def test_large_metadata_is_refused_before_project_read(monkeypatch):
    from spectra_sherpa.app.services import sherpa_object

    def forbidden_read(*args):
        raise AssertionError("oversized project was inflated")

    payload = archive({"name": "x" * (8 * 1024 * 1024 + 1), "workflows": [graph()]})
    monkeypatch.setattr(sherpa_object, "read_project_payload", forbidden_read)
    with pytest.raises(RetainedGraphError):
        inspect_archive_workflow(payload, max_uncompressed_bytes=20 * 1024 * 1024)


def test_unsafe_archive_members_do_not_reach_graph_parser():
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as zipped:
        zipped.writestr("project.json", json.dumps({"workflows": [graph()]}))
        zipped.writestr("../renderer.py", "raise RuntimeError('never execute')")
    with pytest.raises(RetainedGraphError):
        inspect_archive_workflow(stream.getvalue(), max_uncompressed_bytes=100000)


def test_large_optional_manifest_is_refused_before_inflation(monkeypatch):
    from spectra_sherpa.app.services.sherpa_object import SHERPA_OBJECT_MANIFEST

    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w", compression=zipfile.ZIP_DEFLATED) as zipped:
        zipped.writestr("project.json", json.dumps({"workflows": [graph()]}))
        zipped.writestr(SHERPA_OBJECT_MANIFEST, json.dumps({"padding": "x" * (8 * 1024 * 1024)}))
    original = zipfile.ZipFile.read

    def guarded_read(self, name, *args, **kwargs):
        if name == SHERPA_OBJECT_MANIFEST:
            raise AssertionError("oversized manifest was inflated")
        return original(self, name, *args, **kwargs)

    monkeypatch.setattr(zipfile.ZipFile, "read", guarded_read)
    with pytest.raises(RetainedGraphError):
        inspect_archive_workflow(stream.getvalue(), max_uncompressed_bytes=20 * 1024 * 1024)


async def test_cancelled_parse_retains_capacity_until_its_thread_exits(monkeypatch):
    import asyncio
    import threading

    from spectra_sherpa.app.services import retained_archive_inspection as inspection

    started, release, finished = threading.Event(), threading.Event(), threading.Event()
    monkeypatch.setattr(inspection, "_inspection_slots", threading.BoundedSemaphore(1))

    def parse(*args, **kwargs):
        started.set()
        try:
            assert release.wait(10)
            return "finished"
        finally:
            finished.set()

    monkeypatch.setattr(inspection, "inspect_archive_workflow", parse)

    async def own_request():
        with inspection.archive_inspection_slot():
            await inspection.inspect_archive_workflow_owned(b"fixture", workflow_index=0, max_uncompressed_bytes=100)

    task = asyncio.create_task(own_request())
    try:
        assert await asyncio.wait_for(asyncio.to_thread(started.wait), 5)
        task.cancel()
        await asyncio.sleep(0)
        task.cancel()
        await asyncio.sleep(0)
        assert not task.done()
        with pytest.raises(inspection.ArchiveInspectionBusy):
            with inspection.archive_inspection_slot():
                pytest.fail("capacity released before parser exit")
    finally:
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await task
    assert finished.is_set()
    with inspection.archive_inspection_slot():
        pass


async def test_actual_route_selects_inert_inspector_not_workflow_mutation():
    from types import SimpleNamespace

    import httpx
    from fastapi import FastAPI

    from spectra_sherpa.app.api.deps import get_current_user
    from spectra_sherpa.app.api.v1.routes.projects import router

    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id=1)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://test") as client:
        response = await client.post(
            "/projects/objects/inspect-workflow",
            files={"file": ("fixture.sherpa", archive({"workflows": [graph()]}), "application/zip")},
        )
    assert response.status_code == 200, response.text
    assert response.json()["graph"]["inspection_only"] is True
    assert response.json()["graph"]["nodes"][0]["node_type"] == "pro.absent.record"
