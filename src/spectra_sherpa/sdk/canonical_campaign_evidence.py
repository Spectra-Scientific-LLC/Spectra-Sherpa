"""Portable, data-free evidence for one completed canonical search campaign.

The fitted artifact says *what can be applied*.  This closed record says
*why this particular artifact was selected*: every declared development
candidate, either its bounded validation metric record or its exact terminal
failure identity, the frozen selection decision, and the single all-data refit
that followed.  It contains
no spectra, targets, predictions, fitted-state bytes, filesystem locations,
credentials, or free-form diagnostics.

It deliberately makes no publisher or scientific-correctness claim.  A later
publisher attestation may authenticate its content root, while the OSS
reproduction report independently recomputes the selected validation result.
"""

from __future__ import annotations

import hashlib
import json
import re
from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Mapping

from spectra_sherpa.app.services.dag import canonical_selection_policy as _canonical_selection_policy
from spectra_sherpa.app.services.dag.validation_graph import (
    ValidationGraphError,
    validation_graph_from_dict,
)

from . import canonical_execution_evidence as _canonical_execution_evidence

CANONICAL_CAMPAIGN_EVIDENCE_VERSION = "spectra-canonical-campaign-evidence/6"
REVIEWED_CAMPAIGN_EVIDENCE_VERSION = "spectra-canonical-campaign-evidence/7"
REVIEWED_SELECTION_VERSION = "spectra-scientist-reviewed-selection/1"
_REVIEWED_FIELDS = frozenset(
    {
        "schema_version",
        "selection_claim",
        "winner_candidate_id",
        "selected_graph_digest",
        "selected_result_digest",
        "promotion_decision_digest",
        "checkpoint_digest",
        "settlement_digest",
        "reason_code",
    }
)

_DIGEST = re.compile(r"^[0-9a-f]{64}$")
_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{2,127}$")
_ROOT_FIELDS = frozenset({"schema_version", "campaign", "candidates", "decision", "winner_refit", "content_digest"})
_CAMPAIGN_FIELDS = frozenset(
    {
        "campaign_id",
        "search_space_digest",
        "decision_digest",
        "claim_scope",
        "optimization_lane",
    }
)
_SUCCESS_CANDIDATE_FIELDS = frozenset(
    {
        "status",
        "candidate_id",
        "ordinal",
        "declared_ordinal",
        "candidate_digest",
        "graph_digest",
        "candidate_graph",
        "request_digest",
        "result_digest",
        "validation_execution",
    }
)
_FAILED_CANDIDATE_FIELDS = frozenset(
    {
        "status",
        "candidate_id",
        "declared_ordinal",
        "candidate_digest",
        "graph_digest",
        "candidate_graph",
        "request_digest",
        "result_digest",
        "failure_status",
        "failure_code",
    }
)
_FAILURE_STATUSES = frozenset(
    {
        "scientific_failure",
        "execution_failure",
        "timeout",
        "crash",
        "cancelled",
        "malformed_result",
    }
)
_OPTIMIZATION_LANES = frozenset({"quantitative_calibration", "categorical_classification", "class_modelling"})
_WINNER_REFIT_FIELDS = frozenset(
    {
        "candidate_id",
        "authority_digest",
        "refit_request_digest",
        "refit_terminal_digest",
        "full_refit_execution_digest",
        "artifact_digest",
    }
)


class CanonicalCampaignEvidenceError(ValueError):
    """A portable campaign result record is malformed or internally inconsistent."""


def _canonical_json(value: Mapping[str, Any]) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False).encode("utf-8")


def _digest(value: Mapping[str, Any]) -> str:
    return hashlib.sha256(_canonical_json(value)).hexdigest()


def _closed(value: Any, fields: frozenset[str], label: str) -> dict[str, Any]:
    if not isinstance(value, Mapping) or set(value) != fields:
        raise CanonicalCampaignEvidenceError(f"{label} fields are closed")
    return deepcopy(dict(value))


def _identifier(value: Any, field: str) -> str:
    if not isinstance(value, str) or not _IDENTIFIER.fullmatch(value):
        raise CanonicalCampaignEvidenceError(f"{field} is invalid")
    return value


