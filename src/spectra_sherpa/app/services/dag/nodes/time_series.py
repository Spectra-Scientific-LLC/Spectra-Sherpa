"""
Time series analysis nodes for batch monitoring and process control.

These nodes enable time series preprocessing and analysis for process industries,
supporting batch monitoring, drift detection, and real-time process control applications.
"""

from __future__ import annotations

from typing import Any, Dict, List

import numpy as np

from spectra_sherpa.app.lib.sherpa_dataset import SampleAxis, TargetContext
from spectra_sherpa.app.services.dag import supervision_binding
from spectra_sherpa.app.services.dag.meta_helpers import add_processing_step
from spectra_sherpa.app.services.dag.stable_execution_contract import bind_stable_execution_contract
from spectra_sherpa.execution_contract_vocabulary import (
    LifecycleKind,
    ManagedOptimizationEligibility,
    RuntimeFamily,
    WorkerCapability,
)

from ..io_contracts import build_dataset_like, coerce_to_sherpa, to_numpy_2d
from ..node_base import Node, NodeMetadata, NodeParameter, NodePolicy, PortMetadata, register_node

_DATASET_TYPE = "spectrasherpa://types/SpectralDataset/1.0"
_MOVING_AGGREGATIONS = frozenset({"none", "mean", "median", "std"})
_TREND_METHODS = frozenset({"linear", "polynomial", "difference", "moving_average"})


def _closed_integer(
    value: object,
    *,
    name: str,
    minimum: int,
    maximum: int,
) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, np.integer)):
        raise ValueError(f"{name} must be an integer")
    integer = int(value)
    if not minimum <= integer <= maximum:
        raise ValueError(f"{name} must be between {minimum} and {maximum}")
    return integer


def _canonical_moving_window_parameters(raw: dict[str, object]) -> dict[str, object]:
    """Close the exact sliding-window settings."""

    unknown = sorted(set(raw) - {"window_size", "step_size", "aggregation"})
    if unknown:
        raise ValueError(f"time_series.moving_window received unknown parameters: {', '.join(unknown)}")
    window_size = _closed_integer(
        raw.get("window_size", 10),
        name="time_series.moving_window window_size",
        minimum=2,
        maximum=100_000,
    )
    step_size = _closed_integer(
        raw.get("step_size", 1),
        name="time_series.moving_window step_size",
        minimum=1,
        maximum=100_000,
    )
    aggregation = raw.get("aggregation", "none")
    if not isinstance(aggregation, str) or aggregation not in _MOVING_AGGREGATIONS:
        raise ValueError("time_series.moving_window aggregation must be none, mean, median, or std")
    return {"window_size": window_size, "step_size": step_size, "aggregation": aggregation}


def _canonical_trend_parameters(raw: dict[str, object]) -> dict[str, object]:
    """Close the local batch-detrending settings."""

    unknown = sorted(set(raw) - {"method", "poly_order", "window_size"})
    if unknown:
        raise ValueError(f"time_series.trend_removal received unknown parameters: {', '.join(unknown)}")
    method = raw.get("method", "linear")
    if not isinstance(method, str) or method not in _TREND_METHODS:
        raise ValueError("time_series.trend_removal method must be linear, polynomial, difference, or moving_average")
    poly_order = _closed_integer(
        raw.get("poly_order", 2),
        name="time_series.trend_removal poly_order",
        minimum=1,
        maximum=10,
    )
    window_size = _closed_integer(
        raw.get("window_size", 5),
        name="time_series.trend_removal window_size",
        minimum=2,
        maximum=100_000,
    )
    return {"method": method, "poly_order": poly_order, "window_size": window_size}


def _finite_time_series(input_data: Any) -> tuple[Any, np.ndarray]:
    input_ds = coerce_to_sherpa(input_data, input_name="input_data")
    data = to_numpy_2d(input_ds, name="input_data", dtype=np.float64)
    if data.shape[0] < 2 or data.shape[1] < 1:
        raise ValueError("time-series operations require at least two samples and one feature")
    if not np.all(np.isfinite(data)):
        raise ValueError("time-series operations require finite input values")
    return input_ds, data


