"""Canonical scientific descriptions of materialized DAG output ports.

The executor owns scientific values; the workbench only renders them.  This
module turns one raw output value plus its declared ``type_ref`` into a small,
closed description without changing, flattening, or copying the value itself.
It is deliberately independent of HTTP and frontend code so persisted runs,
exports, and a future local hybrid policy can consume the same authority.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

import numpy as np

from spectra_sherpa.app.lib.sherpa_dataset import SherpaDataset
from spectra_sherpa.app.services.dag.regression_comparison import REGRESSION_COMPARISON_SCHEMA
from spectra_sherpa.app.types import ensure_type_registry_loaded, parse_type_ref, type_registry

SCIENTIFIC_VALUE_SCHEMA = "spectrasherpa-scientific-value/1"


@dataclass(frozen=True)
class ScientificDimension:
    """One exact runtime dimension and its scientific role."""

    role: str
    size: int
    labels: tuple[str, ...] | None = None

    def as_dict(self) -> dict[str, object]:
        payload: dict[str, object] = {"role": self.role, "size": self.size}
        if self.labels is not None:
            payload["labels"] = list(self.labels)
        return payload


@dataclass(frozen=True)
class ScientificValueDescriptor:
    """Closed, JSON-safe description of one materialized output port."""

    port_name: str
    type_ref: str
    label: str
    scientific_kind: str
    view_kind: str
    shape: tuple[int, ...] | None
    dimensions: tuple[ScientificDimension, ...]
    view_modes: tuple[str, ...]
    content_categories: tuple[str, ...]
    shape_valid: bool
    shape_issue: str | None = None

    def as_dict(self) -> dict[str, object]:
        return {
            "schema_version": SCIENTIFIC_VALUE_SCHEMA,
            "port_name": self.port_name,
            "type_ref": self.type_ref,
            "label": self.label,
            "scientific_kind": self.scientific_kind,
            "view_kind": self.view_kind,
            "shape": list(self.shape) if self.shape is not None else None,
            "dimensions": [dimension.as_dict() for dimension in self.dimensions],
            "view_modes": list(self.view_modes),
            "content_categories": list(self.content_categories),
            "shape_valid": self.shape_valid,
            "shape_issue": self.shape_issue,
        }


def _rectangular_sequence_shape(value: Sequence[object]) -> tuple[int, ...]:
    """Return the exact rank of one JSON-like rectangular sequence.

    Heterogeneous lists are records, not matrices.  They retain only their
    outer length instead of acquiring a fabricated second dimension.
    """

    rows = len(value)
    if rows == 0:
        return (0,)
    first = value[0]
    if not isinstance(first, (list, tuple)):
        return (rows,)
    width = len(first)
    if all(isinstance(row, (list, tuple)) and len(row) == width for row in value):
        return (rows, width)
    return (rows,)


def _plot_shape(value: Mapping[str, object]) -> tuple[int, ...] | None:
    """Describe a plot's represented observations without calling it a dataset."""

    data = value.get("data")
    if not isinstance(data, list) or not data:
        return None

    # A regression-comparison plot may contain one marker trace per target
    # plus a 1:1 reference line.  Those traces are not one rectangular
    # matrix, but the bound metadata states the exact number of compared
    # observations.  The two displayed coordinates are reference and
    # prediction, so this remains an honest plot-point shape.
    metadata = value.get("metadata")
    if isinstance(metadata, Mapping) and metadata.get("source_schema") == REGRESSION_COMPARISON_SCHEMA:
        n_rows = metadata.get("n_rows")
        if isinstance(n_rows, int) and not isinstance(n_rows, bool) and n_rows >= 0:
            return (n_rows, 2)
    if all(isinstance(row, (list, tuple)) for row in data):
        return _rectangular_sequence_shape(data)
    if not all(isinstance(trace, Mapping) for trace in data):
        return None

    # One heatmap/contour trace represents its z matrix.
    if len(data) == 1:
        trace = data[0]
        z = trace.get("z")
        if isinstance(z, list):
            return _rectangular_sequence_shape(z)
        x = trace.get("x")
        y = trace.get("y")
        if isinstance(x, list) and isinstance(y, list) and len(x) == len(y):
            return (len(x), 2)

    # Multiple traces do not necessarily share observations.  Reporting one
    # aggregate matrix shape would be scientifically false.
    return None


