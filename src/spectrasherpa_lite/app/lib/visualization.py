"""
Interactive visualization utilities for spectral data.

NDDataset-native plotting functions that generate interactive HTML outputs
using Plotly. Migrated from project1/plot_ftir_spectra.py.

Key Features:
- Dual-subplot layout (spectra + concentration scatter)
- Interactive wavenumber slider
- Golden grid interpolation for misaligned spectra
- Calibration curve visualization (linear + saturation models)
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

import numpy as np
import pandas as pd

try:
    import plotly.graph_objects as go
    from plotly.subplots import make_subplots

    HAS_PLOTLY = True
except ImportError:
    HAS_PLOTLY = False
    go = None

try:
    from spectrochempy import NDDataset

    HAS_SCP = True
except ImportError:
    HAS_SCP = False
    NDDataset = None


def check_plotly() -> None:
    """Raise ImportError if plotly is not available."""
    if not HAS_PLOTLY:
        raise ImportError("plotly is required for visualization. Install with: pip install plotly")


# ─────────────────────────────────────────────────────────────────────────────
# BASIC SPECTRUM PLOTTING
# ─────────────────────────────────────────────────────────────────────────────


def plot_spectrum(
    dataset: "NDDataset",
    title: Optional[str] = None,
    show_grid: bool = True,
) -> "go.Figure":
    """
    Create a simple line plot of a spectrum.

    Parameters
    ----------
    dataset : NDDataset
        1D or 2D spectral dataset
    title : str, optional
        Plot title (defaults to dataset.title)
    show_grid : bool
        Whether to show grid lines

    Returns
    -------
    go.Figure
        Plotly figure object
    """
    check_plotly()

    fig = go.Figure()

    # Get wavenumber axis
    if hasattr(dataset, "x") and dataset.x is not None:
        wavenumbers = dataset.x.data
    else:
        wavenumbers = np.arange(dataset.shape[-1])

    # Handle 1D vs 2D data
    data = dataset.data
    if data.ndim == 1:
        data = data.reshape(1, -1)

    # Add traces
    for i in range(data.shape[0]):
        label = f"Spectrum {i + 1}"
        if hasattr(dataset, "y") and dataset.y is not None and i < len(dataset.y.data):
            label = str(dataset.y.data[i])

        fig.add_trace(
            go.Scatter(
                x=wavenumbers,
                y=data[i, :],
                mode="lines",
                name=label,
            )
        )

    fig.update_layout(
        title=title or (dataset.title if hasattr(dataset, "title") else "Spectrum"),
        xaxis_title="Wavenumber (cm⁻¹)",
        yaxis_title="Absorbance",
        template="plotly_white",
        showlegend=data.shape[0] > 1,
        hovermode="closest",
    )

    if show_grid:
        fig.update_xaxes(showgrid=True, gridwidth=1, gridcolor="lightgray")
        fig.update_yaxes(showgrid=True, gridwidth=1, gridcolor="lightgray")

    return fig


def plot_spectra_comparison(
    datasets: List["NDDataset"],
    labels: Optional[List[str]] = None,
    title: str = "Spectra Comparison",
) -> "go.Figure":
    """
    Plot multiple spectra for comparison.

    Parameters
    ----------
    datasets : list[NDDataset]
        List of spectral datasets
    labels : list[str], optional
        Labels for each spectrum
    title : str
        Plot title

    Returns
    -------
    go.Figure
        Plotly figure object
    """
    check_plotly()

    fig = go.Figure()

    for i, ds in enumerate(datasets):
        label = labels[i] if labels and i < len(labels) else (ds.title or f"Spectrum {i + 1}")

        wavenumbers = ds.x.data if hasattr(ds, "x") and ds.x is not None else np.arange(ds.shape[-1])
        data = ds.data.flatten() if ds.data.ndim == 1 else ds.data[0, :]

        fig.add_trace(
            go.Scatter(
                x=wavenumbers,
                y=data,
                mode="lines",
                name=label,
            )
        )

    fig.update_layout(
        title=title,
        xaxis_title="Wavenumber (cm⁻¹)",
        yaxis_title="Absorbance",
        template="plotly_white",
        hovermode="closest",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0),
    )

    return fig


# ─────────────────────────────────────────────────────────────────────────────
# CONCENTRATION-ABSORBANCE PLOTTING
# ─────────────────────────────────────────────────────────────────────────────


def plot_calibration_curve(
    concentrations: np.ndarray,
    absorbances: np.ndarray,
    wavenumber: float,
    model_params: Optional[Dict[str, float]] = None,
    title: Optional[str] = None,
) -> "go.Figure":
    """
    Plot concentration vs absorbance with optional model fit.

    Parameters
    ----------
    concentrations : np.ndarray
        Concentration values
    absorbances : np.ndarray
        Absorbance values at the selected wavenumber
    wavenumber : float
        Selected wavenumber (cm⁻¹)
    model_params : dict, optional
        Model parameters: {model_type, slope, intercept, s, p, c}
    title : str, optional
        Plot title

    Returns
    -------
    go.Figure
        Plotly figure object
    """
    check_plotly()

    fig = go.Figure()

    # Data points
    fig.add_trace(
        go.Scatter(
            x=concentrations,
            y=absorbances,
            mode="markers",
            marker=dict(size=10),
            name="Measured",
        )
    )

    # Add model curve if parameters provided
    if model_params:
        from .blending.core import eval_linear_model, eval_saturation_model

        # Generate smooth curve
        c_range = np.linspace(0, np.max(concentrations) * 1.1, 100)
        model_type = model_params.get("model_type", "linear")

        if model_type == "linear":
            slope = model_params.get("slope", 1.0)
            intercept = model_params.get("intercept", 0.0)
            s_cap = model_params.get("s", 1.8)
            a_model = eval_linear_model(
                c_range,
                np.array([slope]),
                np.array([intercept]),
                s=np.array([s_cap]),
            ).flatten()
            label = f"Linear: A = {slope:.4f}×C + {intercept:.4f}"

        elif model_type == "saturation":
            s = model_params.get("s", 1.0)
            p = model_params.get("p", 1.0)
            c = model_params.get("c", 1.0)
            a_model = eval_saturation_model(
                c_range,
                np.array([s]),
                np.array([p]),
                np.array([c]),
            ).flatten()
            label = f"Saturation: s={s:.3f}, p={p:.3f}, c={c:.3f}"

        else:
            a_model = None
            label = None

        if a_model is not None:
            fig.add_trace(
                go.Scatter(
                    x=c_range,
                    y=a_model,
                    mode="lines",
                    line=dict(width=2),
                    name=label,
                )
            )

    fig.update_layout(
        title=title or f"Calibration Curve at {wavenumber:.2f} cm⁻¹",
        xaxis_title="Concentration (ppm)",
        yaxis_title="Absorbance",
        template="plotly_white",
        hovermode="closest",
    )

    return fig


# ─────────────────────────────────────────────────────────────────────────────
# DUAL SUBPLOT INTERACTIVE FIGURE
# ─────────────────────────────────────────────────────────────────────────────


def build_interactive_figure(
    datasets: List["NDDataset"],
    concentrations: List[float],
    golden_wavenumbers: np.ndarray,
    initial_wavenumber_index: Optional[int] = None,
    x_label: str = "Concentration (ppm)",
) -> "go.Figure":
    """
    Build an interactive dual-subplot figure for spectral analysis.

    Layout:
    - Top subplot: All spectra overlaid with vertical line at selected wavenumber
    - Bottom subplot: Concentration vs absorbance scatter plot

    Parameters
    ----------
    datasets : list[NDDataset]
        List of spectra (one per concentration)
    concentrations : list[float]
        Concentration values corresponding to each spectrum
    golden_wavenumbers : np.ndarray
        Reference wavenumber grid for interpolation
    initial_wavenumber_index : int, optional
        Starting wavenumber index (defaults to middle)
    x_label : str
        Label for concentration axis

    Returns
    -------
    go.Figure
        Interactive Plotly figure
    """
    check_plotly()

    n_spectra = len(datasets)
    n_wn = len(golden_wavenumbers)

    if initial_wavenumber_index is None:
        initial_wavenumber_index = n_wn // 2

    initial_wavenumber = float(golden_wavenumbers[initial_wavenumber_index])

    # Pre-interpolate all spectra onto golden grid
    interpolated_data = []
    for ds in datasets:
        wn = ds.x.data if hasattr(ds, "x") and ds.x is not None else np.arange(ds.shape[-1])
        data = ds.data.flatten() if ds.data.ndim == 1 else ds.data[0, :]

        interp = np.interp(
            golden_wavenumbers,
            wn,
            data,
            left=np.nan,
            right=np.nan,
        )
        interpolated_data.append(interp)

    interpolated_data = np.array(interpolated_data)  # (n_spectra, n_wn)

    # Create figure with subplots
    fig = make_subplots(
        rows=2,
        cols=1,
        row_heights=[0.6, 0.4],
        vertical_spacing=0.12,
        subplot_titles=["FTIR Spectra", f"Absorbance at {initial_wavenumber:.2f} cm⁻¹"],
    )

    # Top subplot: All spectra
    for i, ds in enumerate(datasets):
        wn = ds.x.data if hasattr(ds, "x") and ds.x is not None else np.arange(ds.shape[-1])
        data = ds.data.flatten() if ds.data.ndim == 1 else ds.data[0, :]

        label = f"{concentrations[i]:.1f} ppm"

        fig.add_trace(
            go.Scatter(
                x=wn,
                y=data,
                mode="lines",
                name=label,
            ),
            row=1,
            col=1,
        )

    # Add vertical line at selected wavenumber
    fig.add_vline(
        x=initial_wavenumber,
        line_width=2,
        line_dash="solid",
        line_color="rgba(0,0,0,0.7)",
        row=1,
        col=1,
    )

    # Bottom subplot: Concentration vs absorbance scatter
    scatter_y = interpolated_data[:, initial_wavenumber_index]

    fig.add_trace(
        go.Scatter(
            x=concentrations,
            y=scatter_y,
            mode="markers+lines",
            marker=dict(size=10),
            name="Absorbance",
            showlegend=False,
        ),
        row=2,
        col=1,
    )

    # Update layout
    fig.update_layout(
        template="plotly_white",
        height=800,
        hovermode="closest",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0),
    )

    fig.update_xaxes(title_text="Wavenumber (cm⁻¹)", row=1, col=1)
    fig.update_yaxes(title_text="Absorbance", row=1, col=1)
    fig.update_xaxes(title_text=x_label, row=2, col=1)
    fig.update_yaxes(title_text=f"Absorbance at {initial_wavenumber:.2f} cm⁻¹", row=2, col=1)

    # Embed metadata for JavaScript controls
    fig.update_layout(
        meta=dict(
            golden_wavenumbers=[float(v) for v in golden_wavenumbers],
            concentrations=[float(c) for c in concentrations],
            interpolated_data=interpolated_data.tolist(),
            initial_index=int(initial_wavenumber_index),
            x_label=x_label,
        )
    )

    return fig


# ─────────────────────────────────────────────────────────────────────────────
# HTML EXPORT
# ─────────────────────────────────────────────────────────────────────────────


def save_figure_html(
    fig: "go.Figure",
    output_path: Union[str, Path],
    include_plotlyjs: bool = True,
) -> Path:
    """
    Save a Plotly figure to an HTML file.

    Parameters
    ----------
    fig : go.Figure
        Plotly figure to save
    output_path : str or Path
        Output file path
    include_plotlyjs : bool
        Whether to embed Plotly.js (True for offline use)

    Returns
    -------
    Path
        Path to saved HTML file
    """
    check_plotly()

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    fig.write_html(
        str(output_path),
        include_plotlyjs=include_plotlyjs,
        full_html=True,
    )

    return output_path


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


# ─────────────────────────────────────────────────────────────────────────────
# HEATMAP VISUALIZATION
# ─────────────────────────────────────────────────────────────────────────────


def plot_spectral_heatmap(
    dataset: "NDDataset",
    title: Optional[str] = None,
    colorscale: str = "Viridis",
) -> "go.Figure":
    """
    Plot a 2D spectral dataset as a heatmap.

    Parameters
    ----------
    dataset : NDDataset
        2D spectral dataset (samples × wavenumbers)
    title : str, optional
        Plot title
    colorscale : str
        Plotly colorscale name

    Returns
    -------
    go.Figure
        Plotly figure object
    """
    check_plotly()

    data = dataset.data
    if data.ndim == 1:
        data = data.reshape(1, -1)

    # Get axes
    wavenumbers = dataset.x.data if hasattr(dataset, "x") and dataset.x is not None else np.arange(data.shape[1])

    if hasattr(dataset, "y") and dataset.y is not None:
        y_labels = [str(v) for v in dataset.y.data]
    else:
        y_labels = [f"Sample {i + 1}" for i in range(data.shape[0])]

    fig = go.Figure(
        data=go.Heatmap(
            z=data,
            x=wavenumbers,
            y=y_labels,
            colorscale=colorscale,
            colorbar=dict(title="Absorbance"),
        )
    )

    fig.update_layout(
        title=title or (dataset.title if hasattr(dataset, "title") else "Spectral Heatmap"),
        xaxis_title="Wavenumber (cm⁻¹)",
        yaxis_title="Sample",
        template="plotly_white",
    )

    return fig


# ─────────────────────────────────────────────────────────────────────────────
# RESIDUALS PLOTTING
# ─────────────────────────────────────────────────────────────────────────────


def plot_residuals(
    measured: np.ndarray,
    modeled: np.ndarray,
    wavenumbers: np.ndarray,
    title: str = "Residuals (Measured - Modeled)",
) -> "go.Figure":
    """
    Plot residuals between measured and modeled spectra.

    Parameters
    ----------
    measured : np.ndarray
        Measured absorbance values
    modeled : np.ndarray
        Modeled absorbance values
    wavenumbers : np.ndarray
        Wavenumber values
    title : str
        Plot title

    Returns
    -------
    go.Figure
        Plotly figure object
    """
    check_plotly()

    residuals = measured - modeled

    # Color by sign (positive=red, negative=blue)
    colors = ["red" if r > 0 else "blue" for r in residuals]

    fig = go.Figure()

    fig.add_trace(
        go.Scatter(
            x=wavenumbers,
            y=residuals,
            mode="markers",
            marker=dict(color=colors, size=4, symbol="diamond"),
            name="Residuals",
        )
    )

    # Add zero line
    fig.add_hline(y=0, line_dash="dash", line_color="gray")

    fig.update_layout(
        title=title,
        xaxis_title="Wavenumber (cm⁻¹)",
        yaxis_title="Residual",
        template="plotly_white",
        showlegend=False,
    )

    return fig


# ─────────────────────────────────────────────────────────────────────────────
# BLEND GROUND TRUTH VISUALIZATION
# ─────────────────────────────────────────────────────────────────────────────


def plot_blend_ground_truth(
    dataset: "NDDataset",
    title: str = "Blend Ground Truth",
) -> Dict[str, "go.Figure"]:
    """
    Generate visualization figures for blend ground truth data.

    Parameters
    ----------
    dataset : NDDataset
        Blended dataset with meta["blend_ground_truth"]

    Returns
    -------
    dict[str, go.Figure]
        Dictionary with 'concentrations' and 'spectra' figures
    """
    check_plotly()

    ground_truth = dataset.meta.get("blend_ground_truth", {})
    if not ground_truth:
        raise ValueError("Dataset does not contain blend ground truth")

    C = np.array(ground_truth["C_matrix"])  # (n_times, n_species)
    S = np.array(ground_truth["S_matrix"])  # (n_species, n_wn)
    species_names = ground_truth.get("species_names", [f"Species {i}" for i in range(C.shape[1])])

    wavenumbers = dataset.x.data if hasattr(dataset, "x") and dataset.x is not None else np.arange(S.shape[1])
    times = dataset.y.data if hasattr(dataset, "y") and dataset.y is not None else np.arange(C.shape[0])

    # Concentration profiles
    conc_fig = go.Figure()
    for i, name in enumerate(species_names):
        conc_fig.add_trace(
            go.Scatter(
                x=times,
                y=C[:, i],
                mode="lines",
                name=name,
            )
        )

    conc_fig.update_layout(
        title=f"{title} - Concentration Profiles",
        xaxis_title="Time",
        yaxis_title="Concentration",
        template="plotly_white",
    )

    # Pure component spectra
    spectra_fig = go.Figure()
    for i, name in enumerate(species_names):
        spectra_fig.add_trace(
            go.Scatter(
                x=wavenumbers,
                y=S[i, :],
                mode="lines",
                name=name,
            )
        )

    spectra_fig.update_layout(
        title=f"{title} - Pure Component Spectra",
        xaxis_title="Wavenumber (cm⁻¹)",
        yaxis_title="Absorbance",
        template="plotly_white",
    )

    return {
        "concentrations": conc_fig,
        "spectra": spectra_fig,
    }


__all__ = [
    # Basic plotting
    "plot_spectrum",
    "plot_spectra_comparison",
    # Calibration
    "plot_calibration_curve",
    # Interactive
    "build_interactive_figure",
    # Export
    "save_figure_html",
    "figure_to_json",
    # Heatmap
    "plot_spectral_heatmap",
    # Residuals
    "plot_residuals",
    # Blend visualization
    "plot_blend_ground_truth",
]
