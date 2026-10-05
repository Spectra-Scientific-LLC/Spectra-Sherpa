"""Notebook rendering for canonical plot specifications."""

from __future__ import annotations

from typing import Any, Mapping

from .plot_spec import CanonicalPlotSpec


class PlotRendererUnavailable(RuntimeError):
    """The supported default renderer is missing from this installation."""


def show(spec: CanonicalPlotSpec | Mapping[str, Any], *, renderer: str | None = None) -> Any:
    """Render one canonical plot spec with the default Plotly renderer.

    Plotly is imported only when this function is called, so scientific DAG
    execution and evidence inspection remain renderer-free.  The returned
    figure is convenient for notebook customization; it is not canonical
    evidence and is never serialized into a project.
    """

    canonical = spec if isinstance(spec, CanonicalPlotSpec) else CanonicalPlotSpec.from_dict(spec)
    try:
        import plotly.graph_objects as go
    except ImportError as exc:  # pragma: no cover - installation corruption
        raise PlotRendererUnavailable(
            "The default Plotly renderer is unavailable. Reinstall the default product with "
            "`pip install --upgrade spectra-sherpa`."
        ) from exc
    figure = go.Figure(data=list(canonical.data), layout=canonical.layout)
    figure.show(renderer=renderer)
    return figure


__all__ = ["PlotRendererUnavailable", "show"]
