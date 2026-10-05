"""Bounded native reader for qualified Thermo OMNIC SPA, SPG, and SRS files.

The block-table interpretation follows the public reverse-engineering work in
``spectrochempy-omnic`` 0.2.1 (commit
``2eb6b7d3964451d35eeb0c185cb99a0cc147c7cd``, CeCILL-B).  SpectraSherpa
implements a smaller read-only grammar with checked ranges and allocations:

* SPA: one spectral-header block paired with one float32 data block;
* SPG: compatible header/data/title triples projected as one sample matrix;
* SRS: the independently qualified rapid-scan, high-speed, GC/TGA, and
  extended-directory Kinetics series layouts.

Unknown units, interferogram selection, container variants, and ambiguous
block cardinalities fail closed.  Axis order is the order declared by the
source.  The Kinetics row payload is explicitly reversed from its qualified
ascending storage order onto the descending axis declared by its header; no
other layout is silently reordered or flattened.
"""

from __future__ import annotations

import hashlib
import math
import re
import struct
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import numpy as np

from spectra_sherpa.app.lib.axes import FeatureAxis, SampleAxis, SpectralAxis
from spectra_sherpa.app.lib.sherpa_dataset import DomainContext, SherpaDataset
from spectra_sherpa.ingestion_errors import (
    FormatIdentityError,
    UnreadableSpectrumError,
    UnsupportedFormatVariantError,
)
from spectra_sherpa.io.base import BoundedSource
from spectra_sherpa.io.formats._helpers import dataset_asset, derive_data_role, ingestion_result
from spectra_sherpa.io.types import IngestionResult, ParserLimits, ProbeConfidence, ProbeResult

_DATA_MAGIC = b"Spectral Data File"
_SERIES_MAGIC = b"Spectral Exte File"
_DIRECTORY_OFFSET = 304
_DIRECTORY_ENTRY_BYTES = 16
_KINETICS_DIRECTORY_ENTRY_BYTES = 22
_HEADER_MIN_BYTES = 140
_SERIES_HEADER_MIN_BYTES = 1030
_KINETICS_METADATA_KEY = 325
_KINETICS_TEXT_KEY = 27
_KINETICS_SERIES_DESCRIPTOR_KEY = 146
_KINETICS_ROW_BLOCK_KEY = 301
_KINETICS_ROW_PREAMBLE_BYTES = 212
_KINETICS_METADATA_FIRST_TIME_OFFSET = 66
_KINETICS_METADATA_SAMPLE_COUNT_OFFSET = 90
_KINETICS_METADATA_MIN_BYTES = 94
_KINETICS_TEXT_MARKER = b"Data collection type:\tKinetics"
_KINETICS_METADATA_BLOCK_MAX_BYTES = 4096
_KINETICS_LABEL = re.compile(r"^Linked spectrum at ([0-9]+(?:\.[0-9]+)?) min\.$")
_BLANK_RANGE = re.compile(
    r"Blank on[^\r\n]*[\r\n]+\s*From\s+([-+]?[0-9]+(?:\.[0-9]+)?)\s+to\s+([-+]?[0-9]+(?:\.[0-9]+)?)",
    re.IGNORECASE,
)
_DECODED_BYTES_PER_POINT = 32
_MAX_SERIES_MARKERS = 8
_OMNIC_EPOCH = datetime(1899, 12, 31, tzinfo=UTC)

_RAPID_MARKER = b"\x02\x00\x00\x00\x18\x00\x00\x00\x00\x00\x48\x43\x00\x50\x43\x47"
_HIGH_SPEED_MARKER = b"\x02\x00\x00\x00\x18\x00\x00\x00\x00\x00\x48\x43\x00\xc8\xaf\x47"
_THERMAL_MARKER = b"\x02\x00\x00\x00\x18\x00\x00\x00\x00\x00"

_X_TYPES: dict[int, tuple[str, str | None, bool]] = {
    1: ("Wavenumber", "cm-1", True),
    2: ("Data point", None, False),
    3: ("Wavelength", "nm", True),
    4: ("Wavelength", "um", True),
    32: ("Raman shift", "cm-1", True),
}
_Y_TYPES: dict[int, tuple[str, str | None]] = {
    11: ("Reflectance", "percent"),
    12: ("Log reflectance", None),
    16: ("Transmittance", "percent"),
    17: ("Absorbance", "absorbance"),
    20: ("Kubelka-Munk", None),
    21: ("Reflectance", None),
    22: ("Detector signal", "V"),
    # OMNIC 9.16.233 on a Nicolet Apex displays the retained code-23 sources as
    # Transmittance. Their history separately records ``Final format: Single
    # Beam``. Preserve those as distinct authorities: this is the qualified UI
    # quantity label, while units remain unknown so ratio conversion refuses.
    23: ("Transmittance", None),
    26: ("Photoacoustic intensity", None),
    31: ("Raman intensity", None),
}


@dataclass(frozen=True, slots=True)
class _Entry:
    key: int
    offset: int
    size_bytes: int
    table_offset: int
    multiplicity: int = 1
    reserved: int = 0


@dataclass(frozen=True, slots=True)
class _Header:
    point_count: int
    x_code: int
    y_code: int
    first_x: float
    last_x: float
    scan_points: int
    zpd: int
    scans: int
    background_scans: int
    collection_length_raw: int
    reference_frequency: float
    optical_velocity: float | None


@dataclass(frozen=True, slots=True)
class _SeriesLayout:
    variant: str
    header_entry: _Entry
    row_offset: int
    sample_count: int
    first_time_minutes: float
    last_time_minutes: float
    interval_minutes: float
    reverse_features: bool = False
    title: str | None = None


def _error(detail: str, *, offset: int | None = None) -> UnreadableSpectrumError:
    return UnreadableSpectrumError(format_id="omnic", detail=detail, offset=offset)


def _text(payload: bytes) -> str:
    return payload.split(b"\x00", 1)[0].decode("latin-1").strip()


