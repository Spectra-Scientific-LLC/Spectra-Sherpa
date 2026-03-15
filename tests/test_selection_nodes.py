"""Tests for the Selection & Design node family.

Covers:
- Kennard-Stone and DUPLEX sample partitioning algorithms
- FeatureAxis.include_mask contract
- VIP shared utility equivalence
- Variable selection methods (interval, peak_window, vip)
- Mask propagation through feature axis
"""

from __future__ import annotations

import numpy as np
import pytest

# ── Sample Algorithm Tests ─────────────────────────────────────────────


class TestKennardStone:
    """Kennard-Stone greedy maximin selection."""

    def test_basic_selection(self):
        from spectra_sherpa.app.services.dag.nodes.selection._sample_algorithms import kennard_stone

        rng = np.random.RandomState(42)
        X = rng.randn(50, 10)
        selected = kennard_stone(X, n_select=20)

        assert len(selected) == 20
        assert len(np.unique(selected)) == 20  # no duplicates
        assert all(0 <= idx < 50 for idx in selected)

    def test_deterministic(self):
        """KS is deterministic — same input always gives same output."""
        from spectra_sherpa.app.services.dag.nodes.selection._sample_algorithms import kennard_stone

        X = np.random.RandomState(0).randn(30, 5)
        sel1 = kennard_stone(X, 15)
        sel2 = kennard_stone(X, 15)
        np.testing.assert_array_equal(sel1, sel2)

    def test_select_all(self):
        """Requesting all samples returns all indices."""
        from spectra_sherpa.app.services.dag.nodes.selection._sample_algorithms import kennard_stone

        X = np.random.RandomState(0).randn(10, 3)
        selected = kennard_stone(X, 10)
        assert len(selected) == 10

    def test_mahalanobis_metric(self):
        from spectra_sherpa.app.services.dag.nodes.selection._sample_algorithms import kennard_stone

        X = np.random.RandomState(42).randn(30, 5)
        selected = kennard_stone(X, 15, metric="mahalanobis")
        assert len(selected) == 15

    def test_with_pca_reduction(self):
        from spectra_sherpa.app.services.dag.nodes.selection._sample_algorithms import kennard_stone

        X = np.random.RandomState(42).randn(40, 100)
        selected = kennard_stone(X, 20, n_pcs=5)
        assert len(selected) == 20

    def test_space_filling_property(self):
        """KS should spread selections across the space better than random."""
        from spectra_sherpa.app.services.dag.nodes.selection._sample_algorithms import (
            kennard_stone,
        )

        rng = np.random.RandomState(42)
        # Create data with clear structure (two clusters)
        X = np.vstack([rng.randn(25, 5) + 3, rng.randn(25, 5) - 3])

        ks_idx = kennard_stone(X, 10)

        # KS should select from both clusters
        from_cluster_1 = np.sum(ks_idx < 25)
        from_cluster_2 = np.sum(ks_idx >= 25)
        assert from_cluster_1 >= 2, "KS should select from cluster 1"
        assert from_cluster_2 >= 2, "KS should select from cluster 2"


class TestDUPLEX:
    """DUPLEX simultaneous cal/test partitioning."""

    def test_basic_partition(self):
        from spectra_sherpa.app.services.dag.nodes.selection._sample_algorithms import duplex

        rng = np.random.RandomState(42)
        X = rng.randn(50, 10)
        cal_idx, test_idx = duplex(X, n_cal=35)

        assert len(cal_idx) == 35
        assert len(test_idx) == 15
        # No overlap
        assert len(set(cal_idx) & set(test_idx)) == 0
        # All samples accounted for
        assert len(set(cal_idx) | set(test_idx)) == 50

    def test_deterministic(self):
        from spectra_sherpa.app.services.dag.nodes.selection._sample_algorithms import duplex

        X = np.random.RandomState(0).randn(30, 5)
        c1, t1 = duplex(X, 20)
        c2, t2 = duplex(X, 20)
        np.testing.assert_array_equal(c1, c2)
        np.testing.assert_array_equal(t1, t2)

    def test_both_sets_cover_space(self):
        """Both cal and test should have points from different regions."""
        from spectra_sherpa.app.services.dag.nodes.selection._sample_algorithms import duplex

        rng = np.random.RandomState(42)
        X = np.vstack([rng.randn(25, 5) + 5, rng.randn(25, 5) - 5])

        cal_idx, test_idx = duplex(X, n_cal=30)

        # Both sets should contain points from both clusters
        cal_from_c1 = np.sum(cal_idx < 25)
        cal_from_c2 = np.sum(cal_idx >= 25)
        test_from_c1 = np.sum(test_idx < 25)
        test_from_c2 = np.sum(test_idx >= 25)

        assert cal_from_c1 >= 1 and cal_from_c2 >= 1
        assert test_from_c1 >= 1 and test_from_c2 >= 1


