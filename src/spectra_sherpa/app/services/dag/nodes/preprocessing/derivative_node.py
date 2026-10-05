"""Canonical spectral derivative node."""

from __future__ import annotations

from typing import Any

import numpy as np

from spectra_sherpa.app.services.dag import supervision_binding
from spectra_sherpa.app.services.dag.node_base import NodePolicy
from spectra_sherpa.app.services.dag.stable_execution_contract import bind_stable_execution_contract
from spectra_sherpa.execution_contract_vocabulary import (
    LifecycleKind,
    ManagedOptimizationEligibility,
    RuntimeFamily,
    WorkerCapability,
)

from . import _shared
from . import norris_williams as norris_williams_module
from ._shared import (
    EFFECT_DERIVATIVE,
    EFFECT_SMOOTHED,
    Node,
    NodeMetadata,
    NodeParameter,
    NodeResult,
    PortMetadata,
    add_processing_step,
    build_dataset_like,
    coerce_to_sherpa,
    header_line,
    norris_williams,
    register_node,
    to_numpy_2d,
)


def _savgol_derivative(
    data: np.ndarray,
    *,
    size: int,
    order: int,
    deriv: int,
    delta: float,
) -> np.ndarray:
    from scipy.signal import savgol_filter

    return np.apply_along_axis(
        savgol_filter,
        -1,
        data,
        window_length=size,
        polyorder=order,
        deriv=deriv,
        delta=delta,
    )


def _update_derivative_units(result: Any, input_ds: Any, deriv_order: int) -> None:
    original_units = str(input_ds.units) if getattr(input_ds, "units", None) else None
    feature_axis = getattr(input_ds, "feature_axis", None)
    axis_units = getattr(feature_axis, "units", None)
    if deriv_order == 1:
        if original_units and original_units != "dimensionless":
            result.units = f"d({original_units})/d({axis_units})" if axis_units else f"d({original_units})/dx"
        else:
            result.units = f"d/d({axis_units})" if axis_units else "d/dx"
    elif deriv_order == 2:
        if original_units and original_units != "dimensionless":
            result.units = f"d²({original_units})/d({axis_units})²" if axis_units else f"d²({original_units})/dx²"
        else:
            result.units = f"d²/d({axis_units})²" if axis_units else "d²/dx²"
    else:
        raise ValueError("derivative unit update requires order 1 or 2")


def _canonical_derivative_parameters(parameters: dict[str, object]) -> dict[str, object]:
    """Enforce exact integer and method-specific derivative semantics."""

    method = parameters["method"]
    if not isinstance(method, str) or method not in {"savitzky_golay", "norris_williams"}:
        raise ValueError("derivative method is not admitted")
    if not isinstance(parameters["deriv"], str) or parameters["deriv"] not in {"1", "2"}:
        raise ValueError("derivative order must be exactly '1' or '2'")
    deriv = int(str(parameters["deriv"]))
    numeric = {name: parameters[name] for name in ("size", "order", "gap", "segment")}
    if any(isinstance(value, bool) or not isinstance(value, int) for value in numeric.values()):
        raise ValueError("derivative size, order, gap, and segment must be exact integers")
    if any(int(numeric[name]) < 1 for name in ("size", "order", "gap", "segment")):
        raise ValueError("derivative size, order, gap, and segment must be positive integers")
    if method == "savitzky_golay":
        size = int(numeric["size"])
        order = int(numeric["order"])
        if int(size) % 2 == 0 or int(order) >= int(size) or deriv > int(order):
            raise ValueError("Savitzky-Golay derivative parameters are not scientifically admissible")
        if parameters["gap"] != 5 or parameters["segment"] != 5:
            raise ValueError("Savitzky-Golay may not carry Norris-Williams settings")
    elif method == "norris_williams":
        if parameters["size"] != 11 or parameters["order"] != 2:
            raise ValueError("Norris-Williams may not carry Savitzky-Golay settings")
    return parameters


def _managed_derivative_parameters(parameters: dict[str, object]) -> dict[str, object]:
    """Bound hosted derivative work without changing the local algorithm."""

    projected = _canonical_derivative_parameters(parameters)
    if projected["method"] == "savitzky_golay":
        if not 5 <= int(projected["size"]) <= 31:
            raise ValueError("managed Savitzky-Golay window must be from 5 through 31")
        if not 2 <= int(projected["order"]) <= 4:
            raise ValueError("managed Savitzky-Golay order must be from 2 through 4")
    else:
        if not 1 <= int(projected["gap"]) <= 15 or not 1 <= int(projected["segment"]) <= 15:
            raise ValueError("managed Norris-Williams gap and segment must be from 1 through 15")
    return projected


