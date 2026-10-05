from __future__ import annotations

from copy import deepcopy

import pytest

from spectra_sherpa.sdk.canonical_confirmation_history import (
    CanonicalConfirmationHistory,
    CanonicalConfirmationHistoryError,
)


def _grant() -> dict:
    return {
        "grant_id": "grant-001",
        "benchmark_id": "benchmark-001",
        "benchmark_status": "provisional_internal",
        "development_dataset_ref_digest": "1" * 64,
        "development_content_digest": "2" * 64,
        "development_split_digest": "3" * 64,
        "confirmation_dataset_ref_digest": "4" * 64,
        "confirmation_content_digest": "5" * 64,
        "confirmation_split_digest": "6" * 64,
        "preregistration_digest": "7" * 64,
        "protocol_digest": "8" * 64,
        "decision_plan_digest": "9" * 64,
        "capsule_digest": "a" * 64,
        "requested_metrics_digest": "b" * 64,
        "confirmation_metric_plan": {"schema_version": "metric-plan/1"},
        "frozen_request_digest": "c" * 64,
        "max_replacements": 2,
        "replacements_issued": 0,
        "valid_result_released": False,
        "claim_eligible": True,
        "created_at": "2026-08-13T12:00:00+00:00",
    }


def _issued_attempt() -> dict:
    return {
        "authorization_id": "authorization-001",
        "attempt_id": None,
        "attempt_sequence": 1,
        "authorization_kind": "original",
        "authorization_status": "issued",
        "attempt_status": "issued",
        "claim_eligibility_effect": "unchanged",
        "authorization_receipt_digest": None,
        "governance_request_digest": None,
        "request_digest": None,
        "result_digest": None,
        "evidence_digest": None,
        "failure_code": None,
        "issued_at": "2026-08-13T12:00:00+00:00",
        "consumed_at": None,
        "created_at": None,
        "updated_at": None,
    }


def test_not_requested_history_is_explicit_closed_and_campaign_bound() -> None:
    history = CanonicalConfirmationHistory.not_requested(campaign_id="campaign-001", campaign_record_id=17)

    assert history.disposition == "not_requested"
    history.require_matches_campaign(campaign_id="campaign-001")
    with pytest.raises(CanonicalConfirmationHistoryError, match="another campaign"):
        history.require_matches_campaign(campaign_id="campaign-002")
    with pytest.raises(CanonicalConfirmationHistoryError, match="no receipt keys"):
        history.verify_receipts(trusted_receipt_keys={"unexpected": "0" * 64})


def test_authorized_history_round_trips_and_binds_capsule() -> None:
    history = CanonicalConfirmationHistory.build(
        campaign_id="campaign-001",
        campaign_record_id=17,
        disposition="authorized",
        grant=_grant(),
        attempts=[_issued_attempt()],
        receipts=[],
        signing_keys={},
    )

    assert CanonicalConfirmationHistory.from_dict(history.as_dict()) == history
    history.require_matches_campaign(campaign_id="campaign-001", capsule_digest="a" * 64)
    with pytest.raises(CanonicalConfirmationHistoryError, match="another capsule"):
        history.require_matches_campaign(campaign_id="campaign-001", capsule_digest="d" * 64)


def test_confirmation_history_rejects_reordered_attempts_and_self_consistent_tampering() -> None:
    first = _issued_attempt()
    second = deepcopy(first)
    second.update(
        authorization_id="authorization-002",
        attempt_sequence=3,
        authorization_kind="replacement",
    )
    with pytest.raises(CanonicalConfirmationHistoryError, match="append-only"):
        CanonicalConfirmationHistory.build(
            campaign_id="campaign-001",
            campaign_record_id=17,
            disposition="authorized",
            grant=_grant(),
            attempts=[first, second],
            receipts=[],
            signing_keys={},
        )

    history = CanonicalConfirmationHistory.not_requested(campaign_id="campaign-001", campaign_record_id=17)
    changed = history.as_dict()
    changed["campaign_id"] = "campaign-002"
    with pytest.raises(CanonicalConfirmationHistoryError, match="content digest changed"):
        CanonicalConfirmationHistory.from_dict(changed)


def test_confirmation_history_rejects_non_object_receipts_as_a_closed_domain_error() -> None:
    with pytest.raises(CanonicalConfirmationHistoryError, match=r"receipts\[0\] must be an object"):
        CanonicalConfirmationHistory.build(
            campaign_id="campaign-001",
            campaign_record_id=17,
            disposition="authorized",
            grant=_grant(),
            attempts=[_issued_attempt()],
            receipts=["not-a-receipt"],  # type: ignore[list-item]
            signing_keys={},
        )


@pytest.mark.parametrize("disposition", ["succeeded", "failed"])
def test_terminal_confirmation_requires_its_signed_receipt_chain(disposition: str) -> None:
    attempt = _issued_attempt()
    attempt.update(
        attempt_id="attempt-001",
        authorization_status="consumed",
        attempt_status=disposition,
        authorization_receipt_digest="d" * 64,
        governance_request_digest="e" * 64,
        request_digest="f" * 64,
        result_digest="1" * 64,
        evidence_digest="2" * 64,
        failure_code=None if disposition == "succeeded" else "WorkerFailed",
        consumed_at="2026-08-13T12:01:00+00:00",
        created_at="2026-08-13T12:01:00+00:00",
        updated_at="2026-08-13T12:02:00+00:00",
    )
    grant = _grant()
    grant["valid_result_released"] = disposition == "succeeded"

    with pytest.raises(CanonicalConfirmationHistoryError, match="signed authorization receipt"):
        CanonicalConfirmationHistory.build(
            campaign_id="campaign-001",
            campaign_record_id=17,
            disposition=disposition,
            grant=grant,
            attempts=[attempt],
            receipts=[],
            signing_keys={},
        )
