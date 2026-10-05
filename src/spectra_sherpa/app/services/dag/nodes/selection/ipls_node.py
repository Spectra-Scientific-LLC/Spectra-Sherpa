"""Reference interval PLS (iPLS) variable selection.

Registered as ``selection.ipls``.

The standard operation divides an ordered feature axis into contiguous,
non-overlapping intervals, fits one locally optimized PLS model per interval,
and selects the single interval with the lowest RMSECV.  The full-spectrum PLS
model is evaluated on the same folds as the scientific reference.

Reference: Nørgaard et al., Applied Spectroscopy 54 (2000) 413-419.
"""

from __future__ import annotations

import hashlib
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
_STATE_SERIALIZER = "spectrasherpa.selection.ipls.state/3"
_MAX_MODEL_FIT_BUDGET = 20_000


def _canonical_ipls_parameters(parameters: Mapping[str, Any]) -> dict[str, int | str]:
    """Return the exact closed parameter representation for standard iPLS."""

    allowed = {"n_intervals", "max_components", "cv_folds", "cv_order", "random_seed"}
    unknown = sorted(set(parameters) - allowed)
    if unknown:
        raise ValueError(f"selection.ipls accepts only: {', '.join(sorted(allowed))}")
    resolved: dict[str, Any] = {
        "n_intervals": parameters.get("n_intervals", 20),
        "max_components": parameters.get("max_components", 5),
        "cv_folds": parameters.get("cv_folds", 5),
        "cv_order": parameters.get("cv_order", "sorted_target"),
        "random_seed": parameters.get("random_seed", 42),
    }
    for name in ("n_intervals", "max_components", "cv_folds", "random_seed"):
        if isinstance(resolved[name], bool) or not isinstance(resolved[name], int):
            raise ValueError(f"iPLS {name} must be an integer")
    if not 2 <= resolved["n_intervals"] <= 100:
        raise ValueError("iPLS n_intervals must be between 2 and 100")
    if not 1 <= resolved["max_components"] <= 30:
        raise ValueError("iPLS max_components must be between 1 and 30")
    if not 2 <= resolved["cv_folds"] <= 20:
        raise ValueError("iPLS cv_folds must be between 2 and 20")
    if not isinstance(resolved["cv_order"], str) or resolved["cv_order"] not in {
        "sorted_target",
        "seeded_random",
        "input_order",
    }:
        raise ValueError("iPLS cv_order must be sorted_target, seeded_random, or input_order")
    if not 0 <= resolved["random_seed"] <= 4_294_967_295:
        raise ValueError("iPLS random_seed must be an unsigned 32-bit integer")
    return {
        "n_intervals": resolved["n_intervals"],
        "max_components": resolved["max_components"],
        "cv_folds": resolved["cv_folds"],
        "cv_order": resolved["cv_order"],
        "random_seed": resolved["random_seed"],
    }


def _ipls_inputs(X: Any, y: Any) -> tuple[Any, np.ndarray, np.ndarray]:
    """Bind one finite feature matrix and exactly one quantitative target."""

    dataset = bind_X(X, missing_message="iPLS requires X", allow_array=True)
    target_value = bind_y(
        y,
        X=dataset,
        required=True,
        infer_from_X=True,
        dataset_as_data=False,
        target_type="continuous",
    )
    matrix = to_numpy_2d(dataset, name="X", dtype=np.float64)
    target = to_numpy_y(target_value, name="y", expected_samples=matrix.shape[0])
    if target.ndim == 2:
        if target.shape[1] != 1:
            raise ValueError("iPLS requires exactly one quantitative target")
        target = target[:, 0]
    target = np.asarray(target, dtype=np.float64).reshape(-1)
    if not np.isfinite(matrix).all() or not np.isfinite(target).all():
        raise ValueError("iPLS inputs must be finite")
    if matrix.shape[0] < 3 or matrix.shape[1] < 2:
        raise ValueError("iPLS requires at least three samples and two ordered features")
    if float(np.ptp(target)) == 0.0:
        raise ValueError("iPLS requires a quantitative target with non-zero variation")
    return dataset, matrix, target


