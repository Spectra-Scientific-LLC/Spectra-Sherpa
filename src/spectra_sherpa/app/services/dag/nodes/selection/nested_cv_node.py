"""Leakage-safe Nested Cross-Validation node.

Registered as ``selection.nested_cv``.

Performs variable selection *inside* each CV fold to prevent information
leakage.  For each outer fold:
  1. Tune selection and PLS together inside inner-training folds
  2. Refit selection on the complete outer-training fold
  3. Fit PLS on the selected outer-training variables
  4. Predict the held-out set using only selected variables

Reports outer-fold RMSECV, R², Q² and selection stability.
Generalization claims depend on the declared sampling design.

This is the correct way to evaluate variable selection in chemometrics —
selecting on full data then cross-validating is optimistically biased.

Reference: Filzmoser et al., J. Chemometrics 23 (2009) 160-171.
"""

from __future__ import annotations

import hashlib
import logging
from typing import Any, Mapping

import numpy as np
from sklearn.model_selection import KFold

import spectra_sherpa.app.services.dag.regression_comparison as regression_comparison
import spectra_sherpa.sdk.validate as sdk_validate
from spectra_sherpa.app.services.dag.stable_execution_contract import bind_stable_execution_contract
from spectra_sherpa.execution_contract_vocabulary import (
    LifecycleKind,
    ManagedOptimizationEligibility,
    RuntimeFamily,
    WorkerCapability,
)

from ... import out_of_fold_evidence
from ...io_contracts import bind_X, bind_y, to_numpy_2d, to_numpy_y
from ...node_base import Node, NodeMetadata, NodeParameter, NodePolicy, NodeResult, PortMetadata, register_node
from ...presentation_contract import NodePresentationContract, ScientificPresentation
from ..modeling import pls_core
from . import _vip, cars_node, mcuve_node, spa_node

logger = logging.getLogger(__name__)

_SELECTION_METHODS = frozenset({"vip", "coef_abs", "cars", "mcuve", "spa", "none"})
_SELECTOR_PROFILE_VERSION = "spectra-nested-selector-profile/1"
_CARS_ITERATIONS = 30
_CARS_CV_FOLDS_MAX = 3
_MCUVE_RESAMPLES = 30
_MCUVE_CALIBRATION_FRACTION = 0.8
_MCUVE_MAX_VARIABLES = 20
_SPA_MAX_VARIABLES = 20
_SPA_CV_FOLDS_MAX = 3


def _canonical_nested_cv_parameters(parameters: dict[str, object]) -> dict[str, object]:
    """Return the exact, bounded local nested-CV parameter representation."""

    group_source = parameters.get("group_source", "explicit_or_rows")
    if group_source not in {"explicit_or_rows", "attached"}:
        raise ValueError("nested CV group_source must be explicit_or_rows or attached")
    max_selector_fits = parameters.get("max_selector_fits", 500)
    if isinstance(max_selector_fits, bool) or not isinstance(max_selector_fits, int) or max_selector_fits < 1:
        raise ValueError("max_selector_fits must be a positive integer")
    n_repeats = parameters.get("n_repeats", 1)
    if isinstance(n_repeats, bool) or not isinstance(n_repeats, int) or not 1 <= n_repeats <= 20:
        raise ValueError("nested CV n_repeats must be an integer between 1 and 20")
    method = parameters["selection_method"]
    n_components = parameters["n_components"]
    cv_folds = parameters["cv_folds"]
    vip_threshold = parameters["vip_threshold"]
    coef_threshold = parameters["coef_threshold"]
    random_seed = parameters["random_seed"]
    if not isinstance(method, str) or method not in _SELECTION_METHODS:
        raise ValueError("nested CV selection method is not admitted")
    for name, value in (
        ("n_components", n_components),
        ("cv_folds", cv_folds),
        ("random_seed", random_seed),
    ):
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError(f"nested CV {name} must be an integer")
    for name, value in (("vip_threshold", vip_threshold), ("coef_threshold", coef_threshold)):
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"nested CV {name} must be a finite number")
        if not np.isfinite(value):
            raise ValueError(f"nested CV {name} must be a finite number")
    if not 1 <= n_components <= 50:
        raise ValueError("nested CV n_components must be between 1 and 50")
    if not 2 <= cv_folds <= 20:
        raise ValueError("nested CV cv_folds must be between 2 and 20")
    if not 0 <= random_seed <= 4_294_967_295:
        raise ValueError("nested CV random_seed must be an unsigned 32-bit integer")
    if float(vip_threshold) < 0.1:
        raise ValueError("nested CV vip_threshold must be at least 0.1")
    if float(coef_threshold) < 0.0:
        raise ValueError("nested CV coef_threshold must be non-negative")
    return {
        "selection_method": method,
        "n_repeats": n_repeats,
        "group_source": group_source,
        "max_selector_fits": max_selector_fits,
        "n_components": n_components,
        "cv_folds": cv_folds,
        "vip_threshold": float(vip_threshold),
        "coef_threshold": float(coef_threshold),
        "random_seed": random_seed,
    }


