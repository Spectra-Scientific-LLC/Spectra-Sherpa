"""Build the visible OSS application path for a canonical fitted artifact.

The managed Runner's immutable fitted artifact deliberately contains fitted
state but not a workflow definition.  Conversely, the canonical v4 capsule
contains the admitted typed workflow but never fitted state bytes.  A useful
workbench application path needs both, and must join them by evidence rather
than by a friendly node name.

This module is that join.  It produces a closed, data-free application plan
which later project export/import code can persist unchanged.  The plan keeps
the original identities and parameters for stateless transforms, replaces each
fitted operation with an explicit artifact-bound apply operation, and removes
the validation-only evaluator.  It does *not* execute a workflow, fit a state,
or read a project database.
"""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Mapping

from spectra_sherpa.core.node_identity import canonical_node_type, node_contract_digest_is_compatible
from spectra_sherpa.execution_contract_vocabulary import (
    LifecycleKind,
    ManagedOptimizationEligibility,
    RuntimeFamily,
    WorkerCapability,
)

from .canonical_capsule import CanonicalWorkflowCapsule
from .canonical_fitted_artifact import CanonicalFittedArtifact
from .canonical_wire_versions import CANONICAL_WORKFLOW_CAPSULE_VERSION

CANONICAL_APPLICATION_PLAN_VERSION = "spectra-canonical-application-plan/2"
_DIGEST_LENGTH = 64
_APPLICATION_OPERATION_BY_SOURCE = {
    "classification.knn": "classification.apply_knn",
    "classification.plsda": "classification.apply_plsda",
    "classification.simca": "classification.apply_simca",
    "preprocess.emsc": "preprocess.apply_fitted_emsc",
    "preprocess.msc": "preprocess.apply_fitted_msc",
    "preprocess.osc": "preprocess.apply_fitted_osc",
    "preprocess.scale": "preprocess.apply_fitted_scale",
    "model.fitted_pls": "model.apply_fitted_pls",
    "model.fitted_pcr": "model.apply_fitted_pcr",
    "model.fitted_svr": "model.apply_fitted_svr",
    "model.fitted_linear_regression": "model.apply_fitted_linear_regression",
}
_FITTED_PLS_OPERATION_ID = "model.fitted_pls"
_APPLY_FITTED_PLS_OPERATION_ID = "model.apply_fitted_pls"
_LEGACY_PLS_APPLICATION_CONTRACT_PAIRS = frozenset(
    {
        (
            "64bdf49b4d1cc289f43edca2e760037b3ce6c82e731bbb3c9aa1b7c7460028a8",
            "7a54cae94c875d150e16ea321960b6b3db5f1176cae2756f007d1bd134c94cf9",
        ),
        (
            "ac05f06a069e5551f5cd101dbaec0d40ff352860b360a98e367e1f17dbbaf98d",
            "efee828721a2fa29dc3ddb8b0737a9fcd72d45830b5c9db391438cdd4f087baa",
        ),
    }
)


class CanonicalApplicationPlanError(ValueError):
    """The capsule/artifact pair cannot safely create an application path."""


