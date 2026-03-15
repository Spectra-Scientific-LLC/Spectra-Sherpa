"""Phase 2 selection node tests.

Covers:
- iPLS (interval PLS) variable selection
- CARS (Competitive Adaptive Reweighted Sampling)
- SPA (Successive Projections Algorithm)
- UVE (MC Uninformative Variable Elimination)
- Stability Selection meta-node
- SPXY sample partitioning
"""

from __future__ import annotations

import numpy as np
import pytest

from spectra_sherpa.app.lib.sherpa_dataset import SampleAxis, SherpaDataset, SpectralAxis

# ── Shared Fixtures ───────────────────────────────────────────────────


@pytest.fixture
def spectral_dataset():
    """Synthetic spectral dataset with y correlated to a few features."""
    rng = np.random.RandomState(42)
    n_samples, n_features = 60, 50
    X = rng.randn(n_samples, n_features)
    # y depends on features 10-15 (signal region)
    y = X[:, 10:16].sum(axis=1) + rng.randn(n_samples) * 0.1
    ds = SherpaDataset(
        X=X,
        feature_axis=SpectralAxis(values=np.linspace(400, 4000, n_features), units="cm-1"),
        sample_axis=SampleAxis(labels=[f"s{i}" for i in range(n_samples)]),
        target=y,
    )
    return ds, y


# ── iPLS Tests ────────────────────────────────────────────────────────


class TestIPLSNode:
    """Interval PLS variable selection."""

    @pytest.mark.asyncio
    async def test_basic_ipls(self, spectral_dataset):
        from spectra_sherpa.app.services.dag.nodes.selection.ipls_node import IPLSNode

        ds, y = spectral_dataset
        node = IPLSNode(
            "test_ipls",
            {
                "n_intervals": 10,
                "n_components": 3,
                "cv_folds": 3,
                "n_best": 1,
            },
        )
        result = await node.execute(X=ds, y=y)

        assert "X_selected" in result.outputs
        assert "mask" in result.outputs
        mask = result.outputs["mask"]
        assert mask.dtype == bool
        assert mask.shape[0] == 50
        assert 0 < result.diagnostics["n_selected"] < 50
        assert result.diagnostics["best_rmsecv"] < np.inf

    @pytest.mark.asyncio
    async def test_ipls_multi_interval(self, spectral_dataset):
        from spectra_sherpa.app.services.dag.nodes.selection.ipls_node import IPLSNode

        ds, y = spectral_dataset
        node = IPLSNode(
            "test_ipls2",
            {
                "n_intervals": 10,
                "n_components": 3,
                "cv_folds": 3,
                "n_best": 3,
            },
        )
        result = await node.execute(X=ds, y=y)

        # Combining 3 intervals should select more variables than 1
        assert result.diagnostics["n_selected"] > 0

    @pytest.mark.asyncio
    async def test_ipls_global_vs_local(self, spectral_dataset):
        from spectra_sherpa.app.services.dag.nodes.selection.ipls_node import IPLSNode

        ds, y = spectral_dataset
        node = IPLSNode(
            "test_ipls3",
            {
                "n_intervals": 5,
                "n_components": 2,
                "cv_folds": 3,
            },
        )
        result = await node.execute(X=ds, y=y)

        # Global RMSECV should be reported
        assert "global_rmsecv" in result.diagnostics
        assert result.diagnostics["global_rmsecv"] > 0


# ── CARS Tests ────────────────────────────────────────────────────────


class TestCARSNode:
    """Competitive Adaptive Reweighted Sampling."""

    @pytest.mark.asyncio
    async def test_basic_cars(self, spectral_dataset):
        from spectra_sherpa.app.services.dag.nodes.selection.cars_node import CARSNode

        ds, y = spectral_dataset
        node = CARSNode(
            "test_cars",
            {
                "n_iterations": 20,
                "n_components": 3,
                "cv_folds": 3,
            },
        )
        result = await node.execute(X=ds, y=y)

        assert result.diagnostics["n_selected"] > 0
        assert "best_rmsecv" in result.diagnostics
        assert len(result.diagnostics["rmsecv_trace"]) > 0

    @pytest.mark.asyncio
    async def test_cars_outputs_correct_shape(self, spectral_dataset):
        from spectra_sherpa.app.services.dag.nodes.selection.cars_node import CARSNode

        ds, y = spectral_dataset
        node = CARSNode(
            "test_cars2",
            {
                "n_iterations": 15,
                "n_components": 2,
                "cv_folds": 3,
            },
        )
        result = await node.execute(X=ds, y=y)

        mask = result.outputs["mask"]
        scores = result.outputs["scores"]
        X_sel = result.outputs["X_selected"]
        assert mask.shape == (50,)
        assert scores.shape == (50,)
        assert X_sel.X.shape[1] == np.sum(mask)


