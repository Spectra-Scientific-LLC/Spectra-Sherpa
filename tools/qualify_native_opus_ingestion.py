#!/usr/bin/env python3
"""Build and verify the checked native OPUS ingestion qualification.

The qualification deliberately separates scientific execution from corpus
redistribution. Six licensed files are read from the repository; three
additional exact-hash references are read from a caller-owned ephemeral
directory. No external source bytes or private filesystem paths enter the
public report.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import os
import platform
import stat
import subprocess
import sys
from pathlib import Path, PurePosixPath
from typing import Any

import numpy as np

from spectra_sherpa.core.file_io import open_regular_readonly
from spectra_sherpa.io import ParserLimits, ingest
from spectra_sherpa.io import registry as ingestion_registry

SCHEMA_VERSION = "spectrasherpa-native-opus-qualification/1"
CONFORMANCE_SCHEMA = "spectrasherpa-native-opus-conformance/3"
CHECKED_REPORT_SHA256 = "0eeabdf7f3d277f2e1636cc8b1b788bccf34a106bc4b2aed3528f0a541b3e20e"
QUALIFIED_IMPLEMENTATION_COMMIT = "d64895046b7392753ed7fd4f9cd499d3f9c668d9"
QUALIFIED_RUNTIME_SHA256 = "a3234e9f9cc522bb44719f1b91971c5c1878b78b610d77e9ce366298818b4f74"
CHUNK_BYTES = 1024 * 1024
MAX_SOURCE_BYTES = 64 * 1024 * 1024
MAX_REPORT_BYTES = 256 * 1024
EXTERNAL_FIXTURE_COUNT = 3
BUNDLED_FIXTURE_COUNT = 6
CLAIM_BOUNDARY = (
    "Exact native ingestion of the nine named OPUS acquisitions and the retained format variants in the "
    "checked conformance authority; SpectroChemPy is not an ingestion or parser runtime dependency."
)
NONCLAIMS = [
    "general Bruker OPUS compatibility outside the retained format variants",
    "Bruker vendor-export or instrument-software parity",
    "redistribution permission for the three external SpectroChemPy-data references",
    "paired-platform bit-exact repeatability",
    "replacement of SpectroChemPy for optional EFA, MCR-ALS, or SIMPLISMA algorithms",
    "completion of the broader all-reference C8/M4.20 qualification obligation",
]
EXPECTED_SOURCE_SIZES = {
    "opus-openspecy-polystyrene": 277_968,
    "opus-617262-1tp-c1-a5": 290_712,
    "opus-629266-1tp-a1-c1": 304_152,
    "opus-bf-lo-01-soil-cal": 36_576,
    "opus-mmp-2107-test1": 191_128,
    "opus-test-spectra": 72_032,
    "opus-reference-background": 34_328,
    "opus-sample-multiblock-0000": 65_688,
    "opus-sample-multiblock-0003": 65_688,
}
QUALIFICATION_LIMITS = ParserLimits(
    max_source_bytes=MAX_SOURCE_BYTES,
    max_decoded_elements=1_000_000,
    max_decoded_bytes=16 * 1024 * 1024,
    max_blocks=256,
    max_metadata_bytes=2 * 1024 * 1024,
    max_probe_bytes=64 * 1024,
)


class QualificationError(ValueError):
    """One checked OPUS qualification invariant failed."""


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise QualificationError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _read_json(path: Path, *, max_bytes: int = MAX_REPORT_BYTES) -> dict[str, Any]:
    payload = _read_bounded_regular(path, max_bytes=max_bytes)
    result = json.loads(payload.decode("utf-8"), object_pairs_hook=_reject_duplicate_keys)
    if not isinstance(result, dict):
        raise QualificationError("JSON authority must be an object")
    return result


def _canonical_bytes(value: object) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n").encode("utf-8")


def _digest_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _digest_json(value: object) -> str:
    return _digest_bytes(_canonical_bytes(value))


def _is_sha256(value: object) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(char in "0123456789abcdef" for char in value)


def _stream_sha256(path: Path, *, expected_size: int | None = None) -> tuple[int, str]:
    descriptor = _open_regular_nofollow(path, max_bytes=MAX_SOURCE_BYTES, expected_size=expected_size)
    digest = hashlib.sha256()
    with os.fdopen(descriptor, "rb", closefd=True) as stream:
        observed = os.fstat(stream.fileno())
        for chunk in iter(lambda: stream.read(CHUNK_BYTES), b""):
            digest.update(chunk)
    return observed.st_size, digest.hexdigest()


def _open_regular_nofollow(path: Path, *, max_bytes: int, expected_size: int | None = None) -> int:
    try:
        descriptor = open_regular_readonly(path)
    except OSError as exc:
        raise QualificationError(f"unable to open a regular non-symlink authority: {path}") from exc
    try:
        observed = os.fstat(descriptor)
        if not stat.S_ISREG(observed.st_mode):
            raise QualificationError(f"authority is not a regular file: {path}")
        if observed.st_size > max_bytes:
            raise QualificationError(f"authority exceeds {max_bytes} bytes: {path.name}")
        if expected_size is not None and observed.st_size != expected_size:
            raise QualificationError(f"authority size mismatch: {path.name}")
        return descriptor
    except Exception:
        os.close(descriptor)
        raise


def _read_bounded_regular(path: Path, *, max_bytes: int) -> bytes:
    descriptor = _open_regular_nofollow(path, max_bytes=max_bytes)
    with os.fdopen(descriptor, "rb", closefd=True) as stream:
        payload = stream.read(max_bytes + 1)
    if len(payload) > max_bytes:
        raise QualificationError(f"authority exceeds {max_bytes} bytes: {path.name}")
    return payload


def _array_digest(value: object) -> str:
    array = np.ascontiguousarray(np.asarray(value, dtype="<f8"))
    if not np.isfinite(array).all():
        raise QualificationError("OPUS decoded array contains non-finite values")
    return hashlib.sha256(array.tobytes()).hexdigest()


def _validated_locator(raw: object) -> str:
    if not isinstance(raw, str) or not raw:
        raise QualificationError("external fixture locator must be a non-empty string")
    locator = PurePosixPath(raw)
    if locator.is_absolute() or ".." in locator.parts or locator.parts[0] != "irdata":
        raise QualificationError("external fixture locator is not a canonical irdata path")
    if locator.as_posix() != raw:
        raise QualificationError("external fixture locator must use canonical POSIX spelling")
    return raw


def _source_modules(root: Path) -> dict[str, dict[str, str]]:
    modules = (ingestion_registry, *ingestion_registry.native_implementation_modules())
    if len({module.__name__ for module in modules}) != len(modules):
        raise QualificationError("canonical native-ingestion implementation closure contains duplicates")
    result: dict[str, dict[str, str]] = {}
    for module in modules:
        source_path = Path(module.__file__ or "").resolve()
        try:
            relative = source_path.relative_to(root).as_posix()
        except ValueError as exc:
            raise QualificationError(
                f"native-ingestion source is outside repository custody: {module.__name__}"
            ) from exc
        _size, digest = _stream_sha256(source_path)
        result[module.__name__] = {"path": relative, "sha256": digest}
    return result


def _runtime_identity() -> dict[str, Any]:
    distributions = {}
    for name in ("numpy", "spectra-sherpa"):
        try:
            distributions[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError as exc:
            raise QualificationError(f"required installed distribution is absent: {name}") from exc
    return {
        "python": platform.python_version(),
        "python_implementation": platform.python_implementation(),
        "platform_system": platform.system(),
        "platform_machine": platform.machine(),
        "byteorder": sys.byteorder,
        "distributions": distributions,
    }


def _loaded_scp_modules() -> list[str]:
    return sorted(name for name in sys.modules if name == "spectrochempy" or name.startswith("spectrochempy."))


def _expected_fixture_science(record: dict[str, Any]) -> dict[str, Any]:
    assets = []
    for asset in record["assets"]:
        assets.append(
            {
                "asset_id": asset["asset_id"],
                "shape": asset["shape"],
                "values_sha256": asset["values_sha256"],
                "axis_sha256": asset["axis_sha256"],
                "first_value": asset["first_value"],
                "last_value": asset["last_value"],
                "first_axis": asset["first_axis"],
                "last_axis": asset["last_axis"],
                "axis_units": asset["axis_units"],
                "data_quantity": asset["data_quantity"],
                "value_units": asset["value_units"],
            }
        )
    return {
        "version": record["version"],
        "block_count": record["block_count"],
        "asset_order": record["asset_order"],
        "assets": assets,
    }


def _observed_fixture_science(result: Any) -> dict[str, Any]:
    assets = []
    for asset in result.assets:
        dataset = asset.dataset
        axis = dataset.feature_axis
        values = np.asarray(dataset.X)
        coordinates = np.asarray(axis.values)
        if values.ndim != 2 or values.shape[0] != 1 or coordinates.ndim != 1:
            raise QualificationError("qualified OPUS assets must remain one-row, one-axis datasets")
        if values.shape[1] != coordinates.shape[0]:
            raise QualificationError("qualified OPUS values and feature axis are misaligned")
        assets.append(
            {
                "asset_id": asset.asset_id,
                "shape": list(values.shape),
                "values_sha256": _array_digest(values),
                "axis_sha256": _array_digest(coordinates),
                "first_value": float(values[0, 0]),
                "last_value": float(values[0, -1]),
                "first_axis": float(coordinates[0]),
                "last_axis": float(coordinates[-1]),
                "axis_units": axis.units,
                "data_quantity": dataset.domain.data_quantity,
                "value_units": dataset.units,
            }
        )
    return {
        "version": result.raw_metadata["opus.version"],
        "block_count": result.raw_metadata["opus.block_count"],
        "asset_order": [asset.asset_id for asset in result.assets],
        "assets": assets,
    }


def _fixture_rows(root: Path, external_root: Path, conformance: dict[str, Any]) -> tuple[list[dict[str, Any]], int]:
    if _loaded_scp_modules():
        raise QualificationError("SpectroChemPy was loaded before native OPUS qualification")
    fixture_rows: list[dict[str, Any]] = []
    total_assets = 0
    bundled_root = root / conformance["bundled_fixture_root"]
    groups = (
        ("bundled_redistribution_qualified", conformance["bundled_fixtures"]),
        ("external_ephemeral_not_redistributed", conformance["external_fixtures"]),
    )
    for source_kind, records in groups:
        for record in records:
            if source_kind.startswith("bundled"):
                public_locator = record["filename"]
                path = bundled_root / record["filename"]
            else:
                public_locator = _validated_locator(record["external_locator"])
                path = external_root / public_locator
            expected_size = EXPECTED_SOURCE_SIZES.get(record["fixture_id"])
            if expected_size is None:
                raise QualificationError(f"fixture size authority is missing for {record['fixture_id']}")
            size, source_digest = _stream_sha256(path, expected_size=expected_size)
            if source_digest != record["sha256"]:
                raise QualificationError(f"source SHA-256 mismatch for {record['fixture_id']}")
            result = ingest(path, limits=QUALIFICATION_LIMITS)
            if result.format_id != "opus" or result.parser_id != conformance["parser_id"]:
                raise QualificationError(f"native parser identity mismatch for {record['fixture_id']}")
            if result.parser_version != conformance["parser_version"] or result.variant != "directory-block-v1":
                raise QualificationError(f"native parser version/variant mismatch for {record['fixture_id']}")
            if len(result.source_members) != 1:
                raise QualificationError(f"native parser consumed an unexpected source set for {record['fixture_id']}")
            member = result.source_members[0]
            if (member.name, member.size_bytes, member.sha256) != (path.name, size, source_digest):
                raise QualificationError(f"native parser source custody mismatch for {record['fixture_id']}")
            expected_science = _expected_fixture_science(record)
            observed_science = _observed_fixture_science(result)
            if observed_science != expected_science:
                raise QualificationError(f"decoded OPUS science mismatch for {record['fixture_id']}")
            if _stream_sha256(path, expected_size=expected_size)[1] != source_digest:
                raise QualificationError(f"OPUS source changed during ingestion: {record['fixture_id']}")
            total_assets += len(result.assets)
            fixture_rows.append(
                {
                    "fixture_id": record["fixture_id"],
                    "source_kind": source_kind,
                    "public_locator": public_locator,
                    "source_size_bytes": size,
                    "source_sha256": source_digest,
                    "structural_variant": record["structural_variant"],
                    "asset_count": len(result.assets),
                    "scientific_projection_sha256": _digest_json(observed_science),
                }
            )
    if _loaded_scp_modules():
        raise QualificationError("SpectroChemPy was loaded by native OPUS ingestion")
    return fixture_rows, total_assets


def _conformance(root: Path) -> tuple[Path, dict[str, Any]]:
    path = root / "docs" / "evidence" / "native-opus-reader-conformance.json"
    record = _read_json(path)
    if record.get("schema_version") != CONFORMANCE_SCHEMA:
        raise QualificationError("native OPUS conformance schema is not the qualified version")
    if record.get("format_id") != "opus" or record.get("parser_id") != "spectrasherpa.opus":
        raise QualificationError("native OPUS conformance parser identity is malformed")
    if len(record.get("external_fixtures", [])) != EXTERNAL_FIXTURE_COUNT:
        raise QualificationError("native OPUS conformance must contain exactly three external fixtures")
    if len(record.get("bundled_fixtures", [])) != BUNDLED_FIXTURE_COUNT:
        raise QualificationError("native OPUS conformance must contain exactly six bundled fixtures")
    return path, record


def _current_commit(root: Path) -> str:
    completed = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


def build_report(*, external_root: Path, implementation_commit: str) -> dict[str, Any]:
    root = _repo_root()
    if not isinstance(implementation_commit, str) or len(implementation_commit) != 40:
        raise QualificationError("implementation commit must be one exact full Git SHA")
    if _current_commit(root) != implementation_commit:
        raise QualificationError("build must run at the exact implementation commit")
    conformance_path, conformance = _conformance(root)
    fixture_rows, total_assets = _fixture_rows(root, external_root, conformance)
    runtime = _runtime_identity()
    return {
        "schema_version": SCHEMA_VERSION,
        "status": "qualified_exact_named_corpus",
        "format_id": "opus",
        "parser": {
            "parser_id": conformance["parser_id"],
            "parser_version": conformance["parser_version"],
            "variant": "directory-block-v1",
            "implementation_commit": implementation_commit,
            "implementation_source_sha256": _source_modules(root),
        },
        "operator_authority": "author_operated_qualification",
        "runtime": runtime,
        "runtime_sha256": _digest_json(runtime),
        "conformance_authority": {
            "schema_version": conformance["schema_version"],
            "sha256": _stream_sha256(conformance_path)[1],
            "source_authority": conformance["source_authority"],
            "bundled_corpus_source": conformance["bundled_corpus_source"],
            "external_corpus_source": conformance["external_corpus_source"],
            "retained_scope_sha256": _digest_json(conformance["retained_scope"]),
        },
        "execution": {
            "fixture_count": len(fixture_rows),
            "bundled_fixture_count": BUNDLED_FIXTURE_COUNT,
            "external_fixture_count": EXTERNAL_FIXTURE_COUNT,
            "asset_count": total_assets,
            "spectrochempy_loaded_before": False,
            "spectrochempy_loaded_after": False,
            "native_ingestion_only": True,
            "fixtures": fixture_rows,
            "fixture_projection_sha256": _digest_json(fixture_rows),
        },
        "claim_boundary": CLAIM_BOUNDARY,
        "nonclaims": NONCLAIMS,
        "privacy": {
            "external_source_bytes_in_report": False,
            "external_source_paths_in_report": False,
            "credentials_or_user_identity_in_report": False,
        },
    }


def _require_exact_keys(value: object, expected: set[str], label: str) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != expected:
        raise QualificationError(f"{label} schema is not closed")
    return value


def validate_public_report(report: dict[str, Any], *, require_checked_hash: bool = True) -> None:
    root = _repo_root()
    _require_exact_keys(
        report,
        {
            "schema_version",
            "status",
            "format_id",
            "parser",
            "operator_authority",
            "runtime",
            "runtime_sha256",
            "conformance_authority",
            "execution",
            "claim_boundary",
            "nonclaims",
            "privacy",
        },
        "qualification report",
    )
    if report["schema_version"] != SCHEMA_VERSION or report["status"] != "qualified_exact_named_corpus":
        raise QualificationError("qualification report header is not exact")
    if report["format_id"] != "opus" or report["operator_authority"] != "author_operated_qualification":
        raise QualificationError("qualification report format/operator authority is not exact")
    if report["claim_boundary"] != CLAIM_BOUNDARY or report["nonclaims"] != NONCLAIMS:
        raise QualificationError("qualification claim boundary or ordered nonclaims changed")
    privacy = _require_exact_keys(
        report["privacy"],
        {
            "external_source_bytes_in_report",
            "external_source_paths_in_report",
            "credentials_or_user_identity_in_report",
        },
        "privacy",
    )
    if privacy != {key: False for key in privacy}:
        raise QualificationError("qualification privacy boundary is not exact")
    conformance_path, conformance = _conformance(root)
    authority = _require_exact_keys(
        report["conformance_authority"],
        {
            "schema_version",
            "sha256",
            "source_authority",
            "bundled_corpus_source",
            "external_corpus_source",
            "retained_scope_sha256",
        },
        "conformance authority",
    )
    expected_authority = {
        "schema_version": conformance["schema_version"],
        "sha256": _stream_sha256(conformance_path)[1],
        "source_authority": conformance["source_authority"],
        "bundled_corpus_source": conformance["bundled_corpus_source"],
        "external_corpus_source": conformance["external_corpus_source"],
        "retained_scope_sha256": _digest_json(conformance["retained_scope"]),
    }
    if authority != expected_authority:
        raise QualificationError("qualification conformance authority changed")
    parser = _require_exact_keys(
        report["parser"],
        {"parser_id", "parser_version", "variant", "implementation_commit", "implementation_source_sha256"},
        "parser authority",
    )
    if parser["parser_id"] != conformance["parser_id"] or parser["parser_version"] != conformance["parser_version"]:
        raise QualificationError("qualification parser authority changed")
    if parser["variant"] != "directory-block-v1":
        raise QualificationError("qualification parser variant changed")
    if parser["implementation_commit"] != QUALIFIED_IMPLEMENTATION_COMMIT:
        raise QualificationError("qualification implementation commit changed")
    if parser["implementation_source_sha256"] != _source_modules(root):
        raise QualificationError("qualified parser source bytes changed")
    runtime = _require_exact_keys(
        report["runtime"],
        {"python", "python_implementation", "platform_system", "platform_machine", "byteorder", "distributions"},
        "runtime authority",
    )
    _require_exact_keys(runtime["distributions"], {"numpy", "spectra-sherpa"}, "runtime distributions")
    if not all(isinstance(value, str) and value for key, value in runtime.items() if key != "distributions"):
        raise QualificationError("qualification runtime strings are malformed")
    if report["runtime_sha256"] != _digest_json(runtime) or report["runtime_sha256"] != QUALIFIED_RUNTIME_SHA256:
        raise QualificationError("qualification runtime authority changed")
    execution = _require_exact_keys(
        report["execution"],
        {
            "fixture_count",
            "bundled_fixture_count",
            "external_fixture_count",
            "asset_count",
            "spectrochempy_loaded_before",
            "spectrochempy_loaded_after",
            "native_ingestion_only",
            "fixtures",
            "fixture_projection_sha256",
        },
        "execution",
    )
    if execution["fixture_count"] != BUNDLED_FIXTURE_COUNT + EXTERNAL_FIXTURE_COUNT:
        raise QualificationError("qualification fixture count changed")
    if (
        execution["bundled_fixture_count"] != BUNDLED_FIXTURE_COUNT
        or execution["external_fixture_count"] != EXTERNAL_FIXTURE_COUNT
    ):
        raise QualificationError("qualification corpus partition changed")
    if execution["spectrochempy_loaded_before"] is not False or execution["spectrochempy_loaded_after"] is not False:
        raise QualificationError("SpectroChemPy ingestion isolation changed")
    if execution["native_ingestion_only"] is not True:
        raise QualificationError("native ingestion authority changed")
    fixtures = execution["fixtures"]
    expected_records = list(conformance["bundled_fixtures"]) + list(conformance["external_fixtures"])
    if not isinstance(fixtures, list) or len(fixtures) != len(expected_records):
        raise QualificationError("qualification fixture projection is malformed")
    expected_asset_count = 0
    for index, (row, expected) in enumerate(zip(fixtures, expected_records, strict=True)):
        _require_exact_keys(
            row,
            {
                "fixture_id",
                "source_kind",
                "public_locator",
                "source_size_bytes",
                "source_sha256",
                "structural_variant",
                "asset_count",
                "scientific_projection_sha256",
            },
            f"fixture {index}",
        )
        source_kind = (
            "bundled_redistribution_qualified"
            if index < BUNDLED_FIXTURE_COUNT
            else "external_ephemeral_not_redistributed"
        )
        locator = expected["filename"] if index < BUNDLED_FIXTURE_COUNT else expected["external_locator"]
        expected_asset_count += len(expected["assets"])
        if row != {
            "fixture_id": expected["fixture_id"],
            "source_kind": source_kind,
            "public_locator": locator,
            "source_size_bytes": EXPECTED_SOURCE_SIZES[expected["fixture_id"]],
            "source_sha256": expected["sha256"],
            "structural_variant": expected["structural_variant"],
            "asset_count": len(expected["assets"]),
            "scientific_projection_sha256": _digest_json(_expected_fixture_science(expected)),
        }:
            raise QualificationError(f"qualification fixture {index} changed")
        if type(row["source_size_bytes"]) is not int or not 0 < row["source_size_bytes"] <= MAX_SOURCE_BYTES:
            raise QualificationError(f"qualification fixture {index} size is malformed")
    if execution["asset_count"] != expected_asset_count:
        raise QualificationError("qualification asset count changed")
    if execution["fixture_projection_sha256"] != _digest_json(fixtures):
        raise QualificationError("qualification fixture projection digest changed")
    payload = _canonical_bytes(report)
    if len(payload) > MAX_REPORT_BYTES:
        raise QualificationError("qualification report exceeds its public byte ceiling")
    forbidden = (str(Path.home()), "/private/", "SPECTRA_EXTERNAL_VENDOR_CORPUS")
    text = payload.decode("utf-8")
    if any(value in text for value in forbidden):
        raise QualificationError("qualification report contains a private path or environment name")
    if require_checked_hash:
        if not _is_sha256(CHECKED_REPORT_SHA256) or _digest_bytes(payload) != CHECKED_REPORT_SHA256:
            raise QualificationError("qualification report does not match its checked SHA-256")


def check_corpus(*, external_root: Path, report: dict[str, Any]) -> None:
    validate_public_report(report)
    root = _repo_root()
    _path, conformance = _conformance(root)
    fixtures, asset_count = _fixture_rows(root, external_root, conformance)
    execution = report["execution"]
    if fixtures != execution["fixtures"] or asset_count != execution["asset_count"]:
        raise QualificationError("live OPUS corpus does not reproduce the checked execution")


def _write_new(path: Path, payload: bytes) -> None:
    if path.exists() or path.is_symlink():
        raise QualificationError(f"refusing to replace existing report: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    if temporary.exists() or temporary.is_symlink():
        raise QualificationError("qualification report temporary path already exists")
    try:
        with temporary.open("xb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    build = commands.add_parser("build")
    build.add_argument("--external-corpus", type=Path, required=True)
    build.add_argument("--implementation-commit", required=True)
    build.add_argument("--output", type=Path, required=True)
    check_public = commands.add_parser("check-public")
    check_public.add_argument("--report", type=Path, required=True)
    check_live = commands.add_parser("check-corpus")
    check_live.add_argument("--external-corpus", type=Path, required=True)
    check_live.add_argument("--report", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "build":
            report = build_report(
                external_root=args.external_corpus,
                implementation_commit=args.implementation_commit,
            )
            _write_new(args.output, _canonical_bytes(report))
        elif args.command == "check-public":
            validate_public_report(_read_json(args.report))
        else:
            check_corpus(external_root=args.external_corpus, report=_read_json(args.report))
    except Exception as exc:
        print(f"native OPUS qualification failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    print("Native OPUS exact-corpus qualification: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
