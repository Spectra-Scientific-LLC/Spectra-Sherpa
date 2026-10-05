"""C2k canonical stability-selection scientific and execution proofs."""

from __future__ import annotations

import copy

import numpy as np
import pytest
from sklearn.cross_decomposition import PLSRegression

import spectra_sherpa.app.services.dag.nodes  # noqa: F401 - populate built-ins
from spectra_sherpa.app.lib.sherpa_dataset import SampleAxis, SherpaDataset, SpectralAxis
from spectra_sherpa.app.services.dag.node_base import node_registry
from spectra_sherpa.app.services.dag.nodes.selection import stability_node
from spectra_sherpa.app.services.dag.nodes.selection.stability_node import (
    StabilitySelectionNode,
    _base_scores,
    _canonical_stability_parameters,
    _stability_dispatch,
    _validate_stability_state,
)
from spectra_sherpa.execution_contract_vocabulary import LifecycleKind, ManagedOptimizationEligibility, RuntimeFamily
from tests.performance_contract import PerformanceCeiling


@pytest.fixture
def stability_data() -> tuple[SherpaDataset, np.ndarray]:
    rng = np.random.default_rng(9021)
    matrix = rng.normal(size=(42, 16))
    target = 2.2 * matrix[:, 2] - 1.4 * matrix[:, 10] + rng.normal(scale=0.05, size=42)
    return (
        SherpaDataset(
            X=matrix,
            feature_axis=SpectralAxis(
                values=np.linspace(900.0, 1800.0, 16),
                labels=[f"band-{index}" for index in range(16)],
                units="cm-1",
            ),
            sample_axis=SampleAxis(labels=[f"sample-{index}" for index in range(42)]),
            target=target,
        ),
        target,
    )


def test_stability_has_one_exact_local_fitted_transform_contract() -> None:
    contract = node_registry.get_metadata("selection.stability").resolved_execution_contract()
    assert contract is not None
    assert contract.payload["operation_id"] == "selection.stability"
    assert contract.payload["runtime_family"] == RuntimeFamily.SHERPA_NATIVE.value
    assert contract.payload["lifecycle_kind"] == LifecycleKind.FITTED_TRANSFORM.value
    assert contract.payload["managed_optimization_eligibility"] == (ManagedOptimizationEligibility.LOCAL.value,)
    assert contract.payload["target_access"] == "fit_only"
    assert contract.payload["seed_parameter"] == "random_seed"
    assert contract.payload["implementation_version"] == "1.2.0"
    assert contract.payload["fitted_state_serializer"] == "spectrasherpa.selection.stability.state/4"
    assert any("10.1111/j.1467-9868.2010.00740.x" in item for item in contract.payload["citations"])
    assert any("mda.tools/docs/pls--variable-selection" in item for item in contract.payload["citations"])
    assert any("10.1002/cem.1289" in item for item in contract.payload["citations"])


def test_stability_admission_is_closed_and_removes_prototype_sampling_controls() -> None:
    node = node_registry.create_node("selection.stability", "stability", {})
    assert node.parameters == {
        "base_method": "vip",
        "base_threshold": 1.0,
        "selection_probability_threshold": 0.6,
        "n_resamples": 100,
        "n_components": 5,
        "random_seed": 42,
    }
    for invalid in (
        {"n_bootstrap": 100},
        {"subsample_fraction": 0.5},
        {"stability_threshold": 0.6},
        {"base_method": "invented"},
        {"base_threshold": 0.0},
        {"selection_probability_threshold": 0.5},
        {"n_resamples": 19},
        {"n_components": True},
        {"random_seed": -1},
    ):
        with pytest.raises(ValueError):
            _canonical_stability_parameters(invalid)


def test_stability_matches_independent_half_sample_coefficient_oracle() -> None:
    rng = np.random.default_rng(44)
    matrix = rng.normal(size=(30, 12))
    target = 1.7 * matrix[:, 3] - 0.8 * matrix[:, 9] + rng.normal(scale=0.03, size=30)
    parameters = {
        "base_method": "coef_abs",
        "base_threshold": 0.1,
        "selection_probability_threshold": 0.6,
        "n_resamples": 20,
        "n_components": 2,
        "random_seed": 719,
    }
    actual = _stability_dispatch(matrix, target, **parameters)

    oracle_rng = np.random.default_rng(parameters["random_seed"])
    half_size = matrix.shape[0] // 2
    indices = np.empty((parameters["n_resamples"], half_size), dtype=np.int64)
    counts = np.zeros(matrix.shape[1], dtype=np.int64)
    score_sum = np.zeros(matrix.shape[1], dtype=np.float64)
    for ordinal in range(parameters["n_resamples"]):
        chosen = oracle_rng.choice(matrix.shape[0], size=half_size, replace=False)
        indices[ordinal] = chosen
        model = PLSRegression(n_components=parameters["n_components"], scale=False)
        model.fit(matrix[chosen], target[chosen])
        scores = np.abs(np.asarray(model.coef_).reshape(-1))
        counts += scores >= parameters["base_threshold"]
        score_sum += scores
    frequencies = counts / parameters["n_resamples"]

    np.testing.assert_array_equal(actual["half_sample_indices"], indices)
    np.testing.assert_array_equal(actual["selection_counts"], counts)
    np.testing.assert_allclose(actual["selection_frequencies"], frequencies, rtol=0.0, atol=0.0)
    # Single-response SIMPLS and NIPALS are algebraically equivalent; allow
    # only floating-point ordering noise between the independent authorities.
    np.testing.assert_allclose(
        actual["mean_base_scores"],
        score_sum / parameters["n_resamples"],
        rtol=1e-13,
        atol=1e-14,
    )
    np.testing.assert_array_equal(actual["feature_mask"], frequencies >= parameters["selection_probability_threshold"])


