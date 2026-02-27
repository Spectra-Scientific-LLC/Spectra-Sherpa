"""Tests for N-dimensional SherpaDataset support.

Covers:
- nD construction (3D LC-MS, 4D hyperspectral)
- SpatialAxis
- Convenience properties (n_samples, n_features, inner_shape, inner_axes, dim_role)
- Flattening protocol (FlattenedView, to_numpy_2d with flatten_nd)
- Serialization wire format v2 (to_dict / from_dict)
- Slicing generalization for nD
- copy() with inner axes
- build_dataset_like with restore_shape
- Backward compatibility: 2D behavior unchanged
"""

from __future__ import annotations

import numpy as np
import pytest

from spectra_sherpa.app.lib.axes import (
    MZAxis,
    SampleAxis,
    SpatialAxis,
    SpectralAxis,
    TimeAxis,
)
from spectra_sherpa.app.lib.sherpa_dataset import SherpaDataset
from spectra_sherpa.app.services.dag.io_contracts import (
    FlattenedView,
    build_dataset_like,
    to_numpy_2d,
)

# ═══════════════════════════════════════════════════════════════════
# SpatialAxis
# ═══════════════════════════════════════════════════════════════════


class TestSpatialAxis:
    def test_um_units(self):
        ax = SpatialAxis(values=np.arange(100.0), units="µm", title="Y")
        assert ax.axis_type == "spatial_um"

    def test_mm_units(self):
        ax = SpatialAxis(values=np.arange(50.0), units="mm", title="X")
        assert ax.axis_type == "spatial_mm"

    def test_pixel_units(self):
        ax = SpatialAxis(values=np.arange(256.0), units="px", title="Pixel X")
        assert ax.axis_type == "spatial_pixel"

    def test_cm_units(self):
        ax = SpatialAxis(values=np.arange(10.0), units="cm", title="Width")
        assert ax.axis_type == "spatial_cm"

    def test_no_units(self):
        ax = SpatialAxis(values=np.arange(100.0))
        assert ax.axis_type is None

    def test_copy(self):
        ax = SpatialAxis(values=np.arange(50.0), units="µm", title="Y")
        cp = ax.copy()
        assert isinstance(cp, SpatialAxis)
        assert cp.axis_type == "spatial_um"
        assert np.array_equal(cp.values, ax.values)
        # Independence
        cp.values[0] = -999
        assert ax.values[0] != -999

    def test_range_and_monotonicity(self):
        ax = SpatialAxis(values=np.linspace(0, 100, 50), units="µm")
        assert ax.range == (0.0, 100.0)
        assert ax.is_monotonic(increasing=True)


# ═══════════════════════════════════════════════════════════════════
# nD Construction
# ═══════════════════════════════════════════════════════════════════


