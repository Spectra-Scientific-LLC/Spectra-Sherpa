"""One read-only comparison authority for retained and registered evidence.

Provider resolution is an authorization boundary, not scientific approval.
Here sample membership, fold separation and metric formulas are checked for
each role independently. No fitting or artifact application occurs here.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from itertools import combinations
from math import isfinite
from typing import Any

from spectra_sherpa.app.contracts.comparison_evidence import EvaluationEvidence, ResolvedComparisonEvidence
from spectra_sherpa.app.schemas.execution_runs import EvaluationSelection
from spectra_sherpa.app.schemas.scientific_comparison import (
    ComparisonEvidenceItem,
    EvidenceComparisonResponse,
    EvidenceOutputSelection,
    EvidenceReference,
    PopulationSummary,
    ScientificEvidencePair,
    ScientificSection,
    ScientificSectionComparison,
)
from spectra_sherpa.app.services.dag.out_of_fold_evidence import _normalized_split_plan
from spectra_sherpa.app.services.run_evaluation_comparison import _evaluation
from spectra_sherpa.sdk import validate as sdk_validate

ROLES = ("calibration", "training_cv", "held_out", "outlier_challenge")


def evidence_digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False, ensure_ascii=True).encode()
    ).hexdigest()


def run_evidence_reference(run: Any, selection: EvaluationSelection | None = None) -> EvidenceReference:
    """Bind an existing record's retained evidence, not mutable names/previews."""
    revision = evidence_digest(
        {
            "run_id": run.id,
            "evidence": getattr(run, "evidence_completeness", None),
            "diagnostics": getattr(run, "diagnostics", None),
            "source_metadata": getattr(run, "source_metadata", None),
        }
    )
    return EvidenceReference(
        kind="run",
        id=str(run.id),
        provider="runs",
        revision=revision,
        selected_output=EvidenceOutputSelection(**selection.model_dump()) if selection else None,
    )


def resolve_run_evidence(run: Any, selection: EvaluationSelection | None = None) -> ResolvedComparisonEvidence:
    reference = run_evidence_reference(run, selection)
    label = getattr(run, "name", None) or f"Run {run.id}"
    if getattr(run, "source_type", None) == "paired_evaluation":
        from spectra_sherpa.app.services.paired_evaluation import resolve_paired_evidence

        try:
            return resolve_paired_evidence(run, reference, selection)
        except (ValueError, TypeError, KeyError, AttributeError, OSError, IndexError) as exc:
            return ResolvedComparisonEvidence(reference, label, unavailable_reason=str(exc))
    from spectra_sherpa.app.services.retained_regression_comparison import (
        RetainedComparisonUnavailable,
        retained_regression_evidence,
    )

    try:
        regression, retained_population = retained_regression_evidence(run)
    except RetainedComparisonUnavailable as exc:
        regression, retained_population = (), PopulationSummary(limitations=[str(exc)])
    except (ValueError, TypeError, KeyError, AttributeError, OSError):
        regression, retained_population = (), PopulationSummary(
            limitations=["Retained population evidence could not be verified; inspect individual run outputs."]
        )
    try:
        evaluation = _evaluation(run, selection)
    except (ValueError, TypeError, KeyError, AttributeError, OSError) as exc:
        return ResolvedComparisonEvidence(
            reference,
            label,
            regression,
            retained_population,
            unavailable_reason=" ".join(retained_population.limitations)
            or ("Retained evaluation evidence could not be read." if isinstance(exc, OSError) else str(exc)),
        )
    receipts = dict(evaluation.inputs)
    # These positions are qualified by the exact retained scientific input
    # receipt. They are never matched to a different receipt by row number.
    population = PopulationSummary(
        development_count=len(evaluation.observations),
        evaluation_count=len(evaluation.observations),
        grouped=evaluation.split_plan["grouped"],
        group_count=(len(set(evaluation.split_plan["groups"])) if "groups" in evaluation.split_plan else None),
        fold_count=len(evaluation.split_plan["folds"]),
        partition_digest=evaluation.split,
        source_receipt=receipts["X"],
        verification="partial",
        limitations=["Response units and source/held-out population counts are not established by this CV receipt."],
    )
    record = EvaluationEvidence(
        role="training_cv",
        sample_ids=tuple(f"{receipts['X']}:{i}" for i in range(len(evaluation.observations))),
        observations=tuple(float(v) for v in evaluation.observations),
        predictions=evaluation.predictions,
        feature_receipt=receipts["X"],
        response_identity=receipts["y"],
        split_plan=evaluation.split_plan,
        population=population,
    )
    return ResolvedComparisonEvidence(
        reference,
        label,
        (*regression, record),
        retained_population if retained_population.verification != "unknown" else population,
    )