def _derivative_dispatch(
    data: np.ndarray,
    method: str = "savitzky_golay",
    deriv: str = "1",
    size: int = 11,
    order: int = 2,
    gap: int = 5,
    segment: int = 5,
    delta: float = 1.0,
) -> np.ndarray:
    projected = _canonical_derivative_parameters(
        {
            "method": method,
            "deriv": deriv,
            "size": size,
            "order": order,
            "gap": gap,
            "segment": segment,
        }
    )
    if isinstance(delta, bool) or not isinstance(delta, (int, float)) or not np.isfinite(delta) or delta == 0:
        raise ValueError("derivative axis spacing must be a finite non-zero number")
    matrix = np.asarray(data, dtype=np.float64)
    if matrix.ndim != 2 or matrix.shape[0] == 0 or matrix.shape[1] == 0:
        raise ValueError("preprocess.derivative requires a non-empty two-dimensional sample-by-feature matrix")
    if not np.isfinite(matrix).all():
        raise ValueError(
            "preprocess.derivative requires finite input values; remove an explicitly blanked region "
            "with preprocess.clip_range before differentiation"
        )
    deriv_order = int(str(projected["deriv"]))
    if projected["method"] == "savitzky_golay":
        size = int(projected["size"])
        order = int(projected["order"])
        if size > matrix.shape[-1]:
            raise ValueError("Savitzky-Golay window size may not exceed the feature count")
        return _savgol_derivative(matrix, size=size, order=order, deriv=deriv_order, delta=float(delta))
    if projected["method"] == "norris_williams":
        gap = int(projected["gap"])
        segment = int(projected["segment"])
        if matrix.shape[-1] < 2 * (gap + segment) - 1:
            raise ValueError("Norris-Williams gap and segment leave no interior derivative points")
        return norris_williams(matrix, gap=gap, segment=segment, deriv=deriv_order, delta=float(delta))
    raise AssertionError("closed derivative grammar returned an unknown method")


def _feature_axis_delta(input_ds: Any) -> float:
    axis = (
        input_ds.get_feature_axis()
        if hasattr(input_ds, "get_feature_axis")
        else getattr(input_ds, "feature_axis", None)
    )
    values = getattr(axis, "values", None)
    if values is None:
        return 1.0
    x = np.asarray(values, dtype=np.float64).reshape(-1)
    if x.size < 2:
        return 1.0
    diffs = np.diff(x)
    finite = diffs[np.isfinite(diffs)]
    if finite.size != diffs.size or finite.size == 0:
        raise ValueError("Derivative requires a finite feature axis")
    delta = float(np.median(finite))
    if abs(delta) <= 1e-12:
        raise ValueError("Derivative requires a non-zero feature-axis spacing")
    if not np.allclose(finite, delta, rtol=1e-4, atol=max(abs(delta) * 1e-6, 1e-12)):
        raise ValueError(
            "Derivative requires an evenly spaced feature axis. Resample or align the spectra before "
            "requesting physical derivative units."
        )
    return delta


def _execute_derivative(
    input_data: Any,
    *,
    parameters: dict[str, object],
    node_id: str,
) -> tuple[Any, dict[str, object]]:
    """Build the live and exported result through one complete authority."""

    input_ds = coerce_to_sherpa(input_data, input_name="input_data")
    data = to_numpy_2d(input_ds, name="input_data", dtype=np.float64)
    delta = _feature_axis_delta(input_ds)
    transformed = _derivative_dispatch(data, delta=delta, **parameters)
    result = build_dataset_like(transformed, input_ds)
    derivative_order = int(str(parameters["deriv"]))
    _update_derivative_units(result, input_ds, derivative_order)
    add_processing_step(
        result,
        "preprocess.derivative",
        {**parameters, "delta": delta},
        node_id=node_id,
        state_effects=[EFFECT_DERIVATIVE, EFFECT_SMOOTHED],
    )
    supervision_binding.rebind_sample_preserving_supervision(input_ds, result)
    return result, {
        "method": parameters["method"],
        "derivative_order": derivative_order,
        "axis_delta": delta,
    }


