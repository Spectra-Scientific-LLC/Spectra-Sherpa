"""Tests for the embedded target architecture.

Verifies:
1. Data Source embeds target into dataset.target with TargetContext
2. Single-wire workflows (DataSource → PLS) work without explicit y port
3. Backward-compat: explicit y wiring still works
4. AttachTarget utility node
5. TargetContext.target_names serialization roundtrip
"""

from __future__ import annotations

import numpy as np
import pytest

from spectra_sherpa.app.lib.sherpa_dataset import (
    SherpaDataset,
    SpectralAxis,
    TargetContext,
)
from spectra_sherpa.app.services.dag.node_base import node_registry


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def make_node():
    """Create a DAG node by type with given parameters."""

    def _make(node_type: str, params: dict | None = None, node_id: str = "test"):
        return node_registry.create_node(node_type, node_id, params or {})

    return _make


def _make_dataset_with_target(
    n_samples: int = 50,
    n_features: int = 100,
    n_targets: int = 1,
    target_type: str = "continuous",
    target_names: list[str] | None = None,
) -> SherpaDataset:
    """Create a SherpaDataset with embedded target for testing."""
    rng = np.random.RandomState(42)
    X = rng.randn(n_samples, n_features)
    if target_type == "continuous":
        target = rng.randn(n_samples, n_targets) if n_targets > 1 else rng.randn(n_samples)
    else:
        target = rng.choice(["A", "B", "C"], size=n_samples)

    ds = SherpaDataset(
        X=X,
        feature_axis=SpectralAxis(
            values=np.arange(n_features, dtype=np.float64),
            title="Wavelength",
        ),
        target=target,
        target_context=TargetContext(
            target_type=target_type,
            target_names=target_names,
        ),
        backend="numpy",
    )
    return ds


# ---------------------------------------------------------------------------
# 1. TargetContext.target_names
# ---------------------------------------------------------------------------


class TestTargetContext:
    def test_target_names_serialization_roundtrip(self):
        """target_names should survive to_dict() / from_dict() cycle."""
        ds = _make_dataset_with_target(
            n_targets=4,
            target_names=["Moisture", "Oil", "Protein", "Starch"],
        )
        d = ds.to_dict()
        restored = SherpaDataset.from_dict(d)
        assert restored.target_context.target_names == ["Moisture", "Oil", "Protein", "Starch"]
        assert restored.target_context.target_type == "continuous"
        np.testing.assert_array_equal(restored.target, ds.target)

    def test_target_names_none_when_not_set(self):
        """target_names defaults to None."""
        ctx = TargetContext(target_type="continuous")
        assert ctx.target_names is None

    def test_target_context_copy(self):
        """TargetContext copy should be deep."""
        ds = _make_dataset_with_target(
            n_targets=2,
            target_names=["A", "B"],
        )
        ds_copy = ds.copy()
        ds_copy.target_context.target_names.append("C")
        assert ds.target_context.target_names == ["A", "B"]


# ---------------------------------------------------------------------------
# 2. Data Source embeds target
# ---------------------------------------------------------------------------


class TestDataSourceEmbeddedTarget:
    @pytest.mark.asyncio
    async def test_eigenvector_corn_m5_embedded(self, make_node):
        """Corn M5: dataset.target should be (80, 4) with target_names."""
        node = make_node("data.source", {"source": "eigenvector", "eigenvector_dataset": "corn_m5"})
        result = await node.execute()
        dataset = result["default"]

        assert dataset.target is not None
        assert dataset.target.shape == (80, 4)
        assert dataset.target_context.target_type == "continuous"
        assert dataset.target_context.target_names == ["Moisture", "Oil", "Protein", "Starch"]
        # Target output port should be derived from embedded
        np.testing.assert_array_equal(result["target"], dataset.target)

    @pytest.mark.asyncio
    async def test_sklearn_iris_embedded(self, make_node):
        """sklearn iris: dataset.target should be embedded with categorical context."""
        node = make_node("data.source", {"source": "sklearn", "sklearn_dataset": "iris"})
        result = await node.execute()
        dataset = result["default"]

        assert dataset.target is not None
        assert len(dataset.target) == 150
        assert dataset.target_context.target_type == "categorical"

    @pytest.mark.asyncio
    async def test_target_port_matches_embedded(self, make_node):
        """Target output port should be exactly dataset.target."""
        node = make_node("data.source", {"source": "eigenvector", "eigenvector_dataset": "diesel_nir"})
        result = await node.execute()
        dataset = result["default"]
        target_port = result["target"]

        assert target_port is dataset.target


# ---------------------------------------------------------------------------
# 3. Single-wire PLS (no explicit y port)
# ---------------------------------------------------------------------------


