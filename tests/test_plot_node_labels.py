"""Tests for PlotNode / ContourPlotNode with label-only SampleAxis and trace cap."""

from __future__ import annotations

import numpy as np
import pytest

from spectra_sherpa.app.lib.sherpa_dataset import FeatureAxis, SampleAxis, SherpaDataset, SpectralAxis, TargetContext
from spectra_sherpa.app.services.dag.nodes.output import ContourPlotNode, PlotNode
from spectra_sherpa.app.services.dag.nodes.output._helpers import get_axis_display_info
from spectra_sherpa.core.axis_semantics import AxisQuantity


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


def test_spectral_axis_direction_uses_quantity_not_shared_inverse_centimetre_units() -> None:
    wavenumber = SpectralAxis(
        values=np.asarray([400.0, 4000.0]),
        title="Wavenumber",
        units="cm-1",
        quantity=AxisQuantity.WAVENUMBER,
    )
    raman_shift = SpectralAxis(
        values=np.asarray([100.0, 3200.0]),
        title="Raman Shift",
        units="cm-1",
        quantity=AxisQuantity.RAMAN_SHIFT,
    )

    assert get_axis_display_info(wavenumber)["should_reverse"] is True
    assert get_axis_display_info(raman_shift)["should_reverse"] is False


@pytest.mark.anyio
async def test_explained_variance_plot_is_a_labeled_scree_projection() -> None:
    node = PlotNode(node_id="scree", parameters={"plot_type": "explained_variance"})

    result = await node.execute(np.asarray([0.62, 0.23, 0.09]))
    visualization = result["visualization"]

    assert visualization["plot_type"] == "explained_variance"
    assert visualization["data"][0]["x"] == ["PC1", "PC2", "PC3"]
    assert visualization["data"][0]["y"] == pytest.approx([62.0, 23.0, 9.0])
    assert visualization["data"][1]["y"] == pytest.approx([62.0, 85.0, 94.0])
    assert visualization["layout"]["yaxis"]["title"] == "Explained Variance (%)"


@pytest.mark.anyio
async def test_pca_scores_split_categorical_targets_into_named_populations() -> None:
    scores = SherpaDataset(
        X=np.asarray([[-2.1, 0.2], [-1.7, -0.1], [1.8, 0.3], [2.2, -0.2]]),
        feature_axis=FeatureAxis(labels=["PC1 (74.0%)", "PC2 (18.0%)"], title="Principal Component"),
        sample_axis=SampleAxis(labels=["A-1", "A-2", "B-1", "B-2"], title="Sample"),
        target=np.asarray([0, 0, 1, 1]),
        target_context=TargetContext(
            target_type="categorical",
            target_name="Cultivar",
            target_names=["Cultivar"],
            class_names=["Alpha", "Beta"],
        ),
        data_role="X_features",
        title="PCA Scores",
    )

    result = await PlotNode(node_id="scores", parameters={"plot_type": "scores"}).execute(scores)
    visualization = result["visualization"]

    assert [trace["name"] for trace in visualization["data"]] == ["Alpha", "Beta"]
    assert visualization["data"][0]["text"] == ["A-1", "A-2"]
    assert visualization["data"][1]["text"] == ["B-1", "B-2"]
    assert visualization["layout"]["xaxis"]["title"] == "PC1 (74.0%)"
    assert visualization["layout"]["yaxis"]["title"] == "PC2 (18.0%)"
    assert visualization["layout"]["showlegend"] is True


@pytest.mark.anyio
async def test_pca_loadings_keep_spectral_lines_and_wavenumber_direction() -> None:
    loadings = SherpaDataset(
        X=np.asarray([[0.1, -0.2, 0.3], [-0.3, 0.2, 0.1]]),
        feature_axis=SpectralAxis(
            values=np.asarray([500.0, 2000.0, 4000.0]),
            title="Wavenumber",
            units="cm-1",
            quantity=AxisQuantity.WAVENUMBER,
        ),
        sample_axis=SampleAxis(labels=["PC1", "PC2"], title="Principal Component"),
        data_role="X_features",
        title="PCA Loadings",
    )

    result = await PlotNode(node_id="loadings", parameters={"plot_type": "spectra"}).execute(loadings)
    visualization = result["visualization"]

    assert [trace["type"] for trace in visualization["data"]] == ["scatter", "scatter"]
    assert [trace["mode"] for trace in visualization["data"]] == ["lines", "lines"]
    assert [trace["name"] for trace in visualization["data"]] == ["PC1", "PC2"]
    assert visualization["layout"]["xaxis"]["autorange"] == "reversed"
