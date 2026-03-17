"""
Output nodes for workflow results.

These nodes handle visualization and export of spectral data.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, cast

import numpy as np

from spectra_sherpa.app.lib.scp_compat import NDDataset
from spectra_sherpa.app.lib.sherpa_dataset import SherpaDataset
from spectra_sherpa.app.services.dag.io_contracts import coerce_to_sherpa

from ..node_base import Node, NodeMetadata, NodeParameter, NodePolicy, PortMetadata, register_node


def get_axis_display_info(axis: Any) -> dict[str, Any]:
    """
    Get display information for any axis type.

    Returns dict with:
        - title: Human-readable axis title
        - units: Unit string (empty if dimensionless)
        - label: Formatted label with units
        - should_reverse: Whether axis should be reversed (e.g., wavenumber)
        - default_title: Default title if axis.title is None
    """
    from spectra_sherpa.app.lib.axes import (
        FrequencyAxis,
        MZAxis,
        PotentialAxis,
        SpectralAxis,
        TimeAxis,
    )

    if axis is None:
        return {
            "title": "Index",
            "units": "",
            "label": "Index",
            "should_reverse": False,
            "default_title": "Index",
        }

    # Get units (handle None and "dimensionless")
    units_str = ""
    if hasattr(axis, "units") and axis.units:
        units_str = str(axis.units)
        if units_str == "dimensionless":
            units_str = ""

    # Determine title and default based on axis type
    if isinstance(axis, SpectralAxis):
        default_title = "Wavenumber" if "cm" in units_str else "Wavelength"
        should_reverse = "cm" in units_str  # Reverse wavenumber axes
    elif isinstance(axis, TimeAxis):
        default_title = "Time"
        should_reverse = False
    elif isinstance(axis, MZAxis):
        default_title = "m/z"
        should_reverse = False
    elif isinstance(axis, PotentialAxis):
        default_title = "Potential"
        should_reverse = False
    elif isinstance(axis, FrequencyAxis):
        default_title = "Frequency" if "Hz" in units_str else "Chemical Shift"
        should_reverse = False
    else:
        # Generic FeatureAxis or SampleAxis
        default_title = str(axis.title) if hasattr(axis, "title") and axis.title else "Feature"
        should_reverse = False

    # Use axis title if available, otherwise use default
    title = str(axis.title) if hasattr(axis, "title") and axis.title else default_title

    # Build formatted label
    if units_str:
        label = f"{title} ({units_str})"
    else:
        label = title

    return {
        "title": title,
        "units": units_str,
        "label": label,
        "should_reverse": should_reverse,
        "default_title": default_title,
    }


@register_node
class PlotNode(Node):
    """
    Plot visualization node.

    Creates plot data for spectral visualization in the frontend.
    """

    metadata = NodeMetadata(
        node_type="output.plot",
        category="output",
        label="Plot",
        description="Create plot visualization for spectral data",
        parameters=[
            NodeParameter(
                name="plot_type",
                label="Plot Type",
                param_type="select",
                default="spectra",
                options=["spectra", "contour", "heatmap", "scores", "biplot", "loadings", "scatter"],
                description="Type of plot to generate",
                required=False,
            ),
            NodeParameter(
                name="colorscale",
                label="Color Scale",
                param_type="select",
                default="Viridis",
                options=["Viridis", "Hot", "RdBu", "Blues", "Greys", "Jet", "Spectral"],
                description="Color scale for contour/heatmap plots",
                required=False,
            ),
            NodeParameter(
                name="x_axis",
                label="X Axis",
                param_type="number",
                default=0,
                description="Index or label for X axis",
                required=False,
            ),
            NodeParameter(
                name="y_axis",
                label="Y Axis",
                param_type="number",
                default=1,
                description="Index or label for Y axis",
                required=False,
            ),
        ],
        input_types=["NDDataset", "dict"],
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
                label="Plot Data",
                description="Plotly configuration and data",
            ),
        ],
    )

    def generate_python(
        self,
        inputs: Dict[str, str],
        indent: str = "    ",
        use_scp: bool = True,
    ) -> List[str]:
        """Generate Python code for Plotly-based visualization."""
        input_expr = inputs.get("default", next(iter(inputs.values()), "input_data"))
        plot_type = self.parameters.get("plot_type", "spectra")
        x_axis = self.parameters.get("x_axis", 0)
        y_axis = self.parameters.get("y_axis", 1)

        _nid = self.node_id.replace("-", "_")

        lines: List[str] = []
        lines.append(f"{indent}# --- Plot ({self.node_id}) ---")
        lines.append(f"{indent}try:")
        lines.append(f"{indent}    import plotly.graph_objects as go")
        lines.append(f"{indent}except ImportError:")
        lines.append(f"{indent}    class _SherpaFallbackFigure(dict):")
        lines.append(f"{indent}        def __init__(self, data=None):")
        lines.append(f"{indent}            super().__init__()")
        lines.append(f"{indent}            self['data'] = []")
        lines.append(f"{indent}            self['layout'] = {{}}")
        lines.append(f"{indent}            if data is not None:")
        lines.append(f"{indent}                self['data'] = data if isinstance(data, list) else [data]")
        lines.append(f"{indent}        def add_trace(self, trace):")
        lines.append(f"{indent}            self.setdefault('data', []).append(trace)")
        lines.append(f"{indent}        def update_layout(self, **kwargs):")
        lines.append(f"{indent}            self.setdefault('layout', {{}}).update(kwargs)")
        lines.append(f"{indent}        def show(self):")
        lines.append(f"{indent}            return None")
        lines.append(f"{indent}        def to_plotly_json(self):")
        lines.append(f"{indent}            return dict(self)")
        lines.append(f"{indent}        def write_html(self, path):")
        lines.append(f"{indent}            with open(path, 'w', encoding='utf-8') as _f:")
        lines.append(f"{indent}                _f.write('<html><body><pre>')")
        lines.append(f"{indent}                _f.write(json.dumps(self.to_plotly_json(), indent=2))")
        lines.append(f"{indent}                _f.write('</pre></body></html>')")
        lines.append(f"{indent}    class _SherpaFallbackGO:")
        lines.append(f"{indent}        Figure = _SherpaFallbackFigure")
        lines.append(f"{indent}        @staticmethod")
        lines.append(f"{indent}        def Scatter(**kwargs):")
        lines.append(f"{indent}            return {{'type': 'scatter', **kwargs}}")
        lines.append(f"{indent}        @staticmethod")
        lines.append(f"{indent}        def Contour(**kwargs):")
        lines.append(f"{indent}            return {{'type': 'contour', **kwargs}}")
        lines.append(f"{indent}        @staticmethod")
        lines.append(f"{indent}        def Heatmap(**kwargs):")
        lines.append(f"{indent}            return {{'type': 'heatmap', **kwargs}}")
        lines.append(f"{indent}    go = _SherpaFallbackGO()")
        lines.append(f"{indent}_plot_input_{_nid} = {input_expr}")
        lines.append(f"{indent}if isinstance(_plot_input_{_nid}, dict) and 'scores' in _plot_input_{_nid}:")
        lines.append(f"{indent}    _plot_source_{_nid} = _plot_input_{_nid}['scores']")
        lines.append(f"{indent}elif isinstance(_plot_input_{_nid}, dict) and 'loadings' in _plot_input_{_nid}:")
        lines.append(f"{indent}    _plot_source_{_nid} = _plot_input_{_nid}['loadings']")
        lines.append(f"{indent}else:")
        lines.append(f"{indent}    _plot_source_{_nid} = _plot_input_{_nid}")
        lines.append(f"{indent}_plot_data_{_nid} = (")
        lines.append(f"{indent}    np.asarray(_plot_source_{_nid}.data, dtype=np.float64)")
        lines.append(f"{indent}    if hasattr(_plot_source_{_nid}, 'data')")
        lines.append(f"{indent}    else np.asarray(_plot_source_{_nid}, dtype=np.float64)")
        lines.append(f"{indent})")
        lines.append(f"{indent}_plot_data_{_nid} = np.atleast_2d(_plot_data_{_nid})")
        lines.append(f"{indent}_x_values_{_nid} = None")
        lines.append(f"{indent}_x_title_{_nid} = 'Feature'")
        lines.append(f"{indent}_x_units_{_nid} = ''")
        lines.append(f"{indent}_y_title_{_nid} = 'Intensity'")
        lines.append(f"{indent}if getattr(_plot_source_{_nid}, 'feature_axis', None) is not None:")
        lines.append(f"{indent}    _x_values_{_nid} = np.asarray(_plot_source_{_nid}.feature_axis.data)")
        lines.append(
            f"{indent}    _x_title_{_nid} = " f"getattr(_plot_source_{_nid}.feature_axis, 'title', None) or 'Feature'"
        )
        lines.append(
            f"{indent}    _x_units_{_nid} = " f"getattr(_plot_source_{_nid}.feature_axis, 'units', None) or ''"
        )
        lines.append(f"{indent}if getattr(_plot_source_{_nid}, 'domain', None) is not None:")
        lines.append(f"{indent}    _y_title_{_nid} = _plot_source_{_nid}.domain.data_quantity or _y_title_{_nid}")
        lines.append(f"{indent}elif getattr(_plot_source_{_nid}, 'units', None):")
        lines.append(f"{indent}    _y_title_{_nid} = str(_plot_source_{_nid}.units)")
        lines.append(
            f"{indent}_x_label_{_nid} = "
            f'f"{{_x_title_{_nid}}} ({{_x_units_{_nid}}})" if _x_units_{_nid} else _x_title_{_nid}'
        )

        if plot_type in ("spectra",):
            lines.append(f"{indent}_fig_{_nid} = go.Figure()")
            lines.append(f"{indent}for _si in range(min(_plot_data_{_nid}.shape[0], 50)):")
            lines.append(
                f"{indent}    _xv = _x_values_{_nid} if _x_values_{_nid} is not None "
                f"else np.arange(_plot_data_{_nid}.shape[1])"
            )
            lines.append(
                f"{indent}    _fig_{_nid}.add_trace("
                f"go.Scatter(x=_xv, y=_plot_data_{_nid}[_si], mode='lines', name=f'Trace {{_si+1}}'))"
            )
            lines.append(
                f"{indent}_fig_{_nid}.update_layout(template='plotly_white', title='Spectra Plot', "
                f"xaxis_title=_x_label_{_nid}, yaxis_title=_y_title_{_nid})"
            )
        elif plot_type in ("scores", "biplot"):
            lines.append(f"{indent}_fig_{_nid} = go.Figure()")
            lines.append(f"{indent}if _plot_data_{_nid}.shape[1] > {max(x_axis, y_axis)}:")
            lines.append(
                f"{indent}    _fig_{_nid}.add_trace(go.Scatter("
                f"x=_plot_data_{_nid}[:, {x_axis}], y=_plot_data_{_nid}[:, {y_axis}], "
                f"mode='markers', name='Scores'))"
            )
            lines.append(
                f"{indent}_fig_{_nid}.update_layout(template='plotly_white', title='Scores Plot', "
                f"xaxis_title='PC {x_axis + 1}', yaxis_title='PC {y_axis + 1}')"
            )
        elif plot_type == "loadings":
            lines.append(f"{indent}_fig_{_nid} = go.Figure()")
            lines.append(f"{indent}for _ci in range(min(_plot_data_{_nid}.shape[0], 5)):")
            lines.append(
                f"{indent}    _xv = _x_values_{_nid} if _x_values_{_nid} is not None "
                f"else np.arange(_plot_data_{_nid}.shape[1])"
            )
            lines.append(
                f"{indent}    _fig_{_nid}.add_trace(go.Scatter("
                f"x=_xv, y=_plot_data_{_nid}[_ci], mode='lines', name=f'PC {{_ci+1}}'))"
            )
            lines.append(
                f"{indent}_fig_{_nid}.update_layout(template='plotly_white', title='Loadings Plot', "
                f"xaxis_title=_x_label_{_nid}, yaxis_title='Loading')"
            )
        elif plot_type in ("contour", "heatmap"):
            lines.append(
                f"{indent}_xv = _x_values_{_nid} if _x_values_{_nid} is not None "
                f"else np.arange(_plot_data_{_nid}.shape[1])"
            )
            lines.append(f"{indent}_yv = np.arange(_plot_data_{_nid}.shape[0])")
            lines.append(f"{indent}_fig_{_nid} = go.Figure(")
            if plot_type == "contour":
                lines.append(f"{indent}    data=go.Contour(z=_plot_data_{_nid}, x=_xv, y=_yv, colorscale='Viridis')")
            else:
                lines.append(f"{indent}    data=go.Heatmap(z=_plot_data_{_nid}, x=_xv, y=_yv, colorscale='Viridis')")
            lines.append(f"{indent})")
            lines.append(
                f"{indent}_fig_{_nid}.update_layout(template='plotly_white', title='{plot_type.title()} Plot', "
                f"xaxis_title=_x_label_{_nid}, yaxis_title='Sample Index')"
            )
        else:
            lines.append(f"{indent}_fig_{_nid} = go.Figure()")
            lines.append(
                f"{indent}_fig_{_nid}.add_trace(go.Scatter("
                f"x=_plot_data_{_nid}[:, 0], "
                f"y=_plot_data_{_nid}[:, 1] if _plot_data_{_nid}.shape[1] > 1 else _plot_data_{_nid}[:, 0], "
                f"mode='markers', name='Scatter'))"
            )
            lines.append(f"{indent}_fig_{_nid}.update_layout(template='plotly_white', title='Scatter Plot')")

        lines.append(f"{indent}try:")
        lines.append(f"{indent}    _fig_{_nid}.show()")
        lines.append(f"{indent}except Exception:")
        lines.append(f"{indent}    pass")
        lines.append(f"{indent}results['{self.node_id}'] = {{'visualization': _fig_{_nid}}}")
        lines.append(f'{indent}print(f"  Plot ({self.node_id}): {plot_type} figure created")')

        return lines

    async def execute(self, input_data: Any) -> Dict[str, Any]:
        """
        Generate plot data from input.

        Args:
            input_data: SherpaDataset or dict with spectral/model data

        Returns:
            Dict with plot configuration and data
        """
        plot_type = self.parameters.get("plot_type", "spectra")
        x_axis = self.parameters.get("x_axis", 0)
        y_axis = self.parameters.get("y_axis", 1)

        # Coerce NDDataset → SherpaDataset so all dataset paths work
        if isinstance(input_data, NDDataset):
            input_data = coerce_to_sherpa(input_data)

        # Handle NDDataset / SherpaDataset input
        if isinstance(input_data, SherpaDataset):
            if plot_type in ("contour", "heatmap"):
                colorscale = self.parameters.get("colorscale", "Viridis")
                return self._plot_contour(input_data, plot_type, colorscale)
            if plot_type == "scatter":
                return self._plot_scatter(input_data, x_axis, y_axis)
            return self._plot_spectra(input_data)

        # Handle dict input (e.g., from PCA node)
        if isinstance(input_data, dict):
            if "scores" in input_data:
                if plot_type == "biplot":
                    return self._plot_biplot(input_data, x_axis, y_axis)
                return self._plot_scores(input_data, x_axis, y_axis)
            if "data" in input_data:
                return self._plot_generic(input_data)

        # Fallback
        # Fallback
        result = {
            "plot_type": plot_type,
            "data": [],
            "layout": {"title": "No data to plot"},
        }
        return {"visualization": result}

    def _plot_spectra(self, dataset: Any) -> Dict[str, Any]:
        """Generate spectra plot data, preserving axis titles from dataset."""
        traces = []

        # Get x-axis data and display info from dataset (preferred property accessor)
        x_coord = dataset.feature_axis
        if x_coord is not None:
            x_data = x_coord.data.tolist()
            x_info = get_axis_display_info(x_coord)
            x_label = x_info["label"]
            should_reverse_x = x_info["should_reverse"]
        else:
            x_data = list(range(dataset.shape[-1]))
            x_info = get_axis_display_info(None)
            x_label = x_info["label"]
            should_reverse_x = False

        # Get y-axis title from dataset (data values title/units)
        if hasattr(dataset, "units") and dataset.units:
            y_label = str(dataset.units)
        elif hasattr(dataset, "title") and dataset.title:
            y_label = dataset.title
        else:
            y_label = "Value"

        # Configure x-axis with automatic reversal for appropriate axis types
        x_axis_config = {"title": x_label}
        if should_reverse_x:
            x_axis_config["autorange"] = "reversed"

        # Get spectral data
        data = np.array(dataset.data)
        if data.ndim == 1:
            data = data.reshape(1, -1)

        # Get sample labels from observation axis if available
        sample_labels = None
        obs_axis = dataset.get_observation_axis()
        if obs_axis is not None and getattr(obs_axis, "labels", None) is not None:
            sample_labels = list(obs_axis.labels)

        # Create trace for each spectrum/sample (cap at 50 to avoid browser overload)
        max_traces = 50
        n_samples = data.shape[0]
        if n_samples > max_traces:
            # Evenly-spaced subsample to keep representative coverage
            indices = np.linspace(0, n_samples - 1, max_traces, dtype=int)
        else:
            indices = range(n_samples)

        for i in indices:
            name = sample_labels[i] if sample_labels and i < len(sample_labels) else f"Sample {i+1}"
            traces.append(
                {
                    "x": x_data,
                    "y": data[i].tolist(),
                    "type": "scatter",
                    "mode": "lines",
                    "name": name,
                }
            )

        return {
            "visualization": {
                "plot_type": "spectra",
                "data": traces,
                "layout": {
                    "title": dataset.title if hasattr(dataset, "title") and dataset.title else "Data Plot",
                    "xaxis": x_axis_config,
                    "yaxis": {"title": y_label},
                },
            }
        }

    def _plot_contour(self, dataset: Any, plot_type: str, colorscale: str) -> Dict[str, Any]:
        """Generate contour/heatmap plot from SherpaDataset."""
        data = np.array(dataset.data)
        if data.ndim == 1:
            data = data.reshape(1, -1)

        # X-axis (feature axis — wavelength, wavenumber, etc.)
        x_coord = dataset.feature_axis
        if x_coord is not None:
            x_data = x_coord.data.tolist()
            x_info = get_axis_display_info(x_coord)
            x_label = x_info["label"]
            should_reverse_x = x_info["should_reverse"]
        else:
            x_data = list(range(data.shape[1]))
            x_label = "Feature"
            should_reverse_x = False

        # Y-axis (sample axis)
        y_coord = dataset.get_observation_axis()
        if y_coord is not None and y_coord.data is not None:
            y_data = np.array(y_coord.data).tolist()
            y_info = get_axis_display_info(y_coord)
            y_label = y_info["label"]
        elif y_coord is not None and getattr(y_coord, "labels", None) is not None:
            y_data = list(range(len(y_coord.labels)))
            y_info = get_axis_display_info(y_coord)
            y_label = y_info["label"]
        else:
            y_data = list(range(data.shape[0]))
            y_label = "Sample"

        z_title = str(dataset.units) if dataset.units and str(dataset.units) != "dimensionless" else "Response"
        title = dataset.title if hasattr(dataset, "title") and dataset.title else "Data Plot"

        if plot_type == "contour":
            trace = {
                "x": x_data,
                "y": y_data,
                "z": data.tolist(),
                "type": "contour",
                "colorscale": colorscale,
                "contours": {"coloring": "heatmap", "showlabels": True},
                "colorbar": {"title": z_title},
            }
        else:
            trace = {
                "x": x_data,
                "y": y_data,
                "z": data.tolist(),
                "type": "heatmap",
                "colorscale": colorscale,
                "colorbar": {"title": z_title},
            }

        return {
            "visualization": {
                "plot_type": plot_type,
                "data": [trace],
                "layout": {
                    "title": title,
                    "xaxis": {
                        "title": x_label,
                        "autorange": "reversed" if should_reverse_x else True,
                    },
                    "yaxis": {"title": y_label},
                },
            }
        }

    def _plot_scores(self, model_data: dict, pc_x: int, pc_y: int) -> Dict[str, Any]:
        """Generate PCA scores plot data."""
        scores = model_data.get("scores")
        if scores is None:
            return {"plot_type": "scores", "data": [], "layout": {}}

        # Convert to numpy if NDDataset/SherpaDataset
        if isinstance(scores, SherpaDataset):
            scores_array = np.array(scores.data)
        else:
            scores_array = np.array(scores)

        # Ensure 2D
        if scores_array.ndim == 1:
            scores_array = scores_array.reshape(-1, 1)

        n_components = scores_array.shape[1]
        pc_x = min(pc_x, n_components - 1)
        pc_y = min(pc_y, n_components - 1)

        trace = {
            "x": scores_array[:, pc_x].tolist(),
            "y": scores_array[:, pc_y].tolist(),
            "type": "scatter",
            "mode": "markers",
            "marker": {"size": 8, "color": "#3b82f6"},
            "name": "Scores",
        }

        return {
            "visualization": {
                "plot_type": "scores",
                "data": [trace],
                "layout": {
                    "title": "PCA Scores Plot",
                    "xaxis": {"title": f"PC{pc_x + 1}"},
                    "yaxis": {"title": f"PC{pc_y + 1}"},
                },
            }
        }

    def _plot_biplot(self, model_data: dict, pc_x: int, pc_y: int) -> Dict[str, Any]:
        """Generate PCA biplot data (scores + scaled loading vectors)."""
        scores = model_data.get("scores")
        loadings = model_data.get("loadings")
        if scores is None:
            return {"visualization": {"plot_type": "biplot", "data": [], "layout": {}}}

        if isinstance(scores, SherpaDataset):
            scores_array = np.array(scores.data)
        else:
            scores_array = np.array(scores)
        if scores_array.ndim == 1:
            scores_array = scores_array.reshape(-1, 1)
        if scores_array.size == 0:
            return {"visualization": {"plot_type": "biplot", "data": [], "layout": {}}}

        n_components = scores_array.shape[1]
        pc_x = min(max(0, pc_x), max(0, n_components - 1))
        pc_y = min(max(0, pc_y), max(0, n_components - 1))
        if n_components == 1:
            pc_y = pc_x

        scores_x = scores_array[:, pc_x].astype(float)
        scores_y = scores_array[:, pc_y].astype(float)
        traces: list[dict[str, Any]] = [
            {
                "x": scores_x.tolist(),
                "y": scores_y.tolist(),
                "type": "scatter",
                "mode": "markers",
                "marker": {"size": 8, "color": "#60a5fa", "opacity": 0.8, "line": {"width": 1, "color": "#1d4ed8"}},
                "name": "Scores",
            }
        ]

        if loadings is not None:
            if isinstance(loadings, SherpaDataset):
                loadings_array = np.array(loadings.data)
            else:
                loadings_array = np.array(loadings)

            if loadings_array.ndim == 2 and loadings_array.size > 0:
                # PCA loadings are typically [n_components, n_features].
                if loadings_array.shape[0] > loadings_array.shape[1]:
                    loadings_array = loadings_array.T

                if loadings_array.shape[0] > max(pc_x, pc_y):
                    vec_x = loadings_array[pc_x, :].astype(float)
                    vec_y = loadings_array[pc_y, :].astype(float)
                    norms = np.hypot(vec_x, vec_y)
                    valid = np.isfinite(vec_x) & np.isfinite(vec_y)
                    if np.any(valid):
                        valid_idx = np.where(valid)[0]
                        ranked = valid_idx[np.argsort(norms[valid_idx])[::-1]]
                        selected = ranked[: min(80, ranked.shape[0])]

                        if selected.size > 0:
                            max_score_x = max(float(np.max(np.abs(scores_x))), 1e-12)
                            max_score_y = max(float(np.max(np.abs(scores_y))), 1e-12)
                            max_load_x = max(float(np.max(np.abs(vec_x[selected]))), 1e-12)
                            max_load_y = max(float(np.max(np.abs(vec_y[selected]))), 1e-12)
                            scale = 0.82 * min(max_score_x / max_load_x, max_score_y / max_load_y)

                            lines_x: list[float | None] = []
                            lines_y: list[float | None] = []
                            points_x: list[float] = []
                            points_y: list[float] = []
                            labels: list[str] = []
                            customdata: list[list[float | str]] = []

                            labeled = set(selected[: min(24, selected.size)])
                            for idx in selected:
                                sx = float(vec_x[idx] * scale)
                                sy = float(vec_y[idx] * scale)
                                lines_x.extend([0.0, sx, None])
                                lines_y.extend([0.0, sy, None])
                                points_x.append(sx)
                                points_y.append(sy)
                                labels.append(f"F{idx + 1}" if idx in labeled else "")
                                customdata.append([f"Feature {idx + 1}", float(vec_x[idx]), float(vec_y[idx])])

                            traces.append(
                                {
                                    "x": lines_x,
                                    "y": lines_y,
                                    "type": "scatter",
                                    "mode": "lines",
                                    "line": {"color": "#f59e0b", "width": 1.6},
                                    "name": "Loadings",
                                    "hoverinfo": "skip",
                                }
                            )
                            traces.append(
                                {
                                    "x": points_x,
                                    "y": points_y,
                                    "type": "scatter",
                                    "mode": "markers+text",
                                    "text": labels,
                                    "textposition": "top center",
                                    "textfont": {"size": 10, "color": "#92400e"},
                                    "marker": {"size": 6, "color": "#f97316", "line": {"width": 1, "color": "#7c2d12"}},
                                    "customdata": customdata,
                                    "hovertemplate": (
                                        "%%{customdata[0]}<br>"
                                        "PC%d loading: %%{customdata[1]:.3f}<br>"
                                        "PC%d loading: %%{customdata[2]:.3f}"
                                        "<extra></extra>"
                                    )
                                    % (pc_x + 1, pc_y + 1),
                                    "showlegend": False,
                                }
                            )

        return {
            "visualization": {
                "plot_type": "biplot",
                "data": traces,
                "layout": {
                    "title": "PCA Biplot",
                    "xaxis": {"title": f"PC{pc_x + 1} (scores)", "zeroline": True, "zerolinecolor": "#94a3b8"},
                    "yaxis": {"title": f"PC{pc_y + 1} (scores)", "zeroline": True, "zerolinecolor": "#94a3b8"},
                    "hovermode": "closest",
                },
            }
        }

    def _plot_scatter(self, dataset: SherpaDataset, x_col: int, y_col: int) -> Dict[str, Any]:
        """Generate a scatter plot of two dataset columns (features).

        Uses ``x_axis`` and ``y_axis`` parameters to select which feature
        columns to plot.  When the dataset carries a target vector, each
        class is drawn as a separate trace with a distinct colour.
        """
        data = np.array(dataset.data, dtype=np.float64)
        n_features = data.shape[-1]

        x_col = min(int(x_col), n_features - 1)
        y_col = min(int(y_col), n_features - 1)

        # Resolve axis labels from feature_axis or fallback to index
        feature_axis = dataset.feature_axis
        if (
            feature_axis is not None
            and feature_axis.labels is not None
            and len(feature_axis.labels) > max(x_col, y_col)
        ):
            x_label = str(feature_axis.labels[x_col])
            y_label = str(feature_axis.labels[y_col])
        elif (
            feature_axis is not None
            and feature_axis.values is not None
            and len(feature_axis.values) > max(x_col, y_col)
        ):
            x_label = str(feature_axis.values[x_col])
            y_label = str(feature_axis.values[y_col])
        else:
            x_label = f"Feature {x_col}"
            y_label = f"Feature {y_col}"

        # Check for target-based coloring
        target = dataset.target
        traces: List[Dict[str, Any]] = []

        if target is not None:
            # Resolve class names
            tc = dataset.target_context
            class_names = tc.class_names if tc and tc.class_names else None
            target_names = tc.target_names if tc and tc.target_names else None

            unique_targets = np.unique(target)
            colors = [
                "#3b82f6",
                "#ef4444",
                "#22c55e",
                "#f59e0b",
                "#8b5cf6",
                "#ec4899",
                "#06b6d4",
                "#f97316",
                "#14b8a6",
                "#6366f1",
            ]

            for i, t_val in enumerate(unique_targets):
                mask = target == t_val
                # Determine label
                if class_names and int(t_val) < len(class_names):
                    label = class_names[int(t_val)]
                elif target_names and len(target_names) == 1:
                    label = f"{target_names[0]}={t_val}"
                else:
                    label = str(t_val)

                traces.append(
                    {
                        "x": data[mask, x_col].tolist(),
                        "y": data[mask, y_col].tolist(),
                        "type": "scatter",
                        "mode": "markers",
                        "marker": {"size": 8, "color": colors[i % len(colors)]},
                        "name": label,
                    }
                )
        else:
            traces.append(
                {
                    "x": data[:, x_col].tolist(),
                    "y": data[:, y_col].tolist(),
                    "type": "scatter",
                    "mode": "markers",
                    "marker": {"size": 8, "color": "#3b82f6"},
                    "name": "Samples",
                }
            )

        return {
            "visualization": {
                "plot_type": "scatter",
                "data": traces,
                "layout": {
                    "title": f"Scatter: {x_label} vs {y_label}",
                    "xaxis": {"title": x_label},
                    "yaxis": {"title": y_label},
                    "hovermode": "closest",
                },
            }
        }

    def _plot_generic(self, data: dict) -> Dict[str, Any]:
        """Generate generic plot from data dict."""
        return {
            "visualization": {
                "plot_type": "generic",
                "data": data.get("data", []),
                "layout": data.get("layout", {}),
            }
        }


@register_node
class ExportNode(Node):
    """
    Export node for saving results.

    Exports data to various file formats.
    """

    metadata = NodeMetadata(
        node_type="output.export",
        category="output",
        label="Export",
        description="Export data to file",
        parameters=[
            NodeParameter(
                name="filename",
                label="Filename",
                param_type="text",
                default="output.csv",
                description="Output filename",
                required=True,
            ),
            NodeParameter(
                name="format",
                label="Format",
                param_type="select",
                default="csv",
                options=["csv", "json", "jdx"],
                description="Output file format",
                required=False,
            ),
        ],
        input_types=["NDDataset", "dict"],
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
                name="file_info",
                type_ref="spectrasherpa://types/ValidationResult/1.0",
                required=True,
                label="File Info",
                description="Status and path of exported file",
            ),
        ],
        policy=NodePolicy(
            safe_for_auto_apply=False,
            requires_human_review=True,
            data_egress_risk="full_data",
        ),
    )

    def generate_python(
        self,
        inputs: Dict[str, str],
        indent: str = "    ",
        use_scp: bool = True,
    ) -> List[str]:
        """Generate Python code for data export."""
        input_expr = inputs.get("default", next(iter(inputs.values()), "input_data"))
        filename = self.parameters.get("filename", "output.csv")
        fmt = self.parameters.get("format", "csv")

        lines: List[str] = []
        lines.append(f"{indent}# --- Export ({self.node_id}) ---")
        lines.append(f"{indent}_export_input = {input_expr}")
        lines.append(f"{indent}if hasattr(_export_input, 'data'):")
        lines.append(f"{indent}    _export_data = np.asarray(_export_input.data)")
        lines.append(f"{indent}elif isinstance(_export_input, dict) and 'data' in _export_input:")
        lines.append(f"{indent}    _export_data = np.asarray(_export_input['data'])")
        lines.append(f"{indent}else:")
        lines.append(f"{indent}    _export_data = np.asarray(_export_input)")
        lines.append(f"{indent}if _export_data.ndim == 0:")
        lines.append(f"{indent}    _export_data = _export_data.reshape(1, 1)")
        lines.append(f"{indent}else:")
        lines.append(f"{indent}    _export_data = np.atleast_2d(_export_data)")
        lines.append(f"{indent}_export_is_numeric = (")
        lines.append(f"{indent}    np.issubdtype(_export_data.dtype, np.number)")
        lines.append(f"{indent}    or np.issubdtype(_export_data.dtype, np.bool_)")
        lines.append(f"{indent})")

        # Write next to the script (DATA_DIR sibling) so export_artifacts()
        # can pick it up later.  os is already imported at script level.
        lines.append(f"{indent}_export_path = os.path.join(")
        lines.append(f"{indent}    os.path.dirname(os.path.abspath(__file__)) if '__file__' in dir() else os.getcwd(),")
        lines.append(f"{indent}    {repr(filename)},")
        lines.append(f"{indent})")
        if fmt == "csv":
            lines.append(f"{indent}if _export_is_numeric:")
            lines.append(f"{indent}    np.savetxt(_export_path, _export_data, delimiter=',')")
            lines.append(f"{indent}else:")
            lines.append(f"{indent}    np.savetxt(_export_path, _export_data.astype(str), delimiter=',', fmt='%s')")
        elif fmt == "json":
            lines.append(f"{indent}import json as _json")
            lines.append(f"{indent}with open(_export_path, 'w') as _f:")
            lines.append(f"{indent}    _json.dump(_export_data.tolist(), _f)")
        else:
            # jdx or fallback
            lines.append(f"{indent}if _export_is_numeric:")
            lines.append(f"{indent}    np.savetxt(_export_path, _export_data, delimiter=',')")
            lines.append(f"{indent}else:")
            lines.append(f"{indent}    np.savetxt(_export_path, _export_data.astype(str), delimiter=',', fmt='%s')")

        lines.append(f"{indent}results['{self.node_id}'] = {{")
        lines.append(f"{indent}    'file_info': {{")
        lines.append(f"{indent}        'filename': {repr(filename)},")
        lines.append(f"{indent}        'format': {repr(fmt)},")
        lines.append(f"{indent}        'data_points': int(np.prod(_export_data.shape)),")
        lines.append(f"{indent}    }}")
        lines.append(f"{indent}}}")
        lines.append(f'{indent}print(f"  Export: saved {{_export_data.shape}} to {{_export_path}}")')

        return lines

    async def execute(self, input_data: Any) -> Dict[str, Any]:
        """
        Export data to file.

        Args:
            input_data: Data to export

        Returns:
            Dict with export status and path
        """
        filename = self.parameters.get("filename", "output.csv")
        fmt = self.parameters.get("format", "csv")

        # For now, just return metadata about what would be exported
        # Actual file writing would happen here in production

        # Coerce NDDataset → SherpaDataset so all dataset paths work
        if isinstance(input_data, NDDataset):
            input_data = coerce_to_sherpa(input_data)

        if isinstance(input_data, SherpaDataset):
            shape = input_data.shape
            n_points = np.prod(shape)
        elif isinstance(input_data, dict):
            n_points = len(input_data)
        else:
            n_points = 0

        return {
            "file_info": {
                "status": "ready",
                "filename": filename,
                "format": fmt,
                "data_points": int(n_points),
                "message": f"Ready to export {n_points} data points to {filename}",
            }
        }


@register_node
class StatsSummaryNode(Node):
    """
    Adaptive Statistics node.

    Computes contextual statistics based on input type:
    - NDDataset: spectral statistics, per-sample/feature analysis
    - PCA results: scores/loadings stats, outlier detection
    - MCR results: concentration/spectra statistics
    - Generic arrays: basic descriptive statistics
    """

    metadata = NodeMetadata(
        node_type="stats.summary",
        category="validation",
        label="Statistics",
        description="Compute adaptive statistics based on input type",
        parameters=[
            NodeParameter(
                name="compute_outliers",
                label="Detect Outliers",
                param_type="boolean",
                default=True,
                description="Compute outlier statistics (for PCA data)",
                required=False,
            ),
            NodeParameter(
                name="outlier_threshold",
                label="Outlier Threshold",
                param_type="number",
                default=0.95,
                min_value=0.8,
                max_value=0.99,
                description="Confidence level for outlier detection",
                required=False,
            ),
            NodeParameter(
                name="max_samples",
                label="Max Sample Rows",
                param_type="number",
                default=100,
                min_value=10,
                max_value=500,
                description="Maximum rows in per-sample statistics table",
                required=False,
            ),
        ],
        input_types=["NDDataset", "dict", "array"],
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
                name="statistics",
                type_ref="spectrasherpa://types/ValidationResult/1.0",
                required=True,
                label="Statistics",
                description="Computed statistics and summary",
            ),
        ],
    )

    def generate_python(
        self,
        inputs: Dict[str, str],
        indent: str = "    ",
        use_scp: bool = True,
    ) -> List[str]:
        """Generate Python code for statistics summary."""
        input_expr = inputs.get("default", next(iter(inputs.values()), "input_data"))

        lines: List[str] = []
        lines.append(f"{indent}# --- Statistics ({self.node_id}) ---")
        lines.append(f"{indent}_stats_input = {input_expr}")
        lines.append(f"{indent}if hasattr(_stats_input, 'data'):")
        lines.append(f"{indent}    _stats_data = np.atleast_2d(np.asarray(_stats_input.data, dtype=np.float64))")
        lines.append(f"{indent}elif isinstance(_stats_input, dict):")
        lines.append(f"{indent}    if 'scores' in _stats_input:")
        lines.append(f"{indent}        _sc = _stats_input['scores']")
        lines.append(f"{indent}        _stats_data = np.atleast_2d(")
        lines.append(f"{indent}            np.asarray(")
        lines.append(f"{indent}                _sc.data if hasattr(_sc, 'data') else _sc,")
        lines.append(f"{indent}                dtype=np.float64,")
        lines.append(f"{indent}            )")
        lines.append(f"{indent}        )")
        lines.append(f"{indent}    elif 'data' in _stats_input:")
        lines.append(f"{indent}        _stats_data = np.atleast_2d(np.asarray(_stats_input['data'], dtype=np.float64))")
        lines.append(f"{indent}    else:")
        lines.append(f"{indent}        _stats_data = np.zeros((1, 1))")
        lines.append(f"{indent}else:")
        lines.append(f"{indent}    _stats_data = np.atleast_2d(np.asarray(_stats_input, dtype=np.float64))")
        lines.append(f"{indent}_n_samples, _n_features = _stats_data.shape")
        lines.append(f"{indent}_summary = {{")
        lines.append(f"{indent}    'n_samples': _n_samples, 'n_features': _n_features,")
        lines.append(f"{indent}    'mean': float(np.mean(_stats_data)),")
        lines.append(f"{indent}    'std': float(np.std(_stats_data)),")
        lines.append(f"{indent}    'min': float(np.min(_stats_data)),")
        lines.append(f"{indent}    'max': float(np.max(_stats_data)),")
        lines.append(f"{indent}    'median': float(np.median(_stats_data)),")
        lines.append(f"{indent}}}")
        lines.append(f"{indent}results['{self.node_id}'] = {{'statistics': _summary}}")
        lines.append(
            f'{indent}print(f"  Statistics: {{_n_samples}} samples x {{_n_features}} features, '
            f"mean={{_summary['mean']:.4f}}, std={{_summary['std']:.4f}}\")"
        )

        return lines

    async def execute(self, input_data: Any) -> Dict[str, Any]:
        """
        Compute adaptive statistics based on input type.

        Args:
            input_data: SherpaDataset, PCA/MCR dict, or array data

        Returns:
            Dict with comprehensive statistics and visualization data
        """
        # Detect input type and route to appropriate handler
        if isinstance(input_data, dict):
            if "scores" in input_data or "isPCA" in input_data.get("metadata", {}):
                return await self._stats_pca(input_data)
            elif "C" in input_data or "St" in input_data:
                return await self._stats_mcr(input_data)
            elif "data" in input_data:
                meta = input_data.get("metadata") or {}
                if meta.get("type") == "PeakFinding":
                    return await self._stats_peaks(input_data["data"], meta)
                return await self._stats_array(input_data["data"], meta)

        # Coerce NDDataset → SherpaDataset so all dataset paths work
        if isinstance(input_data, NDDataset):
            input_data = coerce_to_sherpa(input_data)

        if isinstance(input_data, SherpaDataset):
            return await self._stats_dataset(input_data)

        # Fallback to array statistics
        return await self._stats_array(np.array(input_data), None)

    async def _stats_dataset(self, dataset: Any) -> Dict[str, Any]:
        """Compute statistics for SherpaDataset (raw spectra)."""
        data = np.array(dataset.data)
        if data.ndim == 1:
            data = data.reshape(1, -1)

        n_samples, n_features = data.shape

        # Global statistics
        summary = {
            "n_samples": n_samples,
            "n_features": n_features,
            "mean": float(np.mean(data)),
            "std": float(np.std(data)),
            "min": float(np.min(data)),
            "max": float(np.max(data)),
            "median": float(np.median(data)),
            "range": float(np.ptp(data)),
            "q25": float(np.percentile(data, 25)),
            "q75": float(np.percentile(data, 75)),
        }

        # Per-sample statistics
        max_samples = int(self.parameters.get("max_samples", 100))
        sample_stats = []
        for i in range(min(n_samples, max_samples)):
            sample_stats.append(
                {
                    "sample": i + 1,
                    "mean": float(np.mean(data[i])),
                    "std": float(np.std(data[i])),
                    "min": float(np.min(data[i])),
                    "max": float(np.max(data[i])),
                    "median": float(np.median(data[i])),
                }
            )

        # Per-feature statistics (which wavenumbers vary most)
        feature_means = np.mean(data, axis=0)
        feature_stds = np.std(data, axis=0)
        feature_cv = feature_stds / (feature_means + 1e-10)  # Coefficient of variation

        # Get feature axis if available (wavenumber, time, m/z, etc.)
        x_coord = dataset.feature_axis
        if x_coord is not None:
            feature_values = np.array(x_coord.data).tolist()
        else:
            feature_values = list(range(n_features))

        # Build histogram data for distribution visualization
        hist, bin_edges = np.histogram(data.flatten(), bins=50)

        return {
            "statistics": {
                "input_type": "NDDataset",
                "summary": summary,
                "detailed": {
                    "by_sample": sample_stats,
                    "by_feature": {
                        "feature_values": feature_values,
                        "means": feature_means.tolist(),
                        "stds": feature_stds.tolist(),
                        "cv": feature_cv.tolist(),
                    },
                },
                "plots": {
                    "histogram": {
                        "counts": hist.tolist(),
                        "bin_edges": bin_edges.tolist(),
                    },
                    "feature_variation": {
                        "x": feature_values,
                        "y": feature_stds.tolist(),
                        "type": "bar",
                    },
                },
                "data": sample_stats,  # For DataTable compatibility
                "metadata": {
                    "type": "NDDataset",
                    "shape": [n_samples, n_features],
                    "has_wavenumbers": x_coord is not None,
                },
            }
        }

    async def _stats_pca(self, pca_data: dict) -> Dict[str, Any]:
        """Compute statistics for PCA results."""
        # Extract PCA components
        metadata = pca_data.get("metadata", {})
        scores_data = np.array(pca_data.get("data", []))

        if scores_data.ndim == 1:
            scores_data = scores_data.reshape(-1, 1)

        n_obs, n_comp = scores_data.shape

        # Scores statistics per PC
        pc_stats = []
        for i in range(n_comp):
            pc_stats.append(
                {
                    "pc": i + 1,
                    "mean": float(np.mean(scores_data[:, i])),
                    "std": float(np.std(scores_data[:, i])),
                    "min": float(np.min(scores_data[:, i])),
                    "max": float(np.max(scores_data[:, i])),
                    "range": float(np.ptp(scores_data[:, i])),
                }
            )

        # Outlier detection using Hotelling's T² (if enabled)
        outliers = []
        if self.parameters.get("compute_outliers", True):
            # Simplified T² calculation
            cov = np.cov(scores_data.T)
            try:
                inv_cov = np.linalg.inv(cov)
                means = np.mean(scores_data, axis=0)

                threshold = self.parameters.get("outlier_threshold", 0.95)
                from scipy.stats import chi2

                t2_limit = chi2.ppf(threshold, n_comp)

                for i in range(n_obs):
                    diff = scores_data[i] - means
                    t2 = diff @ inv_cov @ diff
                    if t2 > t2_limit:
                        outliers.append(
                            {
                                "sample": i + 1,
                                "t2_statistic": float(t2),
                                "threshold": float(t2_limit),
                            }
                        )
            except (np.linalg.LinAlgError, ValueError):
                # Singular covariance or insufficient data — skip outlier detection
                pass

        # Explained variance
        evr = metadata.get("explained_variance_ratio", [])
        cumulative_var = np.cumsum(evr).tolist() if evr else []
        spe = pca_data.get("spe") or metadata.get("spe") or []
        t2 = pca_data.get("t2") or metadata.get("t2") or []
        spe_mean = metadata.get("spe_mean")
        spe_p95 = metadata.get("spe_p95")
        t2_mean = metadata.get("t2_mean")
        t2_p95 = metadata.get("t2_p95")

        return {
            "statistics": {
                "input_type": "PCA",
                "summary": {
                    "n_observations": n_obs,
                    "n_components": n_comp,
                    "total_variance_explained": float(sum(evr)) if evr else 0.0,
                    "n_outliers": len(outliers),
                    "spe_mean": float(spe_mean) if spe_mean is not None else None,
                    "spe_p95": float(spe_p95) if spe_p95 is not None else None,
                    "t2_mean": float(t2_mean) if t2_mean is not None else None,
                    "t2_p95": float(t2_p95) if t2_p95 is not None else None,
                },
                "detailed": {
                    "by_pc": pc_stats,
                    "outliers": outliers,
                    "variance": {
                        "explained_variance_ratio": evr,
                        "cumulative": cumulative_var,
                    },
                    "diagnostics": {
                        "t2": t2,
                        "spe": spe,
                    },
                },
                "plots": {
                    "scree": {
                        "x": list(range(1, len(evr) + 1)),
                        "y": evr,
                        "type": "bar",
                    },
                    "cumulative_variance": {
                        "x": list(range(1, len(cumulative_var) + 1)),
                        "y": cumulative_var,
                        "type": "scatter",
                    },
                },
                "data": pc_stats,  # For DataTable
                "metadata": {
                    "type": "PCA",
                    "shape": [n_obs, n_comp],
                    "has_outliers": len(outliers) > 0,
                },
            }
        }

    async def _stats_mcr(self, mcr_data: dict) -> Dict[str, Any]:
        """Compute statistics for MCR-ALS results."""
        # Extract concentration (C) and spectra (St) matrices
        C = np.array(mcr_data.get("C", mcr_data.get("concentrations", {}).get("data", [])))
        St = np.array(mcr_data.get("St", mcr_data.get("spectra", {}).get("data", [])))

        n_obs, n_comp = C.shape if C.size > 0 else (0, 0)

        # Concentration statistics
        conc_stats = []
        for i in range(n_comp):
            conc_stats.append(
                {
                    "component": i + 1,
                    "mean_conc": float(np.mean(C[:, i])),
                    "max_conc": float(np.max(C[:, i])),
                    "min_conc": float(np.min(C[:, i])),
                    "range": float(np.ptp(C[:, i])),
                }
            )

        # Pure spectra statistics
        spectra_stats = []
        for i in range(n_comp):
            spectra_stats.append(
                {
                    "component": i + 1,
                    "max_absorbance": float(np.max(St[i])) if St.size > 0 else 0.0,
                    "mean_absorbance": float(np.mean(St[i])) if St.size > 0 else 0.0,
                }
            )

        return {
            "statistics": {
                "input_type": "MCR",
                "summary": {
                    "n_observations": n_obs,
                    "n_components": n_comp,
                    "n_wavenumbers": St.shape[1] if St.size > 0 else 0,
                },
                "detailed": {
                    "concentrations": conc_stats,
                    "pure_spectra": spectra_stats,
                },
                "plots": {
                    "concentration_ranges": {
                        "components": [f"Comp {i+1}" for i in range(n_comp)],
                        "max_values": [float(np.max(C[:, i])) for i in range(n_comp)],
                        "type": "bar",
                    },
                },
                "data": conc_stats,  # For DataTable
                "metadata": {
                    "type": "MCR",
                    "shape": [n_obs, n_comp],
                },
            }
        }

    async def _stats_peaks(self, rows: list, metadata: dict) -> Dict[str, Any]:
        """Compute statistics for peak-finding consensus results.

        Each row is a dict with keys: median_pos, mean_pos, std_pos, min_pos,
        max_pos, count, detected, median_height, q1_height, q3_height.

        Two axes of variation are reported:
        - **Horizontal (positional)**: within each cluster, how much do
          detected positions scatter across samples (std_pos, min–max range).
        - **Vertical (intensity)**: across clusters, how do median heights
          compare and how tight is the IQR (q1–q3).
        """
        n_peaks = len(rows)
        n_samples = metadata.get("n_samples", 0)
        x_title = metadata.get("x_title", "Position")
        x_units = metadata.get("x_units", "")
        unit_suffix = f" ({x_units})" if x_units else ""

        # Build per-peak table rows for DataTable display
        table_rows = []
        horizontal_stats = []  # positional scatter per cluster
        vertical_stats = []  # intensity variation per cluster

        for i, row in enumerate(rows):
            median_pos = float(row.get("median_pos", 0))
            std_pos = float(row.get("std_pos", 0))
            min_pos = float(row.get("min_pos", median_pos))
            max_pos = float(row.get("max_pos", median_pos))
            count = int(row.get("count", 0))
            fraction = row.get("detected", f"{count}/{n_samples}")
            med_h = float(row.get("median_height", 0))
            q1_h = float(row.get("q1_height", med_h))
            q3_h = float(row.get("q3_height", med_h))

            label = f"Peak {i + 1}"

            table_rows.append(
                {
                    "peak": i + 1,
                    "position": median_pos,
                    "pos_std": std_pos,
                    "pos_range": f"{min_pos:.1f}–{max_pos:.1f}",
                    "height": med_h,
                    "height_iqr": f"{q1_h:.4f}–{q3_h:.4f}",
                    "detected": fraction,
                    "detection_rate": f"{count / n_samples * 100:.0f}%" if n_samples else "–",
                }
            )

            # Horizontal: positional scatter within this cluster
            horizontal_stats.append(
                {
                    "label": label,
                    "median_pos": median_pos,
                    "std_pos": std_pos,
                    "min_pos": min_pos,
                    "max_pos": max_pos,
                    "range": max_pos - min_pos,
                }
            )

            # Vertical: intensity variation within this cluster
            vertical_stats.append(
                {
                    "label": label,
                    "median_pos": median_pos,
                    "median_height": med_h,
                    "q1_height": q1_h,
                    "q3_height": q3_h,
                    "iqr": q3_h - q1_h,
                }
            )

        # Global summary
        if n_peaks > 0:
            heights = [cast(float, v["median_height"]) for v in vertical_stats]
            pos_stds = [cast(float, h["std_pos"]) for h in horizontal_stats]
            summary = {
                "n_peaks": n_peaks,
                "n_samples": n_samples,
                "n_total_detections": metadata.get("n_total_detections", 0),
                "position_range": [horizontal_stats[0]["median_pos"], horizontal_stats[-1]["median_pos"]],
                "mean_height": float(np.mean(heights)),
                "std_height": float(np.std(heights)),
                "max_positional_std": float(max(pos_stds)),
                "mean_positional_std": float(np.mean(pos_stds)),
            }
        else:
            summary = {"n_peaks": 0}

        summary["x_label"] = f"{x_title}{unit_suffix}"

        return {
            "statistics": {
                "input_type": "PeakFinding",
                "summary": summary,
                "data": table_rows,
                "horizontal": horizontal_stats,
                "vertical": vertical_stats,
                "metadata": metadata,
            }
        }

    async def _stats_array(self, data: np.ndarray, metadata: Optional[dict]) -> Dict[str, Any]:
        """Compute basic statistics for generic array data."""
        data = np.array(data)
        if data.ndim == 1:
            data = data.reshape(1, -1)

        summary = {
            "n_samples": data.shape[0],
            "n_features": data.shape[1],
            "mean": float(np.mean(data)),
            "std": float(np.std(data)),
            "min": float(np.min(data)),
            "max": float(np.max(data)),
            "median": float(np.median(data)),
        }

        return {
            "statistics": {
                "input_type": "array",
                "summary": summary,
                "data": [summary],  # For DataTable
                "metadata": metadata or {},
            }
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
            input_data: SherpaDataset with 2D spectral data (samples × wavenumbers)

        Returns:
            Dict with Plotly-compatible contour/heatmap configuration
        """
        colorscale = self.parameters.get("colorscale", "Viridis")
        plot_type = self.parameters.get("plot_type", "heatmap")
        reverse_x = self.parameters.get("reverse_x", True)
        transpose = self.parameters.get("transpose", False)

        # Coerce NDDataset → SherpaDataset so all dataset paths work
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


