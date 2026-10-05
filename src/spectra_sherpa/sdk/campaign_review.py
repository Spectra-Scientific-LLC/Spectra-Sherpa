"""No-account inspection of one Campaign Review Package.

The hosted service creates and settles campaigns.  This OSS module does not:
it admits one closed, data-free package and renders the already-bound
candidate ledger, decision, terminal refit, and fixed application authority.
"""

from __future__ import annotations

import hashlib
import io
import json
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from spectra_sherpa.app.services.sherpa_object import (
    PROJECT_PAYLOAD,
    SHERPA_OBJECT_MANIFEST,
    ArchiveMember,
    SherpaObjectError,
    build_archive,
    preflight_zip_central_directory,
    validate_archive_bytes,
)

from .canonical_project import CanonicalProjectPackage
from .canonical_publisher_attestation import (
    CanonicalPublisherAttestationError,
    CanonicalPublisherTrustAnchors,
    LocalCanonicalPublisherTrustStore,
    SignedCanonicalProjectAttestation,
)
from .fitted_state_custody import (
    FittedStateCustodyError,
    require_data_free_fitted_state_members,
)
from .project import ProjectIOError, read_bounded_regular_file

CAMPAIGN_REVIEW_INSPECTION_VERSION = "spectra-campaign-review-inspection/2"
REPRODUCE_LOCALLY_REASON = "recorded_reproduce_locally_with_named_dataset"
CAMPAIGN_REVIEW_PACKAGE_VERSION = "spectra-campaign-review-package/1"
CAMPAIGN_REVIEW_DELIVERABLE = "Campaign Review Package"
_APPLICATION_MEMBER = "campaign-review/fixed-application.sherpa"
_ATTESTATION_MEMBER = "campaign-review/publisher-attestation.json"
_PACKAGE_FIELDS = frozenset(
    {
        "schema_version",
        "deliverable",
        "project_name",
        "application_sha256",
        "publisher_attestation_digest",
        "campaign_id",
        "candidate_id",
        "claim_scope",
        "contains_source_data",
    }
)
_PACKAGE_MEMBERS = frozenset(
    {
        PROJECT_PAYLOAD,
        SHERPA_OBJECT_MANIFEST,
        _APPLICATION_MEMBER,
        _ATTESTATION_MEMBER,
    }
)
_OUTER_DIRECTORY_BYTES_MAX = 1024 * 1024


class CampaignReviewError(ValueError):
    """A Campaign Review Package cannot be rendered truthfully."""


def _parse_unique_object(raw: bytes, *, label: str) -> dict[str, Any]:
    def unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        output: dict[str, Any] = {}
        for key, value in pairs:
            if key in output:
                raise CampaignReviewError(f"{label} has duplicate JSON keys")
            output[key] = value
        return output

    try:
        value = json.loads(raw, object_pairs_hook=unique_object)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CampaignReviewError(f"{label} is invalid") from exc
    if not isinstance(value, dict):
        raise CampaignReviewError(f"{label} must be an object")
    return value


def _canonical_json(value: Mapping[str, Any]) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False).encode()


def _copy(value: Any) -> Any:
    return json.loads(json.dumps(value, sort_keys=True, ensure_ascii=True, allow_nan=False))


@dataclass(frozen=True)
class CampaignReviewInspection:
    """One complete data-free decision-chain projection."""

    payload: Mapping[str, Any]
    report_digest: str

    def as_dict(self) -> dict[str, Any]:
        return _copy(self.payload)

    @property
    def canonical_bytes(self) -> bytes:
        return _canonical_json(self.payload)


