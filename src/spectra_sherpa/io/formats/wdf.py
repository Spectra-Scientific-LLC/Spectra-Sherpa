"""Bounded native reader for qualified Renishaw WiRE WDF files.

The chunk and metadata grammar is adapted from ``renishawWiRE`` 0.1.16,
commit ``b84cc3c23ee977ffd84d58a49e5a9d94260ed07c`` (MIT, T. Tian),
whose implementation follows Alex Henderson's public WDF notes
(DOI: 10.5281/zenodo.495477) and Gwyddion's Renishaw reader.  Structural
semantics are cross-checked against Renishaw Spectroscopy's Apache-2.0
``renishaw-wdf`` 1.4.0 accessor.  That accessor is a reference, not a runtime
dependency or a numerical authority: SpectraSherpa validates the immutable
source bytes independently and preserves FILETIME at its exact 100 ns scale.

SpectraSherpa owns a deliberately closed, read-only projection:

* completed single, series, line, StreamLine, and rectangular-map acquisitions;
* one Raman-shift axis and count-valued float32 spectra;
* exact per-spectrum ORGN coordinates retained as the sample table; and
* WMAP topology retained without inventing a regular grid or flattening away
  physical sample identity.

WiRE-derived ``MAP `` analysis layers are deliberately not interpreted as raw
measurements.  Their presence and identifiers are reported with an explicit
warning so a scientist cannot mistake omission for successful import.

Unknown units, incomplete acquisitions, unsupported scan/measurement types,
duplicate required chunks, inconsistent cardinalities, and malformed ranges
fail before a partial scientific dataset is returned.  Image and annotation
payloads are not decoded by this numerical ingestion boundary.
"""

from __future__ import annotations

import math
import struct
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import numpy as np

from spectra_sherpa.app.lib.axes import SampleAxis, SpectralAxis
from spectra_sherpa.app.lib.sherpa_dataset import DomainContext, SherpaDataset
from spectra_sherpa.ingestion_errors import (
    FormatIdentityError,
    ParserLimitError,
    UnreadableSpectrumError,
    UnsupportedFormatVariantError,
)
from spectra_sherpa.io.base import BoundedSource
from spectra_sherpa.io.formats._helpers import dataset_asset, ingestion_result
from spectra_sherpa.io.types import IngestionResult, ParserLimits, ProbeConfidence, ProbeResult

_BLOCK_HEADER_BYTES = 16
_WDF1_BYTES = 0x200
_MEASUREMENT_INFO_OFFSET = 0x3C
_SPECTRAL_INFO_OFFSET = 0x98
_FILE_INFO_OFFSET = 0xD0
_USER_NAME_OFFSET = 0xF0
_ORIGIN_INFO_OFFSET = 0x14
_ORIGIN_ROW_HEADER_BYTES = 0x18
_WMAP_PAYLOAD_BYTES = 48
_MAX_WDF_BLOCKS = 4_096
_DECODED_BYTES_PER_VALUE = 24
# ORGN projection retains NumPy values, exact-integer tuples, JSON-safe
# decimal strings, sample-table lists, and the defensive SampleAxis copy.
# Fixed-size tracemalloc qualification showed that the former 96-byte charge
# undercounted this retained representation by ~16%.  The 144-byte charge
# keeps the measured qualified series layout below its admitted envelope with
# additional allocator margin.
_DECODED_BYTES_PER_ORIGIN_VALUE = 144
_DECODED_BYTES_PER_SAMPLE_LABEL = 80
_WINDOWS_EPOCH = datetime(1601, 1, 1, tzinfo=UTC)

_MEASUREMENT_TYPES = {1: "single", 2: "series", 3: "mapping"}
_MEASUREMENT_VARIANTS = {1: "single-spectrum", 2: "series", 3: "mapping"}
_SCAN_TYPES = {1: "static", 6: "streamline", 7: "streamline-hr"}
_QUALIFIED_SCANS_BY_MEASUREMENT = {1: frozenset({1}), 2: frozenset({1}), 3: frozenset({6, 7})}
_QUALIFIED_ORIGINS_BY_MEASUREMENT = {
    1: frozenset({11, 16, 17}),
    2: frozenset({5, 11, 16, 17}),
    3: frozenset({3, 4, 11, 16, 17}),
}
_QUALIFIED_PRIMARY_ORIGINS_BY_MEASUREMENT = {
    1: frozenset(),
    2: frozenset({5}),
    3: frozenset({3, 4}),
}
_MAP_AREA_TYPES = {0: "unspecified-rectangular", 2: "column-major", 128: "xy-line"}

