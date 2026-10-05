"""OSS-owned capsule for one governed canonical typed-DAG evaluation.

The capsule carries the exact admitted DAG request and the sample-free
execution evidence produced by that DAG. Loading it never imports the managed
server, opens a dataset, deserializes fitted state, or executes a node. Version
4 is the sole supported capsule contract; prototype and transitional capsule
formats fail closed rather than being translated.
"""

from __future__ import annotations

import hashlib
import json
import re
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from spectra_sherpa.app.services.dag.managed_optimization_profile import (
    ManagedOptimizationProfileError,
    managed_optimization_profile,
)
from spectra_sherpa.app.services.dag.validation_graph import (
    ValidationGraph,
    ValidationGraphError,
    validation_graph_from_dict,
)

from . import canonical_execution_evidence, canonical_full_refit_evidence
from .canonical_execution_evidence import (
    CANONICAL_EXECUTION_EVIDENCE_VERSION,
    CanonicalExecutionEvidence,
    CanonicalExecutionEvidenceError,
)
from .canonical_wire_versions import (
    CANONICAL_RUNNER_PROTOCOL_VERSION,
    CANONICAL_WORKFLOW_CAPSULE_VERSION,
)
from .validate import (
    CLASSIFICATION_METRIC_SET_REGISTRY_VERSION,
    METRIC_REGISTRY_VERSION,
    REGRESSION_METRIC_REGISTRY_VERSION,
)

MAX_CANONICAL_WORKFLOW_CAPSULE_BYTES = 512 * 1024
_MANAGED_OPTIMIZATION_PROFILE = managed_optimization_profile()

_DIGEST = re.compile(r"^[0-9a-f]{64}$")
_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{2,127}$")
_CAPSULE_FIELDS = frozenset({"schema_version", "admitted_request", "execution_evidence", "application_refit"})
_REQUEST_FIELDS = frozenset(
    {
        "protocol",
        "request_id",
        "campaign_id",
        "candidate_id",
        "profile",
        "graph",
        "evaluation_kind",
        "dataset_role",
        "capability_digest",
        "dataset_content_digest",
        "dataset_ref_digest",
        "dataset_shape",
        "split_digest",
        "validation",
        "search",
        "resources",
        "runtime_attestation",
        "execution_purpose",
        "winner_refit_authority_digest",
        "confirmation_authority",
        "request_digest",
    }
)
_EVALUATION_ROLES = {
    "development_cv": "development",
    "public_reproducibility": "public_reproducibility",
}
_REFIT_ABSENT_FIELDS = frozenset({"status"})
_REFIT_MATERIALIZED_FIELDS = frozenset({"status", "evidence"})


class CanonicalWorkflowCapsuleError(ValueError):
    """A canonical capsule is malformed or not bound to its admitted run."""


