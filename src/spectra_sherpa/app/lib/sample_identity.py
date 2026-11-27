"""Observation identity on the typed sample table, separate from display labels.

Reuse the existing ``sample_id`` column. Do not derive specimen independence
from it, mint new IDs on read, or treat matching array lengths as identity.
"""

from __future__ import annotations

from typing import Any


def sample_ids(dataset: Any) -> list[str] | None:
    """Read exact, unique row IDs, refusing a malformed declared column."""
    axis = getattr(dataset, "sample_axis", None)
    table = getattr(axis, "sample_table", None)
    if not isinstance(table, dict) or "sample_id" not in table:
        return None
    values = table["sample_id"]
    count = getattr(dataset, "n_samples", None)
    if (
        not isinstance(values, (list, tuple))
        or len(values) != count
        or any(not isinstance(value, str) or not value or value != value.strip() for value in values)
        or len(set(values)) != len(values)
    ):
        raise ValueError("Declared sample_id values must be exact, unique, and aligned with the sample rows")
    return list(values)


def require_matching_sample_identity(left: Any, right: Any) -> bool:
    """Check explicit IDs when both exist; legacy labels are only a fallback.

    Return whether explicit observation identity was checked. Legacy label equality
    is useful for refusing a mismatch but is not a verified identity claim.
    """
    left_ids, right_ids = sample_ids(left), sample_ids(right)
    if left_ids is not None and right_ids is not None:
        if left_ids != right_ids:
            raise ValueError("Target sample IDs do not exactly match dataset sample IDs and order")
        return True
    left_labels = getattr(getattr(left, "sample_axis", None), "labels", None)
    right_labels = getattr(getattr(right, "sample_axis", None), "labels", None)
    if left_labels is not None and right_labels is not None and list(left_labels) != list(right_labels):
        raise ValueError("Target sample labels do not exactly match dataset sample labels and order")
    return False
