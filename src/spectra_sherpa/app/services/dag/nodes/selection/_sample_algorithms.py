"""Sample partitioning algorithms for chemometric calibration design.

Pure NumPy implementations of Kennard-Stone, DUPLEX, and SPXY.
"""

from __future__ import annotations

from typing import cast

import numpy as np
from sklearn.decomposition import PCA


def _pairwise_distances(X: np.ndarray, metric: str = "euclidean") -> np.ndarray:
    """Compute pairwise distance matrix."""
    if metric == "euclidean":
        from scipy.spatial.distance import cdist

        return cast(np.ndarray, cdist(X, X, metric="euclidean"))
    elif metric == "mahalanobis":
        cov = np.cov(X, rowvar=False)
        # Regularise for rank-deficient data
        cov += np.eye(cov.shape[0]) * 1e-8
        cov_inv = np.linalg.inv(cov)
        # Transform data so Euclidean distance = Mahalanobis distance
        L = np.linalg.cholesky(cov_inv)
        X_t = X @ L
        return _pairwise_distances(X_t, metric="euclidean")
    elif metric == "correlation":
        # 1 - correlation as distance
        X_centered = X - X.mean(axis=1, keepdims=True)
        norms = np.linalg.norm(X_centered, axis=1, keepdims=True)
        norms = np.maximum(norms, 1e-12)
        X_normed = X_centered / norms
        corr = X_normed @ X_normed.T
        np.clip(corr, -1.0, 1.0, out=corr)
        return cast(np.ndarray, 1.0 - corr)
    else:
        raise ValueError(f"Unknown metric: {metric!r}")


def _maybe_reduce(X: np.ndarray, n_pcs: int | None) -> np.ndarray:
    """Optionally reduce dimensionality with PCA before distance calculation."""
    if n_pcs is None or n_pcs <= 0 or n_pcs >= X.shape[1]:
        return X
    n_pcs = min(n_pcs, min(X.shape))
    pca = PCA(n_components=n_pcs)
    return cast(np.ndarray, pca.fit_transform(X))


def kennard_stone(
    X: np.ndarray,
    n_select: int,
    metric: str = "euclidean",
    n_pcs: int | None = None,
) -> np.ndarray:
    """Kennard-Stone sample selection (greedy maximin).

    Selects samples that uniformly cover the experimental space by
    iteratively choosing the sample with the maximum minimum distance
    to already-selected samples.

    Args:
        X: Data matrix, shape (n_samples, n_features).
        n_select: Number of samples to select.
        metric: Distance metric ('euclidean', 'mahalanobis', 'correlation').
        n_pcs: Optional PCA reduction before distance calculation.

    Returns:
        Integer index array of length *n_select* (selected sample indices).
    """
    n_samples = X.shape[0]
    if n_select >= n_samples:
        return np.arange(n_samples)
    if n_select < 1:
        raise ValueError("n_select must be >= 1")

    X_work = _maybe_reduce(X, n_pcs)
    D = _pairwise_distances(X_work, metric=metric)

    # Seed: pair with maximum distance
    i_raw, j_raw = np.unravel_index(np.argmax(D), D.shape)
    i = int(i_raw)
    j = int(j_raw)
    selected = [i, j]
    remaining = set(range(n_samples)) - {i, j}

    # Greedy maximin
    while len(selected) < n_select and remaining:
        # min distance to any selected sample, for each remaining sample
        min_dists = D[list(remaining)][:, selected].min(axis=1)
        remaining_list = list(remaining)
        best = remaining_list[int(np.argmax(min_dists))]
        selected.append(best)
        remaining.discard(best)

    return np.array(selected[:n_select], dtype=np.intp)


