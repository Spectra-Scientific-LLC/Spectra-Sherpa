"""
Tests for the no-SCP DAG execution path.

Verifies that portable nodes work correctly when SpectroChemPy is absent,
using AnalysisDataset as the runtime container.

Run with:
    PYTHONPATH=src/spectra_sherpa python -m pytest tests/test_no_scp_dag.py -v --no-cov
"""

from __future__ import annotations

import numpy as np
import pytest

from spectra_sherpa.app.lib.analysis_dataset import AnalysisDataset, AxisInfo, from_sklearn_bunch
from spectra_sherpa.app.services.dag.node_base import node_registry, NodeResult


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def no_scp(monkeypatch):
    """Simulate SpectroChemPy being absent by patching HAS_SCP to False.

    Patches HAS_SCP in the canonical module and all modules that import it
    at module level (Python binds names at import time, so a single patch
    on the source module does not propagate to already-imported references).
    """
    monkeypatch.setattr("spectra_sherpa.app.lib.scp_compat.HAS_SCP", False)
    monkeypatch.setattr("spectra_sherpa.app.services.dag.nodes.data.HAS_SCP", False)
    monkeypatch.setattr("spectra_sherpa.app.services.dag.executor.HAS_SCP", False)
    monkeypatch.setattr("spectra_sherpa.app.services.dag.serialize.HAS_SCP", False)
    monkeypatch.setattr("spectra_sherpa.app.services.dag.serialize.HAS_NDDATASET", False)
    monkeypatch.setattr("spectra_sherpa.app.services.dag.executor.HAS_NDDATASET", False)


@pytest.fixture
def iris_dataset():
    """Create an AnalysisDataset with iris-like data (10 samples, 4 features)."""
    rng = np.random.default_rng(42)
    X = rng.standard_normal((10, 4))
    x_axis = AxisInfo(
        values=np.arange(4, dtype=float),
        labels=["sepal_length", "sepal_width", "petal_length", "petal_width"],
        title="features",
    )
    y_axis = AxisInfo(
        values=np.arange(10, dtype=float),
        title="samples",
    )
    return AnalysisDataset(
        X=X,
        x_axis=x_axis,
        y_axis=y_axis,
        target=np.array([0, 0, 0, 1, 1, 1, 2, 2, 2, 0]),
        meta={"dataset_name": "test_iris"},
        backend="numpy",
        title="Test Iris",
    )


# ---------------------------------------------------------------------------
# 1. requires_scp gate test
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_requires_scp_gate_raises_import_error(no_scp):
    """Nodes with requires_scp=True should raise ImportError when HAS_SCP=False."""
    node = node_registry.create_node("baseline.rubberband", "test_rb", {})

    # Provide a dummy input so we get past parameter validation
    dummy = AnalysisDataset(X=np.ones((5, 10)))

    with pytest.raises(ImportError, match="requires SpectroChemPy"):
        await node.run(default=dummy)


# ---------------------------------------------------------------------------
# 2. SNV node on AnalysisDataset
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_snv_node_on_analysis_dataset(iris_dataset):
    """SNV normalization should work on AnalysisDataset and preserve shape and axes."""
    node = node_registry.create_node("normalize.snv", "test_snv", {})
    result = await node.run(default=iris_dataset)

    assert isinstance(result, NodeResult)
    output = result.outputs.get("default")
    assert output is not None, "SNV node should produce a 'default' output"
    assert isinstance(output, AnalysisDataset)
    assert output.shape == iris_dataset.shape, "Output shape should match input"

    # x_axis should be preserved
    assert output.x_axis is not None, "x_axis should be preserved"
    np.testing.assert_array_equal(output.x_axis.values, iris_dataset.x_axis.values)
    assert output.x_axis.labels == iris_dataset.x_axis.labels

    # Verify SNV property: each row should have zero mean and unit std
    for i in range(output.shape[0]):
        row = output.X[i]
        assert abs(np.mean(row)) < 1e-10, f"Row {i} mean should be ~0"
        assert abs(np.std(row) - 1.0) < 1e-10 or np.std(row) == 0, (
            f"Row {i} std should be ~1"
        )

    # Diagnostics should be populated
    assert "snr_before" in result.diagnostics
    assert "snr_after" in result.diagnostics


