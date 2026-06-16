"""Portable SpectraSherpa object archive helpers.

The ``.sherpa`` object is a ZIP container with a small signed-by-hash
manifest, a project payload, and optional binary payloads such as model
artifacts.  The helpers in this module deliberately do not execute workflows;
they inspect and validate archive structure offline.
"""

from __future__ import annotations

import hashlib
import io
import json
import zipfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

SHERPA_OBJECT_VERSION = "0.1"
SUPPORTED_SHERPA_OBJECT_VERSIONS = frozenset({SHERPA_OBJECT_VERSION})
SHERPA_OBJECT_MANIFEST = "sherpa-object.json"
PROJECT_PAYLOAD = "project.json"
DEFAULT_MAX_UNCOMPRESSED_BYTES = 512 * 1024 * 1024


class SherpaObjectError(ValueError):
    """Raised when a portable object archive is malformed."""


@dataclass(frozen=True)
class ArchiveMember:
    """File to include in a portable object archive."""

    path: str
    data: bytes


@dataclass(frozen=True)
class SherpaObjectInspection:
    """Offline inspection summary for a portable object archive."""

    valid_zip: bool
    has_manifest: bool
    has_project: bool
    object_version: str | None = None
    object_type: str | None = None
    package_mode: str | None = None
    project_name: str | None = None
    content_hash: str | None = None
    members: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "valid_zip": self.valid_zip,
            "has_manifest": self.has_manifest,
            "has_project": self.has_project,
            "object_version": self.object_version,
            "object_type": self.object_type,
            "package_mode": self.package_mode,
            "project_name": self.project_name,
            "content_hash": self.content_hash,
            "members": self.members,
            "errors": self.errors,
        }


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def read_project_payload(zf: zipfile.ZipFile) -> dict[str, Any]:
    """Read the required project payload from an archive."""

    try:
        payload = json.loads(zf.read(PROJECT_PAYLOAD))
    except KeyError as exc:
        raise SherpaObjectError(f"Archive is missing {PROJECT_PAYLOAD}") from exc
    except json.JSONDecodeError as exc:
        raise SherpaObjectError(f"{PROJECT_PAYLOAD} is not valid JSON") from exc
    if not isinstance(payload, dict):
        raise SherpaObjectError(f"{PROJECT_PAYLOAD} must contain a JSON object")
    return payload


def build_manifest(
    *,
    project_payload: dict[str, Any],
    member_hashes: dict[str, dict[str, Any]],
    object_type: str = "project",
    package_mode: str = "full",
    producer: str = "spectra-sherpa",
) -> dict[str, Any]:
    """Build the portable object manifest for the already-written members."""

    project_name = str(project_payload.get("name") or "Untitled Project")
    archive_format = project_payload.get("archive_format")
    project_payload_version = None
    if isinstance(archive_format, dict):
        project_payload_version = archive_format.get("version")
    ordered_hashes = {name: member_hashes[name] for name in sorted(member_hashes)}
    content_hash = sha256_bytes(json.dumps(ordered_hashes, sort_keys=True, separators=(",", ":")).encode("utf-8"))
    return {
        "schema": "spectra_sherpa_object",
        "object_version": SHERPA_OBJECT_VERSION,
        "object_type": object_type,
        "project_payload_version": str(project_payload_version or "legacy"),
        "package_mode": package_mode,
        "producer": producer,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "project": {
            "name": project_name,
            "technique": project_payload.get("technique"),
            "sample_type": project_payload.get("sample_type"),
        },
        "payloads": {
            "project": PROJECT_PAYLOAD,
            "members": ordered_hashes,
        },
        "content_hash": content_hash,
        "metadata_only": package_mode == "metadata_only",
        "metadata_only_available": False,
    }


