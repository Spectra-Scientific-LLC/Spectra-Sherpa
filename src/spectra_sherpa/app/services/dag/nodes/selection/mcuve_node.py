"""Reference-faithful Monte Carlo uninformative-variable elimination.

Registered as ``selection.mcuve``.

MC-UVE fits a population of PLS models to seeded Monte Carlo calibration
subsets, ranks measured variables by the stability of their regression
coefficients, and retains a declared number of the most stable variables. It
does not add artificial noise variables: that cutoff construction belongs to
the original UVE method and is not silently combined with MC-UVE here.

References:

* Centner et al., Analytical Chemistry 68 (1996) 3851-3858,
  doi:10.1021/ac960321m (original UVE foundation).
* Cai, Li & Shao, Chemometrics and Intelligent Laboratory Systems 90 (2008)
  188-194, doi:10.1016/j.chemolab.2007.10.001 (MC-UVE modification).
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

_STATE_SERIALIZER = "spectrasherpa.selection.mcuve.state/4"
_MAX_MODEL_FIT_BUDGET = 500
_STABILITY_DEFINITION = "abs(mean_pls_coefficient/sample_standard_deviation)"


def _coefficient_sd_floor(coefficient_mean: np.ndarray, coefficient_sd: np.ndarray) -> float:
    """Return a unit-equivariant numerical floor for coefficient dispersion."""

    coefficient_scale = max(
        float(np.max(np.abs(coefficient_mean))),
        float(np.max(coefficient_sd)),
    )
    return max(
        np.finfo(np.float64).eps * coefficient_scale,
        float(np.nextafter(np.float64(0.0), np.float64(1.0))),
    )


def _canonical_mcuve_parameters(parameters: Mapping[str, Any]) -> dict[str, int | float]:
    """Return the exact closed parameter representation for MC-UVE."""

    allowed = {"n_components", "n_resamples", "calibration_fraction", "n_variables", "random_seed"}
    unknown = sorted(set(parameters) - allowed)
    if unknown:
        raise ValueError(f"selection.mcuve accepts only: {', '.join(sorted(allowed))}")
    resolved: dict[str, Any] = {
        "n_components": parameters.get("n_components", 5),
        "n_resamples": parameters.get("n_resamples", 100),
        "calibration_fraction": parameters.get("calibration_fraction", 0.8),
        "n_variables": parameters.get("n_variables", 20),
        "random_seed": parameters.get("random_seed", 42),
    }
    for name in ("n_components", "n_resamples", "n_variables", "random_seed"):
        if isinstance(resolved[name], bool) or not isinstance(resolved[name], int):
            raise ValueError(f"MC-UVE {name} must be an integer")
    if not 1 <= resolved["n_components"] <= 50:
        raise ValueError("MC-UVE n_components must be between 1 and 50")
    if not 20 <= resolved["n_resamples"] <= _MAX_MODEL_FIT_BUDGET:
        raise ValueError(f"MC-UVE n_resamples must be between 20 and {_MAX_MODEL_FIT_BUDGET}")
    if not 1 <= resolved["n_variables"] <= 500:
        raise ValueError("MC-UVE n_variables must be between 1 and 500")
    if not 0 <= resolved["random_seed"] <= 4_294_967_295:
        raise ValueError("MC-UVE random_seed must be an unsigned 32-bit integer")
    fraction = resolved["calibration_fraction"]
    if isinstance(fraction, bool) or not isinstance(fraction, (int, float)):
        raise ValueError("MC-UVE calibration_fraction must be numeric")
    fraction = float(fraction)
    if not 0.5 <= fraction <= 0.95:
        raise ValueError("MC-UVE calibration_fraction must be between 0.5 and 0.95")
    return {
        "n_components": resolved["n_components"],
        "n_resamples": resolved["n_resamples"],
        "calibration_fraction": fraction,
        "n_variables": resolved["n_variables"],
        "random_seed": resolved["random_seed"],
    }


def _mcuve_inputs(X: Any, y: Any) -> tuple[Any, np.ndarray, np.ndarray]:
    dataset = bind_X(X, missing_message="MC-UVE requires X", allow_array=True)
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
            raise ValueError("MC-UVE requires exactly one quantitative target")
        target = target[:, 0]
    target = np.asarray(target, dtype=np.float64).reshape(-1)
    if not np.isfinite(matrix).all() or not np.isfinite(target).all():
        raise ValueError("MC-UVE inputs must be finite")
    if matrix.shape[0] < 4 or matrix.shape[1] < 2:
        raise ValueError("MC-UVE requires at least four samples and two features")
    if float(np.ptp(target)) == 0.0:
        raise ValueError("MC-UVE requires a quantitative target with non-zero variation")
    return dataset, matrix, target


def _calibration_digest(indices: np.ndarray) -> str:
    return hashlib.sha256(np.asarray(indices, dtype="<i8").tobytes(order="C")).hexdigest()


def _mcuve_dispatch(
    matrix: np.ndarray,
    target: np.ndarray,
    *,
    n_components: int,
    n_resamples: int,
    calibration_fraction: float,
    n_variables: int,
    random_seed: int,
) -> dict[str, object]:
    """Run the Cai-Li-Shao MC-UVE coefficient-stability procedure."""

    n_samples, n_features = matrix.shape
    if n_variables > n_features:
        raise ValueError("MC-UVE n_variables may not exceed the input feature count")
    calibration_size = int(np.floor(n_samples * calibration_fraction))
    if calibration_size < 3:
        raise ValueError("MC-UVE calibration subsets require at least three samples")
    supported_components = min(calibration_size - 1, n_features)
    if n_components > supported_components:
        raise ValueError(
            f"MC-UVE requested {n_components} PLS components but each calibration subset supports at most "
            f"{supported_components}"
        )
    components = n_components

    rng = np.random.default_rng(random_seed)
    calibration_indices = np.empty((n_resamples, calibration_size), dtype=np.int64)
    coefficient_matrix = np.empty((n_resamples, n_features), dtype=np.float64)
    for resample in range(n_resamples):
        selected = rng.choice(n_samples, size=calibration_size, replace=False)
        calibration_indices[resample] = selected
        try:
            model = pls_core.fit_simpls_exact(
                matrix[selected],
                target[selected],
                n_components=components,
                scale=False,
            )
        except Exception as exc:
            raise RuntimeError(f"MC-UVE PLS fit failed at resample {resample}") from exc
        coefficients = np.asarray(model.coefficients, dtype=np.float64).reshape(-1)[:n_features]
        if coefficients.shape != (n_features,) or not np.isfinite(coefficients).all():
            raise RuntimeError(f"MC-UVE produced invalid coefficients at resample {resample}")
        coefficient_matrix[resample] = coefficients

    coefficient_mean = np.mean(coefficient_matrix, axis=0)
    coefficient_sd = np.std(coefficient_matrix, axis=0, ddof=1)
    sd_floor = _coefficient_sd_floor(coefficient_mean, coefficient_sd)
    stability = np.abs(coefficient_mean / np.maximum(coefficient_sd, sd_floor))
    feature_indices = np.arange(n_features, dtype=np.int64)
    ranked = np.lexsort((feature_indices, -stability))
    retained = ranked[:n_variables]
    mask = np.zeros(n_features, dtype=bool)
    mask[retained] = True
    return {
        "feature_count": n_features,
        "reference_samples": n_samples,
        "feature_mask": mask.tolist(),
        "coefficient_mean": coefficient_mean.tolist(),
        "coefficient_sd": coefficient_sd.tolist(),
        "stability_scores": stability.tolist(),
        "ranked_indices": ranked.tolist(),
        "calibration_indices": calibration_indices.tolist(),
        "calibration_digest": _calibration_digest(calibration_indices),
        "calibration_size": calibration_size,
        "effective_components": components,
        "model_fit_count": n_resamples,
        "stability_sd_floor": sd_floor,
        "stability_definition": _STABILITY_DEFINITION,
        "selection_scope": "full_calibration_selection_not_predictive_evidence",
    }


def _feature_axis_identity(dataset: Any, *, features: int) -> tuple[str | None, str | None, str | None, str | None]:
    return _canonical_feature_axis_identity(dataset, features=features, context="MC-UVE")


def _finite_vector(value: object, *, name: str, length: int, nonnegative: bool = False) -> np.ndarray:
    if not isinstance(value, list) or len(value) != length:
        raise ValueError(f"fitted MC-UVE state has invalid {name}")
    array = np.asarray(value, dtype=np.float64)
    if array.shape != (length,) or not np.isfinite(array).all() or (nonnegative and np.any(array < 0)):
        raise ValueError(f"fitted MC-UVE state has invalid {name}")
    return array


def _validate_mcuve_state(state: Mapping[str, object]) -> dict[str, object]:
    required = {
        "serializer",
        "feature_count",
        "reference_samples",
        "feature_axis_values_sha256",
        "feature_axis_labels_sha256",
        "feature_axis_units",
        "feature_axis_quantity",
        "feature_mask",
        "coefficient_mean",
        "coefficient_sd",
        "stability_scores",
        "ranked_indices",
        "calibration_indices",
        "calibration_digest",
        "calibration_size",
        "effective_components",
        "model_fit_count",
        "stability_sd_floor",
        "stability_definition",
        "selection_scope",
        "n_components",
        "n_resamples",
        "calibration_fraction",
        "n_variables",
        "random_seed",
    }
    if not isinstance(state, Mapping) or set(state) != required or state.get("serializer") != _STATE_SERIALIZER:
        raise ValueError("fitted MC-UVE state does not use the closed serializer schema")
    parameters = _canonical_mcuve_parameters(
        {
            name: state[name]
            for name in ("n_components", "n_resamples", "calibration_fraction", "n_variables", "random_seed")
        }
    )
    feature_count = state["feature_count"]
    reference_samples = state["reference_samples"]
    if isinstance(feature_count, bool) or not isinstance(feature_count, int) or feature_count < 2:
        raise ValueError("fitted MC-UVE state has invalid feature_count")
    if isinstance(reference_samples, bool) or not isinstance(reference_samples, int) or reference_samples < 4:
        raise ValueError("fitted MC-UVE state has invalid reference_samples")
    if parameters["n_variables"] > feature_count:
        raise ValueError("fitted MC-UVE state selects more variables than it contains")
    coefficient_mean = _finite_vector(state["coefficient_mean"], name="coefficient_mean", length=feature_count)
    coefficient_sd = _finite_vector(
        state["coefficient_sd"], name="coefficient_sd", length=feature_count, nonnegative=True
    )
    stability = _finite_vector(
        state["stability_scores"], name="stability_scores", length=feature_count, nonnegative=True
    )
    floor = state["stability_sd_floor"]
    if isinstance(floor, bool) or not isinstance(floor, (int, float)) or not np.isfinite(floor) or floor <= 0:
        raise ValueError("fitted MC-UVE state has invalid stability_sd_floor")
    expected_floor = _coefficient_sd_floor(coefficient_mean, coefficient_sd)
    if float(floor) != expected_floor:
        raise ValueError("fitted MC-UVE state has a non-canonical stability_sd_floor")
    expected_stability = np.abs(coefficient_mean / np.maximum(coefficient_sd, expected_floor))
    if not np.array_equal(stability, expected_stability):
        raise ValueError("fitted MC-UVE state stability does not match its coefficient population")
    ranked = state["ranked_indices"]
    expected_ranked = np.lexsort((np.arange(feature_count), -stability)).tolist()
    if ranked != expected_ranked:
        raise ValueError("fitted MC-UVE state ranking does not match its stability scores")
    mask = state["feature_mask"]
    if not isinstance(mask, list) or len(mask) != feature_count or not all(type(item) is bool for item in mask):
        raise ValueError("fitted MC-UVE state has invalid feature_mask")
    expected_mask = np.zeros(feature_count, dtype=bool)
    expected_mask[np.asarray(expected_ranked[: int(parameters["n_variables"])], dtype=np.int64)] = True
    if mask != expected_mask.tolist():
        raise ValueError("fitted MC-UVE state mask does not match its declared ranking")
    calibration_size = state["calibration_size"]
    indices = state["calibration_indices"]
    if (
        isinstance(calibration_size, bool)
        or not isinstance(calibration_size, int)
        or calibration_size < 3
        or not isinstance(indices, list)
        or len(indices) != parameters["n_resamples"]
    ):
        raise ValueError("fitted MC-UVE state has invalid calibration population")
    index_array = np.asarray(indices)
    if index_array.shape != (parameters["n_resamples"], calibration_size) or index_array.dtype.kind not in "iu":
        raise ValueError("fitted MC-UVE state has invalid calibration indices")
    if np.any(index_array < 0) or np.any(index_array >= reference_samples):
        raise ValueError("fitted MC-UVE state calibration index is out of bounds")
    if any(np.unique(row).size != calibration_size for row in index_array):
        raise ValueError("fitted MC-UVE state calibration subsets must sample without replacement")
    if state["calibration_digest"] != _calibration_digest(index_array):
        raise ValueError("fitted MC-UVE state calibration digest does not match its indices")
    expected_size = int(np.floor(reference_samples * float(parameters["calibration_fraction"])))
    if calibration_size != expected_size:
        raise ValueError("fitted MC-UVE state calibration size does not match its fraction")
    effective = state["effective_components"]
    supported_components = min(calibration_size - 1, feature_count)
    if int(parameters["n_components"]) > supported_components:
        raise ValueError("fitted MC-UVE state requests an unsupported PLS component count")
    if effective != parameters["n_components"] or state["model_fit_count"] != parameters["n_resamples"]:
        raise ValueError("fitted MC-UVE state does not match its declared fit budget")
    if state["stability_definition"] != _STABILITY_DEFINITION:
        raise ValueError("fitted MC-UVE state has an unknown stability definition")
    if state["selection_scope"] != "full_calibration_selection_not_predictive_evidence":
        raise ValueError("fitted MC-UVE state overstates its selection scope")
    for name in ("feature_axis_values_sha256", "feature_axis_labels_sha256"):
        value = state[name]
        if value is not None and (not isinstance(value, str) or len(value) != 64):
            raise ValueError(f"fitted MC-UVE state has invalid {name}")
    if state["feature_axis_units"] is not None and not isinstance(state["feature_axis_units"], str):
        raise ValueError("fitted MC-UVE state has invalid feature_axis_units")
    validated_axis_quantity(state["feature_axis_quantity"], context="fitted MC-UVE")
    return dict(state)


def _apply_mcuve_state(dataset: Any, state: Mapping[str, object], *, node_id: str) -> dict[str, Any]:
    validated = _validate_mcuve_state(state)
    matrix = to_numpy_2d(dataset, name="X", dtype=np.float64)
    if not np.isfinite(matrix).all() or matrix.shape[1] != validated["feature_count"]:
        raise ValueError("MC-UVE apply input does not match the fitted feature count")
    axis_digest, labels_digest, axis_units, axis_quantity = _feature_axis_identity(dataset, features=matrix.shape[1])
    if (
        axis_digest != validated["feature_axis_values_sha256"]
        or labels_digest != validated["feature_axis_labels_sha256"]
        or axis_units != validated["feature_axis_units"]
        or axis_quantity != validated["feature_axis_quantity"]
    ):
        raise ValueError("MC-UVE apply input does not match the fitted feature axis")
    mask = np.asarray(validated["feature_mask"], dtype=bool)
    scores = np.asarray(validated["stability_scores"], dtype=np.float64)
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
            selection_method="mcuve",
            selection_scores=scores[mask],
        )
    selected.meta["feature_mask"] = mask.tolist()
    add_processing_step(
        selected,
        "selection.mcuve",
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
        "calibration_size": validated["calibration_size"],
        "selection_scope": validated["selection_scope"],
    }
    return {
        "default": selected,
        "X_selected": selected,
        "mask": mask,
        "scores": scores,
        "diagnostics": diagnostics,
    }


def _mcuve_execute(
    X: Any, y: Any, *, node_id: str, parameters: Mapping[str, Any]
) -> tuple[dict[str, Any], dict[str, Any]]:
    node = MCUVENode(node_id, dict(parameters))
    state = node.fit_fitted_state(X, y)
    dataset = bind_X(X, missing_message="MC-UVE requires X", allow_array=True)
    result = _apply_mcuve_state(dataset, state, node_id=node_id)
    diagnostics = result.pop("diagnostics")
    return result, diagnostics


@register_node
class MCUVENode(Node):
    """Monte Carlo UVE — coefficient-stability variable selection."""

    metadata = NodeMetadata(
        node_type="selection.mcuve",
        category="selection",
        label="MC-UVE",
        description=(
            "Ranks measured variables by PLS coefficient stability across seeded Monte Carlo calibration subsets "
            "and retains the declared top count. This full-calibration selector does not itself establish "
            "predictive performance; use nested CV for leakage-safe evaluation."
        ),
        parameters=[
            NodeParameter(
                name="n_components",
                label="PLS Components",
                param_type="number",
                default=5,
                min_value=1,
                max_value=50,
                max_value_reason="Bounds latent-variable fitting and calibration-subset support.",
                step=1,
            ),
            NodeParameter(
                name="n_resamples",
                label="Monte Carlo Resamples",
                param_type="number",
                default=100,
                min_value=20,
                max_value=_MAX_MODEL_FIT_BUDGET,
                max_value_reason="Hard cap on the number of PLS models fitted by one node execution.",
                step=10,
            ),
            NodeParameter(
                name="calibration_fraction",
                label="Calibration Fraction",
                param_type="number",
                default=0.8,
                min_value=0.5,
                max_value=0.95,
                max_value_reason="Leaves at least five percent outside each Monte Carlo calibration subset.",
                step=0.05,
                category="advanced",
            ),
            NodeParameter(
                name="n_variables",
                label="Variables to Retain",
                param_type="number",
                default=20,
                min_value=1,
                max_value=500,
                max_value_reason="Bounds the canonical retained-variable decision and exported state size.",
                step=1,
            ),
            NodeParameter(
                name="random_seed",
                label="Random Seed",
                param_type="number",
                default=42,
                min_value=0,
                max_value=4_294_967_295,
                max_value_reason="Exact unsigned 32-bit seed used for Monte Carlo calibration subsets.",
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
                label="Coefficient Stability Scores",
            ),
        ],
        input_types=["SherpaDataset"],
        output_type="dict",
        diagnostics=["n_selected", "n_resamples", "calibration_size", "selection_scope"],
        policy=NodePolicy(),
        canonical_parameter_validator=_canonical_mcuve_parameters,
    )

    def fit_fitted_state(self, input_data: Any, target: Any = None) -> dict[str, object]:
        dataset, matrix, target_array = _mcuve_inputs(input_data, target)
        parameters = self._resolve_params()
        result = _mcuve_dispatch(matrix, target_array, **parameters)
        axis_digest, labels_digest, axis_units, axis_quantity = _feature_axis_identity(
            dataset, features=matrix.shape[1]
        )
        state = {
            "serializer": _STATE_SERIALIZER,
            "feature_axis_values_sha256": axis_digest,
            "feature_axis_labels_sha256": labels_digest,
            "feature_axis_units": axis_units,
            "feature_axis_quantity": axis_quantity,
            **result,
            **parameters,
        }
        return _validate_mcuve_state(state)

    def apply_fitted_state(self, input_data: Any, state: Mapping[str, object]) -> Any:
        dataset = bind_X(input_data, missing_message="MC-UVE requires X", allow_array=True)
        return _apply_mcuve_state(dataset, state, node_id=self.node_id)["X_selected"]

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
            f"{indent}# --- Canonical MC-UVE variable selection ({self.node_id}) ---",
            (f"{indent}from spectra_sherpa.app.services.dag.nodes.selection.mcuve_node import _mcuve_execute"),
            f"{indent}_mcuve_outputs, _mcuve_diagnostics = _mcuve_execute(",
            f"{indent}    {X_expression}, {y_expression},",
            f"{indent}    node_id={self.node_id!r}, parameters={parameters!r},",
            f"{indent})",
            f"{indent}results[{self.node_id!r}] = _mcuve_outputs",
        ]

    async def execute(self, X: Any = None, y: Any = None, **kwargs: Any) -> NodeResult:
        del kwargs
        outputs, diagnostics = _mcuve_execute(
            X,
            y,
            node_id=self.node_id,
            parameters=self._resolve_params(),
        )
        logger.info(
            "MC-UVE: %s/%s variables retained across %s Monte Carlo calibration subsets",
            diagnostics["n_selected"],
            diagnostics["n_total"],
            diagnostics["n_resamples"],
        )
        return NodeResult(outputs=outputs, diagnostics=diagnostics)


bind_stable_execution_contract(
    MCUVENode,
    runtime_family=RuntimeFamily.SHERPA_NATIVE,
    lifecycle_kind=LifecycleKind.FITTED_TRANSFORM,
    implementation_id="spectrasherpa.selection.mcuve",
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
    implementation_modules=(pls_core,),
    implementation_distributions=("numpy",),
    runtime_requirements=(("numpy", "1.26.4"),),
    citations=(
        "Centner et al., Analytical Chemistry 68 (1996) 3851-3858, doi:10.1021/ac960321m",
        "Cai, Li & Shao, Chemometrics and Intelligent Laboratory Systems 90 (2008) 188-194, "
        "doi:10.1016/j.chemolab.2007.10.001",
        pls_core.CITATION,
    ),
    fitted_state_serializer=_STATE_SERIALIZER,
    deterministic=False,
    seed_parameter="random_seed",
    target_access=TargetAccess.FIT_ONLY,
    group_access="none",
)


# There is deliberately no ``UVENode`` or ``selection.uve`` compatibility
# alias: the original UVE and the 2008 MC-UVE modification are distinct
# scientific operations.
__all__ = [
    "MCUVENode",
    "_canonical_mcuve_parameters",
    "_mcuve_dispatch",
    "_mcuve_execute",
    "_mcuve_inputs",
    "_validate_mcuve_state",
]
