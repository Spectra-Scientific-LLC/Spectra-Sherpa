#!/usr/bin/env python3
"""Qualify the retained private JF SPA/CSV/JDX same-source triplets.

The command emits only a data-free JSON receipt. It binds the three private
archives by size and SHA-256, admits their exact six-member inventories under
bounded ZIP and native-parser limits, and compares the scientific projections
without publishing spectra or private paths.
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

from spectra_sherpa.io import ParserLimits, ingest

SCHEMA_VERSION = "spectrasherpa-avatar-jf-parser-triplet-qualification/1"
MAX_ARCHIVE_BYTES = 2 * 1024 * 1024
MAX_MEMBER_BYTES = 256 * 1024
MAX_TOTAL_MEMBER_BYTES = 2 * 1024 * 1024
EXPECTED_NUMBERS = tuple(f"{value:04d}" for value in range(3, 9))
EXPECTED_IDENTITIES = {
    "0003": "JF2_ESL",
    "0004": "JF1_ELF",
    "0005": "JF1_ELS",
    "0006": "JF1_MSL",
    "0007": "JF1_PL",
    "0008": "JF1_NRL",
}
LIMITS = ParserLimits(
    max_source_bytes=MAX_MEMBER_BYTES,
    max_decoded_elements=20_000,
    # The shared text parser charges a conservative pandas working-set
    # estimate before allocation; this is a ceiling, not observed output size.
    max_decoded_bytes=128 * 1024 * 1024,
    max_blocks=64,
    max_metadata_bytes=512 * 1024,
    max_probe_bytes=64 * 1024,
)


class QualificationError(ValueError):
    """One closed private-corpus qualification invariant failed."""


@dataclass(frozen=True)
class ArchiveAuthority:
    filename: str
    size_bytes: int
    sha256: str
    suffix: str
    parser_id: str
    parser_options: dict[str, str] | None = None


AUTHORITIES = {
    "spa": ArchiveAuthority(
        filename="EO_Lavender_001_JF.zip",
        size_bytes=48_457,
        sha256="84fd799647a4a69782a33fda961b5a09119a5565225d9e11be1d08498aed8868",
        suffix=".spa",
        parser_id="spectrasherpa.omnic",
    ),
    "csv": ArchiveAuthority(
        filename="EO_Lavender_JF-CSV.zip",
        size_bytes=100_592,
        sha256="438ab82b33463fcc0fcc690fe2830f9a94a84cedb955e91ad5ca2acdab1e60c1",
        suffix=".csv",
        parser_id="spectrasherpa.csv",
        parser_options={"csv_layout": "headerless_two_column_spectrum"},
    ),
    "jdx": ArchiveAuthority(
        filename="EO_Lavender_JF_JDX.zip",
        size_bytes=62_480,
        sha256="b1cbb0d1eded802fcb99dc7184e8fc3c5163cf2cf93648bf2a45bd6018951069",
        suffix=".jdx",
        parser_id="spectrasherpa.jcamp",
    ),
}


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


def _number_from_name(name: str, *, suffix: str) -> str:
    pure = PurePosixPath(name)
    if pure.name != name or pure.suffix.casefold() != suffix:
        raise QualificationError(f"archive member has an unexpected path or extension: {name!r}")
    number = pure.stem.rsplit("_", 1)[-1]
    if number not in EXPECTED_NUMBERS:
        raise QualificationError(f"archive member has an unexpected sequence number: {name!r}")
    return number


def _admit_archive(input_dir: Path, authority: ArchiveAuthority) -> dict[str, bytes]:
    payload = _read_bounded_regular(input_dir / authority.filename)
    if len(payload) != authority.size_bytes or hashlib.sha256(payload).hexdigest() != authority.sha256:
        raise QualificationError(f"archive size or SHA-256 differs from authority: {authority.filename}")

    try:
        with zipfile.ZipFile(io.BytesIO(payload), "r") as archive:
            members = archive.infolist()
            if len(members) != len(EXPECTED_NUMBERS):
                raise QualificationError(f"archive member census differs from authority: {authority.filename}")
            total = 0
            admitted: dict[str, bytes] = {}
            for member in members:
                if member.is_dir() or member.flag_bits & 0x1:
                    raise QualificationError(f"archive contains a directory or encrypted member: {member.filename!r}")
                mode = (member.external_attr >> 16) & 0o170000
                if mode == stat.S_IFLNK:
                    raise QualificationError(f"archive contains a link member: {member.filename!r}")
                if member.file_size > MAX_MEMBER_BYTES:
                    raise QualificationError(f"archive member exceeds the source bound: {member.filename!r}")
                total += member.file_size
                if total > MAX_TOTAL_MEMBER_BYTES:
                    raise QualificationError("archive decoded members exceed the aggregate bound")
                number = _number_from_name(member.filename, suffix=authority.suffix)
                if number in admitted:
                    raise QualificationError(f"archive contains a duplicate sample number: {number}")
                raw = archive.read(member)
                if len(raw) != member.file_size:
                    raise QualificationError(f"archive member size changed during decode: {member.filename!r}")
                admitted[number] = raw
    except (OSError, zipfile.BadZipFile, RuntimeError) as exc:
        raise QualificationError(f"archive is not an admitted ZIP: {authority.filename}") from exc
    if tuple(sorted(admitted)) != EXPECTED_NUMBERS:
        raise QualificationError(f"archive does not contain the exact six sample numbers: {authority.filename}")
    return admitted


def _parse_member(
    directory: Path,
    *,
    number: str,
    raw: bytes,
    authority: ArchiveAuthority,
) -> tuple[np.ndarray, np.ndarray, str]:
    path = directory / f"sample-{number}{authority.suffix}"
    path.write_bytes(raw)
    result = ingest(path, limits=LIMITS, parser_options=authority.parser_options)
    if result.parser_id != authority.parser_id or len(result.assets) != 1 or result.warnings:
        raise QualificationError(f"{authority.suffix} sample {number} did not produce one warning-free expected asset")
    member = result.source_members
    if len(member) != 1 or member[0].size_bytes != len(raw) or member[0].sha256 != hashlib.sha256(raw).hexdigest():
        raise QualificationError(f"parser source custody differs from admitted member: {number}{authority.suffix}")
    dataset = result.assets[0].dataset
    if dataset.shape[0] != 1 or dataset.feature_axis is None or dataset.feature_axis.values is None:
        raise QualificationError(f"{authority.suffix} sample {number} is not one explicit-axis spectrum")
    axis = np.asarray(dataset.feature_axis.values, dtype=np.float64)
    signal = np.asarray(dataset.X[0], dtype=np.float64)
    if axis.shape != signal.shape or not np.all(np.isfinite(axis)) or not np.all(np.isfinite(signal)):
        raise QualificationError(f"{authority.suffix} sample {number} has unsafe numeric output")
    order = np.argsort(axis, kind="stable")
    return axis[order], signal[order], str(dataset.title or "")


def qualify(input_dir: Path) -> dict[str, Any]:
    if "spectrochempy" in sys.modules:
        raise QualificationError("SpectroChemPy was loaded before native triplet qualification")
    archives = {kind: _admit_archive(input_dir, authority) for kind, authority in AUTHORITIES.items()}
    observations: list[dict[str, Any]] = []
    csv_axis_max = 0.0
    csv_signal_max = 0.0
    jdx_axis_max = 0.0
    jdx_signal_max = 0.0
    minimum_correlation = 1.0

    with tempfile.TemporaryDirectory(prefix="spectrasherpa-avatar-jf-") as temporary:
        root = Path(temporary)
        for number in EXPECTED_NUMBERS:
            parsed = {
                kind: _parse_member(root, number=number, raw=archives[kind][number], authority=authority)
                for kind, authority in AUTHORITIES.items()
            }
            spa_axis, spa_signal, spa_title = parsed["spa"]
            csv_axis, csv_signal, _csv_title = parsed["csv"]
            jdx_axis, jdx_signal, jdx_title = parsed["jdx"]
            if spa_axis.size != 1868 or jdx_axis.size != 1868 or csv_axis.size != 1869:
                raise QualificationError(f"sample {number} shape differs from the retained triplet authority")
            spa_identity = spa_title.split(":", 1)[0].strip()
            if spa_identity != EXPECTED_IDENTITIES[number] or jdx_title != EXPECTED_IDENTITIES[number]:
                raise QualificationError(f"sample {number} embedded identity differs across retained sources")
            if not np.isclose(csv_axis[-1], 4001.766, rtol=0.0, atol=5e-7) or not np.isclose(
                csv_signal[-1], 0.0, rtol=0.0, atol=5e-12
            ):
                raise QualificationError(f"sample {number} CSV synthetic tail point changed")

            csv_axis_difference = float(np.max(np.abs(spa_axis - csv_axis[:-1])))
            csv_signal_difference = float(np.max(np.abs(spa_signal - csv_signal[:-1])))
            jdx_axis_difference = float(np.max(np.abs(spa_axis - jdx_axis)))
            jdx_signal_difference = float(np.max(np.abs(spa_signal - jdx_signal)))
            correlations = (
                float(np.corrcoef(spa_signal, csv_signal[:-1])[0, 1]),
                float(np.corrcoef(spa_signal, jdx_signal)[0, 1]),
            )
            csv_axis_max = max(csv_axis_max, csv_axis_difference)
            csv_signal_max = max(csv_signal_max, csv_signal_difference)
            jdx_axis_max = max(jdx_axis_max, jdx_axis_difference)
            jdx_signal_max = max(jdx_signal_max, jdx_signal_difference)
            minimum_correlation = min(minimum_correlation, *correlations)
            observations.append(
                {
                    "number": number,
                    "identity": EXPECTED_IDENTITIES[number],
                    "spa_shape": [1, int(spa_axis.size)],
                    "csv_shape": [1, int(csv_axis.size)],
                    "jdx_shape": [1, int(jdx_axis.size)],
                    "csv_extra_tail": {"x": float(csv_axis[-1]), "absorbance": float(csv_signal[-1])},
                    "spa_csv_axis_max_abs_difference_cm-1": csv_axis_difference,
                    "spa_csv_absorbance_max_abs_difference": csv_signal_difference,
                    "spa_jdx_axis_max_abs_difference_cm-1": jdx_axis_difference,
                    "spa_jdx_absorbance_max_abs_difference": jdx_signal_difference,
                    "minimum_absorbance_correlation": min(correlations),
                }
            )

    if csv_axis_max > 0.001 or csv_signal_max > 1e-7:
        raise QualificationError("CSV triplet projection exceeds the retained export-precision boundary")
    if jdx_axis_max > 5e-7 or jdx_signal_max > 1e-8:
        raise QualificationError("JDX triplet projection exceeds the corrected fixed-grid boundary")
    if minimum_correlation < 0.999999999999:
        raise QualificationError("triplet absorbance correlation is below the retained boundary")
    if "spectrochempy" in sys.modules:
        raise QualificationError("SpectroChemPy was loaded during native triplet qualification")

    return {
        "schema_version": SCHEMA_VERSION,
        "status": "pass",
        "claim": (
            "The exact six retained JF SPA/CSV/JDX triplets reproduce the same absorbance spectra under the "
            "bounded native parsers. CSV preserves one disclosed OMNIC synthetic zero tail point; corrected "
            "JCAMP fixed-grid axes agree with SPA within the retained export precision."
        ),
        "archives": {
            kind: {
                "filename": authority.filename,
                "size_bytes": authority.size_bytes,
                "sha256": authority.sha256,
                "members": len(EXPECTED_NUMBERS),
            }
            for kind, authority in AUTHORITIES.items()
        },
        "samples": observations,
        "summary": {
            "sample_count": len(observations),
            "spa_csv_axis_max_abs_difference_cm-1": csv_axis_max,
            "spa_csv_absorbance_max_abs_difference": csv_signal_max,
            "spa_jdx_axis_max_abs_difference_cm-1": jdx_axis_max,
            "spa_jdx_absorbance_max_abs_difference": jdx_signal_max,
            "minimum_absorbance_correlation": minimum_correlation,
            "spectrochempy_loaded": False,
        },
        "nonclaims": [
            "general parser compatibility outside the retained qualified formats and profiles",
            "Thermo vendor-reader source-code equivalence",
            "instrument authenticity or acquisition correctness beyond the operator-attested record",
            "redistribution of the private JF source bytes",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-dir", type=Path, required=True)
    args = parser.parse_args()
    try:
        receipt = qualify(args.input_dir)
    except (QualificationError, ValueError, OSError) as exc:
        print(f"Avatar JF parser qualification failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(receipt, indent=2, sort_keys=True, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
