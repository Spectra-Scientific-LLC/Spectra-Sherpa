"""Tests for AnalysisDataset and AxisInfo.

Run with:
    PYTHONPATH=src/spectra_sherpa python -m pytest tests/test_analysis_dataset.py -v --no-cov
"""

from types import SimpleNamespace

import numpy as np
import pytest

from spectra_sherpa.app.lib.analysis_dataset import AnalysisDataset, AxisInfo, from_sklearn_bunch


# ===========================================================================
# AxisInfo
# ===========================================================================


class TestAxisInfoConstruction:
    """AxisInfo dataclass — creation, properties, len, copy."""

    def test_defaults(self):
        ai = AxisInfo()
        assert ai.values is None
        assert ai.labels is None
        assert ai.units is None
        assert ai.title is None

    def test_with_values(self):
        vals = np.array([1.0, 2.0, 3.0])
        ai = AxisInfo(values=vals, units="cm^-1", title="wavenumber")
        np.testing.assert_array_equal(ai.values, vals)
        assert ai.units == "cm^-1"
        assert ai.title == "wavenumber"

    def test_with_labels(self):
        ai = AxisInfo(labels=["a", "b", "c"])
        assert ai.labels == ["a", "b", "c"]
        assert ai.values is None


class TestAxisInfoDataProperty:
    """.data is an alias for .values (Coord compatibility)."""

    def test_data_returns_values(self):
        vals = np.array([10.0, 20.0])
        ai = AxisInfo(values=vals)
        assert ai.data is ai.values

    def test_data_none_when_values_none(self):
        ai = AxisInfo()
        assert ai.data is None


class TestAxisInfoShape:
    def test_shape_with_values(self):
        ai = AxisInfo(values=np.zeros(5))
        assert ai.shape == (5,)

    def test_shape_empty_when_no_values(self):
        ai = AxisInfo(labels=["x"])
        assert ai.shape == ()


class TestAxisInfoLen:
    def test_len_from_values(self):
        ai = AxisInfo(values=np.arange(4))
        assert len(ai) == 4

    def test_len_from_labels_when_no_values(self):
        ai = AxisInfo(labels=["a", "b"])
        assert len(ai) == 2

    def test_len_zero_when_empty(self):
        ai = AxisInfo()
        assert len(ai) == 0

    def test_len_prefers_values_over_labels(self):
        """When both are present, values length is returned."""
        ai = AxisInfo(values=np.arange(3), labels=["a", "b"])
        assert len(ai) == 3


class TestAxisInfoCopy:
    def test_copy_returns_new_instance(self):
        ai = AxisInfo(values=np.array([1.0, 2.0]), labels=["a", "b"], units="nm", title="x")
        cp = ai.copy()
        assert cp is not ai

    def test_copy_values_independent(self):
        ai = AxisInfo(values=np.array([1.0, 2.0]))
        cp = ai.copy()
        cp.values[0] = 999.0
        assert ai.values[0] == 1.0, "Mutating copy must not affect original"

    def test_copy_labels_independent(self):
        ai = AxisInfo(labels=["a", "b"])
        cp = ai.copy()
        cp.labels[0] = "z"
        assert ai.labels[0] == "a"

    def test_copy_preserves_scalars(self):
        ai = AxisInfo(units="cm^-1", title="wavenumber")
        cp = ai.copy()
        assert cp.units == "cm^-1"
        assert cp.title == "wavenumber"

    def test_copy_none_fields(self):
        ai = AxisInfo()
        cp = ai.copy()
        assert cp.values is None
        assert cp.labels is None


# ===========================================================================
# AnalysisDataset — construction
# ===========================================================================


