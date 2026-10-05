"""Bounded native reader for one-dimensional Bruker OPUS data blocks.

The binary layout and data/status pairing are adapted from ``brukeropus``
1.4.3, tag ``v1.4.3`` / commit
``af5a508cef7de8089acd27a215d644ab451257dd`` (MIT, Josh Duran, 2024).
SpectraSherpa deliberately ports only the read-only file subset and adds its
own checked-range, resource-limit, ambiguity, typed-asset, and provenance
boundaries. OPUS series/3-D blocks are recognized and refused rather than
flattened.

Same-type data/status pairing follows ``brukeropus.file.block.pair_data_and_
status_blocks``: a data block whose type uniquely identifies one status block
is paired immediately, with no value check. A data block sharing its pairing
key with more than one independently qualified status block is disambiguated
by comparing the block's decoded, CSF-scaled value envelope against each
candidate's declared MNY/MXY -- never by position or file order. A status
block's recorded MNY/MXY is not required to match a *singular* pairing's
decoded envelope: real Bruker acquisitions record it from an intermediate
processing stage that can differ slightly from the literal on-disk bytes, so
treating that mismatch as fatal for an otherwise-unambiguous pairing rejects
genuine instrument files. A pairing that stays ambiguous after value
disambiguation is refused individually, exactly like any other unqualified
block: it is named in ``opus.refused_blocks``, and the rest of the file is
unaffected.
"""

from __future__ import annotations

import math
import struct
from collections import defaultdict
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

import numpy as np

from spectra_sherpa.app.lib.axes import FeatureAxis, SampleAxis, SpectralAxis
from spectra_sherpa.app.lib.sherpa_dataset import DomainContext, SherpaDataset
from spectra_sherpa.ingestion_errors import (
    FormatIdentityError,
    UnreadableSpectrumError,
    UnsupportedFormatVariantError,
)
from spectra_sherpa.ingestion_formats import matches_filename
from spectra_sherpa.io.base import BoundedSource
from spectra_sherpa.io.formats._helpers import dataset_asset, derive_data_role, ingestion_result
from spectra_sherpa.io.types import IngestionResult, ParserLimits, ProbeConfidence, ProbeResult

_MAGIC = b"\n\n\xfe\xfe"
_HEADER_BYTES = 24
_DIRECTORY_ENTRY_BYTES = 12
_DATA_TYPE_KEYS = {
    1: "",
    2: "ig",
    3: "ph",
    4: "a",
    5: "t",
    6: "km",
    7: "tr",
    8: "gcig",
    9: "gcsc",
    10: "ra",
    11: "e",
    12: "r",
    14: "pw",
    15: "logr",
    16: "atr",
    17: "pas",
    18: "arit",
    19: "aria",
    22: "match",
}
_DATA_TYPE_LABELS = {
    1: "Spectrum",
    2: "Interferogram",
    3: "Phase",
    4: "Absorbance",
    5: "Transmittance",
    6: "Kubelka-Munk",
    7: "Trace",
    8: "GC interferogram series",
    9: "GC spectrum series",
    10: "Raman",
    11: "Emission",
    12: "Reflectance",
    14: "Power",
    15: "Log reflectance",
    16: "ATR",
    17: "Photoacoustic",
    18: "Arithmetic transmittance",
    19: "Arithmetic absorbance",
    22: "Library match",
}
_RESULT_QUANTITY = {
    4: ("Absorbance", "absorbance"),
    5: ("Transmittance", "transmittance"),
    6: ("Kubelka-Munk", None),
    10: ("Raman intensity", None),
    11: ("Emission intensity", None),
    12: ("Reflectance", "reflectance"),
    14: ("Power", None),
    15: ("Log reflectance", None),
    16: ("ATR", None),
    17: ("Photoacoustic intensity", None),
}
_SUMMARY_PARAMETERS = (
    "snm",
    "sfm",
    "res",
    "nss",
    "bms",
    "src",
    "dtc",
    "apt",
    "apf",
    "dat",
    "tim",
)
_DECODED_BYTES_PER_POINT = 32
_QUALIFIED_TYPE_INDICES = frozenset({1, 2, 3, 4})
_QUALIFIED_AXIS_CODES = frozenset({"PNT", "WN"})


