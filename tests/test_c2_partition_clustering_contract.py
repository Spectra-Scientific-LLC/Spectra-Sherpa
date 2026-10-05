"""Canonical K-means and DBSCAN scientific, state, projection, and cost proofs."""

from __future__ import annotations

import copy
import json

import numpy as np
import pytest
from sklearn.cluster import DBSCAN, KMeans

import spectra_sherpa.app.services.dag.nodes  # noqa: F401 - populate built-ins
from spectra_sherpa.app.lib.sherpa_dataset import SampleAxis, SherpaDataset
from spectra_sherpa.app.services.dag.node_base import node_registry
from spectra_sherpa.app.services.dag.nodes.modeling.clustering_nodes import DBSCANNode, KMeansNode
from spectra_sherpa.app.services.dag.nodes.modeling.partition_clustering_core import (
    DBSCAN_APPLICATION_SCOPE,
    DBSCAN_STATE_SERIALIZER,
    KMEANS_PREDICTION_RULE,
    KMEANS_STATE_SERIALIZER,
    canonical_dbscan_parameters,
    canonical_kmeans_parameters,
    fit_dbscan,
    fit_kmeans,
    replay_dbscan_labels,
    validate_dbscan_state,
    validate_kmeans_state,
)
from spectra_sherpa.execution_contract_vocabulary import LifecycleKind, ManagedOptimizationEligibility
from tests.performance_contract import PerformanceCeiling


def _dataset(*, samples_per_cluster: int = 14, features: int = 10) -> SherpaDataset:
    rng = np.random.default_rng(20260813)
    matrix = np.vstack(
        [rng.normal(loc=center, scale=0.08, size=(samples_per_cluster, features)) for center in (-3.0, 0.0, 3.0)]
    )
    return SherpaDataset(
        X=matrix,
        sample_axis=SampleAxis(labels=[f"sample-{index:03d}" for index in range(matrix.shape[0])]),
        data_role="X_features",
    )


def _kmeans_parameters(**overrides: object) -> dict[str, object]:
    result: dict[str, object] = {"n_clusters": 3, "n_init": 10, "max_iter": 300, "random_state": 42}
    result.update(overrides)
    return result


def _dbscan_parameters(**overrides: object) -> dict[str, object]:
    result: dict[str, object] = {"eps": 0.45, "min_samples": 4, "metric": "euclidean"}
    result.update(overrides)
    return result


@pytest.mark.parametrize(
    ("node_type", "serializer", "citation_term"),
    [
        ("model.kmeans", KMEANS_STATE_SERIALIZER, "MacQueen"),
        ("model.dbscan", DBSCAN_STATE_SERIALIZER, "Ester"),
    ],
)
def test_partition_clustering_nodes_have_exact_local_fitted_model_contracts(
    node_type: str,
    serializer: str,
    citation_term: str,
) -> None:
    contract = node_registry.get_metadata(node_type).resolved_execution_contract()

    assert contract is not None
    assert contract.payload["operation_id"] == node_type
    assert contract.payload["lifecycle_kind"] == LifecycleKind.FITTED_MODEL.value
    assert contract.payload["managed_optimization_eligibility"] == (ManagedOptimizationEligibility.LOCAL.value,)
    assert contract.payload["fitted_state_serializer"] == serializer
    assert any(citation_term in citation for citation in contract.payload["citations"])


def test_partition_clustering_parameter_contracts_are_closed() -> None:
    assert canonical_kmeans_parameters(_kmeans_parameters()) == _kmeans_parameters()
    assert canonical_dbscan_parameters(_dbscan_parameters()) == _dbscan_parameters()
    for invalid in (
        {},
        _kmeans_parameters(n_clusters=True),
        _kmeans_parameters(n_clusters=1),
        _kmeans_parameters(n_init=101),
        _kmeans_parameters(max_iter=0),
        _kmeans_parameters(random_state=-1),
        {**_kmeans_parameters(), "algorithm": "elkan"},
    ):
        with pytest.raises(ValueError):
            canonical_kmeans_parameters(invalid)
    for invalid in (
        {},
        _dbscan_parameters(eps=0.0),
        _dbscan_parameters(eps=True),
        _dbscan_parameters(min_samples=1),
        _dbscan_parameters(metric="l1"),
        _dbscan_parameters(metric="l2"),
        {**_dbscan_parameters(), "algorithm": "auto"},
    ):
        with pytest.raises(ValueError):
            canonical_dbscan_parameters(invalid)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("node_class", "parameters", "serializer"),
    [
        (KMeansNode, _kmeans_parameters(), KMEANS_STATE_SERIALIZER),
        (DBSCANNode, _dbscan_parameters(), DBSCAN_STATE_SERIALIZER),
    ],
)
async def test_partition_clustering_live_and_generated_paths_share_one_authority(
    node_class,
    parameters: dict[str, object],
    serializer: str,
) -> None:
    dataset = _dataset()
    node = node_class("cluster", parameters)

    live = await node.execute(input_data=dataset)
    namespace = {"dataset": dataset, "results": {}}
    exec("\n".join(node.generate_python({"default": "dataset"}, indent="")), namespace)  # noqa: S102

    assert namespace["results"]["cluster"] == {
        key: value for key, value in live.outputs.items() if key != "_model_artifact"
    }
    assert (
        json.loads(live.outputs["_model_artifact"]["arrays"]["native_fitted_state"].tobytes())["state"]
        == live.outputs["model"]
    )
    assert live.outputs["model"]["schema_version"] == serializer
    assert live.outputs["labels"] == live.outputs["cluster_assignment"]
    assert len(live.outputs["embedding"]) == len(dataset.X)
    visualization = live.outputs["visualization"]
    assert sum(len(trace["x"]) for trace in visualization["data"]) == dataset.n_samples
    assert visualization["layout"]["xaxis"]["title"]["text"] == "Centered-SVD component 1"
    assert visualization["layout"]["yaxis"]["title"]["text"] == "Centered-SVD component 2"
    assert "clustering used the full input space" in visualization["layout"]["title"]["text"]
    assert visualization["layout"]["margin"]["t"] >= 80
    assert visualization["layout"]["showlegend"] is True
    assert {sample_label for trace in visualization["data"] for sample_label in trace["text"]} == set(
        dataset.sample_axis.labels
    )
    assert live.outputs["metadata"]["sample_labels"] == dataset.sample_axis.labels


