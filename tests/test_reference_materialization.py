from __future__ import annotations

import hashlib
import json
import os
import zipfile
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

import spectra_sherpa.sdk as ss
from spectra_sherpa.app.lib import parafac_core
from spectra_sherpa.app.lib.axes import FeatureAxis, SampleAxis, SpectralAxis
from spectra_sherpa.app.lib.reference_artifacts import (
    ReferenceArtifact,
    ReferenceArtifactRegistry,
    ReferenceProjection,
)
from spectra_sherpa.app.lib.reference_dataset_packages import reference_annotation_table_digest
from spectra_sherpa.app.lib.reference_datasets import feature_axis_values_digest
from spectra_sherpa.app.lib.reference_materialization import (
    PORTABLE_REFERENCE_SCHEMA,
    ReferenceMaterializationError,
    _axis_for_analysis_profile,
    _bind_registered_reference_source,
    _finish_source_projection,
    _verified_cgl_partition_roles,
    materialize_reference_member,
    materialize_reference_projection,
    portable_reference_manifest,
    reference_source_projection_digest,
    resolve_reference_artifact,
)
from spectra_sherpa.app.lib.sherpa_dataset import DatasetLayoutContext, DatasetSourceIdentity, SherpaDataset
from spectra_sherpa.core.execution_runtime import ExecutionRuntime, ResolvedExperimentCollection, ResolvedExperimentFile
from spectra_sherpa.io.types import IngestionResult, SourceMember, SpectralAsset
from spectra_sherpa.sdk.dataset_identity import public_dataset_digest


@pytest.mark.parametrize("with_package_view", [False, True])
def test_registered_hsi_projection_uses_exact_native_cube_view(
    monkeypatch: pytest.MonkeyPatch, with_package_view: bool
) -> None:
    if with_package_view:
        from spectra_sherpa.app.lib import reference_materialization

        monkeypatch.setattr(
            reference_materialization,
            "package_view_projection",
            lambda _projection_id: {
                "package_id": "fixture-hsi-package",
                "view_id": "fixture-hsi-view",
                "instrument": "image-camera",
                "cohort": "image",
                "annotation_table": None,
            },
        )
    unfolded = np.arange(24.0).reshape(6, 4)
    axis = SpectralAxis(values=np.arange(4.0), title="Spectral coordinate")
    source = SherpaDataset(X=unfolded, feature_axis=axis, data_role="X_hsi")
    cube = SherpaDataset(
        X=unfolded.reshape(2, 3, 4, order="F"),
        feature_axis=axis,
        layout=DatasetLayoutContext(
            kind="image",
            source_type="hyperspectral-image-cube",
            source_dtype=unfolded.dtype.str,
            source_shape=(2, 3, 4),
            mode_roles=("spatial_y", "spatial_x", "spectral_feature"),
            image_size=(2, 3),
            image_mode=1,
            image_include=(True, True, False, True, True, True),
            original_unfolded_shape=unfolded.shape,
        ),
        data_role="X_hsi",
    )
    projection = {
        "projection_id": "fixture-hsi-v1",
        "title": "Qualified HSI",
        "n_samples": 6,
        "n_features": 4,
        "feature_axis_title": "Spectral coordinate",
        "feature_axis_units": None,
        "feature_axis_sha256": feature_axis_values_digest(np.arange(4.0)),
        "scientific_sha256": reference_source_projection_digest(unfolded),
        "native_reader_contract": "spectrasherpa.matlab-source/1",
        "analysis": {
            "primary_role": "X_hsi",
            "modality": "hsi",
            "technique": "Hyperspectral image",
            "target_type": None,
            "target_fields": [],
            "identity_fields": [],
            "group_fields": [],
            "ordered_samples": False,
        },
    }

    admitted = _finish_source_projection(
        source,
        projection,
        {
            "artifact_id": "fixture",
            "sha256": "a" * 64,
            "provider": "Fixture",
            "expected_size_bytes": 1,
            "provider_page": "https://example.invalid",
            "download_url": "https://example.invalid/fixture",
            "redistribution": "test-only",
        },
        {"sha256": "b" * 64, "path": "fixture.mat", "expected_size_bytes": 1},
        spatial_dataset=cube,
    ).dataset

    assert admitted.shape == (2, 3, 4)
    assert admitted.layout.image_size == (2, 3)
    assert admitted.layout.image_include == (True, True, False, True, True, True)
    assert admitted.layout.mode_roles == ("spatial_y", "spatial_x", "spectral_feature")
    np.testing.assert_array_equal(admitted.X.reshape(6, 4, order="F"), unfolded)
    if with_package_view:
        assert admitted.sample_axis is None
        assert admitted.extra["reference.package_id"] == "fixture-hsi-package"
        assert admitted.extra["reference.view_id"] == "fixture-hsi-view"
        assert admitted.extra["analysis.profile"]["identity_fields"] == []

    execution = ss.runtime.execute_operation(
        "model.parafac",
        parameters={"n_components": 1, "max_iter": 5, "tol": 1e-8},
        inputs={"default": admitted},
    )
    diagnostics = execution.diagnostics["sdk.operation"]
    assert diagnostics["input_shape"] == [2, 3, 4]
    assert diagnostics["mode_roles"] == ["spatial_y", "spatial_x", "spectral_feature"]
    assert diagnostics["spatial_mask_policy"] == parafac_core.PARAFAC_SPATIAL_MASK_POLICY
    assert diagnostics["included_spatial_cells"] == 5
    assert diagnostics["excluded_spatial_cells"] == 1
    assert execution.output().shape == (2, 1)


