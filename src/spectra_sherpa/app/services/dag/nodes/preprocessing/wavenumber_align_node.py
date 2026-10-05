"""Canonical interpolation of spectra onto an explicit reference wavenumber grid."""

from __future__ import annotations

import hashlib
import math
from typing import Any, cast

import numpy as np
from scipy.interpolate import PchipInterpolator

from spectra_sherpa.app.lib import sherpa_dataset as sherpa_dataset_contract
from spectra_sherpa.app.lib.axes import SpectralAxis
from spectra_sherpa.app.services.dag import io_contracts as dag_io_contracts
from spectra_sherpa.app.services.dag import meta_helpers as dag_meta_helpers
from spectra_sherpa.app.services.dag import supervision_binding
from spectra_sherpa.app.services.dag.node_base import NodePolicy
from spectra_sherpa.app.services.dag.stable_execution_contract import bind_stable_execution_contract
from spectra_sherpa.core.axis_semantics import AxisQuantity, axis_semantics
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
    build_dataset_like,
    coerce_to_sherpa,
    register_node,
    to_numpy_2d,
)

_SINC_KERNEL_HALF_WIDTH = 8
_SincInterpolationTerm = tuple[np.ndarray, np.ndarray, float]


def _canonical_wavenumber_align_parameters(parameters: dict[str, object]) -> dict[str, object]:
    """Return the exact interpolation and extrapolation policy."""

    if set(parameters) != {"method", "extrapolation"}:
        raise ValueError("wavenumber-align parameters must contain exactly method and extrapolation")
    method = parameters["method"]
    extrapolation = parameters["extrapolation"]
    if method not in {"linear", "pchip", "sinc"}:
        raise ValueError("wavenumber-align method must be linear, pchip, or sinc")
    if extrapolation != "reject":
        raise ValueError("wavenumber-align extrapolation must be reject")
    return {"method": str(method), "extrapolation": "reject"}


def _validated_axis(coordinates: Any, *, name: str) -> tuple[np.ndarray, str]:
    """Return one finite, strictly monotonic coordinate vector and direction."""

    axis = np.asarray(coordinates, dtype=np.float64)
    if axis.ndim != 1 or axis.size < 2:
        raise ValueError(f"{name} must contain at least two one-dimensional coordinates")
    if not np.isfinite(axis).all():
        raise ValueError(f"{name} coordinates must be finite")
    with np.errstate(over="ignore", invalid="ignore"):
        differences = np.diff(axis)
    if not np.isfinite(differences).all():
        raise ValueError(f"{name} coordinate spacings must be finitely representable")
    increasing = bool(np.all(differences > 0.0))
    decreasing = bool(np.all(differences < 0.0))
    if not (increasing or decreasing):
        raise ValueError(f"{name} coordinates must be strictly monotonic")
    return axis, "decreasing" if decreasing else "increasing"


def _median_axis_spacing(axis: np.ndarray, *, name: str) -> float:
    """Return one finite positive median spacing suitable for evidence."""

    with np.errstate(over="ignore", invalid="ignore"):
        spacings = np.abs(np.diff(axis))
    spacing = float(np.median(spacings))
    if not math.isfinite(spacing) or spacing <= 0.0:
        raise ValueError(f"{name} median spacing must be finite and positive")
    return spacing


def _require_uniform_source_spacing(source_axis: np.ndarray, spacing: float) -> None:
    """Enforce the sinc precondition even when no numerical interpolation is needed."""

    coordinate_scale = max(1.0, float(np.max(np.abs(source_axis))))
    tolerance: float = max(float(np.finfo(np.float64).eps) * coordinate_scale * 16.0, 1e-12)
    if not np.allclose(np.diff(source_axis), spacing, rtol=1e-8, atol=tolerance):
        raise ValueError("sinc wavenumber alignment requires a uniformly spaced source axis")


def _require_wavenumber_axis(dataset: Any, *, name: str) -> tuple[SpectralAxis, str]:
    """Require an explicit spectral axis expressed as inverse centimetres."""

    axis = dataset.feature_axis
    if not isinstance(axis, SpectralAxis) or axis.values is None:
        raise ValueError(f"{name} must provide an explicit SpectralAxis")
    semantics = axis_semantics(
        axis_class=type(axis).__name__,
        title=axis.title,
        units=axis.units,
        quantity=axis.quantity,
    )
    if semantics.quantity is not AxisQuantity.WAVENUMBER or semantics.units != "cm-1":
        raise ValueError(f"{name} axis must declare absolute wavenumber in cm-1")
    return axis, "cm-1"


