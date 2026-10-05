"""Bounded remote summary derived from a verified canonical capsule."""

from __future__ import annotations

import hashlib
import json
import math
import re
from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Mapping

from .canonical_capsule import CanonicalWorkflowCapsule
from .validate import REGRESSION_METRIC_FIELDS, REGRESSION_METRIC_REGISTRY_VERSION, validate_supervised_metric_record

CANONICAL_REMOTE_SUMMARY_VERSION = "spectra-canonical-remote-summary/3"
MAX_CANONICAL_REMOTE_SUMMARY_BYTES = 64 * 1024

_DIGEST = re.compile(r"^[0-9a-f]{64}$")
_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{2,127}$")
_SUMMARY_FIELDS = frozenset(
    {
        "schema_version",
        "capsule_digest",
        "request_digest",
        "campaign_id",
        "candidate_id",
        "profile_digest",
        "graph_digest",
        "runtime_digest",
        "evaluation_kind",
        "dataset_role",
        "dataset_binding_digest",
        "dataset_shape",
        "fold_count",
        "nodes",
        "metrics",
    }
) | frozenset({"application_refit"})
_NODE_FIELDS = frozenset(
    {
        "node_id",
        "operation_id",
        "contract_digest",
        "parameter_digest",
        "runtime_family",
        "implementation_id",
        "implementation_version",
        "deterministic",
        "fitted_state_recorded",
    }
)
_METRIC_FIELDS = REGRESSION_METRIC_FIELDS
_REFIT_ABSENT_FIELDS = frozenset({"status"})
_REFIT_MATERIALIZED_FIELDS = frozenset(
    {"status", "full_refit_evidence_digest", "full_refit_execution_digest", "model_node_id", "fitted_state_node_ids"}
)


class CanonicalRemoteSummaryError(ValueError):
    """A remote summary is malformed, unbounded, or detached from its capsule."""