def _ipls_fold_assignments(
    target: np.ndarray,
    *,
    cv_folds: int,
    cv_order: str,
    random_seed: int,
) -> np.ndarray:
    """Create one deterministic Venetian-blinds partition shared by all models."""

    n_samples = target.shape[0]
    if cv_folds > n_samples:
        raise ValueError("iPLS cv_folds may not exceed the sample count")
    if cv_order == "sorted_target":
        ordered = np.argsort(target, kind="stable")
    elif cv_order == "seeded_random":
        ordered = np.random.default_rng(random_seed).permutation(n_samples)
    else:
        ordered = np.arange(n_samples, dtype=np.int64)
    assignments = np.empty(n_samples, dtype=np.int64)
    assignments[ordered] = np.arange(n_samples, dtype=np.int64) % cv_folds
    for fold in range(cv_folds):
        validation_count = int(np.sum(assignments == fold))
        if validation_count < 1 or n_samples - validation_count < 2:
            raise ValueError("iPLS cross-validation leaves insufficient calibration or validation support")
    return assignments


def _split_digest(assignments: np.ndarray) -> str:
    return hashlib.sha256(np.asarray(assignments, dtype="<i8").tobytes(order="C")).hexdigest()


def _interval_bounds(n_features: int, n_intervals: int) -> tuple[tuple[int, int], ...]:
    """Divide the complete ordered axis into deterministic near-equal intervals."""

    if n_intervals > n_features:
        raise ValueError("iPLS n_intervals may not exceed the feature count")
    feature_groups = np.array_split(np.arange(n_features, dtype=np.int64), n_intervals)
    bounds = tuple((int(group[0]), int(group[-1]) + 1) for group in feature_groups)
    if any(lo >= hi for lo, hi in bounds) or bounds[0][0] != 0 or bounds[-1][1] != n_features:
        raise ValueError("iPLS could not construct complete non-empty contiguous intervals")
    if any(left[1] != right[0] for left, right in zip(bounds, bounds[1:], strict=False)):
        raise ValueError("iPLS intervals must cover the feature axis without gaps or overlap")
    return bounds


def _component_rmsecv(
    matrix: np.ndarray,
    target: np.ndarray,
    feature_indices: np.ndarray,
    assignments: np.ndarray,
    *,
    max_components: int,
) -> tuple[float, int, tuple[float, ...]]:
    """Select the smallest component count attaining the minimum pooled RMSECV.

    This is the global minimum of the RMSECV-vs-component-count trace, with
    exact ties broken toward the fewest components (``np.argmin`` returns the
    first occurrence). It is not a local-minimum/turning-point detector.
    """

    subset = matrix[:, feature_indices]
    cv_folds = int(assignments.max()) + 1
    smallest_training_fold = min(int(np.sum(assignments != fold)) for fold in range(cv_folds))
    supported_components = min(max_components, subset.shape[1], smallest_training_fold - 1)
    if supported_components < 1:
        raise ValueError("iPLS interval has insufficient support for one PLS component")
    rmsecv_values: list[float] = []
    for component_count in range(1, supported_components + 1):
        predictions = np.empty(target.shape[0], dtype=np.float64)
        for fold in range(cv_folds):
            train = assignments != fold
            validate = ~train
            try:
                model = pls_core.fit_simpls_exact(
                    subset[train],
                    target[train],
                    n_components=component_count,
                    scale=False,
                )
                fold_predictions = np.asarray(model.predict(subset[validate]), dtype=np.float64).reshape(-1)
            except Exception as exc:
                raise ValueError(f"iPLS PLS fit failed for {component_count} component(s) in fold {fold}") from exc
            if fold_predictions.shape != (int(np.sum(validate)),) or not np.isfinite(fold_predictions).all():
                raise ValueError("iPLS produced invalid held-out predictions")
            predictions[validate] = fold_predictions
        rmsecv = float(np.sqrt(np.mean(np.square(target - predictions))))
        if not np.isfinite(rmsecv):
            raise ValueError("iPLS produced a non-finite RMSECV")
        rmsecv_values.append(rmsecv)
    best_index = int(np.argmin(np.asarray(rmsecv_values, dtype=np.float64)))
    return rmsecv_values[best_index], best_index + 1, tuple(rmsecv_values)


