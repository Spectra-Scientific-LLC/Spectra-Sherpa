"""
Application I/O utilities over the canonical native ingestion registry.

Current source parsing is delegated to the canonical native registry.

MIGRATED FROM: project0/io.py, project1/plot_ftir_spectra.py
"""

from __future__ import annotations

import csv
import logging
import re
from collections.abc import Mapping
from pathlib import Path
from typing import TYPE_CHECKING, Any, Optional, Union

if TYPE_CHECKING:
    from spectra_sherpa.app.lib.sherpa_dataset import SherpaDataset

import numpy as np
import pandas as pd

from spectra_sherpa.app.core.path_security import resolve_existing_file_path
from spectra_sherpa.app.lib.portable_csv import SAMPLE_METADATA_CSV_PREFIX, read_portable_csv_envelope

logger = logging.getLogger(__name__)

# Filename pattern for extracting species labels
# The previous form ``^[A-Z0-9]+[\s_-]?.*\.CSV$`` flagged as polynomial-redos
# because ``[A-Z0-9]+`` and ``.*`` could both consume alphanumeric chars,
# leaving the engine to retry many partitionings on non-matching inputs.
# Folding the separator into the optional tail group eliminates the
# overlap: either the filename is just ``LABEL.CSV`` or the label is
# followed by exactly one separator and then arbitrary content.
FILENAME_PATTERN = re.compile(
    r"^(?P<label>[A-Z0-9]+)(?:[\s_-].*)?\.CSV$",
    re.IGNORECASE,
)
CONC_PATTERN = re.compile(r"\(([^()]*?)ppm", re.IGNORECASE)
_CSV_AXIS_UNITS_PATTERN = re.compile(r"\((?P<units>[^)]*)\)")

CSV_LAYOUT_OPTIONS = (
    {
        "value": "headered",
        "label": "Headered CSV (decimal point)",
        "description": "Supplier header row; comma, semicolon, or tab delimiter; decimal point values.",
    },
    {
        "value": "headerless_two_column_spectrum",
        "label": "Unheaded X/Y spectrum (decimal point)",
        "description": "One coordinate column and one intensity column with no header row.",
    },
    {
        "value": "headerless_axis_column_spectra",
        "label": "Unheaded axis-column spectra (decimal point)",
        "description": "One coordinate column followed by multiple sample spectra, with samples stored in columns.",
    },
    {
        "value": "headered_decimal_comma",
        "label": "Headered CSV (decimal comma)",
        "description": "Supplier header row with semicolon or tab delimiter and decimal comma values.",
    },
    {
        "value": "headerless_two_column_spectrum_decimal_comma",
        "label": "Unheaded X/Y spectrum (decimal comma)",
        "description": "Semicolon- or tab-delimited coordinate/intensity pairs using decimal commas.",
    },
    {
        "value": "headerless_axis_column_spectra_decimal_comma",
        "label": "Unheaded axis-column spectra (decimal comma)",
        "description": "Semicolon- or tab-delimited coordinate and sample columns using decimal commas.",
    },
)


def _optional_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _categorical_class_names(values: Any) -> list[str]:
    """Return real categorical levels without treating missing cells as a class.

    Portable sample tables deliberately permit an excluded source row to omit
    its target.  Pandas represents that empty CSV cell as ``NaN`` inside the
    otherwise textual object array, so NumPy sorting cannot safely compare the
    raw values.  Normalize only the non-missing scientific labels here while
    leaving the row-aligned target array itself unchanged for later filtering.
    """

    names: set[str] = set()
    for value in np.asarray(values, dtype=object).reshape(-1):
        if pd.isna(value):
            continue
        label = str(value).strip()
        if label:
            names.add(label)
    return sorted(names)


def _spectral_axis_info_from_header(header: str) -> tuple[str, str | None] | None:
    """Return spectral axis title and units for a scientist-style CSV header."""

    cleaned = str(header).lstrip("\ufeff").strip()
    lower = cleaned.lower()
    if "raman" in lower and "shift" in lower:
        title = "Raman Shift"
    elif "wavenumber" in lower or "wave number" in lower:
        title = "Wavenumber"
    elif "wavelength" in lower or "wave length" in lower:
        title = "Wavelength"
    elif "chemical shift" in lower:
        title = "Chemical Shift"
    elif lower in {"m/z", "mz"} or "mass-to-charge" in lower or "mass to charge" in lower:
        title = "m/z"
    elif lower in {"cm-1", "cm^-1", "cm⁻¹", "cm−1", "1/cm"}:
        return "Wavenumber", "cm-1"
    elif lower in {"nm", "nanometer", "nanometers"}:
        return "Wavelength", "nm"
    elif lower == "ppm":
        return "Chemical Shift", "ppm"
    else:
        return None

    units_match = _CSV_AXIS_UNITS_PATTERN.search(cleaned)
    units = units_match.group("units").strip() if units_match else None
    if units in {"cm^-1", "cm⁻¹", "cm−1"}:
        units = "cm-1"
    return title, units or None


def _normalize_axis_units(units: str | None) -> str | None:
    if units is None:
        return None
    cleaned = str(units).strip()
    if not cleaned:
        return None
    if cleaned.casefold() in {"cm^-1", "cm⁻¹", "cm−1", "cm-1", "1/cm"}:
        return "cm-1"
    return cleaned


def _clean_csv_column_name(column: Any) -> str:
    return str(column).lstrip("\ufeff").strip()


def _is_empty_csv_column(name: str, values: pd.Series) -> bool:
    if not name or re.match(r"^Unnamed:\s*\d+$", name, flags=re.IGNORECASE):
        text = values.astype(str).str.strip().str.lower()
        return values.isna().all() or bool(text.isin({"", "nan", "none"}).all())
    return False


_ROW_INDEX_HEADERS = frozenset({"index", "idx", "row", "id", "#", "no", "no."})


def _split_row_index_column(df: pd.DataFrame, headers: list[str]) -> tuple[pd.DataFrame, list[str], list[str] | None]:
    """Separate an exported row index from the measured columns.

    pandas (``to_csv(index=True)``) writes an unnamed first column numbered
    0, 1, 2, ...; R ``write.table`` writes row names under a header one field
    shorter than its rows. Either is sample identity, never a feature: in a
    table sorted by class, the index alone predicts the class.
    """

    if not isinstance(df.index, pd.RangeIndex):
        # pandas already moved R-style row names into the index.
        return df.reset_index(drop=True), headers, [str(value) for value in df.index]
    if df.shape[1] < 2 or len(df) < 2:
        return df, headers, None
    name = _clean_csv_column_name(headers[0])
    unnamed = not name or re.match(r"^Unnamed:\s*\d+$", name, flags=re.IGNORECASE) is not None
    if not unnamed and name.casefold() not in _ROW_INDEX_HEADERS:
        return df, headers, None
    values = pd.to_numeric(df.iloc[:, 0], errors="coerce")
    if values.isna().any():
        return df, headers, None
    numbers = values.to_numpy(dtype=np.float64)
    start = numbers[0]
    if start not in (0.0, 1.0) or not np.array_equal(numbers, start + np.arange(len(numbers))):
        return df, headers, None
    return df.iloc[:, 1:], headers[1:], [str(int(value)) for value in numbers]


def _numeric_ratio(values: pd.Series) -> float:
    if len(values) == 0:
        return 0.0
    parsed = pd.to_numeric(values, errors="coerce")
    return float(parsed.notna().sum() / len(parsed))


def _is_monotonic_numeric(values: pd.Series) -> bool:
    parsed = pd.to_numeric(values, errors="coerce").dropna().to_numpy(dtype=np.float64)
    if parsed.size < 2:
        return False
    diffs = np.diff(parsed)
    return bool(np.all(diffs > 0) or np.all(diffs < 0))


def _is_numeric_header(name: str) -> bool:
    try:
        float(re.sub(r"\.\d+$", "", name))
    except (TypeError, ValueError):
        return False
    return True


def _csv_data_row_count(
    filepath: Path,
    fallback: int,
    *,
    delimiter: str = ",",
    decimal: str = ".",
    header: int | None | str = "infer",
) -> int:
    """Count data rows without reading the full numeric matrix."""
    try:
        return int(pd.read_csv(filepath, sep=delimiter, decimal=decimal, header=header, usecols=[0]).shape[0])
    except Exception:
        return fallback


