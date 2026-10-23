"""Starter: turn a beginner's goal into a plan and track it per project."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from spectra_sherpa.app.api.deps import get_current_user, get_session, require_project
from spectra_sherpa.app.contracts.project_access import uses_managed_project_access
from spectra_sherpa.app.contracts.scientific_access import require_scientific_access, scientific_project_ids
from spectra_sherpa.app.contracts.starter_planning import classify_goal_with_model, goal_classifier_available
from spectra_sherpa.app.core.security import check_egress_permission
from spectra_sherpa.app.lib.dataset_compatibility import build_compatibility_matrix
from spectra_sherpa.app.lib.reference_artifacts import model_neutral_dataset_catalog
from spectra_sherpa.app.lib.starter_goal import (
    DATASET_OPTION_LIMIT,
    STARTER_INTENTS,
    SUGGESTED_FIRST_GOAL,
    build_plan,
    choose_dataset,
    classify_goal,
    dataset_option,
    intent_by_key,
    next_step_key,
    preferred_template_slugs,
    starter_examples,
)
from spectra_sherpa.app.lib.template_runtime import template_runtime_readiness
from spectra_sherpa.app.models.experiment import Experiment
from spectra_sherpa.app.models.experiment_file import ExperimentFile
from spectra_sherpa.app.models.project import Project
from spectra_sherpa.app.models.user import User
from spectra_sherpa.app.models.workflow import Workflow
from spectra_sherpa.app.models.workflow_template import WorkflowTemplate
from spectra_sherpa.app.schemas.starter import (
    StarterExample,
    StarterOverview,
    StarterPlan,
    StarterPlanRequest,
    StarterProgress,
    stored_goal_plan,
)
from spectra_sherpa.app.services.starter_disclosure import private_starter_context_allowed
from spectra_sherpa.app.services.starter_progress import latest_run_status, project_progress
from spectra_sherpa.app.services.template_availability import template_admitted_in_profile

router = APIRouter(prefix="/starter")

# Below this keyword confidence the deployment's model classifier, when one is
# registered, may replace the keyword intent. It can always suggest a dataset.
MODEL_CLASSIFIER_THRESHOLD = 0.7
EXPERIMENT_CANDIDATE_LIMIT = 12


async def _count(session: AsyncSession, statement) -> int:  # noqa: ANN001
    return int((await session.scalar(statement)) or 0)


async def _model_planning_allowed(session: AsyncSession, user: User) -> bool:
    """A model may read the goal only when one is registered and the user allows AI disclosure."""
    if not goal_classifier_available():
        return False
    from spectra_sherpa.app.core.mode_policy import is_local

    # Like local chat, an explicitly configured BYO endpoint may receive the
    # user's goal without enabling general egress. Private context is separate.
    return await check_egress_permission(user, "allow_llm_chat", session=session, skip_global_check=is_local())


@router.get("", response_model=StarterOverview)
async def get_starter_overview(
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> StarterOverview:
    """Return what the Starter tab needs before the user types anything."""
    project_count = await _count(session, select(func.count(Project.id)).where(Project.user_id == current_user.id))
    workflow_count = await _count(session, select(func.count(Workflow.id)).where(Workflow.user_id == current_user.id))
    last_goal = await session.scalar(
        select(Project.goal)
        .where(
            Project.user_id == current_user.id,
            Project.deleted_at.is_(None),
            Project.goal.is_not(None),
            Project.goal != "",
        )
        .order_by(Project.updated_at.desc(), Project.id.desc())
        .limit(1)
    )
    return StarterOverview(
        is_first_run=project_count == 0 and workflow_count == 0,
        suggested_goal=SUGGESTED_FIRST_GOAL,
        last_goal=last_goal,
        examples=[StarterExample(**example) for example in starter_examples()],
        model_planning_available=await _model_planning_allowed(session, current_user),
    )


def _ready_template(template: WorkflowTemplate | None) -> bool:
    if template is None or not template_admitted_in_profile(template):
        return False
    template_data = template.template_data if isinstance(template.template_data, dict) else {}
    return template_data.get("status") == "ready"


async def _starter_templates(session: AsyncSession, goal: str) -> dict[str, WorkflowTemplate | None]:
    """The first ready, profile-admitted starter template for every intent."""
    preferences = {intent.key: preferred_template_slugs(intent, goal) for intent in STARTER_INTENTS}
    slugs = {slug for candidates in preferences.values() for slug in candidates}
    result = await session.execute(
        select(WorkflowTemplate).where(WorkflowTemplate.slug.in_(slugs), WorkflowTemplate.is_active.is_(True))
    )
    by_slug = {template.slug: template for template in result.scalars().all()}
    return {
        key: next((by_slug[slug] for slug in candidates if _ready_template(by_slug.get(slug))), None)
        for key, candidates in preferences.items()
    }


def _reference_candidates(templates: dict[str, WorkflowTemplate | None]) -> list[dict]:
    """Reference datasets, each tagged with the intents whose starter accepts it."""
    unique = {template.slug: template for template in templates.values() if template is not None}
    if not unique:
        return []
    template_payloads = [
        {
            "slug": template.slug,
            "name": template.name,
            "status": "ready",
            "template_data": {**template.template_data, "status": "ready"},
            "runtime_readiness": template_runtime_readiness(template.template_data),
        }
        for template in unique.values()
    ]
    catalog = model_neutral_dataset_catalog()
    from spectra_sherpa.app.services.experiments import builtin_lavender_source_files

    if not builtin_lavender_source_files():
        catalog = [dataset for dataset in catalog if dataset.get("dataset_id") != "builtin:lavender-essential-oil-v1"]
    for dataset in catalog:
        dataset["key"] = dataset.get("dataset_id") or f"{dataset['source']}:{dataset['name']}"
    matrix = build_compatibility_matrix(
        [{"dataset_id": dataset["key"], "analysis_profile": dataset["analysis_profile"]} for dataset in catalog],
        template_payloads,
    )
    usable = {
        (decision["dataset_id"], decision["template_slug"])
        for decision in matrix
        if decision.get("compatible") and decision.get("can_use_as_primary")
    }
    candidates = []
    for dataset in catalog:
        supports = [
            key
            for key, template in templates.items()
            if template is not None and (dataset["key"], template.slug) in usable
        ]
        if supports:
            candidates.append(
                {
                    "key": dataset["key"],
                    "label": dataset.get("label") or dataset.get("name") or dataset["key"],
                    "name": dataset.get("name"),
                    "kind": "reference",
                    "source": dataset.get("source"),
                    "technique": dataset.get("technique"),
                    "description": dataset.get("description"),
                    "availability": dataset.get("availability"),
                    "supports": supports,
                }
            )
    return candidates


async def _experiment_candidates(session: AsyncSession, user: User) -> list[dict]:
    """The user's own recent datasets that hold files and belong to no project yet.

    Ready to Start adds the chosen dataset to the new project, and adding a
    dataset to a project moves it. Offering only unassigned datasets keeps
    Starter from taking data out of another project. Managed deployments keep
    every dataset inside an access-controlled project, so they offer none.
    """
    if await scientific_project_ids(session, user.id) is not None:
        return []
    with_files = select(ExperimentFile.experiment_id).distinct().scalar_subquery()
    result = await session.execute(
        select(Experiment)
        .where(
            Experiment.user_id == user.id,
            Experiment.project_id.is_(None),
            Experiment.id.in_(with_files),
        )
        .order_by(Experiment.updated_at.desc(), Experiment.id.desc())
        .limit(EXPERIMENT_CANDIDATE_LIMIT)
    )
    return [
        {
            "key": f"experiment:{experiment.id}",
            "label": experiment.name,
            "name": experiment.name,
            "kind": "experiment",
            "source": "experiment",
            "description": experiment.description,
            "experiment_id": experiment.id,
        }
        for experiment in result.scalars().all()
    ]


def _model_facing(candidate: dict) -> dict:
    """What the classifier may read about a dataset: names and descriptions only."""
    return {
        "key": candidate["key"],
        "label": candidate["label"],
        "kind": candidate["kind"],
        "technique": candidate.get("technique"),
        "description": (candidate.get("description") or "")[:200] or None,
        "supports": list(candidate.get("supports") or []),
    }


@router.post("/plan", response_model=StarterPlan)
async def plan_goal(
    payload: StarterPlanRequest,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> StarterPlan:
    """Turn a goal into ordered steps, a starter template and a dataset to begin with."""
    match = classify_goal(payload.goal)
    intent, confidence, source, summary = match.intent, match.confidence, "rules", None
    templates = await _starter_templates(session, payload.goal)
    candidates = [*await _experiment_candidates(session, current_user), *_reference_candidates(templates)]

    model_dataset: tuple[str, str | None] | None = None
    if await _model_planning_allowed(session, current_user):
        # Keep owned datasets available to local rules without automatically
        # disclosing their names/descriptions to an optional model provider.
        private_context = await private_starter_context_allowed(session, current_user.id)
        model_candidates = [
            candidate for candidate in candidates if candidate["kind"] == "reference" or private_context
        ]
        classification = await classify_goal_with_model(
            payload.goal,
            intents=[
                {"key": candidate.key, "label": candidate.label, "summary": candidate.summary}
                for candidate in STARTER_INTENTS
            ],
            datasets=[_model_facing(candidate) for candidate in model_candidates],
            user_id=int(current_user.id),
        )
        model_intent = intent_by_key(classification.intent) if classification else None
        if classification is not None and model_intent is not None:
            if match.confidence < MODEL_CLASSIFIER_THRESHOLD and classification.confidence > confidence:
                intent, confidence, source, summary = (
                    model_intent,
                    classification.confidence,
                    "model",
                    classification.summary,
                )
            if classification.dataset_key and model_intent.key == intent.key:
                model_dataset = (classification.dataset_key, classification.dataset_reason)

    dataset, options = choose_dataset(payload.goal, candidates, intent.key)
    if model_dataset is not None:
        chosen = next(candidate for candidate in candidates if candidate["key"] == model_dataset[0])
        dataset = {
            **dataset_option(chosen),
            "reason": model_dataset[1] or "Suggested by the assistant for this goal.",
            "chosen_by": "model",
        }
        options = [dataset_option(chosen), *[option for option in options if option["key"] != chosen["key"]]][
            :DATASET_OPTION_LIMIT
        ]

    template = templates.get(intent.key)
    return StarterPlan.model_validate(
        build_plan(
            payload.goal,
            intent=intent,
            confidence=confidence,
            template_slug=template.slug if template else None,
            template_name=template.name if template else None,
            source=source,
            summary=summary,
            dataset=dataset,
            dataset_options=options,
        )
    )


async def _progress_response(session: AsyncSession, project: Project) -> StarterProgress:
    progress = await project_progress(session, project.id)
    plan = stored_goal_plan(project.goal_plan)
    return StarterProgress(
        project_id=project.id,
        **progress,
        last_run_status=await latest_run_status(session, project.id),
        next_step=next_step_key(plan.model_dump() if plan else None, progress),
    )


@router.get("/projects/{project_id}/progress", response_model=StarterProgress)
async def get_project_progress(
    project_id: int,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> StarterProgress:
    """Report which Starter steps a project has already completed."""
    project = await require_project(project_id, current_user.id, session, operation="read")
    return await _progress_response(session, project)


async def _set_step_completed(
    project_id: int, step_key: str, completed: bool, session: AsyncSession, user: User
) -> StarterProgress:
    """Record that the user did, or undid, a step the app cannot observe."""
    if uses_managed_project_access():
        await require_scientific_access(session, user.id, project_id, "write")
        project = await session.get(Project, project_id)
        if project is None:
            raise HTTPException(404, "Project not found")
    else:
        project = await require_project(project_id, user.id, session)
    plan = stored_goal_plan(project.goal_plan)
    if plan is None:
        raise HTTPException(409, "This project has no Starter plan")
    step = next((candidate for candidate in plan.steps if candidate.key == step_key), None)
    if step is None:
        raise HTTPException(404, "Unknown Starter step")
    if step.completion is not None:
        raise HTTPException(409, "This step completes from project progress and cannot be marked by hand")

    marked = [key for key in plan.completed_steps if key != step_key]
    if completed:
        marked.append(step_key)
    if marked != plan.completed_steps:
        before = project.goal_plan
        updated = plan.model_copy(update={"completed_steps": marked})
        project.goal_plan = StarterPlan.model_validate(updated.model_dump()).model_dump()
        from spectra_sherpa.app.services.audit import audit_emitter

        audit_emitter.emit(
            session=session,
            action="project.updated",
            target_type="Project",
            target_id=project.id,
            before={"goal_plan": before},
            after={"goal_plan": project.goal_plan},
        )
        await session.commit()
        await session.refresh(project)
    return await _progress_response(session, project)


@router.post("/projects/{project_id}/steps/{step_key}/complete", response_model=StarterProgress)
async def complete_step(
    project_id: int,
    step_key: str,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> StarterProgress:
    """Mark a step without a progress signal, such as reviewing results, as done."""
    return await _set_step_completed(project_id, step_key, True, session, current_user)


@router.delete("/projects/{project_id}/steps/{step_key}/complete", response_model=StarterProgress)
async def reopen_step(
    project_id: int,
    step_key: str,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> StarterProgress:
    """Undo marking a step done."""
    return await _set_step_completed(project_id, step_key, False, session, current_user)
