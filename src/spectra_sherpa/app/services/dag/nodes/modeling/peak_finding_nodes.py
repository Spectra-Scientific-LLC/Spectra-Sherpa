"""
Peak finding / spectral analysis node.
"""

from __future__ import annotations

import logging
from copy import deepcopy
from typing import Any

import numpy as np

from spectra_sherpa.app.lib.sherpa_dataset import FeatureAxis, SherpaDataset
from spectra_sherpa.app.services.dag import presentation_limits
from spectra_sherpa.execution_contract_vocabulary import (
    LifecycleKind,
    ManagedOptimizationEligibility,
    RuntimeFamily,
    WorkerCapability,
)

from ...io_contracts import (
    bind_X,
    to_numpy_2d,
)
from ...node_base import (
    Node,
    NodeMetadata,
    NodeParameter,
    NodePolicy,
    NodeResult,
    PortMetadata,
    register_node,
)
from ...presentation_contract import NodePresentationContract, ScientificPresentation
from ...stable_execution_contract import bind_stable_execution_contract
from .core_utils import (
    to_numpy_1d_any as _to_numpy_1d_any,
)

logger = logging.getLogger(__name__)


_PEAK_PARAMETER_NAMES = frozenset({"height", "threshold", "distance", "prominence", "width", "consensus_tolerance"})


def _nonnegative_peak_param(value: Any, *, name: str, zero_disables: bool = False) -> float | None:
    """Normalize optional nonnegative peak-finding parameters."""
    if value is None or value == "":
        return None
    normalized = float(value)
    if not np.isfinite(normalized):
        raise ValueError(f"{name} must be finite")
    if normalized < 0:
        raise ValueError(f"{name} must be >= 0")
    if zero_disables and normalized == 0:
        return None
    return normalized


def _canonical_peak_parameters(parameters: dict[str, Any]) -> dict[str, float | None]:
    """Return the one closed parameter object consumed by every execution path."""

    unknown = sorted(set(parameters) - _PEAK_PARAMETER_NAMES)
    if unknown:
        raise ValueError(f"analysis.peak_finding has unknown parameters: {', '.join(unknown)}")
    if parameters.get("consensus_tolerance", 0.0) in (None, ""):
        raise ValueError("consensus_tolerance is required; enter 0 to group only identical positions")
    distance = _nonnegative_peak_param(parameters.get("distance", 10), name="distance", zero_disables=True)
    if distance is not None and distance < 1:
        raise ValueError("distance must be 0 (disabled) or >= 1 point")
    return {
        "height": _nonnegative_peak_param(parameters.get("height"), name="height"),
        "threshold": _nonnegative_peak_param(parameters.get("threshold"), name="threshold"),
        "distance": distance,
        "prominence": _nonnegative_peak_param(parameters.get("prominence"), name="prominence"),
        "width": _nonnegative_peak_param(parameters.get("width"), name="width", zero_disables=True),
        "consensus_tolerance": _nonnegative_peak_param(
            parameters.get("consensus_tolerance", 0.0),
            name="consensus_tolerance",
        ),
    }