@dataclass(frozen=True)
class CanonicalWorkflowCapsule:
    """Verified data-only view of one admitted typed-DAG evaluation."""

    payload: dict[str, Any]
    capsule_digest: str
    graph: ValidationGraph
    execution_evidence: CanonicalExecutionEvidence
    full_refit_evidence: canonical_full_refit_evidence.CanonicalFullRefitEvidence | None

    @classmethod
    def from_admitted_request(
        cls,
        admitted_request: Mapping[str, Any],
        execution_evidence: Mapping[str, Any] | object,
        *,
        full_refit_evidence: Mapping[str, Any] | object | None = None,
    ) -> "CanonicalWorkflowCapsule":
        """Build a capsule from the managed boundary's already-admitted data."""

        if isinstance(execution_evidence, Mapping):
            evidence_payload = deepcopy(dict(execution_evidence))
        else:
            serializer = getattr(execution_evidence, "as_dict", None)
            if not callable(serializer):
                raise CanonicalWorkflowCapsuleError("canonical execution evidence is not serializable")
            # Re-admission below is the authority boundary. This accepts a
            # verified evidence object across importlib.reload() without
            # trusting a cached Python class identity.
            evidence_payload = deepcopy(serializer())
        refit_payload: dict[str, Any]
        if full_refit_evidence is None:
            refit_payload = {"status": "not_materialized"}
        elif isinstance(full_refit_evidence, Mapping):
            refit_payload = {"status": "materialized", "evidence": deepcopy(dict(full_refit_evidence))}
        else:
            serializer = getattr(full_refit_evidence, "as_dict", None)
            if not callable(serializer):
                raise CanonicalWorkflowCapsuleError("canonical full-refit evidence is not serializable")
            refit_payload = {"status": "materialized", "evidence": deepcopy(serializer())}
        return cls._validated(
            {
                "schema_version": CANONICAL_WORKFLOW_CAPSULE_VERSION,
                "admitted_request": deepcopy(dict(admitted_request)),
                "execution_evidence": evidence_payload,
                "application_refit": refit_payload,
            },
            require_live_runtime=True,
        )

    @classmethod
    def from_dict(cls, manifest: Mapping[str, Any]) -> "CanonicalWorkflowCapsule":
        if not isinstance(manifest, Mapping):
            raise CanonicalWorkflowCapsuleError("canonical workflow capsule must be an object")
        expected = manifest.get("capsule_digest")
        _require_digest(expected, "capsule_digest")
        payload = {key: deepcopy(value) for key, value in manifest.items() if key != "capsule_digest"}
        # A data-free imported package remains scientifically inspectable even
        # when an optional runtime (for example SpectroChemPy) is absent.  The
        # structural re-admission below remains closed and exact; live runtime
        # admission is required again at every execution authority.
        capsule = cls._validated(payload, require_live_runtime=False)
        if capsule.capsule_digest != expected:
            raise CanonicalWorkflowCapsuleError("canonical workflow capsule content digest mismatch")
        return capsule

    @classmethod
    def from_bytes(cls, value: bytes) -> "CanonicalWorkflowCapsule":
        if not 1 <= len(value) <= MAX_CANONICAL_WORKFLOW_CAPSULE_BYTES:
            raise CanonicalWorkflowCapsuleError("canonical workflow capsule size is outside the allowed bound")
        try:
            manifest = json.loads(value, object_pairs_hook=_reject_duplicate_fields)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise CanonicalWorkflowCapsuleError("canonical workflow capsule must be UTF-8 JSON") from exc
        capsule = cls.from_dict(manifest)
        if capsule.canonical_bytes() != value:
            raise CanonicalWorkflowCapsuleError("canonical workflow capsule must use canonical JSON")
        return capsule

    @classmethod
    def _validated(
        cls,
        payload: Mapping[str, Any],
        *,
        require_live_runtime: bool,
    ) -> "CanonicalWorkflowCapsule":
        version = payload.get("schema_version")
        if version != CANONICAL_WORKFLOW_CAPSULE_VERSION:
            raise CanonicalWorkflowCapsuleError("canonical workflow capsule schema is unsupported")
        _require_closed_mapping(payload, _CAPSULE_FIELDS, "canonical workflow capsule")
        request = _mapping(payload["admitted_request"], "admitted_request")
        graph = _validate_admitted_request(request, require_live_runtime=require_live_runtime)
        try:
            evidence = CanonicalExecutionEvidence.from_dict(
                _mapping(payload["execution_evidence"], "execution_evidence")
            )
        except CanonicalExecutionEvidenceError as exc:
            raise CanonicalWorkflowCapsuleError("canonical workflow capsule execution evidence is invalid") from exc
        if evidence.payload["schema_version"] != CANONICAL_EXECUTION_EVIDENCE_VERSION:
            raise CanonicalWorkflowCapsuleError("canonical workflow capsule requires traced v2 execution evidence")
        _bind_evidence(request, graph, evidence)
        full_refit_evidence = _validate_application_refit(payload["application_refit"], request, graph, evidence)
        normalized = deepcopy(dict(payload))
        return cls(normalized, _digest(normalized), graph, evidence, full_refit_evidence)

    def as_dict(self) -> dict[str, Any]:
        return {**deepcopy(self.payload), "capsule_digest": self.capsule_digest}

    def canonical_bytes(self) -> bytes:
        return _canonical_json(self.as_dict())


