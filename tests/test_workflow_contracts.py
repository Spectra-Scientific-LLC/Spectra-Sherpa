"""
Workflow contract test suite.

Guards against regressions by asserting:
1. All public symbols remain importable at their documented paths.
2. Core node types are registered.
3. The 4 primary workflow run paths produce correct outputs end-to-end:
   load, apply, deploy, and custom algo.

Self-contained — no external files, no database, no network.

Run with:
    PYTHONPATH=src/spectra_sherpa python -m pytest tests/test_workflow_contracts.py -v --no-cov
"""

from __future__ import annotations

import copy
from typing import Any

import numpy as np
import pytest

from spectra_sherpa.app.lib.sherpa_dataset import SherpaDataset, SpectralAxis
from spectra_sherpa.app.services.dag.node_base import (
    Node,
    NodeMetadata,
    NodeParameter,
    node_registry,
    register_node,
)
from spectra_sherpa.app.services.model_store import ModelStore

# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def spectral_dataset():
    """50-feature SherpaDataset (10 samples) with realistic spectral axis."""
    rng = np.random.default_rng(42)
    X = rng.standard_normal((10, 50))
    return SherpaDataset(
        X=X,
        feature_axis=SpectralAxis(
            values=np.linspace(400, 4000, 50),
            title="Wavenumber",
            units="cm^-1",
        ),
        backend="numpy",
        title="Contract Test Dataset",
    )


@pytest.fixture
def model_store(tmp_path):
    """ModelStore backed by tmp_path."""
    return ModelStore(tmp_path)


@pytest.fixture
def executor(model_store):
    """DAGExecutor wired with model_store, no process pool."""
    from spectra_sherpa.app.services.dag.executor import DAGExecutor

    return DAGExecutor(process_pool=None, model_store=model_store)


# ---------------------------------------------------------------------------
# Class 1: TestPreflightContracts — import & API surface guards
# ---------------------------------------------------------------------------


class TestPreflightContracts:
    """Verify all public symbols remain importable at their documented paths."""

    def test_executor_public_api(self):
        """Core executor symbols importable from executor module."""
        from spectra_sherpa.app.services.dag.executor import (
            DAGExecutor,
            WorkflowEdge,
            WorkflowNode,
            WorkflowStatus,
            _is_dataset,
            _run_node_in_worker,
            set_default_pool,
        )

        assert DAGExecutor is not None
        assert WorkflowEdge is not None
        assert WorkflowNode is not None
        assert WorkflowStatus is not None
        assert callable(set_default_pool)
        assert callable(_is_dataset)
        assert callable(_run_node_in_worker)

    def test_executor_submodule_imports(self):
        """Validation and pool sub-modules importable directly."""
        from spectra_sherpa.app.services.dag.executor_pool import (
            get_default_pool,
            set_default_pool,
        )
        from spectra_sherpa.app.services.dag.executor_validation import (
            _validate_port_type,
            _validate_spectral_units,
        )

        assert callable(_validate_port_type)
        assert callable(_validate_spectral_units)
        assert callable(set_default_pool)
        assert callable(get_default_pool)

    def test_data_package_imports(self):
        """DataSourceNode and HAS_SCP importable from nodes.data."""
        from spectra_sherpa.app.services.dag.nodes.data import (
            HAS_SCP,
            DataSourceNode,
        )

        assert DataSourceNode is not None
        assert isinstance(HAS_SCP, bool)

    def test_data_submodule_imports(self):
        """Sub-modules importable directly."""
        from spectra_sherpa.app.services.dag.nodes.data.source import DataSourceNode
        from spectra_sherpa.app.services.dag.nodes.data.transforms import TrainTestSplitNode

        assert DataSourceNode is not None
        assert TrainTestSplitNode is not None

    def test_node_registry_has_core_types(self):
        """Key node types present in the global registry."""
        all_types = {m.node_type for m in node_registry.list_nodes()}
        expected = {
            "data.source",
            "data.train_test_split",
            "preprocess.normalize",
            "model.load_apply",
            "deploy.input",
            "deploy.output",
        }
        missing = expected - all_types
        assert not missing, f"Missing node types: {missing}"

    def test_monkeypatch_targets_resolve(self):
        """Attributes used by monkeypatch in existing tests are valid getattr targets."""
        import spectra_sherpa.app.services.dag.executor as executor_mod
        import spectra_sherpa.app.services.dag.nodes.data as data_mod

        # These must exist as module-level attributes (tests monkeypatch them)
        assert hasattr(executor_mod, "HAS_SCP")
        assert hasattr(executor_mod, "HAS_NDDATASET")
        assert hasattr(data_mod, "HAS_SCP")


