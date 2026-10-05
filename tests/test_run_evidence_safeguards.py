"""Real foreign-key and lifecycle tests for retained run evidence."""

from datetime import datetime, timezone

import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import delete, text
from sqlalchemy.exc import IntegrityError

from spectra_sherpa.app.models.background_job import BackgroundJob
from spectra_sherpa.app.models.execution_run import ExecutionRun
from spectra_sherpa.app.models.model_artifact import ModelArtifact
from spectra_sherpa.app.models.project import Project
from spectra_sherpa.app.models.workflow import Workflow
from spectra_sherpa.app.models.workflow_version import WorkflowVersion
from spectra_sherpa.app.schemas.run_evidence import OutputEvidence, RunEvidence
from spectra_sherpa.app.services.run_provenance import (
    has_retained_source,
    provenance_cleanup,
    require_unretained_source,
)
from spectra_sherpa.app.services.run_reconciliation import reconcile_job_runs


async def seed(session, user):
    parent = Project(user_id=user.id, name="Parent")
    session.add(parent)
    await session.flush()
    project = Project(user_id=user.id, name="Analysis", parent_id=parent.id)
    session.add(project)
    await session.flush()
    workflow = Workflow(user_id=user.id, project_id=project.id, name="PCA")
    session.add(workflow)
    await session.flush()
    version = WorkflowVersion(workflow_id=workflow.id, created_by=user.id, version_number=1, snapshot={})
    session.add(version)
    await session.flush()
    run = ExecutionRun(
        project_id=project.id,
        workflow_id=workflow.id,
        workflow_version_id=version.id,
        user_id=user.id,
        name="Retained",
        status="completed",
        run_kind="training",
        params_snapshot={},
        results_summary={},
        executed_at=datetime.now(timezone.utc),
    )
    session.add(run)
    await session.flush()
    model = ModelArtifact(
        artifact_uid="retained",
        user_id=user.id,
        project_id=project.id,
        workflow_id=workflow.id,
        workflow_version_id=version.id,
        source_run_id=run.id,
        node_id="pca",
        model_type="pca",
        name="Retained PCA",
        artifact_dir="unused",
        integrity_hash="a" * 64,
        n_features=3,
    )
    session.add(model)
    await session.commit()
    return parent, project, workflow, version, run, model


def test_evidence_gaps_name_output_scope_and_recovery() -> None:
    evidence = RunEvidence(
        qualification="qualified",
        reason=None,
        outputs={
            "export": {
                "artifact": OutputEvidence(
                    state="missing",
                    reason="Output exceeds the retained materialization budget",
                    role="prepared CSV",
                )
            },
            "pca": {
                "runtime": OutputEvidence(
                    state="missing",
                    reason="Not retained: private runtime output excluded by policy.",
                ),
                "scores": OutputEvidence(
                    state="reduced",
                    reason="Large value retained as a bounded preview.",
                    role="scores",
                ),
            },
        },
    )

    gaps = {(gap.node_id, gap.output): gap for gap in evidence.gaps()}
    assert gaps[("export", "artifact")].category == "storage_limit"
    assert "capacity" in gaps[("export", "artifact")].recovery
    assert gaps[("pca", "runtime")].category == "session_only"
    assert gaps[("pca", "scores")].category == "reduced"


def test_unverified_legacy_evidence_has_workflow_recovery() -> None:
    gap = RunEvidence().gaps()[0]

    assert gap.node_id == "__workflow__"
    assert gap.category == "unverified"
    assert "Rerun" in gap.recovery


@pytest.mark.asyncio
@pytest.mark.parametrize("scope", ["run", "workflow", "project", "ancestor"])
async def test_cleanup_preflight_explains_retained_source(test_session, test_user, scope):
    parent, project, workflow, _, run, _ = await seed(test_session, test_user)
    args = {
        "run": {"run_id": run.id},
        "workflow": {"workflow_id": workflow.id},
        "project": {"project_id": project.id},
        "ancestor": {"project_id": parent.id},
    }[scope]
    with pytest.raises(HTTPException, match="retained model") as error:
        await require_unretained_source(test_session, **args)
    assert error.value.status_code == 409


