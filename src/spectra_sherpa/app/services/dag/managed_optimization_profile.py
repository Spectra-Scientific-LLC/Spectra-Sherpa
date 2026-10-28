"""Managed optimization profile identities derived only from the live canonical node registry."""

from __future__ import annotations

import hashlib
import importlib.metadata
import json
from dataclasses import dataclass
from functools import cached_property, lru_cache
from typing import Callable

from spectra_sherpa.app.services.dag.node_base import node_registry
from spectra_sherpa.execution_contract_vocabulary import ManagedOptimizationEligibility, NodeExecutionContract

MANAGED_OPTIMIZATION_PLS_PROFILE_ID = "first_party_pls"
MANAGED_OPTIMIZATION_PROFILE_VERSION = "8"
MANAGED_OPTIMIZATION_RUNTIME_ATTESTATION_VERSION = "spectra-managed-optimization-runtime-attestation/2"
MANAGED_OPTIMIZATION_PROFILE_SCHEMA_VERSION = "spectra-managed-optimization-profile/2"


class ManagedOptimizationProfileError(ValueError):
    """The live registry cannot prove an exact managed optimization profile identity."""


@lru_cache(maxsize=128)
def _installed_version(distribution: str, resolver: Callable[[str], str]) -> str:
    """Snapshot installed distributions for this process, never expected versions.

    Changing an installed runtime requires a process restart. Explicit test or
    qualification resolvers bypass this cache, and failures are not cached.
    Every attestation still checks the observed version against its contract.
    """
    return resolver(distribution)


@dataclass(frozen=True)
class ManagedOptimizationRuntimeRequirement:
    distribution: str
    version: str

    def as_dict(self) -> dict[str, str]:
        return {"distribution": self.distribution, "version": self.version}


@dataclass(frozen=True)
class ManagedOptimizationRuntimeAttestation:
    profile_id: str
    profile_version: str
    profile_digest: str
    operation_ids: tuple[str, ...]
    distributions: tuple[ManagedOptimizationRuntimeRequirement, ...]

    @property
    def digest(self) -> str:
        return _digest(
            {
                "schema_version": MANAGED_OPTIMIZATION_RUNTIME_ATTESTATION_VERSION,
                "profile_id": self.profile_id,
                "profile_version": self.profile_version,
                "profile_digest": self.profile_digest,
                "operation_ids": list(self.operation_ids),
                "distributions": [requirement.as_dict() for requirement in self.distributions],
            }
        )

    def as_dict(self) -> dict[str, object]:
        return {
            "schema_version": MANAGED_OPTIMIZATION_RUNTIME_ATTESTATION_VERSION,
            "profile_id": self.profile_id,
            "profile_version": self.profile_version,
            "profile_digest": self.profile_digest,
            "operation_ids": list(self.operation_ids),
            "distributions": [requirement.as_dict() for requirement in self.distributions],
            "digest": self.digest,
        }