def build_moving_window_result(
    input_data: Any,
    *,
    parameters: dict[str, object],
    node_id: str | None = None,
) -> Any:
    """Create deterministic window-derived rows through the sole authority."""

    projected = _canonical_moving_window_parameters(parameters)
    input_ds, data = _finite_time_series(input_data)
    binding = supervision_binding.admit_attached_sample_table_supervision(input_ds)
    window_size = int(projected["window_size"])
    step_size = int(projected["step_size"])
    aggregation = str(projected["aggregation"])
    n_samples = data.shape[0]
    if window_size > n_samples:
        raise ValueError(f"Window size ({window_size}) cannot exceed number of samples ({n_samples})")

    starts = list(range(0, n_samples - window_size + 1, step_size))
    windows = np.stack([data[start : start + window_size] for start in starts], axis=0)
    if aggregation == "mean":
        output = np.mean(windows, axis=1, dtype=np.float64)
    elif aggregation == "median":
        output = np.median(windows, axis=1)
    elif aggregation == "std":
        output = np.std(windows, axis=1, ddof=0, dtype=np.float64)
    else:
        output = windows.reshape(-1, data.shape[1])

    result = build_dataset_like(output, input_ds)
    # Every output row represents a window or a member of a repeated window,
    # never the original one-to-one sample identity. Give those generated rows
    # explicit identities instead of accidentally preserving source labels.
    if aggregation == "none":
        labels = [
            f"window-{window_index:04d}:member-{member_index:04d}:source-{start + member_index:06d}"
            for window_index, start in enumerate(starts)
            for member_index in range(window_size)
        ]
    else:
        labels = [
            f"window-{window_index:04d}:source-{start:06d}-{start + window_size:06d}"
            for window_index, start in enumerate(starts)
        ]
    result.sample_axis = SampleAxis(labels=labels, title="Generated time-series windows")
    result.target = None
    result.target_context = TargetContext()
    result.meta.pop("supervision_binding", None)
    result.meta["time_series_windows"] = {
        "window_size": window_size,
        "step_size": step_size,
        "aggregation": aggregation,
        "window_intervals": [[start, start + window_size] for start in starts],
        "flattening_order": "window_major" if aggregation == "none" else None,
        "source_supervision_binding_sha256": binding.digest if binding is not None else None,
        "supervision_status": "requires_new_sample_binding",
    }
    add_processing_step(
        result,
        "time_series.moving_window",
        projected,
        node_id=node_id,
        input_shape=input_ds.shape,
    )
    return result


@register_node
class MovingWindowNode(Node):
    """
    Moving Window node.

    Slides a window over time series spectral data to create windowed segments.
    Foundation for batch monitoring and process control applications.

    Enables analysis of spectral evolution over time by creating overlapping
    or non-overlapping windows of consecutive spectra.
    """

    metadata = NodeMetadata(
        policy=NodePolicy(
            safe_for_auto_apply=True,
            requires_human_review=False,
            data_egress_risk="none",
            offload_to_pool=True,
        ),
        node_type="time_series.moving_window",
        category="preprocessing",
        label="Moving Window",
        description="Slide window over time series for batch analysis",
        parameters=[
            NodeParameter(
                name="window_size",
                label="Window Size",
                param_type="number",
                default=10,
                min_value=2,
                max_value=100000,
                max_value_reason="Bounds window metadata and worker memory on local batch analyses.",
                step=1,
                description="Number of consecutive spectra in each window",
                required=True,
            ),
            NodeParameter(
                name="step_size",
                label="Step Size",
                param_type="number",
                default=1,
                min_value=1,
                max_value=100000,
                max_value_reason="Bounds window traversal and worker memory on local batch analyses.",
                step=1,
                description="Number of spectra to move between windows (1=maximum overlap)",
                required=True,
            ),
            NodeParameter(
                name="aggregation",
                label="Aggregation Method",
                param_type="select",
                default="none",
                options=["none", "mean", "median", "std"],
                description="How to aggregate spectra within each window",
                required=False,
            ),
        ],
        input_types=["SherpaDataset"],
        output_type="SherpaDataset",
        input_ports=[
            PortMetadata(
                name="default",
                type_ref=_DATASET_TYPE,
                required=True,
                label="Input Data",
                description="Input data to process",
            ),
        ],
        output_ports=[
            PortMetadata(
                name="default",
                type_ref=_DATASET_TYPE,
                required=True,
                label="Windowed Data",
                description="Window-derived spectra with explicit interval provenance",
            ),
        ],
        canonical_parameter_validator=_canonical_moving_window_parameters,
    )

    async def execute(self, input_data: Any) -> Any:
        """
        Execute moving window segmentation.

        Args:
            input_data: Any containing time series spectral data

        Returns:
            Dataset with windowed data
        """
        parameters = self.metadata.canonicalize_parameters(self._resolve_params())
        return build_moving_window_result(input_data, parameters=parameters, node_id=self.node_id)

    def generate_python(
        self,
        inputs: Dict[str, str],
        indent: str = "    ",
        use_scp: bool = True,
    ) -> List[str]:
        input_expr = inputs.get("default", next(iter(inputs.values()), "input_data"))
        parameters = self.metadata.canonicalize_parameters(self._resolve_params())
        return [
            f"{indent}# --- Moving window ({self.node_id}) ---",
            (f"{indent}from spectra_sherpa.app.services.dag.nodes.time_series import build_moving_window_result"),
            f"{indent}results[{self.node_id!r}] = build_moving_window_result(",
            f"{indent}    {input_expr}, parameters={parameters!r}, node_id={self.node_id!r},",
            f"{indent})",
        ]