def test_kmeans_matches_reference_partition_and_applies_nearest_centroid_state() -> None:
    dataset = _dataset()
    parameters = _kmeans_parameters()
    state = fit_kmeans(dataset, parameters=parameters)
    reference = KMeans(**parameters, algorithm="lloyd", tol=1e-4).fit_predict(dataset.X)
    actual = np.asarray(state["labels"])

    np.testing.assert_array_equal(actual[:, None] == actual[None, :], reference[:, None] == reference[None, :])
    new_samples = np.array([[-3.1] * dataset.X.shape[1], [3.1] * dataset.X.shape[1]])
    assigned = KMeansNode("kmeans", parameters).apply_fitted_state(new_samples, state)
    distances = np.sum(
        np.square(new_samples[:, None, :] - np.asarray(state["centroids"])[None, :, :]),
        axis=2,
    )
    np.testing.assert_array_equal(assigned, np.argmin(distances, axis=1))
    assert state["prediction_rule"] == KMEANS_PREDICTION_RULE


def test_dbscan_matches_reference_partition_but_replays_only_the_fitted_cohort() -> None:
    dataset = _dataset()
    parameters = _dbscan_parameters()
    state = fit_dbscan(dataset, parameters=parameters)
    reference = DBSCAN(**parameters).fit_predict(dataset.X)
    actual = np.asarray(state["labels"])

    np.testing.assert_array_equal(actual == -1, reference == -1)
    np.testing.assert_array_equal(actual[:, None] == actual[None, :], reference[:, None] == reference[None, :])
    np.testing.assert_array_equal(replay_dbscan_labels(dataset, state), actual)
    changed = np.array(dataset.X, copy=True)
    changed[0, 0] += 1e-12
    with pytest.raises(ValueError, match="exact fitted cohort"):
        replay_dbscan_labels(changed, state)
    assert state["application_scope"] == DBSCAN_APPLICATION_SCOPE
    assert state["quality"]["population"] == "non_noise_samples_only"


def test_dbscan_rejects_cosine_distance_for_zero_norm_observations() -> None:
    with pytest.raises(ValueError, match="zero-norm"):
        fit_dbscan(
            np.array([[0.0, 0.0], [1.0, 0.0], [0.9, 0.1]]),
            parameters=_dbscan_parameters(metric="cosine"),
        )


@pytest.mark.asyncio
async def test_dbscan_accepts_its_own_all_noise_fitted_state() -> None:
    dataset = _dataset()
    parameters = _dbscan_parameters(eps=0.01, min_samples=4)
    state = fit_dbscan(dataset, parameters=parameters)
    result = await DBSCANNode("dbscan", parameters).execute(input_data=dataset)

    assert state["core_sample_indices"] == []
    assert state["noise_count"] == dataset.n_samples
    visualization = result.outputs["visualization"]
    assert visualization["layout"]["showlegend"] is True
    assert [trace["name"] for trace in visualization["data"]] == ["Noise"]
    np.testing.assert_array_equal(replay_dbscan_labels(dataset, state), -np.ones(dataset.n_samples, dtype=int))


def test_dbscan_rejects_nonempty_fractional_core_indices() -> None:
    state = fit_dbscan(_dataset(), parameters=_dbscan_parameters())
    state["core_sample_indices"] = [0.5]

    with pytest.raises(ValueError, match="core indices must be integers"):
        validate_dbscan_state(state)


@pytest.mark.parametrize(
    ("fit", "validate", "parameters"),
    [
        (fit_kmeans, validate_kmeans_state, _kmeans_parameters()),
        (fit_dbscan, validate_dbscan_state, _dbscan_parameters()),
    ],
)
def test_partition_clustering_states_fail_closed(fit, validate, parameters: dict[str, object]) -> None:
    state = fit(_dataset(), parameters=parameters)
    extra = copy.deepcopy(state)
    extra["unexpected"] = True
    wrong_schema = copy.deepcopy(state)
    wrong_schema["schema_version"] += "-forged"
    shortened_labels = copy.deepcopy(state)
    shortened_labels["labels"] = shortened_labels["labels"][:-1]
    for corruption in (extra, wrong_schema, shortened_labels):
        with pytest.raises(ValueError):
            validate(corruption)


def test_partition_clustering_fixed_workloads_stay_inside_reviewed_ceiling() -> None:
    dataset = _dataset(samples_per_cluster=60, features=40)
    fit_kmeans(dataset, parameters=_kmeans_parameters())
    fit_dbscan(dataset, parameters=_dbscan_parameters())

    with PerformanceCeiling("model.kmeans", "180x40-three-clusters", 5.0).measure():
        fit_kmeans(dataset, parameters=_kmeans_parameters())
    with PerformanceCeiling("model.dbscan", "180x40-three-clusters", 5.0).measure():
        fit_dbscan(dataset, parameters=_dbscan_parameters())