def duplex(
    X: np.ndarray,
    n_cal: int,
    metric: str = "euclidean",
    n_pcs: int | None = None,
) -> tuple[np.ndarray, np.ndarray]:
    """DUPLEX algorithm — simultaneous calibration/test partitioning.

    Alternates Kennard-Stone selection between calibration and test pools,
    so both sets cover the experimental space representatively.

    Args:
        X: Data matrix, shape (n_samples, n_features).
        n_cal: Number of calibration samples.
        metric: Distance metric.
        n_pcs: Optional PCA reduction.

    Returns:
        Tuple of (cal_indices, test_indices).
    """
    n_samples = X.shape[0]
    n_test = n_samples - n_cal
    if n_cal < 2 or n_test < 1:
        raise ValueError(f"Need n_cal >= 2 and n_test >= 1, got n_cal={n_cal}, n_test={n_test}")

    X_work = _maybe_reduce(X, n_pcs)
    D = _pairwise_distances(X_work, metric=metric)

    # Seed: pair with maximum distance → one to cal, one to test
    i_raw, j_raw = np.unravel_index(np.argmax(D), D.shape)
    i = int(i_raw)
    j = int(j_raw)
    cal = [i]
    test = [j]
    remaining = set(range(n_samples)) - {i, j}

    def _pick_next(pool: list[int], remaining: set[int]) -> int:
        """Pick sample from remaining with max min-distance to pool."""
        rem_list = list(remaining)
        min_dists = D[rem_list][:, pool].min(axis=1)
        best_idx = int(np.argmax(min_dists))
        return rem_list[best_idx]

    # Alternate between cal and test
    turn_cal = True
    while remaining:
        if turn_cal and len(cal) < n_cal:
            pick = _pick_next(cal, remaining)
            cal.append(pick)
            remaining.discard(pick)
        elif not turn_cal and len(test) < n_test:
            pick = _pick_next(test, remaining)
            test.append(pick)
            remaining.discard(pick)
        elif len(cal) < n_cal:
            pick = _pick_next(cal, remaining)
            cal.append(pick)
            remaining.discard(pick)
        else:
            pick = _pick_next(test, remaining)
            test.append(pick)
            remaining.discard(pick)
        turn_cal = not turn_cal

    return np.array(cal, dtype=np.intp), np.array(test, dtype=np.intp)


def spxy(
    X: np.ndarray,
    y: np.ndarray,
    n_cal: int,
    metric: str = "euclidean",
    n_pcs: int | None = None,
) -> tuple[np.ndarray, np.ndarray]:
    """SPXY — Sample set Partitioning based on joint X-Y distances.

    Extension of Kennard-Stone that considers both X-space (spectral)
    and Y-space (reference) distances when selecting calibration samples.
    Ensures the calibration set covers both measurement and property ranges.

    The combined distance is: D_xy = D_x / max(D_x) + D_y / max(D_y)

    Reference: Galvão et al., Talanta 67 (2005) 736-740.

    Args:
        X: Spectral data matrix, shape (n_samples, n_features).
        y: Target values, shape (n_samples,) or (n_samples, n_targets).
        n_cal: Number of calibration samples.
        metric: Distance metric for X-space.
        n_pcs: Optional PCA reduction for X-space distances.

    Returns:
        Tuple of (cal_indices, test_indices).
    """
    from scipy.spatial.distance import cdist

    n_samples = X.shape[0]
    n_test = n_samples - n_cal
    if n_cal < 2 or n_test < 1:
        raise ValueError(f"Need n_cal >= 2 and n_test >= 1, got n_cal={n_cal}, n_test={n_test}")

    # X-space distances
    X_work = _maybe_reduce(X, n_pcs)
    D_x = _pairwise_distances(X_work, metric=metric)

    # Y-space distances (always Euclidean)
    y_arr = np.asarray(y, dtype=np.float64)
    if y_arr.ndim == 1:
        y_arr = y_arr.reshape(-1, 1)
    D_y = cdist(y_arr, y_arr, metric="euclidean")

    # Normalise and combine
    max_dx = D_x.max()
    max_dy = D_y.max()
    if max_dx < 1e-12:
        max_dx = 1.0
    if max_dy < 1e-12:
        max_dy = 1.0

    D = D_x / max_dx + D_y / max_dy

    # Kennard-Stone on combined distance matrix
    i_raw, j_raw = np.unravel_index(np.argmax(D), D.shape)
    i = int(i_raw)
    j = int(j_raw)
    cal = [i, j]
    remaining = set(range(n_samples)) - {i, j}

    while len(cal) < n_cal and remaining:
        rem_list = list(remaining)
        min_dists = D[rem_list][:, cal].min(axis=1)
        best = rem_list[int(np.argmax(min_dists))]
        cal.append(best)
        remaining.discard(best)

    test = sorted(remaining)
    return np.array(cal, dtype=np.intp), np.array(test, dtype=np.intp)
