"""Native PLS-DA through the same canonical fold and refit authorities as PLS."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

import spectra_sherpa.app.services.dag.nodes.classification.plsda_nodes  # noqa: F401
import spectra_sherpa.app.services.dag.nodes.classification_evaluator_node  # noqa: F401
from spectra_sherpa.app.lib.sherpa_dataset import SherpaDataset
from spectra_sherpa.app.services.dag.executor_types import WorkflowEdge, WorkflowNode
from spectra_sherpa.app.services.dag.fold_graph_executor import (
    FoldGraphExecutionError,
    execute_candidate_validation,
    execute_selected_candidate_full_refit,
)
from spectra_sherpa.app.services.dag.spectral_capability import SpectralDatasetCapability
from spectra_sherpa.app.services.dag.validation_graph import ValidationGraphError, admit_validation_graph
from spectra_sherpa.app.types import type_registry
from spectra_sherpa.sdk.validate import ClassificationMetricSet, make_classification_split_plan, make_split_plan


@pytest.fixture(autouse=True)
def loaded_registry() -> None:
    if not type_registry.is_loaded:
        type_registry.load(Path(__file__).resolve().parents[1] / "src" / "spectra_sherpa" / "app" / "types")


def _classification_capability() -> SpectralDatasetCapability:
    rng = np.random.default_rng(20260815)
    labels = np.repeat(np.asarray(["control", "blend-a", "blend-b"], dtype="U8"), 8)
    X = rng.normal(scale=0.08, size=(labels.size, 12))
    X[labels == "control", :4] += 0.2
    X[labels == "blend-a", 4:8] += 1.4
    X[labels == "blend-b", 8:12] += 2.2
    return SpectralDatasetCapability.from_dataset(
        SherpaDataset(X=X, target=labels),
        custody_id="public-native-plsda-fixture",
    )


def _classification_graph():
    return admit_validation_graph(
        [
            WorkflowNode(
                "plsda",
                "classification.plsda",
                {"n_components": 2, "scale": True},
            ),
            WorkflowNode("evaluate", "diagnostics.classification_evaluator", {}),
        ],
        [WorkflowEdge("plsda", "evaluate", "predictions", "default")],
    )


def test_managed_plsda_graph_requires_its_typed_prediction_edge() -> None:
    graph = _classification_graph()

    assert graph.edges[0].from_output == "predictions"
    assert graph.nodes[0].contract.payload["managed_optimization_profiles"] == ("first_party_pls",)
    assert graph.nodes[1].contract.payload["managed_optimization_profiles"] == ("first_party_pls",)

    with pytest.raises(ValidationGraphError, match="incompatible_semantic_edge"):
        admit_validation_graph(
            [
                WorkflowNode(
                    "plsda",
                    "classification.plsda",
                    {"n_components": 2, "scale": True},
                ),
                WorkflowNode("evaluate", "diagnostics.classification_evaluator", {}),
            ],
            [WorkflowEdge("plsda", "evaluate")],
        )


@pytest.mark.asyncio
async def test_plsda_runs_stratified_outer_validation_and_full_data_refit() -> None:
    capability = _classification_capability()
    graph = _classification_graph()
    labels = capability.arrays["target"]
    plan = make_classification_split_plan(labels, n_splits=4, shuffle=True, random_state=91)

    validation = await execute_candidate_validation(graph, capability, plan)
    refit = await execute_selected_candidate_full_refit(graph, capability, validation)

    assert isinstance(validation.metrics, ClassificationMetricSet)
    assert validation.metrics.n_samples == 24
    assert validation.metrics.labels == ("control", "blend-a", "blend-b")
    assert validation.metrics.accuracy >= 0.8
    assert validation.metrics.balanced_accuracy >= 0.8
    assert validation.metrics.macro_f1 >= 0.8
    assert -1.0 <= validation.metrics.mcc <= 1.0
    assert sum(sum(row) for row in validation.metrics.confusion_matrix) == 24
    assert len(validation.folds) == 4
    assert all(isinstance(fold.metrics, ClassificationMetricSet) for fold in validation.folds)
    assert refit.validation_execution_digest == validation.digest
    assert refit.model_node_id == "plsda"
    assert refit.node_ids == ("plsda",)
    assert len(refit.fitted_states) == 1
    assert refit.fitted_states[0].serializer == "spectrasherpa.sherpa-plsda-state/4"


@pytest.mark.asyncio
async def test_plsda_managed_validation_rejects_unstratified_folds() -> None:
    capability = _classification_capability()

    with pytest.raises(FoldGraphExecutionError, match="stratified outer-fold plan"):
        await execute_candidate_validation(
            _classification_graph(),
            capability,
            make_split_plan(24, n_splits=4),
        )
