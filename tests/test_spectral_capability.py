"""M4.4 bounded spectral capability contract tests."""

from __future__ import annotations

import copy
import hashlib
import json

import numpy as np
import pytest

from spectra_sherpa.app.lib.axes import AxisClassSet, AxisInfo, AxisScaleSet, SampleAxis, SpectralAxis
from spectra_sherpa.app.lib.sherpa_dataset import (
    DatasetDescriptiveContext,
    DatasetLayoutContext,
    DatasetSourceHistory,
    DatasetSourceIdentity,
    DomainContext,
    Provenance,
    SherpaDataset,
    TargetContext,
)
from spectra_sherpa.app.services.dag.spectral_capability import (
    SpectralCapabilityBounds,
    SpectralCapabilityError,
    SpectralDatasetCapability,
)


def _dataset() -> SherpaDataset:
    provenance = Provenance()
    provenance.append("data.fixture", {"fixture": "bounded"}, node_id="fixture")
    return SherpaDataset(
        X=np.arange(24, dtype=np.float64).reshape(4, 6),
        target=np.array([[1.0], [2.0], [3.0], [4.0]]),
        feature_axis=SpectralAxis(
            values=np.linspace(1_000.0, 1_500.0, 6),
            units="cm-1",
            title="wavenumber",
            include_mask=np.array([True, True, False, True, True, True]),
        ),
        sample_axis=SampleAxis(
            values=np.arange(4),
            labels=["s1", "s2", "s3", "s4"],
            include_mask=np.array([True, True, False, True]),
        ),
        domain=DomainContext(technique="NIR", measurement_mode="reflectance"),
        target_context=TargetContext(target_type="continuous", target_name="moisture", target_units="percent"),
        provenance=provenance,
        data_role="X_spectra",
        is_time_series=False,
    )


def test_capability_round_trip_preserves_the_scientific_dataset_boundary() -> None:
    source = _dataset()
    capability = SpectralDatasetCapability.from_dataset(
        source,
        custody_id="lab-owned-public-fixture",
        split_plan_digest="a" * 64,
        groups=np.array(["a", "a", "b", "b"]),
    )

    restored_capability = SpectralDatasetCapability.from_wire(capability.to_wire())
    restored, restored_groups = restored_capability.to_dataset_and_groups()

    np.testing.assert_allclose(restored.X, source.X)
    np.testing.assert_allclose(restored.target, source.target)
    np.testing.assert_allclose(restored.feature_axis.values, source.feature_axis.values)
    np.testing.assert_array_equal(restored.feature_axis.include_mask, source.feature_axis.include_mask)
    np.testing.assert_array_equal(restored.sample_axis.include_mask, source.sample_axis.include_mask)
    assert restored.sample_axis.labels == source.sample_axis.labels
    assert restored.feature_axis.units == "cm-1"
    assert restored.domain.technique == "NIR"
    assert restored.target_context.target_name == "moisture"
    assert restored.provenance.operations == ["data.fixture"]
    np.testing.assert_array_equal(restored_groups, np.array(["a", "a", "b", "b"]))
    assert capability.arrays["X"].flags.writeable is False
    assert capability.evidence_summary()["sample_identity_digest"]
    assert capability.evidence_summary()["feature_identity_digest"]
    with pytest.raises(TypeError):
        capability.metadata["domain"]["technique"] = "Raman"  # type: ignore[index]


