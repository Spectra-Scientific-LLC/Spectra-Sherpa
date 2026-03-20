from __future__ import annotations

import pytest

from spectra_sherpa.app.services.dag.nodes.output import PlotNode


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
    assert vis["data"][0]["name"] == "Predictions"
    assert vis["data"][1]["name"] == "Ideal"
    assert vis["layout"]["xaxis"]["title"] == "Actual"
    assert vis["layout"]["yaxis"]["title"] == "Predicted"


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
