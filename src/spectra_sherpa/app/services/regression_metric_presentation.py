"""Read-time qualification of legacy mixed-response metric summaries.

Original artifacts remain immutable evidence. This projection is for display,
not a migration or a numerical recomputation.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any

_CONTAINERS = ("default", "diagnostics", "meta", "metadata", "metrics", "quality_summary")
_AGGREGATES = ("r2", "rmse", "r2_cal", "rmse_cal", "score", "mae", "bias", "sep", "latest_r2", "latest_rmse")
_SCOPE = "legacy_multiresponse_aggregate_unqualified"


def regression_metric_presentation(value: dict[str, Any]) -> dict[str, Any]:
    def multi(record: dict[str, Any], depth: int = 0) -> bool:
        if depth > 6:
            return False
        count = record.get("n_targets", record.get("target_count"))
        return (
            (type(count) is int and count > 1)
            or any(isinstance(record.get(k), list) and len(record[k]) > 1 for k in ("target_names", "per_target"))
            or record.get("metric_summary_scope") in ("per_response_only", _SCOPE)
            or any(multi(record[k], depth + 1) for k in _CONTAINERS if isinstance(record.get(k), dict))
        )

    result = deepcopy(value)
    if not multi(result):
        return result

    def qualify(record: dict[str, Any], depth: int = 0) -> None:
        if depth > 6:
            return
        suppressed = {key: record.pop(key) for key in _AGGREGATES if key in record}
        record["metric_summary_scope"] = (
            _SCOPE if suppressed or record.get("metric_summary_scope") == _SCOPE else "per_response_only"
        )
        if suppressed:
            record["legacy_aggregate_evidence"] = suppressed
            record["metric_qualification_message"] = (
                "Legacy multi-response scalar metrics withheld; inspect per-response evidence."
            )
        for key in _CONTAINERS:
            if isinstance(record.get(key), dict):
                qualify(record[key], depth + 1)

    qualify(result)
    return result