def _digest_value(value: Any, field: str) -> str:
    if not isinstance(value, str) or not _DIGEST.fullmatch(value):
        raise CanonicalCampaignEvidenceError(f"{field} is not a lowercase SHA-256 digest")
    return value


def _declared_candidate_identity(candidate: dict[str, Any]) -> dict[str, Any]:
    candidate["candidate_id"] = _identifier(candidate["candidate_id"], "candidate_id")
    if (
        isinstance(candidate["declared_ordinal"], bool)
        or not isinstance(candidate["declared_ordinal"], int)
        or candidate["declared_ordinal"] < 1
    ):
        raise CanonicalCampaignEvidenceError("candidate declared ordinal is invalid")
    for field in {"candidate_digest", "graph_digest", "request_digest", "result_digest"}:
        candidate[field] = _digest_value(candidate[field], f"candidate.{field}")
    if candidate["candidate_digest"] != candidate["graph_digest"]:
        raise CanonicalCampaignEvidenceError("candidate graph identity changed")
    candidate["candidate_graph"] = _candidate_graph(
        candidate["candidate_graph"],
        expected_digest=candidate["graph_digest"],
    )
    return candidate


def _candidate_graph(value: Any, *, expected_digest: str) -> dict[str, Any]:
    """Re-admit one complete graph through the canonical graph authority.

    The package path deliberately disables only the installed-runtime probe.
    Operation identity, parameters, contracts, typed topology, graph digest,
    and managed-profile membership are still checked by the same authority
    used for execution.
    """

    if not isinstance(value, Mapping):
        raise CanonicalCampaignEvidenceError("candidate graph is invalid")
    raw_nodes = value.get("nodes")
    raw_edges = value.get("edges")
    if (
        not isinstance(raw_nodes, list)
        or not 1 <= len(raw_nodes) <= 64
        or not isinstance(raw_edges, list)
        or len(raw_edges) > 256
    ):
        raise CanonicalCampaignEvidenceError("candidate graph topology is outside the supported bound")
    try:
        graph = validation_graph_from_dict(dict(value), require_live_runtime=False)
    except ValidationGraphError as exc:
        raise CanonicalCampaignEvidenceError("candidate graph is not canonically admissible") from exc
    if graph.digest != expected_digest:
        raise CanonicalCampaignEvidenceError("candidate graph identity changed")
    return graph.as_dict()


