"""Portable, sample-free evidence for one canonical typed-DAG validation.

The M4 Runner executes a graph in an isolated process.  This module defines
the first OSS-owned record that can leave that child: it contains the exact
fold identities and scalar metrics needed to recompute the executor's legacy
validation digest, but never spectra, targets, predictions, paths, fitted
state bytes, or executable code.  It is intentionally narrower than the
future campaign archive and is independently loadable without the server.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Mapping

from spectra_sherpa.app.services.dag.managed_optimization_profile import (
    MANAGED_OPTIMIZATION_RUNTIME_ATTESTATION_VERSION,
    ManagedOptimizationProfileError,
    ManagedOptimizationRuntimeAttestation,
    ManagedOptimizationRuntimeRequirement,
    managed_optimization_profile,
)
from spectra_sherpa.app.services.dag.node_base import node_registry
from spectra_sherpa.execution_contract_vocabulary import ContractError, NodeExecutionContract

from .validate import (
    METRIC_PARITY_ABSOLUTE_TOLERANCE,
    METRIC_PARITY_RELATIVE_TOLERANCE,
    pool_supervised_metric_records,
    supervised_metric_task,
    validate_supervised_metric_record,
)

CANONICAL_EXECUTION_EVIDENCE_VERSION = "spectra-canonical-execution-evidence/4"
VALIDATION_EXECUTION_VERSION = "spectra-candidate-validation/3"
MAX_CANONICAL_EXECUTION_EVIDENCE_BYTES = 128 * 1024
_DIGEST = re.compile(r"^[0-9a-f]{64}$")
_NODE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_EVIDENCE_FIELDS = frozenset(
    {
        "schema_version",
        "validation_execution",
        "validation_execution_digest",
        "node_execution_traces",
        "runtime_attestation",
    }
)
_VALIDATION_FIELDS = frozenset(
    {
        "schema_version",
        "graph_digest",
        "capability_content_digest",
        "capability_envelope_digest",
        "split_plan_digest",
        "task_type",
        "model_operation_id",
        "metrics",
        "folds",
    }
)
_FOLD_FIELDS = frozenset(
    {
        "partition_digest",
        "metrics",
        "model_node_id",
        "evaluator_node_id",
        "node_ids",
        "prediction_application_digest",
    }
)
_TRACE_FOLD_FIELDS = frozenset({"partition_digest", "nodes"})
_TRACE_NODE_FIELDS = frozenset(
    {
        "node_id",
        "operation_id",
        "contract",
        "contract_digest",
        "parameters",
        "parameter_digest",
        "role_envelopes",
        "partition_digest",
        "seed",
        "feature_identity_digest",
        "fitted_state_digest",
        "fitted_state_serializer",
    }
)
_ROLE_ENVELOPE_FIELDS = frozenset({"role", "input_shape", "output_shape"})


class CanonicalExecutionEvidenceError(ValueError):
    """Raised when canonical execution evidence is malformed or unbound."""


@dataclass(frozen=True)
class CanonicalExecutionEvidence:
    """Verified bounded evidence that reproduces one validation digest."""

    payload: dict[str, Any]
    content_digest: str
    validation_execution_digest: str

    @classmethod
    def from_validation_execution(
        cls,
        execution: Any,
        *,
        runtime_attestation: Mapping[str, Any] | None = None,
    ) -> "CanonicalExecutionEvidence":
        """Wrap the executor's sole digest projection without reinterpreting it."""

        try:
            from spectra_sherpa.app.services.dag.fold_graph_executor import (
                FoldGraphExecutionError,
                _serialize_executor_issued_validation,
            )
        except ImportError as exc:
            raise CanonicalExecutionEvidenceError("canonical validation execution is not serializable") from exc
        try:
            validation, digest = _serialize_executor_issued_validation(execution)
        except (FoldGraphExecutionError, TypeError) as exc:
            raise CanonicalExecutionEvidenceError("canonical validation execution is not serializable") from exc
        if runtime_attestation is None:
            raise CanonicalExecutionEvidenceError("canonical validation execution has no runtime attestation")
        folds = getattr(execution, "folds", None)
        if not isinstance(folds, tuple):
            raise CanonicalExecutionEvidenceError("canonical validation execution has no immutable fold records")
        traces = []
        for fold in folds:
            partition_digest = getattr(fold, "partition_digest", None)
            node_traces = getattr(fold, "node_execution_traces", None)
            if not isinstance(partition_digest, str) or not isinstance(node_traces, tuple):
                raise CanonicalExecutionEvidenceError("canonical validation execution has no node execution trace")
            serializers = [getattr(trace, "as_dict", None) for trace in node_traces]
            if not all(callable(serializer) for serializer in serializers):
                raise CanonicalExecutionEvidenceError("canonical node execution trace is not serializable")
            traces.append(
                {
                    "partition_digest": partition_digest,
                    "nodes": [serializer() for serializer in serializers],
                }
            )
        return cls._validated(
            {
                "schema_version": CANONICAL_EXECUTION_EVIDENCE_VERSION,
                "validation_execution": validation,
                "validation_execution_digest": digest,
                "node_execution_traces": traces,
                "runtime_attestation": dict(runtime_attestation),
            }
        )

    @classmethod
    def from_dict(cls, manifest: Mapping[str, Any]) -> "CanonicalExecutionEvidence":
        """Validate a detached canonical evidence manifest and content digest."""

        if not isinstance(manifest, Mapping):
            raise CanonicalExecutionEvidenceError("canonical execution evidence must be an object")
        expected = manifest.get("content_digest")
        _require_digest(expected, "content_digest")
        payload = {key: deepcopy(value) for key, value in manifest.items() if key != "content_digest"}
        evidence = cls._validated(payload)
        if evidence.content_digest != expected:
            raise CanonicalExecutionEvidenceError("canonical execution evidence content digest mismatch")
        return evidence

    @classmethod
    def from_bytes(cls, value: bytes) -> "CanonicalExecutionEvidence":
        """Load only canonical, bounded JSON with no duplicate keys."""

        if not 1 <= len(value) <= MAX_CANONICAL_EXECUTION_EVIDENCE_BYTES:
            raise CanonicalExecutionEvidenceError("canonical execution evidence size is outside the allowed bound")
        try:
            manifest = json.loads(value, object_pairs_hook=_reject_duplicate_fields)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise CanonicalExecutionEvidenceError("canonical execution evidence must be UTF-8 JSON") from exc
        evidence = cls.from_dict(manifest)
        if evidence.canonical_bytes() != value:
            raise CanonicalExecutionEvidenceError("canonical execution evidence must use canonical JSON")
        return evidence

    @classmethod
    def _validated(cls, payload: Mapping[str, Any]) -> "CanonicalExecutionEvidence":
        if payload.get("schema_version") != CANONICAL_EXECUTION_EVIDENCE_VERSION:
            raise CanonicalExecutionEvidenceError("canonical execution evidence schema is unsupported")
        _require_closed_mapping(payload, _EVIDENCE_FIELDS, "canonical execution evidence")
        validation, actual_validation_digest = validate_canonical_validation_execution(payload["validation_execution"])
        if payload["validation_execution_digest"] != actual_validation_digest:
            raise CanonicalExecutionEvidenceError("canonical execution evidence does not reproduce validation digest")
        _validate_node_execution_traces(payload["node_execution_traces"], validation)
        _validate_runtime_attestation(payload["runtime_attestation"], payload["node_execution_traces"])
        canonical_payload = deepcopy(dict(payload))
        return cls(
            payload=canonical_payload,
            content_digest=_digest(canonical_payload),
            validation_execution_digest=actual_validation_digest,
        )

    def as_dict(self) -> dict[str, Any]:
        """Return the closed wire form named by :attr:`content_digest`."""

        return {**deepcopy(self.payload), "content_digest": self.content_digest}

    def canonical_bytes(self) -> bytes:
        """Return exact canonical bytes for portable verification."""

        return _canonical_json(self.as_dict())


