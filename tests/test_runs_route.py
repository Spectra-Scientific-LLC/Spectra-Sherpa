from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from fastapi import Response


async def _seed_artifact(test_session, test_user, *, project_id: int | None = None):
    from spectra_sherpa.app.models.model_artifact import ModelArtifact
    from spectra_sherpa.app.models.project import Project
    from spectra_sherpa.app.models.workflow import Workflow

    project = Project(user_id=test_user.id, name="Run project")
    test_session.add(project)
    await test_session.flush()

    workflow = Workflow(user_id=test_user.id, project_id=project.id, name="Training workflow")
    test_session.add(workflow)
    await test_session.flush()

    artifact = ModelArtifact(
        artifact_uid=f"artifact-{project_id or project.id}",
        user_id=test_user.id,
        project_id=project_id or project.id,
        workflow_id=workflow.id,
        workflow_version_id=None,
        node_id="model_train_1",
        model_type="plsda",
        name="PLSDA — auto",
        display_name="PLSDA — named",
        artifact_dir="/tmp/model",
        integrity_hash="hash",
        n_features=4,
        tags=["calibration"],
        is_active=True,
    )
    test_session.add(artifact)
    await test_session.commit()
    return project, workflow, artifact


@pytest.mark.asyncio
async def test_batch_run_artifacts_persists_artifact_keyed_run(test_session, test_user, monkeypatch):
    from spectra_sherpa.app.api.v1.routes import runs as runs_route

    project, _, artifact = await _seed_artifact(test_session, test_user)

    async def fake_load_project_dataset(*_args, **_kwargs):
        return SimpleNamespace(
            dataset=object(),
            experiment_id=123,
            experiment_name="Wine",
            project_id=project.id,
            file_ids=[456],
            stage="raw",
        )

    def fake_apply_model_to_dataset(artifact_uid, _dataset, *, scope):
        return {
            "artifact_uid": artifact_uid,
            "model_type": "plsda",
            "n_samples": 10,
            "predictions": ["A", "B"],
            "metrics": {"accuracy": 0.9},
            "scope": scope,
        }

    monkeypatch.setattr(runs_route, "load_project_dataset", fake_load_project_dataset)
    monkeypatch.setattr(runs_route, "apply_model_to_dataset", fake_apply_model_to_dataset)

    payload = runs_route.ArtifactBatchRunRequest(
        artifact_uids=[artifact.artifact_uid],
        dataset=runs_route.RunDatasetRef(experiment_id=123),
        scope="all",
        run_name="Artifact batch on wine",
    )

    http_response = Response()
    response = await runs_route.batch_run_artifacts(
        payload,
        response=http_response,
        _dg=None,
        session=test_session,
        current_user=test_user,
    )

    assert http_response.status_code == 201
    assert response.status == "completed"
    assert response.run is not None
    assert response.run.name == "Artifact batch on wine"
    assert response.run.run_kind == "batch_inference"
    assert response.run.applied_artifact_uids == [artifact.artifact_uid]
    assert response.run.model_ids == [artifact.artifact_uid]
    assert response.run.source_type == "batch"
    assert response.run.source_metadata["dataset"]["experiment_id"] == 123
    assert response.run.results_summary[artifact.artifact_uid]["accuracy"] == 0.9
    assert response.results[0].status == "completed"


@pytest.mark.asyncio
async def test_batch_run_artifacts_rejects_cross_project_dataset(test_session, test_user, monkeypatch):
    from fastapi import HTTPException

    from spectra_sherpa.app.api.v1.routes import runs as runs_route

    _, _, artifact = await _seed_artifact(test_session, test_user)

    async def fake_load_project_dataset(*_args, **_kwargs):
        return SimpleNamespace(
            dataset=object(),
            experiment_id=123,
            experiment_name="Other",
            project_id=999,
            file_ids=[],
            stage="raw",
        )

    monkeypatch.setattr(runs_route, "load_project_dataset", fake_load_project_dataset)

    payload = runs_route.ArtifactBatchRunRequest(
        artifact_uids=[artifact.artifact_uid],
        dataset=runs_route.RunDatasetRef(experiment_id=123),
        scope="all",
    )

    with pytest.raises(HTTPException) as exc:
        await runs_route.batch_run_artifacts(
            payload,
            response=Response(),
            _dg=None,
            session=test_session,
            current_user=test_user,
        )

    assert exc.value.status_code == 400
    assert "same project" in exc.value.detail


