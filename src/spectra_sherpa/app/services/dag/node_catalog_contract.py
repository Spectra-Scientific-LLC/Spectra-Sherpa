"""Authoritative, deterministic catalog projections for canonical-DAG work.

This module deliberately projects *registered metadata*; it does not infer a
scientific contract from a node name or its runtime family. A node without an
execution contract is visibly incomplete and local-only until C2 contracts or
removes it.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Iterable

from spectra_sherpa.app.services.dag.managed_optimization_profile import (
    ManagedOptimizationProfileError,
    managed_optimization_profile,
)
from spectra_sherpa.app.services.dag.node_base import NodeMetadata
from spectra_sherpa.app.services.dag.runtime_dependencies import distribution_is_installed

NODE_LIBRARY_SCHEMA_VERSION = "spectra-node-library/8"
NODE_CONTRACT_CENSUS_SCHEMA_VERSION = "spectra-node-contract-census/6"


@dataclass(frozen=True)
class NodeDependencyReadiness:
    """The bounded, non-secret dependency answer a client may display."""

    ready: bool
    blockers: tuple[str, ...] = ()
    remediation: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {
            "ready": self.ready,
            "blockers": list(self.blockers),
            "remediation": list(self.remediation),
        }


def dependency_readiness(metadata: NodeMetadata) -> NodeDependencyReadiness:
    """Report implementation prerequisites without attempting execution."""

    if metadata.requires_scp and not distribution_is_installed("spectrochempy"):
        return NodeDependencyReadiness(
            ready=False,
            blockers=("spectrochempy_unavailable",),
            remediation=("Install the optional SpectroChemPy support: pip install 'spectra-sherpa[scp]'.",),
        )
    return NodeDependencyReadiness(ready=True)


def _port_rows(metadata: NodeMetadata, direction: str) -> list[dict[str, Any]]:
    ports = metadata.input_ports if direction == "input" else metadata.output_ports
    return [
        {
            "name": port.name,
            "type_ref": port.type_ref,
            "required": port.required,
            "variadic": port.variadic,
            "accepted_data_roles": list(port.accepted_data_roles or []),
        }
        for port in ports or []
    ]


def _managed_optimization_profile_classification(metadata: NodeMetadata) -> dict[str, object]:
    """Classify one catalog entry against the sole managed optimization profile.

    This is a registry-derived visibility record, not a second admission
    authority.  ``validation_graph`` consumes the profile directly.  The
    census makes the complement of that closed set equally explicit so an
    incomplete or merely well-typed node cannot be mistaken for managed support.
    """

    contract = metadata.resolved_execution_contract() if metadata.execution_contract is not None else None
    profile = managed_optimization_profile()
    common = {
        "profile_id": profile.profile_id,
        "profile_version": profile.profile_version,
        "profile_digest": profile.digest,
    }
    if metadata.node_type not in profile.operation_ids:
        return {
            **common,
            "eligible": False,
            "reason": ("outside_managed_optimization_profile" if contract is not None else "uncontracted_local_only"),
        }
    if contract is None:
        return {
            **common,
            "eligible": False,
            "reason": "managed_optimization_profile_operation_missing_execution_contract",
        }
    try:
        profile.assert_contract(contract)
    except ManagedOptimizationProfileError:
        return {
            **common,
            "eligible": False,
            "reason": "managed_optimization_profile_contract_drift",
        }
    return {
        **common,
        "eligible": True,
        "reason": "managed_optimization_profile_exact_contract",
    }


def census_node_row(metadata: NodeMetadata) -> dict[str, Any]:
    """Return the stable, one-row-per-node census representation."""

    policy = metadata.policy
    contract = metadata.resolved_execution_contract()
    presentation = metadata.resolved_presentation_contract()
    row = {
        "node_type": metadata.node_type,
        "typed_ports": {
            # ``[]`` is the explicit typed declaration for a source node. It
            # is distinct from the legacy absence sentinel used for optional
            # output-port metadata (``None``).
            "inputs_declared": metadata.input_ports is not None,
            "outputs_declared": bool(metadata.output_ports),
            "input_ports": _port_rows(metadata, "input"),
            "output_ports": _port_rows(metadata, "output"),
        },
        "compatibility_types": {
            "input_types": list(metadata.input_types),
            "output_type": metadata.output_type,
        },
        "policy": {
            "explicit": policy is not None,
            "offload_to_pool": policy.offload_to_pool if policy else True,
        },
        "requires_scp": metadata.requires_scp,
        "contract_complete": contract is not None,
        "execution_contract": (
            {"digest": contract.digest, "payload": contract.as_dict()} if contract is not None else None
        ),
        "managed_optimization_profile": _managed_optimization_profile_classification(metadata),
    }
    if presentation is not None:
        row["presentation_contract"] = {"digest": presentation.digest, "payload": presentation.as_dict()}
    typed_ports = row["typed_ports"]
    if typed_ports["inputs_declared"] and typed_ports["outputs_declared"]:
        typed_port_status = "typed_input_output"
    elif typed_ports["inputs_declared"]:
        typed_port_status = "typed_input_only"
    elif typed_ports["outputs_declared"]:
        typed_port_status = "typed_output_only"
    else:
        typed_port_status = "untyped"
    profile = row["managed_optimization_profile"]
    payload = contract.payload if contract is not None else None
    row["catalog_classification"] = {
        "contract_status": "contracted" if contract is not None else "uncontracted_local_only",
        "runtime_family": payload["runtime_family"] if payload else "unclassified",
        "lifecycle_kind": payload["lifecycle_kind"] if payload else "unclassified",
        "typed_port_status": typed_port_status,
        "managed_optimization_eligible": profile["eligible"],
        "reason": profile["reason"],
    }
    return row


def build_node_contract_census(nodes: Iterable[NodeMetadata]) -> dict[str, Any]:
    """Build a canonical, registry-derived census with aggregate burn-down data."""

    metadata_rows = list(nodes)
    declared_node_types = [metadata.node_type for metadata in metadata_rows]
    if len(declared_node_types) != len(set(declared_node_types)):
        raise ValueError("node contract census requires every node type exactly once")
    rows = sorted((census_node_row(node) for node in metadata_rows), key=lambda row: row["node_type"])
    aggregates = {
        "total_nodes": len(rows),
        "both_typed_ports": sum(
            bool(row["typed_ports"]["inputs_declared"] and row["typed_ports"]["outputs_declared"]) for row in rows
        ),
        "missing_typed_output_ports": sum(not row["typed_ports"]["outputs_declared"] for row in rows),
        "canonical_dataset_output_aliases": sum(
            row["compatibility_types"]["output_type"] == "SherpaDataset" for row in rows
        ),
        "requires_scp": sum(row["requires_scp"] for row in rows),
        "without_explicit_policy": sum(not row["policy"]["explicit"] for row in rows),
        "default_pool_offload": sum(row["policy"]["offload_to_pool"] for row in rows),
        "contracted_nodes": sum(row["contract_complete"] for row in rows),
        "uncontracted_local_only": sum(not row["contract_complete"] for row in rows),
        "artifact_application_nodes": sum(
            row["catalog_classification"]["lifecycle_kind"] == "artifact_application" for row in rows
        ),
        "managed_optimization_profile_eligible": sum(row["managed_optimization_profile"]["eligible"] for row in rows),
        "outside_managed_optimization_profile": sum(
            not row["managed_optimization_profile"]["eligible"] for row in rows
        ),
        "managed_optimization_profile_contract_drift": sum(
            row["managed_optimization_profile"]["reason"] == "managed_optimization_profile_contract_drift"
            for row in rows
        ),
    }
    return {"schema_version": NODE_CONTRACT_CENSUS_SCHEMA_VERSION, "aggregates": aggregates, "nodes": rows}


def canonical_json(payload: dict[str, Any]) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")


def census_digest(census: dict[str, Any]) -> str:
    return hashlib.sha256(canonical_json(census)).hexdigest()


def validate_census_help_references(census: dict[str, Any], *, package_root: Path) -> None:
    """Require every contract help target to exist and name its operation.

    Version 0.6 deliberately uses a small set of scientist-facing category
    pages. A path merely existing is insufficient: the target page must also
    contain the exact backticked operation identity, so a broad or accidental
    remap cannot satisfy the release gate.
    """

    failures: dict[str, str] = {}
    for row in census["nodes"]:
        node_type = row["node_type"]
        contract = row["execution_contract"]
        reference = contract["payload"]["help_reference"] if contract is not None else None
        if not isinstance(reference, str) or not reference:
            failures[node_type] = "missing help_reference"
            continue
        relative = PurePosixPath(reference)
        if relative.is_absolute() or ".." in relative.parts or relative.suffix != ".md":
            failures[node_type] = f"unsafe or non-Markdown help_reference {reference!r}"
            continue
        if relative.parts[:2] != ("docs", "nodes"):
            failures[node_type] = f"help_reference is outside docs/nodes: {reference!r}"
            continue
        target = package_root.joinpath(*relative.parts)
        if not target.is_file():
            failures[node_type] = f"help target does not exist: {reference!r}"
            continue
        if f"`{node_type}`" not in target.read_text(encoding="utf-8"):
            failures[node_type] = f"help target does not name `{node_type}`: {reference!r}"
    if failures:
        raise ValueError(f"unresolved node help references: {failures}")


def node_library_cache_identity(nodes: Iterable[NodeMetadata]) -> str:
    """Return a cache identity sensitive to execution and visible catalog drift.

    The execution census deliberately excludes mutable presentation copy.  The
    workbench still has to refresh when a node moves family or its scientist-
    facing name, purpose, parameters, or ports change, so bind that projection
    independently while retaining the execution-census digest as the suffix.
    """

    metadata_rows = list(nodes)
    visible_catalog = {
        "nodes": [
            {
                "node_type": metadata.node_type,
                "category": metadata.category,
                "label": metadata.label,
                "description": metadata.description,
                "parameters": [
                    {
                        "name": parameter.name,
                        "label": parameter.label,
                        "param_type": parameter.param_type,
                        "default": parameter.default,
                        "min_value": parameter.min_value,
                        "max_value": parameter.max_value,
                        "step": parameter.step,
                        "options": parameter.options,
                        "description": parameter.description,
                        "required": parameter.required,
                        "category": parameter.category,
                        "visible_when": parameter.visible_when,
                    }
                    for parameter in metadata.parameters
                ],
                "input_ports": [
                    {
                        "name": port.name,
                        "type_ref": port.type_ref,
                        "required": port.required,
                        "label": port.label,
                        "description": port.description,
                    }
                    for port in metadata.input_ports or []
                ],
                "output_ports": [
                    {
                        "name": port.name,
                        "type_ref": port.type_ref,
                        "required": port.required,
                        "label": port.label,
                        "description": port.description,
                    }
                    for port in metadata.output_ports or []
                ],
                "help_url": metadata.help_url,
            }
            for metadata in sorted(metadata_rows, key=lambda row: row.node_type)
        ]
    }
    visible_digest = hashlib.sha256(canonical_json(visible_catalog)).hexdigest()

    census = build_node_contract_census(metadata_rows)
    return f"{NODE_LIBRARY_SCHEMA_VERSION}:{visible_digest}:{census_digest(census)}"


def render_census_markdown(census: dict[str, Any]) -> str:
    """Render the human report from the same census payload, never a manual list."""

    aggregates = census["aggregates"]
    lines = [
        "# Node-contract census",
        "",
        "This report is generated from the live canonical node registry. Only an exact member of the named",
        "first-party managed optimization profile may enter hosted campaign execution. Every other canonical",
        "DAG node is explicitly local-only for managed optimization; this is not a quality or canonicality rank.",
        "",
        "| Measure | Count |",
        "| --- | ---: |",
    ]
    for key, value in aggregates.items():
        lines.append(f"| {key.replace('_', ' ')} | {value} |")
    lines.extend(
        [
            "",
            "## Registered nodes",
            "",
            "| Node type | Contract status | Runtime/lifecycle | SCP dependency | "
            "Typed ports | Managed optimization profile | Reason |",
            "| --- | --- | --- | --- | --- | --- |",
        ]
    )
    for row in census["nodes"]:
        lines.append(
            "| {node_type} | {status} | {runtime}/{lifecycle} | {scp} | {ports} | {managed} | {reason} |".format(
                node_type=row["node_type"],
                status=row["catalog_classification"]["contract_status"],
                runtime=row["catalog_classification"]["runtime_family"],
                lifecycle=row["catalog_classification"]["lifecycle_kind"],
                scp="yes" if row["requires_scp"] else "no",
                ports=row["catalog_classification"]["typed_port_status"],
                managed="yes" if row["managed_optimization_profile"]["eligible"] else "no",
                reason=row["managed_optimization_profile"]["reason"],
            )
        )
    return "\n".join(lines) + "\n"
