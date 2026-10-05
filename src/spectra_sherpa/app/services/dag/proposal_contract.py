"""One retained scientific proposal contract for ordinary and managed adapters.

Adapters establish actor/request, source custody and spending authority. This
module re-admits the compiled graph and retains the exact scientific definition;
provider arguments are never themselves a receipt or an execution permission.
"""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from .executor import DAGExecutor
from .executor_types import WorkflowEdge, WorkflowNode
from .integrity import compute_workflow_hash
from .node_base import node_registry
from .population_authority import analyze_populations
from .workflow_preflight import preflight_workflow

PROPOSAL_CONTRACT_VERSION = "spectrasherpa-scientific-proposal/1"


def content_digest(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    return hashlib.sha256(encoded).hexdigest()


class ProposalReceipt(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    schema_version: Literal["spectrasherpa-scientific-proposal/1"] = PROPOSAL_CONTRACT_VERSION
    kind: Literal["ordinary_workflow", "managed_campaign"]
    actor_user_id: int = Field(gt=0)
    request_id: str = Field(min_length=1, max_length=128)
    request_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    parent_identity: dict[str, Any]
    source_bindings: dict[str, Any]
    admitted_definitions: list[dict[str, Any]]
    operation_contracts: dict[str, str]
    effective_parameters: dict[str, Any]
    population_receipts: dict[str, Any]
    changes: list[dict[str, Any]]
    disclosure_manifest: list[dict[str, Any]]
    execution: dict[str, Any]
    qualifications: list[str]
    receipt_digest: str = Field(pattern=r"^[0-9a-f]{64}$")


def saved_definition(nodes: Any, edges: Any) -> dict[str, Any]:
    """Read authoritative ORM rows without consulting a stale stored hash."""
    return {
        "nodes": [
            {"node_id": node.node_id, "node_type": node.node_type, "parameters": deepcopy(node.parameters or {})}
            for node in nodes
        ],
        "edges": [
            {
                "from_node_id": edge.from_node_id,
                "to_node_id": edge.to_node_id,
                "from_output": edge.from_output,
                "to_input": edge.to_input,
            }
            for edge in edges
        ],
    }


def definition_digest(definition: dict[str, Any]) -> str:
    content_digest(definition)  # finite JSON, including internal source parameters
    return compute_workflow_hash(definition["nodes"], definition["edges"])


def admit_ordinary_definition(definition: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any], dict[str, str]]:
    """Persist effective defaults and qualify the same graph that will run."""
    normalized = deepcopy(definition)
    executor = DAGExecutor()
    contracts = {}
    for item in normalized["nodes"]:
        node = node_registry.create_node(item["node_type"], item["node_id"], item.get("parameters", {}))
        if node.metadata and node.metadata.input_ports:
            item["parameters"] = deepcopy(node.parameters)
        metadata = node.metadata
        contract = metadata.resolved_execution_contract() if metadata else None
        if contract is None:
            raise ValueError("Proposed operation has no canonical execution contract")
        contracts[item["node_type"]] = contract.digest
        executor.add_node(WorkflowNode(item["node_id"], item["node_type"], item["parameters"]))
    for item in normalized["edges"]:
        executor.add_edge(WorkflowEdge(item["from_node_id"], item["to_node_id"], item["from_output"], item["to_input"]))
    result = preflight_workflow(
        [WorkflowNode(item["node_id"], item["node_type"], item["parameters"]) for item in normalized["nodes"]],
        list(executor.edges),
    )
    if not result.is_valid:
        raise ValueError(
            "Proposed graph failed canonical admission: " + "; ".join(issue.message for issue in result.issues)
        )
    _, populations = analyze_populations(executor.nodes, executor.edges)
    definition_digest(normalized)
    return normalized, populations, contracts


def build_proposal_receipt(
    *,
    kind: Literal["ordinary_workflow", "managed_campaign"],
    actor_user_id: int,
    request_id: str,
    request_digest: str,
    parent_identity: dict[str, Any],
    source_bindings: dict[str, Any],
    admitted_definitions: list[dict[str, Any]],
    operation_contracts: dict[str, str],
    population_receipts: dict[str, Any],
    changes: list[dict[str, Any]],
    effective_parameters: dict[str, Any],
    disclosure_manifest: list[dict[str, Any]] | None = None,
    requests_execution: bool = False,
    qualifications: list[str] | None = None,
) -> dict[str, Any]:
    """Bind both adapters to one closed receipt; approval never comes from a model."""
    payload = {
        "schema_version": PROPOSAL_CONTRACT_VERSION,
        "kind": kind,
        "actor_user_id": actor_user_id,
        "request_id": request_id,
        "request_digest": request_digest,
        "parent_identity": parent_identity,
        "source_bindings": source_bindings,
        "admitted_definitions": admitted_definitions,
        "operation_contracts": operation_contracts,
        "population_receipts": population_receipts,
        "changes": changes,
        "effective_parameters": effective_parameters,
        "disclosure_manifest": disclosure_manifest or [],
        "execution": {
            "state": "draft",
            "requested": requests_execution,
            "requires_campaign_quote": kind == "managed_campaign",
            "definition_digests": [content_digest(item) for item in admitted_definitions],
        },
        "qualifications": qualifications or [],
    }
    payload["receipt_digest"] = content_digest(payload)
    return ProposalReceipt.model_validate(payload).model_dump(mode="json")


def read_proposal_receipt(value: Any) -> ProposalReceipt:
    receipt = ProposalReceipt.model_validate(value)
    if content_digest(receipt.model_dump(mode="json", exclude={"receipt_digest"})) != receipt.receipt_digest:
        raise ValueError("Retained proposal receipt changed")
    return receipt


def admit_managed_definitions(graphs: Any) -> tuple[list[dict[str, Any]], dict[str, str], dict[str, Any]]:
    """The managed adapter retains its stricter fold/capability graph admission."""
    from .validation_graph import ValidationGraph, validation_graph_from_dict

    definitions, contracts, effective = [], {}, {}
    for index, graph in enumerate(graphs):
        if not isinstance(graph, ValidationGraph):
            raise ValueError("Managed proposal requires canonical validation graphs")
        admitted = validation_graph_from_dict(graph.as_dict())
        definitions.append(admitted.as_dict())
        effective[str(index)] = {}
        for node in admitted.nodes:
            contracts[node.operation_id] = node.contract.digest
            effective[str(index)][node.node_id] = dict(node.parameters)
    if not definitions:
        raise ValueError("Managed proposal contains no admitted candidate")
    return definitions, contracts, effective