def _derive_seed(root_seed: int, *, purpose: str, fold_index: int) -> int:
    """Derive one deterministic uint32 seed without overflow arithmetic."""

    encoded = f"spectra-nested-cv-seed/1:{root_seed}:{purpose}:{fold_index}".encode("ascii")
    return int.from_bytes(hashlib.sha256(encoded).digest()[:4], "big", signed=False)


def _selector_profile(method: str) -> dict[str, object]:
    if method == "cars":
        fixed: dict[str, object] = {"n_iterations": _CARS_ITERATIONS, "cv_folds_max": _CARS_CV_FOLDS_MAX}
    elif method == "mcuve":
        fixed = {
            "n_resamples": _MCUVE_RESAMPLES,
            "calibration_fraction": _MCUVE_CALIBRATION_FRACTION,
            "max_selected_variables": _MCUVE_MAX_VARIABLES,
        }
    elif method == "spa":
        fixed = {
            "max_selected_variables": _SPA_MAX_VARIABLES,
            "cv_folds_max": _SPA_CV_FOLDS_MAX,
            "cv_order": "seeded_random",
        }
    else:
        fixed = {}
    return {"schema_version": _SELECTOR_PROFILE_VERSION, "method": method, "fixed_settings": fixed}


def _select_variables_inner(
    X_train: np.ndarray,
    y_train: np.ndarray,
    method: str,
    n_components: int,
    vip_threshold: float,
    coef_threshold: float,
    random_seed: int,
) -> np.ndarray:
    """Run variable selection on training fold only. Returns boolean mask."""
    n_features = X_train.shape[1]

    if method == "vip":
        pls = pls_core.fit_simpls_exact(
            X_train,
            y_train,
            n_components=min(n_components, X_train.shape[0] - 1, n_features - 1),
            scale=False,
        )
        vip = _vip.calculate_vip(
            pls.x_scores,
            pls.x_weights.T,
            pls.y_loadings.T,
            n_features,
        )
        return vip >= vip_threshold

    elif method == "cars":
        mask, _, _ = cars_node._cars_run(
            X_train,
            y_train,
            n_components,
            cv_folds=min(_CARS_CV_FOLDS_MAX, X_train.shape[0]),
            n_iterations=_CARS_ITERATIONS,
            seed=random_seed,
            fail_on_fit_error=True,
        )
        return mask

    elif method == "mcuve":
        result = mcuve_node._mcuve_dispatch(
            X_train,
            y_train,
            n_components=n_components,
            n_resamples=_MCUVE_RESAMPLES,
            calibration_fraction=_MCUVE_CALIBRATION_FRACTION,
            n_variables=min(_MCUVE_MAX_VARIABLES, n_features),
            random_seed=random_seed,
        )
        return np.asarray(result["feature_mask"], dtype=bool)

    elif method == "spa":
        cv_folds = min(_SPA_CV_FOLDS_MAX, X_train.shape[0])
        smallest_training_fold = min(
            X_train.shape[0] - int(np.sum(np.arange(X_train.shape[0]) % cv_folds == fold)) for fold in range(cv_folds)
        )
        max_variables = min(_SPA_MAX_VARIABLES, n_features, smallest_training_fold - 1)
        result = spa_node._spa_dispatch(
            X_train,
            y_train,
            min_variables=1,
            max_variables=max_variables,
            cv_folds=cv_folds,
            cv_order="seeded_random",
            random_seed=random_seed,
        )
        return np.asarray(result["feature_mask"], dtype=bool)

    elif method == "coef_abs":
        pls = pls_core.fit_simpls_exact(
            X_train,
            y_train,
            n_components=min(n_components, X_train.shape[0] - 1, n_features - 1),
            scale=False,
        )
        coef = np.abs(pls.coefficients.reshape(-1)[:n_features])
        return coef >= coef_threshold

    if method == "none":
        return np.ones(n_features, dtype=bool)
    raise ValueError(f"unsupported nested CV selection method: {method}")