def _trend_removal_transform(
    data: np.ndarray,
    method: str = "linear",
    poly_order: int = 2,
    window_size: int = 5,
) -> np.ndarray:
    """Apply a closed batch-local trend operator along the sample/time axis."""

    projected = _canonical_trend_parameters({"method": method, "poly_order": poly_order, "window_size": window_size})
    matrix = np.asarray(data, dtype=np.float64)
    if matrix.ndim != 2 or matrix.shape[0] < 2 or matrix.shape[1] < 1:
        raise ValueError("trend removal requires at least two samples and one feature")
    if not np.all(np.isfinite(matrix)):
        raise ValueError("trend removal requires finite input values")
    n_samples = data.shape[0]
    detrended = np.zeros_like(matrix)

    if method in {"linear", "polynomial"}:
        degree = 1 if method == "linear" else int(projected["poly_order"])
        if degree >= n_samples:
            raise ValueError("trend-removal polynomial order must be smaller than the sample count")
        # Centered coordinates improve conditioning without changing the
        # least-squares polynomial subspace.
        time_coordinate = np.linspace(-1.0, 1.0, n_samples, dtype=np.float64)
        design = np.vander(time_coordinate, N=degree + 1, increasing=True)
        coefficients, _, rank, _ = np.linalg.lstsq(design, matrix, rcond=None)
        if rank != degree + 1:
            raise ValueError("trend-removal polynomial design is rank deficient")
        detrended = matrix - design @ coefficients

    elif method == "difference":
        # Preserve sample cardinality while marking the undefined leading
        # first difference as zero; never copy an undifferenced spectrum into
        # a result labeled as detrended.
        detrended[1:] = np.diff(matrix, axis=0)

    elif method == "moving_average":
        from scipy.ndimage import uniform_filter1d

        width = int(projected["window_size"])
        if width > n_samples:
            raise ValueError("trend-removal moving-average window cannot exceed the sample count")
        baseline = uniform_filter1d(matrix, width, axis=0, mode="nearest")
        detrended = matrix - baseline

    return detrended


def build_trend_removal_result(
    input_data: Any,
    *,
    parameters: dict[str, object],
    node_id: str | None = None,
) -> Any:
    """Build one metadata-preserving local detrending result."""

    projected = _canonical_trend_parameters(parameters)
    input_ds, data = _finite_time_series(input_data)
    output = _trend_removal_transform(data, **projected)
    result = build_dataset_like(output, input_ds)
    result.meta["time_series_trend_removal"] = {
        **projected,
        "axis": "sample_time",
        "scope": "current_batch_local_only",
        "difference_boundary": "leading_zero" if projected["method"] == "difference" else None,
    }
    add_processing_step(
        result,
        "time_series.trend_removal",
        projected,
        node_id=node_id,
        input_shape=input_ds.shape,
    )
    supervision_binding.rebind_sample_preserving_supervision(input_ds, result)
    return result