@dataclass(frozen=True)
class CampaignReviewPackage:
    """One publisher-attested outer package with a fixed application payload.

    The nested ``.sherpa`` archive remains the normal Workbench application
    artifact.  This outer layer removes the former package-plus-sidecar
    ambiguity by retaining the exact signed statement inside the same closed
    archive.  Trust remains recipient-controlled: bundled bytes are never
    treated as a trust anchor.
    """

    archive: bytes
    project_payload: Mapping[str, Any]
    application: CanonicalProjectPackage
    publisher_attestation: SignedCanonicalProjectAttestation
    archive_sha256: str

    @classmethod
    def has_archive_identity(cls, archive: bytes) -> bool:
        """Recognize the exact outer inventory without trusting a filename or MIME type."""

        if not isinstance(archive, bytes) or not archive:
            return False
        try:
            preflight = preflight_zip_central_directory(
                archive,
                max_members=len(_PACKAGE_MEMBERS),
                max_directory_bytes=_OUTER_DIRECTORY_BYTES_MAX,
                max_uncompressed_bytes=512 * 1024 * 1024,
            )
            if preflight.member_count != len(_PACKAGE_MEMBERS):
                return False
            with zipfile.ZipFile(io.BytesIO(archive), "r") as package_zip:
                return frozenset(package_zip.namelist()) == _PACKAGE_MEMBERS
        except (OSError, SherpaObjectError, zipfile.BadZipFile):
            return False

    @classmethod
    def build(
        cls,
        *,
        application: CanonicalProjectPackage,
        publisher_attestation: SignedCanonicalProjectAttestation,
        publisher_trust_anchors: CanonicalPublisherTrustAnchors,
    ) -> "CampaignReviewPackage":
        if not isinstance(application, CanonicalProjectPackage):
            raise CampaignReviewError("Campaign Review Package requires a verified fixed application")
        if not isinstance(publisher_attestation, SignedCanonicalProjectAttestation):
            raise CampaignReviewError("Campaign Review Package requires a signed publisher attestation")
        if not isinstance(publisher_trust_anchors, CanonicalPublisherTrustAnchors):
            raise CampaignReviewError("Campaign Review Package build requires explicit publisher trust anchors")
        _require_data_free_application(application)
        try:
            LocalCanonicalPublisherTrustStore.from_document(publisher_trust_anchors).verify(
                package=application,
                attestation=publisher_attestation,
            )
        except CanonicalPublisherAttestationError as exc:
            raise CampaignReviewError("Campaign Review Package publisher authentication failed") from exc
        request = application.capsule.payload["admitted_request"]
        payload = {
            "schema_version": CAMPAIGN_REVIEW_PACKAGE_VERSION,
            "deliverable": CAMPAIGN_REVIEW_DELIVERABLE,
            "project_name": application.project_payload["name"],
            "application_sha256": application.archive_sha256,
            "publisher_attestation_digest": publisher_attestation.digest,
            "campaign_id": request["campaign_id"],
            "candidate_id": request["candidate_id"],
            "claim_scope": publisher_attestation.statement["claim_scope"],
            "contains_source_data": False,
        }
        try:
            archive = build_archive(
                project_payload=payload,
                members=(
                    ArchiveMember(_APPLICATION_MEMBER, application.archive),
                    ArchiveMember(_ATTESTATION_MEMBER, publisher_attestation.canonical_bytes),
                ),
                package_mode="metadata_only",
            )
        except SherpaObjectError as exc:
            raise CampaignReviewError("Campaign Review Package could not be sealed") from exc
        return cls.from_archive(archive)

    @classmethod
    def from_archive(
        cls,
        archive: bytes,
        *,
        max_uncompressed_bytes: int = 512 * 1024 * 1024,
    ) -> "CampaignReviewPackage":
        if not isinstance(archive, bytes) or not archive:
            raise CampaignReviewError("Campaign Review Package bytes are required")
        if not isinstance(max_uncompressed_bytes, int) or max_uncompressed_bytes <= 0:
            raise CampaignReviewError("Campaign Review Package uncompressed budget is invalid")
        try:
            outer_preflight = preflight_zip_central_directory(
                archive,
                max_members=len(_PACKAGE_MEMBERS),
                max_directory_bytes=_OUTER_DIRECTORY_BYTES_MAX,
                max_uncompressed_bytes=max_uncompressed_bytes,
            )
        except SherpaObjectError as exc:
            raise CampaignReviewError("Campaign Review Package archive is invalid") from exc
        if outer_preflight.member_count != len(_PACKAGE_MEMBERS):
            raise CampaignReviewError("Campaign Review Package member inventory is not exact")
        report = validate_archive_bytes(archive, max_uncompressed_bytes=max_uncompressed_bytes)
        if not report.get("valid") or frozenset(report.get("members", ())) != _PACKAGE_MEMBERS:
            raise CampaignReviewError("Campaign Review Package archive is invalid")
        try:
            with zipfile.ZipFile(io.BytesIO(archive), "r") as package_zip:
                _parse_unique_object(
                    package_zip.read(SHERPA_OBJECT_MANIFEST),
                    label="Campaign Review integrity manifest",
                )
                payload = _parse_unique_object(package_zip.read(PROJECT_PAYLOAD), label="Campaign Review manifest")
                attestation_value = _parse_unique_object(
                    package_zip.read(_ATTESTATION_MEMBER),
                    label="Campaign Review publisher attestation",
                )
                application_bytes = package_zip.read(_APPLICATION_MEMBER)
        except (KeyError, zipfile.BadZipFile, SherpaObjectError) as exc:
            raise CampaignReviewError("Campaign Review Package archive is invalid") from exc
        if set(payload) != _PACKAGE_FIELDS or payload.get("schema_version") != CAMPAIGN_REVIEW_PACKAGE_VERSION:
            raise CampaignReviewError("Campaign Review Package manifest schema is unsupported")
        if (
            payload.get("deliverable") != CAMPAIGN_REVIEW_DELIVERABLE
            or payload.get("contains_source_data") is not False
        ):
            raise CampaignReviewError("Campaign Review Package boundary is invalid")
        try:
            inner_budget = max_uncompressed_bytes - outer_preflight.total_uncompressed_bytes
            if inner_budget <= 0:
                raise CampaignReviewError("Campaign Review Package aggregate working-set budget is exhausted")
            application = CanonicalProjectPackage.from_archive(application_bytes, max_uncompressed_bytes=inner_budget)
            _require_data_free_application(application)
            attestation = SignedCanonicalProjectAttestation.from_dict(attestation_value)
            attestation.require_matches_package(application)
        except (CanonicalPublisherAttestationError, ValueError) as exc:
            raise CampaignReviewError("Campaign Review Package contents do not agree") from exc
        request = application.capsule.payload["admitted_request"]
        expected = {
            "schema_version": CAMPAIGN_REVIEW_PACKAGE_VERSION,
            "deliverable": CAMPAIGN_REVIEW_DELIVERABLE,
            "project_name": application.project_payload["name"],
            "application_sha256": application.archive_sha256,
            "publisher_attestation_digest": attestation.digest,
            "campaign_id": request["campaign_id"],
            "candidate_id": request["candidate_id"],
            "claim_scope": attestation.statement["claim_scope"],
            "contains_source_data": False,
        }
        if payload != expected:
            raise CampaignReviewError("Campaign Review Package manifest differs from its contents")
        return cls(
            archive=archive,
            project_payload=payload,
            application=application,
            publisher_attestation=attestation,
            archive_sha256=hashlib.sha256(archive).hexdigest(),
        )


