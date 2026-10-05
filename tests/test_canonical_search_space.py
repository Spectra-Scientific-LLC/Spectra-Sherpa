"""M4.16a closed search-space tests against the saved-workbench baseline."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest

import spectra_sherpa.app.services.dag.nodes.data.loaders  # noqa: F401
import spectra_sherpa.app.services.dag.nodes.modeling  # noqa: F401
import spectra_sherpa.app.services.dag.nodes.preprocessing  # noqa: F401
import spectra_sherpa.app.services.dag.nodes.regression_evaluator_node  # noqa: F401
from spectra_sherpa.app.services.dag.canonical_search_space import (
    CanonicalSearchSpaceError,
    canonical_search_space_from_record,
    canonical_search_space_from_request,
)
from spectra_sherpa.app.services.dag.canonical_workbench_baseline import canonical_workbench_baseline_from_records
from spectra_sherpa.app.services.dag.integrity import compute_workflow_hash
from spectra_sherpa.app.types import type_registry


@dataclass
class _Node:
    node_id: str
    node_type: str
    parameters: dict[str, object]


@dataclass
class _Edge:
    from_node_id: str
    to_node_id: str
    from_output: str = "default"
    to_input: str = "default"


@pytest.fixture(autouse=True)
def _load_registry() -> None:
    if not type_registry.is_loaded:
        type_registry.load(Path(__file__).resolve().parents[1] / "src" / "spectra_sherpa" / "app" / "types")


def _baseline():
    nodes = [
        _Node(
            "source",
            "data.file_load",
            {
                "experiment_id": 11,
                "file_id": 12,
                "stage": "raw",
                "target_authority": {
                    "schema_version": "spectrasherpa-target-authority/1",
                    "column": "Moisture",
                    "target_type": "continuous",
                    "units": None,
                    "source_digest": "a" * 64,
                },
            },
        ),
        _Node("scale", "preprocess.scale", {"method": "autoscale", "center": True}),
        _Node("model", "model.fitted_pls", {"n_components": 2, "scale": True}),
        _Node("score", "diagnostics.regression_evaluator", {}),
    ]
    edges = [_Edge("source", "scale"), _Edge("scale", "model"), _Edge("model", "score")]
    integrity = compute_workflow_hash(
        [{"node_id": node.node_id, "node_type": node.node_type, "parameters": node.parameters} for node in nodes],
        [
            {
                "from_node_id": edge.from_node_id,
                "to_node_id": edge.to_node_id,
                "from_output": edge.from_output,
                "to_input": edge.to_input,
            }
            for edge in edges
        ],
    )
    return canonical_workbench_baseline_from_records(
        workflow_id=9,
        stored_integrity_hash=integrity,
        nodes=nodes,
        edges=edges,
    )


def test_search_space_enumerates_baseline_and_parameter_grid_deterministically() -> None:
    baseline = _baseline()
    space = canonical_search_space_from_request(
        baseline,
        {
            "slots": [
                {"node_id": "model", "parameter": "n_components", "values": [3, 1]},
                {"node_id": "model", "parameter": "scale", "values": [True, False]},
            ],
            "validation_budget": 5,
            "minimum_improvement": 0.0,
        },
    )

    assert [candidate.candidate_id for candidate in space.candidates] == [
        "canonical-baseline-001",
        "canonical-grid-002",
        "canonical-grid-003",
        "canonical-grid-004",
        "canonical-grid-005",
    ]
    assert space.candidates[0].graph.digest == baseline.graph.digest
    assert all(candidate.graph.digest != baseline.graph.digest for candidate in space.candidates[1:])
    assert space.as_dict()["candidate_count"] == 5
    assert space.as_dict()["mutable_slots"] == [
        {"node_id": "model", "parameter": "n_components", "values": [1, 3]},
        {"node_id": "model", "parameter": "scale", "values": [False, True]},
    ]
    assert len(space.digest) == 64


def test_stored_search_space_is_rebuilt_from_slots_not_trusted_candidate_json() -> None:
    baseline = _baseline()
    space = canonical_search_space_from_request(
        baseline,
        {
            "slots": [{"node_id": "model", "parameter": "n_components", "values": [1, 3]}],
            "validation_budget": 3,
            "minimum_improvement": 0.0,
        },
    )
    restored = canonical_search_space_from_record(baseline, space.as_dict())
    assert restored.as_dict() == space.as_dict()

    forged = space.as_dict()
    candidates = forged["candidates"]
    assert isinstance(candidates, list)
    candidates[1]["graph_digest"] = "0" * 64
    with pytest.raises(CanonicalSearchSpaceError, match="candidate identities"):
        canonical_search_space_from_record(baseline, forged)


@pytest.mark.parametrize(
    ("search_request", "message"),
    [
        (
            {
                "slots": [{"node_id": "missing", "parameter": "n_components", "values": [3]}],
                "validation_budget": 2,
                "minimum_improvement": 0.0,
            },
            "outside the saved baseline",
        ),
        (
            {
                "slots": [{"node_id": "model", "parameter": "unexpected", "values": [3]}],
                "validation_budget": 2,
                "minimum_improvement": 0.0,
            },
            "absent from the saved baseline",
        ),
        (
            {
                "slots": [{"node_id": "model", "parameter": "n_components", "values": [0]}],
                "validation_budget": 2,
                "minimum_improvement": 0.0,
            },
            "outside the admitted scientific envelope",
        ),
        (
            {
                "slots": [{"node_id": "model", "parameter": "n_components", "values": [2]}],
                "validation_budget": 2,
                "minimum_improvement": 0.0,
            },
            "duplicate scientific candidate identities",
        ),
        (
            {
                "slots": [{"node_id": "model", "parameter": "n_components", "values": [3]}],
                "validation_budget": 3,
                "minimum_improvement": 0.0,
            },
            "exactly cover",
        ),
    ],
)
def test_search_space_rejects_undeclared_or_non_distinct_variation(search_request, message) -> None:
    with pytest.raises(CanonicalSearchSpaceError, match=message):
        canonical_search_space_from_request(_baseline(), search_request)


def test_search_space_cannot_mutate_topology_contract_or_dependency() -> None:
    baseline = _baseline()
    with pytest.raises(CanonicalSearchSpaceError, match="fields are not closed"):
        canonical_search_space_from_request(
            baseline,
            {
                "slots": [{"node_id": "model", "parameter": "n_components", "values": [3]}],
                "validation_budget": 2,
                "minimum_improvement": 0.0,
                "nodes": [{"node_id": "attacker", "operation_id": "model.fitted_pls"}],
            },
        )
    with pytest.raises(CanonicalSearchSpaceError, match="fields are not closed"):
        canonical_search_space_from_request(
            baseline,
            {
                "slots": [
                    {
                        "node_id": "model",
                        "parameter": "n_components",
                        "values": [3],
                        "contract_digest": "0" * 64,
                    }
                ],
                "validation_budget": 2,
                "minimum_improvement": 0.0,
            },
        )


@pytest.mark.parametrize("margin", [-0.1, float("nan"), float("inf"), "0.1", True, None])
def test_search_space_rejects_an_indefensible_selection_margin(margin) -> None:
    """The declared margin must be a finite, non-negative, numeric value."""

    with pytest.raises(CanonicalSearchSpaceError, match="minimum primary-metric improvement"):
        canonical_search_space_from_request(
            _baseline(),
            {
                "slots": [{"node_id": "model", "parameter": "n_components", "values": [3]}],
                "validation_budget": 2,
                "minimum_improvement": margin,
            },
        )


def test_declared_margin_is_bound_into_the_search_space_identity() -> None:
    """Two spaces differing only by margin are different admitted objects.

    The margin has to be part of the digest, otherwise an operator could admit
    a strict bar, observe the scores, and re-present the same space under a
    laxer one without the identity changing.
    """

    baseline = _baseline()
    request = {
        "slots": [{"node_id": "model", "parameter": "n_components", "values": [1, 3]}],
        "validation_budget": 3,
    }
    strict = canonical_search_space_from_request(baseline, {**request, "minimum_improvement": 0.05})
    lax = canonical_search_space_from_request(baseline, {**request, "minimum_improvement": 0.0})

    assert strict.digest != lax.digest
    strategy = strict.as_dict()["strategy"]
    assert strategy["selection_policy"]["minimum_improvement"] == 0.05
    assert strategy["selection_policy"]["content_digest"] == strict.selection_policy.content_digest
    # And the stored form must round-trip its own margin, not silently adopt one.
    assert canonical_search_space_from_record(baseline, strict.as_dict()).digest == strict.digest
    with pytest.raises(CanonicalSearchSpaceError):
        canonical_search_space_from_record(baseline, {**strict.as_dict(), "minimum_improvement": 0.0})
