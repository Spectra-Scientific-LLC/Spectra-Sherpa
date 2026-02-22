"""
Tests for node type_ref declarations (Phase 2).

Verifies that every registered node's PortMetadata has a valid type_ref
that resolves in the type registry.

Run:
    PYTHONPATH=src/spectra_sherpa python -m pytest tests/test_node_type_refs.py -v --no-cov
"""

from __future__ import annotations

from pathlib import Path

import pytest

from spectra_sherpa.app.services.dag.node_base import node_registry
from spectra_sherpa.app.services.dag.node_meta_validator import (
    validate_all_registered_node_meta,
    validate_node_meta,
)

TYPES_DIR = Path(__file__).resolve().parent.parent / "src" / "spectra_sherpa" / "app" / "types"


@pytest.fixture(autouse=True, scope="module")
def _setup_registries():
    """Load type registry and import all node modules to populate node_registry."""
    from spectra_sherpa.app.types import type_registry

    if not type_registry.is_loaded:
        type_registry.load(TYPES_DIR)

    # Import all node modules to trigger @register_node decorators
    import spectra_sherpa.app.services.dag.nodes.blend  # noqa: F401
    import spectra_sherpa.app.services.dag.nodes.classification  # noqa: F401
    import spectra_sherpa.app.services.dag.nodes.custom  # noqa: F401
    import spectra_sherpa.app.services.dag.nodes.data  # noqa: F401
    import spectra_sherpa.app.services.dag.nodes.diagnostics  # noqa: F401
    import spectra_sherpa.app.services.dag.nodes.modeling  # noqa: F401
    import spectra_sherpa.app.services.dag.nodes.output  # noqa: F401
    import spectra_sherpa.app.services.dag.nodes.preprocessing  # noqa: F401
    import spectra_sherpa.app.services.dag.nodes.time_series  # noqa: F401


class TestAllNodeTypeRefs:
    """Ensure all PortMetadata type_refs resolve in the type registry."""

    def test_node_registry_not_empty(self):
        nodes = node_registry.list_nodes()
        assert len(nodes) > 0, "No nodes registered — node imports may have failed"

    def test_all_input_ports_resolve(self):
        from spectra_sherpa.app.types import type_registry

        errors: list[str] = []
        for meta in node_registry.list_nodes():
            if meta.input_ports:
                for port in meta.input_ports:
                    try:
                        type_registry.resolve(port.type_ref)
                    except (KeyError, ValueError) as e:
                        errors.append(f"{meta.node_type} input '{port.name}': {e}")

        if errors:
            pytest.fail("Unresolvable type_refs on input ports:\n" + "\n".join(f"  {e}" for e in errors))

    def test_all_output_ports_resolve(self):
        from spectra_sherpa.app.types import type_registry

        errors: list[str] = []
        for meta in node_registry.list_nodes():
            if meta.output_ports:
                for port in meta.output_ports:
                    try:
                        type_registry.resolve(port.type_ref)
                    except (KeyError, ValueError) as e:
                        errors.append(f"{meta.node_type} output '{port.name}': {e}")

        if errors:
            pytest.fail("Unresolvable type_refs on output ports:\n" + "\n".join(f"  {e}" for e in errors))

    def test_all_ports_have_valid_category(self):
        """Every port's type_ref should resolve to a type with a known category."""
        from spectra_sherpa.app.types import type_registry

        valid_categories = {"dataset", "array", "number", "target", "model", "visualization", "config"}
        errors: list[str] = []

        for meta in node_registry.list_nodes():
            for port in (meta.input_ports or []) + (meta.output_ports or []):
                try:
                    td = type_registry.resolve(port.type_ref)
                    if td.category not in valid_categories:
                        errors.append(
                            f"{meta.node_type} port '{port.name}': " f"category '{td.category}' not in known categories"
                        )
                except (KeyError, ValueError) as e:
                    errors.append(f"{meta.node_type} port '{port.name}': {e}")

        if errors:
            pytest.fail("Invalid port categories:\n" + "\n".join(f"  {e}" for e in errors))

    def test_no_port_type_equals_in_declarations(self):
        """Meta-test: confirm no node file still uses port_type= in PortMetadata constructors."""
        import ast

        nodes_dir = (
            Path(__file__).resolve().parent.parent / "src" / "spectra_sherpa" / "app" / "services" / "dag" / "nodes"
        )

        violations: list[str] = []
        for py_file in nodes_dir.glob("*.py"):
            try:
                tree = ast.parse(py_file.read_text(encoding="utf-8"), filename=str(py_file))
            except SyntaxError:
                continue

            for node in ast.walk(tree):
                if isinstance(node, ast.keyword) and node.arg == "port_type":
                    violations.append(f"{py_file.name}:{node.lineno}")

        if violations:
            pytest.fail(
                "Found port_type= keyword args (should be type_ref=):\n" + "\n".join(f"  {v}" for v in violations)
            )

    def test_validate_node_meta_utility_per_node(self):
        """validate_node_meta() should pass for every registered node class."""
        errors: list[str] = []
        for meta in node_registry.list_nodes():
            node_class = node_registry.get_node_class(meta.node_type)
            ok, node_errors = validate_node_meta(node_class)
            if not ok:
                errors.extend(node_errors)

        if errors:
            pytest.fail("validate_node_meta reported errors:\n" + "\n".join(f"  {e}" for e in errors))

    def test_validate_node_meta_utility_bulk(self):
        """Bulk validator should pass and return no errors."""
        ok, errors = validate_all_registered_node_meta()
        assert ok, "\n".join(errors)
        assert errors == []
