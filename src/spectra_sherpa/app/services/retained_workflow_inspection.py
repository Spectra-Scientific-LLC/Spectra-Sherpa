"""Read saved graphs without constructing nodes or granting execution authority."""

from __future__ import annotations

import json
from typing import Any

from spectra_sherpa.app.schemas.retained_workflow import RetainedWorkflowInspection
from spectra_sherpa.app.services.dag.pack_requirements import (
    PackBindingAdmissionError,
    require_matching_pack_binding,
)
from spectra_sherpa.app.services.pack_requirements import read_stored_pack_binding
from spectra_sherpa.core.retained_graph import inspect_retained_graph


def inspect_saved_workflow(workflow: Any, *, registry=None) -> RetainedWorkflowInspection | None:
    """Compare installed identity only; parameter and entitlement admission are separate."""
    if registry is None:
        from spectra_sherpa.app.services.dag.node_base import node_registry

        registry = node_registry
    payload = {
        "name": workflow.name,
        "pack_binding": workflow.pack_binding,
        "nodes": [
            {
                "node_id": node.node_id,
                "node_type": node.node_type,
                "label": node.label,
                "parameters": node.parameters,
            }
            for node in workflow.nodes
        ],
        "edges": [
            {
                "from_node_id": edge.from_node_id,
                "to_node_id": edge.to_node_id,
                "from_output": edge.from_output,
                "to_input": edge.to_input,
            }
            for edge in workflow.edges
        ],
    }
    unavailable = []
    for node in workflow.nodes:
        try:
            registry.get_metadata(node.node_type)
        except KeyError:
            # Include legacy unknown identities, not only the reserved pack prefix.
            unavailable.append(node.node_id)
    binding_unavailable = False
    try:
        require_matching_pack_binding(
            payload["nodes"], read_stored_pack_binding(workflow.pack_binding), registry=registry
        )
    except (PackBindingAdmissionError, ValueError):
        binding_unavailable = True
    if not unavailable and not binding_unavailable:
        # Preserve ordinary editable graph behavior; inert display bounds apply
        # only to the retained inspection projection, not legacy executable APIs.
        return None
    graph = inspect_retained_graph(json.dumps(payload, ensure_ascii=False, allow_nan=False).encode("utf-8"))
    return RetainedWorkflowInspection(
        graph=graph,
        unavailable_node_ids=tuple(unavailable),
        binding_unavailable=binding_unavailable,
    )
