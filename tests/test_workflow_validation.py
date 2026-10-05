"""Tests for enhanced workflow validation (Issue #17).

Verifies DAGExecutor.validate_full() catches:
- Cycles, disconnected non-source nodes, missing required ports
- Missing required parameters, out-of-range values
- Port type mismatches (warnings)
- Backward-compat: validate() still returns list[str]
"""

from __future__ import annotations

import warnings
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pytest

from spectra_sherpa.app.lib.sherpa_dataset import SherpaDataset
from spectra_sherpa.app.services.dag.executor import (
    DAGExecutor,
    ValidationIssue,
    ValidationResult,
    WorkflowEdge,
    WorkflowNode,
)
from spectra_sherpa.app.services.model_store import ModelStore
from spectra_sherpa.core.execution_runtime import ExecutionRuntime

TYPES_DIR = Path(__file__).resolve().parent.parent / "src" / "spectra_sherpa" / "app" / "types"
_CANONICAL_FILE_PARAMETERS = {"experiment_id": 1, "file_id": 1, "stage": "raw"}

# ---------------------------------------------------------------------------
# Helpers — ensure node modules are registered
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _register_nodes():
    """Ensure core node types are registered."""
    import spectra_sherpa.app.services.dag.nodes.classification  # noqa: F401
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


@pytest.mark.parametrize("reverse", [False, True])
def test_declared_default_input_is_not_a_positional_legacy_port(reverse):
    edges = [
        WorkflowEdge("source", "apply", "default", "default"),
        WorkflowEdge("model", "apply", "fitted_state", "fitted_state"),
    ]
    if reverse:
        edges.reverse()
    executor = _build_executor(
        WorkflowNode("source", "data.file_load", _CANONICAL_FILE_PARAMETERS),
        WorkflowNode("model", "classification.plsda", {}),
        WorkflowNode("apply", "classification.apply_plsda", {}),
        *edges,
    )
    assert not [issue for issue in executor._validate_port_connections() if issue.node_id == "apply"]


def _nested_cv_executor(preprocessing_type: str, preprocessing_parameters: dict) -> DAGExecutor:
    """Build one canvas graph whose preprocessing lifecycle is under test."""

    import spectra_sherpa.app.services.dag.nodes.selection  # noqa: F401

    return _build_executor(
        WorkflowNode(
            node_id="source",
            node_type="data.file_load",
            parameters=_CANONICAL_FILE_PARAMETERS,
        ),
        WorkflowNode(node_id="preprocess", node_type=preprocessing_type, parameters=preprocessing_parameters),
        WorkflowNode(node_id="nested", node_type="selection.nested_cv", parameters={}),
        WorkflowEdge(from_node="source", to_node="preprocess", from_output="default"),
        WorkflowEdge(from_node="preprocess", to_node="nested", to_input="X"),
        WorkflowEdge(from_node="source", to_node="nested", from_output="target", to_input="y"),
    )


