"""Admission tests use actual persisted grants and isolated session boundaries."""

import asyncio
import threading

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from spectra_sherpa.app.models.inspection_grant import InspectionCall
from spectra_sherpa.app.models.project import Project
from spectra_sherpa.app.services import inspection_bridge as module
from spectra_sherpa.app.services.inspection_grants import (
    InspectionAccessDenied,
    issue_inspection_credential,
    revoke_inspection_credential,
)


@pytest.fixture
async def connection(test_session, test_engine, test_user):
    project = Project(name="Bound project", user_id=test_user.id)
    test_session.add(project)
    await test_session.flush()
    credential = await issue_inspection_credential(test_session, test_user, project.id, "Client")
    await test_session.commit()
    return async_sessionmaker(test_engine, expire_on_commit=False), credential


async def call(bridge, connection, **overrides):
    sessions, credential = connection
    arguments = dict(
        token=credential.token,
        client_id=credential.identity.client_id,
        project_id=credential.identity.project_id,
        operation="list_node_types",
        arguments={},
    )
    arguments.update(overrides)
    return await bridge.call(sessions, **arguments)


async def test_paginated_read_and_payload_free_project_log(connection):
    bridge = module.InspectionBridge()
    result = await call(bridge, connection, arguments={"limit": 2})
    assert len(result["items"]) == 2 and result["next_offset"] == 2
    second = await call(bridge, connection, arguments={"limit": 2, "offset": 2})
    assert {row["node_type"] for row in result["items"]}.isdisjoint(row["node_type"] for row in second["items"])
    sessions, credential = connection
    async with sessions() as session:
        rows = (await session.scalars(select(InspectionCall))).all()
        assert len(rows) == 2
        assert all(row.project_id == credential.identity.project_id and row.outcome == "success" for row in rows)
        assert all(row.response_bytes > 0 for row in rows)
        assert credential.token not in repr([row.__dict__ for row in rows])


@pytest.mark.parametrize(
    "operation", ["run_workflow", "propose_workflow", "export_run", "save_workflow", "apply_model"]
)
async def test_no_arbitrary_registry_or_execution_dispatch(connection, monkeypatch, operation):
    monkeypatch.setattr(module, "_node_page", lambda *_: pytest.fail("disallowed operation dispatched"))
    with pytest.raises(module.InspectionRefused, match="unsupported_operation"):
        await call(module.InspectionBridge(), connection, operation=operation)


@pytest.mark.parametrize(
    "arguments",
    [
        {"limit": 101},
        {"limit": True},
        {"offset": -1},
        {"project_id": 5},
        {"category": "x" * 65},
        {"workflow": {"nodes": []}},
    ],
)
async def test_invalid_and_scope_overriding_arguments_refused(connection, arguments):
    with pytest.raises(module.InspectionRefused, match="invalid_arguments"):
        await call(module.InspectionBridge(), connection, arguments=arguments)


async def test_scope_and_explicit_disclosure_denials(connection, test_user):
    bridge = module.InspectionBridge()
    sessions, credential = connection
    with pytest.raises(InspectionAccessDenied):
        await call(bridge, connection, project_id=credential.identity.project_id + 1)
    async with sessions() as session:
        denied = await issue_inspection_credential(
            session, test_user, credential.identity.project_id, "No data", disclosures=frozenset()
        )
        await session.commit()
    with pytest.raises(module.InspectionRefused, match="disclosure_denied"):
        await call(bridge, (sessions, denied))


async def test_revocation_during_read_prevents_result_disclosure(connection, test_user, monkeypatch):
    entered, finish = threading.Event(), threading.Event()

    def reader(_):
        entered.set()
        assert finish.wait(5)
        return {"items": [], "next_offset": None}

    monkeypatch.setattr(module, "_node_page", reader)
    pending = asyncio.create_task(call(module.InspectionBridge(), connection))
    try:
        assert await asyncio.to_thread(entered.wait, 2)
        sessions, credential = connection
        async with sessions() as session:
            await revoke_inspection_credential(session, test_user, credential.identity.client_id)
            await session.commit()
    finally:
        finish.set()
    with pytest.raises(InspectionAccessDenied):
        await pending


async def test_timeout_does_not_release_live_worker_capacity(connection, monkeypatch):
    finish = threading.Event()

    def reader(_):
        assert finish.wait(5)
        return {"items": [], "next_offset": None}

    monkeypatch.setattr(module, "_node_page", reader)
    bridge = module.InspectionBridge(concurrency=1, timeout_seconds=0.05)
    try:
        with pytest.raises(module.InspectionRefused, match="timeout"):
            await call(bridge, connection)
        with pytest.raises(module.InspectionRefused, match="busy"):
            await call(bridge, connection)
    finally:
        finish.set()
    await asyncio.sleep(0.02)


async def test_oversized_response_is_not_disclosed(connection, monkeypatch):
    monkeypatch.setattr(module, "_node_page", lambda _: {"items": ["x" * module.MAX_RESPONSE_BYTES]})
    with pytest.raises(module.InspectionRefused, match="response_limit"):
        await call(module.InspectionBridge(), connection)