def _section(item: EvaluationEvidence) -> tuple[ScientificSection, EvaluationEvidence | None]:
    """Validate individual evidence without trusting supplied metric summaries."""
    try:
        n = len(item.sample_ids)
        if n < 2 or n > 100_000 or len(set(item.sample_ids)) != n or not all(item.sample_ids):
            raise ValueError("Evaluation requires 2–100,000 unique, nonempty sample identities.")
        if len(item.observations) != n or len(item.predictions) != n:
            raise ValueError("Sample, reference and prediction counts differ.")
        if not item.feature_receipt or not item.response_identity:
            raise ValueError("Exact feature population and response identities are required.")
        if any(not isfinite(float(v)) for v in (*item.observations, *item.predictions)):
            raise ValueError("Non-finite results require explicit exclusions and new evidence.")
        population = item.population.model_copy(deep=True)
        population.evaluation_count = n
        population.response, population.units = item.response, item.units
        population.source_receipt = item.feature_receipt
        population.verification = "partial"
        if item.role == "training_cv":
            normalized, plan = _normalized_split_plan(item.split_plan, n_samples=n)
            population.development_count = n
            population.fold_count = len(plan.folds)
            population.partition_digest = evidence_digest(normalized)
            population.grouped = plan.grouped
            population.group_count = len(set(normalized["groups"])) if plan.grouped else None
            item = replace(item, split_plan=normalized)
        elif item.role in {"calibration", "held_out"}:
            fit = item.fitted_sample_ids
            if fit is None or not fit or len(set(fit)) != len(fit):
                raise ValueError("The exact fitted population is required to verify this evaluation role.")
            overlap = set(fit).intersection(item.sample_ids)
            if item.role == "held_out" and overlap:
                raise ValueError("Held-out samples overlap the model's fitting population.")
            if item.role == "calibration" and set(fit) != set(item.sample_ids):
                raise ValueError("Calibration predictions must cover the exact fitted population.")
            population.development_count = len(fit)
            if item.role == "held_out":
                population.held_out_count = n
        else:
            raise ValueError("Challenge errors remain separate; detector and label-basis evidence must be inspected.")
        computed = sdk_validate.metrics(item.observations, item.predictions).as_dict()
        metrics = {
            key: float(computed[key])
            for key in ("rmse", "mae", "r2", "bias", "sep", "rer")
            if computed[key] is not None and isfinite(float(computed[key]))
        }
        # The unqualified fit-data role is never described as predictive
        # validation, regardless of how small its RMSE is.
        reason = (
            "Fitted-sample results describe calibration fit, not predictive validation."
            if item.role == "calibration"
            else (
                "Training-fold membership is verified; CV is development evidence, not independent validation."
                if item.role == "training_cv"
                else (
                    "Evaluation samples are excluded from fitting; "
                    "independence from prior inspection is not established."
                )
            )
        )
        if item.limitation:
            reason += " " + item.limitation
        return (
            ScientificSection(
                role=item.role,
                state="verified",
                population=population,
                metrics=metrics,
                sample_ids=list(item.sample_ids) if n <= 5000 else [],
                observations=list(item.observations) if n <= 5000 else [],
                predictions=list(item.predictions) if n <= 5000 else [],
                reason=reason,
            ),
            item,
        )
    except (ValueError, TypeError, KeyError, AttributeError, OverflowError) as exc:
        # A registered reader may expose retained aggregate scores for
        # inspection. They never substitute for paired observations/folds.
        aggregate = {
            key: float(value)
            for key, value in item.aggregate_metrics.items()
            if key in {"rmse", "rmsecv", "mae", "r2", "q2", "bias", "sep"}
            and isinstance(value, (int, float))
            and not isinstance(value, bool)
            and isfinite(float(value))
        }
        return (
            ScientificSection(
                role=item.role,
                state="descriptive_only",
                population=item.population,
                metrics=aggregate,
                reason=(item.limitation + " " if item.limitation else "") + str(exc),
            ),
            None,
        )