# ── SPA Tests ─────────────────────────────────────────────────────────


class TestSPANode:
    """Successive Projections Algorithm."""

    @pytest.mark.asyncio
    async def test_basic_spa(self, spectral_dataset):
        from spectra_sherpa.app.services.dag.nodes.selection.spa_node import SPANode

        ds, _ = spectral_dataset
        node = SPANode("test_spa", {"n_select": 10})
        result = await node.execute(X=ds)

        assert result.diagnostics["n_selected"] == 10
        assert "condition_number" in result.diagnostics
        assert result.diagnostics["condition_number"] > 0

    @pytest.mark.asyncio
    async def test_spa_selects_independent_vars(self, spectral_dataset):
        """SPA should yield a well-conditioned subset."""
        from spectra_sherpa.app.services.dag.nodes.selection.spa_node import SPANode

        ds, _ = spectral_dataset
        node = SPANode("test_spa2", {"n_select": 8})
        result = await node.execute(X=ds)

        # Condition number should be finite and not astronomical
        cond = result.diagnostics["condition_number"]
        assert np.isfinite(cond)

    @pytest.mark.asyncio
    async def test_spa_mask_and_scores(self, spectral_dataset):
        from spectra_sherpa.app.services.dag.nodes.selection.spa_node import SPANode

        ds, _ = spectral_dataset
        node = SPANode("test_spa3", {"n_select": 5})
        result = await node.execute(X=ds)

        mask = result.outputs["mask"]
        scores = result.outputs["scores"]
        assert mask.shape == (50,)
        assert np.sum(mask) == 5
        # First-selected variable should have highest score
        assert scores[mask].max() == 1.0


# ── UVE Tests ─────────────────────────────────────────────────────────


class TestUVENode:
    """Monte Carlo Uninformative Variable Elimination."""

    @pytest.mark.asyncio
    async def test_basic_uve(self, spectral_dataset):
        from spectra_sherpa.app.services.dag.nodes.selection.uve_node import UVENode

        ds, y = spectral_dataset
        node = UVENode(
            "test_uve",
            {
                "n_components": 3,
                "n_resamples": 30,
                "cutoff_percentile": 90.0,
            },
        )
        result = await node.execute(X=ds, y=y)

        assert result.diagnostics["n_selected"] > 0
        assert "noise_threshold" in result.diagnostics

    @pytest.mark.asyncio
    async def test_uve_outputs(self, spectral_dataset):
        from spectra_sherpa.app.services.dag.nodes.selection.uve_node import UVENode

        ds, y = spectral_dataset
        node = UVENode(
            "test_uve2",
            {
                "n_components": 2,
                "n_resamples": 25,
                "cutoff_percentile": 85.0,
            },
        )
        result = await node.execute(X=ds, y=y)

        mask = result.outputs["mask"]
        scores = result.outputs["scores"]
        assert mask.dtype == bool
        assert scores.shape == (50,)
        assert np.all(scores >= 0)


# ── Stability Selection Tests ─────────────────────────────────────────


