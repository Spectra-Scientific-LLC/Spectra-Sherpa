"""
Plot visualization node.
"""

from __future__ import annotations

from typing import Any, Dict, List

import numpy as np

from spectra_sherpa.app.lib.data_roles import get_dataset_data_role
from spectra_sherpa.app.lib.scp_compat import NDDataset
from spectra_sherpa.app.lib.sherpa_dataset import SherpaDataset
from spectra_sherpa.app.services.dag.io_contracts import coerce_to_sherpa

from ...node_base import Node, NodeMetadata, NodeParameter, PortMetadata, register_node
from ._helpers import get_axis_display_info


def _is_numeric_array(arr: np.ndarray) -> bool:
    """Return True when an array can support numeric plotting."""
    return np.issubdtype(arr.dtype, np.number) or np.issubdtype(arr.dtype, np.bool_)


def _dataset_meta(dataset: Any) -> dict[str, Any]:
    meta = getattr(dataset, "meta", None)
    return meta if isinstance(meta, dict) else {}


def _is_score_dataset(dataset: SherpaDataset) -> bool:
    """Return True for PCA/PLS score matrices carried as feature tables."""
    meta = _dataset_meta(dataset)
    model_type = str(meta.get("type", "")).upper()
    title = str(getattr(dataset, "title", "") or "").lower()
    axis_title = str(getattr(getattr(dataset, "feature_axis", None), "title", "") or "").lower()
    if bool(meta.get("isPCA")) or model_type in {"PCA", "PLS", "PLS_DA", "SIMCA"}:
        if "score" in title or any(term in axis_title for term in ("principal component", "latent variable", "pc")):
            return True
    return "score" in title and any(term in axis_title for term in ("principal component", "latent variable", "pc"))


def _is_profile_dataset(dataset: SherpaDataset) -> bool:
    """Return True for sample-by-component profiles that should plot columns over samples."""
    meta = _dataset_meta(dataset)
    model_type = str(meta.get("type", "")).upper()
    title = str(getattr(dataset, "title", "") or "").lower()
    axis_title = str(getattr(getattr(dataset, "feature_axis", None), "title", "") or "").lower()
    return (
        "concentration profile" in title
        or "concentrations" in title
        or "eigenvalues" in title
        or (model_type.startswith("MCR") and "component" in axis_title)
        or (model_type == "EFA" and "component" in axis_title)
    )