# These are the exact independently qualified WDF origin semantics.  New codes
# must acquire a conformance fixture before admission; they are not generic
# numbers whose scientific role can safely be guessed.
_ORIGIN_TYPES: dict[int, tuple[str, str]] = {
    3: ("spatial_x", "Spatial X"),
    4: ("spatial_y", "Spatial Y"),
    5: ("spatial_z", "Spatial Z"),
    11: ("acquisition_time", "Acquisition time"),
    16: ("checksum", "Checksum"),
    17: ("flags", "Flags"),
}
_ORIGIN_UNITS: dict[int, str | None] = {
    0: None,
    5: "um",
    24: "s",
}
_ORIGIN_UNIT_BY_TYPE = {3: 5, 4: 5, 5: 5, 11: 24, 16: 0, 17: 0}
_ORIGIN_VALUE_ENCODING = {
    3: "float64",
    4: "float64",
    5: "float64",
    11: "relative-float64-seconds+absolute-uint64-decimal",
    16: "uint64-decimal",
    17: "uint64-decimal-zero-qualified",
}


@dataclass(frozen=True, slots=True)
class _Block:
    name: str
    uid: int
    offset: int
    size_bytes: int

    @property
    def payload_offset(self) -> int:
        return self.offset + _BLOCK_HEADER_BYTES

    @property
    def payload_bytes(self) -> int:
        return self.size_bytes - _BLOCK_HEADER_BYTES


@dataclass(frozen=True, slots=True)
class _Header:
    version: int
    file_flags: int
    track_count: int
    status: int
    point_count: int
    capacity: int
    count: int
    accumulation_count: int
    ylist_length: int
    xlist_length: int
    origin_count: int
    application_name: str
    application_version: tuple[int, int, int, int]
    scan_type: int
    measurement_type: int
    started_filetime_100ns: int
    ended_filetime_100ns: int
    value_unit: int
    laser_frequency_cm1: float
    title: str


@dataclass(frozen=True, slots=True)
class _Dimension:
    data_type: int
    unit_type: int
    title: str
    values: np.ndarray
    is_primary: bool
    acquired_at: str | None = None
    exact_integer_values: tuple[int, ...] | None = None


@dataclass(frozen=True, slots=True)
class _Map:
    area_type: int
    offsets: tuple[float, float, float]
    increments: tuple[float, float, float]
    sizes: tuple[int, int, int]
    linefocus_size: int


def _error(detail: str, *, offset: int | None = None) -> UnreadableSpectrumError:
    return UnreadableSpectrumError(format_id="wdf", detail=detail, offset=offset)


def _text(payload: bytes, *, field: str) -> str:
    try:
        return payload.split(b"\x00", 1)[0].decode("utf-8").strip()
    except UnicodeDecodeError as exc:
        raise _error(f"{field} is not valid UTF-8") from exc


def _blocks(source: BoundedSource) -> tuple[_Block, ...]:
    blocks: list[_Block] = []
    offset = 0
    while offset < source.size_bytes:
        if len(blocks) >= _MAX_WDF_BLOCKS:
            raise ParserLimitError(f"wdf contains more than {_MAX_WDF_BLOCKS} chunks")
        source.require_blocks(len(blocks) + 1, format_id="wdf")
        if source.size_bytes - offset < _BLOCK_HEADER_BYTES:
            raise _error("trailing bytes do not contain a complete WDF chunk header", offset=offset)
        payload = source.read_at(offset, _BLOCK_HEADER_BYTES, format_id="wdf")
        try:
            name = payload[:4].decode("ascii")
        except UnicodeDecodeError as exc:
            raise _error("chunk identifier is not ASCII", offset=offset) from exc
        if any(ord(char) < 0x20 or ord(char) > 0x7E for char in name):
            raise _error("chunk identifier contains non-printable bytes", offset=offset)
        uid, size_bytes = struct.unpack_from("<IQ", payload, 4)
        if size_bytes < _BLOCK_HEADER_BYTES:
            raise _error("chunk size is smaller than its header", offset=offset + 8)
        end = offset + int(size_bytes)
        if end <= offset or end > source.size_bytes:
            raise _error("chunk extends outside the source", offset=offset + 8)
        blocks.append(_Block(name, int(uid), offset, int(size_bytes)))
        offset = end
    if offset != source.size_bytes:
        raise _error("chunk walk does not terminate at the source boundary", offset=offset)
    return tuple(blocks)


def _one(blocks: tuple[_Block, ...], name: str, *, required: bool = True) -> _Block | None:
    matches = [block for block in blocks if block.name == name]
    if len(matches) > 1:
        raise _error(f"WDF contains duplicate {name!r} chunks", offset=matches[1].offset)
    if not matches:
        if required:
            raise _error(f"WDF is missing its required {name!r} chunk")
        return None
    return matches[0]


