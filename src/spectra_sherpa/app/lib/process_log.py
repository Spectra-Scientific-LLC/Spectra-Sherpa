"""Explicit scientific operations for time-resolved wafer process logs."""

from __future__ import annotations

import copy

import numpy as np

from spectra_sherpa.app.lib.sherpa_dataset import DatasetLayoutContext, Provenance, SherpaDataset
from spectra_sherpa.core.dimension_roles import DimensionRole

WAFER_TIME_AVERAGE_SCHEMA = "spectrasherpa-wafer-time-average/1"


def wafer_time_average(dataset: SherpaDataset, *, node_id: str | None = None) -> SherpaDataset:
    """Reduce a governed wafer/time/feature cube to one row per wafer.

    The native reader pads unequal source time-series lengths with NaN and
    records each exact source length in ``sample_table.time_point_count``.
    Only the governed prefix participates in the mean; padding can therefore
    never change a result or be confused with an observed source value.
    """

    roles = tuple(dataset.layout.mode_roles)
    if dataset.ndim != 3 or roles[:2] != (DimensionRole.SAMPLE, DimensionRole.TIME_POINT):
        raise ValueError("wafer time average requires a sample × time-point × feature dataset")
    if roles[2] not in {DimensionRole.FEATURE, DimensionRole.SPECTRAL_FEATURE}:
        raise ValueError("wafer time average requires a feature or spectral-feature final dimension")
    if dataset.sample_axis is None or dataset.sample_axis.sample_table is None:
        raise ValueError("wafer time average requires exact source time-point counts")
    raw_counts = dataset.sample_axis.sample_table.get("time_point_count")
    if raw_counts is None or len(raw_counts) != dataset.shape[0]:
        raise ValueError("wafer time average time-point counts do not match the sample dimension")

    counts: list[int] = []
    values = np.asarray(dataset.X, dtype=np.float64)
    rows: list[np.ndarray] = []
    for index, raw_count in enumerate(raw_counts):
        if type(raw_count) is not int or raw_count <= 0 or raw_count > dataset.shape[1]:
            raise ValueError("wafer time average requires bounded exact time-point counts")
        count = int(raw_count)
        if count < dataset.shape[1] and not np.isnan(values[index, count:, :]).all():
            raise ValueError("wafer time average found observed values outside the governed time-point count")
        counts.append(count)
        # MATLAB stores each wafer matrix column-major. Reconstruct that
        # declared storage order before reduction so the canonical operation
        # reproduces the qualified source projection bit-for-bit instead of
        # changing floating summation order after C-contiguous cube assembly.
        rows.append(np.mean(np.asfortranarray(values[index, :count, :]), axis=0))
    averaged = np.asarray(rows, dtype=np.float64)

    provenance_entries = dataset.provenance.to_list()
    provenance_entries.append(
        {
            "op_id": "preprocess.wafer_time_average",
            "op_version": "1.0",
            "parameters": {
                "schema_version": WAFER_TIME_AVERAGE_SCHEMA,
                "reduction_order": "source-column-major",
                "time_dimension": 1,
                "time_point_counts": counts,
            },
            "timestamp": "",
            **({"node_id": node_id} if node_id is not None else {}),
            "input_shape": list(dataset.shape),
            "output_shape": list(averaged.shape),
            "state_effects": ["time_dimension_averaged"],
        }
    )
    provenance = Provenance.from_list(provenance_entries)
    original_layout = dataset.layout
    layout = DatasetLayoutContext(
        kind="generic",
        source_type="wafer-time-average",
        source_dtype=averaged.dtype.str,
        source_shape=tuple(averaged.shape),
        mode_roles=(roles[0], roles[-1]),
        original_unfolded_shape=original_layout.original_unfolded_shape or tuple(dataset.shape),
    )
    extra = copy.deepcopy(dataset.extra)
    extra["sherpa.wafer_time_average"] = {
        "schema_version": WAFER_TIME_AVERAGE_SCHEMA,
        "reduction_order": "source-column-major",
        "time_dimension": 1,
        "time_point_counts": counts,
        "input_scientific_digest": dataset.scientific_digest,
        "input_layout": original_layout.model_dump(mode="json", exclude_none=True),
    }
    return SherpaDataset(
        X=averaged,
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
        is_time_series=False,
        data_role=dataset.data_role,
    )


__all__ = ["WAFER_TIME_AVERAGE_SCHEMA", "wafer_time_average"]
