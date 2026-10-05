"""C2k canonical SPA-MLR scientific, execution, and export proofs."""

from __future__ import annotations

import copy

import numpy as np
import pytest

import spectra_sherpa.app.services.dag.nodes  # noqa: F401 - populate built-ins
from spectra_sherpa.app.lib.sherpa_dataset import SampleAxis, SherpaDataset, SpectralAxis
from spectra_sherpa.app.services.dag.node_base import node_registry
from spectra_sherpa.app.services.dag.nodes.selection import nested_cv_node, spa_node
from spectra_sherpa.app.services.dag.nodes.selection.spa_node import (
    SPANode,
    _canonical_spa_parameters,
    _mlr_rmsecv,
    _projection_chain_from_gram,
    _spa_dispatch,
    _spa_projection_chains,
    _validate_spa_state,
)
from spectra_sherpa.execution_contract_vocabulary import LifecycleKind, ManagedOptimizationEligibility, RuntimeFamily
from tests.performance_contract import PerformanceCeiling


@pytest.fixture
def spa_data() -> tuple[SherpaDataset, np.ndarray]:
    rng = np.random.default_rng(9217)
    matrix = rng.normal(size=(42, 14))
    matrix[:, 8] = 0.98 * matrix[:, 2] + rng.normal(scale=0.02, size=matrix.shape[0])
    target = 2.2 * matrix[:, 2] - 1.4 * matrix[:, 9] + rng.normal(scale=0.05, size=matrix.shape[0])
    dataset = SherpaDataset(
        X=matrix,
        feature_axis=SpectralAxis(
            values=np.linspace(950.0, 1750.0, matrix.shape[1]),
            labels=[f"band-{index}" for index in range(matrix.shape[1])],
            units="cm-1",
        ),
        sample_axis=SampleAxis(labels=[f"sample-{index}" for index in range(matrix.shape[0])]),
        target=target,
    )
    return dataset, target


def _literal_projection_chain(matrix: np.ndarray, start: int, maximum: int) -> tuple[int, ...]:
    """Independent sample-space transcription of the Araújo projection step."""

    residuals = np.array(matrix, dtype=np.float64, copy=True)
    selected = [start]
    available = np.ones(matrix.shape[1], dtype=bool)
    available[start] = False
    tolerance = max(
        np.finfo(np.float64).eps * max(matrix.shape) * float(np.max(np.sum(np.square(matrix), axis=0))),
        float(np.nextafter(np.float64(0.0), np.float64(1.0))),
    )
    while len(selected) < maximum:
        current = residuals[:, selected[-1]]
        norm = float(current @ current)
        if norm <= tolerance:
            break
        residuals[:, available] -= np.outer(current, (current @ residuals[:, available]) / norm)
        norms = np.sum(np.square(residuals), axis=0)
        norms[~available] = -np.inf
        next_variable = int(np.argmax(norms))
        if not np.isfinite(norms[next_variable]) or norms[next_variable] <= tolerance:
            break
        selected.append(next_variable)
        available[next_variable] = False
    return tuple(selected)


def test_spa_contract_names_exact_original_authority() -> None:
    metadata = node_registry.get_metadata("selection.spa")
    contract = metadata.resolved_execution_contract()

    assert contract is not None
    assert contract.payload["operation_id"] == "selection.spa"
    assert contract.payload["runtime_family"] == RuntimeFamily.SHERPA_NATIVE.value
    assert contract.payload["lifecycle_kind"] == LifecycleKind.FITTED_TRANSFORM.value
    assert contract.payload["managed_optimization_eligibility"] == (ManagedOptimizationEligibility.LOCAL.value,)
    assert contract.payload["target_access"] == "fit_only"
    assert contract.payload["implementation_id"] == "spectrasherpa.selection.spa_mlr"
    assert contract.payload["implementation_version"] == "1.1.0"
    assert contract.payload["fitted_state_serializer"] == "spectrasherpa.selection.spa_mlr.state/3"
    assert any("10.1016/S0169-7439(01)00119-8" in item for item in contract.payload["citations"])


def test_spa_admission_is_closed_and_rejects_the_old_fixed_count_heuristic() -> None:
    node = node_registry.create_node("selection.spa", "spa", {"max_variables": 9})
    assert node.parameters == {
        "min_variables": 1,
        "max_variables": 9,
        "cv_folds": 5,
        "cv_order": "sorted_target",
        "random_seed": 42,
    }
    for invalid in (
        {"n_select": 5},
        {"start_var": 2},
        {"max_variables": 31},
        {"min_variables": 0},
        {"cv_folds": True},
        {"cv_order": "shuffle"},
        {"random_seed": -1},
    ):
        with pytest.raises(ValueError):
            _canonical_spa_parameters(invalid)


