"""Portable, content-addressed workflow specifications for the public SDK.

This module describes the execution-semantic DAG exchanged by the visual
workbench, Python SDK, evidence manifests, and a later Harness Runner.  It is
not an execution engine and carries no UI layout or database identifiers.
"""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Mapping, Sequence

if TYPE_CHECKING:
    from .canonical_capsule import CanonicalWorkflowCapsule

WORKFLOW_SCHEMA_VERSION = "spectra-sherpa-workflow/1"


class WorkflowSchemaError(ValueError):
    """Raised when a portable workflow cannot be validated."""


@dataclass(frozen=True)
class WorkflowSpec:
    """A validated, canonical, content-addressed execution workflow."""

    payload: dict[str, Any]
    workflow_digest: str

    def canonical_bytes(self) -> bytes:
        return _canonical_json(self.payload)

    def as_dict(self) -> dict[str, Any]:
        return {**deepcopy(self.payload), "workflow_digest": self.workflow_digest}

    @classmethod
    def from_dict(cls, manifest: Mapping[str, Any]) -> "WorkflowSpec":
        digest = manifest.get("workflow_digest")
        if not isinstance(digest, str):
            raise WorkflowSchemaError("workflow manifest requires workflow_digest")
        payload = {key: deepcopy(value) for key, value in manifest.items() if key != "workflow_digest"}
        normalized = _validate_and_normalize(payload)
        actual = _digest(normalized)
        if actual != digest:
            raise WorkflowSchemaError(f"workflow digest mismatch: expected {digest}, got {actual}")
        return cls(payload=normalized, workflow_digest=actual)


def workflow_spec(*, nodes: Sequence[Mapping[str, Any]], edges: Sequence[Mapping[str, Any]]) -> WorkflowSpec:
    """Create a version-1 portable workflow from an execution DAG.

    Nodes require ``node_id`` and ``node_type``; parameters default to an empty
    object. Edges require source/target node IDs; omitted ports normalize to
    ``"default"``. Node order and visual-only fields do not affect the digest.
    """
    payload = _validate_and_normalize(
        {
            "schema_version": WORKFLOW_SCHEMA_VERSION,
            "nodes": [deepcopy(dict(node)) for node in nodes],
            "edges": [deepcopy(dict(edge)) for edge in edges],
        }
    )
    return WorkflowSpec(payload=payload, workflow_digest=_digest(payload))


def verify_workflow(manifest: WorkflowSpec | Mapping[str, Any]) -> bool:
    """Return whether a portable workflow has a valid schema and digest."""
    try:
        if isinstance(manifest, WorkflowSpec):
            return _digest(_validate_and_normalize(manifest.payload)) == manifest.workflow_digest
        WorkflowSpec.from_dict(manifest)
    except (TypeError, ValueError, WorkflowSchemaError):
        return False
    return True


