"""C2i canonical KNN scientific, fitted-state, and contract proofs."""

from __future__ import annotations

import copy

import numpy as np
import pytest
from sklearn.metrics import confusion_matrix
from sklearn.neighbors import KNeighborsClassifier
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

import spectra_sherpa.app.services.dag.nodes  # noqa: F401 - populate built-ins
from spectra_sherpa.app.lib.fitted_state import KNNExtract
from spectra_sherpa.app.lib.sherpa_dataset import SampleAxis, SherpaDataset, SpectralAxis, TargetContext
from spectra_sherpa.app.services.dag.node_base import node_registry
from spectra_sherpa.app.services.dag.nodes.classification.application_nodes import ApplyKNNNode
from spectra_sherpa.app.services.dag.nodes.classification.knn_nodes import (
    KNNNode,
    _canonical_knn_parameters,
    _knn_display_projection,
    _knn_scientific_core,
    apply_knn_fitted_state,
)
from spectra_sherpa.execution_contract_vocabulary import LifecycleKind, ManagedOptimizationEligibility, RuntimeFamily
from tests.performance_contract import PerformanceCeiling


def _dataset() -> tuple[SherpaDataset, np.ndarray]:
    rng = np.random.default_rng(1967)
    rows_per_class = 18
    labels = np.repeat(np.array(["matrix-a", "matrix-b", "matrix-c"], dtype=object), rows_per_class)
    centers = np.array([[-1.4, 0.2, 0.8], [0.3, 1.5, -0.5], [1.6, -0.9, 0.1]])
    matrix = np.vstack(
        [
            np.column_stack(
                [
                    rng.normal(center[0], 0.35, rows_per_class),
                    rng.normal(center[1], 0.30, rows_per_class),
                    rng.normal(center[2], 0.25, rows_per_class),
                    rng.normal(0.0, 0.5, rows_per_class),
                    rng.normal(0.0, 0.8, rows_per_class),
                    rng.normal(0.0, 0.2, rows_per_class),
                ]
            )
            for center in centers
        ]
    )
    return (
        SherpaDataset(
            X=matrix,
            feature_axis=SpectralAxis(values=np.linspace(900.0, 1800.0, matrix.shape[1]), units="cm-1"),
            sample_axis=SampleAxis(labels=[f"sample-{index}" for index in range(matrix.shape[0])]),
            target=labels,
            target_context=TargetContext(target_type="categorical", target_names=["material class"]),
        ),
        labels,
    )


def _parameters(**overrides: object) -> dict[str, object]:
    values: dict[str, object] = {
        "n_neighbors": 5,
        "weights": "uniform",
        "metric": "euclidean",
        "scale": True,
    }
    values.update(overrides)
    return values


def test_knn_has_one_exact_local_fitted_model_contract() -> None:
    contract = node_registry.get_metadata("classification.knn").resolved_execution_contract()
    assert contract is not None
    assert contract.payload["operation_id"] == "classification.knn"
    assert contract.payload["runtime_family"] == RuntimeFamily.SHERPA_NATIVE.value
    assert contract.payload["lifecycle_kind"] == LifecycleKind.FITTED_MODEL.value
    assert contract.payload["managed_optimization_eligibility"] == (
        ManagedOptimizationEligibility.LOCAL.value,
        ManagedOptimizationEligibility.DEVELOPMENT.value,
        ManagedOptimizationEligibility.FULL_REFIT.value,
    )
    assert contract.payload["managed_optimization_profiles"] == ("first_party_pls",)
    assert contract.payload["target_access"] == "fit_only"
    assert contract.payload["fitted_state_serializer"] == "spectrasherpa.model-artifact.knn/1"
    assert contract.payload["runtime_requirements"] == (
        {"distribution": "numpy", "version": "1.26.4"},
        {"distribution": "scikit-learn", "version": "1.9.0"},
        {"distribution": "scipy", "version": "1.17.1"},
    )
    assert any("10.1109/TIT.1967.1053964" in item for item in contract.payload["citations"])


def test_knn_application_has_one_matching_serializer_and_retires_generic_prediction() -> None:
    contract = node_registry.get_metadata("classification.apply_knn").resolved_execution_contract()
    assert contract is not None
    assert contract.payload["lifecycle_kind"] == LifecycleKind.ARTIFACT_APPLICATION.value
    assert contract.payload["fitted_state_serializer"] == "spectrasherpa.model-artifact.knn/1"
    assert "classification.predict" not in node_registry


