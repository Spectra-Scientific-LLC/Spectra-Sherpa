"""Bounded admission for folders and ordinary ZIPs of scientific sources."""

from __future__ import annotations

import io
import stat
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from fastapi import UploadFile

from spectra_sherpa.app.lib.collection_assembly import (
    MAX_COLLECTION_MEMBERS,
    MAX_COLLECTION_SOURCE_BYTES,
    canonical_collection_file_name,
)
from spectra_sherpa.app.services.file_storage import (
    FileValidationError,
    max_size_bytes,
    sanitize_filename,
    validate_ingestion_filename,
)
from spectra_sherpa.app.services.sherpa_object import (
    DEFAULT_MAX_CENTRAL_DIRECTORY_BYTES,
    SherpaObjectError,
    preflight_zip_central_directory,
)


@dataclass(frozen=True)
class ScientificUploadMember:
    """One exact source member admitted from a browser selection."""

    filename: str
    payload: bytes
    source_name: str


@dataclass(frozen=True)
class ScientificUploadRefusal:
    """One selected source that could not cross scientific admission."""

    source_name: str
    reason: str


@dataclass(frozen=True)
class ScientificUploadBatch:
    """The admitted and refused parts of one browser selection."""

    members: tuple[ScientificUploadMember, ...]
    refusals: tuple[ScientificUploadRefusal, ...]


async def admit_scientific_upload_batch(
    uploads: Iterable[UploadFile],
    *,
    max_file_size_mb: int,
) -> ScientificUploadBatch:
    """Read and expand one bounded browser file/folder/ZIP selection.

    ZIP is a transport container only. Native scientific containers such as
    NPZ are passed through unchanged to the ingestion registry.
    """

    selected = tuple(uploads)
    if not selected:
        raise FileValidationError("Select at least one scientific file or ZIP archive")

    outer_limit = max_size_bytes(max_file_size_mb)
    members: list[ScientificUploadMember] = []
    refusals: list[ScientificUploadRefusal] = []
    seen_names: set[str] = set()
    admitted_bytes = 0
    transport_bytes = 0

    def refuse(source_name: str, reason: str) -> None:
        refusals.append(ScientificUploadRefusal(source_name=source_name, reason=reason))

    def admit(member: ScientificUploadMember) -> None:
        nonlocal admitted_bytes
        if len(members) >= MAX_COLLECTION_MEMBERS:
            refuse(member.source_name, f"Selection exceeds the {MAX_COLLECTION_MEMBERS}-file limit")
            return
        identity = member.filename.casefold()
        if identity in seen_names:
            refuse(member.source_name, f"Duplicate scientific filename: {member.filename}")
            return
        if admitted_bytes + len(member.payload) > MAX_COLLECTION_SOURCE_BYTES:
            refuse(member.source_name, "Selection exceeds the 512 MiB scientific-source limit")
            return
        seen_names.add(identity)
        admitted_bytes += len(member.payload)
        members.append(member)

    try:
        for index, upload in enumerate(selected):
            if len(members) + len(refusals) >= MAX_COLLECTION_MEMBERS:
                refuse(
                    "selection",
                    f"{len(selected) - index} additional source(s) were not examined after "
                    f"the {MAX_COLLECTION_MEMBERS}-source receipt limit",
                )
                break
            source_name = upload.filename or "unnamed source"
            try:
                filename = sanitize_filename(source_name)
                payload = await _read_upload(upload, max_bytes=outer_limit)
                if transport_bytes + len(payload) > MAX_COLLECTION_SOURCE_BYTES:
                    refuse(source_name, "Selection exceeds the 512 MiB transport limit")
                    if index + 1 < len(selected):
                        refuse(
                            "selection",
                            f"{len(selected) - index - 1} additional source(s) were not examined",
                        )
                    break
                transport_bytes += len(payload)
                if Path(filename).suffix.lower() == ".zip":
                    expanded = _members_from_zip(filename, payload, per_file_limit=outer_limit)
                    processed = 0
                    for member in expanded.members:
                        if len(members) + len(refusals) >= MAX_COLLECTION_MEMBERS:
                            break
                        admit(member)
                        processed += 1
                    for refusal in expanded.refusals:
                        if len(members) + len(refusals) >= MAX_COLLECTION_MEMBERS:
                            break
                        refusals.append(refusal)
                        processed += 1
                    omitted = len(expanded.members) + len(expanded.refusals) - processed
                    if omitted:
                        refuse(
                            "selection",
                            f"{omitted + len(selected) - index - 1} additional source(s) "
                            "were not examined after the "
                            f"{MAX_COLLECTION_MEMBERS}-source receipt limit",
                        )
                        break
                else:
                    validate_ingestion_filename(filename)
                    admit(
                        ScientificUploadMember(
                            filename=filename,
                            payload=payload,
                            source_name=source_name,
                        )
                    )
            except FileValidationError as exc:
                refuse(source_name, str(exc))
    finally:
        for upload in selected:
            await upload.close()

    return ScientificUploadBatch(members=tuple(members), refusals=tuple(refusals))


