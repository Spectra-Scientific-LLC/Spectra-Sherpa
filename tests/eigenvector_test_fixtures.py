"""Generated Eigenvector-shaped fixtures for tests that execute source nodes.

These fixtures intentionally do not contain upstream Eigenvector Research data.
They preserve the dimensional contracts needed by workflow and export tests while
the application code exercises the runtime/local-download path for real data.
"""

from __future__ import annotations

from typing import Any

import numpy as np

from spectra_sherpa.app.lib.eigenvector import DATASET_CATALOG

_DIESEL_PROP_NAMES = ["BP50", "CN", "D4052", "FLASH", "FREEZE", "TOTAL", "VISC"]
_CORN_PROP_NAMES = ["Moisture", "Oil", "Protein", "Starch"]


def generated_eigenvector_result(name: str, data_dir: object | None = None) -> dict[str, Any]:
    """Return a deterministic Eigenvector-loader result without bundled raw data."""
    if name not in DATASET_CATALOG:
        raise ValueError(f"Unsupported Eigenvector dataset: {name}")

    catalog = DATASET_CATALOG[name]
    if name.startswith("corn_"):
        return _corn_result(name, catalog)
    if name.startswith("diesel_nir"):
        return _diesel_result(name, catalog)
    if name.startswith("nir_shootout"):
        return _nir_shootout_result(name, catalog)
    if name == "metal_etch_oes":
        return _matrix_result(name, catalog, n_samples=129, n_features=238, prop_names=None)
    if name == "cgl_nir":
        return _matrix_result(name, catalog, n_samples=155, n_features=600, prop_names=["Thickness"])
    if name in {"machine", "rfm"}:
        return _matrix_result(name, catalog, n_samples=120, n_features=256, prop_names=None)
    return _matrix_result(name, catalog, n_samples=64, n_features=128, prop_names=None)


def _base_spectra(n_samples: int, n_features: int, *, offset: float = 0.0) -> np.ndarray:
    sample = np.arange(n_samples, dtype=float)
    axis = np.linspace(0.0, 1.0, n_features)
    centers = np.array([0.16, 0.34, 0.58, 0.79])
    widths = np.array([0.035, 0.055, 0.045, 0.065])
    components = np.exp(-0.5 * ((axis[None, :] - centers[:, None]) / widths[:, None]) ** 2)
    trend = sample / max(n_samples - 1, 1)
    weights = np.column_stack(
        [
            0.45 + 0.20 * np.sin(sample / 9.0),
            0.35 + 0.25 * trend,
            0.40 + 0.18 * np.cos(sample / 11.0),
            0.30 + 0.16 * ((sample % 13) / 12.0),
        ]
    )
    baseline = 0.08 + offset + 0.03 * np.sin(2.0 * np.pi * axis)[None, :]
    sample_slope = (trend[:, None] - 0.5) * 0.04 * axis[None, :]
    spectra = baseline + weights @ components + sample_slope
    return spectra.astype(np.float64)


def _target_matrix(n_samples: int, names: list[str]) -> np.ndarray:
    sample = np.arange(n_samples, dtype=float)
    cols = []
    for idx, _ in enumerate(names):
        cols.append(1.0 + idx + sample * (0.01 + idx * 0.002) + np.sin(sample / (6.0 + idx)))
    return np.column_stack(cols).astype(np.float64)


def _result(
    name: str,
    catalog: dict[str, Any],
    spectra: np.ndarray,
    *,
    wavelengths: np.ndarray | None,
    prop_names: list[str] | None,
) -> dict[str, Any]:
    properties = _target_matrix(spectra.shape[0], prop_names) if prop_names else None
    return {
        "spectra": spectra,
        "properties": properties,
        "wavelengths": wavelengths,
        "sample_ids": [str(i + 1) for i in range(spectra.shape[0])],
        "prop_names": prop_names or [],
        "catalog_entry": catalog,
        "metadata": {"Description": f"Generated {name} test fixture"},
        "file_metadata": [
            {
                "filename": f"{name}.generated",
                "extension": ".generated",
                "source": "generated-test-fixture",
            }
        ],
    }


def _diesel_result(name: str, catalog: dict[str, Any]) -> dict[str, Any]:
    spectra = _base_spectra(784, 401)
    wavelengths = np.arange(750.0, 1552.0, 2.0, dtype=np.float64)
    return _result(name, catalog, spectra, wavelengths=wavelengths, prop_names=_DIESEL_PROP_NAMES)


def _corn_result(name: str, catalog: dict[str, Any]) -> dict[str, Any]:
    offset = {"corn_m5": 0.0, "corn_mp5": 0.02, "corn_mp6": 0.04}.get(name, 0.0)
    spectra = _base_spectra(80, 700, offset=offset)
    return _result(name, catalog, spectra, wavelengths=None, prop_names=_CORN_PROP_NAMES)


def _nir_shootout_result(name: str, catalog: dict[str, Any]) -> dict[str, Any]:
    n_samples = 120 if "cal" in name else 40
    spectra = _base_spectra(n_samples, 700)
    wavelengths = np.linspace(1100.0, 2500.0, spectra.shape[1], dtype=np.float64)
    return _result(name, catalog, spectra, wavelengths=wavelengths, prop_names=["Moisture", "Protein"])


def _matrix_result(
    name: str,
    catalog: dict[str, Any],
    *,
    n_samples: int,
    n_features: int,
    prop_names: list[str] | None,
) -> dict[str, Any]:
    spectra = _base_spectra(n_samples, n_features)
    wavelengths = np.arange(n_features, dtype=np.float64)
    return _result(name, catalog, spectra, wavelengths=wavelengths, prop_names=prop_names)