def _looks_like_plot_payload(value: Any) -> bool:
    if not isinstance(value, dict):
        return False
    return isinstance(value.get("data"), list) and isinstance(value.get("layout"), dict)


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
                options=["spectra", "contour", "heatmap", "scores", "biplot", "loadings", "scatter", "dendrogram"],
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
            if plot_type == "biplot":
                return self._plot_biplot({"scores": input_data}, x_axis, y_axis)
            if plot_type == "scores" or (plot_type == "spectra" and _is_score_dataset(input_data)):
                return self._plot_scores({"scores": input_data}, x_axis, y_axis)
            if plot_type == "spectra" and _is_profile_dataset(input_data):
                return self._plot_profiles(input_data)
            if plot_type in ("contour", "heatmap"):
                colorscale = self.parameters.get("colorscale", "Viridis")
                return self._plot_contour(input_data, plot_type, colorscale)
            if plot_type == "scatter":
                return self._plot_scatter(input_data, x_axis, y_axis)
            return self._plot_spectra(input_data)

        # Handle dict input (e.g., from PCA node)
        if isinstance(input_data, dict):
            plot_payload = self._select_plot_payload(input_data)
            if plot_payload is not None:
                return plot_payload
            if input_data.get("type") == "predicted_vs_actual":
                return self._plot_predicted_vs_actual(input_data)
            if input_data.get("type") == "confusion_matrix":
                return self._plot_confusion_matrix(input_data)
            if input_data.get("type") == "dendrogram":
                return self._plot_dendrogram_payload(input_data)
            if "per_feature_rmse" in input_data or "rmse_transfer" in input_data:
                return self._plot_transfer_error(input_data)
            if "scores" in input_data or "X_scores" in input_data:
                scores_payload = {
                    "scores": (
                        input_data.get("scores") if input_data.get("scores") is not None else input_data.get("X_scores")
                    ),
                    "loadings": (
                        input_data.get("loadings")
                        if input_data.get("loadings") is not None
                        else input_data.get("X_loadings")
                    ),
                }
                if plot_type == "biplot":
                    return self._plot_biplot(scores_payload, x_axis, y_axis)
                return self._plot_scores(scores_payload, x_axis, y_axis)
            if self._is_regression_cv_metrics(input_data):
                return self._plot_regression_cv_metrics(input_data)
            if "data" in input_data:
                return self._plot_generic(input_data)
            if isinstance(input_data.get("default"), SherpaDataset):
                return await self.execute(input_data["default"])
            if isinstance(input_data.get("default"), dict):
                return await self.execute(input_data["default"])
            for key in (
                "transformed",
                "result",
                "predictions",
                "labels",
                "cluster_assignment",
                "y_pred",
                "probabilities",
                "class_probabilities",
                "distances",
                "neighbor_indices",
                "class_distance_matrix",
            ):
                if key in input_data and input_data[key] is not None:
                    return self._plot_array(
                        input_data[key],
                        plot_type,
                        x_axis,
                        y_axis,
                        title=key.replace("_", " ").title(),
                    )

        if isinstance(input_data, (list, tuple, np.ndarray)):
            return self._plot_array(input_data, plot_type, x_axis, y_axis)

        # Fallback
        # Fallback
        result = {
            "plot_type": plot_type,
            "data": [],
            "layout": {"title": "No data to plot"},
        }
        return {"visualization": result}

    def _select_plot_payload(self, input_data: dict[str, Any]) -> dict[str, Any] | None:
        """Pass through pre-built Plotly payloads from modeling/classification nodes."""
        if _looks_like_plot_payload(input_data):
            return {"visualization": self._normalize_plot_payload(input_data)}

        plots = input_data.get("plots")
        if isinstance(plots, dict):
            preferred_keys = (
                str(self.parameters.get("plot_key", "") or ""),
                "default",
                "simca_acceptance",
                "coomans",
                "t2_q",
                "scores",
                "confusion_matrix_cv",
                "confusion_matrix_train",
            )
            for key in preferred_keys:
                payload = plots.get(key) if key else None
                if _looks_like_plot_payload(payload):
                    return {"visualization": self._normalize_plot_payload(payload)}
            for payload in plots.values():
                if _looks_like_plot_payload(payload):
                    return {"visualization": self._normalize_plot_payload(payload)}

        # Some template edges pass the plots registry itself (for example
        # from_output: plots) instead of the full model dict. Treat that bare
        # registry the same way as a nested model["plots"] value.
        preferred_keys = (
            str(self.parameters.get("plot_key", "") or ""),
            "default",
            "simca_acceptance",
            "coomans",
            "t2_q",
            "scores",
            "confusion_matrix_cv",
            "confusion_matrix_train",
        )
        for key in preferred_keys:
            payload = input_data.get(key) if key else None
            if _looks_like_plot_payload(payload):
                return {"visualization": self._normalize_plot_payload(payload)}
        if any(_looks_like_plot_payload(payload) for payload in input_data.values()):
            for payload in input_data.values():
                if _looks_like_plot_payload(payload):
                    return {"visualization": self._normalize_plot_payload(payload)}

        for key in ("visualization", "plot", "figure"):
            payload = input_data.get(key)
            if _looks_like_plot_payload(payload):
                return {"visualization": self._normalize_plot_payload(payload)}

        return None

    def _normalize_plot_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        normalized = dict(payload)
        if "plot_type" not in normalized:
            plot_type = self.parameters.get("plot_type", "plot")
            layout = normalized.get("layout")
            if plot_type == "spectra" and isinstance(layout, dict):
                title = str(layout.get("title", "")).lower()
                if "dendrogram" in title:
                    plot_type = "dendrogram"
            normalized["plot_type"] = plot_type
        return normalized

    def _plot_spectra(self, dataset: Any) -> Dict[str, Any]:
        """Generate spectra plot data, preserving axis titles from dataset."""
        traces = []
        data_role = get_dataset_data_role(dataset)
        is_feature_table = data_role == "X_features"

        # Get x-axis data and display info from dataset (preferred property accessor)
        x_coord = dataset.feature_axis
        if x_coord is not None:
            axis_labels = getattr(x_coord, "labels", None)
            if is_feature_table and axis_labels is not None and len(axis_labels) == dataset.shape[-1]:
                x_data = [str(label) for label in axis_labels]
            elif x_coord.data is not None:
                x_data = x_coord.data.tolist()
            elif axis_labels is not None:
                x_data = [str(label) for label in axis_labels]
            else:
                x_data = list(range(dataset.shape[-1]))
            x_info = get_axis_display_info(x_coord)
            x_label = x_info["label"]
            should_reverse_x = False if is_feature_table else x_info["should_reverse"]
        else:
            x_data = list(range(dataset.shape[-1]))
            x_info = get_axis_display_info(None)
            x_label = "Feature" if is_feature_table else x_info["label"]
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
            subsampling_warning = (
                f"Showing {max_traces} evenly spaced traces from {n_samples} samples. "
                "Use Data Table or export for the complete matrix."
            )
        else:
            indices = range(n_samples)
            subsampling_warning = None

        for i in indices:
            name = sample_labels[i] if sample_labels and i < len(sample_labels) else f"Sample {i+1}"
            trace: dict[str, Any] = {
                "x": x_data,
                "y": data[i].tolist(),
                "type": "bar" if is_feature_table else "scatter",
                "name": name,
            }
            if not is_feature_table:
                trace["mode"] = "lines"
            traces.append(trace)

        layout: dict[str, Any] = {
            "title": dataset.title if hasattr(dataset, "title") and dataset.title else "Data Plot",
            "xaxis": x_axis_config,
            "yaxis": {"title": y_label},
        }
        if is_feature_table:
            layout["barmode"] = "group"

        metadata: dict[str, Any] = {
            "data_role": data_role,
            "n_samples": int(n_samples),
            "n_features": int(data.shape[1]),
            "shown_traces": int(len(list(indices)) if not isinstance(indices, range) else len(indices)),
        }
        if subsampling_warning:
            metadata["warning"] = subsampling_warning
            metadata["subsampled"] = True

        return {
            "visualization": {
                "plot_type": "features" if is_feature_table else "spectra",
                "data": traces,
                "layout": layout,
                "metadata": metadata,
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
        title = "PCA Scores Plot"
        pc_labels: list[str] | None = None
        sample_labels: list[str] | None = None
        if isinstance(scores, SherpaDataset):
            title = str(getattr(scores, "title", "") or title)
            scores_array = np.array(scores.data)
            axis = scores.feature_axis
            if axis is not None:
                labels = getattr(axis, "labels", None)
                if labels is not None:
                    pc_labels = [str(v) for v in labels]
            obs_axis = scores.get_observation_axis()
            if obs_axis is not None:
                labels = getattr(obs_axis, "labels", None)
                if labels is not None:
                    sample_labels = [str(v) for v in labels]
        elif hasattr(scores, "data"):
            scores_array = np.array(scores.data)
        else:
            scores_array = np.array(scores)

        # Ensure 2D
        if scores_array.ndim == 1:
            scores_array = scores_array.reshape(-1, 1)

        n_components = scores_array.shape[1]
        pc_x = min(pc_x, n_components - 1)
        pc_y = min(pc_y, n_components - 1)
        x_label = pc_labels[pc_x] if pc_labels and len(pc_labels) > pc_x else f"PC{pc_x + 1}"
        y_label = pc_labels[pc_y] if pc_labels and len(pc_labels) > pc_y else f"PC{pc_y + 1}"

        trace = {
            "x": scores_array[:, pc_x].tolist(),
            "y": scores_array[:, pc_y].tolist(),
            "type": "scatter",
            "mode": "markers",
            "marker": {"size": 8, "color": "#3b82f6"},
            "name": "Scores",
        }
        if sample_labels and len(sample_labels) == scores_array.shape[0]:
            trace["text"] = sample_labels
            trace["hovertemplate"] = "%{text}<br>%{x:.4g}, %{y:.4g}<extra></extra>"

        return {
            "visualization": {
                "plot_type": "scores",
                "data": [trace],
                "layout": {
                    "title": title,
                    "xaxis": {"title": x_label},
                    "yaxis": {"title": y_label},
                },
            }
        }

    def _plot_profiles(self, dataset: SherpaDataset) -> Dict[str, Any]:
        """Plot sample-by-component profiles with components as traces."""
        data = np.asarray(dataset.data, dtype=np.float64)
        if data.ndim == 1:
            data = data.reshape(-1, 1)

        obs_axis = dataset.get_observation_axis()
        if obs_axis is not None and getattr(obs_axis, "data", None) is not None:
            x_values = np.asarray(obs_axis.data).tolist()
            x_title = str(getattr(obs_axis, "title", "") or "Sample")
        elif obs_axis is not None and getattr(obs_axis, "labels", None) is not None:
            x_values = [str(v) for v in obs_axis.labels]
            x_title = str(getattr(obs_axis, "title", "") or "Sample")
        else:
            x_values = list(range(1, data.shape[0] + 1))
            x_title = "Sample"

        feature_axis = dataset.feature_axis
        labels = None
        if feature_axis is not None and getattr(feature_axis, "labels", None) is not None:
            labels = [str(v) for v in feature_axis.labels]
        elif feature_axis is not None and getattr(feature_axis, "data", None) is not None:
            labels = [str(v) for v in np.asarray(feature_axis.data).tolist()]

        traces: list[dict[str, Any]] = []
        for col in range(min(data.shape[1], 50)):
            name = labels[col] if labels and col < len(labels) else f"Component {col + 1}"
            traces.append(
                {
                    "x": x_values,
                    "y": data[:, col].tolist(),
                    "type": "scatter",
                    "mode": "lines+markers" if data.shape[0] <= 100 else "lines",
                    "name": name,
                }
            )

        return {
            "visualization": {
                "plot_type": "profiles",
                "data": traces,
                "layout": {
                    "title": str(getattr(dataset, "title", "") or "Profiles"),
                    "xaxis": {"title": x_title},
                    "yaxis": self._profile_yaxis(dataset),
                },
                "metadata": {"n_samples": int(data.shape[0]), "n_profiles": int(data.shape[1])},
            }
        }

    def _profile_yaxis(self, dataset: SherpaDataset) -> dict[str, Any]:
        title = str(getattr(dataset, "units", "") or "Value")
        dataset_title = str(getattr(dataset, "title", "") or "").lower()
        meta_type = str(_dataset_meta(dataset).get("type", "")).upper()
        axis: dict[str, Any] = {"title": title}
        if meta_type == "EFA" or "eigenvalue" in dataset_title or "eigenvalue" in title.lower():
            axis["type"] = "log"
        return axis

    def _plot_array(
        self,
        values: Any,
        plot_type: str,
        x_axis: int,
        y_axis: int,
        title: str = "Array Output",
    ) -> Dict[str, Any]:
        """Plot generic numeric matrices or categorical vectors from model outputs."""
        arr = np.asarray(values)
        if arr.size == 0:
            return {
                "visualization": {
                    "plot_type": plot_type,
                    "data": [],
                    "layout": {"title": "No data to plot"},
                }
            }

        if not _is_numeric_array(arr):
            return self._plot_categorical_vector(arr, title=title)

        numeric = arr.astype(np.float64, copy=False)
        if numeric.ndim == 0:
            numeric = numeric.reshape(1, 1)
        elif numeric.ndim == 1:
            numeric = numeric.reshape(-1, 1)
        else:
            numeric = np.atleast_2d(numeric)

        if plot_type in ("contour", "heatmap") and numeric.shape[0] > 1 and numeric.shape[1] > 1:
            trace_type = "contour" if plot_type == "contour" else "heatmap"
            return {
                "visualization": {
                    "plot_type": trace_type,
                    "data": [
                        {
                            "x": list(range(numeric.shape[1])),
                            "y": list(range(numeric.shape[0])),
                            "z": numeric.tolist(),
                            "type": trace_type,
                            "colorscale": self.parameters.get("colorscale", "Viridis"),
                        }
                    ],
                    "layout": {
                        "title": title,
                        "xaxis": {"title": "Feature"},
                        "yaxis": {"title": "Sample"},
                    },
                }
            }

        if plot_type in ("scatter", "scores") and numeric.shape[1] > 1:
            x_idx = min(max(0, int(x_axis)), numeric.shape[1] - 1)
            y_idx = min(max(0, int(y_axis)), numeric.shape[1] - 1)
            return {
                "visualization": {
                    "plot_type": "scatter",
                    "data": [
                        {
                            "x": numeric[:, x_idx].tolist(),
                            "y": numeric[:, y_idx].tolist(),
                            "type": "scatter",
                            "mode": "markers",
                            "marker": {"size": 8, "color": "#3b82f6"},
                            "name": title,
                        }
                    ],
                    "layout": {
                        "title": title,
                        "xaxis": {"title": f"Column {x_idx + 1}"},
                        "yaxis": {"title": f"Column {y_idx + 1}"},
                    },
                }
            }

        traces: list[dict[str, Any]] = []
        x_values = list(range(numeric.shape[0]))
        for col in range(min(numeric.shape[1], 20)):
            traces.append(
                {
                    "x": x_values,
                    "y": numeric[:, col].tolist(),
                    "type": "scatter",
                    "mode": "lines+markers" if numeric.shape[0] <= 100 else "lines",
                    "name": "Value" if numeric.shape[1] == 1 else f"Column {col + 1}",
                }
            )
        return {
            "visualization": {
                "plot_type": "line",
                "data": traces,
                "layout": {
                    "title": title,
                    "xaxis": {"title": "Index"},
                    "yaxis": {"title": "Value"},
                },
            }
        }

    def _plot_transfer_error(self, diagnostics: dict[str, Any]) -> Dict[str, Any]:
        """Plot calibration-transfer RMSE diagnostics instead of a blank dict fallback."""
        per_feature = diagnostics.get("per_feature_rmse")
        traces: list[dict[str, Any]] = []
        if isinstance(per_feature, list) and per_feature:
            traces.append(
                {
                    "x": list(range(1, len(per_feature) + 1)),
                    "y": [float(value) for value in per_feature],
                    "type": "scatter",
                    "mode": "lines",
                    "name": "Per-feature RMSE",
                }
            )

        summary_values: list[float] = []
        summary_labels: list[str] = []
        for key, label in (
            ("rmse_transfer", "Transfer RMSE"),
            ("max_error", "Max Error"),
        ):
            value = diagnostics.get(key)
            if isinstance(value, (int, float, np.integer, np.floating)) and np.isfinite(float(value)):
                summary_labels.append(label)
                summary_values.append(float(value))
        if summary_values:
            traces.append(
                {
                    "x": summary_labels,
                    "y": summary_values,
                    "type": "bar",
                    "name": "Summary",
                    "yaxis": "y2" if per_feature else "y",
                }
            )

        layout: dict[str, Any] = {
            "title": "Calibration Transfer Error",
            "xaxis": {"title": "Feature"},
            "yaxis": {"title": "RMSE"},
        }
        if per_feature and summary_values:
            layout["yaxis2"] = {
                "title": "Summary Error",
                "overlaying": "y",
                "side": "right",
            }

        return {
            "visualization": {
                "plot_type": "transfer_error",
                "data": traces,
                "layout": layout,
                "metadata": {
                    "rmse_transfer": diagnostics.get("rmse_transfer"),
                    "max_error": diagnostics.get("max_error"),
                    "n_features": diagnostics.get("n_features"),
                    "n_transfer_samples": diagnostics.get("n_transfer_samples"),
                },
            }
        }

    def _plot_categorical_vector(self, values: np.ndarray, title: str = "Categorical Output") -> Dict[str, Any]:
        """Plot class/cluster labels as a count bar chart."""
        labels = [str(v) for v in values.reshape(-1).tolist()]
        uniques, counts = np.unique(np.asarray(labels, dtype=object), return_counts=True)
        order = np.argsort(counts)[::-1]
        x_values = [str(uniques[i]) for i in order]
        y_values = [int(counts[i]) for i in order]
        return {
            "visualization": {
                "plot_type": "bar",
                "data": [
                    {
                        "x": x_values,
                        "y": y_values,
                        "type": "bar",
                        "name": "Count",
                    }
                ],
                "layout": {
                    "title": title,
                    "xaxis": {"title": "Label"},
                    "yaxis": {"title": "Count"},
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
        plot_type = data.get("plot_type") or data.get("type") or "generic"
        layout = data.get("layout", {})
        if plot_type == "generic" and isinstance(layout, dict) and "dendrogram" in str(layout.get("title", "")).lower():
            plot_type = "dendrogram"
        return {
            "visualization": {
                "plot_type": plot_type,
                "data": data.get("data", []),
                "layout": layout,
            }
        }

    def _plot_dendrogram_payload(self, data: dict) -> Dict[str, Any]:
        """Pass through an already-renderable dendrogram payload."""
        if "data" in data and "layout" in data:
            return self._plot_generic({**data, "plot_type": "dendrogram"})
        return {
            "visualization": {
                "plot_type": "dendrogram",
                "data": [],
                "layout": {"title": "Dendrogram data unavailable"},
            }
        }

    @staticmethod
    def _is_regression_cv_metrics(data: dict[str, Any]) -> bool:
        meta = data.get("metadata") if isinstance(data.get("metadata"), dict) else {}
        return meta.get("type") == "RegressionCV" or any(
            key in data for key in ("rmsecv", "r2_cv", "q2", "per_fold_n_selected", "per_fold_mse")
        )

    def _plot_regression_cv_metrics(self, data: dict[str, Any]) -> Dict[str, Any]:
        """Render nested-CV metrics as an explicit metrics plot instead of a blank fallback."""
        summary_keys = ("rmsecv", "r2_cv", "q2", "bias", "sep", "rer")
        x_values: list[str] = []
        y_values: list[float] = []
        for key in summary_keys:
            value = data.get(key)
            if isinstance(value, (int, float)) and np.isfinite(float(value)):
                x_values.append(key.upper() if key in {"q2"} else key.replace("_", " ").upper())
                y_values.append(float(value))

        traces: list[dict[str, Any]] = []
        if x_values:
            traces.append({"x": x_values, "y": y_values, "type": "bar", "name": "Summary"})

        fold_mse = data.get("per_fold_mse")
        if isinstance(fold_mse, list) and fold_mse:
            traces.append(
                {
                    "x": list(range(1, len(fold_mse) + 1)),
                    "y": [float(v) for v in fold_mse],
                    "type": "scatter",
                    "mode": "lines+markers",
                    "name": "Fold MSE",
                    "yaxis": "y2",
                }
            )

        fold_selected = data.get("per_fold_n_selected")
        if isinstance(fold_selected, list) and fold_selected:
            traces.append(
                {
                    "x": list(range(1, len(fold_selected) + 1)),
                    "y": [float(v) for v in fold_selected],
                    "type": "scatter",
                    "mode": "lines+markers",
                    "name": "Variables Selected",
                    "yaxis": "y2",
                }
            )

        layout: dict[str, Any] = {
            "title": f"Nested CV Metrics ({data.get('selection_method', 'selection')})",
            "xaxis": {"title": "Metric / Fold"},
            "yaxis": {"title": "Metric Value"},
        }
        if len(traces) > 1:
            layout["yaxis2"] = {"title": "Fold Value", "overlaying": "y", "side": "right"}

        return {
            "visualization": {
                "plot_type": "metrics",
                "data": traces,
                "layout": layout,
                "metadata": {"type": "RegressionCV"},
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
        colors = [
            "#3b82f6",
            "#ef4444",
            "#22c55e",
            "#f59e0b",
            "#8b5cf6",
            "#ec4899",
            "#06b6d4",
            "#f97316",
        ]

        def _fmt(value: Any, digits: int = 3) -> str:
            try:
                fval = float(value)
            except (TypeError, ValueError):
                return "n/a"
            return f"{fval:.{digits}f}" if np.isfinite(fval) else "n/a"

        def _split_summary(metadata: dict[str, Any]) -> str:
            train = metadata.get("train") if isinstance(metadata.get("train"), dict) else {}
            test = metadata.get("test") if isinstance(metadata.get("test"), dict) else {}
            r2_train = metadata.get("r2_train", train.get("R2"))
            rmse_train = metadata.get("rmse_train", train.get("RMSE"))
            r2_test = metadata.get("r2_test", test.get("R2"))
            rmse_test = metadata.get("rmse_test", test.get("RMSE"))
            if r2_train is None and rmse_train is None:
                return f"Test R²={_fmt(r2_test)} · RMSE={_fmt(rmse_test)}"
            return (
                f"Train R²={_fmt(r2_train)} · RMSE={_fmt(rmse_train)}    "
                f"Test R²={_fmt(r2_test)} · RMSE={_fmt(rmse_test)}"
            )

        series_payload = data.get("series")
        if isinstance(series_payload, list) and series_payload:
            traces: list[dict] = []
            all_actual: list[float] = []
            all_predicted: list[float] = []
            for idx, s in enumerate(series_payload):
                if not isinstance(s, dict):
                    continue
                name = str(s.get("name", "Target"))
                color = colors[idx % len(colors)]
                series_actual = [float(v) for v in s.get("actual", [])]
                series_predicted = [float(v) for v in s.get("predicted", [])]
                train_actual = [float(v) for v in s.get("train_actual", [])]
                train_predicted = [float(v) for v in s.get("train_predicted", [])]
                if train_actual and train_predicted:
                    traces.append(
                        {
                            "x": train_actual,
                            "y": train_predicted,
                            "type": "scatter",
                            "mode": "markers",
                            "name": f"{name} train",
                            "marker": {"color": color, "size": 7, "symbol": "circle-open"},
                        }
                    )
                    all_actual.extend(train_actual)
                    all_predicted.extend(train_predicted)
                if series_actual and series_predicted:
                    traces.append(
                        {
                            "x": series_actual,
                            "y": series_predicted,
                            "type": "scatter",
                            "mode": "markers",
                            "name": f"{name} test",
                            "marker": {"color": color, "size": 8, "symbol": "circle"},
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
            title_text = f"{title_text}<br><sup>{_split_summary(metadata)}</sup>"

            return {
                "visualization": {
                    "plot_type": "scatter",
                    "data": traces,
                    "layout": {
                        "title": title_text,
                        "xaxis": {"title": "Actual"},
                        "yaxis": {"title": y_title},
                        "showlegend": True,
                    },
                }
            }

        # Legacy single-target path.
        pairs = np.asarray(data.get("data", []), dtype=np.float64)
        if pairs.ndim == 1:
            pairs = pairs.reshape(-1, 2) if pairs.size else np.zeros((0, 2))

        actual = pairs[:, 0].tolist() if pairs.shape[1] >= 1 else []
        predicted = pairs[:, 1].tolist() if pairs.shape[1] >= 2 else []
        metadata = data.get("metadata") or {}
        train_payload = metadata.get("train") if isinstance(metadata, dict) else None
        train_pairs_raw = train_payload.get("data") if isinstance(train_payload, dict) else []
        train_pairs = np.asarray(train_pairs_raw or [], dtype=np.float64)
        if train_pairs.ndim == 1:
            train_pairs = train_pairs.reshape(-1, 2) if train_pairs.size else np.zeros((0, 2))
        train_actual = train_pairs[:, 0].tolist() if train_pairs.shape[1] >= 1 else []
        train_predicted = train_pairs[:, 1].tolist() if train_pairs.shape[1] >= 2 else []
        if actual and predicted:
            all_actual = actual + train_actual
            all_predicted = predicted + train_predicted
            lo = min(min(all_actual), min(all_predicted))
            hi = max(max(all_actual), max(all_predicted))
        else:
            lo, hi = 0.0, 1.0

        traces = []
        if train_actual and train_predicted:
            traces.append(
                {
                    "x": train_actual,
                    "y": train_predicted,
                    "type": "scatter",
                    "mode": "markers",
                    "name": "Train",
                    "marker": {"color": "#3b82f6", "size": 7, "symbol": "circle-open"},
                }
            )
        traces.extend(
            [
                {
                    "x": actual,
                    "y": predicted,
                    "type": "scatter",
                    "mode": "markers",
                    "name": "Test",
                    "marker": {"color": "#3b82f6", "size": 8, "symbol": "circle"},
                },
                {
                    "x": [lo, hi],
                    "y": [lo, hi],
                    "type": "scatter",
                    "mode": "lines",
                    "name": "Ideal",
                },
            ]
        )

        return {
            "visualization": {
                "plot_type": "scatter",
                "data": traces,
                "layout": {
                    "title": (
                        "Predicted vs Actual<br><sup>"
                        f"{_split_summary(metadata if isinstance(metadata, dict) else {})}</sup>"
                    ),
                    "xaxis": {"title": "Actual"},
                    "yaxis": {"title": "Predicted"},
                    "showlegend": bool(train_actual and train_predicted),
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
