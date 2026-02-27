"""Tests for enhanced workflow validation (Issue #17).

Verifies DAGExecutor.validate_full() catches:
- Cycles, disconnected non-source nodes, missing required ports
- Missing required parameters, out-of-range values
- Port type mismatches (warnings)
- Backward-compat: validate() still returns list[str]
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from spectra_sherpa.app.services.dag.executor import (
    DAGExecutor,
    ValidationIssue,
    ValidationResult,
    WorkflowEdge,
    WorkflowNode,
)

# ---------------------------------------------------------------------------
# Helpers — ensure node modules are registered
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _register_nodes():
    """Ensure core node types are registered."""
    import spectra_sherpa.app.services.dag.nodes.data  # noqa: F401
    import spectra_sherpa.app.services.dag.nodes.preprocessing  # noqa: F401

    try:
        import spectra_sherpa.app.services.dag.nodes.deploy_nodes  # noqa: F401
    except Exception:
        pass
    try:
        import spectra_sherpa.app.services.dag.nodes.modeling  # noqa: F401
    except Exception:
        pass


def _build_executor(*nodes_edges):
    """Shortcut: build executor from (WorkflowNode, ...) and (WorkflowEdge, ...) tuples."""
    executor = DAGExecutor(process_pool=None)
    for item in nodes_edges:
        if isinstance(item, WorkflowNode):
            executor.add_node(item)
        elif isinstance(item, WorkflowEdge):
            executor.add_edge(item)
    return executor


# ---------------------------------------------------------------------------
# Structural validation (existing logic, now via validate_full)
# ---------------------------------------------------------------------------


class TestStructuralValidation:
    def test_empty_workflow_is_valid(self):
        executor = DAGExecutor(process_pool=None)
        result = executor.validate_full()
        assert isinstance(result, ValidationResult)
        assert result.is_valid

    def test_cycle_detection(self):
        executor = _build_executor(
            WorkflowNode(node_id="a", node_type="preprocess.normalize", parameters={"method": "snv"}),
            WorkflowNode(node_id="b", node_type="preprocess.normalize", parameters={"method": "snv"}),
            WorkflowEdge(from_node="a", to_node="b"),
            WorkflowEdge(from_node="b", to_node="a"),
        )
        result = executor.validate_full()
        assert not result.is_valid
        assert any("cycle" in e.message.lower() for e in result.errors)

    def test_disconnected_non_source_node(self):
        executor = _build_executor(
            WorkflowNode(node_id="snv1", node_type="preprocess.normalize", parameters={"method": "snv"}),
        )
        result = executor.validate_full()
        assert not result.is_valid
        assert any("no input" in e.message.lower() for e in result.errors)

    def test_source_node_needs_no_input(self):
        executor = _build_executor(
            WorkflowNode(
                node_id="src1",
                node_type="data.source",
                parameters={"source": "sklearn", "sklearn_dataset": "iris"},
            ),
        )
        result = executor.validate_full()
        assert result.is_valid

    def test_required_port_not_connected(self):
        """LoadApplyModel requires X_new port — if not connected, error."""
        executor = _build_executor(
            WorkflowNode(
                node_id="load1",
                node_type="model.load_apply",
                parameters={"model_id": "test-uid"},
            ),
        )
        result = executor.validate_full()
        errors = result.errors
        # Should have "no input connections" and/or "Required input port"
        assert len(errors) >= 1


# ---------------------------------------------------------------------------
# Parameter validation (new)
# ---------------------------------------------------------------------------


class TestParameterValidation:
    def test_missing_required_param(self):
        """DeployInputNode requires stream_name (has default so should pass)."""
        executor = _build_executor(
            WorkflowNode(
                node_id="dep1",
                node_type="deploy.input",
                parameters={},  # stream_name has default="sample"
            ),
        )
        result = executor.validate_full()
        # stream_name has a default, so no error
        param_errors = [e for e in result.errors if "parameter" in e.message.lower()]
        assert len(param_errors) == 0

    def test_number_below_minimum(self):
        """Normalize SNV doesn't have min/max, so test with a node that does.

        We test the mechanism directly by patching a node's metadata.
        """
        from spectra_sherpa.app.services.dag.node_base import NodeParameter

        executor = _build_executor(
            WorkflowNode(
                node_id="src1",
                node_type="data.source",
                parameters={"source": "sklearn", "sklearn_dataset": "iris"},
            ),
            WorkflowNode(
                node_id="test_node",
                node_type="preprocess.normalize",
                parameters={"method": "snv", "bad_param": -5},
            ),
            WorkflowEdge(from_node="src1", to_node="test_node"),
        )

        # Inject a parameter definition with min_value
        node = executor.nodes["test_node"]
        original_params = list(node.metadata.parameters)
        node.metadata.parameters.append(
            NodeParameter(
                name="bad_param",
                label="Bad Param",
                param_type="number",
                min_value=0,
                max_value=100,
            )
        )

        result = executor.validate_full()
        # Restore
        node.metadata.parameters = original_params

        param_errors = [e for e in result.errors if "below minimum" in e.message.lower()]
        assert len(param_errors) == 1

    def test_number_above_maximum(self):
        from spectra_sherpa.app.services.dag.node_base import NodeParameter

        executor = _build_executor(
            WorkflowNode(
                node_id="src1",
                node_type="data.source",
                parameters={"source": "sklearn", "sklearn_dataset": "iris"},
            ),
            WorkflowNode(
                node_id="test_node",
                node_type="preprocess.normalize",
                parameters={"method": "snv", "bad_param": 200},
            ),
            WorkflowEdge(from_node="src1", to_node="test_node"),
        )
        node = executor.nodes["test_node"]
        original_params = list(node.metadata.parameters)
        node.metadata.parameters.append(
            NodeParameter(
                name="bad_param",
                label="Bad Param",
                param_type="number",
                min_value=0,
                max_value=100,
            )
        )
        result = executor.validate_full()
        node.metadata.parameters = original_params
        param_errors = [e for e in result.errors if "above maximum" in e.message.lower()]
        assert len(param_errors) == 1

    def test_select_invalid_option_warning(self):
        from spectra_sherpa.app.services.dag.node_base import NodeParameter

        executor = _build_executor(
            WorkflowNode(
                node_id="src1",
                node_type="data.source",
                parameters={"source": "sklearn", "sklearn_dataset": "iris"},
            ),
            WorkflowNode(
                node_id="test_node",
                node_type="preprocess.normalize",
                parameters={"method": "snv", "mode": "bogus_option"},
            ),
            WorkflowEdge(from_node="src1", to_node="test_node"),
        )
        node = executor.nodes["test_node"]
        original_params = list(node.metadata.parameters)
        node.metadata.parameters.append(
            NodeParameter(
                name="mode",
                label="Mode",
                param_type="select",
                options=["fast", "accurate"],
            )
        )
        result = executor.validate_full()
        node.metadata.parameters = original_params
        # Should be a warning, not error
        assert result.is_valid  # warnings don't make it invalid
        warnings = [w for w in result.warnings if "not in options" in w.message.lower()]
        assert len(warnings) == 1


# ---------------------------------------------------------------------------
# Port type validation (new)
# ---------------------------------------------------------------------------


class TestPortTypeValidation:
    def test_compatible_types_no_warning(self):
        """data.source outputs SpectralDataset, snv expects SpectralDataset."""
        executor = _build_executor(
            WorkflowNode(
                node_id="src1",
                node_type="data.source",
                parameters={"source": "sklearn", "sklearn_dataset": "iris"},
            ),
            WorkflowNode(node_id="snv1", node_type="preprocess.normalize", parameters={"method": "snv"}),
            WorkflowEdge(from_node="src1", to_node="snv1"),
        )
        # Load type registry if available
        try:
            from spectra_sherpa.app.types import type_registry

            type_registry.load()
        except Exception:
            pytest.skip("Type registry not available")

        result = executor.validate_full()
        port_warnings = [w for w in result.warnings if "mismatch" in w.message.lower()]
        assert len(port_warnings) == 0

    def test_type_registry_not_loaded_skips(self):
        """If type_registry is not loaded, port type validation is silently skipped."""
        executor = _build_executor(
            WorkflowNode(
                node_id="src1",
                node_type="data.source",
                parameters={"source": "sklearn", "sklearn_dataset": "iris"},
            ),
            WorkflowNode(node_id="snv1", node_type="preprocess.normalize", parameters={"method": "snv"}),
            WorkflowEdge(from_node="src1", to_node="snv1"),
        )
        # Patch type_registry.is_loaded to return False
        try:
            from spectra_sherpa.app.types import type_registry

            with patch.object(type_registry, "_loaded", False):
                result = executor.validate_full()
        except ImportError:
            # If type registry can't be imported, validation is skipped anyway
            result = executor.validate_full()

        # No port type warnings/errors should be generated when registry is not loaded
        port_issues = [i for i in result.issues if "mismatch" in i.message.lower()]
        assert len(port_issues) == 0


# ---------------------------------------------------------------------------
# Backward compatibility
# ---------------------------------------------------------------------------


class TestBackwardCompat:
    def test_validate_returns_list_of_strings(self):
        executor = _build_executor(
            WorkflowNode(node_id="snv1", node_type="preprocess.normalize", parameters={"method": "snv"}),
        )
        errors = executor.validate()
        assert isinstance(errors, list)
        assert all(isinstance(e, str) for e in errors)
        assert len(errors) >= 1  # disconnected node

    def test_validate_empty_workflow(self):
        executor = DAGExecutor(process_pool=None)
        errors = executor.validate()
        assert errors == []


# ---------------------------------------------------------------------------
# ValidationResult API
# ---------------------------------------------------------------------------


class TestValidationResult:
    def test_is_valid_no_errors(self):
        result = ValidationResult(
            issues=[
                ValidationIssue("warning", "n1", None, "something"),
            ]
        )
        assert result.is_valid

    def test_is_valid_with_errors(self):
        result = ValidationResult(
            issues=[
                ValidationIssue("error", "n1", None, "bad"),
                ValidationIssue("warning", "n2", None, "meh"),
            ]
        )
        assert not result.is_valid
        assert len(result.errors) == 1
        assert len(result.warnings) == 1

    def test_to_error_strings(self):
        result = ValidationResult(
            issues=[
                ValidationIssue("error", "n1", None, "error msg"),
                ValidationIssue("warning", "n2", None, "warn msg"),
            ]
        )
        strings = result.to_error_strings()
        assert strings == ["error msg"]