@pytest.mark.asyncio
async def test_batch_run_artifacts_reports_failing_artifact(test_session, test_user, monkeypatch):
    from spectra_sherpa.app.api.v1.routes import runs as runs_route

    project, _, artifact = await _seed_artifact(test_session, test_user)

    async def fake_load_project_dataset(*_args, **_kwargs):
        return SimpleNamespace(
            dataset=object(),
            experiment_id=123,
            experiment_name="Wine",
            project_id=project.id,
            file_ids=[456],
            stage="raw",
        )

    def fake_apply_model_to_dataset(_artifact_uid, _dataset, *, scope):
        assert scope == "all"
        raise ValueError("feature-axis values differ from the artifact")

    monkeypatch.setattr(runs_route, "load_project_dataset", fake_load_project_dataset)
    monkeypatch.setattr(runs_route, "apply_model_to_dataset", fake_apply_model_to_dataset)

    payload = runs_route.ArtifactBatchRunRequest(
        artifact_uids=[artifact.artifact_uid],
        dataset=runs_route.RunDatasetRef(experiment_id=123),
        scope="all",
    )

    http_response = Response()
    response = await runs_route.batch_run_artifacts(
        payload,
        response=http_response,
        _dg=None,
        session=test_session,
        current_user=test_user,
    )

    assert http_response.status_code == 207
    assert response.status == "failed"
    assert response.run is None
    assert response.results[0].artifact_uid == artifact.artifact_uid
    assert response.results[0].status == "failed"
    assert response.results[0].error is not None
    assert "feature-axis values differ" in response.results[0].error


@pytest.mark.asyncio
async def test_batch_run_artifacts_persists_successes_with_partial_207(test_session, test_user, monkeypatch):
    from spectra_sherpa.app.api.v1.routes import runs as runs_route
    from spectra_sherpa.app.models.model_artifact import ModelArtifact

    project, workflow, first = await _seed_artifact(test_session, test_user)
    second = ModelArtifact(
        artifact_uid="artifact-partial-fail",
        user_id=test_user.id,
        project_id=project.id,
        workflow_id=workflow.id,
        workflow_version_id=None,
        node_id="model_train_2",
        model_type="plsda",
        name="PLSDA — second",
        display_name="PLSDA — second",
        artifact_dir="/tmp/model-2",
        integrity_hash="hash-2",
        n_features=4,
        is_active=True,
    )
    test_session.add(second)
    await test_session.commit()

    async def fake_load_project_dataset(*_args, **_kwargs):
        return SimpleNamespace(
            dataset=object(),
            experiment_id=123,
            experiment_name="Wine",
            project_id=project.id,
            file_ids=[456],
            stage="raw",
        )

    def fake_apply_model_to_dataset(artifact_uid, _dataset, *, scope):
        assert scope == "all"
        if artifact_uid == second.artifact_uid:
            raise ValueError("feature-axis values differ from the artifact")
        return {
            "artifact_uid": artifact_uid,
            "model_type": "plsda",
            "n_samples": 10,
            "predictions": ["A", "B"],
            "metrics": {"accuracy": 0.9},
            "scope": scope,
        }

    monkeypatch.setattr(runs_route, "load_project_dataset", fake_load_project_dataset)
    monkeypatch.setattr(runs_route, "apply_model_to_dataset", fake_apply_model_to_dataset)

    payload = runs_route.ArtifactBatchRunRequest(
        artifact_uids=[first.artifact_uid, second.artifact_uid],
        dataset=runs_route.RunDatasetRef(experiment_id=123),
        scope="all",
    )

    http_response = Response()
    response = await runs_route.batch_run_artifacts(
        payload,
        response=http_response,
        _dg=None,
        session=test_session,
        current_user=test_user,
    )

    assert http_response.status_code == 207
    assert response.status == "partial"
    assert response.run is not None
    assert response.run.status == "partial"
    assert response.run.applied_artifact_uids == [first.artifact_uid]
    assert response.results[0].status == "completed"
    assert response.results[1].status == "failed"
    assert response.results[1].artifact_uid == second.artifact_uid