# ── FeatureAxis Contract Tests ─────────────────────────────────────────


class TestFeatureAxisMask:
    """Feature selection contract on FeatureAxis."""

    def test_include_mask_basic(self):
        from spectra_sherpa.app.lib.axes import FeatureAxis

        fa = FeatureAxis(values=np.linspace(400, 4000, 100))
        assert fa.n_selected == 100

        mask = np.ones(100, dtype=bool)
        mask[50:] = False
        fa.apply_mask(mask, method="test")

        assert fa.n_selected == 50
        assert fa.selection_method == "test"
        assert fa.include_mask is not None
        np.testing.assert_array_equal(fa.include_mask, mask)

    def test_include_mask_validation(self):
        from spectra_sherpa.app.lib.axes import FeatureAxis

        with pytest.raises(ValueError, match="include_mask length"):
            FeatureAxis(
                values=np.linspace(400, 4000, 100),
                include_mask=np.ones(50, dtype=bool),  # wrong length
            )

    def test_selection_scores_validation(self):
        from spectra_sherpa.app.lib.axes import FeatureAxis

        with pytest.raises(ValueError, match="selection_scores length"):
            FeatureAxis(
                values=np.linspace(400, 4000, 100),
                selection_scores=np.ones(50),  # wrong length
            )

    def test_copy_preserves_mask(self):
        from spectra_sherpa.app.lib.axes import SpectralAxis

        fa = SpectralAxis(values=np.linspace(400, 4000, 50), units="cm-1")
        mask = np.ones(50, dtype=bool)
        mask[25:] = False
        scores = np.random.rand(50)
        fa.apply_mask(mask, method="vip", scores=scores)

        cp = fa.copy()
        assert cp.selection_method == "vip"
        np.testing.assert_array_equal(cp.include_mask, mask)
        np.testing.assert_array_equal(cp.selection_scores, scores)

        # Mutating copy doesn't affect original
        cp.include_mask[0] = False
        assert fa.include_mask[0]  # noqa: E712

    def test_exclude_include_feature(self):
        from spectra_sherpa.app.lib.axes import FeatureAxis

        fa = FeatureAxis(values=np.array([1.0, 2.0, 3.0, 4.0, 5.0]))
        assert fa.n_selected == 5

        fa.exclude_feature(2)
        assert fa.n_selected == 4
        assert not fa.include_mask[2]  # noqa: E712

        fa.include_feature(2)
        assert fa.n_selected == 5
        assert fa.include_mask[2]  # noqa: E712


# ── VIP Shared Utility Tests ──────────────────────────────────────────


class TestVIPUtility:
    """Shared VIP calculation matches the original PLS-DA implementation."""

    def test_basic_vip_calculation(self):
        from spectra_sherpa.app.services.dag.nodes.selection._vip import calculate_vip

        rng = np.random.RandomState(42)
        n_samples, n_features, n_components = 50, 20, 3

        t = rng.randn(n_samples, n_components)  # scores
        w = rng.randn(n_components, n_features)  # weights (component x feature)
        q = rng.randn(1, n_components)  # y loadings

        vip = calculate_vip(t, w, q, n_features)

        assert vip.shape == (n_features,)
        assert np.all(np.isfinite(vip))
        assert np.all(vip >= 0)
        # Mean VIP should be approximately 1.0 by construction
        assert 0.5 < np.mean(vip) < 2.0

    def test_vip_zeros_on_empty_input(self):
        from spectra_sherpa.app.services.dag.nodes.selection._vip import calculate_vip

        # Malformed inputs should return zeros, not crash
        vip = calculate_vip(
            np.zeros((10, 3)),
            np.zeros((3, 20)),
            np.zeros((1, 3)),
            20,
        )
        assert vip.shape == (20,)
        assert np.all(vip == 0.0)


# ── Sample Partition Node Tests ────────────────────────────────────────