def validate_canonical_validation_execution(value: Any) -> tuple[dict[str, Any], str]:
    """Re-admit one sample-free fold projection and reproduce its digest.

    Campaign evidence needs the exact pooled and per-fold validation facts but
    deliberately does not duplicate node traces or runtime attestations for
    every candidate.  This public boundary lets that narrower evidence reuse
    the canonical execution validator rather than growing a second metric and
    partition implementation.
    """

    validation = _mapping(value, "validation_execution")
    _validate_validation_execution(validation)
    normalized = deepcopy(dict(validation))
    return normalized, _validation_execution_digest(normalized)


def _validate_validation_execution(value: Mapping[str, Any]) -> None:
    _require_closed_mapping(value, _VALIDATION_FIELDS, "validation_execution")
    if value["schema_version"] != VALIDATION_EXECUTION_VERSION:
        raise CanonicalExecutionEvidenceError("validation execution schema is unsupported")
    for field in (
        "graph_digest",
        "capability_content_digest",
        "capability_envelope_digest",
        "split_plan_digest",
    ):
        _require_digest(value[field], f"validation_execution.{field}")
    if value["task_type"] not in {"classification", "regression"}:
        raise CanonicalExecutionEvidenceError("validation execution task type is invalid")
    _validate_metrics(value["metrics"], "validation_execution.metrics")
    try:
        metric_task = supervised_metric_task(_mapping(value["metrics"], "validation_execution.metrics"))
    except ValueError as exc:
        raise CanonicalExecutionEvidenceError("validation execution task type is invalid") from exc
    if metric_task != value["task_type"]:
        raise CanonicalExecutionEvidenceError("validation execution task type disagrees with its metrics")
    if not isinstance(value["model_operation_id"], str) or not _NODE_ID.fullmatch(value["model_operation_id"]):
        raise CanonicalExecutionEvidenceError("validation execution model operation is invalid")
    if value["model_operation_id"] == "classification.plsda" and value["task_type"] != "classification":
        raise CanonicalExecutionEvidenceError("PLS-DA validation must use classification metrics")
    folds = value["folds"]
    if not isinstance(folds, list) or not folds:
        raise CanonicalExecutionEvidenceError("validation execution requires one or more folds")
    seen_partitions: set[str] = set()
    fold_metrics: list[Mapping[str, Any]] = []
    expected_node_ids: list[str] | None = None
    expected_model_node_id: str | None = None
    expected_evaluator_node_id: str | None = None
    for index, fold_value in enumerate(folds):
        fold = _mapping(fold_value, f"validation_execution.folds[{index}]")
        _require_closed_mapping(fold, _FOLD_FIELDS, f"validation_execution.folds[{index}]")
        _require_digest(fold["partition_digest"], f"validation_execution.folds[{index}].partition_digest")
        application_digest = fold["prediction_application_digest"]
        if value["task_type"] == "classification" and value["model_operation_id"] == "classification.plsda":
            _require_digest(
                application_digest,
                f"validation_execution.folds[{index}].prediction_application_digest",
            )
        elif application_digest is not None:
            _require_digest(
                application_digest,
                f"validation_execution.folds[{index}].prediction_application_digest",
            )
        if fold["partition_digest"] in seen_partitions:
            raise CanonicalExecutionEvidenceError("validation execution has duplicate fold partitions")
        seen_partitions.add(fold["partition_digest"])
        metrics = _mapping(fold["metrics"], f"validation_execution.folds[{index}].metrics")
        _validate_metrics(metrics, f"validation_execution.folds[{index}].metrics")
        fold_metrics.append(metrics)
        for field in ("model_node_id", "evaluator_node_id"):
            if not isinstance(fold[field], str) or not _NODE_ID.fullmatch(fold[field]):
                raise CanonicalExecutionEvidenceError(f"validation execution fold {field} is invalid")
        node_ids = fold["node_ids"]
        if not isinstance(node_ids, list) or not node_ids or len(node_ids) != len(set(node_ids)):
            raise CanonicalExecutionEvidenceError("validation execution fold node_ids are invalid")
        if any(not isinstance(node_id, str) or not _NODE_ID.fullmatch(node_id) for node_id in node_ids):
            raise CanonicalExecutionEvidenceError("validation execution fold node_ids are invalid")
        if fold["model_node_id"] not in node_ids or fold["evaluator_node_id"] not in node_ids:
            raise CanonicalExecutionEvidenceError("validation execution fold does not name its terminal nodes")
        if expected_node_ids is None:
            expected_node_ids = node_ids
            expected_model_node_id = fold["model_node_id"]
            expected_evaluator_node_id = fold["evaluator_node_id"]
        elif (
            node_ids != expected_node_ids
            or fold["model_node_id"] != expected_model_node_id
            or fold["evaluator_node_id"] != expected_evaluator_node_id
        ):
            raise CanonicalExecutionEvidenceError("validation execution folds disagree on the executed graph")
    _validate_pooled_metrics(value["metrics"], fold_metrics)


