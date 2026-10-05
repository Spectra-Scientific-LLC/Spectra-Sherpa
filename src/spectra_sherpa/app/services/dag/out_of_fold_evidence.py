"""Closed DAG evidence binding for out-of-fold observations and predictions.

The semantic type is intentionally an indivisible record.  A prediction
vector, fold vector, or target vector does not independently prove that any
sample was held out.  This module binds all three vectors to the exact split
plan and to the current canonical producer contract before an evaluator may
describe the result as out-of-fold evidence.

The digest is an integrity binding, not a managed signature.  Workflow
preflight separately restricts which registered operation may produce this
type; managed publisher authenticity remains a higher-level evidence concern.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from typing import Any

import numpy as np

from spectra_sherpa.sdk import validate as sdk_validate

OUT_OF_FOLD_EVIDENCE_TYPE = "spectrasherpa://types/OutOfFoldEvidence/1.0"
OUT_OF_FOLD_EVIDENCE_SCHEMA = "spectrasherpa-out-of-fold-evidence/1"
NESTED_CV_OPERATION_ID = "selection.nested_cv"
NESTED_CV_IMPLEMENTATION_ID = "spectrasherpa.selection.nested_cv"

_EVIDENCE_FIELDS = {
    "schema_version",
    "producer",
    "task_type",
    "observations",
    "predictions",
    "fold_assignments",
    "split_plan",
    "split_plan_digest",
    "evidence_sha256",
}
_PRODUCER_FIELDS = {"operation_id", "implementation_id", "execution_contract_digest", "node_id"}
_SPLIT_PLAN_FIELDS = {"schema_version", "method", "n_samples", "grouped", "folds"}
_FOLD_FIELDS = {"train", "test"}


def _canonical_digest(payload: Mapping[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()


def _canonical_nested_cv_contract() -> Any:
    """Return the live closed producer contract after registry population."""

    from spectra_sherpa.app.services.dag.node_base import node_registry
    from spectra_sherpa.app.services.dag.stable_execution_contract import ensure_registered_execution_contract

    metadata = node_registry.get_metadata(NESTED_CV_OPERATION_ID)
    contract = ensure_registered_execution_contract(metadata)
    if (
        contract.payload["operation_id"] != NESTED_CV_OPERATION_ID
        or contract.payload["implementation_id"] != NESTED_CV_IMPLEMENTATION_ID
    ):
        raise ValueError("the canonical out-of-fold producer contract has an unexpected identity")
    return contract


def require_canonical_out_of_fold_producer(metadata: Any) -> None:
    """Fail unless metadata is the one current in-tree OOF producer.

    This is deliberately closed-world admission.  Adding another producer is
    a reviewed core-contract change, not something a plugin can accomplish by
    declaring the same nominal output type.
    """

    if getattr(metadata, "node_type", None) != NESTED_CV_OPERATION_ID:
        raise ValueError(f"{OUT_OF_FOLD_EVIDENCE_TYPE} requires producer {NESTED_CV_OPERATION_ID}")
    actual = metadata.resolved_execution_contract()
    expected = _canonical_nested_cv_contract()
    if actual is None or actual.digest != expected.digest:
        raise ValueError("out-of-fold evidence producer does not match the current canonical contract")


def _producer_identity(node_id: str) -> dict[str, str]:
    if not isinstance(node_id, str) or not node_id.strip():
        raise ValueError("out-of-fold producer node_id must be non-empty")
    contract = _canonical_nested_cv_contract()
    return {
        "operation_id": NESTED_CV_OPERATION_ID,
        "implementation_id": NESTED_CV_IMPLEMENTATION_ID,
        "execution_contract_digest": contract.digest,
        "node_id": node_id,
    }


def _normalized_sequence(value: Any, *, name: str) -> tuple[list[Any], np.ndarray]:
    array = np.asarray(value)
    if array.ndim != 1 or array.size < 2:
        raise ValueError(f"{name} must be a one-dimensional sequence with at least two samples")
    if array.dtype.kind in {"f", "c"}:
        if array.dtype.kind == "c" or not np.isfinite(array.astype(np.float64)).all():
            raise ValueError(f"{name} must not contain non-finite or complex values")
        normalized = np.asarray(array, dtype=np.float64)
        return normalized.tolist(), normalized
    if array.dtype.kind in {"i", "u"}:
        normalized = np.asarray(array, dtype=np.int64)
        return normalized.tolist(), normalized
    if array.dtype.kind in {"U", "S"}:
        normalized = np.asarray([str(item) for item in array], dtype=str)
        if any(not item for item in normalized.tolist()):
            raise ValueError(f"{name} must not contain empty labels")
        return normalized.tolist(), normalized
    if array.dtype.kind == "O":
        values = array.tolist()
        if not all(isinstance(item, (str, int, float)) and not isinstance(item, bool) for item in values):
            raise ValueError(f"{name} object values must be scalar strings or numbers")
        if any(isinstance(item, float) and not np.isfinite(item) for item in values):
            raise ValueError(f"{name} must not contain non-finite values")
        return list(values), np.asarray(values)
    raise ValueError(f"{name} uses an unsupported value representation")


def _normalized_split_plan(value: Any, *, n_samples: int) -> tuple[dict[str, Any], sdk_validate.SplitPlan]:
    if not isinstance(value, Mapping) or set(value) not in (_SPLIT_PLAN_FIELDS, _SPLIT_PLAN_FIELDS | {"groups"}):
        raise ValueError("out-of-fold split_plan must use the closed split-plan schema")
    if value.get("schema_version") not in {"spectra-split-plan/1", "spectra-grouped-split-plan/1"}:
        raise ValueError("unsupported out-of-fold split-plan schema")
    method = value.get("method")
    grouped = value.get("grouped")
    declared_n_samples = value.get("n_samples")
    if method not in {"kfold", "group_kfold"}:
        raise ValueError("out-of-fold split_plan method must be kfold or group_kfold")
    if not isinstance(grouped, bool) or grouped != (method == "group_kfold"):
        raise ValueError("out-of-fold split_plan grouped flag contradicts its method")
    if isinstance(declared_n_samples, bool) or declared_n_samples != n_samples:
        raise ValueError("out-of-fold split_plan sample count does not match its evidence vectors")
    raw_folds = value.get("folds")
    if not isinstance(raw_folds, Sequence) or isinstance(raw_folds, (str, bytes)) or len(raw_folds) < 2:
        raise ValueError("out-of-fold split_plan requires at least two folds")
    folds: list[sdk_validate.Fold] = []
    normalized_folds: list[dict[str, list[int]]] = []
    for fold_number, raw_fold in enumerate(raw_folds):
        if not isinstance(raw_fold, Mapping) or set(raw_fold) != _FOLD_FIELDS:
            raise ValueError(f"out-of-fold split_plan fold {fold_number} uses an invalid schema")
        train = np.asarray(raw_fold["train"])
        test = np.asarray(raw_fold["test"])
        if (
            train.ndim != 1
            or test.ndim != 1
            or train.dtype.kind not in {"i", "u"}
            or test.dtype.kind
            not in {
                "i",
                "u",
            }
        ):
            raise ValueError(f"out-of-fold split_plan fold {fold_number} indices must be integer vectors")
        train_i = np.asarray(train, dtype=np.int64)
        test_i = np.asarray(test, dtype=np.int64)
        folds.append(sdk_validate.Fold(train_i, test_i))
        normalized_folds.append({"train": train_i.tolist(), "test": test_i.tolist()})
    plan = sdk_validate.SplitPlan(
        method=str(method),
        n_samples=n_samples,
        folds=tuple(folds),
        grouped=grouped,
    )
    groups = None
    if grouped:
        if value.get("schema_version") != "spectra-grouped-split-plan/1" or "groups" not in value:
            raise ValueError("grouped out-of-fold evidence requires recorded group identities")
        raw_groups = value["groups"]
        if not isinstance(raw_groups, list) or len(raw_groups) != n_samples:
            raise ValueError("grouped evidence requires one group identity per row")
        groups = [sdk_validate._normalize_group_identity(v, name="evidence group") for v in raw_groups]
        if len({type(v) for v in groups}) != 1:
            raise ValueError("group identities must have a consistent scalar type")
    elif "groups" in value or value.get("schema_version") != "spectra-split-plan/1":
        raise ValueError("row-wise evidence cannot declare grouped identity")
    plan.validate(groups)
    normalized = {
        "schema_version": value["schema_version"],
        "method": plan.method,
        "n_samples": plan.n_samples,
        "grouped": plan.grouped,
        "folds": normalized_folds,
    }
    if groups is not None:
        normalized["groups"] = groups
    return normalized, plan


def _fold_assignments(plan: sdk_validate.SplitPlan) -> np.ndarray:
    assignments = np.full(plan.n_samples, -1, dtype=np.int64)
    for fold_number, fold in enumerate(plan.folds):
        assignments[np.asarray(fold.test, dtype=np.int64)] = fold_number
    if np.any(assignments < 0):
        raise ValueError("out-of-fold split_plan does not assign every sample to a validation fold")
    return assignments


def build_out_of_fold_evidence(
    *,
    producer_node_id: str,
    task_type: str,
    observations: Any,
    predictions: Any,
    split_plan: Mapping[str, Any],
) -> dict[str, Any]:
    """Build one current-producer evidence record and verify it immediately."""

    observed_values, observed = _normalized_sequence(observations, name="observations")
    predicted_values, predicted = _normalized_sequence(predictions, name="predictions")
    if observed.shape[0] != predicted.shape[0]:
        raise ValueError("out-of-fold observations and predictions must have equal length")
    if task_type != "regression":
        raise ValueError("the current out-of-fold evidence schema supports regression only")
    normalized_plan, plan = _normalized_split_plan(split_plan, n_samples=observed.shape[0])
    assignments = _fold_assignments(plan)
    payload: dict[str, Any] = {
        "schema_version": OUT_OF_FOLD_EVIDENCE_SCHEMA,
        "producer": _producer_identity(producer_node_id),
        "task_type": task_type,
        "observations": observed_values,
        "predictions": predicted_values,
        "fold_assignments": assignments.tolist(),
        "split_plan": normalized_plan,
        "split_plan_digest": plan.digest,
    }
    payload["evidence_sha256"] = _canonical_digest(payload)
    validate_out_of_fold_evidence(payload)
    return payload


def validate_out_of_fold_evidence(value: Any) -> tuple[dict[str, Any], np.ndarray, np.ndarray, np.ndarray]:
    """Validate and return the normalized record plus its three bound vectors."""

    if not isinstance(value, Mapping) or set(value) != _EVIDENCE_FIELDS:
        raise ValueError("out-of-fold evidence must use the closed evidence schema")
    if value.get("schema_version") != OUT_OF_FOLD_EVIDENCE_SCHEMA:
        raise ValueError("unsupported out-of-fold evidence schema")
    producer = value.get("producer")
    if not isinstance(producer, Mapping) or set(producer) != _PRODUCER_FIELDS:
        raise ValueError("out-of-fold evidence producer must use the closed producer schema")
    expected = _producer_identity(str(producer.get("node_id", "")))
    if dict(producer) != expected:
        raise ValueError("out-of-fold evidence producer does not match the current canonical contract")
    task_type = value.get("task_type")
    if task_type != "regression":
        raise ValueError("the current out-of-fold evidence schema supports regression only")
    observed_values, observed = _normalized_sequence(value.get("observations"), name="observations")
    predicted_values, predicted = _normalized_sequence(value.get("predictions"), name="predictions")
    if observed.shape[0] != predicted.shape[0]:
        raise ValueError("out-of-fold observations and predictions must have equal length")
    normalized_plan, plan = _normalized_split_plan(value.get("split_plan"), n_samples=observed.shape[0])
    assignments = np.asarray(value.get("fold_assignments"))
    if assignments.ndim != 1 or assignments.dtype.kind not in {"i", "u"}:
        raise ValueError("out-of-fold fold_assignments must be an integer vector")
    assignments_i = np.asarray(assignments, dtype=np.int64)
    expected_assignments = _fold_assignments(plan)
    if not np.array_equal(assignments_i, expected_assignments):
        raise ValueError("out-of-fold fold_assignments do not match the bound split_plan")
    if value.get("split_plan_digest") != plan.digest:
        raise ValueError("out-of-fold split_plan digest does not match the bound split_plan")
    normalized: dict[str, Any] = {
        "schema_version": OUT_OF_FOLD_EVIDENCE_SCHEMA,
        "producer": expected,
        "task_type": task_type,
        "observations": observed_values,
        "predictions": predicted_values,
        "fold_assignments": assignments_i.tolist(),
        "split_plan": normalized_plan,
        "split_plan_digest": plan.digest,
    }
    expected_digest = _canonical_digest(normalized)
    if value.get("evidence_sha256") != expected_digest:
        raise ValueError("out-of-fold evidence digest does not match its bound content")
    normalized["evidence_sha256"] = expected_digest
    return normalized, observed, predicted, assignments_i


__all__ = [
    "NESTED_CV_IMPLEMENTATION_ID",
    "NESTED_CV_OPERATION_ID",
    "OUT_OF_FOLD_EVIDENCE_SCHEMA",
    "OUT_OF_FOLD_EVIDENCE_TYPE",
    "build_out_of_fold_evidence",
    "require_canonical_out_of_fold_producer",
    "validate_out_of_fold_evidence",
]
