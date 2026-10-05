"""Durable, no-follow storage for experiment collection definitions."""

from __future__ import annotations

import json
import os
import stat
import uuid
from collections.abc import Mapping
from pathlib import Path

from spectra_sherpa.app.lib.collection_definition import (
    MAX_COLLECTION_DEFINITION_BYTES,
    ValidatedCollectionDefinition,
    validate_collection_definition,
)
from spectra_sherpa.app.lib.file_permissions import restrict_file_descriptor
from spectra_sherpa.app.services.experiments import experiment_dir

_FILE_NAME = "collection-definition.json"


def collection_definition_path(experiment_id: int) -> Path:
    """Return the dedicated path; generic experiment metadata never owns it."""

    return experiment_dir(experiment_id) / "objects" / _FILE_NAME


def _read_bounded_regular(path: Path) -> bytes:
    try:
        lexical = path.lstat()
    except FileNotFoundError:
        raise
    if not stat.S_ISREG(lexical.st_mode):
        raise ValueError("collection definition is not an admitted regular file")
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_BINARY", 0)
    try:
        descriptor = os.open(path, flags)
    except FileNotFoundError:
        raise
    except OSError as exc:
        raise ValueError("collection definition is not an admitted regular file") from exc
    try:
        observed = os.fstat(descriptor)
        if not stat.S_ISREG(observed.st_mode) or observed.st_size > MAX_COLLECTION_DEFINITION_BYTES:
            raise ValueError("collection definition is not an admitted bounded regular file")
        # Windows stat mode bits do not describe its inherited profile ACL.
        if os.name != "nt" and observed.st_mode & 0o077:
            raise ValueError("collection definition must be private mode 0600")
        chunks: list[bytes] = []
        remaining = MAX_COLLECTION_DEFINITION_BYTES + 1
        while remaining:
            chunk = os.read(descriptor, min(1024 * 1024, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        payload = b"".join(chunks)
        if len(payload) > MAX_COLLECTION_DEFINITION_BYTES:
            raise ValueError("collection definition exceeds the 4 MiB limit")
        return payload
    finally:
        os.close(descriptor)


def read_collection_definition(experiment_id: int) -> ValidatedCollectionDefinition | None:
    """Read and validate the exact canonical definition, or report absence."""

    path = collection_definition_path(experiment_id)
    try:
        payload = _read_bounded_regular(path)
    except FileNotFoundError:
        return None
    try:
        decoded = json.loads(payload)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("collection definition is not valid canonical JSON") from exc
    definition = validate_collection_definition(decoded)
    if payload != definition.canonical_bytes:
        raise ValueError("collection definition bytes are not canonical")
    return definition


def write_collection_definition(
    experiment_id: int,
    value: Mapping[str, object],
) -> ValidatedCollectionDefinition:
    """Atomically publish a definition; POSIX mode 0600, inherited ACL on Windows."""

    definition = validate_collection_definition(value)
    path = collection_definition_path(experiment_id)
    parent = path.parent
    parent.mkdir(parents=True, exist_ok=True)
    if parent.is_symlink() or not parent.is_dir():
        raise ValueError("collection definition parent is not a regular private directory")
    try:
        leaf = path.lstat()
    except FileNotFoundError:
        leaf = None
    if leaf is not None and not stat.S_ISREG(leaf.st_mode):
        raise ValueError("collection definition destination is not a regular file")

    temporary = parent / f".{_FILE_NAME}.{uuid.uuid4().hex}.tmp"
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_BINARY", 0)
    descriptor = os.open(temporary, flags, 0o600)
    try:
        try:
            restrict_file_descriptor(descriptor)
            written = 0
            while written < len(definition.canonical_bytes):
                written += os.write(descriptor, definition.canonical_bytes[written:])
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        os.replace(temporary, path)
        # Windows cannot open directories with os.open for POSIX fsync.
        # The file contents have already been flushed before atomic replace.
        if os.name != "nt":
            directory_fd = os.open(parent, os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
    finally:
        if temporary.exists():
            temporary.unlink()
    return definition


def remove_collection_definition(experiment_id: int) -> None:
    """Remove only the dedicated regular leaf; never follow a link."""

    path = collection_definition_path(experiment_id)
    try:
        observed = path.lstat()
    except FileNotFoundError:
        return
    if not stat.S_ISREG(observed.st_mode):
        raise ValueError("collection definition destination is not a regular file")
    path.unlink()


__all__ = [
    "collection_definition_path",
    "read_collection_definition",
    "remove_collection_definition",
    "write_collection_definition",
]
