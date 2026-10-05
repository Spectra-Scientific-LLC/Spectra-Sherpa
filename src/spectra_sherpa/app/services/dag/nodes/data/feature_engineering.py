"""Explicit feature selection and sample-aligned feature concatenation.

These operations do not estimate features, impute missing observations, scale
blocks, or assess predictive performance.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any

import numpy as np

from spectra_sherpa.app.lib.sherpa_dataset import FeatureAxis, SherpaDataset
from spectra_sherpa.app.services.dag.io_contracts import bind_X
from spectra_sherpa.app.services.dag.meta_helpers import add_processing_step
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

_TYPE = "spectrasherpa://types/SpectralDataset/1.0"


def column_names(dataset: SherpaDataset) -> list[str]:
    """Exact names, shared with the GUI's label-or-one-based-column rule."""
    axis = dataset.feature_axis
    labels = axis.labels if axis is not None else None
    if labels is None:
        retained = dataset.meta.get("feature_names")
        if isinstance(retained, list) and len(retained) == dataset.n_features:
            labels = retained
    names = list(map(str, labels)) if labels is not None else [f"Column {i + 1}" for i in range(dataset.n_features)]
    if len(names) != dataset.n_features or len(set(names)) != len(names) or any(not name for name in names):
        raise ValueError("Feature labels must be complete, non-empty and unique before selecting or merging columns")
    return names


def _parameters(values: dict[str, object]) -> dict[str, object]:
    columns = values.get("columns", [])
    if not isinstance(columns, list) or any(not isinstance(c, str) or not c for c in columns):
        raise ValueError("columns must be a list of exact, non-empty feature names")
    if len(set(columns)) != len(columns):
        raise ValueError("columns may not contain duplicate names")
    return values


def select_columns(
    dataset: SherpaDataset, columns: list[str], mode: str, *, node_id: str | None = None
) -> SherpaDataset:
    if dataset.ndim != 2:
        raise ValueError("Select Columns requires a two-dimensional dataset")
    _parameters({"columns": columns})
    if mode not in {"keep", "exclude"}:
        raise ValueError("Select Columns mode must be keep or exclude")
    names = column_names(dataset)
    missing = set(columns) - set(names)
    if missing:
        raise ValueError(f"Selected columns are absent from the input: {', '.join(sorted(missing))}")
    selected = set(columns)
    indices = [i for i, name in enumerate(names) if (name in selected) == (mode == "keep")]
    if not indices:
        raise ValueError("Select Columns would leave no features; select at least one column to keep")
    result = dataset[:, indices]
    # Preserve input ordering, not the order in which checkboxes were clicked.
    kept = [names[i] for i in indices]
    result.meta["column_units"] = {
        name: dataset.meta.get("column_units", {}).get(name, dataset.units or "") for name in kept
    }
    result.meta["feature_names"] = kept
    result.meta["selected_columns"] = kept
    add_processing_step(
        result,
        "selection.select_columns",
        {"columns": columns, "mode": mode},
        node_id=node_id,
        input_shape=dataset.shape,
        state_effects=["features_selected"],
    )
    return result


def _sample_keys(dataset: SherpaDataset, field: str) -> list[Any]:
    axis = dataset.sample_axis
    raw = None if axis is None else (axis.labels if field == "sample_labels" else axis.values)
    if raw is None or len(raw) != dataset.n_samples:
        raise ValueError(f"Merge Features requires complete {field} on both inputs; it never invents row identities")
    keys = list(raw)
    if any(
        value is None
        or (isinstance(value, str) and not value)
        or (isinstance(value, (float, np.floating)) and not np.isfinite(value))
        for value in keys
    ):
        raise ValueError(f"Merge Features {field} contains missing identities")
    if len(set(keys)) != len(keys):
        raise ValueError(f"Merge Features requires unique {field}; duplicate sample identities are ambiguous")
    return keys