def build_archive(
    *,
    project_payload: dict[str, Any],
    members: Iterable[ArchiveMember] = (),
    package_mode: str = "full",
) -> bytes:
    """Create a ``.sherpa`` archive as bytes."""

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(PROJECT_PAYLOAD, json.dumps(project_payload, indent=2, default=str))
        seen = {PROJECT_PAYLOAD, SHERPA_OBJECT_MANIFEST}
        for member in members:
            safe_path = _normalize_member_path(member.path)
            if safe_path in seen:
                raise SherpaObjectError(f"Duplicate archive member: {safe_path}")
            seen.add(safe_path)
            zf.writestr(safe_path, member.data)

    payload = buf.getvalue()
    hashes = hash_archive_members(payload)
    manifest = build_manifest(project_payload=project_payload, member_hashes=hashes, package_mode=package_mode)

    final = io.BytesIO(payload)
    with zipfile.ZipFile(final, "a", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(SHERPA_OBJECT_MANIFEST, json.dumps(manifest, indent=2, default=str))
    return final.getvalue()


def write_archive_to_path(
    path: Path,
    *,
    project_payload: dict[str, Any],
    members: Iterable[ArchiveMember] = (),
    package_mode: str = "full",
    payload_name: str = PROJECT_PAYLOAD,
    include_manifest: bool = True,
) -> None:
    """Write a project archive to disk without holding the final ZIP in memory."""

    project_bytes = json.dumps(project_payload, indent=2, default=str).encode("utf-8")
    safe_payload_name = _normalize_member_path(payload_name)
    seen = {safe_payload_name}
    if include_manifest:
        seen.add(SHERPA_OBJECT_MANIFEST)
    member_hashes: dict[str, dict[str, Any]] = {}
    if include_manifest:
        member_hashes[safe_payload_name] = {
            "sha256": sha256_bytes(project_bytes),
            "size": len(project_bytes),
        }

    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(safe_payload_name, project_bytes)
        for member in members:
            safe_path = _normalize_member_path(member.path)
            if safe_path in seen:
                raise SherpaObjectError(f"Duplicate archive member: {safe_path}")
            seen.add(safe_path)
            zf.writestr(safe_path, member.data)
            if include_manifest:
                member_hashes[safe_path] = {
                    "sha256": sha256_bytes(member.data),
                    "size": len(member.data),
                }

    if not include_manifest:
        return

    manifest = build_manifest(
        project_payload=project_payload,
        member_hashes=member_hashes,
        package_mode=package_mode,
    )
    with zipfile.ZipFile(path, "a", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(SHERPA_OBJECT_MANIFEST, json.dumps(manifest, indent=2, default=str))


def hash_archive_members(
    archive_bytes: bytes,
    *,
    max_uncompressed_bytes: int | None = DEFAULT_MAX_UNCOMPRESSED_BYTES,
) -> dict[str, dict[str, Any]]:
    """Return SHA-256 and size for every non-manifest archive member."""

    with zipfile.ZipFile(io.BytesIO(archive_bytes), "r") as zf:
        _validate_zip_members(zf, max_uncompressed_bytes=max_uncompressed_bytes)
        hashes: dict[str, dict[str, Any]] = {}
        for name in sorted(zf.namelist()):
            if name == SHERPA_OBJECT_MANIFEST or name.endswith("/"):
                continue
            data = zf.read(name)
            hashes[name] = {
                "sha256": sha256_bytes(data),
                "size": len(data),
            }
        return hashes


def inspect_archive_bytes(
    archive_bytes: bytes,
    *,
    max_uncompressed_bytes: int | None = DEFAULT_MAX_UNCOMPRESSED_BYTES,
) -> SherpaObjectInspection:
    """Inspect a portable object or legacy project archive without importing it."""

    try:
        with zipfile.ZipFile(io.BytesIO(archive_bytes), "r") as zf:
            _validate_zip_members(zf, max_uncompressed_bytes=max_uncompressed_bytes)
            names = sorted(zf.namelist())
            has_manifest = SHERPA_OBJECT_MANIFEST in names
            has_project = PROJECT_PAYLOAD in names
            manifest: dict[str, Any] = {}
            errors: list[str] = []
            if has_manifest:
                try:
                    manifest = json.loads(zf.read(SHERPA_OBJECT_MANIFEST))
                except json.JSONDecodeError:
                    errors.append(_safe_archive_error(SherpaObjectError(f"{SHERPA_OBJECT_MANIFEST} is invalid JSON")))

            project_name = None
            if has_project:
                try:
                    project = read_project_payload(zf)
                    project_name = str(project.get("name") or "")
                except SherpaObjectError as exc:
                    errors.append(_safe_archive_error(exc))

            return SherpaObjectInspection(
                valid_zip=True,
                has_manifest=has_manifest,
                has_project=has_project,
                object_version=manifest.get("object_version") if isinstance(manifest, dict) else None,
                object_type=manifest.get("object_type") if isinstance(manifest, dict) else None,
                package_mode=manifest.get("package_mode") if isinstance(manifest, dict) else None,
                project_name=project_name or None,
                content_hash=manifest.get("content_hash") if isinstance(manifest, dict) else None,
                members=names,
                errors=errors,
            )
    except (zipfile.BadZipFile, SherpaObjectError) as exc:
        return SherpaObjectInspection(
            valid_zip=not isinstance(exc, zipfile.BadZipFile),
            has_manifest=False,
            has_project=False,
            errors=["Invalid ZIP archive" if isinstance(exc, zipfile.BadZipFile) else _safe_archive_error(exc)],
        )


def validate_archive_bytes(
    archive_bytes: bytes,
    *,
    max_uncompressed_bytes: int | None = DEFAULT_MAX_UNCOMPRESSED_BYTES,
) -> dict[str, Any]:
    """Validate a ``.sherpa`` archive offline and return a JSON-safe report."""

    inspection = inspect_archive_bytes(archive_bytes, max_uncompressed_bytes=max_uncompressed_bytes)
    errors = list(inspection.errors)
    if not inspection.valid_zip:
        return {**inspection.to_dict(), "valid": False}
    if not inspection.has_project:
        errors.append(f"Missing required payload: {PROJECT_PAYLOAD}")
    if not inspection.has_manifest:
        errors.append(f"Missing required manifest: {SHERPA_OBJECT_MANIFEST}")
        return {**inspection.to_dict(), "valid": False, "errors": errors}

    try:
        with zipfile.ZipFile(io.BytesIO(archive_bytes), "r") as zf:
            _validate_zip_members(zf, max_uncompressed_bytes=max_uncompressed_bytes)
            manifest = json.loads(zf.read(SHERPA_OBJECT_MANIFEST))
            _validate_manifest_shape(manifest)
            expected_members = manifest.get("payloads", {}).get("members", {})
            if not isinstance(expected_members, dict):
                raise SherpaObjectError("Manifest payloads.members must be an object")

            actual = hash_archive_members(archive_bytes, max_uncompressed_bytes=max_uncompressed_bytes)
            for name, expected in expected_members.items():
                if name not in actual:
                    errors.append(f"Manifest member missing from archive: {name}")
                    continue
                if not isinstance(expected, dict):
                    errors.append(f"Manifest member entry is not an object: {name}")
                    continue
                if expected.get("sha256") != actual[name]["sha256"]:
                    errors.append(f"SHA-256 mismatch for {name}")
                if int(expected.get("size", -1)) != actual[name]["size"]:
                    errors.append(f"Size mismatch for {name}")
            for name in actual:
                if name not in expected_members:
                    errors.append(f"Archive member missing from manifest: {name}")

            recalculated_content_hash = sha256_bytes(
                json.dumps(expected_members, sort_keys=True, separators=(",", ":")).encode("utf-8")
            )
            if manifest.get("content_hash") != recalculated_content_hash:
                errors.append("Manifest content_hash does not match payload member inventory")
    except (json.JSONDecodeError, SherpaObjectError, ValueError) as exc:
        errors.append(_safe_archive_error(exc))

    return {
        **inspection.to_dict(),
        "valid": not errors,
        "errors": errors,
    }


def _safe_archive_error(exc: BaseException) -> str:
    if isinstance(exc, json.JSONDecodeError):
        return "Archive contains invalid JSON"
    if isinstance(exc, SherpaObjectError):
        message = str(exc)
        if message.endswith(" is not valid JSON") or message.endswith(" is invalid JSON"):
            return "Archive contains invalid JSON"
        if message.endswith(" must contain a JSON object"):
            return "Archive project payload is invalid"
        if message.startswith("Unsupported .sherpa object version"):
            return "Unsupported .sherpa object version"
        if message.startswith("Archive uncompressed payload exceeds limit"):
            return "Archive uncompressed payload exceeds limit"
        if message.startswith("Unsafe archive member path"):
            return "Unsafe archive member path"
        if message.startswith("Duplicate archive member"):
            return "Duplicate archive member"
        if message.startswith("Manifest"):
            return "Archive manifest is invalid"
        if message.startswith("Missing required"):
            return "Archive is missing a required payload"
    return "Archive validation failed"


def archive_members_from_paths(paths: Iterable[tuple[str, Path]]) -> list[ArchiveMember]:
    """Read filesystem paths into archive members."""

    members: list[ArchiveMember] = []
    for archive_path, path in paths:
        if not path.exists() or not path.is_file():
            continue
        members.append(ArchiveMember(_normalize_member_path(archive_path), path.read_bytes()))
    return members


def _validate_manifest_shape(manifest: dict[str, Any]) -> None:
    if not isinstance(manifest, dict):
        raise SherpaObjectError("Manifest must be a JSON object")
    if manifest.get("schema") != "spectra_sherpa_object":
        raise SherpaObjectError("Manifest schema must be 'spectra_sherpa_object'")
    object_version = manifest.get("object_version")
    if object_version not in SUPPORTED_SHERPA_OBJECT_VERSIONS:
        raise SherpaObjectError(
            f"Unsupported .sherpa object version {object_version!r}; "
            f"supported versions: {', '.join(sorted(SUPPORTED_SHERPA_OBJECT_VERSIONS))}"
        )
    if manifest.get("object_type") != "project":
        raise SherpaObjectError("Only project .sherpa objects are supported in v0")


def _validate_zip_members(
    zf: zipfile.ZipFile,
    *,
    max_uncompressed_bytes: int | None,
) -> None:
    total_uncompressed = 0
    seen: set[str] = set()
    for info in zf.infolist():
        normalized = _normalize_member_path(info.filename)
        if normalized in seen:
            raise SherpaObjectError(f"Duplicate archive member: {normalized}")
        seen.add(normalized)
        if info.is_dir():
            continue
        total_uncompressed += info.file_size
        if max_uncompressed_bytes is not None and total_uncompressed > max_uncompressed_bytes:
            raise SherpaObjectError(
                "Archive uncompressed payload exceeds limit " f"({total_uncompressed} > {max_uncompressed_bytes} bytes)"
            )


def _normalize_member_path(path: str) -> str:
    raw = str(path).replace("\\", "/")
    if raw.startswith("/"):
        raise SherpaObjectError(f"Unsafe archive member path: {path!r}")
    raw_parts = raw.split("/")
    if any(part == ".." for part in raw_parts):
        raise SherpaObjectError(f"Unsafe archive member path: {path!r}")
    normalized = "/".join(part for part in raw_parts if part not in ("", "."))
    if not normalized:
        raise SherpaObjectError(f"Unsafe archive member path: {path!r}")
    return normalized
