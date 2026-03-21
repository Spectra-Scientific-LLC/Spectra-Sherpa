"""
Template contract test suite.

Validates every declarative YAML template against the formal Pydantic
schema and structural invariants.  These tests ensure that:

1. Every YAML file parses and validates against ``TemplateFile``.
2. Every node_type in every template exists in the NodeRegistry.
3. Every edge references valid node_ids.
4. Every ``data_roles`` node_binding references a ``data.source`` node.
5. No duplicate slugs across the template set.
6. Every template category exists in ``_categories.yaml``.
7. ``data_roles`` node_bindings are valid and role_types are from the enum.
8. ``data_roles`` binding_mode values are valid.
9. Templates are discoverable via ``importlib.resources``.

Self-contained — no database, no network.

Run with:
    poetry run pytest tests/test_template_contracts.py -v --no-cov
"""

from __future__ import annotations

import importlib.resources

import pytest
import yaml

from spectra_sherpa.app.core.template_loader import TemplateLoader
from spectra_sherpa.app.schemas.template_schema import (
    TemplateCategoryFile,
    TemplateFile,
)
from spectra_sherpa.app.services.dag.node_base import node_registry

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_loader = TemplateLoader()


@pytest.fixture(scope="module")
def all_templates() -> list[dict]:
    return _loader.load_all()


@pytest.fixture(scope="module")
def category_metadata() -> dict:
    return _loader.load_categories()


@pytest.fixture(scope="module")
def raw_yaml_files() -> list[tuple[str, dict]]:
    """Load raw YAML dicts (before Pydantic validation) for each template."""
    templates_dir = importlib.resources.files("spectra_sherpa.data") / "templates"
    results = []
    for resource in sorted(templates_dir.iterdir(), key=lambda r: r.name):
        if not resource.name.endswith(".yaml") or resource.name.startswith("_"):
            continue
        raw = yaml.safe_load(resource.read_text(encoding="utf-8"))
        results.append((resource.name, raw))
    return results


# ---------------------------------------------------------------------------
# 1. Schema validation
# ---------------------------------------------------------------------------


class TestSchemaValidation:
    """Every YAML template must validate against the TemplateFile Pydantic model."""

    def test_all_templates_parse(self, raw_yaml_files: list[tuple[str, dict]]) -> None:
        errors = []
        for filename, raw in raw_yaml_files:
            try:
                TemplateFile.model_validate(raw)
            except Exception as exc:
                errors.append(f"{filename}: {exc}")
        assert not errors, "Schema validation failures:\n" + "\n".join(errors)

    def test_all_templates_have_schema_version(self, raw_yaml_files: list[tuple[str, dict]]) -> None:
        for filename, raw in raw_yaml_files:
            assert "schema_version" in raw, f"{filename}: missing schema_version"
            assert raw["schema_version"] == 1, f"{filename}: unsupported schema_version {raw['schema_version']}"

    def test_categories_file_validates(self) -> None:
        cat_resource = importlib.resources.files("spectra_sherpa.data") / "templates" / "_categories.yaml"
        raw = yaml.safe_load(cat_resource.read_text(encoding="utf-8"))
        validated = TemplateCategoryFile.model_validate(raw)
        assert validated.schema_version == 1
        assert len(validated.categories) > 0


# ---------------------------------------------------------------------------
# 2. Node type existence
# ---------------------------------------------------------------------------


class TestNodeTypes:
    """Every node_type must exist in the NodeRegistry."""

    def test_all_node_types_registered(self, all_templates: list[dict]) -> None:
        errors = []
        for t in all_templates:
            slug = t["slug"]
            for node in t["template_data"]["nodes"]:
                ntype = node["node_type"]
                if ntype not in node_registry:
                    errors.append(f"{slug}: unknown node_type '{ntype}' on node '{node['node_id']}'")
        assert not errors, "Unknown node types:\n" + "\n".join(errors)


# ---------------------------------------------------------------------------
# 3. Edge references
# ---------------------------------------------------------------------------


