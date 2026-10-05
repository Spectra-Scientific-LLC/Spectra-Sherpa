"""Project workflow-template operations against the active server runtime."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from spectra_sherpa.app.services.dag.node_base import node_registry
from spectra_sherpa.app.services.dag.node_catalog_contract import dependency_readiness


def template_runtime_readiness(template_data: Mapping[str, Any]) -> dict[str, Any]:
    """Return missing operation/dependency evidence for one template graph."""

    unavailable_nodes: list[dict[str, Any]] = []
    blockers: set[str] = set()
    remediation: set[str] = set()
    for node in template_data.get("nodes", []):
        if not isinstance(node, Mapping):
            continue
        node_id = str(node.get("node_id") or "")
        node_type = str(node.get("node_type") or "")
        if not node_type:
            continue
        try:
            readiness = dependency_readiness(node_registry.get_metadata(node_type))
        except KeyError:
            node_blockers = ["unknown_node_type"]
            node_remediation = [f"The server does not provide workflow operation {node_type!r}."]
        else:
            if readiness.ready:
                continue
            node_blockers = list(readiness.blockers)
            node_remediation = list(readiness.remediation)
        blockers.update(node_blockers)
        remediation.update(node_remediation)
        unavailable_nodes.append(
            {
                "node_id": node_id,
                "node_type": node_type,
                "blockers": node_blockers,
            }
        )

    return {
        "ready": not unavailable_nodes,
        "blockers": sorted(blockers),
        "remediation": sorted(remediation),
        "unavailable_nodes": unavailable_nodes,
    }


__all__ = ["template_runtime_readiness"]
