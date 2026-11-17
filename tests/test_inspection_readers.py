"""Project/egress admission and bounded existing-fact parity for MCP readers."""

import asyncio
import json
import threading
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import numpy as np
import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker

from spectra_sherpa.app.core import security
from spectra_sherpa.app.lib.sherpa_dataset import SherpaDataset
from spectra_sherpa.app.models.data_egress import DataEgressPermission, UserEgressDefaults
from spectra_sherpa.app.models.project import Project
from spectra_sherpa.app.models.workflow import Workflow
from spectra_sherpa.app.models.workflow_node import WorkflowNode
from spectra_sherpa.app.services import inspection_readers as readers
from spectra_sherpa.app.services.dataset_registry import DatasetRegistry, DatasetRegistryCapacityError, dataset_registry
from spectra_sherpa.app.services.inspection_bridge import InspectionBridge, InspectionRefused
from spectra_sherpa.app.services.inspection_grants import issue_inspection_credential


@pytest.fixture
async def facts(test_session, test_engine, test_user, monkeypatch):
    monkeypatch.setattr(security, "is_egress_enabled", lambda: True)
    project = Project(name="Inspected project", user_id=test_user.id)
    test_session.add(project)
    test_session.add(UserEgressDefaults(user_id=test_user.id, allow_llm_chat=True, allow_llm_context=True))
    await test_session.flush()
    workflow = Workflow(name="Existing workflow", user_id=test_user.id, project_id=project.id)
    test_session.add(workflow)
    await test_session.flush()
    test_session.add_all(
        [
            WorkflowNode(
                workflow_id=workflow.id, node_id="load", node_type="data.load", parameters={"private": "secret-value"}
            ),
            WorkflowNode(workflow_id=workflow.id, node_id="model", node_type="model.pca", parameters={}),
        ]
    )
    issued = await issue_inspection_credential(test_session, test_user, project.id, "Reader", project_summaries=True)
    await test_session.commit()
    ds = SherpaDataset(X=np.arange(12).reshape(3, 4), title="Existing dataset")
    handle = dataset_registry.register(ds, owner_user_id=test_user.id, project_id=project.id)
    return async_sessionmaker(test_engine, expire_on_commit=False), issued, handle, workflow.id, test_user


async def read(facts, operation, arguments):
    sessions, issued, *_ = facts
    return await InspectionBridge().call(
        sessions,
        token=issued.token,
        client_id=issued.identity.client_id,
        project_id=issued.identity.project_id,
        operation=operation,
        arguments=arguments,
    )


async def test_existing_dataset_and_workflow_summary_parity(facts):
    from spectra_sherpa.app.services.tools.builtin.datasets import describe_dataset
    from spectra_sherpa.app.services.tools.builtin.workflow import inspect_workflow

    sessions, issued, handle, workflow_id, user = facts
    described = await read(facts, "describe_dataset", {"dataset_id": handle})
    assert described == describe_dataset(handle, tier=0, user=user)
    assert described["structured"]["shape"] == [3, 4]
    inspected = await read(facts, "inspect_workflow", {"workflow_id": workflow_id})
    async with sessions() as session:
        from sqlalchemy import select
        from sqlalchemy.orm import selectinload

        from spectra_sherpa.app.models.user import User

        loaded = await session.scalar(
            select(User).where(User.id == user.id).options(selectinload(User.egress_defaults))
        )
        expected = await inspect_workflow(workflow_id, session=session, user=loaded)
    assert inspected == expected
    assert inspected["node_count"] == 2
    assert "parameters" not in inspected and "secret-value" not in json.dumps(inspected)


@pytest.mark.parametrize(
    "operation,arguments",
    [
        ("describe_dataset", {"dataset_id": "ignored", "tier": 3}),
        ("inspect_workflow", {"workflow_id": 1, "detail_level": "full"}),
        ("describe_dataset", {"dataset_id": "ignored", "project_id": 1}),
    ],
)
async def test_clients_cannot_expand_summary_or_project_scope(facts, operation, arguments):
    with pytest.raises(InspectionRefused, match="invalid_arguments"):
        await read(facts, operation, arguments)


async def test_same_owner_other_project_and_unbound_handles_are_refused(facts):
    sessions, issued, handle, workflow_id, user = facts
    async with sessions() as session:
        other = Project(name="Other project", user_id=user.id)
        session.add(other)
        await session.flush()
        workflow = await session.get(Workflow, workflow_id)
        workflow.project_id = other.id
        await session.commit()
    with pytest.raises(InspectionRefused, match="object_unavailable"):
        await read(facts, "inspect_workflow", {"workflow_id": workflow_id})
    ds = dataset_registry.get(handle, user_id=user.id)
    for project_id in (other.id, None):
        dataset_registry.register(ds, owner_user_id=user.id, project_id=project_id)
        with pytest.raises(InspectionRefused, match="object_unavailable"):
            await read(facts, "describe_dataset", {"dataset_id": handle})


