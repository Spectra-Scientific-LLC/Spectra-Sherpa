"""Exact retained SIMPLS predictor-space review evidence; never a refit or qualification."""

from __future__ import annotations

import hashlib
import json

import numpy as np

from spectra_sherpa.app.lib.pca_numerics import hotelling_t2_limit
from spectra_sherpa.app.lib.pls_diagnostic_terms import row_terms as _row_terms
from spectra_sherpa.app.services.dag.fitted_input_identity import require_fitted_input_identity
from spectra_sherpa.app.services.dag.nodes.modeling import pls_applicability

SCHEMA = "spectrasherpa-pls-applicability-review/1"
MAX_WORK = 100_000_000
MAX_TERMS = 60000
MAX_BYTES = 6 * 1024 * 1024


def _digest(value):
    return hashlib.sha256(json.dumps(value, separators=(",", ":"), ensure_ascii=True).encode()).hexdigest()


def _reference(state, dataset, rows, saved_scores, saved_loadings):
    diagnostic = pls_applicability.validate_screening(
        state["diagnostic_state"],
        features=state["features"],
        components=state["effective_n_components"],
        samples=state["reference_samples"],
    )
    if diagnostic["schema_version"] != pls_applicability.SCHEMA:
        raise ValueError("Legacy empirical PLS screening requires a new saved run for applicability review.")
    ids = [row["id"] for row in rows if row["role"] == "calibration"]
    if len(ids) != state["reference_samples"] or list(dataset.sample_axis.labels) != ids:
        raise ValueError("PLS applicability calibration identity/order differs from the fitted reference.")
    require_fitted_input_identity(dataset, state["input_identity"], features=state["features"])
    projection = np.asarray(diagnostic["projection"])
    score_blocks, feature_sum = [], np.zeros(state["features"])
    for start in range(0, len(ids), 64):
        z = (
            np.asarray(dataset.X[start : start + 64], dtype=float) - np.asarray(state["feature_offset"]).reshape(-1)
        ) / diagnostic["x_scale"]
        score_blocks.append(z @ projection)
        feature_sum += z.sum(axis=0)
    scores = np.concatenate(score_blocks)
    feature_center = feature_sum / len(ids)
    saved_scores = np.asarray(saved_scores, dtype=float)
    if saved_scores.shape != scores.shape or not np.allclose(saved_scores, scores, rtol=1e-10, atol=1e-12):
        raise ValueError("PLS applicability scores differ from the retained fitted output.")
    if not np.array_equal(np.asarray(diagnostic["reconstruction"]).T, np.asarray(saved_loadings)):
        raise ValueError("PLS applicability reconstruction differs from retained X loadings.")
    center = np.asarray(diagnostic["score_center"])
    if not np.allclose(scores.mean(axis=0), center, rtol=1e-10, atol=1e-12):
        raise ValueError("PLS applicability score center differs from the retained calibration population.")
    if not np.allclose(feature_center @ projection, center, rtol=1e-10, atol=1e-12):
        raise ValueError("PLS feature-center and score-center frames cannot be reconciled.")
    covariance = (scores - center).T @ (scores - center) / (len(ids) - 1)
    eigenvalues = np.linalg.eigvalsh(covariance)
    tolerance = np.finfo(float).eps * scores.shape[1] * max(float(eigenvalues[-1]), 0.0)
    rank = int(np.count_nonzero(eigenvalues > tolerance))
    if rank != diagnostic["score_covariance_rank"] or not np.isclose(
        tolerance, diagnostic["rank_tolerance"], rtol=1e-9, atol=0
    ):
        raise ValueError("PLS applicability rank differs from retained calibration covariance.")
    inverse = diagnostic["score_covariance_inverse"]
    if inverse is not None and not np.allclose(
        np.asarray(inverse) @ covariance, np.eye(scores.shape[1]), rtol=1e-8, atol=1e-8
    ):
        raise ValueError("PLS applicability full covariance inverse differs from the retained calibration population.")
    return diagnostic, ids, feature_center


def without_decomposition(evidence, reason):
    """Keep global screening while explicitly withholding optional variable detail."""
    return {
        **evidence,
        "rows": {
            identity: {
                "variables": [],
                "q_total": row["q_total"],
                "t2_total": row["t2_total"],
                "omitted_q": None,
                "omitted_t2": None,
                "omitted_t2_absolute": None,
                "decomposition_unavailable_reason": reason,
            }
            for identity, row in evidence["rows"].items()
        },
    }


