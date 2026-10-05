"""One lossless authority for sample-table supervision and grouping context."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Mapping, Sequence

import numpy as np

from spectra_sherpa.app.lib.collection_assembly import lossless_sample_table_scalar
from spectra_sherpa.app.lib.sherpa_dataset import SherpaDataset, TargetContext
from spectra_sherpa.app.lib.target_authority import issue_target_authority, verify_target_authority
from spectra_sherpa.app.services.dag.meta_helpers import add_processing_step
from spectra_sherpa.core.target_authority import TargetAuthority, admit_target_authority

SUPERVISION_BINDING_SCHEMA_VERSION = "spectra-sample-table-supervision/2"
_SHA256_KEYS = (
    "source_manifest_sha256",
    "collection_definition_sha256",
    "scientific_collection_sha256",
)


def _canonical_json(value: object) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("utf-8")


def _sha256(value: object) -> str:
    return hashlib.sha256(_canonical_json(value)).hexdigest()


def _dataset_scientific_projection_sha256(dataset: SherpaDataset) -> str:
    # The attach-target provenance entry records this binding digest. Binding
    # the entry itself would therefore create a circular identity. Derive the
    # supervision content identity from the one canonical dataset projection,
    # with operational provenance explicitly outside this nested receipt.
    return _sha256(dataset.scientific_projection(include_provenance=False))


def _require_digest(value: object, *, field: str, optional: bool) -> str | None:
    if value is None and optional:
        return None
    if not isinstance(value, str) or len(value) != 64 or any(ch not in "0123456789abcdef" for ch in value):
        raise ValueError(f"sample-table supervision requires a valid {field}")
    return value


def _column(
    sample_table: Mapping[str, Sequence[object]],
    name: str,
    *,
    n_samples: int,
) -> list[str | int | float | bool | None]:
    if not isinstance(name, str) or not name or name != name.strip():
        raise ValueError("sample-table supervision column names must be exact non-empty strings")
    values = sample_table.get(name)
    if not isinstance(values, Sequence) or isinstance(values, (str, bytes, bytearray)):
        raise ValueError(f"dataset sample table has no aligned column {name!r}")
    if len(values) != n_samples:
        raise ValueError(f"dataset sample table column {name!r} is not aligned to the sample axis")
    return [lossless_sample_table_scalar(value, max_text_chars=4096) for value in values]


def _uniform_identity_type(values: Sequence[object], *, name: str) -> None:
    if any(value is None for value in values):
        raise ValueError(f"sample-table supervision column {name!r} may not contain missing values")
    identities = {type(value) for value in values}
    if len(identities) != 1:
        raise ValueError(f"sample-table supervision column {name!r} must use one exact scalar representation")


@dataclass(frozen=True)
class SampleTableSupervisionBinding:
    """Exact target/group vectors and their path-free scientific identity."""

    target: np.ndarray
    groups: np.ndarray | None
    record: Mapping[str, object]
    digest: str


def bind_sample_table_supervision(
    dataset: SherpaDataset,
    *,
    target_column: str,
    target_type: str,
    group_column: str | None = None,
    target_authority: TargetAuthority | None = None,
) -> SampleTableSupervisionBinding:
    """Bind aligned sample-table columns without making metadata predictors.

    The returned group vector is validation context only.  It is intentionally
    separate from :class:`SherpaDataset` and must be passed explicitly when a
    grouped validation capability is constructed.
    """

    if not isinstance(dataset, SherpaDataset) or dataset.ndim < 2:
        raise ValueError("sample-table supervision requires a SherpaDataset")
    sample_axis = dataset.sample_axis
    labels = getattr(sample_axis, "labels", None) if sample_axis is not None else None
    table = getattr(sample_axis, "sample_table", None) if sample_axis is not None else None
    if labels is None or not isinstance(table, Mapping):
        raise ValueError("sample-table supervision requires aligned sample labels and a sample table")
    if len(labels) != dataset.shape[0]:
        raise ValueError("dataset sample labels are not aligned to X")
    normalized_labels = [lossless_sample_table_scalar(value, max_text_chars=4096) for value in labels]
    if any(not isinstance(value, str) or not value for value in normalized_labels):
        raise ValueError("sample-table supervision requires exact non-empty string sample labels")
    if len(set(normalized_labels)) != len(normalized_labels):
        raise ValueError("sample-table supervision requires unique sample labels")
    sample_ids = _column(table, "sample_id", n_samples=dataset.shape[0])
    if sample_ids != normalized_labels:
        raise ValueError("sample_table.sample_id does not exactly match sample-axis labels and order")

    authority = target_authority or issue_target_authority(
        dataset,
        column=target_column,
        target_type=target_type,  # type: ignore[arg-type]
    )
    if authority.column != target_column or authority.target_type != target_type:
        raise ValueError("sample-table target selection differs from its target authority")
    verify_target_authority(dataset, authority)

    target_values = _column(table, authority.column, n_samples=dataset.shape[0])
    _uniform_identity_type(target_values, name=target_column)
    if target_type == "categorical":
        if any(not isinstance(value, str) or not value for value in target_values):
            raise ValueError("categorical sample-table targets must be exact non-empty strings")
        if len(set(target_values)) < 2:
            raise ValueError("categorical sample-table targets require at least two classes")
        target = np.asarray(target_values, dtype=str)
    elif target_type == "continuous":
        if any(isinstance(value, bool) or not isinstance(value, (int, float)) for value in target_values):
            raise ValueError("continuous sample-table targets must be finite numeric values")
        target = np.asarray(target_values, dtype=np.float64)
    else:
        raise ValueError(f"Unsupported target type: {target_type!r}")

    normalized_group_column = None if group_column is None else group_column
    groups: np.ndarray | None = None
    group_values: list[str | int | float | bool | None] | None = None
    if normalized_group_column is not None:
        group_values = _column(table, normalized_group_column, n_samples=dataset.shape[0])
        _uniform_identity_type(group_values, name=normalized_group_column)
        if any(isinstance(value, bool) for value in group_values):
            raise ValueError("sample-table validation groups may not be boolean")
        groups = np.asarray(group_values)
        if groups.dtype.kind == "O":
            raise ValueError("sample-table validation groups use an unsupported representation")
        # The column is an attached authority, not a request to partition by
        # it. A selected single-instrument view legitimately carries one group;
        # methods that actually hold out whole groups enforce their own
        # two-group minimum when constructing the partition.

    source_collection = dataset.meta.get("source_collection")
    if not isinstance(source_collection, Mapping):
        raise ValueError("sample-table supervision requires the exact source-collection identity")
    source_identities = {
        key: _require_digest(
            source_collection.get("manifest_digest" if key == "source_manifest_sha256" else key),
            field=key,
            optional=False,
        )
        for key in _SHA256_KEYS
    }
    normalized_table = {str(name): _column(table, str(name), n_samples=dataset.shape[0]) for name in sorted(table)}
    record: dict[str, object] = {
        "schema_version": SUPERVISION_BINDING_SCHEMA_VERSION,
        "target_authority": authority.canonical_dict(),
        "group_column": normalized_group_column,
        "sample_count": int(dataset.shape[0]),
        "sample_labels_sha256": _sha256(normalized_labels),
        "sample_table_sha256": _sha256(normalized_table),
        "target_sha256": _sha256(target_values),
        "groups_sha256": _sha256(group_values) if group_values is not None else None,
        "dataset_scientific_projection_sha256": _dataset_scientific_projection_sha256(dataset),
        **source_identities,
    }
    digest = _sha256(record)
    target.setflags(write=False)
    if groups is not None:
        groups = np.array(groups, copy=True)
        groups.setflags(write=False)
    return SampleTableSupervisionBinding(target=target, groups=groups, record=record, digest=digest)


def attach_sample_table_supervision(
    dataset: SherpaDataset,
    *,
    target_column: str,
    target_type: str,
    group_column: str | None = None,
    node_id: str,
    target_authority: TargetAuthority | None = None,
) -> SherpaDataset:
    """Attach one exact sample-table target/group authority to a snapshot."""

    binding = bind_sample_table_supervision(
        dataset,
        target_column=target_column,
        target_type=target_type,
        group_column=group_column,
        target_authority=target_authority,
    )
    authority = admit_target_authority(binding.record["target_authority"], optional=False)
    assert authority is not None
    result = dataset.snapshot()
    result.target = np.array(binding.target, copy=True)
    if target_type == "categorical":
        class_names = sorted({str(value) for value in binding.target})
        result.target_context = TargetContext(
            target_type="categorical",
            target_name=target_column,
            target_names=[target_column],
            selected_target=target_column,
            target_units=authority.units,
            selected_authority=authority,
            n_classes=len(class_names),
            class_names=class_names,
        )
    elif target_type == "continuous":
        result.target_context = TargetContext(
            target_type="continuous",
            target_name=target_column,
            target_names=[target_column],
            selected_target=target_column,
            target_units=authority.units,
            selected_authority=authority,
        )
    else:  # pragma: no cover - bind_sample_table_supervision refuses first
        raise ValueError(f"Unsupported target type: {target_type!r}")

    # Target context participates in the scientific projection, so issue the
    # durable binding only after the result is fully attached.
    binding = bind_sample_table_supervision(
        result,
        target_column=target_column,
        target_type=target_type,
        group_column=group_column,
        target_authority=authority,
    )
    result.meta["supervision_binding"] = {**binding.record, "supervision_binding_sha256": binding.digest}
    add_processing_step(
        result,
        "data.attach_target",
        {
            "target_authority": authority.canonical_dict(),
            "target_source": "sample_table_column",
            "target_column": target_column,
            "group_column": group_column,
            "target_shape": list(binding.target.shape),
            "target_names": [target_column],
            "sample_identity_checked": True,
            "sample_table_schema": None,
            "sample_table_source_file_id": None,
            "sample_table_identity_checked": True,
            "supervision_binding_sha256": binding.digest,
        },
        node_id=node_id,
    )
    return result


def validate_bound_sample_table_supervision(
    dataset: SherpaDataset,
    *,
    binding_record: object,
    dataset_ref_digest: object,
    groups: object,
) -> SampleTableSupervisionBinding:
    """Re-admit an attached binding before omitting its table from transport."""

    if not isinstance(binding_record, Mapping):
        raise ValueError("dataset supervision binding is malformed")
    expected_keys = {
        "schema_version",
        "target_authority",
        "group_column",
        "sample_count",
        "sample_labels_sha256",
        "sample_table_sha256",
        "target_sha256",
        "groups_sha256",
        "dataset_scientific_projection_sha256",
        *_SHA256_KEYS,
        "supervision_binding_sha256",
    }
    if set(binding_record) != expected_keys:
        raise ValueError("dataset supervision binding schema is not closed")
    authority = admit_target_authority(binding_record.get("target_authority"), optional=False)
    assert authority is not None
    group_column = binding_record.get("group_column")
    if group_column is not None and not isinstance(group_column, str):
        raise ValueError("dataset supervision binding columns are malformed")
    rebuilt = bind_sample_table_supervision(
        dataset,
        target_column=authority.column,
        target_type=authority.target_type,
        group_column=group_column,
        target_authority=authority,
    )
    expected_record = {**rebuilt.record, "supervision_binding_sha256": rebuilt.digest}
    if dict(binding_record) != expected_record or dataset_ref_digest != rebuilt.digest:
        raise ValueError("dataset supervision binding does not match its exact sample table")
    if dataset.target is None or not np.array_equal(np.asarray(dataset.target), rebuilt.target):
        raise ValueError("dataset target does not match its sample-table supervision binding")
    if rebuilt.groups is None:
        if groups is not None:
            raise ValueError("dataset carries undeclared validation groups")
    elif groups is None or not np.array_equal(np.asarray(groups), rebuilt.groups):
        raise ValueError("validation groups do not match the sample-table supervision binding")
    return rebuilt


def rebind_sample_preserving_supervision(source: SherpaDataset, result: SherpaDataset) -> None:
    """Derive a receipt after a trusted feature transform, without rebinding samples.

    Never repair an invalid input receipt. The numerical operation may change
    X and its feature space, but sample order, annotations, targets, groups,
    and their original source authority must remain exact.
    """

    original = admit_attached_sample_table_supervision(source)
    if original is None:
        return
    authority = admit_target_authority(original.record["target_authority"], optional=False)
    assert authority is not None
    rebound = bind_sample_table_supervision(
        result,
        target_column=authority.column,
        target_type=authority.target_type,
        group_column=original.record["group_column"],  # type: ignore[arg-type]
        target_authority=authority,
    )
    invariant_keys = set(original.record) - {"dataset_scientific_projection_sha256"}
    if any(original.record[key] != rebound.record[key] for key in invariant_keys):
        raise ValueError("feature transform changed the exact sample supervision context")
    source_projection = source.scientific_projection(include_data=False, include_provenance=False)
    result_projection = result.scientific_projection(include_data=False, include_provenance=False)
    source_samples = [axis for axis in source_projection["axes"] if axis["dimension"] == 0]
    result_samples = [axis for axis in result_projection["axes"] if axis["dimension"] == 0]
    if (
        source_samples != result_samples
        or source_projection["target_context"] != result_projection["target_context"]
        or result.target is None
        or not np.array_equal(np.asarray(result.target), original.target)
    ):
        raise ValueError("feature transform changed the exact sample supervision context")
    result.meta["supervision_binding"] = {**rebound.record, "supervision_binding_sha256": rebound.digest}


def admit_attached_sample_table_supervision(dataset: SherpaDataset) -> SampleTableSupervisionBinding | None:
    """Re-admit optional dataset-attached supervision for portable transport.

    A dataset without a supervision receipt remains an ordinary target-free
    transport.  When a receipt is present, derive its exact target and group
    vectors from the sample table and require the entire stored receipt to
    reproduce before returning either authority.
    """

    record = dataset.meta.get("supervision_binding")
    if record is None:
        return None
    if not isinstance(record, Mapping):
        raise ValueError("dataset supervision binding is malformed")
    authority = admit_target_authority(record.get("target_authority"), optional=False)
    assert authority is not None
    group_column = record.get("group_column")
    if group_column is not None and not isinstance(group_column, str):
        raise ValueError("dataset supervision binding columns are malformed")
    rebuilt = bind_sample_table_supervision(
        dataset,
        target_column=authority.column,
        target_type=authority.target_type,
        group_column=group_column,
        target_authority=authority,
    )
    return validate_bound_sample_table_supervision(
        dataset,
        binding_record=record,
        dataset_ref_digest=record.get("supervision_binding_sha256"),
        groups=rebuilt.groups,
    )


__all__ = [
    "SUPERVISION_BINDING_SCHEMA_VERSION",
    "SampleTableSupervisionBinding",
    "admit_attached_sample_table_supervision",
    "attach_sample_table_supervision",
    "bind_sample_table_supervision",
    "rebind_sample_preserving_supervision",
    "validate_bound_sample_table_supervision",
]
