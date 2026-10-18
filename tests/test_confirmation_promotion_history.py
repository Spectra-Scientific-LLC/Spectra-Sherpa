"""Admitted signed confirmation history survives shared promotion review."""

import hashlib
from copy import deepcopy
from dataclasses import replace

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from spectra_sherpa.app.models.analytical_qualification import AnalyticalQualificationRecord
from spectra_sherpa.app.models.application_release import ApplicationRelease
from spectra_sherpa.app.models.canonical_project_artifact import CanonicalProjectArtifact
from spectra_sherpa.app.models.project import Project
from spectra_sherpa.app.services import canonical_project_custody
from spectra_sherpa.app.services.canonical_project_import import import_canonical_project
from spectra_sherpa.app.services.dataset_use import imported_confirmation_dataset_use
from spectra_sherpa.sdk.canonical_confirmation_history import (
    CanonicalConfirmationHistory,
    CanonicalConfirmationHistoryError,
)
from spectra_sherpa.sdk.canonical_project import CanonicalProjectPackage
from tests.test_analytical_qualification import assess
from tests.test_canonical_confirmation_history import _grant, _issued_attempt
from tests.test_canonical_project_import import _PACKAGE
from tests.test_prediction_uncertainty import runtime as uncertainty_runtime
from tests.test_receipt_verification import _b64, _canonical, _receipt_fixture

runtime = uncertainty_runtime


def succeeded_history(package):
    """Use the real closed receipt serializer/signature verifier, not mocked admission."""
    grant = _grant()
    grant.update(capsule_digest=package.capsule.capsule_digest, valid_result_released=True)
    template, keys, anchors = _receipt_fixture()
    receipts = []
    for sequence, (event, disposition) in enumerate(
        [("authorization_consumed", "consumed"), ("attempt_terminal", "succeeded")], start=1
    ):
        receipt = deepcopy(template)
        payload = receipt["payload"]
        prior = receipts[-1]["receipt_digest"] if receipts else None
        payload.update(
            event_kind=event,
            disposition=disposition,
            ledger_sequence=sequence,
            prior_receipt_digest=prior,
            campaign={"campaign_id": 17, "grant_id": grant["grant_id"]},
            candidate={"frozen_request_digest": grant["frozen_request_digest"]},
            authorization={"authorization_id": "authorization-001", "kind": "original"},
            benchmark={
                "benchmark_id": grant["benchmark_id"],
                "status": grant["benchmark_status"],
                "confirmation_split_digest": grant["confirmation_split_digest"],
                "dataset_role": "confirmation",
            },
            protocol={
                "preregistration_digest": grant["preregistration_digest"],
                "protocol_digest": grant["protocol_digest"],
            },
            request={
                "capsule_digest": grant["capsule_digest"],
                "requested_metrics_digest": grant["requested_metrics_digest"],
            },
            result_digest="1" * 64,
            evidence_digest="2" * 64,
        )
        digest = hashlib.sha256(bytes.fromhex(prior) if prior else bytes(32))
        digest.update(_canonical(payload))
        receipt_digest = digest.hexdigest()
        receipt.update(
            public_id=f"receipt-{sequence}",
            ledger_sequence=sequence,
            event_kind=event,
            disposition=disposition,
            prior_receipt_digest=prior,
            receipt_digest=receipt_digest,
            payload_digest=hashlib.sha256(_canonical(payload)).hexdigest(),
            signature=_b64(Ed25519PrivateKey.from_private_bytes(bytes(range(32))).sign(bytes.fromhex(receipt_digest))),
        )
        receipts.append(receipt)
    attempt = _issued_attempt()
    attempt.update(
        attempt_id="attempt-001",
        authorization_status="consumed",
        attempt_status="succeeded",
        authorization_receipt_digest=receipts[0]["receipt_digest"],
        governance_request_digest="e" * 64,
        request_digest="f" * 64,
        result_digest="1" * 64,
        evidence_digest="2" * 64,
        consumed_at=template["created_at"],
        created_at=template["created_at"],
        updated_at=template["created_at"],
    )
    history = CanonicalConfirmationHistory.build(
        campaign_id=package.campaign_evidence.payload["campaign"]["campaign_id"],
        campaign_record_id=17,
        disposition="succeeded",
        grant=grant,
        attempts=[attempt],
        receipts=receipts,
        signing_keys=keys,
    )
    history.verify_receipts(trusted_receipt_keys=anchors)
    return history


def test_changed_signed_confirmation_history_fails_closed():
    history = succeeded_history(_PACKAGE).as_dict()
    history["grant"]["confirmation_content_digest"] = "0" * 64
    with pytest.raises(CanonicalConfirmationHistoryError, match="content digest changed"):
        imported_confirmation_dataset_use(history)
    changed = succeeded_history(_PACKAGE).as_dict()
    changed["receipts"][1]["payload"]["result_digest"] = "0" * 64
    with pytest.raises(CanonicalConfirmationHistoryError, match="receipt chain"):
        imported_confirmation_dataset_use(changed)


@pytest.mark.asyncio
async def test_successful_import_history_survives_rename_and_later_dossier(
    test_session, test_user, auth_client, tmp_path, monkeypatch, runtime
):
    history = succeeded_history(_PACKAGE)
    package = CanonicalProjectPackage.build(
        capsule=_PACKAGE.capsule,
        artifact=_PACKAGE.artifact,
        application_plan=_PACKAGE.application_plan,
        local_model_record=_PACKAGE.local_model_record,
        campaign_evidence=_PACKAGE.campaign_evidence,
        confirmation_history=history,
    )
    monkeypatch.setattr(
        canonical_project_custody, "settings", replace(canonical_project_custody.settings, data_dir=tmp_path)
    )
    imported = await import_canonical_project(
        async_sessionmaker(test_session.bind, expire_on_commit=False),
        user_id=test_user.id,
        archive=package.archive,
        data_dir=tmp_path,
        max_uncompressed_bytes=32 * 1024 * 1024,
    )
    artifact = await test_session.scalar(
        select(CanonicalProjectArtifact).where(CanonicalProjectArtifact.project_id == imported.project_id)
    )
    endpoint = f"/api/v1/deploy/canonical-artifacts/{artifact.id}/promotion-review"
    response = await auth_client.get(endpoint)
    assert response.status_code == 200, response.text
    initial = response.json()["qualification"]["dataset_use"]
    assert initial["populations"][0]["identity"] == history.payload["grant"]["confirmation_content_digest"]
    assert initial["populations"][0]["results_revealed"] is True
    assert initial["populations"][0]["influenced_development"] is None
    assert initial["populations"][0]["basis"] == "declared"
    project = await test_session.get(Project, imported.project_id)
    project.name = "Renamed unseen validation"
    dossier = await assess(runtime, package=package)
    test_session.add(
        AnalyticalQualificationRecord(
            user_id=test_user.id,
            workflow_id=artifact.workflow_id,
            canonical_artifact_id=artifact.id,
            record_digest=dossier.record_digest,
            kind="assessment",
            payload=dossier.model_dump(mode="json"),
        )
    )
    await test_session.commit()
    later = await auth_client.get(endpoint)
    assert later.status_code == 200, later.text
    use = later.json()["qualification"]["dataset_use"]
    assert len(use["populations"]) == 2
    assert initial["populations"][0] in use["populations"]
    assert use["independence"] == "not_established_by_usage_history"
    release = await test_session.scalar(
        select(ApplicationRelease).where(ApplicationRelease.canonical_artifact_id == artifact.id)
    )
    assert release.state == "revoked"  # Neither import nor a new dossier makes a readiness decision.