# ---------------------------------------------------------------------------
# Class 2: TestLoadPathContract — data.source → preprocessing → model
# ---------------------------------------------------------------------------


class TestLoadPathContract:
    """Verify the data loading and preprocessing pipeline."""

    @pytest.mark.asyncio
    async def test_sklearn_source_to_snv(self):
        """data.source(sklearn) → snv → result is SherpaDataset, shape preserved."""
        source = node_registry.create_node("data.source", "src", {"source": "sklearn", "sklearn_dataset": "iris"})
        result = await source.run()
        ds = result.outputs["default"]
        assert isinstance(ds, SherpaDataset)
        n_samples, n_features = ds.shape

        snv = node_registry.create_node("preprocess.normalize", "snv", {"method": "snv"})
        snv_result = await snv.run(default=ds)
        out = snv_result.outputs["default"]
        assert isinstance(out, SherpaDataset)
        assert out.shape == (n_samples, n_features)

    @pytest.mark.asyncio
    async def test_train_test_split_output_ports(self):
        """data.source → train_test_split → output ports, shapes sum to input.

        Uses the DAGExecutor to run the full pipeline with X and y wired,
        exercising the sample_axis slicing path in slice_axis_for_indices.
        """
        from spectra_sherpa.app.services.dag.executor import (
            DAGExecutor,
            WorkflowEdge,
            WorkflowNode,
        )

        executor = DAGExecutor(process_pool=None)
        executor.add_node(
            WorkflowNode(
                node_id="src",
                node_type="data.source",
                parameters={"source": "sklearn", "sklearn_dataset": "iris"},
            )
        )
        executor.add_node(
            WorkflowNode(
                node_id="split",
                node_type="data.train_test_split",
                parameters={"test_size": 0.2, "split_method": "random", "random_seed": 42},
            )
        )
        executor.add_edge(WorkflowEdge(from_node="src", to_node="split", from_output="default", to_input="X"))
        executor.add_edge(WorkflowEdge(from_node="src", to_node="split", from_output="target", to_input="y"))

        results = await executor.execute()
        outputs = results["split"]

        for key in ("X_train", "X_test"):
            assert key in outputs, f"Missing output port: {key}"

        X_train = outputs["X_train"]
        X_test = outputs["X_test"]
        assert isinstance(X_train, SherpaDataset)
        assert isinstance(X_test, SherpaDataset)
        assert X_train.shape[0] + X_test.shape[0] == 150  # iris has 150 samples
        assert X_train.shape[1] == 4  # iris has 4 features

    @pytest.mark.asyncio
    async def test_multi_step_preprocessing_chain(self, spectral_dataset):
        """data → snv → scale → feature_axis preserved through transforms."""
        snv = node_registry.create_node("preprocess.normalize", "snv", {"method": "snv"})
        snv_result = await snv.run(default=spectral_dataset)
        snv_out = snv_result.outputs["default"]

        scale = node_registry.create_node("preprocess.normalize", "scale", {"method": "scale"})
        scale_result = await scale.run(default=snv_out)
        out = scale_result.outputs["default"]

        assert isinstance(out, SherpaDataset)
        assert out.shape == spectral_dataset.shape
        # Feature axis preserved through both transforms
        assert out.feature_axis is not None
        np.testing.assert_array_equal(out.feature_axis.values, spectral_dataset.feature_axis.values)

    @pytest.mark.asyncio
    async def test_validation_rejects_disconnected_node(self, executor):
        """Unconnected processing node → validate() returns errors."""
        from spectra_sherpa.app.services.dag.executor import WorkflowNode

        # Add a processing node with no inputs
        executor.add_node(
            WorkflowNode(node_id="lonely_snv", node_type="preprocess.normalize", parameters={"method": "snv"})
        )
        errors = executor.validate()
        assert len(errors) > 0
        assert any("no input" in e.lower() or "not connected" in e.lower() for e in errors)

    @pytest.mark.asyncio
    async def test_validation_rejects_cycle(self, executor):
        """A→B→A → validate() returns cycle error."""
        from spectra_sherpa.app.services.dag.executor import WorkflowEdge, WorkflowNode

        executor.add_node(WorkflowNode(node_id="a", node_type="preprocess.normalize", parameters={"method": "snv"}))
        executor.add_node(WorkflowNode(node_id="b", node_type="preprocess.normalize", parameters={"method": "snv"}))
        executor.add_edge(WorkflowEdge(from_node="a", to_node="b"))
        executor.add_edge(WorkflowEdge(from_node="b", to_node="a"))

        errors = executor.validate()
        assert len(errors) > 0
        assert any("cycle" in e.lower() for e in errors)


