from __future__ import annotations

import ast
import copy
import functools
import hashlib
import importlib.util
import io
import json
import os
import stat
import struct
import subprocess
import tempfile
import zipfile
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from spectra_sherpa.core.file_io import open_regular_readonly

REPO_ROOT = Path(__file__).parents[3]
TOOL_PATH = REPO_ROOT / "packages" / "spectra-sherpa" / "tools" / "avatar_omnic_corpus.py"
EXTERNAL_TOOL_PATH = REPO_ROOT / "packages" / "spectra-sherpa" / "tools" / "avatar_omnic_external_comparator.py"
SPEC = importlib.util.spec_from_file_location("avatar_omnic_corpus", TOOL_PATH)
assert SPEC is not None and SPEC.loader is not None
TOOL = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(TOOL)
EXTERNAL_SPEC = importlib.util.spec_from_file_location("avatar_omnic_external_comparator", EXTERNAL_TOOL_PATH)
assert EXTERNAL_SPEC is not None and EXTERNAL_SPEC.loader is not None
EXTERNAL_TOOL = importlib.util.module_from_spec(EXTERNAL_SPEC)
EXTERNAL_SPEC.loader.exec_module(EXTERNAL_TOOL)
PUBLIC_MANIFEST_PATH = REPO_ROOT / "docs" / "evidence" / "avatar-essential-oils-v1-manifest.json"
LICENSE_AUTHORIZATION_PATH = REPO_ROOT / "docs" / "evidence" / "avatar-essential-oils-v1-license-authorization.json"
RELEASE_AUTHORITY_PATH = REPO_ROOT / "docs" / "evidence" / "avatar-lavender-essential-oils-v1-release-authority.json"
PRIVATE_PACKAGE_REVIEW_PATH = (
    REPO_ROOT / "docs" / "evidence" / "avatar-lavender-essential-oils-v1-private-package-review.json"
)
QUALIFICATION_PATH = (
    REPO_ROOT / "docs" / "evidence" / "avatar-lavender-essential-oils-v1-distribution-qualification.json"
)
PUBLICATION_DECISION_PATH = REPO_ROOT / "docs" / "evidence" / "avatar-essential-oils-v1-publication-decision.json"
PUBLIC_MANIFEST_SHA256 = "171b74c2abca681d47d65b286629492b9435832ca3aac200504cc4ee125ca85a"
LICENSE_AUTHORIZATION_SHA256 = "7cef134d44482792eeec4dc2787eb4a0ba134eb5df7a197a5d496d48e9d999d5"
PRIVATE_REVIEW_RELEASE_AUTHORITY_SHA256 = "57c65ad2a284af3c92e15eba4c9251898edaa7c8376957e5954d1267befcbe9a"
RELEASE_AUTHORITY_SHA256 = "ac5356f3fbbf52221f4ad20a79dce7c14533b1321a5d0b3662603f5a4d93aa77"
PRIVATE_PACKAGE_REVIEW_SHA256 = "0e616d0b6c20d982d82040ce5c54a413575524c9139db547453b925698561a4e"
QUALIFICATION_SHA256 = "1238b0fb5ac3e845b1c3b8c5f9ea65b3419f367a49ccab32567445e1c48f0d8d"
PUBLICATION_DECISION_SHA256 = "fd1fb8a205528acbd3f499d163a1f0a39f32d30f55eb600bc09f779d1545f470"
TRACKED_BLOB_BYTES_MAX = 64 * 1024 * 1024
TRACKED_REPOSITORY_BYTES_MAX = 128 * 1024 * 1024
TRACKED_ARCHIVE_MEMBER_COUNT_MAX = 10_000
TRACKED_ARCHIVE_DIRECTORY_BYTES_MAX = 8 * 1024 * 1024
TRACKED_ARCHIVE_TRAILER_BYTES_MAX = 1024 * 1024
TRACKED_ENTRY_COUNT_MAX = 10_000
TRACKED_INDEX_BYTES_MAX = 16 * 1024 * 1024
TRACKED_PATH_BYTES_MAX = 4096
TRACKED_PATHS_BYTES_MAX = 8 * 1024 * 1024
GOVERNANCE_JSON_BYTES_MAX = 4 * 1024 * 1024


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _governance_json_snapshot(path: Path) -> tuple[Any, str]:
    try:
        descriptor = open_regular_readonly(path)
    except OSError as exc:
        raise AssertionError(f"governance authority cannot be opened without following links: {path}") from exc
    try:
        observed = os.fstat(descriptor)
        if not stat.S_ISREG(observed.st_mode):
            raise AssertionError(f"governance authority must be one regular file: {path}")
        if observed.st_size > GOVERNANCE_JSON_BYTES_MAX:
            raise AssertionError(f"governance authority exceeds the byte ceiling: {path}")
        chunks: list[bytes] = []
        retained = 0
        while True:
            chunk = os.read(descriptor, min(1024 * 1024, GOVERNANCE_JSON_BYTES_MAX + 1 - retained))
            if not chunk:
                break
            chunks.append(chunk)
            retained += len(chunk)
            if retained > GOVERNANCE_JSON_BYTES_MAX:
                raise AssertionError(f"governance authority exceeds the byte ceiling: {path}")
        content = b"".join(chunks)
        if len(content) != observed.st_size:
            raise AssertionError(f"governance authority changed while it was read: {path}")
    finally:
        os.close(descriptor)

    def unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise AssertionError(f"governance authority contains duplicate JSON key {key!r}: {path}")
            result[key] = value
        return result

    try:
        parsed = json.loads(content.decode("utf-8"), object_pairs_hook=unique_object)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise AssertionError(f"governance authority is not exact UTF-8 JSON: {path}") from exc
    return parsed, hashlib.sha256(content).hexdigest()


def _load_governance_json(path: Path) -> Any:
    return _governance_json_snapshot(path)[0]


def _zip_directory_preflight(content: bytes) -> int | None:
    if len(content) < 22:
        return None
    search_start = max(0, len(content) - 65_557 - TRACKED_ARCHIVE_TRAILER_BYTES_MAX)
    eocd_offset = content.rfind(b"PK\x05\x06", search_start)
    if eocd_offset < 0:
        return None
    if eocd_offset + 22 > len(content):
        raise AssertionError("tracked archive EOCD is truncated")
    (
        _signature,
        disk_number,
        directory_disk,
        entries_on_disk,
        entry_count,
        directory_size,
        directory_offset,
        comment_size,
    ) = struct.unpack_from("<4s4H2LH", content, eocd_offset)
    record_end = eocd_offset + 22 + comment_size
    if record_end > len(content):
        raise AssertionError("tracked archive EOCD comment is truncated")
    if len(content) - record_end > TRACKED_ARCHIVE_TRAILER_BYTES_MAX:
        raise AssertionError("tracked archive trailer exceeds the byte ceiling")

    directory_boundary = eocd_offset
    if (
        entries_on_disk == 0xFFFF
        or entry_count == 0xFFFF
        or directory_size == 0xFFFFFFFF
        or directory_offset == 0xFFFFFFFF
    ):
        locator_offset = eocd_offset - 20
        if locator_offset < 0:
            raise AssertionError("tracked ZIP64 archive is missing its locator")
        locator_signature, zip64_disk, zip64_offset, total_disks = struct.unpack_from("<4sLQL", content, locator_offset)
        if locator_signature != b"PK\x06\x07" or zip64_disk != 0 or total_disks != 1:
            raise AssertionError("tracked ZIP64 archive has an unsupported disk layout")
        if zip64_offset + 56 > locator_offset:
            raise AssertionError("tracked ZIP64 EOCD is outside the admitted bounds")
        (
            zip64_signature,
            zip64_record_size,
            _version_made,
            _version_needed,
            zip64_disk_number,
            zip64_directory_disk,
            zip64_entries_on_disk,
            zip64_entry_count,
            zip64_directory_size,
            zip64_directory_offset,
        ) = struct.unpack_from("<4sQ2H2L4Q", content, zip64_offset)
        if zip64_signature != b"PK\x06\x06" or zip64_record_size < 44:
            raise AssertionError("tracked ZIP64 EOCD is malformed")
        if zip64_offset + 12 + zip64_record_size > locator_offset:
            raise AssertionError("tracked ZIP64 EOCD exceeds its admitted bounds")
        disk_number = zip64_disk_number
        directory_disk = zip64_directory_disk
        entries_on_disk = zip64_entries_on_disk
        entry_count = zip64_entry_count
        directory_size = zip64_directory_size
        directory_offset = zip64_directory_offset
        directory_boundary = zip64_offset

    if disk_number != 0 or directory_disk != 0 or entries_on_disk != entry_count:
        raise AssertionError("tracked archive uses an unsupported multi-disk layout")
    if entry_count > TRACKED_ARCHIVE_MEMBER_COUNT_MAX:
        raise AssertionError("tracked archive exceeds the member-count ceiling")
    if directory_size > TRACKED_ARCHIVE_DIRECTORY_BYTES_MAX:
        raise AssertionError("tracked archive central directory exceeds the byte ceiling")
    if directory_offset + directory_size > directory_boundary:
        raise AssertionError("tracked archive central directory is outside the admitted bounds")

    directory_end = directory_offset + directory_size
    cursor = directory_offset
    observed_entries = 0
    while cursor < directory_end:
        if directory_end - cursor < 46:
            raise AssertionError("tracked archive central directory entry is truncated")
        (
            signature,
            _version_made,
            _version_needed,
            _flags,
            _compression,
            _modified_time,
            _modified_date,
            _crc32,
            _compressed_size,
            _uncompressed_size,
            name_size,
            extra_size,
            member_comment_size,
            _member_disk,
            _internal_attributes,
            _external_attributes,
            _local_header_offset,
        ) = struct.unpack_from("<4s6H3L5H2L", content, cursor)
        if signature != b"PK\x01\x02":
            raise AssertionError("tracked archive central directory signature is missing")
        observed_entries += 1
        if observed_entries > TRACKED_ARCHIVE_MEMBER_COUNT_MAX:
            raise AssertionError("tracked archive exceeds the member-count ceiling")
        cursor += 46 + name_size + extra_size + member_comment_size
        if cursor > directory_end:
            raise AssertionError("tracked archive central directory entry exceeds its admitted bounds")
    if cursor != directory_end:
        raise AssertionError("tracked archive central directory has trailing bytes")
    if observed_entries != entry_count:
        raise AssertionError("tracked archive member count disagrees with its central directory")
    return observed_entries