class TestSingleWirePLS:
    @pytest.mark.asyncio
    async def test_pls_infers_target_from_dataset(self, make_node):
        """PLS should extract y from dataset.target when y not wired."""
        ds = _make_dataset_with_target(n_samples=50, n_features=100, n_targets=1)
        node = make_node("model.pls", {"n_components": 2, "scale": True})
        result = await node.execute(X=ds)

        assert "default" in result  # X_scores
        assert "model" in result

    @pytest.mark.asyncio
    async def test_pls_multi_target_inferred(self, make_node):
        """PLS with 4 embedded targets should produce multi-target model."""
        ds = _make_dataset_with_target(
            n_samples=50,
            n_features=100,
            n_targets=4,
            target_names=["Moisture", "Oil", "Protein", "Starch"],
        )
        node = make_node("model.pls", {"n_components": 3, "scale": True})
        result = await node.execute(X=ds)

        assert "model" in result
        assert "default" in result  # X_scores

    @pytest.mark.asyncio
    async def test_pls_explicit_y_still_works(self, make_node):
        """Explicit y wiring should override embedded target."""
        ds = _make_dataset_with_target(n_samples=50, n_features=100, n_targets=1)
        # Provide explicit y that differs from embedded
        explicit_y = np.random.randn(50)
        node = make_node("model.pls", {"n_components": 2, "scale": True})
        result = await node.execute(X=ds, y=explicit_y)

        assert "model" in result

    @pytest.mark.asyncio
    async def test_pls_no_target_gives_helpful_error(self, make_node):
        """PLS with no target anywhere should give helpful error."""
        ds = SherpaDataset(
            X=np.random.randn(50, 100),
            backend="numpy",
        )
        node = make_node("model.pls", {"n_components": 2})
        with pytest.raises(ValueError, match="No target values found"):
            await node.execute(X=ds)


# ---------------------------------------------------------------------------
# 4. Single-wire PCR
# ---------------------------------------------------------------------------


class TestSingleWirePCR:
    @pytest.mark.asyncio
    async def test_pcr_infers_target(self, make_node):
        """PCR should extract y from dataset.target when y not wired."""
        ds = _make_dataset_with_target(n_samples=50, n_features=100, n_targets=1)
        node = make_node("model.pcr", {"n_components": 2, "scale": True})
        result = await node.execute(X=ds)

        assert "model" in result
        assert "default" in result  # scores


# ---------------------------------------------------------------------------
# 5. AttachTarget node
# ---------------------------------------------------------------------------


class TestAttachTarget:
    @pytest.mark.asyncio
    async def test_attach_continuous_target(self, make_node):
        """AttachTarget should embed target in dataset."""
        ds = SherpaDataset(X=np.random.randn(50, 100), backend="numpy")
        y = np.random.randn(50, 3)
        node = make_node("data.attach_target", {"target_type": "continuous"})
        result = await node.execute(X=ds, y=y)

        out = result["default"]
        assert isinstance(out, SherpaDataset)
        assert out.target is not None
        assert out.target.shape == (50, 3)
        assert out.target_context.target_type == "continuous"

    @pytest.mark.asyncio
    async def test_attach_categorical_target(self, make_node):
        """AttachTarget with categorical type should set n_classes."""
        ds = SherpaDataset(X=np.random.randn(30, 50), backend="numpy")
        y = np.array([0, 1, 2] * 10)
        node = make_node("data.attach_target", {"target_type": "categorical"})
        result = await node.execute(X=ds, y=y)

        out = result["default"]
        assert out.target_context.target_type == "categorical"
        assert out.target_context.n_classes == 3

    @pytest.mark.asyncio
    async def test_attach_validates_sample_count(self, make_node):
        """AttachTarget should error if y has wrong number of samples."""
        ds = SherpaDataset(X=np.random.randn(50, 100), backend="numpy")
        y = np.random.randn(30)  # Wrong count
        node = make_node("data.attach_target")
        with pytest.raises(ValueError, match="50 samples"):
            await node.execute(X=ds, y=y)

    @pytest.mark.asyncio
    async def test_attach_then_pls(self, make_node):
        """AttachTarget → PLS should work as single-wire pipeline."""
        ds = SherpaDataset(X=np.random.randn(50, 100), backend="numpy")
        y = np.random.randn(50)

        attach_node = make_node("data.attach_target", {"target_type": "continuous"}, node_id="attach")
        attach_result = await attach_node.execute(X=ds, y=y)
        ds_with_target = attach_result["default"]

        pls_node = make_node("model.pls", {"n_components": 2, "scale": True}, node_id="pls")
        pls_result = await pls_node.execute(X=ds_with_target)  # No y — inferred from embedded

        assert "model" in pls_result
