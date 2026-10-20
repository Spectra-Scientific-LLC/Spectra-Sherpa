"""Bounded, read-only explanations of an existing PCA fit; never an estimator."""

from __future__ import annotations

import hashlib
import json

import numpy as np

from spectra_sherpa.app.lib.sample_identity import sample_ids
from spectra_sherpa.app.services.dag.nodes.data.sample_preparation import _slice_dataset_rows
from spectra_sherpa.app.services.dag.nodes.modeling.pca_nodes import (
    apply_pca_fitted_state,
    pca_residual_matrix_in_fitted_space,
    validate_pca_fitted_state,
)

SCHEMA = "spectrasherpa-pca-explanations/1"
MAX_FEATURES = 20000
MAX_LOADING_CELLS = 100000
MAX_RECORDS = 60000
MAX_BYTES = 6 * 1024 * 1024
MAX_COMPONENTS = 64
MAX_WORK = 100_000_000


def _digest(value):
    return hashlib.sha256(json.dumps(value, separators=(",", ":"), ensure_ascii=True).encode()).hexdigest()


def _close(actual, expected, name):
    if not np.isfinite(actual).all() or not np.isfinite(expected).all():
        raise ValueError(f"Non-finite {name} evidence.")
    if not np.allclose(actual, expected, rtol=1e-7, atol=1e-12 * float(np.max(np.abs(expected)))):
        raise ValueError(f"Saved {name} does not match the fitted PCA state.")