@register_node
class PeakFindingNode(Node):
    """
    Peak Finding node.

    Identifies peaks in spectroscopic data using scipy's signal processing algorithms.
    Supports height, distance, prominence, and width-based peak detection criteria.

    Returns consensus positions, heights, half-prominence widths, absolute
    integrals over the half-prominence windows, and the source membership of
    every constituent detection. The integral is descriptive; it is not a
    baseline-corrected quantitative peak area.
    """

    metadata = NodeMetadata(
        policy=NodePolicy(),
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
                step=0.01,
                description="Minimum peak height in response units. Blank passes height=None (no height filter).",
                required=False,
            ),
            NodeParameter(
                name="threshold",
                label="Threshold",
                param_type="number",
                default=None,
                min_value=0.0,
                step=0.01,
                description="Minimum vertical distance to neighbors in response units. Blank passes threshold=None.",
                required=False,
            ),
            NodeParameter(
                name="distance",
                label="Minimum Distance",
                param_type="number",
                default=10,
                min_value=0,
                step=1,
                description=(
                    "Minimum horizontal distance in sample points (default 10). "
                    "Blank or 0 passes distance=None (disabled); otherwise must be >= 1."
                ),
                required=False,
            ),
            NodeParameter(
                name="prominence",
                label="Prominence",
                param_type="number",
                default=None,
                min_value=0.0,
                step=0.01,
                description=(
                    "Minimum prominence in response units. Blank passes prominence=None (no prominence filter)."
                ),
                required=False,
            ),
            NodeParameter(
                name="width",
                label="Expected Width",
                param_type="number",
                default=None,
                min_value=0,
                step=1,
                description=(
                    "Minimum width at half prominence in sample points. Blank or 0 passes width=None (no width filter)."
                ),
                required=False,
            ),
            NodeParameter(
                name="consensus_tolerance",
                label="Consensus Tolerance",
                param_type="number",
                default=0.0,
                min_value=0.0,
                step=0.1,
                description=(
                    "Maximum span of one cross-sample consensus bin in feature-axis units; "
                    "enter 0 to group only identical positions. Required; not a SciPy find_peaks argument."
                ),
                required=True,
            ),
        ],
        input_types=["SherpaDataset"],
        input_ports=[
            PortMetadata(
                name="default",
                type_ref="spectrasherpa://types/SpectralDataset/1.0",
                required=True,
                label="Input Spectra",
                description="Spectral data to process",
            ),
        ],
        output_type="PeakTable",
        output_ports=[
            PortMetadata(
                name="peaks",
                type_ref="spectrasherpa://types/PeakTable/1.0",
                required=True,
                label="Peak List",
                description=(
                    "Consensus detections with positions, source membership, heights, "
                    "half-prominence widths, and window integrals"
                ),
            ),
            PortMetadata(
                name="plots",
                type_ref="spectrasherpa://types/Visualization/1.0",
                required=True,
                label="Peak Plot",
                description="Input spectra with per-sample and consensus peak markers",
            ),
            PortMetadata(
                name="per_spectrum",
                type_ref="spectrasherpa://types/SpectralDataset/1.0",
                required=True,
                label="Per-spectrum Peak Matrix",
                description="One row per spectrum; four measured-position/magnitude columns per consensus group.",
            ),
        ],
        presentation_contract=NodePresentationContract(
            default_presentation="peak_overlay",
            presentations=(
                ScientificPresentation(
                    "peak_overlay",
                    "Spectra with Peaks",
                    "visualization",
                    ("plots",),
                    ("plot",),
                    "Input spectra with per-sample detections and consensus peak markers.",
                ),
                ScientificPresentation(
                    "peak_table",
                    "Peak Table",
                    "peak_table",
                    ("peaks",),
                    ("plot", "table"),
                    "Consensus peak positions, source membership, heights, widths, integrals, and detection rates.",
                ),
                ScientificPresentation(
                    "per_spectrum",
                    "Per-spectrum Peak Matrix",
                    "spectral_dataset",
                    ("per_spectrum",),
                    ("plot", "table"),
                    "One row per spectrum, with detected and nearest-guide measurements for every group.",
                ),
            ),
        ),
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
        all_sample_indices: list[int],
        all_heights: list[float],
        all_fwhm: list[float],
        all_areas: list[float],
        tolerance: float,
        n_samples: int,
        sample_labels: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        """Group nearby peak positions into consensus bins via proximity sweep.

        Returns one row per bounded consensus bin. Raw detection count and
        distinct-sample count remain separate because a spectrum can contain
        more than one detection within the same axis interval.
        """
        input_lengths = {
            len(all_positions),
            len(all_sample_indices),
            len(all_heights),
            len(all_fwhm),
            len(all_areas),
        }
        if len(input_lengths) != 1:
            raise ValueError("consensus peak detection vectors must have equal lengths")
        if n_samples < 0:
            raise ValueError("n_samples must be nonnegative")
        if sample_labels is None:
            normalized_sample_labels = [f"Sample {index + 1}" for index in range(n_samples)]
        elif len(sample_labels) != n_samples:
            raise ValueError("sample_labels must contain one label per input spectrum")
        else:
            normalized_sample_labels = [str(label) for label in sample_labels]

        if not all_positions:
            return []
        if any(index < 0 or index >= n_samples for index in all_sample_indices):
            raise ValueError("consensus peak sample indices must refer to input spectra")

        # Sort by position
        order = np.argsort(all_positions)
        sorted_pos = np.array(all_positions, dtype=np.float64)[order]
        sorted_samples = np.array(all_sample_indices, dtype=np.int64)[order]
        sorted_h = np.array(all_heights, dtype=np.float64)[order]
        sorted_w = np.array(all_fwhm, dtype=np.float64)[order] if all_fwhm else np.zeros_like(sorted_h)
        sorted_a = np.array(all_areas, dtype=np.float64)[order] if all_areas else np.zeros_like(sorted_h)

        # Bounded-span sweep: every position in a bin remains within the
        # declared tolerance of the first position. This avoids chained bins
        # whose total span silently exceeds the scientist's criterion.
        bins: list[list[int]] = [[0]]
        for i in range(1, len(sorted_pos)):
            if sorted_pos[i] - sorted_pos[bins[-1][0]] > tolerance:
                bins.append([i])
            else:
                bins[-1].append(i)

        rows: list[dict[str, Any]] = []
        for indices in bins:
            pos_arr = sorted_pos[indices]
            h_arr = sorted_h[indices]
            w_arr = sorted_w[indices]
            a_arr = sorted_a[indices]
            sample_arr = sorted_samples[indices]
            detection_count = len(indices)
            member_sample_indices = sorted({int(value) for value in sample_arr})
            member_sample_labels = [normalized_sample_labels[index] for index in member_sample_indices]
            constituent_detections = [
                {
                    "sample_index": int(sample_index),
                    "sample_label": normalized_sample_labels[int(sample_index)],
                    "position": float(position),
                    "height": float(height),
                    "half_prominence_width": float(width),
                    "absolute_window_integral": float(area),
                }
                for sample_index, position, height, width, area in zip(
                    sample_arr,
                    pos_arr,
                    h_arr,
                    w_arr,
                    a_arr,
                    strict=True,
                )
            ]
            sample_count = len(member_sample_indices)
            q1_h, med_h, q3_h = np.percentile(h_arr, [25, 50, 75]).tolist()
            q1_w, med_w, q3_w = np.percentile(w_arr, [25, 50, 75]).tolist()
            q1_a, med_a, q3_a = np.percentile(a_arr, [25, 50, 75]).tolist()
            rows.append(
                {
                    "median_pos": float(np.median(pos_arr)),
                    "mean_pos": float(np.mean(pos_arr)),
                    "std_pos": float(np.std(pos_arr)) if detection_count > 1 else 0.0,
                    "min_pos": float(pos_arr.min()),
                    "max_pos": float(pos_arr.max()),
                    "detection_count": detection_count,
                    "sample_count": sample_count,
                    "detection_fraction": sample_count / n_samples if n_samples else 0.0,
                    "member_sample_indices": member_sample_indices,
                    "member_sample_labels": member_sample_labels,
                    "constituent_detections": constituent_detections,
                    "median_height": med_h,
                    "q1_height": q1_h,
                    "q3_height": q3_h,
                    "median_half_prominence_width": med_w,
                    "q1_half_prominence_width": q1_w,
                    "q3_half_prominence_width": q3_w,
                    "median_absolute_window_integral": med_a,
                    "q1_absolute_window_integral": q1_a,
                    "q3_absolute_window_integral": q3_a,
                }
            )

        # Sort consensus rows by median position
        rows.sort(key=lambda r: r["median_pos"])
        for index, row in enumerate(rows, start=1):
            row["consensus_peak_id"] = f"peak-{index:06d}"
            row["consensus_group"] = index
            row["label"] = f"consensus peak ({row['sample_count']}/{n_samples} samples)"
        return rows

    def generate_python(
        self,
        inputs: dict[str, str],
        indent: str = "    ",
        use_scp: bool = True,
    ) -> list[str]:
        """Generate Python that calls the same authority as live execution."""
        input_expr = inputs.get("default", next(iter(inputs.values()), "input_data"))
        return [
            f"{indent}from spectra_sherpa.app.services.dag.nodes.modeling.peak_finding_nodes "
            "import execute_peak_finding",
            f"{indent}results[{self.node_id!r}] = execute_peak_finding(",
            f"{indent}    {input_expr}, parameters={self.parameters!r}, node_id={self.node_id!r},",
            f"{indent}).outputs",
        ]

    def _execute_sync(self, input_data: Any = None) -> NodeResult:
        """
        Execute peak finding on spectral data.

        Args:
            input_data: Dataset containing spectral data

        Returns:
            Dict containing peak positions, heights, widths, and areas
        """
        import scipy
        from scipy.signal import find_peaks as scipy_find_peaks
        from scipy.signal import peak_widths as scipy_peak_widths

        input_ds = bind_X(
            input_data,
            missing_message="Missing required input: input_data (spectrum)",
            dataset_error_message="input_data must be an dataset object",
            allow_array=False,
        )

        parameters = _canonical_peak_parameters(self.parameters)

        # Convert to numpy array (always 2D: n_samples × n_features)
        from spectra_sherpa.app.services.dag.presentation_limits import require_bounded_presentation

        require_bounded_presentation(input_ds, surface="Peak detection input", max_values=1_000_000)
        data = to_numpy_2d(input_ds, name="input_data", dtype=np.float64)
        if data.size == 0 or not np.isfinite(data).all():
            raise ValueError("input_data must contain a non-empty finite spectral matrix")
        n_samples = data.shape[0]

        # Explicit arguments are also the retained reproduction record. Optional
        # blanks remain None; SciPy defaults are never hidden from that record.
        peak_kwargs: dict[str, Any] = {
            name: parameters[name] for name in ("height", "threshold", "distance", "prominence", "width")
        }
        peak_kwargs.update(wlen=None, rel_height=0.5, plateau_size=None)
        scipy_call = (
            "scipy.signal.find_peaks(spectrum, "
            + ", ".join(f"{name}={value!r}" for name, value in peak_kwargs.items())
            + ")"
        )

        # Get x-axis (wavenumber / ppm / wavelength) if available
        _x_coord = input_ds.feature_axis
        _x_values = getattr(_x_coord, "values", None) if _x_coord is not None else None
        if _x_values is not None:
            x_axis = _to_numpy_1d_any(_x_values, name="x_axis", dtype=np.float64)
            if x_axis.size != data.shape[1] or not np.isfinite(x_axis).all():
                raise ValueError("feature axis must contain one finite value per spectral feature")
            delta = np.diff(x_axis)
            if delta.size and not (np.all(delta > 0) or np.all(delta < 0)):
                raise ValueError("feature axis must be strictly monotonic")
            x_axis_list: list[float] = x_axis.tolist()
            x_title = getattr(_x_coord, "title", None) or "Feature"
            x_units = str(_x_coord.units) if hasattr(_x_coord, "units") and _x_coord.units else ""
            if x_units == "dimensionless":
                x_units = ""
        else:
            x_axis = np.arange(data.shape[1], dtype=np.float64)
            x_axis_list = x_axis.tolist()
            x_title = getattr(_x_coord, "title", None) or "Feature"
            x_units = ""

        # Derive Y-axis label from dataset value units
        y_title: str | None = None
        y_units: str | None = None
        if hasattr(input_ds, "units") and input_ds.units:
            raw_units = str(input_ds.units)
            if raw_units != "dimensionless":
                y_units = raw_units
        if hasattr(input_ds, "get_extra"):
            semantic = input_ds.get_extra("spectrasherpa.value_units_label")
            if semantic:
                y_title = str(semantic)

        # Extract sample labels (following the pattern in pca_nodes.py)
        sample_labels: list[str] = []
        _y_coord = input_ds.sample_axis
        if _y_coord is not None and hasattr(_y_coord, "labels") and _y_coord.labels is not None:
            raw = _y_coord.labels.tolist() if hasattr(_y_coord.labels, "tolist") else list(_y_coord.labels)
            sample_labels = [str(label) for label in raw]
        if len(sample_labels) != n_samples:
            sample_labels = [f"Sample {i + 1}" for i in range(n_samples)]

        # ---- Run peak finding on every spectrum ----
        all_positions: list[float] = []
        all_sample_indices: list[int] = []
        all_heights: list[float] = []
        all_half_prominence_widths: list[float] = []
        all_absolute_window_integrals: list[float] = []
        # Plotly traces: spectrum lines + peak markers
        plotly_traces: list[dict[str, Any]] = []

        # Build display labels (matching plotLabels.ts buildAxisLabel logic)
        spectral_kw = ("wavenumber", "wavelength", "raman", "cm-1", "cm⁻¹", "nm", "shift", "frequency")
        is_wavenumber = any(kw in x_title.lower() for kw in spectral_kw) or (
            x_units.lower() in ("cm⁻¹", "cm-1", "1/cm")
        )
        x_label = f"{x_title} ({x_units})" if x_units else x_title
        y_label = y_title or y_units or "Response"

        total_peaks = 0
        width_measurement_samples: list[int] = []

        for sample_idx in range(n_samples):
            spectrum = data[sample_idx]
            label = sample_labels[sample_idx]
            color = self._COLORS[sample_idx % len(self._COLORS)]

            indices, _ = scipy_find_peaks(spectrum, **peak_kwargs)
            if total_peaks + len(indices) > 10_000:
                raise ValueError(
                    "Peak detection exceeds its display limit (10,000 detections). "
                    "Select a smaller explicit cohort or feature range."
                )
            positions = x_axis[indices].tolist()
            heights = spectrum[indices].tolist()
            if len(indices):
                width_measurement_samples.append(sample_idx)
                _, _, left_ips, right_ips = scipy_peak_widths(
                    spectrum, indices, rel_height=0.5, prominence_data=None, wlen=None
                )
                point_grid = np.arange(len(x_axis), dtype=np.float64)
                left_x = np.interp(left_ips, point_grid, x_axis)
                right_x = np.interp(right_ips, point_grid, x_axis)
                half_prominence_widths = np.abs(right_x - left_x).astype(np.float64)
            else:
                left_ips = np.array([], dtype=np.float64)
                right_ips = np.array([], dtype=np.float64)
                half_prominence_widths = np.array([], dtype=np.float64)

            # Estimate peak areas
            absolute_window_integrals: list[float] = []
            for peak_idx, (idx, measured_width) in enumerate(zip(indices, half_prominence_widths)):
                if measured_width > 0:
                    left = int(max(0, np.floor(left_ips[peak_idx])))
                    right = int(min(len(spectrum), np.ceil(right_ips[peak_idx]) + 1))
                    if right - left >= 2:
                        absolute_window_integrals.append(float(abs(np.trapz(spectrum[left:right], x_axis[left:right]))))
                    else:
                        absolute_window_integrals.append(float(abs(spectrum[idx])))
                else:
                    absolute_window_integrals.append(float(abs(spectrum[idx])))

            total_peaks += len(indices)
            all_positions.extend(positions)
            all_sample_indices.extend([sample_idx] * len(positions))
            all_heights.extend(heights)
            all_half_prominence_widths.extend(half_prominence_widths.tolist())
            all_absolute_window_integrals.extend(absolute_window_integrals)

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
                            "size": 6,
                            "color": color,
                            "line": {"color": "#fff", "width": 0.5},
                        },
                    }
                )

        # ---- Consensus peak binning ----
        bin_tolerance = float(parameters["consensus_tolerance"])

        consensus_rows = self._bin_consensus_peaks(
            all_positions,
            all_sample_indices,
            all_heights,
            all_half_prominence_widths,
            all_absolute_window_integrals,
            bin_tolerance,
            n_samples,
            sample_labels,
        )

        # Consensus markers retain membership on hover; guides mark the same
        # positions across the full height of the spectral overlay.
        if consensus_rows:
            plotly_traces.append(
                {
                    "type": "scatter",
                    "mode": "markers",
                    "name": "Consensus peaks",
                    "visible": True,
                    "x": [row["median_pos"] for row in consensus_rows],
                    "y": [row["median_height"] for row in consensus_rows],
                    "customdata": [
                        [
                            row["detection_fraction"],
                            ", ".join(row["member_sample_labels"]),
                            row["sample_count"],
                            n_samples,
                        ]
                        for row in consensus_rows
                    ],
                    "marker": {"symbol": "diamond-open", "size": 8, "color": "#ffffff"},
                    "hovertemplate": (
                        "Position: %{x}<br>Median height: %{y}<br>"
                        "Spectra with detected peak: %{customdata[0]:.1%} (%{customdata[2]}/%{customdata[3]})<br>"
                        "Detected in: %{customdata[1]}<extra>Consensus peaks</extra>"
                    ),
                }
            )

        # Build Plotly layout (dark theme matching basePlotLayout in the frontend)
        plotly_layout: dict[str, Any] = {
            # Same ascending group order as peak_position_N and the other matrix columns.
            "annotations": [
                {
                    "x": row["median_pos"],
                    "xref": "x",
                    "y": 1,
                    "yref": "paper",
                    "text": str(index + 1),
                    "showarrow": False,
                    "yanchor": "bottom",
                    "yshift": 14 * (index % 2),
                    "font": {"color": "#f59e0b", "size": 12},
                    "hovertext": f"Consensus group {index + 1}: {row['median_pos']:g}",
                }
                for index, row in enumerate(consensus_rows)
            ],
            "shapes": [
                {
                    "type": "line",
                    "xref": "x",
                    "yref": "paper",
                    "x0": row["median_pos"],
                    "x1": row["median_pos"],
                    "y0": 0,
                    "y1": 1,
                    "line": {"color": "#f59e0b", "width": 1, "dash": "dot"},
                    "layer": "below",
                }
                for row in consensus_rows
            ],
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
                "x": 0,
                "xanchor": "left",
                "y": -0.25,
                "orientation": "h",
                "bgcolor": "rgba(0,0,0,0)",
                "font": {"size": 10},
            },
        }

        # Detect spectral technique from input dataset (best-effort)
        from ...meta_helpers import detect_spectral_technique

        technique: str | None = detect_spectral_technique(input_ds)
        n_features = data.shape[1]

        # This projection belongs to the detecting node: consumers must not
        # reconstruct consensus membership or rerun detection from a plot.
        columns = []
        column_units = []
        if n_samples * 4 * len(consensus_rows) > 1_000_000:
            raise ValueError(
                "Per-spectrum peak matrix exceeds 1,000,000 values; select a smaller cohort or feature range."
            )
        matrix = np.full((n_samples, 4 * len(consensus_rows)), np.nan)
        for group_index, row in enumerate(consensus_rows):
            suffix = group_index + 1
            columns.extend(
                [
                    f"peak_position_{suffix}",
                    f"magnitude_at_peak_{suffix}",
                    f"group_position_{suffix}",
                    f"magnitude_at_group_position_{suffix}",
                ]
            )
            column_units.extend([x_units, y_units or "", x_units, y_units or ""])
            # Actual measured coordinate nearest the guide, not interpolation.
            # Equal-distance ties choose the lower physical coordinate.
            nearest = int(np.lexsort((x_axis, np.abs(x_axis - row["median_pos"])))[0])
            offset = 4 * group_index
            matrix[:, offset + 2] = x_axis[nearest]
            matrix[:, offset + 3] = data[:, nearest]
            for sample_index in row["member_sample_indices"]:
                members = [d for d in row["constituent_detections"] if d["sample_index"] == sample_index]
                detection = min(members, key=lambda d: (abs(d["position"] - row["median_pos"]), d["position"]))
                matrix[sample_index, offset] = detection["position"]
                matrix[sample_index, offset + 1] = detection["height"]
        peak_matrix = SherpaDataset(
            X=matrix,
            feature_axis=FeatureAxis(labels=columns, title="Peak measurements"),
            sample_axis=deepcopy(input_ds.sample_axis),
            source_identity=input_ds.source_identity.model_copy(deep=True),
            source_history=input_ds.source_history.model_copy(deep=True),
            provenance=input_ds.provenance.copy(),
            title="Per-spectrum peak measurements",
            data_role="X_features",
        )
        peak_matrix.meta["peak_groups"] = [
            {"index": index + 1, "consensus_peak_id": row["consensus_peak_id"], "guide_position": row["median_pos"]}
            for index, row in enumerate(consensus_rows)
        ]
        peak_matrix.meta["column_units"] = dict(zip(columns, column_units, strict=True))
        peak_matrix.provenance.append(
            "analysis.peak_finding",
            dict(self.parameters),
            node_id=self.node_id,
            input_shape=tuple(input_ds.shape),
            output_shape=tuple(peak_matrix.shape),
            state_effects=["peak_features_extracted"],
        )
        peak_matrix.meta["measurement_policy"] = {
            "group_position": "Nearest measured feature coordinate to consensus median; ties use lower coordinate",
            "peak_position": "Nearest member detection to consensus median; ties use lower coordinate",
            "missing_detection": "NaN in detected position and magnitude; group measurements remain populated",
            "all_detections": "Retained in peaks.data[].constituent_detections",
        }

        result = {
            "per_spectrum": peak_matrix,
            "peaks": {
                "data": consensus_rows,
                "metadata": {
                    "type": "PeakFinding",
                    "method": "peak_finding",
                    "n_total_variables": n_features,
                    "selection_context": {"n_samples": n_samples, "technique": technique},
                    "column_units": {
                        key: x_units
                        for key in (
                            "median_pos",
                            "mean_pos",
                            "std_pos",
                            "min_pos",
                            "max_pos",
                            "median_half_prominence_width",
                            "q1_half_prominence_width",
                            "q3_half_prominence_width",
                        )
                    },
                    "output_type": "analysis",
                    "n_consensus_peaks": len(consensus_rows),
                    "n_total_detections": total_peaks,
                    "n_samples": n_samples,
                    "n_features": n_features,
                    "technique": technique,
                    "x_title": x_title,
                    "x_units": x_units,
                    "sample_label_title": getattr(_y_coord, "title", None) or "Sample",
                    "membership_complete": sum(len(row["constituent_detections"]) for row in consensus_rows)
                    == total_peaks,
                    "quality_summary": {
                        "n_peaks": int(total_peaks),
                        "n_consensus_peaks": int(len(consensus_rows)),
                    },
                },
            },
            "plots": {
                "peak_finding": {
                    "data": plotly_traces,
                    "layout": plotly_layout,
                },
                "metadata": {
                    "n_samples": int(n_samples),
                    "n_peaks": int(total_peaks),
                    "n_consensus_peaks": int(len(consensus_rows)),
                },
            },
        }

        logger.debug(
            "[Peak Finding] %s consensus peaks from %s detections across %s spectra",
            len(consensus_rows),
            total_peaks,
            n_samples,
        )

        detection_rates = [row["detection_fraction"] for row in consensus_rows]
        detection_rate_min = float(min(detection_rates)) if detection_rates else 0.0
        detection_rate_max = float(max(detection_rates)) if detection_rates else 0.0

        require_bounded_presentation(
            result, surface="Peak detection presentation", max_values=5_000_000, max_text_bytes=16 * 1024 * 1024
        )
        return NodeResult(
            outputs=result,
            diagnostics={
                "n_consensus_peaks": int(len(consensus_rows)),
                "n_peaks": int(total_peaks),
                "n_samples": int(n_samples),
                "method": "scipy_find_peaks",
                "scipy_version": scipy.__version__,
                "scipy_find_peaks_arguments": peak_kwargs,
                "scipy_find_peaks_call": scipy_call,
                "scipy_find_peaks_call_count": n_samples,
                "scipy_peak_widths_call": (
                    "scipy.signal.peak_widths(spectrum, indices, rel_height=0.5, prominence_data=None, wlen=None)"
                    if width_measurement_samples
                    else None
                ),
                "scipy_peak_widths_call_count": len(width_measurement_samples),
                "scipy_peak_widths_sample_indices": width_measurement_samples,
                "consensus_binning": f"Maximum bin span = {bin_tolerance!r} feature-axis units; not a SciPy argument",
                "parameter_interpretation": (
                    "Blank optional filters pass None; distance=0 and width=0 also disable their filters (None)."
                ),
                "technique": technique,
                "n_features": int(n_features),
                "detection_rate_min": detection_rate_min,
                "detection_rate_max": detection_rate_max,
            },
        )

    async def execute(self, input_data: Any = None, **kwargs: Any) -> NodeResult:
        del kwargs
        return self._execute_sync(input_data)


