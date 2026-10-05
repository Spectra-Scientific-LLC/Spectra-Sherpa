"""Every run writer inherits capture; reads never invent historical evidence."""

from datetime import datetime, timezone

import pytest

from spectra_sherpa.app.models.execution_run import ExecutionRun
from spectra_sherpa.app.models.project import Project
from spectra_sherpa.app.services import run_environment


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "source,status",
    [("manual", "completed"), ("manual", "error"), ("batch", "completed"), ("folder_watch", "completed")],
)
async def test_capture_survives_reopen_and_api_inspection(test_session, test_user, monkeypatch, source, status):
    from spectra_sherpa.app.api.v1.routes.runs import inspect_run_evidence
    from spectra_sherpa.app.schemas.execution_runs import ExecutionRunOut

    monkeypatch.setattr(run_environment, "version", lambda name: "captured-version")
    project = Project(user_id=test_user.id, name="Environment evidence")
    test_session.add(project)
    await test_session.flush()
    run = ExecutionRun(
        user_id=test_user.id,
        project_id=project.id,
        workflow_id=None,
        name="Recorded run",
        status=status,
        source_type=source,
        params_snapshot={},
        results_summary={},
        executed_at=datetime.now(timezone.utc),
    )
    test_session.add(run)
    await test_session.commit()
    snapshot = run.environment_snapshot
    assert snapshot["packages"]["spectrochempy"] == "captured-version"
    monkeypatch.setattr(run_environment, "version", lambda name: "new-runtime")
    await test_session.refresh(run)
    assert run.environment_snapshot == snapshot
    assert ExecutionRunOut.model_validate(run).environment_snapshot == snapshot
    run_id, project_id = run.id, project.id
    # A new request has no fully loaded run in its identity map.
    test_session.expunge(run)
    response = await inspect_run_evidence(run_id, project_id=project_id, session=test_session, current_user=test_user)
    assert response["environment_snapshot"] == snapshot


@pytest.mark.asyncio
async def test_explicit_historical_null_is_not_backfilled(test_session, test_user):
    run = ExecutionRun(
        user_id=test_user.id,
        workflow_id=None,
        name="Legacy import",
        status="completed",
        params_snapshot={},
        results_summary={},
        environment_snapshot=None,
        executed_at=datetime.now(timezone.utc),
    )
    test_session.add(run)
    await test_session.commit()
    await test_session.refresh(run)
    assert run.environment_snapshot is None


def test_failed_capture_is_explicit_and_never_includes_library_paths(monkeypatch):
    import threadpoolctl

    monkeypatch.setattr(run_environment, "version", lambda name: (_ for _ in ()).throw(RuntimeError("broken metadata")))
    monkeypatch.setattr(
        threadpoolctl,
        "threadpool_info",
        lambda: [{"filepath": "/private/customer/library", "internal_api": "openblas", "version": "test"}],
    )
    snapshot = run_environment.build_run_environment_snapshot()
    assert set(snapshot["packages"].values()) == {"unavailable"}
    assert "filepath" not in snapshot["numerical_libraries"]["libraries"][0]
    monkeypatch.setattr(threadpoolctl, "threadpool_info", lambda: (_ for _ in ()).throw(RuntimeError("unavailable")))
    assert run_environment.build_run_environment_snapshot()["numerical_libraries"]["state"] == "unavailable"
