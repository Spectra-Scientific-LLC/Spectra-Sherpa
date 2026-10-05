"""Scientific and execution-contract tests for canonical fitted OSC."""

from __future__ import annotations

import asyncio
import json
import multiprocessing
import os
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np
import pytest

import spectra_sherpa.app.services.dag.nodes.preprocessing  # noqa: F401
from spectra_sherpa.app.lib.axes import FeatureAxis
from spectra_sherpa.app.lib.sherpa_dataset import SherpaDataset
from spectra_sherpa.app.services.dag.executor_pool import WorkerExecutionContext, _run_node_in_worker
from spectra_sherpa.app.services.dag.executor_types import WorkflowNode
from spectra_sherpa.app.services.dag.fold_graph_executor import _fit_fold_transform_state
from spectra_sherpa.app.services.dag.fold_lifecycle import FoldLifecycleContext, FoldLifecycleError, FoldPartition
from spectra_sherpa.app.services.dag.node_base import node_registry
from spectra_sherpa.app.services.dag.nodes.preprocessing.osc_node import (
    OSCNode,
    _apply_osc_state,
    _fit_osc_state,
    _osc_dispatch,
)
from spectra_sherpa.app.services.dag.spectral_capability import SpectralDatasetCapability
from spectra_sherpa.app.services.dag.stable_execution_contract import ensure_registered_execution_contract
from spectra_sherpa.app.services.dag.validation_graph import admit_validation_graph
from spectra_sherpa.app.services.model_application import _prepare_X_for_artifact, validate_feature_contract
from spectra_sherpa.app.types import type_registry
from spectra_sherpa.core.execution_runtime import ExecutionRuntime
from spectra_sherpa.execution_contract_vocabulary import LifecycleKind, RuntimeFamily, WorkerCapability
from tests.performance_contract import PerformanceCeiling


@pytest.fixture(autouse=True)
def _load_type_registry() -> None:
    if not type_registry.is_loaded:
        type_registry.load(Path(__file__).resolve().parents[1] / "src" / "spectra_sherpa" / "app" / "types")


AXIS = np.array([910.0, 945.0, 990.0, 1040.0, 1110.0, 1195.0, 1300.0, 1430.0])
MEAN = np.array([3.0, 2.0, 4.0, 1.5, 3.5, 2.5, 4.5, 1.0])
TARGET_LOADING = np.array([1.0, 0.2, -0.4, 0.8, -0.3, 0.6, 0.1, -0.5])
TARGET_LOADING = TARGET_LOADING / np.linalg.norm(TARGET_LOADING)
NUISANCE_LOADING = np.array([-0.2, 1.0, 0.7, -0.5, 0.4, -0.8, 0.9, 0.3])
NUISANCE_LOADING = NUISANCE_LOADING - TARGET_LOADING * np.dot(NUISANCE_LOADING, TARGET_LOADING)
NUISANCE_LOADING = NUISANCE_LOADING / np.linalg.norm(NUISANCE_LOADING)


def _scientific_rows(samples: int = 24) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    target = np.linspace(-1.5, 1.5, samples, dtype=np.float64)
    nuisance = np.sin(np.arange(samples, dtype=np.float64) * 1.7)
    secondary = np.cos(np.arange(samples, dtype=np.float64) * 0.43)
    noise_loading = np.array([0.1, -0.2, 0.3, -0.1, 0.2, -0.3, 0.1, -0.2])
    noise_loading = noise_loading - TARGET_LOADING * np.dot(noise_loading, TARGET_LOADING)
    rows = (
        MEAN
        + 2.5 * target[:, None] * TARGET_LOADING
        + 5.0 * nuisance[:, None] * NUISANCE_LOADING
        + 0.02 * secondary[:, None] * noise_loading
    )
    return rows, target, nuisance


def _dataset(
    rows: np.ndarray,
    *,
    target: np.ndarray | None = None,
    axis: np.ndarray | None = AXIS,
) -> SherpaDataset:
    feature_axis = None if axis is None else FeatureAxis(values=np.asarray(axis), units="cm-1")
    return SherpaDataset(
        X=np.asarray(rows, dtype=np.float64),
        target=target,
        feature_axis=feature_axis,
        data_role="X_spectra",
    )


def _fitted_state() -> dict[str, object]:
    rows, target, _ = _scientific_rows()
    return _fit_osc_state(
        rows,
        target,
        n_components=1,
        feature_axis_values=AXIS,
        feature_axis_units="cm-1",
    )


