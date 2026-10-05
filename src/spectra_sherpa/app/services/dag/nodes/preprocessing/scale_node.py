"""Canonical reference-fitted scaling node.

``preprocess.scale`` is the sole scaling producer in the live DAG registry.
The ordinary workbench executes it as a one-shot fit/apply operation, while
managed validation calls the same public fit/apply ABI separately so every
held-out fold uses statistics learned only from its training rows.
"""

from __future__ import annotations

from typing import Any, Mapping

import numpy as np

from spectra_sherpa.app.lib.sherpa_dataset import EFFECT_MEAN_CENTERED
from spectra_sherpa.app.services.dag import supervision_binding
from spectra_sherpa.app.services.dag.fitted_input_identity import (
    canonical_signal_units,
    fitted_input_identity,
    require_fitted_input_identity,
)
from spectra_sherpa.app.services.dag.node_base import NodePolicy
from spectra_sherpa.app.services.dag.stable_execution_contract import bind_stable_execution_contract
from spectra_sherpa.execution_contract_vocabulary import (
    LifecycleKind,
    ManagedOptimizationEligibility,
    RuntimeFamily,
    WorkerCapability,
)

from . import _shared
from ._shared import (
    EFFECT_SCALED,
    Node,
    NodeMetadata,
    NodeParameter,
    NodeResult,
    PortMetadata,
    add_processing_step,
    build_dataset_like,
    coerce_to_sherpa,
    header_line,
    register_node,
    to_numpy_2d,
)

_STATE_SERIALIZER = "spectra.scale-reference-json.v2"
_METHODS = frozenset({"mean_center", "autoscale", "pareto"})


def _canonical_scale_parameters(parameters: dict[str, object]) -> dict[str, object]:
    """Return the exact current parameter representation for scaling."""

    method = parameters["method"]
    center = parameters["center"]
    if not isinstance(method, str) or method not in _METHODS:
        raise ValueError("scale method must be mean_center, autoscale, or pareto")
    if not isinstance(center, bool):
        raise ValueError("scale center flag must be boolean")
    if method == "mean_center" and center is not True:
        raise ValueError("mean_center is intrinsically centered")
    return {"method": method, "center": center}


def scaled_signal_units(units: str | None, method: object) -> str | None:
    """The unit algebra is part of the fitted transform's output meaning."""
    if method == "mean_center":
        return units
    if method == "autoscale":
        return "dimensionless"
    if method == "pareto":
        units = canonical_signal_units(units)
        if units is None or units == "dimensionless":
            return units
        return f"sqrt({units})"
    raise ValueError("unknown fitted scaling method")


def _finite_vector(value: object, *, name: str, features: int) -> np.ndarray:
    array = np.asarray(value, dtype=np.float64)
    if array.ndim != 1 or array.shape[0] != features or not np.isfinite(array).all():
        raise ValueError(f"fitted scale state has an invalid {name} vector")
    return np.array(array, dtype=np.float64, copy=True)


def _fit_scale_state(data: np.ndarray, *, method: str, center: bool, source_dataset: Any = None) -> dict[str, object]:
    """Fit finite reference statistics from training rows only."""

    projected = _canonical_scale_parameters({"method": method, "center": center})
    matrix = np.asarray(data, dtype=np.float64)
    if matrix.ndim != 2 or matrix.shape[0] == 0 or matrix.shape[1] == 0 or not np.isfinite(matrix).all():
        raise ValueError("scale fitting requires a non-empty finite two-dimensional training matrix")
    identity = fitted_input_identity(source_dataset, features=matrix.shape[1])
    mean = np.mean(matrix, axis=0, dtype=np.float64)
    if projected["method"] == "mean_center":
        return {
            "serializer": _STATE_SERIALIZER,
            "input_identity": identity,
            "method": "mean_center",
            "center": True,
            "mean": mean.tolist(),
            "scale": None,
        }
    scale = np.std(matrix, axis=0, dtype=np.float64)
    if projected["method"] == "pareto":
        scale = np.sqrt(np.maximum(scale, 0.0))
    scale[(scale == 0.0) | ~np.isfinite(scale)] = 1.0
    return {
        "serializer": _STATE_SERIALIZER,
        "input_identity": identity,
        "method": projected["method"],
        "center": projected["center"],
        "mean": mean.tolist() if projected["center"] else None,
        "scale": scale.tolist(),
    }


