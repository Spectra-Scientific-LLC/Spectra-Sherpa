"""Independent verification of a managed publisher's canonical-project claim.

This module intentionally separates three facts which are often conflated:

* the package hash inventory proves byte integrity;
* this signature proves which configured publisher signed an exact package
  content-root statement; and
* later local reproduction proves whether the reported science can be
  reproduced.

The signer is purpose-separated from confirmation receipts.  The statement is
normally created by managed deployment custody, after the host has inspected
the running image.  A container cannot independently discover Docker's image
identity, so accepting an in-container environment value as that identity
would weaken the claim this contract is intended to make.
"""

from __future__ import annotations

import base64
import binascii
import errno
import hashlib
import json
import os
import re
import stat
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

from .canonical_project import CanonicalProjectPackage

CANONICAL_PROJECT_CONTENT_ROOT_VERSION = "spectra-canonical-project-content-root/1"
CANONICAL_PUBLISHER_ATTESTATION_VERSION = "spectra-canonical-publisher-attestation/1"
CANONICAL_PUBLISHER_ATTESTATION_PURPOSE = "spectra-managed-canonical-project-publisher/1"
CANONICAL_PUBLISHER_ATTESTATION_INPUT_VERSION = "spectra-canonical-publisher-attestation-input/1"
CANONICAL_PUBLISHER_TRUST_ANCHORS_VERSION = "spectra-canonical-publisher-trust-anchors/1"

_DIGEST = re.compile(r"^[0-9a-f]{64}$")
_GIT_SHA = re.compile(r"^[0-9a-f]{40}$")
_IMAGE_ID = re.compile(r"^sha256:[0-9a-f]{64}$")
_REPOSITORY_DIGEST = re.compile(r"^[^\s@]+@sha256:[0-9a-f]{64}$")
_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}$")
_CONTENT_ROOT_FIELDS = frozenset(
    {
        "schema_version",
        "package_sha256",
        "capsule_digest",
        "artifact_digest",
        "application_plan_digest",
        "graph_digest",
        "validation_execution_digest",
        "full_refit_evidence_digest",
        "full_refit_execution_digest",
    }
)
_STATEMENT_FIELDS = frozenset(
    {
        "schema_version",
        "purpose",
        "issuer",
        "signer_key_id",
        "key_custody_ref",
        "project_content_root",
        "executing_build",
        "runtime_profile",
        "subject",
        "terminal",
        "decision",
        "claim_scope",
        "confirmation_disposition",
    }
)
_SIGNED_FIELDS = frozenset({"statement", "signature"})
_INPUT_FIELDS = frozenset(
    {
        "schema_version",
        "project_content_root",
        "runtime_profile",
        "subject",
        "terminal",
        "decision",
        "claim_scope",
        "confirmation_disposition",
    }
)
_TRUST_ANCHOR_FIELDS = frozenset({"schema_version", "issuer", "keys"})
_ATTESTED_BUILD_FIELDS = frozenset(
    {"attestation_status", "source_revision", "image_id", "repository_digests", "runtime_revision"}
)
_UNATTESTED_BUILD_FIELDS = frozenset({"attestation_status", "reason", "source_revision", "runtime_revision"})
_PROFILE_FIELDS = frozenset({"profile_id", "profile_version", "profile_digest"})
_SUBJECT_FIELDS = frozenset({"tenant_id", "campaign_id", "candidate_id"})
_TERMINAL_FIELDS = frozenset({"status", "request_digest", "result_digest"})


class CanonicalPublisherAttestationError(ValueError):
    """A publisher claim, signing identity, or local trust anchor is invalid."""


