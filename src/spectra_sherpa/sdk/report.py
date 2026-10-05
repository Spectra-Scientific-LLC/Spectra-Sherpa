"""Portable local evidence manifests for validation and future Harness work.

An evidence manifest is a canonical JSON record whose SHA-256 digest names
its exact content. It is intentionally local and unsigned. Managed receipt
signatures prove the execution ledger and schema 2 can bind their digests,
but they do not turn the bundle itself into a signed artefact. The manifest
still makes omissions and accidental edits detectable and gives an
independent reviewer complete campaign lineage.
"""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

EVIDENCE_BUNDLE_SCHEMA_VERSION = "2"
_CANDIDATE_OUTCOMES = frozenset({"evaluated", "rejected", "failed", "selected"})
_CONCLUSIONS = frozenset({"improved", "not_demonstrated", "no_defensible_improvement"})
_EVIDENCE_SCOPES = frozenset({"validation", "development_campaign", "confirmation_campaign"})
_DEVELOPMENT_CANDIDATE_KINDS = frozenset({"frozen_baseline", "transparent_grid", "managed_proposal"})
_DEVELOPMENT_FAILURE_STATUSES = frozenset({"execution_failure", "timeout", "crash", "cancelled", "malformed_result"})
_DEVELOPMENT_CONCLUSIONS = frozenset(
    {
        "development_improvement",
        "development_no_defensible_improvement",
        "not_demonstrated",
    }
)
_PROPOSER_KINDS = frozenset({"deterministic_policy", "llm", "human"})
_CONFIRMATION_SCHEMA_VERSION = "spectra-harness-confirmation-evidence/1"
_CONFIRMATION_STATUSES = frozenset(
    {
        "succeeded",
        "scientific_failure",
        "execution_failure",
        "timeout",
        "crash",
        "cancelled",
        "malformed_result",
        "communication_loss",
        "post_admission_interruption",
        "replacement_denied",
    }
)


class EvidenceBundleError(ValueError):
    """Raised when an evidence manifest is incomplete or does not verify."""


@dataclass(frozen=True)
class EvidenceBundle:
    """A verified content-addressed local validation evidence manifest."""

    payload: dict[str, Any]
    content_digest: str

    def canonical_bytes(self) -> bytes:
        """Return the exact canonical bytes named by :attr:`content_digest`."""
        return _canonical_json(self.payload)

    def as_dict(self) -> dict[str, Any]:
        """Return a detached serializable manifest with its content digest."""
        return {**deepcopy(self.payload), "content_digest": self.content_digest}

    @classmethod
    def from_dict(cls, manifest: Mapping[str, Any]) -> "EvidenceBundle":
        """Validate a serialized manifest and reject any digest mismatch."""
        if not isinstance(manifest.get("content_digest"), str):
            raise EvidenceBundleError("evidence manifest requires a content_digest")
        payload = {key: deepcopy(value) for key, value in manifest.items() if key != "content_digest"}
        _validate_payload(payload)
        actual = _digest(payload)
        expected = str(manifest["content_digest"])
        if actual != expected:
            raise EvidenceBundleError(f"evidence manifest digest mismatch: expected {expected}, got {actual}")
        return cls(payload=payload, content_digest=actual)


