"""C8C managed admission and fold-lifecycle proofs for fitted preprocessing."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

import spectra_sherpa.app.services.dag.nodes  # noqa: F401 - populate registry
from spectra_sherpa.app.lib.sherpa_dataset import SherpaDataset, SpectralAxis
from spectra_sherpa.app.services.dag.executor_types import WorkflowEdge, WorkflowNode
from spectra_sherpa.app.services.dag.fold_graph_executor import (
    execute_candidate_validation,
    execute_selected_candidate_full_refit,
)
from spectra_sherpa.app.services.dag.node_base import node_registry
from spectra_sherpa.app.services.dag.nodes.preprocessing.osc_node import OSCNode
from spectra_sherpa.app.services.dag.spectral_capability import SpectralDatasetCapability
from spectra_sherpa.app.services.dag.validation_graph import ValidationGraphError, admit_validation_graph
from spectra_sherpa.app.types import type_registry
from spectra_sherpa.sdk.validate import make_split_plan

_FITTED_OPERATIONS = (
    ("preprocess.msc", {"reference_method": "mean"}, "spectra.msc-reference-json.v2"),
    (
        "preprocess.emsc",
        {"reference_method": "median", "poly_order": 1},
        "spectra.emsc-reference-json.v1",
    ),
    ("preprocess.osc", {"n_components": 1}, "spectra.osc-fearn-direct-json.v1"),
)


@pytest.fixture(autouse=True)
def _load_type_registry() -> None:
    if not type_registry.is_loaded:
        type_registry.load(Path(__file__).resolve().parents[1] / "src" / "spectra_sherpa" / "app" / "types")


def _capability() -> SpectralDatasetCapability:
    rng = np.random.default_rng(20260813)
    samples = 18
    features = 24
    axis = np.linspace(900.0, 1900.0, features)
    target = np.linspace(-1.0, 1.0, samples)
    predictive = np.sin(axis / 175.0)
    nuisance = rng.normal(size=(samples, 3)) @ rng.normal(scale=0.08, size=(3, features))
    multiplicative = np.linspace(0.85, 1.15, samples)[:, None]
    offsets = np.linspace(-0.05, 0.05, samples)[:, None]
    rows = multiplicative * (1.2 + target[:, None] * predictive + nuisance) + offsets
    return SpectralDatasetCapability.from_dataset(
        SherpaDataset(
            X=rows,
            target=target,
            feature_axis=SpectralAxis(values=axis, units="cm-1"),
        ),
        custody_id="c8c-public-fitted-preprocessing",
    )


def _graph(operation_id: str, parameters: dict[str, object]):
    nodes = [
        WorkflowNode("fitted-preprocess", operation_id, parameters),
        WorkflowNode("scale", "preprocess.scale", {"method": "mean_center"}),
        WorkflowNode("model", "model.fitted_pls", {"n_components": 2, "scale": False}),
        WorkflowNode("score", "diagnostics.regression_evaluator", {}),
    ]
    return admit_validation_graph(
        nodes,
        [WorkflowEdge(left.node_id, right.node_id) for left, right in zip(nodes, nodes[1:])],
    )


@pytest.mark.parametrize(("operation_id", "parameters", "serializer"), _FITTED_OPERATIONS)
def test_fitted_preprocessing_has_one_bounded_managed_contract(
    operation_id: str,
    parameters: dict[str, object],
    serializer: str,
) -> None:
    metadata = node_registry.get_metadata(operation_id)
    contract = metadata.resolved_execution_contract()

    assert contract is not None
    assert contract.payload["lifecycle_kind"] == "fitted_transform"
    assert contract.payload["fitted_state_serializer"] == serializer
    assert contract.payload["managed_optimization_eligibility"] == ("local", "development", "full_refit")
    assert contract.payload["managed_optimization_profiles"] == ("first_party_pls",)
    assert metadata.canonicalize_managed_parameters(parameters) == metadata.canonicalize_parameters(parameters)


@pytest.mark.parametrize(
    ("operation_id", "parameters", "message"),
    [
        ("preprocess.msc", {"reference_method": "first"}, "order-sensitive"),
        ("preprocess.emsc", {"reference_method": "first", "poly_order": 1}, "order-sensitive"),
        ("preprocess.emsc", {"reference_method": "mean", "poly_order": 3}, "between 0 and 2"),
        ("preprocess.osc", {"n_components": 3}, "must be 1 or 2"),
    ],
)
def test_managed_fitted_preprocessing_rejects_out_of_envelope_settings(
    operation_id: str,
    parameters: dict[str, object],
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        node_registry.get_metadata(operation_id).canonicalize_managed_parameters(parameters)


def test_managed_emsc_rejects_external_constituent_topology() -> None:
    nodes = [
        WorkflowNode("msc", "preprocess.msc", {"reference_method": "mean"}),
        WorkflowNode("emsc", "preprocess.emsc", {"reference_method": "mean", "poly_order": 1}),
        WorkflowNode("model", "model.fitted_pls", {"n_components": 1, "scale": False}),
        WorkflowNode("score", "diagnostics.regression_evaluator", {}),
    ]
    with pytest.raises(ValidationGraphError, match="default-port edges"):
        admit_validation_graph(
            nodes,
            [
                WorkflowEdge("msc", "emsc", to_input="constituents"),
                WorkflowEdge("emsc", "model"),
                WorkflowEdge("model", "score"),
            ],
        )


@pytest.mark.asyncio
@pytest.mark.parametrize(("operation_id", "parameters", "serializer"), _FITTED_OPERATIONS)
async def test_fitted_preprocessing_runs_fold_local_and_refits_one_winner(
    operation_id: str,
    parameters: dict[str, object],
    serializer: str,
) -> None:
    capability = _capability()
    graph = _graph(operation_id, parameters)
    split = make_split_plan(18, n_splits=3)

    validation = await execute_candidate_validation(graph, capability, split)
    refit = await execute_selected_candidate_full_refit(graph, capability, validation)

    traces = [
        next(trace for trace in fold.node_execution_traces if trace.node_id == "fitted-preprocess")
        for fold in validation.folds
    ]
    assert all(trace.fitted_state_digest is not None for trace in traces)
    assert all(trace.fitted_state_serializer == serializer for trace in traces)
    fitted = next(record for record in refit.fitted_states if record.node_id == "fitted-preprocess")
    assert fitted.serializer == serializer
    assert fitted.validation_execution_digest == validation.digest
    assert refit.node_ids == ("fitted-preprocess", "scale", "model")


@pytest.mark.asyncio
async def test_managed_osc_receives_training_targets_only(monkeypatch: pytest.MonkeyPatch) -> None:
    observed_target_counts: list[int] = []
    original = OSCNode.fit_fitted_state

    def capture(self, input_data, target):
        observed_target_counts.append(int(np.asarray(target).shape[0]))
        return original(self, input_data, target)

    monkeypatch.setattr(OSCNode, "fit_fitted_state", capture)
    capability = _capability()
    graph = _graph("preprocess.osc", {"n_components": 1})

    validation = await execute_candidate_validation(graph, capability, make_split_plan(18, n_splits=3))

    assert validation.metrics.n_samples == 18
    assert observed_target_counts == [12, 12, 12]