def _runtime_shape(value: object, *, type_name: str, view_kind: str) -> tuple[int, ...] | None:
    if view_kind in {"model", "model_reference", "artifact", "metric_record", "structured_record"}:
        return None
    if isinstance(value, SherpaDataset):
        return tuple(int(size) for size in value.shape)
    if isinstance(value, np.ndarray):
        shape = tuple(int(size) for size in value.shape)
    elif isinstance(value, np.generic):
        shape = ()
    elif isinstance(value, (list, tuple)):
        shape = _rectangular_sequence_shape(value)
    elif isinstance(value, Mapping):
        if view_kind == "visualization":
            shape = _plot_shape(value)
        elif isinstance(value.get("shape"), (list, tuple)) and all(
            isinstance(size, int) and not isinstance(size, bool) and size >= 0 for size in value["shape"]
        ):
            shape = tuple(int(size) for size in value["shape"])
        elif isinstance(value.get("n_samples"), int) and isinstance(value.get("n_features"), int):
            shape = (int(value["n_samples"]), int(value["n_features"]))
        elif isinstance(value.get("data"), list):
            shape = _rectangular_sequence_shape(value["data"])
        else:
            shape = None
    elif isinstance(value, (int, float, bool)):
        shape = ()
    else:
        shape = None

    # A one-response TargetMatrix is scientifically samples × one target,
    # even when its wire representation uses a compact one-dimensional list.
    if type_name == "TargetMatrix" and shape is not None and len(shape) == 1:
        return (shape[0], 1)
    return shape


def _dimension_roles(shape: tuple[int, ...] | None, declared_roles: tuple[str, ...]) -> tuple[str, ...]:
    if shape is None:
        return ()
    roles = list(declared_roles[: len(shape)])
    while len(roles) < len(shape):
        roles.append(f"axis_{len(roles) + 1}")
    return tuple(roles)


def describe_scientific_value(
    value: object,
    *,
    port_name: str,
    type_ref: str,
    label: str,
) -> ScientificValueDescriptor:
    """Describe one output port using its canonical type and actual value."""

    ensure_type_registry_loaded()
    type_def = type_registry.resolve(type_ref)
    type_name, _, _ = parse_type_ref(type_ref)
    shape = _runtime_shape(value, type_name=type_name, view_kind=type_def.view_kind)
    roles = _dimension_roles(shape, type_def.dimension_roles)

    shape_valid = True
    shape_issue: str | None = None
    if shape is not None and type_def.ranks and len(shape) not in type_def.ranks:
        shape_valid = False
        shape_issue = (
            f"{type_name} permits rank {list(type_def.ranks)} but the materialized value has rank {len(shape)}"
        )

    categories = type_def.content_categories
    dimension_labels: dict[str, tuple[str, ...]] = {}
    if type_name == "ClassificationComparison":
        dimension_labels["comparison_field"] = (
            "Sample",
            "Reference",
            "Predicted",
            "Correct",
            "Role",
        )
    elif type_name == "RegressionComparison":
        dimension_labels["comparison_field"] = (
            "Sample",
            "Target",
            "Reference",
            "Predicted",
            "Residual",
            "Role",
        )
    elif type_name == "ExplainedVarianceMatrix":
        dimension_labels["variance_domain"] = ("X", "Y")
    # A predicted-vs-actual projection contains both the reference values and
    # sample-level predictions.  It must never become a future egress bypass
    # merely because its outer type is Visualization.
    if type_name == "Visualization" and isinstance(value, Mapping):
        plot_type = value.get("type")
        metadata = value.get("metadata")
        if (
            plot_type == "predicted_vs_actual"
            or (isinstance(metadata, Mapping) and metadata.get("type") == "RegressionTest")
            or (isinstance(metadata, Mapping) and metadata.get("source_schema") == REGRESSION_COMPARISON_SCHEMA)
        ):
            categories = ("reference_targets", "sample_level_results", "visualizations")
            if shape is not None and len(shape) == 2:
                roles = ("held_out_sample", "actual_predicted_value")

    return ScientificValueDescriptor(
        port_name=port_name,
        type_ref=type_ref,
        label=label or port_name,
        scientific_kind=type_def.scientific_kind,
        view_kind=type_def.view_kind,
        shape=shape,
        dimensions=tuple(
            ScientificDimension(
                role=role,
                size=size,
                labels=("Actual", "Predicted") if role == "actual_predicted_value" else dimension_labels.get(role),
            )
            for role, size in zip(roles, shape or (), strict=True)
        ),
        view_modes=type_def.view_modes,
        content_categories=categories,
        shape_valid=shape_valid,
        shape_issue=shape_issue,
    )


