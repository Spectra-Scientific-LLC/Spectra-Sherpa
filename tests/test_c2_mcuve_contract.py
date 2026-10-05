"""C2k canonical MC-UVE scientific, execution, and export proofs."""

from __future__ import annotations

import copy

import numpy as np
import pytest
from sklearn.cross_decomposition import PLSRegression

import spectra_sherpa.app.services.dag.nodes  # noqa: F401 - populate built-ins
from spectra_sherpa.app.lib.sherpa_dataset import SampleAxis, SherpaDataset, SpectralAxis
from spectra_sherpa.app.services.dag.node_base import node_registry
from spectra_sherpa.app.services.dag.nodes.selection import mcuve_node, nested_cv_node
from spectra_sherpa.app.services.dag.nodes.selection.mcuve_node import (
    MCUVENode,
    _canonical_mcuve_parameters,
    _coefficient_sd_floor,
    _mcuve_dispatch,
    _validate_mcuve_state,
)
from spectra_sherpa.execution_contract_vocabulary import LifecycleKind, ManagedOptimizationEligibility, RuntimeFamily
from tests.performance_contract import PerformanceCeiling


@pytest.fixture
def mcuve_data() -> tuple[SherpaDataset, np.ndarray]:
    rng = np.random.default_rng(8701)
    matrix = rng.normal(size=(44, 18))
    target = 2.4 * matrix[:, 3] - 1.6 * matrix[:, 11] + rng.normal(scale=0.05, size=matrix.shape[0])
    dataset = SherpaDataset(
        X=matrix,
        feature_axis=SpectralAxis(
            values=np.linspace(950.0, 1850.0, matrix.shape[1]),
            labels=[f"band-{index}" for index in range(matrix.shape[1])],
            units="cm-1",
        ),
        sample_axis=SampleAxis(labels=[f"sample-{index}" for index in range(matrix.shape[0])]),
        target=target,
    )
    return dataset, target


def test_mcuve_has_one_exact_local_fitted_transform_contract() -> None:
    metadata = node_registry.get_metadata("selection.mcuve")
    contract = metadata.resolved_execution_contract()

    assert contract is not None
    assert contract.payload["operation_id"] == "selection.mcuve"
    assert contract.payload["runtime_family"] == RuntimeFamily.SHERPA_NATIVE.value
    assert contract.payload["lifecycle_kind"] == LifecycleKind.FITTED_TRANSFORM.value
    assert contract.payload["implementation_id"] == "spectrasherpa.selection.mcuve"
    assert contract.payload["managed_optimization_eligibility"] == (ManagedOptimizationEligibility.LOCAL.value,)
    assert contract.payload["target_access"] == "fit_only"
    assert contract.payload["seed_parameter"] == "random_seed"
    assert contract.payload["implementation_version"] == "1.2.0"
    assert contract.payload["fitted_state_serializer"] == "spectrasherpa.selection.mcuve.state/4"
    assert any("10.1016/j.chemolab.2007.10.001" in item for item in contract.payload["citations"])


def test_original_uve_identity_is_not_retained_as_an_alias() -> None:
    assert "selection.uve" not in node_registry.list_nodes()
    with pytest.raises(KeyError):
        node_registry.get_metadata("selection.uve")


def test_mcuve_admission_is_closed_and_rejects_the_noise_hybrid() -> None:
    node = node_registry.create_node("selection.mcuve", "mcuve", {"n_variables": 7})
    assert node.parameters == {
        "n_components": 5,
        "n_resamples": 100,
        "calibration_fraction": 0.8,
        "n_variables": 7,
        "random_seed": 42,
    }
    for invalid in (
        {"test_fraction": 0.2},
        {"noise_percentile": 90.0},
        {"cutoff_percentile": 90.0},
        {"n_components": True},
        {"n_components": 51},
        {"n_resamples": 19},
        {"calibration_fraction": 0.49},
        {"n_variables": 0},
        {"random_seed": -1},
    ):
        with pytest.raises(ValueError):
            _canonical_mcuve_parameters(invalid)