@pytest.mark.asyncio
async def test_batch_run_artifacts_allows_mixed_workflow_lineage(test_session, test_user, monkeypatch):
    from spectra_sherpa.app.api.v1.routes import runs as runs_route
    from spectra_sherpa.app.models.model_artifact import ModelArtifact
    from spectra_sherpa.app.models.workflow import Workflow

    project, _, first = await _seed_artifact(test_session, test_user)
    other_workflow = Workflow(user_id=test_user.id, project_id=project.id, name="Other training workflow")
    test_session.add(other_workflow)
    await test_session.flush()
    second = ModelArtifact(
        artifact_uid="artifact-other-workflow",
        user_id=test_user.id,
        project_id=project.id,
        workflow_id=other_workflow.id,
        workflow_version_id=None,
        node_id="model_train_2",
        model_type="knn",
        name="KNN — auto",
        display_name="KNN — named",
        artifact_dir="/tmp/model-2",
        integrity_hash="hash-2",
        n_features=4,
        is_active=True,
    )
    test_session.add(second)
    await test_session.commit()

    payload = runs_route.ArtifactBatchRunRequest(
        artifact_uids=[first.artifact_uid, second.artifact_uid],
        dataset=runs_route.RunDatasetRef(experiment_id=123),
    )

    async def fake_load_project_dataset(*_args, **_kwargs):
        return SimpleNamespace(
            dataset=object(),
            experiment_id=123,
            experiment_name="Wine",
            project_id=project.id,
            file_ids=[],
            stage="raw",
        )

    def fake_apply_model_to_dataset(artifact_uid, _dataset, *, scope):
        return {"artifact_uid": artifact_uid, "n_samples": 3, "metrics": {"ok": True}, "scope": scope}

    monkeypatch.setattr(runs_route, "load_project_dataset", fake_load_project_dataset)
    monkeypatch.setattr(runs_route, "apply_model_to_dataset", fake_apply_model_to_dataset)

    http_response = Response()
    response = await runs_route.batch_run_artifacts(
        payload,
        response=http_response,
        _dg=None,
        session=test_session,
        current_user=test_user,
    )

    assert http_response.status_code == 201
    assert response.run is not None
    assert response.run.applied_artifact_uids == [first.artifact_uid, second.artifact_uid]
    assert response.run.source_metadata["artifact_lineage"] == [
        {
            "artifact_uid": first.artifact_uid,
            "workflow_id": first.workflow_id,
            "workflow_version_id": first.workflow_version_id,
            "source_run_id": first.source_run_id,
        },
        {
            "artifact_uid": second.artifact_uid,
            "workflow_id": second.workflow_id,
            "workflow_version_id": second.workflow_version_id,
            "source_run_id": second.source_run_id,
        },
    ]


@pytest.mark.asyncio
async def test_project_runs_list_and_compare_across_project(test_session, test_user):
    from spectra_sherpa.app.api.v1.routes import runs as runs_route
    from spectra_sherpa.app.models.execution_run import ExecutionRun
    from spectra_sherpa.app.schemas.execution_runs import CompareRunsRequest

    project, workflow, artifact = await _seed_artifact(test_session, test_user)
    first = ExecutionRun(
        project_id=project.id,
        workflow_id=workflow.id,
        user_id=test_user.id,
        name="Training run",
        status="completed",
        params_snapshot={},
        results_summary={"model": {"accuracy": 0.8}},
        executed_at=datetime.now(timezone.utc),
        labels=[],
        model_ids=[artifact.artifact_uid],
        run_kind="training",
    )
    second = ExecutionRun(
        project_id=project.id,
        workflow_id=workflow.id,
        user_id=test_user.id,
        name="Batch run",
        status="completed",
        params_snapshot={},
        results_summary={"model": {"accuracy": 0.9}},
        executed_at=datetime.now(timezone.utc),
        labels=[],
        model_ids=[artifact.artifact_uid],
        applied_artifact_uids=[artifact.artifact_uid],
        run_kind="batch_inference",
    )
    test_session.add_all([first, second])
    await test_session.commit()

    listed = await runs_route.list_project_runs(
        project_id=project.id,
        kind=None,
        artifact_uid=None,
        session=test_session,
        current_user=test_user,
    )

    assert listed.total == 2
    assert {run.run_kind for run in listed.runs} == {"training", "batch_inference"}

    comparison = await runs_route.compare_project_runs(
        CompareRunsRequest(run_ids=[first.id, second.id]),
        project_id=project.id,
        session=test_session,
        current_user=test_user,
    )

    assert comparison.metric_keys == ["accuracy"]
    assert comparison.diff["accuracy"][str(first.id)] == 0.8
    assert comparison.diff["accuracy"][str(second.id)] == 0.9


