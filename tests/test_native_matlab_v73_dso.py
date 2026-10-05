from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

import h5py
import numpy as np
import pytest
from scipy.io import loadmat, savemat

from spectra_sherpa.io import ParserLimitError, ParserLimits, UnsupportedFormatVariantError, ingest
from spectra_sherpa.io.formats.dso import scipy_struct_fields


def _storage_order(array: np.ndarray) -> np.ndarray:
    return array if array.ndim <= 1 else array.transpose(tuple(reversed(range(array.ndim))))


def _object_scalar(value: Any) -> np.ndarray:
    wrapped = np.empty((1, 1), dtype=object)
    wrapped[0, 0] = value
    return wrapped


def _stamp_v73_header(path: Path) -> None:
    header = b"MATLAB 7.3 MAT-file, Platform: test, Created on: 26-Aug-2026"
    with path.open("r+b") as stream:
        stream.write(header.ljust(128, b" "))


class _Matlab73FixtureWriter:
    def __init__(self, file: h5py.File) -> None:
        self.file = file
        self.refs = file.create_group("#refs#")
        self.refs.attrs["MATLAB_class"] = np.bytes_("struct")
        self.counter = 0

    def _name(self) -> str:
        self.counter += 1
        return f"object_{self.counter:05d}"

    def value(self, value: Any) -> h5py.Group | h5py.Dataset:
        name = self._name()
        if isinstance(value, Mapping):
            group = self.refs.create_group(name)
            group.attrs["MATLAB_class"] = np.bytes_("struct")
            for field, item in value.items():
                self.reference_dataset(group, str(field), _object_scalar(item))
            return group
        if isinstance(value, (str, bytes)):
            text = value.decode("utf-8") if isinstance(value, bytes) else value
            code_units = np.asarray([ord(item) for item in text], dtype=np.uint16).reshape(1, -1)
            dataset = self.refs.create_dataset(name, data=_storage_order(code_units))
            dataset.attrs["MATLAB_class"] = np.bytes_("char")
            return dataset
        array = np.asarray(value)
        if array.dtype.names:
            if array.size != 1:
                raise AssertionError("fixture writer only emits scalar structs")
            record = array.reshape(-1, order="F")[0]
            group = self.refs.create_group(name)
            group.attrs["MATLAB_class"] = np.bytes_("struct")
            for field in array.dtype.names:
                self.reference_dataset(group, field, _object_scalar(record[field]))
            return group
        if array.dtype == object:
            dataset = self.refs.create_dataset(name, shape=_storage_order(array).shape, dtype=h5py.ref_dtype)
            matlab_refs = np.empty(array.shape, dtype=h5py.ref_dtype)
            for index in np.ndindex(array.shape):
                matlab_refs[index] = self.value(array[index]).ref
            dataset[...] = _storage_order(matlab_refs)
            dataset.attrs["MATLAB_class"] = np.bytes_("cell")
            return dataset
        if array.dtype.kind in "US":
            if array.size != 1:
                raise AssertionError("fixture text arrays must be represented as cells")
            return self.value(str(array.reshape(-1, order="F")[0]))
        dataset = self.refs.create_dataset(name, data=_storage_order(array))
        matlab_class = (
            "logical"
            if array.dtype.kind == "b"
            else {
                "f": "single" if array.dtype.itemsize == 4 else "double",
                "i": f"int{array.dtype.itemsize * 8}",
                "u": f"uint{array.dtype.itemsize * 8}",
            }[array.dtype.kind]
        )
        dataset.attrs["MATLAB_class"] = np.bytes_(matlab_class)
        return dataset

    def reference_dataset(self, group: h5py.Group, name: str, value: np.ndarray) -> h5py.Dataset:
        matlab_refs = np.empty(value.shape, dtype=h5py.ref_dtype)
        for index in np.ndindex(value.shape):
            matlab_refs[index] = self.value(value[index]).ref
        dataset = group.create_dataset(name, data=_storage_order(matlab_refs), dtype=h5py.ref_dtype)
        return dataset

    def dso(self, name: str, fields: Mapping[str, Any]) -> None:
        group = self.file.create_group(name)
        group.attrs["MATLAB_class"] = np.bytes_("struct")
        for field, value in fields.items():
            self.reference_dataset(group, field, _object_scalar(value))


def _write_v73(path: Path, **records: Mapping[str, Any]) -> Path:
    with h5py.File(path, "w", userblock_size=512) as file:
        writer = _Matlab73FixtureWriter(file)
        for name, fields in records.items():
            writer.dso(name, fields)
    _stamp_v73_header(path)
    return path


def _cell(rows: list[list[object]]) -> np.ndarray:
    result = np.empty((len(rows), max(len(row) for row in rows)), dtype=object)
    result.fill(np.empty((0, 0)))
    for row, values in enumerate(rows):
        for column, value in enumerate(values):
            result[row, column] = value
    return result


