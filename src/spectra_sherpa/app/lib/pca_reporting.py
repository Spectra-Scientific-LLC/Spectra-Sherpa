"""Block-aware descriptive reporting for already-computed PCA scores.

This module never fits or transforms PCA.  It summarizes the typed sample
identity attached to one native PCA score matrix.  The block variance fraction
is the descriptive Euclidean partition used in multivariate analysis of
variance; it carries no p-value or causal interpretation.

Reference: Anderson, M. J. (2001), Austral Ecology 26, 32-46.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

import numpy as np

from spectra_sherpa.app.lib.collection_assembly import lossless_sample_table_scalar

PCA_BLOCK_REPORT_SCHEMA = "spectrasherpa.pca-block-report/1"
ORDER_IDENTIFIABILITY = "not_separable_from_specimen_identity_same_specimen_order_in_every_block"
REQUIRED_COLUMNS = ("sample_id", "specimen_id", "block", "acquisition_order")
IdentityScalar = str | int | float | bool
MAX_REPORT_ROWS = 10_000
MAX_REPORT_COMPONENTS = 256
MAX_PRIVATE_PAIR_RECORDS = 100_000


def _array_digest(value: Any) -> str:
    array = np.asarray(value, dtype="<f8")
    return hashlib.sha256(array.tobytes(order="C")).hexdigest()


def _json_digest(value: object) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False).encode()
    return hashlib.sha256(payload).hexdigest()


def _finite_scores(value: Any) -> np.ndarray:
    scores = np.asarray(value, dtype=np.float64)
    if scores.ndim != 2 or min(scores.shape) < 1 or not np.isfinite(scores).all():
        raise ValueError("PCA block reporting requires a non-empty finite two-dimensional score matrix")
    return scores


def _exact_text_column(value: object, *, name: str, rows: int, unique: bool) -> list[str]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)) or len(value) != rows:
        raise ValueError(f"PCA sample table {name} must contain one value per score row")
    result = list(value)
    if not all(isinstance(item, str) and item != "" and item == item.strip() for item in result):
        raise ValueError(f"PCA sample table {name} must contain exact non-empty strings")
    if unique and len(set(result)) != rows:
        raise ValueError(f"PCA sample table {name} must be unique")
    return result


def _exact_order(value: object, *, rows: int) -> list[int]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)) or len(value) != rows:
        raise ValueError("PCA sample table acquisition_order must contain one value per score row")
    result: list[int] = []
    for item in value:
        scalar = lossless_sample_table_scalar(item)
        if not isinstance(scalar, int) or isinstance(scalar, bool) or scalar < 1:
            raise ValueError("PCA sample table acquisition_order must contain positive integers")
        result.append(scalar)
    return result


def _scalar_identity(value: IdentityScalar) -> tuple[str, str]:
    """Return a sortable identity that never conflates distinct scalar types."""

    type_name = "bool" if isinstance(value, bool) else type(value).__name__
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return type_name, encoded


def _exact_scalar_column(value: object, *, name: str, rows: int) -> list[IdentityScalar]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)) or len(value) != rows:
        raise ValueError(f"PCA sample table {name} must contain one value per score row")
    result: list[IdentityScalar] = []
    for item in value:
        scalar = lossless_sample_table_scalar(item)
        if scalar is None:
            raise ValueError(f"PCA sample table {name} must contain non-null lossless scalar identities")
        result.append(scalar)
    return result


def _summary(values: Sequence[float]) -> dict[str, Any]:
    array = np.sort(np.asarray(values, dtype=np.float64))
    if array.ndim != 1 or array.size < 1 or not np.isfinite(array).all():
        raise ValueError("PCA descriptive distance set is empty or non-finite")
    return {
        "count": int(array.size),
        "minimum": float(np.min(array)),
        "median": float(np.median(array)),
        "mean": float(np.mean(array)),
        "maximum": float(np.max(array)),
        "values_sha256": _array_digest(array),
    }


def _average_ranks(values: np.ndarray) -> np.ndarray:
    order = np.argsort(values, kind="mergesort")
    ranks = np.empty(values.size, dtype=np.float64)
    start = 0
    while start < values.size:
        end = start + 1
        while end < values.size and values[order[end]] == values[order[start]]:
            end += 1
        ranks[order[start:end]] = (start + end - 1) / 2.0 + 1.0
        start = end
    return ranks


def _spearman(left: np.ndarray, right: np.ndarray) -> dict[str, Any]:
    left_ranks = _average_ranks(np.asarray(left, dtype=np.float64))
    right_ranks = _average_ranks(np.asarray(right, dtype=np.float64))
    if np.ptp(left_ranks) == 0.0 or np.ptp(right_ranks) == 0.0:
        return {"rho": None, "status": "unavailable_constant_rank"}
    return {"rho": float(np.corrcoef(left_ranks, right_ranks)[0, 1]), "status": "available"}


@dataclass(frozen=True)
class PCABlockReport:
    public_summary: dict[str, Any]
    private_pairs: dict[str, list[dict[str, Any]]]


def build_pca_block_report(
    scores: Any,
    *,
    sample_labels: Sequence[str],
    sample_table: Mapping[str, object],
) -> PCABlockReport:
    """Summarize one fitted PCA score matrix without fitting another model."""

    matrix = _finite_scores(scores)
    rows, components = matrix.shape
    if rows > MAX_REPORT_ROWS or components > MAX_REPORT_COMPONENTS:
        raise ValueError("PCA block reporting exceeds its bounded score-matrix dimensions")
    labels = _exact_text_column(sample_labels, name="labels", rows=rows, unique=True)
    if not isinstance(sample_table, Mapping) or not set(REQUIRED_COLUMNS).issubset(sample_table):
        raise ValueError("PCA block reporting requires sample_id, specimen_id, block, and acquisition_order")
    sample_ids = _exact_text_column(sample_table["sample_id"], name="sample_id", rows=rows, unique=True)
    specimens = _exact_text_column(sample_table["specimen_id"], name="specimen_id", rows=rows, unique=False)
    blocks = _exact_scalar_column(sample_table["block"], name="block", rows=rows)
    acquisition_order = _exact_order(sample_table["acquisition_order"], rows=rows)
    if labels != sample_ids:
        raise ValueError("PCA score labels must exactly match sample_table.sample_id")
    specimen_ids = sorted(set(specimens))
    block_keys = [_scalar_identity(value) for value in blocks]
    block_value_by_key = {key: value for key, value in zip(block_keys, blocks, strict=True)}
    unique_block_keys = sorted(block_value_by_key)
    block_ids = [block_value_by_key[key] for key in unique_block_keys]
    if len(specimen_ids) < 2 or len(block_ids) < 2:
        raise ValueError("PCA block reporting requires at least two specimens and two blocks")
    within_pair_count = len(specimen_ids) * len(block_ids) * (len(block_ids) - 1) // 2
    between_pair_count = len(specimen_ids) * (len(specimen_ids) - 1) // 2
    if within_pair_count + between_pair_count > MAX_PRIVATE_PAIR_RECORDS:
        raise ValueError("PCA block reporting exceeds its bounded private pair-record limit")
    specimen_array = np.asarray(specimens, dtype=object)
    order_array = np.asarray(acquisition_order, dtype=np.int64)
    expected_specimen_count = len(block_ids)
    expected_block_count = len(specimen_ids)
    if any(int(np.sum(specimen_array == value)) != expected_specimen_count for value in specimen_ids):
        raise ValueError("PCA block reporting requires one balanced row per specimen and block")
    if any(sum(key == value for key in block_keys) != expected_block_count for value in unique_block_keys):
        raise ValueError("PCA block reporting requires one balanced row per specimen and block")
    seen_cells = {(specimens[index], block_keys[index]) for index in range(rows)}
    if len(seen_cells) != rows or rows != len(specimen_ids) * len(block_ids):
        raise ValueError("PCA block reporting has a missing or duplicate specimen/block cell")

    specimen_centroids = np.vstack(
        [
            np.mean(
                matrix[sorted(np.flatnonzero(specimen_array == value), key=lambda index: block_keys[index])], axis=0
            )
            for value in specimen_ids
        ]
    )
    block_centroids = np.vstack(
        [
            np.mean(
                matrix[
                    sorted(
                        [index for index, key in enumerate(block_keys) if key == value],
                        key=lambda index: sample_ids[index],
                    )
                ],
                axis=0,
            )
            for value in unique_block_keys
        ]
    )
    within_pairs: list[dict[str, Any]] = []
    for specimen in specimen_ids:
        indices = np.asarray(
            sorted(np.flatnonzero(specimen_array == specimen), key=lambda index: block_keys[index]), dtype=np.int64
        )
        for left_position in range(indices.size):
            for right_position in range(left_position + 1, indices.size):
                left = int(indices[left_position])
                right = int(indices[right_position])
                within_pairs.append(
                    {
                        "specimen_id": specimen,
                        "left_sample_id": sample_ids[left],
                        "right_sample_id": sample_ids[right],
                        "distance": float(np.linalg.norm(matrix[left] - matrix[right])),
                    }
                )
    between_pairs: list[dict[str, Any]] = []
    for left in range(len(specimen_ids)):
        for right in range(left + 1, len(specimen_ids)):
            between_pairs.append(
                {
                    "left_specimen_id": specimen_ids[left],
                    "right_specimen_id": specimen_ids[right],
                    "distance": float(np.linalg.norm(specimen_centroids[left] - specimen_centroids[right])),
                }
            )

    grand = np.mean(matrix[np.argsort(np.asarray(sample_ids, dtype=object), kind="mergesort")], axis=0)
    total_ss = float(np.sum((matrix - grand) ** 2))
    block_ss = float(len(specimen_ids) * np.sum((block_centroids - grand) ** 2))
    if total_ss <= 0.0 or not 0.0 <= block_ss <= total_ss * (1.0 + 1e-12):
        raise ValueError("PCA block variance partition is invalid")
    block_r_squared = min(1.0, block_ss / total_ss)

    order_paths: list[dict[str, Any]] = []
    specimen_orders: dict[str, list[int]] = {}
    for block_key, block in zip(unique_block_keys, block_ids, strict=True):
        indices = np.asarray([index for index, key in enumerate(block_keys) if key == block_key], dtype=np.int64)
        indices = indices[np.argsort(order_array[indices], kind="mergesort")]
        block_orders = order_array[indices].tolist()
        if len(set(block_orders)) != len(block_orders):
            raise ValueError("PCA block acquisition_order values must be unique within each block")
        ordered_specimens = [specimens[int(index)] for index in indices]
        if not specimen_orders:
            specimen_orders = {block: ordered_specimens}
        elif ordered_specimens != next(iter(specimen_orders.values())):
            raise ValueError("PCA block report expects the same specimen acquisition sequence in every block")
        else:
            specimen_orders[block] = ordered_specimens
        ordered_scores = matrix[indices]
        order_paths.append(
            {
                "block": block,
                "ordered_sample_ids_sha256": _json_digest([sample_ids[int(index)] for index in indices]),
                "ordered_scores_sha256": _array_digest(ordered_scores),
                "spearman_by_component": [
                    {
                        "component": component + 1,
                        **_spearman(order_array[indices], ordered_scores[:, component]),
                    }
                    for component in range(components)
                ],
                "successive_path_length": float(np.sum(np.linalg.norm(np.diff(ordered_scores, axis=0), axis=1))),
            }
        )

    within_values = [float(pair["distance"]) for pair in within_pairs]
    between_values = [float(pair["distance"]) for pair in between_pairs]
    within_mean = float(np.mean(within_values))
    if within_mean <= 0.0:
        raise ValueError("PCA between/within distance ratio is undefined for zero within-specimen distance")
    public = {
        "schema_version": PCA_BLOCK_REPORT_SCHEMA,
        "score_shape": list(matrix.shape),
        "sample_identity_sha256": _json_digest(sample_ids),
        "specimen_ids": specimen_ids,
        "block_ids": block_ids,
        "within_specimen_pairwise_distance": _summary(within_values),
        "between_specimen_centroid_distance": _summary(between_values),
        "between_to_within_mean_ratio": float(np.mean(between_values) / within_mean),
        "specimen_centroids_sha256": _array_digest(specimen_centroids),
        "block_centroids": block_centroids.tolist(),
        "block_centroids_sha256": _array_digest(block_centroids),
        "block_r_squared": block_r_squared,
        "block_effect_interpretation": "descriptive_euclidean_variance_fraction_no_p_value_or_causal_claim",
        "order_specimen_fully_aliased": True,
        "order_identifiability": ORDER_IDENTIFIABILITY,
        "ordered_paths": order_paths,
    }
    return PCABlockReport(
        public_summary=public,
        private_pairs={"within_specimen": within_pairs, "between_specimen_centroids": between_pairs},
    )


__all__ = [
    "ORDER_IDENTIFIABILITY",
    "PCA_BLOCK_REPORT_SCHEMA",
    "PCABlockReport",
    "build_pca_block_report",
]
