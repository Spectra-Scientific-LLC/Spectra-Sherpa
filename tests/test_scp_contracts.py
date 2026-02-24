"""
SCP Contract Tests — pin the SpectroChemPy API surface that Sherpa depends on.

These tests fail fast when an SCP upgrade changes return types, attribute names,
or normalization conventions.  Every test is skipped when SCP is not installed.
"""

from __future__ import annotations

import numpy as np
import pytest

from spectra_sherpa.app.lib.scp_compat import HAS_SCP

pytestmark = pytest.mark.skipif(not HAS_SCP, reason="spectrochempy not installed")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def scp():
    import spectrochempy as _scp

    return _scp


@pytest.fixture(scope="module")
def sample_ndd(scp):
    """10 samples x 50 features — generic spectral data."""
    rng = np.random.default_rng(42)
    return scp.NDDataset(rng.standard_normal((10, 50)))


@pytest.fixture(scope="module")
def sample_ndd_positive(scp):
    """10 samples x 50 features — positive values with x and y coords (required by .basc)."""
    from spectrochempy import Coord

    rng = np.random.default_rng(42)
    data = np.abs(rng.standard_normal((10, 50))) + 0.1
    ndd = scp.NDDataset(data)
    ndd.set_coordset(
        x=Coord(np.linspace(4000, 400, 50), units="cm^-1", title="wavenumber"),
        y=Coord(np.arange(10), title="samples"),
    )
    return ndd


# ---------------------------------------------------------------------------
# Preprocessing Contracts
# ---------------------------------------------------------------------------


class TestPreprocessingContracts:
    """Verify SCP preprocessing methods are in-place and row-preserving."""

    def test_basc_is_row_preserving(self, scp, sample_ndd_positive):
        from spectrochempy import Coord

        ndd = scp.NDDataset(sample_ndd_positive.data.copy())
        ndd.set_coordset(
            x=Coord(np.linspace(4000, 400, ndd.shape[1]), units="cm^-1", title="wavenumber"),
            y=Coord(np.arange(ndd.shape[0]), title="samples"),
        )
        original_shape = ndd.shape
        # SCP 0.8.1: basc() returns a new NDDataset (not in-place)
        result = ndd.basc(method="rubberband")
        assert result.shape == original_shape, "basc() must not change shape"
        assert result.shape[0] == original_shape[0], "basc() must preserve row count"

    def test_numpy_msc_is_row_preserving(self):
        """MSC is now pure-numpy (scp.msc removed in SCP 0.8.1). Validate the algorithm."""
        # Synthetic data with known multiplicative scatter: y_i = a_i * ref + b_i + noise
        rng = np.random.default_rng(42)
        true_ref = np.abs(rng.standard_normal(50)) + 1.0
        n_samples = 10
        data = np.zeros((n_samples, 50))
        for i in range(n_samples):
            a = 0.8 + 0.4 * rng.random()  # scale factor
            b = rng.standard_normal() * 0.1  # offset
            data[i] = a * true_ref + b + rng.standard_normal(50) * 0.01

        original_shape = data.shape
        ref = np.mean(data, axis=0)
        A = np.vstack([ref, np.ones(len(ref))]).T
        corrected = np.zeros_like(data)
        for i in range(data.shape[0]):
            m, c = np.linalg.lstsq(A, data[i], rcond=None)[0]
            if abs(m) > 1e-10:
                corrected[i] = (data[i] - c) / m
            else:
                corrected[i] = data[i]
        assert corrected.shape == original_shape, "MSC must not change shape"
        assert corrected.shape[0] == original_shape[0], "MSC must preserve row count"
        assert np.all(np.isfinite(corrected)), "MSC must produce finite values"
        # Corrected spectra should have reduced inter-sample variance
        var_before = np.var(data, axis=0).mean()
        var_after = np.var(corrected, axis=0).mean()
        assert var_after < var_before, "MSC should reduce inter-sample variance from scatter"


# ---------------------------------------------------------------------------
# NDDataset Adapter Contracts
# ---------------------------------------------------------------------------