class TestAnalysisDatasetConstruction:
    def test_2d_array(self):
        X = np.array([[1, 2], [3, 4]])
        ds = AnalysisDataset(X)
        assert ds.X.shape == (2, 2)
        assert ds.X.dtype == np.float64

    def test_1d_array_promoted_to_2d(self):
        ds = AnalysisDataset([1, 2, 3])
        assert ds.X.ndim == 2
        assert ds.X.shape == (1, 3)

    def test_list_of_lists(self):
        ds = AnalysisDataset([[1, 2], [3, 4], [5, 6]])
        assert ds.X.shape == (3, 2)
        assert ds.X.dtype == np.float64

    def test_defaults(self):
        ds = AnalysisDataset(np.zeros((2, 3)))
        assert ds.x_axis is None
        assert ds.y_axis is None
        assert ds.target is None
        assert ds.meta == {"processing_history": []}
        assert ds.provenance == []
        assert ds.backend == "numpy"
        assert ds.title is None
        assert ds.units is None

    def test_custom_params(self):
        x_ax = AxisInfo(values=np.arange(5))
        y_ax = AxisInfo(labels=["s1", "s2"])
        ds = AnalysisDataset(
            np.zeros((2, 5)),
            x_axis=x_ax,
            y_axis=y_ax,
            target=np.array([0, 1]),
            meta={"foo": "bar"},
            provenance=[{"step": "test"}],
            backend="sklearn",
            title="Test Dataset",
            units="absorbance",
        )
        assert ds.x_axis is x_ax
        assert ds.y_axis is y_ax
        np.testing.assert_array_equal(ds.target, [0, 1])
        assert ds.meta["foo"] == "bar"
        assert ds.provenance == [{"step": "test"}]
        assert ds.backend == "sklearn"
        assert ds.title == "Test Dataset"
        assert ds.units == "absorbance"


# ===========================================================================
# AnalysisDataset — properties
# ===========================================================================


class TestAnalysisDatasetProperties:
    def test_data_is_X(self):
        ds = AnalysisDataset(np.ones((3, 4)))
        assert ds.data is ds.X

    def test_shape(self):
        ds = AnalysisDataset(np.zeros((5, 10)))
        assert ds.shape == (5, 10)

    def test_ndim(self):
        ds = AnalysisDataset(np.zeros((5, 10)))
        assert ds.ndim == 2

    def test_x_property_returns_x_axis(self):
        ax = AxisInfo(values=np.arange(3))
        ds = AnalysisDataset(np.zeros((2, 3)), x_axis=ax)
        assert ds.x is ax

    def test_y_property_returns_y_axis(self):
        ax = AxisInfo(labels=["a", "b"])
        ds = AnalysisDataset(np.zeros((2, 3)), y_axis=ax)
        assert ds.y is ax


# ===========================================================================
# AnalysisDataset — x/y setters
# ===========================================================================


class TestAnalysisDatasetSetters:
    def test_set_x_with_axis_info(self):
        ds = AnalysisDataset(np.zeros((2, 3)))
        ax = AxisInfo(values=np.array([100, 200, 300]))
        ds.x = ax
        assert ds.x is ax
        assert ds.x_axis is ax

    def test_set_x_to_none(self):
        ds = AnalysisDataset(np.zeros((2, 3)), x_axis=AxisInfo(values=np.arange(3)))
        ds.x = None
        assert ds.x is None

    def test_set_y_with_axis_info(self):
        ds = AnalysisDataset(np.zeros((2, 3)))
        ax = AxisInfo(labels=["s1", "s2"])
        ds.y = ax
        assert ds.y is ax

    def test_set_y_to_none(self):
        ds = AnalysisDataset(np.zeros((2, 3)), y_axis=AxisInfo(labels=["a", "b"]))
        ds.y = None
        assert ds.y is None

    def test_set_x_with_coord_like_object(self):
        """A Coord-like object (has .data, .units, .title, .labels) is converted."""
        coord = SimpleNamespace(
            data=np.array([1.0, 2.0, 3.0]),
            units="cm^-1",
            title="wavenumber",
            labels=["a", "b", "c"],
        )
        ds = AnalysisDataset(np.zeros((2, 3)))
        ds.x = coord
        assert isinstance(ds.x_axis, AxisInfo)
        np.testing.assert_array_equal(ds.x_axis.values, [1.0, 2.0, 3.0])
        assert ds.x_axis.units == "cm^-1"
        assert ds.x_axis.title == "wavenumber"
        assert ds.x_axis.labels == ["a", "b", "c"]

    def test_set_y_with_coord_like_object(self):
        coord = SimpleNamespace(
            data=np.array([0, 1]),
            units=None,
            title="samples",
            labels=None,
        )
        ds = AnalysisDataset(np.zeros((2, 3)))
        ds.y = coord
        assert isinstance(ds.y_axis, AxisInfo)
        np.testing.assert_array_equal(ds.y_axis.values, [0, 1])

    def test_set_x_with_invalid_type_raises(self):
        ds = AnalysisDataset(np.zeros((2, 3)))
        with pytest.raises(TypeError, match="Cannot assign"):
            ds.x = "not an axis"

    def test_set_y_with_invalid_type_raises(self):
        ds = AnalysisDataset(np.zeros((2, 3)))
        with pytest.raises(TypeError, match="Cannot assign"):
            ds.y = 42