def _zip_member_records(content: bytes) -> tuple[dict[str, Any], ...]:
    expected_entry_count = _zip_directory_preflight(content)
    if expected_entry_count is None:
        return ()
    with zipfile.ZipFile(io.BytesIO(content)) as archive:
        all_infos = archive.infolist()
        if len(all_infos) != expected_entry_count:
            raise AssertionError("tracked archive member count disagrees with its EOCD")
        infos = [info for info in all_infos if not info.is_dir()]
        if any(info.file_size < 0 or info.file_size > TRACKED_BLOB_BYTES_MAX for info in infos):
            raise AssertionError("tracked archive member exceeds the byte ceiling")
        if sum(info.file_size for info in infos) > TRACKED_BLOB_BYTES_MAX:
            raise AssertionError("tracked archive exceeds the decoded-byte ceiling")
        records: list[dict[str, Any]] = []
        for info in infos:
            digest = hashlib.sha256()
            observed = 0
            with archive.open(info, "r") as source:
                while chunk := source.read(1024 * 1024):
                    observed += len(chunk)
                    if observed > info.file_size:
                        raise AssertionError("tracked archive member expanded beyond its declared size")
                    digest.update(chunk)
            if observed != info.file_size:
                raise AssertionError("tracked archive member size does not match its declaration")
            records.append(
                {
                    "name": info.filename,
                    "size_bytes": observed,
                    "sha256": digest.hexdigest(),
                }
            )
    return tuple(records)


def _bounded_git_stdout(
    arguments: list[str],
    *,
    max_bytes: int,
    input_bytes: bytes | None = None,
) -> bytes:
    with tempfile.TemporaryFile() if input_bytes is not None else open(os.devnull, "rb") as stdin_file:
        if input_bytes is not None:
            stdin_file.write(input_bytes)
            stdin_file.seek(0)
        process = subprocess.Popen(
            arguments,
            cwd=REPO_ROOT,
            stdin=stdin_file,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        assert process.stdout is not None and process.stderr is not None
        chunks: list[bytes] = []
        observed = 0
        while chunk := process.stdout.read(min(1024 * 1024, max_bytes - observed + 1)):
            observed += len(chunk)
            if observed > max_bytes:
                process.kill()
                process.wait()
                raise AssertionError("git census output exceeds its byte ceiling")
            chunks.append(chunk)
        return_code = process.wait()
        stderr = process.stderr.read()
        if return_code != 0:
            raise AssertionError(f"git census command failed: {stderr.decode(errors='replace')}")
        return b"".join(chunks)


def _parse_git_index(index: bytes) -> tuple[tuple[str, str, str], ...]:
    if len(index) > TRACKED_INDEX_BYTES_MAX:
        raise AssertionError("tracked repository index exceeds the byte ceiling")
    entries: list[tuple[str, str, str]] = []
    seen_paths: set[str] = set()
    path_bytes_total = 0
    offset = 0
    while offset < len(index):
        end = index.find(b"\0", offset)
        if end < 0:
            raise AssertionError("tracked repository index is not NUL terminated")
        raw = index[offset:end]
        offset = end + 1
        if not raw:
            raise AssertionError("tracked repository index contains an empty entry")
        if len(entries) >= TRACKED_ENTRY_COUNT_MAX:
            raise AssertionError("tracked repository exceeds the entry-count ceiling")
        metadata, separator, path_bytes = raw.partition(b"\t")
        if not separator or not path_bytes or len(path_bytes) > TRACKED_PATH_BYTES_MAX:
            raise AssertionError("tracked repository path is absent or exceeds its byte ceiling")
        path_bytes_total += len(path_bytes)
        if path_bytes_total > TRACKED_PATHS_BYTES_MAX:
            raise AssertionError("tracked repository paths exceed the aggregate byte ceiling")
        mode, object_id, stage = metadata.decode("ascii").split()
        if stage != "0":
            raise AssertionError("tracked repository contains an unresolved index stage")
        if len(object_id) not in {40, 64} or any(character not in "0123456789abcdef" for character in object_id):
            raise AssertionError("tracked repository object identity is malformed")
        path = path_bytes.decode("utf-8")
        portable_path = Path(path)
        if portable_path.is_absolute() or ".." in portable_path.parts or path in seen_paths:
            raise AssertionError("tracked repository path is noncanonical or duplicated")
        seen_paths.add(path)
        entries.append((path, mode, object_id))
    return tuple(entries)


@functools.lru_cache(maxsize=1)
def _tracked_repository_records() -> tuple[dict[str, Any], ...]:
    index = _bounded_git_stdout(
        ["git", "ls-files", "-s", "-z"],
        max_bytes=TRACKED_INDEX_BYTES_MAX,
    )
    entries = _parse_git_index(index)

    object_ids = list(dict.fromkeys(object_id for _path, _mode, object_id in entries))
    query = ("\n".join(object_ids) + "\n").encode("ascii")
    size_output = _bounded_git_stdout(
        ["git", "cat-file", "--batch-check=%(objectname) %(objecttype) %(objectsize)"],
        input_bytes=query,
        max_bytes=max(1024, len(object_ids) * 100),
    )
    size_lines = size_output.splitlines()
    if len(size_lines) != len(object_ids):
        raise AssertionError("git batch-check result count changed")
    sizes: dict[str, int] = {}
    for expected_id, line in zip(object_ids, size_lines, strict=True):
        object_id, object_type, size_text = line.decode("ascii").split()
        if object_id != expected_id or object_type != "blob":
            raise AssertionError("tracked repository entry is not a blob")
        size = int(size_text)
        if size < 0 or size > TRACKED_BLOB_BYTES_MAX:
            raise AssertionError("tracked repository blob exceeds the byte ceiling")
        sizes[object_id] = size
    if sum(sizes.values()) > TRACKED_REPOSITORY_BYTES_MAX:
        raise AssertionError("tracked repository exceeds the aggregate census ceiling")

    batch = _bounded_git_stdout(
        ["git", "cat-file", "--batch"],
        input_bytes=query,
        max_bytes=sum(sizes.values()) + len(object_ids) * 100,
    )
    contents: dict[str, bytes] = {}
    offset = 0
    for expected_id in object_ids:
        line_end = batch.index(b"\n", offset)
        object_id, object_type, size_text = batch[offset:line_end].decode("ascii").split()
        if object_id != expected_id or object_type != "blob":
            raise AssertionError("git blob census returned an unexpected object")
        size = int(size_text)
        if size != sizes[expected_id]:
            raise AssertionError("git blob size changed after batch-check admission")
        start = line_end + 1
        end = start + size
        if batch[end : end + 1] != b"\n":
            raise AssertionError("git blob census framing is malformed")
        contents[object_id] = batch[start:end]
        offset = end + 1
    if offset != len(batch):
        raise AssertionError("git blob census returned trailing data")

    object_records = {
        object_id: {
            "size_bytes": len(content),
            "sha256": hashlib.sha256(content).hexdigest(),
            "archive_members": _zip_member_records(content),
        }
        for object_id, content in contents.items()
    }
    records: list[dict[str, Any]] = []
    for path, mode, object_id in entries:
        records.append(
            {
                "path": path,
                "mode": mode,
                **object_records[object_id],
            }
        )
    return tuple(records)


def _fake_custody(
    curated_dir: Path,
) -> tuple[dict[str, Any], dict[str, dict[str, Any]], dict[int, Path], dict[int, str]]:
    rows: list[dict[str, Any]] = []
    inspections: dict[str, dict[str, Any]] = {}
    archive_members: dict[int, list[tuple[str, bytes]]] = {1: [], 2: [], 3: []}
    for block in (1, 2, 3):
        for order, specimen in enumerate(TOOL.EXPECTED_ORDER[block], start=1):
            name = TOOL.canonical_filename(specimen, block)
            member_name = f"source-{block}-{order}.spa"
            payload = (hashlib.sha256(f"source:{block}:{specimen}".encode()).digest() * 13)[:400]
            (curated_dir / name).write_bytes(payload)
            archive_members[block].append((member_name, payload))
            metadata = {
                "acquired_at": f"2026-08-24T0{block}:{order:02d}:00+00:00",
                "header": {"scan_count": 16},
                "shape": [1, 1868],
                "axis_units": "cm-1",
                "value_units": "absorbance",
                "data_quantity": "absorbance",
            }
            inspection = {
                "source_sha256": _sha(payload),
                "size_bytes": len(payload),
                "embedded_title": TOOL.canonical_title(specimen, block),
                "acquired_at": metadata["acquired_at"],
                "format_id": "omnic",
                "variant": "spa-single-spectrum",
                "parser_id": "spectrasherpa.omnic",
                "parser_version": "1",
                "asset_id": "spectrum",
                "shape": [1, 1868],
                "axis_units": "cm-1",
                "value_units": "absorbance",
                "values_sha256": _sha(f"values:{block}:{specimen}".encode()),
                "axis_sha256": "a" * 64,
                "qualified_parser_metadata_sha256": TOOL._json_sha256(metadata),
                "qualified_parser_metadata": metadata,
            }
            inspections[name] = inspection
            inspections[member_name] = inspection
            rows.append(
                {
                    "block": block,
                    "acquisition_order": order,
                    "specimen_id": specimen,
                    "label_status": "acquired_label_verified",
                    "archive_member": member_name,
                    **inspection,
                }
            )
        for excluded_index in (1, 2):
            member_name = f"excluded-{block}-{excluded_index}.spa"
            data = bytes([block, excluded_index]) * 200
            archive_members[block].append((member_name, data))
            inspections[member_name] = {
                **inspections[f"source-{block}-11.spa"],
                "source_sha256": _sha(data),
                "size_bytes": len(data),
                "embedded_title": f"private-excluded-{block}-{excluded_index}",
                "acquired_at": f"2026-08-24T0{block}:{11 + excluded_index:02d}:00+00:00",
            }

    archives: dict[int, Path] = {}
    archive_hashes: dict[int, str] = {}
    archive_rows: list[dict[str, Any]] = []
    for block in (1, 2, 3):
        path = curated_dir.parent / f"fake-block-{block}.zip"
        with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_STORED) as handle:
            for member_name, data in archive_members[block]:
                handle.writestr(member_name, data)
        content = path.read_bytes()
        archives[block] = path
        archive_hashes[block] = _sha(content)
        archive_rows.append(
            {
                "block": block,
                "archive_name": path.name,
                "sha256": archive_hashes[block],
                "size_bytes": len(content),
                "member_count": 13,
                "excluded_member_count": 2,
            }
        )
    inventory = {
        "schema_version": TOOL.PRIVATE_SCHEMA,
        "dataset_id": TOOL.DATASET_ID,
        "privacy": {
            "classification": "private_acquisition_authority",
            "supplier_crosswalk_present": False,
            "manual_metadata_review": "passed",
            "redistribution_intent": "author_approved_open_curation",
        },
        "archives": archive_rows,
        "files": rows,
    }
    return inventory, inspections, archives, archive_hashes


