"""REM-2 + REM-5 coverage for the atomic-fingerprint idempotency rework.

REM-2 — atomic single-flight reservation
  * unique partial index rejects a duplicate-key reservation
  * the route claims the key BEFORE executing; the loser of the race
    finds the winner's row and either replays it (if terminal) or 409s
    (if still running)

REM-5 — workflow integrity_hash mismatch
  * a retried POST with the same Idempotency-Key but a different
    workflow integrity_hash returns 409, NOT a stale replay
"""

from __future__ import annotations

from datetime import datetime

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from spectra_sherpa.app.api.v1.routes.workflows._helpers import (
    TERMINAL_RUN_STATUSES,
    _reserve_run,
)
from spectra_sherpa.app.models.execution_run import ExecutionRun
from spectra_sherpa.app.models.user import User

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _make_workflow(test_session, test_user: User, *, name: str = "wf"):
    from spectra_sherpa.app.models.project import Project
    from spectra_sherpa.app.models.workflow import Workflow

    project = Project(user_id=test_user.id, name=f"{name}-proj")
    test_session.add(project)
    await test_session.flush()
    workflow = Workflow(user_id=test_user.id, project_id=project.id, name=name)
    test_session.add(workflow)
    await test_session.commit()
    return project, workflow


# ---------------------------------------------------------------------------
# REM-2 — terminal status constant invariants
# ---------------------------------------------------------------------------


def test_terminal_run_statuses_excludes_lifecycle_values():
    """Reservation rows in 'pending' / 'running' must NOT be treated as
    replay-eligible — that would let a follower see a half-finished run
    as 'completed'."""
    assert "pending" not in TERMINAL_RUN_STATUSES
    assert "running" not in TERMINAL_RUN_STATUSES
    assert {"completed", "partial", "error", "failed", "cancelled"} <= TERMINAL_RUN_STATUSES


# ---------------------------------------------------------------------------
# REM-2 — _reserve_run + unique partial index
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_reserve_run_inserts_running_row_visible_to_lookup(test_session, test_user: User):
    project, workflow = await _make_workflow(test_session, test_user, name="reserve-1")

    row = await _reserve_run(
        test_session,
        workflow_id=workflow.id,
        user_id=test_user.id,
        project_id=project.id,
        wf_version_id=None,
        integrity_hash="hash-abc",
        idempotency_key="reservekey1234",
        params_snapshot={},
    )
    assert row is not None
    assert row.status == "running"
    assert row.integrity_hash == "hash-abc"
    assert row.idempotency_key == "reservekey1234"

    # The reservation is committed and visible to a subsequent SELECT.
    fetched = (await test_session.execute(select(ExecutionRun).where(ExecutionRun.id == row.id))).scalar_one()
    assert fetched.status == "running"


@pytest.mark.asyncio
async def test_reserve_run_raises_integrity_error_on_duplicate_key(test_session, test_user: User):
    """A second reservation with the same (user, workflow, key) must fail."""
    project, workflow = await _make_workflow(test_session, test_user, name="reserve-dup")

    first = await _reserve_run(
        test_session,
        workflow_id=workflow.id,
        user_id=test_user.id,
        project_id=project.id,
        wf_version_id=None,
        integrity_hash="hash-1",
        idempotency_key="DUPLICATEkey",
        params_snapshot={},
    )
    assert first is not None

    with pytest.raises(IntegrityError):
        await _reserve_run(
            test_session,
            workflow_id=workflow.id,
            user_id=test_user.id,
            project_id=project.id,
            wf_version_id=None,
            integrity_hash="hash-2",
            idempotency_key="DUPLICATEkey",
            params_snapshot={},
        )