def _validate_embedded_spa_envelope(payload: bytes) -> None:
    """Require a complete conventional SPA envelope for a key-78 payload."""

    if len(payload) < _DIRECTORY_OFFSET or not payload.startswith(_DATA_MAGIC):
        raise UnsupportedFormatVariantError("OMNIC key 78 block is not a complete embedded spectral source")
    line_count = struct.unpack_from("<H", payload, 294)[0]
    if line_count < 1:
        raise UnsupportedFormatVariantError("OMNIC key 78 embedded source contains no directory entries")
    table_end = _DIRECTORY_OFFSET + int(line_count) * _DIRECTORY_ENTRY_BYTES
    if table_end > len(payload):
        raise UnsupportedFormatVariantError("OMNIC key 78 embedded directory is truncated")
    ranges: list[tuple[int, int]] = []
    for index in range(int(line_count)):
        row = _DIRECTORY_OFFSET + index * _DIRECTORY_ENTRY_BYTES
        offset = struct.unpack_from("<I", payload, row + 2)[0]
        size_bytes = struct.unpack_from("<I", payload, row + 6)[0]
        end = int(offset) + int(size_bytes)
        if offset < table_end or size_bytes < 1 or end < offset or end > len(payload):
            raise UnsupportedFormatVariantError("OMNIC key 78 embedded directory points outside its payload")
        ranges.append((int(offset), end))
    ranges.sort()
    if any(previous_end > current_start for (_, previous_end), (current_start, _) in zip(ranges, ranges[1:])):
        raise UnsupportedFormatVariantError("OMNIC key 78 embedded directory blocks overlap")


def _directory(source: BoundedSource, *, limits: ParserLimits) -> tuple[_Entry, ...]:
    if source.size_bytes < _DIRECTORY_OFFSET:
        raise _error("source is shorter than the OMNIC directory header", offset=source.size_bytes)
    line_count = struct.unpack("<H", source.read_at(294, 2, format_id="omnic"))[0]
    if line_count < 1:
        raise _error("OMNIC directory contains no entries", offset=294)
    source.require_blocks(line_count, format_id="omnic")
    table_size = line_count * _DIRECTORY_ENTRY_BYTES
    table_end = _DIRECTORY_OFFSET + table_size
    payload = source.read_at(_DIRECTORY_OFFSET, table_size, format_id="omnic")
    entries: list[_Entry] = []
    for index in range(line_count):
        row = index * _DIRECTORY_ENTRY_BYTES
        key = payload[row]
        offset = struct.unpack_from("<I", payload, row + 2)[0]
        size_bytes = struct.unpack_from("<I", payload, row + 6)[0]
        # The retained OMNIC 5.x addition-result family stores a complete linked
        # SPA at EOF. Its key-78 field is one greater than the payload byte
        # count. Arithmetic alone is not an authority: admit that encoding only
        # after the entire nested SPA envelope and directory validate.
        if key == 78 and offset >= table_end and offset < source.size_bytes:
            linked_size = source.size_bytes - offset
            if size_bytes == linked_size + 1:
                linked_payload = source.read_at(offset, linked_size, format_id="omnic")
                _validate_embedded_spa_envelope(linked_payload)
                size_bytes = linked_size
        if offset < table_end or size_bytes < 1 or offset + size_bytes > source.size_bytes:
            raise _error(
                "directory entry points into the directory or outside the source",
                offset=_DIRECTORY_OFFSET + row,
            )
        entries.append(_Entry(int(key), int(offset), int(size_bytes), _DIRECTORY_OFFSET + row))
    ordered = sorted(entries, key=lambda item: (item.offset, item.size_bytes))
    for previous, current in zip(ordered, ordered[1:]):
        if previous.offset + previous.size_bytes > current.offset:
            raise _error("directory blocks overlap", offset=current.table_offset)
    return tuple(entries)


def _kinetics_directory(source: BoundedSource, *, limits: ParserLimits) -> tuple[_Entry, ...]:
    """Read the qualified 64-bit-offset Kinetics directory.

    Legacy SPA/SPG blocks use 16-byte entries with 32-bit offsets.  The
    independently observed Kinetics SRS container uses a different, closed
    22-byte grammar: key/u64-offset/u32-size/u32-multiplicity/u32-reserved.
    Keeping the grammars separate prevents a malformed legacy table from
    being reinterpreted as a series directory.
    """

    if source.size_bytes < _DIRECTORY_OFFSET:
        raise _error("source is shorter than the OMNIC Kinetics directory header", offset=source.size_bytes)
    line_count = struct.unpack("<H", source.read_at(294, 2, format_id="omnic"))[0]
    if line_count < 1:
        raise _error("OMNIC Kinetics directory contains no entries", offset=294)
    source.require_blocks(line_count, format_id="omnic")
    table_size = line_count * _KINETICS_DIRECTORY_ENTRY_BYTES
    source.require_metadata_bytes(table_size, format_id="omnic")
    table_end = _DIRECTORY_OFFSET + table_size
    if table_end > source.size_bytes:
        raise _error("OMNIC Kinetics directory extends beyond the source", offset=_DIRECTORY_OFFSET)
    payload = source.read_at(_DIRECTORY_OFFSET, table_size, format_id="omnic")
    entries: list[_Entry] = []
    for index in range(line_count):
        row = index * _KINETICS_DIRECTORY_ENTRY_BYTES
        key = struct.unpack_from("<H", payload, row)[0]
        offset = struct.unpack_from("<Q", payload, row + 2)[0]
        size_bytes = struct.unpack_from("<I", payload, row + 10)[0]
        multiplicity = struct.unpack_from("<I", payload, row + 14)[0]
        reserved = struct.unpack_from("<I", payload, row + 18)[0]
        end = int(offset) + int(size_bytes)
        if offset < table_end or size_bytes < 1 or end < offset or end > source.size_bytes:
            raise _error(
                "Kinetics directory entry points into the directory or outside the source",
                offset=_DIRECTORY_OFFSET + row,
            )
        entries.append(
            _Entry(
                int(key),
                int(offset),
                int(size_bytes),
                _DIRECTORY_OFFSET + row,
                int(multiplicity),
                int(reserved),
            )
        )
    ordered = sorted(entries, key=lambda item: (item.offset, item.size_bytes))
    for previous, current in zip(ordered, ordered[1:]):
        if previous.offset + previous.size_bytes > current.offset:
            raise _error("Kinetics directory blocks overlap", offset=current.table_offset)
    return tuple(entries)


