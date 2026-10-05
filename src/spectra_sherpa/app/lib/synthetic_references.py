"""Synthetic reference datasets bundled with SpectraSherpa."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np

from spectra_sherpa.app.lib.eigenvector import build_catalog_preview
from spectra_sherpa.app.lib.sherpa_dataset import SherpaDataset

SYNTHETIC_DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "synthetic"

SYNTHETIC_REFERENCE_CATALOG: dict[str, dict[str, Any]] = {
    "Synthetic_atmospheric-6": {
        "label": "Synthetic_atmospheric-6",
        "filename": "Synthetic_atmospheric-6.npz",
        "technique": "FTIR",
        "description": (
            "Spectra Scientific synthetic FTIR gas-mixture benchmark derived from HITRAN spectra. "
            "Includes 50 mixture spectra plus ground-truth concentration profiles and pure signatures for "
            "MCR-ALS recovery and library-comparison stability checks."
        ),
        "featured": True,
        "x_title": "Wavenumber",
        "x_units": "cm^-1",
        "data_quantity": "Absorbance",
        "value_units": "absorbance",
        "target_type": "continuous",
        "expected_shape": (50, 5401),
        "expected_axis_range": (600.0, 3300.0),
        "target_fields": [
            "Carbon dioxide",
            "Carbon monoxide",
            "Water",
            "Methane",
            "Nitrous oxide",
            "Nitrogen dioxide",
        ],
    },
    "Library_atmospheric-9": {
        "label": "Library_atmospheric-9",
        "filename": "Library_atmospheric-9.npz",
        "technique": "FTIR",
        "description": (
            "HITRAN-derived component FTIR signatures as molar absorption coefficients for the Spectra Scientific "
            "atmospheric gas benchmark. "
            "Use this as the reference library for HQI and Compare vs. Library analysis."
        ),
        "featured": True,
        "x_title": "Wavenumber",
        "x_units": "cm^-1",
        "data_quantity": "Molar absorption coefficient",
        "value_units": "L mol^-1 cm^-1",
        "target_type": "continuous",
        "expected_shape": (9, 7199),
        "expected_axis_range": (400.002619, 3999.002619),
        "target_fields": [
            "Carbon dioxide",
            "Carbon monoxide",
            "Water",
            "Methane",
            "Nitrous oxide",
            "Nitrogen dioxide",
            "Ammonia",
            "Ozone",
            "Nitric oxide",
        ],
    },
    "msc_application_spectra": {
        "label": "MSC affine application spectra",
        "filename": "msc_application_spectra.csv",
        "technique": "FTIR",
        "description": (
            "Deterministic synthetic example. Six exact affine distortions of the MSC reference: "
            "row i = (i - 2) + (i + 1) * reference."
        ),
        "featured": False,
        "x_title": "Wavenumber",
        "x_units": "cm^-1",
        "data_quantity": "Absorbance",
        "value_units": "absorbance",
        "target_type": None,
        "expected_shape": (6, 8),
        "expected_axis_range": (1000.0, 1070.0),
        "target_fields": [],
    },
    "msc_reference_spectra": {
        "label": "MSC independent reference cohort",
        "filename": "msc_reference_spectra.csv",
        "technique": "FTIR",
        "description": (
            "Deterministic synthetic example. Three identical reference spectra [1, 2, 5, 10, 7, 4, 2, 1]; "
            "mean and median agree. MSC should recover this spectrum for every application row."
        ),
        "featured": False,
        "x_title": "Wavenumber",
        "x_units": "cm^-1",
        "data_quantity": "Absorbance",
        "value_units": "absorbance",
        "target_type": None,
        "expected_shape": (3, 8),
        "expected_axis_range": (1000.0, 1070.0),
        "target_fields": [],
    },
}


def synthetic_reference_path(name: str) -> Path:
    if name not in SYNTHETIC_REFERENCE_CATALOG:
        raise ValueError(f"Unknown synthetic reference dataset: {name}")
    return SYNTHETIC_DATA_DIR / str(SYNTHETIC_REFERENCE_CATALOG[name]["filename"])


def _optional_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def load_synthetic_reference_as_sherpa(name: str) -> SherpaDataset:
    """Load a catalog reference through the sole byte-ingestion authority.

    The catalog may supplement descriptive provenance, but it never reparses
    or reconstructs the numerical arrays, axes, targets, or fitted meaning.
    """
    from spectra_sherpa.app.lib.io import load_canonical_file_as_sherpa

    path = synthetic_reference_path(name)
    if not path.exists():
        raise FileNotFoundError(f"Synthetic reference dataset not found: {path.name}")
    dataset = load_canonical_file_as_sherpa(path)
    catalog = SYNTHETIC_REFERENCE_CATALOG[name]
    expected_shape = tuple(catalog["expected_shape"])
    if dataset.shape != expected_shape:
        raise ValueError(
            f"Synthetic reference {name} shape {dataset.shape} differs from its catalog contract " f"{expected_shape}"
        )
    axis = dataset.get_feature_axis()
    axis_values = None if axis is None or axis.values is None else np.asarray(axis.values, dtype=np.float64)
    expected_axis_range = tuple(catalog["expected_axis_range"])
    if (
        axis_values is None
        or axis_values.shape != (expected_shape[1],)
        or not np.allclose(
            [axis_values[0], axis_values[-1]],
            expected_axis_range,
            rtol=0.0,
            atol=1e-6,
        )
    ):
        raise ValueError(f"Synthetic reference {name} axis differs from its independent catalog contract")
    dataset.set_extra("synthetic.source", "synthetic_reference")
    dataset.set_extra("synthetic.reference_name", name)
    if dataset.domain.technique is None:
        dataset.domain.technique = _optional_text(catalog.get("technique"))
    return dataset


def get_synthetic_reference_info(name: str) -> dict[str, Any]:
    dataset = load_synthetic_reference_as_sherpa(name)
    catalog = SYNTHETIC_REFERENCE_CATALOG[name]
    X = np.asarray(dataset.X, dtype=float)
    axis = dataset.get_feature_axis()
    wavenumber = np.asarray(axis.values, dtype=float) if axis is not None and axis.values is not None else None
    target_context = dataset.target_context
    target_names = list(target_context.target_names or []) if target_context else []

    info: dict[str, Any] = {
        "name": name,
        "source": "synthetic",
        "label": catalog["label"],
        "technique": catalog["technique"],
        "is_spectra": True,
        "data_role": "X_spectra",
        "description": catalog["description"],
        "x_title": catalog.get("x_title"),
        "x_units": catalog.get("x_units"),
        "x_quantity": getattr(getattr(axis, "quantity", None), "value", getattr(axis, "quantity", None)),
        "data_quantity": catalog.get("data_quantity"),
        "n_samples": int(dataset.n_samples),
        "n_features": int(dataset.n_features),
        "target_names": target_names,
        "target_type": catalog.get("target_type"),
        "spectra_min": float(np.nanmin(X)),
        "spectra_max": float(np.nanmax(X)),
        "spectra_mean": float(np.nanmean(X)),
        "metadata": {
            "source": "synthetic_reference",
            "target_names": target_names,
            "value_units": dataset.units,
        },
    }
    if wavenumber is not None and wavenumber.size:
        info["wavenumber_min"] = float(wavenumber[0])
        info["wavenumber_max"] = float(wavenumber[-1])
        # Backward-compatible aliases for older clients/tests.  The synthetic
        # benchmark axis is wavenumber, not wavelength.
        info["wavelength_min"] = info["wavenumber_min"]
        info["wavelength_max"] = info["wavenumber_max"]
        if wavenumber.size > 1:
            info["wavenumber_step"] = float(np.median(np.diff(wavenumber)))
            info["wavelength_step"] = info["wavenumber_step"]
        preview = build_catalog_preview(X, wavenumber)
    else:
        preview = build_catalog_preview(X, None)
    if preview is not None:
        info["preview_spectra"] = preview["spectra"]
        if "wavelengths" in preview:
            info["wavelengths"] = preview["wavelengths"]
    return info
