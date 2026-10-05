"""Exact operational model identity and explicit watch rebind tests."""

from datetime import datetime, timezone

import pytest
from fastapi import HTTPException

from spectra_sherpa.app.api.v1.routes import deploy
from spectra_sherpa.app.models.batch_prediction import BatchPrediction
from spectra_sherpa.app.models.execution_run import ExecutionRun
from spectra_sherpa.app.models.folder_watch import FolderWatch
from spectra_sherpa.app.models.workflow import Workflow
from spectra_sherpa.app.schemas.deploy import FolderWatchUpdate
from spectra_sherpa.app.services import deployment_binding


@pytest.mark.asyncio
async def test_prediction_inspection_uses_persisted_file_addresses(test_session, test_user):
    run = ExecutionRun(
        user_id=test_user.id,
        name="Addressed predictions",
        run_kind="batch_inference",
        status="completed",
        executed_at=datetime.now(timezone.utc),
        params_snapshot={},
        results_summary={},
        source_metadata={"retained_file_nodes": {"/a.csv": ["file_0::model", "unknown"]}},
        node_statuses={"file_0::model": "completed"},
    )
    test_session.add(run)
    await test_session.flush()
    prediction = BatchPrediction(run_id=run.id, file_name="a.csv", file_path="/a.csv", status="completed")
    test_session.add(prediction)
    await test_session.commit()
    listed = await deploy.list_predictions(run.id, session=test_session, current_user=test_user)
    single = await deploy.get_prediction(run.id, prediction.id, session=test_session, current_user=test_user)
    assert listed.predictions[0].retained_node_ids == single.retained_node_ids == ["file_0::model"]
    run.source_metadata = {}
    await test_session.commit()
    legacy = await deploy.get_prediction(run.id, prediction.id, session=test_session, current_user=test_user)
    assert legacy.retained_node_ids == []


@pytest.mark.asyncio
async def test_prediction_history_excludes_non_prediction_runs(test_session, test_user):
    for kind in ("training", "data", "batch_inference"):
        test_session.add(
            ExecutionRun(
                user_id=test_user.id,
                name=kind,
                run_kind=kind,
                status="completed",
                executed_at=datetime.now(timezone.utc),
                params_snapshot={},
                results_summary={},
            )
        )
    await test_session.commit()
    result = await deploy.list_deploy_runs(source_type=None, label=None, session=test_session, current_user=test_user)
    assert [run.name for run in result.runs] == ["batch_inference"]


@pytest.mark.asyncio
async def test_exact_binding_ignores_canvas_and_rejects_revocation(
    test_session,
    test_user,
    deployment_artifact_factory,
    monkeypatch,
):
    workflow = Workflow(user_id=test_user.id, name="Mutable canvas")
    test_session.add(workflow)
    await test_session.flush()
    artifact = await deployment_artifact_factory(workflow)
    await test_session.commit()

    async def resolve(**changes):
        return await deployment_binding.resolve_deployment_binding(
            test_session,
            **{
                "user_id": test_user.id,
                "workflow_id": workflow.id,
                "artifact_uid": artifact.artifact_uid,
                "expected_version_id": artifact.workflow_version_id,
                **changes,
            },
        )

    bound = await resolve()
    assert [node.node_type for node in bound.workflow.nodes] == ["deploy.input", "model.load_apply"]
    assert bound.workflow.nodes[1].parameters == {"model_id": artifact.artifact_uid}
    with pytest.raises(ValueError, match="exact deploy-ready"):
        await resolve(artifact_uid=None)
    with pytest.raises(ValueError, match="unavailable"):
        await resolve(user_id=test_user.id + 100)
    with pytest.raises(ValueError, match="bound workflow version"):
        await resolve(expected_version_id=artifact.workflow_version_id + 100)
    monkeypatch.setattr(
        deployment_binding,
        "verify_model_artifact_storage_record",
        lambda artifact: (_ for _ in ()).throw(ValueError("checksum mismatch")),
    )
    with pytest.raises(ValueError, match="checksum mismatch"):
        await resolve()
    from spectra_sherpa.app.core.config import app_config

    monkeypatch.setattr(app_config, "mode", "enterprise")
    artifact.is_deploy_ready = False
    await test_session.commit()
    with pytest.raises(ValueError, match="not marked deploy-ready"):
        await resolve()