def _kinetics_entry(
    entries: tuple[_Entry, ...],
    key: int,
    *,
    multiplicity: int,
    exclusive_key: bool = True,
) -> _Entry:
    matched = [entry for entry in entries if entry.key == key and entry.multiplicity == multiplicity]
    same_key = [entry for entry in entries if entry.key == key]
    if len(matched) != 1 or (exclusive_key and len(same_key) != 1):
        raise UnsupportedFormatVariantError(
            f"Kinetics SRS requires exactly one key {key} block with multiplicity {multiplicity}"
        )
    entry = matched[0]
    if entry.reserved != 0:
        raise UnsupportedFormatVariantError(f"Kinetics SRS key {key} block has an unqualified reserved value")
    return entry


def _has_kinetics_directory_signature(source: BoundedSource) -> bool:
    minimum = _DIRECTORY_OFFSET + _KINETICS_DIRECTORY_ENTRY_BYTES
    if source.size_bytes < minimum:
        return False
    line_count = struct.unpack("<H", source.read_at(294, 2, format_id="omnic"))[0]
    if line_count < 1:
        return False
    first = source.read_at(
        _DIRECTORY_OFFSET,
        _KINETICS_DIRECTORY_ENTRY_BYTES,
        format_id="omnic",
    )
    key, offset, size_bytes, multiplicity, reserved = struct.unpack("<HQIII", first)
    table_end = _DIRECTORY_OFFSET + int(line_count) * _KINETICS_DIRECTORY_ENTRY_BYTES
    return (
        key == 2
        and size_bytes == _HEADER_MIN_BYTES
        and multiplicity == 1
        and reserved == 0
        and table_end <= offset <= source.size_bytes - size_bytes
    )


def _header(source: BoundedSource, entry: _Entry, *, series: bool = False) -> _Header:
    required = _SERIES_HEADER_MIN_BYTES if series else _HEADER_MIN_BYTES
    if entry.size_bytes < required:
        raise _error(f"spectral header is shorter than {required} bytes", offset=entry.offset)
    payload = source.read_at(entry.offset, required, format_id="omnic")
    point_count = struct.unpack_from("<I", payload, 4)[0]
    x_code = payload[8]
    y_code = payload[12]
    first_x, last_x = struct.unpack_from("<ff", payload, 16)
    scan_points, zpd, scans = struct.unpack_from("<III", payload, 28)
    background_scans = struct.unpack_from("<I", payload, 52)[0]
    collection_length_raw = struct.unpack_from("<I", payload, 68)[0]
    reference_frequency = struct.unpack_from("<f", payload, 80)[0]
    # Public readers historically read an optical-velocity value at +188 even
    # when the authenticated header block is only 140 bytes.  That crosses into
    # a different directory-owned block, so this bounded grammar deliberately
    # does not claim the value unless a future qualified header variant owns it.
    optical_velocity = None
    if point_count < 1:
        raise _error("spectral header declares zero points", offset=entry.offset + 4)
    if x_code not in _X_TYPES:
        raise UnsupportedFormatVariantError(f"OMNIC X-axis code {x_code} is not independently qualified")
    if y_code not in _Y_TYPES:
        raise UnsupportedFormatVariantError(f"OMNIC data-unit code {y_code} is not independently qualified")
    if not all(math.isfinite(value) for value in (first_x, last_x, reference_frequency)):
        raise _error("spectral header contains non-finite coordinates or instrument values", offset=entry.offset)
    if point_count > 1 and first_x == last_x:
        raise _error("spectral header declares a degenerate feature axis", offset=entry.offset + 16)
    return _Header(
        int(point_count),
        int(x_code),
        int(y_code),
        float(first_x),
        float(last_x),
        int(scan_points),
        int(zpd),
        int(scans),
        int(background_scans),
        int(collection_length_raw),
        float(reference_frequency),
        optical_velocity,
    )


def _axis(header: _Header) -> FeatureAxis:
    title, units, spectral = _X_TYPES[header.x_code]
    values = np.linspace(header.first_x, header.last_x, header.point_count, dtype=np.float64)
    axis_type = SpectralAxis if spectral else FeatureAxis
    return axis_type(values=values, units=units, title=title)


def _decode_values(
    source: BoundedSource,
    entry: _Entry,
    header: _Header,
    *,
    allow_nan: bool = False,
) -> np.ndarray:
    expected = header.point_count * 4
    if entry.size_bytes != expected:
        raise _error(
            f"data block has {entry.size_bytes} bytes but its header requires exactly {expected}",
            offset=entry.offset,
        )
    values = np.frombuffer(source.read_at(entry.offset, expected, format_id="omnic"), dtype="<f4").astype(np.float64)
    if np.any(np.isinf(values)):
        raise _error("decoded spectrum contains infinite values", offset=entry.offset)
    if not allow_nan and np.any(np.isnan(values)):
        raise _error("decoded spectrum contains non-finite values", offset=entry.offset)
    return values


