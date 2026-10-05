"""Bounded native reader for qualified Galactic/Thermo GRAMS SPC files.

The binary grammar follows the *Galactic Universal Data Format
Specification*, revision 4.50 (1997).  Read-only implementation structure was
cross-checked against ``spc-io`` 0.2.1, commit
``855cf9bf08e847dc62759608b7b387e410af79ed`` (MIT, CHARISMA H2020 / IDEAconsult)
and ``spc-parser`` 2.1.0, commit
``f770e788bd553ac8ebe6c831b4619280d083016e`` (MIT, cheminfo).

SpectraSherpa owns the checked-range, allocation, typed-axis, multi-asset, and
provenance boundaries.  Independent-X (``XYXY``) subfiles remain separate
assets; the reader never interpolates or silently flattens them.
"""

from __future__ import annotations

import math
import struct
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

import numpy as np

from spectra_sherpa.app.lib.axes import (
    FeatureAxis,
    FrequencyAxis,
    MZAxis,
    SampleAxis,
    SpectralAxis,
    TimeAxis,
)
from spectra_sherpa.app.lib.sherpa_dataset import DomainContext, SherpaDataset
from spectra_sherpa.ingestion_errors import (
    FormatIdentityError,
    ParserLimitError,
    UnreadableSpectrumError,
    UnsupportedFormatVariantError,
)
from spectra_sherpa.io.base import BoundedSource
from spectra_sherpa.io.formats._helpers import dataset_asset, derive_data_role, ingestion_result
from spectra_sherpa.io.types import IngestionResult, ParserLimits, ProbeConfidence, ProbeResult

_NEW_HEADER_BYTES = 512
_OLD_HEADER_BYTES = 256
_SUBHEADER_BYTES = 32
_DIRECTORY_ENTRY_BYTES = 12
_LOG_HEADER_BYTES = 64
_VERSION_NEW_LSB = 0x4B
_VERSION_NEW_MSB = 0x4C
_VERSION_OLD_LSB = 0x4D

_TSPREC = 0x01
_TCGRAM = 0x02
_TMULTI = 0x04
_TRANDM = 0x08
_TORDRD = 0x10
_TALABS = 0x20
_TXYXYS = 0x40
_TXVALS = 0x80

# Conservatively charges output arrays, float conversion, typed-axis state,
# and the retained source-independent dataset projection before decoding.
_DECODED_BYTES_PER_POINT = 32

# Independent-X SPC files become one typed asset per subfile because their
# axes cannot be combined without an invented interpolation policy.  Bound
# that object cardinality separately from the numeric-element ceiling: tens
# of thousands of one-point subfiles are cheap in encoded bytes but expensive
# as Python/Dataset objects.  4,096 still admits well beyond common 96/384/
# 1,536-well laboratory layouts while keeping the in-process projection
# inside the node's resource envelope.
_MAX_INDEPENDENT_ASSETS = 4_096

_X_TYPES: dict[int, tuple[str, str | None, type[FeatureAxis]]] = {
    0: ("Arbitrary", None, FeatureAxis),
    1: ("Wavenumber", "cm-1", SpectralAxis),
    2: ("Wavelength", "um", SpectralAxis),
    3: ("Wavelength", "nm", SpectralAxis),
    4: ("Time", "s", TimeAxis),
    5: ("Time", "min", TimeAxis),
    6: ("Frequency", "Hz", FrequencyAxis),
    7: ("Frequency", "kHz", FrequencyAxis),
    8: ("Frequency", "MHz", FrequencyAxis),
    9: ("Mass-to-charge", "m/z", MZAxis),
    10: ("Chemical shift", "ppm", FrequencyAxis),
    11: ("Time", "day", TimeAxis),
    12: ("Time", "year", TimeAxis),
    13: ("Raman shift", "cm-1", SpectralAxis),
    14: ("Energy", "eV", FeatureAxis),
    16: ("Diode number", None, FeatureAxis),
    17: ("Channel", None, FeatureAxis),
    18: ("Angle", "degree", FeatureAxis),
    19: ("Temperature", "degF", FeatureAxis),
    20: ("Temperature", "degC", FeatureAxis),
    21: ("Temperature", "K", FeatureAxis),
    22: ("Data point", None, FeatureAxis),
    23: ("Time", "ms", TimeAxis),
    24: ("Time", "us", TimeAxis),
    25: ("Time", "ns", TimeAxis),
    26: ("Frequency", "GHz", FrequencyAxis),
    27: ("Distance", "cm", FeatureAxis),
    28: ("Distance", "m", FeatureAxis),
    29: ("Distance", "mm", FeatureAxis),
    30: ("Time", "h", TimeAxis),
}

