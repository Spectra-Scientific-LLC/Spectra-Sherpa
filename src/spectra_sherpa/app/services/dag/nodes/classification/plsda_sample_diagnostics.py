"""Bounded, fitted-state-bound calibration diagnostics for PLS-DA samples.

These terms explain predictor-space T² and Q; they are not class-response
coefficients, probabilities, or evidence that a measurement should be excluded.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

import numpy as np

from spectra_sherpa.app.lib.pls_diagnostic_terms import row_terms as _row_terms
from spectra_sherpa.app.services.dag.nodes.modeling import pls_applicability

SCHEMA = "spectrasherpa-plsda-sample-diagnostics/1"
MAX_OBSERVATIONS = 5000
MAX_FEATURES = 20000
MAX_WORK = 100_000_000
MAX_BYTES = 6 * 1024 * 1024


def build_sample_diagnostics(core: dict[str, Any]) -> dict[str, Any]:
    """Use the classifier's existing screening state and exact calibration X."""

    artifact = core["artifact"].validated()
    dataset = core["dataset"]
    matrix = np.asarray(core["matrix"], dtype=np.float64)
    n, p = matrix.shape
    k = artifact.effective_n_components
    if n > MAX_OBSERVATIONS or p > MAX_FEATURES or n * p * k > MAX_WORK:
        raise ValueError("PLS-DA sample diagnostics exceed the bounded calculation budget")
    sample_axis = dataset.sample_axis
    if sample_axis is None or sample_axis.labels is None:
        raise ValueError("PLS-DA calibration observation IDs are unavailable")
    identities = list(sample_axis.labels)
    if len(identities) != n or any(not isinstance(x, str) or not x for x in identities):
        raise ValueError("PLS-DA calibration observation IDs are unavailable")
    if len(set(identities)) != n:
        raise ValueError("PLS-DA calibration observation IDs are duplicated")
    if artifact.screening is None:
        raise ValueError("PLS-DA fitted state has no calibration screening reference")
    screening = pls_applicability.validate_screening(artifact.screening, features=p, components=k, samples=n)
    offset = np.asarray(artifact.x_offset)
    scale = np.asarray(screening["x_scale"])
    projection = np.asarray(screening["projection"])
    saved_scores = np.asarray(core["x_scores"])
    if saved_scores.shape != (n, k):
        raise ValueError("PLS-DA diagnostic scores differ from the exact fitted output")
    feature_sum = np.zeros(p, dtype=np.float64)
    # Two bounded passes avoid duplicating a potentially very large fitted X.
    for start in range(0, n, 64):
        z = (matrix[start : start + 64] - offset) / scale
        scores = z @ projection
        if not np.allclose(scores, saved_scores[start : start + 64], rtol=1e-10, atol=1e-12):
            raise ValueError("PLS-DA diagnostic scores differ from the exact fitted output")
        feature_sum += z.sum(axis=0)
    center = feature_sum / n
    if not np.allclose(center @ np.asarray(screening["projection"]), screening["score_center"], rtol=1e-10, atol=1e-12):
        raise ValueError("PLS-DA diagnostic reference frame differs from fitted screening")
    count = min(10, max(1, 60000 // (2 * n)))
    rows = []
    for start in range(0, n, 64):
        block = matrix[start : start + 64]
        applied = pls_applicability.apply_screening(block, offset, screening)
        z = (block - offset) / scale
        scores = z @ projection
        for j, identity in enumerate(identities[start : start + 64]):
            canonical = applied["rows"][j]
            terms = _row_terms(z[j], scores[j], screening, center, canonical, count)
            rows.append(
                {
                    "id": identity,
                    "class": str(core["labels"][start + j]),
                    "role": "calibration",
                    "scores": scores[j].tolist(),
                    "t2": canonical["t2"],
                    "q": canonical["q"],
                    "outside_t2": canonical["outside_t2"],
                    "outside_q": canonical["outside_q"],
                    "terms": terms,
                }
            )
    axis = dataset.feature_axis
    state = artifact.to_fitted_state()
    result = {
        "schema_version": SCHEMA,
        "model_kind": "plsda",
        "source_execution_digest": dataset.scientific_digest,
        "fitted_state_sha256": hashlib.sha256(
            json.dumps(state, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
        ).hexdigest(),
        "reference_population": "fitted calibration observations",
        "reference_count": n,
        "components": k,
        "classes": list(artifact.classes),
        "feature_count": p,
        "feature_values": None if axis is None or axis.values is None else np.asarray(axis.values).tolist(),
        "feature_labels": None if axis is None or axis.labels is None else list(axis.labels),
        "feature_units": None if axis is None else axis.units,
        "space": (
            "internally centered and scaled predictor space"
            if artifact.scale
            else "internally centered predictor space"
        ),
        "q_units": "squared standardized predictor units" if artifact.scale else "squared input signal units",
        "t2_units": "dimensionless",
        "t2_limit": screening["t2_limit"],
        "q_limit": screening["q_limit"],
        "screening_method": screening["method"],
        "q_limit_method": screening.get("q_limit_method", "empirical_calibration_quantile"),
        "score_covariance_rank": screening["score_covariance_rank"],
        "rank_tolerance": screening["rank_tolerance"],
        "t2_unavailable_reason": screening["t2_unavailable_reason"],
        "q_unavailable_reason": screening["q_unavailable_reason"],
        "top_per_statistic": count,
        "contribution_formula": (
            "Q_j=E_j²; signed T²_j=(Z_j-reference_mean_Z_j)" "[(T-center) covariance_inverse projection.T]_j"
        ),
        "interpretation": (
            "Variable loadings describe latent components. These per-sample terms explain the fitted predictor-space "
            "screening statistic; screening is not proof of a bad measurement or classification validity."
        ),
        "rows": rows,
    }
    if len(json.dumps(result, allow_nan=False).encode()) > MAX_BYTES:
        raise ValueError("PLS-DA sample diagnostics exceed the retained evidence budget")
    return result
