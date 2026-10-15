"""Shared fitted predictor-space Q and T² per-variable terms."""

from __future__ import annotations

import numpy as np


def row_terms(z, scores, diagnostic, feature_center, canonical, count):
    residual = z - scores @ np.asarray(diagnostic["reconstruction"]).T
    q_terms = residual * residual
    inverse = diagnostic["score_covariance_inverse"]
    t_terms = (
        None
        if inverse is None
        else (z - feature_center)
        * ((scores - diagnostic["score_center"]) @ np.asarray(inverse) @ np.asarray(diagnostic["projection"]).T)
    )
    if not np.isfinite(q_terms).all() or (t_terms is not None and not np.isfinite(t_terms).all()):
        raise ValueError("PLS applicability terms exceed finite numerical range.")
    for terms, total in ((q_terms, canonical["q"]), (t_terms, canonical["t2"])):
        if terms is not None:
            signed_sum, absolute_mass = terms.sum(), np.abs(terms).sum()
            if (
                not np.isfinite(signed_sum)
                or not np.isfinite(absolute_mass)
                or not np.isclose(signed_sum, total, rtol=1e-9, atol=1e-12 * max(1.0, absolute_mass))
            ):
                raise ValueError("PLS applicability terms do not reproduce retained screening totals.")
    indices = set(np.argsort(-q_terms, kind="stable")[:count].tolist())
    if t_terms is not None:
        indices.update(np.argsort(-np.abs(t_terms), kind="stable")[:count].tolist())
    indices = sorted(indices)
    omitted = np.ones(len(z), dtype=bool)
    omitted[indices] = False
    return {
        "variables": [[j, float(q_terms[j]), None if t_terms is None else float(t_terms[j])] for j in indices],
        "q_total": canonical["q"],
        "t2_total": canonical["t2"],
        "omitted_q": float(q_terms[omitted].sum()),
        "omitted_t2": None if t_terms is None else float(t_terms[omitted].sum()),
        "omitted_t2_absolute": None if t_terms is None else float(np.abs(t_terms[omitted]).sum()),
    }
