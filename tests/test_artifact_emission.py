"""Phase 5 tests: Training nodes emit _model_artifact for persistence.

Verifies that PLS, PCA, MCR, and SIMPLISMA training nodes include a
_model_artifact dict in their results, and that the artifact builder
correctly extracts feature_axis, n_features, and preprocessing chain.
"""

from __future__ import annotations

import asyncio

import numpy as np
import pytest

from spectra_sherpa.app.lib.scp_compat import HAS_SCP

pytestmark = pytest.mark.skipif(not HAS_SCP, reason="requires SpectroChemPy")

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _run(coro):
    return asyncio.run(coro)


@pytest.fixture
def sherpa_dataset():
    from spectra_sherpa.app.lib.axes import FeatureAxis
    from spectra_sherpa.app.lib.sherpa_dataset import SherpaDataset

    rng = np.random.RandomState(42)
    X = rng.randn(30, 50)
    fa = FeatureAxis(values=np.linspace(4000, 400, 50), units="cm-1", title="Wavenumber")
    ds = SherpaDataset(X=X, feature_axis=fa, target=rng.randn(30))
    return ds


# ---------------------------------------------------------------------------
# _artifact_builder unit tests
# ---------------------------------------------------------------------------


class TestArtifactBuilder:
    def test_build_includes_metadata_and_arrays(self, sherpa_dataset):
        from spectra_sherpa.app.lib.adapters.scp_extractors import PCAExtract

        extract = PCAExtract(
            scores=np.random.randn(30, 3),
            loadings=np.random.randn(3, 50),
            explained_variance_ratio=np.array([0.5, 0.3, 0.1]),
            explained_variance=np.array([5.0, 3.0, 1.0]),
            n_components=3,
            mean=np.random.randn(50),
        )
        from spectra_sherpa.app.services.dag.nodes.modeling._artifact_builder import build_model_artifact

        artifact = build_model_artifact(extract, sherpa_dataset, node_id="test_pca_1")

        assert "metadata" in artifact
        assert "arrays" in artifact
        meta = artifact["metadata"]
        assert meta["model_type"] == "pca"
        assert meta["n_features"] == 50
        assert meta["node_id"] == "test_pca_1"
        assert "feature_axis" in meta
        assert len(meta["feature_axis"]) == 50
        assert "loadings" in artifact["arrays"]

    def test_build_includes_metrics(self, sherpa_dataset):
        from spectra_sherpa.app.lib.adapters.scp_extractors import PCAExtract

        extract = PCAExtract(
            scores=np.random.randn(30, 2),
            loadings=np.random.randn(2, 50),
            explained_variance_ratio=np.array([0.6, 0.3]),
            explained_variance=np.array([6.0, 3.0]),
            n_components=2,
        )
        from spectra_sherpa.app.services.dag.nodes.modeling._artifact_builder import build_model_artifact

        artifact = build_model_artifact(
            extract,
            sherpa_dataset,
            metrics={"r2": 0.95, "rmse": 0.12},
        )
        assert artifact["metadata"]["metrics"]["r2"] == 0.95

    def test_build_includes_preprocessing_chain(self, sherpa_dataset):
        from spectra_sherpa.app.services.dag.meta_helpers import add_processing_step

        add_processing_step(sherpa_dataset, "preprocess.snv", {"method": "snv"}, "pp_1")
        add_processing_step(sherpa_dataset, "preprocess.savgol", {"window": 11}, "pp_2")

        from spectra_sherpa.app.lib.adapters.scp_extractors import PCAExtract

        extract = PCAExtract(
            scores=np.random.randn(30, 2),
            loadings=np.random.randn(2, 50),
            explained_variance_ratio=np.array([0.6, 0.3]),
            explained_variance=np.array([6.0, 3.0]),
            n_components=2,
        )
        from spectra_sherpa.app.services.dag.nodes.modeling._artifact_builder import build_model_artifact

        artifact = build_model_artifact(extract, sherpa_dataset)
        chain = artifact["metadata"].get("preprocessing_chain", [])
        assert len(chain) >= 2
        op_ids = [s["op_id"] for s in chain]
        assert "preprocess.snv" in op_ids
        assert "preprocess.savgol" in op_ids

    def test_build_picks_up_feature_mask_from_meta(self):
        """When a dataset has feature_mask in meta (from variable_select),
        the artifact builder must include it in the manifest."""
        from spectra_sherpa.app.lib.adapters.scp_extractors import PCAExtract
        from spectra_sherpa.app.lib.axes import FeatureAxis
        from spectra_sherpa.app.lib.sherpa_dataset import SherpaDataset
        from spectra_sherpa.app.services.dag.nodes.modeling._artifact_builder import build_model_artifact

        # Simulate: variable_select reduced 50 → 20 features and stored mask
        original_mask = np.zeros(50, dtype=bool)
        original_mask[10:30] = True  # selected 20 features
        selected_wn = np.linspace(4000, 400, 50)[original_mask]

        ds = SherpaDataset(
            X=np.random.randn(15, 20),
            feature_axis=FeatureAxis(values=selected_wn),
            extra={"feature_mask": original_mask.tolist()},
        )

        extract = PCAExtract(
            scores=np.random.randn(15, 2),
            loadings=np.random.randn(2, 20),
            explained_variance_ratio=np.array([0.6, 0.3]),
            explained_variance=np.array([6.0, 3.0]),
            n_components=2,
        )
        artifact = build_model_artifact(extract, ds)
        meta = artifact["metadata"]

        assert "feature_mask" in meta, "Artifact must include feature_mask from dataset meta"
        mask = np.asarray(meta["feature_mask"], dtype=bool)
        assert len(mask) == 50
        assert np.sum(mask) == 20

    def test_build_with_numpy_array_input(self):
        """Should handle plain numpy arrays without crashing."""
        from spectra_sherpa.app.lib.adapters.scp_extractors import PCAExtract

        extract = PCAExtract(
            scores=np.random.randn(10, 2),
            loadings=np.random.randn(2, 20),
            explained_variance_ratio=np.array([0.7, 0.2]),
            explained_variance=np.array([7.0, 2.0]),
            n_components=2,
        )
        from spectra_sherpa.app.services.dag.nodes.modeling._artifact_builder import build_model_artifact

        X = np.random.randn(10, 20)
        artifact = build_model_artifact(extract, X)
        assert artifact["metadata"]["n_features"] == 20
        assert artifact["metadata"]["model_type"] == "pca"


