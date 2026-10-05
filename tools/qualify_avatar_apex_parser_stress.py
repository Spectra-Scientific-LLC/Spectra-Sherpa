#!/usr/bin/env python3
"""Qualify the private Nicolet Apex/OMNIC native-parser stress corpus.

The command emits one data-free JSON receipt. It binds five exact private ZIP
archives and two instrument-resaved SPA observations, parses every admitted
source with bounded native readers, and checks same-source SPA/CSV/JDX/SPC
exports without pretending that metadata-losing export formats have identical
semantics.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import stat
import sys
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

import numpy as np

from spectra_sherpa.app.services.dag.nodes.preprocessing.clip_range_node import _clip_range_dispatch
from spectra_sherpa.app.services.dag.nodes.preprocessing.normalize_node import _normalize_dispatch
from spectra_sherpa.io import ParserLimits, ingest

SCHEMA_VERSION = "spectrasherpa-avatar-apex-parser-stress-qualification/1"
MAX_ARCHIVE_BYTES = 2 * 1024 * 1024
MAX_MEMBER_BYTES = 512 * 1024
MAX_TOTAL_MEMBER_BYTES = 4 * 1024 * 1024
LIMITS = ParserLimits(
    max_source_bytes=MAX_MEMBER_BYTES,
    max_decoded_elements=100_000,
    max_decoded_bytes=128 * 1024 * 1024,
    max_blocks=512,
    max_metadata_bytes=2 * 1024 * 1024,
    max_probe_bytes=64 * 1024,
)


class QualificationError(ValueError):
    """One exact stress-corpus qualification invariant failed."""


@dataclass(frozen=True)
class ArchiveAuthority:
    filename: str
    size_bytes: int
    sha256: str
    members: tuple[str, ...]


TYPICAL_MEMBERS = (
    "EVA Out Of Specifications 32% b.SPA",
    "EVA Out Of Specifications 32%.SPA",
    "findpeak.spa",
    "First extracted spectrum epoxy.SPA",
    "fsd.spa",
    "Gold Seal Leaf sample spectrum.SPA",
    "lubed.spa",
    "monitor compaq corrected.spa",
    "othercon.spa",
    "photoac.spa",
    "polysty.spa",
    "raman.spa",
    "scale1.spa",
    "scale2.spa",
    "scale3.spa",
    "search.spa",
    "Second extracted spectrum epoxy.SPA",
    "SpecInt1.SPA",
    "SpecInt2.SPA",
    "SpecInt3.SPA",
    "SpecInt4.SPA",
    "submix.spa",
    "subref.spa",
    "unlubed.spa",
    ".SPA",
    "absorb.spa",
    "Acetominophen Caffeine Acetylsalicylic acid.SPA",
    "advatrcor.SPA",
    "advatrref.SPA",
    "atrcor.spa",
    "baseline.spa",
    "blstline.spa",
    "Cyclohexane Contaminated - Low.SPA",
    "disper.spa",
)


AUTHORITIES = {
    "typical": ArchiveAuthority(
        filename="typical_spectrab.zip",
        size_bytes=630_710,
        sha256="71a9b25259c31942371ea31b580411684d449f8e644adfe92ec7cbc149b98ab0",
        members=TYPICAL_MEMBERS,
    ),
    "cyclohexane": ArchiveAuthority(
        filename="Cyclohexane Contaminated - Low.zip",
        size_bytes=38_981,
        sha256="06ff1f64778d944abca9506042c7a75760800354360e160bb53546862d44f44e",
        members=(
            "Cyclohexane Contaminated - Low.SPC",
            "Cyclohexane Contaminated - Low.CSV",
            "Cyclohexane Contaminated - Low.JDX",
            "Cyclohexane Contaminated - Low.SPA",
        ),
    ),
    "lubed": ArchiveAuthority(
        filename="lubed.zip",
        size_bytes=19_908,
        sha256="0e4cf6632c04ae5837e5bbd058aa5a7ccfb9992c9f143d920802993606ecd13f",
        members=("lubed.SPC", "lubed.CSV", "lubed.JDX", "lubed.spa"),
    ),
    "unlubed": ArchiveAuthority(
        filename="unlubed.zip",
        size_bytes=19_860,
        sha256="5f6ef9efb7548e65fc1e4e570a4a33a1085ab26c31945d7c57655cfe60b46e11",
        members=("unlubed.SPC", "unlubed.CSV", "unlubed.JDX", "unlubed.spa"),
    ),
    "reference": ArchiveAuthority(
        filename="Acetominophen Caffeine Acetylsalicylic acid.zip",
        size_bytes=101_561,
        sha256="412daeb0790a14404fd69927f0fda9ff911c883e5917370b406dca61a500ce5a",
        members=(
            "Acetominophen Caffeine Acetylsalicylic acid.CSV",
            "Acetominophen Caffeine Acetylsalicylic acid.SPC",
            "Acetominophen Caffeine Acetylsalicylic acid.SPA",
            "Acetominophen Caffeine Acetylsalicylic acid.JDX",
        ),
    ),
}

RESAVED_SPA_AUTHORITIES = {
    "lubed": {
        "filename": "lubed_apex_resaved_no_transform.SPA",
        "size_bytes": 4652,
        "sha256": "a046da1f975e403624111f91ffd4f80663eec860c621dff50cf850f27f53383b",
    },
    "unlubed": {
        "filename": "unlubed_apex_resaved_no_transform.SPA",
        "size_bytes": 4652,
        "sha256": "241c5d2b9f8ddbba2d0ef743e5ff53e0cb1cc6618406e1f4bfdd86449879d7cf",
    },
}

INSTRUMENT_OBSERVATION = {
    "observed_on": "2026-08-28",
    "software": "OMNIC 9.16.233",
    "driver_version": "9.16.233",
    "instrument": "Nicolet Apex",
    "firmware_version": "1.03",
    "lubed_unlubed": {
        "displayed_y_quantity": "Transmittance",
        "number_of_points": 871,
        "x_axis": "Wavenumbers (cm-1)",
        "displayed_range_cm-1": [900.0, 4000.0],
        "nothing_displayed_below_cm-1": 900.0,
        "processing_history_final_format": "Single Beam",
        "processing_history_blank": {
            "from_cm-1": 900.4581,
            "to_cm-1": 398.6646,
        },
    },
    "acetominophen_caffeine_acetylsalicylic_acid": {
        "displayed_y_quantity": "%Reflectance",
        "observed_y_range_approx": [60.0, 101.0],
        "jdx_export_scale_choice_available": False,
    },
}

PARSER_BY_SUFFIX = {
    ".spa": "spectrasherpa.omnic",
    ".csv": "spectrasherpa.csv",
    ".jdx": "spectrasherpa.jcamp",
    ".spc": "spectrasherpa.spc",
}


@dataclass(frozen=True)
class ParsedSpectrum:
    axis: np.ndarray
    signal: np.ndarray
    title: str
    units: str | None
    quantity: str | None
    metadata: dict[str, Any]
    warning_count: int


def _read_bounded_regular(path: Path) -> bytes:
    try:
        observed = path.lstat()
    except FileNotFoundError as exc:
        raise QualificationError(f"required archive is unavailable: {path.name}") from exc
    if stat.S_ISLNK(observed.st_mode) or not stat.S_ISREG(observed.st_mode):
        raise QualificationError(f"archive must be a regular non-link file: {path.name}")
    if observed.st_size > MAX_ARCHIVE_BYTES:
        raise QualificationError(f"archive exceeds the {MAX_ARCHIVE_BYTES}-byte limit: {path.name}")
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise QualificationError(f"archive could not be opened without following links: {path.name}") from exc
    try:
        admitted = os.fstat(descriptor)
        if not stat.S_ISREG(admitted.st_mode) or admitted.st_size != observed.st_size:
            raise QualificationError(f"archive identity changed during admission: {path.name}")
        payload = bytearray()
        while len(payload) <= MAX_ARCHIVE_BYTES:
            chunk = os.read(descriptor, min(64 * 1024, MAX_ARCHIVE_BYTES + 1 - len(payload)))
            if not chunk:
                break
            payload.extend(chunk)
    finally:
        os.close(descriptor)
    if len(payload) != observed.st_size or len(payload) > MAX_ARCHIVE_BYTES:
        raise QualificationError(f"archive changed or exceeded its bound during admission: {path.name}")
    return bytes(payload)


def _admit_archive(input_dir: Path, authority: ArchiveAuthority) -> dict[str, bytes]:
    payload = _read_bounded_regular(input_dir / authority.filename)
    if len(payload) != authority.size_bytes or hashlib.sha256(payload).hexdigest() != authority.sha256:
        raise QualificationError(f"archive size or SHA-256 differs from authority: {authority.filename}")
    try:
        with zipfile.ZipFile(io.BytesIO(payload), "r") as archive:
            members = archive.infolist()
            if len(members) != len(authority.members):
                raise QualificationError(f"archive member census differs from authority: {authority.filename}")
            admitted: dict[str, bytes] = {}
            total = 0
            for member in members:
                pure = PurePosixPath(member.filename)
                mode = (member.external_attr >> 16) & 0o170000
                if pure.name != member.filename or member.is_dir() or member.flag_bits & 0x1 or mode == stat.S_IFLNK:
                    raise QualificationError(f"archive contains an unsafe member: {member.filename!r}")
                if member.file_size > MAX_MEMBER_BYTES:
                    raise QualificationError(f"archive member exceeds the source bound: {member.filename!r}")
                total += member.file_size
                if total > MAX_TOTAL_MEMBER_BYTES:
                    raise QualificationError("archive decoded members exceed the aggregate bound")
                if member.filename in admitted:
                    raise QualificationError(f"archive contains a duplicate member: {member.filename!r}")
                raw = archive.read(member)
                if len(raw) != member.file_size:
                    raise QualificationError(f"archive member size changed during decode: {member.filename!r}")
                admitted[member.filename] = raw
    except (OSError, zipfile.BadZipFile, RuntimeError) as exc:
        raise QualificationError(f"archive is not an admitted ZIP: {authority.filename}") from exc
    if tuple(admitted) != authority.members:
        raise QualificationError(f"archive member names or order differ from authority: {authority.filename}")
    return admitted


def _suffix(name: str) -> str:
    # pathlib intentionally treats the historical literal filename '.SPA' as
    # suffixless; the product's shared extension authority admits it as SPA.
    return ".spa" if name.casefold() == ".spa" else PurePosixPath(name).suffix.casefold()


def _parse_member(directory: Path, name: str, raw: bytes) -> ParsedSpectrum:
    suffix = _suffix(name)
    parser_id = PARSER_BY_SUFFIX.get(suffix)
    if parser_id is None:
        raise QualificationError(f"stress member has an unsupported extension: {name!r}")
    path = directory / name
    path.write_bytes(raw)
    options = {"csv_layout": "headerless_two_column_spectrum"} if suffix == ".csv" else None
    result = ingest(path, limits=LIMITS, parser_options=options)
    if result.parser_id != parser_id or len(result.assets) != 1:
        raise QualificationError(f"stress member did not produce one expected native asset: {name!r}")
    if len(result.source_members) != 1:
        raise QualificationError(f"stress member produced an ambiguous source census: {name!r}")
    member = result.source_members[0]
    if member.size_bytes != len(raw) or member.sha256 != hashlib.sha256(raw).hexdigest():
        raise QualificationError(f"parser source custody differs from admitted member: {name!r}")
    dataset = result.assets[0].dataset
    if dataset.shape[0] != 1 or dataset.feature_axis is None or dataset.feature_axis.values is None:
        raise QualificationError(f"stress member is not one explicit-axis spectrum: {name!r}")
    axis = np.asarray(dataset.feature_axis.values, dtype=np.float64)
    signal = np.asarray(dataset.X[0], dtype=np.float64)
    if axis.shape != signal.shape or not np.all(np.isfinite(axis)) or np.any(np.isinf(signal)):
        raise QualificationError(f"stress member has unsafe numeric output: {name!r}")
    missing = int(np.count_nonzero(np.isnan(signal)))
    if len(result.warnings) != (1 if missing else 0):
        raise QualificationError(f"stress member warning count does not match its missingness: {name!r}")
    if missing and ("Missing data preserved" not in result.warnings[0] or "does not impute" not in result.warnings[0]):
        raise QualificationError(f"stress member missingness is not explicitly disclosed: {name!r}")
    order = np.argsort(axis, kind="stable")
    return ParsedSpectrum(
        axis=axis[order],
        signal=signal[order],
        title=str(dataset.title or ""),
        units=dataset.units,
        quantity=dataset.domain.data_quantity,
        metadata=dict(result.raw_metadata),
        warning_count=len(result.warnings),
    )


def _max_difference(left: np.ndarray, right: np.ndarray) -> float:
    if left.shape != right.shape:
        raise QualificationError("same-source comparison shapes differ")
    return float(np.max(np.abs(left - right)))


def _correlation(left: np.ndarray, right: np.ndarray) -> float:
    if left.shape != right.shape:
        raise QualificationError("same-source correlation shapes differ")
    return float(np.corrcoef(left, right)[0, 1])


def _direct_quartet(parsed: dict[str, ParsedSpectrum]) -> dict[str, Any]:
    spa = parsed[".spa"]
    if spa.axis.size != 1738 or any(item.axis.size != 1738 for item in parsed.values()):
        raise QualificationError("Cyclohexane quartet point count differs from authority")
    comparisons: dict[str, Any] = {}
    for suffix in (".csv", ".jdx", ".spc"):
        item = parsed[suffix]
        comparisons[suffix.removeprefix(".")] = {
            "axis_max_abs_difference_cm-1": _max_difference(spa.axis, item.axis),
            "signal_max_abs_difference": _max_difference(spa.signal, item.signal),
            "signal_correlation": _correlation(spa.signal, item.signal),
        }
    if comparisons["csv"]["axis_max_abs_difference_cm-1"] > 0.0007:
        raise QualificationError("Cyclohexane CSV axis exceeds text export precision")
    if comparisons["csv"]["signal_max_abs_difference"] > 5e-7:
        raise QualificationError("Cyclohexane CSV signal exceeds text export precision")
    if comparisons["jdx"]["axis_max_abs_difference_cm-1"] > 3e-7:
        raise QualificationError("Cyclohexane JDX axis exceeds fixed-grid precision")
    if comparisons["jdx"]["signal_max_abs_difference"] > 3e-7:
        raise QualificationError("Cyclohexane JDX signal exceeds text export precision")
    if comparisons["spc"]["axis_max_abs_difference_cm-1"] != 0.0:
        raise QualificationError("Cyclohexane SPC axis is not exact")
    if comparisons["spc"]["signal_max_abs_difference"] > 4e-9:
        raise QualificationError("Cyclohexane SPC signal exceeds binary export precision")
    if min(item["signal_correlation"] for item in comparisons.values()) < 0.999999999999:
        raise QualificationError("Cyclohexane same-source correlation differs from authority")
    return comparisons


def _blanked_transmittance(name: str, parsed: dict[str, ParsedSpectrum]) -> dict[str, Any]:
    spa, csv, jdx, spc = (parsed[suffix] for suffix in (".spa", ".csv", ".jdx", ".spc"))
    if spa.quantity != "Transmittance" or spa.axis.size != 871 or csv.axis.size != 871:
        raise QualificationError(f"{name} SPA/CSV transmittance identity differs from authority")
    spa_missing = np.isnan(spa.signal)
    csv_missing = np.isnan(csv.signal)
    if np.count_nonzero(spa_missing) != 66 or not np.array_equal(spa_missing, csv_missing):
        raise QualificationError(f"{name} SPA/CSV missing-range projection differs from authority")
    measured = ~spa_missing
    if jdx.axis.size != 805 or not np.allclose(spa.axis[measured], jdx.axis, rtol=0.0, atol=1e-5):
        raise QualificationError(f"{name} JDX did not trim to the exact measured feature set")
    csv_axis = _max_difference(spa.axis, csv.axis)
    csv_signal = _max_difference(spa.signal[measured], csv.signal[measured])
    jdx_axis = _max_difference(spa.axis[measured], jdx.axis)
    jdx_signal = _max_difference(spa.signal[measured], jdx.signal)
    if csv_axis > 0.0007 or csv_signal > 5e-7 or jdx_axis > 1e-5 or jdx_signal > 8e-8:
        raise QualificationError(f"{name} measured export values exceed precision boundaries")
    if not np.array_equal(spa.axis, spc.axis):
        raise QualificationError(f"{name} SPC axis is not exact")
    measured_indices = np.flatnonzero(measured)
    if measured_indices[0] != 66 or measured_indices[-1] != 870:
        raise QualificationError(f"{name} blanked range is not one leading sorted-axis region")
    # The SPC export writes a zero endpoint, preserves the remaining measured
    # values, and repeats the first measured low-wavenumber value into the
    # region that SPA/CSV explicitly mark missing. Preserve and disclose this
    # source behavior; do not reverse-engineer it into fabricated missingness.
    spc_measured_error = _max_difference(spa.signal[measured][:-1], spc.signal[measured][:-1])
    repeated = np.unique(spc.signal[spa_missing])
    if spc.signal[measured][-1] != 0.0 or spc_measured_error > 1e-9:
        raise QualificationError(f"{name} SPC measured-region convention differs from authority")
    if repeated.size != 1 or abs(float(repeated[0]) - float(spa.signal[measured][0])) > 1e-9:
        raise QualificationError(f"{name} SPC blank-range fill convention differs from authority")
    try:
        _normalize_dispatch(spa.signal.reshape(1, -1), method="snv")
    except ValueError as exc:
        if "preprocess.normalize requires finite input values" not in str(exc):
            raise QualificationError(f"{name} missing-input normalization refusal is off-contract") from exc
    else:
        raise QualificationError(f"{name} missing-input normalization did not refuse")
    clip_mask, _clip_diagnostics = _clip_range_dispatch(spa.axis, minimum=900.0, maximum=4005.0)
    clipped = spa.signal[clip_mask].reshape(1, -1)
    if clipped.shape != (1, 805) or not np.isfinite(clipped).all():
        raise QualificationError(f"{name} declared measured-range clip did not remove exactly the processing blank")
    normalized = _normalize_dispatch(clipped, method="snv")
    if normalized.shape != clipped.shape or not np.isfinite(normalized).all():
        raise QualificationError(f"{name} measured-range normalization did not remain finite")
    return {
        "point_counts": {"spa": 871, "csv": 871, "jdx": 805, "spc": 871},
        "spa_csv_missing_value_count": 66,
        "jdx_behavior": "blanked_low_wavenumber_region_omitted",
        "spc_behavior": "first_endpoint_zero_and_blanked_region_filled_with_nearest_measured_value",
        "preprocessing_policy": {
            "uncropped_snv": "refused_missing_input",
            "remediation": "preprocess.clip_range_900_to_4005_cm-1",
            "clipped_feature_count": 805,
            "clipped_snv": "finite",
        },
        "spa_csv_axis_max_abs_difference_cm-1": csv_axis,
        "spa_csv_measured_signal_max_abs_difference": csv_signal,
        "spa_jdx_axis_max_abs_difference_cm-1": jdx_axis,
        "spa_jdx_measured_signal_max_abs_difference": jdx_signal,
        "spa_spc_measured_signal_max_abs_difference_excluding_export_endpoint": spc_measured_error,
        "minimum_measured_signal_correlation": min(
            _correlation(spa.signal[measured], csv.signal[measured]),
            _correlation(spa.signal[measured], jdx.signal),
            _correlation(spa.signal[measured][:-1], spc.signal[measured][:-1]),
        ),
    }


def _reflectance_reference(parsed: dict[str, ParsedSpectrum]) -> dict[str, Any]:
    spa, csv, jdx, spc = (parsed[suffix] for suffix in (".spa", ".csv", ".jdx", ".spc"))
    if spa.quantity != "Reflectance" or spa.units != "percent" or spa.axis.size != 1868:
        raise QualificationError("reference SPA reflectance identity differs from authority")
    if spc.axis.size != 1868 or _max_difference(spa.axis, spc.axis) != 0.0:
        raise QualificationError("reference SPC axis differs from SPA")
    if _max_difference(spa.signal, spc.signal) != 0.0:
        raise QualificationError("reference SPC signal differs from SPA")
    if csv.axis.size != 1869 or not np.isclose(csv.signal[-1], 0.0, rtol=0.0, atol=5e-12):
        raise QualificationError("reference CSV synthetic endpoint differs from authority")
    # Sorted CSV has one synthetic low-axis zero endpoint; the retained source
    # endpoint is the other 1,868 values.
    csv_axis = _max_difference(spa.axis, csv.axis[:-1])
    csv_signal = _max_difference(spa.signal, csv.signal[:-1])
    if csv_axis > 0.0008 or csv_signal > 5e-5:
        raise QualificationError("reference CSV exceeds text export precision")
    scaled_jdx = jdx.signal * 100.0
    jdx_axis = _max_difference(spa.axis, jdx.axis)
    scaled_signal = _max_difference(spa.signal, scaled_jdx)
    ratio = spa.signal / jdx.signal
    if jdx_axis > 1e-7 or scaled_signal > 4e-6:
        raise QualificationError("reference JDX scaled curve exceeds text export precision")
    if float(np.max(np.abs(ratio - 100.0))) > 6e-6 or _correlation(spa.signal, jdx.signal) < 0.999999999999:
        raise QualificationError("reference JDX does not preserve one constant-scale curve")
    return {
        "point_counts": {"spa": 1868, "csv": 1869, "jdx": 1868, "spc": 1868},
        "spa_quantity": "Reflectance",
        "spa_units": "percent",
        "csv_behavior": "one_synthetic_zero_endpoint",
        "jdx_behavior": "fractional_curve_with_arbitrary_units_metadata",
        "jdx_comparison_scale_only": 100.0,
        "spa_csv_axis_max_abs_difference_cm-1": csv_axis,
        "spa_csv_percent_reflectance_max_abs_difference": csv_signal,
        "spa_jdx_axis_max_abs_difference_cm-1": jdx_axis,
        "spa_vs_scaled_jdx_max_abs_difference": scaled_signal,
        "spa_jdx_curve_correlation": _correlation(spa.signal, jdx.signal),
        "spa_spc_axis_max_abs_difference_cm-1": 0.0,
        "spa_spc_signal_max_abs_difference": 0.0,
    }


def qualify(input_dir: Path) -> dict[str, Any]:
    if "spectrochempy" in sys.modules:
        raise QualificationError("SpectroChemPy was loaded before native stress qualification")
    archives = {key: _admit_archive(input_dir, authority) for key, authority in AUTHORITIES.items()}
    resaved = {
        key: _read_bounded_regular(input_dir / authority["filename"])
        for key, authority in RESAVED_SPA_AUTHORITIES.items()
    }
    for key, raw in resaved.items():
        authority = RESAVED_SPA_AUTHORITIES[key]
        if len(raw) != authority["size_bytes"] or hashlib.sha256(raw).hexdigest() != authority["sha256"]:
            raise QualificationError(f"instrument-resaved SPA size or SHA-256 differs from authority: {key}")

    parsed_archives: dict[str, dict[str, ParsedSpectrum]] = {}
    parsed_resaves: dict[str, ParsedSpectrum] = {}
    with tempfile.TemporaryDirectory(prefix="spectrasherpa-avatar-apex-") as temporary:
        root = Path(temporary)
        for archive_key, members in archives.items():
            directory = root / archive_key
            directory.mkdir()
            parsed_archives[archive_key] = {name: _parse_member(directory, name, raw) for name, raw in members.items()}
        resaved_directory = root / "instrument-resaved"
        resaved_directory.mkdir()
        parsed_resaves = {
            key: _parse_member(resaved_directory, RESAVED_SPA_AUTHORITIES[key]["filename"], raw)
            for key, raw in resaved.items()
        }

    typical = parsed_archives["typical"]
    if len(typical) != 34 or any(_suffix(name) != ".spa" for name in typical):
        raise QualificationError("typical SPA census differs from authority")
    quantities: dict[str, int] = {}
    missing_sources = 0
    for item in typical.values():
        quantity = item.quantity or "untyped"
        quantities[quantity] = quantities.get(quantity, 0) + 1
        missing_sources += int(bool(np.any(np.isnan(item.signal))))
    if missing_sources != 2 or typical[".SPA"].axis.size != 7468:
        raise QualificationError("typical SPA missingness or literal-name projection differs from authority")

    def quartet(key: str) -> dict[str, ParsedSpectrum]:
        return {_suffix(name): item for name, item in parsed_archives[key].items()}

    cyclo = quartet("cyclohexane")
    cyclo_metadata = cyclo[".spa"].metadata
    if not cyclo_metadata.get("comments") or not cyclo_metadata.get("processing_history"):
        raise QualificationError("Cyclohexane SPA comments or processing history were not retained")
    linked = cyclo_metadata.get("embedded_linked_sources")
    if not isinstance(linked, list) or len(linked) != 1 or linked[0].get("size_bytes") != 9820:
        raise QualificationError("Cyclohexane linked-source identity was not retained")

    reference = quartet("reference")
    reference_metadata = reference[".spa"].metadata
    if not reference_metadata.get("processing_history") or not reference_metadata.get("experiment_information"):
        raise QualificationError("reference SPA processing or experiment metadata were not retained")

    for key in ("lubed", "unlubed"):
        original = quartet(key)[".spa"]
        replay = parsed_resaves[key]
        if not np.array_equal(original.axis, replay.axis) or not np.array_equal(
            original.signal, replay.signal, equal_nan=True
        ):
            raise QualificationError(f"instrument-resaved {key} SPA changed its scientific projection")
        history = replay.metadata.get("processing_history")
        if (
            replay.quantity != "Transmittance"
            or replay.axis.size != 871
            or not history
            or "Final format:\tSingle Beam" not in history[0]
            or "From 900.4581 to 398.6646" not in history[0]
        ):
            raise QualificationError(f"instrument-resaved {key} SPA does not match the operator observation")

    if "spectrochempy" in sys.modules:
        raise QualificationError("SpectroChemPy was loaded during native stress qualification")
    return {
        "schema_version": SCHEMA_VERSION,
        "status": "pass",
        "claim": (
            "All 50 members in the five exact private Nicolet archives and both instrument-resaved SPA sources "
            "are admitted by bounded native readers. "
            "The 34-file SPA stress set parses completely; same-source quartet differences are classified as "
            "text precision, explicit missing-region export policy, constant reflectance scaling, or metadata loss. "
            "For blanked sources, signal parity is claimed only over the measured finite region: SPA/CSV preserve "
            "the declared missing region, JDX omits it, and SPC fills it under the disclosed export convention."
        ),
        "archives": {
            key: {
                "filename": authority.filename,
                "size_bytes": authority.size_bytes,
                "sha256": authority.sha256,
                "member_count": len(authority.members),
            }
            for key, authority in AUTHORITIES.items()
        },
        "instrument_resaved_spa": RESAVED_SPA_AUTHORITIES,
        "instrument_observation": INSTRUMENT_OBSERVATION,
        "summary": {
            "archive_count": 5,
            "parsed_member_count": sum(len(items) for items in archives.values()),
            "instrument_resaved_spa_count": len(parsed_resaves),
            "typical_spa_count": len(typical),
            "typical_spa_quantity_census": dict(sorted(quantities.items())),
            "typical_spa_sources_with_preserved_missing_values": missing_sources,
            "literal_dot_spa_filename_parsed": True,
            "spectrochempy_loaded": False,
        },
        "counterparts": {
            "cyclohexane": {
                "comparison": _direct_quartet(cyclo),
                "spa_metadata_retained": ["comments", "processing_history", "embedded_linked_sources"],
            },
            "lubed": _blanked_transmittance("lubed", quartet("lubed")),
            "unlubed": _blanked_transmittance("unlubed", quartet("unlubed")),
            "acetominophen_caffeine_acetylsalicylic_acid": {
                **_reflectance_reference(reference),
                "spa_metadata_retained": ["processing_history", "experiment_information"],
            },
        },
        "nonclaims": [
            "Thermo vendor-reader source-code equivalence",
            "scientific equivalence of missing, zero-filled, and trimmed regions outside measured values",
            "a physical percent-reflectance unit for JDX that labels its ordinate as arbitrary units",
            "instrument authenticity or acquisition correctness beyond the operator record",
            "redistribution of the private source bytes",
            "general parser compatibility outside the qualified native format grammars and CSV profiles",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-dir", type=Path, required=True)
    args = parser.parse_args()
    try:
        receipt = qualify(args.input_dir)
    except (QualificationError, ValueError, OSError) as exc:
        print(f"Avatar Apex parser qualification failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(receipt, indent=2, sort_keys=True, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
