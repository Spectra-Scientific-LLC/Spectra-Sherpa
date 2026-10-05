"""Validation contracts and metric primitives shared by canonical execution.

This module owns portable metric definitions, split plans, uncertainty
records, and fold-result aggregation. It deliberately does not fit arbitrary
estimators: scientific fitting and validation execute only through admitted
canonical DAG operations and the fold-lifecycle executor.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, replace
from typing import Any, Mapping, Sequence

import numpy as np
from sklearn.model_selection import GroupKFold, KFold, StratifiedGroupKFold, StratifiedKFold

METRIC_REGISTRY_VERSION = "1"
CLASSIFICATION_METRIC_SET_REGISTRY_VERSION = "2"
REGRESSION_METRIC_REGISTRY_VERSION = "2"
# Version 1 accepts ordinary IEEE-754/BLAS-level variation while keeping a
# scientific-score regression visible. The bound is absolute + relative,
# following ``numpy.isclose`` semantics: ``abs(a - b) <= 1e-12 + 1e-9*abs(a)``.
METRIC_PARITY_ABSOLUTE_TOLERANCE = 1e-12
METRIC_PARITY_RELATIVE_TOLERANCE = 1e-9


@dataclass(frozen=True)
class RegressionMetrics:
    """Versioned, explicitly defined regression metrics.

    ``r2``, ``slope``, and ``intercept`` are ``None`` when the reference is
    constant or fewer than two observations exist. ``sep`` is the
    bias-corrected residual standard deviation and is undefined for one
    observation. ``rer`` is the reference range divided by SEP and is
    undefined when SEP is absent or zero.
    """

    registry_version: str
    n_samples: int
    rmse: float
    mae: float
    bias: float
    r2: float | None
    sep: float | None = None
    slope: float | None = None
    intercept: float | None = None
    rer: float | None = None

    def as_dict(self) -> dict[str, float | int | str | None]:
        return {
            "registry_version": self.registry_version,
            "n_samples": self.n_samples,
            "rmse": self.rmse,
            "mae": self.mae,
            "bias": self.bias,
            "r2": self.r2,
            "sep": self.sep,
            "slope": self.slope,
            "intercept": self.intercept,
            "rer": self.rer,
        }


def _centered_scaled_values(values: np.ndarray, origin: float, previous_scale: float) -> tuple[np.ndarray, float]:
    """Subtract a retained origin before dividing whenever subtraction is finite."""
    with np.errstate(over="ignore"):
        shifted = values - origin
    if np.isfinite(shifted).all():
        scale = max(previous_scale, float(np.max(np.abs(shifted))))
        return (shifted / scale if scale else shifted), scale
    scale = max(previous_scale, float(np.max(np.abs(values))), abs(origin))
    return values / scale - origin / scale, scale


@dataclass
class RegressionMetricAccumulator:
    """Private mergeable accumulator for exact pooled regression metrics.

    This holds no arrays and is intentionally not an evidence payload.  It
    uses scaled, centered (Chan/Welford) second moments instead of ``sum(y²)-sum(y)²
    / n``, which is numerically unsafe for large-offset calibration targets.
    The reference/constant flag exists only while accumulating so the final
    metric preserves the registry's explicit undefined-R² behavior.
    """

    count: int = 0
    observed_mean: float = 0.0
    observed_m2: float = 0.0
    predicted_mean: float = 0.0
    observed_predicted_cross_m2: float = 0.0
    observed_min: float = np.inf
    observed_max: float = -np.inf
    sum_residual: float = 0.0
    sum_absolute_residual: float = 0.0
    sum_squared_residual: float = 0.0
    residual_mean: float = 0.0
    residual_m2: float = 0.0
    _scale: float = 0.0
    _residual_scale: float = 0.0
    _prediction_scale: float = 0.0
    _residual_variation_scale: float = 0.0
    _prediction_origin: float | None = None
    _residual_origin: float | None = None
    _reference_observed: float | None = None
    _all_observed_equal_to_reference: bool = True

    def add(self, y_true: Sequence[float] | np.ndarray, y_pred: Sequence[float] | np.ndarray) -> None:
        """Add one finite held-out fold without retaining its rows."""

        observed = _as_target(y_true, "y_true")
        predicted = _as_target(y_pred, "y_pred")
        if observed.shape != predicted.shape or not np.isfinite(observed).all() or not np.isfinite(predicted).all():
            raise ValueError("metric accumulator requires equal finite y_true and y_pred values")
        batch_count = int(observed.size)
        if batch_count < 1:
            raise ValueError("metric accumulator requires at least one sample")
        reference = float(observed[0]) if self._reference_observed is None else self._reference_observed
        self._reference_observed = reference
        self._all_observed_equal_to_reference = self._all_observed_equal_to_reference and bool(
            np.all(observed == reference)
        )
        if self._prediction_origin is None:
            self._prediction_origin = float(predicted[0])
        normalized_observed, scale = _centered_scaled_values(observed, reference, self._scale)
        normalized_predicted, prediction_scale = _centered_scaled_values(
            predicted, self._prediction_origin, self._prediction_scale
        )
        if self.count:
            x_ratio = self._scale / scale if scale else 1.0
            y_ratio = self._prediction_scale / prediction_scale if prediction_scale else 1.0
            self.observed_mean *= x_ratio
            self.observed_m2 *= x_ratio * x_ratio
            self.predicted_mean *= y_ratio
            self.observed_predicted_cross_m2 *= x_ratio * y_ratio
        self._scale = scale
        self._prediction_scale = prediction_scale
        batch_mean = float(np.mean(normalized_observed))
        batch_predicted_mean = float(np.mean(normalized_predicted))
        observed_centered = normalized_observed - batch_mean
        predicted_centered = normalized_predicted - batch_predicted_mean
        batch_m2 = float(np.sum(observed_centered**2))
        batch_cross_m2 = float(np.sum(observed_centered * predicted_centered))
        with np.errstate(over="ignore"):
            raw_residual = predicted - observed
        if not np.isfinite(raw_residual).all():
            raise ValueError("residual differences exceed the supported floating-point dynamic range")
        residual_scale = max(self._residual_scale, float(np.max(np.abs(raw_residual))))
        residual = raw_residual / residual_scale if residual_scale else raw_residual
        if self.count and residual_scale != self._residual_scale:
            ratio = self._residual_scale / residual_scale
            for name in ("sum_residual", "sum_absolute_residual"):
                setattr(self, name, getattr(self, name) * ratio)
            self.sum_squared_residual *= ratio * ratio
        self._residual_scale = residual_scale
        if self._residual_origin is None:
            self._residual_origin = float(raw_residual[0])
        centered_residual, variation_scale = _centered_scaled_values(
            raw_residual, self._residual_origin, self._residual_variation_scale
        )
        if self.count and variation_scale != self._residual_variation_scale:
            ratio = self._residual_variation_scale / variation_scale
            self.residual_mean *= ratio
            self.residual_m2 *= ratio * ratio
        self._residual_variation_scale = variation_scale
        batch_residual_mean = float(np.mean(centered_residual))
        batch_residual_m2 = float(np.sum((centered_residual - batch_residual_mean) ** 2))
        if self.count:
            delta = batch_mean - self.observed_mean
            predicted_delta = batch_predicted_mean - self.predicted_mean
            residual_delta = batch_residual_mean - self.residual_mean
            total = self.count + batch_count
            weight = self.count * batch_count / total
            self.observed_m2 += batch_m2 + delta * delta * weight
            self.observed_predicted_cross_m2 += batch_cross_m2 + delta * predicted_delta * weight
            self.residual_m2 += batch_residual_m2 + residual_delta * residual_delta * weight
            self.observed_mean += delta * batch_count / total
            self.predicted_mean += predicted_delta * batch_count / total
            self.residual_mean += residual_delta * batch_count / total
        else:
            self.observed_mean = batch_mean
            self.observed_m2 = batch_m2
            self.predicted_mean = batch_predicted_mean
            self.observed_predicted_cross_m2 = batch_cross_m2
            self.residual_mean = batch_residual_mean
            self.residual_m2 = batch_residual_m2
        self.count += batch_count
        self.observed_min = min(self.observed_min, float(np.min(observed)))
        self.observed_max = max(self.observed_max, float(np.max(observed)))
        self.sum_residual += float(np.sum(residual))
        self.sum_absolute_residual += float(np.sum(np.abs(residual)))
        self.sum_squared_residual += float(np.sum(residual**2))

    def metrics(self) -> RegressionMetrics:
        """Return one pooled registry-v2 record without retaining source rows."""

        if self.count < 1:
            raise ValueError("metric accumulator has no samples")
        constant = self.count < 2 or self._all_observed_equal_to_reference
        if not constant and (self.observed_m2 <= 0 or not np.isfinite(self.observed_m2)):
            raise ValueError("reference variation exceeds the supported floating-point dynamic range")
        with np.errstate(over="ignore", under="ignore", invalid="ignore"):
            error_ratio = 0.0 if not self._scale else np.float64(self._residual_scale) / self._scale
            r2 = (
                None
                if constant
                else float(1.0 - (error_ratio * error_ratio) * self.sum_squared_residual / self.observed_m2)
            )
        normalized_sep = None if self.count < 2 else float(np.sqrt(self.residual_m2 / (self.count - 1)))
        sep = None if normalized_sep is None else normalized_sep * self._residual_variation_scale
        slope = (
            None
            if constant
            else float((self.observed_predicted_cross_m2 / self.observed_m2) * (self._prediction_scale / self._scale))
        )
        origin = self._reference_observed or 0.0
        intercept = (
            None
            if slope is None
            else float(
                (self._prediction_origin or 0.0)
                - slope * origin
                + self._prediction_scale * self.predicted_mean
                - slope * self._scale * self.observed_mean
            )
        )
        span = self.observed_max - self.observed_min
        if sep is None or sep <= 0.0:
            rer = None
        elif np.isfinite(span):
            rer = span / sep
        else:
            rer = self.observed_max / sep - self.observed_min / sep
        result = RegressionMetrics(
            registry_version=REGRESSION_METRIC_REGISTRY_VERSION,
            n_samples=self.count,
            rmse=float(np.sqrt(self.sum_squared_residual / self.count)) * self._residual_scale,
            mae=float(self.sum_absolute_residual / self.count) * self._residual_scale,
            bias=float(self.sum_residual / self.count) * self._residual_scale,
            r2=r2,
            sep=sep,
            slope=slope,
            intercept=intercept,
            rer=rer,
        )
        if any(
            value is not None and not np.isfinite(value)
            for key, value in result.as_dict().items()
            if key != "registry_version"
        ):
            raise ValueError("regression metrics exceed the supported floating-point dynamic range")
        return result


@dataclass(frozen=True)
class ClassificationMetrics:
    """Versioned binary-classification metrics with an explicit positive class.

    Sensitivity is true-positive rate and specificity is true-negative rate.
    The caller must name ``positive_label``; the SDK never guesses which class
    represents a detected condition, release failure, adulterant, or defect.
    """

    registry_version: str
    n_samples: int
    positive_label: Any
    negative_label: Any
    true_positive: int
    false_positive: int
    true_negative: int
    false_negative: int
    sensitivity: float
    specificity: float
    accuracy: float

    def as_dict(self) -> dict[str, Any]:
        return {
            "registry_version": self.registry_version,
            "n_samples": self.n_samples,
            "positive_label": self.positive_label,
            "negative_label": self.negative_label,
            "true_positive": self.true_positive,
            "false_positive": self.false_positive,
            "true_negative": self.true_negative,
            "false_negative": self.false_negative,
            "sensitivity": self.sensitivity,
            "specificity": self.specificity,
            "accuracy": self.accuracy,
        }


@dataclass(frozen=True)
class SimcaAcceptanceEvidence:
    """Pooled class-model acceptance counts without row-level custody.

    Specificity is deliberately unavailable unless a future examination binds
    a representative negative/challenge population. Closed-set samples from
    the other modeled classes are not silently relabeled as that authority.
    """

    labels: tuple[Any, ...]
    n_samples: int
    unassigned_count: int
    multiple_acceptance_count: int
    observed_class_counts: tuple[int, ...]
    accepted_own_class_counts: tuple[int, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "spectra-simca-acceptance-evidence/1",
            "labels": list(self.labels),
            "n_samples": self.n_samples,
            "unassigned_count": self.unassigned_count,
            "unassigned_rate": self.unassigned_count / self.n_samples,
            "multiple_acceptance_count": self.multiple_acceptance_count,
            "multiple_acceptance_rate": self.multiple_acceptance_count / self.n_samples,
            "observed_class_counts": list(self.observed_class_counts),
            "accepted_own_class_counts": list(self.accepted_own_class_counts),
            "class_acceptance_sensitivity": [
                accepted / observed if observed else None
                for accepted, observed in zip(self.accepted_own_class_counts, self.observed_class_counts, strict=True)
            ],
            "representative_challenge_population_declared": False,
            "class_acceptance_specificity": None,
        }


@dataclass(frozen=True)
class ClassificationMetricSet:
    """Pooled multiclass metrics for one closed held-out prediction set.

    The confusion matrix is the mergeable scientific authority.  Accuracy,
    balanced accuracy, macro-F1, and multiclass MCC are deterministic
    projections of that matrix; no fold-average approximation or retained
    row-level prediction is needed.
    """

    registry_version: str
    n_samples: int
    labels: tuple[Any, ...]
    accuracy: float
    balanced_accuracy: float
    macro_f1: float
    mcc: float
    confusion_matrix: tuple[tuple[int, ...], ...]
    class_sensitivities: tuple[float | None, ...]
    class_specificities: tuple[float | None, ...]
    mean_class_acceptance_sensitivity: float | None = None
    unassigned_rate: float | None = None
    multiple_acceptance_rate: float | None = None
    simca_acceptance: SimcaAcceptanceEvidence | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "registry_version": self.registry_version,
            "task_type": "classification",
            "n_samples": self.n_samples,
            "labels": list(self.labels),
            "accuracy": self.accuracy,
            "balanced_accuracy": self.balanced_accuracy,
            "macro_f1": self.macro_f1,
            "mcc": self.mcc,
            "confusion_matrix": [list(row) for row in self.confusion_matrix],
            "class_sensitivities": list(self.class_sensitivities),
            "class_specificities": list(self.class_specificities),
            "mean_class_acceptance_sensitivity": self.mean_class_acceptance_sensitivity,
            "unassigned_rate": self.unassigned_rate,
            "multiple_acceptance_rate": self.multiple_acceptance_rate,
            "simca_acceptance": None if self.simca_acceptance is None else self.simca_acceptance.as_dict(),
        }


class ClassificationMetricAccumulator:
    """Merge held-out classification folds without retaining their rows."""

    def __init__(self, labels: Sequence[Any]) -> None:
        normalized = tuple(_plain_label(label) for label in _unique_labels(labels))
        if len(normalized) < 2:
            raise ValueError("classification metric accumulator requires at least two classes")
        self.labels = normalized
        self._confusion = np.zeros((len(normalized), len(normalized)), dtype=np.int64)
        self._simca_labels: tuple[Any, ...] | None = None
        self._simca_n_samples = 0
        self._simca_unassigned = 0
        self._simca_multiple = 0
        self._simca_observed: np.ndarray | None = None
        self._simca_accepted_own: np.ndarray | None = None

    def add(self, y_true: Sequence[Any] | np.ndarray, y_pred: Sequence[Any] | np.ndarray) -> None:
        observed = _as_class_labels(y_true, "y_true")
        predicted = _as_class_labels(y_pred, "y_pred")
        if observed.shape != predicted.shape or observed.size < 1:
            raise ValueError("classification metric accumulator requires equal non-empty label vectors")
        for actual, forecast in zip(observed, predicted, strict=True):
            actual_index = _label_index(self.labels, actual)
            predicted_index = _label_index(self.labels, forecast)
            if actual_index is None or predicted_index is None:
                raise ValueError("classification metric accumulator received an undeclared class label")
            self._confusion[actual_index, predicted_index] += 1

    def merge(self, record: ClassificationMetricSet) -> None:
        """Merge one already-bounded fold record through its confusion matrix."""

        if not isinstance(record, ClassificationMetricSet) or record.labels != self.labels:
            raise ValueError("classification metric accumulator cannot merge a different metric authority")
        matrix = np.asarray(record.confusion_matrix, dtype=np.int64)
        if matrix.shape != self._confusion.shape or np.any(matrix < 0) or int(matrix.sum()) != record.n_samples:
            raise ValueError("classification metric accumulator cannot merge a malformed confusion matrix")
        self._confusion += matrix

    def add_simca_acceptance(
        self,
        y_true: Sequence[Any] | np.ndarray,
        membership: Sequence[Sequence[bool]] | np.ndarray,
        *,
        labels: Sequence[Any],
    ) -> None:
        observed = _as_class_labels(y_true, "y_true")
        normalized = tuple(_plain_label(label) for label in labels)
        matrix = np.asarray(membership)
        if (
            len(normalized) < 2
            or matrix.shape != (observed.size, len(normalized))
            or matrix.dtype != np.bool_
            or any(_label_index(normalized, value) is None for value in observed)
        ):
            raise ValueError("SIMCA acceptance evidence is malformed")
        if self._simca_labels not in {None, normalized}:
            raise ValueError("SIMCA acceptance folds disagree on class identity")
        if self._simca_labels is None:
            self._simca_labels = normalized
            self._simca_observed = np.zeros(len(normalized), dtype=np.int64)
            self._simca_accepted_own = np.zeros(len(normalized), dtype=np.int64)
        assert self._simca_observed is not None and self._simca_accepted_own is not None
        self._simca_n_samples += int(observed.size)
        accepted_counts = matrix.sum(axis=1)
        self._simca_unassigned += int(np.count_nonzero(accepted_counts == 0))
        self._simca_multiple += int(np.count_nonzero(accepted_counts > 1))
        for row, truth in enumerate(observed):
            index = _label_index(normalized, truth)
            assert index is not None
            self._simca_observed[index] += 1
            self._simca_accepted_own[index] += int(matrix[row, index])

    def metrics(self) -> ClassificationMetricSet:
        metrics = _classification_metrics_from_confusion(self.labels, self._confusion)
        if self._simca_labels is None:
            return metrics
        assert self._simca_observed is not None and self._simca_accepted_own is not None
        return _with_simca_acceptance(
            metrics,
            SimcaAcceptanceEvidence(
                labels=self._simca_labels,
                n_samples=self._simca_n_samples,
                unassigned_count=self._simca_unassigned,
                multiple_acceptance_count=self._simca_multiple,
                observed_class_counts=tuple(int(value) for value in self._simca_observed),
                accepted_own_class_counts=tuple(int(value) for value in self._simca_accepted_own),
            ),
        )


def _with_simca_acceptance(
    metrics: ClassificationMetricSet,
    evidence: SimcaAcceptanceEvidence,
) -> ClassificationMetricSet:
    sensitivities = [
        accepted / observed
        for accepted, observed in zip(
            evidence.accepted_own_class_counts,
            evidence.observed_class_counts,
            strict=True,
        )
        if observed
    ]
    if not sensitivities or evidence.n_samples < 1:
        raise ValueError("SIMCA acceptance evidence cannot derive its scalar projections")
    return replace(
        metrics,
        mean_class_acceptance_sensitivity=float(sum(sensitivities) / len(sensitivities)),
        unassigned_rate=evidence.unassigned_count / evidence.n_samples,
        multiple_acceptance_rate=evidence.multiple_acceptance_count / evidence.n_samples,
        simca_acceptance=evidence,
    )


def _classification_metrics_from_confusion(
    labels: Sequence[Any],
    confusion: Sequence[Sequence[int]] | np.ndarray,
) -> ClassificationMetricSet:
    """Recompute every classification scalar from one closed count matrix."""

    normalized_labels = tuple(_plain_label(label) for label in labels)
    matrix_int = np.asarray(confusion)
    if (
        len(normalized_labels) < 2
        or matrix_int.shape != (len(normalized_labels), len(normalized_labels))
        or not np.issubdtype(matrix_int.dtype, np.integer)
        or np.any(matrix_int < 0)
    ):
        raise ValueError("classification confusion matrix is malformed")
    matrix = np.asarray(matrix_int, dtype=np.float64)
    n_samples = int(matrix.sum())
    if n_samples < 1:
        raise ValueError("classification confusion matrix has no samples")
    true_counts = matrix.sum(axis=1)
    predicted_counts = matrix.sum(axis=0)
    diagonal = np.diag(matrix)
    observed_rows = true_counts > 0
    recalls = np.divide(diagonal, true_counts, out=np.zeros_like(diagonal), where=observed_rows)
    negatives = n_samples - true_counts
    true_negatives = n_samples - true_counts - predicted_counts + diagonal
    specificities = np.divide(
        true_negatives,
        negatives,
        out=np.zeros_like(diagonal),
        where=negatives > 0,
    )
    precisions = np.divide(
        diagonal,
        predicted_counts,
        out=np.zeros_like(diagonal),
        where=predicted_counts > 0,
    )
    f1 = np.divide(
        2.0 * precisions * recalls,
        precisions + recalls,
        out=np.zeros_like(diagonal),
        where=(precisions + recalls) > 0,
    )
    correct = float(diagonal.sum())
    numerator = correct * n_samples - float(np.dot(true_counts, predicted_counts))
    denominator = float(
        np.sqrt(
            (n_samples**2 - float(np.dot(predicted_counts, predicted_counts)))
            * (n_samples**2 - float(np.dot(true_counts, true_counts)))
        )
    )
    return ClassificationMetricSet(
        registry_version=CLASSIFICATION_METRIC_SET_REGISTRY_VERSION,
        n_samples=n_samples,
        labels=normalized_labels,
        accuracy=correct / n_samples,
        balanced_accuracy=float(np.mean(recalls[observed_rows])),
        macro_f1=float(np.mean(f1)),
        mcc=0.0 if denominator == 0.0 else numerator / denominator,
        confusion_matrix=tuple(tuple(int(value) for value in row) for row in matrix_int.tolist()),
        class_sensitivities=tuple(float(value) if present else None for value, present in zip(recalls, observed_rows)),
        class_specificities=tuple(
            float(value) if present else None for value, present in zip(specificities, negatives > 0)
        ),
    )


REGRESSION_METRIC_FIELDS = frozenset(
    {"registry_version", "n_samples", "rmse", "mae", "bias", "r2", "sep", "slope", "intercept", "rer"}
)
CLASSIFICATION_METRIC_FIELDS = frozenset(
    {
        "registry_version",
        "task_type",
        "n_samples",
        "labels",
        "accuracy",
        "balanced_accuracy",
        "macro_f1",
        "mcc",
        "confusion_matrix",
        "class_sensitivities",
        "class_specificities",
        "mean_class_acceptance_sensitivity",
        "unassigned_rate",
        "multiple_acceptance_rate",
        "simca_acceptance",
    }
)
LEGACY_CLASSIFICATION_METRIC_FIELDS = CLASSIFICATION_METRIC_FIELDS - {
    "class_sensitivities",
    "class_specificities",
    "mean_class_acceptance_sensitivity",
    "unassigned_rate",
    "multiple_acceptance_rate",
    "simca_acceptance",
}


def _validate_simca_acceptance_record(value: object, *, metric_record: Mapping[str, Any]) -> None:
    if value is None:
        return
    fields = {
        "schema_version",
        "labels",
        "n_samples",
        "unassigned_count",
        "unassigned_rate",
        "multiple_acceptance_count",
        "multiple_acceptance_rate",
        "observed_class_counts",
        "accepted_own_class_counts",
        "class_acceptance_sensitivity",
        "representative_challenge_population_declared",
        "class_acceptance_specificity",
    }
    if not isinstance(value, Mapping) or set(value) != fields:
        raise ValueError("SIMCA acceptance evidence does not use the closed schema")
    labels = value["labels"]
    observed = value["observed_class_counts"]
    accepted = value["accepted_own_class_counts"]
    sensitivities = value["class_acceptance_sensitivity"]
    n_samples = value["n_samples"]
    unassigned = value["unassigned_count"]
    multiple = value["multiple_acceptance_count"]
    if (
        value["schema_version"] != "spectra-simca-acceptance-evidence/1"
        or not isinstance(labels, list)
        or len(labels) < 2
        or not all(isinstance(item, list) and len(item) == len(labels) for item in (observed, accepted, sensitivities))
        or type(n_samples) is not int
        or n_samples != metric_record["n_samples"]
        or any(type(count) is not int or count < 0 for count in [unassigned, multiple, *observed, *accepted])
        or sum(observed) != n_samples
        or any(hit > total for hit, total in zip(accepted, observed, strict=True))
        or unassigned > n_samples
        or multiple > n_samples
        or value["representative_challenge_population_declared"] is not False
        or value["class_acceptance_specificity"] is not None
    ):
        raise ValueError("SIMCA acceptance evidence is malformed")
    expected_sensitivity = [hit / total if total else None for hit, total in zip(accepted, observed, strict=True)]
    if sensitivities != expected_sensitivity:
        raise ValueError("SIMCA class acceptance sensitivity does not reproduce from its counts")
    if value["unassigned_rate"] != unassigned / n_samples or value["multiple_acceptance_rate"] != multiple / n_samples:
        raise ValueError("SIMCA acceptance rates do not reproduce from their counts")
    metric_labels = metric_record["labels"]
    confusion = metric_record["confusion_matrix"]
    reject_index = _label_index(metric_labels, "unassigned")
    modeled_metric_labels = [label for index, label in enumerate(metric_labels) if index != reject_index]
    portable_labels: list[str | int | float] = []
    try:
        portable_labels = [_normalize_group_identity(label, name="SIMCA acceptance label") for label in labels]
    except ValueError as exc:
        raise ValueError("SIMCA acceptance labels are not portable class identities") from exc
    if (
        reject_index is None
        or len(portable_labels) != len(modeled_metric_labels)
        or any(
            not _exact_labels_equal(acceptance_label, metric_label)
            for acceptance_label, metric_label in zip(
                portable_labels,
                modeled_metric_labels,
                strict=True,
            )
        )
        or any(
            _labels_equal(left, right)
            for index, left in enumerate(portable_labels)
            for right in portable_labels[index + 1 :]
        )
    ):
        raise ValueError("SIMCA acceptance labels disagree with the confusion-matrix class identities")
    if reject_index is None or sum(row[reject_index] for row in confusion) != unassigned:
        raise ValueError("SIMCA rejection evidence disagrees with its confusion matrix")


def validate_supervised_metric_record(value: Mapping[str, Any]) -> dict[str, Any]:
    """Re-admit one regression or classification metric projection.

    Classification summaries are never trusted: all scalar metrics are
    recomputed from the confusion matrix and must equal its deterministic
    projection.  Regression keeps its established closed scalar contract.
    """

    if not isinstance(value, Mapping):
        raise ValueError("supervised metric record must be an object")
    record = dict(value)
    if set(record) == REGRESSION_METRIC_FIELDS:
        if record.get("registry_version") != REGRESSION_METRIC_REGISTRY_VERSION:
            raise ValueError("regression metrics use an unsupported registry")
        n_samples = record.get("n_samples")
        if isinstance(n_samples, bool) or not isinstance(n_samples, int) or n_samples < 1:
            raise ValueError("regression metric sample count is invalid")
        for field in ("rmse", "mae", "bias"):
            scalar = record.get(field)
            if isinstance(scalar, bool) or not isinstance(scalar, (int, float)) or not np.isfinite(scalar):
                raise ValueError("regression metrics contain a non-finite scalar")
        r2 = record.get("r2")
        if r2 is not None and (isinstance(r2, bool) or not isinstance(r2, (int, float)) or not np.isfinite(r2)):
            raise ValueError("regression r2 must be finite or null")
        for field in ("sep", "slope", "intercept", "rer"):
            scalar = record.get(field)
            if scalar is not None and (
                isinstance(scalar, bool) or not isinstance(scalar, (int, float)) or not np.isfinite(scalar)
            ):
                raise ValueError(f"regression {field} must be finite or null")
        if record["rmse"] < 0 or record["mae"] < 0:
            raise ValueError("regression error metrics cannot be negative")
        if record["mae"] > record["rmse"] + METRIC_PARITY_ABSOLUTE_TOLERANCE:
            raise ValueError("regression MAE cannot exceed RMSE")
        if abs(record["bias"]) > record["mae"] + METRIC_PARITY_ABSOLUTE_TOLERANCE:
            raise ValueError("regression absolute bias cannot exceed MAE")
        if r2 is not None and r2 > 1.0 + METRIC_PARITY_ABSOLUTE_TOLERANCE:
            raise ValueError("regression r2 cannot exceed one")
        if record["sep"] is not None and record["sep"] < 0:
            raise ValueError("regression SEP cannot be negative")
        if record["rer"] is not None and record["rer"] < 0:
            raise ValueError("regression RER cannot be negative")
        return record
    if set(record) == LEGACY_CLASSIFICATION_METRIC_FIELDS and record.get("registry_version") == "1":
        expected = _classification_metrics_from_confusion(
            record.get("labels"), record.get("confusion_matrix")
        ).as_dict()
        legacy_expected = {field: expected[field] for field in LEGACY_CLASSIFICATION_METRIC_FIELDS}
        if record != {**legacy_expected, "registry_version": "1"}:
            raise ValueError("classification metrics do not reproduce from the confusion matrix")
        return record
    if set(record) != CLASSIFICATION_METRIC_FIELDS or record.get("task_type") != "classification":
        raise ValueError("supervised metric record does not use a supported closed schema")
    if record.get("registry_version") != CLASSIFICATION_METRIC_SET_REGISTRY_VERSION:
        raise ValueError("classification metrics use an unsupported registry")
    labels = record.get("labels")
    confusion = record.get("confusion_matrix")
    if not isinstance(labels, list) or not isinstance(confusion, list):
        raise ValueError("classification metric labels and confusion matrix must be arrays")
    expected = _classification_metrics_from_confusion(labels, confusion).as_dict()
    _validate_simca_acceptance_record(record["simca_acceptance"], metric_record=record)
    if record["simca_acceptance"] is not None:
        acceptance = record["simca_acceptance"]
        evidence = SimcaAcceptanceEvidence(
            labels=tuple(acceptance["labels"]),
            n_samples=acceptance["n_samples"],
            unassigned_count=acceptance["unassigned_count"],
            multiple_acceptance_count=acceptance["multiple_acceptance_count"],
            observed_class_counts=tuple(acceptance["observed_class_counts"]),
            accepted_own_class_counts=tuple(acceptance["accepted_own_class_counts"]),
        )
        expected = _with_simca_acceptance(_classification_metrics_from_confusion(labels, confusion), evidence).as_dict()
    if record != expected:
        raise ValueError("classification metrics do not reproduce from the confusion matrix")
    return record


def supervised_metric_task(value: Mapping[str, Any]) -> str:
    """Return the scientific task after validating the complete metric record."""

    record = validate_supervised_metric_record(value)
    return "classification" if record.get("task_type") == "classification" else "regression"


def pool_supervised_metric_records(values: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Pool fold records through the exact mergeable authority for their task."""

    records = tuple(validate_supervised_metric_record(value) for value in values)
    if not records:
        raise ValueError("supervised metric pooling requires at least one fold")
    tasks = {supervised_metric_task(value) for value in records}
    if len(tasks) != 1:
        raise ValueError("supervised metric folds mix scientific tasks")
    if tasks == {"classification"}:
        labels = records[0]["labels"]
        if any(record["labels"] != labels for record in records):
            raise ValueError("classification folds disagree on class identity")
        matrices = [np.asarray(record["confusion_matrix"], dtype=np.int64) for record in records]
        metrics = _classification_metrics_from_confusion(labels, sum(matrices, np.zeros_like(matrices[0])))
        acceptances = [record["simca_acceptance"] for record in records]
        if all(value is None for value in acceptances):
            return metrics.as_dict()
        if any(value is None for value in acceptances):
            raise ValueError("classification folds mix SIMCA and discriminant evidence")
        present = [value for value in acceptances if value is not None]
        acceptance_labels = present[0]["labels"]
        if any(value["labels"] != acceptance_labels for value in present):
            raise ValueError("SIMCA folds disagree on class identity")
        observed = tuple(
            sum(int(value["observed_class_counts"][index]) for value in present)
            for index in range(len(acceptance_labels))
        )
        accepted = tuple(
            sum(int(value["accepted_own_class_counts"][index]) for value in present)
            for index in range(len(acceptance_labels))
        )
        return _with_simca_acceptance(
            metrics,
            SimcaAcceptanceEvidence(
                labels=tuple(acceptance_labels),
                n_samples=sum(int(value["n_samples"]) for value in present),
                unassigned_count=sum(int(value["unassigned_count"]) for value in present),
                multiple_acceptance_count=sum(int(value["multiple_acceptance_count"]) for value in present),
                observed_class_counts=observed,
                accepted_own_class_counts=accepted,
            ),
        ).as_dict()
    total = sum(int(record["n_samples"]) for record in records)
    pooled_bias = float(sum(record["n_samples"] * record["bias"] for record in records) / total)
    pooled_centered_residual_ss = 0.0
    sep_available = total >= 2
    for record in records:
        count = int(record["n_samples"])
        if count > 1:
            if record["sep"] is None:
                sep_available = False
                break
            pooled_centered_residual_ss += float(record["sep"]) ** 2 * (count - 1)
        pooled_centered_residual_ss += count * (float(record["bias"]) - pooled_bias) ** 2
    pooled_sep = float(np.sqrt(max(0.0, pooled_centered_residual_ss) / (total - 1))) if sep_available else None
    return {
        "registry_version": REGRESSION_METRIC_REGISTRY_VERSION,
        "n_samples": total,
        "rmse": float(np.sqrt(sum(record["n_samples"] * record["rmse"] ** 2 for record in records) / total)),
        "mae": float(sum(record["n_samples"] * record["mae"] for record in records) / total),
        "bias": pooled_bias,
        # Fold summaries cannot reconstruct pooled R2 without target variance;
        # the established evidence contract therefore compares the recorded
        # pooled value separately while exactly pooling additive metrics.
        "r2": None,
        "sep": pooled_sep,
        "slope": None,
        "intercept": None,
        "rer": None,
    }


