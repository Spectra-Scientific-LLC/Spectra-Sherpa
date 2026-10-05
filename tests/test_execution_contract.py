"""M4.0 contract fixtures: closed vocabulary before executor migration."""

from __future__ import annotations

import hashlib
import json

import pytest

from spectra_sherpa.sdk.execution_contract import FIELD_CONSUMER_PLAN, ContractError, NodeExecutionContract

_DIGEST = "a" * 64


def _port(
    name: str,
    type_ref: str = "spectrasherpa://types/SpectralDataset/1.0",
    *,
    required: bool = True,
    variadic: bool = False,
    accepted_data_roles: list[str] | None = None,
) -> dict[str, object]:
    return {
        "name": name,
        "type_ref": type_ref,
        "required": required,
        "variadic": variadic,
        "accepted_data_roles": accepted_data_roles or [],
    }


def _implementation_digest(components: list[dict[str, str]]) -> str:
    """Mirror the closed implementation-closure identity contract."""

    canonical = json.dumps(
        {"components": sorted(components, key=lambda item: item["component_id"])},
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def _contract(**overrides):
    components = [{"component_id": "spectrasherpa.preprocess.smooth", "digest": _DIGEST}]
    payload = {
        "contract_version": "4.0",
        "operation_id": "preprocess.smooth",
        "runtime_family": "sherpa_native",
        "custom_trust_class": "not_applicable",
        "lifecycle_kind": "stateless_transform",
        "implementation_id": "spectrasherpa.preprocess.smooth",
        "implementation_version": "1.0.0",
        "implementation_digest": _implementation_digest(components),
        "implementation_components": components,
        "parameter_schema_digest": "b" * 64,
        "semantic_inputs": [_port("input")],
        "semantic_outputs": [_port("output")],
        "target_access": "none",
        "group_access": "none",
        "supervised_task": "none",
        "input_rank_policy": "requires_2d",
        "sample_effect": "preserves_samples",
        "feature_effect": "preserves_features",
        "axis_effect": "preserves_axis",
        "unit_effect": "preserves_units",
        "deterministic": True,
        "seed_parameter": None,
        "fitted_state_serializer": None,
        "required_worker_capabilities": ["read_dataset"],
        "resource_hints": {"timeout_seconds": 5, "cpu_seconds": 5, "memory_bytes": 1048576},
        "managed_optimization_eligibility": ["local", "development"],
        "managed_optimization_profiles": ["first_party_pls"],
        "runtime_requirements": [{"distribution": "numpy", "version": "1.26.4"}],
        "citations": [],
        "license_id": "Apache-2.0",
        "help_reference": "docs/nodes/preprocess/smooth",
    }
    payload.update(overrides)
    if "implementation_digest" not in overrides:
        payload["implementation_digest"] = _implementation_digest(payload["implementation_components"])
    return payload


def test_contract_is_closed_stable_and_changes_for_scientific_identity() -> None:
    contract = NodeExecutionContract.from_dict(_contract())
    reordered = NodeExecutionContract.from_dict(dict(reversed(list(_contract().items()))))
    changed = NodeExecutionContract.from_dict(_contract(implementation_version="1.0.1"))

    assert contract.digest == reordered.digest
    assert contract.digest != changed.digest
    assert contract.as_dict() == _contract()


def test_contract_cannot_be_mutated_through_input_or_public_payload() -> None:
    payload = _contract(resource_hints={"timeout_seconds": 5, "cpu_seconds": 5, "memory_bytes": 1048576})
    contract = NodeExecutionContract(payload)
    original_digest = contract.digest
    payload["resource_hints"]["cpu_seconds"] = 99

    assert contract.digest == original_digest
    assert contract.as_dict()["resource_hints"]["cpu_seconds"] == 5
    with pytest.raises(TypeError):
        contract.payload["runtime_family"] = "spectrochempy"  # type: ignore[index]
    with pytest.raises(TypeError):
        contract.payload["resource_hints"]["cpu_seconds"] = 99  # type: ignore[index]


@pytest.mark.parametrize(
    "example",
    [
        _contract(),
        _contract(
            runtime_family="spectrochempy",
            lifecycle_kind="fitted_transform",
            implementation_id="spectrochempy.model.efa",
            fitted_state_serializer="spectrasherpa.scp.efa-state/1",
            citations=["doi:10.1000/spectrochempy-example"],
            license_id="CeCILL-B",
        ),
        _contract(
            runtime_family="approved_custom",
            custom_trust_class="approved_development",
            lifecycle_kind="fitted_transform",
            implementation_id="org.example.scatter-correction",
            fitted_state_serializer="org.example.scatter-state/1",
            managed_optimization_eligibility=["local", "development"],
            managed_optimization_profiles=["approved_custom_development"],
            license_id="LicenseRef-OrgApproved",
        ),
        _contract(
            runtime_family="sherpa_native",
            lifecycle_kind="fitted_model",
            operation_id="model.pls",
            implementation_id="spectrasherpa.model.pls",
            supervised_task="regression",
            target_access="required",
            group_access="optional",
            fitted_state_serializer="spectrasherpa.pls-artifact/1",
            managed_optimization_eligibility=["local", "development", "confirmation", "full_refit"],
        ),
    ],
)
def test_contract_accepts_each_canonical_runtime_lifecycle_example(example) -> None:
    """M4.0 fixtures: native, SCP, approved-custom, and fitted-model roles."""
    contract = NodeExecutionContract.from_dict(example)
    assert contract.as_dict() == example


def test_contract_allows_a_pure_source_to_require_no_custody_capability() -> None:
    """A deterministic generator must not pretend it reads a governed dataset."""

    payload = _contract()
    payload["required_worker_capabilities"] = []
    contract = NodeExecutionContract.from_dict(payload)
    assert contract.payload["required_worker_capabilities"] == ()


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"unexpected": "field"}, "unknown execution-contract"),
        ({"runtime_family": "plugin"}, "unknown runtime_family"),
        ({"target_access": "perhaps"}, "unknown target_access"),
        ({"group_access": "perhaps"}, "unknown group_access"),
        ({"supervised_task": "forecasting"}, "unknown supervised_task"),
        ({"supervised_task": "classification"}, "only fitted models"),
        ({"implementation_digest": "not-a-digest"}, "implementation_digest"),
        ({"deterministic": False, "seed_parameter": None}, "seed_parameter"),
        ({"deterministic": False, "seed_parameter": ""}, "seed_parameter"),
        ({"lifecycle_kind": "fitted_model", "fitted_state_serializer": None}, "fitted_state_serializer"),
        ({"sample_effect": "maybe"}, "unknown sample_effect"),
        ({"semantic_inputs": ["NDDataset"]}, "closed semantic-port schema"),
        ({"required_worker_capabilities": ["shell"]}, "worker capability"),
        (
            {"resource_hints": {"timeout_seconds": float("nan"), "cpu_seconds": 1, "memory_bytes": 1}},
            "resource_hints.timeout_seconds",
        ),
        ({"managed_optimization_eligibility": ["development"]}, "local eligibility"),
        ({"managed_optimization_eligibility": ["local", "confirmation"]}, "requires development"),
        ({"managed_optimization_profiles": []}, "must name a managed optimization profile"),
        ({"runtime_requirements": [{"distribution": "numpy"}]}, "closed distribution/version schema"),
        ({"runtime_family": "approved_custom"}, "custom_trust_class"),
        (
            {
                "runtime_family": "approved_custom",
                "custom_trust_class": "approved_development",
                "managed_optimization_eligibility": ["local", "development", "confirmation"],
            },
            "custom confirmation",
        ),
    ],
)
def test_contract_rejects_ambiguous_or_unknown_identity(change, message: str) -> None:
    payload = _contract()
    payload.update(change)
    with pytest.raises(ContractError, match=message):
        NodeExecutionContract.from_dict(payload)


