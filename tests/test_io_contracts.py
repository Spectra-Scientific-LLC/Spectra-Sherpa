from __future__ import annotations

import numpy as np
import pytest

from spectra_sherpa.app.lib.sherpa_dataset import SampleAxis, SherpaDataset, SpectralAxis
from spectra_sherpa.app.services.dag.io_contracts import (
    bind_X,
    bind_y,
    build_dataset_like,
    extract_target_like,
    select_exact_target,
    to_numpy_1d,
    to_numpy_2d,
)
from spectra_sherpa.app.services.dag.meta_helpers import add_processing_step


def _make_dataset(with_target: bool = True) -> SherpaDataset:
    ds = SherpaDataset(
        X=np.arange(12, dtype=float).reshape(3, 4),
        feature_axis=SpectralAxis(values=np.array([1000.0, 1100.0, 1200.0, 1300.0]), title="wavenumber"),
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


def test_bind_x_direct():
    ds = _make_dataset()
    bound = bind_X(ds)
    assert bound is ds


def test_bind_x_allows_array_wrapping():
    bound = bind_X([1.0, 2.0, 3.0], allow_array=True)
    assert isinstance(bound, SherpaDataset)
    assert bound.shape == (3, 1)


def test_bind_y_infers_from_target():
    ds = _make_dataset(with_target=True)
    y = bind_y(None, X=ds, required=True)
    np.testing.assert_array_equal(np.asarray(y), np.array([0, 1, 1]))


def test_canonical_target_projection_never_treats_sample_identity_as_supervision():
    without_target = _make_dataset(with_target=False)
    assert extract_target_like(without_target) is None

    with_target = _make_dataset(with_target=True)
    np.testing.assert_array_equal(extract_target_like(with_target), with_target.target)


def test_exact_target_selection_is_the_shared_fail_closed_projection():
    dataset = SherpaDataset(
        X=np.arange(12, dtype=float).reshape(3, 4),
        target=np.array([[1.0, 10.0], [2.0, 20.0], [3.0, 30.0]]),
    )
    dataset.target_context = dataset.target_context.model_copy(
        update={
            "target_names": ["Moisture", "Oil"],
            "selected_target": "Moisture",
        }
    )

    np.testing.assert_allclose(
        select_exact_target(dataset, "Moisture"),
        [1.0, 2.0, 3.0],
    )
    np.testing.assert_allclose(extract_target_like(dataset), [1.0, 2.0, 3.0])

    dataset.target_context = dataset.target_context.model_copy(update={"selected_target": "Ash"})
    with pytest.raises(ValueError, match="not present"):
        extract_target_like(dataset)


def test_bind_y_does_not_infer_supervision_from_sample_labels():
    ds = _make_dataset(with_target=False)
    with pytest.raises(ValueError, match="Missing required input: y"):
        bind_y(None, X=ds, required=True)


def test_bind_y_rejects_sample_labels_as_embedded_target():
    y_ds = SherpaDataset(
        X=np.zeros((3, 1)),
        sample_axis=SampleAxis(values=np.arange(3, dtype=float), labels=["X", "Y", "Z"]),
    )
    with pytest.raises(ValueError, match="no embedded labels"):
        bind_y(y_ds, required=True, infer_from_X=False)


def test_bind_y_dataset_as_data_for_regression():
    y_ds = SherpaDataset(X=np.array([[1.0], [2.0], [3.0]]))
    y = bind_y(y_ds, required=True, infer_from_X=False, dataset_as_data=True)
    np.testing.assert_array_equal(np.asarray(y).reshape(-1), np.array([1.0, 2.0, 3.0]))


def test_bind_y_rejects_sample_axis_values_as_target():
    """Sample-axis values are row identity, not supervised reference values."""
    y_ds = SherpaDataset(X=np.zeros((3, 1)), sample_axis=SampleAxis(values=np.arange(3, dtype=float)))
    with pytest.raises(ValueError, match="no embedded labels"):
        bind_y(y_ds, required=True, infer_from_X=False)


def test_bind_y_dataset_without_labels_raises():
    """y_axis with neither labels nor values → raises ValueError."""
    y_ds = SherpaDataset(X=np.zeros((3, 1)), sample_axis=SampleAxis())
    with pytest.raises(ValueError, match="no embedded labels"):
        bind_y(y_ds, required=True, infer_from_X=False)


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

    assert result.feature_axis is not None
    assert result.sample_axis is not None
    np.testing.assert_array_equal(result.feature_axis.values, src.feature_axis.values)
    np.testing.assert_array_equal(result.sample_axis.values, src.sample_axis.values)
    assert result.sample_axis.labels == src.sample_axis.labels
    np.testing.assert_array_equal(result.target, src.target)

    hist = result.provenance.to_list()
    assert len(hist) == 1
    assert result.provenance[0].op_id == "data.source"


@pytest.mark.parametrize("response_ids", [["C", "B", "A"], ["D", "E", "F"], ["A", "A", "C"]])
def test_separate_response_identity_is_checked_before_unwrapping(response_ids):
    X = _make_dataset()
    y = SherpaDataset(X=np.arange(3.0)[:, None], sample_axis=SampleAxis(labels=response_ids))
    with pytest.raises(ValueError, match="identities"):
        bind_y(y, X=X, dataset_as_data=True)


def test_separate_response_requires_identity_on_both_sides():
    X = _make_dataset()
    y = SherpaDataset(X=np.arange(3.0)[:, None])
    with pytest.raises(ValueError, match="missing complete sample identities"):
        bind_y(y, X=X, dataset_as_data=True)
    with pytest.raises(ValueError, match="missing complete sample identities"):
        bind_y(X, X=y, dataset_as_data=True)


def test_aligned_response_and_explicit_positional_array_remain_supported():
    X = _make_dataset()
    values = np.arange(3.0)[:, None]
    y = SherpaDataset(X=values, sample_axis=SampleAxis(labels=["A", "B", "C"]))
    np.testing.assert_array_equal(bind_y(y, X=X, dataset_as_data=True), values)
    np.testing.assert_array_equal(bind_y(values, X=X), values)
    anonymous = SherpaDataset(X=X.X)
    np.testing.assert_array_equal(bind_y(SherpaDataset(X=values), X=anonymous, dataset_as_data=True), values)


def test_numeric_sample_coordinates_cannot_be_silently_reordered():
    X = SherpaDataset(X=np.ones((3, 2)), sample_axis=SampleAxis(values=np.array([2.0, 4.0, 6.0])))
    y = SherpaDataset(X=np.ones((3, 1)), sample_axis=SampleAxis(values=np.array([6.0, 4.0, 2.0])))
    with pytest.raises(ValueError, match="identities/order differ"):
        bind_y(y, X=X, dataset_as_data=True)


def test_sample_table_cannot_contradict_axis_identity():
    X = _make_dataset()
    y = SherpaDataset(
        X=np.ones((3, 1)),
        sample_axis=SampleAxis(labels=["A", "B", "C"], sample_table={"sample_id": ["C", "B", "A"]}),
    )
    with pytest.raises(ValueError, match="contradict"):
        bind_y(y, X=X, dataset_as_data=True)


def test_table_identity_cannot_hide_behind_equal_numeric_positions():
    X = SherpaDataset(
        X=np.ones((3, 2)), sample_axis=SampleAxis(values=np.arange(3.0), sample_table={"sample_id": ["A", "B", "C"]})
    )
    y = SherpaDataset(
        X=np.ones((3, 1)), sample_axis=SampleAxis(values=np.arange(3.0), sample_table={"sample_id": ["C", "B", "A"]})
    )
    with pytest.raises(ValueError, match="sample table identities"):
        bind_y(y, X=X, dataset_as_data=True)