def classification_metric_set(
    y_true: Sequence[Any] | np.ndarray,
    y_pred: Sequence[Any] | np.ndarray,
    *,
    labels: Sequence[Any] | None = None,
    simca_membership: Sequence[Sequence[bool]] | np.ndarray | None = None,
    simca_labels: Sequence[Any] | None = None,
) -> ClassificationMetricSet:
    """Compute the closed multiclass metric record through its accumulator."""

    observed = _as_class_labels(y_true, "y_true")
    accumulator = ClassificationMetricAccumulator(observed if labels is None else labels)
    accumulator.add(observed, y_pred)
    if simca_membership is not None:
        if simca_labels is None:
            raise ValueError("SIMCA acceptance evidence requires class labels")
        accumulator.add_simca_acceptance(observed, simca_membership, labels=simca_labels)
    return accumulator.metrics()


@dataclass(frozen=True)
class MetricInterval:
    """A percentile confidence interval for one versioned scalar metric."""

    lower: float
    upper: float


@dataclass(frozen=True)
class RegressionMetricUncertainty:
    """Bootstrap uncertainty for the version-2 regression metric registry."""

    registry_version: str
    confidence_level: float
    n_resamples: int
    grouped: bool
    rmse: MetricInterval
    mae: MetricInterval
    bias: MetricInterval
    r2: MetricInterval | None
    sep: MetricInterval | None
    slope: MetricInterval | None
    intercept: MetricInterval | None
    rer: MetricInterval | None

    def as_dict(self) -> dict[str, Any]:
        def interval(value: MetricInterval | None) -> dict[str, float] | None:
            return None if value is None else {"lower": value.lower, "upper": value.upper}

        return {
            "registry_version": self.registry_version,
            "confidence_level": self.confidence_level,
            "n_resamples": self.n_resamples,
            "grouped": self.grouped,
            "rmse": interval(self.rmse),
            "mae": interval(self.mae),
            "bias": interval(self.bias),
            "r2": interval(self.r2),
            "sep": interval(self.sep),
            "slope": interval(self.slope),
            "intercept": interval(self.intercept),
            "rer": interval(self.rer),
        }