@pytest.mark.parametrize(
    ("primary_role", "expected_type"),
    [
        ("X_features", FeatureAxis),
        ("X_spectra", SpectralAxis),
        ("X_hsi", SpectralAxis),
    ],
)
def test_registered_projection_axis_class_follows_governed_data_role(
    primary_role: str,
    expected_type: type[FeatureAxis],
) -> None:
    axis = _axis_for_analysis_profile(
        {
            "values": np.asarray([0.0, 1.0]),
            "labels": ["pressure_kPa", "temperature_C"],
            "title": "Variable",
            "units": None,
        },
        {"primary_role": primary_role},
    )

    assert type(axis) is expected_type
    assert axis.labels == ["pressure_kPa", "temperature_C"]


def test_registered_feature_table_projection_does_not_gain_spectral_axis() -> None:
    data = np.asarray([[101.0, 20.0], [102.0, 21.0]])
    source = SherpaDataset(
        X=data,
        feature_axis=SpectralAxis(
            values=np.asarray([0.0, 1.0]),
            labels=["pressure_kPa", "temperature_C"],
            title="Variable",
        ),
        sample_axis=SampleAxis(labels=["wafer-1", "wafer-2"]),
        data_role="X_features",
    )
    projection = {
        "projection_id": "fixture-process-features-v1",
        "title": "Qualified process variables",
        "n_samples": 2,
        "n_features": 2,
        "feature_axis_title": "Variable",
        "feature_axis_units": None,
        "feature_axis_sha256": feature_axis_values_digest(np.asarray([0.0, 1.0])),
        "scientific_sha256": reference_source_projection_digest(data),
        "native_reader_contract": "spectrasherpa.matlab-process-log/1",
        "analysis": {
            "primary_role": "X_features",
            "modality": "features",
            "technique": "Process sensors",
            "target_type": None,
            "target_fields": [],
            "identity_fields": [],
            "group_fields": [],
            "ordered_samples": False,
        },
    }

    admitted = _finish_source_projection(
        source,
        projection,
        {
            "artifact_id": "fixture",
            "sha256": "a" * 64,
            "provider": "Fixture",
            "expected_size_bytes": 1,
            "provider_page": "https://example.invalid",
            "download_url": "https://example.invalid/fixture",
            "redistribution": "test-only",
        },
        {"sha256": "b" * 64, "path": "fixture.mat", "expected_size_bytes": 1},
    ).dataset

    assert admitted.data_role == "X_features"
    assert admitted.data_modality == "features"
    assert type(admitted.feature_axis) is FeatureAxis
    assert admitted.feature_axis.labels == ["pressure_kPa", "temperature_C"]


def test_registered_gatest_and_corn_manifests_declare_exact_source_scope() -> None:
    gatest = portable_reference_manifest("public-diesel-d4052-v1")
    corn = portable_reference_manifest("public-corn-m5-moisture-v1")

    assert gatest["source_scope"] == "prepared_d4052_gatest_projection"
    assert gatest["member_path"] == "D4052GATEST.mat"
    assert corn["source_scope"] == "registered_projection"
    assert corn["member_path"] == "corn.mat"
    assert gatest["artifact_id"] != corn["artifact_id"]


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def test_cgl_provider_partition_is_one_verified_row_annotation() -> None:
    complete = np.asarray([[1.0, 2.0], [3.0, 4.0], [5.0, 6.0]])
    properties = np.asarray([[10.0, 11.0], [20.0, 21.0], [30.0, 31.0]])
    assets = {
        "Xcal": SimpleNamespace(dataset=SimpleNamespace(X=complete[[0, 2]])),
        "Ycal": SimpleNamespace(dataset=SimpleNamespace(X=properties[[0, 2]])),
        "Xtest": SimpleNamespace(dataset=SimpleNamespace(X=complete[[1]])),
        "Ytest": SimpleNamespace(dataset=SimpleNamespace(X=properties[[1]])),
    }

    assert _verified_cgl_partition_roles(complete, properties, assets) == [
        "calibration",
        "test",
        "calibration",
    ]


def test_cgl_provider_partition_refuses_property_or_coverage_drift() -> None:
    complete = np.asarray([[1.0, 2.0], [3.0, 4.0]])
    properties = np.asarray([[10.0], [20.0]])
    assets = {
        "Xcal": SimpleNamespace(dataset=SimpleNamespace(X=complete[[0]])),
        "Ycal": SimpleNamespace(dataset=SimpleNamespace(X=properties[[0]])),
        "Xtest": SimpleNamespace(dataset=SimpleNamespace(X=complete[[1]])),
        "Ytest": SimpleNamespace(dataset=SimpleNamespace(X=np.asarray([[99.0]]))),
    }

    with pytest.raises(ReferenceMaterializationError, match="properties differ"):
        _verified_cgl_partition_roles(complete, properties, assets)

    assets["Ytest"] = SimpleNamespace(dataset=SimpleNamespace(X=properties[[1]]))
    assets["Xtest"] = SimpleNamespace(dataset=SimpleNamespace(X=np.empty((0, 2))))
    assets["Ytest"] = SimpleNamespace(dataset=SimpleNamespace(X=np.empty((0, 1))))
    with pytest.raises(ReferenceMaterializationError, match="does not cover"):
        _verified_cgl_partition_roles(complete, properties, assets)


def _write_archive(path: Path, member_bytes: bytes, *, duplicate: bool = False) -> bytes:
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("qualified.mat", member_bytes)
        if duplicate:
            archive.writestr("qualified.mat", member_bytes)
    return path.read_bytes()