def test_knn_parameter_contract_is_closed() -> None:
    assert _canonical_knn_parameters(_parameters()) == _parameters()
    for invalid in (
        {},
        _parameters(n_neighbors=True),
        _parameters(n_neighbors=0),
        _parameters(n_neighbors=51),
        _parameters(weights="rank"),
        _parameters(metric="cosine"),
        _parameters(scale=1),
        {**_parameters(), "cv_folds": 3},
        {**_parameters(), "p": 3},
    ):
        with pytest.raises(ValueError):
            _canonical_knn_parameters(invalid)


@pytest.mark.parametrize("weights", ["uniform", "distance"])
@pytest.mark.parametrize("metric", ["euclidean", "manhattan", "chebyshev", "minkowski"])
@pytest.mark.parametrize("scale", [False, True])
def test_knn_matches_direct_sklearn_oracle(weights: str, metric: str, scale: bool) -> None:
    dataset, labels = _dataset()
    parameters = _parameters(weights=weights, metric=metric, scale=scale)
    actual = _knn_scientific_core(dataset, labels, parameters=parameters)
    estimator = KNeighborsClassifier(
        n_neighbors=5,
        weights=weights,
        metric=metric,
        algorithm="brute",
        n_jobs=1,
    )
    oracle = Pipeline([("scale", StandardScaler()), ("knn", estimator)]) if scale else estimator
    oracle.fit(dataset.X, labels)
    expected_train = oracle.predict(dataset.X)
    expected_probabilities = oracle.predict_proba(dataset.X)

    np.testing.assert_array_equal(actual["train_predictions"], expected_train)
    np.testing.assert_allclose(actual["train_probabilities"], expected_probabilities, rtol=0.0, atol=0.0)
    np.testing.assert_array_equal(
        actual["train_confusion"], confusion_matrix(labels, expected_train, labels=actual["classes"])
    )
    assert actual["train_metrics"]["train_accuracy"] == float(np.mean(expected_train == labels))
    assert actual["metrics"]["evidence_scope"] == "calibration_fit_diagnostics_not_validation_evidence"
    assert "cv" not in actual["metrics"]["splits"]


@pytest.mark.asyncio
async def test_knn_live_and_generated_python_share_one_scientific_operation() -> None:
    dataset, labels = _dataset()
    node = KNNNode("knn", _parameters(weights="distance", metric="manhattan"))
    live = await node.execute(X=dataset, y=labels)
    namespace = {"dataset": dataset, "labels": labels, "results": {}}
    exec("\n".join(node.generate_python({"X": "dataset", "y": "labels"}, indent="")), namespace)  # noqa: S102
    generated = namespace["results"]["knn"]

    np.testing.assert_array_equal(generated["predictions"], live.outputs["predictions"])
    np.testing.assert_allclose(generated["probabilities"], live.outputs["probabilities"], rtol=0.0, atol=0.0)
    np.testing.assert_allclose(generated["distances"], live.outputs["distances"], rtol=0.0, atol=0.0)
    np.testing.assert_array_equal(generated["neighbor_indices"], live.outputs["neighbor_indices"])
    assert generated["metrics"] == live.outputs["metrics"]
    assert generated["visualization"] == live.outputs["visualization"]
    assert generated["confusion_visualization"] == live.outputs["confusion_visualization"]
    presentation = node.metadata.resolved_presentation_contract()
    assert presentation.default_presentation == "calibration_map"
    assert [item.presentation_id for item in presentation.presentations] == [
        "calibration_map",
        "coordinates",
        "metrics",
        "calibration_confusion",
    ]
    calibration_map = live.outputs["visualization"]
    assert len(calibration_map["data"]) == 3
    assert sum(len(trace["x"]) for trace in calibration_map["data"]) == dataset.shape[0]
    assert "neighbor search used all model-space variables" in calibration_map["layout"]["title"]["text"]
    assert "decision_boundary" not in live.outputs["plots"]