def _apply_scale_state(data: np.ndarray, state: Mapping[str, object], *, source_dataset: Any = None) -> np.ndarray:
    """Apply already-fitted reference statistics without calculating new ones."""

    required = {"serializer", "method", "center", "mean", "scale", "input_identity"}
    if not isinstance(state, Mapping) or set(state) != required or state["serializer"] != _STATE_SERIALIZER:
        raise ValueError("fitted scale state does not use the closed serializer schema")
    method = state["method"]
    center = state["center"]
    if method not in _METHODS or not isinstance(center, bool):
        raise ValueError("fitted scale state has an invalid method or center flag")
    matrix = np.asarray(data, dtype=np.float64)
    if matrix.ndim != 2 or matrix.shape[1] == 0 or not np.isfinite(matrix).all():
        raise ValueError("fitted scale apply input must be a finite two-dimensional matrix")
    features = matrix.shape[1]
    require_fitted_input_identity(source_dataset, state["input_identity"], features=features)
    result = np.array(matrix, dtype=np.float64, copy=True)
    if method == "mean_center":
        if center is not True or state["scale"] is not None:
            raise ValueError("fitted scale state for mean-center must center and must not declare a scale vector")
        result -= _finite_vector(state["mean"], name="mean", features=features)
        return result
    if center:
        result -= _finite_vector(state["mean"], name="mean", features=features)
    elif state["mean"] is not None:
        raise ValueError("uncentered fitted scale state must not contain a mean vector")
    scale = _finite_vector(state["scale"], name="scale", features=features)
    if np.any(scale <= 0.0):
        raise ValueError("fitted scale state must have a strictly positive scale vector")
    result /= scale
    return result


def _scale_dispatch(
    data: np.ndarray,
    *,
    method: str = "mean_center",
    center: bool = True,
    reference_data: np.ndarray | None = None,
) -> np.ndarray:
    """Fit once on the supplied reference (or input) and apply through the sole ABI."""

    matrix = np.asarray(data, dtype=np.float64)
    reference = matrix if reference_data is None else np.asarray(reference_data, dtype=np.float64)
    return _apply_scale_state(matrix, _fit_scale_state(reference, method=method, center=center))