def _require_data_free_application(application: CanonicalProjectPackage) -> None:
    """Admit only serializers positively classified as data-free state."""

    members = application.artifact.payload.get("state_members")
    if not isinstance(members, list) or not members:
        raise CampaignReviewError("Campaign Review application fitted-state inventory is invalid")
    if any(
        not isinstance(member, Mapping)
        or set(member)
        != {
            "node_id",
            "state_digest",
            "serializer",
            "contract_digest",
            "candidate_node_digest",
            "seed",
            "relative_path",
            "state_content_digest",
        }
        for member in members
    ):
        raise CampaignReviewError("Campaign Review application fitted-state inventory is invalid")
    try:
        require_data_free_fitted_state_members(members)
    except FittedStateCustodyError as exc:
        raise CampaignReviewError(
            "Campaign Review Package cannot claim data-free custody for its fitted artifact"
        ) from exc


def inspect_campaign_review_package(
    source: CampaignReviewPackage | bytes | str | Path,
    *,
    publisher_trust_anchors: Mapping[str, Any] | None = None,
) -> CampaignReviewInspection:
    """Verify and render a Campaign Review Package without an account or network.

    The signed statement is a required member. Publisher authentication is
    still never inferred: the recipient must supply a trusted key document.
    """
    try:
        if isinstance(source, CampaignReviewPackage):
            review_package = source
        elif isinstance(source, bytes):
            review_package = CampaignReviewPackage.from_archive(source)
        elif isinstance(source, (str, Path)):
            review_package = CampaignReviewPackage.from_archive(load_review_package_bytes(source))
        else:
            raise TypeError("Campaign Review source must be package bytes or an explicit local path")
    except (CampaignReviewError, ProjectIOError) as exc:
        raise CampaignReviewError("Campaign Review Package integrity admission failed") from exc
    package = review_package.application

    publisher = {
        "status": "not_authenticated",
        "reason": "publisher_trust_anchors_not_supplied",
        "attestation_digest": review_package.publisher_attestation.digest,
    }
    if publisher_trust_anchors is not None:
        try:
            anchors = CanonicalPublisherTrustAnchors.from_dict(publisher_trust_anchors)
            digest = LocalCanonicalPublisherTrustStore.from_document(anchors).verify(
                package=package,
                attestation=review_package.publisher_attestation,
            )
        except CanonicalPublisherAttestationError as exc:
            raise CampaignReviewError("Campaign Review Package publisher authentication failed") from exc
        publisher = {"status": "passed", "reason": None, "attestation_digest": digest}

    evidence = package.campaign_evidence.as_dict()
    request = package.capsule.payload["admitted_request"]
    candidates: list[dict[str, Any]] = []
    for candidate in evidence["candidates"]:
        rendered = {
            "status": candidate["status"],
            "candidate_id": candidate["candidate_id"],
            "declared_ordinal": candidate["declared_ordinal"],
            "candidate_digest": candidate["candidate_digest"],
            "configuration": candidate["candidate_graph"],
            "request_digest": candidate["request_digest"],
            "result_digest": candidate["result_digest"],
        }
        if candidate["status"] == "succeeded":
            validation = candidate["validation_execution"]
            rendered.update(
                {
                    "successful_ordinal": candidate["ordinal"],
                    "task_type": validation["task_type"],
                    "model_operation_id": validation["model_operation_id"],
                    "split_plan_digest": validation["split_plan_digest"],
                    "aggregate_metrics": validation["metrics"],
                    "folds": validation["folds"],
                    "validation_execution": validation,
                }
            )
        else:
            rendered.update(
                {
                    "failure_status": candidate["failure_status"],
                    "failure_code": candidate["failure_code"],
                }
            )
        candidates.append(rendered)

    unsigned = {
        "schema_version": CAMPAIGN_REVIEW_INSPECTION_VERSION,
        "deliverable": CAMPAIGN_REVIEW_DELIVERABLE,
        "package": {
            "sha256": review_package.archive_sha256,
            "fixed_application_sha256": package.archive_sha256,
            "name": package.project_payload["name"],
            "status": package.project_payload["metadata"]["canonical_project"]["package_status"],
            "data_members": "none",
            "integrity": "passed",
        },
        "campaign": evidence["campaign"],
        "candidate_ledger": candidates,
        "decision": evidence["decision"],
        "terminal_refit": {
            **evidence["winner_refit"],
            "full_refit_evidence": package.artifact.payload["full_refit_evidence"],
        },
        "fixed_application": {
            "selected_candidate_id": request["candidate_id"],
            "application_plan": package.application_plan.as_dict(),
            "fitted_artifact_manifest": package.artifact.as_dict(),
            "local_model_record": package.local_model_record.as_dict(),
            "presentation_manifest": _copy(package.presentation_manifest),
        },
        "confirmation_history": package.confirmation_history.as_dict(),
        "verification": {
            "integrity_verified": {"status": "passed"},
            "publisher_authenticated": publisher,
            # Inspection never executes science.  The recorded values are the
            # expected results that local reproduction must match, bound to the
            # exact dataset and split identities it must be run against.
            "validation_reproduced": {
                "status": "not_run",
                "reason": REPRODUCE_LOCALLY_REASON,
                "recorded": _recorded_validation(package),
            },
            "application_reproduced": {
                "status": "not_run",
                "reason": REPRODUCE_LOCALLY_REASON,
                "recorded": _recorded_application(package),
            },
        },
        "boundaries": {
            "contains_source_data": False,
            "can_create_or_resume_campaign": False,
            "can_search_or_select_candidates": False,
            "fixed_application_only": True,
            "claim_scope": "public_reproducibility_only",
        },
    }
    report_digest = hashlib.sha256(_canonical_json(unsigned)).hexdigest()
    payload = {**unsigned, "report_digest": report_digest}
    return CampaignReviewInspection(payload=payload, report_digest=report_digest)


