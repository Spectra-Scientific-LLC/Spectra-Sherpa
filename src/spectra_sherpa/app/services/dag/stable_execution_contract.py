"""Bind registered nodes directly to their sole immutable execution identity."""

from __future__ import annotations

import hashlib
import inspect
import json
from dataclasses import asdict
from types import ModuleType
from typing import Any, Iterable, Mapping, Type

from spectra_sherpa.app.services.dag.node_base import Node, NodeMetadata
from spectra_sherpa.execution_contract_vocabulary import (
    CustomTrustClass,
    DatasetRankPolicy,
    LifecycleKind,
    ManagedOptimizationEligibility,
    NodeExecutionContract,
    RuntimeFamily,
    WorkerCapability,
)


class StableExecutionContractError(ValueError):
    """A reviewed stable/application node is missing or contradicts its contract."""


def _canonical_digest(value: Mapping[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False).encode("utf-8")
    ).hexdigest()


def _parameter_schema(metadata: NodeMetadata) -> dict[str, Any]:
    """Keep scientist-visible parameter semantics, not UI prose, in identity."""

    return {
        "node_type": metadata.node_type,
        "parameters": [
            {
                key: value
                for key, value in asdict(parameter).items()
                if key
                in {
                    "name",
                    "param_type",
                    "default",
                    "min_value",
                    "max_value",
                    "step",
                    "options",
                    "required",
                    "visible_when",
                }
            }
            for parameter in metadata.parameters
        ],
    }


def _source_component(component: ModuleType) -> dict[str, str]:
    """Name one in-tree implementation module and its exact source digest."""

    if component.__name__ != "spectra_sherpa" and not component.__name__.startswith("spectra_sherpa."):
        raise StableExecutionContractError(
            "implementation_modules may contain only in-tree spectra_sherpa modules; "
            f"bind external runtime {component.__name__!r} through a pinned implementation_distribution"
        )

    try:
        source = inspect.getsource(component).encode("utf-8")
    except OSError:
        # A frozen/packaged distribution (e.g. a PyInstaller desktop bundle)
        # does not retain readable .py source text, so inspect.getsource()
        # cannot recover it here. Node registration -- and the app itself --
        # must not crash merely because this one optional managed-profile
        # identity is uncomputable in this deployment; degrade the same way
        # _distribution_component() does for a missing package below: change
        # the closure instead of silently looking equivalent to a real
        # source digest.
        digest = hashlib.sha256(f"{component.__name__}=source-unavailable".encode("utf-8")).hexdigest()
        return {"component_id": component.__name__, "digest": digest}
    return {"component_id": component.__name__, "digest": hashlib.sha256(source).hexdigest()}


def _distribution_component(distribution: str, version: str) -> dict[str, str]:
    """Name a contract-pinned external implementation version.

    Contract identity must be portable: importing the registry on a machine
    with a missing or newer optional dependency cannot change the contract
    digest.  Live installation state is checked separately by the runtime
    attestation.  The implementation closure therefore binds the reviewed
    version from ``runtime_requirements``, never the importing host's version.
    """

    return {
        "component_id": f"distribution.{distribution}",
        "digest": hashlib.sha256(f"{distribution}={version}".encode("utf-8")).hexdigest(),
    }


def implementation_digest_for_components(components: Iterable[Mapping[str, str]]) -> str:
    """Return the one digest naming a closed, sorted implementation closure."""

    normalized = sorted(
        ({"component_id": item["component_id"], "digest": item["digest"]} for item in components),
        key=lambda item: item["component_id"],
    )
    return _canonical_digest({"components": normalized})


def _ports(metadata: NodeMetadata, direction: str) -> list[dict[str, Any]]:
    ports = metadata.input_ports if direction == "input" else metadata.output_ports
    if ports is None:
        raise StableExecutionContractError(
            f"{metadata.node_type} must declare typed {direction} ports before M4.3 contract binding"
        )
    return [
        {
            "name": port.name,
            "type_ref": port.type_ref,
            "required": port.required,
            "variadic": port.variadic,
            "accepted_data_roles": sorted(port.accepted_data_roles or []),
        }
        for port in ports
    ]


