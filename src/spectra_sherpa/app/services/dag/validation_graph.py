"""Canonical, scientifically admissible DAG shape for validation execution.

This module is deliberately a *graph authority*, not a second executor.  It
turns a persisted workbench graph into the small, immutable graph shape that a
future fold executor may consume.  The ordinary workbench may continue to
display and run legacy/presentation/export nodes locally; none of those nodes
can enter a managed scientific score merely because they happen to share the
same canvas.

The first implementation supports the one-input/one-output transform chain
needed by the M4 first-party wedge.  Branches and named-port fan-in are added
only with an explicit profile and execution consumer; accepting them here
without one would make a scientific promise the runner cannot yet keep.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Iterable, Mapping

from spectra_sherpa.app.services.dag.executor_types import WorkflowEdge, WorkflowNode
from spectra_sherpa.app.services.dag.graph_utils import Edge, topological_sort
from spectra_sherpa.app.services.dag.managed_optimization_profile import (
    ManagedOptimizationProfileError,
    managed_optimization_profile,
)
from spectra_sherpa.app.services.dag.node_base import node_registry
from spectra_sherpa.app.services.dag.workflow_preflight import preflight_workflow
from spectra_sherpa.execution_contract_vocabulary import (
    LifecycleKind,
    ManagedOptimizationEligibility,
    NodeExecutionContract,
    SupervisedTask,
)


class ValidationGraphError(ValueError):
    """A workbench DAG is not safe to score as a validation candidate."""


class ValidationRuntimeAttestationError(ValidationGraphError):
    """The managed worker runtime does not satisfy the admitted profile."""


class ValidationContractError(ValidationGraphError):
    """A node contract differs from the closed managed profile."""


_SHA256_HEX = re.compile(r"[0-9a-f]{64}\Z")


@dataclass(frozen=True)
class ValidationGraphNode:
    """One registered canonical execution identity at a persisted graph node."""

    node_id: str
    operation_id: str
    parameters_json: str
    contract: NodeExecutionContract

    @property
    def parameters(self) -> Mapping[str, object]:
        """Return a fresh plain JSON object for a later fresh-node invocation."""

        return json.loads(self.parameters_json)


@dataclass(frozen=True)
class ValidationGraphEdge:
    """Immutable topology record; never retain mutable workbench edge objects."""

    from_node: str
    to_node: str
    from_output: str
    to_input: str


@dataclass(frozen=True, init=False)
class ValidationGraph:
    """A closed, topologically ordered validation-only graph identity.

    Instances are created only by :func:`admit_validation_graph`.  The fold
    executor also rechecks this immutable projection before execution, so an
    object forged through Python introspection cannot provide an alternate
    topology or operation-admission path.
    """

    nodes: tuple[ValidationGraphNode, ...]
    edges: tuple[ValidationGraphEdge, ...]

    def _identity_dict(self) -> dict[str, object]:
        """Return the content whose digest identifies this immutable graph."""

        return {
            "schema_version": "spectra-validation-graph/1",
            "nodes": [
                {
                    "node_id": node.node_id,
                    "operation_id": node.operation_id,
                    "parameters": json.loads(node.parameters_json),
                    "contract_digest": node.contract.digest,
                }
                for node in self.nodes
            ],
            "edges": [
                {
                    "from_node": edge.from_node,
                    "from_output": edge.from_output,
                    "to_node": edge.to_node,
                    "to_input": edge.to_input,
                }
                for edge in self.edges
            ],
        }

    def as_dict(self) -> dict[str, object]:
        """Return the closed, data-free identity a governed Runner re-admits.

        The request intentionally carries contract *digests*, not contract
        payloads.  The Runner resolves the locally registered immutable
        contracts again.  Each parameter is first projected onto the exact
        first-profile node schema, so no caller can smuggle an opaque nested
        object, implementation description, executable code, or sample-like
        content through an ignored node setting.  ``graph_digest`` binds this
        specific candidate identity; an outer Runner request later binds that
        digest to the campaign and capability it was authorized to use.
        """

        return {**self._identity_dict(), "graph_digest": self.digest}

    @property
    def digest(self) -> str:
        """Return the portable identity of semantics, parameters, and topology."""

        payload = self._identity_dict()
        try:
            encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)
        except (TypeError, ValueError) as exc:
            raise ValidationGraphError("candidate parameters must be finite JSON values") from exc
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def validation_graph_from_dict(
    payload: Mapping[str, object],
    *,
    require_live_runtime: bool = True,
) -> ValidationGraph:
    """Rebuild and independently re-admit a serialized canonical graph.

    This is the sole wire-to-graph path intended for the M4 Runner.  Its
    default binds the caller's operation, parameter, topology, and
    contract-digest claims to live local authority before any dataset
    capability can be opened.  A sealed, data-free package may explicitly use
    ``require_live_runtime=False`` for offline inspection: it still admits
    every closed contract, parameter projection, typed edge, topology, and
    recorded identity, but does not pretend an absent optional numerical
    runtime is installed.  That offline mode is never an execution grant.
    """

    if set(payload) != {"schema_version", "nodes", "edges", "graph_digest"}:
        raise ValidationGraphError("validation graph wire payload has undeclared fields")
    if payload["schema_version"] != "spectra-validation-graph/1":
        raise ValidationGraphError("unsupported validation graph wire version")
    raw_nodes = payload["nodes"]
    raw_edges = payload["edges"]
    graph_digest = payload["graph_digest"]
    if not isinstance(raw_nodes, list) or not isinstance(raw_edges, list):
        raise ValidationGraphError("validation graph nodes and edges must be arrays")
    if not isinstance(graph_digest, str) or _SHA256_HEX.fullmatch(graph_digest) is None:
        raise ValidationGraphError("validation graph wire graph digest is malformed")
    nodes: list[WorkflowNode] = []
    expected_digests: dict[str, str] = {}
    for raw_node in raw_nodes:
        if not isinstance(raw_node, Mapping) or set(raw_node) != {
            "node_id",
            "operation_id",
            "parameters",
            "contract_digest",
        }:
            raise ValidationGraphError("validation graph node wire payload has undeclared fields")
        node_id = raw_node["node_id"]
        operation_id = raw_node["operation_id"]
        parameters = raw_node["parameters"]
        contract_digest = raw_node["contract_digest"]
        if not isinstance(node_id, str) or not isinstance(operation_id, str):
            raise ValidationGraphError("validation graph node identity must be text")
        if not isinstance(parameters, Mapping):
            raise ValidationGraphError("validation graph node parameters must be an object")
        if not isinstance(contract_digest, str) or _SHA256_HEX.fullmatch(contract_digest) is None:
            raise ValidationGraphError("validation graph node contract digest is malformed")
        nodes.append(WorkflowNode(node_id, operation_id, dict(parameters)))
        if node_id in expected_digests:
            raise ValidationGraphError("validation graph wire payload repeats a node ID")
        expected_digests[node_id] = contract_digest
    edges: list[WorkflowEdge] = []
    for raw_edge in raw_edges:
        if not isinstance(raw_edge, Mapping) or set(raw_edge) != {
            "from_node",
            "from_output",
            "to_node",
            "to_input",
        }:
            raise ValidationGraphError("validation graph edge wire payload has undeclared fields")
        values = tuple(raw_edge[name] for name in ("from_node", "to_node", "from_output", "to_input"))
        if not all(isinstance(value, str) for value in values):
            raise ValidationGraphError("validation graph edge identity must be text")
        edges.append(WorkflowEdge(*values))
    graph = admit_validation_graph(nodes, edges, require_live_runtime=require_live_runtime)
    if {node.node_id: node.contract.digest for node in graph.nodes} != expected_digests:
        raise ValidationGraphError("validation graph wire contract digests do not match local authority")
    if graph.digest != graph_digest:
        raise ValidationGraphError("validation graph wire graph digest does not match the admitted candidate")
    return graph


def _graph_edges(edges: Iterable[WorkflowEdge]) -> list[Edge]:
    return [Edge(edge.from_node, edge.to_node) for edge in edges]


_CAPABILITY_SOURCE_ID = "__validation_capability_source__"
_SCIENTIFIC_CATEGORIES = frozenset({"preprocessing", "selection", "modeling", "classification", "diagnostics"})
_FIRST_PROFILE_METHODS = {"selection.variable_select": frozenset({"interval"})}


def managed_validation_parameter_options(operation_id: str) -> dict[str, tuple[object, ...]]:
    """Return option restrictions imposed by the live managed profile.

    Registry schemas describe the wider workbench. Managed callers must use
    this projection so they never advertise settings that the validation
    authority will later reject.
    """

    if not isinstance(operation_id, str) or operation_id not in managed_optimization_profile().operation_ids:
        raise ValidationGraphError("operation is not in the managed validation profile")
    try:
        node_registry.get_metadata(operation_id)
    except KeyError as exc:
        raise ValidationGraphError("managed validation operation is not registered") from exc
    methods = _FIRST_PROFILE_METHODS.get(operation_id)
    return {} if methods is None else {"method": tuple(sorted(methods))}


# ``NodePolicy`` currently classifies egress but not arbitrary local side
# effects.  The scientific scoring boundary remains narrower than a category
# check: only operations selected by the closed canonical registry profile may
# enter, and fitted-model/evaluator compatibility is owned by their contracts.


def _first_profile_edge(source: ValidationGraphNode, target: ValidationGraphNode) -> ValidationGraphEdge:
    """Return the one typed edge the admitted operation pair actually executes."""

    from spectra_sherpa.app.services.dag.managed_port_topology import managed_chain_edges

    edge = managed_chain_edges(
        [WorkflowNode(node.node_id, node.operation_id, dict(node.parameters)) for node in (source, target)]
    )[0]
    return ValidationGraphEdge(edge.from_node, edge.to_node, edge.from_output, edge.to_input)


def _preflight_with_capability_source(nodes: list[WorkflowNode], edges: list[WorkflowEdge]):
    """Preflight a candidate as if the admitted capability were its source.

    The virtual node is only a semantic ``SpectralDataset`` producer; it is
    never admitted or executed.  This preserves one shared port/type
    preflight while keeping the raw-data admission boundary outside the
    candidate graph itself.
    """

    node_ids = {node.node_id for node in nodes}
    if _CAPABILITY_SOURCE_ID in node_ids:
        raise ValidationGraphError("candidate node ID is reserved for the validation capability source")
    incoming = {node.node_id: 0 for node in nodes}
    for edge in edges:
        if edge.to_node in incoming:
            incoming[edge.to_node] += 1
    roots = [node_id for node_id, count in incoming.items() if count == 0]
    source = WorkflowNode(
        node_id=_CAPABILITY_SOURCE_ID,
        node_type="data.file_load",
        parameters={"experiment_id": 1, "file_id": 1},
    )
    return preflight_workflow(
        [source, *nodes],
        [*edges, *(WorkflowEdge(_CAPABILITY_SOURCE_ID, node_id) for node_id in roots)],
    )


def _project_first_profile_parameters(node: WorkflowNode) -> dict[str, object]:
    """Produce the Runner-safe parameter projection for one certified node.

    ``Node`` deliberately tolerates extra settings so locally authored
    workbench workflows can survive old UI versions.  That compatibility is
    inappropriate at a managed candidate boundary: every byte in this
    projection must change computation, be constrained by an admitted schema,
    or be rejected before capability access.  All current first-profile
    settings are scalar; supporting an object or list requires a new profile
    version with an explicit bounded schema and an in-tree consumer.
    """

    if not isinstance(node.parameters, Mapping):
        raise ValidationGraphError(f"{node.node_id} parameters must be a JSON object")
    try:
        metadata = node_registry.get_metadata(node.node_type)
        projected = metadata.canonicalize_managed_parameters(node.parameters)
    except (KeyError, ValueError) as exc:
        raise ValidationGraphError(f"{node.node_id} {exc}") from exc
    allowed_methods = _FIRST_PROFILE_METHODS.get(node.node_type)
    if allowed_methods is not None and projected.get("method") not in allowed_methods:
        raise ValidationGraphError(f"{node.node_id} method is not in the leakage-safe managed-validation subset")
    return projected


def _admit_contract(node: WorkflowNode, *, require_live_runtime: bool = True) -> ValidationGraphNode:
    try:
        metadata = node_registry.get_metadata(node.node_type)
    except KeyError as exc:
        raise ValidationGraphError(f"unknown candidate node type: {node.node_type}") from exc
    contract = metadata.resolved_execution_contract()
    if contract is None:
        raise ValidationGraphError(
            f"{node.node_id} is uncontracted and local-only; it may not enter managed candidate scoring"
        )
    profile = managed_optimization_profile()
    if node.node_type not in profile.operation_ids:
        raise ValidationGraphError(
            f"{node.node_id} has a local-only contract and is not in the closed managed-validation profile"
        )
    if metadata.category not in _SCIENTIFIC_CATEGORIES:
        raise ValidationGraphError(f"{node.node_id} is not in an admitted scientific node category")
    if metadata.policy is None or metadata.policy.data_egress_risk != "none":
        raise ValidationGraphError(f"{node.node_id} has an egress or side-effect policy and may not be scored")
    if contract.payload["operation_id"] != node.node_type:
        raise ValidationGraphError(f"{node.node_id} registered contract does not name its operation")
    # A compatible optional-package range is enough for local OSS work,
    # but not for this fixed managed scientific profile. Execution must
    # attest the numerical runtime before considering its matching source
    # closure. Offline package inspection deliberately verifies the
    # immutable contract without claiming that an optional runtime is
    # present; the caller must explicitly select that non-executable mode.
    if require_live_runtime:
        try:
            profile.runtime_attestation((node.node_type,))
        except ManagedOptimizationProfileError as exc:
            raise ValidationRuntimeAttestationError(
                f"{node.node_id} managed runtime attestation failed: {exc}"
            ) from exc
    try:
        profile.assert_contract(contract)
    except ManagedOptimizationProfileError as exc:
        raise ValidationContractError(
            f"{node.node_id} contract does not match the first-party validation profile: {exc}"
        ) from exc
    if ManagedOptimizationEligibility.DEVELOPMENT.value not in contract.payload["managed_optimization_eligibility"]:
        raise ValidationGraphError(f"{node.node_id} is not admitted for development evaluation")
    if contract.payload["lifecycle_kind"] not in {
        LifecycleKind.STATELESS_TRANSFORM.value,
        LifecycleKind.FITTED_TRANSFORM.value,
        LifecycleKind.FITTED_MODEL.value,
        LifecycleKind.EVALUATOR.value,
    }:
        raise ValidationGraphError(f"{node.node_id} has a non-scientific lifecycle and may not be scored")
    expected_sample_effect = (
        "aggregates_samples"
        if contract.payload["lifecycle_kind"] == LifecycleKind.EVALUATOR.value
        else "preserves_samples"
    )
    if contract.payload["sample_effect"] != expected_sample_effect:
        raise ValidationGraphError(
            f"{node.node_id} has an inadmissible sample effect for this first validation profile"
        )
    projected_parameters = _project_first_profile_parameters(node)
    try:
        parameters_json = json.dumps(
            projected_parameters, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False
        )
    except (TypeError, ValueError) as exc:
        raise ValidationGraphError(f"{node.node_id} parameters must be finite JSON values") from exc
    return ValidationGraphNode(node.node_id, node.node_type, parameters_json, contract)


def _assert_first_profile_lifecycle_topology(nodes: tuple[ValidationGraphNode, ...]) -> None:
    """Permit aggregation only at the exact terminal first-wedge evaluator.

    A scientific score is one aggregate record, so the evaluator cannot claim
    to preserve sample identity.  This narrow exception belongs in the graph
    authority—not merely the executor—so a forged graph cannot place an
    aggregator before a later candidate operation.
    """

    evaluator_indexes = [
        index
        for index, node in enumerate(nodes)
        if node.contract.payload["lifecycle_kind"] == LifecycleKind.EVALUATOR.value
    ]
    if not evaluator_indexes:
        return
    if (
        evaluator_indexes != [len(nodes) - 1]
        or len(nodes) < 2
        or nodes[-2].contract.payload["lifecycle_kind"] != LifecycleKind.FITTED_MODEL.value
    ):
        raise ValidationGraphError("first-profile evaluator must be the one terminal node after a fitted model")
    model_task = nodes[-2].contract.payload["supervised_task"]
    evaluator_task = nodes[-1].contract.payload["supervised_task"]
    if model_task not in {SupervisedTask.REGRESSION.value, SupervisedTask.CLASSIFICATION.value}:
        raise ValidationGraphError("first-profile fitted model must declare a supervised scientific task")
    if evaluator_task != model_task:
        raise ValidationGraphError("first-profile evaluator task does not match its fitted model")


def assert_admitted_validation_graph(graph: ValidationGraph, *, require_live_runtime: bool = True) -> None:
    """Fail closed unless ``graph`` remains an admitted first-profile chain.

    ``ValidationGraph`` deliberately has no public constructor.  This second
    check is still required at the execution authority: Python callers can
    forge frozen objects through introspection, and an executor must never
    turn such an object into a second topology or node-admission path.
    """

    if not isinstance(graph, ValidationGraph) or not isinstance(graph.nodes, tuple) or not graph.nodes:
        raise ValidationGraphError("validation graph must contain at least one admitted node")
    if not isinstance(graph.edges, tuple) or any(not isinstance(node, ValidationGraphNode) for node in graph.nodes):
        raise ValidationGraphError("validation graph has malformed admitted records")
    if any(not isinstance(edge, ValidationGraphEdge) for edge in graph.edges):
        raise ValidationGraphError("validation graph has malformed admitted records")
    node_ids = tuple(node.node_id for node in graph.nodes)
    if len(node_ids) != len(set(node_ids)):
        raise ValidationGraphError("validation graph repeats a node ID")
    expected_edges = tuple(_first_profile_edge(source, target) for source, target in zip(graph.nodes, graph.nodes[1:]))
    if graph.edges != expected_edges:
        raise ValidationGraphError("validation graph topology is not the admitted first-profile chain")
    for graph_node in graph.nodes:
        try:
            parameters = json.loads(graph_node.parameters_json)
        except (TypeError, ValueError) as exc:
            raise ValidationGraphError("validation graph node parameters are malformed") from exc
        if not isinstance(parameters, Mapping):
            raise ValidationGraphError("validation graph node parameters must be a JSON object")
        admitted = _admit_contract(
            WorkflowNode(graph_node.node_id, graph_node.operation_id, parameters),
            require_live_runtime=require_live_runtime,
        )
        if admitted != graph_node:
            raise ValidationGraphError("validation graph node no longer matches its admitted execution contract")
    _assert_first_profile_lifecycle_topology(graph.nodes)


def admit_validation_graph(
    nodes: Iterable[WorkflowNode],
    edges: Iterable[WorkflowEdge],
    *,
    require_live_runtime: bool = True,
) -> ValidationGraph:
    """Admit the ordered canonical graph that a fold executor may score.

    The authority consumes the shared preflight result first, so normal Run,
    import, and managed validation agree on typed edge compatibility.  Its own
    additional restrictions are intentionally fail-closed: only exact
    execution-contract nodes with development eligibility may score.
    """

    materialized_nodes = list(nodes)
    materialized_edges = list(edges)
    source_operations = {node.node_id: node.node_type for node in materialized_nodes}
    target_operations = source_operations
    for edge in materialized_edges:
        is_classification_prediction = False
        source_operation = source_operations.get(edge.from_node)
        if source_operation is not None:
            try:
                source_contract = node_registry.get_metadata(source_operation).resolved_execution_contract()
            except KeyError:
                source_contract = None
            is_classification_prediction = bool(
                source_contract is not None
                and source_contract.payload["lifecycle_kind"] == LifecycleKind.FITTED_MODEL.value
                and source_contract.payload["supervised_task"] == SupervisedTask.CLASSIFICATION.value
                and target_operations.get(edge.to_node) == "diagnostics.classification_evaluator"
                and edge.from_output == "predictions"
                and edge.to_input == "default"
            )
        if not is_classification_prediction and (edge.from_output != "default" or edge.to_input != "default"):
            raise ValidationGraphError("first validation profile admits only its declared default-port edges")
    node_ids = [node.node_id for node in materialized_nodes]
    if len(node_ids) != len(set(node_ids)):
        raise ValidationGraphError("candidate graph repeats a node ID")
    # Validate the closed Runner-facing parameter projection before generic
    # canvas preflight.  A locally tolerated but ignored setting must never
    # reach a later graph, capability, or worker boundary.
    admitted_by_id = {
        node.node_id: _admit_contract(node, require_live_runtime=require_live_runtime) for node in materialized_nodes
    }
    preflight = _preflight_with_capability_source(materialized_nodes, materialized_edges)
    errors = [
        issue
        for issue in preflight.issues
        if issue.level == "error" and (require_live_runtime or issue.code != "spectrochempy_unavailable")
    ]
    if errors:
        details = "; ".join(issue.code for issue in errors)
        raise ValidationGraphError(f"candidate DAG failed shared preflight: {details}")
    try:
        order = topological_sort(node_ids, _graph_edges(materialized_edges))
    except ValueError as exc:
        raise ValidationGraphError("candidate graph must be acyclic") from exc
    incoming = {node_id: 0 for node_id in node_ids}
    outgoing = {node_id: 0 for node_id in node_ids}
    for edge in materialized_edges:
        incoming[edge.to_node] += 1
        outgoing[edge.from_node] += 1
    if any(count > 1 for count in incoming.values()) or any(count > 1 for count in outgoing.values()):
        raise ValidationGraphError("first validation profile admits a single unbranched scientific path")
    roots = [node_id for node_id, count in incoming.items() if count == 0]
    terminals = [node_id for node_id, count in outgoing.items() if count == 0]
    if len(roots) != 1 or len(terminals) != 1 or len(materialized_edges) != len(node_ids) - 1:
        raise ValidationGraphError("first validation profile requires one connected scientific path")
    admitted = tuple(admitted_by_id[node_id] for node_id in order)
    if not admitted:
        raise ValidationGraphError("candidate graph must contain at least one scientific node")
    _assert_first_profile_lifecycle_topology(admitted)
    # Store the exact typed operation path in execution order—not lexical
    # node-ID order—so the identity is stable across input-edge ordering while
    # still naming the output the scientist's canvas sends to its evaluator.
    immutable_edges = tuple(_first_profile_edge(source, target) for source, target in zip(admitted, admitted[1:]))
    normalized_supplied_edges = tuple(
        ValidationGraphEdge(edge.from_node, edge.to_node, edge.from_output, edge.to_input)
        for edge in materialized_edges
    )
    if len(normalized_supplied_edges) != len(immutable_edges) or set(normalized_supplied_edges) != set(immutable_edges):
        raise ValidationGraphError("candidate DAG does not use the admitted typed operation path")
    graph = object.__new__(ValidationGraph)
    object.__setattr__(graph, "nodes", admitted)
    object.__setattr__(graph, "edges", immutable_edges)
    return graph


__all__ = [
    "ValidationContractError",
    "ValidationGraph",
    "ValidationGraphEdge",
    "ValidationGraphError",
    "ValidationGraphNode",
    "ValidationRuntimeAttestationError",
    "assert_admitted_validation_graph",
    "admit_validation_graph",
    "managed_validation_parameter_options",
    "validation_graph_from_dict",
]