def _header(source: BoundedSource, block: _Block) -> _Header:
    if block.offset != 0 or block.name != "WDF1" or block.uid != 1 or block.size_bytes != _WDF1_BYTES:
        raise FormatIdentityError("WDF must begin with one qualified version-1 512-byte WDF1 chunk")
    payload = source.read_at(0, _WDF1_BYTES, format_id="wdf")
    file_flags = struct.unpack_from("<Q", payload, 16)[0]
    track_count, status = struct.unpack_from("<II", payload, 52)
    point_count = struct.unpack_from("<I", payload, _MEASUREMENT_INFO_OFFSET)[0]
    capacity, count = struct.unpack_from("<QQ", payload, _MEASUREMENT_INFO_OFFSET + 4)
    accumulation_count, ylist_length, xlist_length, origin_count = struct.unpack_from(
        "<IIII", payload, _MEASUREMENT_INFO_OFFSET + 20
    )
    application_name = _text(
        payload[_MEASUREMENT_INFO_OFFSET + 36 : _MEASUREMENT_INFO_OFFSET + 60], field="application name"
    )
    application_version = struct.unpack_from("<HHHH", payload, _MEASUREMENT_INFO_OFFSET + 60)
    scan_type, measurement_type = struct.unpack_from("<II", payload, _MEASUREMENT_INFO_OFFSET + 68)
    started_filetime, ended_filetime = struct.unpack_from("<QQ", payload, _MEASUREMENT_INFO_OFFSET + 76)
    value_unit = struct.unpack_from("<I", payload, _SPECTRAL_INFO_OFFSET)[0]
    laser_frequency = struct.unpack_from("<f", payload, _SPECTRAL_INFO_OFFSET + 4)[0]
    title = _text(payload[_USER_NAME_OFFSET:_WDF1_BYTES], field="measurement title")

    if point_count < 2 or count < 1 or capacity < count:
        raise _error("WDF declares invalid point/sample capacity", offset=_MEASUREMENT_INFO_OFFSET)
    if file_flags != 0 or track_count != 0 or status != 0:
        raise UnsupportedFormatVariantError(
            "WDF version-1 flags, track count, and status must all be zero on the independently qualified surface"
        )
    if count != capacity:
        raise UnsupportedFormatVariantError(
            "Incomplete WDF acquisitions are not independently qualified; finish or export the acquisition in WiRE"
        )
    if xlist_length != point_count or ylist_length != 1:
        raise _error("WDF point count and X/Y list cardinalities disagree", offset=_MEASUREMENT_INFO_OFFSET)
    if measurement_type not in _MEASUREMENT_TYPES:
        raise UnsupportedFormatVariantError(f"WDF measurement type {measurement_type} is not independently qualified")
    if scan_type not in _SCAN_TYPES:
        raise UnsupportedFormatVariantError(f"WDF scan type {scan_type} is not independently qualified")
    if scan_type not in _QUALIFIED_SCANS_BY_MEASUREMENT[measurement_type]:
        raise UnsupportedFormatVariantError(
            f"WDF measurement/scan combination ({measurement_type}, {scan_type}) is not independently qualified"
        )
    if (measurement_type == 1 and count != 1) or (measurement_type != 1 and count < 2):
        raise _error("WDF measurement identity contradicts its sample count", offset=_MEASUREMENT_INFO_OFFSET)
    if value_unit != 6:
        raise UnsupportedFormatVariantError(
            f"WDF signal-unit code {value_unit} is not independently qualified; qualified data use detector counts"
        )
    if not math.isfinite(laser_frequency) or laser_frequency <= 0:
        raise _error("WDF laser frequency is missing or non-finite", offset=_SPECTRAL_INFO_OFFSET + 4)
    if origin_count < 1:
        raise _error("qualified WDF acquisitions require an ORGN coordinate table")
    if origin_count > len(_ORIGIN_TYPES):
        raise UnsupportedFormatVariantError(
            f"WDF declares {origin_count} ORGN columns; the qualified surface admits at most "
            f"{len(_ORIGIN_TYPES)} exact coordinate types"
        )
    if accumulation_count < 1:
        raise _error("WDF accumulation count must be positive", offset=_MEASUREMENT_INFO_OFFSET + 20)
    if started_filetime == 0 or ended_filetime == 0 or started_filetime > ended_filetime:
        raise _error("WDF measurement start/end FILETIME window is missing or reversed", offset=0x88)

    return _Header(
        version=block.uid,
        file_flags=int(file_flags),
        track_count=int(track_count),
        status=int(status),
        point_count=int(point_count),
        capacity=int(capacity),
        count=int(count),
        accumulation_count=int(accumulation_count),
        ylist_length=int(ylist_length),
        xlist_length=int(xlist_length),
        origin_count=int(origin_count),
        application_name=application_name,
        application_version=tuple(int(value) for value in application_version),
        scan_type=int(scan_type),
        measurement_type=int(measurement_type),
        started_filetime_100ns=int(started_filetime),
        ended_filetime_100ns=int(ended_filetime),
        value_unit=int(value_unit),
        laser_frequency_cm1=float(laser_frequency),
        title=title,
    )


