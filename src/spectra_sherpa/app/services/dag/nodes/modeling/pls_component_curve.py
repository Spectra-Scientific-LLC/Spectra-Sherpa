"""Bounded, model-bound PLS regression component-selection evidence.

The CV curve is development/tuning evidence, never an independent test result.
Callers must prove that X has not undergone a population-fitted upstream
preprocessing step; PLS autoscaling itself is fitted anew inside every fold.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Sequence
from typing import Any

import numpy as np

from spectra_sherpa.sdk.validate import make_split_plan

from .component_validation import automatic_curve_workload_reason
from .pls_core import PLSFit

SCHEMA_VERSION = "spectrasherpa-pls-component-curve/1"


def _digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False).encode()
    ).hexdigest()


def _response_metric(reference: np.ndarray, predicted: np.ndarray) -> tuple[list[float], list[float | None]]:
    error = predicted - reference
    rmse = np.sqrt(np.mean(error * error, axis=0))
    total = np.sum((reference - np.mean(reference, axis=0)) ** 2, axis=0)
    residual = np.sum(error * error, axis=0)
    r2: list[float | None] = [
        None if denominator <= 0.0 else float(1.0 - numerator / denominator)
        for numerator, denominator in zip(residual, total, strict=True)
    ]
    return [float(value) for value in rmse], r2


def _model_predictions(model: PLSFit, matrix: np.ndarray, components: int) -> np.ndarray:
    prediction = np.asarray(model.predict(matrix, n_components=components), dtype=np.float64)
    if prediction.ndim != 2 or not np.isfinite(prediction).all():
        raise ValueError("PLS component path produced invalid predictions")
    return prediction


def build_pls_component_curve(  # noqa: C901 - bounds, rank and fold-local refusal stay together
    X: object,
    Y: object,
    *,
    selected_components: int,
    requested_components: int | None = None,
    maximum_components: int,
    scale: bool,
    fit_model: Callable[..., PLSFit],
    response_names: Sequence[str] | None,
    response_units: Sequence[str | None],
    groups: Sequence[Any] | None = None,
    cv_folds: int = 5,
    cv_unavailable_reason: str | None = None,
    selection_rule: str = "manual_parameter",
) -> dict[str, object]:
    """Fit one calibration path and one common out-of-fold path per CV fold.

    Only components identifiable in *every* training fold are scored. All
    response metrics use their original physical units. For a multiresponse
    fit, suggestions are per response; no unrecorded target weighting chooses
    a single component count.
    """

    matrix = np.asarray(X, dtype=np.float64)
    target = np.asarray(Y, dtype=np.float64)
    if target.ndim == 1:
        target = target.reshape(-1, 1)
    if (
        matrix.ndim != 2
        or target.ndim != 2
        or min(matrix.shape) < 1
        or target.shape[0] != matrix.shape[0]
        or target.shape[1] < 1
        or not np.isfinite(matrix).all()
        or not np.isfinite(target).all()
    ):
        raise ValueError("PLS component curve requires finite aligned X and Y matrices")
    if type(selected_components) is not int or type(maximum_components) is not int:
        raise ValueError("PLS component counts must be whole numbers")
    if requested_components is None:
        requested_components = selected_components
    if type(requested_components) is not int or requested_components < selected_components:
        raise ValueError("Requested PLS component count must be no lower than its effective fit")
    if not 1 <= selected_components <= min(matrix.shape[0] - 1, matrix.shape[1]) or not 1 <= maximum_components <= min(
        matrix.shape[0] - 1, matrix.shape[1]
    ):
        raise ValueError("PLS component curve component range exceeds calibration dimensions")
    if not isinstance(scale, bool) or type(cv_folds) is not int or not 2 <= cv_folds <= 10:
        raise ValueError("PLS component curve scaling or fold count is invalid")
    if response_names is not None and (
        len(response_names) != target.shape[1]
        or any(not isinstance(name, str) or not name.strip() for name in response_names)
    ):
        raise ValueError("PLS component curve response names do not match Y")
    if len(response_units) != target.shape[1] or any(
        unit is not None and (not isinstance(unit, str) or not unit.strip()) for unit in response_units
    ):
        raise ValueError("PLS component curve response units do not match Y")
    if cv_unavailable_reason is not None and (not isinstance(cv_unavailable_reason, str) or not cv_unavailable_reason):
        raise ValueError("PLS component curve CV reason must be a non-empty string")
    if selection_rule not in {"manual_parameter", "minimum_mean_fold_rmse", "one_standard_error"}:
        raise ValueError("PLS component choice basis is unsupported")

    workload_reason = automatic_curve_workload_reason(*matrix.shape, maximum_components, cv_folds)
    if workload_reason:
        return {
            "schema_version": SCHEMA_VERSION,
            "model_family": "pls_regression",
            "selected_components": selected_components,
            "requested_components": requested_components,
            "selection_rule": selection_rule,
            "selection_rule_status": "unverified",
            "selected_in_curve": False,
            "maximum_components": maximum_components,
            "n_calibration": int(matrix.shape[0]),
            "response_names": (
                list(response_names)
                if response_names is not None
                else [f"Target {index + 1}" for index in range(target.shape[1])]
            ),
            "response_units": list(response_units),
            "scaling": "fold_fitted_autoscale" if scale else "fold_fitted_mean_center",
            "calibration": [],
            "cross_validation": {"status": "unavailable", "reason": workload_reason},
        }

    calibration_fit = fit_model(matrix, target, n_components=maximum_components, scale=scale)
    calibration: list[dict[str, object]] = []
    previous_x = 0.0
    previous_y = [0.0] * target.shape[1]
    x_cumulative = np.cumsum(calibration_fit.x_explained_variance)
    for components in range(1, maximum_components + 1):
        if components > calibration_fit.n_components:
            calibration.append({"components": components, "status": "unavailable_rank"})
            continue
        prediction = _model_predictions(calibration_fit, matrix, components)
        rmsec, r2y = _response_metric(target, prediction)
        x_value = float(x_cumulative[components - 1])
        incremental_y = [None if value is None else value - previous_y[index] for index, value in enumerate(r2y)]
        calibration.append(
            {
                "components": components,
                "status": "available",
                "rmsec": rmsec,
                "r2x_cumulative": x_value,
                "r2x_incremental": x_value - previous_x,
                "r2y_cumulative": r2y,
                "r2y_incremental": incremental_y,
            }
        )
        previous_x = x_value
        previous_y = [0.0 if value is None else value for value in r2y]

    def result(cv_result: dict[str, object]) -> dict[str, object]:
        return {
            "schema_version": SCHEMA_VERSION,
            "model_family": "pls_regression",
            "selected_components": selected_components,
            "requested_components": requested_components,
            "selection_rule": selection_rule,
            "selection_rule_status": (
                "manual"
                if selection_rule == "manual_parameter"
                else (
                    "unverified"
                    if cv_result.get("status") != "available" or target.shape[1] != 1
                    else (
                        "matches_curve"
                        if requested_components == cv_result["suggestions"][0][selection_rule]
                        else "differs_from_curve"
                    )
                )
            ),
            "selection_note": (
                "The saved n_components parameter chose the fitted model. The basis is a user declaration; "
                "the curve only verifies it for one response with available CV."
            ),
            "selected_in_curve": selected_components <= maximum_components,
            "maximum_components": maximum_components,
            "effective_calibration_components": calibration_fit.n_components,
            "reference_population": "calibration",
            "n_calibration": int(matrix.shape[0]),
            "response_names": (
                list(response_names)
                if response_names is not None
                else [f"Target {index + 1}" for index in range(target.shape[1])]
            ),
            "response_units": list(response_units),
            "scaling": "fold_fitted_autoscale" if scale else "fold_fitted_mean_center",
            "r2x_space": "autoscaled_X" if scale else "mean_centered_X",
            "r2y_definition": (
                "1 - calibration residual sum of squares / centered calibration response "
                "sum of squares, per response"
            ),
            "q2_definition": (
                "1 - pooled out-of-fold residual sum of squares / centered calibration "
                "response sum of squares, per response"
            ),
            "calibration": calibration,
            "cross_validation": cv_result,
        }

    cv: dict[str, object]
    if cv_unavailable_reason is not None:
        cv = {"status": "unavailable", "reason": cv_unavailable_reason}
    elif matrix.shape[0] < cv_folds + 2:
        cv = {"status": "unavailable", "reason": "Too few calibration rows for the requested CV folds."}
    elif matrix.shape[0] > 10_000:
        cv = {
            "status": "unavailable",
            "reason": (
                "This model exceeds the bounded 10,000-row automatic component CV; "
                "use an explicit validation workflow."
            ),
        }
    elif groups is not None and len(set(np.asarray(groups).tolist())) < cv_folds:
        cv = {"status": "unavailable", "reason": "Too few independent groups for the requested CV folds."}
    else:
        plan = make_split_plan(matrix.shape[0], n_splits=cv_folds, groups=groups)
        fold_limit = min(len(fold.train) - 1 for fold in plan.folds)
        fold_limit = min(fold_limit, matrix.shape[1], calibration_fit.n_components, maximum_components)
        if fold_limit < 1:
            cv = {"status": "unavailable", "reason": "No component is identifiable in every CV training fold."}
        else:
            predictions = np.empty((fold_limit, *target.shape), dtype=np.float64)
            assignments = np.full(matrix.shape[0], -1, dtype=np.int64)
            fold_error = np.empty((fold_limit, cv_folds, target.shape[1]), dtype=np.float64)
            folds: list[dict[str, object]] = []
            fits: list[PLSFit] = []
            failure_reason: str | None = None
            for fold in plan.folds:
                try:
                    fit = fit_model(matrix[fold.train], target[fold.train], n_components=fold_limit, scale=scale)
                except ValueError as exc:
                    failure_reason = f"A CV training fold cannot be fitted: {exc}"
                    break
                fits.append(fit)
            if failure_reason is None:
                fold_limit = min(fit.n_components for fit in fits)
            if failure_reason is not None:
                return result({"status": "unavailable", "reason": failure_reason})
            for fold_index, (fold, fit) in enumerate(zip(plan.folds, fits, strict=True)):
                assignments[fold.test] = fold_index
                for components in range(1, fold_limit + 1):
                    predicted = _model_predictions(fit, matrix[fold.test], components)
                    predictions[components - 1, fold.test] = predicted
                    fold_error[components - 1, fold_index] = np.sqrt(
                        np.mean((predicted - target[fold.test]) ** 2, axis=0)
                    )
                folds.append(
                    {
                        "train": fold.train.astype(int).tolist(),
                        "test": fold.test.astype(int).tolist(),
                        "n_train": int(len(fold.train)),
                        "n_validation": int(len(fold.test)),
                    }
                )
            if np.any(assignments < 0):
                raise ValueError("PLS component CV did not assign every calibration row")
            rows: list[dict[str, object]] = []
            for components in range(1, maximum_components + 1):
                if components > fold_limit:
                    rows.append({"components": components, "status": "unavailable_rank"})
                    continue
                rmsecv, q2 = _response_metric(target, predictions[components - 1])
                errors = fold_error[components - 1]
                fold_mean = np.mean(errors, axis=0)
                se = np.std(errors, axis=0, ddof=1) / np.sqrt(cv_folds)
                rows.append(
                    {
                        "components": components,
                        "status": "available",
                        "rmsecv": rmsecv,
                        "q2": q2,
                        "fold_rmse": errors.tolist(),
                        "fold_rmse_mean": fold_mean.astype(float).tolist(),
                        "fold_rmse_standard_error": se.astype(float).tolist(),
                    }
                )
            suggestions: list[dict[str, int]] = []
            for response in range(target.shape[1]):
                values = [float(rows[index]["fold_rmse_mean"][response]) for index in range(fold_limit)]  # type: ignore[index]
                minimum_index = min(range(fold_limit), key=lambda index: (values[index], index))
                standard_error = float(rows[minimum_index]["fold_rmse_standard_error"][response])  # type: ignore[index]
                threshold = values[minimum_index] + standard_error
                one_se = next(index + 1 for index, value in enumerate(values) if value <= threshold)
                suggestions.append({"minimum_mean_fold_rmse": minimum_index + 1, "one_standard_error": one_se})
            group_values = None if groups is None else list(np.asarray(groups).tolist())
            cv = {
                "status": "available",
                "role": "development_tuning",
                "method": plan.method,
                "n_folds": cv_folds,
                "n_samples": int(matrix.shape[0]),
                "n_groups": None if group_values is None else len(set(group_values)),
                "groups_sha256": None if group_values is None else _digest(group_values),
                "split_digest": plan.digest,
                "folds": folds,
                "fold_assignments": assignments.astype(int).tolist(),
                "rows": rows,
                "suggestions": suggestions,
                "one_se_definition": (
                    "Smallest LV with mean fold RMSE no greater than the minimum mean fold "
                    "RMSE plus its standard error. Pooled RMSECV is reported separately and "
                    "weights rows rather than folds."
                ),
                "caution": "This CV curve is component-tuning evidence, not unbiased external evaluation.",
            }
    return result(cv)
