"""Node contract tests: ensure diagnostic-producing nodes return NodeResult.

Background: many nodes historically returned plain dicts from ``execute()``,
which caused the DAG executor to store an empty ``diagnostics`` dict for
them (see executor.py lines 958-964). The Sherpa advisor's context builder
reads from that diagnostics channel, so plain-dict returns silently hid
scientific metrics from the LLM.

This test locks in the contract for nodes that have been converted to
``NodeResult`` so future regressions fail loudly, and tracks the remaining
nodes via an explicit ``PENDING_NODE_RESULT`` list so progress is visible.

When a node is migrated to NodeResult, move its entry from PENDING to
REQUIRED_NODE_RESULT.
"""

from __future__ import annotations

import numpy as np
import pytest

from spectra_sherpa.app.services.dag.node_base import NodeResult, node_registry

# ---------------------------------------------------------------------------
# Nodes that MUST return NodeResult with non-empty diagnostics today.
# Each tuple: (node_type, constructor_params, execute_kwargs_builder, expected_diagnostic_keys)
# ---------------------------------------------------------------------------


def _make_classification_data(n_samples: int = 60, n_features: int = 10):
    """Build a small, well-separated 3-class classification dataset."""
    rng = np.random.default_rng(42)
    n_per_class = n_samples // 3
    X = np.vstack(
        [
            rng.normal(0, 0.5, (n_per_class, n_features)),
            rng.normal(3, 0.5, (n_per_class, n_features)),
            rng.normal(-3, 0.5, (n_per_class, n_features)),
        ]
    )
    y = np.array(
        ["a"] * n_per_class + ["b"] * n_per_class + ["c"] * n_per_class,
        dtype=object,
    )
    return X, y


def _make_regression_data(n_samples: int = 40, n_features: int = 8):
    rng = np.random.default_rng(42)
    X = rng.normal(0, 1, (n_samples, n_features))
    coefs = rng.normal(0, 1, n_features)
    y = X @ coefs + rng.normal(0, 0.05, n_samples)
    return X, y


# ---------------------------------------------------------------------------
# Shared helper: run node.execute and assert NodeResult contract
# ---------------------------------------------------------------------------


async def _assert_node_result(
    node_type: str,
    parameters: dict,
    kwargs: dict,
    required_diagnostic_keys: set[str],
) -> None:
    node = node_registry.create_node(
        node_type=node_type,
        node_id=f"test_{node_type.replace('.', '_')}",
        parameters=parameters,
    )
    result = await node.execute(**kwargs)

    assert isinstance(result, NodeResult), (
        f"{node_type}.execute() must return NodeResult so its diagnostics reach "
        f"the Sherpa advisor. Got {type(result).__name__}. "
        f"See src/spectra_sherpa/app/services/dag/nodes/* for the pattern."
    )
    assert result.diagnostics, (
        f"{node_type} returned NodeResult but with empty diagnostics. "
        f"The Sherpa context builder will skip it. Populate diagnostics with "
        f"scientifically meaningful scalars."
    )
    missing = required_diagnostic_keys - set(result.diagnostics.keys())
    assert not missing, (
        f"{node_type} diagnostics is missing required keys: {missing}. "
        f"Emitted keys: {sorted(result.diagnostics.keys())}"
    )


# ---------------------------------------------------------------------------
# Fixed nodes — these must continue to emit NodeResult with diagnostics
# ---------------------------------------------------------------------------


class TestClassificationNodesEmitDiagnostics:
    @pytest.mark.asyncio
    async def test_plsda_emits_diagnostics(self):
        from spectra_sherpa.app.lib.sherpa_dataset import SherpaDataset

        X, y = _make_classification_data()
        await _assert_node_result(
            node_type="classification.plsda",
            parameters={"n_components": 2, "cv_folds": 3},
            kwargs={"X": SherpaDataset(X=X), "y": y},
            required_diagnostic_keys={
                "accuracy",
                "f1_score",
                "n_components",
                "n_classes",
            },
        )

    @pytest.mark.asyncio
    async def test_knn_emits_diagnostics(self):
        from spectra_sherpa.app.lib.sherpa_dataset import SherpaDataset

        X, y = _make_classification_data()
        await _assert_node_result(
            node_type="classification.knn",
            parameters={"n_neighbors": 3, "cv_folds": 3},
            kwargs={"X": SherpaDataset(X=X), "y": y},
            required_diagnostic_keys={"cv_accuracy", "n_classes"},
        )

    @pytest.mark.asyncio
    async def test_simca_emits_diagnostics(self):
        from spectra_sherpa.app.lib.sherpa_dataset import SherpaDataset

        X, y = _make_classification_data()
        await _assert_node_result(
            node_type="classification.simca",
            parameters={"n_components": 2},
            kwargs={"X": SherpaDataset(X=X), "y": y},
            required_diagnostic_keys={"accuracy", "n_classes"},
        )