def execute_peak_finding(input_data: Any, *, parameters: dict[str, Any], node_id: str) -> NodeResult:
    """Execute the canonical peak-finding authority for live and generated DAGs."""

    return PeakFindingNode(node_id, parameters)._execute_sync(input_data)


bind_stable_execution_contract(
    PeakFindingNode,
    runtime_family=RuntimeFamily.SHERPA_NATIVE,
    lifecycle_kind=LifecycleKind.STATELESS_TRANSFORM,
    implementation_id="spectrasherpa.analysis.peak_finding",
    implementation_version="1.5.1",
    required_worker_capabilities=(WorkerCapability.READ_DATASET,),
    managed_optimization_eligibility=(ManagedOptimizationEligibility.LOCAL,),
    sample_effect="aggregates_samples",
    feature_effect="filters_features",
    axis_effect="removes_axis",
    unit_effect="changes_units",
    resource_hints={"timeout_seconds": 30, "cpu_seconds": 30, "memory_bytes": 536_870_912},
    license_id="Apache-2.0",
    help_reference="docs/nodes/exploratory.md",
    implementation_modules=(presentation_limits,),
    implementation_distributions=("numpy", "scipy"),
    runtime_requirements=(("numpy", "1.26.4"), ("scipy", "1.17.1")),
    citations=("Virtanen et al., Nature Methods 17 (2020) 261-272, doi:10.1038/s41592-019-0686-2",),
)


__all__ = ["PeakFindingNode", "execute_peak_finding"]
