"""M4.5c proof that the admitted canvas graph is the fold computation."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

import spectra_sherpa.app.services.dag.nodes.data.loaders  # noqa: F401
import spectra_sherpa.app.services.dag.nodes.modeling  # noqa: F401
import spectra_sherpa.app.services.dag.nodes.preprocessing  # noqa: F401
import spectra_sherpa.app.services.dag.nodes.regression_evaluator_node  # noqa: F401
from spectra_sherpa.app.lib.sherpa_dataset import SherpaDataset, SpectralAxis
from spectra_sherpa.app.services.dag.executor_types import WorkflowEdge, WorkflowNode
from spectra_sherpa.app.services.dag.fold_graph_executor import (
    CandidateValidationExecution,
    FoldGraphExecutionError,
    execute_candidate_validation,
    execute_fold_graph,
    execute_scored_supervised_validation_fold,
    execute_selected_candidate_full_refit,
    execute_supervised_validation_fold,
    execute_validation_fold,
)
from spectra_sherpa.app.services.dag.fold_lifecycle import FoldLifecycleContext, FoldPartition
from spectra_sherpa.app.services.dag.nodes.modeling.fitted_pls_node import FittedPLSV2Node
from spectra_sherpa.app.services.dag.nodes.preprocessing.scale_node import ScaleNode
from spectra_sherpa.app.services.dag.spectral_capability import SpectralDatasetCapability
from spectra_sherpa.app.services.dag.validation_graph import (
    ValidationGraph,
    ValidationGraphEdge,
    ValidationGraphError,
    admit_validation_graph,
)
from spectra_sherpa.app.types import type_registry
from spectra_sherpa.sdk.validate import RegressionMetrics, make_split_plan


@pytest.fixture(autouse=True)
def loaded_registry() -> None:
    if not type_registry.is_loaded:
        type_registry.load(Path(__file__).resolve().parents[1] / "src" / "spectra_sherpa" / "app" / "types")


def _capability(*, custody_id: str = "public-fixture") -> SpectralDatasetCapability:
    return SpectralDatasetCapability.from_dataset(
        SherpaDataset(X=np.arange(36, dtype=float).reshape(4, 9), target=np.arange(4, dtype=float)),
        custody_id=custody_id,
    )


@pytest.mark.asyncio
async def test_admitted_canvas_chain_is_rebuilt_and_executed_independently_per_fold() -> None:
    graph = admit_validation_graph(
        [
            WorkflowNode("first", "preprocess.smooth", {"method": "gaussian", "sigma": 1.0}),
            WorkflowNode("second", "preprocess.smooth", {"method": "gaussian", "sigma": 1.0}),
        ],
        [WorkflowEdge("first", "second")],
    )
    capability = _capability()
    partition = FoldPartition.create([0, 1], [2, 3], sample_count=4)

    train = await execute_fold_graph(graph, capability, partition, role="train")
    test = await execute_fold_graph(graph, capability, partition, role="test")

    assert train.node_ids == ("first", "second")
    assert test.node_ids == ("first", "second")
    assert train.graph_digest == test.graph_digest == graph.digest
    assert train.capability_content_digest == test.capability_content_digest == capability.content_digest
    assert train.capability_envelope_digest == test.capability_envelope_digest == capability.envelope_digest
    assert train.partition_digest == test.partition_digest == partition.digest
    assert train.output.shape == test.output.shape == (2, 9)
    assert not np.array_equal(train.output.X, test.output.X)
    np.testing.assert_array_equal(capability.arrays["X"], np.arange(36, dtype=float).reshape(4, 9))


@pytest.mark.asyncio
async def test_fold_execution_is_reproducible_for_the_same_graph_and_partition() -> None:
    graph = admit_validation_graph(
        [WorkflowNode("smooth", "preprocess.smooth", {"method": "gaussian", "sigma": 1.0})], []
    )
    capability = _capability()
    partition = FoldPartition.create([0, 1], [2, 3], sample_count=4)

    first = await execute_fold_graph(graph, capability, partition, role="train")
    second = await execute_fold_graph(graph, capability, partition, role="train")

    np.testing.assert_allclose(first.output.X, second.output.X)


@pytest.mark.asyncio
async def test_executor_accepts_a_valid_chain_with_nonlexical_node_ids() -> None:
    graph = admit_validation_graph(
        [
            WorkflowNode("z-root", "preprocess.smooth", {"method": "gaussian", "sigma": 1.0}),
            WorkflowNode("a-middle", "preprocess.smooth", {"method": "gaussian", "sigma": 1.0}),
            WorkflowNode("m-terminal", "preprocess.smooth", {"method": "gaussian", "sigma": 1.0}),
        ],
        [WorkflowEdge("z-root", "a-middle"), WorkflowEdge("a-middle", "m-terminal")],
    )

    result = await execute_fold_graph(
        graph,
        _capability(),
        FoldPartition.create([0, 1], [2, 3], sample_count=4),
        role="train",
    )

    assert result.node_ids == ("z-root", "a-middle", "m-terminal")


@pytest.mark.asyncio
async def test_executor_rejects_forged_graph_with_an_alternate_topology() -> None:
    admitted = admit_validation_graph(
        [WorkflowNode("first", "preprocess.smooth", {"method": "gaussian", "sigma": 1.0})], []
    )
    forged = object.__new__(ValidationGraph)
    object.__setattr__(forged, "nodes", admitted.nodes)
    object.__setattr__(forged, "edges", (object(),))

    with pytest.raises(FoldGraphExecutionError, match="not an admitted execution identity"):
        await execute_fold_graph(
            forged,
            _capability(),
            FoldPartition.create([0, 1], [2, 3], sample_count=4),
            role="train",
        )


@pytest.mark.asyncio
async def test_executor_bounds_malformed_forged_graph_records() -> None:
    forged = object.__new__(ValidationGraph)
    object.__setattr__(forged, "nodes", (object(),))
    object.__setattr__(forged, "edges", ())

    with pytest.raises(FoldGraphExecutionError, match="not an admitted execution identity"):
        await execute_fold_graph(
            forged,
            _capability(),
            FoldPartition.create([0, 1], [2, 3], sample_count=4),
            role="train",
        )


@pytest.mark.asyncio
async def test_executor_rejects_a_preserved_samples_node_that_drops_a_row(monkeypatch) -> None:
    class DropsSample:
        async def execute(self, *, input_data: SherpaDataset) -> SherpaDataset:
            return SherpaDataset(X=input_data.X[:1])

    monkeypatch.setattr(FoldLifecycleContext, "fresh_node", lambda *_args, **_kwargs: DropsSample())
    graph = admit_validation_graph(
        [WorkflowNode("smooth", "preprocess.smooth", {"method": "gaussian", "sigma": 1.0})], []
    )

    with pytest.raises(FoldGraphExecutionError, match="violated its preserves-samples contract"):
        await execute_fold_graph(
            graph,
            _capability(),
            FoldPartition.create([0, 1], [2, 3], sample_count=4),
            role="train",
        )


@pytest.mark.asyncio
async def test_executor_bounds_node_exceptions_without_returning_partial_result(monkeypatch) -> None:
    class FailingNode:
        async def execute(self, *, input_data: SherpaDataset) -> SherpaDataset:
            del input_data
            raise RuntimeError("raw sample detail must not become the public failure")

    monkeypatch.setattr(FoldLifecycleContext, "fresh_node", lambda *_args, **_kwargs: FailingNode())
    graph = admit_validation_graph(
        [WorkflowNode("smooth", "preprocess.smooth", {"method": "gaussian", "sigma": 1.0})], []
    )

    with pytest.raises(FoldGraphExecutionError, match="smooth execution failed") as caught:
        await execute_fold_graph(
            graph,
            _capability(),
            FoldPartition.create([0, 1], [2, 3], sample_count=4),
            role="train",
        )
    assert "raw sample detail" not in str(caught.value)


@pytest.mark.asyncio
async def test_execution_record_binds_capability_custody_envelope() -> None:
    graph = admit_validation_graph(
        [WorkflowNode("smooth", "preprocess.smooth", {"method": "gaussian", "sigma": 1.0})], []
    )
    partition = FoldPartition.create([0, 1], [2, 3], sample_count=4)
    first = await execute_fold_graph(graph, _capability(custody_id="custody-a"), partition, role="train")
    second = await execute_fold_graph(graph, _capability(custody_id="custody-b"), partition, role="train")

    assert first.capability_content_digest == second.capability_content_digest
    assert first.capability_envelope_digest != second.capability_envelope_digest


@pytest.mark.asyncio
async def test_paired_fold_executor_fits_reference_scale_only_on_training_then_applies_to_held_out(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    capability = SpectralDatasetCapability.from_dataset(
        SherpaDataset(
            X=np.array([[0.0, 2.0], [2.0, 6.0], [4.0, 10.0], [6.0, 14.0]]),
            target=np.arange(4, dtype=float),
        ),
        custody_id="public-fixture",
    )
    graph = admit_validation_graph([WorkflowNode("reference-scale", "preprocess.scale", {"method": "mean_center"})], [])
    fitted_inputs: list[np.ndarray] = []
    original_fit = ScaleNode.fit_fitted_state

    def _capture_fit(node: ScaleNode, input_data: SherpaDataset):
        fitted_inputs.append(np.array(input_data.X, copy=True))
        return original_fit(node, input_data)

    monkeypatch.setattr(ScaleNode, "fit_fitted_state", _capture_fit)

    result = await execute_validation_fold(
        graph,
        capability,
        FoldPartition.create([0, 1], [2, 3], sample_count=4),
    )

    np.testing.assert_allclose(result.train_output.X, [[-1.0, -2.0], [1.0, 2.0]])
    np.testing.assert_allclose(result.test_output.X, [[3.0, 6.0], [5.0, 10.0]])
    assert len(fitted_inputs) == 1
    np.testing.assert_allclose(fitted_inputs[0], [[0.0, 2.0], [2.0, 6.0]])
    assert result.node_ids == ("reference-scale",)
    # Re-fitting the held-out partition would produce a zero-centered result.
    assert not np.allclose(result.test_output.X, 0.0)


@pytest.mark.asyncio
async def test_paired_executor_keeps_stateless_steps_in_the_same_canonical_graph_before_fitted_apply() -> None:
    graph = admit_validation_graph(
        [
            WorkflowNode("smooth", "preprocess.smooth", {"method": "gaussian", "sigma": 1.0}),
            WorkflowNode("reference-scale", "preprocess.scale", {"method": "mean_center"}),
        ],
        [WorkflowEdge("smooth", "reference-scale")],
    )

    result = await execute_validation_fold(
        graph,
        _capability(),
        FoldPartition.create([0, 1], [2, 3], sample_count=4),
    )

    assert result.node_ids == ("smooth", "reference-scale")
    assert result.train_output.shape == result.test_output.shape == (2, 9)
    assert not np.allclose(result.test_output.X, 0.0)


@pytest.mark.asyncio
async def test_single_role_executor_refuses_a_fitted_graph_instead_of_silently_fitting_each_role() -> None:
    graph = admit_validation_graph([WorkflowNode("reference-scale", "preprocess.scale", {"method": "autoscale"})], [])

    with pytest.raises(FoldGraphExecutionError, match="stateless transforms only"):
        await execute_fold_graph(
            graph,
            _capability(),
            FoldPartition.create([0, 1], [2, 3], sample_count=4),
            role="test",
        )


@pytest.mark.asyncio
async def test_supervised_executor_fits_explicit_pls_only_on_training_targets_and_never_reads_held_out_targets(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    capability = SpectralDatasetCapability.from_dataset(
        SherpaDataset(
            X=np.array([[0.0], [1.0], [2.0], [3.0], [4.0], [5.0]], dtype=float),
            target=np.array([0.0, 1.0, 2.0, 3.0, 4.0, 5.0], dtype=float),
        ),
        custody_id="public-fixture",
    )
    graph = admit_validation_graph(
        [WorkflowNode("pls-v2", "model.fitted_pls", {"n_components": 1, "scale": False})], []
    )
    fitted_targets: list[np.ndarray] = []
    original_fit = FittedPLSV2Node.fit_fitted_state
    original_target = FoldLifecycleContext.target

    def _capture_fit(node: FittedPLSV2Node, input_data: SherpaDataset, target: SherpaDataset):
        fitted_targets.append(np.array(target.X, copy=True))
        return original_fit(node, input_data, target)

    def _only_train_target(context: FoldLifecycleContext, role: str) -> np.ndarray:
        assert role == "train", "prediction layer must not retrieve held-out targets"
        return original_target(context, role)  # type: ignore[arg-type]

    monkeypatch.setattr(FittedPLSV2Node, "fit_fitted_state", _capture_fit)
    monkeypatch.setattr(FoldLifecycleContext, "target", _only_train_target)

    result = await execute_supervised_validation_fold(
        graph,
        capability,
        FoldPartition.create([0, 1, 2, 3], [4, 5], sample_count=6),
    )

    np.testing.assert_allclose(fitted_targets, [[[0.0], [1.0], [2.0], [3.0]]])
    np.testing.assert_allclose(result.train_predictions[:, 0], [0.0, 1.0, 2.0, 3.0], atol=1e-12)
    np.testing.assert_allclose(result.test_predictions[:, 0], [4.0, 5.0], atol=1e-12)
    assert result.node_ids == ("pls-v2",)
    assert len(result.fitted_state_digest) == 64
    assert not result.train_predictions.flags.writeable
    assert not result.test_predictions.flags.writeable


@pytest.mark.asyncio
async def test_supervised_executor_requires_one_terminal_fitted_model() -> None:
    transform_only = admit_validation_graph(
        [WorkflowNode("smooth", "preprocess.smooth", {"method": "gaussian", "sigma": 1.0})], []
    )

    with pytest.raises(FoldGraphExecutionError, match="requires one terminal fitted model"):
        await execute_supervised_validation_fold(
            transform_only,
            _capability(),
            FoldPartition.create([0, 1], [2, 3], sample_count=4),
        )


@pytest.mark.asyncio
async def test_supervised_executor_fails_closed_when_the_admitted_target_capability_is_absent() -> None:
    graph = admit_validation_graph(
        [WorkflowNode("pls-v2", "model.fitted_pls", {"n_components": 1, "scale": False})], []
    )
    capability_without_target = SpectralDatasetCapability.from_dataset(
        SherpaDataset(X=np.arange(12, dtype=float).reshape(4, 3)), custody_id="public-fixture"
    )

    with pytest.raises(FoldGraphExecutionError, match="pls-v2 fitted model execution failed"):
        await execute_supervised_validation_fold(
            graph,
            capability_without_target,
            FoldPartition.create([0, 1], [2, 3], sample_count=4),
        )


@pytest.mark.asyncio
async def test_general_pair_executor_refuses_the_model_lifecycle_instead_of_misreporting_predictions_as_datasets() -> (
    None
):
    graph = admit_validation_graph(
        [WorkflowNode("pls-v2", "model.fitted_pls", {"n_components": 1, "scale": False})], []
    )

    with pytest.raises(FoldGraphExecutionError, match="unsupported lifecycle"):
        await execute_validation_fold(
            graph,
            _capability(),
            FoldPartition.create([0, 1], [2, 3], sample_count=4),
        )


@pytest.mark.asyncio
async def test_terminal_evaluator_is_the_only_layer_that_reads_held_out_targets_and_scores_predictions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    capability = SpectralDatasetCapability.from_dataset(
        SherpaDataset(
            X=np.array([[0.0], [1.0], [2.0], [3.0], [4.0], [5.0]], dtype=float),
            target=np.array([0.0, 1.0, 2.0, 3.0, 4.0, 5.0], dtype=float),
        ),
        custody_id="public-fixture",
    )
    graph = admit_validation_graph(
        [
            WorkflowNode("pls-v2", "model.fitted_pls", {"n_components": 1, "scale": False}),
            WorkflowNode("score", "diagnostics.regression_evaluator", {}),
        ],
        [WorkflowEdge("pls-v2", "score")],
    )
    original_target = FoldLifecycleContext.target
    target_reads: list[tuple[str, str]] = []

    def _capture_target(context: FoldLifecycleContext, role: str) -> np.ndarray:
        target_reads.append((context.contract.payload["operation_id"], role))
        return original_target(context, role)  # type: ignore[arg-type]

    monkeypatch.setattr(FoldLifecycleContext, "target", _capture_target)
    result = await execute_scored_supervised_validation_fold(
        graph,
        capability,
        FoldPartition.create([0, 1, 2, 3], [4, 5], sample_count=6),
    )

    assert target_reads == [
        ("model.fitted_pls", "train"),
        ("diagnostics.regression_evaluator", "test"),
    ]
    assert result.node_ids == ("pls-v2", "score")
    assert result.model_node_id == "pls-v2"
    assert result.evaluator_node_id == "score"
    assert result.metrics.registry_version == "2"
    assert result.metrics.n_samples == 2
    assert result.metrics.rmse == pytest.approx(0.0, abs=1e-12)
    assert len(result.fitted_state_digest) == 64
    assert not hasattr(result, "test_predictions")


@pytest.mark.asyncio
async def test_scored_executor_fails_closed_without_held_out_target_capability() -> None:
    graph = admit_validation_graph(
        [
            WorkflowNode("pls-v2", "model.fitted_pls", {"n_components": 1, "scale": False}),
            WorkflowNode("score", "diagnostics.regression_evaluator", {}),
        ],
        [WorkflowEdge("pls-v2", "score")],
    )
    capability_without_target = SpectralDatasetCapability.from_dataset(
        SherpaDataset(X=np.arange(12, dtype=float).reshape(4, 3)), custody_id="public-fixture"
    )

    with pytest.raises(FoldGraphExecutionError, match="pls-v2 fitted model execution failed"):
        await execute_scored_supervised_validation_fold(
            graph,
            capability_without_target,
            FoldPartition.create([0, 1], [2, 3], sample_count=4),
        )


@pytest.mark.asyncio
async def test_scored_executor_requires_the_evaluator_to_follow_the_model() -> None:
    graph = admit_validation_graph(
        [WorkflowNode("pls-v2", "model.fitted_pls", {"n_components": 1, "scale": False})], []
    )

    with pytest.raises(FoldGraphExecutionError, match="immediately precede the terminal evaluator"):
        await execute_scored_supervised_validation_fold(
            graph,
            _capability(),
            FoldPartition.create([0, 1], [2, 3], sample_count=4),
        )


@pytest.mark.asyncio
async def test_candidate_validation_runs_each_locked_outer_fold_and_pools_only_bounded_summaries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    capability = SpectralDatasetCapability.from_dataset(
        SherpaDataset(
            X=np.arange(12, dtype=float).reshape(6, 2),
            target=np.arange(6, dtype=float),
        ),
        custody_id="public-fixture",
    )
    graph = admit_validation_graph(
        [
            WorkflowNode("pls-v2", "model.fitted_pls", {"n_components": 1, "scale": False}),
            WorkflowNode("score", "diagnostics.regression_evaluator", {}),
        ],
        [WorkflowEdge("pls-v2", "score")],
    )
    plan = make_split_plan(6, n_splits=3)
    original_target = FoldLifecycleContext.target
    held_out_reads: list[str] = []

    def _capture_target(context: FoldLifecycleContext, role: str) -> np.ndarray:
        if role == "test":
            held_out_reads.append(context.contract.payload["operation_id"])
        return original_target(context, role)  # type: ignore[arg-type]

    monkeypatch.setattr(FoldLifecycleContext, "target", _capture_target)
    result = await execute_candidate_validation(graph, capability, plan)

    assert result.graph_digest == graph.digest
    assert result.split_plan is plan
    assert len(result.folds) == 3
    assert [fold.partition_digest for fold in result.folds] == [
        FoldPartition.create(fold.train, fold.test, sample_count=6).digest for fold in plan.folds
    ]
    assert held_out_reads == ["diagnostics.regression_evaluator"] * 3
    assert result.metrics.n_samples == 6
    assert set(result.__dataclass_fields__) == {
        "graph_digest",
        "capability_content_digest",
        "capability_envelope_digest",
        "split_plan",
        "task_type",
        "model_operation_id",
        "metrics",
        "folds",
    }
    assert not hasattr(result, "predictions")
    assert not hasattr(result, "observed")
    assert not hasattr(result, "accumulator")
    assert all(not hasattr(fold, "evaluation") for fold in result.folds)


@pytest.mark.asyncio
async def test_candidate_validation_refuses_a_grouped_plan_without_capability_groups() -> None:
    graph = admit_validation_graph(
        [
            WorkflowNode("pls-v2", "model.fitted_pls", {"n_components": 1, "scale": False}),
            WorkflowNode("score", "diagnostics.regression_evaluator", {}),
        ],
        [WorkflowEdge("pls-v2", "score")],
    )
    grouped_plan = make_split_plan(4, n_splits=2, groups=np.array(["a", "a", "b", "b"]))

    with pytest.raises(FoldGraphExecutionError, match="requires groups"):
        await execute_candidate_validation(
            graph,
            _capability(),
            grouped_plan,
        )


@pytest.mark.asyncio
async def test_selected_candidate_full_refit_is_bound_to_validation_and_never_scores_full_data() -> None:
    capability = SpectralDatasetCapability.from_dataset(
        SherpaDataset(
            X=np.arange(48, dtype=float).reshape(6, 8),
            target=np.array([0.0, 1.0, 1.5, 2.5, 4.0, 5.5]),
        ),
        custody_id="public-fixture",
    )
    graph = admit_validation_graph(
        [
            WorkflowNode("scale", "preprocess.scale", {"method": "mean_center", "center": True}),
            WorkflowNode("pls-v2", "model.fitted_pls", {"n_components": 1, "scale": False}),
            WorkflowNode("score", "diagnostics.regression_evaluator", {}),
        ],
        [WorkflowEdge("scale", "pls-v2"), WorkflowEdge("pls-v2", "score")],
    )
    selected = await execute_candidate_validation(graph, capability, make_split_plan(6, n_splits=3))

    refit = await execute_selected_candidate_full_refit(graph, capability, selected)

    assert refit.validation_execution_digest == selected.digest
    assert refit.graph_digest == graph.digest
    assert refit.model_node_id == "pls-v2"
    assert refit.node_ids == ("scale", "pls-v2")
    assert len(refit.fitted_states) == 2
    assert all(record.validation_execution_digest == selected.digest for record in refit.fitted_states)
    assert {record.serializer for record in refit.fitted_states} == {
        "spectra.scale-reference-json.v2",
        "spectra.sherpa-simpls-regression-json/9",
    }
    assert all(record.capability_content_digest == capability.content_digest for record in refit.fitted_states)
    assert not hasattr(refit, "metrics")
    assert not hasattr(refit, "predictions")


@pytest.mark.asyncio
async def test_complete_first_party_profile_runs_fold_local_validation_and_full_refit() -> None:
    """Certify every current managed operation as one canonical DAG.

    The graph deliberately contains every profile member.  It is not a model
    search claim: the test proves only that the same typed graph supplies
    leak-safe folds and the selected candidate's full-data refit.
    """

    samples = np.linspace(0.0, 1.0, 8, dtype=np.float64)
    features = np.linspace(1000.0, 1800.0, 12, dtype=np.float64)
    X = np.vstack([0.2 * sample + 0.05 * np.sin(features / 100.0) + 0.00001 * features**2 for sample in samples])
    capability = SpectralDatasetCapability.from_dataset(
        SherpaDataset(
            X=X,
            target=1.5 * samples + 0.25,
            feature_axis=SpectralAxis(values=features, units="cm-1"),
        ),
        custody_id="public-first-party-profile-fixture",
    )
    graph = admit_validation_graph(
        [
            WorkflowNode("smooth", "preprocess.smooth", {"method": "gaussian", "sigma": 1.0}),
            WorkflowNode("normalize", "preprocess.normalize", {"method": "snv"}),
            WorkflowNode(
                "derivative",
                "preprocess.derivative",
                {"method": "savitzky_golay", "deriv": "1", "size": 5, "order": 2},
            ),
            WorkflowNode(
                "baseline",
                "baseline.penalized_ls",
                {"method": "als", "lam": 1e3, "p": 0.001, "max_iter": 100, "tol": 1e-4},
            ),
            WorkflowNode("scale", "preprocess.scale", {"method": "mean_center"}),
            WorkflowNode("pls", "model.fitted_pls", {"n_components": 1, "scale": False}),
            WorkflowNode("evaluate", "diagnostics.regression_evaluator", {}),
        ],
        [
            WorkflowEdge("smooth", "normalize"),
            WorkflowEdge("normalize", "derivative"),
            WorkflowEdge("derivative", "baseline"),
            WorkflowEdge("baseline", "scale"),
            WorkflowEdge("scale", "pls"),
            WorkflowEdge("pls", "evaluate"),
        ],
    )

    validation = await execute_candidate_validation(graph, capability, make_split_plan(8, n_splits=4))
    refit = await execute_selected_candidate_full_refit(graph, capability, validation)

    assert validation.graph_digest == graph.digest
    assert validation.metrics.n_samples == 8
    assert validation.metrics.rmse >= 0.0
    assert tuple(fold.node_ids for fold in validation.folds) == (tuple(node.node_id for node in graph.nodes),) * 4
    assert refit.graph_digest == graph.digest
    assert refit.validation_execution_digest == validation.digest
    assert refit.node_ids == ("smooth", "normalize", "derivative", "baseline", "scale", "pls")
    assert {record.serializer for record in refit.fitted_states} == {
        "spectra.scale-reference-json.v2",
        "spectra.sherpa-simpls-regression-json/9",
    }


@pytest.mark.asyncio
async def test_selected_candidate_full_refit_withholds_target_until_the_declared_model_access(monkeypatch) -> None:
    capability = SpectralDatasetCapability.from_dataset(
        SherpaDataset(
            X=np.arange(48, dtype=float).reshape(6, 8),
            target=np.array([0.0, 1.0, 1.5, 2.5, 4.0, 5.5]),
        ),
        custody_id="public-fixture",
    )
    graph = admit_validation_graph(
        [
            WorkflowNode("scale", "preprocess.scale", {"method": "mean_center", "center": True}),
            WorkflowNode("pls-v2", "model.fitted_pls", {"n_components": 1, "scale": False}),
            WorkflowNode("score", "diagnostics.regression_evaluator", {}),
        ],
        [WorkflowEdge("scale", "pls-v2"), WorkflowEdge("pls-v2", "score")],
    )
    selected = await execute_candidate_validation(graph, capability, make_split_plan(6, n_splits=3))

    observed: dict[str, np.ndarray | None] = {}
    scale_fit = ScaleNode.fit_fitted_state
    pls_fit = FittedPLSV2Node.fit_fitted_state

    def capture_scale_target(self, input_data):
        observed["scale_target"] = input_data.target
        return scale_fit(self, input_data)

    def capture_pls_target(self, input_data, target):
        observed["pls_input_target"] = input_data.target
        observed["pls_explicit_target"] = np.array(target.X, copy=True)
        return pls_fit(self, input_data, target)

    monkeypatch.setattr(ScaleNode, "fit_fitted_state", capture_scale_target)
    monkeypatch.setattr(FittedPLSV2Node, "fit_fitted_state", capture_pls_target)

    await execute_selected_candidate_full_refit(graph, capability, selected)

    assert observed["scale_target"] is None
    assert observed["pls_input_target"] is None
    np.testing.assert_array_equal(observed["pls_explicit_target"], capability.arrays["target"].reshape(-1, 1))


@pytest.mark.asyncio
async def test_selected_candidate_full_refit_rejects_validation_from_another_capability() -> None:
    graph = admit_validation_graph(
        [
            WorkflowNode("pls-v2", "model.fitted_pls", {"n_components": 1, "scale": False}),
            WorkflowNode("score", "diagnostics.regression_evaluator", {}),
        ],
        [WorkflowEdge("pls-v2", "score")],
    )
    selected = await execute_candidate_validation(graph, _capability(), make_split_plan(4, n_splits=2))
    other = SpectralDatasetCapability.from_dataset(
        SherpaDataset(X=np.arange(36, dtype=float).reshape(4, 9) + 1.0, target=np.arange(4, dtype=float)),
        custody_id="different-fixture",
    )

    with pytest.raises(FoldGraphExecutionError, match="does not match"):
        await execute_selected_candidate_full_refit(graph, other, selected)


@pytest.mark.asyncio
async def test_selected_candidate_full_refit_rejects_a_forged_validation_execution() -> None:
    capability = _capability()
    graph = admit_validation_graph(
        [
            WorkflowNode("pls-v2", "model.fitted_pls", {"n_components": 1, "scale": False}),
            WorkflowNode("score", "diagnostics.regression_evaluator", {}),
        ],
        [WorkflowEdge("pls-v2", "score")],
    )
    selected = await execute_candidate_validation(graph, capability, make_split_plan(4, n_splits=2))

    with pytest.raises(TypeError):
        CandidateValidationExecution(
            graph_digest=graph.digest,
            capability_content_digest=capability.content_digest,
            capability_envelope_digest=capability.envelope_digest,
            split_plan=selected.split_plan,
            metrics=RegressionMetrics("1", 4, -99.0, -88.0, 0.0, 1.0),
            folds=selected.folds,
        )

    forged = object.__new__(CandidateValidationExecution)
    for name in (
        "graph_digest",
        "capability_content_digest",
        "capability_envelope_digest",
        "split_plan",
        "folds",
    ):
        object.__setattr__(forged, name, getattr(selected, name))
    object.__setattr__(forged, "metrics", RegressionMetrics("2", 4, -99.0, -88.0, 0.0, 1.0))

    with pytest.raises(FoldGraphExecutionError, match="executor-issued"):
        await execute_selected_candidate_full_refit(graph, capability, forged)


@pytest.mark.asyncio
async def test_selected_candidate_full_refit_rechecks_executor_issued_fold_bindings() -> None:
    capability = _capability()
    graph = admit_validation_graph(
        [
            WorkflowNode("pls-v2", "model.fitted_pls", {"n_components": 1, "scale": False}),
            WorkflowNode("score", "diagnostics.regression_evaluator", {}),
        ],
        [WorkflowEdge("pls-v2", "score")],
    )
    selected = await execute_candidate_validation(graph, capability, make_split_plan(4, n_splits=2))
    first_fold = selected.folds[0]
    object.__setattr__(first_fold, "metrics", RegressionMetrics("2", 2, -1.0, -1.0, 0.0, 1.0))

    with pytest.raises(FoldGraphExecutionError, match="impossible regression values"):
        await execute_selected_candidate_full_refit(graph, capability, selected)


def test_graph_authority_rejects_a_forged_nonterminal_aggregating_evaluator() -> None:
    admitted = admit_validation_graph(
        [
            WorkflowNode("pls-v2", "model.fitted_pls", {"n_components": 1, "scale": False}),
            WorkflowNode("score", "diagnostics.regression_evaluator", {}),
        ],
        [WorkflowEdge("pls-v2", "score")],
    )
    forged = object.__new__(ValidationGraph)
    object.__setattr__(forged, "nodes", (admitted.nodes[1], admitted.nodes[0]))
    object.__setattr__(
        forged,
        "edges",
        (ValidationGraphEdge("score", "pls-v2", "default", "default"),),
    )

    with pytest.raises(ValidationGraphError, match="evaluator must be the one terminal node after a fitted model"):
        from spectra_sherpa.app.services.dag.validation_graph import assert_admitted_validation_graph

        assert_admitted_validation_graph(forged)