def evidence_bundle(
    *,
    dataset_attestation: Mapping[str, Any],
    split_attestation: Mapping[str, Any],
    baseline: Mapping[str, Any],
    candidates: Sequence[Mapping[str, Any]],
    evaluation_diagnostics: Sequence[Mapping[str, Any]],
    environment: Mapping[str, Any],
    human_decisions: Sequence[Mapping[str, Any]] = (),
    confirmation: Mapping[str, Any] | None = None,
    conclusion: str = "not_demonstrated",
    scope: str = "validation",
    execution_records: Sequence[Mapping[str, Any]] = (),
    campaign_history: Sequence[Mapping[str, Any]] = (),
    receipt_chain: Sequence[str] = (),
) -> EvidenceBundle:
    """Build a strict, content-addressed local evidence manifest.

    This is the sole public evidence producer and writes the sole supported
    schema, version 2. Prototype schema-1 manifests fail closed rather than
    being translated or interpreted as current evidence.

    Dataset and split attestations must name their immutable hashes. Every
    attempted candidate must remain in ``candidates``—including failures and
    rejected proposals—so the bundle cannot present only a winning result.
    Exact local fold diagnostics are required for the baseline and each
    evaluated/selected candidate. They are intentionally local evidence and
    must never be used as a Hybrid uplink payload.
    The optional confirmation record is evidence only; one-time quarantine is
    enforced later by the Runner, not by this portable SDK object.
    """
    payload = {
        "schema_version": EVIDENCE_BUNDLE_SCHEMA_VERSION,
        "dataset_attestation": deepcopy(dict(dataset_attestation)),
        "split_attestation": deepcopy(dict(split_attestation)),
        "baseline": deepcopy(dict(baseline)),
        "candidates": [deepcopy(dict(candidate)) for candidate in candidates],
        "evaluation_diagnostics": [deepcopy(dict(diagnostic)) for diagnostic in evaluation_diagnostics],
        "environment": deepcopy(dict(environment)),
        "human_decisions": [deepcopy(dict(decision)) for decision in human_decisions],
        "confirmation": deepcopy(dict(confirmation)) if confirmation is not None else None,
        "conclusion": conclusion,
        "scope": scope,
        "execution_records": [deepcopy(dict(record)) for record in execution_records],
        "campaign_history": [deepcopy(dict(event)) for event in campaign_history],
        "receipt_chain": list(receipt_chain),
    }
    _validate_payload(payload)
    return EvidenceBundle(payload=payload, content_digest=_digest(payload))


def verify_evidence_bundle(manifest: EvidenceBundle | Mapping[str, Any]) -> bool:
    """Return whether a serialized or in-memory manifest verifies exactly."""
    try:
        if isinstance(manifest, EvidenceBundle):
            _validate_payload(manifest.payload)
            return _digest(manifest.payload) == manifest.content_digest
        EvidenceBundle.from_dict(manifest)
    except (EvidenceBundleError, TypeError, ValueError):
        return False
    return True


def _validate_payload(payload: Mapping[str, Any]) -> None:
    required_keys = {
        "schema_version",
        "dataset_attestation",
        "split_attestation",
        "baseline",
        "candidates",
        "evaluation_diagnostics",
        "environment",
        "human_decisions",
        "confirmation",
        "conclusion",
        "scope",
        "execution_records",
        "campaign_history",
        "receipt_chain",
    }
    version = payload.get("schema_version")
    if version != EVIDENCE_BUNDLE_SCHEMA_VERSION:
        raise EvidenceBundleError(f"unsupported evidence schema version: {version!r}")
    missing = sorted(required_keys - set(payload))
    extra = sorted(set(payload) - required_keys)
    if missing or extra:
        raise EvidenceBundleError(f"invalid evidence fields: missing={missing}, extra={extra}")
    _require_mapping(payload["dataset_attestation"], "dataset_attestation")
    _require_mapping(payload["split_attestation"], "split_attestation")
    _require_mapping(payload["baseline"], "baseline")
    _require_mapping(payload["environment"], "environment")
    _require_digest(payload["dataset_attestation"], "dataset_digest")
    _require_digest(payload["split_attestation"], "split_digest")
    _require_digest(payload["baseline"], "workflow_digest")
    if payload["conclusion"] not in _CONCLUSIONS:
        raise EvidenceBundleError(f"unsupported evidence conclusion: {payload['conclusion']!r}")

    candidates = payload["candidates"]
    if not isinstance(candidates, list) or not candidates:
        raise EvidenceBundleError("evidence candidates must be a non-empty list")
    candidate_ids: set[str] = set()
    for index, candidate in enumerate(candidates):
        _require_mapping(candidate, f"candidates[{index}]")
        candidate_id = candidate.get("candidate_id")
        if not isinstance(candidate_id, str) or not candidate_id:
            raise EvidenceBundleError(f"candidates[{index}] requires a non-empty candidate_id")
        if candidate_id in candidate_ids:
            raise EvidenceBundleError(f"duplicate evidence candidate_id: {candidate_id!r}")
        candidate_ids.add(candidate_id)
        _require_digest(candidate, "workflow_digest", prefix=f"candidates[{index}].")
        outcome = candidate.get("outcome")
        if outcome not in _CANDIDATE_OUTCOMES:
            raise EvidenceBundleError(f"candidates[{index}] has unsupported outcome: {outcome!r}")
        if outcome == "failed" and not isinstance(candidate.get("failure"), Mapping):
            raise EvidenceBundleError(f"failed candidates[{index}] require structured failure evidence")

    _validate_evaluation_diagnostics(payload["evaluation_diagnostics"], candidate_ids, candidates)
    if version == EVIDENCE_BUNDLE_SCHEMA_VERSION:
        _validate_campaign_bindings(payload, candidate_ids, candidates)

    decisions = payload["human_decisions"]
    if not isinstance(decisions, list):
        raise EvidenceBundleError("human_decisions must be a list")
    for index, decision in enumerate(decisions):
        _require_mapping(decision, f"human_decisions[{index}]")
        if not isinstance(decision.get("decision"), str) or not decision["decision"]:
            raise EvidenceBundleError(f"human_decisions[{index}] requires a non-empty decision")

    confirmation = payload["confirmation"]
    if confirmation is not None:
        _require_mapping(confirmation, "confirmation")
        if not isinstance(confirmation.get("candidate_id"), str):
            raise EvidenceBundleError("confirmation requires candidate_id")
        if confirmation["candidate_id"] not in candidate_ids:
            raise EvidenceBundleError("confirmation candidate_id is not present in candidates")

    # Canonical encoding is deliberately the final validation: it rejects NaN,
    # bytes, unsupported custom objects, and non-string object keys.
    try:
        _canonical_json(dict(payload))
    except (TypeError, ValueError) as exc:
        raise EvidenceBundleError(f"evidence manifest is not canonical-JSON serializable: {exc}") from exc


