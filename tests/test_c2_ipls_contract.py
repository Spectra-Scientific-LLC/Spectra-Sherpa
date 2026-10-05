"""C2k canonical iPLS scientific, execution, and export proofs."""

from __future__ import annotations

import copy

import numpy as np
import pytest
from sklearn.cross_decomposition import PLSRegression
from sklearn.model_selection import KFold

import spectra_sherpa.app.services.dag.nodes  # noqa: F401 - populate built-ins
from spectra_sherpa.app.lib.sherpa_dataset import SampleAxis, SherpaDataset, SpectralAxis, TargetContext
from spectra_sherpa.app.services.dag.node_base import node_registry
from spectra_sherpa.app.services.dag.nodes.selection import ipls_node
from spectra_sherpa.app.services.dag.nodes.selection.ipls_node import (
    IPLSNode,
    _canonical_ipls_parameters,
    _component_rmsecv,
    _interval_bounds,
    _ipls_dispatch,
    _ipls_fold_assignments,
    _validate_ipls_state,
)
from spectra_sherpa.execution_contract_vocabulary import (
    LifecycleKind,
    ManagedOptimizationEligibility,
    RuntimeFamily,
    WorkerCapability,
)
from tests.performance_contract import PerformanceCeiling


@pytest.fixture
def ipls_data() -> tuple[SherpaDataset, np.ndarray]:
    rng = np.random.default_rng(4021)
    matrix = rng.normal(size=(48, 24))
    # Signal confined to a contiguous block so a known interval should win.
    target = 2.0 * matrix[:, 10] - 1.5 * matrix[:, 11] + 0.75 * matrix[:, 12]
    target += rng.normal(scale=0.05, size=matrix.shape[0])
    dataset = SherpaDataset(
        X=matrix,
        feature_axis=SpectralAxis(values=np.linspace(900.0, 2100.0, matrix.shape[1]), units="cm-1"),
        sample_axis=SampleAxis(labels=[f"sample-{index}" for index in range(matrix.shape[0])]),
        target=target,
    )
    return dataset, target


# ── 1. Closed contract shape ────────────────────────────────────────────


def test_ipls_has_one_complete_local_fitted_transform_contract() -> None:
    metadata = node_registry.get_metadata("selection.ipls")
    contract = metadata.resolved_execution_contract()

    assert contract is not None
    assert contract.payload["contract_version"] == "4.0"
    assert contract.payload["operation_id"] == "selection.ipls"
    assert contract.payload["runtime_family"] == RuntimeFamily.SHERPA_NATIVE.value
    assert contract.payload["lifecycle_kind"] == LifecycleKind.FITTED_TRANSFORM.value
    assert contract.payload["implementation_id"] == "spectrasherpa.selection.ipls"
    assert contract.payload["managed_optimization_eligibility"] == (ManagedOptimizationEligibility.LOCAL.value,)
    assert contract.payload["required_worker_capabilities"] == (WorkerCapability.READ_DATASET.value,)
    assert contract.payload["deterministic"] is False
    assert contract.payload["seed_parameter"] == "random_seed"
    assert contract.payload["target_access"] == "fit_only"
    assert contract.payload["implementation_version"] == "1.1.0"
    assert contract.payload["fitted_state_serializer"] == "spectrasherpa.selection.ipls.state/3"
    assert contract.payload["citations"] and "Nørgaard" in contract.payload["citations"][0]

    input_names = {port.name: port.type_ref for port in metadata.input_ports}
    output_names = {port.name: port.type_ref for port in metadata.output_ports}
    assert input_names["X"] == "spectrasherpa://types/Array2D/1.0"
    assert input_names["y"] == "spectrasherpa://types/TargetMatrix/1.0"
    assert output_names["X_selected"] == "spectrasherpa://types/SpectralDataset/1.0"
    assert output_names["mask"] == "spectrasherpa://types/Array1D/1.0"


def test_ipls_admission_materializes_one_closed_parameter_shape() -> None:
    node = node_registry.create_node("selection.ipls", "ipls", {"n_intervals": 8})
    defaults = node_registry.create_node("selection.ipls", "ipls-default", {})

    assert node.parameters == {
        "n_intervals": 8,
        "max_components": 5,
        "cv_folds": 5,
        "cv_order": "sorted_target",
        "random_seed": 42,
    }
    assert defaults.parameters["n_intervals"] == 20
    assert defaults.parameters["max_components"] == 5


