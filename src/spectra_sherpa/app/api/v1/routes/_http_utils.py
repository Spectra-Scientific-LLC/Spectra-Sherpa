"""Small HTTP response helpers shared by route modules."""

from __future__ import annotations

import re
from urllib.parse import quote


def safe_download_stem(name: str | None, fallback: str = "download", *, lowercase: bool = False) -> str:
    """Return a conservative ASCII filename stem for attachment headers."""

    value = (name or fallback).strip()
    if lowercase:
        value = value.lower()
    value = re.sub(r"[\r\n/\\\";]+", "_", value)
    value = re.sub(r"\s+", "_", value)
    pattern = r"[^a-z0-9._-]+" if lowercase else r"[^A-Za-z0-9._-]+"
    value = re.sub(pattern, "_", value)
    value = value.strip("._-")
    return value or fallback


def attachment_headers(filename: str, *, fallback: str = "download", lowercase: bool = False) -> dict[str, str]:
    """Build safe Content-Disposition headers for a download filename."""

    stem, dot, suffix = filename.rpartition(".")
    safe_stem = safe_download_stem(stem or filename, fallback=fallback, lowercase=lowercase)
    safe_suffix = re.sub(r"[^A-Za-z0-9]+", "", suffix)[:16] if dot else ""
    safe_filename = f"{safe_stem}.{safe_suffix}" if safe_suffix else safe_stem
    return {
        "Content-Disposition": (f"attachment; filename=\"{safe_filename}\"; filename*=UTF-8''{quote(safe_filename)}")
    }