# ===========================================================================
# AnalysisDataset — .copy()
# ===========================================================================


class TestAnalysisDatasetCopy:
    def _make_ds(self):
        return AnalysisDataset(
            X=np.array([[1.0, 2.0], [3.0, 4.0]]),
            x_axis=AxisInfo(values=np.array([10.0, 20.0]), labels=["f1", "f2"], units="nm", title="wl"),
            y_axis=AxisInfo(values=np.array([0.0, 1.0]), labels=["s1", "s2"]),
            target=np.array([0, 1]),
            meta={"custom_key": "value"},
            provenance=[{"step": "load"}],
            backend="numpy",
            title="original",
            units="absorbance",
        )

    def test_copy_returns_new_instance(self):
        ds = self._make_ds()
        cp = ds.copy()
        assert cp is not ds

    def test_copy_X_independent(self):
        ds = self._make_ds()
        cp = ds.copy()
        cp.X[0, 0] = 999.0
        assert ds.X[0, 0] == 1.0

    def test_copy_x_axis_independent(self):
        ds = self._make_ds()
        cp = ds.copy()
        cp.x_axis.values[0] = 999.0
        assert ds.x_axis.values[0] == 10.0

    def test_copy_y_axis_independent(self):
        ds = self._make_ds()
        cp = ds.copy()
        cp.y_axis.labels[0] = "CHANGED"
        assert ds.y_axis.labels[0] == "s1"

    def test_copy_target_independent(self):
        ds = self._make_ds()
        cp = ds.copy()
        cp.target[0] = 999
        assert ds.target[0] == 0

    def test_copy_meta_independent(self):
        ds = self._make_ds()
        cp = ds.copy()
        cp.meta["custom_key"] = "CHANGED"
        assert ds.meta["custom_key"] == "value"

    def test_copy_provenance_independent(self):
        ds = self._make_ds()
        cp = ds.copy()
        cp.provenance.append({"step": "new_step"})
        assert len(ds.provenance) == 1

    def test_copy_preserves_scalar_fields(self):
        ds = self._make_ds()
        cp = ds.copy()
        assert cp.backend == "numpy"
        assert cp.title == "original"
        assert cp.units == "absorbance"

    def test_copy_meta_processing_history_in_sync(self):
        """After copy, meta['processing_history'] IS provenance (same list object)."""
        ds = self._make_ds()
        cp = ds.copy()
        assert cp.meta["processing_history"] is cp.provenance

    def test_copy_with_list_target(self):
        ds = AnalysisDataset(
            X=np.zeros((3, 2)),
            target=["a", "b", "c"],
        )
        cp = ds.copy()
        cp.target[0] = "CHANGED"
        assert ds.target[0] == "a"

    def test_copy_with_none_axes(self):
        ds = AnalysisDataset(np.zeros((2, 3)))
        cp = ds.copy()
        assert cp.x_axis is None
        assert cp.y_axis is None
        assert cp.target is None


# ===========================================================================
# AnalysisDataset — __getitem__
# ===========================================================================


