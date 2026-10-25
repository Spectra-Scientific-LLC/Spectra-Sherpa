"""Exact saved-state continuity after the OSS scientific audit; no fit aliases."""

import pytest

from spectra_sherpa.app.services.dag import node_registry
from spectra_sherpa.core import contract_compatibility as authority
from spectra_sherpa.sdk.fitted_state_custody import (
    DATA_FREE_APPLICATION_STATE,
    RETAINS_TRAINING_ROWS,
    fitted_state_custody_capability,
)

_REVIEWED = {
    "classification.plsda": (
        "85b2a1fd3938dee8a3a12f61397a07052883cd3f0bfa4d977151b600fe4992b6",
        "50f7565a6e8ef6e6ce7b92e730588b9f1d1ef334015a8cf50555a793ed7815a2",
    ),
    "model.fitted_linear_regression": (
        "a0a31850e5ec62ce5d3d45050af62f715306d1da9d84442d76d70b1b738303f8",
        "0ba997bbc87209703db011f38850ee82d93027bb72ab28db27aa108a8f9cca9a",
    ),
    "model.fitted_pcr": (
        "e76876f01548800f4b3ee2bdf0382359e046793a1e02e61e424e17b552256bf3",
        "99359a3588dfe55e29fd32428ce896d1ca503e3472e8b17a5982ed24d72a0d0d",
    ),
    "model.fitted_pls": (
        "473b586d631d966d9a76a32ec3788f95b7aea3771fb8981256475061d1b52871",
        "ba02705c9868ae460e80af30207f8fa1c60f5ff20e8e6588be267292811472da",
    ),
    "model.fitted_svr": (
        "a6be415b3b1ed88d25ef0a220d1059031ada900f4c470d2a7cb762c250edf8af",
        "b8ba060d1154848d0f96e25a0178c0c5eeff6658a4fc36de6ae3f7c82cb3f7ed",
    ),
    "model.pca": (
        "85b458d4b762f028fd9e825c47642460faf9f4682122def13416c88082a879f6",
        "bcf69d89f62cb9e9ad1cfb46fc1f32b258c130dd571eb457df73fb535f685f0f",
    ),
}


@pytest.mark.parametrize("operation", _REVIEWED)
def test_scientific_audit_preserves_exact_prior_application_not_execution(operation):
    before, current = _REVIEWED[operation]
    contract = node_registry.get_metadata(operation).resolved_execution_contract()
    assert contract.digest == current
    serializer = contract.payload["fitted_state_serializer"]
    previous = list(authority.saved_state_compatibilities())
    for name, entries in vars(authority).items():
        if name.endswith("_PREDECESSORS") and name != "_SCIENTIFIC_AUDIT_PREDECESSORS":
            previous.extend(entries)
    expected = {before} | {
        entry.predecessor_digest
        for entry in previous
        if entry.operation_id == operation and entry.consumer_digest == before
    }
    declared = [entry for entry in authority._SCIENTIFIC_AUDIT_PREDECESSORS if entry.operation_id == operation]
    assert {entry.predecessor_digest for entry in declared} == expected
    assert len(declared) == len(expected)
    for predecessor in expected:
        assert authority.saved_state_predecessor_is_compatible(
            predecessor, current, operation_id=operation, serializer=serializer
        )
        assert not authority.saved_state_predecessor_is_compatible(
            current, predecessor, operation_id=operation, serializer=serializer
        )
        assert not authority.saved_state_predecessor_is_compatible(
            predecessor, current, operation_id="not.a.model", serializer=serializer
        )
        assert not authority.saved_state_predecessor_is_compatible(
            predecessor, current, operation_id=operation, serializer="wrong.serializer"
        )
    assert not authority.saved_state_predecessor_is_compatible(
        "f" * 64, current, operation_id=operation, serializer=serializer
    )
    capability = fitted_state_custody_capability(serializer, current)
    assert capability.custody_class == (
        RETAINS_TRAINING_ROWS if operation == "model.fitted_svr" else DATA_FREE_APPLICATION_STATE
    )