class TestEdgeReferences:
    """Every edge must reference valid node_ids within its template."""

    def test_edges_reference_valid_nodes(self, all_templates: list[dict]) -> None:
        errors = []
        for t in all_templates:
            slug = t["slug"]
            node_ids = {n["node_id"] for n in t["template_data"]["nodes"]}
            for edge in t["template_data"]["edges"]:
                if edge["from_node_id"] not in node_ids:
                    errors.append(f"{slug}: edge from unknown node '{edge['from_node_id']}'")
                if edge["to_node_id"] not in node_ids:
                    errors.append(f"{slug}: edge to unknown node '{edge['to_node_id']}'")
        assert not errors, "Invalid edge references:\n" + "\n".join(errors)


# ---------------------------------------------------------------------------
# 4. data_roles node bindings
# ---------------------------------------------------------------------------


class TestDataRolesNodeBindings:
    """data_roles node_binding values must reference data.source nodes."""

    def test_data_role_bindings_are_source_nodes(self, all_templates: list[dict]) -> None:
        errors = []
        for t in all_templates:
            slug = t["slug"]
            source_ids = {n["node_id"] for n in t["template_data"]["nodes"] if n["node_type"] == "data.source"}
            for role_name, role in t["template_data"].get("data_roles", {}).items():
                if role.get("role_type") in ("X_spectra", "Y_reference", "class_labels"):
                    if role["node_binding"] not in source_ids:
                        errors.append(
                            f"{slug}: data_roles.{role_name}.node_binding "
                            f"'{role['node_binding']}' is not a data.source node"
                        )
        assert not errors, "Invalid data_roles bindings:\n" + "\n".join(errors)

    def test_no_user_dataset_mode_remnants(self, all_templates: list[dict]) -> None:
        """user_dataset_mode has been removed — ensure none sneak back in."""
        errors = []
        for t in all_templates:
            if t["template_data"].get("user_dataset_mode"):
                errors.append(f"{t['slug']}: still has user_dataset_mode (should use data_roles)")
        assert not errors, "Legacy user_dataset_mode found:\n" + "\n".join(errors)


# ---------------------------------------------------------------------------
# 5. Slug uniqueness
# ---------------------------------------------------------------------------


class TestSlugUniqueness:
    """No two templates may share the same slug."""

    def test_no_duplicate_slugs(self, all_templates: list[dict]) -> None:
        slugs = [t["slug"] for t in all_templates]
        duplicates = [s for s in slugs if slugs.count(s) > 1]
        assert not duplicates, f"Duplicate slugs: {set(duplicates)}"


# ---------------------------------------------------------------------------
# 6. Category existence
# ---------------------------------------------------------------------------


class TestCategoryExistence:
    """Every template category must exist in _categories.yaml."""

    def test_categories_exist(self, all_templates: list[dict], category_metadata: dict) -> None:
        errors = []
        for t in all_templates:
            if t["category"] not in category_metadata:
                errors.append(f"{t['slug']}: category '{t['category']}' not in _categories.yaml")
        assert not errors, "Unknown categories:\n" + "\n".join(errors)


# ---------------------------------------------------------------------------
# 7 & 8. data_roles validation
# ---------------------------------------------------------------------------

VALID_ROLE_TYPES = {
    "X_spectra",
    "Y_reference",
    "class_labels",
    "wavelength_axis",
    "validation_set",
    "sample_metadata",
    "background_spectrum",
}
VALID_BINDING_MODES = {"embedded", "separate_source", "port_output"}


