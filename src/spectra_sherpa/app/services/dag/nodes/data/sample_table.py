"""Closed portable sample-table contract for canonical data preparation."""

from __future__ import annotations

import json
import math
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, TypedDict, cast

import numpy as np
import pandas as pd

from spectra_sherpa.app.lib.axes import SampleAxis
from spectra_sherpa.core.plate_formats import (
    DEFAULT_PLATE_FORMAT_ID,
    get_plate_format,
    infer_legacy_plate_format,
)
from spectra_sherpa.core.spectra_meta import get_spectra_meta

SAMPLE_TABLE_SCHEMA_VERSION = "spectrasherpa.sample-table/2"
_TARGET_SCHEMA_COLUMN = "target_schema"
_STRUCTURAL_COLUMNS = frozenset({"row_index", "source_file_id", "sample_id", "include", _TARGET_SCHEMA_COLUMN})
_PLATE_FORMAT_COLUMN = "plate_format"
_RESERVED_TARGET_NAMES = _STRUCTURAL_COLUMNS | {_PLATE_FORMAT_COLUMN, "plate_id", "well"}


def _declares_portable_sample_table(columns: Sequence[object]) -> bool:
    """Distinguish the editor wire from ordinary scientific CSV columns.

    ``sample_id`` and ``row_index`` are useful ordinary dataset columns, so a
    single overlapping name is not enough to claim the closed sample-table
    schema.  The schema-specific ``target_schema`` column is conclusive; two
    or more structural names are also enough to make a malformed editor
    export fail closed instead of being reinterpreted as features.
    """

    present = _STRUCTURAL_COLUMNS.intersection(str(column) for column in columns)
    return _TARGET_SCHEMA_COLUMN in present or len(present) >= 2


class SampleTablePayload(TypedDict):
    """JSON-safe sample identities, target, decisions, and annotations."""

    schema_version: str
    source_file_id: int
    row_indices: list[int]
    sample_ids: list[str]
    include: list[bool]
    target_definitions: dict[str, str]
    target_name: str
    target_type: str
    target_values: list[Any]
    annotations: dict[str, list[Any]]


def _parse_include(value: Any, *, row_number: int) -> bool:
    if isinstance(value, (bool, np.bool_)):
        return bool(value)
    text = str(value).strip().lower()
    if text in {"true", "1", "yes", "include", "included"}:
        return True
    if text in {"false", "0", "no", "exclude", "excluded"}:
        return False
    raise ValueError(f"Sample table row {row_number} has invalid include value {value!r}")


def _json_scalar(value: Any) -> Any:
    """Return one JSON-safe table cell without stringifying its meaning."""

    if pd.isna(value):
        return None
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def _validate_plate_well_coordinates(
    plate_values: Sequence[Any],
    well_values: Sequence[Any],
    *,
    format_values: Sequence[Any] | None,
    row_prefix: str,
) -> tuple[list[str], list[str]]:
    """Validate and normalize one unambiguous physical plate assignment."""

    normalized_wells = ["" if well is None else str(well).strip().upper() for well in well_values]
    assigned_wells = [well for well in normalized_wells if well]
    if format_values is None:
        plate_format = (
            infer_legacy_plate_format(assigned_wells) if assigned_wells else get_plate_format(DEFAULT_PLATE_FORMAT_ID)
        )
        normalized_formats = [plate_format.id] * len(normalized_wells)
    else:
        normalized_formats = ["" if value is None else str(value).strip() for value in format_values]
        unique_formats = {value for value in normalized_formats if value}
        if len(unique_formats) != 1 or any(not value for value in normalized_formats):
            raise ValueError(f"{row_prefix} must declare one plate format for every row")
        plate_format = get_plate_format(unique_formats.pop())

    occupied: dict[tuple[str, str], int] = {}
    for row_number, (plate, well_text) in enumerate(
        zip(plate_values, normalized_wells, strict=True),
        start=1,
    ):
        plate_text = "" if plate is None else str(plate).strip()
        if well_text and not plate_text:
            raise ValueError(f"{row_prefix} row {row_number} has a well but no plate ID")
        if well_text and not plate_format.admits_well(well_text):
            raise ValueError(f"{row_prefix} row {row_number} has a well outside {plate_format.label}")
        if well_text:
            coordinate = (plate_text, well_text)
            previous_row = occupied.get(coordinate)
            if previous_row is not None:
                raise ValueError(
                    f"{row_prefix} rows {previous_row} and {row_number} assign duplicate "
                    f"plate/well coordinate {plate_text}/{well_text}"
                )
            occupied[coordinate] = row_number
    return normalized_wells, normalized_formats


