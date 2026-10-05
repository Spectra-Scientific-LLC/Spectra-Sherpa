"""Neutral closed vocabulary shared by SDK identities and live DAG metadata.

This module must remain free of SDK and application imports.  The SDK package
has a compatibility façade that imports application symbols, so importing a
vocabulary through ``spectra_sherpa.sdk`` from the DAG registry would create a
cycle.  Both layers therefore import these exact enum classes directly.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType
from typing import Any, Mapping

IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,127}$")


def is_portable_identifier(value: object) -> bool:
    """Return whether *value* has the closed portable contract-identifier form."""

    return isinstance(value, str) and bool(IDENTIFIER_RE.fullmatch(value))


class RuntimeFamily(StrEnum):
    SHERPA_NATIVE = "sherpa_native"
    SPECTROCHEMPY = "spectrochempy"
    APPROVED_CUSTOM = "approved_custom"


class LifecycleKind(StrEnum):
    DATA_SOURCE = "data_source"
    STATELESS_TRANSFORM = "stateless_transform"
    FITTED_TRANSFORM = "fitted_transform"
    FITTED_MODEL = "fitted_model"
    ARTIFACT_APPLICATION = "artifact_application"
    EVALUATOR = "evaluator"


class TargetAccess(StrEnum):
    NONE = "none"
    OPTIONAL = "optional"
    FIT_ONLY = "fit_only"
    REQUIRED = "required"


class GroupAccess(StrEnum):
    NONE = "none"
    FIT_ONLY = "fit_only"
    OPTIONAL = "optional"
    REQUIRED = "required"


class WorkerCapability(StrEnum):
    READ_DATASET = "read_dataset"
    READ_MODEL_ARTIFACT = "read_model_artifact"
    READ_CANONICAL_FITTED_ARTIFACT = "read_canonical_fitted_artifact"
    WRITE_MODEL_ARTIFACT = "write_model_artifact"


class ManagedOptimizationEligibility(StrEnum):
    LOCAL = "local"
    DEVELOPMENT = "development"
    CONFIRMATION = "confirmation"
    FULL_REFIT = "full_refit"


class SupervisedTask(StrEnum):
    """Closed scientific task identity for fitted-model/evaluator pairing."""

    NONE = "none"
    REGRESSION = "regression"
    CLASSIFICATION = "classification"


class DatasetRankPolicy(StrEnum):
    """Closed admission rule for SherpaDataset inputs to one operation."""

    REQUIRES_2D = "requires_2d"
    PRESERVES_ND = "preserves_nd"
    PROJECTS_TO_2D = "projects_to_2d"


class CustomTrustClass(StrEnum):
    NOT_APPLICABLE = "not_applicable"
    LOCAL_UNTRUSTED = "local_untrusted"
    APPROVED_DEVELOPMENT = "approved_development"


# The immutable payload implementation is deliberately colocated with the
# neutral vocabulary rather than under ``sdk``.  The DAG registry must be able
# to bind a contract without importing the SDK facade (which imports the
# application compatibility surface).  ``sdk.execution_contract`` re-exports
# these names as its public compatibility module.
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_TYPE_REF_RE = re.compile(r"^spectrasherpa://types/[A-Za-z0-9_]+/[0-9]+\.[0-9]+$")
_SEMANTIC_PORT_FIELDS = frozenset({"name", "type_ref", "required", "variadic", "accepted_data_roles"})
_EFFECTS = {
    "sample_effect": frozenset({"preserves_samples", "filters_samples", "aggregates_samples", "generates_samples"}),
    "feature_effect": frozenset(
        {"preserves_features", "filters_features", "transforms_features", "generates_features"}
    ),
    "axis_effect": frozenset({"preserves_axis", "changes_axis", "removes_axis"}),
    "unit_effect": frozenset({"preserves_units", "changes_units", "requires_compatible_units"}),
}
_RESOURCE_KEYS = frozenset({"timeout_seconds", "cpu_seconds", "memory_bytes", "temp_bytes", "max_file_bytes"})
_REQUIRED_RESOURCE_KEYS = frozenset({"timeout_seconds", "cpu_seconds", "memory_bytes"})
_FIELDS = frozenset(
    {
        "contract_version",
        "operation_id",
        "runtime_family",
        "custom_trust_class",
        "lifecycle_kind",
        "implementation_id",
        "implementation_version",
        "implementation_digest",
        "implementation_components",
        "parameter_schema_digest",
        "semantic_inputs",
        "semantic_outputs",
        "target_access",
        "group_access",
        "supervised_task",
        "input_rank_policy",
        "sample_effect",
        "feature_effect",
        "axis_effect",
        "unit_effect",
        "deterministic",
        "seed_parameter",
        "fitted_state_serializer",
        "required_worker_capabilities",
        "resource_hints",
        "managed_optimization_eligibility",
        "managed_optimization_profiles",
        "runtime_requirements",
        "citations",
        "license_id",
        "help_reference",
    }
)

# Every field has a named in-tree owner.  The field list is deliberately
# closed: accepting a new identity field without a consumer is not progress.
FIELD_CONSUMER_PLAN: Mapping[str, tuple[str, ...]] = {
    "contract_version": ("M4.8 capsule v3",),
    "operation_id": ("M4.2 catalog binding",),
    "runtime_family": ("M4.3 adapter selection",),
    "custom_trust_class": ("M4.9 package admission",),
    "lifecycle_kind": ("M4.5 fold-local lifecycle",),
    "implementation_id": ("M4.7 re-admission",),
    "implementation_version": ("M4.7 re-admission",),
    "implementation_digest": ("M4.3 contract binding",),
    "implementation_components": ("M4.3 implementation closure",),
    "parameter_schema_digest": ("M4.3 contract binding",),
    "semantic_inputs": ("M4.2 graph compatibility",),
    "semantic_outputs": ("M4.2 graph compatibility",),
    "target_access": ("M4.5 leakage defense",),
    "group_access": ("M4.5 grouped validation",),
    "supervised_task": ("canonical fitted-model/evaluator admission",),
    "input_rank_policy": ("pre-kernel dimensional admission",),
    "sample_effect": ("M4.8 evidence",),
    "feature_effect": ("M4.8 evidence",),
    "axis_effect": ("M4.4 capability envelope",),
    "unit_effect": ("M4.4 capability envelope",),
    "deterministic": ("M4.5 reproducibility",),
    "seed_parameter": ("M4.5 reproducibility",),
    "fitted_state_serializer": ("M4.10 export/import",),
    "required_worker_capabilities": ("M4.1 worker context",),
    "resource_hints": ("M4.7 resource admission",),
    "managed_optimization_eligibility": ("managed optimization admission",),
    "managed_optimization_profiles": ("managed optimization profile projection",),
    "runtime_requirements": ("managed runtime attestation",),
    "citations": ("M4.8 evidence",),
    "license_id": ("M4.6 certification",),
    "help_reference": ("M4.10 inspection",),
}


class ContractError(ValueError):
    """A canonical-DAG execution identity is malformed or ambiguous."""


def _canonical_json(value: Mapping[str, Any]) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False).encode()


def _freeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType({key: _freeze(item) for key, item in value.items()})
    if isinstance(value, list):
        return tuple(_freeze(item) for item in value)
    return value


def _identifier(value: Any, field: str) -> str:
    if not is_portable_identifier(value):
        raise ContractError(f"{field} must be a non-empty portable identifier")
    return value


def _sequence(value: Any, field: str, *, kind: str = "identifier", empty: bool = False) -> list[str]:
    if not isinstance(value, list) or (not value and not empty) or not all(isinstance(item, str) for item in value):
        raise ContractError(f"{field} must be a {'possibly empty' if empty else 'non-empty'} list of strings")
    if len(set(value)) != len(value):
        raise ContractError(f"{field} may not contain duplicates")
    if kind == "type" and not all(_TYPE_REF_RE.fullmatch(item) for item in value):
        raise ContractError(f"{field} must contain canonical semantic type URIs")
    if kind == "identifier":
        for item in value:
            _identifier(item, field)
    if kind == "citation" and not all(item and len(item) <= 512 and "\n" not in item for item in value):
        raise ContractError("citations must be non-empty single-line references")
    return value


def _semantic_ports(value: Any, field: str) -> list[dict[str, Any]]:
    """Validate one ordered, named typed-port surface.

    Port names, rather than type references, are the identities in this
    sequence. Multiple outputs may legitimately share a type (for example,
    ``X_train`` and ``X_test``), while duplicate names would make an edge
    binding ambiguous and are therefore rejected.
    """

    if not isinstance(value, list):
        raise ContractError(f"{field} must be a list of semantic port objects")
    normalized: list[dict[str, Any]] = []
    for port in value:
        if not isinstance(port, Mapping) or set(port) != _SEMANTIC_PORT_FIELDS:
            raise ContractError(f"{field} must use the closed semantic-port schema")
        name = _identifier(port["name"], f"{field} port name")
        type_ref = port["type_ref"]
        if not isinstance(type_ref, str) or not _TYPE_REF_RE.fullmatch(type_ref):
            raise ContractError(f"{field} port type_ref must be a canonical semantic type URI")
        if not isinstance(port["required"], bool):
            raise ContractError(f"{field} port required must be boolean")
        if not isinstance(port["variadic"], bool):
            raise ContractError(f"{field} port variadic must be boolean")
        accepted_data_roles = _sequence(
            port["accepted_data_roles"],
            f"{field} port accepted_data_roles",
            empty=True,
        )
        normalized.append(
            {
                "name": name,
                "type_ref": type_ref,
                "required": port["required"],
                "variadic": port["variadic"],
                "accepted_data_roles": sorted(accepted_data_roles),
            }
        )
    if len({port["name"] for port in normalized}) != len(normalized):
        raise ContractError(f"{field} may not repeat a port name")
    return normalized


def _enum(value: Any, enum: type[StrEnum], field: str) -> str:
    try:
        return enum(value).value
    except (TypeError, ValueError) as exc:
        raise ContractError(f"unknown {field}: {value!r}") from exc


def _implementation_components(value: Any) -> list[dict[str, str]]:
    if not isinstance(value, list) or not value:
        raise ContractError("implementation_components must be a non-empty list")
    normalized: list[dict[str, str]] = []
    for component in value:
        if not isinstance(component, Mapping) or set(component) != {"component_id", "digest"}:
            raise ContractError("implementation_components must use the closed component schema")
        component_id = _identifier(component["component_id"], "implementation component")
        digest = component["digest"]
        if not isinstance(digest, str) or not _SHA256_RE.fullmatch(digest):
            raise ContractError("implementation component digest must be a lowercase SHA-256 digest")
        normalized.append({"component_id": component_id, "digest": digest})
    if len({item["component_id"] for item in normalized}) != len(normalized):
        raise ContractError("implementation_components may not repeat component_id")
    return sorted(normalized, key=lambda item: item["component_id"])


def _runtime_requirements(value: Any) -> list[dict[str, str]]:
    if not isinstance(value, list):
        raise ContractError("runtime_requirements must be a list")
    normalized: list[dict[str, str]] = []
    for requirement in value:
        if not isinstance(requirement, Mapping) or set(requirement) != {"distribution", "version"}:
            raise ContractError("runtime_requirements must use the closed distribution/version schema")
        distribution = _identifier(requirement["distribution"], "runtime requirement distribution")
        version = _identifier(requirement["version"], "runtime requirement version")
        normalized.append({"distribution": distribution, "version": version})
    if len({item["distribution"] for item in normalized}) != len(normalized):
        raise ContractError("runtime_requirements may not repeat a distribution")
    return sorted(normalized, key=lambda item: item["distribution"])


def _normalize(payload: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, Mapping):
        raise ContractError("execution contract must be an object")
    unknown, missing = set(payload) - _FIELDS, _FIELDS - set(payload)
    if unknown:
        raise ContractError(f"unknown execution-contract field(s): {', '.join(sorted(unknown))}")
    if missing:
        raise ContractError(f"missing execution-contract field(s): {', '.join(sorted(missing))}")
    p = dict(payload)
    if p["contract_version"] != "4.0":
        raise ContractError("unsupported execution-contract version")
    for field in ("operation_id", "implementation_id", "implementation_version", "license_id", "help_reference"):
        p[field] = _identifier(p[field], field)
    for field in ("implementation_digest", "parameter_schema_digest"):
        if not isinstance(p[field], str) or not _SHA256_RE.fullmatch(p[field]):
            raise ContractError(f"{field} must be a lowercase SHA-256 digest")
    p["implementation_components"] = _implementation_components(p["implementation_components"])
    component_digest = hashlib.sha256(_canonical_json({"components": p["implementation_components"]})).hexdigest()
    if component_digest != p["implementation_digest"]:
        raise ContractError("implementation_digest must name the canonical implementation components")
    for field, enum in (
        ("runtime_family", RuntimeFamily),
        ("custom_trust_class", CustomTrustClass),
        ("lifecycle_kind", LifecycleKind),
        ("target_access", TargetAccess),
        ("group_access", GroupAccess),
        ("supervised_task", SupervisedTask),
        ("input_rank_policy", DatasetRankPolicy),
    ):
        p[field] = _enum(p[field], enum, field)
    if p["supervised_task"] != SupervisedTask.NONE.value and p["lifecycle_kind"] not in {
        LifecycleKind.FITTED_MODEL.value,
        LifecycleKind.ARTIFACT_APPLICATION.value,
        LifecycleKind.EVALUATOR.value,
    }:
        raise ContractError("only fitted models, artifact applications, and evaluators may declare supervised_task")
    p["semantic_inputs"] = _semantic_ports(p["semantic_inputs"], "semantic_inputs")
    p["semantic_outputs"] = _semantic_ports(p["semantic_outputs"], "semantic_outputs")
    if not p["semantic_inputs"] and not p["semantic_outputs"]:
        raise ContractError("an execution contract must declare at least one semantic input or output")
    for field, allowed in _EFFECTS.items():
        if p[field] not in allowed:
            raise ContractError(f"unknown {field}: {p[field]!r}")
    if not isinstance(p["deterministic"], bool):
        raise ContractError("deterministic must be boolean")
    if p["deterministic"]:
        if p["seed_parameter"] is not None:
            raise ContractError("deterministic nodes must not declare seed_parameter")
    else:
        p["seed_parameter"] = _identifier(p["seed_parameter"], "seed_parameter")
    state_bound = p["lifecycle_kind"] in {
        LifecycleKind.FITTED_TRANSFORM.value,
        LifecycleKind.FITTED_MODEL.value,
        LifecycleKind.ARTIFACT_APPLICATION.value,
    }
    if state_bound:
        p["fitted_state_serializer"] = _identifier(p["fitted_state_serializer"], "fitted_state_serializer")
    elif p["fitted_state_serializer"] is not None:
        raise ContractError("only fitted and artifact-application nodes may declare fitted_state_serializer")
    p["required_worker_capabilities"] = [
        _enum(item, WorkerCapability, "worker capability")
        for item in _sequence(
            p["required_worker_capabilities"],
            "required_worker_capabilities",
            empty=True,
        )
    ]
    if not isinstance(p["resource_hints"], Mapping):
        raise ContractError("resource_hints must be an object")
    hints = dict(p["resource_hints"])
    if set(hints) - _RESOURCE_KEYS or not _REQUIRED_RESOURCE_KEYS.issubset(hints):
        raise ContractError("resource_hints must use the closed limit schema")
    for key, value in hints.items():
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
            raise ContractError(f"resource_hints.{key} must be a finite positive number")
    p["resource_hints"] = hints
    p["managed_optimization_eligibility"] = [
        _enum(item, ManagedOptimizationEligibility, "managed optimization eligibility")
        for item in _sequence(p["managed_optimization_eligibility"], "managed_optimization_eligibility")
    ]
    if ManagedOptimizationEligibility.LOCAL.value not in p["managed_optimization_eligibility"]:
        raise ContractError("every OSS node must retain local eligibility")
    if (
        ManagedOptimizationEligibility.CONFIRMATION.value in p["managed_optimization_eligibility"]
        and ManagedOptimizationEligibility.DEVELOPMENT.value not in p["managed_optimization_eligibility"]
    ):
        raise ContractError("confirmation eligibility requires development eligibility")
    is_custom = p["runtime_family"] == RuntimeFamily.APPROVED_CUSTOM.value
    if is_custom != (p["custom_trust_class"] != CustomTrustClass.NOT_APPLICABLE.value):
        raise ContractError("custom_trust_class must match runtime_family")
    if p["custom_trust_class"] == CustomTrustClass.LOCAL_UNTRUSTED.value and p["managed_optimization_eligibility"] != [
        ManagedOptimizationEligibility.LOCAL.value
    ]:
        raise ContractError("local-untrusted custom nodes are local only")
    if is_custom and ManagedOptimizationEligibility.CONFIRMATION.value in p["managed_optimization_eligibility"]:
        raise ContractError("custom confirmation needs a later qualification contract")
    p["managed_optimization_profiles"] = _sequence(
        p["managed_optimization_profiles"], "managed_optimization_profiles", empty=True
    )
    if (
        p["managed_optimization_profiles"]
        and ManagedOptimizationEligibility.DEVELOPMENT.value not in p["managed_optimization_eligibility"]
    ):
        raise ContractError("managed optimization profile membership requires development eligibility")
    if (
        ManagedOptimizationEligibility.DEVELOPMENT.value in p["managed_optimization_eligibility"]
        and not p["managed_optimization_profiles"]
    ):
        raise ContractError("development-eligible nodes must name a managed optimization profile")
    p["runtime_requirements"] = _runtime_requirements(p["runtime_requirements"])
    p["citations"] = _sequence(p["citations"], "citations", kind="citation", empty=True)
    return p


@dataclass(frozen=True, init=False)
class NodeExecutionContract:
    """Validated immutable payload; construction cannot bypass contract checks.

    This M4.3 shape is an internal, pre-wire-freeze contract.  It may receive
    additive refinement before M4.8 publishes the durable capsule/wire schema;
    no cross-release payload compatibility is claimed before that freeze.
    """

    _canonical: bytes
    _payload: Mapping[str, Any]

    def __init__(self, payload: Mapping[str, Any]) -> None:
        normalized = _normalize(payload)
        object.__setattr__(self, "_canonical", _canonical_json(normalized))
        object.__setattr__(self, "_payload", _freeze(normalized))

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "NodeExecutionContract":
        return cls(payload)

    @property
    def payload(self) -> Mapping[str, Any]:
        return self._payload

    def as_dict(self) -> dict[str, Any]:
        return json.loads(self._canonical)

    @property
    def digest(self) -> str:
        return hashlib.sha256(self._canonical).hexdigest()