def _jsonable(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: _jsonable(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_jsonable(item) for item in value]
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    return value


def _freeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType({key: _freeze(item) for key, item in value.items()})
    if isinstance(value, list):
        return tuple(_freeze(item) for item in value)
    return value


def _canonical_json(value: Mapping[str, Any]) -> bytes:
    encoded = json.dumps(_jsonable(value), sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)
    return encoded.encode("utf-8")


def _closed(value: Any, fields: frozenset[str], label: str) -> dict[str, Any]:
    if not isinstance(value, Mapping) or set(value) != fields:
        raise CanonicalPublisherAttestationError(f"{label} must use its closed schema")
    return dict(value)


def _identifier(value: Any, label: str) -> str:
    if not isinstance(value, str) or _IDENTIFIER.fullmatch(value) is None:
        raise CanonicalPublisherAttestationError(f"{label} is invalid")
    return value


def _digest(value: Any, label: str) -> str:
    if not isinstance(value, str) or _DIGEST.fullmatch(value) is None:
        raise CanonicalPublisherAttestationError(f"{label} is invalid")
    return value


def _b64(value: Any, label: str, *, length: int) -> bytes:
    if not isinstance(value, str) or not value:
        raise CanonicalPublisherAttestationError(f"{label} is invalid")
    try:
        decoded = base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
    except (ValueError, binascii.Error) as exc:
        raise CanonicalPublisherAttestationError(f"{label} is invalid") from exc
    if len(decoded) != length or base64.urlsafe_b64encode(decoded).decode("ascii").rstrip("=") != value:
        raise CanonicalPublisherAttestationError(f"{label} is not canonical URL-safe base64")
    return decoded


def _project_content_root(package: CanonicalProjectPackage) -> dict[str, str]:
    return {
        "schema_version": CANONICAL_PROJECT_CONTENT_ROOT_VERSION,
        "package_sha256": package.archive_sha256,
        "capsule_digest": package.capsule.capsule_digest,
        "artifact_digest": package.artifact.artifact_digest,
        "application_plan_digest": package.application_plan.application_plan_digest,
        "graph_digest": package.application_plan.payload["graph_digest"],
        "validation_execution_digest": package.application_plan.payload["validation_execution_digest"],
        "full_refit_evidence_digest": package.application_plan.payload["full_refit_evidence_digest"],
        "full_refit_execution_digest": package.application_plan.payload["full_refit_execution_digest"],
    }


def _validate_content_root(value: Any) -> dict[str, str]:
    root = _closed(value, _CONTENT_ROOT_FIELDS, "canonical project content root")
    if root["schema_version"] != CANONICAL_PROJECT_CONTENT_ROOT_VERSION:
        raise CanonicalPublisherAttestationError("canonical project content-root schema is unsupported")
    for field in _CONTENT_ROOT_FIELDS - {"schema_version"}:
        root[field] = _digest(root[field], f"project_content_root.{field}")
    return root


def _validate_statement(value: Any) -> dict[str, Any]:
    statement = _closed(value, _STATEMENT_FIELDS, "canonical publisher statement")
    if statement["schema_version"] != CANONICAL_PUBLISHER_ATTESTATION_VERSION:
        raise CanonicalPublisherAttestationError("canonical publisher statement schema is unsupported")
    if statement["purpose"] != CANONICAL_PUBLISHER_ATTESTATION_PURPOSE:
        raise CanonicalPublisherAttestationError("canonical publisher statement purpose is unsupported")
    for field in ("issuer", "signer_key_id", "key_custody_ref", "claim_scope", "confirmation_disposition"):
        statement[field] = _identifier(statement[field], field)
    statement["project_content_root"] = _validate_content_root(statement["project_content_root"])

    if not isinstance(statement["executing_build"], Mapping):
        raise CanonicalPublisherAttestationError("executing_build must be an object")
    build_status = statement["executing_build"].get("attestation_status")
    if build_status == "attested":
        build = _closed(statement["executing_build"], _ATTESTED_BUILD_FIELDS, "executing_build")
    elif build_status == "not_attested":
        build = _closed(statement["executing_build"], _UNATTESTED_BUILD_FIELDS, "executing_build")
        if build["reason"] != "local_process_has_no_container_build_identity":
            raise CanonicalPublisherAttestationError("executing_build.reason is unsupported")
    else:
        raise CanonicalPublisherAttestationError("executing_build.attestation_status is unsupported")
    if (
        not isinstance(build["source_revision"], str)
        or _GIT_SHA.fullmatch(build["source_revision"]) is None
        or build["source_revision"] == "0" * 40
    ):
        raise CanonicalPublisherAttestationError("executing_build.source_revision is invalid")
    if (
        not isinstance(build["runtime_revision"], str)
        or _GIT_SHA.fullmatch(build["runtime_revision"]) is None
        or build["runtime_revision"] == "0" * 40
    ):
        raise CanonicalPublisherAttestationError("executing_build.runtime_revision is invalid")
    if build["source_revision"] != build["runtime_revision"]:
        raise CanonicalPublisherAttestationError("executing build source and runtime revisions do not agree")
    if build_status == "attested":
        if not isinstance(build["image_id"], str) or _IMAGE_ID.fullmatch(build["image_id"]) is None:
            raise CanonicalPublisherAttestationError("executing_build.image_id is invalid")
        repository_digests = build["repository_digests"]
        if (
            not isinstance(repository_digests, list)
            or not repository_digests
            or repository_digests != sorted(set(repository_digests))
            or any(
                not isinstance(item, str) or _REPOSITORY_DIGEST.fullmatch(item) is None for item in repository_digests
            )
        ):
            raise CanonicalPublisherAttestationError("executing_build.repository_digests is invalid")
    statement["executing_build"] = build

    profile = _closed(statement["runtime_profile"], _PROFILE_FIELDS, "runtime_profile")
    profile["profile_id"] = _identifier(profile["profile_id"], "runtime_profile.profile_id")
    profile["profile_version"] = _identifier(profile["profile_version"], "runtime_profile.profile_version")
    profile["profile_digest"] = _digest(profile["profile_digest"], "runtime_profile.profile_digest")
    statement["runtime_profile"] = profile

    subject = _closed(statement["subject"], _SUBJECT_FIELDS, "subject")
    for field in _SUBJECT_FIELDS:
        subject[field] = _identifier(subject[field], f"subject.{field}")
    statement["subject"] = subject

    terminal = _closed(statement["terminal"], _TERMINAL_FIELDS, "terminal")
    if terminal["status"] != "succeeded":
        raise CanonicalPublisherAttestationError("terminal.status must be succeeded")
    terminal["request_digest"] = _digest(terminal["request_digest"], "terminal.request_digest")
    terminal["result_digest"] = _digest(terminal["result_digest"], "terminal.result_digest")
    statement["terminal"] = terminal
    if statement["decision"] is not None:
        statement["decision"] = _identifier(statement["decision"], "decision")
    return statement


def _validate_input(value: Any) -> dict[str, Any]:
    input_value = _closed(value, _INPUT_FIELDS, "canonical publisher attestation input")
    if input_value["schema_version"] != CANONICAL_PUBLISHER_ATTESTATION_INPUT_VERSION:
        raise CanonicalPublisherAttestationError("canonical publisher attestation input schema is unsupported")
    # Reuse the signed-statement validator for every semantic field. The three
    # issuer/key/build fields are deliberately unavailable until the managed
    # host has inspected its actual image identity and selected key custody.
    placeholder = _validate_statement(
        {
            "schema_version": CANONICAL_PUBLISHER_ATTESTATION_VERSION,
            "purpose": CANONICAL_PUBLISHER_ATTESTATION_PURPOSE,
            "issuer": "pending-host-attestation",
            "signer_key_id": "pending-host-attestation",
            "key_custody_ref": "pending-host-attestation",
            "project_content_root": input_value["project_content_root"],
            "executing_build": {
                "attestation_status": "attested",
                "source_revision": "1" * 40,
                "image_id": "sha256:" + "0" * 64,
                "repository_digests": ["pending@sha256:" + "0" * 64],
                "runtime_revision": "1" * 40,
            },
            "runtime_profile": input_value["runtime_profile"],
            "subject": input_value["subject"],
            "terminal": input_value["terminal"],
            "decision": input_value["decision"],
            "claim_scope": input_value["claim_scope"],
            "confirmation_disposition": input_value["confirmation_disposition"],
        }
    )
    return {
        "schema_version": CANONICAL_PUBLISHER_ATTESTATION_INPUT_VERSION,
        **{key: placeholder[key] for key in _INPUT_FIELDS - {"schema_version"}},
    }


@dataclass(frozen=True)
class CanonicalProjectContentRoot:
    """The exact package identities a publisher may sign, without a key."""

    payload: Mapping[str, str]
    digest: str

    @classmethod
    def from_package(cls, package: CanonicalProjectPackage) -> "CanonicalProjectContentRoot":
        if not isinstance(package, CanonicalProjectPackage):
            raise CanonicalPublisherAttestationError("canonical project package is required")
        payload = _project_content_root(package)
        return cls(MappingProxyType(payload), hashlib.sha256(_canonical_json(payload)).hexdigest())

    def as_dict(self) -> dict[str, str]:
        return dict(self.payload)


@dataclass(frozen=True)
class CanonicalPublisherAttestationInput:
    """Managed terminal facts awaiting host-observed build identity and signing.

    This object is deliberately unsigned.  Its package-root, profile, and
    request facts are locally cross-checkable; its terminal result digest is a
    managed fact which becomes attributable only when the deployment host
    signs it.  The host must obtain this input through its authenticated
    server-control path, never from an arbitrary project recipient.
    """

    payload: Mapping[str, Any]
    digest: str

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "CanonicalPublisherAttestationInput":
        normalized = _validate_input(value)
        return cls(_freeze(normalized), hashlib.sha256(_canonical_json(normalized)).hexdigest())

    @classmethod
    def from_package(
        cls,
        package: CanonicalProjectPackage,
        *,
        tenant_id: str,
        terminal_result_digest: str,
        decision: str | None,
        claim_scope: str,
        confirmation_disposition: str,
    ) -> "CanonicalPublisherAttestationInput":
        if not isinstance(package, CanonicalProjectPackage):
            raise CanonicalPublisherAttestationError("canonical project package is required")
        request = package.capsule.payload["admitted_request"]
        return cls.from_dict(
            {
                "schema_version": CANONICAL_PUBLISHER_ATTESTATION_INPUT_VERSION,
                "project_content_root": CanonicalProjectContentRoot.from_package(package).as_dict(),
                "runtime_profile": request["profile"],
                "subject": {
                    "tenant_id": tenant_id,
                    "campaign_id": request["campaign_id"],
                    "candidate_id": request["candidate_id"],
                },
                "terminal": {
                    "status": "succeeded",
                    "request_digest": request["request_digest"],
                    "result_digest": terminal_result_digest,
                },
                "decision": decision,
                "claim_scope": claim_scope,
                "confirmation_disposition": confirmation_disposition,
            }
        )

    def as_dict(self) -> dict[str, Any]:
        return json.loads(self.canonical_bytes)

    @property
    def canonical_bytes(self) -> bytes:
        return _canonical_json(self.payload)

    def require_matches_package(self, package: CanonicalProjectPackage) -> None:
        expected = CanonicalProjectContentRoot.from_package(package).as_dict()
        if dict(self.payload["project_content_root"]) != expected:
            raise CanonicalPublisherAttestationError("publisher attestation input does not bind this canonical project")
        request = package.capsule.payload["admitted_request"]
        if (
            self.payload["runtime_profile"] != request["profile"]
            or self.payload["subject"]["campaign_id"] != request["campaign_id"]
            or self.payload["subject"]["candidate_id"] != request["candidate_id"]
            or self.payload["terminal"]["request_digest"] != request["request_digest"]
        ):
            raise CanonicalPublisherAttestationError("publisher attestation input differs from canonical project")

    def to_statement(
        self,
        *,
        issuer: str,
        signer_key_id: str,
        key_custody_ref: str,
        executing_build: Mapping[str, Any],
    ) -> dict[str, Any]:
        return _validate_statement(
            {
                "schema_version": CANONICAL_PUBLISHER_ATTESTATION_VERSION,
                "purpose": CANONICAL_PUBLISHER_ATTESTATION_PURPOSE,
                "issuer": issuer,
                "signer_key_id": signer_key_id,
                "key_custody_ref": key_custody_ref,
                "project_content_root": self.payload["project_content_root"],
                "executing_build": dict(executing_build),
                "runtime_profile": self.payload["runtime_profile"],
                "subject": self.payload["subject"],
                "terminal": self.payload["terminal"],
                "decision": self.payload["decision"],
                "claim_scope": self.payload["claim_scope"],
                "confirmation_disposition": self.payload["confirmation_disposition"],
            }
        )


@dataclass(frozen=True)
class CanonicalPublisherTrustAnchors:
    """A portable, recipient-supplied trust-anchor document."""

    issuer: str
    public_keys: Mapping[str, str]

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "CanonicalPublisherTrustAnchors":
        document = _closed(value, _TRUST_ANCHOR_FIELDS, "canonical publisher trust anchors")
        if document["schema_version"] != CANONICAL_PUBLISHER_TRUST_ANCHORS_VERSION:
            raise CanonicalPublisherAttestationError("canonical publisher trust-anchor schema is unsupported")
        issuer = _identifier(document["issuer"], "publisher trust-anchor issuer")
        keys = document["keys"]
        if not isinstance(keys, Mapping) or not keys:
            raise CanonicalPublisherAttestationError("canonical publisher trust anchors are invalid")
        normalized = {
            _identifier(key_id, "publisher trust-anchor key id"): base64.urlsafe_b64encode(
                _b64(encoded, "publisher trust-anchor public key", length=32)
            )
            .decode("ascii")
            .rstrip("=")
            for key_id, encoded in keys.items()
        }
        if len(normalized) != len(keys):
            raise CanonicalPublisherAttestationError("canonical publisher trust-anchor keys are duplicated")
        return cls(issuer=issuer, public_keys=MappingProxyType(normalized))

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": CANONICAL_PUBLISHER_TRUST_ANCHORS_VERSION,
            "issuer": self.issuer,
            "keys": dict(self.public_keys),
        }