def _target_definitions(frame: pd.DataFrame) -> dict[str, str]:
    raw_values = frame[_TARGET_SCHEMA_COLUMN].fillna("").astype(str).map(str.strip).tolist()
    if not raw_values or any(not value for value in raw_values):
        raise ValueError("Portable sample table target_schema is required on every row")
    if len(set(raw_values)) != 1:
        raise ValueError("Portable sample table target_schema must be identical on every row")
    try:
        parsed = json.loads(raw_values[0])
    except json.JSONDecodeError as exc:
        raise ValueError("Portable sample table target_schema is not valid JSON") from exc
    if (
        not isinstance(parsed, dict)
        or not parsed
        or any(
            not isinstance(name, str)
            or not name.strip()
            or name in _RESERVED_TARGET_NAMES
            or target_type not in {"continuous", "categorical"}
            for name, target_type in parsed.items()
        )
    ):
        raise ValueError("Portable sample table target_schema must map target names to closed scientific types")
    missing = sorted(set(parsed).difference(str(column) for column in frame.columns))
    if missing:
        raise ValueError(f"Portable sample table is missing declared target columns: {', '.join(missing)}")
    return {str(name): str(target_type) for name, target_type in parsed.items()}


def inspect_portable_sample_table(path: str | Path) -> dict[str, str] | None:
    """Return declared targets for one portable table without selecting one."""

    source_path = Path(path)
    if source_path.suffix.lower() != ".csv":
        return None
    # CSV identifiers and categorical values are lexical scientific data. Read
    # them as text and convert only fields whose contract declares them numeric.
    frame = pd.read_csv(source_path, dtype=str, keep_default_na=False)
    if not _declares_portable_sample_table(frame.columns):
        return None
    missing = sorted(_STRUCTURAL_COLUMNS.difference(str(column) for column in frame.columns))
    if missing:
        raise ValueError(f"Portable sample table is missing structural columns: {', '.join(missing)}")
    if frame.empty:
        raise ValueError("Portable sample table contains no sample rows")
    return _target_definitions(frame)