@pytest.mark.asyncio
async def test_project_run_compare_extracts_nested_training_metrics(test_session, test_user):
    from spectra_sherpa.app.api.v1.routes import runs as runs_route
    from spectra_sherpa.app.models.execution_run import ExecutionRun
    from spectra_sherpa.app.schemas.execution_runs import CompareRunsRequest

    project, workflow, _ = await _seed_artifact(test_session, test_user)
    first = ExecutionRun(
        project_id=project.id,
        workflow_id=workflow.id,
        user_id=test_user.id,
        name="SIMCA",
        status="completed",
        params_snapshot={},
        results_summary={"simca": {"train_accuracy": 0.88}},
        executed_at=datetime.now(timezone.utc),
        labels=[],
        run_kind="training",
    )
    second = ExecutionRun(
        project_id=project.id,
        workflow_id=workflow.id,
        user_id=test_user.id,
        name="KNN",
        status="completed",
        params_snapshot={},
        results_summary={
            "knn": {
                "default": {
                    "metadata": {
                        "train_accuracy": 0.95,
                        "quality_summary": {
                            "cv_accuracy": 0.91,
                            "cv_f1_macro": 0.89,
                            "cv_sensitivity_macro": 0.88,
                            "cv_specificity_macro": 0.93,
                        },
                    }
                }
            }
        },
        executed_at=datetime.now(timezone.utc),
        labels=[],
        run_kind="training",
    )
    test_session.add_all([first, second])
    await test_session.commit()

    comparison = await runs_route.compare_project_runs(
        CompareRunsRequest(run_ids=[first.id, second.id]),
        project_id=project.id,
        session=test_session,
        current_user=test_user,
    )

    assert "train_accuracy" in comparison.metric_keys
    assert "cv_accuracy" in comparison.metric_keys
    assert "cv_f1_macro" in comparison.metric_keys
    assert "cv_sensitivity_macro" in comparison.metric_keys
    assert "cv_specificity_macro" in comparison.metric_keys
    assert comparison.diff["train_accuracy"][str(first.id)] == 0.88
    assert comparison.diff["train_accuracy"][str(second.id)] == 0.95
    assert comparison.diff["cv_accuracy"][str(second.id)] == 0.91
    assert comparison.diff["cv_f1_macro"][str(second.id)] == 0.89


@pytest.mark.asyncio
async def test_workflow_compare_uses_curated_scalar_metrics(test_session, test_user):
    from spectra_sherpa.app.api.v1.routes import execution_runs as execution_runs_route
    from spectra_sherpa.app.models.execution_run import ExecutionRun
    from spectra_sherpa.app.schemas.execution_runs import CompareRunsRequest

    project, workflow, _ = await _seed_artifact(test_session, test_user)
    first = ExecutionRun(
        project_id=project.id,
        workflow_id=workflow.id,
        user_id=test_user.id,
        name="KNN",
        status="completed",
        params_snapshot={},
        results_summary={
            "knn": {
                "default": {"data": [[1, 2]], "metadata": {"cv_accuracy": 0.9}},
                "predictions": ["a", "b"],
                "confusion_matrix": [[1, 0], [0, 1]],
                "model": {"type": "knn"},
            }
        },
        executed_at=datetime.now(timezone.utc),
        labels=[],
        run_kind="training",
    )
    second = ExecutionRun(
        project_id=project.id,
        workflow_id=workflow.id,
        user_id=test_user.id,
        name="SIMCA",
        status="completed",
        params_snapshot={},
        results_summary={
            "simca": {
                "default": {"data": [[1, 2]], "metadata": {"train_accuracy": 0.95}},
                "predictions": ["a", "b"],
                "confusion_matrix": [[1, 0], [0, 1]],
                "model": {"type": "simca"},
            }
        },
        executed_at=datetime.now(timezone.utc),
        labels=[],
        run_kind="training",
    )
    test_session.add_all([first, second])
    await test_session.commit()

    comparison = await execution_runs_route.compare_runs(
        workflow.id,
        CompareRunsRequest(run_ids=[first.id, second.id]),
        session=test_session,
        current_user=test_user,
    )

    assert comparison.metric_keys == ["cv_accuracy", "train_accuracy"]
    assert set(comparison.diff) == {"cv_accuracy", "train_accuracy"}
    assert comparison.diff["cv_accuracy"][str(first.id)] == 0.9
    assert comparison.diff["train_accuracy"][str(second.id)] == 0.95


