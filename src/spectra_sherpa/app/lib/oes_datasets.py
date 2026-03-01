"""OES (Optical Emission Spectroscopy) reference datasets.

Provides a catalog and loader for bundled OES data files.
The CSV format is *transposed*: rows = wavelength points, columns = samples.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

OES_DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "oes"

OES_CATALOG: dict[str, dict[str, Any]] = {
    "uvspectra10": {
        "label": "UV Spectra (120 samples, 2038 wavelengths, 190-416 nm)",
        "file": "UVSpectra10.csv",
        "technique": "OES",
        "x_title": "Wavelength",
        "x_units": "nm",
        "description": "UV/OES emission spectra — 120 measurements across 190-416 nm",
        "featured": True,
    },
}


def load_oes_dataset(
    name: str,
    data_dir: Path | None = None,
) -> dict[str, Any]:
    """Load an OES dataset by catalog name.

    The raw CSV is transposed (rows = wavelengths, cols = samples).
    This function reads it, transposes to (n_samples, n_wavelengths),
    and returns a dict matching the eigenvector loader contract.

    Returns:
        Dict with keys: spectra, wavelengths, properties, prop_names,
        sample_ids, catalog_entry.
    """
    if name not in OES_CATALOG:
        raise ValueError(f"Unknown OES dataset: {name}")

    catalog = OES_CATALOG[name]
    base_dir = data_dir or OES_DATA_DIR
    csv_path = base_dir / catalog["file"]

    if not csv_path.exists():
        raise FileNotFoundError(f"OES data file not found: {csv_path}")

    df = pd.read_csv(csv_path, header=None)

    # Column 0 = wavelengths, columns 1..N = sample intensities
    wavelengths = df.iloc[:, 0].values.astype(np.float64)
    intensities = df.iloc[:, 1:].values.astype(np.float64)

    # Transpose: (n_wavelengths, n_samples) -> (n_samples, n_wavelengths)
    spectra = intensities.T

    n_samples = spectra.shape[0]
    sample_ids = [f"Sample_{i + 1:03d}" for i in range(n_samples)]

    return {
        "spectra": spectra,
        "wavelengths": wavelengths,
        "properties": None,
        "prop_names": None,
        "sample_ids": sample_ids,
        "catalog_entry": catalog,
    }


def get_oes_dataset_info(
    name: str,
    data_dir: Path | None = None,
) -> dict[str, Any]:
    """Get full metadata + computed statistics for an OES dataset."""
    result = load_oes_dataset(name, data_dir=data_dir)
    catalog = result["catalog_entry"]
    spectra = result["spectra"]
    wavelengths = result["wavelengths"]

    info: dict[str, Any] = {
        "name": name,
        "source": "oes",
        "label": catalog["label"],
        "technique": catalog["technique"],
        "description": catalog["description"],
        "x_title": catalog["x_title"],
        "x_units": catalog["x_units"],
        "n_samples": spectra.shape[0],
        "n_features": spectra.shape[1],
        "spectra_min": float(np.nanmin(spectra)),
        "spectra_max": float(np.nanmax(spectra)),
        "spectra_mean": float(np.nanmean(spectra)),
    }

    if wavelengths is not None and len(wavelengths) > 1:
        info["wavelength_min"] = float(wavelengths.min())
        info["wavelength_max"] = float(wavelengths.max())
        info["wavelength_step"] = float(np.mean(np.diff(wavelengths)))

    return info