_Y_TYPES: dict[int, tuple[str, str | None]] = {
    0: ("Arbitrary intensity", None),
    1: ("Interferogram", None),
    2: ("Absorbance", "absorbance"),
    3: ("Kubelka-Munk", None),
    4: ("Counts", "count"),
    5: ("Voltage", "V"),
    6: ("Angle", "degree"),
    7: ("Current", "mA"),
    8: ("Distance", "mm"),
    9: ("Voltage", "mV"),
    10: ("Log reflectance", None),
    11: ("Percent", "%"),
    12: ("Intensity", None),
    13: ("Relative intensity", None),
    14: ("Energy", None),
    16: ("Decibel", "dB"),
    19: ("Temperature", "degF"),
    20: ("Temperature", "degC"),
    21: ("Temperature", "K"),
    22: ("Index of refraction", None),
    23: ("Extinction coefficient", None),
    24: ("Real", None),
    25: ("Imaginary", None),
    26: ("Complex", None),
    128: ("Transmission", "%"),
    129: ("Reflectance", "%"),
    130: ("Single-beam intensity", None),
    131: ("Emission", None),
    255: ("Reference energy", None),
}

_TECHNIQUES = {
    1: "Gas chromatography",
    2: "Chromatography",
    3: "HPLC",
    4: "IR",
    5: "NIR",
    7: "UV-Vis",
    8: "X-ray diffraction",
    9: "Mass spectrometry",
    10: "NMR",
    11: "Raman",
    12: "Fluorescence",
    13: "Atomic spectroscopy",
    14: "Diode-array chromatography",
}


@dataclass(frozen=True, slots=True)
class _Header:
    version: int
    endian: str
    flags: int
    experiment: int | None
    exponent: int
    point_count: int
    first_x: float
    last_x: float
    subfile_count: int | None
    x_type: int
    y_type: int
    z_type: int | None
    date_value: int | None
    resolution: str
    source_instrument: str
    comment: str
    axis_labels: tuple[str, str, str]
    log_offset: int
    method_file: str
    z_increment: float | None
    w_planes: int
    w_increment: float | None
    w_type: int | None
    scans: int | None

    @property
    def header_bytes(self) -> int:
        return _OLD_HEADER_BYTES if self.version == _VERSION_OLD_LSB else _NEW_HEADER_BYTES

    @property
    def multi(self) -> bool:
        return bool(self.flags & _TMULTI)

    @property
    def explicit_x(self) -> bool:
        return bool(self.flags & _TXVALS)

    @property
    def independent_x(self) -> bool:
        return bool(self.flags & _TXYXYS)

    @property
    def precision_bytes(self) -> int:
        return 2 if self.flags & _TSPREC else 4


@dataclass(frozen=True, slots=True)
class _Subheader:
    offset: int
    flags: int
    exponent: int
    index: int
    first_z: float
    next_z: float
    noise: float
    point_count: int
    scans: int
    w_level: float


@dataclass(frozen=True, slots=True)
class _Layout:
    subheader: _Subheader
    x_offset: int | None
    y_offset: int
    y_bytes: int
    storage_bytes: int
    trailing_padding_bytes: int
    directory_time: float | None


def _error(detail: str, *, offset: int | None = None) -> UnreadableSpectrumError:
    return UnreadableSpectrumError(format_id="spc", detail=detail, offset=offset)


def _text(payload: bytes) -> str:
    return payload.split(b"\x00", 1)[0].decode("latin-1").strip()


def _axis_labels(payload: bytes) -> tuple[str, str, str]:
    # The three labels are variable-length, NUL-terminated X/Y/Z strings that
    # share this 30-byte field; they are not fixed ten-byte columns.
    values = payload.split(b"\x00")[:3]
    values.extend([b""] * (3 - len(values)))
    return tuple(value.decode("latin-1").strip() for value in values)  # type: ignore[return-value]


def _finite(value: float, *, name: str, offset: int) -> float:
    if not math.isfinite(value):
        raise _error(f"header contains non-finite {name}", offset=offset)
    return value