def _candidate(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise CanonicalCampaignEvidenceError("campaign candidate fields are closed")
    status = value.get("status")
    fields = _SUCCESS_CANDIDATE_FIELDS if status == "succeeded" else _FAILED_CANDIDATE_FIELDS
    candidate = _declared_candidate_identity(_closed(value, fields, "campaign candidate"))
    if status == "failed":
        if candidate["failure_status"] not in _FAILURE_STATUSES:
            raise CanonicalCampaignEvidenceError("candidate failure status is invalid")
        failure_code = candidate["failure_code"]
        if not isinstance(failure_code, str) or not 1 <= len(failure_code) <= 64:
            raise CanonicalCampaignEvidenceError("candidate failure code is invalid")
        return candidate
    if status != "succeeded":
        raise CanonicalCampaignEvidenceError("candidate status is invalid")
    if isinstance(candidate["ordinal"], bool) or not isinstance(candidate["ordinal"], int) or candidate["ordinal"] < 1:
        raise CanonicalCampaignEvidenceError("candidate ordinal is invalid")
    try:
        validation, _validation_digest = _canonical_execution_evidence.validate_canonical_validation_execution(
            candidate["validation_execution"]
        )
    except _canonical_execution_evidence.CanonicalExecutionEvidenceError as exc:
        raise CanonicalCampaignEvidenceError("candidate validation execution is invalid") from exc
    if validation["graph_digest"] != candidate["graph_digest"]:
        raise CanonicalCampaignEvidenceError("candidate validation execution changed its graph")
    candidate["validation_execution"] = validation
    return candidate


def _reviewed_decision(value: Any, candidates: tuple[dict[str, Any], ...]) -> dict[str, Any]:
    decision = _closed(value, _REVIEWED_FIELDS, "scientist reviewed selection")
    if (
        decision["schema_version"] != REVIEWED_SELECTION_VERSION
        or decision["selection_claim"] != "scientist_selected_not_automatic_metric_winner"
        or decision["reason_code"]
        not in {"primary_metric", "robustness", "simplicity", "interpretability", "exploratory_stability"}
    ):
        raise CanonicalCampaignEvidenceError("reviewed selection claim is invalid")
    decision["winner_candidate_id"] = _identifier(decision["winner_candidate_id"], "selected candidate")
    for key in _REVIEWED_FIELDS - {"schema_version", "selection_claim", "winner_candidate_id", "reason_code"}:
        _digest_value(decision[key], key)
    selected = next((item for item in candidates if item["candidate_id"] == decision["winner_candidate_id"]), None)
    if (
        selected is None
        or selected["status"] != "succeeded"
        or selected["result_digest"] != decision["selected_result_digest"]
        or selected["graph_digest"] != decision["selected_graph_digest"]
    ):
        raise CanonicalCampaignEvidenceError("reviewed selection does not bind a successful trial")
    populations = {
        (item["validation_execution"]["capability_content_digest"], item["validation_execution"]["split_plan_digest"])
        for item in candidates
        if item["status"] == "succeeded"
    }
    if len(populations) != 1:
        raise CanonicalCampaignEvidenceError("reviewed candidate populations differ")
    return decision


def _decision(value: Any, candidates: tuple[dict[str, Any], ...]) -> dict[str, Any]:
    if isinstance(value, Mapping) and value.get("schema_version") == REVIEWED_SELECTION_VERSION:
        return _reviewed_decision(value, candidates)
    try:
        projected = []
        for candidate in candidates:
            if candidate["status"] != "succeeded":
                continue
            validation = candidate["validation_execution"]
            projected.append(
                _canonical_selection_policy.selection_candidate(
                    candidate_id=candidate["candidate_id"],
                    ordinal=candidate["ordinal"],
                    result_digest=candidate["result_digest"],
                    dataset_content_digest=validation["capability_content_digest"],
                    split_plan_digest=validation["split_plan_digest"],
                    metrics=validation["metrics"],
                    folds=[
                        {
                            "partition_digest": fold["partition_digest"],
                            "metrics": fold["metrics"],
                        }
                        for fold in validation["folds"]
                    ],
                )
            )
        verified = _canonical_selection_policy.verify_canonical_development_decision(value, projected)
        if (
            verified.get("schema_version") == _canonical_selection_policy.SCIENTIST_DEVELOPMENT_DECISION_VERSION
            and verified.get("scientist_selection") is None
        ):
            raise CanonicalCampaignEvidenceError("Ranked results without a scientist selection cannot authorize export")
        return verified
    except _canonical_selection_policy.CanonicalSelectionPolicyError as exc:
        raise CanonicalCampaignEvidenceError("development decision does not reproduce from fold evidence") from exc


@dataclass(frozen=True)
class CanonicalCampaignEvidence:
    """One self-contained, closed result ledger for an exported M4 campaign."""

    payload: dict[str, Any]
    content_digest: str

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "CanonicalCampaignEvidence":
        root = _closed(value, _ROOT_FIELDS, "canonical campaign evidence")
        if root["schema_version"] not in {CANONICAL_CAMPAIGN_EVIDENCE_VERSION, REVIEWED_CAMPAIGN_EVIDENCE_VERSION}:
            raise CanonicalCampaignEvidenceError("canonical campaign evidence version is unsupported")
        campaign = _closed(root["campaign"], _CAMPAIGN_FIELDS, "campaign identity")
        campaign["campaign_id"] = _identifier(campaign["campaign_id"], "campaign_id")
        campaign["search_space_digest"] = _digest_value(campaign["search_space_digest"], "search_space_digest")
        campaign["decision_digest"] = _digest_value(campaign["decision_digest"], "decision_digest")
        if campaign["claim_scope"] != "public_reproducibility_only":
            raise CanonicalCampaignEvidenceError("campaign claim scope is invalid")
        if campaign["optimization_lane"] not in _OPTIMIZATION_LANES:
            raise CanonicalCampaignEvidenceError("campaign optimization lane is invalid")
        raw_candidates = root["candidates"]
        if not isinstance(raw_candidates, list) or not 2 <= len(raw_candidates) <= 6:
            raise CanonicalCampaignEvidenceError("campaign needs a bounded baseline and candidate ledger")
        candidates = tuple(_candidate(item) for item in raw_candidates)
        if tuple(item["declared_ordinal"] for item in candidates) != tuple(range(1, len(candidates) + 1)):
            raise CanonicalCampaignEvidenceError("campaign declared candidate ordinals are not closed")
        successful = tuple(item for item in candidates if item["status"] == "succeeded")
        if len(successful) < 2 or tuple(item["ordinal"] for item in successful) != tuple(range(1, len(successful) + 1)):
            raise CanonicalCampaignEvidenceError("campaign successful candidate ordinals are not closed")
        if len({item["candidate_id"] for item in candidates}) != len(candidates):
            raise CanonicalCampaignEvidenceError("campaign candidate identities are repeated")
        reviewed = (
            isinstance(root["decision"], Mapping)
            and root["decision"].get("schema_version") == REVIEWED_SELECTION_VERSION
        )
        if campaign["optimization_lane"] == "class_modelling" and not reviewed:
            raise CanonicalCampaignEvidenceError("class modelling requires reviewed selection evidence")
        if reviewed != (root["schema_version"] == REVIEWED_CAMPAIGN_EVIDENCE_VERSION):
            raise CanonicalCampaignEvidenceError("selection interpretation differs from evidence version")
        if reviewed:
            lane = campaign["optimization_lane"]
            for candidate in successful:
                validation = candidate["validation_execution"]
                expected_task = "regression" if lane == "quantitative_calibration" else "classification"
                if validation["task_type"] != expected_task or (lane == "class_modelling") != (
                    validation["model_operation_id"] == "classification.simca"
                ):
                    raise CanonicalCampaignEvidenceError("reviewed optimization lane differs from model interpretation")
        decision = _decision(root["decision"], candidates)
        if _digest(decision) != campaign["decision_digest"]:
            raise CanonicalCampaignEvidenceError("campaign decision digest mismatch")
        winner_refit = _closed(root["winner_refit"], _WINNER_REFIT_FIELDS, "winner refit")
        winner_refit["candidate_id"] = _identifier(winner_refit["candidate_id"], "winner refit candidate_id")
        for field in _WINNER_REFIT_FIELDS - {"candidate_id"}:
            winner_refit[field] = _digest_value(winner_refit[field], f"winner_refit.{field}")
        winner = next((item for item in successful if item["candidate_id"] == decision["winner_candidate_id"]), None)
        if winner is None or winner_refit["candidate_id"] != winner["candidate_id"]:
            raise CanonicalCampaignEvidenceError("winner refit does not bind the selected candidate")
        if winner_refit["refit_request_digest"] == winner["request_digest"]:
            raise CanonicalCampaignEvidenceError("winner refit reuses the validation request identity")
        unsigned = {
            "schema_version": root["schema_version"],
            "campaign": campaign,
            "candidates": list(candidates),
            "decision": decision,
            "winner_refit": winner_refit,
        }
        content_digest = _digest_value(root["content_digest"], "content_digest")
        if _digest(unsigned) != content_digest:
            raise CanonicalCampaignEvidenceError("canonical campaign evidence content digest mismatch")
        return cls(payload={**unsigned, "content_digest": content_digest}, content_digest=content_digest)

    @classmethod
    def build(
        cls,
        *,
        campaign: Mapping[str, Any],
        candidates: list[Mapping[str, Any]],
        decision: Mapping[str, Any],
        winner_refit: Mapping[str, Any],
    ) -> "CanonicalCampaignEvidence":
        """Create then re-admit one closed, data-free campaign evidence record."""

        unsigned = {
            "schema_version": (
                REVIEWED_CAMPAIGN_EVIDENCE_VERSION
                if decision.get("schema_version") == REVIEWED_SELECTION_VERSION
                else CANONICAL_CAMPAIGN_EVIDENCE_VERSION
            ),
            "campaign": deepcopy(dict(campaign)),
            "candidates": [deepcopy(dict(item)) for item in candidates],
            "decision": deepcopy(dict(decision)),
            "winner_refit": deepcopy(dict(winner_refit)),
        }
        candidate_payload = tuple(_candidate(item) for item in unsigned["candidates"])
        decision_payload = _decision(unsigned["decision"], candidate_payload)
        normalized_campaign = _closed(unsigned["campaign"], _CAMPAIGN_FIELDS, "campaign identity")
        normalized_campaign["decision_digest"] = _digest(decision_payload)
        unsigned["campaign"] = normalized_campaign
        unsigned["decision"] = decision_payload
        return cls.from_dict({**unsigned, "content_digest": _digest(unsigned)})

    def as_dict(self) -> dict[str, Any]:
        return deepcopy(self.payload)

    def canonical_bytes(self) -> bytes:
        return _canonical_json(self.payload)

    def require_matches(self, capsule: Any, artifact: Any, application_plan: Any) -> None:
        """Bind this selection ledger to the exact exported application.

        The ledger intentionally remains an OSS data contract instead of
        importing the canonical package types.  This keeps the package loader
        as the single ownership boundary while making substitution of a
        separately well-formed campaign record fail closed.
        """

        request = getattr(capsule, "payload", {}).get("admitted_request")
        evidence = getattr(capsule, "execution_evidence", None)
        plan = getattr(application_plan, "payload", None)
        artifact_payload = getattr(artifact, "payload", None)
        artifact_digest = getattr(artifact, "artifact_digest", None)
        if not all(isinstance(value, Mapping) for value in (request, plan, artifact_payload)):
            raise CanonicalCampaignEvidenceError("canonical campaign evidence cannot bind package identities")
        validation_execution_digest = getattr(evidence, "validation_execution_digest", None)
        if not isinstance(validation_execution_digest, str) or not isinstance(artifact_digest, str):
            raise CanonicalCampaignEvidenceError("canonical campaign evidence cannot bind package identities")

        winner_id = self.payload["decision"]["winner_candidate_id"]
        winner = next(
            (
                candidate
                for candidate in self.payload["candidates"]
                if candidate["status"] == "succeeded" and candidate["candidate_id"] == winner_id
            ),
            None,
        )
        if winner is None:
            raise CanonicalCampaignEvidenceError("canonical campaign evidence winner is unavailable")
        refit = self.payload["winner_refit"]
        _validation, winner_validation_digest = _canonical_execution_evidence.validate_canonical_validation_execution(
            winner["validation_execution"]
        )
        expected = {
            "candidate_id": request.get("candidate_id"),
            "graph_digest": plan.get("graph_digest"),
            "request_digest": request.get("request_digest"),
            "validation_execution_digest": validation_execution_digest,
            "artifact_digest": artifact_digest,
            "full_refit_execution_digest": plan.get("full_refit_execution_digest"),
        }
        actual = {
            "candidate_id": winner.get("candidate_id"),
            "graph_digest": winner.get("graph_digest"),
            "request_digest": winner.get("request_digest"),
            "validation_execution_digest": winner_validation_digest,
            "artifact_digest": refit.get("artifact_digest"),
            "full_refit_execution_digest": refit.get("full_refit_execution_digest"),
        }
        if actual != expected:
            raise CanonicalCampaignEvidenceError("canonical campaign evidence differs from package identities")
        artifact_refit = artifact_payload.get("full_refit_evidence")
        if not isinstance(artifact_refit, Mapping) or (
            artifact_refit.get("full_refit_execution_digest") != expected["full_refit_execution_digest"]
        ):
            raise CanonicalCampaignEvidenceError("canonical campaign evidence differs from fitted artifact")


__all__ = [
    "CANONICAL_CAMPAIGN_EVIDENCE_VERSION",
    "CanonicalCampaignEvidence",
    "CanonicalCampaignEvidenceError",
]