def _registry(
    archive_bytes: bytes,
    member_bytes: bytes,
    *,
    native_reader_contract: str = "spectrasherpa.matlab-dso/1",
) -> ReferenceArtifactRegistry:
    X = np.asarray([[1.0, 2.0], [3.0, 4.0]])
    y = np.asarray([10.0, 11.0])
    axis = np.asarray([1000.0, 1100.0])
    artifact = ReferenceArtifact(
        {
            "artifact_id": "upstream-fixture-v1",
            "title": "Upstream fixture",
            "description": "Test-only upstream fixture",
            "provider": "Eigenvector Research",
            "provider_page": "https://eigenvector.com/resources/data-sets/",
            "download_url": "https://eigenvector.com/fixture.zip",
            "expected_size_bytes": len(archive_bytes),
            "sha256": _sha256(archive_bytes),
            "media_type": "application/zip",
            "redistribution": "upstream_only_not_redistributed",
            "attribution": "Test attribution",
            "no_endorsement": "No endorsement",
            "qualification_status": "qualified",
            "reviewed_at": "2026-08-30",
            "members": [
                {
                    "path": "qualified.mat",
                    "expected_size_bytes": len(member_bytes),
                    "sha256": _sha256(member_bytes),
                }
            ],
        }
    )
    projection = ReferenceProjection(
        {
            "projection_id": "fixture-projection-v1",
            "artifact_id": "upstream-fixture-v1",
            "title": "Fixture projection",
            "member_path": "qualified.mat",
            "native_reader_contract": native_reader_contract,
            "object_name": "spectra",
            "target_object_name": "targets",
            "target_index": 0,
            "target_name": "Moisture",
            "target_units": None,
            "n_samples": 2,
            "n_features": 2,
            "feature_axis_title": "Wavelength",
            "feature_axis_units": "nm",
            "feature_axis_sha256": feature_axis_values_digest(axis),
            "scientific_sha256": public_dataset_digest(X, y),
            "qualification_status": "qualified",
            "analysis": {
                "primary_role": "X_spectra",
                "modality": "spectra",
                "technique": "NIR",
                "target_type": "continuous",
                "target_fields": ["Moisture"],
                "identity_fields": [],
                "group_fields": [],
                "ordered_samples": False,
            },
        }
    )
    return ReferenceArtifactRegistry(artifacts=(artifact,), projections=(projection,))


def _ingestion_result(member_bytes: bytes, *, generated_target_labels: bool = False) -> IngestionResult:
    spectra = SherpaDataset(
        X=np.asarray([[1.0, 2.0], [3.0, 4.0]]),
        feature_axis=SpectralAxis(values=np.asarray([1000.0, 1100.0]), title="Wavelength", units="nm"),
        sample_axis=SampleAxis(labels=["Sample A", "Sample B"], title="Sample"),
        source_identity=DatasetSourceIdentity(source_format="eigenvector-dso", object_name="spectra"),
        title="Native spectra object",
        extra={"dso.userdata": {"instrument": "fixture"}},
    )
    targets = SherpaDataset(
        X=np.asarray([[10.0, 1.0], [11.0, 2.0]]),
        feature_axis=FeatureAxis(
            labels=["0", "1"] if generated_target_labels else ["Moisture", "Oil"],
            title="Feature" if generated_target_labels else "Property",
        ),
        sample_axis=SampleAxis(labels=["Sample A", "Sample B"], title="Sample"),
        source_identity=DatasetSourceIdentity(source_format="eigenvector-dso", object_name="targets"),
        title="Native target object",
    )
    return IngestionResult(
        format_id="matlab",
        variant="mat-v5",
        parser_id="spectrasherpa.matlab",
        parser_version="3",
        source_members=(
            SourceMember(name="qualified.mat", sha256=_sha256(member_bytes), size_bytes=len(member_bytes)),
        ),
        assets=(
            SpectralAsset(asset_id="spectra", dataset=spectra, dimension_roles=("sample", "feature")),
            SpectralAsset(asset_id="targets", dataset=targets, dimension_roles=("sample", "feature")),
        ),
    )


def test_renamed_exact_artifact_resolves_by_size_and_digest(tmp_path: Path) -> None:
    member = b"native-dso-placeholder"
    selected = tmp_path / "renamed-without-zip-extension.bin"
    archive = _write_archive(selected, member)
    registry = _registry(archive, member)

    assert (
        resolve_reference_artifact("fixture-projection-v1", explicit_path=selected, registry=registry)
        == selected.resolve()
    )


def test_filename_is_not_authority_and_wrong_bytes_refuse(tmp_path: Path) -> None:
    member = b"native-dso-placeholder"
    qualified = tmp_path / "qualified.zip"
    archive = _write_archive(qualified, member)
    registry = _registry(archive, member)
    impostor = tmp_path / "expected-upstream-name.zip"
    impostor.write_bytes(b"x" * len(archive))

    with pytest.raises(ReferenceMaterializationError, match="SHA-256"):
        resolve_reference_artifact("fixture-projection-v1", explicit_path=impostor, registry=registry)


def test_nonrecursive_reference_directory_resolution_uses_environment(tmp_path: Path) -> None:
    member = b"native-dso-placeholder"
    reference_dir = tmp_path / "chosen"
    reference_dir.mkdir()
    selected = reference_dir / "user-renamed-file"
    archive = _write_archive(selected, member)
    registry = _registry(archive, member)
    nested = reference_dir / "nested"
    nested.mkdir()
    (nested / "ignored-copy").write_bytes(archive)

    assert (
        resolve_reference_artifact(
            "fixture-projection-v1",
            environ={"SPECTRA_REFERENCE_DIR": str(reference_dir)},
            cwd=tmp_path / "unrelated",
            registry=registry,
        )
        == selected.resolve()
    )


def test_reference_directory_search_is_bounded(tmp_path: Path) -> None:
    member = b"native-dso-placeholder"
    archive_path = tmp_path / "source.zip"
    archive = _write_archive(archive_path, member)
    registry = _registry(archive, member)
    search = tmp_path / "many"
    search.mkdir()
    for index in range(3):
        (search / f"item-{index}").write_bytes(b"no")

    with pytest.raises(ReferenceMaterializationError, match="entry non-recursive search bound"):
        resolve_reference_artifact(
            "fixture-projection-v1", search_directory=search, registry=registry, max_search_entries=2
        )