class TestNDConstruction:
    def test_2d_unchanged(self):
        """Existing 2D construction works identically."""
        ds = SherpaDataset(X=np.random.rand(10, 100))
        assert ds.shape == (10, 100)
        assert ds.ndim == 2
        assert ds.n_samples == 10
        assert ds.n_features == 100
        assert ds.inner_shape == ()
        assert ds.inner_axes == {}

    def test_1d_promotion(self):
        """1D input promotes to (1, n)."""
        ds = SherpaDataset(X=np.arange(50.0))
        assert ds.shape == (1, 50)
        assert ds.ndim == 2
        assert ds.n_samples == 1
        assert ds.n_features == 50

    def test_0d_rejected(self):
        with pytest.raises(ValueError, match="at least 1-dimensional"):
            SherpaDataset(X=np.float64(42.0))

    def test_3d_lcms(self):
        """3D LC-MS data: (n_samples, n_timepoints, n_mz)."""
        data = np.random.rand(20, 50, 100)
        ds = SherpaDataset(
            X=data,
            sample_axis=SampleAxis(labels=[f"s{i}" for i in range(20)]),
            axes={1: TimeAxis(values=np.linspace(0, 30, 50), units="min", title="RT")},
            feature_axis=MZAxis(values=np.linspace(100, 1000, 100), units="m/z"),
        )
        assert ds.shape == (20, 50, 100)
        assert ds.ndim == 3
        assert ds.n_samples == 20
        assert ds.n_features == 100
        assert ds.inner_shape == (50,)
        assert isinstance(ds.axis(1), TimeAxis)
        assert ds.get_feature_axis().axis_type == "mass_to_charge"

    def test_4d_hyperspectral(self):
        """4D hyperspectral: (n_samples, height, width, n_wavelengths)."""
        data = np.random.rand(5, 32, 32, 224)
        ds = SherpaDataset(
            X=data,
            axes={
                1: SpatialAxis(values=np.arange(32.0), units="µm", title="Y"),
                2: SpatialAxis(values=np.arange(32.0), units="µm", title="X"),
            },
            feature_axis=SpectralAxis(values=np.linspace(400, 2500, 224), units="nm"),
        )
        assert ds.shape == (5, 32, 32, 224)
        assert ds.ndim == 4
        assert ds.inner_shape == (32, 32)
        assert len(ds.inner_axes) == 2
        assert isinstance(ds.axis(1), SpatialAxis)
        assert isinstance(ds.axis(2), SpatialAxis)

    def test_3d_no_inner_axes(self):
        """3D data without explicit inner axes is valid."""
        ds = SherpaDataset(X=np.random.rand(10, 20, 30))
        assert ds.shape == (10, 20, 30)
        assert ds.inner_shape == (20,)
        assert ds.inner_axes == {}

    def test_axes_dim0_conflict_raises(self):
        """Cannot set inner axis on dim 0."""
        with pytest.raises(ValueError, match="conflicts"):
            SherpaDataset(
                X=np.random.rand(5, 10, 20),
                axes={0: SpatialAxis(values=np.arange(5.0))},
            )

    def test_axes_dim_last_conflict_raises(self):
        """Cannot set inner axis on last dim."""
        with pytest.raises(ValueError, match="conflicts"):
            SherpaDataset(
                X=np.random.rand(5, 10, 20),
                axes={-1: SpatialAxis(values=np.arange(20.0))},
            )

    def test_axes_length_mismatch_raises(self):
        """Inner axis length must match data dimension."""
        with pytest.raises(ValueError, match="mismatch"):
            SherpaDataset(
                X=np.random.rand(5, 10, 20),
                axes={1: TimeAxis(values=np.arange(99.0), units="min")},
            )

    def test_axes_conflicts_with_feature_dim_raises(self):
        """For 2D data, dim 1 IS the feature dim — must use feature_axis= instead."""
        with pytest.raises(ValueError, match="conflicts"):
            SherpaDataset(
                X=np.random.rand(5, 20),
                axes={1: TimeAxis(values=np.arange(20.0), units="min")},
            )

    def test_axes_out_of_range_raises(self):
        """Inner axis dim beyond data dimensions raises error."""
        with pytest.raises(ValueError, match="out of range"):
            SherpaDataset(
                X=np.random.rand(5, 10, 20),
                axes={3: TimeAxis(values=np.arange(10.0), units="min")},
            )

    def test_dim_role(self):
        ds = SherpaDataset(X=np.random.rand(5, 10, 20, 100))
        assert ds.dim_role(0) == "sample"
        assert ds.dim_role(-1) == "feature"
        assert ds.dim_role(3) == "feature"
        assert ds.dim_role(1) == "inner"
        assert ds.dim_role(2) == "inner"

    def test_target_with_nd(self):
        """Target is 1D per sample, regardless of inner dims."""
        data = np.random.rand(15, 20, 100)
        target = np.arange(15.0)
        ds = SherpaDataset(X=data, target=target)
        assert ds.target is not None
        assert ds.target.shape == (15,)


# ═══════════════════════════════════════════════════════════════════
# nD Copy
# ═══════════════════════════════════════════════════════════════════


class TestNDCopy:
    def test_copy_preserves_inner_axes(self):
        ds = SherpaDataset(
            X=np.random.rand(5, 32, 32, 224),
            axes={
                1: SpatialAxis(values=np.arange(32.0), units="µm", title="Y"),
                2: SpatialAxis(values=np.arange(32.0), units="µm", title="X"),
            },
            feature_axis=SpectralAxis(values=np.linspace(400, 2500, 224), units="nm"),
        )
        cp = ds.copy()
        assert cp.shape == ds.shape
        assert isinstance(cp.axis(1), SpatialAxis)
        assert isinstance(cp.axis(2), SpatialAxis)
        assert isinstance(cp.get_feature_axis(), SpectralAxis)
        # Verify independence
        cp._X[0, 0, 0, 0] = -999
        assert ds._X[0, 0, 0, 0] != -999

    def test_copy_2d_still_works(self):
        ds = SherpaDataset(
            X=np.random.rand(10, 100),
            feature_axis=SpectralAxis(values=np.arange(100.0), units="cm-1"),
        )
        cp = ds.copy()
        assert cp.shape == (10, 100)
        assert isinstance(cp.get_feature_axis(), SpectralAxis)