def _sinc_interpolation_plan(
    source_axis: np.ndarray,
    target_axis: np.ndarray,
    *,
    spacing: float,
) -> tuple[_SincInterpolationTerm, ...]:
    """Build exact local sinc weights once for every target coordinate."""

    terms: list[_SincInterpolationTerm] = []
    radius = _SINC_KERNEL_HALF_WIDTH * spacing
    for coordinate in target_axis:
        # The source grid is tolerance-uniform rather than algebraically exact,
        # so arithmetic index rounding is not authoritative. Search exact
        # coordinates, widen by one position for boundary rounding, and then
        # reapply the original distance mask before computing weights.
        left = max(0, int(np.searchsorted(source_axis, coordinate - radius, side="left")) - 1)
        right = min(source_axis.size, int(np.searchsorted(source_axis, coordinate + radius, side="right")) + 1)
        candidate_indices = np.arange(left, right, dtype=np.intp)
        distance = coordinate - source_axis[candidate_indices]
        mask = np.abs(distance) <= radius
        indices = candidate_indices[mask]
        weights = np.sinc(distance[mask] / spacing)
        weight_sum = float(weights.sum())
        if not math.isfinite(weight_sum) or abs(weight_sum) <= 1e-12:
            raise ValueError("sinc wavenumber alignment produced an undefined local weight sum")
        terms.append((indices, weights, weight_sum))
    return tuple(terms)


def _apply_sinc_interpolation_plan(
    matrix: np.ndarray,
    plan: tuple[_SincInterpolationTerm, ...],
) -> np.ndarray:
    """Apply one precomputed interpolation plan to every spectrum."""

    output = np.empty((matrix.shape[0], len(plan)), dtype=np.float64)
    for index, (source_indices, weights, weight_sum) in enumerate(plan):
        output[:, index] = (matrix[:, source_indices] @ weights) / weight_sum
    return output


def _sinc_interpolate_row(
    source_axis: np.ndarray,
    values: np.ndarray,
    target_axis: np.ndarray,
    *,
    spacing: float,
) -> np.ndarray:
    """Evaluate a bounded normalized-sinc interpolant on one row."""

    plan = _sinc_interpolation_plan(source_axis, target_axis, spacing=spacing)
    return _apply_sinc_interpolation_plan(np.asarray(values, dtype=np.float64).reshape(1, -1), plan)[0]


def _wavenumber_align_dispatch(
    data: np.ndarray,
    source_coordinates: np.ndarray,
    reference_coordinates: np.ndarray,
    *,
    method: str,
    extrapolation: str,
) -> tuple[np.ndarray, dict[str, object]]:
    """Interpolate finite spectra onto one explicit, in-range reference grid."""

    parameters = _canonical_wavenumber_align_parameters({"method": method, "extrapolation": extrapolation})
    resolved_method = cast(str, parameters["method"])
    source_axis, source_direction = _validated_axis(source_coordinates, name="source axis")
    reference_axis, reference_direction = _validated_axis(reference_coordinates, name="reference axis")
    matrix = np.asarray(data, dtype=np.float64)
    if matrix.ndim == 1:
        matrix = matrix.reshape(1, -1)
    if matrix.ndim != 2 or matrix.shape[0] < 1 or matrix.shape[1] != source_axis.size:
        raise ValueError("wavenumber-align data must be a non-empty spectra matrix matching the source axis")
    if not np.isfinite(matrix).all():
        raise ValueError("wavenumber-align input spectra must contain only finite values")
    if float(reference_axis.min()) < float(source_axis.min()) or float(reference_axis.max()) > float(source_axis.max()):
        raise ValueError("reference wavenumber grid extends outside the source spectral coverage")

    source_ascending = source_axis if source_direction == "increasing" else source_axis[::-1]
    data_ascending = matrix if source_direction == "increasing" else matrix[:, ::-1]
    source_spacing = _median_axis_spacing(source_axis, name="source axis")
    reference_spacing = _median_axis_spacing(reference_axis, name="reference axis")
    with np.errstate(over="ignore", invalid="ignore"):
        spacing_ratio = float(reference_spacing / source_spacing)
    if not math.isfinite(spacing_ratio) or spacing_ratio <= 0.0:
        raise ValueError("reference-to-source spacing ratio must be finite and positive")
    upsampled = spacing_ratio < 1.0
    upsampling_factor = float(source_spacing / reference_spacing) if upsampled else 1.0
    if not math.isfinite(upsampling_factor):
        raise ValueError("wavenumber-align upsampling factor must be finitely representable")
    if resolved_method == "sinc":
        _require_uniform_source_spacing(source_ascending, source_spacing)
    aligned = np.empty((matrix.shape[0], reference_axis.size), dtype=np.float64)
    identical_grid = bool(np.array_equal(source_axis, reference_axis))
    if identical_grid:
        aligned[:] = matrix
    else:
        if resolved_method == "sinc":
            plan = _sinc_interpolation_plan(
                source_ascending,
                reference_axis,
                spacing=source_spacing,
            )
            aligned[:] = _apply_sinc_interpolation_plan(data_ascending, plan)
        else:
            for sample_index, spectrum in enumerate(data_ascending):
                if resolved_method == "linear":
                    aligned[sample_index] = np.interp(reference_axis, source_ascending, spectrum)
                else:
                    aligned[sample_index] = PchipInterpolator(
                        source_ascending,
                        spectrum,
                        extrapolate=False,
                    )(reference_axis)
    if not np.isfinite(aligned).all():
        raise ValueError("wavenumber alignment produced a non-finite result")

    diagnostics: dict[str, object] = {
        "method": resolved_method,
        "extrapolation": "reject",
        "source_direction": source_direction,
        "reference_direction": reference_direction,
        "source_features": int(source_axis.size),
        "reference_features": int(reference_axis.size),
        "source_coordinate_minimum": float(source_axis.min()),
        "source_coordinate_maximum": float(source_axis.max()),
        "reference_coordinate_minimum": float(reference_axis.min()),
        "reference_coordinate_maximum": float(reference_axis.max()),
        "source_spacing_median": source_spacing,
        "reference_spacing_median": reference_spacing,
        "reference_to_source_spacing_ratio": spacing_ratio,
        "upsampled": upsampled,
        "upsampling_factor": upsampling_factor,
        "adds_measured_resolution": False,
        "resolution_note": (
            "Interpolation onto a finer grid does not add measured spectral resolution." if upsampled else None
        ),
        "reference_grid_sha256": hashlib.sha256(np.asarray(reference_axis, dtype="<f8").tobytes()).hexdigest(),
        "identical_grid": identical_grid,
        "sinc_kernel_half_width": _SINC_KERNEL_HALF_WIDTH if resolved_method == "sinc" else None,
    }
    return aligned, diagnostics


