"""Install one canonical PLS-DA full refit as an explicitly identified saved model.

The canonical executor and the Workbench ModelStore are two custody adapters
over the same native :class:`SherpaPLSDAArtifact`.  This module performs the
only admitted conversion.  It never fits, refits, or reimplements prediction.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import Awaitable, Callable
from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Mapping

import numpy as np

from spectra_sherpa.app.lib.sherpa_dataset import SherpaDataset
from spectra_sherpa.app.services.artifact_preprocessing_authority import (
    validate_experiment_source_provenance,
    validate_variable_selection_provenance,
)
from spectra_sherpa.app.services.dag.nodes.classification.plsda_state import (
    CANONICAL_MODEL_ORIGIN,
    FITTED_STATE_SERIALIZER,
    OUTPUT_SEMANTICS,
    SherpaPLSDAArtifact,
)
from spectra_sherpa.app.services.dag.spectral_capability import (
    SpectralCapabilityError,
    SpectralDatasetCapability,
)
from spectra_sherpa.app.services.dag.supervision_binding import (
    bind_sample_table_supervision,
    validate_bound_sample_table_supervision,
)
from spectra_sherpa.app.services.dag.validation_graph import validation_graph_from_dict
from spectra_sherpa.core.axis_semantics import axis_semantics
from spectra_sherpa.core.model_artifact import CANONICAL_MODEL_ARTIFACT_AUTHORITY
from spectra_sherpa.core.target_authority import TargetAuthority, admit_target_authority
from spectra_sherpa.sdk.canonical_execution_evidence import (
    CanonicalExecutionEvidenceError,
    validate_canonical_validation_execution,
)
from spectra_sherpa.sdk.canonical_fitted_artifact import CanonicalFittedArtifact

CANONICAL_TRAINING_LINEAGE_SCHEMA = "spectrasherpa.canonical-training-lineage/1"
MAX_CANONICAL_LINEAGE_BYTES = 4 * 1024 * 1024
_CANONICAL_MODEL_BASE_FIELDS = {
    "artifact_authority",
    "model_type",
    "serializer",
    "algorithm_id",
    "algorithm_version",
    "requested_n_components",
    "effective_n_components",
    "scale",
    "classes",
    "decision_rule",
    "output_semantics",
    "features",
    "feature_identity",
    "node_id",
    "n_features",
    "n_components",
    "feature_axis",
    "feature_axis_title",
    "feature_axis_quantity",
    "feature_axis_units",
    "feature_mask",
    "training_data_hash",
    "preprocessing_chain",
    "classification_output_semantics",
    "artifact_origin",
    "canonical_training_lineage",
}


def _application_model_artifact_replay() -> Any:
    """Load the Workbench replay adapter only at the application boundary.

    Registry discovery and the R1/R2 scientific-core profile must remain free
    of application configuration, database, and web-service dependencies.
    Canonical bridge validation calls this helper only inside a configured
    Workbench process.
    """

    from spectra_sherpa.app.services.execution_runtime import ApplicationModelArtifactReplay

    return ApplicationModelArtifactReplay()


_MODELSTORE_IDENTITY_FIELDS = {"arrays", "integrity_hash", "artifact_uid"}


class CanonicalModelBridgeError(ValueError):
    """Canonical and Workbench artifact authorities contradict each other."""


def _binding_target_authority(binding: Mapping[str, Any]) -> TargetAuthority:
    """Admit the one inseparable target identity carried by a binding."""

    try:
        authority = admit_target_authority(binding.get("target_authority"), optional=False)
    except ValueError as exc:
        raise CanonicalModelBridgeError("canonical supervision has no valid target authority") from exc
    assert authority is not None
    return authority


@dataclass(frozen=True)
class CanonicalPLSDABridge:
    """Verified ModelStore payload and bounded origin receipt."""

    manifest: dict[str, Any]
    arrays: dict[str, np.ndarray]
    receipt: dict[str, Any]


async def persist_canonical_plsda_bridge(
    session: Any,
    *,
    user_id: int,
    project_id: int,
    training_dataset_id: int,
    bridge: CanonicalPLSDABridge,
    re_admit_training_dataset: Callable[[], Awaitable[SherpaDataset]],
    display_name: str | None = None,
) -> tuple[Any, dict[str, Any]]:
    """Atomically publish one verified bridge under a fresh storage identity."""

    from sqlalchemy import select

    from spectra_sherpa.app.models.model_artifact import ModelArtifact
    from spectra_sherpa.app.services.audit import audit_emitter
    from spectra_sherpa.app.services.model_store import ModelArtifactCollisionError, get_model_store

    if not isinstance(bridge, CanonicalPLSDABridge) or not callable(re_admit_training_dataset):
        raise CanonicalModelBridgeError("canonical bridge receipt is unavailable")
    validate_canonical_plsda_model_artifact(
        bridge.manifest,
        bridge.arrays,
        expected_training_dataset_id=training_dataset_id,
    )
    store = get_model_store()
    artifact_uid: str | None = None
    integrity_hash: str | None = None
    manifest: dict[str, Any] | None = None
    arrays = {name: np.array(value, copy=True) for name, value in bridge.arrays.items()}
    published = False
    for _attempt in range(8):
        candidate = str(uuid.uuid4())
        exists = await session.scalar(select(ModelArtifact.id).where(ModelArtifact.artifact_uid == candidate))
        if exists is not None:
            continue
        candidate_manifest = deepcopy(bridge.manifest)
        try:
            candidate_integrity = store.save_new(candidate, candidate_manifest, arrays)
        except ModelArtifactCollisionError:
            continue
        artifact_uid = candidate
        integrity_hash = candidate_integrity
        manifest = candidate_manifest
        published = True
        break
    if artifact_uid is None or integrity_hash is None or manifest is None:
        raise CanonicalModelBridgeError("could not allocate a fresh model artifact identity")
    try:
        stored_manifest, stored_arrays = store.load(artifact_uid, verify=True)
        fresh_training_dataset = await re_admit_training_dataset()
        lineage = validate_canonical_plsda_model_artifact(
            stored_manifest,
            stored_arrays,
            training_dataset=fresh_training_dataset,
            expected_training_dataset_id=training_dataset_id,
        )
        if stored_manifest.get("integrity_hash") != integrity_hash:
            raise CanonicalModelBridgeError("stored canonical bridge integrity is inconsistent")
        default_name = f"Imported canonical PLS-DA — {artifact_uid[:8]}"
        row = ModelArtifact(
            artifact_uid=artifact_uid,
            user_id=user_id,
            project_id=project_id,
            workflow_id=None,
            workflow_version_id=None,
            source_run_id=None,
            training_dataset_id=training_dataset_id,
            node_id=str(stored_manifest["node_id"]),
            model_type="plsda",
            name=default_name,
            display_name=display_name or default_name,
            description=(
                "Imported canonical full-refit application artifact; linked validation evidence is not "
                "full-refit or in-sample performance."
            ),
            artifact_dir=store.artifact_directory(artifact_uid),
            integrity_hash=integrity_hash,
            n_features=int(stored_manifest["n_features"]),
            n_components=int(stored_manifest["n_components"]),
            classes_json=json.dumps(stored_manifest["classes"], separators=(",", ":")),
            feature_axis_json=json.dumps(stored_manifest["feature_axis"], separators=(",", ":")),
            metrics_json=None,
            training_data_hash=str(stored_manifest["training_data_hash"]),
            preprocessing_summary=json.dumps(stored_manifest["preprocessing_chain"], separators=(",", ":")),
            artifact_origin=CANONICAL_MODEL_ORIGIN,
            canonical_lineage_digest=str(lineage["lineage_digest"]),
            validation_evidence_digest=str(lineage["validation_execution_digest"]),
            tags=["canonical-full-refit", "application-artifact"],
            is_deploy_ready=False,
        )
        session.add(row)
        audit_emitter.emit(
            session=session,
            action="model_artifact.canonical_full_refit_imported",
            target_type="ModelArtifact",
            target_id=artifact_uid,
            after={
                "artifact_uid": artifact_uid,
                "user_id": user_id,
                "project_id": project_id,
                "training_dataset_id": training_dataset_id,
                "model_type": "plsda",
                "artifact_origin": CANONICAL_MODEL_ORIGIN,
                "canonical_lineage_digest": lineage["lineage_digest"],
                "validation_evidence_digest": lineage["validation_execution_digest"],
                "integrity_hash": integrity_hash,
            },
        )
        await session.commit()
    except Exception:
        await session.rollback()
        if published:
            store.delete(artifact_uid)
        raise
    receipt = {
        **deepcopy(bridge.receipt),
        "artifact_uid": artifact_uid,
        "storage_integrity_sha256": integrity_hash,
        "project_id": project_id,
        "training_dataset_id": training_dataset_id,
        "verified_after_storage": True,
    }
    return row, receipt


def bridge_canonical_plsda_artifact(
    artifact: CanonicalFittedArtifact,
    *,
    graph_payload: Mapping[str, Any],
    training_dataset: SherpaDataset,
    experiment_id: int,
    asset_id: str,
    validation_execution: Mapping[str, Any],
    original_capability_metadata: Mapping[str, Any],
    custody_id: str,
    feature_mask: object,
    selection_report: Mapping[str, Any],
) -> CanonicalPLSDABridge:
    """Convert one verified canonical PLS-DA state without fitting it again."""

    if not isinstance(artifact, CanonicalFittedArtifact):
        raise CanonicalModelBridgeError("canonical model bridge requires a verified fitted artifact")
    if not isinstance(asset_id, str) or not asset_id or len(asset_id) > 255:
        raise CanonicalModelBridgeError("canonical model bridge requires an exact training asset")
    graph = validation_graph_from_dict(graph_payload)
    if graph.digest != _full_refit(artifact)["graph_digest"]:
        raise CanonicalModelBridgeError("canonical graph differs from the full-refit authority")
    model_nodes = [node for node in graph.nodes if node.operation_id == "classification.plsda"]
    if len(model_nodes) != 1:
        raise CanonicalModelBridgeError("canonical bridge requires exactly one PLS-DA model node")
    model_node = model_nodes[0]

    state_reference, state_bytes = _canonical_state_authority(artifact, model_node.node_id)
    try:
        state = _parse_canonical_mapping(state_bytes, "canonical PLS-DA state")
        native = SherpaPLSDAArtifact.from_fitted_state(state)
    except ValueError as exc:
        raise CanonicalModelBridgeError("canonical fitted state is not the native PLS-DA authority") from exc
    rebuilt_state = _canonical_json(native.to_fitted_state())
    if rebuilt_state != state_bytes:
        raise CanonicalModelBridgeError("canonical PLS-DA state does not round-trip losslessly")
    native_metadata, native_arrays = native.to_artifact()

    binding_record = training_dataset.meta.get("supervision_binding")
    if not isinstance(binding_record, Mapping):
        raise CanonicalModelBridgeError("canonical training dataset has no supervision binding")
    try:
        target_authority = _binding_target_authority(binding_record)
        rebound = bind_sample_table_supervision(
            training_dataset,
            target_column=target_authority.column,
            target_type=target_authority.target_type,
            group_column=binding_record.get("group_column"),
            target_authority=target_authority,
        )
        validate_bound_sample_table_supervision(
            training_dataset,
            binding_record=binding_record,
            dataset_ref_digest=rebound.digest,
            groups=rebound.groups,
        )
    except ValueError as exc:
        raise CanonicalModelBridgeError("canonical training supervision cannot be re-admitted") from exc
    if binding_record.get("supervision_binding_sha256") != rebound.digest:
        raise CanonicalModelBridgeError("canonical supervision identity is stale")
    refit = _full_refit(artifact)
    try:
        validation, validation_digest = validate_canonical_validation_execution(validation_execution)
    except CanonicalExecutionEvidenceError as exc:
        raise CanonicalModelBridgeError("canonical validation execution is invalid") from exc
    if (
        validation_digest != refit["validation_execution_digest"]
        or validation["graph_digest"] != graph.digest
        or validation["capability_content_digest"] != refit["capability_content_digest"]
        or validation["capability_envelope_digest"] != refit["capability_envelope_digest"]
        or validation["task_type"] != "classification"
        or validation["model_operation_id"] != "classification.plsda"
    ):
        raise CanonicalModelBridgeError("canonical validation execution differs from the full refit")
    split_plan_digest = validation["split_plan_digest"]
    if not isinstance(custody_id, str) or not custody_id:
        raise CanonicalModelBridgeError("canonical capability custody is malformed")
    capability = SpectralDatasetCapability.from_dataset(
        training_dataset,
        custody_id=custody_id,
        dataset_ref_digest=rebound.digest,
        split_plan_digest=split_plan_digest,
        groups=rebound.groups,
    )
    original_capability = _authenticate_original_capability(
        capability,
        original_capability_metadata,
        expected_content_digest=refit["capability_content_digest"],
        expected_envelope_digest=refit["capability_envelope_digest"],
    )
    portable_content_digest, portable_envelope_digest = _portable_capability_digests(original_capability)
    if _portable_capability_digests(capability) != (portable_content_digest, portable_envelope_digest):
        raise CanonicalModelBridgeError("live training capability differs from the authenticated refit capability")

    mask = _strict_mask(feature_mask, features=training_dataset.shape[1])
    selected_dataset = _selected_dataset(training_dataset, mask)
    source_record = {**_dataset_record(training_dataset), "asset_id": asset_id}
    selection_record = _selection_record(
        training_dataset,
        selected_dataset,
        mask=mask,
        report=selection_report,
        graph_selection_parameters=_selection_parameters(graph),
        asset_id=asset_id,
    )
    if native.features != selected_dataset.shape[1]:
        raise CanonicalModelBridgeError("canonical PLS-DA state differs from the selected feature count")

    artifact_manifest = artifact.as_dict()
    state_member = next(item for item in artifact_manifest["state_members"] if item["node_id"] == model_node.node_id)
    lineage_unsigned = {
        "schema_version": CANONICAL_TRAINING_LINEAGE_SCHEMA,
        "origin": CANONICAL_MODEL_ORIGIN,
        "canonical_artifact_manifest": artifact_manifest,
        "canonical_artifact_digest": artifact.artifact_digest,
        "canonical_state_node_id": model_node.node_id,
        "application_state_digest": state_reference["state_digest"],
        "canonical_state_content_digest": state_member["state_content_digest"],
        "canonical_state_contract_digest": state_reference["contract_digest"],
        "full_refit_evidence_digest": artifact_manifest["full_refit_evidence"]["content_digest"],
        "full_refit_execution_digest": artifact_manifest["full_refit_evidence"]["full_refit_execution_digest"],
        "validation_execution_digest": refit["validation_execution_digest"],
        "validation_execution": validation,
        "graph": graph.as_dict(),
        "supervision_binding": deepcopy(dict(binding_record)),
        "supervision_binding_sha256": rebound.digest,
        "supervision_attachment_node_id": _supervision_attachment_node_id(training_dataset),
        "split_plan_sha256": split_plan_digest,
        "capability": {
            "schema_version": "spectrasherpa.portable-training-capability/2",
            "original_content_digest": refit["capability_content_digest"],
            "original_envelope_digest": refit["capability_envelope_digest"],
            "original_metadata": _plain_json(original_capability.metadata),
            "custody_id": custody_id,
            "portable_content_digest": portable_content_digest,
            "portable_envelope_digest": portable_envelope_digest,
        },
        "source_dataset": source_record,
        "selection": selection_record,
    }
    lineage = {**lineage_unsigned, "lineage_digest": _digest(lineage_unsigned)}
    _require_lineage_size(lineage)

    manifest: dict[str, Any] = {
        **native_metadata,
        "artifact_authority": CANONICAL_MODEL_ARTIFACT_AUTHORITY,
        "model_type": "plsda",
        "node_id": model_node.node_id,
        "n_features": native.features,
        "n_components": native.effective_n_components,
        "classes": list(native.classes),
        "feature_axis": selection_record["selected_feature_axis_values"],
        "feature_axis_title": selection_record["feature_axis_title"],
        "feature_axis_quantity": selection_record["feature_axis_quantity"],
        "feature_axis_units": selection_record["feature_axis_units"],
        "feature_mask": mask.tolist(),
        "training_data_hash": selection_record["training_data_hash"],
        "preprocessing_chain": [
            _experiment_source_step(training_dataset, experiment_id=experiment_id, asset_id=asset_id),
            {
                "op_id": "selection.variable_select",
                "parameters": {
                    "selection_report": deepcopy(dict(selection_report)),
                    "feature_mask": mask.tolist(),
                },
            },
        ],
        "classification_output_semantics": OUTPUT_SEMANTICS,
        "artifact_origin": CANONICAL_MODEL_ORIGIN,
        "canonical_training_lineage": lineage,
    }
    arrays = {name: np.array(value, copy=True) for name, value in native_arrays.items()}
    validate_canonical_plsda_model_artifact(
        manifest,
        arrays,
        training_dataset=training_dataset,
        expected_training_dataset_id=experiment_id,
    )
    receipt = {
        "schema_version": "spectrasherpa.canonical-model-bridge-receipt/1",
        "origin": CANONICAL_MODEL_ORIGIN,
        "model_type": "plsda",
        "canonical_artifact_digest": artifact.artifact_digest,
        "canonical_state_digest": state_reference["state_digest"],
        "canonical_state_content_digest": state_member["state_content_digest"],
        "canonical_state_contract_digest": state_reference["contract_digest"],
        "validation_execution_digest": refit["validation_execution_digest"],
        "full_refit_execution_digest": artifact_manifest["full_refit_evidence"]["full_refit_execution_digest"],
        "lineage_digest": lineage["lineage_digest"],
        "response_semantics": OUTPUT_SEMANTICS,
        "validation_role": "linked_held_out_validation_evidence_not_full_refit_performance",
    }
    return CanonicalPLSDABridge(manifest, arrays, receipt)


def validate_canonical_plsda_model_artifact(
    manifest: Mapping[str, Any],
    arrays: Mapping[str, Any],
    *,
    training_dataset: SherpaDataset | None = None,
    expected_training_dataset_id: int | None = None,
) -> dict[str, Any]:
    """Re-admit a bridged artifact at load, inspection, export, and import."""

    observed_manifest_fields = frozenset(manifest)
    if observed_manifest_fields not in {
        frozenset(_CANONICAL_MODEL_BASE_FIELDS),
        frozenset(_CANONICAL_MODEL_BASE_FIELDS | _MODELSTORE_IDENTITY_FIELDS),
    }:
        raise CanonicalModelBridgeError("canonical ModelStore manifest fields are closed")

    lineage_value = manifest.get("canonical_training_lineage")
    if (
        manifest.get("artifact_authority") != CANONICAL_MODEL_ARTIFACT_AUTHORITY
        or manifest.get("artifact_origin") != CANONICAL_MODEL_ORIGIN
        or not isinstance(lineage_value, Mapping)
    ):
        raise CanonicalModelBridgeError("model is not an imported canonical full-refit artifact")
    lineage = deepcopy(dict(lineage_value))
    expected_lineage_fields = {
        "schema_version",
        "origin",
        "canonical_artifact_manifest",
        "canonical_artifact_digest",
        "canonical_state_node_id",
        "application_state_digest",
        "canonical_state_content_digest",
        "canonical_state_contract_digest",
        "full_refit_evidence_digest",
        "full_refit_execution_digest",
        "validation_execution_digest",
        "validation_execution",
        "graph",
        "supervision_binding",
        "supervision_binding_sha256",
        "supervision_attachment_node_id",
        "split_plan_sha256",
        "capability",
        "source_dataset",
        "selection",
        "lineage_digest",
    }
    if set(lineage) != expected_lineage_fields:
        raise CanonicalModelBridgeError("canonical training lineage fields are closed")
    if lineage["schema_version"] != CANONICAL_TRAINING_LINEAGE_SCHEMA or lineage["origin"] != CANONICAL_MODEL_ORIGIN:
        raise CanonicalModelBridgeError("canonical training lineage schema is unsupported")
    _require_node_id(lineage["supervision_attachment_node_id"])
    unsigned = {key: value for key, value in lineage.items() if key != "lineage_digest"}
    if lineage["lineage_digest"] != _digest(unsigned):
        raise CanonicalModelBridgeError("canonical training lineage digest is stale")
    _require_lineage_size(lineage)

    try:
        graph = validation_graph_from_dict(_mapping(lineage["graph"], "canonical graph"))
        artifact_manifest = _mapping(lineage["canonical_artifact_manifest"], "canonical artifact manifest")
        model_node_id = lineage["canonical_state_node_id"]
        if not isinstance(model_node_id, str):
            raise CanonicalModelBridgeError("canonical state node is malformed")
        native = SherpaPLSDAArtifact.from_artifact(dict(manifest), dict(arrays))
        state_bytes = _canonical_json(native.to_fitted_state())
        canonical = CanonicalFittedArtifact.from_serialized(
            _canonical_json(artifact_manifest),
            {model_node_id: state_bytes},
        )
    except (ValueError, TypeError) as exc:
        if isinstance(exc, CanonicalModelBridgeError):
            raise
        raise CanonicalModelBridgeError("canonical ModelStore state cannot reproduce its source artifact") from exc
    refit = _full_refit(canonical)
    state_reference, _ = _canonical_state_authority(canonical, model_node_id)
    state_member = next(item for item in canonical.payload["state_members"] if item["node_id"] == model_node_id)
    capability = _mapping(lineage["capability"], "canonical capability")
    if (
        set(capability)
        != {
            "schema_version",
            "original_content_digest",
            "original_envelope_digest",
            "original_metadata",
            "custody_id",
            "portable_content_digest",
            "portable_envelope_digest",
        }
        or capability.get("schema_version") != "spectrasherpa.portable-training-capability/2"
    ):
        raise CanonicalModelBridgeError("canonical capability identity is malformed")
    try:
        validation, validation_digest = validate_canonical_validation_execution(lineage["validation_execution"])
    except CanonicalExecutionEvidenceError as exc:
        raise CanonicalModelBridgeError("canonical validation execution is invalid") from exc
    expected_equalities = {
        "canonical_artifact_digest": canonical.artifact_digest,
        "application_state_digest": state_reference["state_digest"],
        "canonical_state_content_digest": state_member["state_content_digest"],
        "canonical_state_contract_digest": state_reference["contract_digest"],
        "full_refit_evidence_digest": canonical.payload["full_refit_evidence"]["content_digest"],
        "full_refit_execution_digest": canonical.payload["full_refit_evidence"]["full_refit_execution_digest"],
        "validation_execution_digest": refit["validation_execution_digest"],
    }
    if any(lineage[key] != value for key, value in expected_equalities.items()):
        raise CanonicalModelBridgeError("canonical training lineage contradicts its fitted artifact")
    if (
        graph.digest != refit["graph_digest"]
        or validation_digest != refit["validation_execution_digest"]
        or validation["graph_digest"] != graph.digest
        or validation["capability_content_digest"] != refit["capability_content_digest"]
        or validation["capability_envelope_digest"] != refit["capability_envelope_digest"]
        or validation["split_plan_digest"] != lineage["split_plan_sha256"]
        or validation["task_type"] != "classification"
        or validation["model_operation_id"] != "classification.plsda"
        or capability.get("original_content_digest") != refit["capability_content_digest"]
        or capability.get("original_envelope_digest") != refit["capability_envelope_digest"]
    ):
        raise CanonicalModelBridgeError("canonical graph, validation, or capability differs from the full refit")

    selection = _mapping(lineage["selection"], "canonical selection")
    _validate_selection_record(
        selection,
        manifest=manifest,
        native=native,
        graph_selection_parameters=_selection_parameters(graph),
    )
    source_record = _mapping(lineage["source_dataset"], "canonical source dataset")
    if source_record.get("asset_id") != _manifest_training_asset(manifest):
        raise CanonicalModelBridgeError("canonical training asset differs from its preprocessing authority")
    _validate_preprocessing_chain(
        manifest,
        lineage=lineage,
        source_dataset=training_dataset,
        expected_training_dataset_id=expected_training_dataset_id,
    )
    if training_dataset is not None:
        _validate_training_dataset(lineage, training_dataset, manifest=manifest)
    return lineage


def _validate_training_dataset(
    lineage: Mapping[str, Any],
    dataset: SherpaDataset,
    *,
    manifest: Mapping[str, Any],
) -> None:
    if {**_dataset_record(dataset), "asset_id": _manifest_training_asset(manifest)} != lineage["source_dataset"]:
        raise CanonicalModelBridgeError("live training dataset differs from canonical lineage")
    binding = _mapping(lineage["supervision_binding"], "supervision binding")
    target_authority = _binding_target_authority(binding)
    rebound = bind_sample_table_supervision(
        dataset,
        target_column=target_authority.column,
        target_type=target_authority.target_type,
        group_column=binding.get("group_column"),
        target_authority=target_authority,
    )
    validate_bound_sample_table_supervision(
        dataset,
        binding_record=binding,
        dataset_ref_digest=rebound.digest,
        groups=rebound.groups,
    )
    capability_record = _mapping(lineage["capability"], "canonical capability")
    if _supervision_attachment_node_id(dataset) != lineage["supervision_attachment_node_id"]:
        raise CanonicalModelBridgeError("live supervision attachment differs from canonical lineage")
    capability = SpectralDatasetCapability.from_dataset(
        dataset,
        custody_id=capability_record["custody_id"],
        dataset_ref_digest=rebound.digest,
        split_plan_digest=lineage["split_plan_sha256"],
        groups=rebound.groups,
    )
    original_capability = _authenticate_original_capability(
        capability,
        _mapping(capability_record["original_metadata"], "original capability metadata"),
        expected_content_digest=capability_record["original_content_digest"],
        expected_envelope_digest=capability_record["original_envelope_digest"],
    )
    portable_content, portable_envelope = _portable_capability_digests(capability)
    if (
        rebound.digest != lineage["supervision_binding_sha256"]
        or portable_content != capability_record["portable_content_digest"]
        or portable_envelope != capability_record["portable_envelope_digest"]
        or _portable_capability_digests(original_capability) != (portable_content, portable_envelope)
    ):
        raise CanonicalModelBridgeError("live training capability differs from canonical lineage")
    replay = _application_model_artifact_replay()
    selected, _warnings = replay.prepare(dataset.X, dataset, dict(manifest))
    record = _mapping(lineage["selection"], "canonical selection")
    if _array_digest(selected) != record["selected_values_sha256"]:
        raise CanonicalModelBridgeError("live selected matrix differs from canonical lineage")


def _validate_selection_record(
    record: Mapping[str, Any],
    *,
    manifest: Mapping[str, Any],
    native: SherpaPLSDAArtifact,
    graph_selection_parameters: Mapping[str, Any],
) -> None:
    fields = {
        "selection_report",
        "feature_mask",
        "feature_mask_sha256",
        "source_shape",
        "source_values_sha256",
        "source_feature_axis_sha256",
        "selected_shape",
        "selected_dtype",
        "selected_values_sha256",
        "selected_feature_axis_values",
        "selected_feature_axis_sha256",
        "feature_axis_type",
        "feature_axis_title",
        "feature_axis_quantity",
        "feature_axis_units",
        "training_data_hash",
    }
    if set(record) != fields:
        raise CanonicalModelBridgeError("canonical selection fields are closed")
    selection_report = _mapping(record["selection_report"], "canonical selection report")
    mask = _strict_mask(record["feature_mask"], features=int(record["source_shape"][1]))
    top_mask = _strict_mask(manifest.get("feature_mask"), features=mask.size)
    if (
        record["feature_mask_sha256"] != _bool_digest(mask)
        or record["selected_shape"] != [int(record["source_shape"][0]), int(mask.sum())]
        or record["selected_shape"][1] != native.features
        or not np.array_equal(top_mask, mask)
        or manifest.get("feature_axis") != record["selected_feature_axis_values"]
        or manifest.get("feature_axis_title") != record["feature_axis_title"]
        or manifest.get("feature_axis_quantity") != record["feature_axis_quantity"]
        or manifest.get("feature_axis_units") != record["feature_axis_units"]
        or manifest.get("training_data_hash") != record["training_data_hash"]
        or _array_digest(np.asarray(record["selected_feature_axis_values"], dtype=np.float64))
        != record["selected_feature_axis_sha256"]
        or selection_report.get("parameters") != dict(graph_selection_parameters)
    ):
        raise CanonicalModelBridgeError("canonical selection contradicts the saved model")


def _validate_preprocessing_chain(
    manifest: Mapping[str, Any],
    *,
    lineage: Mapping[str, Any],
    source_dataset: SherpaDataset | None,
    expected_training_dataset_id: int | None,
) -> None:
    """Require one source step and one selection step bound to lineage."""

    chain = manifest.get("preprocessing_chain")
    if (
        not isinstance(chain, list)
        or len(chain) != 2
        or any(not isinstance(step, Mapping) or set(step) != {"op_id", "parameters"} for step in chain)
        or chain[0]["op_id"] != "spectrasherpa.experiment_dataset_read/2"
        or chain[1]["op_id"] != "selection.variable_select"
    ):
        raise CanonicalModelBridgeError("canonical preprocessing chain is malformed")
    source_parameters = _mapping(chain[0]["parameters"], "canonical source provenance")
    selection_parameters = _mapping(chain[1]["parameters"], "canonical selection provenance")
    try:
        validate_experiment_source_provenance(source_parameters)
        if source_dataset is not None:
            validate_variable_selection_provenance(
                selection_parameters,
                manifest=manifest,
                source_dataset=source_dataset,
            )
    except ValueError as exc:
        raise CanonicalModelBridgeError("canonical preprocessing chain is invalid") from exc
    source = _mapping(lineage["source_dataset"], "canonical source dataset")
    selection = _mapping(lineage["selection"], "canonical selection")
    expected_source = {
        "file_count": source.get("file_count"),
        "stage": "raw",
        "asset_id": source.get("asset_id"),
        "source_manifest_sha256": source.get("source_manifest_sha256"),
        "collection_definition_sha256": source.get("collection_definition_sha256"),
        "scientific_collection_sha256": source.get("scientific_collection_sha256"),
    }
    if any(source_parameters.get(key) != value for key, value in expected_source.items()):
        raise CanonicalModelBridgeError("canonical source provenance differs from lineage")
    if expected_training_dataset_id is not None and source_parameters.get("dataset_id") != expected_training_dataset_id:
        raise CanonicalModelBridgeError("canonical source provenance names the wrong training experiment")
    lineage_mask = _strict_mask(selection.get("feature_mask"), features=int(selection["source_shape"][1]))
    chain_mask = _strict_mask(selection_parameters.get("feature_mask"), features=lineage_mask.size)
    if not np.array_equal(chain_mask, lineage_mask) or selection_parameters.get("selection_report") != selection.get(
        "selection_report"
    ):
        raise CanonicalModelBridgeError("canonical selection provenance differs from lineage")


def _selection_record(
    source: SherpaDataset,
    selected: SherpaDataset,
    *,
    mask: np.ndarray,
    report: Mapping[str, Any],
    graph_selection_parameters: Mapping[str, Any],
    asset_id: str,
) -> dict[str, Any]:
    axis = source.get_feature_axis()
    selected_axis = selected.get_feature_axis()
    if axis is None or axis.values is None or selected_axis is None or selected_axis.values is None:
        raise CanonicalModelBridgeError("canonical selection requires complete feature axes")
    if report.get("parameters") != dict(graph_selection_parameters):
        raise CanonicalModelBridgeError("selection report differs from the canonical graph")
    selected_values = np.asarray(selected.X, dtype=np.float64)
    selected_axis_values = np.asarray(selected_axis.values, dtype=np.float64)
    selected_axis_semantics = axis_semantics(
        axis_class=type(selected_axis).__name__,
        title=selected_axis.title,
        units=selected_axis.units,
        quantity=selected_axis.quantity,
    )
    training_hash = _training_data_hash(selected_values)
    record = {
        "selection_report": deepcopy(dict(report)),
        "feature_mask": mask.tolist(),
        "feature_mask_sha256": _bool_digest(mask),
        "source_shape": list(source.shape),
        "source_values_sha256": _array_digest(source.X),
        "source_feature_axis_sha256": _array_digest(axis.values),
        "selected_shape": list(selected_values.shape),
        "selected_dtype": selected_values.dtype.str,
        "selected_values_sha256": _array_digest(selected_values),
        "selected_feature_axis_values": selected_axis_values.tolist(),
        "selected_feature_axis_sha256": _array_digest(selected_axis_values),
        "feature_axis_type": type(selected_axis).__name__,
        "feature_axis_title": selected_axis.title,
        "feature_axis_quantity": (
            None if selected_axis_semantics.quantity is None else selected_axis_semantics.quantity.value
        ),
        "feature_axis_units": selected_axis_semantics.units,
        "training_data_hash": training_hash,
    }
    temporary_manifest = {
        "n_features": selected_values.shape[1],
        "feature_axis": selected_axis_values.tolist(),
        "feature_axis_quantity": (
            None if selected_axis_semantics.quantity is None else selected_axis_semantics.quantity.value
        ),
        "feature_axis_units": selected_axis_semantics.units,
        "feature_mask": mask.tolist(),
        "preprocessing_chain": [
            _experiment_source_step(source, experiment_id=1, asset_id=asset_id),
            {
                "op_id": "selection.variable_select",
                "parameters": {"selection_report": deepcopy(dict(report)), "feature_mask": mask.tolist()},
            },
        ],
    }
    replayed, _warnings = _application_model_artifact_replay().prepare(source.X, source, temporary_manifest)
    if not np.array_equal(replayed, selected_values):
        raise CanonicalModelBridgeError("canonical selection does not reproduce the selected matrix")
    return record


def _dataset_record(dataset: SherpaDataset) -> dict[str, Any]:
    matrix = np.asarray(dataset.X)
    axis = dataset.get_feature_axis()
    sample_axis = dataset.sample_axis
    source = dataset.meta.get("source_collection")
    if (
        matrix.ndim != 2
        or not np.issubdtype(matrix.dtype, np.floating)
        or not np.isfinite(matrix).all()
        or axis is None
        or axis.values is None
        or np.asarray(axis.values).shape != (matrix.shape[1],)
        or not np.isfinite(axis.values).all()
        or sample_axis is None
        or sample_axis.labels is None
        or sample_axis.sample_table is None
        or not isinstance(source, Mapping)
    ):
        raise CanonicalModelBridgeError("canonical training dataset is incomplete")
    table = {str(name): list(values) for name, values in sorted(sample_axis.sample_table.items())}
    source_manifest = source.get("manifest_digest")
    source_files = source.get("files")
    if not isinstance(source_files, list) or not source_files:
        raise CanonicalModelBridgeError("canonical training dataset has no source-member inventory")
    return {
        "dataset_id": dataset.dataset_id,
        "shape": list(matrix.shape),
        "dtype": matrix.dtype.str,
        "values_sha256": _array_digest(matrix),
        "feature_axis": {
            "axis_type": type(axis).__name__,
            "values_sha256": _array_digest(axis.values),
            "dtype": np.asarray(axis.values).dtype.str,
            "title": axis.title,
            "units": axis.units,
        },
        "sample_labels_sha256": _digest(list(sample_axis.labels)),
        "sample_table_sha256": _digest(table),
        "file_count": len(source_files),
        "data_role": str(dataset.data_role),
        "units": str(dataset.units),
        "target_context": dataset.target_context.model_dump(mode="json", exclude_none=True),
        "source_manifest_sha256": source_manifest,
        "collection_definition_sha256": source.get("collection_definition_sha256"),
        "scientific_collection_sha256": source.get("scientific_collection_sha256"),
    }


def _selected_dataset(source: SherpaDataset, mask: np.ndarray) -> SherpaDataset:
    axis = source.get_feature_axis()
    assert axis is not None and axis.values is not None
    selected = source[:, mask]
    if not np.array_equal(np.asarray(selected.X), np.asarray(source.X)[:, mask]):
        raise CanonicalModelBridgeError("selected dataset differs from its exact column projection")
    return selected


def _experiment_source_step(dataset: SherpaDataset, *, experiment_id: int, asset_id: str) -> dict[str, Any]:
    source = _mapping(dataset.meta.get("source_collection"), "source collection")
    files = source.get("files")
    if not isinstance(files, list) or not files:
        raise CanonicalModelBridgeError("source collection has no exact member inventory")
    if not isinstance(asset_id, str) or not asset_id or len(asset_id) > 255:
        raise CanonicalModelBridgeError("source collection has no exact asset identity")
    if isinstance(experiment_id, bool) or not isinstance(experiment_id, int) or experiment_id < 1:
        raise CanonicalModelBridgeError("source collection has no durable experiment identity")
    return {
        "op_id": "spectrasherpa.experiment_dataset_read/2",
        "parameters": {
            "dataset_id": experiment_id,
            "file_count": len(files),
            "stage": "raw",
            "asset_id": asset_id,
            "source_manifest_sha256": source.get("manifest_digest"),
            "collection_definition_sha256": source.get("collection_definition_sha256"),
            "scientific_collection_sha256": source.get("scientific_collection_sha256"),
        },
    }


def _manifest_training_asset(manifest: Mapping[str, Any]) -> str:
    chain = manifest.get("preprocessing_chain")
    if not isinstance(chain, list) or len(chain) != 2 or not isinstance(chain[0], Mapping):
        raise CanonicalModelBridgeError("canonical preprocessing chain is malformed")
    parameters = chain[0].get("parameters")
    if not isinstance(parameters, Mapping):
        raise CanonicalModelBridgeError("canonical training source provenance is malformed")
    asset_id = parameters.get("asset_id")
    if not isinstance(asset_id, str) or not asset_id or len(asset_id) > 255:
        raise CanonicalModelBridgeError("canonical training asset is malformed")
    return asset_id


def _supervision_attachment_node_id(dataset: SherpaDataset) -> str:
    history = dataset.provenance.to_list()
    if not history or not isinstance(history[-1], Mapping):
        raise CanonicalModelBridgeError("canonical training dataset has no supervision attachment provenance")
    step = history[-1]
    node_id = step.get("node_id")
    if step.get("op_id") != "data.attach_target":
        raise CanonicalModelBridgeError("canonical supervision attachment provenance is malformed")
    return _require_node_id(node_id)


def _require_node_id(value: object) -> str:
    if (
        not isinstance(value, str)
        or not value
        or not value[0].isalnum()
        or len(value) > 128
        or any(not (char.isalnum() or char in "._:-") for char in value)
    ):
        raise CanonicalModelBridgeError("canonical supervision attachment node identity is malformed")
    return value


def _portable_capability_digests(capability: SpectralDatasetCapability) -> tuple[str, str]:
    """Bind a capability while excluding only non-reproducible event timestamps."""

    metadata = _plain_json(capability.metadata)
    provenance = metadata.get("provenance")
    if not isinstance(provenance, list):
        raise CanonicalModelBridgeError("canonical capability provenance is malformed")
    normalized_provenance: list[dict[str, Any]] = []
    for step in provenance:
        if not isinstance(step, dict) or not isinstance(step.get("timestamp"), str):
            raise CanonicalModelBridgeError("canonical capability provenance is malformed")
        normalized_provenance.append({key: value for key, value in step.items() if key != "timestamp"})
    metadata["provenance"] = normalized_provenance

    # The v2 capability carries the canonical dataset projection as well as
    # the historical top-level provenance. Its provenance receipt therefore
    # transitively includes the same event timestamps. Recompute that one
    # nested receipt from the normalized events; otherwise two independently
    # re-admitted copies of the same durable science would differ only by the
    # wall-clock time of their attach-target operations. The full capability
    # digests still authenticate the original timestamped execution.
    execution_projection = metadata.get("execution_scientific_projection")
    if not isinstance(execution_projection, dict):
        raise CanonicalModelBridgeError("canonical capability scientific projection is malformed")
    execution_projection["provenance"] = {
        "count": len(normalized_provenance),
        "sha256": _digest(normalized_provenance),
    }
    metadata["execution_scientific_digest"] = _digest(execution_projection)
    # The complete source digest also binds the full sample table, which is
    # intentionally absent from the local capability after supervision has
    # been admitted. It cannot be recomputed from this portable envelope and
    # was not part of the pre-v2 portable authority. Exact original custody
    # remains bound by the authenticated capability and supervision digests.
    metadata.pop("scientific_digest", None)
    arrays = {
        name: {
            "dtype": array.dtype.str,
            "shape": list(array.shape),
            "sha256": _array_digest(array),
        }
        for name, array in sorted(capability.arrays.items())
    }
    envelope = {"metadata": metadata, "arrays": arrays}
    content_metadata = dict(metadata)
    content_metadata.pop("custody_id", None)
    content = {"metadata": content_metadata, "arrays": arrays}
    return _digest(content), _digest(envelope)


def _authenticate_original_capability(
    live_capability: SpectralDatasetCapability,
    original_metadata: Mapping[str, Any],
    *,
    expected_content_digest: str,
    expected_envelope_digest: str,
) -> SpectralDatasetCapability:
    """Reconstruct the original execution capability from live arrays.

    The caller supplies only its private metadata (including original
    provenance timestamps); the admitted live arrays must reproduce the exact
    capability digests named by the canonical refit.  A replacement dataset
    therefore cannot mint its own portable lineage projection.
    """

    try:
        original = SpectralDatasetCapability(
            arrays=live_capability.arrays,
            metadata=deepcopy(dict(original_metadata)),
        )
    except (SpectralCapabilityError, TypeError, ValueError) as exc:
        raise CanonicalModelBridgeError("original training capability metadata is invalid") from exc
    if original.content_digest != expected_content_digest or original.envelope_digest != expected_envelope_digest:
        raise CanonicalModelBridgeError("live training arrays do not reproduce the canonical refit capability")
    return original


def _plain_json(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _plain_json(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain_json(item) for item in value]
    return value


def _selection_parameters(graph: Any) -> Mapping[str, Any]:
    nodes = [node for node in graph.nodes if node.operation_id == "selection.variable_select"]
    if len(nodes) != 1:
        raise CanonicalModelBridgeError("canonical bridge requires one variable-selection node")
    return nodes[0].parameters


def _canonical_state_authority(
    artifact: CanonicalFittedArtifact,
    node_id: str,
) -> tuple[Mapping[str, Any], bytes]:
    refit = _full_refit(artifact)
    references = [item for item in refit["fitted_state_references"] if item["node_id"] == node_id]
    if len(references) != 1 or references[0]["serializer"] != FITTED_STATE_SERIALIZER:
        raise CanonicalModelBridgeError("canonical artifact has no exact PLS-DA state")
    raw = artifact.state_bytes.get(node_id)
    if raw is None:
        raise CanonicalModelBridgeError("canonical artifact is missing its PLS-DA state bytes")
    return references[0], raw


def _full_refit(artifact: CanonicalFittedArtifact) -> Mapping[str, Any]:
    return _mapping(
        _mapping(artifact.payload.get("full_refit_evidence"), "full refit evidence").get("full_refit_execution"),
        "full refit execution",
    )


def _strict_mask(value: object, *, features: int) -> np.ndarray:
    if not isinstance(value, list) or len(value) != features or any(type(item) is not bool for item in value):
        raise CanonicalModelBridgeError("canonical feature mask is malformed")
    mask = np.asarray(value, dtype=bool)
    if not mask.any():
        raise CanonicalModelBridgeError("canonical feature mask selects no variables")
    return mask


def _training_data_hash(value: np.ndarray) -> str:
    matrix = np.asarray(value, dtype=np.float64)
    digest = hashlib.sha256()
    digest.update(str(matrix.shape).encode("utf-8"))
    digest.update(matrix.tobytes(order="C"))
    return digest.hexdigest()


def _array_digest(value: object) -> str:
    array = np.ascontiguousarray(np.asarray(value))
    return hashlib.sha256(array.tobytes(order="C")).hexdigest()


def _bool_digest(value: np.ndarray) -> str:
    return hashlib.sha256(np.asarray(value, dtype="?").tobytes(order="C")).hexdigest()


def _digest(value: object) -> str:
    return hashlib.sha256(_canonical_json(value)).hexdigest()


def _canonical_json(value: object) -> bytes:
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False).encode()
    except (TypeError, ValueError) as exc:
        raise CanonicalModelBridgeError("canonical model lineage must be finite JSON") from exc


def _parse_canonical_mapping(value: bytes, name: str) -> dict[str, Any]:
    try:
        parsed = json.loads(value, object_pairs_hook=_reject_duplicates)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CanonicalModelBridgeError(f"{name} must be canonical JSON") from exc
    if not isinstance(parsed, dict) or _canonical_json(parsed) != value:
        raise CanonicalModelBridgeError(f"{name} must be a canonical JSON object")
    return parsed


def _reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise CanonicalModelBridgeError("canonical model JSON repeats a field")
        result[key] = value
    return result


def _mapping(value: object, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise CanonicalModelBridgeError(f"{name} must be an object")
    return value


def _is_sha256(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and value == value.lower()
        and all(character in "0123456789abcdef" for character in value)
    )


def _require_lineage_size(value: Mapping[str, Any]) -> None:
    if len(_canonical_json(value)) > MAX_CANONICAL_LINEAGE_BYTES:
        raise CanonicalModelBridgeError("canonical training lineage exceeds its byte ceiling")


__all__ = [
    "CANONICAL_MODEL_ORIGIN",
    "CANONICAL_TRAINING_LINEAGE_SCHEMA",
    "CanonicalModelBridgeError",
    "CanonicalPLSDABridge",
    "bridge_canonical_plsda_artifact",
    "persist_canonical_plsda_bridge",
    "validate_canonical_plsda_model_artifact",
]