def _validate_campaign_bindings(
    payload: Mapping[str, Any],
    candidate_ids: set[str],
    candidates: Sequence[Mapping[str, Any]],
) -> None:
    scope = payload["scope"]
    if scope not in _EVIDENCE_SCOPES:
        raise EvidenceBundleError(f"unsupported evidence scope: {scope!r}")
    executions = payload["execution_records"]
    if not isinstance(executions, list):
        raise EvidenceBundleError("execution_records must be a list")
    allowed_subjects = {"baseline", *candidate_ids}
    outcome_by_subject = {candidate["candidate_id"]: candidate.get("outcome") for candidate in candidates}
    outcome_by_subject["baseline"] = payload["baseline"].get("outcome", "evaluated")
    observed_subjects: set[str] = set()
    for index, execution in enumerate(executions):
        _require_mapping(execution, f"execution_records[{index}]")
        required = {
            "subject_id",
            "request_digest",
            "result_digest",
            "local_evidence_digest",
            "workflow_capsule_digest",
            "receipt_digest",
        }
        missing, extra = sorted(required - set(execution)), sorted(set(execution) - required)
        if missing or extra:
            raise EvidenceBundleError(f"execution_records[{index}] fields are closed: missing={missing}, extra={extra}")
        subject_id = execution["subject_id"]
        if subject_id not in allowed_subjects or subject_id in observed_subjects:
            raise EvidenceBundleError(f"execution_records[{index}] subject is unknown or duplicated")
        observed_subjects.add(subject_id)
        for key in ("request_digest", "result_digest", "workflow_capsule_digest"):
            _require_digest(execution, key, prefix=f"execution_records[{index}].")
        local_evidence = execution["local_evidence_digest"]
        if outcome_by_subject[subject_id] == "failed":
            if local_evidence is not None:
                raise EvidenceBundleError(
                    f"execution_records[{index}] failed subject cannot carry exact-success evidence"
                )
        else:
            _require_digest(
                execution,
                "local_evidence_digest",
                prefix=f"execution_records[{index}].",
            )
        receipt = execution["receipt_digest"]
        if receipt is not None:
            _require_digest(execution, "receipt_digest", prefix=f"execution_records[{index}].")

    history = payload["campaign_history"]
    if not isinstance(history, list):
        raise EvidenceBundleError("campaign_history must be a list")
    for expected_sequence, event in enumerate(history, start=1):
        event_name = f"campaign_history[{expected_sequence - 1}]"
        _require_mapping(event, event_name)
        _require_closed_fields(
            event,
            {"sequence", "event_kind", "actor_kind", "subject_id", "payload"},
            event_name,
        )
        if event.get("sequence") != expected_sequence:
            raise EvidenceBundleError("campaign_history must be complete and monotonically sequenced")
        for key in ("event_kind", "actor_kind", "subject_id"):
            if not isinstance(event.get(key), str) or not event[key]:
                raise EvidenceBundleError(f"campaign_history event requires {key}")
        _require_mapping(event.get("payload"), f"{event_name}.payload")
    if scope == "development_campaign":
        _validate_development_history(history)

    receipts = payload["receipt_chain"]
    if not isinstance(receipts, list):
        raise EvidenceBundleError("receipt_chain must be a list")
    for index, digest in enumerate(receipts):
        _require_digest({"digest": digest}, "digest", prefix=f"receipt_chain[{index}].")
    if len(receipts) != len(set(receipts)):
        raise EvidenceBundleError("receipt_chain cannot contain duplicate receipt digests")

    if scope == "validation":
        if executions or history or receipts:
            raise EvidenceBundleError("validation-scoped evidence cannot imply campaign execution history")
        return
    required_executions = {"baseline"}
    required_executions.update(
        candidate["candidate_id"]
        for candidate in candidates
        if candidate.get("outcome") in {"evaluated", "selected", "failed"}
    )
    missing_executions = sorted(required_executions - observed_subjects)
    if missing_executions:
        raise EvidenceBundleError(f"campaign evidence lacks exact execution bindings for: {missing_executions}")
    if not history:
        raise EvidenceBundleError("campaign evidence requires complete orchestration history")
    if scope == "development_campaign" and (
        payload["confirmation"] is not None
        or receipts
        or any(execution["receipt_digest"] is not None for execution in executions)
    ):
        raise EvidenceBundleError("development evidence cannot contain confirmation or receipt-chain claims")
    if scope == "development_campaign" and payload["conclusion"] != "not_demonstrated":
        raise EvidenceBundleError("development evidence cannot claim a scientific conclusion")
    if scope == "confirmation_campaign":
        if payload["confirmation"] is None or not receipts:
            raise EvidenceBundleError("confirmation evidence requires a confirmation and receipt chain")
        _validate_confirmation_record(payload["confirmation"], candidate_ids, payload["conclusion"])
        _validate_confirmation_history(
            history,
            receipts,
            payload["confirmation"],
            payload["human_decisions"],
        )