async def _read_upload(upload: UploadFile, *, max_bytes: int) -> bytes:
    chunks: list[bytes] = []
    observed = 0
    while True:
        chunk = await upload.read(min(1024 * 1024, max_bytes + 1 - observed))
        if not chunk:
            break
        observed += len(chunk)
        if observed > max_bytes:
            raise FileValidationError("File exceeds size limit")
        chunks.append(chunk)
    return b"".join(chunks)


def _members_from_zip(
    archive_name: str,
    payload: bytes,
    *,
    per_file_limit: int,
) -> ScientificUploadBatch:
    try:
        preflight_zip_central_directory(
            payload,
            max_members=MAX_COLLECTION_MEMBERS,
            max_directory_bytes=DEFAULT_MAX_CENTRAL_DIRECTORY_BYTES,
            max_uncompressed_bytes=MAX_COLLECTION_SOURCE_BYTES,
        )
        members: list[ScientificUploadMember] = []
        refusals: list[ScientificUploadRefusal] = []
        seen_paths: set[str] = set()
        seen_names: set[str] = set()
        with zipfile.ZipFile(io.BytesIO(payload), "r") as archive:
            for info in archive.infolist():
                raw_member_name = info.filename
                source_name = f"{archive_name}:{raw_member_name}"
                try:
                    member_name = (
                        raw_member_name[:-1] if info.is_dir() and raw_member_name.endswith("/") else raw_member_name
                    )
                    canonical_path = canonical_collection_file_name(member_name)
                    source_name = f"{archive_name}:{canonical_path}"
                    path_identity = canonical_path.casefold()
                    if path_identity in seen_paths:
                        raise FileValidationError("ZIP contains duplicate member path")
                    seen_paths.add(path_identity)
                    unix_mode = (info.external_attr >> 16) & 0xFFFF
                    if unix_mode and stat.S_ISLNK(unix_mode):
                        raise FileValidationError("ZIP symbolic links are not admitted")
                    if info.is_dir():
                        continue
                    if info.flag_bits & 0x1:
                        raise FileValidationError("Encrypted ZIP members are not admitted")
                    filename = sanitize_filename(Path(canonical_path).name)
                    validate_ingestion_filename(filename)
                    if filename.casefold() in seen_names:
                        raise FileValidationError(f"Duplicate scientific filename: {filename}")
                    seen_names.add(filename.casefold())
                    if info.file_size > per_file_limit:
                        raise FileValidationError("ZIP member exceeds the per-file size limit")
                    member_payload = archive.read(info)
                    if len(member_payload) != info.file_size:
                        raise FileValidationError("ZIP member size changed during admission")
                    members.append(
                        ScientificUploadMember(
                            filename=filename,
                            payload=member_payload,
                            source_name=source_name,
                        )
                    )
                except FileValidationError as exc:
                    refusals.append(ScientificUploadRefusal(source_name=source_name, reason=str(exc)))
                except (zipfile.BadZipFile, ValueError, OSError, RuntimeError) as exc:
                    refusals.append(
                        ScientificUploadRefusal(
                            source_name=source_name,
                            reason=f"ZIP member refused: {exc}",
                        )
                    )
        return ScientificUploadBatch(members=tuple(members), refusals=tuple(refusals))
    except FileValidationError:
        raise
    except (zipfile.BadZipFile, SherpaObjectError, ValueError, OSError, RuntimeError) as exc:
        raise FileValidationError(f"ZIP archive refused: {exc}") from exc