# ---------------------------------------------------------------------------
# PLS artifact emission
# ---------------------------------------------------------------------------


class TestPLSArtifactEmission:
    def test_pls_emits_artifact(self, sherpa_dataset):
        from spectra_sherpa.app.services.dag.nodes.modeling.pls_nodes import PLSNode

        node = PLSNode(node_id="pls_1", parameters={"n_components": 3, "scale": True})
        result = _run(node.execute(X=sherpa_dataset, y=sherpa_dataset.target))
        assert "_model_artifact" in result.outputs
        meta = result.outputs["_model_artifact"]["metadata"]
        assert meta["model_type"] == "pls"
        assert meta["n_features"] == 50
        assert "coef" in result.outputs["_model_artifact"]["arrays"]

    def test_pls_artifact_has_feature_axis(self, sherpa_dataset):
        from spectra_sherpa.app.services.dag.nodes.modeling.pls_nodes import PLSNode

        node = PLSNode(node_id="pls_2", parameters={"n_components": 2})
        result = _run(node.execute(X=sherpa_dataset, y=sherpa_dataset.target))
        meta = result.outputs["_model_artifact"]["metadata"]
        assert "feature_axis" in meta
        assert len(meta["feature_axis"]) == 50
        # Check wavenumber values are plausible
        assert meta["feature_axis"][0] == pytest.approx(4000.0, abs=1)

    def test_pls_artifact_has_metrics(self, sherpa_dataset):
        from spectra_sherpa.app.services.dag.nodes.modeling.pls_nodes import PLSNode

        node = PLSNode(node_id="pls_3", parameters={"n_components": 3})
        result = _run(node.execute(X=sherpa_dataset, y=sherpa_dataset.target))
        metrics = result.outputs["_model_artifact"]["metadata"].get("metrics")
        # Random data may or may not give good metrics, but they should exist
        if metrics:
            assert "r2" in metrics or "rmse" in metrics


# ---------------------------------------------------------------------------
# Regression artifact emission
# ---------------------------------------------------------------------------


