"""Scikit-learn reference dataset catalog and metadata extraction."""

from __future__ import annotations

from typing import Any

import numpy as np

SKLEARN_CATALOG: dict[str, dict[str, Any]] = {
    "iris": {
        "label": "Iris (3 species, 4 features, 150 samples)",
        "task_type": "classification",
    },
    "wine": {
        "label": "Wine (3 classes, 13 features, 178 samples)",
        "task_type": "classification",
    },
    "breast_cancer": {
        "label": "Breast Cancer (2 classes, 30 features, 569 samples)",
        "task_type": "classification",
    },
    "digits": {
        "label": "Digits (10 classes, 64 features, 1797 samples)",
        "task_type": "classification",
    },
}

_LOADERS = {
    "iris": "load_iris",
    "wine": "load_wine",
    "breast_cancer": "load_breast_cancer",
    "digits": "load_digits",
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
        "technique": "ML/Statistics",
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