@pytest.mark.asyncio
async def test_legacy_watch_requires_explicit_rebind_before_enabling(
    test_session,
    test_user,
    deployment_artifact_factory,
    monkeypatch,
):
    from spectra_sherpa.app.core.config import app_config

    monkeypatch.setattr(app_config, "mode", "enterprise")
    workflow = Workflow(user_id=test_user.id, name="Watch source")
    test_session.add(workflow)
    await test_session.flush()
    artifact = await deployment_artifact_factory(workflow)
    watch = FolderWatch(
        user_id=test_user.id,
        workflow_id=workflow.id,
        name="Legacy watch",
        folder_path="/tmp/watch",
        is_enabled=False,
        processed_files={"old": "done"},
    )
    test_session.add(watch)
    await test_session.commit()
    with pytest.raises(HTTPException) as exc:
        await deploy.enable_watch(watch.id, session=test_session, current_user=test_user)
    assert exc.value.status_code == 422
    rebound = await deploy.update_watch(
        watch.id, FolderWatchUpdate(artifact_uid=artifact.artifact_uid), session=test_session, current_user=test_user
    )
    assert rebound.workflow_version_id == artifact.workflow_version_id
    assert rebound.processed_files == {}
    assert not rebound.is_enabled
    enabled = await deploy.enable_watch(watch.id, session=test_session, current_user=test_user)
    assert enabled.is_enabled
    with pytest.raises(HTTPException) as exc:
        await deploy.update_watch(
            watch.id, FolderWatchUpdate(artifact_uid="different"), session=test_session, current_user=test_user
        )
    assert exc.value.status_code == 409
    from spectra_sherpa.app.core.config import app_config

    monkeypatch.setattr(app_config, "mode", "enterprise")
    artifact.is_deploy_ready = False
    await test_session.commit()
    with pytest.raises(HTTPException) as exc:
        await deploy.enable_watch(watch.id, session=test_session, current_user=test_user)
    assert exc.value.status_code == 422


@pytest.mark.asyncio
async def test_deploy_collections_are_filtered_by_project(test_session, test_user):
    from spectra_sherpa.app.models.project import Project

    projects = [Project(user_id=test_user.id, name=f"Project {index}") for index in range(2)]
    test_session.add_all(projects)
    await test_session.flush()
    for index, project in enumerate(projects):
        workflow = Workflow(user_id=test_user.id, project_id=project.id, name=f"Workflow {index}")
        test_session.add(workflow)
        await test_session.flush()
        test_session.add(
            FolderWatch(
                user_id=test_user.id,
                workflow_id=workflow.id,
                name=f"Watch {index}",
                folder_path=f"/test/{index}",
                is_enabled=False,
            )
        )
        test_session.add(
            ExecutionRun(
                user_id=test_user.id,
                project_id=project.id,
                workflow_id=workflow.id,
                name=f"Prediction {index}",
                run_kind="batch_inference",
                status="completed",
                executed_at=datetime.now(timezone.utc),
                params_snapshot={},
                results_summary={},
            )
        )
    await test_session.commit()
    for index, project in enumerate(projects):
        watches = await deploy.list_watches(project_id=project.id, session=test_session, current_user=test_user)
        history = await deploy.list_deploy_runs(
            project_id=project.id, source_type=None, label=None, session=test_session, current_user=test_user
        )
        assert [watch.name for watch in watches] == [f"Watch {index}"]
        assert [run.name for run in history.runs] == [f"Prediction {index}"]
        assert history.total == 1
