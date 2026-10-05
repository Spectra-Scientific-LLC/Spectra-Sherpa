"""Run-retention projection for optimization seed performance evidence."""

from __future__ import annotations

import numpy as np

from spectra_sherpa.app.services.canonical_metric_retention import (
    CANONICAL_METRIC_EVIDENCE_PORT,
    project_canonical_metric_evidence,
)
from spectra_sherpa.app.services.dag.nodes.classification_evaluator_node import (
    evaluate_classification_v2,
)
from spectra_sherpa.app.services.dag.nodes.regression_evaluator_node import evaluate_regression_v2
from spectra_sherpa.sdk.validate import validate_supervised_metric_record


def _definition(node_type: str) -> dict[str, object]:
    return {"nodes": [{"node_id": "score", "node_type": node_type}]}


def test_actual_regression_evaluator_output_projects_to_exact_canonical_record() -> None:
    evaluated = evaluate_regression_v2(
        np.asarray([1.1, 2.9, 4.2]),
        np.asarray([1.0, 3.0, 4.0]),
        node_id="score",
    )

    projected = project_canonical_metric_evidence(
        {"score": evaluated.outputs},
        _definition("diagnostics.regression_evaluator"),
    )

    retained = projected["score"][CANONICAL_METRIC_EVIDENCE_PORT]
    assert retained == validate_supervised_metric_record(retained)
    assert retained == {key: value for key, value in evaluated.outputs["default"].items() if key != "task_type"}


def test_historical_evaluator_alias_projects_without_rewriting_the_definition() -> None:
    evaluated = evaluate_regression_v2(
        np.asarray([1.1, 2.9, 4.2]),
        np.asarray([1.0, 3.0, 4.0]),
        node_id="score",
    )
    definition = _definition("diagnostics.regression_evaluator_v2")

    projected = project_canonical_metric_evidence({"score": evaluated.outputs}, definition)

    assert CANONICAL_METRIC_EVIDENCE_PORT in projected["score"]
    assert definition["nodes"][0]["node_type"] == "diagnostics.regression_evaluator_v2"


def test_actual_classification_evaluator_output_projects_to_exact_canonical_record() -> None:
    evaluated = evaluate_classification_v2(
        np.asarray(["A", "unassigned", "B", "C", "C", "unassigned"]),
        np.asarray(["A", "A", "B", "B", "C", "C"]),
        node_id="score",
    )

    projected = project_canonical_metric_evidence(
        {"score": evaluated.outputs},
        _definition("diagnostics.classification_evaluator"),
    )

    retained = projected["score"][CANONICAL_METRIC_EVIDENCE_PORT]
    assert retained == validate_supervised_metric_record(retained)
    assert retained["n_samples"] == 6
    assert retained["balanced_accuracy"] == 0.5


def test_multi_response_regression_is_omitted_instead_of_blending_scales() -> None:
    evaluated = evaluate_regression_v2(
        np.asarray([[1.1, 101.0], [1.9, 198.0], [3.2, 303.0]]),
        np.asarray([[1.0, 100.0], [2.0, 200.0], [3.0, 300.0]]),
        target_names=["minor", "major"],
        node_id="score",
    )

    projected = project_canonical_metric_evidence(
        {"score": evaluated.outputs},
        _definition("diagnostics.regression_evaluator"),
    )

    assert CANONICAL_METRIC_EVIDENCE_PORT not in projected["score"]


def test_oversized_confusion_matrix_is_omitted_without_expanding_counts() -> None:
    outputs = {
        "score": {
            "default": {
                "schema_version": "spectrasherpa.classification-evaluation/1",
                "labels": ["A", "B"],
                "confusion_matrix": [[500_001, 0], [0, 0]],
                "n_samples": 500_001,
            }
        }
    }

    projected = project_canonical_metric_evidence(
        outputs,
        _definition("diagnostics.classification_evaluator"),
    )

    assert CANONICAL_METRIC_EVIDENCE_PORT not in projected["score"]