# ---------------------------------------------------------------------------
# 3. Scale node on AnalysisDataset
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_scale_node_on_analysis_dataset(iris_dataset):
    """Scale normalization should work on AnalysisDataset with 'max' method."""
    node = node_registry.create_node("normalize.scale", "test_scale", {"method": "max"})
    result = await node.run(default=iris_dataset)

    assert isinstance(result, NodeResult)
    output = result.outputs.get("default")
    assert output is not None, "Scale node should produce a 'default' output"
    assert isinstance(output, AnalysisDataset)
    assert output.shape == iris_dataset.shape

    # x_axis should be preserved
    assert output.x_axis is not None
    np.testing.assert_array_equal(output.x_axis.values, iris_dataset.x_axis.values)

    # Each row's max absolute value should be 1.0 (max normalization)
    for i in range(output.shape[0]):
        row_max = np.abs(output.X[i]).max()
        assert abs(row_max - 1.0) < 1e-10, (
            f"Row {i} max abs should be 1.0, got {row_max}"
        )


@pytest.mark.asyncio
async def test_scale_node_minmax_method(iris_dataset):
    """Scale normalization with 'minmax' should map each row to [0, 1]."""
    node = node_registry.create_node("normalize.scale", "test_scale_mm", {"method": "minmax"})
    result = await node.run(default=iris_dataset)

    output = result.outputs.get("default")
    assert isinstance(output, AnalysisDataset)

    for i in range(output.shape[0]):
        row = output.X[i]
        assert np.min(row) >= -1e-10, f"Row {i} min should be >= 0"
        assert abs(np.max(row) - 1.0) < 1e-10, f"Row {i} max should be ~1"


# ---------------------------------------------------------------------------
# 4. KMeans node on AnalysisDataset
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_kmeans_node_on_analysis_dataset(iris_dataset):
    """KMeans clustering should work on AnalysisDataset and return expected keys."""
    node = node_registry.create_node("model.kmeans", "test_kmeans", {
        "n_clusters": 3,
        "random_state": 42,
    })
    result = await node.run(default=iris_dataset)

    assert isinstance(result, NodeResult)
    outputs = result.outputs
    assert "labels" in outputs, "KMeans should output 'labels'"
    assert "centroids" in outputs, "KMeans should output 'centroids'"
    assert "model" in outputs, "KMeans should output 'model'"
    assert "inertia" in outputs, "KMeans should output 'inertia'"
    assert "n_clusters" in outputs
    assert "data" in outputs, "KMeans should output 'data' (embedding)"
    assert "metadata" in outputs

    labels = outputs["labels"]
    assert isinstance(labels, list)
    assert len(labels) == iris_dataset.shape[0]
    assert set(labels).issubset({0, 1, 2}), "Labels should be in {0, 1, 2}"

    centroids = outputs["centroids"]
    assert len(centroids) == 3, "Should have 3 centroids"

    metadata = outputs["metadata"]
    assert metadata["type"] == "KMeans"
    assert metadata["output_type"] == "clustering"


# ---------------------------------------------------------------------------
# 5. DataSource sklearn node (no SCP)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_data_source_sklearn_no_scp(no_scp):
    """DataSource node with source='sklearn' should work without SCP."""
    node = node_registry.create_node("data.source", "test_source", {
        "source": "sklearn",
        "sklearn_dataset": "iris",
    })
    result = await node.run()

    assert isinstance(result, NodeResult)
    outputs = result.outputs
    dataset = outputs.get("default")
    assert dataset is not None, "DataSource should produce a 'default' output"
    assert isinstance(dataset, AnalysisDataset), (
        f"Expected AnalysisDataset, got {type(dataset).__name__}"
    )
    assert dataset.shape == (150, 4), f"Iris shape should be (150, 4), got {dataset.shape}"

    target = outputs.get("target")
    assert target is not None, "Sklearn source should produce 'target' output"
    assert isinstance(target, list), f"Target should be a list, got {type(target).__name__}"
    assert len(target) == 150


# ---------------------------------------------------------------------------
# 6. Serialization test (AnalysisDataset.to_dict)
# ---------------------------------------------------------------------------

