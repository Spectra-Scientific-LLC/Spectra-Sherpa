"""Retained-run navigation parity and closed consent/project/size admission."""

import asyncio
import json
from datetime import datetime, timezone

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker

from spectra_sherpa.app.core import security
from spectra_sherpa.app.models.data_egress import UserEgressDefaults
from spectra_sherpa.app.models.execution_run import ExecutionRun
from spectra_sherpa.app.models.project import Project
from spectra_sherpa.app.models.workflow import Workflow
from spectra_sherpa.app.services.inspection_bridge import InspectionBridge, InspectionRefused
from spectra_sherpa.app.services.inspection_grants import issue_inspection_credential


@pytest.fixture
async def run_facts(test_session, test_engine, test_user, monkeypatch):
    monkeypatch.setattr(security, "is_egress_enabled", lambda: True)
    project = Project(name="Retained facts", user_id=test_user.id)
    test_session.add(project)
    test_session.add(UserEgressDefaults(user_id=test_user.id, allow_llm_context=True))
    await test_session.flush()
    workflow = Workflow(name="Recorded workflow", user_id=test_user.id, project_id=project.id)
    test_session.add(workflow)
    await test_session.flush()
    runs = []
    for index in range(3):
        run = ExecutionRun(
            user_id=test_user.id,
            project_id=project.id,
            workflow_id=workflow.id,
            name=f"Run {index}",
            status="completed",
            run_kind="training",
            executed_at=datetime(2026, 1, index + 1, tzinfo=timezone.utc),
            params_snapshot={"secret": "parameter"},
            results_summary={"raw": [1, 2, 3]},
            diagnostics={"private": "diagnostic"},
            labels=["reviewed"],
            produced_artifact_uids=[f"artifact-{index}"],
        )
        test_session.add(run)
        runs.append(run)
    grant = await issue_inspection_credential(test_session, test_user, project.id, "Run reader", retained_results=True)
    await test_session.commit()
    return async_sessionmaker(test_engine, expire_on_commit=False), grant, runs, test_user


async def call(facts, operation, arguments):
    sessions, grant, *_ = facts
    return await InspectionBridge().call(
        sessions,
        token=grant.token,
        client_id=grant.identity.client_id,
        project_id=grant.identity.project_id,
        operation=operation,
        arguments=arguments,
    )


async def test_navigation_matches_workbench_and_never_loads_scientific_fields(run_facts):
    from spectra_sherpa.app.api.v1.routes.runs import list_project_runs

    sessions, grant, runs, user = run_facts
    result = await call(run_facts, "list_runs", {"limit": 2})
    async with sessions() as session:
        expected = await list_project_runs(
            grant.identity.project_id,
            kind=None,
            artifact_uid=None,
            sort_by="executed_at",
            sort_order="desc",
            session=session,
            current_user=user,
            limit=2,
            offset=0,
        )
    assert result["runs"] == [item.model_dump(mode="json") for item in expected.runs]
    assert result["next_offset"] == 2
    assert "parameter" not in json.dumps(result) and "diagnostic" not in json.dumps(result)
    detail = await call(run_facts, "get_run", {"run_id": runs[2].id})
    assert detail == result["runs"][0]
    last = await call(run_facts, "list_runs", {"limit": 2, "offset": 2})
    assert len(last["runs"]) == 1 and last["next_offset"] is None


async def test_project_summary_consent_does_not_grant_run_access(run_facts):
    sessions, original, runs, user = run_facts
    async with sessions() as session:
        grant = await issue_inspection_credential(
            session, user, original.identity.project_id, "Summaries", project_summaries=True
        )
        await session.commit()
    with pytest.raises(InspectionRefused, match="retained_result_consent_required"):
        await call((sessions, grant, runs, user), "list_runs", {})


async def test_cross_project_and_unbound_run_refused(run_facts):
    sessions, _, runs, user = run_facts
    async with sessions() as session:
        other = Project(name="Other", user_id=user.id)
        session.add(other)
        await session.flush()
        run = await session.get(ExecutionRun, runs[0].id)
        run.project_id = other.id
        legacy = await session.get(ExecutionRun, runs[1].id)
        legacy.project_id = None
        await session.commit()
    for run in runs[:2]:
        with pytest.raises(InspectionRefused, match="object_unavailable"):
            await call(run_facts, "get_run", {"run_id": run.id})
    assert len((await call(run_facts, "list_runs", {}))["runs"]) == 1


async def test_large_navigation_field_refused_without_reading_results(run_facts):
    async with run_facts[0]() as session:
        run = await session.get(ExecutionRun, run_facts[2][0].id)
        run.labels = ["x" * 10000]
        await session.commit()
    with pytest.raises(InspectionRefused, match="inspection_failed"):
        await call(run_facts, "get_run", {"run_id": run_facts[2][0].id})


@pytest.mark.parametrize("arguments", [{"limit": 26}, {"offset": 4097}, {"project_id": 1}])
async def test_navigation_arguments_cannot_expand_scope(run_facts, arguments):
    with pytest.raises(InspectionRefused, match="invalid_arguments"):
        await call(run_facts, "list_runs", arguments)


@pytest.mark.parametrize("change", ["project", "privacy", "consent", "workflow_project", "workflow_association"])
async def test_changes_during_navigation_read_prevent_disclosure(run_facts, monkeypatch, change):
    from spectra_sherpa.app.models.data_egress import DataEgressPermission
    from spectra_sherpa.app.models.inspection_grant import InspectionGrant
    from spectra_sherpa.app.services import inspection_runs

    entered, release = asyncio.Event(), asyncio.Event()
    original = inspection_runs.list_runs

    async def delayed(*args, **kwargs):
        result = await original(*args, **kwargs)
        entered.set()
        await release.wait()
        return result

    monkeypatch.setattr(inspection_runs, "list_runs", delayed)
    pending = asyncio.create_task(call(run_facts, "list_runs", {}))
    try:
        await asyncio.wait_for(entered.wait(), 3)
        async with run_facts[0]() as session:
            if change == "project":
                run = await session.get(ExecutionRun, run_facts[2][0].id)
                run.project_id = None
            elif change == "privacy":
                session.add(
                    DataEgressPermission(
                        user_id=run_facts[3].id,
                        data_type="models",
                        destination="llm_context",
                        allowed=False,
                    )
                )
            elif change == "consent":
                grant = await session.get(InspectionGrant, run_facts[1].identity.client_id)
                grant.retained_results = False
            elif change == "workflow_project":
                workflow = await session.get(Workflow, run_facts[2][0].workflow_id)
                workflow.project_id = None
            else:
                run = await session.get(ExecutionRun, run_facts[2][0].id)
                run.workflow_id = None
            await session.commit()
        release.set()
        with pytest.raises(InspectionRefused):
            await pending
    finally:
        release.set()
        if not pending.done():
            await pending


def test_project_context_run_interfaces_do_not_leak_into_provider_catalogs():
    from spectra_sherpa.app.services.tools.builtin.runs import inspection_run_catalog
    from spectra_sherpa.app.services.tools.registry import tool_registry

    before = tool_registry.to_openai_tools()
    for _ in range(2):
        catalog = inspection_run_catalog()
        assert {definition.name for definition in catalog.list_definitions()} == {"list_runs", "get_run"}
    assert tool_registry.get("list_runs") is None and tool_registry.get("get_run") is None
    assert tool_registry.to_openai_tools() == before
