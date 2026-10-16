"""Bounded PLS-DA latent-variable evidence from calibration and out-of-fold decisions."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Sequence
from typing import Any

import numpy as np

from spectra_sherpa.sdk.validate import make_classification_split_plan

from ..modeling.component_validation import automatic_curve_workload_reason
from .core_utils import classification_scalar_metrics

SCHEMA_VERSION = "spectrasherpa-plsda-component-curve/1"


def _dummy(labels: np.ndarray, classes: np.ndarray) -> np.ndarray:
    indices = {value: index for index, value in enumerate(classes.tolist())}
    return np.eye(len(classes), dtype=np.float64)[[indices[value] for value in labels.tolist()]]


def _decisions(fit: Any, X: np.ndarray, count: int, classes: np.ndarray) -> np.ndarray:
    responses = np.asarray(fit.predict(X, n_components=count), dtype=np.float64)
    if responses.shape != (X.shape[0], len(classes)) or not np.isfinite(responses).all():
        raise ValueError("PLS-DA component path produced invalid class responses")
    return classes[np.argmax(responses, axis=1)]


def _scores(labels: np.ndarray, predictions: np.ndarray, classes: np.ndarray) -> dict[str, float]:
    values = classification_scalar_metrics(labels, predictions, classes)
    return {name: values[name] for name in ("accuracy", "balanced_accuracy", "f1_macro")}


def build_plsda_component_curve(
    X: object,
    y: object,
    *,
    selected_components: int,
    requested_components: int | None = None,
    maximum_components: int,
    scale: bool,
    fit_model: Callable[[np.ndarray, np.ndarray, np.ndarray, int, bool], Any],
    groups: Sequence[Any] | None = None,
    cv_folds: int = 5,
    cv_unavailable_reason: str | None = None,
) -> dict[str, object]:
    """Use the same class order and a newly fitted dummy-response model in each fold.

    The CV path is development/tuning evidence. A locked independent cohort is
    never read here and cannot choose the latent-variable count.
    """

    matrix = np.asarray(X, dtype=np.float64)
    labels = np.asarray(y)
    if (
        matrix.ndim != 2
        or labels.ndim != 1
        or matrix.shape[0] != labels.size
        or matrix.shape[0] < 4
        or matrix.shape[1] < 1
        or not np.isfinite(matrix).all()
    ):
        raise ValueError("PLS-DA component curve requires finite aligned calibration data")
    if (
        type(selected_components) is not int
        or type(maximum_components) is not int
        or not 1 <= selected_components <= maximum_components <= min(20, matrix.shape[1], matrix.shape[0] - 1)
    ):
        raise ValueError("PLS-DA component counts exceed the calibration limit")
    if type(cv_folds) is not int or not 2 <= cv_folds <= 10 or not isinstance(scale, bool):
        raise ValueError("PLS-DA component-validation settings are invalid")
    if requested_components is None:
        requested_components = selected_components
    if type(requested_components) is not int or requested_components < selected_components:
        raise ValueError("Requested PLS-DA component count must be no lower than its effective fit")
    classes = np.unique(labels)
    if classes.size < 2:
        raise ValueError("PLS-DA component curve requires at least two classes")

    workload_reason = automatic_curve_workload_reason(*matrix.shape, maximum_components, cv_folds)
    if workload_reason:
        return {
            "schema_version": SCHEMA_VERSION,
            "model_family": "plsda",
            "selected_components": selected_components,
            "requested_components": requested_components,
            "selection_rule": "manual_parameter",
            "selected_in_curve": False,
            "maximum_components": maximum_components,
            "n_calibration": int(labels.size),
            "classes": [str(value) for value in classes.tolist()],
            "calibration": [],
            "cross_validation": {"status": "unavailable", "reason": workload_reason},
        }

    dummy = _dummy(labels, classes)
    try:
        fit = fit_model(matrix, dummy, classes, maximum_components, scale)
    except ValueError:
        maximum_components = selected_components
        fit = fit_model(matrix, dummy, classes, maximum_components, scale)
    calibration = []
    for count in range(1, maximum_components + 1):
        calibration.append(
            {
                "components": count,
                "status": "available",
                **_scores(labels, _decisions(fit, matrix, count, classes), classes),
            }
            if count <= fit.n_components
            else {"components": count, "status": "unavailable_rank"}
        )

    cv: dict[str, object] = {"status": "unavailable", "reason": "Not evaluated."}
    if cv_unavailable_reason is not None:
        cv["reason"] = cv_unavailable_reason
    elif matrix.shape[0] > 10_000:
        cv["reason"] = "This model exceeds the bounded 10,000-row automatic component CV."
    else:
        try:
            plan = make_classification_split_plan(labels, n_splits=cv_folds, groups=groups)
            limit = min(maximum_components, min(len(fold.train) - 1 for fold in plan.folds))
            if limit < 1:
                raise ValueError("No latent variable is identifiable in every training fold")
            fits = [fit_model(matrix[fold.train], dummy[fold.train], classes, limit, scale) for fold in plan.folds]
            limit = min(item.n_components for item in fits)
            if limit < 1:
                raise ValueError("No latent variable is identifiable in every training fold")
            assigned = np.full(labels.size, -1, dtype=np.int64)
            predicted = np.empty((limit, labels.size), dtype=labels.dtype)
            folds = []
            for fold_index, (fold, fold_fit) in enumerate(zip(plan.folds, fits, strict=True)):
                assigned[fold.test] = fold_index
                for count in range(1, limit + 1):
                    predicted[count - 1, fold.test] = _decisions(fold_fit, matrix[fold.test], count, classes)
                folds.append({"train": fold.train.astype(int).tolist(), "test": fold.test.astype(int).tolist()})
            if np.any(assigned < 0):
                raise ValueError("Classification CV did not assign every calibration row")
            rows = [
                (
                    {"components": count, "status": "available", **_scores(labels, predicted[count - 1], classes)}
                    if count <= limit
                    else {"components": count, "status": "unavailable_rank"}
                )
                for count in range(1, maximum_components + 1)
            ]
            recommended = min(range(limit), key=lambda index: (-float(rows[index]["balanced_accuracy"]), index)) + 1
            group_values = None if groups is None else np.asarray(groups).tolist()
            cv = {
                "status": "available",
                "role": "development_tuning",
                "method": plan.method,
                "n_folds": len(plan.folds),
                "n_samples": int(labels.size),
                "n_groups": None if group_values is None else len(set(group_values)),
                "groups_sha256": (
                    None
                    if group_values is None
                    else hashlib.sha256(
                        json.dumps(group_values, ensure_ascii=True, allow_nan=False).encode()
                    ).hexdigest()
                ),
                "split_digest": plan.digest,
                "folds": folds,
                "fold_assignments": assigned.astype(int).tolist(),
                "rows": rows,
                "suggestion": {"maximum_balanced_accuracy": recommended},
                "caution": (
                    "Out-of-fold class decisions are component-tuning evidence, " "not independent external validation."
                ),
            }
        except ValueError as exc:
            cv["reason"] = f"Classification CV is unavailable: {exc}"
    return {
        "schema_version": SCHEMA_VERSION,
        "model_family": "plsda",
        "selected_components": selected_components,
        "requested_components": requested_components,
        "selection_rule": "manual_parameter",
        "selection_note": "The saved n_components parameter chose the classifier; curve suggestions did not change it.",
        "selected_in_curve": selected_components <= maximum_components,
        "maximum_components": maximum_components,
        "effective_calibration_components": fit.n_components,
        "reference_population": "calibration",
        "n_calibration": int(labels.size),
        "classes": [str(value) for value in classes.tolist()],
        "class_counts": {str(value): int(np.count_nonzero(labels == value)) for value in classes.tolist()},
        "decision_rule": "maximum_predicted_dummy_response",
        "scaling": "fold_fitted_autoscale" if scale else "fold_fitted_mean_center",
        "calibration": calibration,
        "cross_validation": cv,
    }
