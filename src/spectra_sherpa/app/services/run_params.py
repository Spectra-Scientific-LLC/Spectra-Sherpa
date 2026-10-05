"""Workflow parameter snapshots for run reproducibility."""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Iterable

from spectra_sherpa.app.services.dag import node_registry
from spectra_sherpa.app.services.dag.saved_graph_admission import CURRENT_CLASSIFIER_VALIDATION_SEMANTICS
from spectra_sherpa.core.node_identity import canonical_node_type


def build_saved_definition_snapshot(workflow: Any) -> dict[str, Any]:
    """Freeze the exact saved graph; effective defaults belong in params_snapshot."""
    primary_source = getattr(workflow, "primary_data_source", None)
    return deepcopy(
        {
            "schema_version": 1,
            "fold_validation_plan": getattr(workflow, "fold_validation_plan", None),
            "name": workflow.name,
            "integrity_hash": workflow.integrity_hash,
            "data_context": {
                "schema_version": 1,
                "data_source_id": getattr(workflow, "primary_data_source_id", None),
                "source_name": getattr(primary_source, "display_name", None),
                "source_origin": (
                    workflow.data_origin if getattr(workflow, "data_origin", None) in {"current", "example"} else None
                ),
            },
            "nodes": [
                {
                    "node_id": node.node_id,
                    "node_type": canonical_node_type(node.node_type),
                    "label": node.label,
                    "parameters": node.parameters or {},
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
    )


def build_effective_params_snapshot(nodes: Iterable[Any]) -> dict[str, dict[str, Any]]:
    """Return per-node parameters with metadata defaults materialized.

    Saved workflows often store only values the user changed. Run comparison,
    however, needs the effective settings that were actually used. The DAG node
    resolver already defines that contract, so this helper mirrors execution
    by creating the node and asking it to resolve defaults.
    """
    snapshot: dict[str, dict[str, Any]] = {}
    for workflow_node in nodes:
        node_id = getattr(workflow_node, "node_id", None)
        node_type = getattr(workflow_node, "node_type", None)
        explicit_params = getattr(workflow_node, "parameters", None) or {}
        if not node_id:
            continue
        if not node_type:
            if explicit_params:
                snapshot[str(node_id)] = dict(explicit_params)
            continue
        try:
            node = node_registry.create_node(str(node_type), str(node_id), explicit_params)
            resolved = node._resolve_params()
            for key, value in explicit_params.items():
                resolved.setdefault(key, value)
        except Exception:
            resolved = dict(explicit_params)
        if resolved:
            snapshot[str(node_id)] = resolved
    return snapshot


def build_workflow_version_snapshot(workflow: Any) -> dict[str, Any]:
    """Freeze a restorable sheet version, including purpose and canvas state."""
    return deepcopy(
        {
            "classifier_validation_semantics": CURRENT_CLASSIFIER_VALIDATION_SEMANTICS,
            "fold_validation_plan": getattr(workflow, "fold_validation_plan", None),
            "name": workflow.name,
            "description": workflow.description,
            "status": workflow.status,
            "purpose": workflow.purpose,
            "canvas_state": workflow.canvas_state,
            "notes": workflow.notes,
            "integrity_hash": workflow.integrity_hash,
            "technique": workflow.technique,
            "sample_type": workflow.sample_type,
            "tab_color": workflow.tab_color,
            "tab_color_override": workflow.tab_color_override,
            "color_source": workflow.color_source,
            "primary_data_source_id": workflow.primary_data_source_id,
            "data_source_ids": workflow.data_source_ids,
            "created_from_template_name": workflow.created_from_template_name,
            "created_from_template_version": workflow.created_from_template_version,
            "data_origin": workflow.data_origin,
            "sheet_order": workflow.sheet_order,
            "nodes": [
                {
                    "node_id": n.node_id,
                    "node_type": canonical_node_type(n.node_type),
                    "label": n.label,
                    "parameters": n.parameters,
                    "annotation": n.annotation,
                    "position_x": n.position_x,
                    "position_y": n.position_y,
                }
                for n in workflow.nodes
            ],
            "edges": [
                {
                    "from_node_id": e.from_node_id,
                    "to_node_id": e.to_node_id,
                    "from_output": e.from_output,
                    "to_input": e.to_input,
                }
                for e in workflow.edges
            ],
        }
    )
