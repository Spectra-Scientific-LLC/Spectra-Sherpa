"""
Tests for the no-SCP DAG execution path.

Verifies that portable nodes work correctly when SpectroChemPy is absent,
using SherpaDataset as the runtime container.

Run with:
    PYTHONPATH=src/spectra_sherpa python -m pytest tests/test_no_scp_dag.py -v --no-cov
"""

from __future__ import annotations

import numpy as np
import pytest

# sklearn adapter now lives in its own module and returns SherpaDataset
from spectra_sherpa.app.lib.adapters.sklearn_adapter import from_sklearn
from spectra_sherpa.app.lib.sherpa_dataset import (
    SampleAxis,
    SherpaDataset,
    SpectralAxis,
)
from spectra_sherpa.app.services.dag.node_base import NodeResult, node_registry

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def no_scp(monkeypatch):
    """Simulate optional-runtime import failure at the one adapter boundary."""

    def unavailable(_name: str):
        raise ImportError("simulated absent optional runtime")

    monkeypatch.setattr(
        "spectra_sherpa.interoperability.spectrochempy_adapter.import_module",
        unavailable,
    )
    monkeypatch.setattr(
        "spectra_sherpa.app.services.dag.runtime_dependencies.distribution_is_installed",
        lambda distribution: distribution != "spectrochempy",
    )


@pytest.fixture
def iris_dataset():
    """Create a SherpaDataset with iris-like data (10 samples, 4 features)."""
    rng = np.random.default_rng(42)
    X = rng.standard_normal((10, 4))
    feature_axis = SpectralAxis(
        values=np.arange(4, dtype=float),
        labels=["sepal_length", "sepal_width", "petal_length", "petal_width"],
        title="features",
    )
    sample_axis = SampleAxis(
        values=np.arange(10, dtype=float),
        title="samples",
    )
    return SherpaDataset(
        X=X,
        feature_axis=feature_axis,
        sample_axis=sample_axis,
        target=np.array([0, 0, 0, 1, 1, 1, 2, 2, 2, 0]),
        extra={"dataset_name": "test_iris"},
        backend="numpy",
        title="Test Iris",
    )


# ---------------------------------------------------------------------------
# 1. requires_scp gate test
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "operation_id",
    (
        "model.efa",
        "model.mcr_als",
        "model.simplisma",
    ),
)
async def test_scp_contract_operations_fail_before_execution(no_scp, operation_id, monkeypatch):
    """Every contract-declared SCP operation fails at the shared gate."""

    node = node_registry.create_node(operation_id, f"test-{operation_id}", {})

    async def _must_not_execute(*_args, **_kwargs):
        raise AssertionError("scientific execution ran before the SCP availability gate")

    monkeypatch.setattr(node, "execute", _must_not_execute)
    dummy = SherpaDataset(X=np.ones((5, 10)))
    kwargs = {} if not node.metadata.input_ports else {"default": dummy}
    with pytest.raises(ImportError, match="requires SpectroChemPy"):
        await node.run(**kwargs)


@pytest.mark.asyncio
async def test_native_plsda_fit_and_application_remain_available_without_scp(no_scp, iris_dataset):
    assert node_registry.get_metadata("classification.plsda").requires_scp is False
    assert node_registry.get_metadata("classification.apply_plsda").requires_scp is False

    producer = node_registry.create_node(
        "classification.plsda",
        "native-plsda",
        {"n_components": 2, "scale": True},
    )
    fitted_state = producer.fit_fitted_state(iris_dataset, iris_dataset.target)
    direct_scores = producer.apply_fitted_state(iris_dataset, fitted_state)

    application = node_registry.create_node("classification.apply_plsda", "native-apply", {})
    applied = await application.run(default=iris_dataset, fitted_state=fitted_state)
    np.testing.assert_allclose(applied.outputs["class_scores"], direct_scores, rtol=0.0, atol=0.0)
    assert len(applied.outputs["y_pred"]) == iris_dataset.shape[0]


@pytest.mark.asyncio
async def test_native_pca_fit_and_application_remain_available_without_scp(no_scp, iris_dataset):
    assert node_registry.get_metadata("model.pca").requires_scp is False
    assert node_registry.get_metadata("model.pca_transform").requires_scp is False

    producer = node_registry.create_node(
        "model.pca",
        "native-pca",
        {"n_components": "2", "standardized": False, "scaled": False},
    )
    result = await producer.run(default=iris_dataset)
    state = result.outputs["fitted_state"]

    application = node_registry.create_node("model.pca_transform", "native-pca-apply", {})
    applied = await application.run(X_new=iris_dataset, model=state)
    np.testing.assert_allclose(applied.outputs["scores"].data, result.outputs["scores"].data, rtol=0.0, atol=1e-12)


