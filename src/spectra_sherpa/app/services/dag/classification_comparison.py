"""Canonical sample-level classification reference and prediction values."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

CLASSIFICATION_COMPARISON_SCHEMA = "spectrasherpa-classification-comparison/1"


def build_classification_comparison(
    reference: Sequence[Any],
    predicted: Sequence[Any],
    *,
    role: str,
    sample_labels: Sequence[str] | None = None,
) -> dict[str, object]:
    """Return one explicit reference/prediction decision per sample."""

    actual = list(reference)
    estimates = list(predicted)
    if not actual or len(actual) != len(estimates):
        raise ValueError("classification comparison requires aligned non-empty reference and prediction vectors")
    if role not in {"calibration", "cross_validation", "held_out_test", "unqualified_evaluation"}:
        raise ValueError("classification comparison role is not recognized")
    role_title = {
        "calibration": "Calibration",
        "cross_validation": "Cross-validation",
        "held_out_test": "Held-out",
        "unqualified_evaluation": "Evaluation",
    }[role]
    labels = (
        list(sample_labels)
        if sample_labels is not None
        else [f"{role_title} row {index + 1}" for index in range(len(actual))]
    )
    if len(labels) != len(actual) or not all(isinstance(item, str) and item for item in labels):
        raise ValueError("classification comparison labels must match the sample dimension")

    rows = [
        {
            "sample": labels[index],
            "reference": actual[index],
            "predicted": estimates[index],
            "correct": bool(actual[index] == estimates[index]),
            "role": role,
        }
        for index in range(len(actual))
    ]
    return {
        "schema_version": CLASSIFICATION_COMPARISON_SCHEMA,
        "shape": [len(rows), 5],
        "data": rows,
        "metadata": {
            "column_names": ["sample", "reference", "predicted", "correct", "role"],
            "n_samples": len(rows),
            "n_correct": sum(1 for row in rows if row["correct"]),
            "role": role,
            "sample_identity": "provided_labels" if sample_labels is not None else "row_position_only",
        },
    }


__all__ = ["CLASSIFICATION_COMPARISON_SCHEMA", "build_classification_comparison"]