def _choose_pls_components_inner_cv(
    X_train: np.ndarray,
    y_train: np.ndarray,
    *,
    max_components: int,
    random_seed: int,
    inner_folds: int = 3,
    groups: np.ndarray | None = None,
    selection_method: str = "none",
    vip_threshold: float = 1.0,
    coef_threshold: float = 0.0,
) -> int:
    """Choose PLS latent variables by inner CV inside one outer training fold."""
    n_samples, n_features = X_train.shape
    max_valid = max(1, min(int(max_components), n_features, n_samples - 1))
    if max_valid == 1 or n_samples < 4:
        return 1

    n_splits = min(int(inner_folds), n_samples)
    if n_splits < 2:
        return 1

    if groups is None:
        kf = KFold(n_splits=n_splits, shuffle=True, random_state=random_seed)
        inner_partitions = list(kf.split(X_train))
    else:
        n_splits = min(n_splits, len(np.unique(groups)))
        if n_splits < 2:
            raise ValueError("nested group CV requires at least two training groups in every outer fold")
        inner_plan = sdk_validate.make_split_plan(n_samples, n_splits=n_splits, groups=groups)
        inner_partitions = [(fold.train, fold.test) for fold in inner_plan.folds]
    max_consistent = min(
        max_valid,
        min(len(inner_train_idx) - 1 for inner_train_idx, _ in inner_partitions),
    )
    if max_consistent < 1:
        return 1
    best_components: int | None = None
    best_mse = float("inf")

    for n_comp in range(1, max_consistent + 1):
        squared_error = 0.0
        count = 0
        for inner_index, (inner_train_idx, inner_val_idx) in enumerate(inner_partitions):
            # Neither selection nor model fitting may see inner-validation targets.
            mask = _select_variables_inner(
                X_train[inner_train_idx],
                y_train[inner_train_idx],
                selection_method,
                n_comp,
                vip_threshold,
                coef_threshold,
                _derive_seed(random_seed, purpose="inner_selector", fold_index=inner_index),
            )
            if mask.shape != (n_features,) or mask.dtype != np.bool_:
                raise ValueError("inner CV selector produced an invalid selection mask")
            if int(mask.sum()) < n_comp:
                # A candidate must be evaluable in every fold; do not score a
                # favourable subset or silently change its component count.
                count = 0
                break
            pls = pls_core.fit_simpls_exact(
                X_train[inner_train_idx][:, mask],
                y_train[inner_train_idx],
                n_components=n_comp,
                scale=False,
            )
            y_hat = pls.predict(X_train[inner_val_idx][:, mask]).reshape(-1)
            squared_error += float(np.sum((y_train[inner_val_idx] - y_hat) ** 2))
            count += len(inner_val_idx)
        if count != n_samples:
            continue
        mse = squared_error / count
        if mse < best_mse:
            best_mse = mse
            best_components = n_comp
    if best_components is None:
        raise ValueError("no component candidate has sufficient selected features in every inner fold")
    return best_components


def _nested_cv_inputs(X: object, y: object) -> tuple[np.ndarray, np.ndarray]:
    """Bind one finite matrix and one finite quantitative target without guessing."""

    X_ds = bind_X(X, missing_message="Nested CV requires X", allow_array=True)
    y_val = bind_y(y, X=X_ds, required=True, infer_from_X=True, dataset_as_data=False)
    X_array = to_numpy_2d(X_ds, name="X", dtype=np.float64)
    y_array = to_numpy_y(y_val, name="y", expected_samples=X_array.shape[0])
    if y_array.ndim == 2:
        if y_array.shape[1] != 1:
            raise ValueError("nested CV supports exactly one quantitative target")
        y_array = y_array[:, 0]
    if y_array.ndim != 1 or not np.isfinite(y_array).all():
        raise ValueError("nested CV requires one finite quantitative target")
    if X_array.shape[0] < 3 or X_array.shape[1] < 2 or not np.isfinite(X_array).all():
        raise ValueError("nested CV requires at least three finite samples and two finite features")
    return np.array(X_array, copy=True), np.array(y_array, copy=True)


def _regression_cv_metrics(target: np.ndarray, predictions: np.ndarray) -> dict[str, Any]:
    """Compute the one-target registry metrics plus bias-corrected SEP/RER."""

    registry = sdk_validate.metrics(target, predictions)
    if registry.r2 is None or target.size < 2:
        raise ValueError("nested CV cannot score a constant or single-sample target")
    residual = predictions - target
    sep = float(np.sqrt(np.sum((residual - registry.bias) ** 2) / (target.size - 1)))
    if sep == 0.0:
        rer: float | None = None
        rer_status = "undefined_zero_sep"
    else:
        rer = float((np.max(target) - np.min(target)) / sep)
        rer_status = "defined"
    return {
        "statistics": regression_comparison.build_regression_statistics(
            target, predictions, metric_records=[registry.as_dict()]
        ),
        "rmsecv": registry.rmse,
        "r2": registry.r2,
        "bias": registry.bias,
        "sep": sep,
        "rer": rer,
        "rer_status": rer_status,
        "metric_registry_version": registry.registry_version,
    }


def _nested_groups(groups: object, n_samples: int) -> np.ndarray | None:
    if groups is None:
        return None
    values = np.asarray(groups)
    if values.ndim != 1 or len(values) != n_samples:
        raise ValueError("nested CV groups require one identity per row")
    normalized = [
        sdk_validate._normalize_group_identity(v.item() if isinstance(v, np.generic) else v, name="nested CV group")
        for v in values
    ]
    if len({type(value) for value in normalized}) != 1:
        raise ValueError("nested CV group identities must have a consistent scalar type")
    return np.asarray(normalized)