class TestRegressionNodesEmitDiagnostics:
    @pytest.mark.asyncio
    async def test_pls_emits_diagnostics(self):
        from spectra_sherpa.app.lib.sherpa_dataset import SherpaDataset

        X, y = _make_regression_data()
        await _assert_node_result(
            node_type="model.pls",
            parameters={"n_components": 3},
            kwargs={"X": SherpaDataset(X=X), "y": y},
            required_diagnostic_keys={"r2", "rmse", "n_components"},
        )

    @pytest.mark.asyncio
    async def test_pcr_emits_diagnostics(self):
        from spectra_sherpa.app.lib.sherpa_dataset import SherpaDataset

        X, y = _make_regression_data()
        await _assert_node_result(
            node_type="model.pcr",
            parameters={"n_components": 3},
            kwargs={"X": SherpaDataset(X=X), "y": y},
            required_diagnostic_keys={"r2", "rmse"},
        )


class TestDiagnosticsNodesEmitDiagnostics:
    @pytest.mark.asyncio
    async def test_cross_validation_regression_emits_diagnostics(self):
        node = node_registry.create_node(
            node_type="diagnostics.cross_validation",
            node_id="cv_regression",
            parameters={"cv_folds": 5, "cv_method": "k_fold", "task_type": "regression"},
        )
        y_true = np.linspace(0, 10, 30)
        y_pred = y_true + np.random.default_rng(0).normal(0, 0.3, 30)
        result = await node.execute(y_true=y_true, y_pred=y_pred)

        assert isinstance(result, NodeResult)
        assert result.diagnostics
        # Regression CV metrics
        for key in ("rmsecv", "q2"):
            assert key.lower() in {k.lower() for k in result.diagnostics.keys()}, (
                f"CrossValidationNode (regression) missing {key!r} in diagnostics: "
                f"{list(result.diagnostics.keys())}"
            )

    @pytest.mark.asyncio
    async def test_holdout_evaluation_classification_emits_diagnostics(self):
        node = node_registry.create_node(
            node_type="diagnostics.holdout_evaluation",
            node_id="holdout_cls",
            parameters={"task_type": "classification"},
        )
        y_true = np.array(["a", "a", "b", "b", "c", "c"])
        y_pred = np.array(["a", "b", "b", "b", "c", "c"])
        result = await node.execute(y_true=y_true, y_pred=y_pred)

        assert isinstance(result, NodeResult)
        assert result.diagnostics
        assert "accuracy" in result.diagnostics
        assert "confusion_matrix" in result.diagnostics
        assert "per_class" in result.diagnostics

    @pytest.mark.asyncio
    async def test_holdout_evaluation_regression_emits_diagnostics(self):
        node = node_registry.create_node(
            node_type="diagnostics.holdout_evaluation",
            node_id="holdout_reg",
            parameters={"task_type": "regression"},
        )
        y_true = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
        y_pred = np.array([1.1, 1.9, 3.2, 3.8, 5.1])
        result = await node.execute(y_true=y_true, y_pred=y_pred)

        assert isinstance(result, NodeResult)
        assert result.diagnostics
        for key in ("RMSEP", "R2"):
            assert key in result.diagnostics


class TestClusteringNodesEmitDiagnostics:
    @pytest.mark.asyncio
    async def test_kmeans_emits_diagnostics(self):
        from spectra_sherpa.app.lib.sherpa_dataset import SherpaDataset

        X, _ = _make_classification_data()
        await _assert_node_result(
            node_type="model.kmeans",
            parameters={"n_clusters": 3},
            kwargs={"input_data": SherpaDataset(X=X)},
            required_diagnostic_keys={"n_clusters"},
        )

    @pytest.mark.asyncio
    async def test_hca_emits_diagnostics(self):
        from spectra_sherpa.app.lib.sherpa_dataset import SherpaDataset

        X, _ = _make_classification_data()
        await _assert_node_result(
            node_type="model.hca",
            parameters={"n_clusters": 3, "linkage": "ward", "metric": "euclidean"},
            kwargs={"input_data": SherpaDataset(X=X)},
            required_diagnostic_keys={"n_clusters", "linkage", "metric", "n_samples"},
        )

    @pytest.mark.asyncio
    async def test_dbscan_emits_diagnostics(self):
        from spectra_sherpa.app.lib.sherpa_dataset import SherpaDataset

        X, _ = _make_classification_data()
        await _assert_node_result(
            node_type="model.dbscan",
            parameters={"eps": 2.0, "min_samples": 3, "metric": "euclidean"},
            kwargs={"input_data": SherpaDataset(X=X)},
            required_diagnostic_keys={
                "n_clusters",
                "eps",
                "min_samples",
                "noise_fraction",
                "metric",
            },
        )


