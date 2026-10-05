from __future__ import annotations

import spectra_sherpa.app.services.dag.nodes  # noqa: F401
from spectra_sherpa.app.services.dag.node_base import node_registry


def test_workflow_node_upper_bounds_publish_their_basis():
    unexplained = []
    for metadata in node_registry.list_nodes():
        for parameter in metadata.parameters:
            if parameter.max_value is not None and not (parameter.max_value_reason or "").strip():
                unexplained.append(f"{metadata.node_type}.{parameter.name}={parameter.max_value}")

    assert unexplained == []
