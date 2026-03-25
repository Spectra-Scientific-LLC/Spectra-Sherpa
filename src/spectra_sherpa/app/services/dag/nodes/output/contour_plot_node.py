"""
Contour Plot visualization node.
"""

from __future__ import annotations

from typing import Any, Dict, List

import numpy as np

from spectra_sherpa.app.lib.scp_compat import NDDataset
from spectra_sherpa.app.lib.sherpa_dataset import SherpaDataset
from spectra_sherpa.app.services.dag.io_contracts import coerce_to_sherpa

from ...node_base import Node, NodeMetadata, NodeParameter, PortMetadata, register_node
from ._helpers import get_axis_display_info


@register_node
class ContourPlotNode(Node):
    """
    Contour Plot visualization node.

    Creates 2D contour/heatmap plots for spectral data - ideal for
    visualizing time-resolved or multi-sample spectroscopy data
    where you want to see all spectra as a 2D surface.

    Common uses:
    - MCR-ALS input data visualization
    - Kinetic/reaction monitoring
    - Temperature-dependent spectra
    """

    metadata = NodeMetadata(
        node_type="output.contour",
        category="output",
        label="Contour Plot",
        description="Create 2D contour/heatmap visualization for spectral data",
        parameters=[
            NodeParameter(
                name="colorscale",
                label="Color Scale",
                param_type="select",
                default="Viridis",
                options=["Viridis", "Hot", "RdBu", "Blues", "Greys", "Jet", "Spectral"],
                description="Color scale for contour plot",
                required=False,
            ),
            NodeParameter(
                name="plot_type",
                label="Plot Type",
                param_type="select",
                default="heatmap",
                options=["heatmap", "contour", "surface"],
                description="Type of 2D visualization",
                required=False,
            ),
            NodeParameter(
                name="reverse_x",
                label="Reverse X-axis",
                param_type="boolean",
                default=False,
                description="Reverse X-axis direction (auto-enabled for wavenumber axes)",
                required=False,
            ),
            NodeParameter(
                name="transpose",
                label="Transpose Data",
                param_type="boolean",
                default=False,
                description="Swap sample and feature axes",
                required=False,
            ),
        ],
        input_types=["NDDataset"],
        output_type="dict",
        input_ports=[
            PortMetadata(
                name="default",
                type_ref="spectrasherpa://types/Any/1.0",
                required=True,
                label="Input Data",
                description="Input data to process",
            ),
        ],
        output_ports=[
            PortMetadata(
                name="visualization",
                type_ref="spectrasherpa://types/Visualization/1.0",
                required=True,
                label="Contour Plot",
                description="Contour/Heatmap configuration",
            ),
        ],
    )

    async def execute(self, input_data: Any) -> Dict[str, Any]:
        """
        Generate contour/heatmap plot data from input.

        Args:
            input_data: SherpaDataset with 2D spectral data (samples x wavenumbers)

        Returns:
            Dict with Plotly-compatible contour/heatmap configuration
        """
        colorscale = self.parameters.get("colorscale", "Viridis")
        plot_type = self.parameters.get("plot_type", "heatmap")
        reverse_x = self.parameters.get("reverse_x", True)
        transpose = self.parameters.get("transpose", False)

        # Coerce NDDataset -> SherpaDataset so all dataset paths work
        if isinstance(input_data, NDDataset):
            input_data = coerce_to_sherpa(input_data)

        # Handle NDDataset / SherpaDataset input
        if isinstance(input_data, SherpaDataset):
            return self._create_contour(input_data, colorscale, plot_type, reverse_x, transpose)

        # Handle dict with data field
        if isinstance(input_data, dict) and "data" in input_data:
            data = np.array(input_data["data"])
            x_data = input_data.get("x", list(range(data.shape[1])))
            y_data = input_data.get("y", list(range(data.shape[0])))
            plot_data = self._create_contour_from_arrays(
                data, x_data, y_data, colorscale, plot_type, reverse_x, transpose
            )
            return {"visualization": plot_data}

        # Fallback
        # Fallback
        result = {
            "plot_type": "contour",
            "data": [],
            "layout": {"title": "No 2D data to plot"},
        }
        return {"visualization": result}

    def _create_contour(
        self, dataset: Any, colorscale: str, plot_type: str, reverse_x: bool, transpose: bool
    ) -> Dict[str, Any]:
        """Generate contour/heatmap plot from SherpaDataset."""

        # Get spectral data as 2D array
        data = np.array(dataset.data)
        if data.ndim == 1:
            data = data.reshape(1, -1)

        # Get axes - preserve titles from source data (use generic accessors)
        x_coord = dataset.feature_axis
        if x_coord is not None:
            x_data = np.array(x_coord.data).tolist()
            x_info = get_axis_display_info(x_coord)
            x_title = x_info["title"]
            x_units = x_info["units"]
            auto_reverse_x = x_info["should_reverse"]
        else:
            x_data = list(range(data.shape[1]))
            x_info = get_axis_display_info(None)
            x_title = x_info["title"]
            x_units = x_info["units"]
            auto_reverse_x = False

        y_coord = dataset.get_observation_axis()
        if y_coord is not None and y_coord.data is not None:
            y_data = np.array(y_coord.data).tolist()
            y_info = get_axis_display_info(y_coord)
            y_title = y_info["title"]
            y_units = y_info["units"]
        elif y_coord is not None and getattr(y_coord, "labels", None) is not None:
            y_data = list(range(len(y_coord.labels)))
            y_info = get_axis_display_info(y_coord)
            y_title = y_info["title"]
            y_units = y_info["units"]
        else:
            y_data = list(range(data.shape[0]))
            y_info = get_axis_display_info(None)
            y_title = "Sample"
            y_units = ""

        # Transpose if requested
        if transpose:
            data = data.T
            x_data, y_data = y_data, x_data
            x_title, y_title = y_title, x_title
            x_units, y_units = y_units, x_units
            # Swap auto-reverse logic when transposing
            auto_reverse_x = False  # After transpose, y becomes x, reset auto-reverse

        # Auto-detect axis-specific display preferences (user override OR auto-detect)
        should_reverse = reverse_x or auto_reverse_x

        plot_data = self._create_contour_from_arrays(
            data,
            x_data,
            y_data,
            colorscale,
            plot_type,
            should_reverse,
            transpose,
            x_title=x_title,
            x_units=x_units,
            y_title=y_title,
            y_units=y_units,
            z_title=str(dataset.units) if dataset.units and str(dataset.units) != "dimensionless" else "Response",
        )
        return {"visualization": plot_data}

    def _create_contour_from_arrays(
        self,
        data: np.ndarray,
        x_data: List,
        y_data: List,
        colorscale: str,
        plot_type: str,
        reverse_x: bool,
        transpose: bool,
        x_title: str = "Feature",
        x_units: str = "",
        y_title: str = "Sample",
        y_units: str = "",
        z_title: str = "Value",
    ) -> Dict[str, Any]:
        """Create contour plot data from arrays."""

        # Create the trace based on plot type
        if plot_type == "contour":
            trace = {
                "x": x_data,
                "y": y_data,
                "z": data.tolist(),
                "type": "contour",
                "colorscale": colorscale,
                "contours": {
                    "coloring": "heatmap",
                    "showlabels": True,
                },
                "colorbar": {"title": z_title},
            }
        elif plot_type == "surface":
            trace = {
                "x": x_data,
                "y": y_data,
                "z": data.tolist(),
                "type": "surface",
                "colorscale": colorscale,
                "colorbar": {"title": z_title},
            }
        else:  # heatmap (default)
            trace = {
                "x": x_data,
                "y": y_data,
                "z": data.tolist(),
                "type": "heatmap",
                "colorscale": colorscale,
                "colorbar": {"title": z_title},
            }

        # Build axis labels
        x_label = f"{x_title} ({x_units})" if x_units else x_title
        y_label = f"{y_title} ({y_units})" if y_units else y_title

        layout = {
            "title": "Spectral Contour Plot",
            "xaxis": {
                "title": x_label,
                "autorange": "reversed" if reverse_x else True,
            },
            "yaxis": {"title": y_label},
        }

        # For surface plots, add 3D scene configuration
        if plot_type == "surface":
            layout = {
                "title": "3D Spectral Surface",
                "scene": {
                    "xaxis": {"title": x_label},
                    "yaxis": {"title": y_label},
                    "zaxis": {"title": z_title},
                },
            }

        return {
            "plot_type": plot_type,
            "data": [trace],
            "layout": layout,
        }