@dataclass(frozen=True)
class MetricParityResult:
    """The result of comparing two metric records under the registry contract."""

    matches: bool
    differences: dict[str, tuple[Any, Any]]

    def require_match(self) -> None:
        """Raise a concise diagnostic if the records are not reproducibly equal."""
        if not self.matches:
            raise ValueError(f"metric parity failed: {self.differences}")


@dataclass(frozen=True)
class Fold:
    """One immutable train/test partition, expressed as integer indices."""

    train: np.ndarray
    test: np.ndarray


@dataclass(frozen=True)
class SplitPlan:
    """An inspectable, reusable outer-CV split plan.

    The plan contains no target values.  It can therefore be recorded before
    model search and re-used for baseline/candidate comparisons without
    accidental split drift.
    """

    method: str
    n_samples: int
    folds: tuple[Fold, ...]
    grouped: bool
    held_out_groups: tuple[Any, ...] | None = None

    @property
    def digest(self) -> str:
        """Return the portable identity of the locked outer-fold plan."""

        payload = {
            "schema_version": ("spectra-split-plan/2" if self.held_out_groups is not None else "spectra-split-plan/1"),
            "method": self.method,
            "n_samples": self.n_samples,
            "grouped": self.grouped,
            "folds": [
                {
                    "train": np.asarray(fold.train, dtype=np.int64).tolist(),
                    "test": np.asarray(fold.test, dtype=np.int64).tolist(),
                }
                for fold in self.folds
            ],
        }
        if self.held_out_groups is not None:
            payload["held_out_groups"] = [
                _normalize_group_identity(value, name="split plan held-out group") for value in self.held_out_groups
            ]
        return hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False).encode(
                "utf-8"
            )
        ).hexdigest()

    def validate(self, groups: Sequence[Any] | None = None) -> None:
        """Reject malformed folds and train/test group leakage."""
        seen_test = np.zeros(self.n_samples, dtype=int)
        group_values = _as_groups(groups, self.n_samples) if groups is not None else None
        if self.held_out_groups is not None and (group_values is None or len(self.held_out_groups) != len(self.folds)):
            raise ValueError("split plan held-out group identities do not match its grouped folds")
        normalized_held_out_groups = (
            None
            if self.held_out_groups is None
            else tuple(
                _normalize_group_identity(value, name="split plan held-out group") for value in self.held_out_groups
            )
        )
        for fold_number, fold in enumerate(self.folds):
            train = _as_index_array(fold.train, self.n_samples, f"fold {fold_number} train")
            test = _as_index_array(fold.test, self.n_samples, f"fold {fold_number} test")
            if train.size == 0 or test.size == 0:
                raise ValueError(f"fold {fold_number} must contain both training and test samples")
            if np.intersect1d(train, test).size:
                raise ValueError(f"fold {fold_number} overlaps training and test samples")
            if np.union1d(train, test).size != self.n_samples:
                raise ValueError(f"fold {fold_number} does not partition every sample into training or test")
            if group_values is not None:
                shared_groups = np.intersect1d(group_values[train], group_values[test])
                if shared_groups.size:
                    raise ValueError(
                        f"fold {fold_number} leaks group(s) across training and test: {shared_groups.tolist()}"
                    )
                if self.held_out_groups is not None:
                    test_groups = [
                        _normalize_group_identity(value, name="observed validation group")
                        for value in _unique_labels(group_values[test])
                    ]
                    assert normalized_held_out_groups is not None
                    expected_group = normalized_held_out_groups[fold_number]
                    if len(test_groups) != 1 or not _exact_labels_equal(test_groups[0], expected_group):
                        raise ValueError(f"fold {fold_number} does not hold out its declared exact group")
            seen_test[test] += 1

        if not np.all(seen_test == 1):
            missing = np.flatnonzero(seen_test == 0).tolist()
            repeated = np.flatnonzero(seen_test > 1).tolist()
            raise ValueError(
                "an outer cross-validation plan must test every sample exactly once "
                f"(missing={missing}, repeated={repeated})"
            )


