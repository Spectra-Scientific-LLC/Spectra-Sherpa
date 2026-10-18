"""Starter API: overview, goal planning, project goals and progress."""

from __future__ import annotations

import io
import json
import zipfile
from datetime import datetime, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from spectra_sherpa.app.contracts import starter_planning
from spectra_sherpa.app.contracts.starter_planning import GoalClassification, set_goal_classifier
from spectra_sherpa.app.core.template_loader import TemplateLoader
from spectra_sherpa.app.models.execution_run import ExecutionRun
from spectra_sherpa.app.models.experiment import Experiment
from spectra_sherpa.app.models.experiment_file import ExperimentFile
from spectra_sherpa.app.models.model_artifact import ModelArtifact
from spectra_sherpa.app.models.project import Project
from spectra_sherpa.app.models.project_data_source import ProjectDataSource
from spectra_sherpa.app.models.user import User
from spectra_sherpa.app.models.workflow import Workflow
from spectra_sherpa.app.models.workflow_node import WorkflowNode
from spectra_sherpa.app.models.workflow_template import WorkflowTemplate

pytestmark = pytest.mark.anyio


@pytest.fixture(autouse=True)
def _no_goal_classifier():
    set_goal_classifier(None)
    yield
    set_goal_classifier(None)


@pytest.fixture
def ai_consent(monkeypatch):
    """The user has allowed AI disclosure, so a registered classifier may read goals."""
    from spectra_sherpa.app.api.v1.routes import starter as starter_routes

    async def allow(_user, permission, **_kwargs):
        assert permission == "allow_llm_chat"
        return True

    monkeypatch.setattr(starter_routes, "check_egress_permission", allow)


async def _seed_templates(session: AsyncSession, *slugs: str) -> None:
    records = {record["slug"]: record for record in TemplateLoader().load_all()}
    session.add_all(WorkflowTemplate(**records[slug]) for slug in slugs)
    await session.flush()


async def test_overview_reports_first_run_and_suggests_a_goal(auth_client: AsyncClient):
    response = await auth_client.get("/api/v1/starter")
    assert response.status_code == 200
    body = response.json()
    assert body["is_first_run"] is True
    assert body["last_goal"] is None
    assert body["suggested_goal"].startswith("Smooth my spectra")
    assert {example["intent"] for example in body["examples"]} >= {"preprocess", "explore", "calibrate"}
    assert body["model_planning_available"] is False


async def test_overview_returns_the_most_recent_goal(auth_client: AsyncClient):
    for goal in ("Find peaks in my spectra", "Smooth my Raman spectra"):
        created = await auth_client.post("/api/v1/projects", json={"name": goal, "goal": goal})
        assert created.status_code == 201
    await auth_client.post("/api/v1/projects", json={"name": "No goal"})

    body = (await auth_client.get("/api/v1/starter")).json()
    assert body["is_first_run"] is False
    assert body["last_goal"] == "Smooth my Raman spectra"


async def test_plan_uses_the_ready_template_for_the_goal(auth_client: AsyncClient, test_session: AsyncSession):
    await _seed_templates(test_session, "preprocessing", "pca")

    response = await auth_client.post("/api/v1/starter/plan", json={"goal": "  Smooth my spectra  "})
    assert response.status_code == 200
    plan = response.json()
    assert plan["schema_version"] == "spectra-starter-plan/1"
    assert plan["goal"] == "Smooth my spectra"
    assert plan["intent"] == "preprocess"
    assert plan["source"] == "rules"
    assert plan["template_slug"] == "preprocessing"
    assert plan["template_name"]
    assert [step["key"] for step in plan["steps"]][0] == "project"


async def test_plan_without_an_available_template_still_returns_steps(auth_client: AsyncClient):
    plan = (await auth_client.post("/api/v1/starter/plan", json={"goal": "Find the peaks"})).json()
    assert plan["intent"] == "peaks"
    assert plan["template_slug"] is None
    assert plan["steps"]


async def test_blank_goal_is_rejected(auth_client: AsyncClient):
    response = await auth_client.post("/api/v1/starter/plan", json={"goal": "   "})
    assert response.status_code == 422


