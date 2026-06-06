"""Coverage for the M5 Idempotency-Key support on POST /workflows/{id}/execute.

The route accepts an optional ``Idempotency-Key`` header; a retried POST
with the same key replays the persisted ExecutionRun row's response
instead of running the workflow again.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from spectra_sherpa.app.api.v1.routes.workflows._helpers import (
    IDEMPOTENCY_REPLAY_WINDOW_SEC,
    _auto_persist_run,
    _compact_diagnostics_for_run_history,
    _compact_results_for_run_history,
    contains_run_history_truncation,
    find_any_idempotent_run,
    find_idempotent_run,
    validate_idempotency_key,
)
from spectra_sherpa.app.models.execution_run import ExecutionRun
from spectra_sherpa.app.models.user import User

# ---------------------------------------------------------------------------
# validate_idempotency_key
# ---------------------------------------------------------------------------


def test_validate_idempotency_key_returns_none_for_no_header():
    assert validate_idempotency_key(None) is None


def test_validate_idempotency_key_treats_blank_as_absent():
    assert validate_idempotency_key("   ") is None


def test_validate_idempotency_key_strips_surrounding_whitespace():
    assert validate_idempotency_key("  ABCDEFGH  ") == "ABCDEFGH"


@pytest.mark.parametrize(
    "raw",
    [
        "abc",  # too short
        "x" * 65,  # too long
        "has space",  # invalid char
        "weird/key",  # invalid char
        "tab\tchar",  # invalid char
    ],
)
def test_validate_idempotency_key_rejects_malformed(raw: str):
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc:
        validate_idempotency_key(raw)
    assert exc.value.status_code == 400


@pytest.mark.parametrize(
    "raw",
    [
        "ABCDEFGH",  # 8-char min
        "x" * 64,  # 64-char max
        "abc-def_GHI-123",  # mixed allowed chars
        "550e8400-e29b-41d4-a716-446655440000",  # UUID-ish
    ],
)
def test_validate_idempotency_key_accepts_well_formed(raw: str):
    assert validate_idempotency_key(raw) == raw.strip()


def test_compact_results_for_run_history_trims_large_sherpa_dataset():
    result = {
        "data_1": {
            "default": {
                "type": "SherpaDataset",
                "shape": [40, 300],
                "n_samples": 40,
                "n_features": 300,
                "data": [[float(row * 300 + col) for col in range(300)] for row in range(40)],
                "x_axis": {"data": [float(col) for col in range(300)], "title": "Wavenumber"},
                "y_axis": {"labels": [f"sample_{row:03d}" for row in range(40)]},
                "metadata": {"wavenumbers": [float(col) for col in range(300)]},
            }
        }
    }

    compacted = _compact_results_for_run_history(result)
    dataset = compacted["data_1"]["default"]

    assert dataset["n_samples"] == 40
    assert dataset["n_features"] == 300
    assert dataset["data_truncated"] is True
    assert len(dataset["data"]) == 20
    assert len(dataset["data"][0]) == 128
    assert len(dataset["x_axis"]["data"]) == 128
    assert dataset["x_axis"]["data_original_length"] == 300
    assert dataset["metadata"]["wavenumbers"]["_truncated_sequence"] is True
    assert len(json.dumps(compacted)) < len(json.dumps(result)) / 4


def test_compact_results_for_run_history_preserves_visualization_payloads():
    result = {
        "viz_1": {
            "visualization": {
                "plot_type": "spectra",
                "data": [{"x": list(range(300)), "y": [float(i) for i in range(300)]}],
            }
        }
    }

    compacted = _compact_results_for_run_history(result)

    assert compacted["viz_1"]["visualization"]["data"][0]["x"] == list(range(300))
    assert compacted["viz_1"]["visualization"]["data"][0]["y"][-1] == 299.0


def test_compact_diagnostics_for_run_history_summarizes_large_arrays():
    diagnostics = {"model_1": {"ground_truth": {"spectra": [[float(i) for i in range(5401)] for _ in range(3)]}}}

    compacted = _compact_diagnostics_for_run_history(diagnostics)
    first_spectrum = compacted["model_1"]["ground_truth"]["spectra"][0]

    assert first_spectrum["_truncated_sequence"] is True
    assert first_spectrum["length"] == 5401
    assert len(first_spectrum["preview"]) == 32


def test_contains_run_history_truncation_detects_compacted_payloads():
    assert contains_run_history_truncation({"data_1": {"default": {"persisted_summary": True}}}) is True
    assert contains_run_history_truncation({"data_1": {"default": {"y_axis": {"labels_truncated": True}}}}) is True
    assert contains_run_history_truncation({"model_1": {"ground_truth": {"spectra": [{"length": 5401}]}}}) is False
    assert (
        contains_run_history_truncation({"model_1": {"ground_truth": {"spectra": [{"_truncated_sequence": True}]}}})
        is True
    )


# ---------------------------------------------------------------------------
# _auto_persist_run persists the key on the row
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_auto_persist_run_stores_idempotency_key(test_session, test_user: User):
    from spectra_sherpa.app.models.project import Project
    from spectra_sherpa.app.models.workflow import Workflow

    project = Project(user_id=test_user.id, name="idem project")
    test_session.add(project)
    await test_session.flush()
    workflow = Workflow(user_id=test_user.id, project_id=project.id, name="idem wf")
    test_session.add(workflow)
    await test_session.commit()

    run_id = await _auto_persist_run(
        test_session,
        workflow_id=workflow.id,
        user_id=test_user.id,
        project_id=project.id,
        wf_version_id=None,
        serialized_results={"node1": {"score": 0.9}},
        diagnostics_serialized={},
        node_statuses={"node1": "completed"},
        final_status="completed",
        error_msg=None,
        integrity_hash="abc",
        model_ids=[],
        params_snapshot={},
        idempotency_key="key-with-token-42",
    )
    assert run_id is not None
    row = (await test_session.execute(select(ExecutionRun).where(ExecutionRun.id == run_id))).scalar_one()
    assert row.idempotency_key == "key-with-token-42"


# ---------------------------------------------------------------------------
# find_idempotent_run lookup semantics
# ---------------------------------------------------------------------------


async def _make_run(
    test_session,
    *,
    user_id: int,
    workflow_id: int,
    project_id: int | None,
    key: str,
    executed_at: datetime,
    status: str = "completed",
    results_summary: dict | None = None,
    diagnostics: dict | None = None,
) -> ExecutionRun:
    row = ExecutionRun(
        project_id=project_id,
        workflow_id=workflow_id,
        user_id=user_id,
        name="r",
        status=status,
        params_snapshot={},
        results_summary=results_summary or {},
        diagnostics=diagnostics or {},
        node_statuses={},
        executed_at=executed_at,
        run_kind="data",
        idempotency_key=key,
    )
    test_session.add(row)
    await test_session.commit()
    await test_session.refresh(row)
    return row


@pytest.mark.asyncio
async def test_find_idempotent_run_matches_recent_row(test_session, test_user: User):
    from spectra_sherpa.app.models.project import Project
    from spectra_sherpa.app.models.workflow import Workflow

    project = Project(user_id=test_user.id, name="p")
    test_session.add(project)
    await test_session.flush()
    workflow = Workflow(user_id=test_user.id, project_id=project.id, name="w")
    test_session.add(workflow)
    await test_session.commit()

    row = await _make_run(
        test_session,
        user_id=test_user.id,
        workflow_id=workflow.id,
        project_id=project.id,
        key="MATCHkey1",
        executed_at=datetime.now(UTC),
    )
    found = await find_idempotent_run(
        test_session,
        user_id=test_user.id,
        workflow_id=workflow.id,
        idempotency_key="MATCHkey1",
    )
    assert found is not None
    assert found.id == row.id


@pytest.mark.asyncio
async def test_find_idempotent_run_skips_rows_outside_replay_window(test_session, test_user: User):
    from spectra_sherpa.app.models.project import Project
    from spectra_sherpa.app.models.workflow import Workflow

    project = Project(user_id=test_user.id, name="p")
    test_session.add(project)
    await test_session.flush()
    workflow = Workflow(user_id=test_user.id, project_id=project.id, name="w")
    test_session.add(workflow)
    await test_session.commit()

    too_old = datetime.utcnow() - timedelta(seconds=IDEMPOTENCY_REPLAY_WINDOW_SEC + 60)
    await _make_run(
        test_session,
        user_id=test_user.id,
        workflow_id=workflow.id,
        project_id=project.id,
        key="STALEkey1",
        executed_at=too_old,
    )
    assert (
        await find_idempotent_run(
            test_session,
            user_id=test_user.id,
            workflow_id=workflow.id,
            idempotency_key="STALEkey1",
        )
        is None
    )

    expired = await find_any_idempotent_run(
        test_session,
        user_id=test_user.id,
        workflow_id=workflow.id,
        idempotency_key="STALEkey1",
    )
    assert expired is not None
    assert expired.id is not None


@pytest.mark.asyncio
async def test_find_idempotent_run_is_scoped_to_user_and_workflow(test_session, test_user: User):
    from spectra_sherpa.app.models.project import Project
    from spectra_sherpa.app.models.workflow import Workflow

    project = Project(user_id=test_user.id, name="p")
    test_session.add(project)
    await test_session.flush()
    wf1 = Workflow(user_id=test_user.id, project_id=project.id, name="wf1")
    wf2 = Workflow(user_id=test_user.id, project_id=project.id, name="wf2")
    test_session.add_all([wf1, wf2])
    await test_session.commit()

    await _make_run(
        test_session,
        user_id=test_user.id,
        workflow_id=wf1.id,
        project_id=project.id,
        key="SHAREDkey",
        executed_at=datetime.utcnow(),
    )

    # Same key on a DIFFERENT workflow must not match.
    assert (
        await find_idempotent_run(
            test_session,
            user_id=test_user.id,
            workflow_id=wf2.id,
            idempotency_key="SHAREDkey",
        )
        is None
    )


# ---------------------------------------------------------------------------
# End-to-end via the auth client
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_execute_replays_response_on_duplicate_idempotency_key(auth_client, test_session, test_user: User):
    """A retried POST with the same Idempotency-Key returns the original
    response (same run_id, same status, same executed_at) instead of
    creating a second run row."""
    from spectra_sherpa.app.models.project import Project
    from spectra_sherpa.app.models.workflow import Workflow

    project = Project(user_id=test_user.id, name="replay p")
    test_session.add(project)
    await test_session.flush()
    workflow = Workflow(user_id=test_user.id, project_id=project.id, name="replay wf")
    test_session.add(workflow)
    await test_session.commit()

    headers = {"Idempotency-Key": "replaykey1234"}

    first = await auth_client.post(f"/api/v1/workflows/{workflow.id}/execute", json={}, headers=headers)
    assert first.status_code == 200
    first_body = first.json()

    second = await auth_client.post(f"/api/v1/workflows/{workflow.id}/execute", json={}, headers=headers)
    assert second.status_code == 200
    second_body = second.json()

    # The canonical "this was a replay" invariants: same run_id, same
    # status, no duplicate row. ``executed_at`` is metadata that may
    # legitimately differ between the live response (set at response
    # build time) and the replay (read from the persisted row).
    assert first_body["run_id"] == second_body["run_id"]
    assert first_body["status"] == second_body["status"]

    # Exactly one row should exist for this workflow + key.
    rows = (
        (
            await test_session.execute(
                select(ExecutionRun).where(
                    ExecutionRun.workflow_id == workflow.id,
                    ExecutionRun.idempotency_key == "replaykey1234",
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(rows) == 1


@pytest.mark.asyncio
async def test_execute_replay_marks_compacted_run_history_payload(auth_client, test_session, test_user: User):
    from spectra_sherpa.app.models.project import Project
    from spectra_sherpa.app.models.workflow import Workflow

    project = Project(user_id=test_user.id, name="truncated replay p")
    test_session.add(project)
    await test_session.flush()
    workflow = Workflow(user_id=test_user.id, project_id=project.id, name="truncated replay wf")
    test_session.add(workflow)
    await test_session.commit()

    await _make_run(
        test_session,
        user_id=test_user.id,
        workflow_id=workflow.id,
        project_id=project.id,
        key="truncatedkey123",
        executed_at=datetime.utcnow(),
        results_summary={"data_1": {"default": {"type": "SherpaDataset", "persisted_summary": True}}},
        diagnostics={"model_1": {"ground_truth": {"spectra": [{"_truncated_sequence": True, "length": 5401}]}}},
    )

    response = await auth_client.post(
        f"/api/v1/workflows/{workflow.id}/execute",
        json={},
        headers={"Idempotency-Key": "truncatedkey123"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["results_truncated"] is True
    assert body["diagnostics_truncated"] is True


@pytest.mark.asyncio
async def test_execute_rejects_malformed_idempotency_key(auth_client, test_session, test_user: User):
    from spectra_sherpa.app.models.project import Project
    from spectra_sherpa.app.models.workflow import Workflow

    project = Project(user_id=test_user.id, name="bad p")
    test_session.add(project)
    await test_session.flush()
    workflow = Workflow(user_id=test_user.id, project_id=project.id, name="bad wf")
    test_session.add(workflow)
    await test_session.commit()

    resp = await auth_client.post(
        f"/api/v1/workflows/{workflow.id}/execute",
        json={},
        headers={"Idempotency-Key": "short"},
    )
    assert resp.status_code == 400
    assert "Idempotency-Key" in resp.json()["detail"]
