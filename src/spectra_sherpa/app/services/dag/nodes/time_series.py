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
from spectra_sherpa.app.lib.analysis_dataset import AnalysisDataset
from spectra_sherpa.app.services.dag.meta_helpers import add_processing_step

from ..io_contracts import build_dataset_like, coerce_dataset, to_numpy_2d
from ..node_base import Node, NodeMetadata, NodeParameter, register_node


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
                max_value=100,
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
                max_value=50,
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
    )

    async def execute(self, input_data: AnalysisDataset) -> Any:
        """
        Execute moving window segmentation.

        Args:
            input_data: AnalysisDataset containing time series spectral data

        Returns:
            AnalysisDataset with windowed data
        """
        window_size = self.parameters.get("window_size", 10)
        step_size = self.parameters.get("step_size", 1)
        aggregation = self.parameters.get("aggregation", "none")

        input_ds = coerce_dataset(input_data, input_name="input_data")
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
        result.y = None
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
                max_value=5,
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
                max_value=50,
                step=1,
                description="Window size for moving average baseline",
                required=False,
            ),
        ],
        input_types=["NDDataset"],
        output_type="NDDataset",
    )

    async def execute(self, input_data: AnalysisDataset) -> Any:
        """
        Execute trend removal.

        Args:
            input_data: AnalysisDataset containing time series spectral data

        Returns:
            AnalysisDataset with detrended data
        """
        method = self.parameters.get("method", "linear")
        poly_order = self.parameters.get("poly_order", 2)
        window_size = self.parameters.get("window_size", 5)

        input_ds = coerce_dataset(input_data, input_name="input_data")
        data = to_numpy_2d(input_ds, name="input_data", dtype=np.float64)
        n_samples, n_features = data.shape
        input_shape = input_ds.shape

        detrended_data = np.zeros_like(data)

        if method == "linear":
            # Linear detrending along time axis for each wavelength
            t = np.arange(n_samples)
            for j in range(n_features):
                # Fit linear trend
                p = np.polyfit(t, data[:, j], 1)
                trend = np.polyval(p, t)
                detrended_data[:, j] = data[:, j] - trend

        elif method == "polynomial":
            # Polynomial detrending
            t = np.arange(n_samples)
            for j in range(n_features):
                # Fit polynomial trend
                p = np.polyfit(t, data[:, j], poly_order)
                trend = np.polyval(p, t)
                detrended_data[:, j] = data[:, j] - trend

        elif method == "difference":
            # First difference (removes linear trends)
            detrended_data[0] = data[0]  # Keep first spectrum as reference
            detrended_data[1:] = np.diff(data, axis=0)

        elif method == "moving_average":
            # Remove moving average baseline
            from scipy.ndimage import uniform_filter1d

            for j in range(n_features):
                baseline = uniform_filter1d(data[:, j], window_size, mode="nearest")
                detrended_data[:, j] = data[:, j] - baseline

        logger.debug(f"[Trend Removal] Applied {method} detrending")

        result = build_dataset_like(detrended_data, input_ds)
        add_processing_step(
            result,
            "time_series.trend_removal",
            {
                "method": method,
                "poly_order": poly_order if method == "polynomial" else None,
                "window_size": window_size if method == "moving_average" else None,
            },
            node_id=self.node_id,
            input_shape=input_shape,
        )

        return result
