"""Tests for newly added modeling nodes (PCR/SVR/HCA/KMeans/DBSCAN)."""

from __future__ import annotations

import numpy as np
import pytest

pytest.importorskip("spectrochempy")

from spectra_sherpa.app.lib.scp_compat import NDDataset, scp
from spectra_sherpa.app.lib.sherpa_dataset import SampleAxis, SherpaDataset, SpectralAxis, TargetContext
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


def _make_multitarget_regression_dataset(
    n_samples: int = 42,
    n_features: int = 9,
    n_targets: int = 3,
    noise: float = 0.01,
    seed: int = 314,
) -> tuple[SherpaDataset, np.ndarray, list[str]]:
    rng = np.random.default_rng(seed)
    X = rng.normal(size=(n_samples, n_features))
    coefficients = rng.normal(size=(n_features, n_targets))
    y = X @ coefficients + noise * rng.normal(size=(n_samples, n_targets))
    target_names = [f"Property {idx + 1}" for idx in range(n_targets)]
    dataset = SherpaDataset(
        X=X,
        feature_axis=SpectralAxis(values=np.linspace(900.0, 1700.0, n_features), units="nm"),
        sample_axis=SampleAxis(labels=[f"sample-{idx + 1}" for idx in range(n_samples)]),
        target=y,
        target_context=TargetContext(target_type="continuous", target_names=target_names),
        data_role="X_spectra",
        title="multi-target calibration",
    )
    return dataset, y, target_names


def _make_incomplete_multitarget_dataset() -> tuple[SherpaDataset, np.ndarray, list[str]]:
    dataset, y, target_names = _make_multitarget_regression_dataset(n_samples=30, n_features=7, n_targets=3)
    incomplete = y.copy()
    incomplete[:10, 1:] = np.nan
    incomplete[10:20, [0, 2]] = np.nan
    incomplete[20:25, :2] = np.nan
    dataset.target = incomplete
    return dataset, incomplete, target_names


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
    assert scores_ds.quality.latest is not None
    assert scores_ds.quality.latest.model_type == "PCR"
    assert scores_ds.quality.latest.r2 is not None


@pytest.mark.asyncio
async def test_pcr_node_multitarget_preserves_target_dimensions():
    X_dataset, y, target_names = _make_multitarget_regression_dataset()
    node = node_registry.create_node(
        node_type="model.pcr",
        node_id="pcr_multitarget_test",
        parameters={"n_components": 4, "scale": True},
    )

    result = await node.run(X=X_dataset, y=y)
    scores_ds = result.outputs["default"]

    assert scores_ds.shape == (X_dataset.shape[0], 4)
    assert scores_ds.meta["training_X_shape"] == [X_dataset.shape[0], X_dataset.shape[1]]
    assert scores_ds.meta["training_y_shape"] == [X_dataset.shape[0], y.shape[1]]
    assert scores_ds.meta["output_dimensions"]["y_pred"] == [X_dataset.shape[0], y.shape[1]]
    assert scores_ds.meta["target_names"] == target_names
    assert len(scores_ds.meta["r2_per_target"]) == y.shape[1]
    assert len(scores_ds.meta["rmse_per_target"]) == y.shape[1]


@pytest.mark.asyncio
async def test_pcr_node_rejects_incomplete_multitarget_without_selection():
    X_dataset, _y, _target_names = _make_incomplete_multitarget_dataset()
    node = node_registry.create_node(
        node_type="model.pcr",
        node_id="pcr_incomplete_target_test",
        parameters={"n_components": 2, "scale": True},
    )

    with pytest.raises(ValueError, match="incomplete multi-target reference values"):
        await node.run(X=X_dataset)


@pytest.mark.asyncio
async def test_pcr_node_selected_target_drops_incomplete_rows():
    X_dataset, y, target_names = _make_incomplete_multitarget_dataset()
    selected = target_names[1]
    X_dataset.target_context = X_dataset.target_context.model_copy(update={"selected_target": selected})
    valid_rows = int(np.isfinite(y[:, 1]).sum())
    node = node_registry.create_node(
        node_type="model.pcr",
        node_id="pcr_selected_target_test",
        parameters={"n_components": 2, "scale": True},
    )

    result = await node.run(X=X_dataset)
    scores_ds = result.outputs["default"]

    assert scores_ds.shape == (valid_rows, 2)
    assert scores_ds.meta["training_X_shape"] == [valid_rows, X_dataset.shape[1]]
    assert scores_ds.meta["training_y_shape"] == [valid_rows, 1]
    assert scores_ds.meta["target_names"] == [selected]


