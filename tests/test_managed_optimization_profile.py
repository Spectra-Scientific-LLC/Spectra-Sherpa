"""The managed optimization profile is a deterministic projection of live node contracts."""

from __future__ import annotations

import pytest

from spectra_sherpa.app.services.dag.managed_optimization_profile import (
    ManagedOptimizationProfileError,
    managed_optimization_profile,
)
from spectra_sherpa.app.services.dag.node_base import node_registry
from spectra_sherpa.execution_contract_vocabulary import NodeExecutionContract

_EXPECTED_PLS_OPERATIONS = {
    "baseline.penalized_ls",
    "classification.knn",
    "classification.plsda",
    "classification.simca",
    "diagnostics.classification_evaluator",
    "diagnostics.regression_evaluator",
    "model.fitted_pls",
    "model.fitted_pcr",
    "model.fitted_svr",
    "model.fitted_linear_regression",
    "preprocess.derivative",
    "preprocess.emsc",
    "preprocess.msc",
    "preprocess.normalize",
    "preprocess.osc",
    "preprocess.scale",
    "preprocess.smooth",
    "selection.variable_select",
}


def test_profile_is_derived_from_the_exact_registered_contract_objects() -> None:
    first = managed_optimization_profile()
    second = managed_optimization_profile()

    assert first.operation_ids == _EXPECTED_PLS_OPERATIONS
    assert first.digest == second.digest
    assert [contract.payload["operation_id"] for contract in first.contracts] == sorted(_EXPECTED_PLS_OPERATIONS)
    for contract in first.contracts:
        metadata = node_registry.get_metadata(str(contract.payload["operation_id"]))
        assert metadata.resolved_execution_contract() is contract
        assert first.profile_id in contract.payload["managed_optimization_profiles"]


def test_profile_runtime_requirements_come_from_registered_contracts() -> None:
    profile = managed_optimization_profile()
    versions = {
        str(requirement["distribution"]): str(requirement["version"])
        for contract in profile.contracts
        for requirement in contract.payload["runtime_requirements"]
    }

    attestation = profile.runtime_attestation(version_resolver=versions.__getitem__)

    assert attestation.profile_digest == profile.digest
    assert attestation.operation_ids == tuple(sorted(_EXPECTED_PLS_OPERATIONS))
    assert {item.distribution: item.version for item in attestation.distributions} == versions


def test_profile_rejects_a_forged_copy_of_a_registered_operation() -> None:
    profile = managed_optimization_profile()
    original = profile.operation("preprocess.smooth")
    forged_payload = original.as_dict()
    forged_payload["implementation_version"] = "forged"
    forged = NodeExecutionContract.from_dict(forged_payload)

    with pytest.raises(ManagedOptimizationProfileError, match="differs from the live canonical registry"):
        profile.assert_contract(forged)


def test_application_contracts_are_not_candidate_profile_members() -> None:
    profile = managed_optimization_profile()

    assert "model.apply_fitted_pls" not in profile.operation_ids
    assert "preprocess.apply_fitted_scale" not in profile.operation_ids


def test_nonreplayable_rubberband_remains_explicitly_local_only() -> None:
    profile = managed_optimization_profile()
    contract = node_registry.get_metadata("baseline.rubberband").resolved_execution_contract()

    assert contract is not None
    assert contract.payload["managed_optimization_eligibility"] == ("local",)
    assert contract.payload["managed_optimization_profiles"] == ()
    assert "baseline.rubberband" not in profile.operation_ids
