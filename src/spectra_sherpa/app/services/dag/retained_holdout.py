"""Exact saved-run train/test membership, independent of candidate preprocessing."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping

import numpy as np

from spectra_sherpa.app.lib.sherpa_dataset import SherpaDataset

SCHEMA = "spectrasherpa-retained-holdout/2"
_FIELDS = frozenset(
    {
        "schema_version",
        "source_run_id",
        "source_node_id",
        "split_node_id",
        "source_scientific_digest",
        "source_replay_digest",
        "n_samples",
        "train_indices",
        "test_indices",
    }
)


def source_replay_digest(dataset: SherpaDataset) -> str:
    """Bind all source science and ordered operations, excluding only event time.

    Reloading the same source records new read/target-attachment timestamps.
    The full execution digest is retained separately; neither operation parameters
    (including any scientific timestamps) nor source/sample authority are omitted.
    """
    projection = dataset.scientific_projection(include_provenance=False)
    projection["provenance"] = [
        {key: value for key, value in entry.items() if key != "timestamp"} for entry in dataset.provenance.to_list()
    ]
    payload = json.dumps(projection, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _indices(value: object, *, n_samples: int, name: str) -> list[int]:
    if isinstance(value, (list, tuple)) and any(isinstance(item, (bool, np.bool_)) for item in value):
        raise ValueError(f"{name} must not contain booleans")
    array = np.asarray(value)
    if array.ndim != 1 or array.size == 0 or array.dtype.kind not in "iu":
        raise ValueError(f"{name} must be a nonempty integer vector")
    if np.any(array < 0) or np.any(array >= n_samples) or len(np.unique(array)) != len(array):
        raise ValueError(f"{name} contains duplicate or out-of-range rows")
    return array.astype(np.intp).tolist()


def read_retained_holdout(value: object) -> dict:
    if not isinstance(value, Mapping) or set(value) != _FIELDS or value.get("schema_version") != SCHEMA:
        raise ValueError("retained holdout fields or version are invalid")
    n = value["n_samples"]
    if isinstance(n, bool) or not isinstance(n, int) or n < 2:
        raise ValueError("retained holdout sample count is invalid")
    if (
        isinstance(value["source_run_id"], bool)
        or not isinstance(value["source_run_id"], int)
        or value["source_run_id"] < 1
    ):
        raise ValueError("retained holdout source run is invalid")
    for name in ("source_node_id", "split_node_id"):
        if not isinstance(value[name], str) or not value[name].strip():
            raise ValueError("retained holdout node identity is invalid")
    for name in ("source_scientific_digest", "source_replay_digest"):
        digest = value[name]
        if not isinstance(digest, str) or len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
            raise ValueError("retained holdout source identity is invalid")
    train = _indices(value["train_indices"], n_samples=n, name="training indices")
    test = _indices(value["test_indices"], n_samples=n, name="test indices")
    if len(train) + len(test) != n or set(train) & set(test):
        raise ValueError("training and test rows must be disjoint and cover the exact source population")
    return {**value, "train_indices": train, "test_indices": test}


def retained_holdout_partition(
    dataset: SherpaDataset,
    *,
    split_node_id: str,
    source_node_id: str,
    source_run_id: int,
    train_indices: object,
    test_indices: object,
) -> dict:
    return read_retained_holdout(
        {
            "schema_version": SCHEMA,
            "source_run_id": source_run_id,
            "source_node_id": source_node_id,
            "split_node_id": split_node_id,
            "source_scientific_digest": dataset.scientific_digest,
            "source_replay_digest": source_replay_digest(dataset),
            "n_samples": dataset.shape[0],
            "train_indices": train_indices,
            "test_indices": test_indices,
        }
    )


def verify_holdout_source(dataset: object, holdout: Mapping) -> SherpaDataset:
    record = read_retained_holdout(holdout)
    if not isinstance(dataset, SherpaDataset) or source_replay_digest(dataset) != record["source_replay_digest"]:
        raise ValueError("Saved holdout source has changed; create a new split before running this workflow")
    return dataset


def materialize_retained_holdout(dataset: object, holdout: Mapping, *, parameters: Mapping, raw_source=None) -> dict:
    """Apply recorded membership to the exact raw source without selecting rows again."""
    from dataclasses import replace

    from .nodes.data.split_planner import (
        _SPACE_FILLING_METHODS,
        SPLIT_METHODS,
        SplitPlan,
        _array_content_digest,
        _ordered_groups,
        _plan_digest,
        _unsigned_plan_payload,
        bind_split_groups,
        bind_split_target,
        materialize_split_outputs,
    )

    record = read_retained_holdout(holdout)
    source = verify_holdout_source(dataset if raw_source is None else raw_source, record)
    if raw_source is not None:
        if not isinstance(dataset, SherpaDataset) or not np.array_equal(dataset.X, source.X, equal_nan=True):
            raise ValueError("Retained split requires unchanged source rows before target attachment")
        if (dataset.sample_axis is None) != (source.sample_axis is None):
            raise ValueError("Retained split sample authority changed before target attachment")
        if dataset.sample_axis is not None and dataset.sample_axis.labels != source.sample_axis.labels:
            raise ValueError("Retained split sample order changed before target attachment")
        source = dataset
    matrix = np.asarray(source.X, dtype=np.float64)
    target, target_context = bind_split_target(source, None)
    groups = bind_split_groups(source)
    method = parameters.get("split_method", "random")
    if method not in SPLIT_METHODS:
        raise ValueError("Saved holdout split method is invalid")
    train = np.asarray(record["train_indices"], dtype=np.intp)
    test = np.asarray(record["test_indices"], dtype=np.intp)
    held_out = None if groups is None or method in _SPACE_FILLING_METHODS else _ordered_groups(groups[test])
    plan = SplitPlan(
        method=method,
        n_samples=len(matrix),
        test_size=float(parameters.get("test_size", 0.2)),
        random_seed=int(parameters.get("random_seed", 42)),
        distance_metric=parameters.get("distance_metric", "euclidean"),
        n_components=int(parameters.get("n_components", 0)),
        x_content_digest=_array_content_digest(matrix),
        y_content_digest=None if target is None else _array_content_digest(target),
        groups_content_digest=None if groups is None else _array_content_digest(groups),
        n_groups=None if groups is None else len(_ordered_groups(groups)),
        held_out_groups=held_out,
        train_indices=train,
        test_indices=test,
        digest="",
    )
    plan = replace(plan, digest=_plan_digest(_unsigned_plan_payload(plan)))
    return materialize_split_outputs(
        source,
        matrix,
        target,
        plan,
        node_id=record["split_node_id"],
        target_context=target_context,
        groups=groups,
    )