@dataclass(frozen=True, slots=True)
class _Entry:
    type_code: tuple[int, int, int, int, int, int]
    offset: int
    size_bytes: int

    @property
    def is_status(self) -> bool:
        return self.type_code[2] == 1

    @property
    def is_parameter(self) -> bool:
        return self.type_code[2] > 0 or self.type_code == (0, 0, 0, 0, 0, 1)

    @property
    def is_series(self) -> bool:
        return self.type_code[2] == 0 and self.type_code[3] not in {0, 13} and self.type_code[5] == 2

    @property
    def is_data(self) -> bool:
        return self.type_code[2] == 0 and self.type_code[3] not in {0, 13} and self.type_code[5] not in {2, 5}

    @property
    def is_compact(self) -> bool:
        return self.is_data and self.type_code[5] == 4

    @property
    def pairing_key(self) -> tuple[int, int, int, int, int]:
        return (*self.type_code[:2], *self.type_code[3:])


def _error(detail: str, *, offset: int | None = None) -> UnreadableSpectrumError:
    return UnreadableSpectrumError(format_id="opus", detail=detail, offset=offset)


def _decode_type(value: int) -> tuple[int, int, int, int, int, int]:
    return (
        value & 0b11,
        (value >> 2) & 0b11,
        (value >> 4) & 0b111111,
        (value >> 10) & 0b1111111,
        (value >> 17) & 0b11,
        (value >> 19) & 0b111,
    )


def _header(source: BoundedSource) -> tuple[float, int, int, int]:
    if source.size_bytes < _HEADER_BYTES:
        raise _error("file is shorter than the 24-byte OPUS header", offset=source.size_bytes)
    payload = source.read_at(0, _HEADER_BYTES, format_id="opus")
    if payload[:4] != _MAGIC:
        raise FormatIdentityError("OPUS parser received bytes without the OPUS file magic")
    version, directory_offset, max_blocks, block_count = struct.unpack_from("<diii", payload, 4)
    if not math.isfinite(version) or version <= 0:
        raise _error("header contains an invalid OPUS version", offset=4)
    if directory_offset < _HEADER_BYTES or directory_offset % 4:
        raise _error("directory offset is invalid or not 32-bit aligned", offset=12)
    if max_blocks < 1 or block_count < 1 or block_count > max_blocks:
        raise _error("directory block counts are inconsistent", offset=16)
    return float(version), int(directory_offset), int(max_blocks), int(block_count)


def _directory(source: BoundedSource, *, limits: ParserLimits) -> tuple[float, tuple[_Entry, ...]]:
    version, directory_offset, max_blocks, block_count = _header(source)
    source.require_blocks(max_blocks, format_id="opus")
    directory_size = max_blocks * _DIRECTORY_ENTRY_BYTES
    payload = source.read_at(directory_offset, directory_size, format_id="opus")
    entries: list[_Entry] = []
    for index in range(max_blocks):
        type_value, size_words, offset = struct.unpack_from("<iii", payload, index * _DIRECTORY_ENTRY_BYTES)
        if offset <= 0:
            break
        if size_words <= 0:
            raise _error("directory entry declares a non-positive block size", offset=directory_offset + index * 12 + 4)
        size_bytes = size_words * 4
        if offset < 0 or offset % 4 or offset + size_bytes > source.size_bytes:
            raise _error(
                "directory entry points outside the source or is not 32-bit aligned",
                offset=directory_offset + index * 12 + 8,
            )
        entries.append(_Entry(_decode_type(type_value), int(offset), int(size_bytes)))
    if len(entries) != block_count:
        raise _error(
            f"header declares {block_count} blocks but the directory contains {len(entries)}",
            offset=directory_offset,
        )
    directory_entry = entries[0]
    if (
        directory_entry.type_code != (0, 0, 0, 13, 0, 0)
        or directory_entry.offset != directory_offset
        or directory_entry.size_bytes != directory_size
    ):
        raise _error(
            "first directory entry does not authenticate the header-declared directory block",
            offset=directory_offset,
        )
    ordered = sorted(entries, key=lambda entry: (entry.offset, entry.size_bytes))
    for previous, current in zip(ordered, ordered[1:]):
        if previous.offset + previous.size_bytes > current.offset:
            raise _error("directory blocks overlap", offset=current.offset)
    return version, tuple(entries)


