"""Rebind attached supervision after an exact, ordered sample-row subset."""

from __future__ import annotations

import numpy as np

from spectra_sherpa.app.lib.sherpa_dataset import SherpaDataset
from spectra_sherpa.app.services.dag.supervision_binding import (
    admit_attached_sample_table_supervision,
    bind_sample_table_supervision,
)
from spectra_sherpa.core.target_authority import admit_target_authority


def rebind_sample_subset_supervision(source: SherpaDataset, result: SherpaDataset) -> None:
    """Rebind only a verified ordered subset, never inherited full-row metadata."""
    original = admit_attached_sample_table_supervision(source)
    if original is None:
        return
    source_labels = list(source.sample_axis.labels)
    result_labels = list(result.sample_axis.labels)
    positions = {label: index for index, label in enumerate(source_labels)}
    if len(positions) != len(source_labels) or any(label not in positions for label in result_labels):
        raise ValueError("Filtered supervision changed source observation identity.")
    indices = [positions[label] for label in result_labels]
    if indices != sorted(indices) or len(indices) != len(set(indices)):
        raise ValueError("Filtered supervision changed source observation order.")
    result_target = np.asarray(result.target)
    source_target = np.asarray(source.target)[indices]
    numeric_targets = result_target.dtype.kind in "fc" and source_target.dtype.kind in "fc"
    targets_match = (
        np.array_equal(result_target, source_target, equal_nan=True)
        if numeric_targets
        else np.array_equal(result_target, source_target)
    )
    if not np.array_equal(result.X, source.X[indices], equal_nan=True) or not targets_match:
        raise ValueError("Filtered supervision changed source observations or responses.")
    source_table = source.sample_axis.sample_table or {}
    result_table = result.sample_axis.sample_table or {}
    if set(source_table) != set(result_table) or any(
        [source_table[column][index] for index in indices] != list(result_table[column]) for column in source_table
    ):
        raise ValueError("Filtered supervision changed the exact sample table.")
    authority = admit_target_authority(original.record["target_authority"], optional=False)
    assert authority is not None
    result.meta.pop("supervision_binding", None)
    try:
        rebound = bind_sample_table_supervision(
            result,
            target_column=authority.column,
            target_type=authority.target_type,
            group_column=original.record["group_column"],
            target_authority=authority,
        )
    except ValueError as exc:
        if str(exc) != "categorical sample-table targets require at least two classes":
            raise
        return
    result.meta["supervision_binding"] = {**rebound.record, "supervision_binding_sha256": rebound.digest}
