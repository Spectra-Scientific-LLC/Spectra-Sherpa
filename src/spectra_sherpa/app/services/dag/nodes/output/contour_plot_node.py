"""
Contour Plot visualization node.
"""

from __future__ import annotations

from typing import Any, Dict, List

import numpy as np

import spectra_sherpa.sdk.plot_spec as plot_spec_contract
from spectra_sherpa.app.lib.sherpa_dataset import SherpaDataset
from spectra_sherpa.app.services.dag.stable_execution_contract import bind_stable_execution_contract
from spectra_sherpa.execution_contract_vocabulary import (
    LifecycleKind,
    ManagedOptimizationEligibility,
    RuntimeFamily,
    WorkerCapability,
)
from spectra_sherpa.sdk.plot_spec import canonical_plot_spec_from_projection

from ...node_base import Node, NodeMetadata, NodeParameter, NodePolicy, PortMetadata, register_node
from ._helpers import get_axis_display_info


def _canonical_contour_parameters(raw: dict[str, object]) -> dict[str, object]:
    """Close the contour-presentation settings."""

    unknown = sorted(set(raw) - {"colorscale", "plot_type", "reverse_x", "transpose"})
    if unknown:
        raise ValueError(f"output.contour received unknown parameters: {', '.join(unknown)}")
    colorscale = raw.get("colorscale", "Viridis")
    if colorscale not in {"Viridis", "Hot", "RdBu", "Blues", "Greys", "Jet", "Spectral"}:
        raise ValueError("output.contour colorscale is not supported")
    plot_type = raw.get("plot_type", "heatmap")
    if plot_type not in {"heatmap", "contour", "surface"}:
        raise ValueError("output.contour plot_type is not supported")
    reverse_x = raw.get("reverse_x", False)
    transpose = raw.get("transpose", False)
    if not isinstance(reverse_x, bool) or not isinstance(transpose, bool):
        raise ValueError("output.contour reverse_x and transpose must be boolean")
    return {
        "colorscale": colorscale,
        "plot_type": plot_type,
        "reverse_x": reverse_x,
        "transpose": transpose,
    }


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
        policy=NodePolicy(
            safe_for_auto_apply=True,
            requires_human_review=False,
            data_egress_risk="none",
            offload_to_pool=False,
        ),
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
        input_types=["SherpaDataset"],
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
        canonical_parameter_validator=_canonical_contour_parameters,
    )

    def generate_python(
        self,
        inputs: Dict[str, str],
        indent: str = "    ",
        use_scp: bool = True,
    ) -> List[str]:
        """Generate a call to the same contour authority used live."""
        input_expr = inputs.get("default", next(iter(inputs.values()), "input_data"))
        parameters = self.metadata.canonicalize_parameters(self._resolve_params())
        return [
            f"{indent}# --- Contour ({self.node_id}) ---",
            (
                f"{indent}from spectra_sherpa.app.services.dag.nodes.output.contour_plot_node "
                "import build_contour_result"
            ),
            f"{indent}results[{self.node_id!r}] = build_contour_result(",
            f"{indent}    {input_expr}, parameters={parameters!r},",
            f"{indent})",
        ]

    async def execute(self, input_data: Any) -> Dict[str, Any]:
        """
        Generate contour/heatmap plot data from input.

        Args:
            input_data: SherpaDataset with 2D spectral data (samples x wavenumbers)

        Returns:
            Dict with Plotly-compatible contour/heatmap configuration
        """
        parameters = self.metadata.canonicalize_parameters(self._resolve_params())
        return build_contour_result(input_data, parameters=parameters)

    def _build(self, input_data: Any) -> Dict[str, Any]:
        """Project a supported numeric matrix into one contour payload."""
        colorscale = self.parameters.get("colorscale", "Viridis")
        plot_type = self.parameters.get("plot_type", "heatmap")
        reverse_x = self.parameters.get("reverse_x", False)
        transpose = self.parameters.get("transpose", False)

        # Handle the canonical scientific dataset directly.
        if isinstance(input_data, SherpaDataset):
            return self._create_contour(input_data, colorscale, plot_type, reverse_x, transpose)

        # Handle dict with data field
        if isinstance(input_data, dict) and "data" in input_data:
            data = self._numeric_matrix(input_data["data"])
            x_data = input_data.get("x", list(range(data.shape[1])))
            y_data = input_data.get("y", list(range(data.shape[0])))
            plot_data = self._create_contour_from_arrays(
                data, x_data, y_data, colorscale, plot_type, reverse_x, transpose
            )
            return {"visualization": plot_data}
        if isinstance(input_data, dict):
            for key in ("transformed", "result", "predictions", "probabilities"):
                if key in input_data and input_data[key] is not None:
                    return self._create_from_array_like(
                        input_data[key],
                        colorscale,
                        plot_type,
                        reverse_x,
                        transpose,
                        title=key.replace("_", " ").title(),
                    )
        if isinstance(input_data, (list, tuple, np.ndarray)):
            return self._create_from_array_like(input_data, colorscale, plot_type, reverse_x, transpose)

        raise ValueError("output.contour requires a supported canonical dataset or numeric array")

    @staticmethod
    def _numeric_matrix(input_data: Any) -> np.ndarray:
        data = np.asarray(input_data, dtype=np.float64)
        if data.ndim == 1:
            data = data.reshape(-1, 1)
        if data.ndim != 2 or data.size == 0:
            raise ValueError("output.contour requires a non-empty one- or two-dimensional numeric array")
        if not np.isfinite(data).all():
            raise ValueError("output.contour requires finite numeric values")
        return data

    def _create_from_array_like(
        self,
        input_data: Any,
        colorscale: str,
        plot_type: str,
        reverse_x: bool,
        transpose: bool,
        title: str = "Array Output",
    ) -> Dict[str, Any]:
        """Create a contour/heatmap from numeric array-like model outputs."""
        data = self._numeric_matrix(input_data)
        plot_data = self._create_contour_from_arrays(
            data,
            list(range(data.shape[1])),
            list(range(data.shape[0])),
            colorscale,
            plot_type,
            reverse_x,
            transpose,
            x_title="Feature",
            y_title="Sample",
            z_title=title,
        )
        return {"visualization": plot_data}

    def _create_contour(
        self, dataset: Any, colorscale: str, plot_type: str, reverse_x: bool, transpose: bool
    ) -> Dict[str, Any]:
        """Generate contour/heatmap plot from SherpaDataset."""

        # Get spectral data as 2D array
        data = self._numeric_matrix(dataset.data)

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

        data = self._numeric_matrix(data)
        x_data = list(x_data)
        y_data = list(y_data)
        if len(x_data) != data.shape[1] or len(y_data) != data.shape[0]:
            raise ValueError("output.contour axis lengths must match the numeric matrix")

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