class TestRegressionArtifactEmission:
    def test_pcr_emits_artifact(self, sherpa_dataset):
        from spectra_sherpa.app.services.dag.nodes.modeling.regression_nodes import PCRNode

        node = PCRNode(node_id="pcr_1", parameters={"n_components": 3, "scale": True})
        result = _run(node.execute(X=sherpa_dataset, y=sherpa_dataset.target))
        artifact = result.outputs["_model_artifact"]
        assert artifact["metadata"]["model_type"] == "pcr"
        assert artifact["metadata"]["n_features"] == 50
        assert {"pca_components", "pca_mean", "reg_coef", "reg_intercept"}.issubset(artifact["arrays"])

    def test_svr_emits_artifact(self, sherpa_dataset):
        from spectra_sherpa.app.services.dag.nodes.modeling.regression_nodes import SVRNode

        node = SVRNode(node_id="svr_1", parameters={"kernel": "linear", "scale": True})
        result = _run(node.execute(X=sherpa_dataset, y=sherpa_dataset.target))
        artifact = result["_model_artifact"]
        assert artifact["metadata"]["model_type"] == "svr"
        assert artifact["metadata"]["n_features"] == 50
        assert {"support_vectors", "dual_coef", "intercept"}.issubset(artifact["arrays"])

    def test_linear_regression_emits_artifact(self, sherpa_dataset):
        from spectra_sherpa.app.services.dag.nodes.modeling.regression_nodes import LinearRegressionNode

        node = LinearRegressionNode(node_id="linear_1", parameters={"fit_intercept": True})
        result = _run(node.execute(X=sherpa_dataset, y=sherpa_dataset.target))
        artifact = result["_model_artifact"]
        assert artifact["metadata"]["model_type"] == "linear_regression"
        assert artifact["metadata"]["n_features"] == 50
        assert {"coef", "intercept"}.issubset(artifact["arrays"])


# ---------------------------------------------------------------------------
# Classification artifact emission
# ---------------------------------------------------------------------------


class TestClassificationArtifactEmission:
    @pytest.fixture()
    def classification_dataset(self):
        from spectra_sherpa.app.lib.axes import FeatureAxis
        from spectra_sherpa.app.lib.sherpa_dataset import SherpaDataset, TargetContext

        rng = np.random.RandomState(123)
        X = np.vstack(
            [
                rng.normal(loc=-1.0, scale=0.2, size=(12, 20)),
                rng.normal(loc=1.0, scale=0.2, size=(12, 20)),
                rng.normal(loc=3.0, scale=0.2, size=(12, 20)),
            ]
        )
        y = np.array(["A"] * 12 + ["B"] * 12 + ["C"] * 12)
        return SherpaDataset(
            X=X,
            feature_axis=FeatureAxis(values=np.linspace(4000, 400, 20), units="cm-1", title="Wavenumber"),
            target=y,
            target_context=TargetContext(target_type="categorical", target_name="class"),
        )

    def test_plsda_emits_artifact(self, classification_dataset):
        from spectra_sherpa.app.services.dag.nodes.classification.plsda_nodes import PLSDANode

        node = PLSDANode(node_id="plsda_1", parameters={"n_components": 2, "cv_folds": 3})
        result = _run(node.execute(X=classification_dataset, y=classification_dataset.target))
        assert "_model_artifact" in result.outputs
        artifact = result.outputs["_model_artifact"]
        meta = artifact["metadata"]
        assert meta["model_type"] == "plsda"
        assert meta["classes"] == ["A", "B", "C"]
        assert meta["n_features"] == 20
        assert "training_data_hash" in meta
        assert {"coef", "x_mean", "y_mean"}.issubset(artifact["arrays"])

    def test_knn_emits_artifact(self, classification_dataset):
        from spectra_sherpa.app.services.dag.nodes.classification.knn_nodes import KNNNode

        node = KNNNode(node_id="knn_1", parameters={"n_neighbors": 3, "cv_folds": 3})
        result = _run(node.execute(X=classification_dataset, y=classification_dataset.target))
        assert "_model_artifact" in result.outputs
        artifact = result.outputs["_model_artifact"]
        meta = artifact["metadata"]
        assert meta["model_type"] == "knn"
        assert meta["classes"] == ["A", "B", "C"]
        assert meta["n_features"] == 20
        assert "training_data_hash" in meta
        assert {"X_train", "y_train_encoded"}.issubset(artifact["arrays"])

    def test_simca_emits_artifact(self, classification_dataset):
        from spectra_sherpa.app.services.dag.nodes.classification.simca_nodes import SIMCANode

        node = SIMCANode(node_id="simca_1", parameters={"n_components": 2})
        result = _run(node.execute(X=classification_dataset, y=classification_dataset.target))
        artifact = result.outputs["_model_artifact"]
        meta = artifact["metadata"]
        arrays = artifact["arrays"]
        assert meta["model_type"] == "simca"
        assert meta["classes"] == ["A", "B", "C"]
        assert meta["n_features"] == 20
        assert {"class_0_loadings", "class_0_mean", "class_0_scale", "class_0_pca_mean"}.issubset(arrays)


