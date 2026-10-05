"""C2k canonical feature-selection comparison proofs."""

from __future__ import annotations

import copy
import math

import numpy as np
import pytest

import spectra_sherpa.app.services.dag.nodes  # noqa: F401 - populate built-ins
from spectra_sherpa.app.lib.sherpa_dataset import SampleAxis, SherpaDataset, SpectralAxis
from spectra_sherpa.app.services.dag.node_base import node_registry
from spectra_sherpa.app.services.dag.nodes.selection.compare_selections_node import (
    CompareSelectionsNode,
    _canonical_compare_parameters,
    _compare_dispatch,
)
from spectra_sherpa.execution_contract_vocabulary import LifecycleKind, ManagedOptimizationEligibility, RuntimeFamily
from tests.performance_contract import PerformanceCeiling


@pytest.fixture
def comparison_data() -> SherpaDataset:
    matrix = np.arange(48, dtype=np.float64).reshape(6, 8)
    return SherpaDataset(
        X=matrix,
        feature_axis=SpectralAxis(
            values=np.linspace(900.0, 1600.0, 8),
            labels=[f"band-{index}" for index in range(8)],
            units="cm-1",
        ),
        sample_axis=SampleAxis(labels=[f"sample-{index}" for index in range(6)]),
    )


def test_compare_has_one_exact_local_stateless_contract() -> None:
    metadata = node_registry.get_metadata("selection.compare")
    contract = metadata.resolved_execution_contract()

    assert contract is not None
    assert contract.payload["operation_id"] == "selection.compare"
    assert contract.payload["runtime_family"] == RuntimeFamily.SHERPA_NATIVE.value
    assert contract.payload["lifecycle_kind"] == LifecycleKind.STATELESS_TRANSFORM.value
    assert contract.payload["implementation_id"] == "spectrasherpa.selection.compare"
    assert contract.payload["managed_optimization_eligibility"] == (ManagedOptimizationEligibility.LOCAL.value,)
    assert contract.payload["target_access"] == "none"
    assert contract.payload["deterministic"] is True
    assert any("10.5169/seals-266450" in citation for citation in contract.payload["citations"])


