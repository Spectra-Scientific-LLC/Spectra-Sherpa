"""Starter goal planner: keyword intents, plan shape and step progress."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from spectra_sherpa.app.lib.starter_goal import (
    GOAL_MAX_LENGTH,
    STARTER_INTENTS,
    STEP_ACTIONS,
    STEP_KEYS,
    SUGGESTED_FIRST_GOAL,
    build_plan,
    choose_dataset,
    classify_goal,
    intent_by_key,
    next_step_key,
    normalize_goal,
    preferred_template_slugs,
    step_states,
)
from spectra_sherpa.app.schemas.projects import ProjectCreate
from spectra_sherpa.app.schemas.starter import StarterPlan, imported_goal_fields, stored_goal_plan


@pytest.mark.parametrize(
    ("goal", "intent"),
    [
        ("Smooth my spectra and correct the baseline so I can compare samples", "preprocess"),
        ("apply a Savitzky-Golay filter and SNV transform", "preprocess"),
        ("Find the peaks in my spectra and list their positions", "peaks"),
        ("Build a model that predicts concentration", "calibrate"),
        ("classify olive oils as authentic or not", "classify"),
        ("group my samples into clusters", "cluster"),
        ("unmix the mixture into pure components", "resolve"),
        ("look for outliers with PCA", "explore"),
        ("Remove fluorescence and cosmic-ray spikes from my Raman spectra", "preprocess"),
    ],
)
def test_keywords_pick_the_matching_intent(goal, intent):
    match = classify_goal(goal)
    assert match.intent.key == intent
    assert match.matched_terms
    assert 0.6 < match.confidence <= 0.95


def test_unmatched_goal_falls_back_to_exploration_at_low_confidence():
    match = classify_goal("I just got my instrument")
    assert match.intent.key == "explore"
    assert match.matched_terms == ()
    assert match.confidence < 0.5


def test_suggested_goal_and_every_example_classify_to_their_own_intent():
    assert classify_goal(SUGGESTED_FIRST_GOAL).intent.key == "preprocess"
    for intent in STARTER_INTENTS:
        assert classify_goal(intent.example_goal).intent.key == intent.key, intent.key


def test_raman_preprocessing_prefers_the_raman_starter():
    intent = intent_by_key("preprocess")
    assert preferred_template_slugs(intent, "remove cosmic rays from Raman spectra")[0] == "raman_processing"
    assert preferred_template_slugs(intent, "smooth NIR spectra")[0] == "preprocessing"


def test_goal_is_normalized_and_bounded():
    assert normalize_goal("  smooth \n\t my   spectra ") == "smooth my spectra"
    assert len(normalize_goal("x" * (GOAL_MAX_LENGTH + 50))) == GOAL_MAX_LENGTH


@pytest.mark.parametrize("intent", STARTER_INTENTS, ids=lambda intent: intent.key)
def test_every_plan_validates_and_uses_only_executable_actions(intent):
    plan = build_plan(
        intent.example_goal,
        intent=intent,
        confidence=0.8,
        template_slug=intent.template_slugs[0],
        template_name="Starter",
    )
    validated = StarterPlan.model_validate(plan)
    assert tuple(step.key for step in validated.steps) == STEP_KEYS
    assert {step.action_id for step in validated.steps if step.action_id} <= STEP_ACTIONS


def test_plan_without_a_template_points_at_the_gallery():
    intent = intent_by_key("explore")
    plan = build_plan("explore", intent=intent, confidence=0.3, template_slug=None, template_name=None)
    workflow = next(step for step in plan["steps"] if step["key"] == "workflow")
    assert workflow["title"] == "Open a starter workflow"
    assert "gallery" in workflow["detail"]


def _plan(intent_key: str) -> dict:
    intent = intent_by_key(intent_key)
    return build_plan(intent.example_goal, intent=intent, confidence=0.8, template_slug=None, template_name=None)


def test_step_states_follow_observed_progress():
    plan = _plan("preprocess")
    progress = {"has_project": True, "has_data": True}
    assert step_states(plan, progress) == [
        ("project", "done"),
        ("data", "done"),
        ("workflow", "current"),
        ("configure", "todo"),
        ("run", "todo"),
        ("review", "todo"),
    ]
    assert next_step_key(plan, progress) == "workflow"


def test_unobservable_step_counts_as_done_once_a_later_step_is():
    plan = _plan("explore")
    progress = {"has_project": True, "has_data": True, "has_workflow": True}
    assert next_step_key(plan, progress) == "configure"
    progress["has_executed"] = True
    assert dict(step_states(plan, progress))["configure"] == "done"
    assert next_step_key(plan, progress) == "review"


def test_saving_a_model_does_not_complete_the_review_step():
    plan = _plan("calibrate")
    progress = dict.fromkeys(
        ("has_project", "has_data", "has_workflow", "has_preprocessing", "has_executed", "has_model"), True
    )
    assert next_step_key(plan, progress) == "review"
    review = next(step for step in plan["steps"] if step["key"] == "review")
    assert review["completion"] is None
    plan["completed_steps"] = ["review"]
    assert next_step_key(plan, progress) is None
    assert next_step_key(None, progress) is None


def test_only_manual_steps_can_be_marked_done():
    plan = _plan("calibrate")
    plan["completed_steps"] = ["review", "configure"]
    assert StarterPlan.model_validate(plan).completed_steps == ["review", "configure"]
    plan["completed_steps"] = ["run"]
    with pytest.raises(ValidationError):
        StarterPlan.model_validate(plan)
    plan["completed_steps"] = ["review", "review"]
    with pytest.raises(ValidationError):
        StarterPlan.model_validate(plan)


@pytest.mark.parametrize(
    ("goal", "intent", "method"),
    [
        ("Run PLS-DA on my spectra", "classify", "pls-da"),
        ("plsda model for the two olive grades", "classify", "plsda"),
        ("PLS DA classification", "classify", "pls da"),
        ("Build a PLS model for moisture", "calibrate", "pls"),
        ("PLS regression of fat content", "calibrate", "pls"),
        ("Do a PCA and then cluster", "explore", "pca"),
        ("MCR-ALS on my reaction spectra", "resolve", "mcr-als"),
        ("k-means on NIR spectra", "cluster", "k-means"),
        ("SNV then smooth", "preprocess", "snv"),
    ],
)
def test_named_methods_take_precedence_over_keyword_counts(goal, intent, method):
    match = classify_goal(goal)
    assert match.intent.key == intent
    assert match.matched_terms == (method,)
    assert match.confidence == 0.95


def test_method_names_do_not_match_inside_other_words():
    # "pca" inside "pcap" and "pls" inside "plsx" are not method names.
    assert classify_goal("smooth the pcap traces").intent.key == "preprocess"
    assert classify_goal("smooth the plsx exports").matched_terms == ("smooth",)


def test_plan_schema_rejects_unknown_actions_and_signals():
    plan = _plan("preprocess")
    plan["steps"][1]["action_id"] = "delete_everything"
    with pytest.raises(ValidationError):
        StarterPlan.model_validate(plan)
    plan = _plan("preprocess")
    plan["steps"][1]["completion"] = "has_magic"
    with pytest.raises(ValidationError):
        StarterPlan.model_validate(plan)


def test_project_create_normalizes_goal_and_validates_plan():
    created = ProjectCreate(name="P", goal="  smooth   my spectra  ", goal_plan=_plan("preprocess"))
    assert created.goal == "smooth my spectra"
    assert created.goal_plan is not None and created.goal_plan.intent == "preprocess"
    assert ProjectCreate(name="P", goal="   ").goal is None


def test_stored_and_imported_plans_degrade_instead_of_failing():
    assert stored_goal_plan({"schema_version": "spectra-starter-plan/1"}) is None
    assert stored_goal_plan("not a plan") is None
    fields = imported_goal_fields({"goal": " smooth  spectra ", "goal_plan": {"steps": "broken"}})
    assert fields == {"goal": "smooth spectra", "goal_plan": None}
    fields = imported_goal_fields({"goal": 42, "goal_plan": _plan("peaks")})
    assert fields["goal"] is None
    assert fields["goal_plan"]["intent"] == "peaks"
    assert imported_goal_fields({}) == {"goal": None, "goal_plan": None}


_CANDIDATES = [
    {
        "key": "synthetic:ftir",
        "label": "Synthetic FTIR gas mixtures",
        "kind": "reference",
        "technique": "FTIR",
        "availability": "distributed_reference",
        "supports": ["preprocess", "explore", "resolve"],
    },
    {
        "key": "registered:corn",
        "label": "Eigenvector Corn M5",
        "kind": "reference",
        "technique": "NIR",
        "description": "Corn samples measured on three near-infrared instruments for calibration.",
        "availability": "exact_user_acquisition_required",
        "supports": ["calibrate", "explore"],
    },
    {
        "key": "sklearn:wine",
        "label": "Wine feature table",
        "kind": "reference",
        "technique": "ML/Statistics",
        "availability": "distributed_reference",
        "supports": ["classify", "explore"],
    },
    {"key": "experiment:7", "label": "Olive oil batch 3", "kind": "experiment", "experiment_id": 7},
]


def test_dataset_named_in_the_goal_is_chosen_with_a_reason():
    choice, options = choose_dataset("Predict moisture in corn from NIR spectra", _CANDIDATES, "calibrate")
    assert choice["key"] == "registered:corn"
    assert choice["chosen_by"] == "rules"
    assert "corn" in choice["reason"]
    assert options[0]["key"] == "registered:corn"
    # Datasets whose starter cannot run this intent are never offered.
    assert {option["key"] for option in options} == {"registered:corn", "experiment:7"}


def test_users_own_dataset_is_chosen_when_named_or_requested():
    choice, _ = choose_dataset("Explore my olive oil spectra", _CANDIDATES, "explore")
    assert choice["key"] == "experiment:7"
    assert choice["experiment_id"] == 7
    choice, _ = choose_dataset("Smooth the spectra I uploaded", _CANDIDATES, "preprocess")
    assert choice["key"] == "experiment:7"
    assert choice["chosen_by"] == "rules"


def test_unnamed_dataset_defaults_to_a_bundled_practice_dataset():
    choice, options = choose_dataset("Smooth and baseline correct", _CANDIDATES, "preprocess")
    assert choice["key"] == "synthetic:ftir"
    assert choice["chosen_by"] == "default"
    assert len(options) == 2


def test_no_eligible_dataset_leaves_the_choice_open():
    assert choose_dataset("cluster", _CANDIDATES[:1], "cluster") == (None, [])


def test_plan_steps_name_the_chosen_dataset():
    intent = intent_by_key("calibrate")
    choice, options = choose_dataset("Predict moisture in corn", _CANDIDATES, "calibrate")
    plan = build_plan(
        "Predict moisture in corn",
        intent=intent,
        confidence=0.8,
        template_slug="pls_calibration",
        template_name="PLS Calibration",
        dataset=choice,
        dataset_options=options,
    )
    validated = StarterPlan.model_validate(plan)
    assert validated.dataset.key == "registered:corn"
    data_step = next(step for step in validated.steps if step.key == "data")
    assert "Eigenvector Corn M5" in data_step.detail
    assert "provider's original file" in data_step.detail


def test_a_generic_word_in_a_description_does_not_name_a_dataset():
    candidates = [
        {
            "key": "registered:corn",
            "label": "Eigenvector Corn M5",
            "kind": "reference",
            "technique": "NIR",
            "description": "Corn samples measured on three near-infrared instruments.",
            "availability": "exact_user_acquisition_required",
            "supports": ["explore"],
        },
        {
            "key": "builtin:lavender",
            "label": "Lavender Essential Oil FTIR Corpus",
            "kind": "reference",
            "technique": "FTIR",
            "description": "Thirty-three FTIR spectra in three acquisition blocks.",
            "availability": "distributed_reference",
            "supports": ["explore"],
        },
    ]
    choice, _ = choose_dataset("I just got a new instrument and want to look around", candidates, "explore")
    assert choice["chosen_by"] == "default"
    assert choice["key"] == "builtin:lavender"
    # One description-only word is half a match; two make a full one.
    choice, _ = choose_dataset("three near-infrared", candidates, "explore")
    assert choice["key"] == "registered:corn"
    assert choice["chosen_by"] == "rules"