@dataclass(frozen=True)
class CanonicalRemoteSummary:
    """Sample-free projection suitable for policy-controlled remote exchange."""

    payload: dict[str, Any]
    summary_digest: str

    @classmethod
    def from_capsule(cls, capsule: CanonicalWorkflowCapsule) -> "CanonicalRemoteSummary":
        serializer = getattr(capsule, "as_dict", None)
        if not callable(serializer):
            raise CanonicalRemoteSummaryError("remote summary requires a verified canonical capsule")
        # Dataclass construction is not validation authority. Reparse before
        # projecting so a hand-built lookalike cannot bypass capsule checks.
        capsule = CanonicalWorkflowCapsule.from_dict(serializer())
        request = capsule.payload["admitted_request"]
        evidence = capsule.execution_evidence.payload
        validation = evidence["validation_execution"]
        first_trace = evidence["node_execution_traces"][0]["nodes"]
        dataset_binding = {
            "capability_digest": request["capability_digest"],
            "dataset_content_digest": request["dataset_content_digest"],
            "dataset_ref_digest": request["dataset_ref_digest"],
            "split_digest": request["split_digest"],
        }
        if capsule.full_refit_evidence is None:
            refit_summary: dict[str, Any] = {"status": "not_materialized"}
        else:
            refit = capsule.full_refit_evidence.payload["full_refit_execution"]
            refit_summary = {
                "status": "materialized",
                "full_refit_evidence_digest": capsule.full_refit_evidence.content_digest,
                "full_refit_execution_digest": capsule.full_refit_evidence.full_refit_execution_digest,
                "model_node_id": refit["model_node_id"],
                "fitted_state_node_ids": [item["node_id"] for item in refit["fitted_state_references"]],
            }
        payload = {
            "schema_version": CANONICAL_REMOTE_SUMMARY_VERSION,
            "capsule_digest": capsule.capsule_digest,
            "request_digest": request["request_digest"],
            "campaign_id": request["campaign_id"],
            "candidate_id": request["candidate_id"],
            "profile_digest": request["profile"]["profile_digest"],
            "graph_digest": request["graph"]["graph_digest"],
            "runtime_digest": request["runtime_attestation"]["digest"],
            "evaluation_kind": request["evaluation_kind"],
            "dataset_role": request["dataset_role"],
            "dataset_binding_digest": _digest(dataset_binding),
            "dataset_shape": deepcopy(request["dataset_shape"]),
            "fold_count": len(validation["folds"]),
            "nodes": [
                {
                    "node_id": trace["node_id"],
                    "operation_id": trace["operation_id"],
                    "contract_digest": trace["contract_digest"],
                    "parameter_digest": trace["parameter_digest"],
                    "runtime_family": trace["contract"]["runtime_family"],
                    "implementation_id": trace["contract"]["implementation_id"],
                    "implementation_version": trace["contract"]["implementation_version"],
                    "deterministic": trace["contract"]["deterministic"],
                    "fitted_state_recorded": trace["fitted_state_digest"] is not None,
                }
                for trace in first_trace
            ],
            "metrics": deepcopy(validation["metrics"]),
        }
        payload["application_refit"] = refit_summary
        return cls._validated(payload)

    @classmethod
    def from_dict(cls, manifest: Mapping[str, Any]) -> "CanonicalRemoteSummary":
        if not isinstance(manifest, Mapping):
            raise CanonicalRemoteSummaryError("canonical remote summary must be an object")
        expected = manifest.get("summary_digest")
        _require_digest(expected, "summary_digest")
        payload = {key: deepcopy(value) for key, value in manifest.items() if key != "summary_digest"}
        summary = cls._validated(payload)
        if summary.summary_digest != expected:
            raise CanonicalRemoteSummaryError("canonical remote summary content digest mismatch")
        return summary

    @classmethod
    def from_bytes(cls, value: bytes) -> "CanonicalRemoteSummary":
        if not 1 <= len(value) <= MAX_CANONICAL_REMOTE_SUMMARY_BYTES:
            raise CanonicalRemoteSummaryError("canonical remote summary size is outside the allowed bound")
        try:
            manifest = json.loads(value, object_pairs_hook=_reject_duplicate_fields)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise CanonicalRemoteSummaryError("canonical remote summary must be UTF-8 JSON") from exc
        summary = cls.from_dict(manifest)
        if summary.canonical_bytes() != value:
            raise CanonicalRemoteSummaryError("canonical remote summary must use canonical JSON")
        return summary

    @classmethod
    def _validated(cls, payload: Mapping[str, Any]) -> "CanonicalRemoteSummary":
        version = payload.get("schema_version")
        if version != CANONICAL_REMOTE_SUMMARY_VERSION:
            raise CanonicalRemoteSummaryError("canonical remote summary schema is unsupported")
        _require_closed(payload, _SUMMARY_FIELDS, "canonical remote summary")
        for field in (
            "capsule_digest",
            "request_digest",
            "profile_digest",
            "graph_digest",
            "runtime_digest",
            "dataset_binding_digest",
        ):
            _require_digest(payload[field], field)
        for field in ("campaign_id", "candidate_id"):
            if not isinstance(payload[field], str) or _IDENTIFIER.fullmatch(payload[field]) is None:
                raise CanonicalRemoteSummaryError(f"canonical remote summary {field} is invalid")
        expected_role = {
            "development_cv": "development",
            "public_reproducibility": "public_reproducibility",
        }.get(payload["evaluation_kind"])
        if expected_role is None:
            raise CanonicalRemoteSummaryError("canonical remote summary evaluation kind is invalid")
        if payload["dataset_role"] != expected_role:
            raise CanonicalRemoteSummaryError(
                "canonical remote summary evaluation kind and dataset role are inconsistent"
            )
        _validate_shape(payload["dataset_shape"])
        _bounded_int(payload["fold_count"], "fold_count", 2, 20)
        _validate_nodes(payload["nodes"])
        _validate_metrics(payload["metrics"])
        _validate_application_refit(payload["application_refit"])
        normalized = deepcopy(dict(payload))
        return cls(normalized, _digest(normalized))

    def require_matches(self, capsule: CanonicalWorkflowCapsule) -> None:
        expected = self.from_capsule(capsule)
        if self.summary_digest != expected.summary_digest:
            raise CanonicalRemoteSummaryError("canonical remote summary differs from its verified capsule")

    def as_dict(self) -> dict[str, Any]:
        return {**deepcopy(self.payload), "summary_digest": self.summary_digest}

    def canonical_bytes(self) -> bytes:
        return _canonical_json(self.as_dict())


def _validate_shape(value: Any) -> None:
    if not isinstance(value, Mapping):
        raise CanonicalRemoteSummaryError("dataset_shape must be an object")
    _require_closed(value, {"n_samples", "n_features", "grouped"}, "dataset_shape")
    _bounded_int(value["n_samples"], "n_samples", 2, 100_000)
    _bounded_int(value["n_features"], "n_features", 1, 20_000)
    if not isinstance(value["grouped"], bool):
        raise CanonicalRemoteSummaryError("dataset_shape.grouped must be boolean")


def _validate_nodes(value: Any) -> None:
    if not isinstance(value, list) or not value or len(value) > 32:
        raise CanonicalRemoteSummaryError("canonical remote summary nodes are outside the allowed bound")
    seen: set[str] = set()
    for node in value:
        if not isinstance(node, Mapping):
            raise CanonicalRemoteSummaryError("canonical remote summary node must be an object")
        _require_closed(node, _NODE_FIELDS, "canonical remote summary node")
        for field in ("node_id", "operation_id", "implementation_id", "implementation_version"):
            if not isinstance(node[field], str) or _IDENTIFIER.fullmatch(node[field]) is None:
                raise CanonicalRemoteSummaryError(f"canonical remote summary node {field} is invalid")
        if node["node_id"] in seen:
            raise CanonicalRemoteSummaryError("canonical remote summary repeats a node")
        seen.add(node["node_id"])
        for field in ("contract_digest", "parameter_digest"):
            _require_digest(node[field], f"node.{field}")
        if node["runtime_family"] not in {"sherpa_native", "spectrochempy"}:
            raise CanonicalRemoteSummaryError("canonical remote summary node runtime family is unsupported")
        if not isinstance(node["deterministic"], bool) or not isinstance(node["fitted_state_recorded"], bool):
            raise CanonicalRemoteSummaryError("canonical remote summary node flags must be boolean")