def _digest(payload: dict[str, object]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True)
class ManagedOptimizationProfile:
    """A deterministic view of contracts that name one managed optimization profile.

    The object contains the registry contracts themselves. It does not copy
    operation semantics into a second profile table.
    """

    profile_id: str
    profile_version: str
    contracts: tuple[NodeExecutionContract, ...]

    def __post_init__(self) -> None:
        operation_ids = [contract.payload["operation_id"] for contract in self.contracts]
        if not self.profile_id or not operation_ids:
            raise ManagedOptimizationProfileError(
                "managed optimization profile requires an identity and registered contracts"
            )
        if operation_ids != sorted(operation_ids) or len(operation_ids) != len(set(operation_ids)):
            raise ManagedOptimizationProfileError(
                "managed optimization profile contracts must be uniquely sorted by operation"
            )
        for contract in self.contracts:
            if self.profile_id not in contract.payload["managed_optimization_profiles"]:
                raise ManagedOptimizationProfileError("profile contains a contract that does not name its membership")

    @cached_property
    def operation_ids(self) -> frozenset[str]:
        return frozenset(contract.payload["operation_id"] for contract in self.contracts)

    @cached_property
    def digest(self) -> str:
        return _digest(
            {
                "schema_version": MANAGED_OPTIMIZATION_PROFILE_SCHEMA_VERSION,
                "profile_id": self.profile_id,
                "profile_version": self.profile_version,
                "operations": [
                    {
                        "operation_id": contract.payload["operation_id"],
                        "contract_digest": contract.digest,
                    }
                    for contract in self.contracts
                ],
            }
        )

    def operation(self, operation_id: str) -> NodeExecutionContract:
        for contract in self.contracts:
            if contract.payload["operation_id"] == operation_id:
                return contract
        raise ManagedOptimizationProfileError(
            f"{operation_id} is not in managed optimization profile {self.profile_id}"
        )

    def assert_contract(self, contract: NodeExecutionContract) -> None:
        registered = self.operation(str(contract.payload["operation_id"]))
        if registered.digest != contract.digest:
            raise ManagedOptimizationProfileError("execution contract differs from the live canonical registry")
        if ManagedOptimizationEligibility.DEVELOPMENT.value not in contract.payload["managed_optimization_eligibility"]:
            raise ManagedOptimizationProfileError("managed optimization profile contract lacks development eligibility")

    def runtime_requirements(
        self,
        operation_ids: tuple[str, ...] | None = None,
    ) -> tuple[ManagedOptimizationRuntimeRequirement, ...]:
        """Return the closed runtime requirements declared by selected live contracts."""

        selected_ids = tuple(sorted(self.operation_ids if operation_ids is None else operation_ids))
        if not selected_ids:
            raise ManagedOptimizationProfileError("runtime requirements need at least one operation")
        requirements: dict[str, str] = {}
        for operation_id in selected_ids:
            contract = self.operation(operation_id)
            for requirement in contract.payload["runtime_requirements"]:
                distribution = str(requirement["distribution"])
                version = str(requirement["version"])
                previous = requirements.setdefault(distribution, version)
                if previous != version:
                    raise ManagedOptimizationProfileError(
                        "managed optimization profile requires conflicting "
                        f"{distribution} versions: {previous} and {version}"
                    )
        return tuple(
            ManagedOptimizationRuntimeRequirement(distribution, version)
            for distribution, version in sorted(requirements.items())
        )

    def runtime_attestation(
        self,
        operation_ids: tuple[str, ...] | None = None,
        *,
        version_resolver: Callable[[str], str] | None = None,
    ) -> ManagedOptimizationRuntimeAttestation:
        resolver = (
            version_resolver
            if version_resolver is not None
            else (lambda distribution: _installed_version(distribution, importlib.metadata.version))
        )
        selected_ids = tuple(sorted(self.operation_ids if operation_ids is None else operation_ids))
        observed: list[ManagedOptimizationRuntimeRequirement] = []
        for requirement in self.runtime_requirements(selected_ids):
            distribution = requirement.distribution
            expected = requirement.version
            try:
                actual = resolver(distribution)
            except importlib.metadata.PackageNotFoundError as exc:
                raise ManagedOptimizationProfileError(
                    f"{self.profile_id} requires {distribution}=={expected}; it is not installed"
                ) from exc
            if actual != expected:
                raise ManagedOptimizationProfileError(
                    f"{self.profile_id} requires {distribution}=={expected}; observed {actual}"
                )
            observed.append(ManagedOptimizationRuntimeRequirement(distribution, actual))
        return ManagedOptimizationRuntimeAttestation(
            profile_id=self.profile_id,
            profile_version=self.profile_version,
            profile_digest=self.digest,
            operation_ids=selected_ids,
            distributions=tuple(observed),
        )


def managed_optimization_profile(profile_id: str = MANAGED_OPTIMIZATION_PLS_PROFILE_ID) -> ManagedOptimizationProfile:
    """Resolve one profile from registered contracts, with no operation map."""

    # Before application startup freezes the registry it is still being built;
    # do not retain a partial profile. Registry identity also isolates SDK/tests.
    if node_registry.is_frozen:
        return _frozen_profile(node_registry, profile_id, MANAGED_OPTIMIZATION_PROFILE_VERSION)
    return _build_profile(node_registry, profile_id, MANAGED_OPTIMIZATION_PROFILE_VERSION)


@lru_cache(maxsize=16)
def _frozen_profile(registry, profile_id: str, profile_version: str) -> ManagedOptimizationProfile:
    return _build_profile(registry, profile_id, profile_version)


def _build_profile(registry, profile_id: str, profile_version: str) -> ManagedOptimizationProfile:

    contracts = []
    for metadata in registry.list_nodes():
        contract = metadata.resolved_execution_contract()
        if contract is not None and profile_id in contract.payload["managed_optimization_profiles"]:
            contracts.append(contract)
    contracts.sort(key=lambda contract: str(contract.payload["operation_id"]))
    return ManagedOptimizationProfile(profile_id, profile_version, tuple(contracts))


__all__ = [
    "MANAGED_OPTIMIZATION_PLS_PROFILE_ID",
    "MANAGED_OPTIMIZATION_PROFILE_VERSION",
    "MANAGED_OPTIMIZATION_PROFILE_SCHEMA_VERSION",
    "MANAGED_OPTIMIZATION_RUNTIME_ATTESTATION_VERSION",
    "ManagedOptimizationProfile",
    "ManagedOptimizationProfileError",
    "ManagedOptimizationRuntimeAttestation",
    "ManagedOptimizationRuntimeRequirement",
    "managed_optimization_profile",
]
