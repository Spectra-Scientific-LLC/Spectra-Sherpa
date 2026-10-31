"""Temporary diagnostics must be opt-in, authenticated, bounded and data-free."""

import logging
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from spectra_sherpa.app.api.deps import get_current_user
from spectra_sherpa.app.api.v1.routes import logs


def test_trace_is_private_disabled_by_default_and_closed(monkeypatch, caplog):
    app = FastAPI()
    app.include_router(logs.router)
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id=42)
    client = TestClient(app)
    body = {
        "page_id": "11111111-1111-4111-8111-111111111111",
        "events": [{"seq": 1, "operation": "workbook_load", "state": "ok", "node_count": 5}],
    }
    monkeypatch.setattr(logs, "settings", SimpleNamespace(gui_trace=False))
    assert client.post("/logs/workspace-events", json=body).status_code == 404
    assert "/logs/workspace-events" not in app.openapi()["paths"]
    monkeypatch.setattr(logs, "settings", SimpleNamespace(gui_trace=True))
    logs._trace_windows.clear()
    with caplog.at_level(logging.INFO, logger="spectra_sherpa.gui_trace"):
        assert client.post("/logs/workspace-events", json=body).status_code == 204
    assert "actor=42" in caplog.text and '"node_count":5' in caplog.text
    for forbidden in ("token", "values", "error_message", "sample_ids", "url"):
        bad = {**body, "events": [{**body["events"][0], forbidden: "never log this"}]}
        assert client.post("/logs/workspace-events", json=bad).status_code == 422
    assert "never log this" not in caplog.text
    assert client.post("/logs/workspace-events", json={**body, "events": body["events"] * 31}).status_code == 422
    logs._trace_windows[42] = (logs.time.monotonic(), 600)
    assert client.post("/logs/workspace-events", json=body).status_code == 429
    logs._trace_windows.clear()


def test_trace_requires_the_existing_actor_dependency():
    route = next(r for r in logs.router.routes if r.path == "/logs/workspace-events")
    assert any(d.call is get_current_user for d in route.dependant.dependencies)


def test_loading_trace_contract_accepts_only_bounded_typed_diagnostics(monkeypatch, caplog):
    app = FastAPI()
    app.include_router(logs.router)
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id=42)
    client = TestClient(app)
    monkeypatch.setattr(logs, "settings", SimpleNamespace(gui_trace=True))
    logs._trace_windows.clear()
    event = {
        "seq": 1,
        "operation": "workflow_execute_finalize",
        "state": "ok",
        "attempt_id": 1,
        "project_id": 126,
        "workflow_id": 424,
        "run_id": 698,
        "workbook_context_ready": True,
        "workbook_loading": False,
        "workflow_loading": False,
        "workflow_id_matches": True,
        "workflow_owner_current": True,
        "execution_owner_current": True,
        "loading_clear_authorized": True,
    }
    body = {"page_id": "11111111-1111-4111-8111-111111111111", "events": [event]}
    with caplog.at_level(logging.INFO, logger="spectra_sherpa.gui_trace"):
        for operation in (
            "workflow_loading",
            "workflow_execute_http",
            "workflow_execute_apply",
            "workflow_execute_finalize",
        ):
            assert (
                client.post(
                    "/logs/workspace-events", json={**body, "events": [{**event, "operation": operation}]}
                ).status_code
                == 204
            )
    assert '"attempt_id":1' in caplog.text
    for field in (
        "workbook_context_ready",
        "workbook_loading",
        "workflow_loading",
        "workflow_id_matches",
        "workflow_owner_current",
        "execution_owner_current",
        "loading_clear_authorized",
    ):
        for invalid in ("true", 1, 0):
            assert (
                client.post("/logs/workspace-events", json={**body, "events": [{**event, field: invalid}]}).status_code
                == 422
            )
    for field in ("attempt_id", "run_id"):
        for invalid in (0, -1, "1", True):
            assert (
                client.post("/logs/workspace-events", json={**body, "events": [{**event, field: invalid}]}).status_code
                == 422
            )
    assert (
        client.post("/logs/workspace-events", json={**body, "events": [{**event, "attempt_id": 1000001}]}).status_code
        == 422
    )
    for field in ("url", "token", "values", "name", "error_message"):
        assert (
            client.post(
                "/logs/workspace-events", json={**body, "events": [{**event, field: "private-never-log"}]}
            ).status_code
            == 422
        )
    assert "private-never-log" not in caplog.text
    assert (
        client.post("/logs/workspace-events", json={**body, "events": [{**event, "operation": "invented"}]}).status_code
        == 422
    )
    assert "/logs/workspace-events" not in app.openapi()["paths"]
    logs._trace_windows.clear()