def load_portable_sample_table(
    path: str | Path,
    *,
    selected_target: object = None,
    target_type: object = None,
) -> SampleTablePayload | None:
    """Load the exact editor CSV when its structural signature is present.

    Ordinary CSV datasets return ``None``.  A file that declares any of the
    reserved structural fields must declare all of them and satisfy the closed
    sample-table contract; it may not silently fall back to a feature table.
    """

    source_path = Path(path)
    if source_path.suffix.lower() != ".csv":
        return None
    # Keep identifiers and categorical values lexical. Numeric conversion below
    # is limited to structural indices, source IDs, and continuous targets.
    frame = pd.read_csv(source_path, dtype=str, keep_default_na=False)
    if not _declares_portable_sample_table(frame.columns):
        return None
    missing = sorted(_STRUCTURAL_COLUMNS.difference(str(column) for column in frame.columns))
    if missing:
        raise ValueError(f"Portable sample table is missing structural columns: {', '.join(missing)}")
    if frame.empty:
        raise ValueError("Portable sample table contains no sample rows")
    target_definitions = _target_definitions(frame)

    numeric_row_indices = pd.to_numeric(frame["row_index"], errors="raise")
    if not np.all(np.isfinite(numeric_row_indices)) or not np.all(
        numeric_row_indices.to_numpy(dtype=np.float64) == numeric_row_indices.astype(int).to_numpy()
    ):
        raise ValueError("Portable sample table row_index values must be finite integers")
    row_indices = numeric_row_indices.astype(int).tolist()
    if row_indices != list(range(len(frame.index))):
        raise ValueError("Portable sample table row_index must be the exact zero-based source row order")
    numeric_source_ids = pd.to_numeric(frame["source_file_id"], errors="raise")
    if not np.all(np.isfinite(numeric_source_ids)) or not np.all(
        numeric_source_ids.to_numpy(dtype=np.float64) == numeric_source_ids.astype(int).to_numpy()
    ):
        raise ValueError("Portable sample table source_file_id values must be finite integers")
    source_ids = numeric_source_ids.astype(int)
    unique_source_ids = sorted(set(source_ids.tolist()))
    if len(unique_source_ids) != 1 or unique_source_ids[0] < 1:
        raise ValueError("Portable sample table must bind every row to one exact positive source_file_id")

    sample_ids = frame["sample_id"].map(str.strip).tolist()
    if any(not sample_id for sample_id in sample_ids):
        raise ValueError("Portable sample table requires a non-empty sample_id for every row")
    if len(set(sample_ids)) != len(sample_ids):
        raise ValueError("Portable sample table sample_id values must be unique")
    include = [_parse_include(value, row_number=index + 1) for index, value in enumerate(frame["include"])]

    target_name = str(selected_target).strip() if selected_target is not None else ""
    if not target_name:
        raise ValueError("Portable sample table loading requires one explicit selected_target")
    if target_name not in target_definitions:
        raise ValueError(f"Portable sample table target column {target_name!r} is not declared")
    normalized_target_type = str(target_type).strip() if target_type is not None else ""
    declared_target_type = target_definitions[target_name]
    if normalized_target_type and normalized_target_type != declared_target_type:
        raise ValueError("Portable sample table selected target type disagrees with target_schema")
    normalized_target_type = declared_target_type
    target_series = frame[target_name]
    included_target = target_series[np.asarray(include, dtype=bool)]
    if included_target.map(str.strip).eq("").any():
        raise ValueError("Every included sample requires a target value")
    if normalized_target_type == "continuous":
        target_values = pd.to_numeric(target_series, errors="coerce")
        included_numeric = target_values[np.asarray(include, dtype=bool)].to_numpy(dtype=np.float64)
        if target_values[np.asarray(include, dtype=bool)].isna().any() or not np.all(np.isfinite(included_numeric)):
            raise ValueError("Every included continuous target must be numeric and finite")
        target_payload: list[Any] = [None if pd.isna(value) else float(value) for value in target_values]
    else:
        target_payload = [None if not str(value).strip() else str(value) for value in target_series]

    annotation_columns = [
        str(column)
        for column in frame.columns
        if str(column) not in _STRUCTURAL_COLUMNS and str(column) not in target_definitions
    ]
    annotations: dict[str, list[Any]] = {
        "include": ["true" if value else "false" for value in include],
        "source_file_id": [int(value) for value in source_ids.tolist()],
        "row_index": row_indices,
    }
    for column in annotation_columns:
        annotations[column] = [_json_scalar(value) for value in frame[column].tolist()]
    plate_values = annotations.get("plate_id")
    well_values = annotations.get("well")
    if well_values is not None:
        if plate_values is None:
            raise ValueError("Portable sample table well annotations require a plate_id column")
        normalized_wells, normalized_formats = _validate_plate_well_coordinates(
            plate_values,
            well_values,
            format_values=annotations.get(_PLATE_FORMAT_COLUMN),
            row_prefix="Portable sample table",
        )
        annotations["well"] = normalized_wells
        if _PLATE_FORMAT_COLUMN in annotations:
            annotations[_PLATE_FORMAT_COLUMN] = normalized_formats

    return {
        "schema_version": SAMPLE_TABLE_SCHEMA_VERSION,
        "source_file_id": unique_source_ids[0],
        "row_indices": row_indices,
        "sample_ids": sample_ids,
        "include": include,
        "target_definitions": target_definitions,
        "target_name": target_name,
        "target_type": normalized_target_type,
        "target_values": target_payload,
        "annotations": annotations,
    }


