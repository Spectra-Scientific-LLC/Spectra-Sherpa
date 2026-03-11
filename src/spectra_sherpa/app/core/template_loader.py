"""
Template loader for declarative YAML workflow templates.

Loads templates from ``spectra_sherpa/data/templates/*.yaml`` using
``importlib.resources`` so that templates are discoverable both in
development checkouts and installed wheels.

Every template is validated against the Pydantic schema defined in
:mod:`spectra_sherpa.app.schemas.template_schema`.
"""

from __future__ import annotations

import importlib.resources
import logging
from typing import Any

import yaml

from spectra_sherpa.app.schemas.template_schema import (
    TemplateCategoryFile,
    TemplateFile,
)

logger = logging.getLogger(__name__)

# Supported schema versions — bump this when the schema evolves.
SUPPORTED_SCHEMA_VERSIONS = {1}

# Package path for importlib.resources
_TEMPLATES_PACKAGE = "spectra_sherpa.data"


class TemplateLoader:
    """Loads, validates, and returns declarative YAML workflow templates.

    Parameters
    ----------
    package : str
        Dotted package path containing the ``templates/`` subdirectory.
        Defaults to ``spectra_sherpa.data``.
    """

    def __init__(self, package: str = _TEMPLATES_PACKAGE) -> None:
        self._package = package
        self._templates_dir = importlib.resources.files(package) / "templates"

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def load_all(self) -> list[dict[str, Any]]:
        """Load all ``*.yaml`` template files, validate, and return as dicts.

        Returns the same ``list[dict]`` format as the legacy
        ``WORKFLOW_TEMPLATES`` constant so the startup sync logic in
        ``ensure_workflow_templates()`` requires zero changes.

        Raises
        ------
        ValueError
            If any template file fails validation.
        """
        templates: list[dict[str, Any]] = []
        errors: list[str] = []

        for resource in sorted(self._templates_dir.iterdir(), key=lambda r: r.name):
            name = resource.name
            if not name.endswith(".yaml") or name.startswith("_"):
                continue

            try:
                raw = yaml.safe_load(resource.read_text(encoding="utf-8"))
            except yaml.YAMLError as exc:
                errors.append(f"{name}: invalid YAML — {exc}")
                continue

            if not isinstance(raw, dict):
                errors.append(f"{name}: top-level value must be a mapping")
                continue

            # Schema version gate
            sv = raw.get("schema_version")
            if sv not in SUPPORTED_SCHEMA_VERSIONS:
                errors.append(f"{name}: unsupported schema_version {sv!r} " f"(supported: {SUPPORTED_SCHEMA_VERSIONS})")
                continue

            # Validate against Pydantic model
            file_errors = self._validate_one(raw, filename=name)
            if file_errors:
                errors.extend(file_errors)
                continue

            # Convert to the dict shape expected by ensure_workflow_templates()
            validated = TemplateFile.model_validate(raw)
            templates.append(self._to_legacy_dict(validated))

        if errors:
            msg = "Template validation failed:\n" + "\n".join(f"  • {e}" for e in errors)
            raise ValueError(msg)

        logger.info("Loaded %d workflow templates from YAML", len(templates))
        return templates

    def load_categories(self) -> dict[str, Any]:
        """Load ``_categories.yaml`` and return validated category metadata.

        Returns
        -------
        dict[str, dict]
            Mapping of category slug → category metadata dict.
        """
        cat_resource = self._templates_dir / "_categories.yaml"
        raw = yaml.safe_load(cat_resource.read_text(encoding="utf-8"))
        validated = TemplateCategoryFile.model_validate(raw)
        return {slug: entry.model_dump() for slug, entry in validated.categories.items()}

    def validate_all(self) -> list[str]:
        """Validate all templates and return a list of error strings.

        Returns an empty list if everything is valid.
        """
        all_errors: list[str] = []
        slugs_seen: set[str] = set()

        # Load category slugs for cross-reference
        try:
            categories = self.load_categories()
            valid_categories = set(categories.keys())
        except Exception as exc:
            all_errors.append(f"_categories.yaml: {exc}")
            valid_categories = set()

        for resource in sorted(self._templates_dir.iterdir(), key=lambda r: r.name):
            name = resource.name
            if not name.endswith(".yaml") or name.startswith("_"):
                continue

            try:
                raw = yaml.safe_load(resource.read_text(encoding="utf-8"))
            except yaml.YAMLError as exc:
                all_errors.append(f"{name}: invalid YAML — {exc}")
                continue

            if not isinstance(raw, dict):
                all_errors.append(f"{name}: top-level value must be a mapping")
                continue

            sv = raw.get("schema_version")
            if sv not in SUPPORTED_SCHEMA_VERSIONS:
                all_errors.append(
                    f"{name}: unsupported schema_version {sv!r} " f"(supported: {SUPPORTED_SCHEMA_VERSIONS})"
                )
                continue

            file_errors = self._validate_one(raw, filename=name)
            all_errors.extend(file_errors)

            # Cross-template checks
            slug = raw.get("slug", "")
            if slug in slugs_seen:
                all_errors.append(f"{name}: duplicate slug '{slug}'")
            slugs_seen.add(slug)

            cat = raw.get("category", "")
            if valid_categories and cat not in valid_categories:
                all_errors.append(f"{name}: category '{cat}' not found in _categories.yaml")

        return all_errors

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _validate_one(self, raw: dict, *, filename: str) -> list[str]:
        """Validate a single template dict against the Pydantic schema.

        Also performs structural checks that go beyond type validation:
        node ID uniqueness, edge references, and data_roles bindings.
        """
        errors: list[str] = []

        # Pydantic parse
        try:
            parsed = TemplateFile.model_validate(raw)
        except Exception as exc:
            errors.append(f"{filename}: schema validation failed — {exc}")
            return errors

        td = parsed.template_data
        node_ids = {n.node_id for n in td.nodes}

        # Check for duplicate node_ids
        seen_ids: set[str] = set()
        for n in td.nodes:
            if n.node_id in seen_ids:
                errors.append(f"{filename}: duplicate node_id '{n.node_id}'")
            seen_ids.add(n.node_id)

        # Check edges reference valid nodes
        for edge in td.edges:
            if edge.from_node_id not in node_ids:
                errors.append(f"{filename}: edge references unknown node_id " f"'{edge.from_node_id}'")
            if edge.to_node_id not in node_ids:
                errors.append(f"{filename}: edge references unknown node_id " f"'{edge.to_node_id}'")

        # Check data_roles node_bindings reference valid node_ids
        for role_name, role in td.data_roles.items():
            if role.node_binding not in node_ids:
                errors.append(
                    f"{filename}: data_roles.{role_name}.node_binding "
                    f"'{role.node_binding}' references unknown node_id"
                )

        # Check node types exist in registry (deferred — only when registry
        # is available, not at import time)
        try:
            from spectra_sherpa.app.services.dag.node_base import node_registry

            for n in td.nodes:
                if n.node_type not in node_registry:
                    errors.append(f"{filename}: node '{n.node_id}' has unknown " f"node_type '{n.node_type}'")
        except ImportError:
            pass  # Registry not available (e.g. in lightweight test context)

        return errors

    @staticmethod
    def _to_legacy_dict(template: TemplateFile) -> dict[str, Any]:
        """Convert a validated TemplateFile back to the dict shape
        expected by ``ensure_workflow_templates()``.

        This preserves backward compatibility: the startup sync code
        does ``WorkflowTemplate(**template_data)`` which expects the
        flat dict with ``name``, ``slug``, ``category``, ``template_data``, etc.
        """
        td = template.template_data
        return {
            "name": template.name,
            "slug": template.slug,
            "description": template.description,
            "category": template.category,
            "is_active": template.is_active,
            "template_data": {
                "nodes": [n.model_dump() for n in td.nodes],
                "edges": [e.model_dump() for e in td.edges],
                "canvas_state": td.canvas_state,
                "data_roles": {k: v.model_dump(exclude_none=True) for k, v in td.data_roles.items()},
                "status": template.status,
            },
        }


# ---------------------------------------------------------------------------
# CLI entry point for validation
# ---------------------------------------------------------------------------


def _cli_validate() -> None:
    """CLI entry point: ``spectra-sherpa validate-templates``."""
    import sys

    # Match application startup behavior so plugin-backed templates validate
    # against the same node registry contents users get at runtime.
    from spectra_sherpa.app.services.plugin_loader import discover_plugins

    discover_plugins()

    loader = TemplateLoader()
    errors = loader.validate_all()

    if errors:
        print("Template validation FAILED:", file=sys.stderr)
        for err in errors:
            print(f"  • {err}", file=sys.stderr)
        sys.exit(1)
    else:
        # Also load to get count
        templates = loader.load_all()
        categories = loader.load_categories()
        print(f"All {len(templates)} templates valid across {len(categories)} categories.")
        sys.exit(0)


if __name__ == "__main__":
    _cli_validate()
