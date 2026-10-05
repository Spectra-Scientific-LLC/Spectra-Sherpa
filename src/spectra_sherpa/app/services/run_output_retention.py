"""Versioned run output JSON files, separate from navigation and live handles.

Files are finalized before the row commits. A failed transaction can leave an
unreferenced file, never a reference to an unfinished file. Garbage collection
uses a grace period and retained database references, including failed runs.
"""

from __future__ import annotations

import hashlib
import json
import logging
import math
import os
import shutil
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from spectra_sherpa.app.core.config import settings
from spectra_sherpa.app.schemas.run_evidence import OutputEvidence, RunEvidence

logger = logging.getLogger(__name__)

FORMAT_VERSION = 1
FORMAT_OUTPUT_BYTES_LIMIT = 8 * 1024 * 1024
OUTPUT_BYTES_LIMIT = settings.run_output_max_bytes
RUN_BYTES_LIMIT = settings.run_output_run_max_bytes
USER_BYTES_LIMIT = settings.run_output_user_max_bytes
MAX_OUTPUT_VALUES = 500_000
INLINE_BUDGET_BYTES = 2 * 1024 * 1024
DETAIL_METADATA_BUDGET_BYTES = 512 * 1024
TRUNCATION_FLAGS = {
    "data_truncated",
    "target_truncated",
    "labels_truncated",
    "persisted_preview",
    "_truncated_array",
    "_truncated_matrix",
    "_truncated_sequence",
    "_truncated_numeric",
    "__model_placeholder__",
    "retention_nonfinite_values",
}


def admit_retained_value(value: Any) -> None:
    """Apply configured storage limits to the shared materialization guard."""
    from spectra_sherpa.app.services.dag.serialize import admit_retained_value as admit

    admit(value, max_values=MAX_OUTPUT_VALUES, max_bytes=OUTPUT_BYTES_LIMIT)


@contextmanager
def _storage_lock(directory: Path):
    flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(directory / ".lock", flags, 0o600)
    unlock = None
    try:
        try:
            import fcntl
        except ImportError:  # pragma: no cover - Windows
            import msvcrt

            if os.fstat(fd).st_size == 0:
                os.write(fd, b"0")
            os.lseek(fd, 0, os.SEEK_SET)
            msvcrt.locking(fd, msvcrt.LK_LOCK, 1)

            def unlock():
                msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)

        else:
            fcntl.flock(fd, fcntl.LOCK_EX)

            def unlock():
                fcntl.flock(fd, fcntl.LOCK_UN)

        yield
    finally:
        if unlock is not None:
            os.lseek(fd, 0, os.SEEK_SET)
            unlock()
        os.close(fd)


def _safe_json(value: Any) -> tuple[Any, bool]:
    if isinstance(value, float) and not math.isfinite(value):
        return None, True
    if isinstance(value, dict):
        items = {str(key): _safe_json(item) for key, item in value.items()}
        return {key: item for key, (item, _) in items.items()}, any(changed for _, changed in items.values())
    if isinstance(value, (tuple, list)):
        items = [_safe_json(item) for item in value]
        return [item for item, _ in items], any(changed for _, changed in items)
    return value, False


def _has_reduction(value: Any) -> bool:
    if isinstance(value, dict):
        return any(value.get(key) for key in TRUNCATION_FLAGS) or any(_has_reduction(item) for item in value.values())
    return isinstance(value, list) and any(_has_reduction(item) for item in value)


def _user_directory(user_id: int) -> Path:
    if user_id < 1:
        raise ValueError("Run evidence requires an owning user")
    root = settings.data_dir / "run-outputs-v1"
    directory = root / str(user_id)
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    if root.is_symlink() or directory.is_symlink():
        raise ValueError("Run output storage must not use symlinked directories")
    return directory


def _directory_signature(directory: Path) -> list[int]:
    stat = directory.stat()
    return [stat.st_dev, stat.st_ino, stat.st_mtime_ns, stat.st_ctime_ns]


def _quota_directory(directory: Path) -> Path:
    cache = directory / ".quota"
    cache.mkdir(exist_ok=True, mode=0o700)
    if cache.is_symlink():
        raise ValueError("Retained-output quota cache must not use symlinks")
    return cache