def _wavenumber_align_dataset_dispatch(
    source: Any,
    reference: Any,
    *,
    method: str,
    extrapolation: str,
) -> tuple[np.ndarray, dict[str, object]]:
    """Bind explicit reference-grid and unit semantics before interpolation."""

    source_axis, source_units = _require_wavenumber_axis(source, name="source spectra")
    reference_axis, reference_units = _require_wavenumber_axis(reference, name="reference grid")
    aligned, diagnostics = _wavenumber_align_dispatch(
        to_numpy_2d(source, name="spectra", dtype=np.float64),
        np.asarray(source_axis.values, dtype=np.float64),
        np.asarray(reference_axis.values, dtype=np.float64),
        method=method,
        extrapolation=extrapolation,
    )
    diagnostics["source_axis_units"] = source_units
    diagnostics["reference_axis_units"] = reference_units
    diagnostics["source_axis_quantity"] = AxisQuantity.WAVENUMBER.value
    diagnostics["reference_axis_quantity"] = AxisQuantity.WAVENUMBER.value
    diagnostics["reference_axis_title"] = reference_axis.title or "unavailable"
    return aligned, diagnostics


def _build_wavenumber_align_result(
    aligned: np.ndarray,
    source: Any,
    reference: Any,
    parameters: dict[str, object],
    diagnostics: dict[str, object],
    *,
    node_id: str | None = None,
):
    """Wrap aligned values with source observations and reference features."""

    reference_axis, _ = _require_wavenumber_axis(reference, name="reference grid")
    result = build_dataset_like(aligned, source, units=source.units)
    result.feature_axis = reference_axis
    impact = {
        "schema_version": "spectrasherpa-preprocess-wavenumber-align-impact/1",
        **diagnostics,
    }
    add_processing_step(
        result,
        "preprocess.wavenumber_align",
        parameters,
        node_id=node_id,
        input_shape=source.shape,
        impact=impact,
    )
    result.meta["wavenumber_align_diagnostics"] = diagnostics
    supervision_binding.rebind_sample_preserving_supervision(source, result)
    return result