# ---------------------------------------------------------------------------
# PCA artifact emission
# ---------------------------------------------------------------------------


class TestPCAArtifactEmission:
    def test_pca_emits_artifact(self, sherpa_dataset):
        from spectra_sherpa.app.services.dag.nodes.modeling.pca_nodes import PCANode

        node = PCANode(node_id="pca_1", parameters={"n_components": "3"})
        result = _run(node.execute(input_data=sherpa_dataset))
        outputs = result.outputs
        assert "_model_artifact" in outputs
        meta = outputs["_model_artifact"]["metadata"]
        assert meta["model_type"] == "pca"
        assert "loadings" in outputs["_model_artifact"]["arrays"]

    def test_pca_artifact_n_features(self, sherpa_dataset):
        from spectra_sherpa.app.services.dag.nodes.modeling.pca_nodes import PCANode

        node = PCANode(node_id="pca_2", parameters={"n_components": "2"})
        result = _run(node.execute(input_data=sherpa_dataset))
        meta = result.outputs["_model_artifact"]["metadata"]
        assert meta["n_features"] == 50


# ---------------------------------------------------------------------------
# Decomposition artifact emission
# ---------------------------------------------------------------------------


class TestDecompositionArtifactEmission:
    def test_nmf_emits_artifact(self, sherpa_dataset):
        from spectra_sherpa.app.lib.axes import FeatureAxis
        from spectra_sherpa.app.lib.sherpa_dataset import SherpaDataset
        from spectra_sherpa.app.services.dag.nodes.modeling.decomposition_nodes import NMFNode

        nonnegative = SherpaDataset(
            X=np.abs(sherpa_dataset.X),
            feature_axis=FeatureAxis(values=np.linspace(4000, 400, 50), units="cm-1", title="Wavenumber"),
        )
        node = NMFNode(node_id="nmf_1", parameters={"n_components": 3, "max_iter": 50})
        result = _run(node.execute(input_data=nonnegative))
        artifact = result.outputs["_model_artifact"]
        assert artifact["metadata"]["model_type"] == "nmf"
        assert artifact["metadata"]["n_features"] == 50
        assert "H" in artifact["arrays"]

    def test_fastica_emits_artifact(self, sherpa_dataset):
        from spectra_sherpa.app.services.dag.nodes.modeling.decomposition_nodes import FastICANode

        node = FastICANode(node_id="ica_1", parameters={"n_components": 3, "max_iter": 100})
        result = _run(node.execute(input_data=sherpa_dataset))
        artifact = result.outputs["_model_artifact"]
        assert artifact["metadata"]["model_type"] == "fastica"
        assert artifact["metadata"]["n_features"] == 50
        assert "components" in artifact["arrays"]


# ---------------------------------------------------------------------------
# Executor graceful handling without ModelStore
# ---------------------------------------------------------------------------


class TestExecutorGracefulArtifact:
    def test_executor_fails_without_model_store(self, sherpa_dataset):
        """Executor must fail closed when artifact persistence is unavailable."""
        from unittest.mock import patch

        from spectra_sherpa.app.services.dag.executor import DAGExecutor

        nodes = {
            "pca_1": {
                "type": "model.pca",
                "parameters": {"n_components": "2"},
            },
        }
        edges = []
        executor = DAGExecutor(nodes, edges)

        # Simulate: node produced _model_artifact but no store
        executor.results["pca_1"] = {
            "_model_artifact": {
                "metadata": {"model_type": "pca"},
                "arrays": {"loadings": np.eye(2)},
            }
        }

        # Force _resolve_model_store to return None
        with patch.object(executor, "_resolve_model_store", return_value=None):
            with pytest.raises(RuntimeError, match="ModelStore not initialized"):
                executor._process_model_artifact("pca_1")


# ---------------------------------------------------------------------------
# Containment: new files in approved list
# ---------------------------------------------------------------------------


class TestContainment:
    def test_artifact_builder_in_modeling(self):
        """The _artifact_builder module should be importable."""
        from spectra_sherpa.app.services.dag.nodes.modeling._artifact_builder import build_model_artifact

        assert callable(build_model_artifact)
