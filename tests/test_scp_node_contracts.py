"""Contract tests for SCP-backed nodes.

Verifies:
1. No SCP node returns NDDataset in any output port
2. Shape conventions are correct for modeling node outputs
3. SherpaDataset outputs carry correct axis metadata

Run with:
    cd spectra-sherpa && .venv/bin/pytest tests/test_scp_node_contracts.py -v
"""

from __future__ import annotations

import numpy as np
import pytest

from spectra_sherpa.app.lib.scp_compat import HAS_SCP
from spectra_sherpa.app.lib.sherpa_dataset import (
    SherpaDataset,
    SpectralAxis,
    TargetContext,
)
from spectra_sherpa.app.services.dag.node_base import node_registry
from spectra_sherpa.app.services.serialization import serialize_result

_skip_no_scp = pytest.mark.skipif(not HAS_SCP, reason="spectrochempy not installed")

if HAS_SCP:
    from spectra_sherpa.app.lib.scp_compat import NDDataset as _NDDataset
else:
    _NDDataset = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _check_no_nddataset(value, path=""):
    """Recursively assert that no NDDataset exists in the value tree."""
    if _NDDataset is not None and isinstance(value, _NDDataset):
        raise AssertionError(f"NDDataset found at output path '{path}'")
    if isinstance(value, dict):
        for k, v in value.items():
            _check_no_nddataset(v, f"{path}.{k}")
    if isinstance(value, (list, tuple)):
        for i, v in enumerate(value):
            _check_no_nddataset(v, f"{path}[{i}]")


def _unwrap_result(result) -> dict:
    """Unwrap NodeResult.outputs or pass through a plain dict."""
    if hasattr(result, "outputs"):
        return result.outputs
    return result


@pytest.fixture
def make_node():
    """Create a DAG node by type with given parameters."""

    def _make(node_type: str, params: dict | None = None, node_id: str = "test"):
        return node_registry.create_node(node_type, node_id, params or {})

    return _make


def _make_spectral_dataset(
    n_samples: int = 30,
    n_features: int = 100,
    *,
    n_targets: int = 0,
    target_names: list[str] | None = None,
    target_type: str = "continuous",
) -> SherpaDataset:
    """Build a synthetic SherpaDataset for testing."""
    rng = np.random.RandomState(42)
    X = rng.randn(n_samples, n_features).astype(np.float64)
    # Ensure positive values for MCR/SIMPLISMA (non-negative constraints)
    X = np.abs(X) + 0.1

    target = None
    target_context = None
    if n_targets > 0:
        if target_type == "continuous":
            target = rng.randn(n_samples, n_targets) if n_targets > 1 else rng.randn(n_samples)
        else:
            classes = np.array(["A", "B", "C"], dtype=object)
            target = np.resize(classes, n_samples)
        target_context = TargetContext(
            target_type=target_type,
            target_names=target_names,
        )

    return SherpaDataset(
        X=X,
        feature_axis=SpectralAxis(
            values=np.linspace(400, 4000, n_features),
            title="Wavenumber",
            units="cm^-1",
        ),
        target=target,
        target_context=target_context,
        backend="numpy",
    )


# ---------------------------------------------------------------------------
# 1. No-NDDataset contract (all SCP modeling nodes)
# ---------------------------------------------------------------------------


class TestNoNDDatasetContract:
    """Every SCP modeling node must return SherpaDataset, never NDDataset."""

    @_skip_no_scp
    @pytest.mark.asyncio
    async def test_pca_no_nddataset(self, make_node):
        ds = _make_spectral_dataset(n_samples=20, n_features=50)
        node = make_node("model.pca", {"n_components": "2"})
        result = _unwrap_result(await node.execute(input_data=ds))
        _check_no_nddataset(result, "pca")

    @_skip_no_scp
    @pytest.mark.asyncio
    async def test_pls_no_nddataset(self, make_node):
        ds = _make_spectral_dataset(n_samples=30, n_features=50, n_targets=2, target_names=["A", "B"])
        node = make_node("model.pls", {"n_components": 2})
        result = await node.execute(X=ds)
        _check_no_nddataset(result, "pls")

    @_skip_no_scp
    @pytest.mark.asyncio
    async def test_mcr_no_nddataset(self, make_node):
        ds = _make_spectral_dataset(n_samples=20, n_features=50)
        node = make_node("model.mcr_als", {"n_components": 2})
        result = await node.execute(input_data=ds)
        _check_no_nddataset(result, "mcr")

    @_skip_no_scp
    @pytest.mark.asyncio
    async def test_efa_no_nddataset(self, make_node):
        # EFA returns (n_samples, n_components) eigenvalues; use matching n_components
        ds = _make_spectral_dataset(n_samples=20, n_features=50)
        node = make_node("model.efa", {"n_components": 20})
        result = await node.execute(input_data=ds)
        _check_no_nddataset(result, "efa")

    @_skip_no_scp
    @pytest.mark.asyncio
    async def test_simplisma_no_nddataset(self, make_node):
        ds = _make_spectral_dataset(n_samples=20, n_features=50)
        node = make_node("model.simplisma", {"n_components": 2})
        result = await node.execute(input_data=ds)
        _check_no_nddataset(result, "simplisma")


