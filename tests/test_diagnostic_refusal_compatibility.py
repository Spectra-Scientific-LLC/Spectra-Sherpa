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
        "45dfeb78fef8ebf91d22edf584342724a5f5d8ca3532649ff86ea7347db0900f",
    ),
    "classification.plsda": (
        "526a54177bad1ec421ec319c031f6ba322fa431e7235cf35604e14d7ecf23f6c",
        "f8cb93e6a0b919054f55680e6d4e994bd310d122d3dfb0e40b095569cef53ef9",
    ),
    "classification.simca": (
        "16dfeba33f742c80aad2e8ae2dcccb42d430215b20b2fdfb77179f821db52034",
        "bd702d6c67ccd5e0450b7c084ee7c7b0d20a530a3eb364a5e53d1a07caf07bc8",
    ),
    "model.fitted_linear_regression": (
        "10b125ffb88229b92cfe1eac67e5717117cfdf57d485b3e370abb2ef8910f6a7",
        "0249dc0427231232a1b543a5bdce6d1f1eceb5231719b41d0e65d52082bb4026",
    ),
    "model.fitted_pcr": (
        "577777179c36fedf0338c84a003e9080aa8879043e2ad0e19e7dccc5f618c201",
        "27f4c22c6ae6fb575c7e9cb2882de79143b166274356e739346cbe2d6f7f9a22",
    ),
    "model.fitted_svr": (
        "cde922310dc4713ab5349720f865595fee13c8c2a53b60f68708ceed9882bae0",
        "2ac66187fb0e4fc00934d9630e68128888cd8c2c2c2d172194ee5ca550798fbc",
    ),
    "model.ica": (
        "053d4bf663ea8242c2ad400629f7a9436035a826781346966cb62d95a19cac5a",
        "94c112265e78275a70a033f9ac7fbe5b9e6f24b99a7c2d5652ec2e76c8033d8f",
    ),
    "model.mcr_als": (
        "ce5de4a28b2258eed1ad44509ae8f0aa9952f7f8b7d5097116ad55f5b21ba9d3",
        "50cd24ddedd39194455a526922e3923b9fb6c2acef12aba4b9fe18b5be940a9b",
    ),
    "model.pca": (
        "5e809716a8266c4ddd5fb3902b8a68c264019fd05237bdb1397f664ae31dea10",
        "7d89eafc1c61c6ed5b121cea3ed06e74045dea4c7b5381275c54facf9b0b8924",
    ),
}


def test_source_only_registrations_preserve_all_previously_supported_producers():
    new = authority._DIAGNOSTIC_REFUSAL_PREDECESSORS
    assert {entry.operation_id for entry in new} == set(_REVIEWED)
    previous = list(authority.saved_state_compatibilities())
    for name, entries in vars(authority).items():
        if name.endswith("_PREDECESSORS") and name != "_DIAGNOSTIC_REFUSAL_PREDECESSORS":
            previous.extend(entries)
    for operation, (old, current) in _REVIEWED.items():
        contract = node_registry.get_metadata(operation).resolved_execution_contract()
        assert contract.digest == current
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