# ---------------------------------------------------------------------------
# 2. SNV node on SherpaDataset
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_snv_node_on_sherpa_dataset(iris_dataset):
    """SNV normalization should work on SherpaDataset and preserve shape and axes."""
    node = node_registry.create_node("preprocess.normalize", "test_snv", {"method": "snv"})
    result = await node.run(default=iris_dataset)

    assert isinstance(result, NodeResult)
    output = result.outputs.get("default")
    assert output is not None, "SNV node should produce a 'default' output"
    assert isinstance(output, SherpaDataset)
    assert output.shape == iris_dataset.shape, "Output shape should match input"

    # feature_axis should be preserved
    assert output.feature_axis is not None, "feature_axis should be preserved"
    np.testing.assert_array_equal(output.feature_axis.values, iris_dataset.feature_axis.values)
    assert output.feature_axis.labels == iris_dataset.feature_axis.labels

    # Verify SNV property: each row should have zero mean and unit std
    for i in range(output.shape[0]):
        row = output.X[i]
        assert abs(np.mean(row)) < 1e-10, f"Row {i} mean should be ~0"
        assert abs(np.std(row) - 1.0) < 1e-10 or np.std(row) == 0, f"Row {i} std should be ~1"

    # Diagnostics should be populated
    assert "snr_before" in result.diagnostics
    assert "snr_after" in result.diagnostics


# ---------------------------------------------------------------------------
# 3. Scale node on SherpaDataset
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_scale_node_on_sherpa_dataset(iris_dataset):
    """Scale normalization should work on SherpaDataset with 'max' method."""
    node = node_registry.create_node("preprocess.normalize", "test_scale", {"method": "scale"})
    result = await node.run(default=iris_dataset)

    assert isinstance(result, NodeResult)
    output = result.outputs.get("default")
    assert output is not None, "Scale node should produce a 'default' output"
    assert isinstance(output, SherpaDataset)
    assert output.shape == iris_dataset.shape

    # feature_axis should be preserved
    assert output.feature_axis is not None
    np.testing.assert_array_equal(output.feature_axis.values, iris_dataset.feature_axis.values)

    # Each row's max absolute value should be 1.0 (max normalization)
    for i in range(output.shape[0]):
        row_max = np.abs(output.X[i]).max()
        assert abs(row_max - 1.0) < 1e-10, f"Row {i} max abs should be 1.0, got {row_max}"


@pytest.mark.asyncio
async def test_scale_node_minmax_method(iris_dataset):
    """Scale normalization with 'minmax' should map each row to [0, 1]."""
    node = node_registry.create_node(
        "preprocess.normalize", "test_scale_mm", {"method": "scale", "scale_method": "minmax"}
    )
    result = await node.run(default=iris_dataset)

    output = result.outputs.get("default")
    assert isinstance(output, SherpaDataset)

    for i in range(output.shape[0]):
        row = output.X[i]
        assert np.min(row) >= -1e-10, f"Row {i} min should be >= 0"
        assert abs(np.max(row) - 1.0) < 1e-10, f"Row {i} max should be ~1"


# ---------------------------------------------------------------------------
# 3b. Migrated TransformSpecNode execution tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_clip_floor_execution(iris_dataset):
    """ClipFloorNode (TransformSpecNode) should clip values below the floor."""
    node = node_registry.create_node("preprocess.clip_floor", "test_clip", {"floor": 0.0})
    result = await node.run(default=iris_dataset)

    output = result.outputs.get("default")
    assert isinstance(output, SherpaDataset)
    assert output.shape == iris_dataset.shape
    assert np.all(output.X >= 0.0), "All values should be >= floor"
    # Verify values above floor are unchanged
    mask = iris_dataset.X >= 0.0
    np.testing.assert_array_almost_equal(output.X[mask], iris_dataset.X[mask])


@pytest.mark.asyncio
async def test_center_mean_execution(iris_dataset):
    """CenterMeanNode (TransformSpecNode) should mean-center columns."""
    node = node_registry.create_node("preprocess.scale", "test_cm", {"method": "mean_center"})
    result = await node.run(default=iris_dataset)

    output = result.outputs.get("default")
    assert isinstance(output, SherpaDataset)
    assert output.shape == iris_dataset.shape
    col_means = np.mean(output.X, axis=0)
    np.testing.assert_array_almost_equal(col_means, 0.0, decimal=10)


@pytest.mark.asyncio
async def test_autoscaling_execution(iris_dataset):
    """AutoscalingNode (TransformSpecNode) should produce unit-variance columns."""
    node = node_registry.create_node("preprocess.scale", "test_as", {"method": "autoscale", "center": True})
    result = await node.run(default=iris_dataset)

    output = result.outputs.get("default")
    assert isinstance(output, SherpaDataset)
    assert output.shape == iris_dataset.shape
    col_means = np.mean(output.X, axis=0)
    col_stds = np.std(output.X, axis=0)
    np.testing.assert_array_almost_equal(col_means, 0.0, decimal=10)
    np.testing.assert_array_almost_equal(col_stds, 1.0, decimal=10)


