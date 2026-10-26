"""Independent decode/identity checks for the BOSCH NetCDF4 multi-file reader."""

from __future__ import annotations

import hashlib
from pathlib import Path

import h5py
import numpy as np
import pytest

from spectra_sherpa.ingestion_errors import IngestionError, ParserLimitError, UnreadableSpectrumError
from spectra_sherpa.io.bosch_netcdf import read_bosch_netcdf
from spectra_sherpa.io.types import ParserLimits


def files(tmp_path: Path, *, process=False):
    dictionary = tmp_path / "Dictionary.nc"
    path = tmp_path / "Source.nc"
    values = np.array([0.0, 10.5, -2.25, 20.0], dtype=np.float32)
    codes = np.array([[0, 1, 2], [3, 2, 1], [1, 0, 3], [2, 3, 0]], dtype=np.uint16)
    timestamps = np.array([1722855600.0, 1722855600.04, 1722855600.16, 1722855600.20])
    for file in (dictionary, path):
        with h5py.File(file, "w") as f:
            f.attrs["_NCProperties"] = "version=2,netcdf=4.9.2,hdf5=1.14.4"
    with h5py.File(dictionary, "a") as f:
        f["data"] = values
    with h5py.File(path, "a") as f:
        for name in ("Wafer_01", "Wafer_02"):
            group = f.create_group(name)
            group["data"] = codes if name == "Wafer_01" else np.zeros_like(codes)
            group["times"] = timestamps
            group["times"].attrs["units"] = "seconds since 1970-01-01 00:00:00 UTC"
            group["times"].attrs["calendar"] = "standard"
            if process:
                group.create_dataset("feature", data=["Gas flow", "Pressure", "Temperature"], dtype=h5py.string_dtype())
            else:
                group["wavelengths"] = np.array([250.0, 400.0, 800.0])
    return path, dictionary, codes, values, timestamps


def test_decodes_exact_values_without_averaging_and_preserves_irregular_times(tmp_path):
    path, dictionary, codes, values, timestamps = files(tmp_path)
    dataset = read_bosch_netcdf(path, dictionary_path=dictionary, group="Wafer_01")
    np.testing.assert_array_equal(dataset.X, [[0, 10.5, -2.25], [20, -2.25, 10.5], [10.5, 0, 20], [-2.25, 20, 0]])
    np.testing.assert_array_equal(dataset.sample_axis.values, timestamps)
    np.testing.assert_array_equal(dataset.feature_axis.values, [250, 400, 800])
    assert dataset.feature_axis.units == "nm"
    assert dataset.data_role == "X_spectra"
    assert dataset.domain.data_quantity == "Intensity"  # Acquisition seconds describe rows, not signal amplitude.
    assert dataset.is_time_series
    assert dataset.units is None  # The source does not declare calibrated intensity units.
    authority = dataset.get_extra("ingestion.authority")
    assert [m["sha256"] for m in authority["source_members"]] == [
        hashlib.sha256(p.read_bytes()).hexdigest() for p in (path, dictionary)
    ]
    assert authority["asset_id"] == "Wafer_01"


def test_positive_row_slice_retains_original_observation_ids(tmp_path):
    path, dictionary, codes, values, timestamps = files(tmp_path)
    full = read_bosch_netcdf(path, dictionary_path=dictionary, group="Wafer_01")
    subset = read_bosch_netcdf(path, dictionary_path=dictionary, group="Wafer_01", rows=slice(1, 4, 2))
    np.testing.assert_array_equal(subset.X, values[codes[[1, 3]]])
    np.testing.assert_array_equal(subset.sample_axis.values, timestamps[[1, 3]])
    assert subset.sample_axis.labels == full.sample_axis.labels[1:4:2]
    assert "2024-08-05T" in subset.sample_axis.labels[0]
    assert subset.sample_axis.sample_table["sample_id"] == full.sample_axis.sample_table["sample_id"][1:4:2]
    assert subset.layout.source_shape == (2, 3)
    assert subset.get_extra("bosch.original_shape") == [4, 3]


def test_process_channels_are_features_with_unknown_units(tmp_path):
    path, dictionary, codes, values, _ = files(tmp_path, process=True)
    dataset = read_bosch_netcdf(path, dictionary_path=dictionary, group="Wafer_01")
    np.testing.assert_array_equal(dataset.X, values[codes])
    assert dataset.feature_axis.labels == ["Gas flow", "Pressure", "Temperature"]
    assert dataset.feature_axis.units is None
    assert dataset.data_role == "X_features"
    assert dataset.domain.technique is None


def test_requested_wafer_is_selected_without_combining_wafers(tmp_path):
    path, dictionary, *_ = files(tmp_path)
    dataset = read_bosch_netcdf(path, dictionary_path=dictionary, group="Wafer_02")
    np.testing.assert_array_equal(dataset.X, np.zeros((4, 3)))
    with pytest.raises(UnreadableSpectrumError):
        read_bosch_netcdf(path, dictionary_path=dictionary, group="Wafer_03")


