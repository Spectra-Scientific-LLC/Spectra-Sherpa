from __future__ import annotations

import numpy as np
import pytest

from spectra_sherpa.app.lib.sklearn_info import SKLEARN_CATALOG, load_sklearn_reference_as_sherpa
from spectra_sherpa.app.lib.synthetic_references import (
    SYNTHETIC_REFERENCE_CATALOG,
    load_synthetic_reference_as_sherpa,
)
from spectra_sherpa.app.services.dag.nodes.modeling.pca_nodes import PCANode
from spectra_sherpa.app.services.dag.nodes.output import PlotNode
from spectra_sherpa.app.services.dag.nodes.output._helpers import get_axis_display_info
from spectra_sherpa.app.services.dag.nodes.preprocessing.scale_node import ScaleNode

_CATALOG_CASES = [
    *(pytest.param("synthetic", name, id=f"synthetic-{name}") for name in SYNTHETIC_REFERENCE_CATALOG),
    *(pytest.param("sklearn", name, id=f"sklearn-{name}") for name in SKLEARN_CATALOG),
]


def _load_reference(source: str, name: str):
    if source == "synthetic":
        return load_synthetic_reference_as_sherpa(name)
    return load_sklearn_reference_as_sherpa(name)


@pytest.mark.anyio
@pytest.mark.parametrize(("source", "name"), _CATALOG_CASES)
async def test_every_local_catalog_reference_has_an_explicit_pca_outcome(source: str, name: str) -> None:
    dataset = _load_reference(source, name)
    assert dataset.X.ndim == 2
    assert dataset.n_samples >= 2
    assert dataset.n_features >= 3
    assert np.isfinite(dataset.X).all()
    assert dataset.sample_axis is not None
    assert len(dataset.sample_axis.labels or []) == dataset.n_samples

    method = "autoscale" if dataset.data_role == "X_features" else "mean_center"
    scaled_result = await ScaleNode("scale", {"method": method, "center": True}).execute(default=dataset)
    scaled = scaled_result.outputs["default"]
    assert scaled_result.diagnostics["method"] == method
    np.testing.assert_allclose(np.mean(scaled.X, axis=0), 0.0, atol=1e-9)
    if method == "autoscale":
        np.testing.assert_allclose(np.std(scaled.X, axis=0), 1.0, atol=1e-9)

    # An explicit scatter-reference cohort may have no between-sample variance.
    # Its correct PCA outcome is refusal, not fabricated explained variance.
    if not np.any(np.ptp(scaled.X, axis=0)):
        with pytest.raises(ValueError, match="fitted PCA outputs do not share one consistent finite shape"):
            await PCANode("pca", {"n_components": "1"}).execute(scaled)
        return

    pca = (await PCANode("pca", {"n_components": "3"}).execute(scaled)).outputs
    scores = pca["scores"]
    loadings = pca["loadings"]
    explained = np.asarray(pca["explained_variance"], dtype=np.float64)

    assert scores.shape == (dataset.n_samples, 3)
    assert scores.title == "PCA Scores"
    assert loadings.shape == (3, dataset.n_features)
    assert np.isfinite(scores.X).all()
    assert np.isfinite(loadings.X).all()
    assert np.isfinite(explained).all()
    assert np.all(explained >= 0.0)
    assert 0.0 < float(explained.sum()) <= 1.0 + 1e-12
    assert scores.sample_axis.labels == dataset.sample_axis.labels
    assert scores.feature_axis.labels and all(
        label.startswith(f"PC{index} (") and label.endswith("%)")
        for index, label in enumerate(scores.feature_axis.labels, start=1)
    )
    assert loadings.feature_axis is not None
    assert loadings.feature_axis.labels == dataset.feature_axis.labels

    scores_plot = (await PlotNode("scores", {"plot_type": "scores"}).execute(scores))["visualization"]
    loadings_plot = (await PlotNode("loadings", {"plot_type": "loadings"}).execute(loadings))["visualization"]
    scree_plot = (await PlotNode("variance", {"plot_type": "explained_variance"}).execute(explained))["visualization"]

    assert scores_plot["layout"]["xaxis"]["title"] == scores.feature_axis.labels[0]
    assert scores_plot["layout"]["yaxis"]["title"] == scores.feature_axis.labels[1]
    assert scores_plot["layout"]["title"] == "PCA Scores"
    assert sum(len(trace["x"]) for trace in scores_plot["data"]) == dataset.n_samples
    assert loadings_plot["layout"]["xaxis"]["title"]
    assert scree_plot["data"][0]["x"] == ["PC1", "PC2", "PC3"]
    assert scree_plot["layout"]["yaxis"]["title"] == "Explained Variance (%)"

    if dataset.target_context.target_type == "categorical":
        assert {trace["name"] for trace in scores_plot["data"]} == set(dataset.target_context.class_names or [])
    if source == "synthetic":
        assert get_axis_display_info(loadings.feature_axis)["should_reverse"] is True