def build_contour_result(
    input_data: Any,
    *,
    parameters: dict[str, object] | None = None,
) -> dict[str, Any]:
    """Return the sole live/generated contour-presentation payload."""

    canonical = ContourPlotNode.metadata.canonicalize_parameters(parameters or {})
    node = ContourPlotNode("canonical-contour-authority", canonical)
    projection = node._build(input_data)
    visualization = projection.get("visualization")
    if not isinstance(visualization, dict):
        raise ValueError("output.contour did not produce a visualization projection")
    return {"visualization": canonical_plot_spec_from_projection(visualization).as_dict()}


bind_stable_execution_contract(
    ContourPlotNode,
    runtime_family=RuntimeFamily.SHERPA_NATIVE,
    lifecycle_kind=LifecycleKind.STATELESS_TRANSFORM,
    implementation_id="spectrasherpa.output.contour",
    implementation_version="2.0.0",
    implementation_modules=(plot_spec_contract,),
    implementation_distributions=("numpy",),
    runtime_requirements=(("numpy", "1.26.4"),),
    required_worker_capabilities=(WorkerCapability.READ_DATASET,),
    managed_optimization_eligibility=(ManagedOptimizationEligibility.LOCAL,),
    sample_effect="preserves_samples",
    feature_effect="preserves_features",
    axis_effect="preserves_axis",
    unit_effect="preserves_units",
    resource_hints={"timeout_seconds": 10, "cpu_seconds": 5, "memory_bytes": 536_870_912},
    license_id="Apache-2.0",
    help_reference="docs/nodes/output.md",
)


__all__ = ["ContourPlotNode", "build_contour_result"]