def _validate_metrics(value: Any, name: str) -> None:
    try:
        validate_supervised_metric_record(_mapping(value, name))
    except ValueError as exc:
        raise CanonicalExecutionEvidenceError(f"{name} is invalid: {exc}") from exc


def _validate_pooled_metrics(pooled_value: Any, folds: list[Mapping[str, Any]]) -> None:
    """Prove the pooled sample and additive metrics agree with every fold."""

    pooled = _mapping(pooled_value, "validation_execution.metrics")
    total_samples = sum(int(fold["n_samples"]) for fold in folds)
    if pooled["n_samples"] != total_samples:
        raise CanonicalExecutionEvidenceError("validation execution fold sample counts do not match pooled metrics")
    try:
        task = supervised_metric_task(pooled)
        expected = pool_supervised_metric_records(folds)
    except ValueError as exc:
        raise CanonicalExecutionEvidenceError("validation execution fold metrics cannot be pooled") from exc
    if any(supervised_metric_task(fold) != task for fold in folds):
        raise CanonicalExecutionEvidenceError("validation execution folds mix supervised tasks")
    if task == "classification":
        if pooled != expected:
            raise CanonicalExecutionEvidenceError(
                "validation execution pooled classification metrics do not match its folds"
            )
        return
    for field in ("rmse", "mae", "bias"):
        expected_value = expected[field]
        if not math.isclose(
            pooled[field],
            expected_value,
            rel_tol=METRIC_PARITY_RELATIVE_TOLERANCE,
            abs_tol=METRIC_PARITY_ABSOLUTE_TOLERANCE,
        ):
            raise CanonicalExecutionEvidenceError(f"validation execution pooled {field} does not match its folds")


