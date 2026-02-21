from __future__ import annotations

import numpy as np
import pytest

from spectra_sherpa.app.lib.sherpa_dataset import SherpaDataset, SpectralAxis, SampleAxis
from spectra_sherpa.app.services.dag.io_contracts import (
    bind_X,
    bind_y,
    build_dataset_like,
    to_numpy_1d,
    to_numpy_2d,
)
from spectra_sherpa.app.services.dag.meta_helpers import add_processing_step


def _make_dataset(with_target: bool = True) -> SherpaDataset:
    ds = SherpaDataset(
        X=np.arange(12, dtype=float).reshape(3, 4),
        spectral_axis=SpectralAxis(values=np.array([1000.0, 1100.0, 1200.0, 1300.0]), title="wavenumber"),
        sample_axis=SampleAxis(
            values=np.arange(3, dtype=float),
            labels=["A", "B", "C"],
            title="samples",
        ),
        target=np.array([0, 1, 1]) if with_target else None,
        title="Source Dataset",
        units="absorbance",
        backend="numpy",
        extra={"catalog.dataset_name": "toy-set", "catalog.target_names": ["neg", "pos"]},
    )
    add_processing_step(ds, "data.source", {"source": "unit-test"}, node_id="src")
    return ds


def test_bind_x_legacy_kwarg():
    ds = _make_dataset()
    bound = bind_X(None, {"input_0": ds})
    assert bound is ds


def test_bind_x_allows_array_wrapping():
    bound = bind_X(None, {"input_0": [1.0, 2.0, 3.0]}, allow_array=True)
    assert isinstance(bound, SherpaDataset)
    assert bound.shape == (3, 1)


def test_bind_y_infers_from_target():
    ds = _make_dataset(with_target=True)
    y = bind_y(None, {}, X=ds, required=True)
    np.testing.assert_array_equal(np.asarray(y), np.array([0, 1, 1]))


def test_bind_y_infers_from_y_axis_labels_when_target_missing():
    ds = _make_dataset(with_target=False)
    y = bind_y(None, {}, X=ds, required=True)
    assert list(y) == ["A", "B", "C"]


def test_bind_y_extracts_embedded_labels_from_dataset_input():
    y_ds = SherpaDataset(
        X=np.zeros((3, 1)),
        sample_axis=SampleAxis(values=np.arange(3, dtype=float), labels=["X", "Y", "Z"]),
    )
    y = bind_y(y_ds, {}, required=True, infer_from_X=False)
    assert list(y) == ["X", "Y", "Z"]


def test_bind_y_dataset_as_data_for_regression():
    y_ds = SherpaDataset(X=np.array([[1.0], [2.0], [3.0]]))
    y = bind_y(y_ds, {}, required=True, infer_from_X=False, dataset_as_data=True)
    np.testing.assert_array_equal(np.asarray(y).reshape(-1), np.array([1.0, 2.0, 3.0]))


def test_bind_y_dataset_with_values_but_no_labels_returns_values():
    """y_axis with numeric values but no labels → values are used as target."""
    y_ds = SherpaDataset(X=np.zeros((3, 1)), sample_axis=SampleAxis(values=np.arange(3, dtype=float)))
    y = bind_y(y_ds, {}, required=True, infer_from_X=False)
    np.testing.assert_array_equal(y, np.arange(3, dtype=float))


def test_bind_y_dataset_without_labels_raises():
    """y_axis with neither labels nor values → raises ValueError."""
    y_ds = SherpaDataset(X=np.zeros((3, 1)), sample_axis=SampleAxis())
    with pytest.raises(ValueError, match="no embedded labels"):
        bind_y(y_ds, {}, required=True, infer_from_X=False)


def test_to_numpy_helpers():
    X = to_numpy_2d(np.array([1.0, 2.0, 3.0]), name="X")
    assert X.shape == (3, 1)

    y = to_numpy_1d([[1], [2], [3]], name="y", expected_length=3)
    assert y.shape == (3,)
    np.testing.assert_array_equal(y, np.array([1, 2, 3]))


def test_build_dataset_like_preserves_axes_and_history():
    src = _make_dataset(with_target=True)
    result = build_dataset_like(np.ones((3, 4)), src, units="normalized")

    assert isinstance(result, SherpaDataset)
    assert result.shape == (3, 4)
    assert result.title == "Source Dataset"
    assert result.units == "normalized"
    assert result.get_extra("catalog.dataset_name") == "toy-set"
    assert result.get_extra("catalog.target_names") == ["neg", "pos"]

    assert result.spectral_axis is not None
    assert result.sample_axis is not None
    np.testing.assert_array_equal(result.spectral_axis.values, src.spectral_axis.values)
    np.testing.assert_array_equal(result.sample_axis.values, src.sample_axis.values)
    assert result.sample_axis.labels == src.sample_axis.labels
    np.testing.assert_array_equal(result.target, src.target)

    hist = result.provenance.to_list()
    assert len(hist) == 1
    assert result.provenance[0].op_id == "data.source"