def _ipls_dispatch(
    matrix: np.ndarray,
    target: np.ndarray,
    *,
    n_intervals: int,
    max_components: int,
    cv_folds: int,
    cv_order: str,
    random_seed: int,
) -> dict[str, object]:
    """Execute standard single-interval iPLS on one calibration dataset."""

    n_samples, n_features = matrix.shape
    bounds = _interval_bounds(n_features, n_intervals)
    assignments = _ipls_fold_assignments(
        target,
        cv_folds=cv_folds,
        cv_order=cv_order,
        random_seed=random_seed,
    )
    fit_budget = (n_intervals + 1) * cv_folds * max_components
    if fit_budget > _MAX_MODEL_FIT_BUDGET:
        raise ValueError(
            f"iPLS requested model-fit budget {fit_budget} exceeds {_MAX_MODEL_FIT_BUDGET}; "
            "reduce intervals, components, or folds"
        )

    interval_rmsecv: list[float] = []
    interval_components: list[int] = []
    interval_component_rmsecv: list[list[float]] = []
    for lower, upper in bounds:
        score, components, component_trace = _component_rmsecv(
            matrix,
            target,
            np.arange(lower, upper, dtype=np.int64),
            assignments,
            max_components=max_components,
        )
        interval_rmsecv.append(score)
        interval_components.append(components)
        interval_component_rmsecv.append(list(component_trace))

    global_rmsecv, global_components, global_component_rmsecv = _component_rmsecv(
        matrix,
        target,
        np.arange(n_features, dtype=np.int64),
        assignments,
        max_components=max_components,
    )
    best_interval = int(np.argmin(np.asarray(interval_rmsecv, dtype=np.float64)))
    lower, upper = bounds[best_interval]
    mask = np.zeros(n_features, dtype=bool)
    mask[lower:upper] = True
    scores = np.empty(n_features, dtype=np.float64)
    for interval_index, (start, stop) in enumerate(bounds):
        scores[start:stop] = 1.0 / (1.0 + interval_rmsecv[interval_index])
    return {
        "feature_mask": mask.tolist(),
        "importance_scores": scores.tolist(),
        "interval_bounds": [list(bound) for bound in bounds],
        "interval_rmsecv": interval_rmsecv,
        "interval_components": interval_components,
        "interval_component_rmsecv": interval_component_rmsecv,
        "best_interval": best_interval,
        "best_rmsecv": interval_rmsecv[best_interval],
        "best_components": interval_components[best_interval],
        "global_rmsecv": global_rmsecv,
        "global_components": global_components,
        "global_component_rmsecv": list(global_component_rmsecv),
        "beats_global_rmsecv": bool(interval_rmsecv[best_interval] < global_rmsecv),
        "fold_assignments": assignments.tolist(),
        "split_digest": _split_digest(assignments),
        "model_fit_budget": fit_budget,
        "reference_samples": n_samples,
        "feature_count": n_features,
    }


def _feature_axis_identity(dataset: Any, *, features: int) -> tuple[str | None, str | None, str | None, str | None]:
    return _canonical_feature_axis_identity(dataset, features=features, context="iPLS")


def _finite_number_list(value: object, *, name: str, length: int | None = None) -> list[float]:
    if not isinstance(value, list) or (length is not None and len(value) != length):
        raise ValueError(f"fitted iPLS state has invalid {name}")
    if any(isinstance(item, bool) or not isinstance(item, (int, float)) or not np.isfinite(item) for item in value):
        raise ValueError(f"fitted iPLS state has invalid {name}")
    return [float(item) for item in value]