# ═══════════════════════════════════════════════════════════════════
# nD Slicing
# ═══════════════════════════════════════════════════════════════════


class TestNDSlicing:
    @pytest.fixture
    def ds3d(self):
        return SherpaDataset(
            X=np.random.rand(20, 50, 100),
            sample_axis=SampleAxis(labels=[f"s{i}" for i in range(20)]),
            axes={1: TimeAxis(values=np.linspace(0, 30, 50), units="min")},
            feature_axis=MZAxis(values=np.linspace(100, 1000, 100), units="m/z"),
        )

    @pytest.fixture
    def ds4d(self):
        return SherpaDataset(
            X=np.random.rand(5, 32, 32, 224),
            axes={
                1: SpatialAxis(values=np.arange(32.0), units="µm", title="Y"),
                2: SpatialAxis(values=np.arange(32.0), units="µm", title="X"),
            },
            feature_axis=SpectralAxis(values=np.linspace(400, 2500, 224), units="nm"),
        )

    def test_sample_slice_3d(self, ds3d):
        sliced = ds3d[:5]
        assert sliced.shape == (5, 50, 100)
        assert isinstance(sliced.axis(1), TimeAxis)
        assert isinstance(sliced.get_feature_axis(), MZAxis)
        assert sliced.sample_axis is not None
        assert len(sliced.sample_axis.labels) == 5

    def test_sample_int_3d(self, ds3d):
        sliced = ds3d[0]
        assert sliced.shape == (1, 50, 100)
        assert isinstance(sliced.axis(1), TimeAxis)

    def test_bool_mask_3d(self, ds3d):
        mask = np.array([True] * 10 + [False] * 10)
        sliced = ds3d[mask]
        assert sliced.shape == (10, 50, 100)
        assert isinstance(sliced.axis(1), TimeAxis)

    def test_feature_slice_shorthand_3d(self, ds3d):
        """2D shorthand (rows, cols) on 3D data: inner dims pass through."""
        sliced = ds3d[:, 10:20]
        assert sliced.shape == (20, 50, 10)
        assert isinstance(sliced.axis(1), TimeAxis)

    def test_feature_slice_shorthand_4d(self, ds4d):
        sliced = ds4d[:, 50:100]
        assert sliced.shape == (5, 32, 32, 50)

    def test_sample_slice_4d(self, ds4d):
        sliced = ds4d[:3]
        assert sliced.shape == (3, 32, 32, 224)
        assert isinstance(sliced.axis(1), SpatialAxis)
        assert isinstance(sliced.axis(2), SpatialAxis)

    def test_full_nd_slice_3d(self, ds3d):
        """Full 3D indexing: (samples, time, mz)."""
        sliced = ds3d[0:5, 10:20, 30:50]
        assert sliced.shape == (5, 10, 20)

    def test_target_sliced_3d(self):
        data = np.random.rand(20, 50, 100)
        target = np.arange(20.0)
        ds = SherpaDataset(X=data, target=target)
        sliced = ds[:10]
        assert sliced.target is not None
        assert sliced.target.shape == (10,)


# ═══════════════════════════════════════════════════════════════════
# Flattening Protocol
# ═══════════════════════════════════════════════════════════════════


class TestFlattenedView:
    def test_2d_noop(self):
        ds = SherpaDataset(X=np.random.rand(10, 100))
        fv = FlattenedView(ds)
        assert fv.is_2d
        assert fv.flat.shape == (10, 100)
        result = fv.unflatten(fv.flat)
        assert result.shape == (10, 100)

    def test_3d_flatten_unflatten(self):
        data = np.random.rand(20, 50, 100)
        ds = SherpaDataset(X=data)
        fv = FlattenedView(ds)
        assert not fv.is_2d
        assert fv.flat.shape == (20, 5000)
        result = fv.unflatten(fv.flat)
        assert result.shape == (20, 50, 100)
        assert np.allclose(result, data)

    def test_4d_flatten_unflatten(self):
        data = np.random.rand(5, 32, 32, 224)
        ds = SherpaDataset(X=data)
        fv = FlattenedView(ds)
        assert fv.flat.shape == (5, 32 * 32 * 224)
        result = fv.unflatten(fv.flat)
        assert result.shape == (5, 32, 32, 224)

    def test_unflatten_with_changed_features(self):
        """If feature count changed, cannot unflatten — stays 2D."""
        data = np.random.rand(20, 50, 100)
        ds = SherpaDataset(X=data)
        fv = FlattenedView(ds)
        # Simulate a feature-reducing operation (e.g., PCA)
        reduced = fv.flat[:, :10]
        result = fv.unflatten(reduced)
        assert result.shape == (20, 10)  # stays 2D