class TestSamplePartitionNode:
    """Integration tests for selection.sample_partition."""

    @pytest.fixture
    def make_dataset(self):
        """Create a simple SherpaDataset for testing."""

        def _make(n_samples=50, n_features=100):
            from spectra_sherpa.app.lib.sherpa_dataset import SampleAxis, SherpaDataset, SpectralAxis

            rng = np.random.RandomState(42)
            ds = SherpaDataset(
                X=rng.randn(n_samples, n_features),
                feature_axis=SpectralAxis(values=np.linspace(400, 4000, n_features), units="cm-1"),
                sample_axis=SampleAxis(labels=[f"sample_{i}" for i in range(n_samples)]),
                target=rng.rand(n_samples),
            )
            return ds

        return _make

    @pytest.mark.asyncio
    async def test_kennard_stone_partition(self, make_dataset):
        from spectra_sherpa.app.services.dag.nodes.selection.sample_partition_node import SamplePartitionNode

        ds = make_dataset(50, 100)
        node = SamplePartitionNode("test_ks", {"method": "kennard_stone", "test_size": 0.2})
        result = await node.execute(X=ds)

        assert "X_cal" in result.outputs
        assert "X_test" in result.outputs
        assert "cal_indices" in result.outputs
        assert result.diagnostics["method"] == "kennard_stone"
        assert result.diagnostics["n_cal"] == 40
        assert result.diagnostics["n_test"] == 10

    @pytest.mark.asyncio
    async def test_duplex_partition(self, make_dataset):
        from spectra_sherpa.app.services.dag.nodes.selection.sample_partition_node import SamplePartitionNode

        ds = make_dataset(50, 100)
        node = SamplePartitionNode("test_dup", {"method": "duplex", "test_size": 0.2})
        result = await node.execute(X=ds)

        n_cal = result.diagnostics["n_cal"]
        n_test = result.diagnostics["n_test"]
        assert n_cal + n_test == 50
        assert "coverage" in result.diagnostics

    @pytest.mark.asyncio
    async def test_random_partition(self, make_dataset):
        from spectra_sherpa.app.services.dag.nodes.selection.sample_partition_node import SamplePartitionNode

        ds = make_dataset(50, 100)
        node = SamplePartitionNode("test_rand", {"method": "random", "test_size": 0.3, "random_seed": 42})
        result = await node.execute(X=ds)

        assert result.diagnostics["n_test"] == 15
        assert result.diagnostics["n_cal"] == 35


# ── Variable Selection Node Tests ──────────────────────────────────────


class TestVariableSelectNode:
    """Integration tests for selection.variable_select."""

    @pytest.fixture
    def make_dataset(self):
        def _make(n_samples=50, n_features=200):
            from spectra_sherpa.app.lib.sherpa_dataset import SherpaDataset, SpectralAxis

            rng = np.random.RandomState(42)
            ds = SherpaDataset(
                X=rng.randn(n_samples, n_features),
                feature_axis=SpectralAxis(values=np.linspace(400, 4000, n_features), units="cm-1"),
            )
            return ds

        return _make

    @pytest.mark.asyncio
    async def test_interval_selection(self, make_dataset):
        from spectra_sherpa.app.services.dag.nodes.selection.variable_select_node import VariableSelectNode

        ds = make_dataset()
        node = VariableSelectNode(
            "test_int",
            {"method": "interval", "region_start": 1600, "region_end": 1800},
        )
        result = await node.execute(X=ds)

        mask = result.outputs["mask"]
        assert mask.dtype == bool
        n_selected = result.diagnostics["n_selected"]
        assert 0 < n_selected < 200

        X_sel = result.outputs["X_selected"]
        assert hasattr(X_sel, "feature_axis")
        assert X_sel.feature_axis.selection_method == "interval"

    @pytest.mark.asyncio
    async def test_peak_window_selection(self, make_dataset):
        from spectra_sherpa.app.services.dag.nodes.selection.variable_select_node import VariableSelectNode

        ds = make_dataset()
        node = VariableSelectNode(
            "test_peak",
            {"method": "peak_window", "peak_prominence": 0.05, "peak_half_window": 5},
        )
        result = await node.execute(X=ds)

        assert result.diagnostics["n_selected"] > 0
        assert "scores" in result.outputs

    @pytest.mark.asyncio
    async def test_vip_requires_model(self, make_dataset):
        from spectra_sherpa.app.services.dag.nodes.selection.variable_select_node import VariableSelectNode

        ds = make_dataset()
        node = VariableSelectNode("test_vip", {"method": "vip", "threshold": 1.0})

        with pytest.raises(ValueError, match="requires a PLS"):
            await node.execute(X=ds)  # no model provided

    @pytest.mark.asyncio
    async def test_interval_requires_region(self, make_dataset):
        from spectra_sherpa.app.services.dag.nodes.selection.variable_select_node import VariableSelectNode

        ds = make_dataset()
        node = VariableSelectNode("test_int2", {"method": "interval"})

        with pytest.raises(ValueError, match="region_start"):
            await node.execute(X=ds)

    @pytest.mark.asyncio
    async def test_invert_selection(self, make_dataset):
        from spectra_sherpa.app.services.dag.nodes.selection.variable_select_node import VariableSelectNode

        ds = make_dataset()
        node_normal = VariableSelectNode(
            "test_inv1",
            {"method": "interval", "region_start": 1600, "region_end": 1800},
        )
        node_invert = VariableSelectNode(
            "test_inv2",
            {"method": "interval", "region_start": 1600, "region_end": 1800, "invert": True},
        )

        result_normal = await node_normal.execute(X=ds)
        result_invert = await node_invert.execute(X=ds)

        n_normal = result_normal.diagnostics["n_selected"]
        n_invert = result_invert.diagnostics["n_selected"]
        assert n_normal + n_invert == 200