@pytest.mark.asyncio
@pytest.mark.parametrize("source", [ExecutionRun, WorkflowVersion, Workflow, Project])
async def test_database_rejects_cleanup_even_without_preflight(test_session, test_user, source):
    parent, _, workflow, version, run, _ = await seed(test_session, test_user)
    ids = {ExecutionRun: run.id, WorkflowVersion: version.id, Workflow: workflow.id, Project: parent.id}
    await test_session.execute(text("PRAGMA foreign_keys=ON"))
    assert (await test_session.execute(text("PRAGMA foreign_keys"))).scalar() == 1
    try:
        with pytest.raises(HTTPException) as error:
            async with provenance_cleanup(test_session):
                await test_session.execute(delete(source).where(source.id == ids[source]))
                await test_session.commit()
        assert error.value.status_code == 409
        retained = await test_session.get(ModelArtifact, 1)
        assert retained.source_run_id == ids[ExecutionRun]
        assert retained.workflow_version_id == ids[WorkflowVersion]
    finally:
        await test_session.rollback()
        await test_session.execute(text("PRAGMA foreign_keys=OFF"))


@pytest.mark.asyncio
async def test_delete_wins_then_model_insert_cannot_succeed(test_session, test_user):
    _, _, _, _, run, model = await seed(test_session, test_user)
    run_id = run.id
    await test_session.delete(model)
    await test_session.commit()
    await test_session.execute(text("PRAGMA foreign_keys=ON"))
    try:
        await test_session.execute(delete(ExecutionRun).where(ExecutionRun.id == run_id))
        await test_session.commit()
        orphan = ModelArtifact(
            artifact_uid="late",
            user_id=test_user.id,
            source_run_id=run_id,
            node_id="pca",
            model_type="pca",
            name="Late",
            artifact_dir="unused",
            integrity_hash="a" * 64,
            n_features=3,
        )
        test_session.add(orphan)
        with pytest.raises(IntegrityError):
            await test_session.commit()
    finally:
        await test_session.rollback()
        await test_session.execute(text("PRAGMA foreign_keys=OFF"))


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "job_status,expected", [("failed", "failed"), ("cancelled", "cancelled"), ("completed", "failed")]
)
async def test_terminal_job_reconciles_only_unfinished_run(test_session, test_user, job_status, expected):
    _, _, _, _, run, _ = await seed(test_session, test_user)
    job = BackgroundJob(user_id=test_user.id, job_type="batch_predict", status=job_status, execution_run_id=run.id)
    test_session.add(job)
    await test_session.commit()
    await reconcile_job_runs(test_session, job_id=job.id)
    await test_session.refresh(run)
    assert run.status == "completed"
    run.status = "running"
    await test_session.commit()
    await reconcile_job_runs(test_session, job_id=job.id)
    await test_session.refresh(run)
    assert run.status == expected
    assert "Background job" in run.error


def test_completeness_never_follows_a_name_or_status():
    assert RunEvidence().qualification == "unverified"
    with pytest.raises(ValidationError):
        RunEvidence(qualification="qualified")
    for state in ("missing", "reduced", "unverified"):
        with pytest.raises(ValidationError):
            OutputEvidence(state=state)
    evidence = RunEvidence(
        outputs={
            "pca": {
                "scores": OutputEvidence(state="exact", role="scores"),
                "loadings": OutputEvidence(state="missing", reason="Legacy summary retained no loadings."),
            }
        }
    )
    assert evidence.outputs["pca"]["scores"].state == "exact"
    assert evidence.outputs["pca"]["loadings"].state == "missing"