def load_canonical_capsule(
    source: Mapping[str, Any] | str | Path | bytes,
) -> CanonicalWorkflowCapsule:
    """Load the current canonical capsule from data or an explicit local path.

    Paths are caller-selected and size-checked before reading. URLs are never
    resolved, and the capsule cannot direct the loader to another location.
    """

    if isinstance(source, Mapping):
        return CanonicalWorkflowCapsule.from_dict(source)
    if isinstance(source, bytes):
        return CanonicalWorkflowCapsule.from_bytes(source)
    if isinstance(source, (str, Path)):
        if isinstance(source, str) and source.lower().startswith(("http://", "https://")):
            raise CanonicalWorkflowCapsuleError("canonical workflow capsule loading does not accept URLs")
        path = Path(source)
        try:
            size = path.stat().st_size
        except OSError as exc:
            raise CanonicalWorkflowCapsuleError("canonical workflow capsule file is unavailable") from exc
        if not 1 <= size <= MAX_CANONICAL_WORKFLOW_CAPSULE_BYTES:
            raise CanonicalWorkflowCapsuleError("canonical workflow capsule file size is outside the allowed bound")
        try:
            value = path.read_bytes()
        except OSError as exc:
            raise CanonicalWorkflowCapsuleError("canonical workflow capsule file is unavailable") from exc
        return CanonicalWorkflowCapsule.from_bytes(value)
    raise TypeError("canonical workflow capsule source must be a mapping, JSON bytes, or explicit local path")


def _validate_admitted_request(
    request: Mapping[str, Any],
    *,
    require_live_runtime: bool,
) -> ValidationGraph:
    _require_closed_mapping(request, _REQUEST_FIELDS, "admitted canonical request")
    if request["protocol"] != CANONICAL_RUNNER_PROTOCOL_VERSION:
        raise CanonicalWorkflowCapsuleError("admitted canonical request protocol is unsupported")
    if request["execution_purpose"] != "candidate_validation":
        raise CanonicalWorkflowCapsuleError("canonical capsule requires a candidate-validation request")
    if request["winner_refit_authority_digest"] is not None:
        raise CanonicalWorkflowCapsuleError("candidate-validation capsule cannot carry winner-refit authority")
    if request["confirmation_authority"] is not None:
        raise CanonicalWorkflowCapsuleError("candidate-validation capsule cannot carry confirmation authority")
    for field in ("request_id", "campaign_id", "candidate_id"):
        if not isinstance(request[field], str) or _IDENTIFIER.fullmatch(request[field]) is None:
            raise CanonicalWorkflowCapsuleError(f"admitted canonical request {field} is invalid")
    for field in (
        "capability_digest",
        "dataset_content_digest",
        "dataset_ref_digest",
        "split_digest",
        "request_digest",
    ):
        _require_digest(request[field], f"admitted_request.{field}")
    if _digest({key: value for key, value in request.items() if key != "request_digest"}) != request["request_digest"]:
        raise CanonicalWorkflowCapsuleError("admitted canonical request digest mismatch")

    profile = _mapping(request["profile"], "admitted_request.profile")
    _require_closed_mapping(
        profile, {"profile_id", "profile_version", "profile_digest"}, "managed optimization profile"
    )
    if profile != {
        "profile_id": _MANAGED_OPTIMIZATION_PROFILE.profile_id,
        "profile_version": _MANAGED_OPTIMIZATION_PROFILE.profile_version,
        "profile_digest": _MANAGED_OPTIMIZATION_PROFILE.digest,
    }:
        raise CanonicalWorkflowCapsuleError("admitted canonical request profile is not locally recognized")
    try:
        graph = validation_graph_from_dict(
            _mapping(request["graph"], "admitted_request.graph"),
            require_live_runtime=require_live_runtime,
        )
    except ValidationGraphError as exc:
        raise CanonicalWorkflowCapsuleError("admitted canonical request graph failed local re-admission") from exc
    expected_role = _EVALUATION_ROLES.get(request["evaluation_kind"])
    if expected_role is None or request["dataset_role"] != expected_role:
        raise CanonicalWorkflowCapsuleError("admitted canonical request evaluation role is invalid")
    _validate_dataset_shape(request["dataset_shape"])
    _validate_validation_plan(request["validation"])
    _validate_search_plan(
        request["search"],
        candidate_id=request["candidate_id"],
        graph_digest=graph.digest,
    )
    _validate_resource_envelope(request["resources"])
    _validate_runtime(request["runtime_attestation"], graph)
    return graph


