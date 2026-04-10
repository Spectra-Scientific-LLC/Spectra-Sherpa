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
    X = np.vstack([
        rng.normal(0, 0.5, (n_per_class, n_features)),
        rng.normal(3, 0.5, (n_per_class, n_features)),
        rng.normal(-3, 0.5, (n_per_class, n_features)),
    ])
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


# ---------------------------------------------------------------------------
# Pending migration — documents nodes that still return plain dicts.
# When you migrate a node, move its entry into the "fixed" section above and
# delete from PENDING. The test below will catch accidental re-regressions.
# ---------------------------------------------------------------------------


PENDING_NODE_RESULT: set[str] = {
    # Clustering (Phase 2)
    "model.hca",
    "model.dbscan",
    # Decomposition (Phase 2)
    "model.mcr_als",
    "model.simplisma",
    "model.nmf",
    "model.ica",
    "model.efa",
    # Prediction/apply (Phase 2)
    "classification.predict",
    "model.pls_predict",
    # Peak finding (Phase 2 — declared summarizer now matches but node still plain dict)
    "analysis.peak_finding",
    # Preprocessing nodes with SNR / baseline / smoothing diagnostics on .meta
    "preprocess.baseline_pls",
    "preprocess.smooth",
    "preprocess.normalize",
}


def test_pending_list_is_visible():
    """Sanity check: the pending list should not be empty until Phase 2 is done.
    Once all nodes are migrated, delete this test along with PENDING_NODE_RESULT.
    """
    assert PENDING_NODE_RESULT, (
        "All pending NodeResult migrations are complete — remove PENDING_NODE_RESULT "
        "and this test, and fold the migrated nodes into the assertion suite above."
    )