def _qualified_spa_blank_range(
    header: _Header,
    data: np.ndarray,
    text_metadata: Mapping[str, Any],
) -> tuple[float, float] | None:
    missing = np.isnan(data[0])
    if not np.any(missing):
        return None
    if header.y_code != 23 or np.all(missing):
        raise _error("SPA missing values are not part of the qualified code-23 blank-range profile")
    histories = text_metadata.get("processing_history")
    if not isinstance(histories, list) or any(not isinstance(value, str) for value in histories):
        raise _error("SPA missing values require one explicit OMNIC processing-history blank range")
    joined = "\n".join(histories)
    matches = _BLANK_RANGE.findall(joined)
    if len(matches) != 1 or re.search(r"Final\s+format:\s*Single\s+Beam", joined, re.IGNORECASE) is None:
        raise _error("SPA missing values require one explicit Single Beam processing blank range")
    first, last = (float(value) for value in matches[0])
    if not math.isfinite(first) or not math.isfinite(last) or first == last:
        raise _error("SPA processing history declares an invalid blank range")
    coordinates = np.asarray(_axis(header).values, dtype=np.float64)
    lower, upper = sorted((first, last))
    expected_missing = (coordinates >= lower) & (coordinates <= upper)
    if not np.array_equal(missing, expected_missing):
        raise _error("SPA missing values do not exactly match its declared processing-history blank range")
    return first, last


def _spa_text_metadata(source: BoundedSource, entries: tuple[_Entry, ...]) -> dict[str, Any]:
    """Project bounded human-readable SPA metadata without exposing spectra."""

    comments = [
        text
        for entry in entries
        if entry.key == 4 and (text := _text(source.read_at(entry.offset, entry.size_bytes, format_id="omnic")))
    ]
    histories = [
        text
        for entry in entries
        if entry.key == 27 and (text := _text(source.read_at(entry.offset, entry.size_bytes, format_id="omnic")))
    ]
    experiment_information: list[dict[str, str]] = []
    for entry in entries:
        if entry.key != 130:
            continue
        payload = source.read_at(entry.offset, entry.size_bytes, format_id="omnic")
        projected: dict[str, str] = {}
        for name, offset, length in (
            ("experiment_file", 10, 80),
            ("experiment_title", 90, 164),
            ("custom_text", 254, 159),
            ("accessory", 413, 160),
        ):
            if offset < len(payload) and (value := _text(payload[offset : offset + length])):
                projected[name] = value
        if projected:
            experiment_information.append(projected)

    linked_sources: list[dict[str, Any]] = []
    for entry in entries:
        if entry.key != 78:
            continue
        payload = source.read_at(entry.offset, entry.size_bytes, format_id="omnic")
        if not payload.startswith(_DATA_MAGIC):
            raise UnsupportedFormatVariantError("OMNIC key 78 block is not an embedded spectral source")
        linked_sources.append(
            {
                "title": _text(payload[30:286]),
                "size_bytes": entry.size_bytes,
                "sha256": hashlib.sha256(payload).hexdigest(),
            }
        )

    metadata: dict[str, Any] = {}
    if comments:
        metadata["comments"] = comments
    if histories:
        metadata["processing_history"] = histories
    if experiment_information:
        metadata["experiment_information"] = experiment_information
    if linked_sources:
        metadata["embedded_linked_sources"] = linked_sources
    return metadata


def _timestamp(raw_seconds: int) -> tuple[float, str]:
    try:
        value = _OMNIC_EPOCH + timedelta(seconds=int(raw_seconds))
    except OverflowError as exc:
        raise _error("acquisition timestamp lies outside the supported datetime range") from exc
    return value.timestamp(), value.isoformat()


def _dataset(
    *,
    source: BoundedSource,
    header: _Header,
    data: np.ndarray,
    labels: list[str],
    sample_values: np.ndarray | None = None,
    sample_units: str | None = None,
    sample_title: str = "Sample",
    sample_table: dict[str, list[Any]] | None = None,
    title: str,
) -> SherpaDataset:
    quantity, value_units = _Y_TYPES[header.y_code]
    feature_axis = _axis(header)
    technique = "Raman" if header.x_code == 32 or header.y_code == 31 else "IR" if header.x_code == 1 else None
    return SherpaDataset(
        X=np.asarray(data, dtype=np.float64),
        feature_axis=feature_axis,
        sample_axis=SampleAxis(
            values=sample_values,
            labels=labels,
            units=sample_units,
            title=sample_title,
            sample_table=sample_table,
        ),
        domain=DomainContext(
            technique=technique,
            expected_units=feature_axis.units,
            data_quantity=quantity,
            instrument="Thermo Nicolet OMNIC",
        ),
        title=title,
        units=value_units,
        extra={"source_file": source.path.name, "omnic.variant": source.extension.removeprefix(".")},
        data_role=derive_data_role(feature_axis),
    )


def _header_metadata(header: _Header) -> dict[str, Any]:
    return {
        "point_count": header.point_count,
        "x_code": header.x_code,
        "y_code": header.y_code,
        "first_x": header.first_x,
        "last_x": header.last_x,
        "scan_points": header.scan_points,
        "zero_path_difference_index": header.zpd,
        "scan_count": header.scans,
        "background_scan_count": header.background_scans,
        "collection_length_raw": header.collection_length_raw,
        "reference_frequency_cm-1": header.reference_frequency,
        "optical_velocity": header.optical_velocity,
    }