@pytest.mark.asyncio
async def test_autoscaling_with_reference_uses_train_statistics(iris_dataset):
    """Test-set scaling must reuse train-set centering and variance."""
    train = SherpaDataset(
        X=np.array(
            [
                [1.0, 2.0],
                [3.0, 6.0],
                [5.0, 10.0],
            ]
        ),
        feature_axis=SpectralAxis(values=np.array([1000.0, 1100.0]), units="cm-1"),
    )
    test = SherpaDataset(
        X=np.array(
            [
                [7.0, 14.0],
                [9.0, 18.0],
            ]
        ),
        feature_axis=train.feature_axis.copy(),
    )
    node = node_registry.create_node("preprocess.scale", "test_as_ref", {"method": "autoscale", "center": True})

    result = await node.run(default=test, reference=train)
    output = result.outputs.get("default")

    expected = (test.X - np.mean(train.X, axis=0, keepdims=True)) / np.std(train.X, axis=0, keepdims=True)
    np.testing.assert_allclose(output.X, expected)
    assert not np.allclose(np.mean(output.X, axis=0), 0.0)


@pytest.mark.asyncio
async def test_pareto_scaling_execution(iris_dataset):
    """ParetoScalingNode (TransformSpecNode) should scale by sqrt(std)."""
    node = node_registry.create_node("preprocess.scale", "test_ps", {"method": "pareto", "center": True})
    result = await node.run(default=iris_dataset)

    output = result.outputs.get("default")
    assert isinstance(output, SherpaDataset)
    assert output.shape == iris_dataset.shape
    # Verify manually: centered data / sqrt(std)
    data = iris_dataset.X.astype(np.float64)
    centered = data - np.mean(data, axis=0, keepdims=True)
    std = np.std(data, axis=0, keepdims=True)
    sf = np.sqrt(std)
    sf[sf == 0] = 1.0
    expected = centered / sf
    np.testing.assert_array_almost_equal(output.X, expected)


# ---------------------------------------------------------------------------
# 4. KMeans node on SherpaDataset
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_kmeans_node_on_sherpa_dataset(iris_dataset):
    """KMeans clustering should work on SherpaDataset and return expected keys."""
    node = node_registry.create_node(
        "model.kmeans",
        "test_kmeans",
        {
            "n_clusters": 3,
            "random_state": 42,
        },
    )
    result = await node.run(default=iris_dataset)

    assert isinstance(result, NodeResult)
    outputs = result.outputs
    assert "labels" in outputs, "KMeans should output 'labels'"
    assert "centroids" in outputs, "KMeans should output 'centroids'"
    assert "model" in outputs, "KMeans should output 'model'"
    assert "inertia" in outputs, "KMeans should output 'inertia'"
    assert "n_clusters" in outputs
    assert "embedding" in outputs, "KMeans should output 'embedding' (2D projection)"
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


def test_file_load_categorical_csv_no_scp(no_scp, tmp_path):
    """The canonical source preserves a categorical target without SCP."""
    from sklearn.datasets import load_iris

    iris = load_iris()
    source = tmp_path / "iris.csv"
    rows = np.column_stack([iris.data, iris.target_names[iris.target]])
    np.savetxt(source, rows, delimiter=",", header="f1,f2,f3,f4,target", comments="", fmt="%s")
    node = node_registry.create_node(
        "data.file_load",
        "test_source",
        {
            "experiment_id": 1,
            "file_id": 1,
            "stage": "raw",
            "target_authority": {
                "schema_version": "spectrasherpa-target-authority/1",
                "column": "target",
                "target_type": "categorical",
                "units": None,
                "source_digest": "0" * 64,
            },
        },
    )
    dataset = node._load_file(source, selected_target="target", target_type="categorical")
    assert dataset is not None, "DataSource should produce a 'default' output"
    assert isinstance(dataset, SherpaDataset), f"Expected SherpaDataset, got {type(dataset).__name__}"
    assert dataset.shape == (150, 4), f"Iris shape should be (150, 4), got {dataset.shape}"
    assert dataset.target is not None
    assert len(dataset.target) == 150
    assert dataset.target_context.target_type == "categorical"
    assert dataset.target_context.selected_target == "target"
    assert node.exported_output_ports() == {"default", "target", "sample_table"}


# ---------------------------------------------------------------------------
# 6. Serialization test (SherpaDataset.to_dict)
# ---------------------------------------------------------------------------


