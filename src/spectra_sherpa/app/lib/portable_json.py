"""Closed, resource-admissible JSON wire for exported Sherpa datasets."""

from __future__ import annotations

import json
import math
import re
from collections.abc import Mapping
from typing import Any

PORTABLE_JSON_SCHEMA = "spectrasherpa-portable-json/1"
MAX_PORTABLE_JSON_BYTES = 32 * 1024 * 1024
MAX_PORTABLE_JSON_ELEMENTS = 1_000_000
_HEADER = f'{{"schema_version":"{PORTABLE_JSON_SCHEMA}","shape":['.encode("ascii")
_SHAPE_RE = re.compile(
    rb'^\{"schema_version":"spectrasherpa-portable-json/1","shape":\[([1-9][0-9]*(?:,[1-9][0-9]*)*)\],"decoded_nodes":([1-9][0-9]*),"dataset":'
)
_NUMBER_RE = re.compile(rb"-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?")


def _canonicalize_json_value(value: Any) -> Any:
    """Return recursively key-sorted JSON data without changing array order."""

    if isinstance(value, Mapping):
        if any(type(key) is not str for key in value):
            raise ValueError("portable JSON object keys must be strings")
        return {key: _canonicalize_json_value(value[key]) for key in sorted(value)}
    if isinstance(value, (list, tuple)):
        return [_canonicalize_json_value(item) for item in value]
    return value


def _scan_json_nodes(payload: bytes) -> int:
    """Count every JSON container, key, and value without allocating a tree."""

    count = 0
    index = 0
    while index < len(payload):
        byte = payload[index]
        if byte in b" \t\r\n,:}]":
            index += 1
            continue
        if byte in b"[{":
            count += 1
            index += 1
            continue
        if byte == ord('"'):
            count += 1
            index += 1
            while index < len(payload):
                if payload[index] == ord("\\"):
                    index += 2
                elif payload[index] == ord('"'):
                    index += 1
                    break
                else:
                    index += 1
            else:
                raise ValueError("portable JSON contains an unterminated string")
            continue
        if byte == ord("-") or ord("0") <= byte <= ord("9"):
            match = _NUMBER_RE.match(payload, index)
            if match is None:
                raise ValueError("portable JSON contains a malformed number")
            count += 1
            index = match.end()
            continue
        matched_constant = False
        for token in (b"true", b"false", b"null"):
            if payload.startswith(token, index):
                count += 1
                index += len(token)
                matched_constant = True
                break
        if matched_constant:
            continue
        raise ValueError("portable JSON contains an invalid token")
    return count


def encode_portable_json(dataset_wire: Mapping[str, Any], shape: list[int]) -> str:
    """Encode one exact transport envelope with an admission header before data."""

    dimensions = [int(value) for value in shape]
    if not dimensions or any(type(value) is not int or value < 1 for value in shape):
        raise ValueError("portable JSON shape must contain positive integers")
    if math.prod(dimensions) > MAX_PORTABLE_JSON_ELEMENTS:
        raise ValueError("portable JSON dataset exceeds the decoded-element limit")
    value = {
        "schema_version": PORTABLE_JSON_SCHEMA,
        "shape": dimensions,
        "decoded_nodes": 0,
        "dataset": _canonicalize_json_value(dataset_wire),
    }
    provisional = json.dumps(value, separators=(",", ":"), ensure_ascii=True, allow_nan=False).encode("ascii")
    decoded_nodes = _scan_json_nodes(provisional)
    if decoded_nodes > MAX_PORTABLE_JSON_ELEMENTS:
        raise ValueError("portable JSON dataset exceeds the decoded-element limit")
    value["decoded_nodes"] = decoded_nodes
    content = json.dumps(value, separators=(",", ":"), ensure_ascii=True, allow_nan=False) + "\n"
    if len(content.encode("ascii")) > MAX_PORTABLE_JSON_BYTES:
        raise ValueError("portable JSON artifact exceeds the byte limit")
    return content


def inspect_portable_json_header(payload: bytes) -> tuple[list[int], int, int]:
    """Admit byte size and declared array shape before JSON object allocation."""

    if not payload.startswith(_HEADER) or len(payload) > MAX_PORTABLE_JSON_BYTES:
        raise ValueError("portable JSON header or byte length is invalid")
    match = _SHAPE_RE.match(payload[:4096])
    if match is None:
        raise ValueError("portable JSON shape header is malformed")
    shape = [int(value) for value in match.group(1).split(b",")]
    x_elements = math.prod(shape)
    decoded_nodes = int(match.group(2))
    if x_elements > MAX_PORTABLE_JSON_ELEMENTS or decoded_nodes > MAX_PORTABLE_JSON_ELEMENTS:
        raise ValueError("portable JSON dataset exceeds the decoded-element limit")
    if _scan_json_nodes(payload) != decoded_nodes:
        raise ValueError("portable JSON decoded-node declaration contradicts its content")
    return shape, x_elements, decoded_nodes


def decode_portable_json(payload: bytes) -> dict[str, Any]:
    """Decode one duplicate-free, finite, byte-canonical portable JSON value."""

    shape, _x_elements, decoded_nodes = inspect_portable_json_header(payload)

    def unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        value: dict[str, Any] = {}
        for key, item in pairs:
            if key in value:
                raise ValueError("portable JSON contains duplicate fields")
            value[key] = item
        return value

    def reject_constant(value: str) -> None:
        raise ValueError(f"portable JSON contains non-finite constant {value}")

    try:
        decoded = json.loads(
            payload.decode("ascii"),
            object_pairs_hook=unique_object,
            parse_constant=reject_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("portable JSON is malformed") from exc
    if not isinstance(decoded, dict) or set(decoded) != {"schema_version", "shape", "decoded_nodes", "dataset"}:
        raise ValueError("portable JSON must use the closed schema")
    if (
        decoded["schema_version"] != PORTABLE_JSON_SCHEMA
        or decoded["shape"] != shape
        or decoded["decoded_nodes"] != decoded_nodes
    ):
        raise ValueError("portable JSON header contradicts its payload")
    dataset = decoded["dataset"]
    if not isinstance(dataset, dict):
        raise ValueError("portable JSON dataset must be an object")
    canonical = encode_portable_json(dataset, shape).encode("ascii")
    if payload != canonical:
        raise ValueError("portable JSON is not in canonical encoding")
    return dataset


__all__ = [
    "MAX_PORTABLE_JSON_BYTES",
    "MAX_PORTABLE_JSON_ELEMENTS",
    "PORTABLE_JSON_SCHEMA",
    "decode_portable_json",
    "encode_portable_json",
    "inspect_portable_json_header",
]
