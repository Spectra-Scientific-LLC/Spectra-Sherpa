"""Provisional SIMPLS global screening; never analytical qualification.

Only aggregate calibration state is retained. Neighborhood support is therefore
unavailable, even when both global screening statistics are within their limits.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import numpy as np

SCHEMA = "spectrasherpa.pls-global-screening/1"
METHOD = "calibration_quantile_linear_0.95_strict_greater"


def fit_screening(X: np.ndarray, model: Any) -> dict[str, Any]:
    z = (X - model.x_offset) / model.x_scale
    scores = z @ model.x_weights
    center = scores.mean(axis=0)
    centered = scores - center
    n, p = X.shape
    k = scores.shape[1]
    covariance = centered.T @ centered / (n - 1)
    eigenvalues = np.linalg.eigvalsh(covariance)
    rank_tolerance = float(np.finfo(float).eps * k * max(float(eigenvalues[-1]), 0.0))
    rank = int(np.count_nonzero(eigenvalues > rank_tolerance))
    reason = (
        "insufficient_reference_degrees_of_freedom"
        if n <= k + 1
        else "rank_deficient_score_covariance" if rank < k else None
    )
    inverse = np.linalg.inv(covariance) if reason is None else None
    t2 = np.einsum("ij,jk,ik->i", centered, inverse, centered) if inverse is not None else None
    residual = z - scores @ model.x_loadings.T
    q = np.sum(residual * residual, axis=1)
    # Fixed at fit time. A large application row must never enlarge its own limit.
    numerical_q_tolerance = float(64 * np.finfo(float).eps ** 2 * max(n, p, k) ** 2 * np.max(np.sum(z * z, axis=1)))
    q_reason = "no_residual_feature_dimensions" if k >= p else reason
    q_quantile = float(np.quantile(q, 0.95, method="linear"))
    state = {
        "schema_version": SCHEMA,
        "method": METHOD,
        "reference_samples": n,
        "features": p,
        "components": k,
        "score_covariance_rank": rank,
        "rank_tolerance": rank_tolerance,
        "x_scale": model.x_scale.tolist(),
        "projection": model.x_weights.tolist(),
        "reconstruction": model.x_loadings.tolist(),
        "score_center": center.tolist(),
        "score_covariance_inverse": None if inverse is None else inverse.tolist(),
        "t2_limit": None if t2 is None else float(np.quantile(t2, 0.95, method="linear")),
        "t2_unavailable_reason": reason,
        "q_calibration_quantile": q_quantile,
        "q_numerical_tolerance": numerical_q_tolerance,
        "q_limit": None if q_reason else max(q_quantile, numerical_q_tolerance),
        "q_unavailable_reason": q_reason,
        "neighborhood_support": "unavailable_aggregate_state",
    }
    return validate_screening(state, features=p, components=k, samples=n)


def validate_screening(value: Any, *, features: int, components: int, samples: int) -> dict[str, Any]:
    fields = {
        "schema_version",
        "method",
        "reference_samples",
        "features",
        "components",
        "score_covariance_rank",
        "rank_tolerance",
        "x_scale",
        "projection",
        "reconstruction",
        "score_center",
        "score_covariance_inverse",
        "t2_limit",
        "t2_unavailable_reason",
        "q_calibration_quantile",
        "q_numerical_tolerance",
        "q_limit",
        "q_unavailable_reason",
        "neighborhood_support",
    }
    if not isinstance(value, Mapping) or set(value) != fields:
        raise ValueError("PLS screening state fields are closed")
    if (
        value["schema_version"] != SCHEMA
        or value["method"] != METHOD
        or value["neighborhood_support"] != "unavailable_aggregate_state"
    ):
        raise ValueError("PLS screening method is unsupported")
    for name, expected in (("features", features), ("components", components), ("reference_samples", samples)):
        if type(value[name]) is not int or value[name] != expected:
            raise ValueError("PLS screening dimensions contradict model state")
    rank = value["score_covariance_rank"]
    if type(rank) is not int or not 0 <= rank <= components:
        raise ValueError("PLS screening covariance rank is invalid")
    out = dict(value)
    for name, shape in (
        ("x_scale", (features,)),
        ("projection", (features, components)),
        ("reconstruction", (features, components)),
        ("score_center", (components,)),
    ):
        array = np.asarray(value[name], dtype=float)
        if array.shape != shape or not np.isfinite(array).all():
            raise ValueError(f"PLS screening {name} is invalid")
        if name == "x_scale" and np.any(array <= 0):
            raise ValueError("PLS screening scale must be positive")
        out[name] = array.tolist()
    for name in ("rank_tolerance", "q_calibration_quantile", "q_numerical_tolerance", "t2_limit", "q_limit"):
        v = value[name]
        if v is None and name in ("t2_limit", "q_limit"):
            continue
        if isinstance(v, bool) or not isinstance(v, (int, float)) or not np.isfinite(v) or v < 0:
            raise ValueError(f"PLS screening {name} is invalid")
    reason = (
        "insufficient_reference_degrees_of_freedom"
        if samples <= components + 1
        else "rank_deficient_score_covariance" if rank < components else None
    )
    if value["t2_unavailable_reason"] != reason or (value["t2_limit"] is None) != (reason is not None):
        raise ValueError("PLS screening T2 availability contradicts reference rank")
    inverse = value["score_covariance_inverse"]
    if reason is None:
        matrix = np.asarray(inverse, dtype=float)
        if (
            matrix.shape != (components, components)
            or not np.isfinite(matrix).all()
            or not np.allclose(matrix, matrix.T)
            or np.min(np.linalg.eigvalsh(matrix)) <= 0
        ):
            raise ValueError("PLS screening covariance inverse is invalid")
        out["score_covariance_inverse"] = matrix.tolist()
    elif inverse is not None:
        raise ValueError("Unavailable PLS screening retains a covariance inverse")
    q_reason = "no_residual_feature_dimensions" if components >= features else reason
    expected_limit = None if q_reason else max(value["q_calibration_quantile"], value["q_numerical_tolerance"])
    if value["q_unavailable_reason"] != q_reason or value["q_limit"] != expected_limit:
        raise ValueError("PLS screening Q authority contradicts retained method")
    return out


def apply_screening(X: np.ndarray, offset: Any, state: Mapping[str, Any]) -> dict[str, Any]:
    z = (X - np.asarray(offset).reshape(-1)) / np.asarray(state["x_scale"])
    scores = z @ np.asarray(state["projection"])
    residual = z - scores @ np.asarray(state["reconstruction"]).T
    q = np.sum(residual * residual, axis=1)
    center = scores - np.asarray(state["score_center"])
    inverse = state["score_covariance_inverse"]
    t2 = None if inverse is None else np.einsum("ij,jk,ik->i", center, inverse, center)
    if not np.isfinite(q).all() or (t2 is not None and not np.isfinite(t2).all()):
        raise ValueError("PLS screening exceeds finite numerical range")
    rows = []
    for index in range(X.shape[0]):
        outside_t2 = None if t2 is None else bool(t2[index] > state["t2_limit"])
        outside_q = None if state["q_limit"] is None else bool(q[index] > state["q_limit"])
        status = (
            "outside_global_screen"
            if outside_t2 or outside_q
            else "unavailable" if outside_t2 is None or outside_q is None else "within_global_screen"
        )
        rows.append(
            {
                "row_index": index,
                "t2": None if t2 is None else float(t2[index]),
                "q": float(q[index]),
                "outside_t2": outside_t2,
                "outside_q": outside_q,
                "screening_status": status,
                "applicability_status": "unqualified",
            }
        )
    return {
        "schema_version": SCHEMA,
        "method": METHOD,
        "claim_scope": "provisional_calibration_screening",
        "reference_samples": state["reference_samples"],
        "components": state["components"],
        "score_covariance_rank": state["score_covariance_rank"],
        "t2_limit": state["t2_limit"],
        "q_limit": state["q_limit"],
        "q_calibration_quantile": state["q_calibration_quantile"],
        "q_numerical_tolerance": state["q_numerical_tolerance"],
        "t2_unavailable_reason": state["t2_unavailable_reason"],
        "q_unavailable_reason": state["q_unavailable_reason"],
        "neighborhood_support": state["neighborhood_support"],
        "rows": rows,
    }