def _bind_nested_groups(X: object, groups: object = None, group_source: str = "explicit_or_rows") -> object:
    from ..data.split_planner import bind_split_groups

    if group_source == "explicit_or_rows":
        return groups
    attached = bind_split_groups(X)
    if attached is None:
        raise ValueError("Attached grouping was selected but no authoritative group binding is present")
    if groups is not None and attached is not None and not np.array_equal(np.asarray(groups), attached):
        raise ValueError("explicit groups contradict the attached specimen group authority")
    return groups if groups is not None else attached


def _nested_cv_dispatch(
    X: np.ndarray,
    y: np.ndarray,
    *,
    producer_node_id: str,
    selection_method: str,
    n_components: int,
    cv_folds: int,
    vip_threshold: float,
    coef_threshold: float,
    random_seed: int,
    groups: object = None,
    n_repeats: int = 1,
    group_source: str = "explicit_or_rows",
    max_selector_fits: int = 500,
    _group_repeat_seed: int | None = None,
) -> tuple[dict[str, object], dict[str, object]]:
    """Run the sole local nested-CV implementation and return outputs plus diagnostics."""

    parameters = _canonical_nested_cv_parameters(
        {
            "selection_method": selection_method,
            "n_repeats": n_repeats,
            "group_source": group_source,
            "max_selector_fits": max_selector_fits,
            "n_components": n_components,
            "cv_folds": cv_folds,
            "vip_threshold": vip_threshold,
            "coef_threshold": coef_threshold,
            "random_seed": random_seed,
        }
    )
    selector_fit_bound = n_repeats * cv_folds * (3 * n_components + 1)
    if selector_fit_bound > max_selector_fits:
        raise ValueError(
            f"Requested nested validation has a conservative bound of {selector_fit_bound} selector calls, "
            f"above the declared max_selector_fits={max_selector_fits}. Reduce folds, components or repeats, "
            "or explicitly raise Selector Fit Budget. The existing node time limit still applies."
        )
    if n_repeats > 1:
        return _repeated_nested_cv(X, y, groups=groups, producer_node_id=producer_node_id, parameters=parameters)
    matrix = np.asarray(X, dtype=np.float64)
    target = np.asarray(y, dtype=np.float64)
    if matrix.ndim != 2 or target.ndim != 1 or matrix.shape[0] != target.shape[0]:
        raise ValueError("nested CV requires a two-dimensional X and matching one-dimensional y")
    if matrix.shape[0] < 3 or matrix.shape[1] < 2 or not np.isfinite(matrix).all() or not np.isfinite(target).all():
        raise ValueError("nested CV requires at least three finite samples and two finite features")
    folds_requested = int(parameters["cv_folds"])
    if folds_requested > matrix.shape[0]:
        raise ValueError("nested CV fold count cannot exceed the number of samples")

    group_values = _nested_groups(groups, matrix.shape[0])
    random_seed_value = int(parameters["random_seed"])
    split_plan = sdk_validate.make_split_plan(
        matrix.shape[0],
        n_splits=folds_requested,
        groups=group_values,
        shuffle=group_values is None,
        random_state=random_seed_value if group_values is None else None,
    )
    if group_values is not None and _group_repeat_seed is not None:
        # Randomize independent units, never their constituent observations.
        identities = np.unique(group_values)
        np.random.default_rng(_group_repeat_seed).shuffle(identities)
        chunks = np.array_split(identities, folds_requested)
        split_plan = sdk_validate.SplitPlan(
            method="group_kfold",
            n_samples=len(target),
            grouped=True,
            folds=tuple(
                sdk_validate.Fold(
                    np.flatnonzero(~np.isin(group_values, held)), np.flatnonzero(np.isin(group_values, held))
                )
                for held in chunks
            ),
        )
        split_plan.validate(group_values)
    if any(fold.train.size < 2 for fold in split_plan.folds):
        raise ValueError("nested CV requires at least two training samples in every outer fold")
    folds = [(np.array(fold.train, copy=True), np.array(fold.test, copy=True)) for fold in split_plan.folds]
    split_digest = split_plan.digest
    predictions = np.full(matrix.shape[0], np.nan, dtype=np.float64)
    fold_assignments = np.full(matrix.shape[0], -1, dtype=np.int64)
    fold_masks: list[np.ndarray] = []
    fold_n_selected: list[int] = []
    fold_n_components: list[int] = []
    fold_requested_components: list[int] = []
    fold_mse: list[float] = []
    fold_sizes: list[int] = []

    for fold_index, (train_index, test_index) in enumerate(folds):
        X_train, X_test = matrix[train_index], matrix[test_index]
        y_train, y_test = target[train_index], target[test_index]
        component_count = _choose_pls_components_inner_cv(
            X_train,
            y_train,
            max_components=min(int(parameters["n_components"]), len(train_index) - 1),
            random_seed=_derive_seed(random_seed_value, purpose="component_tuning", fold_index=fold_index),
            inner_folds=min(3, len(train_index)),
            groups=None if group_values is None else group_values[train_index],
            selection_method=str(parameters["selection_method"]),
            vip_threshold=float(parameters["vip_threshold"]),
            coef_threshold=float(parameters["coef_threshold"]),
        )
        mask = _select_variables_inner(
            X_train,
            y_train,
            str(parameters["selection_method"]),
            component_count,
            vip_threshold=float(parameters["vip_threshold"]),
            coef_threshold=float(parameters["coef_threshold"]),
            random_seed=_derive_seed(random_seed_value, purpose="selector", fold_index=fold_index),
        )
        if mask.shape != (matrix.shape[1],) or mask.dtype != np.bool_:
            raise ValueError(f"nested CV fold {fold_index} produced an invalid selection mask")
        selected_count = int(np.sum(mask))
        if selected_count == 0:
            raise ValueError(
                f"nested CV fold {fold_index} selected no variables; " "adjust the declared selection threshold"
            )
        fold_requested_components.append(component_count)
        # Adapt only using outer-training information; expose the actual refit.
        component_count = min(component_count, selected_count)
        fold_masks.append(np.array(mask, copy=True))
        fold_n_selected.append(selected_count)
        X_train_selected = X_train[:, mask]
        fold_n_components.append(component_count)
        model = pls_core.fit_simpls_exact(
            X_train_selected,
            y_train,
            n_components=component_count,
            scale=False,
        )
        fold_prediction = np.asarray(model.predict(X_test[:, mask]), dtype=np.float64).reshape(-1)
        if fold_prediction.shape != (len(test_index),) or not np.isfinite(fold_prediction).all():
            raise ValueError(f"nested CV fold {fold_index} produced invalid predictions")
        predictions[test_index] = fold_prediction
        fold_assignments[test_index] = fold_index
        fold_mse.append(float(np.mean((y_test - fold_prediction) ** 2)))
        fold_sizes.append(int(len(test_index)))

    if not np.isfinite(predictions).all():
        raise ValueError("nested CV did not produce exactly one finite prediction per sample")
    if np.any(fold_assignments < 0):
        raise ValueError("nested CV did not assign every prediction to exactly one validation fold")
    ss_tot = float(np.sum((target - np.mean(target)) ** 2))
    if ss_tot <= 0.0:
        raise ValueError("nested CV cannot score a constant target")
    scored = _regression_cv_metrics(target, predictions)
    rmsecv = float(scored["rmsecv"])
    r2 = float(scored["r2"])
    bias = float(scored["bias"])
    sep = float(scored["sep"])
    rer = scored["rer"]

    jaccards: list[float] = []
    for left in range(len(fold_masks)):
        for right in range(left + 1, len(fold_masks)):
            intersection = int(np.sum(fold_masks[left] & fold_masks[right]))
            union = int(np.sum(fold_masks[left] | fold_masks[right]))
            jaccards.append(float(intersection / union) if union else 0.0)
    mean_jaccard = float(np.mean(jaccards)) if jaccards else 1.0
    frequency = np.mean(np.stack(fold_masks, axis=0).astype(np.float64), axis=0)

    split_plan_payload = {
        "schema_version": "spectra-split-plan/1",
        "method": split_plan.method,
        "grouped": split_plan.grouped,
        "n_samples": split_plan.n_samples,
        "folds": [{"train": train.astype(int).tolist(), "test": test.astype(int).tolist()} for train, test in folds],
    }
    if group_values is not None:
        split_plan_payload["schema_version"] = "spectra-grouped-split-plan/1"
        split_plan_payload["groups"] = group_values.tolist()
    metrics: dict[str, object] = {
        "statistics": scored["statistics"],
        "metadata": {"type": "RegressionCV"},
        "rmsecv": rmsecv,
        "r2_cv": r2,
        "r2": r2,
        "q2": r2,
        "bias": bias,
        "metric_registry_version": scored["metric_registry_version"],
        "sep": sep,
        "rer": rer,
        "rer_status": scored["rer_status"],
        "n_folds": folds_requested,
        "n_rows": len(target),
        "n_groups": None if group_values is None else len(np.unique(group_values)),
        "population_scope": "row_wise" if group_values is None else "whole_group",
        "selection_method": parameters["selection_method"],
        "selector_profile": _selector_profile(str(parameters["selection_method"])),
        "component_selection": "inner_cv",
        "inner_selection_scope": "inner_training_fold",
        "random_seed": random_seed_value,
        "split_plan_digest": split_digest,
        "split_plan": {
            **split_plan_payload,
            "n_folds": len(split_plan.folds),
            "digest": split_digest,
            "root_seed": random_seed_value,
            "seed_derivation": "spectra-nested-cv-seed/1",
        },
        "per_fold_n_samples": fold_sizes,
        "per_fold_n_selected": fold_n_selected,
        "per_fold_n_components": fold_n_components,
        "per_fold_inner_chosen_components": fold_requested_components,
        "outer_refit_component_policy": "min(inner_choice, outer_training_selected_features)",
        "selector_call_upper_bound": selector_fit_bound,
        "selector_fit_budget": max_selector_fits,
        "per_fold_mse": fold_mse,
        "per_fold_rmse": [float(np.sqrt(value)) for value in fold_mse],
    }
    stability: dict[str, object] = {
        "mean_jaccard": mean_jaccard,
        "per_variable_frequency": frequency.tolist(),
        "mean_n_selected": float(np.mean(fold_n_selected)),
        "std_n_selected": float(np.std(fold_n_selected)),
    }
    diagnostics: dict[str, object] = {
        "metadata": {"type": "RegressionCV"},
        "rmsecv": rmsecv,
        "r2_cv": r2,
        "r2": r2,
        "q2": r2,
        "sep": sep,
        "rer": rer,
        "rer_status": scored["rer_status"],
        "bias": bias,
        "mean_n_selected": stability["mean_n_selected"],
        "selection_stability": mean_jaccard,
        "selection_method": parameters["selection_method"],
        "mean_n_components": float(np.mean(fold_n_components)),
        "component_selection": "inner_cv",
        "inner_selection_scope": "inner_training_fold",
        "random_seed": random_seed_value,
        "split_plan_digest": split_digest,
        "group_boundary": (
            "whole_groups_outer_and_inner" if group_values is not None else "row_wise_no_group_protection"
        ),
    }
    out_of_fold_record = out_of_fold_evidence.build_out_of_fold_evidence(
        producer_node_id=producer_node_id,
        task_type="regression",
        observations=target,
        predictions=predictions,
        split_plan=split_plan_payload,
    )
    return {
        "cv_metrics": metrics,
        "oof_evidence": out_of_fold_record,
        "stability": stability,
    }, diagnostics


