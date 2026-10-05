"""Target-projection Selectivity Ratio scientific authority.

The regression vector defines the predictive score direction.  It is not the
loading used to reconstruct the predictor matrix.  The loading is the
least-squares projection of every centered predictor onto that score.  This
distinction makes the reconstructed and residual predictor spaces orthogonal,
which is required before their variable-wise variance ratio is interpreted as
a Selectivity Ratio.

References
----------
Kvalheim, O. M. (2010). Interpretation of partial least squares regression
models by means of target projection and selectivity ratio plots. Journal of
Chemometrics, 24, 496-504. https://doi.org/10.1002/cem.1289

Rajalahti, T. et al. (2009). Biomarker discovery in mass spectral profiles by
means of selectivity ratio plot. Chemometrics and Intelligent Laboratory
Systems, 95, 35-48. https://doi.org/10.1016/j.chemolab.2008.08.004
"""

from __future__ import annotations

import numpy as np


def target_projection_selectivity_ratio(matrix: np.ndarray, regression_vector: np.ndarray) -> np.ndarray:
    """Return variable-wise target-projection explained/residual variance.

    ``matrix`` contains the calibration rows used to fit ``regression_vector``.
    The operation centers ``matrix`` because the fitted intercept is not part
    of the target-projection direction.  Scaling the regression vector does
    not change the result; normalizing it first improves numerical stability.
    """

    predictors = np.asarray(matrix, dtype=np.float64)
    coefficients = np.asarray(regression_vector, dtype=np.float64).reshape(-1)
    if predictors.ndim != 2 or predictors.shape[1] < 1:
        raise ValueError("Selectivity Ratio requires a two-dimensional predictor matrix")
    if coefficients.shape != (predictors.shape[1],):
        raise ValueError("Selectivity Ratio regression vector must match the predictor count")
    if not np.isfinite(predictors).all() or not np.isfinite(coefficients).all():
        raise ValueError("Selectivity Ratio inputs must be finite")

    coefficient_scale = float(np.max(np.abs(coefficients)))
    if coefficient_scale == 0.0:
        raise ValueError("Selectivity Ratio requires a non-zero target-projection direction")
    scaled_coefficients = coefficients / coefficient_scale
    direction = scaled_coefficients / np.linalg.norm(scaled_coefficients)
    centered = predictors - np.mean(predictors, axis=0)
    raw_target_scores = centered @ direction
    score_scale = float(np.max(np.abs(raw_target_scores)))
    if score_scale == 0.0:
        raise ValueError("Selectivity Ratio requires a non-zero target-projection score")
    # Score scaling cancels in t @ p.T. Normalizing here prevents otherwise
    # valid, uniformly small predictor units from underflowing t.T @ t.
    target_scores = raw_target_scores / score_scale
    score_sum_of_squares = float(target_scores @ target_scores)
    if score_sum_of_squares == 0.0:
        raise ValueError("Selectivity Ratio requires a non-zero target-projection score")

    target_loadings = centered.T @ target_scores / score_sum_of_squares
    target_projection = np.outer(target_scores, target_loadings)
    residual = centered - target_projection
    explained_variance = np.var(target_projection, axis=0)
    residual_variance = np.var(residual, axis=0)
    variable_scale = np.maximum(np.var(centered, axis=0), explained_variance)
    floor = np.maximum(np.finfo(np.float64).eps * variable_scale, np.finfo(np.float64).tiny)
    scores = explained_variance / np.maximum(residual_variance, floor)
    if scores.shape != (predictors.shape[1],) or not np.isfinite(scores).all() or np.any(scores < 0.0):
        raise RuntimeError("Selectivity Ratio produced invalid variable scores")
    return scores


__all__ = ["target_projection_selectivity_ratio"]
