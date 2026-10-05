"""Registered-reference collection identity shared by app and DAG loaders."""

from __future__ import annotations

import copy
import hashlib
import json
from collections.abc import Mapping, Sequence
from typing import Any

from spectra_sherpa.app.lib.collection_assembly import source_collection_manifest
from spectra_sherpa.app.lib.collection_definition import scientific_collection_identity_from_digest
from spectra_sherpa.app.lib.sherpa_dataset import SherpaDataset

REGISTERED_REFERENCE_COLLECTION_KEYS = frozenset(
    {
        "analysis.profile",
        "reference.artifact_id",
        "reference.artifact_sha256",
        "reference.member_sha256",
        "reference.projection_id",
        "reference.provider",
        "reference.target_object_name",
        "reference.target_object_scientific_digest",
        "reference.package_id",
        "reference.view_id",
        "reference.instrument_view",
        "reference.cohort",
        "reference.annotation_table_sha256",
    }
)

_REGISTERED_REFERENCE_DEFINITION_SCHEMA = "spectrasherpa-registered-reference-definition/1"
_REGISTERED_REFERENCE_COMPOSITE_DEFINITION_SCHEMA = "spectrasherpa-registered-reference-definition/2"


def copy_registered_reference_collection_extras(
    source: SherpaDataset,
    target: SherpaDataset,
    *,
    selected_asset_id: str | None,
) -> None:
    """Retain the bounded registered-reference authority across assembly."""

    projection_id = source.get_extra("reference.projection_id")
    if not isinstance(projection_id, str) or projection_id != selected_asset_id:
        return
    for key in REGISTERED_REFERENCE_COLLECTION_KEYS:
        value = source.get_extra(key)
        if value is not None:
            target.extra[key] = copy.deepcopy(value)


def _canonical_digest(value: object) -> str:
    encoded = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def registered_reference_collection_identity(
    source_manifest: Mapping[str, object],
    dataset: SherpaDataset,
    *,
    members: Sequence[tuple[SherpaDataset, str | None]] | None = None,
) -> dict[str, Any] | None:
    """Issue a recomputable sample-table authority for registered views.

    Registered references obtain row annotations from a qualified native
    projection, not from a scientist-authored collection-definition file.
    Supervised execution still needs the same three-part custody guarantee:
    exact source bytes, an exact row/annotation definition, and an exact
    scientific dataset projection. Build those identities from the verified
    registered member instead of inventing a user-authored sidecar.
    """

    registered_members = list(members) if members is not None else [(dataset, None)]
    if not registered_members:
        return None
    member_projections: list[dict[str, Any]] = []
    for member, selected_asset_id in registered_members:
        projection_id = member.get_extra("reference.projection_id")
        if not isinstance(projection_id, str) or (selected_asset_id is not None and projection_id != selected_asset_id):
            return None
        projection = _registered_member_definition_projection(member)
        if projection is None:
            return None
        member_projections.append(projection)

    if len(member_projections) == 1:
        # Keep the deployed single-view identity byte-for-byte stable. The
        # assembled dataset is authoritative because its title and provenance
        # intentionally differ from the admitted member.
        definition_projection = _registered_member_definition_projection(dataset)
        if definition_projection is None:
            return None
    else:
        raw_manifest_members = source_manifest.get("files")
        if not isinstance(raw_manifest_members, list) or len(raw_manifest_members) != len(member_projections):
            raise ValueError("registered reference collection member authority is misaligned")
        definition_projection = {
            "schema_version": _REGISTERED_REFERENCE_COMPOSITE_DEFINITION_SCHEMA,
            "members": [
                {
                    "source_file_name": manifest_member.get("file_name"),
                    **projection,
                }
                for manifest_member, projection in zip(raw_manifest_members, member_projections, strict=True)
                if isinstance(manifest_member, Mapping)
            ],
        }
        if len(definition_projection["members"]) != len(member_projections):
            raise ValueError("registered reference collection source manifest is malformed")

    definition_digest = _canonical_digest(definition_projection)
    dataset_projection_digest = _canonical_digest(
        {
            "schema_version": "spectrasherpa-registered-reference-dataset-projection/1",
            "dataset_scientific_projection": dataset.scientific_projection(include_provenance=False),
        }
    )
    return scientific_collection_identity_from_digest(
        source_manifest,
        definition_digest,
        dataset_projection_digest,
    )


