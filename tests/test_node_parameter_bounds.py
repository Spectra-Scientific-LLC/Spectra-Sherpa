from __future__ import annotations

import spectra_sherpa.app.services.dag.nodes  # noqa: F401
from spectra_sherpa.app.services.dag.node_base import node_registry


def test_workflow_node_parameters_do_not_advertise_artificial_upper_bounds():
    capped = []
    for metadata in node_registry.list_nodes():
        for parameter in metadata.parameters:
            if parameter.max_value is not None:
                capped.append(f"{metadata.node_type}.{parameter.name}={parameter.max_value}")

    assert capped == []