@pytest.mark.asyncio
async def test_pls_node_attaches_quality_evaluation():
    X_dataset, y = _make_regression_dataset(n_samples=36, n_features=6, seed=24)
    node = node_registry.create_node(
        node_type="model.pls",
        node_id="pls_test",
        parameters={"n_components": 3, "scale": True},
    )

    result = await node.run(X=X_dataset, y=y)
    outputs = result.outputs

    scores_ds = outputs["default"]
    assert isinstance(scores_ds, SherpaDataset)
    assert scores_ds.quality.latest is not None
    assert scores_ds.quality.latest.model_type == "PLS"
    assert scores_ds.quality.latest.n_components == 3
    assert scores_ds.quality.latest.r2 is None or isinstance(scores_ds.quality.latest.r2, float)
    assert scores_ds.quality.latest.rmse is None or isinstance(scores_ds.quality.latest.rmse, float)


@pytest.mark.asyncio
async def test_pls_node_rejects_incomplete_multitarget_without_selection():
    X_dataset, _y, _target_names = _make_incomplete_multitarget_dataset()
    node = node_registry.create_node(
        node_type="model.pls",
        node_id="pls_incomplete_target_test",
        parameters={"n_components": 2, "scale": True},
    )

    with pytest.raises(ValueError, match="incomplete multi-target reference values"):
        await node.run(X=X_dataset)


@pytest.mark.asyncio
async def test_pls_node_selected_target_uses_single_incomplete_property():
    X_dataset, y, target_names = _make_incomplete_multitarget_dataset()
    selected = target_names[1]
    X_dataset.target_context = X_dataset.target_context.model_copy(update={"selected_target": selected})
    valid_rows = int(np.isfinite(y[:, 1]).sum())
    node = node_registry.create_node(
        node_type="model.pls",
        node_id="pls_selected_target_test",
        parameters={"n_components": 2, "scale": True},
    )

    result = await node.run(X=X_dataset)
    scores_ds = result.outputs["default"]

    assert scores_ds.shape == (valid_rows, 2)
    assert scores_ds.meta["training_X_shape"] == [valid_rows, X_dataset.shape[1]]
    assert scores_ds.meta["training_y_shape"] == [valid_rows, 1]
    assert scores_ds.meta["target_names"] == [selected]
    assert scores_ds.meta["target_mode"] == "single"
    assert scores_ds.meta["selected_target"] == selected
    assert scores_ds.meta["quality_summary"]["target_names"] == [selected]
    assert scores_ds.meta["quality_summary"]["selected_target"] == selected
    assert result.diagnostics["target_names"] == [selected]
    assert result.diagnostics["selected_target"] == selected
    assert result.outputs["_model_artifact"]["metadata"]["target_names"] == [selected]
    assert result.outputs["_model_artifact"]["metadata"]["selected_target"] == selected
    assert result.outputs["cv_predictions"]["metadata"]["selected_target"] == selected
    assert result.outputs["Y_loadings"].shape == (1, 2)


def test_my_dataset_node_freezes_selected_target_per_sheet():
    X_dataset, _y, target_names = _make_incomplete_multitarget_dataset()
    selected = target_names[2]
    node = node_registry.create_node(
        node_type="data.my_dataset",
        node_id="my_dataset_selected_target_test",
        parameters={"target_mode": "single", "selected_target": selected},
    )

    output = node._apply_node_target_selection(X_dataset)

    assert output.target_context.selected_target == selected
    assert output.meta["target_mode"] == "single"
    assert output.meta["selected_target"] == selected


def test_my_dataset_node_rejects_stale_selected_target():
    X_dataset, _y, _target_names = _make_incomplete_multitarget_dataset()
    node = node_registry.create_node(
        node_type="data.my_dataset",
        node_id="my_dataset_bad_target_test",
        parameters={"target_mode": "single", "selected_target": "NoSuchProperty"},
    )

    with pytest.raises(ValueError, match="NoSuchProperty"):
        node._apply_node_target_selection(X_dataset)


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
async def test_svr_node_selects_one_target_from_multitarget_dataset():
    X_dataset, _y, target_names = _make_multitarget_regression_dataset()
    node = node_registry.create_node(
        node_type="model.svr",
        node_id="svr_single_target_test",
        parameters={"kernel": "linear", "C": 10.0, "epsilon": 0.01, "scale": True, "target_index": 2},
    )

    result = await node.run(X=X_dataset)
    outputs = result.outputs

    assert len(outputs["y_pred"]) == X_dataset.shape[0]
    assert len(outputs["residuals"]) == X_dataset.shape[0]
    assert outputs["metadata"]["n_targets"] == 1
    assert outputs["metadata"]["target_names"] == [target_names[1]]
    assert outputs["metadata"]["selected_target_index"] == 1
    assert outputs["metadata"]["available_target_names"] == target_names
    assert np.asarray(outputs["metadata"]["y_pred"]).shape == (X_dataset.shape[0], 1)


