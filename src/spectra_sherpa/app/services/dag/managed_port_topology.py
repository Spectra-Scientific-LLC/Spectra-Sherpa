"""One versioned port authority for managed graph producers and consumers.

Canonical validation graphs retain their historical logical ``default``
shorthand. Its resolved concrete declaration is separately digest-bound so
changing declaration order cannot silently reinterpret a stored candidate.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence

from spectra_sherpa.app.services.dag.executor_types import WorkflowEdge, WorkflowNode
from spectra_sherpa.app.services.dag.node_base import NodeMetadata, PortMetadata, node_registry

MANAGED_PORT_TOPOLOGY_VERSION = "spectra-managed-port-topology/1"


def resolve_declared_port(
    metadata: NodeMetadata, name: str, direction: str, *, allow_default_alias: bool = True
) -> PortMetadata:
    """Resolve a logical edge, or require an exact concrete materialized port."""

    if direction not in {"input", "output"}:
        raise ValueError("Port direction must be input or output")
    ports = metadata.input_ports if direction == "input" else metadata.output_ports
    for port in ports or ():
        if port.name == name:
            return port
    if allow_default_alias and name == "default" and ports:
        return ports[0]
    raise ValueError(f"{metadata.node_type} has no declared {direction} port {name}")


def declared_classifier_application_data_input(operation_id: str) -> str:
    """Return the locally fitted classifier application's declared data port.

    Application nodes may also expose a ``default`` port for canonical artifact
    replay.  A locally fitted state uses the explicit ``X_new`` declaration
    when present; otherwise the single declared spectra/features input is the
    data port.  This keeps graph producers tied to the registry instead of a
    model-family lookup table.
    """

    metadata = node_registry.get_metadata(operation_id)
    contract = metadata.resolved_execution_contract()
    if (
        metadata.category != "classification"
        or contract is None
        or contract.payload["lifecycle_kind"] != "artifact_application"
    ):
        raise ValueError(f"{operation_id} is not a declared classifier application")
    candidates = [port for port in metadata.input_ports if port.accepted_data_roles]
    explicit = [port for port in candidates if port.name == "X_new"]
    if explicit:
        return explicit[0].name
    required = [port for port in candidates if port.required]
    if len(required) == 1:
        return required[0].name
    if len(candidates) == 1:
        return candidates[0].name
    raise ValueError(f"{operation_id} does not declare one local classifier data input")


def managed_chain_edges(nodes: Sequence[WorkflowNode]) -> list[WorkflowEdge]:
    """Build the existing canonical chain through declared, typed ports."""

    edges = []
    for source, target in zip(nodes, nodes[1:]):
        metadata = node_registry.get_metadata(source.node_type)
        contract = metadata.resolved_execution_contract()
        if contract is None:
            raise ValueError("Managed source has no execution contract")
        output = (
            "predictions"
            if contract.payload["lifecycle_kind"] == "fitted_model"
            and contract.payload["supervised_task"] == "classification"
            and target.node_type == "diagnostics.classification_evaluator"
            else "default"
        )
        resolve_declared_port(metadata, output, "output")
        resolve_declared_port(node_registry.get_metadata(target.node_type), "default", "input")
        edges.append(WorkflowEdge(source.node_id, target.node_id, output, "default"))
    return edges


def _declaration(port: PortMetadata) -> dict[str, object]:
    return {
        "name": port.name,
        "type_ref": port.type_ref,
        "required": port.required,
        "variadic": port.variadic,
        "accepted_data_roles": port.accepted_data_roles,
    }


def managed_port_topology(nodes: Sequence[WorkflowNode], edges: Sequence[WorkflowEdge]) -> dict[str, object]:
    """Bind declaration order and every logical-to-concrete edge resolution."""

    by_id = {node.node_id: node_registry.get_metadata(node.node_type) for node in nodes}
    if len(by_id) != len(nodes):
        raise ValueError("Managed port topology repeats a node identity")
    declarations = [
        {
            "node_id": node.node_id,
            "operation_id": node.node_type,
            "input_ports": [_declaration(port) for port in by_id[node.node_id].input_ports],
            "output_ports": [_declaration(port) for port in by_id[node.node_id].output_ports or ()],
        }
        for node in nodes
    ]
    resolved = []
    for edge in edges:
        if edge.from_node not in by_id or edge.to_node not in by_id:
            raise ValueError("Managed port topology references an unknown node")
        source = resolve_declared_port(by_id[edge.from_node], edge.from_output, "output")
        target = resolve_declared_port(by_id[edge.to_node], edge.to_input, "input")
        resolved.append(
            {
                "from_node": edge.from_node,
                "to_node": edge.to_node,
                "from_output": edge.from_output,
                "to_input": edge.to_input,
                "resolved_output": source.name,
                "resolved_input": target.name,
            }
        )
    identity = {"schema_version": MANAGED_PORT_TOPOLOGY_VERSION, "nodes": declarations, "edges": resolved}
    encoded = json.dumps(identity, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode(
        "utf-8"
    )
    return {**identity, "topology_digest": hashlib.sha256(encoded).hexdigest()}