def metrics(y_true: Sequence[float], y_pred: Sequence[float]) -> RegressionMetrics:
    """Compute registry-2 metrics using the same stable authority as pooled folds.

    RMSE is the root mean squared prediction error, bias is prediction minus
    reference, and SEP is the sample standard deviation of residuals. Constant
    means exact equality of the represented reference values, never an
    absolute or relative closeness threshold.
    """
    accumulator = RegressionMetricAccumulator()
    accumulator.add(y_true, y_pred)
    return accumulator.metrics()


def classification_metrics(
    y_true: Sequence[Any] | np.ndarray,
    y_pred: Sequence[Any] | np.ndarray,
    *,
    positive_label: Any,
) -> ClassificationMetrics:
    """Compute binary sensitivity, specificity, and accuracy under registry v1.

    Both observed classes must be represented in ``y_true`` and all predictions
    must use one of those observed labels. This avoids silently treating an
    absent class or a third ``unknown`` label as a favorable score.
    """
    observed = _as_class_labels(y_true, "y_true")
    predicted = _as_class_labels(y_pred, "y_pred")
    if observed.shape != predicted.shape:
        raise ValueError(f"y_true and y_pred must have equal shape, got {observed.shape} and {predicted.shape}")
    classes = _unique_labels(observed)
    if len(classes) != 2:
        raise ValueError("classification_metrics requires exactly two observed classes")
    if not _contains_label(classes, positive_label):
        raise ValueError("positive_label must be one of the observed classes")
    negative_label = next(label for label in classes if not _labels_equal(label, positive_label))
    if any(not _contains_label(classes, label) for label in predicted):
        raise ValueError("y_pred contains a label that is absent from y_true")

    actual_positive = np.asarray([_labels_equal(label, positive_label) for label in observed], dtype=bool)
    predicted_positive = np.asarray([_labels_equal(label, positive_label) for label in predicted], dtype=bool)
    true_positive = int(np.count_nonzero(actual_positive & predicted_positive))
    false_positive = int(np.count_nonzero(~actual_positive & predicted_positive))
    true_negative = int(np.count_nonzero(~actual_positive & ~predicted_positive))
    false_negative = int(np.count_nonzero(actual_positive & ~predicted_positive))
    return ClassificationMetrics(
        registry_version=METRIC_REGISTRY_VERSION,
        n_samples=int(observed.size),
        positive_label=positive_label,
        negative_label=negative_label,
        true_positive=true_positive,
        false_positive=false_positive,
        true_negative=true_negative,
        false_negative=false_negative,
        sensitivity=true_positive / (true_positive + false_negative),
        specificity=true_negative / (true_negative + false_positive),
        accuracy=(true_positive + true_negative) / observed.size,
    )