@register_node
class TrendRemovalNode(Node):
    """
    Trend Removal node.

    Removes systematic trends from time series spectral data.
    Supports detrending, differencing, and baseline drift correction
    for process control applications.

    Essential preprocessing for detecting process changes and drift
    in continuous monitoring scenarios.
    """

    metadata = NodeMetadata(
        policy=NodePolicy(
            safe_for_auto_apply=True,
            requires_human_review=False,
            data_egress_risk="none",
            offload_to_pool=True,
        ),
        node_type="time_series.trend_removal",
        category="preprocessing",
        label="Trend Removal",
        description="Remove systematic trends and drift from time series data",
        parameters=[
            NodeParameter(
                name="method",
                label="Detrending Method",
                param_type="select",
                default="linear",
                options=["linear", "polynomial", "difference", "moving_average"],
                description="Method for trend removal",
                required=True,
            ),
            NodeParameter(
                name="poly_order",
                label="Polynomial Order",
                param_type="number",
                default=2,
                min_value=1,
                max_value=10,
                max_value_reason="Bounds polynomial conditioning and local worker cost.",
                step=1,
                description="Polynomial order (for polynomial method)",
                required=False,
            ),
            NodeParameter(
                name="window_size",
                label="MA Window Size",
                param_type="number",
                default=5,
                min_value=2,
                max_value=100000,
                max_value_reason="Bounds moving-average worker memory and makes the admitted domain explicit.",
                step=1,
                description="Window size for moving average baseline",
                required=False,
            ),
        ],
        input_types=["SherpaDataset"],
        output_type="SherpaDataset",
        input_ports=[
            PortMetadata(
                name="default",
                type_ref=_DATASET_TYPE,
                required=True,
                label="Input Data",
                description="Input data to process",
            ),
        ],
        output_ports=[
            PortMetadata(
                name="default",
                type_ref=_DATASET_TYPE,
                required=True,
                label="Detrended Data",
                description="Spectra detrended along the current sample/time axis",
            ),
        ],
        canonical_parameter_validator=_canonical_trend_parameters,
    )

    async def execute(self, input_data: Any) -> Any:
        parameters = self.metadata.canonicalize_parameters(self._resolve_params())
        return build_trend_removal_result(input_data, parameters=parameters, node_id=self.node_id)

    def generate_python(
        self,
        inputs: Dict[str, str],
        indent: str = "    ",
        use_scp: bool = True,
    ) -> List[str]:
        input_expr = inputs.get("default", next(iter(inputs.values()), "input_data"))
        parameters = self.metadata.canonicalize_parameters(self._resolve_params())
        return [
            f"{indent}# --- Trend removal ({self.node_id}) ---",
            (f"{indent}from spectra_sherpa.app.services.dag.nodes.time_series import build_trend_removal_result"),
            f"{indent}results[{self.node_id!r}] = build_trend_removal_result(",
            f"{indent}    {input_expr}, parameters={parameters!r}, node_id={self.node_id!r},",
            f"{indent})",
        ]


bind_stable_execution_contract(
    MovingWindowNode,
    runtime_family=RuntimeFamily.SHERPA_NATIVE,
    lifecycle_kind=LifecycleKind.STATELESS_TRANSFORM,
    implementation_id="spectrasherpa.time_series.moving_window",
    implementation_version="1.0.1",
    implementation_modules=(supervision_binding,),
    required_worker_capabilities=(WorkerCapability.READ_DATASET,),
    managed_optimization_eligibility=(ManagedOptimizationEligibility.LOCAL,),
    sample_effect="generates_samples",
    feature_effect="preserves_features",
    axis_effect="preserves_axis",
    unit_effect="preserves_units",
    resource_hints={"timeout_seconds": 60, "cpu_seconds": 60, "memory_bytes": 1_073_741_824},
    license_id="Apache-2.0",
    help_reference="docs/nodes/preprocessing.md",
    implementation_distributions=("numpy", "scipy"),
    runtime_requirements=(("numpy", "1.26.4"), ("scipy", "1.17.1")),
    citations=("Zeileis and Grothendieck, R News 5/1 (2005) 1-4, zoo::rollapply",),
)


bind_stable_execution_contract(
    TrendRemovalNode,
    runtime_family=RuntimeFamily.SHERPA_NATIVE,
    lifecycle_kind=LifecycleKind.STATELESS_TRANSFORM,
    implementation_id="spectrasherpa.time_series.trend_removal",
    implementation_version="1.0.1",
    implementation_modules=(supervision_binding,),
    required_worker_capabilities=(WorkerCapability.READ_DATASET,),
    managed_optimization_eligibility=(ManagedOptimizationEligibility.LOCAL,),
    sample_effect="preserves_samples",
    feature_effect="preserves_features",
    axis_effect="preserves_axis",
    unit_effect="preserves_units",
    resource_hints={"timeout_seconds": 60, "cpu_seconds": 60, "memory_bytes": 1_073_741_824},
    license_id="Apache-2.0",
    help_reference="docs/nodes/preprocessing.md",
    implementation_distributions=("numpy", "scipy"),
    runtime_requirements=(("numpy", "1.26.4"), ("scipy", "1.17.1")),
    citations=("Box, Jenkins, Reinsel, and Ljung, Time Series Analysis, 5th ed. (2015)",),
)


__all__ = [
    "MovingWindowNode",
    "TrendRemovalNode",
    "_canonical_moving_window_parameters",
    "_canonical_trend_parameters",
    "_trend_removal_transform",
    "build_moving_window_result",
    "build_trend_removal_result",
]
