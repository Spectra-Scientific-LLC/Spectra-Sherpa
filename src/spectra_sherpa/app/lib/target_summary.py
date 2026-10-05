"""Small, format-neutral summaries of an admitted dataset's target contract.

The catalog, file list, and analysis-readiness endpoints all need the same
target vocabulary. Keeping this projection beside the canonical dataset model
prevents one endpoint from silently dropping categorical or native targets.
"""

from __future__ import annotations

from typing import Any

import numpy as np


def _non_empty_mask(values: np.ndarray) -> np.ndarray:
    if np.issubdtype(values.dtype, np.number):
        return np.isfinite(values)
    return np.vectorize(
        lambda value: value is not None
        and not (isinstance(value, (float, np.floating)) and np.isnan(value))
        and str(value).strip() != "",
        otypes=[bool],
    )(values)


def target_summary(dataset: Any) -> dict[str, Any]:
    """Return bounded target names/types and row completeness for one dataset."""

    context = getattr(dataset, "target_context", None)
    if context is None:
        return {}
    target = getattr(dataset, "target", None)
    names = [str(name) for name in (getattr(context, "target_names", None) or []) if str(name).strip()]
    target_name = getattr(context, "target_name", None)
    if not names and target_name:
        names = [str(target_name)]
    target_type = getattr(context, "target_type", None)
    summary: dict[str, Any] = {
        "target_names": names or None,
        "target_types": ({name: str(target_type) for name in names} if target_type and names else None),
    }
    if target is None:
        return summary
    values = np.asarray(target)
    if values.ndim == 1:
        values = values.reshape(-1, 1)
    if values.ndim != 2:
        return summary
    non_empty = _non_empty_mask(values)
    summary.update(
        {
            "target_row_count": int(values.shape[0]),
            "target_any_rows": int(non_empty.any(axis=1).sum()),
            "target_complete_rows": int(non_empty.all(axis=1).sum()),
        }
    )
    return summary


__all__ = ["target_summary"]
