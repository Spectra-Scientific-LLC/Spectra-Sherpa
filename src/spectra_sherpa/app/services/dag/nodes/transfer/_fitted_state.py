"""One fitted-state envelope authority for canonical transfer producers.

DS, PDS, and SWS differ in their scientific fit and application kernels, but
the trust boundary around their portable fitted state is identical.  Keeping
contract digest lookup, envelope creation, and verification here prevents a
security fix from landing in only part of the transfer family.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import ClassVar, Protocol, cast

from . import _core


class _TransferProducer(Protocol):
    metadata: object

    def validate_fitted_state(self, state: object) -> dict[str, object]: ...


def source_contract_digest(producer: _TransferProducer) -> str:
    metadata = cast(object, producer.metadata)
    contract = metadata.resolved_execution_contract()  # type: ignore[attr-defined]
    if contract is None:  # pragma: no cover - import-time binding is mandatory
        raise RuntimeError("transfer execution contract is unavailable")
    return str(contract.digest)


class TransferFittedStateEnvelopeAuthority:
    """Shared, fail-closed envelope methods for DS/PDS/SWS nodes."""

    fitted_state_serializer: ClassVar[str]

    def make_fitted_state_envelope(self: _TransferProducer, state: Mapping[str, object]) -> dict[str, object]:
        return _core.make_state_envelope(
            state,
            source_operation_id=self.metadata.node_type,  # type: ignore[attr-defined]
            serializer=self.fitted_state_serializer,  # type: ignore[attr-defined]
            source_contract_digest=source_contract_digest(self),
            normalize=self.validate_fitted_state,
        )

    def verify_fitted_state_envelope(self: _TransferProducer, value: object) -> dict[str, object]:
        return _core.verify_state_envelope(
            value,
            source_operation_id=self.metadata.node_type,  # type: ignore[attr-defined]
            serializer=self.fitted_state_serializer,  # type: ignore[attr-defined]
            source_contract_digest=source_contract_digest(self),
            normalize=self.validate_fitted_state,
        )


__all__ = ["TransferFittedStateEnvelopeAuthority", "source_contract_digest"]
