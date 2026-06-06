from __future__ import annotations

import numpy as np
import pytest

from spectra_sherpa.app.lib.axes import FeatureAxis
from spectra_sherpa.app.lib.sherpa_dataset import SherpaDataset
from spectra_sherpa.app.services.dag.nodes.output import ContourPlotNode, DataTableNode, ExportNode, PlotNode
from spectra_sherpa.app.services.dag.nodes.output.stats_summary_node import StatsSummaryNode


@pytest.mark.anyio
async def test_data_table_accepts_categorical_model_outputs() -> None:
    node = DataTableNode(node_id="table_labels", parameters={})

    result = await node.execute(["setosa", "virginica", "setosa"])

    table = result["visualization"]
    assert table["metadata"]["value_type"] == "categorical"
    assert table["metadata"]["column_names"] == ["Value"]
    assert table["data"] == [["setosa"], ["virginica"], ["setosa"]]


@pytest.mark.anyio
async def test_data_table_truncates_array1d_without_stale_row_count() -> None:
    node = DataTableNode(node_id="table_predictions", parameters={"max_rows": 100})

    result = await node.execute(np.arange(150, dtype=float))

    table = result["visualization"]
    assert table["metadata"]["n_rows"] == 100
    assert table["metadata"]["truncated"] is True
    assert table["metadata"]["column_names"] == ["Value"]
    assert len(table["data"]) == 100
    assert table["data"][0] == [0.0]
    assert table["data"][-1] == [99.0]


@pytest.mark.anyio
async def test_data_table_default_allows_large_scientific_tables() -> None:
    node = DataTableNode(node_id="table_predictions", parameters={})

    result = await node.execute(np.arange(250, dtype=float))

    table = result["visualization"]
    assert table["metadata"]["n_rows"] == 250
    assert table["metadata"]["truncated"] is False


@pytest.mark.anyio
async def test_data_table_prefers_cluster_summary_records() -> None:
    node = DataTableNode(node_id="table_clusters", parameters={})

    result = await node.execute(
        {
            "labels": [0, 0, 1],
            "cluster_summary": [
                {"cluster": 0, "count": 2, "fraction": 2 / 3},
                {"cluster": 1, "count": 1, "fraction": 1 / 3},
            ],
            "metadata": {"type": "KMeans", "quality_summary": {"silhouette_score": 0.5}},
        }
    )

    table = result["visualization"]
    assert table["metadata"]["type"] == "cluster_summary"
    assert table["metadata"]["column_names"] == ["cluster", "count", "fraction"]
    assert table["data"][0]["count"] == 2


@pytest.mark.anyio
async def test_statistics_counts_categorical_model_outputs() -> None:
    node = StatsSummaryNode(node_id="stats_labels", parameters={})

    result = await node.execute({"labels": ["A", "B", "A", "C", "A"]})

    stats = result["statistics"]
    assert stats["input_type"] == "categorical_array"
    assert stats["summary"]["n_unique"] == 3
    assert stats["summary"]["mode"] == "A"
    assert stats["data"][0] == {"value": "A", "count": 3, "fraction": 0.6}
    assert stats["metadata"]["source_key"] == "labels"


@pytest.mark.anyio
async def test_statistics_routes_pca_score_dataset_to_pca_summary() -> None:
    dataset = SherpaDataset(
        X=np.array([[1.0, 0.2], [0.4, -0.6], [-0.8, 0.7]]),
        feature_axis=FeatureAxis(values=np.array([0.0, 1.0]), labels=["PC1", "PC2"], title="Principal Component"),
        title="PCA Scores",
        data_role="X_features",
        extra={
            "type": "PCA",
            "isPCA": True,
            "explained_variance_ratio": [0.7, 0.2],
            "t2": [1.0, 2.0, 3.0],
            "spe": [0.1, 0.2, 0.3],
            "t2_p95": 4.0,
            "spe_p95": 0.5,
        },
    )
    node = StatsSummaryNode(node_id="stats_pca_scores", parameters={})

    result = await node.execute(dataset)
    stats = result["statistics"]

    assert stats["input_type"] == "PCA"
    assert stats["summary"]["total_variance_explained"] == pytest.approx(0.9)
    assert stats["detailed"]["diagnostics"]["t2"] == [1.0, 2.0, 3.0]
    assert stats["plots"]["scree"]["y"] == [0.7, 0.2]


@pytest.mark.anyio
async def test_statistics_surfaces_dataset_quality_summary() -> None:
    dataset = SherpaDataset(
        X=np.array([[0.1, 0.8], [0.4, 0.5], [0.7, 0.2]]),
        feature_axis=FeatureAxis(values=np.array([0.0, 1.0]), labels=["Component 1", "Component 2"], title="Component"),
        title="MCR-ALS Concentration Profiles",
        data_role="X_features",
        extra={
            "type": "MCR_ALS",
            "quality_summary": {
                "n_iter": 17,
                "lof_percent": 4.2,
                "residual_rms": 0.01,
                "ground_truth_selected_r2": 0.93,
            },
        },
    )
    node = StatsSummaryNode(node_id="stats_mcr_quality", parameters={})

    result = await node.execute(dataset)
    stats = result["statistics"]

    assert stats["input_type"] == "FeatureTable"
    assert stats["summary"]["quality"]["lof_percent"] == 4.2
    assert stats["summary"]["quality"]["n_iter"] == 17
    assert stats["summary"]["quality"]["ground_truth_selected_r2"] == 0.93


@pytest.mark.anyio
async def test_plot_accepts_categorical_model_outputs_as_bar_counts() -> None:
    node = PlotNode(node_id="plot_labels", parameters={})

    result = await node.execute({"labels": ["cluster_1", "cluster_2", "cluster_1"]})

    vis = result["visualization"]
    assert vis["plot_type"] == "bar"
    assert vis["data"][0]["type"] == "bar"
    assert vis["data"][0]["x"][0] == "cluster_1"
    assert vis["data"][0]["y"][0] == 2


@pytest.mark.anyio
async def test_plot_and_contour_accept_numeric_transform_result_dicts() -> None:
    matrix = np.arange(12, dtype=float).reshape(4, 3)

    plot = await PlotNode(node_id="plot_result", parameters={"plot_type": "scores"}).execute({"result": matrix})
    assert plot["visualization"]["plot_type"] == "scatter"
    assert plot["visualization"]["data"][0]["x"] == [0.0, 3.0, 6.0, 9.0]

    contour = await ContourPlotNode(node_id="contour_result", parameters={"plot_type": "heatmap"}).execute(
        {"transformed": matrix}
    )
    assert contour["visualization"]["plot_type"] == "heatmap"
    assert contour["visualization"]["data"][0]["z"] == matrix.tolist()


@pytest.mark.anyio
async def test_export_counts_array_like_model_outputs() -> None:
    node = ExportNode(node_id="export_labels", parameters={"filename": "labels.csv", "format": "csv"})

    result = await node.execute({"labels": ["A", "B", "A"]})

    info = result["file_info"]
    assert info["data_points"] == 3
    assert "3 data points" in info["message"]