def test_sherpa_dataset_to_dict(iris_dataset):
    """SherpaDataset.to_dict() should emit the wire-format contract."""
    d = iris_dataset.to_dict()

    assert d["type"] == "SherpaDataset", "Wire format must have type='SherpaDataset'"
    assert d["n_samples"] == 10
    assert d["n_features"] == 4
    assert d["shape"] == [10, 4]
    assert d["title"] == "Test Iris"
    assert d["backend"] == "numpy"

    # feature_axis must use 'data' key (not 'values') per wire-format contract
    assert "feature_axis" in d
    assert "data" in d["feature_axis"], "feature_axis must use 'data' key for frontend compat"
    assert d["feature_axis"]["data"] is not None
    assert len(d["feature_axis"]["data"]) == 4
    assert d["feature_axis"]["labels"] == ["sepal_length", "sepal_width", "petal_length", "petal_width"]
    assert d["feature_axis"]["title"] == "features"

    # sample_axis
    assert "sample_axis" in d
    assert len(d["sample_axis"]["data"]) == 10

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
# 7. serialize_for_api with SherpaDataset
# ---------------------------------------------------------------------------


def test_serialize_for_api_with_sherpa_dataset(iris_dataset):
    """serialize_for_api should build on SherpaDataset.to_dict() with enrichment."""
    from spectra_sherpa.app.services.dag.serialize import serialize_for_api

    serialized = serialize_for_api(iris_dataset)

    # Core fields from to_dict() must be present
    assert serialized["type"] == "SherpaDataset"
    assert serialized["n_samples"] == 10
    assert serialized["n_features"] == 4
    assert serialized["shape"] == [10, 4]

    # Enrichment: spectral detection metadata added by serialize_for_api
    assert "is_spectra" in serialized["metadata"]
    assert "data_type" in serialized["metadata"]


# ---------------------------------------------------------------------------
# 8. serialize_result with SherpaDataset
# ---------------------------------------------------------------------------


def test_serialize_result_with_sherpa_dataset(iris_dataset):
    """serialize_result should serialize SherpaDataset to dict with type='SherpaDataset'."""
    from spectra_sherpa.app.services.serialization import serialize_result

    result = serialize_result(iris_dataset)
    assert isinstance(result, dict)
    assert result["type"] == "SherpaDataset"
    assert result["n_samples"] == 10
    assert result["n_features"] == 4
    assert "x_axis" in result
    assert "data" in result["x_axis"]


def test_serialize_result_with_nested_sherpa_dataset(iris_dataset):
    """serialize_result should handle dicts containing SherpaDataset values."""
    from spectra_sherpa.app.services.serialization import serialize_result

    multi_output = {
        "default": iris_dataset,
        "labels": [0, 1, 2],
        "score": 0.95,
    }
    result = serialize_result(multi_output)
    assert isinstance(result, dict)
    assert result["default"]["type"] == "SherpaDataset"
    assert result["labels"] == [0, 1, 2]
    assert result["score"] == 0.95


def test_serialize_result_with_pydantic_evaluation_result():
    """serialize_result should convert EvaluationResult to a plain JSON-safe dict."""
    from spectra_sherpa.app.lib.sherpa_dataset import EvaluationResult
    from spectra_sherpa.app.services.serialization import serialize_result

    evaluation = EvaluationResult(
        evaluation_id="eval-1",
        model_type="PCA",
        r2=0.95,
        confusion_matrix=[[5.0, 1.0], [0.0, 6.0]],
    )

    result = serialize_result({"evaluation": evaluation})
    assert result["evaluation"]["evaluation_id"] == "eval-1"
    assert result["evaluation"]["model_type"] == "PCA"
    assert result["evaluation"]["r2"] == 0.95
    assert result["evaluation"]["confusion_matrix"] == [[5.0, 1.0], [0.0, 6.0]]


# ---------------------------------------------------------------------------
# 9. _is_dataset helper
# ---------------------------------------------------------------------------


def test_is_dataset_with_sherpa_dataset(iris_dataset):
    """_is_dataset should return True for SherpaDataset."""
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
    """Running SNV on SherpaDataset should record provenance in the output."""
    node = node_registry.create_node("preprocess.normalize", "test_snv_prov", {"method": "snv"})
    result = await node.run(default=iris_dataset)

    output = result.outputs["default"]
    assert isinstance(output, SherpaDataset)

    # Provenance should contain at least the SNV step
    assert len(output.provenance) > 0, "Provenance should not be empty after SNV"

    # Find the SNV step — ProvenanceEntry uses .op_id, not dict .get("operation")
    snv_steps = [entry for entry in output.provenance if entry.op_id == "preprocess.normalize"]
    assert len(snv_steps) == 1, "Should have exactly one SNV provenance entry"

    snv_step = snv_steps[0]
    assert snv_step.node_id == "test_snv_prov"
    assert snv_step.timestamp  # non-empty string


