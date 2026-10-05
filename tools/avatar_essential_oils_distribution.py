#!/usr/bin/env python3
"""Build and independently validate the Avatar essential-oil distribution.

The raw corpus is a separately licensed data product.  It must never be added
to the SpectraSherpa wheel or source distribution.  This tool joins the frozen
scientific authorities to an explicit release authority, produces a
deterministic ZIP, and then re-admits the resulting bytes before success.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import re
import stat
import struct
import sys
import tempfile
import zipfile
from collections.abc import Mapping, Sequence
from pathlib import Path, PurePosixPath
from typing import Any

import numpy as np

from spectra_sherpa.core.file_io import open_regular_readonly
from spectra_sherpa.io import ParserLimits, ingest
from spectra_sherpa.io.registry import native_implementation_modules

DATASET_ID = "avatar-essential-oils/1"
DATASET_TITLE = "Lavender Essential Oil FTIR Corpus v1"
PACKAGE_ROOT = "lavender-essential-oil-v1"
RELEASE_AUTHORITY_SCHEMA = "spectrasherpa-avatar-essential-oils-release-authority/1"
PACKAGE_MANIFEST_SCHEMA = "spectrasherpa-avatar-essential-oils-distribution/2"
RECEIPT_SCHEMA = "spectrasherpa-avatar-essential-oils-distribution-receipt/1"
LICENSE = "CC-BY-4.0"
LICENSE_URL = "https://creativecommons.org/licenses/by/4.0/"
LICENSE_AUTHORIZATION_SHA256 = "7cef134d44482792eeec4dc2787eb4a0ba134eb5df7a197a5d496d48e9d999d5"
REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
PRIVATE_WORKTREE_ROOT = REPOSITORY_ROOT / "private-input"

JSON_BYTES_MAX = 4 * 1024 * 1024
SOURCE_FILE_BYTES_MAX = 64 * 1024 * 1024
SOURCE_AGGREGATE_BYTES_MAX = 64 * 1024 * 1024
ARCHIVE_BYTES_MAX = 96 * 1024 * 1024
ARCHIVE_MEMBER_COUNT = 41
ARCHIVE_DIRECTORY_BYTES_MAX = 1024 * 1024
TEXT_FIELD_BYTES_MAX = 16 * 1024
ZIP_TIMESTAMP = (1980, 1, 1, 0, 0, 0)

_RELEASE_FIELDS = {
    "schema_version",
    "dataset_id",
    "dataset_version",
    "status",
    "license",
    "license_url",
    "license_authorization_sha256",
    "source_manifest_sha256",
    "collection_definition_sha256",
    "dataset_title",
    "creator_display_name",
    "licensor_display_name",
    "canonical_attribution_statement",
    "citation_policy",
    "citations",
    "privacy_review",
    "limitations",
}
_PRIVACY_FIELDS = {
    "status",
    "reviewed_on",
    "reviewer_role",
    "supplier_crosswalk_absent",
    "supplier_identity_absent",
    "supplier_identifying_metadata_absent",
    "private_paths_and_ids_absent",
    "non_oil_references_absent",
}
_CITATION_POLICY_FIELDS = {
    "status",
    "basis",
    "statement",
    "external_publication_citation_count",
}
_PACKAGE_MANIFEST_FIELDS = {
    "schema_version",
    "dataset_id",
    "dataset_version",
    "dataset_title",
    "license",
    "license_url",
    "creator_display_name",
    "licensor_display_name",
    "canonical_attribution_statement",
    "citation_policy",
    "source_manifest_authority",
    "source_collection_definition_authority",
    "release_authority_sha256",
    "acquisition_method",
    "claim_boundary",
    "counts",
    "files",
    "citations_sha256",
    "resolved_collection_definition_sha256",
    "privacy_review",
    "limitations",
}
_PRIVATE_TEXT_PATTERNS = (
    re.compile(r"(?:^|[\s\"'])(?:/Users/|/home/|/private/tmp/|[A-Za-z]:\\)"),
    re.compile(r"\b[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}\b"),
    re.compile(r"\b(?:supplier_crosswalk|supplier_identity|supplier_identifying_metadata)\b", re.IGNORECASE),
)
_PRIVATE_SOURCE_PATTERNS = (
    re.compile(
        r"(?:/Users/|/home/|/private/tmp/|[A-Za-z]:\\Users\\|[A-Za-z]:\\Documents and Settings\\)",
        re.IGNORECASE,
    ),
    re.compile(r"\b[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}\b", re.IGNORECASE),
    re.compile(
        r"\b(?:supplier|vendor|invoice|purchase[_ -]?order|catalog[_ -]?number|customer[_ -]?number)\b",
        re.IGNORECASE,
    ),
)


class DistributionError(ValueError):
    """The proposed package does not satisfy the publication contract."""


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _canonical_json(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise DistributionError(f"JSON authority contains duplicate key {key!r}")
        result[key] = value
    return result


def _parse_json(content: bytes, *, label: str) -> Any:
    try:
        return json.loads(content.decode("utf-8"), object_pairs_hook=_unique_object)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise DistributionError(f"{label} is not exact UTF-8 JSON") from exc


def _read_regular(path: Path, *, limit: int, label: str) -> bytes:
    try:
        lexical = path.lstat()
    except OSError as exc:
        raise DistributionError(f"{label} cannot be inspected") from exc
    if not stat.S_ISREG(lexical.st_mode) or stat.S_ISLNK(lexical.st_mode):
        raise DistributionError(f"{label} must be one real regular file")
    try:
        descriptor = open_regular_readonly(path)
    except OSError as exc:
        raise DistributionError(f"{label} cannot be opened without following links") from exc
    try:
        observed = os.fstat(descriptor)
        if not stat.S_ISREG(observed.st_mode):
            raise DistributionError(f"{label} must be one regular file")
        if hasattr(lexical, "st_ino") and (lexical.st_dev, lexical.st_ino) != (observed.st_dev, observed.st_ino):
            raise DistributionError(f"{label} changed between inspection and open")
        if observed.st_size < 0 or observed.st_size > limit:
            raise DistributionError(f"{label} exceeds its {limit}-byte ceiling")
        chunks: list[bytes] = []
        retained = 0
        while True:
            chunk = os.read(descriptor, min(1024 * 1024, limit + 1 - retained))
            if not chunk:
                break
            chunks.append(chunk)
            retained += len(chunk)
            if retained > limit:
                raise DistributionError(f"{label} exceeds its {limit}-byte ceiling")
        content = b"".join(chunks)
        if len(content) != observed.st_size:
            raise DistributionError(f"{label} changed while it was read")
        final = path.lstat()
        if not stat.S_ISREG(final.st_mode) or (final.st_dev, final.st_ino) != (observed.st_dev, observed.st_ino):
            raise DistributionError(f"{label} changed while it was admitted")
        return content
    finally:
        os.close(descriptor)


def _json_snapshot(path: Path, *, label: str) -> tuple[dict[str, Any], bytes, str]:
    content = _read_regular(path, limit=JSON_BYTES_MAX, label=label)
    parsed = _parse_json(content, label=label)
    if not isinstance(parsed, dict):
        raise DistributionError(f"{label} must be one JSON object")
    return parsed, content, _sha256(content)


def _exact_fields(value: Mapping[str, Any], fields: set[str], *, label: str) -> None:
    if set(value) != fields:
        missing = sorted(fields - set(value))
        unknown = sorted(set(value) - fields)
        raise DistributionError(f"{label} has an incomplete or unknown schema (missing={missing}, unknown={unknown})")


def _exact_text(value: Any, *, label: str) -> str:
    if not isinstance(value, str) or not value or value.strip() != value:
        raise DistributionError(f"{label} must be exact non-empty text")
    if len(value.encode("utf-8")) > TEXT_FIELD_BYTES_MAX:
        raise DistributionError(f"{label} exceeds its text ceiling")
    lowered = value.casefold()
    if "pending" in lowered or "placeholder" in lowered or "tbd" in lowered:
        raise DistributionError(f"{label} still contains a release placeholder")
    return value


def _sha(value: Any, *, label: str) -> str:
    if not isinstance(value, str) or len(value) != 64 or any(ch not in "0123456789abcdef" for ch in value):
        raise DistributionError(f"{label} must be lowercase SHA-256")
    return value


def _reject_spectrochempy_loaded() -> None:
    loaded = sorted(name for name in sys.modules if name == "spectrochempy" or name.startswith("spectrochempy."))
    if loaded:
        raise DistributionError("SpectroChemPy must remain unloaded during native Avatar package qualification")


def _implementation_authority() -> dict[str, Any]:
    tool_bytes = _read_regular(Path(__file__), limit=4 * 1024 * 1024, label="distribution implementation")
    modules: list[dict[str, str]] = []
    for module in sorted(native_implementation_modules(), key=lambda item: item.__name__):
        module_path = getattr(module, "__file__", None)
        if not isinstance(module_path, str) or not module_path.endswith(".py"):
            raise DistributionError(f"native ingestion module {module.__name__} has no exact Python source")
        content = _read_regular(Path(module_path), limit=4 * 1024 * 1024, label=f"native module {module.__name__}")
        modules.append({"module": module.__name__, "sha256": _sha256(content)})
    projection = {"modules": modules}
    return {
        "distribution_tool_sha256": _sha256(tool_bytes),
        "native_module_count": len(modules),
        "native_module_projection_sha256": _sha256(_canonical_json(projection)),
    }


def _validate_release_authority(
    authority: Mapping[str, Any],
    *,
    source_manifest_sha256: str,
    collection_definition_sha256: str,
    historical_pending_specimens: set[str],
) -> dict[str, Any]:
    _exact_fields(authority, _RELEASE_FIELDS, label="release authority")
    expected = {
        "schema_version": RELEASE_AUTHORITY_SCHEMA,
        "dataset_id": DATASET_ID,
        "dataset_title": DATASET_TITLE,
        "license": LICENSE,
        "license_url": LICENSE_URL,
        "license_authorization_sha256": LICENSE_AUTHORIZATION_SHA256,
        "source_manifest_sha256": source_manifest_sha256,
        "collection_definition_sha256": collection_definition_sha256,
    }
    for field, wanted in expected.items():
        if authority.get(field) != wanted:
            raise DistributionError(f"release authority {field} does not match its exact authority")
    dataset_version = authority.get("dataset_version")
    if type(dataset_version) is not int or dataset_version != 1:
        raise DistributionError("release authority dataset_version must be integer 1")
    status = authority.get("status")
    if status not in {
        "approved_for_private_package_review",
        "approved_for_unpublished_distribution_candidate",
    }:
        raise DistributionError("release authority status is not an admitted Phase 1 state")
    _exact_text(authority.get("creator_display_name"), label="creator display name")
    _exact_text(authority.get("licensor_display_name"), label="licensor display name")
    _exact_text(authority.get("canonical_attribution_statement"), label="canonical attribution statement")

    citation_policy = authority.get("citation_policy")
    if not isinstance(citation_policy, Mapping):
        raise DistributionError("citation policy must be one closed object")
    _exact_fields(citation_policy, _CITATION_POLICY_FIELDS, label="citation policy")
    if citation_policy.get("status") != "no_external_publication_citations_applicable":
        raise DistributionError("citation policy must state that no external publication citations apply")
    if citation_policy.get("basis") != "original_unpublished_laboratory_dataset":
        raise DistributionError("citation policy must identify the original unpublished laboratory basis")
    _exact_text(citation_policy.get("statement"), label="laboratory-origin citation statement")
    if citation_policy.get("external_publication_citation_count") != 0:
        raise DistributionError("laboratory-origin citation count must be exact integer zero")
    if authority.get("citations") != []:
        raise DistributionError("the original laboratory dataset must not manufacture publication citations")

    privacy = authority.get("privacy_review")
    if not isinstance(privacy, Mapping):
        raise DistributionError("privacy review must be one closed object")
    _exact_fields(privacy, _PRIVACY_FIELDS, label="privacy review")
    privacy_assertions = _PRIVACY_FIELDS - {"status", "reviewed_on", "reviewer_role"}
    if status == "approved_for_private_package_review":
        if privacy != {
            "status": "pending_candidate_content_review",
            "reviewed_on": None,
            "reviewer_role": None,
            **{field: None for field in privacy_assertions},
        }:
            raise DistributionError("private-review candidate must retain an exact pending privacy review")
    else:
        if privacy.get("status") != "passed":
            raise DistributionError("final privacy review has not passed")
        _exact_text(privacy.get("reviewed_on"), label="privacy review date")
        _exact_text(privacy.get("reviewer_role"), label="privacy reviewer role")
        for field in privacy_assertions:
            if privacy.get(field) is not True:
                raise DistributionError(f"privacy review did not affirm {field}")

    limitations = authority.get("limitations")
    if not isinstance(limitations, list) or not limitations:
        raise DistributionError("release authority requires at least one limitation")
    for index, value in enumerate(limitations):
        _exact_text(value, label=f"limitation {index}")
    if len(set(limitations)) != len(limitations):
        raise DistributionError("release limitations must be unique")

    return {
        "schema_version": "spectrasherpa-avatar-essential-oils-citations/2",
        "citation_policy": dict(citation_policy),
        "historical_pending_specimen_ids_superseded": sorted(historical_pending_specimens),
        "citations": [],
    }


def _validate_source_authorities(
    manifest: Mapping[str, Any], definition: Mapping[str, Any]
) -> tuple[list[dict[str, Any]], set[str]]:
    if manifest.get("schema_version") != "spectrasherpa-avatar-essential-oils-public-manifest/2":
        raise DistributionError("source manifest schema is not the frozen Avatar authority")
    if manifest.get("dataset_id") != DATASET_ID or manifest.get("dataset_version") != 1:
        raise DistributionError("source manifest dataset identity is invalid")
    rows = manifest.get("files")
    if not isinstance(rows, list) or len(rows) != 33:
        raise DistributionError("source manifest must contain exactly 33 files")
    names: set[str] = set()
    hashes: set[str] = set()
    samples: set[str] = set()
    ordered: list[dict[str, Any]] = []
    expected_position = 0
    required_citations: set[str] = set()
    for row in rows:
        if not isinstance(row, Mapping):
            raise DistributionError("source manifest file rows must be objects")
        name = _exact_text(row.get("distribution_filename"), label="distribution filename")
        portable = PurePosixPath(name)
        if portable.name != name or portable.suffix.casefold() != ".spa" or name != portable.as_posix():
            raise DistributionError(f"distribution filename {name!r} is not canonical portable SPA spelling")
        digest = _sha(row.get("curated_sha256"), label=f"{name} source digest")
        size = row.get("size_bytes")
        if type(size) is not int or not 0 < size <= SOURCE_FILE_BYTES_MAX:
            raise DistributionError(f"{name} has an invalid source size")
        sample_id = _exact_text(row.get("sample_id"), label=f"{name} sample ID")
        specimen_id = _exact_text(row.get("specimen_id"), label=f"{name} specimen ID")
        block = row.get("block")
        order = row.get("acquisition_order")
        if type(block) is not int or block not in (1, 2, 3) or type(order) is not int or not 1 <= order <= 11:
            raise DistributionError(f"{name} has an invalid block/order identity")
        expected_position += 1
        expected_block = (expected_position - 1) // 11 + 1
        expected_order = (expected_position - 1) % 11 + 1
        if (block, order) != (expected_block, expected_order):
            raise DistributionError("source manifest is not in exact acquisition order")
        if name in names or digest in hashes or sample_id in samples:
            raise DistributionError("source manifest names, hashes, and sample IDs must be unique")
        names.add(name)
        hashes.add(digest)
        samples.add(sample_id)
        if row.get("evidence_status") == "pending_exact_citation":
            required_citations.add(specimen_id)
        ordered.append(dict(row))
    if len({row["specimen_id"] for row in ordered}) != 11:
        raise DistributionError("source manifest must contain exactly 11 specimens")

    if definition.get("schema_version") != "spectrasherpa-collection-definition/1":
        raise DistributionError("collection definition schema is not the frozen authority")
    definition_rows = definition.get("rows")
    if not isinstance(definition_rows, list) or len(definition_rows) != 33:
        raise DistributionError("collection definition must contain exactly 33 rows")
    for source, defined in zip(ordered, definition_rows, strict=True):
        if not isinstance(defined, Mapping) or not isinstance(defined.get("annotations"), Mapping):
            raise DistributionError("collection definition row is malformed")
        annotations = defined["annotations"]
        expected = {
            "file_name": f"raw/{source['distribution_filename']}",
            "sha256": source["curated_sha256"],
            "asset_id": "spectrum",
            "source_row_index": 0,
            "sample_id": source["sample_id"],
        }
        for field, value in expected.items():
            if defined.get(field) != value:
                raise DistributionError(f"collection definition {field} is not bound to the source manifest")
        for field in ("sample_id", "specimen_id", "block", "acquisition_order", "curated_filename", "curated_sha256"):
            source_field = "distribution_filename" if field == "curated_filename" else field
            if annotations.get(field) != source[source_field]:
                raise DistributionError(f"collection definition annotation {field} is not source-bound")
    return ordered, required_citations


def _source_snapshot(source_dir: Path, rows: Sequence[Mapping[str, Any]]) -> dict[str, bytes]:
    try:
        directory_state = source_dir.lstat()
    except OSError as exc:
        raise DistributionError("source directory cannot be inspected") from exc
    if not stat.S_ISDIR(directory_state.st_mode) or stat.S_ISLNK(directory_state.st_mode):
        raise DistributionError("source directory must be one real directory")
    expected = {str(row["distribution_filename"]) for row in rows}
    observed: set[str] = set()
    with os.scandir(source_dir) as entries:
        for entry in entries:
            observed.add(entry.name)
            if entry.name not in expected or not entry.is_file(follow_symlinks=False) or entry.is_symlink():
                raise DistributionError("source directory contains an extra, linked, or non-regular entry")
    if observed != expected:
        raise DistributionError("source directory does not contain the exact 33-file inventory")
    result: dict[str, bytes] = {}
    aggregate = 0
    for row in rows:
        name = str(row["distribution_filename"])
        content = _read_regular(source_dir / name, limit=SOURCE_FILE_BYTES_MAX, label=f"source {name}")
        aggregate += len(content)
        if aggregate > SOURCE_AGGREGATE_BYTES_MAX:
            raise DistributionError("source collection exceeds its aggregate byte ceiling")
        if len(content) != row["size_bytes"] or _sha256(content) != row["curated_sha256"]:
            raise DistributionError(f"source {name} does not match the frozen manifest")
        _reject_private_source_bytes(name, content)
        result[name] = content
    if {entry.name for entry in os.scandir(source_dir)} != expected:
        raise DistributionError("source inventory changed during admission")
    return result


def _array_sha256(values: Any) -> str:
    array = np.ascontiguousarray(np.asarray(values, dtype="<f8"))
    return _sha256(array.tobytes(order="C"))


def _native_projection(name: str, content: bytes) -> dict[str, Any]:
    limits = ParserLimits(
        max_source_bytes=SOURCE_FILE_BYTES_MAX,
        max_decoded_elements=4_000_000,
        max_decoded_bytes=64 * 1024 * 1024,
        max_blocks=4096,
        max_metadata_bytes=4 * 1024 * 1024,
        max_probe_bytes=64 * 1024,
    )
    with tempfile.TemporaryDirectory(prefix="spectrasherpa-avatar-parse-") as temp_dir:
        snapshot = Path(temp_dir) / name
        snapshot.write_bytes(content)
        result = ingest(snapshot, limits=limits)
    if (result.format_id, result.variant, result.parser_id, result.parser_version) != (
        "omnic",
        "spa-single-spectrum",
        "spectrasherpa.omnic",
        "1",
    ):
        raise DistributionError(f"{name} did not select the exact qualified native OMNIC parser")
    if len(result.source_members) != 1:
        raise DistributionError(f"{name} did not report one exact source member")
    source = result.source_members[0]
    if source.sha256 != _sha256(content) or source.size_bytes != len(content):
        raise DistributionError(f"{name} parser source identity does not match the admitted snapshot")
    if len(result.assets) != 1 or result.assets[0].asset_id != "spectrum":
        raise DistributionError(f"{name} does not contain the sole qualified spectrum asset")
    dataset = result.assets[0].dataset
    axis = dataset.feature_axis
    if tuple(dataset.shape) != (1, 1868) or axis is None or axis.values is None:
        raise DistributionError(f"{name} has an unqualified scientific shape")
    values = np.asarray(dataset.X, dtype=np.float64)
    coordinates = np.asarray(axis.values, dtype=np.float64)
    if not np.all(np.isfinite(values)) or not np.all(np.isfinite(coordinates)) or not np.all(np.diff(coordinates) < 0):
        raise DistributionError(f"{name} has invalid scientific values or feature axis")
    return {
        "format_id": result.format_id,
        "variant": result.variant,
        "parser_id": result.parser_id,
        "parser_version": result.parser_version,
        "asset_id": result.assets[0].asset_id,
        "shape": [1, 1868],
        "axis_units": str(axis.units),
        "value_units": str(dataset.units),
        "values_sha256": _array_sha256(values),
        "axis_sha256": _array_sha256(coordinates),
    }


def _resolved_definition(definition: Mapping[str, Any], historical_pending_specimens: set[str]) -> dict[str, Any]:
    resolved = json.loads(json.dumps(definition))
    for row in resolved["rows"]:
        annotations = row["annotations"]
        specimen = annotations["specimen_id"]
        if annotations["evidence_status"] == "pending_exact_citation":
            if specimen not in historical_pending_specimens:
                raise DistributionError("historical pending-citation rows are not internally consistent")
            annotations["evidence_status"] = "original_lab_dataset_no_external_publication_citation"
            annotations["evidence_citation_id"] = None
    return resolved


def _text_members(authority: Mapping[str, Any], citations: Mapping[str, Any]) -> dict[str, bytes]:
    attribution = str(authority["canonical_attribution_statement"])
    limitations = [str(value) for value in authority["limitations"]]
    return {
        "README.md": (
            f"# {DATASET_TITLE}\n\n"
            "This separately distributed dataset contains 33 Thermo Nicolet Avatar 370 OMNIC SPA files: "
            "11 retained lavender essential-oil specimens acquired in three blocks. Spectra are absorbance with "
            "OMNIC correction set to None. Validate `SHA256SUMS` and `manifest.json` before use.\n\n"
            "This is an original unpublished laboratory dataset. No external publication citations apply.\n\n"
            "This dataset is not evidence of botanical authenticity, supplier identity, population "
            "performance, or performance on future lots. The software is distributed separately.\n"
        ).encode("utf-8"),
        "LICENSE.txt": (
            f"{DATASET_TITLE}\n\n"
            f"Creator: {authority['creator_display_name']}\n"
            f"Licensor: {authority['licensor_display_name']}\n\n"
            "Licensed under the Creative Commons Attribution 4.0 International license (CC BY 4.0):\n"
            f"{LICENSE_URL}\n\n"
            "You may share and adapt the material under the license terms, including attribution and "
            "indication of changes. This license applies to this dataset, not to the SpectraSherpa software.\n"
        ).encode("utf-8"),
        "ATTRIBUTION.md": (
            "# Attribution\n\n"
            f"{attribution}\n\n"
            f"Creator: {authority['creator_display_name']}\n"
            f"Licensor: {authority['licensor_display_name']}\n"
            f"License: CC BY 4.0 ({LICENSE_URL})\n"
        ).encode("utf-8"),
        "CITATIONS.json": _canonical_json(citations),
        "LIMITATIONS.md": ("# Limitations\n\n" + "\n".join(f"- {item}" for item in limitations) + "\n").encode("utf-8"),
    }


def _reject_private_text(payloads: Mapping[str, bytes]) -> None:
    for name, content in payloads.items():
        if name.startswith("data/"):
            continue
        try:
            text = content.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise DistributionError(f"public metadata member {name} is not UTF-8") from exc
        for pattern in _PRIVATE_TEXT_PATTERNS:
            if pattern.search(text):
                raise DistributionError(f"public metadata member {name} contains privacy-bearing text")


def _reject_private_source_bytes(name: str, content: bytes) -> None:
    fragments = [match.group().decode("ascii") for match in re.finditer(rb"[\x20-\x7e]{5,}", content)]
    for expression, encoding in (
        (rb"(?:[\x20-\x7e]\x00){5,}", "utf-16-le"),
        (rb"(?:\x00[\x20-\x7e]){5,}", "utf-16-be"),
    ):
        fragments.extend(match.group().decode(encoding) for match in re.finditer(expression, content))
    projection = "\n".join(fragments)
    for pattern in _PRIVATE_SOURCE_PATTERNS:
        if pattern.search(projection):
            raise DistributionError(f"raw source {name} contains privacy-bearing text")


def _package_payloads(
    *,
    source_manifest: Mapping[str, Any],
    source_manifest_sha256: str,
    definition: Mapping[str, Any],
    definition_sha256: str,
    release_authority: Mapping[str, Any],
    release_authority_bytes: bytes,
    sources: Mapping[str, bytes],
    verify_native: bool,
) -> dict[str, bytes]:
    rows, historical_pending_specimens = _validate_source_authorities(source_manifest, definition)
    citations = _validate_release_authority(
        release_authority,
        source_manifest_sha256=source_manifest_sha256,
        collection_definition_sha256=definition_sha256,
        historical_pending_specimens=historical_pending_specimens,
    )
    resolved_definition = _resolved_definition(definition, historical_pending_specimens)
    resolved_definition_bytes = _canonical_json(resolved_definition)
    text_members = _text_members(release_authority, citations)
    file_projection: list[dict[str, Any]] = []
    for row in rows:
        name = str(row["distribution_filename"])
        content = sources[name]
        if len(content) != row["size_bytes"] or _sha256(content) != row["curated_sha256"]:
            raise DistributionError(f"package source {name} does not match its frozen identity")
        _reject_private_source_bytes(name, content)
        if verify_native:
            projection = _native_projection(name, content)
            for field in (
                "format_id",
                "variant",
                "parser_id",
                "parser_version",
                "asset_id",
                "shape",
                "axis_units",
                "value_units",
                "values_sha256",
                "axis_sha256",
            ):
                if projection[field] != row[field]:
                    raise DistributionError(f"package source {name} parser projection changed at {field}")
        file_projection.append(
            {
                "path": f"data/{name}",
                "size_bytes": len(content),
                "sha256": _sha256(content),
                "sample_id": row["sample_id"],
                "specimen_id": row["specimen_id"],
                "block": row["block"],
                "acquisition_order": row["acquisition_order"],
                "shape": row["shape"],
                "axis_units": row["axis_units"],
                "feature_axis_order": row["feature_axis_order"],
                "value_units": row["value_units"],
                "values_sha256": row["values_sha256"],
                "axis_sha256": row["axis_sha256"],
            }
        )
    package_manifest = {
        "schema_version": PACKAGE_MANIFEST_SCHEMA,
        "dataset_id": DATASET_ID,
        "dataset_version": 1,
        "dataset_title": release_authority["dataset_title"],
        "license": LICENSE,
        "license_url": LICENSE_URL,
        "creator_display_name": release_authority["creator_display_name"],
        "licensor_display_name": release_authority["licensor_display_name"],
        "canonical_attribution_statement": release_authority["canonical_attribution_statement"],
        "citation_policy": dict(release_authority["citation_policy"]),
        "source_manifest_authority": {
            "schema_version": source_manifest["schema_version"],
            "sha256": source_manifest_sha256,
        },
        "source_collection_definition_authority": {
            "schema_version": definition["schema_version"],
            "sha256": definition_sha256,
        },
        "release_authority_sha256": _sha256(release_authority_bytes),
        "acquisition_method": {
            "instrument": "Thermo Nicolet Avatar 370",
            "measurement_mode": "ATR absorbance",
            "ordinate": "absorbance",
            "correction": "None",
        },
        "claim_boundary": source_manifest["claim_boundary"],
        "counts": {"files": 33, "specimens": 11, "blocks": 3},
        "files": file_projection,
        "citations_sha256": _sha256(text_members["CITATIONS.json"]),
        "resolved_collection_definition_sha256": _sha256(resolved_definition_bytes),
        "privacy_review": dict(release_authority["privacy_review"]),
        "limitations": list(release_authority["limitations"]),
    }
    _exact_fields(package_manifest, _PACKAGE_MANIFEST_FIELDS, label="package manifest")
    payloads = dict(text_members)
    payloads["manifest.json"] = _canonical_json(package_manifest)
    payloads["collection-definition.json"] = resolved_definition_bytes
    for row in rows:
        name = str(row["distribution_filename"])
        payloads[f"data/{name}"] = sources[name]
    checksums = "".join(f"{_sha256(payloads[name])}  {name}\n" for name in sorted(payloads))
    payloads["SHA256SUMS"] = checksums.encode("utf-8")
    if len(payloads) != ARCHIVE_MEMBER_COUNT:
        raise DistributionError("package payload census is not exactly 41 members")
    _reject_private_text(payloads)
    return payloads


def _zip_bytes(payloads: Mapping[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_STORED, allowZip64=False) as archive:
        for relative in sorted(payloads):
            name = f"{PACKAGE_ROOT}/{relative}"
            info = zipfile.ZipInfo(name, ZIP_TIMESTAMP)
            info.compress_type = zipfile.ZIP_STORED
            info.create_system = 3
            info.external_attr = 0o100644 << 16
            archive.writestr(info, payloads[relative])
    content = buffer.getvalue()
    if len(content) > ARCHIVE_BYTES_MAX:
        raise DistributionError("distribution archive exceeds its byte ceiling")
    return content


def _write_new_private(path: Path, content: bytes) -> None:
    destination = path.expanduser().resolve(strict=False)
    try:
        destination.relative_to(REPOSITORY_ROOT)
    except ValueError:
        pass
    else:
        try:
            destination.relative_to(PRIVATE_WORKTREE_ROOT)
        except ValueError as exc:
            raise DistributionError(
                f"distribution output must be outside the repository or under {PRIVATE_WORKTREE_ROOT}"
            ) from exc
    if destination.suffix.casefold() != ".zip":
        raise DistributionError("distribution output must use the .zip extension")
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists() or destination.is_symlink():
        raise DistributionError("distribution output already exists; overwrite is forbidden")
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{destination.name}.", dir=destination.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as output:
            output.write(content)
            output.flush()
            os.fsync(output.fileno())
        os.chmod(temporary, 0o600)
        try:
            os.link(temporary, destination)
        except FileExistsError as exc:
            raise DistributionError("distribution output was concurrently created") from exc
        os.chmod(destination, 0o600)
    finally:
        temporary.unlink(missing_ok=True)


def _zip_directory_preflight(content: bytes) -> int:
    if len(content) < 22:
        raise DistributionError("distribution archive is truncated")
    eocd_offset = content.rfind(b"PK\x05\x06", max(0, len(content) - 65_557))
    if eocd_offset < 0 or eocd_offset + 22 > len(content):
        raise DistributionError("distribution archive has no bounded EOCD")
    (
        _signature,
        disk,
        directory_disk,
        entries_on_disk,
        entry_count,
        directory_size,
        directory_offset,
        comment_size,
    ) = struct.unpack_from("<4s4H2LH", content, eocd_offset)
    if eocd_offset + 22 + comment_size != len(content):
        raise DistributionError("distribution archive has a comment or trailing bytes")
    if disk != 0 or directory_disk != 0 or entries_on_disk != entry_count:
        raise DistributionError("distribution archive uses an unsupported multi-disk layout")
    if entry_count != ARCHIVE_MEMBER_COUNT:
        raise DistributionError("distribution archive member count is not exactly 41")
    if directory_size > ARCHIVE_DIRECTORY_BYTES_MAX or directory_offset + directory_size != eocd_offset:
        raise DistributionError("distribution archive central directory is outside its bounds")
    cursor = directory_offset
    end = directory_offset + directory_size
    observed = 0
    while cursor < end:
        if end - cursor < 46:
            raise DistributionError("distribution archive central directory is truncated")
        values = struct.unpack_from("<4s6H3L5H2L", content, cursor)
        if values[0] != b"PK\x01\x02":
            raise DistributionError("distribution archive central directory is malformed")
        name_size, extra_size, member_comment_size = values[10], values[11], values[12]
        cursor += 46 + name_size + extra_size + member_comment_size
        observed += 1
        if observed > ARCHIVE_MEMBER_COUNT or cursor > end:
            raise DistributionError("distribution archive central directory exceeds its bounds")
    if cursor != end or observed != entry_count:
        raise DistributionError("distribution archive central-directory census is inconsistent")
    return observed


def _archive_payloads(content: bytes) -> dict[str, bytes]:
    _zip_directory_preflight(content)
    payloads: dict[str, bytes] = {}
    total = 0
    with zipfile.ZipFile(io.BytesIO(content)) as archive:
        infos = archive.infolist()
        if len(infos) != ARCHIVE_MEMBER_COUNT:
            raise DistributionError("distribution archive member census changed after preflight")
        for info in infos:
            path = PurePosixPath(info.filename)
            if (
                info.is_dir()
                or path.as_posix() != info.filename
                or not path.parts
                or path.parts[0] != PACKAGE_ROOT
                or len(path.parts) < 2
                or any(part in ("", ".", "..") for part in path.parts)
            ):
                raise DistributionError("distribution archive has a non-canonical member path")
            relative = PurePosixPath(*path.parts[1:]).as_posix()
            if relative in payloads:
                raise DistributionError("distribution archive has duplicate member names")
            if info.compress_type != zipfile.ZIP_STORED or info.flag_bits & 0x1:
                raise DistributionError("distribution archive members must be stored and unencrypted")
            mode = (info.external_attr >> 16) & 0xFFFF
            if mode and not stat.S_ISREG(mode):
                raise DistributionError("distribution archive contains a non-regular member")
            total += info.file_size
            if info.file_size < 0 or info.file_size > SOURCE_FILE_BYTES_MAX or total > SOURCE_AGGREGATE_BYTES_MAX:
                raise DistributionError("distribution archive exceeds its decoded-byte ceiling")
            with archive.open(info, "r") as source:
                member = source.read(info.file_size + 1)
                if len(member) != info.file_size:
                    raise DistributionError("distribution archive member size is inconsistent")
            payloads[relative] = member
    return payloads


def _receipt(content: bytes, payloads: Mapping[str, bytes], manifest: Mapping[str, Any]) -> dict[str, Any]:
    privacy_complete = manifest["privacy_review"]["status"] == "passed"
    return {
        "schema_version": RECEIPT_SCHEMA,
        "status": (
            "unpublished_distribution_candidate_validated"
            if privacy_complete
            else "private_package_review_candidate_validated"
        ),
        "dataset_id": DATASET_ID,
        "dataset_title": DATASET_TITLE,
        "archive_size_bytes": len(content),
        "archive_sha256": _sha256(content),
        "member_count": len(payloads),
        "member_projection_sha256": _sha256(
            _canonical_json(
                [
                    {"path": name, "size_bytes": len(payloads[name]), "sha256": _sha256(payloads[name])}
                    for name in sorted(payloads)
                ]
            )
        ),
        "source_manifest_sha256": manifest["source_manifest_authority"]["sha256"],
        "collection_definition_sha256": manifest["source_collection_definition_authority"]["sha256"],
        "release_authority_sha256": manifest["release_authority_sha256"],
        # Tool and parser source belong to the qualification receipt, not the
        # licensed dataset payload.  This keeps the exact archive reproducible
        # when implementation bytes move while every admitted scientific
        # projection remains unchanged.
        "implementation_authority": _implementation_authority(),
        "resolved_collection_definition_sha256": manifest["resolved_collection_definition_sha256"],
        "license": LICENSE,
        "creator_display_name": manifest["creator_display_name"],
        "licensor_display_name": manifest["licensor_display_name"],
        "external_publication_citation_count": 0,
        "privacy_review_complete": privacy_complete,
        "correction": "None",
        "raw_publication_performed": False,
    }


def build_distribution(
    *,
    source_manifest_path: Path,
    collection_definition_path: Path,
    release_authority_path: Path,
    source_dir: Path,
    output_path: Path,
    verify_native: bool = True,
) -> dict[str, Any]:
    _reject_spectrochempy_loaded()
    source_manifest, _source_bytes, source_sha = _json_snapshot(source_manifest_path, label="source manifest")
    definition, _definition_bytes, definition_sha = _json_snapshot(
        collection_definition_path, label="collection definition"
    )
    authority, authority_bytes, _authority_sha = _json_snapshot(release_authority_path, label="release authority")
    rows, _required = _validate_source_authorities(source_manifest, definition)
    sources = _source_snapshot(source_dir, rows)
    payloads = _package_payloads(
        source_manifest=source_manifest,
        source_manifest_sha256=source_sha,
        definition=definition,
        definition_sha256=definition_sha,
        release_authority=authority,
        release_authority_bytes=authority_bytes,
        sources=sources,
        verify_native=verify_native,
    )
    content = _zip_bytes(payloads)
    _write_new_private(output_path, content)
    receipt = validate_distribution(
        archive_path=output_path,
        source_manifest_path=source_manifest_path,
        collection_definition_path=collection_definition_path,
        release_authority_path=release_authority_path,
        verify_native=verify_native,
    )
    _reject_spectrochempy_loaded()
    return receipt


def preflight_sources(
    *,
    source_manifest_path: Path,
    collection_definition_path: Path,
    source_dir: Path,
    verify_native: bool = True,
) -> dict[str, Any]:
    """Re-admit the frozen sources without claiming release approval."""

    _reject_spectrochempy_loaded()
    source_manifest, _source_bytes, source_sha = _json_snapshot(source_manifest_path, label="source manifest")
    definition, _definition_bytes, definition_sha = _json_snapshot(
        collection_definition_path, label="collection definition"
    )
    rows, required_citations = _validate_source_authorities(source_manifest, definition)
    sources = _source_snapshot(source_dir, rows)
    parser_projection: list[dict[str, Any]] = []
    if verify_native:
        for row in rows:
            name = str(row["distribution_filename"])
            observed = _native_projection(name, sources[name])
            for field in (
                "format_id",
                "variant",
                "parser_id",
                "parser_version",
                "asset_id",
                "shape",
                "axis_units",
                "value_units",
                "values_sha256",
                "axis_sha256",
            ):
                if observed[field] != row[field]:
                    raise DistributionError(f"source {name} parser projection changed at {field}")
            parser_projection.append({"sample_id": row["sample_id"], **observed})
    receipt = {
        "schema_version": "spectrasherpa-avatar-essential-oils-distribution-preflight/1",
        "status": "source_science_admitted_release_authority_pending",
        "dataset_id": DATASET_ID,
        "source_manifest_sha256": source_sha,
        "collection_definition_sha256": definition_sha,
        "file_count": len(rows),
        "specimen_count": len({row["specimen_id"] for row in rows}),
        "blocks": sorted({row["block"] for row in rows}),
        "total_source_bytes": sum(len(content) for content in sources.values()),
        "source_projection_sha256": _sha256(
            _canonical_json(
                [
                    {
                        "sample_id": row["sample_id"],
                        "sha256": row["curated_sha256"],
                        "size_bytes": row["size_bytes"],
                        "values_sha256": row["values_sha256"],
                        "axis_sha256": row["axis_sha256"],
                    }
                    for row in rows
                ]
            )
        ),
        "native_parser_projection_sha256": _sha256(_canonical_json(parser_projection)) if verify_native else None,
        "implementation_authority": _implementation_authority(),
        "historical_pending_citation_specimen_ids": sorted(required_citations),
        "required_release_authorities": [
            "creator_display_name",
            "licensor_display_name",
            "canonical_attribution_statement",
            "laboratory_origin_no_external_publication_citations",
            "repeated_privacy_and_package_content_review",
        ],
        "archive_created": False,
    }
    _reject_spectrochempy_loaded()
    return receipt


def validate_distribution(
    *,
    archive_path: Path,
    source_manifest_path: Path,
    collection_definition_path: Path,
    release_authority_path: Path,
    verify_native: bool = True,
) -> dict[str, Any]:
    _reject_spectrochempy_loaded()
    content = _read_regular(archive_path, limit=ARCHIVE_BYTES_MAX, label="distribution archive")
    payloads = _archive_payloads(content)
    source_manifest, _source_bytes, source_sha = _json_snapshot(source_manifest_path, label="source manifest")
    definition, _definition_bytes, definition_sha = _json_snapshot(
        collection_definition_path, label="collection definition"
    )
    authority, authority_bytes, _authority_sha = _json_snapshot(release_authority_path, label="release authority")
    rows, _required = _validate_source_authorities(source_manifest, definition)
    expected_names = {str(row["distribution_filename"]) for row in rows}
    archived_sources: dict[str, bytes] = {}
    for relative, member in payloads.items():
        path = PurePosixPath(relative)
        if len(path.parts) == 2 and path.parts[0] == "data":
            archived_sources[path.parts[1]] = member
    if set(archived_sources) != expected_names:
        raise DistributionError("distribution archive does not contain the exact raw source inventory")
    expected = _package_payloads(
        source_manifest=source_manifest,
        source_manifest_sha256=source_sha,
        definition=definition,
        definition_sha256=definition_sha,
        release_authority=authority,
        release_authority_bytes=authority_bytes,
        sources=archived_sources,
        verify_native=verify_native,
    )
    if payloads != expected:
        raise DistributionError("distribution archive bytes do not equal the reconstructed closed package")
    manifest = _parse_json(payloads["manifest.json"], label="package manifest")
    if not isinstance(manifest, Mapping):
        raise DistributionError("package manifest must be one object")
    _exact_fields(manifest, _PACKAGE_MANIFEST_FIELDS, label="package manifest")
    receipt = _receipt(content, payloads, manifest)
    _reject_spectrochempy_loaded()
    return receipt


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    preflight = subparsers.add_parser("preflight-sources")
    preflight.add_argument("--source-manifest", type=Path, required=True)
    preflight.add_argument("--collection-definition", type=Path, required=True)
    preflight.add_argument("--source-dir", type=Path, required=True)
    for name in ("build", "validate"):
        command = subparsers.add_parser(name)
        command.add_argument("--source-manifest", type=Path, required=True)
        command.add_argument("--collection-definition", type=Path, required=True)
        command.add_argument("--release-authority", type=Path, required=True)
        command.add_argument("--archive", type=Path, required=True)
        if name == "build":
            command.add_argument("--source-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.command == "preflight-sources":
        receipt = preflight_sources(
            source_manifest_path=args.source_manifest,
            collection_definition_path=args.collection_definition,
            source_dir=args.source_dir,
        )
    elif args.command == "build":
        receipt = build_distribution(
            source_manifest_path=args.source_manifest,
            collection_definition_path=args.collection_definition,
            release_authority_path=args.release_authority,
            source_dir=args.source_dir,
            output_path=args.archive,
        )
    else:
        receipt = validate_distribution(
            archive_path=args.archive,
            source_manifest_path=args.source_manifest,
            collection_definition_path=args.collection_definition,
            release_authority_path=args.release_authority,
        )
    print(json.dumps(receipt, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
