"""Canonical inclusive feature-coordinate range selection."""

from __future__ import annotations

import math
from typing import Any, cast

import numpy as np

from spectra_sherpa.app.lib import sherpa_dataset as sherpa_dataset_contract
from spectra_sherpa.app.services.dag import io_contracts as dag_io_contracts
from spectra_sherpa.app.services.dag import meta_helpers as dag_meta_helpers
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
from ._shared import (
    Node,
    NodeMetadata,
    NodeParameter,
    NodeResult,
    PortMetadata,
    add_processing_step,
    coerce_to_sherpa,
    register_node,
)


def _canonical_clip_range_parameters(parameters: dict[str, object]) -> dict[str, object]:
    """Return one exact, inclusive coordinate interval."""

    if set(parameters) != {"minimum", "maximum"}:
        raise ValueError("clip-range parameters must contain exactly minimum and maximum")
    minimum = parameters["minimum"]
    maximum = parameters["maximum"]
    if isinstance(minimum, bool) or not isinstance(minimum, (int, float)) or not math.isfinite(minimum):
        raise ValueError("clip-range minimum must be a finite number")
    if isinstance(maximum, bool) or not isinstance(maximum, (int, float)) or not math.isfinite(maximum):
        raise ValueError("clip-range maximum must be a finite number")
    lower = float(minimum)
    upper = float(maximum)
    if lower >= upper:
        raise ValueError("clip-range minimum must be strictly less than maximum")
    return {"minimum": lower, "maximum": upper}


def _clip_range_dispatch(
    feature_coordinates: np.ndarray,
    *,
    minimum: float,
    maximum: float,
) -> tuple[np.ndarray, dict[str, object]]:
    """Select an inclusive interval from one explicit monotonic feature axis."""

    parameters = _canonical_clip_range_parameters({"minimum": minimum, "maximum": maximum})
    lower = cast(float, parameters["minimum"])
    upper = cast(float, parameters["maximum"])
    coordinates = np.asarray(feature_coordinates, dtype=np.float64)
    if coordinates.ndim != 1 or coordinates.size < 1:
        raise ValueError("clip-range requires a non-empty one-dimensional feature axis")
    if not np.isfinite(coordinates).all():
        raise ValueError("clip-range feature coordinates must be finite")
    differences = np.diff(coordinates)
    increasing = bool(np.all(differences > 0.0))
    decreasing = bool(np.all(differences < 0.0))
    if coordinates.size > 1 and not (increasing or decreasing):
        raise ValueError("clip-range feature coordinates must be strictly monotonic")

    mask = (coordinates >= lower) & (coordinates <= upper)
    retained = int(mask.sum())
    if retained == 0:
        raise ValueError("clip-range interval excludes every feature coordinate")
    selected = coordinates[mask]
    diagnostics: dict[str, object] = {
        "minimum": lower,
        "maximum": upper,
        "inclusive_bounds": True,
        "axis_direction": "decreasing" if decreasing else "increasing",
        "input_features": int(coordinates.size),
        "output_features": retained,
        "removed_features": int(coordinates.size - retained),
        "retained_fraction": float(retained / coordinates.size),
        "selected_coordinate_minimum": float(selected.min()),
        "selected_coordinate_maximum": float(selected.max()),
    }
    return mask, diagnostics


def _clip_range_dataset_dispatch(
    source: Any,
    *,
    minimum: float,
    maximum: float,
) -> tuple[np.ndarray, dict[str, object]]:
    """Resolve the explicit scientific axis before selecting its interval."""

    if source.feature_axis is None:
        raise ValueError(
            "clip-range requires an explicit feature axis; integer column positions are not scientific coordinates"
        )
    return _clip_range_dispatch(
        source.feature_axis.values,
        minimum=minimum,
        maximum=maximum,
    )


def _build_clip_range_result(
    source: Any,
    mask: np.ndarray,
    parameters: dict[str, object],
    diagnostics: dict[str, object],
    *,
    node_id: str | None = None,
):
    """Subset one Sherpa dataset and bind exact interval impact provenance."""

    result = source[:, mask]
    axis_units = str(source.feature_axis.units) if source.feature_axis.units else "unavailable"
    diagnostics["axis_units"] = axis_units
    diagnostics["axis_title"] = str(source.feature_axis.title) if source.feature_axis.title else "unavailable"
    impact = {
        "schema_version": "spectrasherpa-preprocess-clip-range-impact/1",
        **diagnostics,
    }
    add_processing_step(
        result,
        "preprocess.clip_range",
        parameters,
        node_id=node_id,
        input_shape=source.shape,
        impact=impact,
    )
    result.meta["clip_range_diagnostics"] = diagnostics
    supervision_binding.rebind_sample_preserving_supervision(source, result)
    return result