@pytest.mark.asyncio
async def test_workflow_compare_prefers_canonical_classification_contract(test_session, test_user):
    from spectra_sherpa.app.api.v1.routes import execution_runs as execution_runs_route
    from spectra_sherpa.app.models.execution_run import ExecutionRun
    from spectra_sherpa.app.schemas.execution_runs import CompareRunsRequest

    project, workflow, _ = await _seed_artifact(test_session, test_user)
    first = ExecutionRun(
        project_id=project.id,
        workflow_id=workflow.id,
        user_id=test_user.id,
        name="KNN",
        status="completed",
        params_snapshot={},
        results_summary={
            "knn": {
                "accuracy": 0.99,  # ambiguous legacy scalar; must not drive comparison
                "metrics": {
                    "task_type": "classification",
                    "primary_split": "cv",
                    "primary_metric": "balanced_accuracy",
                    "n_classes": 3,
                    "splits": {
                        "train": {"accuracy": 0.94, "balanced_accuracy": 0.93},
                        "cv": {"accuracy": 0.82, "balanced_accuracy": 0.80, "f1_macro": 0.79},
                    },
                },
            }
        },
        executed_at=datetime.now(timezone.utc),
        labels=[],
        run_kind="training",
    )
    second = ExecutionRun(
        project_id=project.id,
        workflow_id=workflow.id,
        user_id=test_user.id,
        name="SIMCA",
        status="completed",
        params_snapshot={},
        results_summary={
            "simca": {
                "accuracy": 0.98,  # ambiguous legacy scalar; must not drive comparison
                "metrics": {
                    "task_type": "classification",
                    "primary_split": "cv",
                    "primary_metric": "balanced_accuracy",
                    "n_classes": 3,
                    "splits": {
                        "train": {"accuracy": 0.96, "balanced_accuracy": 0.95},
                        "cv": {"accuracy": 0.84, "balanced_accuracy": 0.83, "f1_macro": 0.81},
                    },
                },
            }
        },
        executed_at=datetime.now(timezone.utc),
        labels=[],
        run_kind="training",
    )
    test_session.add_all([first, second])
    await test_session.commit()

    comparison = await execution_runs_route.compare_runs(
        workflow.id,
        CompareRunsRequest(run_ids=[first.id, second.id]),
        session=test_session,
        current_user=test_user,
    )

    assert "accuracy" not in comparison.metric_keys
    assert comparison.metric_keys[:5] == [
        "cv_balanced_accuracy",
        "cv_accuracy",
        "train_accuracy",
        "train_balanced_accuracy",
        "cv_f1_macro",
    ]
    assert comparison.diff["cv_balanced_accuracy"][str(first.id)] == 0.80
    assert comparison.diff["cv_balanced_accuracy"][str(second.id)] == 0.83
    assert comparison.diff["train_accuracy"][str(first.id)] == 0.94


@pytest.mark.asyncio
async def test_project_run_survives_workflow_sheet_delete(test_session, test_user):
    from spectra_sherpa.app.models.execution_run import ExecutionRun

    project, workflow, _ = await _seed_artifact(test_session, test_user)
    run = ExecutionRun(
        project_id=project.id,
        workflow_id=workflow.id,
        user_id=test_user.id,
        name="Durable run",
        status="completed",
        params_snapshot={},
        results_summary={},
        executed_at=datetime.now(timezone.utc),
        labels=[],
        run_kind="data",
    )
    test_session.add(run)
    await test_session.flush()
    run_id = run.id

    await test_session.delete(workflow)
    await test_session.commit()

    persisted = await test_session.get(ExecutionRun, run_id)
    assert persisted is not None
    assert persisted.project_id == project.id
    assert persisted.workflow_id is None

    from spectra_sherpa.app.api.v1.routes import runs as runs_route

    listed = await runs_route.list_project_runs(
        project_id=project.id,
        kind=None,
        artifact_uid=None,
        session=test_session,
        current_user=test_user,
    )
    assert [item.id for item in listed.runs] == [run_id]


