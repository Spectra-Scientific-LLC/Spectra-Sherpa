"""Phase 4: Calibration transfer node tests.

Covers:
- PDS (Piecewise Direct Standardization) — local window regression
- SBC (Slope/Bias Correction) — per-wavelength linear correction
- DS (Direct Standardization) — global transfer matrix
"""

from __future__ import annotations

import numpy as np
import pytest

from spectra_sherpa.app.lib.sherpa_dataset import SherpaDataset, SpectralAxis

# ── Shared Fixtures ───────────────────────────────────────────────────


def _make_instrument_pair(n_transfer=20, n_new=30, n_features=50, seed=42):
    """Simulate two instruments with linear distortion on correlated spectra.

    Uses Gaussian-smoothed random data to mimic real spectral correlation
    between neighbouring wavelengths — essential for PDS to work correctly.
    """
    from scipy.ndimage import gaussian_filter1d

    rng = np.random.RandomState(seed)

    # Create spectrally correlated data (smooth random spectra)
    raw = rng.randn(n_transfer + n_new, n_features)
    X_true = np.array([gaussian_filter1d(row, sigma=3) for row in raw]) + 1.0

    # Secondary instrument distortion: smooth slope and bias (instrument response)
    slope_raw = 1.0 + rng.randn(n_features) * 0.1
    slope = gaussian_filter1d(slope_raw, sigma=2)  # smooth instrument response
    bias_raw = rng.randn(n_features) * 0.05
    bias = gaussian_filter1d(bias_raw, sigma=2)
    noise = rng.randn(n_transfer + n_new, n_features) * 0.005

    X_secondary_all = X_true * slope[np.newaxis, :] + bias[np.newaxis, :] + noise

    wn = np.linspace(400, 4000, n_features)

    X_primary_transfer = SherpaDataset(
        X=X_true[:n_transfer],
        feature_axis=SpectralAxis(values=wn, units="cm-1"),
    )
    X_secondary_transfer = SherpaDataset(
        X=X_secondary_all[:n_transfer],
        feature_axis=SpectralAxis(values=wn, units="cm-1"),
    )
    X_secondary_new = SherpaDataset(
        X=X_secondary_all[n_transfer:],
        feature_axis=SpectralAxis(values=wn, units="cm-1"),
    )
    X_true_new = X_true[n_transfer:]

    return X_primary_transfer, X_secondary_transfer, X_secondary_new, X_true_new


@pytest.fixture
def instrument_pair():
    return _make_instrument_pair()


# ── PDS Tests ─────────────────────────────────────────────────────────


class TestPDSNode:
    """Piecewise Direct Standardization."""

    @pytest.mark.asyncio
    async def test_basic_pds(self, instrument_pair):
        from spectra_sherpa.app.services.dag.nodes.transfer.pds_node import PDSNode

        X_pri, X_sec, X_new, X_true_new = instrument_pair
        node = PDSNode("test_pds", {"half_window": 3, "n_components": 2})
        result = await node.execute(X_primary=X_pri, X_secondary=X_sec, X_new=X_new)

        X_std = result.outputs["X_standardized"]
        assert X_std.X.shape == (30, 50)
        assert result.diagnostics["rmse_transfer"] > 0

    @pytest.mark.asyncio
    async def test_pds_reduces_error(self, instrument_pair):
        """PDS should reduce spectral difference vs no transfer."""
        from spectra_sherpa.app.services.dag.nodes.transfer.pds_node import PDSNode

        # Use more transfer samples for stable PDS
        X_pri, X_sec, X_new, X_true_new = _make_instrument_pair(
            n_transfer=40,
            n_new=20,
            n_features=30,
            seed=42,
        )
        node = PDSNode("test_pds2", {"half_window": 2, "n_components": 1})
        result = await node.execute(X_primary=X_pri, X_secondary=X_sec, X_new=X_new)

        X_std = np.asarray(result.outputs["X_standardized"].X)

        # Error after transfer vs before
        error_before = np.sqrt(np.mean((X_new.X - X_true_new) ** 2))
        error_after = np.sqrt(np.mean((X_std - X_true_new) ** 2))
        assert error_after < error_before, f"PDS should reduce error: {error_after:.4f} >= {error_before:.4f}"

    @pytest.mark.asyncio
    async def test_pds_diagnostics(self, instrument_pair):
        from spectra_sherpa.app.services.dag.nodes.transfer.pds_node import PDSNode

        X_pri, X_sec, X_new, _ = instrument_pair
        node = PDSNode("test_pds3", {"half_window": 3})
        result = await node.execute(X_primary=X_pri, X_secondary=X_sec, X_new=X_new)

        diag = result.outputs["transfer_error"]
        assert "rmse_transfer" in diag
        assert "per_feature_rmse" in diag
        assert len(diag["per_feature_rmse"]) == 50
        assert diag["window_size"] == 7  # 2*3+1

    @pytest.mark.asyncio
    async def test_pds_validates_paired_samples(self, instrument_pair):
        from spectra_sherpa.app.services.dag.nodes.transfer.pds_node import PDSNode

        X_pri, X_sec, X_new, _ = instrument_pair
        # Mismatch sample count
        X_pri_bad = SherpaDataset(X=np.random.randn(10, 50))
        node = PDSNode("test_pds4", {})

        with pytest.raises(ValueError, match="paired"):
            await node.execute(X_primary=X_pri_bad, X_secondary=X_sec, X_new=X_new)

    @pytest.mark.asyncio
    async def test_pds_ols_mode(self, instrument_pair):
        """n_components=0 should use OLS."""
        from spectra_sherpa.app.services.dag.nodes.transfer.pds_node import PDSNode

        X_pri, X_sec, X_new, _ = instrument_pair
        node = PDSNode("test_pds5", {"half_window": 2, "n_components": 0})
        result = await node.execute(X_primary=X_pri, X_secondary=X_sec, X_new=X_new)
        assert result.outputs["X_standardized"].X.shape == (30, 50)