class TestAnalysisDatasetGetitem:
    def _make_ds(self):
        X = np.arange(20, dtype=float).reshape(4, 5)
        return AnalysisDataset(
            X=X,
            x_axis=AxisInfo(values=np.array([100, 200, 300, 400, 500]), labels=["f0", "f1", "f2", "f3", "f4"]),
            y_axis=AxisInfo(values=np.arange(4, dtype=float), labels=["s0", "s1", "s2", "s3"]),
            target=np.array([0, 1, 0, 1]),
            backend="numpy",
            title="indexed",
        )

    # -- boolean mask --------------------------------------------------------

    def test_bool_mask_rows(self):
        ds = self._make_ds()
        mask = np.array([True, False, True, False])
        result = ds[mask]
        assert result.shape == (2, 5)
        np.testing.assert_array_equal(result.X[0], ds.X[0])
        np.testing.assert_array_equal(result.X[1], ds.X[2])

    def test_bool_mask_slices_y_axis(self):
        ds = self._make_ds()
        mask = np.array([True, False, True, False])
        result = ds[mask]
        assert result.y_axis is not None
        assert result.y_axis.labels == ["s0", "s2"]
        np.testing.assert_array_equal(result.y_axis.values, [0.0, 2.0])

    def test_bool_mask_preserves_x_axis(self):
        ds = self._make_ds()
        mask = np.array([True, False, True, False])
        result = ds[mask]
        assert result.x_axis is not None
        np.testing.assert_array_equal(result.x_axis.values, ds.x_axis.values)

    def test_bool_mask_slices_target(self):
        ds = self._make_ds()
        mask = np.array([False, True, False, True])
        result = ds[mask]
        np.testing.assert_array_equal(result.target, [1, 1])

    # -- integer index -------------------------------------------------------

    def test_int_index_single_row(self):
        ds = self._make_ds()
        result = ds[2]
        assert result.shape == (1, 5), "Single row stays 2-D"
        np.testing.assert_array_equal(result.X[0], ds.X[2])

    def test_int_index_slices_y_axis(self):
        ds = self._make_ds()
        result = ds[1]
        assert result.y_axis is not None
        assert result.y_axis.labels == ["s1"]

    def test_int_index_preserves_x_axis(self):
        ds = self._make_ds()
        result = ds[0]
        assert result.x_axis is not None
        np.testing.assert_array_equal(result.x_axis.values, ds.x_axis.values)

    # -- tuple slice ---------------------------------------------------------

    def test_tuple_row_col_slice(self):
        ds = self._make_ds()
        result = ds[:, 1:4]
        assert result.shape == (4, 3)
        np.testing.assert_array_equal(result.X, ds.X[:, 1:4])

    def test_tuple_slice_x_axis(self):
        ds = self._make_ds()
        result = ds[:, 1:3]
        assert result.x_axis is not None
        np.testing.assert_array_equal(result.x_axis.values, [200, 300])
        assert result.x_axis.labels == ["f1", "f2"]

    def test_tuple_slice_y_axis_unchanged_for_all_rows(self):
        ds = self._make_ds()
        result = ds[:, 1:3]
        assert result.y_axis is not None
        assert result.y_axis.labels == ["s0", "s1", "s2", "s3"]

    def test_tuple_row_slice_and_col_slice(self):
        ds = self._make_ds()
        result = ds[0:2, 1:4]
        assert result.shape == (2, 3)
        np.testing.assert_array_equal(result.X, ds.X[0:2, 1:4])

    # -- deep copy of meta on slice ------------------------------------------

    def test_getitem_deep_copies_meta(self):
        ds = self._make_ds()
        ds.meta["key"] = "original"
        result = ds[0]
        result.meta["key"] = "changed"
        assert ds.meta["key"] == "original"

    def test_getitem_deep_copies_provenance(self):
        ds = self._make_ds()
        ds.provenance.append({"step": "test"})
        result = ds[0]
        result.provenance.append({"step": "new"})
        assert len(ds.provenance) == 1


# ===========================================================================
# AnalysisDataset — set_coordset
# ===========================================================================


