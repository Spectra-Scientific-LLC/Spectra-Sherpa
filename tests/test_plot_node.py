from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from spectra_sherpa.app.lib.axes import FeatureAxis
from spectra_sherpa.app.lib.sherpa_dataset import SherpaDataset
from spectra_sherpa.app.services.dag.nodes.output import PlotNode


def test_frontend_validation_ledger_fixture_matches_canonical_producer():
    from spectra_sherpa.app.services.dag.regression_comparison import build_regression_comparison

    comparison = build_regression_comparison(
        [1, 2], [1.1, 1.8], role="held_out_test", sample_labels=["A", "B"], target_names=["density"]
    )
    actual = PlotNode("plot", {})._plot_regression_comparison(comparison)["visualization"]
    fixture = Path(__file__).resolve().parents[1] / "frontend/src/test/fixtures/regression-comparison-plot.json"
    assert actual == json.loads(fixture.read_text())
    assert actual["metadata"]["n_rows"] == 2
    assert actual["data"][-1]["mode"] == "lines"


@pytest.mark.anyio
async def test_plot_node_biplot_with_scores_and_loadings() -> None:
    node = PlotNode(
        node_id="plot_biplot",
        parameters={"plot_type": "biplot", "x_axis": 0, "y_axis": 1},
    )

    payload = {
        "scores": [
            [1.1, 0.2],
            [0.7, -0.4],
            [-0.6, 0.9],
        ],
        "loadings": [
            [0.4, -0.3, 0.1],
            [0.2, 0.5, -0.4],
        ],
    }

    result = await node.execute(payload)
    vis = result["visualization"]

    assert vis["plot_type"] == "biplot"
    assert len(vis["data"]) >= 3
    assert vis["data"][0]["name"] == "Scores"
    assert vis["data"][1]["name"] == "Loadings"
    assert vis["layout"]["xaxis"]["title"].startswith("PC1")
    assert vis["layout"]["yaxis"]["title"].startswith("PC2")


@pytest.mark.anyio
async def test_plot_node_biplot_falls_back_to_scores_when_loadings_missing() -> None:
    node = PlotNode(
        node_id="plot_biplot_no_loadings",
        parameters={"plot_type": "biplot", "x_axis": 0, "y_axis": 1},
    )

    payload = {
        "scores": [
            [1.0, 2.0],
            [3.0, 4.0],
        ],
    }

    result = await node.execute(payload)
    vis = result["visualization"]

    assert vis["plot_type"] == "biplot"
    assert len(vis["data"]) == 1
    assert vis["data"][0]["name"] == "Scores"


@pytest.mark.anyio
async def test_plot_node_renders_predicted_vs_actual_payload() -> None:
    node = PlotNode(node_id="plot_holdout_reg", parameters={"plot_type": "scatter"})

    result = await node.execute(
        {
            "type": "predicted_vs_actual",
            "data": [[1.0, 0.9], [2.0, 2.1], [3.0, 3.2]],
            "metadata": {"task_type": "regression"},
        }
    )
    vis = result["visualization"]

    assert vis["plot_type"] == "scatter"
    assert len(vis["data"]) == 2
    assert vis["data"][0]["name"] == "Test"
    assert vis["data"][1]["name"] == "Ideal"
    assert vis["layout"]["xaxis"]["title"] == "Actual"
    assert vis["layout"]["yaxis"]["title"] == "Predicted"


@pytest.mark.anyio
async def test_plot_node_renders_canonical_regression_comparison_as_scatter() -> None:
    """Row records must never fall through to the categorical-count plot."""

    node = PlotNode(node_id="plot_canonical_comparison", parameters={})
    rows = [
        {
            "sample": "Corn 1",
            "target": "Moisture",
            "reference": 10.0,
            "predicted": 9.8,
            "residual": 0.2,
            "role": "held_out_test",
        },
        {
            "sample": "Corn 2",
            "target": "Moisture",
            "reference": 11.0,
            "predicted": 11.1,
            "residual": -0.1,
            "role": "held_out_test",
        },
    ]

    result = await node.execute(
        {
            "schema_version": "spectrasherpa-regression-comparison/1",
            "shape": [2, 6],
            "data": rows,
            "metadata": {
                "column_names": ["sample", "target", "reference", "predicted", "residual", "role"],
                "n_samples": 2,
                "n_targets": 1,
                "target_names": ["Moisture"],
                "role": "held_out_test",
                "residual_definition": "reference_minus_predicted",
            },
        }
    )
    vis = result["visualization"]

    assert vis["plot_type"] == "scatter"
    assert vis["metadata"]["source_schema"] == "spectrasherpa-regression-comparison/1"
    assert [trace["name"] for trace in vis["data"]] == ["Moisture", "1:1 Line"]
    assert vis["data"][0]["type"] == "scatter"
    assert vis["data"][0]["x"] == [10.0, 11.0]
    assert vis["data"][0]["y"] == [9.8, 11.1]
    assert vis["metadata"]["n_rows"] == 2
    assert vis["layout"]["title"] == "Predicted vs Reference — Moisture · held out test"
    assert vis["layout"]["xaxis"] == {
        "title": "Reference — Moisture",
        "range": pytest.approx([9.735, 11.165]),
        "constrain": "domain",
    }
    assert vis["layout"]["yaxis"] == {
        "title": "Predicted — Moisture",
        "range": pytest.approx([9.735, 11.165]),
        "scaleanchor": "x",
        "scaleratio": 1,
        "constrain": "domain",
    }