@pytest.mark.asyncio
@pytest.mark.parametrize("route", ["run", "legacy_run", "workflow", "project"])
async def test_cleanup_routes_return_conflict(test_session, test_user, route):
    from spectra_sherpa.app.api.v1.routes.execution_runs import delete_run
    from spectra_sherpa.app.api.v1.routes.projects import delete_project
    from spectra_sherpa.app.api.v1.routes.runs import delete_project_run
    from spectra_sherpa.app.api.v1.routes.workflows.crud import delete_workflow

    _, project, workflow, _, run, _ = await seed(test_session, test_user)
    calls = {
        "run": lambda: delete_project_run(run.id, project.id, test_session, test_user),
        "legacy_run": lambda: delete_run(workflow.id, run.id, test_session, test_user),
        "workflow": lambda: delete_workflow(workflow.id, test_session, test_user),
        "project": lambda: delete_project(project.id, test_session, test_user),
    }
    with pytest.raises(HTTPException) as error:
        await calls[route]()
    assert error.value.status_code == 409


@pytest.mark.asyncio
async def test_archived_project_permanent_removal_preserves_retained_model_evidence(
    auth_client, test_session, test_user
):
    parent, child, workflow, version, run, model = await seed(test_session, test_user)
    parent_id, child_id, workflow_id = parent.id, child.id, workflow.id
    version_id, run_id, model_id = version.id, run.id, model.id

    assert (await auth_client.post(f"/api/v1/projects/{parent_id}/archive")).status_code == 200
    removed = await auth_client.delete(f"/api/v1/projects/{parent_id}", params={"confirm_name": "Parent"})
    assert removed.status_code == 204
    assert (await auth_client.get("/api/v1/projects")).json() == []
    assert (await auth_client.get("/api/v1/projects?archived=true")).json() == []
    for project_id in (parent_id, child_id):
        retained_project = await test_session.get(Project, project_id)
        await test_session.refresh(retained_project)
        assert retained_project.deleted_at is not None
        assert (await auth_client.get(f"/api/v1/projects/{project_id}")).status_code == 404
        assert (await auth_client.post(f"/api/v1/projects/{project_id}/restore")).status_code == 404
        assert (await auth_client.put(f"/api/v1/projects/{project_id}", json={"name": "Reused"})).status_code == 404

    assert await test_session.get(Workflow, workflow_id) is not None
    assert await test_session.get(WorkflowVersion, version_id) is not None
    assert await test_session.get(ExecutionRun, run_id) is not None
    assert await test_session.get(ModelArtifact, model_id) is not None


@pytest.mark.asyncio
async def test_tombstoned_project_contents_leave_user_listings(auth_client, test_session, test_user):
    """A confirmed permanent deletion must also hide the tree's contents.

    The tombstone branch keeps experiments and workflows so retained model
    evidence stays intact, but the user-scoped listings are not project
    scoped, so without a live-project filter everything inside a
    "permanently deleted" project stays visible and editable.
    """
    from spectra_sherpa.app.models.experiment import Experiment

    parent, project, workflow, _, _, _ = await seed(test_session, test_user)
    parent_id, workflow_id = parent.id, workflow.id
    test_session.add(Experiment(user_id=test_user.id, project_id=project.id, name="Filed", metadata_path="unused"))
    test_session.add(Experiment(user_id=test_user.id, name="Unfiled", metadata_path="unused"))
    await test_session.commit()

    listed = (await auth_client.get("/api/v1/workflows")).json()
    assert any(item["id"] == workflow_id for item in listed)

    assert (await auth_client.post(f"/api/v1/projects/{parent_id}/archive")).status_code == 200
    removed = await auth_client.delete(f"/api/v1/projects/{parent_id}", params={"confirm_name": "Parent"})
    assert removed.status_code == 204

    listed = (await auth_client.get("/api/v1/workflows")).json()
    assert [item for item in listed if item["id"] == workflow_id] == []
    names = {item["name"] for item in (await auth_client.get("/api/v1/experiments")).json()}
    assert "Filed" not in names
    # An unfiled experiment has no project and must survive the filter.
    assert "Unfiled" in names

    # The evidence itself is retained, exactly as the tombstone intends.
    assert await test_session.get(Workflow, workflow_id) is not None