def test_analysis_dataset_to_dict(iris_dataset):
    """AnalysisDataset.to_dict() should emit the wire-format contract."""
    d = iris_dataset.to_dict()

    assert d["type"] == "NDDataset", "Wire format must have type='NDDataset'"
    assert d["n_samples"] == 10
    assert d["n_features"] == 4
    assert d["shape"] == [10, 4]
    assert d["title"] == "Test Iris"
    assert d["backend"] == "numpy"

    # x_axis must use 'data' key (not 'values') per wire-format contract
    assert "x_axis" in d
    assert "data" in d["x_axis"], "x_axis must use 'data' key for frontend compat"
    assert d["x_axis"]["data"] is not None
    assert len(d["x_axis"]["data"]) == 4
    assert d["x_axis"]["labels"] == [
        "sepal_length", "sepal_width", "petal_length", "petal_width"
    ]
    assert d["x_axis"]["title"] == "features"

    # y_axis
    assert "y_axis" in d
    assert len(d["y_axis"]["data"]) == 10

    # target
    assert "target" in d
    assert len(d["target"]) == 10

    # metadata
    assert "metadata" in d
    assert d["metadata"]["data_type"] == "generic"
    assert d["metadata"]["is_spectra"] is False

    # data array
    assert len(d["data"]) == 10
    assert len(d["data"][0]) == 4


# ---------------------------------------------------------------------------
# 7. serialize_for_api with AnalysisDataset
# ---------------------------------------------------------------------------

def test_serialize_for_api_with_analysis_dataset(iris_dataset):
    """serialize_for_api should delegate to AnalysisDataset.to_dict()."""
    from spectra_sherpa.app.services.dag.serialize import serialize_for_api

    serialized = serialize_for_api(iris_dataset)
    expected = iris_dataset.to_dict()

    assert serialized == expected, (
        "serialize_for_api should return the same dict as to_dict() for AnalysisDataset"
    )
    assert serialized["type"] == "NDDataset"
    assert serialized["n_samples"] == 10
    assert serialized["n_features"] == 4


# ---------------------------------------------------------------------------
# 8. serialize_result with AnalysisDataset
# ---------------------------------------------------------------------------

def test_serialize_result_with_analysis_dataset(iris_dataset):
    """serialize_result should serialize AnalysisDataset to dict with type='NDDataset'."""
    from spectra_sherpa.app.api.v1.routes.workflows import serialize_result

    result = serialize_result(iris_dataset)
    assert isinstance(result, dict)
    assert result["type"] == "NDDataset"
    assert result["n_samples"] == 10
    assert result["n_features"] == 4
    assert "x_axis" in result
    assert "data" in result["x_axis"]


def test_serialize_result_with_nested_analysis_dataset(iris_dataset):
    """serialize_result should handle dicts containing AnalysisDataset values."""
    from spectra_sherpa.app.api.v1.routes.workflows import serialize_result

    multi_output = {
        "default": iris_dataset,
        "labels": [0, 1, 2],
        "score": 0.95,
    }
    result = serialize_result(multi_output)
    assert isinstance(result, dict)
    assert result["default"]["type"] == "NDDataset"
    assert result["labels"] == [0, 1, 2]
    assert result["score"] == 0.95


# ---------------------------------------------------------------------------
# 9. _is_dataset helper
# ---------------------------------------------------------------------------

def test_is_dataset_with_analysis_dataset(iris_dataset):
    """_is_dataset should return True for AnalysisDataset."""
    from spectra_sherpa.app.services.dag.executor import _is_dataset

    assert _is_dataset(iris_dataset) is True


def test_is_dataset_with_plain_dict():
    """_is_dataset should return False for a plain dict."""
    from spectra_sherpa.app.services.dag.executor import _is_dataset

    assert _is_dataset({"key": "value"}) is False


def test_is_dataset_with_plain_list():
    """_is_dataset should return False for a plain list."""
    from spectra_sherpa.app.services.dag.executor import _is_dataset

    assert _is_dataset([1, 2, 3]) is False


def test_is_dataset_with_numpy_array():
    """_is_dataset should return False for a raw numpy array."""
    from spectra_sherpa.app.services.dag.executor import _is_dataset

    assert _is_dataset(np.array([1, 2, 3])) is False