class TestStabilitySelectionNode:
    """Bootstrap-robust stability selection."""

    @pytest.mark.asyncio
    async def test_basic_stability(self, spectral_dataset):
        from spectra_sherpa.app.services.dag.nodes.selection.stability_node import StabilitySelectionNode

        ds, y = spectral_dataset
        node = StabilitySelectionNode(
            "test_stab",
            {
                "base_method": "coef_abs",
                "base_threshold": 0.01,
                "stability_threshold": 0.3,
                "n_bootstrap": 30,
                "n_components": 3,
            },
        )
        result = await node.execute(X=ds, y=y)

        assert result.diagnostics["n_selected"] > 0
        assert result.diagnostics["base_method"] == "coef_abs"

    @pytest.mark.asyncio
    async def test_stability_scores_are_frequencies(self, spectral_dataset):
        from spectra_sherpa.app.services.dag.nodes.selection.stability_node import StabilitySelectionNode

        ds, y = spectral_dataset
        node = StabilitySelectionNode(
            "test_stab2",
            {
                "base_method": "coef_abs",
                "base_threshold": 0.01,
                "stability_threshold": 0.2,
                "n_bootstrap": 25,
                "n_components": 2,
            },
        )
        result = await node.execute(X=ds, y=y)

        scores = result.outputs["scores"]
        assert np.all(scores >= 0.0)
        assert np.all(scores <= 1.0)  # frequencies are [0, 1]

    @pytest.mark.asyncio
    async def test_stability_feature_axis(self, spectral_dataset):
        from spectra_sherpa.app.services.dag.nodes.selection.stability_node import StabilitySelectionNode

        ds, y = spectral_dataset
        node = StabilitySelectionNode(
            "test_stab3",
            {
                "base_method": "coef_abs",
                "base_threshold": 0.005,
                "stability_threshold": 0.2,
                "n_bootstrap": 20,
                "n_components": 2,
            },
        )
        result = await node.execute(X=ds, y=y)

        X_sel = result.outputs["X_selected"]
        assert hasattr(X_sel, "feature_axis")
        assert X_sel.feature_axis.selection_method == "stability"
        assert "feature_mask" in X_sel.meta


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("node_module", "node_name", "params", "needs_y"),
    [
        ("ipls_node", "IPLSNode", {"n_intervals": 10, "n_components": 3, "cv_folds": 3, "n_best": 1}, True),
        ("cars_node", "CARSNode", {"n_iterations": 15, "n_components": 2, "cv_folds": 3}, True),
        ("spa_node", "SPANode", {"n_select": 5}, False),
        ("uve_node", "UVENode", {"n_components": 2, "n_resamples": 20, "cutoff_percentile": 85.0}, True),
        (
            "stability_node",
            "StabilitySelectionNode",
            {
                "base_method": "coef_abs",
                "base_threshold": 0.01,
                "stability_threshold": 0.2,
                "n_bootstrap": 20,
                "n_components": 2,
            },
            True,
        ),
    ],
)
async def test_phase2_selection_outputs_store_feature_mask(spectral_dataset, node_module, node_name, params, needs_y):
    module = __import__(
        f"spectra_sherpa.app.services.dag.nodes.selection.{node_module}",
        fromlist=[node_name],
    )
    node_cls = getattr(module, node_name)
    ds, y = spectral_dataset
    node = node_cls("mask_contract", params)
    kwargs = {"X": ds}
    if needs_y:
        kwargs["y"] = y
    result = await node.execute(**kwargs)

    X_selected = result.outputs["X_selected"]
    assert "feature_mask" in X_selected.meta
    mask = np.asarray(X_selected.meta["feature_mask"], dtype=bool)
    assert mask.shape == (ds.shape[1],)
    assert np.sum(mask) == X_selected.shape[1]


# ── SPXY Sample Partition Test ────────────────────────────────────────


class TestSPXYPartition:
    """SPXY joint X+Y distance partitioning."""

    @pytest.mark.asyncio
    async def test_spxy_partition(self, spectral_dataset):
        from spectra_sherpa.app.services.dag.nodes.selection.sample_partition_node import SamplePartitionNode

        ds, y = spectral_dataset
        node = SamplePartitionNode(
            "test_spxy",
            {
                "method": "spxy",
                "test_size": 0.2,
            },
        )
        result = await node.execute(X=ds, y=y)

        assert result.diagnostics["method"] == "spxy"
        assert result.diagnostics["n_cal"] + result.diagnostics["n_test"] == 60
        assert "y_cal" in result.outputs
        assert "y_test" in result.outputs


# ── SPA Core Algorithm Tests ─────────────────────────────────────────


class TestSPAProjections:
    """Low-level SPA projection algorithm."""

    def test_projections_select_correct_count(self):
        from spectra_sherpa.app.services.dag.nodes.selection.spa_node import _spa_projections

        rng = np.random.RandomState(42)
        X = rng.randn(30, 20) - rng.randn(30, 20).mean(axis=0)
        selected = _spa_projections(X, n_select=8)
        assert len(selected) == 8
        assert len(np.unique(selected)) == 8

    def test_projections_with_start_var(self):
        from spectra_sherpa.app.services.dag.nodes.selection.spa_node import _spa_projections

        rng = np.random.RandomState(42)
        X = rng.randn(30, 20) - rng.randn(30, 20).mean(axis=0)
        selected = _spa_projections(X, n_select=5, start_var=3)
        assert selected[0] == 3
        assert len(selected) == 5


# ── UVE Core Algorithm Tests ─────────────────────────────────────────


class TestUVEMC:
    """Low-level MC-UVE algorithm."""

    def test_reliability_shape(self):
        from spectra_sherpa.app.services.dag.nodes.selection.uve_node import _uve_mc

        rng = np.random.RandomState(42)
        X = rng.randn(40, 20)
        y = X[:, 5] + rng.randn(40) * 0.1

        real_rel, noise_rel = _uve_mc(X, y, n_components=3, n_resamples=15, test_fraction=0.2)
        assert real_rel.shape == (20,)
        assert noise_rel.shape == (20,)
        assert np.all(real_rel >= 0)
        assert np.all(noise_rel >= 0)
