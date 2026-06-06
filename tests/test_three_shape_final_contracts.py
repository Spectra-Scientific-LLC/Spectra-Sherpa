from __future__ import annotations

import numpy as np
import pytest

from spectra_sherpa.app.lib.axes import FeatureAxis
from spectra_sherpa.app.lib.sherpa_dataset import SherpaDataset, TargetContext
from spectra_sherpa.app.services.dag.nodes.classification.knn_nodes import KNNNode
from spectra_sherpa.app.services.dag.nodes.classification.plsda_nodes import PLSDANode
from spectra_sherpa.app.services.dag.nodes.classification.simca_nodes import SIMCANode
from spectra_sherpa.app.services.dag.nodes.modeling.clustering_nodes import HCANode
from spectra_sherpa.app.services.dag.nodes.modeling.core_utils import create_spectral_dataset
from spectra_sherpa.app.services.dag.nodes.modeling.pca_nodes import PCANode
from spectra_sherpa.app.services.dag.nodes.output import PlotNode
from spectra_sherpa.app.services.dag.nodes.output.stats_summary_node import StatsSummaryNode


def _feature_dataset() -> SherpaDataset:
    rng = np.random.default_rng(42)
    X = np.vstack(
        [
            rng.normal(loc=-2.0, scale=0.2, size=(8, 5)),
            rng.normal(loc=0.0, scale=0.2, size=(8, 5)),
            rng.normal(loc=2.0, scale=0.2, size=(8, 5)),
        ]
    )
    y = np.array(["low"] * 8 + ["mid"] * 8 + ["high"] * 8, dtype=object)
    return SherpaDataset(
        X=X,
        feature_axis=FeatureAxis(
            values=np.arange(X.shape[1], dtype=np.float64),
            labels=[f"feature_{i + 1}" for i in range(X.shape[1])],
            title="Feature",
        ),
        target=y,
        target_context=TargetContext(target_type="categorical", target_name="class"),
        data_role="X_features",
    )


def test_plsda_declares_latent_and_probability_ports() -> None:
    ports = {port.name for port in PLSDANode.metadata.output_ports or []}

    assert {"default", "X_scores", "loadings", "X_loadings"}.issubset(ports)
    assert {"predictions", "probabilities", "class_probabilities", "metrics"}.issubset(ports)


def test_classifiers_declare_canonical_metrics_port() -> None:
    for node_cls in (KNNNode, PLSDANode, SIMCANode):
        ports = {port.name for port in node_cls.metadata.output_ports or []}
        assert "metrics" in ports


def test_pca_declares_cross_technique_score_aliases() -> None:
    ports = {port.name for port in PCANode.metadata.output_ports or []}

    assert {"default", "scores", "X_scores", "loadings", "X_loadings"}.issubset(ports)


def test_create_spectral_dataset_preserves_feature_axis_role() -> None:
    dataset = create_spectral_dataset(
        data=np.ones((2, 3), dtype=np.float64),
        x_coord=FeatureAxis(values=np.arange(3), labels=["a", "b", "c"], title="Feature"),
        y_coord=["row_1", "row_2"],
    )

    assert dataset.data_role == "X_features"
    assert isinstance(dataset.feature_axis, FeatureAxis)


def test_generated_python_outputs_match_declared_latent_contracts() -> None:
    knn_code = "\n".join(KNNNode(node_id="knn").generate_python({"X": "X", "y": "y"}))
    hca_code = "\n".join(HCANode(node_id="hca").generate_python({"default": "X"}))
    simca_code = "\n".join(SIMCANode(node_id="simca").generate_python({"X": "X", "y": "y"}))

    assert "'default': _sample_coordinates" in knn_code
    assert "'embedding': _embedding.tolist()" in hca_code
    assert "'dendrogram_data': _dendrogram_data" in hca_code
    assert "'default': _default_scores" in simca_code
    assert "'class_distance_matrix': _class_distance_matrix" in simca_code


@pytest.mark.anyio
async def test_knn_emits_comparable_feature_outputs() -> None:
    dataset = _feature_dataset()
    node = KNNNode(node_id="knn_contract", parameters={"n_neighbors": 3, "cv_folds": 4})

    result = await node.execute(X=dataset, y=dataset.target)
    outputs = result.outputs

    assert outputs["default"].data_role == "X_features"
    assert len(outputs["predictions"]) == dataset.shape[0]
    assert np.asarray(outputs["probabilities"]).shape == (dataset.shape[0], 3)
    assert outputs["class_probabilities"] == outputs["probabilities"]
    assert outputs["metrics"]["task_type"] == "classification"
    assert outputs["metrics"]["method"] == "knn"
    assert set(outputs["metrics"]["splits"]) >= {"train", "cv"}
    assert np.asarray(outputs["distances"]).shape == (dataset.shape[0], 3)
    assert np.asarray(outputs["neighbor_indices"]).shape == (dataset.shape[0], 3)
    assert 0.0 <= outputs["train_accuracy"] <= 1.0
    assert 0.0 <= outputs["cv_accuracy"] <= 1.0
    assert 0.0 <= outputs["cv_balanced_accuracy"] <= 1.0
    assert 0.0 <= outputs["cv_f1_macro"] <= 1.0
    assert 0.0 <= outputs["cv_sensitivity_macro"] <= 1.0
    assert 0.0 <= outputs["cv_specificity_macro"] <= 1.0


@pytest.mark.anyio
async def test_hca_exposes_cluster_assignment_and_dendrogram_data() -> None:
    dataset = _feature_dataset()
    node = HCANode(node_id="hca_contract", parameters={"n_clusters": 3, "linkage": "ward", "metric": "euclidean"})

    result = await node.execute(input_data=dataset)
    outputs = result.outputs

    assert outputs["cluster_assignment"] == outputs["labels"]
    assert len(outputs["cluster_assignment"]) == dataset.shape[0]
    assert np.asarray(outputs["linkage_matrix"]).shape[1] == 4
    assert outputs["dendrogram_data"] == outputs["plots"]["dendrogram"]


@pytest.mark.anyio
async def test_plot_node_renders_x_features_as_feature_bars() -> None:
    dataset = _feature_dataset()
    node = PlotNode(node_id="plot_features", parameters={"plot_type": "spectra"})

    result = await node.execute(dataset)
    vis = result["visualization"]

    assert vis["plot_type"] == "features"
    assert vis["data"][0]["type"] == "bar"
    assert vis["data"][0]["x"] == ["feature_1", "feature_2", "feature_3", "feature_4", "feature_5"]
    assert vis["layout"]["xaxis"]["title"] == "Feature"


@pytest.mark.anyio
async def test_statistics_node_labels_x_features_as_features() -> None:
    dataset = _feature_dataset()
    node = StatsSummaryNode(node_id="stats_features", parameters={})

    result = await node.execute(dataset)
    stats = result["statistics"]

    assert stats["input_type"] == "FeatureTable"
    assert "feature" in stats["data"][0]
    assert "wavelength" not in stats["data"][0]
    assert stats["plots"]["mean_spectrum"]["type"] == "bar"
    assert stats["plots"]["std_spectrum"]["type"] == "bar"
    assert stats["plots"]["mean_feature_response"]["type"] == "bar"
    assert stats["metadata"]["data_role"] == "X_features"
