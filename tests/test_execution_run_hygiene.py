"""Unit coverage for the PR-C run-hygiene changes.

- ``ExecutionRun.status`` CHECK constraint
- ``_auto_persist_run`` dedups model_ids
- ``_auto_persist_run`` persists ``source_metadata`` from the route
- The error-path ``diagnostics["_run_summary"]`` carries serialization-vs-execution
  triage info (asserted via direct call to the route helper).
"""

from __future__ import annotations

from datetime import datetime

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from spectra_sherpa.app.api.v1.routes.workflows._helpers import (
    _auto_persist_run,
    _build_source_metadata,
)
from spectra_sherpa.app.models.execution_run import ExecutionRun
from spectra_sherpa.app.models.user import User

# ---------------------------------------------------------------------------
# M8 — status CHECK constraint
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_execution_run_status_check_rejects_unknown_value(test_session, test_user: User):
    """An ExecutionRun row with a status outside the allowlist must fail at flush."""
    row = ExecutionRun(
        user_id=test_user.id,
        workflow_id=None,
        workflow_version_id=None,
        name="bad",
        status="not_a_real_status",
        params_snapshot={},
        results_summary={},
        executed_at=datetime.utcnow(),
        run_kind="data",
    )
    test_session.add(row)
    with pytest.raises(IntegrityError):
        await test_session.flush()
    await test_session.rollback()


@pytest.mark.parametrize("status", ExecutionRun.VALID_STATUSES)
@pytest.mark.asyncio
async def test_execution_run_status_check_accepts_every_allowlisted_value(test_session, test_user: User, status: str):
    row = ExecutionRun(
        user_id=test_user.id,
        workflow_id=None,
        workflow_version_id=None,
        name=f"ok-{status}",
        status=status,
        params_snapshot={},
        results_summary={},
        executed_at=datetime.utcnow(),
        run_kind="data",
    )
    test_session.add(row)
    await test_session.flush()
    await test_session.rollback()


# ---------------------------------------------------------------------------
# L1 — _auto_persist_run dedups model_ids
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_auto_persist_run_dedups_model_ids(test_session, test_user: User):
    from spectra_sherpa.app.models.project import Project
    from spectra_sherpa.app.models.workflow import Workflow

    project = Project(user_id=test_user.id, name="dedup project")
    test_session.add(project)
    await test_session.flush()
    workflow = Workflow(user_id=test_user.id, project_id=project.id, name="dedup wf")
    test_session.add(workflow)
    await test_session.commit()

    duplicates = ["artifact-a", "artifact-a", "artifact-b", "artifact-a"]
    run_id = await _auto_persist_run(
        test_session,
        workflow_id=workflow.id,
        user_id=test_user.id,
        project_id=project.id,
        wf_version_id=None,
        serialized_results={},
        diagnostics_serialized={},
        node_statuses={},
        final_status="completed",
        error_msg=None,
        integrity_hash=None,
        model_ids=duplicates,
        params_snapshot={},
    )
    assert run_id is not None
    persisted = (await test_session.execute(select(ExecutionRun).where(ExecutionRun.id == run_id))).scalar_one()
    assert persisted.model_ids == ["artifact-a", "artifact-b"]


# ---------------------------------------------------------------------------
# L2 — source_metadata is persisted and structured
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_auto_persist_run_persists_source_metadata(test_session, test_user: User):
    from spectra_sherpa.app.models.project import Project
    from spectra_sherpa.app.models.workflow import Workflow

    project = Project(user_id=test_user.id, name="meta project")
    test_session.add(project)
    await test_session.flush()
    workflow = Workflow(user_id=test_user.id, project_id=project.id, name="meta wf")
    test_session.add(workflow)
    await test_session.commit()

    meta = _build_source_metadata(executor_status="completed", had_serialization_errors=False)
    assert meta["executor_status"] == "completed"
    assert meta["had_serialization_errors"] is False

    run_id = await _auto_persist_run(
        test_session,
        workflow_id=workflow.id,
        user_id=test_user.id,
        project_id=project.id,
        wf_version_id=None,
        serialized_results={},
        diagnostics_serialized={},
        node_statuses={},
        final_status="completed",
        error_msg=None,
        integrity_hash=None,
        model_ids=[],
        params_snapshot={},
        source_metadata=meta,
    )
    persisted = (await test_session.execute(select(ExecutionRun).where(ExecutionRun.id == run_id))).scalar_one()
    assert persisted.source_metadata is not None
    assert persisted.source_metadata.get("executor_status") == "completed"
    assert persisted.source_metadata.get("had_serialization_errors") is False


# ---------------------------------------------------------------------------
# M9 — _build_source_metadata composes the triage payload correctly
# ---------------------------------------------------------------------------


def test_build_source_metadata_records_serialization_vs_execution():
    """The helper must distinguish a serialization failure from an
    execution failure for downstream triage."""
    ser_only = _build_source_metadata(executor_status="completed", had_serialization_errors=True)
    assert ser_only["executor_status"] == "completed"
    assert ser_only["had_serialization_errors"] is True
    assert "exception_class" not in ser_only

    exec_only = _build_source_metadata(
        executor_status="error",
        had_serialization_errors=False,
        exception_class="ValueError",
    )
    assert exec_only["executor_status"] == "error"
    assert exec_only["had_serialization_errors"] is False
    assert exec_only["exception_class"] == "ValueError"