def _validate_confirmation_record(
    confirmation: Mapping[str, Any],
    candidate_ids: set[str],
    conclusion: str,
) -> None:
    """Validate the closed M3.5 terminal confirmation evidence record."""
    required = {
        "schema_version",
        "candidate_id",
        "benchmark_id",
        "benchmark_status",
        "request_digest",
        "result_digest",
        "local_evidence_digest",
        "terminal_receipt_digest",
        "development_dataset_reference_digest",
        "development_content_digest",
        "development_split_digest",
        "confirmation_dataset_reference_digest",
        "confirmation_content_digest",
        "confirmation_split_digest",
        "metric_plan_digest",
        "decision_plan_digest",
        "status",
        "metrics",
        "uncertainty",
        "failure_class",
        "conclusion",
        "claim_eligible",
    }
    _require_closed_fields(confirmation, required, "confirmation")
    if confirmation["schema_version"] != _CONFIRMATION_SCHEMA_VERSION:
        raise EvidenceBundleError("confirmation evidence schema is unsupported")
    if confirmation["candidate_id"] not in candidate_ids:
        raise EvidenceBundleError("confirmation candidate_id is not present in candidates")
    for key in ("benchmark_id", "benchmark_status"):
        _require_bounded_string(confirmation[key], f"confirmation.{key}", minimum=3, maximum=64)
    for key in (
        "terminal_receipt_digest",
        "development_dataset_reference_digest",
        "development_content_digest",
        "development_split_digest",
        "confirmation_dataset_reference_digest",
        "confirmation_content_digest",
        "confirmation_split_digest",
        "metric_plan_digest",
        "decision_plan_digest",
    ):
        _require_digest(confirmation, key, prefix="confirmation.")
    status = confirmation["status"]
    if status not in _CONFIRMATION_STATUSES:
        raise EvidenceBundleError("confirmation status is unsupported")
    if confirmation["result_digest"] is not None:
        _require_digest(confirmation, "result_digest", prefix="confirmation.")
    elif status != "replacement_denied":
        raise EvidenceBundleError(
            "confirmation result_digest may be absent only for a pre-execution protocol deviation"
        )
    if not isinstance(confirmation["claim_eligible"], bool):
        raise EvidenceBundleError("confirmation claim_eligible must be boolean")
    if confirmation["benchmark_status"] == "public_reproducibility_only" and confirmation["claim_eligible"]:
        raise EvidenceBundleError("public reproducibility evidence cannot be claim eligible")
    if confirmation["conclusion"] != conclusion:
        raise EvidenceBundleError("confirmation and bundle conclusions disagree")
    if status == "succeeded":
        for key in ("request_digest", "local_evidence_digest"):
            _require_digest(confirmation, key, prefix="confirmation.")
        _require_mapping(confirmation["metrics"], "confirmation.metrics")
        _require_mapping(confirmation["uncertainty"], "confirmation.uncertainty")
        if confirmation["failure_class"] is not None:
            raise EvidenceBundleError("successful confirmation cannot carry failure_class")
        if conclusion not in {"improved", "no_defensible_improvement"}:
            raise EvidenceBundleError("successful confirmation requires a scientific conclusion")
    else:
        if confirmation["request_digest"] is not None:
            _require_digest(confirmation, "request_digest", prefix="confirmation.")
        if confirmation["local_evidence_digest"] is not None:
            raise EvidenceBundleError("failed confirmation cannot carry exact-success evidence")
        if confirmation["metrics"] is not None or confirmation["uncertainty"] is not None:
            raise EvidenceBundleError("failed confirmation cannot carry successful metrics")
        _require_bounded_string(
            confirmation["failure_class"],
            "confirmation.failure_class",
            minimum=1,
            maximum=64,
        )
        if conclusion != "not_demonstrated":
            raise EvidenceBundleError("failed confirmation cannot support a scientific conclusion")


