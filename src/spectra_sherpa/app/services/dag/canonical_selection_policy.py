"""One closed scientific rule for canonical supervised development selection.

The candidate metric vector remains task-specific and complete.  This module
only names the scalar used to rank a finite declared candidate set and whether
larger or smaller values are favourable.  The fold rule is descriptive, not
inferential: folds overlap in their training observations, so paired
dispersion is not a confidence interval or p-value.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from spectra_sherpa.sdk.validate import (
    pool_supervised_metric_records,
    supervised_metric_task,
    validate_supervised_metric_record,
)

CANONICAL_SELECTION_POLICY_VERSION = "spectra-canonical-selection-policy/2"
CANONICAL_DEVELOPMENT_DECISION_VERSION = "spectra-canonical-search-development-decision/3"
SCIENTIST_DEVELOPMENT_DECISION_VERSION = "spectra-canonical-search-development-decision/4"

_RULE_ID = "declared_margin_paired_dispersion_strict_majority"
_TASK_OBJECTIVES = {
    "regression": ("rmse", "minimize"),
    "classification": ("balanced_accuracy", "maximize"),
}
_SELECTION_BIAS_NOTICE = (
    "The winner is the best primary-metric value in the declared candidate set evaluated on one split plan. "
    "That development estimate is optimistically biased by selection and is not a held-out result."
)
_DIGEST = re.compile(r"^[0-9a-f]{64}$")
_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{2,127}$")
_POLICY_FIELDS = frozenset(
    {
        "schema_version",
        "rule_id",
        "task_type",
        "primary_metric",
        "optimization_direction",
        "minimum_improvement",
        "dispersion_floor",
        "fold_majority",
        "content_digest",
    }
)
_DISPERSION_FIELDS = frozenset({"method", "minimum_multiple", "single_fold_disposition"})
_MAJORITY_FIELDS = frozenset({"comparison", "threshold_numerator", "threshold_denominator"})
_CANDIDATE_FIELDS = frozenset(
    {
        "candidate_id",
        "ordinal",
        "result_digest",
        "dataset_content_digest",
        "split_plan_digest",
        "metrics",
        "folds",
    }
)
_FOLD_FIELDS = frozenset({"partition_digest", "metrics"})
_DECISION_FIELDS = frozenset(
    {
        "schema_version",
        "strategy",
        "baseline_candidate_id",
        "baseline_result_digest",
        "baseline_primary_metric",
        "winner_candidate_id",
        "winner_result_digest",
        "winner_primary_metric",
        "pooled_improvement",
        "paired_fold_margin",
        "conclusion",
        "conclusion_reason",
        "selection_bias_notice",
        "candidate_results",
    }
)
_MARGIN_FIELDS = frozenset(
    {
        "fold_count",
        "folds_favouring_winner",
        "mean_fold_improvement",
        "paired_standard_error",
        "required_dispersion_delta",
        "interpretation",
    }
)
_DECISION_CANDIDATE_FIELDS = frozenset({"candidate_id", "ordinal", "result_digest", "primary_metric_value"})


class CanonicalSelectionPolicyError(ValueError):
    """The selection policy, candidate evidence, or decision is malformed."""


@dataclass(frozen=True)
class CanonicalSelectionPolicy:
    """A digest-bound task objective fixed before any result is observed."""

    payload: dict[str, Any]
    content_digest: str

    @classmethod
    def build(
        cls,
        minimum_improvement: float,
        *,
        task_type: str = "regression",
    ) -> "CanonicalSelectionPolicy":
        if task_type not in _TASK_OBJECTIVES:
            raise CanonicalSelectionPolicyError("canonical selection task is unsupported")
        primary_metric, direction = _TASK_OBJECTIVES[task_type]
        margin = _finite_non_negative(minimum_improvement, "minimum_improvement")
        unsigned = {
            "schema_version": CANONICAL_SELECTION_POLICY_VERSION,
            "rule_id": _RULE_ID,
            "task_type": task_type,
            "primary_metric": primary_metric,
            "optimization_direction": direction,
            "minimum_improvement": margin,
            "dispersion_floor": {
                "method": "paired_fold_primary_metric_improvement_standard_error",
                "minimum_multiple": 1.0,
                "single_fold_disposition": "invalid",
            },
            "fold_majority": {
                "comparison": "strictly_greater_than",
                "threshold_numerator": 1,
                "threshold_denominator": 2,
            },
        }
        return cls.from_dict({**unsigned, "content_digest": _digest(unsigned)})

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "CanonicalSelectionPolicy":
        policy = _closed(value, _POLICY_FIELDS, "canonical selection policy")
        if policy["schema_version"] != CANONICAL_SELECTION_POLICY_VERSION or policy["rule_id"] != _RULE_ID:
            raise CanonicalSelectionPolicyError("canonical selection policy version or rule is unsupported")
        task_type = policy["task_type"]
        if task_type not in _TASK_OBJECTIVES:
            raise CanonicalSelectionPolicyError("canonical selection task is unsupported")
        primary_metric, direction = _TASK_OBJECTIVES[task_type]
        if policy["primary_metric"] != primary_metric or policy["optimization_direction"] != direction:
            raise CanonicalSelectionPolicyError("canonical selection objective differs from its task")
        policy["minimum_improvement"] = _finite_non_negative(policy["minimum_improvement"], "minimum_improvement")
        dispersion = _closed(policy["dispersion_floor"], _DISPERSION_FIELDS, "dispersion floor")
        if dispersion != {
            "method": "paired_fold_primary_metric_improvement_standard_error",
            "minimum_multiple": 1.0,
            "single_fold_disposition": "invalid",
        }:
            raise CanonicalSelectionPolicyError("canonical selection dispersion floor is unsupported")
        majority = _closed(policy["fold_majority"], _MAJORITY_FIELDS, "fold majority")
        if majority != {
            "comparison": "strictly_greater_than",
            "threshold_numerator": 1,
            "threshold_denominator": 2,
        }:
            raise CanonicalSelectionPolicyError("canonical selection fold majority is unsupported")
        content_digest = _digest_value(policy["content_digest"], "selection policy content_digest")
        unsigned = {key: policy[key] for key in _POLICY_FIELDS - {"content_digest"}}
        if _digest(unsigned) != content_digest:
            raise CanonicalSelectionPolicyError("canonical selection policy content digest mismatch")
        return cls(payload={**unsigned, "content_digest": content_digest}, content_digest=content_digest)

    def as_dict(self) -> dict[str, Any]:
        return deepcopy(self.payload)


def build_canonical_development_decision(
    candidates: Sequence[Mapping[str, Any]],
    *,
    policy: CanonicalSelectionPolicy,
    scientist_selection: Mapping[str, Any] | None = None,
    require_scientist_selection: bool = False,
) -> dict[str, Any]:
    """Rank the declared set and compute its sole defensible conclusion."""

    if not isinstance(policy, CanonicalSelectionPolicy):
        raise CanonicalSelectionPolicyError("canonical development decision requires a selection policy")
    records = _candidates(candidates, policy=policy)
    metric = policy.payload["primary_metric"]
    reverse = policy.payload["optimization_direction"] == "maximize"
    ranked = sorted(
        records,
        key=lambda item: (
            -_primary_value(item, metric) if reverse else _primary_value(item, metric),
            item["ordinal"],
            item["candidate_id"],
        ),
    )
    baseline, winner = records[0], ranked[0]
    selection = None
    if scientist_selection is not None:
        selection = _closed(
            scientist_selection, frozenset({"candidate_id", "actor_user_id", "rationale"}), "scientist selection"
        )
        actor = selection["actor_user_id"]
        reason = selection["rationale"]
        if isinstance(actor, bool) or not isinstance(actor, int) or actor < 1:
            raise CanonicalSelectionPolicyError("scientist selection actor is invalid")
        if not isinstance(reason, str) or not reason.strip() or len(reason) > 1000 or reason != reason.strip():
            raise CanonicalSelectionPolicyError("scientist selection rationale is invalid")
        winner = next((item for item in records if item["candidate_id"] == selection["candidate_id"]), None)
        if winner is None:
            raise CanonicalSelectionPolicyError("scientist selection requires a successful candidate")
    baseline_value = _primary_value(baseline, metric)
    winner_value = _primary_value(winner, metric)
    pooled_improvement = _improvement(baseline_value, winner_value, maximize=reverse)
    margin = _paired_margin(baseline, winner, metric=metric, maximize=reverse)
    minimum = policy.payload["minimum_improvement"]
    if winner["candidate_id"] == baseline["candidate_id"]:
        conclusion, reason = "no_defensible_improvement", "baseline_ranked_first"
    elif pooled_improvement < minimum:
        conclusion, reason = "no_defensible_improvement", "below_declared_margin"
    elif pooled_improvement < margin["required_dispersion_delta"]:
        conclusion, reason = "no_defensible_improvement", "within_fold_dispersion"
    elif margin["folds_favouring_winner"] * 2 <= margin["fold_count"]:
        conclusion, reason = "no_defensible_improvement", "not_consistent_across_folds"
    else:
        conclusion, reason = "improved", "declared_margin_dispersion_and_majority_satisfied"
    decision = {
        "schema_version": CANONICAL_DEVELOPMENT_DECISION_VERSION,
        "strategy": policy.as_dict(),
        "baseline_candidate_id": baseline["candidate_id"],
        "baseline_result_digest": baseline["result_digest"],
        "baseline_primary_metric": baseline_value,
        "winner_candidate_id": winner["candidate_id"],
        "winner_result_digest": winner["result_digest"],
        "winner_primary_metric": winner_value,
        "pooled_improvement": pooled_improvement,
        "paired_fold_margin": margin,
        "conclusion": conclusion,
        "conclusion_reason": reason,
        "selection_bias_notice": _SELECTION_BIAS_NOTICE,
        "candidate_results": [
            {
                "candidate_id": item["candidate_id"],
                "ordinal": item["ordinal"],
                "result_digest": item["result_digest"],
                "primary_metric_value": _primary_value(item, metric),
            }
            for item in records
        ],
    }
    if require_scientist_selection or selection is not None:
        decision.update(
            schema_version=SCIENTIST_DEVELOPMENT_DECISION_VERSION,
            ranked_first_candidate_id=ranked[0]["candidate_id"],
            scientist_selection=selection,
            selection_bias_notice=(
                "Candidates are ranked for inspection, not automatically selected. "
                "The scientist's choice is a development result, not independent confirmation."
            ),
        )
    return decision


def verify_canonical_development_decision(
    value: Mapping[str, Any],
    candidates: Sequence[Mapping[str, Any]],
    *,
    expected_policy: CanonicalSelectionPolicy | None = None,
) -> dict[str, Any]:
    reviewed = value.get("schema_version") == SCIENTIST_DEVELOPMENT_DECISION_VERSION
    fields = _DECISION_FIELDS | {"ranked_first_candidate_id", "scientist_selection"} if reviewed else _DECISION_FIELDS
    decision = _closed(value, fields, "canonical development decision")
    if decision["schema_version"] not in {
        CANONICAL_DEVELOPMENT_DECISION_VERSION,
        SCIENTIST_DEVELOPMENT_DECISION_VERSION,
    }:
        raise CanonicalSelectionPolicyError("canonical development decision version is unsupported")
    policy = CanonicalSelectionPolicy.from_dict(_mapping(decision["strategy"], "decision strategy"))
    if expected_policy is not None and policy.content_digest != expected_policy.content_digest:
        raise CanonicalSelectionPolicyError("canonical development decision changed its declared strategy")
    expected = build_canonical_development_decision(
        candidates,
        policy=policy,
        scientist_selection=decision.get("scientist_selection"),
        require_scientist_selection=reviewed,
    )
    if decision != expected:
        raise CanonicalSelectionPolicyError("canonical development decision does not reproduce from fold evidence")
    return deepcopy(expected)


def selection_candidate(
    *,
    candidate_id: str,
    ordinal: int,
    result_digest: str,
    dataset_content_digest: str,
    split_plan_digest: str,
    metrics: Mapping[str, Any],
    folds: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    return _candidate(
        {
            "candidate_id": candidate_id,
            "ordinal": ordinal,
            "result_digest": result_digest,
            "dataset_content_digest": dataset_content_digest,
            "split_plan_digest": split_plan_digest,
            "metrics": deepcopy(dict(metrics)),
            "folds": [deepcopy(dict(item)) for item in folds],
        }
    )


def _candidates(values: Sequence[Mapping[str, Any]], *, policy: CanonicalSelectionPolicy) -> tuple[dict[str, Any], ...]:
    if not isinstance(values, Sequence) or isinstance(values, (str, bytes)) or not values:
        raise CanonicalSelectionPolicyError("canonical selection requires a successful baseline")
    records = tuple(_candidate(value) for value in values)
    if tuple(item["ordinal"] for item in records) != tuple(range(1, len(records) + 1)):
        raise CanonicalSelectionPolicyError("canonical selection candidate ordinals are not contiguous")
    if len({item["candidate_id"] for item in records}) != len(records):
        raise CanonicalSelectionPolicyError("canonical selection candidate identities are repeated")
    if len({item["result_digest"] for item in records}) != len(records):
        raise CanonicalSelectionPolicyError("canonical selection result identities are repeated")
    if len({item["dataset_content_digest"] for item in records}) != 1:
        raise CanonicalSelectionPolicyError("canonical selection candidates changed the dataset content")
    if len({item["split_plan_digest"] for item in records}) != 1:
        raise CanonicalSelectionPolicyError("canonical selection candidates changed the split plan")
    task = policy.payload["task_type"]
    if any(supervised_metric_task(item["metrics"]) != task for item in records):
        raise CanonicalSelectionPolicyError("canonical selection metrics differ from the declared task")
    expected_partitions = tuple(item["partition_digest"] for item in records[0]["folds"])
    expected_samples = tuple(item["metrics"]["n_samples"] for item in records[0]["folds"])
    if any(
        tuple(item["partition_digest"] for item in record["folds"]) != expected_partitions
        or tuple(item["metrics"]["n_samples"] for item in record["folds"]) != expected_samples
        for record in records[1:]
    ):
        raise CanonicalSelectionPolicyError("canonical selection candidates were not evaluated on identical folds")
    return records


def _candidate(value: Mapping[str, Any]) -> dict[str, Any]:
    candidate = _closed(value, _CANDIDATE_FIELDS, "canonical selection candidate")
    candidate["candidate_id"] = _identifier(candidate["candidate_id"], "candidate_id")
    if isinstance(candidate["ordinal"], bool) or not isinstance(candidate["ordinal"], int) or candidate["ordinal"] < 1:
        raise CanonicalSelectionPolicyError("canonical selection candidate ordinal is invalid")
    for field in ("result_digest", "dataset_content_digest", "split_plan_digest"):
        candidate[field] = _digest_value(candidate[field], f"candidate {field}")
    try:
        candidate["metrics"] = validate_supervised_metric_record(_mapping(candidate["metrics"], "candidate metrics"))
    except ValueError as exc:
        raise CanonicalSelectionPolicyError("canonical selection candidate metrics are invalid") from exc
    raw_folds = candidate["folds"]
    if not isinstance(raw_folds, list) or len(raw_folds) < 2:
        raise CanonicalSelectionPolicyError("canonical selection needs at least two folds for dispersion")
    folds = [_fold(item) for item in raw_folds]
    if len({item["partition_digest"] for item in folds}) != len(folds):
        raise CanonicalSelectionPolicyError("canonical selection fold partitions are repeated")
    tasks = {supervised_metric_task(item["metrics"]) for item in folds}
    if tasks != {supervised_metric_task(candidate["metrics"])}:
        raise CanonicalSelectionPolicyError("canonical selection fold metrics differ from pooled task")
    try:
        pooled = pool_supervised_metric_records([item["metrics"] for item in folds])
    except ValueError as exc:
        raise CanonicalSelectionPolicyError("canonical selection fold metrics cannot be pooled") from exc
    metric = _TASK_OBJECTIVES[next(iter(tasks))][0]
    if not math.isclose(
        float(candidate["metrics"][metric]),
        float(pooled[metric]),
        rel_tol=1e-12,
        abs_tol=1e-12,
    ):
        raise CanonicalSelectionPolicyError("canonical selection primary metric does not reproduce from its folds")
    candidate["folds"] = folds
    return candidate


def _fold(value: Mapping[str, Any]) -> dict[str, Any]:
    fold = _closed(value, _FOLD_FIELDS, "canonical selection fold")
    fold["partition_digest"] = _digest_value(fold["partition_digest"], "fold partition_digest")
    try:
        fold["metrics"] = validate_supervised_metric_record(_mapping(fold["metrics"], "fold metrics"))
    except ValueError as exc:
        raise CanonicalSelectionPolicyError("canonical selection fold metrics are invalid") from exc
    return fold


def _primary_value(candidate: Mapping[str, Any], metric: str) -> float:
    value = candidate["metrics"].get(metric)
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
        raise CanonicalSelectionPolicyError("canonical selection primary metric is invalid")
    return float(value)


def _improvement(baseline: float, winner: float, *, maximize: bool) -> float:
    return winner - baseline if maximize else baseline - winner


def _paired_margin(
    baseline: Mapping[str, Any],
    winner: Mapping[str, Any],
    *,
    metric: str,
    maximize: bool,
) -> dict[str, Any]:
    deltas = [
        _improvement(float(left["metrics"][metric]), float(right["metrics"][metric]), maximize=maximize)
        for left, right in zip(baseline["folds"], winner["folds"], strict=True)
    ]
    count = len(deltas)
    mean_delta = sum(deltas) / count
    variance = sum((value - mean_delta) ** 2 for value in deltas) / (count - 1)
    standard_error = math.sqrt(variance / count)
    return {
        "fold_count": count,
        "folds_favouring_winner": sum(1 for value in deltas if value > 0),
        "mean_fold_improvement": mean_delta,
        "paired_standard_error": standard_error,
        "required_dispersion_delta": standard_error,
        "interpretation": "conservative_dispersion_floor_not_a_confidence_interval",
    }


def _closed(value: Any, fields: frozenset[str], label: str) -> dict[str, Any]:
    if not isinstance(value, Mapping) or set(value) != fields:
        raise CanonicalSelectionPolicyError(f"{label} fields are closed")
    return deepcopy(dict(value))


def _mapping(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise CanonicalSelectionPolicyError(f"{label} must be an object")
    return value


def _identifier(value: Any, field: str) -> str:
    if not isinstance(value, str) or not _IDENTIFIER.fullmatch(value):
        raise CanonicalSelectionPolicyError(f"{field} is invalid")
    return value


def _digest_value(value: Any, field: str) -> str:
    if not isinstance(value, str) or not _DIGEST.fullmatch(value):
        raise CanonicalSelectionPolicyError(f"{field} is not a lowercase SHA-256 digest")
    return value


def _finite_non_negative(value: Any, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)) or value < 0:
        raise CanonicalSelectionPolicyError(f"{field} must be finite and non-negative")
    return float(value)


def _digest(value: Mapping[str, Any]) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


__all__ = [
    "CANONICAL_DEVELOPMENT_DECISION_VERSION",
    "CANONICAL_SELECTION_POLICY_VERSION",
    "CanonicalSelectionPolicy",
    "CanonicalSelectionPolicyError",
    "build_canonical_development_decision",
    "selection_candidate",
    "verify_canonical_development_decision",
]