@register_node
class DerivativeNode(Node):
    """Compute a first or second spectral derivative with one admitted method."""

    metadata = NodeMetadata(
        node_type="preprocess.derivative",
        category="preprocessing",
        label="Derivative",
        description="Compute a first or second Savitzky-Golay or Norris-Williams derivative.",
        parameters=[
            NodeParameter(
                name="method",
                label="Method",
                param_type="select",
                default="savitzky_golay",
                options=[
                    {"label": "Savitzky-Golay", "value": "savitzky_golay"},
                    {"label": "Norris-Williams", "value": "norris_williams"},
                ],
                description="Derivative algorithm",
                required=True,
                category="basic",
            ),
            NodeParameter(
                name="deriv",
                label="Derivative Order",
                param_type="select",
                default="1",
                options=["1", "2"],
                description="First or second derivative order",
                required=True,
                category="basic",
            ),
            NodeParameter(
                name="size",
                label="Window Size",
                param_type="number",
                default=11,
                min_value=3,
                step=2,
                description=(
                    "Odd Savitzky-Golay window size. "
                    "Hosted execution admits Savitzky-Golay windows from 5 through 31 points."
                ),
                required=False,
                category="basic",
                visible_when={"method": ["savitzky_golay"]},
            ),
            NodeParameter(
                name="order",
                label="Polynomial Order",
                param_type="number",
                default=2,
                min_value=1,
                step=1,
                description=(
                    "Savitzky-Golay polynomial order. " "Hosted execution admits polynomial orders from 2 through 4."
                ),
                required=False,
                category="basic",
                visible_when={"method": ["savitzky_golay"]},
            ),
            NodeParameter(
                name="gap",
                label="Gap",
                param_type="number",
                default=5,
                min_value=1,
                step=1,
                description=(
                    "Norris-Williams gap size. " "Hosted execution admits Norris-Williams gaps from 1 through 15."
                ),
                required=False,
                category="basic",
                visible_when={"method": ["norris_williams"]},
            ),
            NodeParameter(
                name="segment",
                label="Segment",
                param_type="number",
                default=5,
                min_value=1,
                step=1,
                description=(
                    "Norris-Williams segment size. "
                    "Hosted execution admits Norris-Williams segments from 1 through 15."
                ),
                required=False,
                category="basic",
                visible_when={"method": ["norris_williams"]},
            ),
        ],
        input_types=["SherpaDataset"],
        input_ports=[
            PortMetadata(
                name="default",
                type_ref="spectrasherpa://types/SpectralDataset/1.0",
                required=True,
                label="Input Spectra",
                description="Evenly spaced spectral data to differentiate.",
                accepted_data_roles=["X_spectra"],
            )
        ],
        output_ports=[
            PortMetadata(
                name="default",
                type_ref="spectrasherpa://types/SpectralDataset/1.0",
                required=True,
                label="Derivative Spectra",
                description="Spectra differentiated on the declared feature-axis spacing.",
                accepted_data_roles=["X_spectra"],
            )
        ],
        output_type="SherpaDataset",
        policy=NodePolicy(),
        canonical_parameter_validator=_canonical_derivative_parameters,
        managed_parameter_validator=_managed_derivative_parameters,
    )

    async def execute(self, input_data: Any = None, **kwargs: Any) -> NodeResult:
        del kwargs
        params = self._resolve_params()
        result, diagnostics = _execute_derivative(input_data, parameters=params, node_id=self.node_id)
        return NodeResult(outputs={"default": result}, diagnostics=diagnostics)

    def supports_python_export(self) -> bool:
        return True

    def generate_python(self, inputs, indent="    ", use_scp=True):
        del use_scp
        inp = next(iter(inputs.values())) if inputs else "input_data"
        params = self._resolve_params()
        return [
            header_line("Canonical Derivative", self.node_id, indent),
            f"{indent}from spectra_sherpa.app.services.dag.nodes.preprocessing.derivative_node import "
            "_execute_derivative",
            f"{indent}results[{self.node_id!r}], _derivative_diagnostics = _execute_derivative(",
            f"{indent}    {inp}, parameters={params!r}, node_id={self.node_id!r},",
            f"{indent})",
        ]


bind_stable_execution_contract(
    DerivativeNode,
    runtime_family=RuntimeFamily.SHERPA_NATIVE,
    lifecycle_kind=LifecycleKind.STATELESS_TRANSFORM,
    implementation_id="spectrasherpa.preprocess.derivative",
    implementation_version="1.0.1",
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
    implementation_modules=(_shared, norris_williams_module, supervision_binding),
    implementation_distributions=("numpy", "scipy"),
    runtime_requirements=(("numpy", "1.26.4"), ("scipy", "1.17.1")),
    managed_optimization_profiles=("first_party_pls",),
    citations=(
        "Savitzky and Golay, Analytical Chemistry 36 (1964) 1627-1639, DOI 10.1021/ac60214a047",
        "Norris and Williams, Cereal Chemistry 61 (1984) 158-165, Norris-Williams gap derivative",
    ),
)


__all__ = ["DerivativeNode", "_execute_derivative"]