def _new_header(source: BoundedSource, *, endian: str) -> _Header:
    payload = source.read_at(0, _NEW_HEADER_BYTES, format_id="spc")
    flags, version, experiment = payload[0], payload[1], payload[2]
    exponent = struct.unpack_from("b", payload, 3)[0]
    point_count = struct.unpack_from(f"{endian}I", payload, 4)[0]
    first_x, last_x = struct.unpack_from(f"{endian}dd", payload, 8)
    subfile_count = struct.unpack_from(f"{endian}I", payload, 24)[0]
    date_value = struct.unpack_from(f"{endian}I", payload, 32)[0]
    log_offset = struct.unpack_from(f"{endian}I", payload, 248)[0]
    z_increment = struct.unpack_from(f"{endian}f", payload, 312)[0]
    w_planes = struct.unpack_from(f"{endian}I", payload, 316)[0]
    w_increment = struct.unpack_from(f"{endian}f", payload, 320)[0]
    header = _Header(
        version=version,
        endian=endian,
        flags=flags,
        experiment=experiment,
        exponent=exponent,
        point_count=int(point_count),
        first_x=_finite(first_x, name="first X coordinate", offset=8),
        last_x=_finite(last_x, name="last X coordinate", offset=16),
        subfile_count=int(subfile_count),
        x_type=payload[28],
        y_type=payload[29],
        z_type=payload[30],
        date_value=int(date_value),
        resolution=_text(payload[36:45]),
        source_instrument=_text(payload[45:54]),
        comment=_text(payload[88:218]),
        axis_labels=_axis_labels(payload[218:248]),
        log_offset=int(log_offset),
        method_file=_text(payload[264:312]),
        z_increment=_finite(z_increment, name="Z increment", offset=312),
        w_planes=int(w_planes),
        w_increment=_finite(w_increment, name="W increment", offset=320),
        w_type=payload[324],
        scans=None,
    )
    _validate_header(source, header)
    return header


def _old_header(source: BoundedSource) -> _Header:
    payload = source.read_at(0, _OLD_HEADER_BYTES, format_id="spc")
    exponent = struct.unpack_from("<h", payload, 2)[0]
    encoded_count = struct.unpack_from("<f", payload, 4)[0]
    if not math.isfinite(encoded_count) or encoded_count < 1 or encoded_count != float(int(encoded_count)):
        raise _error("old-format point count is not a positive exact integer", offset=4)
    first_x, last_x = struct.unpack_from("<ff", payload, 8)
    header = _Header(
        version=payload[1],
        endian="<",
        flags=payload[0],
        experiment=None,
        exponent=exponent,
        point_count=int(encoded_count),
        first_x=_finite(float(first_x), name="first X coordinate", offset=8),
        last_x=_finite(float(last_x), name="last X coordinate", offset=12),
        subfile_count=None,
        x_type=payload[16],
        y_type=payload[17],
        z_type=None,
        date_value=None,
        resolution=_text(payload[24:32]),
        source_instrument="",
        comment=_text(payload[64:194]),
        axis_labels=_axis_labels(payload[194:224]),
        log_offset=0,
        method_file="",
        z_increment=None,
        w_planes=0,
        w_increment=None,
        w_type=None,
        scans=struct.unpack_from("<H", payload, 34)[0],
    )
    _validate_header(source, header)
    return header


def _header(source: BoundedSource) -> _Header:
    if source.size_bytes < 2:
        raise _error("file is shorter than the SPC identity bytes", offset=source.size_bytes)
    identity = source.read_at(0, 2, format_id="spc")
    version = identity[1]
    if version == _VERSION_NEW_LSB:
        return _new_header(source, endian="<")
    if version == _VERSION_NEW_MSB:
        return _new_header(source, endian=">")
    if version == _VERSION_OLD_LSB:
        return _old_header(source)
    raise FormatIdentityError("SPC parser received bytes without a Galactic SPC version identifier")


def _validate_header(source: BoundedSource, header: _Header) -> None:
    if source.size_bytes < header.header_bytes:
        raise _error(f"source is shorter than the {header.header_bytes}-byte SPC header")
    if header.flags & _TXYXYS and not (header.flags & _TXVALS and header.flags & _TMULTI):
        raise _error("TXYXYS requires both TXVALS and TMULTI", offset=0)
    if header.version == _VERSION_OLD_LSB and header.flags & (_TXVALS | _TXYXYS | _TCGRAM):
        raise UnsupportedFormatVariantError(
            "Old-format SPC explicit-X and experiment-extension variants are not independently qualified"
        )
    if header.version != _VERSION_OLD_LSB and header.flags & _TCGRAM:
        raise UnsupportedFormatVariantError("Galactic experiment-extension SPC files are not independently qualified")
    if header.flags & _TRANDM:
        raise UnsupportedFormatVariantError("Random-order Galactic SPC multifiles are not independently qualified")
    if header.w_planes:
        raise UnsupportedFormatVariantError(
            "Four-dimensional Galactic SPC W-plane files are not independently qualified"
        )
    custom_x = bool(header.flags & _TALABS and header.axis_labels[0])
    custom_y = bool(header.flags & _TALABS and header.axis_labels[1])
    custom_z = bool(header.flags & _TALABS and header.axis_labels[2])
    if header.x_type not in _X_TYPES and not custom_x:
        raise UnsupportedFormatVariantError(f"Galactic SPC X unit type {header.x_type} is not qualified")
    if header.y_type not in _Y_TYPES and not custom_y:
        raise UnsupportedFormatVariantError(f"Galactic SPC Y unit type {header.y_type} is not qualified")
    if header.multi and header.version != _VERSION_OLD_LSB and header.z_type not in _X_TYPES and not custom_z:
        raise UnsupportedFormatVariantError(f"Galactic SPC Z unit type {header.z_type} is not qualified")
    if not header.independent_x and header.point_count < 1:
        raise _error("header declares no data points", offset=4)
    if header.version != _VERSION_OLD_LSB:
        assert header.subfile_count is not None
        if header.subfile_count < 1:
            raise _error("header declares no subfiles", offset=24)
        if not header.multi and header.subfile_count != 1:
            raise _error("non-multifile header must declare exactly one subfile", offset=24)
        if header.multi and header.subfile_count < 2:
            raise _error("TMULTI header must declare at least two subfiles", offset=24)
        if header.log_offset and not (header.header_bytes <= header.log_offset < source.size_bytes):
            raise _error("log offset points outside the source", offset=248)
        if (
            header.independent_x
            and header.point_count
            and not (header.header_bytes <= header.point_count <= source.size_bytes)
        ):
            raise _error("XYXY directory offset points outside the source", offset=4)


