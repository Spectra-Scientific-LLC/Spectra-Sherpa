"""M4.5b admission tests for the canonical validation-only DAG shape."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

import spectra_sherpa.app.services.dag.nodes.data.loaders  # noqa: F401
import spectra_sherpa.app.services.dag.nodes.modeling  # noqa: F401
import spectra_sherpa.app.services.dag.nodes.preprocessing  # noqa: F401
import spectra_sherpa.app.services.dag.nodes.regression_evaluator_node  # noqa: F401
from spectra_sherpa.app.services.dag import managed_optimization_profile as managed_optimization_profile_module
from spectra_sherpa.app.services.dag import validation_graph as validation_graph_module
from spectra_sherpa.app.services.dag.executor_types import WorkflowEdge, WorkflowNode
from spectra_sherpa.app.services.dag.managed_optimization_profile import (
    ManagedOptimizationProfileError,
    managed_optimization_profile,
)
from spectra_sherpa.app.services.dag.node_base import node_registry
from spectra_sherpa.app.services.dag.stable_execution_contract import implementation_digest_for_components
from spectra_sherpa.app.services.dag.validation_graph import (
    ValidationContractError,
    ValidationGraph,
    ValidationGraphError,
    ValidationRuntimeAttestationError,
    _admit_contract,
    admit_validation_graph,
    managed_validation_parameter_options,
    validation_graph_from_dict,
)
from spectra_sherpa.app.types import type_registry
from spectra_sherpa.execution_contract_vocabulary import NodeExecutionContract

_RUNTIME_ATTESTATION_PATH = (
    Path(__file__).resolve().parents[3] / "docs" / "evidence" / "managed-optimization-runtime-attestation.json"
)


def _profile_runtime_versions() -> dict[str, str]:
    return {
        str(requirement["distribution"]): str(requirement["version"])
        for contract in managed_optimization_profile().contracts
        for requirement in contract.payload["runtime_requirements"]
    }


def _first_party_runtime_matches_local_environment() -> bool:
    """Whether every operation's pinned runtime is actually installed here.

    Admission (``_admit_contract``) checks the real environment against the
    frozen profile's exact numpy/scipy/scikit-learn pins -- correctly, since
    that is a real admission decision, not a test double. A local run, CI
    leg, or contributor environment that lacks those exact versions cannot
    admit the affected operation (or, for the whole-profile check below, any operation), so tests that
    exercise real admission for it are only meaningful where the pinned
    runtime is actually present.
    """

    try:
        managed_optimization_profile().runtime_attestation()
    except ManagedOptimizationProfileError:
        return False
    return True


_first_party_runtime_pinned = pytest.mark.skipif(
    not _first_party_runtime_matches_local_environment(),
    reason="frozen first-party profile runtime (exact numpy/scipy/spectrochempy pins) is not installed here",
)


@pytest.fixture(autouse=True)
def loaded_registry() -> None:
    if not type_registry.is_loaded:
        type_registry.load(Path(__file__).resolve().parents[1] / "src" / "spectra_sherpa" / "app" / "types")


def _smooth(node_id: str, **parameters: object) -> WorkflowNode:
    return WorkflowNode(node_id=node_id, node_type="preprocess.smooth", parameters=parameters)


def test_admission_binds_registered_contracts_typed_topology_and_candidate_identity() -> None:
    nodes = [
        _smooth("first", method="gaussian", sigma=1.0),
        _smooth("second", method="gaussian", sigma=1.0),
        _smooth("third", method="gaussian", sigma=1.0),
    ]
    edges = [WorkflowEdge("first", "second"), WorkflowEdge("second", "third")]
    graph = admit_validation_graph(nodes, edges)

    assert [node.node_id for node in graph.nodes] == ["first", "second", "third"]
    assert all(node.contract.payload["operation_id"] == "preprocess.smooth" for node in graph.nodes)
    assert graph.digest == admit_validation_graph(nodes, list(reversed(edges))).digest
    original_parameters = nodes[0].parameters
    original_parameters["sigma"] = 99.0
    assert graph.nodes[0].parameters["method"] == "gaussian"
    assert graph.nodes[0].parameters["sigma"] == 1.0
    assert (
        graph.digest
        != admit_validation_graph(
            [_smooth("first", method="gaussian", sigma=2.0), _smooth("second", method="gaussian", sigma=1.0)],
            [WorkflowEdge("first", "second")],
        ).digest
    )
    with pytest.raises(TypeError):
        ValidationGraph((), ())


def test_admitted_edge_order_follows_the_execution_path_not_lexical_node_ids() -> None:
    graph = admit_validation_graph(
        [_smooth("z-root"), _smooth("a-middle"), _smooth("m-terminal")],
        [WorkflowEdge("z-root", "a-middle"), WorkflowEdge("a-middle", "m-terminal")],
    )

    assert [(edge.from_node, edge.to_node) for edge in graph.edges] == [
        ("z-root", "a-middle"),
        ("a-middle", "m-terminal"),
    ]


def test_serialized_graph_round_trips_through_independent_local_readmission() -> None:
    graph = admit_validation_graph(
        [_smooth("z-root"), _smooth("a-middle"), _smooth("m-terminal")],
        [WorkflowEdge("z-root", "a-middle"), WorkflowEdge("a-middle", "m-terminal")],
    )

    payload = graph.as_dict()
    rebuilt = validation_graph_from_dict(payload)

    assert payload["schema_version"] == "spectra-validation-graph/1"
    assert rebuilt == graph
    assert rebuilt.digest == graph.digest


def test_serialized_graph_rejects_undeclared_fields_and_contract_drift() -> None:
    graph = admit_validation_graph([_smooth("first"), _smooth("second")], [WorkflowEdge("first", "second")])
    payload = graph.as_dict()

    payload["unexpected"] = True
    with pytest.raises(ValidationGraphError, match="undeclared fields"):
        validation_graph_from_dict(payload)

    payload = graph.as_dict()
    payload["nodes"][0]["contract_digest"] = "0" * 64
    with pytest.raises(ValidationGraphError, match="do not match local authority"):
        validation_graph_from_dict(payload)


def test_serialized_graph_rejects_unknown_parameter_payload_and_bound_violations() -> None:
    with pytest.raises(ValidationGraphError, match="undeclared fields"):
        admit_validation_graph(
            [_smooth("first", exfiltration_payload={"sample_like": [1, 2, 3]})],
            [],
        )
    with pytest.raises(ValidationGraphError, match="below its admitted minimum"):
        admit_validation_graph([_smooth("first", method="gaussian", sigma=0.0)], [])
    for invalid_method in (["gaussian"], {"method": "gaussian"}):
        with pytest.raises(ValidationGraphError, match="finite scalar option"):
            admit_validation_graph([_smooth("first", method=invalid_method)], [])


@pytest.mark.parametrize(
    ("node_type", "parameters", "message"),
    [
        (
            "preprocess.derivative",
            {"method": "savitzky_golay", "deriv": "1", "size": 33, "order": 2},
            "managed Savitzky-Golay window",
        ),
        (
            "preprocess.derivative",
            {"method": "norris_williams", "deriv": "1", "gap": 16, "segment": 5},
            "managed Norris-Williams",
        ),
        (
            "baseline.penalized_ls",
            {"method": "als", "lam": 1e10, "p": 0.001, "max_iter": 50, "tol": 1e-6},
            "lambda may not exceed",
        ),
        (
            "baseline.penalized_ls",
            {"method": "als", "lam": 1e5, "p": 0.001, "max_iter": 101, "tol": 1e-6},
            "max_iter may not exceed",
        ),
    ],
)
def test_node_owned_managed_envelopes_reject_work_outside_hosted_bounds(
    node_type: str,
    parameters: dict[str, object],
    message: str,
) -> None:
    with pytest.raises(ValidationGraphError, match=message):
        admit_validation_graph([WorkflowNode("candidate", node_type, parameters)], [])


def test_local_canonical_grammar_remains_broader_than_managed_resource_envelope() -> None:
    derivative = node_registry.get_metadata("preprocess.derivative")
    baseline = node_registry.get_metadata("baseline.penalized_ls")

    assert (
        derivative.canonicalize_parameters({"method": "savitzky_golay", "deriv": "1", "size": 33, "order": 2})["size"]
        == 33
    )
    assert (
        baseline.canonicalize_parameters({"method": "als", "lam": 1e10, "p": 0.001, "max_iter": 101, "tol": 1e-6})[
            "max_iter"
        ]
        == 101
    )


def test_nonreplayable_rubberband_never_enters_managed_scoring() -> None:
    with pytest.raises(ValidationGraphError, match="local-only"):
        admit_validation_graph([WorkflowNode("rubberband", "baseline.rubberband", {})], [])


def test_serialized_graph_rejects_parameter_mutation_without_its_bound_graph_digest() -> None:
    graph = admit_validation_graph([_smooth("first", method="gaussian", sigma=1.0)], [])
    payload = graph.as_dict()
    payload["nodes"][0]["parameters"]["sigma"] = 2.0

    with pytest.raises(ValidationGraphError, match="graph digest does not match"):
        validation_graph_from_dict(payload)


def test_serialized_graph_rejects_malformed_or_nonadmissible_topology() -> None:
    graph = admit_validation_graph([_smooth("first"), _smooth("second")], [WorkflowEdge("first", "second")])

    malformed = graph.as_dict()
    malformed["nodes"][0]["contract_digest"] = "not-a-sha256"
    with pytest.raises(ValidationGraphError, match="contract digest is malformed"):
        validation_graph_from_dict(malformed)

    disconnected = graph.as_dict()
    disconnected["edges"] = []
    with pytest.raises(ValidationGraphError, match="connected scientific path"):
        validation_graph_from_dict(disconnected)


def test_local_only_nodes_never_enter_scientific_candidate_scoring() -> None:
    with pytest.raises(ValidationGraphError, match="local-only"):
        admit_validation_graph([WorkflowNode("source", "data.file_load", {"experiment_id": 1, "file_id": 1})], [])


def test_first_profile_rejects_branches_and_named_port_ambiguity() -> None:
    nodes = [_smooth("first"), _smooth("left"), _smooth("right")]
    with pytest.raises(ValidationGraphError, match="unbranched"):
        admit_validation_graph(nodes, [WorkflowEdge("first", "left"), WorkflowEdge("first", "right")])
    with pytest.raises(ValidationGraphError, match="default-port"):
        admit_validation_graph([_smooth("first"), _smooth("second")], [WorkflowEdge("first", "second", "x")])
    with pytest.raises(ValidationGraphError, match="connected"):
        admit_validation_graph([_smooth("first"), _smooth("second")], [])


def test_admission_rejects_scientific_looking_node_with_an_export_like_policy(monkeypatch) -> None:
    metadata = node_registry.get_metadata("preprocess.smooth")
    monkeypatch.setattr(metadata, "category", "export")
    with pytest.raises(ValidationGraphError, match="scientific node category"):
        admit_validation_graph([_smooth("first")], [])


def test_closed_profile_rejects_future_scientific_node_that_declares_no_egress(monkeypatch) -> None:
    metadata = node_registry.get_metadata("preprocess.smooth")
    payload = metadata.resolved_execution_contract().as_dict()
    payload["operation_id"] = "preprocess.future.side_effect"
    payload["implementation_id"] = "spectrasherpa.preprocess.future.side_effect"
    future_metadata = replace(
        metadata,
        node_type="preprocess.future.side_effect",
        execution_contract=NodeExecutionContract.from_dict(payload),
    )
    monkeypatch.setattr(node_registry, "get_metadata", lambda _node_type: future_metadata)
    with pytest.raises(ValidationGraphError, match="closed managed-validation profile"):
        _admit_contract(WorkflowNode("future", "preprocess.future.side_effect", {}))


def test_shared_preflight_remains_the_authority_for_invalid_typed_graphs() -> None:
    with pytest.raises(ValidationGraphError, match="shared preflight"):
        admit_validation_graph(
            [_smooth("first"), _smooth("second")], [WorkflowEdge("first", "second"), WorkflowEdge("second", "first")]
        )


@pytest.mark.parametrize(
    "parameters",
    [
        {},
        {"method": "peak_window"},
        {"method": "apply_mask"},
        {"method": "vip"},
        {"method": "coef_abs"},
        {"method": "selectivity_ratio"},
    ],
)
def test_managed_variable_selection_refuses_auxiliary_or_fold_learned_methods(
    parameters: dict[str, object],
) -> None:
    with pytest.raises(ValidationGraphError, match="leakage-safe managed-validation subset"):
        admit_validation_graph(
            [WorkflowNode("select", "selection.variable_select", parameters)],
            [],
        )


def test_managed_parameter_projection_exposes_the_same_interval_only_subset() -> None:
    assert managed_validation_parameter_options("selection.variable_select") == {"method": ("interval",)}
    assert managed_validation_parameter_options("preprocess.scale") == {}


@_first_party_runtime_pinned
def test_first_party_profile_is_closed_versioned_and_binds_each_registered_contract() -> None:
    profile = managed_optimization_profile()
    assert profile.profile_id == "first_party_pls"
    assert profile.profile_version == "8"
    assert len(profile.digest) == 64
    assert profile.operation_ids == {
        "preprocess.smooth",
        "baseline.penalized_ls",
        "preprocess.derivative",
        "preprocess.emsc",
        "preprocess.msc",
        "preprocess.normalize",
        "preprocess.osc",
        "preprocess.scale",
        "model.fitted_pls",
        "model.fitted_pcr",
        "model.fitted_svr",
        "model.fitted_linear_regression",
        "diagnostics.regression_evaluator",
        "classification.knn",
        "classification.plsda",
        "classification.simca",
        "diagnostics.classification_evaluator",
        "selection.variable_select",
    }
    for operation_id in profile.operation_ids:
        contract = node_registry.get_metadata(operation_id).resolved_execution_contract()
        assert contract is not None
        assert contract.payload["license_id"]
        assert contract.payload["citations"]
        profile.assert_contract(contract)
    baseline_contract = node_registry.get_metadata("baseline.penalized_ls").resolved_execution_contract()
    assert baseline_contract is not None
    assert len(baseline_contract.payload["citations"]) == 3


def test_first_party_profile_rejects_recomputed_implementation_closure_drift() -> None:
    contract = node_registry.get_metadata("model.fitted_pls").resolved_execution_contract()
    assert contract is not None
    payload = contract.as_dict()
    components = [dict(component) for component in payload["implementation_components"]]
    components[0]["digest"] = "0" * 64
    payload["implementation_components"] = components
    payload["implementation_digest"] = implementation_digest_for_components(components)
    with pytest.raises(ManagedOptimizationProfileError, match="differs from the live canonical registry"):
        managed_optimization_profile().assert_contract(NodeExecutionContract.from_dict(payload))


def test_first_party_profile_runtime_attestation_is_exact_and_portable() -> None:
    expected = _profile_runtime_versions()

    attestation = managed_optimization_profile().runtime_attestation(
        ("preprocess.derivative",), version_resolver=expected.__getitem__
    )

    assert attestation.operation_ids == ("preprocess.derivative",)
    assert [requirement.as_dict() for requirement in attestation.distributions] == [
        {"distribution": "numpy", "version": "1.26.4"},
        {"distribution": "scipy", "version": "1.17.1"},
    ]
    assert len(attestation.digest) == 64
    assert attestation.as_dict()["digest"] == attestation.digest

    wrong = {**expected, "scipy": "1.18.0"}
    with pytest.raises(ManagedOptimizationProfileError, match="requires scipy==1.17.1; observed 1.18.0"):
        managed_optimization_profile().runtime_attestation(
            ("preprocess.derivative",), version_resolver=wrong.__getitem__
        )

    def missing(_distribution: str) -> str:
        raise managed_optimization_profile_module.importlib.metadata.PackageNotFoundError

    with pytest.raises(ManagedOptimizationProfileError, match="requires numpy==1.26.4; it is not installed"):
        managed_optimization_profile().runtime_attestation(("model.fitted_pls",), version_resolver=missing)


def test_checked_runtime_attestation_names_the_profile_pins() -> None:
    expected = _profile_runtime_versions()
    recorded = json.loads(_RUNTIME_ATTESTATION_PATH.read_text())

    assert (
        recorded == managed_optimization_profile().runtime_attestation(version_resolver=expected.__getitem__).as_dict()
    )


def test_admission_checks_the_operation_runtime_before_contract_identity(monkeypatch) -> None:
    def wrong_runtime(distribution: str) -> str:
        return "1.18.0" if distribution == "scipy" else _profile_runtime_versions()[distribution]

    monkeypatch.setattr(managed_optimization_profile_module.importlib.metadata, "version", wrong_runtime)
    with pytest.raises(
        ValidationRuntimeAttestationError,
        match=(
            r"derivative managed runtime attestation failed: "
            r"first_party_pls requires scipy==1\.17\.1; observed 1\.18\.0"
        ),
    ):
        _admit_contract(WorkflowNode("derivative", "preprocess.derivative", {}))


def test_admission_reports_contract_identity_separately_from_runtime(monkeypatch) -> None:
    profile = managed_optimization_profile()

    class ContractDrift:
        operation_ids = profile.operation_ids

        @staticmethod
        def runtime_attestation(_operation_ids) -> None:
            return None

        @staticmethod
        def assert_contract(_contract) -> None:
            raise ManagedOptimizationProfileError("execution contract differs from the live canonical registry")

    monkeypatch.setattr(validation_graph_module, "managed_optimization_profile", lambda: ContractDrift())
    with pytest.raises(
        ValidationContractError,
        match="derivative contract does not match the first-party validation profile",
    ):
        _admit_contract(WorkflowNode("derivative", "preprocess.derivative", {}))


def test_offline_inspection_does_not_re_admit_a_local_only_contract() -> None:
    node = WorkflowNode("rubberband", "baseline.rubberband", {})

    with pytest.raises(ValidationGraphError, match="local-only"):
        admit_validation_graph([node], [], require_live_runtime=False)


def test_admission_rejects_pls_when_its_native_numpy_runtime_drifts(monkeypatch) -> None:
    expected = _profile_runtime_versions()

    def drifted_runtime(distribution: str) -> str:
        return "1.27.0" if distribution == "numpy" else expected[distribution]

    monkeypatch.setattr(managed_optimization_profile_module.importlib.metadata, "version", drifted_runtime)
    with pytest.raises(
        ValidationRuntimeAttestationError,
        match=r"pls managed runtime attestation failed: first_party_pls requires numpy==1\.26\.4; observed 1\.27\.0",
    ):
        _admit_contract(WorkflowNode("pls", "model.fitted_pls", {}))
