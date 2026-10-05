"""Import-light lossless scalar authorities for scientific metadata."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from datetime import date, datetime
from typing import TypeAlias

import numpy as np

JSON_SAFE_INTEGER_MAX = (1 << 53) - 1

LosslessScalar = str | int | float | bool | None
LosslessJSON: TypeAlias = LosslessScalar | list["LosslessJSON"] | dict[str, "LosslessJSON"]


def lossless_json_scalar(
    value: object,
    *,
    max_text_chars: int | None = None,
    field_name: str = "scientific metadata",
) -> LosslessScalar:
    """Normalize one scalar without collapsing its identity on the JSON wire."""

    if value is None:
        return None
    if isinstance(value, (bool, np.bool_)):
        return bool(value)
    if isinstance(value, str):
        if max_text_chars is not None and len(value) > max_text_chars:
            raise ValueError(f"{field_name} contains an oversized text value")
        return value
    if isinstance(value, (datetime, date)):
        raise ValueError(f"{field_name} contains an unsupported date or datetime value")
    if isinstance(value, (int, np.integer)):
        integer = int(value)
        if abs(integer) > JSON_SAFE_INTEGER_MAX:
            raise ValueError(f"{field_name} contains an integer outside the lossless JSON range")
        return integer
    if isinstance(value, (float, np.floating)):
        number = float(value)
        if not math.isfinite(number):
            raise ValueError(f"{field_name} contains a non-finite numeric value")
        return number
    raise ValueError(f"{field_name} contains an unsupported structured value")


def lossless_scalar_identity(value: LosslessScalar) -> tuple[str, LosslessScalar]:
    """Return a type-preserving identity suitable for duplicate checks."""

    if value is None:
        return ("null", None)
    if type(value) is bool:
        return ("boolean", value)
    if type(value) is int:
        return ("integer", value)
    if type(value) is float:
        return ("number", value)
    return ("string", value)


def lossless_json_value(
    value: object,
    *,
    field_name: str = "scientific metadata",
    max_depth: int = 12,
    max_scalars: int = 1_000_000,
    max_text_bytes: int = 4 * 1024 * 1024,
) -> LosslessJSON:
    """Normalize one bounded JSON tree without coercing scientific identity."""

    budget = {"nodes": 0, "text_bytes": 0}

    def require_budget() -> None:
        if budget["nodes"] > max_scalars or budget["text_bytes"] > max_text_bytes:
            raise ValueError(f"{field_name} exceeds the scalar or text budget")

    def normalize(item: object, *, depth: int) -> LosslessJSON:
        if depth > max_depth:
            raise ValueError(f"{field_name} exceeds the maximum nesting depth")
        budget["nodes"] += 1
        require_budget()
        if isinstance(item, Mapping):
            normalized: dict[str, LosslessJSON] = {}
            for key, nested in item.items():
                if not isinstance(key, str):
                    raise ValueError(f"{field_name} requires exact string mapping keys")
                budget["text_bytes"] += len(key.encode("utf-8"))
                require_budget()
                normalized[key] = normalize(nested, depth=depth + 1)
            result: LosslessJSON = normalized
        elif isinstance(item, Sequence) and not isinstance(item, (str, bytes, bytearray)):
            result = [normalize(nested, depth=depth + 1) for nested in item]
        else:
            scalar = lossless_json_scalar(item, field_name=field_name)
            if isinstance(scalar, str):
                budget["text_bytes"] += len(scalar.encode("utf-8"))
            result = scalar
        require_budget()
        return result

    return normalize(value, depth=0)


__all__ = [
    "JSON_SAFE_INTEGER_MAX",
    "LosslessScalar",
    "LosslessJSON",
    "lossless_json_scalar",
    "lossless_json_value",
    "lossless_scalar_identity",
]