@dataclass(frozen=True)
class CanonicalApplicationPlan:
    """A verified, visible application projection of one selected refit.

    ``payload`` is intentionally data-free and has a closed schema.  The
    actual state bytes remain only in the separately verified fitted artifact;
    each fitted application node carries every identity needed for its later
    reader to reject a swapped state before applying it.
    """

    payload: dict[str, Any]
    application_plan_digest: str

    @classmethod
    def from_capsule_and_artifact(
        cls,
        capsule: CanonicalWorkflowCapsule,
        artifact: CanonicalFittedArtifact,
    ) -> "CanonicalApplicationPlan":
        """Jointly re-admit a materialized v4 capsule and fitted artifact.

        New application plans bind the execution contract of every operation
        that will execute in the scientist-facing workbench.  The original
        fitted graph's contract is not enough: an artifact-application node
        has its own implementation closure and a deliberately local-only
        lifecycle.
        """

        return cls._from_capsule_and_artifact(capsule, artifact)

    @classmethod
    def _from_capsule_and_artifact(
        cls,
        capsule: CanonicalWorkflowCapsule,
        artifact: CanonicalFittedArtifact,
    ) -> "CanonicalApplicationPlan":
        """Build the sole current application plan."""

        if not isinstance(capsule, CanonicalWorkflowCapsule):
            raise CanonicalApplicationPlanError("canonical application plan requires a verified capsule")
        if not isinstance(artifact, CanonicalFittedArtifact):
            raise CanonicalApplicationPlanError("canonical application plan requires a verified fitted artifact")
        if capsule.payload["schema_version"] != CANONICAL_WORKFLOW_CAPSULE_VERSION:
            raise CanonicalApplicationPlanError("canonical application plan requires the current materialized capsule")
        refit = capsule.full_refit_evidence
        if refit is None:
            raise CanonicalApplicationPlanError("canonical application plan requires a materialized full-data refit")
        if artifact.payload["full_refit_evidence"] != refit.as_dict():
            raise CanonicalApplicationPlanError("canonical artifact refit differs from canonical capsule")

        graph = capsule.graph
        refit_projection = refit.payload["full_refit_execution"]
        if refit_projection["graph_digest"] != graph.digest:
            raise CanonicalApplicationPlanError("canonical full-data refit graph differs from capsule")
        if refit_projection["validation_execution_digest"] != capsule.execution_evidence.validation_execution_digest:
            raise CanonicalApplicationPlanError("canonical full-data refit validation differs from capsule")

        state_members = _state_members_by_node(artifact)
        application_nodes: list[dict[str, Any]] = []
        expected_state_node_ids: list[str] = []
        for graph_node in graph.nodes:
            lifecycle = graph_node.contract.payload["lifecycle_kind"]
            if lifecycle == LifecycleKind.EVALUATOR.value:
                continue
            node = {
                "node_id": graph_node.node_id,
                "source_operation_id": graph_node.operation_id,
                "source_contract_digest": graph_node.contract.digest,
                "parameters": deepcopy(dict(graph_node.parameters)),
            }
            if lifecycle == LifecycleKind.STATELESS_TRANSFORM.value:
                node["application_operation_id"] = graph_node.operation_id
            elif lifecycle in {LifecycleKind.FITTED_TRANSFORM.value, LifecycleKind.FITTED_MODEL.value}:
                application_operation = _APPLICATION_OPERATION_BY_SOURCE.get(graph_node.operation_id)
                if application_operation is None:
                    raise CanonicalApplicationPlanError(
                        f"no artifact-bound application operation is registered for {graph_node.operation_id}"
                    )
                member = state_members.get(graph_node.node_id)
                if member is None:
                    raise CanonicalApplicationPlanError("canonical artifact is missing a fitted application state")
                if (
                    member["contract_digest"] != graph_node.contract.digest
                    or member["serializer"] != graph_node.contract.payload["fitted_state_serializer"]
                ):
                    raise CanonicalApplicationPlanError(
                        "canonical artifact state differs from the admitted node contract"
                    )
                expected_state_node_ids.append(graph_node.node_id)
                node["application_operation_id"] = application_operation
                node["artifact_binding"] = {
                    "artifact_digest": artifact.artifact_digest,
                    "state_node_id": graph_node.node_id,
                    "state_digest": member["state_digest"],
                    "state_content_digest": member["state_content_digest"],
                    "serializer": member["serializer"],
                    "source_contract_digest": member["contract_digest"],
                }
            else:  # The graph admission boundary has already closed this vocabulary.
                raise CanonicalApplicationPlanError("canonical application graph contains an unsupported lifecycle")
            node["application_contract_digest"] = _admit_application_operation(
                source_operation_id=graph_node.operation_id,
                source_contract_digest=graph_node.contract.digest,
                application_operation_id=node["application_operation_id"],
                source_serializer=(
                    graph_node.contract.payload["fitted_state_serializer"]
                    if lifecycle in {LifecycleKind.FITTED_TRANSFORM.value, LifecycleKind.FITTED_MODEL.value}
                    else None
                ),
            )
            application_nodes.append(node)

        if [member["node_id"] for member in artifact.payload["state_members"]] != expected_state_node_ids:
            raise CanonicalApplicationPlanError("canonical artifact state order differs from application graph")
        if refit_projection["node_ids"] != [node["node_id"] for node in application_nodes]:
            raise CanonicalApplicationPlanError("canonical full-data refit nodes differ from application graph")

        application_node_ids = {node["node_id"] for node in application_nodes}
        application_edges = [
            {
                "from_node_id": edge.from_node,
                "from_output": edge.from_output,
                "to_node_id": edge.to_node,
                "to_input": edge.to_input,
            }
            for edge in graph.edges
            if edge.from_node in application_node_ids and edge.to_node in application_node_ids
        ]
        unsigned = {
            "schema_version": CANONICAL_APPLICATION_PLAN_VERSION,
            "capsule_digest": capsule.capsule_digest,
            "artifact_digest": artifact.artifact_digest,
            "graph_digest": graph.digest,
            "validation_execution_digest": capsule.execution_evidence.validation_execution_digest,
            "full_refit_evidence_digest": refit.content_digest,
            "full_refit_execution_digest": refit.full_refit_execution_digest,
            "model_node_id": refit_projection["model_node_id"],
            "nodes": application_nodes,
            "edges": application_edges,
        }
        return cls._validated({**unsigned, "application_plan_digest": _digest(unsigned)})

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "CanonicalApplicationPlan":
        """Load a closed plan for a later project importer without executing it."""

        return cls._validated(value)

    def as_dict(self) -> dict[str, Any]:
        """Return a detached, JSON-safe plan projection."""

        return deepcopy(self.payload)

    def require_matches(
        self,
        capsule: CanonicalWorkflowCapsule,
        artifact: CanonicalFittedArtifact,
    ) -> None:
        """Rebuild the admitted plan and reject a detached substitution.

        Project import calls this after loading archive members: structural
        validation of a stored plan is deliberately not a substitute for
        rejoining it to the exact capsule and artifact that it names.
        """

        expected = type(self)._from_capsule_and_artifact(
            capsule,
            artifact,
        )
        if self.payload != expected.payload:
            raise CanonicalApplicationPlanError("canonical application plan differs from its capsule or artifact")

    @classmethod
    def _validated(cls, value: Mapping[str, Any]) -> "CanonicalApplicationPlan":
        if isinstance(value, Mapping):
            value = _normalize_legacy_node_identities(value)
        required = {
            "schema_version",
            "capsule_digest",
            "artifact_digest",
            "graph_digest",
            "validation_execution_digest",
            "full_refit_evidence_digest",
            "full_refit_execution_digest",
            "model_node_id",
            "nodes",
            "edges",
            "application_plan_digest",
        }
        if not isinstance(value, Mapping) or set(value) != required:
            raise CanonicalApplicationPlanError("canonical application plan fields are closed")
        schema_version = value["schema_version"]
        if schema_version != CANONICAL_APPLICATION_PLAN_VERSION:
            raise CanonicalApplicationPlanError("canonical application plan schema is unsupported")
        for field in required - {"schema_version", "nodes", "edges", "model_node_id", "application_plan_digest"}:
            _require_digest(value[field], field)
        _require_digest(value["application_plan_digest"], "application_plan_digest")
        if not isinstance(value["model_node_id"], str) or not value["model_node_id"]:
            raise CanonicalApplicationPlanError("canonical application plan model node is invalid")
        nodes = value["nodes"]
        edges = value["edges"]
        if not isinstance(nodes, list) or not nodes or not isinstance(edges, list):
            raise CanonicalApplicationPlanError("canonical application plan nodes and edges are malformed")

        node_ids: set[str] = set()
        fitted_node_ids: list[str] = []
        normalized_nodes: list[dict[str, Any]] = []
        for node in nodes:
            if not isinstance(node, Mapping):
                raise CanonicalApplicationPlanError("canonical application plan node is malformed")
            base_fields = {
                "node_id",
                "source_operation_id",
                "source_contract_digest",
                "parameters",
                "application_operation_id",
            }
            base_fields.add("application_contract_digest")
            binding = node.get("artifact_binding")
            if binding is None:
                if set(node) != base_fields:
                    raise CanonicalApplicationPlanError("stateless application node fields are closed")
            else:
                if set(node) != base_fields | {"artifact_binding"}:
                    raise CanonicalApplicationPlanError("fitted application node fields are closed")
            node_id = node["node_id"]
            source_operation = node["source_operation_id"]
            application_operation = node["application_operation_id"]
            if (
                not isinstance(node_id, str)
                or not node_id
                or node_id in node_ids
                or not isinstance(source_operation, str)
                or not source_operation
                or not isinstance(application_operation, str)
                or not application_operation
                or not isinstance(node["parameters"], Mapping)
            ):
                raise CanonicalApplicationPlanError("canonical application node identity is invalid")
            _require_digest(node["source_contract_digest"], "source_contract_digest")
            normalized = {
                "node_id": node_id,
                "source_operation_id": source_operation,
                "source_contract_digest": node["source_contract_digest"],
                "parameters": deepcopy(dict(node["parameters"])),
                "application_operation_id": application_operation,
            }
            source_serializer: str | None = None
            if binding is None:
                if application_operation != source_operation:
                    raise CanonicalApplicationPlanError("stateless application node must retain its operation")
            else:
                _validate_artifact_binding(
                    binding,
                    node_id=node_id,
                    source_contract_digest=node["source_contract_digest"],
                    artifact_digest=value["artifact_digest"],
                )
                expected_operation = _APPLICATION_OPERATION_BY_SOURCE.get(source_operation)
                if application_operation != expected_operation:
                    raise CanonicalApplicationPlanError("fitted application node operation is not registered")
                source_serializer = binding["serializer"]
                normalized["artifact_binding"] = deepcopy(dict(binding))
                fitted_node_ids.append(node_id)
            application_contract_digest = node["application_contract_digest"]
            _require_digest(application_contract_digest, "application_contract_digest")
            admitted_digest = _admit_application_operation(
                source_operation_id=source_operation,
                source_contract_digest=node["source_contract_digest"],
                application_operation_id=application_operation,
                source_serializer=source_serializer,
            )
            if application_contract_digest != admitted_digest:
                raise CanonicalApplicationPlanError(
                    "application operation differs from its admitted execution contract"
                )
            normalized["application_contract_digest"] = application_contract_digest
            node_ids.add(node_id)
            normalized_nodes.append(normalized)

        normalized_edges: list[dict[str, str]] = []
        seen_edges: set[tuple[str, str, str, str]] = set()
        for edge in edges:
            if not isinstance(edge, Mapping) or set(edge) != {"from_node_id", "from_output", "to_node_id", "to_input"}:
                raise CanonicalApplicationPlanError("canonical application edge fields are closed")
            values = tuple(edge[field] for field in ("from_node_id", "from_output", "to_node_id", "to_input"))
            if not all(isinstance(item, str) and item for item in values):
                raise CanonicalApplicationPlanError("canonical application edge identity is invalid")
            if values[0] not in node_ids or values[2] not in node_ids or values in seen_edges:
                raise CanonicalApplicationPlanError("canonical application edge is invalid")
            seen_edges.add(values)
            normalized_edges.append(
                {"from_node_id": values[0], "from_output": values[1], "to_node_id": values[2], "to_input": values[3]}
            )

        if value["model_node_id"] not in fitted_node_ids:
            raise CanonicalApplicationPlanError("canonical application plan model does not bind fitted state")
        model_node = next(node for node in normalized_nodes if node["node_id"] == value["model_node_id"])
        if model_node["application_operation_id"] not in {
            "classification.apply_knn",
            "classification.apply_plsda",
            "classification.apply_simca",
            "model.apply_fitted_pls",
            "model.apply_fitted_pcr",
            "model.apply_fitted_svr",
            "model.apply_fitted_linear_regression",
        }:
            raise CanonicalApplicationPlanError("canonical application plan has no supported fitted model")
        expected_edges = [
            {
                "from_node_id": left["node_id"],
                "from_output": "default",
                "to_node_id": right["node_id"],
                "to_input": "default",
            }
            for left, right in zip(normalized_nodes, normalized_nodes[1:])
        ]
        if normalized_edges != expected_edges:
            raise CanonicalApplicationPlanError("canonical application plan topology is not the admitted linear path")
        unsigned = {
            "schema_version": value["schema_version"],
            "capsule_digest": value["capsule_digest"],
            "artifact_digest": value["artifact_digest"],
            "graph_digest": value["graph_digest"],
            "validation_execution_digest": value["validation_execution_digest"],
            "full_refit_evidence_digest": value["full_refit_evidence_digest"],
            "full_refit_execution_digest": value["full_refit_execution_digest"],
            "model_node_id": value["model_node_id"],
            "nodes": normalized_nodes,
            "edges": normalized_edges,
        }
        digest = _digest(unsigned)
        if value["application_plan_digest"] != digest:
            raise CanonicalApplicationPlanError("canonical application plan content digest mismatch")
        return cls({**unsigned, "application_plan_digest": digest}, digest)

    @property
    def application_contract_status(self) -> str:
        """State that the sole admitted plan binds its application executor."""

        return "application_contracts_bound"