def describe_node_outputs(metadata: Any, result: object) -> dict[str, dict[str, object]]:
    """Describe every materialized, declared output port for one node."""

    ports = list(metadata.output_ports or [])
    if not ports:
        return {}

    declared_names = {port.name for port in ports}
    if isinstance(result, Mapping) and any(name in result for name in declared_names):
        values = result
    elif len(ports) == 1:
        values = {ports[0].name: result}
    else:
        values = {}

    descriptors: dict[str, dict[str, object]] = {}
    for port in ports:
        if port.name not in values:
            continue
        descriptors[port.name] = describe_scientific_value(
            values[port.name],
            port_name=port.name,
            type_ref=port.type_ref,
            label=port.label,
        ).as_dict()
    return descriptors


def build_scientific_output_semantics_census(metadata_rows: Sequence[Any]) -> dict[str, object]:
    """Project all declared output ports through the canonical type registry."""

    ensure_type_registry_loaded()
    nodes: list[dict[str, object]] = []
    port_count = 0
    unclassified_ports = 0

    for metadata in sorted(metadata_rows, key=lambda item: item.node_type):
        ports: list[dict[str, object]] = []
        for port in metadata.output_ports:
            type_def = type_registry.resolve(port.type_ref)
            categories = list(type_def.content_categories)
            ports.append(
                {
                    "port_name": port.name,
                    "label": port.label,
                    "type_ref": port.type_ref,
                    "scientific_kind": type_def.scientific_kind,
                    "view_kind": type_def.view_kind,
                    "permitted_ranks": list(type_def.ranks),
                    "dimension_roles": list(type_def.dimension_roles),
                    "view_modes": list(type_def.view_modes),
                    "content_categories": categories,
                }
            )
            port_count += 1
            if "unclassified" in categories:
                unclassified_ports += 1
        nodes.append(
            {
                "node_type": metadata.node_type,
                "label": metadata.label,
                "category": metadata.category,
                "output_ports": ports,
            }
        )

    payload: dict[str, object] = {
        "schema_version": "spectrasherpa-scientific-output-semantics-census/1",
        "scientific_value_schema": SCIENTIFIC_VALUE_SCHEMA,
        "type_registry_version": type_registry.version,
        "aggregates": {
            "registered_nodes": len(nodes),
            "declared_output_ports": port_count,
            "registered_types": len(type_registry.list_types()),
            "fail_closed_unclassified_ports": unclassified_ports,
        },
        "nodes": nodes,
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return {"census_digest": hashlib.sha256(encoded).hexdigest(), **payload}


__all__ = [
    "SCIENTIFIC_VALUE_SCHEMA",
    "ScientificDimension",
    "ScientificValueDescriptor",
    "build_scientific_output_semantics_census",
    "describe_node_outputs",
    "describe_scientific_value",
]