def _dimension(
    source: BoundedSource,
    block: _Block,
    *,
    expected_length: int,
    expected_type: int,
    expected_unit: int,
    name: str,
) -> np.ndarray:
    expected_bytes = 8 + expected_length * 4
    if block.payload_bytes != expected_bytes:
        raise _error(
            f"{name} chunk has {block.payload_bytes} payload bytes; expected exactly {expected_bytes}",
            offset=block.offset,
        )
    data_type, unit_type = struct.unpack("<II", source.read_at(block.payload_offset, 8, format_id="wdf"))
    if data_type != expected_type or unit_type != expected_unit:
        raise UnsupportedFormatVariantError(
            f"WDF {name} type/unit ({data_type}, {unit_type}) is not independently qualified"
        )
    values = np.frombuffer(
        source.read_at(block.payload_offset + 8, expected_length * 4, format_id="wdf"), dtype="<f4"
    ).astype(np.float64)
    if not np.all(np.isfinite(values)):
        raise _error(f"WDF {name} contains non-finite values", offset=block.payload_offset + 8)
    return values


def _spectra(source: BoundedSource, block: _Block, header: _Header) -> np.ndarray:
    element_count = header.count * header.point_count
    expected_bytes = element_count * 4
    if block.payload_bytes != expected_bytes:
        raise _error(
            f"DATA chunk has {block.payload_bytes} payload bytes; expected exactly {expected_bytes}",
            offset=block.offset,
        )
    source.require_elements(element_count, format_id="wdf")
    source.require_decoded_bytes(element_count * _DECODED_BYTES_PER_VALUE, format_id="wdf")
    values = np.frombuffer(source.read_at(block.payload_offset, expected_bytes, format_id="wdf"), dtype="<f4").astype(
        np.float64
    )
    if not np.all(np.isfinite(values)):
        raise _error("WDF DATA contains non-finite values", offset=block.payload_offset)
    return values.reshape(header.count, header.point_count)


def _windows_filetime_text(value: int) -> str:
    whole_seconds, fractional_ticks = divmod(value, 10_000_000)
    try:
        instant = _WINDOWS_EPOCH + timedelta(seconds=whole_seconds)
    except (OverflowError, ValueError) as exc:
        raise _error("WDF acquisition timestamp lies outside the supported range") from exc
    return f"{instant.strftime('%Y-%m-%dT%H:%M:%S')}.{fractional_ticks:07d}+00:00"


def _windows_time(raw: np.ndarray) -> tuple[np.ndarray, str, tuple[int, ...]]:
    if np.any(raw > np.iinfo(np.int64).max):
        raise _error("WDF acquisition timestamp lies outside the supported range")
    signed = raw.astype(np.int64)
    if np.any(signed[1:] < signed[:-1]):
        raise _error("WDF acquisition timestamps are not ordered by sample")
    first = int(signed[0])
    if np.any(signed < first) or np.any(np.diff(signed) < 0):
        raise _error("WDF acquisition timestamps are not monotonically ordered")
    # Subtract the large Windows FILETIME epoch while values are still exact
    # integers.  Converting each absolute timestamp to float first loses
    # sub-second acquisition spacing at contemporary FILETIME magnitudes.
    relative = (signed - first).astype(np.float64) / 10_000_000.0
    acquired = _windows_filetime_text(first)
    return relative, acquired, tuple(int(value) for value in signed)


def _require_working_set(source: BoundedSource, header: _Header) -> None:
    """Admit the complete retained projection before numerical allocation.

    ORGN columns become scientist-visible ``sample_table`` lists.  Their
    Python scalar/list representation is materially larger than the on-disk
    float64 values, so it is charged separately and conservatively rather
    than hidden behind the DATA-matrix budget.
    """

    spectrum_elements = header.count * header.point_count
    origin_elements = header.count * header.origin_count
    feature_elements = header.point_count + header.ylist_length
    source.require_elements(spectrum_elements + origin_elements + feature_elements, format_id="wdf")
    projected_bytes = (
        spectrum_elements * _DECODED_BYTES_PER_VALUE
        + origin_elements * _DECODED_BYTES_PER_ORIGIN_VALUE
        + feature_elements * _DECODED_BYTES_PER_VALUE
        + header.count * _DECODED_BYTES_PER_SAMPLE_LABEL
    )
    source.require_decoded_bytes(projected_bytes, format_id="wdf")