def _storage_usage(directory: Path) -> tuple[int, int]:
    """Under the storage lock, reuse counts only for an unchanged directory.

    The cache lives in a child directory so publishing it cannot invalidate
    its own signature. An interrupted output rename or cleanup invalidates
    the old signature even when the corresponding cache update never ran.
    """
    cache = _quota_directory(directory) / "state.json"
    try:
        if not cache.is_symlink() and cache.stat().st_size <= 4096:
            record = json.loads(cache.read_text())
            if (
                record.get("signature") == _directory_signature(directory)
                and type(record.get("bytes")) is int
                and record["bytes"] >= 0
                and type(record.get("count")) is int
                and record["count"] >= 0
            ):
                return record["bytes"], record["count"]
    except (OSError, ValueError, AttributeError):
        pass
    used = count = 0
    for path in directory.iterdir():
        if path.name == ".quota":
            continue
        count += 1
        if not path.is_symlink() and path.is_file():
            used += path.stat().st_size
    return used, count


def _save_storage_usage(directory: Path, used: int, count: int) -> None:
    cache = _quota_directory(directory)
    record = {"signature": _directory_signature(directory), "bytes": used, "count": count}
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", dir=cache, delete=False) as stream:
            temporary = Path(stream.name)
            json.dump(record, stream)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, cache / "state.json")
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def retain_output(
    user_id: int, value: Any, *, role: str | None = None, byte_limit: int = OUTPUT_BYTES_LIMIT
) -> OutputEvidence:
    admit_retained_value(value)
    value, changed = _safe_json(value)
    payload = json.dumps(
        {"format_version": FORMAT_VERSION, "value": value}, ensure_ascii=True, allow_nan=False, separators=(",", ":")
    ).encode()
    if len(payload) > min(byte_limit, OUTPUT_BYTES_LIMIT):
        raise ValueError("Output exceeds the configured retained output/run byte limit")
    digest = hashlib.sha256(payload).hexdigest()
    directory = _user_directory(user_id)
    destination = directory / f"{digest}.json"
    temporary = None
    try:
        with _storage_lock(directory):
            if shutil.disk_usage(directory).free < len(payload) + 128 * 1024 * 1024:
                raise ValueError("Insufficient free space for retained output; 128 MiB reserve required")
            used, count = _storage_usage(directory)
            if destination.is_symlink():
                raise ValueError("Retained output must not use a symlink")
            exists = destination.is_file()
            if count >= 20000 and not exists:
                raise ValueError("Retained-output file quota reached; reclaim unreferenced outputs")
            existing = destination.stat().st_size if exists else 0
            if used - existing + len(payload) > USER_BYTES_LIMIT:
                raise ValueError(
                    "Configured retained-output user quota reached; remove unneeded runs and reclaim storage"
                )
            with tempfile.NamedTemporaryFile(dir=directory, prefix=".pending-", delete=False) as stream:
                temporary = Path(stream.name)
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, destination)
            _save_storage_usage(directory, used - existing + len(payload), count + (0 if exists else 1))
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    reduced = changed or _has_reduction(value)
    return OutputEvidence(
        state="reduced" if reduced else "exact",
        reason=(
            "Output contains a declared preview/model placeholder or non-finite values rendered as null."
            if reduced
            else None
        ),
        role=role,
        storage="file",
        sha256=digest,
        byte_count=len(payload),
        format_version=FORMAT_VERSION,
    )