def build_applicability(
    state, model_digest, source_contract_digest, populations, rows, preprocessing, saved_scores, saved_loadings
):
    """Apply the exact fitted diagnostic state; calibration is used only to verify its custody."""
    p, k = state["features"], state["effective_n_components"]
    observations = sum(dataset.shape[0] for dataset in populations)
    if not 1 <= p <= 20000 or not 1 <= k <= 64 or not 1 <= observations <= 5000 or observations * p * k > MAX_WORK:
        raise ValueError("PLS applicability exceeds the bounded review calculation budget.")
    diagnostic, reference_ids, feature_center = _reference(state, populations[0], rows, saved_scores, saved_loadings)
    calibration_limit = None if diagnostic["t2_unavailable_reason"] else hotelling_t2_limit(len(reference_ids), k, 0.95)
    expected = {row["id"]: row for row in rows}
    if len(expected) != len(rows):
        raise ValueError("PLS applicability observation identities are duplicated.")
    count = min(10, max(1, MAX_TERMS // (observations * 2)))
    evidence, updates = {}, {}
    for dataset in populations:
        require_fitted_input_identity(dataset, state["input_identity"], features=p)
        ids = list(dataset.sample_axis.labels)
        if len(set(ids)) != len(ids) or any(identity not in expected or identity in evidence for identity in ids):
            raise ValueError("PLS applicability observation custody is inconsistent.")
        for start in range(0, len(ids), 64):
            applied = pls_applicability.apply_screening(
                np.asarray(dataset.X[start : start + 64], dtype=float), state["feature_offset"], diagnostic
            )
            z = (
                np.asarray(dataset.X[start : start + 64], dtype=float) - np.asarray(state["feature_offset"]).reshape(p)
            ) / diagnostic["x_scale"]
            scores = z @ np.asarray(diagnostic["projection"])
            if not np.isfinite(scores).all():
                raise ValueError("PLS applicability scores exceed finite numerical range.")
            for index, identity in enumerate(ids[start : start + 64]):
                canonical = applied["rows"][index]
                limit = calibration_limit if expected[identity]["role"] == "calibration" else diagnostic["t2_limit"]
                high_t = None if limit is None or canonical["t2"] is None else bool(canonical["t2"] > limit)
                high_q = canonical["outside_q"]
                updates[identity] = {
                    "scores": scores[index].tolist(),
                    "t2": canonical["t2"],
                    "q": canonical["q"],
                    "outside_t2": high_t,
                    "outside_q": high_q,
                    "screening_status": (
                        "outside_global_screen"
                        if high_t or high_q
                        else ("unavailable" if high_t is None or high_q is None else "within_global_screen")
                    ),
                    "applicability_unavailable_reason": diagnostic["t2_unavailable_reason"]
                    or diagnostic["q_unavailable_reason"],
                }
                try:
                    evidence[identity] = _row_terms(
                        z[index], scores[index], diagnostic, feature_center, canonical, count
                    )
                except ValueError as exc:
                    evidence[identity] = {
                        "variables": [],
                        "q_total": canonical["q"],
                        "t2_total": canonical["t2"],
                        "omitted_q": None,
                        "omitted_t2": None,
                        "omitted_t2_absolute": None,
                        "decomposition_unavailable_reason": str(exc),
                    }
    if set(evidence) != {row["id"] for row in rows if row["predicted"] is not None}:
        raise ValueError("PLS applicability population is incomplete.")
    axis = populations[0].feature_axis
    result = {
        "schema_version": SCHEMA,
        "model_digest": model_digest,
        "source_contract_digest": source_contract_digest,
        "feature_identity": _digest(state["input_identity"]),
        "reference_digest": _digest(reference_ids),
        "input_digests": [dataset.scientific_digest for dataset in populations],
        "reference_count": len(reference_ids),
        "components": k,
        "score_covariance_rank": diagnostic["score_covariance_rank"],
        "rank_tolerance": diagnostic["rank_tolerance"],
        "confidence": 0.95,
        "calibration_t2_limit": calibration_limit,
        "application_t2_limit": diagnostic["t2_limit"],
        "calibration_t2_limit_method": "jackson_f_calibration_0.95_strict_greater",
        "application_t2_limit_method": "jackson_f_prediction_0.95_strict_greater",
        "q_limit": diagnostic["q_limit"],
        "q_limit_method": diagnostic["q_limit_method"],
        "q_numerical_tolerance": diagnostic["q_numerical_tolerance"],
        "t2_unavailable_reason": diagnostic["t2_unavailable_reason"],
        "q_unavailable_reason": diagnostic["q_unavailable_reason"],
        "neighborhood_support": diagnostic["neighborhood_support"],
        "claim_scope": "provisional_global_screening",
        "space": (
            "PLS internally centered and scaled predictor space"
            if state["scale"]
            else "PLS internally centered predictor space"
        ),
        "internal_scale": state["scale"],
        "q_units": "squared standardized predictor units" if state["scale"] else "squared PLS input signal units",
        "score_units": "fitted latent predictor coordinates",
        "t2_units": "dimensionless",
        "preprocessing": preprocessing,
        "feature_count": p,
        "feature_values": np.asarray(axis.values).tolist() if axis is not None and axis.values is not None else None,
        "feature_units": state["feature_axis_units"] or "",
        "signal_units": state["input_identity"]["signal_units"],
        "top_per_statistic": count,
        "formula": (
            "Z=(X-offset)/scale; T=Z projection; E=Z-T reconstruction.T; "
            "Q=sum(E_j²); T²=(T-center) covariance_inverse (T-center).T"
        ),
        "contribution_formula": "Q_j=E_j²; T²_j=(Z_j-reference_mean_Z_j)[(T-center) covariance_inverse projection.T]_j",
        "rows": evidence,
    }
    if len(json.dumps(result, allow_nan=False).encode()) > MAX_BYTES:
        result = without_decomposition(result, "Optional applicability terms exceed the evidence budget.")
        if len(json.dumps(result, allow_nan=False).encode()) > MAX_BYTES:
            raise ValueError("PLS applicability exceeds the 6 MiB evidence budget.")
    return result, updates