@pytest.mark.asyncio
async def test_svr_node_selected_target_drops_incomplete_rows():
    X_dataset, y, _target_names = _make_incomplete_multitarget_dataset()
    valid_rows = int(np.isfinite(y[:, 1]).sum())
    node = node_registry.create_node(
        node_type="model.svr",
        node_id="svr_incomplete_selected_target_test",
        parameters={"kernel": "linear", "C": 10.0, "epsilon": 0.01, "scale": True, "target_index": 2},
    )

    result = await node.run(X=X_dataset)
    outputs = result.outputs

    assert len(outputs["y_pred"]) == valid_rows
    assert len(outputs["residuals"]) == valid_rows
    assert outputs["metadata"]["n_samples"] == valid_rows


@pytest.mark.asyncio
async def test_svr_node_rejects_out_of_range_target_index():
    X_dataset, _y, _target_names = _make_multitarget_regression_dataset(n_targets=2)
    node = node_registry.create_node(
        node_type="model.svr",
        node_id="svr_bad_target_test",
        parameters={"kernel": "linear", "C": 1.0, "epsilon": 0.01, "scale": True, "target_index": 3},
    )

    with pytest.raises(ValueError, match="Target Property 3 is out of range"):
        await node.run(X=X_dataset)


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
async def test_linear_regression_node_multitarget_preserves_target_dimensions():
    X_dataset, _y, target_names = _make_multitarget_regression_dataset()
    node = node_registry.create_node(
        node_type="model.linear_regression",
        node_id="lr_multitarget_test",
        parameters={"fit_intercept": True},
    )

    result = await node.run(X=X_dataset)
    outputs = result.outputs

    assert np.asarray(outputs["y_pred"]).shape == (X_dataset.shape[0], len(target_names))
    assert np.asarray(outputs["residuals"]).shape == (X_dataset.shape[0], len(target_names))
    assert outputs["metadata"]["n_targets"] == len(target_names)
    assert outputs["metadata"]["target_names"] == target_names
    assert len(outputs["metadata"]["r2_per_target"]) == len(target_names)
    assert len(outputs["metadata"]["rmse_per_target"]) == len(target_names)


@pytest.mark.asyncio
async def test_linear_regression_node_rejects_incomplete_multitarget_without_selection():
    X_dataset, _y, _target_names = _make_incomplete_multitarget_dataset()
    node = node_registry.create_node(
        node_type="model.linear_regression",
        node_id="lr_incomplete_target_test",
        parameters={"fit_intercept": True},
    )

    with pytest.raises(ValueError, match="incomplete multi-target reference values"):
        await node.run(X=X_dataset)


@pytest.mark.asyncio
async def test_linear_regression_node_selected_target_drops_incomplete_rows():
    X_dataset, y, target_names = _make_incomplete_multitarget_dataset()
    selected = target_names[1]
    X_dataset.target_context = X_dataset.target_context.model_copy(update={"selected_target": selected})
    valid_rows = int(np.isfinite(y[:, 1]).sum())
    node = node_registry.create_node(
        node_type="model.linear_regression",
        node_id="lr_selected_target_test",
        parameters={"fit_intercept": True},
    )

    result = await node.run(X=X_dataset)
    outputs = result.outputs

    assert len(outputs["y_pred"]) == valid_rows
    assert len(outputs["residuals"]) == valid_rows
    assert outputs["metadata"]["n_samples"] == valid_rows
    assert outputs["metadata"]["target_names"] == [selected]


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
    assert outputs["default"] == outputs["labels"]


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
    assert outputs["default"] == outputs["labels"]
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
    assert outputs["default"] == outputs["labels"]


@pytest.mark.asyncio
async def test_pca_node_after_snv_accepts_analysis_dataset_units():
    rng = np.random.default_rng(21)
    data = rng.normal(size=(18, 40))
    dataset = SherpaDataset(
        X=data,
        feature_axis=SpectralAxis(
            values=np.linspace(950.0, 1650.0, 40),
            units="cm^-1",
            title="Wavenumber",
        ),
        sample_axis=SampleAxis(values=np.arange(18), title="Sample"),
        units="absorbance",
    )

    snv_node = node_registry.create_node(
        node_type="preprocess.normalize",
        node_id="snv_before_pca",
        parameters={"method": "snv"},
    )
    snv_result = await snv_node.run(default=dataset)
    snv_output = snv_result.outputs["default"]

    assert isinstance(snv_output, SherpaDataset)
    assert snv_output.units == "dimensionless"

    pca_node = node_registry.create_node(
        node_type="model.pca",
        node_id="pca_after_snv",
        parameters={"n_components": "3"},
    )
    pca_result = await pca_node.run(default=snv_output)
    outputs = pca_result.outputs

    assert "scores" in outputs
    assert isinstance(outputs["scores"], SherpaDataset)
    assert outputs["scores"].shape == (18, 3)
    assert outputs["scores"].quality.latest is not None
    assert outputs["scores"].quality.latest.model_type == "PCA"