class TestDataRoles:
    """data_roles must have valid node_bindings, role_types, and binding_modes."""

    def test_data_roles_bindings_valid(self, all_templates: list[dict]) -> None:
        errors = []
        for t in all_templates:
            slug = t["slug"]
            node_ids = {n["node_id"] for n in t["template_data"]["nodes"]}
            for role_name, role in t["template_data"].get("data_roles", {}).items():
                if role["node_binding"] not in node_ids:
                    errors.append(
                        f"{slug}: data_roles.{role_name}.node_binding "
                        f"'{role['node_binding']}' references unknown node"
                    )
        assert not errors, "Invalid data_roles bindings:\n" + "\n".join(errors)

    def test_data_roles_role_types_valid(self, all_templates: list[dict]) -> None:
        errors = []
        for t in all_templates:
            slug = t["slug"]
            for role_name, role in t["template_data"].get("data_roles", {}).items():
                if role["role_type"] not in VALID_ROLE_TYPES:
                    errors.append(f"{slug}: data_roles.{role_name}.role_type " f"'{role['role_type']}' is not valid")
        assert not errors, "Invalid role_types:\n" + "\n".join(errors)

    def test_data_roles_binding_modes_valid(self, all_templates: list[dict]) -> None:
        errors = []
        for t in all_templates:
            slug = t["slug"]
            for role_name, role in t["template_data"].get("data_roles", {}).items():
                if role["binding_mode"] not in VALID_BINDING_MODES:
                    errors.append(
                        f"{slug}: data_roles.{role_name}.binding_mode " f"'{role['binding_mode']}' is not valid"
                    )
        assert not errors, "Invalid binding_modes:\n" + "\n".join(errors)

    def test_supervised_templates_have_target_role(self, all_templates: list[dict]) -> None:
        """Templates in supervised categories should have Y_reference or class_labels data_role."""
        supervised_categories = {"calibration", "classification", "quality_control"}
        errors = []
        for t in all_templates:
            slug = t["slug"]
            if t["category"] not in supervised_categories:
                continue
            data_roles = t["template_data"].get("data_roles", {})
            has_target_role = any(r["role_type"] in ("Y_reference", "class_labels") for r in data_roles.values())
            if not has_target_role:
                errors.append(
                    f"{slug}: supervised category '{t['category']}' but no Y_reference or class_labels data_role"
                )
        assert not errors, "Missing target data_roles:\n" + "\n".join(errors)

    def test_every_template_has_data_roles(self, all_templates: list[dict]) -> None:
        """Every template must define at least one data_role."""
        errors = []
        for t in all_templates:
            if not t["template_data"].get("data_roles"):
                errors.append(f"{t['slug']}: missing data_roles")
        assert not errors, "Templates without data_roles:\n" + "\n".join(errors)


class TestCertifiedDatasets:
    """Certified example templates must keep their default launch path curated."""

    @staticmethod
    def _default_example_refs(template_data: dict) -> list[tuple[str, str]]:
        refs: list[tuple[str, str]] = []
        for node in template_data.get("nodes", []):
            if node.get("node_type") != "data.source":
                continue
            params = node.get("parameters", {}) or {}
            source = params.get("source")
            if source == "eigenvector" and params.get("eigenvector_dataset"):
                refs.append(("eigenvector", params["eigenvector_dataset"]))
            elif source == "sklearn" and params.get("sklearn_dataset"):
                refs.append(("sklearn", params["sklearn_dataset"]))
            elif source == "spectrochempy":
                dataset_name = params.get("example_dataset") or params.get("example_file")
                if dataset_name:
                    refs.append(("spectrochempy", dataset_name))
            elif source == "oes" and params.get("oes_dataset"):
                refs.append(("oes", params["oes_dataset"]))
        return refs

    def test_default_example_bindings_are_certified(self, all_templates: list[dict]) -> None:
        errors = []
        for template in all_templates:
            certified = template["template_data"].get("certified_datasets") or []
            if not certified:
                continue
            certified_pairs = {(entry["source"], entry["name"]) for entry in certified}
            for example_ref in self._default_example_refs(template["template_data"]):
                if example_ref not in certified_pairs:
                    errors.append(
                        f"{template['slug']}: default example "
                        f"'{example_ref[0]}:{example_ref[1]}' missing from certified_datasets"
                    )
        assert not errors, "Default examples must remain certified:\n" + "\n".join(errors)


# ---------------------------------------------------------------------------
# 9. importlib.resources discoverability
# ---------------------------------------------------------------------------