def _variant(header: _Header) -> str:
    prefix = (
        "old-lsb"
        if header.version == _VERSION_OLD_LSB
        else "new-msb" if header.version == _VERSION_NEW_MSB else "new-lsb"
    )
    cardinality = "multi" if header.multi else "single"
    if header.independent_x:
        layout = "independent-xyxy"
    elif header.explicit_x:
        layout = "common-explicit-x"
    else:
        layout = "common-generated-x"
    return f"{prefix}-{cardinality}-{layout}"


def _subheader(source: BoundedSource, offset: int, *, endian: str, shared_points: int | None) -> _Subheader:
    payload = source.read_at(offset, _SUBHEADER_BYTES, format_id="spc")
    sub_points = struct.unpack_from(f"{endian}I", payload, 16)[0]
    point_count = int(sub_points) if shared_points is None else int(shared_points)
    if point_count < 1:
        raise _error("subfile declares no points", offset=offset + 16)
    first_z, next_z, noise = struct.unpack_from(f"{endian}fff", payload, 4)
    w_level = struct.unpack_from(f"{endian}f", payload, 24)[0]
    for name, value, position in (
        ("first Z", first_z, offset + 4),
        ("next Z", next_z, offset + 8),
        ("noise", noise, offset + 12),
        ("W level", w_level, offset + 24),
    ):
        _finite(float(value), name=name, offset=position)
    return _Subheader(
        offset=offset,
        flags=payload[0],
        exponent=struct.unpack_from("b", payload, 1)[0],
        index=struct.unpack_from(f"{endian}H", payload, 2)[0],
        first_z=float(first_z),
        next_z=float(next_z),
        noise=float(noise),
        point_count=point_count,
        scans=struct.unpack_from(f"{endian}I", payload, 20)[0],
        w_level=float(w_level),
    )


def _effective_exponent(header: _Header, subheader: _Subheader) -> int:
    # Galactic UDF 4.50: an ordinary file uses the SPCHDR exponent.  TMULTI
    # moves exponent authority to each SUBHDR, where zero is a real exponent
    # and must not be treated as an inheritance sentinel.
    return subheader.exponent if header.multi else header.exponent


def _y_bytes(header: _Header, subheader: _Subheader) -> int:
    exponent = _effective_exponent(header, subheader)
    width = 4 if exponent == -128 else header.precision_bytes
    return subheader.point_count * width


