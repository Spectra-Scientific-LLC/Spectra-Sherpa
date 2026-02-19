"""Tests for newly added modeling nodes (PCR/SVR/HCA/KMeans/DBSCAN)."""

from __future__ import annotations

import numpy as np
import pytest

scp = pytest.importorskip("spectrochempy")
from spectrochempy import NDDataset

from spectra_sherpa.app.lib.analysis_dataset import AnalysisDataset, AxisInfo
from spectra_sherpa.app.services.dag import node_registry


def _make_regression_dataset(
    n_samples: int = 40,
    n_features: int = 8,
    noise: float = 0.02,
    seed: int = 42,
) -> tuple[NDDataset, np.ndarray]:
    rng = np.random.default_rng(seed)
    X = rng.normal(size=(n_samples, n_features))
    coefficients = np.linspace(1.2, 0.3, n_features)
    y = X @ coefficients + noise * rng.normal(size=n_samples)
    return scp.NDDataset(X), y


def _make_cluster_dataset(seed: int = 7) -> NDDataset:
    rng = np.random.default_rng(seed)
    cluster_a = rng.normal(loc=-2.0, scale=0.12, size=(12, 2))
    cluster_b = rng.normal(loc=2.0, scale=0.12, size=(12, 2))
    data = np.vstack([cluster_a, cluster_b])
    return scp.NDDataset(data)


@pytest.mark.asyncio
async def test_pcr_node_regression_fit():
    X_dataset, y = _make_regression_dataset()
    node = node_registry.create_node(
        node_type="model.pcr",
        node_id="pcr_test",
        parameters={"n_components": 7, "scale": True},
    )

    result = await node.run(X=X_dataset, y=y)
    outputs = result.outputs

    scores_ds = outputs["default"]
    assert scores_ds.shape == (X_dataset.shape[0], 7)
    assert scores_ds.meta["r2"] > 0.8


@pytest.mark.asyncio
async def test_svr_node_regression_fit():
    X_dataset, y = _make_regression_dataset(seed=13)
    node = node_registry.create_node(
        node_type="model.svr",
        node_id="svr_test",
        parameters={"kernel": "linear", "C": 10.0, "epsilon": 0.01, "scale": True},
    )

    result = await node.run(X=X_dataset, y=y)
    outputs = result.outputs

    assert len(outputs["y_pred"]) == X_dataset.shape[0]
    assert outputs["r2"] > 0.9
    # Verify post-fit outputs from _svr_post_fit
    assert "support_vectors" in outputs, "SVR should return support_vectors"
    assert isinstance(outputs["support_vectors"], list)
    assert "data" in outputs, "SVR should return obs/pred data pairs"
    assert isinstance(outputs["data"], list)
    assert "metadata" in outputs, "SVR should return metadata dict"
    assert outputs["metadata"]["type"] == "SVR"
    assert outputs["metadata"]["kernel"] == "linear"


@pytest.mark.asyncio
async def test_linear_regression_node_fit():
    X_dataset, y = _make_regression_dataset(seed=99)
    node = node_registry.create_node(
        node_type="model.linear_regression",
        node_id="lr_test",
        parameters={"fit_intercept": True},
    )

    result = await node.run(X=X_dataset, y=y)
    outputs = result.outputs

    assert len(outputs["y_pred"]) == X_dataset.shape[0]
    assert outputs["r2"] > 0.9
    # Verify post-fit outputs from _lr_post_fit
    assert "coef" in outputs, "LR should return coefficients"
    assert isinstance(outputs["coef"], list)
    assert len(outputs["coef"]) == X_dataset.shape[1]
    assert "intercept" in outputs
    assert "score" in outputs
    assert outputs["score"] > 0.9


@pytest.mark.asyncio
async def test_hca_node_clusters():
    dataset = _make_cluster_dataset()
    node = node_registry.create_node(
        node_type="model.hca",
        node_id="hca_test",
        parameters={"n_clusters": 2, "linkage": "ward", "metric": "euclidean"},
    )

    result = await node.run(dataset)
    outputs = result.outputs

    assert outputs["n_clusters"] == 2
    assert len(outputs["labels"]) == dataset.shape[0]


@pytest.mark.asyncio
async def test_kmeans_node_clusters():
    dataset = _make_cluster_dataset(seed=9)
    node = node_registry.create_node(
        node_type="model.kmeans",
        node_id="kmeans_test",
        parameters={"n_clusters": 2, "n_init": 10, "max_iter": 200, "random_state": 42},
    )

    result = await node.run(dataset)
    outputs = result.outputs

    assert outputs["n_clusters"] == 2
    assert len(outputs["labels"]) == dataset.shape[0]
    assert len(outputs["centroids"]) == 2


@pytest.mark.asyncio
async def test_dbscan_node_clusters():
    dataset = _make_cluster_dataset(seed=11)
    node = node_registry.create_node(
        node_type="model.dbscan",
        node_id="dbscan_test",
        parameters={"eps": 0.4, "min_samples": 3, "metric": "euclidean"},
    )

    result = await node.run(dataset)
    outputs = result.outputs

    assert outputs["n_clusters"] == 2
    assert len(outputs["labels"]) == dataset.shape[0]


@pytest.mark.asyncio
async def test_pca_node_after_snv_accepts_analysis_dataset_units():
    rng = np.random.default_rng(21)
    data = rng.normal(size=(18, 40))
    dataset = AnalysisDataset(
        X=data,
        x_axis=AxisInfo(
            values=np.linspace(950.0, 1650.0, 40),
            units="cm^-1",
            title="Wavenumber",
        ),
        y_axis=AxisInfo(values=np.arange(18), title="Sample"),
        units="absorbance",
    )

    snv_node = node_registry.create_node(
        node_type="normalize.snv",
        node_id="snv_before_pca",
        parameters={},
    )
    snv_result = await snv_node.run(default=dataset)
    snv_output = snv_result.outputs["default"]

    assert isinstance(snv_output, AnalysisDataset)
    assert snv_output.units == "dimensionless"

    pca_node = node_registry.create_node(
        node_type="model.pca",
        node_id="pca_after_snv",
        parameters={"n_components": "3"},
    )
    pca_result = await pca_node.run(default=snv_output)
    outputs = pca_result.outputs

    assert "scores" in outputs
    assert isinstance(outputs["scores"], AnalysisDataset)
    assert outputs["scores"].shape == (18, 3)
