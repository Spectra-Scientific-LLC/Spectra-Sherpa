"""C2k canonical CARS scientific, execution, and export proofs."""

from __future__ import annotations

import numpy as np
import pytest

import spectra_sherpa.app.services.dag.nodes  # noqa: F401 - populate built-ins
from spectra_sherpa.app.lib.sherpa_dataset import SampleAxis, SherpaDataset, SpectralAxis, TargetContext
from spectra_sherpa.app.services.dag.node_base import node_registry
from spectra_sherpa.app.services.dag.nodes.selection import cars_node
from spectra_sherpa.app.services.dag.nodes.selection.cars_node import (
    CARSNode,
    _canonical_cars_parameters,
    _cars_dispatch,
)
from spectra_sherpa.execution_contract_vocabulary import (
    LifecycleKind,
    ManagedOptimizationEligibility,
    RuntimeFamily,
    WorkerCapability,
)
from tests.performance_contract import PerformanceCeiling


@pytest.fixture
def cars_data() -> tuple[SherpaDataset, np.ndarray]:
    rng = np.random.default_rng(731)
    matrix = rng.normal(size=(48, 24))
    target = 2.0 * matrix[:, 3] - 1.25 * matrix[:, 9] + 0.5 * matrix[:, 17]
    target += rng.normal(scale=0.05, size=matrix.shape[0])
    dataset = SherpaDataset(
        X=matrix,
        feature_axis=SpectralAxis(values=np.linspace(900.0, 2100.0, matrix.shape[1]), units="cm-1"),
        sample_axis=SampleAxis(labels=[f"sample-{index}" for index in range(matrix.shape[0])]),
        target=target,
    )
    return dataset, target


def test_cars_has_one_complete_local_fitted_transform_contract() -> None:
    metadata = node_registry.get_metadata("selection.cars")
    contract = metadata.resolved_execution_contract()

    assert contract is not None
    assert contract.payload["contract_version"] == "4.0"
    assert contract.payload["operation_id"] == "selection.cars"
    assert contract.payload["runtime_family"] == RuntimeFamily.SHERPA_NATIVE.value
    assert contract.payload["lifecycle_kind"] == LifecycleKind.FITTED_TRANSFORM.value
    assert contract.payload["implementation_id"] == "spectrasherpa.selection.cars"
    assert contract.payload["managed_optimization_eligibility"] == (ManagedOptimizationEligibility.LOCAL.value,)
    assert contract.payload["required_worker_capabilities"] == (WorkerCapability.READ_DATASET.value,)
    assert contract.payload["deterministic"] is False
    assert contract.payload["seed_parameter"] == "random_seed"
    assert contract.payload["target_access"] == "fit_only"
    assert contract.payload["implementation_version"] == "1.1.0"
    assert contract.payload["fitted_state_serializer"] == "spectrasherpa.selection.cars.state/3"


def test_cars_admission_materializes_one_closed_parameter_shape() -> None:
    node = node_registry.create_node("selection.cars", "cars", {"max_components": 3})
    author_defaults = node_registry.create_node("selection.cars", "cars-default", {})

    assert node.parameters == {
        "n_iterations": 50,
        "max_components": 3,
        "cv_folds": 5,
        "calibration_fraction": 0.9,
        "random_seed": 42,
        "component_selection": "one_standard_deviation",
        "cv_order": "sorted_target",
    }
    assert author_defaults.parameters["max_components"] == 2
    assert author_defaults.parameters["calibration_fraction"] == 0.9


