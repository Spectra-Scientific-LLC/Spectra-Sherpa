"""Fail-closed materialization for user-acquired registered references.

This boundary never downloads, mirrors, or redistributes an upstream artifact.
It snapshots bytes selected by the user, verifies the registered size and
SHA-256, extracts only the exact registered member, and delegates scientific
decoding to the qualified native ingestion registry.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import shutil
import stat
import tempfile
import zipfile
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from spectra_sherpa.app.lib.axes import FeatureAxis, SampleAxis
from spectra_sherpa.app.lib.collection_assembly import prepared_data_digest, source_collection_manifest
from spectra_sherpa.app.lib.reference_artifacts import (
    ReferenceArtifactRegistry,
    ReferenceArtifactRegistryError,
    load_reference_artifact_registry,
)
from spectra_sherpa.app.lib.reference_dataset_packages import (
    package_view_projection,
    reference_annotation_table_digest,
)
from spectra_sherpa.app.lib.reference_datasets import feature_axis_values_digest
from spectra_sherpa.app.lib.registered_reference_collection_identity import (
    registered_reference_collection_identity,
)
from spectra_sherpa.app.lib.sample_labels import clean_sample_labels
from spectra_sherpa.app.lib.sherpa_dataset import (
    DomainContext,
    Provenance,
    SherpaDataset,
    SpectralAxis,
    TargetContext,
)
from spectra_sherpa.io import ingest
from spectra_sherpa.sdk.dataset_identity import public_dataset_digest

PORTABLE_REFERENCE_SCHEMA = "spectra-sherpa-external-reference/2"
REFERENCE_DIRECTORY_ENV = "SPECTRA_REFERENCE_DIR"
DEFAULT_REFERENCE_DIRECTORY = "reference-data"
MAX_SEARCH_ENTRIES = 256
_CHUNK_BYTES = 1024 * 1024
_SOURCE_PROJECTION_DIGEST_VERSION = b"spectra-sherpa-reference-source/1\x00"


def _reference_source_scope(projection_id: str) -> str:
    """Distinguish prepared Diesel projections from complete raw corpora."""

    if projection_id.startswith("public-diesel-"):
        return "prepared_d4052_gatest_projection"
    return "registered_projection"


class ReferenceMaterializationError(ValueError):
    """A selected source failed exact admission or scientific projection."""


def _axis_for_analysis_profile(
    axis_payload: Mapping[str, Any],
    analysis: Mapping[str, Any],
) -> FeatureAxis:
    """Bind the feature-axis class declared by the governed data role.

    A named process-variable table can carry numeric coordinates without
    becoming a spectrum.  Keeping it as a plain ``FeatureAxis`` prevents
    downstream presentation and capability checks from inferring wavelength
    semantics from the axis class alone.
    """

    if analysis.get("primary_role") == "X_features":
        return FeatureAxis.model_validate(axis_payload)
    return SpectralAxis.model_validate(axis_payload)


@dataclass(frozen=True, slots=True)
class MaterializedReferenceProjection:
    """A verified in-memory dataset and its path-free portable identity."""

    dataset: SherpaDataset
    portable_reference: Mapping[str, Any]


def reference_source_projection_digest(data: Any) -> str:
    """Hash one target-free numeric projection independently of metadata."""

    values = np.asarray(data, dtype="<f8", order="C")
    if values.ndim != 2 or not np.isfinite(values).all():
        raise ReferenceMaterializationError("registered reference source must be one finite 2-D matrix")
    digest = hashlib.sha256()
    digest.update(_SOURCE_PROJECTION_DIGEST_VERSION)
    digest.update(np.asarray(values.shape, dtype="<i8").tobytes(order="C"))
    digest.update(values.tobytes(order="C"))
    return digest.hexdigest()


def portable_reference_manifest(
    projection_id: str,
    *,
    registry: ReferenceArtifactRegistry | None = None,
) -> dict[str, Any]:
    """Return the stable export identity; local and server paths are excluded."""

    active = registry or load_reference_artifact_registry()
    projection = active.projection(projection_id).as_dict()
    artifact = active.artifact(projection["artifact_id"]).as_dict()
    member = _member_for_projection(artifact, projection)
    result = {
        "schema_version": PORTABLE_REFERENCE_SCHEMA,
        "projection_id": projection["projection_id"],
        "artifact_id": artifact["artifact_id"],
        "artifact_size_bytes": artifact["expected_size_bytes"],
        "artifact_sha256": artifact["sha256"],
        "member_path": member["path"],
        "member_size_bytes": member["expected_size_bytes"],
        "member_sha256": member["sha256"],
        "native_reader_contract": projection["native_reader_contract"],
        "scientific_sha256": projection["scientific_sha256"],
        "provider": artifact["provider"],
        "provider_page": artifact["provider_page"],
        "download_url": artifact["download_url"],
        "redistribution": artifact["redistribution"],
        "analysis_profile": projection["analysis"],
        "source_scope": _reference_source_scope(str(projection["projection_id"])),
    }
    package_view = package_view_projection(projection_id)
    if package_view is not None:
        result["dataset_package"] = package_view
        result["analysis_profile"] = _analysis_profile_for_package_view(projection, package_view)
    return result


def resolve_reference_artifact(
    projection_id: str,
    *,
    explicit_path: str | Path | None = None,
    search_directory: str | Path | None = None,
    cwd: str | Path | None = None,
    environ: Mapping[str, str] | None = None,
    registry: ReferenceArtifactRegistry | None = None,
    max_search_entries: int = MAX_SEARCH_ENTRIES,
) -> Path:
    """Resolve exact bytes without filename authority or recursive discovery.

    Resolution order is an explicit file, an explicit directory,
    ``SPECTRA_REFERENCE_DIR``, then ``./reference-data``. Directory scans are
    non-recursive, bounded, size-prefiltered, and digest-confirmed.
    """

    active = registry or load_reference_artifact_registry()
    projection = active.projection(projection_id).as_dict()
    artifact = active.artifact(projection["artifact_id"]).as_dict()
    if explicit_path is not None:
        path = Path(explicit_path).expanduser()
        _verify_regular_file(path, artifact)
        return path.resolve()
    if type(max_search_entries) is not int or not 1 <= max_search_entries <= 4096:
        raise ReferenceMaterializationError("reference search entry bound must be between 1 and 4096")

    roots: list[Path] = []
    if search_directory is not None:
        roots.append(Path(search_directory).expanduser())
    environment = os.environ if environ is None else environ
    configured = environment.get(REFERENCE_DIRECTORY_ENV, "").strip()
    if configured:
        roots.append(Path(configured).expanduser())
    roots.append(Path(cwd or Path.cwd()) / DEFAULT_REFERENCE_DIRECTORY)

    seen: set[Path] = set()
    for root in roots:
        resolved = root.resolve()
        if resolved in seen or not _is_plain_directory(root):
            continue
        seen.add(resolved)
        entries = sorted(root.iterdir(), key=lambda value: value.name)
        if len(entries) > max_search_entries:
            raise ReferenceMaterializationError(
                f"reference directory exceeds the {max_search_entries}-entry non-recursive search bound"
            )
        for candidate in entries:
            if not _is_plain_file(candidate):
                continue
            if candidate.stat().st_size != artifact["expected_size_bytes"]:
                continue
            if hmac.compare_digest(_sha256_file(candidate), artifact["sha256"]):
                return candidate.resolve()
    raise ReferenceMaterializationError(
        "registered reference file was not found; choose it explicitly, set "
        f"{REFERENCE_DIRECTORY_ENV}, or place it directly in {DEFAULT_REFERENCE_DIRECTORY}/"
    )


def materialize_reference_projection(
    source_path: str | Path,
    projection_id: str,
    *,
    registry: ReferenceArtifactRegistry | None = None,
    persist_member_to: str | Path | None = None,
) -> MaterializedReferenceProjection:
    """Verify, natively parse, and project one registered reference artifact.

    ``persist_member_to`` is for a managed workspace that must retain the
    admitted native source after deleting the selected archive.  The exact
    registered member is copied only after its native scientific projection
    has passed every authority check; a partial destination is removed on any
    copy failure.
    """

    active = registry or load_reference_artifact_registry()
    try:
        projection = active.projection(projection_id).as_dict()
        artifact = active.artifact(projection["artifact_id"]).as_dict()
    except ReferenceArtifactRegistryError as exc:
        raise ReferenceMaterializationError(str(exc)) from exc
    member = _member_for_projection(artifact, projection)

    with tempfile.TemporaryDirectory(prefix="spectra-reference-") as directory:
        private_root = Path(directory)
        snapshot = private_root / "selected-reference.zip"
        _snapshot_verified_artifact(Path(source_path), snapshot, artifact)
        member_path = private_root / "registered-member.mat"
        _extract_verified_member(snapshot, member_path, member)
        materialized = _materialize_verified_member(member_path, projection, artifact, member)
        if persist_member_to is not None:
            _persist_verified_member(member_path, Path(persist_member_to), member)
        return materialized


def materialize_reference_member(
    member_path: str | Path,
    projection_id: str,
    *,
    registry: ReferenceArtifactRegistry | None = None,
) -> MaterializedReferenceProjection:
    """Project one already-admitted exact native member from workspace custody."""

    active = registry or load_reference_artifact_registry()
    try:
        projection = active.projection(projection_id).as_dict()
        artifact = active.artifact(projection["artifact_id"]).as_dict()
    except ReferenceArtifactRegistryError as exc:
        raise ReferenceMaterializationError(str(exc)) from exc
    member = _member_for_projection(artifact, projection)
    path = Path(member_path)
    _verify_registered_member(path, member)
    return _materialize_verified_member(path, projection, artifact, member)


def _materialize_verified_member(
    member_path: Path,
    projection: Mapping[str, Any],
    artifact: Mapping[str, Any],
    member: Mapping[str, Any],
) -> MaterializedReferenceProjection:
    """Apply scientific authorities after exact member-byte admission."""

    contract = str(projection["native_reader_contract"])
    result = ingest(member_path)

    assets = {asset.asset_id: asset for asset in result.assets}
    object_name = projection["object_name"]
    target_object_name = projection["target_object_name"]
    if object_name not in assets or (target_object_name is not None and target_object_name not in assets):
        raise ReferenceMaterializationError(
            "registered reference does not expose its governed object(s) through the native reader"
        )
    source_dataset = assets[object_name].dataset
    spatial_dataset = None
    if projection["analysis"]["primary_role"] == "X_hsi":
        spatial_asset = assets.get(f"{object_name}:image-cube")
        if spatial_asset is not None:
            spatial_dataset = spatial_asset.dataset
    if contract == "spectrasherpa.matlab-process-log/1":
        if source_dataset.source_identity.source_format != "matlab-process-log":
            raise ReferenceMaterializationError("registered reference source object is not a native MATLAB process log")
        from spectra_sherpa.app.lib.process_log import wafer_time_average

        source_dataset = wafer_time_average(source_dataset)
    if (
        contract in {"spectrasherpa.matlab-dso/1", "spectrasherpa.matlab-source/1"}
        and source_dataset.source_identity.source_format != "eigenvector-dso"
    ):
        raise ReferenceMaterializationError("registered reference source object is not a native Eigenvector DSO")
    if target_object_name is None:
        return _finish_source_projection(
            source_dataset,
            projection,
            artifact,
            member,
            spatial_dataset=spatial_dataset,
        )

    target_dataset = assets[target_object_name].dataset
    if contract == "spectrasherpa.matlab-dso/1" and target_dataset.source_identity.source_format != "eigenvector-dso":
        raise ReferenceMaterializationError("registered reference target object is not a native Eigenvector DSO")

    data = np.asarray(source_dataset.X, dtype=np.float64)
    targets = np.asarray(target_dataset.X, dtype=np.float64)
    target_index = int(projection["target_index"])
    if data.shape != (projection["n_samples"], projection["n_features"]):
        raise ReferenceMaterializationError("registered reference source shape differs from its authority")
    if targets.ndim == 1:
        targets = targets.reshape(-1, 1)
    if targets.ndim == 2 and targets.shape[0] != data.shape[0] and targets.shape[1] == data.shape[0]:
        targets = targets.T
    if targets.ndim != 2 or targets.shape[0] != data.shape[0] or target_index >= targets.shape[1]:
        raise ReferenceMaterializationError("registered reference target projection is outside the native DSO")
    target = np.asarray(targets[:, target_index], dtype=np.float64)

    axis = source_dataset.get_feature_axis()
    if axis is None:
        raise ReferenceMaterializationError("registered reference is missing its native feature axis")
    axis_values = (
        np.asarray(axis.values, dtype=np.float64)
        if axis.values is not None
        else np.arange(data.shape[1], dtype=np.float64)
    )
    if axis.title not in (None, "Feature", projection["feature_axis_title"]) or axis.units not in (
        None,
        projection["feature_axis_units"],
    ):
        raise ReferenceMaterializationError("registered reference feature-axis semantics differ from its authority")
    if not hmac.compare_digest(feature_axis_values_digest(axis_values), projection["feature_axis_sha256"]):
        raise ReferenceMaterializationError("registered reference feature-axis values differ from its authority")
    if not hmac.compare_digest(public_dataset_digest(data, target), projection["scientific_sha256"]):
        raise ReferenceMaterializationError("registered reference scientific content differs from its authority")
    target_axis = target_dataset.get_feature_axis()
    if contract == "spectrasherpa.matlab-dso/1" and target_axis is not None and target_axis.labels is not None:
        if target_axis.labels[target_index].casefold() != projection["target_name"].casefold():
            raise ReferenceMaterializationError("registered reference target label differs from its authority")

    package_view = package_view_projection(str(projection["projection_id"]))
    effective_analysis = dict(projection["analysis"])
    if package_view is not None:
        annotation_table = package_view["annotation_table"]
        if annotation_table["object_name"] != target_object_name:
            raise ReferenceMaterializationError("reference package annotation object differs from its projection")
        fields = list(annotation_table["fields"])
        field_names = [str(field["name"]) for field in fields]
        if targets.shape != (int(annotation_table["n_rows"]), len(fields)):
            raise ReferenceMaterializationError("reference package annotation shape differs from its authority")
        if not hmac.compare_digest(
            reference_annotation_table_digest(targets, fields),
            str(annotation_table["values_sha256"]),
        ):
            raise ReferenceMaterializationError("reference package annotation values differ from their authority")
        target_axis = target_dataset.get_feature_axis()
        target_labels = [] if target_axis is None else [str(value) for value in target_axis.labels or []]
        # A plain MATLAB row vector has only generated numeric feature labels;
        # after its verified transpose those labels describe source positions,
        # not property identity. The closed registry field plus the exact
        # target-object name, shape, and annotation digest are its authority.
        if contract != "spectrasherpa.matlab-array-pair/1" and (
            not target_labels
            or [value.casefold() for value in target_labels] != [value.casefold() for value in field_names]
        ):
            raise ReferenceMaterializationError("reference package annotation labels differ from their authority")
        target = np.asarray(targets, dtype=np.float64)
        effective_analysis = _analysis_profile_for_package_view(projection, package_view)

    dataset = source_dataset.copy()
    axis_payload = axis.model_dump(mode="python")
    axis_payload.update(
        {
            "values": axis_values,
            "title": projection["feature_axis_title"],
            "units": projection["feature_axis_units"],
        }
    )
    dataset.feature_axis = _axis_for_analysis_profile(axis_payload, effective_analysis)
    dataset.target = target
    if package_view is None:
        dataset.target_context = TargetContext(
            target_type=projection["analysis"]["target_type"],
            target_name=projection["target_name"],
            target_names=[projection["target_name"]],
            target_units=projection["target_units"],
            selected_target=projection["target_name"],
        )
        sample_axis_payload = dataset.sample_axis.model_dump(mode="python") if dataset.sample_axis is not None else {}
        source_labels = clean_sample_labels(
            sample_axis_payload.get("labels"),
            data.shape[0],
            fallback_prefix=str(projection["projection_id"]),
        )
        # Native labels remain the most useful row names when they are exact
        # identifiers. Some scientific files legitimately repeat a class or
        # treatment label, however, so fall back to a stable projection-row
        # identity rather than letting supervised binding fail ambiguously.
        sample_ids = (
            source_labels
            if len(set(source_labels)) == len(source_labels)
            else [f"{projection['projection_id']}-{index + 1:03d}" for index in range(data.shape[0])]
        )
        sample_axis_payload.update(
            {
                # The exact, unique row identity is the sample authority.
                # Native/provider labels remain visible separately whenever
                # they are not suitable identifiers.
                "labels": sample_ids,
                "title": "Sample",
                "sample_table": {
                    "sample_id": sample_ids,
                    "source_label": source_labels,
                    str(projection["target_name"]): target.tolist(),
                },
            }
        )
        if projection["projection_id"] == "public-cgl-nir-lactate-v1":
            roles = _verified_cgl_partition_roles(data, targets, assets)
            sample_axis_payload["sample_table"]["analysis_role"] = roles
        dataset.sample_axis = SampleAxis.model_validate(sample_axis_payload)
    else:
        annotation_table = package_view["annotation_table"]
        fields = list(annotation_table["fields"])
        field_names = [str(field["name"]) for field in fields]
        field_types = {str(field["target_type"]) for field in fields}
        field_units = {field["units"] for field in fields}
        dataset.target_context = TargetContext(
            target_type=next(iter(field_types)) if len(field_types) == 1 else None,
            target_name=None,
            target_names=field_names,
            target_units=next(iter(field_units)) if len(field_units) == 1 else None,
            selected_target=None,
        )
        sample_axis_payload = dataset.sample_axis.model_dump(mode="python") if dataset.sample_axis is not None else {}
        specimen_ids = [f"{package_view['cohort']}-{index + 1:03d}" for index in range(data.shape[0])]
        sample_ids = [f"{package_view['view_id']}-{index + 1:03d}" for index in range(data.shape[0])]
        sample_axis_payload.update(
            {
                # One specimen appears once per instrument view.  Row labels
                # identify observations; specimen_id preserves the deliberate
                # cross-view pairing without creating duplicate observations.
                "labels": sample_ids,
                "title": "Specimen",
                "sample_table": {
                    "sample_id": sample_ids,
                    "specimen_id": specimen_ids,
                    "instrument": [package_view["instrument"]] * data.shape[0],
                    **{field["name"]: target[:, int(field["index"])].tolist() for field in fields},
                },
            }
        )
        if projection["projection_id"] == "public-cgl-nir-lactate-v1":
            sample_axis_payload["sample_table"]["analysis_role"] = _verified_cgl_partition_roles(
                data,
                targets,
                assets,
            )
        dataset.sample_axis = SampleAxis.model_validate(sample_axis_payload)
    dataset.title = projection["title"]
    _apply_analysis_profile(dataset, projection, analysis=effective_analysis)
    dataset.extra.update(
        {
            "reference.artifact_id": artifact["artifact_id"],
            "reference.artifact_sha256": artifact["sha256"],
            "reference.member_sha256": member["sha256"],
            "reference.projection_id": projection["projection_id"],
            "reference.provider": artifact["provider"],
            "reference.target_object_name": target_object_name,
            "reference.target_object_scientific_digest": target_dataset.scientific_digest,
        }
    )
    if package_view is not None:
        dataset.extra.update(
            {
                "reference.package_id": package_view["package_id"],
                "reference.view_id": package_view["view_id"],
                "reference.instrument_view": package_view["instrument"],
                "reference.cohort": package_view["cohort"],
                "reference.annotation_table_sha256": package_view["annotation_table"]["values_sha256"],
            }
        )
    # Re-admission of the same registered bytes must reproduce the same
    # scientific identity. This projection is identity-bearing, not an
    # observation of wall-clock time, so its provenance uses the contract's
    # empty timestamp rather than Provenance.append()'s current-time default.
    provenance = dataset.provenance.to_list()
    provenance.append(
        {
            "op_id": "import.registered_reference",
            "op_version": "1.0",
            "parameters": {
                "artifact_id": artifact["artifact_id"],
                "artifact_sha256": artifact["sha256"],
                "member_sha256": member["sha256"],
                "native_reader_contract": projection["native_reader_contract"],
                "projection_id": projection["projection_id"],
                "scientific_sha256": projection["scientific_sha256"],
                "target_object_name": target_object_name,
                "analysis_profile": effective_analysis,
                **({"dataset_package": package_view} if package_view is not None else {}),
            },
            "timestamp": "",
            "input_shape": list(dataset.shape),
            "output_shape": list(dataset.shape),
            "state_effects": ["annotations_bound"] if package_view is not None else ["target_bound"],
        }
    )
    dataset.provenance = Provenance.from_list(provenance)
    dataset = _bind_registered_reference_source(dataset, member)
    return MaterializedReferenceProjection(
        dataset=dataset,
        portable_reference=_portable_reference(projection, artifact, member),
    )


def _verified_cgl_partition_roles(
    complete_spectra: np.ndarray,
    complete_properties: np.ndarray,
    assets: Mapping[str, Any],
) -> list[str]:
    """Reconcile CGL's provider calibration/test arrays to the full row set.

    The four arrays are source annotations, not alternative Sherpa datasets.
    Exact spectrum-row identity and exact property-row identity are required;
    any duplicate, omission, overlap, or reordered target value refuses the
    annotation instead of guessing a partition.
    """

    required = {"Xcal", "Xtest", "Ycal", "Ytest"}
    if not required.issubset(assets):
        raise ReferenceMaterializationError("CGL provider partition arrays are incomplete")
    spectra = np.asarray(complete_spectra, dtype=np.float64)
    properties = np.asarray(complete_properties, dtype=np.float64)
    if spectra.ndim != 2 or properties.ndim != 2 or spectra.shape[0] != properties.shape[0]:
        raise ReferenceMaterializationError("CGL complete spectra and properties are misaligned")
    row_index: dict[bytes, int] = {}
    for index, row in enumerate(np.ascontiguousarray(spectra, dtype="<f8")):
        identity = row.tobytes()
        if identity in row_index:
            raise ReferenceMaterializationError("CGL complete spectra contain duplicate partition identities")
        row_index[identity] = index

    roles: list[str | None] = [None] * spectra.shape[0]
    for role, x_name, y_name in (
        ("calibration", "Xcal", "Ycal"),
        ("test", "Xtest", "Ytest"),
    ):
        subset = np.asarray(assets[x_name].dataset.X, dtype=np.float64)
        subset_properties = np.asarray(assets[y_name].dataset.X, dtype=np.float64)
        if subset.ndim != 2 or subset_properties.ndim != 2 or subset.shape[0] != subset_properties.shape[0]:
            raise ReferenceMaterializationError(f"CGL provider {role} arrays are misaligned")
        for subset_index, row in enumerate(np.ascontiguousarray(subset, dtype="<f8")):
            complete_index = row_index.get(row.tobytes())
            if complete_index is None or roles[complete_index] is not None:
                raise ReferenceMaterializationError(f"CGL provider {role} spectra do not form one exact partition")
            if not np.array_equal(
                properties[complete_index],
                subset_properties[subset_index],
                equal_nan=True,
            ):
                raise ReferenceMaterializationError(f"CGL provider {role} properties differ from the complete table")
            roles[complete_index] = role
    if any(role is None for role in roles):
        raise ReferenceMaterializationError("CGL provider partition does not cover every observation")
    return [str(role) for role in roles]


def _finish_source_projection(
    source_dataset: SherpaDataset,
    projection: Mapping[str, Any],
    artifact: Mapping[str, Any],
    member: Mapping[str, Any],
    *,
    spatial_dataset: SherpaDataset | None = None,
) -> MaterializedReferenceProjection:
    data = np.asarray(source_dataset.X, dtype=np.float64)
    if data.ndim != 2 or data.shape != (projection["n_samples"], projection["n_features"]):
        raise ReferenceMaterializationError("registered reference source shape differs from its authority")
    if not hmac.compare_digest(reference_source_projection_digest(data), projection["scientific_sha256"]):
        raise ReferenceMaterializationError("registered reference scientific content differs from its authority")
    axis = source_dataset.get_feature_axis()
    values = (
        np.asarray(axis.values, dtype=np.float64)
        if axis is not None and axis.values is not None
        else np.arange(data.shape[1], dtype=np.float64)
    )
    if not hmac.compare_digest(feature_axis_values_digest(values), projection["feature_axis_sha256"]):
        raise ReferenceMaterializationError("registered reference feature-axis values differ from its authority")

    dataset = source_dataset.copy()
    if spatial_dataset is not None:
        image_size = spatial_dataset.layout.image_size
        if (
            spatial_dataset.ndim != 3
            or image_size != tuple(spatial_dataset.shape[:2])
            or int(np.prod(spatial_dataset.shape[:2])) != data.shape[0]
            or spatial_dataset.shape[-1] != data.shape[1]
            or not np.array_equal(
                spatial_dataset.X.reshape(data.shape, order="F"),
                data,
                equal_nan=True,
            )
        ):
            raise ReferenceMaterializationError(
                "registered HSI cube does not exactly refold the governed unfolded source"
            )
        dataset = spatial_dataset.copy()
    axis_payload = axis.model_dump(mode="python") if axis is not None else {}
    axis_payload.update(
        {
            "values": values,
            "title": projection["feature_axis_title"],
            "units": projection["feature_axis_units"],
        }
    )
    if projection["projection_id"] == "public-metal-etch-oes-v1":
        axis_payload["labels"] = _metal_etch_oes_feature_labels(values)
    dataset.feature_axis = _axis_for_analysis_profile(axis_payload, projection["analysis"])
    dataset.title = projection["title"]
    package_view = package_view_projection(str(projection["projection_id"]))
    effective_analysis = dict(projection["analysis"])
    if package_view is not None:
        effective_analysis = _analysis_profile_for_package_view(projection, package_view)
        if spatial_dataset is None:
            sample_axis_payload = (
                dataset.sample_axis.model_dump(mode="python") if dataset.sample_axis is not None else {}
            )
            source_labels = clean_sample_labels(
                sample_axis_payload.get("labels"),
                data.shape[0],
                fallback_prefix="Sample",
            )
            sample_ids = [f"{package_view['view_id']}-{index + 1:03d}" for index in range(data.shape[0])]
            source_sample_table = sample_axis_payload.get("sample_table")
            sample_table = dict(source_sample_table) if isinstance(source_sample_table, Mapping) else {}
            sample_table.update(
                {
                    "sample_id": sample_ids,
                    "source_label": source_labels,
                    "instrument": [package_view["instrument"]] * data.shape[0],
                }
            )
            sample_axis_payload.update(
                {
                    "labels": sample_ids,
                    "title": "Observation",
                    "sample_table": sample_table,
                }
            )
            # A refolded HSI cube has two spatial modes rather than one
            # observation mode; flattened pixel IDs do not belong on either.
            dataset.sample_axis = SampleAxis.model_validate(sample_axis_payload)
    _apply_analysis_profile(dataset, projection, analysis=effective_analysis)
    dataset.extra.update(
        {
            "reference.artifact_id": artifact["artifact_id"],
            "reference.artifact_sha256": artifact["sha256"],
            "reference.member_sha256": member["sha256"],
            "reference.projection_id": projection["projection_id"],
            "reference.provider": artifact["provider"],
        }
    )
    if package_view is not None:
        dataset.extra.update(
            {
                "reference.package_id": package_view["package_id"],
                "reference.view_id": package_view["view_id"],
                "reference.instrument_view": package_view["instrument"],
                "reference.cohort": package_view["cohort"],
            }
        )
    provenance = dataset.provenance.to_list()
    provenance.append(
        {
            "op_id": "import.registered_reference",
            "op_version": "1.0",
            "parameters": {
                "artifact_id": artifact["artifact_id"],
                "artifact_sha256": artifact["sha256"],
                "member_sha256": member["sha256"],
                "native_reader_contract": projection["native_reader_contract"],
                "projection_id": projection["projection_id"],
                "scientific_sha256": projection["scientific_sha256"],
                "analysis_profile": effective_analysis,
                **({"dataset_package": package_view} if package_view is not None else {}),
            },
            "timestamp": "",
            "input_shape": list(dataset.shape),
            "output_shape": list(dataset.shape),
            "state_effects": ["data_view_bound"] if package_view is not None else [],
        }
    )
    dataset.provenance = Provenance.from_list(provenance)
    dataset = _bind_registered_reference_source(dataset, member)
    return MaterializedReferenceProjection(
        dataset=dataset,
        portable_reference=_portable_reference(projection, artifact, member),
    )


def _metal_etch_oes_feature_labels(values: np.ndarray) -> list[str]:
    """Give each repeated OES wavelength a unique, non-invented block identity."""

    axis = np.asarray(values, dtype=np.float64)
    if axis.ndim != 1 or axis.size % 3 != 0:
        raise ReferenceMaterializationError("Metal Etch OES axis does not contain three equal blocks")
    block_size = axis.size // 3
    blocks = axis.reshape(3, block_size)
    if not all(np.array_equal(blocks[0], block) for block in blocks[1:]):
        raise ReferenceMaterializationError("Metal Etch OES wavelength blocks do not reproduce")
    return [
        f"block_{block_index + 1}:wavelength_{format(float(value), '.17g')}_nm"
        for block_index, block in enumerate(blocks)
        for value in block
    ]


def _bind_registered_reference_source(
    dataset: SherpaDataset,
    member: Mapping[str, Any],
) -> SherpaDataset:
    """Issue direct SDK custody for one verified registered projection.

    Project and DAG loaders already derive this registered-reference identity
    after wrapping a materialized member in a collection. Direct SDK readers
    do not pass through those loaders, so issue the same path-free identity at
    the materialization boundary and bind an explicitly selected target.
    """

    sample_axis = dataset.sample_axis
    if sample_axis is None or not isinstance(sample_axis.sample_table, Mapping):
        return dataset
    try:
        source_manifest = source_collection_manifest(
            [
                {
                    "file_name": member["path"],
                    "size_bytes": member["expected_size_bytes"],
                    "sha256": member["sha256"],
                    "prepared_data_sha256": prepared_data_digest(None),
                }
            ]
        )
        identity = registered_reference_collection_identity(source_manifest, dataset)
        if identity is None:
            raise ValueError("registered reference sample-table authority is unavailable")
        dataset.meta["source_collection"] = {**source_manifest, **identity}

        context = dataset.target_context
        selected_target = context.selected_target
        target_type = context.target_type
        if selected_target is None:
            return dataset
        if target_type not in {"continuous", "categorical"}:
            raise ValueError("registered reference selected target has an unsupported type")

        from spectra_sherpa.app.services.dag.supervision_binding import bind_sample_table_supervision

        binding = bind_sample_table_supervision(
            dataset,
            target_column=selected_target,
            target_type=target_type,
        )
        if dataset.target is None or not np.array_equal(np.asarray(dataset.target), binding.target):
            raise ValueError("registered reference target differs from its sample-table authority")
        dataset.meta["supervision_binding"] = {
            **binding.record,
            "supervision_binding_sha256": binding.digest,
        }
        return dataset
    except (KeyError, TypeError, ValueError) as exc:
        raise ReferenceMaterializationError("registered reference could not issue direct sample-table custody") from exc


def _portable_reference(
    projection: Mapping[str, Any], artifact: Mapping[str, Any], member: Mapping[str, Any]
) -> dict[str, Any]:
    result = {
        "schema_version": PORTABLE_REFERENCE_SCHEMA,
        "projection_id": projection["projection_id"],
        "artifact_id": artifact["artifact_id"],
        "artifact_size_bytes": artifact["expected_size_bytes"],
        "artifact_sha256": artifact["sha256"],
        "member_path": member["path"],
        "member_size_bytes": member["expected_size_bytes"],
        "member_sha256": member["sha256"],
        "native_reader_contract": projection["native_reader_contract"],
        "scientific_sha256": projection["scientific_sha256"],
        "provider": artifact["provider"],
        "provider_page": artifact["provider_page"],
        "download_url": artifact["download_url"],
        "redistribution": artifact["redistribution"],
        "analysis_profile": projection["analysis"],
        "source_scope": _reference_source_scope(str(projection["projection_id"])),
    }
    package_view = package_view_projection(str(projection["projection_id"]))
    if package_view is not None:
        result["dataset_package"] = package_view
        result["analysis_profile"] = _analysis_profile_for_package_view(projection, package_view)
    return result


def _analysis_profile_for_package_view(
    projection: Mapping[str, Any], package_view: Mapping[str, Any]
) -> dict[str, Any]:
    annotation_table = package_view["annotation_table"]
    if annotation_table is None:
        if projection["analysis"]["primary_role"] == "X_hsi":
            # Image row/column coordinates, image_size, and image_include are
            # the pixel authority. A 3-D cube has no 1-D sample table with
            # one entry per unfolded pixel.
            return dict(projection["analysis"])
        return {
            **dict(projection["analysis"]),
            "identity_fields": ["sample_id", "instrument"],
            "group_fields": [],
        }
    fields = list(annotation_table["fields"])
    field_types = {str(field["target_type"]) for field in fields}
    repeated_specimen_authority = any(
        relation.get("relation_type") in {"same_specimens_aligned", "calibration_application_cohorts"}
        for relation in package_view.get("relations", [])
    )
    return {
        **dict(projection["analysis"]),
        "target_type": next(iter(field_types)) if len(field_types) == 1 else None,
        "target_fields": [str(field["name"]) for field in fields],
        "identity_fields": ["sample_id", "specimen_id", "instrument"],
        # A specimen identifier is always useful provenance, but it becomes a
        # grouped-validation authority only when the package declares an
        # aligned repeated-specimen relationship. Unaligned cohorts (Diesel)
        # must not offer one-group-per-row as if it prevented leakage.
        # `instrument` is offered alongside it for the same reason: an
        # instrument-held-out split is the scientist's transfer check. A single
        # selected view yields one level, which the consumer already declines.
        "group_fields": (["specimen_id", "instrument"] if repeated_specimen_authority else []),
    }


def _apply_analysis_profile(
    dataset: SherpaDataset,
    projection: Mapping[str, Any],
    *,
    analysis: Mapping[str, Any] | None = None,
) -> None:
    """Bind one closed profile and verify every materialized fact it claims."""

    analysis = dict(analysis or projection["analysis"])
    target_type = analysis["target_type"]
    target_fields = list(analysis["target_fields"])
    if target_type is None:
        if dataset.target is not None or target_fields:
            raise ReferenceMaterializationError("target-free analysis profile disagrees with materialized dataset")
    else:
        context = dataset.target_context
        if (
            dataset.target is None
            or context is None
            or context.target_type != target_type
            or list(context.target_names or []) != target_fields
        ):
            raise ReferenceMaterializationError("analysis target profile disagrees with materialized dataset")

    table = None if dataset.sample_axis is None else dataset.sample_axis.sample_table
    declared_sample_fields = list(analysis["identity_fields"]) + list(analysis["group_fields"])
    if declared_sample_fields:
        if not isinstance(table, dict):
            raise ReferenceMaterializationError("analysis sample fields are absent from the materialized dataset")
        for field in declared_sample_fields:
            values = table.get(field)
            if values is None or len(values) != dataset.shape[0] or any(value in (None, "") for value in values):
                raise ReferenceMaterializationError(
                    f"analysis sample field {field!r} is incomplete in the materialized dataset"
                )

    dataset.data_role = analysis["primary_role"]
    domain_payload = dataset.domain.model_dump(mode="python")
    domain_payload["technique"] = analysis["technique"]
    dataset.domain = DomainContext.model_validate(domain_payload)
    dataset.extra["analysis.profile"] = analysis


def _member_for_projection(artifact: Mapping[str, Any], projection: Mapping[str, Any]) -> dict[str, Any]:
    matches = [member for member in artifact["members"] if member["path"] == projection["member_path"]]
    if len(matches) != 1:
        raise ReferenceMaterializationError("reference projection does not resolve one exact registered member")
    return dict(matches[0])


def _snapshot_verified_artifact(source: Path, destination: Path, artifact: Mapping[str, Any]) -> None:
    if not _is_plain_file(source):
        raise ReferenceMaterializationError("selected reference must be one regular, non-symlink file")
    if source.stat().st_size != artifact["expected_size_bytes"]:
        raise ReferenceMaterializationError("selected file does not match the registered reference size")
    digest = hashlib.sha256()
    size = 0
    with source.open("rb") as reader, destination.open("xb") as writer:
        while chunk := reader.read(_CHUNK_BYTES):
            size += len(chunk)
            digest.update(chunk)
            writer.write(chunk)
    if size != artifact["expected_size_bytes"] or not hmac.compare_digest(digest.hexdigest(), artifact["sha256"]):
        destination.unlink(missing_ok=True)
        raise ReferenceMaterializationError(
            "selected file does not match the registered reference SHA-256; no selected bytes were retained"
        )


def _extract_verified_member(archive_path: Path, destination: Path, member: Mapping[str, Any]) -> None:
    try:
        with zipfile.ZipFile(archive_path) as archive:
            matches = [info for info in archive.infolist() if info.filename == member["path"]]
            if len(matches) != 1:
                raise ReferenceMaterializationError("verified archive does not contain one exact registered member")
            info = matches[0]
            if info.is_dir() or info.file_size != member["expected_size_bytes"]:
                raise ReferenceMaterializationError("registered archive member size differs from its authority")
            digest = hashlib.sha256()
            size = 0
            with archive.open(info) as reader, destination.open("xb") as writer:
                while chunk := reader.read(_CHUNK_BYTES):
                    size += len(chunk)
                    digest.update(chunk)
                    writer.write(chunk)
    except (OSError, zipfile.BadZipFile, RuntimeError) as exc:
        raise ReferenceMaterializationError("registered reference archive is unreadable") from exc
    if size != member["expected_size_bytes"] or not hmac.compare_digest(digest.hexdigest(), member["sha256"]):
        destination.unlink(missing_ok=True)
        raise ReferenceMaterializationError("registered archive member digest differs from its authority")


def _verify_registered_member(path: Path, member: Mapping[str, Any]) -> None:
    if not _is_plain_file(path):
        raise ReferenceMaterializationError("registered reference member must be one regular, non-symlink file")
    if path.stat().st_size != member["expected_size_bytes"]:
        raise ReferenceMaterializationError("registered reference member size differs from its authority")
    if not hmac.compare_digest(_sha256_file(path), member["sha256"]):
        raise ReferenceMaterializationError("registered reference member digest differs from its authority")


def _persist_verified_member(source: Path, destination: Path, member: Mapping[str, Any]) -> None:
    if destination.exists() or destination.is_symlink():
        raise ReferenceMaterializationError("registered reference workspace destination already exists")
    if not _is_plain_directory(destination.parent):
        raise ReferenceMaterializationError("registered reference workspace directory is unavailable")
    try:
        with source.open("rb") as reader, destination.open("xb") as writer:
            shutil.copyfileobj(reader, writer, length=_CHUNK_BYTES)
        os.chmod(destination, 0o600)
        _verify_registered_member(destination, member)
    except BaseException:
        destination.unlink(missing_ok=True)
        raise


def _verify_regular_file(path: Path, artifact: Mapping[str, Any]) -> None:
    if not _is_plain_file(path):
        raise ReferenceMaterializationError("selected reference must be one regular, non-symlink file")
    if path.stat().st_size != artifact["expected_size_bytes"]:
        raise ReferenceMaterializationError("selected file does not match the registered reference size")
    if not hmac.compare_digest(_sha256_file(path), artifact["sha256"]):
        raise ReferenceMaterializationError("selected file does not match the registered reference SHA-256")


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(_CHUNK_BYTES), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _is_plain_file(path: Path) -> bool:
    try:
        return stat.S_ISREG(path.lstat().st_mode) and not path.is_symlink()
    except OSError:
        return False


def _is_plain_directory(path: Path) -> bool:
    try:
        return stat.S_ISDIR(path.lstat().st_mode) and not path.is_symlink()
    except OSError:
        return False


__all__ = [
    "DEFAULT_REFERENCE_DIRECTORY",
    "MAX_SEARCH_ENTRIES",
    "PORTABLE_REFERENCE_SCHEMA",
    "REFERENCE_DIRECTORY_ENV",
    "MaterializedReferenceProjection",
    "ReferenceMaterializationError",
    "materialize_reference_member",
    "materialize_reference_projection",
    "portable_reference_manifest",
    "reference_source_projection_digest",
    "resolve_reference_artifact",
]