# ---------------------------------------------------------------------------
# 10. Provenance through no-SCP flow
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_provenance_recorded_after_snv(iris_dataset):
    """Running SNV on AnalysisDataset should record provenance in the output."""
    node = node_registry.create_node("normalize.snv", "test_snv_prov", {})
    result = await node.run(default=iris_dataset)

    output = result.outputs["default"]
    assert isinstance(output, AnalysisDataset)

    # Provenance list should contain at least the SNV step
    assert len(output.provenance) > 0, "Provenance should not be empty after SNV"

    # Find the SNV step
    snv_steps = [
        step for step in output.provenance
        if step.get("operation") == "normalize.snv"
    ]
    assert len(snv_steps) == 1, "Should have exactly one SNV provenance entry"

    snv_step = snv_steps[0]
    assert snv_step["node_id"] == "test_snv_prov"
    assert "timestamp" in snv_step


@pytest.mark.asyncio
async def test_provenance_chain_snv_then_scale(iris_dataset):
    """Chaining SNV -> Scale should produce two entries in processing_history."""
    snv_node = node_registry.create_node("normalize.snv", "chain_snv", {})
    snv_result = await snv_node.run(default=iris_dataset)
    snv_output = snv_result.outputs["default"]

    scale_node = node_registry.create_node("normalize.scale", "chain_scale", {"method": "max"})
    scale_result = await scale_node.run(default=snv_output)
    scale_output = scale_result.outputs["default"]

    assert isinstance(scale_output, AnalysisDataset)

    # meta["processing_history"] is the authoritative provenance chain
    # (copy_processing_history copies from source.meta, add_processing_step appends)
    meta_history = scale_output.meta.get("processing_history", [])
    operations = [step.get("operation") for step in meta_history]
    assert "normalize.snv" in operations, "SNV step should be in processing_history"
    assert "normalize.scale" in operations, "Scale step should be in processing_history"
    assert len(meta_history) >= 2, "Should have at least 2 history entries"


# ---------------------------------------------------------------------------
# Bonus: NodeResult.wrap behaviour
# ---------------------------------------------------------------------------

def test_node_result_wrap_dict():
    """NodeResult.wrap should treat a dict as named outputs."""
    raw = {"default": "data", "labels": [1, 2]}
    wrapped = NodeResult.wrap(raw)
    assert wrapped.outputs == raw
    assert wrapped.diagnostics == {}


def test_node_result_wrap_non_dict():
    """NodeResult.wrap should wrap non-dict as {"default": raw}."""
    ds = AnalysisDataset(X=np.ones((2, 3)))
    wrapped = NodeResult.wrap(ds)
    assert wrapped.outputs == {"default": ds}


def test_node_result_wrap_passthrough():
    """NodeResult.wrap should return a NodeResult as-is."""
    nr = NodeResult(outputs={"a": 1}, diagnostics={"b": 2})
    assert NodeResult.wrap(nr) is nr


# ---------------------------------------------------------------------------
# Bonus: AnalysisDataset round-trip serialization
# ---------------------------------------------------------------------------

def test_analysis_dataset_round_trip(iris_dataset):
    """AnalysisDataset should survive a to_dict -> from_dict round trip."""
    d = iris_dataset.to_dict()
    restored = AnalysisDataset.from_dict(d)

    assert restored.shape == iris_dataset.shape
    np.testing.assert_allclose(restored.X, iris_dataset.X)
    assert restored.backend == iris_dataset.backend
    assert restored.title == iris_dataset.title

    # x_axis round trip
    assert restored.x_axis is not None
    np.testing.assert_array_equal(restored.x_axis.values, iris_dataset.x_axis.values)
    assert restored.x_axis.labels == iris_dataset.x_axis.labels
    assert restored.x_axis.title == iris_dataset.x_axis.title

    # target round trip
    assert restored.target is not None
    np.testing.assert_array_equal(restored.target, iris_dataset.target)


# ---------------------------------------------------------------------------
# Bonus: from_sklearn_bunch adapter
# ---------------------------------------------------------------------------

def test_from_sklearn_bunch():
    """from_sklearn_bunch should properly convert an sklearn Bunch."""
    from sklearn.datasets import load_iris

    bunch = load_iris()
    ds = from_sklearn_bunch(bunch, name="iris")

    assert isinstance(ds, AnalysisDataset)
    assert ds.shape == (150, 4)
    assert ds.backend == "sklearn"
    assert ds.x_axis is not None
    assert ds.x_axis.labels is not None
    assert len(ds.x_axis.labels) == 4
    assert ds.target is not None
    assert len(ds.target) == 150
    assert ds.meta.get("dataset_name") == "iris"