class TestDecompositionNodesEmitDiagnostics:
    @pytest.mark.asyncio
    async def test_mcr_emits_diagnostics(self):
        from spectra_sherpa.app.lib.sherpa_dataset import SherpaDataset

        rng = np.random.default_rng(0)
        X = np.abs(rng.normal(0, 1, (20, 50))) + 0.1
        await _assert_node_result(
            node_type="model.mcr_als",
            parameters={"n_components": 2},
            kwargs={"input_data": SherpaDataset(X=X)},
            required_diagnostic_keys={"n_components"},
        )

    @pytest.mark.asyncio
    async def test_simplisma_emits_diagnostics(self):
        from spectra_sherpa.app.lib.sherpa_dataset import SherpaDataset

        rng = np.random.default_rng(1)
        X = np.abs(rng.normal(0, 1, (20, 50))) + 0.1
        await _assert_node_result(
            node_type="model.simplisma",
            parameters={"n_components": 2},
            kwargs={"input_data": SherpaDataset(X=X)},
            required_diagnostic_keys={"n_components", "noise"},
        )

    @pytest.mark.asyncio
    async def test_nmf_emits_diagnostics(self):
        from spectra_sherpa.app.lib.sherpa_dataset import SherpaDataset

        rng = np.random.default_rng(2)
        X = np.abs(rng.normal(0, 1, (20, 30))) + 0.1
        await _assert_node_result(
            node_type="model.nmf",
            parameters={"n_components": 3},
            kwargs={"input_data": SherpaDataset(X=X)},
            required_diagnostic_keys={"n_components", "reconstruction_error"},
        )

    @pytest.mark.asyncio
    async def test_ica_emits_diagnostics(self):
        from spectra_sherpa.app.lib.sherpa_dataset import SherpaDataset

        rng = np.random.default_rng(3)
        X = rng.normal(0, 1, (40, 20))
        await _assert_node_result(
            node_type="model.ica",
            parameters={"n_components": 3},
            kwargs={"input_data": SherpaDataset(X=X)},
            required_diagnostic_keys={"n_components"},
        )

    @pytest.mark.asyncio
    async def test_efa_emits_diagnostics(self):
        from spectra_sherpa.app.lib.sherpa_dataset import SherpaDataset

        rng = np.random.default_rng(4)
        X = np.abs(rng.normal(0, 1, (20, 30))) + 0.1
        await _assert_node_result(
            node_type="model.efa",
            parameters={"n_components": 10},
            kwargs={"input_data": SherpaDataset(X=X)},
            required_diagnostic_keys={"n_components"},
        )


class TestPredictionNodesEmitDiagnostics:
    @pytest.mark.asyncio
    async def test_classifier_predict_plsda_emits_diagnostics(self):
        from spectra_sherpa.app.lib.sherpa_dataset import SherpaDataset

        X, y = _make_classification_data()
        train_node = node_registry.create_node(
            node_type="classification.plsda",
            node_id="plsda_train",
            parameters={"n_components": 2, "cv_folds": 3},
        )
        train_result = await train_node.execute(X=SherpaDataset(X=X), y=y)
        model = train_result.outputs["model"]

        await _assert_node_result(
            node_type="classification.predict",
            parameters={},
            kwargs={"X_new": SherpaDataset(X=X), "model": model},
            required_diagnostic_keys={"method", "n_predicted", "n_classes"},
        )

    @pytest.mark.asyncio
    async def test_classifier_predict_knn_emits_diagnostics(self):
        from spectra_sherpa.app.lib.sherpa_dataset import SherpaDataset

        X, y = _make_classification_data()
        train_node = node_registry.create_node(
            node_type="classification.knn",
            node_id="knn_train",
            parameters={"n_neighbors": 3, "cv_folds": 3},
        )
        train_result = await train_node.execute(X=SherpaDataset(X=X), y=y)
        model = train_result.outputs["model"]

        await _assert_node_result(
            node_type="classification.predict",
            parameters={},
            kwargs={"X_new": SherpaDataset(X=X), "model": model},
            required_diagnostic_keys={"method", "n_predicted", "n_classes", "mean_max_prob"},
        )

    @pytest.mark.asyncio
    async def test_classifier_predict_simca_emits_diagnostics(self):
        from spectra_sherpa.app.lib.sherpa_dataset import SherpaDataset

        X, y = _make_classification_data()
        train_node = node_registry.create_node(
            node_type="classification.simca",
            node_id="simca_train",
            parameters={"n_components": 2},
        )
        train_result = await train_node.execute(X=SherpaDataset(X=X), y=y)
        model = train_result.outputs["model"]

        await _assert_node_result(
            node_type="classification.predict",
            parameters={},
            kwargs={"X_new": SherpaDataset(X=X), "model": model},
            required_diagnostic_keys={"method", "n_predicted", "n_classes", "mean_min_distance"},
        )

    @pytest.mark.asyncio
    async def test_peak_finding_emits_diagnostics(self):
        from spectra_sherpa.app.lib.sherpa_dataset import SherpaDataset

        rng = np.random.default_rng(5)
        # Build synthetic spectra with clear gaussian peaks
        x = np.linspace(0, 100, 200)
        n_samples = 5
        spectra = np.zeros((n_samples, len(x)))
        for i in range(n_samples):
            for center in (25.0, 55.0, 80.0):
                spectra[i] += np.exp(-((x - center) ** 2) / 10.0)
            spectra[i] += rng.normal(0, 0.01, len(x))
        await _assert_node_result(
            node_type="analysis.peak_finding",
            parameters={"distance": 5},
            kwargs={"input_data": SherpaDataset(X=spectra)},
            required_diagnostic_keys={
                "n_consensus_peaks",
                "n_peaks",
                "method",
                "n_features",
                "detection_rate_min",
                "detection_rate_max",
            },
        )

    @pytest.mark.asyncio
    async def test_pls_predict_emits_diagnostics(self):
        from spectra_sherpa.app.lib.sherpa_dataset import SherpaDataset

        X, y = _make_regression_data()
        train_node = node_registry.create_node(
            node_type="model.pls",
            node_id="pls_train",
            parameters={"n_components": 3},
        )
        train_result = await train_node.execute(X=SherpaDataset(X=X), y=y)
        model = train_result.outputs["model"]

        await _assert_node_result(
            node_type="model.pls_predict",
            parameters={},
            kwargs={"X_new": SherpaDataset(X=X), "model": model, "y_true": y},
            required_diagnostic_keys={"n_predicted", "rmsep", "r2"},
        )


