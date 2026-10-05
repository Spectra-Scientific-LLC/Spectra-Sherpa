"""Authoritative semantic preflight for canonical-DAG workflow admission.

The service intentionally has no database or HTTP dependency.  Saved-workflow
validation, the preflight endpoint, and ordinary Run consume the exact same
admission result today; import, support tools, and managed admission can adopt
it without recreating compatibility policy.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable

from spectra_sherpa.app.services.dag import out_of_fold_evidence
from spectra_sherpa.app.services.dag.executor import DAGExecutor
from spectra_sherpa.app.services.dag.executor_types import WorkflowEdge, WorkflowNode
from spectra_sherpa.app.services.dag.node_base import node_registry
from spectra_sherpa.app.services.dag.node_catalog_contract import dependency_readiness
from spectra_sherpa.app.services.dag.stable_execution_contract import (
    StableExecutionContractError,
    ensure_registered_execution_contract,
)
from spectra_sherpa.app.types import type_registry


@dataclass(frozen=True)
class PreflightIssue:
    level: str
    code: str
    message: str
    node_id: str | None = None
    port: str | None = None


@dataclass(frozen=True)
class EdgeCompatibility:
    from_node_id: str
    from_output: str
    to_node_id: str
    to_input: str
    status: str
    reason: str | None = None


@dataclass
class WorkflowPreflight:
    issues: list[PreflightIssue] = field(default_factory=list)
    edges: list[EdgeCompatibility] = field(default_factory=list)

    @property
    def is_valid(self) -> bool:
        return not any(issue.level == "error" for issue in self.issues)


def _port_type(metadata, name: str, direction: str) -> str | None:
    from spectra_sherpa.app.services.dag.managed_port_topology import resolve_declared_port

    try:
        return resolve_declared_port(metadata, name, direction).type_ref
    except ValueError:
        return None


def preflight_workflow(
    nodes: Iterable[WorkflowNode],
    edges: Iterable[WorkflowEdge],
    *,
    require_runtime_dependencies: bool = True,
    target_node_id: str | None = None,
) -> WorkflowPreflight:
    """Resolve dependency readiness and semantic edge compatibility once.

    Every admitted operation must carry a current execution contract and every
    edge must resolve through the one semantic type registry.  Prototype
    compatibility and migration classification are intentionally absent.
    """

    materialized_nodes = list(nodes)
    materialized_edges = list(edges)
    result = WorkflowPreflight()
    if target_node_id is not None:
        from .execution_scope import upstream_node_ids

        try:
            selected = upstream_node_ids(
                (node.node_id for node in materialized_nodes), materialized_edges, target_node_id
            )
        except ValueError as exc:
            result.issues.append(PreflightIssue("error", "unknown_execution_target", str(exc), target_node_id))
            return result
        materialized_nodes = [node for node in materialized_nodes if node.node_id in selected]
        materialized_edges = [edge for edge in materialized_edges if edge.to_node in selected]

    node_by_id: dict[str, WorkflowNode] = {}
    for node in materialized_nodes:
        if node.node_id in node_by_id:
            result.issues.append(
                PreflightIssue(
                    "error",
                    "duplicate_node_id",
                    f"Workflow contains duplicate node ID: {node.node_id}",
                    node.node_id,
                )
            )
            continue
        node_by_id[node.node_id] = node

    if not type_registry.is_loaded:
        result.issues.append(
            PreflightIssue(
                "error",
                "type_registry_unavailable",
                "Semantic type registry is unavailable; workflow remains inspectable but cannot run.",
            )
        )

    metadata_by_id = {}
    for node in node_by_id.values():
        try:
            metadata = node_registry.get_metadata(node.node_type)
        except KeyError:
            result.issues.append(
                PreflightIssue("error", "unknown_node_type", f"Unknown node type: {node.node_type}", node.node_id)
            )
            continue
        metadata_by_id[node.node_id] = metadata
        if metadata.execution_contract is None:
            result.issues.append(
                PreflightIssue(
                    "error",
                    "missing_execution_contract",
                    "Workflow operations require a current canonical execution contract.",
                    node.node_id,
                )
            )
        else:
            try:
                ensure_registered_execution_contract(metadata)
            except (StableExecutionContractError, ValueError) as exc:
                result.issues.append(
                    PreflightIssue(
                        "error",
                        "invalid_execution_contract",
                        f"Canonical node execution contract is unavailable or inconsistent: {exc}",
                        node.node_id,
                    )
                )
        readiness = dependency_readiness(metadata)
        if require_runtime_dependencies and not readiness.ready:
            result.issues.append(
                PreflightIssue(
                    "error",
                    readiness.blockers[0],
                    readiness.remediation[0],
                    node.node_id,
                )
            )

    for edge in materialized_edges:
        source = metadata_by_id.get(edge.from_node)
        target = metadata_by_id.get(edge.to_node)
        if source is None or target is None:
            continue
        source_ref = _port_type(source, edge.from_output, "output")
        target_ref = _port_type(target, edge.to_input, "input")
        if source_ref is None or target_ref is None:
            result.issues.append(
                PreflightIssue(
                    "error",
                    "missing_declared_port",
                    "Canonical-contract nodes require declared named input and output ports.",
                    edge.to_node,
                    edge.to_input,
                )
            )
            result.edges.append(
                EdgeCompatibility(edge.from_node, edge.from_output, edge.to_node, edge.to_input, "invalid")
            )
            continue
        if not type_registry.is_loaded:
            result.edges.append(
                EdgeCompatibility(
                    edge.from_node,
                    edge.from_output,
                    edge.to_node,
                    edge.to_input,
                    "invalid",
                    "Semantic type registry is unavailable.",
                )
            )
            continue

        if target_ref == out_of_fold_evidence.OUT_OF_FOLD_EVIDENCE_TYPE:
            try:
                out_of_fold_evidence.require_canonical_out_of_fold_producer(source)
            except ValueError as exc:
                reason = str(exc)
                result.issues.append(
                    PreflightIssue(
                        "error",
                        "unauthorized_out_of_fold_evidence_producer",
                        reason,
                        edge.to_node,
                        edge.to_input,
                    )
                )
                result.edges.append(
                    EdgeCompatibility(
                        edge.from_node,
                        edge.from_output,
                        edge.to_node,
                        edge.to_input,
                        "invalid",
                        reason,
                    )
                )
                continue

        compatible, reason = type_registry.is_compatible(source_ref, target_ref)
        if compatible:
            from .model_edge_contracts import model_edge_error

            reason = model_edge_error(source, edge.from_output, target, edge.to_input)
            compatible = reason is None
        if compatible:
            result.edges.append(
                EdgeCompatibility(edge.from_node, edge.from_output, edge.to_node, edge.to_input, "typed_valid")
            )
        else:
            result.issues.append(
                PreflightIssue(
                    "error",
                    "incompatible_semantic_edge",
                    f"Incompatible semantic edge: {reason}",
                    edge.to_node,
                    edge.to_input,
                )
            )
            result.edges.append(
                EdgeCompatibility(edge.from_node, edge.from_output, edge.to_node, edge.to_input, "invalid", reason)
            )
    # The semantic result above and the executor's structural/parameter/data-
    # role rules form one admission report.  Semantic port checks are omitted
    # here deliberately: this service is the sole resolver for compatibility
    # in saved-workflow API paths.
    executor = DAGExecutor()
    for node in node_by_id.values():
        try:
            executor.add_node(node)
        except KeyError:
            # ``unknown_node_type`` is already recorded above.
            continue
    for edge in materialized_edges:
        try:
            executor.add_edge(edge)
        except ValueError as exc:
            result.issues.append(PreflightIssue("error", "invalid_graph_edge", str(exc)))
    for issue in executor.validate_full(include_port_type_validation=False).issues:
        result.issues.append(
            PreflightIssue(
                issue.level,
                issue.code,
                issue.message,
                issue.node_id,
                issue.port,
            )
        )
    return result
