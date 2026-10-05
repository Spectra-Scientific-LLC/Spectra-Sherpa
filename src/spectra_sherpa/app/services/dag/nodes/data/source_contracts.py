"""Shared, closed contracts for canonical local data-source nodes."""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Any, Iterable, Mapping

import numpy as np

from spectra_sherpa.io.types import SourceMember

_MANIFEST_SCHEMA = "spectrasherpa.file-manifest/1"
_CURVE_TYPES = frozenset({"sigmoid", "gaussian", "linear", "exponential", "step"})


def sha256_file(path: Path, *, max_bytes: int) -> str:
    """Return one bounded SHA-256 digest; never read beyond admission."""

    digest = hashlib.sha256()
    read_bytes = 0
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            read_bytes += len(chunk)
            if read_bytes > max_bytes:
                raise ValueError(f"source file exceeds the {max_bytes}-byte manifest limit")
            digest.update(chunk)
    return digest.hexdigest()


def file_manifest(
    root: Path,
    files: Iterable[Path],
    *,
    max_members: int,
    max_file_bytes: int,
    max_total_bytes: int,
) -> dict[str, Any]:
    """Describe a deterministic, root-relative set of source bytes."""

    resolved_root = root.resolve()
    candidates = list(files)
    if len(candidates) > max_members:
        raise ValueError(f"source manifest has {len(candidates)} files; limit is {max_members}")
    admitted: list[tuple[Path, str, int]] = []
    seen: set[str] = set()
    total_bytes = 0
    for candidate in candidates:
        resolved = candidate.resolve(strict=True)
        try:
            relative = resolved.relative_to(resolved_root).as_posix()
        except ValueError as exc:
            raise ValueError(f"source file escapes the admitted root: {candidate}") from exc
        if relative in seen:
            raise ValueError(f"source manifest repeats a file: {relative}")
        seen.add(relative)
        size_bytes = resolved.stat().st_size
        if size_bytes > max_file_bytes:
            raise ValueError(f"source file {relative!r} is {size_bytes} bytes; limit is {max_file_bytes}")
        total_bytes += size_bytes
        if total_bytes > max_total_bytes:
            raise ValueError(f"source manifest totals {total_bytes} bytes; aggregate limit is {max_total_bytes}")
        admitted.append((resolved, relative, size_bytes))
    members = [
        {
            "path": relative,
            "size_bytes": size_bytes,
            "sha256": sha256_file(resolved, max_bytes=max_file_bytes),
        }
        for resolved, relative, size_bytes in admitted
    ]
    return _finalize_file_manifest(members)


def file_manifest_from_members(
    root: Path,
    members: Iterable[tuple[Path, SourceMember]],
    *,
    max_members: int,
    max_file_bytes: int,
    max_total_bytes: int,
) -> dict[str, Any]:
    """Describe the exact registry snapshots that produced grouped values."""

    resolved_root = root.resolve()
    source_members = list(members)
    if len(source_members) > max_members:
        raise ValueError(f"source manifest has {len(source_members)} files; limit is {max_members}")
    projected: list[dict[str, Any]] = []
    seen: set[str] = set()
    total_bytes = 0
    for candidate, member in source_members:
        resolved = candidate.resolve(strict=True)
        try:
            relative = resolved.relative_to(resolved_root).as_posix()
        except ValueError as exc:
            raise ValueError(f"source file escapes the admitted root: {candidate}") from exc
        if relative in seen:
            raise ValueError(f"source manifest repeats a file: {relative}")
        if member.name != candidate.name:
            raise ValueError(f"registry source member {member.name!r} does not match grouped file {candidate.name!r}")
        seen.add(relative)
        if member.size_bytes > max_file_bytes:
            raise ValueError(f"source file {relative!r} is {member.size_bytes} bytes; limit is {max_file_bytes}")
        total_bytes += member.size_bytes
        if total_bytes > max_total_bytes:
            raise ValueError(f"source manifest totals {total_bytes} bytes; aggregate limit is {max_total_bytes}")
        projected.append(
            {
                "path": relative,
                "size_bytes": member.size_bytes,
                "sha256": member.sha256,
            }
        )
    return _finalize_file_manifest(projected)