@pytest.mark.asyncio
async def test_workflow_data_access_rejects_dataset_from_other_project(test_session, test_user):
    from fastapi import HTTPException

    from spectra_sherpa.app.models.experiment import Experiment
    from spectra_sherpa.app.models.project import Project
    from spectra_sherpa.app.services.workflow_access import validate_workflow_execution_access

    project_a = Project(user_id=test_user.id, name="Project A")
    project_b = Project(user_id=test_user.id, name="Project B")
    test_session.add_all([project_a, project_b])
    await test_session.flush()

    foreign_dataset = Experiment(
        user_id=test_user.id,
        project_id=project_b.id,
        name="Foreign dataset",
        metadata_path="/tmp/foreign-metadata.json",
    )
    test_session.add(foreign_dataset)
    await test_session.commit()

    nodes = [
        SimpleNamespace(
            node_id="src",
            node_type="data.source",
            parameters={"source": "experiment", "experiment_id": foreign_dataset.id},
        )
    ]
    with pytest.raises(HTTPException) as exc:
        await validate_workflow_execution_access(
            nodes,
            None,
            test_user.id,
            project_a.id,
            test_session,
        )

    assert exc.value.status_code == 404
    assert "this project" in exc.value.detail


@pytest.mark.asyncio
async def test_model_select_and_search_are_project_scoped(test_session, test_user):
    from spectra_sherpa.app.api.v1.routes import models as models_route

    project, _, artifact = await _seed_artifact(test_session, test_user)

    selected = await models_route.select_models(
        model_type=None,
        n_features=None,
        project_id=project.id,
        session=test_session,
        current_user=test_user,
    )

    assert [item.artifact_uid for item in selected] == [artifact.artifact_uid]
    assert selected[0].name == artifact.display_name

    searched = await models_route.list_models(
        model_type=None,
        project_id=project.id,
        workflow_id=None,
        q="calibration",
        deploy_ready=None,
        include_inactive=False,
        limit=100,
        offset=0,
        session=test_session,
        current_user=test_user,
    )

    assert [model.artifact_uid for model in searched] == [artifact.artifact_uid]


@pytest.mark.asyncio
async def test_model_metadata_patch_updates_editable_lifecycle_fields(test_session, test_user):
    from spectra_sherpa.app.api.v1.routes import models as models_route

    _, _, artifact = await _seed_artifact(test_session, test_user)

    updated = await models_route.update_model(
        artifact.artifact_uid,
        models_route.ModelUpdateRequest(
            display_name="Wine PLSDA production candidate",
            tags=["wine", "candidate"],
            is_deploy_ready=True,
        ),
        _dg=None,
        session=test_session,
        current_user=test_user,
    )

    assert updated.display_name == "Wine PLSDA production candidate"
    assert updated.tags == ["wine", "candidate"]
    assert updated.is_deploy_ready is True


def test_model_update_rejects_overlong_tags():
    from pydantic import ValidationError

    from spectra_sherpa.app.api.v1.routes.models import ModelUpdateRequest

    with pytest.raises(ValidationError):
        ModelUpdateRequest(tags=["x" * 65])


