"""Current, science-neutral verification of governed evaluation receipts.

Receipt chains govern who used a protected evaluation capability, in what
order, and under which Runner signing identity.  They do not interpret a
workflow or establish scientific correctness.  Keeping that authority in
this module lets current canonical confirmation retain its access-governance
proofs without depending on the historical M3 archive or PLS materializer.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import re
from typing import Any, Mapping, Sequence

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

RECEIPT_SCHEMA_VERSION = "spectra-harness-evaluation-receipt/1"

_DIGEST = re.compile(r"^[0-9a-f]{64}$")
_ZERO_DIGEST = "0" * 64
_RECEIPT_FIELDS = frozenset(
    {
        "public_id",
        "ledger_sequence",
        "evaluation_sequence",
        "event_kind",
        "disposition",
        "actor_ref",
        "actor_role",
        "runner_id",
        "signing_key_id",
        "payload",
        "payload_digest",
        "prior_receipt_digest",
        "receipt_digest",
        "signature",
        "created_at",
    }
)
_RECEIPT_PAYLOAD_FIELDS = frozenset(
    {
        "schema_version",
        "event_kind",
        "ledger_sequence",
        "evaluation_sequence",
        "campaign",
        "candidate",
        "profile",
        "authorization",
        "actor",
        "runner",
        "benchmark",
        "protocol",
        "request",
        "result_digest",
        "failure_code",
        "evidence_digest",
        "prior_receipt_digest",
        "timestamp",
        "disposition",
        "claim_eligibility_effect",
    }
)
_SIGNING_KEY_FIELDS = frozenset(
    {
        "runner_id",
        "algorithm",
        "public_key",
        "custody_ref",
        "status",
        "created_at",
    }
)


class ReceiptVerificationError(ValueError):
    """A receipt chain or its independent trust anchors are invalid."""


def receipt_key_fingerprint(public_key: str) -> str:
    """Return the lowercase SHA-256 fingerprint of one raw Ed25519 key."""
    raw = _b64decode(public_key, "receipt public key")
    if len(raw) != 32:
        raise ReceiptVerificationError("receipt public key is not a raw Ed25519 key")
    return hashlib.sha256(raw).hexdigest()


def validated_receipt_trust_anchors(value: Mapping[str, str]) -> dict[str, str]:
    """Copy and validate independently obtained key-id/fingerprint anchors."""
    if not isinstance(value, Mapping) or not value:
        raise ReceiptVerificationError("at least one independent receipt-key trust anchor is required")
    result: dict[str, str] = {}
    for key_id, fingerprint in value.items():
        if not isinstance(key_id, str) or not 1 <= len(key_id) <= 96:
            raise ReceiptVerificationError("receipt trust-anchor key id is invalid")
        _require_digest(fingerprint, f"receipt trust anchor {key_id}")
        result[key_id] = fingerprint
    return result


def verify_evaluation_receipt_chain(
    receipts: Sequence[Mapping[str, Any]],
    *,
    signing_keys: Mapping[str, Mapping[str, Any]],
    trusted_receipt_keys: Mapping[str, str],
    campaign_record_id: int,
    expected_digests: Sequence[str],
) -> dict[str, str]:
    """Verify exact receipt order, durable bindings, chain, keys, and signatures.

    The returned mapping contains only the independently matched key
    fingerprints.  This function deliberately makes no statement about the
    scientific correctness of a result named by a receipt.
    """
    anchors = validated_receipt_trust_anchors(trusted_receipt_keys)
    if isinstance(campaign_record_id, bool) or not isinstance(campaign_record_id, int) or campaign_record_id <= 0:
        raise ReceiptVerificationError("receipt campaign record id is invalid")
    if not receipts:
        raise ReceiptVerificationError("receipt chain must not be empty")
    if any(not isinstance(record, Mapping) for record in receipts):
        raise ReceiptVerificationError("receipt chain records must be objects")
    if not isinstance(signing_keys, Mapping) or not signing_keys:
        raise ReceiptVerificationError("receipt signing keys must be a non-empty object")
    if [record.get("receipt_digest") for record in receipts] != list(expected_digests):
        raise ReceiptVerificationError("exported receipts do not match the campaign evidence chain")
    raw_key_ids = [record.get("signing_key_id") for record in receipts]
    if any(not isinstance(key_id, str) or not 1 <= len(key_id) <= 96 for key_id in raw_key_ids):
        raise ReceiptVerificationError("exported receipt signing key id is invalid")
    used_key_ids = set(raw_key_ids)
    if set(signing_keys) != used_key_ids:
        raise ReceiptVerificationError("exported signing keys do not exactly match the receipt chain")
    if not set(signing_keys).issubset(anchors):
        raise ReceiptVerificationError("receipt chain uses a key without an independent trust anchor")

    fingerprints: dict[str, str] = {}
    prior: str | None = None
    for sequence, record in enumerate(receipts, start=1):
        name = f"receipt_chain[{sequence - 1}]"
        _closed(record, _RECEIPT_FIELDS, name)
        payload = _mapping(record["payload"], f"{name}.payload")
        _closed(payload, _RECEIPT_PAYLOAD_FIELDS, f"{name}.payload")
        if (
            payload["schema_version"] != RECEIPT_SCHEMA_VERSION
            or record["ledger_sequence"] != sequence
            or payload["ledger_sequence"] != sequence
            or record["prior_receipt_digest"] != prior
            or payload["prior_receipt_digest"] != prior
            or payload["event_kind"] != record["event_kind"]
            or payload["evaluation_sequence"] != record["evaluation_sequence"]
            or payload["disposition"] != record["disposition"]
            or payload["timestamp"] != record["created_at"]
        ):
            raise ReceiptVerificationError("exported receipt durable identity changed")
        campaign = _mapping(payload["campaign"], f"{name}.payload.campaign")
        if campaign.get("campaign_id") != campaign_record_id:
            raise ReceiptVerificationError("exported receipt belongs to another campaign")
        actor = _mapping(payload["actor"], f"{name}.payload.actor")
        runner = _mapping(payload["runner"], f"{name}.payload.runner")
        if actor.get("actor_ref") != record["actor_ref"] or actor.get("role") != record["actor_role"]:
            raise ReceiptVerificationError("exported receipt actor identity changed")
        if runner.get("runner_id") != record["runner_id"] or runner.get("signing_key_id") != record["signing_key_id"]:
            raise ReceiptVerificationError("exported receipt Runner identity changed")

        payload_bytes = _canonical_json(payload)
        if hashlib.sha256(payload_bytes).hexdigest() != record["payload_digest"]:
            raise ReceiptVerificationError("exported receipt payload digest is invalid")
        receipt_digest = hashlib.sha256(bytes.fromhex(prior or _ZERO_DIGEST) + payload_bytes).hexdigest()
        if receipt_digest != record["receipt_digest"]:
            raise ReceiptVerificationError("exported receipt chain digest is invalid")

        key_id = record["signing_key_id"]
        key = signing_keys[key_id]
        if not isinstance(key, Mapping):
            raise ReceiptVerificationError(f"signing_keys.{key_id} must be an object")
        _closed(key, _SIGNING_KEY_FIELDS, f"signing_keys.{key_id}")
        if (
            key["runner_id"] != record["runner_id"]
            or key["algorithm"] != "ed25519"
            or key["status"] not in {"active", "retired"}
        ):
            raise ReceiptVerificationError("exported receipt signing identity is invalid")
        fingerprint = receipt_key_fingerprint(key["public_key"])
        if fingerprint != anchors[key_id]:
            raise ReceiptVerificationError("archive receipt key does not match its independent trust anchor")
        fingerprints[key_id] = fingerprint
        try:
            Ed25519PublicKey.from_public_bytes(_b64decode(key["public_key"], "receipt public key")).verify(
                _b64decode(record["signature"], "receipt signature"),
                bytes.fromhex(record["receipt_digest"]),
            )
        except (ValueError, InvalidSignature) as exc:
            raise ReceiptVerificationError("exported receipt signature is invalid") from exc
        prior = record["receipt_digest"]
    return fingerprints


def _mapping(value: Any, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ReceiptVerificationError(f"{name} must be an object")
    return value


def _closed(value: Mapping[str, Any], required: frozenset[str], name: str) -> None:
    missing = sorted(required - set(value))
    extra = sorted(set(value) - required)
    if missing or extra:
        raise ReceiptVerificationError(f"{name} fields are closed: missing={missing}, extra={extra}")


def _require_digest(value: Any, name: str) -> None:
    if not isinstance(value, str) or not _DIGEST.fullmatch(value):
        raise ReceiptVerificationError(f"{name} must be a lowercase SHA-256 digest")


def _b64decode(value: Any, name: str) -> bytes:
    if not isinstance(value, str) or not value:
        raise ReceiptVerificationError(f"{name} is invalid")
    try:
        return base64.b64decode(value + "=" * (-len(value) % 4), altchars=b"-_", validate=True)
    except (UnicodeEncodeError, binascii.Error, ValueError) as exc:
        raise ReceiptVerificationError(f"{name} is invalid") from exc


def _canonical_json(value: Mapping[str, Any]) -> bytes:
    try:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ReceiptVerificationError("receipt contains non-canonical JSON values") from exc


__all__ = [
    "RECEIPT_SCHEMA_VERSION",
    "ReceiptVerificationError",
    "receipt_key_fingerprint",
    "validated_receipt_trust_anchors",
    "verify_evaluation_receipt_chain",
]