def _bind_evidence(request: Mapping[str, Any], graph: ValidationGraph, evidence: CanonicalExecutionEvidence) -> None:
    validation = evidence.payload["validation_execution"]
    if (
        validation["graph_digest"] != graph.digest
        or validation["capability_content_digest"] != request["dataset_content_digest"]
        or validation["capability_envelope_digest"] != request["capability_digest"]
        or validation["split_plan_digest"] != request["split_digest"]
        or validation["metrics"]["n_samples"] != request["dataset_shape"]["n_samples"]
        or len(validation["folds"]) != request["validation"]["outer_splits"]
        or evidence.payload["runtime_attestation"] != request["runtime_attestation"]
    ):
        raise CanonicalWorkflowCapsuleError("canonical execution evidence differs from the admitted request")
    expected_nodes = tuple(graph.nodes)
    for fold_trace in evidence.payload["node_execution_traces"]:
        nodes = fold_trace["nodes"]
        if len(nodes) != len(expected_nodes):
            raise CanonicalWorkflowCapsuleError("canonical execution trace does not cover the admitted graph")
        for trace, expected in zip(nodes, expected_nodes, strict=True):
            if (
                trace["node_id"] != expected.node_id
                or trace["operation_id"] != expected.operation_id
                or trace["contract_digest"] != expected.contract.digest
                or trace["parameters"] != dict(expected.parameters)
            ):
                raise CanonicalWorkflowCapsuleError("canonical execution trace differs from the admitted graph")


def _validate_application_refit(
    value: Any,
    request: Mapping[str, Any],
    graph: ValidationGraph,
    evidence: canonical_execution_evidence.CanonicalExecutionEvidence,
) -> canonical_full_refit_evidence.CanonicalFullRefitEvidence | None:
    """Bind an application fit to this validation without treating it as scoring.

    A v4 capsule always states whether an all-data refit was materialized.
    The absence state is deliberate, not an omitted field; a materialized
    record must name the exact validation, graph, capability, model node, and
    fitted node contracts already present in this capsule.
    """

    refit = _mapping(value, "canonical application refit")
    status = refit.get("status")
    if status == "not_materialized":
        _require_closed_mapping(refit, _REFIT_ABSENT_FIELDS, "canonical application refit")
        return None
    if status != "materialized":
        raise CanonicalWorkflowCapsuleError("canonical application refit status is unsupported")
    _require_closed_mapping(refit, _REFIT_MATERIALIZED_FIELDS, "canonical application refit")
    try:
        detached = canonical_full_refit_evidence.CanonicalFullRefitEvidence.from_dict(
            _mapping(refit["evidence"], "canonical application refit evidence")
        )
    except canonical_full_refit_evidence.CanonicalFullRefitEvidenceError as exc:
        raise CanonicalWorkflowCapsuleError("canonical application refit evidence is invalid") from exc

    projection = detached.payload["full_refit_execution"]
    validation = evidence.payload["validation_execution"]
    if (
        detached.validation_execution_digest != evidence.validation_execution_digest
        or projection["graph_digest"] != graph.digest
        or projection["capability_content_digest"] != request["dataset_content_digest"]
        or projection["capability_envelope_digest"] != request["capability_digest"]
        or projection["model_node_id"] != validation["folds"][0]["model_node_id"]
    ):
        raise CanonicalWorkflowCapsuleError("canonical application refit differs from the selected validation")
    expected_node_ids = [node.node_id for node in graph.nodes[:-1]]
    if projection["node_ids"] != expected_node_ids:
        raise CanonicalWorkflowCapsuleError("canonical application refit nodes differ from the admitted graph")
    contracts = {node.node_id: node.contract.digest for node in graph.nodes[:-1]}
    for reference in projection["fitted_state_references"]:
        if contracts.get(reference["node_id"]) != reference["contract_digest"]:
            raise CanonicalWorkflowCapsuleError("canonical application refit state differs from the admitted contract")
    return detached