async def test_model_classifier_refines_only_unclear_intents(
    ai_consent, auth_client: AsyncClient, test_session: AsyncSession
):
    await _seed_templates(test_session, "pls_calibration", "preprocessing")
    calls: list[str] = []

    async def classifier(*, goal, intents, datasets, user_id):
        calls.append(goal)
        assert {intent["key"] for intent in intents} >= {"calibrate", "explore"}
        assert all(
            set(dataset) <= {"key", "label", "kind", "technique", "description", "supports"} for dataset in datasets
        )
        return GoalClassification(intent="calibrate", confidence=0.85, summary="  Predict   moisture. ")

    set_goal_classifier(classifier)
    assert (await auth_client.get("/api/v1/starter")).json()["model_planning_available"] is True

    plan = (await auth_client.post("/api/v1/starter/plan", json={"goal": "How wet is my grain?"})).json()
    assert plan["intent"] == "calibrate"
    assert plan["source"] == "model"
    assert plan["summary"] == "Predict moisture."
    assert plan["template_slug"] == "pls_calibration"

    clear = (await auth_client.post("/api/v1/starter/plan", json={"goal": "smooth and baseline correct"})).json()
    assert clear["source"] == "rules"
    assert clear["intent"] == "preprocess"
    assert calls == ["How wet is my grain?", "smooth and baseline correct"]


async def test_plan_suggests_a_compatible_dataset(auth_client: AsyncClient, test_session: AsyncSession):
    await _seed_templates(test_session, "pls_calibration")
    plan = (await auth_client.post("/api/v1/starter/plan", json={"goal": "Predict moisture in corn from NIR"})).json()
    assert plan["dataset"] is not None
    assert "corn" in plan["dataset"]["label"].lower()
    assert plan["dataset"]["chosen_by"] == "rules"
    assert plan["dataset_options"][0]["key"] == plan["dataset"]["key"]
    assert all(option["kind"] == "reference" for option in plan["dataset_options"])


async def test_plan_offers_the_users_own_dataset(auth_client: AsyncClient, test_session: AsyncSession, test_user: User):
    await _seed_templates(test_session, "preprocessing")
    elsewhere = Project(user_id=test_user.id, name="Other project")
    test_session.add(elsewhere)
    await test_session.flush()
    experiment = Experiment(user_id=test_user.id, name="Olive oil batch 3", metadata_path="{}")
    empty = Experiment(user_id=test_user.id, name="Olive oil empty", metadata_path="{}")
    # Adding a dataset to the new project would move it out of this one.
    in_project = Experiment(
        user_id=test_user.id, project_id=elsewhere.id, name="Olive oil in project", metadata_path="{}"
    )
    test_session.add_all([experiment, empty, in_project])
    await test_session.flush()
    test_session.add_all(
        [
            ExperimentFile(experiment_id=experiment.id, file_path="raw/a.csv", stage="raw"),
            ExperimentFile(experiment_id=in_project.id, file_path="raw/b.csv", stage="raw"),
        ]
    )
    await test_session.commit()

    plan = (await auth_client.post("/api/v1/starter/plan", json={"goal": "Smooth my olive oil spectra"})).json()
    assert plan["dataset"]["kind"] == "experiment"
    assert plan["dataset"]["experiment_id"] == experiment.id
    offered = {option.get("experiment_id") for option in plan["dataset_options"]}
    assert empty.id not in offered
    assert in_project.id not in offered


async def test_model_can_choose_among_offered_datasets_only(
    ai_consent, auth_client: AsyncClient, test_session: AsyncSession
):
    await _seed_templates(test_session, "pls_calibration")
    offered: list[str] = []
    answer: dict = {}

    async def classifier(*, goal, intents, datasets, user_id):
        offered[:] = [dataset["key"] for dataset in datasets if "calibrate" in dataset["supports"]]
        return GoalClassification(intent="calibrate", confidence=0.9, **answer)

    set_goal_classifier(classifier)
    await auth_client.post("/api/v1/starter/plan", json={"goal": "predict concentration"})
    assert len(offered) >= 2
    answer.update(dataset_key=offered[-1], dataset_reason="  Diesel   density is closest. ")

    plan = (await auth_client.post("/api/v1/starter/plan", json={"goal": "predict concentration"})).json()
    assert plan["dataset"]["key"] == offered[-1]
    assert plan["dataset"]["chosen_by"] == "model"
    assert plan["dataset"]["reason"] == "Diesel density is closest."
    assert plan["dataset_options"][0]["key"] == offered[-1]

    answer.update(dataset_key="registered:not-offered", dataset_reason="trust me")
    plan = (await auth_client.post("/api/v1/starter/plan", json={"goal": "predict concentration"})).json()
    assert plan["dataset"]["chosen_by"] != "model"
    assert plan["dataset"]["key"] in offered