def _literal_fearn_reference(
    rows: np.ndarray,
    target: np.ndarray,
    *,
    n_components: int,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Literal matrix-equation reference from Fearn (2000), equations 5-8."""

    centered = rows - np.mean(rows, axis=0, dtype=np.float64)
    centered_target = target - np.mean(target, axis=0, dtype=np.float64)
    if centered_target.ndim == 1:
        centered_target = centered_target.reshape(-1, 1)
    cross = centered.T @ centered_target
    projection = np.eye(rows.shape[1]) - cross @ np.linalg.pinv(cross.T @ cross) @ cross.T
    candidate = centered @ projection
    _, _, right = np.linalg.svd(candidate, full_matrices=False)
    weights = right[:n_components]
    for index, weight in enumerate(weights):
        pivot = int(np.argmax(np.abs(weight)))
        if weight[pivot] < 0.0:
            weights[index] *= -1.0
    scores = centered @ weights.T
    loadings = (centered.T @ scores @ np.linalg.inv(scores.T @ scores)).T
    corrected = centered - scores @ loadings + np.mean(rows, axis=0, dtype=np.float64)
    return weights, loadings, corrected


@pytest.mark.parametrize("n_components", [1, 2])
def test_osc_matches_fearns_published_direct_matrix_equations(n_components: int) -> None:
    rows, target, _ = _scientific_rows()
    if n_components == 2:
        second = np.cos(np.arange(rows.shape[0], dtype=np.float64) * 0.71)
        second -= (
            np.column_stack((np.ones(target.size), target))
            @ np.linalg.lstsq(np.column_stack((np.ones(target.size), target)), second, rcond=None)[0]
        )
        rows = rows + 0.8 * second[:, None] * np.roll(NUISANCE_LOADING, 1)
    state = _fit_osc_state(
        rows,
        target,
        n_components=n_components,
        feature_axis_values=AXIS,
        feature_axis_units="cm-1",
    )
    expected_weights, expected_loadings, expected = _literal_fearn_reference(
        rows,
        target,
        n_components=n_components,
    )

    np.testing.assert_allclose(state["orthogonal_weights"], expected_weights, rtol=1e-10, atol=1e-10)
    np.testing.assert_allclose(state["deflation_loadings"], expected_loadings, rtol=1e-10, atol=1e-10)
    np.testing.assert_allclose(
        _apply_osc_state(rows, state, feature_axis_values=AXIS, feature_axis_units="cm-1"),
        expected,
        rtol=1e-10,
        atol=1e-10,
    )


def test_osc_removes_dominant_target_orthogonal_variation_and_preserves_target_signal() -> None:
    rows, target, _ = _scientific_rows()
    corrected = _apply_osc_state(
        rows,
        _fitted_state(),
        feature_axis_values=AXIS,
        feature_axis_units="cm-1",
    )

    centered_before = rows - rows.mean(axis=0)
    centered_after = corrected - corrected.mean(axis=0)
    nuisance_before = np.linalg.norm(centered_before @ NUISANCE_LOADING)
    nuisance_after = np.linalg.norm(centered_after @ NUISANCE_LOADING)
    target_before = centered_before @ TARGET_LOADING
    target_after = centered_after @ TARGET_LOADING

    assert nuisance_after < nuisance_before * 0.01
    np.testing.assert_allclose(target_after, target_before, rtol=1e-10, atol=1e-10)
    assert abs(np.corrcoef(target, target_after)[0, 1]) > 0.999


def test_osc_preserves_target_covariance_when_analyte_and_nuisance_share_features() -> None:
    """The removed score—not merely a residual loading—must be Y-orthogonal."""

    target = np.linspace(-2.0, 2.0, 31, dtype=np.float64)
    nuisance = np.sin(np.arange(target.size, dtype=np.float64) * 1.37)
    nuisance = nuisance - target * float(target @ nuisance) / float(target @ target)
    nuisance = nuisance * (np.linalg.norm(target) / np.linalg.norm(nuisance))
    rows = np.column_stack((3.0 * target + 8.0 * nuisance, 2.0 * target - 5.0 * nuisance))
    axis = np.array([1000.0, 1100.0])
    state = _fit_osc_state(
        rows,
        target,
        n_components=1,
        feature_axis_values=axis,
        feature_axis_units="cm-1",
    )
    corrected = _apply_osc_state(
        rows,
        state,
        feature_axis_values=axis,
        feature_axis_units="cm-1",
    )

    centered_target = target - np.mean(target)
    before = centered_target @ (rows - np.mean(rows, axis=0))
    after = centered_target @ (corrected - np.mean(corrected, axis=0))
    np.testing.assert_allclose(after, before, rtol=1.0e-10, atol=1.0e-10)
    assert np.linalg.norm(corrected - np.mean(corrected, axis=0)) < np.linalg.norm(rows - np.mean(rows, axis=0))
    assert float(state["training_target_covariance_relative_error"]) <= 1.0e-10


def test_osc_accepts_spectra_whose_entire_variation_is_target_orthogonal() -> None:
    """True zero covariance is signal-free, not a rank or invariant failure."""

    target = np.linspace(-2.0, 2.0, 31, dtype=np.float64)
    target_basis = np.column_stack((np.ones(target.size, dtype=np.float64), target))
    raw_scores = np.column_stack(
        (
            np.sin(np.arange(target.size, dtype=np.float64) * 0.37),
            np.cos(np.arange(target.size, dtype=np.float64) * 0.71),
            np.sin(np.arange(target.size, dtype=np.float64) * 1.13),
        )
    )
    orthogonal_scores = raw_scores - target_basis @ np.linalg.lstsq(target_basis, raw_scores, rcond=None)[0]
    left_vectors, _, _ = np.linalg.svd(orthogonal_scores, full_matrices=False)
    rows = left_vectors @ np.diag([5.0, 2.0, 0.5])
    axis = np.array([1000.0, 1100.0, 1200.0])

    state = _fit_osc_state(
        rows,
        target,
        n_components=1,
        feature_axis_values=axis,
        feature_axis_units="cm-1",
    )
    corrected = _apply_osc_state(
        rows,
        state,
        feature_axis_values=axis,
        feature_axis_units="cm-1",
    )

    centered_target = target - np.mean(target)
    np.testing.assert_allclose(centered_target @ rows, 0.0, atol=1.0e-12)
    np.testing.assert_allclose(centered_target @ corrected, 0.0, atol=1.0e-12)
    assert np.linalg.norm(corrected) < np.linalg.norm(rows) * 0.5
    assert float(state["training_target_covariance_relative_error"]) <= 1.0e-10


def test_osc_two_component_sequence_replays_both_deflations() -> None:
    target = np.linspace(-2.0, 2.0, 41, dtype=np.float64)
    sample_basis = np.column_stack((np.ones(target.size, dtype=np.float64), target))
    nuisance_one = np.sin(np.arange(target.size, dtype=np.float64) * 0.47)
    nuisance_one = nuisance_one - sample_basis @ np.linalg.lstsq(sample_basis, nuisance_one, rcond=None)[0]
    nuisance_two = np.cos(np.arange(target.size, dtype=np.float64) * 0.83)
    nuisance_two = nuisance_two - sample_basis @ np.linalg.lstsq(sample_basis, nuisance_two, rcond=None)[0]
    nuisance_two = nuisance_two - nuisance_one * float(nuisance_one @ nuisance_two) / float(nuisance_one @ nuisance_one)
    nuisance_one = nuisance_one / np.linalg.norm(nuisance_one)
    nuisance_two = nuisance_two / np.linalg.norm(nuisance_two)
    feature_basis = np.linalg.qr(
        np.array(
            [
                [1.0, 0.3, -0.4],
                [0.2, 1.0, 0.5],
                [-0.6, 0.4, 1.0],
                [0.5, -0.7, 0.2],
            ]
        )
    )[0]
    rows = (
        2.5 * target[:, None] * feature_basis[:, 0]
        + 8.0 * nuisance_one[:, None] * feature_basis[:, 1]
        + 4.0 * nuisance_two[:, None] * feature_basis[:, 2]
    )
    axis = np.array([1000.0, 1100.0, 1200.0, 1300.0])

    state = _fit_osc_state(
        rows,
        target,
        n_components=2,
        feature_axis_values=axis,
        feature_axis_units="cm-1",
    )
    corrected = _apply_osc_state(
        rows,
        state,
        feature_axis_values=axis,
        feature_axis_units="cm-1",
    )

    assert len(state["orthogonal_weights"]) == 2
    assert len(state["deflation_loadings"]) == 2
    singular_values = np.asarray(state["removed_score_singular_values"])
    assert singular_values[0] > singular_values[1] > 0.0
    centered_target = target - np.mean(target)
    np.testing.assert_allclose(centered_target @ corrected, centered_target @ rows, rtol=1.0e-10, atol=1.0e-10)
    assert np.linalg.norm(corrected @ feature_basis[:, 1:3]) < 1.0e-10


def test_osc_preserves_each_response_in_a_multi_target_matrix() -> None:
    samples = 37
    target_one = np.linspace(-2.0, 2.0, samples, dtype=np.float64)
    target_two = np.cos(np.linspace(0.0, 2.0 * np.pi, samples, dtype=np.float64))
    targets = np.column_stack((target_one, target_two))
    sample_basis = np.column_stack((np.ones(samples, dtype=np.float64), targets))
    nuisance = np.sin(np.arange(samples, dtype=np.float64) * 0.61)
    nuisance = nuisance - sample_basis @ np.linalg.lstsq(sample_basis, nuisance, rcond=None)[0]
    nuisance = nuisance / np.linalg.norm(nuisance)
    rows = np.column_stack(
        (
            2.0 * target_one + 7.0 * nuisance,
            -1.5 * target_one + 0.7 * target_two - 4.0 * nuisance,
            2.2 * target_two + 3.0 * nuisance,
            0.6 * target_one - 0.8 * target_two + 5.0 * nuisance,
        )
    )
    axis = np.array([1000.0, 1100.0, 1200.0, 1300.0])

    state = _fit_osc_state(
        rows,
        targets,
        n_components=1,
        feature_axis_values=axis,
        feature_axis_units="cm-1",
    )
    corrected = _apply_osc_state(
        rows,
        state,
        feature_axis_values=axis,
        feature_axis_units="cm-1",
    )

    centered_targets = targets - np.mean(targets, axis=0)
    np.testing.assert_allclose(
        centered_targets.T @ corrected,
        centered_targets.T @ rows,
        rtol=1.0e-10,
        atol=1.0e-10,
    )
    assert state["target_count"] == 2
    assert float(state["training_target_covariance_relative_error"]) <= 1.0e-10


def test_osc_rank_admission_and_frozen_result_are_invariant_to_input_scale() -> None:
    rows, target, _ = _scientific_rows()
    state = _fitted_state()
    scale = 1.0e-9
    scaled_state = _fit_osc_state(
        rows * scale,
        target,
        n_components=1,
        feature_axis_values=AXIS,
        feature_axis_units="cm-1",
    )

    np.testing.assert_allclose(scaled_state["orthogonal_weights"], state["orthogonal_weights"], rtol=1e-10, atol=1e-10)
    np.testing.assert_allclose(scaled_state["deflation_loadings"], state["deflation_loadings"], rtol=1e-10, atol=1e-10)
    corrected = _apply_osc_state(rows, state, feature_axis_values=AXIS, feature_axis_units="cm-1")
    scaled_corrected = _apply_osc_state(
        rows * scale,
        scaled_state,
        feature_axis_values=AXIS,
        feature_axis_units="cm-1",
    )
    np.testing.assert_allclose(scaled_corrected, corrected * scale, rtol=1e-10, atol=1e-18)


def test_osc_fails_closed_when_the_dominant_orthogonal_score_is_degenerate() -> None:
    target = np.linspace(-1.0, 1.0, 21, dtype=np.float64)
    target_basis = np.column_stack((np.ones(target.size, dtype=np.float64), target))
    nuisance_one = np.sin(np.arange(target.size, dtype=np.float64) * 0.71)
    nuisance_one = nuisance_one - target_basis @ np.linalg.lstsq(target_basis, nuisance_one, rcond=None)[0]
    nuisance_two = np.cos(np.arange(target.size, dtype=np.float64) * 1.13)
    nuisance_two = nuisance_two - target_basis @ np.linalg.lstsq(target_basis, nuisance_two, rcond=None)[0]
    nuisance_two = nuisance_two - nuisance_one * float(nuisance_one @ nuisance_two) / float(nuisance_one @ nuisance_one)
    nuisance_one = nuisance_one / np.linalg.norm(nuisance_one)
    nuisance_two = nuisance_two / np.linalg.norm(nuisance_two)
    rows = np.column_stack((target, nuisance_one, nuisance_two))

    with pytest.raises(ValueError, match="not uniquely resolved"):
        _fit_osc_state(
            rows,
            target,
            n_components=1,
            feature_axis_values=np.array([1000.0, 1100.0, 1200.0]),
            feature_axis_units="cm-1",
        )


def test_fit_state_is_training_only_and_application_requires_no_target() -> None:
    rows, target, _ = _scientific_rows()
    node = OSCNode("osc", {"n_components": 1})
    training = _dataset(rows[:16], target=target[:16])
    held_out = _dataset(rows[16:])

    state = node.fit_fitted_state(training, target[:16])
    corrected = node.apply_fitted_state(held_out, state)

    assert state["x_mean"] == np.mean(rows[:16], axis=0).tolist()
    assert corrected.target is None
    assert corrected.shape == held_out.shape


def test_fold_lifecycle_grants_training_target_only_to_the_fitted_transform() -> None:
    rows, target, _ = _scientific_rows()
    dataset = _dataset(rows, target=target)
    capability = SpectralDatasetCapability.from_dataset(dataset, custody_id="osc-public-fixture")
    partition = FoldPartition.create(range(16), range(16, 24), sample_count=24)
    contract = ensure_registered_execution_contract(node_registry.get_metadata("preprocess.osc"))
    context = FoldLifecycleContext(contract, capability, partition)
    node = context.fresh_node("osc", {"n_components": 1})

    state = _fit_fold_transform_state(node, context, context.dataset("train"), node_id="osc")

    assert state["x_mean"] == np.mean(rows[:16], axis=0).tolist()
    with pytest.raises(FoldLifecycleError, match="fit-only target access"):
        context.target("test")


def test_workbench_execution_and_generated_python_use_the_same_authority() -> None:
    rows, target, _ = _scientific_rows()
    dataset = _dataset(rows, target=target)
    node = OSCNode("osc", {"n_components": 1})
    live_result = asyncio.run(node.execute(default=dataset))
    live = live_result.outputs["default"]

    source = "\n".join(node.generate_python({"default": "application_data"}, use_scp=False))
    exported_source = f"def exported(application_data):\n    results = {{}}\n{source}\n    return results['osc']\n"
    namespace: dict[str, object] = {}
    exec(compile(exported_source, "<preprocess.osc export>", "exec"), namespace)
    generated = namespace["exported"](dataset)  # type: ignore[operator]

    assert "osc_node import OSCNode" in source
    assert "apply_fitted_state(application_data, _state)" in source
    assert "np.linalg" not in source
    np.testing.assert_allclose(generated.X, live.X, rtol=1e-12, atol=1e-12)
    assert generated.data_role == live.data_role == dataset.data_role
    for actual_axis in (generated.get_feature_axis(), live.get_feature_axis()):
        assert actual_axis is not None
        assert actual_axis.units == "cm-1"
        np.testing.assert_array_equal(actual_axis.values, AXIS)
    assert live_result.diagnostics == {
        "algorithm": "fearn-direct-orthogonal-signal-correction",
        "n_components": 1,
        "target_count": 1,
        "training_centered_variance_removed_percent": live.provenance.to_list()[-1]["parameters"][
            "variance_removed_percent"
        ],
        "training_target_covariance_relative_error": live.provenance.to_list()[-1]["parameters"]["transform_state"][
            "training_target_covariance_relative_error"
        ],
        "fitted_state_serializer": "spectra.osc-fearn-direct-json.v1",
    }


def test_one_shot_dispatch_accepts_an_explicit_target() -> None:
    rows, target, _ = _scientific_rows()
    expected = _apply_osc_state(rows, _fitted_state(), feature_axis_values=AXIS, feature_axis_units="cm-1")
    actual = _osc_dispatch(_dataset(rows), target, n_components=1)
    np.testing.assert_allclose(actual, expected, rtol=1e-12, atol=1e-12)


def test_artifact_application_replays_the_exact_fitted_projection() -> None:
    rows, target, _ = _scientific_rows()
    execution = asyncio.run(OSCNode("osc", {"n_components": 1}).execute(default=_dataset(rows, target=target)))
    parameters = execution.outputs["default"].provenance.to_list()[-1]["parameters"]
    assert isinstance(parameters, dict)
    chain = [{"op_id": "preprocess.osc", "parameters": parameters}]

    replayed, _, _, warnings = _prepare_X_for_artifact(
        rows,
        None,
        {"preprocessing_chain": chain},
        scope="all",
        source_dataset=_dataset(rows),
    )

    state = parameters["transform_state"]
    assert isinstance(state, dict)
    np.testing.assert_allclose(
        replayed,
        _apply_osc_state(rows, state, feature_axis_values=AXIS, feature_axis_units="cm-1"),
        rtol=1e-12,
        atol=1e-12,
    )
    assert warnings == []


def test_artifact_replay_requires_the_exact_full_fitted_axis() -> None:
    rows, target, _ = _scientific_rows()
    execution = asyncio.run(OSCNode("osc", {"n_components": 1}).execute(default=_dataset(rows, target=target)))
    parameters = execution.outputs["default"].provenance.to_list()[-1]["parameters"]
    assert isinstance(parameters, dict)
    chain = [{"op_id": "preprocess.osc", "parameters": parameters}]
    drifted_axis = AXIS.copy()
    drifted_axis[-1] += 5.0e-7
    source = _dataset(rows, axis=drifted_axis)
    manifest = {
        "n_features": AXIS.size,
        "feature_axis": AXIS.tolist(),
        "feature_axis_units": "cm-1",
        "preprocessing_chain": chain,
    }

    validate_feature_contract(rows, source, manifest)
    with pytest.raises(ValueError, match="feature axis differs"):
        _prepare_X_for_artifact(rows, None, manifest, scope="all", source_dataset=source)


@pytest.mark.parametrize(
    "field, value, message",
    [
        ("n_components", True, "component count"),
        ("feature_count", 8.0, "feature count"),
        ("target_count", False, "target count"),
        ("feature_axis_values", tuple(AXIS.tolist()), "feature axis"),
        ("x_mean", MEAN.astype(str).tolist(), "X mean"),
        ("orthogonal_weights", [NUISANCE_LOADING.astype(str).tolist()], "orthogonal weights"),
        ("deflation_loadings", [NUISANCE_LOADING.astype(str).tolist()], "deflation loadings"),
        ("removed_score_singular_values", ["1.0"], "removed-score singular values"),
        ("training_target_covariance_relative_error", 0, "target-covariance invariant"),
        ("training_centered_variance_removed_percent", 0, "training variance diagnostic"),
    ],
)
def test_fitted_state_accepts_only_its_canonical_json_representation(
    field: str,
    value: object,
    message: str,
) -> None:
    state = _fitted_state()
    state[field] = value
    with pytest.raises(ValueError, match=message):
        _apply_osc_state(rows := _scientific_rows()[0], state, feature_axis_values=AXIS, feature_axis_units="cm-1")
    assert rows.shape == (24, 8)


def test_fitted_state_has_one_lossless_json_round_trip() -> None:
    state = _fitted_state()
    round_tripped = json.loads(json.dumps(state, allow_nan=False))
    rows, _, _ = _scientific_rows()

    assert round_tripped == state
    np.testing.assert_allclose(
        _apply_osc_state(rows, round_tripped, feature_axis_values=AXIS, feature_axis_units="cm-1"),
        _apply_osc_state(rows, state, feature_axis_values=AXIS, feature_axis_units="cm-1"),
        rtol=0.0,
        atol=0.0,
    )


def test_fitted_state_rejects_cross_component_projection_corruption() -> None:
    rows, target, _ = _scientific_rows()
    nuisance_two = np.cos(np.arange(rows.shape[0], dtype=np.float64) * 0.71)
    nuisance_two -= (
        np.column_stack((np.ones(target.size), target))
        @ np.linalg.lstsq(np.column_stack((np.ones(target.size), target)), nuisance_two, rcond=None)[0]
    )
    rows = rows + 0.8 * nuisance_two[:, None] * np.roll(NUISANCE_LOADING, 1)
    state = _fit_osc_state(
        rows,
        target,
        n_components=2,
        feature_axis_values=AXIS,
        feature_axis_units="cm-1",
    )
    weights = np.asarray(state["orthogonal_weights"], dtype=np.float64)
    loadings = np.asarray(state["deflation_loadings"], dtype=np.float64)
    loadings[0] += 0.1 * weights[1]
    state["deflation_loadings"] = loadings.tolist()

    with pytest.raises(ValueError, match="biorthogonal projection"):
        _apply_osc_state(rows, state, feature_axis_values=AXIS, feature_axis_units="cm-1")


def test_fit_and_apply_fail_closed_on_scientifically_invalid_inputs() -> None:
    rows, target, _ = _scientific_rows()
    with pytest.raises(ValueError, match="non-constant target"):
        _fit_osc_state(
            rows,
            np.ones(rows.shape[0]),
            n_components=1,
            feature_axis_values=AXIS,
            feature_axis_units="cm-1",
        )
    with pytest.raises(ValueError, match="score rank"):
        _fit_osc_state(
            np.column_stack((target, target)),
            target,
            n_components=1,
            feature_axis_values=np.array([1.0, 2.0]),
            feature_axis_units="cm-1",
        )
    with pytest.raises(ValueError, match="feature axis differs"):
        _apply_osc_state(
            rows,
            _fitted_state(),
            feature_axis_values=AXIS + np.array([0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.1]),
            feature_axis_units="cm-1",
        )
    contaminated = rows.copy()
    contaminated[0, 0] = np.inf
    with pytest.raises(ValueError, match="finite values"):
        _apply_osc_state(contaminated, _fitted_state(), feature_axis_values=AXIS, feature_axis_units="cm-1")
    with pytest.raises(ValueError, match="explicit numeric feature axis"):
        _fit_osc_state(
            rows,
            target,
            n_components=1,
            feature_axis_values=None,
            feature_axis_units=None,
        )
    with pytest.raises(ValueError, match="exact numeric fitted feature axis"):
        _apply_osc_state(rows, _fitted_state(), feature_axis_values=None, feature_axis_units=None)


def test_retired_iterative_parameters_and_fractional_components_fail_closed() -> None:
    with pytest.raises(ValueError, match="undeclared fields"):
        node_registry.create_node("preprocess.osc", "osc", {"n_components": 1, "tol": 1.0e-6})
    with pytest.raises(ValueError, match="exact integer"):
        node_registry.create_node("preprocess.osc", "osc", {"n_components": 1.5})


def test_osc_declares_one_complete_target_fitted_transform_contract() -> None:
    metadata = node_registry.get_metadata("preprocess.osc")
    contract = ensure_registered_execution_contract(metadata)

    assert contract.payload["runtime_family"] == RuntimeFamily.SHERPA_NATIVE.value
    assert contract.payload["lifecycle_kind"] == LifecycleKind.FITTED_TRANSFORM.value
    assert contract.payload["target_access"] == "fit_only"
    assert contract.payload["required_worker_capabilities"] == (WorkerCapability.READ_DATASET.value,)
    assert contract.payload["fitted_state_serializer"] == "spectra.osc-fearn-direct-json.v1"
    assert contract.payload["citations"] == (
        "Fearn, Chemometrics and Intelligent Laboratory Systems 50 (2000) 47-52, doi:10.1016/S0169-7439(99)00045-3",
    )
    assert [port["name"] for port in contract.payload["semantic_inputs"]] == ["default", "reference", "y"]
    assert contract.payload["semantic_outputs"][0]["accepted_data_roles"] == ("X_spectra",)
    assert contract.payload["managed_optimization_eligibility"] == ("local", "development", "full_refit")
    assert contract.payload["managed_optimization_profiles"] == ("first_party_pls",)
    admit_validation_graph([WorkflowNode("osc", "preprocess.osc", {"n_components": 1})], [])


def test_model_application_rejects_incomplete_or_mismatched_osc_records() -> None:
    rows, _, _ = _scientific_rows()
    state = _fitted_state()
    with pytest.raises(ValueError, match="complete canonical"):
        _prepare_X_for_artifact(
            rows,
            None,
            {"preprocessing_chain": [{"op_id": "preprocess.osc", "parameters": {"transform_state": state}}]},
            scope="all",
            source_dataset=_dataset(rows),
        )
    mismatched = {
        "algorithm": "fearn-direct-orthogonal-signal-correction",
        "n_components": 2,
        "state_serializer": "spectra.osc-fearn-direct-json.v1",
        "transform_state": state,
        "variance_removed_percent": 10.0,
    }
    with pytest.raises(ValueError, match="do not match"):
        _prepare_X_for_artifact(
            rows,
            None,
            {"preprocessing_chain": [{"op_id": "preprocess.osc", "parameters": mismatched}]},
            scope="all",
            source_dataset=_dataset(rows),
        )
    invalid_diagnostic = {
        **mismatched,
        "n_components": 1,
        "variance_removed_percent": 101.0,
    }
    with pytest.raises(ValueError, match="between zero and 100"):
        _prepare_X_for_artifact(
            rows,
            None,
            {"preprocessing_chain": [{"op_id": "preprocess.osc", "parameters": invalid_diagnostic}]},
            scope="all",
            source_dataset=_dataset(rows),
        )


def test_osc_executes_in_a_real_spawned_worker() -> None:
    rows, target, _ = _scientific_rows()
    context = WorkerExecutionContext(
        execution_id="canonical-osc",
        runtime=ExecutionRuntime(),
        capabilities=(WorkerCapability.READ_DATASET.value,),
        origin_pid=os.getpid(),
    )
    try:
        pool = ProcessPoolExecutor(max_workers=1, mp_context=multiprocessing.get_context("spawn"))
    except (NotImplementedError, PermissionError, OSError) as exc:
        pytest.skip(f"spawn worker unavailable: {exc}")
    try:
        result = pool.submit(
            _run_node_in_worker,
            "preprocess.osc",
            "osc",
            {"n_components": 1},
            (),
            {"default": _dataset(rows, target=target)},
            context,
        ).result(timeout=30)
    finally:
        pool.shutdown(wait=True)

    assert result.outputs["default"].shape == rows.shape
    worker = result.diagnostics["worker_execution"]
    assert worker["mode"] == "spawned_worker"
    assert worker["origin_pid"] == os.getpid()
    assert worker["worker_pid"] != os.getpid()


def test_osc_requires_its_declared_dataset_capability() -> None:
    rows, target, _ = _scientific_rows()
    context = WorkerExecutionContext(
        execution_id="canonical-osc-denied", runtime=ExecutionRuntime(), origin_pid=os.getpid()
    )
    with pytest.raises(PermissionError, match="worker capabilities are missing"):
        _run_node_in_worker(
            "preprocess.osc",
            "osc",
            {"n_components": 1},
            (),
            {"default": _dataset(rows, target=target)},
            context,
        )


def test_osc_representative_fit_and_apply_stays_below_absolute_ceiling() -> None:
    rng = np.random.default_rng(20260812)
    samples = 120
    features = 320
    target = rng.normal(size=samples)
    nuisance = rng.normal(size=(samples, 4))
    rows = (
        target[:, None] * rng.normal(size=(1, features))
        + nuisance @ rng.normal(size=(4, features))
        + rng.normal(scale=0.01, size=(samples, features))
    )
    axis = np.linspace(400.0, 4000.0, features)

    with PerformanceCeiling("preprocess.osc", "fearn-direct-120x320-two-components", 5.0).measure():
        state = _fit_osc_state(
            rows,
            target,
            n_components=2,
            feature_axis_values=axis,
            feature_axis_units="cm-1",
        )
        corrected = _apply_osc_state(
            rows,
            state,
            feature_axis_values=axis,
            feature_axis_units="cm-1",
        )

    assert corrected.shape == rows.shape

    with PerformanceCeiling(
        "preprocess.apply_fitted_osc",
        "fearn-direct-120x320-two-component-replay",
        5.0,
    ).measure():
        replayed = _apply_osc_state(
            rows,
            state,
            feature_axis_values=axis,
            feature_axis_units="cm-1",
        )
    np.testing.assert_array_equal(replayed, corrected)


@pytest.mark.asyncio
async def test_local_reference_fits_training_only_and_ignores_application_targets():
    rows, target, _ = _scientific_rows()
    training = _dataset(rows, target=target)
    application = _dataset(rows[:8] + 300, target=np.arange(8, dtype=float) * 1000)
    node = OSCNode("osc", {"n_components": 1})
    expected_state = node.fit_fitted_state(training, target)
    result = await node.execute(default=application, reference=training)
    expected = node.apply_fitted_state(application, expected_state)
    np.testing.assert_allclose(result.outputs["default"].X, expected.X)
    state = result.outputs["default"].provenance[-1].parameters["transform_state"]
    for key in ("x_mean", "orthogonal_weights", "deflation_loadings"):
        np.testing.assert_array_equal(state[key], expected_state[key])
    application.target = application.target[::-1]
    second = await node.execute(default=application, reference=training)
    np.testing.assert_array_equal(second.outputs["default"].X, result.outputs["default"].X)
    missing_target = _dataset(rows)
    with pytest.raises(ValueError, match="target"):
        await node.execute(default=application, reference=missing_target)
    code = "\n".join(node.generate_python({"default": "test_data", "reference": "train_data"}))
    assert "_resolve_target(train_data, None)" in code
    assert "fit_fitted_state(train_data, _target)" in code