def _validate_dataset_shape(value: Any) -> None:
    shape = _mapping(value, "admitted_request.dataset_shape")
    _require_closed_mapping(shape, {"n_samples", "n_features", "grouped"}, "canonical dataset shape")
    _bounded_int(shape["n_samples"], "n_samples", 2, 100_000)
    _bounded_int(shape["n_features"], "n_features", 1, 20_000)
    if not isinstance(shape["grouped"], bool):
        raise CanonicalWorkflowCapsuleError("canonical dataset grouped flag must be boolean")


def _validate_validation_plan(value: Any) -> None:
    plan = _mapping(value, "admitted_request.validation")
    _require_closed_mapping(
        plan,
        {
            "schema_version",
            "task_type",
            "selection",
            "outer_splits",
            "shuffle",
            "metric_registry_version",
            "primary_metric",
        },
        "canonical validation plan",
    )
    task_type = plan["task_type"]
    schema_version = plan["schema_version"]
    if task_type == "regression":
        expected_selection = "group_kfold_when_groups_else_kfold"
        expected_metrics = {"rmse"}
        expected_registry = REGRESSION_METRIC_REGISTRY_VERSION
        supported_version = schema_version == "spectra-canonical-validation/3"
    elif task_type == "classification":
        expected_selection = "stratified_group_kfold_when_groups_else_stratified_kfold"
        expected_metrics = (
            {"balanced_accuracy", "mean_class_acceptance_sensitivity"}
            if schema_version == "spectra-canonical-validation/4"
            else {"balanced_accuracy"}
        )
        expected_registry = (
            CLASSIFICATION_METRIC_SET_REGISTRY_VERSION
            if schema_version == "spectra-canonical-validation/4"
            else METRIC_REGISTRY_VERSION
        )
        supported_version = schema_version in {
            "spectra-canonical-validation/3",
            "spectra-canonical-validation/4",
        }
    else:
        raise CanonicalWorkflowCapsuleError("canonical validation task is unsupported")
    if (
        not supported_version
        or plan["selection"] != expected_selection
        or plan["primary_metric"] not in expected_metrics
        or plan["shuffle"] is not False
        or plan["metric_registry_version"] != expected_registry
    ):
        raise CanonicalWorkflowCapsuleError("canonical validation plan is unsupported")
    _bounded_int(plan["outer_splits"], "outer_splits", 2, 20)


def _validate_search_plan(
    value: Any,
    *,
    candidate_id: str,
    graph_digest: str,
) -> None:
    plan = _mapping(value, "admitted_request.search")
    _require_closed_mapping(
        plan,
        {
            "schema_version",
            "strategy",
            "search_space_digest",
            "candidate_ordinal",
            "candidate_count",
            "candidate_id",
            "candidate_graph_digest",
        },
        "canonical search execution plan",
    )
    if (
        plan["schema_version"] != "spectra-canonical-search-execution/2"
        or plan["strategy"] != "finite_declared_parameter_grid"
        or plan["candidate_id"] != candidate_id
        or plan["candidate_graph_digest"] != graph_digest
    ):
        raise CanonicalWorkflowCapsuleError("canonical search execution plan is unsupported")
    _require_digest(plan["search_space_digest"], "admitted_request.search.search_space_digest")
    _require_digest(plan["candidate_graph_digest"], "admitted_request.search.candidate_graph_digest")
    _bounded_int(plan["candidate_count"], "candidate_count", 2, 64)
    _bounded_int(plan["candidate_ordinal"], "candidate_ordinal", 1, plan["candidate_count"])


