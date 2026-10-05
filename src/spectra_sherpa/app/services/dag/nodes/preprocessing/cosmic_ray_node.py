"""Canonical Hampel cosmic-ray correction for spectral matrices."""

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

_MAD_NORMAL_CONSISTENCY = 1.4826
_COSMIC_RAY_WORKING_SET_BYTES = 32 * 1024 * 1024
_COSMIC_RAY_BYTES_PER_WINDOW_VALUE = 24


def _cosmic_ray_block_shape(*, samples: int, features: int, window: int) -> tuple[int, int]:
    """Return sample/window block sizes under the Hampel working-set budget."""

    interior_features = features - window + 1
    maximum_window_cells = max(
        1,
        _COSMIC_RAY_WORKING_SET_BYTES // (window * _COSMIC_RAY_BYTES_PER_WINDOW_VALUE),
    )
    window_block = min(interior_features, maximum_window_cells)
    sample_block = min(samples, max(1, maximum_window_cells // window_block))
    return sample_block, window_block


def _canonical_cosmic_ray_parameters(parameters: dict[str, object]) -> dict[str, object]:
    """Return one exact, bounded Hampel-filter parameter payload."""

    window = parameters["window"]
    zscore = parameters["zscore"]
    if isinstance(window, bool) or not isinstance(window, int) or not 3 <= window <= 101 or window % 2 == 0:
        raise ValueError("cosmic-ray window must be an odd integer from 3 through 101")
    if (
        isinstance(zscore, bool)
        or not isinstance(zscore, (int, float))
        or not math.isfinite(zscore)
        or float(zscore) < 1.5
    ):
        raise ValueError("cosmic-ray zscore must be a finite number greater than or equal to 1.5")
    return {"window": window, "zscore": float(zscore)}


def _cosmic_ray_dispatch(
    data: np.ndarray,
    *,
    window: int,
    zscore: float,
) -> tuple[np.ndarray, dict[str, object]]:
    """Replace Hampel-identified spikes simultaneously, never sequentially."""

    parameters = _canonical_cosmic_ray_parameters({"window": window, "zscore": zscore})
    resolved_window = cast(int, parameters["window"])
    resolved_zscore = cast(float, parameters["zscore"])
    matrix = np.asarray(data, dtype=np.float64)
    was_vector = matrix.ndim == 1
    if was_vector:
        matrix = matrix.reshape(1, -1)
    if matrix.ndim != 2 or matrix.shape[0] < 1:
        raise ValueError("cosmic-ray input must contain at least one spectrum")
    if matrix.shape[1] < resolved_window:
        raise ValueError("cosmic-ray window may not exceed the input feature count")
    if not np.isfinite(matrix).all():
        raise ValueError("cosmic-ray input must contain only finite values")

    half_window = resolved_window // 2
    corrected = np.array(matrix, dtype=np.float64, copy=True)
    corrected_mask = np.zeros(matrix.shape, dtype=bool)
    replacement_values = np.zeros(matrix.shape, dtype=np.float64)
    zero_mad_windows = 0

    # Statistics are always calculated from immutable input windows. Applying
    # a replacement cannot influence the detection or replacement of a later
    # point in the same spectrum. Two-dimensional sample/window blocks keep the
    # estimated vectorized median/deviation workspace under a fixed budget even
    # when one spectrum contains an exceptionally large number of features.
    sample_block, window_block = _cosmic_ray_block_shape(
        samples=matrix.shape[0],
        features=matrix.shape[1],
        window=resolved_window,
    )
    interior_features = matrix.shape[1] - resolved_window + 1
    for sample_start in range(0, matrix.shape[0], sample_block):
        sample_stop = min(matrix.shape[0], sample_start + sample_block)
        for window_start in range(0, interior_features, window_block):
            window_stop = min(interior_features, window_start + window_block)
            source_stop = window_stop + resolved_window - 1
            windows = np.lib.stride_tricks.sliding_window_view(
                matrix[sample_start:sample_stop, window_start:source_stop],
                window_shape=resolved_window,
                axis=1,
            )
            medians = np.median(windows, axis=-1)
            with np.errstate(over="ignore", invalid="ignore"):
                deviations = np.abs(windows - medians[..., np.newaxis])
            if not np.isfinite(deviations).all():
                raise ValueError("cosmic-ray local deviation is not finitely representable")
            mads = np.median(deviations, axis=-1)
            zero_mad_windows += int(np.count_nonzero(mads == 0.0))
            neighborhood_maxima = np.max(np.abs(windows), axis=-1)
            numerical_floors = np.finfo(np.float64).eps * np.maximum.reduce(
                (
                    np.ones_like(medians),
                    np.abs(medians),
                    neighborhood_maxima,
                )
            )
            robust_scales = _MAD_NORMAL_CONSISTENCY * mads
            if not np.isfinite(robust_scales).all():
                raise ValueError("cosmic-ray robust scale is not finitely representable")
            scales = np.maximum(robust_scales, numerical_floors)
            feature_start = window_start + half_window
            feature_stop = window_stop + half_window
            local_mask = (
                np.abs(matrix[sample_start:sample_stop, feature_start:feature_stop] - medians)
                > resolved_zscore * scales
            )
            corrected_mask[sample_start:sample_stop, feature_start:feature_stop] = local_mask
            replacement_values[sample_start:sample_stop, feature_start:feature_stop] = medians

    corrected[corrected_mask] = replacement_values[corrected_mask]
    with np.errstate(over="ignore", invalid="ignore"):
        corrections = np.abs(matrix[corrected_mask] - corrected[corrected_mask])
    if not np.isfinite(corrections).all():
        raise ValueError("cosmic-ray correction magnitude is not finitely representable")
    corrected_count = int(corrected_mask.sum())
    corrected_spectra = int(np.any(corrected_mask, axis=1).sum())
    diagnostics: dict[str, object] = {
        "method": "hampel_local_median_mad",
        "window": resolved_window,
        "zscore": resolved_zscore,
        "mad_normal_consistency": _MAD_NORMAL_CONSISTENCY,
        "simultaneous_replacement": True,
        "edge_points_unassessed_per_spectrum": 2 * half_window,
        "zero_mad_windows": zero_mad_windows,
        "corrected_values": corrected_count,
        "corrected_fraction": float(corrected_count / matrix.size),
        "spectra_with_corrections": corrected_spectra,
        "maximum_absolute_correction": float(corrections.max()) if corrected_count else 0.0,
        "mean_absolute_correction": finite_nonnegative_mean(corrections),
    }
    return (corrected[0] if was_vector else corrected), diagnostics


def _build_cosmic_ray_result(
    corrected: np.ndarray,
    source: Any,
    parameters: dict[str, object],
    diagnostics: dict[str, object],
    *,
    node_id: str | None = None,
):
    """Wrap the correction with identical provenance on every public path."""

    result = build_dataset_like(corrected, source, units=source.units)
    diagnostics["value_units"] = source.units or "unavailable"
    impact = {
        "schema_version": "spectrasherpa-preprocess-cosmic-ray-impact/1",
        **diagnostics,
    }
    add_processing_step(
        result,
        "preprocess.cosmic_ray",
        parameters,
        node_id=node_id,
        input_shape=source.shape,
        impact=impact,
    )
    result.meta["cosmic_ray_diagnostics"] = diagnostics
    supervision_binding.rebind_sample_preserving_supervision(source, result)
    return result


@register_node
class CosmicRayRemovalNode(Node):
    """Replace isolated spike-like outliers with their local median."""

    metadata = NodeMetadata(
        node_type="preprocess.cosmic_ray",
        category="preprocessing",
        label="Cosmic Ray Removal",
        description=(
            "Identify isolated spikes with a local Hampel rule and replace all "
            "flagged points simultaneously with their pre-correction local median. "
            "The first and last (window - 1) / 2 features are preserved unassessed "
            "because they do not have a complete centered neighborhood."
        ),
        parameters=[
            NodeParameter(
                name="window",
                label="Window Size",
                param_type="number",
                default=7,
                min_value=3,
                max_value=101,
                max_value_reason=(
                    "Bounds the per-spectrum neighborhood work while covering a much "
                    "wider region than an isolated detector spike."
                ),
                step=2,
                description=(
                    "Odd number of spectral features in each local Hampel neighborhood. "
                    "The half-window at each spectrum edge is preserved unassessed."
                ),
                required=True,
            ),
            NodeParameter(
                name="zscore",
                label="MAD Threshold",
                param_type="number",
                default=3.0,
                min_value=1.5,
                step=0.5,
                description="Threshold in normal-consistent local MAD scale units.",
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
                description="Finite spectra with at least as many features as the selected window.",
                accepted_data_roles=["X_spectra"],
            )
        ],
        output_ports=[
            PortMetadata(
                name="default",
                type_ref="spectrasherpa://types/SpectralDataset/1.0",
                required=True,
                label="Cosmic-ray-corrected Spectra",
                description="Spectra with samples, feature axis, and value units preserved.",
                accepted_data_roles=["X_spectra"],
            )
        ],
        output_type="SpectralDataset",
        policy=NodePolicy(),
        canonical_parameter_validator=_canonical_cosmic_ray_parameters,
    )

    async def execute(self, input_data: Any = None, default: Any = None, **kwargs: Any) -> NodeResult:
        del kwargs
        source = coerce_to_sherpa(input_data if input_data is not None else default, input_name="input_data")
        parameters = self._resolve_params()
        corrected, diagnostics = _cosmic_ray_dispatch(to_numpy_2d(source, name="input_data"), **parameters)
        result = _build_cosmic_ray_result(
            corrected,
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
            f"{indent}# --- Canonical Cosmic Ray Removal ({self.node_id}) ---",
            f"{indent}from spectra_sherpa.app.services.dag.nodes.preprocessing.cosmic_ray_node "
            "import _build_cosmic_ray_result, _cosmic_ray_dispatch",
            f"{indent}_cosmic_corrected, _cosmic_diagnostics = _cosmic_ray_dispatch("
            f"np.asarray({source}.data, dtype=np.float64), **{parameters!r})",
            f"{indent}results[{self.node_id!r}] = _build_cosmic_ray_result("
            f"_cosmic_corrected, {source}, {parameters!r}, _cosmic_diagnostics, node_id={self.node_id!r})",
        ]


bind_stable_execution_contract(
    CosmicRayRemovalNode,
    runtime_family=RuntimeFamily.SHERPA_NATIVE,
    lifecycle_kind=LifecycleKind.STATELESS_TRANSFORM,
    implementation_id="spectrasherpa.preprocess.cosmic_ray",
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
    citations=(
        "Hampel, The influence curve and its role in robust estimation (1974)",
        "Rousseeuw and Croux, Alternatives to the median absolute deviation (1993)",
    ),
)


__all__ = [
    "CosmicRayRemovalNode",
    "_build_cosmic_ray_result",
    "_canonical_cosmic_ray_parameters",
    "_cosmic_ray_block_shape",
    "_cosmic_ray_dispatch",
]