def _nested_cv_after_fitted_selector() -> DAGExecutor:
    """Build the target-fitted selection path that a category-only guard misses."""

    import spectra_sherpa.app.services.dag.nodes.selection  # noqa: F401

    return _build_executor(
        WorkflowNode(
            node_id="source",
            node_type="data.file_load",
            parameters=_CANONICAL_FILE_PARAMETERS,
        ),
        WorkflowNode(node_id="stability", node_type="selection.stability", parameters={}),
        WorkflowNode(node_id="nested", node_type="selection.nested_cv", parameters={}),
        WorkflowEdge(from_node="source", to_node="stability", from_output="default", to_input="X"),
        WorkflowEdge(from_node="source", to_node="stability", from_output="target", to_input="y"),
        WorkflowEdge(from_node="stability", from_output="X_selected", to_node="nested", to_input="X"),
        WorkflowEdge(from_node="source", to_node="nested", from_output="target", to_input="y"),
    )


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
                node_type="data.file_load",
                parameters=_CANONICAL_FILE_PARAMETERS,
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

    def test_nested_cv_rejects_globally_fitted_upstream_preprocessing(self):
        executor = _nested_cv_executor("preprocess.scale", {"method": "autoscale", "center": True})

        result = executor.validate_full(include_port_type_validation=False)

        assert not result.is_valid
        assert any(
            issue.node_id == "nested" and "execute that operation on all rows before cross-validation" in issue.message
            for issue in result.errors
        )

    def test_nested_cv_accepts_contract_declared_stateless_preprocessing(self):
        executor = _nested_cv_executor("preprocess.normalize", {"method": "snv"})

        result = executor.validate_full(include_port_type_validation=False)

        assert not any("before cross-validation" in issue.message for issue in result.errors)

    def test_nested_cv_accepts_stateless_target_attachment(self):
        executor = _build_executor(
            WorkflowNode(
                node_id="spectra",
                node_type="data.file_load",
                parameters=_CANONICAL_FILE_PARAMETERS,
            ),
            WorkflowNode(
                node_id="targets",
                node_type="data.file_load",
                parameters=_CANONICAL_FILE_PARAMETERS,
            ),
            WorkflowNode(
                node_id="attach",
                node_type="data.attach_target",
                parameters={"target_type": "continuous"},
            ),
            WorkflowNode(node_id="nested", node_type="selection.nested_cv", parameters={}),
            WorkflowEdge(from_node="spectra", to_node="attach", from_output="default", to_input="X"),
            WorkflowEdge(from_node="targets", to_node="attach", from_output="target", to_input="y"),
            WorkflowEdge(from_node="attach", to_node="nested", to_input="X"),
            WorkflowEdge(from_node="attach", to_node="nested", to_input="y"),
        )

        result = executor.validate_full(include_port_type_validation=False)

        assert not any("before cross-validation" in issue.message for issue in result.errors)

    def test_nested_cv_rejects_target_fitted_osc_before_outer_folds(self):
        executor = _nested_cv_executor("preprocess.osc", {})

        result = executor.validate_full(include_port_type_validation=False)

        assert not result.is_valid
        assert any("declares lifecycle_kind=fitted_transform" in issue.message for issue in result.errors)

    def test_nested_cv_accepts_contract_bound_group_source_as_fold_safe(self):
        import spectra_sherpa.app.services.dag.nodes.selection  # noqa: F401

        executor = _build_executor(
            WorkflowNode(
                node_id="dataset",
                node_type="data.load_group",
                parameters={"folder_path": "/contract-test/not-executed"},
            ),
            WorkflowNode(node_id="nested", node_type="selection.nested_cv", parameters={}),
            WorkflowEdge(from_node="dataset", to_node="nested", to_input="X"),
            WorkflowEdge(from_node="dataset", to_node="nested", to_input="y"),
        )

        result = executor.validate_full(include_port_type_validation=False)

        assert result.is_valid
        assert not any("before cross-validation" in issue.message for issue in result.errors)

    def test_nested_cv_rejects_target_fitted_selector_before_outer_folds(self):
        executor = _nested_cv_after_fitted_selector()

        result = executor.validate_full(include_port_type_validation=False)

        assert not result.is_valid
        assert any(
            issue.node_id == "nested" and "lifecycle_kind=fitted_transform" in issue.message for issue in result.errors
        )

    @pytest.mark.asyncio
    async def test_canvas_execution_cannot_bypass_nested_cv_ancestor_safety(self):
        executor = _nested_cv_after_fitted_selector()

        with pytest.raises(ValueError, match="Nested CV cannot consume upstream operation"):
            await executor.execute()


# ---------------------------------------------------------------------------
# Parameter validation (new)
# ---------------------------------------------------------------------------