def _validate_node_execution_traces(value: Any, validation: Mapping[str, Any]) -> None:
    """Verify actual fold traces bind precisely to the legacy fold identity."""

    if not isinstance(value, list) or not value:
        raise CanonicalExecutionEvidenceError("node execution traces require one record per validation fold")
    validation_folds = validation["folds"]
    if not isinstance(validation_folds, list) or len(value) != len(validation_folds):
        raise CanonicalExecutionEvidenceError("node execution traces do not match validation fold count")
    expected_node_identities: list[tuple[Any, ...]] | None = None
    for index, (trace_value, validation_fold) in enumerate(zip(value, validation_folds, strict=True)):
        trace = _mapping(trace_value, f"node_execution_traces[{index}]")
        fold = _mapping(validation_fold, f"validation_execution.folds[{index}]")
        _require_closed_mapping(trace, _TRACE_FOLD_FIELDS, f"node_execution_traces[{index}]")
        if trace["partition_digest"] != fold["partition_digest"]:
            raise CanonicalExecutionEvidenceError("node execution trace fold differs from validation partition")
        nodes = trace["nodes"]
        if not isinstance(nodes, list) or not nodes:
            raise CanonicalExecutionEvidenceError("node execution trace fold requires nodes")
        expected_ids = fold["node_ids"]
        if [node.get("node_id") if isinstance(node, Mapping) else None for node in nodes] != expected_ids:
            raise CanonicalExecutionEvidenceError("node execution trace node order differs from validation graph")
        for node_index, node_value in enumerate(nodes):
            _validate_node_execution_trace(
                _mapping(node_value, f"node_execution_traces[{index}].nodes[{node_index}]"),
                partition_digest=fold["partition_digest"],
            )
        model_trace = next((node for node in nodes if node["node_id"] == fold["model_node_id"]), None)
        if model_trace is None or model_trace["operation_id"] != validation["model_operation_id"]:
            raise CanonicalExecutionEvidenceError("node execution trace disagrees with validation model operation")
        node_identities = [
            (
                node["node_id"],
                node["operation_id"],
                node["contract_digest"],
                node["parameter_digest"],
                node["seed"],
            )
            for node in nodes
        ]
        if expected_node_identities is None:
            expected_node_identities = node_identities
        elif node_identities != expected_node_identities:
            raise CanonicalExecutionEvidenceError("node execution traces disagree across validation folds")


