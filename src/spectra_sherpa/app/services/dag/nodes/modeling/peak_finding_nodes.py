"""
Peak finding / spectral analysis node.
"""

from __future__ import annotations

import logging
from typing import Any

import numpy as np

from ...io_contracts import (
    bind_X,
    resolve_legacy_input,
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

    async def execute(self, input_data: Any = None, **kwargs: Any) -> Any:
        """
        Execute peak finding on spectral data.

        Args:
            input_data: Dataset containing spectral data

        Returns:
            Dict containing peak positions, heights, widths, and areas
        """
        from scipy.signal import find_peaks as scipy_find_peaks

        input_data = resolve_legacy_input(input_data, kwargs, "default")
        input_ds = bind_X(
            input_data,
            kwargs,
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

        # Convert to numpy array
        data = to_numpy_2d(input_ds, name="input_data", dtype=np.float64)

        # Handle multi-spectrum input (take first spectrum for peak finding)
        if data.ndim > 1:
            spectrum = data[0]
            logger.debug("[Peak Finding] Multi-spectrum input detected, analyzing first spectrum")
        else:
            spectrum = data

        # Build kwargs for scipy find_peaks
        peak_kwargs = {}
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

        # Find peaks using scipy
        peak_indices, peak_properties = scipy_find_peaks(spectrum, **peak_kwargs)

        # Get wavenumber/ppm positions if available
        _x_coord = input_ds.feature_axis
        if _x_coord is not None:
            x_axis = _to_numpy_1d_any(_x_coord, name="x_axis", dtype=np.float64)
            peak_positions = x_axis[peak_indices].tolist()
            x_unit = str(_x_coord.units) if hasattr(_x_coord, "units") else "cm⁻¹"
        else:
            peak_positions = peak_indices.tolist()
            x_unit = "index"

        # Extract peak properties
        peak_heights = spectrum[peak_indices].tolist()

        # Get widths if calculated
        peak_widths = peak_properties.get("widths", np.zeros(len(peak_indices))).tolist()

        # Get prominences if calculated
        peak_prominences = peak_properties.get("prominences", np.zeros(len(peak_indices))).tolist()

        # Estimate peak areas (simple trapezoidal integration around peak)
        peak_areas = []
        for idx, width in zip(peak_indices, peak_widths):
            if width > 0:
                # Integration window: peak ± width/2
                left = max(0, int(idx - width / 2))
                right = min(len(spectrum), int(idx + width / 2))
                area = np.trapz(spectrum[left:right])
                peak_areas.append(area)
            else:
                peak_areas.append(peak_heights[peak_indices.tolist().index(idx)])

        # Create annotated spectrum for visualization
        annotated_spectrum = spectrum.copy()

        result = {
            "peaks": {
                "count": len(peak_indices),
                "positions": peak_positions,
                "indices": peak_indices.tolist(),
                "heights": peak_heights,
                "widths": peak_widths,
                "prominences": peak_prominences,
                "areas": peak_areas,
            },
            "spectrum": spectrum.tolist(),
            "annotated_spectrum": annotated_spectrum.tolist(),
            "x_axis": (x_axis.tolist() if _x_coord is not None else list(range(len(spectrum)))),
            "x_unit": x_unit,
            # Visualization data
            "data": [[pos, height] for pos, height in zip(peak_positions, peak_heights)],
            "metadata": {
                "type": "PeakFinding",
                "output_type": "analysis",
                "n_peaks": len(peak_indices),
                "x_unit": x_unit,
                "peak_table": [
                    {
                        "position": pos,
                        "height": height,
                        "width": width,
                        "prominence": prom,
                        "area": area,
                    }
                    for pos, height, width, prom, area in zip(
                        peak_positions, peak_heights, peak_widths, peak_prominences, peak_areas
                    )
                ],
            },
        }

        logger.debug("[Peak Finding] Found %s peaks", len(peak_indices))

        return result