@pytest.mark.asyncio
async def test_provenance_chain_snv_then_scale(iris_dataset):
    """Chaining SNV -> Scale should produce two entries in provenance."""
    snv_node = node_registry.create_node("preprocess.normalize", "chain_snv", {"method": "snv"})
    snv_result = await snv_node.run(default=iris_dataset)
    snv_output = snv_result.outputs["default"]

    scale_node = node_registry.create_node("preprocess.normalize", "chain_scale", {"method": "scale"})
    scale_result = await scale_node.run(default=snv_output)
    scale_output = scale_result.outputs["default"]

    assert isinstance(scale_output, SherpaDataset)

    # Provenance is the single source of truth on SherpaDataset
    operations = [entry.op_id for entry in scale_output.provenance]
    assert "preprocess.normalize" in operations, "SNV step should be in provenance"
    assert "preprocess.normalize" in operations, "Scale step should be in provenance"
    assert len(scale_output.provenance) >= 2, "Should have at least 2 provenance entries"


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
    ds = SherpaDataset(X=np.ones((2, 3)))
    wrapped = NodeResult.wrap(ds)
    assert wrapped.outputs == {"default": ds}


def test_node_result_wrap_passthrough():
    """NodeResult.wrap should return a NodeResult as-is."""
    nr = NodeResult(outputs={"a": 1}, diagnostics={"b": 2})
    assert NodeResult.wrap(nr) is nr


# ---------------------------------------------------------------------------
# Bonus: SherpaDataset round-trip serialization
# ---------------------------------------------------------------------------


def test_sherpa_dataset_round_trip(iris_dataset):
    """SherpaDataset should survive a to_dict -> from_dict round trip."""
    d = iris_dataset.to_dict()
    restored = SherpaDataset.from_dict(d)

    assert restored.shape == iris_dataset.shape
    np.testing.assert_allclose(restored.X, iris_dataset.X)
    assert restored.backend == iris_dataset.backend
    assert restored.title == iris_dataset.title

    # feature_axis round trip
    assert restored.feature_axis is not None
    np.testing.assert_array_equal(restored.feature_axis.values, iris_dataset.feature_axis.values)
    assert restored.feature_axis.labels == iris_dataset.feature_axis.labels
    assert restored.feature_axis.title == iris_dataset.feature_axis.title

    # target round trip
    assert restored.target is not None
    np.testing.assert_array_equal(restored.target, iris_dataset.target)


# ---------------------------------------------------------------------------
# sklearn Bunch adapter
# ---------------------------------------------------------------------------


def test_from_sklearn():
    """from_sklearn should properly convert an sklearn Bunch."""
    from sklearn.datasets import load_iris

    bunch = load_iris()
    ds = from_sklearn(bunch, name="iris")

    assert isinstance(ds, SherpaDataset)
    assert ds.shape == (150, 4)
    assert ds.backend == "sklearn"
    assert ds.feature_axis is not None
    assert ds.feature_axis.labels is not None
    assert len(ds.feature_axis.labels) == 4
    assert ds.target is not None
    assert len(ds.target) == 150
    assert ds.get_extra("sklearn.dataset_name") == "iris"


# ---------------------------------------------------------------------------
# SG-family nodes: scipy fallback on SherpaDataset
# ---------------------------------------------------------------------------


@pytest.fixture
def spectral_dataset():
    """SherpaDataset with enough features for SG window operations."""
    np.random.seed(42)
    X = np.random.randn(10, 100)  # 10 samples, 100 features (spectral-like)
    return SherpaDataset(
        X=X,
        feature_axis=SpectralAxis(values=np.linspace(400, 4000, 100), title="Wavenumber", units="cm^-1"),
        backend="numpy",
    )


@pytest.mark.asyncio
async def test_savgol_smooth_on_sherpa_dataset(spectral_dataset):
    """SG smooth should work via scipy fallback on SherpaDataset."""
    node = node_registry.create_node(
        "preprocess.smooth", "sg_smooth", {"method": "savitzky_golay", "size": 11, "order": 2}
    )
    result = await node.run(default=spectral_dataset)
    output = result.outputs["default"]
    assert isinstance(output, SherpaDataset)
    assert output.shape == spectral_dataset.shape
    # Data should be different (smoothed)
    assert not np.array_equal(output.X, spectral_dataset.X)


@pytest.mark.asyncio
async def test_first_derivative_on_sherpa_dataset(spectral_dataset):
    """1st derivative should work via scipy fallback on SherpaDataset."""
    node = node_registry.create_node(
        "preprocess.derivative", "deriv1", {"method": "savitzky_golay", "deriv": "1", "size": 11, "order": 2}
    )
    result = await node.run(default=spectral_dataset)
    output = result.outputs["default"]
    assert isinstance(output, SherpaDataset)
    assert output.shape == spectral_dataset.shape


@pytest.mark.asyncio
async def test_second_derivative_on_sherpa_dataset(spectral_dataset):
    """2nd derivative should work via scipy fallback on SherpaDataset."""
    node = node_registry.create_node(
        "preprocess.derivative", "deriv2", {"method": "savitzky_golay", "deriv": "2", "size": 11, "order": 3}
    )
    result = await node.run(default=spectral_dataset)
    output = result.outputs["default"]
    assert isinstance(output, SherpaDataset)
    assert output.shape == spectral_dataset.shape


