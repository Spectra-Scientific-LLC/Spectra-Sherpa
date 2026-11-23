"""Canonical procedures: a governed template is the single procedure definition.

A guided journey or a skill builds its workflow from the template instead of
declaring its own graph, so every surface runs the same nodes, parameters and
wiring. Only the parameters the template declares as tunable may change.
"""

from __future__ import annotations

import copy
from functools import lru_cache
from typing import Any


class ProcedureRefused(ValueError):
    """The requested procedure or parameter change is not part of the canonical definition."""


@lru_cache(maxsize=1)
def _governed_templates() -> dict[str, dict[str, Any]]:
    from spectra_sherpa.app.core.template_loader import TemplateLoader

    return {
        template["slug"]: template
        for template in TemplateLoader().load_all()
        if template["template_data"].get("governed_procedure") and template["template_data"].get("status") == "ready"
    }


def governed_procedure_ids() -> tuple[str, ...]:
    return tuple(sorted(_governed_templates()))


def build_procedure(
    procedure_id: str,
    *,
    source_binding: Any,
    parameters: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Return ``{"name", "nodes", "edges"}`` for one governed template.

    ``source_binding`` is an admitted ``DataBindingSpec``. ``parameters`` maps a
    node_id to the tunable parameters to set on it; anything else is refused.
    """
    from spectra_sherpa.app.api.v1.routes.workflow_templates import _apply_binding_to_template_source

    template = _governed_templates().get(procedure_id)
    if template is None:
        raise ProcedureRefused(f"Unknown governed procedure {procedure_id!r}")
    data = copy.deepcopy(template["template_data"])
    governed = data["governed_procedure"]
    tunable = {node_id: set(names) for node_id, names in governed.get("tunable", {}).items()}
    nodes = []
    for node in data["nodes"]:
        node.pop("example_binding", None)
        if node["node_id"] == governed["source_node"]:
            _apply_binding_to_template_source(node, source_binding)
        nodes.append(node)
    by_id = {node["node_id"]: node for node in nodes}
    for node_id, values in (parameters or {}).items():
        allowed = tunable.get(node_id, set())
        if node_id not in by_id or not set(values) <= allowed:
            raise ProcedureRefused(
                f"{procedure_id} does not allow changing {sorted(set(values) - allowed)} on {node_id}"
            )
        by_id[node_id]["parameters"] = {**by_id[node_id].get("parameters", {}), **values}
    edges = [
        {
            "from_node_id": edge["from_node_id"],
            "from_output": edge.get("from_output", "default"),
            "to_node_id": edge["to_node_id"],
            "to_input": edge.get("to_input", "default"),
        }
        for edge in data["edges"]
    ]
    return {"name": template["name"], "nodes": nodes, "edges": edges}