def _validate_confirmation_history(
    history: Sequence[Mapping[str, Any]],
    receipts: Sequence[str],
    confirmation: Mapping[str, Any],
    human_decisions: Any,
) -> None:
    first_confirmation = next(
        (
            index
            for index, event in enumerate(history)
            if event["event_kind"].startswith("confirmation_") or event["event_kind"] == "campaign_concluded"
        ),
        None,
    )
    if first_confirmation is None:
        raise EvidenceBundleError("confirmation evidence lacks terminal lifecycle history")
    _validate_development_history(history[:first_confirmation])
    confirmation_events = history[first_confirmation:]
    receipt_events: list[Mapping[str, Any]] = []
    for index, event in enumerate(confirmation_events, start=first_confirmation):
        name = f"campaign_history[{index}]"
        event_kind = event["event_kind"]
        payload = event["payload"]
        if event_kind == "campaign_concluded":
            if index != len(history) - 1:
                raise EvidenceBundleError("campaign_concluded must be the final history event")
            _require_actor(event["actor_kind"], "orchestrator", name)
            _require_closed_fields(
                payload,
                {
                    "conclusion",
                    "reason_code",
                    "decision_plan_digest",
                    "terminal_receipt_digest",
                },
                f"{name}.payload",
            )
            if payload["conclusion"] != confirmation["conclusion"]:
                raise EvidenceBundleError("campaign conclusion history disagrees with confirmation")
            for key in ("decision_plan_digest", "terminal_receipt_digest"):
                _require_digest(payload, key, prefix=f"{name}.payload.")
            _require_bounded_string(
                payload["reason_code"],
                f"{name}.payload.reason_code",
                minimum=3,
                maximum=64,
            )
            continue
        expected_actor = {
            "confirmation_authorization_consumed": "human",
            "confirmation_attempt_terminal": "runner",
            "confirmation_replacement_authorized": "human",
            "confirmation_protocol_deviation": "human",
        }.get(event_kind)
        if expected_actor is None:
            raise EvidenceBundleError(f"{name} has an unsupported confirmation event_kind")
        _require_actor(event["actor_kind"], expected_actor, name)
        _require_closed_fields(
            payload,
            {
                "receipt_digest",
                "authorization_id",
                "evaluation_sequence",
                "disposition",
                "result_digest",
                "evidence_digest",
                "failure_code",
                "claim_eligibility_effect",
            },
            f"{name}.payload",
        )
        _require_digest(payload, "receipt_digest", prefix=f"{name}.payload.")
        for key in ("result_digest", "evidence_digest"):
            if payload[key] is not None:
                _require_digest(payload, key, prefix=f"{name}.payload.")
        _require_bounded_string(
            payload["authorization_id"],
            f"{name}.payload.authorization_id",
            minimum=3,
            maximum=64,
        )
        if (
            isinstance(payload["evaluation_sequence"], bool)
            or not isinstance(payload["evaluation_sequence"], int)
            or not 1 <= payload["evaluation_sequence"] <= 3
        ):
            raise EvidenceBundleError(f"{name}.payload evaluation_sequence is invalid")
        receipt_events.append(event)
    observed_receipts = [event["payload"]["receipt_digest"] for event in receipt_events]
    if observed_receipts != list(receipts):
        raise EvidenceBundleError("confirmation history does not exactly reproduce the receipt chain")
    if confirmation_events[-1]["event_kind"] != "campaign_concluded":
        raise EvidenceBundleError("confirmation history lacks its final campaign conclusion")
    if confirmation["terminal_receipt_digest"] != receipts[-1]:
        raise EvidenceBundleError("confirmation terminal receipt is not the receipt-chain head")
    deviation_events = [event for event in receipt_events if event["event_kind"] == "confirmation_protocol_deviation"]
    if deviation_events:
        if not isinstance(human_decisions, list):
            raise EvidenceBundleError("protocol deviation requires a human decision")
        deviation_decisions = [
            decision
            for decision in human_decisions
            if isinstance(decision, Mapping) and decision.get("decision") == "protocol_deviation"
        ]
        if len(deviation_decisions) != len(deviation_events):
            raise EvidenceBundleError("each protocol deviation requires exactly one human decision")
        decisions_by_receipt = {decision.get("receipt_digest"): decision for decision in deviation_decisions}
        for event in deviation_events:
            payload = event["payload"]
            decision = decisions_by_receipt.get(payload["receipt_digest"])
            if decision is None:
                raise EvidenceBundleError("protocol-deviation decision does not bind its receipt")
            _require_closed_fields(
                decision,
                {
                    "decision",
                    "actor_ref",
                    "actor_role",
                    "reason_code",
                    "prior_receipt_digest",
                    "receipt_digest",
                    "claim_eligibility_effect",
                },
                "protocol-deviation human decision",
            )
            for key in ("actor_ref", "actor_role", "reason_code"):
                _require_bounded_string(
                    decision[key],
                    f"protocol-deviation human decision.{key}",
                    minimum=3,
                    maximum=160,
                )
            if not decision["actor_ref"].startswith("urn:spectra:"):
                raise EvidenceBundleError("protocol-deviation human decision actor_ref must be opaque")
            _require_digest(
                decision,
                "prior_receipt_digest",
                prefix="protocol-deviation human decision.",
            )
            if (
                decision["reason_code"] != payload["failure_code"]
                or decision["claim_eligibility_effect"] != "forfeited"
                or payload["claim_eligibility_effect"] != "forfeited"
            ):
                raise EvidenceBundleError("protocol-deviation human decision disagrees with its receipt")