def _validate_node_execution_trace(value: Mapping[str, Any], *, partition_digest: Any) -> None:
    _require_closed_mapping(value, _TRACE_NODE_FIELDS, "node execution trace")
    for field in ("node_id", "operation_id"):
        if not isinstance(value[field], str) or not _NODE_ID.fullmatch(value[field]):
            raise CanonicalExecutionEvidenceError(f"node execution trace {field} is invalid")
    for field in ("contract_digest", "parameter_digest"):
        _require_digest(value[field], f"node execution trace {field}")
    if value["feature_identity_digest"] is not None:
        _require_digest(value["feature_identity_digest"], "node execution trace feature_identity_digest")
    if value["partition_digest"] != partition_digest:
        raise CanonicalExecutionEvidenceError("node execution trace partition differs from its fold")
    try:
        contract = NodeExecutionContract.from_dict(_mapping(value["contract"], "node execution trace contract"))
    except ContractError as exc:
        raise CanonicalExecutionEvidenceError("node execution trace contract is invalid") from exc
    if contract.digest != value["contract_digest"] or contract.payload["operation_id"] != value["operation_id"]:
        raise CanonicalExecutionEvidenceError("node execution trace contract identity differs from node identity")
    parameters = _mapping(value["parameters"], "node execution trace parameters")
    _validate_first_profile_parameters(parameters, operation_id=value["operation_id"])
    if _parameter_digest(parameters) != value["parameter_digest"]:
        raise CanonicalExecutionEvidenceError("node execution trace parameter digest mismatch")
    role_envelopes = value["role_envelopes"]
    if not isinstance(role_envelopes, list) or not role_envelopes:
        raise CanonicalExecutionEvidenceError("node execution trace requires bounded role envelopes")
    expected_roles = (
        ["train", "test"]
        if contract.payload["lifecycle_kind"] in {"stateless_transform", "fitted_transform"}
        else ["test"]
    )
    observed_roles = [envelope.get("role") if isinstance(envelope, Mapping) else None for envelope in role_envelopes]
    if observed_roles != expected_roles:
        raise CanonicalExecutionEvidenceError("node execution trace roles differ from lifecycle")
    for envelope in role_envelopes:
        item = _mapping(envelope, "node execution trace role envelope")
        _require_closed_mapping(item, _ROLE_ENVELOPE_FIELDS, "node execution trace role envelope")
        for field in ("input_shape", "output_shape"):
            shape = item[field]
            if (
                not isinstance(shape, list)
                or len(shape) > 4
                or any(isinstance(size, bool) or not isinstance(size, int) or size < 0 for size in shape)
            ):
                raise CanonicalExecutionEvidenceError(f"node execution trace {field} is invalid")
    seed = value["seed"]
    if seed is not None and (isinstance(seed, bool) or not isinstance(seed, int)):
        raise CanonicalExecutionEvidenceError("node execution trace seed is invalid")
    fitted_digest = value["fitted_state_digest"]
    serializer = value["fitted_state_serializer"]
    if fitted_digest is None:
        if serializer is not None:
            raise CanonicalExecutionEvidenceError("stateless node execution trace names a state serializer")
    else:
        _require_digest(fitted_digest, "node execution trace fitted_state_digest")
        if not isinstance(serializer, str) or serializer != contract.payload["fitted_state_serializer"]:
            raise CanonicalExecutionEvidenceError("fitted node execution trace serializer mismatch")


def _validate_first_profile_parameters(parameters: Mapping[str, Any], *, operation_id: str) -> None:
    """Require the exact projection used at managed graph admission."""

    try:
        metadata = node_registry.get_metadata(operation_id)
        if metadata.canonicalize_parameters(parameters) != dict(parameters):
            raise CanonicalExecutionEvidenceError(
                "node execution trace parameters are not the canonical first-profile projection"
            )
    except (KeyError, ValueError) as exc:
        raise CanonicalExecutionEvidenceError(f"node execution trace parameters are invalid: {exc}") from exc