@register_node
class ClipRangeNode(Node):
    """Keep features whose explicit coordinate is inside a closed interval."""

    metadata = NodeMetadata(
        node_type="preprocess.clip_range",
        category="preprocessing",
        label="Clip Feature Range",
        description=(
            "Keep the inclusive interval [minimum, maximum] in the input feature-axis units; "
            "no integer-index fallback or bound swapping is performed."
        ),
        parameters=[
            NodeParameter(
                name="minimum",
                label="Minimum Feature Coordinate",
                param_type="number",
                default=400.0,
                description="Inclusive lower bound expressed in the input feature-axis units.",
                required=True,
            ),
            NodeParameter(
                name="maximum",
                label="Maximum Feature Coordinate",
                param_type="number",
                default=4000.0,
                description="Inclusive upper bound expressed in the input feature-axis units.",
                required=True,
            ),
        ],
        input_types=["SpectralDataset"],
        input_ports=[
            PortMetadata(
                name="default",
                type_ref="spectrasherpa://types/SpectralDataset/1.0",
                required=True,
                label="Input Spectra",
                description="Spectra with a finite, strictly monotonic feature axis.",
                accepted_data_roles=["X_spectra"],
            )
        ],
        output_ports=[
            PortMetadata(
                name="default",
                type_ref="spectrasherpa://types/SpectralDataset/1.0",
                required=True,
                label="Range-selected Spectra",
                description="Spectra retaining only features inside the requested coordinate interval.",
                accepted_data_roles=["X_spectra"],
            )
        ],
        output_type="SpectralDataset",
        policy=NodePolicy(),
        canonical_parameter_validator=_canonical_clip_range_parameters,
    )

    async def execute(self, input_data: Any = None, default: Any = None, **kwargs: Any) -> NodeResult:
        del kwargs
        source = coerce_to_sherpa(input_data if input_data is not None else default, input_name="input_data")
        parameters = self._resolve_params()
        mask, diagnostics = _clip_range_dataset_dispatch(source, **parameters)
        result = _build_clip_range_result(
            source,
            mask,
            parameters,
            diagnostics,
            node_id=self.node_id,
        )
        return NodeResult(outputs={"default": result}, diagnostics=diagnostics)

    def supports_python_export(self) -> bool:
        return True

    def generate_python(self, inputs, indent="    ", use_scp=True):
        del use_scp
        source = next(iter(inputs.values())) if inputs else "input_data"
        parameters = self._resolve_params()
        return [
            f"{indent}# --- Canonical Feature Range ({self.node_id}) ---",
            f"{indent}from spectra_sherpa.app.services.dag.nodes.preprocessing.clip_range_node "
            "import _build_clip_range_result, _clip_range_dataset_dispatch",
            f"{indent}_range_mask, _range_diagnostics = _clip_range_dataset_dispatch({source}, **{parameters!r})",
            f"{indent}results[{self.node_id!r}] = _build_clip_range_result("
            f"{source}, _range_mask, {parameters!r}, _range_diagnostics, node_id={self.node_id!r})",
        ]


bind_stable_execution_contract(
    ClipRangeNode,
    runtime_family=RuntimeFamily.SHERPA_NATIVE,
    lifecycle_kind=LifecycleKind.STATELESS_TRANSFORM,
    implementation_id="spectrasherpa.preprocess.clip_range",
    implementation_version="1.0.1",
    required_worker_capabilities=(WorkerCapability.READ_DATASET,),
    managed_optimization_eligibility=(ManagedOptimizationEligibility.LOCAL,),
    sample_effect="preserves_samples",
    feature_effect="filters_features",
    axis_effect="changes_axis",
    unit_effect="preserves_units",
    resource_hints={"timeout_seconds": 30, "cpu_seconds": 30, "memory_bytes": 1_073_741_824},
    license_id="Apache-2.0",
    help_reference="docs/nodes/preprocessing.md",
    implementation_modules=(
        _shared,
        dag_io_contracts,
        dag_meta_helpers,
        sherpa_dataset_contract,
        supervision_binding,
    ),
    implementation_distributions=("numpy",),
    runtime_requirements=(("numpy", "1.26.4"),),
)


__all__ = [
    "ClipRangeNode",
    "_build_clip_range_result",
    "_canonical_clip_range_parameters",
    "_clip_range_dataset_dispatch",
    "_clip_range_dispatch",
]
