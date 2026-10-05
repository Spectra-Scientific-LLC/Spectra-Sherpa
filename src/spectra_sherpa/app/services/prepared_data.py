from __future__ import annotations

import hashlib
import json
import logging
import os
import stat
from pathlib import Path
from typing import Any, Mapping

from spectra_sherpa.app.core.config import settings
from spectra_sherpa.core.prepared_data import (
    PreparedDataOverrides as PreparedDataOverrides,
)
from spectra_sherpa.core.prepared_data import (
    apply_dataset_prepared_data_overrides as apply_dataset_prepared_data_overrides,
)
from spectra_sherpa.core.prepared_data import (
    apply_serialized_prepared_data_overrides as apply_serialized_prepared_data_overrides,
)
from spectra_sherpa.core.prepared_data import (
    bind_explicit_target_selection as bind_explicit_target_selection,
)
from spectra_sherpa.core.prepared_data import (
    merge_prepared_data_overrides,
    parser_options_for_prepared_data,
)

logger = logging.getLogger(__name__)


_OVERRIDES_DIR = Path(settings.data_dir) / ".metadata_overrides"
PREPARED_DATA_SIDECAR_MAX_BYTES = 64 * 1024


def normalize_relative_data_path(file_path: str) -> str:
    # Metadata sidecars only need a stable identifier; this helper normalizes
    # display/storage keys and does not open the path. Sidecar filenames are
    # derived from a SHA-256 digest, never from this raw string directly.
    raw = str(file_path).replace("\\", "/")
    normalized = _normalize_path_identifier(raw)
    data_dir = _normalize_path_identifier(str(settings.data_dir).replace("\\", "/"))
    if normalized == data_dir:
        return ""
    data_prefix = f"{data_dir}/"
    if data_dir and normalized.startswith(data_prefix):
        return normalized[len(data_prefix) :]
    return normalized


def _normalize_path_identifier(value: str) -> str:
    """Normalize a path-like identifier without opening or resolving it."""

    prefix = "/" if value.startswith("/") else ""
    parts: list[str] = []
    for part in value.split("/"):
        if part in {"", "."}:
            continue
        if part == "..":
            if parts and parts[-1] != "..":
                parts.pop()
            else:
                parts.append(part)
            continue
        parts.append(part)
    return prefix + "/".join(parts)


def _sidecar_digest(kind: str, *parts: str) -> str:
    """Return an opaque, filesystem-safe identifier for a sidecar record."""
    payload = "\x1f".join([kind, *parts])
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def sidecar_path(*, file_path: str | None, source: str | None, name: str | None) -> Path:
    if source and name:
        filename = f"ref__{_sidecar_digest('ref', source, name)}.json"
    elif file_path:
        filename = f"file__{_sidecar_digest('file', normalize_relative_data_path(file_path))}.json"
    else:
        raise ValueError("Either file_path or source+name required")

    sanitised = _OVERRIDES_DIR / filename
    # Final containment check: the resolved sidecar must live under
    # ``_OVERRIDES_DIR``.  This is belt-and-braces — the filename is now
    # a fixed-prefix SHA-256 hex digest — but defends against drift if the
    # directory is ever computed differently.
    overrides_root = _OVERRIDES_DIR.resolve()
    resolved = sanitised.resolve()
    if not resolved.is_relative_to(overrides_root):
        raise ValueError("Computed sidecar path escapes the overrides directory.")
    return sanitised


def load_prepared_data_overrides(
    *,
    file_path: str | None = None,
    source: str | None = None,
    name: str | None = None,
) -> PreparedDataOverrides:
    try:
        target = sidecar_path(file_path=file_path, source=source, name=name)
        if target.exists():
            return PreparedDataOverrides.from_mapping(json.loads(target.read_text(encoding="utf-8")))
    except Exception:
        logger.warning("Failed to load prepared data overrides for %s", file_path or source or name, exc_info=True)
        return PreparedDataOverrides()
    return PreparedDataOverrides()


