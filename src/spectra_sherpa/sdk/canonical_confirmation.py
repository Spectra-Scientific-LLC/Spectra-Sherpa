"""Current, sample-free evidence for one governed canonical confirmation.

Confirmation applies the already selected and full-development-refitted
canonical artifact to one separately governed dataset. It never re-runs
search, changes the selected graph, or fits against confirmation values.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

import numpy as np

from .validate import (
    CLASSIFICATION_METRIC_FIELDS,
    CLASSIFICATION_METRIC_SET_REGISTRY_VERSION,
    REGRESSION_METRIC_FIELDS,
    REGRESSION_METRIC_REGISTRY_VERSION,
    bootstrap_regression_uncertainty,
    classification_metric_set,
    metrics,
    supervised_metric_task,
    validate_supervised_metric_record,
)

CANONICAL_CONFIRMATION_PLAN_VERSION = "spectra-canonical-confirmation-plan/3"
CANONICAL_CONFIRMATION_EVIDENCE_VERSION = "spectra-canonical-confirmation-evidence/3"
SIMCA_CONFIRMATION_PLAN_VERSION = "spectra-canonical-confirmation-plan/4"
SIMCA_CONFIRMATION_EVIDENCE_VERSION = "spectra-canonical-confirmation-evidence/4"
LEGACY_CANONICAL_CONFIRMATION_PLAN_VERSION = "spectra-canonical-confirmation-plan/2"
LEGACY_CANONICAL_CONFIRMATION_EVIDENCE_VERSION = "spectra-canonical-confirmation-evidence/2"
_LEGACY_PLAN_VERSION = LEGACY_CANONICAL_CONFIRMATION_PLAN_VERSION
_LEGACY_EVIDENCE_VERSION = LEGACY_CANONICAL_CONFIRMATION_EVIDENCE_VERSION
_REGRESSION_REPORTED_METRICS = ["bias", "intercept", "mae", "r2", "rer", "rmse", "sep", "slope"]
_CLASSIFICATION_REPORTED_METRICS = ["accuracy", "balanced_accuracy", "macro_f1", "mcc"]
_SIMCA_REPORTED_METRICS = [
    "mean_class_acceptance_sensitivity",
    "unassigned_rate",
    "multiple_acceptance_rate",
]

_DIGEST = re.compile(r"^[0-9a-f]{64}$")
_LEGACY_PLAN_FIELDS = frozenset(
    {"schema_version", "metric_registry_version", "primary_metric", "reported_metrics", "uncertainty"}
)
_PLAN_FIELDS = _LEGACY_PLAN_FIELDS | {"task_type"}
_LEGACY_EVIDENCE_FIELDS = frozenset(
    {
        "schema_version",
        "request_digest",
        "graph_digest",
        "selected_validation_request_digest",
        "winner_refit_authority_digest",
        "artifact_digest",
        "application_plan_digest",
        "capability_content_digest",
        "capability_envelope_digest",
        "dataset_ref_digest",
        "split_plan_digest",
        "metrics",
        "uncertainty",
        "evidence_digest",
    }
)
_EVIDENCE_FIELDS = _LEGACY_EVIDENCE_FIELDS | {"task_type"}


class CanonicalConfirmationError(ValueError):
    """A confirmation plan or aggregate evidence record is not current."""


@dataclass(frozen=True)
class CanonicalConfirmationPlan:
    """Frozen scalar-metric and grouped-bootstrap design."""

    uncertainty_resamples: int
    uncertainty_confidence: float
    uncertainty_seed: int
    task_type: str = "regression"
    primary_metric: str | None = None
    schema_version: str = CANONICAL_CONFIRMATION_PLAN_VERSION

    @classmethod
    def for_validation(
        cls,
        uncertainty_resamples: int,
        uncertainty_confidence: float,
        uncertainty_seed: int,
        *,
        task_type: str,
        primary_metric: str,
    ) -> "CanonicalConfirmationPlan":
        """Bind confirmation to the selected development objective, not a model default."""

        return cls(
            uncertainty_resamples,
            uncertainty_confidence,
            uncertainty_seed,
            task_type=task_type,
            primary_metric=primary_metric,
            schema_version=(
                SIMCA_CONFIRMATION_PLAN_VERSION
                if primary_metric == "mean_class_acceptance_sensitivity"
                else CANONICAL_CONFIRMATION_PLAN_VERSION
            ),
        )

    def __post_init__(self) -> None:
        if (
            isinstance(self.uncertainty_resamples, bool)
            or not isinstance(self.uncertainty_resamples, int)
            or not 100 <= self.uncertainty_resamples <= 100_000
        ):
            raise CanonicalConfirmationError("uncertainty_resamples must be an integer from 100 through 100000")
        if (
            isinstance(self.uncertainty_confidence, bool)
            or not isinstance(self.uncertainty_confidence, (int, float))
            or not 0.5 <= float(self.uncertainty_confidence) < 1.0
        ):
            raise CanonicalConfirmationError("uncertainty_confidence must be from 0.5 up to but excluding 1")
        if (
            isinstance(self.uncertainty_seed, bool)
            or not isinstance(self.uncertainty_seed, int)
            or not 0 <= self.uncertainty_seed <= 2**32 - 1
        ):
            raise CanonicalConfirmationError("uncertainty_seed must be an unsigned 32-bit integer")
        if self.task_type not in {"regression", "classification"}:
            raise CanonicalConfirmationError("confirmation task_type is unsupported")
        if self.schema_version not in {
            _LEGACY_PLAN_VERSION,
            CANONICAL_CONFIRMATION_PLAN_VERSION,
            SIMCA_CONFIRMATION_PLAN_VERSION,
        }:
            raise CanonicalConfirmationError("confirmation plan schema_version is unsupported")
        if self.schema_version == _LEGACY_PLAN_VERSION and self.task_type != "regression":
            raise CanonicalConfirmationError("legacy confirmation plans support regression only")
        expected_primary = (
            "mean_class_acceptance_sensitivity"
            if self.schema_version == SIMCA_CONFIRMATION_PLAN_VERSION
            else "balanced_accuracy" if self.task_type == "classification" else "rmse"
        )
        if self.primary_metric is None:
            object.__setattr__(self, "primary_metric", expected_primary)
        if self.primary_metric != expected_primary or (
            self.schema_version == SIMCA_CONFIRMATION_PLAN_VERSION and self.task_type != "classification"
        ):
            raise CanonicalConfirmationError("confirmation primary metric differs from its governed objective")

    def as_dict(self) -> dict[str, Any]:
        classification = self.task_type == "classification"
        simca = self.schema_version == SIMCA_CONFIRMATION_PLAN_VERSION
        value = {
            "schema_version": self.schema_version,
            "metric_registry_version": (
                CLASSIFICATION_METRIC_SET_REGISTRY_VERSION if classification else REGRESSION_METRIC_REGISTRY_VERSION
            ),
            "primary_metric": self.primary_metric,
            "reported_metrics": (
                _SIMCA_REPORTED_METRICS
                if simca
                else _CLASSIFICATION_REPORTED_METRICS if classification else _REGRESSION_REPORTED_METRICS
            ),
            "uncertainty": {
                "method": "grouped_bootstrap",
                "method_version": "2" if simca else "1",
                "n_resamples": self.uncertainty_resamples,
                "confidence_level": float(self.uncertainty_confidence),
                "random_state": self.uncertainty_seed,
            },
        }
        if self.schema_version != _LEGACY_PLAN_VERSION:
            value["task_type"] = self.task_type
        return value

    @property
    def digest(self) -> str:
        return _digest(self.as_dict())

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "CanonicalConfirmationPlan":
        version = value.get("schema_version") if isinstance(value, Mapping) else None
        legacy = version == _LEGACY_PLAN_VERSION
        _closed(value, _LEGACY_PLAN_FIELDS if legacy else _PLAN_FIELDS, "canonical confirmation plan")
        task_type = "regression" if legacy else value.get("task_type")
        classification = task_type == "classification"
        simca = version == SIMCA_CONFIRMATION_PLAN_VERSION
        if (
            version not in {_LEGACY_PLAN_VERSION, CANONICAL_CONFIRMATION_PLAN_VERSION, SIMCA_CONFIRMATION_PLAN_VERSION}
            or (
                legacy
                and (
                    value["metric_registry_version"] != REGRESSION_METRIC_REGISTRY_VERSION
                    or value["primary_metric"] != "rmse"
                    or value["reported_metrics"] != _REGRESSION_REPORTED_METRICS
                )
            )
            or (
                not legacy
                and (
                    task_type not in {"regression", "classification"}
                    or (simca and not classification)
                    or value["metric_registry_version"]
                    != (
                        CLASSIFICATION_METRIC_SET_REGISTRY_VERSION
                        if classification
                        else REGRESSION_METRIC_REGISTRY_VERSION
                    )
                    or value["primary_metric"]
                    != (
                        "mean_class_acceptance_sensitivity"
                        if simca
                        else "balanced_accuracy" if classification else "rmse"
                    )
                    or value["reported_metrics"]
                    != (
                        _SIMCA_REPORTED_METRICS
                        if simca
                        else _CLASSIFICATION_REPORTED_METRICS if classification else _REGRESSION_REPORTED_METRICS
                    )
                )
            )
        ):
            raise CanonicalConfirmationError("canonical confirmation metric semantics are unsupported")
        uncertainty = value["uncertainty"]
        _closed(
            uncertainty,
            {"method", "method_version", "n_resamples", "confidence_level", "random_state"},
            "canonical confirmation uncertainty plan",
        )
        if uncertainty["method"] != "grouped_bootstrap" or uncertainty["method_version"] != ("2" if simca else "1"):
            raise CanonicalConfirmationError("canonical confirmation uncertainty semantics are unsupported")
        return cls(
            uncertainty_resamples=uncertainty["n_resamples"],
            uncertainty_confidence=uncertainty["confidence_level"],
            uncertainty_seed=uncertainty["random_state"],
            task_type=task_type,
            primary_metric=value["primary_metric"],
            schema_version=version,
        )


@dataclass(frozen=True)
class CanonicalConfirmationEvidence:
    """Verified aggregate result of applying one frozen canonical artifact."""

    payload: dict[str, Any]
    evidence_digest: str

    @classmethod
    def build(
        cls,
        *,
        request_digest: str,
        graph_digest: str,
        selected_validation_request_digest: str,
        winner_refit_authority_digest: str,
        artifact_digest: str,
        application_plan_digest: str,
        capability_content_digest: str,
        capability_envelope_digest: str,
        dataset_ref_digest: str,
        split_plan_digest: str,
        observed: Sequence[Any] | np.ndarray,
        predicted: Sequence[Any] | np.ndarray,
        groups: Sequence[object] | np.ndarray | None,
        plan: CanonicalConfirmationPlan,
        simca_membership: Sequence[Sequence[bool]] | np.ndarray | None = None,
        simca_labels: Sequence[Any] | None = None,
    ) -> "CanonicalConfirmationEvidence":
        if not isinstance(plan, CanonicalConfirmationPlan):
            raise CanonicalConfirmationError("confirmation evidence requires the current plan")
        simca = plan.schema_version == SIMCA_CONFIRMATION_PLAN_VERSION
        if simca != (simca_membership is not None) or simca != (simca_labels is not None):
            raise CanonicalConfirmationError("confirmation acceptance evidence differs from its metric plan")
        if plan.task_type == "classification":
            y_true = _label_column(observed, "observed")
            y_pred = _label_column(predicted, "predicted")
        else:
            y_true = _one_column(observed, "observed")
            y_pred = _one_column(predicted, "predicted")
        if y_true.shape != y_pred.shape:
            raise CanonicalConfirmationError("confirmation observations and predictions differ in shape")
        group_array = None if groups is None else np.asarray(groups)
        if group_array is not None and (group_array.ndim != 1 or group_array.size != y_true.size):
            raise CanonicalConfirmationError("confirmation groups differ from the evaluated samples")
        if plan.task_type == "classification":
            labels = (
                [*simca_labels, "unassigned"]
                if simca and simca_labels is not None
                else _unique_labels([*y_true.tolist(), *y_pred.tolist()])
            )
            if simca and any(_labels_equal(label, "unassigned") for label in simca_labels):
                raise CanonicalConfirmationError("SIMCA class identity conflicts with the rejection label")
            if simca and any(
                not any(_labels_equal(observed_label, fitted_label) for observed_label in y_true)
                for fitted_label in simca_labels
            ):
                raise CanonicalConfirmationError("SIMCA confirmation requires observations for every fitted class")
            try:
                scalar = classification_metric_set(
                    y_true,
                    y_pred,
                    labels=labels,
                    simca_membership=simca_membership,
                    simca_labels=simca_labels,
                )
            except ValueError as exc:
                raise CanonicalConfirmationError("confirmation acceptance membership is invalid") from exc
            uncertainty_payload = _classification_uncertainty(
                y_true,
                y_pred,
                groups=group_array,
                labels=labels,
                simca_membership=simca_membership,
                simca_labels=simca_labels,
                n_resamples=plan.uncertainty_resamples,
                confidence_level=plan.uncertainty_confidence,
                random_state=plan.uncertainty_seed,
            )
        else:
            scalar = metrics(y_true, y_pred)
            uncertainty = bootstrap_regression_uncertainty(
                y_true,
                y_pred,
                groups=group_array,
                n_resamples=plan.uncertainty_resamples,
                confidence_level=plan.uncertainty_confidence,
                random_state=plan.uncertainty_seed,
            )
            uncertainty_payload = uncertainty.as_dict()
        unsigned = {
            "schema_version": (
                SIMCA_CONFIRMATION_EVIDENCE_VERSION if simca else CANONICAL_CONFIRMATION_EVIDENCE_VERSION
            ),
            "task_type": plan.task_type,
            "request_digest": request_digest,
            "graph_digest": graph_digest,
            "selected_validation_request_digest": selected_validation_request_digest,
            "winner_refit_authority_digest": winner_refit_authority_digest,
            "artifact_digest": artifact_digest,
            "application_plan_digest": application_plan_digest,
            "capability_content_digest": capability_content_digest,
            "capability_envelope_digest": capability_envelope_digest,
            "dataset_ref_digest": dataset_ref_digest,
            "split_plan_digest": split_plan_digest,
            "metrics": scalar.as_dict(),
            "uncertainty": uncertainty_payload,
        }
        for field in (
            "request_digest",
            "graph_digest",
            "selected_validation_request_digest",
            "winner_refit_authority_digest",
            "artifact_digest",
            "application_plan_digest",
            "capability_content_digest",
            "capability_envelope_digest",
            "dataset_ref_digest",
            "split_plan_digest",
        ):
            _require_digest(unsigned[field], field)
        return cls._validated({**unsigned, "evidence_digest": _digest(unsigned)})

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "CanonicalConfirmationEvidence":
        return cls._validated(value)

    @classmethod
    def _validated(cls, value: Mapping[str, Any]) -> "CanonicalConfirmationEvidence":
        version = value.get("schema_version") if isinstance(value, Mapping) else None
        legacy = version == _LEGACY_EVIDENCE_VERSION
        _closed(value, _LEGACY_EVIDENCE_FIELDS if legacy else _EVIDENCE_FIELDS, "canonical confirmation evidence")
        if version not in {
            _LEGACY_EVIDENCE_VERSION,
            CANONICAL_CONFIRMATION_EVIDENCE_VERSION,
            SIMCA_CONFIRMATION_EVIDENCE_VERSION,
        }:
            raise CanonicalConfirmationError("canonical confirmation evidence schema is unsupported")
        task_type = "regression" if legacy else value.get("task_type")
        if task_type not in {"regression", "classification"}:
            raise CanonicalConfirmationError("canonical confirmation evidence task is unsupported")
        fields = _LEGACY_EVIDENCE_FIELDS if legacy else _EVIDENCE_FIELDS
        for field in fields - {"schema_version", "task_type", "metrics", "uncertainty"}:
            _require_digest(value[field], field)
        simca = version == SIMCA_CONFIRMATION_EVIDENCE_VERSION
        if simca and task_type != "classification":
            raise CanonicalConfirmationError("acceptance confirmation requires classification evidence")
        _validate_metrics(value["metrics"], task_type=task_type, simca=simca)
        _validate_uncertainty(value["uncertainty"], task_type=task_type, simca=simca)
        unsigned = {key: deepcopy(item) for key, item in value.items() if key != "evidence_digest"}
        if _digest(unsigned) != value["evidence_digest"]:
            raise CanonicalConfirmationError("canonical confirmation evidence digest mismatch")
        return cls(payload=deepcopy(unsigned), evidence_digest=value["evidence_digest"])

    def as_dict(self) -> dict[str, Any]:
        return {**deepcopy(self.payload), "evidence_digest": self.evidence_digest}


def _classification_uncertainty(
    observed: np.ndarray,
    predicted: np.ndarray,
    *,
    groups: np.ndarray | None,
    labels: Sequence[Any],
    simca_membership: Sequence[Sequence[bool]] | np.ndarray | None,
    simca_labels: Sequence[Any] | None,
    n_resamples: int,
    confidence_level: float,
    random_state: int,
) -> dict[str, Any]:
    """Bootstrap protected classification aggregates without changing DAG authority."""

    if len(_unique_labels(observed.tolist())) < 2:
        raise CanonicalConfirmationError("classification confirmation requires at least two observed classes")
    rng = np.random.default_rng(random_state)
    class_rows = (
        [
            np.flatnonzero(np.asarray([_labels_equal(value, label) for value in observed], dtype=bool))
            for label in simca_labels
        ]
        if simca_labels is not None
        else None
    )
    if groups is None:
        draws = (
            [
                np.concatenate([rng.choice(rows, size=rows.size, replace=True) for rows in class_rows])
                for _ in range(n_resamples)
            ]
            if class_rows is not None
            else [rng.integers(0, observed.size, size=observed.size) for _ in range(n_resamples)]
        )
    else:
        unique_groups = _unique_labels(groups.tolist())
        group_rows = [
            np.flatnonzero(np.asarray([_labels_equal(value, group) for value in groups], dtype=bool))
            for group in unique_groups
        ]
        draws = []
        attempts = 0
        while len(draws) < n_resamples and attempts < 20 * n_resamples:
            attempts += 1
            index = np.concatenate(
                [group_rows[group_index] for group_index in rng.integers(0, len(group_rows), size=len(group_rows))]
            )
            if class_rows is None or all(np.intersect1d(index, rows).size for rows in class_rows):
                draws.append(index)
        if len(draws) != n_resamples:
            raise CanonicalConfirmationError("grouped SIMCA confirmation cannot preserve fitted-class support")
    membership = None if simca_membership is None else np.asarray(simca_membership)
    values = [
        classification_metric_set(
            observed[index],
            predicted[index],
            labels=labels,
            simca_membership=None if membership is None else membership[index],
            simca_labels=simca_labels,
        )
        for index in draws
    ]
    alpha = (1.0 - confidence_level) / 2.0

    def interval(field: str) -> dict[str, float]:
        samples = np.asarray([getattr(value, field) for value in values], dtype=np.float64)
        lower, upper = np.quantile(samples, [alpha, 1.0 - alpha])
        return {"lower": float(lower), "upper": float(upper)}

    if membership is not None:
        return {
            "registry_version": CLASSIFICATION_METRIC_SET_REGISTRY_VERSION,
            "confidence_level": float(confidence_level),
            "n_resamples": n_resamples,
            "grouped": groups is not None,
            "mean_class_acceptance_sensitivity": interval("mean_class_acceptance_sensitivity"),
            "unassigned_rate": interval("unassigned_rate"),
            "multiple_acceptance_rate": interval("multiple_acceptance_rate"),
        }
    return {
        "registry_version": CLASSIFICATION_METRIC_SET_REGISTRY_VERSION,
        "confidence_level": float(confidence_level),
        "n_resamples": n_resamples,
        "grouped": groups is not None,
        "accuracy": interval("accuracy"),
        "balanced_accuracy": interval("balanced_accuracy"),
        "macro_f1": interval("macro_f1"),
        "mcc": interval("mcc"),
    }


def _unique_labels(values: Sequence[Any]) -> list[Any]:
    labels: list[Any] = []
    for value in values:
        if not any(_labels_equal(value, label) for label in labels):
            labels.append(value)
    return labels


def _labels_equal(left: Any, right: Any) -> bool:
    result = left == right
    return bool(result) if isinstance(result, (bool, np.bool_)) else False


def _validate_metrics(value: Any, *, task_type: str, simca: bool = False) -> None:
    expected_fields = CLASSIFICATION_METRIC_FIELDS if task_type == "classification" else REGRESSION_METRIC_FIELDS
    if not isinstance(value, Mapping) or set(value) != expected_fields:
        raise CanonicalConfirmationError("canonical confirmation metrics use an unsupported schema")
    try:
        validated = validate_supervised_metric_record(value)
    except ValueError as exc:
        raise CanonicalConfirmationError("canonical confirmation metric registry is unsupported") from exc
    if supervised_metric_task(validated) != task_type:
        raise CanonicalConfirmationError("canonical confirmation metric task changed")
    if simca and (value["simca_acceptance"] is None or value["mean_class_acceptance_sensitivity"] is None):
        raise CanonicalConfirmationError("canonical confirmation acceptance metrics are missing")
    if not simca and task_type == "classification" and value["simca_acceptance"] is not None:
        raise CanonicalConfirmationError("ordinary classification cannot carry acceptance metrics")
    if isinstance(value["n_samples"], bool) or not isinstance(value["n_samples"], int) or value["n_samples"] < 2:
        raise CanonicalConfirmationError("canonical confirmation sample count is invalid")
    if task_type == "regression":
        for field in REGRESSION_METRIC_FIELDS - {"registry_version", "n_samples"}:
            if value[field] is not None:
                _finite(value[field], field)


def _validate_uncertainty(value: Any, *, task_type: str, simca: bool = False) -> None:
    metric_fields = (
        {"mean_class_acceptance_sensitivity", "unassigned_rate", "multiple_acceptance_rate"}
        if simca
        else (
            {"accuracy", "balanced_accuracy", "macro_f1", "mcc"}
            if task_type == "classification"
            else {"rmse", "mae", "bias", "r2", "sep", "slope", "intercept", "rer"}
        )
    )
    required = {"registry_version", "confidence_level", "n_resamples", "grouped", *metric_fields}
    if not isinstance(value, Mapping) or set(value) != required:
        raise CanonicalConfirmationError("canonical confirmation uncertainty uses an unsupported schema")
    expected_registry = (
        CLASSIFICATION_METRIC_SET_REGISTRY_VERSION
        if task_type == "classification"
        else REGRESSION_METRIC_REGISTRY_VERSION
    )
    if value["registry_version"] != expected_registry or not isinstance(value["grouped"], bool):
        raise CanonicalConfirmationError("canonical confirmation uncertainty identity is invalid")
    if (
        isinstance(value["n_resamples"], bool)
        or not isinstance(value["n_resamples"], int)
        or value["n_resamples"] < 100
    ):
        raise CanonicalConfirmationError("canonical confirmation uncertainty resamples are invalid")
    confidence = value["confidence_level"]
    if isinstance(confidence, bool) or not isinstance(confidence, (int, float)) or not 0.5 <= float(confidence) < 1.0:
        raise CanonicalConfirmationError("canonical confirmation uncertainty confidence is invalid")
    for field in metric_fields:
        interval = value[field]
        if task_type == "regression" and interval is None and field in {"r2", "sep", "slope", "intercept", "rer"}:
            continue
        if not isinstance(interval, Mapping) or set(interval) != {"lower", "upper"}:
            raise CanonicalConfirmationError("canonical confirmation uncertainty interval is invalid")
        _finite(interval["lower"], f"{field}.lower")
        _finite(interval["upper"], f"{field}.upper")
        if float(interval["lower"]) > float(interval["upper"]):
            raise CanonicalConfirmationError("canonical confirmation uncertainty interval is reversed")
        if task_type == "classification":
            lower = float(interval["lower"])
            upper = float(interval["upper"])
            floor = -1.0 if field == "mcc" else 0.0
            if lower < floor or upper > 1.0:
                raise CanonicalConfirmationError("canonical confirmation classification interval is out of range")


def _one_column(value: Sequence[float] | np.ndarray, field: str) -> np.ndarray:
    try:
        array = np.asarray(value, dtype=np.float64)
    except (TypeError, ValueError) as exc:
        raise CanonicalConfirmationError(f"canonical confirmation {field} values are invalid") from exc
    if array.ndim == 2 and array.shape[1] == 1:
        array = array[:, 0]
    if array.ndim != 1 or array.size < 2 or not np.isfinite(array).all():
        raise CanonicalConfirmationError(f"canonical confirmation {field} values must be finite and one-dimensional")
    return np.array(array, copy=True)


def _label_column(value: Sequence[Any] | np.ndarray, field: str) -> np.ndarray:
    array = np.asarray(value, dtype=object)
    if array.ndim == 2 and array.shape[1] == 1:
        array = array[:, 0]
    if array.ndim != 1 or array.size < 2:
        raise CanonicalConfirmationError(f"canonical confirmation {field} labels must be one-dimensional")
    normalized: list[str | int | float | bool] = []
    for raw in array:
        label = raw.item() if isinstance(raw, np.generic) else raw
        if (
            label is None
            or isinstance(label, (list, tuple, dict, set, bytes, bytearray))
            or not isinstance(label, (str, int, float, bool))
            or (isinstance(label, float) and not math.isfinite(label))
            or (isinstance(label, str) and (not label or len(label) > 256))
        ):
            raise CanonicalConfirmationError(f"canonical confirmation {field} labels are invalid")
        normalized.append(label)
    return np.asarray(normalized, dtype=object)


def _finite(value: Any, field: str) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
        raise CanonicalConfirmationError(f"canonical confirmation {field} must be finite")


def _closed(value: Any, fields: set[str] | frozenset[str], name: str) -> None:
    if not isinstance(value, Mapping) or set(value) != set(fields):
        raise CanonicalConfirmationError(f"{name} fields are closed")


def _require_digest(value: Any, field: str) -> None:
    if not isinstance(value, str) or _DIGEST.fullmatch(value) is None:
        raise CanonicalConfirmationError(f"canonical confirmation {field} must be lowercase SHA-256")


def _digest(value: Mapping[str, Any]) -> str:
    try:
        encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise CanonicalConfirmationError("canonical confirmation content must be finite JSON") from exc
    return hashlib.sha256(encoded).hexdigest()


__all__ = [
    "CANONICAL_CONFIRMATION_EVIDENCE_VERSION",
    "CANONICAL_CONFIRMATION_PLAN_VERSION",
    "LEGACY_CANONICAL_CONFIRMATION_EVIDENCE_VERSION",
    "LEGACY_CANONICAL_CONFIRMATION_PLAN_VERSION",
    "SIMCA_CONFIRMATION_EVIDENCE_VERSION",
    "SIMCA_CONFIRMATION_PLAN_VERSION",
    "CanonicalConfirmationError",
    "CanonicalConfirmationEvidence",
    "CanonicalConfirmationPlan",
]