@pytest.mark.parametrize("rows", [slice(None, None, 0), slice(None, None, -1), slice(True, 2), [1, 2]])
def test_invalid_row_requests_are_rejected(tmp_path, rows):
    path, dictionary, *_ = files(tmp_path)
    with pytest.raises(ValueError):
        read_bosch_netcdf(path, dictionary_path=dictionary, group="Wafer_01", rows=rows)


def test_empty_row_selection_is_rejected(tmp_path):
    path, dictionary, *_ = files(tmp_path)
    with pytest.raises(UnreadableSpectrumError, match="empty"):
        read_bosch_netcdf(path, dictionary_path=dictionary, group="Wafer_01", rows=slice(3, 3))


def test_source_and_decoded_limits_are_enforced(tmp_path):
    path, dictionary, *_ = files(tmp_path)
    for limits in [
        ParserLimits(max_source_bytes=8, max_probe_bytes=8),
        ParserLimits(max_decoded_elements=10),
        ParserLimits(max_decoded_bytes=64),
        ParserLimits(max_metadata_bytes=8),
    ]:
        with pytest.raises(ParserLimitError):
            read_bosch_netcdf(path, dictionary_path=dictionary, group="Wafer_01", limits=limits)


def test_out_of_dictionary_code_is_rejected_instead_of_wrapped(tmp_path):
    path, dictionary, *_ = files(tmp_path)
    with h5py.File(path, "a") as f:
        f["Wafer_01/data"][0, 0] = 65535
    with pytest.raises(UnreadableSpectrumError, match="dictionary"):
        read_bosch_netcdf(path, dictionary_path=dictionary, group="Wafer_01")


@pytest.mark.parametrize("object_path", ["Wafer_01/data", "Wafer_01/wavelengths", "Wafer_01/times"])
def test_external_and_soft_links_are_rejected(tmp_path, object_path):
    path, dictionary, *_ = files(tmp_path)
    with h5py.File(path, "a") as f:
        del f[object_path]
        f[object_path] = h5py.ExternalLink(str(dictionary), "/data")
    with pytest.raises(UnreadableSpectrumError, match="local hard link"):
        read_bosch_netcdf(path, dictionary_path=dictionary, group="Wafer_01")


def test_wrong_time_origin_is_not_silently_treated_as_unix_time(tmp_path):
    path, dictionary, *_ = files(tmp_path)
    with h5py.File(path, "a") as f:
        f["Wafer_01/times"].attrs["units"] = "hours since 1900-01-01"
    with pytest.raises(UnreadableSpectrumError, match="origin"):
        read_bosch_netcdf(path, dictionary_path=dictionary, group="Wafer_01")


def test_non_netcdf_hdf5_and_missing_dictionary_are_rejected(tmp_path):
    path, dictionary, *_ = files(tmp_path)
    with h5py.File(path, "a") as f:
        del f.attrs["_NCProperties"]
    with pytest.raises(UnreadableSpectrumError, match="NetCDF4"):
        read_bosch_netcdf(path, dictionary_path=dictionary, group="Wafer_01")
    with pytest.raises(IngestionError):
        read_bosch_netcdf(path, dictionary_path=tmp_path / "absent.nc", group="Wafer_01")


def test_missing_dictionary_values_are_preserved_and_disclosed(tmp_path):
    path, dictionary, *_ = files(tmp_path)
    with h5py.File(dictionary, "a") as f:
        f["data"][0] = np.nan
    dataset = read_bosch_netcdf(path, dictionary_path=dictionary, group="Wafer_01")
    assert np.isnan(dataset.X[0, 0])
    assert any(x.startswith("Missing data preserved:") for x in dataset.get_extra("ingestion.authority")["warnings"])


def test_native_inventory_does_not_decode_and_selected_wafer_uses_bundled_dictionary(tmp_path, monkeypatch):
    from spectra_sherpa.io import ingest, inspect_assets
    from spectra_sherpa.io.bosch_netcdf import _BoschPlugin

    path, _, codes, _, timestamps = files(tmp_path)
    original = _BoschPlugin._decode
    monkeypatch.setattr(_BoschPlugin, "_decode", lambda *args: pytest.fail("inventory decoded the matrix"))
    inventory = inspect_assets(path)
    assert [asset["asset_id"] for asset in inventory.assets] == ["Wafer_01", "Wafer_02"]
    assert inventory.assets[0]["shape"] == [4, 3]
    monkeypatch.setattr(_BoschPlugin, "_decode", original)
    with pytest.raises(UnreadableSpectrumError, match="select a wafer"):
        ingest(path)
    result = ingest(path, asset_id="Wafer_01")
    with h5py.File(Path(__file__).parents[1] / "src/spectra_sherpa/data/bosch_netcdf/Dictionary_OES.nc") as dictionary:
        np.testing.assert_array_equal(result.assets[0].dataset.X, dictionary["data"][:][codes])
    np.testing.assert_array_equal(result.assets[0].dataset.sample_axis.values, timestamps)
    assert len(result.source_members) == 1
    assert result.assets[0].dataset.get_extra("bosch.dictionary_sha256")


