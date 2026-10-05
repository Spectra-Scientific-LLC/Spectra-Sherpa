"""Bounded wire helpers for canonical portable CSV datasets."""

from __future__ import annotations

import base64
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

SAMPLE_METADATA_CSV_PREFIX = "sample_meta."
PORTABLE_CSV_SCHEMA = "spectrasherpa-portable-csv/2"
PORTABLE_CSV_PREFIX = f"#{PORTABLE_CSV_SCHEMA},"
MAX_PORTABLE_CSV_ENVELOPE_BYTES = 8 * 1024 * 1024

_PORTABLE_CSV_FIELDS = frozenset(
    {
        "shape",
        "feature_axis",
        "sample_axis",
        "dataset",
        "target_context",
        "feature_columns",
        "target_columns",
        "sample_metadata_columns",
    }
)


def encode_portable_csv_envelope(value: Mapping[str, Any]) -> str:
    """Encode one closed metadata row without introducing CSV delimiters."""

    if set(value) != _PORTABLE_CSV_FIELDS:
        raise ValueError("portable CSV metadata must use the closed schema")
    encoded_json = json.dumps(
        dict(value),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("ascii")
    if len(encoded_json) > MAX_PORTABLE_CSV_ENVELOPE_BYTES:
        raise ValueError("portable CSV metadata exceeds the envelope limit")
    token = base64.urlsafe_b64encode(encoded_json).decode("ascii").rstrip("=")
    return PORTABLE_CSV_PREFIX + token


def portable_csv_envelope_decoded_size(first_line: str) -> int:
    """Return the decoded envelope size without allocating decoded metadata."""

    line = first_line.rstrip("\r\n")
    if not line.startswith(PORTABLE_CSV_PREFIX):
        raise ValueError("portable CSV metadata prefix is missing")
    token = line[len(PORTABLE_CSV_PREFIX) :]
    if not token or len(token) % 4 == 1 or any(character.isspace() for character in token):
        raise ValueError("portable CSV metadata envelope is malformed")
    return len(token) * 3 // 4


def read_portable_csv_envelope(path: str | Path) -> dict[str, Any] | None:
    """Read and admit the optional first-row portable metadata envelope."""

    with Path(path).open("rb") as stream:
        first_line = stream.readline(MAX_PORTABLE_CSV_ENVELOPE_BYTES * 2 + 1)
    if not first_line.startswith(PORTABLE_CSV_PREFIX.encode("ascii")):
        return None
    if len(first_line) > MAX_PORTABLE_CSV_ENVELOPE_BYTES * 2:
        raise ValueError("portable CSV metadata row exceeds the envelope limit")
    try:
        line = first_line.decode("ascii").rstrip("\r\n")
        token = line[len(PORTABLE_CSV_PREFIX) :]
        if not token or any(character.isspace() for character in token):
            raise ValueError
        padded = token + "=" * (-len(token) % 4)
        decoded = base64.b64decode(padded, altchars=b"-_", validate=True)
        if len(decoded) > MAX_PORTABLE_CSV_ENVELOPE_BYTES:
            raise ValueError
        value = json.loads(decoded)
    except (UnicodeDecodeError, ValueError, json.JSONDecodeError) as exc:
        raise ValueError("portable CSV metadata envelope is malformed") from exc
    if not isinstance(value, dict) or set(value) != _PORTABLE_CSV_FIELDS:
        raise ValueError("portable CSV metadata must use the closed schema")
    return value


__all__ = [
    "MAX_PORTABLE_CSV_ENVELOPE_BYTES",
    "PORTABLE_CSV_PREFIX",
    "PORTABLE_CSV_SCHEMA",
    "SAMPLE_METADATA_CSV_PREFIX",
    "encode_portable_csv_envelope",
    "portable_csv_envelope_decoded_size",
    "read_portable_csv_envelope",
]