@register_node
class WavenumberAlignNode(Node):
    """Interpolate source spectra onto an explicitly connected reference grid."""

    metadata = NodeMetadata(
        node_type="preprocess.wavenumber_align",
        category="preprocessing",
        label="Wavenumber Align",
        description=(
            "Interpolate source spectra onto the connected reference spectrum's cm-1 grid. "
            "The reference grid must remain inside the measured source coverage. A finer "
            "output grid is interpolation only and does not add measured spectral resolution."
        ),
        parameters=[
            NodeParameter(
                name="method",
                label="Interpolation Method",
                param_type="select",
                default="pchip",
                options=["pchip", "linear", "sinc"],
                description=(
                    "Exact interpolation rule; sinc requires a uniform source grid. "
                    "Upsampling never implies additional measured resolution."
                ),
                required=True,
            ),
            NodeParameter(
                name="extrapolation",
                label="Extrapolation Policy",
                param_type="select",
                default="reject",
                options=["reject"],
                description="Fail when the reference grid extends beyond measured source coverage.",
                required=True,
            ),
        ],
        input_types=["SpectralDataset"],
        input_ports=[
            PortMetadata(
                name="spectra",
                type_ref="spectrasherpa://types/SpectralDataset/1.0",
                required=True,
                label="Source Spectra",
                description="Finite spectra to interpolate, with an explicit cm-1 SpectralAxis.",
                accepted_data_roles=["X_spectra"],
            ),
            PortMetadata(
                name="reference",
                type_ref="spectrasherpa://types/SpectralDataset/1.0",
                required=True,
                label="Reference Grid",
                description="Dataset whose explicit cm-1 feature grid defines the output coordinates.",
                accepted_data_roles=["X_spectra"],
            ),
        ],
        output_ports=[
            PortMetadata(
                name="default",
                type_ref="spectrasherpa://types/SpectralDataset/1.0",
                required=True,
                label="Aligned Spectra",
                description="Source observations interpolated onto the exact connected reference grid.",
                accepted_data_roles=["X_spectra"],
            )
        ],
        output_type="SpectralDataset",
        policy=NodePolicy(),
        canonical_parameter_validator=_canonical_wavenumber_align_parameters,
    )

    async def execute(self, spectra: Any = None, reference: Any = None, **kwargs: Any) -> NodeResult:
        del kwargs
        source = coerce_to_sherpa(spectra, input_name="spectra")
        reference_dataset = coerce_to_sherpa(reference, input_name="reference")
        parameters = self._resolve_params()
        aligned, diagnostics = _wavenumber_align_dataset_dispatch(
            source,
            reference_dataset,
            **parameters,
        )
        result = _build_wavenumber_align_result(
            aligned,
            source,
            reference_dataset,
            parameters,
            diagnostics,
            node_id=self.node_id,
        )
        return NodeResult(outputs={"default": result}, diagnostics=diagnostics)

    def supports_python_export(self) -> bool:
        return True

    def generate_python(self, inputs, indent="    ", use_scp=True):
        del use_scp
        source = inputs.get("spectra", "input_data")
        reference = inputs.get("reference", "reference_data")
        parameters = self._resolve_params()
        return [
            f"{indent}# --- Canonical Wavenumber Alignment ({self.node_id}) ---",
            f"{indent}from spectra_sherpa.app.services.dag.nodes.preprocessing.wavenumber_align_node "
            "import _build_wavenumber_align_result, _wavenumber_align_dataset_dispatch",
            f"{indent}_aligned, _align_diagnostics = _wavenumber_align_dataset_dispatch("
            f"{source}, {reference}, **{parameters!r})",
            f"{indent}results[{self.node_id!r}] = _build_wavenumber_align_result("
            f"_aligned, {source}, {reference}, {parameters!r}, _align_diagnostics, node_id={self.node_id!r})",
        ]


bind_stable_execution_contract(
    WavenumberAlignNode,
    runtime_family=RuntimeFamily.SHERPA_NATIVE,
    lifecycle_kind=LifecycleKind.STATELESS_TRANSFORM,
    implementation_id="spectrasherpa.preprocess.wavenumber_align",
    implementation_version="1.0.1",
    required_worker_capabilities=(WorkerCapability.READ_DATASET,),
    managed_optimization_eligibility=(ManagedOptimizationEligibility.LOCAL,),
    sample_effect="preserves_samples",
    feature_effect="transforms_features",
    axis_effect="changes_axis",
    unit_effect="requires_compatible_units",
    resource_hints={"timeout_seconds": 60, "cpu_seconds": 60, "memory_bytes": 1_073_741_824},
    license_id="Apache-2.0",
    help_reference="docs/nodes/preprocessing.md",
    implementation_modules=(
        supervision_binding,
        _shared,
        dag_io_contracts,
        dag_meta_helpers,
        sherpa_dataset_contract,
    ),
    implementation_distributions=("numpy", "scipy"),
    runtime_requirements=(("numpy", "1.26.4"), ("scipy", "1.17.1")),
)


__all__ = [
    "WavenumberAlignNode",
    "_build_wavenumber_align_result",
    "_canonical_wavenumber_align_parameters",
    "_wavenumber_align_dataset_dispatch",
    "_wavenumber_align_dispatch",
]