def load_portable_sample_table_editor(
    path: str | Path,
    *,
    selected_target: object,
    target_type: object,
) -> dict[str, Any] | None:
    """Return a validated portable table in the measured-sample editor shape."""

    payload = load_portable_sample_table(
        path,
        selected_target=selected_target,
        target_type=target_type,
    )
    if payload is None:
        return None
    # Preserve categorical spellings such as "01" through an edit round-trip.
    # The validated payload above remains the scientific type authority.
    frame = pd.read_csv(path, dtype=str, keep_default_na=False)
    definitions = payload["target_definitions"]
    structural_annotations = {"include", "source_file_id", "row_index"}
    physical_annotations = {_PLATE_FORMAT_COLUMN, "plate_id", "well"}
    group_columns = [
        name
        for name in payload["annotations"]
        if name not in structural_annotations and name not in physical_annotations
    ]
    plate_formats = payload["annotations"].get(_PLATE_FORMAT_COLUMN)
    plate_format_id = (
        str(plate_formats[0])
        if plate_formats and all(str(value) == str(plate_formats[0]) for value in plate_formats)
        else DEFAULT_PLATE_FORMAT_ID
    )
    plate_ids = payload["annotations"].get("plate_id", [""] * len(frame.index))
    wells = payload["annotations"].get("well", [""] * len(frame.index))
    rows = []
    for index in range(len(frame.index)):
        rows.append(
            {
                "row_index": payload["row_indices"][index],
                "source_file_id": payload["source_file_id"],
                "sample_id": payload["sample_ids"][index],
                "include": payload["include"][index],
                "targets": {name: str(frame.iloc[index][name]) for name in definitions},
                "plate_id": "" if plate_ids[index] is None else str(plate_ids[index]),
                "well": "" if wells[index] is None else str(wells[index]),
                "annotations": {name: str(frame.iloc[index][name]) for name in group_columns},
            }
        )
    return {
        "schema_version": "spectrasherpa.sample-table-editor/1",
        "source_file_id": payload["source_file_id"],
        "selected_target": payload["target_name"],
        "target_definitions": [
            {"name": name, "type": definition_type} for name, definition_type in definitions.items()
        ],
        "annotation_columns": group_columns,
        "plate_format_id": plate_format_id,
        "rows": rows,
    }


def _validate_target_values(*, target_type: object, include: list[Any], values: list[Any]) -> None:
    for row_number, (included, target_value) in enumerate(zip(include, values, strict=True), start=1):
        if target_type == "continuous":
            if target_value is None:
                if included:
                    raise ValueError(f"sample_table row {row_number} requires a continuous target")
                continue
            if isinstance(target_value, bool) or not isinstance(target_value, (int, float)):
                raise ValueError(f"sample_table row {row_number} continuous target must be numeric")
            if not math.isfinite(float(target_value)):
                raise ValueError(f"sample_table row {row_number} continuous target must be finite")
        elif included and (not isinstance(target_value, str) or not target_value.strip()):
            raise ValueError(f"sample_table row {row_number} requires a categorical target")


def _validate_annotations(
    annotations: object,
    *,
    count: int,
    source_file_id: int,
    row_indices: list[Any],
    include: list[Any],
    target_names: set[str],
) -> None:
    if not isinstance(annotations, Mapping) or any(
        not isinstance(name, str)
        or not name.strip()
        or name in target_names
        or not isinstance(column, list)
        or len(column) != count
        for name, column in annotations.items()
    ):
        raise ValueError("sample_table annotations are not row-aligned")
    for name, column in annotations.items():
        for cell in column:
            if not isinstance(cell, (str, int, float, bool, type(None))):
                raise ValueError(f"sample_table annotation {name!r} must contain JSON scalar values")
            if isinstance(cell, float) and not math.isfinite(cell):
                raise ValueError(f"sample_table annotation {name!r} must contain finite values")
    expected_structural_annotations = {
        "row_index": row_indices,
        "source_file_id": [source_file_id] * count,
        "include": ["true" if item else "false" for item in include],
    }
    for name, expected in expected_structural_annotations.items():
        if annotations.get(name) != expected:
            raise ValueError(f"sample_table annotation {name!r} does not match its structural field")
    plate_values = annotations.get("plate_id")
    well_values = annotations.get("well")
    if well_values is not None:
        if plate_values is None:
            raise ValueError("sample_table well annotations require plate_id annotations")
        _validate_plate_well_coordinates(
            plate_values,
            well_values,
            format_values=annotations.get(_PLATE_FORMAT_COLUMN),
            row_prefix="sample_table",
        )


