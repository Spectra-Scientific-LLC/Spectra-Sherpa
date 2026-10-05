from __future__ import annotations

import numpy as np
import pytest

from spectra_sherpa.app.lib.axes import FeatureAxis
from spectra_sherpa.app.lib.sherpa_dataset import SherpaDataset
from spectra_sherpa.app.services.dag.node_base import SalientFeature, SalientFeatures
from spectra_sherpa.app.services.dag.nodes.output import ContourPlotNode, DataTableNode, ExportNode, PlotNode
from spectra_sherpa.app.services.dag.nodes.output.data_table_node import build_data_table_result
from spectra_sherpa.app.services.dag.nodes.output.stats_summary_node import StatsSummaryNode


@pytest.mark.parametrize("serialized", [False, True])
def test_salient_feature_table_preserves_rows_and_context(serialized) -> None:
    from dataclasses import asdict

    value = SalientFeatures(
        method="peak_finding",
        features=[
            SalientFeature(position=1206, importance=1, label="consensus peak (155/155 samples)"),
            SalientFeature(position=1690, importance=6 / 155, label="consensus peak (6/155 samples)"),
        ],
        x_units="nm",
        x_title="Wavelength",
        n_total_variables=571,
        selection_context={"n_samples": 155},
    )
    table = build_data_table_result(asdict(value) if serialized else value)["visualization"]
    assert table["data"][1] == {
        "consensus_group": 2,
        "position": 1690,
        "detection_fraction": 6 / 155,
        "label": "consensus peak (6/155 samples)",
    }
    assert table["metadata"]["n_rows"] == 2
    assert table["metadata"]["column_units"] == {"position": "nm"}
    assert table["metadata"]["selection_context"] == {"n_samples": 155}
    assert table["metadata"]["n_total_variables"] == 571


def test_table_plot_selects_late_columns_and_keeps_null_row_indices() -> None:
    from spectra_sherpa.app.services.dag.nodes.output.plot_node import build_plot_result

    names = [f"measurement_{index}" for index in range(44)]
    rows = [[float(index) for index in range(44)] for _ in range(3)]
    rows[1][43] = None
    table = {"data": rows, "metadata": {"column_names": names, "column_units": {names[43]: "nm"}}}
    plot = build_plot_result(table, parameters={"plot_key": "column:measurement_43"})["visualization"]
    assert plot["data"][0]["x"] == [1, 2, 3]
    assert plot["data"][0]["y"] == [43, None, 43]
    assert plot["layout"]["yaxis"]["title"] == "measurement_43 (nm)"
    missing = build_plot_result({"data": [{"empty": None}], "metadata": {"column_names": ["empty"]}})["visualization"]
    assert missing["data"][0]["y"] == [None]
    assert "all values are missing" in missing["layout"]["annotations"][0]["text"]


def test_salient_feature_table_handles_empty_generic_and_truncated_values() -> None:
    value = SalientFeatures(method="vip", features=[])
    assert build_data_table_result(value)["visualization"]["data"] == []
    value.features = [SalientFeature(position=i, importance=2.5) for i in range(12)]
    table = build_data_table_result(value, parameters={"max_rows": 10})["visualization"]
    assert len(table["data"]) == 10
    assert table["data"][9]["importance"] == 2.5
    assert table["data"][9]["feature_index"] == 10
    assert table["metadata"]["truncated"] is True


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
async def test_export_rejects_untyped_model_output_dictionaries() -> None:
    node = ExportNode(node_id="export_labels", parameters={"filename": "labels.csv", "format": "csv"})

    with pytest.raises(ValueError, match="canonical dataset"):
        await node.execute({"labels": ["A", "B", "A"]})
