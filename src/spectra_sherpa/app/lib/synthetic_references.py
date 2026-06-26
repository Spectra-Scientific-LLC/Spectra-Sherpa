"""Synthetic reference datasets bundled with SpectraSherpa."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np

from spectra_sherpa.app.lib.eigenvector import build_catalog_preview
from spectra_sherpa.app.lib.sherpa_dataset import DomainContext, SampleAxis, SherpaDataset, SpectralAxis, TargetContext
from spectra_sherpa.app.services.synthesis import load_synthetic_npz

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
    },
}


def synthetic_reference_path(name: str) -> Path:
    if name not in SYNTHETIC_REFERENCE_CATALOG:
        raise ValueError(f"Unknown synthetic reference dataset: {name}")
    return SYNTHETIC_DATA_DIR / str(SYNTHETIC_REFERENCE_CATALOG[name]["filename"])


def _read_json_field(data: dict[str, Any], key: str) -> dict[str, Any]:
    raw = data.get(key)
    if not raw:
        return {}
    try:
        parsed = json.loads(str(raw))
    except (TypeError, ValueError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _optional_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def load_synthetic_reference_dataset(name: str) -> dict[str, Any]:
    path = synthetic_reference_path(name)
    if not path.exists():
        raise FileNotFoundError(f"Synthetic reference dataset not found: {path.name}")
    data = load_synthetic_npz(path)
    data["catalog_entry"] = SYNTHETIC_REFERENCE_CATALOG[name]
    data["path"] = path
    return data


def load_synthetic_reference_as_sherpa(name: str) -> SherpaDataset:
    data = load_synthetic_reference_dataset(name)
    catalog = data["catalog_entry"]
    X = np.asarray(data["X"], dtype=float)
    wavenumber = np.asarray(data["wavenumber"], dtype=float)
    sample_labels = [str(label) for label in data.get("sample_labels", [])]
    C = np.asarray(data.get("C"), dtype=float)
    metadata = data.get("metadata") if isinstance(data.get("metadata"), dict) else {}
    ground_truth = _read_json_field(data, "ground_truth_json")
    target_names = ground_truth.get("component_names")
    if not isinstance(target_names, list) or not target_names:
        target_names = [f"component_{index + 1}" for index in range(C.shape[1] if C.ndim == 2 else 1)]
    target_names = [str(name) for name in target_names]
    S = np.asarray(data.get("S"), dtype=float)

    recipe = _read_json_field(data, "recipe_json")
    x_title = _optional_text(metadata.get("x_title")) or _optional_text(catalog.get("x_title"))
    x_units = (
        _optional_text(metadata.get("x_units"))
        or _optional_text(data.get("feature_units"))
        or _optional_text(catalog.get("x_units"))
    )
    value_units = (
        _optional_text(metadata.get("value_units"))
        or _optional_text(data.get("units"))
        or _optional_text(catalog.get("value_units"))
    )
    data_quantity = _optional_text(metadata.get("data_quantity")) or _optional_text(catalog.get("data_quantity"))
    extra: dict[str, Any] = {
        "source": "synthetic_reference",
        "reference_name": name,
        "recipe": recipe or None,
        "ground_truth.spectra": S.tolist() if S.ndim == 2 and S.size else None,
        "ground_truth.spectra_names": target_names,
        "ground_truth.spectra_units": ground_truth.get("S_units"),
        "ground_truth.spectra_x": wavenumber.tolist(),
        "ground_truth.spectra_x_title": x_title,
        "ground_truth.spectra_x_units": x_units,
        "component_ids": (
            ground_truth.get("component_ids") if isinstance(ground_truth.get("component_ids"), list) else None
        ),
    }

    return SherpaDataset(
        X=X,
        feature_axis=SpectralAxis(
            values=wavenumber,
            title=x_title,
            units=x_units,
        ),
        sample_axis=SampleAxis(
            labels=sample_labels if sample_labels else [f"sample_{index + 1}" for index in range(X.shape[0])],
            title=str(metadata.get("y_title") or "Sample"),
        ),
        target=C,
        target_context=TargetContext(
            target_type="continuous",
            target_name="synthetic concentration",
            target_names=target_names,
            target_units=_optional_text(data.get("concentration_units")),
        ),
        extra=extra,
        title=str(metadata.get("title") or catalog["label"]),
        units=value_units,
        domain=DomainContext(
            technique=_optional_text(metadata.get("spectral_technique")) or _optional_text(catalog.get("technique")),
            data_quantity=data_quantity,
        ),
        data_role=str(metadata.get("data_role") or "X_spectra"),
        is_time_series=bool(metadata.get("is_time_series", False)),
    )


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