class TestSetCoordset:
    def test_set_x_only(self):
        ds = AnalysisDataset(np.zeros((2, 3)))
        ax = AxisInfo(values=np.arange(3))
        ds.set_coordset(x=ax)
        assert ds.x is ax
        assert ds.y is None

    def test_set_y_only(self):
        ds = AnalysisDataset(np.zeros((2, 3)))
        ax = AxisInfo(labels=["a", "b"])
        ds.set_coordset(y=ax)
        assert ds.y is ax
        assert ds.x is None

    def test_set_both(self):
        ds = AnalysisDataset(np.zeros((2, 3)))
        x_ax = AxisInfo(values=np.arange(3))
        y_ax = AxisInfo(labels=["a", "b"])
        ds.set_coordset(x=x_ax, y=y_ax)
        assert ds.x is x_ax
        assert ds.y is y_ax

    def test_set_coordset_with_coord_like(self):
        coord = SimpleNamespace(
            data=np.array([1.0, 2.0, 3.0]),
            units="nm",
            title="wavelength",
            labels=None,
        )
        ds = AnalysisDataset(np.zeros((2, 3)))
        ds.set_coordset(x=coord)
        assert isinstance(ds.x_axis, AxisInfo)
        np.testing.assert_array_equal(ds.x_axis.values, [1.0, 2.0, 3.0])


# ===========================================================================
# AnalysisDataset — to_dict() wire format
# ===========================================================================


class TestToDict:
    def _make_ds(self):
        return AnalysisDataset(
            X=np.array([[1.0, 2.0, 3.0], [4.0, 5.0, 6.0]]),
            x_axis=AxisInfo(values=np.array([100.0, 200.0, 300.0]), labels=["a", "b", "c"], units="cm^-1", title="wavenumber"),
            y_axis=AxisInfo(values=np.array([0.0, 1.0]), labels=["s1", "s2"], units=None, title="samples"),
            target=np.array([0, 1]),
            meta={"custom": "value"},
            provenance=[{"step": "load", "params": {}}],
            backend="numpy",
            title="Test",
            units="absorbance",
        )

    def test_type_field(self):
        d = self._make_ds().to_dict()
        assert d["type"] == "NDDataset"

    def test_n_samples_and_n_features(self):
        d = self._make_ds().to_dict()
        assert d["n_samples"] == 2
        assert d["n_features"] == 3

    def test_shape_field(self):
        d = self._make_ds().to_dict()
        assert d["shape"] == [2, 3]

    def test_data_field_is_nested_list(self):
        d = self._make_ds().to_dict()
        assert d["data"] == [[1.0, 2.0, 3.0], [4.0, 5.0, 6.0]]

    def test_x_axis_uses_data_key(self):
        """Frontend expects x_axis.data, NOT x_axis.values."""
        d = self._make_ds().to_dict()
        assert "data" in d["x_axis"]
        assert "values" not in d["x_axis"]
        assert d["x_axis"]["data"] == [100.0, 200.0, 300.0]

    def test_x_axis_metadata(self):
        d = self._make_ds().to_dict()
        assert d["x_axis"]["labels"] == ["a", "b", "c"]
        assert d["x_axis"]["units"] == "cm^-1"
        assert d["x_axis"]["title"] == "wavenumber"

    def test_y_axis_present(self):
        d = self._make_ds().to_dict()
        assert "y_axis" in d
        assert d["y_axis"]["data"] == [0.0, 1.0]
        assert d["y_axis"]["labels"] == ["s1", "s2"]

    def test_target_serialized(self):
        d = self._make_ds().to_dict()
        assert d["target"] == [0, 1]

    def test_metadata_dict(self):
        d = self._make_ds().to_dict()
        assert "metadata" in d
        assert isinstance(d["metadata"], dict)

    def test_metadata_contains_processing_history(self):
        d = self._make_ds().to_dict()
        assert d["metadata"]["processing_history"] == [{"step": "load", "params": {}}]

    def test_metadata_contains_data_type(self):
        d = self._make_ds().to_dict()
        assert d["metadata"]["data_type"] == "generic"

    def test_metadata_contains_is_spectra(self):
        d = self._make_ds().to_dict()
        assert d["metadata"]["is_spectra"] is False

    def test_metadata_contains_custom_fields(self):
        d = self._make_ds().to_dict()
        assert d["metadata"]["custom"] == "value"

    def test_title_and_units(self):
        d = self._make_ds().to_dict()
        assert d["title"] == "Test"
        assert d["units"] == "absorbance"

    def test_nan_inf_sanitized_to_none(self):
        """NaN and Inf values in data must become None for JSON safety."""
        ds = AnalysisDataset(X=np.array([[1.0, float("nan"), float("inf")]]))
        d = ds.to_dict()
        row = d["data"][0]
        assert row[0] == 1.0
        assert row[1] is None  # NaN → None
        assert row[2] is None  # Inf → None

    def test_metadata_datetime_serialized(self):
        """datetime values in metadata must be JSON-serialized to ISO strings."""
        from datetime import datetime
        ts = datetime(2026, 2, 13, 10, 30, 0)
        ds = AnalysisDataset(
            X=np.zeros((2, 3)),
            provenance=[{"step": "load", "timestamp": ts}],
        )
        d = ds.to_dict()
        step = d["metadata"]["processing_history"][0]
        assert step["timestamp"] == "2026-02-13T10:30:00"

    def test_metadata_numpy_types_serialized(self):
        """numpy scalar types in metadata must be JSON-serialized to native Python types."""
        ds = AnalysisDataset(
            X=np.zeros((2, 3)),
            meta={"count": np.int64(42), "score": np.float64(3.14)},
        )
        d = ds.to_dict()
        assert d["metadata"]["count"] == 42
        assert isinstance(d["metadata"]["count"], int)
        assert d["metadata"]["score"] == 3.14
        assert isinstance(d["metadata"]["score"], float)

    def test_backend_field(self):
        d = self._make_ds().to_dict()
        assert d["backend"] == "numpy"

    def test_no_axes_omitted(self):
        ds = AnalysisDataset(np.zeros((2, 3)))
        d = ds.to_dict()
        assert "x_axis" not in d
        assert "y_axis" not in d

    def test_no_target_omitted(self):
        ds = AnalysisDataset(np.zeros((2, 3)))
        d = ds.to_dict()
        assert "target" not in d

    def test_target_list_serialized(self):
        ds = AnalysisDataset(np.zeros((2, 3)), target=["cat", "dog"])
        d = ds.to_dict()
        assert d["target"] == ["cat", "dog"]

    def test_default_title_is_data(self):
        ds = AnalysisDataset(np.zeros((2, 3)))
        d = ds.to_dict()
        assert d["title"] == "Data"