class TestAdapterContracts:
    """Verify nD coordinate mapping in NDDataset <-> SherpaDataset adapters."""

    def test_from_nddataset_3d_maps_sample_inner_feature_dims(self, scp):
        from spectrochempy import Coord

        from spectra_sherpa.app.lib.adapters.scp_adapter import from_nddataset
        from spectra_sherpa.app.lib.axes import TimeAxis

        rng = np.random.default_rng(7)
        ndd = scp.NDDataset(rng.standard_normal((2, 3, 4)))
        ndd.set_coordset(
            x=Coord(np.linspace(100, 900, 4), units="amu", title="m/z"),
            y=Coord(np.linspace(0, 2, 3), units="min", title="rt"),
            z=Coord(np.arange(2), title="samples"),
        )

        ds = from_nddataset(ndd)
        assert ds.shape == (2, 3, 4)
        assert ds.sample_axis is not None
        assert ds.sample_axis.length == 2
        assert isinstance(ds.axis(1), TimeAxis)
        assert ds.axis(1).length == 3
        assert ds.get_feature_axis() is not None
        assert ds.get_feature_axis().length == 4

    def test_roundtrip_4d_preserves_dimension_roles(self, scp):
        from spectra_sherpa.app.lib.adapters.scp_adapter import from_nddataset, to_nddataset
        from spectra_sherpa.app.lib.axes import SampleAxis, SpatialAxis, SpectralAxis, TimeAxis
        from spectra_sherpa.app.lib.sherpa_dataset import SherpaDataset

        ds = SherpaDataset(
            X=np.random.default_rng(11).standard_normal((2, 3, 4, 5)),
            sample_axis=SampleAxis(values=np.arange(2), title="sample axis"),
            axes={
                1: TimeAxis(values=np.linspace(0, 1, 3), units="min", title="rt"),
                2: SpatialAxis(values=np.arange(4), units="px", title="x-px"),
            },
            feature_axis=SpectralAxis(values=np.linspace(400, 800, 5), units="nm", title="wavelength"),
        )

        ndd = to_nddataset(ds)
        dim_names = [str(name) for name in ndd.dims]
        assert len(dim_names) == 4
        assert getattr(ndd, dim_names[0]).size == 2
        assert str(getattr(ndd, dim_names[0]).title) == "sample axis"
        assert getattr(ndd, dim_names[1]).size == 3
        assert str(getattr(ndd, dim_names[1]).title) == "rt"
        assert getattr(ndd, dim_names[2]).size == 4
        assert str(getattr(ndd, dim_names[2]).title) == "x-px"
        assert getattr(ndd, dim_names[3]).size == 5
        assert str(getattr(ndd, dim_names[3]).title) == "wavelength"

        back = from_nddataset(ndd)
        assert back.shape == (2, 3, 4, 5)
        assert back.sample_axis is not None
        assert back.sample_axis.length == 2
        assert back.axis(1).length == 3
        assert back.axis(2).length == 4
        assert back.get_feature_axis() is not None
        assert back.get_feature_axis().length == 5


# ---------------------------------------------------------------------------
# PCA Contracts
# ---------------------------------------------------------------------------


class TestPCAContracts:
    """Verify SCP PCA return types and attribute names."""

    @pytest.fixture()
    def fitted_pca(self, scp, sample_ndd):
        pca = scp.PCA(n_components=3)
        pca.fit(sample_ndd)
        return pca, sample_ndd

    def test_pca_transform_returns_nddataset(self, scp, fitted_pca):
        pca, input_ndd = fitted_pca
        result = pca.transform()
        assert isinstance(result, scp.NDDataset), f"PCA.transform() must return NDDataset, got {type(result).__name__}"
        assert result.shape[0] == input_ndd.shape[0], "PCA.transform() must preserve row count"

    def test_pca_components_is_nddataset(self, scp, fitted_pca):
        pca, _ = fitted_pca
        components = pca.components
        assert isinstance(
            components, scp.NDDataset
        ), f"PCA.components must be NDDataset, got {type(components).__name__}"

    def test_pca_evr_is_extractable(self, fitted_pca):
        pca, _ = fitted_pca
        evr = pca.explained_variance_ratio
        assert evr is not None, "PCA must expose explained_variance_ratio"
        # Must be extractable as numpy array
        data = evr.data if hasattr(evr, "data") else np.asarray(evr)
        assert isinstance(data, np.ndarray), "EVR .data must be a numpy array"
        assert len(data) > 0, "EVR must have at least one element"

    def test_pca_transform_preserves_rows_on_new_data(self, scp, fitted_pca):
        pca, _ = fitted_pca
        rng = np.random.default_rng(99)
        new_data = scp.NDDataset(rng.standard_normal((5, 50)))
        result = pca.transform(new_data)
        assert result.shape[0] == 5, "PCA.transform(new_data) must preserve input row count"

    def test_pca_evr_is_ratio_not_percentage(self, scp, sample_ndd):
        """Verify EVR normalization contract — SCP returns percentages, we need ratios.

        This pins the normalization contract. If SCP changes to return 0-1 ratios
        instead of 0-100 percentages, PCAExtract.from_scp() will need updating.
        """
        pca = scp.PCA(n_components=3)
        pca.fit(sample_ndd)
        evr = pca.explained_variance_ratio
        evr_data = evr.data if hasattr(evr, "data") else np.asarray(evr)

        # Pin current SCP behavior: returns percentages (0-100)
        # If this assertion fails, SCP changed its API — update PCAExtract.from_scp()
        assert evr_data.max() > 1.0, (
            "SCP API changed: EVR is now a ratio (0-1) instead of percentage (0-100). "
            f"Got max={evr_data.max():.2f}. Update PCAExtract.from_scp() to remove "
            "normalization logic."
        )
        assert evr_data.min() >= 0.0, f"EVR must be non-negative. Got min={evr_data.min():.2f}"

        # Verify our extractor normalizes it correctly
        from spectra_sherpa.app.lib.adapters.scp_extractors import PCAExtract

        extracted = PCAExtract.from_scp(pca, sample_ndd)
        assert extracted.explained_variance_ratio.max() <= 1.0, (
            "PCAExtract.from_scp() failed to normalize EVR to 0-1 ratio. "
            f"Got max={extracted.explained_variance_ratio.max():.2f}"
        )
        assert extracted.explained_variance_ratio.min() >= 0.0, (
            f"PCAExtract EVR must be non-negative. " f"Got min={extracted.explained_variance_ratio.min():.2f}"
        )


