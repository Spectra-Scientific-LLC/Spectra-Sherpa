"""Closed provenance admission for saved-model preprocessing replay."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from typing import Any

import numpy as np

from spectra_sherpa.app.lib.collection_assembly import MAX_COLLECTION_MEMBERS
from spectra_sherpa.app.lib.sherpa_dataset import SherpaDataset


def validate_experiment_source_provenance(params: Mapping[str, Any]) -> None:
    """Admit the collection reader as non-transforming training provenance."""

    expected = {
        "dataset_id",
        "file_count",
        "stage",
        "asset_id",
        "source_manifest_sha256",
        "collection_definition_sha256",
        "scientific_collection_sha256",
    }
    if set(params) != expected:
        raise ValueError("experiment collection provenance does not match its closed schema")
    if (
        type(params["dataset_id"]) is not int
        or params["dataset_id"] < 1
        or type(params["file_count"]) is not int
        or not 1 <= params["file_count"] <= MAX_COLLECTION_MEMBERS
        or params["stage"] not in {"raw", "preprocessed", "synthetic"}
        or not isinstance(params["asset_id"], str)
        or not params["asset_id"]
        or params["asset_id"] != params["asset_id"].strip()
        or not all(
            is_sha256(params[name])
            for name in (
                "source_manifest_sha256",
                "collection_definition_sha256",
                "scientific_collection_sha256",
            )
        )
    ):
        raise ValueError("experiment collection provenance is malformed")


def validate_variable_selection_provenance(
    params: Mapping[str, Any],
    *,
    manifest: Mapping[str, Any],
    source_dataset: Any | None,
) -> None:
    """Cross-bind a recorded selection to its mask, source axis, and report."""

    from spectra_sherpa.app.services.dag.nodes.selection.variable_select_node import VariableSelectNode

    if set(params) != {"selection_report", "feature_mask"}:
        raise ValueError("variable-selection provenance does not match its closed schema")
    report = params["selection_report"]
    if not isinstance(report, Mapping) or set(report) != {
        "schema",
        "method",
        "parameters",
        "selection_scope",
        "predictive_performance_claimed",
        "reference_samples",
        "reference_features",
        "selected_features",
        "feature_axis_values_sha256",
        "feature_mask_sha256",
        "score_sha256",
        "detected_extrema_indices",
    }:
        raise ValueError("variable-selection report does not match its closed schema")
    raw_mask = params["feature_mask"]
    top_mask = manifest.get("feature_mask")
    if (
        not isinstance(raw_mask, list)
        or not raw_mask
        or any(type(value) is not bool for value in raw_mask)
        or not isinstance(top_mask, list)
        or len(top_mask) != len(raw_mask)
        or any(type(value) is not bool for value in top_mask)
        or not np.array_equal(np.asarray(top_mask, dtype=bool), np.asarray(raw_mask, dtype=bool))
    ):
        raise ValueError("variable-selection report differs from the artifact feature mask")
    mask = np.asarray(raw_mask, dtype=bool)
    if (
        report["schema"] != "spectrasherpa.selection.variable_select.report/1"
        or report["selection_scope"] != "target_free_feature_rule_not_predictive_validation"
        or report["predictive_performance_claimed"] is not False
        or type(report["reference_samples"]) is not int
        or report["reference_samples"] < 1
        or type(report["reference_features"]) is not int
        or report["reference_features"] != mask.size
        or type(report["selected_features"]) is not int
        or report["selected_features"] != int(mask.sum())
        or not is_sha256(report["feature_axis_values_sha256"])
        or report["feature_mask_sha256"] != hashlib.sha256(mask.astype("?").tobytes(order="C")).hexdigest()
        or not is_optional_sha256(report["score_sha256"])
        or not isinstance(report["detected_extrema_indices"], list)
        or any(type(index) is not int or not 0 <= index < mask.size for index in report["detected_extrema_indices"])
    ):
        raise ValueError("variable-selection report is malformed")
    raw_parameters = report["parameters"]
    if not isinstance(raw_parameters, Mapping):
        raise ValueError("variable-selection parameters are malformed")
    canonical = VariableSelectNode.metadata.canonicalize_parameters(dict(raw_parameters))
    if dict(raw_parameters) != canonical or report["method"] != canonical["method"]:
        raise ValueError("variable-selection parameters are not canonical")
    if source_dataset is None or not isinstance(source_dataset, SherpaDataset):
        raise ValueError("variable-selection replay requires a typed source feature axis")
    axis = source_dataset.get_feature_axis()
    if axis is None or axis.values is None:
        raise ValueError("variable-selection replay requires source feature-axis values")
    axis_values = np.asarray(axis.values, dtype=np.float64)
    if axis_values.ndim != 1 or not np.isfinite(axis_values).all():
        raise ValueError("variable-selection source feature axis is malformed")
    if axis_values.shape == (mask.size,):
        axis_digest = hashlib.sha256(axis_values.astype("<f8").tobytes(order="C")).hexdigest()
        if report["feature_axis_values_sha256"] != axis_digest:
            raise ValueError("variable-selection report differs from the source feature axis")
        if canonical["method"] == "interval":
            low = min(float(canonical["region_start"]), float(canonical["region_end"]))
            high = max(float(canonical["region_start"]), float(canonical["region_end"]))
            expected = (axis_values >= low) & (axis_values <= high)
            if canonical["invert"]:
                expected = ~expected
            if not np.array_equal(mask, expected):
                raise ValueError("variable-selection mask differs from its interval rule")
    elif axis_values.shape == (int(mask.sum()),):
        selected_axis = np.asarray(manifest.get("feature_axis"), dtype=np.float64)
        if selected_axis.shape != axis_values.shape or not np.array_equal(axis_values, selected_axis):
            raise ValueError("already-selected input differs from the artifact feature axis")
    else:
        raise ValueError("variable-selection source feature axis is malformed")


def is_sha256(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and value == value.lower()
        and all(char in "0123456789abcdef" for char in value)
    )


def is_optional_sha256(value: object) -> bool:
    return value is None or is_sha256(value)


__all__ = [
    "is_optional_sha256",
    "is_sha256",
    "validate_experiment_source_provenance",
    "validate_variable_selection_provenance",
]
