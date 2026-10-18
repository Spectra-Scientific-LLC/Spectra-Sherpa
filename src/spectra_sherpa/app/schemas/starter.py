"""Schemas for the Starter goal planner and project goals."""

from __future__ import annotations

from typing import Literal, get_args

from pydantic import BaseModel, ConfigDict, Field, field_validator

from spectra_sherpa.app.lib.starter_goal import (
    DATASET_OPTION_LIMIT,
    GOAL_MAX_LENGTH,
    PROGRESS_SIGNALS,
    STARTER_PLAN_SCHEMA,
    STEP_ACTIONS,
    normalize_goal,
)

StarterPlanSchema = Literal["spectra-starter-plan/1"]
ProgressSignal = Literal["has_project", "has_data", "has_workflow", "has_preprocessing", "has_executed", "has_model"]
if set(get_args(ProgressSignal)) != set(PROGRESS_SIGNALS):  # pragma: no cover - import-time drift guard
    raise RuntimeError("Starter progress signals drifted from the planner")
if get_args(StarterPlanSchema) != (STARTER_PLAN_SCHEMA,):  # pragma: no cover - import-time drift guard
    raise RuntimeError("Starter plan schema drifted from the planner")


class StarterStep(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: str = Field(..., min_length=1, max_length=40)
    title: str = Field(..., min_length=1, max_length=160)
    detail: str = Field("", max_length=600)
    action_id: str | None = Field(None, max_length=64)
    completion: ProgressSignal | None = None

    @field_validator("action_id")
    @classmethod
    def _known_action(cls, value: str | None) -> str | None:
        if value is not None and value not in STEP_ACTIONS:
            raise ValueError(f"Unknown Starter action {value!r}")
        return value


class StarterDatasetOption(BaseModel):
    """A dataset the plan can start from: a reference or one of the user's own."""

    model_config = ConfigDict(extra="forbid")

    key: str = Field(..., min_length=1, max_length=300)
    label: str = Field(..., min_length=1, max_length=255)
    kind: Literal["reference", "experiment"]
    source: str | None = Field(None, max_length=40)
    technique: str | None = Field(None, max_length=60)
    availability: str | None = Field(None, max_length=60)
    experiment_id: int | None = Field(None, gt=0)


class StarterDatasetChoice(StarterDatasetOption):
    reason: str = Field("", max_length=240)
    chosen_by: Literal["rules", "model", "default"] = "rules"


class StarterPlan(BaseModel):
    """A goal turned into ordered steps; stored on the project as ``goal_plan``."""

    model_config = ConfigDict(extra="forbid")

    schema_version: StarterPlanSchema = "spectra-starter-plan/1"
    goal: str = Field(..., min_length=1, max_length=GOAL_MAX_LENGTH)
    intent: str = Field(..., min_length=1, max_length=40)
    intent_label: str = Field(..., min_length=1, max_length=120)
    summary: str = Field("", max_length=240)
    confidence: float = Field(..., ge=0.0, le=1.0)
    source: Literal["rules", "model"] = "rules"
    template_slug: str | None = Field(None, max_length=100)
    template_name: str | None = Field(None, max_length=255)
    steps: list[StarterStep] = Field(..., min_length=1, max_length=12)
    dataset: StarterDatasetChoice | None = None
    dataset_options: list[StarterDatasetOption] = Field(default_factory=list, max_length=DATASET_OPTION_LIMIT)


class StarterPlanRequest(BaseModel):
    goal: str = Field(..., min_length=1, max_length=GOAL_MAX_LENGTH * 2)

    @field_validator("goal")
    @classmethod
    def _non_blank(cls, value: str) -> str:
        normalized = normalize_goal(value)
        if not normalized:
            raise ValueError("Describe what you want to do")
        return normalized


class StarterExample(BaseModel):
    intent: str
    label: str
    goal: str


class StarterOverview(BaseModel):
    is_first_run: bool
    suggested_goal: str
    last_goal: str | None = None
    examples: list[StarterExample]
    model_planning_available: bool = False


class StarterProgress(BaseModel):
    project_id: int
    has_project: bool = True
    has_data: bool = False
    has_workflow: bool = False
    has_preprocessing: bool = False
    has_executed: bool = False
    has_model: bool = False
    next_step: str | None = None


def stored_goal_plan(value: object) -> StarterPlan | None:
    """Read a stored or imported plan, dropping one that no longer validates.

    Plans come from older releases and from project archives, so an invalid
    plan must not make the whole project unreadable or unimportable.
    """
    if not isinstance(value, dict):
        return None
    try:
        return StarterPlan.model_validate(value)
    except ValueError:
        return None


def imported_goal_fields(project_json: dict) -> dict[str, object]:
    """Goal fields to restore from a project snapshot or archive."""
    goal = project_json.get("goal")
    plan = stored_goal_plan(project_json.get("goal_plan"))
    return {
        "goal": normalize_goal(goal) or None if isinstance(goal, str) else None,
        "goal_plan": plan.model_dump() if plan is not None else None,
    }