def _dataset_identity(request: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "dataset_content_digest": request["dataset_content_digest"],
        "capability_digest": request["capability_digest"],
        "dataset_ref_digest": request["dataset_ref_digest"],
        "split_digest": request["split_digest"],
        "dataset_shape": _copy(request["dataset_shape"]),
    }


def _recorded_validation(package: CanonicalProjectPackage) -> dict[str, Any]:
    validation = package.capsule.execution_evidence.payload["validation_execution"]
    return {
        "task_type": validation["task_type"],
        "model_operation_id": validation["model_operation_id"],
        "metrics": _copy(validation["metrics"]),
        "fold_count": len(validation["folds"]),
        "capsule_digest": package.capsule.capsule_digest,
        "dataset": _dataset_identity(package.capsule.payload["admitted_request"]),
    }


def _recorded_application(package: CanonicalProjectPackage) -> dict[str, Any]:
    return {
        "artifact_digest": package.artifact.artifact_digest,
        "application_plan_digest": package.application_plan.application_plan_digest,
        "dataset": _dataset_identity(package.capsule.payload["admitted_request"]),
        "held_out_confirmation": package.confirmation_history.disposition,
    }


def load_review_package_bytes(source: str | Path) -> bytes:
    """Read one outer package through the same bounded no-follow authority."""

    # Reuse the canonical package facade for its 512 MiB single-descriptor
    # boundary without asking it to parse the outer format.
    return read_bounded_regular_file(
        Path(source).expanduser(),
        max_bytes=512 * 1024 * 1024,
        label="Campaign Review Package",
    )


__all__ = [
    "CAMPAIGN_REVIEW_DELIVERABLE",
    "CAMPAIGN_REVIEW_INSPECTION_VERSION",
    "CAMPAIGN_REVIEW_PACKAGE_VERSION",
    "CampaignReviewError",
    "CampaignReviewInspection",
    "CampaignReviewPackage",
    "inspect_campaign_review_package",
    "load_review_package_bytes",
]
