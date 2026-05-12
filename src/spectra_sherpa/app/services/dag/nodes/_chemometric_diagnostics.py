"""Shared chemometric diagnostics.

Per-sample Hotelling T² and Q (SPE) residuals for PLS / PCA / SIMCA, plus
the Pomerantsev (J. Chemom. 2008) data-driven moments method for critical
limits.

These functions are kept algorithm-agnostic on purpose: they operate on
score / loading / data matrices and return numpy arrays, so any node
(PLS, SIMCA, PCA outlier detection) can call them without circular
imports.
"""

from __future__ import annotations

import numpy as np
from scipy.stats import chi2


def hotelling_t2_per_sample(
    scores: np.ndarray,
    *,
    score_covariance: np.ndarray | None = None,
    eigenvalues: np.ndarray | None = None,
) -> np.ndarray:
    """Hotelling T² for each sample.

    Two regimes are supported:

    - PCA-style (orthogonal scores): pass ``eigenvalues`` — the diagonal
      Mahalanobis form ``T²_i = Σ_h t_{i,h}² / λ_h`` is used.
    - PLS-style (non-orthogonal scores): pass ``score_covariance``
      ``Σ_T = T'T / (n−1)`` — the full Mahalanobis form
      ``T²_i = t_i' Σ_T^{-1} t_i`` is used. This is the chemometric
      standard for PLS regression diagnostics (de Maesschalck et al.,
      Chemom. Intell. Lab. Syst. 2000).

    Args:
        scores: (n_samples, n_components) score matrix.
        score_covariance: (n_components, n_components) — required for PLS.
        eigenvalues: (n_components,) — required for PCA.

    Returns:
        (n_samples,) array of T² values.
    """
    if scores.ndim != 2:
        raise ValueError(f"scores must be 2D, got shape {scores.shape}")
    if eigenvalues is None and score_covariance is None:
        raise ValueError("Provide either eigenvalues (PCA) or score_covariance (PLS)")

    if eigenvalues is not None:
        eig = np.maximum(np.asarray(eigenvalues, dtype=np.float64), 1e-12)
        result: np.ndarray = np.sum((scores**2) / eig, axis=1)
        return result

    cov = np.asarray(score_covariance, dtype=np.float64)
    # Regularise against rank-deficient score covariance (common with few
    # samples or strongly collinear LVs); fall back to pseudo-inverse so
    # downstream callers don't see a LinAlgError on edge-case datasets.
    try:
        cov_inv = np.linalg.inv(cov)
    except np.linalg.LinAlgError:
        cov_inv = np.linalg.pinv(cov)
    # T²_i = t_i' Σ⁻¹ t_i, vectorised over samples
    out: np.ndarray = np.einsum("ij,jk,ik->i", scores, cov_inv, scores)
    return out


def q_residuals_per_sample(X_centered: np.ndarray, reconstructed: np.ndarray) -> np.ndarray:
    """Q-residuals (Squared Prediction Error) for each sample.

    Q_i = ||x_i − x̂_i||² in the same (centered, optionally scaled) space
    that the reconstruction lives in. Both inputs must already be
    centered/scaled identically.

    Args:
        X_centered: (n_samples, n_features) input matrix in model space.
        reconstructed: (n_samples, n_features) reconstruction from the
            model (e.g. ``T @ P.T`` for PCA/PLS).

    Returns:
        (n_samples,) array of Q values.
    """
    if X_centered.shape != reconstructed.shape:
        raise ValueError(
            f"X_centered shape {X_centered.shape} does not match reconstructed shape {reconstructed.shape}"
        )
    residual = X_centered - reconstructed
    result: np.ndarray = np.sum(residual**2, axis=1)
    return result


def pomerantsev_dd_limit(
    stat_values: np.ndarray,
    confidence_level: float,
) -> tuple[float, float, float]:
    """Critical limit by the Pomerantsev data-driven moments (DD) method.

    Estimates an effective number of degrees of freedom directly from the
    sample moments of a statistic (Hotelling T² or Q-residuals), then
    scales a chi-squared quantile.

    Method of moments (Pomerantsev, J. Chemom. 2008):
        DoF = 2 · μ² / σ²
        h   = μ / DoF           (scale factor; equivalent to σ² / (2 μ))
        crit = h · χ²(α, DoF)

    The DD form is robust when the theoretical F / χ²-with-fixed-DoF
    limits over-reject (heavy-tailed Q, small samples). When sample
    variance is degenerate (≤ 0) or insufficient samples exist, falls
    back to the empirical quantile of the values themselves.

    Args:
        stat_values: 1-D array of T² or Q values from calibration samples.
        confidence_level: e.g. 0.95 → 95th-percentile critical value.

    Returns:
        (critical_value, effective_dof, scale_h) — the limit plus the
        intermediate DoF and h so callers can persist them in diagnostics.
    """
    vals = np.asarray(stat_values, dtype=np.float64)
    vals = vals[np.isfinite(vals)]
    if vals.size < 2:
        # Not enough samples for moments; fall back to the empirical
        # quantile (degenerate DoF / h reported as NaN).
        crit = float(np.quantile(vals, confidence_level)) if vals.size else 0.0
        return crit, float("nan"), float("nan")

    mean_v = float(np.mean(vals))
    var_v = float(np.var(vals, ddof=1))

    if mean_v <= 0.0 or var_v <= 0.0:
        crit = float(np.quantile(vals, confidence_level))
        return crit, float("nan"), float("nan")

    dof = max(2.0 * mean_v * mean_v / var_v, 1.0)
    h = mean_v / dof
    crit = float(h * chi2.ppf(confidence_level, dof))
    return crit, float(dof), float(h)