class TestToNumpy2dFlattenND:
    def test_2d_unchanged(self):
        ds = SherpaDataset(X=np.random.rand(10, 100))
        arr = to_numpy_2d(ds)
        assert arr.shape == (10, 100)

    def test_3d_default_is_fail_fast(self):
        ds = SherpaDataset(X=np.random.rand(20, 50, 100))
        with pytest.raises(ValueError, match="2D"):
            to_numpy_2d(ds)

    def test_3d_explicit_flatten(self):
        ds = SherpaDataset(X=np.random.rand(20, 50, 100))
        arr = to_numpy_2d(ds, flatten_nd=True)
        assert arr.shape == (20, 5000)

    def test_3d_flatten_disabled_raises(self):
        ds = SherpaDataset(X=np.random.rand(20, 50, 100))
        with pytest.raises(ValueError, match="2D"):
            to_numpy_2d(ds, flatten_nd=False)


class TestBuildDatasetLikeRestoreShape:
    def test_restore_3d_shape(self):
        data_3d = np.random.rand(20, 50, 100)
        ds = SherpaDataset(
            X=data_3d,
            axes={1: TimeAxis(values=np.arange(50.0), units="min")},
            feature_axis=MZAxis(values=np.arange(100.0), units="m/z"),
        )
        flat = to_numpy_2d(ds, flatten_nd=True)
        result = build_dataset_like(flat, ds, restore_shape=data_3d.shape)
        assert result.shape == (20, 50, 100)
        assert isinstance(result.axis(1), TimeAxis)
        assert isinstance(result.get_feature_axis(), MZAxis)

    def test_no_restore_stays_2d(self):
        data_3d = np.random.rand(20, 50, 100)
        ds = SherpaDataset(X=data_3d)
        flat = to_numpy_2d(ds, flatten_nd=True)
        result = build_dataset_like(flat, ds)
        assert result.shape == (20, 5000)  # stays flat without restore_shape

    def test_2d_source_no_restore(self):
        ds = SherpaDataset(X=np.random.rand(10, 100))
        processed = ds.X * 2
        result = build_dataset_like(processed, ds)
        assert result.shape == (10, 100)


# ═══════════════════════════════════════════════════════════════════
# Serialization v2
# ═══════════════════════════════════════════════════════════════════