def _validate_metrics(value: Any) -> None:
    if not isinstance(value, Mapping):
        raise CanonicalRemoteSummaryError("metrics must be an object")
    _require_closed(value, _METRIC_FIELDS, "metrics")
    if value["registry_version"] != REGRESSION_METRIC_REGISTRY_VERSION:
        raise CanonicalRemoteSummaryError("metrics registry is unsupported")
    _bounded_int(value["n_samples"], "metrics.n_samples", 1, 100_000)
    for field in ("rmse", "mae", "bias"):
        number = value[field]
        if isinstance(number, bool) or not isinstance(number, (int, float)) or not math.isfinite(number):
            raise CanonicalRemoteSummaryError(f"metrics.{field} must be finite")
    if value["rmse"] < 0 or value["mae"] < 0:
        raise CanonicalRemoteSummaryError("remote summary error metrics cannot be negative")
    tolerance = 1e-12
    if value["mae"] > value["rmse"] + tolerance:
        raise CanonicalRemoteSummaryError("metrics.mae cannot exceed metrics.rmse")
    if abs(value["bias"]) > value["rmse"] + tolerance:
        raise CanonicalRemoteSummaryError("absolute metrics.bias cannot exceed metrics.rmse")
    r2 = value["r2"]
    if r2 is not None and (isinstance(r2, bool) or not isinstance(r2, (int, float)) or not math.isfinite(r2) or r2 > 1):
        raise CanonicalRemoteSummaryError("metrics.r2 is invalid")
    try:
        validate_supervised_metric_record(value)
    except ValueError as exc:
        raise CanonicalRemoteSummaryError("metrics use an invalid regression contract") from exc


def _validate_application_refit(value: Any) -> None:
    """Validate the no-metrics remote projection of application-fit status."""

    refit = _mapping(value, "application_refit")
    status = refit.get("status")
    if status == "not_materialized":
        _require_closed(refit, _REFIT_ABSENT_FIELDS, "application_refit")
        return
    if status != "materialized":
        raise CanonicalRemoteSummaryError("application_refit status is unsupported")
    _require_closed(refit, _REFIT_MATERIALIZED_FIELDS, "application_refit")
    for field in ("full_refit_evidence_digest", "full_refit_execution_digest"):
        _require_digest(refit[field], f"application_refit.{field}")
    if not isinstance(refit["model_node_id"], str) or _IDENTIFIER.fullmatch(refit["model_node_id"]) is None:
        raise CanonicalRemoteSummaryError("application_refit model_node_id is invalid")
    node_ids = refit["fitted_state_node_ids"]
    if not isinstance(node_ids, list) or not node_ids or len(node_ids) != len(set(node_ids)):
        raise CanonicalRemoteSummaryError("application_refit fitted_state_node_ids are invalid")
    if any(not isinstance(node_id, str) or _IDENTIFIER.fullmatch(node_id) is None for node_id in node_ids):
        raise CanonicalRemoteSummaryError("application_refit fitted_state_node_ids are invalid")
    if refit["model_node_id"] not in node_ids:
        raise CanonicalRemoteSummaryError("application_refit does not name its model state")


def _mapping(value: Any, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise CanonicalRemoteSummaryError(f"{name} must be an object")
    return value


def _require_closed(value: Mapping[str, Any], fields: set[str] | frozenset[str], name: str) -> None:
    missing, extra = sorted(set(fields) - set(value)), sorted(set(value) - set(fields))
    if missing or extra:
        raise CanonicalRemoteSummaryError(f"{name} fields are closed: missing={missing}, extra={extra}")


def _require_digest(value: Any, name: str) -> None:
    if not isinstance(value, str) or _DIGEST.fullmatch(value) is None:
        raise CanonicalRemoteSummaryError(f"{name} must be lowercase SHA-256")


def _bounded_int(value: Any, name: str, lower: int, upper: int) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or not lower <= value <= upper:
        raise CanonicalRemoteSummaryError(f"{name} must be an integer from {lower} through {upper}")


def _reject_duplicate_fields(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise CanonicalRemoteSummaryError(f"canonical remote summary repeats field {key!r}")
        result[key] = value
    return result


def _canonical_json(value: Mapping[str, Any]) -> bytes:
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()
    except (TypeError, ValueError) as exc:
        raise CanonicalRemoteSummaryError("canonical remote summary must contain finite JSON") from exc


def _digest(value: Mapping[str, Any]) -> str:
    return hashlib.sha256(_canonical_json(value)).hexdigest()


__all__ = [
    "CANONICAL_REMOTE_SUMMARY_VERSION",
    "MAX_CANONICAL_REMOTE_SUMMARY_BYTES",
    "CanonicalRemoteSummary",
    "CanonicalRemoteSummaryError",
]