def _repeated_nested_cv(X, y, *, groups, producer_node_id, parameters):
    """Keep repeats separate: these are partition sensitivity, not new specimens."""
    repeats = []
    for index in range(parameters["n_repeats"]):
        seed = _derive_seed(parameters["random_seed"], purpose="repeat", fold_index=index)
        outputs, _ = _nested_cv_dispatch(
            X,
            y,
            groups=groups,
            producer_node_id=producer_node_id,
            **{**parameters, "n_repeats": 1, "random_seed": seed},
            _group_repeat_seed=seed,
        )
        repeats.append({"repeat_id": index + 1, "seed": seed, "outputs": outputs})
    distributions = {}
    for name in ("rmsecv", "r2_cv", "bias", "sep"):
        values = np.asarray([item["outputs"]["cv_metrics"][name] for item in repeats], dtype=float)
        distributions[name] = {
            "per_repeat": values.tolist(),
            "mean": float(values.mean()),
            "std_across_repeats": float(values.std(ddof=1)),
            "minimum": float(values.min()),
            "maximum": float(values.max()),
        }
    record = {
        "schema_version": "spectrasherpa.repeated-nested-validation/1",
        "n_repeats": len(repeats),
        "n_rows": len(y),
        "n_groups": repeats[0]["outputs"]["cv_metrics"]["n_groups"],
        "root_seed": parameters["random_seed"],
        "seed_derivation": "spectra-nested-cv-seed/1",
        "parameters": parameters,
        "scope": "sensitivity_to_partitions_of_this_dataset",
        "interpretation": "Repeat spread is not a confidence interval or external validation. "
        "Repeated predictions are not independent observations.",
        "distributions": distributions,
        "selection_stability_per_repeat": [item["outputs"]["stability"] for item in repeats],
    }
    record["metadata"] = {"repeated_validation": dict(record)}
    return {"cv_metrics": record, "repeated_evidence": {**record, "repeats": repeats}}, record