class TestHoldoutAncestorSafety:
    @staticmethod
    def graph(node_type=None, parameters=None):
        executor = _build_executor(
            WorkflowNode("source", "data.file_load", _CANONICAL_FILE_PARAMETERS),
            WorkflowNode("split", "data.train_test_split", {"split_method": "sequential", "test_size": 0.25}),
            WorkflowEdge("source", "split", "target", "y"),
        )
        if node_type:
            executor.add_node(WorkflowNode("before_split", node_type, parameters or {}))
            executor.add_edge(WorkflowEdge("source", "before_split"))
            executor.add_edge(WorkflowEdge("before_split", "split", "default", "X"))
            if node_type == "preprocess.osc":
                executor.add_edge(WorkflowEdge("source", "before_split", "target", "y"))
        else:
            executor.add_edge(WorkflowEdge("source", "split", "default", "X"))
        return executor

    @pytest.mark.parametrize(
        "node_type,parameters",
        [("preprocess.osc", {"n_components": 1}), ("preprocess.scale", {"method": "autoscale"})],
    )
    def test_refuses_supervised_and_unsupervised_fitting_before_holdout(self, node_type, parameters):
        result = self.graph(node_type, parameters).validate_full()
        assert not result.is_valid
        assert any("Train/test split cannot consume" in issue.message for issue in result.errors)

    @pytest.mark.parametrize("node_type", [None, "preprocess.normalize"])
    def test_accepts_raw_and_stateless_inputs(self, node_type):
        result = self.graph(node_type, {"method": "snv"}).validate_full()
        assert result.is_valid, result.errors

    def test_accepts_training_only_fitting_after_holdout(self):
        executor = self.graph()
        executor.add_node(WorkflowNode("fit", "preprocess.osc", {"n_components": 1}))
        executor.add_edge(WorkflowEdge("split", "fit", "X_train", "default"))
        executor.add_edge(WorkflowEdge("split", "fit", "y_train", "y"))
        assert executor.validate_full().is_valid

    @pytest.mark.asyncio
    async def test_execution_cannot_bypass_holdout_safety(self):
        with pytest.raises(ValueError, match="Train/test split cannot consume upstream operation"):
            await self.graph("preprocess.osc", {"n_components": 1}).execute()

    def test_shared_preflight_refuses_complete_pls_graph_with_osc_before_split(self):
        import yaml

        from spectra_sherpa.app.services.tools.builtin.workflow import validate_workflow

        source = Path(__file__).resolve().parents[1] / "src/spectra_sherpa/data/templates/pls_calibration.yaml"
        graph = yaml.safe_load(source.read_text())["template_data"]
        graph["nodes"][0]["parameters"] = dict(_CANONICAL_FILE_PARAMETERS)
        assert validate_workflow(graph["nodes"], graph["edges"])["valid"]
        graph["nodes"].append({"node_id": "osc", "node_type": "preprocess.osc", "parameters": {"n_components": 1}})
        for edge in graph["edges"]:
            if edge["from_node_id"] == "data_1" and edge.get("to_input") == "X":
                edge["from_node_id"] = "osc"
        graph["edges"].extend(
            [
                {"from_node_id": "data_1", "to_node_id": "osc", "to_input": "default"},
                {"from_node_id": "data_1", "to_node_id": "osc", "from_output": "target", "to_input": "y"},
            ]
        )
        result = validate_workflow(graph["nodes"], graph["edges"])
        assert not result["valid"]
        assert any("Train/test split cannot consume" in issue["message"] for issue in result["issues"])


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
                node_type="data.file_load",
                parameters=_CANONICAL_FILE_PARAMETERS,
            ),
            WorkflowNode(
                node_id="test_node",
                node_type="preprocess.normalize",
                parameters={"method": "snv"},
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
        node.parameters["bad_param"] = -5

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
                node_type="data.file_load",
                parameters=_CANONICAL_FILE_PARAMETERS,
            ),
            WorkflowNode(
                node_id="test_node",
                node_type="preprocess.normalize",
                parameters={"method": "snv"},
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
        node.parameters["bad_param"] = 200
        result = executor.validate_full()
        node.metadata.parameters = original_params
        param_errors = [e for e in result.errors if "above maximum" in e.message.lower()]
        assert len(param_errors) == 1

    def test_select_invalid_option_warning(self):
        from spectra_sherpa.app.services.dag.node_base import NodeParameter

        executor = _build_executor(
            WorkflowNode(
                node_id="src1",
                node_type="data.file_load",
                parameters=_CANONICAL_FILE_PARAMETERS,
            ),
            WorkflowNode(
                node_id="test_node",
                node_type="preprocess.normalize",
                parameters={"method": "snv"},
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
        node.parameters["mode"] = "bogus_option"
        result = executor.validate_full()
        node.metadata.parameters = original_params
        # Should be a warning, not error
        assert result.is_valid  # warnings don't make it invalid
        warnings = [w for w in result.warnings if "not in options" in w.message.lower()]
        assert len(warnings) == 1


class TestRuntimePortTypeFallbacks:
    def test_category_fallback_keeps_model_ports_as_model(self, monkeypatch):
        from spectra_sherpa.app.services.dag.executor_validation import _category_from_type_ref
        from spectra_sherpa.app.types import type_registry

        monkeypatch.setattr(type_registry, "_loaded", False)

        assert _category_from_type_ref("spectrasherpa://types/RegressionModel/1.0") == "model"
        assert _category_from_type_ref("spectrasherpa://types/FittedModel/1.0") == "model"
        assert _category_from_type_ref("spectrasherpa://types/TargetMatrix/1.0") == "target"

    def test_wrapped_classification_models_validate_as_model_payloads(self):
        from sklearn.neighbors import KNeighborsClassifier

        from spectra_sherpa.app.services.dag.executor_validation import _validate_port_type

        knn = KNeighborsClassifier(n_neighbors=1)
        valid_payloads = [
            {"model": knn, "type": "knn"},
            {"model": knn, "classes": ["a", "b"], "type": "plsda"},
            {
                "class_models": {"a": {"loadings": [[1.0]], "class_mean": [0.0]}},
                "classes": ["a"],
                "type": "simca",
            },
            {"model_id": "artifact-123"},
        ]

        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            for payload in valid_payloads:
                _validate_port_type(
                    data=payload,
                    expected_type="model",
                    port_name="model",
                    source_node_id="train",
                    target_node_id="predict",
                    strict=False,
                )

        mismatch_warnings = [w for w in caught if "Port type mismatch" in str(w.message)]
        assert mismatch_warnings == []

    def test_plain_config_dict_does_not_validate_as_model_payload(self):
        from spectra_sherpa.app.services.dag.executor_validation import _validate_port_type

        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            _validate_port_type(
                data={"type": "knn", "n_neighbors": 5},
                expected_type="model",
                port_name="model",
                source_node_id="config",
                target_node_id="predict",
                strict=False,
            )

        mismatch_warnings = [w for w in caught if "Port type mismatch" in str(w.message)]
        assert len(mismatch_warnings) == 1

    @pytest.mark.asyncio
    async def test_knn_fitted_state_edge_does_not_warn_for_canonical_artifact_payload(self, tmp_path: Path):
        executor = DAGExecutor(
            process_pool=None,
            runtime=ExecutionRuntime(model_artifact_writer=ModelStore(tmp_path)),
        )
        executor.add_node(
            WorkflowNode(
                node_id="src",
                node_type="deploy.input",
                parameters={"stream_name": "contract-test"},
            )
        )
        executor.add_node(
            WorkflowNode(
                node_id="split",
                node_type="data.train_test_split",
                parameters={"split_method": "random", "test_size": 0.25, "random_seed": 42},
            )
        )
        executor.add_node(
            WorkflowNode(
                node_id="train",
                node_type="classification.knn",
                parameters={"n_neighbors": 3},
            )
        )
        executor.add_node(
            WorkflowNode(
                node_id="predict",
                node_type="classification.apply_knn",
                parameters={},
            )
        )

        executor.add_edge(WorkflowEdge(from_node="src", to_node="split", to_input="X"))
        executor.add_edge(WorkflowEdge(from_node="split", to_node="train", from_output="X_train", to_input="X"))
        executor.add_edge(WorkflowEdge(from_node="split", to_node="train", from_output="y_train", to_input="y"))
        executor.add_edge(WorkflowEdge(from_node="split", to_node="predict", from_output="X_test", to_input="X_new"))
        executor.add_edge(
            WorkflowEdge(from_node="train", to_node="predict", from_output="fitted_state", to_input="fitted_state")
        )

        X = np.arange(80, dtype=float).reshape(20, 4)
        executor.inject_deployment_input(
            "src",
            SherpaDataset(X=X, target=np.arange(20) % 2),
            stream_name="contract-test",
        )

        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            await executor.execute()

        mismatch_warnings = [w for w in caught if "Port type mismatch" in str(w.message)]
        assert mismatch_warnings == []


# ---------------------------------------------------------------------------
# Port type validation (new)
# ---------------------------------------------------------------------------


class TestPortTypeValidation:
    def test_compatible_types_no_warning(self):
        """data.file_load outputs SpectralDataset, snv expects SpectralDataset."""
        executor = _build_executor(
            WorkflowNode(
                node_id="src1",
                node_type="data.file_load",
                parameters=_CANONICAL_FILE_PARAMETERS,
            ),
            WorkflowNode(node_id="snv1", node_type="preprocess.normalize", parameters={"method": "snv"}),
            WorkflowEdge(from_node="src1", to_node="snv1"),
        )
        from spectra_sherpa.app.types import type_registry

        type_registry.load(TYPES_DIR)

        result = executor.validate_full()
        port_warnings = [w for w in result.warnings if "mismatch" in w.message.lower()]
        assert len(port_warnings) == 0

    def test_type_registry_not_loaded_skips(self):
        """If type_registry is not loaded, port type validation is silently skipped."""
        executor = _build_executor(
            WorkflowNode(
                node_id="src1",
                node_type="data.file_load",
                parameters=_CANONICAL_FILE_PARAMETERS,
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
