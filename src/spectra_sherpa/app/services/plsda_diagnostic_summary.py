"""Compatibility entry point; diagnostic_review_summary owns all review dispatch."""

from __future__ import annotations

from typing import Any

from .diagnostic_review_summary import build_summary


def build_plsda_summary(receipt: dict[str, Any], *, selected_ids: list[str], variable_ids: list[str]) -> dict[str, Any]:
    """Keep the historical packet shape for existing integrations."""
    result = build_summary({**receipt, "model_kind": "plsda"}, selected_ids=selected_ids, variable_ids=variable_ids)
    result["schema_version"] = "diagnostic-review-plsda/1"
    for key in ("availability", "selection_count", "populations", "response"):
        result.pop(key, None)
    return result