def _scan_layout(source: BoundedSource, header: _Header, *, limits: ParserLimits) -> tuple[_Layout, ...]:
    if header.independent_x:
        assert header.subfile_count is not None
        if header.subfile_count > _MAX_INDEPENDENT_ASSETS:
            raise ParserLimitError(
                (
                    f"independent-X asset count {header.subfile_count:,} exceeds the "
                    f"qualified ceiling {_MAX_INDEPENDENT_ASSETS:,}; split the source into "
                    "smaller files before ingestion"
                ),
            )
        if header.point_count:
            return _scan_directory_layout(source, header, limits=limits)

    cursor = header.header_bytes
    global_x_bytes = 0
    if header.explicit_x and not header.independent_x:
        global_x_bytes = header.point_count * 4
        cursor += global_x_bytes

    old_first_subheader: _Subheader | None = None
    if header.version == _VERSION_OLD_LSB:
        # OSPCHDR embeds the first SUBHDR in bytes 224..255.  Subsequent
        # records carry their own 32-byte SUBHDR structures.
        old_first_subheader = _subheader(
            source,
            _OLD_HEADER_BYTES - _SUBHEADER_BYTES,
            endian=header.endian,
            shared_points=header.point_count,
        )
        first_y_bytes = _y_bytes(header, old_first_subheader)
        body_bytes = source.size_bytes - cursor
        if not header.multi:
            if body_bytes != first_y_bytes:
                raise _error(
                    "old non-multifile SPC contains bytes beyond its single declared spectrum",
                    offset=cursor + first_y_bytes,
                )
            subfile_count = 1
        else:
            following_record_bytes = _SUBHEADER_BYTES + first_y_bytes
            if body_bytes < first_y_bytes or (body_bytes - first_y_bytes) % following_record_bytes:
                raise UnsupportedFormatVariantError(
                    "Old-format SPC body does not match the qualified embedded-first-subheader layout"
                )
            subfile_count = 1 + (body_bytes - first_y_bytes) // following_record_bytes
            if subfile_count < 2:
                raise _error("old TMULTI SPC must contain at least two subfiles")
    else:
        assert header.subfile_count is not None
        subfile_count = header.subfile_count

    limits_count = subfile_count + (1 if global_x_bytes else 0)
    source.require_blocks(limits_count, format_id="spc")
    layouts: list[_Layout] = []
    declared_elements = header.point_count if global_x_bytes else 0
    for index in range(subfile_count):
        shared_points = None if header.independent_x else header.point_count
        if index == 0 and old_first_subheader is not None:
            sub = old_first_subheader
        else:
            sub = _subheader(source, cursor, endian=header.endian, shared_points=shared_points)
            cursor += _SUBHEADER_BYTES
        if header.flags & _TSPREC and _effective_exponent(header, sub) == -128:
            raise UnsupportedFormatVariantError("SPC TSPREC contradicts floating-point Y storage")
        x_offset = cursor if header.independent_x else None
        if header.independent_x:
            cursor += sub.point_count * 4
            declared_elements += sub.point_count
        y_offset = cursor
        y_size = _y_bytes(header, sub)
        cursor += y_size
        declared_elements += sub.point_count
        if cursor > source.size_bytes:
            raise _error("subfile data extends beyond the source", offset=y_offset)
        record_size = 0 if index == 0 and old_first_subheader is not None else _SUBHEADER_BYTES
        record_size += (sub.point_count * 4 if header.independent_x else 0) + y_size
        layouts.append(_Layout(sub, x_offset, y_offset, y_size, record_size, 0, None))

    expected_end = header.log_offset or source.size_bytes
    if cursor != expected_end:
        raise _error(
            f"parsed SPC data ends at {cursor}, but the next authenticated boundary is {expected_end}",
            offset=cursor,
        )
    source.require_elements(declared_elements, format_id="spc")
    source.require_decoded_bytes(declared_elements * _DECODED_BYTES_PER_POINT, format_id="spc")
    result = tuple(layouts)
    _validate_layout_semantics(header, result)
    return result


def _scan_directory_layout(
    source: BoundedSource,
    header: _Header,
    *,
    limits: ParserLimits,
) -> tuple[_Layout, ...]:
    """Read an XYXY directory as the authority for movable subfile records."""
    assert header.subfile_count is not None
    offset = header.point_count
    size = header.subfile_count * _DIRECTORY_ENTRY_BYTES
    source.require_blocks(header.subfile_count, format_id="spc")
    if offset + size > (header.log_offset or source.size_bytes):
        raise _error("XYXY directory extends beyond the authenticated data boundary", offset=offset)
    payload = source.read_at(offset, size, format_id="spc")
    layouts: list[_Layout] = []
    occupied: list[tuple[int, int, int]] = []
    declared_elements = 0
    for index in range(header.subfile_count):
        position, declared_size, time_value = struct.unpack_from(
            f"{header.endian}IIf", payload, index * _DIRECTORY_ENTRY_BYTES
        )
        if not math.isfinite(time_value):
            raise _error("XYXY directory contains a non-finite time value", offset=offset + 12 * index + 8)
        if position < header.header_bytes or position + declared_size > offset:
            raise _error("XYXY directory points outside the subfile-data area", offset=offset + 12 * index)
        sub = _subheader(source, position, endian=header.endian, shared_points=None)
        if header.flags & _TSPREC and _effective_exponent(header, sub) == -128:
            raise UnsupportedFormatVariantError("SPC TSPREC contradicts floating-point Y storage")
        y_size = _y_bytes(header, sub)
        actual_size = _SUBHEADER_BYTES + (sub.point_count * 4) + y_size
        if not actual_size <= declared_size <= actual_size + _SUBHEADER_BYTES:
            raise _error("XYXY directory size contradicts the subfile header", offset=offset + 12 * index + 4)
        occupied.append((position, position + actual_size, index))
        x_offset = position + _SUBHEADER_BYTES
        layouts.append(
            _Layout(
                sub,
                x_offset,
                x_offset + sub.point_count * 4,
                y_size,
                int(declared_size),
                int(declared_size - actual_size),
                float(time_value),
            )
        )
        declared_elements += sub.point_count * 2

    # Directory order is semantic subfile order, not storage order.  Sort a
    # compact extent projection once so overlap validation is O(n log n)
    # rather than quadratic on received files.
    occupied.sort(key=lambda item: (item[0], item[1]))
    for previous, current in zip(occupied, occupied[1:], strict=False):
        if current[0] < previous[1]:
            directory_index = current[2]
            raise _error(
                "XYXY directory contains overlapping subfile records",
                offset=offset + _DIRECTORY_ENTRY_BYTES * directory_index,
            )

    source.require_elements(declared_elements, format_id="spc")
    source.require_decoded_bytes(declared_elements * _DECODED_BYTES_PER_POINT, format_id="spc")
    expected_directory_end = header.log_offset or source.size_bytes
    if offset + size != expected_directory_end:
        raise _error("XYXY directory does not end at the next authenticated boundary", offset=offset + size)
    result = tuple(layouts)
    _validate_layout_semantics(header, result)
    return result