def _validate_ipls_state(state: Mapping[str, object]) -> dict[str, object]:
    """Validate and copy the closed iPLS fitted-state representation."""

    required = {
        "serializer",
        "feature_count",
        "feature_axis_values_sha256",
        "feature_axis_labels_sha256",
        "feature_axis_units",
        "feature_axis_quantity",
        "feature_mask",
        "importance_scores",
        "n_intervals",
        "max_components",
        "cv_folds",
        "cv_order",
        "random_seed",
        "interval_bounds",
        "interval_rmsecv",
        "interval_components",
        "interval_component_rmsecv",
        "best_interval",
        "best_rmsecv",
        "best_components",
        "global_rmsecv",
        "global_components",
        "global_component_rmsecv",
        "beats_global_rmsecv",
        "fold_assignments",
        "split_digest",
        "model_fit_budget",
        "reference_samples",
        "selection_scope",
    }
    if not isinstance(state, Mapping) or set(state) != required or state.get("serializer") != _STATE_SERIALIZER:
        raise ValueError("fitted iPLS state does not use the closed serializer schema")
    parameters = _canonical_ipls_parameters(
        {name: state[name] for name in ("n_intervals", "max_components", "cv_folds", "cv_order", "random_seed")}
    )
    feature_count = state["feature_count"]
    reference_samples = state["reference_samples"]
    if isinstance(feature_count, bool) or not isinstance(feature_count, int) or feature_count < 2:
        raise ValueError("fitted iPLS state has invalid feature_count")
    if isinstance(reference_samples, bool) or not isinstance(reference_samples, int) or reference_samples < 3:
        raise ValueError("fitted iPLS state has invalid reference_samples")
    n_intervals = int(parameters["n_intervals"])
    if n_intervals > feature_count:
        raise ValueError("fitted iPLS intervals exceed feature_count")

    mask_value = state["feature_mask"]
    if (
        not isinstance(mask_value, list)
        or len(mask_value) != feature_count
        or any(not isinstance(item, bool) for item in mask_value)
        or not any(mask_value)
    ):
        raise ValueError("fitted iPLS state has invalid feature_mask")
    scores = _finite_number_list(state["importance_scores"], name="importance_scores", length=feature_count)
    if any(value < 0 for value in scores):
        raise ValueError("fitted iPLS importance_scores must be non-negative")

    bounds_value = state["interval_bounds"]
    if not isinstance(bounds_value, list) or len(bounds_value) != n_intervals:
        raise ValueError("fitted iPLS state has invalid interval_bounds")
    bounds: list[list[int]] = []
    for item in bounds_value:
        if (
            not isinstance(item, list)
            or len(item) != 2
            or any(isinstance(value, bool) or not isinstance(value, int) for value in item)
            or not 0 <= item[0] < item[1] <= feature_count
        ):
            raise ValueError("fitted iPLS state has invalid interval_bounds")
        bounds.append(list(item))
    if (
        bounds[0][0] != 0
        or bounds[-1][1] != feature_count
        or any(left[1] != right[0] for left, right in zip(bounds, bounds[1:], strict=False))
    ):
        raise ValueError("fitted iPLS intervals do not partition the complete feature axis")
    canonical_bounds = [list(bound) for bound in _interval_bounds(feature_count, n_intervals)]
    if bounds != canonical_bounds:
        raise ValueError("fitted iPLS intervals do not match the canonical near-equal partition")

    assignments = state["fold_assignments"]
    cv_folds = int(parameters["cv_folds"])
    if (
        not isinstance(assignments, list)
        or len(assignments) != reference_samples
        or any(
            isinstance(value, bool) or not isinstance(value, int) or not 0 <= value < cv_folds for value in assignments
        )
        or set(assignments) != set(range(cv_folds))
    ):
        raise ValueError("fitted iPLS fold_assignments are invalid")
    split_digest = state["split_digest"]
    if not isinstance(split_digest, str) or split_digest != _split_digest(np.asarray(assignments, dtype=np.int64)):
        raise ValueError("fitted iPLS split_digest does not bind the fold assignments")
    smallest_training_fold = min(sum(assignment != fold for assignment in assignments) for fold in range(cv_folds))
    max_components = int(parameters["max_components"])

    interval_rmsecv = _finite_number_list(state["interval_rmsecv"], name="interval_rmsecv", length=n_intervals)
    if any(value < 0 for value in interval_rmsecv):
        raise ValueError("fitted iPLS RMSECV values must be non-negative")
    interval_components_value = state["interval_components"]
    if (
        not isinstance(interval_components_value, list)
        or len(interval_components_value) != n_intervals
        or any(
            isinstance(value, bool) or not isinstance(value, int) or value < 1 for value in interval_components_value
        )
    ):
        raise ValueError("fitted iPLS state has invalid interval_components")
    component_traces_value = state["interval_component_rmsecv"]
    if not isinstance(component_traces_value, list) or len(component_traces_value) != n_intervals:
        raise ValueError("fitted iPLS state has invalid interval_component_rmsecv")
    component_traces: list[list[float]] = []
    for interval_index, trace in enumerate(component_traces_value):
        validated_trace = _finite_number_list(trace, name="interval_component_rmsecv")
        selected_components = interval_components_value[interval_index]
        lower, upper = bounds[interval_index]
        supported_components = min(max_components, upper - lower, smallest_training_fold - 1)
        if (
            len(validated_trace) != supported_components
            or selected_components > len(validated_trace)
            or int(np.argmin(validated_trace)) + 1 != selected_components
            or validated_trace[selected_components - 1] != interval_rmsecv[interval_index]
        ):
            raise ValueError("fitted iPLS component trace does not bind the selected interval score")
        component_traces.append(validated_trace)

    best_interval = state["best_interval"]
    best_components = state["best_components"]
    if isinstance(best_interval, bool) or not isinstance(best_interval, int) or not 0 <= best_interval < n_intervals:
        raise ValueError("fitted iPLS state has invalid best_interval")
    if best_interval != int(np.argmin(interval_rmsecv)):
        raise ValueError("fitted iPLS best_interval is not the first minimum RMSECV interval")
    if (
        isinstance(best_components, bool)
        or not isinstance(best_components, int)
        or best_components != interval_components_value[best_interval]
    ):
        raise ValueError("fitted iPLS best_components do not match the selected interval")
    best_rmsecv = state["best_rmsecv"]
    global_rmsecv = state["global_rmsecv"]
    if (
        isinstance(best_rmsecv, bool)
        or not isinstance(best_rmsecv, (int, float))
        or not np.isfinite(best_rmsecv)
        or float(best_rmsecv) != interval_rmsecv[best_interval]
        or isinstance(global_rmsecv, bool)
        or not isinstance(global_rmsecv, (int, float))
        or not np.isfinite(global_rmsecv)
        or float(global_rmsecv) < 0
    ):
        raise ValueError("fitted iPLS best/global RMSECV binding is invalid")
    global_trace = _finite_number_list(state["global_component_rmsecv"], name="global_component_rmsecv")
    global_components = state["global_components"]
    supported_global_components = min(max_components, feature_count, smallest_training_fold - 1)
    if (
        isinstance(global_components, bool)
        or not isinstance(global_components, int)
        or len(global_trace) != supported_global_components
        or not 1 <= global_components <= len(global_trace)
        or int(np.argmin(global_trace)) + 1 != global_components
        or global_trace[global_components - 1] != float(global_rmsecv)
    ):
        raise ValueError("fitted iPLS global component trace is invalid")
    beats_global = state["beats_global_rmsecv"]
    if not isinstance(beats_global, bool) or beats_global != (float(best_rmsecv) < float(global_rmsecv)):
        raise ValueError("fitted iPLS global comparison is invalid")

    selected_lower, selected_upper = bounds[best_interval]
    expected_mask = [selected_lower <= index < selected_upper for index in range(feature_count)]
    if mask_value != expected_mask:
        raise ValueError("fitted iPLS feature_mask does not match the selected interval")
    expected_scores = [0.0] * feature_count
    for interval_index, (lower, upper) in enumerate(bounds):
        score = 1.0 / (1.0 + interval_rmsecv[interval_index])
        expected_scores[lower:upper] = [score] * (upper - lower)
    if not np.array_equal(np.asarray(scores), np.asarray(expected_scores)):
        raise ValueError("fitted iPLS importance_scores do not match interval RMSECV")

    fit_budget = state["model_fit_budget"]
    expected_budget = (n_intervals + 1) * cv_folds * max_components
    if (
        isinstance(fit_budget, bool)
        or not isinstance(fit_budget, int)
        or fit_budget != expected_budget
        or fit_budget > _MAX_MODEL_FIT_BUDGET
    ):
        raise ValueError("fitted iPLS model_fit_budget is invalid")
    if state["selection_scope"] != "full_calibration_fit_not_performance_evidence":
        raise ValueError("fitted iPLS state has invalid selection_scope")
    for name in ("feature_axis_values_sha256", "feature_axis_labels_sha256"):
        digest = state[name]
        if digest is not None and (
            not isinstance(digest, str)
            or len(digest) != 64
            or any(character not in "0123456789abcdef" for character in digest)
        ):
            raise ValueError(f"fitted iPLS state has invalid {name}")
    if state["feature_axis_units"] is not None and not isinstance(state["feature_axis_units"], str):
        raise ValueError("fitted iPLS state has invalid feature_axis_units")
    validated_axis_quantity(state["feature_axis_quantity"], context="fitted iPLS")
    return {
        **dict(state),
        "feature_mask": list(mask_value),
        "importance_scores": scores,
        "interval_bounds": bounds,
        "interval_rmsecv": interval_rmsecv,
        "interval_components": list(interval_components_value),
        "interval_component_rmsecv": component_traces,
        "global_component_rmsecv": global_trace,
        "fold_assignments": list(assignments),
    }