@pytest.mark.asyncio
async def test_project_retention_detects_model_link_without_source_run(test_session, test_user):
    _, project, _, _, _, model = await seed(test_session, test_user)
    model.source_run_id = None
    model.workflow_id = None
    model.workflow_version_id = None
    await test_session.commit()

    assert await has_retained_source(test_session, project_id=project.id)


@pytest.mark.asyncio
async def test_naming_does_not_rewrite_scientific_evidence(test_session, test_user):
    from spectra_sherpa.app.api.v1.routes.execution_runs import create_run
    from spectra_sherpa.app.schemas.execution_runs import SaveRunRequest

    _, _, workflow, _, run, _ = await seed(test_session, test_user)
    run.source_type = "auto"
    run.status = "partial"
    run.error = "One node failed"
    run.integrity_hash = "a" * 64
    await test_session.commit()
    payload = SaveRunRequest(
        run_id=run.id,
        name="Reviewed",
        status="completed",
        results_summary={},
        executed_at=datetime.now(timezone.utc).isoformat(),
        run_kind="data",
        integrity_hash="b" * 64,
    )
    result = await create_run(workflow.id, payload, test_session, test_user)
    assert result.name == "Reviewed"
    assert result.status == "partial"
    assert result.error == "One node failed"
    assert result.integrity_hash == "a" * 64
    assert result.run_kind == "training"


@pytest.mark.asyncio
@pytest.mark.parametrize("stale", [False, True])
async def test_restart_preserves_live_worker_and_reconciles_stale_one(test_session, test_user, monkeypatch, stale):
    from contextlib import asynccontextmanager
    from datetime import timedelta

    from spectra_sherpa.app.core import startup

    _, _, _, _, run, _ = await seed(test_session, test_user)
    run.status = "running"
    now = datetime.now(timezone.utc)
    heartbeat = now - timedelta(minutes=10) if stale else now
    job = BackgroundJob(
        user_id=test_user.id,
        job_type="batch_predict",
        status="running",
        execution_run_id=run.id,
        last_heartbeat=heartbeat,
    )
    test_session.add(job)
    await test_session.commit()

    @asynccontextmanager
    async def session_factory():
        yield test_session

    monkeypatch.setattr(startup, "async_session", session_factory)
    await startup.reconcile_stale_jobs()
    await test_session.refresh(run)
    await test_session.refresh(job)
    assert run.status == ("failed" if stale else "running")
    assert job.status == ("failed" if stale else "running")


@pytest.mark.asyncio
@pytest.mark.parametrize("work_raises", [False, True])
async def test_finishing_work_cannot_overwrite_cancelled_job(test_session, test_user, monkeypatch, work_raises):
    import asyncio
    from contextlib import asynccontextmanager
    from unittest.mock import AsyncMock

    from spectra_sherpa.app.services import job_manager as module

    manager = module.JobManager()
    job = BackgroundJob(user_id=test_user.id, job_type="test", status="pending")
    test_session.add(job)
    await test_session.commit()

    @asynccontextmanager
    async def session_factory():
        yield test_session

    async def heartbeat(_job_id):
        await asyncio.sleep(60)

    async def work():
        assert await manager.cancel_job(test_session, job.id, user_id=test_user.id)
        if work_raises:
            raise RuntimeError("Late worker failure")

    monkeypatch.setattr(module, "async_session", session_factory)
    monkeypatch.setattr(manager, "_heartbeat_loop", heartbeat)
    monkeypatch.setattr(manager, "_broadcast_job", AsyncMock())
    await manager.run_job(job.id, work)
    await test_session.refresh(job)
    assert job.status == "cancelled"
    assert job.error_message == "Cancelled by user"