def test_stability_seed_reproduces_complete_half_sample_decision() -> None:
    rng = np.random.default_rng(84)
    matrix = rng.normal(size=(32, 10))
    target = matrix[:, 2] - matrix[:, 7]
    parameters = {
        "base_method": "coef_abs",
        "base_threshold": 0.05,
        "selection_probability_threshold": 0.6,
        "n_resamples": 20,
        "n_components": 2,
        "random_seed": 53,
    }
    assert _stability_dispatch(matrix, target, **parameters) == _stability_dispatch(matrix, target, **parameters)


def test_stability_rejects_an_unsupported_component_request_instead_of_narrowing_it() -> None:
    matrix = np.arange(48.0).reshape(8, 6)
    target = np.linspace(0.0, 1.0, 8)

    with pytest.raises(ValueError, match="requested 4 PLS components.*supports at most 3"):
        _stability_dispatch(
            matrix,
            target,
            base_method="coef_abs",
            base_threshold=0.01,
            selection_probability_threshold=0.6,
            n_resamples=20,
            n_components=4,
            random_seed=42,
        )


@pytest.mark.parametrize("base_method", ["vip", "coef_abs", "selectivity_ratio"])
def test_each_declared_pls_base_rule_produces_finite_bounded_frequencies(base_method: str) -> None:
    rng = np.random.default_rng(187)
    matrix = rng.normal(size=(32, 10))
    target = 1.5 * matrix[:, 1] - matrix[:, 7]
    result = _stability_dispatch(
        matrix,
        target,
        base_method=base_method,
        base_threshold=0.01,
        selection_probability_threshold=0.6,
        n_resamples=20,
        n_components=2,
        random_seed=62,
    )
    frequencies = np.asarray(result["selection_frequencies"])
    assert np.isfinite(frequencies).all()
    assert np.all((0.0 <= frequencies) & (frequencies <= 1.0))


def test_selectivity_ratio_base_rule_matches_target_projection_oracle() -> None:
    rng = np.random.default_rng(221)
    matrix = rng.normal(size=(28, 9))
    target = 1.8 * matrix[:, 2] - 0.9 * matrix[:, 6]
    model = stability_node.pls_core.fit_simpls_exact(matrix, target, n_components=2, scale=False)
    actual = _base_scores(model, matrix, "selectivity_ratio")

    coefficients = np.asarray(model.coefficients).reshape(-1)
    centered = matrix - np.mean(matrix, axis=0)
    target_scores = centered @ coefficients
    # Independent least-squares reconstruction of every X variable from the
    # one target-projection score.  Reusing ``coefficients`` here would merely
    # repeat the implementation defect this test is intended to catch.
    target_loading = np.linalg.lstsq(target_scores[:, None], centered, rcond=None)[0].reshape(-1)
    target_projection = np.outer(target_scores, target_loading)
    residual_matrix = centered - target_projection
    explained = np.var(target_projection, axis=0)
    residual = np.var(residual_matrix, axis=0)
    floor = np.finfo(np.float64).eps * max(float(np.max(explained)), 1.0)

    np.testing.assert_allclose(target_scores @ residual_matrix, np.zeros(matrix.shape[1]), atol=1e-12)
    np.testing.assert_allclose(actual, explained / np.maximum(residual, floor), rtol=1e-13, atol=1e-13)


def test_stability_requires_target_only_during_fit(
    stability_data: tuple[SherpaDataset, np.ndarray], monkeypatch: pytest.MonkeyPatch
) -> None:
    dataset, target = stability_data
    node = StabilitySelectionNode(
        "stability",
        {
            "base_method": "coef_abs",
            "base_threshold": 0.05,
            "selection_probability_threshold": 0.6,
            "n_resamples": 20,
            "n_components": 2,
        },
    )
    with pytest.raises(ValueError):
        node.fit_fitted_state(SherpaDataset(X=np.array(dataset.X), feature_axis=dataset.feature_axis), None)
    state = node.fit_fitted_state(dataset, target)
    monkeypatch.setattr(stability_node, "bind_y", lambda *_a, **_k: pytest.fail("apply read target"))
    applied = node.apply_fitted_state(SherpaDataset(X=np.array(dataset.X), feature_axis=dataset.feature_axis), state)
    np.testing.assert_array_equal(applied.X, dataset.X[:, np.asarray(state["feature_mask"], dtype=bool)])