def compare_evidence(items: list[ResolvedComparisonEvidence]) -> EvidenceComparisonResponse:
    if not 2 <= len(items) <= 10:
        raise ValueError("Select between two and ten evidence records.")
    rendered, validated = [], []
    for item in items:
        sections, records = {}, {}
        for role in ROLES:
            candidates = [entry for entry in item.evaluations if entry.role == role]
            if len(candidates) == 1:
                sections[role], records[role] = _section(candidates[0])
            else:
                sections[role] = ScientificSection(
                    role=role,
                    state="unavailable" if not candidates else "descriptive_only",
                    reason=(
                        (item.unavailable_reason or "No retained evidence for this evaluation role.")
                        if not candidates
                        else "Choose one explicit output for this evaluation role."
                    ),
                )
                records[role] = None
        rendered.append(
            ComparisonEvidenceItem(
                reference=item.reference,
                label=item.label,
                population=item.population,
                sections=sections,
                dataset_use=item.dataset_use,
            )
        )
        validated.append(records)
    pairs = []
    for left, right in combinations(range(len(items)), 2):
        comparisons = []
        for role in ROLES:
            lhs, rhs = validated[left][role], validated[right][role]
            ls, rs = rendered[left].sections[role], rendered[right].sections[role]
            metric_values = {}
            if ls.state == "unavailable" or rs.state == "unavailable":
                state, reason = "unavailable", ls.reason if ls.state == "unavailable" else rs.reason
            elif lhs is None or rhs is None:
                state, reason = "descriptive_only", ls.reason if lhs is None else rs.reason
                metric_values = {
                    key: {"left": ls.metrics[key], "right": rs.metrics[key]}
                    for key in ls.metrics.keys() & rs.metrics.keys()
                }
                left_aggregate = [e for e in items[left].evaluations if e.role == role]
                right_aggregate = [e for e in items[right].evaluations if e.role == role]
                if len(left_aggregate) == len(right_aggregate) == 1:
                    la, ra = left_aggregate[0], right_aggregate[0]
                    if (
                        role == "training_cv"
                        and metric_values
                        and not any(
                            (
                                la.sample_ids,
                                la.observations,
                                la.predictions,
                                la.split_plan,
                                ra.sample_ids,
                                ra.observations,
                                ra.predictions,
                                ra.split_plan,
                            )
                        )
                        and la.aggregate_protocol
                        and ra.aggregate_protocol
                        and la.feature_receipt
                        and la.response_identity
                        and la.feature_receipt == ra.feature_receipt
                        and la.response_identity == ra.response_identity
                        and la.units == ra.units
                    ):
                        if la.aggregate_protocol == ra.aggregate_protocol:
                            state, reason = "comparable", (
                                "Verified aggregate training CV on the same development examination "
                                "and paired partitions. "
                                "Row-level predictions are not retained; sample plots are unavailable."
                            )
                        else:
                            state, reason = "reevaluation_needed", "Aggregate training CV partition receipts differ."
            elif (
                lhs.feature_receipt != rhs.feature_receipt
                or lhs.response_identity != rhs.response_identity
                or lhs.units != rhs.units
                or lhs.sample_ids != rhs.sample_ids
                or lhs.observations != rhs.observations
            ):
                state, reason = (
                    "reevaluation_needed",
                    "Exact evaluation population, response, units or sample alignment differ.",
                )
            elif role == "training_cv" and lhs.split_plan != rhs.split_plan:
                state, reason = (
                    "reevaluation_needed",
                    "Training CV folds differ; use a common protocol for paired comparison.",
                )
            else:
                state, reason = (
                    "comparable",
                    "Matched population, response and evaluation conditions; compare within this role only.",
                )
                metric_values = {
                    key: {"left": ls.metrics[key], "right": rs.metrics[key]}
                    for key in ls.metrics.keys() & rs.metrics.keys()
                }
            action = (
                "Inspect paired results; calibration, training CV and held-out claims remain distinct."
                if state == "comparable"
                else (
                    "Review a common evaluation protocol using retained development data."
                    if state == "reevaluation_needed" and role == "training_cv"
                    else "Inspect the retained evidence and complete the missing population or evaluation record."
                )
            )
            comparisons.append(
                ScientificSectionComparison(
                    role=role,
                    state=state,
                    reason=reason,
                    next_action=action,
                    metric_values=metric_values,
                )
            )
        pairs.append(ScientificEvidencePair(left_index=left, right_index=right, sections=comparisons))
    return EvidenceComparisonResponse(items=rendered, pairs=pairs)


def compare_saved_run_evidence(runs: list[Any], selections: dict[int, EvaluationSelection] | None = None):
    return compare_evidence([resolve_run_evidence(run, (selections or {}).get(run.id)) for run in runs])
