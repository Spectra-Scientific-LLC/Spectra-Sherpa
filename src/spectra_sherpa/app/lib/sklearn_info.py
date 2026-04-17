"""Scikit-learn reference dataset catalog and metadata extraction."""

from __future__ import annotations

from typing import Any

import numpy as np

# NOTE: sklearn datasets are NOT spectroscopic data.  They are tabular
# morphological / clinical measurements and lack physical axis scales (no
# wavenumber, wavelength, or m/z axis).  Spectral preprocessing nodes
# (baseline correction, smoothing, normalisation, derivative) produce
# physically meaningless results on these datasets.  They are provided for
# algorithm exploration and workflow testing only.
_SKLEARN_NON_SPECTROSCOPIC_WARNING = (
    "⚠ This is a non-spectroscopic dataset (tabular measurements, no wavelength/wavenumber axis). "
    "Spectral preprocessing nodes (baseline correction, smoothing, derivatives, scatter correction) "
    "are not physically meaningful on this data. Suitable for testing classification and regression nodes only."
)

SKLEARN_CATALOG: dict[str, dict[str, Any]] = {
    "iris": {
        "label": "Iris — non-spectroscopic (3 species, 4 features, 150 samples)",
        "task_type": "classification",
        "is_spectra": False,
        "warning": _SKLEARN_NON_SPECTROSCOPIC_WARNING,
    },
    "wine": {
        "label": "Wine — non-spectroscopic (3 classes, 13 features, 178 samples)",
        "task_type": "classification",
        "is_spectra": False,
        "warning": _SKLEARN_NON_SPECTROSCOPIC_WARNING,
    },
    "breast_cancer": {
        "label": "Breast Cancer — non-spectroscopic (2 classes, 30 features, 569 samples)",
        "task_type": "classification",
        "is_spectra": False,
        "warning": _SKLEARN_NON_SPECTROSCOPIC_WARNING,
    },
}

_LOADERS = {
    "iris": "load_iris",
    "wine": "load_wine",
    "breast_cancer": "load_breast_cancer",
}


def get_sklearn_dataset_info(name: str) -> dict[str, Any]:
    """Extract rich metadata from a scikit-learn dataset."""
    if name not in SKLEARN_CATALOG:
        raise ValueError(f"Unknown sklearn dataset: {name!r}. " f"Available: {', '.join(SKLEARN_CATALOG)}")

    from sklearn import datasets

    loader = getattr(datasets, _LOADERS[name])
    bunch = loader()
    catalog = SKLEARN_CATALOG[name]

    return {
        "name": name,
        "source": "sklearn",
        "label": catalog["label"],
        "technique": "Non-spectroscopic (tabular)",
        "is_spectra": catalog.get("is_spectra", False),
        "warning": catalog.get("warning"),
        "description": bunch.DESCR,
        "task_type": catalog["task_type"],
        "n_samples": int(bunch.data.shape[0]),
        "n_features": int(bunch.data.shape[1]),
        "feature_names": list(getattr(bunch, "feature_names", [])),
        "target_names": [str(t) for t in bunch.target_names] if hasattr(bunch, "target_names") else [],
        "data_min": float(np.min(bunch.data)),
        "data_max": float(np.max(bunch.data)),
        "data_mean": float(np.mean(bunch.data)),
    }