def _build_fake_manifest(curated_dir: Path) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    inventory, inspections, archives, archive_hashes = _fake_custody(curated_dir)
    frozen = TOOL.ARCHIVE_SHA256
    TOOL.ARCHIVE_SHA256 = archive_hashes
    try:
        manifest = TOOL.build_public_manifest(
            inventory,
            archives,
            curated_dir,
            inspector=lambda path: inspections[path.name],
        )
    finally:
        TOOL.ARCHIVE_SHA256 = frozen
    return manifest, inspections


def _fake_phase2_sources(
    tmp_path: Path,
) -> tuple[
    Path,
    Path,
    Path,
    dict[str, dict[str, Any]],
    dict[str, tuple[np.ndarray, np.ndarray]],
]:
    curated = tmp_path / "curated"
    curated.mkdir()
    manifest, inspections = _build_fake_manifest(curated)
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(manifest))
    axis = np.linspace(4000.0, 400.0, 1868, dtype=np.float64)
    arrays: dict[str, tuple[np.ndarray, np.ndarray]] = {}
    for index, row in enumerate(manifest["files"], start=1):
        sample_id = row["sample_id"]
        peak = 0.2 + index * 1e-5
        if sample_id == "MSL__B1":
            peak = 0.1
        elif sample_id == "ACFL__B2":
            peak = 0.3
        arrays[sample_id] = (np.linspace(0.0, peak, 1868), axis.copy())

    external_report_path = tmp_path / "external-report.json"
    external_report_path.write_text(
        json.dumps(
            {
                "schema_version": "spectrasherpa-avatar-external-omnic-comparison/1",
                "converter": TOOL.EXTERNAL_OMNIC_COMPARATOR,
                "source_manifest_sha256": _sha(manifest_path.read_bytes()),
                "execution": {
                    "network_access": "python_socket_dns_blocked",
                    "spectrasherpa_imported": False,
                    "comparison_scope": "all_33_complete_axis_and_ordinate_arrays",
                },
                "files": [
                    {
                        "sample_id": row["sample_id"],
                        "spa_sha256": row["curated_sha256"],
                        "shape": [1, 1868],
                        "point_count": 1868,
                        "axis_order": "strictly_descending",
                        "axis_units": "cm^-1",
                        "value_units": "absorbance",
                        "external_values_sha256": row["values_sha256"],
                        "external_axis_sha256": row["axis_sha256"],
                    }
                    for row in manifest["files"]
                ],
            }
        )
    )
    return manifest_path, curated, external_report_path, inspections, arrays


def test_frozen_identity_is_exactly_eleven_oils_in_three_blocks() -> None:
    assert len(TOOL.SPECIMEN_METADATA) == 11
    assert set(TOOL.EXPECTED_ORDER) == {1, 2, 3}
    assert all(order == TOOL.COMMON_ORDER and len(order) == 11 for order in TOOL.EXPECTED_ORDER.values())


def test_private_inventory_selects_only_the_exact_oil_titles(tmp_path: Path) -> None:
    curated = tmp_path / "curated"
    curated.mkdir()
    _inventory, inspections, archives, archive_hashes = _fake_custody(curated)
    frozen = TOOL.ARCHIVE_SHA256
    TOOL.ARCHIVE_SHA256 = archive_hashes
    try:
        inventory = TOOL.build_private_inventory(
            archives,
            manual_metadata_review="passed",
            inspector=lambda path: inspections[path.name],
        )
    finally:
        TOOL.ARCHIVE_SHA256 = frozen
    assert len(inventory["files"]) == 33
    assert all(row["excluded_member_count"] == 2 for row in inventory["archives"])


def test_public_manifest_builds_closed_33_file_boundary(tmp_path: Path) -> None:
    curated = tmp_path / "curated"
    curated.mkdir()
    manifest, inspections = _build_fake_manifest(curated)
    assert (
        TOOL.validate_public_manifest(manifest, curated_dir=curated, inspector=lambda path: inspections[path.name])
        == []
    )
    assert len(manifest["files"]) == 33
    assert all(row["curation_equivalence"] == "byte_identical" for row in manifest["files"])
    assert manifest["instrument"]["correction"] == "None"
    assert TOOL._public_privacy_failures(manifest) == []


@pytest.mark.parametrize(
    ("mutation", "expected"),
    (
        ({"supplier_name": "private"}, "private key"),
        ({"operator_email": "scientist@example.org"}, "private-looking value"),
        ({"storage_note": "/srv/spectra/private/file.spa"}, "private-looking value"),
        ({"curation_note": "CORR-001"}, "private-looking value"),
    ),
)
def test_public_manifest_rejects_private_surfaces(tmp_path: Path, mutation: dict[str, str], expected: str) -> None:
    curated = tmp_path / "curated"
    curated.mkdir()
    manifest, inspections = _build_fake_manifest(curated)
    manifest["files"][0].update(mutation)
    failures = TOOL.validate_public_manifest(
        manifest, curated_dir=curated, inspector=lambda path: inspections[path.name]
    )
    assert any(expected in failure for failure in failures)


def test_public_manifest_rejects_wrong_curated_bytes(tmp_path: Path) -> None:
    curated = tmp_path / "curated"
    curated.mkdir()
    manifest, inspections = _build_fake_manifest(curated)
    (curated / manifest["files"][0]["distribution_filename"]).write_bytes(b"changed")
    failures = TOOL.validate_public_manifest(
        manifest, curated_dir=curated, inspector=lambda path: inspections[path.name]
    )
    assert any("digest mismatch" in failure for failure in failures)


def test_public_verification_requires_curated_files(tmp_path: Path) -> None:
    curated = tmp_path / "curated"
    curated.mkdir()
    manifest, _inspections = _build_fake_manifest(curated)
    with pytest.raises(TypeError, match="curated_dir"):
        TOOL.validate_public_manifest(manifest)


def test_public_manifest_rejects_load_bearing_mutations(tmp_path: Path) -> None:
    curated = tmp_path / "curated"
    curated.mkdir()
    manifest, inspections = _build_fake_manifest(curated)
    mutations = (
        lambda value: value["files"][0].__setitem__("sample_id", "wrong"),
        lambda value: value["files"][0].__setitem__("acquisition_order", 99),
        lambda value: value["files"][0].__setitem__("shape", [1868, 1]),
        lambda value: value["files"][0].__setitem__("values_sha256", "0" * 64),
        lambda value: value.__setitem__("dataset_license", "provided by operator"),
        lambda value: value.__setitem__("status", "distribution_qualified"),
        lambda value: value["instrument"].__setitem__("correction", "ATR"),
    )
    for mutate in mutations:
        changed = copy.deepcopy(manifest)
        mutate(changed)
        assert TOOL.validate_public_manifest(
            changed, curated_dir=curated, inspector=lambda path: inspections[path.name]
        )


def test_post_inventory_whole_row_swap_cannot_stage(tmp_path: Path) -> None:
    curated = tmp_path / "curated"
    curated.mkdir()
    inventory, inspections, archives, archive_hashes = _fake_custody(curated)
    first, second = inventory["files"][0], inventory["files"][1]
    identity_fields = {"block", "acquisition_order", "specimen_id", "label_status"}
    for field in TOOL._PRIVATE_FILE_FIELDS - identity_fields:
        first[field], second[field] = second[field], first[field]
    frozen = TOOL.ARCHIVE_SHA256
    TOOL.ARCHIVE_SHA256 = archive_hashes
    try:
        with pytest.raises(TOOL.CorpusError, match="source title does not prove"):
            TOOL.stage_curated_files(
                inventory,
                archives,
                tmp_path / "staged",
                inspector=lambda path: inspections[path.name],
            )
    finally:
        TOOL.ARCHIVE_SHA256 = frozen


