"""
Unified NDDataset-native preprocessing for spectral data.

This module provides preprocessing functions that operate directly on
SpectroChemPy NDDataset objects, preserving coordinates and metadata.

MIGRATED FROM: project0/preprocess.py
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, List, Optional, Tuple

import numpy as np

try:
    from scipy import sparse
    from scipy.interpolate import PchipInterpolator, interp1d
    from scipy.ndimage import gaussian_filter1d as scipy_gaussian_filter1d
    from scipy.signal import savgol_filter as scipy_savgol

    HAS_SCIPY = True
except ImportError:
    HAS_SCIPY = False
    interp1d = None
    PchipInterpolator = None
    scipy_savgol = None
    scipy_gaussian_filter1d = None
    sparse = None

try:
    from joblib import Parallel, delayed

    HAS_JOBLIB = True
except ImportError:
    HAS_JOBLIB = False
    Parallel = None
    delayed = None


def _get_parallel_threshold() -> int:
    """Read parallel threshold from app settings, with env-var fallback."""
    try:
        from spectra_sherpa.app.core.config import settings

        return settings.parallel_threshold
    except Exception:
        import os

        return int(os.getenv("PARALLEL_THRESHOLD", "100"))


if TYPE_CHECKING:
    from spectra_sherpa.app.lib.scp_compat import NDDataset


@dataclass
class PreprocessingSettings:
    """Configuration for spectral preprocessing pipeline."""

    # Wavenumber alignment
    align_wavenumbers: bool = False
    alignment_method: str = "pchip"  # "none", "sinc", "pchip", "linear"
    merge_tolerance: float = 0.05  # cm^-1 for golden grid merging

    # Cosmic ray removal
    remove_cosmic_rays: bool = False
    cosmic_ray_window: int = 11
    cosmic_ray_zscore: float = 6.0

    # Smoothing
    apply_smoothing: bool = False
    smoothing_window: int = 11
    smoothing_polyorder: int = 2

    # Range limiting
    clip_range: bool = False
    min_wavenumber: Optional[float] = 400.0
    max_wavenumber: Optional[float] = 4000.0


# ─────────────────────────────────────────────────────────────────────────────
# GOLDEN GRID CONSTRUCTION
# ─────────────────────────────────────────────────────────────────────────────


def build_golden_grid(
    datasets: List["NDDataset"],
    merge_tolerance: float = 0.05,
) -> np.ndarray:
    """
    Build a golden wavenumber grid from union of all input grids.

    Parameters
    ----------
    datasets : list[NDDataset]
        Input datasets with x-coordinates
    merge_tolerance : float
        Tolerance (cm^-1) for merging near-duplicate points

    Returns
    -------
    np.ndarray
        Merged wavenumber grid spanning all input ranges
    """
    wavenumbers = []
    for ds in datasets:
        wn = None
        # SherpaDataset path
        if hasattr(ds, "feature_axis") and ds.feature_axis is not None:
            wn = np.asarray(ds.feature_axis.values)
        # NDDataset path
        elif hasattr(ds, "x") and ds.x is not None:
            wn = ds.x.data if hasattr(ds.x, "data") else np.array(ds.x)
        if wn is not None:
            wavenumbers.append(wn)

    if not wavenumbers:
        raise ValueError("No wavenumber arrays found in datasets")

    # Concatenate all wavenumber points
    all_points = np.concatenate(wavenumbers)
    if all_points.size == 0:
        raise ValueError("No wavenumber points provided")

    # Sort and merge nearby points
    sorted_points = np.sort(all_points)
    merged: List[float] = []
    cluster: List[float] = [float(sorted_points[0])]

    for value in sorted_points[1:]:
        if abs(value - cluster[-1]) <= merge_tolerance:
            cluster.append(float(value))
        else:
            merged.append(float(np.mean(cluster)))
            cluster = [float(value)]

    merged.append(float(np.mean(cluster)))
    return np.array(merged)


# ─────────────────────────────────────────────────────────────────────────────
# INTERPOLATION
# ─────────────────────────────────────────────────────────────────────────────


def _min_spacing(values: np.ndarray) -> float:
    """Calculate median spacing between unique sorted values."""
    unique = np.unique(np.sort(values))
    diffs = np.diff(unique)
    positive_diffs = diffs[diffs > 0]
    return float(np.median(positive_diffs)) if positive_diffs.size else 1.0


def _sinc_interpolate(
    x: np.ndarray,
    y: np.ndarray,
    x_new: np.ndarray,
    kernel_half_width: int = 8,
) -> np.ndarray:
    """
    Sinc interpolation limited to a local window.

    Ideal for spectroscopic data with sharp peaks where cubic splines
    would introduce oscillations (Gibbs phenomenon).
    """
    if x.size == 0:
        return np.zeros_like(x_new)

    spacing = _min_spacing(x)
    y_new = np.zeros_like(x_new, dtype=float)

    for idx, center in enumerate(x_new):
        mask = np.abs(x - center) <= kernel_half_width * spacing
        if not np.any(mask):
            continue
        dx = center - x[mask]
        weights = np.sinc(dx / spacing)
        weight_sum = weights.sum()
        if abs(weight_sum) > 1e-12:
            y_new[idx] = (weights * y[mask]).sum() / weight_sum

    return y_new


def interpolate_to_grid(
    dataset: "NDDataset",
    target_grid: np.ndarray,
    method: str = "pchip",
    warn_undersampling: bool = True,
    expected_peak_width: float = 1.0,
) -> "NDDataset":
    """
    Interpolate dataset onto target wavenumber grid.

    Parameters
    ----------
    dataset : NDDataset
        Input dataset with x-coordinates
    target_grid : np.ndarray
        Target wavenumber grid
    method : str
        Interpolation method: 'sinc', 'pchip', or 'linear'
    warn_undersampling : bool
        If True, warn when target grid is too coarse for sharp peaks
    expected_peak_width : float
        Expected minimum peak width in cm^-1 (for undersampling warning)

    Returns
    -------
    NDDataset
        Interpolated dataset with new x-coordinates and resolution metadata
    """
    from spectra_sherpa.app.lib.scp_compat import require_scp, scp

    require_scp("Spectral interpolation")
    import warnings

    from .spectral.dataset import add_provenance

    if method not in {"none", "sinc", "pchip", "linear"}:
        raise ValueError(f"method must be 'none', 'sinc', 'pchip', or 'linear', got '{method}'")

    if method in {"pchip", "linear"} and not HAS_SCIPY:
        raise ImportError("SciPy is required for interpolation")

    # Get original wavenumbers (SherpaDataset or NDDataset)
    if hasattr(dataset, "feature_axis") and dataset.feature_axis is not None:
        wavenumber = np.asarray(dataset.feature_axis.values)
    elif hasattr(dataset, "x") and dataset.x is not None:
        wavenumber = dataset.x.data if hasattr(dataset.x, "data") else np.array(dataset.x)
    else:
        raise ValueError("Dataset has no wavenumber/feature axis")

    # Calculate grid spacings for resolution tracking
    original_spacing = float(np.median(np.abs(np.diff(wavenumber))))
    target_spacing = float(np.median(np.abs(np.diff(target_grid))))

    # Warn if target grid is too coarse (undersampling)
    if warn_undersampling and target_spacing > expected_peak_width / 2:
        warnings.warn(
            f"Target grid spacing ({target_spacing:.3f} cm^-1) may be too coarse "
            f"for peaks with FWHM < {expected_peak_width:.1f} cm^-1. "
            f"Peak heights may be underestimated by 10-30%. "
            f"Original spacing was {original_spacing:.3f} cm^-1.",
            UserWarning,
        )

    # Ensure ascending order
    if wavenumber[0] > wavenumber[-1]:
        wavenumber = wavenumber[::-1]
        data = dataset.data[..., ::-1]
    else:
        data = dataset.data

    # Handle 1D and 2D data
    if data.ndim == 1:
        data = data.reshape(1, -1)
        was_1d = True
    else:
        was_1d = False

    n_samples = data.shape[0]
    n_target = len(target_grid)
    interpolated = np.zeros((n_samples, n_target), dtype=float)

    # Find points within the native range
    within = (target_grid >= wavenumber.min()) & (target_grid <= wavenumber.max())
    target_within = target_grid[within]

    for i in range(n_samples):
        spectrum = data[i]

        # Ensure unique wavenumbers
        order = np.argsort(wavenumber)
        wn_sorted = wavenumber[order]
        spec_sorted = spectrum[order]
        unique_wn, unique_idx = np.unique(wn_sorted, return_index=True)
        spec_unique = spec_sorted[unique_idx]

        if target_within.size == 0:
            continue

        if method == "sinc":
            interpolated[i, within] = _sinc_interpolate(unique_wn, spec_unique, target_within)
        elif method == "pchip":
            if len(unique_wn) < 2:
                continue
            interp = PchipInterpolator(unique_wn, spec_unique, extrapolate=False)
            result = interp(target_within)
            interpolated[i, within] = np.nan_to_num(result, nan=0.0)
        elif method == "linear":
            interp = interp1d(unique_wn, spec_unique, kind="linear", bounds_error=False, fill_value=0.0)
            interpolated[i, within] = interp(target_within)

    # Create result dataset
    if was_1d:
        interpolated = interpolated[0]

    result = scp.NDDataset(interpolated)
    result.x = scp.Coord(target_grid, title="Wavenumber", units="cm^-1")

    if hasattr(dataset, "y") and dataset.y is not None:
        result.y = dataset.y.copy()

    if hasattr(dataset, "units") and dataset.units:
        result.units = dataset.units

    if hasattr(dataset, "title"):
        result.title = dataset.title

    if hasattr(dataset, "meta") and dataset.meta:
        result.meta.update(dict(dataset.meta))

    # Track spectral resolution in metadata
    result.meta["spectral_resolution"] = {
        "original_spacing": original_spacing,
        "current_spacing": target_spacing,
        "interpolated": True,
        "interpolation_method": method,
        "interpolation_ratio": target_spacing / original_spacing if original_spacing > 0 else None,
    }

    add_provenance(
        result,
        "interpolate_to_grid",
        {
            "method": method,
            "n_points": len(target_grid),
            "original_spacing": original_spacing,
            "target_spacing": target_spacing,
        },
    )

    return result


# ─────────────────────────────────────────────────────────────────────────────
# COSMIC RAY REMOVAL
# ─────────────────────────────────────────────────────────────────────────────


def remove_cosmic_rays(
    dataset: "NDDataset",
    window_size: int = 11,
    zscore_threshold: float = 6.0,
) -> "NDDataset":
    """
    Remove cosmic ray spikes using local median/MAD statistics.

    Parameters
    ----------
    dataset : NDDataset
        Input dataset
    window_size : int
        Size of the rolling window (must be odd)
    zscore_threshold : float
        Z-score threshold for spike detection

    Returns
    -------
    NDDataset
        Dataset with cosmic rays replaced by local median
    """
    from spectra_sherpa.app.lib.scp_compat import require_scp, scp

    require_scp("Spectral preprocessing")
    from .spectral.dataset import add_provenance

    if window_size % 2 == 0:
        window_size += 1

    data = dataset.data.copy()
    if data.ndim == 1:
        data = data.reshape(1, -1)
        was_1d = True
    else:
        was_1d = False

    half_window = window_size // 2
    n_samples, n_points = data.shape

    for i in range(n_samples):
        spectrum = data[i]
        for j in range(n_points):
            start = max(0, j - half_window)
            end = min(n_points, j + half_window + 1)
            window = spectrum[start:end]

            median = np.median(window)
            mad = np.median(np.abs(window - median))
            if mad < 1e-10:
                continue

            zscore = (spectrum[j] - median) / (mad * 1.4826)  # MAD to std conversion
            if abs(zscore) > zscore_threshold:
                data[i, j] = median

    if was_1d:
        data = data[0]

    result = scp.NDDataset(data)

    # Preserve coordinates and metadata
    if hasattr(dataset, "x") and dataset.x is not None:
        result.x = dataset.x.copy()
    if hasattr(dataset, "y") and dataset.y is not None:
        result.y = dataset.y.copy()
    if hasattr(dataset, "units") and dataset.units:
        result.units = dataset.units
    if hasattr(dataset, "title"):
        result.title = dataset.title
    if hasattr(dataset, "meta") and dataset.meta:
        result.meta.update(dict(dataset.meta))

    add_provenance(
        result,
        "remove_cosmic_rays",
        {"window_size": window_size, "zscore_threshold": zscore_threshold},
    )

    return result


# ─────────────────────────────────────────────────────────────────────────────
# SMOOTHING
# ─────────────────────────────────────────────────────────────────────────────


def smooth_savgol(
    dataset: "NDDataset",
    window_size: int = 11,
    polyorder: int = 2,
) -> "NDDataset":
    """
    Apply Savitzky-Golay smoothing.

    Parameters
    ----------
    dataset : NDDataset
        Input dataset
    window_size : int
        Size of the filter window (must be odd)
    polyorder : int
        Order of the polynomial

    Returns
    -------
    NDDataset
        Smoothed dataset
    """
    from spectra_sherpa.app.lib.scp_compat import require_scp, scp

    require_scp("Spectral preprocessing")
    from .spectral.dataset import add_provenance

    if not HAS_SCIPY:
        raise ImportError("SciPy is required for Savitzky-Golay smoothing")

    if window_size % 2 == 0:
        window_size += 1

    data = dataset.data.copy()
    if data.ndim == 1:
        smoothed = scipy_savgol(data, window_size, polyorder)
    else:
        smoothed = np.apply_along_axis(lambda x: scipy_savgol(x, window_size, polyorder), axis=-1, arr=data)

    result = scp.NDDataset(smoothed)

    # Preserve coordinates and metadata
    if hasattr(dataset, "x") and dataset.x is not None:
        result.x = dataset.x.copy()
    if hasattr(dataset, "y") and dataset.y is not None:
        result.y = dataset.y.copy()
    if hasattr(dataset, "units") and dataset.units:
        result.units = dataset.units
    if hasattr(dataset, "title"):
        result.title = dataset.title
    if hasattr(dataset, "meta") and dataset.meta:
        result.meta.update(dict(dataset.meta))

    add_provenance(result, "smooth_savgol", {"window_size": window_size, "polyorder": polyorder})

    return result


# ─────────────────────────────────────────────────────────────────────────────
# RANGE CLIPPING
# ─────────────────────────────────────────────────────────────────────────────


def clip_range(
    dataset: "NDDataset",
    min_wavenumber: Optional[float] = None,
    max_wavenumber: Optional[float] = None,
) -> "NDDataset":
    """
    Clip dataset to specified wavenumber range.

    Parameters
    ----------
    dataset : NDDataset
        Input dataset
    min_wavenumber : float, optional
        Minimum wavenumber (inclusive)
    max_wavenumber : float, optional
        Maximum wavenumber (inclusive)

    Returns
    -------
    NDDataset
        Clipped dataset
    """
    from spectra_sherpa.app.lib.scp_compat import require_scp, scp

    require_scp("Spectral preprocessing")
    from .spectral.dataset import add_provenance

    wavenumber = dataset.x.data if hasattr(dataset.x, "data") else np.array(dataset.x)

    # Build mask
    mask = np.ones(len(wavenumber), dtype=bool)
    if min_wavenumber is not None:
        mask &= wavenumber >= min_wavenumber
    if max_wavenumber is not None:
        mask &= wavenumber <= max_wavenumber

    if not np.any(mask):
        raise ValueError("Clipping range excludes all wavenumbers")

    # Apply mask
    new_wn = wavenumber[mask]
    data = dataset.data
    if data.ndim == 1:
        new_data = data[mask]
    else:
        new_data = data[:, mask]

    result = scp.NDDataset(new_data)
    result.x = scp.Coord(new_wn, title="Wavenumber", units="cm^-1")

    if hasattr(dataset, "y") and dataset.y is not None:
        result.y = dataset.y.copy()
    if hasattr(dataset, "units") and dataset.units:
        result.units = dataset.units
    if hasattr(dataset, "title"):
        result.title = dataset.title
    if hasattr(dataset, "meta") and dataset.meta:
        result.meta.update(dict(dataset.meta))

    add_provenance(
        result,
        "clip_range",
        {"min_wavenumber": min_wavenumber, "max_wavenumber": max_wavenumber},
    )

    return result


# ─────────────────────────────────────────────────────────────────────────────
# PIPELINE
# ─────────────────────────────────────────────────────────────────────────────


def preprocess_pipeline(
    datasets: List["NDDataset"],
    settings: PreprocessingSettings,
) -> Tuple[List["NDDataset"], np.ndarray]:
    """
    Apply full preprocessing pipeline to a list of datasets.

    Parameters
    ----------
    datasets : list[NDDataset]
        Input datasets
    settings : PreprocessingSettings
        Preprocessing configuration

    Returns
    -------
    processed : list[NDDataset]
        Preprocessed datasets
    golden_grid : np.ndarray
        Common wavenumber grid (if alignment was applied)
    """
    processed = list(datasets)
    golden_grid = None

    # 1. Build golden grid and align
    if settings.align_wavenumbers and len(processed) > 1:
        golden_grid = build_golden_grid(processed, settings.merge_tolerance)
        processed = [interpolate_to_grid(ds, golden_grid, method=settings.alignment_method) for ds in processed]

    # 2. Cosmic ray removal
    if settings.remove_cosmic_rays:
        processed = [remove_cosmic_rays(ds, settings.cosmic_ray_window, settings.cosmic_ray_zscore) for ds in processed]

    # 3. Smoothing
    if settings.apply_smoothing:
        processed = [smooth_savgol(ds, settings.smoothing_window, settings.smoothing_polyorder) for ds in processed]

    # 4. Range clipping
    if settings.clip_range:
        processed = [clip_range(ds, settings.min_wavenumber, settings.max_wavenumber) for ds in processed]

    if golden_grid is None and processed:
        golden_grid = processed[0].x.data

    return processed, golden_grid


# ─────────────────────────────────────────────────────────────────────────────
# PENALIZED LEAST SQUARES BASELINES
# ─────────────────────────────────────────────────────────────────────────────


def _diff_matrix(n: int, d: int = 2) -> "sparse.csc_matrix":
    """Build sparse d-th order difference matrix (n-d × n)."""
    if not HAS_SCIPY:
        raise ImportError("SciPy is required for penalized least squares methods")
    D = sparse.eye(n, format="csc")
    for _ in range(d):
        m = D.shape[0]
        D = sparse.diags([-np.ones(m - 1), np.ones(m - 1)], [0, 1], shape=(m - 1, m), format="csc") @ D
    return D


def baseline_als(
    y: np.ndarray,
    lam: float = 1e5,
    p: float = 0.001,
    max_iter: int = 50,
    tol: float = 1e-6,
) -> np.ndarray:
    """
    Asymmetric Least Squares baseline estimation (Eilers 2005).

    Solves: (W + λ D'D) z = W y, with asymmetric weights.

    Parameters
    ----------
    y : np.ndarray
        1-D spectrum (n_features,)
    lam : float
        Smoothness penalty (larger = smoother baseline)
    p : float
        Asymmetry weight (0 < p < 1; smaller = more asymmetric)
    max_iter : int
        Maximum iterations
    tol : float
        Convergence tolerance on weight change

    Returns
    -------
    np.ndarray
        Estimated baseline, same shape as y
    """
    n = len(y)
    D = _diff_matrix(n, d=2)
    DTD = lam * D.T @ D
    w = np.ones(n)
    z = np.zeros(n)

    for _ in range(max_iter):
        W = sparse.diags(w, format="csc")
        z_new = sparse.linalg.spsolve(W + DTD, w * y)
        w_new = np.where(y > z_new, p, 1 - p)
        if np.linalg.norm(w_new - w) / (np.linalg.norm(w) + 1e-12) < tol:
            return z_new
        w = w_new
        z = z_new

    return z


def baseline_arpls(
    y: np.ndarray,
    lam: float = 1e5,
    max_iter: int = 50,
    tol: float = 1e-6,
) -> np.ndarray:
    """
    Asymmetrically Reweighted Penalized Least Squares (Baek et al. 2015).

    Adaptive weighting based on negative residual statistics.

    Parameters
    ----------
    y : np.ndarray
        1-D spectrum (n_features,)
    lam : float
        Smoothness penalty
    max_iter : int
        Maximum iterations
    tol : float
        Convergence tolerance on weight change

    Returns
    -------
    np.ndarray
        Estimated baseline
    """
    n = len(y)
    D = _diff_matrix(n, d=2)
    DTD = lam * D.T @ D
    w = np.ones(n)

    for _ in range(max_iter):
        W = sparse.diags(w, format="csc")
        z = sparse.linalg.spsolve(W + DTD, w * y)
        d = y - z
        d_neg = d[d < 0]
        if d_neg.size == 0:
            break
        m = d_neg.mean()
        s = d_neg.std(ddof=1) if d_neg.size > 1 else 1.0
        if s < 1e-12:
            break
        exponent = 2.0 * (d - (2.0 * s - m)) / s
        exponent = np.clip(exponent, -709, 709)  # prevent overflow in exp()
        w_new = 1.0 / (1.0 + np.exp(exponent))
        if np.linalg.norm(w_new - w) / (np.linalg.norm(w) + 1e-12) < tol:
            return z
        w = w_new

    return z


def baseline_airpls(
    y: np.ndarray,
    lam: float = 1e5,
    max_iter: int = 50,
    tol: float = 0.001,
) -> np.ndarray:
    """
    Adaptive Iteratively Reweighted Penalized Least Squares (Zhang et al. 2010).

    Parameters
    ----------
    y : np.ndarray
        1-D spectrum (n_features,)
    lam : float
        Smoothness penalty
    max_iter : int
        Maximum iterations
    tol : float
        Convergence ratio (sum of negative residuals / sum of abs(y))

    Returns
    -------
    np.ndarray
        Estimated baseline
    """
    n = len(y)
    D = _diff_matrix(n, d=2)
    DTD = lam * D.T @ D
    w = np.ones(n)
    y_abs_sum = np.abs(y).sum()
    if y_abs_sum < 1e-12:
        return np.zeros(n)

    for iteration in range(1, max_iter + 1):
        W = sparse.diags(w, format="csc")
        z = sparse.linalg.spsolve(W + DTD, w * y)
        d = y - z
        sum_neg = np.abs(d[d < 0]).sum()
        if sum_neg < tol * y_abs_sum:
            break
        # Adaptive weights: zero out positive residuals, exponential for negative
        w = np.zeros(n)
        neg_mask = d < 0
        if neg_mask.any() and sum_neg > 1e-12:
            w[neg_mask] = np.exp(iteration * np.abs(d[neg_mask]) / sum_neg)
            # Boundary points: use the largest absolute negative residual
            w[0] = np.exp(iteration * np.abs(d[neg_mask]).max() / sum_neg)
            w[-1] = w[0]

    return z


def baseline_penalized_ls(
    data: np.ndarray,
    method: str = "als",
    lam: float = 1e5,
    p: float = 0.001,
    max_iter: int = 50,
    tol: float = 1e-6,
) -> np.ndarray:
    """
    Unified penalized least squares baseline correction.

    Dispatches to ALS, ArPLS, or AirPLS based on method parameter.
    Operates on 2-D data (n_samples × n_features) and returns
    baseline-corrected spectra.

    Parameters
    ----------
    data : np.ndarray
        2-D array (n_samples × n_features) or 1-D spectrum
    method : str
        One of "als", "arpls", "airpls"
    lam : float
        Smoothness penalty
    p : float
        Asymmetry parameter (only used for ALS)
    max_iter : int
        Maximum iterations
    tol : float
        Convergence tolerance

    Returns
    -------
    np.ndarray
        Baseline-corrected spectra, same shape as input
    """
    if data.ndim == 1:
        data = data.reshape(1, -1)
        was_1d = True
    else:
        was_1d = False

    funcs = {"als": baseline_als, "arpls": baseline_arpls, "airpls": baseline_airpls}
    if method not in funcs:
        raise ValueError(f"method must be one of {list(funcs.keys())}, got '{method}'")

    func = funcs[method]
    kwargs = {"lam": lam, "max_iter": max_iter, "tol": tol}
    if method == "als":
        kwargs["p"] = p

    n_samples = data.shape[0]
    if HAS_JOBLIB and n_samples >= _get_parallel_threshold():
        baselines = Parallel(n_jobs=-2, prefer="threads")(delayed(func)(data[i], **kwargs) for i in range(n_samples))
        corrected = data - np.array(baselines)
    else:
        corrected = np.empty_like(data)
        for i in range(n_samples):
            corrected[i] = data[i] - func(data[i], **kwargs)

    return corrected[0] if was_1d else corrected


# ─────────────────────────────────────────────────────────────────────────────
# WHITTAKER SMOOTHER
# ─────────────────────────────────────────────────────────────────────────────


def whittaker_smooth(
    data: np.ndarray,
    lam: float = 1e2,
    d: int = 2,
) -> np.ndarray:
    """
    Whittaker smoother (Eilers 2003).

    Minimises ||y - z||² + λ ||D^d z||² where D is the d-th difference matrix.

    Parameters
    ----------
    data : np.ndarray
        1-D or 2-D array (n_samples × n_features)
    lam : float
        Smoothness penalty (larger = smoother)
    d : int
        Difference order (2 is most common)

    Returns
    -------
    np.ndarray
        Smoothed data, same shape as input
    """
    if not HAS_SCIPY:
        raise ImportError("SciPy is required for Whittaker smoothing")

    if data.ndim == 1:
        data = data.reshape(1, -1)
        was_1d = True
    else:
        was_1d = False

    n_features = data.shape[1]
    D = _diff_matrix(n_features, d=d)
    A = sparse.eye(n_features, format="csc") + lam * D.T @ D

    n_samples = data.shape[0]
    if HAS_JOBLIB and n_samples >= _get_parallel_threshold():
        rows = Parallel(n_jobs=-2, prefer="threads")(
            delayed(sparse.linalg.spsolve)(A, data[i]) for i in range(n_samples)
        )
        smoothed = np.array(rows)
    else:
        smoothed = np.empty_like(data)
        for i in range(n_samples):
            smoothed[i] = sparse.linalg.spsolve(A, data[i])

    return smoothed[0] if was_1d else smoothed


# ─────────────────────────────────────────────────────────────────────────────
# NORRIS-WILLIAMS DERIVATIVE
# ─────────────────────────────────────────────────────────────────────────────


def norris_williams(
    data: np.ndarray,
    gap: int = 5,
    segment: int = 5,
    deriv: int = 1,
) -> np.ndarray:
    """
    Norris-Williams gap-segment derivative.

    For each point i:
        d(i) = mean(y[i+gap : i+gap+segment]) - mean(y[i-gap-segment+1 : i-gap+1])

    Parameters
    ----------
    data : np.ndarray
        1-D or 2-D array (n_samples × n_features)
    gap : int
        Gap size (number of points between segments)
    segment : int
        Segment size (number of points to average)
    deriv : int
        Derivative order (1 or 2)

    Returns
    -------
    np.ndarray
        Derivative data, same shape as input (edges zero-padded)
    """
    if data.ndim == 1:
        data = data.reshape(1, -1)
        was_1d = True
    else:
        was_1d = False

    n_samples, n_features = data.shape

    def _first_deriv(y):
        result = np.zeros(n_features)
        for i in range(gap + segment - 1, n_features - gap - segment + 1):
            left_start = i - gap - segment + 1
            left_end = i - gap + 1
            right_start = i + gap
            right_end = i + gap + segment
            result[i] = np.mean(y[right_start:right_end]) - np.mean(y[left_start:left_end])
        return result

    def _compute_row(row):
        d1 = _first_deriv(row)
        if deriv == 1:
            return d1
        elif deriv == 2:
            return _first_deriv(d1)
        else:
            raise ValueError(f"deriv must be 1 or 2, got {deriv}")

    if HAS_JOBLIB and n_samples >= _get_parallel_threshold():
        rows = Parallel(n_jobs=-2, prefer="threads")(delayed(_compute_row)(data[i]) for i in range(n_samples))
        output = np.array(rows)
    else:
        output = np.empty_like(data)
        for i in range(n_samples):
            output[i] = _compute_row(data[i])

    return output[0] if was_1d else output


# ─────────────────────────────────────────────────────────────────────────────
# GAUSSIAN SMOOTHING
# ─────────────────────────────────────────────────────────────────────────────


def gaussian_smooth(
    data: np.ndarray,
    sigma: float = 2.0,
) -> np.ndarray:
    """
    Gaussian smoothing using scipy.ndimage.gaussian_filter1d.

    Parameters
    ----------
    data : np.ndarray
        1-D or 2-D array (n_samples × n_features)
    sigma : float
        Standard deviation of the Gaussian kernel

    Returns
    -------
    np.ndarray
        Smoothed data, same shape as input
    """
    if not HAS_SCIPY:
        raise ImportError("SciPy is required for Gaussian smoothing")

    if data.ndim == 1:
        return scipy_gaussian_filter1d(data, sigma=sigma)

    if HAS_JOBLIB and data.shape[0] >= _get_parallel_threshold():
        rows = Parallel(n_jobs=-2, prefer="threads")(
            delayed(scipy_gaussian_filter1d)(data[i], sigma=sigma) for i in range(data.shape[0])
        )
        return np.array(rows)

    return np.apply_along_axis(scipy_gaussian_filter1d, -1, data, sigma=sigma)


__all__ = [
    "PreprocessingSettings",
    "build_golden_grid",
    "interpolate_to_grid",
    "remove_cosmic_rays",
    "smooth_savgol",
    "clip_range",
    "preprocess_pipeline",
    "baseline_als",
    "baseline_arpls",
    "baseline_airpls",
    "baseline_penalized_ls",
    "whittaker_smooth",
    "norris_williams",
    "gaussian_smooth",
]