def _validate_layout_semantics(header: _Header, layouts: tuple[_Layout, ...]) -> None:
    indices = [layout.subheader.index for layout in layouts]
    if indices != list(range(len(layouts))):
        raise _error("SPC subfile indices are not the qualified zero-based sequence")
    storage_kinds = {_effective_exponent(header, layout.subheader) == -128 for layout in layouts}
    if header.flags & _TSPREC and True in storage_kinds:
        raise UnsupportedFormatVariantError("SPC TSPREC contradicts floating-point Y storage")


def _decode_x(source: BoundedSource, offset: int, count: int, *, endian: str) -> np.ndarray:
    payload = source.read_at(offset, count * 4, format_id="spc")
    values = np.frombuffer(payload, dtype=f"{endian}f4").astype(np.float64)
    if not np.all(np.isfinite(values)):
        raise _error("decoded X axis contains non-finite values", offset=offset)
    return values


def _decode_y(source: BoundedSource, header: _Header, layout: _Layout) -> np.ndarray:
    payload = source.read_at(layout.y_offset, layout.y_bytes, format_id="spc")
    exponent = _effective_exponent(header, layout.subheader)
    if exponent == -128:
        values = np.frombuffer(payload, dtype=f"{header.endian}f4").astype(np.float64)
    elif header.flags & _TSPREC:
        integers = np.frombuffer(payload, dtype=f"{header.endian}i2").astype(np.float64)
        values = np.ldexp(integers, exponent - 16)
    elif header.version == _VERSION_OLD_LSB:
        words = np.frombuffer(payload, dtype=np.uint8).reshape(-1, 4)
        reordered = words[:, [2, 3, 0, 1]].copy().reshape(-1)
        integers = np.frombuffer(reordered.tobytes(), dtype="<i4").astype(np.float64)
        values = np.ldexp(integers, exponent - 32)
    else:
        integers = np.frombuffer(payload, dtype=f"{header.endian}i4").astype(np.float64)
        values = np.ldexp(integers, exponent - 32)
    if not np.all(np.isfinite(values)):
        raise _error("decoded Y data contains non-finite values", offset=layout.y_offset)
    return values


def _generated_x(header: _Header, count: int) -> np.ndarray:
    values = np.linspace(header.first_x, header.last_x, count, dtype=np.float64)
    if not np.all(np.isfinite(values)):
        raise _error("generated X axis contains non-finite values", offset=8)
    return values


def _custom_label(header: _Header, index: int) -> str | None:
    if not header.flags & _TALABS:
        return None
    value = header.axis_labels[index].strip()
    return value or None


def _feature_axis(header: _Header, values: np.ndarray) -> FeatureAxis:
    title, units, axis_class = _X_TYPES.get(header.x_type, (f"SPC X type {header.x_type}", None, FeatureAxis))
    custom = _custom_label(header, 0)
    if custom:
        # TALABS replaces, rather than decorates, the numeric type code.  The
        # label carries no separate unit grammar, so stale fxtype units/class
        # must not acquire scientific meaning.
        return FeatureAxis(values=values, title=custom, units=None)
    return axis_class(values=values, title=title, units=units)


def _z_coordinates(layouts: tuple[_Layout, ...], header: _Header) -> tuple[float, ...]:
    if header.flags & _TORDRD:
        return tuple(float(layout.subheader.first_z) for layout in layouts)
    first = layouts[0].subheader.first_z
    increment = header.z_increment
    if increment in (None, 0.0):
        increment = layouts[0].subheader.next_z - first
    return tuple(float(first + increment * position) for position in range(len(layouts)))


