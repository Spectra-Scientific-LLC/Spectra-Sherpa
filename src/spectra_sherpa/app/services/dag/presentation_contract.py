"""Renderer-neutral scientific presentation contracts for canonical DAG nodes.

The contract names scientific views and the output ports that supply them.  It
contains no Plotly, Vue, HTTP, or desktop concepts: applications choose a
renderer for the closed ``kind`` while numerical values remain owned by the
node outputs.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from spectra_sherpa.app.types import ensure_type_registry_loaded, type_registry

PRESENTATION_SCHEMA_VERSION = "spectrasherpa-node-presentation/1"
EXECUTED_PRESENTATION_SCHEMA_VERSION = "spectrasherpa-executed-presentation/1"
PORTABLE_PRESENTATION_MANIFEST_VERSION = "spectrasherpa-portable-presentation-manifest/1"

PRESENTATION_KINDS = frozenset(
    {
        "component_explained_variance",
        "component_loadings",
        "component_scores",
        "categorical_labels",
        "chromatogram",
        "classification_model",
        "classification_comparison",
        "classification_responses",
        "comparison",
        "confusion_matrix",
        "decomposition_result",
        "deployment_response",
        "explained_variance",
        "export_artifact",
        "fitted_model",
        "loading_matrix",
        "mass_spectrum",
        "model_reference",
        "numeric_matrix",
        "numeric_vector",
        "out_of_fold_evidence",
        "pca_explained_variance",
        "pca_loadings",
        "pca_scores",
        "pls_explained_variance",
        "pls_loadings",
        "pls_scores",
        "plsda_loadings",
        "plsda_scores",
        "peak_table",
        "regression_model",
        "metric_record",
        "model_summary",
        "salient_features",
        "scalar",
        "score_matrix",
        "spectral_dataset",
        "spectral_image",
        "spectral_transfer_model",
        "spectrum",
        "statistics_summary",
        "structured_record",
        "target_matrix",
        "t2_q_diagnostics",
        "time_series",
        "validation_result",
        "variable_importance",
        "voltammogram",
        "visualization",
        "workflow_snapshot",
        "regression_coefficients",
        "regression_comparison",
        "variable_profile",
    }
)
PRESENTATION_MODES = frozenset({"model_summary", "plot", "record", "table"})

_PLOT_VIEW_MODES = frozenset(
    {
        "category_counts",
        "component_plot",
        "confusion_matrix",
        "image",
        "loading_plot",
        "peak_plot",
        "plot",
        "predicted_vs_actual",
        "score_plot",
        "spectral_plot",
        "time_series_plot",
        "variable_profile",
    }
)


@dataclass(frozen=True)
class ScientificPresentation:
    """One scientist-facing view sourced from named canonical output ports."""

    presentation_id: str
    label: str
    kind: str
    source_ports: tuple[str, ...]
    modes: tuple[str, ...]
    description: str = ""

    def __post_init__(self) -> None:
        if not self.presentation_id or not self.label:
            raise ValueError("scientific presentation id and label must be non-empty")
        if self.kind not in PRESENTATION_KINDS:
            raise ValueError(f"unknown scientific presentation kind {self.kind!r}")
        if not self.source_ports or len(set(self.source_ports)) != len(self.source_ports):
            raise ValueError("scientific presentation source ports must be non-empty and unique")
        if not self.modes or len(set(self.modes)) != len(self.modes):
            raise ValueError("scientific presentation modes must be non-empty and unique")
        unknown_modes = set(self.modes) - PRESENTATION_MODES
        if unknown_modes:
            raise ValueError(f"unknown scientific presentation modes {sorted(unknown_modes)!r}")

    def as_dict(self) -> dict[str, object]:
        return {
            "presentation_id": self.presentation_id,
            "label": self.label,
            "kind": self.kind,
            "source_ports": list(self.source_ports),
            "modes": list(self.modes),
            "description": self.description,
        }


@dataclass(frozen=True)
class NodePresentationContract:
    """Closed presentation vocabulary for one registered node type."""

    default_presentation: str
    presentations: tuple[ScientificPresentation, ...]
    schema_version: str = PRESENTATION_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != PRESENTATION_SCHEMA_VERSION:
            raise ValueError("unsupported node presentation schema")
        identifiers = tuple(item.presentation_id for item in self.presentations)
        if not identifiers or len(set(identifiers)) != len(identifiers):
            raise ValueError("presentation identifiers must be non-empty and unique")
        if self.default_presentation not in identifiers:
            raise ValueError("default presentation must name one declared presentation")

    def validate_ports(self, output_ports: set[str]) -> None:
        for presentation in self.presentations:
            missing = set(presentation.source_ports) - output_ports
            if missing:
                raise ValueError(
                    f"presentation {presentation.presentation_id!r} references unknown output ports {sorted(missing)!r}"
                )

    def as_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "default_presentation": self.default_presentation,
            "presentations": [item.as_dict() for item in self.presentations],
        }

    @property
    def digest(self) -> str:
        encoded = json.dumps(
            self.as_dict(), sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()


def _workbench_modes(view_modes: Sequence[str]) -> tuple[str, ...]:
    modes: list[str] = []
    if "table" in view_modes:
        modes.append("table")
    if "record" in view_modes or "artifact_summary" in view_modes:
        modes.append("record")
    if "model_summary" in view_modes:
        modes.append("model_summary")
    if set(view_modes) & _PLOT_VIEW_MODES:
        modes.append("plot")
    return tuple(modes)


def derive_node_presentation_contract(metadata: Any) -> NodePresentationContract:
    """Derive the closed default presentation from typed output authority.

    Node-owned contracts remain authoritative when a result needs a curated
    multi-view ordering or a more precise scientific label. Every other node
    receives a deterministic one-view-per-port projection from the canonical
    type registry. Unclassified ports remain visible in the census but cannot
    become a scientist-facing presentation by guesswork.
    """

    declared = metadata.presentation_contract
    if declared is not None:
        if not isinstance(declared, NodePresentationContract):
            raise ValueError("node presentation contract must be a NodePresentationContract")
        declared.validate_ports({port.name for port in metadata.output_ports or ()})
        return declared

    ensure_type_registry_loaded()
    presentations: list[ScientificPresentation] = []
    for port in metadata.output_ports or ():
        type_def = type_registry.resolve(port.type_ref)
        modes = _workbench_modes(type_def.view_modes)
        if type_def.scientific_kind == "unclassified" or not modes:
            continue
        presentations.append(
            ScientificPresentation(
                presentation_id=port.name,
                label=port.label or port.name,
                kind=type_def.scientific_kind,
                source_ports=(port.name,),
                modes=modes,
                description=port.description or type_def.description,
            )
        )
    if not presentations:
        raise ValueError(f"{metadata.node_type} has no classified scientist-facing output port")
    default = next(
        (item.presentation_id for item in presentations if item.presentation_id == "default"),
        presentations[0].presentation_id,
    )
    return NodePresentationContract(default_presentation=default, presentations=tuple(presentations))


def describe_executed_presentations(
    metadata: Any,
    descriptors: Mapping[str, Mapping[str, object]],
) -> dict[str, object]:
    """Bind one resolved presentation contract to materialized output meaning.

    The record carries no numerical values. Content categories are the union
    of the already-materialized source descriptors, so a later local consent
    policy can decide what may leave a device without reinterpreting a result.
    """

    contract = derive_node_presentation_contract(metadata)
    materialized: list[dict[str, object]] = []
    for presentation in contract.presentations:
        if not all(port in descriptors for port in presentation.source_ports):
            continue
        categories = sorted(
            {
                str(category)
                for port in presentation.source_ports
                for category in descriptors[port].get("content_categories", [])
            }
        )
        materialized.append(
            {
                **presentation.as_dict(),
                "content_categories": categories,
            }
        )
    return {
        "schema_version": EXECUTED_PRESENTATION_SCHEMA_VERSION,
        "contract_digest": contract.digest,
        "contract": contract.as_dict(),
        "presentations": materialized,
    }


def build_portable_presentation_manifest(nodes: Sequence[Mapping[str, object]]) -> dict[str, object]:
    """Build the closed presentation/content policy for a portable DAG.

    ``nodes`` contains only stable node and operation identities. This helper
    does not execute the DAG and does not include scientific values.
    """

    ensure_type_registry_loaded()
    manifest_nodes: list[dict[str, object]] = []
    for node in nodes:
        node_id = node.get("node_id")
        operation_id = node.get("operation_id")
        if not isinstance(node_id, str) or not node_id or not isinstance(operation_id, str) or not operation_id:
            raise ValueError("portable presentation node identities must be non-empty strings")
        metadata = _registered_node_metadata(operation_id)
        contract = derive_node_presentation_contract(metadata)
        presentations: list[dict[str, object]] = []
        for presentation in contract.presentations:
            categories = sorted(
                {
                    category
                    for source_port in presentation.source_ports
                    for category in _declared_port_categories(metadata, source_port)
                }
            )
            presentations.append({**presentation.as_dict(), "content_categories": categories})
        manifest_nodes.append(
            {
                "node_id": node_id,
                "operation_id": operation_id,
                "contract_digest": contract.digest,
                "contract": contract.as_dict(),
                "presentations": presentations,
            }
        )
    unsigned: dict[str, object] = {
        "schema_version": PORTABLE_PRESENTATION_MANIFEST_VERSION,
        "type_registry_version": type_registry.version,
        "nodes": manifest_nodes,
    }
    encoded = json.dumps(unsigned, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    return {**unsigned, "manifest_digest": hashlib.sha256(encoded).hexdigest()}


def _registered_node_metadata(operation_id: str) -> Any:
    from spectra_sherpa.app.services.dag.node_base import node_registry

    return node_registry.get_metadata(operation_id)


def _declared_port_categories(metadata: Any, port_name: str) -> tuple[str, ...]:
    port = next((item for item in metadata.output_ports or () if item.name == port_name), None)
    if port is None:
        raise ValueError(f"presentation source port {port_name!r} is not declared")
    return type_registry.resolve(port.type_ref).content_categories


def build_scientific_presentation_census(metadata_rows: Sequence[Any]) -> dict[str, object]:
    """Build the all-node presentation/disposition authority."""

    ensure_type_registry_loaded()
    nodes: list[dict[str, object]] = []
    presentation_count = 0
    explicit_count = 0
    derived_count = 0
    no_view_count = 0
    for metadata in sorted(metadata_rows, key=lambda item: item.node_type):
        contract = derive_node_presentation_contract(metadata)
        authority = "explicit" if metadata.presentation_contract is not None else "derived_from_type_registry"
        explicit_count += authority == "explicit"
        derived_count += authority == "derived_from_type_registry"
        presented_ports = {
            port_name for presentation in contract.presentations for port_name in presentation.source_ports
        }
        dispositions: list[dict[str, object]] = []
        for port in metadata.output_ports or ():
            type_def = type_registry.resolve(port.type_ref)
            if port.name in presented_ports:
                disposition = "scientist_facing_presentation"
            else:
                disposition = "no_scientist_view_unclassified"
                no_view_count += 1
            dispositions.append(
                {
                    "port_name": port.name,
                    "type_ref": port.type_ref,
                    "scientific_kind": type_def.scientific_kind,
                    "disposition": disposition,
                }
            )
        presentation_count += len(contract.presentations)
        nodes.append(
            {
                "node_type": metadata.node_type,
                "label": metadata.label,
                "authority": authority,
                "contract_digest": contract.digest,
                "contract": contract.as_dict(),
                "output_port_dispositions": dispositions,
            }
        )
    payload: dict[str, object] = {
        "schema_version": "spectrasherpa-scientific-presentation-census/1",
        "presentation_schema_version": PRESENTATION_SCHEMA_VERSION,
        "type_registry_version": type_registry.version,
        "aggregates": {
            "registered_nodes": len(nodes),
            "explicit_contracts": explicit_count,
            "derived_contracts": derived_count,
            "scientist_facing_presentations": presentation_count,
            "fail_closed_unclassified_ports": no_view_count,
        },
        "nodes": nodes,
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    return {"census_digest": hashlib.sha256(encoded).hexdigest(), **payload}


__all__ = [
    "EXECUTED_PRESENTATION_SCHEMA_VERSION",
    "NodePresentationContract",
    "PRESENTATION_KINDS",
    "PRESENTATION_MODES",
    "PRESENTATION_SCHEMA_VERSION",
    "PORTABLE_PRESENTATION_MANIFEST_VERSION",
    "ScientificPresentation",
    "build_scientific_presentation_census",
    "build_portable_presentation_manifest",
    "describe_executed_presentations",
    "derive_node_presentation_contract",
]
