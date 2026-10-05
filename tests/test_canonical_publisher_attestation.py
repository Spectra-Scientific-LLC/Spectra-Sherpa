"""Offline publisher-authentication tests for canonical project packages."""

from __future__ import annotations

import base64
import hashlib
import os
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from spectra_sherpa.app.types import type_registry
from spectra_sherpa.sdk.canonical_confirmation_history import CanonicalConfirmationHistory
from spectra_sherpa.sdk.canonical_project import CanonicalProjectPackage
from spectra_sherpa.sdk.canonical_publisher_attestation import (
    CANONICAL_PUBLISHER_ATTESTATION_PURPOSE,
    CANONICAL_PUBLISHER_ATTESTATION_VERSION,
    CanonicalProjectAttestationSigner,
    CanonicalProjectContentRoot,
    CanonicalPublisherAttestationError,
    CanonicalPublisherAttestationInput,
    CanonicalPublisherTrustAnchors,
    LocalCanonicalPublisherTrustStore,
    SignedCanonicalProjectAttestation,
)
from tests.test_canonical_project_package import _package


@pytest.fixture(autouse=True)
def _load_type_registry() -> None:
    """The package fixture is an authentic typed-DAG construction."""

    if not type_registry.is_loaded:
        type_registry.load(Path(__file__).resolve().parents[1] / "src" / "spectra_sherpa" / "app" / "types")


def _statement(package: CanonicalProjectPackage, *, key_id: str = "publisher-key-001") -> dict:
    request = package.capsule.payload["admitted_request"]
    return {
        "schema_version": CANONICAL_PUBLISHER_ATTESTATION_VERSION,
        "purpose": CANONICAL_PUBLISHER_ATTESTATION_PURPOSE,
        "issuer": "spectra-managed-staging",
        "signer_key_id": key_id,
        "key_custody_ref": "urn:spectra:publisher-key:staging-001",
        "project_content_root": CanonicalProjectContentRoot.from_package(package).as_dict(),
        "executing_build": {
            "attestation_status": "attested",
            "source_revision": "a" * 40,
            "image_id": "sha256:" + "b" * 64,
            "repository_digests": ["spectra-backend@sha256:" + "c" * 64],
            "runtime_revision": "a" * 40,
        },
        "runtime_profile": request["profile"],
        "subject": {
            "tenant_id": "tenant-staging-001",
            "campaign_id": request["campaign_id"],
            "candidate_id": request["candidate_id"],
        },
        "terminal": {
            "status": "succeeded",
            "request_digest": request["request_digest"],
            "result_digest": hashlib.sha256(b"canonical terminal result").hexdigest(),
        },
        "decision": "canonical-selection-policy:" + "d" * 64,
        "claim_scope": "public_reproducibility_only",
        "confirmation_disposition": "not_requested",
    }


def _signer(*, key_id: str = "publisher-key-001") -> CanonicalProjectAttestationSigner:
    return CanonicalProjectAttestationSigner(
        issuer="spectra-managed-staging",
        key_id=key_id,
        custody_ref="urn:spectra:publisher-key:staging-001",
        private_key=Ed25519PrivateKey.generate(),
    )


def test_external_anchor_authenticates_the_exact_canonical_project_package() -> None:
    package = _package()
    signer = _signer()
    signed = signer.sign(_statement(package))
    reloaded = SignedCanonicalProjectAttestation.from_dict(signed.as_dict())

    trust = LocalCanonicalPublisherTrustStore({"publisher-key-001": signer.public_key_b64()})
    assert trust.verify(package=package, attestation=reloaded) == reloaded.digest
    assert reloaded.statement["project_content_root"]["package_sha256"] == package.archive_sha256


def test_signature_cannot_authenticate_a_different_valid_package() -> None:
    package = _package()
    signer = _signer()
    signed = signer.sign(_statement(package))
    unrelated = CanonicalProjectPackage.build(
        capsule=package.capsule,
        artifact=package.artifact,
        application_plan=package.application_plan,
        local_model_record=package.local_model_record,
        campaign_evidence=package.campaign_evidence,
        confirmation_history=CanonicalConfirmationHistory.not_requested(
            campaign_id=package.campaign_evidence.payload["campaign"]["campaign_id"], campaign_record_id=1
        ),
        project_name="An independently named package",
    )

    # The second package has identical fixture semantics but independently
    # generated archive bytes; publisher authenticity is content-root exact.
    assert unrelated.archive_sha256 != package.archive_sha256
    trust = LocalCanonicalPublisherTrustStore({"publisher-key-001": signer.public_key_b64()})
    with pytest.raises(CanonicalPublisherAttestationError, match="not authenticated"):
        trust.verify(package=unrelated, attestation=signed)


