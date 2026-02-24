"""
Numpy adapter for SherpaDataset.

Converts raw numpy arrays to/from SherpaDataset at system boundaries.
"""

from __future__ import annotations

from typing import Any

import numpy as np

from spectra_sherpa.app.lib.sherpa_dataset import (
    DomainContext,
    SampleAxis,
    SherpaDataset,
    SpectralAxis,
    TargetContext,
)


def from_numpy(
    X: np.ndarray,
    *,
    wavenumbers: np.ndarray | None = None,
    wavelengths: np.ndarray | None = None,
    spectral_units: str | None = None,
    sample_labels: list[str] | None = None,
    target: np.ndarray | list | None = None,
    target_name: str | None = None,
    target_type: str | None = None,
    technique: str | None = None,
    title: str | None = None,
    units: str | None = None,
) -> SherpaDataset:
    """Create SherpaDataset from a numpy array.

    Args:
        X: 1D or 2D array (samples x features).
        wavenumbers: Spectral axis values (cm-1). Mutually exclusive with wavelengths.
        wavelengths: Spectral axis values (nm). Mutually exclusive with wavenumbers.
        spectral_units: Override units for spectral axis.
        sample_labels: Per-sample labels.
        target: Target/label vector.
        target_name: Name of the target variable.
        target_type: Type of the target: "continuous", "categorical", "ordinal".
        technique: Spectral technique (e.g., "IR", "NIR", "Raman").
        title: Dataset title.
        units: Data value units (e.g., "absorbance").
    """
    if wavenumbers is not None and wavelengths is not None:
        raise ValueError("Provide wavenumbers or wavelengths, not both")

    arr = np.asarray(X, dtype=np.float64)
    if arr.ndim == 0:
        raise ValueError("X must be at least 1-dimensional")
    if arr.ndim == 1:
        arr = arr.reshape(1, -1)
    X = arr

    feature_axis = None
    if wavenumbers is not None:
        feature_axis = SpectralAxis(
            values=np.asarray(wavenumbers, dtype=np.float64),
            units=spectral_units or "cm-1",
            title="wavenumber",
        )
    elif wavelengths is not None:
        feature_axis = SpectralAxis(
            values=np.asarray(wavelengths, dtype=np.float64),
            units=spectral_units or "nm",
            title="wavelength",
        )

    sample_axis = None
    if sample_labels is not None:
        sample_axis = SampleAxis(
            values=np.arange(X.shape[0], dtype=np.float64),
            labels=sample_labels,
            title="samples",
        )

    domain = None
    if technique:
        domain = DomainContext(technique=technique)

    target_context = None
    if target_name or target_type:
        target_context = TargetContext(
            target_name=target_name,
            target_type=target_type,
        )

    return SherpaDataset(
        X=X,
        feature_axis=feature_axis,
        sample_axis=sample_axis,
        target=target,
        target_context=target_context,
        domain=domain,
        backend="numpy",
        title=title,
        units=units,
    )


def to_numpy(ds: SherpaDataset) -> dict[str, Any]:
    """Extract numpy arrays from SherpaDataset.

    Returns:
        dict with keys: X, wavenumbers (optional), target (optional),
        sample_labels (optional).
    """
    result: dict[str, Any] = {"X": ds.X.copy()}

    sa = ds.feature_axis
    if sa and sa.values is not None:
        axis_type = sa.axis_type
        if axis_type == "wavenumber":
            result["wavenumbers"] = sa.values.copy()
        elif axis_type and axis_type.startswith("wavelength"):
            result["wavelengths"] = sa.values.copy()
        else:
            result["spectral_values"] = sa.values.copy()
        if sa.units:
            result["spectral_units"] = sa.units

    if ds.target is not None:
        result["target"] = ds.target.copy()

    sam = ds.sample_axis
    if sam and sam.labels:
        result["sample_labels"] = list(sam.labels)

    return result
