"""Canonical HCA scientific, state, projection, and cost proofs."""

from __future__ import annotations

import copy
import json

import numpy as np
import pytest

import spectra_sherpa.app.services.dag.nodes  # noqa: F401 - populate built-ins
from spectra_sherpa.app.lib.sherpa_dataset import SampleAxis, SherpaDataset
from spectra_sherpa.app.services.dag.node_base import node_registry
from spectra_sherpa.app.services.dag.nodes.modeling.clustering_nodes import HCANode
from spectra_sherpa.app.services.dag.nodes.modeling.hca_core import (
    HCA_EMBEDDING_RULE,
    HCA_LABEL_RULE,
    HCA_STATE_SERIALIZER,
    canonical_hca_parameters,
    fit_hca,
    replay_hca_labels,
    validate_hca_state,
)
from spectra_sherpa.execution_contract_vocabulary import LifecycleKind, ManagedOptimizationEligibility, RuntimeFamily
from tests.performance_contract import PerformanceCeiling


def _parameters(**overrides: object) -> dict[str, object]:
    parameters: dict[str, object] = {"n_clusters": 3, "linkage": "ward", "metric": "euclidean"}
    parameters.update(overrides)
    return parameters


def _dataset(*, samples_per_cluster: int = 12, features: int = 8) -> SherpaDataset:
    rng = np.random.default_rng(20260812)
    centers = np.array([-3.0, 0.0, 3.0])
    matrix = np.vstack([rng.normal(loc=center, scale=0.16, size=(samples_per_cluster, features)) for center in centers])
    return SherpaDataset(
        X=matrix,
        sample_axis=SampleAxis(labels=[f"sample-{index:03d}" for index in range(matrix.shape[0])]),
        data_role="X_features",
    )


def test_hca_has_one_exact_local_fitted_model_contract() -> None:
    metadata = node_registry.get_metadata("model.hca")
    contract = metadata.resolved_execution_contract()

    assert contract is not None
    assert contract.payload["operation_id"] == "model.hca"
    assert contract.payload["runtime_family"] == RuntimeFamily.SHERPA_NATIVE.value
    assert contract.payload["lifecycle_kind"] == LifecycleKind.FITTED_MODEL.value
    assert contract.payload["managed_optimization_eligibility"] == (ManagedOptimizationEligibility.LOCAL.value,)
    assert contract.payload["fitted_state_serializer"] == HCA_STATE_SERIALIZER
    assert any("hclust" in citation for citation in contract.payload["citations"])


def test_hca_parameter_contract_is_closed_and_has_no_deprecated_metric_aliases() -> None:
    assert canonical_hca_parameters(_parameters()) == _parameters()
    for invalid in (
        {},
        _parameters(n_clusters=True),
        _parameters(n_clusters=1),
        _parameters(n_clusters=501),
        _parameters(linkage="centroid"),
        _parameters(metric="l1"),
        _parameters(metric="l2"),
        _parameters(linkage="ward", metric="manhattan"),
        {**_parameters(), "optimal_ordering": True},
    ):
        with pytest.raises(ValueError):
            canonical_hca_parameters(invalid)


@pytest.mark.asyncio
async def test_hca_live_generated_and_replay_paths_share_one_authority() -> None:
    dataset = _dataset()
    node = HCANode("hca", _parameters())

    live = await node.execute(input_data=dataset)
    namespace = {"dataset": dataset, "results": {}}
    exec("\n".join(node.generate_python({"default": "dataset"}, indent="")), namespace)  # noqa: S102
    generated = namespace["results"]["hca"]
    replayed = replay_hca_labels(dataset, live.outputs["model"])

    assert generated == {key: value for key, value in live.outputs.items() if key != "_model_artifact"}
    assert (
        json.loads(live.outputs["_model_artifact"]["arrays"]["native_fitted_state"].tobytes())["state"]
        == live.outputs["model"]
    )
    assert generated["labels"] == replayed.tolist()
    assert live.outputs["model"]["label_rule"] == HCA_LABEL_RULE
    assert live.outputs["model"]["embedding_method"] == HCA_EMBEDDING_RULE
    assert live.outputs["n_clusters"] == 3
    assert live.outputs["cluster_summary"] == [
        {
            "cluster": cluster,
            "count": 12,
            "fraction": pytest.approx(1.0 / 3.0),
            "sample_preview": [f"sample-{index:03d}" for index in range(cluster * 12, cluster * 12 + 10)],
            "preview_truncated": True,
        }
        for cluster in range(3)
    ]