def _origins(source: BoundedSource, block: _Block, header: _Header) -> tuple[_Dimension, ...]:
    stride = _ORIGIN_ROW_HEADER_BYTES + 8 * header.capacity
    expected_bytes = 4 + header.origin_count * stride
    if block.payload_bytes != expected_bytes:
        raise _error(
            f"ORGN chunk has {block.payload_bytes} payload bytes; expected exactly {expected_bytes}",
            offset=block.offset,
        )
    declared_count = struct.unpack("<I", source.read_at(block.payload_offset, 4, format_id="wdf"))[0]
    if declared_count != header.origin_count:
        raise _error(
            f"ORGN row count {declared_count} contradicts WDF1 origin count {header.origin_count}",
            offset=block.payload_offset,
        )
    source.require_elements(header.origin_count * header.capacity, format_id="wdf")
    dimensions: list[_Dimension] = []
    seen_types: set[int] = set()
    for index in range(header.origin_count):
        offset = block.payload_offset + 4 + index * stride
        row_header = source.read_at(offset, _ORIGIN_ROW_HEADER_BYTES, format_id="wdf")
        encoded_type, unit_type = struct.unpack_from("<II", row_header)
        is_primary = bool(encoded_type & 0x80000000)
        data_type = int(encoded_type & 0x7FFFFFFF)
        expected_unit = _ORIGIN_UNIT_BY_TYPE.get(data_type)
        if expected_unit is None or unit_type != expected_unit:
            raise UnsupportedFormatVariantError(
                f"WDF ORGN type/unit ({data_type}, {unit_type}) is not independently qualified"
            )
        if data_type in seen_types:
            raise _error("WDF ORGN repeats one coordinate type ambiguously", offset=offset)
        seen_types.add(data_type)
        declared_title = _text(row_header[8:24], field="ORGN title")
        raw = source.read_at(offset + _ORIGIN_ROW_HEADER_BYTES, 8 * header.count, format_id="wdf")
        acquired_at: str | None = None
        exact_integer_values: tuple[int, ...] | None = None
        if data_type in (11, 16, 17):
            exact_values = np.frombuffer(raw, dtype="<u8")
            exact_integer_values = tuple(int(value) for value in exact_values)
            if data_type == 11:
                values, acquired_at, exact_integer_values = _windows_time(exact_values)
            else:
                values = exact_values
                if data_type == 17 and np.any(exact_values != 0):
                    raise UnsupportedFormatVariantError(
                        "WDF spectra carry nonzero acquisition-quality flags; explicit quality and masking "
                        "semantics are required before these samples can enter modeling"
                    )
        else:
            values = np.frombuffer(raw, dtype="<f8").astype(np.float64)
            if not np.all(np.isfinite(values)):
                raise _error("WDF ORGN contains non-finite values", offset=offset + _ORIGIN_ROW_HEADER_BYTES)
        canonical_title = _ORIGIN_TYPES[data_type][1]
        title = declared_title or canonical_title
        dimensions.append(
            _Dimension(data_type, int(unit_type), title, values, is_primary, acquired_at, exact_integer_values)
        )
    return tuple(dimensions)


def _map(source: BoundedSource, block: _Block, header: _Header) -> _Map:
    if block.payload_bytes != _WMAP_PAYLOAD_BYTES:
        raise _error("WMAP chunk must contain exactly 48 payload bytes", offset=block.offset)
    payload = source.read_at(block.payload_offset, _WMAP_PAYLOAD_BYTES, format_id="wdf")
    area_type, reserved = struct.unpack_from("<II", payload)
    offsets = struct.unpack_from("<fff", payload, 8)
    increments = struct.unpack_from("<fff", payload, 20)
    sizes = struct.unpack_from("<III", payload, 32)
    linefocus_size = struct.unpack_from("<I", payload, 44)[0]
    if reserved != 0:
        raise UnsupportedFormatVariantError("WDF WMAP reserved flags are not independently qualified")
    if area_type not in _MAP_AREA_TYPES:
        raise UnsupportedFormatVariantError(f"WDF map-area type {area_type} is not independently qualified")
    if not all(math.isfinite(value) for value in (*offsets, *increments)):
        raise _error("WDF WMAP contains non-finite coordinates", offset=block.payload_offset + 8)
    if any(value < 1 for value in sizes) or math.prod(sizes) != header.count:
        raise _error("WDF WMAP dimensions do not equal the spectrum count", offset=block.payload_offset + 32)
    if sizes[2] != 1:
        raise UnsupportedFormatVariantError("Three-dimensional WDF maps are not independently qualified")
    if linefocus_size != 0:
        raise UnsupportedFormatVariantError("WDF line-focus map semantics are not independently qualified")
    if area_type == 128 and not (sizes[0] > 1 and sizes[1] == 1):
        raise _error("WDF XY-line map requires its point count on X and a singleton Y dimension")
    x_tolerance = _map_coordinate_tolerance(offsets[0], increments[0], sizes[0])
    y_tolerance = _map_coordinate_tolerance(offsets[1], increments[1], sizes[1])
    if area_type == 128:
        if abs(increments[0]) <= x_tolerance and abs(increments[1]) <= y_tolerance:
            raise _error("WDF XY-line map requires a nonzero physical X/Y step vector")
    else:
        if sizes[0] > 1 and abs(increments[0]) <= x_tolerance:
            raise _error("WDF map has multiple X positions but no resolvable X increment")
        if sizes[1] > 1 and abs(increments[1]) <= y_tolerance:
            raise _error("WDF map has multiple Y positions but no resolvable Y increment")
    return _Map(
        int(area_type),
        tuple(float(value) for value in offsets),
        tuple(float(value) for value in increments),
        tuple(int(value) for value in sizes),
        int(linefocus_size),
    )


