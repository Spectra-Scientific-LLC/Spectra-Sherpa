"""CARS — Competitive Adaptive Reweighted Sampling.

Registered as ``selection.cars``.

Iterative variable selection that uses exponentially decreasing function
to progressively remove variables with small PLS regression coefficients.

Reference: Li et al., Analytica Chimica Acta 648 (2009) 77-84.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

import numpy as np

from spectra_sherpa.app.services.dag.feature_axis_identity import (
    feature_axis_identity as _canonical_feature_axis_identity,
)
from spectra_sherpa.app.services.dag.feature_axis_identity import (
    validated_axis_quantity,
)
from spectra_sherpa.app.services.dag.meta_helpers import add_processing_step
from spectra_sherpa.app.services.dag.stable_execution_contract import bind_stable_execution_contract
from spectra_sherpa.execution_contract_vocabulary import (
    LifecycleKind,
    ManagedOptimizationEligibility,
    RuntimeFamily,
    TargetAccess,
    WorkerCapability,
)

from ...io_contracts import bind_X, bind_y, build_dataset_like, to_numpy_2d, to_numpy_y
from ...node_base import Node, NodeMetadata, NodeParameter, NodePolicy, NodeResult, PortMetadata, register_node
from ..modeling import pls_core

logger = logging.getLogger(__name__)
_STATE_SERIALIZER = "spectrasherpa.selection.cars.state/3"


def _canonical_cars_parameters(parameters: Mapping[str, Any]) -> dict[str, int | float | str]:
    """Return the exact bounded CARS parameter representation."""

    allowed = {
        "n_iterations",
        "max_components",
        "cv_folds",
        "calibration_fraction",
        "random_seed",
        "component_selection",
        "cv_order",
    }
    unknown = sorted(set(parameters) - allowed)
    if unknown:
        raise ValueError(f"selection.cars accepts only: {', '.join(sorted(allowed))}")
    resolved: dict[str, Any] = {
        "n_iterations": parameters.get("n_iterations", 50),
        "max_components": parameters.get("max_components", 2),
        "cv_folds": parameters.get("cv_folds", 5),
        "calibration_fraction": parameters.get("calibration_fraction", 0.9),
        "random_seed": parameters.get("random_seed", 42),
        "component_selection": parameters.get("component_selection", "one_standard_deviation"),
        "cv_order": parameters.get("cv_order", "sorted_target"),
    }
    for name in ("n_iterations", "max_components", "cv_folds", "random_seed"):
        if isinstance(resolved[name], bool) or not isinstance(resolved[name], int):
            raise ValueError(f"CARS {name} must be an integer")
    fraction = resolved["calibration_fraction"]
    if isinstance(fraction, bool) or not isinstance(fraction, (int, float)) or not np.isfinite(fraction):
        raise ValueError("CARS calibration_fraction must be a finite number")
    if not 10 <= resolved["n_iterations"] <= 200:
        raise ValueError("CARS n_iterations must be between 10 and 200")
    if not 1 <= resolved["max_components"] <= 50:
        raise ValueError("CARS max_components must be between 1 and 50")
    if not 2 <= resolved["cv_folds"] <= 20:
        raise ValueError("CARS cv_folds must be between 2 and 20")
    if not 0.5 <= float(fraction) <= 0.95:
        raise ValueError("CARS calibration_fraction must be between 0.5 and 0.95")
    if not 0 <= resolved["random_seed"] <= 4_294_967_295:
        raise ValueError("CARS random_seed must be an unsigned 32-bit integer")
    if not isinstance(resolved["component_selection"], str) or resolved["component_selection"] not in {
        "minimum_rmsecv",
        "one_standard_deviation",
    }:
        raise ValueError("CARS component_selection must be minimum_rmsecv or one_standard_deviation")
    if not isinstance(resolved["cv_order"], str) or resolved["cv_order"] not in {
        "sorted_target",
        "seeded_random",
        "input_order",
    }:
        raise ValueError("CARS cv_order must be sorted_target, seeded_random, or input_order")
    return {
        "n_iterations": resolved["n_iterations"],
        "max_components": resolved["max_components"],
        "cv_folds": resolved["cv_folds"],
        "calibration_fraction": float(fraction),
        "random_seed": resolved["random_seed"],
        "component_selection": resolved["component_selection"],
        "cv_order": resolved["cv_order"],
    }


def _cars_inputs(X: Any, y: Any) -> tuple[np.ndarray, np.ndarray]:
    """Bind one finite feature matrix and exactly one quantitative target."""

    X_ds = bind_X(X, missing_message="CARS requires X", allow_array=True)
    y_value = bind_y(
        y,
        X=X_ds,
        required=True,
        infer_from_X=True,
        dataset_as_data=False,
        target_type="continuous",
    )
    matrix = to_numpy_2d(X_ds, name="X", dtype=np.float64)
    target = to_numpy_y(y_value, name="y", expected_samples=matrix.shape[0])
    if target.ndim == 2:
        if target.shape[1] != 1:
            raise ValueError("CARS requires exactly one quantitative target")
        target = target[:, 0]
    target = np.asarray(target, dtype=np.float64).reshape(-1)
    if not np.isfinite(matrix).all() or not np.isfinite(target).all():
        raise ValueError("CARS inputs must be finite")
    if matrix.shape[0] < 3 or matrix.shape[1] < 3:
        raise ValueError("CARS requires at least three samples and three features")
    if float(np.ptp(target)) == 0.0:
        raise ValueError("CARS requires a quantitative target with non-zero variation")
    return matrix, target


def _cars_support(
    *,
    n_samples: int,
    n_features: int,
    max_components: int,
    cv_folds: int,
    calibration_fraction: float,
) -> int:
    """Return the author-defined discrete MC draw size or fail closed."""

    if cv_folds > n_samples:
        raise ValueError("CARS cv_folds may not exceed the sample count")
    calibration_size = int(np.floor(calibration_fraction * n_samples))
    if calibration_size < 2 or calibration_size >= n_samples:
        raise ValueError("CARS calibration_fraction must define a proper calibration subset")
    if n_features < 2:
        raise ValueError("CARS requires at least two candidate features")
    if max_components > min(calibration_size - 1, n_features):
        raise ValueError("CARS max_components exceeds the initial Monte Carlo PLS support")
    smallest_cv_training_fold = n_samples - int(np.ceil(n_samples / cv_folds))
    if smallest_cv_training_fold < 2:
        raise ValueError("CARS cv_folds leave too few training samples")
    return calibration_size


def _feature_axis_identity(dataset: Any, *, features: int) -> tuple[str | None, str | None, str | None, str | None]:
    return _canonical_feature_axis_identity(dataset, features=features, context="CARS")


def _validate_cars_state(state: Mapping[str, object]) -> dict[str, object]:
    """Validate and copy the closed CARS fitted-state representation."""

    required = {
        "serializer",
        "feature_count",
        "feature_axis_values_sha256",
        "feature_axis_labels_sha256",
        "feature_axis_units",
        "feature_axis_quantity",
        "feature_mask",
        "importance_scores",
        "rmsecv_trace",
        "best_rmsecv",
        "n_iterations_run",
        "n_iterations",
        "max_components",
        "cv_folds",
        "reference_samples",
        "calibration_size",
        "random_seed",
        "calibration_fraction",
        "component_selection",
        "cv_order",
        "best_iteration",
        "optimal_components",
        "subset_masks",
        "retention_ratios",
        "selection_scope",
    }
    if not isinstance(state, Mapping) or set(state) != required or state.get("serializer") != _STATE_SERIALIZER:
        raise ValueError("fitted CARS state does not use the closed serializer schema")
    feature_count = state["feature_count"]
    iterations = state["n_iterations_run"]
    requested_iterations = state["n_iterations"]
    max_components = state["max_components"]
    cv_folds = state["cv_folds"]
    reference_samples = state["reference_samples"]
    calibration_size = state["calibration_size"]
    random_seed = state["random_seed"]
    if (
        isinstance(feature_count, bool)
        or not isinstance(feature_count, int)
        or feature_count < 1
        or isinstance(iterations, bool)
        or not isinstance(iterations, int)
        or iterations < 1
        or isinstance(requested_iterations, bool)
        or not isinstance(requested_iterations, int)
        or not 10 <= requested_iterations <= 200
        or iterations != requested_iterations
        or isinstance(max_components, bool)
        or not isinstance(max_components, int)
        or not 1 <= max_components <= 50
        or isinstance(cv_folds, bool)
        or not isinstance(cv_folds, int)
        or not 2 <= cv_folds <= 20
        or isinstance(reference_samples, bool)
        or not isinstance(reference_samples, int)
        or reference_samples < 3
        or isinstance(calibration_size, bool)
        or not isinstance(calibration_size, int)
        or calibration_size < 1
        or isinstance(random_seed, bool)
        or not isinstance(random_seed, int)
        or not 0 <= random_seed <= 4_294_967_295
    ):
        raise ValueError("fitted CARS state has invalid integer identity fields")
    axis_digest = state["feature_axis_values_sha256"]
    labels_digest = state["feature_axis_labels_sha256"]
    axis_units = state["feature_axis_units"]
    if axis_digest is not None and (
        not isinstance(axis_digest, str)
        or len(axis_digest) != 64
        or any(character not in "0123456789abcdef" for character in axis_digest)
    ):
        raise ValueError("fitted CARS state has an invalid feature-axis digest")
    if labels_digest is not None and (
        not isinstance(labels_digest, str)
        or len(labels_digest) != 64
        or any(character not in "0123456789abcdef" for character in labels_digest)
    ):
        raise ValueError("fitted CARS state has an invalid feature-axis label digest")
    if axis_units is not None and not isinstance(axis_units, str):
        raise ValueError("fitted CARS state has invalid feature-axis units")
    validated_axis_quantity(state["feature_axis_quantity"], context="fitted CARS")
    mask = np.asarray(state["feature_mask"])
    scores = np.asarray(state["importance_scores"], dtype=np.float64)
    trace = np.asarray(state["rmsecv_trace"], dtype=np.float64)
    if mask.ndim != 1 or mask.shape[0] != feature_count or mask.dtype != np.bool_ or not mask.any():
        raise ValueError("fitted CARS state has an invalid feature mask")
    if (
        scores.ndim != 1
        or scores.shape[0] != feature_count
        or not np.isfinite(scores).all()
        or np.any(scores < 0.0)
        or np.any(scores[~mask] != 0.0)
    ):
        raise ValueError("fitted CARS state has invalid importance scores")
    if trace.ndim != 1 or trace.shape[0] != iterations or not np.isfinite(trace).all() or np.any(trace < 0.0):
        raise ValueError("fitted CARS state has an invalid RMSECV trace")
    best_rmsecv = state["best_rmsecv"]
    calibration_fraction = state["calibration_fraction"]
    if (
        isinstance(best_rmsecv, bool)
        or not isinstance(best_rmsecv, (int, float))
        or not np.isfinite(best_rmsecv)
        or float(best_rmsecv) < 0.0
        or isinstance(calibration_fraction, bool)
        or not isinstance(calibration_fraction, (int, float))
        or not np.isfinite(calibration_fraction)
        or not 0.5 <= float(calibration_fraction) <= 0.95
    ):
        raise ValueError("fitted CARS state has invalid scientific summary fields")
    if state["selection_scope"] != "full_calibration_fit_not_performance_evidence":
        raise ValueError("fitted CARS state has an invalid selection scope")
    if not isinstance(state["component_selection"], str) or state["component_selection"] not in {
        "minimum_rmsecv",
        "one_standard_deviation",
    }:
        raise ValueError("fitted CARS state has an invalid component-selection rule")
    if not isinstance(state["cv_order"], str) or state["cv_order"] not in {
        "sorted_target",
        "seeded_random",
        "input_order",
    }:
        raise ValueError("fitted CARS state has an invalid CV ordering rule")
    best_iteration = state["best_iteration"]
    if isinstance(best_iteration, bool) or not isinstance(best_iteration, int) or not 0 <= best_iteration < iterations:
        raise ValueError("fitted CARS state has an invalid best iteration")
    subset_masks = np.asarray(state["subset_masks"])
    optimal_components = np.asarray(state["optimal_components"])
    retention_ratios = np.asarray(state["retention_ratios"], dtype=np.float64)
    if (
        subset_masks.ndim != 2
        or subset_masks.shape != (iterations, feature_count)
        or subset_masks.dtype != np.bool_
        or not np.all(np.any(subset_masks, axis=1))
    ):
        raise ValueError("fitted CARS state has invalid recorded subsets")
    if (
        optimal_components.ndim != 1
        or optimal_components.shape[0] != iterations
        or optimal_components.dtype.kind not in "iu"
        or np.any(optimal_components < 1)
        or np.any(optimal_components > max_components)
        or np.any(optimal_components > subset_masks.sum(axis=1))
    ):
        raise ValueError("fitted CARS state has invalid per-subset component choices")
    if (
        retention_ratios.ndim != 1
        or retention_ratios.shape[0] != iterations
        or not np.isfinite(retention_ratios).all()
        or np.any(retention_ratios <= 0.0)
        or np.any(retention_ratios >= 1.0)
        or np.any(np.diff(retention_ratios) >= 0.0)
    ):
        raise ValueError("fitted CARS state has invalid EDF retention ratios")
    if not np.array_equal(mask, subset_masks[best_iteration]):
        raise ValueError("fitted CARS state does not bind its selected mask to the best iteration")
    if float(best_rmsecv) != float(trace[best_iteration]) or best_iteration != int(np.argmin(trace)):
        raise ValueError("fitted CARS state does not bind its best RMSECV to the selected iteration")
    expected_calibration_size = _cars_support(
        n_samples=reference_samples,
        n_features=feature_count,
        max_components=max_components,
        cv_folds=cv_folds,
        calibration_fraction=float(calibration_fraction),
    )
    if calibration_size != expected_calibration_size:
        raise ValueError("fitted CARS state has an invalid calibration draw size")
    return {
        **dict(state),
        "feature_mask": mask.astype(bool, copy=True).tolist(),
        "importance_scores": scores.astype(np.float64, copy=True).tolist(),
        "rmsecv_trace": trace.astype(np.float64, copy=True).tolist(),
        "subset_masks": subset_masks.astype(bool, copy=True).tolist(),
        "optimal_components": optimal_components.astype(int, copy=True).tolist(),
        "retention_ratios": retention_ratios.astype(np.float64, copy=True).tolist(),
        "best_rmsecv": float(best_rmsecv),
        "calibration_fraction": float(calibration_fraction),
    }


def _cars_cv_splits(
    y: np.ndarray,
    *,
    cv_folds: int,
    cv_order: str,
    seed: int,
) -> list[tuple[np.ndarray, np.ndarray]]:
    """Reproduce libPLS's cyclic fold assignment under one declared ordering."""

    n_samples = len(y)
    if cv_order == "sorted_target":
        order = np.argsort(y, kind="stable")
    elif cv_order == "seeded_random":
        order = np.random.RandomState(seed).permutation(n_samples)
    else:
        order = np.arange(n_samples)
    group = np.arange(n_samples) % cv_folds
    splits = []
    for group_id in range(cv_folds):
        test = order[group == group_id]
        train = order[group != group_id]
        splits.append((train, test))
    return splits