def _admit_application_operation(
    *,
    source_operation_id: str,
    source_contract_digest: str,
    application_operation_id: str,
    source_serializer: str | None,
) -> str:
    """Resolve the one live contract that the visible application node runs.

    This deliberately re-admits both sides of an artifact application.  A
    source contract names how state was fitted; it cannot substitute for the
    execution identity of code that reads an artifact and applies that state
    to new local spectra.
    """

    # Keep this application import lazy.  The package verifier stays usable
    # as an SDK artifact until a caller asks it to certify current workbench
    # execution, at which point a live typed-node registry is required.
    from spectra_sherpa.app.services.dag.node_base import node_registry

    try:
        source_metadata = node_registry.get_metadata(source_operation_id)
        application_metadata = node_registry.get_metadata(application_operation_id)
    except KeyError as exc:
        raise CanonicalApplicationPlanError("canonical application operation is not registered") from exc
    source_contract = source_metadata.resolved_execution_contract()
    application_contract = application_metadata.resolved_execution_contract()
    if source_contract is None or not node_contract_digest_is_compatible(
        source_operation_id,
        source_contract_digest,
        source_contract.digest,
    ):
        raise CanonicalApplicationPlanError("canonical application source operation is not currently re-admitted")
    if application_contract is None:
        raise CanonicalApplicationPlanError("canonical application operation lacks an immutable execution contract")

    payload = application_contract.payload
    if payload["operation_id"] != application_operation_id:
        raise CanonicalApplicationPlanError("canonical application operation has an invalid execution identity")
    if source_operation_id == application_operation_id:
        if application_contract.digest != source_contract_digest:
            raise CanonicalApplicationPlanError("stateless application operation differs from its source contract")
        return application_contract.digest

    if (
        payload["runtime_family"] != RuntimeFamily.SHERPA_NATIVE.value
        or payload["lifecycle_kind"] != LifecycleKind.ARTIFACT_APPLICATION.value
        or payload["fitted_state_serializer"] != source_serializer
        or list(payload["managed_optimization_eligibility"]) != [ManagedOptimizationEligibility.LOCAL.value]
        or WorkerCapability.READ_CANONICAL_FITTED_ARTIFACT.value not in payload["required_worker_capabilities"]
    ):
        raise CanonicalApplicationPlanError(
            "canonical artifact application operation is not local-only and state-bound"
        )
    return application_contract.digest


