"""Shared VIP (Variable Importance in Projection) calculation.

Extracted from PLS-DA so it can be used by both classification nodes
and the standalone variable selection node.
"""

from __future__ import annotations

import numpy as np


def calculate_vip(
    x_scores: np.ndarray,
    x_weights: np.ndarray,
    y_loadings: np.ndarray,
    n_features: int,
) -> np.ndarray:
    """Calculate VIP scores from PLS model components.

    VIP_i = sqrt(n_features * sum(s_h * w_{i,h}^2) / sum(s_h))

    where s_h = explained variance per component, w_{i,h} = normalised
    loading weight for feature i on component h.

    Args:
        x_scores: T matrix, shape (n_samples, n_components).
        x_weights: W matrix, shape (n_components, n_features) — will be
            transposed internally to (n_features, n_components).
        y_loadings: Q matrix, shape (n_targets, n_components) or
            (n_components,).
        n_features: Number of spectral variables.

    Returns:
        1-D float64 array of length *n_features*.  Values > 1.0 indicate
        important variables by the standard convention.
    """
    t = np.asarray(x_scores, dtype=np.float64)
    w_raw = np.asarray(x_weights, dtype=np.float64)
    q_raw = np.asarray(y_loadings, dtype=np.float64)

    # Ensure 2-D
    if t.ndim != 2 or w_raw.ndim != 2 or q_raw.ndim < 1:
        return np.zeros(n_features, dtype=np.float64)

    n_components = t.shape[1]

    # Normalise weight orientation to (n_features, n_components).
    if w_raw.shape == (n_components, n_features):
        w = w_raw.T
    elif w_raw.shape == (n_features, n_components):
        w = w_raw
    else:
        return np.zeros(n_features, dtype=np.float64)

    # Normalise loading orientation to (n_components, n_targets).
    q = q_raw.reshape(-1, 1) if q_raw.ndim == 1 else q_raw
    if q.shape[0] == n_components:
        pass
    elif q.shape[1] == n_components:
        q = q.T
    else:
        return np.zeros(n_features, dtype=np.float64)

    # Explained Y-variance contribution per latent variable:
    # diag(T'T QQ') for q shaped (n_components, n_targets).
    s = np.diag(t.T @ t @ q @ q.T).reshape(n_components, -1)
    s = np.nan_to_num(s, nan=0.0, posinf=0.0, neginf=0.0)
    total_s = float(np.sum(s))
    if total_s <= 1e-12:
        return np.zeros(n_features, dtype=np.float64)

    # VIP per feature
    vip = np.zeros(n_features, dtype=np.float64)
    for i in range(n_features):
        weights = np.empty(n_components, dtype=np.float64)
        for j in range(n_components):
            norm = float(np.linalg.norm(np.nan_to_num(w[:, j], nan=0.0)))
            if norm <= 1e-12:
                weights[j] = 0.0
            else:
                weights[j] = (w[i, j] / norm) ** 2
        vip[i] = np.sqrt(n_features * np.sum(s.flatten() * weights) / total_s)

    return np.nan_to_num(vip, nan=0.0, posinf=0.0, neginf=0.0)


def extract_vip_from_pls_model(pls_model: object, n_features: int) -> np.ndarray:
    """Extract VIP scores from a SpectroChemPy PLS or PLS-DA model.

    Tries multiple attribute name conventions for version resilience.

    Args:
        pls_model: Trained SpectroChemPy PLSRegression instance.
        n_features: Number of spectral variables in the training data.

    Returns:
        VIP scores array of length *n_features*, or zeros on failure.
    """
    from spectra_sherpa.app.lib.adapters.scp_extractors import _safe_getattr

    def _coerce(raw: object) -> np.ndarray | None:
        if raw is None:
            return None
        arr = np.asarray(raw)
        if hasattr(raw, "data"):
            arr = np.asarray(raw.data)
        return arr.astype(np.float64)

    raw_t = _safe_getattr(pls_model, ("x_scores", "_x_scores", "x_scores_"))
    raw_w = _safe_getattr(pls_model, ("x_weights", "_x_weights", "x_weights_"))
    raw_q = _safe_getattr(pls_model, ("y_loadings", "_y_loadings", "y_loadings_"))

    t = _coerce(raw_t)
    w = _coerce(raw_w)
    q = _coerce(raw_q)

    if t is None or w is None or q is None:
        return np.zeros(n_features, dtype=np.float64)

    return calculate_vip(t, w, q, n_features)
