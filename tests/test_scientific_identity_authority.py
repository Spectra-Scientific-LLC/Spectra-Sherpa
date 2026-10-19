"""Identity is not a display label or an equal row count."""

import numpy as np
import pytest

from spectra_sherpa.app.lib.collection_assembly import (
    CollectionMember,
    assemble_collection,
    verified_source_observations,
)
from spectra_sherpa.app.lib.sample_identity import require_matching_sample_identity, sample_ids
from spectra_sherpa.app.services.dag.nodes.data._utils import slice_axis_for_indices
from spectra_sherpa.sdk import (
    FeatureAxis,
    SampleAxis,
    SherpaDataset,
    exclude_samples,
    get_included_data,
    set_sample_labels,
)


def source(ids=None):
    return SherpaDataset(
        X=np.arange(12.0).reshape(3, 4),
        feature_axis=FeatureAxis(labels=["a", "b", "c", "d"]),
        sample_axis=SampleAxis(labels=["A", "B", "C"], sample_table={"sample_id": ids} if ids is not None else None),
    )


@pytest.mark.parametrize("explicit", [False, True])
def test_relabel_preserves_receipt_identity_exclusion_order_and_roundtrip(explicit):
    dataset = assemble_collection(
        [CollectionMember(source(["s1", "s2", "s3"] if explicit else None), "source.csv", 100, "a" * 64)],
        title="Source",
    )
    original = dataset.copy()
    receipt = verified_source_observations(dataset)
    exclude_samples(dataset, [1], reason="damaged specimen")
    set_sample_labels(dataset, ["Renamed", "Renamed", "Different label"])
    assert sample_ids(dataset) == [row["sample_id"] for row in receipt]
    assert verified_source_observations(dataset) == receipt
    kept = get_included_data(dataset)[[1, 0]]
    restored = SherpaDataset.from_dict(kept.to_dict())
    assert verified_source_observations(restored) == [receipt[2], receipt[0]]
    assert restored.sample_axis.labels == ["Different label", "Renamed"]
    assert restored.sample_axis.include_mask.tolist() == [True, True]
    np.testing.assert_array_equal(restored.X, original.X[[2, 0]])
    assert original.sample_axis.labels == ["A", "B", "C"]


def test_ids_not_labels_bind_target_rows():
    left, right = source(["s1", "s2", "s3"]), source(["s1", "s2", "s3"])
    set_sample_labels(right, ["other1", "other2", "other3"])
    assert require_matching_sample_identity(left, right)
    shuffled = source(["s2", "s1", "s3"])
    with pytest.raises(ValueError, match="sample IDs.*order"):
        require_matching_sample_identity(left, shuffled)
    assert require_matching_sample_identity(source(), source()) is False


def test_canonical_response_binding_uses_ids_after_display_relabel():
    from spectra_sherpa.app.services.dag.io_contracts import bind_y

    left, right = source(["s1", "s2", "s3"]), source(["s1", "s2", "s3"])
    set_sample_labels(left, ["Repeated display", "Repeated display", "Other"])
    np.testing.assert_array_equal(bind_y(right, X=left, dataset_as_data=True), right.X)
    with pytest.raises(ValueError, match="sample identities/order differ"):
        bind_y(source(["s2", "s1", "s3"]), X=left, dataset_as_data=True)


@pytest.mark.parametrize(
    "ids",
    [
        ["s1", "s1", "s3"],
        ["s1", "s2"],
        ["s1", None, "s3"],
        [1, 2, 3],
        [1, "1", "s3"],
        [True, "s2", "s3"],
        [" s1", "s2", "s3"],
    ],
)
def test_malformed_declared_ids_are_not_replaced_with_display_labels(ids):
    # Short columns are refused by SampleAxis itself; other defects by identity admission.
    with pytest.raises(ValueError):
        sample_ids(source(ids))


def test_split_axis_preserves_ids_and_full_typed_coordinate_sets():
    from spectra_sherpa.app.lib.axes import AxisLabelSet

    axis = source(["s1", "s2", "s3"]).sample_axis
    axis.alternate_label_sets = (AxisLabelSet(name="Display alias", values=("a", "b", "c"), source_set_index=0),)
    sliced = slice_axis_for_indices(axis, np.array([2, 0]))
    assert sliced.sample_table["sample_id"] == ["s3", "s1"]
    assert sliced.alternate_label_sets[0].values == ("c", "a")


def test_reassembly_preserves_declared_ids_when_display_labels_repeat():
    dataset = source(["s1", "s2", "s3"])
    set_sample_labels(dataset, ["Same display", "Same display", "Third"])
    assembled = assemble_collection([CollectionMember(dataset, "source.csv", 100, "a" * 64)], title="Reimport")
    assert sample_ids(assembled) == ["s1", "s2", "s3"]
    assert [row["sample_id"] for row in verified_source_observations(assembled)] == ["s1", "s2", "s3"]