# ── SBC Tests ─────────────────────────────────────────────────────────


class TestSBCNode:
    """Slope/Bias Correction."""

    @pytest.mark.asyncio
    async def test_basic_sbc(self, instrument_pair):
        from spectra_sherpa.app.services.dag.nodes.transfer.sbc_node import SBCNode

        X_pri, X_sec, X_new, _ = instrument_pair
        node = SBCNode("test_sbc", {"method": "sbc"})
        result = await node.execute(X_primary=X_pri, X_secondary=X_sec, X_new=X_new)

        X_std = result.outputs["X_standardized"]
        assert X_std.X.shape == (30, 50)
        assert result.diagnostics["method"] == "sbc"

    @pytest.mark.asyncio
    async def test_sbc_reduces_error(self, instrument_pair):
        """SBC should reduce spectral distortion."""
        from spectra_sherpa.app.services.dag.nodes.transfer.sbc_node import SBCNode

        X_pri, X_sec, X_new, X_true_new = instrument_pair
        node = SBCNode("test_sbc2", {"method": "sbc"})
        result = await node.execute(X_primary=X_pri, X_secondary=X_sec, X_new=X_new)

        X_std = np.asarray(result.outputs["X_standardized"].X)
        error_before = np.sqrt(np.mean((X_new.X - X_true_new) ** 2))
        error_after = np.sqrt(np.mean((X_std - X_true_new) ** 2))
        assert error_after < error_before

    @pytest.mark.asyncio
    async def test_sbc_diagnostics(self, instrument_pair):
        from spectra_sherpa.app.services.dag.nodes.transfer.sbc_node import SBCNode

        X_pri, X_sec, X_new, _ = instrument_pair
        node = SBCNode("test_sbc3", {"method": "sbc"})
        result = await node.execute(X_primary=X_pri, X_secondary=X_sec, X_new=X_new)

        diag = result.outputs["transfer_error"]
        assert "slope_range" in diag
        assert "bias_range" in diag
        assert abs(diag["mean_slope"] - 1.0) < 0.5  # slope should be close to 1

    @pytest.mark.asyncio
    async def test_ds_method(self, instrument_pair):
        """Direct Standardization (global matrix)."""
        from spectra_sherpa.app.services.dag.nodes.transfer.sbc_node import SBCNode

        X_pri, X_sec, X_new, _ = instrument_pair
        node = SBCNode("test_ds", {"method": "ds", "regularization": 1e-4})
        result = await node.execute(X_primary=X_pri, X_secondary=X_sec, X_new=X_new)

        assert result.diagnostics["method"] == "ds"
        assert "matrix_condition" in result.outputs["transfer_error"]

    @pytest.mark.asyncio
    async def test_ds_reduces_error(self, instrument_pair):
        from spectra_sherpa.app.services.dag.nodes.transfer.sbc_node import SBCNode

        X_pri, X_sec, X_new, X_true_new = instrument_pair
        node = SBCNode("test_ds2", {"method": "ds", "regularization": 1e-3})
        result = await node.execute(X_primary=X_pri, X_secondary=X_sec, X_new=X_new)

        X_std = np.asarray(result.outputs["X_standardized"].X)
        error_before = np.sqrt(np.mean((X_new.X - X_true_new) ** 2))
        error_after = np.sqrt(np.mean((X_std - X_true_new) ** 2))
        assert error_after < error_before

    @pytest.mark.asyncio
    async def test_validates_feature_count(self, instrument_pair):
        from spectra_sherpa.app.services.dag.nodes.transfer.sbc_node import SBCNode

        X_pri, X_sec, _, _ = instrument_pair
        X_new_bad = SherpaDataset(X=np.random.randn(10, 30))  # wrong feature count
        node = SBCNode("test_sbc_err", {})

        with pytest.raises(ValueError, match="features"):
            await node.execute(X_primary=X_pri, X_secondary=X_sec, X_new=X_new_bad)


