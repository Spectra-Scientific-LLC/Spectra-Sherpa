"""Exact source-only application compatibility; never inference by chaining."""

import pytest

import spectra_sherpa.app.services.dag.nodes  # noqa: F401
from spectra_sherpa.app.services.dag.node_base import node_registry
from spectra_sherpa.core import contract_compatibility as authority
from spectra_sherpa.sdk.fitted_state_custody import FittedStateCustodyError, fitted_state_custody_capability

# Independently reviewed old/current source identities. No runtime-derived aliases.
_REVIEWED = {
    "classification.knn": (
        "8acc66bc0b248e2ebfbd89f041dd0513b3505740fa5a2b5e3b4dbccba81f1206",
        "df59b9d414abefb1c93de58ef405f3044ad4c6a02b23dd62cf8cd38c131b58a7",
    ),
    "classification.plsda": (
        "526a54177bad1ec421ec319c031f6ba322fa431e7235cf35604e14d7ecf23f6c",
        "85b2a1fd3938dee8a3a12f61397a07052883cd3f0bfa4d977151b600fe4992b6",
    ),
    "classification.simca": (
        "16dfeba33f742c80aad2e8ae2dcccb42d430215b20b2fdfb77179f821db52034",
        "2a591ac8626fe115463326b7f6b30b1ad3721c6392e6e4a07af786de13777388",
    ),
    "model.fitted_linear_regression": (
        "10b125ffb88229b92cfe1eac67e5717117cfdf57d485b3e370abb2ef8910f6a7",
        "a0a31850e5ec62ce5d3d45050af62f715306d1da9d84442d76d70b1b738303f8",
    ),
    "model.fitted_pcr": (
        "577777179c36fedf0338c84a003e9080aa8879043e2ad0e19e7dccc5f618c201",
        "e76876f01548800f4b3ee2bdf0382359e046793a1e02e61e424e17b552256bf3",
    ),
    "model.fitted_svr": (
        "cde922310dc4713ab5349720f865595fee13c8c2a53b60f68708ceed9882bae0",
        "a6be415b3b1ed88d25ef0a220d1059031ada900f4c470d2a7cb762c250edf8af",
    ),
    "model.ica": (
        "053d4bf663ea8242c2ad400629f7a9436035a826781346966cb62d95a19cac5a",
        "96cf3f6dd097f4bbe30b4dcaf2c70f919fdb7abdce90b9d51ba4f25aa4a2427e",
    ),
    "model.mcr_als": (
        "ce5de4a28b2258eed1ad44509ae8f0aa9952f7f8b7d5097116ad55f5b21ba9d3",
        "bc1c45f468420d8931ff66c71b388abaf32e1d459cc35a6b1d668c819470389e",
    ),
    "model.pca": (
        "5e809716a8266c4ddd5fb3902b8a68c264019fd05237bdb1397f664ae31dea10",
        "85b458d4b762f028fd9e825c47642460faf9f4682122def13416c88082a879f6",
    ),
}


def test_source_only_registrations_preserve_all_previously_supported_producers():
    new = authority._DIAGNOSTIC_REFUSAL_PREDECESSORS
    assert {entry.operation_id for entry in new} == set(_REVIEWED)
    previous = list(authority.saved_state_compatibilities())
    for name, entries in vars(authority).items():
        if name.endswith("_PREDECESSORS") and name not in {
            "_DIAGNOSTIC_REFUSAL_PREDECESSORS",
            "_SCIENTIFIC_AUDIT_PREDECESSORS",
            "_WORKFLOW_POPULATION_PREDECESSORS",
            "_PCA_DISPLAY_INPUT_REUSE_PREDECESSORS",
            "_HANDOFF_PRESENTATION_PREDECESSORS",
        }:
            previous.extend(entries)
    for operation, (old, current) in _REVIEWED.items():
        contract = node_registry.get_metadata(operation).resolved_execution_contract()
        # Earlier registrations stay historically pinned. New exact consumers
        # have their own independent current-identity assertions.
        if operation == "model.mcr_als":
            # Truth-grid admission changed; no application-compatibility alias
            # is inferred from that change. The current contract also binds axis
            # semantics explicitly; historical registrations stay exact.
            assert contract.digest == "d1ed762e88caf1095a9ecb777fac02701994d2846223807b3266e7af305e8eea"
            assert not authority.saved_state_predecessor_is_compatible(
                current,
                contract.digest,
                operation_id=operation,
                serializer=contract.payload["fitted_state_serializer"],
            )
        else:
            assert contract.digest == current or authority.saved_state_predecessor_is_compatible(
                current,
                contract.digest,
                operation_id=operation,
                serializer=contract.payload["fitted_state_serializer"],
            )
        serializer = contract.payload["fitted_state_serializer"]
        entries = [entry for entry in new if entry.operation_id == operation]
        expected = {old}
        for entry in previous:
            if entry.operation_id == operation:
                expected.update((entry.predecessor_digest, entry.consumer_digest))
                # Previously reviewed consumers remain supported exactly as before.
                assert authority.saved_state_predecessor_is_compatible(
                    entry.predecessor_digest, entry.consumer_digest, operation_id=operation, serializer=entry.serializer
                )
        assert {entry.predecessor_digest for entry in entries} == expected
        assert len(entries) == len(expected)
        for predecessor in expected:
            assert authority.saved_state_predecessor_is_compatible(
                predecessor, current, operation_id=operation, serializer=serializer
            )
            assert not authority.saved_state_predecessor_is_compatible(
                current, predecessor, operation_id=operation, serializer=serializer
            )
            for wrong in (
                {"operation_id": "model.other", "serializer": serializer},
                {"operation_id": operation, "serializer": "wrong/1"},
            ):
                assert not authority.saved_state_predecessor_is_compatible(predecessor, current, **wrong)
        assert not authority.saved_state_predecessor_is_compatible("0" * 64, current, operation_id=operation)
        # No source-only correction grants a previously unavailable custody capability.
        try:
            before = fitted_state_custody_capability(serializer, old)
        except FittedStateCustodyError:
            with pytest.raises(FittedStateCustodyError):
                fitted_state_custody_capability(serializer, current)
        else:
            assert fitted_state_custody_capability(serializer, current).custody_class == before.custody_class
