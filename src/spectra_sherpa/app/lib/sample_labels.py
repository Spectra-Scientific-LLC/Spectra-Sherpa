"""Utilities for concise, useful sample labels.

Scientific file readers often expose object reprs, paths, or class labels as
sample labels. Those strings are useful provenance, but poor row labels. Keep
the meaningful varying part visible and move parseable provenance into the
sample table.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Sequence

_PATH_RE = re.compile(r"(?:PosixPath|WindowsPath)\(['\"]([^'\"]+)['\"]\)")
_FILE_TOKEN_RE = re.compile(
    r"(?P<path>[A-Za-z0-9_./@()+\-\s]+?\.(?:spa|spg|spc|srs|wdf|opus|jdx|dx|txt|csv|dat|asc|mat))",
    re.IGNORECASE,
)
_DATETIME_RE = re.compile(
    r"datetime\.datetime\(\s*(\d{4})\s*,\s*(\d{1,2})\s*,\s*(\d{1,2})"
    r"(?:\s*,\s*(\d{1,2})\s*,\s*(\d{1,2})(?:\s*,\s*(\d{1,2}))?)?"
)
_TIME_UNIT_PATTERN = (
    r"µs|μs|us|usec|usecs|microseconds?|msec|msecs|milliseconds?|ms|"
    r"secs?|seconds?|s|mins?|minutes?|min|hrs?|hours?|h"
)
_LINKED_TIME_RE = re.compile(
    rf"linked\s+spectrum\s+at\s*([+-]?\d+(?:\.\d+)?)\s*({_TIME_UNIT_PATTERN})\b",
    re.IGNORECASE,
)
_QUANTITY_RE = re.compile(
    rf"\b([+-]?\d+(?:\.\d+)?)\s*" rf"(torr|mbar|bar|pa|kpa|ppm|%|{_TIME_UNIT_PATTERN}|sec|hr)\b",
    re.IGNORECASE,
)
_QUANTITY_LABEL_RE = re.compile(
    rf"^\s*([+-]?\d+(?:\.\d+)?)\s*(torr|mbar|bar|pa|kpa|ppm|%|{_TIME_UNIT_PATTERN}|sec|hr)\.?\s*$",
    re.IGNORECASE,
)
_PREFIXED_SAMPLE_RE = re.compile(r"^[^:]{1,120}:\s*(sample(?:[_\s-]*\d+)?)\s*$", re.IGNORECASE)
_GENERIC_LABELS = {"", "nan", "none", "null", "normal", "sample", "unknown"}
_KNOWN_SPECTRAL_SUFFIXES = {
    ".spa",
    ".spg",
    ".spc",
    ".srs",
    ".wdf",
    ".opus",
    ".jdx",
    ".dx",
    ".txt",
    ".csv",
    ".dat",
    ".asc",
    ".mat",
}
_TIME_UNIT_ALIASES = {
    "µs": "us",
    "μs": "us",
    "us": "us",
    "usec": "us",
    "usecs": "us",
    "microsecond": "us",
    "microseconds": "us",
    "ms": "ms",
    "msec": "ms",
    "msecs": "ms",
    "millisecond": "ms",
    "milliseconds": "ms",
    "s": "s",
    "sec": "s",
    "secs": "s",
    "second": "s",
    "seconds": "s",
    "min": "min",
    "mins": "min",
    "minute": "min",
    "minutes": "min",
    "h": "h",
    "hr": "h",
    "hrs": "h",
    "hour": "h",
    "hours": "h",
}
_TIME_UNIT_SECONDS = {"us": 1e-6, "ms": 1e-3, "s": 1.0, "min": 60.0, "h": 3600.0}


def normalize_time_unit(unit: Any) -> str | None:
    """Return a canonical time unit label used by SherpaDataset axes."""

    if unit is None:
        return None
    text = str(unit).strip().lower()
    return _TIME_UNIT_ALIASES.get(text)


def time_unit_seconds(unit: Any) -> float | None:
    """Return the scale factor from a supported time unit to seconds."""

    normalized = normalize_time_unit(unit)
    if normalized is None:
        return None
    return _TIME_UNIT_SECONDS[normalized]


def clean_sample_labels(
    raw_labels: Sequence[Any] | None,
    n_samples: int,
    *,
    fallback_prefix: str = "Sample",
    source_name: str | None = None,
) -> list[str]:
    """Return short, useful row labels.

    If the supplied labels collapse to one value such as ``normal`` for many
    samples, they are not identifiers and should not drive row names or plots.
    Meaningful duplicate labels such as class names are preserved because they
    are useful for coloring and grouping.
    """

    n = int(n_samples)
    if n <= 0:
        return []

    fallback = _safe_prefix(fallback_prefix)
    if raw_labels is None or len(raw_labels) != n:
        if n == 1 and source_name:
            return [_clip(_file_display_name(source_name))]
        return _indexed_labels(fallback, n)

    labels = [
        _short_sample_label(label, fallback=_indexed_label(fallback, idx), source_name=source_name)
        for idx, label in enumerate(raw_labels)
    ]
    labels = _use_common_difference_if_better(labels)
    labels = [
        _clip(label.strip()) if label.strip() else _indexed_label(fallback, idx) for idx, label in enumerate(labels)
    ]

    normalized = [_normalize_for_compare(label) for label in labels]
    if n > 1 and len(set(normalized)) <= 1:
        return _indexed_labels(fallback, n)

    return labels


def parse_sample_label_metadata(raw_label: Any) -> dict[str, Any]:
    """Extract structured provenance from verbose reader labels."""

    text = "" if raw_label is None else str(raw_label).strip()
    metadata: dict[str, Any] = {}
    if not text:
        return metadata

    path = _extract_path(text)
    if path:
        metadata["source_path"] = path
        metadata["source_file"] = Path(path).name

    acquired = _extract_datetime(text)
    if acquired:
        metadata["acquired_datetime"] = acquired

    linked_time = _LINKED_TIME_RE.search(text)
    if linked_time:
        metadata["time_value"] = float(linked_time.group(1))
        metadata["time_units"] = normalize_time_unit(linked_time.group(2)) or linked_time.group(2)

    quantity = _QUANTITY_RE.search(text)
    if quantity and "time_value" not in metadata:
        quantity_value = float(quantity.group(1))
        quantity_units = quantity.group(2)
        time_units = normalize_time_unit(quantity_units)
        if time_units:
            metadata["time_value"] = quantity_value
            metadata["time_units"] = time_units
        else:
            metadata["condition_value"] = quantity_value
            metadata["condition_units"] = quantity_units
            metadata["condition"] = f"{quantity.group(1)} {quantity_units}"

    if text and not metadata and _short_sample_label(text, fallback="") != text and _is_safe_raw_metadata(text):
        metadata["raw_label"] = _collapse_whitespace(text)
    return metadata


def _short_sample_label(raw_label: Any, *, fallback: str, source_name: str | None = None) -> str:
    text = "" if raw_label is None else str(raw_label).strip()
    if not text or _normalize_for_compare(text) in _GENERIC_LABELS:
        return fallback

    linked_time = _LINKED_TIME_RE.search(text)
    if linked_time:
        unit = normalize_time_unit(linked_time.group(2)) or linked_time.group(2)
        return f"{linked_time.group(1)} {unit}"

    prefixed_sample = _PREFIXED_SAMPLE_RE.match(text)
    if prefixed_sample and re.search(r"\d", prefixed_sample.group(1)):
        return prefixed_sample.group(1).replace("_", " ")

    quantity_label = _QUANTITY_LABEL_RE.match(text)
    if quantity_label:
        unit = normalize_time_unit(quantity_label.group(2)) or quantity_label.group(2)
        return f"{quantity_label.group(1)} {unit}"

    path = _extract_path(text)
    if path:
        return _file_display_name(path)

    acquired = _extract_datetime(text)
    if acquired:
        return acquired.replace("T", " ")

    if source_name:
        prefix = f"{source_name}:"
        if text.lower().startswith(prefix.lower()):
            suffix = text[len(prefix) :].strip()
            if suffix:
                return suffix

    if _looks_like_verbose_repr(text):
        return fallback
    return text


def _extract_path(text: str) -> str | None:
    match = _PATH_RE.search(text)
    if match:
        return match.group(1)
    match = _FILE_TOKEN_RE.search(text)
    if match:
        return match.group("path").strip()
    return None


def _extract_datetime(text: str) -> str | None:
    match = _DATETIME_RE.search(text)
    if not match:
        return None
    year, month, day, hour, minute, second = match.groups()
    if hour is None or minute is None:
        return f"{int(year):04d}-{int(month):02d}-{int(day):02d}"
    return f"{int(year):04d}-{int(month):02d}-{int(day):02d}T{int(hour):02d}:{int(minute):02d}:{int(second or 0):02d}"


def _file_display_name(value: str) -> str:
    path = Path(str(value).strip().strip("'\""))
    name = path.name or str(value)
    suffix = path.suffix
    return name[: -len(suffix)] if suffix.lower() in _KNOWN_SPECTRAL_SUFFIXES else name


def _looks_like_verbose_repr(text: str) -> bool:
    if len(text) > 90:
        return True
    return any(token in text for token in ("datetime.datetime(", "PosixPath(", "WindowsPath(", "array("))


def _is_safe_raw_metadata(text: str) -> bool:
    if len(text) > 240:
        return False
    # Keep ordinary whitespace, reject binary/control payloads from some
    # instrument readers. Those strings can overwhelm node metadata panels.
    return re.search(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]", text) is None


def _collapse_whitespace(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _use_common_difference_if_better(labels: list[str]) -> list[str]:
    if len(labels) < 2 or max(len(label) for label in labels) <= 80:
        return labels
    prefix = _common_prefix(labels)
    suffix = _common_suffix(labels)
    if len(prefix) + len(suffix) < 12:
        return labels
    trimmed = []
    for label in labels:
        end = len(label) - len(suffix) if suffix else len(label)
        value = label[len(prefix) : end].strip(" -_:,[]()")
        trimmed.append(value)
    if all(trimmed) and len(set(map(_normalize_for_compare, trimmed))) == len(trimmed):
        return [_clip(value) for value in trimmed]
    return labels


def _common_prefix(values: Sequence[str]) -> str:
    if not values:
        return ""
    prefix = values[0]
    for value in values[1:]:
        while prefix and not value.startswith(prefix):
            prefix = prefix[:-1]
    return prefix


def _common_suffix(values: Sequence[str]) -> str:
    reversed_values = [value[::-1] for value in values]
    return _common_prefix(reversed_values)[::-1]


def _safe_prefix(value: str) -> str:
    prefix = _file_display_name(value).strip()
    return prefix if prefix and _normalize_for_compare(prefix) not in _GENERIC_LABELS else "Sample"


def _indexed_label(prefix: str, idx: int) -> str:
    return f"{prefix} {idx + 1:03d}"


def _indexed_labels(prefix: str, n: int) -> list[str]:
    return [_indexed_label(prefix, idx) for idx in range(n)]


def _normalize_for_compare(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip().lower())


def _clip(value: str, limit: int = 80) -> str:
    return value if len(value) <= limit else f"{value[: limit - 3].rstrip()}..."
