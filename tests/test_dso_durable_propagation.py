from __future__ import annotations

import asyncio
import json
from datetime import date

import numpy as np
import pytest

from spectra_sherpa.app.lib.axes import (
    AxisClassLevel,
    AxisClassSet,
    AxisInfo,
    AxisLabelSet,
    AxisScaleSet,
    FeatureAxis,
    SampleAxis,
)
from spectra_sherpa.app.lib.collection_assembly import CollectionMember, assemble_collection
from spectra_sherpa.app.lib.export_artifact import build_export_artifact, verify_export_artifact
from spectra_sherpa.app.lib.sherpa_dataset import (
    DatasetDescriptiveContext,
    DatasetLayoutContext,
    DatasetSourceIdentity,
    SherpaDataset,
)
from spectra_sherpa.app.services.dag.node_base import node_registry
from spectra_sherpa.app.services.dag.nodes.data.dimension_projection import (
    PROJECTION_SCHEMA,
    project_dataset_to_2d,
)
from spectra_sherpa.app.services.dag.nodes.modeling._artifact_builder import build_model_artifact
from spectra_sherpa.app.services.dag.serialize import serialize_for_api
from spectra_sherpa.app.services.dag.spectral_capability import SpectralCapabilityError, SpectralDatasetCapability


def _dataset(
    *,
    source: str,
    rows: int = 2,
    inner_shape: tuple[int, ...] = (3,),
    features: int = 4,
    alternate_axis_offset: float = 0.0,
    include_sample_table: bool = True,
) -> SherpaDataset:
    shape = (rows, *inner_shape, features)
    sample_codes = tuple(f"{source}-{index}" for index in range(rows))
    return SherpaDataset(
        np.arange(np.prod(shape), dtype=np.float64).reshape(shape),
        feature_axis=FeatureAxis(
            values=np.linspace(1000.0, 700.0, features),
            labels=[f"v{index}" for index in range(features)],
            include_mask=np.asarray([True] * features),
            units="cm-1",
            title="Wavenumber",
            alternate_scales=(
                AxisScaleSet(
                    name="wavelength",
                    values=np.linspace(10.0, 14.0, features) + alternate_axis_offset,
                    units="um",
                    source_set_index=1,
                ),
            ),
        ),
        sample_axis=SampleAxis(
            values=np.arange(rows, dtype=np.float64),
            labels=list(sample_codes),
            include_mask=np.asarray([True] * rows),
            alternate_scales=(
                AxisScaleSet(
                    name="sequence",
                    values=np.arange(1, rows + 1, dtype=np.float64),
                    source_set_index=1,
                ),
            ),
            alternate_label_sets=(
                AxisLabelSet(
                    name="display", values=tuple(f"Sample {value}" for value in sample_codes), source_set_index=1
                ),
            ),
            class_sets=(
                AxisClassSet(
                    name="specimen",
                    values=sample_codes,
                    levels=tuple(AxisClassLevel(code=value, label=value) for value in sample_codes),
                    source_set_index=0,
                ),
            ),
            primary_class_set_name="specimen",
            sample_table=({"sample_id": list(sample_codes), "block": [1] * rows} if include_sample_table else None),
        ),
        axes={
            dimension: AxisInfo(
                values=np.arange(size, dtype=np.float64),
                title=f"Mode {dimension}",
                include_mask=np.asarray([True] * size),
                class_sets=(
                    AxisClassSet(
                        name=f"region-{dimension}",
                        values=tuple(f"r{index}" for index in range(size)),
                        source_set_index=0,
                    ),
                ),
            )
            for dimension, size in enumerate(inner_shape, start=1)
        },
        title=f"Dataset {source}",
        units="absorbance",
        descriptive=DatasetDescriptiveContext(authors=("Scientist",), description="DSO fixture"),
        source_identity=DatasetSourceIdentity(source_format="eigenvector-dso", object_unique_id=source),
        layout=DatasetLayoutContext(
            source_type="dataset-object",
            source_dtype="double",
            source_shape=shape,
            mode_roles=("samples", *(f"inner-{index}" for index in range(len(inner_shape))), "features"),
        ),
        extra={"dso.userdata": {"study": "durable"}},
    )