class TestPackageDiscoverability:
    """Templates must be discoverable via importlib.resources."""

    def test_templates_discoverable(self) -> None:
        templates_dir = importlib.resources.files("spectra_sherpa.data") / "templates"
        yaml_files = [
            r.name for r in templates_dir.iterdir() if r.name.endswith(".yaml") and not r.name.startswith("_")
        ]
        assert len(yaml_files) >= 20, f"Expected ≥20 template files, found {len(yaml_files)}"

    def test_categories_file_discoverable(self) -> None:
        cat = importlib.resources.files("spectra_sherpa.data") / "templates" / "_categories.yaml"
        content = cat.read_text(encoding="utf-8")
        assert "schema_version" in content

    def test_loader_uses_importlib(self) -> None:
        """TemplateLoader must resolve via importlib, not hardcoded paths."""
        loader = TemplateLoader()
        templates = loader.load_all()
        assert len(templates) >= 20


# ---------------------------------------------------------------------------
# Structural integrity
# ---------------------------------------------------------------------------


class TestDAGStructure:
    """Basic DAG structural checks."""

    def test_no_self_loops(self, all_templates: list[dict]) -> None:
        errors = []
        for t in all_templates:
            for edge in t["template_data"]["edges"]:
                if edge["from_node_id"] == edge["to_node_id"]:
                    errors.append(f"{t['slug']}: self-loop on node '{edge['from_node_id']}'")
        assert not errors, "Self-loops found:\n" + "\n".join(errors)

    def test_all_non_source_nodes_have_incoming_edge(self, all_templates: list[dict]) -> None:
        """Every non-source, non-deploy-input node should have at least one incoming edge."""
        errors = []
        exempt_types = {"data.source", "deploy.input"}
        for t in all_templates:
            slug = t["slug"]
            nodes = t["template_data"]["nodes"]
            edges = t["template_data"]["edges"]
            targets = {e["to_node_id"] for e in edges}
            for node in nodes:
                if node["node_type"] not in exempt_types and node["node_id"] not in targets:
                    errors.append(f"{slug}: node '{node['node_id']}' ({node['node_type']}) has no incoming edge")
        assert not errors, "Orphaned nodes:\n" + "\n".join(errors)


# ---------------------------------------------------------------------------
# Port existence — every edge from_output / to_input must exist on the node
# ---------------------------------------------------------------------------


def _get_port_names(node_type: str, direction: str) -> list[str] | None:
    """Return output or input port names for a node type, or None if unknown."""
    try:
        cls = node_registry.get_node_class(node_type)
    except Exception:
        return None
    meta = getattr(cls, "metadata", None)
    if meta is None:
        return None
    ports = meta.output_ports if direction == "out" else meta.input_ports
    if not ports:
        return None
    return [p.name for p in ports]


def _get_port_type_ref(node_type: str, port_name: str, direction: str) -> str | None:
    """Return the type_ref for a specific port, or None."""
    try:
        cls = node_registry.get_node_class(node_type)
    except Exception:
        return None
    meta = getattr(cls, "metadata", None)
    if meta is None:
        return None
    ports = meta.output_ports if direction == "out" else meta.input_ports
    if not ports:
        return None
    for p in ports:
        if p.name == port_name:
            return str(p.type_ref)
    return None


# Downstream nodes that accept the full multi-output dict via the executor's
# dict-passthrough behavior (no specific from_output needed).
_DICT_PASSTHROUGH_TARGETS = {"stats.summary", "output.plot", "output.export"}


