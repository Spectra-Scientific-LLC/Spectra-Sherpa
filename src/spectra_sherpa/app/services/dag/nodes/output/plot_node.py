"""
Plot visualization node.
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
        _p = f"_plot_input_{_nid}"  # shorthand for generated variable
        lines.append(f"{indent}{_p} = {input_expr}")
        lines.append(f"{indent}_plot_kind_{_nid} = None")
        lines.append(f"{indent}_plot_metadata_{_nid} = {{}}")
        lines.append(f"{indent}if isinstance({_p}, dict)" f" and {_p}.get('type') == 'predicted_vs_actual':")
        lines.append(f"{indent}    _plot_kind_{_nid} = 'predicted_vs_actual'")
        lines.append(f"{indent}    _plot_source_{_nid} = {_p}")
        lines.append(f"{indent}    _plot_metadata_{_nid} = {_p}.get('metadata') or {{}}")
        lines.append(
            f"{indent}    _plot_data_{_nid} = np.atleast_2d(" f"np.asarray({_p}.get('data', []), dtype=np.float64))"
        )
        lines.append(f"{indent}elif isinstance({_p}, dict)" f" and {_p}.get('type') == 'confusion_matrix':")
        lines.append(f"{indent}    _plot_kind_{_nid} = 'confusion_matrix'")
        lines.append(f"{indent}    _plot_source_{_nid} = {_p}")
        lines.append(f"{indent}    _plot_metadata_{_nid} = {_p}.get('metadata') or {{}}")
        lines.append(
            f"{indent}    _plot_data_{_nid} = np.atleast_2d(" f"np.asarray({_p}.get('data', []), dtype=np.float64))"
        )
        lines.append(f"{indent}elif isinstance(_plot_input_{_nid}, dict) and 'scores' in _plot_input_{_nid}:")
        lines.append(f"{indent}    _plot_source_{_nid} = _plot_input_{_nid}['scores']")
        lines.append(f"{indent}    _plot_data_{_nid} = (")
        lines.append(f"{indent}        np.asarray(_plot_source_{_nid}.data, dtype=np.float64)")
        lines.append(f"{indent}        if hasattr(_plot_source_{_nid}, 'data')")
        lines.append(f"{indent}        else np.asarray(_plot_source_{_nid}, dtype=np.float64)")
        lines.append(f"{indent}    )")
        lines.append(f"{indent}    _plot_data_{_nid} = np.atleast_2d(_plot_data_{_nid})")
        lines.append(f"{indent}elif isinstance(_plot_input_{_nid}, dict) and 'loadings' in _plot_input_{_nid}:")
        lines.append(f"{indent}    _plot_source_{_nid} = _plot_input_{_nid}['loadings']")
        lines.append(f"{indent}    _plot_data_{_nid} = (")
        lines.append(f"{indent}        np.asarray(_plot_source_{_nid}.data, dtype=np.float64)")
        lines.append(f"{indent}        if hasattr(_plot_source_{_nid}, 'data')")
        lines.append(f"{indent}        else np.asarray(_plot_source_{_nid}, dtype=np.float64)")
        lines.append(f"{indent}    )")
        lines.append(f"{indent}    _plot_data_{_nid} = np.atleast_2d(_plot_data_{_nid})")
        lines.append(f"{indent}else:")
        lines.append(f"{indent}    _plot_source_{_nid} = _plot_input_{_nid}")
        lines.append(f"{indent}    _plot_data_{_nid} = (")
        lines.append(f"{indent}        np.asarray(_plot_source_{_nid}.data, dtype=np.float64)")
        lines.append(f"{indent}        if hasattr(_plot_source_{_nid}, 'data')")
        lines.append(f"{indent}        else np.asarray(_plot_source_{_nid}, dtype=np.float64)")
        lines.append(f"{indent}    )")
        lines.append(f"{indent}    _plot_data_{_nid} = np.atleast_2d(_plot_data_{_nid})")
        lines.append(f"{indent}_x_values_{_nid} = None")
        lines.append(f"{indent}_x_title_{_nid} = 'Feature'")
        lines.append(f"{indent}_x_units_{_nid} = ''")
        lines.append(f"{indent}_y_title_{_nid} = 'Intensity'")
        lines.append(f"{indent}if _plot_kind_{_nid} == 'predicted_vs_actual':")
        lines.append(f"{indent}    _x_title_{_nid} = 'Actual'")
        lines.append(f"{indent}    _y_title_{_nid} = 'Predicted'")
        lines.append(f"{indent}elif _plot_kind_{_nid} == 'confusion_matrix':")
        lines.append(f"{indent}    _x_title_{_nid} = 'Predicted Class'")
        lines.append(f"{indent}    _y_title_{_nid} = 'True Class'")
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

        if plot_type == "scatter":
            lines.append(f"{indent}_fig_{_nid} = go.Figure()")
            lines.append(f"{indent}if _plot_kind_{_nid} == 'predicted_vs_actual' and _plot_data_{_nid}.shape[1] >= 2:")
            lines.append(
                f"{indent}    _fig_{_nid}.add_trace(go.Scatter("
                f"x=_plot_data_{_nid}[:, 0], y=_plot_data_{_nid}[:, 1], mode='markers', name='Predictions'))"
            )
            lines.append(f"{indent}    _min_v = float(np.min(_plot_data_{_nid})) if _plot_data_{_nid}.size else 0.0")
            lines.append(f"{indent}    _max_v = float(np.max(_plot_data_{_nid})) if _plot_data_{_nid}.size else 1.0")
            lines.append(
                f"{indent}    _fig_{_nid}.add_trace(go.Scatter("
                f"x=[_min_v, _max_v], y=[_min_v, _max_v], mode='lines', name='Ideal'))"
            )
            lines.append(
                f"{indent}    _fig_{_nid}.update_layout("
                f"template='plotly_white', title='Predicted vs Actual', "
                f"xaxis_title=_x_title_{_nid}, yaxis_title=_y_title_{_nid})"
            )
            lines.append(f"{indent}else:")
            lines.append(
                f"{indent}    _fig_{_nid}.add_trace(go.Scatter("
                f"x=_plot_data_{_nid}[:, 0], "
                f"y=_plot_data_{_nid}[:, 1] if _plot_data_{_nid}.shape[1] > 1 else _plot_data_{_nid}[:, 0], "
                f"mode='markers', name='Scatter'))"
            )
            lines.append(
                f"{indent}    _fig_{_nid}.update_layout("
                f"template='plotly_white', title='Scatter Plot', "
                f"xaxis_title=_x_title_{_nid}, "
                f"yaxis_title=_y_title_{_nid})"
            )
        elif plot_type in ("spectra",):
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
            lines.append(f"{indent}if _plot_kind_{_nid} == 'confusion_matrix':")
            lines.append(f"{indent}    _classes = _plot_metadata_{_nid}.get('classes')")
            _pd = f"_plot_data_{_nid}"
            lines.append(
                f"{indent}    if isinstance(_classes, list)" f" and len(_classes) == {_pd}.shape[0] == {_pd}.shape[1]:"
            )
            lines.append(f"{indent}        _xv = _classes")
            lines.append(f"{indent}        _yv = _classes")
            lines.append(f"{indent}    else:")
            lines.append(f"{indent}        _xv = np.arange(_plot_data_{_nid}.shape[1])")
            lines.append(f"{indent}        _yv = np.arange(_plot_data_{_nid}.shape[0])")
            lines.append(f"{indent}_fig_{_nid} = go.Figure(")
            if plot_type == "contour":
                lines.append(f"{indent}    data=go.Contour(z=_plot_data_{_nid}, x=_xv, y=_yv, colorscale='Viridis')")
            else:
                lines.append(f"{indent}    data=go.Heatmap(z=_plot_data_{_nid}, x=_xv, y=_yv, colorscale='Viridis')")
            lines.append(f"{indent})")
            lines.append(
                f"{indent}_fig_{_nid}.update_layout(template='plotly_white', title='{plot_type.title()} Plot', "
                f"xaxis_title=_x_title_{_nid} if _plot_kind_{_nid} == 'confusion_matrix' else _x_label_{_nid}, "
                f"yaxis_title=_y_title_{_nid} if _plot_kind_{_nid} == 'confusion_matrix' else 'Sample Index')"
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

        # Coerce NDDataset -> SherpaDataset so all dataset paths work
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
            if input_data.get("type") == "predicted_vs_actual":
                return self._plot_predicted_vs_actual(input_data)
            if input_data.get("type") == "confusion_matrix":
                return self._plot_confusion_matrix(input_data)
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

        # X-axis (feature axis -- wavelength, wavenumber, etc.)
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

    def _plot_predicted_vs_actual(self, data: dict) -> Dict[str, Any]:
        """Generate a regression holdout scatter plot.

        Accepts two payload shapes from HoldoutEvaluation:

        * Single-target (legacy):
          ``{"data": [[actual, predicted], ...], "type": "predicted_vs_actual"}``
        * Multi-target PLS2:
          ``{"series": [{"name": str, "actual": [...], "predicted": [...]}],
             "type": "predicted_vs_actual"}``

        Multi-target renders each target as its own marker series on shared
        axes.  Targets may have different units, so the 45° ideal line is
        drawn from the combined min/max as a visual anchor only — judge
        goodness of fit per-series, not globally.
        """
        series_payload = data.get("series")
        if isinstance(series_payload, list) and series_payload:
            traces: list[dict] = []
            all_actual: list[float] = []
            all_predicted: list[float] = []
            for s in series_payload:
                if not isinstance(s, dict):
                    continue
                name = str(s.get("name", "Target"))
                series_actual = [float(v) for v in s.get("actual", [])]
                series_predicted = [float(v) for v in s.get("predicted", [])]
                if not series_actual or not series_predicted:
                    continue
                traces.append(
                    {
                        "x": series_actual,
                        "y": series_predicted,
                        "type": "scatter",
                        "mode": "markers",
                        "name": name,
                    }
                )
                all_actual.extend(series_actual)
                all_predicted.extend(series_predicted)

            if all_actual and all_predicted:
                lo = min(min(all_actual), min(all_predicted))
                hi = max(max(all_actual), max(all_predicted))
            else:
                lo, hi = 0.0, 1.0
            traces.append(
                {
                    "x": [lo, hi],
                    "y": [lo, hi],
                    "type": "scatter",
                    "mode": "lines",
                    "name": "Ideal",
                    "line": {"dash": "dash", "color": "#888"},
                }
            )

            # When HoldoutEvaluation resolved real reference property names
            # (via its ``context`` port), incorporate them into the axis
            # titles so the plot is self-describing.  Falls back to generic
            # "Predicted" labels when the metadata carries Target_1..N.
            metadata = data.get("metadata") or {}
            raw_names = metadata.get("target_names")
            if isinstance(raw_names, list):
                name_list = [str(n) for n in raw_names if n]
            else:
                name_list = []
            has_real_names = bool(name_list) and not all(str(n).startswith("Target_") for n in name_list)
            if has_real_names:
                joined = ", ".join(name_list)
                title_text = f"Predicted vs Actual \u2014 {joined}"
                y_title = f"Predicted ({joined})"
            else:
                title_text = "Predicted vs Actual (per target)"
                y_title = "Predicted"

            return {
                "visualization": {
                    "plot_type": "scatter",
                    "data": traces,
                    "layout": {
                        "title": title_text,
                        "xaxis": {"title": "Actual"},
                        "yaxis": {"title": y_title},
                    },
                }
            }

        # Legacy single-target path.
        pairs = np.asarray(data.get("data", []), dtype=np.float64)
        if pairs.ndim == 1:
            pairs = pairs.reshape(-1, 2) if pairs.size else np.zeros((0, 2))

        actual = pairs[:, 0].tolist() if pairs.shape[1] >= 1 else []
        predicted = pairs[:, 1].tolist() if pairs.shape[1] >= 2 else []
        if actual and predicted:
            lo = min(min(actual), min(predicted))
            hi = max(max(actual), max(predicted))
        else:
            lo, hi = 0.0, 1.0

        return {
            "visualization": {
                "plot_type": "scatter",
                "data": [
                    {
                        "x": actual,
                        "y": predicted,
                        "type": "scatter",
                        "mode": "markers",
                        "name": "Predictions",
                    },
                    {
                        "x": [lo, hi],
                        "y": [lo, hi],
                        "type": "scatter",
                        "mode": "lines",
                        "name": "Ideal",
                    },
                ],
                "layout": {
                    "title": "Predicted vs Actual",
                    "xaxis": {"title": "Actual"},
                    "yaxis": {"title": "Predicted"},
                },
            }
        }

    def _plot_confusion_matrix(self, data: dict) -> Dict[str, Any]:
        """Generate a confusion-matrix heatmap."""
        matrix = np.asarray(data.get("data", []), dtype=np.float64)
        if matrix.ndim == 1:
            matrix = matrix.reshape(1, -1)

        x_labels = list(range(matrix.shape[1]))
        y_labels = list(range(matrix.shape[0]))
        metadata = data.get("metadata") or {}
        classes = metadata.get("classes")
        if isinstance(classes, list) and len(classes) == matrix.shape[0] == matrix.shape[1]:
            x_labels = classes
            y_labels = classes

        return {
            "visualization": {
                "plot_type": "heatmap",
                "data": [
                    {
                        "x": x_labels,
                        "y": y_labels,
                        "z": matrix.tolist(),
                        "type": "heatmap",
                        "colorscale": "Viridis",
                    }
                ],
                "layout": {
                    "title": "Confusion Matrix",
                    "xaxis": {"title": "Predicted Class"},
                    "yaxis": {"title": "True Class"},
                },
            }
        }
