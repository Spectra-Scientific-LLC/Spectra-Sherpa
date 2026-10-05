"""Reference-faithful stability-frequency variable selection.

Registered as ``selection.stability``.

The node repeatedly draws seeded half-samples without replacement, applies a
declared PLS variable-scoring rule, and retains variables whose empirical
selection probability reaches the declared threshold.  This is the core
stability-selection construction of Meinshausen and Buehlmann.  The node does
not claim their formal false-discovery bound: the bundled chemometric base
selectors do not establish every assumption required by that theorem.

Reference: Meinshausen & Buehlmann, Journal of the Royal Statistical Society
Series B 72 (2010) 417-473, doi:10.1111/j.1467-9868.2010.00740.x.
The bundled PLS importance rules follow the mdatools variable-selection
reference implementation documentation.
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
from . import _selectivity_ratio
from ._vip import calculate_vip

logger = logging.getLogger(__name__)

_STATE_SERIALIZER = "spectrasherpa.selection.stability.state/4"
_MAX_MODEL_FIT_BUDGET = 500
_BASE_METHODS = {"vip", "coef_abs", "selectivity_ratio"}
_SELECTION_SCOPE = "full_calibration_selection_frequency_not_predictive_or_error_control_evidence"


def _canonical_stability_parameters(parameters: Mapping[str, Any]) -> dict[str, object]:
    """Return the exact closed parameter representation."""

    allowed = {
        "base_method",
        "base_threshold",
        "selection_probability_threshold",
        "n_resamples",
        "n_components",
        "random_seed",
    }
    unknown = sorted(set(parameters) - allowed)
    if unknown:
        raise ValueError(f"selection.stability accepts only: {', '.join(sorted(allowed))}")
    resolved: dict[str, Any] = {
        "base_method": parameters.get("base_method", "vip"),
        "base_threshold": parameters.get("base_threshold", 1.0),
        "selection_probability_threshold": parameters.get("selection_probability_threshold", 0.6),
        "n_resamples": parameters.get("n_resamples", 100),
        "n_components": parameters.get("n_components", 5),
        "random_seed": parameters.get("random_seed", 42),
    }
    if resolved["base_method"] not in _BASE_METHODS:
        raise ValueError("Stability base_method must be vip, coef_abs, or selectivity_ratio")
    for name in ("base_threshold", "selection_probability_threshold"):
        value = resolved[name]
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not np.isfinite(value):
            raise ValueError(f"Stability {name} must be finite and numeric")
        resolved[name] = float(value)
    if resolved["base_threshold"] <= 0.0 or resolved["base_threshold"] > 1_000_000.0:
        raise ValueError("Stability base_threshold must be in (0, 1000000]")
    if not 0.5 < resolved["selection_probability_threshold"] <= 1.0:
        raise ValueError("Stability selection_probability_threshold must be in (0.5, 1]")
    for name in ("n_resamples", "n_components", "random_seed"):
        if isinstance(resolved[name], bool) or not isinstance(resolved[name], int):
            raise ValueError(f"Stability {name} must be an integer")
    if not 20 <= resolved["n_resamples"] <= _MAX_MODEL_FIT_BUDGET:
        raise ValueError(f"Stability n_resamples must be between 20 and {_MAX_MODEL_FIT_BUDGET}")
    if not 1 <= resolved["n_components"] <= 50:
        raise ValueError("Stability n_components must be between 1 and 50")
    if not 0 <= resolved["random_seed"] <= 4_294_967_295:
        raise ValueError("Stability random_seed must be an unsigned 32-bit integer")
    return resolved


def _stability_inputs(X: Any, y: Any) -> tuple[Any, np.ndarray, np.ndarray]:
    dataset = bind_X(X, missing_message="Stability selection requires X", allow_array=True)
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
            raise ValueError("Stability selection requires exactly one quantitative target")
        target = target[:, 0]
    target = np.asarray(target, dtype=np.float64).reshape(-1)
    if not np.isfinite(matrix).all() or not np.isfinite(target).all():
        raise ValueError("Stability selection inputs must be finite")
    if matrix.shape[0] < 6 or matrix.shape[1] < 2:
        raise ValueError("Stability selection requires at least six samples and two features")
    if float(np.ptp(target)) == 0.0:
        raise ValueError("Stability selection requires a target with non-zero variation")
    return dataset, matrix, target


def _base_scores(model: pls_core.PLSFit, matrix: np.ndarray, method: str) -> np.ndarray:
    features = matrix.shape[1]
    if method == "vip":
        scores = calculate_vip(model.x_scores, model.x_weights.T, model.y_loadings.T, features)
    elif method == "coef_abs":
        scores = np.abs(np.asarray(model.coefficients, dtype=np.float64).reshape(-1)[:features])
    else:
        coefficients = np.asarray(model.coefficients, dtype=np.float64).reshape(-1)[:features]
        scores = _selectivity_ratio.target_projection_selectivity_ratio(matrix, coefficients)
    scores = np.asarray(scores, dtype=np.float64)
    if scores.shape != (features,) or not np.isfinite(scores).all() or np.any(scores < 0.0):
        raise RuntimeError("Stability selection base selector produced invalid scores")
    return scores


def _index_digest(indices: np.ndarray) -> str:
    return hashlib.sha256(np.asarray(indices, dtype="<i8").tobytes(order="C")).hexdigest()


def _stability_dispatch(
    matrix: np.ndarray,
    target: np.ndarray,
    *,
    base_method: str,
    base_threshold: float,
    selection_probability_threshold: float,
    n_resamples: int,
    n_components: int,
    random_seed: int,
) -> dict[str, object]:
    """Run seeded half-sample stability selection."""

    samples, features = matrix.shape
    half_sample_size = samples // 2
    supported_components = min(half_sample_size - 1, features)
    if n_components > supported_components:
        raise ValueError(
            f"Stability selection requested {n_components} PLS components but each half-sample supports at most "
            f"{supported_components}"
        )
    components = n_components
    rng = np.random.default_rng(random_seed)
    half_samples = np.empty((n_resamples, half_sample_size), dtype=np.int64)
    selection_counts = np.zeros(features, dtype=np.int64)
    score_sum = np.zeros(features, dtype=np.float64)
    for ordinal in range(n_resamples):
        indices = rng.choice(samples, size=half_sample_size, replace=False)
        half_samples[ordinal] = indices
        try:
            model = pls_core.fit_simpls_exact(
                matrix[indices],
                target[indices],
                n_components=components,
                scale=False,
            )
        except Exception as exc:
            raise RuntimeError(f"Stability-selection PLS fit failed at half-sample {ordinal}") from exc
        scores = _base_scores(model, matrix[indices], base_method)
        selection_counts += scores >= base_threshold
        score_sum += scores
    frequencies = selection_counts.astype(np.float64) / n_resamples
    mask = frequencies >= selection_probability_threshold
    if not np.any(mask):
        raise ValueError("Stability selection retained no variables; lower the base or selection-probability threshold")
    return {
        "feature_count": features,
        "reference_samples": samples,
        "feature_mask": mask.tolist(),
        "selection_counts": selection_counts.tolist(),
        "selection_frequencies": frequencies.tolist(),
        "mean_base_scores": (score_sum / n_resamples).tolist(),
        "half_sample_indices": half_samples.tolist(),
        "half_sample_digest": _index_digest(half_samples),
        "half_sample_size": half_sample_size,
        "effective_components": components,
        "model_fit_count": n_resamples,
        "selection_scope": _SELECTION_SCOPE,
        "formal_error_control_claimed": False,
    }


def _feature_axis_identity(dataset: Any, *, features: int) -> tuple[str | None, str | None, str | None, str | None]:
    return _canonical_feature_axis_identity(dataset, features=features, context="Stability-selection")


def _finite_vector(value: object, *, name: str, length: int, nonnegative: bool = True) -> np.ndarray:
    if not isinstance(value, list) or len(value) != length:
        raise ValueError(f"fitted stability state has invalid {name}")
    array = np.asarray(value, dtype=np.float64)
    if array.shape != (length,) or not np.isfinite(array).all() or (nonnegative and np.any(array < 0.0)):
        raise ValueError(f"fitted stability state has invalid {name}")
    return array


def _validate_stability_state(state: Mapping[str, object]) -> dict[str, object]:
    required = {
        "serializer",
        "feature_count",
        "reference_samples",
        "feature_axis_values_sha256",
        "feature_axis_labels_sha256",
        "feature_axis_units",
        "feature_axis_quantity",
        "feature_mask",
        "selection_counts",
        "selection_frequencies",
        "mean_base_scores",
        "half_sample_indices",
        "half_sample_digest",
        "half_sample_size",
        "effective_components",
        "model_fit_count",
        "selection_scope",
        "formal_error_control_claimed",
        "base_method",
        "base_threshold",
        "selection_probability_threshold",
        "n_resamples",
        "n_components",
        "random_seed",
    }
    if not isinstance(state, Mapping) or set(state) != required or state.get("serializer") != _STATE_SERIALIZER:
        raise ValueError("fitted stability state does not use the closed serializer schema")
    parameters = _canonical_stability_parameters(
        {
            name: state[name]
            for name in (
                "base_method",
                "base_threshold",
                "selection_probability_threshold",
                "n_resamples",
                "n_components",
                "random_seed",
            )
        }
    )
    features, samples = state["feature_count"], state["reference_samples"]
    if isinstance(features, bool) or not isinstance(features, int) or features < 2:
        raise ValueError("fitted stability state has invalid feature_count")
    if isinstance(samples, bool) or not isinstance(samples, int) or samples < 6:
        raise ValueError("fitted stability state has invalid reference_samples")
    counts = state["selection_counts"]
    if (
        not isinstance(counts, list)
        or len(counts) != features
        or any(
            isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= parameters["n_resamples"]
            for value in counts
        )
    ):
        raise ValueError("fitted stability state has invalid selection_counts")
    frequencies = _finite_vector(state["selection_frequencies"], name="selection_frequencies", length=features)
    if np.any(frequencies > 1.0) or not np.array_equal(
        frequencies, np.asarray(counts, dtype=np.float64) / int(parameters["n_resamples"])
    ):
        raise ValueError("fitted stability frequencies do not match selection counts")
    _finite_vector(state["mean_base_scores"], name="mean_base_scores", length=features)
    mask = state["feature_mask"]
    expected_mask = (frequencies >= float(parameters["selection_probability_threshold"])).tolist()
    if not isinstance(mask, list) or mask != expected_mask or not any(mask):
        raise ValueError("fitted stability mask does not match its probability threshold")
    half_size = state["half_sample_size"]
    indices = state["half_sample_indices"]
    if half_size != samples // 2 or not isinstance(indices, list) or len(indices) != parameters["n_resamples"]:
        raise ValueError("fitted stability state has invalid half-sample population")
    index_array = np.asarray(indices)
    if index_array.shape != (parameters["n_resamples"], half_size) or index_array.dtype.kind not in "iu":
        raise ValueError("fitted stability state has invalid half-sample indices")
    if (
        np.any(index_array < 0)
        or np.any(index_array >= samples)
        or any(np.unique(row).size != half_size for row in index_array)
    ):
        raise ValueError("fitted stability half-samples must be unique in-range samples")
    if state["half_sample_digest"] != _index_digest(index_array):
        raise ValueError("fitted stability half-sample digest does not match its indices")
    supported_components = min(half_size - 1, features)
    if int(parameters["n_components"]) > supported_components:
        raise ValueError("fitted stability state requests an unsupported PLS component count")
    if (
        state["effective_components"] != parameters["n_components"]
        or state["model_fit_count"] != parameters["n_resamples"]
    ):
        raise ValueError("fitted stability state does not match its model-fit budget")
    if state["selection_scope"] != _SELECTION_SCOPE or state["formal_error_control_claimed"] is not False:
        raise ValueError("fitted stability state overstates its scientific scope")
    for name in ("feature_axis_values_sha256", "feature_axis_labels_sha256"):
        value = state[name]
        if value is not None and (not isinstance(value, str) or len(value) != 64):
            raise ValueError(f"fitted stability state has invalid {name}")
    if state["feature_axis_units"] is not None and not isinstance(state["feature_axis_units"], str):
        raise ValueError("fitted stability state has invalid feature_axis_units")
    validated_axis_quantity(state["feature_axis_quantity"], context="fitted stability")
    return dict(state)


def _apply_stability_state(dataset: Any, state: Mapping[str, object], *, node_id: str) -> dict[str, Any]:
    validated = _validate_stability_state(state)
    matrix = to_numpy_2d(dataset, name="X", dtype=np.float64)
    if not np.isfinite(matrix).all() or matrix.shape[1] != validated["feature_count"]:
        raise ValueError("Stability apply input does not match the fitted feature count")
    identity = _feature_axis_identity(dataset, features=matrix.shape[1])
    if identity != (
        validated["feature_axis_values_sha256"],
        validated["feature_axis_labels_sha256"],
        validated["feature_axis_units"],
        validated["feature_axis_quantity"],
    ):
        raise ValueError("Stability apply input does not match the fitted feature axis")
    mask = np.asarray(validated["feature_mask"], dtype=bool)
    scores = np.asarray(validated["selection_frequencies"], dtype=np.float64)
    selected = build_dataset_like(matrix[:, mask], dataset)
    axis = getattr(dataset, "feature_axis", None)
    if axis is not None and (axis.values is not None or axis.labels is not None):
        selected.feature_axis = type(axis)(
            values=None if axis.values is None else np.asarray(axis.values)[mask],
            labels=None if axis.labels is None else [v for v, keep in zip(axis.labels, mask, strict=True) if keep],
            units=axis.units,
            display_units=axis.display_units,
            quantity=axis.quantity,
            title=axis.title,
            include_mask=np.ones(int(mask.sum()), dtype=bool),
            selection_method="stability",
            selection_scores=scores[mask],
        )
    selected.meta["feature_mask"] = mask.tolist()
    add_processing_step(
        selected,
        "selection.stability",
        {
            "state_serializer": _STATE_SERIALIZER,
            "transform_state": dict(validated),
            "n_selected": int(mask.sum()),
        },
        node_id,
    )
    diagnostics = {
        "n_selected": int(mask.sum()),
        "n_total": int(mask.size),
        "n_resamples": validated["n_resamples"],
        "half_sample_size": validated["half_sample_size"],
        "base_method": validated["base_method"],
        "selection_scope": validated["selection_scope"],
        "formal_error_control_claimed": False,
    }
    return {"default": selected, "X_selected": selected, "mask": mask, "scores": scores, "diagnostics": diagnostics}


def _stability_execute(
    X: Any, y: Any, *, node_id: str, parameters: Mapping[str, Any]
) -> tuple[dict[str, Any], dict[str, Any]]:
    node = StabilitySelectionNode(node_id, dict(parameters))
    state = node.fit_fitted_state(X, y)
    dataset = bind_X(X, missing_message="Stability selection requires X", allow_array=True)
    result = _apply_stability_state(dataset, state, node_id=node_id)
    diagnostics = result.pop("diagnostics")
    return result, diagnostics


@register_node
class StabilitySelectionNode(Node):
    """Half-sample stability-frequency variable selection."""

    metadata = NodeMetadata(
        node_type="selection.stability",
        category="selection",
        label="Stability Selection",
        description=(
            "Retains variables repeatedly selected by a declared PLS scoring rule across seeded half-samples. "
            "Reports empirical stability, not a false-discovery guarantee or predictive performance."
        ),
        parameters=[
            NodeParameter(
                name="base_method",
                label="Base Selector",
                param_type="select",
                options=[
                    {"label": "VIP", "value": "vip"},
                    {"label": "|Coefficient|", "value": "coef_abs"},
                    {"label": "Selectivity Ratio", "value": "selectivity_ratio"},
                ],
                default="vip",
                description="PLS variable score thresholded in every half-sample",
            ),
            NodeParameter(
                name="base_threshold",
                label="Base Threshold",
                param_type="number",
                default=1.0,
                min_value=0.000001,
                max_value=1_000_000.0,
                max_value_reason="Bounds the closed base-selector decision envelope.",
                step=0.1,
            ),
            NodeParameter(
                name="selection_probability_threshold",
                label="Selection Probability Threshold",
                param_type="number",
                default=0.6,
                min_value=0.500001,
                max_value=1.0,
                max_value_reason="A probability may not exceed one.",
                step=0.05,
                description="Minimum empirical half-sample selection frequency",
            ),
            NodeParameter(
                name="n_resamples",
                label="Half-sample Resamples",
                param_type="number",
                default=100,
                min_value=20,
                max_value=_MAX_MODEL_FIT_BUDGET,
                max_value_reason="Hard cap on PLS fits per node execution.",
                step=10,
            ),
            NodeParameter(
                name="n_components",
                label="PLS Components",
                param_type="number",
                default=5,
                min_value=1,
                max_value=50,
                max_value_reason="Bounds latent-variable fitting and half-sample support.",
                step=1,
            ),
            NodeParameter(
                name="random_seed",
                label="Random Seed",
                param_type="number",
                default=42,
                min_value=0,
                max_value=4_294_967_295,
                max_value_reason="Exact unsigned 32-bit sampling seed.",
                step=1,
                category="advanced",
            ),
        ],
        input_ports=[
            PortMetadata(
                name="X",
                type_ref="spectrasherpa://types/Array2D/1.0",
                required=True,
                label="Input Data Matrix",
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
                name="mask", type_ref="spectrasherpa://types/Array1D/1.0", required=True, label="Feature Mask"
            ),
            PortMetadata(
                name="scores",
                type_ref="spectrasherpa://types/Array1D/1.0",
                required=False,
                label="Selection Frequencies",
            ),
        ],
        input_types=["SherpaDataset"],
        output_type="dict",
        diagnostics=["n_selected", "n_resamples", "half_sample_size", "base_method", "selection_scope"],
        policy=NodePolicy(),
        canonical_parameter_validator=_canonical_stability_parameters,
    )

    def fit_fitted_state(self, input_data: Any, target: Any = None) -> dict[str, object]:
        dataset, matrix, target_array = _stability_inputs(input_data, target)
        parameters = self._resolve_params()
        result = _stability_dispatch(matrix, target_array, **parameters)
        values_digest, labels_digest, units, quantity = _feature_axis_identity(dataset, features=matrix.shape[1])
        return _validate_stability_state(
            {
                "serializer": _STATE_SERIALIZER,
                "feature_axis_values_sha256": values_digest,
                "feature_axis_labels_sha256": labels_digest,
                "feature_axis_units": units,
                "feature_axis_quantity": quantity,
                **result,
                **parameters,
            }
        )

    def apply_fitted_state(self, input_data: Any, state: Mapping[str, object]) -> Any:
        dataset = bind_X(input_data, missing_message="Stability selection requires X", allow_array=True)
        return _apply_stability_state(dataset, state, node_id=self.node_id)["X_selected"]

    def generate_python(self, inputs: Mapping[str, str], indent: str = "    ", use_scp: bool = True) -> list[str]:
        del use_scp
        X_expression = inputs.get("X", inputs.get("default", "input_data"))
        y_expression = inputs.get("y", "None")
        return [
            f"{indent}# --- Canonical stability-frequency selection ({self.node_id}) ---",
            f"{indent}from spectra_sherpa.app.services.dag.nodes.selection.stability_node import _stability_execute",
            f"{indent}_stability_outputs, _stability_diagnostics = _stability_execute(",
            f"{indent}    {X_expression}, {y_expression},",
            f"{indent}    node_id={self.node_id!r}, parameters={self._resolve_params()!r},",
            f"{indent})",
            f"{indent}results[{self.node_id!r}] = _stability_outputs",
        ]

    async def execute(self, X: Any = None, y: Any = None, **kwargs: Any) -> NodeResult:
        del kwargs
        outputs, diagnostics = _stability_execute(X, y, node_id=self.node_id, parameters=self._resolve_params())
        logger.info(
            "Stability selection retained %s/%s variables across %s half-samples",
            diagnostics["n_selected"],
            diagnostics["n_total"],
            diagnostics["n_resamples"],
        )
        return NodeResult(outputs=outputs, diagnostics=diagnostics)


bind_stable_execution_contract(
    StabilitySelectionNode,
    runtime_family=RuntimeFamily.SHERPA_NATIVE,
    lifecycle_kind=LifecycleKind.FITTED_TRANSFORM,
    implementation_id="spectrasherpa.selection.stability",
    implementation_version="1.2.0",
    required_worker_capabilities=(WorkerCapability.READ_DATASET,),
    managed_optimization_eligibility=(ManagedOptimizationEligibility.LOCAL,),
    sample_effect="preserves_samples",
    feature_effect="filters_features",
    axis_effect="changes_axis",
    unit_effect="preserves_units",
    resource_hints={"timeout_seconds": 120, "cpu_seconds": 120, "memory_bytes": 1_073_741_824},
    license_id="Apache-2.0",
    help_reference="docs/nodes/selection-validation.md",
    implementation_distributions=("numpy",),
    implementation_modules=(_selectivity_ratio, pls_core),
    runtime_requirements=(("numpy", "1.26.4"),),
    citations=(
        "Meinshausen & Buehlmann, JRSS-B 72 (2010) 417-473, doi:10.1111/j.1467-9868.2010.00740.x",
        "mdatools PLS variable-selection reference, https://mda.tools/docs/pls--variable-selection.html",
        "Kvalheim, Journal of Chemometrics 24 (2010) 496-504, doi:10.1002/cem.1289",
        pls_core.CITATION,
    ),
    fitted_state_serializer=_STATE_SERIALIZER,
    deterministic=False,
    seed_parameter="random_seed",
    target_access=TargetAccess.FIT_ONLY,
    group_access="none",
)


__all__ = [
    "StabilitySelectionNode",
    "_canonical_stability_parameters",
    "_stability_dispatch",
    "_stability_execute",
    "_stability_inputs",
    "_validate_stability_state",
]