def _score_cars_subset(
    X: np.ndarray,
    y: np.ndarray,
    mask: np.ndarray,
    *,
    max_components: int,
    cv_folds: int,
    component_selection: str,
    cv_order: str,
    seed: int,
) -> tuple[float, int]:
    """Return libPLS-style pooled RMSECV and the declared latent-variable choice."""

    candidate = X[:, mask]
    splits = _cars_cv_splits(y, cv_folds=cv_folds, cv_order=cv_order, seed=seed)
    maximum = min(max_components, candidate.shape[1], min(len(train) - 1 for train, _test in splits))
    if maximum < 1:
        raise ValueError("CARS subset cannot support one cross-validated PLS component")
    predictions = np.empty((len(y), maximum), dtype=np.float64)
    for train, test in splits:
        if float(np.ptp(y[train])) == 0.0:
            raise ValueError("CARS validation-fold training target has no variation")
        for component_index in range(maximum):
            try:
                model = pls_core.fit_simpls_exact(
                    candidate[train],
                    y[train],
                    n_components=component_index + 1,
                    scale=False,
                )
                predictions[test, component_index] = model.predict(candidate[test]).reshape(-1)
            except Exception as exc:
                raise RuntimeError("CARS validation-fold PLS fit failed") from exc
    squared_errors = (predictions - y[:, None]) ** 2
    if not np.isfinite(squared_errors).all():
        raise ValueError("CARS cross-validation produced non-finite prediction errors")
    mean_squared_errors = np.mean(squared_errors, axis=0)
    minimum_index = int(np.argmin(mean_squared_errors))
    if component_selection == "one_standard_deviation":
        deviation = float(np.std(squared_errors[:, minimum_index], ddof=1))
        candidates = np.flatnonzero(mean_squared_errors <= mean_squared_errors[minimum_index] + deviation)
        selected_index = int(candidates[0])
    else:
        selected_index = minimum_index
    return float(np.sqrt(mean_squared_errors[selected_index])), selected_index + 1