def _map_coordinate_tolerance(start: float, increment: float, step_count: int) -> float:
    endpoint = start + increment * max(step_count - 1, 0)
    return 8.0 * max(
        abs(float(np.spacing(np.float32(start)))),
        abs(float(np.spacing(np.float32(endpoint)))),
        abs(float(np.spacing(np.float32(increment)))),
        np.finfo(np.float32).tiny,
    )


def _validate_map_origins(map_info: _Map, dimensions: tuple[_Dimension, ...], count: int) -> None:
    coordinates = {dimension.data_type: dimension.values for dimension in dimensions}
    if 3 not in coordinates or 4 not in coordinates:
        raise _error("qualified WDF maps require exact spatial X and Y ORGN columns")

    x_values = coordinates[3]
    y_values = coordinates[4]
    x_size, y_size, _z_size = map_info.sizes
    x_tolerance = _map_coordinate_tolerance(map_info.offsets[0], map_info.increments[0], x_size)
    y_tolerance = _map_coordinate_tolerance(map_info.offsets[1], map_info.increments[1], y_size)

    # Check in bounded chunks: constructing full expected coordinate arrays
    # would itself create a second map-sized allocation after parser admission.
    for start in range(0, count, 65_536):
        stop = min(start + 65_536, count)
        indices = np.arange(start, stop, dtype=np.int64)
        if map_info.area_type == 128:
            x_steps = indices
            y_steps = indices
        elif map_info.area_type == 2:
            x_steps = (indices // y_size) % x_size
            y_steps = indices % y_size
        else:
            x_steps = indices % x_size
            y_steps = (indices // x_size) % y_size
        expected_x = map_info.offsets[0] + x_steps * map_info.increments[0]
        expected_y = map_info.offsets[1] + y_steps * map_info.increments[1]
        if not np.allclose(x_values[start:stop], expected_x, rtol=0.0, atol=x_tolerance):
            raise _error("WDF WMAP X topology contradicts the exact ORGN coordinates")
        if not np.allclose(y_values[start:stop], expected_y, rtol=0.0, atol=y_tolerance):
            raise _error("WDF WMAP Y topology contradicts the exact ORGN coordinates")


def _sample_axis(dimensions: tuple[_Dimension, ...], count: int, *, measurement_type: int) -> SampleAxis:
    labels = [f"sample-{index + 1:06d}" for index in range(count)]
    table: dict[str, list[Any]] = {}
    values: np.ndarray | None = None
    units: str | None = None
    title = "Sample"
    for dimension in dimensions:
        key, canonical_title = _ORIGIN_TYPES[dimension.data_type]
        if dimension.data_type in (16, 17):
            assert dimension.exact_integer_values is not None
            table[key] = [str(value) for value in dimension.exact_integer_values]
        else:
            table[key] = dimension.values.tolist()
        if dimension.acquired_at is not None:
            table["acquired_at"] = [dimension.acquired_at] * count
        if dimension.exact_integer_values is not None:
            if dimension.data_type == 11:
                table["acquisition_filetime_100ns"] = [str(value) for value in dimension.exact_integer_values]
        # A depth series has one exact one-dimensional scientific coordinate.
        # Maps retain their two-dimensional X/Y identity in the sample table
        # and WMAP topology rather than fabricating a one-dimensional distance.
        if measurement_type == 2 and dimension.data_type == 5:
            values = dimension.values
            units = _ORIGIN_UNITS[dimension.unit_type]
            title = canonical_title
    return SampleAxis(values=values, labels=labels, units=units, title=title, sample_table=table)


def _raw_metadata(
    header: _Header,
    blocks: tuple[_Block, ...],
    dimensions: tuple[_Dimension, ...],
    detector_y: np.ndarray,
    map_info: _Map | None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "wdf_header": {
            "version": header.version,
            "file_flags": header.file_flags,
            "track_count": header.track_count,
            "status": header.status,
        },
        "measurement_type": _MEASUREMENT_TYPES[header.measurement_type],
        "scan_type": _SCAN_TYPES[header.scan_type],
        "sample_count": header.count,
        "point_count": header.point_count,
        "accumulation_count": header.accumulation_count,
        "application": header.application_name,
        "application_version": list(header.application_version),
        "laser_frequency_cm-1": header.laser_frequency_cm1,
        "title": header.title,
        "measurement_window": {
            "start_filetime_100ns": str(header.started_filetime_100ns),
            "end_filetime_100ns": str(header.ended_filetime_100ns),
            "start_utc": _windows_filetime_text(header.started_filetime_100ns),
            "end_utc": _windows_filetime_text(header.ended_filetime_100ns),
        },
        "detector_y_coordinate": {
            "data_type": "spatial_y",
            "units": "px",
            "values": detector_y.tolist(),
        },
        "origin_columns": [
            {
                "data_type": dimension.data_type,
                "name": _ORIGIN_TYPES[dimension.data_type][0],
                "unit_code": dimension.unit_type,
                "units": _ORIGIN_UNITS[dimension.unit_type],
                "title": dimension.title,
                "is_primary": dimension.is_primary,
                "value_encoding": _ORIGIN_VALUE_ENCODING[dimension.data_type],
            }
            for dimension in dimensions
        ],
        "chunks": [
            {"name": block.name, "uid": block.uid, "offset": block.offset, "size_bytes": block.size_bytes}
            for block in blocks
        ],
    }
    acquired = next((dimension.acquired_at for dimension in dimensions if dimension.acquired_at), None)
    if acquired is not None:
        payload["acquired_at"] = acquired
    if map_info is not None:
        payload["map"] = {
            "area_type": _MAP_AREA_TYPES[map_info.area_type],
            "offsets": list(map_info.offsets),
            "increments": list(map_info.increments),
            "sizes": list(map_info.sizes),
            "linefocus_size": map_info.linefocus_size,
            "projection": "sample-matrix-with-exact-origin-table",
        }
    return payload


def _read(source: BoundedSource, *, limits: ParserLimits) -> IngestionResult:
    blocks = _blocks(source)
    if not blocks:
        raise FormatIdentityError("WDF source contains no chunks")
    header_block = _one(blocks, "WDF1")
    assert header_block is not None
    header = _header(source, header_block)
    data_block = _one(blocks, "DATA")
    x_block = _one(blocks, "XLST")
    y_block = _one(blocks, "YLST")
    origin_block = _one(blocks, "ORGN")
    assert data_block is not None and x_block is not None and y_block is not None and origin_block is not None

    _require_working_set(source, header)
    spectra = _spectra(source, data_block, header)
    feature_values = _dimension(
        source,
        x_block,
        expected_length=header.xlist_length,
        expected_type=1,
        expected_unit=1,
        name="XLST",
    )
    detector_y = _dimension(source, y_block, expected_length=1, expected_type=4, expected_unit=16, name="YLST")
    if not (np.all(np.diff(feature_values) > 0) or np.all(np.diff(feature_values) < 0)):
        raise _error("WDF Raman-shift axis is not strictly monotonic", offset=x_block.payload_offset + 8)
    dimensions = _origins(source, origin_block, header)
    observed_origins = frozenset(dimension.data_type for dimension in dimensions)
    required_origins = _QUALIFIED_ORIGINS_BY_MEASUREMENT[header.measurement_type]
    if observed_origins != required_origins:
        raise UnsupportedFormatVariantError(
            "WDF acquisition ORGN roles are not independently qualified: "
            f"measurement type {header.measurement_type} requires {sorted(required_origins)}, "
            f"received {sorted(observed_origins)}"
        )
    observed_primary = frozenset(dimension.data_type for dimension in dimensions if dimension.is_primary)
    required_primary = _QUALIFIED_PRIMARY_ORIGINS_BY_MEASUREMENT[header.measurement_type]
    if observed_primary != required_primary:
        raise UnsupportedFormatVariantError(
            "WDF acquisition primary ORGN roles are not independently qualified: "
            f"measurement type {header.measurement_type} requires {sorted(required_primary)}, "
            f"received {sorted(observed_primary)}"
        )
    time_dimension = next(dimension for dimension in dimensions if dimension.data_type == 11)
    assert time_dimension.exact_integer_values is not None
    first_origin_time = time_dimension.exact_integer_values[0]
    last_origin_time = time_dimension.exact_integer_values[-1]
    if not (header.started_filetime_100ns <= first_origin_time <= last_origin_time <= header.ended_filetime_100ns):
        raise _error("WDF1 measurement window does not enclose the exact ORGN acquisition times", offset=0x88)

    map_block = _one(blocks, "WMAP", required=False)
    map_info: _Map | None = None
    if header.measurement_type == 3:
        if map_block is None:
            raise _error("WDF mapping acquisition is missing WMAP topology")
        map_info = _map(source, map_block, header)
        _validate_map_origins(map_info, dimensions, header.count)
    elif map_block is not None:
        raise _error("non-mapping WDF unexpectedly contains WMAP topology", offset=map_block.offset)

    feature_axis = SpectralAxis(values=feature_values, units="cm-1", title="Raman shift")
    variant = (
        "single-spectrum" if header.measurement_type == 1 else "series" if header.measurement_type == 2 else "mapping"
    )
    dataset = SherpaDataset(
        X=spectra,
        feature_axis=feature_axis,
        sample_axis=_sample_axis(dimensions, header.count, measurement_type=header.measurement_type),
        domain=DomainContext(
            technique="Raman",
            expected_units="cm-1",
            data_quantity="Counts",
            instrument=None,
        ),
        title=header.title or source.path.stem,
        units="count",
        extra={
            "source_file": source.path.name,
            "wdf.variant": variant,
            "wdf.map_shape": list(map_info.sizes) if map_info is not None else None,
            "wdf.detector_y_coordinate": {
                "data_type": "spatial_y",
                "units": "px",
                "values": detector_y.tolist(),
            },
        },
        data_role="X_spectra",
    )
    metadata = _raw_metadata(header, blocks, dimensions, detector_y, map_info)
    omitted_map_layers = [
        {"uid": block.uid, "size_bytes": block.size_bytes} for block in blocks if block.name == "MAP "
    ]
    warnings: tuple[str, ...] = ()
    if omitted_map_layers:
        metadata["omitted_derived_map_layers"] = omitted_map_layers
        warnings = (
            "WiRE-derived MAP analysis layers were not imported; raw spectra, physical origins, "
            "and qualified WMAP topology remain available.",
        )
    return ingestion_result(
        source=source,
        format_id="wdf",
        variant=variant,
        parser_id="spectrasherpa.native.wdf",
        parser_version="1",
        assets=(dataset_asset(dataset, asset_id="spectra", raw_metadata=metadata, warnings=warnings),),
        raw_metadata=metadata,
        warnings=warnings,
    )


class WdfPlugin:
    format_id = "wdf"
    display_name = "Renishaw WiRE WDF"
    description = "Qualified native Renishaw WiRE Raman spectra, series, line scans, and maps"
    extensions = (".wdf",)
    parser_id = "spectrasherpa.native.wdf"
    parser_version = "1"

    def probe(self, source: BoundedSource) -> ProbeResult:
        prefix = source.probe_prefix()
        exact = len(prefix) >= 16 and prefix[:4] == b"WDF1" and struct.unpack_from("<Q", prefix, 8)[0] == 512
        if exact:
            uid = struct.unpack_from("<I", prefix, 4)[0]
            variant = "wdf1-unsupported-version"
            if uid == 1:
                variant = "wdf1-unsupported-measurement"
                if len(prefix) >= _MEASUREMENT_INFO_OFFSET + 76:
                    measurement_type = struct.unpack_from("<I", prefix, _MEASUREMENT_INFO_OFFSET + 72)[0]
                    variant = _MEASUREMENT_VARIANTS.get(int(measurement_type), variant)
            return ProbeResult(
                format_id=self.format_id,
                variant=variant,
                confidence=ProbeConfidence.EXACT,
                evidence=("WDF1 chunk", "512-byte header", f"version={uid}"),
                bytes_inspected=min(len(prefix), 16),
            )
        return ProbeResult(
            format_id=self.format_id,
            variant=None,
            confidence=ProbeConfidence.NO_MATCH,
            evidence=(),
            bytes_inspected=min(len(prefix), 16),
        )

    def read(
        self,
        source: BoundedSource,
        *,
        limits: ParserLimits,
        parser_options: Mapping[str, str] | None = None,
    ) -> IngestionResult:
        if parser_options:
            raise UnsupportedFormatVariantError("WDF does not admit parser options")
        return _read(source, limits=limits)


PLUGIN = WdfPlugin()
