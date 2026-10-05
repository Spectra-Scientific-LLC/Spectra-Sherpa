"""Phase 2 selection node tests.

Covers:
- iPLS (interval PLS) variable selection
- CARS (Competitive Adaptive Reweighted Sampling)
- SPA (Successive Projections Algorithm)
- MC-UVE (Monte Carlo Uninformative Variable Elimination)
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
                "max_components": 3,
                "cv_folds": 3,
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
    async def test_ipls_selects_one_contiguous_interval(self, spectral_dataset):
        from spectra_sherpa.app.services.dag.nodes.selection.ipls_node import IPLSNode

        ds, y = spectral_dataset
        node = IPLSNode(
            "test_ipls2",
            {
                "n_intervals": 10,
                "max_components": 3,
                "cv_folds": 3,
            },
        )
        result = await node.execute(X=ds, y=y)

        # Standard iPLS retains exactly one contiguous interval, not a
        # combination of the best-scoring intervals.
        mask = result.outputs["mask"]
        selected_indices = np.flatnonzero(mask)
        assert selected_indices.size > 0
        assert np.array_equal(selected_indices, np.arange(selected_indices[0], selected_indices[-1] + 1))

    @pytest.mark.asyncio
    async def test_ipls_global_vs_local(self, spectral_dataset):
        from spectra_sherpa.app.services.dag.nodes.selection.ipls_node import IPLSNode

        ds, y = spectral_dataset
        node = IPLSNode(
            "test_ipls3",
            {
                "n_intervals": 5,
                "max_components": 2,
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
                "max_components": 3,
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
                "max_components": 2,
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

        ds, y = spectral_dataset
        node = SPANode("test_spa", {"max_variables": 10, "cv_folds": 3})
        result = await node.execute(X=ds, y=y)

        assert 1 <= result.diagnostics["n_selected"] <= 10
        assert result.diagnostics["best_rmsecv"] >= 0

    @pytest.mark.asyncio
    async def test_spa_selects_independent_vars(self, spectral_dataset):
        """SPA should yield a well-conditioned subset."""
        from spectra_sherpa.app.services.dag.nodes.selection.spa_node import SPANode

        ds, y = spectral_dataset
        node = SPANode("test_spa2", {"max_variables": 8, "cv_folds": 3})
        result = await node.execute(X=ds, y=y)

        assert np.isfinite(result.diagnostics["best_rmsecv"])
        assert result.diagnostics["candidate_chain_count"] > 1

    @pytest.mark.asyncio
    async def test_spa_mask_and_scores(self, spectral_dataset):
        from spectra_sherpa.app.services.dag.nodes.selection.spa_node import SPANode

        ds, y = spectral_dataset
        node = SPANode("test_spa3", {"max_variables": 5, "cv_folds": 3})
        result = await node.execute(X=ds, y=y)

        mask = result.outputs["mask"]
        scores = result.outputs["scores"]
        assert mask.shape == (50,)
        assert 1 <= np.sum(mask) <= 5
        # First-selected variable should have highest score
        assert scores[mask].max() == 1.0


# ── MC-UVE Tests ──────────────────────────────────────────────────────


class TestMCUVENode:
    """Monte Carlo Uninformative Variable Elimination."""

    @pytest.mark.asyncio
    async def test_basic_uve(self, spectral_dataset):
        from spectra_sherpa.app.services.dag.nodes.selection.mcuve_node import MCUVENode

        ds, y = spectral_dataset
        node = MCUVENode(
            "test_uve",
            {
                "n_components": 3,
                "n_resamples": 30,
                "n_variables": 10,
            },
        )
        result = await node.execute(X=ds, y=y)

        assert result.diagnostics["n_selected"] > 0
        assert result.diagnostics["n_selected"] == 10

    @pytest.mark.asyncio
    async def test_uve_outputs(self, spectral_dataset):
        from spectra_sherpa.app.services.dag.nodes.selection.mcuve_node import MCUVENode

        ds, y = spectral_dataset
        node = MCUVENode(
            "test_uve2",
            {
                "n_components": 2,
                "n_resamples": 25,
                "n_variables": 10,
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
                "selection_probability_threshold": 0.6,
                "n_resamples": 30,
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
                "selection_probability_threshold": 0.6,
                "n_resamples": 25,
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
                "selection_probability_threshold": 0.6,
                "n_resamples": 20,
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
        ("ipls_node", "IPLSNode", {"n_intervals": 10, "max_components": 3, "cv_folds": 3}, True),
        ("cars_node", "CARSNode", {"n_iterations": 15, "max_components": 2, "cv_folds": 3}, True),
        ("spa_node", "SPANode", {"max_variables": 5, "cv_folds": 3}, True),
        ("mcuve_node", "MCUVENode", {"n_components": 2, "n_resamples": 20, "n_variables": 10}, True),
        (
            "stability_node",
            "StabilitySelectionNode",
            {
                "base_method": "coef_abs",
                "base_threshold": 0.01,
                "selection_probability_threshold": 0.6,
                "n_resamples": 20,
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
        from spectra_sherpa.app.services.dag.nodes.data.transforms import TrainTestSplitNode

        ds, y = spectral_dataset
        node = TrainTestSplitNode(
            "test_spxy",
            {
                "split_method": "spxy",
                "test_size": 0.2,
            },
        )
        result = await node.execute(X=ds, y=y)

        assert result["X_train"].shape[0] + result["X_test"].shape[0] == 60
        assert "y_train" in result
        assert "y_test" in result


# ── SPA Core Algorithm Tests ─────────────────────────────────────────


class TestSPAProjectionChains:
    """Low-level SPA projection-chain algorithm."""

    def test_projections_select_correct_count(self):
        from spectra_sherpa.app.services.dag.nodes.selection.spa_node import _spa_projection_chains

        rng = np.random.default_rng(42)
        X = rng.normal(size=(30, 20))
        chains = _spa_projection_chains(X, max_variables=8)
        assert len(chains) == 20
        assert all(len(chain) == 8 for chain in chains)
        assert all(len(set(chain)) == len(chain) for chain in chains)

    def test_projections_with_start_var(self):
        from spectra_sherpa.app.services.dag.nodes.selection.spa_node import _spa_projection_chains

        rng = np.random.default_rng(42)
        X = rng.normal(size=(30, 20))
        chains = _spa_projection_chains(X, max_variables=5)
        assert [chain[0] for chain in chains] == list(range(20))
        assert len(chains[3]) == 5


# ── MC-UVE Core Algorithm Tests ──────────────────────────────────────


class TestMCUVE:
    """Low-level MC-UVE algorithm."""

    def test_reliability_shape(self):
        from spectra_sherpa.app.services.dag.nodes.selection.mcuve_node import _mcuve_dispatch

        rng = np.random.RandomState(42)
        X = rng.randn(40, 20)
        y = X[:, 5] + rng.randn(40) * 0.1

        result = _mcuve_dispatch(
            X,
            y,
            n_components=3,
            n_resamples=20,
            calibration_fraction=0.8,
            n_variables=5,
            random_seed=42,
        )
        stability = np.asarray(result["stability_scores"])
        assert stability.shape == (20,)
        assert np.all(stability >= 0)
        assert np.sum(result["feature_mask"]) == 5