@register_node
class DataTableNode(Node):
    """
    Data Table visualization node.

    Displays tabular data with interactive features like sorting, filtering,
    and column selection. Useful for inspecting numerical results, model outputs,
    and statistical summaries.
    """

    metadata = NodeMetadata(
        node_type="output.data_table",
        category="output",
        label="Data Table",
        description="Display data in an interactive table with sorting and filtering",
        parameters=[
            NodeParameter(
                name="max_rows",
                label="Max Rows",
                param_type="number",
                default=100,
                min_value=10,
                max_value=1000,
                step=10,
                description="Maximum number of rows to display",
                required=False,
            ),
            NodeParameter(
                name="transpose",
                label="Transpose",
                param_type="boolean",
                default=False,
                description="Swap rows and columns",
                required=False,
            ),
            NodeParameter(
                name="show_index",
                label="Show Index",
                param_type="boolean",
                default=True,
                description="Display row indices",
                required=False,
            ),
        ],
        input_types=["NDDataset", "dict", "array"],
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
                label="Table Data",
                description="Table configuration and data",
            ),
        ],
    )

    async def execute(self, input_data: Any) -> Dict[str, Any]:
        """
        Convert input data to table format.

        Args:
            input_data: Data to display in table (SherpaDataset, dict, or array)

        Returns:
            Dict with table data (columns, rows) and metadata
        """
        max_rows = self.parameters.get("max_rows", 100)
        transpose = self.parameters.get("transpose", False)
        show_index = self.parameters.get("show_index", True)

        # Coerce NDDataset → SherpaDataset so all dataset paths work
        if isinstance(input_data, NDDataset):
            input_data = coerce_to_sherpa(input_data)

        # Convert input to table format
        if isinstance(input_data, SherpaDataset):
            table_data = self._table_from_dataset(input_data, max_rows, transpose, show_index)
        elif isinstance(input_data, dict):
            table_data = self._table_from_dict(input_data, max_rows, transpose, show_index)
        elif isinstance(input_data, (list, np.ndarray)):
            table_data = self._table_from_array(input_data, max_rows, transpose, show_index)
        else:
            table_data = {
                "columns": [],
                "rows": [],
                "metadata": {"type": "empty", "message": "No data to display"},
            }

        return {"visualization": table_data}

    def _table_from_dataset(self, dataset: Any, max_rows: int, transpose: bool, show_index: bool) -> Dict[str, Any]:
        """Convert SherpaDataset to table format."""
        data = np.array(dataset.data)

        # Handle 1D data
        if data.ndim == 1:
            data = data.reshape(-1, 1)

        n_rows, n_cols = data.shape

        # Apply max_rows limit
        if n_rows > max_rows:
            data = data[:max_rows]
            truncated = True
        else:
            truncated = False

        # Transpose if requested
        if transpose:
            data = data.T
            n_rows, n_cols = n_cols, n_rows

        # Build column headers
        x_coord = dataset.feature_axis
        if x_coord is not None and not transpose:
            # Use feature axis values (wavenumber/time/m/z/etc.) as column headers
            x_vals = np.array(x_coord.data)
            if len(x_vals) == n_cols:
                columns = [f"{float(x):.2f}" for x in x_vals[:n_cols]]
            else:
                columns = [f"Col_{i+1}" for i in range(n_cols)]
        else:
            columns = [f"Col_{i+1}" for i in range(n_cols)]

        # Build rows
        rows = []
        for i in range(n_rows):
            row_data = data[i].tolist()
            rows.append({"index": i, "values": row_data} if show_index else {"values": row_data})

        return {
            "columns": columns,
            "rows": rows,
            "metadata": {
                "type": "NDDataset",
                "shape": dataset.shape,
                "n_rows": n_rows,
                "n_cols": n_cols,
                "truncated": truncated,
                "show_index": show_index,
            },
        }

    def _table_from_dict(
        self, data: Dict[str, Any], max_rows: int, transpose: bool, show_index: bool
    ) -> Dict[str, Any]:
        """Convert dict to table format."""
        # Handle common dict structures from modeling nodes
        if "data" in data and isinstance(data["data"], (list, np.ndarray)):
            # Use 'data' field (e.g., from PCA, MCR nodes)
            return self._table_from_array(data["data"], max_rows, transpose, show_index)

        elif "scores" in data:
            # PCA scores
            scores = np.array(data["scores"])
            if scores.ndim == 1:
                scores = scores.reshape(-1, 1)

            n_rows = min(scores.shape[0], max_rows)
            n_cols = scores.shape[1] if scores.ndim > 1 else 1

            columns = data.get("pc_labels", [f"PC{i+1}" for i in range(n_cols)])
            rows = [
                {"index": i, "values": scores[i].tolist()} if show_index else {"values": scores[i].tolist()}
                for i in range(n_rows)
            ]

            return {
                "columns": columns[:n_cols],
                "rows": rows,
                "metadata": {
                    "type": "PCA_scores",
                    "n_rows": n_rows,
                    "n_cols": n_cols,
                    "truncated": scores.shape[0] > max_rows,
                },
            }

        # Fallback: treat dict as key-value table
        items = list(data.items())[:max_rows]
        return {
            "columns": ["Key", "Value"],
            "rows": [
                {"index": i, "values": [str(k), str(v)]} if show_index else {"values": [str(k), str(v)]}
                for i, (k, v) in enumerate(items)
            ],
            "metadata": {
                "type": "dict",
                "n_rows": len(items),
                "n_cols": 2,
                "truncated": len(data) > max_rows,
            },
        }

    def _table_from_array(self, data: Any, max_rows: int, transpose: bool, show_index: bool) -> Dict[str, Any]:
        """Convert array to table format."""
        arr = np.array(data)

        # Handle 1D arrays
        if arr.ndim == 1:
            arr = arr.reshape(-1, 1)

        n_rows, n_cols = arr.shape

        # Apply max_rows limit
        if n_rows > max_rows:
            arr = arr[:max_rows]
            truncated = True
        else:
            truncated = False

        # Transpose if requested
        if transpose:
            arr = arr.T
            n_rows, n_cols = n_cols, n_rows

        columns = [f"Col_{i+1}" for i in range(n_cols)]
        rows = [
            {"index": i, "values": arr[i].tolist()} if show_index else {"values": arr[i].tolist()}
            for i in range(n_rows)
        ]

        return {
            "columns": columns,
            "rows": rows,
            "metadata": {
                "type": "array",
                "shape": arr.shape,
                "n_rows": n_rows,
                "n_cols": n_cols,
                "truncated": truncated,
                "show_index": show_index,
            },
        }
