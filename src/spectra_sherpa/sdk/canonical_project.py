"""Sealed, data-free portable packages for canonical fitted applications.

This is deliberately not the historical ``harness_project`` materializer.
That PLS-v1 route is frozen evidence and must never become the authority for a
canonical v4 DAG.  A canonical package instead transports the three identities
that make an application meaningful together: the admitted workflow capsule,
the immutable fitted artifact, and the visible application-plan projection.

The package is safe to inspect offline.  It has no source data, executable
code, or implicit model reconstruction.  The later project importer must call
the loader here before it may write an artifact or database record.
"""

from __future__ import annotations

import hashlib
import io
import json
import zipfile
from dataclasses import dataclass
from typing import Any, Mapping

from spectra_sherpa.app.services.dag.presentation_contract import build_portable_presentation_manifest
from spectra_sherpa.app.services.sherpa_object import (
    DEFAULT_MAX_UNCOMPRESSED_BYTES,
    PROJECT_PAYLOAD,
    SHERPA_OBJECT_MANIFEST,
    ArchiveMember,
    SherpaObjectError,
    build_archive,
    preflight_zip_central_directory,
    validate_archive_bytes,
)

from .canonical_application import CanonicalApplicationPlan, CanonicalApplicationPlanError
from .canonical_campaign_evidence import CanonicalCampaignEvidence, CanonicalCampaignEvidenceError
from .canonical_capsule import CanonicalWorkflowCapsule, CanonicalWorkflowCapsuleError
from .canonical_confirmation_history import (
    CanonicalConfirmationHistory,
    CanonicalConfirmationHistoryError,
)
from .canonical_fitted_artifact import (
    MAX_CANONICAL_STATE_MEMBERS,
    CanonicalFittedArtifact,
    CanonicalFittedArtifactError,
)
from .local_model_record import LocalModelRecord, LocalModelRecordError

CANONICAL_PROJECT_PACKAGE_VERSION = "spectra-canonical-project-package/6"
_PLAN_MEMBER = "canonical/application-plan.json"
_CAPSULE_MEMBER = "canonical/capsule.json"
_ARTIFACT_MANIFEST_MEMBER = "canonical/artifact/manifest.json"
_ARTIFACT_STATE_ROOT = "canonical/artifact/states"
_LOCAL_MODEL_RECORD_MEMBER = "canonical/local-model-record.json"
_CAMPAIGN_EVIDENCE_MEMBER = "canonical/campaign-evidence.json"
_CONFIRMATION_HISTORY_MEMBER = "canonical/confirmation-history.json"
_PRESENTATION_MANIFEST_MEMBER = "canonical/presentation-manifest.json"
_DIGEST_LENGTH = 64
_FIXED_PACKAGE_MEMBER_COUNT = 9
_PACKAGE_DIRECTORY_BYTES_MAX = 4 * 1024 * 1024


class CanonicalProjectPackageError(ValueError):
    """A canonical project package is incomplete, forged, or malformed."""


