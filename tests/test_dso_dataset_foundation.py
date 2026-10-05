from __future__ import annotations

import copy
from datetime import datetime, timezone

import numpy as np
import pytest
from pydantic import ValidationError

import spectra_sherpa as ss
import spectra_sherpa.app.lib.axes as axes_module
from spectra_sherpa.app.lib.axes import (
    AxisClassLevel,
    AxisClassSet,
    AxisInfo,
    AxisLabelSet,
    AxisScaleSet,
    AxisTitleSet,
    SampleAxis,
    SpatialAxis,
    SpectralAxis,
)
from spectra_sherpa.app.lib.sherpa_dataset import (
    DatasetDescriptiveContext,
    DatasetLayoutContext,
    DatasetSourceHistory,
    DatasetSourceIdentity,
    SherpaDataset,
)


def _class_set(name: str, values: tuple[object, ...], source_set_index: int) -> AxisClassSet:
    distinct: list[object] = []
    for value in values:
        if not any(type(value) is type(item) and value == item for item in distinct):
            distinct.append(value)
    return AxisClassSet(
        name=name,
        values=values,
        levels=tuple(AxisClassLevel(code=value, label=f"{type(value).__name__}:{value}") for value in distinct),
        source_set_index=source_set_index,
    )


def test_dso_foundation_types_are_available_from_the_public_sdk_root() -> None:
    assert ss.AxisScaleSet is AxisScaleSet
    assert ss.AxisLabelSet is AxisLabelSet
    assert ss.AxisTitleSet is AxisTitleSet
    assert ss.AxisClassLevel is AxisClassLevel
    assert ss.AxisClassSet is AxisClassSet
    assert ss.DatasetDescriptiveContext is DatasetDescriptiveContext
    assert ss.DatasetSourceIdentity is DatasetSourceIdentity
    assert ss.DatasetSourceHistory is DatasetSourceHistory
    assert ss.DatasetLayoutContext is DatasetLayoutContext


def _rich_dataset() -> SherpaDataset:
    sample_axis = SampleAxis(
        values=np.array([0.0, 1.0, 2.0]),
        labels=["S1", "S2", "S3"],
        title="Samples",
        include_mask=np.array([True, False, True]),
        primary_scale_name="acquisition index",
        alternate_scales=(
            AxisScaleSet(
                name="elapsed time",
                values=np.array([0.0, 2.5, 5.0]),
                title="Elapsed time",
                units="min",
                axis_type="time",
                source_set_index=1,
            ),
        ),
        primary_label_name="sample id",
        alternate_label_sets=(AxisLabelSet(name="operator label", values=("one", "two", "three"), source_set_index=1),),
        primary_title_name="sample mode",
        alternate_title_sets=(AxisTitleSet(name="customer title", title="Calibration specimens", source_set_index=1),),
        class_sets=(
            _class_set("species", ("A", "B", "A"), 0),
            _class_set("block", (1, 1, 2), 1),
        ),
        primary_class_set_name="species",
        sample_table={"sample_id": ["S1", "S2", "S3"], "operator": ["AA", "BB", "AA"]},
    )
    y_axis = SpatialAxis(
        values=np.array([10.0, 20.0]),
        units="um",
        title="Y position",
        include_mask=np.array([True, False]),
        primary_scale_name="micrometres",
        alternate_label_sets=(AxisLabelSet(name="row", values=("top", "bottom"), source_set_index=1),),
        class_sets=(_class_set("detector row", ("upper", "lower"), 0),),
    )
    x_axis = AxisInfo(
        values=np.array([100.0, 200.0]),
        units="um",
        title="X position",
        include_mask=np.array([True, True]),
        alternate_title_sets=(AxisTitleSet(name="short", title="X", source_set_index=1),),
    )
    feature_axis = SpectralAxis(
        values=np.array([4000.0, 3000.0, 2000.0, 1000.0]),
        units="cm-1",
        title="Wavenumber",
        include_mask=np.array([True, True, False, True]),
        primary_scale_name="wavenumber",
        alternate_scales=(
            AxisScaleSet(
                name="wavelength",
                values=np.array([2500.0, 3333.333333, 5000.0, 10000.0]),
                title="Wavelength",
                units="nm",
                axis_type="wavelength_nm",
                source_set_index=1,
            ),
        ),
        class_sets=(_class_set("detector", ("A", "A", "B", "B"), 0),),
    )
    return SherpaDataset(
        X=np.arange(3 * 2 * 2 * 4, dtype=np.float64).reshape(3, 2, 2, 4),
        sample_axis=sample_axis,
        axes={1: y_axis, 2: x_axis},
        feature_axis=feature_axis,
        title="Multidimensional DSO",
        units="absorbance",
        descriptive=DatasetDescriptiveContext(
            authors=("A. Scientist",),
            description="A complete DSO projection",
            created_at=datetime(2026, 8, 25, 10, 30, tzinfo=timezone.utc),
            raw_date_fields={"moddate": "25-Aug-2026 10:30:00"},
        ),
        source_identity=DatasetSourceIdentity(
            source_format="eigenvector-dso",
            storage_version="matlab-v7.3",
            object_name="calibration",
            object_unique_id="dso-123",
            dataset_version="5.0",
            source_variable="cal",
        ),
        source_history=DatasetSourceHistory(
            entries=("Imported", "Baseline correction: none"),
            source_shape=(2, 1),
            storage_order="column-major",
        ),
        layout=DatasetLayoutContext(
            kind="image",
            source_type="image",
            source_dtype="float64",
            source_shape=(3, 2, 2, 4),
            mode_roles=("sample", "spatial-y", "spatial-x", "feature"),
            image_size=(2, 2),
            image_mode=2,
            image_include=(True, False, True, True),
            original_unfolded_shape=(3, 4, 4),
        ),
    )