def _cars_algorithm(
    X: np.ndarray,
    y: np.ndarray,
    max_components: int,
    cv_folds: int,
    n_iterations: int,
    seed: int = 42,
    *,
    calibration_fraction: float = 0.9,
    component_selection: str = "one_standard_deviation",
    cv_order: str = "sorted_target",
    fail_on_fit_error: bool = True,
) -> dict[str, Any]:
    """Execute seeded original CARS as defined by Li et al. and ``carspls.m``."""

    if fail_on_fit_error is not True:
        raise ValueError("canonical CARS requires strict fit-error handling")
    n_samples, n_features = X.shape
    calibration_size = _cars_support(
        n_samples=n_samples,
        n_features=n_features,
        max_components=max_components,
        cv_folds=cv_folds,
        calibration_fraction=calibration_fraction,
    )
    rng = np.random.RandomState(seed)
    active = np.arange(n_features)
    coefficient_history: list[np.ndarray] = []
    subset_masks: list[np.ndarray] = []
    retention_ratios: list[float] = []
    b = float(np.log(n_features / 2.0) / (n_iterations - 1))
    a = float(np.exp(b))

    for iteration in range(n_iterations):
        calibration = rng.permutation(n_samples)[:calibration_size]
        if float(np.ptp(y[calibration])) == 0.0:
            raise ValueError("CARS Monte Carlo calibration draw has no target variation")
        components = min(max_components, calibration_size - 1, len(active))
        try:
            model = pls_core.fit_simpls_exact(
                X[calibration][:, active],
                y[calibration],
                n_components=components,
                scale=False,
            )
            active_coefficients = np.asarray(model.coefficients, dtype=np.float64).reshape(-1)[: len(active)]
        except Exception as exc:
            raise RuntimeError("CARS Monte Carlo calibration PLS fit failed") from exc
        coefficients = np.zeros(n_features, dtype=np.float64)
        coefficients[active] = active_coefficients
        mask = coefficients != 0.0
        if not mask.any() or not np.isfinite(coefficients).all():
            raise ValueError("CARS Monte Carlo PLS produced no finite weighted variables")
        coefficient_history.append(coefficients)
        subset_masks.append(mask)

        ratio = a * np.exp(-b * (iteration + 2))
        retention_ratios.append(float(ratio))
        retained_count = min(n_features, max(1, int(np.floor(n_features * ratio + 0.5))))
        weights = np.abs(coefficients)
        ranked = np.argsort(-weights, kind="stable")
        weights[ranked[retained_count:]] = 0.0
        total = float(weights.sum())
        if not np.isfinite(total) or total <= 0.0:
            raise ValueError("CARS EDF produced no positive adaptive sampling weights")
        # Original ARS draws p variables with replacement in proportion to
        # retained absolute coefficients, then carries the unique winners.
        active = np.unique(rng.choice(n_features, size=n_features, replace=True, p=weights / total))
        if active.size == 0:
            raise ValueError("CARS adaptive reweighted sampling produced an empty subset")

    rmsecv_trace: list[float] = []
    optimal_components: list[int] = []
    for mask in subset_masks:
        rmsecv, components = _score_cars_subset(
            X,
            y,
            mask,
            max_components=max_components,
            cv_folds=cv_folds,
            component_selection=component_selection,
            cv_order=cv_order,
            seed=seed,
        )
        rmsecv_trace.append(rmsecv)
        optimal_components.append(components)
    best_iteration = int(np.argmin(rmsecv_trace))
    best_coefficients = coefficient_history[best_iteration]
    return {
        "best_mask": subset_masks[best_iteration],
        "importance_scores": np.abs(best_coefficients),
        "rmsecv_trace": rmsecv_trace,
        "subset_masks": subset_masks,
        "optimal_components": optimal_components,
        "best_iteration": best_iteration,
        "retention_ratios": retention_ratios,
        "calibration_size": calibration_size,
    }