@pytest.mark.anyio
async def test_plot_node_renders_train_and_test_predicted_vs_actual_payload() -> None:
    node = PlotNode(node_id="plot_holdout_reg_split", parameters={"plot_type": "scatter"})

    result = await node.execute(
        {
            "type": "predicted_vs_actual",
            "data": [[4.0, 3.9], [5.0, 5.1]],
            "metadata": {
                "task_type": "regression",
                "r2_test": 0.98,
                "rmse_test": 0.1,
                "r2_train": 0.99,
                "rmse_train": 0.05,
                "train": {"data": [[1.0, 1.0], [2.0, 2.1]]},
            },
        }
    )
    vis = result["visualization"]

    assert [trace["name"] for trace in vis["data"]] == ["Train", "Test", "Ideal"]
    assert "Train R²=0.990" in vis["layout"]["title"]


@pytest.mark.anyio
async def test_plot_node_renders_confusion_matrix_payload() -> None:
    node = PlotNode(node_id="plot_holdout_cls", parameters={"plot_type": "heatmap"})

    result = await node.execute(
        {
            "type": "confusion_matrix",
            "data": [[8, 1], [2, 9]],
            "metadata": {"classes": ["Class A", "Class B"]},
        }
    )
    vis = result["visualization"]

    assert vis["plot_type"] == "heatmap"
    assert vis["data"][0]["type"] == "heatmap"
    assert vis["data"][0]["x"] == ["Class A", "Class B"]
    assert vis["data"][0]["y"] == ["Class A", "Class B"]
    assert vis["layout"]["xaxis"]["title"] == "Predicted Class"
    assert vis["layout"]["yaxis"]["title"] == "True Class"


@pytest.mark.anyio
async def test_plot_node_honors_scores_plot_type_for_score_dataset() -> None:
    dataset = SherpaDataset(
        X=np.array([[1.0, 0.2], [0.4, -0.6], [-0.8, 0.7]]),
        feature_axis=FeatureAxis(values=np.array([0.0, 1.0]), labels=["PC1", "PC2"], title="Principal Component"),
        title="PCA Scores",
        data_role="X_features",
        extra={"type": "PCA", "isPCA": True},
    )
    node = PlotNode(node_id="plot_scores_dataset", parameters={"plot_type": "spectra", "x_axis": 0, "y_axis": 1})

    result = await node.execute(dataset)
    vis = result["visualization"]

    assert vis["plot_type"] == "scores"
    assert vis["data"][0]["type"] == "scatter"
    assert vis["data"][0]["mode"] == "markers"
    assert vis["layout"]["xaxis"]["title"] == "PC1"
    assert vis["layout"]["yaxis"]["title"] == "PC2"


@pytest.mark.anyio
async def test_plot_node_honors_scores_metadata_even_without_score_title() -> None:
    dataset = SherpaDataset(
        X=np.array([[1.0, 0.2], [0.4, -0.6], [-0.8, 0.7]]),
        feature_axis=FeatureAxis(values=np.array([0.0, 1.0]), labels=["PC1", "PC2"], title="Principal Component"),
        title="PCA Transform",
        data_role="X_features",
        extra={"type": "PCA", "isPCA": True},
    )
    node = PlotNode(node_id="plot_scores_by_axis", parameters={"plot_type": "spectra", "x_axis": 0, "y_axis": 1})

    result = await node.execute(dataset)
    vis = result["visualization"]

    assert vis["plot_type"] == "scores"
    assert vis["data"][0]["type"] == "scatter"
    assert vis["layout"]["xaxis"]["title"] == "PC1"


@pytest.mark.anyio
async def test_plot_node_renders_component_profiles_by_sample() -> None:
    dataset = SherpaDataset(
        X=np.array([[0.1, 0.8], [0.4, 0.5], [0.7, 0.2]]),
        feature_axis=FeatureAxis(values=np.array([0.0, 1.0]), labels=["Component 1", "Component 2"], title="Component"),
        title="MCR-ALS Concentration Profiles",
        data_role="X_features",
        extra={"type": "MCR_ALS"},
    )
    node = PlotNode(node_id="plot_profiles", parameters={"plot_type": "spectra"})

    result = await node.execute(dataset)
    vis = result["visualization"]

    assert vis["plot_type"] == "profiles"
    assert [trace["name"] for trace in vis["data"]] == ["Component 1", "Component 2"]
    assert vis["data"][0]["x"] == [1, 2, 3]
    assert vis["data"][0]["y"] == [0.1, 0.4, 0.7]