@pytest.mark.parametrize(
    "answer",
    [
        GoalClassification(intent="delete_everything", confidence=0.99),
        GoalClassification(intent="calibrate", confidence=1.5),
        "calibrate",
    ],
)
async def test_invalid_classifier_answers_fall_back_to_rules(ai_consent, auth_client: AsyncClient, answer):
    async def classifier(**_kwargs):
        return answer

    set_goal_classifier(classifier)
    plan = (await auth_client.post("/api/v1/starter/plan", json={"goal": "How wet is my grain?"})).json()
    assert plan["source"] == "rules"
    assert plan["intent"] == "explore"


async def test_failing_or_slow_classifier_falls_back_to_rules(ai_consent, auth_client: AsyncClient):
    async def classifier(**_kwargs):
        raise RuntimeError("model offline")

    set_goal_classifier(classifier)
    plan = (await auth_client.post("/api/v1/starter/plan", json={"goal": "How wet is my grain?"})).json()
    assert plan["source"] == "rules"

    import asyncio

    async def slow(**_kwargs):
        await asyncio.sleep(1)

    set_goal_classifier(slow, timeout_seconds=0.01)
    assert starter_planning._timeout_seconds == 0.01
    plan = (await auth_client.post("/api/v1/starter/plan", json={"goal": "How wet is my grain?"})).json()
    assert plan["source"] == "rules"


async def _plan(client: AsyncClient, goal: str) -> dict:
    return (await client.post("/api/v1/starter/plan", json={"goal": goal})).json()


async def test_goal_is_a_first_class_project_property(auth_client: AsyncClient):
    plan = await _plan(auth_client, "Smooth my spectra")
    created = await auth_client.post(
        "/api/v1/projects", json={"name": "Smoothing", "goal": "Smooth my spectra", "goal_plan": plan}
    )
    assert created.status_code == 201
    detail = created.json()
    assert detail["goal"] == "Smooth my spectra"
    assert detail["goal_plan"]["intent"] == "preprocess"

    listed = (await auth_client.get("/api/v1/projects")).json()
    assert listed[0]["goal"] == "Smooth my spectra"

    new_plan = await _plan(auth_client, "Find the peaks")
    updated = await auth_client.patch(
        f"/api/v1/projects/{detail['id']}", json={"goal": "Find the peaks", "goal_plan": new_plan}
    )
    assert updated.status_code == 200
    assert updated.json()["goal_plan"]["intent"] == "peaks"

    cleared = await auth_client.patch(f"/api/v1/projects/{detail['id']}", json={"goal": None, "goal_plan": None})
    assert cleared.json()["goal"] is None
    assert cleared.json()["goal_plan"] is None


async def test_project_rejects_a_plan_with_unknown_actions(auth_client: AsyncClient):
    plan = await _plan(auth_client, "Smooth my spectra")
    plan["steps"][1]["action_id"] = "run_shell"
    response = await auth_client.post("/api/v1/projects", json={"name": "Bad", "goal": "x", "goal_plan": plan})
    assert response.status_code == 422


async def test_corrupt_stored_plan_does_not_break_project_reads(
    auth_client: AsyncClient, test_session: AsyncSession, test_user: User
):
    project = Project(user_id=test_user.id, name="Legacy", goal="smooth", goal_plan={"steps": "broken"})
    test_session.add(project)
    await test_session.commit()

    response = await auth_client.get(f"/api/v1/projects/{project.id}")
    assert response.status_code == 200
    assert response.json()["goal"] == "smooth"
    assert response.json()["goal_plan"] is None
    progress = await auth_client.get(f"/api/v1/starter/projects/{project.id}/progress")
    assert progress.status_code == 200
    assert progress.json()["next_step"] is None


async def test_goal_survives_project_archive_import(auth_client: AsyncClient):
    plan = await _plan(auth_client, "Find the peaks")
    snapshot = {
        "name": "Archived",
        "goal": "Find the peaks",
        "goal_plan": plan,
        "experiments": [],
        "workflows": [],
        "children": [],
    }
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("project.json", json.dumps(snapshot))
    buf.seek(0)

    response = await auth_client.post(
        "/api/v1/projects/import", files={"file": ("goal.spectrapy", buf, "application/zip")}
    )
    assert response.status_code == 201
    assert response.json()["goal"] == "Find the peaks"
    assert response.json()["goal_plan"]["intent"] == "peaks"


async def test_import_drops_an_invalid_plan_but_keeps_the_goal(auth_client: AsyncClient):
    snapshot = {"name": "Old", "goal": "smooth", "goal_plan": {"bad": True}, "experiments": [], "workflows": []}
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("project.json", json.dumps(snapshot))
    buf.seek(0)

    response = await auth_client.post(
        "/api/v1/projects/import", files={"file": ("old.spectrapy", buf, "application/zip")}
    )
    assert response.status_code == 201
    assert response.json()["goal"] == "smooth"
    assert response.json()["goal_plan"] is None


