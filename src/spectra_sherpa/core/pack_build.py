"""Verify an explicitly supplied installed source inventory without loading code.

Only trusted startup chooses the root and inventory. Retained pack manifests do
not select filesystem paths. This establishes source-build identity, not a
sandbox, license grant, or proof that a client received any content.
"""

from __future__ import annotations

import hashlib
import json
import os
import stat
from pathlib import Path, PurePosixPath
from typing import Annotated

from pydantic import Field, model_validator

from spectra_sherpa.core.pack_manifest import Digest, Frozen, PackManifest, PackReference

MAX_BUILD_FILES = 256
MAX_FILE_BYTES = 1024 * 1024
MAX_BUILD_BYTES = 16 * 1024 * 1024


class PackBuildError(ValueError):
    """An explicitly supplied installed build does not match its declaration."""


class PackFile(Frozen):
    path: Annotated[str, Field(min_length=1, max_length=240, pattern=r"^[A-Za-z0-9_./-]+$")]
    sha256: Digest

    @model_validator(mode="after")
    def confined_path(self):
        parts = self.path.split("/")
        if len(parts) > 16 or any(part in {"", ".", "..", "__pycache__"} for part in parts):
            raise ValueError("Invalid pack file path")
        if PurePosixPath(self.path).is_absolute() or self.path.endswith((".pyc", ".pyo")):
            raise ValueError("Pack inventory must name source files")
        return self


def build_sha256(files: tuple[PackFile, ...]) -> str:
    if not files or len(files) > MAX_BUILD_FILES or len({entry.path for entry in files}) != len(files):
        raise PackBuildError("Pack source inventory must be bounded and unique")
    payload = {
        "schema_version": "spectra-pack-source-build/1",
        "files": [entry.model_dump() for entry in sorted(files, key=lambda entry: entry.path)],
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _installed_files(root: Path) -> set[str]:
    result = set()
    entries_seen = 0
    for directory, directories, filenames in os.walk(root, followlinks=False):
        # Python's generated cache is not part of the installed source build.
        directories[:] = [name for name in directories if name != "__pycache__"]
        for name in (*directories, *filenames):
            entries_seen += 1
            path = Path(directory) / name
            if entries_seen > MAX_BUILD_FILES * 4 or path.is_symlink():
                raise PackBuildError("Installed pack tree is unbounded or contains a symlink")
        for name in filenames:
            path = Path(directory) / name
            if not path.is_file():
                raise PackBuildError("Installed pack entry is not a regular file")
            result.add(path.relative_to(root).as_posix())
            if len(result) > MAX_BUILD_FILES:
                raise PackBuildError("Installed pack has too many files")
    return result


def _read_source(root: Path, relative: str) -> bytes:
    """Read regular source through pinned directories where supported.

    Windows lacks dir_fd/O_NOFOLLOW: its trusted installation tree must remain
    immutable during startup. No platform attests previously imported bytecode.
    """
    descriptors = []
    try:
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
        if os.open in os.supports_dir_fd and hasattr(os, "O_NOFOLLOW") and hasattr(os, "O_DIRECTORY"):
            directory = os.open(root, flags | os.O_DIRECTORY)
            descriptors.append(directory)
            parts = relative.split("/")
            for part in parts[:-1]:
                directory = os.open(part, flags | os.O_DIRECTORY, dir_fd=directory)
                descriptors.append(directory)
            descriptor = os.open(parts[-1], flags, dir_fd=directory)
        else:
            descriptor = os.open(root / relative, flags)
        descriptors.append(descriptor)
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise PackBuildError("Installed pack entry is not a regular file")
        # fdopen owns a duplicate, leaving descriptor cleanup unambiguous.
        with os.fdopen(os.dup(descriptor), "rb") as stream:
            return stream.read(MAX_FILE_BYTES + 1)
    finally:
        for descriptor in reversed(descriptors):
            os.close(descriptor)


def verify_installed_build(root: Path, files: tuple[PackFile, ...], manifest: PackManifest) -> PackReference:
    """Check complete source-file membership and captured bytes; import nothing."""
    if build_sha256(files) != manifest.build_sha256:
        raise PackBuildError("Pack build declaration does not match its source inventory")
    try:
        root = root.resolve(strict=True)
        if not root.is_dir() or _installed_files(root) != {entry.path for entry in files}:
            raise PackBuildError("Installed pack source-file membership differs")
        total = 0
        for entry in files:
            path = root.joinpath(*PurePosixPath(entry.path).parts)
            if not path.resolve(strict=True).is_relative_to(root):
                raise PackBuildError("Installed pack path escapes its root")
            content = _read_source(root, entry.path)
            total += len(content)
            if len(content) > MAX_FILE_BYTES or total > MAX_BUILD_BYTES:
                raise PackBuildError("Installed pack source exceeds its byte bound")
            if hashlib.sha256(content).hexdigest() != entry.sha256:
                raise PackBuildError("Installed pack source bytes differ")
    except OSError as exc:
        raise PackBuildError("Installed pack source is unavailable") from exc
    return manifest.reference