def _representative_dso() -> np.ndarray:
    fields = (
        "data",
        "name",
        "type",
        "author",
        "date",
        "description",
        "axisscale",
        "axisscalename",
        "label",
        "labelname",
        "class",
        "classname",
        "include",
        "history",
        "uniqueid",
        "datasetversion",
    )
    result = np.empty((1, 1), dtype=[(field, "O") for field in fields])
    shape = (2, 3, 4)
    result["data"][0, 0] = np.arange(24, dtype=np.float32).reshape(shape)
    result["name"][0, 0] = np.array(["Cross-storage DSO"])
    result["type"][0, 0] = np.array(["data"])
    result["author"][0, 0] = np.array(["A. Scientist"])
    result["date"][0, 0] = np.array(["2026-08-26"])
    result["description"][0, 0] = np.array(["Representative v5/v7.3 fixture"])
    result["axisscale"][0, 0] = _cell(
        [
            [np.arange(2.0), np.arange(2.0) + 0.5],
            [np.arange(3.0), np.arange(3.0) + 0.5],
            [np.arange(4.0) + 1000.0, np.arange(4.0) + 500.0],
        ]
    )
    result["axisscalename"][0, 0] = _cell(
        [
            ["sample index", "sample alternate"],
            ["time", "time alternate"],
            ["wavenumber", "wavelength"],
        ]
    )
    result["label"][0, 0] = _cell(
        [
            [np.array(["S1", "S2"], dtype=object)],
            [np.array(["T1", "T2", "T3"], dtype=object)],
            [np.array(["V1", "V2", "V3", "V4"], dtype=object)],
        ]
    )
    result["labelname"][0, 0] = _cell([["samples"], ["times"], ["variables"]])
    result["class"][0, 0] = _cell(
        [
            [np.array(["A", "B"], dtype=object)],
            [np.array([1, 1, 2], dtype=np.int32)],
            [np.array(["region-1", "region-1", "region-2", "region-2"], dtype=object)],
        ]
    )
    result["classname"][0, 0] = _cell([["specimen"], ["phase"], ["region"]])
    result["include"][0, 0] = _cell(
        [
            [np.array([1, 2], dtype=np.int32)],
            [np.array([1, 3], dtype=np.int32)],
            [np.array([1, 2, 4], dtype=np.int32)],
        ]
    )
    result["history"][0, 0] = np.array([["Imported", "Correction: none"]], dtype=object)
    result["uniqueid"][0, 0] = np.array(["cross-storage-001"])
    result["datasetversion"][0, 0] = np.array(["5.0"])
    return result


def _rich_fields(tmp_path: Path) -> Mapping[str, Any]:
    v5 = tmp_path / "source-v5.mat"
    savemat(v5, {"calibration": _representative_dso()}, do_compression=True)
    decoded = loadmat(v5, squeeze_me=False, struct_as_record=True)["calibration"]
    return scipy_struct_fields(decoded)


def test_matlab_v73_dso_reproduces_v5_science_exactly(tmp_path: Path) -> None:
    fields = _rich_fields(tmp_path)
    v73 = _write_v73(tmp_path / "source-v73.mat", calibration=fields)
    with h5py.File(v73, "r+") as file:
        file["calibration"].attrs["MATLAB_class"] = np.bytes_("DataSet")

    v5_dataset = ingest(tmp_path / "source-v5.mat").assets[0].dataset
    result = ingest(v73)
    v73_dataset = result.assets[0].dataset

    assert result.variant == "mat-v7.3-hdf5"
    assert result.parser_version == "6"
    assert v73_dataset.source_identity.storage_version == "matlab-v7.3"
    assert v73_dataset.scientific_projection() == v5_dataset.scientific_projection()
    assert v73_dataset.scientific_digest == v5_dataset.scientific_digest
    np.testing.assert_array_equal(v73_dataset.X, v5_dataset.X)


def test_matlab_v73_multiple_dso_assets_are_deterministic(tmp_path: Path) -> None:
    fields = _rich_fields(tmp_path)
    path = _write_v73(tmp_path / "multiple.mat", zeta=fields, alpha=fields)

    result = ingest(path)

    assert [asset.asset_id for asset in result.assets] == ["alpha", "zeta"]
    assert result.raw_metadata["matlab.dso_variables"] == ["alpha", "zeta"]


def test_matlab_v73_resource_census_refuses_before_decode(monkeypatch, tmp_path: Path) -> None:
    import spectra_sherpa.io.formats.matlab_v73 as decoder

    path = _write_v73(tmp_path / "bounded.mat", calibration=_rich_fields(tmp_path))
    decoded = False

    def _unexpected_decode(*_args, **_kwargs):
        nonlocal decoded
        decoded = True
        raise AssertionError("resource refusal must precede materialization")

    monkeypatch.setattr(decoder._Decoder, "decode", _unexpected_decode)
    with pytest.raises(ParserLimitError, match="decoded elements"):
        ingest(path, limits=ParserLimits(max_decoded_elements=10))
    assert decoded is False