# ===========================================================================
# AnalysisDataset — from_dict() deserialization
# ===========================================================================


class TestFromDict:
    def test_round_trip(self):
        original = AnalysisDataset(
            X=np.array([[1.0, 2.0], [3.0, 4.0]]),
            x_axis=AxisInfo(values=np.array([10.0, 20.0]), labels=["f1", "f2"], units="nm", title="wl"),
            y_axis=AxisInfo(values=np.array([0.0, 1.0]), labels=["s1", "s2"], title="samples"),
            target=np.array([0, 1]),
            provenance=[{"step": "load"}],
            backend="numpy",
            title="Test",
            units="absorbance",
        )
        d = original.to_dict()
        restored = AnalysisDataset.from_dict(d)

        np.testing.assert_array_almost_equal(restored.X, original.X)
        assert restored.shape == original.shape
        assert restored.backend == original.backend
        assert restored.title == original.title
        assert restored.units == original.units

    def test_round_trip_x_axis(self):
        original = AnalysisDataset(
            X=np.array([[1.0, 2.0]]),
            x_axis=AxisInfo(values=np.array([100.0, 200.0]), units="cm^-1", title="wavenumber"),
        )
        d = original.to_dict()
        restored = AnalysisDataset.from_dict(d)

        assert restored.x_axis is not None
        np.testing.assert_array_almost_equal(restored.x_axis.values, [100.0, 200.0])
        assert restored.x_axis.units == "cm^-1"
        assert restored.x_axis.title == "wavenumber"

    def test_round_trip_y_axis(self):
        original = AnalysisDataset(
            X=np.array([[1.0], [2.0]]),
            y_axis=AxisInfo(values=np.array([0.0, 1.0]), labels=["s1", "s2"]),
        )
        d = original.to_dict()
        restored = AnalysisDataset.from_dict(d)

        assert restored.y_axis is not None
        np.testing.assert_array_almost_equal(restored.y_axis.values, [0.0, 1.0])
        assert restored.y_axis.labels == ["s1", "s2"]

    def test_round_trip_target(self):
        original = AnalysisDataset(
            X=np.zeros((3, 2)),
            target=np.array([0, 1, 2]),
        )
        d = original.to_dict()
        restored = AnalysisDataset.from_dict(d)

        assert restored.target is not None
        np.testing.assert_array_equal(restored.target, [0, 1, 2])

    def test_round_trip_provenance(self):
        original = AnalysisDataset(
            X=np.zeros((2, 3)),
            provenance=[{"step": "snv"}, {"step": "savgol"}],
        )
        d = original.to_dict()
        restored = AnalysisDataset.from_dict(d)

        assert restored.provenance == [{"step": "snv"}, {"step": "savgol"}]

    def test_from_dict_no_axes(self):
        d = {
            "type": "NDDataset",
            "data": [[1.0, 2.0]],
            "shape": [1, 2],
        }
        ds = AnalysisDataset.from_dict(d)
        assert ds.shape == (1, 2)
        assert ds.x_axis is None
        assert ds.y_axis is None

    def test_from_dict_no_target(self):
        d = {
            "type": "NDDataset",
            "data": [[1.0, 2.0]],
            "shape": [1, 2],
        }
        ds = AnalysisDataset.from_dict(d)
        assert ds.target is None

    def test_from_dict_default_backend(self):
        d = {"data": [[1.0]], "shape": [1, 1]}
        ds = AnalysisDataset.from_dict(d)
        assert ds.backend == "numpy"

    def test_from_dict_metadata_passthrough(self):
        """Custom metadata fields survive round-trip (excluding processing_history)."""
        original = AnalysisDataset(
            X=np.zeros((1, 2)),
            meta={"custom_key": "custom_value"},
        )
        d = original.to_dict()
        restored = AnalysisDataset.from_dict(d)
        # data_type and is_spectra are added by to_dict; custom keys pass through
        assert restored.meta.get("custom_key") == "custom_value"