def test_unknown_or_modified_publisher_statement_fails_closed() -> None:
    package = _package()
    signer = _signer()
    signed = signer.sign(_statement(package))
    value = signed.as_dict()
    value["statement"]["claim_scope"] = "scientifically_proven"
    forged = SignedCanonicalProjectAttestation.from_dict(value)

    trust = LocalCanonicalPublisherTrustStore({"publisher-key-001": signer.public_key_b64()})
    with pytest.raises(CanonicalPublisherAttestationError, match="not authenticated"):
        trust.verify(package=package, attestation=forged)
    with pytest.raises(CanonicalPublisherAttestationError, match="not authenticated"):
        LocalCanonicalPublisherTrustStore({"other-publisher": signer.public_key_b64()}).verify(
            package=package,
            attestation=signed,
        )


def test_trust_anchor_document_binds_the_publisher_issuer_as_well_as_key_id() -> None:
    package = _package()
    signer = _signer()
    signed = signer.sign(_statement(package))
    anchors = CanonicalPublisherTrustAnchors.from_dict(
        {
            "schema_version": "spectra-canonical-publisher-trust-anchors/1",
            "issuer": "a-different-managed-publisher",
            "keys": {"publisher-key-001": signer.public_key_b64()},
        }
    )

    with pytest.raises(CanonicalPublisherAttestationError, match="not authenticated"):
        LocalCanonicalPublisherTrustStore.from_document(anchors).verify(package=package, attestation=signed)


