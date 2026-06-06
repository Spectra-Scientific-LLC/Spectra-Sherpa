"""Tests for PlotNode / ContourPlotNode with label-only SampleAxis and trace cap."""

from __future__ import annotations

import numpy as np
import pytest

from spectra_sherpa.app.lib.sherpa_dataset import SampleAxis, SherpaDataset, SpectralAxis
from spectra_sherpa.app.services.dag.nodes.output import ContourPlotNode, PlotNode


def _make_dataset(n_samples: int, n_features: int = 10, labels: list[str] | None = None) -> SherpaDataset:
    """Create a SherpaDataset with a labels-only SampleAxis (no numeric values)."""
    data = np.random.default_rng(42).standard_normal((n_samples, n_features))
    wavenumbers = np.linspace(4000, 400, n_features)
    return SherpaDataset(
        data,
        feature_axis=SpectralAxis(values=wavenumbers, units="cm-1"),
        sample_axis=SampleAxis(labels=labels or [f"s{i}" for i in range(n_samples)]),
    )


# ── PlotNode: contour with label-only observation axis ──────────────────


@pytest.mark.anyio
async def test_plot_node_contour_labels_only_sample_axis() -> None:
    """output.plot(plot_type='contour') must produce a valid y-axis when
    the observation axis has labels but no numeric values."""
    ds = _make_dataset(3, labels=["a", "b", "c"])
    node = PlotNode(node_id="p1", parameters={"plot_type": "contour"})

    result = await node.execute(ds)
    vis = result["visualization"]

    assert vis["plot_type"] in ("contour", "heatmap")
    # y must be a real list, not None
    assert isinstance(vis["data"][0]["y"], list)
    assert len(vis["data"][0]["y"]) == 3


@pytest.mark.anyio
async def test_plot_node_heatmap_labels_only_sample_axis() -> None:
    """Same check for the heatmap variant."""
    ds = _make_dataset(4, labels=["w", "x", "y", "z"])
    node = PlotNode(node_id="p2", parameters={"plot_type": "heatmap"})

    result = await node.execute(ds)
    trace = result["visualization"]["data"][0]

    assert isinstance(trace["y"], list)
    assert len(trace["y"]) == 4
    assert isinstance(trace["z"], list)


# ── ContourPlotNode: label-only observation axis ────────────────────────


@pytest.mark.anyio
async def test_contour_node_labels_only_sample_axis() -> None:
    """output.contour must produce a valid y-axis for labels-only datasets."""
    ds = _make_dataset(5, labels=["a", "b", "c", "d", "e"])
    node = ContourPlotNode(node_id="c1", parameters={"plot_type": "heatmap"})

    result = await node.execute(ds)
    vis = result["visualization"]

    assert isinstance(vis["data"][0]["y"], list)
    assert len(vis["data"][0]["y"]) == 5


@pytest.mark.anyio
async def test_contour_node_transpose_labels_only() -> None:
    """Transpose path must also survive a labels-only observation axis."""
    ds = _make_dataset(3, n_features=8, labels=["r1", "r2", "r3"])
    node = ContourPlotNode(node_id="c2", parameters={"plot_type": "heatmap", "transpose": True})

    result = await node.execute(ds)
    trace = result["visualization"]["data"][0]

    # After transpose the original y (3 items) becomes x and vice versa.
    assert isinstance(trace["x"], list)
    assert isinstance(trace["y"], list)
    assert trace["z"] is not None


# ── PlotNode: spectra trace cap ─────────────────────────────────────────


@pytest.mark.anyio
async def test_plot_spectra_caps_traces_at_50() -> None:
    """Datasets with >50 samples must be downsampled to at most 50 traces."""
    ds = _make_dataset(200)
    node = PlotNode(node_id="p3", parameters={"plot_type": "spectra"})

    result = await node.execute(ds)
    vis = result["visualization"]
    traces = vis["data"]

    assert len(traces) <= 50
    assert vis["metadata"]["subsampled"] is True
    assert "Showing 50 evenly spaced traces" in vis["metadata"]["warning"]


@pytest.mark.anyio
async def test_plot_spectra_keeps_all_traces_when_under_cap() -> None:
    """Datasets at or below 50 samples should not be downsampled."""
    ds = _make_dataset(10)
    node = PlotNode(node_id="p4", parameters={"plot_type": "spectra"})

    result = await node.execute(ds)
    vis = result["visualization"]
    traces = vis["data"]

    assert len(traces) == 10
    assert "warning" not in vis["metadata"]
