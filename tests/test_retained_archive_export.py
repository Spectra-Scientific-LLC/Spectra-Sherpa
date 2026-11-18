"""Explicit run selection and positive managed disclosure before archive release."""

from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi import HTTPException, Request

from spectra_sherpa.app.api.v1.routes import projects
from spectra_sherpa.app.contracts import retained_archive_export as admission
from spectra_sherpa.app.models.execution_run import ExecutionRun
from spectra_sherpa.app.models.project import Project
from spectra_sherpa.app.schemas.run_evidence import RunEvidence
from spectra_sherpa.app.services import run_output_retention as retention
from spectra_sherpa.app.services.retained_archive_export import selected_archive_runs
from spectra_sherpa.app.services.retained_archive_results import read_archived_output, read_archived_results


@pytest.fixture
async def saved_run(test_session, test_user, tmp_path, monkeypatch):
    monkeypatch.setattr(retention, "settings", replace(retention.settings, data_dir=tmp_path))
    project = Project(user_id=test_user.id, name="Archive qualification")
    test_session.add(project)
    await test_session.flush()
    evidence = retention.retain_output(
        test_user.id, {"identity": 9007199254740993, "value": 1.25, "units": "mg/L", "role": "held_out"}, role="record"
    )
    run = ExecutionRun(
        user_id=test_user.id,
        project_id=project.id,
        name="Retained run",
        status="completed",
        params_snapshot={},
        results_summary={},
        executed_at=datetime.now(timezone.utc),
        evidence_completeness=RunEvidence(
            qualification="qualified", outputs={"absent": {"record": evidence}}
        ).model_dump(),
    )
    test_session.add(run)
    await test_session.commit()
    return project, run, retention.read_output_bytes(test_user.id, evidence)


async def test_selected_run_and_original_output_export_without_pack_code(test_session, test_user, saved_run):
    project, run, encoded = saved_run
    response = await projects.export_project_sherpa_object(
        project.id, Request({"type": "http"}), session=test_session, current_user=test_user, retained_run_ids=[run.id]
    )
    try:
        payload = Path(response.path).read_bytes()
        index = read_archived_results(payload, max_uncompressed_bytes=1024 * 1024)
        assert [item.source_run_id for item in index.runs] == [run.id]
        assert index.prior_unrecorded_history == "unknown"
        assert (
            read_archived_output(
                payload, run_id=run.id, node_id="absent", port="record", max_uncompressed_bytes=1024 * 1024
            )
            == encoded
        )
    finally:
        await response.background()


@pytest.mark.parametrize("selection", ["unknown", "wrong_owner", "wrong_project", "duplicate", "running"])
async def test_selection_is_complete_owned_and_terminal(test_session, test_user, saved_run, selection):
    project, run, _ = saved_run
    user_id, project_id, ids = test_user.id, project.id, [run.id]
    if selection == "unknown":
        ids.append(run.id + 1000)
    elif selection == "wrong_owner":
        user_id += 1000
    elif selection == "wrong_project":
        project_id += 1000
    elif selection == "duplicate":
        ids *= 2
    else:
        run.status = "running"
        await test_session.commit()
    with pytest.raises(HTTPException) as error:
        await selected_archive_runs(test_session, user_id, project_id, ids)
    assert error.value.status_code in {404, 409, 422}


async def test_managed_export_requires_positive_disclosure_provider(test_session, test_user, saved_run, monkeypatch):
    project, run, _ = saved_run
    runs = await selected_archive_runs(test_session, test_user.id, project.id, [run.id])
    monkeypatch.setattr(admission, "uses_managed_project_access", lambda: True)
    monkeypatch.setattr(admission, "_provider", None)
    with pytest.raises(HTTPException, match="not available"):
        async with admission.retained_archive_export_admission(
            test_session, test_user.id, project.id, runs, Request({"type": "http"})
        ):
            pytest.fail("Unqualified managed result export entered byte collection")


async def test_disclosure_commit_failure_removes_archive_before_response(
    test_session, test_user, saved_run, monkeypatch
):
    project, run, _ = saved_run
    created = []
    original = projects._temporary_archive_path

    def temporary(suffix):
        path = original(suffix)
        created.append(path)
        return path

    monkeypatch.setattr(projects, "_temporary_archive_path", temporary)
    monkeypatch.setattr(admission, "uses_managed_project_access", lambda: True)

    @asynccontextmanager
    async def failed_commit(*args):
        yield
        raise HTTPException(409, "Disclosure could not commit")

    monkeypatch.setattr(admission, "_provider", failed_commit)
    with pytest.raises(HTTPException, match="could not commit"):
        await projects.export_project_sherpa_object(
            project.id,
            Request({"type": "http"}),
            session=test_session,
            current_user=test_user,
            retained_run_ids=[run.id],
        )
    assert created and all(not Path(path).exists() for path in created)


@pytest.mark.parametrize("prefix", ["", "x\x00"])
async def test_oversized_historical_metadata_is_refused_before_orm_decode(
    test_session, test_user, saved_run, monkeypatch, prefix
):
    from sqlalchemy import event

    from spectra_sherpa.app.services import retained_archive_export as export

    project, run, _ = saved_run
    run.notes = prefix + "x" * 2048
    await test_session.commit()
    monkeypatch.setattr(export, "MAX_INDEX_BYTES", 1024)
    decoded = []

    def refreshed(*args):
        decoded.append(True)

    event.listen(ExecutionRun, "refresh", refreshed)
    try:
        with pytest.raises(HTTPException, match="metadata limit"):
            await selected_archive_runs(test_session, test_user.id, project.id, [run.id])
    finally:
        event.remove(ExecutionRun, "refresh", refreshed)
    assert not decoded


async def test_capacity_is_reserved_before_database_selection(test_session, test_user, saved_run, monkeypatch):
    from spectra_sherpa.app.services.retained_archive_inspection import archive_inspection_slot

    project, run, _ = saved_run

    async def forbidden(*args):
        pytest.fail("Run selection happened outside capacity admission")

    monkeypatch.setattr(projects, "selected_archive_runs", forbidden)
    with archive_inspection_slot(), archive_inspection_slot():
        with pytest.raises(HTTPException) as caught:
            await projects.export_project_sherpa_object(
                project.id,
                Request({"type": "http"}),
                session=test_session,
                current_user=test_user,
                retained_run_ids=[run.id],
            )
    assert caught.value.status_code == 503


async def test_cancelled_composite_preparation_drains_nested_reader():
    import asyncio
    import threading

    from spectra_sherpa.app.services.retained_archive_inspection import run_archive_operation_owned

    entered, release, finished = threading.Event(), threading.Event(), threading.Event()

    def read():
        entered.set()
        assert release.wait(5)
        finished.set()

    async def preparation():
        await asyncio.to_thread(read)

    task = asyncio.create_task(run_archive_operation_owned(preparation()))
    try:
        assert await asyncio.to_thread(entered.wait, 5)
        task.cancel()
        await asyncio.sleep(0)
        assert not task.done()
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert finished.is_set()
    finally:
        release.set()