def merge_features(
    base: SherpaDataset, additional: SherpaDataset, match_by: str, *, node_id: str | None = None
) -> SherpaDataset:
    if base.ndim != 2 or additional.ndim != 2:
        raise ValueError("Merge Features requires two-dimensional inputs")
    if not base.n_samples or not base.n_features or not additional.n_features:
        raise ValueError("Merge Features requires non-empty sample and feature axes")
    if match_by not in {"sample_labels", "sample_index"}:
        raise ValueError("Merge Features match_by must be sample_labels or sample_index")
    left = _sample_keys(base, match_by)
    right = _sample_keys(additional, match_by)
    if set(left) != set(right):
        raise ValueError("Merge Features inputs must contain exactly the same sample identities; no rows are dropped")
    lookup = {key: i for i, key in enumerate(right)}
    order = [lookup[key] for key in left]
    # Coordinate joins also check available labels, so reset row counters cannot
    # silently join two differently ordered labelled datasets.
    if match_by == "sample_index" and base.sample_axis.labels is not None and additional.sample_axis.labels is not None:
        if list(base.sample_axis.labels) != [additional.sample_axis.labels[i] for i in order]:
            raise ValueError("Sample index matches contradict sample labels; match by sample labels instead")
    for field in ("include_mask", "classes"):
        a, b = getattr(base.sample_axis, field, None), getattr(additional.sample_axis, field, None)
        if field == "include_mask":
            a = np.ones(base.n_samples, dtype=bool) if a is None else np.asarray(a)
            b = np.ones(additional.n_samples, dtype=bool) if b is None else np.asarray(b)
        if a is not None and b is not None and not np.array_equal(a, np.asarray(b)[order]):
            raise ValueError(f"Merge Features sample {field} conflicts between inputs")
    if additional.target is not None:
        numeric_targets = additional.target.dtype.kind in "biufc" and (
            base.target is not None and base.target.dtype.kind in "biufc"
        )
        if base.target is None or not np.array_equal(base.target, additional.target[order], equal_nan=numeric_targets):
            raise ValueError("Merge Features target values conflict; the base input must own the authoritative targets")
        if base.target_context != additional.target_context:
            raise ValueError("Merge Features target context conflicts between inputs")
    left_names, right_names = column_names(base), column_names(additional)
    names = [f"base::{name}" for name in left_names] + [f"added::{name}" for name in right_names]
    extra = deepcopy(base.extra)
    extra["feature_names"] = names
    extra["column_units"] = {
        f"{prefix}::{name}": dataset.meta.get("column_units", {}).get(name, dataset.units or "")
        for prefix, dataset, source_names in (("base", base, left_names), ("added", additional, right_names))
        for name in source_names
    }
    extra["feature_merge"] = {
        "match_by": match_by,
        "additional_row_order": order,
        "base_digest": base.scientific_digest,
        "additional_digest": additional.scientific_digest,
        "blocks": [
            {
                "name": prefix,
                "start": start,
                "stop": start + dataset.n_features,
                "feature_axis": (
                    dataset.feature_axis.model_dump(mode="json") if dataset.feature_axis is not None else None
                ),
                "units": dataset.units,
                "provenance": dataset.provenance.to_list(),
                "feature_context": {
                    key: deepcopy(dataset.meta[key])
                    for key in ("peak_groups", "measurement_policy", "selected_columns")
                    if key in dataset.meta
                },
            }
            for prefix, dataset, start in (("base", base, 0), ("added", additional, base.n_features))
        ],
        "missing_values": "preserved; no imputation or scaling",
    }
    # A heterogeneous feature matrix has no single wavelength axis or response unit.
    result = SherpaDataset(
        X=np.concatenate((base.X, additional.X[order]), axis=1),
        feature_axis=FeatureAxis(
            labels=names,
            title="Engineered features",
            include_mask=np.concatenate(
                [
                    (
                        dataset.feature_axis.include_mask
                        if dataset.feature_axis is not None and dataset.feature_axis.include_mask is not None
                        else np.ones(dataset.n_features, dtype=bool)
                    )
                    for dataset in (base, additional)
                ]
            ),
        ),
        sample_axis=base.sample_axis.copy(),
        target=base.target.copy() if base.target is not None else None,
        target_context=base.target_context.model_copy(deep=True),
        domain=base.domain.model_copy(deep=True),
        descriptive=base.descriptive.model_copy(deep=True),
        source_identity=base.source_identity.model_copy(deep=True),
        source_history=base.source_history.model_copy(deep=True),
        provenance=base.provenance.copy(),
        backend=base.backend,
        title="Merged features",
        units=None,
        extra=extra,
        is_time_series=base.is_time_series,
        data_role="X_features",
    )
    add_processing_step(
        result,
        "data.merge_features",
        {
            "match_by": match_by,
            "base_digest": base.scientific_digest,
            "additional_digest": additional.scientific_digest,
        },
        node_id=node_id,
        input_shape=base.shape,
        state_effects=["features_concatenated"],
    )
    return result


