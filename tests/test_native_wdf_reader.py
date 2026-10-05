"""Scientific and structural qualification for the native WDF reader."""

from __future__ import annotations

import hashlib
import json
import os
import struct
import subprocess
import sys
import tracemalloc
from pathlib import Path

import numpy as np
import pytest

from spectra_sherpa.core.axis_semantics import AxisQuantity
from spectra_sherpa.ingestion_errors import (
    FormatIdentityError,
    ParserLimitError,
    UnreadableSpectrumError,
    UnsupportedFormatVariantError,
)
from spectra_sherpa.io import ingest
from spectra_sherpa.io.formats import wdf as wdf_format
from spectra_sherpa.io.types import ParserLimits

REPO_ROOT = Path(__file__).resolve().parents[3]
CONFORMANCE_PATH = REPO_ROOT / "docs" / "evidence" / "native-wdf-reader-conformance.json"
BUNDLED_ROOT = Path(__file__).parent / "fixtures" / "wdf"
# mapping.wdf is 44 MiB and is deliberately not bundled; its scientific coverage is
# a superset of the bundled line.wdf.  It is exercised only when a maintainer has
# the renishawWiRE release archive unpacked locally.
EXTERNAL_ROOT = Path.home() / ".spectrochempy" / "testdata" / "ramandata" / "wire"
SYNTHETIC_FILETIME = 132_537_600_000_000_000


def _chunk(name: bytes, payload: bytes, *, uid: int = 0, declared_size: int | None = None) -> bytes:
    size = len(payload) + 16 if declared_size is None else declared_size
    return name + struct.pack("<IQ", uid, size) + payload


def _header(
    *,
    point_count: int,
    count: int,
    capacity: int | None = None,
    origin_count: int,
    measurement_type: int,
    scan_type: int,
    value_unit: int = 6,
    title: str = "Qualified test",
    version: int = 1,
    file_flags: int = 0,
    track_count: int = 0,
    status: int = 0,
    started_filetime: int = SYNTHETIC_FILETIME - 10_000_000,
    ended_filetime: int = SYNTHETIC_FILETIME + 10_000_000,
) -> bytes:
    payload = bytearray(512)
    payload[:4] = b"WDF1"
    struct.pack_into("<IQ", payload, 4, version, 512)
    struct.pack_into("<Q", payload, 16, file_flags)
    struct.pack_into("<II", payload, 52, track_count, status)
    capacity = count if capacity is None else capacity
    struct.pack_into("<IQQIIII", payload, 0x3C, point_count, capacity, count, 1, 1, point_count, origin_count)
    payload[0x60:0x64] = b"WiRE"
    struct.pack_into("<HHHHII", payload, 0x78, 4, 4, 0, 6602, scan_type, measurement_type)
    struct.pack_into("<QQ", payload, 0x88, started_filetime, ended_filetime)
    struct.pack_into("<If", payload, 0x98, value_unit, 18789.0)
    encoded_title = title.encode("utf-8")
    payload[0xF0 : 0xF0 + len(encoded_title)] = encoded_title
    return bytes(payload)


def _origin_row(
    data_type: int,
    unit_type: int,
    title: str,
    values: list[float | int],
    *,
    time: bool = False,
    primary: bool = False,
) -> bytes:
    label = title.encode("utf-8")[:16].ljust(16, b"\x00")
    if time or data_type in (16, 17):
        data = struct.pack(f"<{len(values)}Q", *(int(value) for value in values))
    else:
        data = struct.pack(f"<{len(values)}d", *(float(value) for value in values))
    encoded_type = data_type | (0x80000000 if primary else 0)
    return struct.pack("<II", encoded_type, unit_type) + label + data