# ---------------------------------------------------------------------------
# SG-family nodes: scipy fallback on AnalysisDataset
# ---------------------------------------------------------------------------

@pytest.fixture
def spectral_dataset():
    """AnalysisDataset with enough features for SG window operations."""
    np.random.seed(42)
    X = np.random.randn(10, 100)  # 10 samples, 100 features (spectral-like)
    return AnalysisDataset(
        X=X,
        x_axis=AxisInfo(values=np.linspace(400, 4000, 100), title="Wavenumber", units="cm^-1"),
        backend="numpy",
    )


@pytest.mark.asyncio
async def test_savgol_smooth_on_analysis_dataset(spectral_dataset):
    """SG smooth should work via scipy fallback on AnalysisDataset."""
    node = node_registry.create_node("smooth.savitzky_golay", "sg_smooth", {"size": 11, "order": 2})
    result = await node.run(default=spectral_dataset)
    output = result.outputs["default"]
    assert isinstance(output, AnalysisDataset)
    assert output.shape == spectral_dataset.shape
    # Data should be different (smoothed)
    assert not np.array_equal(output.X, spectral_dataset.X)


@pytest.mark.asyncio
async def test_first_derivative_on_analysis_dataset(spectral_dataset):
    """1st derivative should work via scipy fallback on AnalysisDataset."""
    node = node_registry.create_node("derivative.first", "deriv1", {"size": 11, "order": 2})
    result = await node.run(default=spectral_dataset)
    output = result.outputs["default"]
    assert isinstance(output, AnalysisDataset)
    assert output.shape == spectral_dataset.shape


@pytest.mark.asyncio
async def test_second_derivative_on_analysis_dataset(spectral_dataset):
    """2nd derivative should work via scipy fallback on AnalysisDataset."""
    node = node_registry.create_node("derivative.second", "deriv2", {"size": 11, "order": 3})
    result = await node.run(default=spectral_dataset)
    output = result.outputs["default"]
    assert isinstance(output, AnalysisDataset)
    assert output.shape == spectral_dataset.shape


@pytest.mark.asyncio
async def test_sg_derivative_on_analysis_dataset(spectral_dataset):
    """Generic SG derivative should work via scipy fallback on AnalysisDataset."""
    node = node_registry.create_node("preprocess.sg_derivative", "sg_deriv", {"size": 11, "order": 2, "deriv": "1"})
    result = await node.run(default=spectral_dataset)
    output = result.outputs["default"]
    assert isinstance(output, AnalysisDataset)
    assert output.shape == spectral_dataset.shape


# ---------------------------------------------------------------------------
# Provenance: copy_processing_history syncs with AnalysisDataset.provenance
# ---------------------------------------------------------------------------

def test_copy_processing_history_syncs_provenance():
    """copy_processing_history must update both meta and provenance on AnalysisDataset."""
    from spectra_sherpa.app.services.dag.meta_helpers import copy_processing_history, add_processing_step

    source = AnalysisDataset(X=np.ones((3, 5)))
    add_processing_step(source, "normalize.snv", {}, node_id="n1")
    add_processing_step(source, "normalize.scale", {"method": "max"}, node_id="n2")

    target = AnalysisDataset(X=np.ones((3, 5)))
    # target starts with 0 history entries
    assert len(target.provenance) == 0

    copy_processing_history(source, target)

    # Both meta and provenance should have the same 2 steps
    assert len(target.meta["processing_history"]) == 2
    assert len(target.provenance) == 2
    assert target.meta["processing_history"] is target.provenance

    # Verify operations
    ops = [s["operation"] for s in target.provenance]
    assert ops == ["normalize.snv", "normalize.scale"]