def validate_sample_table_payload(value: object) -> SampleTablePayload:
    """Validate the closed in-memory value received through a typed port."""

    if not isinstance(value, Mapping):
        raise ValueError("sample_table must be a SampleTable/2.0 mapping")
    required = {
        "schema_version",
        "source_file_id",
        "row_indices",
        "sample_ids",
        "include",
        "target_definitions",
        "target_name",
        "target_type",
        "target_values",
        "annotations",
    }
    if set(value) != required:
        raise ValueError(f"sample_table fields must be exactly {sorted(required)}")
    if value["schema_version"] != SAMPLE_TABLE_SCHEMA_VERSION:
        raise ValueError("sample_table schema version is unsupported")
    source_file_id = value["source_file_id"]
    target_name = value["target_name"]
    target_type = value["target_type"]
    row_indices = value["row_indices"]
    sample_ids = value["sample_ids"]
    include = value["include"]
    target_definitions = value["target_definitions"]
    target_values = value["target_values"]
    annotations = value["annotations"]
    if isinstance(source_file_id, bool) or not isinstance(source_file_id, int) or source_file_id < 1:
        raise ValueError("sample_table source_file_id must be an exact positive integer")
    if not isinstance(target_name, str) or not target_name.strip():
        raise ValueError("sample_table target_name must be a non-empty exact column name")
    if (
        not isinstance(target_definitions, Mapping)
        or not target_definitions
        or any(
            not isinstance(name, str) or not name.strip() or declared_type not in {"continuous", "categorical"}
            for name, declared_type in target_definitions.items()
        )
        or target_definitions.get(target_name) != target_type
    ):
        raise ValueError("sample_table target_definitions do not bind the selected target")
    if target_type not in {"continuous", "categorical"}:
        raise ValueError("sample_table target_type must be continuous or categorical")
    if not all(isinstance(item, list) for item in (row_indices, sample_ids, include, target_values)):
        raise ValueError("sample_table row fields must be JSON arrays")
    count = len(cast(Sequence[Any], row_indices))
    if list(row_indices) != list(range(count)):
        raise ValueError("sample_table row_indices must preserve exact zero-based source order")
    if any(len(cast(Sequence[Any], item)) != count for item in (sample_ids, include, target_values)):
        raise ValueError("sample_table row fields are not aligned")
    if any(not isinstance(item, str) or not item.strip() for item in sample_ids):
        raise ValueError("sample_table sample_ids must be non-empty strings")
    if len(set(cast(Sequence[str], sample_ids))) != count:
        raise ValueError("sample_table sample_ids must be unique")
    if any(not isinstance(item, bool) for item in include):
        raise ValueError("sample_table include values must be booleans")
    if not any(include):
        raise ValueError("sample_table must include at least one sample")
    _validate_target_values(target_type=target_type, include=include, values=target_values)
    _validate_annotations(
        annotations,
        count=count,
        source_file_id=source_file_id,
        row_indices=row_indices,
        include=include,
        target_names=set(cast(Mapping[str, str], target_definitions)),
    )
    return cast(SampleTablePayload, dict(value))


def apply_sample_table_to_dataset(dataset: Any, value: object) -> SampleTablePayload:
    """Verify source/row/target identity and attach portable annotations."""

    table = validate_sample_table_payload(value)
    n_samples = int(dataset.shape[0])
    if len(table["row_indices"]) != n_samples:
        raise ValueError("sample_table row count does not match the spectral dataset")
    metadata = get_spectra_meta(dataset)
    file_id = metadata.provenance.file_id if metadata and metadata.provenance else None
    if file_id is None:
        raise ValueError("sample_table attachment requires exact source-file provenance on X")
    if int(file_id) != int(table["source_file_id"]):
        raise ValueError("sample_table source_file_id does not match the spectral dataset source")
    existing_labels = getattr(getattr(dataset, "sample_axis", None), "labels", None)
    if existing_labels is not None and [str(value) for value in existing_labels] != table["sample_ids"]:
        raise ValueError("sample_table sample_id values do not match the spectral dataset sample order")

    prior_axis = getattr(dataset, "sample_axis", None)
    axis = SampleAxis(
        values=(
            np.asarray(prior_axis.values).copy()
            if prior_axis is not None and prior_axis.values is not None
            else np.arange(n_samples, dtype=np.float64)
        ),
        labels=list(table["sample_ids"]),
        classes=(
            ["" if value is None else str(value) for value in table["target_values"]]
            if table["target_type"] == "categorical"
            else None
        ),
        include_mask=np.asarray(table["include"], dtype=bool),
        exclusion_reasons=[None if included else "excluded_by_sample_table" for included in table["include"]],
        sample_table={name: list(values) for name, values in table["annotations"].items()},
        title=getattr(prior_axis, "title", None) if prior_axis is not None else "Sample",
    )
    dataset.sample_axis = axis
    return table


__all__ = [
    "SAMPLE_TABLE_SCHEMA_VERSION",
    "SampleTablePayload",
    "apply_sample_table_to_dataset",
    "inspect_portable_sample_table",
    "load_portable_sample_table",
    "load_portable_sample_table_editor",
    "validate_sample_table_payload",
]