def bootstrap_regression_uncertainty(
    y_true: Sequence[float] | np.ndarray,
    y_pred: Sequence[float] | np.ndarray,
    *,
    groups: Sequence[Any] | None = None,
    n_resamples: int = 1_000,
    confidence_level: float = 0.95,
    random_state: int | None = None,
) -> RegressionMetricUncertainty:
    """Estimate percentile uncertainty for regression metrics by bootstrap.

    With ``groups``, whole independent units are sampled with replacement;
    repeated spectra from a specimen or batch are never independently
    resampled. The interval characterizes this fixed observed/predicted pair;
    it neither replaces a locked validation design nor licenses repeated
    candidate selection on a confirmation set.
    """
    observed = _as_target(y_true, "y_true")
    predicted = _as_target(y_pred, "y_pred")
    if observed.shape != predicted.shape:
        raise ValueError(f"y_true and y_pred must have equal shape, got {observed.shape} and {predicted.shape}")
    if not np.isfinite(observed).all() or not np.isfinite(predicted).all():
        raise ValueError("bootstrap uncertainty requires finite y_true and y_pred values")
    if n_resamples < 2:
        raise ValueError("n_resamples must be at least 2")
    if not 0 < confidence_level < 1:
        raise ValueError("confidence_level must be strictly between 0 and 1")
    group_values = _as_groups(groups, observed.size) if groups is not None else None
    draws = _bootstrap_indices(observed.size, group_values, n_resamples, random_state)
    values = [metrics(observed[index], predicted[index]) for index in draws]
    alpha = (1.0 - confidence_level) / 2.0

    def percentile(name: str) -> MetricInterval:
        samples = np.asarray([getattr(value, name) for value in values], dtype=float)
        lower, upper = np.quantile(samples, [alpha, 1.0 - alpha])
        return MetricInterval(lower=float(lower), upper=float(upper))

    def optional_percentile(name: str) -> MetricInterval | None:
        return None if any(getattr(value, name) is None for value in values) else percentile(name)

    return RegressionMetricUncertainty(
        registry_version=REGRESSION_METRIC_REGISTRY_VERSION,
        confidence_level=confidence_level,
        n_resamples=n_resamples,
        grouped=group_values is not None,
        rmse=percentile("rmse"),
        mae=percentile("mae"),
        bias=percentile("bias"),
        r2=optional_percentile("r2"),
        sep=optional_percentile("sep"),
        slope=optional_percentile("slope"),
        intercept=optional_percentile("intercept"),
        rer=optional_percentile("rer"),
    )


