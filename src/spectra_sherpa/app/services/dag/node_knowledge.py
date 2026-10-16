"""Scientist-facing projection of the registry's canonical execution contract."""

from __future__ import annotations

from typing import Any

from .node_base import NodeMetadata


def scientific_method_description(metadata: NodeMetadata) -> dict[str, Any]:
    """Describe registered semantics, never substitute defaults for a saved setting."""
    contract = metadata.resolved_execution_contract()
    if contract is None:
        return {"qualification": "No canonical execution contract is registered"}
    payload = contract.payload
    fields = (
        "operation_id",
        "implementation_id",
        "implementation_version",
        "lifecycle_kind",
        "target_access",
        "supervised_task",
        "sample_effect",
        "feature_effect",
        "axis_effect",
        "unit_effect",
        "deterministic",
        "seed_parameter",
        "help_reference",
    )
    return {
        **{key: payload[key] for key in fields if key in payload},
        "citations": list(payload.get("citations", ())),
        "parameter_notice": "Catalog defaults describe the method, not this workflow's saved or executed settings.",
    }