def test_multidimensional_axis_sets_copy_slice_and_wire_round_trip_exactly() -> None:
    dataset = _rich_dataset()
    copied = dataset.copy()
    assert copied.scientific_digest == dataset.scientific_digest
    assert copied.equals(dataset, mode="full")

    wire = dataset.to_dict()
    assert wire["version"] == "3.0"
    restored = SherpaDataset.from_dict(wire)
    assert restored.scientific_digest == dataset.scientific_digest
    assert restored.layout == dataset.layout
    assert restored.source_identity == dataset.source_identity
    assert restored.source_history == dataset.source_history
    assert restored.descriptive == dataset.descriptive

    sliced = dataset[1:, :, :, 1:3]
    assert sliced.shape == (2, 2, 2, 2)
    assert sliced.sample_axis is not None
    assert sliced.sample_axis.class_sets[0].values == ("B", "A")
    assert sliced.sample_axis.alternate_label_sets[0].values == ("two", "three")
    assert sliced.axis(1).include_mask.tolist() == [True, False]  # type: ignore[union-attr]
    assert sliced.feature_axis is not None
    np.testing.assert_array_equal(sliced.feature_axis.alternate_scales[0].values, [3333.333333, 5000.0])
    assert sliced.feature_axis.class_sets[0].values == ("A", "B")


def test_scientific_digest_binds_metadata_while_fingerprint_remains_data_only() -> None:
    first = _rich_dataset()
    feature = first.feature_axis
    assert feature is not None
    changed_scale = feature.alternate_scales[0].model_copy(
        update={"values": np.array([2501.0, 3333.333333, 5000.0, 10000.0])}
    )
    second = SherpaDataset(
        X=first.X.copy(),
        sample_axis=first.sample_axis,
        axes=first.inner_axes,
        feature_axis=feature.model_copy(update={"alternate_scales": (changed_scale,)}),
        title=first.title,
        units=first.units,
        descriptive=first.descriptive,
        source_identity=first.source_identity,
        layout=first.layout,
    )
    assert first.fingerprint == second.fingerprint
    assert first.scientific_digest != second.scientific_digest
    assert not first.equals(second, mode="metadata")


def test_axis_class_identity_keeps_boolean_integer_and_float_distinct() -> None:
    class_set = _class_set("typed", (True, 1, 1.0), 0)
    assert [level.code for level in class_set.levels] == [True, 1, 1.0]
    axis = SampleAxis(
        labels=["a", "b", "c"],
        class_sets=(class_set,),
        primary_class_set_name="typed",
    )
    assert axis.classes is not None
    assert [type(value) for value in axis.classes.tolist()] == [bool, int, float]