def _validate_runtime_attestation(value: Any, traces: Any) -> None:
    # Build from the live, fully registered node census.  This module can be
    # imported by API route setup before every node package has registered;
    # freezing the profile at module import made its identity depend on import
    # order.
    managed_profile = managed_optimization_profile()
    runtime = _mapping(value, "runtime_attestation")
    expected_fields = {
        "schema_version",
        "profile_id",
        "profile_version",
        "profile_digest",
        "operation_ids",
        "distributions",
        "digest",
    }
    _require_closed_mapping(runtime, frozenset(expected_fields), "runtime_attestation")
    if runtime["schema_version"] != MANAGED_OPTIMIZATION_RUNTIME_ATTESTATION_VERSION:
        raise CanonicalExecutionEvidenceError("runtime attestation schema is unsupported")
    for field in ("profile_id", "profile_version"):
        if not isinstance(runtime[field], str) or not runtime[field]:
            raise CanonicalExecutionEvidenceError(f"runtime attestation {field} is invalid")
    _require_digest(runtime["profile_digest"], "runtime attestation profile_digest")
    if (
        runtime["profile_id"] != managed_profile.profile_id
        or runtime["profile_version"] != managed_profile.profile_version
        or runtime["profile_digest"] != managed_profile.digest
    ):
        raise CanonicalExecutionEvidenceError("runtime attestation does not name the live managed optimization profile")
    operation_ids = runtime["operation_ids"]
    distributions = runtime["distributions"]
    if not isinstance(operation_ids, list) or not operation_ids or not isinstance(distributions, list):
        raise CanonicalExecutionEvidenceError("runtime attestation lists are invalid")
    if operation_ids != sorted(set(operation_ids)) or any(
        not isinstance(operation, str) or not _NODE_ID.fullmatch(operation) for operation in operation_ids
    ):
        raise CanonicalExecutionEvidenceError("runtime attestation operations are invalid")
    traced_operations = sorted({node["operation_id"] for fold in traces for node in fold["nodes"]})
    if operation_ids != traced_operations:
        raise CanonicalExecutionEvidenceError("runtime attestation operations differ from executed node traces")
    requirements: list[ManagedOptimizationRuntimeRequirement] = []
    for item in distributions:
        distribution = _mapping(item, "runtime attestation distribution")
        _require_closed_mapping(
            distribution,
            frozenset({"distribution", "version"}),
            "runtime attestation distribution",
        )
        if not isinstance(distribution["distribution"], str) or not isinstance(distribution["version"], str):
            raise CanonicalExecutionEvidenceError("runtime attestation distribution is invalid")
        requirements.append(
            ManagedOptimizationRuntimeRequirement(distribution["distribution"], distribution["version"])
        )
    if [item.distribution for item in requirements] != sorted({item.distribution for item in requirements}):
        raise CanonicalExecutionEvidenceError("runtime attestation distributions are not canonical")
    expected_versions: dict[str, str] = {}
    try:
        for operation_id in operation_ids:
            for requirement in managed_profile.operation(operation_id).payload["runtime_requirements"]:
                expected_versions[str(requirement["distribution"])] = str(requirement["version"])
    except ManagedOptimizationProfileError as exc:
        raise CanonicalExecutionEvidenceError(
            "runtime attestation names an operation outside the approved profile"
        ) from exc
    if {item.distribution: item.version for item in requirements} != expected_versions:
        raise CanonicalExecutionEvidenceError("runtime attestation distributions differ from the approved profile")
    attestation = ManagedOptimizationRuntimeAttestation(
        profile_id=runtime["profile_id"],
        profile_version=runtime["profile_version"],
        profile_digest=runtime["profile_digest"],
        operation_ids=tuple(operation_ids),
        distributions=tuple(requirements),
    )
    if attestation.as_dict() != dict(runtime):
        raise CanonicalExecutionEvidenceError("runtime attestation digest mismatch")


def _parameter_digest(value: Mapping[str, Any]) -> str:
    try:
        encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise CanonicalExecutionEvidenceError("node execution trace parameters must be finite JSON") from exc
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _validation_execution_digest(value: Mapping[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False).encode("utf-8")
    ).hexdigest()


def _digest(value: Mapping[str, Any]) -> str:
    return hashlib.sha256(_canonical_json(value)).hexdigest()


def _canonical_json(value: Mapping[str, Any]) -> bytes:
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False).encode(
            "utf-8"
        )
    except (TypeError, ValueError) as exc:
        raise CanonicalExecutionEvidenceError("canonical execution evidence must be finite JSON") from exc


def _mapping(value: Any, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise CanonicalExecutionEvidenceError(f"{name} must be an object")
    return value


def _require_closed_mapping(value: Mapping[str, Any], fields: frozenset[str], name: str) -> None:
    missing, extra = sorted(fields - set(value)), sorted(set(value) - fields)
    if missing or extra:
        raise CanonicalExecutionEvidenceError(f"{name} fields are closed: missing={missing}, extra={extra}")


def _require_digest(value: Any, name: str) -> None:
    if not isinstance(value, str) or not _DIGEST.fullmatch(value):
        raise CanonicalExecutionEvidenceError(f"{name} must be lowercase SHA-256")


def _reject_duplicate_fields(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise CanonicalExecutionEvidenceError("canonical execution evidence contains duplicate JSON fields")
        result[key] = value
    return result


__all__ = [
    "CANONICAL_EXECUTION_EVIDENCE_VERSION",
    "CanonicalExecutionEvidence",
    "CanonicalExecutionEvidenceError",
    "validate_canonical_validation_execution",
]