async def test_progress_tracks_the_project_journey(
    auth_client: AsyncClient, test_session: AsyncSession, test_user: User
):
    plan = await _plan(auth_client, "Smooth my spectra")
    project_id = (
        await auth_client.post("/api/v1/projects", json={"name": "Journey", "goal": "Smooth", "goal_plan": plan})
    ).json()["id"]
    url = f"/api/v1/starter/projects/{project_id}/progress"

    progress = (await auth_client.get(url)).json()
    assert progress["has_project"] is True
    assert progress["has_data"] is False
    assert progress["next_step"] == "data"

    test_session.add(ProjectDataSource(project_id=project_id, display_name="Spectra", source_type="experiment"))
    workflow = Workflow(user_id=test_user.id, project_id=project_id, name="Sheet")
    test_session.add(workflow)
    await test_session.flush()
    test_session.add(WorkflowNode(workflow_id=workflow.id, node_id="load", node_type="data.file_load"))
    await test_session.commit()

    progress = (await auth_client.get(url)).json()
    assert progress["has_data"] is True
    assert progress["has_workflow"] is True
    assert progress["has_preprocessing"] is False
    assert progress["next_step"] == "configure"

    test_session.add(WorkflowNode(workflow_id=workflow.id, node_id="smooth", node_type="preprocess.smooth"))
    test_session.add(
        ExecutionRun(
            project_id=project_id,
            workflow_id=workflow.id,
            user_id=test_user.id,
            name="Run 1",
            status="completed",
            params_snapshot={},
            results_summary={},
            executed_at=datetime.now(timezone.utc),
        )
    )
    await test_session.commit()

    progress = (await auth_client.get(url)).json()
    assert progress["has_preprocessing"] is True
    assert progress["has_executed"] is True
    assert progress["next_step"] == "review"


async def test_progress_requires_project_access(auth_client: AsyncClient, test_session: AsyncSession):
    other = User(username="someone-else")
    test_session.add(other)
    await test_session.flush()
    project = Project(user_id=other.id, name="Private")
    test_session.add(project)
    await test_session.commit()

    response = await auth_client.get(f"/api/v1/starter/projects/{project.id}/progress")
    assert response.status_code == 404


async def test_classifier_reported_unavailable_is_not_called(ai_consent, auth_client: AsyncClient):
    calls: list[str] = []

    async def classifier(*, goal, **_kwargs):
        calls.append(goal)
        return GoalClassification(intent="calibrate", confidence=0.9)

    set_goal_classifier(classifier, is_available=lambda: False)
    assert (await auth_client.get("/api/v1/starter")).json()["model_planning_available"] is False
    plan = (await auth_client.post("/api/v1/starter/plan", json={"goal": "How wet is my grain?"})).json()
    assert plan["source"] == "rules"
    assert calls == []

    def broken() -> bool:
        raise RuntimeError("engine probe failed")

    set_goal_classifier(classifier, is_available=broken)
    assert (await auth_client.get("/api/v1/starter")).json()["model_planning_available"] is False


async def test_goal_is_not_sent_to_a_model_without_ai_disclosure_consent(auth_client: AsyncClient, monkeypatch):
    from spectra_sherpa.app.api.v1.routes import starter as starter_routes

    calls: list[str] = []

    async def classifier(*, goal, **_kwargs):
        calls.append(goal)
        return GoalClassification(intent="calibrate", confidence=0.9)

    async def deny(user, permission, **_kwargs):
        assert permission == "allow_llm_chat"
        return False

    set_goal_classifier(classifier)
    monkeypatch.setattr(starter_routes, "check_egress_permission", deny)
    assert (await auth_client.get("/api/v1/starter")).json()["model_planning_available"] is False
    plan = (await auth_client.post("/api/v1/starter/plan", json={"goal": "How wet is my grain?"})).json()
    assert plan["source"] == "rules"
    assert calls == []


async def _journey_to_run(client: AsyncClient, session: AsyncSession, user: User, goal: str) -> tuple[int, Workflow]:
    plan = await _plan(client, goal)
    project_id = (await client.post("/api/v1/projects", json={"name": goal, "goal": goal, "goal_plan": plan})).json()[
        "id"
    ]
    session.add(ProjectDataSource(project_id=project_id, display_name="Spectra", source_type="experiment"))
    workflow = Workflow(user_id=user.id, project_id=project_id, name="Sheet")
    session.add(workflow)
    await session.flush()
    session.add(WorkflowNode(workflow_id=workflow.id, node_id="smooth", node_type="preprocess.smooth"))
    await session.commit()
    return project_id, workflow