def _sample_table(
    layouts: tuple[_Layout, ...],
    header: _Header,
    *,
    z_values: tuple[float, ...] | None = None,
) -> dict[str, list[Any]]:
    resolved_z = z_values if z_values is not None else _z_coordinates(layouts, header)
    if len(resolved_z) != len(layouts):
        raise AssertionError("SPC Z-coordinate projection does not match layout cardinality")
    scans: list[int] = []
    w_values: list[float | None] = []
    for layout in layouts:
        sub = layout.subheader
        scans.append(int(sub.scans or header.scans or 0))
        w_values.append(float(sub.w_level) if header.w_planes else None)
    custom_z = _custom_label(header, 2)
    z_type = header.z_type if header.z_type is not None else -1
    z_title, z_units, _ = _X_TYPES.get(z_type, ("SPC Z", None, FeatureAxis))
    return {
        "spc_subfile_index": [item.subheader.index for item in layouts],
        "spc_z": list(resolved_z),
        "spc_z_label": [custom_z or z_title] * len(layouts),
        "spc_z_units": [None if custom_z else z_units] * len(layouts),
        "spc_directory_time": [item.directory_time for item in layouts],
        "spc_scans": scans,
        "spc_w": w_values,
    }


def _dataset(
    *,
    source: BoundedSource,
    header: _Header,
    x: np.ndarray,
    y: np.ndarray,
    layouts: tuple[_Layout, ...],
    title_suffix: str | None = None,
    z_values: tuple[float, ...] | None = None,
) -> SherpaDataset:
    quantity, value_units = _Y_TYPES.get(header.y_type, (f"SPC Y type {header.y_type}", None))
    custom_y = _custom_label(header, 1)
    if custom_y:
        value_units = None
    sample_name = header.comment or source.path.stem
    labels = [sample_name] if len(layouts) == 1 else [f"{sample_name} [{item.subheader.index}]" for item in layouts]
    sample_axis = SampleAxis(
        labels=labels,
        title="Sample",
        sample_table=_sample_table(layouts, header, z_values=z_values),
    )
    feature_axis = _feature_axis(header, x)
    title = f"{sample_name}: {custom_y or quantity}"
    if title_suffix:
        title = f"{title} ({title_suffix})"
    technique = _TECHNIQUES.get(header.experiment or -1)
    return SherpaDataset(
        X=np.asarray(y, dtype=np.float64),
        feature_axis=feature_axis,
        sample_axis=sample_axis,
        domain=DomainContext(
            technique=technique,
            expected_units=feature_axis.units,
            data_quantity=custom_y or quantity,
            instrument=header.source_instrument or None,
        ),
        title=title,
        units=value_units,
        extra={
            "source_file": source.path.name,
            "spc.version": header.version,
            "spc.flags": header.flags,
            "spc.method_file": header.method_file,
        },
        data_role=derive_data_role(feature_axis),
    )


def _log_block(source: BoundedSource, header: _Header) -> dict[str, Any] | None:
    if not header.log_offset:
        return None
    payload = source.read_at(header.log_offset, _LOG_HEADER_BYTES, format_id="spc")
    size, memory_size, text_offset, binary_size, disk_size = struct.unpack_from(f"{header.endian}IIIII", payload)
    if size < _LOG_HEADER_BYTES or header.log_offset + size != source.size_bytes:
        raise _error("log block size does not terminate at the source boundary", offset=header.log_offset)
    if not (_LOG_HEADER_BYTES <= text_offset <= size):
        raise _error("log text offset lies outside the log block", offset=header.log_offset + 8)
    if _LOG_HEADER_BYTES + binary_size + disk_size > text_offset:
        raise _error("log binary/disk areas overlap the text section", offset=header.log_offset + 12)
    source.require_metadata_bytes(size, format_id="spc")
    text_payload = source.read_at(header.log_offset + text_offset, size - text_offset, format_id="spc")
    text = text_payload.rstrip(b"\x00").decode("latin-1").strip()
    return {
        "size_bytes": int(size),
        "memory_size_bytes": int(memory_size),
        "binary_size_bytes": int(binary_size),
        "disk_size_bytes": int(disk_size),
        "text": text,
    }


