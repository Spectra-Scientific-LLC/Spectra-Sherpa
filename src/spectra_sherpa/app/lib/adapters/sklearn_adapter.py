"""
Scikit-learn adapter for SherpaDataset.

Converts sklearn Bunch objects to SherpaDataset at system boundaries.
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


def from_sklearn(bunch: Any, name: str = "") -> SherpaDataset:
    """Convert an sklearn Bunch to SherpaDataset.

    Args:
        bunch: sklearn.utils.Bunch (e.g., from ``load_iris()``).
        name: Optional dataset name.

    Returns:
        SherpaDataset with X, feature-axis labels, target, and metadata.
    """
    X = np.asarray(bunch.data, dtype=np.float64)
    n_samples, n_features = X.shape

    feature_names = list(getattr(bunch, "feature_names", []))
    target_names = list(getattr(bunch, "target_names", []))

    spectral_axis = SpectralAxis(
        values=np.arange(n_features, dtype=np.float64),
        labels=feature_names or None,
        title="features",
    )

    sample_axis = SampleAxis(
        values=np.arange(n_samples, dtype=np.float64),
        title="samples",
    )

    target = None
    if hasattr(bunch, "target"):
        target = np.asarray(bunch.target)

    # Infer target context
    target_context = None
    if target is not None:
        n_unique = len(np.unique(target))
        if n_unique <= 30 and np.issubdtype(target.dtype, np.integer):
            target_context = TargetContext(
                target_type="categorical",
                target_name=name or None,
                n_classes=n_unique,
                class_names=target_names or None,
            )
        else:
            target_context = TargetContext(
                target_type="continuous",
                target_name=name or None,
            )

    extra = {}
    if target_names:
        extra["sklearn.target_names"] = target_names
    if name:
        extra["sklearn.dataset_name"] = name
    if hasattr(bunch, "DESCR"):
        extra["sklearn.description"] = bunch.DESCR[:500]  # truncate

    return SherpaDataset(
        X=X,
        spectral_axis=spectral_axis,
        sample_axis=sample_axis,
        target=target,
        target_context=target_context,
        domain=DomainContext(
            technique="generic",
            sample_type=name or None,
        ),
        backend="sklearn",
        title=name or None,
        extra=extra,
    )


# Alias for backward compat with existing import sites
from_sklearn_bunch = from_sklearn