def retain_run_outputs(
    user_id: int, results: dict[str, Any], diagnostics: dict[str, Any], *, previous: dict[str, Any] | None = None
) -> dict[str, Any]:
    from spectra_sherpa.app.services.serialization import serialize_result

    if not settings.run_output_retention_enabled:
        return RunEvidence(reason="Automatic run-output retention is disabled in configuration.").model_dump()

    prior = RunEvidence.model_validate(previous) if previous else None
    inventory = prior.outputs if prior else {}
    stored_bytes = sum(item.byte_count or 0 for ports in inventory.values() for item in ports.values())
    # Small provenance records take precedence over large numerical outputs.
    entries = {key: results[key] for key in ("__workflow__", "__application__") if key in results}
    if "__application__" in entries:
        application = entries["__application__"]
        if isinstance(application, dict):
            entries["__application__"] = {
                **({"selection": application["selection"]} if "selection" in application else {}),
                **application,
            }
    if diagnostics:
        entries["__diagnostics__"] = diagnostics
    entries.update({key: value for key, value in results.items() if key not in entries})
    output_count = sum(len(ports) for ports in inventory.values())
    for node_id, result in entries.items():
        # The executor has already normalized NodeResult.outputs. A dict-valued
        # default is nested under "default"; exported_output_ports is a separate
        # code-generation contract and must not reinterpret runtime outputs.
        ports = result if isinstance(result, dict) and result.get("type") != "SherpaDataset" else {"default": result}
        inventory.setdefault(node_id, {})
        for port, value in ports.items():
            if port in inventory[node_id]:
                raise ValueError("Retained run outputs are immutable; an existing output cannot be replaced")
            output_count += 1
            if output_count > 1024:
                return RunEvidence(
                    reason="Run exceeds the 1024-output retention inventory limit.", outputs=inventory
                ).model_dump()
            if port.startswith("_") and node_id != "__diagnostics__":
                inventory[node_id][port] = OutputEvidence(
                    state="missing", reason="Not retained: private runtime output excluded by policy.", role=port
                )
                continue
            try:
                if stored_bytes >= RUN_BYTES_LIMIT:
                    raise ValueError("Run exceeds the configured retained-output budget")
                admit_retained_value(value)
                # Typed evaluations and scalar/date outputs use the same API
                # serializer as datasets; a second type allowlist drops valid
                # ports (for example PCA outlier EvaluationResult).
                serialized = serialize_result(value, owner_user_id=user_id, retain_full=True)
                inventory[node_id][port] = retain_output(
                    user_id, serialized, role=port, byte_limit=RUN_BYTES_LIMIT - stored_bytes
                )
                stored_bytes += inventory[node_id][port].byte_count or 0
            except Exception as exc:
                logger.exception("Could not retain run output node=%s port=%s", node_id, port)
                reason = (
                    str(exc) if isinstance(exc, ValueError) else "Output could not be finalized in durable storage."
                )
                inventory[node_id][port] = OutputEvidence(state="missing", reason=reason, role=port)
    incomplete = prior is not None and prior.qualification == "unverified"
    return RunEvidence(
        qualification="qualified" if any(inventory.values()) and not incomplete else "unverified",
        reason=(
            prior.reason
            if incomplete
            else None if any(inventory.values()) else "Execution produced no retained outputs."
        ),
        outputs=inventory,
    ).model_dump()


def read_output(user_id: int, evidence: OutputEvidence) -> Any:
    if evidence.storage != "file" or evidence.sha256 is None:
        raise FileNotFoundError(evidence.reason or "This historical output was not retained.")
    path = _user_directory(user_id) / f"{evidence.sha256}.json"
    if path.is_symlink():
        raise ValueError("Invalid retained output storage")
    if path.stat().st_size > FORMAT_OUTPUT_BYTES_LIMIT:
        raise ValueError("Retained output exceeds the supported byte limit")
    payload = path.read_bytes()
    if len(payload) != evidence.byte_count or hashlib.sha256(payload).hexdigest() != evidence.sha256:
        raise ValueError("Retained output checksum mismatch")
    envelope = json.loads(payload)
    if not isinstance(envelope, dict) or envelope.get("format_version") != FORMAT_VERSION:
        raise ValueError("Unsupported retained output format")
    if "value" not in envelope:
        raise ValueError("Retained output has no value")
    return envelope["value"]


def prune_unreferenced_outputs(user_id: int, retained_digests: set[str], *, grace_seconds: int = 86400) -> int:
    """Explicit maintenance only; callers must inventory all retained user runs."""
    if grace_seconds < 86400:
        raise ValueError("Run-output cleanup requires at least a 24-hour finalization grace period")
    cutoff = time.time() - grace_seconds
    removed = 0
    directory = _user_directory(user_id)
    with _storage_lock(directory):
        for path in directory.iterdir():
            if path.is_symlink() or not path.is_file() or path.stat().st_mtime >= cutoff:
                continue
            if path.suffix == ".json" and path.stem in retained_digests:
                continue
            if path.suffix == ".json" or path.name.startswith(".pending-"):
                path.unlink()
                removed += 1
    return removed


def retained_storage_usage(user_id: int) -> dict[str, int]:
    """Report the same owner quota accounting used when retaining outputs."""
    directory = _user_directory(user_id)
    with _storage_lock(directory):
        used, _ = _storage_usage(directory)
    return {"used_bytes": used, "quota_bytes": USER_BYTES_LIMIT, "grace_seconds": 86400}
