"""Records from the profile before baseline non-convergence warnings stay read-only."""

from __future__ import annotations

from pathlib import Path

import pytest

import spectra_sherpa.app.services.dag.nodes  # noqa: F401
from spectra_sherpa.app.services.dag.executor_types import WorkflowNode
from spectra_sherpa.app.services.dag.historical_contracts import HistoricalReconstructionContext
from spectra_sherpa.app.services.dag.node_base import node_registry
from spectra_sherpa.app.services.dag.validation_graph import (
    ValidationGraphError,
    assert_admitted_validation_graph,
    validation_graph_from_dict,
)
from spectra_sherpa.app.types import type_registry
from spectra_sherpa.core.contract_compatibility import inspection_predecessor_catalog

OPERATION = "baseline.penalized_ls"
PROFILE = "61b569f87ff357307444ec60e1f8adbf1f6a3e0e1555408e73d6756f6ed919ed"
OLD = "3572299978c258b77523d201247340fc62dce738c2feff9357583016f37574c1"
OLDEST = "b3b824ef38585a9f7e1e673f2369f03c3d2e4900028168f79948aa35592095da"
NEW = "6d0ba8461fa1aba633e96a9def01514785bff4f68bc6f90091116f3c944ad599"
PROFILES = (
    PROFILE,
    "d82af6a5a5b9922b1c57531d3ce9d121ad6e7c6f80ee3dc6bb24119f6b2f24c9",
    "eec02d6f13ac5b5fa1af45dfea754b0c054faf1c92d75cf9af88ec74ac066cdb",
    "af74c1883601c4db7943953a864eb319794e19cebf5b303ef3f67ac858714336",
    "a90673771ee6f54d95591e8eb9cd56470dca68dae5a319a58936552d77a96140",
    "9f37d08a914c3e276859c0ba10b5d2187d5d5ba4ff85f6d00b35cba23e7369f4",
    None,
)
PARAMETERS = {"method": "arpls", "lam": 1e5, "p": 0.001, "max_iter": 50, "tol": 1e-6}


@pytest.fixture(autouse=True)
def load_type_registry():
    if not type_registry.is_loaded:
        type_registry.load(Path(__file__).resolve().parents[1] / "src/spectra_sherpa/app/types")


def _current():
    return node_registry.get_metadata(OPERATION).resolved_execution_contract()


def test_current_node_is_the_exact_reviewed_consumer():
    assert _current().digest == NEW


@pytest.mark.parametrize("profile_digest", PROFILES)
def test_every_registered_profile_preserves_its_recorded_identity(profile_digest):
    catalog = inspection_predecessor_catalog(profile_digest)
    context = HistoricalReconstructionContext(profile_digest)
    profile = context.profile()

    assert profile.digest == catalog["profile"]["profile_digest"]
    assert {c.payload["operation_id"]: c.digest for c in profile.contracts} == catalog["profile"]["operations"]
    identity = {key: catalog["profile"][key] for key in ("profile_id", "profile_version", "profile_digest")}
    assert context.require_profile(identity).digest == profile.digest


def test_deployed_profile_differs_only_by_implementation_source():
    archived = HistoricalReconstructionContext(PROFILE).contract(OPERATION, OLD)
    current = _current()

    assert archived.digest == OLD
    assert {key for key in archived.payload if archived.payload[key] != current.payload[key]} == {
        "implementation_components",
        "implementation_digest",
    }


def test_deployed_graph_reconstructs_read_only_and_cannot_execute():
    context = HistoricalReconstructionContext(PROFILE)
    graph = context.reconstruct([WorkflowNode("baseline", OPERATION, PARAMETERS)], [])

    assert [node.contract.digest for node in graph.nodes] == [OLD]
    context.require_historical_graph(graph)
    assert context.graph(graph.as_dict()).digest == graph.digest
    with pytest.raises(ValidationGraphError):
        assert_admitted_validation_graph(graph)
    with pytest.raises(ValidationGraphError):
        validation_graph_from_dict(graph.as_dict())


@pytest.mark.parametrize("digest", [NEW, OLDEST, "f" * 64])
def test_deployed_profile_refuses_other_baseline_identities(digest):
    with pytest.raises(ValidationGraphError):
        HistoricalReconstructionContext(PROFILE).contract(OPERATION, digest)


def test_consumer_rule_requires_the_profile_to_record_that_contract():
    with pytest.raises(ValidationGraphError):
        HistoricalReconstructionContext("9f37d08a914c3e276859c0ba10b5d2187d5d5ba4ff85f6d00b35cba23e7369f4").contract(
            OPERATION, OLD
        )


def test_unknown_profile_is_still_refused():
    with pytest.raises(ValueError):
        inspection_predecessor_catalog("f" * 64)