# ---------------------------------------------------------------------------
# Pending migration — documents nodes that still return plain dicts.
# When you migrate a node, move its entry into the "fixed" section above and
# delete from PENDING. The test below will catch accidental re-regressions.
# ---------------------------------------------------------------------------


class TestPreprocessingNodesEmitDiagnostics:
    @pytest.mark.asyncio
    async def test_baseline_penalized_ls_emits_diagnostics(self):
        from spectra_sherpa.app.lib.sherpa_dataset import SherpaDataset

        rng = np.random.default_rng(6)
        x = np.linspace(0, 100, 200)
        baseline = 0.02 * x + 0.5
        spectra = np.zeros((5, 200))
        for i in range(5):
            peak = np.exp(-((x - 50) ** 2) / 10.0)
            spectra[i] = baseline + peak + rng.normal(0, 0.01, 200)
        await _assert_node_result(
            node_type="baseline.penalized_ls",
            parameters={"method": "als", "lam": 1e5},
            kwargs={"input_data": SherpaDataset(X=spectra)},
            required_diagnostic_keys={
                "baseline_mean",
                "baseline_std",
                "baseline_max",
                "residual_rms",
                "correction_magnitude_pct",
            },
        )

    @pytest.mark.asyncio
    async def test_smooth_emits_diagnostics(self):
        from spectra_sherpa.app.lib.sherpa_dataset import SherpaDataset

        rng = np.random.default_rng(7)
        X = rng.normal(0, 1, (5, 100))
        await _assert_node_result(
            node_type="preprocess.smooth",
            parameters={"method": "savitzky_golay", "size": 11, "order": 2},
            kwargs={"input_data": SherpaDataset(X=X)},
            required_diagnostic_keys={"snr_before", "snr_after", "snr_improvement_db"},
        )

    @pytest.mark.asyncio
    async def test_normalize_snv_emits_diagnostics(self):
        from spectra_sherpa.app.lib.sherpa_dataset import SherpaDataset

        rng = np.random.default_rng(8)
        X = rng.normal(0, 1, (5, 100))
        await _assert_node_result(
            node_type="preprocess.normalize",
            parameters={"method": "snv"},
            kwargs={"input_data": SherpaDataset(X=X)},
            required_diagnostic_keys={"method", "snr_before", "snr_after"},
        )

    @pytest.mark.asyncio
    async def test_normalize_scale_emits_diagnostics(self):
        from spectra_sherpa.app.lib.sherpa_dataset import SherpaDataset

        rng = np.random.default_rng(9)
        X = np.abs(rng.normal(0, 1, (5, 100))) + 0.1
        await _assert_node_result(
            node_type="preprocess.normalize",
            parameters={"method": "max"},
            kwargs={"input_data": SherpaDataset(X=X)},
            required_diagnostic_keys={"method"},
        )


PENDING_NODE_RESULT: set[str] = set()