# ---------------------------------------------------------------------------
# 2. Shape convention tests
# ---------------------------------------------------------------------------


class TestShapeConventions:
    """Verify canonical shapes for modeling node outputs."""

    @_skip_no_scp
    @pytest.mark.asyncio
    async def test_pca_shapes(self, make_node):
        n_samples, n_features, n_components = 20, 50, 3
        ds = _make_spectral_dataset(n_samples=n_samples, n_features=n_features)
        node = make_node("model.pca", {"n_components": str(n_components)})
        result = _unwrap_result(await node.execute(input_data=ds))

        scores = result["scores"]
        loadings = result["loadings"]
        assert isinstance(scores, SherpaDataset)
        assert isinstance(loadings, SherpaDataset)
        assert scores.shape == (n_samples, n_components)
        assert loadings.shape == (n_components, n_features)

    @_skip_no_scp
    @pytest.mark.asyncio
    async def test_pls_shapes(self, make_node):
        n_samples, n_features, n_components, n_targets = 30, 50, 3, 2
        ds = _make_spectral_dataset(
            n_samples=n_samples,
            n_features=n_features,
            n_targets=n_targets,
            target_names=["Target_A", "Target_B"],
        )
        node = make_node("model.pls", {"n_components": n_components})
        result = await node.execute(X=ds)

        # X scores: (n_samples, n_components)
        assert result["default"].shape == (n_samples, n_components)
        # X loadings: (n_components, n_features)
        assert result["X_loadings"].shape == (n_components, n_features)
        # Y scores: (n_samples, n_components)
        assert result["Y_scores"].shape == (n_samples, n_components)
        # Y loadings: (n_targets, n_components)
        assert result["Y_loadings"].shape == (n_targets, n_components)
        # Coefficients: (n_features, n_targets) — plain ndarray
        assert result["coef"].shape == (n_features, n_targets)

    @_skip_no_scp
    @pytest.mark.asyncio
    async def test_pls_y_loadings_target_labels(self, make_node):
        """Y_loadings should carry target names on sample axis."""
        ds = _make_spectral_dataset(
            n_samples=30,
            n_features=50,
            n_targets=2,
            target_names=["Moisture", "Oil"],
        )
        node = make_node("model.pls", {"n_components": 2})
        result = await node.execute(X=ds)

        yl = result["Y_loadings"]
        assert isinstance(yl, SherpaDataset)
        assert yl.sample_axis is not None
        assert yl.sample_axis.labels == ["Moisture", "Oil"]

    @_skip_no_scp
    @pytest.mark.asyncio
    async def test_mcr_shapes(self, make_node):
        n_samples, n_features, n_components = 20, 50, 2
        ds = _make_spectral_dataset(n_samples=n_samples, n_features=n_features)
        node = make_node("model.mcr_als", {"n_components": n_components})
        result = await node.execute(input_data=ds)

        # C: (n_samples, n_components)
        assert result["default"].shape == (n_samples, n_components)
        # St: (n_components, n_features)
        assert result["St"].shape == (n_components, n_features)

    @_skip_no_scp
    @pytest.mark.asyncio
    async def test_simplisma_shapes(self, make_node):
        n_samples, n_features, n_components = 20, 50, 2
        ds = _make_spectral_dataset(n_samples=n_samples, n_features=n_features)
        node = make_node("model.simplisma", {"n_components": n_components})
        result = await node.execute(input_data=ds)

        # C (concentrations): (n_samples, n_components)
        assert isinstance(result["default"], SherpaDataset)
        assert result["default"].shape == (n_samples, n_components)
        # St (pure spectra): (n_components, n_features)
        assert isinstance(result["spectra"], SherpaDataset)
        assert result["spectra"].shape == (n_components, n_features)

    @_skip_no_scp
    @pytest.mark.asyncio
    async def test_efa_shapes(self, make_node):
        # EFA returns eigenvalues for min(n_samples, n_features) components
        n_samples, n_features = 20, 50
        n_components = n_samples  # EFA computes up to min(n_samples, n_features)
        ds = _make_spectral_dataset(n_samples=n_samples, n_features=n_features)
        node = make_node("model.efa", {"n_components": n_components})
        result = await node.execute(input_data=ds)

        # Forward eigenvalues: (n_samples, n_components)
        fwd = result["forward_eigenvalues"]
        assert isinstance(fwd, SherpaDataset)
        assert fwd.shape[0] == n_samples
        assert fwd.shape[1] == n_components


