"""Explicit, provenance-bound projections used by n-D-aware DAG nodes."""

from __future__ import annotations

import copy
import hashlib
import itertools
import json
from dataclasses import dataclass
from typing import Any

import numpy as np

from spectra_sherpa.app.lib.axes import AxisInfo, FeatureAxis
from spectra_sherpa.app.lib.sherpa_dataset import DatasetLayoutContext, SherpaDataset
from spectra_sherpa.core.dimension_roles import DimensionRole

MODE_1_UNFOLDING = "mode_1_samples_by_composite_features_c_order"
_MAX_COMPOSITE_LABELS = 1_000_000


@dataclass(frozen=True, slots=True)
class RankProjection:
    """One exact rank transformation applied before a scientific kernel."""

    strategy: str
    input_shape: tuple[int, ...]
    output_shape: tuple[int, int]
    input_axis_identity_sha256: str


def _canonical_json(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False).encode()


def input_axis_identity(dataset: SherpaDataset) -> str:
    """Digest shape, roles, and every coordinate axis without hashing measurements."""

    projection: dict[str, Any] = {
        "rank": dataset.ndim,
        "non_sample_shape": list(dataset.shape[1:]),
        "mode_roles": [str(role) for role in dataset.layout.mode_roles],
        "feature_axis": (
            None if dataset.feature_axis is None else dataset.feature_axis.model_dump(mode="json", exclude_none=True)
        ),
        "inner_axes": {
            str(index): axis.model_dump(mode="json", exclude_none=True)
            for index, axis in sorted(dataset.inner_axes.items())
        },
    }
    return hashlib.sha256(_canonical_json(projection)).hexdigest()


def _axis_token(axis: AxisInfo | None, index: int) -> str:
    if axis is None:
        return str(index)
    if axis.labels is not None:
        return str(axis.labels[index])
    if axis.values is not None:
        return str(axis.values[index])
    return str(index)


def _composite_feature_axis(dataset: SherpaDataset) -> FeatureAxis:
    shape = tuple(int(value) for value in dataset.shape[1:])
    count = int(np.prod(shape, dtype=np.int64))
    source_axes: list[AxisInfo | None] = [dataset.inner_axes.get(index) for index in range(1, dataset.ndim - 1)]
    source_axes.append(dataset.feature_axis)

    labels: list[str] | None = None
    if count <= _MAX_COMPOSITE_LABELS:
        labels = []
        role_values = list(dataset.layout.mode_roles[1:]) if dataset.layout.mode_roles else []
        for coordinate in itertools.product(*(range(length) for length in shape)):
            pieces = []
            for offset, index in enumerate(coordinate):
                role = str(role_values[offset]) if offset < len(role_values) else f"dimension_{offset + 1}"
                pieces.append(f"{role}={_axis_token(source_axes[offset], index)}")
            labels.append(" | ".join(pieces))

    include = np.ones(shape, dtype=bool)
    has_mask = False
    for offset, axis in enumerate(source_axes):
        if axis is None or axis.include_mask is None:
            continue
        has_mask = True
        broadcast = [1] * len(shape)
        broadcast[offset] = shape[offset]
        include &= np.asarray(axis.include_mask, dtype=bool).reshape(broadcast)

    return FeatureAxis(
        labels=labels,
        include_mask=include.reshape(-1, order="C") if has_mask else None,
        title="Mode-1 unfolded composite variables",
    )


def project_mode_1_to_2d(
    dataset: SherpaDataset, *, operation_id: str, node_id: str | None = None
) -> tuple[SherpaDataset, RankProjection]:
    """Keep samples on mode 1 and unfold every remaining mode into features."""

    if dataset.ndim < 2:
        raise ValueError("mode-1 unfolding requires a dataset with at least two dimensions")
    identity = input_axis_identity(dataset)
    if dataset.ndim == 2:
        return dataset, RankProjection("none", tuple(dataset.shape), tuple(dataset.shape), identity)

    output_shape = (dataset.n_samples, int(np.prod(dataset.shape[1:], dtype=np.int64)))
    matrix = np.asarray(dataset.X, dtype=np.float64).reshape(output_shape, order="C")
    provenance = dataset.provenance.copy()
    projection = {
        "strategy": MODE_1_UNFOLDING,
        "order": "C",
        "input_shape": list(dataset.shape),
        "input_mode_roles": [str(role) for role in dataset.layout.mode_roles],
        "input_axis_identity_sha256": identity,
    }
    provenance.append(
        operation_id,
        projection,
        op_version="1.0",
        node_id=node_id,
        input_shape=tuple(dataset.shape),
        output_shape=output_shape,
        state_effects=["mode_1_unfolded"],
    )
    extra = copy.deepcopy(dataset.extra)
    extra["sherpa.rank_projection"] = projection
    layout = DatasetLayoutContext(
        kind="generic",
        source_type="mode-1-unfolding",
        source_dtype=matrix.dtype.str,
        source_shape=output_shape,
        mode_roles=(DimensionRole.SAMPLE, DimensionRole.FEATURE),
        original_unfolded_shape=tuple(dataset.shape),
    )
    projected = SherpaDataset(
        X=matrix,
        feature_axis=_composite_feature_axis(dataset),
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
    return projected, RankProjection(MODE_1_UNFOLDING, tuple(dataset.shape), output_shape, identity)


__all__ = [
    "MODE_1_UNFOLDING",
    "RankProjection",
    "input_axis_identity",
    "project_mode_1_to_2d",
]