def _decode_text(payload: bytes, *, offset: int) -> str:
    value = payload.split(b"\x00", 1)[0]
    try:
        return value.decode("latin-1")
    except UnicodeDecodeError as exc:  # pragma: no cover - latin-1 is total
        raise _error("parameter text cannot be decoded", offset=offset) from exc


def _parameters(source: BoundedSource, entry: _Entry) -> dict[str, int | float | str]:
    payload = source.read_at(entry.offset, entry.size_bytes, format_id="opus")
    values: dict[str, int | float | str] = {}
    cursor = 0
    while cursor < len(payload):
        if len(payload) - cursor < 8:
            if any(payload[cursor:]):
                raise _error("truncated parameter record", offset=entry.offset + cursor)
            break
        key_bytes = payload[cursor : cursor + 3]
        try:
            key = key_bytes.decode("ascii")
        except UnicodeDecodeError as exc:
            raise _error("parameter key is not ASCII", offset=entry.offset + cursor) from exc
        if key == "END":
            break
        if not key.strip() or any(ord(character) < 32 for character in key):
            raise _error("parameter key is invalid", offset=entry.offset + cursor)
        dtype_code, size_words = struct.unpack_from("<hh", payload, cursor + 4)
        if size_words < 0:
            raise _error("parameter declares a negative payload size", offset=entry.offset + cursor + 6)
        value_size = size_words * 2
        value_offset = cursor + 8
        end = value_offset + value_size
        if end > len(payload):
            raise _error("parameter payload exceeds its block", offset=entry.offset + value_offset)
        if dtype_code == 0:
            if value_size < 4:
                raise _error("integer parameter is shorter than four bytes", offset=entry.offset + value_offset)
            value: int | float | str = int(struct.unpack_from("<i", payload, value_offset)[0])
        elif dtype_code == 1:
            if value_size < 8:
                raise _error("floating parameter is shorter than eight bytes", offset=entry.offset + value_offset)
            value = float(struct.unpack_from("<d", payload, value_offset)[0])
            if not math.isfinite(value):
                raise _error("floating parameter is not finite", offset=entry.offset + value_offset)
        else:
            value = _decode_text(payload[value_offset:end], offset=entry.offset + value_offset)
        values[key.lower()] = value
        cursor = end
    return values


def _raw_values(source: BoundedSource, entry: _Entry, *, dpf: int) -> np.ndarray:
    if dpf != 1:
        raise UnsupportedFormatVariantError(
            f"OPUS DPF={dpf} is structurally recognized but not independently qualified; "
            "export as float32 OPUS, CSV, or JCAMP-DX"
        )
    if entry.size_bytes % 4:
        raise _error("data block size is not a multiple of four bytes", offset=entry.offset)
    payload = source.read_at(entry.offset, entry.size_bytes, format_id="opus")
    return np.frombuffer(payload, dtype=np.dtype("<f4"))