@pytest.mark.asyncio
async def test_auto_persist_run_keeps_artifact_source_run_immutable(test_session, test_user):
    from sqlalchemy import select

    from spectra_sherpa.app.api.v1.routes.workflows._helpers import _auto_persist_run
    from spectra_sherpa.app.models.execution_run import ExecutionRun
    from spectra_sherpa.app.models.model_artifact import ModelArtifact

    project, workflow, first = await _seed_artifact(test_session, test_user)
    second = ModelArtifact(
        artifact_uid="artifact-second-run",
        user_id=test_user.id,
        project_id=project.id,
        workflow_id=workflow.id,
        workflow_version_id=None,
        node_id="model_train_2",
        model_type="knn",
        name="KNN — auto",
        display_name="KNN — named",
        artifact_dir="/tmp/model-2",
        integrity_hash="hash-2",
        n_features=4,
        is_active=True,
    )
    test_session.add(second)
    await test_session.commit()

    first_run_id = await _auto_persist_run(
        test_session,
        workflow_id=workflow.id,
        user_id=test_user.id,
        wf_version_id=None,
        serialized_results={"model_train_1": {"model_id": first.artifact_uid}},
        diagnostics_serialized={},
        node_statuses={"model_train_1": "completed"},
        final_status="completed",
        error_msg=None,
        integrity_hash=None,
        model_ids=[first.artifact_uid],
        params_snapshot={},
    )
    assert first_run_id is not None
    await test_session.refresh(first)
    first_source_run = first.source_run_id
    assert first_source_run is not None

    second_run_id = await _auto_persist_run(
        test_session,
        workflow_id=workflow.id,
        user_id=test_user.id,
        wf_version_id=None,
        serialized_results={"model_train_2": {"model_id": second.artifact_uid}},
        diagnostics_serialized={},
        node_statuses={"model_train_2": "completed"},
        final_status="completed",
        error_msg=None,
        integrity_hash=None,
        model_ids=[second.artifact_uid],
        params_snapshot={},
    )
    assert second_run_id is not None
    await test_session.refresh(first)
    await test_session.refresh(second)

    assert first.source_run_id == first_source_run
    assert second.source_run_id is not None
    assert second.source_run_id != first_source_run
    run_ids = (await test_session.execute(select(ExecutionRun.id).where(ExecutionRun.workflow_id == workflow.id))).all()
    assert len(run_ids) == 2


@pytest.mark.asyncio
async def test_create_run_rejects_model_artifact_from_another_workflow(test_session, test_user):
    from fastapi import HTTPException

    from spectra_sherpa.app.api.v1.routes import execution_runs as run_route
    from spectra_sherpa.app.schemas.execution_runs import SaveRunRequest

    _, workflow, _ = await _seed_artifact(test_session, test_user)
    _, _, foreign_artifact = await _seed_artifact(test_session, test_user)

    payload = SaveRunRequest(
        name="Named run",
        status="completed",
        results_summary={},
        executed_at="2026-01-01T00:00:00",
        model_ids=[foreign_artifact.artifact_uid],
    )

    with pytest.raises(HTTPException) as exc:
        await run_route.create_run(workflow.id, payload, session=test_session, current_user=test_user)

    assert exc.value.status_code == 400
    assert "workflow and project" in exc.value.detail


@pytest.mark.asyncio
async def test_create_run_names_explicit_auto_run_once(test_session, test_user):
    from fastapi import HTTPException

    from spectra_sherpa.app.api.v1.routes import execution_runs as run_route
    from spectra_sherpa.app.models.execution_run import ExecutionRun
    from spectra_sherpa.app.schemas.execution_runs import SaveRunRequest

    _, workflow, _ = await _seed_artifact(test_session, test_user)
    auto_run = ExecutionRun(
        project_id=workflow.project_id,
        workflow_id=workflow.id,
        workflow_version_id=None,
        user_id=test_user.id,
        name="__latest__",
        status="completed",
        params_snapshot={},
        results_summary={},
        diagnostics=None,
        node_statuses=None,
        error=None,
        integrity_hash="hash",
        executed_at=datetime.now(timezone.utc),
        notes=None,
        labels=[],
        source_type="auto",
        model_ids=[],
        run_kind="data",
        applied_artifact_uids=[],
    )
    test_session.add(auto_run)
    await test_session.commit()
    await test_session.refresh(auto_run)

    payload = SaveRunRequest(
        run_id=auto_run.id,
        name="Named exact run",
        status="completed",
        results_summary={},
        executed_at="2026-01-01T00:00:00",
        run_kind="data",
    )

    named = await run_route.create_run(workflow.id, payload, session=test_session, current_user=test_user)
    assert named.id == auto_run.id
    assert named.name == "Named exact run"
    assert named.source_type == "named"

    with pytest.raises(HTTPException) as exc:
        await run_route.create_run(workflow.id, payload, session=test_session, current_user=test_user)
    assert exc.value.status_code == 404
