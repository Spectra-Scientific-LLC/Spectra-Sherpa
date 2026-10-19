"""Public sample helpers must affect the same axis consumed by workflows."""

import numpy as np
import pytest

from spectra_sherpa.sdk import (
    SampleAxis,
    SherpaDataset,
    exclude_samples,
    filter_by_class,
    get_classes,
    get_include_mask,
    get_included_data,
    get_sample_labels,
    include_samples,
    set_class,
    set_sample_labels,
)


def dataset():
    return SherpaDataset(X=np.arange(12.0).reshape(3, 4), sample_axis=SampleAxis(labels=["a", "b", "c"]))


def test_public_helpers_use_axis_and_preserve_source_values():
    value = dataset()
    source = value.copy()
    set_sample_labels(value, ["u", "v", "w"])
    exclude_samples(value, [1], reason="reviewed outlier")
    assert value.sample_axis.labels == get_sample_labels(value) == ["u", "v", "w"]
    assert value.sample_axis.include_mask.tolist() == get_include_mask(value).tolist() == [True, False, True]
    assert value.sample_axis.exclusion_reasons == [None, "reviewed outlier", None]
    retained = get_included_data(value)
    assert retained.sample_axis.labels == ["u", "w"]
    np.testing.assert_array_equal(retained.X, value.X[[0, 2]])
    np.testing.assert_array_equal(source.X, value.X)
    assert source.sample_axis.labels == ["a", "b", "c"]
    assert source.sample_axis.include_mask is None
    assert "samples" not in value.meta
    include_samples(value, [1])
    assert get_include_mask(value).all()
    assert value.sample_axis.exclusion_reasons == [None, None, None]


def test_classes_use_axis_and_filter_without_changing_original():
    value = dataset()
    set_class(value, [0, 2], "control")
    set_class(value, 1, 7)
    assert get_classes(value).tolist() == ["control", 7, "control"]
    assert value.sample_axis.classes.tolist() == get_classes(value).tolist()
    assert filter_by_class(value, "control").sample_axis.labels == ["a", "c"]
    assert value.shape == (3, 4)


@pytest.mark.parametrize("indices", [[0, 9], [-1], [1.5], [True]])
def test_invalid_indices_are_atomic(indices):
    value = dataset()
    with pytest.raises((ValueError, IndexError)):
        exclude_samples(value, indices)
    assert value.sample_axis.include_mask is None
    assert "samples" not in value.meta


def test_axisless_and_detached_getters():
    value = SherpaDataset(X=np.ones((3, 2)))
    exclude_samples(value, 1)
    assert value.sample_axis.include_mask.tolist() == [True, False, True]
    mask = get_include_mask(value)
    mask[:] = False
    include_samples(value)
    assert value.sample_axis.include_mask.all()
    set_sample_labels(value, ["a", "b", "c"])
    with pytest.raises(ValueError):
        set_sample_labels(value, ["bad"])
    assert get_sample_labels(value) == ["a", "b", "c"]