class SpcPlugin:
    format_id = "spc"
    display_name = "Galactic / Thermo GRAMS SPC"
    description = "Qualified Galactic/Thermo SPC single and multi-spectrum data"
    extensions = (".spc",)
    parser_id = "spectrasherpa.spc"
    parser_version = "1"

    def probe(self, source: BoundedSource) -> ProbeResult:
        inspected = min(source.size_bytes, _NEW_HEADER_BYTES)
        # SPC has a version byte rather than a collision-resistant magic. Bind
        # that structural byte to the format's sole filename family so ZIP
        # files beginning with ``PK`` (0x50, 0x4B) cannot false-match.
        if source.extension != ".spc" or source.size_bytes < 2:
            return ProbeResult(self.format_id, None, ProbeConfidence.NO_MATCH, bytes_inspected=inspected)
        identity = source.read_at(0, 2, format_id=self.format_id)
        if identity[1] not in {_VERSION_NEW_LSB, _VERSION_NEW_MSB, _VERSION_OLD_LSB}:
            return ProbeResult(self.format_id, None, ProbeConfidence.NO_MATCH, bytes_inspected=inspected)
        if identity[1] == _VERSION_NEW_MSB:
            return ProbeResult(
                self.format_id,
                "new-msb-unqualified",
                ProbeConfidence.EXACT,
                ("Galactic SPC version 0x4C", "big-endian layout is not independently qualified"),
                inspected,
            )
        try:
            header = _header(source)
        except (UnreadableSpectrumError, UnsupportedFormatVariantError):
            return ProbeResult(
                self.format_id,
                "recognized-unreadable",
                ProbeConfidence.EXACT,
                (f"Galactic SPC version 0x{identity[1]:02X}", "header requires fail-closed validation"),
                inspected,
            )
        return ProbeResult(
            self.format_id,
            _variant(header),
            ProbeConfidence.EXACT,
            (f"Galactic SPC version 0x{header.version:02X}", f"flags 0x{header.flags:02X}"),
            inspected,
        )

    def read(
        self,
        source: BoundedSource,
        *,
        limits: ParserLimits,
        parser_options: Mapping[str, str] | None = None,
    ) -> IngestionResult:
        if parser_options:
            raise UnsupportedFormatVariantError("SPC does not admit parser options")
        if source.extension != ".spc":
            raise FormatIdentityError(f"Galactic SPC bytes contradict filename {source.path.name!r}; use .spc")
        if source.read_at(1, 1, format_id="spc")[0] == _VERSION_NEW_MSB:
            raise UnsupportedFormatVariantError(
                "Big-endian Galactic SPC (0x4C) is structurally recognized but lacks an independent conformance fixture"
            )
        header = _header(source)
        layouts = _scan_layout(source, header, limits=limits)
        global_x = None
        if header.explicit_x and not header.independent_x:
            global_x = _decode_x(source, header.header_bytes, header.point_count, endian=header.endian)
        elif not header.independent_x:
            global_x = _generated_x(header, header.point_count)

        assets = []
        if header.independent_x:
            all_z = _z_coordinates(layouts, header)
            for index, layout in enumerate(layouts, 1):
                assert layout.x_offset is not None
                x = _decode_x(source, layout.x_offset, layout.subheader.point_count, endian=header.endian)
                y = _decode_y(source, header, layout).reshape(1, -1)
                asset_id = f"spectrum_{index}"
                dataset = _dataset(
                    source=source,
                    header=header,
                    x=x,
                    y=y,
                    layouts=(layout,),
                    title_suffix=f"subfile {layout.subheader.index}",
                    z_values=(all_z[index - 1],),
                )
                assets.append(
                    dataset_asset(
                        dataset,
                        asset_id=asset_id,
                        raw_metadata={
                            "spc.subfile_index": layout.subheader.index,
                            "spc.z": layout.subheader.first_z,
                            "spc.resolved_z": all_z[index - 1],
                            "spc.directory_time": layout.directory_time,
                            "spc.scans": layout.subheader.scans,
                            "spc.storage_bytes": layout.storage_bytes,
                            "spc.trailing_padding_bytes": layout.trailing_padding_bytes,
                        },
                    )
                )
        else:
            assert global_x is not None
            rows = np.stack([_decode_y(source, header, layout) for layout in layouts], axis=0)
            dataset = _dataset(source=source, header=header, x=global_x, y=rows, layouts=layouts)
            assets.append(
                dataset_asset(
                    dataset,
                    asset_id="spectra",
                    raw_metadata={"spc.subfile_count": len(layouts)},
                )
            )

        log = _log_block(source, header)
        raw_metadata = {
            "spc.version": header.version,
            "spc.flags": header.flags,
            "spc.experiment": header.experiment,
            "spc.x_type": header.x_type,
            "spc.y_type": header.y_type,
            "spc.z_type": None if _custom_label(header, 2) else header.z_type,
            "spc.z_label": _custom_label(header, 2),
            "spc.resolution": header.resolution,
            "spc.source_instrument": header.source_instrument,
            "spc.comment": header.comment,
            "spc.axis_labels": list(header.axis_labels),
            "spc.method_file": header.method_file,
            "spc.log": log,
        }
        return ingestion_result(
            source=source,
            format_id=self.format_id,
            variant=_variant(header),
            parser_id=self.parser_id,
            parser_version=self.parser_version,
            assets=tuple(assets),
            raw_metadata=raw_metadata,
        )


PLUGIN = SpcPlugin()