def _mutable_ports(value: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Project an immutable contract payload back to its canonical port shape."""

    return [
        {
            "name": str(port["name"]),
            "type_ref": str(port["type_ref"]),
            "required": bool(port["required"]),
            "variadic": bool(port["variadic"]),
            "accepted_data_roles": [str(role) for role in port["accepted_data_roles"]],
        }
        for port in value
    ]


def bind_stable_execution_contract(
    node_class: Type[Node],
    *,
    runtime_family: RuntimeFamily,
    lifecycle_kind: LifecycleKind,
    implementation_id: str,
    implementation_version: str,
    required_worker_capabilities: tuple[WorkerCapability, ...],
    managed_optimization_eligibility: tuple[ManagedOptimizationEligibility, ...],
    sample_effect: str,
    feature_effect: str,
    axis_effect: str,
    unit_effect: str,
    resource_hints: Mapping[str, int],
    license_id: str,
    help_reference: str,
    implementation_modules: tuple[ModuleType, ...] = (),
    implementation_distributions: tuple[str, ...] = (),
    runtime_requirements: tuple[tuple[str, str], ...] = (),
    managed_optimization_profiles: tuple[str, ...] = (),
    citations: tuple[str, ...] = (),
    fitted_state_serializer: str | None = None,
    deterministic: bool = True,
    seed_parameter: str | None = None,
    target_access: str = "none",
    group_access: str = "none",
    supervised_task: str = "none",
    input_rank_policy: DatasetRankPolicy = DatasetRankPolicy.REQUIRES_2D,
) -> NodeExecutionContract:
    """Attach and return the one full contract for a reviewed node class.

    The implementation digest names a documented direct closure: the node's
    defining module, each explicitly supplied in-tree helper/adapter module,
    and relevant external distribution versions.  It is not a claim that all
    transitive runtime code has undergone M4.7 re-admission custody.
    """

    metadata = node_class.get_metadata()
    if metadata.execution_contract is not None:
        raise StableExecutionContractError(f"{metadata.node_type} already has an execution contract")
    state_bound = lifecycle_kind.value in {"fitted_transform", "fitted_model", "artifact_application"}
    if state_bound != (fitted_state_serializer is not None):
        raise StableExecutionContractError(
            f"{metadata.node_type} fitted-state serializer must match its declared lifecycle"
        )
    declared_parameters = {parameter.name: parameter for parameter in metadata.parameters}
    if deterministic and seed_parameter is not None:
        raise StableExecutionContractError(f"{metadata.node_type} deterministic contract may not name a seed")
    if not deterministic:
        parameter = declared_parameters.get(seed_parameter or "")
        if parameter is None or parameter.param_type != "number":
            raise StableExecutionContractError(
                f"{metadata.node_type} stochastic contract must name one declared numeric seed parameter"
            )
    node_module = inspect.getmodule(node_class)
    if node_module is None:
        raise StableExecutionContractError(f"cannot locate source module for {metadata.node_type}")
    requirement_versions = dict(runtime_requirements)
    if len(requirement_versions) != len(runtime_requirements):
        raise StableExecutionContractError(f"{metadata.node_type} repeats a runtime requirement")
    unpinned_distributions = sorted(set(implementation_distributions) - requirement_versions.keys())
    if unpinned_distributions:
        raise StableExecutionContractError(
            f"{metadata.node_type} implementation distributions lack pinned runtime requirements: "
            + ", ".join(unpinned_distributions)
        )

    components = [_source_component(node_module)]
    components.extend(_source_component(module) for module in implementation_modules)
    components.extend(
        _distribution_component(distribution, requirement_versions[distribution])
        for distribution in implementation_distributions
    )
    if len({component["component_id"] for component in components}) != len(components):
        raise StableExecutionContractError(f"{metadata.node_type} implementation closure repeats a component")
    components.sort(key=lambda component: component["component_id"])
    payload = {
        "contract_version": "4.0",
        "operation_id": metadata.node_type,
        "runtime_family": runtime_family.value,
        "custom_trust_class": CustomTrustClass.NOT_APPLICABLE.value,
        "lifecycle_kind": lifecycle_kind.value,
        "implementation_id": implementation_id,
        "implementation_version": implementation_version,
        "implementation_digest": implementation_digest_for_components(components),
        "implementation_components": components,
        "parameter_schema_digest": _canonical_digest(_parameter_schema(metadata)),
        "semantic_inputs": _ports(metadata, "input"),
        "semantic_outputs": _ports(metadata, "output"),
        "target_access": target_access,
        "group_access": group_access,
        "supervised_task": supervised_task,
        "input_rank_policy": input_rank_policy.value,
        "sample_effect": sample_effect,
        "feature_effect": feature_effect,
        "axis_effect": axis_effect,
        "unit_effect": unit_effect,
        "deterministic": deterministic,
        "seed_parameter": seed_parameter,
        "fitted_state_serializer": fitted_state_serializer,
        "required_worker_capabilities": [capability.value for capability in required_worker_capabilities],
        "resource_hints": dict(resource_hints),
        "managed_optimization_eligibility": [eligibility.value for eligibility in managed_optimization_eligibility],
        "managed_optimization_profiles": list(managed_optimization_profiles),
        "runtime_requirements": [
            {"distribution": distribution, "version": version} for distribution, version in runtime_requirements
        ],
        "citations": list(citations),
        "license_id": license_id,
        "help_reference": help_reference,
    }
    contract = NodeExecutionContract.from_dict(payload)
    metadata.execution_contract = contract
    ensure_registered_execution_contract(metadata)
    return contract


def ensure_registered_execution_contract(metadata: NodeMetadata) -> NodeExecutionContract:
    """Fail closed if the registry metadata drifts from its execution truth."""

    contract = metadata.resolved_execution_contract()
    if contract is None:
        raise StableExecutionContractError(f"{metadata.node_type} has no immutable execution contract")
    payload = contract.payload
    if payload["operation_id"] != metadata.node_type:
        raise StableExecutionContractError(f"{metadata.node_type} registry identity does not match its contract")
    if _mutable_ports(payload["semantic_inputs"]) != _ports(metadata, "input") or _mutable_ports(
        payload["semantic_outputs"]
    ) != _ports(metadata, "output"):
        raise StableExecutionContractError(
            f"{metadata.node_type} typed ports do not match immutable execution contract"
        )
    return contract


def execution_contract_digest(metadata: NodeMetadata) -> str:
    """Return one registered node's required immutable contract digest."""

    contract = metadata.resolved_execution_contract()
    if contract is None:
        raise StableExecutionContractError(f"{metadata.node_type} has no immutable execution contract")
    digest = contract.digest
    if not isinstance(digest, str) or len(digest) != 64:
        raise StableExecutionContractError(f"{metadata.node_type} has an invalid execution contract digest")
    return digest


__all__ = [
    "StableExecutionContractError",
    "bind_stable_execution_contract",
    "ensure_registered_execution_contract",
    "execution_contract_digest",
    "implementation_digest_for_components",
]
