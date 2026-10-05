from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException
from sqlalchemy import event

from spectra_sherpa.app.api.v1.routes.runs import get_project_run, list_project_runs
from spectra_sherpa.app.models.execution_run import ExecutionRun


@pytest.mark.asyncio
async def test_sheet_rename_updates_navigation_without_rewriting_history(test_session, test_user):
    from spectra_sherpa.app.api.v1.routes.runs import inspect_run_evidence
    from spectra_sherpa.app.models.workflow import Workflow

    workflow = Workflow(user_id=test_user.id, name="Original sheet")
    test_session.add(workflow)
    await test_session.flush()
    auto = ExecutionRun(
        user_id=test_user.id,
        workflow_id=workflow.id,
        name="PLS — abc12345",
        source_type="auto",
        status="completed",
        run_kind="training",
        params_snapshot={},
        results_summary={},
        executed_at=datetime.now(timezone.utc),
    )
    named = ExecutionRun(
        user_id=test_user.id,
        workflow_id=workflow.id,
        name="Chosen run name",
        source_type="named",
        status="completed",
        run_kind="training",
        params_snapshot={},
        results_summary={},
        executed_at=datetime.now(timezone.utc),
    )
    test_session.add_all([auto, named])
    await test_session.commit()
    workflow.name = "Peak Find + PLS"
    await test_session.commit()
    page = await list_project_runs(
        project_id=None,
        kind=None,
        artifact_uid=None,
        sort_by="name",
        sort_order="asc",
        limit=50,
        offset=0,
        session=test_session,
        current_user=test_user,
    )
    assert [run.display_name for run in page.runs] == ["Chosen run name", "Peak Find + PLS"]
    detail = await inspect_run_evidence(auto.id, project_id=None, session=test_session, current_user=test_user)
    assert detail["run"]["display_name"] == "Peak Find + PLS"
    assert detail["run"]["workflow_name"] == "Peak Find + PLS"
    assert detail["run"]["name"] == "PLS — abc12345"
    await test_session.refresh(auto)
    assert auto.name == "PLS — abc12345"


def test_new_training_run_records_sheet_name():
    from spectra_sherpa.app.api.v1.routes.workflows._helpers import _derive_run_display_name

    assert (
        _derive_run_display_name("Peak Find + PLS", "digest", [{"model_type": "pls", "artifact_uid": "abc12345"}])
        == "Peak Find + PLS"
    )


@pytest.mark.asyncio
async def test_history_pages_exclude_evidence_and_preserve_exact_artifact_filter(test_session, test_user):
    now = datetime.now(timezone.utc)
    for index in range(4):
        test_session.add(
            ExecutionRun(
                user_id=test_user.id,
                name=f"Run {index}",
                status="completed",
                run_kind="data",
                params_snapshot={"graph": "private detail"},
                results_summary={"matrix": list(range(10000))},
                diagnostics={"large": list(range(10000))},
                executed_at=now,
                produced_artifact_uids=["artifact-1" if index < 3 else "artifact-10"],
            )
        )
    await test_session.commit()
    test_session.expunge_all()
    statements = []

    def capture(_conn, _cursor, statement, _parameters, _context, _many):
        statements.append(statement)

    engine = test_session.get_bind()
    event.listen(engine, "before_cursor_execute", capture)
    try:
        page = await list_project_runs(
            project_id=None,
            kind="data",
            artifact_uid="artifact-1",
            sort_by="executed_at",
            sort_order="desc",
            limit=2,
            offset=1,
            session=test_session,
            current_user=test_user,
        )
    finally:
        event.remove(engine, "before_cursor_execute", capture)
    assert page.total == 3
    assert len(page.runs) == 2
    assert len(page.model_dump_json()) < 2048
    assert "diagnostics" not in page.model_dump_json()
    assert "params_snapshot" not in statements[-1]
    assert "results_summary" not in statements[-1]
    detail = await get_project_run(page.runs[0].id, project_id=None, session=test_session, current_user=test_user)
    assert len(detail.results_summary["matrix"]) == 10000


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("sort_by", "ascending_indexes"),
    [
        ("name", [0, 3, 2, 1]),
        ("status", [1, 3, 2, 0]),
        ("run_kind", [2, 1, 3, 0]),
        ("executed_at", [2, 0, 3, 1]),
    ],
)
async def test_history_sorting_is_server_owned_and_stable(test_session, test_user, sort_by, ascending_indexes):
    timestamp = datetime.now(timezone.utc)
    rows = [
        ExecutionRun(
            user_id=test_user.id,
            name="Alpha",
            status="running",
            run_kind="training",
            params_snapshot={},
            results_summary={},
            executed_at=timestamp + timedelta(seconds=1),
        ),
        ExecutionRun(
            user_id=test_user.id,
            name="Zulu",
            status="completed",
            run_kind="data",
            params_snapshot={},
            results_summary={},
            executed_at=timestamp + timedelta(seconds=2),
        ),
        ExecutionRun(
            user_id=test_user.id,
            name="Mike",
            status="failed",
            run_kind="batch_inference",
            params_snapshot={},
            results_summary={},
            executed_at=timestamp,
        ),
        ExecutionRun(
            user_id=test_user.id,
            name="Alpha",
            status="error",
            run_kind="other",
            params_snapshot={},
            results_summary={},
            executed_at=timestamp + timedelta(seconds=1),
        ),
    ]
    test_session.add_all(rows)
    await test_session.commit()

    ascending = await list_project_runs(
        project_id=None,
        kind=None,
        artifact_uid=None,
        sort_by=sort_by,
        sort_order="asc",
        limit=2,
        offset=0,
        session=test_session,
        current_user=test_user,
    )
    ascending_next = await list_project_runs(
        project_id=None,
        kind=None,
        artifact_uid=None,
        sort_by=sort_by,
        sort_order="asc",
        limit=2,
        offset=2,
        session=test_session,
        current_user=test_user,
    )
    descending = await list_project_runs(
        project_id=None,
        kind=None,
        artifact_uid=None,
        sort_by=sort_by,
        sort_order="desc",
        limit=4,
        offset=0,
        session=test_session,
        current_user=test_user,
    )

    ascending_ids = [rows[index].id for index in ascending_indexes]
    assert [item.id for item in (*ascending.runs, *ascending_next.runs)] == ascending_ids
    assert [item.id for item in descending.runs] == list(reversed(ascending_ids))


@pytest.mark.asyncio
async def test_detail_does_not_cross_project_scope(test_session, test_user):
    run = ExecutionRun(
        user_id=test_user.id,
        name="Hidden",
        status="completed",
        run_kind="other",
        params_snapshot={},
        results_summary={},
        executed_at=datetime.now(timezone.utc),
    )
    test_session.add(run)
    await test_session.commit()
    with pytest.raises(HTTPException) as exc:
        await get_project_run(run.id, project_id=999, session=test_session, current_user=test_user)
    assert exc.value.status_code == 404