@pytest.mark.parametrize("timestamp", (None, "2026-08-23T13:00:00", "not-a-time"))
def test_private_inventory_rejects_missing_naive_or_invalid_timestamp(timestamp: Any) -> None:
    with pytest.raises(TOOL.CorpusError, match="timestamp"):
        TOOL._parse_unique_timestamp(timestamp, source_name="source.spa")


def test_private_inventory_rejects_equal_timestamps() -> None:
    timestamp = "2026-08-23T13:00:00-07:00"
    with pytest.raises(TOOL.CorpusError, match="must be unique"):
        TOOL._sort_inspected_by_timestamp(
            [("a.spa", {"acquired_at": timestamp}), ("b.spa", {"acquired_at": timestamp})], block=2
        )


def test_private_output_is_restricted_and_mode_0600(tmp_path: Path) -> None:
    with pytest.raises(TOOL.CorpusError, match="must be outside"):
        TOOL._require_private_worktree_path(REPO_ROOT / "docs" / "evidence" / "private.json")
    output = tmp_path / "private.json"
    TOOL._write_private_json(output, {"private": True})
    assert json.loads(output.read_text()) == {"private": True}
    if os.name != "nt":  # Windows uses the containing profile ACL.
        assert os.stat(output).st_mode & 0o777 == 0o600


def test_unrelated_omnic_fixture_cannot_be_used_as_avatar_source() -> None:
    fixture = (
        REPO_ROOT
        / "packages"
        / "spectra-sherpa"
        / "tests"
        / "fixtures"
        / "omnic"
        / "openspecy-polyethylene-reflectance.spa"
    )
    with pytest.raises(TOOL.CorpusError, match="expected shape"):
        TOOL.inspect_spa(fixture)