@pytest.mark.parametrize(
    "parameters",
    [
        {"n_iterations": 9},
        {"n_iterations": 10.0},
        {"max_components": True},
        {"cv_folds": 21},
        {"calibration_fraction": 0.49},
        {"calibration_fraction": np.nan},
        {"random_seed": -1},
        {"component_selection": "smallest_rmsecv"},
        {"cv_order": "shuffle"},
        {"n_components": 3},
        {"seed": 42},
    ],
)
def test_cars_rejects_unbounded_coerced_and_alias_parameters(parameters: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        _canonical_cars_parameters(parameters)


def test_cars_uses_monte_carlo_calibration_subsets(monkeypatch: pytest.MonkeyPatch) -> None:
    original = cars_node.pls_core.fit_simpls_exact
    fitted_row_counts: list[int] = []

    def recording_fit(X: np.ndarray, y: np.ndarray, **kwargs: object):
        fitted_row_counts.append(len(X))
        return original(X, y, **kwargs)

    monkeypatch.setattr(cars_node.pls_core, "fit_simpls_exact", recording_fit)
    rng = np.random.default_rng(42)
    matrix = rng.normal(size=(30, 12))
    target = matrix[:, 2] - matrix[:, 7]

    _cars_dispatch(
        matrix,
        target,
        n_iterations=10,
        max_components=2,
        cv_folds=3,
        calibration_fraction=0.6,
        random_seed=42,
    )

    assert fitted_row_counts[0] == 18
    assert fitted_row_counts[0] < len(matrix)


def test_cars_seed_reproduces_mask_scores_and_rmsecv() -> None:
    rng = np.random.default_rng(91)
    matrix = rng.normal(size=(36, 18))
    target = matrix[:, 4] + 0.25 * matrix[:, 12]
    parameters = {
        "n_iterations": 15,
        "max_components": 2,
        "cv_folds": 3,
        "calibration_fraction": 0.75,
        "random_seed": 619,
    }

    first_outputs, first_diagnostics = _cars_dispatch(matrix, target, **parameters)
    second_outputs, second_diagnostics = _cars_dispatch(matrix, target, **parameters)

    np.testing.assert_array_equal(first_outputs["mask"], second_outputs["mask"])
    np.testing.assert_array_equal(first_outputs["scores"], second_outputs["scores"])
    assert first_diagnostics["rmsecv_trace"] == second_diagnostics["rmsecv_trace"]


@pytest.mark.asyncio
async def test_cars_live_and_exported_execution_share_one_typed_operation(cars_data) -> None:
    dataset, target = cars_data
    original_axis = np.asarray(dataset.feature_axis.values).copy()
    original_mask = np.asarray(dataset.feature_axis.include_mask).copy()
    node = CARSNode(
        "cars",
        {
            "n_iterations": 12,
            "max_components": 2,
            "cv_folds": 3,
            "calibration_fraction": 0.75,
            "random_seed": 113,
        },
    )

    live = await node.execute(X=dataset, y=target)
    namespace = {"dataset": dataset, "target": target, "results": {}}
    exec("\n".join(node.generate_python({"X": "dataset", "y": "target"}, indent="")), namespace)
    exported = namespace["results"]["cars"]

    np.testing.assert_array_equal(exported["mask"], live.outputs["mask"])
    np.testing.assert_array_equal(exported["scores"], live.outputs["scores"])
    np.testing.assert_array_equal(exported["X_selected"].X, live.outputs["X_selected"].X)
    np.testing.assert_array_equal(dataset.feature_axis.values, original_axis)
    np.testing.assert_array_equal(dataset.feature_axis.include_mask, original_mask)
    assert live.diagnostics["selection_scope"] == "full_calibration_fit_not_performance_evidence"


def test_cars_rejects_multiple_targets_and_unsupported_component_count() -> None:
    matrix = np.arange(60, dtype=np.float64).reshape(10, 6)
    with pytest.raises(ValueError, match="exactly one quantitative target"):
        cars_node._cars_inputs(matrix, np.ones((10, 2)))
    with pytest.raises(ValueError, match="initial Monte Carlo PLS support"):
        _cars_dispatch(matrix, np.arange(10.0), max_components=7)


def test_cars_rejects_constant_categorical_and_discretely_unsupported_targets() -> None:
    matrix = np.arange(60, dtype=np.float64).reshape(10, 6)
    with pytest.raises(ValueError, match="non-zero variation"):
        cars_node._cars_inputs(matrix, np.ones(10))

    categorical = SherpaDataset(
        X=matrix,
        target=np.arange(10.0),
        target_context=TargetContext(target_type="categorical", target_name="class"),
    )
    with pytest.raises(ValueError, match="requires continuous targets"):
        cars_node._cars_inputs(categorical, None)

    with pytest.raises(ValueError, match="initial Monte Carlo PLS support"):
        _cars_dispatch(
            matrix,
            np.arange(10.0),
            n_iterations=10,
            max_components=8,
            cv_folds=2,
            calibration_fraction=0.5,
            random_seed=42,
        )


def test_cars_fit_state_is_closed_axis_bound_and_applies_without_target(
    cars_data: tuple[SherpaDataset, np.ndarray], monkeypatch: pytest.MonkeyPatch
) -> None:
    dataset, target = cars_data
    labeled_axis = dataset.feature_axis
    labeled_axis.labels = [f"band-{index}" for index in range(dataset.n_features)]
    dataset.feature_axis = labeled_axis
    original_values = np.array(dataset.feature_axis.values, copy=True)
    original_labels = list(dataset.feature_axis.labels)
    node = CARSNode(
        "cars",
        {
            "n_iterations": 10,
            "max_components": 2,
            "cv_folds": 3,
            "calibration_fraction": 0.75,
            "random_seed": 113,
        },
    )
    state = node.fit_fitted_state(dataset, target)
    assert state["serializer"] == "spectrasherpa.selection.cars.state/3"
    assert state["max_components"] == 2
    assert state["cv_folds"] == 3
    assert state["n_iterations"] == 10
    assert state["reference_samples"] == 48
    assert state["calibration_size"] == 36

    monkeypatch.setattr(cars_node, "bind_y", lambda *_args, **_kwargs: pytest.fail("apply read a target"))
    application = SherpaDataset(
        X=np.array(dataset.X, copy=True),
        feature_axis=dataset.feature_axis.model_copy(deep=True),
    )
    selected = node.apply_fitted_state(application, state)
    mask = np.asarray(state["feature_mask"], dtype=bool)
    np.testing.assert_array_equal(selected.X, dataset.X[:, mask])
    assert selected.feature_axis.labels == [label for label, keep in zip(original_labels, mask, strict=True) if keep]
    assert selected.feature_axis.quantity == dataset.feature_axis.quantity
    assert selected.feature_axis.display_units == dataset.feature_axis.display_units
    np.testing.assert_array_equal(dataset.feature_axis.values, original_values)
    assert dataset.feature_axis.labels == original_labels

    drifted_axis = application.feature_axis
    drifted_axis.values = np.asarray(drifted_axis.values) + 0.5
    drifted = SherpaDataset(X=np.array(application.X, copy=True), feature_axis=drifted_axis)
    with pytest.raises(ValueError, match="fitted feature axis"):
        node.apply_fitted_state(drifted, state)
    with pytest.raises(ValueError, match="closed serializer schema"):
        node.apply_fitted_state(application, {**state, "unexpected": True})


def test_cars_rmsecv_pools_held_out_residuals_by_sample(monkeypatch: pytest.MonkeyPatch) -> None:
    class ZeroPredictingPLS:
        def predict(self, X: np.ndarray) -> np.ndarray:
            return np.zeros((len(X), 1), dtype=float)

    monkeypatch.setattr(cars_node.pls_core, "fit_simpls_exact", lambda *_args, **_kwargs: ZeroPredictingPLS())
    matrix = np.arange(20, dtype=float).reshape(5, 4)
    target = np.arange(1.0, 6.0)
    rmsecv, components = cars_node._score_cars_subset(
        matrix,
        target,
        np.ones(4, dtype=bool),
        max_components=1,
        cv_folds=2,
        component_selection="minimum_rmsecv",
        cv_order="input_order",
        seed=7,
    )
    assert rmsecv == pytest.approx(float(np.sqrt(np.mean(target**2))))
    assert components == 1


def test_cars_reproduces_the_author_record_then_edf_then_ars_sequence(monkeypatch: pytest.MonkeyPatch) -> None:
    class PositiveCoefficientPLS:
        def __init__(self, features: int) -> None:
            self.coefficients = np.arange(features, 0, -1, dtype=float).reshape(-1, 1)

    scored_masks: list[np.ndarray] = []

    def record_score(_X, _y, mask, **_kwargs):
        scored_masks.append(np.array(mask, copy=True))
        return float(10 - len(scored_masks)), 1

    monkeypatch.setattr(
        cars_node.pls_core,
        "fit_simpls_exact",
        lambda X, *_args, **_kwargs: PositiveCoefficientPLS(X.shape[1]),
    )
    monkeypatch.setattr(cars_node, "_score_cars_subset", record_score)
    matrix = np.arange(144, dtype=float).reshape(12, 12)
    target = np.linspace(0.0, 1.0, 12)

    result = cars_node._cars_algorithm(matrix, target, 2, 3, 10, seed=42)

    recorded = [np.asarray(mask, dtype=bool) for mask in result["subset_masks"]]
    assert len(recorded) == 10
    assert recorded[0].all()  # W(:, 1) is recorded before the first EDF/ARS reduction.
    assert all(np.array_equal(scored, expected) for scored, expected in zip(scored_masks, recorded, strict=True))
    assert result["best_iteration"] == 9
    np.testing.assert_array_equal(result["best_mask"], recorded[9])
    b = np.log(matrix.shape[1] / 2.0) / 9
    a = np.exp(b)
    expected_ratios = [a * np.exp(-b * (iteration + 2)) for iteration in range(10)]
    np.testing.assert_allclose(result["retention_ratios"], expected_ratios, rtol=0.0, atol=1e-15)


def test_cars_fails_closed_when_pls_provides_no_adaptive_weight(monkeypatch: pytest.MonkeyPatch) -> None:
    class ZeroCoefficientPLS:
        def __init__(self, features: int) -> None:
            self.coefficients = np.zeros((features, 1), dtype=float)

    monkeypatch.setattr(
        cars_node.pls_core,
        "fit_simpls_exact",
        lambda X, *_args, **_kwargs: ZeroCoefficientPLS(X.shape[1]),
    )
    with pytest.raises(ValueError, match="no finite weighted variables"):
        cars_node._cars_algorithm(
            np.arange(72, dtype=float).reshape(12, 6),
            np.linspace(0.0, 1.0, 12),
            2,
            3,
            10,
            seed=42,
        )


def test_cars_seeded_random_cv_reuses_one_partition_for_every_recorded_subset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class PositiveCoefficientPLS:
        def __init__(self, features: int) -> None:
            self.coefficients = np.arange(features, 0, -1, dtype=float).reshape(-1, 1)

        def predict(self, X: np.ndarray) -> np.ndarray:
            return np.zeros((len(X), 1), dtype=float)

    original_splits = cars_node._cars_cv_splits
    observed: list[tuple[tuple[tuple[int, ...], tuple[int, ...]], ...]] = []

    def record_splits(*args, **kwargs):
        splits = original_splits(*args, **kwargs)
        observed.append(tuple((tuple(train), tuple(test)) for train, test in splits))
        return splits

    monkeypatch.setattr(
        cars_node.pls_core,
        "fit_simpls_exact",
        lambda X, *_args, **_kwargs: PositiveCoefficientPLS(X.shape[1]),
    )
    monkeypatch.setattr(cars_node, "_cars_cv_splits", record_splits)
    matrix = np.arange(144, dtype=float).reshape(12, 12)
    target = np.linspace(0.0, 1.0, 12)

    cars_node._cars_algorithm(
        matrix,
        target,
        1,
        3,
        10,
        seed=819,
        component_selection="minimum_rmsecv",
        cv_order="seeded_random",
    )

    assert len(observed) == 10
    assert all(partition == observed[0] for partition in observed[1:])


def test_cars_one_standard_deviation_rule_selects_the_simpler_supported_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class ControlledPredictionPLS:
        def __init__(self, n_components: int) -> None:
            self.n_components = n_components

        def predict(self, X: np.ndarray) -> np.ndarray:
            target = X[:, 0]
            if self.n_components == 1:
                return (target + np.sqrt(10.0)).reshape(-1, 1)
            errors = np.where(target == 5.0, np.sqrt(24.0), 0.0)
            return (target + errors).reshape(-1, 1)

    monkeypatch.setattr(
        cars_node.pls_core,
        "fit_simpls_exact",
        lambda *_args, n_components, **_kwargs: ControlledPredictionPLS(n_components),
    )
    matrix = np.column_stack([np.arange(6.0), np.arange(6.0) + 10.0])
    target = np.arange(6.0)
    mask = np.ones(2, dtype=bool)

    minimum = cars_node._score_cars_subset(
        matrix,
        target,
        mask,
        max_components=2,
        cv_folds=2,
        component_selection="minimum_rmsecv",
        cv_order="input_order",
        seed=42,
    )
    one_sd = cars_node._score_cars_subset(
        matrix,
        target,
        mask,
        max_components=2,
        cv_folds=2,
        component_selection="one_standard_deviation",
        cv_order="input_order",
        seed=42,
    )

    assert minimum == (pytest.approx(2.0), 2)
    assert one_sd == (pytest.approx(np.sqrt(10.0)), 1)


@pytest.mark.parametrize(
    "mutation",
    [
        lambda state: state.update(n_iterations_run=state["n_iterations"] - 1),
        lambda state: state["importance_scores"].__setitem__(0, -1.0),
        lambda state: state["rmsecv_trace"].__setitem__(0, -1.0),
        lambda state: state.update(best_iteration=(state["best_iteration"] + 1) % state["n_iterations"]),
        lambda state: state["feature_mask"].__setitem__(0, not state["feature_mask"][0]),
    ],
)
def test_cars_closed_state_rejects_incomplete_or_unbound_scientific_records(cars_data, mutation) -> None:
    dataset, target = cars_data
    state = CARSNode("cars", {"n_iterations": 10, "max_components": 2, "cv_folds": 3}).fit_fitted_state(dataset, target)
    mutation(state)
    with pytest.raises(ValueError):
        cars_node._validate_cars_state(state)


def test_cars_fixed_local_workload_stays_inside_reviewed_ceiling() -> None:
    rng = np.random.default_rng(17)
    matrix = rng.normal(size=(60, 40))
    target = matrix[:, :4].sum(axis=1) + rng.normal(scale=0.05, size=60)
    with PerformanceCeiling("selection.cars", "60x40-20-iterations", 5.0).measure():
        outputs, diagnostics = _cars_dispatch(
            matrix,
            target,
            n_iterations=20,
            max_components=3,
            cv_folds=4,
            calibration_fraction=0.8,
            random_seed=42,
        )

    assert outputs["mask"].any()
    assert np.isfinite(diagnostics["best_rmsecv"])
