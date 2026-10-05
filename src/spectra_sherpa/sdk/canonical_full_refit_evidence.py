"""Portable, sample-free identity evidence for one selected full-data refit.

Validation and a subsequent all-data fit answer different scientific
questions.  This module makes that separation machine-checkable: it records
the selected validation digest and the state *references* produced by the
all-data fit, but contains no validation metrics, predictions, samples, or
fitted-state bytes.  It is therefore suitable for an OSS user to inspect the
provenance of an application artifact without allowing a refit to be reported
as a new measurement of model performance.
"""

from __future__ import annotations

import hashlib
import json
import re
from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Mapping

CANONICAL_FULL_REFIT_EVIDENCE_VERSION = "spectra-canonical-full-refit-evidence/1"
FULL_REFIT_EXECUTION_VERSION = "spectra-full-data-refit/1"
MAX_CANONICAL_FULL_REFIT_EVIDENCE_BYTES = 64 * 1024

_DIGEST = re.compile(r"^[0-9a-f]{64}$")
_NODE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_EVIDENCE_FIELDS = frozenset({"schema_version", "full_refit_execution", "full_refit_execution_digest"})
_REFIT_FIELDS = frozenset(
    {
        "schema_version",
        "validation_execution_digest",
        "graph_digest",
        "capability_content_digest",
        "capability_envelope_digest",
        "model_node_id",
        "node_ids",
        "fitted_state_references",
    }
)
_STATE_REFERENCE_FIELDS = frozenset(
    {"node_id", "state_digest", "serializer", "contract_digest", "candidate_node_digest", "seed"}
)


class CanonicalFullRefitEvidenceError(ValueError):
    """Raised when full-data refit evidence is malformed or not executor-issued."""


@dataclass(frozen=True)
class CanonicalFullRefitEvidence:
    """Verified public identity of a selected all-data application refit."""

    payload: dict[str, Any]
    content_digest: str
    validation_execution_digest: str
    full_refit_execution_digest: str

    @classmethod
    def from_full_refit_execution(cls, execution: Any) -> "CanonicalFullRefitEvidence":
        """Wrap an executor-issued refit without serializing fitted-state bytes."""

        try:
            from spectra_sherpa.app.services.dag.fold_graph_executor import (
                FoldGraphExecutionError,
                _serialize_executor_issued_full_refit,
            )
        except ImportError as exc:
            raise CanonicalFullRefitEvidenceError("full-data refit is not serializable") from exc
        try:
            refit, digest = _serialize_executor_issued_full_refit(execution)
        except (FoldGraphExecutionError, TypeError) as exc:
            raise CanonicalFullRefitEvidenceError("full-data refit is not serializable") from exc
        return cls._validated(
            {
                "schema_version": CANONICAL_FULL_REFIT_EVIDENCE_VERSION,
                "full_refit_execution": refit,
                "full_refit_execution_digest": digest,
            }
        )

    @classmethod
    def from_dict(cls, manifest: Mapping[str, Any]) -> "CanonicalFullRefitEvidence":
        """Validate detached evidence and its canonical content digest."""

        if not isinstance(manifest, Mapping):
            raise CanonicalFullRefitEvidenceError("canonical full-refit evidence must be an object")
        expected = manifest.get("content_digest")
        _require_digest(expected, "content_digest")
        payload = {key: deepcopy(value) for key, value in manifest.items() if key != "content_digest"}
        evidence = cls._validated(payload)
        if evidence.content_digest != expected:
            raise CanonicalFullRefitEvidenceError("canonical full-refit evidence content digest mismatch")
        return evidence

    @classmethod
    def from_bytes(cls, value: bytes) -> "CanonicalFullRefitEvidence":
        """Load canonical JSON only, with duplicate-field rejection."""

        if not 1 <= len(value) <= MAX_CANONICAL_FULL_REFIT_EVIDENCE_BYTES:
            raise CanonicalFullRefitEvidenceError("canonical full-refit evidence size is outside the allowed bound")
        try:
            manifest = json.loads(value, object_pairs_hook=_reject_duplicate_fields)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise CanonicalFullRefitEvidenceError("canonical full-refit evidence must be UTF-8 JSON") from exc
        evidence = cls.from_dict(manifest)
        if evidence.canonical_bytes() != value:
            raise CanonicalFullRefitEvidenceError("canonical full-refit evidence must use canonical JSON")
        return evidence

    @classmethod
    def _validated(cls, payload: Mapping[str, Any]) -> "CanonicalFullRefitEvidence":
        _require_closed_mapping(payload, _EVIDENCE_FIELDS, "canonical full-refit evidence")
        if payload["schema_version"] != CANONICAL_FULL_REFIT_EVIDENCE_VERSION:
            raise CanonicalFullRefitEvidenceError("canonical full-refit evidence schema is unsupported")
        refit = _mapping(payload["full_refit_execution"], "full_refit_execution")
        validation_digest = _validate_full_refit_execution(refit)
        actual_refit_digest = _digest(refit)
        if payload["full_refit_execution_digest"] != actual_refit_digest:
            raise CanonicalFullRefitEvidenceError("full-data refit evidence does not reproduce refit digest")
        normalized = deepcopy(dict(payload))
        return cls(
            payload=normalized,
            content_digest=_digest(normalized),
            validation_execution_digest=validation_digest,
            full_refit_execution_digest=actual_refit_digest,
        )

    def as_dict(self) -> dict[str, Any]:
        """Return the closed wire form named by :attr:`content_digest`."""

        return {**deepcopy(self.payload), "content_digest": self.content_digest}

    def canonical_bytes(self) -> bytes:
        """Return exact canonical bytes for detached OSS verification."""

        return _canonical_json(self.as_dict())