def test_spa_gram_chain_matches_literal_mean_centered_sample_space_projection() -> None:
    rng = np.random.default_rng(71)
    matrix = rng.normal(loc=3.0, scale=1.7, size=(28, 11))
    centered = matrix - np.mean(matrix, axis=0, keepdims=True)
    gram = centered.T @ centered

    for start in range(matrix.shape[1]):
        expected = _literal_projection_chain(centered, start, 7)
        actual = _projection_chain_from_gram(gram, start_variable=start, max_variables=7)
        assert actual == expected


def test_spa_constructs_one_chain_for_every_nonconstant_start_not_a_fifty_start_sample() -> None:
    rng = np.random.default_rng(82)
    matrix = rng.normal(size=(30, 67))
    matrix[:, 13] = 4.0
    chains = _spa_projection_chains(matrix, max_variables=4)

    assert [chain[0] for chain in chains] == [index for index in range(67) if index != 13]
    assert len(chains) == 66


def test_spa_projection_and_selected_subset_are_invariant_to_equivalent_X_units() -> None:
    rng = np.random.default_rng(86)
    matrix = rng.normal(size=(36, 12))
    matrix[:, 11] = 7.0
    target = 1.8 * matrix[:, 2] - 0.7 * matrix[:, 9] + rng.normal(scale=0.03, size=36)
    parameters = {
        "min_variables": 1,
        "max_variables": 5,
        "cv_folds": 3,
        "cv_order": "sorted_target",
        "random_seed": 42,
    }

    baseline = _spa_dispatch(matrix, target, **parameters)
    for scale in (1.0e-8, 1.0e8):
        converted = _spa_dispatch(matrix * scale, target, **parameters)
        assert converted["projection_chains"] == baseline["projection_chains"]
        assert converted["selected_indices"] == baseline["selected_indices"]
        assert converted["feature_mask"] == baseline["feature_mask"]
        assert all(chain[0] != 11 for chain in converted["projection_chains"])


def test_spa_mlr_rmsecv_matches_an_independent_fold_calculation() -> None:
    rng = np.random.default_rng(93)
    matrix = rng.normal(size=(35, 8))
    target = 1.5 * matrix[:, 1] - 0.8 * matrix[:, 6] + rng.normal(scale=0.04, size=35)
    assignments = np.arange(35, dtype=np.int64) % 5
    indices = (1, 6)
    predictions = np.empty(target.shape[0], dtype=np.float64)
    for fold in range(5):
        train = assignments != fold
        validate = ~train
        train_design = np.column_stack((np.ones(int(train.sum())), matrix[train][:, indices]))
        coefficients = np.linalg.lstsq(train_design, target[train], rcond=None)[0]
        validation_design = np.column_stack((np.ones(int(validate.sum())), matrix[validate][:, indices]))
        predictions[validate] = validation_design @ coefficients
    expected = float(np.sqrt(np.mean(np.square(target - predictions))))

    assert _mlr_rmsecv(matrix, target, indices, assignments) == pytest.approx(expected, abs=1e-14)