@pytest.mark.asyncio
async def test_knn_high_dimensional_display_projection_is_shared_with_export() -> None:
    dataset, labels = _dataset()
    matrix = np.column_stack([dataset.X, dataset.X, dataset.X])
    high_dimensional = SherpaDataset(
        X=matrix,
        feature_axis=SpectralAxis(values=np.linspace(900.0, 1800.0, matrix.shape[1]), units="cm-1"),
        sample_axis=dataset.sample_axis,
        target=labels,
        target_context=dataset.target_context,
    )
    node = KNNNode("knn", _parameters())

    live = await node.execute(X=high_dimensional, y=labels)
    namespace = {"dataset": high_dimensional, "labels": labels, "results": {}}
    exec("\n".join(node.generate_python({"X": "dataset", "y": "labels"}, indent="")), namespace)  # noqa: S102
    generated = namespace["results"]["knn"]

    assert live.outputs["default"].shape == (dataset.shape[0], 5)
    np.testing.assert_allclose(generated["default"], live.outputs["default"].X, rtol=0.0, atol=0.0)


def test_knn_large_randomized_display_projection_is_seeded_and_repeatable() -> None:
    rng = np.random.default_rng(42)
    matrix = rng.normal(size=(501, 511))

    first, first_labels = _knn_display_projection(matrix)
    second, second_labels = _knn_display_projection(matrix)

    np.testing.assert_array_equal(first, second)
    assert first_labels == second_labels


def test_knn_fitted_state_and_artifact_replay_exact_sklearn_voting() -> None:
    dataset, labels = _dataset()
    node = KNNNode("knn", _parameters(weights="distance", metric="chebyshev"))
    state = node.fit_fitted_state(dataset, labels)
    replayed = node.apply_fitted_state(dataset, state)
    core = _knn_scientific_core(dataset, labels, parameters=_parameters(weights="distance", metric="chebyshev"))
    np.testing.assert_allclose(replayed, core["train_probabilities"], rtol=0.0, atol=0.0)

    extract = KNNExtract(
        X_train=np.asarray(state["X_train"]),
        y_train_encoded=np.asarray(state["y_train_encoded"], dtype=np.int64),
        classes=state["classes"],
        k=state["n_neighbors"],
        metric=state["metric"],
        weights=state["weights"],
        scale=state["scale"],
        x_mean=np.asarray(state["x_mean"]),
        x_scale=np.asarray(state["x_scale"]),
    )
    metadata, arrays = extract.to_artifact()
    restored = KNNExtract.from_artifact(metadata, arrays)
    labels_replayed, probabilities = restored.predict(dataset.X)
    np.testing.assert_array_equal(labels_replayed, core["train_predictions"])
    np.testing.assert_allclose(probabilities, core["train_probabilities"], rtol=0.0, atol=0.0)


@pytest.mark.asyncio
async def test_knn_application_live_and_generated_paths_share_the_artifact_core() -> None:
    dataset, labels = _dataset()
    producer = KNNNode("fit", _parameters(weights="distance", metric="manhattan"))
    fitted_state = producer.fit_fitted_state(dataset, labels)
    node = ApplyKNNNode("apply", {})

    live = await node.execute(X_new=dataset, fitted_state=fitted_state)
    namespace = {"dataset": dataset, "fitted_state": fitted_state, "results": {}}
    exec(  # noqa: S102
        "\n".join(node.generate_python({"X_new": "dataset", "fitted_state": "fitted_state"}, indent="")),
        namespace,
    )
    generated = namespace["results"]["apply"]
    default_namespace = {"dataset": dataset, "fitted_state": fitted_state, "results": {}}
    exec(  # noqa: S102
        "\n".join(node.generate_python({"default": "dataset", "fitted_state": "fitted_state"}, indent="")),
        default_namespace,
    )
    generated_default = default_namespace["results"]["apply"]
    expected_labels, expected_probabilities = apply_knn_fitted_state(dataset, fitted_state)

    np.testing.assert_array_equal(live.outputs["y_pred"], expected_labels)
    np.testing.assert_array_equal(generated["y_pred"], expected_labels)
    np.testing.assert_array_equal(generated_default["y_pred"], expected_labels)
    np.testing.assert_allclose(live.outputs["y_prob"], expected_probabilities, rtol=0.0, atol=0.0)
    np.testing.assert_allclose(generated["y_prob"], expected_probabilities, rtol=0.0, atol=0.0)
    np.testing.assert_allclose(generated_default["y_prob"], expected_probabilities, rtol=0.0, atol=0.0)