def test_capability_round_trip_preserves_multidimensional_dso_science() -> None:
    source = SherpaDataset(
        # Sherpa's admitted numerical matrix is normalized to float64 while
        # the exact source DSO dtype remains in DatasetLayoutContext.
        X=np.arange(24, dtype=np.float64).reshape(2, 3, 4),
        sample_axis=SampleAxis(
            values=np.asarray([1.0, 2.0]),
            labels=["sample-a", "sample-b"],
            class_sets=(
                AxisClassSet(name="origin", values=("north", "south"), source_set_index=0),
                AxisClassSet(name="batch", values=(1, 2), source_set_index=1),
            ),
            primary_class_set_name="origin",
        ),
        feature_axis=SpectralAxis(
            values=np.asarray([1000.0, 1100.0, 1200.0, 1300.0]),
            units="cm-1",
            title="Wavenumber",
            alternate_scales=(
                AxisScaleSet(
                    name="wavelength",
                    values=np.asarray([10000.0, 9090.909, 8333.333, 7692.308]),
                    title="Wavelength",
                    units="nm",
                    axis_type="wavelength",
                    source_set_index=1,
                ),
            ),
            class_sets=(AxisClassSet(name="detector", values=("A", "A", "B", "B"), source_set_index=0),),
            include_mask=np.asarray([True, True, False, True]),
        ),
        axes={
            1: AxisInfo(
                values=np.asarray([0.0, 1.0, 2.0]),
                title="Image row",
                class_sets=(AxisClassSet(name="region", values=("top", "middle", "bottom"), source_set_index=0),),
            )
        },
        title="Imported DSO image",
        units="absorbance",
        descriptive=DatasetDescriptiveContext(authors=("A. Scientist",), description="DSO fixture"),
        source_identity=DatasetSourceIdentity(
            source_format="eigenvector-dso",
            storage_version="matlab-v7.3",
            object_name="fixture",
        ),
        source_history=DatasetSourceHistory(entries=("Imported without correction",), source_shape=(1,)),
        layout=DatasetLayoutContext(
            kind="image",
            source_type="image",
            source_dtype="single",
            source_shape=(2, 3, 4),
            mode_roles=("sample", "image-row", "feature"),
            image_size=(2, 3),
            image_mode=2,
        ),
        extra={"dso.userdata": {"instrument_note": "bounded fixture"}},
        data_role="X_spectra",
    )

    capability = SpectralDatasetCapability.from_dataset(source, custody_id="licensed-dso-fixture")
    restored = SpectralDatasetCapability.from_wire(capability.to_wire()).to_dataset()

    assert restored.scientific_digest == source.scientific_digest
    assert restored.shape == (2, 3, 4)
    assert restored.layout == source.layout
    assert restored.descriptive == source.descriptive
    assert restored.source_identity == source.source_identity
    assert restored.source_history == source.source_history
    assert restored.extra["dso.userdata"] == {"instrument_note": "bounded fixture"}
    assert restored.sample_axis is not None
    assert [item.name for item in restored.sample_axis.class_sets] == ["origin", "batch"]
    assert restored.feature_axis is not None
    assert restored.feature_axis.alternate_scales[0].units == "nm"
    assert restored.inner_axes[1].class_sets[0].name == "region"

    metadata = copy.deepcopy(capability.to_wire()["metadata"])
    metadata["execution_scientific_projection"]["title"] = "Coherently rehashed false title"
    metadata["execution_scientific_digest"] = hashlib.sha256(
        json.dumps(
            metadata["execution_scientific_projection"],
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()
    tampered = SpectralDatasetCapability(arrays=capability.arrays, metadata=metadata)
    with pytest.raises(SpectralCapabilityError, match="scientific projection"):
        tampered.to_dataset()


def test_scientific_changes_rotate_content_digest_but_custody_only_changes_do_not() -> None:
    source = _dataset()
    first = SpectralDatasetCapability.from_dataset(source, custody_id="lab-owned-a")
    same_data_other_custody = SpectralDatasetCapability.from_dataset(source, custody_id="lab-owned-b")

    changed = _dataset()
    changed.X[0, 0] += 0.25
    changed_data = SpectralDatasetCapability.from_dataset(changed, custody_id="lab-owned-a")

    assert first.content_digest == same_data_other_custody.content_digest
    assert first.envelope_digest != same_data_other_custody.envelope_digest
    assert first.content_digest != changed_data.content_digest


def test_exact_target_identity_is_digest_bound_without_disclosure() -> None:
    moisture = _dataset()
    moisture.target_context = moisture.target_context.model_copy(
        update={
            "target_name": "moisture",
            "target_names": ["moisture"],
            "selected_target": "moisture",
        }
    )
    protein = _dataset()
    protein.target_context = protein.target_context.model_copy(
        update={
            "target_name": "protein",
            "target_names": ["protein"],
            "selected_target": "protein",
        }
    )

    moisture_capability = SpectralDatasetCapability.from_dataset(moisture, custody_id="lab-owned-a")
    protein_capability = SpectralDatasetCapability.from_dataset(protein, custody_id="lab-owned-a")

    assert moisture_capability.content_digest != protein_capability.content_digest
    assert moisture_capability.envelope_digest != protein_capability.envelope_digest
    assert moisture_capability.to_dataset().target_context.selected_target == "moisture"
    assert protein_capability.to_dataset().target_context.selected_target == "protein"
    assert "target_context" not in moisture_capability.evidence_summary()


def test_dataset_reference_identity_rotates_only_the_capability_envelope() -> None:
    source = _dataset()
    first = SpectralDatasetCapability.from_dataset(source, custody_id="lab-owned-a", dataset_ref_digest="a" * 64)
    same_data_other_reference = SpectralDatasetCapability.from_dataset(
        source, custody_id="lab-owned-a", dataset_ref_digest="b" * 64
    )

    assert first.content_digest == same_data_other_reference.content_digest
    assert first.envelope_digest != same_data_other_reference.envelope_digest


def test_wire_digest_is_stable_across_irrelevant_mapping_order() -> None:
    capability = SpectralDatasetCapability.from_dataset(_dataset(), custody_id="lab-owned-a")
    wire = capability.to_wire()
    reordered = {
        "envelope_digest": wire["envelope_digest"],
        "content_digest": wire["content_digest"],
        "arrays": dict(reversed(list(wire["arrays"].items()))),
        "metadata": dict(reversed(list(wire["metadata"].items()))),
        "schema_version": wire["schema_version"],
    }

    restored = SpectralDatasetCapability.from_wire(reordered)
    assert restored.content_digest == capability.content_digest
    assert restored.envelope_digest == capability.envelope_digest


@pytest.mark.parametrize(
    "mutate, message",
    [
        (
            lambda wire: wire["arrays"].__setitem__("bad", {"dtype": "|O", "shape": [1], "values": ["x"]}),
            "arrays do not match",
        ),
        (lambda wire: wire["metadata"].__setitem__("location", "/private/lab-data"), "closed schema"),
        (lambda wire: wire["metadata"].__setitem__("custody_id", "file:///private/data"), "filesystem locations"),
        (lambda wire: wire["arrays"]["X"].__setitem__("dtype", "|O"), "dtype is unsupported"),
        (lambda wire: wire["arrays"]["X"].__setitem__("base64", "not base64!"), "wire bytes"),
        (lambda wire: wire["arrays"]["X"].__setitem__("shape", [100_001, 100_001]), "exceeds capability bounds"),
    ],
)
def test_capability_rejects_unsafe_or_malformed_wire_payloads(mutate, message: str) -> None:
    wire = copy.deepcopy(SpectralDatasetCapability.from_dataset(_dataset(), custody_id="lab-owned-a").to_wire())
    mutate(wire)
    with pytest.raises(SpectralCapabilityError, match=message):
        SpectralDatasetCapability.from_wire(wire)


@pytest.mark.parametrize(
    "mutate",
    [
        lambda wire: wire["metadata"]["array_roles"].__setitem__("/private/lab/run-42", "context"),
        lambda wire: wire["metadata"]["axes"].__setitem__("inner.not-an-int", {"axis_type": "AxisInfo"}),
    ],
)
def test_capability_rejects_location_or_noncanonical_dictionary_keys(mutate) -> None:
    wire = copy.deepcopy(SpectralDatasetCapability.from_dataset(_dataset(), custody_id="lab-owned-a").to_wire())
    mutate(wire)
    with pytest.raises(SpectralCapabilityError):
        SpectralDatasetCapability.from_wire(wire)


def test_capability_rejects_oversized_and_nonfinite_arrays_before_execution() -> None:
    source = _dataset()
    with pytest.raises(SpectralCapabilityError, match="exceeds sample or feature bounds"):
        SpectralDatasetCapability.from_dataset(
            source,
            custody_id="lab-owned-a",
            bounds=SpectralCapabilityBounds(max_samples=3),
        )

    source.X[0, 0] = np.nan
    with pytest.raises(SpectralCapabilityError, match="non-finite"):
        SpectralDatasetCapability.from_dataset(source, custody_id="lab-owned-a")


def test_capability_rejects_nonlossless_dso_userdata() -> None:
    source = _dataset()
    source.meta["dso.userdata"] = {"acquisition_index": 2**53}

    with pytest.raises(SpectralCapabilityError, match="lossless JSON range"):
        SpectralDatasetCapability.from_dataset(source, custody_id="lab-owned-a")


def test_capability_evidence_summary_never_contains_raw_samples_or_labels() -> None:
    capability = SpectralDatasetCapability.from_dataset(_dataset(), custody_id="lab-owned-a")
    summary = capability.evidence_summary()
    rendered = repr(summary)

    assert "s1" not in rendered
    assert "1000.0" not in rendered
    assert "array_shapes" in summary
    assert summary["content_digest"] == capability.content_digest
    event = capability.local_conversion_event(direction="dataset_to_capability")
    assert event["content_digest"] == capability.content_digest
    assert "s1" not in repr(event)
    with pytest.raises(SpectralCapabilityError, match="direction"):
        capability.local_conversion_event(direction="remote_export")


def test_sample_tables_are_not_an_unbounded_side_channel() -> None:
    dataset = _dataset()
    sample_axis = dataset.sample_axis
    assert sample_axis is not None
    sample_axis.sample_table = {"source_file": ["a", "b", "c", "d"]}
    dataset.sample_axis = sample_axis
    with pytest.raises(SpectralCapabilityError, match="sample_table"):
        SpectralDatasetCapability.from_dataset(dataset, custody_id="lab-owned-a")


def test_oversized_axis_metadata_refuses_before_model_dump(monkeypatch: pytest.MonkeyPatch) -> None:
    values = tuple(index % 2 for index in range(100_000))
    dataset = SherpaDataset(
        X=np.ones((1, 100_000), dtype=np.float64),
        feature_axis=SpectralAxis(
            values=np.arange(100_000, dtype=np.float64),
            class_sets=(
                AxisClassSet(name="first", values=values, source_set_index=0),
                AxisClassSet(name="second", values=values, source_set_index=1),
            ),
        ),
    )

    def materialization_was_reached(*_args, **_kwargs):
        raise AssertionError("axis model_dump must be unreachable after the preflight refusal")

    monkeypatch.setattr(AxisInfo, "model_dump", materialization_was_reached)
    with pytest.raises(SpectralCapabilityError, match="metadata budget"):
        SpectralDatasetCapability.from_dataset(dataset, custody_id="bounded-axis")


@pytest.mark.parametrize("with_labels", [False, True])
def test_large_hsi_sample_identity_and_spatial_mask_round_trip_within_separate_budgets(with_labels: bool) -> None:
    sample_count = 59_292
    labels = [f"pixel-{index + 1:05d}" for index in range(sample_count)] if with_labels else None
    image_include = tuple(index % 7 != 0 for index in range(sample_count))
    source = SherpaDataset(
        X=np.ones((sample_count, 2), dtype=np.float64),
        feature_axis=SpectralAxis(values=np.array([900.0, 901.0]), units="nm"),
        sample_axis=SampleAxis(labels=labels, include_mask=np.ones(sample_count, dtype=bool)),
        layout=DatasetLayoutContext(
            kind="image",
            source_shape=(sample_count, 2),
            mode_roles=("spatial_coordinate", "spectral_feature"),
            image_size=(243, 244),
            image_include=image_include,
            original_unfolded_shape=(sample_count, 2),
        ),
        data_role="X_hsi",
    )

    restored = SpectralDatasetCapability.from_wire(
        SpectralDatasetCapability.from_dataset(source, custody_id="hsi-pixels").to_wire()
    ).to_dataset()

    assert restored.sample_axis is not None
    assert restored.sample_axis.labels == labels
    np.testing.assert_array_equal(restored.sample_axis.include_mask, np.ones(sample_count, dtype=bool))
    assert restored.layout.image_size == (243, 244)
    assert restored.layout.image_include == image_include
    assert sum(restored.layout.image_include) == sum(image_include)


def test_spatial_mask_allowance_requires_matching_shape_and_scientific_projection() -> None:
    source = SherpaDataset(
        X=np.ones((4, 2), dtype=np.float64),
        feature_axis=SpectralAxis(values=np.array([900.0, 901.0]), units="nm"),
        layout=DatasetLayoutContext(
            kind="image",
            source_shape=(4, 2),
            image_size=(2, 2),
            image_include=(True, False, True, True),
        ),
        data_role="X_hsi",
    )
    capability = SpectralDatasetCapability.from_dataset(source, custody_id="hsi-mask")
    metadata = copy.deepcopy(capability.to_wire()["metadata"])
    metadata["layout"]["image_size"] = [2, 3]
    with pytest.raises(SpectralCapabilityError, match="not aligned to its spatial shape"):
        SpectralDatasetCapability(arrays=capability.arrays, metadata=metadata)

    metadata = copy.deepcopy(capability.to_wire()["metadata"])
    metadata["layout"]["image_include"][1] = True
    with pytest.raises(SpectralCapabilityError, match="differs from its scientific projection"):
        SpectralDatasetCapability(arrays=capability.arrays, metadata=metadata)

    metadata = copy.deepcopy(capability.to_wire()["metadata"])
    metadata["provenance"] = ["x" * 2_000 for _ in range(150)]
    with pytest.raises(SpectralCapabilityError, match="metadata exceeds the maximum size"):
        SpectralDatasetCapability(arrays=capability.arrays, metadata=metadata)

    with pytest.raises(SpectralCapabilityError, match="exceeds its entry budget"):
        SpectralDatasetCapability.from_dataset(
            source, custody_id="hsi-mask", bounds=SpectralCapabilityBounds(max_spatial_mask_entries=3)
        )


def test_spatial_mask_must_match_admitted_x_geometry() -> None:
    source = SherpaDataset(
        X=np.ones((4, 2), dtype=np.float64),
        layout=DatasetLayoutContext(
            kind="image",
            source_shape=(4, 2),
            image_size=(2, 3),
            image_include=(True, True, True, True, True, True),
        ),
        data_role="X_hsi",
    )
    with pytest.raises(SpectralCapabilityError, match="does not align to X spatial dimensions"):
        SpectralDatasetCapability.from_dataset(source, custody_id="wrong-image-geometry")


@pytest.mark.parametrize("technique, units", [("NIR", "nm"), ("FTIR", "cm-1"), ("Raman", "cm-1"), ("UVVIS", "nm")])
def test_capability_preserves_representative_spectroscopy_context(technique: str, units: str) -> None:
    dataset = _dataset()
    feature_axis = dataset.get_feature_axis()
    assert feature_axis is not None
    feature_axis.units = units
    dataset.feature_axis = feature_axis
    dataset.domain = DomainContext(technique=technique, measurement_mode="reflectance")

    restored = SpectralDatasetCapability.from_wire(
        SpectralDatasetCapability.from_dataset(dataset, custody_id="lab-owned-a").to_wire()
    ).to_dataset()

    assert restored.domain.technique == technique
    assert restored.feature_axis is not None
    assert restored.feature_axis.units == units


def test_capability_preserves_absent_target_and_axis_without_inventing_context() -> None:
    dataset = SherpaDataset(
        X=np.arange(12, dtype=np.float64).reshape(3, 4),
        data_role="X_features",
    )
    restored = SpectralDatasetCapability.from_wire(
        SpectralDatasetCapability.from_dataset(dataset, custody_id="public-feature-fixture").to_wire()
    ).to_dataset()

    assert restored.target is None
    assert restored.sample_axis is None
    assert restored.get_feature_axis() is None


def test_capability_preserves_multitarget_grouped_and_masked_context() -> None:
    dataset = _dataset()
    dataset.target = np.array([[1.0, 10.0], [2.0, 20.0], [3.0, 30.0], [4.0, 40.0]])
    capability = SpectralDatasetCapability.from_wire(
        SpectralDatasetCapability.from_dataset(
            dataset,
            custody_id="lab-owned-multitarget",
            groups=np.array(["lot-a", "lot-a", "lot-b", "lot-b"]),
        ).to_wire()
    )
    restored, groups = capability.to_dataset_and_groups()

    assert restored.target is not None
    assert restored.target.shape == (4, 2)
    np.testing.assert_array_equal(groups, np.array(["lot-a", "lot-a", "lot-b", "lot-b"]))
    with pytest.raises(SpectralCapabilityError, match="to_dataset_and_groups"):
        capability.to_dataset()