def _validate_development_history(history: Sequence[Mapping[str, Any]]) -> None:
    """Validate the closed M3.4 development event vocabulary and payloads."""
    for index, event in enumerate(history):
        name = f"campaign_history[{index}]"
        event_kind = event["event_kind"]
        actor_kind = event["actor_kind"]
        subject_id = event["subject_id"]
        payload = event["payload"]

        if event_kind == "candidate_planned":
            _require_actor(actor_kind, "orchestrator", name)
            _require_closed_fields(
                payload,
                {
                    "candidate_kind",
                    "candidate_digest",
                    "workflow_digest",
                    "proposal_provenance",
                },
                f"{name}.payload",
            )
            candidate_kind = payload["candidate_kind"]
            if candidate_kind not in _DEVELOPMENT_CANDIDATE_KINDS:
                raise EvidenceBundleError(f"{name}.payload has an unsupported candidate_kind")
            for key in ("candidate_digest", "workflow_digest"):
                _require_digest(payload, key, prefix=f"{name}.payload.")
            provenance = payload["proposal_provenance"]
            if candidate_kind == "managed_proposal":
                _validate_proposal_provenance(provenance, f"{name}.payload.proposal_provenance")
            elif provenance is not None:
                raise EvidenceBundleError(f"{name}.payload proposal_provenance is permitted only for managed_proposal")
            continue

        if event_kind in {"evaluation_succeeded", "evaluation_failed"}:
            _require_actor(actor_kind, "runner", name)
            _require_closed_fields(
                payload,
                {"status", "result_digest", "local_evidence_digest", "failure_class"},
                f"{name}.payload",
            )
            _require_digest(payload, "result_digest", prefix=f"{name}.payload.")
            if event_kind == "evaluation_succeeded":
                if payload["status"] != "succeeded":
                    raise EvidenceBundleError(f"{name}.payload status contradicts event_kind")
                _require_digest(
                    payload,
                    "local_evidence_digest",
                    prefix=f"{name}.payload.",
                )
                if payload["failure_class"] is not None:
                    raise EvidenceBundleError(f"{name}.payload successful evaluation cannot carry failure_class")
            else:
                if payload["status"] not in _DEVELOPMENT_FAILURE_STATUSES:
                    raise EvidenceBundleError(f"{name}.payload has an unsupported failure status")
                if payload["local_evidence_digest"] is not None:
                    raise EvidenceBundleError(f"{name}.payload failed evaluation cannot carry local_evidence_digest")
                _require_bounded_string(
                    payload["failure_class"],
                    f"{name}.payload.failure_class",
                    minimum=1,
                    maximum=64,
                )
            continue

        if event_kind == "human_intervention":
            _require_actor(actor_kind, "human", name)
            _require_closed_fields(
                payload,
                {"actor_ref", "actor_role", "decision", "reason_code"},
                f"{name}.payload",
            )
            for key, minimum, maximum in (
                ("actor_ref", 3, 128),
                ("actor_role", 2, 64),
                ("decision", 1, 256),
                ("reason_code", 2, 64),
            ):
                _require_bounded_string(
                    payload[key],
                    f"{name}.payload.{key}",
                    minimum=minimum,
                    maximum=maximum,
                )
            if subject_id != payload["actor_ref"]:
                raise EvidenceBundleError(f"{name}.subject_id must match the human actor_ref")
            continue

        if event_kind == "search_stopped":
            _require_actor(actor_kind, "orchestrator", name)
            _require_closed_fields(
                payload,
                {"reason", "development_conclusion"},
                f"{name}.payload",
            )
            _require_bounded_string(
                payload["reason"],
                f"{name}.payload.reason",
                minimum=3,
                maximum=64,
            )
            if payload["development_conclusion"] not in _DEVELOPMENT_CONCLUSIONS:
                raise EvidenceBundleError(f"{name}.payload has an unsupported development_conclusion")
            continue

        if event_kind == "candidate_selected":
            _require_actor(actor_kind, "orchestrator", name)
            _require_closed_fields(payload, {"reason"}, f"{name}.payload")
            _require_bounded_string(
                payload["reason"],
                f"{name}.payload.reason",
                minimum=3,
                maximum=64,
            )
            continue

        raise EvidenceBundleError(f"{name} has an unsupported development event_kind")


