"""Closed, portable authority for scientist-defined experiment collections."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from typing import Any

import numpy as np

from spectra_sherpa.app.lib.axes import SampleAxis
from spectra_sherpa.app.lib.collection_assembly import (
    CollectionMember,
    assemble_collection,
    canonical_collection_file_name,
    lossless_sample_table_scalar,
)
from spectra_sherpa.app.lib.data_roles import normalize_data_role
from spectra_sherpa.app.lib.sherpa_dataset import DomainContext, SherpaDataset, TargetContext

COLLECTION_DEFINITION_SCHEMA = "spectrasherpa-collection-definition/1"
SCIENTIFIC_COLLECTION_SCHEMA = "spectrasherpa-scientific-collection/2"
LEGACY_SCIENTIFIC_COLLECTION_SCHEMA = "spectrasherpa-scientific-collection/1"
SCIENTIFIC_DATASET_PROJECTION_SCHEMA = "spectrasherpa-scientific-dataset-projection/2"
MAX_COLLECTION_DEFINITION_BYTES = 4 * 1024 * 1024
MAX_COLLECTION_DEFINITION_ROWS = 10_000
MAX_COLLECTION_DEFINITION_COLUMNS = 64
MAX_COLLECTION_TEXT_CHARS = 4_096
_SHA256_CHARS = frozenset("0123456789abcdef")
_REQUIRED_COLUMNS = frozenset({"sample_id", "specimen_id", "block"})
_ROOT_KEYS = frozenset({"schema_version", "columns", "collection", "rows"})
_COLLECTION_KEYS = frozenset({"dataset_id", "title", "units", "data_role", "domain", "sample_axis"})
_SAMPLE_AXIS_KEYS = frozenset({"title", "units", "values_policy"})
_ROW_KEYS = frozenset({"file_name", "sha256", "asset_id", "source_row_index", "sample_id", "annotations"})


@dataclass(frozen=True)
class ValidatedCollectionDefinition:
    """Canonical definition bytes and their immutable SHA-256 identity."""

    payload: dict[str, Any]
    canonical_bytes: bytes
    sha256: str


def _exact_keys(value: Mapping[str, object], expected: frozenset[str], *, name: str) -> None:
    if frozenset(value) != expected:
        raise ValueError(f"collection definition {name} has an invalid schema")


def _text(value: object, *, name: str, allow_none: bool = False) -> str | None:
    if value is None and allow_none:
        return None
    if not isinstance(value, str) or not value or value != value.strip():
        raise ValueError(f"collection definition {name} must be exact non-empty text")
    if len(value) > MAX_COLLECTION_TEXT_CHARS:
        raise ValueError(f"collection definition {name} is too long")
    return value


def _sha256(value: object, *, name: str) -> str:
    if not isinstance(value, str) or len(value) != 64 or any(ch not in _SHA256_CHARS for ch in value):
        raise ValueError(f"collection definition {name} must be lowercase SHA-256 hex")
    return value


def _canonical_json_sha256(value: object) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()
    return hashlib.sha256(encoded).hexdigest()


def scientific_dataset_projection(dataset: SherpaDataset) -> dict[str, Any]:
    """Bind project collection custody to the sole dataset science authority."""

    # Closed collection definitions intentionally cannot create these modeling
    # authorities.  Bind the absence explicitly so a future parser/assembler
    # cannot turn annotations into a target or class label silently.
    if dataset.target is not None or (dataset.sample_axis is not None and dataset.sample_axis.classes is not None):
        raise ValueError("defined scientific collection cannot contain target or class state")
    return {
        "schema_version": SCIENTIFIC_DATASET_PROJECTION_SCHEMA,
        "dataset_id": dataset.dataset_id,
        "dataset_scientific_projection": dataset.scientific_projection(),
        "dataset_scientific_digest": dataset.scientific_digest,
    }


def scientific_dataset_projection_sha256(projection: Mapping[str, object]) -> str:
    if projection.get("schema_version") != SCIENTIFIC_DATASET_PROJECTION_SCHEMA:
        raise ValueError("scientific dataset projection schema is unsupported")
    return _canonical_json_sha256(projection)


def validate_collection_definition(value: Mapping[str, object]) -> ValidatedCollectionDefinition:
    """Return the unique canonical representation of one closed definition."""

    if not isinstance(value, Mapping):
        raise ValueError("collection definition must be an object")
    _exact_keys(value, _ROOT_KEYS, name="root")
    if value.get("schema_version") != COLLECTION_DEFINITION_SCHEMA:
        raise ValueError("collection definition schema version is unsupported")

    raw_columns = value.get("columns")
    if not isinstance(raw_columns, list) or not raw_columns or len(raw_columns) > MAX_COLLECTION_DEFINITION_COLUMNS:
        raise ValueError("collection definition columns are invalid")
    columns = [_text(item, name="column") for item in raw_columns]
    if len(set(columns)) != len(columns) or not _REQUIRED_COLUMNS.issubset(columns):
        raise ValueError("collection definition requires unique sample_id, specimen_id, and block columns")

    raw_collection = value.get("collection")
    if not isinstance(raw_collection, Mapping):
        raise ValueError("collection definition collection context must be an object")
    _exact_keys(raw_collection, _COLLECTION_KEYS, name="collection context")
    raw_domain = raw_collection.get("domain")
    if not isinstance(raw_domain, Mapping):
        raise ValueError("collection definition domain must be an object")
    try:
        domain = DomainContext.model_validate(raw_domain)
    except Exception as exc:
        raise ValueError("collection definition domain is invalid") from exc
    normalized_domain = domain.model_dump(mode="json", exclude_none=False)
    if dict(raw_domain) != normalized_domain:
        raise ValueError("collection definition domain must use the exact closed DomainContext schema")

    raw_sample_axis = raw_collection.get("sample_axis")
    if not isinstance(raw_sample_axis, Mapping):
        raise ValueError("collection definition sample axis must be an object")
    _exact_keys(raw_sample_axis, _SAMPLE_AXIS_KEYS, name="sample axis")
    values_policy = raw_sample_axis.get("values_policy")
    if values_policy not in {"omit", "preserve"}:
        raise ValueError("collection definition sample-axis values policy is invalid")
    collection = {
        "dataset_id": _text(raw_collection.get("dataset_id"), name="dataset_id"),
        "title": _text(raw_collection.get("title"), name="title"),
        "units": _text(raw_collection.get("units"), name="units", allow_none=True),
        "data_role": normalize_data_role(raw_collection.get("data_role")),
        "domain": normalized_domain,
        "sample_axis": {
            "title": _text(raw_sample_axis.get("title"), name="sample-axis title", allow_none=True),
            "units": _text(raw_sample_axis.get("units"), name="sample-axis units", allow_none=True),
            "values_policy": values_policy,
        },
    }

    raw_rows = value.get("rows")
    if not isinstance(raw_rows, list) or not raw_rows or len(raw_rows) > MAX_COLLECTION_DEFINITION_ROWS:
        raise ValueError("collection definition rows are invalid")
    rows: list[dict[str, Any]] = []
    sample_ids: set[str] = set()
    source_rows: set[tuple[str, str, str, int]] = set()
    projected_bytes = 4096 + sum(len(str(column).encode("utf-8")) + 32 for column in columns)
    for raw_row in raw_rows:
        if not isinstance(raw_row, Mapping):
            raise ValueError("collection definition row must be an object")
        _exact_keys(raw_row, _ROW_KEYS, name="row")
        file_name = canonical_collection_file_name(raw_row.get("file_name"))  # type: ignore[arg-type]
        digest = _sha256(raw_row.get("sha256"), name="source digest")
        asset_id = _text(raw_row.get("asset_id"), name="asset_id")
        row_index = raw_row.get("source_row_index")
        if not isinstance(row_index, int) or isinstance(row_index, bool) or row_index < 0:
            raise ValueError("collection definition source_row_index must be a non-negative integer")
        sample_id = _text(raw_row.get("sample_id"), name="sample_id")
        raw_annotations = raw_row.get("annotations")
        if not isinstance(raw_annotations, Mapping) or set(raw_annotations) != set(columns):
            raise ValueError("collection definition annotations must match the exact declared columns")
        annotations = {
            column: lossless_sample_table_scalar(
                raw_annotations[column],
                max_text_chars=MAX_COLLECTION_TEXT_CHARS,
            )
            for column in columns
        }
        projected_bytes += len(file_name.encode("utf-8")) + len(str(asset_id).encode("utf-8")) + 256
        for annotation in annotations.values():
            projected_bytes += len(annotation.encode("utf-8")) + 32 if isinstance(annotation, str) else 64
        if projected_bytes > MAX_COLLECTION_DEFINITION_BYTES:
            raise ValueError("collection definition exceeds the 4 MiB canonical-byte limit")
        if annotations["sample_id"] != sample_id:
            raise ValueError("collection definition sample_id is not aligned with its annotation row")
        if not isinstance(annotations["specimen_id"], (str, int, float, bool)):
            raise ValueError("collection definition specimen_id must be a grouping scalar")
        if not isinstance(annotations["block"], (str, int, float, bool)):
            raise ValueError("collection definition block must be a grouping scalar")
        if annotations["specimen_id"] == "" or annotations["block"] == "":
            raise ValueError("collection definition grouping values cannot be empty")
        source_key = (file_name.casefold(), digest, str(asset_id), row_index)
        if sample_id in sample_ids or source_key in source_rows:
            raise ValueError("collection definition contains duplicate sample or source-row identity")
        sample_ids.add(str(sample_id))
        source_rows.add(source_key)
        rows.append(
            {
                "file_name": file_name,
                "sha256": digest,
                "asset_id": asset_id,
                "source_row_index": row_index,
                "sample_id": sample_id,
                "annotations": annotations,
            }
        )

    payload = {
        "schema_version": COLLECTION_DEFINITION_SCHEMA,
        "columns": columns,
        "collection": collection,
        "rows": rows,
    }
    canonical_bytes = (json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n").encode(
        "utf-8"
    )
    if len(canonical_bytes) > MAX_COLLECTION_DEFINITION_BYTES:
        raise ValueError("collection definition exceeds the 4 MiB canonical-byte limit")
    return ValidatedCollectionDefinition(
        payload=payload,
        canonical_bytes=canonical_bytes,
        sha256=hashlib.sha256(canonical_bytes).hexdigest(),
    )


def scientific_collection_identity(
    source_manifest: Mapping[str, object],
    definition: ValidatedCollectionDefinition | None,
    dataset: SherpaDataset | None = None,
) -> dict[str, Any]:
    """Bind exact source read semantics to the optional scientist definition."""

    return scientific_collection_identity_from_digest(
        source_manifest,
        definition.sha256 if definition is not None else None,
        (
            scientific_dataset_projection_sha256(scientific_dataset_projection(dataset))
            if definition is not None and dataset is not None
            else None
        ),
    )


def scientific_collection_identity_from_digest(
    source_manifest: Mapping[str, object],
    collection_definition_sha256: object,
    scientific_dataset_projection_sha256_value: object = None,
) -> dict[str, Any]:
    """Recompute the combined identity from closed source and definition digests."""

    source_digest = _sha256(source_manifest.get("manifest_digest"), name="source manifest digest")
    if collection_definition_sha256 is not None:
        collection_definition_sha256 = _sha256(
            collection_definition_sha256,
            name="collection definition digest",
        )
        scientific_dataset_projection_sha256_value = _sha256(
            scientific_dataset_projection_sha256_value,
            name="scientific dataset projection digest",
        )
    elif scientific_dataset_projection_sha256_value is not None:
        raise ValueError("scientific dataset projection cannot exist without a collection definition")
    identity = {
        "scientific_collection_schema_version": (
            SCIENTIFIC_COLLECTION_SCHEMA
            if collection_definition_sha256 is not None
            else LEGACY_SCIENTIFIC_COLLECTION_SCHEMA
        ),
        "source_manifest_sha256": source_digest,
        "collection_definition_sha256": collection_definition_sha256,
    }
    if collection_definition_sha256 is not None:
        identity["scientific_dataset_projection_sha256"] = scientific_dataset_projection_sha256_value
    encoded = json.dumps(identity, sort_keys=True, separators=(",", ":")).encode()
    return {**identity, "scientific_collection_sha256": hashlib.sha256(encoded).hexdigest()}


def apply_collection_definition(
    members: Sequence[CollectionMember],
    definition: ValidatedCollectionDefinition,
) -> SherpaDataset:
    """Assemble exact members in definition order and apply declared row semantics."""

    by_key: dict[tuple[str, str, str], CollectionMember] = {}
    for member in members:
        key = (canonical_collection_file_name(member.file_name).casefold(), member.sha256, member.asset_id)
        if key in by_key:
            raise ValueError("scientific collection contains duplicate source/asset identity")
        by_key[key] = member

    rows_by_key: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
    ordered_keys: list[tuple[str, str, str]] = []
    for row in definition.payload["rows"]:
        key = (row["file_name"].casefold(), row["sha256"], row["asset_id"])
        if key not in by_key:
            raise ValueError("collection definition does not match the admitted source/asset set")
        if key not in rows_by_key:
            rows_by_key[key] = []
            ordered_keys.append(key)
        elif ordered_keys[-1] != key:
            raise ValueError("collection definition rows for one source must be contiguous")
        rows_by_key[key].append(row)
    if set(rows_by_key) != set(by_key):
        raise ValueError("collection definition does not cover every admitted source/asset")

    context = definition.payload["collection"]
    sample_context = context["sample_axis"]
    projected: list[CollectionMember] = []
    for key in ordered_keys:
        member = by_key[key]
        rows = rows_by_key[key]
        expected_indices = list(range(member.dataset.n_samples))
        if [row["source_row_index"] for row in rows] != expected_indices:
            raise ValueError("collection definition does not cover source rows in exact native order")
        if member.dataset.target is not None or member.dataset.sample_axis is None:
            raise ValueError("collection definition requires a target-free dataset with a typed sample axis")
        if member.dataset.sample_axis.classes is not None:
            raise ValueError("collection definition cannot create or retain sample classes")
        if member.dataset.target_context != TargetContext():
            raise ValueError("collection definition cannot retain target semantics")
        dataset = member.dataset.copy()
        existing_axis = dataset.sample_axis
        assert existing_axis is not None
        dataset.sample_axis = SampleAxis(
            values=existing_axis.values if sample_context["values_policy"] == "preserve" else None,
            labels=[row["sample_id"] for row in rows],
            title=sample_context["title"],
            units=sample_context["units"],
            include_mask=(
                np.array(existing_axis.include_mask, copy=True) if existing_axis.include_mask is not None else None
            ),
            exclusion_reasons=(
                list(existing_axis.exclusion_reasons) if existing_axis.exclusion_reasons is not None else None
            ),
            sample_table={
                column: [row["annotations"][column] for row in rows] for column in definition.payload["columns"]
            },
        )
        dataset.domain = DomainContext.model_validate(context["domain"])
        dataset.units = context["units"]
        dataset.data_role = context["data_role"]
        projected.append(replace(member, dataset=dataset))

    result = assemble_collection(
        projected,
        title=context["title"],
        dataset_id=context["dataset_id"],
    )
    if result.target is not None or result.sample_axis is None or result.sample_axis.classes is not None:
        raise ValueError("collection definition produced forbidden target or class state")
    source_manifest = result.meta["source_collection"]
    identity = scientific_collection_identity(source_manifest, definition, result)
    source_manifest.update(identity)
    result.meta["collection_definition"] = {
        "schema_version": COLLECTION_DEFINITION_SCHEMA,
        "sha256": definition.sha256,
        "row_count": len(definition.payload["rows"]),
        "column_count": len(definition.payload["columns"]),
    }
    return result


def project_collection_definition(
    definition: ValidatedCollectionDefinition,
    members: Sequence[CollectionMember],
) -> ValidatedCollectionDefinition:
    """Project one admitted collection definition onto an exact member subset.

    File-scoped readers still need the labels and annotations declared by the
    experiment's collection definition.  Applying the complete definition to
    a subset is invalid, while dropping it loses the scientist's curated row
    semantics.  Derive a new closed definition containing only rows whose
    source/asset identity is present in ``members``.
    """

    selected = {
        (canonical_collection_file_name(member.file_name).casefold(), member.sha256, member.asset_id)
        for member in members
    }
    rows = [
        row
        for row in definition.payload["rows"]
        if (row["file_name"].casefold(), row["sha256"], row["asset_id"]) in selected
    ]
    observed = {(row["file_name"].casefold(), row["sha256"], row["asset_id"]) for row in rows}
    if observed != selected:
        raise ValueError("collection definition does not match the admitted source/asset subset")
    if len(rows) == len(definition.payload["rows"]):
        return definition
    return validate_collection_definition(
        {
            "schema_version": definition.payload["schema_version"],
            "columns": list(definition.payload["columns"]),
            "collection": dict(definition.payload["collection"]),
            "rows": rows,
        }
    )


__all__ = [
    "COLLECTION_DEFINITION_SCHEMA",
    "MAX_COLLECTION_DEFINITION_BYTES",
    "SCIENTIFIC_COLLECTION_SCHEMA",
    "SCIENTIFIC_DATASET_PROJECTION_SCHEMA",
    "ValidatedCollectionDefinition",
    "apply_collection_definition",
    "project_collection_definition",
    "scientific_collection_identity",
    "scientific_collection_identity_from_digest",
    "scientific_dataset_projection",
    "scientific_dataset_projection_sha256",
    "validate_collection_definition",
]