def _read_spa(source: BoundedSource, *, limits: ParserLimits) -> IngestionResult:
    entries = _directory(source, limits=limits)
    headers = tuple(item for item in entries if item.key == 2)
    values = tuple(item for item in entries if item.key == 3)
    if len(headers) != 1 or len(values) != 1:
        raise UnsupportedFormatVariantError("Qualified SPA requires exactly one spectral-header/data pair")
    header = _header(source, headers[0])
    source.require_elements(header.point_count, format_id="omnic")
    source.require_decoded_bytes(header.point_count * _DECODED_BYTES_PER_POINT, format_id="omnic")
    text_metadata = _spa_text_metadata(source, entries)
    data = _decode_values(source, values[0], header, allow_nan=True).reshape(1, -1)
    blank_range = _qualified_spa_blank_range(header, data, text_metadata)
    original_name = _text(source.read_at(30, 256, format_id="omnic")) or source.path.stem
    raw_timestamp = struct.unpack("<I", source.read_at(296, 4, format_id="omnic"))[0]
    timestamp, acquired_at = _timestamp(raw_timestamp)
    dataset = _dataset(
        source=source,
        header=header,
        data=data,
        labels=[original_name],
        sample_values=np.asarray([timestamp], dtype=np.float64),
        sample_units="s",
        sample_title="Acquisition timestamp (UTC)",
        sample_table={"acquired_at": [acquired_at]},
        title=f"{original_name}: {_Y_TYPES[header.y_code][0]}",
    )
    metadata = {
        "container_name": original_name,
        "directory_entry_count": len(entries),
        "acquired_at": acquired_at,
        "header": _header_metadata(header),
        **text_metadata,
    }
    metadata["missing_value_count"] = int(np.count_nonzero(np.isnan(data)))
    if header.y_code == 23:
        metadata["quantity_interpretation"] = {
            "displayed_quantity": "Transmittance",
            "display_authority": "qualified_nicolet_apex_omnic_9.16.233_observation",
            "ratio_units": "unresolved",
            "processing_final_format": (
                "Single Beam" if "Single Beam" in "\n".join(text_metadata.get("processing_history", [])) else None
            ),
        }
        dataset.set_extra("omnic.quantity_interpretation", metadata["quantity_interpretation"])
    if blank_range is not None:
        metadata["blanked_range_cm-1"] = {"from": blank_range[0], "to": blank_range[1]}
        metadata["missing_value_policy"] = "explicit_processing_blank_preserved_no_imputation"
        dataset.set_extra("omnic.blanked_range_cm-1", metadata["blanked_range_cm-1"])
    dataset.meta["omnic.acquisition"] = {
        "acquired_at": acquired_at,
        **metadata["header"],
    }
    if "processing_history" in metadata:
        dataset.set_extra("omnic.processing_history", metadata["processing_history"])
    if "comments" in metadata:
        dataset.set_extra("omnic.comments", metadata["comments"])
    if "experiment_information" in metadata:
        dataset.set_extra("omnic.experiment_information", metadata["experiment_information"])
    return ingestion_result(
        source=source,
        format_id="omnic",
        variant="spa-single-spectrum",
        parser_id="spectrasherpa.omnic",
        parser_version="1",
        assets=(dataset_asset(dataset, asset_id="spectrum", raw_metadata=metadata),),
        raw_metadata=metadata,
    )


def _spg_records(entries: tuple[_Entry, ...]) -> tuple[tuple[_Entry, _Entry, _Entry], ...]:
    records: list[tuple[_Entry, _Entry, _Entry]] = []
    current_header: _Entry | None = None
    current_data: _Entry | None = None
    current_title: _Entry | None = None
    for entry in entries:
        if entry.key == 2:
            if current_header is not None:
                if current_data is None or current_title is None:
                    raise _error("SPG record is missing its data or title block", offset=current_header.table_offset)
                records.append((current_header, current_data, current_title))
            current_header = entry
            current_data = None
            current_title = None
        elif entry.key == 3:
            if current_header is None:
                raise _error("SPG data block appears before any spectral header", offset=entry.table_offset)
            if current_data is not None:
                raise _error("SPG record contains more than one data block", offset=entry.table_offset)
            current_data = entry
        elif entry.key == 107:
            if current_header is None:
                raise _error("SPG title block appears before any spectral header", offset=entry.table_offset)
            if current_title is not None:
                raise _error("SPG record contains more than one title block", offset=entry.table_offset)
            current_title = entry
    if current_header is not None:
        if current_data is None or current_title is None:
            raise _error("SPG record is missing its data or title block", offset=current_header.table_offset)
        records.append((current_header, current_data, current_title))
    if not records:
        raise UnsupportedFormatVariantError("Qualified SPG requires at least one header/data/title record")
    return tuple(records)


def _read_spg(source: BoundedSource, *, limits: ParserLimits) -> IngestionResult:
    entries = _directory(source, limits=limits)
    records = _spg_records(entries)
    count = len(records)
    headers = tuple(_header(source, record[0]) for record in records)
    authority = headers[0]
    compatibility = (authority.point_count, authority.x_code, authority.y_code, authority.first_x, authority.last_x)
    if any(
        (item.point_count, item.x_code, item.y_code, item.first_x, item.last_x) != compatibility for item in headers[1:]
    ):
        raise _error("SPG members do not share one exact feature axis and data quantity")
    element_count = count * authority.point_count
    source.require_elements(element_count, format_id="omnic")
    source.require_decoded_bytes(element_count * _DECODED_BYTES_PER_POINT, format_id="omnic")
    data = np.empty((count, authority.point_count), dtype=np.float64)
    labels: list[str] = []
    timestamps: list[float] = []
    acquired_at: list[str] = []
    for index, ((_header_entry, data_entry, title_entry), item_header) in enumerate(zip(records, headers)):
        data[index] = _decode_values(source, data_entry, item_header)
        if title_entry.size_bytes < 260:
            raise _error("SPG title block is shorter than 260 bytes", offset=title_entry.offset)
        payload = source.read_at(title_entry.offset, 260, format_id="omnic")
        labels.append(_text(payload[:256]) or f"Spectrum {index + 1}")
        raw = struct.unpack_from("<I", payload, 256)[0]
        timestamp, iso = _timestamp(raw)
        timestamps.append(timestamp)
        acquired_at.append(iso)
    # OMNIC SPG directory records are commonly newest-first.  Project the
    # acquisition coordinate in chronological order while retaining the exact
    # source-directory position, so sample order is explicit and reproducible.
    order = np.argsort(np.asarray(timestamps, dtype=np.float64), kind="stable")
    data = data[order]
    labels = [labels[int(index)] for index in order]
    timestamps = [timestamps[int(index)] for index in order]
    acquired_at = [acquired_at[int(index)] for index in order]
    source_directory_indices = [int(index) for index in order]
    container_name = _text(source.read_at(30, 256, format_id="omnic")) or source.path.stem
    dataset = _dataset(
        source=source,
        header=authority,
        data=data,
        labels=labels,
        sample_values=np.asarray(timestamps, dtype=np.float64),
        sample_units="s",
        sample_title="Acquisition timestamp (UTC)",
        sample_table={"acquired_at": acquired_at, "source_directory_index": source_directory_indices},
        title=f"{container_name}: {_Y_TYPES[authority.y_code][0]} group",
    )
    metadata = {
        "container_name": container_name,
        "directory_entry_count": len(entries),
        "spectrum_count": count,
        "header": _header_metadata(authority),
    }
    dataset.meta["omnic.acquisition"] = {
        "acquired_at": acquired_at,
        **metadata["header"],
    }
    return ingestion_result(
        source=source,
        format_id="omnic",
        variant="spg-compatible-spectrum-group",
        parser_id="spectrasherpa.omnic",
        parser_version="1",
        assets=(dataset_asset(dataset, asset_id="spectra", raw_metadata=metadata),),
        raw_metadata=metadata,
    )