# ===========================================================================
# AnalysisDataset — meta / provenance sync
# ===========================================================================


class TestMetaProvenanceSync:
    def test_initial_sync(self):
        """meta['processing_history'] is the same object as provenance."""
        ds = AnalysisDataset(np.zeros((2, 3)))
        assert ds.meta["processing_history"] is ds.provenance

    def test_appending_to_provenance_visible_in_meta(self):
        ds = AnalysisDataset(np.zeros((2, 3)))
        ds.provenance.append({"step": "snv"})
        assert ds.meta["processing_history"] == [{"step": "snv"}]
        # Same object
        assert ds.meta["processing_history"] is ds.provenance

    def test_initial_provenance_preserved(self):
        prov = [{"step": "load"}]
        ds = AnalysisDataset(np.zeros((2, 3)), provenance=prov)
        assert ds.meta["processing_history"] is ds.provenance
        assert ds.meta["processing_history"] == [{"step": "load"}]

    def test_explicit_meta_with_processing_history(self):
        """If meta already has processing_history, setdefault doesn't overwrite."""
        existing_history = [{"step": "preexisting"}]
        ds = AnalysisDataset(
            np.zeros((2, 3)),
            meta={"processing_history": existing_history},
            provenance=[{"step": "from_provenance"}],
        )
        # setdefault keeps existing key → meta uses existing_history
        assert ds.meta["processing_history"] is existing_history

    def test_copy_sync(self):
        """After copy, meta['processing_history'] IS the copy's provenance."""
        ds = AnalysisDataset(np.zeros((2, 3)), provenance=[{"step": "load"}])
        cp = ds.copy()
        cp.provenance.append({"step": "snv"})
        assert len(cp.meta["processing_history"]) == 2
        assert len(ds.meta["processing_history"]) == 1

    def test_add_processing_step_no_double_append(self):
        """add_processing_step must not double-append when meta and provenance are linked."""
        from spectra_sherpa.app.services.dag.meta_helpers import add_processing_step

        ds = AnalysisDataset(np.zeros((3, 5)))
        # Confirm they're the same object (fresh AnalysisDataset)
        assert ds.meta["processing_history"] is ds.provenance

        add_processing_step(ds, "normalize.snv", {}, node_id="test_node")

        # Must have exactly ONE entry, not two
        assert len(ds.provenance) == 1
        assert len(ds.meta["processing_history"]) == 1
        assert ds.provenance[0]["operation"] == "normalize.snv"