@pytest.mark.parametrize("value", [2**53, np.nan, datetime(2026, 8, 25), {"nested": True}])
def test_axis_class_set_refuses_lossy_wire_values(value: object) -> None:
    with pytest.raises(ValidationError):
        AxisClassSet(name="invalid", values=(value,), source_set_index=0)


@pytest.mark.parametrize("value", [2**53, np.nan, datetime(2026, 8, 25), {"nested": {"bad"}}])
def test_dataset_refuses_lossy_dso_userdata(value: object) -> None:
    with pytest.raises(ValueError, match="dso.userdata"):
        SherpaDataset(X=np.ones((1, 2)), extra={"dso.userdata": {"value": value}})


def test_axis_sets_refuse_wrong_lengths_duplicate_names_and_primary_aliases() -> None:
    with pytest.raises(ValidationError, match="length"):
        AxisInfo(
            values=np.array([1.0, 2.0]),
            alternate_label_sets=(AxisLabelSet(name="short", values=("only",), source_set_index=0),),
        )
    with pytest.raises(ValidationError, match="duplicate"):
        AxisInfo(
            values=np.array([1.0]),
            alternate_title_sets=(
                AxisTitleSet(name="same", title="A", source_set_index=0),
                AxisTitleSet(name="same", title="B", source_set_index=1),
            ),
        )
    with pytest.raises(ValidationError, match="primary"):
        AxisInfo(
            values=np.array([1.0]),
            primary_scale_name="same",
            alternate_scales=(AxisScaleSet(name="same", values=np.array([2.0]), source_set_index=1),),
        )
    with pytest.raises(ValidationError, match="boolean"):
        AxisInfo(values=np.array([1.0, 2.0]), include_mask=np.array([1, 0]))
    with pytest.raises(ValidationError, match="valid integer"):
        AxisScaleSet(name="coerced index", values=np.array([1.0]), source_set_index=True)


@pytest.mark.parametrize(
    ("model", "payload", "message"),
    [
        (DatasetSourceHistory, {"entries": ("one",), "source_shape": (True,)}, "history shape"),
        (DatasetLayoutContext, {"source_shape": (1.0, 2)}, "positive integer dimensions"),
        (DatasetLayoutContext, {"image_mode": True}, "image mode"),
    ],
)
def test_dso_layout_indices_and_shapes_do_not_coerce_types(
    model: type[DatasetSourceHistory] | type[DatasetLayoutContext],
    payload: dict[str, object],
    message: str,
) -> None:
    with pytest.raises(ValidationError, match=message):
        model.model_validate(payload)


def test_dataset_readmits_model_copy_updates_instead_of_trusting_nested_instances() -> None:
    invalid_scale = AxisScaleSet(
        name="valid-before-copy",
        values=np.array([1.0, 2.0]),
        source_set_index=0,
    ).model_copy(update={"values": np.array([1.0, np.nan])})
    axis = SpectralAxis(
        values=np.array([1.0, 2.0]),
        alternate_scales=(invalid_scale,),
    )

    with pytest.raises(ValidationError, match="non-finite"):
        SherpaDataset(X=np.ones((1, 2)), feature_axis=axis)


