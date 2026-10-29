"""Exact saved-state continuity after the OSS scientific audit; no fit aliases."""

import pytest

from spectra_sherpa.app.services.dag import historical_contracts, node_registry
from spectra_sherpa.app.services.dag.managed_optimization_profile import managed_optimization_profile
from spectra_sherpa.app.services.dag.validation_graph import ValidationGraphError
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

_READ_ONLY_CONSUMERS = {
    "diagnostics.regression_evaluator": "769f2b7129ae580721435b91c2df1fd11ee6e2400e8489d266643da74ae96684",
    **{operation: current for operation, (_, current) in _REVIEWED.items() if operation != "model.pca"},
    "model.apply_fitted_linear_regression": "d2d1306c1b29286f1103349c9bf961428dd17c065054a024e1efe4d7f2428495",
    "model.apply_fitted_pcr": "6663dc32859dd2b7552ec3c22bc608173a24ad032bc96fe9a82b5fb8ec0b25fe",
    "model.apply_fitted_svr": "492ef1eb3ed2bda68cd34e7c100fc3f196e45045b26246199de937ed4a1d7c6b",
    "classification.plsda": "1775c23851d9ec5231755349dbf04ee2dcade3af8963e2e68e7911657316a236",
    "model.fitted_pls": "7e577601daba52133d0e63f7496614960747b78a438c03c01297c22b28226012",
    "model.fitted_linear_regression": "f28fc334028632f8bfce32aded3019e2d4094846825d0573b743f8b513b4f69f",
    "model.fitted_pcr": "af58a7e90bc1a7dffae447ab12048fa8b702ec493a86c256711ef0a3ccce2f63",
    "model.fitted_svr": "598257753f8ef867cf069372e8cdfb88d1a2ba3f6a862b12a8afd12e41b11179",
}
_PROFILE_DIGESTS = (None, "9f37d08a914c3e276859c0ba10b5d2187d5d5ba4ff85f6d00b35cba23e7369f4")


@pytest.mark.parametrize("profile_digest", _PROFILE_DIGESTS)
@pytest.mark.parametrize("operation", _READ_ONLY_CONSUMERS)
def test_exact_historical_inspection_consumers_preserve_both_packaged_profiles(operation, profile_digest, monkeypatch):
    context = historical_contracts.HistoricalReconstructionContext(profile_digest)
    catalog = authority.inspection_predecessor_catalog(profile_digest)
    current = node_registry.get_metadata(operation).resolved_execution_contract()
    assert current.digest == _READ_ONLY_CONSUMERS[operation]
    archived = catalog["contracts"].get(operation) or catalog.get("profile_contracts", {}).get(operation)
    if archived is None and operation == "diagnostics.regression_evaluator":
        # The first pinned profile omitted this payload; the second contains
        # exactly the same historic digest, verified by the reconstruction path.
        staging = authority.inspection_predecessor_catalog(_PROFILE_DIGESTS[1])
        archived = staging["contracts"][operation]
    if archived is None:
        assert operation not in catalog["profile"]["operations"]
        original = authority.inspection_predecessor_catalog()["contracts"][operation]
        with pytest.raises(ValidationGraphError, match="unknown historical operation"):
            context.contract(operation, original["digest"])
        return
    restored = context.contract(operation, archived["digest"])
    assert restored.as_dict() == archived["payload"]
    assert restored.digest == archived["digest"] != current.digest
    assert context.profile().digest == catalog["profile"]["profile_digest"]
    # A future consumer cannot inherit this review just by matching declarations.
    before, _ = historical_contracts._INSPECTION_CONSUMERS[operation]
    monkeypatch.setitem(historical_contracts._INSPECTION_CONSUMERS, operation, (before, "f" * 64))
    with pytest.raises(ValidationGraphError, match="not qualified"):
        context.contract(operation, archived["digest"])


_OUTSIDE_PROFILE = {
    "model.apply_fitted_pls": "de28cf5fbdc56e73ce478886ec7792ef34a6f3e965c7276da2a45014b4adadc2",
    "model.pca_transform": "19245b23ef3c6a4292e13b99cd29f5022adec8569137d474639fc2431586bd4e",
    "model.predict_regression": "c3946bcaf9f36178efaba8bd14c8e5b07cf3de77311eb6e7514268880a4069b1",
    "diagnostics.labeled_regression_evaluator": "49e49cd7dfb6a737ae3e6c87038547a294ec495ff0e1d9e1f46e62a68b4d48da",
    "diagnostics.plsda_permutation": "536b366411346eb3bd59489e9efcb98cd9edd660e929157047c33f81e98bb9e3",
    "analysis.peak_finding": "1314d8d00cba0525f74044f31d7a6d93269ac079c986342514fd49ca6221e129",
}


@pytest.mark.parametrize("profile_digest", _PROFILE_DIGESTS)
@pytest.mark.parametrize("operation", _OUTSIDE_PROFILE)
def test_other_changed_consumers_have_no_archived_profile_or_application_alias(operation, profile_digest):
    catalog = authority.inspection_predecessor_catalog(profile_digest)
    assert operation not in catalog["profile"]["operations"]
    assert operation not in catalog["contracts"]
    assert operation not in catalog.get("profile_contracts", {})
    assert operation not in managed_optimization_profile().operation_ids
    current = node_registry.get_metadata(operation).resolved_execution_contract()
    assert current.digest != _OUTSIDE_PROFILE[operation]
    assert not authority.saved_state_predecessor_is_compatible(
        _OUTSIDE_PROFILE[operation],
        current.digest,
        operation_id=operation,
    )
    with pytest.raises(ValidationGraphError, match="unknown historical operation"):
        historical_contracts.HistoricalReconstructionContext(profile_digest).contract(
            operation, _OUTSIDE_PROFILE[operation]
        )


@pytest.mark.parametrize("operation", _REVIEWED)
def test_scientific_audit_preserves_exact_prior_application_not_execution(operation):
    before, current = _REVIEWED[operation]
    contract = node_registry.get_metadata(operation).resolved_execution_contract()
    latest = {entry.operation_id: entry.consumer_digest for entry in authority._WORKFLOW_POPULATION_PREDECESSORS}
    # The reviewed display-only reuse has its own exact current PCA consumer;
    # the historical scientific-audit pairs below remain pinned unchanged.
    latest.update({entry.operation_id: entry.consumer_digest for entry in authority._HANDOFF_PRESENTATION_PREDECESSORS})
    latest["model.pca"] = "1f31f0ab7581b4f68319d01574545fb3038f640c171c2f2df2dc68f48ce29b3f"
    assert contract.digest == latest.get(operation, current)
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


def test_scientific_audit_application_registry_has_only_the_reviewed_operations():
    assert {entry.operation_id for entry in authority._SCIENTIFIC_AUDIT_PREDECESSORS} == set(_REVIEWED)
    assert len(authority._SCIENTIFIC_AUDIT_PREDECESSORS) == 46