def compare_metric_parity(expected: RegressionMetrics, actual: RegressionMetrics) -> MetricParityResult:
    """Compare two metric records under the version-2 reproducibility bound.

    Registry version and sample count must match exactly.  RMSE, MAE, bias,
    and defined R² values use
    ``abs(expected - actual) <= 1e-12 + 1e-9 * abs(expected)``.  An undefined
    R² remains meaningful and therefore only matches another ``None``.
    """
    differences: dict[str, tuple[Any, Any]] = {}
    if expected.registry_version != actual.registry_version:
        differences["registry_version"] = (expected.registry_version, actual.registry_version)
    if expected.n_samples != actual.n_samples:
        differences["n_samples"] = (expected.n_samples, actual.n_samples)
    for name in ("rmse", "mae", "bias", "r2", "sep", "slope", "intercept", "rer"):
        expected_value = getattr(expected, name)
        actual_value = getattr(actual, name)
        if expected_value is None or actual_value is None:
            if expected_value != actual_value:
                differences[name] = (expected_value, actual_value)
            continue
        if (
            not np.isfinite(expected_value)
            or not np.isfinite(actual_value)
            or not np.isclose(
                expected_value,
                actual_value,
                rtol=METRIC_PARITY_RELATIVE_TOLERANCE,
                atol=METRIC_PARITY_ABSOLUTE_TOLERANCE,
            )
        ):
            differences[name] = (expected_value, actual_value)
    return MetricParityResult(matches=not differences, differences=differences)


