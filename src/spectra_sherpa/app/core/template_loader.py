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

import yaml  # type: ignore[import-untyped]

from spectra_sherpa.app.schemas.template_schema import (
    TemplateCategoryFile,
    TemplateEdge,
    TemplateFile,
    TemplateNode,
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
                errors.append(f"{name}: unsupported schema_version {sv!r} (supported: {SUPPORTED_SCHEMA_VERSIONS})")
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
                all_errors.append(f"{name}: unsupported schema_version {sv!r} (supported: {SUPPORTED_SCHEMA_VERSIONS})")
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
        node_ids = self._validate_graph(
            td.nodes,
            td.edges,
            filename=filename,
            graph_name="scientist workflow",
            errors=errors,
        )

        # Check data_roles node_bindings reference valid node_ids
        for role_name, role in td.data_roles.items():
            if role.node_binding not in node_ids:
                errors.append(
                    f"{filename}: data_roles.{role_name}.node_binding '{role.node_binding}' references unknown node_id"
                )

        canonical_project = td.canonical_project
        if canonical_project is not None:
            candidate = canonical_project.managed_candidate
            candidate_ids = self._validate_graph(
                candidate.nodes,
                candidate.edges,
                filename=filename,
                graph_name="managed candidate",
                errors=errors,
            )
            source_nodes = [node for node in candidate.nodes if node.node_id == candidate.source_node_id]
            if len(source_nodes) != 1 or source_nodes[0].node_type != "data.file_load":
                errors.append(
                    f"{filename}: managed candidate source_node_id '{candidate.source_node_id}' "
                    "must name exactly one data.file_load node"
                )
            scientist_sources = [node for node in td.nodes if node.node_id == candidate.scientist_source_node_id]
            if len(scientist_sources) != 1 or scientist_sources[0].node_type != "data.file_load":
                errors.append(
                    f"{filename}: managed candidate scientist_source_node_id "
                    f"'{candidate.scientist_source_node_id}' must name exactly one scientist-facing "
                    "data.file_load node"
                )
            if candidate.source_node_id not in candidate_ids:
                errors.append(f"{filename}: managed candidate source_node_id is not present in its DAG")

        # Check node types exist in registry (deferred — only when registry
        # is available, not at import time)
        try:
            from spectra_sherpa.app.services.dag.node_base import node_registry

            for n in td.nodes:
                if n.node_type not in node_registry:
                    errors.append(f"{filename}: node '{n.node_id}' has unknown node_type '{n.node_type}'")
            if canonical_project is not None:
                candidate = canonical_project.managed_candidate
                for node in candidate.nodes:
                    if node.node_type not in node_registry:
                        errors.append(
                            f"{filename}: managed candidate node '{node.node_id}' has unknown "
                            f"node_type '{node.node_type}'"
                        )
        except ImportError:
            pass  # Registry not available (e.g. in lightweight test context)

        if canonical_project is not None:
            try:
                from spectra_sherpa.app.lib.reference_datasets import load_reference_dataset_registry

                governed_ids = {entry.dataset_id for entry in load_reference_dataset_registry()}
                declared_ids = canonical_project.qualification_dataset_ids
                if len(declared_ids) != len(set(declared_ids)):
                    errors.append(f"{filename}: canonical project qualification dataset identities must be unique")
                unknown_ids = sorted(set(declared_ids).difference(governed_ids))
                if unknown_ids:
                    errors.append(
                        f"{filename}: canonical project names unknown governed dataset(s): {', '.join(unknown_ids)}"
                    )
            except ImportError:
                pass

        return errors

    @staticmethod
    def _validate_graph(
        nodes: list[TemplateNode],
        edges: list[TemplateEdge],
        *,
        filename: str,
        graph_name: str,
        errors: list[str],
    ) -> set[str]:
        """Apply the same structural rules to every explicitly stored DAG."""

        node_ids = {node.node_id for node in nodes}
        seen_ids: set[str] = set()
        for node in nodes:
            if node.node_id in seen_ids:
                errors.append(f"{filename}: {graph_name} has duplicate node_id '{node.node_id}'")
            seen_ids.add(node.node_id)
        for edge in edges:
            if edge.from_node_id not in node_ids:
                errors.append(f"{filename}: {graph_name} edge references unknown node_id '{edge.from_node_id}'")
            if edge.to_node_id not in node_ids:
                errors.append(f"{filename}: {graph_name} edge references unknown node_id '{edge.to_node_id}'")
        return node_ids

    @staticmethod
    def _to_legacy_dict(template: TemplateFile) -> dict[str, Any]:
        """Convert a validated TemplateFile back to the dict shape
        expected by ``ensure_workflow_templates()``.

        This preserves backward compatibility: the startup sync code
        does ``WorkflowTemplate(**template_data)`` which expects the
        flat dict with ``name``, ``slug``, ``category``, ``template_data``, etc.
        """
        td = template.template_data.model_dump(exclude_none=True)
        td["schema_version"] = template.schema_version
        td["status"] = template.status
        if template.status_detail is not None:
            td["status_detail"] = template.status_detail
        td["data_modalities"] = list(template.data_modalities)
        return {
            "name": template.name,
            "slug": template.slug,
            "description": template.description,
            "category": template.category,
            "is_active": template.is_active,
            "template_data": td,
        }


# ---------------------------------------------------------------------------
# CLI entry point for validation
# ---------------------------------------------------------------------------


def _cli_validate() -> None:
    """CLI entry point: ``spectra-sherpa validate-templates``."""
    import sys

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