def _cars_run(
    X: np.ndarray,
    y: np.ndarray,
    max_components: int,
    cv_folds: int,
    n_iterations: int,
    seed: int = 42,
    *,
    calibration_fraction: float = 0.9,
    fail_on_fit_error: bool = True,
) -> tuple[np.ndarray, np.ndarray, list[float]]:
    """Compatibility-shaped strict numeric authority used by nested CV."""

    result = _cars_algorithm(
        X,
        y,
        max_components,
        cv_folds,
        n_iterations,
        seed,
        calibration_fraction=calibration_fraction,
        fail_on_fit_error=fail_on_fit_error,
    )
    return result["best_mask"], result["importance_scores"], result["rmsecv_trace"]


def _cars_dispatch(
    X: np.ndarray,
    y: np.ndarray,
    **parameters: Any,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Execute the sole numeric CARS implementation for live and exported DAGs."""

    resolved = _canonical_cars_parameters(parameters)
    _cars_support(
        n_samples=X.shape[0],
        n_features=X.shape[1],
        max_components=int(resolved["max_components"]),
        cv_folds=int(resolved["cv_folds"]),
        calibration_fraction=float(resolved["calibration_fraction"]),
    )
    result = _cars_algorithm(
        X,
        y,
        int(resolved["max_components"]),
        int(resolved["cv_folds"]),
        int(resolved["n_iterations"]),
        seed=int(resolved["random_seed"]),
        calibration_fraction=float(resolved["calibration_fraction"]),
        component_selection=str(resolved["component_selection"]),
        cv_order=str(resolved["cv_order"]),
        fail_on_fit_error=True,
    )
    mask = result["best_mask"]
    scores = result["importance_scores"]
    trace = result["rmsecv_trace"]
    n_selected = int(mask.sum())
    if n_selected == 0 or not trace or not np.isfinite(trace).all():
        raise ValueError("CARS did not produce a finite selected-variable result")
    outputs = {
        "default": X[:, mask],
        "X_selected": X[:, mask],
        "mask": mask,
        "scores": scores,
    }
    diagnostics = {
        "n_selected": n_selected,
        "n_total": int(X.shape[1]),
        "best_rmsecv": float(min(trace)),
        "n_iterations_run": len(trace),
        "rmsecv_trace": trace,
        "n_iterations": int(resolved["n_iterations"]),
        "max_components": int(resolved["max_components"]),
        "cv_folds": int(resolved["cv_folds"]),
        "reference_samples": int(X.shape[0]),
        "calibration_size": result["calibration_size"],
        "component_selection": resolved["component_selection"],
        "cv_order": resolved["cv_order"],
        "best_iteration": result["best_iteration"],
        "optimal_components": result["optimal_components"],
        "subset_masks": [np.asarray(value, dtype=bool).tolist() for value in result["subset_masks"]],
        "retention_ratios": result["retention_ratios"],
        "random_seed": int(resolved["random_seed"]),
        "calibration_fraction": float(resolved["calibration_fraction"]),
        "selection_scope": "full_calibration_fit_not_performance_evidence",
    }
    return outputs, diagnostics


def _cars_execute(
    X: Any,
    y: Any,
    *,
    node_id: str,
    parameters: Mapping[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Run canonical CARS and preserve the typed dataset wrapper without mutating the input."""

    node = CARSNode(node_id, dict(parameters))
    state = node.fit_fitted_state(X, y)
    X_selected = node.apply_fitted_state(X, state)
    mask = np.asarray(state["feature_mask"], dtype=bool)
    scores = np.asarray(state["importance_scores"], dtype=np.float64)
    diagnostics = {
        "n_selected": int(mask.sum()),
        "n_total": int(state["feature_count"]),
        "best_rmsecv": state["best_rmsecv"],
        "n_iterations_run": state["n_iterations_run"],
        "rmsecv_trace": list(state["rmsecv_trace"]),
        "n_iterations": state["n_iterations"],
        "max_components": state["max_components"],
        "cv_folds": state["cv_folds"],
        "reference_samples": state["reference_samples"],
        "calibration_size": state["calibration_size"],
        "random_seed": state["random_seed"],
        "calibration_fraction": state["calibration_fraction"],
        "component_selection": state["component_selection"],
        "cv_order": state["cv_order"],
        "best_iteration": state["best_iteration"],
        "optimal_components": list(state["optimal_components"]),
        "subset_masks": [list(mask) for mask in state["subset_masks"]],
        "retention_ratios": list(state["retention_ratios"]),
        "selection_scope": state["selection_scope"],
    }
    return {
        "default": X_selected,
        "X_selected": X_selected,
        "mask": mask,
        "scores": scores,
    }, diagnostics


@register_node
class CARSNode(Node):
    """Competitive Adaptive Reweighted Sampling (CARS).

    Iteratively removes variables with small PLS coefficients using
    exponentially decaying sampling.  Selects the variable subset that
    minimises RMSECV across all iterations.
    """

    metadata = NodeMetadata(
        node_type="selection.cars",
        category="selection",
        label="CARS",
        description=(
            "Selects variables by classical CARS Monte Carlo calibration sampling, an exponentially decreasing "
            "retention schedule, adaptive coefficient-weighted sampling, and fixed-fold RMSECV comparison. "
            "This full-calibration selector does not by itself establish predictive performance; use nested CV "
            "for leakage-safe evaluation."
        ),
        parameters=[
            NodeParameter(
                name="n_iterations",
                label="Iterations",
                param_type="number",
                default=50,
                min_value=10,
                max_value=200,
                max_value_reason=(
                    "Bounds stochastic PLS fits and interactive runtime while retaining a dense CARS path."
                ),
                step=5,
                description="Number of sampling iterations",
            ),
            NodeParameter(
                name="max_components",
                label="Maximum PLS Components",
                param_type="number",
                default=2,
                min_value=1,
                max_value=50,
                max_value_reason="PLS latent-variable cap; runtime also restricts it to sample and feature support.",
                step=1,
                description="Maximum latent variables evaluated for each recorded subset",
            ),
            NodeParameter(
                name="cv_folds",
                label="CV Folds",
                param_type="number",
                default=5,
                min_value=2,
                max_value=20,
                max_value_reason="Bounds repeated PLS fitting and prevents impractically small validation folds.",
                step=1,
                description="Cross-validation folds",
            ),
            NodeParameter(
                name="calibration_fraction",
                label="Monte Carlo Calibration Fraction",
                param_type="number",
                default=0.9,
                min_value=0.5,
                max_value=0.95,
                max_value_reason="Leaves at least five percent outside each Monte Carlo calibration draw.",
                step=0.05,
                description="Fraction of samples used for each stochastic coefficient fit",
                category="advanced",
            ),
            NodeParameter(
                name="component_selection",
                label="Component Selection",
                param_type="select",
                default="one_standard_deviation",
                options=["minimum_rmsecv", "one_standard_deviation"],
                description=(
                    "Choose the global RMSECV minimum or the simplest component count whose MSE lies within "
                    "one sample-error standard deviation of that minimum"
                ),
                category="advanced",
            ),
            NodeParameter(
                name="cv_order",
                label="Cross-Validation Order",
                param_type="select",
                default="sorted_target",
                options=["sorted_target", "seeded_random", "input_order"],
                description="Author-defined sample ordering before cyclic fold assignment",
                category="advanced",
            ),
            NodeParameter(
                name="random_seed",
                label="Random Seed",
                param_type="number",
                default=42,
                min_value=0,
                max_value=4_294_967_295,
                max_value_reason="Exact unsigned 32-bit seed accepted by the canonical CARS random generator.",
                step=1,
                description="Exact seed for Monte Carlo draws, adaptive sampling, and fixed CV folds",
                category="advanced",
            ),
        ],
        input_ports=[
            PortMetadata(
                name="X",
                type_ref="spectrasherpa://types/Array2D/1.0",
                required=True,
                label="Input Data Matrix",
                description="Spectral dataset or multivariate feature table",
                accepted_data_roles=["X_spectra", "X_features"],
            ),
            PortMetadata(
                name="y",
                type_ref="spectrasherpa://types/TargetMatrix/1.0",
                required=True,
                label="Target Values",
                description="Exactly one finite quantitative target",
            ),
        ],
        output_ports=[
            PortMetadata(
                name="X_selected",
                type_ref="spectrasherpa://types/SpectralDataset/1.0",
                required=True,
                label="Selected Data",
            ),
            PortMetadata(
                name="mask",
                type_ref="spectrasherpa://types/Array1D/1.0",
                required=True,
                label="Feature Mask",
            ),
            PortMetadata(
                name="scores",
                type_ref="spectrasherpa://types/Array1D/1.0",
                required=False,
                label="Importance Scores",
            ),
        ],
        input_types=["SherpaDataset"],
        output_type="dict",
        diagnostics=["n_selected", "best_rmsecv", "n_iterations_run"],
        policy=NodePolicy(),
        canonical_parameter_validator=_canonical_cars_parameters,
    )

    def fit_fitted_state(self, input_data: Any, target: Any = None) -> dict[str, object]:
        """Fit a closed feature-selection state from calibration X/y only."""

        dataset = bind_X(input_data, missing_message="CARS requires X", allow_array=True)
        matrix, target_array = _cars_inputs(dataset, target)
        resolved = self._resolve_params()
        outputs, diagnostics = _cars_dispatch(matrix, target_array, **resolved)
        axis_digest, labels_digest, axis_units, axis_quantity = _feature_axis_identity(
            dataset, features=matrix.shape[1]
        )
        state = {
            "serializer": _STATE_SERIALIZER,
            "feature_count": int(matrix.shape[1]),
            "feature_axis_values_sha256": axis_digest,
            "feature_axis_labels_sha256": labels_digest,
            "feature_axis_units": axis_units,
            "feature_axis_quantity": axis_quantity,
            "feature_mask": np.asarray(outputs["mask"], dtype=bool).tolist(),
            "importance_scores": np.asarray(outputs["scores"], dtype=np.float64).tolist(),
            "rmsecv_trace": list(diagnostics["rmsecv_trace"]),
            "best_rmsecv": diagnostics["best_rmsecv"],
            "n_iterations_run": diagnostics["n_iterations_run"],
            "n_iterations": diagnostics["n_iterations"],
            "max_components": diagnostics["max_components"],
            "cv_folds": diagnostics["cv_folds"],
            "reference_samples": diagnostics["reference_samples"],
            "calibration_size": diagnostics["calibration_size"],
            "random_seed": diagnostics["random_seed"],
            "calibration_fraction": diagnostics["calibration_fraction"],
            "component_selection": diagnostics["component_selection"],
            "cv_order": diagnostics["cv_order"],
            "best_iteration": diagnostics["best_iteration"],
            "optimal_components": diagnostics["optimal_components"],
            "subset_masks": diagnostics["subset_masks"],
            "retention_ratios": diagnostics["retention_ratios"],
            "selection_scope": diagnostics["selection_scope"],
        }
        return _validate_cars_state(state)

    def apply_fitted_state(self, input_data: Any, state: Mapping[str, object]) -> Any:
        """Apply a frozen CARS mask to X without reading or inferring a target."""

        validated = _validate_cars_state(state)
        dataset = bind_X(input_data, missing_message="CARS requires X", allow_array=True)
        matrix = to_numpy_2d(dataset, name="X", dtype=np.float64)
        if not np.isfinite(matrix).all() or matrix.shape[1] != validated["feature_count"]:
            raise ValueError("CARS apply input does not match the fitted feature count")
        axis_digest, labels_digest, axis_units, axis_quantity = _feature_axis_identity(
            dataset, features=matrix.shape[1]
        )
        if (
            axis_digest != validated["feature_axis_values_sha256"]
            or labels_digest != validated["feature_axis_labels_sha256"]
            or axis_units != validated["feature_axis_units"]
            or axis_quantity != validated["feature_axis_quantity"]
        ):
            raise ValueError("CARS apply input does not match the fitted feature axis")
        mask = np.asarray(validated["feature_mask"], dtype=bool)
        scores = np.asarray(validated["importance_scores"], dtype=np.float64)
        selected = build_dataset_like(matrix[:, mask], dataset)
        feature_axis = getattr(dataset, "feature_axis", None)
        if feature_axis is not None and (feature_axis.values is not None or feature_axis.labels is not None):
            selected.feature_axis = type(feature_axis)(
                values=None if feature_axis.values is None else np.asarray(feature_axis.values)[mask],
                labels=(
                    None
                    if feature_axis.labels is None
                    else [label for label, retained in zip(feature_axis.labels, mask, strict=True) if retained]
                ),
                units=feature_axis.units,
                display_units=feature_axis.display_units,
                quantity=feature_axis.quantity,
                title=feature_axis.title,
                include_mask=np.ones(int(mask.sum()), dtype=bool),
                selection_method="cars",
                selection_scores=scores[mask],
            )
        selected.meta["feature_mask"] = mask.tolist()
        add_processing_step(
            selected,
            "selection.cars",
            {
                "state_serializer": _STATE_SERIALIZER,
                "transform_state": dict(validated),
                "n_selected": int(mask.sum()),
            },
            self.node_id,
        )
        return selected

    def generate_python(
        self,
        inputs: Mapping[str, str],
        indent: str = "    ",
        use_scp: bool = True,
    ) -> list[str]:
        """Export the same numeric dispatcher used by live DAG execution."""

        del use_scp
        X_expression = inputs.get("X", inputs.get("default", "input_data"))
        y_expression = inputs.get("y", "None")
        parameters = self._resolve_params()
        return [
            f"{indent}# --- Canonical CARS variable selection ({self.node_id}) ---",
            (f"{indent}from spectra_sherpa.app.services.dag.nodes.selection.cars_node import _cars_execute"),
            f"{indent}_cars_outputs, _cars_diagnostics = _cars_execute(",
            f"{indent}    {X_expression}, {y_expression},",
            f"{indent}    node_id={self.node_id!r}, parameters={parameters!r},",
            f"{indent})",
            f"{indent}results[{self.node_id!r}] = _cars_outputs",
        ]

    async def execute(self, X: Any = None, y: Any = None, **kwargs: Any) -> NodeResult:
        del kwargs
        outputs, diagnostics = _cars_execute(
            X,
            y,
            node_id=self.node_id,
            parameters=self._resolve_params(),
        )

        logger.info(
            "CARS: %s/%s variables, best RMSECV=%.4f",
            diagnostics["n_selected"],
            diagnostics["n_total"],
            diagnostics["best_rmsecv"],
        )
        return NodeResult(outputs=outputs, diagnostics=diagnostics)


bind_stable_execution_contract(
    CARSNode,
    runtime_family=RuntimeFamily.SHERPA_NATIVE,
    lifecycle_kind=LifecycleKind.FITTED_TRANSFORM,
    implementation_id="spectrasherpa.selection.cars",
    implementation_version="1.1.0",
    required_worker_capabilities=(WorkerCapability.READ_DATASET,),
    managed_optimization_eligibility=(ManagedOptimizationEligibility.LOCAL,),
    sample_effect="preserves_samples",
    feature_effect="filters_features",
    axis_effect="changes_axis",
    unit_effect="preserves_units",
    resource_hints={"timeout_seconds": 120, "cpu_seconds": 120, "memory_bytes": 1_073_741_824},
    license_id="Apache-2.0",
    help_reference="docs/nodes/selection-validation.md",
    implementation_modules=(pls_core,),
    implementation_distributions=("numpy",),
    runtime_requirements=(("numpy", "1.26.4"),),
    citations=(
        "Li et al., Analytica Chimica Acta 648 (2009) 77-84",
        pls_core.CITATION,
    ),
    fitted_state_serializer=_STATE_SERIALIZER,
    deterministic=False,
    seed_parameter="random_seed",
    target_access=TargetAccess.FIT_ONLY,
    group_access="none",
)


__all__ = [
    "CARSNode",
    "_canonical_cars_parameters",
    "_cars_dispatch",
    "_cars_execute",
    "_cars_inputs",
    "_cars_run",
    "_validate_cars_state",
]
