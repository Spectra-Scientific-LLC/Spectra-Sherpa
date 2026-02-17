"""
Tests for NodeResult and diagnostic emission (Phase 4).

Covers:
- NodeResult.wrap() with raw values, dicts, explicit NodeResult
- Node.run() returns NodeResult
- Executor unpacks NodeResult.outputs and .diagnostics

Run:
    PYTHONPATH=src/spectra_sherpa python -m pytest tests/test_node_result.py -v --no-cov
"""
from __future__ import annotations

import asyncio
from typing import Any, Dict
from unittest.mock import patch

import pytest

from spectra_sherpa.app.services.dag.node_base import Node, NodeMetadata, NodeResult, NodeStatus, PortMetadata


# ── NodeResult.wrap() ─────────────────────────────────────────────────────

class TestNodeResultWrap:
    def test_wrap_node_result_passthrough(self):
        nr = NodeResult(outputs={"a": 1}, diagnostics={"d": 2})
        assert NodeResult.wrap(nr) is nr

    def test_wrap_dict_as_outputs(self):
        nr = NodeResult.wrap({"x": 10, "y": 20})
        assert nr.outputs == {"x": 10, "y": 20}
        assert nr.diagnostics == {}

    def test_wrap_raw_value_as_default(self):
        nr = NodeResult.wrap(42)
        assert nr.outputs == {"default": 42}
        assert nr.diagnostics == {}

    def test_wrap_none(self):
        nr = NodeResult.wrap(None)
        assert nr.outputs == {"default": None}

    def test_wrap_list(self):
        nr = NodeResult.wrap([1, 2, 3])
        assert nr.outputs == {"default": [1, 2, 3]}

    def test_wrap_string(self):
        nr = NodeResult.wrap("hello")
        assert nr.outputs == {"default": "hello"}

    def test_wrap_empty_dict(self):
        nr = NodeResult.wrap({})
        assert nr.outputs == {}
        assert nr.diagnostics == {}


# ── Node.run() integration ────────────────────────────────────────────────

class _SimpleNode(Node):
    metadata = NodeMetadata(
        node_type="test.simple",
        category="test",
        label="Simple Test Node",
        description="Returns a dict",
        parameters=[],
    )

    async def execute(self, *inputs, **kwargs):
        return {"default": "output_value"}


class _DiagnosticNode(Node):
    metadata = NodeMetadata(
        node_type="test.diagnostic",
        category="test",
        label="Diagnostic Test Node",
        description="Returns NodeResult with diagnostics",
        parameters=[],
    )

    async def execute(self, *inputs, **kwargs):
        return NodeResult(
            outputs={"default": "result"},
            diagnostics={"metric_a": 0.95, "metric_b": 42},
        )


class _ErrorNode(Node):
    metadata = NodeMetadata(
        node_type="test.error",
        category="test",
        label="Error Test Node",
        description="Always raises",
        parameters=[],
    )

    async def execute(self, *inputs, **kwargs):
        raise ValueError("intentional error")


class TestNodeRun:
    def test_run_wraps_dict(self):
        node = _SimpleNode("n1")
        result = asyncio.get_event_loop().run_until_complete(node.run())
        assert isinstance(result, NodeResult)
        assert result.outputs == {"default": "output_value"}
        assert node.status == NodeStatus.COMPLETED

    def test_run_returns_diagnostics(self):
        node = _DiagnosticNode("n2")
        result = asyncio.get_event_loop().run_until_complete(node.run())
        assert isinstance(result, NodeResult)
        assert result.diagnostics == {"metric_a": 0.95, "metric_b": 42}
        assert node.status == NodeStatus.COMPLETED

    def test_run_error_sets_status(self):
        node = _ErrorNode("n3")
        with pytest.raises(ValueError, match="intentional error"):
            asyncio.get_event_loop().run_until_complete(node.run())
        assert node.status == NodeStatus.ERROR
        assert node.error_message == "intentional error"