def test_materialization_preserves_native_dso_metadata_and_adds_path_free_lineage(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import spectra_sherpa.sdk as ss

    member = b"native-dso-placeholder"
    selected = tmp_path / "anything.dat"
    archive = _write_archive(selected, member)
    registry = _registry(archive, member)
    observed_member: list[bytes] = []

    def _ingest(path: Path) -> IngestionResult:
        observed_member.append(path.read_bytes())
        return _ingestion_result(member)

    monkeypatch.setattr("spectra_sherpa.app.lib.reference_materialization.ingest", _ingest)
    materialized = materialize_reference_projection(selected, "fixture-projection-v1", registry=registry)
    repeated = materialize_reference_projection(selected, "fixture-projection-v1", registry=registry)

    assert observed_member == [member, member]
    assert materialized.dataset.shape == (2, 2)
    assert materialized.dataset.target.tolist() == [10.0, 11.0]
    assert materialized.dataset.target_context.selected_target == "Moisture"
    assert materialized.dataset.sample_axis.labels == ["Sample A", "Sample B"]
    assert materialized.dataset.sample_axis.sample_table == {
        "sample_id": ["Sample A", "Sample B"],
        "source_label": ["Sample A", "Sample B"],
        "Moisture": [10.0, 11.0],
    }
    assert materialized.dataset.extra["dso.userdata"] == {"instrument": "fixture"}
    assert materialized.dataset.extra["reference.projection_id"] == "fixture-projection-v1"
    assert materialized.dataset.provenance.operations[-1] == "import.registered_reference"
    assert materialized.dataset.provenance[-1].timestamp == ""
    assert repeated.dataset.scientific_digest == materialized.dataset.scientific_digest
    source = materialized.dataset.meta["source_collection"]
    binding = materialized.dataset.meta["supervision_binding"]
    assert source["files"] == [
        {
            "file_name": "qualified.mat",
            "size_bytes": len(member),
            "sha256": _sha256(member),
            "prepared_data_sha256": hashlib.sha256(b"{}").hexdigest(),
        }
    ]
    for field in (
        "manifest_digest",
        "collection_definition_sha256",
        "scientific_collection_sha256",
    ):
        assert len(source[field]) == 64
    assert binding["target_authority"]["column"] == "Moisture"
    assert binding["target_authority"]["target_type"] == "continuous"
    assert repeated.dataset.meta["source_collection"] == source
    assert repeated.dataset.meta["supervision_binding"] == binding

    result = ss.explore.pca(materialized.dataset, n_components=1)
    assert result.scores.shape == (2, 1)

    tampered = materialized.dataset.copy()
    assert tampered.sample_axis is not None and tampered.sample_axis.sample_table is not None
    tampered_axis = tampered.sample_axis.model_copy(deep=True)
    tampered_axis.sample_table["Moisture"][0] = 99.0
    tampered.sample_axis = tampered_axis
    with pytest.raises(ValueError, match="does not match its exact sample table"):
        ss.explore.pca(tampered, n_components=1)

    changed_source = materialized.dataset.copy()
    changed_source.meta["source_collection"]["files"][0]["size_bytes"] += 1
    with pytest.raises(ValueError, match="does not match its exact members"):
        ss.explore.pca(changed_source, n_components=1)
    serialized = json.dumps(materialized.portable_reference, sort_keys=True)
    assert materialized.portable_reference["schema_version"] == PORTABLE_REFERENCE_SCHEMA
    assert str(tmp_path) not in serialized
    assert selected.name not in serialized


def test_package_view_materializes_complete_annotations_without_default_target(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import spectra_sherpa.sdk as ss
    from spectra_sherpa.app.services.dag.spectral_capability import SpectralCapabilityError

    member = b"native-dso-placeholder"
    selected = tmp_path / "anything.dat"
    archive = _write_archive(selected, member)
    registry = _registry(archive, member)
    fields = [
        {"index": 0, "name": "Moisture", "target_type": "continuous", "units": None},
        {"index": 1, "name": "Oil", "target_type": "continuous", "units": None},
    ]
    values = np.asarray([[10.0, 1.0], [11.0, 2.0]])
    package_view = {
        "package_id": "fixture-package-v1",
        "package_title": "Fixture package",
        "package_description": "Two aligned instrument views",
        "view_id": "fixture-m5",
        "view_label": "M5",
        "instrument": "M5",
        "cohort": "fixture-2",
        "annotation_table": {
            "annotation_table_id": "fixture-properties",
            "object_name": "targets",
            "n_rows": 2,
            "fields": fields,
            "values_sha256": reference_annotation_table_digest(values, fields),
        },
        "initially_selected": True,
        "relations": [],
    }

    monkeypatch.setattr(
        "spectra_sherpa.app.lib.reference_materialization.ingest", lambda _path: _ingestion_result(member)
    )
    monkeypatch.setattr(
        "spectra_sherpa.app.lib.reference_materialization.package_view_projection",
        lambda projection_id: package_view if projection_id == "fixture-projection-v1" else None,
    )
    materialized = materialize_reference_projection(selected, "fixture-projection-v1", registry=registry)
    dataset = materialized.dataset

    assert dataset.target.shape == (2, 2)
    assert dataset.target.tolist() == values.tolist()
    assert dataset.target_context.target_names == ["Moisture", "Oil"]
    assert dataset.target_context.selected_target is None
    assert dataset.sample_axis.labels == ["fixture-m5-001", "fixture-m5-002"]
    assert dataset.sample_axis.sample_table == {
        "sample_id": ["fixture-m5-001", "fixture-m5-002"],
        "specimen_id": ["fixture-2-001", "fixture-2-002"],
        "instrument": ["M5", "M5"],
        "Moisture": [10.0, 11.0],
        "Oil": [1.0, 2.0],
    }
    assert dataset.get_extra("analysis.profile")["target_fields"] == ["Moisture", "Oil"]
    assert dataset.get_extra("reference.package_id") == "fixture-package-v1"
    assert dataset.get_extra("reference.view_id") == "fixture-m5"
    assert materialized.portable_reference["dataset_package"] == package_view
    assert "supervision_binding" not in dataset.meta
    assert len(dataset.meta["source_collection"]["scientific_collection_sha256"]) == 64
    assert ss.explore.pca(dataset, n_components=1).scores.shape == (2, 1)

    # The export reader must rebind a selected response against the admitted
    # annotation table, without weakening its source/annotation checks.
    monkeypatch.setattr(
        "spectra_sherpa.app.lib.reference_materialization.materialize_reference_member",
        lambda *_args: SimpleNamespace(dataset=dataset.copy()),
    )
    for column, expected in (("Moisture", [10.0, 11.0]), ("Oil", [1.0, 2.0])):
        bound = ss.data.read_registered_reference(
            selected,
            projection_id="fixture-projection-v1",
            prepared_overrides={
                "selected_target": column,
                "target_column": column,
                "target_type": "continuous",
                "target_mode": "single",
            },
        )
        assert bound.target.tolist() == expected
        assert bound.target_context.target_names == [column]
        assert bound.meta["supervision_binding"]["target_authority"]["column"] == column
        assert ss.explore.pca(bound, n_components=1).scores.shape == (2, 1)
    with pytest.raises(ValueError):
        ss.data.read_registered_reference(
            selected, projection_id="fixture-projection-v1", prepared_overrides={"selected_target": "Unknown"}
        )

    tampered = dataset.copy()
    assert tampered.sample_axis is not None and tampered.sample_axis.sample_table is not None
    axis = tampered.sample_axis.model_copy(deep=True)
    axis.sample_table["Oil"][0] = 9.0
    tampered.sample_axis = axis
    with pytest.raises(SpectralCapabilityError, match="does not match its exact annotations"):
        ss.explore.pca(tampered, n_components=1)

    changed_source = dataset.copy()
    changed_source.meta["source_collection"]["files"][0]["size_bytes"] += 1
    with pytest.raises(SpectralCapabilityError, match="does not match its exact members"):
        ss.explore.pca(changed_source, n_components=1)


def test_package_view_collection_issues_recomputable_supervision_authority(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from spectra_sherpa.app.services.dag.supervision_binding import attach_sample_table_supervision
    from spectra_sherpa.app.services.model_application import _loaded_files_to_sherpa

    member = b"native-dso-placeholder"
    selected = tmp_path / "provider.zip"
    archive = _write_archive(selected, member)
    registry = _registry(archive, member)
    fields = [
        {"index": 0, "name": "Moisture", "target_type": "continuous", "units": None},
        {"index": 1, "name": "Oil", "target_type": "continuous", "units": None},
    ]
    values = np.asarray([[10.0, 1.0], [11.0, 2.0]])
    package_view = {
        "package_id": "fixture-package-v1",
        "package_title": "Fixture package",
        "package_description": "Two aligned instrument views",
        "view_id": "fixture-m5",
        "view_label": "M5",
        "instrument": "M5",
        "cohort": "fixture-2",
        "annotation_table": {
            "annotation_table_id": "fixture-properties",
            "object_name": "targets",
            "n_rows": 2,
            "fields": fields,
            "values_sha256": reference_annotation_table_digest(values, fields),
        },
        "initially_selected": True,
        "relations": [],
    }
    monkeypatch.setattr(
        "spectra_sherpa.app.lib.reference_materialization.ingest", lambda _path: _ingestion_result(member)
    )
    monkeypatch.setattr(
        "spectra_sherpa.app.lib.reference_materialization.package_view_projection",
        lambda projection_id: package_view if projection_id == "fixture-projection-v1" else None,
    )
    dataset = materialize_reference_projection(selected, "fixture-projection-v1", registry=registry).dataset
    loaded = SimpleNamespace(
        dataset=dataset,
        file_name="raw/fixture-m5.mat",
        source_members=(SourceMember(name="fixture-m5.mat", sha256=_sha256(member), size_bytes=len(member)),),
        selected_asset_id="fixture-projection-v1",
        prepared_overrides={},
    )

    collection = _loaded_files_to_sherpa([loaded], "Fixture package", definition=None)
    source = collection.meta["source_collection"]

    assert source["scientific_collection_schema_version"] == "spectrasherpa-scientific-collection/2"
    assert len(source["collection_definition_sha256"]) == 64
    assert len(source["scientific_dataset_projection_sha256"]) == 64
    supervised = attach_sample_table_supervision(
        collection,
        target_column="Moisture",
        target_type="continuous",
        node_id="registered-reference-test",
    )
    assert supervised.target.tolist() == [10.0, 11.0]
    assert (
        supervised.meta["supervision_binding"]["collection_definition_sha256"] == source["collection_definition_sha256"]
    )


def test_registered_feature_annotations_with_missing_values_are_admitted_without_supervision() -> None:
    import spectra_sherpa.sdk as ss

    dataset = SherpaDataset(
        X=np.asarray([[1.0, 2.0], [2.0, 4.0], [4.0, 8.0]]),
        feature_axis=FeatureAxis(labels=["pressure", "temperature"], title="Feature"),
        sample_axis=SampleAxis(
            labels=["A", "B", "C"],
            title="Observation",
            sample_table={
                "sample_id": ["A", "B", "C"],
                "batch_note": ["reference", None, "challenge"],
            },
        ),
        data_role="X_features",
        extra={
            "reference.artifact_id": "fixture-artifact-v1",
            "reference.artifact_sha256": "a" * 64,
            "reference.member_sha256": "b" * 64,
            "reference.projection_id": "fixture-features-v1",
        },
    )
    admitted = _bind_registered_reference_source(
        dataset,
        {"path": "fixture.csv", "expected_size_bytes": 12, "sha256": "b" * 64},
    )

    assert "supervision_binding" not in admitted.meta
    assert admitted.sample_axis.sample_table["batch_note"] == ["reference", None, "challenge"]
    assert ss.explore.pca(admitted, n_components=1).scores.shape == (3, 1)


def test_multi_member_registered_collection_identity_binds_each_qualified_view(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from spectra_sherpa.app.services.model_application import _loaded_files_to_sherpa

    member = b"native-dso-placeholder"
    selected = tmp_path / "provider.zip"
    archive = _write_archive(selected, member)
    registry = _registry(archive, member)
    monkeypatch.setattr(
        "spectra_sherpa.app.lib.reference_materialization.ingest", lambda _path: _ingestion_result(member)
    )
    first = materialize_reference_projection(selected, "fixture-projection-v1", registry=registry).dataset
    second = first.copy()
    second.extra["reference.projection_id"] = "fixture-projection-v2"
    second_axis = second.sample_axis
    assert second_axis is not None and second_axis.sample_table is not None
    second_axis.labels = ["View B 1", "View B 2"]
    second_axis.sample_table["sample_id"] = ["View B 1", "View B 2"]
    second.sample_axis = second_axis

    def loaded(dataset: SherpaDataset, *, name: str, projection_id: str) -> SimpleNamespace:
        return SimpleNamespace(
            dataset=dataset,
            file_name=f"raw/{name}.mat",
            source_members=(SourceMember(name=f"{name}.mat", sha256=_sha256(member), size_bytes=len(member)),),
            selected_asset_id=projection_id,
            prepared_overrides={},
        )

    admitted = [
        loaded(first, name="view-a", projection_id="fixture-projection-v1"),
        loaded(second, name="view-b", projection_id="fixture-projection-v2"),
    ]
    collection = _loaded_files_to_sherpa(admitted, "Registered views", definition=None)
    repeated = _loaded_files_to_sherpa(admitted, "Registered views", definition=None)
    source = collection.meta["source_collection"]

    assert source["scientific_collection_schema_version"] == "spectrasherpa-scientific-collection/2"
    assert len(source["collection_definition_sha256"]) == 64
    assert len(source["scientific_dataset_projection_sha256"]) == 64
    assert repeated.meta["source_collection"]["scientific_collection_sha256"] == source["scientific_collection_sha256"]

    changed = second.copy()
    changed_axis = changed.sample_axis
    assert changed_axis is not None and changed_axis.sample_table is not None
    changed_axis.sample_table["Moisture"][0] = 99.0
    changed.sample_axis = changed_axis
    changed_collection = _loaded_files_to_sherpa(
        [admitted[0], loaded(changed, name="view-b", projection_id="fixture-projection-v2")],
        "Registered views",
        definition=None,
    )

    assert changed_collection.meta["source_collection"]["manifest_digest"] == source["manifest_digest"]
    assert (
        changed_collection.meta["source_collection"]["scientific_collection_sha256"]
        != source["scientific_collection_sha256"]
    )


def test_array_pair_package_uses_closed_annotation_authority_not_generated_numeric_labels(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    member = b"native-array-pair-placeholder"
    selected = tmp_path / "anything.dat"
    archive = _write_archive(selected, member)
    registry = _registry(
        archive,
        member,
        native_reader_contract="spectrasherpa.matlab-array-pair/1",
    )
    fields = [
        {"index": 0, "name": "Moisture", "target_type": "continuous", "units": None},
        {"index": 1, "name": "Oil", "target_type": "continuous", "units": None},
    ]
    values = np.asarray([[10.0, 1.0], [11.0, 2.0]])
    package_view = {
        "package_id": "fixture-package-v1",
        "package_title": "Fixture package",
        "package_description": "Plain arrays with registered annotations",
        "view_id": "fixture-array",
        "view_label": "Array",
        "instrument": "Fixture",
        "cohort": "fixture-2",
        "annotation_table": {
            "annotation_table_id": "fixture-properties",
            "object_name": "targets",
            "n_rows": 2,
            "fields": fields,
            "values_sha256": reference_annotation_table_digest(values, fields),
        },
        "initially_selected": True,
        "relations": [
            {
                "relation_id": "unaligned",
                "relation_type": "alignment_unverified",
                "view_ids": ["fixture-array", "fixture-other"],
                "row_identity": "not asserted",
            }
        ],
    }

    monkeypatch.setattr(
        "spectra_sherpa.app.lib.reference_materialization.ingest",
        lambda _path: _ingestion_result(member, generated_target_labels=True),
    )
    monkeypatch.setattr(
        "spectra_sherpa.app.lib.reference_materialization.package_view_projection",
        lambda projection_id: package_view if projection_id == "fixture-projection-v1" else None,
    )

    dataset = materialize_reference_projection(
        selected,
        "fixture-projection-v1",
        registry=registry,
    ).dataset

    assert dataset.target_context.target_names == ["Moisture", "Oil"]
    assert dataset.sample_axis.sample_table["Moisture"] == [10.0, 11.0]
    assert "specimen_id" in dataset.get_extra("analysis.profile")["identity_fields"]
    assert dataset.get_extra("analysis.profile")["group_fields"] == []


def test_wrong_registered_member_digest_refuses_before_native_ingestion(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    member = b"native-dso-placeholder"
    selected = tmp_path / "source.zip"
    archive = _write_archive(selected, member)
    registry = _registry(archive, b"different-member-bytes")
    called = False

    def _unexpected(_path: Path) -> IngestionResult:
        nonlocal called
        called = True
        raise AssertionError("native ingestion must not run")

    monkeypatch.setattr("spectra_sherpa.app.lib.reference_materialization.ingest", _unexpected)
    with pytest.raises(ReferenceMaterializationError, match="member digest"):
        materialize_reference_projection(selected, "fixture-projection-v1", registry=registry)
    assert called is False


def test_duplicate_registered_member_refuses_even_when_archive_digest_matches(tmp_path: Path) -> None:
    member = b"native-dso-placeholder"
    selected = tmp_path / "duplicate.zip"
    with pytest.warns(UserWarning, match="Duplicate name"):
        archive = _write_archive(selected, member, duplicate=True)
    registry = _registry(archive, member)

    with pytest.raises(ReferenceMaterializationError, match="one exact registered member"):
        materialize_reference_projection(selected, "fixture-projection-v1", registry=registry)


def test_portable_manifest_contains_rebinding_authority_not_local_paths(tmp_path: Path) -> None:
    member = b"native-dso-placeholder"
    selected = tmp_path / "source.zip"
    archive = _write_archive(selected, member)
    registry = _registry(archive, member)

    manifest = portable_reference_manifest("fixture-projection-v1", registry=registry)

    assert manifest["artifact_size_bytes"] == len(archive)
    assert manifest["artifact_sha256"] == _sha256(archive)
    assert manifest["download_url"] == "https://eigenvector.com/fixture.zip"
    assert manifest["analysis_profile"]["target_type"] == "continuous"
    assert "path" not in manifest
    assert "filename" not in manifest


def test_symlink_is_not_an_admitted_reference_source(tmp_path: Path) -> None:
    member = b"native-dso-placeholder"
    selected = tmp_path / "source.zip"
    archive = _write_archive(selected, member)
    registry = _registry(archive, member)
    link = tmp_path / "link.zip"
    link.symlink_to(selected)

    with pytest.raises(ReferenceMaterializationError, match="non-symlink"):
        resolve_reference_artifact("fixture-projection-v1", explicit_path=link, registry=registry)


def test_verified_projection_can_persist_exact_member_for_workspace_custody(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    member = b"native-dso-placeholder"
    selected = tmp_path / "renamed-user-download"
    archive = _write_archive(selected, member)
    registry = _registry(archive, member)
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    retained = workspace / "qualified.mat"
    monkeypatch.setattr(
        "spectra_sherpa.app.lib.reference_materialization.ingest",
        lambda _path: _ingestion_result(member),
    )

    materialize_reference_projection(
        selected,
        "fixture-projection-v1",
        registry=registry,
        persist_member_to=retained,
    )

    assert retained.read_bytes() == member
    if os.name != "nt":  # Windows uses the containing profile ACL.
        assert retained.stat().st_mode & 0o777 == 0o600


def test_retained_exact_member_reprojects_without_upstream_archive(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    member = b"native-dso-placeholder"
    archive_path = tmp_path / "source.zip"
    archive = _write_archive(archive_path, member)
    registry = _registry(archive, member)
    retained = tmp_path / "qualified.mat"
    retained.write_bytes(member)
    monkeypatch.setattr(
        "spectra_sherpa.app.lib.reference_materialization.ingest",
        lambda _path: _ingestion_result(member),
    )

    materialized = materialize_reference_member(retained, "fixture-projection-v1", registry=registry)

    assert materialized.dataset.shape == (2, 2)
    assert materialized.dataset.target.tolist() == [10.0, 11.0]


def test_provider_archive_round_trip_reaches_the_project_collection_identity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Exercise the complete archive -> retained member -> project path."""

    from spectra_sherpa.app.lib.registered_reference_storage import (
        write_registered_reference_sidecar,
    )
    from spectra_sherpa.app.services.dag.nodes.data.loaders import ExperimentDatasetReader
    from spectra_sherpa.app.services.model_application import _loaded_files_to_sherpa

    member = b"native-dso-placeholder"
    selected = tmp_path / "provider-download.zip"
    archive = _write_archive(selected, member)
    registry = _registry(archive, member)
    retained = tmp_path / "user-renamed-source.mat"
    monkeypatch.setattr(
        "spectra_sherpa.app.lib.reference_materialization.ingest",
        lambda _path: _ingestion_result(member),
    )
    monkeypatch.setattr(
        "spectra_sherpa.app.lib.reference_materialization.load_reference_artifact_registry",
        lambda: registry,
    )
    monkeypatch.setattr(
        "spectra_sherpa.app.lib.registered_reference_storage.portable_reference_manifest",
        lambda projection_id: portable_reference_manifest(projection_id, registry=registry),
    )

    admitted = materialize_reference_projection(
        selected,
        "fixture-projection-v1",
        registry=registry,
        persist_member_to=retained,
    )
    sidecar = write_registered_reference_sidecar(retained, admitted.portable_reference)
    loaded = ExperimentDatasetReader("reference-round-trip", {"dataset_id": 1})._load_file(
        str(retained),
        file_name="raw/user-renamed-source.mat",
        asset_id="fixture-projection-v1",
        prepared_overrides={},
    )
    collection = _loaded_files_to_sherpa([loaded], "Provider reference", definition=None)

    assert collection.shape == (2, 2)
    assert collection.target.tolist() == [10.0, 11.0]
    assert collection.target_context.selected_target == "Moisture"
    assert collection.feature_axis.title == "Wavelength"
    assert collection.feature_axis.units == "nm"
    assert collection.get_extra("reference.projection_id") == "fixture-projection-v1"
    assert collection.get_extra("reference.artifact_id") == "upstream-fixture-v1"
    assert collection.get_extra("reference.artifact_sha256") == admitted.portable_reference["artifact_sha256"]
    assert collection.get_extra("reference.provider") == "Eigenvector Research"
    assert collection.meta["source_collection"]["scientific_collection_sha256"]
    # Collection assembly is an identity-bearing projection. A grant must
    # govern this final identity, not the pre-assembly in-memory object's.
    assert collection.scientific_digest != admitted.dataset.scientific_digest

    # A deployed /2 sidecar may predate source_scope. Re-admission must retain
    # every identity bound into an existing managed trial grant, without a
    # storage migration or an upstream download.
    payload = json.loads(sidecar.read_text())
    del payload["portable_reference"]["source_scope"]
    sidecar.write_text(json.dumps(payload))
    legacy_bytes = sidecar.read_bytes()
    reader = ExperimentDatasetReader("legacy-reference-round-trip", {"dataset_id": 1})
    legacy_loaded = reader._load_file(
        str(retained),
        file_name="raw/user-renamed-source.mat",
        asset_id="fixture-projection-v1",
        prepared_overrides={},
    )
    legacy_collection = _loaded_files_to_sherpa([legacy_loaded], "Provider reference", definition=None)
    assert legacy_collection.meta["source_collection"] == collection.meta["source_collection"]
    assert legacy_collection.scientific_digest == collection.scientific_digest
    assert sidecar.read_bytes() == legacy_bytes

    # Normalizing descriptive metadata must not bypass retained-member custody.
    retained.write_bytes(b"x" * len(member))
    with pytest.raises(ReferenceMaterializationError, match="member digest differs"):
        reader._load_file(
            str(retained),
            file_name="raw/user-renamed-source.mat",
            asset_id="fixture-projection-v1",
            prepared_overrides={},
        )


@pytest.mark.asyncio
async def test_registered_reference_collection_node_accepts_pinned_projection_identity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Registered references carry generated collection identity into DAG execution."""

    from spectra_sherpa.app.lib.registered_reference_storage import write_registered_reference_sidecar
    from spectra_sherpa.app.services.dag.nodes.data.loaders import CollectionLoadNode, ExperimentDatasetReader
    from spectra_sherpa.app.services.model_application import _loaded_files_to_sherpa

    member = b"native-dso-placeholder"
    selected = tmp_path / "provider-download.zip"
    archive = _write_archive(selected, member)
    registry = _registry(archive, member)
    retained = tmp_path / "corn-m5.mat"
    monkeypatch.setattr(
        "spectra_sherpa.app.lib.reference_materialization.ingest",
        lambda _path: _ingestion_result(member),
    )
    monkeypatch.setattr(
        "spectra_sherpa.app.lib.reference_materialization.load_reference_artifact_registry",
        lambda: registry,
    )
    monkeypatch.setattr(
        "spectra_sherpa.app.lib.registered_reference_storage.portable_reference_manifest",
        lambda projection_id: portable_reference_manifest(projection_id, registry=registry),
    )

    admitted = materialize_reference_projection(
        selected,
        "fixture-projection-v1",
        registry=registry,
        persist_member_to=retained,
    )
    write_registered_reference_sidecar(retained, admitted.portable_reference)
    loader = ExperimentDatasetReader("reference-admission", {"dataset_id": 1})
    loaded = loader._load_file(
        str(retained),
        file_name="raw/corn-m5.mat",
        asset_id="fixture-projection-v1",
        prepared_overrides={},
    )
    collection = _loaded_files_to_sherpa([loaded], "Eigenvector Corn M5", definition=None)
    source_collection = collection.meta["source_collection"]

    class Resolver:
        async def resolve_experiment_collection(self, *, experiment_id: int, stage: str = "raw"):
            assert (experiment_id, stage) == (121, "raw")
            return ResolvedExperimentCollection(
                experiment_id=121,
                experiment_name="Eigenvector Corn M5",
                files=(
                    ResolvedExperimentFile(
                        path=str(retained),
                        original_file_path="raw/corn-m5.mat",
                        created_datetime="2026-09-04T22:07:21+00:00",
                        file_id=206,
                        stage="raw",
                        size_bytes=len(member),
                        sha256=_sha256(member),
                    ),
                ),
                collection_definition_bytes=None,
            )

    reader = ExperimentDatasetReader(
        "data_1",
        {
            "dataset_id": 121,
            "stage": "raw",
            "asset_id": "fixture-projection-v1",
            "selected_file_ids": ["206"],
            "source_manifest_sha256": source_collection["manifest_digest"],
            "collection_definition_sha256": source_collection["collection_definition_sha256"],
            "scientific_collection_sha256": source_collection["scientific_collection_sha256"],
        },
        source_resolver=Resolver(),
    )

    reader_result = await reader.execute()

    assert reader_result["default"].meta["source_collection"]["collection_definition_sha256"] == (
        source_collection["collection_definition_sha256"]
    )
    assert reader_result["default"].meta["source_collection"]["scientific_collection_sha256"] == (
        source_collection["scientific_collection_sha256"]
    )

    node = CollectionLoadNode(
        "data_1",
        {
            "experiment_id": 121,
            "stage": "raw",
            "asset_id": "fixture-projection-v1",
            "selected_file_ids": ["206"],
            "source_manifest_sha256": source_collection["manifest_digest"],
            "collection_definition_sha256": source_collection["collection_definition_sha256"],
            "scientific_collection_sha256": source_collection["scientific_collection_sha256"],
            "target_authority": None,
            "group_column": "",
        },
    )
    node.bind_execution_runtime(ExecutionRuntime(dataset_source_resolver=Resolver()))

    node_result = await node.execute()

    assert node_result["default"].meta["source_collection"]["collection_definition_sha256"] == (
        source_collection["collection_definition_sha256"]
    )
    assert node_result["default"].meta["source_collection"]["scientific_collection_sha256"] == (
        source_collection["scientific_collection_sha256"]
    )


def test_persisted_member_is_removed_when_post_copy_verification_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    member = b"native-dso-placeholder"
    selected = tmp_path / "source.zip"
    archive = _write_archive(selected, member)
    registry = _registry(archive, member)
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    retained = workspace / "qualified.mat"
    monkeypatch.setattr(
        "spectra_sherpa.app.lib.reference_materialization.ingest",
        lambda _path: _ingestion_result(member),
    )
    monkeypatch.setattr(
        "spectra_sherpa.app.lib.reference_materialization._verify_registered_member",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(ReferenceMaterializationError("post-copy refusal")),
    )

    with pytest.raises(ReferenceMaterializationError, match="post-copy refusal"):
        materialize_reference_projection(
            selected,
            "fixture-projection-v1",
            registry=registry,
            persist_member_to=retained,
        )

    assert not retained.exists()
