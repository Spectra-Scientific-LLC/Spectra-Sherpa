"""HTTP admission and secret handling for the local inspection bridge."""

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker

from spectra_sherpa.app.api.v1.routes import inspection as routes
from spectra_sherpa.app.models.project import Project

CONTROL = {"X-Spectra-Workbench": "inspection", "Origin": "http://localhost:5173"}
CREATE = {"client_label": "External client", "confirm_external_provider": True}


@pytest.fixture
async def endpoint(test_session, test_engine, test_user, monkeypatch):
    app = FastAPI()
    app.include_router(routes.router)
    sessions = async_sessionmaker(test_engine, expire_on_commit=False)

    async def session():
        async with sessions() as value:
            yield value

    app.dependency_overrides[routes.get_session] = session
    app.dependency_overrides[routes.get_current_user] = lambda: test_user
    app.dependency_overrides[routes.inspection_sessions] = lambda: sessions
    monkeypatch.setattr(routes, "is_local", lambda: True)
    project = Project(name="HTTP inspection", user_id=test_user.id)
    test_session.add(project)
    await test_session.commit()
    async with AsyncClient(
        transport=ASGITransport(app=app, client=("127.0.0.1", 1234)), base_url="http://localhost"
    ) as client:
        yield client, project.id


async def test_issue_once_read_revoke_and_call_history(endpoint):
    client, project = endpoint
    path = f"/projects/{project}/inspection-clients"
    issued = await client.post(path, json=CREATE, headers=CONTROL)
    assert issued.status_code == 201, issued.text
    assert issued.headers["cache-control"] == "no-store"
    info = issued.json()
    assert info["project_summaries"] is False
    assert info["retained_results"] is False
    secret = info["credential"]
    listed = await client.get(path, headers={"X-Spectra-Workbench": "inspection"})
    assert listed.status_code == 200
    assert secret not in listed.text and "token_digest" not in listed.text
    call_path = f"/inspection/{project}/{info['client_id']}/call"
    headers = {"Authorization": f"Bearer {secret}"}
    body = {"operation": "list_node_types", "arguments": {"limit": 1}}
    read = await client.post(call_path, headers=headers, json=body)
    assert read.status_code == 200, read.text
    assert len(read.json()["items"]) == 1
    history = await client.get(f"/projects/{project}/inspection-calls", headers=CONTROL)
    assert history.status_code == 200 and history.json()[0]["outcome"] == "success"
    assert secret not in history.text and "items" not in history.text
    revoked = await client.delete(f"{path}/{info['client_id']}", headers=CONTROL)
    assert revoked.status_code == 204
    assert (await client.post(call_path, headers=headers, json=body)).status_code == 403


@pytest.mark.parametrize(
    "headers",
    [{}, {**CONTROL, "Origin": "https://evil.example"}, {**CONTROL, "Authorization": "Bearer ssmcp_untrusted"}],
)
async def test_connection_control_requires_workbench_request(endpoint, headers):
    client, project = endpoint
    assert (
        await client.post(f"/projects/{project}/inspection-clients", headers=headers, json=CREATE)
    ).status_code == 403


async def test_explicit_confirmation_body_bounds_and_no_implicit_bridge_identity(endpoint):
    client, project = endpoint
    path = f"/projects/{project}/inspection-clients"
    assert (await client.post(path, headers=CONTROL, json={"client_label": "No consent"})).status_code == 422
    assert (await client.post(path, headers=CONTROL, content=b"x" * 8193)).status_code == 413
    response = await client.post(f"/inspection/{project}/unknown/call", json={"operation": "list_node_types"})
    assert response.status_code == 401


async def test_hosted_mode_and_non_loopback_are_not_admitted(endpoint, monkeypatch):
    client, project = endpoint
    path = f"/projects/{project}/inspection-clients"
    monkeypatch.setattr(routes, "is_local", lambda: False)
    assert (await client.post(path, headers=CONTROL, json=CREATE)).status_code == 404
    monkeypatch.setattr(routes, "is_local", lambda: True)
    monkeypatch.setattr(routes, "get_client_host", lambda _: "192.0.2.1")
    assert (await client.post(path, headers=CONTROL, json=CREATE)).status_code == 404


async def test_custom_port_same_origin_control_and_rebinding_denial(endpoint):
    client, project = endpoint
    path = f"http://127.0.0.1:8001/projects/{project}/inspection-clients"
    headers = {"X-Spectra-Workbench": "inspection", "Origin": "http://127.0.0.1:8001"}
    issued = await client.post(path, headers=headers, json=CREATE)
    assert issued.status_code == 201
    assert (await client.delete(f"{path}/{issued.json()['client_id']}", headers=headers)).status_code == 204
    hostile = "http://rebound.example:8001"
    headers["Origin"] = hostile
    assert (
        await client.post(f"{hostile}/projects/{project}/inspection-clients", headers=headers, json=CREATE)
    ).status_code == 403


@pytest.mark.parametrize("field", ["project_summaries", "retained_results"])
async def test_project_summary_consent_is_explicit_and_retained(endpoint, field):
    client, project = endpoint
    path = f"/projects/{project}/inspection-clients"
    issued = await client.post(path, headers=CONTROL, json={**CREATE, field: True})
    assert issued.status_code == 201, issued.text
    assert issued.json()[field] is True
    listed = await client.get(path, headers=CONTROL)
    assert listed.json()[0][field] is True
    invalid = await client.post(path, headers=CONTROL, json={**CREATE, field: "true"})
    assert invalid.status_code == 422
