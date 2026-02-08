"""
Multi-species spectral blending with calibration models.

PRESERVED FROM project0/blend.py - DO NOT MODIFY formulas without scientific review.

Copyright (c) 2025 Spectra Scientific LLC
All rights reserved.

Core Algorithm:
    For a mixture of N species, total absorbance at wavenumber ν and time t:

    A_total(ν, t) = Σᵢ₌₁ᴺ Aᵢ(ν, Cᵢ(t))

    Where Aᵢ(ν, Cᵢ) is computed using:
    - Linear model: A = α(ν) × C + β(ν)
    - Saturation model: A = s · [tanh((c·C/s)^p)]^(1/p)
    - Hybrid model: Per-wavenumber selection of above
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    from spectrochempy import NDDataset


# ═══════════════════════════════════════════════════════════════════════════════
# PHYSICAL CONSTANTS
# ═══════════════════════════════════════════════════════════════════════════════

SAFE_MIN_THRESHOLD = 1.8
"""
Conservative upper bound for linear model absorbance (AU).

This threshold prevents linear extrapolation from producing unphysical values
when no saturation model is available. The value of 1.8 AU is based on typical
FTIR detector linearity limits (most detectors are linear up to ~2 AU).

When a saturation model exists at the same wavenumber, the effective clipping
threshold is max(SAFE_MIN_THRESHOLD, s_saturation) to ensure conservative bounds.
"""


# ═══════════════════════════════════════════════════════════════════════════════
# NUMERICAL CORE - CALIBRATION MODELS
# Exact preservation from project0/blend.py
# ═══════════════════════════════════════════════════════════════════════════════


def eval_linear_model(
    concentrations: np.ndarray,
    slope: np.ndarray,
    intercept: np.ndarray,
    s: Optional[np.ndarray] = None,
) -> np.ndarray:
    """
    Evaluate linear calibration model with saturation capping: A = clip(slope × C + intercept, 0, s)

    The linear model is physically capped at [0, s] where s is the saturation plateau.
    This prevents the linear extrapolation from exceeding the physical saturation limit
    at high concentrations.

    Parameters
    ----------
    concentrations : np.ndarray
        Concentration values, shape: (n_times,) or scalar
    slope : np.ndarray
        Slope parameter (a.u./ppm), shape: (n_wavenumbers,)
    intercept : np.ndarray
        Intercept parameter (a.u.), shape: (n_wavenumbers,)
    s : Optional[np.ndarray]
        Saturation plateau level (a.u.), shape: (n_wavenumbers,).
        If provided, clips output to [0, s]. If None, only clips at 0.

    Returns
    -------
    absorbance : np.ndarray
        Absorbance values (a.u.), shape: (n_wavenumbers, n_times) or (n_wavenumbers,).
        Clipped to valid physical range [0, s].

    Notes
    -----
    **Physical Justification**:
    - Linear calibration: A = slope × C + intercept
    - Valid only in the linear regime (low to moderate concentrations)
    - At high concentrations, the system saturates at level `s`
    - Negative absorbance is non-physical and clipped to 0
    - The `s` value comes from the saturation model fit (same wavenumber)

    **Clipping Strategy**:
    - Lower bound: 0 (no negative absorbance)
    - Upper bound: s (saturation plateau from fitted model)
    - If s is None, no upper clipping (legacy behavior)

    Uses NumPy broadcasting for efficient vectorized computation.
    """
    # Ensure concentrations is at least 1D
    concentrations = np.atleast_1d(concentrations)

    # Broadcasting: (n_wn, 1) * (n_times,) + (n_wn, 1) = (n_wn, n_times)
    slope_col = slope[:, np.newaxis]
    intercept_col = intercept[:, np.newaxis]

    absorbance = slope_col * concentrations + intercept_col

    # Clip to physical range [0, s]
    absorbance = np.maximum(absorbance, 0.0)  # Lower bound: no negative absorbance

    if s is not None:
        s_col = s[:, np.newaxis]
        absorbance = np.minimum(absorbance, s_col)  # Upper bound: saturation cap

    return absorbance


def eval_saturation_model(
    concentrations: np.ndarray,
    s: np.ndarray,
    p: np.ndarray,
    c: np.ndarray,
) -> np.ndarray:
    """
    Evaluate saturation calibration model: A = s · [tanh((c·C/s)^p)]^(1/p)

    This model captures non-linear Beer-Lambert behavior at high concentrations
    due to detector saturation or self-absorption effects.

    Parameters
    ----------
    concentrations : np.ndarray
        Concentration values (ppm or ppm·m), shape: (n_times,) or scalar
    s : np.ndarray
        Saturation plateau level (a.u.), shape: (n_wavenumbers,)
    p : np.ndarray
        Shape exponent (dimensionless), shape: (n_wavenumbers,)
    c : np.ndarray
        Sensitivity parameter (a.u./ppm), shape: (n_wavenumbers,)

    Returns
    -------
    absorbance : np.ndarray
        Absorbance values (a.u.), shape: (n_wavenumbers, n_times) or (n_wavenumbers,)

    Notes
    -----
    - At low concentrations: A ≈ c·C (linear regime)
    - At high concentrations: A → s (saturation plateau)
    - Parameter p controls transition sharpness
    - Uses np.errstate to handle division edge cases gracefully

    References
    ----------
    See FORMULA_CONSISTENCY_ANALYSIS.md for mathematical derivation.
    """
    # Ensure concentrations is at least 1D
    concentrations = np.atleast_1d(concentrations)

    # CRITICAL VALIDATION: All saturation parameters must be positive
    # s, p, c ≤ 0 cause division by zero and meaningless physics
    if np.any(s <= 0):
        invalid_indices = np.where(s <= 0)[0]
        raise ValueError(
            f"Saturation parameter s must be > 0 at all wavenumbers. "
            f"Found s ≤ 0 at {len(invalid_indices)} wavenumbers (first: index {invalid_indices[0]}, s={s[invalid_indices[0]]})"
        )
    if np.any(p <= 0):
        invalid_indices = np.where(p <= 0)[0]
        raise ValueError(
            f"Saturation parameter p must be > 0 at all wavenumbers. "
            f"Found p ≤ 0 at {len(invalid_indices)} wavenumbers (first: index {invalid_indices[0]}, p={p[invalid_indices[0]]})"
        )
    if np.any(c <= 0):
        invalid_indices = np.where(c <= 0)[0]
        raise ValueError(
            f"Saturation parameter c must be > 0 at all wavenumbers. "
            f"Found c ≤ 0 at {len(invalid_indices)} wavenumbers (first: index {invalid_indices[0]}, c={c[invalid_indices[0]]})"
        )

    # Clip negative concentrations (non-physical)
    concentrations = np.maximum(concentrations, 0)

    # Reshape parameters for broadcasting: (n_wn, 1)
    s_col = s[:, np.newaxis]
    p_col = p[:, np.newaxis]
    c_col = c[:, np.newaxis]

    # No error suppression needed - parameters are validated above
    with np.errstate(divide="raise", invalid="raise"):
        # Standard formula: A = s · [tanh((c·C/s)^p)]^(1/p)
        # Step 1: Normalize concentration by saturation level
        normalized = (c_col * concentrations) / s_col

        # Step 2: Apply shape exponent
        powered = normalized ** p_col

        # Step 3: Apply hyperbolic tangent (bounded [0, 1])
        tanh_val = np.tanh(powered)

        # Step 4: Invert shape exponent and scale by saturation level
        absorbance = s_col * (tanh_val ** (1.0 / p_col))

    # Failsafe: catch any unexpected NaN/inf (should not occur with validation above)
    # If this triggers, there's a numerical issue in the calculation itself
    if np.any(~np.isfinite(absorbance)):
        print(
            f"WARNING: NaN/inf detected in saturation model output despite parameter validation"
        )
    absorbance = np.nan_to_num(absorbance, nan=0.0, posinf=0.0, neginf=0.0)

    return absorbance


def apply_system_saturation(
    absorbance: np.ndarray,
    s_system: float,
    p_system: float,
) -> np.ndarray:
    """
    Apply dimensionless system-level saturation after multi-species blending.

    Models detector saturation that occurs AFTER Beer's Law superposition:
    A_measured = s_system · [tanh((A_total / s_system)^p_system)]^(1/p_system)

    This represents intensity attenuation when the detector has insufficient
    dynamic range for the total absorbance.

    Parameters
    ----------
    absorbance : np.ndarray
        Total absorbance before system saturation (a.u.),
        shape: (n_wavenumbers, n_times)
    s_system : float
        System saturation plateau (a.u., dimensionless)
    p_system : float
        System saturation shape exponent (dimensionless)

    Returns
    -------
    saturated_absorbance : np.ndarray
        Absorbance after system saturation (a.u.),
        shape: (n_wavenumbers, n_times)

    Notes
    -----
    - If s_system ≤ 0 or p_system ≤ 0, returns input unchanged
    - System saturation is applied element-wise across the entire matrix
    - Unlike species-level saturation, this is dimensionless (no units)

    See Also
    --------
    eval_saturation_model : Species-level saturation with concentration units
    """
    if s_system <= 0 or p_system <= 0:
        return absorbance

    # Normalize by system saturation level
    normalized = absorbance / s_system

    # Apply saturation function with shape exponent
    # Step 1: Raise to power p_system
    powered = np.maximum(normalized, 0) ** p_system
    # Step 2: Apply tanh (bounded [0, 1])
    tanh_val = np.tanh(powered)
    # Step 3: Invert shape exponent (matches species saturation formula)
    saturated = tanh_val ** (1.0 / p_system)

    # Scale back by system saturation level
    return s_system * saturated


def select_hybrid_model(
    concentrations: np.ndarray,
    model_mask: np.ndarray,
    slope: np.ndarray,
    intercept: np.ndarray,
    s: np.ndarray,
    p: np.ndarray,
    c: np.ndarray,
) -> np.ndarray:
    """
    Per-wavenumber model selection between linear and saturation.

    This is the hybrid model that allows using different calibration
    models at different wavenumbers based on a selection mask.

    Parameters
    ----------
    concentrations : np.ndarray
        Concentration values, shape: (n_times,)
    model_mask : np.ndarray
        Boolean mask, True=saturation, False=linear, shape: (n_wavenumbers,)
    slope, intercept : np.ndarray
        Linear model parameters, shape: (n_wavenumbers,)
    s, p, c : np.ndarray
        Saturation model parameters, shape: (n_wavenumbers,)

    Returns
    -------
    absorbance : np.ndarray
        Blended absorbance, shape: (n_wavenumbers, n_times)
    """
    n_wn = len(model_mask)
    n_times = len(np.atleast_1d(concentrations))
    absorbance = np.zeros((n_wn, n_times))

    # Linear model indices
    linear_idx = ~model_mask
    if np.any(linear_idx):
        s_cap = np.where(
            (s[linear_idx] > 0),
            np.maximum(SAFE_MIN_THRESHOLD, s[linear_idx]),
            SAFE_MIN_THRESHOLD,
        )
        absorbance[linear_idx] = eval_linear_model(
            concentrations,
            slope[linear_idx],
            intercept[linear_idx],
            s=s_cap,
        )

    # Saturation model indices
    sat_idx = model_mask
    if np.any(sat_idx):
        # Only apply where parameters are valid
        valid_sat = sat_idx & (s > 0) & (p > 0) & (c > 0)
        if np.any(valid_sat):
            absorbance[valid_sat] = eval_saturation_model(
                concentrations,
                s[valid_sat],
                p[valid_sat],
                c[valid_sat],
            )

    return absorbance


# ═══════════════════════════════════════════════════════════════════════════════
# DATA CLASSES
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass
class BlendSettings:
    """Configuration for multi-species blending."""

    system_saturation_enabled: bool = False
    """Apply dimensionless system-level saturation after blending."""

    s_system: float = 1.0
    """System saturation plateau level (dimensionless)."""

    p_system: float = 1.0
    """System saturation shape exponent (dimensionless)."""

    clip_negative: bool = False
    """Clip negative absorbance values to zero."""


# ═══════════════════════════════════════════════════════════════════════════════
# NDDATASET-NATIVE BLENDING
# ═══════════════════════════════════════════════════════════════════════════════


def blend_datasets(
    species_datasets: List["NDDataset"],
    concentration_timeseries: Dict[str, np.ndarray],
    settings: BlendSettings,
    pathlength_m: Optional[float] = None,
) -> "NDDataset":
    """
    Blend multiple species according to concentration timeseries.

    This is the NDDataset-native version of project0's blend_species().
    Uses calibration models stored in dataset.meta["calibration"].

    Parameters
    ----------
    species_datasets : list[NDDataset]
        Pure component spectra with calibration metadata.
        Each dataset should have:
        - x: wavenumber axis
        - meta["calibration"]["model_type"]: "linear", "saturation", or "hybrid"
        - meta["calibration"]["slope"], ["intercept"]: for linear
        - meta["calibration"]["s"], ["p"], ["c"]: for saturation
    concentration_timeseries : dict[str, np.ndarray]
        {species_name: concentration_array} for each timepoint
    settings : BlendSettings
        System saturation and clipping options
    pathlength_m : float, optional
        Pathlength for unit conversion (ppm → ppm·m)

    Returns
    -------
    NDDataset
        Blended mixture with ground truth in meta["blend_ground_truth"]
    """
    import spectrochempy as scp
    from ..spectral.dataset import create_spectral_dataset, SpectralUnit

    if not species_datasets:
        raise ValueError("At least one species dataset is required")

    # Validate wavenumber alignment
    reference_wn = species_datasets[0].x.data
    n_wn = len(reference_wn)

    for ds in species_datasets[1:]:
        if not np.allclose(ds.x.data, reference_wn, atol=1e-6):
            raise ValueError(
                f"Species '{ds.title}' has misaligned wavenumber grid. "
                "Use preprocessing alignment first."
            )

    # Determine time axis from concentration timeseries
    times = None
    n_times = None

    for label, concentrations in concentration_timeseries.items():
        if times is None:
            n_times = len(concentrations)
            times = np.arange(n_times, dtype=float)
        elif len(concentrations) != n_times:
            raise ValueError(
                f"Concentration timeseries for '{label}' has {len(concentrations)} points, "
                f"but expected {n_times}."
            )

    if times is None or n_times == 0:
        raise ValueError("No concentration timeseries provided")

    # Initialize absorbance matrix
    absorbance_matrix = np.zeros((n_wn, n_times), dtype=float)

    # Build S matrix for ground truth
    S = np.zeros((n_wn, len(species_datasets)))
    C = np.zeros((n_times, len(species_datasets)))

    # Process each species
    import warnings

    for i, ds in enumerate(species_datasets):
        species_name = ds.title if ds.title else f"Species_{i}"

        if species_name not in concentration_timeseries:
            continue

        concentrations = concentration_timeseries[species_name]
        C[:, i] = concentrations

        # Check calibration range (if available)
        calib_meta = ds.meta.get("calibration", {})
        calib_range = calib_meta.get("calibration_range", {})
        if calib_range:
            min_conc = calib_range.get("min_concentration")
            max_conc = calib_range.get("max_concentration")
            if min_conc is not None and max_conc is not None:
                conc_min_actual = float(np.min(concentrations))
                conc_max_actual = float(np.max(concentrations))

                if conc_min_actual < min_conc:
                    pct_below = (min_conc - conc_min_actual) / min_conc * 100 if min_conc > 0 else 100
                    warnings.warn(
                        f"Species '{species_name}': concentration {conc_min_actual:.2f} is "
                        f"{pct_below:.1f}% below calibration minimum ({min_conc:.2f}). "
                        f"Extrapolation may be inaccurate.",
                        UserWarning,
                    )

                if conc_max_actual > max_conc:
                    pct_above = (conc_max_actual - max_conc) / max_conc * 100 if max_conc > 0 else 100
                    warnings.warn(
                        f"Species '{species_name}': concentration {conc_max_actual:.2f} is "
                        f"{pct_above:.1f}% above calibration maximum ({max_conc:.2f}). "
                        f"Extrapolation may be inaccurate, especially for saturation models.",
                        UserWarning,
                    )

        # Apply pathlength conversion if needed
        effective_conc = concentrations
        if pathlength_m is not None:
            # Check concentration mode from metadata
            calib = ds.meta.get("calibration", {})
            if calib.get("concentration_mode") == "product":
                effective_conc = concentrations * pathlength_m

        # Get calibration parameters
        calib = ds.meta.get("calibration", {})
        model_type = calib.get("model_type", "linear")

        # Store pure spectrum for ground truth
        if ds.ndim == 2:
            S[:, i] = np.mean(ds.data, axis=0)
        else:
            S[:, i] = ds.data

        # Evaluate calibration model
        if model_type == "linear":
            slope = np.array(calib.get("slope", np.ones(n_wn)))
            intercept = np.array(calib.get("intercept", np.zeros(n_wn)))
            s_cap = calib.get("s")
            if s_cap is not None:
                s_cap = np.array(s_cap)
                s_cap = np.where(s_cap > 0, np.maximum(SAFE_MIN_THRESHOLD, s_cap), SAFE_MIN_THRESHOLD)
            else:
                s_cap = np.full(n_wn, SAFE_MIN_THRESHOLD)

            A = eval_linear_model(effective_conc, slope, intercept, s=s_cap)
            absorbance_matrix += A

        elif model_type == "saturation":
            s = np.array(calib.get("s", np.ones(n_wn)))
            p = np.array(calib.get("p", np.ones(n_wn)))
            c = np.array(calib.get("c", np.ones(n_wn)))

            valid = (s > 0) & (p > 0) & (c > 0)
            if np.any(valid):
                A = np.zeros((n_wn, n_times))
                A[valid] = eval_saturation_model(effective_conc, s[valid], p[valid], c[valid])
                absorbance_matrix += A

        elif model_type == "hybrid":
            model_mask = np.array(calib.get("model_mask", np.zeros(n_wn, dtype=bool)))
            slope = np.array(calib.get("slope", np.zeros(n_wn)))
            intercept = np.array(calib.get("intercept", np.zeros(n_wn)))
            s = np.array(calib.get("s", np.zeros(n_wn)))
            p = np.array(calib.get("p", np.ones(n_wn)))
            c = np.array(calib.get("c", np.zeros(n_wn)))

            A = select_hybrid_model(effective_conc, model_mask, slope, intercept, s, p, c)
            absorbance_matrix += A

        else:
            # Raw/unknown - use Beer-Lambert approximation
            if ds.ndim == 2:
                spectrum = np.mean(ds.data, axis=0)
            else:
                spectrum = ds.data
            absorbance_matrix += spectrum[:, np.newaxis] * effective_conc

    # Apply system saturation if enabled
    if settings.system_saturation_enabled:
        absorbance_matrix = apply_system_saturation(
            absorbance_matrix,
            settings.s_system,
            settings.p_system,
        )

    # Clip negative values if requested
    if settings.clip_negative:
        absorbance_matrix = np.maximum(absorbance_matrix, 0.0)

    # Sort wavenumbers to ascending order for consistency
    if len(reference_wn) > 1 and reference_wn[0] > reference_wn[-1]:
        reference_wn = reference_wn[::-1].copy()
        absorbance_matrix = absorbance_matrix[::-1, :]

    # Create output dataset
    result = create_spectral_dataset(
        data=absorbance_matrix.T,  # (n_times, n_wn)
        wavenumbers=reference_wn,
        units=SpectralUnit.ABSORBANCE,
        title="Blended Mixture",
    )

    # Add ground truth metadata
    result.meta["blend_ground_truth"] = {
        "C_matrix": C.tolist(),
        "S_matrix": S.T.tolist(),  # (n_species, n_wn)
        "species_names": [ds.title for ds in species_datasets],
        "settings": {
            "system_saturation_enabled": settings.system_saturation_enabled,
            "s_system": settings.s_system,
            "p_system": settings.p_system,
            "clip_negative": settings.clip_negative,
        },
    }

    # Add time axis
    result.y = scp.Coord(times, title="Time", units="s")

    return result