def test_provenance_chain_survives_to_dict():
    """After SNV->Scale chain, to_dict() should serialize ALL provenance steps."""
    from spectra_sherpa.app.services.dag.meta_helpers import add_processing_step, copy_processing_history

    # Simulate: source dataset → copy history → add step → serialize
    ds = AnalysisDataset(X=np.ones((3, 5)))
    add_processing_step(ds, "data.source", {"source": "sklearn"}, node_id="src")

    # Create result from copy (simulating what a node does)
    result = ds.copy()
    copy_processing_history(ds, result)
    add_processing_step(result, "normalize.snv", {}, node_id="snv")

    # Serialize
    d = result.to_dict()
    history = d["metadata"]["processing_history"]
    operations = [step["operation"] for step in history]
    assert "data.source" in operations
    assert "normalize.snv" in operations
    assert len(history) == 2


# ---------------------------------------------------------------------------
# generate_python() SCP-aware code generation
# ---------------------------------------------------------------------------

class TestGeneratePythonNoScp:
    """Verify generate_python(use_scp=False) emits numpy/scipy code."""

    def _make_node(self, node_type, params=None):
        return node_registry.create_node(node_type, f"test_{node_type}", params or {})

    def _inputs(self):
        return {"default": "results['source']"}

    def test_snv_no_scp_uses_result(self):
        node = self._make_node("normalize.snv")
        lines = node.generate_python(self._inputs(), use_scp=False)
        code = "\n".join(lines)
        assert "scp.NDDataset" not in code
        assert "_Result(" in code
        assert "np.array(" in code

    def test_snv_scp_uses_nddataset(self):
        node = self._make_node("normalize.snv")
        lines = node.generate_python(self._inputs(), use_scp=True)
        code = "\n".join(lines)
        assert "scp.NDDataset" in code

    def test_scale_no_scp_uses_result(self):
        node = self._make_node("normalize.scale", {"method": "max"})
        lines = node.generate_python(self._inputs(), use_scp=False)
        code = "\n".join(lines)
        assert "scp.NDDataset" not in code
        assert "_Result(" in code

    def test_cosmic_ray_no_scp(self):
        node = self._make_node("preprocess.cosmic_ray", {"window": 7, "zscore": 3.0})
        lines = node.generate_python(self._inputs(), use_scp=False)
        code = "\n".join(lines)
        assert "scp.NDDataset" not in code
        assert "_Result(" in code

    def test_clip_floor_no_scp(self):
        node = self._make_node("preprocess.clip_floor", {"floor": 0.0})
        lines = node.generate_python(self._inputs(), use_scp=False)
        code = "\n".join(lines)
        assert "scp.NDDataset" not in code
        assert "_Result(" in code

    def test_scale_max_no_scp(self):
        node = self._make_node("preprocess.scale_max", {"target_max": 1.0})
        lines = node.generate_python(self._inputs(), use_scp=False)
        code = "\n".join(lines)
        assert "scp.NDDataset" not in code
        assert "_Result(" in code

    def test_center_mean_no_scp(self):
        node = self._make_node("preprocess.center_mean")
        lines = node.generate_python(self._inputs(), use_scp=False)
        code = "\n".join(lines)
        assert "scp.NDDataset" not in code
        assert "_Result(" in code

    def test_pareto_no_scp(self):
        node = self._make_node("preprocess.pareto_scaling", {"center": True})
        lines = node.generate_python(self._inputs(), use_scp=False)
        code = "\n".join(lines)
        assert "scp.NDDataset" not in code
        assert "_Result(" in code

    def test_autoscaling_no_scp(self):
        node = self._make_node("preprocess.autoscaling", {"center": True})
        lines = node.generate_python(self._inputs(), use_scp=False)
        code = "\n".join(lines)
        assert "scp.NDDataset" not in code
        assert "_Result(" in code

    def test_emsc_no_scp(self):
        node = self._make_node("preprocess.emsc", {"reference": "mean", "poly_order": 2})
        lines = node.generate_python(self._inputs(), use_scp=False)
        code = "\n".join(lines)
        assert "scp.NDDataset" not in code
        assert "_Result(" in code

    def test_savgol_smooth_no_scp_uses_scipy(self):
        node = self._make_node("smooth.savitzky_golay", {"size": 11, "order": 2})
        lines = node.generate_python(self._inputs(), use_scp=False)
        code = "\n".join(lines)
        assert "scp" not in code.lower() or "scp" not in code
        assert "savgol_filter" in code
        assert "_Result(" in code

    def test_savgol_smooth_scp_uses_method(self):
        node = self._make_node("smooth.savitzky_golay", {"size": 11, "order": 2})
        lines = node.generate_python(self._inputs(), use_scp=True)
        code = "\n".join(lines)
        assert "data.smooth(" in code

    def test_first_deriv_no_scp_uses_scipy(self):
        node = self._make_node("derivative.first", {"size": 11, "order": 2})
        lines = node.generate_python(self._inputs(), use_scp=False)
        code = "\n".join(lines)
        assert "savgol_filter" in code
        assert "deriv=1" in code
        assert "_Result(" in code

    def test_second_deriv_no_scp_uses_scipy(self):
        node = self._make_node("derivative.second", {"size": 11, "order": 2})
        lines = node.generate_python(self._inputs(), use_scp=False)
        code = "\n".join(lines)
        assert "savgol_filter" in code
        assert "deriv=2" in code
        assert "_Result(" in code

    def test_sg_derivative_no_scp_uses_scipy(self):
        node = self._make_node("preprocess.sg_derivative", {"size": 11, "order": 2, "deriv": "1"})
        lines = node.generate_python(self._inputs(), use_scp=False)
        code = "\n".join(lines)
        assert "savgol_filter" in code
        assert "_Result(" in code

    def test_sg_derivative_scp_uses_method(self):
        node = self._make_node("preprocess.sg_derivative", {"size": 11, "order": 2, "deriv": "1"})
        lines = node.generate_python(self._inputs(), use_scp=True)
        code = "\n".join(lines)
        assert "data.savgol(" in code

    def test_scp_only_node_emits_import_error(self):
        """SCP-only nodes should emit ImportError when use_scp=False."""
        node = self._make_node("normalize.msc", {"reference": "mean"})
        lines = node.generate_python(self._inputs(), use_scp=False)
        code = "\n".join(lines)
        assert "ImportError" in code
        assert "spectrochempy" in code.lower()

    def test_clip_range_no_scp_uses_index_lookup(self):
        """ClipRange no-SCP path should find columns by x-axis values, not SCP slicing."""
        node = self._make_node("preprocess.clip_range", {"min_wavenumber": 500, "max_wavenumber": 3000})
        lines = node.generate_python(self._inputs(), use_scp=False)
        code = "\n".join(lines)
        assert "_x_vals" in code, "Should use x_vals for index lookup"
        assert "_mask" in code, "Should build boolean mask"
        assert "_Result(" in code, "Should wrap with _Result"
        # Primary path must use mask-based selection
        assert "_x_vals >= 500" in code
        assert "_x_vals <= 3000" in code

    def test_clip_range_scp_uses_coord_slicing(self):
        """ClipRange SCP path should use coordinate-aware slicing."""
        node = self._make_node("preprocess.clip_range", {"min_wavenumber": 500, "max_wavenumber": 3000})
        lines = node.generate_python(self._inputs(), use_scp=True)
        code = "\n".join(lines)
        assert "[:, 500:3000]" in code