@pytest.mark.asyncio
async def test_partial_index_allows_many_null_idempotency_keys(test_session, test_user: User):
    """Non-idempotent callers (no key) must remain unaffected — many rows
    with NULL idempotency_key can coexist."""
    project, workflow = await _make_workflow(test_session, test_user, name="null-keys")

    for i in range(3):
        row = ExecutionRun(
            project_id=project.id,
            workflow_id=workflow.id,
            user_id=test_user.id,
            name=f"null-{i}",
            status="completed",
            params_snapshot={},
            results_summary={},
            executed_at=datetime.utcnow(),
            run_kind="data",
            idempotency_key=None,
        )
        test_session.add(row)
        await test_session.commit()

    rows = (
        (
            await test_session.execute(
                select(ExecutionRun).where(
                    ExecutionRun.workflow_id == workflow.id,
                    ExecutionRun.idempotency_key.is_(None),
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(rows) == 3


# ---------------------------------------------------------------------------
# REM-2 — end-to-end: serial race (winner finishes, loser replays)
# ---------------------------------------------------------------------------
#
# True concurrent POSTs against ``auth_client`` would share the test's
# single AsyncSession and hit ``IllegalStateChangeError`` — a test-harness
# artifact, not a product invariant. The atomic-race contract is already
# proven by:
#   * ``test_reserve_run_raises_integrity_error_on_duplicate_key`` — the
#     unique partial index rejects a duplicate-key reservation
#   * ``test_in_flight_reservation_returns_409_not_replay`` — the route
#     returns 409 for an in-flight reservation
# What's left is the post-race replay case: WINNER finishes, then LOSER
# (or any later retry) replays the now-terminal row. That's a serial
# scenario and is what this test covers end-to-end.


@pytest.mark.asyncio
async def test_terminal_run_with_same_key_replays_on_retry(auth_client, test_session, test_user: User):
    _, workflow = await _make_workflow(test_session, test_user, name="serial-race")

    headers = {"Idempotency-Key": "SERIALrace1"}

    # First POST runs end-to-end and persists a terminal row.
    first = await auth_client.post(f"/api/v1/workflows/{workflow.id}/execute", json={}, headers=headers)
    assert first.status_code == 200
    first_body = first.json()

    # Retry with the same key — must replay (not re-execute, not insert a
    # second row).
    second = await auth_client.post(f"/api/v1/workflows/{workflow.id}/execute", json={}, headers=headers)
    assert second.status_code == 200
    assert second.json()["run_id"] == first_body["run_id"]

    rows = (
        (
            await test_session.execute(
                select(ExecutionRun).where(
                    ExecutionRun.workflow_id == workflow.id,
                    ExecutionRun.idempotency_key == "SERIALrace1",
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(rows) == 1


# ---------------------------------------------------------------------------
# REM-2 — in-flight reservation responds 409 (not replay)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_in_flight_reservation_returns_409_not_replay(auth_client, test_session, test_user: User):
    """A running reservation row must NOT be replayed (it has no results).
    The route must return 409 with a code that lets the client poll."""
    _, workflow = await _make_workflow(test_session, test_user, name="inflight")

    # Plant a reservation row in 'running' state directly.
    res = await _reserve_run(
        test_session,
        workflow_id=workflow.id,
        user_id=test_user.id,
        project_id=workflow.project_id,
        wf_version_id=None,
        integrity_hash=workflow.integrity_hash,
        idempotency_key="INFLIGHTkey",
        params_snapshot={},
    )
    assert res is not None

    resp = await auth_client.post(
        f"/api/v1/workflows/{workflow.id}/execute",
        json={},
        headers={"Idempotency-Key": "INFLIGHTkey"},
    )
    assert resp.status_code == 409
    body = resp.json()
    assert body["detail"]["code"] == "idempotency_in_progress"
    assert body["detail"]["run_id"] == res.id


# ---------------------------------------------------------------------------
# REM-5 — integrity_hash mismatch returns 409
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_idempotency_key_with_mismatched_workflow_hash_returns_409(auth_client, test_session, test_user: User):
    """A row exists for (user, workflow, key) but its integrity_hash differs
    from the current workflow's hash — the user reused the key after
    mutating the workflow. The route must NOT replay stale results; it
    returns 409 with a distinct code."""
    _, workflow = await _make_workflow(test_session, test_user, name="hash-mismatch")

    # Plant a TERMINAL row whose integrity_hash differs from the workflow's.
    planted = ExecutionRun(
        project_id=workflow.project_id,
        workflow_id=workflow.id,
        user_id=test_user.id,
        name="__latest__",
        status="completed",
        params_snapshot={},
        results_summary={"node_a": {"r2": 0.9}},
        diagnostics={},
        node_statuses={"node_a": "completed"},
        executed_at=datetime.utcnow(),
        run_kind="data",
        integrity_hash="STALE-hash-from-prior-graph",
        idempotency_key="HASHkey5678",
        source_type="auto",
    )
    test_session.add(planted)
    await test_session.commit()

    # The current workflow's integrity_hash is NOT 'STALE-hash-...' (it's
    # whatever the model defaulted to / None for an unmodified row). The
    # mismatch must trigger 409.
    resp = await auth_client.post(
        f"/api/v1/workflows/{workflow.id}/execute",
        json={},
        headers={"Idempotency-Key": "HASHkey5678"},
    )
    assert resp.status_code == 409
    body = resp.json()
    assert body["detail"]["code"] == "idempotency_workflow_changed"
    assert body["detail"]["run_id"] == planted.id