class TestNDSerialization:
    def test_2d_produces_v1(self):
        ds = SherpaDataset(
            X=np.random.rand(10, 50),
            feature_axis=SpectralAxis(values=np.arange(50.0), units="cm-1"),
        )
        d = ds.to_dict()
        assert d["version"] == "1.0"
        assert d["ndim"] == 2
        assert "inner_axes" not in d
        assert "feature_axis" in d

    def test_3d_produces_v2(self):
        data = np.random.rand(5, 30, 100)
        ds = SherpaDataset(
            X=data,
            axes={1: TimeAxis(values=np.arange(30.0), units="min", title="RT")},
            feature_axis=MZAxis(values=np.arange(100.0), units="m/z"),
        )
        d = ds.to_dict()
        assert d["version"] == "2.0"
        assert d["ndim"] == 3
        assert "inner_axes" in d
        assert "1" in d["inner_axes"]
        assert d["inner_axes"]["1"]["axis_class"] == "TimeAxis"
        assert d["feature_axis"]["axis_class"] == "MZAxis"

    def test_roundtrip_2d(self):
        ds = SherpaDataset(
            X=np.random.rand(10, 50),
            feature_axis=SpectralAxis(values=np.arange(50.0), units="cm-1"),
        )
        d = ds.to_dict()
        ds2 = SherpaDataset.from_dict(d)
        assert np.allclose(ds.X, ds2.X)
        assert ds2.shape == (10, 50)
        assert isinstance(ds2.get_feature_axis(), SpectralAxis)

    def test_roundtrip_3d(self):
        data = np.random.rand(5, 30, 100)
        ds = SherpaDataset(
            X=data,
            axes={1: TimeAxis(values=np.arange(30.0), units="min", title="RT")},
            feature_axis=MZAxis(values=np.arange(100.0), units="m/z"),
        )
        d = ds.to_dict()
        ds2 = SherpaDataset.from_dict(d)
        assert ds2.shape == (5, 30, 100)
        assert np.allclose(ds.X, ds2.X)
        assert isinstance(ds2.axis(1), TimeAxis)
        assert isinstance(ds2.get_feature_axis(), MZAxis)

    def test_roundtrip_4d(self):
        data = np.random.rand(3, 16, 16, 50)
        ds = SherpaDataset(
            X=data,
            axes={
                1: SpatialAxis(values=np.arange(16.0), units="µm", title="Y"),
                2: SpatialAxis(values=np.arange(16.0), units="µm", title="X"),
            },
            feature_axis=SpectralAxis(values=np.linspace(400, 2500, 50), units="nm"),
        )
        d = ds.to_dict()
        ds2 = SherpaDataset.from_dict(d)
        assert ds2.shape == (3, 16, 16, 50)
        assert isinstance(ds2.axis(1), SpatialAxis)
        assert isinstance(ds2.axis(2), SpatialAxis)
        assert isinstance(ds2.get_feature_axis(), SpectralAxis)

    def test_v2_format_loads(self):
        """v2 dict with feature_axis loads correctly."""
        v2 = {
            "type": "SherpaDataset",
            "version": "2.0",
            "data": np.random.rand(10, 50).tolist(),
            "shape": [10, 50],
            "n_samples": 10,
            "n_features": 50,
            "backend": "numpy",
            "feature_axis": {
                "axis_class": "SpectralAxis",
                "data": np.arange(50.0).tolist(),
                "units": "cm-1",
                "title": "wavenumber",
            },
        }
        ds = SherpaDataset.from_dict(v2)
        assert ds.shape == (10, 50)
        fa = ds.get_feature_axis()
        assert fa is not None
        assert isinstance(fa, SpectralAxis)


# ═══════════════════════════════════════════════════════════════════
# Edge Cases
# ═══════════════════════════════════════════════════════════════════


class TestNDEdgeCases:
    def test_trivial_inner_dim(self):
        """Shape (5, 1, 100) — trivial inner dimension."""
        ds = SherpaDataset(X=np.random.rand(5, 1, 100))
        assert ds.shape == (5, 1, 100)
        assert ds.inner_shape == (1,)

    def test_single_sample_3d(self):
        ds = SherpaDataset(X=np.random.rand(1, 50, 100))
        assert ds.shape == (1, 50, 100)
        assert ds.n_samples == 1
        assert ds.n_features == 100

    def test_nan_handling_nd(self):
        data = np.random.rand(5, 10, 20)
        data[0, 0, 0] = np.nan
        ds = SherpaDataset(X=data)
        d = ds.to_dict()
        assert d["data"][0][0][0] is None  # NaN → None in JSON
        ds2 = SherpaDataset.from_dict(d)
        assert np.isnan(ds2.X[0, 0, 0])

    def test_no_inner_axes_3d_copy(self):
        """3D data with no axes metadata copies cleanly."""
        ds = SherpaDataset(X=np.random.rand(10, 20, 30))
        cp = ds.copy()
        assert cp.shape == (10, 20, 30)
        assert cp.inner_axes == {}

    def test_feature_axis_setter_on_3d(self):
        ds = SherpaDataset(X=np.random.rand(10, 20, 100))
        ds.feature_axis = SpectralAxis(values=np.arange(100.0), units="nm")
        assert isinstance(ds.get_feature_axis(), SpectralAxis)

    def test_mixed_axis_types(self):
        """dim 1 = TimeAxis, dim 2 = SpatialAxis."""
        ds = SherpaDataset(
            X=np.random.rand(5, 100, 50, 224),
            axes={
                1: TimeAxis(values=np.linspace(0, 60, 100), units="min"),
                2: SpatialAxis(values=np.arange(50.0), units="px"),
            },
            feature_axis=SpectralAxis(values=np.linspace(400, 2500, 224), units="nm"),
        )
        assert ds.dim_role(1) == "inner"
        assert ds.dim_role(2) == "inner"
        assert isinstance(ds.axis(1), TimeAxis)
        assert isinstance(ds.axis(2), SpatialAxis)