@register_node
class NestedCVNode(Node):
    """Leakage-safe Nested CV — variable selection inside each fold.

    For each outer CV fold:
    1. Select variables on training data only (VIP, CARS, MC-UVE, SPA, or |coef|)
    2. Tune the latent-variable count by inner CV
    3. Fit PLS on selected training variables
    4. Predict held-out samples with selected variables only

    Reports leakage-safe random-fold RMSECV, R², Q² and per-fold selection
    stability. It does not claim to protect grouped, temporal, or batch
    dependence; those designs require a separate split contract.
    """

    metadata = NodeMetadata(
        node_type="selection.nested_cv",
        category="selection",
        label="Evaluate Nested CV Selection",
        description=(
            "Fits variable selection and latent-variable choice inside each shuffled outer fold. "
            "Recorded or explicit specimen groups are kept separate in outer and inner folds. "
            "Without groups this is row-wise validation, not a grouped or temporal design."
        ),
        parameters=[
            NodeParameter(
                name="group_source",
                label="Grouping Choice",
                param_type="select",
                default="explicit_or_rows",
                options=[
                    {"label": "Row-wise unless Groups input is connected", "value": "explicit_or_rows"},
                    {"label": "Use attached specimen groups", "value": "attached"},
                ],
                description=(
                    "Existing workflows remain row-wise. Attached groups require explicit selection; "
                    "insufficient groups never silently fall back."
                ),
            ),
            NodeParameter(
                name="max_selector_fits",
                label="Selector Fit Budget",
                param_type="number",
                default=500,
                min_value=1,
                step=1,
                description=(
                    "Conservative bound: repeats × outer folds × (3 × maximum components + 1). "
                    "Each CARS/MCUVE call fits many models. Raising this budget does not raise "
                    "the 120-second node limit."
                ),
            ),
            NodeParameter(
                name="n_repeats",
                label="Validation Repeats",
                param_type="number",
                default=1,
                min_value=1,
                max_value=20,
                step=1,
                max_value_reason="Repeated nested fitting multiplies selector and model work.",
                description="Separate seeded repeats; spread measures partition sensitivity, not new specimens.",
            ),
            NodeParameter(
                name="selection_method",
                label="Selection Method",
                param_type="select",
                options=[
                    {"label": "VIP", "value": "vip"},
                    {"label": "|Coefficient|", "value": "coef_abs"},
                    {"label": "CARS", "value": "cars"},
                    {"label": "MC-UVE", "value": "mcuve"},
                    {"label": "SPA", "value": "spa"},
                    {"label": "None (full spectrum)", "value": "none"},
                ],
                default="vip",
                description="Variable selection method applied inside each fold",
            ),
            NodeParameter(
                name="n_components",
                label="Max PLS Components",
                param_type="number",
                default=5,
                min_value=1,
                max_value=50,
                max_value_reason="Bounds the inner PLS search inside the declared local resource envelope.",
                step=1,
                description="Maximum latent variables considered by the inner CV loop",
            ),
            NodeParameter(
                name="cv_folds",
                label="Outer CV Folds",
                param_type="number",
                default=5,
                min_value=2,
                max_value=20,
                max_value_reason="Bounds repeated outer and inner fitting inside the declared local resource envelope.",
                step=1,
                description="Number of outer cross-validation folds",
            ),
            NodeParameter(
                name="vip_threshold",
                label="VIP Threshold",
                param_type="number",
                default=1.0,
                min_value=0.1,
                step=0.1,
                description="VIP threshold (for VIP method)",
                category="advanced",
                visible_when={"selection_method": ["vip"]},
            ),
            NodeParameter(
                name="coef_threshold",
                label="Coefficient Threshold",
                param_type="number",
                default=0.01,
                min_value=0.0,
                step=0.001,
                description="Absolute PLS coefficient threshold (for |Coefficient| method)",
                category="advanced",
                visible_when={"selection_method": ["coef_abs"]},
            ),
            NodeParameter(
                name="random_seed",
                label="Random Seed",
                param_type="number",
                default=42,
                min_value=0,
                max_value=4_294_967_295,
                max_value_reason="Exact unsigned 32-bit root seed; per-fold seeds use overflow-safe hash derivation.",
                step=1,
                description="Exact seed for outer folds, inner folds, and stochastic selectors.",
                category="advanced",
            ),
        ],
        input_ports=[
            PortMetadata(
                name="groups",
                type_ref="spectrasherpa://types/Array1D/1.0",
                required=False,
                label="Independent Specimen Groups",
                description=(
                    "One specimen or batch ID per row; used explicitly when connected; "
                    "attached binding requires Grouping Choice."
                ),
            ),
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
                description="Exactly one finite quantitative target; may be supplied by the dataset target binding.",
            ),
        ],
        output_ports=[
            PortMetadata(
                name="repeated_evidence",
                type_ref="spectrasherpa://types/ValidationResult/1.0",
                required=False,
                label="Repeated Validation Evidence",
                description="Separate repeat identities, fold evidence and partition-sensitivity distributions.",
            ),
            PortMetadata(
                name="cv_metrics",
                type_ref="spectrasherpa://types/ValidationResult/1.0",
                required=True,
                label="CV Metrics",
            ),
            PortMetadata(
                name="oof_evidence",
                type_ref=out_of_fold_evidence.OUT_OF_FOLD_EVIDENCE_TYPE,
                required=False,
                label="Out-of-Fold Evidence",
                description=(
                    "Observations, predictions, fold assignments, exact split plan, and canonical producer "
                    "identity bound into one closed record"
                ),
            ),
            PortMetadata(
                name="stability",
                type_ref="spectrasherpa://types/ValidationResult/1.0",
                required=False,
                label="Selection Stability",
            ),
        ],
        input_types=["Array2D", "TargetMatrix"],
        output_type="dict",
        diagnostics=["rmsecv", "r2_cv", "q2", "mean_n_selected", "selection_stability"],
        policy=NodePolicy(),
        canonical_parameter_validator=_canonical_nested_cv_parameters,
        presentation_contract=NodePresentationContract(
            default_presentation="metrics",
            presentations=(
                ScientificPresentation("metrics", "Validation Metrics", "metric_record", ("cv_metrics",), ("record",)),
                ScientificPresentation(
                    "oof",
                    "Single-repeat Predictions",
                    "out_of_fold_evidence",
                    ("oof_evidence",),
                    ("plot", "table", "record"),
                ),
                ScientificPresentation(
                    "repeats", "Separate Repeat Evidence", "metric_record", ("repeated_evidence",), ("record",)
                ),
                ScientificPresentation(
                    "stability", "Selection Stability", "metric_record", ("stability",), ("record",)
                ),
            ),
        ),
    )

    def generate_python(
        self,
        inputs: Mapping[str, str],
        indent: str = "    ",
        use_scp: bool = True,
    ) -> list[str]:
        """Export the same registered implementation used by the live DAG."""

        del use_scp
        X_expression = inputs.get("X", inputs.get("default", "input_data"))
        y_expression = inputs.get("y", "None")
        groups_expression = inputs.get("groups", "None")
        parameters = self._resolve_params()
        return [
            f"{indent}# --- Canonical nested CV selection ({self.node_id}) ---",
            (
                f"{indent}from spectra_sherpa.app.services.dag.nodes.selection.nested_cv_node "
                "import _nested_cv_dispatch, _nested_cv_inputs, _bind_nested_groups"
            ),
            f"{indent}_nested_X, _nested_y = _nested_cv_inputs({X_expression}, {y_expression})",
            f"{indent}_nested_outputs, _nested_diagnostics = _nested_cv_dispatch(",
            f"{indent}    _nested_X, _nested_y, producer_node_id={self.node_id!r}, "
            f"groups=_bind_nested_groups({X_expression}, {groups_expression}, {parameters['group_source']!r}), "
            f"**{parameters!r}",
            f"{indent})",
            f"{indent}results[{self.node_id!r}] = _nested_outputs",
        ]

    async def execute(self, X: Any = None, y: Any = None, groups: Any = None, **kwargs: Any) -> NodeResult:
        del kwargs
        matrix, target = _nested_cv_inputs(X, y)
        outputs, diagnostics = _nested_cv_dispatch(
            matrix,
            target,
            producer_node_id=self.node_id,
            groups=_bind_nested_groups(X, groups, self._resolve_params()["group_source"]),
            **self._resolve_params(),
        )
        logger.info("Nested CV completed for %s", self.node_id)
        return NodeResult(outputs=outputs, diagnostics=diagnostics)