def test_hca_state_fails_closed_and_cannot_assign_a_different_cohort() -> None:
    dataset = _dataset()
    state = fit_hca(dataset, parameters=_parameters())
    corruptions: list[dict[str, object]] = []

    extra = copy.deepcopy(state)
    extra["unexpected"] = True
    corruptions.append(extra)
    wrong_serializer = copy.deepcopy(state)
    wrong_serializer["schema_version"] = "spectrasherpa.model.hca-state/0"
    corruptions.append(wrong_serializer)
    wrong_labels = copy.deepcopy(state)
    wrong_labels["labels"] = wrong_labels["labels"][:-1]
    corruptions.append(wrong_labels)
    wrong_convention = copy.deepcopy(state)
    wrong_convention["label_rule"] = "scipy_incidental_labels"
    corruptions.append(wrong_convention)
    boolean_observed_count = copy.deepcopy(state)
    boolean_observed_count["observed_clusters"] = True
    corruptions.append(boolean_observed_count)
    hierarchy_mismatch = copy.deepcopy(state)
    hierarchy_mismatch["labels"] = hierarchy_mismatch["labels"][::-1]
    corruptions.append(hierarchy_mismatch)
    invalid_linkage = copy.deepcopy(state)
    invalid_linkage["linkage_matrix"][0][0] = 10_000.0
    corruptions.append(invalid_linkage)

    for corrupted in corruptions:
        with pytest.raises(ValueError):
            validate_hca_state(corrupted)
    different = np.array(dataset.X, copy=True)
    different[0, 0] += 1e-10
    with pytest.raises(ValueError, match="exact fitted cohort"):
        replay_hca_labels(different, state)


def test_hca_reports_requested_and_observed_clusters_without_overclaiming() -> None:
    matrix = np.array([[0.0], [0.0], [0.0], [1.0], [1.0], [1.0]])
    state = fit_hca(matrix, parameters=_parameters(n_clusters=4, linkage="complete"))

    assert state["requested_clusters"] == 4
    assert state["observed_clusters"] <= 4
    assert set(state["labels"]) == set(range(state["observed_clusters"]))


def test_hca_distance_guards_and_metric_specific_diagnostics_are_explicit() -> None:
    matrix = np.array([[0.0, 0.0], [1.0, 0.0], [0.0, 1.0]])
    with pytest.raises(ValueError, match="zero-norm"):
        fit_hca(matrix, parameters=_parameters(n_clusters=2, linkage="average", metric="cosine"))

    non_euclidean = fit_hca(
        matrix + 1.0,
        parameters=_parameters(n_clusters=2, linkage="average", metric="manhattan"),
    )
    assert non_euclidean["quality"]["silhouette_score"] is not None
    assert non_euclidean["quality"]["davies_bouldin_score"] is None
    assert non_euclidean["quality"]["davies_bouldin_reason"] == "euclidean_geometry_only"


def test_hca_fixed_local_workload_stays_inside_reviewed_ceiling() -> None:
    dataset = _dataset(samples_per_cluster=60, features=40)
    fit_hca(dataset, parameters=_parameters())

    with PerformanceCeiling("model.hca", "180x40-three-clusters", 5.0).measure():
        fit_hca(dataset, parameters=_parameters())