# ---------------------------------------------------------------------------
# PLS Contracts
# ---------------------------------------------------------------------------


class TestPLSContracts:
    """Verify SCP PLS return types and attribute names."""

    @pytest.fixture()
    def fitted_pls(self, scp, sample_ndd):
        y = scp.NDDataset(np.random.default_rng(42).standard_normal((10, 1)))
        pls = scp.PLSRegression(n_components=2)
        pls.fit(sample_ndd, y)
        return pls, sample_ndd, y

    def test_pls_fit_predict_preserves_rows(self, scp, fitted_pls):
        pls, input_ndd, _ = fitted_pls
        y_pred = pls.predict(input_ndd)
        pred_data = y_pred.data if hasattr(y_pred, "data") else np.asarray(y_pred)
        assert pred_data.shape[0] == input_ndd.shape[0], "PLS.predict() must preserve row count"

    def test_pls_has_transform(self, fitted_pls):
        pls, _, _ = fitted_pls
        assert hasattr(pls, "transform"), "PLS must have transform() method"


# ---------------------------------------------------------------------------
# MCR-ALS Contracts
# ---------------------------------------------------------------------------


class TestMCRALSContracts:
    """Verify SCP MCR-ALS return types."""

    def test_mcrals_c_preserves_rows(self, scp):
        rng = np.random.default_rng(42)
        data = np.abs(rng.standard_normal((10, 50))) + 0.1
        ndd = scp.NDDataset(data)
        n_components = 2

        # Initial C guess
        from numpy.linalg import svd

        U, S, _ = svd(data, full_matrices=False)
        C0 = scp.NDDataset(np.abs(U[:, :n_components] @ np.diag(S[:n_components])))

        mcr = scp.MCRALS(max_iter=10, tol=0.5)
        mcr.fit(ndd, C0)

        C_data = mcr.C.data if hasattr(mcr.C, "data") else np.asarray(mcr.C)
        assert C_data.shape[0] == 10, "MCR C matrix must preserve input row count"


# ---------------------------------------------------------------------------
# EFA Contracts
# ---------------------------------------------------------------------------


class TestEFAContracts:
    """Verify SCP EFA return types."""

    def test_efa_fit_returns_eigenvalues(self, scp, sample_ndd):
        efa = scp.EFA(n_components=2)
        efa.fit(sample_ndd)
        assert hasattr(efa, "f_ev"), "EFA must have f_ev (forward eigenvalues)"
        assert hasattr(efa, "b_ev"), "EFA must have b_ev (backward eigenvalues)"


# ---------------------------------------------------------------------------
# SIMPLISMA Contracts
# ---------------------------------------------------------------------------


class TestSIMPLISMAContracts:
    """Verify SCP SIMPLISMA return types."""

    def test_simplisma_fit_returns_c(self, scp):
        rng = np.random.default_rng(42)
        data = np.abs(rng.standard_normal((10, 50))) + 0.1
        ndd = scp.NDDataset(data)
        simplisma = scp.SIMPLISMA(n_components=2)
        simplisma.fit(ndd)
        assert hasattr(simplisma, "C"), "SIMPLISMA must have C attribute"


# ---------------------------------------------------------------------------
# NDDataset Core Contracts
# ---------------------------------------------------------------------------


class TestNDDatasetContracts:
    """Verify core NDDataset behaviors that Sherpa depends on."""

    def test_nddataset_coord_assignment(self, scp):
        ndd = scp.NDDataset(np.random.default_rng(42).standard_normal((3, 5)))
        coord = scp.Coord(np.linspace(400, 4000, 5), title="wavenumber")
        ndd.x = coord
        assert ndd.x is not None, "Coord x assignment must stick"
        assert ndd.x.title == "wavenumber"

    def test_nddataset_meta_round_trip(self, scp):
        ndd = scp.NDDataset(np.ones((2, 3)))
        ndd.meta = {"key1": "value1", "key2": [1, 2, 3]}
        assert ndd.meta["key1"] == "value1", "meta dict must survive set/get"
        assert ndd.meta["key2"] == [1, 2, 3], "meta list values must survive"

    def test_nddataset_data_is_numpy(self, scp):
        arr = np.ones((3, 5))
        ndd = scp.NDDataset(arr)
        assert isinstance(ndd.data, np.ndarray), f"NDDataset.data must be numpy array, got {type(ndd.data).__name__}"

    def test_nddataset_shape_and_ndim(self, scp):
        ndd = scp.NDDataset(np.ones((4, 6)))
        assert ndd.shape == (4, 6)
        assert ndd.ndim == 2
