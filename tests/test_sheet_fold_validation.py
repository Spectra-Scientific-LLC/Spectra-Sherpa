"""A sheet opened from a campaign candidate is scored with the campaign's exact folds."""

from __future__ import annotations

import numpy as np
import pytest

import spectra_sherpa.app.services.dag.nodes.data  # noqa: F401
import spectra_sherpa.app.services.dag.nodes.modeling  # noqa: F401
import spectra_sherpa.app.services.dag.nodes.preprocessing  # noqa: F401
import spectra_sherpa.app.services.dag.nodes.regression_evaluator_node  # noqa: F401
from spectra_sherpa.app.lib.sherpa_dataset import SherpaDataset, SpectralAxis
from spectra_sherpa.app.services.dag.executor import DAGExecutor
from spectra_sherpa.app.services.dag.executor_types import WorkflowEdge, WorkflowNode
from spectra_sherpa.app.services.dag.sheet_fold_validation import (
    SHEET_FOLD_VALIDATION_VERSION,
    SheetFoldValidationError,
    SheetFoldValidationPlan,
    fold_validation_chain,
    prepare_sheet_fold_validation,
    reconstruct_split_plan,
    run_sheet_fold_validation_async,
)
from spectra_sherpa.app.services.model_store import ModelStore
from spectra_sherpa.core.execution_runtime import ExecutionRuntime

CHAIN = [
    WorkflowNode("scale", "preprocess.scale", {"method": "autoscale", "center": True}),
    WorkflowNode("model", "model.fitted_pls", {"n_components": 2, "scale": True}),
    WorkflowNode("score", "diagnostics.regression_evaluator", {}),
]


def _dataset(n: int = 30) -> SherpaDataset:
    rng = np.random.default_rng(7)
    x = rng.normal(size=(n, 12))
    y = x[:, 0] * 2.0 - x[:, 3] + rng.normal(scale=0.05, size=n)
    return SherpaDataset(
        X=x, target=y, feature_axis=SpectralAxis(values=np.linspace(1000, 2000, 12), title="Wavenumber", units="cm-1")
    )


def _plan(dataset: SherpaDataset, **changes) -> SheetFoldValidationPlan:
    split = reconstruct_split_plan(
        task_type="regression", n_samples=dataset.shape[0], outer_splits=5, target=dataset.target, groups=None
    )
    value = {
        "schema_version": SHEET_FOLD_VALIDATION_VERSION,
        "task_type": "regression",
        "outer_splits": 5,
        "split_digest": split.digest,
        "dataset_content_digest": None,
        "origin": "campaign-1 · candidate-012",
        **changes,
    }
    return SheetFoldValidationPlan.from_dict(value)


def _executor(dataset: SherpaDataset, plan: SheetFoldValidationPlan | None, artifact_root) -> DAGExecutor:
    executor = DAGExecutor(process_pool=None, runtime=ExecutionRuntime(model_artifact_writer=ModelStore(artifact_root)))
    executor._process_pool = None
    executor.add_node(WorkflowNode("source", "data.file_load", {"experiment_id": 1, "file_id": 2}))
    for node in CHAIN:
        executor.add_node(node)
    executor.add_edge(WorkflowEdge("source", "scale"))
    executor.add_edge(WorkflowEdge("scale", "model"))
    executor.add_edge(WorkflowEdge("model", "score"))
    executor.inject_result("source", dataset)
    executor.fold_validation_plan = plan
    return executor


def _edges() -> list[WorkflowEdge]:
    return [WorkflowEdge("scale", "model"), WorkflowEdge("model", "score")]


async def test_the_evaluator_reports_campaign_fold_metrics_not_training_metrics(tmp_path):
    dataset = _dataset()
    plan = _plan(dataset)
    graph, capability, split = prepare_sheet_fold_validation(plan, CHAIN, _edges(), dataset)
    reference = await run_sheet_fold_validation_async(graph, capability, split)

    results = await _executor(dataset, plan, tmp_path).execute()
    metrics = results["score"]["default"]

    assert metrics["rmse"] == pytest.approx(reference["metrics"]["rmse"])
    assert metrics["n_samples"] == 30
    scope = metrics["fold_validation"]
    assert scope["scope"] == "cross_validation" and scope["n_folds"] == 5 and scope["method"] == "kfold"
    assert scope["split_digest"] == plan.split_digest
    assert len(scope["fold_metrics"]) == 5
    assert metrics["population_authority"]["role"] == "cross_validation"


async def test_the_worker_pool_entry_point_matches_in_process_scoring():
    import asyncio

    from spectra_sherpa.app.services.dag.sheet_fold_validation import run_sheet_fold_validation

    dataset = _dataset()
    graph, capability, split = prepare_sheet_fold_validation(_plan(dataset), CHAIN, _edges(), dataset)
    in_process = await run_sheet_fold_validation_async(graph, capability, split)
    pooled = await asyncio.to_thread(run_sheet_fold_validation, graph, capability, split)
    assert pooled["validation_execution_digest"] == in_process["validation_execution_digest"]


