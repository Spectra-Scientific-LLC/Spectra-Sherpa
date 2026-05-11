"""
Bulk smoke test for every shipped, production-ready workflow template.

The YAML templates under ``src/spectra_sherpa/data/templates/`` are
auto-loaded into the DB on startup via ``template_loader.py`` and exposed
to users via ``GET /workflow-templates``.  ``TemplateLoader`` already
enforces a Pydantic-level schema gate at load time, but it does NOT verify
that every ``node_type`` referenced in a template actually exists in the
runtime node registry — a typo'd or renamed node type silently passes
loader validation and only surfaces when a user clicks the template, in
production.

This module closes that gap with a parameterized check that runs over
every "ready" template (those that a user can actually pick) and asserts:

- The template loads via ``TemplateLoader`` (no YAML / schema errors).
- ``template_data`` carries a non-empty ``nodes`` list and a ``edges`` list.
- Every ``node_type`` in the template's nodes is registered in
  ``spectra_sherpa.app.services.dag.node_base.node_registry``.
- Node IDs within a single template are unique (no duplicate ``node_id``).
- Every edge endpoint refers to a known node_id.
- Required top-level fields (``name``, ``slug``, ``description``,
  ``category``, ``is_active``) are present and non-empty.

Failures are parameterized by template slug so a regression points at the
specific YAML file that needs attention.
"""

from __future__ import annotations

from typing import Any

import pytest

from spectra_sherpa.app.core.template_loader import TemplateLoader
from spectra_sherpa.app.services.dag.node_base import node_registry


def _is_ready(template: dict[str, Any]) -> bool:
    """Return True for templates exposed to users by default.

    Mirrors ``_template_status`` in ``routes/workflow_templates.py``:
    untagged templates default to "ready"; only explicit ``status: wip``
    is filtered out by the listing endpoint.
    """
    template_data = template.get("template_data") or {}
    return template_data.get("status") != "wip"


def _load_ready_templates() -> list[dict[str, Any]]:
    """Load every shipped template, then narrow to the ready subset."""
    return [t for t in TemplateLoader().load_all() if _is_ready(t)]


_READY_TEMPLATES: list[dict[str, Any]] = _load_ready_templates()


def _ids(templates: list[dict[str, Any]]) -> list[str]:
    """pytest-friendly ids — show template slug on failure."""
    return [t.get("slug") or t.get("name", "<no-slug>") for t in templates]


def test_at_least_one_ready_template_ships() -> None:
    """Sanity guard: a release with zero ready templates is almost certainly a bug."""
    assert len(_READY_TEMPLATES) > 0, (
        "TemplateLoader returned no ready templates. "
        "Either every shipped template is marked wip, or template loading failed silently."
    )


@pytest.mark.parametrize("template", _READY_TEMPLATES, ids=_ids(_READY_TEMPLATES))
def test_ready_template_has_required_top_level_fields(template: dict[str, Any]) -> None:
    """Every ready template must have a name, slug, description, category, and be active."""
    assert template.get("name"), "template is missing a non-empty name"
    assert template.get("slug"), "template is missing a non-empty slug"
    assert template.get("description"), "template is missing a non-empty description"
    assert template.get("category"), "template is missing a non-empty category"
    assert template.get("is_active") is True, "template is not marked is_active=true"


@pytest.mark.parametrize("template", _READY_TEMPLATES, ids=_ids(_READY_TEMPLATES))
def test_ready_template_data_structurally_valid(template: dict[str, Any]) -> None:
    """``template_data`` must be a dict with non-empty nodes and an edges list."""
    template_data = template.get("template_data")
    assert isinstance(template_data, dict), "template_data must be a dict"

    nodes = template_data.get("nodes")
    edges = template_data.get("edges")
    assert isinstance(nodes, list) and len(nodes) > 0, "nodes must be a non-empty list"
    assert isinstance(edges, list), "edges must be a list (may be empty for single-node templates)"


@pytest.mark.parametrize("template", _READY_TEMPLATES, ids=_ids(_READY_TEMPLATES))
def test_ready_template_node_types_registered(template: dict[str, Any]) -> None:
    """Every node_type in a ready template must exist in the node registry.

    This is the primary regression guard: a typo'd or renamed node type
    that slips past Pydantic loader validation will fail here, surfaced
    by template slug, instead of waiting to fail in production when a
    user clicks the template.
    """
    template_data = template.get("template_data") or {}
    nodes = template_data.get("nodes") or []
    unknown_types = sorted(
        {n["node_type"] for n in nodes if isinstance(n, dict) and n.get("node_type") not in node_registry}
    )
    assert not unknown_types, (
        f"Template '{template.get('slug')}' references node types not present in node_registry: "
        f"{unknown_types}. Either the template needs updating or the node was removed/renamed."
    )


@pytest.mark.parametrize("template", _READY_TEMPLATES, ids=_ids(_READY_TEMPLATES))
def test_ready_template_node_ids_unique(template: dict[str, Any]) -> None:
    """Two nodes with the same node_id in one template would break edge resolution."""
    template_data = template.get("template_data") or {}
    nodes = template_data.get("nodes") or []
    node_ids = [n.get("node_id") for n in nodes if isinstance(n, dict) and n.get("node_id")]
    duplicates = sorted({nid for nid in node_ids if node_ids.count(nid) > 1})
    assert not duplicates, f"Template '{template.get('slug')}' has duplicate node_ids: {duplicates}"


@pytest.mark.parametrize("template", _READY_TEMPLATES, ids=_ids(_READY_TEMPLATES))
def test_ready_template_edges_reference_existing_nodes(template: dict[str, Any]) -> None:
    """Every edge endpoint must point at a node defined in the same template."""
    template_data = template.get("template_data") or {}
    nodes = template_data.get("nodes") or []
    edges = template_data.get("edges") or []

    node_ids = {n.get("node_id") for n in nodes if isinstance(n, dict) and n.get("node_id")}
    dangling: list[str] = []
    for edge in edges:
        if not isinstance(edge, dict):
            continue
        for endpoint_key in ("from_node_id", "to_node_id"):
            endpoint = edge.get(endpoint_key)
            if endpoint and endpoint not in node_ids:
                dangling.append(f"{endpoint_key}={endpoint!r}")
    assert (
        not dangling
    ), f"Template '{template.get('slug')}' has edge endpoints that don't match any node_id: {dangling}"
