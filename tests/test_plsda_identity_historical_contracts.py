"""Read-only historical identity remains distinct from current execution."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

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

OLD = "65017fa4efd2c518f7f07dbdd12c332cb472b13ee6b734b69f4c9569aa445b7f"
NEW = "b4910376c363b3564a1fb959b52ab75ca93b7744f5b15d19caa582258ca43f43"
PROFILE = "d82af6a5a5b9922b1c57531d3ce9d121ad6e7c6f80ee3dc6bb24119f6b2f24c9"
PROFILES = (
    None,
    "9f37d08a914c3e276859c0ba10b5d2187d5d5ba4ff85f6d00b35cba23e7369f4",
    "eec02d6f13ac5b5fa1af45dfea754b0c054faf1c92d75cf9af88ec74ac066cdb",
    "af74c1883601c4db7943953a864eb319794e19cebf5b303ef3f67ac858714336",
    "a90673771ee6f54d95591e8eb9cd56470dca68dae5a319a58936552d77a96140",
    PROFILE,
)


@pytest.fixture(autouse=True)
def load_type_registry():
    if not type_registry.is_loaded:
        type_registry.load(Path(__file__).resolve().parents[1] / "src/spectra_sherpa/app/types")


@pytest.mark.parametrize("profile_digest", PROFILES)
def test_all_six_profiles_preserve_recorded_identity(profile_digest):
    catalog = inspection_predecessor_catalog(profile_digest)
    context = HistoricalReconstructionContext(profile_digest)
    profile = context.profile()
    assert profile.digest == catalog["profile"]["profile_digest"]
    assert {c.payload["operation_id"]: c.digest for c in profile.contracts} == catalog["profile"]["operations"]
    identity = {k: catalog["profile"][k] for k in ("profile_id", "profile_version", "profile_digest")}
    assert context.require_profile(identity).digest == profile.digest
    with pytest.raises(ValidationGraphError, match="unknown historical managed profile"):
        context.require_profile({**identity, "profile_digest": "f" * 64})


def test_new_history_retains_current_pls_controls_and_has_no_classifier_output_exception():
    context = HistoricalReconstructionContext(PROFILE)
    assert context.added_pls_parameters() == set()
    assert not context.predates_automatic_pls
    assert not context.predates_grouped_cv
    assert not context.predates_preprocessing_expansion
    archived = context.contract("classification.plsda", OLD)
    current = node_registry.get_metadata("classification.plsda").resolved_execution_contract()
    assert current.digest == NEW
    assert {k for k in archived.payload if archived.payload[k] != current.payload[k]} == {
        "implementation_components",
        "implementation_digest",
    }
    # PLS controls already existed in v9 and must not be stripped by this reader.
    graph = context.reconstruct(
        [WorkflowNode("pls", "model.fitted_pls", {"component_fit_mode": "one_standard_error"})], []
    )
    assert graph.nodes[0].parameters["component_fit_mode"] == "one_standard_error"
    with pytest.raises(ValidationGraphError, match="historical or noncanonical"):
        assert_admitted_validation_graph(graph, require_live_runtime=False)


def test_plsda_historical_graph_is_inspectable_but_not_executable():
    context = HistoricalReconstructionContext(PROFILE)
    graph = context.reconstruct([WorkflowNode("fit", "classification.plsda", {})], [])
    wire = graph.as_dict()
    assert wire["nodes"][0]["contract_digest"] == OLD
    assert context.graph(wire).as_dict() == wire
    with pytest.raises(ValidationGraphError, match="historical or noncanonical"):
        assert_admitted_validation_graph(graph, require_live_runtime=False)
    with pytest.raises(ValidationGraphError):
        validation_graph_from_dict(wire, require_live_runtime=False)
    changed = deepcopy(wire)
    changed["nodes"][0]["contract_digest"] = NEW
    with pytest.raises(ValidationGraphError, match="mixes unsupported profile"):
        context.graph(changed)


@pytest.mark.parametrize("profile_digest", PROFILES)
def test_unknown_current_consumer_is_not_admitted(profile_digest, monkeypatch):
    context = HistoricalReconstructionContext(profile_digest)
    digest = inspection_predecessor_catalog(profile_digest)["profile"]["operations"]["classification.plsda"]
    metadata = node_registry.get_metadata("classification.plsda")
    current = metadata.resolved_execution_contract()
    monkeypatch.setattr(
        metadata, "resolved_execution_contract", lambda: SimpleNamespace(digest="f" * 64, payload=current.payload)
    )
    with pytest.raises(ValidationGraphError):
        context.contract("classification.plsda", digest)


@pytest.mark.parametrize(
    "field",
    [
        "semantic_outputs",
        "parameter_schema_digest",
        "fitted_state_serializer",
        "runtime_requirements",
        "implementation_version",
    ],
)
def test_new_history_checks_declarations_even_for_exact_consumer(field, monkeypatch):
    context = HistoricalReconstructionContext(PROFILE)
    metadata = node_registry.get_metadata("classification.plsda")
    current = metadata.resolved_execution_contract()
    payload = dict(current.payload)
    payload[field] = () if field in {"semantic_outputs", "runtime_requirements"} else "altered"
    monkeypatch.setattr(metadata, "resolved_execution_contract", lambda: SimpleNamespace(digest=NEW, payload=payload))
    with pytest.raises(ValidationGraphError, match="scientific declarations changed"):
        context.contract("classification.plsda", OLD)


def test_unknown_profile_and_wrong_predecessor_are_refused():
    with pytest.raises(ValueError, match="unrecognized historical inspection profile"):
        HistoricalReconstructionContext("f" * 64)
    context = HistoricalReconstructionContext(PROFILE)
    for digest in (NEW, "f" * 64):
        with pytest.raises(ValidationGraphError):
            context.contract("classification.plsda", digest)
