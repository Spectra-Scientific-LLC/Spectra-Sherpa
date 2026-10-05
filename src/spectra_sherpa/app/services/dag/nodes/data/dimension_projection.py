"""Explicit, provenance-bound projection of n-dimensional datasets to 2-D."""

from __future__ import annotations

import copy
import hashlib
import json
from typing import Any, Mapping

import numpy as np

from spectra_sherpa.app.lib.sherpa_dataset import DatasetLayoutContext, SherpaDataset
from spectra_sherpa.app.services.dag.node_base import (
    Node,
    NodeMetadata,
    NodeParameter,
    NodePolicy,
    PortMetadata,
    register_node,
)
from spectra_sherpa.app.services.dag.stable_execution_contract import bind_stable_execution_contract
from spectra_sherpa.execution_contract_vocabulary import (
    DatasetRankPolicy,
    LifecycleKind,
    ManagedOptimizationEligibility,
    RuntimeFamily,
    WorkerCapability,
)

PROJECTION_SCHEMA = "spectrasherpa-dimension-projection/1"


def canonical_dimension_projection(value: object) -> dict[str, Any]:
    """Admit one closed inner-dimension index selection."""

    if not isinstance(value, Mapping) or set(value) != {"schema_version", "selections"}:
        raise ValueError("dimension projection must use the closed projection schema")
    if value["schema_version"] != PROJECTION_SCHEMA:
        raise ValueError("dimension projection has an unsupported schema version")
    received = value["selections"]
    if not isinstance(received, list) or len(received) > 14:
        raise ValueError("dimension projection selections must be a bounded list")
    selections: list[dict[str, int]] = []
    for item in received:
        if not isinstance(item, Mapping) or set(item) != {"dimension", "index"}:
            raise ValueError("dimension projection selection must contain exact dimension and index fields")
        dimension, index = item["dimension"], item["index"]
        if type(dimension) is not int or dimension < 1 or dimension > 14:
            raise ValueError("dimension projection dimension must be an exact positive inner-dimension index")
        if type(index) is not int or index < 0:
            raise ValueError("dimension projection index must be an exact non-negative integer")
        selections.append({"dimension": dimension, "index": index})
    if len({item["dimension"] for item in selections}) != len(selections):
        raise ValueError("dimension projection may select an inner dimension only once")
    selections.sort(key=lambda item: item["dimension"])
    return {"schema_version": PROJECTION_SCHEMA, "selections": selections}


def canonical_dimension_projection_parameters(values: dict[str, object]) -> dict[str, object]:
    values["projection"] = canonical_dimension_projection(values["projection"])
    return values