@register_node
class SelectColumnsNode(Node):
    metadata = NodeMetadata(
        node_type="selection.select_columns",
        category="selection",
        label="Select Columns",
        description="Keep or exclude named feature columns without changing samples or filling missing values",
        policy=NodePolicy(),
        input_types=["SherpaDataset"],
        output_type="SherpaDataset",
        input_ports=[PortMetadata(name="default", type_ref=_TYPE, required=True, label="Input Dataset")],
        output_ports=[PortMetadata(name="default", type_ref=_TYPE, required=True, label="Selected Features")],
        parameters=[
            NodeParameter(
                name="mode", label="Selection Mode", param_type="select", default="keep", options=["keep", "exclude"]
            ),
            NodeParameter(
                name="columns",
                label="Columns",
                param_type="string_list",
                default=[],
                description="Exact column names; run the upstream node to populate the selector",
            ),
        ],
        canonical_parameter_validator=_parameters,
    )

    async def execute(self, input_data: Any) -> dict[str, SherpaDataset]:
        dataset = bind_X(input_data, allow_array=False)
        return {
            "default": select_columns(
                dataset, self.parameters.get("columns", []), self.parameters.get("mode", "keep"), node_id=self.node_id
            )
        }


@register_node
class MergeFeaturesNode(Node):
    metadata = NodeMetadata(
        node_type="data.merge_features",
        category="data",
        label="Merge Features",
        description="Append feature columns by unique sample identity; preserve base row order and targets",
        policy=NodePolicy(),
        input_types=["SherpaDataset", "SherpaDataset"],
        output_type="SherpaDataset",
        input_ports=[
            PortMetadata(
                name="base",
                type_ref=_TYPE,
                required=True,
                label="Base Dataset",
                description="Authoritative sample order, metadata, and targets",
            ),
            PortMetadata(
                name="additional",
                type_ref=_TYPE,
                required=True,
                label="Additional Features",
                description="Feature columns with exactly the same sample identities",
            ),
        ],
        output_ports=[PortMetadata(name="default", type_ref=_TYPE, required=True, label="Merged Features")],
        parameters=[
            NodeParameter(
                name="match_by",
                label="Match Samples By",
                param_type="select",
                default="sample_labels",
                options=["sample_labels", "sample_index"],
                description="Unique sample labels or retained sample-axis coordinates, not row count",
            )
        ],
    )

    async def execute(self, base: Any, additional: Any) -> dict[str, SherpaDataset]:
        return {
            "default": merge_features(
                bind_X(base, allow_array=False),
                bind_X(additional, allow_array=False),
                self.parameters.get("match_by", "sample_labels"),
                node_id=self.node_id,
            )
        }


for _node, _feature_effect in ((SelectColumnsNode, "filters_features"), (MergeFeaturesNode, "generates_features")):
    bind_stable_execution_contract(
        _node,
        runtime_family=RuntimeFamily.SHERPA_NATIVE,
        lifecycle_kind=LifecycleKind.STATELESS_TRANSFORM,
        implementation_id=f"spectrasherpa.{_node.metadata.node_type}",
        implementation_version="1.0.0",
        required_worker_capabilities=(WorkerCapability.READ_DATASET,),
        managed_optimization_eligibility=(ManagedOptimizationEligibility.LOCAL,),
        sample_effect="preserves_samples",
        feature_effect=_feature_effect,
        axis_effect="changes_axis",
        unit_effect="preserves_units",
        resource_hints={"timeout_seconds": 30, "cpu_seconds": 30, "memory_bytes": 1073741824},
        license_id="Apache-2.0",
        help_reference="docs/nodes/selection-validation.md",
        implementation_modules=(),
        implementation_distributions=("numpy",),
        runtime_requirements=(("numpy", "1.26.4"),),
        input_rank_policy=DatasetRankPolicy.REQUIRES_2D,
    )
