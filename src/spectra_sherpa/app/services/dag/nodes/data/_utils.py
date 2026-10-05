"""Small metadata helpers shared by current data nodes."""

from __future__ import annotations

from typing import Any

import numpy as np

from spectra_sherpa.app.lib.sherpa_dataset import AxisInfo, SampleAxis


def slice_axis_for_indices(coord: Any, indices: np.ndarray) -> Any | None:
    """
    Slice sample-axis metadata for integer index selection.

    Supports canonical AxisInfo values and conservative third-party axis-like objects.
    """
    if coord is None:
        return None

    if isinstance(coord, AxisInfo):
        values = None
        if coord.values is not None:
            values = np.asarray(coord.values)[indices]

        labels = None
        if coord.labels is not None:
            labels = np.asarray(coord.labels, dtype=object)[indices].astype(str).tolist()

        # SampleAxis extends AxisInfo with per-sample fields; preserve them.
        if isinstance(coord, SampleAxis):
            classes = None
            if coord.classes is not None:
                classes = np.asarray(coord.classes)[indices]
            include_mask = None
            if coord.include_mask is not None:
                include_mask = np.asarray(coord.include_mask)[indices]
            exclusion_reasons = None
            if coord.exclusion_reasons is not None:
                exclusion_reasons = [coord.exclusion_reasons[i] for i in indices]
            sample_table = None
            if coord.sample_table is not None:
                sample_table = {k: [v[i] for i in indices] for k, v in coord.sample_table.items()}
            return SampleAxis(
                values=values,
                labels=labels,
                units=coord.units,
                title=coord.title,
                classes=classes,
                include_mask=include_mask,
                exclusion_reasons=exclusion_reasons,
                sample_table=sample_table,
            )

        return AxisInfo(
            values=values,
            labels=labels,
            units=coord.units,
            title=coord.title,
        )

    try:
        sliced = coord[indices]
        return sliced.copy() if hasattr(sliced, "copy") else sliced
    except Exception:
        return coord.copy() if hasattr(coord, "copy") else coord