def _normalize_legacy_node_identities(value: Mapping[str, Any]) -> dict[str, Any]:
    """Verify and upgrade a self-consistent suffix-era application plan."""

    normalized = deepcopy(dict(value))
    nodes = normalized.get("nodes")
    if not isinstance(nodes, list):
        return normalized
    uses_alias = any(
        isinstance(node, Mapping)
        and any(
            isinstance(node.get(field), str) and canonical_node_type(node[field]) != node[field]
            for field in ("source_operation_id", "application_operation_id")
        )
        for node in nodes
    )
    if not uses_alias:
        return normalized

    supplied_digest = normalized.get("application_plan_digest")
    unsigned_before = {key: item for key, item in normalized.items() if key != "application_plan_digest"}
    if supplied_digest != _digest(unsigned_before):
        raise CanonicalApplicationPlanError("legacy canonical application plan content digest mismatch")

    for node in nodes:
        if not isinstance(node, dict):
            continue
        source_operation = node.get("source_operation_id")
        application_operation = node.get("application_operation_id")
        if isinstance(source_operation, str):
            node["source_operation_id"] = canonical_node_type(source_operation)
        if isinstance(application_operation, str):
            node["application_operation_id"] = canonical_node_type(application_operation)
        legacy_pair = (node.get("source_contract_digest"), node.get("application_contract_digest"))
        if (
            node.get("source_operation_id") == _FITTED_PLS_OPERATION_ID
            and node.get("application_operation_id") == _APPLY_FITTED_PLS_OPERATION_ID
            and legacy_pair in _LEGACY_PLS_APPLICATION_CONTRACT_PAIRS
        ):
            binding = node.get("artifact_binding")
            serializer = binding.get("serializer") if isinstance(binding, Mapping) else None
            node["application_contract_digest"] = _admit_application_operation(
                source_operation_id=_FITTED_PLS_OPERATION_ID,
                source_contract_digest=node["source_contract_digest"],
                application_operation_id=_APPLY_FITTED_PLS_OPERATION_ID,
                source_serializer=serializer if isinstance(serializer, str) else None,
            )

    unsigned_after = {key: item for key, item in normalized.items() if key != "application_plan_digest"}
    normalized["application_plan_digest"] = _digest(unsigned_after)
    return normalized