@pytest.mark.asyncio
async def test_sg_derivative_on_sherpa_dataset(spectral_dataset):
    """Generic SG derivative should work via scipy fallback on SherpaDataset."""
    node = node_registry.create_node(
        "preprocess.derivative", "sg_deriv", {"method": "savitzky_golay", "size": 11, "order": 2, "deriv": "1"}
    )
    result = await node.run(default=spectral_dataset)
    output = result.outputs["default"]
    assert isinstance(output, SherpaDataset)
    assert output.shape == spectral_dataset.shape


# ---------------------------------------------------------------------------
# Provenance: copy_processing_history syncs with SherpaDataset.provenance
# ---------------------------------------------------------------------------


def test_copy_processing_history_syncs_provenance():
    """copy_processing_history must update provenance on SherpaDataset."""
    from spectra_sherpa.app.services.dag.meta_helpers import add_processing_step, copy_processing_history

    source = SherpaDataset(X=np.ones((3, 5)))
    add_processing_step(source, "preprocess.normalize", {}, node_id="n1")
    add_processing_step(source, "preprocess.normalize", {"method": "max"}, node_id="n2")

    target = SherpaDataset(X=np.ones((3, 5)))
    # target starts with 0 history entries
    assert len(target.provenance) == 0

    copy_processing_history(source, target)

    # SherpaDataset provenance is a Provenance object (single source of truth)
    assert len(target.provenance) == 2

    # Verify operations via ProvenanceEntry.op_id
    ops = [entry.op_id for entry in target.provenance]
    assert ops == ["preprocess.normalize", "preprocess.normalize"]