async def test_changed_data_is_a_new_evaluation_not_claimed_reproduction(tmp_path):
    dataset = _dataset()
    plan = _plan(dataset)
    results = await _executor(_dataset(29), plan, tmp_path).execute()
    scope = results["score"]["default"]["fold_validation"]
    assert scope["data_identity"] == "unknown"
    assert scope["same_fold_indices"] is False
    assert "New cross-validation" in scope["comparison_notice"]


async def test_reordered_rows_do_not_claim_original_fold_membership(tmp_path):
    dataset = _dataset()
    _, original_wire, _ = prepare_sheet_fold_validation(_plan(dataset), CHAIN, _edges(), dataset)
    plan = _plan(dataset, dataset_content_digest=original_wire["content_digest"])
    same = (await _executor(dataset, plan, tmp_path).execute())["score"]["default"]["fold_validation"]
    assert same["data_identity"] == "verified_same"
    reordered = SherpaDataset(X=dataset.X[::-1], target=dataset.target[::-1], feature_axis=dataset.feature_axis)
    scope = (await _executor(reordered, plan, tmp_path).execute())["score"]["default"]["fold_validation"]
    assert scope["same_fold_indices"] is True
    assert scope["data_identity"] == "unknown"
    assert "original sample identity or fold membership is not verified" in scope["comparison_notice"]


async def test_without_a_plan_the_sheet_runs_as_before(tmp_path):
    executor = _executor(_dataset(), None, tmp_path)
    with pytest.raises(ValueError, match="explicit y_true edge"):
        await executor.execute()


@pytest.mark.parametrize("source_type", ["data.file_load", "data.collection_load"])
def test_the_chain_is_found_from_the_evaluator_back_to_the_data_boundary(source_type):
    nodes = {"source": source_type, "scale": "preprocess.scale", "model": "model.fitted_pls"}
    nodes["score"] = "diagnostics.regression_evaluator"
    edges = [WorkflowEdge("source", "scale"), *_edges()]
    assert fold_validation_chain(nodes, edges, "score") == ("source", ["scale", "model", "score"])
    assert fold_validation_chain(nodes, edges, "model") is None
    with_truth = [*edges, WorkflowEdge("source", "score", to_input="y_true")]
    assert fold_validation_chain(nodes, with_truth, "score") is None
    branched = [*edges, WorkflowEdge("source", "model", to_input="y")]
    with pytest.raises(SheetFoldValidationError, match="unbranched chain"):
        fold_validation_chain(nodes, branched, "score")


@pytest.mark.parametrize(
    "change",
    [{"extra": 1}, {"outer_splits": 1}, {"split_digest": "x"}, {"task_type": "clustering"}, {"origin": ""}],
)
def test_the_plan_is_a_closed_contract(change):
    dataset = _dataset()
    value = {**_plan(dataset).as_dict(), **change}
    with pytest.raises(SheetFoldValidationError):
        SheetFoldValidationPlan.from_dict(value)


def test_masked_samples_or_features_are_refused_rather_than_silently_scored():
    base = _dataset()
    plan = _plan(base)
    dataset = SherpaDataset(
        X=base.X,
        target=base.target,
        feature_axis=SpectralAxis(
            values=np.linspace(1000, 2000, 12),
            title="Wavenumber",
            units="cm-1",
            include_mask=np.array([True] * 11 + [False]),
        ),
    )
    with pytest.raises(SheetFoldValidationError, match="every sample and feature included"):
        prepare_sheet_fold_validation(plan, CHAIN, _edges(), dataset)


async def test_the_fold_run_survives_a_real_isolated_worker_process(tmp_path):
    from spectra_sherpa.app.services.dag.executor_pool import IsolatedWorkerPool

    dataset = _dataset()
    plan = _plan(dataset)
    graph, capability, split = prepare_sheet_fold_validation(plan, CHAIN, _edges(), dataset)
    in_process = await run_sheet_fold_validation_async(graph, capability, split)
    executor = _executor(dataset, plan, tmp_path)
    pool = IsolatedWorkerPool(max_workers=1)
    executor._process_pool = pool
    try:
        results = await executor.execute()
    finally:
        pool.shutdown()
    scope = results["score"]["default"]["fold_validation"]
    assert scope["validation_execution_digest"] == in_process["validation_execution_digest"]


def test_target_attachment_cannot_hide_global_fitted_preprocessing():
    nodes = {
        "source": "data.file_load",
        "scale": "preprocess.scale",
        "attach": "data.attach_target",
        "model": "model.fitted_pls",
        "score": "diagnostics.regression_evaluator",
    }
    edges = [
        WorkflowEdge("source", "scale"),
        WorkflowEdge("scale", "attach"),
        WorkflowEdge("attach", "model"),
        WorkflowEdge("model", "score"),
    ]
    with pytest.raises(SheetFoldValidationError, match="inside each validation fold"):
        fold_validation_chain(nodes, edges, "score")