# ---------------------------------------------------------------------------
# Class 3: TestApplyPathContract — train → save → load_apply
# ---------------------------------------------------------------------------


class TestApplyPathContract:
    """Verify the model artifact save → load_apply roundtrip.

    Training nodes (PCA etc.) require SpectroChemPy, so we create a
    PCA-shaped artifact manually via ModelStore and test load_apply
    against it.  This isolates the contract between ModelStore and
    LoadApplyModelNode.
    """

    @pytest.fixture
    def pca_artifact(self, model_store):
        """Save a synthetic PCA artifact and return (model_store, uid)."""
        rng = np.random.default_rng(42)
        uid = "contract-test-pca-001"
        manifest = {
            "model_type": "pca",
            "format_version": "1.0",
            "n_features": 50,
            "n_components": 3,
        }
        arrays = {
            "loadings": rng.standard_normal((3, 50)).astype(np.float64),
            "mean": rng.standard_normal(50).astype(np.float64),
            "explained_variance_ratio": np.array([0.6, 0.25, 0.1], dtype=np.float64),
            "explained_variance": np.array([3.0, 1.25, 0.5], dtype=np.float64),
        }
        model_store.save(uid, manifest, arrays)
        return model_store, uid, arrays

    @pytest.mark.asyncio
    async def test_pca_save_then_load_apply(self, pca_artifact, spectral_dataset, monkeypatch):
        """Saved PCA artifact → load_apply → produces scores with correct shape."""
        store, uid, arrays = pca_artifact

        # Patch global model store so LoadApplyModelNode can find it
        monkeypatch.setattr(
            "spectra_sherpa.app.services.dag.nodes.modeling.load_apply_node.get_model_store",
            lambda: store,
        )

        node = node_registry.create_node("model.load_apply", "apply", {"model_id": uid})
        result = await node.run(X_new=spectral_dataset)
        outputs = result.outputs

        assert "result" in outputs
        assert "model_id" in outputs
        assert outputs["model_id"] == uid

        # PCA transform: (10 samples, 50 features) @ (50, 3).T → (10, 3)
        scores = outputs["result"]
        assert isinstance(scores, np.ndarray)
        assert scores.shape == (10, 3)

    @pytest.mark.asyncio
    async def test_load_apply_rejects_missing_model(self, model_store, monkeypatch):
        """model.load_apply with bogus model_id → clear ValueError."""
        monkeypatch.setattr(
            "spectra_sherpa.app.services.dag.nodes.modeling.load_apply_node.get_model_store",
            lambda: model_store,
        )
        node = node_registry.create_node("model.load_apply", "apply", {"model_id": "nonexistent-uid"})
        dummy = SherpaDataset(X=np.ones((2, 10)))

        with pytest.raises(ValueError, match="not found"):
            await node.run(X_new=dummy)


# ---------------------------------------------------------------------------
# Class 4: TestDeployPathContract — headless prediction simulation
# ---------------------------------------------------------------------------