def test_mcuve_matches_an_independent_coefficient_stability_oracle() -> None:
    rng = np.random.default_rng(102)
    matrix = rng.normal(size=(32, 12))
    target = 1.8 * matrix[:, 2] - 0.7 * matrix[:, 9] + rng.normal(scale=0.03, size=32)
    parameters = {
        "n_components": 3,
        "n_resamples": 24,
        "calibration_fraction": 0.75,
        "n_variables": 5,
        "random_seed": 719,
    }
    actual = _mcuve_dispatch(matrix, target, **parameters)

    oracle_rng = np.random.default_rng(parameters["random_seed"])
    calibration_size = int(np.floor(matrix.shape[0] * parameters["calibration_fraction"]))
    oracle_indices = np.empty((parameters["n_resamples"], calibration_size), dtype=np.int64)
    coefficients = np.empty((parameters["n_resamples"], matrix.shape[1]), dtype=np.float64)
    for resample in range(parameters["n_resamples"]):
        selected = oracle_rng.choice(matrix.shape[0], size=calibration_size, replace=False)
        oracle_indices[resample] = selected
        model = PLSRegression(n_components=parameters["n_components"], scale=False)
        model.fit(matrix[selected], target[selected])
        coefficients[resample] = np.asarray(model.coef_).reshape(-1)
    means = np.mean(coefficients, axis=0)
    standard_deviations = np.std(coefficients, axis=0, ddof=1)
    floor = _coefficient_sd_floor(means, standard_deviations)
    stability = np.abs(means / np.maximum(standard_deviations, floor))
    ranking = np.lexsort((np.arange(matrix.shape[1]), -stability))
    mask = np.zeros(matrix.shape[1], dtype=bool)
    mask[ranking[: parameters["n_variables"]]] = True

    np.testing.assert_array_equal(actual["calibration_indices"], oracle_indices)
    # Single-response SIMPLS and NIPALS are algebraically equivalent; allow
    # only floating-point ordering noise between the independent authorities.
    np.testing.assert_allclose(actual["coefficient_mean"], means, rtol=1e-13, atol=1e-14)
    np.testing.assert_allclose(actual["coefficient_sd"], standard_deviations, rtol=1e-13, atol=1e-14)
    np.testing.assert_allclose(actual["stability_scores"], stability, rtol=1e-12, atol=1e-12)
    np.testing.assert_array_equal(actual["ranked_indices"], ranking)
    np.testing.assert_array_equal(actual["feature_mask"], mask)


def test_mcuve_seed_reproduces_the_complete_decision_record() -> None:
    rng = np.random.default_rng(203)
    matrix = rng.normal(size=(36, 15))
    target = matrix[:, 1] - matrix[:, 8]
    parameters = {
        "n_components": 2,
        "n_resamples": 20,
        "calibration_fraction": 0.8,
        "n_variables": 6,
        "random_seed": 53,
    }
    assert _mcuve_dispatch(matrix, target, **parameters) == _mcuve_dispatch(matrix, target, **parameters)


def test_mcuve_rejects_an_unsupported_component_request_instead_of_narrowing_it() -> None:
    matrix = np.arange(24.0).reshape(6, 4)
    target = np.linspace(0.0, 1.0, 6)

    with pytest.raises(ValueError, match="requested 4 PLS components.*supports at most 3"):
        _mcuve_dispatch(
            matrix,
            target,
            n_components=4,
            n_resamples=20,
            calibration_fraction=0.75,
            n_variables=2,
            random_seed=42,
        )


def test_mcuve_coefficient_stability_is_invariant_to_equivalent_X_units() -> None:
    rng = np.random.default_rng(216)
    matrix = rng.normal(size=(36, 12))
    target = 1.8 * matrix[:, 2] - 0.7 * matrix[:, 9] + rng.normal(scale=0.03, size=36)
    parameters = {
        "n_components": 3,
        "n_resamples": 24,
        "calibration_fraction": 0.75,
        "n_variables": 5,
        "random_seed": 719,
    }

    baseline = _mcuve_dispatch(matrix, target, **parameters)
    converted = _mcuve_dispatch(matrix * 1.0e-6, target, **parameters)

    np.testing.assert_array_equal(converted["calibration_indices"], baseline["calibration_indices"])
    np.testing.assert_array_equal(converted["ranked_indices"], baseline["ranked_indices"])
    np.testing.assert_array_equal(converted["feature_mask"], baseline["feature_mask"])
    np.testing.assert_allclose(converted["stability_scores"], baseline["stability_scores"], rtol=2e-10, atol=0.0)
    assert converted["stability_sd_floor"] == pytest.approx(
        baseline["stability_sd_floor"] * 1.0e6,
        rel=2e-10,
    )


def test_mcuve_requires_target_only_during_fit(
    mcuve_data: tuple[SherpaDataset, np.ndarray], monkeypatch: pytest.MonkeyPatch
) -> None:
    dataset, target = mcuve_data
    node = MCUVENode("mcuve", {"n_components": 2, "n_resamples": 20, "n_variables": 6})
    with pytest.raises(ValueError):
        node.fit_fitted_state(SherpaDataset(X=np.array(dataset.X), feature_axis=dataset.feature_axis), None)
    state = node.fit_fitted_state(dataset, target)
    monkeypatch.setattr(mcuve_node, "bind_y", lambda *_args, **_kwargs: pytest.fail("apply read target"))
    applied = node.apply_fitted_state(SherpaDataset(X=np.array(dataset.X), feature_axis=dataset.feature_axis), state)
    np.testing.assert_array_equal(applied.X, dataset.X[:, np.asarray(state["feature_mask"], dtype=bool)])


