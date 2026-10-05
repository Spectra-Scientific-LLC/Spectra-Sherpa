"""Canonical, host-neutral dataset export artifacts.

The DAG owns serialization and evidence.  Browser, CLI, and generated-script
hosts own materialization.  Keeping those responsibilities separate means the
same bytes and digest cross every execution projection without granting a
scientific node an arbitrary filesystem path.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import re
from pathlib import Path
from typing import Any, Mapping

import numpy as np

from spectra_sherpa.app.lib.portable_csv import SAMPLE_METADATA_CSV_PREFIX, encode_portable_csv_envelope
from spectra_sherpa.app.lib.portable_json import encode_portable_json
from spectra_sherpa.app.lib.sherpa_dataset import SherpaDataset, axis_to_wire

EXPORT_ARTIFACT_SCHEMA = "spectrasherpa-export-artifact/1"
_MAX_EXPORT_BYTES = 32 * 1024 * 1024
_MAX_EXPORT_NUMERIC_ELEMENTS = 1_000_000
_FORMAT_SUFFIX = {"csv": ".csv", "json": ".json", "jdx": ".jdx"}
_FORMAT_MEDIA_TYPE = {
    "csv": "text/csv;charset=utf-8",
    "json": "application/json",
    "jdx": "chemical/x-jcamp-dx",
}
_ARTIFACT_FIELDS = frozenset(
    {
        "schema_version",
        "filename",
        "format",
        "media_type",
        "content_encoding",
        "content",
        "content_sha256",
        "byte_length",
        "source_digest",
        "shape",
    }
)
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_CSV_FORMULA_PREFIXES = ("=", "+", "-", "@")
_TABULAR_DATASET_SCHEMA = "spectrasherpa-tabular-dataset/2"


def _canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)


def _safe_filename(filename: object, fmt: str) -> str:
    if not isinstance(filename, str) or not filename or filename.strip() != filename:
        raise ValueError("export filename must be non-empty text without surrounding whitespace")
    if len(filename) > 128 or filename in {".", ".."}:
        raise ValueError("export filename is invalid")
    if Path(filename).name != filename or "/" in filename or "\\" in filename or "\x00" in filename:
        raise ValueError("export filename must be a basename without path separators")
    suffix = _FORMAT_SUFFIX[fmt]
    if Path(filename).suffix.lower() != suffix:
        raise ValueError(f"export filename for {fmt} must end with {suffix}")
    return filename


def canonicalize_export_parameters(raw: Mapping[str, object]) -> dict[str, str]:
    """Admit the complete format/filename pair before scientific execution."""

    fmt = raw.get("format")
    filename = raw.get("filename")
    if not isinstance(fmt, str) or fmt not in _FORMAT_SUFFIX:
        raise ValueError("export format must be one of csv, json, or jdx")
    return {"filename": _safe_filename(filename, fmt), "format": fmt}


def _finite_matrix(dataset: SherpaDataset) -> np.ndarray:
    matrix = np.asarray(dataset.data, dtype=np.float64)
    if matrix.ndim != 2 or matrix.shape[0] < 1 or matrix.shape[1] < 1:
        raise ValueError("output.export requires a non-empty two-dimensional dataset")
    if not np.all(np.isfinite(matrix)):
        raise ValueError("output.export rejects non-finite values")
    return matrix


def _axis_payload(axis: object, length: int) -> dict[str, object]:
    values = getattr(axis, "values", None) if axis is not None else None
    labels = getattr(axis, "labels", None) if axis is not None else None
    if values is not None and len(values) != length:
        raise ValueError("export axis value count does not match the dataset")
    if labels is not None and len(labels) != length:
        raise ValueError("export axis label count does not match the dataset")
    units = getattr(axis, "units", None) if axis is not None else None
    title = getattr(axis, "title", None) if axis is not None else None
    return {
        "values": None if values is None else np.asarray(values).tolist(),
        "labels": None if labels is None else [str(value) for value in labels],
        "units": None if units is None else str(units),
        "title": None if title is None else str(title),
    }


def _dataset_payload(dataset: SherpaDataset, matrix: np.ndarray) -> dict[str, object]:
    target = _target_payload(dataset, matrix.shape[0])
    sample_metadata = _sample_metadata_payload(dataset, matrix.shape[0])
    return {
        "schema_version": _TABULAR_DATASET_SCHEMA,
        "shape": [int(value) for value in matrix.shape],
        "data": matrix.tolist(),
        "feature_axis": _axis_payload(dataset.get_feature_axis(), matrix.shape[1]),
        "sample_axis": _axis_payload(dataset.sample_axis, matrix.shape[0]),
        "title": None if dataset.title is None else str(dataset.title),
        "units": None if dataset.units is None else str(dataset.units),
        "data_role": str(dataset.data_role),
        "target": target,
        "sample_metadata": sample_metadata,
        "feature_axis_wire": (None if dataset.get_feature_axis() is None else axis_to_wire(dataset.get_feature_axis())),
        "sample_axis_wire": (
            None if dataset.sample_axis is None else axis_to_wire(dataset.sample_axis, include_sample_table=True)
        ),
        "domain": dataset.domain.model_dump(mode="json", exclude_none=True),
        "target_context": dataset.target_context.model_dump(mode="json", exclude_none=True),
    }


def _json_cell(value: object, *, field: str) -> str | int | float | bool | None:
    if isinstance(value, np.generic):
        value = value.item()
    if value is None or isinstance(value, (str, int, bool)):
        return value
    if isinstance(value, float):
        if not np.isfinite(value):
            raise ValueError(f"output.export rejects non-finite {field} values")
        return value
    raise ValueError(f"output.export requires scalar {field} values")


def _safe_csv_text(value: object, *, field: str) -> str:
    text = str(value)
    if any(ord(character) < 32 or ord(character) == 127 for character in text):
        raise ValueError(f"CSV export rejects control characters in {field}")
    if text.lstrip().startswith(_CSV_FORMULA_PREFIXES):
        raise ValueError(f"CSV export rejects formula-like {field}")
    return text


def _target_payload(dataset: SherpaDataset, n_samples: int) -> dict[str, object] | None:
    if dataset.target is None:
        return None
    values = np.asarray(dataset.target)
    if values.ndim == 1:
        values = values[:, None]
    if values.ndim != 2 or values.shape[0] != n_samples or values.shape[1] < 1:
        raise ValueError("output.export CSV requires sample-aligned target columns")
    context = dataset.target_context
    names = list(context.target_names or [])
    if values.shape[1] == 1:
        name = context.selected_target or context.target_name or (names[0] if len(names) == 1 else None)
        names = [name] if name is not None else []
    if (
        len(names) != values.shape[1]
        or any(not isinstance(name, str) or not name.strip() for name in names)
        or len(set(names)) != len(names)
    ):
        raise ValueError("output.export requires one unique target name per target column")
    target_type = context.target_type
    if target_type not in {"continuous", "categorical"}:
        raise ValueError("output.export requires target_type continuous or categorical")
    exported_values = [
        [_json_cell(value, field=f"target {names[column_index]!r}") for column_index, value in enumerate(row)]
        for row in values.tolist()
    ]
    if target_type == "continuous" and any(
        isinstance(value, bool) or not isinstance(value, (int, float)) for row in exported_values for value in row
    ):
        raise ValueError("output.export continuous target values must be numeric")
    if target_type == "categorical":
        if any(not isinstance(value, str) or not value.strip() for row in exported_values for value in row):
            raise ValueError("output.export categorical target values must be non-empty text")
    return {"names": names, "target_type": target_type, "values": exported_values}


def _sample_metadata_payload(dataset: SherpaDataset, n_samples: int) -> dict[str, list[object]]:
    table = dataset.sample_axis.sample_table if dataset.sample_axis is not None else None
    if table is None:
        return {}
    result: dict[str, list[object]] = {}
    for raw_name, raw_values in sorted(table.items()):
        name = _safe_csv_text(raw_name, field="sample metadata column").strip()
        if not name or name in result:
            raise ValueError("output.export sample metadata column names must be non-empty and unique")
        if len(raw_values) != n_samples:
            raise ValueError(f"output.export sample metadata column {name!r} is not row-aligned")
        result[name] = [_json_cell(value, field=f"sample metadata {name!r}") for value in raw_values]
    return result


def _label(axis_payload: Mapping[str, object], index: int, prefix: str) -> str:
    labels = axis_payload["labels"]
    if isinstance(labels, list) and labels[index]:
        label = str(labels[index])
        if any(ord(character) < 32 or ord(character) == 127 for character in label):
            raise ValueError("CSV export rejects control characters in axis labels")
        if label.lstrip().startswith(_CSV_FORMULA_PREFIXES):
            raise ValueError("CSV export rejects formula-like axis labels")
        return label
    values = axis_payload["values"]
    if isinstance(values, list):
        return format(float(values[index]), ".17g")
    return f"{prefix}_{index + 1}"


def _csv_content(payload: Mapping[str, Any]) -> str:
    buffer = io.StringIO(newline="")
    writer = csv.writer(buffer, lineterminator="\n")
    feature_axis = payload["feature_axis"]
    sample_axis = payload["sample_axis"]
    n_samples, n_features = payload["shape"]
    feature_labels = [_label(feature_axis, index, "feature") for index in range(n_features)]
    target = payload["target"]
    target_names = [] if target is None else [_safe_csv_text(name, field="target name") for name in target["names"]]
    sample_metadata = payload["sample_metadata"]
    metadata_names = list(sample_metadata)
    metadata_headers = [f"{SAMPLE_METADATA_CSV_PREFIX}{name}" for name in metadata_names]
    proposed_headers = ["sample", *feature_labels, *target_names, *metadata_headers]
    headers: list[str] = []
    used: set[str] = set()
    for proposed in proposed_headers:
        header = proposed
        suffix = 2
        while header in used:
            header = f"{proposed} [{suffix}]"
            suffix += 1
        used.add(header)
        headers.append(header)
    feature_headers = headers[1 : 1 + n_features]
    target_headers = headers[1 + n_features : 1 + n_features + len(target_names)]
    metadata_transport_headers = headers[1 + n_features + len(target_names) :]
    envelope = {
        "shape": [n_samples, n_features],
        "feature_axis": payload["feature_axis_wire"],
        "sample_axis": payload["sample_axis_wire"],
        "dataset": {
            "title": payload["title"],
            "units": payload["units"],
            "data_role": payload["data_role"],
            "domain": payload["domain"],
        },
        "target_context": payload["target_context"],
        "feature_columns": feature_headers,
        "target_columns": [
            {"transport": transport, "name": name, "target_type": target["target_type"]}
            for transport, name in zip(target_headers, target_names, strict=True)
        ],
        "sample_metadata_columns": [
            {"transport": transport, "name": name}
            for transport, name in zip(metadata_transport_headers, metadata_names, strict=True)
        ],
    }
    buffer.write(encode_portable_csv_envelope(envelope) + "\n")
    writer.writerow(headers)
    for row_index in range(n_samples):
        row = payload["data"][row_index]
        exported_row: list[object] = [
            _label(sample_axis, row_index, "sample"),
            *[format(float(value), ".17g") for value in row],
        ]
        if target is not None:
            exported_row.extend(
                (
                    format(float(target_value), ".17g")
                    if target["target_type"] == "continuous"
                    else _safe_csv_text(target_value, field="categorical target")
                )
                for target_value in target["values"][row_index]
            )
        exported_row.extend(
            (
                _safe_csv_text(sample_metadata[name][row_index], field=f"sample metadata {name!r}")
                if isinstance(sample_metadata[name][row_index], str)
                else sample_metadata[name][row_index]
            )
            for name in metadata_names
        )
        writer.writerow(exported_row)
    return buffer.getvalue()


def _jdx_content(payload: Mapping[str, Any]) -> str:
    n_samples, n_features = payload["shape"]
    feature_axis = payload["feature_axis"]
    values = feature_axis["values"]
    units = feature_axis["units"]
    if n_samples != 1:
        raise ValueError("JCAMP-DX export requires exactly one spectrum")
    if not isinstance(values, list) or len(values) != n_features:
        raise ValueError("JCAMP-DX export requires a measured numeric feature axis")
    if not isinstance(units, str) or not units.strip():
        raise ValueError("JCAMP-DX export requires declared feature-axis units")
    title = payload["title"] if isinstance(payload["title"], str) and payload["title"] else "SpectraSherpa Export"
    y_units = payload["units"] if isinstance(payload["units"], str) and payload["units"] else "ARBITRARY UNITS"
    for field_name, header_value in (("title", title), ("x units", units), ("y units", y_units)):
        if len(header_value) > 256 or any(ord(character) < 32 or ord(character) == 127 for character in header_value):
            raise ValueError(f"JCAMP-DX export rejects invalid {field_name} header text")
    lines = [
        f"##TITLE={title}",
        "##JCAMP-DX=5.01",
        "##DATA TYPE=SPECTRUM",
        f"##XUNITS={units}",
        f"##YUNITS={y_units}",
        f"##NPOINTS={n_features}",
        "##XYPOINTS=(XY..XY)",
    ]
    lines.extend(
        f"{format(float(x), '.17g')}, {format(float(y), '.17g')}"
        for x, y in zip(values, payload["data"][0], strict=True)
    )
    lines.append("##END=")
    return "\n".join(lines) + "\n"


def build_export_artifact(dataset: SherpaDataset, *, filename: str, format: str) -> dict[str, object]:
    """Serialize one canonical dataset into a closed, digest-bound artifact."""

    if not isinstance(dataset, SherpaDataset):
        raise TypeError("output.export requires a SherpaDataset")
    parameters = canonicalize_export_parameters({"filename": filename, "format": format})
    safe_filename = parameters["filename"]
    format = parameters["format"]
    values = np.asarray(dataset.data)
    if values.size > _MAX_EXPORT_NUMERIC_ELEMENTS:
        raise ValueError("export dataset exceeds the decoded-element limit")
    if not np.all(np.isfinite(values)):
        raise ValueError("output.export rejects non-finite values")
    if format == "json":
        payload = dataset.to_dict(include_extra=True)
        # Dataset serialization has one complete current authority; export
        # must not construct a second compatibility projection.
        source_digest = dataset.scientific_digest
        shape = list(dataset.shape)
        content = encode_portable_json(payload, shape)
    else:
        matrix = _finite_matrix(dataset)
        payload = _dataset_payload(dataset, matrix)
        source_digest = dataset.scientific_digest
        shape = [int(value) for value in matrix.shape]
    if format == "csv":
        content = _csv_content(payload)
    elif format == "jdx":
        content = _jdx_content(payload)
    encoded = content.encode("utf-8")
    if len(encoded) > _MAX_EXPORT_BYTES:
        raise ValueError(f"export artifact exceeds the {_MAX_EXPORT_BYTES}-byte limit")
    return {
        "schema_version": EXPORT_ARTIFACT_SCHEMA,
        "filename": safe_filename,
        "format": format,
        "media_type": _FORMAT_MEDIA_TYPE[format],
        "content_encoding": "utf-8",
        "content": content,
        "content_sha256": hashlib.sha256(encoded).hexdigest(),
        "byte_length": len(encoded),
        "source_digest": source_digest,
        "shape": shape,
    }


def verify_export_artifact(value: object) -> dict[str, object]:
    """Validate a closed artifact and return a detached plain dictionary."""

    if not isinstance(value, Mapping) or set(value) != _ARTIFACT_FIELDS:
        raise ValueError("export artifact must use the closed schema")
    artifact = dict(value)
    if artifact["schema_version"] != EXPORT_ARTIFACT_SCHEMA:
        raise ValueError("unsupported export artifact schema")
    fmt = artifact["format"]
    if not isinstance(fmt, str) or fmt not in _FORMAT_SUFFIX:
        raise ValueError("export artifact format is invalid")
    artifact["filename"] = _safe_filename(artifact["filename"], fmt)
    if artifact["media_type"] != _FORMAT_MEDIA_TYPE[fmt] or artifact["content_encoding"] != "utf-8":
        raise ValueError("export artifact media contract is invalid")
    content = artifact["content"]
    if not isinstance(content, str):
        raise ValueError("export artifact content must be UTF-8 text")
    encoded = content.encode("utf-8")
    byte_length = artifact["byte_length"]
    if (
        len(encoded) > _MAX_EXPORT_BYTES
        or not isinstance(byte_length, int)
        or isinstance(byte_length, bool)
        or byte_length != len(encoded)
    ):
        raise ValueError("export artifact byte length is invalid")
    digest = hashlib.sha256(encoded).hexdigest()
    if artifact["content_sha256"] != digest:
        raise ValueError("export artifact content digest does not match")
    if not isinstance(artifact["content_sha256"], str) or not _SHA256_RE.fullmatch(artifact["content_sha256"]):
        raise ValueError("export artifact content digest is invalid")
    if not isinstance(artifact["source_digest"], str) or not _SHA256_RE.fullmatch(artifact["source_digest"]):
        raise ValueError("export artifact source digest is invalid")
    shape = artifact["shape"]
    if (
        not isinstance(shape, list)
        or not shape
        or not all(isinstance(v, int) and not isinstance(v, bool) and v > 0 for v in shape)
    ):
        raise ValueError("export artifact shape is invalid")
    if fmt != "json" and len(shape) != 2:
        raise ValueError("CSV and JCAMP-DX export artifacts must be two-dimensional")
    return artifact


def materialize_export_artifact(value: object, output_dir: str | Path) -> Path:
    """Write verified artifact bytes beneath an explicit host-owned directory."""

    artifact = verify_export_artifact(value)
    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=True)
    destination = root / str(artifact["filename"])
    with destination.open("xb") as output:
        output.write(str(artifact["content"]).encode("utf-8"))
    return destination


__all__ = [
    "EXPORT_ARTIFACT_SCHEMA",
    "build_export_artifact",
    "canonicalize_export_parameters",
    "materialize_export_artifact",
    "verify_export_artifact",
]
