"""Canonical sample-level regression comparison values.

Both calibration-fit and held-out evaluation nodes use this one projection so
tables and plots cannot disagree about reference, prediction, or residual.
"""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np

from spectra_sherpa.sdk.validate import metrics

REGRESSION_COMPARISON_SCHEMA = "spectrasherpa-regression-comparison/1"


def build_regression_statistics(reference, predicted, *, target_names=None, metric_records=None):
    """Canonical workflow computation; consumers must retain/read, never reconstruct."""
    actual = np.asarray(reference, dtype=float)
    estimates = np.asarray(predicted, dtype=float)
    if actual.ndim == 1:
        actual = actual.reshape(-1, 1)
    if estimates.ndim == 1:
        estimates = estimates.reshape(-1, 1)
    if actual.ndim != 2 or estimates.shape != actual.shape or not actual.shape[0]:
        raise ValueError("Regression statistics require aligned, nonempty response matrices")
    if not np.isfinite(actual).all() or not np.isfinite(estimates).all():
        raise ValueError("Regression statistics require finite observations and predictions")
    names = list(target_names or [f"Target {i + 1}" for i in range(actual.shape[1])])
    if len(names) != actual.shape[1] or len(set(names)) != len(names):
        raise ValueError("Regression target names must uniquely identify each response")
    records = (
        metric_records
        if metric_records is not None
        else [metrics(actual[:, i], estimates[:, i]).as_dict() for i in range(actual.shape[1])]
    )
    return {
        "schema_version": "spectrasherpa-regression-statistics/1",
        "targets": [
            {
                "target": name,
                "reference_min": float(actual[:, i].min()),
                "reference_max": float(actual[:, i].max()),
                "reference_sd": float(actual[:, i].std(ddof=1)) if len(actual) > 1 else None,
                "metrics": records[i],
                "bias_definition": "predicted_minus_reference",
            }
            for i, name in enumerate(names)
        ],
    }


def build_regression_comparison(
    reference: object,
    predicted: object,
    *,
    role: str,
    target_names: Sequence[str] | None = None,
    sample_labels: Sequence[str] | None = None,
) -> dict[str, object]:
    """Return a closed long-form comparison for one or more responses."""

    actual = np.asarray(reference, dtype=np.float64)
    estimates = np.asarray(predicted, dtype=np.float64)
    if actual.ndim == 1:
        actual = actual.reshape(-1, 1)
    if estimates.ndim == 1:
        estimates = estimates.reshape(-1, 1)
    if actual.ndim != 2 or estimates.shape != actual.shape:
        raise ValueError("regression comparison requires aligned two-dimensional reference and prediction matrices")
    if not np.isfinite(actual).all() or not np.isfinite(estimates).all():
        raise ValueError("regression comparison values must be finite")
    if role not in {"calibration", "cross_validation", "held_out_test", "unqualified_evaluation"}:
        raise ValueError("regression comparison role is not recognized")

    samples, targets = actual.shape
    names = list(target_names or [f"Target {index + 1}" for index in range(targets)])
    labels = list(sample_labels or [str(index + 1) for index in range(samples)])
    if len(names) != targets or len(labels) != samples:
        raise ValueError("regression comparison labels must match the scientific dimensions")
    if not all(isinstance(item, str) and item for item in (*names, *labels)):
        raise ValueError("regression comparison labels must be non-empty strings")

    rows: list[dict[str, object]] = []
    for sample_index in range(samples):
        for target_index in range(targets):
            observed = float(actual[sample_index, target_index])
            estimate = float(estimates[sample_index, target_index])
            rows.append(
                {
                    "sample": labels[sample_index],
                    "target": names[target_index],
                    "reference": observed,
                    "predicted": estimate,
                    "residual": observed - estimate,
                    "role": role,
                }
            )
    return {
        "schema_version": REGRESSION_COMPARISON_SCHEMA,
        "statistics": build_regression_statistics(actual, estimates, target_names=names),
        "shape": [len(rows), 6],
        "data": rows,
        "metadata": {
            "column_names": ["sample", "target", "reference", "predicted", "residual", "role"],
            "n_samples": samples,
            "n_targets": targets,
            "target_names": names,
            "role": role,
            "residual_definition": "reference_minus_predicted",
        },
    }


__all__ = ["REGRESSION_COMPARISON_SCHEMA", "build_regression_comparison"]
