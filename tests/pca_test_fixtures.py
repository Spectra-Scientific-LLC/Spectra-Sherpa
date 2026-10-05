"""SCP-independent closed PCA fixtures for consumer-boundary tests."""

from __future__ import annotations

import numpy as np

from spectra_sherpa.app.lib.pca import PCAExtract
from spectra_sherpa.app.lib.sherpa_dataset import SherpaDataset
from spectra_sherpa.app.services.dag.nodes.modeling.pca_nodes import (
    _pca_diagnostic_state,
    _pca_state_from_extract,
)
from spectra_sherpa.app.services.dag.rank_projection import input_axis_identity


def closed_pca_diagnostic_state(dataset: SherpaDataset, *, n_components: int) -> dict[str, object]:
    """Build a valid closed PCA diagnostic envelope without invoking a fit runtime."""

    matrix = np.asarray(dataset.X, dtype=np.float64)
    mean = np.mean(matrix, axis=0)
    centered = matrix - mean
    _, singular_values, right_vectors = np.linalg.svd(centered, full_matrices=False)
    all_eigenvalues = singular_values**2 / max(matrix.shape[0] - 1, 1)
    loadings = right_vectors[:n_components]
    scores = centered @ loadings.T
    eigenvalues = all_eigenvalues[:n_components]
    extract = PCAExtract(
        scores=scores,
        loadings=loadings,
        explained_variance_ratio=eigenvalues / np.sum(all_eigenvalues),
        explained_variance=eigenvalues,
        n_components=n_components,
        mean=mean,
    )
    state = _pca_state_from_extract(
        extract,
        dataset,
        input_shape=tuple(dataset.shape),
        input_axis_identity_sha256=input_axis_identity(dataset),
        rank_projection_strategy="none",
    )
    return _pca_diagnostic_state(
        model=state,
        scores=extract.scores,
        eigenvalues=extract.explained_variance,
        input_data=dataset,
    )