@register_node
class ScaleNode(Node):
    """Fit and apply mean centering, autoscaling, or Pareto scaling."""

    metadata = NodeMetadata(
        node_type="preprocess.scale",
        category="preprocessing",
        label="Scale / Center",
        description=(
            "Fit centering or scaling statistics on reference data and apply the frozen state. "
            "Managed validation fits each fold from training rows only."
        ),
        parameters=[
            NodeParameter(
                name="method",
                label="Method",
                param_type="select",
                default="mean_center",
                options=[
                    {"label": "Mean Center", "value": "mean_center"},
                    {"label": "Autoscale", "value": "autoscale"},
                    {"label": "Pareto", "value": "pareto"},
                ],
                description="Reference-fitted scaling method.",
                required=True,
                category="basic",
            ),
            NodeParameter(
                name="center",
                label="Mean Center First",
                param_type="boolean",
                default=True,
                description="Subtract the fitted reference mean before autoscaling or Pareto scaling.",
                required=False,
                category="basic",
                visible_when={"method": ["autoscale", "pareto"]},
            ),
        ],
        input_types=["SherpaDataset"],
        input_ports=[
            PortMetadata(
                name="default",
                type_ref="spectrasherpa://types/SpectralDataset/1.0",
                required=True,
                label="Input Data",
                description="Data matrix to fit or apply using the canonical scaling lifecycle.",
                accepted_data_roles=["X_spectra", "X_features"],
            ),
            PortMetadata(
                name="reference",
                type_ref="spectrasherpa://types/SpectralDataset/1.0",
                required=False,
                label="Fit Reference",
                description="Optional rows used to fit scaling statistics before transforming the input data.",
                accepted_data_roles=["X_spectra", "X_features"],
            ),
        ],
        output_ports=[
            PortMetadata(
                name="default",
                type_ref="spectrasherpa://types/SpectralDataset/1.0",
                required=True,
                label="Scaled Data",
                description="Data transformed with fitted reference statistics.",
                accepted_data_roles=["X_spectra", "X_features"],
            )
        ],
        output_type="SherpaDataset",
        policy=NodePolicy(),
        canonical_parameter_validator=_canonical_scale_parameters,
    )

    def fit_fitted_state(self, input_data: Any) -> dict[str, object]:
        dataset = coerce_to_sherpa(input_data, input_name="input_data")
        data = to_numpy_2d(dataset, name="input_data", dtype=np.float64)
        parameters = self._resolve_params()
        return _fit_scale_state(
            data, method=str(parameters["method"]), center=bool(parameters["center"]), source_dataset=dataset
        )

    def apply_fitted_state(self, input_data: Any, state: Mapping[str, object]):
        dataset = coerce_to_sherpa(input_data, input_name="input_data")
        data = to_numpy_2d(dataset, name="input_data", dtype=np.float64)
        transformed = _apply_scale_state(data, state, source_dataset=dataset)
        result = build_dataset_like(transformed, dataset)
        result.units = scaled_signal_units(dataset.units, state["method"])
        effects = [EFFECT_MEAN_CENTERED] if state["center"] else []
        if state["method"] != "mean_center":
            effects.append(EFFECT_SCALED)
        add_processing_step(
            result,
            "preprocess.scale",
            {
                "method": state["method"],
                "center": state["center"],
                "state_serializer": _STATE_SERIALIZER,
                # Ordinary workbench models persist this exact state in their
                # preprocessing chain. Artifact application therefore reuses
                # the same closed ABI instead of inferring scale statistics.
                "transform_state": dict(state),
            },
            node_id=self.node_id,
            state_effects=effects,
        )
        supervision_binding.rebind_sample_preserving_supervision(dataset, result)
        return result

    async def execute(
        self,
        default: Any = None,
        input_data: Any = None,
        reference: Any = None,
        **kwargs: Any,
    ) -> NodeResult:
        """Run the workbench's one-shot fit/apply through the managed lifecycle ABI."""

        del kwargs
        source = input_data if input_data is not None else default
        fit_source = reference if reference is not None else source
        state = self.fit_fitted_state(fit_source)
        output = self.apply_fitted_state(source, state)
        return NodeResult(
            outputs={"default": output},
            diagnostics={
                "method": state["method"],
                "center": state["center"],
                "fitted_state_serializer": _STATE_SERIALIZER,
            },
        )

    def supports_python_export(self) -> bool:
        return True

    def generate_python(self, inputs, indent="    ", use_scp=True):
        inp = inputs.get("default") if inputs else None
        if inp is None:
            inp = next(iter(inputs.values())) if inputs else "input_data"
        reference = inputs.get("reference") if inputs else None
        params = self._resolve_params()
        return [
            header_line("Canonical Scaling", self.node_id, indent),
            f"{indent}from spectra_sherpa.app.services.dag.nodes.preprocessing.scale_node import ScaleNode",
            f"{indent}_transform = ScaleNode({self.node_id!r}, {params!r})",
            f"{indent}_state = _transform.fit_fitted_state({reference if reference is not None else inp})",
            f"{indent}results[{self.node_id!r}] = _transform.apply_fitted_state({inp}, _state)",
        ]


bind_stable_execution_contract(
    ScaleNode,
    runtime_family=RuntimeFamily.SHERPA_NATIVE,
    lifecycle_kind=LifecycleKind.FITTED_TRANSFORM,
    implementation_id="spectrasherpa.preprocess.scale",
    implementation_version="2.0.0",
    required_worker_capabilities=(WorkerCapability.READ_DATASET,),
    managed_optimization_eligibility=(
        ManagedOptimizationEligibility.LOCAL,
        ManagedOptimizationEligibility.DEVELOPMENT,
        ManagedOptimizationEligibility.FULL_REFIT,
    ),
    sample_effect="preserves_samples",
    feature_effect="preserves_features",
    axis_effect="preserves_axis",
    unit_effect="changes_units",
    resource_hints={"timeout_seconds": 30, "cpu_seconds": 30, "memory_bytes": 1_073_741_824},
    license_id="Apache-2.0",
    help_reference="docs/nodes/preprocessing.md",
    implementation_modules=(_shared, supervision_binding),
    implementation_distributions=("numpy",),
    runtime_requirements=(("numpy", "1.26.4"),),
    managed_optimization_profiles=("first_party_pls",),
    fitted_state_serializer=_STATE_SERIALIZER,
    citations=(
        "van den Berg et al., BMC Genomics 7 (2006) 142, DOI 10.1186/1471-2164-7-142",
        "mdatools prep.autoscale reference, https://mdatools.com/docs/preprocessing--autoscaling.html",
    ),
)


__all__ = ["ScaleNode"]