def _ipls_execute(
    X: Any,
    y: Any,
    *,
    node_id: str,
    parameters: Mapping[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Run canonical iPLS and preserve the typed wrapper without mutating input."""

    node = IPLSNode(node_id, dict(parameters))
    state = node.fit_fitted_state(X, y)
    selected = node.apply_fitted_state(X, state)
    mask = np.asarray(state["feature_mask"], dtype=bool)
    scores = np.asarray(state["importance_scores"], dtype=np.float64)
    diagnostics = {
        name: state[name]
        for name in (
            "n_intervals",
            "max_components",
            "cv_folds",
            "cv_order",
            "random_seed",
            "interval_bounds",
            "interval_rmsecv",
            "interval_components",
            "interval_component_rmsecv",
            "best_interval",
            "best_rmsecv",
            "best_components",
            "global_rmsecv",
            "global_components",
            "global_component_rmsecv",
            "beats_global_rmsecv",
            "fold_assignments",
            "split_digest",
            "model_fit_budget",
            "reference_samples",
            "selection_scope",
        )
    }
    diagnostics["n_selected"] = int(mask.sum())
    diagnostics["n_total"] = int(state["feature_count"])
    diagnostics["rmsecv_improvement"] = float(state["global_rmsecv"]) - float(state["best_rmsecv"])
    diagnostics["comparison_warning"] = (
        None
        if state["beats_global_rmsecv"]
        else "The best local interval did not improve RMSECV over the full-spectrum reference model."
    )
    return {"default": selected, "X_selected": selected, "mask": mask, "scores": scores}, diagnostics


@register_node
class IPLSNode(Node):
    """Standard interval PLS selection of one contiguous spectral region."""

    metadata = NodeMetadata(
        node_type="selection.ipls",
        category="selection",
        label="Interval PLS (iPLS)",
        description=(
            "Divides the ordered feature axis into contiguous non-overlapping intervals, optimizes one PLS model "
            "per interval on a shared cross-validation partition, and retains the single lowest-RMSECV interval. "
            "The full-spectrum PLS model is reported as a reference. This calibration-set selection is not by "
            "itself predictive-performance evidence; use nested CV for leakage-safe evaluation."
        ),
        parameters=[
            NodeParameter(
                name="n_intervals",
                label="Number of Intervals",
                param_type="number",
                default=20,
                min_value=2,
                max_value=100,
                max_value_reason="Bounds the number of independently cross-validated local PLS models.",
                step=1,
                description="Number of contiguous, non-overlapping intervals spanning the complete feature axis",
            ),
            NodeParameter(
                name="max_components",
                label="Maximum PLS Components",
                param_type="number",
                default=5,
                min_value=1,
                max_value=30,
                max_value_reason="Bounds latent-variable fitting for every local and full-spectrum model.",
                step=1,
                description="Maximum PLS latent variables evaluated independently for each interval",
            ),
            NodeParameter(
                name="cv_folds",
                label="CV Folds",
                param_type="number",
                default=5,
                min_value=2,
                max_value=20,
                max_value_reason="Bounds repeated local PLS fitting and requires supported held-out folds.",
                step=1,
                description="Venetian-blinds folds shared by every interval and the full-spectrum reference",
            ),
            NodeParameter(
                name="cv_order",
                label="Cross-Validation Order",
                param_type="select",
                default="sorted_target",
                options=["sorted_target", "seeded_random", "input_order"],
                description="Sample order before cyclic Venetian-blinds fold assignment",
                category="advanced",
            ),
            NodeParameter(
                name="random_seed",
                label="Random Seed",
                param_type="number",
                default=42,
                min_value=0,
                max_value=4_294_967_295,
                max_value_reason="Exact unsigned 32-bit seed used only by seeded-random CV ordering.",
                step=1,
                description="Seed for the optional seeded-random sample order",
                category="advanced",
            ),
        ],
        input_ports=[
            PortMetadata(
                name="X",
                type_ref="spectrasherpa://types/Array2D/1.0",
                required=True,
                label="Input Data Matrix",
                description="Spectral dataset or ordered multivariate feature table",
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
                label="Selected Interval Data",
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
                label="Interval Scores",
            ),
        ],
        input_types=["SherpaDataset"],
        output_type="dict",
        diagnostics=["best_interval", "best_rmsecv", "global_rmsecv", "n_selected"],
        policy=NodePolicy(),
        canonical_parameter_validator=_canonical_ipls_parameters,
    )

    def fit_fitted_state(self, input_data: Any, target: Any = None) -> dict[str, object]:
        dataset, matrix, target_array = _ipls_inputs(input_data, target)
        resolved = self._resolve_params()
        result = _ipls_dispatch(matrix, target_array, **resolved)
        axis_digest, labels_digest, axis_units, axis_quantity = _feature_axis_identity(
            dataset, features=matrix.shape[1]
        )
        state = {
            "serializer": _STATE_SERIALIZER,
            "feature_axis_values_sha256": axis_digest,
            "feature_axis_labels_sha256": labels_digest,
            "feature_axis_units": axis_units,
            "feature_axis_quantity": axis_quantity,
            "selection_scope": "full_calibration_fit_not_performance_evidence",
            **resolved,
            **result,
        }
        return _validate_ipls_state(state)

    def apply_fitted_state(self, input_data: Any, state: Mapping[str, object]) -> Any:
        validated = _validate_ipls_state(state)
        dataset = bind_X(input_data, missing_message="iPLS requires X", allow_array=True)
        matrix = to_numpy_2d(dataset, name="X", dtype=np.float64)
        if not np.isfinite(matrix).all() or matrix.shape[1] != validated["feature_count"]:
            raise ValueError("iPLS apply input does not match the fitted feature count")
        axis_digest, labels_digest, axis_units, axis_quantity = _feature_axis_identity(
            dataset, features=matrix.shape[1]
        )
        if (
            axis_digest != validated["feature_axis_values_sha256"]
            or labels_digest != validated["feature_axis_labels_sha256"]
            or axis_units != validated["feature_axis_units"]
            or axis_quantity != validated["feature_axis_quantity"]
        ):
            raise ValueError("iPLS apply input does not match the fitted feature axis")
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
                selection_method="ipls",
                selection_scores=scores[mask],
            )
        selected.meta["feature_mask"] = mask.tolist()
        add_processing_step(
            selected,
            "selection.ipls",
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
        del use_scp
        X_expression = inputs.get("X", inputs.get("default", "input_data"))
        y_expression = inputs.get("y", "None")
        parameters = self._resolve_params()
        return [
            f"{indent}# --- Canonical interval PLS selection ({self.node_id}) ---",
            f"{indent}from spectra_sherpa.app.services.dag.nodes.selection.ipls_node import _ipls_execute",
            f"{indent}_ipls_outputs, _ipls_diagnostics = _ipls_execute(",
            f"{indent}    {X_expression}, {y_expression},",
            f"{indent}    node_id={self.node_id!r}, parameters={parameters!r},",
            f"{indent})",
            f"{indent}results[{self.node_id!r}] = _ipls_outputs",
        ]

    async def execute(self, X: Any = None, y: Any = None, **kwargs: Any) -> NodeResult:
        del kwargs
        outputs, diagnostics = _ipls_execute(
            X,
            y,
            node_id=self.node_id,
            parameters=self._resolve_params(),
        )
        logger.info(
            "iPLS: interval %s selected with %s/%s variables; RMSECV %.4f (global %.4f)",
            diagnostics["best_interval"],
            diagnostics["n_selected"],
            diagnostics["n_total"],
            diagnostics["best_rmsecv"],
            diagnostics["global_rmsecv"],
        )
        return NodeResult(outputs=outputs, diagnostics=diagnostics)


bind_stable_execution_contract(
    IPLSNode,
    runtime_family=RuntimeFamily.SHERPA_NATIVE,
    lifecycle_kind=LifecycleKind.FITTED_TRANSFORM,
    implementation_id="spectrasherpa.selection.ipls",
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
        "Nørgaard et al., Applied Spectroscopy 54 (2000) 413-419",
        pls_core.CITATION,
    ),
    fitted_state_serializer=_STATE_SERIALIZER,
    deterministic=False,
    seed_parameter="random_seed",
    target_access=TargetAccess.FIT_ONLY,
    group_access="none",
)


__all__ = [
    "IPLSNode",
    "_canonical_ipls_parameters",
    "_component_rmsecv",
    "_interval_bounds",
    "_ipls_dispatch",
    "_ipls_execute",
    "_ipls_fold_assignments",
    "_validate_ipls_state",
]
