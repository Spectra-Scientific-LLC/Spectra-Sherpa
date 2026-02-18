"""
Interactive visualization utilities for spectral data.

NDDataset-native plotting functions that generate interactive HTML outputs
using Plotly.
"""

from __future__ import annotations

from typing import Optional

try:
    import plotly.graph_objects as go

    HAS_PLOTLY = True
except ImportError:
    HAS_PLOTLY = False
    go = None


def check_plotly() -> None:
    """Raise ImportError if plotly is not available."""
    if not HAS_PLOTLY:
        raise ImportError("plotly is required for visualization. Install with: pip install plotly")


def figure_to_json(fig: "go.Figure") -> str:
    """
    Convert a Plotly figure to JSON string.

    Useful for embedding in web applications.

    Parameters
    ----------
    fig : go.Figure
        Plotly figure

    Returns
    -------
    str
        JSON representation of the figure
    """
    check_plotly()
    return fig.to_json()


__all__ = [
    "check_plotly",
    "figure_to_json",
]