class TestDeployPathContract:
    """Verify the deploy.input → processing → deploy.output pipeline."""

    @pytest.mark.asyncio
    async def test_deploy_input_output_roundtrip(self, executor, spectral_dataset):
        """deploy.input → snv → deploy.output with injected data → result dict has expected structure."""
        from spectra_sherpa.app.services.dag.executor import WorkflowEdge, WorkflowNode

        executor.add_node(WorkflowNode(node_id="d_in", node_type="deploy.input", parameters={"stream_name": "sample"}))
        executor.add_node(WorkflowNode(node_id="snv", node_type="preprocess.normalize", parameters={"method": "snv"}))
        executor.add_node(
            WorkflowNode(node_id="d_out", node_type="deploy.output", parameters={"output_format": "json"})
        )
        executor.add_edge(WorkflowEdge(from_node="d_in", to_node="snv"))
        executor.add_edge(WorkflowEdge(from_node="snv", to_node="d_out"))

        # Inject real data into the deploy.input node
        executor.inject_result("d_in", {"default": spectral_dataset})

        results = await executor.execute()
        outputs = results["d_out"]

        assert "format" in outputs
        assert outputs["format"] == "json"
        assert "content" in outputs
        assert "raw_payload" in outputs

    def test_executor_deepcopy_preserves_graph(self, executor):
        """deepcopy(executor) → clone has same nodes/edges, independent execution."""
        from spectra_sherpa.app.services.dag.executor import WorkflowEdge, WorkflowNode

        executor.add_node(
            WorkflowNode(
                node_id="src", node_type="data.source", parameters={"source": "sklearn", "sklearn_dataset": "iris"}
            )
        )
        executor.add_node(WorkflowNode(node_id="snv", node_type="preprocess.normalize", parameters={"method": "snv"}))
        executor.add_edge(WorkflowEdge(from_node="src", to_node="snv"))

        clone = copy.deepcopy(executor)
        assert set(clone.nodes.keys()) == {"src", "snv"}
        assert len(clone.edges) == 1
        # Clone is independent
        assert clone.nodes is not executor.nodes
        assert clone.edges is not executor.edges

    @pytest.mark.asyncio
    async def test_inject_result_skips_source(self, executor, spectral_dataset):
        """inject_result() → source not re-executed, downstream runs."""
        from spectra_sherpa.app.services.dag.executor import WorkflowEdge, WorkflowNode

        executor.add_node(WorkflowNode(node_id="src", node_type="deploy.input", parameters={"stream_name": "sample"}))
        executor.add_node(WorkflowNode(node_id="snv", node_type="preprocess.normalize", parameters={"method": "snv"}))
        executor.add_edge(WorkflowEdge(from_node="src", to_node="snv"))

        # Inject a pre-computed result for the source
        executor.inject_result("src", {"default": spectral_dataset})

        results = await executor.execute()

        # Source result is our injected data
        assert "src" in results
        src_default = results["src"]["default"]
        assert src_default is spectral_dataset

        # SNV ran on the injected data
        assert "snv" in results
        snv_out = results["snv"]["default"]
        assert isinstance(snv_out, SherpaDataset)
        assert snv_out.shape == spectral_dataset.shape

    def test_executor_pickle_protocol(self, executor):
        """__getstate__ excludes pool, __setstate__ reconnects via get_default_pool()."""
        state = executor.__getstate__()
        assert state["_process_pool"] is None

        new_executor = object.__new__(type(executor))
        new_executor.__setstate__(state)
        # Pool restored from global default (None in test env)
        assert hasattr(new_executor, "_process_pool")


# ---------------------------------------------------------------------------
# Class 5: TestCustomAlgoContract — dynamic node registration
# ---------------------------------------------------------------------------


class TestCustomAlgoContract:
    """Verify dynamic node registration and custom offload policies."""

    @pytest.fixture(autouse=True)
    def _cleanup_custom_node(self):
        """Ensure the test node type is removed after the test."""
        yield
        try:
            node_registry.unregister("_test.contract_custom")
        except (ValueError, KeyError):
            pass

    @pytest.mark.asyncio
    async def test_custom_node_registers_and_executes(self, spectral_dataset):
        """Dynamically register a node class → build workflow → execute → produces output."""

        @register_node
        class _ContractCustomNode(Node):
            metadata = NodeMetadata(
                node_type="_test.contract_custom",
                category="custom",
                label="Contract Test Custom",
                description="Test node for contract tests",
                parameters=[
                    NodeParameter(
                        name="scale_factor",
                        label="Scale Factor",
                        param_type="number",
                        default=2.0,
                    ),
                ],
                input_types=["NDDataset"],
                output_type="NDDataset",
            )

            async def execute(self, input_data: Any = None, **kwargs: Any) -> Any:
                if input_data is None:
                    input_data = kwargs.get("default")
                factor = self.parameters.get("scale_factor", 2.0)
                if isinstance(input_data, SherpaDataset):
                    return SherpaDataset(
                        X=input_data.X * factor,
                        feature_axis=input_data.feature_axis,
                        sample_axis=input_data.sample_axis,
                        backend=input_data.backend,
                        title=input_data.title,
                    )
                return input_data

        # Verify registered
        assert node_registry.get_node_class("_test.contract_custom") is _ContractCustomNode

        # Create and execute
        node = node_registry.create_node("_test.contract_custom", "custom1", {"scale_factor": 3.0})
        result = await node.run(default=spectral_dataset)
        out = result.outputs["default"]

        assert isinstance(out, SherpaDataset)
        np.testing.assert_allclose(out.X, spectral_dataset.X * 3.0)

    def test_custom_node_respects_offload_policy(self):
        """Node with offload_to_pool=False → _should_offload() returns False."""
        from spectra_sherpa.app.services.dag.executor import DAGExecutor
        from spectra_sherpa.app.services.dag.node_base import NodePolicy

        @register_node
        class _ContractCustomNode(Node):
            metadata = NodeMetadata(
                node_type="_test.contract_custom",
                category="custom",
                label="Contract Test No-Pool",
                description="Test node with offload disabled",
                policy=NodePolicy(offload_to_pool=False),
            )

            async def execute(self, *args: Any, **kwargs: Any) -> Any:
                return None

        node = _ContractCustomNode("test", {})
        executor = DAGExecutor(process_pool=None)
        assert executor._should_offload(node) is False