def test_axis_refuses_aggregate_aligned_metadata_before_dataset_copy(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(axes_module, "MAX_AXIS_TOTAL_ALIGNED_VALUES", 5)

    with pytest.raises(ValidationError, match="aggregate value limit"):
        AxisInfo(
            values=np.array([1.0, 2.0]),
            alternate_scales=(
                AxisScaleSet(name="one", values=np.array([3.0, 4.0]), source_set_index=0),
                AxisScaleSet(name="two", values=np.array([5.0, 6.0]), source_set_index=1),
            ),
        )


def test_primary_sample_class_projection_must_be_exact() -> None:
    classes = _class_set("species", ("A", "B"), 0)
    with pytest.raises(ValidationError, match="contradicts"):
        SampleAxis(
            labels=["one", "two"],
            classes=np.array(["B", "A"], dtype=object),
            class_sets=(classes,),
            primary_class_set_name="species",
        )


def test_dataset_context_instances_are_revalidated_on_admission() -> None:
    invalid_history = DatasetSourceHistory(entries=("one",)).model_copy(update={"source_shape": (2,)})
    with pytest.raises(ValidationError, match="shape does not match"):
        SherpaDataset(X=np.ones((1, 2)), source_history=invalid_history)

    invalid_layout = DatasetLayoutContext(source_shape=(1, 2)).model_copy(update={"kind": "invented"})
    with pytest.raises(ValidationError, match="unsupported"):
        SherpaDataset(X=np.ones((1, 2)), layout=invalid_layout)


def test_current_wire_is_required_for_every_dataset_rank() -> None:
    dataset_2d = SherpaDataset(
        X=np.arange(6.0).reshape(2, 3),
        sample_axis=SampleAxis(labels=["one", "two"]),
        feature_axis=SpectralAxis(values=np.array([3.0, 2.0, 1.0]), units="cm-1"),
    )
    current_2d = dataset_2d.to_dict()
    assert current_2d["version"] == "3.0"
    assert current_2d["descriptive"] == {"authors": [], "raw_date_fields": {}}
    assert current_2d["source_identity"] == {}
    assert current_2d["source_history"] == {"entries": [], "storage_order": "column-major"}
    assert current_2d["layout"] == {"kind": "generic", "mode_roles": []}
    assert SherpaDataset.from_dict(current_2d).scientific_digest == dataset_2d.scientific_digest

    dataset_nd = SherpaDataset(
        X=np.arange(24.0).reshape(2, 3, 4),
        axes={1: SpatialAxis(values=np.array([0.0, 1.0, 2.0]), title="row")},
        feature_axis=SpectralAxis(values=np.array([4.0, 3.0, 2.0, 1.0]), units="cm-1"),
    )
    current_nd = dataset_nd.to_dict()
    assert current_nd["version"] == "3.0"
    assert SherpaDataset.from_dict(current_nd).scientific_digest == dataset_nd.scientific_digest

    for retired_version in (None, "1.0", "2.0"):
        retired = copy.deepcopy(current_2d)
        if retired_version is None:
            del retired["version"]
        else:
            retired["version"] = retired_version
        with pytest.raises(ValueError, match="Unsupported SherpaDataset wire version"):
            SherpaDataset.from_dict(retired)


def test_current_wire_admission_is_closed_and_versioned() -> None:
    wire = _rich_dataset().to_dict()

    unknown = dict(wire)
    unknown["invented_science"] = "accepted nowhere"
    with pytest.raises(ValueError, match="undeclared field"):
        SherpaDataset.from_dict(unknown)

    future = dict(wire)
    future["version"] = "4.0"
    with pytest.raises(ValueError, match="Unsupported"):
        SherpaDataset.from_dict(future)

    downgraded = dict(wire)
    downgraded["version"] = "1.0"
    with pytest.raises(ValueError, match="Unsupported"):
        SherpaDataset.from_dict(downgraded)

    unknown_context = copy.deepcopy(wire)
    unknown_context["source_identity"]["unmapped_identity"] = "not admitted"
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        SherpaDataset.from_dict(unknown_context)

    unknown_axis = copy.deepcopy(wire)
    unknown_axis["feature_axis"]["axis_class"] = "InventedSpectralAxis"
    with pytest.raises(ValueError, match="unsupported axis class"):
        SherpaDataset.from_dict(unknown_axis)


@pytest.mark.parametrize(
    ("path", "replacement", "message"),
    [
        (("shape",), [3, 2, 2, 5], "shape"),
        (("ndim",), 3, "ndim"),
        (("n_samples",), 4, "n_samples"),
        (("n_features",), 5, "n_features"),
        (("data_modality",), "tabular", "data_modality"),
        (("state", "n_steps"), 9, "state"),
        (("metadata", "processing_history"), [{"op_id": "invented"}], "processing_history"),
        (("metadata", "data_type"), "Raman", "data_type"),
        (("metadata", "is_spectra"), False, "is_spectra"),
    ],
)
def test_wire_compatibility_receipts_are_recomputed(
    path: tuple[str, ...],
    replacement: object,
    message: str,
) -> None:
    wire = copy.deepcopy(_rich_dataset().to_dict())
    target: dict[str, object] = wire
    for key in path[:-1]:
        target = target[key]  # type: ignore[assignment,index]
    target[path[-1]] = replacement
    with pytest.raises(ValueError, match=message):
        SherpaDataset.from_dict(wire)