def make_split_plan(
    n_samples: int,
    *,
    n_splits: int = 5,
    groups: Sequence[Any] | None = None,
    shuffle: bool = False,
    random_state: int | None = None,
) -> SplitPlan:
    """Create a K-fold or group-K-fold outer evaluation plan.

    When ``groups`` is supplied, every member of an independent unit is held
    out together.  Group K-fold has no shuffle parameter; requesting one is
    rejected instead of presenting a falsely randomised protocol.
    """
    if n_samples < 2:
        raise ValueError("n_samples must be at least 2")
    if n_splits < 2 or n_splits > n_samples:
        raise ValueError("n_splits must be between 2 and n_samples")
    if not shuffle and random_state is not None:
        raise ValueError("random_state requires shuffle=True")

    feature_placeholder = np.empty((n_samples, 1))
    if groups is None:
        splitter = KFold(n_splits=n_splits, shuffle=shuffle, random_state=random_state if shuffle else None)
        pairs = splitter.split(feature_placeholder)
        plan = SplitPlan(
            method="kfold",
            n_samples=n_samples,
            folds=tuple(Fold(np.asarray(train), np.asarray(test)) for train, test in pairs),
            grouped=False,
        )
        plan.validate()
        return plan

    if shuffle or random_state is not None:
        raise ValueError("group_kfold does not support shuffle or random_state; define a grouped split plan explicitly")
    group_values = _as_groups(groups, n_samples)
    if np.unique(group_values).size < n_splits:
        raise ValueError("n_splits cannot exceed the number of distinct groups")
    splitter = GroupKFold(n_splits=n_splits)
    pairs = splitter.split(feature_placeholder, groups=group_values)
    plan = SplitPlan(
        method="group_kfold",
        n_samples=n_samples,
        folds=tuple(Fold(np.asarray(train), np.asarray(test)) for train, test in pairs),
        grouped=True,
    )
    plan.validate(group_values)
    return plan


def make_classification_split_plan(
    labels: Sequence[Any] | np.ndarray,
    *,
    n_splits: int = 5,
    groups: Sequence[Any] | None = None,
    shuffle: bool = False,
    random_state: int | None = None,
) -> SplitPlan:
    """Create an outer plan that preserves every declared class in every fold.

    Classification validation must not inherit the ordinary K-fold default:
    an unlucky fold can otherwise omit a minority class and turn a scientific
    score into a property of sample ordering. Grouped plans keep independent
    units intact while stratifying as closely as the group composition permits;
    this authority rejects the plan if any train or test partition still loses
    a class.
    """

    observed = _as_class_labels(labels, "labels")
    classes = _unique_labels(observed)
    if len(classes) < 2:
        raise ValueError("classification split plan requires at least two classes")
    if n_splits < 2 or n_splits > observed.size:
        raise ValueError("n_splits must be between 2 and n_samples")
    counts = [sum(_labels_equal(value, label) for value in observed) for label in classes]
    if min(counts) < n_splits:
        raise ValueError("every classification class must contain at least n_splits samples")
    if not shuffle and random_state is not None:
        raise ValueError("random_state requires shuffle=True")

    feature_placeholder = np.empty((observed.size, 1))
    if groups is None:
        splitter = StratifiedKFold(
            n_splits=n_splits,
            shuffle=shuffle,
            random_state=random_state if shuffle else None,
        )
        pairs = splitter.split(feature_placeholder, observed)
        plan = SplitPlan(
            method="stratified_kfold",
            n_samples=int(observed.size),
            folds=tuple(Fold(np.asarray(train), np.asarray(test)) for train, test in pairs),
            grouped=False,
        )
        validate_classification_split_plan(plan, observed)
        return plan

    group_values = _as_groups(groups, int(observed.size))
    if np.unique(group_values).size < n_splits:
        raise ValueError("n_splits cannot exceed the number of distinct groups")
    splitter = StratifiedGroupKFold(
        n_splits=n_splits,
        shuffle=shuffle,
        random_state=random_state if shuffle else None,
    )
    pairs = splitter.split(feature_placeholder, observed, group_values)
    plan = SplitPlan(
        method="stratified_group_kfold",
        n_samples=int(observed.size),
        folds=tuple(Fold(np.asarray(train), np.asarray(test)) for train, test in pairs),
        grouped=True,
    )
    validate_classification_split_plan(plan, observed, groups=group_values)
    return plan


def make_leave_one_group_out_classification_plan(
    labels: Sequence[Any] | np.ndarray,
    groups: Sequence[Any] | np.ndarray,
    *,
    require_one_per_class_group: bool = False,
) -> SplitPlan:
    """Hold out each exact group once while preserving every training class domain.

    This is a protocol authority rather than a heuristic grouped splitter.  A
    fold's test set is exactly one complete group and its training set is the
    exact complement.  Optional one-per-cell admission is useful for balanced
    acquisition designs such as one replicate of every specimen per block.
    """

    observed = _as_class_labels(labels, "labels")
    classes = _unique_labels(observed)
    if len(classes) < 2:
        raise ValueError("leave-one-group-out classification requires at least two classes")
    raw_groups = np.asarray(groups, dtype=object)
    if raw_groups.ndim != 1 or raw_groups.size != observed.size:
        raise ValueError("groups must be one-dimensional and contain one value per sample")
    normalized_groups: list[Any] = []
    for raw_value in raw_groups:
        value = _plain_label(raw_value)
        if (
            value is None
            or isinstance(value, bool)
            or not isinstance(value, (str, int, float))
            or (isinstance(value, str) and (not value or len(value) > 256))
            or (isinstance(value, float) and not np.isfinite(value))
        ):
            raise ValueError("groups must contain bounded non-boolean JSON scalar identities")
        normalized_groups.append(value)
    if len({type(value) for value in normalized_groups}) != 1:
        raise ValueError("groups must use one exact scalar representation")
    group_values = np.asarray(normalized_groups, dtype=object)
    unique_groups = _unique_labels(group_values)
    if len(unique_groups) < 2:
        raise ValueError("leave-one-group-out classification requires at least two groups")
    unique_groups = sorted(
        unique_groups,
        key=lambda value: json.dumps(value, ensure_ascii=True, allow_nan=False),
    )
    folds: list[Fold] = []
    for group in unique_groups:
        test = np.flatnonzero(np.asarray([_labels_equal(value, group) for value in group_values], dtype=bool))
        train = np.flatnonzero(np.asarray([not _labels_equal(value, group) for value in group_values], dtype=bool))
        folds.append(Fold(train.astype(np.int64), test.astype(np.int64)))
    plan = SplitPlan(
        method="leave_one_group_out_classification",
        n_samples=int(observed.size),
        folds=tuple(folds),
        grouped=True,
        held_out_groups=tuple(unique_groups),
    )
    validate_classification_split_plan(plan, observed, groups=group_values)
    if require_one_per_class_group:
        for group in unique_groups:
            group_rows = np.asarray([_labels_equal(value, group) for value in group_values], dtype=bool)
            for class_label in classes:
                cell_count = sum(_labels_equal(label, class_label) for label in observed[group_rows])
                if cell_count != 1:
                    raise ValueError("balanced classification protocol requires exactly one row per class/group cell")
    return plan