def test_contract_allows_a_typed_source_or_sink_but_not_a_portless_operation() -> None:
    source = NodeExecutionContract.from_dict(_contract(semantic_inputs=[]))
    sink = NodeExecutionContract.from_dict(_contract(semantic_outputs=[]))

    assert source.payload["semantic_inputs"] == ()
    assert sink.payload["semantic_outputs"] == ()

    with pytest.raises(ContractError, match="at least one semantic input or output"):
        NodeExecutionContract.from_dict(_contract(semantic_inputs=[], semantic_outputs=[]))


def test_named_ports_allow_repeated_types_but_reject_repeated_names() -> None:
    repeated_type = "spectrasherpa://types/SpectralDataset/1.0"
    contract = NodeExecutionContract.from_dict(
        _contract(semantic_outputs=[_port("X_train", repeated_type), _port("X_test", repeated_type)])
    )

    assert [port["name"] for port in contract.payload["semantic_outputs"]] == ["X_train", "X_test"]
    with pytest.raises(ContractError, match="may not repeat a port name"):
        NodeExecutionContract.from_dict(
            _contract(semantic_outputs=[_port("result", repeated_type), _port("result", repeated_type)])
        )


def test_prototype_execution_contract_v1_is_rejected_without_compatibility() -> None:
    with pytest.raises(ContractError, match="unsupported execution-contract version"):
        NodeExecutionContract.from_dict(_contract(contract_version="1.0"))


def test_all_contract_fields_have_named_in_tree_consumers() -> None:
    contract = NodeExecutionContract.from_dict(_contract())
    assert set(FIELD_CONSUMER_PLAN) == set(contract.as_dict())
    assert all(consumers for consumers in FIELD_CONSUMER_PLAN.values())


def test_contract_digest_cannot_claim_a_different_implementation_closure() -> None:
    payload = _contract()
    payload["implementation_components"] = [{"component_id": "spectrasherpa.preprocess.smooth", "digest": "c" * 64}]

    with pytest.raises(ContractError, match="implementation_digest must name"):
        NodeExecutionContract.from_dict(payload)
