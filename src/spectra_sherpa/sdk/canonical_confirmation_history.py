"""Closed, sample-free confirmation history for a canonical project.

This record says whether protected confirmation was requested and, when it
was, binds the frozen governance grant, every authorization/attempt, and the
science-neutral signed receipt chain.  It never contains protected samples,
predictions, filesystem paths, or credentials.  Publisher attestation covers
the record as package content; receipt signatures remain independently
verifiable with recipient-supplied trust anchors.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from .receipt_verification import (
    ReceiptVerificationError,
    receipt_key_fingerprint,
    verify_evaluation_receipt_chain,
)

CANONICAL_CONFIRMATION_HISTORY_VERSION = "spectra-canonical-confirmation-history/1"

_DIGEST = re.compile(r"^[0-9a-f]{64}$")
_TOP_FIELDS = frozenset(
    {
        "schema_version",
        "campaign_id",
        "campaign_record_id",
        "disposition",
        "grant",
        "attempts",
        "receipts",
        "signing_keys",
        "content_digest",
    }
)
_GRANT_FIELDS = frozenset(
    {
        "grant_id",
        "benchmark_id",
        "benchmark_status",
        "development_dataset_ref_digest",
        "development_content_digest",
        "development_split_digest",
        "confirmation_dataset_ref_digest",
        "confirmation_content_digest",
        "confirmation_split_digest",
        "preregistration_digest",
        "protocol_digest",
        "decision_plan_digest",
        "capsule_digest",
        "requested_metrics_digest",
        "confirmation_metric_plan",
        "frozen_request_digest",
        "max_replacements",
        "replacements_issued",
        "valid_result_released",
        "claim_eligible",
        "created_at",
    }
)
_ATTEMPT_FIELDS = frozenset(
    {
        "authorization_id",
        "attempt_id",
        "attempt_sequence",
        "authorization_kind",
        "authorization_status",
        "attempt_status",
        "claim_eligibility_effect",
        "authorization_receipt_digest",
        "governance_request_digest",
        "request_digest",
        "result_digest",
        "evidence_digest",
        "failure_code",
        "issued_at",
        "consumed_at",
        "created_at",
        "updated_at",
    }
)
_DISPOSITIONS = frozenset({"not_requested", "authorized", "in_progress", "succeeded", "failed"})
_ATTEMPT_STATUSES = frozenset({"issued", "consumed", "prepared", "running", "succeeded", "failed"})


class CanonicalConfirmationHistoryError(ValueError):
    """Current confirmation history is malformed or internally inconsistent."""


@dataclass(frozen=True)
class CanonicalConfirmationHistory:
    """One closed current confirmation projection."""

    payload: dict[str, Any]

    @classmethod
    def not_requested(cls, *, campaign_id: str, campaign_record_id: int) -> "CanonicalConfirmationHistory":
        return cls.build(
            campaign_id=campaign_id,
            campaign_record_id=campaign_record_id,
            disposition="not_requested",
            grant=None,
            attempts=(),
            receipts=(),
            signing_keys={},
        )

    @classmethod
    def build(
        cls,
        *,
        campaign_id: str,
        campaign_record_id: int,
        disposition: str,
        grant: Mapping[str, Any] | None,
        attempts: Sequence[Mapping[str, Any]],
        receipts: Sequence[Mapping[str, Any]],
        signing_keys: Mapping[str, Mapping[str, Any]],
    ) -> "CanonicalConfirmationHistory":
        unsigned = {
            "schema_version": CANONICAL_CONFIRMATION_HISTORY_VERSION,
            "campaign_id": campaign_id,
            "campaign_record_id": campaign_record_id,
            "disposition": disposition,
            "grant": dict(grant) if grant is not None else None,
            "attempts": [
                dict(_mapping(attempt, f"confirmation attempts[{index}]")) for index, attempt in enumerate(attempts)
            ],
            "receipts": [
                dict(_mapping(receipt, f"confirmation receipts[{index}]")) for index, receipt in enumerate(receipts)
            ],
            "signing_keys": {
                key_id: dict(_mapping(value, f"signing_keys.{key_id}"))
                for key_id, value in sorted(signing_keys.items())
            },
        }
        return cls.from_dict({**unsigned, "content_digest": _digest(unsigned)})

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "CanonicalConfirmationHistory":
        record = _closed(value, _TOP_FIELDS, "canonical confirmation history")
        if record["schema_version"] != CANONICAL_CONFIRMATION_HISTORY_VERSION:
            raise CanonicalConfirmationHistoryError("canonical confirmation history schema is unsupported")
        _text(record["campaign_id"], "campaign id", 64)
        campaign_record_id = record["campaign_record_id"]
        if isinstance(campaign_record_id, bool) or not isinstance(campaign_record_id, int) or campaign_record_id <= 0:
            raise CanonicalConfirmationHistoryError("canonical confirmation campaign record id is invalid")
        disposition = record["disposition"]
        if disposition not in _DISPOSITIONS:
            raise CanonicalConfirmationHistoryError("canonical confirmation disposition is invalid")
        attempts_value = record["attempts"]
        receipts_value = record["receipts"]
        signing_keys_value = record["signing_keys"]
        if not isinstance(attempts_value, list) or not isinstance(receipts_value, list):
            raise CanonicalConfirmationHistoryError("canonical confirmation histories must be arrays")
        if not isinstance(signing_keys_value, Mapping):
            raise CanonicalConfirmationHistoryError("canonical confirmation signing keys must be an object")

        grant_value = record["grant"]
        if disposition == "not_requested":
            if grant_value is not None or attempts_value or receipts_value or signing_keys_value:
                raise CanonicalConfirmationHistoryError("not-requested confirmation must carry no governance history")
        else:
            grant = _closed(_mapping(grant_value, "confirmation grant"), _GRANT_FIELDS, "confirmation grant")
            _validate_grant(grant)
            attempts = [
                _closed(_mapping(item, f"confirmation attempts[{index}]"), _ATTEMPT_FIELDS, "confirmation attempt")
                for index, item in enumerate(attempts_value)
            ]
            _validate_attempts(attempts)
            if disposition == "authorized" and (
                not attempts
                or attempts[-1]["attempt_status"] != "issued"
                or any(item["attempt_status"] not in {"issued", "failed"} for item in attempts)
            ):
                raise CanonicalConfirmationHistoryError("authorized confirmation has no current issued authorization")
            if disposition == "in_progress" and not any(
                item["attempt_status"] in {"consumed", "prepared", "running"} for item in attempts
            ):
                raise CanonicalConfirmationHistoryError("in-progress confirmation has no active attempt")
            if disposition == "succeeded" and not any(item["attempt_status"] == "succeeded" for item in attempts):
                raise CanonicalConfirmationHistoryError("successful confirmation has no successful attempt")
            if disposition == "failed" and (not attempts or attempts[-1]["attempt_status"] != "failed"):
                raise CanonicalConfirmationHistoryError("failed confirmation has no terminal failed attempt")
            receipts = [_mapping(item, f"confirmation receipts[{index}]") for index, item in enumerate(receipts_value)]
            receipt_digests = [item.get("receipt_digest") for item in receipts]
            if len(receipt_digests) != len(set(receipt_digests)):
                raise CanonicalConfirmationHistoryError("canonical confirmation repeats a receipt")
            used_keys = {item.get("signing_key_id") for item in receipts}
            if used_keys != set(signing_keys_value):
                raise CanonicalConfirmationHistoryError("canonical confirmation signing-key inventory is incomplete")
            if receipts:
                try:
                    # Embedded keys establish internal signature consistency only.
                    # Independent publisher trust is supplied later to
                    # ``verify_receipts`` and is intentionally not inferred here.
                    embedded_fingerprints = {
                        key_id: receipt_key_fingerprint(_mapping(key, f"signing_keys.{key_id}")["public_key"])
                        for key_id, key in signing_keys_value.items()
                    }
                    verify_evaluation_receipt_chain(
                        receipts,
                        signing_keys=signing_keys_value,
                        trusted_receipt_keys=embedded_fingerprints,
                        campaign_record_id=campaign_record_id,
                        expected_digests=receipt_digests,
                    )
                except (KeyError, ReceiptVerificationError) as exc:
                    raise CanonicalConfirmationHistoryError(
                        "canonical confirmation receipt chain is malformed"
                    ) from exc
            _validate_receipt_bindings(
                campaign_record_id=campaign_record_id,
                grant=grant,
                attempts=attempts,
                receipts=receipts,
            )

        _require_digest(record["content_digest"], "canonical confirmation content digest")
        unsigned = {key: record[key] for key in record if key != "content_digest"}
        if _digest(unsigned) != record["content_digest"]:
            raise CanonicalConfirmationHistoryError("canonical confirmation content digest changed")
        return cls(dict(record))

    @property
    def content_digest(self) -> str:
        return str(self.payload["content_digest"])

    @property
    def disposition(self) -> str:
        return str(self.payload["disposition"])

    def as_dict(self) -> dict[str, Any]:
        return json.loads(self.canonical_bytes())

    def canonical_bytes(self) -> bytes:
        return _canonical_json(self.payload)

    def require_matches_campaign(self, *, campaign_id: str, capsule_digest: str | None = None) -> None:
        if self.payload["campaign_id"] != campaign_id:
            raise CanonicalConfirmationHistoryError("canonical confirmation belongs to another campaign")
        grant = self.payload["grant"]
        if capsule_digest is not None and grant is not None and grant["capsule_digest"] != capsule_digest:
            raise CanonicalConfirmationHistoryError("canonical confirmation belongs to another capsule")

    def verify_receipts(self, *, trusted_receipt_keys: Mapping[str, str]) -> dict[str, str]:
        if self.disposition == "not_requested":
            if trusted_receipt_keys:
                raise CanonicalConfirmationHistoryError("not-requested confirmation has no receipt keys")
            return {}
        try:
            return verify_evaluation_receipt_chain(
                self.payload["receipts"],
                signing_keys=self.payload["signing_keys"],
                trusted_receipt_keys=trusted_receipt_keys,
                campaign_record_id=self.payload["campaign_record_id"],
                expected_digests=[receipt["receipt_digest"] for receipt in self.payload["receipts"]],
            )
        except ReceiptVerificationError as exc:
            raise CanonicalConfirmationHistoryError("canonical confirmation receipt verification failed") from exc


def _validate_grant(grant: Mapping[str, Any]) -> None:
    for field in (
        "development_dataset_ref_digest",
        "development_content_digest",
        "development_split_digest",
        "confirmation_dataset_ref_digest",
        "confirmation_content_digest",
        "confirmation_split_digest",
        "preregistration_digest",
        "protocol_digest",
        "decision_plan_digest",
        "capsule_digest",
        "requested_metrics_digest",
        "frozen_request_digest",
    ):
        _require_digest(grant[field], f"confirmation grant {field}")
    _text(grant["grant_id"], "confirmation grant id", 64)
    _text(grant["benchmark_id"], "confirmation benchmark id", 64)
    if grant["benchmark_status"] not in {
        "public_reproducibility_only",
        "provisional_internal",
        "claim_eligible",
        "retired",
    }:
        raise CanonicalConfirmationHistoryError("confirmation benchmark status is invalid")
    if not isinstance(grant["confirmation_metric_plan"], Mapping):
        raise CanonicalConfirmationHistoryError("confirmation metric plan is invalid")
    for field in ("max_replacements", "replacements_issued"):
        value = grant[field]
        if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 2:
            raise CanonicalConfirmationHistoryError(f"confirmation grant {field} is invalid")
    if grant["replacements_issued"] > grant["max_replacements"]:
        raise CanonicalConfirmationHistoryError("confirmation replacement count exceeds its grant")
    if not isinstance(grant["valid_result_released"], bool) or not isinstance(grant["claim_eligible"], bool):
        raise CanonicalConfirmationHistoryError("confirmation grant eligibility fields are invalid")
    _text(grant["created_at"], "confirmation grant creation time", 64)


def _validate_attempts(attempts: Sequence[Mapping[str, Any]]) -> None:
    sequences = [item["attempt_sequence"] for item in attempts]
    if sequences != list(range(1, len(attempts) + 1)) or len(attempts) > 3:
        raise CanonicalConfirmationHistoryError("confirmation attempt sequence is not append-only")
    for item in attempts:
        _text(item["authorization_id"], "confirmation authorization id", 64)
        if item["attempt_id"] is not None:
            _text(item["attempt_id"], "confirmation attempt id", 64)
        if item["authorization_kind"] not in {"original", "replacement"}:
            raise CanonicalConfirmationHistoryError("confirmation authorization kind is invalid")
        if item["authorization_status"] not in {"issued", "consumed"}:
            raise CanonicalConfirmationHistoryError("confirmation authorization status is invalid")
        if item["attempt_status"] not in _ATTEMPT_STATUSES:
            raise CanonicalConfirmationHistoryError("confirmation attempt status is invalid")
        if item["claim_eligibility_effect"] not in {"unchanged", "preserved", "forfeited"}:
            raise CanonicalConfirmationHistoryError("confirmation eligibility effect is invalid")
        for field in (
            "authorization_receipt_digest",
            "governance_request_digest",
            "request_digest",
            "result_digest",
            "evidence_digest",
        ):
            if item[field] is not None:
                _require_digest(item[field], f"confirmation attempt {field}")
        if item["attempt_status"] == "issued":
            if item["attempt_id"] is not None or item["authorization_receipt_digest"] is not None:
                raise CanonicalConfirmationHistoryError("issued confirmation already carries consumed attempt state")
        elif item["attempt_id"] is None or item["authorization_receipt_digest"] is None:
            raise CanonicalConfirmationHistoryError("consumed confirmation lacks its durable attempt identity")
        for field in ("issued_at", "consumed_at", "created_at", "updated_at"):
            if item[field] is not None:
                _text(item[field], f"confirmation attempt {field}", 64)
        if item["failure_code"] is not None:
            _text(item["failure_code"], "confirmation failure code", 64)


def _validate_receipt_bindings(
    *,
    campaign_record_id: int,
    grant: Mapping[str, Any],
    attempts: Sequence[Mapping[str, Any]],
    receipts: Sequence[Mapping[str, Any]],
) -> None:
    """Bind every projected attempt to the signed governance facts.

    Signature verification proves receipt bytes were signed. This projection
    additionally proves those bytes describe this grant and every durable
    attempt, so a self-consistent but fabricated summary cannot be publisher
    attested beside an unrelated receipt chain.
    """

    for index, receipt in enumerate(receipts):
        payload = _mapping(receipt["payload"], f"confirmation receipts[{index}].payload")
        campaign = _mapping(payload.get("campaign"), f"confirmation receipts[{index}].payload.campaign")
        benchmark = _mapping(payload.get("benchmark"), f"confirmation receipts[{index}].payload.benchmark")
        protocol = _mapping(payload.get("protocol"), f"confirmation receipts[{index}].payload.protocol")
        request = _mapping(payload.get("request"), f"confirmation receipts[{index}].payload.request")
        candidate = _mapping(payload.get("candidate"), f"confirmation receipts[{index}].payload.candidate")
        expected = {
            "campaign_id": campaign_record_id,
            "grant_id": grant["grant_id"],
            "benchmark_id": grant["benchmark_id"],
            "benchmark_status": grant["benchmark_status"],
            "confirmation_split_digest": grant["confirmation_split_digest"],
            "preregistration_digest": grant["preregistration_digest"],
            "protocol_digest": grant["protocol_digest"],
            "capsule_digest": grant["capsule_digest"],
            "requested_metrics_digest": grant["requested_metrics_digest"],
            "frozen_request_digest": grant["frozen_request_digest"],
        }
        actual = {
            "campaign_id": campaign.get("campaign_id"),
            "grant_id": campaign.get("grant_id"),
            "benchmark_id": benchmark.get("benchmark_id"),
            "benchmark_status": benchmark.get("status"),
            "confirmation_split_digest": benchmark.get("confirmation_split_digest"),
            "preregistration_digest": protocol.get("preregistration_digest"),
            "protocol_digest": protocol.get("protocol_digest"),
            "capsule_digest": request.get("capsule_digest"),
            "requested_metrics_digest": request.get("requested_metrics_digest"),
            "frozen_request_digest": candidate.get("frozen_request_digest"),
        }
        if actual != expected or benchmark.get("dataset_role") != "confirmation":
            raise CanonicalConfirmationHistoryError("confirmation receipt differs from its grant")

    for attempt in attempts:
        authorization_id = attempt["authorization_id"]
        sequence = attempt["attempt_sequence"]
        matching = [
            receipt
            for receipt in receipts
            if receipt["evaluation_sequence"] == sequence and _receipt_authorization_id(receipt) == authorization_id
        ]
        consumed = [receipt for receipt in matching if receipt["event_kind"] == "authorization_consumed"]
        terminal = [receipt for receipt in matching if receipt["event_kind"] == "attempt_terminal"]
        status = attempt["attempt_status"]
        if status == "issued":
            if consumed or terminal:
                raise CanonicalConfirmationHistoryError("issued confirmation has signed execution receipts")
            continue
        if len(consumed) != 1 or consumed[0]["receipt_digest"] != attempt["authorization_receipt_digest"]:
            raise CanonicalConfirmationHistoryError("confirmation attempt lacks its signed authorization receipt")
        authorization = _mapping(consumed[0]["payload"]["authorization"], "confirmation authorization payload")
        if (
            authorization.get("kind") != attempt["authorization_kind"]
            or consumed[0]["payload"].get("claim_eligibility_effect") != attempt["claim_eligibility_effect"]
        ):
            raise CanonicalConfirmationHistoryError("confirmation attempt differs from its authorization receipt")
        if status in {"consumed", "prepared", "running"}:
            if terminal:
                raise CanonicalConfirmationHistoryError("active confirmation already has a terminal receipt")
            continue
        if len(terminal) != 1:
            raise CanonicalConfirmationHistoryError("terminal confirmation lacks one signed terminal receipt")
        terminal_payload = _mapping(terminal[0]["payload"], "confirmation terminal receipt payload")
        if (
            terminal_payload.get("result_digest") != attempt["result_digest"]
            or terminal_payload.get("evidence_digest") != attempt["evidence_digest"]
            or terminal_payload.get("failure_code") != attempt["failure_code"]
            or terminal_payload.get("claim_eligibility_effect") != attempt["claim_eligibility_effect"]
            or (status == "succeeded") != (terminal[0]["disposition"] == "succeeded")
        ):
            raise CanonicalConfirmationHistoryError("confirmation attempt differs from its signed terminal receipt")

    if grant["valid_result_released"] != any(item["attempt_status"] == "succeeded" for item in attempts):
        raise CanonicalConfirmationHistoryError("confirmation grant result-release state contradicts its attempts")


def _receipt_authorization_id(receipt: Mapping[str, Any]) -> Any:
    payload = _mapping(receipt["payload"], "confirmation receipt payload")
    authorization = _mapping(payload.get("authorization"), "confirmation receipt authorization")
    return authorization.get("authorization_id")


def _closed(value: Mapping[str, Any], fields: frozenset[str], label: str) -> dict[str, Any]:
    if not isinstance(value, Mapping) or set(value) != fields:
        raise CanonicalConfirmationHistoryError(f"{label} fields are closed")
    return dict(value)


def _mapping(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise CanonicalConfirmationHistoryError(f"{label} must be an object")
    return value


def _text(value: Any, label: str, maximum: int) -> str:
    if not isinstance(value, str) or not value or len(value) > maximum:
        raise CanonicalConfirmationHistoryError(f"{label} is invalid")
    return value


def _require_digest(value: Any, label: str) -> None:
    if not isinstance(value, str) or not _DIGEST.fullmatch(value):
        raise CanonicalConfirmationHistoryError(f"{label} is invalid")


def _digest(value: Mapping[str, Any]) -> str:
    return hashlib.sha256(_canonical_json(value)).hexdigest()


def _canonical_json(value: Any) -> bytes:
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()
    except (TypeError, ValueError) as exc:
        raise CanonicalConfirmationHistoryError("canonical confirmation is not JSON-safe") from exc


__all__ = [
    "CANONICAL_CONFIRMATION_HISTORY_VERSION",
    "CanonicalConfirmationHistory",
    "CanonicalConfirmationHistoryError",
]