@dataclass(frozen=True)
class CanonicalProjectPackage:
    """One verified data-free portable canonical project package."""

    archive: bytes
    project_payload: dict[str, Any]
    application_plan: CanonicalApplicationPlan
    capsule: CanonicalWorkflowCapsule
    artifact: CanonicalFittedArtifact
    local_model_record: LocalModelRecord
    campaign_evidence: CanonicalCampaignEvidence
    confirmation_history: CanonicalConfirmationHistory
    presentation_manifest: dict[str, Any]
    archive_sha256: str

    @classmethod
    def build(
        cls,
        *,
        capsule: CanonicalWorkflowCapsule,
        artifact: CanonicalFittedArtifact,
        application_plan: CanonicalApplicationPlan,
        local_model_record: LocalModelRecord,
        campaign_evidence: CanonicalCampaignEvidence,
        confirmation_history: CanonicalConfirmationHistory,
        project_name: str | None = None,
    ) -> "CanonicalProjectPackage":
        """Create the one current package from its complete canonical record."""

        if not isinstance(capsule, CanonicalWorkflowCapsule):
            raise CanonicalProjectPackageError("canonical project package requires a verified capsule")
        if not isinstance(artifact, CanonicalFittedArtifact):
            raise CanonicalProjectPackageError("canonical project package requires a verified fitted artifact")
        if not isinstance(application_plan, CanonicalApplicationPlan):
            raise CanonicalProjectPackageError("canonical project package requires a verified application plan")
        try:
            application_plan.require_matches(capsule, artifact)
        except CanonicalApplicationPlanError as exc:
            raise CanonicalProjectPackageError("canonical project package identities do not agree") from exc
        if not isinstance(local_model_record, LocalModelRecord):
            raise CanonicalProjectPackageError("canonical project package local model record is invalid")
        try:
            local_model_record.require_matches(
                capsule=capsule,
                artifact=artifact,
                application_plan=application_plan,
            )
        except LocalModelRecordError as exc:
            raise CanonicalProjectPackageError(
                "canonical project package local model record does not match its identities"
            ) from exc
        if not isinstance(campaign_evidence, CanonicalCampaignEvidence):
            raise CanonicalProjectPackageError("canonical project package campaign evidence is invalid")
        try:
            campaign_evidence.require_matches(capsule, artifact, application_plan)
            local_model_record.require_matches_campaign_evidence(campaign_evidence)
        except CanonicalCampaignEvidenceError as exc:
            raise CanonicalProjectPackageError(
                "canonical project package campaign evidence does not match its identities"
            ) from exc
        except LocalModelRecordError as exc:
            raise CanonicalProjectPackageError(
                "canonical project package local model record does not match its campaign"
            ) from exc
        if not isinstance(confirmation_history, CanonicalConfirmationHistory):
            raise CanonicalProjectPackageError("canonical project package confirmation history is invalid")
        try:
            confirmation_history.require_matches_campaign(
                campaign_id=campaign_evidence.payload["campaign"]["campaign_id"],
                capsule_digest=capsule.capsule_digest,
            )
        except CanonicalConfirmationHistoryError as exc:
            raise CanonicalProjectPackageError(
                "canonical project package confirmation history belongs to another campaign"
            ) from exc

        presentation_manifest = _presentation_manifest(application_plan)
        payload = _project_payload(
            capsule,
            artifact,
            application_plan,
            local_model_record=local_model_record,
            campaign_evidence=campaign_evidence,
            confirmation_history=confirmation_history,
            presentation_manifest=presentation_manifest,
            project_name=project_name,
        )
        members = [
            ArchiveMember(_PLAN_MEMBER, _canonical_json(application_plan.as_dict())),
            ArchiveMember(_CAPSULE_MEMBER, _canonical_json(capsule.as_dict())),
            ArchiveMember(_ARTIFACT_MANIFEST_MEMBER, _canonical_json(artifact.as_dict())),
        ]
        members.append(ArchiveMember(_LOCAL_MODEL_RECORD_MEMBER, local_model_record.canonical_bytes()))
        members.append(ArchiveMember(_CAMPAIGN_EVIDENCE_MEMBER, campaign_evidence.canonical_bytes()))
        members.append(ArchiveMember(_CONFIRMATION_HISTORY_MEMBER, confirmation_history.canonical_bytes()))
        members.append(ArchiveMember(_PRESENTATION_MANIFEST_MEMBER, _canonical_json(presentation_manifest)))
        for member in artifact.payload["state_members"]:
            node_id = member["node_id"]
            members.append(ArchiveMember(_state_member_path(node_id), artifact.state_bytes[node_id]))
        archive = build_archive(project_payload=payload, members=members, package_mode="full")
        return cls.from_archive(archive)

    @classmethod
    def from_archive(
        cls,
        archive: bytes,
        *,
        max_uncompressed_bytes: int = DEFAULT_MAX_UNCOMPRESSED_BYTES,
    ) -> "CanonicalProjectPackage":
        """Verify all package bytes before returning any project representation."""

        if not isinstance(archive, bytes) or not archive:
            raise CanonicalProjectPackageError("canonical project package bytes are required")
        if not isinstance(max_uncompressed_bytes, int) or max_uncompressed_bytes <= 0:
            raise CanonicalProjectPackageError("canonical project package uncompressed budget is invalid")
        try:
            preflight_zip_central_directory(
                archive,
                max_members=_FIXED_PACKAGE_MEMBER_COUNT + MAX_CANONICAL_STATE_MEMBERS,
                max_directory_bytes=_PACKAGE_DIRECTORY_BYTES_MAX,
                max_uncompressed_bytes=max_uncompressed_bytes,
            )
            report = validate_archive_bytes(archive, max_uncompressed_bytes=max_uncompressed_bytes)
        except (SherpaObjectError, ValueError) as exc:
            raise CanonicalProjectPackageError("canonical project package archive is invalid") from exc
        if not report.get("valid"):
            raise CanonicalProjectPackageError("canonical project package hash inventory is invalid")
        try:
            with zipfile.ZipFile(io.BytesIO(archive), "r") as zf:
                project = _read_json_object(zf, PROJECT_PAYLOAD, "canonical project payload", require_canonical=False)
                _require_current_project_package_version(project)
                plan_value = _read_json_object(zf, _PLAN_MEMBER, "canonical application plan")
                capsule_value = _read_json_object(zf, _CAPSULE_MEMBER, "canonical workflow capsule")
                artifact_manifest = zf.read(_ARTIFACT_MANIFEST_MEMBER)
                try:
                    capsule = CanonicalWorkflowCapsule.from_dict(capsule_value)
                    application_plan = CanonicalApplicationPlan.from_dict(plan_value)
                    artifact_manifest_value = _parse_canonical_object(
                        artifact_manifest, "canonical fitted artifact manifest"
                    )
                    state_members = artifact_manifest_value.get("state_members")
                    if not isinstance(state_members, list):
                        raise CanonicalProjectPackageError("canonical fitted artifact members are malformed")
                    state_bytes = {
                        _member_node_id(member): zf.read(_state_member_path(_member_node_id(member)))
                        for member in state_members
                    }
                    artifact = CanonicalFittedArtifact.from_serialized(artifact_manifest, state_bytes)
                    application_plan.require_matches(capsule, artifact)
                    local_model_record = LocalModelRecord.from_dict(
                        _read_json_object(zf, _LOCAL_MODEL_RECORD_MEMBER, "canonical local model record")
                    )
                    local_model_record.require_matches(
                        capsule=capsule,
                        artifact=artifact,
                        application_plan=application_plan,
                    )
                    campaign_evidence = CanonicalCampaignEvidence.from_dict(
                        _read_json_object(zf, _CAMPAIGN_EVIDENCE_MEMBER, "canonical campaign evidence")
                    )
                    campaign_evidence.require_matches(capsule, artifact, application_plan)
                    local_model_record.require_matches_campaign_evidence(campaign_evidence)
                    confirmation_history = CanonicalConfirmationHistory.from_dict(
                        _read_json_object(zf, _CONFIRMATION_HISTORY_MEMBER, "canonical confirmation history")
                    )
                    confirmation_history.require_matches_campaign(
                        campaign_id=campaign_evidence.payload["campaign"]["campaign_id"],
                        capsule_digest=capsule.capsule_digest,
                    )
                    presentation_manifest = _read_json_object(
                        zf,
                        _PRESENTATION_MANIFEST_MEMBER,
                        "canonical presentation manifest",
                    )
                    if presentation_manifest != _presentation_manifest(application_plan):
                        raise CanonicalProjectPackageError(
                            "canonical project presentation manifest differs from its application plan"
                        )
                except (
                    CanonicalApplicationPlanError,
                    CanonicalCampaignEvidenceError,
                    CanonicalFittedArtifactError,
                    CanonicalWorkflowCapsuleError,
                    CanonicalConfirmationHistoryError,
                    LocalModelRecordError,
                    KeyError,
                ) as exc:
                    raise CanonicalProjectPackageError("canonical project package identities are invalid") from exc
                _validate_project_payload(
                    project,
                    application_plan,
                    capsule,
                    artifact,
                    local_model_record=local_model_record,
                    campaign_evidence=campaign_evidence,
                    confirmation_history=confirmation_history,
                    presentation_manifest=presentation_manifest,
                )
                expected_names = {
                    PROJECT_PAYLOAD,
                    SHERPA_OBJECT_MANIFEST,
                    _PLAN_MEMBER,
                    _CAPSULE_MEMBER,
                    _ARTIFACT_MANIFEST_MEMBER,
                    *(_state_member_path(member["node_id"]) for member in artifact.payload["state_members"]),
                }
                expected_names.add(_LOCAL_MODEL_RECORD_MEMBER)
                expected_names.add(_CAMPAIGN_EVIDENCE_MEMBER)
                expected_names.add(_CONFIRMATION_HISTORY_MEMBER)
                expected_names.add(_PRESENTATION_MANIFEST_MEMBER)
                actual_names = set(zf.namelist())
                if actual_names != expected_names:
                    raise CanonicalProjectPackageError("canonical project package member inventory is closed")
        except (zipfile.BadZipFile, KeyError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise CanonicalProjectPackageError("canonical project package is malformed") from exc
        return cls(
            archive=archive,
            project_payload=project,
            application_plan=application_plan,
            capsule=capsule,
            artifact=artifact,
            local_model_record=local_model_record,
            campaign_evidence=campaign_evidence,
            confirmation_history=confirmation_history,
            presentation_manifest=presentation_manifest,
            archive_sha256=hashlib.sha256(archive).hexdigest(),
        )


def _project_payload(
    capsule: CanonicalWorkflowCapsule,
    artifact: CanonicalFittedArtifact,
    application_plan: CanonicalApplicationPlan,
    *,
    local_model_record: LocalModelRecord,
    campaign_evidence: CanonicalCampaignEvidence,
    confirmation_history: CanonicalConfirmationHistory,
    presentation_manifest: Mapping[str, Any],
    project_name: str | None,
) -> dict[str, Any]:
    admitted_request = capsule.payload["admitted_request"]
    candidate_id = admitted_request.get("candidate_id") if isinstance(admitted_request, Mapping) else None
    if not isinstance(candidate_id, str) or not candidate_id:
        raise CanonicalProjectPackageError("canonical project package candidate identity is invalid")
    name = project_name or f"Canonical managed result — {candidate_id}"
    if not isinstance(name, str) or not name.strip():
        raise CanonicalProjectPackageError("canonical project package name is invalid")
    return {
        "archive_format": {
            "schema": CANONICAL_PROJECT_PACKAGE_VERSION,
            "version": "1",
            "data_members": "none",
        },
        "name": name.strip(),
        "description": (
            "Data-free canonical managed result. After import, bind a compatible local application data source; "
            "the artifact-bound workflow applies its exact fitted states without refitting."
        ),
        "metadata": {
            "canonical_project": {
                "schema_version": CANONICAL_PROJECT_PACKAGE_VERSION,
                "package_status": "awaiting_local_data_binding",
                "application_plan_digest": application_plan.application_plan_digest,
                "capsule_digest": capsule.capsule_digest,
                "artifact_digest": artifact.artifact_digest,
                "graph_digest": application_plan.payload["graph_digest"],
                "validation_execution_digest": application_plan.payload["validation_execution_digest"],
                "full_refit_evidence_digest": application_plan.payload["full_refit_evidence_digest"],
                "local_model_record_digest": local_model_record.record_digest,
                "campaign_evidence_digest": campaign_evidence.content_digest,
                "confirmation_history_digest": confirmation_history.content_digest,
                "presentation_manifest_digest": presentation_manifest["manifest_digest"],
            }
        },
        "technique": "NIR",
        "sample_type": "canonical managed application",
        "data_sources": [],
        "experiments": [],
        "workflows": [],
        "models": [],
        "scripts": [],
        "children": [],
    }


def _validate_project_payload(
    value: Mapping[str, Any],
    application_plan: CanonicalApplicationPlan,
    capsule: CanonicalWorkflowCapsule,
    artifact: CanonicalFittedArtifact,
    *,
    local_model_record: LocalModelRecord,
    campaign_evidence: CanonicalCampaignEvidence,
    confirmation_history: CanonicalConfirmationHistory,
    presentation_manifest: Mapping[str, Any],
) -> None:
    required = {
        "archive_format",
        "name",
        "description",
        "metadata",
        "technique",
        "sample_type",
        "data_sources",
        "experiments",
        "workflows",
        "models",
        "scripts",
        "children",
    }
    if set(value) != required or not isinstance(value["name"], str) or not value["name"].strip():
        raise CanonicalProjectPackageError("canonical project payload fields are closed")
    archive_format = value["archive_format"]
    if not isinstance(archive_format, Mapping) or archive_format != {
        "schema": CANONICAL_PROJECT_PACKAGE_VERSION,
        "version": "1",
        "data_members": "none",
    }:
        raise CanonicalProjectPackageError("canonical project archive format is invalid")
    for field in ("data_sources", "experiments", "workflows", "models", "scripts", "children"):
        if value[field] != []:
            raise CanonicalProjectPackageError("canonical package cannot carry mutable project content")
    metadata = value["metadata"]
    if not isinstance(metadata, Mapping) or set(metadata) != {"canonical_project"}:
        raise CanonicalProjectPackageError("canonical project metadata is invalid")
    expected = {
        "schema_version": CANONICAL_PROJECT_PACKAGE_VERSION,
        "package_status": "awaiting_local_data_binding",
        "application_plan_digest": application_plan.application_plan_digest,
        "capsule_digest": capsule.capsule_digest,
        "artifact_digest": artifact.artifact_digest,
        "graph_digest": application_plan.payload["graph_digest"],
        "validation_execution_digest": application_plan.payload["validation_execution_digest"],
        "full_refit_evidence_digest": application_plan.payload["full_refit_evidence_digest"],
        "local_model_record_digest": local_model_record.record_digest,
        "campaign_evidence_digest": campaign_evidence.content_digest,
        "confirmation_history_digest": confirmation_history.content_digest,
        "presentation_manifest_digest": presentation_manifest["manifest_digest"],
    }
    if metadata["canonical_project"] != expected:
        raise CanonicalProjectPackageError("canonical project metadata differs from canonical identities")


def _presentation_manifest(application_plan: CanonicalApplicationPlan) -> dict[str, object]:
    """Derive the portable readout policy from the admitted application DAG."""

    return build_portable_presentation_manifest(
        [
            {
                "node_id": node["node_id"],
                "operation_id": node["application_operation_id"],
            }
            for node in application_plan.payload["nodes"]
        ]
    )


def _require_current_project_package_version(project: Mapping[str, Any]) -> None:
    """Reject every package schema except the one current closed contract."""

    archive_format = project.get("archive_format") if isinstance(project, Mapping) else None
    if not isinstance(archive_format, Mapping):
        raise CanonicalProjectPackageError("canonical project archive format is invalid")
    if archive_format.get("schema") != CANONICAL_PROJECT_PACKAGE_VERSION:
        raise CanonicalProjectPackageError("canonical project package schema is unsupported")


def _read_json_object(
    zf: zipfile.ZipFile,
    name: str,
    label: str,
    *,
    require_canonical: bool = True,
) -> dict[str, Any]:
    try:
        return _parse_canonical_object(zf.read(name), label, require_canonical=require_canonical)
    except KeyError as exc:
        raise CanonicalProjectPackageError(f"canonical project package is missing {name}") from exc


def _parse_canonical_object(raw: bytes, label: str, *, require_canonical: bool = True) -> dict[str, Any]:
    try:
        value = json.loads(raw, object_pairs_hook=_reject_duplicate_fields)
    except (UnicodeDecodeError, json.JSONDecodeError, CanonicalProjectPackageError) as exc:
        raise CanonicalProjectPackageError(f"{label} must be canonical JSON") from exc
    if not isinstance(value, dict) or (require_canonical and _canonical_json(value) != raw):
        raise CanonicalProjectPackageError(f"{label} must be canonical JSON")
    return value


def _reject_duplicate_fields(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise CanonicalProjectPackageError("canonical project JSON repeats a field")
        result[key] = value
    return result


def _member_node_id(member: object) -> str:
    if not isinstance(member, Mapping):
        raise CanonicalProjectPackageError("canonical fitted artifact member is malformed")
    node_id = member.get("node_id")
    if not isinstance(node_id, str) or not node_id or "/" in node_id or "\\" in node_id:
        raise CanonicalProjectPackageError("canonical fitted artifact member is malformed")
    return node_id


def _state_member_path(node_id: str) -> str:
    return f"{_ARTIFACT_STATE_ROOT}/{node_id}.json"


def _canonical_json(value: object) -> bytes:
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False).encode(
            "utf-8"
        )
    except (TypeError, ValueError) as exc:
        raise CanonicalProjectPackageError("canonical project JSON is invalid") from exc


__all__ = [
    "CANONICAL_PROJECT_PACKAGE_VERSION",
    "CanonicalProjectPackage",
    "CanonicalProjectPackageError",
]