def test_spa_dispatch_uses_one_shared_fold_plan_and_declared_tie_break(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    matrix = np.arange(72.0).reshape(12, 6)
    target = np.linspace(0.0, 1.0, 12)
    monkeypatch.setattr(spa_node, "_spa_projection_chains", lambda *_args, **_kwargs: ((2, 4, 1), (0, 5, 3)))
    seen_assignments: list[np.ndarray] = []

    def tied_score(_matrix, _target, indices, assignments):
        seen_assignments.append(np.array(assignments, copy=True))
        return 1.0 if len(indices) in {1, 2} else 2.0

    monkeypatch.setattr(spa_node, "_mlr_rmsecv", tied_score)
    result = _spa_dispatch(
        matrix,
        target,
        min_variables=1,
        max_variables=3,
        cv_folds=3,
        cv_order="seeded_random",
        random_seed=17,
    )

    assert result["selected_indices"] == [0]
    assert all(np.array_equal(seen_assignments[0], item) for item in seen_assignments[1:])


def test_spa_requires_a_quantitative_target_but_application_reads_no_target(
    spa_data: tuple[SherpaDataset, np.ndarray], monkeypatch: pytest.MonkeyPatch
) -> None:
    dataset, target = spa_data
    node = SPANode("spa", {"max_variables": 5, "cv_folds": 3})
    with pytest.raises(ValueError):
        node.fit_fitted_state(
            SherpaDataset(X=np.array(dataset.X), feature_axis=dataset.feature_axis),
            None,
        )
    state = node.fit_fitted_state(dataset, target)
    monkeypatch.setattr(spa_node, "bind_y", lambda *_args, **_kwargs: pytest.fail("apply read target"))
    applied = node.apply_fitted_state(SherpaDataset(X=np.array(dataset.X), feature_axis=dataset.feature_axis), state)
    np.testing.assert_array_equal(applied.X, dataset.X[:, np.asarray(state["feature_mask"], dtype=bool)])


def test_spa_fit_apply_preserves_inputs_and_rejects_axis_drift(spa_data: tuple[SherpaDataset, np.ndarray]) -> None:
    dataset, target = spa_data
    source = np.array(dataset.X, copy=True)
    target_source = np.array(target, copy=True)
    node = SPANode("spa", {"max_variables": 5, "cv_folds": 3})
    state = node.fit_fitted_state(dataset, target)
    node.apply_fitted_state(dataset, state)

    np.testing.assert_array_equal(dataset.X, source)
    np.testing.assert_array_equal(target, target_source)
    drifted_axis = dataset.feature_axis.model_copy(deep=True)
    drifted_axis.values = np.asarray(drifted_axis.values) + 0.5
    with pytest.raises(ValueError, match="fitted feature axis"):
        node.apply_fitted_state(SherpaDataset(X=source, feature_axis=drifted_axis), state)


@pytest.mark.asyncio
async def test_spa_live_and_generated_python_share_the_same_typed_operation(
    spa_data: tuple[SherpaDataset, np.ndarray],
) -> None:
    dataset, target = spa_data
    node = SPANode("spa", {"max_variables": 5, "cv_folds": 3, "random_seed": 8})
    live = await node.execute(X=dataset, y=target)
    namespace = {"dataset": dataset, "target": target, "results": {}}
    exec("\n".join(node.generate_python({"X": "dataset", "y": "target"}, indent="")), namespace)  # noqa: S102
    generated = namespace["results"]["spa"]

    np.testing.assert_array_equal(generated["mask"], live.outputs["mask"])
    np.testing.assert_array_equal(generated["X_selected"].X, live.outputs["X_selected"].X)
    np.testing.assert_array_equal(generated["scores"], live.outputs["scores"])


@pytest.mark.parametrize(
    "mutation",
    [
        lambda state: state.update(serializer="spectrasherpa.selection.spa_mlr.state/1"),
        lambda state: state["projection_chains"].reverse(),
        lambda state: state["projection_chains"][1].__setitem__(0, state["projection_chains"][0][0]),
        lambda state: state.update(best_start=True),
        lambda state: state.update(best_size=True),
        lambda state: state.update(best_rmsecv=True),
        lambda state: state["feature_mask"].__setitem__(0, not state["feature_mask"][0]),
        lambda state: state.update(split_digest="0" * 64),
        lambda state: state.update(model_fit_budget=state["model_fit_budget"] + 1),
        lambda state: state.update(projection_preprocessing="none"),
        lambda state: state.update(selection_scope="predictive_performance_evidence"),
    ],
)
def test_spa_closed_state_rejects_mutated_or_coordinated_forgery(
    spa_data: tuple[SherpaDataset, np.ndarray], mutation
) -> None:
    dataset, target = spa_data
    state = SPANode("spa", {"max_variables": 5, "cv_folds": 3}).fit_fitted_state(dataset, target)
    forged = copy.deepcopy(state)
    mutation(forged)
    with pytest.raises(ValueError):
        _validate_spa_state(forged)


def test_nested_cv_delegates_spa_to_the_canonical_dispatcher(monkeypatch: pytest.MonkeyPatch) -> None:
    rng = np.random.default_rng(104)
    matrix = rng.normal(size=(24, 9))
    target = matrix[:, 2] - matrix[:, 7]
    seen: dict[str, object] = {}

    def probe(X, y, **parameters):
        seen.update(parameters)
        assert X is matrix
        assert y is target
        mask = [False] * X.shape[1]
        mask[2] = True
        return {"feature_mask": mask}

    monkeypatch.setattr(spa_node, "_spa_dispatch", probe)
    mask = nested_cv_node._select_variables_inner(matrix, target, "spa", 2, 1.0, 0.01, 37)

    assert np.flatnonzero(mask).tolist() == [2]
    assert seen == {
        "min_variables": 1,
        "max_variables": 9,
        "cv_folds": 3,
        "cv_order": "seeded_random",
        "random_seed": 37,
    }


def test_spa_fixed_workload_completes_below_regression_ceiling() -> None:
    rng = np.random.default_rng(115)
    matrix = rng.normal(size=(60, 48))
    target = matrix[:, 4] - 0.7 * matrix[:, 31] + rng.normal(scale=0.05, size=60)
    with PerformanceCeiling("selection.spa", "60x48-six-variables", 5.0).measure():
        result = _spa_dispatch(
            matrix,
            target,
            min_variables=1,
            max_variables=6,
            cv_folds=3,
            cv_order="sorted_target",
            random_seed=42,
        )

    assert result["best_rmsecv"] >= 0