def _wdf_bytes(
    *,
    spectra: np.ndarray | None = None,
    axis: np.ndarray | None = None,
    mapping: bool = False,
    capacity: int | None = None,
    value_unit: int = 6,
    duplicate_data: bool = False,
    map_sizes: tuple[int, int, int] = (2, 2, 1),
) -> bytes:
    values = np.asarray(spectra if spectra is not None else [[1.0, 2.0, 3.0]], dtype="<f4")
    x = np.asarray(axis if axis is not None else [100.0, 200.0, 300.0], dtype="<f4")
    count, point_count = values.shape
    if mapping:
        times = [SYNTHETIC_FILETIME + index * 10_000_000 for index in range(count)]
        rows = [
            _origin_row(3, 5, "X", [float(index % map_sizes[0]) for index in range(count)], primary=True),
            _origin_row(4, 5, "Y", [float(index // map_sizes[0]) for index in range(count)], primary=True),
            _origin_row(11, 24, "Time", times, time=True),
            _origin_row(17, 0, "Flags", [0.0] * count),
            _origin_row(16, 0, "Checksum", [float(index) for index in range(count)]),
        ]
        measurement_type = 3
        scan_type = 7
    else:
        rows: list[bytes] = []
        if count > 1:
            rows.append(_origin_row(5, 5, "Z", [float(index) for index in range(count)], primary=True))
        rows.extend(
            [
                _origin_row(11, 24, "Time", [SYNTHETIC_FILETIME] * count, time=True),
                _origin_row(17, 0, "Flags", [0.0] * count),
                _origin_row(16, 0, "Checksum", [float(index) for index in range(count)]),
            ]
        )
        measurement_type = 1 if count == 1 else 2
        scan_type = 1
    parts = [
        _header(
            point_count=point_count,
            count=count,
            capacity=capacity,
            origin_count=len(rows),
            measurement_type=measurement_type,
            scan_type=scan_type,
            value_unit=value_unit,
            ended_filetime=SYNTHETIC_FILETIME + max(count, 1) * 10_000_000,
        ),
        _chunk(b"DATA", values.tobytes(order="C")),
    ]
    if duplicate_data:
        parts.append(_chunk(b"DATA", values.tobytes(order="C")))
    parts.extend(
        [
            _chunk(b"YLST", struct.pack("<IIf", 4, 16, 0.0)),
            _chunk(b"XLST", struct.pack("<II", 1, 1) + x.tobytes(order="C")),
            _chunk(b"ORGN", struct.pack("<I", len(rows)) + b"".join(rows)),
        ]
    )
    if mapping:
        parts.append(
            _chunk(
                b"WMAP",
                struct.pack("<IIffffffIIII", 0, 0, 0.0, 0.0, 0.0, 1.0, 1.0, 1.0, *map_sizes, 0),
            )
        )
    return b"".join(parts)


def _write(tmp_path: Path, payload: bytes, name: str = "source.wdf") -> Path:
    path = tmp_path / name
    path.write_bytes(payload)
    return path


def _float64_digest(value: np.ndarray) -> str:
    return hashlib.sha256(np.asarray(value, dtype="<f8").tobytes(order="C")).hexdigest()


def _sample_identity_digest(dataset: object) -> str:
    sample_axis = dataset.sample_axis  # type: ignore[attr-defined]
    payload = {"labels": sample_axis.labels, "sample_table": sample_axis.sample_table}
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _sample_axis_digest(dataset: object) -> str | None:
    sample_axis = dataset.sample_axis  # type: ignore[attr-defined]
    if sample_axis.values is None:
        return None
    return _float64_digest(sample_axis.values)


def test_native_wdf_single_spectrum_preserves_science(tmp_path: Path) -> None:
    source = _write(tmp_path, _wdf_bytes())
    result = ingest(source)
    assert result.format_id == "wdf"
    assert result.variant == "single-spectrum"
    assert result.parser_id == "spectrasherpa.native.wdf"
    asset = result.assets[0]
    assert asset.asset_id == "spectra"
    assert asset.dimension_roles == ("sample", "spectral_feature")
    np.testing.assert_array_equal(asset.dataset.X, [[1.0, 2.0, 3.0]])
    np.testing.assert_array_equal(asset.dataset.feature_axis.values, [100.0, 200.0, 300.0])
    assert asset.dataset.feature_axis.units == "cm-1"
    assert asset.dataset.feature_axis.quantity is AxisQuantity.RAMAN_SHIFT
    assert asset.dataset.domain.technique == "Raman"
    assert asset.dataset.domain.data_quantity == "Counts"
    assert asset.dataset.units == "count"
    assert asset.dataset.sample_axis.sample_table is not None
    assert asset.dataset.sample_axis.sample_table["flags"] == ["0"]
    assert asset.dataset.sample_axis.sample_table["checksum"] == ["0"]
    assert asset.dataset.domain.instrument is None
    assert result.raw_metadata["detector_y_coordinate"] == {
        "data_type": "spatial_y",
        "units": "px",
        "values": [0.0],
    }


def test_native_wdf_mapping_preserves_sample_matrix_and_physical_origins(tmp_path: Path) -> None:
    spectra = np.arange(12, dtype=np.float32).reshape(4, 3)
    result = ingest(_write(tmp_path, _wdf_bytes(spectra=spectra, mapping=True)))
    asset = result.assets[0]
    assert result.variant == "mapping"
    np.testing.assert_array_equal(asset.dataset.X, spectra)
    assert result.raw_metadata["map"] == {
        "area_type": "unspecified-rectangular",
        "offsets": [0.0, 0.0, 0.0],
        "increments": [1.0, 1.0, 1.0],
        "sizes": [2, 2, 1],
        "linefocus_size": 0,
        "projection": "sample-matrix-with-exact-origin-table",
    }
    table = asset.dataset.sample_axis.sample_table
    assert table is not None
    assert table["spatial_x"] == [0.0, 1.0, 0.0, 1.0]
    assert table["spatial_y"] == [0.0, 0.0, 1.0, 1.0]


def test_native_wdf_rejects_map_topology_that_contradicts_exact_origins(tmp_path: Path) -> None:
    payload = bytearray(_wdf_bytes(spectra=np.arange(12, dtype=np.float32).reshape(4, 3), mapping=True))
    map_offset = payload.find(b"WMAP")
    assert map_offset >= 0
    struct.pack_into("<f", payload, map_offset + 16 + 8, 50.0)
    with pytest.raises(UnreadableSpectrumError, match="WMAP X topology contradicts"):
        ingest(_write(tmp_path, bytes(payload)))


def test_native_wdf_rejects_degenerate_map_and_unqualified_linefocus(tmp_path: Path) -> None:
    payload = bytearray(_wdf_bytes(spectra=np.arange(12, dtype=np.float32).reshape(4, 3), mapping=True))
    map_offset = payload.find(b"WMAP")
    origin_offset = payload.find(b"ORGN")
    assert map_offset >= 0 and origin_offset >= 0
    # The WMAP X step and every exact X origin agree at zero, but two declared
    # X positions would collapse onto the same physical wells.
    struct.pack_into("<f", payload, map_offset + 16 + 20, 0.0)
    x_values_offset = origin_offset + 16 + 4 + 24
    struct.pack_into("<4d", payload, x_values_offset, 0.0, 0.0, 0.0, 0.0)
    with pytest.raises(UnreadableSpectrumError, match="multiple X positions but no resolvable X increment"):
        ingest(_write(tmp_path, bytes(payload), "degenerate-map.wdf"))

    payload = bytearray(_wdf_bytes(spectra=np.arange(12, dtype=np.float32).reshape(4, 3), mapping=True))
    map_offset = payload.find(b"WMAP")
    struct.pack_into("<I", payload, map_offset + 16 + 44, 2)
    with pytest.raises(UnsupportedFormatVariantError, match="line-focus"):
        ingest(_write(tmp_path, bytes(payload), "linefocus-map.wdf"))


def test_native_wdf_rejects_origin_unit_and_row_count_contradictions(tmp_path: Path) -> None:
    payload = bytearray(_wdf_bytes())
    origin_offset = payload.find(b"ORGN")
    assert origin_offset >= 0
    struct.pack_into("<I", payload, origin_offset + 16, 2)
    with pytest.raises(UnreadableSpectrumError, match="row count 2 contradicts"):
        ingest(_write(tmp_path, bytes(payload), "bad-origin-count.wdf"))

    payload = bytearray(_wdf_bytes())
    origin_offset = payload.find(b"ORGN")
    struct.pack_into("<I", payload, origin_offset + 16 + 4 + 4, 5)
    with pytest.raises(UnsupportedFormatVariantError, match=r"type/unit \(11, 5\)"):
        ingest(_write(tmp_path, bytes(payload), "bad-origin-unit.wdf"))


def test_native_wdf_rejects_unqualified_measurement_scan_cross_product(tmp_path: Path) -> None:
    payload = bytearray(_wdf_bytes())
    struct.pack_into("<I", payload, 0x80, 6)
    with pytest.raises(UnsupportedFormatVariantError, match=r"combination \(1, 6\)"):
        ingest(_write(tmp_path, bytes(payload)))


@pytest.mark.parametrize(
    ("offset", "encoding", "value", "error"),
    [
        (4, "<I", 0, "qualified version-1"),
        (16, "<Q", 1, "flags, track count, and status"),
        (52, "<I", 2, "flags, track count, and status"),
        (56, "<I", 99, "flags, track count, and status"),
    ],
)
def test_native_wdf_rejects_unqualified_wdf1_header_surface(
    tmp_path: Path, offset: int, encoding: str, value: int, error: str
) -> None:
    payload = bytearray(_wdf_bytes())
    struct.pack_into(encoding, payload, offset, value)
    with pytest.raises((FormatIdentityError, UnsupportedFormatVariantError), match=error):
        ingest(_write(tmp_path, bytes(payload), f"header-{offset}.wdf"))


def test_native_wdf_requires_header_window_to_enclose_exact_origin_times(tmp_path: Path) -> None:
    payload = bytearray(_wdf_bytes())
    struct.pack_into("<QQ", payload, 0x88, SYNTHETIC_FILETIME + 20, SYNTHETIC_FILETIME + 10)
    with pytest.raises(UnreadableSpectrumError, match="missing or reversed"):
        ingest(_write(tmp_path, bytes(payload), "reversed-window.wdf"))

    payload = bytearray(_wdf_bytes())
    struct.pack_into(
        "<QQ",
        payload,
        0x88,
        SYNTHETIC_FILETIME + 1,
        SYNTHETIC_FILETIME + 10_000_000,
    )
    with pytest.raises(UnreadableSpectrumError, match="does not enclose"):
        ingest(_write(tmp_path, bytes(payload), "out-of-window.wdf"))

    payload = bytearray(_wdf_bytes(spectra=np.arange(9, dtype=np.float32).reshape(3, 3)))
    origin_offset = payload.find(b"ORGN")
    assert origin_offset >= 0
    stride = 24 + 8 * 3
    time_value_offset = origin_offset + 16 + 4 + stride + 24
    struct.pack_into(
        "<QQQ",
        payload,
        time_value_offset,
        SYNTHETIC_FILETIME,
        SYNTHETIC_FILETIME + 2,
        SYNTHETIC_FILETIME + 1,
    )
    with pytest.raises(UnreadableSpectrumError, match="not ordered by sample"):
        ingest(_write(tmp_path, bytes(payload), "unordered-origin-time.wdf"))


def test_native_wdf_preserves_uint64_checksum_and_rejects_nonzero_quality_flags(tmp_path: Path) -> None:
    payload = bytearray(_wdf_bytes())
    origin_offset = payload.find(b"ORGN")
    assert origin_offset >= 0
    stride = 24 + 8
    flags_value_offset = origin_offset + 16 + 4 + stride + 24
    struct.pack_into("<Q", payload, flags_value_offset, 3)
    with pytest.raises(UnsupportedFormatVariantError, match="nonzero acquisition-quality flags"):
        ingest(_write(tmp_path, bytes(payload), "flagged.wdf"))

    payload = bytearray(_wdf_bytes())
    origin_offset = payload.find(b"ORGN")
    checksum_value_offset = origin_offset + 16 + 4 + 2 * stride + 24
    exact_checksum = 9_007_199_254_740_993
    struct.pack_into("<Q", payload, checksum_value_offset, exact_checksum)
    result = ingest(_write(tmp_path, bytes(payload), "large-checksum.wdf"))
    table = result.assets[0].dataset.sample_axis.sample_table
    assert table is not None
    assert table["checksum"] == [str(exact_checksum)]


def test_native_wdf_rejects_unqualified_origin_role_and_primary_sets(tmp_path: Path) -> None:
    payload = bytearray(_wdf_bytes(spectra=np.arange(6, dtype=np.float32).reshape(2, 3)))
    origin_offset = payload.find(b"ORGN")
    assert origin_offset >= 0
    # Turn the required Spatial-Z coordinate into a duplicate Checksum
    # coordinate without changing the structural row count.
    struct.pack_into("<II", payload, origin_offset + 16 + 4, 16, 0)
    with pytest.raises(UnreadableSpectrumError, match="repeats one coordinate type"):
        ingest(_write(tmp_path, bytes(payload), "missing-series-z.wdf"))

    payload = bytearray(_wdf_bytes(spectra=np.arange(6, dtype=np.float32).reshape(2, 3)))
    origin_offset = payload.find(b"ORGN")
    struct.pack_into("<I", payload, origin_offset + 16 + 4, 5)
    with pytest.raises(UnsupportedFormatVariantError, match="primary ORGN roles"):
        ingest(_write(tmp_path, bytes(payload), "nonprimary-series-z.wdf"))


@pytest.mark.parametrize(
    ("payload", "error"),
    [
        (_wdf_bytes(duplicate_data=True), "duplicate 'DATA'"),
        (_wdf_bytes(capacity=2), "Incomplete WDF acquisitions"),
        (_wdf_bytes(value_unit=17), "signal-unit code 17"),
        (_wdf_bytes(axis=np.array([100.0, 100.0, 200.0], dtype=np.float32)), "not strictly monotonic"),
        (
            _wdf_bytes(spectra=np.array([[1.0, np.nan, 3.0]], dtype=np.float32)),
            "non-finite",
        ),
        (
            _wdf_bytes(spectra=np.arange(12, dtype=np.float32).reshape(4, 3), mapping=True, map_sizes=(3, 2, 1)),
            "dimensions do not equal",
        ),
    ],
)
def test_native_wdf_fails_closed_on_scientific_contradictions(tmp_path: Path, payload: bytes, error: str) -> None:
    with pytest.raises((UnreadableSpectrumError, UnsupportedFormatVariantError), match=error):
        ingest(_write(tmp_path, payload))


def test_native_wdf_rejects_chunk_outside_source(tmp_path: Path) -> None:
    payload = bytearray(_wdf_bytes())
    data_offset = 512
    struct.pack_into("<Q", payload, data_offset + 8, len(payload) + 1)
    with pytest.raises(UnreadableSpectrumError, match="extends outside"):
        ingest(_write(tmp_path, bytes(payload)))


def test_native_wdf_rejects_decoded_allocation_before_data_materialization(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = _write(tmp_path, _wdf_bytes())
    original = np.frombuffer

    def guarded(*args: object, **kwargs: object) -> np.ndarray:
        dtype = kwargs.get("dtype")
        if dtype == "<f4" or (len(args) > 1 and args[1] == "<f4"):
            raise AssertionError("numeric WDF allocation must not begin above the element ceiling")
        return original(*args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(np, "frombuffer", guarded)
    with pytest.raises(ParserLimitError, match="decoded elements"):
        ingest(source, limits=ParserLimits(max_decoded_elements=2))


def test_native_wdf_charges_origin_projection_before_data_materialization(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = _write(tmp_path, _wdf_bytes())
    original = np.frombuffer

    def guarded(*args: object, **kwargs: object) -> np.ndarray:
        dtype = kwargs.get("dtype")
        if dtype in ("<f4", "<f8", "<u8") or (len(args) > 1 and args[1] in ("<f4", "<f8", "<u8")):
            raise AssertionError("WDF numerical allocation must not begin above the aggregate working-set ceiling")
        return original(*args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(np, "frombuffer", guarded)
    with pytest.raises(ParserLimitError, match="decoded bytes"):
        ingest(source, limits=ParserLimits(max_decoded_bytes=100))


def test_native_wdf_charges_generated_sample_labels_before_data_materialization(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    count = 50_000
    source = _write(
        tmp_path,
        _wdf_bytes(
            spectra=np.zeros((count, 2), dtype=np.float32),
            axis=np.array([100.0, 200.0], dtype=np.float32),
        ),
    )
    spectrum_elements = count * 2
    origin_elements = count * 4
    feature_elements = 3
    budget_without_labels = spectrum_elements * 24 + origin_elements * 144 + feature_elements * 24

    def must_not_materialize(*_args: object, **_kwargs: object) -> np.ndarray:
        raise AssertionError("WDF DATA allocation must not begin before the label budget is admitted")

    monkeypatch.setattr(wdf_format, "_spectra", must_not_materialize)
    with pytest.raises(ParserLimitError, match="decoded bytes"):
        ingest(source, limits=ParserLimits(max_decoded_bytes=budget_without_labels))


def test_native_wdf_json_safe_origin_projection_stays_within_charged_memory(tmp_path: Path) -> None:
    count = 50_000
    source = _write(
        tmp_path,
        _wdf_bytes(
            spectra=np.zeros((count, 2), dtype=np.float32),
            axis=np.array([100.0, 200.0], dtype=np.float32),
        ),
    )
    assert wdf_format._DECODED_BYTES_PER_ORIGIN_VALUE == 144
    projected_bytes = count * (2 * 24 + 4 * 144 + 80) + 3 * 24

    tracemalloc.start()
    try:
        result = ingest(source, limits=ParserLimits(max_decoded_bytes=projected_bytes))
        _current, peak_bytes = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()

    assert result.assets[0].dataset.shape == (count, 2)
    assert peak_bytes <= projected_bytes


def test_native_wdf_rejects_old_origin_charge_before_numerical_materialization(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    count = 50_000
    source = _write(
        tmp_path,
        _wdf_bytes(
            spectra=np.zeros((count, 2), dtype=np.float32),
            axis=np.array([100.0, 200.0], dtype=np.float32),
        ),
    )
    old_undercharged_budget = count * (2 * 24 + 4 * 96 + 80) + 3 * 24

    def must_not_materialize(*_args: object, **_kwargs: object) -> np.ndarray:
        raise AssertionError("WDF DATA allocation must not begin under the retired origin-value charge")

    monkeypatch.setattr(wdf_format, "_spectra", must_not_materialize)
    with pytest.raises(ParserLimitError, match="decoded bytes"):
        ingest(source, limits=ParserLimits(max_decoded_bytes=old_undercharged_budget))


def test_native_wdf_time_spacing_is_subtracted_before_float_conversion(tmp_path: Path) -> None:
    payload = _wdf_bytes(spectra=np.arange(6, dtype=np.float32).reshape(2, 3))
    source = _write(tmp_path, payload)
    result = ingest(source)
    table = result.assets[0].dataset.sample_axis.sample_table
    assert table is not None
    # Rewrite the synthetic series with a one-tick (100 ns) difference to
    # prove that contemporary FILETIME magnitudes do not erase the spacing.
    raw = bytearray(payload)
    origin_offset = raw.find(b"ORGN")
    assert origin_offset >= 0
    stride = 24 + 8 * 2
    first_value_offset = origin_offset + 16 + 4 + stride + 24
    first = 132_537_600_000_000_000
    struct.pack_into("<QQ", raw, first_value_offset, first, first + 1)
    precise = ingest(_write(tmp_path, bytes(raw), "precise-time.wdf"))
    precise_table = precise.assets[0].dataset.sample_axis.sample_table
    assert precise_table is not None
    assert precise_table["acquisition_time"] == [0.0, 1e-7]
    assert precise_table["acquisition_filetime_100ns"] == [str(first), str(first + 1)]
    assert precise_table["acquired_at"] == ["2020-12-30T00:00:00.0000000+00:00"] * 2


def test_native_wdf_reports_omitted_derived_map_layers(tmp_path: Path) -> None:
    payload = _wdf_bytes(spectra=np.arange(6, dtype=np.float32).reshape(2, 3)) + _chunk(
        b"MAP ", b"derived-analysis-payload", uid=7
    )
    result = ingest(_write(tmp_path, payload, "derived-map-layer.wdf"))
    assert result.raw_metadata["omitted_derived_map_layers"] == [
        {"uid": 7, "size_bytes": 16 + len(b"derived-analysis-payload")}
    ]
    assert result.warnings == (
        "WiRE-derived MAP analysis layers were not imported; raw spectra, physical origins, "
        "and qualified WMAP topology remain available.",
    )
    assert result.assets[0].warnings == result.warnings


def test_native_wdf_rejects_parser_options(tmp_path: Path) -> None:
    with pytest.raises(UnsupportedFormatVariantError, match="does not admit parser options"):
        ingest(_write(tmp_path, _wdf_bytes()), parser_options={"layout": "mapping"})


def test_native_wdf_executes_without_spectrochempy_import(tmp_path: Path) -> None:
    source = _write(tmp_path, _wdf_bytes())
    env = dict(os.environ)
    env["SOURCE"] = str(source)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    command = """
import builtins
import sys
real_import = builtins.__import__
def guarded(name, *args, **kwargs):
    if name == 'spectrochempy' or name.startswith('spectrochempy.'):
        raise AssertionError(name)
    return real_import(name, *args, **kwargs)
builtins.__import__ = guarded
from spectra_sherpa.io import ingest
result = ingest(__import__('os').environ['SOURCE'])
assert result.assets[0].dataset.shape == (1, 3)
assert not any(name == 'spectrochempy' or name.startswith('spectrochempy.') for name in sys.modules)
"""
    completed = subprocess.run([sys.executable, "-c", command], env=env, text=True, capture_output=True, check=False)
    assert completed.returncode == 0, completed.stderr


def test_external_wdf_conformance_binds_full_science_and_sample_identity() -> None:
    record = json.loads(CONFORMANCE_PATH.read_text(encoding="utf-8"))
    assert record["schema_version"] == "spectrasherpa-native-wdf-conformance/1"
    assert record["structural_cross_check"] == {
        "project": "renishaw-wdf",
        "version": "1.4.0",
        "publisher": "Renishaw Spectroscopy",
        "license": "Apache-2.0",
        "role": (
            "Independent section, origin, Y-list, WMAP, and derived-MAP structural comparator; "
            "not a runtime dependency or FILETIME numerical oracle"
        ),
    }
    assert record["qualified_wdf_header"] == {
        "version": 1,
        "file_flags": 0,
        "track_count": 0,
        "status": 0,
    }
    assert record["domain_projection"] == {
        "technique": "Raman",
        "sample_type": None,
        "measurement_mode": None,
        "expected_units": "cm-1",
        "data_quantity": "Counts",
        "instrument": None,
        "inferred": None,
    }
    assert len(record["fixtures"]) == 5
    assert sum(1 for item in record["fixtures"] if item["bundled"]) == 4
    checked = 0
    for expected in record["fixtures"]:
        if expected["bundled"]:
            source = BUNDLED_ROOT / expected["filename"]
            assert source.is_file(), f"bundled WDF conformance fixture is missing: {source}"
        else:
            source = EXTERNAL_ROOT / expected["filename"]
            if not source.exists():
                continue
        checked += 1
        assert hashlib.sha256(source.read_bytes()).hexdigest() == expected["source_sha256"]
        result = ingest(source)
        asset = result.assets[0]
        dataset = asset.dataset
        assert result.variant == expected["variant"]
        assert list(dataset.shape) == expected["shape"]
        assert _float64_digest(dataset.X) == expected["x_sha256"]
        assert _float64_digest(dataset.feature_axis.values) == expected["feature_axis_sha256"]
        assert _sample_identity_digest(dataset) == expected["sample_identity_sha256"]
        assert _sample_axis_digest(dataset) == expected["sample_axis_sha256"]
        assert dataset.sample_axis.title == expected["sample_axis_title"]
        assert dataset.sample_axis.units == expected["sample_axis_units"]
        assert dataset.domain.model_dump(mode="json") == record["domain_projection"]
        assert result.raw_metadata["wdf_header"] == record["qualified_wdf_header"]
        assert result.raw_metadata["measurement_window"] == expected["measurement_window"]
        assert result.raw_metadata["detector_y_coordinate"] == expected["detector_y_coordinate"]
        assert result.raw_metadata["origin_columns"] == expected["origin_columns"]
        assert result.raw_metadata.get("omitted_derived_map_layers") == expected["omitted_derived_map_layers"]
        assert list(result.warnings) == expected["warnings"]
        assert list(asset.warnings) == expected["warnings"]
        assert dataset.title == expected["title"]
        assert dataset.units == expected["units"]
        assert dataset.feature_axis.units == expected["feature_units"]
        assert list(asset.dimension_roles) == expected["dimension_roles"]
        assert result.raw_metadata.get("map") == expected["map"]

    assert checked >= 4, "every bundled WDF conformance fixture must be exercised"