def test_collection_concatenates_all_sample_axis_sets_and_scopes_member_science() -> None:
    first = _dataset(source="a")
    second = _dataset(source="b")
    result = assemble_collection(
        [
            CollectionMember(first, "a.mat", 10, "a" * 64),
            CollectionMember(second, "b.mat", 10, "b" * 64),
        ],
        title="DSO collection",
    )

    assert result.shape == (4, 3, 4)
    assert result.sample_axis is not None
    assert result.sample_axis.alternate_scales[0].values.tolist() == [1.0, 2.0, 1.0, 2.0]
    assert result.sample_axis.alternate_label_sets[0].values == (
        "Sample a-0",
        "Sample a-1",
        "Sample b-0",
        "Sample b-1",
    )
    assert result.sample_axis.class_sets[0].values == ("a-0", "a-1", "b-0", "b-1")
    assert result.layout.source_shape == result.shape
    members = result.meta["source_member_metadata"]
    assert [item["source_identity"]["object_unique_id"] for item in members] == ["a", "b"]
    assert [item["scientific_digest"] for item in members] == [first.scientific_digest, second.scientific_digest]


def test_collection_science_survives_bounded_execution_capability() -> None:
    collection = assemble_collection(
        [
            CollectionMember(_dataset(source="a", include_sample_table=False), "a.mat", 10, "a" * 64),
            CollectionMember(_dataset(source="b", include_sample_table=False), "b.mat", 10, "b" * 64),
        ],
        title="DSO collection",
    )
    capability = SpectralDatasetCapability.from_dataset(collection, custody_id="dso-collection")
    rehydrated, groups = capability.to_dataset_and_groups()

    assert groups is None
    assert rehydrated.scientific_digest == collection.scientific_digest
    assert (
        rehydrated.scientific_projection()["collection_member_science"]
        == collection.scientific_projection()["collection_member_science"]
    )

    malformed = dict(capability.metadata)
    malformed["collection_member_science"] = {"nodes": 1, "text_bytes": 0, "sha256": "not-a-digest"}
    with pytest.raises(SpectralCapabilityError, match="collection member scientific projection"):
        SpectralDatasetCapability(arrays=capability.arrays, metadata=malformed)


def test_collection_refuses_unprojectable_member_science_before_concatenation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dataset = _dataset(source="invalid-member")
    dataset.meta["scientist.invalid_date"] = date(2026, 1, 1)
    monkeypatch.setattr(
        "spectra_sherpa.app.lib.collection_assembly.np.concatenate",
        lambda *_args, **_kwargs: pytest.fail("invalid member science reached concatenation"),
    )
    with pytest.raises(ValueError, match="date or datetime"):
        assemble_collection(
            [CollectionMember(dataset, "invalid.mat", 10, "a" * 64)],
            title="Invalid collection",
        )


def test_multidimensional_api_preview_is_aligned_and_binds_complete_science() -> None:
    dataset = _dataset(source="preview", rows=101, inner_shape=(31,), features=321)
    wire = serialize_for_api(dataset, dataset_register=lambda _dataset, _owner: "handle-1")

    assert wire["metadata"]["api_serialization"]["mode"] == "bounded_preview"
    assert wire["dataset_id"] == "handle-1"
    assert wire["shape"] == [101, 31, 321]
    assert len(wire["preview_shape"]) == 3
    assert np.prod(wire["preview_shape"]) <= 30_000
    assert wire["inner_axes"]["1"]["title"] == "Mode 1"
    assert wire["descriptive"]["description"] == "DSO fixture"
    assert wire["source_identity"]["object_unique_id"] == "preview"
    assert wire["scientific_projection"] == dataset.scientific_projection(
        include_data=False,
        include_sample_table=False,
    )


def test_pca_explicitly_unfolds_nd_and_records_the_projection() -> None:
    node = node_registry.create_node(
        "model.pca",
        "pca",
        {"n_components": "2", "standardized": False, "scaled": False},
    )
    result = asyncio.run(node.run(_dataset(source="rank")))

    scores = result.outputs["scores"]
    state = result.outputs["fitted_state"]
    assert scores.shape == (2, 2)
    assert state["metadata"]["input_shape"] == [2, 3, 4]
    assert state["metadata"]["rank_projection_strategy"] == "mode_1_samples_by_composite_features_c_order"
    assert any(entry.op_id == "model.pca.mode_1_unfold" for entry in scores.provenance)


def test_dimension_projection_is_exact_and_preserves_remaining_metadata() -> None:
    dataset = _dataset(source="project", inner_shape=(2, 3))
    projected = project_dataset_to_2d(
        dataset,
        {
            "schema_version": PROJECTION_SCHEMA,
            "selections": [{"dimension": 1, "index": 1}, {"dimension": 2, "index": 2}],
        },
        node_id="projection",
    )

    assert projected.shape == (2, 4)
    assert np.array_equal(projected.X, dataset.X[:, 1, 2, :])
    assert projected.sample_axis is not None
    assert projected.sample_axis.class_sets == dataset.sample_axis.class_sets
    assert projected.feature_axis is not None
    assert projected.feature_axis.alternate_scales[0].values.tolist() == [
        10.0,
        11.333333333333334,
        12.666666666666666,
        14.0,
    ]
    assert projected.inner_axes == {}
    assert projected.layout.original_unfolded_shape == dataset.shape
    assert projected.provenance.to_list()[-1]["state_effects"] == ["inner_dimensions_projected"]