def _status_matches(data: np.ndarray, status: Mapping[str, Any], *, compact: bool) -> bool:
    npt = status.get("npt")
    csf = status.get("csf")
    if isinstance(npt, bool) or not isinstance(npt, int) or npt < 1 or npt > data.size:
        return False
    selected = data[-npt:] if compact else data[:npt]
    expected_min = status.get("mny")
    expected_max = status.get("mxy")
    if (
        isinstance(expected_min, bool)
        or not isinstance(expected_min, (int, float))
        or isinstance(expected_max, bool)
        or not isinstance(expected_max, (int, float))
    ):
        # Missing MNY/MXY is harmless only when the directory supplies one
        # status candidate in total.  It cannot prove which status belongs to
        # which data block when the pairing key is repeated.
        return False
    if isinstance(csf, bool) or not isinstance(csf, (int, float)) or not math.isfinite(float(csf)):
        return False
    scale = float(csf)
    raw_min = float(np.min(selected))
    raw_max = float(np.max(selected))
    actual_min, actual_max = scale * raw_min, scale * raw_max
    if scale < 0:
        actual_min, actual_max = actual_max, actual_min
    return bool(
        np.isclose(actual_min, expected_min, rtol=2e-6, atol=1e-12)
        and np.isclose(actual_max, expected_max, rtol=2e-6, atol=1e-12)
    )


def _qualified_data_type(entry: _Entry) -> int:
    """Return the admitted result type after closing every scientific type dimension."""
    complex_part, source_role, _parameter_kind, encoded_type, derivative_order, data_flags = entry.type_code
    type_index = encoded_type % 32
    if complex_part != 3:
        raise UnsupportedFormatVariantError(
            f"OPUS complex-part code {complex_part} is structurally recognized but not independently qualified; "
            "export the amplitude spectrum as CSV or JCAMP-DX"
        )
    if source_role not in {1, 2, 3}:
        raise UnsupportedFormatVariantError(
            f"OPUS source-role code {source_role} is structurally recognized but not independently qualified"
        )
    if encoded_type >= 32:
        raise UnsupportedFormatVariantError(
            "Multi-channel OPUS data blocks are structurally recognized but not independently qualified"
        )
    if derivative_order != 0:
        raise UnsupportedFormatVariantError(
            f"OPUS derivative order {derivative_order} is structurally recognized but not independently qualified"
        )
    if entry.is_compact:
        raise UnsupportedFormatVariantError(
            "Compact OPUS data blocks are structurally recognized but not independently qualified"
        )
    if data_flags != 0:
        raise UnsupportedFormatVariantError(
            f"OPUS data-flags code {data_flags} is structurally recognized but not independently qualified"
        )
    if type_index not in _QUALIFIED_TYPE_INDICES:
        raise UnsupportedFormatVariantError(
            f"OPUS data type {type_index} is structurally recognized but not independently qualified"
        )
    return type_index


