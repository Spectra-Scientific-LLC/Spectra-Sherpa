"""Sole Chong-Jun/mdatools VIP (Variable Importance in Projection) authority."""

from __future__ import annotations

import numpy as np


def calculate_vip(
    x_scores: np.ndarray,
    x_weights: np.ndarray,
    y_loadings: np.ndarray,
    n_features: int,
) -> np.ndarray:
    """Calculate combined-response VIP scores from PLS model components.

    VIP_i = sqrt(n_features * sum(s_h * w_{i,h}^2) / sum(s_h))

    where s_h = explained variance per component, w_{i,h} = normalised
    loading weight for feature i on component h.

    Args:
        x_scores: T matrix, shape (n_samples, n_components).
        x_weights: W matrix in either common orientation,
            (n_features, n_components) or (n_components, n_features).
        y_loadings: Q matrix, shape (n_targets, n_components) or
            (n_components,).
        n_features: Number of spectral variables.

    Returns:
        1-D float64 array of length *n_features*.  Values > 1.0 indicate
        important variables by the standard convention.
    """
    if isinstance(n_features, bool) or not isinstance(n_features, int) or n_features < 1:
        raise ValueError("VIP requires a positive feature count")
    t = np.asarray(x_scores, dtype=np.float64)
    w_raw = np.asarray(x_weights, dtype=np.float64)
    q_raw = np.asarray(y_loadings, dtype=np.float64)

    if (
        t.ndim != 2
        or w_raw.ndim != 2
        or q_raw.ndim not in {1, 2}
        or not np.isfinite(t).all()
        or not np.isfinite(w_raw).all()
        or not np.isfinite(q_raw).all()
    ):
        raise ValueError("VIP requires finite score, weight, and loading matrices")

    n_components = t.shape[1]

    # Normalise weight orientation to (n_features, n_components).
    if w_raw.shape == (n_components, n_features):
        w = w_raw.T
    elif w_raw.shape == (n_features, n_components):
        w = w_raw
    else:
        raise ValueError("VIP weight dimensions do not match scores and features")

    # Normalise loading orientation to (n_components, n_targets).
    q = q_raw.reshape(-1, 1) if q_raw.ndim == 1 else q_raw
    if q.shape[0] == n_components:
        pass
    elif q.shape[1] == n_components:
        q = q.T
    else:
        raise ValueError("VIP loading dimensions do not match score components")

    # Each component contribution is ||t_h||² ||q_h||². A relative activity
    # floor makes the unitless VIP invariant to changing response units while
    # excluding a trailing component retained after the response residual is
    # constant.
    explained_y = np.sum(t * t, axis=0) * np.sum(q * q, axis=1)
    if not np.isfinite(explained_y).all() or np.any(explained_y < 0.0):
        raise ValueError("VIP response contributions are invalid")
    maximum_contribution = float(np.max(explained_y, initial=0.0))
    if maximum_contribution <= 0.0:
        raise ValueError("VIP requires explained response variance")
    active = explained_y > np.finfo(np.float64).eps * maximum_contribution
    if not np.any(active):
        raise ValueError("VIP requires an active response component")
    active_weights = w[:, active]
    weight_norms = np.linalg.norm(active_weights, axis=0)
    if np.any(weight_norms <= 0.0):
        raise ValueError("VIP has a degenerate weight vector with response contribution")
    normalized_weights = active_weights / weight_norms
    active_contributions = explained_y[active]
    total_contribution = float(np.sum(active_contributions))
    vip = np.sqrt(n_features * ((normalized_weights * normalized_weights) @ active_contributions) / total_contribution)
    if vip.shape != (n_features,) or not np.isfinite(vip).all() or np.any(vip < 0.0):
        raise ValueError("VIP calculation produced invalid scores")
    return np.asarray(vip, dtype=np.float64)
