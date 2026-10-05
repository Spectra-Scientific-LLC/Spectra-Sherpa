"""Reference-faithful SPA-MLR variable selection.

Registered as ``selection.spa``.

The Successive Projections Algorithm first mean-centers the calibration
columns and constructs low-collinearity variable chains from every
non-constant starting variable. It then selects a chain prefix by the held-out
prediction error of Multiple Linear Regression on one shared cross-validation
partition. This is the original 2001 SPA-MLR variant; the later F-test
elimination extension is a distinct scientific method and is not silently
folded into this operation.

Reference: Araújo et al., Chemometrics and Intelligent Laboratory Systems 57
(2001) 65-73, doi:10.1016/S0169-7439(01)00119-8.
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

logger = logging.getLogger(__name__)

_STATE_SERIALIZER = "spectrasherpa.selection.spa_mlr.state/3"
_MAX_MODEL_FIT_BUDGET = 250_000


def _gram_zero_tolerance(gram: np.ndarray, *, observation_count: int) -> float:
    """Return the scale-relative rank tolerance for one centered Gram matrix."""

    scale = float(np.max(np.abs(np.diag(gram))))
    return max(
        np.finfo(np.float64).eps * max(observation_count, gram.shape[0]) * scale,
        float(np.nextafter(np.float64(0.0), np.float64(1.0))),
    )


def _canonical_spa_parameters(parameters: Mapping[str, Any]) -> dict[str, int | str]:
    """Return the exact closed parameter representation for SPA-MLR."""

    allowed = {"min_variables", "max_variables", "cv_folds", "cv_order", "random_seed"}
    unknown = sorted(set(parameters) - allowed)
    if unknown:
        raise ValueError(f"selection.spa accepts only: {', '.join(sorted(allowed))}")
    resolved: dict[str, Any] = {
        "min_variables": parameters.get("min_variables", 1),
        "max_variables": parameters.get("max_variables", 20),
        "cv_folds": parameters.get("cv_folds", 5),
        "cv_order": parameters.get("cv_order", "sorted_target"),
        "random_seed": parameters.get("random_seed", 42),
    }
    for name in ("min_variables", "max_variables", "cv_folds", "random_seed"):
        if isinstance(resolved[name], bool) or not isinstance(resolved[name], int):
            raise ValueError(f"SPA {name} must be an integer")
    if not 1 <= resolved["min_variables"] <= 30:
        raise ValueError("SPA min_variables must be between 1 and 30")
    if not resolved["min_variables"] <= resolved["max_variables"] <= 30:
        raise ValueError("SPA max_variables must be between min_variables and 30")
    if not 2 <= resolved["cv_folds"] <= 20:
        raise ValueError("SPA cv_folds must be between 2 and 20")
    if resolved["cv_order"] not in {"sorted_target", "seeded_random", "input_order"}:
        raise ValueError("SPA cv_order must be sorted_target, seeded_random, or input_order")
    if not 0 <= resolved["random_seed"] <= 4_294_967_295:
        raise ValueError("SPA random_seed must be an unsigned 32-bit integer")
    return {
        "min_variables": resolved["min_variables"],
        "max_variables": resolved["max_variables"],
        "cv_folds": resolved["cv_folds"],
        "cv_order": resolved["cv_order"],
        "random_seed": resolved["random_seed"],
    }


def _spa_inputs(X: Any, y: Any) -> tuple[Any, np.ndarray, np.ndarray]:
    dataset = bind_X(X, missing_message="SPA-MLR requires X", allow_array=True)
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
            raise ValueError("SPA-MLR requires exactly one quantitative target")
        target = target[:, 0]
    target = np.asarray(target, dtype=np.float64).reshape(-1)
    if not np.isfinite(matrix).all() or not np.isfinite(target).all():
        raise ValueError("SPA-MLR inputs must be finite")
    if matrix.shape[0] < 4 or matrix.shape[1] < 2:
        raise ValueError("SPA-MLR requires at least four samples and two features")
    if float(np.ptp(target)) == 0.0:
        raise ValueError("SPA-MLR requires a quantitative target with non-zero variation")
    return dataset, matrix, target


def _spa_fold_assignments(
    target: np.ndarray,
    *,
    cv_folds: int,
    cv_order: str,
    random_seed: int,
) -> np.ndarray:
    n_samples = target.shape[0]
    if cv_folds > n_samples:
        raise ValueError("SPA cv_folds may not exceed the sample count")
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
        if validation_count < 1 or n_samples - validation_count < 3:
            raise ValueError("SPA cross-validation leaves insufficient calibration or validation support")
    return assignments


def _split_digest(assignments: np.ndarray) -> str:
    return hashlib.sha256(np.asarray(assignments, dtype="<i8").tobytes(order="C")).hexdigest()


def _projection_chain_from_gram(
    gram: np.ndarray,
    *,
    start_variable: int,
    max_variables: int,
    zero_norm_tolerance: float | None = None,
) -> tuple[int, ...]:
    """Construct one standard SPA projection chain using Gram identities.

    This is algebraically equivalent to repeatedly projecting every remaining
    input feature vector onto the orthogonal complement of the most
    recently selected residual vector.  The Gram representation avoids
    copying the sample-by-feature matrix for every starting wavelength.
    """

    n_features = gram.shape[0]
    if zero_norm_tolerance is None:
        zero_norm_tolerance = _gram_zero_tolerance(gram, observation_count=n_features)
    residual_norms = np.diag(gram).astype(np.float64, copy=True)
    factors = np.zeros((max_variables, n_features), dtype=np.float64)
    selected = [start_variable]
    selected_mask = np.zeros(n_features, dtype=bool)
    selected_mask[start_variable] = True
    for step in range(max_variables - 1):
        current = selected[-1]
        covariance = gram[current].astype(np.float64, copy=True)
        if step:
            covariance -= factors[:step, current] @ factors[:step]
        current_norm = float(residual_norms[current])
        if current_norm <= zero_norm_tolerance:
            break
        factor = covariance / np.sqrt(current_norm)
        factors[step] = factor
        residual_norms = np.maximum(residual_norms - np.square(factor), 0.0)
        residual_norms[selected_mask] = -np.inf
        next_variable = int(np.argmax(residual_norms))
        if not np.isfinite(residual_norms[next_variable]) or residual_norms[next_variable] <= zero_norm_tolerance:
            break
        selected.append(next_variable)
        selected_mask[next_variable] = True
    return tuple(selected)


def _spa_projection_chains(matrix: np.ndarray, *, max_variables: int) -> tuple[tuple[int, ...], ...]:
    """Construct exhaustive SPA chains from every non-constant variable."""

    # Mean-centering the calibration columns is part of the original SPA
    # projection geometry. It affects only variable selection: the fitted
    # transform still returns the corresponding original input columns.
    centered = matrix - np.mean(matrix, axis=0, keepdims=True)
    gram = centered.T @ centered
    diagonal = np.diag(gram)
    tolerance = _gram_zero_tolerance(gram, observation_count=centered.shape[0])
    starts = np.flatnonzero(diagonal > tolerance)
    if starts.size < 2:
        raise ValueError("SPA-MLR requires at least two non-constant features")
    return tuple(
        _projection_chain_from_gram(
            gram,
            start_variable=int(start),
            max_variables=max_variables,
            zero_norm_tolerance=tolerance,
        )
        for start in starts
    )


def _mlr_rmsecv(
    matrix: np.ndarray,
    target: np.ndarray,
    indices: tuple[int, ...],
    assignments: np.ndarray,
) -> float | None:
    """Return pooled held-out MLR RMSECV, or None for a rank-deficient subset."""

    predictions = np.empty(target.shape[0], dtype=np.float64)
    for fold in range(int(assignments.max()) + 1):
        train = assignments != fold
        validate = ~train
        design_train = np.column_stack((np.ones(int(np.sum(train))), matrix[train][:, indices]))
        if np.linalg.matrix_rank(design_train) != design_train.shape[1]:
            return None
        coefficients, _residuals, rank, _singular = np.linalg.lstsq(design_train, target[train], rcond=None)
        if rank != design_train.shape[1] or not np.isfinite(coefficients).all():
            return None
        design_validate = np.column_stack((np.ones(int(np.sum(validate))), matrix[validate][:, indices]))
        fold_predictions = design_validate @ coefficients
        if not np.isfinite(fold_predictions).all():
            return None
        predictions[validate] = fold_predictions
    score = float(np.sqrt(np.mean(np.square(target - predictions))))
    return score if np.isfinite(score) else None


def _spa_dispatch(
    matrix: np.ndarray,
    target: np.ndarray,
    *,
    min_variables: int,
    max_variables: int,
    cv_folds: int,
    cv_order: str,
    random_seed: int,
) -> dict[str, object]:
    """Execute exhaustive projection-chain SPA with shared-fold MLR scoring."""

    n_samples, n_features = matrix.shape
    assignments = _spa_fold_assignments(
        target,
        cv_folds=cv_folds,
        cv_order=cv_order,
        random_seed=random_seed,
    )
    smallest_training_fold = min(int(np.sum(assignments != fold)) for fold in range(cv_folds))
    supported_maximum = min(max_variables, n_features, smallest_training_fold - 1)
    if min_variables > supported_maximum:
        raise ValueError("SPA variable bounds exceed cross-validated MLR support")
    chains = _spa_projection_chains(matrix, max_variables=supported_maximum)
    fit_budget = sum(max(0, len(chain) - min_variables + 1) for chain in chains) * cv_folds
    if fit_budget > _MAX_MODEL_FIT_BUDGET:
        raise ValueError(
            f"SPA requested model-fit budget {fit_budget} exceeds {_MAX_MODEL_FIT_BUDGET}; "
            "reduce max_variables or cross-validation folds"
        )

    score_rows: list[list[float | None]] = []
    candidates: list[tuple[float, int, int, tuple[int, ...]]] = []
    for chain in chains:
        row: list[float | None] = []
        for size in range(min_variables, len(chain) + 1):
            subset = chain[:size]
            score = _mlr_rmsecv(matrix, target, subset, assignments)
            row.append(score)
            if score is not None:
                candidates.append((score, size, chain[0], subset))
        score_rows.append(row)
    if not candidates:
        raise ValueError("SPA-MLR found no full-rank cross-validated candidate subset")
    best_rmsecv, best_size, best_start, selected = min(candidates, key=lambda item: (item[0], item[1], item[2]))
    mask = np.zeros(n_features, dtype=bool)
    mask[list(selected)] = True
    scores = np.zeros(n_features, dtype=np.float64)
    for rank, index in enumerate(selected):
        scores[index] = 1.0 - rank / len(selected)
    return {
        "feature_count": n_features,
        "reference_samples": n_samples,
        "feature_mask": mask.tolist(),
        "importance_scores": scores.tolist(),
        "projection_chains": [list(chain) for chain in chains],
        "candidate_rmsecv": score_rows,
        "best_start": best_start,
        "best_size": best_size,
        "best_rmsecv": best_rmsecv,
        "selected_indices": list(selected),
        "fold_assignments": assignments.tolist(),
        "split_digest": _split_digest(assignments),
        "model_fit_budget": fit_budget,
        "projection_preprocessing": "mean_center_columns",
    }


def _feature_axis_identity(dataset: Any, *, features: int) -> tuple[str | None, str | None, str | None, str | None]:
    return _canonical_feature_axis_identity(dataset, features=features, context="SPA")


def _validate_spa_state(state: Mapping[str, object]) -> dict[str, object]:
    required = {
        "serializer",
        "feature_count",
        "reference_samples",
        "feature_axis_values_sha256",
        "feature_axis_labels_sha256",
        "feature_axis_units",
        "feature_axis_quantity",
        "feature_mask",
        "importance_scores",
        "min_variables",
        "max_variables",
        "cv_folds",
        "cv_order",
        "random_seed",
        "projection_chains",
        "candidate_rmsecv",
        "best_start",
        "best_size",
        "best_rmsecv",
        "selected_indices",
        "fold_assignments",
        "split_digest",
        "model_fit_budget",
        "projection_preprocessing",
        "selection_scope",
    }
    if not isinstance(state, Mapping) or set(state) != required or state.get("serializer") != _STATE_SERIALIZER:
        raise ValueError("fitted SPA state does not use the closed serializer schema")
    parameters = _canonical_spa_parameters(
        {name: state[name] for name in ("min_variables", "max_variables", "cv_folds", "cv_order", "random_seed")}
    )
    feature_count = state["feature_count"]
    reference_samples = state["reference_samples"]
    if isinstance(feature_count, bool) or not isinstance(feature_count, int) or feature_count < 2:
        raise ValueError("fitted SPA state has invalid feature_count")
    if isinstance(reference_samples, bool) or not isinstance(reference_samples, int) or reference_samples < 4:
        raise ValueError("fitted SPA state has invalid reference_samples")
    chains = state["projection_chains"]
    score_rows = state["candidate_rmsecv"]
    if not isinstance(chains, list) or not chains or not isinstance(score_rows, list) or len(score_rows) != len(chains):
        raise ValueError("fitted SPA state has invalid projection-chain evidence")
    validated_chains: list[list[int]] = []
    validated_scores: list[list[float | None]] = []
    candidates: list[tuple[float, int, int, list[int]]] = []
    min_variables = int(parameters["min_variables"])
    for chain, row in zip(chains, score_rows, strict=True):
        if (
            not isinstance(chain, list)
            or len(chain) < min_variables
            or len(chain) > int(parameters["max_variables"])
            or any(
                isinstance(item, bool) or not isinstance(item, int) or not 0 <= item < feature_count for item in chain
            )
            or len(set(chain)) != len(chain)
            or not isinstance(row, list)
            or len(row) != len(chain) - min_variables + 1
        ):
            raise ValueError("fitted SPA state has an invalid projection chain")
        copied_row: list[float | None] = []
        for offset, score in enumerate(row):
            if score is None:
                copied_row.append(None)
                continue
            if isinstance(score, bool) or not isinstance(score, (int, float)) or not np.isfinite(score) or score < 0:
                raise ValueError("fitted SPA state has an invalid RMSECV trace")
            value = float(score)
            size = min_variables + offset
            candidates.append((value, size, chain[0], chain[:size]))
            copied_row.append(value)
        validated_chains.append(list(chain))
        validated_scores.append(copied_row)
    starts = [chain[0] for chain in validated_chains]
    if starts != sorted(starts) or len(starts) != len(set(starts)):
        raise ValueError("fitted SPA state does not contain one ordered chain per starting variable")
    if not candidates:
        raise ValueError("fitted SPA state has no valid candidate")
    expected = min(candidates, key=lambda item: (item[0], item[1], item[2]))
    best_rmsecv, best_size, best_start, selected = expected
    if (
        isinstance(state["best_start"], bool)
        or not isinstance(state["best_start"], int)
        or isinstance(state["best_size"], bool)
        or not isinstance(state["best_size"], int)
        or isinstance(state["best_rmsecv"], bool)
        or not isinstance(state["best_rmsecv"], (int, float))
        or not np.isfinite(state["best_rmsecv"])
        or state["best_start"] != best_start
        or state["best_size"] != best_size
        or float(state["best_rmsecv"]) != best_rmsecv
        or state["selected_indices"] != selected
    ):
        raise ValueError("fitted SPA state does not bind the declared winning subset")
    mask = state["feature_mask"]
    expected_mask = [index in set(selected) for index in range(feature_count)]
    if not isinstance(mask, list) or mask != expected_mask or any(not isinstance(item, bool) for item in mask):
        raise ValueError("fitted SPA feature_mask does not match the winning subset")
    scores = state["importance_scores"]
    expected_scores = [0.0] * feature_count
    for rank, index in enumerate(selected):
        expected_scores[index] = 1.0 - rank / len(selected)
    if (
        not isinstance(scores, list)
        or len(scores) != feature_count
        or any(isinstance(item, bool) or not isinstance(item, (int, float)) or not np.isfinite(item) for item in scores)
        or not np.array_equal(np.asarray(scores, dtype=np.float64), np.asarray(expected_scores, dtype=np.float64))
    ):
        raise ValueError("fitted SPA importance_scores do not match the winning projection order")
    assignments = state["fold_assignments"]
    cv_folds = int(parameters["cv_folds"])
    if (
        not isinstance(assignments, list)
        or len(assignments) != reference_samples
        or any(isinstance(item, bool) or not isinstance(item, int) or not 0 <= item < cv_folds for item in assignments)
        or set(assignments) != set(range(cv_folds))
    ):
        raise ValueError("fitted SPA fold assignments are invalid")
    if state["split_digest"] != _split_digest(np.asarray(assignments, dtype=np.int64)):
        raise ValueError("fitted SPA split digest does not bind its fold assignments")
    expected_budget = sum(len(row) for row in validated_scores) * cv_folds
    if state["model_fit_budget"] != expected_budget or expected_budget > _MAX_MODEL_FIT_BUDGET:
        raise ValueError("fitted SPA model-fit budget is invalid")
    if state["selection_scope"] != "full_calibration_fit_not_performance_evidence":
        raise ValueError("fitted SPA state has invalid selection_scope")
    if state["projection_preprocessing"] != "mean_center_columns":
        raise ValueError("fitted SPA state has invalid projection preprocessing")
    for name in ("feature_axis_values_sha256", "feature_axis_labels_sha256"):
        digest = state[name]
        if digest is not None and (
            not isinstance(digest, str)
            or len(digest) != 64
            or any(character not in "0123456789abcdef" for character in digest)
        ):
            raise ValueError(f"fitted SPA state has invalid {name}")
    if state["feature_axis_units"] is not None and not isinstance(state["feature_axis_units"], str):
        raise ValueError("fitted SPA state has invalid feature_axis_units")
    validated_axis_quantity(state["feature_axis_quantity"], context="fitted SPA")
    return {
        **dict(state),
        "projection_chains": validated_chains,
        "candidate_rmsecv": validated_scores,
        "feature_mask": list(mask),
        "importance_scores": [float(item) for item in scores],
        "selected_indices": list(selected),
        "fold_assignments": list(assignments),
    }


def _spa_execute(
    X: Any,
    y: Any,
    *,
    node_id: str,
    parameters: Mapping[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    node = SPANode(node_id, dict(parameters))
    state = node.fit_fitted_state(X, y)
    selected = node.apply_fitted_state(X, state)
    mask = np.asarray(state["feature_mask"], dtype=bool)
    scores = np.asarray(state["importance_scores"], dtype=np.float64)
    diagnostics = {
        name: state[name]
        for name in (
            "min_variables",
            "max_variables",
            "cv_folds",
            "cv_order",
            "random_seed",
            "best_start",
            "best_size",
            "best_rmsecv",
            "selected_indices",
            "fold_assignments",
            "split_digest",
            "model_fit_budget",
            "projection_preprocessing",
            "selection_scope",
        )
    }
    diagnostics["n_selected"] = int(mask.sum())
    diagnostics["n_total"] = int(state["feature_count"])
    diagnostics["candidate_chain_count"] = len(state["projection_chains"])
    return {"default": selected, "X_selected": selected, "mask": mask, "scores": scores}, diagnostics


@register_node
class SPANode(Node):
    """Successive Projections Algorithm with MLR cross-validation."""

    metadata = NodeMetadata(
        node_type="selection.spa",
        category="selection",
        label="SPA-MLR Variable Selection (Araújo 2001)",
        description=(
            "Mean-centers calibration columns, builds the original Araújo 2001 low-collinearity variable chains "
            "from every non-constant starting feature, and selects one chain prefix by shared-fold MLR RMSECV. "
            "This calibration-set selection is not predictive-performance evidence; use nested CV for "
            "leakage-safe evaluation."
        ),
        parameters=[
            NodeParameter(
                name="min_variables",
                label="Minimum Variables",
                param_type="number",
                default=1,
                min_value=1,
                max_value=30,
                max_value_reason="Matches the bounded exhaustive projection and MLR search envelope.",
                step=1,
                description="Smallest projection-chain prefix evaluated by MLR cross-validation",
            ),
            NodeParameter(
                name="max_variables",
                label="Maximum Variables",
                param_type="number",
                default=20,
                min_value=1,
                max_value=30,
                max_value_reason="Bounds exhaustive projection-chain construction and MLR evaluation.",
                step=1,
                description="Largest projection-chain prefix evaluated by MLR cross-validation",
            ),
            NodeParameter(
                name="cv_folds",
                label="CV Folds",
                param_type="number",
                default=5,
                min_value=2,
                max_value=20,
                max_value_reason="Bounds repeated MLR fitting for every candidate chain prefix.",
                step=1,
                description="Venetian-blinds folds shared by every candidate subset",
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
                label="Projection Order Scores",
            ),
        ],
        input_types=["SherpaDataset"],
        output_type="dict",
        diagnostics=["best_rmsecv", "best_size", "best_start", "n_selected"],
        policy=NodePolicy(),
        canonical_parameter_validator=_canonical_spa_parameters,
    )

    def fit_fitted_state(self, input_data: Any, target: Any = None) -> dict[str, object]:
        dataset, matrix, target_array = _spa_inputs(input_data, target)
        resolved = self._resolve_params()
        result = _spa_dispatch(matrix, target_array, **resolved)
        axis_digest, labels_digest, axis_units, axis_quantity = _feature_axis_identity(
            dataset, features=matrix.shape[1]
        )
        return _validate_spa_state(
            {
                "serializer": _STATE_SERIALIZER,
                "feature_axis_values_sha256": axis_digest,
                "feature_axis_labels_sha256": labels_digest,
                "feature_axis_units": axis_units,
                "feature_axis_quantity": axis_quantity,
                "selection_scope": "full_calibration_fit_not_performance_evidence",
                **resolved,
                **result,
            }
        )

    def apply_fitted_state(self, input_data: Any, state: Mapping[str, object]) -> Any:
        validated = _validate_spa_state(state)
        dataset = bind_X(input_data, missing_message="SPA-MLR requires X", allow_array=True)
        matrix = to_numpy_2d(dataset, name="X", dtype=np.float64)
        if not np.isfinite(matrix).all() or matrix.shape[1] != validated["feature_count"]:
            raise ValueError("SPA apply input does not match the fitted feature count")
        axis_digest, labels_digest, axis_units, axis_quantity = _feature_axis_identity(
            dataset, features=matrix.shape[1]
        )
        if (
            axis_digest != validated["feature_axis_values_sha256"]
            or labels_digest != validated["feature_axis_labels_sha256"]
            or axis_units != validated["feature_axis_units"]
            or axis_quantity != validated["feature_axis_quantity"]
        ):
            raise ValueError("SPA apply input does not match the fitted feature axis")
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
                selection_method="spa_mlr",
                selection_scores=scores[mask],
            )
        selected.meta["feature_mask"] = mask.tolist()
        add_processing_step(
            selected,
            "selection.spa",
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
            f"{indent}# --- Canonical SPA-MLR selection ({self.node_id}) ---",
            f"{indent}from spectra_sherpa.app.services.dag.nodes.selection.spa_node import _spa_execute",
            f"{indent}_spa_outputs, _spa_diagnostics = _spa_execute(",
            f"{indent}    {X_expression}, {y_expression},",
            f"{indent}    node_id={self.node_id!r}, parameters={parameters!r},",
            f"{indent})",
            f"{indent}results[{self.node_id!r}] = _spa_outputs",
        ]

    async def execute(self, X: Any = None, y: Any = None, **kwargs: Any) -> NodeResult:
        del kwargs
        outputs, diagnostics = _spa_execute(
            X,
            y,
            node_id=self.node_id,
            parameters=self._resolve_params(),
        )
        logger.info(
            "SPA-MLR: %s/%s variables selected from start %s; RMSECV %.4f",
            diagnostics["n_selected"],
            diagnostics["n_total"],
            diagnostics["best_start"],
            diagnostics["best_rmsecv"],
        )
        return NodeResult(outputs=outputs, diagnostics=diagnostics)


bind_stable_execution_contract(
    SPANode,
    runtime_family=RuntimeFamily.SHERPA_NATIVE,
    lifecycle_kind=LifecycleKind.FITTED_TRANSFORM,
    implementation_id="spectrasherpa.selection.spa_mlr",
    implementation_version="1.1.0",
    required_worker_capabilities=(WorkerCapability.READ_DATASET,),
    managed_optimization_eligibility=(ManagedOptimizationEligibility.LOCAL,),
    sample_effect="preserves_samples",
    feature_effect="filters_features",
    axis_effect="changes_axis",
    unit_effect="preserves_units",
    resource_hints={"timeout_seconds": 300, "cpu_seconds": 300, "memory_bytes": 1_073_741_824},
    license_id="Apache-2.0",
    help_reference="docs/nodes/selection-validation.md",
    implementation_distributions=("numpy",),
    runtime_requirements=(("numpy", "1.26.4"),),
    citations=(
        "Araújo et al., Chemometrics and Intelligent Laboratory Systems 57 (2001) 65-73, "
        "doi:10.1016/S0169-7439(01)00119-8",
    ),
    fitted_state_serializer=_STATE_SERIALIZER,
    deterministic=False,
    seed_parameter="random_seed",
    target_access=TargetAccess.FIT_ONLY,
    group_access="none",
)


__all__ = [
    "SPANode",
    "_canonical_spa_parameters",
    "_mlr_rmsecv",
    "_projection_chain_from_gram",
    "_spa_dispatch",
    "_spa_execute",
    "_spa_fold_assignments",
    "_spa_projection_chains",
    "_validate_spa_state",
]