def test_stability_fit_apply_preserves_inputs_and_rejects_axis_drift(
    stability_data: tuple[SherpaDataset, np.ndarray],
) -> None:
    dataset, target = stability_data
    source = np.array(dataset.X, copy=True)
    source_axis = np.array(dataset.feature_axis.values, copy=True)
    source_target = np.array(target, copy=True)
    node = StabilitySelectionNode(
        "stability",
        {
            "base_method": "coef_abs",
            "base_threshold": 0.05,
            "selection_probability_threshold": 0.6,
            "n_resamples": 20,
            "n_components": 2,
        },
    )
    state = node.fit_fitted_state(dataset, target)
    node.apply_fitted_state(dataset, state)
    np.testing.assert_array_equal(dataset.X, source)
    np.testing.assert_array_equal(dataset.feature_axis.values, source_axis)
    np.testing.assert_array_equal(target, source_target)

    drifted_axis = dataset.feature_axis.model_copy(deep=True)
    drifted_axis.values = np.asarray(drifted_axis.values) + 0.25
    with pytest.raises(ValueError, match="fitted feature axis"):
        node.apply_fitted_state(SherpaDataset(X=source, feature_axis=drifted_axis), state)


def test_stability_does_not_silently_skip_a_failed_base_fit(monkeypatch: pytest.MonkeyPatch) -> None:
    rng = np.random.default_rng(121)
    matrix = rng.normal(size=(20, 8))
    target = matrix[:, 1]

    def fail_fit(*_args, **_kwargs):
        raise FloatingPointError("synthetic fit failure")

    monkeypatch.setattr(stability_node.pls_core, "fit_simpls_exact", fail_fit)
    with pytest.raises(RuntimeError, match="half-sample 0"):
        _stability_dispatch(
            matrix,
            target,
            base_method="coef_abs",
            base_threshold=0.01,
            selection_probability_threshold=0.6,
            n_resamples=20,
            n_components=2,
            random_seed=42,
        )


@pytest.mark.asyncio
async def test_stability_live_and_generated_python_share_one_operation(
    stability_data: tuple[SherpaDataset, np.ndarray],
) -> None:
    dataset, target = stability_data
    node = StabilitySelectionNode(
        "stability",
        {
            "base_method": "coef_abs",
            "base_threshold": 0.05,
            "selection_probability_threshold": 0.6,
            "n_resamples": 20,
            "n_components": 2,
            "random_seed": 91,
        },
    )
    live = await node.execute(X=dataset, y=target)
    namespace = {"dataset": dataset, "target": target, "results": {}}
    exec("\n".join(node.generate_python({"X": "dataset", "y": "target"}, indent="")), namespace)  # noqa: S102
    generated = namespace["results"]["stability"]
    np.testing.assert_array_equal(generated["mask"], live.outputs["mask"])
    np.testing.assert_array_equal(generated["scores"], live.outputs["scores"])
    np.testing.assert_array_equal(generated["X_selected"].X, live.outputs["X_selected"].X)


@pytest.mark.parametrize(
    "mutation",
    [
        lambda state: state.update(serializer="spectrasherpa.selection.stability.state/1"),
        lambda state: state["feature_mask"].__setitem__(0, not state["feature_mask"][0]),
        lambda state: state["selection_counts"].__setitem__(0, state["selection_counts"][0] + 1),
        lambda state: state["selection_frequencies"].__setitem__(0, 0.123),
        lambda state: state["half_sample_indices"][0].reverse(),
        lambda state: state.update(half_sample_digest="0" * 64),
        lambda state: state.update(model_fit_count=19),
        lambda state: state.update(selection_scope="predictive_performance_evidence"),
        lambda state: state.update(formal_error_control_claimed=True),
    ],
)
def test_stability_closed_state_rejects_mutation(stability_data: tuple[SherpaDataset, np.ndarray], mutation) -> None:
    dataset, target = stability_data
    state = StabilitySelectionNode(
        "stability",
        {
            "base_method": "coef_abs",
            "base_threshold": 0.05,
            "selection_probability_threshold": 0.6,
            "n_resamples": 20,
            "n_components": 2,
        },
    ).fit_fitted_state(dataset, target)
    forged = copy.deepcopy(state)
    mutation(forged)
    with pytest.raises(ValueError):
        _validate_stability_state(forged)


def test_stability_fixed_workload_stays_inside_reviewed_ceiling() -> None:
    rng = np.random.default_rng(405)
    matrix = rng.normal(size=(80, 240))
    target = matrix[:, 7] - 0.6 * matrix[:, 133] + rng.normal(scale=0.05, size=80)
    with PerformanceCeiling("selection.stability", "80x240-coef-abs", 5.0).measure():
        result = _stability_dispatch(
            matrix,
            target,
            base_method="coef_abs",
            base_threshold=0.05,
            selection_probability_threshold=0.6,
            n_resamples=20,
            n_components=3,
            random_seed=42,
        )
    assert result["model_fit_count"] == 20
