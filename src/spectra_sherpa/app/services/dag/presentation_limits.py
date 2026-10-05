"""Explicit limits for scientific views that materialize complete JSON payloads."""

from collections.abc import Mapping

import numpy as np

from spectra_sherpa.app.lib.sherpa_dataset import SherpaDataset

MAX_PRESENTATION_VALUES = 100_000
MAX_PRESENTATION_TEXT_BYTES = 2 * 1024 * 1024


def require_bounded_presentation(
    value,
    *,
    surface: str,
    multiplier: int = 1,
    max_values: int = MAX_PRESENTATION_VALUES,
    max_text_bytes: int = MAX_PRESENTATION_TEXT_BYTES,
) -> None:
    """Refuse excessive materialization before list/string/JSON expansion.

    Counts include labels and mappings. No observations are silently removed;
    callers must select a smaller explicit cohort or feature range.
    """
    count = 0
    text_bytes = 0
    stack = [value]
    while stack:
        item = stack.pop()
        count += 1
        if isinstance(item, SherpaDataset):
            stack.append(item.data)
            for axis in (item.sample_axis, item.feature_axis):
                if axis is not None:
                    stack.extend([getattr(axis, "values", None), getattr(axis, "labels", None)])
        elif isinstance(item, np.ndarray):
            count += item.size
            if item.dtype.kind in "OUS":
                # Refuse large arrays before inspecting individual strings.
                if count * multiplier <= max_values:
                    stack.extend(item.flat)
        elif isinstance(item, Mapping):
            count += len(item)
            if count * multiplier <= max_values:
                stack.extend(item.keys())
                stack.extend(item.values())
        elif isinstance(item, (list, tuple)):
            count += len(item)
            if count * multiplier <= max_values:
                stack.extend(item)
        elif isinstance(item, str):
            text_bytes += len(item.encode("utf-8"))
        if count * multiplier > max_values or text_bytes * multiplier > max_text_bytes:
            raise ValueError(
                f"{surface} exceeds its display limit ({max_values:,} values or "
                f"{max_text_bytes:,} text bytes). Select a smaller explicit cohort or feature range."
            )