# ---------------------------------------------------------------------------
# 3. Corn MP5 integration test
# ---------------------------------------------------------------------------


class TestCornMP5Integration:
    """End-to-end: DataSource(corn_mp5) -> PLS(3 comps), all outputs valid."""

    @_skip_no_scp
    @pytest.mark.asyncio
    async def test_corn_mp5_through_pls(self, make_node):
        # Load corn_mp5 dataset
        src = make_node(
            "data.source",
            {"source": "eigenvector", "eigenvector_dataset": "corn_mp5"},
        )
        src_result = await src.execute()
        dataset = src_result["default"]

        # Title should survive NDDataset->SherpaDataset conversion
        assert dataset.title is not None and dataset.title != "<untitled>"

        # Run PLS with 3 components
        pls = make_node("model.pls", {"n_components": 3})
        result = await pls.execute(X=dataset)

        # All output ports should be non-None
        for key in ("default", "X_loadings", "Y_scores", "Y_loadings", "coef"):
            assert result[key] is not None, f"output port '{key}' is None"

        # Canonical shapes
        assert result["default"].shape == (80, 3)  # X scores
        assert result["X_loadings"].shape == (3, 700)  # X loadings
        assert result["Y_scores"].shape == (80, 3)  # Y scores
        assert result["Y_loadings"].shape == (4, 3)  # Y loadings
        assert result["coef"].shape == (700, 4)  # coefficients

        # Y_loadings should carry target names
        yl = result["Y_loadings"]
        assert yl.sample_axis is not None
        assert list(yl.sample_axis.labels) == ["Moisture", "Oil", "Protein", "Starch"]

        # No NDDataset anywhere in results
        _check_no_nddataset(result, "corn_mp5_pls")


# ---------------------------------------------------------------------------
# 4. Explicit algorithm identity on primary outputs
# ---------------------------------------------------------------------------


class TestExplicitOutputTypes:
    """Primary serialized outputs should retain explicit algorithm identity."""

    @_skip_no_scp
    @pytest.mark.asyncio
    async def test_pls_default_output_has_explicit_type(self, make_node):
        ds = _make_spectral_dataset(
            n_samples=30,
            n_features=50,
            n_targets=2,
            target_names=["Moisture", "Oil"],
        )
        node = make_node("model.pls", {"n_components": 2})
        result = await node.execute(X=ds)

        payload = serialize_result(result["default"])
        assert payload["metadata"]["type"] == "PLS"

    @_skip_no_scp
    @pytest.mark.asyncio
    async def test_mcr_default_output_has_explicit_type(self, make_node):
        ds = _make_spectral_dataset(n_samples=20, n_features=50)
        node = make_node("model.mcr_als", {"n_components": 2})
        result = await node.execute(input_data=ds)

        payload = serialize_result(result["default"])
        assert payload["metadata"]["type"] == "MCR_ALS"

    @_skip_no_scp
    @pytest.mark.asyncio
    async def test_simplisma_default_output_has_explicit_type(self, make_node):
        ds = _make_spectral_dataset(n_samples=20, n_features=50)
        node = make_node("model.simplisma", {"n_components": 2})
        result = await node.execute(input_data=ds)

        payload = serialize_result(result["default"])
        assert payload["metadata"]["type"] == "SIMPLISMA"

    @_skip_no_scp
    @pytest.mark.asyncio
    async def test_plsda_default_output_has_explicit_type(self, make_node):
        ds = _make_spectral_dataset(
            n_samples=60,
            n_features=50,
            n_targets=1,
            target_type="categorical",
        )
        node = make_node("classification.plsda", {"n_components": 2, "cv_folds": 3})
        result = await node.execute(X=ds)

        payload = serialize_result(result["default"])
        assert payload["metadata"]["type"] == "PLS_DA"