# ── 2. Old/alias/coerced/out-of-range parameters fail closed ───────────


@pytest.mark.parametrize(
    "parameters",
    [
        {"n_best": 1},
        {"n_components": 3},
        {"n_intervals": 10, "n_components": 3, "cv_folds": 3, "n_best": 1},
        {"unexpected_field": True},
        {"n_intervals": 1},
        {"n_intervals": 101},
        {"n_intervals": 10.0},
        {"max_components": 0},
        {"max_components": True},
        {"cv_folds": 1},
        {"cv_folds": 21},
        {"random_seed": -1},
        {"random_seed": 4_294_967_296},
        {"cv_order": "shuffle"},
        {"cv_order": 1},
    ],
)
def test_ipls_rejects_unbounded_coerced_and_alias_parameters(parameters: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        _canonical_ipls_parameters(parameters)


# ── 3. Input shape/target failures before scientific output ────────────


def test_ipls_rejects_multiple_targets_and_undersized_inputs() -> None:
    matrix = np.arange(60, dtype=np.float64).reshape(10, 6)
    with pytest.raises(ValueError, match="exactly one quantitative target"):
        ipls_node._ipls_inputs(matrix, np.ones((10, 2)))
    with pytest.raises(ValueError, match="at least three samples"):
        ipls_node._ipls_inputs(matrix[:2], np.arange(2.0))
    single_feature = np.arange(10, dtype=np.float64).reshape(10, 1)
    with pytest.raises(ValueError, match="two ordered features"):
        ipls_node._ipls_inputs(single_feature, np.arange(10.0))


def test_ipls_rejects_constant_categorical_and_nonfinite_targets() -> None:
    matrix = np.arange(60, dtype=np.float64).reshape(10, 6)
    with pytest.raises(ValueError, match="non-zero variation"):
        ipls_node._ipls_inputs(matrix, np.ones(10))

    categorical = SherpaDataset(
        X=matrix,
        target=np.arange(10.0),
        target_context=TargetContext(target_type="categorical", target_name="class"),
    )
    with pytest.raises(ValueError, match="continuous"):
        ipls_node._ipls_inputs(categorical, None)

    non_finite_target = np.arange(10.0)
    non_finite_target[0] = np.nan
    with pytest.raises(ValueError, match="finite"):
        ipls_node._ipls_inputs(matrix, non_finite_target)


def test_ipls_rejects_excess_intervals_and_undersupported_cv() -> None:
    matrix = np.arange(60, dtype=np.float64).reshape(10, 6)
    target = np.arange(10.0)
    with pytest.raises(ValueError, match="n_intervals may not exceed the feature count"):
        _ipls_dispatch(
            matrix, target, n_intervals=7, max_components=2, cv_folds=3, cv_order="sorted_target", random_seed=42
        )
    with pytest.raises(ValueError, match="cv_folds may not exceed the sample count"):
        _ipls_dispatch(
            matrix, target, n_intervals=2, max_components=2, cv_folds=11, cv_order="sorted_target", random_seed=42
        )


def test_ipls_has_a_representative_absolute_performance_ceiling() -> None:
    rng = np.random.default_rng(507)
    matrix = rng.normal(size=(60, 48))
    target = 1.7 * matrix[:, 17] - 0.8 * matrix[:, 18] + rng.normal(scale=0.05, size=60)

    with PerformanceCeiling("selection.ipls", "60x48-six-interval-four-fold-fit", 5.0).measure():
        result = _ipls_dispatch(
            matrix,
            target,
            n_intervals=6,
            max_components=3,
            cv_folds=4,
            cv_order="sorted_target",
            random_seed=42,
        )

    assert np.asarray(result["feature_mask"], dtype=bool).shape == (48,)


# ── 4. Deterministic near-equal interval boundaries ─────────────────────


@pytest.mark.parametrize(("n_features", "n_intervals"), [(23, 7), (20, 20), (100, 3), (17, 5), (2, 2)])
def test_ipls_interval_bounds_are_deterministic_complete_and_ordered(n_features: int, n_intervals: int) -> None:
    bounds = _interval_bounds(n_features, n_intervals)
    again = _interval_bounds(n_features, n_intervals)

    assert bounds == again
    assert len(bounds) == n_intervals
    assert bounds[0][0] == 0
    assert bounds[-1][1] == n_features
    covered: list[int] = []
    for (lower, upper), (next_lower, _next_upper) in zip(bounds, bounds[1:] + ((n_features, n_features),)):
        assert lower < upper
        covered.extend(range(lower, upper))
        assert upper == next_lower
    assert covered == list(range(n_features))


def test_ipls_interval_bounds_reject_more_intervals_than_features() -> None:
    with pytest.raises(ValueError, match="n_intervals may not exceed the feature count"):
        _interval_bounds(5, 6)


# ── 5. Every interval and the global model share one fold plan ──────────


def test_ipls_all_interval_and_global_models_share_one_fold_plan(monkeypatch: pytest.MonkeyPatch) -> None:
    rng = np.random.default_rng(55)
    matrix = rng.normal(size=(30, 12))
    target = matrix[:, 3] + 0.5 * matrix[:, 8]
    seen_train_sizes: list[int] = []

    original_fit = ipls_node.pls_core.fit_simpls_exact

    def recording_fit(X: np.ndarray, y: np.ndarray, **kwargs: object):
        seen_train_sizes.append(len(X))
        return original_fit(X, y, **kwargs)

    monkeypatch.setattr(ipls_node.pls_core, "fit_simpls_exact", recording_fit)

    result = _ipls_dispatch(
        matrix, target, n_intervals=4, max_components=2, cv_folds=3, cv_order="sorted_target", random_seed=42
    )

    # 4 intervals + 1 global model, each fit across 3 folds and up to 2 component counts.
    assignments = np.asarray(result["fold_assignments"])
    expected_train_sizes = sorted(int(np.sum(assignments != fold)) for fold in range(3))
    observed_unique = sorted(set(seen_train_sizes))
    assert observed_unique == sorted(set(expected_train_sizes))


def test_ipls_component_rmsecv_receives_identical_assignments_for_every_interval() -> None:
    rng = np.random.default_rng(9)
    matrix = rng.normal(size=(24, 10))
    target = matrix[:, 2] - matrix[:, 5]
    assignments = _ipls_fold_assignments(target, cv_folds=4, cv_order="sorted_target", random_seed=42)

    captured: list[np.ndarray] = []
    original = ipls_node._component_rmsecv

    def recording(matrix_, target_, feature_indices, assignments_, *, max_components):
        captured.append(np.array(assignments_, copy=True))
        return original(matrix_, target_, feature_indices, assignments_, max_components=max_components)

    import unittest.mock as mock

    with mock.patch.object(ipls_node, "_component_rmsecv", side_effect=recording):
        _ipls_dispatch(
            matrix, target, n_intervals=3, max_components=2, cv_folds=4, cv_order="sorted_target", random_seed=42
        )

    assert len(captured) == 4  # 3 intervals + 1 global
    for other in captured[1:]:
        np.testing.assert_array_equal(captured[0], other)
        np.testing.assert_array_equal(captured[0], assignments)


# ── 6. Pooled RMSECV, first-minimum, and first-interval tie-breaking ────


def test_ipls_component_rmsecv_matches_an_independent_reference_calculation() -> None:
    rng = np.random.default_rng(0)
    n, p = 40, 12
    matrix = rng.normal(size=(n, p))
    true_weights = np.zeros(p)
    true_weights[3:6] = [2.0, -1.5, 1.0]
    target = matrix @ true_weights + rng.normal(scale=0.1, size=n)

    assignments = _ipls_fold_assignments(target, cv_folds=5, cv_order="sorted_target", random_seed=42)
    feature_indices = np.arange(3, 6)
    subset = matrix[:, feature_indices]

    reference_trace = []
    for k in range(1, 4):
        predictions = np.empty(n)
        for fold in range(5):
            train = assignments != fold
            validate = ~train
            model = PLSRegression(n_components=k, scale=False).fit(subset[train], target[train])
            predictions[validate] = np.asarray(model.predict(subset[validate])).reshape(-1)
        reference_trace.append(float(np.sqrt(np.mean((target - predictions) ** 2))))
    reference_best_k = int(np.argmin(reference_trace)) + 1

    score, components, trace = _component_rmsecv(matrix, target, feature_indices, assignments, max_components=3)

    np.testing.assert_allclose(trace, reference_trace, rtol=0.0, atol=1e-12)
    assert components == reference_best_k
    assert score == pytest.approx(reference_trace[reference_best_k - 1])


def test_ipls_selects_the_first_minimum_component_count_on_a_tie(monkeypatch: pytest.MonkeyPatch) -> None:
    class TiedPLS:
        def predict(self, X: np.ndarray) -> np.ndarray:
            return np.zeros((len(X), 1))

    monkeypatch.setattr(ipls_node.pls_core, "fit_simpls_exact", lambda *_args, **_kwargs: TiedPLS())
    matrix = np.arange(60, dtype=np.float64).reshape(10, 6)
    target = np.abs(np.arange(10.0) - 4.5) + 1.0
    assignments = _ipls_fold_assignments(target, cv_folds=5, cv_order="sorted_target", random_seed=42)

    _score, components, trace = _component_rmsecv(matrix, target, np.arange(6), assignments, max_components=4)

    assert len(set(trace)) == 1  # every component count ties exactly
    assert components == 1


def test_ipls_selects_the_true_global_minimum_on_a_non_monotonic_trace(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Component selection is the global RMSECV minimum, not a local-minimum /
    turning-point detector: an early shallow dip must not shadow a deeper
    minimum reached at a higher component count."""

    errors_by_component = {1: 1.0, 2: 3.0, 3: 0.5, 4: 2.0}

    class ProbePLS:
        def __init__(self, n_components: int) -> None:
            self.n_components = n_components

        def predict(self, X: np.ndarray) -> np.ndarray:
            # Column 0 carries the true target value for each row, so the
            # residual for every held-out sample is exactly the configured
            # per-component-count error regardless of fold membership.
            target_values = X[:, 0]
            return (target_values - errors_by_component[self.n_components]).reshape(-1, 1)

    monkeypatch.setattr(
        ipls_node.pls_core,
        "fit_simpls_exact",
        lambda *_args, n_components, **_kwargs: ProbePLS(n_components),
    )
    target = np.linspace(0.0, 9.0, 10)
    matrix = np.column_stack([target, np.arange(10.0), np.arange(10.0) * 2.0, np.arange(10.0) * 3.0])
    assignments = _ipls_fold_assignments(target, cv_folds=5, cv_order="sorted_target", random_seed=42)

    _score, components, trace = _component_rmsecv(matrix, target, np.arange(4), assignments, max_components=4)

    np.testing.assert_allclose(trace, [1.0, 3.0, 0.5, 2.0])
    # The trace rises from k=1 to k=2 before falling to its true minimum at
    # k=3: a local-minimum/turning-point rule would wrongly stop at k=1.
    assert components == 3


def test_ipls_selects_the_first_interval_on_a_tied_rmsecv(monkeypatch: pytest.MonkeyPatch) -> None:
    def tied_component_rmsecv(matrix, target, feature_indices, assignments, *, max_components):
        del matrix, target, feature_indices, assignments, max_components
        return 1.0, 1, (1.0,)

    monkeypatch.setattr(ipls_node, "_component_rmsecv", tied_component_rmsecv)
    rng = np.random.default_rng(2)
    matrix = rng.normal(size=(20, 10))
    target = rng.normal(size=20)

    result = _ipls_dispatch(
        matrix, target, n_intervals=5, max_components=2, cv_folds=4, cv_order="sorted_target", random_seed=42
    )

    assert result["best_interval"] == 0


# ── 7. A synthetic signal confined to a known interval selects it ──────


def test_ipls_recovers_the_known_signal_interval(ipls_data: tuple[SherpaDataset, np.ndarray]) -> None:
    dataset, target = ipls_data
    node = IPLSNode("ipls", {"n_intervals": 8, "max_components": 3, "cv_folds": 4, "random_seed": 42})

    state = node.fit_fitted_state(dataset, target)

    lower, upper = state["interval_bounds"][state["best_interval"]]
    # Signal lives at feature indices 10, 11, 12; the winning interval must
    # contain a majority of the true signal region (exact alignment isn't
    # guaranteed when the signal straddles a boundary).
    signal = {10, 11, 12}
    overlap = signal & set(range(lower, upper))
    assert len(overlap) >= 2


# ── 8. Honest full-spectrum comparison even when the interval loses ─────


def test_ipls_reports_honest_global_comparison_when_interval_does_not_beat_it() -> None:
    rng = np.random.default_rng(71)
    n, p = 36, 18
    matrix = rng.normal(size=(n, p))
    # Spread real, additive signal across every feature so the full-spectrum
    # model has far more information than any single narrow interval.
    weights = rng.normal(size=p)
    target = matrix @ weights + rng.normal(scale=0.02, size=n)

    result = _ipls_dispatch(
        matrix, target, n_intervals=9, max_components=2, cv_folds=4, cv_order="sorted_target", random_seed=42
    )

    assert result["beats_global_rmsecv"] == (result["best_rmsecv"] < result["global_rmsecv"])
    assert not result["beats_global_rmsecv"]
    assert result["global_rmsecv"] > 0
    assert result["best_rmsecv"] > 0


# ── 9. Live execution and generated Python agree exactly ───────────────


@pytest.mark.asyncio
async def test_ipls_live_and_exported_execution_share_one_typed_operation(
    ipls_data: tuple[SherpaDataset, np.ndarray],
) -> None:
    dataset, target = ipls_data
    original_axis = np.asarray(dataset.feature_axis.values).copy()
    original_mask = np.asarray(dataset.feature_axis.include_mask).copy()
    node = IPLSNode("ipls", {"n_intervals": 6, "max_components": 3, "cv_folds": 4, "random_seed": 113})

    live = await node.execute(X=dataset, y=target)
    namespace = {"dataset": dataset, "target": target, "results": {}}
    exec("\n".join(node.generate_python({"X": "dataset", "y": "target"}, indent="")), namespace)
    exported = namespace["results"]["ipls"]

    np.testing.assert_array_equal(exported["mask"], live.outputs["mask"])
    np.testing.assert_array_equal(exported["scores"], live.outputs["scores"])
    np.testing.assert_array_equal(exported["X_selected"].X, live.outputs["X_selected"].X)
    np.testing.assert_array_equal(dataset.feature_axis.values, original_axis)
    np.testing.assert_array_equal(dataset.feature_axis.include_mask, original_mask)
    assert live.diagnostics["selection_scope"] == "full_calibration_fit_not_performance_evidence"
    exported_transform_state = exported["default"].provenance[-1].parameters["transform_state"]
    assert list(live.diagnostics["interval_rmsecv"]) == list(exported_transform_state["interval_rmsecv"])
    assert live.diagnostics["split_digest"] == exported_transform_state["split_digest"]
    assert list(live.diagnostics["interval_components"]) == list(exported_transform_state["interval_components"])


# ── 10. Fit/apply round-trip; apply never reads or infers y ────────────


def test_ipls_fit_state_round_trips_and_apply_never_reads_target(
    ipls_data: tuple[SherpaDataset, np.ndarray], monkeypatch: pytest.MonkeyPatch
) -> None:
    dataset, target = ipls_data
    labeled_axis = dataset.feature_axis
    labeled_axis.labels = [f"band-{index}" for index in range(dataset.n_features)]
    dataset.feature_axis = labeled_axis
    original_values = np.array(dataset.feature_axis.values, copy=True)
    original_labels = list(dataset.feature_axis.labels)
    node = IPLSNode("ipls", {"n_intervals": 6, "max_components": 3, "cv_folds": 4, "random_seed": 113})

    state = node.fit_fitted_state(dataset, target)
    assert state["serializer"] == "spectrasherpa.selection.ipls.state/3"
    assert state["reference_samples"] == 48
    assert state["feature_count"] == 24

    monkeypatch.setattr(ipls_node, "bind_y", lambda *_args, **_kwargs: pytest.fail("apply read a target"))
    application = SherpaDataset(
        X=np.array(dataset.X, copy=True),
        feature_axis=dataset.feature_axis.model_copy(deep=True),
    )
    selected = node.apply_fitted_state(application, state)

    mask = np.asarray(state["feature_mask"], dtype=bool)
    np.testing.assert_array_equal(selected.X, dataset.X[:, mask])
    assert selected.feature_axis.labels == [label for label, keep in zip(original_labels, mask, strict=True) if keep]
    np.testing.assert_array_equal(dataset.feature_axis.values, original_values)
    assert dataset.feature_axis.labels == original_labels

    # Re-fitting from the round-tripped state must reproduce the identical mask.
    replayed = _validate_ipls_state(state)
    np.testing.assert_array_equal(np.asarray(replayed["feature_mask"]), mask)


# ── 11. Feature-count, axis-value, axis-label, and unit drift fail apply ──


def test_ipls_apply_rejects_feature_count_axis_value_label_and_unit_drift(
    ipls_data: tuple[SherpaDataset, np.ndarray],
) -> None:
    dataset, target = ipls_data
    labeled_axis = dataset.feature_axis
    labeled_axis.labels = [f"band-{index}" for index in range(dataset.n_features)]
    dataset.feature_axis = labeled_axis
    node = IPLSNode("ipls", {"n_intervals": 6, "max_components": 3, "cv_folds": 4, "random_seed": 113})
    state = node.fit_fitted_state(dataset, target)

    fewer_features = SherpaDataset(X=np.array(dataset.X[:, :-1], copy=True))
    with pytest.raises(ValueError, match="fitted feature count"):
        node.apply_fitted_state(fewer_features, state)

    drifted_values = dataset.feature_axis.model_copy(deep=True)
    drifted_values.values = np.asarray(drifted_values.values) + 0.5
    drifted_values_ds = SherpaDataset(X=np.array(dataset.X, copy=True), feature_axis=drifted_values)
    with pytest.raises(ValueError, match="fitted feature axis"):
        node.apply_fitted_state(drifted_values_ds, state)

    drifted_labels = dataset.feature_axis.model_copy(deep=True)
    drifted_labels.labels = [f"other-{index}" for index in range(dataset.n_features)]
    drifted_labels_ds = SherpaDataset(X=np.array(dataset.X, copy=True), feature_axis=drifted_labels)
    with pytest.raises(ValueError, match="fitted feature axis"):
        node.apply_fitted_state(drifted_labels_ds, state)

    drifted_units = dataset.feature_axis.model_copy(deep=True)
    drifted_units.units = "nm"
    drifted_units_ds = SherpaDataset(X=np.array(dataset.X, copy=True), feature_axis=drifted_units)
    with pytest.raises(ValueError, match="fitted feature axis"):
        node.apply_fitted_state(drifted_units_ds, state)


# ── 12. Inputs are never mutated by fit or apply ────────────────────────


def test_ipls_fit_and_apply_do_not_mutate_source_matrix_target_or_metadata(
    ipls_data: tuple[SherpaDataset, np.ndarray],
) -> None:
    dataset, target = ipls_data
    original_matrix = np.array(dataset.X, copy=True)
    original_target = np.array(target, copy=True)
    original_sample_labels = list(dataset.sample_axis.labels)
    original_meta = dict(dataset.meta)

    node = IPLSNode("ipls", {"n_intervals": 6, "max_components": 3, "cv_folds": 4, "random_seed": 113})
    state = node.fit_fitted_state(dataset, target)
    node.apply_fitted_state(dataset, state)

    np.testing.assert_array_equal(dataset.X, original_matrix)
    np.testing.assert_array_equal(target, original_target)
    assert dataset.sample_axis.labels == original_sample_labels
    assert dataset.meta == original_meta


# ── 13. Every meaningful state field is mutation-tested; extra/missing fields fail closed ──


@pytest.mark.parametrize(
    "mutation",
    [
        lambda state: state["feature_mask"].__setitem__(0, not state["feature_mask"][0]),
        lambda state: state["importance_scores"].__setitem__(0, -1.0),
        lambda state: state["interval_rmsecv"].__setitem__(0, -1.0),
        lambda state: state["interval_components"].__setitem__(0, state["interval_components"][0] + 5),
        lambda state: state.update(best_interval=(state["best_interval"] + 1) % state["n_intervals"]),
        lambda state: state.update(best_components=state["best_components"] + 1),
        lambda state: state.update(best_rmsecv=state["best_rmsecv"] + 1.0),
        lambda state: state.update(global_rmsecv=-1.0),
        lambda state: state.update(global_components=state["global_components"] + 1),
        lambda state: state.update(beats_global_rmsecv=not state["beats_global_rmsecv"]),
        lambda state: state["fold_assignments"].__setitem__(0, (state["fold_assignments"][0] + 1) % state["cv_folds"]),
        lambda state: state.update(split_digest="0" * 64),
        lambda state: state.update(model_fit_budget=state["model_fit_budget"] + 1),
        lambda state: state.update(reference_samples=state["reference_samples"] + 1),
        lambda state: state.update(selection_scope="unbounded_predictive_claim"),
        lambda state: state["interval_bounds"].__setitem__(0, [0, state["interval_bounds"][0][1] + 1]),
        lambda state: state["interval_component_rmsecv"][0].__setitem__(0, -1.0),
    ],
)
def test_ipls_closed_state_rejects_mutated_or_forged_scientific_records(
    ipls_data: tuple[SherpaDataset, np.ndarray], mutation
) -> None:
    dataset, target = ipls_data
    state = IPLSNode("ipls", {"n_intervals": 6, "max_components": 3, "cv_folds": 4}).fit_fitted_state(dataset, target)
    mutation(state)
    with pytest.raises(ValueError):
        _validate_ipls_state(state)


def test_ipls_closed_state_rejects_extra_and_missing_fields(
    ipls_data: tuple[SherpaDataset, np.ndarray],
) -> None:
    dataset, target = ipls_data
    state = IPLSNode("ipls", {"n_intervals": 6, "max_components": 3, "cv_folds": 4}).fit_fitted_state(dataset, target)

    with pytest.raises(ValueError, match="closed serializer schema"):
        _validate_ipls_state({**state, "extra_field": True})

    truncated = dict(state)
    del truncated["split_digest"]
    with pytest.raises(ValueError, match="closed serializer schema"):
        _validate_ipls_state(truncated)


def test_ipls_closed_state_rejects_coordinated_noncanonical_interval_partition(
    ipls_data: tuple[SherpaDataset, np.ndarray],
) -> None:
    dataset, target = ipls_data
    state = IPLSNode("ipls", {"n_intervals": 6, "max_components": 3, "cv_folds": 4}).fit_fitted_state(dataset, target)
    forged = copy.deepcopy(state)
    forged["interval_bounds"][0][1] += 1
    forged["interval_bounds"][1][0] += 1

    forged_scores = [0.0] * forged["feature_count"]
    for interval_index, (lower, upper) in enumerate(forged["interval_bounds"]):
        score = 1.0 / (1.0 + forged["interval_rmsecv"][interval_index])
        forged_scores[lower:upper] = [score] * (upper - lower)
    forged["importance_scores"] = forged_scores
    selected_lower, selected_upper = forged["interval_bounds"][forged["best_interval"]]
    forged["feature_mask"] = [
        selected_lower <= feature_index < selected_upper for feature_index in range(forged["feature_count"])
    ]

    with pytest.raises(ValueError, match="canonical near-equal partition"):
        _validate_ipls_state(forged)


def test_ipls_closed_state_rejects_component_trace_above_declared_maximum(
    ipls_data: tuple[SherpaDataset, np.ndarray],
) -> None:
    dataset, target = ipls_data
    state = IPLSNode("ipls", {"n_intervals": 6, "max_components": 2, "cv_folds": 4}).fit_fitted_state(dataset, target)
    forged = copy.deepcopy(state)
    forged["global_component_rmsecv"].append(0.0)
    forged["global_components"] = 3
    forged["global_rmsecv"] = 0.0
    forged["beats_global_rmsecv"] = False

    with pytest.raises(ValueError, match="global component trace"):
        _validate_ipls_state(forged)


def test_ipls_closed_state_rejects_component_trace_above_interval_width(
    ipls_data: tuple[SherpaDataset, np.ndarray],
) -> None:
    dataset, target = ipls_data
    state = IPLSNode("ipls", {"n_intervals": 6, "max_components": 5, "cv_folds": 4}).fit_fitted_state(dataset, target)
    forged = copy.deepcopy(state)
    forged["interval_component_rmsecv"][0].append(0.0)
    forged["interval_components"][0] = 5
    forged["interval_rmsecv"][0] = 0.0

    with pytest.raises(ValueError, match="component trace"):
        _validate_ipls_state(forged)


def test_ipls_closed_state_rejects_component_trace_above_training_fold_support() -> None:
    rng = np.random.default_rng(813)
    matrix = rng.normal(size=(6, 10))
    target = matrix[:, 3] + rng.normal(scale=0.1, size=6)
    state = IPLSNode("ipls", {"n_intervals": 2, "max_components": 5, "cv_folds": 5}).fit_fitted_state(matrix, target)
    forged = copy.deepcopy(state)
    forged["global_component_rmsecv"].append(0.0)
    forged["global_components"] = len(forged["global_component_rmsecv"])
    forged["global_rmsecv"] = 0.0
    forged["beats_global_rmsecv"] = False

    with pytest.raises(ValueError, match="global component trace"):
        _validate_ipls_state(forged)


# ── 14. The fit-budget ceiling rejects before any PLS fit ──────────────


def test_ipls_fit_budget_is_rejected_before_any_pls_fit(monkeypatch: pytest.MonkeyPatch) -> None:
    call_count = {"n": 0}
    original_fit = ipls_node.pls_core.fit_simpls_exact

    def counting_fit(X: np.ndarray, y: np.ndarray, **kwargs: object):
        call_count["n"] += 1
        return original_fit(X, y, **kwargs)

    monkeypatch.setattr(ipls_node.pls_core, "fit_simpls_exact", counting_fit)
    rng = np.random.default_rng(3)
    matrix = rng.normal(size=(60, 200))
    target = rng.normal(size=60)

    with pytest.raises(ValueError, match="exceeds"):
        _ipls_dispatch(
            matrix, target, n_intervals=100, max_components=30, cv_folds=20, cv_order="sorted_target", random_seed=42
        )

    assert call_count["n"] == 0


def test_ipls_fit_budget_matches_the_declared_formula_and_rejects_forged_values(
    ipls_data: tuple[SherpaDataset, np.ndarray],
) -> None:
    dataset, target = ipls_data
    state = IPLSNode("ipls", {"n_intervals": 6, "max_components": 3, "cv_folds": 4}).fit_fitted_state(dataset, target)
    expected = (6 + 1) * 4 * 3
    assert state["model_fit_budget"] == expected


# ── 15. The numeric authority composes inside an outer CV loop without a second implementation ──


def test_ipls_numeric_authority_composes_inside_an_outer_cv_loop() -> None:
    """Prove `_ipls_dispatch` is a bare (X, y, params) -> result function that an outer
    leakage-safe validator (e.g. `selection.nested_cv`) can call per training fold exactly
    like it already calls `cars_node._cars_run` / `mcuve_node._mcuve_dispatch` /
    `spa_node._spa_projections`,
    with no second iPLS implementation required."""

    rng = np.random.default_rng(823)
    n, p = 60, 20
    matrix = rng.normal(size=(n, p))
    target = matrix[:, 5] + 0.5 * matrix[:, 6] + rng.normal(scale=0.05, size=n)

    outer = KFold(n_splits=3, shuffle=True, random_state=7)
    fold_masks = []
    for train_idx, _test_idx in outer.split(matrix):
        result = _ipls_dispatch(
            matrix[train_idx],
            target[train_idx],
            n_intervals=5,
            max_components=2,
            cv_folds=3,
            cv_order="sorted_target",
            random_seed=42,
        )
        mask = np.asarray(result["feature_mask"], dtype=bool)
        assert mask.shape == (p,)
        fold_masks.append(mask)

    assert len(fold_masks) == 3
    assert all(mask.any() for mask in fold_masks)


# ── 16. See test_selection_phase2.py for updated legacy smoke coverage ──