def _validate_resource_envelope(value: Any) -> None:
    resources = _mapping(value, "admitted_request.resources")
    fields = {
        "schema_version",
        "timeout_seconds",
        "cpu_seconds",
        "memory_bytes",
        "temp_bytes",
        "max_file_bytes",
        "stdout_bytes",
        "stderr_bytes",
    }
    _require_closed_mapping(resources, fields, "canonical resource envelope")
    if resources["schema_version"] != "spectra-canonical-resources/1":
        raise CanonicalWorkflowCapsuleError("canonical resource envelope is unsupported")
    bounds = {
        "timeout_seconds": (1, 86_400),
        "cpu_seconds": (1, 86_400),
        "memory_bytes": (64 * 1024 * 1024, 64 * 1024**3),
        "temp_bytes": (0, 64 * 1024**3),
        "max_file_bytes": (1, 64 * 1024**3),
        "stdout_bytes": (1, 16 * 1024 * 1024),
        "stderr_bytes": (1, 16 * 1024 * 1024),
    }
    for field, (lower, upper) in bounds.items():
        _bounded_int(resources[field], field, lower, upper)


def _validate_runtime(value: Any, graph: ValidationGraph) -> None:
    runtime = _mapping(value, "admitted_request.runtime_attestation")
    distributions = runtime.get("distributions")
    if not isinstance(distributions, list):
        raise CanonicalWorkflowCapsuleError("canonical runtime distributions must be an array")
    versions: dict[str, str] = {}
    for item in distributions:
        requirement = _mapping(item, "runtime distribution")
        _require_closed_mapping(requirement, {"distribution", "version"}, "runtime distribution")
        if not all(isinstance(requirement[name], str) and requirement[name] for name in requirement):
            raise CanonicalWorkflowCapsuleError("canonical runtime distribution is invalid")
        if requirement["distribution"] in versions:
            raise CanonicalWorkflowCapsuleError("canonical runtime repeats a distribution")
        versions[requirement["distribution"]] = requirement["version"]
    try:
        expected = _MANAGED_OPTIMIZATION_PROFILE.runtime_attestation(
            tuple(node.operation_id for node in graph.nodes), version_resolver=versions.__getitem__
        ).as_dict()
    except (ManagedOptimizationProfileError, KeyError) as exc:
        raise CanonicalWorkflowCapsuleError("canonical runtime does not satisfy the admitted profile") from exc
    if runtime != expected:
        raise CanonicalWorkflowCapsuleError("canonical runtime differs from local profile authority")


def _mapping(value: Any, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise CanonicalWorkflowCapsuleError(f"{name} must be an object")
    return value


def _require_closed_mapping(value: Mapping[str, Any], fields: set[str] | frozenset[str], name: str) -> None:
    missing, extra = sorted(set(fields) - set(value)), sorted(set(value) - set(fields))
    if missing or extra:
        raise CanonicalWorkflowCapsuleError(f"{name} fields are closed: missing={missing}, extra={extra}")


def _require_digest(value: Any, name: str) -> None:
    if not isinstance(value, str) or _DIGEST.fullmatch(value) is None:
        raise CanonicalWorkflowCapsuleError(f"{name} must be lowercase SHA-256")


def _bounded_int(value: Any, name: str, lower: int, upper: int) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or not lower <= value <= upper:
        raise CanonicalWorkflowCapsuleError(f"{name} must be an integer from {lower} through {upper}")


def _reject_duplicate_fields(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise CanonicalWorkflowCapsuleError(f"canonical workflow capsule repeats field {key!r}")
        result[key] = value
    return result


def _canonical_json(value: Mapping[str, Any]) -> bytes:
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode(
            "utf-8"
        )
    except (TypeError, ValueError) as exc:
        raise CanonicalWorkflowCapsuleError("canonical workflow capsule must contain finite JSON") from exc


def _digest(value: Mapping[str, Any]) -> str:
    return hashlib.sha256(_canonical_json(value)).hexdigest()


__all__ = [
    "CANONICAL_WORKFLOW_CAPSULE_VERSION",
    "MAX_CANONICAL_WORKFLOW_CAPSULE_BYTES",
    "CanonicalWorkflowCapsule",
    "CanonicalWorkflowCapsuleError",
    "load_canonical_capsule",
]