def _series_markers(source: BoundedSource) -> dict[bytes, tuple[int, ...]]:
    markers = (_RAPID_MARKER, _HIGH_SPEED_MARKER, _THERMAL_MARKER)
    chunk_size = 1024 * 1024
    overlap = max(map(len, markers)) - 1
    carry = b""
    positions: dict[bytes, list[int]] = {marker: [] for marker in markers}
    offset = 0
    while offset < source.size_bytes:
        length = min(chunk_size, source.size_bytes - offset)
        chunk = source.read_at(offset, length, format_id="omnic")
        combined = carry + chunk
        base = offset - len(carry)
        for marker in markers:
            start = 0
            while True:
                found = combined.find(marker, start)
                if found < 0:
                    break
                absolute = base + found
                marker_positions = positions[marker]
                if not marker_positions or marker_positions[-1] != absolute:
                    marker_positions.append(absolute)
                    if len(marker_positions) > _MAX_SERIES_MARKERS:
                        raise UnsupportedFormatVariantError(
                            "SRS contains more structural markers than the qualified grammar"
                        )
                start = found + 1
        carry = combined[-overlap:] if overlap else b""
        offset += length
    return {marker: tuple(found) for marker, found in positions.items()}


def _legacy_series_layout(source: BoundedSource, variant: str, header_offset: int, row_offset: int) -> _SeriesLayout:
    payload = source.read_at(header_offset, _SERIES_HEADER_MIN_BYTES, format_id="omnic")
    interval_minutes, last_time_minutes, first_time_minutes = struct.unpack_from("<fff", payload, 1002)
    sample_count = struct.unpack_from("<I", payload, 1026)[0]
    title = _text(source.read_at(header_offset + 938, 256, format_id="omnic")).split("\n", 1)[0]
    return _SeriesLayout(
        variant=variant,
        header_entry=_Entry(2, header_offset, source.size_bytes - header_offset, header_offset),
        row_offset=row_offset,
        sample_count=int(sample_count),
        first_time_minutes=float(first_time_minutes),
        last_time_minutes=float(last_time_minutes),
        interval_minutes=float(interval_minutes),
        title=title or None,
    )


