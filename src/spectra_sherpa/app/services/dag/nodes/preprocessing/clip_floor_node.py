"""Canonical literal value-floor clipping for spectral matrices."""

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

from . import _impact_statistics, _shared
from ._impact_statistics import finite_nonnegative_mean
from ._shared import (
    Node,
    NodeMetadata,
    NodeParameter,
    NodeResult,
    PortMetadata,
    add_processing_step,
    build_dataset_like,
    coerce_to_sherpa,
    register_node,
    to_numpy_2d,
)


def _canonical_clip_floor_parameters(parameters: dict[str, object]) -> dict[str, object]:
    """Return the exact finite threshold executed by the node."""

    floor = parameters["floor"]
    if isinstance(floor, bool) or not isinstance(floor, (int, float)) or not math.isfinite(floor):
        raise ValueError("clip-floor threshold must be a finite number")
    return {"floor": float(floor)}


def _clip_floor_dispatch(
    data: np.ndarray,
    *,
    floor: float,
) -> tuple[np.ndarray, dict[str, object]]:
    """Apply one literal lower bound and quantify every changed value."""

    parameters = _canonical_clip_floor_parameters({"floor": floor})
    matrix = np.asarray(data, dtype=np.float64)
    was_vector = matrix.ndim == 1
    if was_vector:
        matrix = matrix.reshape(1, -1)
    if matrix.ndim != 2 or matrix.shape[0] < 1 or matrix.shape[1] < 1:
        raise ValueError("clip-floor input must be a non-empty spectral matrix")
    if not np.isfinite(matrix).all():
        raise ValueError("clip-floor input must contain only finite values")

    threshold = cast(float, parameters["floor"])
    changed = matrix < threshold
    result = np.maximum(matrix, threshold)
    with np.errstate(over="ignore", invalid="ignore"):
        adjustments = result[changed] - matrix[changed]
    if not np.isfinite(adjustments).all():
        raise ValueError("clip-floor adjustment magnitude is not finitely representable")
    changed_count = int(changed.sum())
    diagnostics: dict[str, object] = {
        "floor": threshold,
        "clipped_values": changed_count,
        "clipped_fraction": float(changed_count / matrix.size),
        "samples_with_clipping": int(np.any(changed, axis=1).sum()),
        "maximum_upward_adjustment": float(adjustments.max()) if changed_count else 0.0,
        "mean_upward_adjustment": finite_nonnegative_mean(adjustments),
        "input_minimum": float(matrix.min()),
        "output_minimum": float(result.min()),
    }
    return (result[0] if was_vector else result), diagnostics


def _build_clip_floor_result(
    clipped: np.ndarray,
    source: Any,
    parameters: dict[str, object],
    diagnostics: dict[str, object],
    *,
    node_id: str | None = None,
):
    """Wrap clipped values with exact threshold and impact provenance."""

    result = build_dataset_like(clipped, source, units=source.units)
    diagnostics["value_units"] = source.units or "unavailable"
    impact = {
        "schema_version": "spectrasherpa-preprocess-clip-floor-impact/1",
        **diagnostics,
    }
    add_processing_step(
        result,
        "preprocess.clip_floor",
        parameters,
        node_id=node_id,
        input_shape=source.shape,
        impact=impact,
    )
    result.meta["clip_floor_diagnostics"] = diagnostics
    supervision_binding.rebind_sample_preserving_supervision(source, result)
    return result


@register_node
class ClipFloorNode(Node):
    """Set every value below one explicit finite floor to that floor."""

    metadata = NodeMetadata(
        node_type="preprocess.clip_floor",
        category="preprocessing",
        label="Clip Floor",
        description=(
            "Apply one explicit lower value threshold and report the count, fraction, "
            "and magnitude of all upward adjustments."
        ),
        parameters=[
            NodeParameter(
                name="floor",
                label="Floor Value",
                param_type="number",
                default=0.0,
                step=0.001,
                description="Exact minimum value; every smaller finite value is set to this threshold.",
                required=True,
            )
        ],
        input_types=["SpectralDataset"],
        input_ports=[
            PortMetadata(
                name="default",
                type_ref="spectrasherpa://types/SpectralDataset/1.0",
                required=True,
                label="Input Spectra",
                description="Non-empty finite spectra whose literal values will be bounded.",
                accepted_data_roles=["X_spectra"],
            )
        ],
        output_ports=[
            PortMetadata(
                name="default",
                type_ref="spectrasherpa://types/SpectralDataset/1.0",
                required=True,
                label="Floor-clipped Spectra",
                description="Spectra with samples, feature axis, and value units preserved.",
                accepted_data_roles=["X_spectra"],
            )
        ],
        output_type="SpectralDataset",
        policy=NodePolicy(),
        canonical_parameter_validator=_canonical_clip_floor_parameters,
    )

    async def execute(self, input_data: Any = None, default: Any = None, **kwargs: Any) -> NodeResult:
        del kwargs
        source = coerce_to_sherpa(input_data if input_data is not None else default, input_name="input_data")
        parameters = self._resolve_params()
        clipped, diagnostics = _clip_floor_dispatch(to_numpy_2d(source, name="input_data"), **parameters)
        result = _build_clip_floor_result(
            clipped,
            source,
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
            f"{indent}# --- Canonical Clip Floor ({self.node_id}) ---",
            f"{indent}from spectra_sherpa.app.services.dag.nodes.preprocessing.clip_floor_node "
            "import _build_clip_floor_result, _clip_floor_dispatch",
            f"{indent}_floor_clipped, _floor_diagnostics = _clip_floor_dispatch("
            f"np.asarray({source}.data, dtype=np.float64), **{parameters!r})",
            f"{indent}results[{self.node_id!r}] = _build_clip_floor_result("
            f"_floor_clipped, {source}, {parameters!r}, _floor_diagnostics, node_id={self.node_id!r})",
        ]


bind_stable_execution_contract(
    ClipFloorNode,
    runtime_family=RuntimeFamily.SHERPA_NATIVE,
    lifecycle_kind=LifecycleKind.STATELESS_TRANSFORM,
    implementation_id="spectrasherpa.preprocess.clip_floor",
    implementation_version="1.0.1",
    required_worker_capabilities=(WorkerCapability.READ_DATASET,),
    managed_optimization_eligibility=(ManagedOptimizationEligibility.LOCAL,),
    sample_effect="preserves_samples",
    feature_effect="preserves_features",
    axis_effect="preserves_axis",
    unit_effect="preserves_units",
    resource_hints={"timeout_seconds": 30, "cpu_seconds": 30, "memory_bytes": 1_073_741_824},
    license_id="Apache-2.0",
    help_reference="docs/nodes/preprocessing.md",
    implementation_modules=(
        supervision_binding,
        _shared,
        _impact_statistics,
        dag_io_contracts,
        dag_meta_helpers,
        sherpa_dataset_contract,
    ),
    implementation_distributions=("numpy",),
    runtime_requirements=(("numpy", "1.26.4"),),
)


__all__ = [
    "ClipFloorNode",
    "_build_clip_floor_result",
    "_canonical_clip_floor_parameters",
    "_clip_floor_dispatch",
]
