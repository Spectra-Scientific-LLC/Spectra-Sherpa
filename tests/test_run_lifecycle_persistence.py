"""Regression coverage for the post-PR #158 hotfix bundle.

- REM-1: PR #158 narrowed ``execution_run.status`` to terminal-only,
  breaking the batch route (deploy.py) and folder-watch service which
  pre-create rows in ``status="running"``. These tests insert rows
  exactly the way those code paths do and confirm they no longer
  violate the relaxed CHECK constraint.
- REM-3: PR #158 / #161's timeout handler raised 504 without persisting
  an ExecutionRun. The handler now writes a ``status="cancelled"`` row
  before raising, so the timeout shows up in run history AND a retried
  ``Idempotency-Key`` replays the cancelled response instead of silently
  re-executing.
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from unittest.mock import patch

import pytest
from sqlalchemy import select

from spectra_sherpa.app.models.execution_run import ExecutionRun
from spectra_sherpa.app.models.user import User

# ---------------------------------------------------------------------------
# REM-1 — deploy.py / folder_watch_service.py pre-create row in "running"
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_batch_route_running_row_succeeds_against_status_check(test_session, test_user: User):
    """Mirrors the insert pattern in ``app/api/v1/routes/deploy.py:140``."""
    from spectra_sherpa.app.models.project import Project
    from spectra_sherpa.app.models.workflow import Workflow

    project = Project(user_id=test_user.id, name="batch project")
    test_session.add(project)
    await test_session.flush()
    workflow = Workflow(user_id=test_user.id, project_id=project.id, name="batch wf")
    test_session.add(workflow)
    await test_session.flush()

    row = ExecutionRun(
        project_id=workflow.project_id,
        workflow_id=workflow.id,
        workflow_version_id=None,
        user_id=test_user.id,
        name="Batch: /tmp/test",
        status="running",
        params_snapshot={},
        results_summary={},
        executed_at=datetime.utcnow(),
        source_type="batch",
        run_kind="batch_inference",
        source_metadata={"folder_path": "/tmp/test", "file_count": 1},
        labels=[],
    )
    test_session.add(row)
    await test_session.flush()  # must not raise IntegrityError
    assert row.id is not None
    await test_session.rollback()


@pytest.mark.asyncio
async def test_folder_watch_running_row_succeeds_against_status_check(test_session, test_user: User):
    """Mirrors the insert pattern in ``app/services/folder_watch_service.py:197``."""
    from spectra_sherpa.app.models.project import Project
    from spectra_sherpa.app.models.workflow import Workflow

    project = Project(user_id=test_user.id, name="watch project")
    test_session.add(project)
    await test_session.flush()
    workflow = Workflow(user_id=test_user.id, project_id=project.id, name="watch wf")
    test_session.add(workflow)
    await test_session.flush()

    row = ExecutionRun(
        project_id=workflow.project_id,
        workflow_id=workflow.id,
        user_id=test_user.id,
        name="Watch: test (1 files)",
        status="running",
        params_snapshot={},
        results_summary={},
        executed_at=datetime.utcnow(),
        source_type="folder_watch",
        source_metadata={"watch_id": 1, "watch_name": "test", "file_count": 1},
        labels=[],
    )
    test_session.add(row)
    await test_session.flush()  # must not raise IntegrityError
    assert row.id is not None
    await test_session.rollback()


# ---------------------------------------------------------------------------
# REM-3 — timeout handler persists a "cancelled" ExecutionRun
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_auto_persist_run_writes_cancelled_status(test_session, test_user: User):
    """The timeout handler in execute.py calls ``_auto_persist_run`` with
    ``final_status="cancelled"``; this verifies that path against the
    relaxed CHECK constraint and confirms source_metadata captures the
    TimeoutError exception class so a retried Idempotency-Key replay
    surfaces the timeout."""
    from spectra_sherpa.app.api.v1.routes.workflows._helpers import (
        _auto_persist_run,
        _build_source_metadata,
    )
    from spectra_sherpa.app.models.project import Project
    from spectra_sherpa.app.models.workflow import Workflow

    project = Project(user_id=test_user.id, name="timeout helper p")
    test_session.add(project)
    await test_session.flush()
    workflow = Workflow(user_id=test_user.id, project_id=project.id, name="timeout helper wf")
    test_session.add(workflow)
    await test_session.commit()

    run_id = await _auto_persist_run(
        test_session,
        workflow_id=workflow.id,
        project_id=project.id,
        user_id=test_user.id,
        wf_version_id=None,
        serialized_results={},
        diagnostics_serialized={},
        node_statuses={},
        final_status="cancelled",
        error_msg="Workflow execution timed out after 30s",
        integrity_hash=None,
        produced_artifact_uids=[],
        params_snapshot={},
        source_metadata=_build_source_metadata(
            executor_status="cancelled",
            had_serialization_errors=False,
            exception_class="TimeoutError",
        ),
        idempotency_key="timeoutkey1234",
    )
    assert run_id is not None

    row = (await test_session.execute(select(ExecutionRun).where(ExecutionRun.id == run_id))).scalar_one()
    assert row.status == "cancelled"
    assert "timed out" in (row.error or "").lower()
    assert row.idempotency_key == "timeoutkey1234"
    assert row.source_metadata is not None
    assert row.source_metadata.get("exception_class") == "TimeoutError"


def test_timeout_handler_calls_auto_persist_run_with_cancelled_status():
    """The timeout branch awaits the shared wrapper, which forwards persistence.

    Pin both hops, cancelled status, retry identity and ordering before the 504.
    The database test above independently verifies terminal-row persistence.
    """
    import ast
    from pathlib import Path

    src = (
        Path(__file__).resolve().parent.parent / "src/spectra_sherpa/app/api/v1/routes/workflows/execute.py"
    ).read_text()
    tree = ast.parse(src)
    wrappers = [n for n in ast.walk(tree) if isinstance(n, ast.AsyncFunctionDef) and n.name == "persist_execution_run"]
    assert len(wrappers) == 1
    forwarded = wrappers[0].body[-1]
    assert isinstance(forwarded, ast.Return) and isinstance(forwarded.value, ast.Await)
    assert ast.unparse(forwarded.value.value) == "_auto_persist_run(*args, **kwargs)"
    handlers = [
        n
        for n in ast.walk(tree)
        if isinstance(n, ast.ExceptHandler) and n.type is not None and ast.unparse(n.type) == "asyncio.TimeoutError"
    ]
    assert len(handlers) == 1
    handler = handlers[0]
    calls = [
        n.value
        for n in ast.walk(handler)
        if isinstance(n, ast.Await)
        and isinstance(n.value, ast.Call)
        and isinstance(n.value.func, ast.Name)
        and n.value.func.id == "persist_execution_run"
    ]
    assert len(calls) == 1
    keywords = {kw.arg: ast.unparse(kw.value) for kw in calls[0].keywords}
    assert keywords["final_status"] == "'cancelled'"
    assert keywords["idempotency_key"] == "normalized_idempotency_key"
    assert keywords["reservation_id"] == "reservation_id"
    terminal = handler.body[-1]
    assert isinstance(terminal, ast.Raise) and isinstance(terminal.exc, ast.Call)
    assert ast.unparse(terminal.exc.func) == "HTTPException"
    assert {kw.arg: ast.literal_eval(kw.value) for kw in terminal.exc.keywords if kw.arg == "status_code"} == {
        "status_code": 504
    }
    assert calls[0].lineno < terminal.lineno


# Silence unused-import lint for the mock helper still referenced if
# someone wants to extend with a full route-level test later.
_ = asyncio, patch