def _finalize_file_manifest(members: list[dict[str, Any]]) -> dict[str, Any]:
    """Close and digest one normalized manifest projection."""

    members.sort(key=lambda item: item["path"])
    if not members:
        raise ValueError("source manifest requires at least one file")
    payload = {"schema_version": _MANIFEST_SCHEMA, "members": members}
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    return {**payload, "manifest_digest": hashlib.sha256(encoded).hexdigest()}


def canonical_synthetic_curve_parameters(parameters: Mapping[str, object]) -> dict[str, object]:
    """Validate one representation of a deterministic concentration curve."""

    projected = dict(parameters)
    curve_type = projected.get("curve_type")
    if not isinstance(curve_type, str) or curve_type not in _CURVE_TYPES:
        raise ValueError("curve_type is not admitted")

    n_points = projected.get("n_points")
    if isinstance(n_points, bool) or not isinstance(n_points, int) or not 10 <= n_points <= 100_000:
        raise ValueError("n_points must be an integer from 10 through 100000")

    for name in ("max_concentration", "center", "width", "duration_seconds"):
        value = projected.get(name)
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
            raise ValueError(f"{name} must be finite")
        projected[name] = float(value)

    if float(projected["max_concentration"]) < 0.0:
        raise ValueError("max_concentration may not be negative")
    if not 0.0 <= float(projected["center"]) <= 1.0:
        raise ValueError("center is a fraction and must be between zero and one")
    if not 0.0 < float(projected["width"]) <= 1.0:
        raise ValueError("width is a fraction and must be greater than zero and at most one")
    if float(projected["duration_seconds"]) <= 0.0:
        raise ValueError("duration_seconds must be greater than zero")

    # Defaults are the sole canonical representation of parameters that a
    # selected curve does not consume. This keeps the persisted DAG honest
    # without making the canvas expose several nearly identical source nodes.
    if curve_type == "linear" and (projected["center"] != 0.5 or projected["width"] != 0.1):
        raise ValueError("linear curves may not carry non-default center or width settings")
    if curve_type == "exponential" and projected["center"] != 0.5:
        raise ValueError("exponential curves may not carry a non-default center setting")
    if curve_type == "step" and projected["width"] != 0.1:
        raise ValueError("step curves may not carry a non-default width setting")
    return projected


def generate_synthetic_curve(parameters: Mapping[str, object]) -> tuple[np.ndarray, np.ndarray]:
    """Return physical time values and the exact admitted concentration curve."""

    projected = canonical_synthetic_curve_parameters(parameters)
    n_points = int(projected["n_points"])
    maximum = float(projected["max_concentration"])
    center = float(projected["center"])
    width = float(projected["width"])
    normalized_time = np.linspace(0.0, 1.0, n_points, dtype=np.float64)
    curve_type = str(projected["curve_type"])

    if curve_type == "sigmoid":
        curve = maximum / (1.0 + np.exp(-(normalized_time - center) / width))
    elif curve_type == "gaussian":
        curve = maximum * np.exp(-((normalized_time - center) ** 2) / (2.0 * width**2))
    elif curve_type == "linear":
        curve = maximum * normalized_time
    elif curve_type == "exponential":
        curve = maximum * (1.0 - np.exp(-normalized_time / width))
    elif curve_type == "step":
        curve = np.where(normalized_time >= center, maximum, 0.0)
    else:  # pragma: no cover - the closed validator makes this unreachable
        raise AssertionError("closed curve grammar returned an unknown curve")

    physical_time = normalized_time * float(projected["duration_seconds"])
    return physical_time, np.asarray(curve, dtype=np.float64)


__all__ = [
    "canonical_synthetic_curve_parameters",
    "file_manifest",
    "generate_synthetic_curve",
    "sha256_file",
]
