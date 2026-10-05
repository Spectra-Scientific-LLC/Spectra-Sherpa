"""Derive a closed aggregate metric receipt at the run-retention boundary.

The workbench evaluator's ``default`` output is a scientist-facing display
contract that predates the canonical optimization metric schema.  Replacing
that output or adding a semantic DAG port would rewrite historical graph
digests.  This adapter therefore adds one retention-only evidence item while
the run is first persisted.  Historical runs simply lack the item.
"""

from __future__ import annotations

from typing import Any, Mapping

from spectra_sherpa.core.node_identity import canonical_node_type
from spectra_sherpa.sdk.validate import (
    CLASSIFICATION_METRIC_SET_REGISTRY_VERSION,
    ClassificationMetricAccumulator,
    ClassificationMetricSet,
    classification_metric_set,
    validate_supervised_metric_record,
)

CANONICAL_METRIC_EVIDENCE_PORT = "canonical_metrics"
_MAX_CANONICAL_METRIC_SAMPLES = 500_000
_EVALUATOR_TYPES = {
    "diagnostics.regression_evaluator": "regression",
    "diagnostics.labeled_regression_evaluator": "regression",
    "diagnostics.classification_evaluator": "classification",
}


def _regression_metric(value: object) -> dict[str, object] | None:
    if not isinstance(value, Mapping) or value.get("task_type") != "regression":
        return None
    candidate = dict(value)
    candidate.pop("task_type", None)
    try:
        return validate_supervised_metric_record(candidate)
    except (TypeError, ValueError):
        # Multi-response display records deliberately have no scalar canonical
        # equivalent because response units and scales cannot be blended.
        return None


def _classification_metric(value: object) -> dict[str, object] | None:
    if (
        not isinstance(value, Mapping)
        or value.get("schema_version") != "spectrasherpa.classification-evaluation/1"
        or not isinstance(value.get("labels"), list)
        or not isinstance(value.get("confusion_matrix"), list)
    ):
        return None
    labels = value["labels"]
    matrix = value["confusion_matrix"]
    if len(labels) < 2 or len(matrix) != len(labels):
        return None
    sample_count = 0
    try:
        for row in matrix:
            if not isinstance(row, list) or len(row) != len(labels):
                return None
            for count in row:
                if isinstance(count, bool) or not isinstance(count, int) or count < 0:
                    return None
                sample_count += count
                if sample_count > _MAX_CANONICAL_METRIC_SAMPLES:
                    return None
        if sample_count != value.get("n_samples"):
            return None
        accumulator = ClassificationMetricAccumulator(labels)
        accumulator.merge(
            ClassificationMetricSet(
                registry_version=CLASSIFICATION_METRIC_SET_REGISTRY_VERSION,
                n_samples=sample_count,
                labels=tuple(labels),
                accuracy=0.0,
                balanced_accuracy=0.0,
                macro_f1=0.0,
                mcc=0.0,
                confusion_matrix=tuple(tuple(row) for row in matrix),
                class_sensitivities=tuple(None for _ in labels),
                class_specificities=tuple(None for _ in labels),
            )
        )
        return validate_supervised_metric_record(accumulator.metrics().as_dict())
    except (TypeError, ValueError):
        return None


def _simca_metric(
    results: Mapping[str, Any],
    definition: Mapping[str, object],
    *,
    evaluator_id: str,
    ordinary: dict[str, object],
) -> dict[str, object] | None:
    nodes = definition.get("nodes")
    if not isinstance(nodes, list):
        return None
    typed = {
        node["node_id"]: canonical_node_type(node["node_type"])
        for node in nodes
        if isinstance(node, Mapping) and isinstance(node.get("node_id"), str) and isinstance(node.get("node_type"), str)
    }
    simca_models = [node_id for node_id, node_type in typed.items() if node_type == "classification.simca"]
    if not simca_models:
        return ordinary
    edges = definition.get("edges")
    if not isinstance(edges, list):
        return None
    applications = [node_id for node_id, node_type in typed.items() if node_type == "classification.apply_simca"]
    splits = [node_id for node_id, node_type in typed.items() if node_type == "data.train_test_split"]
    if len(simca_models) != 1 or len(applications) != 1 or len(splits) != 1:
        return None
    model_id, application_id, split_id = simca_models[0], applications[0], splits[0]
    wiring = {
        (
            edge.get("from_node_id"),
            edge.get("to_node_id"),
            edge.get("from_output", "default"),
            edge.get("to_input", "default"),
        )
        for edge in edges
        if isinstance(edge, Mapping)
    }
    required = {
        (model_id, application_id, "fitted_state", "fitted_state"),
        (split_id, application_id, "X_test", "X_new"),
        (application_id, evaluator_id, "y_pred", "default"),
        (split_id, evaluator_id, "y_test", "y_true"),
    }
    if not required.issubset(wiring):
        return None
    model_outputs = results.get(model_id)
    application_outputs = results.get(application_id)
    split_outputs = results.get(split_id)
    if not all(isinstance(value, Mapping) for value in (model_outputs, application_outputs, split_outputs)):
        return None
    assert isinstance(model_outputs, Mapping)
    assert isinstance(application_outputs, Mapping)
    assert isinstance(split_outputs, Mapping)
    observed = split_outputs.get("y_test")
    predicted = application_outputs.get("y_pred")
    try:
        if len(observed) != ordinary["n_samples"] or len(observed) > _MAX_CANONICAL_METRIC_SAMPLES:
            return None
        from spectra_sherpa.app.services.dag.nodes.classification.simca_nodes import (
            simca_acceptance_membership,
        )

        simca_labels, membership = simca_acceptance_membership(
            split_outputs.get("X_test"), model_outputs.get("fitted_state")
        )
        candidate = validate_supervised_metric_record(
            classification_metric_set(
                observed,
                predicted,
                labels=ordinary["labels"],
                simca_membership=membership,
                simca_labels=simca_labels,
            ).as_dict()
        )
    except (KeyError, TypeError, ValueError):
        return None
    simca_fields = {
        "mean_class_acceptance_sensitivity",
        "unassigned_rate",
        "multiple_acceptance_rate",
        "simca_acceptance",
    }
    if any(candidate[key] != value for key, value in ordinary.items() if key not in simca_fields):
        return None
    return candidate


def project_canonical_metric_evidence(
    results: Mapping[str, Any], definition: Mapping[str, object] | None
) -> dict[str, Any]:
    """Return results with exact canonical metrics added for admitted evaluators."""

    projected = dict(results)
    if not isinstance(definition, Mapping) or not isinstance(definition.get("nodes"), list):
        return projected
    for node in definition["nodes"]:
        if not isinstance(node, Mapping) or not isinstance(node.get("node_id"), str):
            continue
        serialized_type = node.get("node_type")
        task = _EVALUATOR_TYPES.get(canonical_node_type(serialized_type)) if isinstance(serialized_type, str) else None
        outputs = projected.get(node["node_id"])
        if task is None or not isinstance(outputs, Mapping) or CANONICAL_METRIC_EVIDENCE_PORT in outputs:
            continue
        if task == "regression":
            canonical = _regression_metric(outputs.get("default"))
        else:
            ordinary = _classification_metric(outputs.get("default"))
            canonical = (
                None
                if ordinary is None
                else _simca_metric(projected, definition, evaluator_id=node["node_id"], ordinary=ordinary)
            )
        if canonical is not None:
            projected[node["node_id"]] = {**dict(outputs), CANONICAL_METRIC_EVIDENCE_PORT: canonical}
    return projected


__all__ = ["CANONICAL_METRIC_EVIDENCE_PORT", "project_canonical_metric_evidence"]
