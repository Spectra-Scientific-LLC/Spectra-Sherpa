"""Portable deterministic evidence for structural optimization hypotheses.

This module is intentionally free of provider and persistence concerns.  It
projects already-admitted validation evidence through the decision rule that
was frozen before execution; narration may consume the result but cannot alter
it.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections import defaultdict
from copy import deepcopy
from typing import Any, Mapping


class OptimizationHypothesisEvidenceError(ValueError):
    """Frozen hypothesis evidence cannot be reproduced truthfully."""


def _canonical_json(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _digest(value: object) -> str:
    return hashlib.sha256(_canonical_json(value)).hexdigest()


def _finite_metric(metrics: Mapping[str, Any], name: str) -> float | None:
    value = metrics.get(name)
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
        return None
    return float(value)


def _fold_metrics(validation: Mapping[str, Any]) -> dict[str, Mapping[str, Any]] | None:
    folds = validation.get("folds")
    if not isinstance(folds, list):
        return None
    indexed: dict[str, Mapping[str, Any]] = {}
    for fold in folds:
        if not isinstance(fold, Mapping) or not isinstance(fold.get("partition_digest"), str):
            return None
        partition = fold["partition_digest"]
        metrics = fold.get("metrics")
        if partition in indexed or not isinstance(metrics, Mapping):
            return None
        indexed[partition] = metrics
    return indexed


def _guardrail_result(guardrail: Mapping[str, Any], metrics: Mapping[str, Any]) -> dict[str, Any]:
    metric = guardrail.get("metric")
    operator = guardrail.get("operator")
    limit = guardrail.get("value")
    if not isinstance(metric, str) or operator not in {"minimum", "maximum", "maximum_absolute"}:
        raise OptimizationHypothesisEvidenceError("hypothesis guardrail is unsupported")
    if isinstance(limit, bool) or not isinstance(limit, (int, float)) or not math.isfinite(float(limit)):
        raise OptimizationHypothesisEvidenceError("hypothesis guardrail limit is invalid")
    observed = _finite_metric(metrics, metric)
    passed = None
    if observed is not None:
        passed = (
            observed >= float(limit)
            if operator == "minimum"
            else (observed <= float(limit) if operator == "maximum" else abs(observed) <= float(limit))
        )
    return {
        "metric": metric,
        "operator": operator,
        "limit": float(limit),
        "observed": observed,
        "passed": passed,
    }


def classify_hypothesis(
    *,
    hypothesis: Mapping[str, Any],
    reference_validation: Mapping[str, Any] | None,
    trial_validation: Mapping[str, Any] | None,
    trial_status: str,
    failure_code: str | None,
    execution_complete: bool = True,
) -> dict[str, Any]:
    """Apply one frozen decision rule to one exact seed/trial pair."""

    rule = hypothesis.get("decision_rule")
    trial = hypothesis.get("trial")
    if not isinstance(rule, Mapping) or rule.get("schema_version") != "spectra-managed-hypothesis-decision-rule/1":
        raise OptimizationHypothesisEvidenceError("hypothesis decision rule is unsupported")
    if not isinstance(trial, Mapping) or not isinstance(trial.get("workflow_diff"), Mapping):
        raise OptimizationHypothesisEvidenceError("hypothesis workflow difference is unavailable")
    paired = rule.get("paired_calculation")
    stability_rule = rule.get("stability")
    guardrail_rules = rule.get("guardrails")
    if (
        not isinstance(paired, Mapping)
        or not isinstance(stability_rule, Mapping)
        or not isinstance(guardrail_rules, list)
    ):
        raise OptimizationHypothesisEvidenceError("hypothesis decision rule is incomplete")
    metric = paired.get("primary_metric")
    direction = paired.get("direction")
    required_pairs = paired.get("required_pair_count")
    minimum_fraction = stability_rule.get("minimum_fraction")
    threshold = rule.get("minimum_meaningful_improvement")
    if (
        not isinstance(metric, str)
        or direction not in {"minimize", "maximize"}
        or isinstance(required_pairs, bool)
        or not isinstance(required_pairs, int)
        or required_pairs < 1
        or isinstance(minimum_fraction, bool)
        or not isinstance(minimum_fraction, (int, float))
        or not 0 <= float(minimum_fraction) <= 1
        or isinstance(threshold, bool)
        or not isinstance(threshold, (int, float))
        or not math.isfinite(float(threshold))
        or float(threshold) < 0
    ):
        raise OptimizationHypothesisEvidenceError("hypothesis comparison rule is invalid")

    workflow_diff = deepcopy(dict(trial["workflow_diff"]))
    added_nodes = workflow_diff.get("added_nodes", [])
    removed_nodes = workflow_diff.get("removed_nodes", [])
    operation_changes = workflow_diff.get("operation_changes", [])
    parameter_changes = workflow_diff.get("parameter_changes", [])
    order_changes = workflow_diff.get("order_changes", [])
    scientific_change_lists = (added_nodes, removed_nodes, operation_changes, parameter_changes, order_changes)
    if any(not isinstance(items, list) for items in scientific_change_lists):
        raise OptimizationHypothesisEvidenceError("hypothesis workflow difference is invalid")
    # Count actual interventions, not distinct affected nodes. Two parameter
    # changes on one model are still a bundle and cannot support single-change
    # attribution. Edge rewiring is excluded as the usual mechanical
    # consequence of a node-level intervention.
    scientific_change_count = sum(len(items) for items in scientific_change_lists)
    complexity = {
        "node_count_delta": (
            len(added_nodes) - len(removed_nodes)
            if isinstance(added_nodes, list) and isinstance(removed_nodes, list)
            else None
        ),
        "operation_change_count": len(operation_changes) if isinstance(operation_changes, list) else None,
        "parameter_change_count": len(parameter_changes) if isinstance(parameter_changes, list) else None,
        "topology_changed": workflow_diff.get("topology_changed"),
        "latent_variable_changes": (
            [
                deepcopy(dict(item))
                for item in parameter_changes
                if isinstance(item, Mapping) and item.get("parameter") == "n_components"
            ]
            if isinstance(parameter_changes, list)
            else []
        ),
    }
    attribution = "single_change_attributable" if scientific_change_count == 1 else "bundled_changes_non_attributable"
    base = {
        "hypothesis_id": hypothesis.get("hypothesis_id"),
        "title": hypothesis.get("title"),
        "direction_label": hypothesis.get("direction_label"),
        "workflow_diff": workflow_diff,
        "scientific_change_count": scientific_change_count,
        "complexity": complexity,
        "attribution": attribution,
        "decision_rule_digest": _digest(rule),
        "failure_code": failure_code,
    }
    if not execution_complete:
        result = {
            **base,
            "outcome": "pending",
            "reason": "execution_in_progress",
            "primary_metric": None,
            "guardrails": [],
            "stability": None,
        }
        return {**result, "evidence_digest": _digest(result)}
    if trial_status != "evaluated" or reference_validation is None or trial_validation is None:
        result = {
            **base,
            "outcome": "inconclusive",
            "reason": "trial_failed_or_evidence_incomplete",
            "primary_metric": None,
            "guardrails": [],
            "stability": None,
        }
        return {**result, "evidence_digest": _digest(result)}

    reference_metrics = reference_validation.get("metrics")
    trial_metrics = trial_validation.get("metrics")
    if not isinstance(reference_metrics, Mapping) or not isinstance(trial_metrics, Mapping):
        raise OptimizationHypothesisEvidenceError("validation metrics are unavailable")
    reference_primary = _finite_metric(reference_metrics, metric)
    trial_primary = _finite_metric(trial_metrics, metric)
    reference_folds = _fold_metrics(reference_validation)
    trial_folds = _fold_metrics(trial_validation)
    guardrails = [_guardrail_result(item, trial_metrics) for item in guardrail_rules]
    evidence_complete = (
        reference_primary is not None
        and trial_primary is not None
        and reference_folds is not None
        and trial_folds is not None
        and set(reference_folds) == set(trial_folds)
        and len(reference_folds) == required_pairs
        and all(item["observed"] is not None for item in guardrails)
    )
    pair_deltas: list[dict[str, Any]] = []
    if evidence_complete:
        for partition in sorted(reference_folds):
            reference_value = _finite_metric(reference_folds[partition], metric)
            trial_value = _finite_metric(trial_folds[partition], metric)
            if reference_value is None or trial_value is None:
                evidence_complete = False
                pair_deltas = []
                break
            improvement = reference_value - trial_value if direction == "minimize" else trial_value - reference_value
            pair_deltas.append(
                {
                    "partition_digest": partition,
                    "reference": reference_value,
                    "trial": trial_value,
                    "improvement": improvement,
                    "directionally_improved": improvement > 0,
                }
            )
    if not evidence_complete:
        result = {
            **base,
            "outcome": "inconclusive",
            "reason": "paired_evidence_insufficient",
            "primary_metric": None,
            "guardrails": guardrails,
            "stability": None,
        }
        return {**result, "evidence_digest": _digest(result)}

    improvement = reference_primary - trial_primary if direction == "minimize" else trial_primary - reference_primary
    improved_pairs = sum(item["directionally_improved"] for item in pair_deltas)
    fraction = improved_pairs / required_pairs
    threshold_met = improvement >= float(threshold)
    stability_met = fraction >= float(minimum_fraction)
    guardrails_met = all(item["passed"] is True for item in guardrails)
    aggregate_improved = improvement > 0
    pair_direction_improved = stability_met
    if aggregate_improved != pair_direction_improved:
        outcome, reason = "inconclusive", "aggregate_and_pair_stability_conflict"
    elif threshold_met and stability_met and guardrails_met:
        outcome, reason = "supported", "all_frozen_rules_met"
    else:
        outcome, reason = "not_supported", "one_or_more_frozen_rules_not_met"
    result = {
        **base,
        "outcome": outcome,
        "reason": reason,
        "primary_metric": {
            "metric": metric,
            "direction": direction,
            "reference": reference_primary,
            "trial": trial_primary,
            "improvement": improvement,
            "minimum_meaningful_improvement": float(threshold),
            "threshold_met": threshold_met,
        },
        "guardrails": guardrails,
        "stability": {
            "required_pair_count": required_pairs,
            "valid_pair_count": len(pair_deltas),
            "directionally_improved_pair_count": improved_pairs,
            "directionally_improved_pair_fraction": fraction,
            "minimum_fraction": float(minimum_fraction),
            "passed": stability_met,
            "pairs": pair_deltas,
        },
    }
    return {**result, "evidence_digest": _digest(result)}


def summarize_direction_groups(hypotheses: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Summarize related hypotheses without manufacturing a group outcome."""

    groups: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for hypothesis in hypotheses:
        label = hypothesis.get("direction_label")
        groups[label if isinstance(label, str) and label.strip() else "Unlabelled direction"].append(hypothesis)
    summaries = []
    for label in sorted(groups):
        members = groups[label]
        counts = {
            name: sum(item.get("outcome") == name for item in members)
            for name in ("pending", "supported", "not_supported", "inconclusive")
        }
        summaries.append(
            {
                "direction_label": label,
                "member_hypothesis_ids": [item.get("hypothesis_id") for item in members],
                "member_outcome_counts": counts,
                "claim_status": "summary_only_no_group_support_claim",
            }
        )
    return summaries


def hypothesis_projection_digest(value: Mapping[str, Any]) -> str:
    """Digest a closed readout projection without a self-reference."""

    return _digest(value)


__all__ = [
    "OptimizationHypothesisEvidenceError",
    "classify_hypothesis",
    "hypothesis_projection_digest",
    "summarize_direction_groups",
]