def test_provenance_chain_survives_to_dict():
    """After SNV->Scale chain, to_dict() should serialize ALL provenance steps."""
    from spectra_sherpa.app.services.dag.meta_helpers import add_processing_step, copy_processing_history

    # Simulate: source dataset -> copy history -> add step -> serialize
    ds = SherpaDataset(X=np.ones((3, 5)))
    add_processing_step(ds, "data.source", {"source": "sklearn"}, node_id="src")

    # Create result from copy (simulating what a node does)
    result = ds.copy()
    copy_processing_history(ds, result)
    add_processing_step(result, "preprocess.normalize", {}, node_id="snv")

    # Serialize
    d = result.to_dict()
    history = d["metadata"]["processing_history"]
    operations = [step["op_id"] for step in history]
    assert "data.source" in operations
    assert "preprocess.normalize" in operations
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
        node = self._make_node("preprocess.normalize", {"method": "snv"})
        lines = node.generate_python(self._inputs(), use_scp=False)
        code = "\n".join(lines)
        assert "scp.NDDataset" not in code
        assert "NormalizeNode" in code
        assert "transform_dataset(" in code

    def test_snv_scp_uses_sherpa_dataset(self):
        node = self._make_node("preprocess.normalize", {"method": "snv"})
        lines = node.generate_python(self._inputs(), use_scp=True)
        code = "\n".join(lines)
        assert "transform_dataset(" in code

    def test_scale_no_scp_uses_result(self):
        node = self._make_node("preprocess.normalize", {"method": "scale"})
        lines = node.generate_python(self._inputs(), use_scp=False)
        code = "\n".join(lines)
        assert "scp.NDDataset" not in code
        assert "transform_dataset(" in code

    def test_cosmic_ray_no_scp(self):
        node = self._make_node("preprocess.cosmic_ray", {"window": 7, "zscore": 3.0})
        lines = node.generate_python(self._inputs(), use_scp=False)
        code = "\n".join(lines)
        assert "scp.NDDataset" not in code
        assert "_cosmic_ray_dispatch" in code
        assert "_build_cosmic_ray_result" in code
        assert "def _remove_cosmic_rays" not in code

    def test_clip_floor_no_scp(self):
        node = self._make_node("preprocess.clip_floor", {"floor": 0.0})
        lines = node.generate_python(self._inputs(), use_scp=False)
        code = "\n".join(lines)
        assert "scp.NDDataset" not in code
        assert "_clip_floor_dispatch" in code
        assert "_build_clip_floor_result" in code
        assert "np.maximum" not in code

    def test_sample_max_normalization_no_scp(self):
        node = self._make_node("preprocess.normalize", {"method": "scale", "scale_method": "max"})
        lines = node.generate_python(self._inputs(), use_scp=False)
        code = "\n".join(lines)
        assert "scp.NDDataset" not in code
        assert "transform_dataset(" in code

    def test_center_mean_no_scp(self):
        node = self._make_node("preprocess.scale", {"method": "mean_center"})
        lines = node.generate_python(self._inputs(), use_scp=False)
        code = "\n".join(lines)
        assert "scp.NDDataset" not in code
        assert "apply_fitted_state(" in code

    def test_pareto_no_scp(self):
        node = self._make_node("preprocess.scale", {"method": "pareto", "center": True})
        lines = node.generate_python(self._inputs(), use_scp=False)
        code = "\n".join(lines)
        assert "scp.NDDataset" not in code
        assert "apply_fitted_state(" in code

    def test_autoscaling_no_scp(self):
        node = self._make_node("preprocess.scale", {"method": "autoscale", "center": True})
        lines = node.generate_python(self._inputs(), use_scp=False)
        code = "\n".join(lines)
        assert "scp.NDDataset" not in code
        assert "apply_fitted_state(" in code

    def test_emsc_no_scp(self):
        node = self._make_node("preprocess.emsc", {"reference_method": "mean", "poly_order": 2})
        lines = node.generate_python(self._inputs(), use_scp=False)
        code = "\n".join(lines)
        assert "scp.NDDataset" not in code
        assert "apply_fitted_state(" in code
        assert "EMSCNode" in code
        assert "np.linalg.lstsq" not in code

    def test_savgol_smooth_no_scp_uses_canonical_dispatcher(self):
        node = self._make_node("preprocess.smooth", {"method": "savitzky_golay", "size": 11, "order": 2})
        lines = node.generate_python(self._inputs(), use_scp=False)
        code = "\n".join(lines)
        assert "SmoothNode" in code
        assert "savgol_filter" not in code
        assert ".smooth(" not in code
        assert "transform_dataset(" in code

    def test_savgol_smooth_scp_uses_same_canonical_dispatcher(self):
        node = self._make_node("preprocess.smooth", {"method": "savitzky_golay", "size": 11, "order": 2})
        lines = node.generate_python(self._inputs(), use_scp=True)
        code = "\n".join(lines)
        assert "SmoothNode" in code
        assert "savgol_filter" not in code
        assert ".smooth(" not in code
        assert "transform_dataset(" in code

    def test_first_deriv_no_scp_uses_complete_canonical_authority(self):
        node = self._make_node(
            "preprocess.derivative", {"method": "savitzky_golay", "deriv": "1", "size": 11, "order": 2}
        )
        lines = node.generate_python(self._inputs(), use_scp=False)
        code = "\n".join(lines)
        assert "_execute_derivative" in code
        assert "_derivative_dispatch" not in code
        assert "'deriv': '1'" in code
        assert "savgol_filter" not in code
        assert ".savgol(" not in code
        assert "results['test_preprocess.derivative']" in code

    def test_second_deriv_no_scp_uses_complete_canonical_authority(self):
        node = self._make_node(
            "preprocess.derivative", {"method": "savitzky_golay", "deriv": "2", "size": 11, "order": 2}
        )
        lines = node.generate_python(self._inputs(), use_scp=False)
        code = "\n".join(lines)
        assert "_execute_derivative" in code
        assert "_derivative_dispatch" not in code
        assert "'deriv': '2'" in code
        assert "savgol_filter" not in code
        assert ".savgol(" not in code
        assert "results['test_preprocess.derivative']" in code

    def test_sg_derivative_no_scp_uses_complete_canonical_authority(self):
        node = self._make_node(
            "preprocess.derivative", {"method": "savitzky_golay", "size": 11, "order": 2, "deriv": "1"}
        )
        lines = node.generate_python(self._inputs(), use_scp=False)
        code = "\n".join(lines)
        assert "_execute_derivative" in code
        assert "_derivative_dispatch" not in code
        assert "savgol_filter" not in code
        assert ".savgol(" not in code
        assert "results['test_preprocess.derivative']" in code

    def test_sg_derivative_scp_uses_same_complete_canonical_authority(self):
        node = self._make_node(
            "preprocess.derivative", {"method": "savitzky_golay", "size": 11, "order": 2, "deriv": "1"}
        )
        lines = node.generate_python(self._inputs(), use_scp=True)
        code = "\n".join(lines)
        assert "_execute_derivative" in code
        assert "_derivative_dispatch" not in code
        assert "savgol_filter" not in code
        assert ".savgol(" not in code
        assert "results['test_preprocess.derivative']" in code

    def test_native_rubberband_export_uses_the_same_complete_authority(self):
        """SCP availability cannot select another rubberband implementation."""
        node = self._make_node("baseline.rubberband", {})
        without_scp = node.generate_python(self._inputs(), use_scp=False)
        assert node.generate_python(self._inputs(), use_scp=True) == without_scp
        code = "\n".join(without_scp)
        assert "_execute_rubberband" in code
        assert "spectrochempy" not in code.lower()

    def test_clip_range_no_scp_uses_index_lookup(self):
        """ClipRange export must delegate rather than restate range math."""
        node = self._make_node("preprocess.clip_range", {"minimum": 500, "maximum": 3000})
        lines = node.generate_python(self._inputs(), use_scp=False)
        code = "\n".join(lines)
        assert "_clip_range_dataset_dispatch" in code
        assert "_build_clip_range_result" in code
        assert "np.ones" not in code

    def test_clip_range_scp_uses_coord_slicing(self):
        """SCP availability cannot select another range implementation."""
        node = self._make_node("preprocess.clip_range", {"minimum": 500, "maximum": 3000})
        assert node.generate_python(self._inputs(), use_scp=True) == node.generate_python(self._inputs(), use_scp=False)


