"""Current, container-independent identities for scientific dataset inputs.

These helpers are shared by canonical DAG admission, supervised execution,
confirmation governance, and public-fixture reproduction.  They deliberately
do not depend on a workflow capsule or a model implementation: dataset and
split identity must survive removal of the historical M3 capsule interpreter.
"""

from __future__ import annotations

import hashlib
import json
import math
from typing import Any, Mapping, Sequence

import numpy as np

from .validate import SplitPlan

PUBLIC_DATASET_DIGEST_VERSION = "spectra-sherpa-public-dataset/1"


class DatasetIdentityError(ValueError):
    """A dataset reference, array envelope, or split plan is malformed."""


def reference_digest(reference: str) -> str:
    """Return an opaque digest for a caller-owned dataset reference."""

    if not isinstance(reference, str) or not 1 <= len(reference) <= 512:
        raise DatasetIdentityError("dataset reference must be a bounded non-empty string")
    return hashlib.sha256(reference.encode("utf-8")).hexdigest()


def public_dataset_digest(
    X: Sequence[Sequence[float]] | np.ndarray,
    y: Sequence[float] | np.ndarray,
    *,
    groups: Sequence[Any] | np.ndarray | None = None,
) -> str:
    """Hash canonical public-fixture arrays independently of container format."""

    features, observed, group_values = validate_public_dataset(X, y, groups)
    digest = hashlib.sha256()
    digest.update(PUBLIC_DATASET_DIGEST_VERSION.encode("ascii"))
    _update_numeric_array_digest(digest, features)
    _update_numeric_array_digest(digest, observed)
    if group_values is None:
        digest.update(b"\x00")
    else:
        digest.update(b"\x01")
        digest.update(_canonical_bytes({"groups": [_json_scalar(value) for value in group_values]}))
    return digest.hexdigest()


def split_plan_digest(plan: SplitPlan) -> str:
    """Return the canonical digest of an exact split plan."""

    if not isinstance(plan, SplitPlan):
        raise DatasetIdentityError("split plan identity requires a validated SplitPlan")
    return hashlib.sha256(_canonical_bytes(_split_plan_payload(plan))).hexdigest()


def split_plan_payload(plan: SplitPlan) -> dict[str, Any]:
    """Return the closed split identity payload shared by current consumers."""

    if not isinstance(plan, SplitPlan):
        raise DatasetIdentityError("split plan identity requires a validated SplitPlan")
    return _split_plan_payload(plan)


def _split_plan_payload(plan: SplitPlan) -> dict[str, Any]:
    return {
        "method": plan.method,
        "n_samples": plan.n_samples,
        "grouped": plan.grouped,
        "folds": [
            {
                "train_indices": fold.train.tolist(),
                "test_indices": fold.test.tolist(),
            }
            for fold in plan.folds
        ],
    }


def validate_public_dataset(
    X: Sequence[Sequence[float]] | np.ndarray,
    y: Sequence[float] | np.ndarray,
    groups: Sequence[Any] | np.ndarray | None,
) -> tuple[np.ndarray, np.ndarray, np.ndarray | None]:
    """Validate and freeze the arrays used by public reproduction."""

    try:
        features = np.asarray(X, dtype=np.float64)
        observed = np.asarray(y, dtype=np.float64)
    except (TypeError, ValueError) as exc:
        raise DatasetIdentityError("public reproduction data must be numeric") from exc
    if features.ndim != 2 or not 2 <= features.shape[0] <= 100_000 or not 1 <= features.shape[1] <= 20_000:
        raise DatasetIdentityError("public reproduction feature shape is outside the supported bound")
    if observed.ndim != 1 or observed.size != features.shape[0]:
        raise DatasetIdentityError("public reproduction target must contain one value per sample")
    if not np.isfinite(features).all() or not np.isfinite(observed).all():
        raise DatasetIdentityError("public reproduction data must contain only finite values")
    group_values: np.ndarray | None = None
    if groups is not None:
        group_values = np.asarray(groups)
        if group_values.ndim != 1 or group_values.size != features.shape[0]:
            raise DatasetIdentityError("public reproduction groups must contain one value per sample")
        for value in group_values:
            _json_scalar(value)
    features_copy = np.array(features, dtype="<f8", order="C", copy=True)
    observed_copy = np.array(observed, dtype="<f8", order="C", copy=True)
    groups_copy = None if group_values is None else np.array(group_values, copy=True)
    features_copy.setflags(write=False)
    observed_copy.setflags(write=False)
    if groups_copy is not None:
        groups_copy.setflags(write=False)
    return features_copy, observed_copy, groups_copy


def _update_numeric_array_digest(digest: Any, values: np.ndarray) -> None:
    metadata = {
        "dtype": "float64-le",
        "shape": list(values.shape),
        "nbytes": int(values.nbytes),
    }
    digest.update(_canonical_bytes(metadata))
    digest.update(np.ascontiguousarray(values, dtype="<f8").tobytes(order="C"))


def _json_scalar(value: Any) -> str | int | float | bool | None:
    if isinstance(value, np.generic):
        value = value.item()
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float) and math.isfinite(value):
        return value
    raise DatasetIdentityError("public reproduction group labels must be finite JSON scalar values")


def _canonical_bytes(payload: Mapping[str, Any]) -> bytes:
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


__all__ = [
    "DatasetIdentityError",
    "PUBLIC_DATASET_DIGEST_VERSION",
    "public_dataset_digest",
    "reference_digest",
    "split_plan_digest",
    "split_plan_payload",
    "validate_public_dataset",
]
