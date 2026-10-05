"""Fail-closed admission for graphs copied from durable storage.

Saved workflow versions, duplicated sheets, and generic project archives are
untrusted inputs at the point where they are copied into current database
rows.  This module is the single boundary that prevents a retired or malformed
graph from becoming current merely because it was valid in an older build.

The boundary deliberately validates persistence safety rather than execution
readiness: an incomplete canvas may be saved, but every operation identity,
parameter set, edge endpoint, and canonical typed port must belong to the
current registry contract.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping
from copy import deepcopy
from dataclasses import dataclass
from typing import Any

from spectra_sherpa.app.services.dag.node_base import node_registry
from spectra_sherpa.app.types import ensure_type_registry_loaded, type_registry
from spectra_sherpa.core.node_identity import canonical_node_type
from spectra_sherpa.core.retired_classifier_parameters import (
    CURRENT_CLASSIFIER_VALIDATION_SEMANTICS,
    RETIRED_CLASSIFIER_VALIDATION_PARAMETER,
    historical_classifier_cv_folds,
)


class SavedGraphAdmissionError(ValueError):
    """Raised when durable graph content is not admissible in this build."""


@dataclass(frozen=True)
class SavedGraphAdmission:
    """Current detached graph bytes admitted without semantic translation."""

    nodes: tuple[dict[str, Any], ...]
    edges: tuple[dict[str, Any], ...]


def _refuse_retired_classifier_validation(payload: Mapping[str, Any]) -> None:
    """Refuse a classifier whose persisted output semantics are ambiguous."""

    node_type = payload.get("node_type")
    retired = RETIRED_CLASSIFIER_VALIDATION_PARAMETER.get(node_type)
    parameters = payload.get("parameters", {})
    if retired is None or not isinstance(parameters, Mapping) or retired not in parameters:
        return
    try:
        historical_classifier_cv_folds(node_type, parameters[retired])
    except ValueError as exc:
        raise SavedGraphAdmissionError(
            f"Saved workflow node '{payload.get('node_id', '?')}' retired parameter '{retired}' is malformed"
        ) from exc
    raise SavedGraphAdmissionError(
        f"Saved workflow node '{payload.get('node_id', '?')}' ({node_type}) cannot be auto-migrated: "
        "its former outputs included hidden cross-validation diagnostics that now mean calibration-fit "
        "diagnostics. Recreate the classifier node and connect an explicit held-out or grouped fold plan."
    )


def _required_text(value: Any, *, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise SavedGraphAdmissionError(f"Saved workflow {field} must be a non-empty string")
    return value


def _canonical_port_type(metadata: Any, name: str, *, direction: str) -> str | None:
    ports = metadata.output_ports if direction == "output" else metadata.input_ports
    if not ports:
        return None
    if name == "default":
        return ports[0].type_ref
    for port in ports:
        if port.name == name:
            return port.type_ref
    return None


def _validate_supplied_parameter(node_id: str, definition: Any, value: Any) -> None:
    """Validate a value that is present without requiring omitted draft values."""

    if value is None and not definition.required:
        return
    kind = definition.param_type
    if kind == "number":
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
            raise SavedGraphAdmissionError(
                f"Saved workflow node '{node_id}' parameter '{definition.name}' must be a finite number"
            )
        if definition.min_value is not None and value < definition.min_value:
            raise SavedGraphAdmissionError(
                f"Saved workflow node '{node_id}' parameter '{definition.name}' is below its minimum"
            )
        if definition.max_value is not None and value > definition.max_value:
            raise SavedGraphAdmissionError(
                f"Saved workflow node '{node_id}' parameter '{definition.name}' is above its maximum"
            )
    elif kind == "boolean" and not isinstance(value, bool):
        raise SavedGraphAdmissionError(
            f"Saved workflow node '{node_id}' parameter '{definition.name}' must be a boolean"
        )
    elif kind == "text" and not isinstance(value, str):
        raise SavedGraphAdmissionError(f"Saved workflow node '{node_id}' parameter '{definition.name}' must be text")
    elif kind == "string_list" and not (isinstance(value, list) and all(isinstance(item, str) for item in value)):
        raise SavedGraphAdmissionError(
            f"Saved workflow node '{node_id}' parameter '{definition.name}' must be a list of strings"
        )
    elif kind == "select" and definition.options:
        options = [item["value"] if isinstance(item, dict) else item for item in definition.options]
        if value not in options:
            raise SavedGraphAdmissionError(
                f"Saved workflow node '{node_id}' parameter '{definition.name}' is not an admitted option"
            )


def _assert_acyclic(node_ids: set[str], edges: list[tuple[str, str, str, str]]) -> None:
    outgoing: dict[str, list[str]] = {node_id: [] for node_id in node_ids}
    indegree = {node_id: 0 for node_id in node_ids}
    for source, target, _source_port, _target_port in edges:
        outgoing[source].append(target)
        indegree[target] += 1

    ready = [node_id for node_id, count in indegree.items() if count == 0]
    visited = 0
    while ready:
        source = ready.pop()
        visited += 1
        for target in outgoing[source]:
            indegree[target] -= 1
            if indegree[target] == 0:
                ready.append(target)
    if visited != len(node_ids):
        raise SavedGraphAdmissionError("Saved workflow graph contains a cycle")


def admit_saved_workflow_graph(
    nodes: Iterable[Mapping[str, Any]],
    edges: Iterable[Mapping[str, Any]],
    *,
    classifier_validation_semantics: str | None = None,
    current_graph: bool = False,
) -> SavedGraphAdmission:
    """Admit a durable graph against the current authoritative node registry.

    This function performs no mutation and returns only after the complete
    graph passes.  Callers must invoke it before clearing, inserting, or
    cloning database rows. ``classifier_validation_semantics`` is required for
    durable snapshots containing a current classifier. ``current_graph`` is
    reserved for new SDK construction and live database rows admitted after
    the Alembic editable-graph migration; it must never be used for an archive
    or version snapshot.
    """

    materialized_nodes = [deepcopy(dict(node)) for node in nodes]
    materialized_edges = [deepcopy(dict(edge)) for edge in edges]
    if classifier_validation_semantics not in (None, CURRENT_CLASSIFIER_VALIDATION_SEMANTICS):
        raise SavedGraphAdmissionError("Saved workflow classifier-validation semantics are not current")
    current_classifier_semantics = current_graph or (
        classifier_validation_semantics == CURRENT_CLASSIFIER_VALIDATION_SEMANTICS
    )
    for payload in materialized_nodes:
        node_type = payload.get("node_type")
        if node_type not in RETIRED_CLASSIFIER_VALIDATION_PARAMETER:
            continue
        _refuse_retired_classifier_validation(payload)
        if not current_classifier_semantics:
            raise SavedGraphAdmissionError(
                f"Saved workflow node '{payload.get('node_id', '?')}' ({node_type}) has no current "
                "classifier-validation authority. Recreate the classifier node and connect an explicit "
                "held-out or grouped fold plan."
            )
    ensure_type_registry_loaded()
    node_ids: set[str] = set()
    metadata_by_id: dict[str, Any] = {}

    for index, payload in enumerate(materialized_nodes):
        if not isinstance(payload, Mapping):
            raise SavedGraphAdmissionError(f"Saved workflow node {index} must be an object")
        node_id = _required_text(payload.get("node_id"), field=f"node {index} ID")
        node_type = canonical_node_type(_required_text(payload.get("node_type"), field=f"node {index} type"))
        payload["node_type"] = node_type
        if node_id in node_ids:
            raise SavedGraphAdmissionError(f"Saved workflow contains duplicate node ID: {node_id}")
        node_ids.add(node_id)

        parameters = payload.get("parameters", {})
        if not isinstance(parameters, Mapping):
            raise SavedGraphAdmissionError(f"Saved workflow node '{node_id}' parameters must be an object")
        try:
            metadata = node_registry.get_metadata(node_type)
        except KeyError as exc:
            raise SavedGraphAdmissionError(
                f"Saved workflow node '{node_id}' is not admitted by the current registry: {exc}"
            ) from exc

        # Canonical contracts are closed.  Local-only nodes remain inspectable
        # while their catalog contracts are completed in the C2 repair track.
        if metadata.execution_contract is not None:
            declared = {parameter.name for parameter in metadata.parameters}
            unknown = sorted(set(parameters) - declared)
            if unknown:
                raise SavedGraphAdmissionError(
                    f"Saved workflow node '{node_id}' has undeclared parameter(s): {', '.join(unknown)}"
                )
        definitions = {parameter.name: parameter for parameter in metadata.parameters}
        if metadata.execution_contract is not None:
            for name, value in parameters.items():
                definition = definitions.get(name)
                if definition is not None:
                    _validate_supplied_parameter(node_id, definition, value)

        # Once every required value is available, invoke the node's full
        # canonicalizer so cross-field scientific constraints remain one
        # authority. A draft may omit required values; persistence is not an
        # execution-readiness decision.
        complete = all(
            not definition.required or definition.default is not None or definition.name in parameters
            for definition in metadata.parameters
        )
        if metadata.draft_parameter_validator is not None:
            try:
                metadata.draft_parameter_validator(
                    {
                        **{definition.name: definition.default for definition in metadata.parameters},
                        **parameters,
                    }
                )
            except (TypeError, ValueError) as exc:
                raise SavedGraphAdmissionError(
                    f"Saved workflow node '{node_id}' parameters are not admitted: {exc}"
                ) from exc
        elif complete:
            try:
                node_registry.create_node(node_type, node_id, dict(parameters)).validate_parameters()
            except (TypeError, ValueError) as exc:
                raise SavedGraphAdmissionError(
                    f"Saved workflow node '{node_id}' parameters are not admitted: {exc}"
                ) from exc
        metadata_by_id[node_id] = metadata

    edge_keys: set[tuple[str, str, str, str]] = set()
    for index, payload in enumerate(materialized_edges):
        if not isinstance(payload, Mapping):
            raise SavedGraphAdmissionError(f"Saved workflow edge {index} must be an object")
        source = _required_text(payload.get("from_node_id"), field=f"edge {index} source")
        target = _required_text(payload.get("to_node_id"), field=f"edge {index} target")
        source_port = _required_text(payload.get("from_output", "default"), field=f"edge {index} output port")
        target_port = _required_text(payload.get("to_input", "default"), field=f"edge {index} input port")
        if source not in node_ids or target not in node_ids:
            raise SavedGraphAdmissionError(f"Saved workflow edge {index} references a missing node")
        if source == target:
            raise SavedGraphAdmissionError(f"Saved workflow edge {index} is a self-loop")
        key = (source, target, source_port, target_port)
        if key in edge_keys:
            raise SavedGraphAdmissionError(f"Saved workflow contains duplicate edge {index}")
        edge_keys.add(key)

        source_metadata = metadata_by_id[source]
        target_metadata = metadata_by_id[target]
        source_type = _canonical_port_type(source_metadata, source_port, direction="output")
        target_type = _canonical_port_type(target_metadata, target_port, direction="input")
        contracted = source_metadata.execution_contract is not None or target_metadata.execution_contract is not None
        if contracted and (source_type is None or target_type is None):
            raise SavedGraphAdmissionError(
                f"Saved workflow edge {index} does not name ports declared by its canonical node contracts"
            )
        if contracted and source_type is not None and target_type is not None:
            compatible, reason = type_registry.is_compatible(source_type, target_type)
            if compatible:
                from .model_edge_contracts import model_edge_error

                reason = model_edge_error(source_metadata, source_port, target_metadata, target_port)
                compatible = reason is None
            if not compatible:
                raise SavedGraphAdmissionError(f"Saved workflow edge {index} is not type-compatible: {reason}")

    _assert_acyclic(node_ids, list(edge_keys))
    return SavedGraphAdmission(tuple(materialized_nodes), tuple(materialized_edges))


__all__ = [
    "CURRENT_CLASSIFIER_VALIDATION_SEMANTICS",
    "SavedGraphAdmission",
    "SavedGraphAdmissionError",
    "admit_saved_workflow_graph",
]
