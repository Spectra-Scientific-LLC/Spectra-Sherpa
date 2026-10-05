from __future__ import annotations

import base64
import hashlib
import json
from copy import deepcopy

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from spectra_sherpa.sdk.receipt_verification import (
    ReceiptVerificationError,
    receipt_key_fingerprint,
    validated_receipt_trust_anchors,
    verify_evaluation_receipt_chain,
)


def _b64(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _canonical(value) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def _receipt_fixture():
    private_key = Ed25519PrivateKey.from_private_bytes(bytes(range(32)))
    public_key = _b64(
        private_key.public_key().public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )
    )
    payload = {
        "schema_version": "spectra-harness-evaluation-receipt/1",
        "event_kind": "evaluation_consumed",
        "ledger_sequence": 1,
        "evaluation_sequence": 1,
        "campaign": {"campaign_id": 17},
        "candidate": {"candidate_id": "candidate-001"},
        "profile": {"version": "profile/1"},
        "authorization": {"authorization_id": "authorization-001"},
        "actor": {"actor_ref": "user:7", "role": "owner"},
        "runner": {"runner_id": "runner-001", "signing_key_id": "key-001"},
        "benchmark": {"benchmark_id": "benchmark-001"},
        "protocol": {"protocol_id": "protocol-001"},
        "request": {"request_digest": "a" * 64},
        "result_digest": "b" * 64,
        "failure_code": None,
        "evidence_digest": "c" * 64,
        "prior_receipt_digest": None,
        "timestamp": "2026-08-13T12:00:00+00:00",
        "disposition": "consumed",
        "claim_eligibility_effect": "unchanged",
    }
    payload_bytes = _canonical(payload)
    receipt_digest = hashlib.sha256(bytes(32) + payload_bytes).hexdigest()
    receipt = {
        "public_id": "receipt-001",
        "ledger_sequence": 1,
        "evaluation_sequence": 1,
        "event_kind": "evaluation_consumed",
        "disposition": "consumed",
        "actor_ref": "user:7",
        "actor_role": "owner",
        "runner_id": "runner-001",
        "signing_key_id": "key-001",
        "payload": payload,
        "payload_digest": hashlib.sha256(payload_bytes).hexdigest(),
        "prior_receipt_digest": None,
        "receipt_digest": receipt_digest,
        "signature": _b64(private_key.sign(bytes.fromhex(receipt_digest))),
        "created_at": "2026-08-13T12:00:00+00:00",
    }
    signing_keys = {
        "key-001": {
            "runner_id": "runner-001",
            "algorithm": "ed25519",
            "public_key": public_key,
            "custody_ref": "urn:spectra:key:key-001",
            "status": "active",
            "created_at": "2026-08-13T11:00:00+00:00",
        }
    }
    anchors = {"key-001": receipt_key_fingerprint(public_key)}
    return receipt, signing_keys, anchors


def test_current_receipt_verifier_authenticates_exact_chain_without_science() -> None:
    receipt, signing_keys, anchors = _receipt_fixture()

    assert (
        verify_evaluation_receipt_chain(
            [receipt],
            signing_keys=signing_keys,
            trusted_receipt_keys=anchors,
            campaign_record_id=17,
            expected_digests=[receipt["receipt_digest"]],
        )
        == anchors
    )


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (lambda record: record.update(disposition="released"), "durable identity"),
        (lambda record: record["payload"].update(campaign={"campaign_id": 18}), "another campaign"),
        (lambda record: record.update(signature=_b64(bytes(64))), "signature is invalid"),
    ],
)
def test_current_receipt_verifier_fails_closed_on_tampering(mutation, message: str) -> None:
    receipt, signing_keys, anchors = _receipt_fixture()
    changed = deepcopy(receipt)
    mutation(changed)

    with pytest.raises(ReceiptVerificationError, match=message):
        verify_evaluation_receipt_chain(
            [changed],
            signing_keys=signing_keys,
            trusted_receipt_keys=anchors,
            campaign_record_id=17,
            expected_digests=[receipt["receipt_digest"]],
        )


def test_current_receipt_verifier_requires_independent_exact_anchors() -> None:
    receipt, signing_keys, anchors = _receipt_fixture()

    with pytest.raises(ReceiptVerificationError, match="independent receipt-key trust anchor"):
        validated_receipt_trust_anchors({})
    with pytest.raises(ReceiptVerificationError, match="does not match its independent trust anchor"):
        verify_evaluation_receipt_chain(
            [receipt],
            signing_keys=signing_keys,
            trusted_receipt_keys={"key-001": "0" * 64},
            campaign_record_id=17,
            expected_digests=[receipt["receipt_digest"]],
        )
    assert validated_receipt_trust_anchors(anchors) == anchors


def test_current_receipt_verifier_rejects_an_empty_chain() -> None:
    _, _, anchors = _receipt_fixture()

    with pytest.raises(ReceiptVerificationError, match="must not be empty"):
        verify_evaluation_receipt_chain(
            [],
            signing_keys={},
            trusted_receipt_keys=anchors,
            campaign_record_id=17,
            expected_digests=[],
        )


@pytest.mark.parametrize(
    ("receipts", "signing_keys", "message"),
    [
        (["not-an-object"], {}, "records must be objects"),
        (
            [{"receipt_digest": "a" * 64, "signing_key_id": []}],
            {"key-001": {}},
            "signing key id is invalid",
        ),
    ],
)
def test_current_receipt_verifier_closes_malformed_structure(receipts, signing_keys, message: str) -> None:
    _, _, anchors = _receipt_fixture()

    with pytest.raises(ReceiptVerificationError, match=message):
        verify_evaluation_receipt_chain(
            receipts,
            signing_keys=signing_keys,
            trusted_receipt_keys=anchors,
            campaign_record_id=17,
            expected_digests=["a" * 64],
        )
