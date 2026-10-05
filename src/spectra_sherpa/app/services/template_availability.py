"""Deployment-profile projection of canonical scientific analysis starters."""

from spectra_sherpa.app.models.workflow_template import WorkflowTemplate
from spectra_sherpa.app.services.dag.node_base import node_registry


def template_example_unavailable_reason(template: WorkflowTemplate) -> str | None:
    """Expose provider-dependent examples without advertising a closed import."""
    from spectra_sherpa.app.contracts.project_access import uses_managed_project_access

    if not uses_managed_project_access():
        return None
    for node in (template.template_data or {}).get("nodes", []):
        binding = node.get("example_binding") if isinstance(node, dict) else None
        if isinstance(binding, dict) and binding.get("source") != "synthetic":
            return "Provider example import is unavailable in this deployment. Select an uploaded My Dataset instead."
    return None


def template_admitted_in_profile(template: WorkflowTemplate) -> bool:
    """A starter cannot advertise operations/settings this profile refuses.

    This is availability projection only. Source bindings, project custody and
    the complete effective graph are still authorized at execution.
    """
    from spectra_sherpa.app.contracts.project_access import uses_managed_project_access
    from spectra_sherpa.app.contracts.scientific_access import (
        QUALIFIED_SCIENTIFIC_NODES,
        QUALIFIED_SCIENTIFIC_TEMPLATES,
    )

    if not uses_managed_project_access():
        return True
    if template.slug not in QUALIFIED_SCIENTIFIC_TEMPLATES:
        return False
    payload = template.template_data
    if not isinstance(payload, dict) or not isinstance(payload.get("nodes"), list) or not payload["nodes"]:
        return False
    for node in payload["nodes"]:
        if not isinstance(node, dict) or node.get("node_type") not in QUALIFIED_SCIENTIFIC_NODES:
            return False
        parameters = node.get("parameters", {})
        if not isinstance(parameters, dict):
            return False
        # File identifiers are supplied by the user at launch, not the starter.
        if node["node_type"] in {"data.file_load", "data.collection_load"}:
            continue
        try:
            node_registry.get_metadata(node["node_type"]).canonicalize_managed_parameters(parameters)
        except (KeyError, TypeError, ValueError):
            return False
    return True
