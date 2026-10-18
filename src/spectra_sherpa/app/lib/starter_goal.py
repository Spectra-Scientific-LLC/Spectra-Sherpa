"""Turn a beginner's goal, written in their own words, into a Starter plan.

The plan is deterministic: keywords pick one analysis intent, the intent
picks a starter template, and the steps are built only from Guidance
actions the frontend can execute. An optional planner registered through
``spectra_sherpa.app.contracts.starter_planning`` may reclassify the goal,
but it can only choose among the intents defined here, so every plan keeps
pointing at real product surfaces.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

STARTER_PLAN_SCHEMA = "spectra-starter-plan/1"
GOAL_MAX_LENGTH = 500

# Signals the Starter checklist and Guidance can observe for a project.
PROGRESS_SIGNALS = (
    "has_project",
    "has_data",
    "has_workflow",
    "has_preprocessing",
    "has_executed",
    "has_model",
)

# Every plan has these steps, in this order.
STEP_KEYS = ("project", "data", "workflow", "configure", "run", "review")

# Guidance action ids a Starter step may point at. Each one exists in both
# the frontend and server Guidance action ontologies.
STEP_ACTIONS = frozenset(
    {
        "import_data",
        "open_data_explore",
        "open_workflow",
        "add_preprocessing",
        "run_workflow",
        "view_results",
        "explain_latest_results",
    }
)


@dataclass(frozen=True)
class StarterIntent:
    key: str
    label: str
    summary: str
    template_slugs: tuple[str, ...]
    keywords: tuple[str, ...]
    example_goal: str
    configure_title: str
    configure_detail: str
    review_detail: str


STARTER_INTENTS: tuple[StarterIntent, ...] = (
    StarterIntent(
        key="preprocess",
        label="Clean up and transform spectra",
        summary="Smooth noise, correct the baseline and normalize spectra so samples can be compared.",
        template_slugs=("preprocessing", "msc_reference_correction"),
        keywords=(
            "smooth",
            "savitzky",
            "golay",
            "noise",
            "denois",
            "baseline",
            "snv",
            "msc",
            "normaliz",
            "derivative",
            "transform",
            "clean",
            "preprocess",
            "pre-process",
            "correct",
            "scatter",
            "fluorescen",
            "cosmic",
            "spike",
            "background",
        ),
        example_goal="Smooth my spectra and correct the baseline so I can compare samples",
        configure_title="Review the smoothing and baseline settings",
        configure_detail=(
            "Open each preprocessing step to see what it changes. Smoothing reduces noise, baseline "
            "correction removes slow background drift and normalization puts spectra on a common scale. "
            "The defaults are a reasonable first pass."
        ),
        review_detail=(
            "Compare the raw and processed spectra in the run results. Noise should be lower and the "
            "baselines flatter, with the peaks you care about still in place."
        ),
    ),
    StarterIntent(
        key="explore",
        label="Explore and compare samples",
        summary="Get an overview of how samples differ and spot outliers with PCA.",
        template_slugs=("pca",),
        keywords=(
            "explore",
            "overview",
            "pca",
            "principal",
            "outlier",
            "compare",
            "differ",
            "similar",
            "variation",
            "trend",
            "visuali",
            "look at",
            "understand",
        ),
        example_goal="Explore my data and find samples that look different from the rest",
        configure_title="Check the preprocessing and scaling",
        configure_detail=(
            "PCA is sensitive to scaling. The starter applies a sensible default; keep it for the first "
            "run and come back to it once you have seen the scores plot."
        ),
        review_detail=(
            "In the scores plot, samples close together have similar spectra. Points far from the main "
            "group are candidate outliers worth a second look."
        ),
    ),
    StarterIntent(
        key="peaks",
        label="Find and measure peaks",
        summary="Detect peaks and report their positions, heights and widths.",
        template_slugs=("peaks",),
        keywords=("peak", "band", "maxima", "position", "height", "width", "find lines", "line list"),
        example_goal="Find the peaks in my spectra and list their positions",
        configure_title="Adjust the peak detection threshold",
        configure_detail=(
            "Prominence controls how strong a peak must be to count. Raise it if small noise bumps are "
            "detected; lower it if real peaks are missed."
        ),
        review_detail="Check the peak table against the plot and confirm that the expected peaks were found.",
    ),
    StarterIntent(
        key="calibrate",
        label="Predict a value from spectra",
        summary="Build a PLS calibration that predicts a measured property such as concentration.",
        template_slugs=("pls_calibration",),
        keywords=(
            "predict",
            "calibrat",
            "concentration",
            "quantif",
            "pls",
            "regression",
            "content",
            "amount",
            "measure",
        ),
        example_goal="Build a model that predicts concentration from my spectra",
        configure_title="Choose the value to predict",
        configure_detail=(
            "A calibration needs a reference value for each sample, such as a lab-measured concentration. "
            "Pick that column as the target before running."
        ),
        review_detail=(
            "Look at the prediction error on held-out samples (RMSEP) and the predicted-versus-measured "
            "plot. Points close to the diagonal mean good predictions."
        ),
    ),
    StarterIntent(
        key="classify",
        label="Sort samples into known classes",
        summary="Train a PLS-DA classifier that assigns samples to known categories.",
        template_slugs=("classification_plsda",),
        keywords=(
            "classif",
            "discriminat",
            "categor",
            "class",
            "authentic",
            "identify which",
            "pass/fail",
            "plsda",
            "pls-da",
            "label",
        ),
        example_goal="Classify my samples into their known groups",
        configure_title="Choose the class label column",
        configure_detail=(
            "Classification learns from samples whose class is already known. Pick the column that holds "
            "each sample's class before running."
        ),
        review_detail="Check the confusion matrix: the diagonal shows correct predictions for each class.",
    ),
    StarterIntent(
        key="cluster",
        label="Group similar samples",
        summary="Find natural groupings in the data without labels.",
        template_slugs=("clustering_comparison", "hierarchical_clustering"),
        keywords=("cluster", "group", "segment", "k-means", "kmeans", "unsupervised"),
        example_goal="Group my samples into clusters of similar spectra",
        configure_title="Choose how many groups to look for",
        configure_detail=(
            "Clustering needs a target number of groups. Start with a small number and compare the "
            "results with what you know about the samples."
        ),
        review_detail="Check whether the groups match what you know about the samples.",
    ),
    StarterIntent(
        key="resolve",
        label="Separate mixture components",
        summary="Resolve mixture spectra into pure-component spectra and their amounts.",
        template_slugs=("mcr_als", "nmf_mixture_decomposition"),
        keywords=("mixture", "component", "unmix", "resolve", "mcr", "pure", "decompos", "deconvol"),
        example_goal="Separate my mixture spectra into their pure components",
        configure_title="Set the number of components",
        configure_detail=(
            "Curve resolution needs to know how many components to look for. Use the number of "
            "substances you expect in the mixtures."
        ),
        review_detail="Compare the resolved spectra with known reference spectra where you have them.",
    ),
)

_INTENTS_BY_KEY = {intent.key: intent for intent in STARTER_INTENTS}
DEFAULT_INTENT_KEY = "explore"
SUGGESTED_FIRST_GOAL = STARTER_INTENTS[0].example_goal
_RAMAN_PATTERN = re.compile(r"\braman\b", re.IGNORECASE)


def intent_by_key(key: str | None) -> StarterIntent | None:
    return _INTENTS_BY_KEY.get(key or "")


def normalize_goal(goal: str) -> str:
    """Collapse whitespace and bound the goal to the stored length."""
    return " ".join(str(goal or "").split())[:GOAL_MAX_LENGTH]


@dataclass(frozen=True)
class IntentMatch:
    intent: StarterIntent
    confidence: float
    matched_terms: tuple[str, ...]


# An explicitly named method decides the intent before any keyword counting.
# Order matters: specific names come before the names they contain, so
# "PLS-DA" is classification even though it contains "PLS".
_METHOD_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\bpls[\s-]?da\b"), "classify"),
    (re.compile(r"\bsimca\b"), "classify"),
    (re.compile(r"\bk[\s-]?nn\b|\bk[\s-]nearest\b"), "classify"),
    (re.compile(r"\bmcr(?:[\s-]?als)?\b"), "resolve"),
    (re.compile(r"\bnmf\b"), "resolve"),
    (re.compile(r"\bk[\s-]?means\b"), "cluster"),
    (re.compile(r"\bpca\b|\bprincipal components?(?: analysis)?\b"), "explore"),
    (re.compile(r"\bpls(?:[\s-]?r)?\b|\bpartial least squares\b"), "calibrate"),
    (re.compile(r"\bsavitzky[\s-]?golay\b|\bsnv\b|\bmsc\b"), "preprocess"),
)
METHOD_CONFIDENCE = 0.95


def classify_goal(goal: str) -> IntentMatch:
    """Pick the intent for the goal text.

    A named method ("PLS-DA", "PCA", "MCR-ALS") decides the intent at high
    confidence. Otherwise the intent with the most keyword hits wins; ties go
    to the earlier intent, so beginner-friendly preprocessing wins over
    specialist methods. With no hit the plan falls back to exploration,
    which works for any dataset, at low confidence.
    """
    text = normalize_goal(goal).lower()
    for pattern, intent_key in _METHOD_PATTERNS:
        method = pattern.search(text)
        if method:
            return IntentMatch(
                intent=_INTENTS_BY_KEY[intent_key], confidence=METHOD_CONFIDENCE, matched_terms=(method.group(0),)
            )
    best: IntentMatch | None = None
    for intent in STARTER_INTENTS:
        terms = tuple(keyword for keyword in intent.keywords if keyword in text)
        if not terms:
            continue
        if best is None or len(terms) > len(best.matched_terms):
            confidence = min(0.95, 0.6 + 0.1 * len(terms))
            best = IntentMatch(intent=intent, confidence=confidence, matched_terms=terms)
    if best is not None:
        return best
    return IntentMatch(intent=_INTENTS_BY_KEY[DEFAULT_INTENT_KEY], confidence=0.3, matched_terms=())


def preferred_template_slugs(intent: StarterIntent, goal: str) -> tuple[str, ...]:
    """Template slugs to try in order; Raman preprocessing has its own starter."""
    if intent.key == "preprocess" and _RAMAN_PATTERN.search(goal or ""):
        return ("raman_processing", *intent.template_slugs)
    return intent.template_slugs


def _step(
    key: str,
    title: str,
    detail: str,
    *,
    action_id: str | None,
    completion: str | None,
) -> dict[str, Any]:
    if action_id is not None and action_id not in STEP_ACTIONS:
        raise ValueError(f"Unknown Starter action {action_id!r}")
    if completion is not None and completion not in PROGRESS_SIGNALS:
        raise ValueError(f"Unknown Starter progress signal {completion!r}")
    return {"key": key, "title": title, "detail": detail, "action_id": action_id, "completion": completion}


def build_steps(
    intent: StarterIntent,
    template_name: str | None,
    dataset: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    if dataset is None:
        data_detail = (
            "Import your own files, or use the suggested reference dataset to practise first. Check that "
            "each spectrum and its labels look right before moving on."
        )
    elif dataset.get("kind") == "experiment":
        data_detail = (
            f"Start from your dataset “{dataset['label']}”. Ready to Start adds it to the project; check that "
            "each spectrum and its labels look right before moving on."
        )
    elif dataset.get("availability") == "exact_user_acquisition_required":
        data_detail = (
            f"Start from “{dataset['label']}”. It needs the provider's original file, which you import on the "
            "Data page. Check that each spectrum and its labels look right before moving on."
        )
    else:
        data_detail = (
            f"Start from “{dataset['label']}”, which is bundled with the app, or import your own files instead. "
            "Check that each spectrum and its labels look right before moving on."
        )
    workflow_label = f"the {template_name} starter" if template_name else "a starter workflow"
    steps = [
        _step(
            "project",
            "Create a project for this goal",
            "Ready to Start creates a project that keeps your goal, data, workflow and results together.",
            action_id=None,
            completion="has_project",
        ),
        _step(
            "data",
            "Add your spectra",
            data_detail,
            action_id="import_data",
            completion="has_data",
        ),
        _step(
            "workflow",
            f"Open {workflow_label}",
            (
                "A workflow is a chain of processing steps. The starter is already wired up for this goal, "
                "so you only need to connect your data."
                if template_name
                else "Pick a template from the gallery that matches your goal and connect your data to it."
            ),
            action_id="open_workflow",
            completion="has_workflow",
        ),
        _step(
            "configure",
            intent.configure_title,
            intent.configure_detail,
            action_id="add_preprocessing" if intent.key == "preprocess" else "open_workflow",
            completion="has_preprocessing" if intent.key == "preprocess" else None,
        ),
        _step(
            "run",
            "Run the workflow",
            "Running applies every step to your data and saves the results as a run you can come back to.",
            action_id="run_workflow",
            completion="has_executed",
        ),
        _step(
            "review",
            "Review the results",
            intent.review_detail,
            action_id="view_results",
            # Saving a model is not evidence that anyone looked at its
            # validation; the user marks this step done themselves.
            completion=None,
        ),
    ]
    return steps


def build_plan(
    goal: str,
    *,
    intent: StarterIntent,
    confidence: float,
    template_slug: str | None,
    template_name: str | None,
    source: str = "rules",
    summary: str | None = None,
    dataset: dict[str, Any] | None = None,
    dataset_options: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "schema_version": STARTER_PLAN_SCHEMA,
        "goal": normalize_goal(goal),
        "intent": intent.key,
        "intent_label": intent.label,
        "summary": summary or intent.summary,
        "confidence": round(float(confidence), 2),
        "source": source,
        "template_slug": template_slug,
        "template_name": template_name,
        "steps": build_steps(intent, template_name, dataset),
        "dataset": dataset,
        "dataset_options": list(dataset_options or []),
    }


def step_states(plan: dict[str, Any] | None, progress: dict[str, bool]) -> list[tuple[str, str]]:
    """Return ``(step_key, "done" | "current" | "todo")`` for each plan step.

    A step with a signal is done once the signal is observed. A step without
    one is done once the user marks it done (``completed_steps``) or once any
    later step is. The first step that is not done is current.
    """
    if not isinstance(plan, dict):
        return []
    steps = [step for step in plan.get("steps") or [] if isinstance(step, dict) and step.get("key")]
    marked = set(plan.get("completed_steps") or ())
    observed = [
        bool(progress.get(step["completion"], False)) if step.get("completion") else step["key"] in marked
        for step in steps
    ]
    states: list[tuple[str, str]] = []
    current_assigned = False
    for index, step in enumerate(steps):
        done = observed[index] or (not step.get("completion") and any(observed[index + 1 :]))
        if done:
            states.append((str(step["key"]), "done"))
        elif not current_assigned:
            states.append((str(step["key"]), "current"))
            current_assigned = True
        else:
            states.append((str(step["key"]), "todo"))
    return states


def next_step_key(plan: dict[str, Any] | None, progress: dict[str, bool]) -> str | None:
    """The step the user should do next, or ``None`` when the plan is finished."""
    for key, state in step_states(plan, progress):
        if state == "current":
            return key
    return None


def starter_examples() -> list[dict[str, str]]:
    return [{"intent": intent.key, "label": intent.label, "goal": intent.example_goal} for intent in STARTER_INTENTS]


# --- Dataset choice ---------------------------------------------------------

DATASET_OPTION_LIMIT = 6
_TOKEN_PATTERN = re.compile(r"[a-z0-9][a-z0-9\-]{2,}")
_STOPWORDS = frozenset(
    {
        "analyse",
        "analysis",
        "analyze",
        "and",
        "are",
        "can",
        "compare",
        "data",
        "dataset",
        "datasets",
        "find",
        "for",
        "file",
        "files",
        "from",
        "get",
        "got",
        "have",
        "help",
        "how",
        "instrument",
        "instruments",
        "into",
        "just",
        "like",
        "look",
        "make",
        "model",
        "mine",
        "measured",
        "measurement",
        "measurements",
        "my",
        "need",
        "new",
        "our",
        "out",
        "sample",
        "samples",
        "see",
        "set",
        "show",
        "some",
        "spectra",
        "spectrum",
        "start",
        "that",
        "the",
        "their",
        "them",
        "then",
        "these",
        "this",
        "use",
        "using",
        "want",
        "what",
        "which",
        "with",
        "would",
    }
)
_OWN_DATA_PATTERN = re.compile(
    r"\b(my own|our own|uploaded|imported|my files|my data|our data|my measurements)\b",
    re.IGNORECASE,
)


def goal_tokens(goal: str) -> tuple[str, ...]:
    """Content words in the goal that can name a dataset, technique or property."""
    words = _TOKEN_PATTERN.findall(normalize_goal(goal).lower())
    return tuple(dict.fromkeys(word for word in words if word not in _STOPWORDS))


def _dataset_text(candidate: dict[str, Any], *keys: str) -> str:
    return " ".join(str(candidate[key]) for key in keys if candidate.get(key)).lower()


def _dataset_rank(candidate: dict[str, Any], tokens: tuple[str, ...], own_data: bool) -> tuple[float, tuple[str, ...]]:
    """Score a candidate; a word in its name counts fully, one only in its description by half.

    ``matched`` is empty unless the matches add up to at least one full
    word, so a single generic word in a long description does not count as
    the goal naming that dataset.
    """
    title = _dataset_text(candidate, "label", "name", "technique")
    description = _dataset_text(candidate, "description")
    matches = [(token, 1.0 if token in title else 0.5) for token in tokens if token in title or token in description]
    score = sum(weight for _token, weight in matches)
    matched = tuple(token for token, _weight in matches) if score >= 1.0 else ()
    if not matched:
        score = 0.0
    technique = str(candidate.get("technique") or "").lower()
    if technique and technique in tokens:
        score += 2.0
    if candidate.get("kind") == "experiment":
        # The user's own data wins ties, and wins outright when they say so.
        score += 0.25 + (1.5 if own_data else 0.0)
    elif candidate.get("availability") == "exact_user_acquisition_required":
        # Provider datasets need a separate download before they can run.
        score -= 0.5
    return score, matched


def dataset_option(candidate: dict[str, Any]) -> dict[str, Any]:
    return {
        "key": str(candidate["key"]),
        "label": str(candidate.get("label") or candidate["key"])[:255],
        "kind": candidate.get("kind", "reference"),
        "source": str(candidate.get("source") or "")[:40] or None,
        "technique": str(candidate.get("technique") or "")[:60] or None,
        "availability": candidate.get("availability"),
        "experiment_id": candidate.get("experiment_id"),
    }


def choose_dataset(
    goal: str,
    candidates: list[dict[str, Any]],
    intent_key: str,
) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    """Pick the dataset to start with and the alternatives to offer.

    ``candidates`` carry ``key``, ``label``, ``kind`` (``reference`` or
    ``experiment``) and, for references, the intents they ``support``. Only
    the user's own datasets and references compatible with the intent's
    starter are eligible.
    """
    eligible = [
        candidate
        for candidate in candidates
        if candidate.get("kind") == "experiment" or intent_key in (candidate.get("supports") or ())
    ]
    if not eligible:
        return None, []
    tokens = goal_tokens(goal)
    own_data = bool(_OWN_DATA_PATTERN.search(goal or ""))
    ranked = sorted(
        ((candidate, *_dataset_rank(candidate, tokens, own_data)) for candidate in eligible),
        key=lambda item: -item[1],
    )
    best, score, matched = ranked[0]
    if matched or (own_data and best.get("kind") == "experiment"):
        if matched:
            reason = "Matches " + ", ".join(f"“{term}”" for term in matched[:3]) + " in your goal."
        else:
            reason = "Your own most recent dataset, as your goal asks."
        chosen_by = "rules"
    else:
        practice = [item for item in ranked if item[0].get("availability") == "distributed_reference"]
        best = (practice or ranked)[0][0]
        reason = (
            "Nothing in your goal names a dataset, so this practice dataset that works with the starter is suggested."
        )
        chosen_by = "default"
    choice = {**dataset_option(best), "reason": reason, "chosen_by": chosen_by}
    options = [dataset_option(item[0]) for item in ranked if item[0] is not best][: DATASET_OPTION_LIMIT - 1]
    return choice, [dataset_option(best), *options]
