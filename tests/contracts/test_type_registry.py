"""Contract tests for the type-registry public surface.

Distinct from the existing ``tests/test_type_registry.py``, which covers
URI parsing, resolution semantics, compatibility rules, and JSON
serialisation. This module tests the **outward-facing invariants**:

  - Every URI declared in ``registry.json`` is reachable through the
    canonical ``TypeRegistry.resolve(...)`` entrypoint.

  - Every ``PortMetadata.type_ref`` declared by every registered Node
    (built-in or third-party plugin) resolves through the registry.
    This is the bridge that lets third-party node authors declare their
    ports against published type URIs.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

# Importing the nodes package triggers @register_node side effects for
# every built-in node — that's how we get a populated node_registry.
import spectra_sherpa.app.services.dag.nodes  # noqa: F401  (import-for-side-effects)
from spectra_sherpa.app.services.dag.node_base import node_registry
from spectra_sherpa.app.types.registry import TypeRegistry

TYPES_DIR = Path(__file__).resolve().parents[1].parent / "src" / "spectra_sherpa" / "app" / "types"
REGISTRY_JSON = TYPES_DIR / "registry.json"


@pytest.fixture(scope="module")
def registry() -> TypeRegistry:
    reg = TypeRegistry()
    reg.load(TYPES_DIR)
    return reg


# ── URI reachability ──────────────────────────────────────────────────


class TestURIReachability:
    def test_every_declared_uri_resolves(self, registry: TypeRegistry) -> None:
        """Every URI in registry.json must be resolvable via ``resolve()``."""
        declared = json.loads(REGISTRY_JSON.read_text())["types"]
        unreachable: list[tuple[str, str]] = []
        for name, body in declared.items():
            uri = body["uri"]
            try:
                td = registry.resolve(uri)
            except KeyError as exc:
                unreachable.append((name, str(exc)))
                continue
            assert td.uri == uri, f"{name}: resolve returned wrong URI ({td.uri!r} != {uri!r})"
        assert not unreachable, f"unreachable URIs in registry.json: {unreachable}"

    def test_every_parent_uri_is_declared(self, registry: TypeRegistry) -> None:
        """A type's declared parent must itself exist in the registry."""
        declared = json.loads(REGISTRY_JSON.read_text())["types"]
        names = set(declared.keys())
        dangling: list[tuple[str, str]] = []
        for name, body in declared.items():
            parent = body.get("parent")
            if parent is not None and parent not in names:
                dangling.append((name, parent))
        assert not dangling, f"types reference parents that don't exist in the registry: {dangling}"


# ── Node port resolution ──────────────────────────────────────────────


def _all_port_type_refs() -> list[tuple[str, str, str, str]]:
    """Return (node_type, direction, port_name, type_ref) for every port."""
    rows: list[tuple[str, str, str, str]] = []
    for meta in node_registry.list_nodes():
        for port in meta.input_ports:
            rows.append((meta.node_type, "input", port.name, port.type_ref))
        for port in meta.output_ports or []:
            rows.append((meta.node_type, "output", port.name, port.type_ref))
    return rows


class TestNodePortResolution:
    def test_at_least_some_nodes_are_registered(self) -> None:
        """Sanity check — if this fails, the side-effect import didn't run."""
        nodes = node_registry.list_nodes()
        assert nodes, (
            "node_registry is empty — importing spectra_sherpa.app.services.dag.nodes "
            "should have triggered @register_node side effects."
        )

    def test_every_port_type_ref_resolves(self, registry: TypeRegistry) -> None:
        """Every port's ``type_ref`` must resolve through the registry."""
        unresolved: list[tuple[str, str, str, str, str]] = []
        for node_type, direction, port_name, type_ref in _all_port_type_refs():
            try:
                registry.resolve(type_ref)
            except (KeyError, ValueError) as exc:
                unresolved.append((node_type, direction, port_name, type_ref, str(exc)))
        assert not unresolved, (
            "node ports declare type_refs that the type registry cannot resolve. "
            "Either register the type in registry.json or fix the port declaration:\n"
            + "\n".join(f"  {n}.{d}.{p}: {t!r} → {e}" for n, d, p, t, e in unresolved)
        )
