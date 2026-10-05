"""Path-free sidecar custody for admitted registered-reference members.

This is a filesystem identity helper, not an application service. Keeping it
below ``app.lib`` lets reusable scientific loaders read portable reference
identity without coupling the DAG tree to the application-service layer.
"""

from __future__ import annotations

import json
import os
import stat
import tempfile
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from spectra_sherpa.app.lib.reference_materialization import portable_reference_manifest

REGISTERED_REFERENCE_SIDECAR_SCHEMA = "spectra-sherpa-registered-reference-source/1"
MAX_REGISTERED_REFERENCE_SIDECAR_BYTES = 64 * 1024
_SIDECAR_KEYS = frozenset({"schema_version", "portable_reference"})


class RegisteredReferenceStorageError(ValueError):
    """A workspace registered-reference sidecar is missing or invalid."""


def registered_reference_sidecar_path(member_path: str | Path) -> Path:
    path = Path(member_path)
    return path.with_name(f"{path.name}.reference.json")


def write_registered_reference_sidecar(
    member_path: str | Path,
    portable_reference: Mapping[str, Any],
) -> Path:
    """Atomically bind one retained member to the current exact registry."""

    path = Path(member_path)
    if not _is_plain_file(path):
        raise RegisteredReferenceStorageError("registered reference member is unavailable")
    expected = _validated_portable_reference(portable_reference)
    payload = {
        "schema_version": REGISTERED_REFERENCE_SIDECAR_SCHEMA,
        "portable_reference": expected,
    }
    encoded = (json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n").encode()
    if len(encoded) > MAX_REGISTERED_REFERENCE_SIDECAR_BYTES:  # pragma: no cover - closed registry is tiny
        raise RegisteredReferenceStorageError("registered reference sidecar exceeds its byte limit")
    destination = registered_reference_sidecar_path(path)
    if destination.exists() or destination.is_symlink():
        raise RegisteredReferenceStorageError("registered reference sidecar already exists")
    temporary: Path | None = None
    try:
        descriptor, raw_path = tempfile.mkstemp(prefix=f".{destination.name}.", dir=destination.parent)
        temporary = Path(raw_path)
        with os.fdopen(descriptor, "wb") as target:
            target.write(encoded)
            target.flush()
            os.fsync(target.fileno())
        os.chmod(temporary, 0o600)
        os.replace(temporary, destination)
    except BaseException:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
        raise
    return destination


def read_registered_reference_sidecar(member_path: str | Path) -> dict[str, Any] | None:
    """Return a re-admitted portable reference, or ``None`` for ordinary files."""

    sidecar = registered_reference_sidecar_path(member_path)
    if not sidecar.exists():
        return None
    if not _is_plain_file(sidecar):
        raise RegisteredReferenceStorageError("registered reference sidecar must be a regular non-symlink file")
    if sidecar.stat().st_size > MAX_REGISTERED_REFERENCE_SIDECAR_BYTES:
        raise RegisteredReferenceStorageError("registered reference sidecar exceeds its byte limit")
    try:
        payload = json.loads(sidecar.read_bytes())
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RegisteredReferenceStorageError("registered reference sidecar is unreadable") from exc
    if not isinstance(payload, Mapping) or frozenset(payload) != _SIDECAR_KEYS:
        raise RegisteredReferenceStorageError("registered reference sidecar schema is invalid")
    if payload.get("schema_version") != REGISTERED_REFERENCE_SIDECAR_SCHEMA:
        raise RegisteredReferenceStorageError("registered reference sidecar version is unsupported")
    portable = payload.get("portable_reference")
    if not isinstance(portable, Mapping):
        raise RegisteredReferenceStorageError("registered reference sidecar identity is invalid")
    return _validated_portable_reference(portable, allow_legacy_source_scope=True)


def remove_registered_reference_sidecar(member_path: str | Path) -> None:
    registered_reference_sidecar_path(member_path).unlink(missing_ok=True)


def _validated_portable_reference(
    value: Mapping[str, Any], *, allow_legacy_source_scope: bool = False
) -> dict[str, Any]:
    projection_id = value.get("projection_id")
    if not isinstance(projection_id, str) or not projection_id:
        raise RegisteredReferenceStorageError("registered reference projection identity is invalid")
    expected = portable_reference_manifest(projection_id)
    candidate = dict(value)
    # Earlier /2 sidecars predate this registry-derived description. Re-admit
    # only that exact omission, in memory, without rewriting workspace custody.
    # Never repair an explicit scope, another schema, or any other difference.
    # New writes remain strict; member-byte/scientific checks stay in the loader.
    if (
        allow_legacy_source_scope
        and candidate.get("schema_version") == "spectra-sherpa-external-reference/2"
        and "source_scope" not in candidate
        and "source_scope" in expected
    ):
        candidate["source_scope"] = expected["source_scope"]
    if candidate != expected:
        raise RegisteredReferenceStorageError("registered reference sidecar differs from the active registry")
    return expected


def _is_plain_file(path: Path) -> bool:
    try:
        return stat.S_ISREG(path.lstat().st_mode) and not path.is_symlink()
    except OSError:
        return False


__all__ = [
    "MAX_REGISTERED_REFERENCE_SIDECAR_BYTES",
    "REGISTERED_REFERENCE_SIDECAR_SCHEMA",
    "RegisteredReferenceStorageError",
    "read_registered_reference_sidecar",
    "registered_reference_sidecar_path",
    "remove_registered_reference_sidecar",
    "write_registered_reference_sidecar",
]
