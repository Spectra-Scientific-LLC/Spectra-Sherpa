from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
from scipy.io import loadmat, savemat

from spectra_sherpa.app.lib import eigenvector
from spectra_sherpa.app.lib.axes import SampleAxis, SpectralAxis
from spectra_sherpa.app.lib.eigenvector import parse_eigenvector_mat
from spectra_sherpa.io import (
    ParserLimitError,
    ParserLimits,
    UnreadableSpectrumError,
    UnsupportedFormatVariantError,
    ingest,
)
from spectra_sherpa.io.base import BoundedSource
from spectra_sherpa.io.formats.dso import (
    DecodedDSO,
    decoded_dso_footprint,
    map_decoded_dso,
    scipy_struct_fields,
)

_FIELDS = (
    "data",
    "name",
    "type",
    "author",
    "date",
    "moddate",
    "description",
    "axisscale",
    "axisscalename",
    "axisscaletype",
    "axistype",
    "label",
    "labelname",
    "title",
    "titlename",
    "class",
    "classname",
    "classlookup",
    "include",
    "history",
    "userdata",
    "uniqueid",
    "datasetversion",
)


def _cell(rows: list[list[object]]) -> np.ndarray:
    result = np.empty((len(rows), max(len(row) for row in rows)), dtype=object)
    for row_index in range(result.shape[0]):
        for column_index in range(result.shape[1]):
            result[row_index, column_index] = np.empty((0, 0))
    for row_index, row in enumerate(rows):
        for column_index, value in enumerate(row):
            result[row_index, column_index] = value
    return result