def load_prepared_data_overrides_strict(
    *,
    file_path: str | None = None,
    source: str | None = None,
    name: str | None = None,
) -> PreparedDataOverrides:
    """Read one persisted sidecar without links, truncation, or silent defaults.

    Absence has the exact empty-override meaning.  Once a sidecar exists, its
    bytes are durable scientific state: callers that bind or export a project
    must refuse rather than reinterpret an unreadable record as empty.
    """

    target = sidecar_path(file_path=file_path, source=source, name=name)
    try:
        observed = target.lstat()
    except FileNotFoundError:
        return PreparedDataOverrides()
    if stat.S_ISLNK(observed.st_mode) or not stat.S_ISREG(observed.st_mode):
        raise ValueError("prepared-data sidecar is not a regular file")
    if observed.st_size > PREPARED_DATA_SIDECAR_MAX_BYTES:
        raise ValueError("prepared-data sidecar exceeds the 64 KiB limit")

    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_BINARY", 0)
    try:
        descriptor = os.open(target, flags)
    except OSError as exc:
        raise ValueError("prepared-data sidecar is unavailable") from exc
    try:
        admitted = os.fstat(descriptor)
        if not stat.S_ISREG(admitted.st_mode):
            raise ValueError("prepared-data sidecar is not a regular file")
        if admitted.st_size > PREPARED_DATA_SIDECAR_MAX_BYTES:
            raise ValueError("prepared-data sidecar exceeds the 64 KiB limit")
        chunks: list[bytes] = []
        remaining = PREPARED_DATA_SIDECAR_MAX_BYTES + 1
        while remaining:
            chunk = os.read(descriptor, min(64 * 1024, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        payload = b"".join(chunks)
        if len(payload) > PREPARED_DATA_SIDECAR_MAX_BYTES:
            raise ValueError("prepared-data sidecar exceeds the 64 KiB limit")
    finally:
        os.close(descriptor)

    try:
        decoded = json.loads(payload.decode("utf-8"))
        if not isinstance(decoded, Mapping):
            raise ValueError("prepared-data sidecar must contain an object")
        return PreparedDataOverrides.from_sidecar_mapping(decoded)
    except (UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError) as exc:
        raise ValueError("prepared-data sidecar is invalid") from exc


def save_prepared_data_overrides(
    overrides: PreparedDataOverrides | Mapping[str, Any],
    *,
    file_path: str | None = None,
    source: str | None = None,
    name: str | None = None,
) -> None:
    prepared = (
        overrides if isinstance(overrides, PreparedDataOverrides) else PreparedDataOverrides.from_mapping(overrides)
    )
    if prepared.csv_layout is not None:
        if file_path is None:
            raise ValueError("csv_layout requires one exact CSV file source")
        parser_options_for_prepared_data(Path(file_path).name, prepared)
    target = sidecar_path(file_path=file_path, source=source, name=name)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(prepared.to_sidecar_dict(), indent=2), encoding="utf-8")


def load_prepared_data_overrides_for_source(
    *,
    source: str,
    parameters: Mapping[str, Any],
    resolved_file_paths: list[str] | None = None,
) -> PreparedDataOverrides:
    file_paths = resolved_file_paths or []
    if file_paths:
        loaded = [load_prepared_data_overrides(file_path=normalize_relative_data_path(path)) for path in file_paths]
        return merge_prepared_data_overrides(loaded)

    if source == "file":
        file_path = parameters.get("file_path")
        if isinstance(file_path, str) and file_path:
            return load_prepared_data_overrides(file_path=normalize_relative_data_path(file_path))

    reference_name = reference_dataset_name(source=source, parameters=parameters)
    if reference_name is not None:
        return load_prepared_data_overrides(source=source, name=reference_name)

    return PreparedDataOverrides()


def reference_dataset_name(*, source: str, parameters: Mapping[str, Any]) -> str | None:
    if source == "sklearn":
        value = parameters.get("sklearn_dataset")
        return str(value) if value else None
    if source == "eigenvector":
        value = parameters.get("eigenvector_dataset")
        return str(value) if value else None
    if source == "oes":
        value = parameters.get("oes_dataset")
        return str(value) if value else None
    return None