def build_explanations(state, populations, rows, preprocessing):
    """populations contain exact PCA inputs paired with the saved/applied scores.

    Q_j = e_j²; signed additive T²_j = z_j [Pᵀ Λ⁻¹ t]_j.
    P is stored as components × features. All fitted components participate.
    Evaluate in small batches, retaining only bounded leading-variable records.
    """
    # Inspect only closed dimensions before validators allocate arrays and check
    # loading orthogonality. Sparse output alone does not bound that work.
    metadata, arrays = state["metadata"], state["arrays"]
    features, components = metadata["n_features"], metadata["n_components"]
    if (
        type(features) is not int
        or type(components) is not int
        or not 1 <= features <= MAX_FEATURES
        or not 1 <= components <= MAX_COMPONENTS
    ):
        raise ValueError("PCA explanations support up to 20,000 variables and 64 components.")
    matrix = arrays["loadings"]
    if (
        not isinstance(matrix, list)
        or len(matrix) != components
        or any(not isinstance(row, list) or len(row) != features for row in matrix)
    ):
        raise ValueError("PCA explanation loading dimensions are invalid.")
    for name, value in arrays.items():
        if (
            name != "loadings"
            and value is not None
            and (not isinstance(value, list) or len(value) > features + components)
        ):
            raise ValueError("PCA explanation state dimensions are invalid.")
    observations = sum(ds.shape[0] for ds, _ in populations)
    batches = sum((ds.shape[0] + 63) // 64 for ds, _ in populations)
    work = features * (observations * components + (1 + 5 * batches) * components**2)
    if work > MAX_WORK:
        raise ValueError("PCA explanations exceed the bounded calculation budget; sample review remains available.")
    normalized = validate_pca_fitted_state(state)
    metadata, arrays = normalized["metadata"], normalized["arrays"]
    features = int(metadata["n_features"])
    if features > MAX_FEATURES:
        raise ValueError(f"PCA explanations support at most {MAX_FEATURES:,} fitted variables.")
    loadings = np.asarray(arrays["loadings"], dtype=float)
    eigenvalues = np.asarray(arrays["explained_variance"], dtype=float)
    reference_ids = [r["id"] for r in rows if r["role"] == "calibration"]
    axis_identity = _digest(
        [
            metadata[k]
            for k in (
                "feature_axis_values_sha256",
                "feature_axis_labels_sha256",
                "feature_axis_units",
                "feature_axis_quantity",
            )
        ]
    )
    if sample_ids(populations[0][0]) != reference_ids:
        raise ValueError("PCA input does not preserve the fitted calibration observation order.")
    axis = populations[0][0].feature_axis
    if axis is not None and axis.labels is not None and sum(len(x) for x in axis.labels) > MAX_BYTES // 4:
        raise ValueError("PCA explanation feature labels exceed the evidence budget.")
    labels = list(axis.labels) if axis is not None and axis.labels is not None else None
    values = np.asarray(axis.values).tolist() if axis is not None and axis.values is not None else None
    count = min(20, max(1, MAX_RECORDS // (2 * len(rows))))
    expected = {r["id"]: r for r in rows}
    evidence = {}
    for dataset, saved_scores in populations:
        ids = sample_ids(dataset)
        if ids is None:
            raise ValueError("PCA explanations require typed sample_id values.")
        if len(set(ids)) != len(ids) or any(identity in evidence or identity not in expected for identity in ids):
            raise ValueError("PCA explanation observation identity is inconsistent.")
        saved_scores = np.asarray(saved_scores, dtype=float)
        for start in range(0, len(ids), 64):
            stop = min(start + 64, len(ids))
            subset = _slice_dataset_rows(dataset, dataset.X, np.arange(start, stop))
            scores = apply_pca_fitted_state(subset, normalized)
            _close(scores, saved_scores[start:stop], "scores")
            residual = pca_residual_matrix_in_fitted_space(subset, scores, normalized)
            # Reuse canonical fitted-space residual preprocessing, including its
            # full-rank and roundoff policy, rather than reinterpret scaling.
            centered = residual + scores @ loadings
            q = residual**2
            t2 = centered * ((scores / eigenvalues) @ loadings)
            for offset, identity in enumerate(ids[start:stop]):
                qr, tr = q[offset], t2[offset]
                q_total, t2_total = float(qr.sum()), float(tr.sum())
                _close(np.asarray(q_total), np.asarray(expected[identity]["q"]), "Q")
                _close(np.asarray(t2_total), np.asarray(expected[identity]["t2"]), "T²")
                # Stable ordering breaks equal contributions by fitted column index.
                leading = np.union1d(
                    np.argsort(-qr, kind="stable")[:count], np.argsort(-np.abs(tr), kind="stable")[:count]
                )
                omitted = np.ones(features, dtype=bool)
                omitted[leading] = False
                evidence[identity] = {
                    "variables": [[int(j), float(qr[j]), float(tr[j])] for j in leading],
                    "q_total": q_total,
                    "t2_total": t2_total,
                    "omitted_q": float(qr[omitted].sum()),
                    "omitted_t2": float(tr[omitted].sum()),
                    "omitted_t2_absolute": float(np.abs(tr[omitted]).sum()),
                }
    if set(evidence) != {r["id"] for r in rows if r["scores"] is not None}:
        raise ValueError("PCA explanation cohort is incomplete.")
    result = {
        "schema_version": SCHEMA,
        "model_digest": normalized["state_content_digest"],
        "source_contract_digest": normalized["source_contract_digest"],
        "feature_identity": axis_identity,
        "input_axis_identity": metadata["input_axis_identity_sha256"],
        "input_digests": [ds.scientific_digest for ds, _ in populations],
        "reference_digest": _digest(reference_ids),
        "reference_count": len(reference_ids),
        "reference": "Fitted calibration centroid; all retained components",
        "formula": "Q_j = e_j²; signed T²_j = z_j [Pᵀ Λ⁻¹ t]_j",
        "space": (
            "PCA "
            + (
                "standardized"
                if metadata["standardized"]
                else "min-max scaled and centered" if metadata["scaled"] else "mean-centered"
            )
            + " model space after workflow preprocessing"
        ),
        "preprocessing": preprocessing,
        "feature_count": features,
        "feature_labels": labels,
        "feature_values": values,
        "feature_units": metadata["feature_axis_units"] or "",
        "top_per_statistic": count,
        "loadings": loadings.tolist() if loadings.size <= MAX_LOADING_CELLS else None,
        "loadings_unavailable_reason": (
            "Full loadings exceed the 100,000 coefficient display budget."
            if loadings.size > MAX_LOADING_CELLS
            else None
        ),
        "rows": evidence,
    }
    if len(json.dumps(result, allow_nan=False).encode()) > MAX_BYTES:
        raise ValueError("PCA explanations exceed the 6 MiB evidence budget; sample review remains available.")
    return result
