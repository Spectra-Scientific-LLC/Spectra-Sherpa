"""
Peak finding / spectral analysis node.
"""

from __future__ import annotations

import logging
from typing import Any

import numpy as np

from ...io_contracts import (
    bind_X,
    to_numpy_2d,
)
from ...node_base import (
    Node,
    NodeMetadata,
    NodeParameter,
    PortMetadata,
    register_node,
)
from .core_utils import (
    to_numpy_1d_any as _to_numpy_1d_any,
)

logger = logging.getLogger(__name__)


@register_node
class PeakFindingNode(Node):
    """
    Peak Finding node.

    Identifies peaks in spectroscopic data using scipy's signal processing algorithms.
    Supports height, distance, prominence, and width-based peak detection criteria.

    Returns peak positions, heights, widths, prominences, and integrated areas.
    """

    metadata = NodeMetadata(
        node_type="analysis.peak_finding",
        category="exploratory",
        label="Peak Finding",
        description="Find peaks in spectral data with domain-specific algorithms",
        parameters=[
            NodeParameter(
                name="height",
                label="Minimum Height",
                param_type="number",
                default=None,
                min_value=0.0,
                max_value=100.0,
                step=0.01,
                description="Minimum peak height (leave empty for auto)",
                required=False,
            ),
            NodeParameter(
                name="threshold",
                label="Threshold",
                param_type="number",
                default=None,
                min_value=0.0,
                max_value=10.0,
                step=0.01,
                description="Minimum vertical distance to neighbors",
                required=False,
            ),
            NodeParameter(
                name="distance",
                label="Minimum Distance",
                param_type="number",
                default=10,
                min_value=1,
                max_value=100,
                step=1,
                description="Minimum horizontal distance between peaks (in points)",
                required=False,
            ),
            NodeParameter(
                name="prominence",
                label="Prominence",
                param_type="number",
                default=None,
                min_value=0.0,
                max_value=10.0,
                step=0.01,
                description="Peak prominence threshold",
                required=False,
            ),
            NodeParameter(
                name="width",
                label="Expected Width",
                param_type="number",
                default=None,
                min_value=1,
                max_value=100,
                step=1,
                description="Expected peak width (in points)",
                required=False,
            ),
        ],
        input_types=["NDDataset"],
        input_ports=[
            PortMetadata(
                name="default",
                type_ref="spectrasherpa://types/SpectralDataset/1.0",
                required=True,
                label="Input Spectra",
                description="Spectral data to process",
            ),
        ],
        output_type="PeakData",
        output_ports=[
            PortMetadata(
                name="peaks",
                type_ref="spectrasherpa://types/Array1D/1.0",
                required=True,
                label="Peak List",
                description="Detected peaks with positions, heights, widths, areas",
            ),
            PortMetadata(
                name="annotated_spectrum",
                type_ref="spectrasherpa://types/Array1D/1.0",
                required=True,
                label="Annotated Spectrum",
                description="Spectrum with peak markers and labels",
            ),
            PortMetadata(
                name="spectrum",
                type_ref="spectrasherpa://types/Array1D/1.0",
                required=False,
                label="Original Spectrum",
                description="Input spectrum (for comparison)",
            ),
        ],
    )

    # Colour palette shared with the frontend (NodeDetailView.vue)
    _COLORS = [
        "#3b82f6",
        "#ef4444",
        "#22c55e",
        "#f59e0b",
        "#8b5cf6",
        "#ec4899",
        "#06b6d4",
        "#f97316",
    ]

    @staticmethod
    def _bin_consensus_peaks(
        all_positions: list[float],
        all_heights: list[float],
        tolerance: float,
        n_samples: int,
    ) -> list[list[Any]]:
        """Group nearby peak positions into consensus bins via proximity sweep.

        Returns a list of rows, one per consensus peak:
        [median_pos, mean_pos, std_pos, min_pos, max_pos,
         count, fraction_str, median_height, q1_height, q3_height]
        """
        if not all_positions:
            return []

        # Sort by position
        order = np.argsort(all_positions)
        sorted_pos = np.array(all_positions, dtype=np.float64)[order]
        sorted_h = np.array(all_heights, dtype=np.float64)[order]

        # Greedy sweep: start a new bin whenever the gap exceeds tolerance
        bins: list[list[int]] = [[0]]
        for i in range(1, len(sorted_pos)):
            if sorted_pos[i] - sorted_pos[bins[-1][-1]] > tolerance:
                bins.append([i])
            else:
                bins[-1].append(i)

        rows: list[dict[str, Any]] = []
        for indices in bins:
            pos_arr = sorted_pos[indices]
            h_arr = sorted_h[indices]
            count = len(indices)
            q1_h, med_h, q3_h = np.percentile(h_arr, [25, 50, 75]).tolist()
            rows.append(
                {
                    "median_pos": float(np.median(pos_arr)),
                    "mean_pos": float(np.mean(pos_arr)),
                    "std_pos": float(np.std(pos_arr)) if count > 1 else 0.0,
                    "min_pos": float(pos_arr.min()),
                    "max_pos": float(pos_arr.max()),
                    "count": count,
                    "detected": f"{count}/{n_samples}",
                    "median_height": med_h,
                    "q1_height": q1_h,
                    "q3_height": q3_h,
                }
            )

        # Sort consensus rows by median position
        rows.sort(key=lambda r: r["median_pos"])
        return rows

    async def execute(self, input_data: Any = None, **kwargs: Any) -> Any:
        """
        Execute peak finding on spectral data.

        Args:
            input_data: Dataset containing spectral data

        Returns:
            Dict containing peak positions, heights, widths, and areas
        """
        from scipy.signal import find_peaks as scipy_find_peaks

        input_ds = bind_X(
            input_data,
            missing_message="Missing required input: input_data (spectrum)",
            dataset_error_message="input_data must be an dataset object",
            allow_array=False,
        )

        # Get parameters
        height = self.parameters.get("height")
        threshold = self.parameters.get("threshold")
        distance = self.parameters.get("distance", 10)
        prominence = self.parameters.get("prominence")
        width = self.parameters.get("width")

        # Convert to numpy array (always 2D: n_samples × n_features)
        data = to_numpy_2d(input_ds, name="input_data", dtype=np.float64)
        n_samples = data.shape[0]

        # Build kwargs for scipy find_peaks
        peak_kwargs: dict[str, Any] = {}
        if height is not None:
            peak_kwargs["height"] = height
        if threshold is not None:
            peak_kwargs["threshold"] = threshold
        if distance is not None:
            peak_kwargs["distance"] = distance
        if prominence is not None:
            peak_kwargs["prominence"] = prominence
        if width is not None:
            peak_kwargs["width"] = width

        # Get x-axis (wavenumber / ppm / wavelength) if available
        _x_coord = input_ds.feature_axis
        if _x_coord is not None:
            x_axis = _to_numpy_1d_any(_x_coord, name="x_axis", dtype=np.float64)
            x_axis_list: list[float] = x_axis.tolist()
            x_title = getattr(_x_coord, "title", None) or "Feature"
            x_units = str(_x_coord.units) if hasattr(_x_coord, "units") and _x_coord.units else ""
            if x_units == "dimensionless":
                x_units = ""
        else:
            x_axis = np.arange(data.shape[1], dtype=np.float64)
            x_axis_list = x_axis.tolist()
            x_title = "Feature"
            x_units = ""

        # Derive Y-axis label from dataset value units
        y_title: str | None = None
        y_units: str | None = None
        if hasattr(input_ds, "units") and input_ds.units:
            raw_units = str(input_ds.units)
            if raw_units != "dimensionless":
                y_units = raw_units
        if hasattr(input_ds, "get_extra"):
            semantic = input_ds.get_extra("scp.value_units_label")
            if semantic:
                y_title = str(semantic)

        # Extract sample labels (following the pattern in pca_nodes.py)
        sample_labels: list[str] = []
        _y_coord = input_ds.sample_axis
        if _y_coord is not None:
            try:
                if hasattr(_y_coord, "labels") and _y_coord.labels is not None:
                    raw = _y_coord.labels.tolist() if hasattr(_y_coord.labels, "tolist") else list(_y_coord.labels)
                    sample_labels = [str(l) for l in raw]
            except Exception:
                pass
        if len(sample_labels) != n_samples:
            sample_labels = [f"Sample {i + 1}" for i in range(n_samples)]

        # ---- Run peak finding on every spectrum ----
        all_positions: list[float] = []
        all_heights: list[float] = []
        all_spectra = data.tolist()

        # Plotly traces: spectrum lines + peak markers
        plotly_traces: list[dict[str, Any]] = []
        plotly_shapes: list[dict[str, Any]] = []

        # Build display labels (matching plotLabels.ts buildAxisLabel logic)
        spectral_kw = ("wavenumber", "wavelength", "raman", "cm-1", "cm⁻¹", "nm", "shift", "frequency")
        is_wavenumber = any(kw in x_title.lower() for kw in spectral_kw) or (
            x_units.lower() in ("cm⁻¹", "cm-1", "1/cm")
        )
        x_label = f"{x_title} ({x_units})" if x_units else x_title
        y_label = y_title or y_units or "Response"

        total_peaks = 0

        for sample_idx in range(n_samples):
            spectrum = data[sample_idx]
            label = sample_labels[sample_idx]
            color = self._COLORS[sample_idx % len(self._COLORS)]

            indices, props = scipy_find_peaks(spectrum, **peak_kwargs)
            positions = x_axis[indices].tolist()
            heights = spectrum[indices].tolist()
            widths = props.get("widths", np.zeros(len(indices))).tolist()

            # Estimate peak areas
            areas: list[float] = []
            for idx, w in zip(indices, widths):
                if w > 0:
                    left = max(0, int(idx - w / 2))
                    right = min(len(spectrum), int(idx + w / 2))
                    areas.append(float(np.trapz(spectrum[left:right])))
                else:
                    areas.append(float(spectrum[idx]))

            total_peaks += len(indices)
            all_positions.extend(positions)
            all_heights.extend(heights)

            # -- Plotly: spectrum line trace --
            plotly_traces.append(
                {
                    "type": "scatter",
                    "mode": "lines",
                    "x": x_axis_list,
                    "y": spectrum.tolist(),
                    "name": label,
                    "legendgroup": label,
                    "line": {"color": color, "width": 1.5},
                    "opacity": 0.8,
                }
            )

            # -- Plotly: peak markers --
            if len(positions) > 0:
                plotly_traces.append(
                    {
                        "type": "scatter",
                        "mode": "markers",
                        "x": positions,
                        "y": heights,
                        "name": f"{label} peaks",
                        "legendgroup": label,
                        "showlegend": False,
                        "marker": {
                            "symbol": "triangle-down",
                            "size": 10,
                            "color": color,
                            "line": {"color": "#fff", "width": 0.5},
                        },
                    }
                )

                # -- Plotly: vertical dashed lines at peaks --
                for pos, h in zip(positions, heights):
                    plotly_shapes.append(
                        {
                            "type": "line",
                            "x0": pos,
                            "x1": pos,
                            "y0": 0,
                            "y1": h,
                            "line": {"color": color, "width": 1, "dash": "dot"},
                            "opacity": 0.35,
                        }
                    )

        # ---- Consensus peak binning ----
        # Tolerance = distance (points) × mean x-axis spacing (x-units per point)
        if len(x_axis_list) > 1:
            mean_spacing = abs(x_axis_list[-1] - x_axis_list[0]) / (len(x_axis_list) - 1)
        else:
            mean_spacing = 1.0
        bin_tolerance = (distance or 10) * mean_spacing

        consensus_rows = self._bin_consensus_peaks(
            all_positions,
            all_heights,
            bin_tolerance,
            n_samples,
        )

        # Add consensus peak markers to plot (white dashed full-height lines)
        for row in consensus_rows:
            median_pos = row["median_pos"]
            plotly_shapes.append(
                {
                    "type": "line",
                    "x0": median_pos,
                    "x1": median_pos,
                    "y0": 0,
                    "y1": 1,
                    "yref": "paper",
                    "line": {"color": "#ffffff", "width": 1.5, "dash": "dash"},
                    "opacity": 0.45,
                }
            )

        # Build Plotly layout (dark theme matching basePlotLayout in the frontend)
        plotly_layout: dict[str, Any] = {
            "autosize": True,
            "height": 500,
            "paper_bgcolor": "#1e293b",
            "plot_bgcolor": "#0f172a",
            "font": {"color": "#f8fafc", "size": 12},
            "margin": {"t": 40, "r": 20, "b": 50, "l": 60},
            "xaxis": {
                "gridcolor": "#334155",
                "zerolinecolor": "#475569",
                "title": x_label,
                "autorange": "reversed" if is_wavenumber else True,
            },
            "yaxis": {
                "gridcolor": "#334155",
                "zerolinecolor": "#475569",
                "title": y_label,
            },
            "showlegend": True,
            "legend": {
                "x": 1,
                "xanchor": "right",
                "y": 1,
                "bgcolor": "rgba(0,0,0,0)",
                "font": {"size": 10},
            },
            "shapes": plotly_shapes,
        }

        result = {
            "peaks": {
                "data": consensus_rows,
                "metadata": {
                    "type": "PeakFinding",
                    "output_type": "analysis",
                    "n_consensus_peaks": len(consensus_rows),
                    "n_total_detections": total_peaks,
                    "n_samples": n_samples,
                    "x_title": x_title,
                    "x_units": x_units,
                },
            },
            "spectrum": all_spectra,
            "annotated_spectrum": all_spectra,
            "plots": {
                "peak_finding": {
                    "data": plotly_traces,
                    "layout": plotly_layout,
                },
            },
        }

        logger.debug(
            "[Peak Finding] %s consensus peaks from %s detections across %s spectra",
            len(consensus_rows),
            total_peaks,
            n_samples,
        )

        return result