def _dso_struct(
    data: np.ndarray,
    *,
    name: str = "Three-way calibration",
    source_type: str = "data",
    include_field: str = "include",
    legacy_include: np.ndarray | None = None,
) -> np.ndarray:
    shape = data.shape
    mode_count = data.ndim
    fields = list(_FIELDS)
    if include_field == "includ":
        fields[fields.index("include")] = "includ"
    elif legacy_include is not None:
        fields.append("includ")
    if source_type == "image":
        fields.extend(
            (
                "imagemode",
                "imagesize",
                "imageinclude",
                "imageaxisscale",
                "imageaxisscalename",
                "imageaxisscaletype",
                "imageaxistype",
            )
        )
    result = np.empty((1, 1), dtype=[(field, "O") for field in fields])
    result["data"][0, 0] = data
    result["name"][0, 0] = np.array([name])
    result["type"][0, 0] = np.array([source_type])
    result["author"][0, 0] = np.array(["A. Scientist"])
    result["date"][0, 0] = np.array(["2026-08-25"])
    result["moddate"][0, 0] = np.array(["2026-08-26"])
    result["description"][0, 0] = np.array(["Generated DSO parser fixture"])

    scales: list[list[object]] = []
    scale_names: list[list[object]] = []
    scale_types: list[list[object]] = []
    labels: list[list[object]] = []
    label_names: list[list[object]] = []
    titles: list[list[object]] = []
    title_names: list[list[object]] = []
    classes: list[list[object]] = []
    class_names: list[list[object]] = []
    class_lookups: list[list[object]] = []
    includes: list[list[object]] = []
    for mode, length in enumerate(shape):
        primary = np.arange(length, dtype=float) + mode * 100
        alternate = primary + 0.5
        scales.append([primary, alternate])
        scale_names.append(
            [
                np.array(["wavenumber" if mode == mode_count - 1 else f"mode {mode + 1} coordinate"]),
                np.array(["wavelength" if mode == mode_count - 1 else f"mode {mode + 1} alternate"]),
            ]
        )
        scale_types.append(
            [
                np.array(["wavenumber" if mode == mode_count - 1 else "index"]),
                np.array(["wavelength" if mode == mode_count - 1 else "alternate"]),
            ]
        )
        labels.append(
            [
                np.array([f"M{mode + 1}-{index + 1}" for index in range(length)], dtype=object),
                np.array([f"Alt-{mode + 1}-{index + 1}" for index in range(length)], dtype=object),
            ]
        )
        label_names.append([np.array(["primary labels"]), np.array(["alternate labels"])])
        titles.append(
            [[f"Mode {mode + 1}"], ["Wavenumber" if mode == mode_count - 1 else f"Alternate mode {mode + 1}"]]
        )
        title_names.append([np.array(["primary title"]), np.array(["alternate title"])])
        classes.append(
            [
                np.array(["A" if index % 2 == 0 else "B" for index in range(length)], dtype=object),
                np.arange(1, length + 1, dtype=np.int32),
            ]
        )
        class_names.append([np.array(["group"]), np.array(["sequence"])])
        group_lookup = np.empty((2, 2), dtype=object)
        group_lookup[:, 0] = ["A", "B"]
        group_lookup[:, 1] = ["Group A", "Group B"]
        sequence_lookup = np.empty((length, 2), dtype=object)
        sequence_lookup[:, 0] = np.arange(1, length + 1, dtype=np.int32)
        sequence_lookup[:, 1] = [f"Sequence {index + 1}" for index in range(length)]
        class_lookups.append([group_lookup, sequence_lookup])
        includes.append([np.arange(1, length + 1, 2, dtype=np.int32)])
    result["axisscale"][0, 0] = _cell(scales)
    result["axisscalename"][0, 0] = _cell(scale_names)
    result["axisscaletype"][0, 0] = _cell(scale_types)
    result["axistype"][0, 0] = _cell([[np.array(["none"])] for _ in shape])
    result["label"][0, 0] = _cell(labels)
    result["labelname"][0, 0] = _cell(label_names)
    result["title"][0, 0] = _cell(titles)
    result["titlename"][0, 0] = _cell(title_names)
    result["class"][0, 0] = _cell(classes)
    result["classname"][0, 0] = _cell(class_names)
    result["classlookup"][0, 0] = _cell(class_lookups)
    result[include_field][0, 0] = _cell(includes)
    if legacy_include is not None:
        result["includ"][0, 0] = legacy_include
    result["history"][0, 0] = np.array([["Imported", "Correction: none"]], dtype=object)
    result["userdata"][0, 0] = {"instrument": "Generated", "replicates": 3}
    result["uniqueid"][0, 0] = np.array(["generated-dso-001"])
    result["datasetversion"][0, 0] = np.array(["5.0"])
    if source_type == "image":
        result["imagemode"][0, 0] = np.array([[2]], dtype=np.int32)
        result["imagesize"][0, 0] = np.array([[2, data.shape[1] // 2]], dtype=np.int32)
        result["imageinclude"][0, 0] = _cell(
            [[np.array([1, 2], dtype=np.int32)], [np.array([1, data.shape[1] // 2], dtype=np.int32)]]
        )
        result["imageaxisscale"][0, 0] = _cell(
            [[np.array([0.0, 10.0])], [np.arange(data.shape[1] // 2, dtype=float) * 20.0]]
        )
        result["imageaxisscalename"][0, 0] = _cell([[np.array(["row position"])], [np.array(["column position"])]])
        result["imageaxisscaletype"][0, 0] = _cell([[np.array(["spatial-y"])], [np.array(["spatial-x"])]])
        result["imageaxistype"][0, 0] = _cell([[np.array(["none"])], [np.array(["none"])]])
    return result


def _write_dso(path: Path, **objects: np.ndarray) -> Path:
    savemat(path, objects, do_compression=True)
    return path


def test_matlab_v5_dso_maps_every_mode_and_set_without_flattening(tmp_path: Path) -> None:
    source = _write_dso(
        tmp_path / "three-way.mat", calibration=_dso_struct(np.arange(24, dtype=np.int64).reshape(2, 3, 4))
    )

    result = ingest(source)

    assert result.variant == "mat-v5"
    assert [asset.asset_id for asset in result.assets] == ["calibration"]
    dataset = result.assets[0].dataset
    assert dataset.shape == (2, 3, 4)
    assert dataset.layout.source_dtype.endswith("i8")
    assert dataset.layout.mode_roles == ("sample", "inner", "feature")
    assert dataset.source_identity.storage_version == "matlab-v5"
    assert dataset.source_identity.object_unique_id == "generated-dso-001"
    assert dataset.source_identity.dataset_version == "5.0"
    assert dataset.descriptive.authors == ("A. Scientist",)
    assert dataset.descriptive.raw_date_fields == {"date": "2026-08-25", "moddate": "2026-08-26"}
    assert dataset.source_history.entries == ("Imported", "Correction: none")
    assert dataset.extra["dso.userdata"] == {"instrument": "Generated", "replicates": 3}
    assert dataset.extra["dso.axistype"] == ["none", "none", "none"]
    assert isinstance(dataset.sample_axis, SampleAxis)
    assert dataset.sample_axis.primary_class_set_name == "group"
    assert [item.name for item in dataset.sample_axis.class_sets] == ["group", "sequence"]
    assert [level.label for level in dataset.sample_axis.class_sets[0].levels] == ["Group A", "Group B"]
    assert dataset.sample_axis.include_mask.tolist() == [True, False]
    assert dataset.axis(1).include_mask.tolist() == [True, False, True]  # type: ignore[union-attr]
    assert isinstance(dataset.feature_axis, SpectralAxis)
    assert dataset.feature_axis.include_mask.tolist() == [True, False, True, False]
    assert dataset.feature_axis.primary_scale_name == "wavenumber"
    assert dataset.feature_axis.alternate_scales[0].name == "wavelength"
    assert dataset.feature_axis.alternate_label_sets[0].values[-1] == "Alt-3-4"
    assert dataset.feature_axis.alternate_title_sets[0].title == "Wavenumber"
    assert len(dataset.provenance) == 1
    assert dataset.provenance[0].op_id == "import.matlab_dso"
    assert dataset.provenance[0].parameters["source_sha256"] == result.source_members[0].sha256
    assert result.assets[0].raw_metadata["dataset_scientific_digest"] == dataset.scientific_digest


def test_matlab_v5_inventory_emits_all_dso_and_numeric_assets_in_order(tmp_path: Path) -> None:
    source = _write_dso(
        tmp_path / "multi.mat",
        beta=_dso_struct(np.arange(6.0).reshape(2, 3), name="Beta"),
        alpha=_dso_struct(np.arange(8.0).reshape(2, 4), name="Alpha"),
        numeric=np.arange(5.0),
    )

    result = ingest(source)

    assert [asset.asset_id for asset in result.assets] == ["alpha", "beta", "numeric"]
    assert result.raw_metadata["matlab.dso_variables"] == ["alpha", "beta"]
    assert result.assets[0].dataset.source_identity.source_variable == "alpha"
    assert result.assets[1].dataset.source_identity.source_variable == "beta"


def test_matlab_dso_preserves_missing_property_asset_without_rejecting_finite_spectra(tmp_path: Path) -> None:
    properties = np.asarray([[0.80, np.nan], [0.90, 42.0], [np.nan, 43.0]])
    source = _write_dso(
        tmp_path / "diesel.mat",
        diesel_spec=_dso_struct(np.arange(12.0).reshape(3, 4), name="Diesel spectra"),
        diesel_prop=_dso_struct(properties, name="Diesel properties"),
    )

    result = ingest(source)

    assets = {asset.asset_id: asset for asset in result.assets}
    assert set(assets) == {"diesel_prop", "diesel_spec"}
    assert np.isfinite(assets["diesel_spec"].dataset.X).all()
    np.testing.assert_array_equal(np.isnan(assets["diesel_prop"].dataset.X), np.isnan(properties))
    assert any(warning.startswith("Missing data preserved: asset 'diesel_prop'") for warning in result.warnings)

    spectral_x, _, property_y, _ = parse_eigenvector_mat(source, spec_key="diesel_spec", prop_key="diesel_prop")
    assert np.isfinite(spectral_x).all()
    np.testing.assert_array_equal(np.isnan(property_y), np.isnan(properties))


def test_eigenvector_mat_selected_spectral_x_rejects_nan_after_dso_inventory(tmp_path: Path) -> None:
    spectral_x = np.arange(12.0).reshape(3, 4)
    spectral_x[1, 2] = np.nan
    source = _write_dso(
        tmp_path / "missing-spectral-x.mat",
        diesel_spec=_dso_struct(spectral_x, name="Diesel spectra"),
        diesel_prop=_dso_struct(np.asarray([[0.8], [np.nan], [0.9]]), name="Diesel properties"),
    )

    # The generic DSO inventory retains both assets; only the selected X role
    # can distinguish forbidden spectral missingness from allowed property Y.
    result = ingest(source)
    assert {asset.asset_id for asset in result.assets} == {"diesel_spec", "diesel_prop"}
    with pytest.raises(ValueError, match="Selected Eigenvector spectral X must be a finite"):
        parse_eigenvector_mat(source, spec_key="diesel_spec", prop_key="diesel_prop")


def test_eigenvector_mat_declared_property_and_sample_labels_must_match(tmp_path: Path) -> None:
    spectra = _dso_struct(np.arange(12.0).reshape(3, 4), name="Diesel spectra")
    properties = _dso_struct(np.arange(3.0).reshape(3, 1), name="Diesel properties")
    source = _write_dso(tmp_path / "missing-property.mat", diesel_spec=spectra)
    with pytest.raises(ValueError, match="Key 'diesel_prop' not found"):
        parse_eigenvector_mat(source, spec_key="diesel_spec", prop_key="diesel_prop")

    property_labels = properties["label"][0, 0]
    property_labels[0, 0] = np.array(["M1-2", "M1-1", "M1-3"], dtype=object)
    source = _write_dso(tmp_path / "shuffled-property.mat", diesel_spec=spectra, diesel_prop=properties)
    with pytest.raises(ValueError, match="different specimen IDs"):
        parse_eigenvector_mat(source, spec_key="diesel_spec", prop_key="diesel_prop")


def test_res38_full_diesel_mat_builder_preserves_missing_targets(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from spectra_sherpa.app.api.v1.routes import builder

    spectra = np.arange(24.0).reshape(6, 4)
    properties = np.arange(42.0).reshape(6, 7)
    properties[1, 0] = np.nan
    properties[3, 2] = np.nan
    properties[5, 6] = np.nan
    source_dir = tmp_path / "diesel_nir_mat"
    source_dir.mkdir()
    _write_dso(
        source_dir / "SWRI_Diesel_NIR.mat",
        diesel_spec=_dso_struct(spectra, name="Diesel spectra"),
        diesel_prop=_dso_struct(properties, name="Diesel properties"),
    )

    loaded = eigenvector.load_eigenvector_dataset("diesel_nir_mat", data_dir=tmp_path)
    governed = loaded["dataset"]
    assert governed is not None
    assert loaded["sample_ids"] == governed.sample_axis.labels
    np.testing.assert_array_equal(governed.X, spectra)
    np.testing.assert_allclose(governed.target, properties, equal_nan=True)
    assert governed.target_context.target_names == ["BP50", "CN", "D4052", "FLASH", "FREEZE", "TOTAL", "VISC"]
    assert isinstance(governed.feature_axis, SpectralAxis)
    assert governed.feature_axis.units == "nm"
    assert governed.feature_axis.quantity == "wavelength"
    assert governed.data_role == "X_spectra"
    assert len(set(governed.sample_axis.labels or [])) == 6
    assert set(governed.sample_axis.sample_table or {}) == {
        "sample_id",
        "BP50",
        "CN",
        "D4052",
        "FLASH",
        "FREEZE",
        "TOTAL",
        "VISC",
    }
    assert governed.sample_axis.sample_table["sample_id"] == governed.sample_axis.labels
    for index, name in enumerate(governed.target_context.target_names):
        np.testing.assert_allclose(
            np.asarray(governed.sample_axis.sample_table[name], dtype=float), governed.target[:, index], equal_nan=True
        )

    monkeypatch.setattr(eigenvector, "EIGENVECTOR_DATA_DIR", tmp_path)
    materialized = builder._reference_dataset_as_sherpa("eigenvector", "diesel_nir_mat")
    np.testing.assert_array_equal(materialized.X, governed.X)
    np.testing.assert_allclose(materialized.target, governed.target, equal_nan=True)
    assert materialized.target_context == governed.target_context
    assert materialized.sample_axis.model_dump(mode="json") == governed.sample_axis.model_dump(mode="json")
    assert materialized.feature_axis.model_dump(mode="json") == governed.feature_axis.model_dump(mode="json")


@pytest.mark.asyncio
async def test_res38_full_diesel_mat_experiment_import_preserves_source_labels(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from spectra_sherpa.app.services import eigenvector_datasets as eigenvector_service
    from spectra_sherpa.app.services import experiments

    spectra = np.arange(24.0).reshape(6, 4)
    properties = np.arange(42.0).reshape(6, 7)
    properties[2, 4] = np.nan
    source_dir = tmp_path / "source" / "diesel_nir_mat"
    source_dir.mkdir(parents=True)
    _write_dso(
        source_dir / "SWRI_Diesel_NIR.mat",
        diesel_spec=_dso_struct(spectra, name="Diesel spectra"),
        diesel_prop=_dso_struct(properties, name="Diesel properties"),
    )
    loaded = eigenvector.load_eigenvector_dataset("diesel_nir_mat", data_dir=tmp_path / "source")
    expected_labels = list(loaded["dataset"].sample_axis.labels or [])
    assert expected_labels == [f"M1-{index + 1}" for index in range(6)]

    monkeypatch.setattr(eigenvector_service, "load_eigenvector_dataset", lambda _name: loaded)
    monkeypatch.setattr(experiments, "experiment_dir", lambda _experiment_id: tmp_path / "experiment")

    async def fake_add_experiment_file(*_args: object, **_kwargs: object) -> SimpleNamespace:
        return SimpleNamespace(id=1, file_path="raw/diesel_nir_mat.csv")

    monkeypatch.setattr(experiments, "add_experiment_file", fake_add_experiment_file)
    created = await experiments.import_reference_dataset(object(), 1, "eigenvector", "diesel_nir_mat")

    assert len(created) == 1
    imported = (tmp_path / "experiment" / "raw" / "diesel_nir_mat.csv").read_text().splitlines()
    assert imported[0].split(",")[0] == "sample_id"
    assert [row.split(",")[0] for row in imported[1:]] == expected_labels


def test_matlab_dso_still_rejects_infinite_values(tmp_path: Path) -> None:
    source = _write_dso(
        tmp_path / "infinite.mat",
        spectra=_dso_struct(np.asarray([[1.0, np.inf], [2.0, 3.0]])),
    )

    with pytest.raises(UnreadableSpectrumError, match="data contains infinite values"):
        ingest(source)


def test_legacy_packed_class_name_and_dormant_image_axes_are_preserved(tmp_path: Path) -> None:
    dso = _dso_struct(np.arange(12.0).reshape(3, 4))
    dso_fields = dso.dtype.names
    assert dso_fields is not None
    fields = {name: dso[name][0, 0] for name in dso_fields}
    fields.pop("classname")
    fields["class"] = _cell(
        [
            [np.array([1, 2, 1], dtype=np.uint8), np.array(["Sample type"])],
            [np.empty((0, 0), dtype=np.uint8), np.empty((0,), dtype="U1")],
        ]
    )
    fields["classlookup"] = _cell(
        [
            [np.array([[1, "Calibration"], [2, "Validation"]], dtype=object)],
            [np.empty((0, 0), dtype=object)],
        ]
    )
    fields["imageaxisscale"] = _cell([[np.empty((0, 0)), np.empty((0, 0))], [np.empty((0, 0)), np.empty((0, 0))]])
    fields["imageaxistype"] = _cell([[np.array(["none"])], [np.array(["none"])]])
    legacy = np.empty((1, 1), dtype=[(name, "O") for name in fields])
    for name, value in fields.items():
        legacy[name][0, 0] = value

    dataset = ingest(_write_dso(tmp_path / "legacy-packed.mat", legacy=legacy)).assets[0].dataset

    assert dataset.sample_axis.class_sets[0].name == "Sample type"
    assert [level.label for level in dataset.sample_axis.class_sets[0].levels] == ["Calibration", "Validation"]
    assert dataset.extra["dso.imageaxistype"] == ["none", "none"]


def test_legacy_includ_alias_is_exact_and_contradiction_refuses(tmp_path: Path) -> None:
    data = np.arange(6.0).reshape(2, 3)
    legacy = _write_dso(tmp_path / "legacy.mat", legacy=_dso_struct(data, include_field="includ"))
    admitted = ingest(legacy).assets[0].dataset
    assert admitted.sample_axis.include_mask.tolist() == [True, False]

    wrong = _cell([[np.array([2], dtype=np.int32)], [np.array([1, 3], dtype=np.int32)]])
    contradicting = _dso_struct(data, legacy_include=wrong)
    path = _write_dso(tmp_path / "contradicting.mat", bad=contradicting)
    with pytest.raises(Exception, match="include and legacy includ authorities contradict"):
        ingest(path)


def test_batch_dso_refuses_instead_of_degrading(tmp_path: Path) -> None:
    dso = _dso_struct(np.arange(6.0).reshape(2, 3), source_type="batch")
    path = _write_dso(tmp_path / "unsupported.mat", claimed=dso)
    with pytest.raises(UnsupportedFormatVariantError, match="batch DSO"):
        ingest(path)


def test_image_dso_refolds_column_major_pixels_and_preserves_spatial_axes(tmp_path: Path) -> None:
    unfolded = np.arange(2 * 6 * 4.0).reshape(2, 6, 4)
    path = _write_dso(tmp_path / "image.mat", image=_dso_struct(unfolded, source_type="image"))

    dataset = ingest(path).assets[0].dataset

    assert dataset.shape == (2, 2, 3, 4)
    assert dataset.layout.kind == "image"
    assert dataset.layout.image_size == (2, 3)
    assert dataset.layout.image_mode == 2
    assert dataset.layout.original_unfolded_shape == (2, 6, 4)
    assert dataset.layout.mode_roles == ("sample", "spatial_coordinate", "spatial_coordinate", "feature")
    np.testing.assert_array_equal(dataset.X[0, :, :, 0], unfolded[0, :, 0].reshape(2, 3, order="F"))
    assert dataset.axis(1).title == "Image dimension 1"  # type: ignore[union-attr]
    assert dataset.axis(1).primary_scale_name == "row position"  # type: ignore[union-attr]
    assert dataset.axis(2).include_mask.tolist() == [True, False, True]  # type: ignore[union-attr]


def test_two_dimensional_image_dso_preserves_pixels_as_modeling_rows(tmp_path: Path) -> None:
    unfolded = np.arange(6 * 4.0).reshape(6, 4)
    dso = _dso_struct(unfolded, source_type="image")
    dso["imagemode"][0, 0] = np.array([[1]], dtype=np.int32)
    dso["imagesize"][0, 0] = np.array([[2, 3]], dtype=np.int32)
    dso["imageinclude"][0, 0] = _cell([[np.array([1, 2], dtype=np.int32)], [np.array([1, 3], dtype=np.int32)]])
    dso["imageaxisscale"][0, 0] = _cell([[np.array([0.0, 10.0])], [np.array([0.0, 20.0, 40.0])]])
    path = _write_dso(tmp_path / "unfolded-image.mat", image=dso)

    result = ingest(path)
    assert [asset.asset_id for asset in result.assets] == ["image", "image:image-cube"]
    dataset = result.assets[0].dataset

    assert dataset.shape == (6, 4)
    assert dataset.layout.kind == "image"
    assert dataset.layout.image_size == (2, 3)
    assert dataset.layout.image_mode == 1
    assert dataset.layout.original_unfolded_shape == (6, 4)
    assert dataset.layout.mode_roles == ("sample", "feature")
    assert dataset.extra["dso.imageaxistype"] == ["none", "none"]
    np.testing.assert_array_equal(dataset.X, unfolded)

    cube = result.assets[1].dataset
    assert cube.shape == (2, 3, 4)
    assert cube.data_role == "X_spectra"
    assert cube.layout.mode_roles == ("spatial_coordinate", "spatial_coordinate", "feature")
    assert cube.layout.image_include == (True, True, False, False, True, True)
    assert cube.layout.original_unfolded_shape == (6, 4)
    assert cube.provenance[-1].parameters["image_view"] == "image-cube"
    np.testing.assert_array_equal(cube.X[:, :, 0], unfolded[:, 0].reshape(2, 3, order="F"))


def test_dso_resource_ceiling_refuses_decoded_data(tmp_path: Path) -> None:
    path = _write_dso(tmp_path / "bounded.mat", dso=_dso_struct(np.arange(60.0).reshape(3, 4, 5)))
    with pytest.raises(ParserLimitError, match="decoded elements"):
        ingest(path, limits=ParserLimits(max_decoded_elements=50))


def test_one_sample_dso_keeps_feature_metadata(tmp_path: Path) -> None:
    path = _write_dso(tmp_path / "one-sample.mat", dso=_dso_struct(np.arange(5.0).reshape(1, 5)))
    dataset = ingest(path).assets[0].dataset
    assert dataset.shape == (1, 5)
    assert dataset.sample_axis.labels == ["M1-1"]
    assert dataset.feature_axis.primary_scale_name == "wavenumber"


def test_dso_scientific_identity_excludes_only_storage_container_facts(tmp_path: Path) -> None:
    mat_path = _write_dso(tmp_path / "science.mat", dso=_dso_struct(np.arange(6.0).reshape(2, 3)))
    decoded = loadmat(mat_path, squeeze_me=False, struct_as_record=True)["dso"]
    alternate_source = tmp_path / "alternate-container.mat"
    alternate_source.write_bytes(mat_path.read_bytes() + b"storage-only-trailer")
    limits = ParserLimits()
    with (
        BoundedSource(mat_path, limits=limits) as v5_source,
        BoundedSource(alternate_source, limits=limits) as v73_source,
    ):
        first = map_decoded_dso(
            DecodedDSO("dso", scipy_struct_fields(decoded), "matlab-v5"),
            source=v5_source,
            parser_version="3",
        )
        second = map_decoded_dso(
            DecodedDSO("dso", scipy_struct_fields(decoded), "matlab-v7.3"),
            source=v73_source,
            parser_version="3",
        )

    assert first.source_identity.storage_version == "matlab-v5"
    assert second.source_identity.storage_version == "matlab-v7.3"
    assert first.provenance[0].parameters["source_sha256"] != second.provenance[0].parameters["source_sha256"]
    assert first.scientific_projection() == second.scientific_projection()
    assert first.scientific_digest == second.scientific_digest


def test_dso_preserves_multiple_authors_and_promotes_only_iso_dates(tmp_path: Path) -> None:
    dso = _dso_struct(np.arange(6.0).reshape(2, 3))
    authors = np.empty((1, 2), dtype=object)
    authors[0, :] = ["A. Scientist", "B. Reviewer"]
    dso["author"][0, 0] = authors
    dso["moddate"][0, 0] = np.array(["vendor date 27-Aug-2026"])
    path = _write_dso(tmp_path / "authors.mat", dso=dso)

    descriptive = ingest(path).assets[0].dataset.descriptive

    assert descriptive.authors == ("A. Scientist", "B. Reviewer")
    assert descriptive.created_at is not None
    assert descriptive.created_at.isoformat() == "2026-08-25T00:00:00"
    assert descriptive.modified_at is None
    assert descriptive.raw_date_fields["moddate"] == "vendor date 27-Aug-2026"


def test_dso_unknown_fields_refuse_instead_of_disappearing(tmp_path: Path) -> None:
    path = _write_dso(tmp_path / "unknown.mat", dso=_dso_struct(np.arange(6.0).reshape(2, 3)))
    decoded = loadmat(path, squeeze_me=False, struct_as_record=True)["dso"]
    fields = dict(scipy_struct_fields(decoded))
    fields["private_secondary_class"] = np.array(["must not disappear"])

    with BoundedSource(path, limits=ParserLimits()) as source:
        with pytest.raises(UnsupportedFormatVariantError, match="unsupported field.*private_secondary_class"):
            map_decoded_dso(DecodedDSO("dso", fields, "matlab-v5"), source=source, parser_version="3")


def test_dso_datasetversion_and_legacy_version_must_not_contradict(tmp_path: Path) -> None:
    path = _write_dso(tmp_path / "version.mat", dso=_dso_struct(np.arange(6.0).reshape(2, 3)))
    decoded = loadmat(path, squeeze_me=False, struct_as_record=True)["dso"]
    fields = dict(scipy_struct_fields(decoded))
    fields["version"] = np.array(["4.0"])

    with BoundedSource(path, limits=ParserLimits()) as source:
        with pytest.raises(UnreadableSpectrumError, match="authorities contradict"):
            map_decoded_dso(DecodedDSO("dso", fields, "matlab-v5"), source=source, parser_version="4")


def test_dso_matlab_date_vector_is_preserved_and_promoted(tmp_path: Path) -> None:
    dso = _dso_struct(np.arange(6.0).reshape(2, 3))
    dso["date"][0, 0] = np.array([[2005, 5, 13, 9, 50, 32.501]], dtype=np.float64)
    path = _write_dso(tmp_path / "date-vector.mat", dso=dso)

    descriptive = ingest(path).assets[0].dataset.descriptive

    assert descriptive.raw_date_fields["date"] == "2005-05-13T09:50:32.501000"
    assert descriptive.created_at is not None
    assert descriptive.created_at.isoformat() == "2005-05-13T09:50:32.501000"


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        ("short-labels", "aligned labels"),
        ("nonfinite-axis", "non-finite"),
        ("unsafe-class", "non-lossless scalar"),
        ("missing-class-lookup", "does not name every class value"),
    ],
)
def test_dso_parallel_metadata_mutations_fail_closed(tmp_path: Path, mutation: str, message: str) -> None:
    dso = _dso_struct(np.arange(6.0).reshape(2, 3))
    if mutation == "short-labels":
        labels = dso["label"][0, 0]
        labels[1, 0] = np.array(["only", "two"], dtype=object)
    elif mutation == "nonfinite-axis":
        scales = dso["axisscale"][0, 0]
        scales[1, 0] = np.array([1.0, np.nan, 3.0])
    elif mutation == "unsafe-class":
        classes = dso["class"][0, 0]
        classes[1, 1] = np.array([1, 2**53, 3], dtype=np.int64)
    else:
        lookups = dso["classlookup"][0, 0]
        incomplete = np.empty((1, 2), dtype=object)
        incomplete[0, :] = ["A", "Group A"]
        lookups[1, 0] = incomplete
    path = _write_dso(tmp_path / f"{mutation}.mat", dso=dso)

    with pytest.raises(Exception, match=message):
        ingest(path)


def test_multiple_dso_records_share_one_aggregate_decoded_budget(monkeypatch, tmp_path: Path) -> None:
    import spectra_sherpa.io.formats.matlab as matlab_format

    objects = {
        "alpha": _dso_struct(np.arange(30.0).reshape(5, 6), name="Alpha"),
        "beta": _dso_struct(np.arange(30.0).reshape(5, 6), name="Beta"),
    }
    path = _write_dso(tmp_path / "aggregate.mat", **objects)
    decoded = loadmat(path, squeeze_me=False, struct_as_record=True)
    footprint = decoded_dso_footprint(scipy_struct_fields(decoded["alpha"]))
    limit = 2 + footprint.elements + 1
    mapped = False

    def _unexpected_map(*_args, **_kwargs):
        nonlocal mapped
        mapped = True
        raise AssertionError("aggregate refusal must precede dataset construction")

    monkeypatch.setattr(matlab_format, "map_decoded_dso", _unexpected_map)
    with pytest.raises(ParserLimitError, match="decoded elements"):
        ingest(path, limits=ParserLimits(max_decoded_elements=limit))
    assert mapped is False
