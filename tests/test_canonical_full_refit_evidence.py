"""OSS-only tests for the separate full-data application-refit evidence."""

from __future__ import annotations

import asyncio
from copy import deepcopy
from pathlib import Path

import numpy as np
import pytest

import spectra_sherpa.app.services.dag.nodes.modeling  # noqa: F401
import spectra_sherpa.app.services.dag.nodes.preprocessing  # noqa: F401
import spectra_sherpa.app.services.dag.nodes.regression_evaluator_node  # noqa: F401
from spectra_sherpa.app.lib.sherpa_dataset import SherpaDataset
from spectra_sherpa.app.services.dag.executor_types import WorkflowEdge, WorkflowNode
from spectra_sherpa.app.services.dag.fold_graph_executor import (
    execute_candidate_validation,
    execute_selected_candidate_full_refit,
)
from spectra_sherpa.app.services.dag.spectral_capability import SpectralDatasetCapability
from spectra_sherpa.app.services.dag.validation_graph import admit_validation_graph
from spectra_sherpa.app.types import type_registry
from spectra_sherpa.sdk import canonical_full_refit_evidence
from spectra_sherpa.sdk.validate import make_split_plan


@pytest.fixture(autouse=True)
def _load_type_registry() -> None:
    if not type_registry.is_loaded:
        type_registry.load(Path(__file__).resolve().parents[1] / "src" / "spectra_sherpa" / "app" / "types")


def _refit_execution():
    X = np.arange(96, dtype=float).reshape(12, 8)
    target = X[:, 0] * 0.3 + X[:, 1] * 0.1
    split = make_split_plan(X.shape[0], n_splits=3)
    capability = SpectralDatasetCapability.from_dataset(
        SherpaDataset(X=X, target=target),
        custody_id="public-fixture",
        dataset_ref_digest="a" * 64,
        split_plan_digest=split.digest,
    )
    nodes = [
        WorkflowNode("scale", "preprocess.scale", {"method": "autoscale", "center": True}),
        WorkflowNode("model", "model.fitted_pls", {"n_components": 2, "scale": True}),
        WorkflowNode("score", "diagnostics.regression_evaluator", {}),
    ]
    graph = admit_validation_graph(
        nodes,
        [WorkflowEdge(left.node_id, right.node_id) for left, right in zip(nodes, nodes[1:])],
    )
    validation = asyncio.run(execute_candidate_validation(graph, capability, split))
    return asyncio.run(execute_selected_candidate_full_refit(graph, capability, validation)), validation


def test_round_trip_binds_the_application_refit_to_selected_validation_without_metrics() -> None:
    refit, validation = _refit_execution()

    evidence = canonical_full_refit_evidence.CanonicalFullRefitEvidence.from_full_refit_execution(refit)
    loaded = canonical_full_refit_evidence.CanonicalFullRefitEvidence.from_bytes(evidence.canonical_bytes())

    assert loaded.validation_execution_digest == validation.digest
    assert loaded.full_refit_execution_digest == refit.digest
    assert loaded.content_digest == evidence.content_digest
    projection = loaded.payload["full_refit_execution"]
    assert projection["model_node_id"] == "model"
    assert [item["node_id"] for item in projection["fitted_state_references"]] == ["scale", "model"]
    encoded = evidence.canonical_bytes().decode("utf-8")
    for forbidden in ("metrics", "predictions", '"target"', "fitted_state_bytes", "file://", "/Users/"):
        assert forbidden not in encoded


def test_full_refit_evidence_rejects_a_duck_typed_forgery() -> None:
    refit, _validation = _refit_execution()

    class ForgedRefit:
        digest = refit.digest

        @staticmethod
        def as_dict():
            return refit.as_dict()

    with pytest.raises(canonical_full_refit_evidence.CanonicalFullRefitEvidenceError, match="not serializable"):
        canonical_full_refit_evidence.CanonicalFullRefitEvidence.from_full_refit_execution(ForgedRefit())


def test_detached_evidence_cannot_add_a_self_rehashed_validation_metric() -> None:
    refit, _validation = _refit_execution()
    evidence = canonical_full_refit_evidence.CanonicalFullRefitEvidence.from_full_refit_execution(refit)
    manifest = evidence.as_dict()
    payload = deepcopy(manifest)
    payload["full_refit_execution"]["metrics"] = {"rmse": 0.0}
    payload["full_refit_execution_digest"] = canonical_full_refit_evidence._digest(payload["full_refit_execution"])
    unsigned = {key: value for key, value in payload.items() if key != "content_digest"}
    payload["content_digest"] = canonical_full_refit_evidence._digest(unsigned)

    with pytest.raises(canonical_full_refit_evidence.CanonicalFullRefitEvidenceError, match="fields are closed"):
        canonical_full_refit_evidence.CanonicalFullRefitEvidence.from_dict(payload)