# ===========================================================================
# AnalysisDataset — __repr__
# ===========================================================================


class TestRepr:
    def test_repr_format(self):
        ds = AnalysisDataset(np.zeros((5, 10)), backend="sklearn", title="Iris")
        r = repr(ds)
        assert "AnalysisDataset" in r
        assert "shape=(5, 10)" in r
        assert "backend='sklearn'" in r
        assert "title='Iris'" in r

    def test_repr_none_title(self):
        ds = AnalysisDataset(np.zeros((2, 3)))
        r = repr(ds)
        assert "title=None" in r


# ===========================================================================
# from_sklearn_bunch
# ===========================================================================


class TestFromSklearnBunch:
    def _make_bunch(self):
        """Create a mock sklearn Bunch."""
        return SimpleNamespace(
            data=np.array([[5.1, 3.5, 1.4, 0.2],
                           [4.9, 3.0, 1.4, 0.2],
                           [7.0, 3.2, 4.7, 1.4]]),
            target=np.array([0, 0, 1]),
            feature_names=["sepal_length", "sepal_width", "petal_length", "petal_width"],
            target_names=["setosa", "versicolor"],
        )

    def test_returns_analysis_dataset(self):
        bunch = self._make_bunch()
        ds = from_sklearn_bunch(bunch, name="iris")
        assert isinstance(ds, AnalysisDataset)

    def test_X_shape(self):
        bunch = self._make_bunch()
        ds = from_sklearn_bunch(bunch)
        assert ds.shape == (3, 4)

    def test_backend_sklearn(self):
        bunch = self._make_bunch()
        ds = from_sklearn_bunch(bunch)
        assert ds.backend == "sklearn"

    def test_x_axis_labels(self):
        bunch = self._make_bunch()
        ds = from_sklearn_bunch(bunch)
        assert ds.x_axis is not None
        assert ds.x_axis.labels == ["sepal_length", "sepal_width", "petal_length", "petal_width"]
        assert ds.x_axis.title == "features"

    def test_x_axis_values_are_indices(self):
        bunch = self._make_bunch()
        ds = from_sklearn_bunch(bunch)
        np.testing.assert_array_equal(ds.x_axis.values, np.arange(4))

    def test_y_axis_values_are_indices(self):
        bunch = self._make_bunch()
        ds = from_sklearn_bunch(bunch)
        assert ds.y_axis is not None
        np.testing.assert_array_equal(ds.y_axis.values, np.arange(3))
        assert ds.y_axis.title == "samples"

    def test_target(self):
        bunch = self._make_bunch()
        ds = from_sklearn_bunch(bunch)
        np.testing.assert_array_equal(ds.target, [0, 0, 1])

    def test_meta_target_names(self):
        bunch = self._make_bunch()
        ds = from_sklearn_bunch(bunch, name="iris")
        assert ds.meta["target_names"] == ["setosa", "versicolor"]
        assert ds.meta["dataset_name"] == "iris"

    def test_bunch_without_feature_names(self):
        bunch = SimpleNamespace(
            data=np.zeros((2, 3)),
            target=np.array([0, 1]),
            target_names=["a", "b"],
        )
        ds = from_sklearn_bunch(bunch)
        assert ds.x_axis is not None
        # No feature names → labels is None
        assert ds.x_axis.labels is None

    def test_bunch_without_target(self):
        bunch = SimpleNamespace(
            data=np.zeros((2, 3)),
            feature_names=["f1", "f2", "f3"],
            target_names=[],
        )
        ds = from_sklearn_bunch(bunch)
        assert ds.target is None

    def test_default_name_empty(self):
        bunch = self._make_bunch()
        ds = from_sklearn_bunch(bunch)
        assert ds.meta["dataset_name"] == ""