def validate_registered_reference_collection_identity(
    source_manifest: object,
    dataset: SherpaDataset,
) -> None:
    """Re-admit an annotation-bearing registered view before table omission."""

    validate_registered_reference_source_identity(source_manifest, dataset)
    assert isinstance(source_manifest, Mapping)
    rebuilt = registered_reference_collection_identity(source_manifest, dataset)
    if rebuilt is None:
        raise ValueError("dataset is not an annotation-bearing registered reference")
    expected = {key: source_manifest.get(key) for key in rebuilt}
    if expected != rebuilt:
        raise ValueError("registered reference collection identity does not match its exact annotations")


def validate_registered_reference_source_identity(
    source_manifest: object,
    dataset: SherpaDataset,
) -> None:
    """Re-admit registered source members and annotations across target selection."""

    if not isinstance(source_manifest, Mapping):
        raise ValueError("registered reference dataset has no source-collection identity")
    files = source_manifest.get("files")
    if not isinstance(files, list):
        raise ValueError("registered reference source manifest is malformed")
    rebuilt_manifest = source_collection_manifest(files)
    if any(source_manifest.get(key) != value for key, value in rebuilt_manifest.items()):
        raise ValueError("registered reference source manifest does not match its exact members")
    definition_projection = _registered_member_definition_projection(dataset)
    if definition_projection is None:
        raise ValueError("dataset is not an annotation-bearing registered reference")
    definition_digest = _canonical_digest(definition_projection)
    rebuilt = scientific_collection_identity_from_digest(
        source_manifest,
        definition_digest,
        source_manifest.get("scientific_dataset_projection_sha256"),
    )
    expected = {key: source_manifest.get(key) for key in rebuilt}
    if expected != rebuilt:
        raise ValueError("registered reference collection identity does not match its exact annotations")


def _registered_member_definition_projection(dataset: SherpaDataset) -> dict[str, Any] | None:
    projection_id = dataset.get_extra("reference.projection_id")
    artifact_id = dataset.get_extra("reference.artifact_id")
    artifact_sha256 = dataset.get_extra("reference.artifact_sha256")
    member_sha256 = dataset.get_extra("reference.member_sha256")
    axis = dataset.sample_axis
    table = axis.sample_table if axis is not None else None
    if not isinstance(projection_id, str):
        return None
    if axis is None or axis.labels is None or not isinstance(table, Mapping):
        if dataset.target is None:
            return None
        raise ValueError("registered reference target has no aligned sample-table authority")
    if (
        not isinstance(artifact_id, str)
        or not isinstance(artifact_sha256, str)
        or len(artifact_sha256) != 64
        or not isinstance(member_sha256, str)
        or len(member_sha256) != 64
    ):
        raise ValueError("registered reference sample-table authority is incomplete")
    return {
        "schema_version": _REGISTERED_REFERENCE_DEFINITION_SCHEMA,
        "projection_id": projection_id,
        "artifact_id": artifact_id,
        "artifact_sha256": artifact_sha256,
        "member_sha256": member_sha256,
        "package_id": dataset.get_extra("reference.package_id"),
        "view_id": dataset.get_extra("reference.view_id"),
        "annotation_table_sha256": dataset.get_extra("reference.annotation_table_sha256"),
        "target_object_name": dataset.get_extra("reference.target_object_name"),
        "target_object_scientific_digest": dataset.get_extra("reference.target_object_scientific_digest"),
        "sample_labels": list(axis.labels),
        "sample_table": {str(name): list(values) for name, values in sorted(table.items())},
    }