@pytest.mark.anyio
async def test_plot_node_renders_efa_eigenvalues_as_log_profiles() -> None:
    dataset = SherpaDataset(
        X=np.array([[10.0, 1.0], [5.0, 0.5], [2.5, 0.25]]),
        feature_axis=FeatureAxis(values=np.array([0.0, 1.0]), labels=["EV1", "EV2"], title="Component"),
        title="EFA Forward Eigenvalues",
        data_role="X_features",
        extra={"type": "EFA"},
    )
    node = PlotNode(node_id="plot_efa", parameters={"plot_type": "spectra"})

    result = await node.execute(dataset)
    vis = result["visualization"]

    assert vis["plot_type"] == "profiles"
    assert [trace["name"] for trace in vis["data"]] == ["EV1", "EV2"]
    assert vis["layout"]["yaxis"]["type"] == "log"


@pytest.mark.anyio
async def test_plot_node_passes_through_dendrogram_payload() -> None:
    node = PlotNode(node_id="plot_dendrogram", parameters={"plot_type": "dendrogram"})
    payload = {
        "data": [{"x": [0.0, 1.0], "y": [5.0, 5.0], "type": "scatter"}],
        "layout": {"title": "Hierarchical Clustering Dendrogram (ward linkage)"},
    }

    result = await node.execute(payload)
    vis = result["visualization"]

    assert vis["plot_type"] == "dendrogram"
    assert vis["data"] == payload["data"]
    assert vis["layout"] == payload["layout"]


@pytest.mark.anyio
async def test_plot_node_selects_payload_from_bare_plots_registry() -> None:
    node = PlotNode(
        node_id="plot_simca_registry",
        parameters={"plot_type": "scatter", "plot_key": "simca_acceptance"},
    )
    payload = {
        "confusion_matrix_train": {
            "data": [{"z": [[2, 0], [1, 3]], "type": "heatmap"}],
            "layout": {"title": "Training Confusion Matrix"},
        },
        "simca_acceptance": {
            "type": "simca_acceptance",
            "data": [{"x": [0.2, 1.3], "y": [0.5, 0.8], "type": "scatter"}],
            "layout": {"title": "SIMCA T²/Q Acceptance"},
        },
    }

    result = await node.execute(payload)
    vis = result["visualization"]

    assert vis["plot_type"] == "scatter"
    assert vis["layout"]["title"] == "SIMCA T²/Q Acceptance"
    assert vis["data"][0]["x"] == [0.2, 1.3]


@pytest.mark.anyio
async def test_plot_node_renders_calibration_transfer_error_dict() -> None:
    node = PlotNode(node_id="plot_transfer_error", parameters={"plot_type": "scatter"})

    result = await node.execute(
        {
            "rmse_transfer": 0.12,
            "max_error": 0.31,
            "per_feature_rmse": [0.1, 0.2, 0.15],
            "n_features": 3,
            "n_transfer_samples": 8,
        }
    )
    vis = result["visualization"]

    assert vis["plot_type"] == "transfer_error"
    assert [trace["name"] for trace in vis["data"]] == ["Per-feature RMSE", "Summary"]
    assert vis["data"][0]["y"] == [0.1, 0.2, 0.15]
    assert vis["metadata"]["rmse_transfer"] == 0.12


@pytest.mark.anyio
async def test_plot_node_renders_regression_cv_metric_dict() -> None:
    node = PlotNode(node_id="plot_nested_cv", parameters={"plot_type": "spectra"})
    payload = {
        "metadata": {"type": "RegressionCV"},
        "rmsecv": 0.12,
        "r2_cv": 0.91,
        "q2": 0.9,
        "bias": -0.01,
        "sep": 0.11,
        "slope": 0.98,
        "intercept": 0.02,
        "rer": 19.4,
        "per_fold_n_selected": [12, 10, 11],
        "per_fold_mse": [0.01, 0.02, 0.015],
        "selection_method": "vip",
    }

    result = await node.execute(payload)
    vis = result["visualization"]

    assert vis["plot_type"] == "metrics"
    assert {trace["name"] for trace in vis["data"]} == {"Outer-fold RMSE", "Variables Selected"}
    assert vis["data"][0]["y"] == pytest.approx([0.1, np.sqrt(0.02), np.sqrt(0.015)])
    assert vis["layout"]["xaxis"]["title"] == "Outer Fold"
    assert vis["layout"]["yaxis"]["title"] == "Outer-fold RMSE"
    assert vis["layout"]["yaxis2"]["title"] == "Variables Selected"
    summary = vis["layout"]["annotations"][0]["text"]
    assert "RMSECV 0.12" in summary
    assert "R² CV 0.91" in summary
    assert "Q² 0.9" in summary
    assert "RER 19.4" in summary