# ── Core Algorithm Tests ──────────────────────────────────────────────


class TestPDSAlgorithm:
    """Low-level PDS fit/transform."""

    def test_perfect_transfer_per_channel(self):
        """With identical instruments and window=0, PDS is identity."""
        from spectra_sherpa.app.services.dag.nodes.transfer.pds_node import _pds_fit, _pds_transform

        rng = np.random.RandomState(42)
        X = rng.randn(20, 30) + 1.0
        transforms = _pds_fit(X, X, half_window=0, n_components=0)
        X_std = _pds_transform(X, transforms)
        np.testing.assert_allclose(X_std, X, atol=1e-5)

    def test_linear_distortion_correlated(self):
        """PDS should correct linear distortion on correlated spectra."""
        from scipy.ndimage import gaussian_filter1d

        from spectra_sherpa.app.services.dag.nodes.transfer.pds_node import _pds_fit, _pds_transform

        rng = np.random.RandomState(42)
        n, p = 40, 30
        raw = rng.randn(n, p)
        X_pri = np.array([gaussian_filter1d(row, sigma=3) for row in raw]) + 1.0
        slope = gaussian_filter1d(1.0 + rng.randn(p) * 0.1, sigma=2)
        bias = gaussian_filter1d(rng.randn(p) * 0.02, sigma=2)
        X_sec = X_pri * slope + bias

        transforms = _pds_fit(X_pri, X_sec, half_window=2, n_components=1)
        X_std = _pds_transform(X_sec, transforms)
        rmse = np.sqrt(np.mean((X_std - X_pri) ** 2))
        assert rmse < 0.1, f"PDS RMSE too high: {rmse}"


class TestSBCAlgorithm:
    """Low-level SBC fit."""

    def test_sbc_recovers_slope_bias(self):
        from spectra_sherpa.app.services.dag.nodes.transfer.sbc_node import _sbc_fit

        rng = np.random.RandomState(42)
        n, p = 30, 10
        X_pri = rng.randn(n, p)
        true_slope = np.array([1.1, 0.95, 1.05, 1.0, 0.9, 1.15, 1.0, 0.98, 1.02, 1.08])
        true_bias = np.array([0.01, -0.02, 0.03, 0.0, -0.01, 0.02, -0.03, 0.01, 0.0, -0.02])
        X_sec = X_pri * true_slope + true_bias

        slope, bias = _sbc_fit(X_pri, X_sec)
        # SBC fits: x_pri = slope * x_sec + bias
        # So slope ≈ 1/true_slope and bias ≈ -true_bias/true_slope (approximately)
        # Actually: we have x_sec = true_slope * x_pri + true_bias
        # SBC fits: x_pri = slope * x_sec + bias
        # So x_pri = slope * (true_slope * x_pri + true_bias) + bias
        # => slope ≈ 1/true_slope, bias ≈ -true_bias * slope
        X_corrected = X_sec * slope + bias
        rmse = np.sqrt(np.mean((X_corrected - X_pri) ** 2))
        assert rmse < 1e-10, f"SBC should perfectly correct linear distortion: {rmse}"

    def test_ds_identity(self):
        """DS with identical instruments should produce near-identity matrix."""
        from spectra_sherpa.app.services.dag.nodes.transfer.sbc_node import _ds_fit

        X = np.random.RandomState(42).randn(30, 15)
        F = _ds_fit(X, X, regularization=1e-8)
        # F should be close to identity
        np.testing.assert_allclose(F, np.eye(15), atol=0.05)