def test_matlab_v73_combined_retained_budget_refuses_before_dso_projection(monkeypatch, tmp_path: Path) -> None:
    import spectra_sherpa.io.formats.matlab as matlab_format

    data = np.zeros((100, 100), dtype=np.float32)
    fields = {"data": data, "name": "Compressed", "type": "data"}
    path = _write_v73(tmp_path / "combined-budget.mat", compressed=fields)
    projected = False

    def _unexpected_projection(*_args, **_kwargs):
        nonlocal projected
        projected = True
        raise AssertionError("combined retained-state refusal must precede DSO projection")

    monkeypatch.setattr(matlab_format, "map_decoded_dso", _unexpected_projection)
    combined_floor = path.stat().st_size + data.nbytes + data.size * 8
    with pytest.raises(ParserLimitError, match="decoded bytes"):
        ingest(path, limits=ParserLimits(max_decoded_bytes=combined_floor - 1))
    assert projected is False


@pytest.mark.parametrize("link_kind", ["soft", "external"])
def test_matlab_v73_link_indirection_refuses_before_decode(tmp_path: Path, link_kind: str) -> None:
    path = _write_v73(tmp_path / f"{link_kind}.mat", calibration=_rich_fields(tmp_path))
    with h5py.File(path, "r+") as file:
        if link_kind == "soft":
            file["untrusted"] = h5py.SoftLink("/calibration")
        else:
            file["untrusted"] = h5py.ExternalLink("other.h5", "/payload")

    with pytest.raises(UnsupportedFormatVariantError, match="soft and external"):
        ingest(path)


def test_matlab_v73_variable_length_payload_refuses_in_preflight(tmp_path: Path) -> None:
    path = tmp_path / "vlen.mat"
    with h5py.File(path, "w", userblock_size=512) as file:
        dataset = file.create_dataset("payload", shape=(1,), dtype=h5py.string_dtype("utf-8"))
        dataset[0] = "unbounded"
    _stamp_v73_header(path)

    with pytest.raises(UnsupportedFormatVariantError, match="variable-length"):
        ingest(path)


def test_matlab_v73_plain_numeric_workspace_preserves_matlab_dimension_order(tmp_path: Path) -> None:
    path = tmp_path / "numeric.mat"
    matrix = np.arange(6.0).reshape(2, 3)
    with h5py.File(path, "w", userblock_size=512) as file:
        data = file.create_dataset("X", data=_storage_order(matrix))
        data.attrs["MATLAB_class"] = np.bytes_("double")
        axis = file.create_dataset("wavenumber", data=np.array([1000.0, 1001.0, 1002.0]))
        axis.attrs["MATLAB_class"] = np.bytes_("double")
    _stamp_v73_header(path)

    result = ingest(path)

    assert [asset.asset_id for asset in result.assets] == ["X"]
    np.testing.assert_array_equal(result.assets[0].dataset.X, matrix)
    np.testing.assert_array_equal(result.assets[0].dataset.feature_axis.values, [1000.0, 1001.0, 1002.0])


def test_matlab_v73_non_dso_struct_is_visible_in_inventory(tmp_path: Path) -> None:
    path = tmp_path / "inventory.mat"
    with h5py.File(path, "w", userblock_size=512) as file:
        data = file.create_dataset("X", data=_storage_order(np.arange(6.0).reshape(2, 3)))
        data.attrs["MATLAB_class"] = np.bytes_("double")
        metadata = file.create_group("vendor_metadata")
        metadata.attrs["MATLAB_class"] = np.bytes_("struct")
        note = metadata.create_dataset("note", data=np.array([[ord("x")]], dtype=np.uint16))
        note.attrs["MATLAB_class"] = np.bytes_("char")
    _stamp_v73_header(path)

    result = ingest(path)

    assert result.raw_metadata["matlab.unimported_struct_variables"] == ["vendor_metadata"]
    assert "inventoried but not imported" in result.warnings[0]


def test_matlab_v73_cyclic_object_reference_refuses(tmp_path: Path) -> None:
    path = tmp_path / "cycle.mat"
    with h5py.File(path, "w", userblock_size=512) as file:
        dso = file.create_group("cycle")
        dso.attrs["MATLAB_class"] = np.bytes_("struct")
        cyclic = dso.create_dataset("data", shape=(1, 1), dtype=h5py.ref_dtype)
        cyclic[0, 0] = cyclic.ref
        writer = _Matlab73FixtureWriter(file)
        writer.reference_dataset(dso, "name", _object_scalar("Cycle"))
        writer.reference_dataset(dso, "type", _object_scalar("data"))
    _stamp_v73_header(path)

    with pytest.raises(UnsupportedFormatVariantError, match="cyclic"):
        ingest(path)