@dataclass(frozen=True)
class SignedCanonicalProjectAttestation:
    """One publisher signature over a closed canonical-project statement."""

    statement: Mapping[str, Any]
    signature: bytes

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "SignedCanonicalProjectAttestation":
        signed = _closed(value, _SIGNED_FIELDS, "signed canonical publisher attestation")
        statement = _validate_statement(signed["statement"])
        signature = _b64(signed["signature"], "canonical publisher signature", length=64)
        return cls(_freeze(statement), signature)

    @property
    def canonical_statement(self) -> bytes:
        return _canonical_json(self.statement)

    @property
    def digest(self) -> str:
        return hashlib.sha256(self.canonical_bytes).hexdigest()

    @property
    def canonical_bytes(self) -> bytes:
        return _canonical_json(self.as_dict())

    def as_dict(self) -> dict[str, Any]:
        return {
            "statement": json.loads(self.canonical_statement),
            "signature": base64.urlsafe_b64encode(self.signature).decode("ascii").rstrip("="),
        }

    def verify(self, public_key: Ed25519PublicKey) -> None:
        try:
            public_key.verify(self.signature, self.canonical_statement)
        except InvalidSignature as exc:
            raise CanonicalPublisherAttestationError("canonical publisher signature is invalid") from exc

    def require_matches_package(self, package: CanonicalProjectPackage) -> None:
        expected = CanonicalProjectContentRoot.from_package(package).as_dict()
        if dict(self.statement["project_content_root"]) != expected:
            raise CanonicalPublisherAttestationError("publisher statement does not bind this canonical project package")
        request = package.capsule.payload["admitted_request"]
        if (
            self.statement["runtime_profile"] != request["profile"]
            or self.statement["subject"]["campaign_id"] != request["campaign_id"]
            or self.statement["subject"]["candidate_id"] != request["candidate_id"]
            or self.statement["terminal"]["request_digest"] != request["request_digest"]
        ):
            raise CanonicalPublisherAttestationError("publisher statement differs from the canonical package")