class _PairingRefused(Exception):
    """Internal control-flow signal: this data block's pairing was not resolved.

    Never propagates out of :func:`OpusPlugin.read`; the caller converts it
    into a ``refused_blocks`` entry so the rest of the file is unaffected.
    """

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def _resolve_status_pairing(
    source: BoundedSource,
    data_entry: _Entry,
    status_candidates: list[_Entry],
    parsed_parameters: Mapping[int, dict[str, Any]],
    raw_cache: dict[int, np.ndarray],
) -> tuple[_Entry, dict[str, Any], np.ndarray]:
    """Resolve one data block to exactly one status block, or raise ``_PairingRefused``.

    A status candidate first has to be independently qualified itself: an
    explicit DPF=1, a finite CSF, and a qualified axis code. A data block with
    exactly one qualified candidate is paired directly -- brukeropus accepts a
    singular type match with no value check, and this reader follows that: a
    status block's recorded MNY/MXY reflects Bruker's own intermediate
    processing and is not guaranteed to reproduce from the literal on-disk
    bytes, so requiring it to match would refuse genuine unambiguous
    acquisitions. A data block with more than one qualified candidate -- the
    same OPUS type stored twice, which real acquisitions do produce -- is
    disambiguated by comparing its decoded, CSF-scaled value envelope against
    each candidate's declared MNY/MXY.
    """
    qualifying: list[tuple[_Entry, dict[str, Any]]] = []
    disqualification_reasons: list[str] = []
    for status_entry in status_candidates:
        status = parsed_parameters[status_entry.offset]
        dpf = status.get("dpf")
        if isinstance(dpf, bool) or not isinstance(dpf, int):
            raise _error("data-status block is missing an explicit integer DPF", offset=status_entry.offset)
        if dpf != 1:
            disqualification_reasons.append(
                f"OPUS DPF={dpf} is structurally recognized but not independently qualified"
            )
            continue
        csf = status.get("csf")
        if isinstance(csf, bool) or not isinstance(csf, (int, float)) or not math.isfinite(float(csf)):
            raise _error("data-status block is missing an explicit finite CSF", offset=status_entry.offset)
        axis_code = str(status.get("dxu") or "").strip().upper()
        if axis_code not in _QUALIFIED_AXIS_CODES:
            disqualification_reasons.append(
                f"OPUS axis code {axis_code!r} is structurally recognized but not independently qualified"
            )
            continue
        qualifying.append((status_entry, status))

    if not qualifying:
        raise _PairingRefused(
            disqualification_reasons[0]
            if disqualification_reasons
            else "OPUS data block has no independently qualified data-status pairing"
        )

    raw = raw_cache.get(data_entry.offset)
    if raw is None:
        raw = _raw_values(source, data_entry, dpf=1)
        raw_cache[data_entry.offset] = raw

    # The brukeropus singular-pairing rule applies only when the directory has
    # one candidate in total.  Filtering an ambiguous candidate set down to
    # one qualified status does not make that status the data block's proven
    # partner: doing so can attach a later result's status/axis to an earlier
    # result's values.  Repeated keys always require an exact, unique envelope
    # match among the independently qualified candidates.
    if len(status_candidates) == 1 and len(qualifying) == 1:
        status_entry, status = qualifying[0]
        return status_entry, status, raw

    matched = [pair for pair in qualifying if _status_matches(raw, pair[1], compact=data_entry.is_compact)]
    if len(matched) != 1:
        excluded = "; excluded candidates: " + "; ".join(disqualification_reasons) if disqualification_reasons else ""
        raise _PairingRefused(
            f"{len(qualifying)} same-type OPUS data/status pairings are independently qualified but "
            f"{len(matched)} match this block's decoded value envelope; not independently qualified{excluded}"
        )
    status_entry, status = matched[0]
    return status_entry, status, raw


def _asset_key(entry: _Entry) -> str:
    type_index = entry.type_code[3] % 32
    key = _DATA_TYPE_KEYS.get(type_index, f"type_{type_index}")
    if entry.type_code[1] == 1:
        key += "sm"
    elif entry.type_code[1] == 2:
        key += "rf"
    elif entry.type_code[1] > 3:
        key += f"_{entry.type_code[1]}"
    channel_count = entry.type_code[3] // 32 + 1
    if channel_count > 1:
        key += f"_{channel_count}ch"
    if entry.is_compact:
        key += "_compact"
    return key


def _axis(
    *,
    values: np.ndarray,
    dxu: str | None,
    type_index: int,
) -> tuple[FeatureAxis, tuple[str, ...], str | None]:
    code = (dxu or "").strip().upper()
    if code == "WN":
        return SpectralAxis(values=values, title="Wavenumber", units="cm-1"), (), "cm-1"
    if code == "PNT":
        return FeatureAxis(values=values, title="Data point"), (), None
    raise UnsupportedFormatVariantError(
        f"OPUS axis code {code!r} is structurally recognized but not independently qualified; "
        "export as WN/PNT OPUS, CSV, or JCAMP-DX"
    )


