"""Canonical fitted Orthogonal Signal Correction (OSC).

OSC uses training spectra and training targets to identify dominant spectral
variation that is orthogonal to the target space.  The resulting projection
is serialized once and may then be applied to training, held-out, or future
spectra without target access or refitting.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeAlias

import numpy as np
from numpy.typing import NDArray

from spectra_sherpa.app.lib.sherpa_dataset import EFFECT_SCATTER_CORRECTED, SherpaDataset
from spectra_sherpa.app.services.dag import io_contracts as dag_io_contracts
from spectra_sherpa.app.services.dag import meta_helpers as dag_meta_helpers
from spectra_sherpa.app.services.dag import supervision_binding
from spectra_sherpa.app.services.dag.export_helpers import header_line
from spectra_sherpa.app.services.dag.io_contracts import (
    bind_y,
    build_dataset_like,
    coerce_to_sherpa,
    to_numpy_1d,
    to_numpy_2d,
)
from spectra_sherpa.app.services.dag.meta_helpers import add_processing_step
from spectra_sherpa.app.services.dag.node_base import (
    Node,
    NodeMetadata,
    NodeParameter,
    NodePolicy,
    NodeResult,
    PortMetadata,
    register_node,
)
from spectra_sherpa.app.services.dag.stable_execution_contract import bind_stable_execution_contract
from spectra_sherpa.execution_contract_vocabulary import (
    LifecycleKind,
    ManagedOptimizationEligibility,
    RuntimeFamily,
    WorkerCapability,
)

from . import _shared

FloatArray: TypeAlias = NDArray[np.float64]

_STATE_SERIALIZER = "spectra.osc-fearn-direct-json.v1"
_ALGORITHM = "fearn-direct-orthogonal-signal-correction"
_MAX_COMPONENTS = 10
_MIN_RELATIVE_SINGULAR_VALUE = 1.0e-12
_MIN_RELATIVE_SINGULAR_GAP = 1.0e-10
_TARGET_COVARIANCE_RTOL = 1.0e-10
_AXIS_UNSPECIFIED = object()


def _canonical_osc_parameters(parameters: dict[str, object]) -> dict[str, object]:
    """Return the sole admitted scientist-facing OSC parameter record."""

    component_value = parameters["n_components"]
    if (
        isinstance(component_value, bool)
        or not isinstance(component_value, (int, float))
        or not np.isfinite(component_value)
        or int(component_value) != component_value
    ):
        raise ValueError("OSC n_components must be an exact integer")
    components = int(component_value)
    if components < 1 or components > _MAX_COMPONENTS:
        raise ValueError(f"OSC n_components must be between 1 and {_MAX_COMPONENTS}")
    return {"n_components": components}


def _managed_osc_parameters(parameters: dict[str, object]) -> dict[str, object]:
    """Bound managed OSC removal to a small, reviewable subspace."""

    if int(parameters["n_components"]) > 2:
        raise ValueError("managed OSC n_components must be 1 or 2")
    return parameters


def _finite_matrix(value: object, *, name: str) -> FloatArray:
    matrix = np.asarray(value, dtype=np.float64)
    if matrix.ndim == 1:
        matrix = matrix.reshape(1, -1)
    if matrix.ndim != 2 or matrix.shape[0] == 0 or matrix.shape[1] == 0:
        raise ValueError(f"OSC {name} must be a non-empty two-dimensional matrix")
    if not np.isfinite(matrix).all():
        raise ValueError(f"OSC {name} must contain only finite values")
    return np.array(matrix, dtype=np.float64, copy=True)


def _target_matrix(value: object, *, samples: int) -> FloatArray:
    target = np.asarray(value, dtype=np.float64)
    if target.ndim == 1:
        target = target.reshape(-1, 1)
    if target.ndim != 2 or target.shape[0] != samples or target.shape[1] == 0:
        raise ValueError("OSC target must be a non-empty matrix with one row per training spectrum")
    if not np.isfinite(target).all():
        raise ValueError("OSC target must contain only finite values")
    centered = target - np.mean(target, axis=0, dtype=np.float64)
    if not np.any(np.linalg.norm(centered, axis=0) > 0.0):
        raise ValueError("OSC requires at least one non-constant target")
    return np.array(target, dtype=np.float64, copy=True)


def _axis_record(value: Any, *, features: int) -> tuple[FloatArray | None, str | None]:
    """Extract the exact feature identity bound to a fitted projection."""

    if isinstance(value, SherpaDataset):
        axis = value.get_feature_axis()
    else:
        axis = getattr(value, "feature_axis", None)
        if axis is None:
            axis = getattr(value, "x", None)
    if axis is None:
        return None, None
    raw_values = getattr(axis, "values", None)
    if raw_values is None:
        raw_values = getattr(axis, "data", None)
    if raw_values is None:
        return None, None
    values = np.asarray(raw_values, dtype=np.float64)
    if values.ndim != 1 or values.shape[0] != features or not np.isfinite(values).all():
        raise ValueError("OSC feature axis must be a finite vector matching the feature count")
    units_raw = getattr(axis, "units", None)
    if units_raw is not None and (not isinstance(units_raw, str) or not units_raw.strip()):
        raise ValueError("OSC feature-axis units must be a non-empty string when present")
    return np.array(values, dtype=np.float64, copy=True), units_raw.strip() if units_raw is not None else None


def _canonical_float_vector(value: object, *, name: str, length: int) -> FloatArray:
    if not isinstance(value, list) or len(value) != length:
        raise ValueError(f"fitted OSC state has an invalid {name}")
    if any(type(item) is not float or not np.isfinite(item) for item in value):
        raise ValueError(f"fitted OSC state has an invalid {name}")
    return np.asarray(value, dtype=np.float64)


def _canonical_float_matrix(value: object, *, name: str, rows: int, columns: int) -> FloatArray:
    if not isinstance(value, list) or len(value) != rows:
        raise ValueError(f"fitted OSC state has an invalid {name}")
    decoded = [_canonical_float_vector(row, name=name, length=columns) for row in value]
    return np.vstack(decoded)


def _validated_osc_state(
    state: Mapping[str, object],
) -> tuple[FloatArray, FloatArray, FloatArray, FloatArray]:
    required = {
        "serializer",
        "algorithm",
        "n_components",
        "feature_count",
        "target_count",
        "feature_axis_values",
        "feature_axis_units",
        "x_mean",
        "orthogonal_weights",
        "deflation_loadings",
        "removed_score_singular_values",
        "training_target_covariance_relative_error",
        "training_centered_variance_removed_percent",
    }
    if not isinstance(state, Mapping) or set(state) != required:
        raise ValueError("fitted OSC state does not use the closed serializer schema")
    if state["serializer"] != _STATE_SERIALIZER or state["algorithm"] != _ALGORITHM:
        raise ValueError("fitted OSC state has an unsupported scientific identity")
    components = state["n_components"]
    feature_count = state["feature_count"]
    target_count = state["target_count"]
    if type(components) is not int or components < 1 or components > _MAX_COMPONENTS:
        raise ValueError("fitted OSC state has an invalid component count")
    if type(feature_count) is not int or feature_count < 2 or components > feature_count:
        raise ValueError("fitted OSC state has an invalid feature count")
    if type(target_count) is not int or target_count < 1:
        raise ValueError("fitted OSC state has an invalid target count")
    units = state["feature_axis_units"]
    if units is not None and (not isinstance(units, str) or not units.strip() or units != units.strip()):
        raise ValueError("fitted OSC state has invalid feature-axis units")
    axis_raw = state["feature_axis_values"]
    if axis_raw is None:
        raise ValueError("fitted OSC state requires numeric feature coordinates")
    axis_values = _canonical_float_vector(axis_raw, name="feature axis", length=feature_count)
    x_mean = _canonical_float_vector(state["x_mean"], name="X mean", length=feature_count)
    weights = _canonical_float_matrix(
        state["orthogonal_weights"],
        name="orthogonal weights",
        rows=components,
        columns=feature_count,
    )
    loadings = _canonical_float_matrix(
        state["deflation_loadings"],
        name="deflation loadings",
        rows=components,
        columns=feature_count,
    )
    singular_values = _canonical_float_vector(
        state["removed_score_singular_values"],
        name="removed-score singular values",
        length=components,
    )
    if np.any(singular_values <= 0.0):
        raise ValueError("fitted OSC removed-score singular values must be positive")
    weight_norms = np.linalg.norm(weights, axis=1)
    if not np.allclose(weight_norms, np.ones(components), rtol=1.0e-12, atol=1.0e-12):
        raise ValueError("fitted OSC weights must have unit length")
    if not np.allclose(
        loadings @ weights.T,
        np.eye(components, dtype=np.float64),
        rtol=1.0e-10,
        atol=1.0e-10,
    ):
        raise ValueError("fitted OSC weights and loadings do not define one biorthogonal projection")
    covariance_error = state["training_target_covariance_relative_error"]
    if (
        type(covariance_error) is not float
        or not np.isfinite(covariance_error)
        or covariance_error < 0.0
        or covariance_error > _TARGET_COVARIANCE_RTOL
    ):
        raise ValueError("fitted OSC target-covariance invariant is invalid")
    variance_removed = state["training_centered_variance_removed_percent"]
    if (
        type(variance_removed) is not float
        or not np.isfinite(variance_removed)
        or variance_removed < 0.0
        or variance_removed > 100.0
    ):
        raise ValueError("fitted OSC training variance diagnostic is invalid")
    return (
        np.array(x_mean, copy=True),
        np.array(weights, copy=True),
        np.array(loadings, copy=True),
        axis_values,
    )


def _canonicalize_loading_signs(loadings: FloatArray) -> FloatArray:
    """Choose deterministic signs without changing an OSC projection."""

    result = np.array(loadings, dtype=np.float64, copy=True)
    for index, loading in enumerate(result):
        pivot = int(np.argmax(np.abs(loading)))
        if loading[pivot] < 0.0:
            result[index] *= -1.0
    return result


def _fit_osc_state(
    data: FloatArray,
    target: object,
    *,
    n_components: int,
    feature_axis_values: FloatArray | None,
    feature_axis_units: str | None,
) -> dict[str, object]:
    """Fit the direct OSC projection defined by Fearn (2000).

    In Fearn's notation, ``Z = X M`` projects centered spectra into the
    feature subspace orthogonal to ``X.T @ Y``. The leading right singular
    vectors of ``Z`` are the OSC weights. This implementation forms the same
    projection through an orthonormal basis for ``col(X.T @ Y)`` instead of
    materializing the potentially large square matrix ``M``.
    """

    matrix = _finite_matrix(data, name="fit input")
    if matrix.shape[0] < 3 or matrix.shape[1] < 2:
        raise ValueError("OSC fitting requires at least three spectra and two features")
    projected = _canonical_osc_parameters({"n_components": n_components})
    component_value = projected["n_components"]
    if type(component_value) is not int:  # Defensive: canonicalization already enforces this.
        raise ValueError("OSC n_components must be an exact integer")
    components = component_value
    targets = _target_matrix(target, samples=matrix.shape[0])
    axis_values = None if feature_axis_values is None else np.asarray(feature_axis_values, dtype=np.float64)
    if axis_values is not None and (
        axis_values.ndim != 1 or axis_values.shape[0] != matrix.shape[1] or not np.isfinite(axis_values).all()
    ):
        raise ValueError("OSC fit feature axis does not match the training matrix")
    if axis_values is None:
        raise ValueError("OSC fitting requires an explicit numeric feature axis")
    if feature_axis_units is not None and (
        not isinstance(feature_axis_units, str)
        or not feature_axis_units.strip()
        or feature_axis_units != feature_axis_units.strip()
    ):
        raise ValueError("OSC fit feature-axis units are invalid")

    x_mean = np.mean(matrix, axis=0, dtype=np.float64)
    centered = matrix - x_mean
    centered_singular_values = np.linalg.svd(centered, compute_uv=False)
    if centered_singular_values.size == 0 or not np.isfinite(centered_singular_values).all():
        raise ValueError("OSC could not resolve finite centered spectral variation")
    initial_score_scale = float(centered_singular_values[0])
    if initial_score_scale <= 0.0:
        raise ValueError("OSC fitting requires non-zero centered spectral variation")
    target_centered = targets - np.mean(targets, axis=0, dtype=np.float64)
    initial_target_covariance = target_centered.T @ centered

    cross_covariance = centered.T @ target_centered
    cross_left, cross_singular_values, _ = np.linalg.svd(cross_covariance, full_matrices=False)
    if not np.isfinite(cross_singular_values).all() or not np.isfinite(cross_left).all():
        raise ValueError("OSC could not resolve a finite target-predictive feature subspace")
    possible_covariance_scale = max(
        np.finfo(np.float64).tiny,
        float(np.linalg.norm(target_centered, ord="fro") * np.linalg.norm(centered, ord="fro")),
    )
    cross_rank = int(np.count_nonzero(cross_singular_values > _MIN_RELATIVE_SINGULAR_VALUE * possible_covariance_scale))
    predictive_basis = cross_left[:, :cross_rank]
    candidate = centered - (centered @ predictive_basis) @ predictive_basis.T

    _, candidate_singular_values, candidate_right = np.linalg.svd(candidate, full_matrices=False)
    if not np.isfinite(candidate_singular_values).all() or not np.isfinite(candidate_right).all():
        raise ValueError("OSC could not resolve finite target-orthogonal scores")
    score_rank = int(np.count_nonzero(candidate_singular_values > _MIN_RELATIVE_SINGULAR_VALUE * initial_score_scale))
    if components > score_rank:
        raise ValueError("OSC n_components exceeds the resolved target-orthogonal score rank")
    if components < candidate_singular_values.size and abs(
        float(candidate_singular_values[components - 1]) - float(candidate_singular_values[components])
    ) <= _MIN_RELATIVE_SINGULAR_GAP * float(candidate_singular_values[components - 1]):
        raise ValueError("OSC component boundary is not uniquely resolved")

    weights = _canonicalize_loading_signs(candidate_right[:components])
    scores = centered @ weights.T
    score_gram = scores.T @ scores
    score_gram_singular_values = np.linalg.svd(score_gram, compute_uv=False)
    if score_gram_singular_values.size != components or float(
        score_gram_singular_values[-1]
    ) <= _MIN_RELATIVE_SINGULAR_VALUE * float(score_gram_singular_values[0]):
        raise ValueError("OSC score matrix is rank deficient")
    loadings = (centered.T @ scores @ np.linalg.inv(score_gram)).T
    if not np.allclose(
        loadings @ weights.T,
        np.eye(components, dtype=np.float64),
        rtol=1.0e-10,
        atol=1.0e-10,
    ):
        raise ValueError("OSC fit did not produce one biorthogonal projection")
    corrected_centered = centered - scores @ loadings
    if not np.isfinite(corrected_centered).all():
        raise ValueError("OSC projection produced non-finite values")

    removed_score_singular_values = np.linalg.svd(scores, compute_uv=False)
    final_target_covariance = target_centered.T @ corrected_centered
    # Normalize by a Cauchy bound on possible target covariance.  Using only
    # the observed covariance makes a scientifically valid all-orthogonal
    # dataset appear to have O(1) relative error because both the numerator
    # and denominator then contain only floating-point roundoff.
    covariance_scale = max(
        np.finfo(np.float64).tiny,
        float(np.linalg.norm(target_centered, ord="fro") * np.linalg.norm(centered, ord="fro")),
    )
    covariance_error = float(np.linalg.norm(final_target_covariance - initial_target_covariance) / covariance_scale)
    if not np.isfinite(covariance_error) or covariance_error > _TARGET_COVARIANCE_RTOL:
        raise ValueError("OSC score deflation did not preserve training target covariance")
    initial_centered_energy = float(np.sum(np.square(centered), dtype=np.float64))
    remaining_centered_energy = float(np.sum(np.square(corrected_centered), dtype=np.float64))
    if not np.isfinite(initial_centered_energy) or initial_centered_energy <= 0.0:
        raise ValueError("OSC fitting requires non-zero finite centered spectral variation")
    variance_removed = min(
        100.0,
        max(0.0, 100.0 * (1.0 - remaining_centered_energy / initial_centered_energy)),
    )
    state: dict[str, object] = {
        "serializer": _STATE_SERIALIZER,
        "algorithm": _ALGORITHM,
        "n_components": components,
        "feature_count": int(matrix.shape[1]),
        "target_count": int(targets.shape[1]),
        "feature_axis_values": None if axis_values is None else axis_values.tolist(),
        "feature_axis_units": feature_axis_units,
        "x_mean": x_mean.tolist(),
        "orthogonal_weights": weights.tolist(),
        "deflation_loadings": loadings.tolist(),
        "removed_score_singular_values": removed_score_singular_values.tolist(),
        "training_target_covariance_relative_error": covariance_error,
        "training_centered_variance_removed_percent": float(variance_removed),
    }
    _validated_osc_state(state)
    return state


def _apply_osc_state(
    data: FloatArray,
    state: Mapping[str, object],
    *,
    feature_axis_values: object = _AXIS_UNSPECIFIED,
    feature_axis_units: object = _AXIS_UNSPECIFIED,
) -> FloatArray:
    """Apply a frozen OSC projection without target access or refitting."""

    matrix = _finite_matrix(data, name="apply input")
    x_mean, weights, loadings, fitted_axis = _validated_osc_state(state)
    if matrix.shape[1] != x_mean.shape[0]:
        raise ValueError("fitted OSC state does not match the supplied feature count")
    if feature_axis_values is _AXIS_UNSPECIFIED or feature_axis_values is None:
        raise ValueError("OSC apply requires the exact numeric fitted feature axis")
    supplied_axis = np.asarray(feature_axis_values, dtype=np.float64)
    if supplied_axis.shape != fitted_axis.shape or not np.array_equal(supplied_axis, fitted_axis):
        raise ValueError("OSC apply feature axis differs from the fitted axis")
    if feature_axis_units is _AXIS_UNSPECIFIED:
        raise ValueError("OSC apply requires explicit feature-axis units, including an explicit null value")
    if feature_axis_units != state["feature_axis_units"]:
        raise ValueError("OSC apply feature-axis units differ from the fitted units")
    centered = matrix - x_mean
    corrected_centered = centered - (centered @ weights.T) @ loadings
    corrected = corrected_centered + x_mean
    if not np.isfinite(corrected).all():
        raise ValueError("OSC correction produced non-finite output")
    return corrected


def _dataset_view(value: Any, *, name: str) -> tuple[SherpaDataset, FloatArray, FloatArray | None, str | None]:
    dataset = coerce_to_sherpa(value, input_name=name)
    matrix = to_numpy_2d(dataset, name=name, dtype=np.float64)
    if not np.isfinite(matrix).all():
        raise ValueError(f"OSC {name} must contain only finite values")
    axis_values, axis_units = _axis_record(dataset, features=matrix.shape[1])
    return dataset, matrix, axis_values, axis_units


def _resolve_target(input_dataset: SherpaDataset, target: Any) -> FloatArray:
    resolved = bind_y(
        target,
        X=input_dataset,
        required=True,
        infer_from_X=True,
        dataset_as_data=True,
        target_type="continuous",
        missing_message="OSC requires continuous target values on the y port or input dataset",
    )
    if isinstance(resolved, SherpaDataset):
        resolved = resolved.X
    array = np.asarray(resolved, dtype=np.float64)
    if array.ndim == 1:
        return to_numpy_1d(array, name="y", expected_length=input_dataset.n_samples, dtype=np.float64)
    return _target_matrix(array, samples=input_dataset.n_samples)


def _osc_dispatch(input_data: Any, target: Any = None, *, n_components: int = 1) -> FloatArray:
    """One-shot workbench/export dispatcher over the sole fitted OSC ABI."""

    dataset, matrix, axis_values, axis_units = _dataset_view(input_data, name="input_data")
    resolved_target = _resolve_target(dataset, target)
    state = _fit_osc_state(
        matrix,
        resolved_target,
        n_components=n_components,
        feature_axis_values=axis_values,
        feature_axis_units=axis_units,
    )
    return _apply_osc_state(
        matrix,
        state,
        feature_axis_values=axis_values,
        feature_axis_units=axis_units,
    )


@register_node
class OSCNode(Node):
    """Fit target-orthogonal loadings once and apply their frozen projection."""

    metadata = NodeMetadata(
        node_type="preprocess.osc",
        category="preprocessing",
        label="Orthogonal Signal Correction",
        description=(
            "Fit dominant spectral variation orthogonal to continuous training targets, then apply the frozen "
            "projection without target access."
        ),
        parameters=[
            NodeParameter(
                name="n_components",
                label="Orthogonal Components",
                param_type="number",
                default=1,
                min_value=1,
                max_value=_MAX_COMPONENTS,
                max_value_reason=(
                    "Bounds SVD work and prevents an interactive correction from removing an unreviewably broad "
                    "orthogonal subspace; resolved data rank imposes the tighter runtime limit."
                ),
                step=1,
                description="Dominant target-orthogonal spectral components to remove.",
                required=True,
                category="basic",
            )
        ],
        input_types=["SherpaDataset", "array"],
        output_type="SherpaDataset",
        input_ports=[
            PortMetadata(
                name="default",
                type_ref="spectrasherpa://types/SpectralDataset/1.0",
                required=True,
                label="Input Spectra",
                description="Spectra used for fitting and correction.",
                accepted_data_roles=["X_spectra"],
            ),
            PortMetadata(
                name="reference",
                type_ref="spectrasherpa://types/SpectralDataset/1.0",
                required=False,
                label="Training Reference",
                description="Fit OSC on these training spectra and their targets; apply to Input Spectra.",
                accepted_data_roles=["X_spectra"],
            ),
            PortMetadata(
                name="y",
                type_ref="spectrasherpa://types/TargetMatrix/1.0",
                required=False,
                label="Continuous Target",
                description="Training targets; optional only when the input dataset carries them.",
                accepted_data_roles=["y_continuous"],
            ),
        ],
        output_ports=[
            PortMetadata(
                name="default",
                type_ref="spectrasherpa://types/SpectralDataset/1.0",
                required=True,
                label="OSC-Corrected Spectra",
                description="Spectra corrected through the frozen target-orthogonal projection.",
                accepted_data_roles=["X_spectra"],
            )
        ],
        policy=NodePolicy(),
        canonical_parameter_validator=_canonical_osc_parameters,
        managed_parameter_validator=_managed_osc_parameters,
    )

    def fit_fitted_state(self, input_data: Any, target: object) -> dict[str, object]:
        dataset, matrix, axis_values, axis_units = _dataset_view(input_data, name="input_data")
        parameters = self._resolve_params()
        return _fit_osc_state(
            matrix,
            target,
            n_components=int(parameters["n_components"]),
            feature_axis_values=axis_values,
            feature_axis_units=axis_units,
        )

    def apply_fitted_state(self, input_data: Any, state: Mapping[str, object]) -> SherpaDataset:
        dataset, matrix, axis_values, axis_units = _dataset_view(input_data, name="input_data")
        corrected = _apply_osc_state(
            matrix,
            state,
            feature_axis_values=axis_values,
            feature_axis_units=axis_units,
        )
        result = build_dataset_like(corrected, dataset)
        variance_removed = state["training_centered_variance_removed_percent"]
        add_processing_step(
            result,
            "preprocess.osc",
            {
                "algorithm": _ALGORITHM,
                "n_components": state["n_components"],
                "state_serializer": _STATE_SERIALIZER,
                "transform_state": dict(state),
                "variance_removed_percent": variance_removed,
            },
            node_id=self.node_id,
            state_effects=[EFFECT_SCATTER_CORRECTED],
        )
        supervision_binding.rebind_sample_preserving_supervision(dataset, result)
        return result

    async def execute(
        self,
        default: Any = None,
        input_data: Any = None,
        y: Any = None,
        reference: Any = None,
        **kwargs: Any,
    ) -> NodeResult:
        del kwargs
        source = input_data if input_data is not None else default
        dataset, _, _, _ = _dataset_view(source, name="input_data")
        fit_source = dataset if reference is None else reference
        fit_dataset, _, _, _ = _dataset_view(fit_source, name="training_reference")
        target = _resolve_target(fit_dataset, y)
        state = self.fit_fitted_state(fit_dataset, target)
        output = self.apply_fitted_state(dataset, state)
        return NodeResult(
            outputs={"default": output},
            diagnostics={
                "algorithm": _ALGORITHM,
                "n_components": state["n_components"],
                "target_count": state["target_count"],
                "training_centered_variance_removed_percent": state["training_centered_variance_removed_percent"],
                "training_target_covariance_relative_error": state["training_target_covariance_relative_error"],
                "fitted_state_serializer": _STATE_SERIALIZER,
            },
        )

    def supports_python_export(self) -> bool:
        return True

    def generate_python(
        self,
        inputs: Mapping[str, str],
        indent: str = "    ",
        use_scp: bool = True,
    ) -> list[str]:
        source = inputs.get("default") if inputs else None
        if source is None:
            source = next(iter(inputs.values())) if inputs else "input_data"
        target = inputs.get("y") if inputs else None
        reference = inputs.get("reference", source) if inputs else source
        parameters = self._resolve_params()
        return [
            header_line("Canonical fitted OSC", self.node_id, indent),
            f"{indent}from spectra_sherpa.app.services.dag.nodes.preprocessing.osc_node "
            "import OSCNode, _resolve_target",
            f"{indent}_transform = OSCNode({self.node_id!r}, {parameters!r})",
            f"{indent}_target = _resolve_target({reference}, {target or 'None'})",
            f"{indent}_state = _transform.fit_fitted_state({reference}, _target)",
            f"{indent}results[{self.node_id!r}] = _transform.apply_fitted_state({source}, _state)",
        ]


bind_stable_execution_contract(
    OSCNode,
    runtime_family=RuntimeFamily.SHERPA_NATIVE,
    lifecycle_kind=LifecycleKind.FITTED_TRANSFORM,
    implementation_id="spectrasherpa.preprocess.osc",
    implementation_version="1.0.2",
    required_worker_capabilities=(WorkerCapability.READ_DATASET,),
    managed_optimization_eligibility=(
        ManagedOptimizationEligibility.LOCAL,
        ManagedOptimizationEligibility.DEVELOPMENT,
        ManagedOptimizationEligibility.FULL_REFIT,
    ),
    sample_effect="preserves_samples",
    feature_effect="preserves_features",
    axis_effect="preserves_axis",
    unit_effect="preserves_units",
    resource_hints={"timeout_seconds": 30, "cpu_seconds": 30, "memory_bytes": 1_073_741_824},
    license_id="Apache-2.0",
    help_reference="docs/nodes/preprocessing.md",
    implementation_modules=(_shared, dag_io_contracts, dag_meta_helpers, supervision_binding),
    implementation_distributions=("numpy",),
    runtime_requirements=(("numpy", "1.26.4"),),
    managed_optimization_profiles=("first_party_pls",),
    citations=(
        "Fearn, Chemometrics and Intelligent Laboratory Systems 50 (2000) 47-52, doi:10.1016/S0169-7439(99)00045-3",
    ),
    fitted_state_serializer=_STATE_SERIALIZER,
    target_access="fit_only",
)


__all__ = ["OSCNode", "_apply_osc_state", "_fit_osc_state", "_osc_dispatch"]
