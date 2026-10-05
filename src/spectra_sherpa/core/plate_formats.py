"""Closed multi-well format registry shared by scientific and application paths."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from importlib.resources import files
from typing import Any

_REGISTRY_PATH = files("spectra_sherpa.data").joinpath("plate_formats_v1.json")
PLATE_FORMAT_REGISTRY_SCHEMA = "spectrasherpa.plate-formats/1"


@dataclass(frozen=True)
class PlateFormat:
    id: str
    label: str
    rows: tuple[str, ...]
    columns: int

    @property
    def capacity(self) -> int:
        return len(self.rows) * self.columns

    @property
    def first_well(self) -> str:
        return self.format_well(0, 0)

    @property
    def last_well(self) -> str:
        return self.format_well(len(self.rows) - 1, self.columns - 1)

    def format_well(self, row: int, column: int) -> str:
        return f"{self.rows[row]}{column + 1:02d}"

    def parse_well(self, value: object) -> tuple[int, int]:
        normalized = str(value).strip().upper()
        match = re.fullmatch(r"([A-Z]+)([0-9]+)", normalized)
        if match is None or match.group(1) not in self.rows:
            raise ValueError(f"Well {value!r} is outside {self.label} ({self.first_well} through {self.last_well})")
        column = int(match.group(2)) - 1
        if column < 0 or column >= self.columns or match.group(2) != f"{column + 1:02d}":
            raise ValueError(f"Well {value!r} is outside {self.label} ({self.first_well} through {self.last_well})")
        return self.rows.index(match.group(1)), column

    def admits_well(self, value: object) -> bool:
        try:
            self.parse_well(value)
        except ValueError:
            return False
        return True


def _load_registry() -> tuple[str, dict[str, PlateFormat]]:
    raw: Any = json.loads(_REGISTRY_PATH.read_text(encoding="utf-8"))
    if not isinstance(raw, dict) or raw.get("schema_version") != PLATE_FORMAT_REGISTRY_SCHEMA:
        raise RuntimeError("Plate-format registry schema is unsupported")
    entries = raw.get("formats")
    if not isinstance(entries, list) or not entries:
        raise RuntimeError("Plate-format registry must contain at least one format")
    registry: dict[str, PlateFormat] = {}
    for entry in entries:
        if not isinstance(entry, dict):
            raise RuntimeError("Plate-format registry entries must be objects")
        format_id = entry.get("id")
        label = entry.get("label")
        rows = entry.get("rows")
        columns = entry.get("columns")
        if (
            not isinstance(format_id, str)
            or not format_id
            or not isinstance(label, str)
            or not label
            or not isinstance(rows, list)
            or not rows
            or any(not isinstance(row, str) or not row for row in rows)
            or len(set(rows)) != len(rows)
            or isinstance(columns, bool)
            or not isinstance(columns, int)
            or columns < 1
            or format_id in registry
        ):
            raise RuntimeError("Plate-format registry contains an invalid entry")
        registry[format_id] = PlateFormat(format_id, label, tuple(rows), columns)
    default_format_id = raw.get("default_format_id")
    if not isinstance(default_format_id, str) or default_format_id not in registry:
        raise RuntimeError("Plate-format registry default is missing")
    return default_format_id, registry


DEFAULT_PLATE_FORMAT_ID, PLATE_FORMATS = _load_registry()


def get_plate_format(format_id: object) -> PlateFormat:
    normalized = str(format_id).strip()
    try:
        return PLATE_FORMATS[normalized]
    except KeyError as exc:
        raise ValueError(f"Unknown plate format {normalized!r}") from exc


def infer_legacy_plate_format(wells: list[str]) -> PlateFormat:
    """Infer only when exactly one registered format admits every saved well."""

    candidates = [
        plate_format for plate_format in PLATE_FORMATS.values() if all(plate_format.admits_well(w) for w in wells)
    ]
    if len(candidates) != 1:
        if len(PLATE_FORMATS) == 1:
            return next(iter(PLATE_FORMATS.values()))
        raise ValueError("Legacy sample table plate format is ambiguous")
    return candidates[0]
