"""Scale-invariant numerical rank policy for PCA fitting and diagnostics."""

from __future__ import annotations

import numpy as np

# Eigenvalue ratio (squared singular-value ratio). Retained directions below
# this relative resolution cannot support meaningful inverse-variance diagnostics.
PCA_EIGENVALUE_RTOL = 1e-12


def require_resolved_pca_eigenvalues(values: object) -> np.ndarray:
    eigenvalues = np.asarray(values, dtype=np.float64)
    if eigenvalues.ndim != 1 or not eigenvalues.size or not np.isfinite(eigenvalues).all():
        raise ValueError("PCA eigenvalues must be a finite nonempty vector")
    largest = float(np.max(eigenvalues))
    if largest <= 0 or np.any(eigenvalues <= largest * PCA_EIGENVALUE_RTOL):
        raise ValueError("PCA retains numerical-null components; reduce n_components to the resolved numerical rank")
    return eigenvalues


def hotelling_t2_limit(samples: int, components: int, confidence: float, *, prediction: bool = False) -> float:
    """Jackson F limit; prediction includes uncertainty in the fitted mean."""
    from scipy.stats import f

    if samples <= components or components < 1 or not 0 < confidence < 1:
        raise ValueError("T2 limit requires positive residual degrees of freedom and confidence in (0, 1)")
    limit = components * (samples - 1) / (samples - components) * f.ppf(confidence, components, samples - components)
    return float(limit * ((samples + 1) / samples if prediction else 1))


def residual_eigenvalues(residuals: np.ndarray) -> np.ndarray:
    """Eigenvalues of the calibration residual second moment, in signal² units."""
    residuals = np.asarray(residuals, dtype=np.float64)
    if residuals.ndim != 2 or residuals.shape[0] < 2 or not np.isfinite(residuals).all():
        raise ValueError("Residual limits require at least two finite calibration rows")
    return np.linalg.svd(residuals, compute_uv=False) ** 2 / (residuals.shape[0] - 1)


def residual_q_limit(eigenvalues: object, confidence: float) -> tuple[float, str]:
    """Jackson–Mudholkar Q limit, with an explicit moment fallback when h0 <= 0.

    Normalize moments by their largest eigenvalue to avoid unit-dependent
    underflow. Eigenvector's residuallimit documents both JM and chi² moments.
    """
    from scipy.stats import chi2, norm

    eigen = np.asarray(eigenvalues, dtype=np.float64)
    if eigen.ndim != 1 or not np.isfinite(eigen).all() or np.any(eigen < 0) or not 0 < confidence < 1:
        raise ValueError("Q limits require finite nonnegative residual eigenvalues")
    largest = float(np.max(eigen, initial=0))
    if largest == 0:
        return 0.0, "no_residual_variance"
    scaled = eigen / largest
    theta1, theta2, theta3 = (float(np.sum(scaled**power)) for power in (1, 2, 3))
    h0 = 1 - 2 * theta1 * theta3 / (3 * theta2**2)
    base = 1 + norm.ppf(confidence) * np.sqrt(2 * theta2) * h0 / theta1 + theta2 * h0 * (h0 - 1) / theta1**2
    if h0 > 0 and base > 0:
        result = largest * theta1 * base ** (1 / h0)
        method = "jackson_mudholkar"
    else:
        result = largest * theta2 / theta1 * chi2.ppf(confidence, theta1**2 / theta2)
        method = "chi_squared_residual_moments"
    if not np.isfinite(result) or result < 0:
        raise ValueError("Q limit is not finitely representable")
    return float(result), method