bind_stable_execution_contract(
    NestedCVNode,
    runtime_family=RuntimeFamily.SHERPA_NATIVE,
    lifecycle_kind=LifecycleKind.EVALUATOR,
    implementation_id="spectrasherpa.selection.nested_cv",
    implementation_version="2.5.0",
    required_worker_capabilities=(WorkerCapability.READ_DATASET,),
    managed_optimization_eligibility=(ManagedOptimizationEligibility.LOCAL,),
    sample_effect="preserves_samples",
    # This evaluator reports fold-local selection stability and predictions;
    # it does not emit a filtered feature matrix or a replacement axis.
    feature_effect="preserves_features",
    axis_effect="preserves_axis",
    unit_effect="preserves_units",
    resource_hints={"timeout_seconds": 120, "cpu_seconds": 120, "memory_bytes": 1_073_741_824},
    license_id="Apache-2.0",
    help_reference="docs/nodes/selection-validation.md",
    implementation_modules=(
        out_of_fold_evidence,
        _vip,
        cars_node,
        mcuve_node,
        pls_core,
        sdk_validate,
        spa_node,
        regression_comparison,
    ),
    implementation_distributions=("numpy", "scikit-learn"),
    runtime_requirements=(("numpy", "1.26.4"), ("scikit-learn", "1.9.0")),
    citations=(
        "Filzmoser et al., Journal of Chemometrics 23 (2009) 160-171",
        pls_core.CITATION,
    ),
    deterministic=False,
    seed_parameter="random_seed",
    target_access="required",
    group_access="optional",
)


__all__ = [
    "NestedCVNode",
    "_canonical_nested_cv_parameters",
    "_nested_cv_dispatch",
    "_nested_cv_inputs",
]
