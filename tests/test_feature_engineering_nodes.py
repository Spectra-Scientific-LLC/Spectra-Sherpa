import asyncio

import numpy as np
import pytest

from spectra_sherpa.app.lib.sherpa_dataset import FeatureAxis, SampleAxis, SherpaDataset, SpectralAxis
from spectra_sherpa.app.services.dag.nodes.data.feature_engineering import (
    MergeFeaturesNode,
    SelectColumnsNode,
    column_names,
    merge_features,
    select_columns,
)
from spectra_sherpa.app.services.dag.saved_graph_admission import admit_saved_workflow_graph


def inputs():
    base = SherpaDataset(
        X=[[1, 2], [3, 4], [5, 6]],
        target=np.array([10.0, 20.0, 30.0]),
        units="absorbance",
        sample_axis=SampleAxis(labels=["a", "b", "c"], values=[10, 20, 30]),
        feature_axis=SpectralAxis(values=[1000, 1200], units="nm"),
    )
    extra = SherpaDataset(
        X=[[9, 1200], [np.nan, 1202], [7, 1198]],
        sample_axis=SampleAxis(labels=["c", "a", "b"], values=[30, 10, 20]),
        feature_axis=FeatureAxis(labels=["magnitude", "position"]),
        extra={"column_units": {"magnitude": "absorbance", "position": "nm"}},
    )
    return base, extra


@pytest.mark.parametrize(
    "mode,columns,expected",
    [
        ("keep", ["position"], [1]),
        ("exclude", ["position"], [0]),
        ("keep", ["position", "magnitude"], [0, 1]),
        ("exclude", [], [0, 1]),
    ],
)
def test_select_preserves_samples_order_nulls_units_and_input(mode, columns, expected):
    _, source = inputs()
    digest = source.scientific_digest
    result = select_columns(source, columns, mode)
    np.testing.assert_array_equal(result.X, source.X[:, expected])
    assert result.sample_axis.labels == source.sample_axis.labels
    assert list(result.feature_axis.labels) == [column_names(source)[i] for i in expected]
    assert set(result.meta["column_units"]) == set(result.feature_axis.labels)
    assert source.scientific_digest == digest
    assert result.provenance[-1].op_id == "selection.select_columns"


@pytest.mark.parametrize(
    "columns,mode",
    [([], "keep"), (["missing"], "keep"), (["position", "position"], "keep"), (["position"], "invented")],
)
def test_select_rejects_ambiguous_or_empty_selection(columns, mode):
    with pytest.raises(ValueError):
        select_columns(inputs()[1], columns, mode)


@pytest.mark.parametrize("match_by", ["sample_labels", "sample_index"])
def test_merge_reorders_by_identity_preserves_targets_and_heterogeneous_units(match_by):
    base, extra = inputs()
    digests = base.scientific_digest, extra.scientific_digest
    merged = merge_features(base, extra, match_by)
    np.testing.assert_array_equal(merged.X[:, :2], base.X)
    np.testing.assert_array_equal(merged.X[:, 2:], extra.X[[1, 2, 0]])
    np.testing.assert_array_equal(merged.target, base.target)
    assert merged.sample_axis.labels == base.sample_axis.labels
    assert type(merged.feature_axis) is FeatureAxis
    assert merged.feature_axis.values is None and merged.units is None
    assert merged.meta["column_units"]["added::position"] == "nm"
    assert merged.meta["column_units"]["base::Column 1"] == "absorbance"
    assert merged.meta["feature_merge"]["additional_row_order"] == [1, 2, 0]
    assert merged.meta["feature_merge"]["blocks"][0]["feature_axis"]["units"] == "nm"
    assert (base.scientific_digest, extra.scientific_digest) == digests
    assert merged.provenance[-1].op_id == "data.merge_features"


@pytest.mark.parametrize("problem", ["duplicate", "missing", "no_identity", "counter_reset", "target", "mask"])
def test_merge_refuses_unsafe_alignment(problem):
    base, extra = inputs()
    match_by = "sample_labels"
    if problem == "duplicate":
        extra.sample_axis = SampleAxis(labels=["a", "a", "c"])
    elif problem == "missing":
        extra.sample_axis = SampleAxis(labels=["a", "b", "different"])
    elif problem == "no_identity":
        extra.sample_axis = SampleAxis()
    elif problem == "counter_reset":
        extra.sample_axis = SampleAxis(labels=["c", "a", "b"], values=[10, 20, 30])
        match_by = "sample_index"
    elif problem == "target":
        extra.target = np.array([999.0, 10.0, 20.0])
    elif problem == "mask":
        extra.sample_axis = SampleAxis(labels=["c", "a", "b"], include_mask=[False, True, True])
    with pytest.raises(ValueError):
        merge_features(base, extra, match_by)


def test_canonical_admission_execution_and_contracts():
    nodes = [
        {
            "node_id": "select",
            "node_type": "selection.select_columns",
            "parameters": {"mode": "keep", "columns": ["position"]},
        },
        {"node_id": "merge", "node_type": "data.merge_features", "parameters": {"match_by": "sample_labels"}},
    ]
    admit_saved_workflow_graph(nodes, [])
    base, extra = inputs()
    selected = asyncio.run(SelectColumnsNode("select", nodes[0]["parameters"]).execute(extra))["default"]
    merged = asyncio.run(MergeFeaturesNode("merge", nodes[1]["parameters"]).execute(base, selected))["default"]
    assert merged.shape == (3, 3)
    for node in (SelectColumnsNode, MergeFeaturesNode):
        contract = node.metadata.resolved_execution_contract()
        assert contract.payload["deterministic"]
        assert contract.payload["lifecycle_kind"] == "stateless_transform"
        assert contract.payload["sample_effect"] == "preserves_samples"


def test_select_spectral_axis_and_targets_are_sliced_not_renamed():
    base, _ = inputs()
    result = select_columns(base, ["Column 2"], "keep")
    np.testing.assert_array_equal(result.feature_axis.values, [1200])
    np.testing.assert_array_equal(result.target, base.target)
    assert isinstance(result.feature_axis, SpectralAxis)
    assert column_names(result) == ["Column 2"]
    assert column_names(select_columns(result, ["Column 2"], "keep")) == ["Column 2"]


def test_duplicate_features_and_nd_inputs_are_rejected():
    base, extra = inputs()
    extra.feature_axis = FeatureAxis(labels=["same", "same"])
    with pytest.raises(ValueError, match="unique"):
        select_columns(extra, ["same"], "keep")
    cube = SherpaDataset(X=np.ones((3, 2, 2)))
    with pytest.raises(ValueError, match="two-dimensional"):
        merge_features(base, cube, "sample_labels")


def test_merge_preserves_feature_masks_and_both_branch_histories():
    base, extra = inputs()
    extra.feature_axis = FeatureAxis(labels=["magnitude", "position"], include_mask=[True, False])
    extra.provenance.append("analysis.peak_finding", {"consensus_tolerance": 20})
    selected = select_columns(extra, ["position", "magnitude"], "keep")
    merged = merge_features(base, selected, "sample_labels")
    np.testing.assert_array_equal(merged.feature_axis.include_mask, [True, True, True, False])
    history = merged.meta["feature_merge"]["blocks"][1]["provenance"]
    assert [step["op_id"] for step in history] == ["analysis.peak_finding", "selection.select_columns"]


def test_equal_targets_are_aligned_and_preserved():
    base, extra = inputs()
    extra.target = np.array([30.0, 10.0, 20.0])
    result = merge_features(base, extra, "sample_labels")
    np.testing.assert_array_equal(result.target, base.target)