def test_mcuve_fit_apply_preserves_inputs_and_rejects_axis_drift(
    mcuve_data: tuple[SherpaDataset, np.ndarray],
) -> None:
    dataset, target = mcuve_data
    source = np.array(dataset.X, copy=True)
    source_axis = np.array(dataset.feature_axis.values, copy=True)
    target_source = np.array(target, copy=True)
    node = MCUVENode("mcuve", {"n_components": 2, "n_resamples": 20, "n_variables": 6})
    state = node.fit_fitted_state(dataset, target)
    node.apply_fitted_state(dataset, state)

    np.testing.assert_array_equal(dataset.X, source)
    np.testing.assert_array_equal(dataset.feature_axis.values, source_axis)
    np.testing.assert_array_equal(target, target_source)
    drifted_axis = dataset.feature_axis.model_copy(deep=True)
    drifted_axis.values = np.asarray(drifted_axis.values) + 0.25
    with pytest.raises(ValueError, match="fitted feature axis"):
        node.apply_fitted_state(SherpaDataset(X=source, feature_axis=drifted_axis), state)


@pytest.mark.asyncio
async def test_mcuve_live_and_generated_python_share_one_typed_operation(
    mcuve_data: tuple[SherpaDataset, np.ndarray],
) -> None:
    dataset, target = mcuve_data
    node = MCUVENode(
        "mcuve",
        {"n_components": 2, "n_resamples": 20, "calibration_fraction": 0.75, "n_variables": 6, "random_seed": 91},
    )
    live = await node.execute(X=dataset, y=target)
    namespace = {"dataset": dataset, "target": target, "results": {}}
    exec("\n".join(node.generate_python({"X": "dataset", "y": "target"}, indent="")), namespace)  # noqa: S102
    generated = namespace["results"]["mcuve"]

    np.testing.assert_array_equal(generated["mask"], live.outputs["mask"])
    np.testing.assert_array_equal(generated["scores"], live.outputs["scores"])
    np.testing.assert_array_equal(generated["X_selected"].X, live.outputs["X_selected"].X)


@pytest.mark.parametrize(
    "mutation",
    [
        lambda state: state.update(serializer="spectrasherpa.selection.mcuve.state/1"),
        lambda state: state["feature_mask"].__setitem__(0, not state["feature_mask"][0]),
        lambda state: state["coefficient_mean"].__setitem__(0, state["coefficient_mean"][0] + 0.5),
        lambda state: state["coefficient_sd"].__setitem__(0, state["coefficient_sd"][0] + 0.5),
        lambda state: state["stability_scores"].__setitem__(0, state["stability_scores"][0] + 0.5),
        lambda state: state["ranked_indices"].reverse(),
        lambda state: state["calibration_indices"][0].reverse(),
        lambda state: state.update(calibration_digest="0" * 64),
        lambda state: state.update(stability_sd_floor=state["stability_sd_floor"] * 2.0),
        lambda state: state.update(model_fit_count=state["model_fit_count"] - 1),
        lambda state: state.update(stability_definition="mean_only"),
        lambda state: state.update(selection_scope="predictive_performance_evidence"),
    ],
)
def test_mcuve_closed_state_rejects_mutated_or_coordinated_forgery(
    mcuve_data: tuple[SherpaDataset, np.ndarray], mutation
) -> None:
    dataset, target = mcuve_data
    state = MCUVENode(
        "mcuve", {"n_components": 2, "n_resamples": 20, "n_variables": 6, "random_seed": 19}
    ).fit_fitted_state(dataset, target)
    forged = copy.deepcopy(state)
    mutation(forged)
    with pytest.raises(ValueError):
        _validate_mcuve_state(forged)


def test_nested_cv_delegates_mcuve_to_the_canonical_dispatcher(monkeypatch: pytest.MonkeyPatch) -> None:
    rng = np.random.default_rng(304)
    matrix = rng.normal(size=(28, 9))
    target = matrix[:, 2] - matrix[:, 7]
    seen: dict[str, object] = {}

    def probe(X, y, **parameters):
        assert X is matrix
        assert y is target
        seen.update(parameters)
        mask = [False] * X.shape[1]
        mask[2] = True
        return {"feature_mask": mask}

    monkeypatch.setattr(mcuve_node, "_mcuve_dispatch", probe)
    mask = nested_cv_node._select_variables_inner(matrix, target, "mcuve", 2, 1.0, 0.0, 77)

    assert mask.tolist() == [False, False, True, False, False, False, False, False, False]
    assert seen == {
        "n_components": 2,
        "n_resamples": 30,
        "calibration_fraction": 0.8,
        "n_variables": 9,
        "random_seed": 77,
    }


def test_mcuve_fixed_workload_stays_inside_reviewed_ceiling() -> None:
    rng = np.random.default_rng(405)
    matrix = rng.normal(size=(80, 240))
    target = matrix[:, 7] - 0.6 * matrix[:, 133] + rng.normal(scale=0.05, size=80)
    with PerformanceCeiling("selection.mcuve", "80x240-20-resamples", 5.0).measure():
        result = _mcuve_dispatch(
            matrix,
            target,
            n_components=3,
            n_resamples=20,
            calibration_fraction=0.8,
            n_variables=20,
            random_seed=42,
        )

    assert sum(result["feature_mask"]) == 20