def test_knn_zero_distance_and_tie_semantics_are_not_reimplemented() -> None:
    training = np.array([[0.0], [0.0], [1.0], [2.0]], dtype=np.float64)
    encoded = np.array([0, 1, 1, 0], dtype=np.int64)
    extract = KNNExtract(
        X_train=training,
        y_train_encoded=encoded,
        classes=["A", "B"],
        k=3,
        weights="distance",
        scale=False,
    )
    expected = KNeighborsClassifier(
        n_neighbors=3,
        weights="distance",
        metric="euclidean",
        algorithm="brute",
        n_jobs=1,
    ).fit(training, encoded)
    labels, probabilities = extract.predict(np.array([[0.0], [1.5]]))
    np.testing.assert_array_equal(labels, np.array([["A", "B"][value] for value in expected.predict([[0.0], [1.5]])]))
    np.testing.assert_allclose(probabilities, expected.predict_proba([[0.0], [1.5]]), rtol=0.0, atol=0.0)


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"X_train": [[0.0], [np.nan]]}, "training matrix"),
        ({"y_train_encoded": [0, 2]}, "class identity"),
        ({"classes": ["A", "A"]}, "class identity"),
        ({"k": True}, "neighbor count"),
        ({"weights": "rank"}, "weight rule"),
        ({"metric": "cosine"}, "distance metric"),
        ({"scale": True, "x_mean": None, "x_scale": None}, "scaling vectors"),
        ({"x_scale": [0.0]}, "scaling state"),
    ],
)
def test_knn_refuses_to_serialize_invalid_scientific_state(change: dict[str, object], message: str) -> None:
    values: dict[str, object] = {
        "X_train": np.array([[0.0], [1.0]], dtype=np.float64),
        "y_train_encoded": np.array([0, 1], dtype=np.int64),
        "classes": ["A", "B"],
        "k": 1,
        "weights": "uniform",
        "metric": "euclidean",
        "scale": False,
        "x_mean": np.zeros(1, dtype=np.float64),
        "x_scale": np.ones(1, dtype=np.float64),
    }
    values.update(change)

    with pytest.raises(ValueError, match=message):
        KNNExtract(**values).to_artifact()  # type: ignore[arg-type]


def test_knn_rejects_invalid_data_training_bounds_and_fitted_state() -> None:
    dataset, labels = _dataset()
    matrix_before = np.array(dataset.X, copy=True)
    labels_before = copy.deepcopy(labels)
    _knn_scientific_core(dataset, labels, parameters=_parameters())
    np.testing.assert_array_equal(dataset.X, matrix_before)
    np.testing.assert_array_equal(labels, labels_before)

    with pytest.raises(ValueError, match="training rows"):
        _knn_scientific_core(dataset.X[:4], np.asarray(["a", "a", "b", "b"]), parameters=_parameters(n_neighbors=5))
    invalid = dataset.copy()
    invalid.X[0, 0] = np.nan
    with pytest.raises(ValueError, match="finite"):
        _knn_scientific_core(invalid, labels, parameters=_parameters())

    node = KNNNode("knn", _parameters())
    state = node.fit_fitted_state(dataset, labels)
    for patch, message in (
        ({"serializer": "spectrasherpa.model-artifact.knn/2"}, "serializer"),
        ({"feature_count": 99}, "training matrix"),
        ({"classes": ["only"]}, "class labels"),
        ({"x_scale": [0.0] * dataset.shape[1]}, "scaling vectors"),
        ({"extra": True}, "closed serializer"),
    ):
        forged = dict(state)
        forged.update(patch)
        with pytest.raises(ValueError, match=message):
            node.apply_fitted_state(dataset, forged)


def test_knn_fixed_local_workload_stays_inside_reviewed_ceiling() -> None:
    rng = np.random.default_rng(2718)
    matrix = rng.normal(size=(180, 120))
    labels = np.repeat(np.array(["a", "b", "c"]), 60)
    with PerformanceCeiling("classification.knn", "180x120-three-class-fit-only", 5.0).measure():
        _knn_scientific_core(matrix, labels, parameters=_parameters())