def _kinetics_layout(source: BoundedSource, *, limits: ParserLimits) -> _SeriesLayout:
    entries = _kinetics_directory(source, limits=limits)
    header_entry = _kinetics_entry(entries, 2, multiplicity=1)
    descriptor_entry = _kinetics_entry(entries, _KINETICS_SERIES_DESCRIPTOR_KEY, multiplicity=1)
    metadata_entry = _kinetics_entry(entries, _KINETICS_METADATA_KEY, multiplicity=1)
    text_entry = _kinetics_entry(entries, _KINETICS_TEXT_KEY, multiplicity=1, exclusive_key=False)
    row_entry = _kinetics_entry(entries, _KINETICS_ROW_BLOCK_KEY, multiplicity=1)

    if header_entry.size_bytes != _HEADER_MIN_BYTES:
        raise UnsupportedFormatVariantError("Kinetics SRS requires one exact 140-byte spectral header")
    header = _header(source, header_entry)
    if header.first_x <= header.last_x:
        raise UnsupportedFormatVariantError(
            "Kinetics SRS ascending or degenerate declared feature axes are not independently qualified"
        )

    if not len(_SERIES_MAGIC) <= descriptor_entry.size_bytes <= _KINETICS_METADATA_BLOCK_MAX_BYTES:
        raise _error("Kinetics series descriptor exceeds the qualified metadata bound", offset=descriptor_entry.offset)
    text_entries = [entry for entry in entries if entry.key == _KINETICS_TEXT_KEY]
    if any(
        not len(_KINETICS_TEXT_MARKER) <= entry.size_bytes <= _KINETICS_METADATA_BLOCK_MAX_BYTES
        for entry in text_entries
    ):
        raise _error("Kinetics description exceeds the qualified metadata bound", offset=text_entry.offset)
    source.require_metadata_bytes(
        descriptor_entry.size_bytes + sum(entry.size_bytes for entry in text_entries) + _KINETICS_METADATA_MIN_BYTES,
        format_id="omnic",
    )
    descriptor = source.read_at(descriptor_entry.offset, descriptor_entry.size_bytes, format_id="omnic")
    if descriptor.count(_SERIES_MAGIC) != 1:
        raise UnsupportedFormatVariantError(
            "Kinetics SRS requires exactly one embedded spectral-series descriptor magic"
        )
    text_payload = source.read_at(text_entry.offset, text_entry.size_bytes, format_id="omnic")
    for repeated in text_entries:
        if repeated is text_entry:
            continue
        repeated_payload = source.read_at(repeated.offset, repeated.size_bytes, format_id="omnic")
        if repeated_payload != text_payload:
            raise _error("Kinetics SRS contains contradictory repeated descriptions", offset=repeated.offset)
    if _KINETICS_TEXT_MARKER not in text_payload:
        raise UnsupportedFormatVariantError("extended-directory SRS is not a qualified Kinetics acquisition")
    text = _text(text_payload)
    title: str | None = None
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("Series title:\t"):
            candidate = stripped.split("\t", 1)[1].strip()
            title = candidate or None
            break

    if metadata_entry.size_bytes < _KINETICS_METADATA_MIN_BYTES:
        raise _error("Kinetics metadata block is shorter than 94 bytes", offset=metadata_entry.offset)
    metadata = source.read_at(
        metadata_entry.offset,
        _KINETICS_METADATA_MIN_BYTES,
        format_id="omnic",
    )
    first_time_minutes, last_time_minutes, interval_minutes = struct.unpack_from(
        "<fff", metadata, _KINETICS_METADATA_FIRST_TIME_OFFSET
    )
    sample_count = struct.unpack_from("<I", metadata, _KINETICS_METADATA_SAMPLE_COUNT_OFFSET)[0]
    if sample_count < 1 or not all(
        math.isfinite(value) for value in (first_time_minutes, last_time_minutes, interval_minutes)
    ):
        raise _error("Kinetics SRS declares invalid sample/time coordinates", offset=metadata_entry.offset + 66)
    source.require_blocks(int(sample_count), format_id="omnic")
    element_count = int(sample_count) * header.point_count
    source.require_elements(element_count, format_id="omnic")
    source.require_decoded_bytes(element_count * _DECODED_BYTES_PER_POINT, format_id="omnic")
    if first_time_minutes < 0 or last_time_minutes < first_time_minutes or interval_minutes <= 0:
        raise _error("Kinetics SRS time coordinates are not increasing and positive", offset=metadata_entry.offset + 66)
    expected_last = float(first_time_minutes) + (int(sample_count) - 1) * float(interval_minutes)
    if not math.isclose(expected_last, float(last_time_minutes), rel_tol=2e-6, abs_tol=2e-4):
        raise _error(
            "Kinetics SRS time endpoints contradict its interval and row count",
            offset=metadata_entry.offset + 66,
        )

    row_payload_bytes = int(sample_count) * (84 + header.point_count * 4) + (int(sample_count) - 1) * 16
    expected_row_block_bytes = _KINETICS_ROW_PREAMBLE_BYTES + row_payload_bytes
    if row_entry.size_bytes != expected_row_block_bytes:
        raise _error(
            "Kinetics row block size contradicts its header, point count, or sample count",
            offset=row_entry.table_offset,
        )
    return _SeriesLayout(
        variant="srs-kinetics",
        header_entry=header_entry,
        row_offset=row_entry.offset + _KINETICS_ROW_PREAMBLE_BYTES,
        sample_count=int(sample_count),
        first_time_minutes=float(first_time_minutes),
        last_time_minutes=float(last_time_minutes),
        interval_minutes=float(interval_minutes),
        reverse_features=True,
        title=title,
    )


def _series_layout(source: BoundedSource, *, limits: ParserLimits) -> _SeriesLayout:
    markers = _series_markers(source)
    rapid = markers[_RAPID_MARKER]
    if rapid:
        if len(rapid) != 3:
            raise UnsupportedFormatVariantError("Rapid-scan SRS requires exactly three structural markers")
        key = source.read_at(292, 1, format_id="omnic")[0]
        if key == 39:
            variant = "srs-rapid-scan-pristine"
        elif key == 15:
            variant = "srs-rapid-scan-reprocessed"
        else:
            raise UnsupportedFormatVariantError(f"Rapid-scan SRS status key {key} is not qualified")
        header_offset = rapid[0] - 152
        return _legacy_series_layout(source, variant, header_offset, rapid[2] + 60)
    high = markers[_HIGH_SPEED_MARKER]
    if high:
        if len(high) != 4:
            raise UnsupportedFormatVariantError("High-speed SRS requires exactly four structural markers")
        header_offset = high[0] - 152
        return _legacy_series_layout(source, "srs-high-speed", header_offset, high[3] + 60)
    thermal = markers[_THERMAL_MARKER]
    if thermal:
        if len(thermal) != 3:
            raise UnsupportedFormatVariantError("GC/TGA SRS requires exactly three structural markers")
        header_offset = thermal[0] - 152
        return _legacy_series_layout(source, "srs-gc-tga", header_offset, thermal[2] + 60)
    if _has_kinetics_directory_signature(source):
        return _kinetics_layout(source, limits=limits)
    raise UnsupportedFormatVariantError("SRS is not a qualified rapid-scan, high-speed, GC, TGA, or Kinetics series")