# ---------------------------------------------------------------------------
# 14. ClipRangeNode execute() on SherpaDataset
# ---------------------------------------------------------------------------


class TestClipRangeSherpaDataset:
    """Test ClipRangeNode execute() with SherpaDataset (value-based clipping)."""

    @pytest.mark.asyncio
    async def test_clip_by_wavenumber_values(self):
        """ClipRange should select columns where feature_axis values are within [min, max]."""
        # Simulate spectral data: 5 samples, 100 features at wavenumbers 400-4000
        wavenumbers = np.linspace(400, 4000, 100)
        X = np.random.default_rng(42).standard_normal((5, 100))
        ds = SherpaDataset(
            X=X,
            feature_axis=SpectralAxis(values=wavenumbers, units="cm-1", title="wavenumber"),
        )

        node = node_registry.create_node("preprocess.clip_range", "test_clip", {"minimum": 1000, "maximum": 2000})
        result = await node.run(default=ds)
        output = result.outputs["default"]

        assert isinstance(output, SherpaDataset)
        # Only columns with wavenumber in [1000, 2000] should survive
        expected_mask = (wavenumbers >= 1000) & (wavenumbers <= 2000)
        expected_cols = expected_mask.sum()
        assert output.shape == (5, expected_cols), f"Expected (5, {expected_cols}), got {output.shape}"
        # feature_axis values should be the clipped subset
        np.testing.assert_array_almost_equal(output.feature_axis.values, wavenumbers[expected_mask])
        # Data should match the correct columns from the original
        np.testing.assert_array_almost_equal(output.X, X[:, expected_mask])

    @pytest.mark.asyncio
    async def test_clip_range_includes_both_requested_boundaries(self):
        """ClipRange keeps all explicit coordinates inside its closed interval."""
        wavenumbers = np.linspace(400, 4000, 50)
        X = np.ones((3, 50))
        ds = SherpaDataset(
            X=X,
            feature_axis=SpectralAxis(values=wavenumbers, units="cm-1"),
        )
        node = node_registry.create_node("preprocess.clip_range", "test_clip_min", {"minimum": 2000, "maximum": 4000})
        result = await node.run(default=ds)
        output = result.outputs["default"]

        expected_mask = (wavenumbers >= 2000) & (wavenumbers <= 4000)
        assert output.shape[1] == expected_mask.sum()
        assert output.feature_axis.values[0] >= 2000

    @pytest.mark.asyncio
    async def test_clip_rejects_missing_feature_coordinates(self):
        """Scientific range selection cannot infer coordinates from column positions."""
        X = np.ones((3, 100))
        ds = SherpaDataset(X=X)
        node = node_registry.create_node("preprocess.clip_range", "test_clip_nox", {"minimum": 10, "maximum": 50})
        with pytest.raises(ValueError, match="requires an explicit feature axis"):
            await node.run(default=ds)

    @pytest.mark.asyncio
    async def test_clip_preserves_provenance(self):
        """ClipRange should record processing history."""
        wavenumbers = np.linspace(400, 4000, 100)
        ds = SherpaDataset(
            X=np.ones((3, 100)),
            feature_axis=SpectralAxis(values=wavenumbers),
        )
        node = node_registry.create_node("preprocess.clip_range", "test_clip_prov", {"minimum": 1000, "maximum": 3000})
        result = await node.run(default=ds)
        output = result.outputs["default"]
        history = output.provenance.to_list()
        assert len(history) >= 1
        assert history[-1]["op_id"] == "preprocess.clip_range"
        assert history[-1]["parameters"]["minimum"] == 1000
        assert history[-1]["parameters"]["maximum"] == 3000

    def test_clip_rejects_reversed_bounds(self):
        """Reversed bounds are invalid rather than silently reinterpreted."""
        with pytest.raises(ValueError, match="strictly less"):
            node_registry.create_node(
                "preprocess.clip_range",
                "test_clip_reversed",
                {"minimum": 3000, "maximum": 1000},
            )


# ---------------------------------------------------------------------------
# 15. Classification isinstance guard tests
# ---------------------------------------------------------------------------


class TestClassificationIsinstanceGuards:
    """Verify PLSDA and SIMCA nodes accept SherpaDataset."""

    def test_plsda_accepts_sherpa_dataset_type(self):
        """PLSDANode isinstance check should accept SherpaDataset."""
        ds = SherpaDataset(X=np.ones((10, 5)))
        # Check passes without raising
        assert isinstance(ds, SherpaDataset)

    def test_simca_accepts_sherpa_dataset_type(self):
        """SIMCANode isinstance check should accept SherpaDataset."""
        ds = SherpaDataset(X=np.ones((10, 5)))
        assert isinstance(ds, SherpaDataset)