def test_content_root_is_data_free_and_covers_all_package_identity_digests() -> None:
    package = _package()
    root = CanonicalProjectContentRoot.from_package(package)

    assert set(root.as_dict()) == {
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
    assert all("data" not in field for field in root.as_dict())


def test_publisher_statement_rejects_a_disagreeing_source_and_runtime_revision() -> None:
    package = _package()
    statement = _statement(package)
    statement["executing_build"]["runtime_revision"] = "d" * 40

    with pytest.raises(CanonicalPublisherAttestationError, match="source and runtime revisions do not agree"):
        _signer().sign(statement)


def test_local_qualification_build_is_explicitly_unattested_and_cannot_claim_zero_revision() -> None:
    package = _package()
    statement = _statement(package)
    statement["executing_build"] = {
        "attestation_status": "not_attested",
        "reason": "local_process_has_no_container_build_identity",
        "source_revision": "d" * 40,
        "runtime_revision": "d" * 40,
    }
    signed = _signer().sign(statement)
    assert signed.statement["executing_build"]["attestation_status"] == "not_attested"
    assert "image_id" not in signed.statement["executing_build"]

    statement["executing_build"]["source_revision"] = "0" * 40
    statement["executing_build"]["runtime_revision"] = "0" * 40
    with pytest.raises(CanonicalPublisherAttestationError, match="source_revision is invalid"):
        _signer().sign(statement)


def test_build_attestation_cannot_mix_local_and_container_fields() -> None:
    statement = _statement(_package())
    statement["executing_build"]["reason"] = "local_process_has_no_container_build_identity"
    with pytest.raises(CanonicalPublisherAttestationError, match="closed schema"):
        _signer().sign(statement)


def test_managed_attestation_key_file_requires_private_regular_file(tmp_path: Path) -> None:
    private_key = Ed25519PrivateKey.generate()
    key_file = tmp_path / "publisher-key"
    raw = private_key.private_bytes_raw()
    key_file.write_text(base64.urlsafe_b64encode(raw).decode("ascii").rstrip("="), encoding="utf-8")
    key_file.chmod(0o600)

    if os.name != "posix":
        with pytest.raises(CanonicalPublisherAttestationError, match="requires a POSIX custody host"):
            CanonicalProjectAttestationSigner.from_private_key_file(
                issuer="spectra-managed-staging",
                key_id="publisher-key-001",
                custody_ref="urn:spectra:publisher-key:staging-001",
                path=key_file,
            )
        return

    loaded = CanonicalProjectAttestationSigner.from_private_key_file(
        issuer="spectra-managed-staging",
        key_id="publisher-key-001",
        custody_ref="urn:spectra:publisher-key:staging-001",
        path=key_file,
    )
    assert loaded.public_key_b64()

    key_file.chmod(0o640)
    with pytest.raises(CanonicalPublisherAttestationError, match="permissions are unsafe"):
        CanonicalProjectAttestationSigner.from_private_key_file(
            issuer="spectra-managed-staging",
            key_id="publisher-key-001",
            custody_ref="urn:spectra:publisher-key:staging-001",
            path=key_file,
        )

    key_file.chmod(0o600)
    link = tmp_path / "publisher-key-link"
    os.symlink(key_file, link)
    with pytest.raises(CanonicalPublisherAttestationError, match="non-symlink"):
        CanonicalProjectAttestationSigner.from_private_key_file(
            issuer="spectra-managed-staging",
            key_id="publisher-key-001",
            custody_ref="urn:spectra:publisher-key:staging-001",
            path=link,
        )


@pytest.mark.skipif(os.name != "posix", reason="publisher signing is POSIX-only")
def test_managed_attestation_key_accepts_root_owned_read_only_container_secret(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    key_file = tmp_path / "publisher-key"
    key_file.write_text(
        base64.urlsafe_b64encode(Ed25519PrivateKey.generate().private_bytes_raw()).decode("ascii").rstrip("="),
        encoding="utf-8",
    )
    key_file.chmod(0o444)
    real_fstat = os.fstat

    def _root_owned(descriptor: int) -> os.stat_result:
        values = list(real_fstat(descriptor))
        values[4] = 0  # st_uid
        return os.stat_result(values)

    monkeypatch.setattr(os, "fstat", _root_owned)
    loaded = CanonicalProjectAttestationSigner.from_private_key_file(
        issuer="spectra-managed-staging",
        key_id="publisher-key-001",
        custody_ref="urn:spectra:publisher-key:staging-001",
        path=key_file,
    )
    assert loaded.public_key_b64()

    key_file.chmod(0o466)
    with pytest.raises(CanonicalPublisherAttestationError, match="permissions are unsafe"):
        CanonicalProjectAttestationSigner.from_private_key_file(
            issuer="spectra-managed-staging",
            key_id="publisher-key-001",
            custody_ref="urn:spectra:publisher-key:staging-001",
            path=key_file,
        )


@pytest.mark.skipif(os.name != "posix", reason="publisher signing is POSIX-only")
def test_managed_attestation_key_file_refuses_a_path_swap_before_open(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    admitted = tmp_path / "publisher-key"
    replacement = tmp_path / "replacement-key"
    for path in (admitted, replacement):
        path.write_text(
            base64.urlsafe_b64encode(Ed25519PrivateKey.generate().private_bytes_raw()).decode("ascii").rstrip("="),
            encoding="utf-8",
        )
        path.chmod(0o600)
    real_open = os.open

    def swap_then_open(path: os.PathLike[str] | str, flags: int, *args: object, **kwargs: object) -> int:
        admitted.unlink()
        os.symlink(replacement, admitted)
        monkeypatch.setattr(os, "open", real_open)
        return real_open(path, flags, *args, **kwargs)

    monkeypatch.setattr(os, "open", swap_then_open)
    with pytest.raises(CanonicalPublisherAttestationError, match="non-symlink"):
        CanonicalProjectAttestationSigner.from_private_key_file(
            issuer="spectra-managed-staging",
            key_id="publisher-key-001",
            custody_ref="urn:spectra:publisher-key:staging-001",
            path=admitted,
        )


def test_attestation_input_binds_server_terminal_facts_before_host_signing() -> None:
    package = _package()
    input_value = CanonicalPublisherAttestationInput.from_package(
        package,
        tenant_id="tenant-staging-001",
        terminal_result_digest="d" * 64,
        decision="canonical-selection-policy:" + "d" * 64,
        claim_scope="public_reproducibility_only",
        confirmation_disposition="not_requested",
    )
    loaded = CanonicalPublisherAttestationInput.from_dict(input_value.as_dict())
    loaded.require_matches_package(package)

    signer = _signer()
    signed = signer.sign(
        loaded.to_statement(
            issuer="spectra-managed-staging",
            signer_key_id="publisher-key-001",
            key_custody_ref="urn:spectra:publisher-key:staging-001",
            executing_build=_statement(package)["executing_build"],
        )
    )
    anchors = CanonicalPublisherTrustAnchors.from_dict(
        {
            "schema_version": "spectra-canonical-publisher-trust-anchors/1",
            "issuer": "spectra-managed-staging",
            "keys": {"publisher-key-001": signer.public_key_b64()},
        }
    )
    assert LocalCanonicalPublisherTrustStore.from_document(anchors).verify(package=package, attestation=signed)