def _validate_and_normalize(payload: Mapping[str, Any]) -> dict[str, Any]:
    required = {"schema_version", "nodes", "edges"}
    missing, extra = sorted(required - set(payload)), sorted(set(payload) - required)
    if missing or extra:
        raise WorkflowSchemaError(f"invalid workflow fields: missing={missing}, extra={extra}")
    if payload["schema_version"] != WORKFLOW_SCHEMA_VERSION:
        raise WorkflowSchemaError(f"unsupported workflow schema version: {payload['schema_version']!r}")

    normalized_nodes: list[dict[str, Any]] = []
    node_ids: set[str] = set()
    for index, node in enumerate(_require_list(payload["nodes"], "nodes")):
        if not isinstance(node, Mapping):
            raise WorkflowSchemaError(f"nodes[{index}] must be an object")
        node_id, node_type = node.get("node_id"), node.get("node_type")
        if not isinstance(node_id, str) or not node_id:
            raise WorkflowSchemaError(f"nodes[{index}] requires a non-empty node_id")
        if node_id in node_ids:
            raise WorkflowSchemaError(f"duplicate workflow node_id: {node_id!r}")
        if not isinstance(node_type, str) or not node_type:
            raise WorkflowSchemaError(f"nodes[{index}] requires a non-empty node_type")
        parameters = node.get("parameters", {})
        if not isinstance(parameters, Mapping):
            raise WorkflowSchemaError(f"nodes[{index}].parameters must be an object")
        node_ids.add(node_id)
        normalized_nodes.append({"node_id": node_id, "node_type": node_type, "parameters": deepcopy(dict(parameters))})

    normalized_edges: list[dict[str, str]] = []
    seen_edges: set[tuple[str, str, str, str]] = set()
    for index, edge in enumerate(_require_list(payload["edges"], "edges")):
        if not isinstance(edge, Mapping):
            raise WorkflowSchemaError(f"edges[{index}] must be an object")
        source, target = edge.get("from_node_id"), edge.get("to_node_id")
        output, input_port = edge.get("from_output", "default"), edge.get("to_input", "default")
        if not all(isinstance(value, str) and value for value in (source, target, output, input_port)):
            raise WorkflowSchemaError(f"edges[{index}] requires non-empty node ids and ports")
        if source not in node_ids or target not in node_ids:
            raise WorkflowSchemaError(f"edges[{index}] references a node not present in workflow")
        edge_key = (source, target, output, input_port)
        if edge_key in seen_edges:
            raise WorkflowSchemaError(f"duplicate workflow edge: {edge_key!r}")
        seen_edges.add(edge_key)
        normalized_edges.append(
            {"from_node_id": source, "to_node_id": target, "from_output": output, "to_input": input_port}
        )

    _assert_acyclic(node_ids, normalized_edges)
    normalized = {
        "schema_version": WORKFLOW_SCHEMA_VERSION,
        "nodes": sorted(normalized_nodes, key=lambda node: node["node_id"]),
        "edges": sorted(
            normalized_edges,
            key=lambda edge: (edge["from_node_id"], edge["to_node_id"], edge["from_output"], edge["to_input"]),
        ),
    }
    try:
        _canonical_json(normalized)
    except (TypeError, ValueError) as exc:
        raise WorkflowSchemaError(f"workflow is not canonical-JSON serializable: {exc}") from exc
    _admit_current_registry(normalized["nodes"], normalized["edges"])
    return normalized


def _admit_current_registry(nodes: list[dict[str, Any]], edges: list[dict[str, str]]) -> None:
    """Bind public SDK construction to the same registry as saved workflows."""

    # Import lazily so importing the SDK facade does not eagerly load every
    # scientific runtime. Construction and verification are authority-bearing
    # operations, however, and must reject retired or unknown node identities.
    import spectra_sherpa.app.services.dag.nodes  # noqa: F401
    from spectra_sherpa.app.services.dag.saved_graph_admission import (
        SavedGraphAdmissionError,
        admit_saved_workflow_graph,
    )

    try:
        admit_saved_workflow_graph(nodes, edges, current_graph=True)
    except SavedGraphAdmissionError as exc:
        raise WorkflowSchemaError(f"workflow is not admitted by the current canonical registry: {exc}") from exc


def _assert_acyclic(node_ids: set[str], edges: Sequence[Mapping[str, str]]) -> None:
    dependencies = {node_id: 0 for node_id in node_ids}
    successors: dict[str, list[str]] = {node_id: [] for node_id in node_ids}
    for edge in edges:
        source, target = edge["from_node_id"], edge["to_node_id"]
        dependencies[target] += 1
        successors[source].append(target)
    ready = sorted(node_id for node_id, degree in dependencies.items() if degree == 0)
    visited = 0
    while ready:
        node_id = ready.pop()
        visited += 1
        for target in successors[node_id]:
            dependencies[target] -= 1
            if dependencies[target] == 0:
                ready.append(target)
    if visited != len(node_ids):
        raise WorkflowSchemaError("workflow graph must be acyclic")


def _require_list(value: Any, name: str) -> list[Any]:
    if not isinstance(value, list):
        raise WorkflowSchemaError(f"{name} must be a list")
    return value


def _canonical_json(payload: Mapping[str, Any]) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode(
        "utf-8"
    )


def _digest(payload: Mapping[str, Any]) -> str:
    return hashlib.sha256(_canonical_json(payload)).hexdigest()


def load(source: Mapping[str, Any] | str | Path | bytes) -> CanonicalWorkflowCapsule:
    """Load and verify the current canonical typed-DAG capsule.

    ``source`` may be a mapping, bounded JSON bytes, or an explicit local
    path. URLs and capsule-directed locations are not supported. Prototype
    capsule versions are intentionally rejected rather than translated.
    """
    from .canonical_capsule import load_canonical_capsule

    return load_canonical_capsule(source)


__all__ = [
    "WORKFLOW_SCHEMA_VERSION",
    "WorkflowSchemaError",
    "WorkflowSpec",
    "load",
    "verify_workflow",
    "workflow_spec",
]
