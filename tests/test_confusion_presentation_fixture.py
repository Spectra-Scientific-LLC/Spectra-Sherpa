"""Keep the frontend evaluator regression bound to actual canonical producers."""

import json
from pathlib import Path

from spectra_sherpa.app.services.dag.nodes.classification_evaluator_node import (
    ClassificationEvaluatorV2Node,
    evaluate_classification_v2,
)
from spectra_sherpa.app.services.dag.scientific_values import describe_node_outputs


def evaluator_fixture():
    classes = ["setosa", "versicolor", "virginica"]
    matrix = [[11, 1, 0], [0, 6, 6], [0, 3, 10]]
    observed, predicted = [], []
    for i, row in enumerate(matrix):
        for k, count in enumerate(row):
            observed.extend([classes[i]] * count)
            predicted.extend([classes[k]] * count)
    result = evaluate_classification_v2(predicted, observed, node_id="eval_1")
    metadata = ClassificationEvaluatorV2Node.metadata
    presentation = metadata.resolved_presentation_contract()
    return {
        "node_type": metadata.node_type,
        "result": result.outputs,
        "descriptors": describe_node_outputs(metadata, result.outputs),
        "presentation_contract": {"digest": presentation.digest, "payload": presentation.as_dict()},
    }


def test_frontend_confusion_fixture_matches_actual_evaluator_and_descriptors():
    actual = evaluator_fixture()
    fixture = Path(__file__).resolve().parents[1] / "frontend/src/test/fixtures/classification-evaluator.json"
    assert actual == json.loads(fixture.read_text())
    assert actual["result"]["default"]["n_samples"] == 37
    assert actual["result"]["visualization"]["metadata"]["labels"] == ["setosa", "versicolor", "virginica"]
    assert actual["descriptors"]["visualization"]["dimensions"] == [
        {"role": "axis_1", "size": 3},
        {"role": "axis_2", "size": 3},
    ]
