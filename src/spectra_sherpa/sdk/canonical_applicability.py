"""Bounded, data-free applicability evidence for portable applications.

Applicability checks need the fitted boundary and a small statistical reference
for interpreting a new score.  They do not need the calibration rows that were
used to estimate that reference.  This module owns the closed wire shape used
by fitted-state serializers to retain those aggregate values.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Mapping

import numpy as np

CANONICAL_APPLICABILITY_EVIDENCE_VERSION = "spectra-canonical-applicability-evidence/1"
_QUANTILES = ("0.05", "0.5", "0.95")
_MAX_DIMENSIONS = 4096
_MAX_COUNT = 1_000_000_000


class CanonicalApplicabilityEvidenceError(ValueError):
    """Applicability evidence is malformed or contains sample-level data."""


def build_applicability_evidence(
    scores: Any,
    t2: Any,
    q: Any,
    *,
    t2_limit: float,
    q_limit: float,
    method: str,
) -> dict[str, Any]:
    """Summarize calibration diagnostics without retaining any calibration row."""

    score_matrix = np.asarray(scores, dtype=np.float64)
    t2_values = np.asarray(t2, dtype=np.float64).reshape(-1)
    q_values = np.asarray(q, dtype=np.float64).reshape(-1)
    if score_matrix.ndim != 2 or score_matrix.shape[0] < 1:
        raise CanonicalApplicabilityEvidenceError("applicability scores must be a non-empty matrix")
    if score_matrix.shape[1] < 1 or score_matrix.shape[1] > _MAX_DIMENSIONS:
        raise CanonicalApplicabilityEvidenceError("applicability score dimensions are outside the supported bound")
    if t2_values.shape != (score_matrix.shape[0],) or q_values.shape != t2_values.shape:
        raise CanonicalApplicabilityEvidenceError("applicability statistics must have matching row counts")
    if not all(np.isfinite(value).all() for value in (score_matrix, t2_values, q_values)):
        raise CanonicalApplicabilityEvidenceError("applicability statistics must be finite")
    return validate_applicability_evidence(
        {
            "schema_version": CANONICAL_APPLICABILITY_EVIDENCE_VERSION,
            "limits": {"t2": float(t2_limit), "q": float(q_limit), "method": str(method)},
            "score_statistics": _vector_statistics(score_matrix),
            "t2_statistics": _scalar_statistics(t2_values),
            "q_statistics": _scalar_statistics(q_values),
        }
    )


def validate_applicability_evidence(value: Mapping[str, Any]) -> dict[str, Any]:
    """Validate and detach the aggregate-only applicability wire contract."""

    required = {"schema_version", "limits", "score_statistics", "t2_statistics", "q_statistics"}
    if not isinstance(value, Mapping) or set(value) != required:
        raise CanonicalApplicabilityEvidenceError("applicability evidence fields are closed")
    if value["schema_version"] != CANONICAL_APPLICABILITY_EVIDENCE_VERSION:
        raise CanonicalApplicabilityEvidenceError("applicability evidence schema is unsupported")
    limits = value["limits"]
    if not isinstance(limits, Mapping) or set(limits) != {"t2", "q", "method"}:
        raise CanonicalApplicabilityEvidenceError("applicability limits are closed")
    for name in ("t2", "q"):
        if isinstance(limits[name], bool) or not isinstance(limits[name], (int, float)):
            raise CanonicalApplicabilityEvidenceError(f"applicability {name} limit is invalid")
        if not np.isfinite(float(limits[name])) or float(limits[name]) <= 0.0:
            raise CanonicalApplicabilityEvidenceError(f"applicability {name} limit is invalid")
    if not isinstance(limits["method"], str) or not 1 <= len(limits["method"]) <= 128:
        raise CanonicalApplicabilityEvidenceError("applicability limit method is invalid")
    score_stats = _validate_statistics(value["score_statistics"], vector=True, name="score")
    t2_stats = _validate_statistics(value["t2_statistics"], vector=False, name="T2")
    q_stats = _validate_statistics(value["q_statistics"], vector=False, name="Q")
    if score_stats["count"] != t2_stats["count"] or score_stats["count"] != q_stats["count"]:
        raise CanonicalApplicabilityEvidenceError("applicability statistic counts disagree")
    return deepcopy(dict(value))


def _vector_statistics(values: np.ndarray) -> dict[str, Any]:
    return {
        "count": int(values.shape[0]),
        "dimensions": int(values.shape[1]),
        "mean": np.mean(values, axis=0).tolist(),
        "std": np.std(values, axis=0, ddof=1 if values.shape[0] > 1 else 0).tolist(),
        "min": np.min(values, axis=0).tolist(),
        "max": np.max(values, axis=0).tolist(),
        "quantiles": {key: np.quantile(values, float(key), axis=0).tolist() for key in _QUANTILES},
    }


def _scalar_statistics(values: np.ndarray) -> dict[str, Any]:
    vector = np.asarray(values, dtype=np.float64).reshape(-1, 1)
    stats = _vector_statistics(vector)
    return {
        "count": stats["count"],
        "mean": stats["mean"][0],
        "std": stats["std"][0],
        "min": stats["min"][0],
        "max": stats["max"][0],
        "quantiles": {key: value[0] for key, value in stats["quantiles"].items()},
    }


def _validate_statistics(value: Any, *, vector: bool, name: str) -> dict[str, Any]:
    fields = {"count", "mean", "std", "min", "max", "quantiles"}
    if vector:
        fields.add("dimensions")
    if not isinstance(value, Mapping) or set(value) != fields:
        raise CanonicalApplicabilityEvidenceError(f"applicability {name} statistics are closed")
    count = value["count"]
    if isinstance(count, bool) or not isinstance(count, int) or not 1 <= count <= _MAX_COUNT:
        raise CanonicalApplicabilityEvidenceError(f"applicability {name} count is invalid")
    dimensions = int(value["dimensions"]) if vector else 1
    if vector and (isinstance(value["dimensions"], bool) or not isinstance(value["dimensions"], int)):
        raise CanonicalApplicabilityEvidenceError(f"applicability {name} dimensions are invalid")
    if dimensions < 1 or dimensions > _MAX_DIMENSIONS:
        raise CanonicalApplicabilityEvidenceError(f"applicability {name} dimensions are invalid")
    for field in ("mean", "std", "min", "max"):
        raw = value[field]
        if vector:
            if not isinstance(raw, list) or len(raw) != dimensions:
                raise CanonicalApplicabilityEvidenceError(f"applicability {name} {field} is invalid")
            numbers = raw
        else:
            numbers = [raw]
        if any(
            isinstance(item, bool) or not isinstance(item, (int, float)) or not np.isfinite(float(item))
            for item in numbers
        ):
            raise CanonicalApplicabilityEvidenceError(f"applicability {name} {field} is invalid")
    quantiles = value["quantiles"]
    if not isinstance(quantiles, Mapping) or set(quantiles) != set(_QUANTILES):
        raise CanonicalApplicabilityEvidenceError(f"applicability {name} quantiles are closed")
    for raw in quantiles.values():
        if vector:
            if not isinstance(raw, list) or len(raw) != dimensions:
                raise CanonicalApplicabilityEvidenceError(f"applicability {name} quantile is invalid")
            numbers = raw
        else:
            numbers = [raw]
        if any(
            isinstance(item, bool) or not isinstance(item, (int, float)) or not np.isfinite(float(item))
            for item in numbers
        ):
            raise CanonicalApplicabilityEvidenceError(f"applicability {name} quantile is invalid")
    return dict(value)


__all__ = [
    "CANONICAL_APPLICABILITY_EVIDENCE_VERSION",
    "CanonicalApplicabilityEvidenceError",
    "build_applicability_evidence",
    "validate_applicability_evidence",
]