def _dataset(
    *,
    source: BoundedSource,
    entry: _Entry,
    status: Mapping[str, Any],
    raw: np.ndarray,
    asset_id: str,
    global_parameters: Mapping[str, Any],
) -> tuple[SherpaDataset, tuple[str, ...], dict[str, Any]]:
    npt = status.get("npt")
    if isinstance(npt, bool) or not isinstance(npt, int) or npt < 1 or npt > raw.size:
        raise _error("paired data-status block has an invalid NPT", offset=entry.offset)
    for name in ("fxv", "lxv"):
        if (
            isinstance(status.get(name), bool)
            or not isinstance(status.get(name), (int, float))
            or not math.isfinite(float(status[name]))
        ):
            raise _error(f"paired data-status block has no finite {name.upper()}", offset=entry.offset)
    csf = status.get("csf")
    if isinstance(csf, bool) or not isinstance(csf, (int, float)) or not math.isfinite(float(csf)):
        raise _error("paired data-status block has no finite CSF", offset=entry.offset)
    selected = raw[-npt:] if entry.is_compact else raw[:npt]
    y = float(csf) * selected
    if not np.all(np.isfinite(y)):
        raise _error("decoded OPUS data contains non-finite values", offset=entry.offset)
    encoded_axis = np.linspace(float(status["fxv"]), float(status["lxv"]), npt, dtype=np.float64)
    type_index = entry.type_code[3] % 32
    feature_axis, warnings, expected_units = _axis(
        values=encoded_axis,
        dxu=str(status.get("dxu") or ""),
        type_index=type_index,
    )
    label = _DATA_TYPE_LABELS.get(type_index, f"OPUS data type {type_index}")
    quantity, value_units = _RESULT_QUANTITY.get(type_index, (label, None))
    sample_name = str(global_parameters.get("snm") or source.path.stem)
    technique = "Raman" if type_index == 10 else "IR" if isinstance(feature_axis, SpectralAxis) else None
    metadata = {
        "opus.asset_id": asset_id,
        "opus.block_type": list(entry.type_code),
        "opus.data_label": label,
        "opus.data_parameters": dict(status),
    }
    dataset = SherpaDataset(
        X=y.reshape(1, -1),
        feature_axis=feature_axis,
        sample_axis=SampleAxis(labels=[sample_name], title="Sample"),
        domain=DomainContext(
            technique=technique,
            expected_units=expected_units,
            data_quantity=quantity,
            instrument=str(global_parameters.get("ins")) if global_parameters.get("ins") else None,
        ),
        title=f"{sample_name}: {label}",
        units=value_units,
        extra={"source_file": source.path.name, **metadata},
        data_role=derive_data_role(feature_axis),
    )
    return dataset, warnings, metadata