def project_dataset_to_2d(
    dataset: SherpaDataset,
    projection: Mapping[str, object],
    *,
    node_id: str | None = None,
) -> SherpaDataset:
    """Select one index from every inner mode without implicit flattening."""

    admitted = canonical_dimension_projection(projection)
    expected_dimensions = set(range(1, dataset.ndim - 1))
    selected = {item["dimension"]: item["index"] for item in admitted["selections"]}
    if set(selected) != expected_dimensions:
        raise ValueError("dimension projection must select exactly one index from every inner dimension")
    for dimension, index in selected.items():
        if index >= dataset.shape[dimension]:
            raise ValueError(f"dimension projection index is out of range for dimension {dimension}")

    projected_X = np.asarray(dataset.X)
    for dimension in sorted(selected, reverse=True):
        projected_X = np.take(projected_X, selected[dimension], axis=dimension)
    if projected_X.ndim != 2:
        raise ValueError("dimension projection did not produce a two-dimensional dataset")

    canonical = json.dumps(admitted, sort_keys=True, separators=(",", ":")).encode("utf-8")
    projection_digest = hashlib.sha256(canonical).hexdigest()
    provenance = dataset.provenance.copy()
    provenance.append(
        "selection.dimension_project",
        {"projection": admitted, "projection_digest": projection_digest},
        op_version="1.0",
        node_id=node_id,
        input_shape=tuple(dataset.shape),
        output_shape=tuple(projected_X.shape),
        state_effects=["inner_dimensions_projected"],
    )
    original_layout = dataset.layout
    mode_roles = ()
    if original_layout.mode_roles:
        mode_roles = (original_layout.mode_roles[0], original_layout.mode_roles[-1])
    layout = DatasetLayoutContext(
        kind="generic",
        source_type="dimension_projection",
        source_dtype=projected_X.dtype.str,
        source_shape=tuple(projected_X.shape),
        mode_roles=mode_roles,
        original_unfolded_shape=original_layout.original_unfolded_shape or tuple(dataset.shape),
    )
    extra = copy.deepcopy(dataset.extra)
    extra["sherpa.dimension_projection"] = {
        **admitted,
        "projection_digest": projection_digest,
        "input_scientific_digest": dataset.scientific_digest,
        "input_layout": original_layout.model_dump(mode="json", exclude_none=True),
    }
    return SherpaDataset(
        X=projected_X,
        feature_axis=dataset.feature_axis.copy() if dataset.feature_axis is not None else None,
        sample_axis=dataset.sample_axis.copy() if dataset.sample_axis is not None else None,
        target=dataset.target.copy() if dataset.target is not None else None,
        target_context=dataset.target_context.model_copy(deep=True),
        domain=dataset.domain.model_copy(deep=True),
        descriptive=dataset.descriptive.model_copy(deep=True),
        source_identity=dataset.source_identity.model_copy(deep=True),
        source_history=dataset.source_history.model_copy(deep=True),
        layout=layout,
        provenance=provenance,
        quality=dataset.quality.model_copy(deep=True),
        backend=dataset.backend,
        title=dataset.title,
        units=dataset.units,
        extra=extra,
        is_time_series=dataset.is_time_series,
        data_role=dataset.data_role,
    )


@register_node
class DimensionProjectionNode(Node):
    """Explicitly select one coordinate from every inner dataset dimension."""

    metadata = NodeMetadata(
        policy=NodePolicy(),
        node_type="selection.dimension_project",
        category="selection",
        label="Dimension Projection",
        description="Select one exact index from each inner dimension before two-dimensional analysis",
        input_types=["SherpaDataset"],
        output_type="SherpaDataset",
        input_ports=[
            PortMetadata(
                name="default",
                type_ref="spectrasherpa://types/SpectralDataset/1.0",
                required=True,
                accepted_data_roles=[],
            )
        ],
        output_ports=[
            PortMetadata(
                name="default",
                type_ref="spectrasherpa://types/SpectralDataset/1.0",
                required=True,
                accepted_data_roles=[],
            )
        ],
        parameters=[
            NodeParameter(
                name="projection",
                label="Inner Dimension Selection",
                param_type="json",
                default={"schema_version": PROJECTION_SCHEMA, "selections": []},
                required=True,
                description="One exact zero-based index for every inner dimension",
            )
        ],
        canonical_parameter_validator=canonical_dimension_projection_parameters,
    )

    async def execute(self, input_data: SherpaDataset) -> dict[str, SherpaDataset]:
        return {
            "default": project_dataset_to_2d(
                input_data,
                self.parameters["projection"],
                node_id=self.node_id,
            )
        }


bind_stable_execution_contract(
    DimensionProjectionNode,
    runtime_family=RuntimeFamily.SHERPA_NATIVE,
    lifecycle_kind=LifecycleKind.STATELESS_TRANSFORM,
    implementation_id="spectrasherpa.selection.dimension_project",
    implementation_version="1.0.0",
    required_worker_capabilities=(WorkerCapability.READ_DATASET,),
    managed_optimization_eligibility=(ManagedOptimizationEligibility.LOCAL,),
    sample_effect="preserves_samples",
    feature_effect="preserves_features",
    axis_effect="changes_axis",
    unit_effect="preserves_units",
    resource_hints={"timeout_seconds": 30, "cpu_seconds": 30, "memory_bytes": 1_073_741_824},
    license_id="Apache-2.0",
    help_reference="docs/nodes/selection-validation.md",
    implementation_modules=(),
    implementation_distributions=("numpy",),
    runtime_requirements=(("numpy", "1.26.4"),),
    input_rank_policy=DatasetRankPolicy.PROJECTS_TO_2D,
)


__all__ = [
    "DimensionProjectionNode",
    "canonical_dimension_projection",
    "project_dataset_to_2d",
]