@pytest.mark.anyio
async def test_upload_inventory_and_persisted_wafer_matrix(auth_client, tmp_path):
    path, _, codes, _, _ = files(tmp_path)
    staged = await auth_client.post(
        "/api/v1/builder/upload/stage-batch", files={"files": (path.name, path.read_bytes(), "application/x-netcdf")}
    )
    assert staged.status_code == 200, staged.text
    payload = staged.json()
    assert not payload["refusals"], payload
    assert len(payload["files"][0]["assets"]) == 2
    project = (await auth_client.post("/api/v1/projects", json={"name": "BOSCH"})).json()
    experiment = (
        await auth_client.post("/api/v1/experiments", json={"name": "BOSCH", "project_id": project["id"]})
    ).json()
    uploaded = await auth_client.post(
        f"/api/v1/experiments/{experiment['id']}/files",
        data={"stage": "raw"},
        files={"file": (path.name, path.read_bytes(), "application/x-netcdf")},
    )
    assert uploaded.status_code == 201, uploaded.text
    file_id = uploaded.json()["id"]
    inventory = await auth_client.get(f"/api/v1/experiments/{experiment['id']}/files/{file_id}/scientific-assets")
    assert inventory.status_code == 200, inventory.text
    assert len(inventory.json()["assets"]) == 2
    preview = await auth_client.post(
        "/api/v1/builder/data-matrix",
        json={
            "kind": "experiment_file",
            "experiment_id": experiment["id"],
            "file_id": file_id,
            "asset_id": "Wafer_02",
        },
    )
    assert preview.status_code == 200, preview.text
    assert preview.json()["shape"] == list(codes.shape)
    assert all("Wafer_02:" in label and "+00:00" in label for label in preview.json()["row_labels"])


def test_native_inventory_rejects_corruption_and_unused_external_links(tmp_path):
    from spectra_sherpa.io import inspect_assets

    path, dictionary, *_ = files(tmp_path)
    with h5py.File(path, "a") as f:
        f["Wafer_02/unused"] = h5py.ExternalLink(str(dictionary), "/data")
    with pytest.raises(UnreadableSpectrumError, match="local hard link"):
        inspect_assets(path)
    path.write_bytes(b"\x89HDF\r\n\x1a\ncorrupted")
    with pytest.raises(UnreadableSpectrumError):
        inspect_assets(path)


def test_reference_protocol_has_two_variable_epd_steps_and_no_invented_lot(tmp_path):
    path, dictionary, *_ = files(tmp_path)
    dataset = read_bosch_netcdf(path, dictionary_path=dictionary, group="Wafer_01")
    context = dataset.get_extra("bosch.experiment_context")
    assert context["selected_lot"] is None  # A matching date/name is not source identity.
    assert context["initial_chamber_preparation"][4]["duration_seconds"] is None
    assert context["production_lot"]["inter_wafer_sequence"] == [
        {"label": "Break", "duration_seconds": 60},
        {"label": "Endpoint-controlled clean (EPD)", "duration_seconds": None},
    ]
    assert context["conditioning_experiment"]["repetition_options"] == [1, 3, 9]


def test_published_lot_mapping_uses_checksum_not_uploaded_filename(tmp_path, monkeypatch):
    from types import SimpleNamespace

    from spectra_sherpa.io import bosch_netcdf

    renamed = tmp_path / "renamed.nc"
    renamed.write_bytes(b"snapshot bytes")
    monkeypatch.setattr(
        bosch_netcdf.hashlib,
        "file_digest",
        lambda stream, algorithm: SimpleNamespace(hexdigest=lambda: "4567d24ec2125102a2e5129203ba31fa"),
    )
    context = bosch_netcdf._experiment_context(
        SimpleNamespace(size_bytes=8_819_467, snapshot_path=renamed), "Day_2024_08_05_Wafer_06"
    )
    lot = context["selected_lot"]
    assert (lot["lot_number"], lot["wafer_number"], lot["recorded_wafer_count"]) == (7, 6, 6)
    assert lot["conditioning_surface"] == "Blank SiO₂ wafer"
    assert lot["conditioning_repetitions"] == 3
    assert lot["source_cells"] == "Tabelle1!A8:E8"


def test_process_clock_conflict_preserves_raw_values_and_warns(tmp_path):
    path, dictionary, *_ = files(tmp_path, process=True)
    with h5py.File(path, "a") as nc:
        nc.move("Wafer_01", "Day_2024_08_05_Wafer_01")
        nc["Day_2024_08_05_Wafer_01/times"][:] = [121.2, 121.4, 121.6, 121.8]
    dataset = read_bosch_netcdf(path, dictionary_path=dictionary, group="Day_2024_08_05_Wafer_01")
    np.testing.assert_array_equal(dataset.sample_axis.values, [121.2, 121.4, 121.6, 121.8])
    assert "origin unverified" in dataset.sample_axis.title
    assert "source time 121.200000 s" in dataset.sample_axis.labels[0]
    assert any("conflict" in warning for warning in dataset.get_extra("ingestion.authority")["warnings"])