def test_json_export_is_complete_for_nd_while_tabular_formats_refuse() -> None:
    dataset = _dataset(source="export")
    artifact = verify_export_artifact(build_export_artifact(dataset, filename="dataset.json", format="json"))
    envelope = json.loads(artifact["content"])
    wire = envelope["dataset"]

    assert artifact["shape"] == [2, 3, 4]
    assert artifact["source_digest"] == dataset.scientific_digest
    assert envelope["schema_version"] == "spectrasherpa-portable-json/1"
    assert envelope["shape"] == [2, 3, 4]
    assert wire["version"] == "3.0"
    assert wire["inner_axes"]["1"]["class_sets"][0]["name"] == "region-1"
    assert wire["source_identity"]["object_unique_id"] == "export"
    with pytest.raises(ValueError, match="two-dimensional"):
        build_export_artifact(dataset, filename="dataset.csv", format="csv")
    with pytest.raises(ValueError, match="two-dimensional"):
        build_export_artifact(dataset, filename="dataset.jdx", format="jdx")


def test_scientific_identity_changes_when_axis_semantics_change_with_same_matrix() -> None:
    original = _dataset(source="identity")
    changed = _dataset(source="identity", alternate_axis_offset=1.0)

    assert np.array_equal(original.X, changed.X)
    assert original.fingerprint == changed.fingerprint
    assert original.scientific_digest != changed.scientific_digest


def test_model_lineage_binds_complete_training_science_not_only_matrix() -> None:
    class Extract:
        @staticmethod
        def to_artifact() -> tuple[dict[str, object], dict[str, np.ndarray]]:
            return {"model_type": "fixture"}, {"state": np.asarray([1.0])}

    original = _dataset(source="lineage")
    changed = _dataset(source="lineage", alternate_axis_offset=1.0)
    first = build_model_artifact(Extract(), original)["metadata"]
    second = build_model_artifact(Extract(), changed)["metadata"]

    assert first["training_data_hash"] == second["training_data_hash"]
    assert first["training_scientific_projection_schema"] == "spectrasherpa-dataset-scientific-projection/1"
    assert first["training_scientific_digest"] == original.scientific_digest
    assert first["training_scientific_digest"] != second["training_scientific_digest"]


def test_execution_receipt_projects_actual_dataset_scientific_identity() -> None:
    from spectra_sherpa.app.api.v1.routes.workflows.execute import _execution_dataset_scientific_receipts

    dataset = _dataset(source="run")
    receipts = _execution_dataset_scientific_receipts({"z": {"value": 1}, "source": dataset})

    assert receipts == [
        {
            "node_id": "source",
            "scientific_projection_schema": dataset.manifest.scientific_projection_schema,
            "scientific_digest": dataset.scientific_digest,
            "shape": [2, 3, 4],
            "title": "Dataset run",
            "sample_identity": {
                "count": 2,
                "labels_sha256": "fa03aba7865c9a4a3e4a646f97fee30dedd0350a69cb9260d26474c181d82d8f",
            },
            "selection_lineage": [],
        }
    ]


def test_complete_axis_inventory_exposes_every_mode_and_named_set() -> None:
    from spectra_sherpa.app.api.v1.routes.datasets import _complete_dataset_axis_inventory

    dataset = _dataset(source="axes", inner_shape=(2, 3))
    inventory = _complete_dataset_axis_inventory(dataset)

    assert inventory["scientific_digest"] == dataset.scientific_digest
    assert [record["dimension"] for record in inventory["axes"]] == [0, 1, 2, 3]
    sample = inventory["axes"][0]["axis"]
    assert sample["alternate_scales"][0]["name"] == "sequence"
    assert sample["alternate_label_sets"][0]["name"] == "display"
    assert sample["class_sets"][0]["name"] == "specimen"
    assert "sample_table" not in sample


def test_axis_inventory_refuses_before_wire_materialization(monkeypatch: pytest.MonkeyPatch) -> None:
    from spectra_sherpa.app.api.v1.routes import datasets as datasets_route

    monkeypatch.setattr(datasets_route, "_DATASET_AXIS_INVENTORY_MAX_VALUES", 1)
    monkeypatch.setattr(
        datasets_route,
        "axis_to_wire",
        lambda *_args, **_kwargs: pytest.fail("over-budget axis reached wire materialization"),
    )
    with pytest.raises(ValueError, match="retrieval limit"):
        datasets_route._complete_dataset_axis_inventory(_dataset(source="bounded-axis"))