def _validate_proposal_provenance(value: Any, name: str) -> None:
    _require_mapping(value, name)
    _require_closed_fields(
        value,
        {
            "proposer_kind",
            "proposer_id",
            "proposer_version",
            "policy_digest",
            "parameters_digest",
        },
        name,
    )
    if value["proposer_kind"] not in _PROPOSER_KINDS:
        raise EvidenceBundleError(f"{name}.proposer_kind is unsupported")
    for key in ("proposer_id", "proposer_version"):
        _require_bounded_string(
            value[key],
            f"{name}.{key}",
            minimum=1,
            maximum=128,
        )
    for key in ("policy_digest", "parameters_digest"):
        _require_digest(value, key, prefix=f"{name}.")


def _require_actor(actual: str, expected: str, event_name: str) -> None:
    if actual != expected:
        raise EvidenceBundleError(f"{event_name} requires actor_kind={expected!r}")


def _require_closed_fields(value: Mapping[str, Any], required: set[str], name: str) -> None:
    if any(not isinstance(key, str) for key in value):
        raise EvidenceBundleError(f"{name} fields must use string keys")
    missing = sorted(required - set(value))
    extra = sorted(set(value) - required)
    if missing or extra:
        raise EvidenceBundleError(f"{name} fields are closed: missing={missing}, extra={extra}")