@pytest.mark.parametrize(
    "parameters",
    [
        {"other": 1},
        {"consensus_threshold": True},
        {"consensus_threshold": 0.0},
        {"consensus_threshold": -0.1},
        {"consensus_threshold": 1.01},
        {"consensus_threshold": float("nan")},
    ],
)
def test_compare_parameters_are_closed(parameters: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        _canonical_compare_parameters(parameters)


def test_compare_matches_independent_vote_and_jaccard_oracle() -> None:
    masks = [
        np.array([True, True, False, False, True, False]),
        np.array([True, False, True, False, True, False]),
        np.array([False, True, True, False, True, False]),
    ]
    result = _compare_dispatch(masks, consensus_threshold=0.5)

    vote_counts = np.array([2, 2, 2, 0, 3, 0])
    required = math.ceil(0.5 * len(masks))
    oracle_jaccard = np.empty((3, 3), dtype=np.float64)
    for left in range(3):
        for right in range(3):
            intersection = np.count_nonzero(masks[left] & masks[right])
            union = np.count_nonzero(masks[left] | masks[right])
            oracle_jaccard[left, right] = 0.0 if union == 0 else intersection / union

    np.testing.assert_array_equal(result["vote_counts"], vote_counts)
    assert result["required_votes"] == required == 2
    np.testing.assert_array_equal(result["consensus_mask"], vote_counts >= required)
    np.testing.assert_allclose(result["jaccard_matrix"], oracle_jaccard, rtol=0.0, atol=0.0)
    assert result["mean_pairwise_jaccard"] == pytest.approx(float(np.mean(oracle_jaccard[np.triu_indices(3, k=1)])))


def test_compare_has_a_representative_absolute_performance_ceiling() -> None:
    rng = np.random.default_rng(506)
    masks = [rng.random(50_000) < (0.20 + 0.02 * index) for index in range(4)]

    with PerformanceCeiling("selection.compare", "four-masks-by-50000-features", 5.0).measure():
        result = _compare_dispatch(masks, consensus_threshold=0.5)

    assert result["vote_counts"].shape == (50_000,)
    assert result["jaccard_matrix"].shape == (4, 4)


def test_half_with_two_methods_is_explicitly_inclusive_not_majority() -> None:
    first = np.array([True, False, False])
    second = np.array([False, True, False])
    result = _compare_dispatch([first, second], consensus_threshold=0.5)

    assert result["required_votes"] == 1
    np.testing.assert_array_equal(result["consensus_mask"], [True, True, False])


@pytest.mark.asyncio
async def test_compare_rejects_coerced_or_misaligned_masks(comparison_data: SherpaDataset) -> None:
    valid = np.array([True, False, True, False, True, False, True, False])
    invalid_values = (
        np.array([1, 0, 1, 0, 1, 0, 1, 0]),
        valid.reshape(2, 4),
        valid[:-1],
        "10101010",
    )
    for invalid in invalid_values:
        with pytest.raises(ValueError, match="boolean mask|elements"):
            await CompareSelectionsNode("compare", {}).execute(
                X=comparison_data,
                mask_1=valid,
                mask_2=invalid,
            )


@pytest.mark.asyncio
async def test_compare_preserves_input_axis_labels_and_records_closed_decision(
    comparison_data: SherpaDataset,
) -> None:
    source = copy.deepcopy(comparison_data)
    first = np.array([True, True, False, False, True, False, False, False])
    second = np.array([True, False, True, False, True, False, False, False])
    result = await CompareSelectionsNode("compare", {"consensus_threshold": 1.0}).execute(
        X=comparison_data,
        mask_1=first,
        mask_2=second,
    )

    selected = result.outputs["X_consensus"]
    report = result.outputs["report"]
    np.testing.assert_array_equal(selected.X, comparison_data.X[:, [0, 4]])
    np.testing.assert_array_equal(selected.feature_axis.values, comparison_data.feature_axis.values[[0, 4]])
    assert selected.feature_axis.labels == ["band-0", "band-4"]
    assert selected.feature_axis.units == "cm-1"
    assert selected.meta["feature_mask"] == [True, False, False, False, True, False, False, False]
    assert report["schema_version"] == "spectrasherpa.selection.compare.report/1"
    assert report["decision_rule"] == ("selected_votes_greater_than_or_equal_to_ceiling_of_threshold_times_methods")
    assert report["required_votes"] == 2
    assert report["scope"] == "selector_agreement_record_not_predictive_performance_evidence"
    assert len(report["consensus_mask_sha256"]) == 64
    assert all(len(entry["mask_sha256"]) == 64 for entry in report["method_stats"])
    assert [entry["mask"] for entry in report["input_masks"]] == [first.tolist(), second.tolist()]
    replayed = _compare_dispatch(
        [np.asarray(entry["mask"], dtype=bool) for entry in report["input_masks"]],
        consensus_threshold=report["consensus_threshold"],
    )
    np.testing.assert_array_equal(replayed["consensus_mask"], report["consensus_mask"])
    np.testing.assert_allclose(replayed["jaccard_matrix"], report["jaccard_matrix"], rtol=0.0, atol=0.0)
    np.testing.assert_array_equal(comparison_data.X, source.X)
    np.testing.assert_array_equal(comparison_data.feature_axis.values, source.feature_axis.values)
    assert comparison_data.feature_axis.labels == source.feature_axis.labels


@pytest.mark.asyncio
async def test_compare_live_and_generated_python_share_one_operation(comparison_data: SherpaDataset) -> None:
    first = np.array([True, True, False, False, True, False, True, False])
    second = np.array([True, False, True, False, True, False, False, True])
    third = np.array([True, True, True, False, False, False, False, False])
    node = CompareSelectionsNode("compare", {"consensus_threshold": 0.6})
    live = await node.execute(X=comparison_data, mask_1=first, mask_2=second, mask_3=third)
    namespace = {
        "dataset": comparison_data,
        "first": first,
        "second": second,
        "third": third,
        "results": {},
    }
    exec(  # noqa: S102
        "\n".join(
            node.generate_python(
                {"X": "dataset", "mask_1": "first", "mask_2": "second", "mask_3": "third"},
                indent="",
            )
        ),
        namespace,
    )
    generated = namespace["results"]["compare"]

    np.testing.assert_array_equal(generated["consensus_mask"], live.outputs["consensus_mask"])
    np.testing.assert_array_equal(generated["X_consensus"].X, live.outputs["X_consensus"].X)
    assert generated["report"] == live.outputs["report"]


@pytest.mark.asyncio
async def test_compare_rejects_empty_consensus(comparison_data: SherpaDataset) -> None:
    first = np.array([True, False, False, False, False, False, False, False])
    second = np.array([False, True, False, False, False, False, False, False])
    with pytest.raises(ValueError, match="retained no variables"):
        await CompareSelectionsNode("compare", {"consensus_threshold": 1.0}).execute(
            X=comparison_data,
            mask_1=first,
            mask_2=second,
        )
