"""
Time series analysis nodes for batch monitoring and process control.

These nodes enable time series preprocessing and analysis for process industries,
supporting batch monitoring, drift detection, and real-time process control applications.
"""

from __future__ import annotations

import logging
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)
from spectra_sherpa.app.services.dag.meta_helpers import add_processing_step

from ..io_contracts import build_dataset_like, coerce_to_sherpa, to_numpy_2d
from ..node_base import Node, NodeMetadata, NodeParameter, PortMetadata, register_node
from ..spec_nodes import TransformSpec, TransformSpecNode


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
        input_types=["NDDataset"],
        output_type="NDDataset",
        input_ports=[
            PortMetadata(
                name="default",
                type_ref="spectrasherpa://types/SpectralDataset/1.0",
                required=True,
                label="Input Data",
                description="Input data to process",
            ),
        ],
    )

    async def execute(self, input_data: Any) -> Any:
        """
        Execute moving window segmentation.

        Args:
            input_data: Any containing time series spectral data

        Returns:
            Dataset with windowed data
        """
        window_size = self.parameters.get("window_size", 10)
        step_size = self.parameters.get("step_size", 1)
        aggregation = self.parameters.get("aggregation", "none")

        input_ds = coerce_to_sherpa(input_data, input_name="input_data")
        data = to_numpy_2d(input_ds, name="input_data", dtype=np.float64)
        n_samples, n_features = data.shape
        input_shape = input_ds.shape

        if window_size > n_samples:
            raise ValueError(f"Window size ({window_size}) cannot exceed number of samples ({n_samples})")

        # Create windows
        windows = []
        window_indices = []

        for i in range(0, n_samples - window_size + 1, step_size):
            window = data[i : i + window_size]
            windows.append(window)
            window_indices.append((i, i + window_size))

        n_windows = len(windows)
        logger.debug(f"[Moving Window] Created {n_windows} windows of size {window_size} with step {step_size}")

        # Aggregate if requested
        if aggregation == "mean":
            windowed_data = np.array([np.mean(window, axis=0) for window in windows])
        elif aggregation == "median":
            windowed_data = np.array([np.median(window, axis=0) for window in windows])
        elif aggregation == "std":
            windowed_data = np.array([np.std(window, axis=0) for window in windows])
        else:
            # No aggregation: flatten windows into (n_windows * window_size, n_features)
            windowed_data = np.vstack(windows)

        result = build_dataset_like(windowed_data, input_ds)
        # Windowing changes sample cardinality: clear sample-coupled fields.
        result.sample_axis = None  # type: ignore[assignment]
        result.target = None
        add_processing_step(
            result,
            "time_series.moving_window",
            {
                "window_size": window_size,
                "step_size": step_size,
                "aggregation": aggregation,
                "n_windows": n_windows,
            },
            node_id=self.node_id,
            input_shape=input_shape,
        )

        # Store window metadata for downstream consumers
        result.meta["_window_size"] = window_size
        result.meta["_step_size"] = step_size
        result.meta["_n_windows"] = n_windows
        result.meta["_window_indices"] = window_indices

        return result


def _trend_removal_transform(
    data: np.ndarray,
    method: str = "linear",
    poly_order: int = 2,
    window_size: int = 5,
) -> np.ndarray:
    n_samples, n_features = data.shape
    detrended = np.zeros_like(data)

    if method == "linear":
        t = np.arange(n_samples)
        for j in range(n_features):
            p = np.polyfit(t, data[:, j], 1)
            detrended[:, j] = data[:, j] - np.polyval(p, t)

    elif method == "polynomial":
        t = np.arange(n_samples)
        for j in range(n_features):
            p = np.polyfit(t, data[:, j], poly_order)
            detrended[:, j] = data[:, j] - np.polyval(p, t)

    elif method == "difference":
        detrended[0] = data[0]
        detrended[1:] = np.diff(data, axis=0)

    elif method == "moving_average":
        from scipy.ndimage import uniform_filter1d

        for j in range(n_features):
            baseline = uniform_filter1d(data[:, j], window_size, mode="nearest")
            detrended[:, j] = data[:, j] - baseline

    return detrended


@register_node
class TrendRemovalNode(TransformSpecNode):
    """
    Trend Removal node.

    Removes systematic trends from time series spectral data.
    Supports detrending, differencing, and baseline drift correction
    for process control applications.

    Essential preprocessing for detecting process changes and drift
    in continuous monitoring scenarios.
    """

    metadata = NodeMetadata(
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
                step=1,
                description="Window size for moving average baseline",
                required=False,
            ),
        ],
        input_types=["NDDataset"],
        output_type="NDDataset",
        input_ports=[
            PortMetadata(
                name="default",
                type_ref="spectrasherpa://types/SpectralDataset/1.0",
                required=True,
                label="Input Data",
                description="Input data to process",
            ),
        ],
    )

    spec = TransformSpec(
        transform_fn=_trend_removal_transform,
        extra_imports=["import numpy as np"],
    )