class TestEdgePorts:
    """Every edge must reference ports that actually exist on the source/target nodes."""

    def test_from_output_ports_exist(self, all_templates: list[dict]) -> None:
        errors = []
        for t in all_templates:
            slug = t["slug"]
            nodes = {n["node_id"]: n["node_type"] for n in t["template_data"]["nodes"]}
            for i, edge in enumerate(t["template_data"]["edges"]):
                from_output = edge.get("from_output", "default")
                from_type = nodes.get(edge["from_node_id"], "")
                to_type = nodes.get(edge["to_node_id"], "")
                out_ports = _get_port_names(from_type, "out")
                if out_ports is None:
                    continue
                # Dict-passthrough: downstream nodes that parse the full dict
                if from_output == "default" and "default" not in out_ports:
                    if to_type in _DICT_PASSTHROUGH_TARGETS:
                        continue
                    errors.append(
                        f"{slug}: edge {i} ({edge['from_node_id']}->{edge['to_node_id']}) "
                        f'from_output="default" but {from_type} has no default port '
                        f"(available: {out_ports})"
                    )
                elif from_output != "default" and from_output not in out_ports:
                    errors.append(
                        f"{slug}: edge {i} ({edge['from_node_id']}->{edge['to_node_id']}) "
                        f'from_output="{from_output}" not in {from_type} '
                        f"output_ports {out_ports}"
                    )
        assert not errors, "Invalid from_output ports:\n" + "\n".join(errors)

    def test_to_input_ports_exist(self, all_templates: list[dict]) -> None:
        errors = []
        for t in all_templates:
            slug = t["slug"]
            nodes = {n["node_id"]: n["node_type"] for n in t["template_data"]["nodes"]}
            for i, edge in enumerate(t["template_data"]["edges"]):
                to_input = edge.get("to_input", "default")
                to_type = nodes.get(edge["to_node_id"], "")
                in_ports = _get_port_names(to_type, "in")
                if in_ports is None:
                    continue
                if to_input != "default" and to_input not in in_ports:
                    errors.append(
                        f"{slug}: edge {i} ({edge['from_node_id']}->{edge['to_node_id']}) "
                        f'to_input="{to_input}" not in {to_type} '
                        f"input_ports {in_ports}"
                    )
        assert not errors, "Invalid to_input ports:\n" + "\n".join(errors)


# ---------------------------------------------------------------------------
# Type compatibility — from_output type_ref must be assignable to to_input
# ---------------------------------------------------------------------------


class TestEdgeTypeCompatibility:
    """Edge type_refs must be compatible (same type, subtype, or Any target)."""

    @pytest.fixture(scope="class", autouse=True)
    def _load_type_registry(self) -> None:
        from pathlib import Path

        from spectra_sherpa.app.types import type_registry

        if not type_registry._by_name:
            registry_dir = Path(__file__).resolve().parent.parent / "src" / "spectra_sherpa" / "app" / "types"
            type_registry.load(registry_dir)

    def test_edge_type_refs_compatible(self, all_templates: list[dict]) -> None:
        from spectra_sherpa.app.types.validator import can_connect

        errors = []
        for t in all_templates:
            slug = t["slug"]
            nodes = {n["node_id"]: n["node_type"] for n in t["template_data"]["nodes"]}
            for i, edge in enumerate(t["template_data"]["edges"]):
                from_output = edge.get("from_output", "default")
                to_input = edge.get("to_input", "default")
                from_type = nodes.get(edge["from_node_id"], "")
                to_type = nodes.get(edge["to_node_id"], "")

                # Skip dict-passthrough edges
                if from_output == "default" and to_type in _DICT_PASSTHROUGH_TARGETS:
                    out_ports = _get_port_names(from_type, "out")
                    if out_ports and "default" not in out_ports:
                        continue

                src_ref = _get_port_type_ref(from_type, from_output, "out")
                # For to_input="default" fallback to first port
                dst_ref = _get_port_type_ref(to_type, to_input, "in")
                if dst_ref is None and to_input == "default":
                    in_ports = _get_port_names(to_type, "in")
                    if in_ports:
                        dst_ref = _get_port_type_ref(to_type, in_ports[0], "in")

                if src_ref is None or dst_ref is None:
                    continue

                ok, reason = can_connect(src_ref, dst_ref)
                if not ok:
                    errors.append(
                        f"{slug}: edge {i} ({edge['from_node_id']}.{from_output} "
                        f"-> {edge['to_node_id']}.{to_input}) {reason}"
                    )
        assert not errors, "Type-incompatible edges:\n" + "\n".join(errors)
