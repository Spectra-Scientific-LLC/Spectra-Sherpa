"""Sheet CV output projections retain scientific scope without fabricating OOF rows."""

from copy import deepcopy
from dataclasses import asdict

import pytest

from spectra_sherpa.app.services.dag.nodes.output.data_table_node import build_data_table_result
from spectra_sherpa.app.services.dag.nodes.output.plot_node import build_plot_result
from spectra_sherpa.app.services.dag.sheet_fold_validation import SheetFoldValidationPlan, sheet_fold_validation_result
from spectra_sherpa.sdk.validate import make_split_plan, metrics


@pytest.fixture
def evidence():
    split = make_split_plan(4, n_splits=2)
    plan = SheetFoldValidationPlan("regression", 2, split.digest, None, "campaign-candidate")
    execution = {
        "task_type": "regression",
        "metrics": asdict(metrics([1, 2, 3, 4], [1, 3, 3, 6])),
        "folds": [{"metrics": asdict(metrics([1, 2], [1, 3]))}, {"metrics": asdict(metrics([3, 4], [3, 6]))}],
        "validation_execution_digest": "a" * 64,
    }
    return sheet_fold_validation_result(plan, execution, split=split).outputs["default"]


def test_outputs_keep_fold_errors_distinct_from_pooled_cv(evidence):
    original = deepcopy(evidence)
    plot = build_plot_result(evidence)["visualization"]
    assert plot["data"][0]["y"] == [fold["rmse"] for fold in evidence["fold_validation"]["fold_metrics"]]
    assert plot["data"][1]["y"] == [evidence["rmse"]] * 2
    assert "Nested" not in str(plot)
    assert "RMSE" in plot["layout"]["yaxis"]["title"]
    table = build_data_table_result(evidence)["visualization"]
    assert [row["Evaluation"] for row in table["data"]] == ["Pooled CV", "Fold 1", "Fold 2"]
    assert table["data"][0]["RMSE"] == evidence["rmse"]
    assert table["metadata"]["fold_validation"] == evidence["fold_validation"]
    assert evidence == original


def test_undefined_statistics_and_truncation(evidence):
    evidence["r2"] = None
    evidence["fold_validation"]["fold_metrics"][0]["r2"] = None
    evidence["fold_validation"]["fold_metrics"] *= 5
    evidence["fold_validation"]["n_folds"] = 10
    evidence["n_samples"] = 20
    table = build_data_table_result(evidence, parameters={"max_rows": 10})["visualization"]
    assert table["data"][0]["R²"] is None
    assert table["metadata"]["truncated"] is True


@pytest.mark.parametrize(
    "change",
    [
        lambda d: d.update(rmse=float("nan")),
        lambda d: d.update(rmse=True),
        lambda d: d.update(rmse=[1.0, 2.0]),
        lambda d: d.update(responses=["A", "B"]),
        lambda d: d["fold_validation"].update(n_folds=True),
        lambda d: d["fold_validation"].update(n_folds=3),
        lambda d: d["fold_validation"].update(schema_version="nested_cv"),
        lambda d: d["population_authority"].update(qualification="unknown"),
        lambda d: d.update(n_samples=10),
    ],
)
def test_invalid_or_multiresponse_evidence_is_not_presented(evidence, change):
    change(evidence)
    with pytest.raises((ValueError, TypeError)):
        build_plot_result(evidence)
    with pytest.raises((ValueError, TypeError)):
        build_data_table_result(evidence)