def _target_hint_from_header(name: str) -> bool:
    lower = name.lower()
    tokens = {
        "target",
        "class",
        "label",
        "species",
        "analyte",
        "concentration",
        "concentration_ppm",
        "conc",
        "ppm",
        "y",
    }
    return lower in tokens or any(token in lower for token in ("target", "class", "label", "species", "concentration"))


def _index_hint_from_header(name: str) -> bool:
    lower = name.lower().replace(" ", "_").replace("-", "_")
    return lower in {"i", "id", "idx", "index", "sample", "sample_id", "sample_name", "name", "file", "filename"}


def _inspect_csv_syntax(filepath: Path) -> tuple[str, str, str]:
    """Return delimiter, decimal mark, and recommended closed layout profile."""

    with filepath.open("r", encoding="utf-8-sig", newline="") as stream:
        sample = stream.read(64 * 1024)
    first_line = sample.splitlines()[0] if sample.splitlines() else ""
    if "\t" in first_line:
        delimiter = "\t"
    elif ";" in first_line:
        delimiter = ";"
    else:
        try:
            delimiter = csv.Sniffer().sniff(sample, delimiters=",").delimiter
        except csv.Error:
            delimiter = ","
    rows = list(csv.reader(sample.splitlines()[:8], delimiter=delimiter))

    def headerless(decimal: str) -> bool:
        probe = rows[:3]
        if len(probe) < 3 or any(len(row) != 2 for row in probe):
            return False
        try:
            coordinates = np.asarray([_csv_float(row[0], decimal=decimal) for row in probe])
            signals = np.asarray([_csv_signal_float(row[1], decimal=decimal) for row in probe])
        except (TypeError, ValueError):
            return False
        delta = np.diff(coordinates)
        return bool((np.all(delta > 0) or np.all(delta < 0)) and not np.any(np.isinf(signals)))

    decimal = "."
    if delimiter != ",":
        data_cells = [cell.strip() for row in rows[1:8] for cell in row]
        comma_numeric = sum(
            1
            for cell in data_cells
            if "," in cell and "." not in cell and re.fullmatch(r"[+-]?(?:\d+,\d*|,\d+)(?:[Ee][+-]?\d+)?", cell)
        )
        if comma_numeric >= max(2, len(data_cells) // 3):
            decimal = ","

    if headerless(decimal):
        layout = "headerless_two_column_spectrum"
        if decimal == ",":
            layout += "_decimal_comma"
        return delimiter, decimal, layout
    return delimiter, decimal, "headered_decimal_comma" if decimal == "," else "headered"


def inspect_csv_import_plan(filepath: Union[str, Path]) -> dict[str, Any]:
    """Return a lightweight, UI-facing CSV role inspection plan.

    This intentionally does not replace `load_csv_as_sherpa`.  It gives the
    Upload pane evidence for choosing the right import shape and target
    settings without trying to build a universal CSV parser.
    """
    filepath = resolve_existing_file_path(
        filepath,
        label="CSV",
        suffixes={".csv"},
        restrict_to_data_dir_in_multi_user=True,
    )
    path = Path(filepath)
    portable = read_portable_csv_envelope(path)
    if portable is not None:
        shape = portable.get("shape")
        feature_columns = portable.get("feature_columns")
        target_columns = portable.get("target_columns")
        metadata_columns = portable.get("sample_metadata_columns")
        if (
            not isinstance(shape, list)
            or len(shape) != 2
            or not all(type(value) is int and value > 0 for value in shape)
            or not isinstance(feature_columns, list)
            or len(feature_columns) != shape[1]
            or not isinstance(target_columns, list)
            or not isinstance(metadata_columns, list)
        ):
            raise ValueError("portable CSV metadata dimensions are malformed")
        target_names = [item.get("name") for item in target_columns if isinstance(item, dict)]
        target_types = {item.get("target_type") for item in target_columns if isinstance(item, dict)}
        axis_wire = portable.get("feature_axis")
        return {
            "layout": "spectrasherpa_portable_v2",
            "layout_label": "SpectraSherpa portable dataset",
            "recommended_layout": "headered",
            "layout_options": list(CSV_LAYOUT_OPTIONS),
            "requires_confirmation": False,
            "delimiter": "comma",
            "decimal": "point",
            "confidence": "high",
            "role_sequence": "I" + "F" * shape[1] + "T" * len(target_columns) + "M" * len(metadata_columns),
            "shape": {
                "rows": shape[0],
                "columns": 1 + shape[1] + len(target_columns) + len(metadata_columns),
                "samples": shape[0],
                "features": shape[1],
            },
            "axis": (
                None
                if not isinstance(axis_wire, dict)
                else {
                    "column": "portable metadata",
                    "title": axis_wire.get("title"),
                    "units": axis_wire.get("units"),
                }
            ),
            "target": {
                "column": target_names[0] if len(target_names) == 1 else None,
                "type": next(iter(target_types)) if len(target_types) == 1 else None,
                "candidates": target_names[:5],
            },
            "columns": [],
            "warnings": [],
        }
    delimiter, decimal, recommended_layout = _inspect_csv_syntax(path)
    raw_preview = pd.read_csv(path, sep=delimiter, decimal=decimal, header=None, nrows=100)
    if raw_preview.shape[1] >= 3:
        numeric = raw_preview.apply(pd.to_numeric, errors="coerce")
        first = numeric.iloc[:, 0].dropna().to_numpy(dtype=np.float64)
        delta = np.diff(first)
        all_numeric = bool(numeric.notna().to_numpy().all())
        monotonic_axis = first.size >= 3 and bool(np.all(delta > 0) or np.all(delta < 0))
        total_rows = _csv_data_row_count(
            path, len(raw_preview.index), delimiter=delimiter, decimal=decimal, header=None
        )
        if all_numeric and monotonic_axis and total_rows > raw_preview.shape[1]:
            recommended_layout = "headerless_axis_column_spectra"
            if decimal == ",":
                recommended_layout += "_decimal_comma"
            axis_title, axis_units = _infer_numeric_spectral_axis(path, first, None)
            return {
                "layout": "headerless_axis_column_spectra",
                "layout_label": "Unheaded axis column with sample spectra",
                "recommended_layout": recommended_layout,
                "layout_options": list(CSV_LAYOUT_OPTIONS),
                "requires_confirmation": True,
                "delimiter": {",": "comma", ";": "semicolon", "\t": "tab"}.get(delimiter, delimiter),
                "decimal": "comma" if decimal == "," else "point",
                "confidence": "high",
                "role_sequence": "W" + "F" * (raw_preview.shape[1] - 1),
                "shape": {
                    "rows": total_rows,
                    "columns": int(raw_preview.shape[1]),
                    "samples": int(raw_preview.shape[1] - 1),
                    "features": total_rows,
                },
                "axis": {"column": "column 1", "title": axis_title, "units": axis_units},
                "target": {"column": None, "type": None, "candidates": []},
                "columns": [],
                "warnings": [
                    "This headerless matrix stores samples in columns. Confirm the axis and transpose before commit."
                ],
            }
    if recommended_layout.startswith("headerless_two_column_spectrum"):
        df = pd.read_csv(path, sep=delimiter, decimal=decimal, header=None, nrows=100)
        preview_rows = int(len(df.index))
        total_rows = _csv_data_row_count(
            path,
            preview_rows,
            delimiter=delimiter,
            decimal=decimal,
            header=None,
        )
        return {
            "layout": "headerless_two_column_spectrum",
            "layout_label": "Unheaded coordinate/intensity spectrum",
            "recommended_layout": recommended_layout,
            "layout_options": list(CSV_LAYOUT_OPTIONS),
            "requires_confirmation": True,
            "delimiter": {",": "comma", ";": "semicolon", "\t": "tab"}.get(delimiter, delimiter),
            "decimal": "comma" if decimal == "," else "point",
            "confidence": "high",
            "role_sequence": "WY",
            "shape": {"rows": total_rows, "columns": 2, "samples": 1, "features": total_rows},
            "axis": {"column": "column 1", "title": None, "units": None},
            "target": {"column": None, "type": None, "candidates": []},
            "columns": [
                {"name": "column 1", "role": "W", "numeric_pct": 100.0, "reason": "monotonic coordinate"},
                {"name": "column 2", "role": "F", "numeric_pct": 100.0, "reason": "intensity value"},
            ],
            "warnings": [
                "This file has no header. Review and preserve the coordinate/intensity interpretation before commit."
            ],
        }

    df = pd.read_csv(path, sep=delimiter, decimal=decimal, nrows=100)
    preview_rows = int(len(df.index))
    total_rows = _csv_data_row_count(path, preview_rows, delimiter=delimiter, decimal=decimal)
    if df.empty:
        return {
            "layout": "empty",
            "layout_label": "Empty CSV",
            "recommended_layout": recommended_layout,
            "layout_options": list(CSV_LAYOUT_OPTIONS),
            "requires_confirmation": False,
            "delimiter": {",": "comma", ";": "semicolon", "\t": "tab"}.get(delimiter, delimiter),
            "decimal": "comma" if decimal == "," else "point",
            "confidence": "low",
            "role_sequence": "",
            "shape": {"rows": total_rows, "columns": int(len(df.columns)), "samples": None, "features": None},
            "axis": None,
            "target": {"column": None, "type": None, "candidates": []},
            "columns": [],
            "warnings": ["The CSV contains no preview rows."],
        }

    columns: list[dict[str, Any]] = []
    target_candidates: list[str] = []
    clean_to_raw: dict[str, Any] = {}
    axis: dict[str, Any] | None = None

    for idx, raw_name in enumerate(df.columns):
        name = _clean_csv_column_name(raw_name)
        clean_to_raw[name] = raw_name
        values = df[raw_name]
        numeric_ratio = _numeric_ratio(values)
        axis_info = _spectral_axis_info_from_header(name)
        reason = "numeric feature values"
        role = "F"

        if str(raw_name).startswith(SAMPLE_METADATA_CSV_PREFIX):
            role = "M"
            reason = "portable sample metadata"
        elif _is_empty_csv_column(name, values):
            role = "E"
            reason = "empty column"
        elif axis_info is not None and numeric_ratio >= 0.9 and _is_monotonic_numeric(values):
            role = "W"
            reason = "axis header with monotonic numeric values"
            if axis is None:
                axis = {
                    "column": name or str(raw_name),
                    "title": axis_info[0],
                    "units": axis_info[1],
                }
        elif idx == 0 and _index_hint_from_header(name):
            role = "I"
            reason = "sample or row identifier"
        elif _target_hint_from_header(name):
            role = "T"
            reason = "target-like column name"
            target_candidates.append(name)
        elif numeric_ratio < 0.8:
            unique_count = int(values.dropna().astype(str).nunique())
            if idx == 0 or _index_hint_from_header(name):
                role = "I"
                reason = "text identifier column"
            else:
                role = "T"
                reason = "non-numeric column"
                target_candidates.append(name)
                if unique_count > 20:
                    reason = "text column"
        columns.append(
            {
                "name": name or str(raw_name),
                "role": role,
                "numeric_pct": round(numeric_ratio * 100.0, 1),
                "reason": reason,
            }
        )

    non_empty_roles = [column["role"] for column in columns if column["role"] not in {"E", "M"}]
    role_sequence = "".join(non_empty_roles)
    warnings: list[str] = []
    layout = "feature_table"
    layout_label = "Feature table"
    confidence = "medium"
    samples: int | None = total_rows
    features: int | None = int(sum(1 for column in columns if column["role"] == "F"))

    if role_sequence.count("W") >= 2:
        layout = "alternating_axis_blocks"
        layout_label = "Alternating axis/value blocks"
        confidence = "low"
        warnings.append("Multiple axis-like columns were found; review the file before committing.")
    elif non_empty_roles[:1] == ["W"]:
        layout = "axis_column_spectra"
        layout_label = "Axis column with spectra columns"
        confidence = "high"
        samples = int(sum(1 for column in columns if column["role"] == "F"))
        features = total_rows
    elif non_empty_roles[:2] == ["I", "W"]:
        layout = "indexed_axis_column_spectra"
        layout_label = "Index plus axis column with spectra columns"
        confidence = "medium"
        samples = int(sum(1 for column in columns if column["role"] == "F"))
        features = total_rows
        warnings.append("The first column looks like an index before a shared spectral axis.")
    elif sum(_is_numeric_header(column["name"]) for column in columns) >= 2:
        layout = "sample_rows_spectral_matrix"
        layout_label = "Sample rows with spectral-variable columns"
        confidence = "high"
        axis_title = None
        axis_units = None
        if len(columns) > 1:
            values = np.array(
                [
                    float(re.sub(r"\.\d+$", "", column["name"]))
                    for column in columns
                    if _is_numeric_header(column["name"])
                ]
            )
            axis_title, axis_units = _infer_numeric_spectral_axis(filepath, values, None)
        axis = {"column": "column headers", "title": axis_title, "units": axis_units}
        features = int(sum(1 for column in columns if _is_numeric_header(column["name"])))
        # The canonical parser treats named columns beside numeric spectral
        # headers as properties, not X variables or an implicit response.
        for column in columns:
            if column["role"] in {"F", "T"} and not _is_numeric_header(column["name"]):
                column["role"] = "P"
                column["reason"] = "named reference property beside spectral columns"
        target_candidates = []
        role_sequence = "".join(column["role"] for column in columns if column["role"] != "E")
    elif target_candidates:
        layout = "feature_table_with_target"
        layout_label = "Feature table with target column"
        confidence = "medium"

    target_type: str | None = None
    target_column = target_candidates[0] if target_candidates else None
    raw_target_column = clean_to_raw.get(target_column) if target_column else None
    if raw_target_column is not None and raw_target_column in df.columns:
        series = df[raw_target_column]
        target_type = (
            "continuous" if _numeric_ratio(series) >= 0.9 and series.nunique(dropna=True) > 8 else "categorical"
        )

    return {
        "layout": layout,
        "layout_label": layout_label,
        "recommended_layout": recommended_layout,
        "layout_options": list(CSV_LAYOUT_OPTIONS),
        "requires_confirmation": confidence != "high",
        "delimiter": {",": "comma", ";": "semicolon", "\t": "tab"}.get(delimiter, delimiter),
        "decimal": "comma" if decimal == "," else "point",
        "confidence": confidence,
        "role_sequence": role_sequence,
        "shape": {
            "rows": total_rows,
            "columns": int(len(df.columns)),
            "samples": samples,
            "features": features,
        },
        "axis": axis,
        "target": {
            "column": target_column,
            "type": target_type,
            "candidates": target_candidates[:5],
        },
        "columns": columns[:24],
        "warnings": warnings,
    }


def _infer_numeric_spectral_axis(
    filepath: Union[str, Path],
    x_values: np.ndarray,
    overrides: Any | None,
) -> tuple[str | None, str | None]:
    """Infer metadata for matrix-style spectral CSVs with numeric column headers.

    Numeric headers alone cannot prove whether the axis is wavenumber, Raman
    shift, wavelength, or an arbitrary feature coordinate. Prefer explicit
    prepared-data metadata and otherwise leave quantity/units blank for user
    review in My Dataset.
    """
    if overrides is not None:
        override_title = getattr(overrides, "x_title", None)
        override_units = _normalize_axis_units(getattr(overrides, "x_units", None))
        if override_title or override_units:
            return override_title or None, override_units

    if Path(filepath).name.casefold() == "uvspectra10.csv":
        return "Wavelength", "nm"
    return None, None


def _load_axis_column_spectral_csv(
    df: pd.DataFrame,
    filepath: Union[str, Path],
    *,
    data_role: str | None = None,
) -> "SherpaDataset | None":
    """Load wide CSVs with one shared spectral axis column and condition columns.

    Example:
        Wavenumber (cm-1),Condition A,Condition B
        200,2139,9549
        201,2159,9538

    The scientist intent is two spectra sharing the same x-axis, not 1801
    samples with three generic features.
    """
    if len(df.columns) < 2:
        return None

    axis_col = df.columns[0]
    axis_info = _spectral_axis_info_from_header(str(axis_col))
    if axis_info is None:
        return None

    x_values = pd.to_numeric(df[axis_col], errors="coerce")
    if x_values.isna().any() or len(x_values) < 2:
        return None

    x_array = x_values.to_numpy(dtype=np.float64)
    diffs = np.diff(x_array)
    if not (bool(np.all(diffs > 0)) or bool(np.all(diffs < 0))):
        return None

    condition_cols = list(df.columns[1:])
    intensity_df = df[condition_cols].apply(pd.to_numeric, errors="coerce")
    if intensity_df.isna().any().any():
        return None

    from spectra_sherpa.app.lib.axes import SampleAxis, SpectralAxis
    from spectra_sherpa.app.lib.sherpa_dataset import DomainContext, SherpaDataset

    axis_title, units = axis_info
    path = Path(filepath)
    technique = "raman" if "raman" in path.stem.lower() or "raman" in str(axis_col).lower() else None

    return SherpaDataset(
        X=intensity_df.to_numpy(dtype=np.float64).T,
        feature_axis=SpectralAxis(values=x_array, title=axis_title, units=units),
        sample_axis=SampleAxis(labels=[str(col) for col in condition_cols], title="Condition"),
        domain=DomainContext(
            technique=technique,
            sample_type=path.stem,
            expected_units=units,
        ),
        extra={
            "csv.layout": "axis_column_conditions",
            "csv.axis_column": str(axis_col),
            "csv.condition_columns": [str(col) for col in condition_cols],
        },
        title=path.stem,
        data_role="X_spectra",
    )


def _normalise_label(value: str) -> str:
    """Normalize a species label."""
    cleaned = re.sub(r"[_\s]+", " ", value).strip()
    return cleaned.upper() if cleaned else value.upper()


def _extract_label_from_filename(filename: str) -> str:
    """Extract species label from filename."""
    stem = Path(filename).stem

    # Try pattern: PREFIX_SPECIES_SUFFIX_SUFFIX.csv
    first_sep = stem.find("_")
    second_last_sep = stem.rfind("_", 0, stem.rfind("_")) if stem.count("_") >= 2 else -1
    if first_sep != -1 and second_last_sep != -1 and second_last_sep > first_sep:
        candidate = stem[first_sep + 1 : second_last_sep]
        if candidate:
            return _normalise_label(candidate)

    parts = stem.split("_")
    if len(parts) >= 4:
        candidate_parts = parts[1:-2]
        candidate = " ".join(candidate_parts).strip()
        if candidate:
            return _normalise_label(candidate)

    match = FILENAME_PATTERN.match(filename)
    if match:
        return _normalise_label(match.group("label"))

    fallback = re.sub(r"[_\s]+", " ", stem).strip()
    return fallback.upper() if fallback else stem.upper()


def extract_concentration(filepath: Path) -> Optional[float]:
    """
    Extract concentration value from filename pattern like "(XXXppm)".

    Returns None if no pattern found.
    """
    match = CONC_PATTERN.search(filepath.name)
    if not match:
        return None
    try:
        raw_value = match.group(1).strip().replace("-", ".")
        return float(raw_value)
    except ValueError:
        return None


def extract_pathlength(filepath: Path) -> Optional[float]:
    """
    Extract pathlength from filename (second-to-last underscore segment).

    Returns pathlength in meters, or None if not found.
    """
    stem = filepath.stem
    parts = stem.split("_")
    if len(parts) < 2:
        return None

    segment = parts[-2]

    # Detect unit suffix
    unit_suffix = None
    if segment.endswith("cm") or segment.endswith("CM"):
        unit_suffix = "cm"
    elif segment.endswith("m") or segment.endswith("M"):
        unit_suffix = "m"

    # Strip letters and convert hyphen to decimal
    clean_segment = segment.rstrip("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ)").replace("-", ".").strip()

    try:
        value = float(clean_segment)
    except ValueError:
        return None

    # Convert to meters
    if unit_suffix == "cm":
        value = value / 100.0

    return value


# ─────────────────────────────────────────────────────────────────────────────
# CSV READING
# ─────────────────────────────────────────────────────────────────────────────


# ─────────────────────────────────────────────────────────────────────────────
# JSON SIGNATURE READING
# ─────────────────────────────────────────────────────────────────────────────


# ─────────────────────────────────────────────────────────────────────────────
# MATLAB .MAT READING
# ─────────────────────────────────────────────────────────────────────────────


# ─────────────────────────────────────────────────────────────────────────────
# CANONICAL NATIVE FORMAT PROJECTION
# ─────────────────────────────────────────────────────────────────────────────


def read_spectral_file(filepath: Path, *, asset_id: str | None = None) -> "SherpaDataset":
    """
    Read one vendor spectral asset through the frozen ingestion registry.

    Parameters
    ----------
    filepath : Path
        Path to spectral file

    Returns
    -------
    SherpaDataset
        One explicitly parsed asset. Multi-asset files require selection.
    """
    from spectra_sherpa.io import ingest, select_asset

    result = ingest(filepath)
    return select_asset(result, asset_id=asset_id).dataset


def load_open_spectral_file_as_sherpa(
    filepath: Union[str, Path],
    *,
    asset_id: str | None = None,
    prepared_overrides: Mapping[str, Any] | None = None,
) -> "SherpaDataset | None":
    """Load one base-install asset through the frozen ingestion registry."""
    from spectra_sherpa.io import builtin_registry, select_asset

    path = Path(filepath)
    ext = path.suffix.lower()
    native_extensions = {extension for plugin in builtin_registry.plugins for extension in plugin.extensions}
    if ext not in native_extensions and not builtin_registry.accepts_filename(path.name):
        return None
    from spectra_sherpa.core.prepared_data import parser_options_for_prepared_data

    result = builtin_registry.ingest(
        path,
        parser_options=parser_options_for_prepared_data(path.name, prepared_overrides),
    )
    selected = select_asset(result, asset_id=asset_id)
    return selected.dataset


# ─────────────────────────────────────────────────────────────────────────────
# UNIFIED LOADER
# ─────────────────────────────────────────────────────────────────────────────


def load_spectrum(filepath: Union[str, Path]) -> "SherpaDataset":
    """
    Load one asset through the sole structural ingestion dispatcher.

    Parameters
    ----------
    filepath : str or Path
        Path to spectrum file

    Returns
    -------
    SherpaDataset
        Loaded native dataset.
    """
    from spectra_sherpa.io import ingest

    filepath = Path(filepath)
    result = ingest(filepath)
    if len(result.assets) != 1:
        raise ValueError(
            f"{filepath.name} contains {len(result.assets)} assets; select an asset explicitly instead of flattening it"
        )
    return result.assets[0].dataset


# ─────────────────────────────────────────────────────────────────────────────
# CSV → SherpaDataset (handles matrix spectra + properties/tabular CSVs)
# ─────────────────────────────────────────────────────────────────────────────


def load_csv_as_sherpa(
    filepath: Union[str, Path],
    *,
    csv_layout: str | None = None,
    data_role: str | None = None,
    target_column: str | None = None,
    target_type: str | None = None,
    _infer_implicit_target: bool = True,
    _resolve_prepared_overrides: bool = True,
) -> "SherpaDataset":
    """Authorize one application-facing CSV path, then invoke the shared parser."""

    filepath = resolve_existing_file_path(
        filepath,
        label="CSV",
        suffixes={".csv"},
        restrict_to_data_dir_in_multi_user=True,
    )
    from spectra_sherpa.core.prepared_data import csv_layout_settings

    structural_layout, decimal = csv_layout_settings(csv_layout)
    detected_delimiter, _, _ = _inspect_csv_syntax(Path(filepath))
    return parse_csv_snapshot_as_sherpa(
        filepath,
        delimiter=detected_delimiter,
        csv_layout=None if structural_layout == "auto" else structural_layout,
        decimal=decimal,
        csv_profile=csv_layout,
        data_role=data_role,
        target_column=target_column,
        target_type=target_type,
        _infer_implicit_target=_infer_implicit_target,
        _resolve_prepared_overrides=_resolve_prepared_overrides,
    )


def _csv_float(value: str, *, decimal: str) -> float:
    text = str(value).strip()
    if decimal == ",":
        text = text.replace(",", ".")
    return float(text)


def _csv_signal_float(value: str, *, decimal: str) -> float:
    text = str(value).strip()
    if text.casefold() in {"#nan", "nan", "#n/a", "n/a", "na"}:
        return float("nan")
    return _csv_float(text, decimal=decimal)


def _looks_like_headerless_two_column_spectrum(
    filepath: Path,
    *,
    delimiter: str,
    decimal: str = ".",
) -> bool:
    """Return structural ambiguity evidence without choosing an interpretation."""
    with filepath.open("r", encoding="utf-8-sig", newline="") as stream:
        probe_rows: list[list[str]] = []
        for row in csv.reader(stream, delimiter=delimiter):
            probe_rows.append(row)
            if len(probe_rows) == 3:
                break
    if len(probe_rows) != 3 or any(len(row) != 2 for row in probe_rows):
        return False
    try:
        coordinate = np.asarray([_csv_float(row[0], decimal=decimal) for row in probe_rows])
        signal = np.asarray([_csv_signal_float(row[1], decimal=decimal) for row in probe_rows])
    except (TypeError, ValueError):
        return False
    delta = np.diff(coordinate)
    return bool((np.all(delta > 0) or np.all(delta < 0)) and not np.any(np.isinf(signal)))


def _load_headerless_two_column_spectrum(
    filepath: Path,
    *,
    delimiter: str,
    decimal: str,
    csv_profile: str | None,
    data_role: str | None,
    target_column: str | None,
    overrides: Any,
) -> "SherpaDataset | None":
    """Load a deterministic unheaded coordinate/intensity CSV variant."""
    from spectra_sherpa.app.lib.axes import SampleAxis, SpectralAxis
    from spectra_sherpa.app.lib.sherpa_dataset import DomainContext, SherpaDataset

    if target_column is not None or data_role == "X_features":
        raise ValueError("Headerless two-column spectrum layout cannot bind a tabular target or X_features role")
    if not _looks_like_headerless_two_column_spectrum(filepath, delimiter=delimiter, decimal=decimal):
        raise ValueError("Source does not satisfy the explicit headerless two-column spectrum layout")

    table = pd.read_csv(
        filepath,
        sep=delimiter,
        header=None,
        decimal=decimal,
        na_values=["#NaN", "#NAN", "NaN", "NAN", "#N/A", "N/A", "NA"],
        keep_default_na=True,
    )
    coordinate = table.iloc[:, 0].to_numpy(dtype=np.float64)
    intensity = table.iloc[:, 1].to_numpy(dtype=np.float64)
    delta = np.diff(coordinate)
    if not (
        np.all(np.isfinite(coordinate)) and not np.any(np.isinf(intensity)) and (np.all(delta > 0) or np.all(delta < 0))
    ):
        raise ValueError("Headerless two-column spectral coordinates must remain finite and strictly monotonic")
    axis_title, axis_units = _infer_numeric_spectral_axis(filepath, coordinate, overrides)
    return SherpaDataset(
        X=intensity.reshape(1, -1),
        feature_axis=SpectralAxis(values=coordinate, title=axis_title, units=axis_units),
        sample_axis=SampleAxis(labels=[filepath.stem], title="Samples"),
        domain=DomainContext(expected_units=axis_units),
        extra={
            "csv.layout": "headerless_two_column_spectrum",
            "csv.profile": csv_profile or "headerless_two_column_spectrum",
            "csv.delimiter": delimiter,
            "csv.decimal": decimal,
        },
        title=filepath.stem,
        data_role="X_spectra",
    )


def _load_headerless_axis_column_spectra(
    filepath: Path,
    *,
    delimiter: str,
    decimal: str,
    csv_profile: str | None,
    data_role: str | None,
    target_column: str | None,
    overrides: Any,
) -> "SherpaDataset":
    """Load an unheaded wavelength-row/sample-column spectral matrix."""
    from spectra_sherpa.app.lib.axes import SampleAxis, SpectralAxis
    from spectra_sherpa.app.lib.sherpa_dataset import DomainContext, SherpaDataset

    if target_column is not None or data_role == "X_features":
        raise ValueError("Headerless axis-column spectra cannot bind a tabular target or X_features role")
    table = pd.read_csv(
        filepath,
        sep=delimiter,
        header=None,
        decimal=decimal,
        na_values=["#NaN", "#NAN", "NaN", "NAN", "#N/A", "N/A", "NA"],
        keep_default_na=True,
    )
    if table.shape[0] < 2 or table.shape[1] < 3:
        raise ValueError("Headerless axis-column spectra require one coordinate and at least two sample columns")
    numeric = table.apply(pd.to_numeric, errors="coerce").to_numpy(dtype=np.float64)
    coordinate = numeric[:, 0]
    intensities = numeric[:, 1:]
    delta = np.diff(coordinate)
    if not np.all(np.isfinite(coordinate)) or not (np.all(delta > 0) or np.all(delta < 0)):
        raise ValueError("Headerless axis-column spectral coordinates must be finite and strictly monotonic")
    if np.any(np.isinf(intensities)):
        raise ValueError("Headerless axis-column spectra cannot contain infinite intensities")
    axis_title, axis_units = _infer_numeric_spectral_axis(filepath, coordinate, overrides)
    sample_labels = [f"{filepath.stem}-{index + 1}" for index in range(intensities.shape[1])]
    return SherpaDataset(
        X=intensities.T,
        feature_axis=SpectralAxis(values=coordinate, title=axis_title, units=axis_units),
        sample_axis=SampleAxis(labels=sample_labels, title="Samples"),
        domain=DomainContext(expected_units=axis_units),
        extra={
            "csv.layout": "headerless_axis_column_spectra",
            "csv.profile": csv_profile or "headerless_axis_column_spectra",
            "csv.delimiter": delimiter,
            "csv.decimal": decimal,
            "csv.source_orientation": "feature_rows_sample_columns",
        },
        title=filepath.stem,
        data_role="X_spectra",
    )


def _portable_axis_label(axis: Any, index: int, prefix: str) -> str:
    labels = getattr(axis, "labels", None) if axis is not None else None
    if labels is not None and labels[index]:
        return str(labels[index])
    values = getattr(axis, "values", None) if axis is not None else None
    if values is not None:
        return format(float(values[index]), ".17g")
    return f"{prefix}_{index + 1}"


def _portable_cell_text(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, np.generic):
        value = value.item()
    return str(value)


def _portable_target(
    metadata: Mapping[str, Any],
    frame: pd.DataFrame,
    target_columns: list[dict[str, str]],
) -> tuple[np.ndarray | None, Any]:
    from spectra_sherpa.app.lib.sherpa_dataset import TargetContext

    target_context_value = metadata.get("target_context")
    if not isinstance(target_context_value, Mapping):
        raise ValueError("portable CSV target context is malformed")
    target_context = TargetContext.model_validate(dict(target_context_value))
    if not target_columns:
        if any(
            value is not None
            for value in (
                target_context.target_type,
                target_context.target_name,
                target_context.target_names,
                target_context.selected_target,
            )
        ):
            raise ValueError("portable CSV target context declares absent target columns")
        return None, target_context

    target_types = {item["target_type"] for item in target_columns}
    target_names = [item["name"] for item in target_columns]
    if len(target_types) != 1 or target_types - {"continuous", "categorical"}:
        raise ValueError("portable CSV target type is malformed")
    target_type = next(iter(target_types))
    context_names = list(target_context.target_names or [])
    if not context_names and len(target_names) == 1 and target_context.target_name is not None:
        context_names = [target_context.target_name]
    if target_context.target_type != target_type or context_names != target_names:
        raise ValueError("portable CSV target columns contradict the target context")
    target_frame = frame[[item["transport"] for item in target_columns]]
    if target_type == "continuous":
        try:
            target = target_frame.map(lambda value: float(value)).to_numpy(dtype=np.float64)
        except (TypeError, ValueError) as exc:
            raise ValueError("portable CSV continuous target cells must be finite numeric values") from exc
        if not np.all(np.isfinite(target)):
            raise ValueError("portable CSV continuous target cells must be finite numeric values")
    else:
        target = target_frame.to_numpy(dtype=str)
        if np.any(target == ""):
            raise ValueError("portable CSV categorical target cells must be non-empty text")
    if target.shape[1] == 1:
        target = target[:, 0]
    return target, target_context


def _load_portable_csv_dataset(
    filepath: Path,
    metadata: Mapping[str, Any],
    *,
    delimiter: str,
    decimal: str,
) -> "SherpaDataset":
    """Load one Sherpa-issued CSV using its closed identity envelope."""

    from spectra_sherpa.app.lib.axes import FeatureAxis, SampleAxis
    from spectra_sherpa.app.lib.sherpa_dataset import (
        DomainContext,
        SherpaDataset,
        axis_from_wire,
    )

    if delimiter != "," or decimal != ".":
        raise ValueError("portable CSV v2 requires comma delimiters and decimal-point values")
    shape = metadata.get("shape")
    if not isinstance(shape, list) or len(shape) != 2 or not all(type(value) is int and value > 0 for value in shape):
        raise ValueError("portable CSV metadata dimensions are malformed")
    n_samples, n_features = shape

    feature_columns = metadata.get("feature_columns")
    target_columns = metadata.get("target_columns")
    sample_metadata_columns = metadata.get("sample_metadata_columns")
    if (
        not isinstance(feature_columns, list)
        or len(feature_columns) != n_features
        or any(not isinstance(value, str) or not value for value in feature_columns)
        or not isinstance(target_columns, list)
        or not isinstance(sample_metadata_columns, list)
    ):
        raise ValueError("portable CSV column metadata is malformed")
    for item, fields in (
        *((item, {"transport", "name", "target_type"}) for item in target_columns),
        *((item, {"transport", "name"}) for item in sample_metadata_columns),
    ):
        if (
            not isinstance(item, dict)
            or set(item) != fields
            or any(not isinstance(item[field], str) or not item[field] for field in fields)
        ):
            raise ValueError("portable CSV column metadata is malformed")
    target_transport = [item["transport"] for item in target_columns]
    metadata_transport = [item["transport"] for item in sample_metadata_columns]
    expected_headers = ["sample", *feature_columns, *target_transport, *metadata_transport]
    if len(expected_headers) != len(set(expected_headers)):
        raise ValueError("portable CSV transport columns must be unique")

    with filepath.open("r", encoding="utf-8-sig", newline="") as stream:
        stream.readline()
        reader = csv.reader(stream, delimiter=delimiter)
        raw_headers = next(reader, None)
    if raw_headers != expected_headers:
        raise ValueError("portable CSV header contradicts its metadata envelope")
    frame = pd.read_csv(filepath, sep=delimiter, skiprows=1, dtype=str, keep_default_na=False)
    if list(frame.columns) != expected_headers or frame.shape[0] != n_samples:
        raise ValueError("portable CSV table shape contradicts its metadata envelope")

    try:
        data = frame[feature_columns].map(lambda value: float(value)).to_numpy(dtype=np.float64)
    except (TypeError, ValueError) as exc:
        raise ValueError("portable CSV feature cells must be finite numeric values") from exc
    if data.shape != (n_samples, n_features) or not np.all(np.isfinite(data)):
        raise ValueError("portable CSV feature cells must be finite numeric values")

    feature_wire = metadata.get("feature_axis")
    feature_axis = axis_from_wire(feature_wire) if isinstance(feature_wire, Mapping) else None
    if feature_axis is not None and not isinstance(feature_axis, FeatureAxis):
        raise ValueError("portable CSV feature axis must be a typed feature axis")
    sample_wire = metadata.get("sample_axis")
    sample_axis = axis_from_wire(sample_wire) if isinstance(sample_wire, Mapping) else None
    if sample_axis is not None and not isinstance(sample_axis, SampleAxis):
        raise ValueError("portable CSV sample axis must be a typed sample axis")
    expected_samples = (
        [f"sample_{index + 1}" for index in range(n_samples)]
        if sample_axis is None
        else [_portable_axis_label(sample_axis, index, "sample") for index in range(n_samples)]
    )
    if frame["sample"].tolist() != expected_samples:
        raise ValueError("portable CSV sample identity contradicts its metadata envelope")

    table = {} if sample_axis is None else sample_axis.sample_table or {}
    declared_metadata_names = [item["name"] for item in sample_metadata_columns]
    if set(table) != set(declared_metadata_names):
        raise ValueError("portable CSV sample metadata contradicts its typed sample axis")
    for item in sample_metadata_columns:
        expected = [_portable_cell_text(value) for value in table[item["name"]]]
        if frame[item["transport"]].tolist() != expected:
            raise ValueError("portable CSV sample metadata cells contradict the metadata envelope")

    target, target_context = _portable_target(metadata, frame, target_columns)

    dataset_value = metadata.get("dataset")
    if not isinstance(dataset_value, dict) or set(dataset_value) != {"title", "units", "data_role", "domain"}:
        raise ValueError("portable CSV dataset metadata is malformed")
    if not isinstance(dataset_value["domain"], Mapping):
        raise ValueError("portable CSV domain metadata is malformed")
    return SherpaDataset(
        X=data,
        feature_axis=feature_axis,
        sample_axis=sample_axis,
        target=target,
        target_context=target_context,
        domain=DomainContext.model_validate(dict(dataset_value["domain"])),
        title=dataset_value["title"],
        units=dataset_value["units"],
        data_role=dataset_value["data_role"],
        extra={"csv.layout": "spectrasherpa_portable_v2"},
    )


def parse_csv_snapshot_as_sherpa(
    filepath: Union[str, Path],
    *,
    delimiter: str = ",",
    csv_layout: str | None = None,
    decimal: str = ".",
    csv_profile: str | None = None,
    data_role: str | None = None,
    target_column: str | None = None,
    target_type: str | None = None,
    _infer_implicit_target: bool = True,
    _resolve_prepared_overrides: bool = False,
) -> "SherpaDataset":
    """Parse an admitted CSV snapshot, including the canonical portable wire."""

    path = Path(filepath)
    portable_metadata = read_portable_csv_envelope(path)
    if portable_metadata is not None:
        if csv_layout not in {None, "headered"}:
            raise ValueError("portable CSV metadata cannot be combined with a headerless layout")
        return _load_portable_csv_dataset(path, portable_metadata, delimiter=delimiter, decimal=decimal)
    return _parse_legacy_csv_snapshot_as_sherpa(
        path,
        delimiter=delimiter,
        csv_layout=csv_layout,
        decimal=decimal,
        csv_profile=csv_profile,
        data_role=data_role,
        target_column=target_column,
        target_type=target_type,
        _infer_implicit_target=_infer_implicit_target,
        _resolve_prepared_overrides=_resolve_prepared_overrides,
    )


def _parse_legacy_csv_snapshot_as_sherpa(
    filepath: Union[str, Path],
    *,
    delimiter: str = ",",
    csv_layout: str | None = None,
    decimal: str = ".",
    csv_profile: str | None = None,
    data_role: str | None = None,
    target_column: str | None = None,
    target_type: str | None = None,
    _infer_implicit_target: bool = True,
    _resolve_prepared_overrides: bool = False,
) -> "SherpaDataset":
    """Parse an already-admitted immutable CSV snapshot.

    Handles two layouts:
    1. **Spectral matrix** — float-parseable column headers are x-axis values
       (wavelengths/wavenumbers), rows are samples.  String-named columns
       (e.g. ``sample_id``) become sample labels.
    2. **Tabular / properties** — all column headers are strings.  Numeric
       columns become features with string labels on the feature axis.

    Parameters
    ----------
    This function owns no filesystem authorization decision. Public application
    paths call :func:`load_csv_as_sherpa`; the native registry calls this parser
    only with the private snapshot produced by ``BoundedSource``.

    Returns
    -------
    SherpaDataset
    """
    from spectra_sherpa.app.lib.axes import FeatureAxis, SampleAxis, SpectralAxis
    from spectra_sherpa.app.lib.sherpa_dataset import DomainContext, SherpaDataset, TargetContext

    if decimal not in {".", ","}:
        raise ValueError("CSV decimal mark must be '.' or ','")

    filepath = Path(filepath)
    overrides = None
    if _resolve_prepared_overrides:
        try:
            from spectra_sherpa.app.services.prepared_data import load_prepared_data_overrides

            overrides = load_prepared_data_overrides(file_path=str(filepath))
            data_role = data_role or overrides.data_role
            target_column = target_column or overrides.target_column
            target_type = target_type or overrides.target_type
            if csv_profile is None and overrides.csv_layout is not None:
                from spectra_sherpa.core.prepared_data import csv_layout_settings

                csv_profile = overrides.csv_layout
                resolved_layout, decimal = csv_layout_settings(overrides.csv_layout)
                csv_layout = None if resolved_layout == "auto" else resolved_layout
        except Exception:
            # CSV loading is used in lightweight contexts where the application
            # settings module may not be fully initialised. Explicit arguments
            # still work in those contexts.
            pass

    if csv_layout == "headerless_two_column_spectrum":
        return _load_headerless_two_column_spectrum(
            filepath,
            delimiter=delimiter,
            decimal=decimal,
            csv_profile=csv_profile,
            data_role=data_role,
            target_column=target_column,
            overrides=overrides,
        )
    if csv_layout == "headerless_axis_column_spectra":
        return _load_headerless_axis_column_spectra(
            filepath,
            delimiter=delimiter,
            decimal=decimal,
            csv_profile=csv_profile,
            data_role=data_role,
            target_column=target_column,
            overrides=overrides,
        )
    if csv_layout not in {None, "headered"}:
        raise ValueError(f"Unsupported CSV layout: {csv_layout!r}")
    if csv_layout is None and _looks_like_headerless_two_column_spectrum(
        filepath,
        delimiter=delimiter,
        decimal=decimal,
    ):
        from spectra_sherpa.ingestion_errors import AmbiguousFormatError

        raise AmbiguousFormatError(
            "Two-column numeric CSV is structurally ambiguous between a headered two-feature table and an "
            "unheaded coordinate/intensity spectrum; bind csv_layout explicitly"
        )

    df = pd.read_csv(filepath, sep=delimiter, decimal=decimal)
    with filepath.open("r", encoding="utf-8-sig", newline="") as stream:
        raw_headers = next(csv.reader(stream, delimiter=delimiter))
    if len(raw_headers) != df.shape[1]:
        raise ValueError("CSV header width does not match its data width")

    if df.empty:
        raise ValueError(f"Empty CSV file: {filepath}")

    sample_metadata_columns = {
        str(column): str(column)[len(SAMPLE_METADATA_CSV_PREFIX) :]
        for column in df.columns
        if str(column).startswith(SAMPLE_METADATA_CSV_PREFIX)
    }
    if any(not name for name in sample_metadata_columns.values()) or len(set(sample_metadata_columns.values())) != len(
        sample_metadata_columns
    ):
        raise ValueError("Portable CSV sample metadata columns must have unique non-empty names")
    sample_metadata = {
        name: df[column].where(pd.notna(df[column]), None).tolist() for column, name in sample_metadata_columns.items()
    }
    if sample_metadata_columns:
        df = df.drop(columns=list(sample_metadata_columns))
    active_raw_headers = [header for header in raw_headers if not str(header).startswith(SAMPLE_METADATA_CSV_PREFIX)]
    if len(active_raw_headers) != df.shape[1]:
        raise ValueError("CSV declared headers do not align with the parsed columns")
    df, active_raw_headers, row_index_labels = _split_row_index_column(df, active_raw_headers)

    axis_column_dataset = _load_axis_column_spectral_csv(df, filepath, data_role=data_role)
    if axis_column_dataset is not None:
        if sample_metadata:
            raise ValueError("Portable sample metadata is not admitted by axis-column spectral CSV layout")
        if overrides is not None:
            from spectra_sherpa.app.services.prepared_data import apply_dataset_prepared_data_overrides

            axis_column_dataset = apply_dataset_prepared_data_overrides(axis_column_dataset, overrides)
        return axis_column_dataset

    # Partition columns from the source-declared header, never from pandas'
    # duplicate-name mangling (which can turn a repeated `100` into `100.1`).
    spectral_cols: list[str] = []
    x_vals: list[float] = []
    label_cols: list[str] = []

    for col, declared_header in zip(df.columns, active_raw_headers, strict=True):
        try:
            x_vals.append(float(declared_header))
            spectral_cols.append(col)
        except (ValueError, TypeError):
            label_cols.append(col)

    if data_role == "X_features":
        spectral_cols = []
        x_vals = []
        label_cols = list(df.columns)

    # Sample identity is semantic, not positional. Arbitrary named columns may
    # be quantitative properties or categorical targets, so never consume the
    # first one merely because it is not a spectral-coordinate header.
    sample_labels: list[str] | None = row_index_labels
    sample_label_column = next(
        (
            column
            for column in label_cols
            if str(column).strip().casefold().replace(" ", "_") in {"sample", "sample_id", "sampleid"}
        ),
        None,
    )
    if sample_label_column is not None:
        sample_labels = df[sample_label_column].astype(str).tolist()

    title = filepath.stem

    if spectral_cols:
        declared = np.asarray(x_vals, dtype=np.float64)
        declared_delta = np.diff(declared)
        declared_is_monotonic = (
            len(declared) < 2 or bool(np.all(declared_delta > 0)) or bool(np.all(declared_delta < 0))
        )
        if not declared_is_monotonic:
            # Numeric labels that repeat or reverse are not a spectral axis.
            # Preserve their exact declared identity as generic features; do
            # not fabricate coordinates merely to satisfy plotting software.
            raw_labels = active_raw_headers
            if label_cols:
                raise ValueError(
                    "Numeric CSV coordinate headers must be finite, unique, and strictly monotonic; "
                    "mixed labeled columns cannot be reinterpreted safely"
                )
            data = df.to_numpy(dtype=np.float64)
            return SherpaDataset(
                X=data,
                feature_axis=FeatureAxis(labels=raw_labels, title="Declared feature"),
                sample_axis=SampleAxis(values=np.arange(data.shape[0], dtype=np.float64), title="Sample"),
                domain=DomainContext(technique="generic", sample_type=title),
                extra={"csv.feature_names": raw_labels, "csv.layout": "numeric_labeled_feature_table"},
                backend="pandas",
                title=title,
                data_role="X_features",
            )
        # ── Spectral matrix path ──
        data = df[spectral_cols].values.astype(np.float64)
        wavelengths = np.array(x_vals, dtype=np.float64)
        axis_title, axis_units = _infer_numeric_spectral_axis(filepath, wavelengths, overrides)

        # Preserve every non-spectral, non-identity column as an explicitly
        # named property. Target selection happens later and never changes the
        # parser's interpretation of the bytes.
        extra: dict[str, Any] | None = None
        prop_label_cols = [column for column in label_cols if column != sample_label_column]
        if prop_label_cols:
            extra = {
                "prop_names": prop_label_cols,
                "properties": {column: df[column].tolist() for column in prop_label_cols},
            }

        target = None
        target_context = None
        if target_column is not None:
            if target_column not in df.columns:
                raise ValueError(f"Target column {target_column!r} is not present in {filepath.name}")
            target = df[target_column].to_numpy()
            target_is_categorical = target_type == "categorical" or target.dtype.kind in ("O", "S", "U")
            class_names = _categorical_class_names(target) if target_is_categorical else None
            target_context = TargetContext(
                target_type="categorical" if target_is_categorical else "continuous",
                target_name=target_column,
                target_names=[target_column],
                selected_target=target_column,
                n_classes=len(class_names) if class_names is not None else None,
                class_names=class_names,
            )

        return SherpaDataset(
            X=data,
            feature_axis=SpectralAxis(values=wavelengths, title=axis_title, units=axis_units),
            # Header-only matrices still have a governed sample axis: rows are
            # ordered observations even without a source-provided name column.
            # Preserve positional identity so collection admission receives
            # both typed axes instead of failing after a successful preview.
            sample_axis=SampleAxis(
                labels=sample_labels,
                values=None if sample_labels is not None else np.arange(data.shape[0], dtype=np.float64),
                sample_table=sample_metadata or None,
                title="Sample",
            ),
            target=target,
            target_context=target_context,
            domain=DomainContext(expected_units=axis_units),
            extra=extra,
            title=title,
            data_role="X_spectra",
        )

    # ── Tabular / properties path ──
    # Named-column tables are generic multivariate data, not spectra.
    # Preserve numeric columns as features and keep a single non-numeric
    # column as an embedded categorical target when present.
    target_col = target_column if target_column in df.columns else None
    numeric_cols = [c for c in df.columns if pd.api.types.is_numeric_dtype(df[c]) and c != target_col]
    numeric_df = df[numeric_cols]
    if numeric_df.empty:
        raise ValueError(f"No numeric columns in {filepath.name}")

    data = numeric_df.values.astype(np.float64)
    col_names = list(numeric_df.columns)
    non_numeric_cols = [
        column
        for column in df.columns
        if not pd.api.types.is_numeric_dtype(df[column]) and column != target_col and column != sample_label_column
    ]

    target = None
    target_context = None
    extra2: dict[str, Any] = {
        "csv.feature_names": col_names,
    }

    inferred_target_col = target_col or (
        non_numeric_cols[0] if _infer_implicit_target and len(non_numeric_cols) == 1 else None
    )
    if inferred_target_col is not None:
        target = df[inferred_target_col].to_numpy()
        target_is_categorical = (
            target_type == "categorical"
            or target.dtype.kind in ("O", "S", "U")
            or (target_type is None and np.issubdtype(target.dtype, np.integer) and len(np.unique(target)) <= 30)
        )
        class_names = _categorical_class_names(target) if target_is_categorical else None
        target_context = TargetContext(
            target_type="categorical" if target_is_categorical else "continuous",
            target_name=inferred_target_col,
            # The GUI target picker is driven by target_names. Keep the
            # declared response visible for tabular reference imports just as
            # it is for spectral and portable-table readers.
            target_names=[inferred_target_col],
            selected_target=inferred_target_col,
            n_classes=len(class_names) if class_names is not None else None,
            class_names=class_names,
        )
        extra2["csv.target_column"] = inferred_target_col
        extra2["csv.target_type"] = "categorical" if target_is_categorical else "continuous"
    remaining_properties = [column for column in non_numeric_cols if column != inferred_target_col]
    if remaining_properties:
        extra2["prop_names"] = remaining_properties
        extra2["properties"] = {column: df[column].tolist() for column in remaining_properties}

    return SherpaDataset(
        X=data,
        feature_axis=FeatureAxis(labels=col_names, title="Property"),
        sample_axis=SampleAxis(
            values=np.arange(data.shape[0], dtype=np.float64),
            labels=sample_labels,
            sample_table=sample_metadata or None,
            title="Sample",
        ),
        target=target,
        target_context=target_context,
        domain=DomainContext(
            technique="generic",
            sample_type=title,
        ),
        extra=extra2,
        backend="pandas",
        title=title,
        data_role="X_features",
    )


def load_canonical_file_as_sherpa(
    filepath: Union[str, Path],
    *,
    asset_id: str | None = None,
    selected_target: str | None = None,
    target_type: str | None = None,
    prepared_overrides: Mapping[str, Any] | None = None,
) -> "SherpaDataset":
    """Load one canonical portable file under the DAG source contract.

    The same dispatcher is used by live execution and exported OSS code.  A
    named target is an explicit part of the saved scientific procedure; the
    reader never chooses one property from a multi-response dataset.
    """
    from spectra_sherpa.app.lib.sherpa_dataset import SherpaDataset
    from spectra_sherpa.io import builtin_registry

    path = Path(filepath)
    extension = path.suffix.lower()
    if not builtin_registry.accepts_filename(path.name):
        supported = ", ".join(builtin_registry.capability_report()["acceptedExtensions"])
        raise ValueError(
            f"Canonical data.file_load does not admit {extension or 'extensionless'} files. "
            f"Supported native formats: {supported}."
        )

    dataset = load_open_spectral_file_as_sherpa(
        path,
        asset_id=asset_id,
        prepared_overrides=prepared_overrides,
    )
    if not isinstance(dataset, SherpaDataset):
        raise ValueError(f"Canonical reader is unavailable for admitted file format: {extension}")
    return select_dataset_target(
        dataset,
        selected_target=selected_target,
        target_type=target_type,
        source_name=path.name,
    )


def select_dataset_target(
    dataset: "SherpaDataset",
    *,
    selected_target: str | None,
    target_type: str | None = None,
    source_name: str = "dataset",
) -> "SherpaDataset":
    """Project one named response from an already-admitted dataset snapshot.

    This is the sole target-selection authority shared by ordinary file reads
    and server-preloaded trial sources.  It never reopens or reparses source
    bytes, so access admission and DAG execution consume the same snapshot.
    """
    from spectra_sherpa.app.lib.sherpa_dataset import TargetContext

    if selected_target is None:
        return dataset

    context = dataset.target_context
    names = list(context.target_names or []) if context is not None else []
    target = np.asarray(dataset.target) if dataset.target is not None else None
    resolved_target_type = target_type
    if resolved_target_type is not None and resolved_target_type not in {"continuous", "categorical"}:
        raise ValueError("target_type must be continuous or categorical")
    if (
        resolved_target_type is not None
        and context is not None
        and context.target_type in {"continuous", "categorical"}
        and resolved_target_type != context.target_type
    ):
        raise ValueError("requested target type contradicts the admitted dataset target type")
    if context is not None and context.target_name == selected_target and target is not None:
        selected = target
        resolved_target_type = resolved_target_type or context.target_type
    elif names == [selected_target] and target is not None and target.ndim == 1:
        # Portable single-response targets retain their exact target_names list
        # while the sole numeric column is represented as a vector.
        selected = target
        resolved_target_type = resolved_target_type or (context.target_type if context is not None else None)
    elif selected_target in names and target is not None and target.ndim == 2:
        selected = target[:, names.index(selected_target)]
        resolved_target_type = resolved_target_type or (context.target_type if context is not None else None)
    else:
        properties = dataset.get_extra("properties")
        if isinstance(properties, dict) and selected_target in properties:
            # Preserve missing categorical cells as real missing values.  A
            # mixed Python list such as ["control", NaN, "treated"] would
            # otherwise be coerced by NumPy to Unicode and turn NaN into the
            # scientifically false class label "nan".
            property_values = pd.Series(properties[selected_target])
            if resolved_target_type is None:
                resolved_target_type = "continuous" if pd.api.types.is_numeric_dtype(property_values) else "categorical"
            selected = property_values.to_numpy(dtype=object if resolved_target_type == "categorical" else None)
        else:
            feature_axis = dataset.get_feature_axis()
            feature_labels = list(feature_axis.labels or []) if feature_axis is not None else []
            if selected_target not in feature_labels:
                raise ValueError(f"Target column {selected_target!r} is not present in {source_name}")
            target_index = feature_labels.index(selected_target)
            selected = np.asarray(dataset.X)[:, target_index]
            keep = np.ones(dataset.n_features, dtype=bool)
            keep[target_index] = False
            dataset = dataset[:, keep]
            resolved_target_type = resolved_target_type or "continuous"

    if selected.ndim != 1 or selected.shape[0] != dataset.n_samples:
        raise ValueError(f"Target {selected_target!r} is not a one-dimensional sample-aligned response")
    categorical = (
        resolved_target_type == "categorical"
        if resolved_target_type is not None
        else selected.dtype.kind in ("O", "S", "U")
    )
    if categorical:
        selected = np.asarray(
            [np.nan if pd.isna(value) else str(value) for value in np.asarray(selected, dtype=object)],
            dtype=object,
        )
    else:
        raw_values = pd.Series(np.asarray(selected, dtype=object))
        numeric_values = pd.to_numeric(raw_values, errors="coerce")
        invalid = numeric_values.isna() & ~raw_values.isna()
        if bool(invalid.any()):
            bad_value = raw_values[invalid].iloc[0]
            raise ValueError(
                f"Target {selected_target!r} is declared continuous but contains non-numeric value {bad_value!r}"
            )
        selected = numeric_values.to_numpy(dtype=np.float64)
    dataset.target = selected
    class_names = _categorical_class_names(selected) if categorical else None
    dataset.target_context = TargetContext(
        target_type="categorical" if categorical else "continuous",
        target_name=selected_target,
        target_names=[selected_target],
        target_units=context.target_units if context is not None else None,
        selected_target=selected_target,
        n_classes=len(class_names) if class_names is not None else None,
        class_names=class_names,
    )
    return dataset


__all__ = [
    "load_canonical_file_as_sherpa",
    "select_dataset_target",
    "read_spectral_file",
    "load_spectrum",
    "inspect_csv_import_plan",
    "load_csv_as_sherpa",
    "extract_concentration",
    "extract_pathlength",
]