def _validate_full_refit_execution(value: Mapping[str, Any]) -> str:
    _require_closed_mapping(value, _REFIT_FIELDS, "full_refit_execution")
    if value["schema_version"] != FULL_REFIT_EXECUTION_VERSION:
        raise CanonicalFullRefitEvidenceError("full-data refit execution schema is unsupported")
    for field in (
        "validation_execution_digest",
        "graph_digest",
        "capability_content_digest",
        "capability_envelope_digest",
    ):
        _require_digest(value[field], f"full_refit_execution.{field}")
    model_node_id = value["model_node_id"]
    if not isinstance(model_node_id, str) or _NODE_ID.fullmatch(model_node_id) is None:
        raise CanonicalFullRefitEvidenceError("full-data refit model_node_id is invalid")
    node_ids = value["node_ids"]
    if not isinstance(node_ids, list) or not node_ids or len(node_ids) != len(set(node_ids)):
        raise CanonicalFullRefitEvidenceError("full-data refit node_ids are invalid")
    if any(not isinstance(node_id, str) or _NODE_ID.fullmatch(node_id) is None for node_id in node_ids):
        raise CanonicalFullRefitEvidenceError("full-data refit node_ids are invalid")
    if model_node_id not in node_ids:
        raise CanonicalFullRefitEvidenceError("full-data refit does not include its model node")

    references = value["fitted_state_references"]
    if not isinstance(references, list) or not references:
        raise CanonicalFullRefitEvidenceError("full-data refit requires fitted-state references")
    reference_nodes: list[str] = []
    for index, item_value in enumerate(references):
        item = _mapping(item_value, f"fitted_state_references[{index}]")
        _require_closed_mapping(item, _STATE_REFERENCE_FIELDS, "full-data fitted-state reference")
        node_id = item["node_id"]
        if not isinstance(node_id, str) or _NODE_ID.fullmatch(node_id) is None or node_id not in node_ids:
            raise CanonicalFullRefitEvidenceError("full-data fitted-state reference node_id is invalid")
        if node_id in reference_nodes:
            raise CanonicalFullRefitEvidenceError("full-data refit has duplicate fitted-state references")
        reference_nodes.append(node_id)
        for field in ("state_digest", "contract_digest", "candidate_node_digest"):
            _require_digest(item[field], f"full-data fitted-state reference {field}")
        serializer = item["serializer"]
        if not isinstance(serializer, str) or not serializer or len(serializer) > 256:
            raise CanonicalFullRefitEvidenceError("full-data fitted-state serializer is invalid")
        seed = item["seed"]
        if seed is not None and (isinstance(seed, bool) or not isinstance(seed, int)):
            raise CanonicalFullRefitEvidenceError("full-data fitted-state seed is invalid")
    if model_node_id not in reference_nodes:
        raise CanonicalFullRefitEvidenceError("full-data refit has no fitted state for its model node")
    return value["validation_execution_digest"]


def _digest(value: Mapping[str, Any]) -> str:
    return hashlib.sha256(_canonical_json(value)).hexdigest()


def _canonical_json(value: Mapping[str, Any]) -> bytes:
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False).encode(
            "utf-8"
        )
    except (TypeError, ValueError) as exc:
        raise CanonicalFullRefitEvidenceError("canonical full-refit evidence must be finite JSON") from exc


def _mapping(value: Any, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise CanonicalFullRefitEvidenceError(f"{name} must be an object")
    return value


def _require_closed_mapping(value: Mapping[str, Any], fields: frozenset[str], name: str) -> None:
    missing, extra = sorted(fields - set(value)), sorted(set(value) - fields)
    if missing or extra:
        raise CanonicalFullRefitEvidenceError(f"{name} fields are closed: missing={missing}, extra={extra}")


def _require_digest(value: Any, name: str) -> None:
    if not isinstance(value, str) or _DIGEST.fullmatch(value) is None:
        raise CanonicalFullRefitEvidenceError(f"{name} must be lowercase SHA-256")


def _reject_duplicate_fields(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise CanonicalFullRefitEvidenceError("canonical full-refit evidence contains duplicate JSON fields")
        result[key] = value
    return result


__all__ = [
    "CANONICAL_FULL_REFIT_EVIDENCE_VERSION",
    "CanonicalFullRefitEvidence",
    "CanonicalFullRefitEvidenceError",
]