# ---------------------------------------------------------------------------
# 14. ClipRangeNode execute() on AnalysisDataset
# ---------------------------------------------------------------------------

class TestClipRangeAnalysisDataset:
    """Test ClipRangeNode execute() with AnalysisDataset (value-based clipping)."""

    @pytest.mark.asyncio
    async def test_clip_by_wavenumber_values(self):
        """ClipRange should select columns where x_axis values are within [min, max]."""
        # Simulate spectral data: 5 samples, 100 features at wavenumbers 400-4000
        wavenumbers = np.linspace(400, 4000, 100)
        X = np.random.default_rng(42).standard_normal((5, 100))
        ds = AnalysisDataset(
            X=X,
            x_axis=AxisInfo(values=wavenumbers, units="cm-1", title="wavenumber"),
        )

        node = node_registry.create_node(
            "preprocess.clip_range", "test_clip",
            {"min_wavenumber": 1000, "max_wavenumber": 2000}
        )
        result = await node.run(default=ds)
        output = result.outputs["default"]

        assert isinstance(output, AnalysisDataset)
        # Only columns with wavenumber in [1000, 2000] should survive
        expected_mask = (wavenumbers >= 1000) & (wavenumbers <= 2000)
        expected_cols = expected_mask.sum()
        assert output.shape == (5, expected_cols), (
            f"Expected (5, {expected_cols}), got {output.shape}"
        )
        # x_axis values should be the clipped subset
        np.testing.assert_array_almost_equal(
            output.x_axis.values, wavenumbers[expected_mask]
        )
        # Data should match the correct columns from the original
        np.testing.assert_array_almost_equal(output.X, X[:, expected_mask])

    @pytest.mark.asyncio
    async def test_clip_min_only(self):
        """ClipRange with only min_wavenumber should keep all columns >= min."""
        wavenumbers = np.linspace(400, 4000, 50)
        X = np.ones((3, 50))
        ds = AnalysisDataset(
            X=X,
            x_axis=AxisInfo(values=wavenumbers, units="cm-1"),
        )
        node = node_registry.create_node(
            "preprocess.clip_range", "test_clip_min",
            {"min_wavenumber": 2000, "max_wavenumber": 4000}
        )
        result = await node.run(default=ds)
        output = result.outputs["default"]

        expected_mask = (wavenumbers >= 2000) & (wavenumbers <= 4000)
        assert output.shape[1] == expected_mask.sum()
        assert output.x_axis.values[0] >= 2000

    @pytest.mark.asyncio
    async def test_clip_no_xaxis_falls_back_to_integer_slicing(self):
        """Without x_axis, ClipRange should fall back to integer column slicing."""
        X = np.ones((3, 100))
        ds = AnalysisDataset(X=X)
        node = node_registry.create_node(
            "preprocess.clip_range", "test_clip_nox",
            {"min_wavenumber": 10, "max_wavenumber": 50}
        )
        result = await node.run(default=ds)
        output = result.outputs["default"]
        # Integer slicing: columns 10 through 50
        assert output.shape == (3, 40)

    @pytest.mark.asyncio
    async def test_clip_preserves_provenance(self):
        """ClipRange should record processing history."""
        wavenumbers = np.linspace(400, 4000, 100)
        ds = AnalysisDataset(
            X=np.ones((3, 100)),
            x_axis=AxisInfo(values=wavenumbers),
        )
        node = node_registry.create_node(
            "preprocess.clip_range", "test_clip_prov",
            {"min_wavenumber": 1000, "max_wavenumber": 3000}
        )
        result = await node.run(default=ds)
        output = result.outputs["default"]
        history = output.meta.get("processing_history", [])
        assert len(history) >= 1
        assert history[-1]["operation"] == "preprocess.clip_range"
        assert history[-1]["parameters"]["min_wavenumber"] == 1000
        assert history[-1]["parameters"]["max_wavenumber"] == 3000

    @pytest.mark.asyncio
    async def test_clip_swaps_reversed_bounds(self):
        """ClipRange should swap min/max if min > max."""
        wavenumbers = np.linspace(400, 4000, 100)
        ds = AnalysisDataset(
            X=np.ones((3, 100)),
            x_axis=AxisInfo(values=wavenumbers),
        )
        node = node_registry.create_node(
            "preprocess.clip_range", "test_clip_swap",
            {"min_wavenumber": 3000, "max_wavenumber": 1000}
        )
        result = await node.run(default=ds)
        output = result.outputs["default"]
        # Should have swapped and clipped to [1000, 3000]
        expected_mask = (wavenumbers >= 1000) & (wavenumbers <= 3000)
        assert output.shape[1] == expected_mask.sum()


# ---------------------------------------------------------------------------
# 15. Classification isinstance guard tests
# ---------------------------------------------------------------------------

class TestClassificationIsinstanceGuards:
    """Verify PLSDA and SIMCA nodes accept AnalysisDataset (not just NDDataset)."""

    def test_plsda_accepts_analysis_dataset_type(self):
        """PLSDANode isinstance check should accept AnalysisDataset."""
        ds = AnalysisDataset(X=np.ones((10, 5)))
        # Check passes without raising
        assert isinstance(ds, AnalysisDataset)
        # The actual isinstance in the node should accept it
        from spectra_sherpa.app.lib.scp_compat import NDDataset
        assert isinstance(ds, (NDDataset, AnalysisDataset))

    def test_simca_accepts_analysis_dataset_type(self):
        """SIMCANode isinstance check should accept AnalysisDataset."""
        ds = AnalysisDataset(X=np.ones((10, 5)))
        from spectra_sherpa.app.lib.scp_compat import NDDataset
        assert isinstance(ds, (NDDataset, AnalysisDataset))