@pytest.mark.parametrize("operation", ["describe_dataset", "inspect_workflow"])
async def test_global_privacy_switch_is_not_overridden_by_connection_consent(facts, monkeypatch, operation):
    monkeypatch.setattr(security, "is_egress_enabled", lambda: False)
    arguments = {"dataset_id": facts[2]} if operation == "describe_dataset" else {"workflow_id": facts[3]}
    with pytest.raises(InspectionRefused, match="privacy_denied"):
        await read(facts, operation, arguments)


async def test_privacy_change_during_read_prevents_disclosure(facts, monkeypatch):
    from spectra_sherpa.app.services.tools.builtin import datasets

    entered, finish = threading.Event(), threading.Event()
    original = datasets.describe_dataset

    def delayed(*args, **kwargs):
        entered.set()
        assert finish.wait(5)
        return original(*args, **kwargs)

    monkeypatch.setattr(datasets, "describe_dataset", delayed)
    pending = asyncio.create_task(read(facts, "describe_dataset", {"dataset_id": facts[2]}))
    try:
        assert await asyncio.to_thread(entered.wait, 2)
        async with facts[0]() as session:
            session.add(
                DataEgressPermission(
                    user_id=facts[4].id, data_type="metadata", destination="llm_context", allowed=False
                )
            )
            await session.commit()
        finish.set()
        with pytest.raises(InspectionRefused, match="privacy_denied"):
            await pending
    finally:
        finish.set()
        if not pending.done():
            await pending


async def test_workflow_summary_cost_limit(facts, monkeypatch):
    monkeypatch.setattr(readers, "MAX_WORKFLOW_NODES", 1)
    with pytest.raises(InspectionRefused):
        await read(facts, "inspect_workflow", {"workflow_id": facts[3]})


def test_registry_refuses_scope_and_copy_budget_before_snapshot(monkeypatch):
    registry = DatasetRegistry()
    handle = registry.register(SherpaDataset(X=np.zeros((2, 2))), owner_user_id=7, project_id=8)
    monkeypatch.setattr(SherpaDataset, "snapshot", lambda _: pytest.fail("unauthorized/oversized copy"))
    with pytest.raises(PermissionError):
        registry.get(handle, user_id=7, project_id=9)
    with pytest.raises(DatasetRegistryCapacityError):
        registry.get(handle, user_id=7, project_id=8, max_snapshot_bytes=1)


async def test_policy_lookup_failure_denies_but_missing_override_preserves_defaults(monkeypatch):
    monkeypatch.setattr(security, "is_egress_enabled", lambda: True)
    user = SimpleNamespace(id=1, egress_defaults=SimpleNamespace(allow_llm_context=True))
    session = SimpleNamespace(execute=AsyncMock(side_effect=RuntimeError("policy unavailable")))
    options = dict(data_type="metadata", destination="llm_context", session=session, fail_closed_on_policy_error=True)
    assert not await security.check_egress_permission(user, "allow_llm_context", **options)
    result = MagicMock()
    result.scalar_one_or_none.return_value = None
    session.execute = AsyncMock(return_value=result)
    assert await security.check_egress_permission(user, "allow_llm_context", **options)


async def test_catalog_only_credentials_cannot_read_project_facts(facts):
    sessions, issued, handle, workflow_id, user = facts
    async with sessions() as session:
        catalog = await issue_inspection_credential(session, user, issued.identity.project_id, "Catalog only")
        await session.commit()
    legacy = (sessions, catalog, handle, workflow_id, user)
    assert (await read(legacy, "list_node_types", {"limit": 1}))["items"]
    for operation, arguments in (
        ("describe_dataset", {"dataset_id": handle}),
        ("inspect_workflow", {"workflow_id": workflow_id}),
    ):
        with pytest.raises(InspectionRefused, match="project_summary_consent_required"):
            await read(legacy, operation, arguments)


async def test_unavailable_defaults_store_refuses_disclosure(monkeypatch):
    monkeypatch.setattr(security, "is_egress_enabled", lambda: True)

    class DetachedUser:
        id = 1

        @property
        def egress_defaults(self):
            raise RuntimeError("Detached relationship")

    result = MagicMock()
    result.scalar_one_or_none.return_value = None
    session = SimpleNamespace(execute=AsyncMock(side_effect=[result, RuntimeError("Defaults unavailable")]))
    assert not await security.check_egress_permission(
        DetachedUser(),
        "allow_llm_context",
        data_type="metadata",
        destination="llm_context",
        session=session,
        fail_closed_on_policy_error=True,
    )
