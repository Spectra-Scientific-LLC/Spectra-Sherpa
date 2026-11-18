"""Inspection never grants executable admission or imports absent node code."""

import json
import subprocess
import sys

import pytest

from spectra_sherpa.core.retained_graph import RetainedGraphError, inspect_retained_graph


def payload(**changes):
    value = {
        "name": "Historical pack output",
        "nodes": [
            {
                "node_id": "unknown",
                "node_type": "pro.absent.measure",
                "label": "<script>inert text</script>",
                "parameters": {"unit": "mg/L", "threshold": 2.5},
            },
            {"node_id": "retired", "node_type": "obsolete.operation", "parameters": {"scope": "held_out"}},
        ],
        "edges": [{"from_node_id": "unknown", "to_node_id": "retired"}],
    }
    value.update(changes)
    return json.dumps(value).encode()


def test_unknown_and_retired_nodes_are_only_display_facts():
    graph = inspect_retained_graph(payload())
    assert graph.inspection_only is True
    assert graph.nodes[0].parameters == {"unit": "mg/L", "threshold": 2.5}
    assert graph.nodes[0].label == "<script>inert text</script>"
    assert graph.nodes[1].node_type == "obsolete.operation"
    assert graph.pack_binding is None  # No invented historical build.
    with pytest.raises(ValueError):
        graph.inspection_only = False


def test_fresh_process_inspection_imports_no_registry_or_private_package():
    script = """
import sys
from spectra_sherpa.core.retained_graph import inspect_retained_graph
value = inspect_retained_graph(sys.argv[1].encode())
assert value.inspection_only
assert not any(name.startswith(("spectra_sherpa.app.services.dag", "spectrasherpa_server")) for name in sys.modules)
"""
    result = subprocess.run(
        [sys.executable, "-c", script, payload().decode()], capture_output=True, text=True, timeout=30
    )
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize(
    "wire",
    [
        b'{"nodes":[],"nodes":[],"edges":[]}',
        payload(nodes=[{"node_id": "x", "node_type": "unknown", "parameters": {"x": float("nan")}}]),
        b'{"nodes":[{"node_id":"x","node_type":"u","parameters":{"v":1e999}}],"edges":[]}',
        payload(edges=[{"from_node_id": "unknown", "to_node_id": "missing"}]),
        payload(nodes=[{"node_id": "x", "node_type": "u"}] * 2),
        b" " * (2 * 1024 * 1024 + 1),
        b"[" * 2000 + b"]" * 2000,
    ],
    ids=[
        "duplicate-json-key",
        "nan",
        "nonfinite-number",
        "unresolved-edge",
        "duplicate-node-id",
        "oversized-json",
        "excessive-json-depth",
    ],
)
def test_malformed_or_oversized_evidence_is_refused(wire):
    with pytest.raises(RetainedGraphError):
        inspect_retained_graph(wire)


def test_renderer_fields_are_not_part_of_the_display_contract():
    graph = inspect_retained_graph(payload(renderer_code="arbitrary", module="private.loader"))
    assert "renderer_code" not in graph.model_dump()
    assert "module" not in graph.model_dump()