class OpusPlugin:
    format_id = "opus"
    display_name = "Bruker OPUS"
    description = "Qualified Bruker OPUS float32 WN/PNT one-dimensional spectra and signal blocks"
    extensions = (".opus",)
    filename_patterns = ("numeric-extension",)
    extension_examples = (".0",)
    parser_id = "spectrasherpa.opus"
    parser_version = "2"

    def probe(self, source: BoundedSource) -> ProbeResult:
        prefix = source.read_at(0, min(source.size_bytes, _HEADER_BYTES), format_id=self.format_id)
        if prefix.startswith(_MAGIC):
            return ProbeResult(
                self.format_id,
                "directory-block-v1",
                ProbeConfidence.EXACT,
                ("OPUS magic", "little-endian directory header"),
                len(prefix),
            )
        return ProbeResult(self.format_id, None, ProbeConfidence.NO_MATCH, bytes_inspected=len(prefix))

    def read(
        self,
        source: BoundedSource,
        *,
        limits: ParserLimits,
        parser_options: Mapping[str, str] | None = None,
    ) -> IngestionResult:
        if parser_options:
            raise UnsupportedFormatVariantError("OPUS does not admit parser options")
        if not matches_filename(
            source.path.name,
            extensions=self.extensions,
            filename_patterns=self.filename_patterns,
        ):
            raise FormatIdentityError(
                f"OPUS bytes contradict filename {source.path.name!r}; rename the file with .opus or a numeric suffix"
            )
        version, entries = _directory(source, limits=limits)
        series = [entry for entry in entries if entry.is_series]
        if series:
            raise UnsupportedFormatVariantError(
                "Bruker OPUS series/3-D data blocks are recognized but not supported by this reader; "
                "export the intended one-dimensional spectrum without flattening the series"
            )
        parameter_entries = [entry for entry in entries if entry.is_parameter]
        source.require_metadata_bytes(
            sum(entry.size_bytes for entry in parameter_entries),
            format_id=self.format_id,
        )
        parsed_parameters = {entry.offset: _parameters(source, entry) for entry in parameter_entries}
        global_parameter_blocks = [
            {"type_code": list(entry.type_code), "parameters": parsed_parameters[entry.offset]}
            for entry in parameter_entries
            if not entry.is_status
        ]
        global_parameters: dict[str, Any] = {}
        for block in global_parameter_blocks:
            for key, value in block["parameters"].items():
                global_parameters.setdefault(key, value)

        status_by_key: dict[tuple[int, int, int, int, int], list[_Entry]] = defaultdict(list)
        for entry in entries:
            if entry.is_status:
                status_by_key[entry.pairing_key].append(entry)
        # Include qualified-shape result entries even when an unqualified flag
        # would otherwise make ``is_data`` hide them.  A block SpectraSherpa
        # cannot interpret is never silently omitted: it is refused
        # individually, named in an explicit warning, and recorded in
        # ``opus.refused_blocks``.  Refusing the containing file instead would
        # deny access to every qualified block beside it, which real OPUS
        # acquisitions routinely carry.
        candidate_entries = [
            entry
            for entry in entries
            if entry.is_data
            or (
                entry.type_code[0] == 3
                and entry.type_code[1] in {1, 2, 3}
                and entry.type_code[2] == 0
                and entry.type_code[3] % 32 in _QUALIFIED_TYPE_INDICES
            )
        ]
        if not candidate_entries:
            raise _error("file contains no supported one-dimensional data blocks")

        data_entries: list[_Entry] = []
        refused_blocks: list[dict[str, Any]] = []
        refused_status_offsets: set[int] = set()
        for data_entry in candidate_entries:
            try:
                _qualified_data_type(data_entry)
            except UnsupportedFormatVariantError as refusal:
                refused_blocks.append(
                    {
                        "offset": data_entry.offset,
                        "size_bytes": data_entry.size_bytes,
                        "type_code": list(data_entry.type_code),
                        "reason": str(refusal),
                    }
                )
                refused_status_offsets.update(entry.offset for entry in status_by_key.get(data_entry.pairing_key, []))
                continue
            data_entries.append(data_entry)

        if not data_entries:
            raise UnsupportedFormatVariantError(
                "Every OPUS data block in this file is structurally recognized but not independently "
                "qualified: " + "; ".join(str(block["reason"]) for block in refused_blocks)
            )

        # Reject declared output sizes before decoding any data block. Multiple
        # same-type status blocks are charged conservatively by their largest
        # NPT until value-level pairing resolves them.
        declared_points = 0
        for data_entry in data_entries:
            status_entries = status_by_key.get(data_entry.pairing_key, [])
            if not status_entries:
                raise _error("data block has no matching status block", offset=data_entry.offset)
            candidate_counts = []
            for status_entry in status_entries:
                npt = parsed_parameters[status_entry.offset].get("npt")
                if isinstance(npt, bool) or not isinstance(npt, int) or npt < 1:
                    raise _error("data-status block has an invalid NPT", offset=status_entry.offset)
                candidate_counts.append(npt)
            declared_points += max(candidate_counts)
        source.require_elements(declared_points, format_id=self.format_id)
        source.require_decoded_bytes(
            declared_points * _DECODED_BYTES_PER_POINT,
            format_id=self.format_id,
        )

        # Resolve each type-qualified data block to exactly one status block.
        # A pairing that cannot be resolved is refused individually and never
        # denies the rest of the file. See ``_resolve_status_pairing`` for the
        # qualification and disambiguation rules.
        candidates: list[tuple[_Entry, _Entry, dict[str, Any], np.ndarray]] = []
        used_status_offsets: set[int] = set()
        raw_cache: dict[int, np.ndarray] = {}
        for data_entry in data_entries:
            status_candidates = [
                entry
                for entry in status_by_key.get(data_entry.pairing_key, [])
                if entry.offset not in used_status_offsets
            ]
            try:
                status_entry, status, raw = _resolve_status_pairing(
                    source, data_entry, status_candidates, parsed_parameters, raw_cache
                )
            except _PairingRefused as refusal:
                refused_blocks.append(
                    {
                        "offset": data_entry.offset,
                        "size_bytes": data_entry.size_bytes,
                        "type_code": list(data_entry.type_code),
                        "reason": refusal.reason,
                    }
                )
                refused_status_offsets.update(entry.offset for entry in status_candidates)
                continue

            used_status_offsets.add(status_entry.offset)
            candidates.append((data_entry, status_entry, status, raw))

        if not candidates:
            raise UnsupportedFormatVariantError(
                "Every OPUS data block in this file is structurally recognized but not independently "
                "qualified: " + "; ".join(str(block["reason"]) for block in refused_blocks)
            )

        unmatched_statuses = [
            entry
            for values in status_by_key.values()
            for entry in values
            if entry.offset not in used_status_offsets and entry.offset not in refused_status_offsets
        ]
        if unmatched_statuses:
            raise _error(
                f"{len(unmatched_statuses)} data-status block(s) have no unambiguous data block",
                offset=unmatched_statuses[0].offset,
            )

        # Bruker's own OPUS convention treats the last-written block of a
        # repeated type as the current result -- brukeropus's own pairing
        # rule sorts duplicates by reverse file position because "last spec
        # seems to be OPUS preference". The bare asset id is reserved for
        # that occurrence; earlier same-type blocks are numbered oldest-last
        # (``a_2`` is the older of two absorbance results, not the newer).
        by_base_id: dict[str, list[_Entry]] = defaultdict(list)
        for data_entry, *_rest in candidates:
            by_base_id[_asset_key(data_entry)].append(data_entry)
        asset_id_by_offset: dict[int, str] = {}
        for base_id, group in by_base_id.items():
            for rank, entry in enumerate(sorted(group, key=lambda entry: entry.offset, reverse=True), start=1):
                asset_id_by_offset[entry.offset] = base_id if rank == 1 else f"{base_id}_{rank}"

        assets = []
        for data_entry, _status_entry, status, raw in sorted(candidates, key=lambda item: item[0].offset):
            asset_id = asset_id_by_offset[data_entry.offset]
            dataset, warnings, metadata = _dataset(
                source=source,
                entry=data_entry,
                status=status,
                raw=raw,
                asset_id=asset_id,
                global_parameters=global_parameters,
            )
            assets.append(
                dataset_asset(
                    dataset,
                    asset_id=asset_id,
                    raw_metadata=metadata,
                    warnings=warnings,
                )
            )

        summary = {key: global_parameters[key] for key in _SUMMARY_PARAMETERS if key in global_parameters}
        warnings: tuple[str, ...] = ()
        if refused_blocks:
            warnings = (
                f"{len(refused_blocks)} OPUS data block(s) were recognized but not independently "
                "qualified and were not imported; the qualified blocks in this file are unaffected. "
                "See opus.refused_blocks for each block's offset, type code, and reason.",
            )
        return ingestion_result(
            source=source,
            format_id=self.format_id,
            variant="directory-block-v1",
            parser_id=self.parser_id,
            parser_version=self.parser_version,
            assets=tuple(assets),
            raw_metadata={
                "opus.version": version,
                "opus.block_count": len(entries),
                "opus.parameters": summary,
                "opus.parameter_blocks": global_parameter_blocks,
                "opus.refused_blocks": refused_blocks,
            },
            warnings=warnings,
        )


PLUGIN = OpusPlugin()