def validate_classification_split_plan(
    plan: SplitPlan,
    labels: Sequence[Any] | np.ndarray,
    *,
    groups: Sequence[Any] | None = None,
) -> None:
    """Require complete train domains and an honest pooled test domain.

    Ordinary stratified folds must contain every class in both partitions.
    A leave-one-group-out test partition may contain only the class represented
    by that independent group; the split-plan authority already guarantees
    that every sample is tested exactly once across the complete plan.
    """

    observed = _as_class_labels(labels, "labels")
    if observed.size != plan.n_samples:
        raise ValueError("classification labels do not match split-plan sample count")
    plan.validate(groups if plan.grouped else None)
    expected = _unique_labels(observed)
    if len(expected) < 2:
        raise ValueError("classification split plan requires at least two classes")
    leave_one_group_out = plan.method == "leave_one_group_out_classification" and plan.held_out_groups is not None
    pooled_test_labels: list[Any] = []
    for fold_number, fold in enumerate(plan.folds):
        for role, indices in (("train", fold.train), ("test", fold.test)):
            present = _unique_labels(observed[np.asarray(indices, dtype=np.int64)])
            if role == "test":
                pooled_test_labels.extend(present)
                if leave_one_group_out:
                    continue
            if len(present) != len(expected) or any(not _contains_label(present, label) for label in expected):
                raise ValueError(f"classification fold {fold_number} {role} partition omits a declared class")
    pooled = _unique_labels(pooled_test_labels)
    if len(pooled) != len(expected) or any(not _contains_label(pooled, label) for label in expected):
        raise ValueError("classification split plan pooled test partitions omit a declared class")


def _as_target(values: Sequence[float] | np.ndarray, name: str) -> np.ndarray:
    array = np.asarray(values, dtype=float)
    if array.ndim != 1 or array.size == 0:
        raise ValueError(f"{name} must be a non-empty one-dimensional array")
    return array


def _as_class_labels(values: Sequence[Any] | np.ndarray, name: str) -> np.ndarray:
    array = np.asarray(values, dtype=object)
    if array.ndim != 1 or array.size == 0:
        raise ValueError(f"{name} must be a non-empty one-dimensional label array")
    normalized: list[Any] = []
    for raw_value in array:
        value = _plain_label(raw_value)
        if (
            value is None
            or isinstance(value, (list, tuple, dict, set, bytes, bytearray))
            or not isinstance(value, (str, int, float, bool))
            or (isinstance(value, float) and not np.isfinite(value))
            or (isinstance(value, str) and (not value or len(value) > 256))
        ):
            raise ValueError(f"{name} must contain bounded JSON-scalar class labels")
        normalized.append(value)
    return np.asarray(normalized, dtype=object)


def _unique_labels(values: Sequence[Any]) -> list[Any]:
    labels: list[Any] = []
    for value in values:
        if not _contains_label(labels, value):
            labels.append(value)
    return labels


def _plain_label(value: Any) -> Any:
    """Normalize NumPy scalars so metric records remain portable JSON values."""

    return value.item() if isinstance(value, np.generic) else value


def _normalize_group_identity(value: Any, *, name: str) -> str | int | float:
    value = _plain_label(value)
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        raise ValueError(f"{name} must be a bounded non-boolean JSON scalar")
    if isinstance(value, str):
        if not value or value != value.strip() or len(value) > 256:
            raise ValueError(f"{name} must be an exact bounded non-empty string")
    elif isinstance(value, int):
        if abs(value) > (2**53 - 1):
            raise ValueError(f"{name} integer exceeds the lossless JSON range")
    elif not np.isfinite(value):
        raise ValueError(f"{name} must be finite")
    return value


def _exact_labels_equal(left: Any, right: Any) -> bool:
    return type(left) is type(right) and _labels_equal(left, right)


def _label_index(labels: Sequence[Any], value: Any) -> int | None:
    for index, label in enumerate(labels):
        if _labels_equal(label, value):
            return index
    return None


def _contains_label(labels: Sequence[Any], value: Any) -> bool:
    return any(_labels_equal(label, value) for label in labels)


def _labels_equal(left: Any, right: Any) -> bool:
    result = left == right
    return bool(result) if isinstance(result, (bool, np.bool_)) else False


def _as_groups(groups: Sequence[Any], n_samples: int) -> np.ndarray:
    values = np.asarray(groups)
    if values.ndim != 1 or values.size != n_samples:
        raise ValueError("groups must be one-dimensional and contain one value per sample")
    return values


def _bootstrap_indices(
    n_samples: int,
    groups: np.ndarray | None,
    n_resamples: int,
    random_state: int | None,
) -> list[np.ndarray]:
    rng = np.random.default_rng(random_state)
    if groups is None:
        return [rng.integers(0, n_samples, size=n_samples) for _ in range(n_resamples)]
    unique_groups = _unique_labels(groups)
    group_rows = [
        np.flatnonzero(np.asarray([_labels_equal(value, group) for value in groups])) for group in unique_groups
    ]
    draws: list[np.ndarray] = []
    for _ in range(n_resamples):
        chosen = rng.integers(0, len(group_rows), size=len(group_rows))
        draws.append(np.concatenate([group_rows[index] for index in chosen]))
    return draws


def _is_sha256_digest(value: Any) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(char in "0123456789abcdef" for char in value)


def _as_index_array(values: np.ndarray, n_samples: int, name: str) -> np.ndarray:
    array = np.asarray(values)
    if array.ndim != 1 or not np.issubdtype(array.dtype, np.integer):
        raise ValueError(f"{name} indices must be a one-dimensional integer array")
    if np.any(array < 0) or np.any(array >= n_samples):
        raise ValueError(f"{name} indices are outside the sample range")
    if np.unique(array).size != array.size:
        raise ValueError(f"{name} contains duplicate indices")
    return array


__all__ = [
    "CLASSIFICATION_METRIC_SET_REGISTRY_VERSION",
    "METRIC_REGISTRY_VERSION",
    "REGRESSION_METRIC_REGISTRY_VERSION",
    "ClassificationMetrics",
    "ClassificationMetricAccumulator",
    "ClassificationMetricSet",
    "CLASSIFICATION_METRIC_FIELDS",
    "MetricInterval",
    "RegressionMetricUncertainty",
    "REGRESSION_METRIC_FIELDS",
    "METRIC_PARITY_ABSOLUTE_TOLERANCE",
    "METRIC_PARITY_RELATIVE_TOLERANCE",
    "Fold",
    "MetricParityResult",
    "RegressionMetricAccumulator",
    "RegressionMetrics",
    "SplitPlan",
    "bootstrap_regression_uncertainty",
    "classification_metrics",
    "classification_metric_set",
    "pool_supervised_metric_records",
    "supervised_metric_task",
    "validate_supervised_metric_record",
    "compare_metric_parity",
    "make_classification_split_plan",
    "make_leave_one_group_out_classification_plan",
    "make_split_plan",
    "metrics",
    "validate_classification_split_plan",
]