def _read_srs(source: BoundedSource, *, limits: ParserLimits) -> IngestionResult:
    layout = _series_layout(source, limits=limits)
    header_offset = layout.header_entry.offset
    data_offset = layout.row_offset
    if header_offset < 0:
        raise _error("SRS structural marker points before its series header")
    header = _header(source, layout.header_entry, series=layout.variant != "srs-kinetics")
    name = layout.title or source.path.stem
    sample_count = layout.sample_count
    if sample_count < 1 or not all(
        math.isfinite(value) for value in (layout.interval_minutes, layout.first_time_minutes, layout.last_time_minutes)
    ):
        raise _error("SRS declares invalid sample/time coordinates", offset=header_offset)
    source.require_blocks(sample_count, format_id="omnic")
    element_count = int(sample_count) * header.point_count
    source.require_elements(element_count, format_id="omnic")
    source.require_decoded_bytes(element_count * _DECODED_BYTES_PER_POINT, format_id="omnic")
    row_bytes = 84 + header.point_count * 4
    expected_end = data_offset + sample_count * row_bytes + (sample_count - 1) * 16
    if data_offset < 0 or expected_end > source.size_bytes:
        raise _error("SRS series rows extend beyond the source", offset=max(data_offset, 0))
    data = np.empty((sample_count, header.point_count), dtype=np.float64)
    labels: list[str] = []
    position = data_offset
    for index in range(sample_count):
        if index:
            position += 16
        prefix = source.read_at(position, 84, format_id="omnic")
        labels.append(_text(prefix) or f"Spectrum {index + 1}")
        position += 84
        values = np.frombuffer(source.read_at(position, header.point_count * 4, format_id="omnic"), dtype="<f4").astype(
            np.float64
        )
        if not np.all(np.isfinite(values)):
            raise _error("decoded SRS row contains non-finite values", offset=position)
        data[index] = values[::-1] if layout.reverse_features else values
        position += header.point_count * 4
    time_values = np.linspace(
        layout.first_time_minutes,
        layout.last_time_minutes,
        sample_count,
        dtype=np.float64,
    )
    sample_table: dict[str, list[Any]] = {"series_time_minutes": time_values.tolist()}
    recorded_times: np.ndarray | None = None
    if layout.variant == "srs-kinetics":
        if len(set(labels)) != len(labels):
            raise _error("Kinetics SRS contains duplicate row labels", offset=data_offset)
        parsed_times: list[float] = []
        for label in labels:
            match = _KINETICS_LABEL.fullmatch(label)
            if match is None:
                raise UnsupportedFormatVariantError(
                    "Kinetics SRS row labels do not match the qualified linked-spectrum grammar"
                )
            parsed_times.append(float(match.group(1)))
        recorded_times = np.asarray(parsed_times, dtype=np.float64)
        if not np.all(np.isfinite(recorded_times)) or np.any(np.diff(recorded_times) <= 0):
            raise _error("Kinetics SRS recorded row times are not finite and strictly increasing", offset=data_offset)
        first_time_matches = math.isclose(recorded_times[0], layout.first_time_minutes, rel_tol=0.0, abs_tol=1e-3)
        last_time_matches = math.isclose(recorded_times[-1], layout.last_time_minutes, rel_tol=0.0, abs_tol=1e-3)
        if not first_time_matches or not last_time_matches:
            raise _error("Kinetics SRS row-label times contradict its header endpoints", offset=data_offset)
        sample_table["recorded_series_time_minutes"] = recorded_times.tolist()
    dataset = _dataset(
        source=source,
        header=header,
        data=data,
        labels=labels,
        sample_values=time_values,
        sample_units="min",
        sample_title="Series time",
        sample_table=sample_table,
        title=f"{name}: {_Y_TYPES[header.y_code][0]} series",
    )
    metadata = {
        "container_name": name,
        "series_layout": layout.variant,
        "spectrum_count": int(sample_count),
        "first_time_minutes": float(layout.first_time_minutes),
        "last_time_minutes": float(layout.last_time_minutes),
        "collection_interval_seconds": float(layout.interval_minutes) * 60.0,
        "header": _header_metadata(header),
    }
    dataset.meta["omnic.acquisition"] = {
        "series_time_minutes": time_values.tolist(),
        **metadata["header"],
    }
    if layout.variant == "srs-kinetics":
        metadata["feature_storage_order"] = "ascending_reversed_to_declared_axis"
        metadata["recorded_time_source"] = "row_labels"
    return ingestion_result(
        source=source,
        format_id="omnic",
        variant="srs-qualified-series",
        parser_id="spectrasherpa.omnic",
        parser_version="1",
        assets=(dataset_asset(dataset, asset_id="series", raw_metadata=metadata),),
        raw_metadata=metadata,
    )


class OmnicPlugin:
    format_id = "omnic"
    display_name = "Thermo Nicolet OMNIC"
    description = "Qualified native OMNIC SPA spectra, SPG groups, and SRS series"
    extensions = (".spa", ".spg", ".srs")
    parser_id = "spectrasherpa.omnic"
    parser_version = "1"

    def probe(self, source: BoundedSource) -> ProbeResult:
        inspected = min(source.size_bytes, len(_DATA_MAGIC))
        if source.extension not in self.extensions or source.size_bytes < len(_DATA_MAGIC):
            return ProbeResult(self.format_id, None, ProbeConfidence.NO_MATCH, bytes_inspected=inspected)
        magic = source.read_at(0, len(_DATA_MAGIC), format_id=self.format_id)
        if source.extension in {".spa", ".spg"} and magic == _DATA_MAGIC:
            variant = "spa-single-spectrum" if source.extension == ".spa" else "spg-compatible-spectrum-group"
            return ProbeResult(
                self.format_id, variant, ProbeConfidence.EXACT, ("OMNIC spectral-data magic",), inspected
            )
        if source.extension == ".srs" and magic == _SERIES_MAGIC:
            return ProbeResult(
                self.format_id,
                "srs-qualified-series",
                ProbeConfidence.EXACT,
                ("OMNIC spectral-series magic",),
                inspected,
            )
        return ProbeResult(self.format_id, None, ProbeConfidence.NO_MATCH, bytes_inspected=inspected)

    def read(
        self,
        source: BoundedSource,
        *,
        limits: ParserLimits,
        parser_options: Mapping[str, str] | None = None,
    ) -> IngestionResult:
        if parser_options:
            raise UnsupportedFormatVariantError("OMNIC does not admit parser options")
        if source.extension == ".spa":
            return _read_spa(source, limits=limits)
        if source.extension == ".spg":
            return _read_spg(source, limits=limits)
        if source.extension == ".srs":
            return _read_srs(source, limits=limits)
        raise FormatIdentityError(f"OMNIC bytes contradict filename {source.path.name!r}; use .spa, .spg, or .srs")


PLUGIN = OmnicPlugin()

__all__ = ["OmnicPlugin", "PLUGIN"]