class CanonicalProjectAttestationSigner:
    """Purpose-separated managed custody for canonical project attestations."""

    def __init__(self, *, issuer: str, key_id: str, custody_ref: str, private_key: Ed25519PrivateKey) -> None:
        self.issuer = _identifier(issuer, "issuer")
        self.key_id = _identifier(key_id, "signer_key_id")
        self.custody_ref = _identifier(custody_ref, "key_custody_ref")
        if not isinstance(private_key, Ed25519PrivateKey):
            raise CanonicalPublisherAttestationError("canonical publisher private key is invalid")
        self._private_key = private_key

    @classmethod
    def from_private_key_file(
        cls,
        *,
        issuer: str,
        key_id: str,
        custody_ref: str,
        path: Path,
    ) -> "CanonicalProjectAttestationSigner":
        # The managed signing deployment is a POSIX host.  This loader's
        # custody boundary is the owner-only regular file contract below;
        # Windows' synthetic mode bits cannot attest that equivalent ACL
        # property.  Refuse to sign there rather than silently weakening
        # private-key custody.  OSS verification remains cross-platform.
        if os.name != "posix":
            raise CanonicalPublisherAttestationError("canonical publisher signing requires a POSIX custody host")
        if not isinstance(path, Path) or not path.is_absolute():
            raise CanonicalPublisherAttestationError("canonical publisher key path must be absolute")
        nofollow = getattr(os, "O_NOFOLLOW", None)
        if nofollow is None:  # pragma: no cover - the POSIX signing hosts expose O_NOFOLLOW
            raise CanonicalPublisherAttestationError("canonical publisher key no-follow admission is unavailable")
        descriptor = -1
        try:
            descriptor = os.open(path, os.O_RDONLY | nofollow | getattr(os, "O_CLOEXEC", 0))
            before = os.fstat(descriptor)
            if not stat.S_ISREG(before.st_mode):
                raise CanonicalPublisherAttestationError("canonical publisher key must be a regular non-symlink file")
            process_uid = os.getuid()
            if before.st_uid == process_uid:
                # An app-owned key is private to the signing principal.
                unsafe_permissions = bool(before.st_mode & (stat.S_IRWXG | stat.S_IRWXO))
            elif before.st_uid == 0:
                # Docker/OCI secret mounts are conventionally root-owned and
                # made readable to the non-root workload.  Root remains the
                # external custody principal; the workload must never admit a
                # group/world-writable or executable secret.
                unsafe_permissions = bool(before.st_mode & (stat.S_IWGRP | stat.S_IWOTH | stat.S_IXGRP | stat.S_IXOTH))
            else:
                unsafe_permissions = True
            if unsafe_permissions:
                raise CanonicalPublisherAttestationError("canonical publisher key permissions are unsafe")
            if before.st_size <= 0 or before.st_size > 256:
                raise CanonicalPublisherAttestationError("canonical publisher key size is invalid")
            chunks: list[bytes] = []
            remaining = before.st_size + 1
            while remaining:
                chunk = os.read(descriptor, min(remaining, 256))
                if not chunk:
                    break
                chunks.append(chunk)
                remaining -= len(chunk)
            encoded = b"".join(chunks)
            after = os.fstat(descriptor)
            identity_before = (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
            identity_after = (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)
            if identity_after != identity_before or len(encoded) != before.st_size:
                raise CanonicalPublisherAttestationError("canonical publisher key changed during admission")
            try:
                text = encoded.decode("utf-8").strip()
            except UnicodeDecodeError as exc:
                raise CanonicalPublisherAttestationError("canonical publisher key is not UTF-8") from exc
            raw = _b64(text, "canonical publisher private key", length=32)
        except OSError as exc:
            if exc.errno == errno.ELOOP:
                raise CanonicalPublisherAttestationError(
                    "canonical publisher key must be a regular non-symlink file"
                ) from exc
            raise CanonicalPublisherAttestationError("canonical publisher key cannot be read") from exc
        finally:
            if descriptor >= 0:
                os.close(descriptor)
        return cls(
            issuer=issuer,
            key_id=key_id,
            custody_ref=custody_ref,
            private_key=Ed25519PrivateKey.from_private_bytes(raw),
        )

    def public_key_b64(self) -> str:
        raw = self._private_key.public_key().public_bytes_raw()
        return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")

    def sign(self, statement: Mapping[str, Any]) -> SignedCanonicalProjectAttestation:
        normalized = _validate_statement(statement)
        if (
            normalized["issuer"] != self.issuer
            or normalized["signer_key_id"] != self.key_id
            or normalized["key_custody_ref"] != self.custody_ref
        ):
            raise CanonicalPublisherAttestationError("canonical publisher statement differs from signing identity")
        signature = self._private_key.sign(_canonical_json(normalized))
        return SignedCanonicalProjectAttestation(_freeze(normalized), signature)


class LocalCanonicalPublisherTrustStore:
    """Verify a publisher claim only against recipient-supplied anchors."""

    def __init__(self, public_keys: Mapping[str, str], *, issuer: str | None = None) -> None:
        if not isinstance(public_keys, Mapping) or not public_keys:
            raise CanonicalPublisherAttestationError("at least one local publisher trust anchor is required")
        anchors: dict[str, Ed25519PublicKey] = {}
        for key_id, encoded in public_keys.items():
            anchors[_identifier(key_id, "publisher trust-anchor key id")] = Ed25519PublicKey.from_public_bytes(
                _b64(encoded, "publisher trust-anchor public key", length=32)
            )
        self._anchors = MappingProxyType(anchors)
        self._issuer = _identifier(issuer, "publisher trust-anchor issuer") if issuer is not None else None

    @classmethod
    def from_document(cls, document: CanonicalPublisherTrustAnchors) -> "LocalCanonicalPublisherTrustStore":
        if not isinstance(document, CanonicalPublisherTrustAnchors):
            raise CanonicalPublisherAttestationError("canonical publisher trust-anchor document is required")
        return cls(document.public_keys, issuer=document.issuer)

    def verify(
        self,
        *,
        package: CanonicalProjectPackage,
        attestation: SignedCanonicalProjectAttestation,
    ) -> str:
        if not isinstance(attestation, SignedCanonicalProjectAttestation):
            raise CanonicalPublisherAttestationError("signed canonical publisher attestation is required")
        try:
            if self._issuer is not None and attestation.statement["issuer"] != self._issuer:
                raise CanonicalPublisherAttestationError("canonical publisher issuer is not trusted")
            signer = self._anchors[attestation.statement["signer_key_id"]]
            attestation.verify(signer)
            attestation.require_matches_package(package)
        except (CanonicalPublisherAttestationError, KeyError) as exc:
            raise CanonicalPublisherAttestationError("canonical project publisher is not authenticated") from exc
        return attestation.digest


__all__ = [
    "CANONICAL_PROJECT_CONTENT_ROOT_VERSION",
    "CANONICAL_PUBLISHER_ATTESTATION_INPUT_VERSION",
    "CANONICAL_PUBLISHER_ATTESTATION_PURPOSE",
    "CANONICAL_PUBLISHER_ATTESTATION_VERSION",
    "CANONICAL_PUBLISHER_TRUST_ANCHORS_VERSION",
    "CanonicalProjectAttestationSigner",
    "CanonicalProjectContentRoot",
    "CanonicalPublisherAttestationInput",
    "CanonicalPublisherAttestationError",
    "CanonicalPublisherTrustAnchors",
    "LocalCanonicalPublisherTrustStore",
    "SignedCanonicalProjectAttestation",
]
