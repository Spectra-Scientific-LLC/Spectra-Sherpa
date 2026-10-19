"""Small metadata helpers shared by current data nodes."""

from __future__ import annotations

from typing import Any

import numpy as np

from spectra_sherpa.app.lib.sherpa_dataset import AxisInfo, _slice_axis


def slice_axis_for_indices(coord: Any, indices: np.ndarray) -> Any | None:
    """
    Slice sample-axis metadata for integer index selection.

    Supports canonical AxisInfo values and conservative third-party axis-like objects.
    """
    if coord is None:
        return None

    if isinstance(coord, AxisInfo):
        return _slice_axis(coord, indices)

    try:
        sliced = coord[indices]
        return sliced.copy() if hasattr(sliced, "copy") else sliced
    except Exception:
        return coord.copy() if hasattr(coord, "copy") else coord