def test_phase2_report_binds_exact_structural_and_external_parity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest_path, curated, external_report, inspections, arrays = _fake_phase2_sources(tmp_path)
    monkeypatch.setattr(TOOL, "validate_public_manifest", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(TOOL, "inspect_spa", lambda path: inspections[path.name])
    monkeypatch.setattr(
        TOOL,
        "_native_arrays",
        lambda path: (*arrays[path.stem], None),
    )
    report = TOOL.build_phase2_report(manifest_path, curated, external_report)
    assert report["structural_ingestion_passed"] is True
    assert report["structural_file_count"] == 33
    assert report["external_converter_parity_verified"] is True
    assert report["external_converter_file_count"] == 33
    assert report["instrument_export_parity_verified"] is False
    assert all(row["spectrochempy_transport_absent"] for row in report["files"])
    assert all(row["external_converter_full_array_equal"] for row in report["files"])
    assert TOOL.validate_phase2_report(report, manifest_path, curated, external_report) == []


def test_phase2_refuses_missing_or_substituted_external_identity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest_path, curated, external_report, inspections, arrays = _fake_phase2_sources(tmp_path)
    external = json.loads(external_report.read_text())
    external["files"].pop()
    external["files"][0]["sample_id"] = "substituted"
    external_report.write_text(json.dumps(external))
    monkeypatch.setattr(TOOL, "validate_public_manifest", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(TOOL, "inspect_spa", lambda item: inspections[item.name])
    monkeypatch.setattr(TOOL, "_native_arrays", lambda item: (*arrays[item.stem], None))
    with pytest.raises(TOOL.CorpusError, match="exactly 33 rows"):
        TOOL.build_phase2_report(manifest_path, curated, external_report)


@pytest.mark.parametrize("field", ("spa_sha256", "external_values_sha256", "external_axis_sha256"))
def test_phase2_refuses_external_science_or_source_mismatch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, field: str
) -> None:
    manifest_path, curated, external_report, inspections, arrays = _fake_phase2_sources(tmp_path)
    external = json.loads(external_report.read_text())
    external["files"][0][field] = "0" * 64
    external_report.write_text(json.dumps(external))
    monkeypatch.setattr(TOOL, "validate_public_manifest", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(TOOL, "inspect_spa", lambda item: inspections[item.name])
    monkeypatch.setattr(TOOL, "_native_arrays", lambda item: (*arrays[item.stem], None))
    with pytest.raises(TOOL.CorpusError, match=f"external converter {field} disagrees"):
        TOOL.build_phase2_report(manifest_path, curated, external_report)


def test_phase2_validator_rejects_a_forged_pass(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    manifest_path, curated, external_report, inspections, arrays = _fake_phase2_sources(tmp_path)
    monkeypatch.setattr(TOOL, "validate_public_manifest", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(TOOL, "inspect_spa", lambda path: inspections[path.name])
    monkeypatch.setattr(TOOL, "_native_arrays", lambda path: (*arrays[path.stem], None))
    report = TOOL.build_phase2_report(manifest_path, curated, external_report)
    report["files"][0]["repeat_ingestion_identical"] = False
    assert TOOL.validate_phase2_report(report, manifest_path, curated, external_report)


def test_external_comparator_is_separate_and_exactly_pinned() -> None:
    assert EXTERNAL_TOOL.CONVERTER == TOOL.EXTERNAL_OMNIC_COMPARATOR
    tree = ast.parse(EXTERNAL_TOOL_PATH.read_text())
    imported_modules = {
        alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names
    } | {node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)}
    assert not any(name == "spectra_sherpa" or name.startswith("spectra_sherpa.") for name in imported_modules)


def test_checked_phase2_evidence_is_cross_bound_and_fails_on_mutation() -> None:
    manifest_path = REPO_ROOT / "docs" / "evidence" / "avatar-essential-oils-v1-manifest.json"
    external_path = REPO_ROOT / "docs" / "evidence" / "avatar-essential-oils-v1-external-omnic-comparison.json"
    report_path = REPO_ROOT / "docs" / "evidence" / "avatar-essential-oils-v1-parser-qualification.json"
    manifest_bytes = manifest_path.read_bytes()
    external_bytes = external_path.read_bytes()
    report = json.loads(report_path.read_text())
    assert TOOL.validate_phase2_evidence_links(report, manifest_bytes, external_bytes) == []

    changed = copy.deepcopy(report)
    changed["files"][0]["values_sha256"] = "0" * 64
    assert any(
        "native values digest is not cross-bound" in failure
        for failure in TOOL.validate_phase2_evidence_links(changed, manifest_bytes, external_bytes)
    )

    changed_external = json.loads(external_bytes)
    changed_external["execution"]["network_access"] = "blocked"
    changed_external_bytes = json.dumps(changed_external).encode()
    assert any(
        "overstates or changes its execution isolation" in failure
        for failure in TOOL.validate_phase2_evidence_links(
            report,
            manifest_bytes,
            changed_external_bytes,
        )
    )


def _release_authority_binding_failures(
    decision: dict[str, Any], expected_release_authority: dict[str, Any]
) -> list[str]:
    failures: list[str] = []
    release_authority, release_authority_sha256 = _governance_json_snapshot(RELEASE_AUTHORITY_PATH)
    if release_authority_sha256 != RELEASE_AUTHORITY_SHA256:
        failures.append("dataset release authority bytes changed")
    if release_authority != expected_release_authority:
        failures.append("dataset release authority semantics changed")
    if decision["release_authority"] != {
        "path": "docs/evidence/avatar-lavender-essential-oils-v1-release-authority.json",
        "sha256": RELEASE_AUTHORITY_SHA256,
        "schema_version": "spectrasherpa-avatar-essential-oils-release-authority/1",
        "status": "approved_for_unpublished_distribution_candidate",
        "dataset_title": "Lavender Essential Oil FTIR Corpus v1",
        "creator_display_name": "Ye Feng",
        "licensor_display_name": "Spectra Scientific LLC",
        "canonical_attribution_statement": expected_release_authority["canonical_attribution_statement"],
        "citation_policy": "original_unpublished_laboratory_dataset_no_external_publication_citations_applicable",
        "external_publication_citation_count": 0,
        "privacy_review_status": "passed",
    }:
        failures.append("publication decision does not exactly bind the release authority")
    return failures


def _private_package_review_binding_failures(decision: dict[str, Any]) -> list[str]:
    failures: list[str] = []
    review, review_sha256 = _governance_json_snapshot(PRIVATE_PACKAGE_REVIEW_PATH)
    expected_review = {
        "schema_version": "spectrasherpa-avatar-essential-oils-private-package-review/1",
        "dataset_id": "avatar-essential-oils/1",
        "dataset_title": "Lavender Essential Oil FTIR Corpus v1",
        "status": "deterministic_private_package_review_candidate_frozen",
        "generated_on": "2026-08-26",
        "build_count": 2,
        "builds_byte_identical": True,
        "distribution_receipt": {
            "schema_version": "spectrasherpa-avatar-essential-oils-distribution-receipt/1",
            "status": "private_package_review_candidate_validated",
            "archive_size_bytes": 397438,
            "archive_sha256": "83623f4f89a6832a3db70060e76d8f91dcc8657321447b17c0ccb5736631babe",
            "member_count": 41,
            "member_projection_sha256": "f10745c136e03693c500a647055e9988d1a71a2912e58365e5379b4d9736c8b5",
            "source_manifest_sha256": PUBLIC_MANIFEST_SHA256,
            "collection_definition_sha256": ("524960aed6d2ef8294a7ffed0056f7287a38b611462c12599fc2bd7cf1222db2"),
            "release_authority_sha256": PRIVATE_REVIEW_RELEASE_AUTHORITY_SHA256,
            "resolved_collection_definition_sha256": (
                "d9ac1b75ecdc767baff9e2ac3adc514d7b08d0601d1adb0d36cfe5afb0af1ec2"
            ),
            "implementation_authority": {
                "distribution_tool_sha256": ("36d0b86cd67ae047018fece1469a86e4459bec984b6136e3d9f3d90df9809dac"),
                "native_module_count": 21,
                "native_module_projection_sha256": ("113b5f851aebc490337d7dfb6b420366eb2696023cc3ddf946838ef73008307e"),
            },
            "license": "CC-BY-4.0",
            "creator_display_name": "Ye Feng",
            "licensor_display_name": "Spectra Scientific LLC",
            "external_publication_citation_count": 0,
            "correction": "None",
            "privacy_review_complete": False,
            "raw_publication_performed": False,
        },
        "candidate_contents": {
            "raw_source_count": 33,
            "documentation_and_authority_member_count": 8,
            "specimen_count": 11,
            "blocks": [1, 2, 3],
            "supplier_crosswalk_included": False,
            "supplier_identity_intentionally_included": False,
            "removed_non_oil_reference_count": 0,
        },
        "privacy_review": {
            "status": "pending_owner_or_designated_reviewer_approval",
            "required_assertions": [
                "supplier_crosswalk_absent",
                "supplier_identity_absent",
                "supplier_identifying_metadata_absent",
                "private_paths_and_ids_absent",
                "non_oil_references_absent",
            ],
        },
        "custody": {
            "archive_retained_privately": True,
            "archive_path_recorded_publicly": False,
            "raw_member_names_recorded_in_this_evidence": False,
            "publication_performed": False,
        },
        "claim_boundary": (
            "This path-free receipt freezes a deterministic private package-review candidate for the exact "
            "33-source Lavender Essential Oil FTIR Corpus v1. It records no raw bytes, raw member names, private "
            "paths, supplier identities, or publication action. Final distribution qualification remains pending "
            "the repeated owner or designated-reviewer privacy and package-content review."
        ),
    }
    if review_sha256 != PRIVATE_PACKAGE_REVIEW_SHA256:
        failures.append("private package-review authority bytes changed")
    if review != expected_review:
        failures.append("private package-review authority semantics changed")
    if decision["private_package_review_authority"] != {
        "path": "docs/evidence/avatar-lavender-essential-oils-v1-private-package-review.json",
        "sha256": PRIVATE_PACKAGE_REVIEW_SHA256,
        "schema_version": "spectrasherpa-avatar-essential-oils-private-package-review/1",
        "status": "deterministic_private_package_review_candidate_frozen",
        "archive_sha256": "83623f4f89a6832a3db70060e76d8f91dcc8657321447b17c0ccb5736631babe",
        "archive_size_bytes": 397438,
        "member_count": 41,
        "build_count": 2,
        "builds_byte_identical": True,
        "privacy_review_complete": False,
        "publication_performed": False,
    }:
        failures.append("publication decision does not exactly bind the private package-review authority")
    return failures


def _distribution_qualification_binding_failures(decision: dict[str, Any]) -> list[str]:
    failures: list[str] = []
    qualification, qualification_sha256 = _governance_json_snapshot(QUALIFICATION_PATH)
    expected_qualification = {
        "schema_version": "spectrasherpa-avatar-essential-oils-distribution-qualification/1",
        "dataset_id": "avatar-essential-oils/1",
        "dataset_title": "Lavender Essential Oil FTIR Corpus v1",
        "status": "unpublished_distribution_candidate_qualified",
        "qualification_date": "2026-08-26",
        "approval_authority": {
            "approval_kind": "dataset_owner_privacy_and_package_content_approval",
            "reviewer_role": "dataset_owner_and_licensor_representative",
            "approved_assertions": [
                "supplier_crosswalk_absent",
                "supplier_identity_absent",
                "supplier_identifying_metadata_absent",
                "private_paths_and_ids_absent",
                "non_oil_references_absent",
            ],
            "release_authority_sha256": RELEASE_AUTHORITY_SHA256,
            "private_package_review_authority_sha256": PRIVATE_PACKAGE_REVIEW_SHA256,
        },
        "build_count": 2,
        "builds_byte_identical": True,
        "distribution_receipt": {
            "schema_version": "spectrasherpa-avatar-essential-oils-distribution-receipt/1",
            "status": "unpublished_distribution_candidate_validated",
            "archive_size_bytes": 397185,
            "archive_sha256": "42565d51e2969c26ee24171f848ff9c3ab5cb429cd6250568993dffa738cd05c",
            "member_count": 41,
            "member_projection_sha256": "5e258cf7e9a710bbb4a1b9b4f958c3e995fea771a57ca5bc0214107fde7c9e7c",
            "source_manifest_sha256": PUBLIC_MANIFEST_SHA256,
            "collection_definition_sha256": ("524960aed6d2ef8294a7ffed0056f7287a38b611462c12599fc2bd7cf1222db2"),
            "release_authority_sha256": RELEASE_AUTHORITY_SHA256,
            "resolved_collection_definition_sha256": (
                "d9ac1b75ecdc767baff9e2ac3adc514d7b08d0601d1adb0d36cfe5afb0af1ec2"
            ),
            "implementation_authority": {
                "distribution_tool_sha256": ("1bc134095e6a693a8300b9565078b1ce62602c1108fabf9651d60197a3f774d3"),
                "native_module_count": 21,
                "native_module_projection_sha256": ("2c41fa5c412258efcc56ad0ca2bd5ce46c5d23d10d2b549c03d32b464a6fb523"),
            },
            "license": "CC-BY-4.0",
            "creator_display_name": "Ye Feng",
            "licensor_display_name": "Spectra Scientific LLC",
            "external_publication_citation_count": 0,
            "correction": "None",
            "privacy_review_complete": True,
            "raw_publication_performed": False,
        },
        "candidate_contents": {
            "raw_source_count": 33,
            "documentation_and_authority_member_count": 8,
            "specimen_count": 11,
            "blocks": [1, 2, 3],
            "supplier_crosswalk_included": False,
            "supplier_identity_included": False,
            "supplier_identifying_metadata_included": False,
            "private_paths_and_ids_included": False,
            "removed_non_oil_reference_count": 0,
        },
        "custody": {
            "archive_retained_privately": True,
            "archive_path_recorded_publicly": False,
            "raw_member_names_recorded_in_this_evidence": False,
            "repository_raw_bytes_added": False,
            "publication_performed": False,
        },
        "next_release_gate": {
            "phase": 7,
            "phase_6_exact_sha_requalification_required_before_publication": True,
            "explicit_phase_7_publication_approval_required": True,
        },
        "claim_boundary": (
            "Phase 1 qualifies an unpublished deterministic distribution candidate for the exact 33-source "
            "Lavender Essential Oil FTIR Corpus v1 after the dataset owner affirmed all five privacy and "
            "package-content exclusions. It does not publish raw bytes or satisfy the later exact-SHA release "
            "qualification and explicit publication gates."
        ),
    }
    if qualification_sha256 != QUALIFICATION_SHA256:
        failures.append("distribution qualification authority bytes changed")
    if qualification != expected_qualification:
        failures.append("distribution qualification authority semantics changed")
    if decision["distribution_qualification_authority"] != {
        "path": "docs/evidence/avatar-lavender-essential-oils-v1-distribution-qualification.json",
        "sha256": QUALIFICATION_SHA256,
        "schema_version": "spectrasherpa-avatar-essential-oils-distribution-qualification/1",
        "status": "unpublished_distribution_candidate_qualified",
        "archive_sha256": "42565d51e2969c26ee24171f848ff9c3ab5cb429cd6250568993dffa738cd05c",
        "archive_size_bytes": 397185,
        "member_count": 41,
        "build_count": 2,
        "builds_byte_identical": True,
        "privacy_review_complete": True,
        "publication_performed": False,
    }:
        failures.append("publication decision does not exactly bind the distribution qualification authority")
    return failures


def _publication_decision_failures(
    decision: dict[str, Any],
    *,
    tracked_records: tuple[dict[str, Any], ...] | None = None,
) -> list[str]:
    failures: list[str] = []
    expected_top = {
        "schema_version",
        "dataset_id",
        "decision",
        "decision_date",
        "operator_authority",
        "manifest_authority",
        "license_authority",
        "release_authority",
        "private_package_review_authority",
        "distribution_qualification_authority",
        "repository_census",
        "blocking_authorities",
        "custody_and_publication",
        "reopen_conditions",
        "claim_boundary",
        "physical_action_2",
    }
    if set(decision) != expected_top:
        failures.append("publication decision schema is not closed")
        return failures
    if decision["schema_version"] != "spectrasherpa-avatar-publication-decision/5":
        failures.append("publication decision schema version changed")
    if decision["dataset_id"] != "avatar-essential-oils/1":
        failures.append("publication decision dataset identity changed")
    if decision["decision_date"] != "2026-08-26":
        failures.append("publication decision date changed")
    if decision["operator_authority"] != (
        "author_operated_governance_decision_with_owner_creator_licensor_and_laboratory_origin_confirmation"
    ):
        failures.append("publication decision operator authority changed")

    manifest, manifest_sha256 = _governance_json_snapshot(PUBLIC_MANIFEST_PATH)
    authority = decision["manifest_authority"]
    expected_authority = {
        "path": "docs/evidence/avatar-essential-oils-v1-manifest.json",
        "sha256": PUBLIC_MANIFEST_SHA256,
        "schema_version": manifest["schema_version"],
        "status": manifest["status"],
        "dataset_license": manifest["dataset_license"],
        "file_count": len(manifest["files"]),
        "total_source_bytes": sum(row["size_bytes"] for row in manifest["files"]),
        "specimen_count": len({row["specimen_id"] for row in manifest["files"]}),
        "blocks": sorted({row["block"] for row in manifest["files"]}),
        "supplier_identity_collected": False,
    }
    if manifest_sha256 != PUBLIC_MANIFEST_SHA256:
        failures.append("public manifest bytes changed")
    if authority != expected_authority:
        failures.append("publication decision does not exactly bind the public manifest")
    if manifest["status"] != "curated_not_yet_distribution_qualified":
        failures.append("public manifest no longer states that distribution qualification is pending")
    if manifest["dataset_license"] != "license_selection_pending":
        failures.append("public manifest no longer states that dataset licensing is pending")
    if manifest["privacy_statement"] != "Supplier identity is not collected in the public corpus.":
        failures.append("public manifest privacy statement changed")
    if {row["evidence_status"] for row in manifest["files"]} != {
        "not_applicable",
        "pending_exact_citation",
    }:
        failures.append("citation evidence status changed")

    license_authorization, license_authorization_sha256 = _governance_json_snapshot(LICENSE_AUTHORIZATION_PATH)
    expected_license_authorization = {
        "schema_version": "spectrasherpa-avatar-essential-oils-license-authorization/1",
        "dataset_id": "avatar-essential-oils/1",
        "authorization_date": "2026-08-25",
        "authorization_basis": "dataset_rights_holder_or_controller_confirmation",
        "license": "CC-BY-4.0",
        "license_url": "https://creativecommons.org/licenses/by/4.0/",
        "source_authority": {
            "path": "docs/evidence/avatar-essential-oils-v1-manifest.json",
            "sha256": PUBLIC_MANIFEST_SHA256,
            "schema_version": "spectrasherpa-avatar-essential-oils-public-manifest/2",
            "authorized_file_count": 33,
            "excluded_non_oil_reference_count": 2,
        },
        "authorization_scope": (
            "Redistribution and adaptation of the exact 33 curated Avatar essential-oil SPA "
            "files represented by the bound source manifest, excluding the two removed non-oil "
            "references, under CC BY 4.0."
        ),
        "supplier_privacy": {
            "supplier_crosswalk": "must_remain_private",
            "supplier_identity": "must_remain_private",
            "supplier_identifying_metadata": "must_remain_private",
            "public_package_requirement": "exclude_all_supplier_identifying_authorities",
        },
        "public_release_readiness": {
            "status": "withheld_pending_attribution_citations_and_privacy_review",
            "creator_licensor_display_name": "pending",
            "canonical_attribution_statement": "pending",
            "pending_exact_citations": True,
            "privacy_and_package_content_review_required": True,
        },
        "claim_boundary": (
            "This record selects and authorizes CC BY 4.0 for the exact bound 33-file corpus. "
            "It does not itself publish raw files, disclose supplier information, complete "
            "attribution or citations, establish botanical authenticity, or satisfy non-author "
            "Physical Action 2."
        ),
    }
    if license_authorization_sha256 != LICENSE_AUTHORIZATION_SHA256:
        failures.append("dataset license authorization bytes changed")
    if license_authorization != expected_license_authorization:
        failures.append("dataset license authorization semantics changed")
    expected_license_authority = {
        "path": "docs/evidence/avatar-essential-oils-v1-license-authorization.json",
        "sha256": LICENSE_AUTHORIZATION_SHA256,
        "schema_version": "spectrasherpa-avatar-essential-oils-license-authorization/1",
        "license": "CC-BY-4.0",
        "license_url": "https://creativecommons.org/licenses/by/4.0/",
        "authorization_scope": ("exact_33_curated_oil_sources_excluding_two_removed_non_oil_references"),
        "supplier_privacy_required": True,
        "public_attribution_status": "historical_pending_superseded_by_release_authority",
    }
    if decision["license_authority"] != expected_license_authority:
        failures.append("publication decision does not exactly bind the license authorization")

    expected_release_authority = {
        "schema_version": "spectrasherpa-avatar-essential-oils-release-authority/1",
        "dataset_id": "avatar-essential-oils/1",
        "dataset_version": 1,
        "dataset_title": "Lavender Essential Oil FTIR Corpus v1",
        "status": "approved_for_unpublished_distribution_candidate",
        "license": "CC-BY-4.0",
        "license_url": "https://creativecommons.org/licenses/by/4.0/",
        "license_authorization_sha256": LICENSE_AUTHORIZATION_SHA256,
        "source_manifest_sha256": PUBLIC_MANIFEST_SHA256,
        "collection_definition_sha256": "524960aed6d2ef8294a7ffed0056f7287a38b611462c12599fc2bd7cf1222db2",
        "creator_display_name": "Ye Feng",
        "licensor_display_name": "Spectra Scientific LLC",
        "canonical_attribution_statement": (
            "Ye Feng. (2026). Lavender Essential Oil FTIR Corpus v1 [Data set]. "
            "Spectra Scientific LLC. Licensed under CC BY 4.0."
        ),
        "citation_policy": {
            "status": "no_external_publication_citations_applicable",
            "basis": "original_unpublished_laboratory_dataset",
            "statement": (
                "This is an original unpublished laboratory dataset; no external publication citations apply."
            ),
            "external_publication_citation_count": 0,
        },
        "citations": [],
        "privacy_review": {
            "status": "passed",
            "reviewed_on": "2026-08-26",
            "reviewer_role": "dataset_owner_and_licensor_representative",
            "supplier_crosswalk_absent": True,
            "supplier_identity_absent": True,
            "supplier_identifying_metadata_absent": True,
            "private_paths_and_ids_absent": True,
            "non_oil_references_absent": True,
        },
        "limitations": [
            (
                "The 33 spectra are technical acquisition replicates of 11 retained lavender essential-oil "
                "specimens in three blocks, not independent population samples."
            ),
            (
                "Sample labels and author-reported statuses do not establish botanical authenticity, supplier "
                "identity, population performance, or performance on future lots."
            ),
            (
                "The corpus is intended for native-parser, reproducibility, visualization, PCA, and closed-set "
                "specimen-identification pipeline validation."
            ),
            (
                "The acquisition used absorbance with OMNIC Correction set to None; no spectral correction was "
                "applied at acquisition."
            ),
        ],
    }
    failures.extend(_release_authority_binding_failures(decision, expected_release_authority))
    failures.extend(_private_package_review_binding_failures(decision))
    failures.extend(_distribution_qualification_binding_failures(decision))

    expected_blockers = [
        "phase_6_exact_sha_requalification_pending",
        "explicit_phase_7_publication_approval_pending",
    ]
    if decision["blocking_authorities"] != expected_blockers:
        failures.append("publication blockers changed")
    if decision["decision"] != "distribution_qualified_publication_deferred_to_phase_7_release_gate":
        failures.append("raw-corpus publication is not withheld")
    if decision["custody_and_publication"] != {
        "private_raw_authority": (
            "cc_by_4_0_authorized_attributed_privacy_reviewed_distribution_qualified_not_published"
        ),
        "open_curated_corpus": "not_published",
        "canonical_derived_evidence": "retained_public_path_free",
        "distribution_integration": "not_performed",
        "avatar_parser_fixture": "not_bundled",
        "supplier_identifying_authorities": "private_excluded_from_publication",
    }:
        failures.append("publication custody boundary changed")
    if decision["reopen_conditions"] != [
        "repeat_privacy_and_package_content_review_if_candidate_contents_change",
        "complete_phase_6_exact_sha_requalification_before_publication",
        "obtain_explicit_phase_7_publication_approval",
    ]:
        failures.append("publication reopen conditions changed")
    if decision["claim_boundary"] != (
        "The rights holder or controller authorizes the exact 33-source Lavender Essential Oil FTIR Corpus v1 "
        "under CC BY 4.0, excluding the two removed non-oil references. Ye Feng is the creator and Spectra "
        "Scientific LLC is the licensor. This is an original unpublished laboratory dataset, so no external "
        "publication citation mappings apply. The dataset owner affirmed all five privacy and package-content "
        "exclusions, and a deterministic unpublished distribution candidate is qualified. Raw publication remains "
        "withheld pending Phase 6 exact-SHA requalification and explicit Phase 7 publication approval. Supplier "
        "crosswalks and supplier-identifying "
        "metadata remain private. This decision makes no botanical authenticity, population, new-lot, supplier, "
        "paper-validation, or public-corpus claim."
    ):
        failures.append("publication claim boundary changed")
    if decision["physical_action_2"] != {
        "status": "external_observation_pending",
        "satisfied_by_this_decision": False,
        "required_operator": "person_other_than_an_author",
    }:
        failures.append("non-author Physical Action 2 boundary changed")

    records = _tracked_repository_records() if tracked_records is None else tracked_records
    corpus_names = {row["distribution_filename"] for row in manifest["files"]}
    corpus_digests = {row["curated_sha256"] for row in manifest["files"]}
    direct_matches = [row for row in records if row["sha256"] in corpus_digests]
    archive_matches = [
        row
        for row in records
        if any(
            Path(member["name"]).name in corpus_names or member["sha256"] in corpus_digests
            for member in row["archive_members"]
        )
    ]
    if direct_matches:
        failures.append("an exact Avatar raw source is tracked under a repository path")
    if archive_matches:
        failures.append("a tracked archive contains an Avatar raw source")

    fixture_path = decision["repository_census"]["existing_licensed_omnic_fixture"]
    fixture_records = [row for row in records if row["path"] == fixture_path]
    if len(fixture_records) != 1 or fixture_records[0]["mode"] not in {"100644", "100755"}:
        failures.append("the retained licensed OMNIC parser fixture is not one exact tracked regular file")
    attribution_path = REPO_ROOT / decision["repository_census"]["attribution_authority"]
    attribution, attribution_sha256 = _governance_json_snapshot(attribution_path)
    fixture_authorities = [
        row
        for row in attribution["fixtures"]
        if row["path"] == decision["repository_census"]["existing_licensed_omnic_fixture"]
    ]
    if attribution_sha256 != "2406b922928cdb78937f2b12e521721c9463626ebe5fd68daf71369dc7595e36":
        failures.append("fixture attribution authority changed")
    if len(fixture_authorities) != 1 or fixture_authorities[0] != {
        "path": ("packages/spectra-sherpa/tests/fixtures/omnic/openspecy-polyethylene-reflectance.spa"),
        "sha256": "042c53feb30cb7328318b8c426203720da455be3f948f41ee5e39119b9d86288",
        "source": ("Open Specy inst/extdata/ftir_polyethylene_reflectance_adjustment_not_working.spa"),
        "upstream": "https://github.com/wincowgerDEV/OpenSpecy-package",
        "license": "CC-BY-4.0",
        "notice": ("packages/spectra-sherpa/THIRD_PARTY_LICENSES/OpenSpecy-CC-BY-4.0.txt"),
    }:
        failures.append("licensed OMNIC fixture authority changed")
    if len(fixture_records) != 1 or fixture_records[0]["sha256"] != (
        "042c53feb30cb7328318b8c426203720da455be3f948f41ee5e39119b9d86288"
    ):
        failures.append("licensed OMNIC fixture bytes changed")
    notice_path = decision["repository_census"]["existing_fixture_notice"]
    notice_records = [row for row in records if row["path"] == notice_path]
    if len(notice_records) != 1 or notice_records[0]["mode"] not in {"100644", "100755"}:
        failures.append("the retained fixture notice is not one exact tracked regular file")
    if len(notice_records) != 1 or notice_records[0]["sha256"] != (
        "e7b738af9022d2aa5f30592650e9b70876753a61955576a534fc60858ca629a6"
    ):
        failures.append("the retained fixture notice bytes changed")
    if decision["repository_census"] != {
        "avatar_raw_spa_files_tracked": 0,
        "avatar_project_archives_tracked": 0,
        "existing_licensed_omnic_fixture": (
            "packages/spectra-sherpa/tests/fixtures/omnic/openspecy-polyethylene-reflectance.spa"
        ),
        "existing_fixture_sha256": ("042c53feb30cb7328318b8c426203720da455be3f948f41ee5e39119b9d86288"),
        "existing_fixture_license": "CC-BY-4.0",
        "existing_fixture_notice": ("packages/spectra-sherpa/THIRD_PARTY_LICENSES/OpenSpecy-CC-BY-4.0.txt"),
        "existing_fixture_notice_sha256": ("e7b738af9022d2aa5f30592650e9b70876753a61955576a534fc60858ca629a6"),
        "attribution_authority": "docs/evidence/bundled-vendor-fixture-attribution.json",
        "attribution_authority_sha256": ("2406b922928cdb78937f2b12e521721c9463626ebe5fd68daf71369dc7595e36"),
        "parser_fixture_decision": ("do_not_bundle_avatar_corpus_use_existing_licensed_fixture_authority"),
    }:
        failures.append("repository or parser-fixture decision changed")
    return failures


def test_checked_phase9_publication_decision_is_closed_and_cross_bound() -> None:
    decision, decision_sha256 = _governance_json_snapshot(PUBLICATION_DECISION_PATH)
    assert decision_sha256 == PUBLICATION_DECISION_SHA256
    assert _publication_decision_failures(decision) == []


@pytest.mark.parametrize(
    ("needle", "replacement"),
    (
        (
            '  "license": "CC-BY-4.0",',
            '  "license": "CC0-1.0",\n  "license": "CC-BY-4.0",',
        ),
        (
            '    "authorized_file_count": 33,',
            '    "authorized_file_count": 32,\n    "authorized_file_count": 33,',
        ),
        (
            '    "supplier_crosswalk": "must_remain_private",',
            ('    "supplier_crosswalk": "public",\n    "supplier_crosswalk": "must_remain_private",'),
        ),
    ),
)
def test_phase9_license_authorization_rejects_duplicate_legal_keys(
    needle: str,
    replacement: str,
    tmp_path: Path,
) -> None:
    content = LICENSE_AUTHORIZATION_PATH.read_text()
    assert content.count(needle) == 1
    mutated = tmp_path / "duplicate-license-authorization.json"
    mutated.write_text(content.replace(needle, replacement))
    with pytest.raises(AssertionError, match="duplicate JSON key"):
        _load_governance_json(mutated)


def test_phase9_publication_decision_rejects_duplicate_release_authority(tmp_path: Path) -> None:
    content = PUBLICATION_DECISION_PATH.read_text()
    needle = '  "decision": "distribution_qualified_publication_deferred_to_phase_7_release_gate",'
    assert content.count(needle) == 1
    mutated = tmp_path / "duplicate-publication-decision.json"
    mutated.write_text(
        content.replace(
            needle,
            '  "decision": "published",\n' + needle,
        )
    )
    with pytest.raises(AssertionError, match="duplicate JSON key"):
        _load_governance_json(mutated)


def test_phase9_governance_json_admission_refuses_symlink_and_oversize(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = tmp_path / "target.json"
    target.write_text("{}\n")
    linked = tmp_path / "linked.json"
    linked.symlink_to(target)
    with pytest.raises(AssertionError, match="without following links"):
        _load_governance_json(linked)

    monkeypatch.setitem(globals(), "GOVERNANCE_JSON_BYTES_MAX", 8)
    oversized = tmp_path / "oversized.json"
    oversized.write_text('{"value": 1}\n')
    with pytest.raises(AssertionError, match="byte ceiling"):
        _load_governance_json(oversized)


@pytest.mark.parametrize(
    "source",
    (
        PUBLICATION_DECISION_PATH,
        LICENSE_AUTHORIZATION_PATH,
        RELEASE_AUTHORITY_PATH,
        PRIVATE_PACKAGE_REVIEW_PATH,
        QUALIFICATION_PATH,
        PUBLIC_MANIFEST_PATH,
        REPO_ROOT / "docs" / "evidence" / "bundled-vendor-fixture-attribution.json",
    ),
)
def test_phase9_governance_snapshot_survives_leaf_swap_after_open(
    source: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = source.read_bytes()
    leaf = tmp_path / source.name
    leaf.write_bytes(original)
    replacement = tmp_path / "replacement.json"
    replacement.write_text('{"replacement": true}\n')
    displaced = tmp_path / "displaced.json"
    original_read = os.read
    swapped = False

    def swap_after_first_read(descriptor: int, amount: int) -> bytes:
        nonlocal swapped
        chunk = original_read(descriptor, amount)
        if chunk and not swapped:
            swapped = True
            leaf.rename(displaced)
            leaf.symlink_to(replacement)
        return chunk

    monkeypatch.setattr(os, "read", swap_after_first_read)
    parsed, observed_sha256 = _governance_json_snapshot(leaf)
    assert swapped is True
    assert parsed == json.loads(original)
    assert observed_sha256 == hashlib.sha256(original).hexdigest()
    assert leaf.is_symlink()
    assert leaf.read_bytes() == replacement.read_bytes()


@pytest.mark.parametrize(
    "source",
    (
        PUBLICATION_DECISION_PATH,
        LICENSE_AUTHORIZATION_PATH,
        RELEASE_AUTHORITY_PATH,
        PRIVATE_PACKAGE_REVIEW_PATH,
        QUALIFICATION_PATH,
        PUBLIC_MANIFEST_PATH,
        REPO_ROOT / "docs" / "evidence" / "bundled-vendor-fixture-attribution.json",
    ),
)
def test_phase9_governance_snapshot_bounds_each_authority(
    source: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    content = source.read_bytes()
    copied = tmp_path / source.name
    copied.write_bytes(content)
    monkeypatch.setitem(globals(), "GOVERNANCE_JSON_BYTES_MAX", len(content) - 1)
    with pytest.raises(AssertionError, match="byte ceiling"):
        _governance_json_snapshot(copied)


@pytest.mark.parametrize(
    ("path", "value", "expected"),
    (
        (("decision",), "published", "raw-corpus publication is not withheld"),
        (
            ("manifest_authority", "dataset_license"),
            "CC0-1.0",
            "publication decision does not exactly bind the public manifest",
        ),
        (
            ("custody_and_publication", "avatar_parser_fixture"),
            "bundled",
            "publication custody boundary changed",
        ),
        (
            ("physical_action_2", "status"),
            "complete",
            "non-author Physical Action 2 boundary changed",
        ),
    ),
)
def test_phase9_publication_decision_rejects_authority_mutations(
    path: tuple[str, ...], value: Any, expected: str
) -> None:
    decision = _load_governance_json(PUBLICATION_DECISION_PATH)
    target: dict[str, Any] = decision
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    assert expected in _publication_decision_failures(decision)


@pytest.mark.parametrize(
    ("path", "value"),
    (
        (("license",), "CC0-1.0"),
        (("source_authority", "authorized_file_count"), 32),
        (("source_authority", "excluded_non_oil_reference_count"), 0),
        (("supplier_privacy", "supplier_crosswalk"), "public"),
        (("supplier_privacy", "supplier_identifying_metadata"), "public"),
        (("public_release_readiness", "creator_licensor_display_name"), "invented-name"),
        (("public_release_readiness", "privacy_and_package_content_review_required"), False),
        (("public_release_readiness", "status"), "ready_for_publication"),
    ),
)
def test_phase9_license_authorization_rejects_refreshed_hash_semantic_mutations(
    path: tuple[str, ...],
    value: Any,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    authorization = _load_governance_json(LICENSE_AUTHORIZATION_PATH)
    target: dict[str, Any] = authorization
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    mutated_path = tmp_path / "license-authorization.json"
    mutated_path.write_text(json.dumps(authorization, indent=2) + "\n")
    mutated_sha = hashlib.sha256(mutated_path.read_bytes()).hexdigest()
    monkeypatch.setitem(globals(), "LICENSE_AUTHORIZATION_PATH", mutated_path)
    monkeypatch.setitem(globals(), "LICENSE_AUTHORIZATION_SHA256", mutated_sha)

    decision = _load_governance_json(PUBLICATION_DECISION_PATH)
    decision["license_authority"]["sha256"] = mutated_sha
    assert "dataset license authorization semantics changed" in _publication_decision_failures(decision)


@pytest.mark.parametrize(
    ("path", "value"),
    (
        (("approval_authority", "approved_assertions"), []),
        (("distribution_receipt", "privacy_review_complete"), False),
        (("distribution_receipt", "archive_sha256"), "0" * 64),
        (("custody", "publication_performed"), True),
        (("next_release_gate", "explicit_phase_7_publication_approval_required"), False),
    ),
)
def test_phase9_qualification_rejects_refreshed_hash_semantic_mutations(
    path: tuple[str, ...],
    value: Any,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    qualification = _load_governance_json(QUALIFICATION_PATH)
    target: dict[str, Any] = qualification
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    mutated_path = tmp_path / "distribution-qualification.json"
    mutated_path.write_text(json.dumps(qualification, indent=2) + "\n")
    mutated_sha = hashlib.sha256(mutated_path.read_bytes()).hexdigest()
    monkeypatch.setitem(globals(), "QUALIFICATION_PATH", mutated_path)
    monkeypatch.setitem(globals(), "QUALIFICATION_SHA256", mutated_sha)

    decision = _load_governance_json(PUBLICATION_DECISION_PATH)
    decision["distribution_qualification_authority"]["sha256"] = mutated_sha
    assert "distribution qualification authority semantics changed" in _publication_decision_failures(decision)


@pytest.mark.parametrize(
    "blocker",
    (
        "phase_6_exact_sha_requalification_pending",
        "explicit_phase_7_publication_approval_pending",
    ),
)
def test_phase9_publication_decision_cannot_drop_later_release_gate(blocker: str) -> None:
    decision = _load_governance_json(PUBLICATION_DECISION_PATH)
    decision["blocking_authorities"].remove(blocker)
    assert "publication blockers changed" in _publication_decision_failures(decision)


def test_phase9_census_rejects_an_exact_avatar_source_under_a_different_name() -> None:
    decision = _load_governance_json(PUBLICATION_DECISION_PATH)
    manifest = _load_governance_json(PUBLIC_MANIFEST_PATH)
    renamed_source = {
        "path": "docs/evidence/renamed-private-source.bin",
        "mode": "100644",
        "size_bytes": manifest["files"][0]["size_bytes"],
        "sha256": manifest["files"][0]["curated_sha256"],
        "archive_members": (),
    }
    failures = _publication_decision_failures(
        decision,
        tracked_records=(*_tracked_repository_records(), renamed_source),
    )
    assert "an exact Avatar raw source is tracked under a repository path" in failures


def test_phase9_census_rejects_a_renamed_raw_bearing_archive(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    payload = b"synthetic exact private Avatar source for archive admission"
    archive_buffer = io.BytesIO()
    with zipfile.ZipFile(archive_buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("renamed-member.bin", payload)
    member_records = _zip_member_records(archive_buffer.getvalue())
    assert member_records == (
        {
            "name": "renamed-member.bin",
            "size_bytes": len(payload),
            "sha256": hashlib.sha256(payload).hexdigest(),
        },
    )

    manifest = _load_governance_json(PUBLIC_MANIFEST_PATH)
    manifest["files"][0]["curated_sha256"] = hashlib.sha256(payload).hexdigest()
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
    manifest_sha = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
    monkeypatch.setitem(globals(), "PUBLIC_MANIFEST_PATH", manifest_path)
    monkeypatch.setitem(globals(), "PUBLIC_MANIFEST_SHA256", manifest_sha)

    decision = _load_governance_json(PUBLICATION_DECISION_PATH)
    decision["manifest_authority"]["sha256"] = manifest_sha
    renamed_archive = {
        "path": "docs/evidence/renamed-private-project.bin",
        "mode": "100644",
        "size_bytes": len(archive_buffer.getvalue()),
        "sha256": hashlib.sha256(archive_buffer.getvalue()).hexdigest(),
        "archive_members": member_records,
    }
    failures = _publication_decision_failures(
        decision,
        tracked_records=(*_tracked_repository_records(), renamed_archive),
    )
    assert "a tracked archive contains an Avatar raw source" in failures


def test_phase9_license_authority_rejects_a_different_nonempty_notice() -> None:
    decision = _load_governance_json(PUBLICATION_DECISION_PATH)
    notice_path = decision["repository_census"]["existing_fixture_notice"]
    corrupted_records = tuple(
        (
            {
                **record,
                "sha256": hashlib.sha256(b"not a license; deliberately corrupted but nonempty").hexdigest(),
            }
            if record["path"] == notice_path
            else record
        )
        for record in _tracked_repository_records()
    )
    failures = _publication_decision_failures(decision, tracked_records=corrupted_records)
    assert "the retained fixture notice bytes changed" in failures


def test_phase9_git_index_census_refuses_excessive_path_multiplicity() -> None:
    object_id = "a" * 40
    index = b"".join(
        f"100644 {object_id} 0\tbounded/path-{index}.txt\0".encode() for index in range(TRACKED_ENTRY_COUNT_MAX + 1)
    )
    with pytest.raises(AssertionError, match="entry-count ceiling"):
        _parse_git_index(index)


def test_phase9_git_blob_census_parses_a_shared_archive_only_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    archive_buffer = io.BytesIO()
    with zipfile.ZipFile(archive_buffer, "w", compression=zipfile.ZIP_STORED) as archive:
        archive.writestr("one.txt", b"bounded")
    archive_bytes = archive_buffer.getvalue()
    object_id = "b" * 40
    index = b"".join(f"100644 {object_id} 0\tshared/archive-{path_index}.bin\0".encode() for path_index in range(50))
    batch_check = f"{object_id} blob {len(archive_bytes)}\n".encode()
    batch = f"{object_id} blob {len(archive_bytes)}\n".encode() + archive_bytes + b"\n"
    parse_calls = 0
    original_zip_member_records = _zip_member_records

    def fake_git_stdout(arguments: list[str], *, max_bytes: int, input_bytes: bytes | None = None) -> bytes:
        del max_bytes, input_bytes
        if arguments[1:3] == ["ls-files", "-s"]:
            return index
        if arguments[2].startswith("--batch-check"):
            return batch_check
        return batch

    def counted_zip_member_records(content: bytes) -> tuple[dict[str, Any], ...]:
        nonlocal parse_calls
        parse_calls += 1
        return original_zip_member_records(content)

    _tracked_repository_records.cache_clear()
    monkeypatch.setitem(globals(), "_bounded_git_stdout", fake_git_stdout)
    monkeypatch.setitem(globals(), "_zip_member_records", counted_zip_member_records)
    try:
        records = _tracked_repository_records()
        assert len(records) == 50
        assert parse_calls == 1
        assert all(record["archive_members"][0]["name"] == "one.txt" for record in records)
    finally:
        _tracked_repository_records.cache_clear()


def test_phase9_zip_member_ceiling_refuses_before_zipfile_allocation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    archive_buffer = io.BytesIO()
    with zipfile.ZipFile(archive_buffer, "w", compression=zipfile.ZIP_STORED) as archive:
        for member_index in range(TRACKED_ARCHIVE_MEMBER_COUNT_MAX + 1):
            archive.writestr(f"empty-{member_index}.txt", b"")

    def forbidden_zipfile(*_args: Any, **_kwargs: Any) -> None:
        raise AssertionError("ZipFile must be unreachable before central-directory admission")

    monkeypatch.setattr(zipfile, "ZipFile", forbidden_zipfile)
    with pytest.raises(AssertionError, match="member-count ceiling"):
        _zip_member_records(archive_buffer.getvalue())


def test_phase9_zip_member_ceiling_does_not_trust_a_forged_low_eocd_count(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    archive_buffer = io.BytesIO()
    with zipfile.ZipFile(archive_buffer, "w", compression=zipfile.ZIP_STORED) as archive:
        for member_index in range(TRACKED_ARCHIVE_MEMBER_COUNT_MAX + 1):
            archive.writestr(f"empty-{member_index}.txt", b"")
    archive_bytes = bytearray(archive_buffer.getvalue())
    eocd_offset = archive_bytes.rfind(b"PK\x05\x06")
    assert eocd_offset >= 0
    struct.pack_into("<HH", archive_bytes, eocd_offset + 8, 1, 1)

    def forbidden_zipfile(*_args: Any, **_kwargs: Any) -> None:
        raise AssertionError("ZipFile must be unreachable before central-directory admission")

    monkeypatch.setattr(zipfile, "ZipFile", forbidden_zipfile)
    with pytest.raises(AssertionError, match="member-count ceiling"):
        _zip_member_records(bytes(archive_bytes))
