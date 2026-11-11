"""Presentation of retained sheet-fold regression evidence; never executes a fit."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from spectra_sherpa.app.services.dag.sheet_fold_validation import SHEET_FOLD_VALIDATION_RESULT_VERSION
from spectra_sherpa.sdk.validate import REGRESSION_METRIC_FIELDS, validate_supervised_metric_record

SCHEMA = SHEET_FOLD_VALIDATION_RESULT_VERSION


def regression_records(data: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Validate the producer's single-response metrics without inventing sample predictions."""
    scope = data.get("fold_validation")
    authority = data.get("population_authority")
    if (
        data.get("task_type") != "regression"
        or not isinstance(scope, dict)
        or scope.get("schema_version") != SCHEMA
        or scope.get("scope") != "cross_validation"
        or not isinstance(authority, dict)
        or authority.get("schema_version") != "spectrasherpa-population-authority/1"
        or authority.get("qualification") != "fold_executor_verified"
        or authority.get("role") != "cross_validation"
    ):
        raise ValueError("Training-set CV presentation requires canonical fold-executor regression evidence")
    allowed = REGRESSION_METRIC_FIELDS | {"task_type", "fold_validation", "population_authority"}
    if set(data) != allowed:
        raise ValueError("Training-set CV presentation requires one canonical response metric record")
    pooled = validate_supervised_metric_record({key: data[key] for key in REGRESSION_METRIC_FIELDS})
    folds = scope.get("fold_metrics")
    n_folds = scope.get("n_folds")
    if (
        not isinstance(folds, list)
        or not folds
        or isinstance(n_folds, bool)
        or not isinstance(n_folds, int)
        or n_folds < 2
        or n_folds != len(folds)
    ):
        raise ValueError("Training-set CV fold count does not match retained metrics")
    records = []
    for fold in folds:
        if not isinstance(fold, dict) or set(fold) != REGRESSION_METRIC_FIELDS:
            raise ValueError("Training-set CV requires single-response regression metrics for every fold")
        records.append(validate_supervised_metric_record(fold))
    if sum(record["n_samples"] for record in records) != pooled["n_samples"]:
        raise ValueError("Training-set CV pooled and fold sample counts disagree")
    metadata = {
        "type": "SheetFoldRegressionCV",
        "scope": "cross_validation",
        "fold_validation": deepcopy(scope),
        "population_authority": deepcopy(authority),
        "notice": "Training-set cross-validation only; no calibration or held-out test results. "
        "Pooled metrics are retained executor results, not averages of fold metrics. Response units are not declared.",
    }
    return [pooled, *records], metadata


def plot(data: dict[str, Any]) -> dict[str, Any]:
    records, metadata = regression_records(data)
    x = list(range(1, len(records)))
    return {
        "visualization": {
            "plot_type": "metrics",
            "data": [
                {
                    "type": "scatter",
                    "mode": "lines+markers",
                    "name": "Fold RMSE",
                    "x": x,
                    "y": [row["rmse"] for row in records[1:]],
                },
                {
                    "type": "scatter",
                    "mode": "lines",
                    "name": "Pooled RMSECV",
                    "x": x,
                    "y": [records[0]["rmse"]] * len(x),
                    "line": {"dash": "dash"},
                },
            ],
            "layout": {
                "title": "Training-set CV — fold errors",
                "xaxis": {"title": "Validation fold", "dtick": 1},
                "yaxis": {"title": "RMSE (response units not declared)", "rangemode": "tozero"},
            },
            "metadata": metadata,
        }
    }


def table(data: dict[str, Any], *, max_rows: int, show_index: bool) -> dict[str, Any]:
    records, metadata = regression_records(data)
    fields = (
        ("n_samples", "Samples"),
        ("rmse", "RMSE"),
        ("mae", "MAE"),
        ("bias", "Bias"),
        ("r2", "R²"),
        ("sep", "SEP"),
        ("slope", "Slope"),
        ("intercept", "Intercept"),
        ("rer", "RER"),
    )
    rows = [
        {"Evaluation": "Pooled CV" if i == 0 else f"Fold {i}", **{label: row[key] for key, label in fields}}
        for i, row in enumerate(records)
    ]
    metadata.update(
        n_rows=min(len(rows), max_rows),
        n_cols=1 + len(fields),
        truncated=len(rows) > max_rows,
        show_index=show_index,
        column_names=["Evaluation", *[label for _, label in fields]],
    )
    return {"data": rows[:max_rows], "metadata": metadata}