def _require_bounded_string(value: Any, name: str, *, minimum: int, maximum: int) -> None:
    if not isinstance(value, str) or not minimum <= len(value) <= maximum:
        raise EvidenceBundleError(f"{name} must be a bounded string")


def _require_mapping(value: Any, name: str) -> None:
    if not isinstance(value, Mapping):
        raise EvidenceBundleError(f"{name} must be an object")


def _validate_evaluation_diagnostics(
    diagnostics: Any,
    candidate_ids: set[str],
    candidates: Sequence[Mapping[str, Any]],
) -> None:
    if not isinstance(diagnostics, list) or not diagnostics:
        raise EvidenceBundleError("evaluation_diagnostics must be a non-empty list")
    required_subjects = {"baseline"}
    required_subjects.update(
        candidate["candidate_id"] for candidate in candidates if candidate.get("outcome") in {"evaluated", "selected"}
    )
    observed_subjects: set[str] = set()
    for index, diagnostic in enumerate(diagnostics):
        _require_mapping(diagnostic, f"evaluation_diagnostics[{index}]")
        subject_id = diagnostic.get("subject_id")
        if not isinstance(subject_id, str) or subject_id not in {"baseline", *candidate_ids}:
            raise EvidenceBundleError(f"evaluation_diagnostics[{index}] has an unknown subject_id")
        if subject_id in observed_subjects:
            raise EvidenceBundleError(f"duplicate evaluation diagnostics subject_id: {subject_id!r}")
        observed_subjects.add(subject_id)
        cross_validation = diagnostic.get("cross_validation")
        _require_mapping(cross_validation, f"evaluation_diagnostics[{index}].cross_validation")
        folds = cross_validation.get("folds")
        if not isinstance(folds, list) or not folds:
            raise EvidenceBundleError(f"evaluation_diagnostics[{index}] requires non-empty cross_validation.folds")
        for fold_index, fold in enumerate(folds):
            _require_mapping(fold, f"evaluation_diagnostics[{index}].folds[{fold_index}]")
            if not isinstance(fold.get("fold_index"), int) or fold["fold_index"] < 0:
                raise EvidenceBundleError(f"evaluation diagnostics fold {fold_index} requires non-negative fold_index")
            for key in ("train_indices", "test_indices", "observed", "predictions"):
                if not isinstance(fold.get(key), list):
                    raise EvidenceBundleError(f"evaluation diagnostics fold {fold_index} requires {key} list")
            if not fold["test_indices"] or len(fold["observed"]) != len(fold["predictions"]):
                raise EvidenceBundleError(f"evaluation diagnostics fold {fold_index} has inconsistent exact outputs")
            _require_mapping(fold.get("metrics"), f"evaluation diagnostics fold {fold_index}.metrics")
    missing_subjects = sorted(required_subjects - observed_subjects)
    if missing_subjects:
        raise EvidenceBundleError(f"missing exact evaluation diagnostics for: {missing_subjects}")


def _require_digest(value: Mapping[str, Any], key: str, *, prefix: str = "") -> None:
    digest = value.get(key)
    if not isinstance(digest, str) or len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
        raise EvidenceBundleError(f"{prefix}{key} must be a lowercase SHA-256 hex digest")


def _canonical_json(payload: Mapping[str, Any]) -> bytes:
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def _digest(payload: Mapping[str, Any]) -> str:
    return hashlib.sha256(_canonical_json(payload)).hexdigest()


__all__ = [
    "EVIDENCE_BUNDLE_SCHEMA_VERSION",
    "EvidenceBundle",
    "EvidenceBundleError",
    "evidence_bundle",
    "verify_evidence_bundle",
]