def _state_members_by_node(artifact: CanonicalFittedArtifact) -> dict[str, Mapping[str, Any]]:
    try:
        members = artifact.payload["state_members"]
        return {member["node_id"]: member for member in members}
    except (KeyError, TypeError) as exc:  # Artifact validates this, but fail closed at this independent join.
        raise CanonicalApplicationPlanError("canonical artifact state members are unavailable") from exc


def _validate_artifact_binding(
    value: Any,
    *,
    node_id: str,
    source_contract_digest: Any,
    artifact_digest: Any,
) -> None:
    required = {
        "artifact_digest",
        "state_node_id",
        "state_digest",
        "state_content_digest",
        "serializer",
        "source_contract_digest",
    }
    if not isinstance(value, Mapping) or set(value) != required:
        raise CanonicalApplicationPlanError("canonical artifact binding fields are closed")
    if (
        value["artifact_digest"] != artifact_digest
        or value["state_node_id"] != node_id
        or value["source_contract_digest"] != source_contract_digest
    ):
        raise CanonicalApplicationPlanError("canonical artifact binding identity differs from its node")
    for field in ("artifact_digest", "state_digest", "state_content_digest", "source_contract_digest"):
        _require_digest(value[field], f"artifact_binding.{field}")
    if not isinstance(value["serializer"], str) or not value["serializer"]:
        raise CanonicalApplicationPlanError("canonical artifact binding serializer is invalid")


def _require_digest(value: Any, field: str) -> None:
    if (
        not isinstance(value, str)
        or len(value) != _DIGEST_LENGTH
        or any(char not in "0123456789abcdef" for char in value)
    ):
        raise CanonicalApplicationPlanError(f"canonical application plan {field} is not a SHA-256 digest")


def _digest(value: Mapping[str, Any]) -> str:
    try:
        encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False).encode(
            "utf-8"
        )
    except (TypeError, ValueError) as exc:
        raise CanonicalApplicationPlanError("canonical application plan must contain finite JSON") from exc
    return hashlib.sha256(encoded).hexdigest()


__all__ = [
    "CANONICAL_APPLICATION_PLAN_VERSION",
    "CanonicalApplicationPlan",
    "CanonicalApplicationPlanError",
]