def _run(project_id: int, workflow: Workflow, user: User, status: str, name: str) -> ExecutionRun:
    return ExecutionRun(
        project_id=project_id,
        workflow_id=workflow.id,
        user_id=user.id,
        name=name,
        status=status,
        params_snapshot={},
        results_summary={},
        executed_at=datetime.now(timezone.utc),
    )


@pytest.mark.parametrize("status", ["running", "pending", "partial", "error", "failed", "cancelled"])
async def test_an_unsuccessful_run_does_not_count_as_running_the_workflow(
    auth_client: AsyncClient, test_session: AsyncSession, test_user: User, status
):
    project_id, workflow = await _journey_to_run(auth_client, test_session, test_user, "Smooth my spectra")
    test_session.add(_run(project_id, workflow, test_user, status, "Attempt"))
    await test_session.commit()

    progress = (await auth_client.get(f"/api/v1/starter/projects/{project_id}/progress")).json()
    assert progress["has_executed"] is False
    assert progress["last_run_status"] == status
    assert progress["next_step"] == "run"


async def test_a_completed_run_after_a_failure_counts(
    auth_client: AsyncClient, test_session: AsyncSession, test_user: User
):
    project_id, workflow = await _journey_to_run(auth_client, test_session, test_user, "Smooth my spectra")
    test_session.add(_run(project_id, workflow, test_user, "failed", "First"))
    await test_session.commit()
    test_session.add(_run(project_id, workflow, test_user, "completed", "Second"))
    await test_session.commit()

    progress = (await auth_client.get(f"/api/v1/starter/projects/{project_id}/progress")).json()
    assert progress["has_executed"] is True
    assert progress["last_run_status"] == "completed"
    assert progress["next_step"] == "review"


async def test_review_is_done_only_when_the_user_marks_it(
    auth_client: AsyncClient, test_session: AsyncSession, test_user: User
):
    project_id, workflow = await _journey_to_run(
        auth_client, test_session, test_user, "Build a PLS model that predicts moisture"
    )
    test_session.add(_run(project_id, workflow, test_user, "completed", "Fit"))
    test_session.add(
        ModelArtifact(
            user_id=test_user.id,
            project_id=project_id,
            name="Moisture PLS",
            artifact_uid="00000000-0000-0000-0000-000000000001",
            node_id="pls",
            model_type="pls",
            artifact_dir="models/moisture",
            integrity_hash="0" * 64,
            n_features=10,
        )
    )
    await test_session.commit()
    base = f"/api/v1/starter/projects/{project_id}"

    progress = (await auth_client.get(f"{base}/progress")).json()
    assert progress["has_model"] is True
    assert progress["next_step"] == "review"

    done = await auth_client.post(f"{base}/steps/review/complete")
    assert done.status_code == 200
    assert done.json()["next_step"] is None
    project = (await auth_client.get(f"/api/v1/projects/{project_id}")).json()
    assert project["goal_plan"]["completed_steps"] == ["review"]

    again = await auth_client.post(f"{base}/steps/review/complete")
    assert again.json()["next_step"] is None
    reopened = await auth_client.delete(f"{base}/steps/review/complete")
    assert reopened.json()["next_step"] == "review"
    project = (await auth_client.get(f"/api/v1/projects/{project_id}")).json()
    assert project["goal_plan"]["completed_steps"] == []


async def test_observed_steps_and_unknown_steps_cannot_be_marked(
    auth_client: AsyncClient, test_session: AsyncSession, test_user: User
):
    project_id, _workflow = await _journey_to_run(auth_client, test_session, test_user, "Smooth my spectra")
    base = f"/api/v1/starter/projects/{project_id}/steps"
    assert (await auth_client.post(f"{base}/run/complete")).status_code == 409
    assert (await auth_client.post(f"{base}/celebrate/complete")).status_code == 404

    plain = (await auth_client.post("/api/v1/projects", json={"name": "No plan"})).json()["id"]
    assert (await auth_client.post(f"/api/v1/starter/projects/{plain}/steps/review/complete")).status_code == 409


async def test_marking_a_step_requires_project_access(auth_client: AsyncClient, test_session: AsyncSession):
    other = User(username="not-the-owner")
    test_session.add(other)
    await test_session.flush()
    project = Project(user_id=other.id, name="Private", goal="x")
    test_session.add(project)
    await test_session.commit()
    response = await auth_client.post(f"/api/v1/starter/projects/{project.id}/steps/review/complete")
    assert response.status_code == 404
