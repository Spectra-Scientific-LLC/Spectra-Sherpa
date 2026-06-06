"""Shared utility for building _model_artifact dicts from Extract objects.

Training nodes call `build_model_artifact()` to construct the artifact dict
that the DAG executor persists via ModelStore.  This centralises feature_mask,
selected_features, and preprocessing_chain extraction so every training node
benefits from selection-aware artifact persistence.
"""

from __future__ import annotations

import logging
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)


def build_model_artifact(
    extract: Any,
    input_dataset: Any,
    *,
    node_id: str | None = None,
    metrics: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a ``_model_artifact`` dict ready for the executor.

    Args:
        extract: An Extract dataclass (PLSExtract, PCAExtract, etc.) with
            a ``to_artifact()`` method returning ``(metadata, arrays)``.
        input_dataset: The training input (SherpaDataset or NDDataset).
            Used to extract feature_axis, feature_mask, and preprocessing
            chain for the manifest.
        node_id: Optional node ID for provenance.
        metrics: Optional quality metrics dict (r2, rmse, etc.) to store
            in the manifest.

    Returns:
        Dict with keys ``metadata`` and ``arrays``, suitable for inclusion
        in a node's result dict as ``result["_model_artifact"]``.
    """
    metadata, arrays = extract.to_artifact()

    # --- Feature axis and selection mask ---
    _enrich_with_feature_info(metadata, input_dataset)

    # --- Preprocessing chain ---
    _enrich_with_preprocessing(metadata, input_dataset)

    # --- Training data identity ---
    _enrich_with_training_data_hash(metadata, input_dataset)

    # --- Metrics ---
    if metrics:
        metadata["metrics"] = metrics

    # --- Node provenance ---
    if node_id:
        metadata["node_id"] = node_id

    return {"metadata": metadata, "arrays": arrays}


def _enrich_with_feature_info(metadata: dict, dataset: Any) -> None:
    """Extract feature_axis values, feature_mask, and n_features."""
    from spectra_sherpa.app.lib.sherpa_dataset import SherpaDataset

    n_features: int | None = None

    if isinstance(dataset, SherpaDataset):
        if dataset.data is not None:
            n_features = dataset.data.shape[-1]

        fa = getattr(dataset, "feature_axis", None)
        if fa is not None:
            if getattr(fa, "units", None) is not None:
                metadata["feature_axis_units"] = fa.units
            if getattr(fa, "title", None) is not None:
                metadata["feature_axis_title"] = fa.title
            metadata["feature_axis_class"] = type(fa).__name__
            # Store full feature axis values for axis identity validation
            vals = getattr(fa, "values", None)
            if vals is not None:
                fa_arr = np.asarray(vals, dtype=np.float64)
                metadata["feature_axis"] = fa_arr.tolist()
                # If feature selection was applied, the current axis IS the
                # selected features (variable_select slices the dataset).
                metadata["selected_features"] = fa_arr.tolist()

        # Check for original feature mask — variable_select stores this in
        # the dataset's meta dict so load_apply can auto-slice full-spectrum data.
        original_mask = _extract_original_feature_mask(dataset)
        if original_mask is not None:
            metadata["feature_mask"] = original_mask.tolist()
    elif hasattr(dataset, "data"):
        data = getattr(dataset, "data", None)
        if data is not None:
            arr = np.asarray(data)
            if arr.ndim >= 2:
                n_features = arr.shape[-1]
    elif hasattr(dataset, "shape"):
        shape = dataset.shape
        if len(shape) >= 2:
            n_features = shape[-1]

    if n_features is not None:
        metadata["n_features"] = n_features


def _extract_original_feature_mask(dataset: Any) -> np.ndarray | None:
    """Try to find the original feature mask from provenance or metadata.

    When variable_select slices the dataset, the original boolean mask
    is recorded in the processing step parameters.
    """
    from spectra_sherpa.app.lib.sherpa_dataset import SherpaDataset

    if not isinstance(dataset, SherpaDataset):
        return None

    # Check provenance for variable selection steps
    try:
        history = dataset.provenance.to_list()
        for step in reversed(history):
            op_id = step.get("op_id", "")
            params = step.get("parameters", {})
            if "variable_select" in op_id or "selection" in op_id:
                n_total = params.get("n_total")
                n_selected = params.get("n_selected")
                if n_total and n_selected and n_total != n_selected:
                    # Selection was applied but we don't have the raw mask
                    # in provenance — it would be too large.
                    # The mask must come from the feature_axis metadata.
                    pass
    except Exception:
        pass

    # Check meta for stored mask
    meta = getattr(dataset, "meta", {})
    if isinstance(meta, dict):
        raw_mask = meta.get("feature_mask")
        if raw_mask is not None:
            return np.asarray(raw_mask, dtype=bool)

    return None


def _enrich_with_preprocessing(metadata: dict, dataset: Any) -> None:
    """Extract preprocessing chain from dataset provenance."""
    from spectra_sherpa.app.lib.sherpa_dataset import SherpaDataset

    chain: list[dict] = []

    if isinstance(dataset, SherpaDataset):
        try:
            history = dataset.provenance.to_list()
            for step in history:
                chain.append(
                    {
                        "op_id": step.get("op_id", "unknown"),
                        "parameters": step.get("parameters", {}),
                    }
                )
        except Exception:
            pass
    elif hasattr(dataset, "meta") and isinstance(getattr(dataset, "meta", None), dict):
        meta = dataset.meta
        raw_chain = meta.get("processing_history", [])
        if isinstance(raw_chain, list):
            chain = raw_chain

    if chain:
        metadata["preprocessing_chain"] = chain


def _enrich_with_training_data_hash(metadata: dict, dataset: Any) -> None:
    """Store a stable hash of the training matrix used by the model."""
    import hashlib

    data = None
    if hasattr(dataset, "X"):
        data = getattr(dataset, "X")
    elif hasattr(dataset, "data"):
        data = getattr(dataset, "data")
    elif isinstance(dataset, np.ndarray):
        data = dataset

    if data is None:
        return

    try:
        arr = np.asarray(data, dtype=np.float64)
        h = hashlib.sha256()
        h.update(str(arr.shape).encode("utf-8"))
        h.update(arr.tobytes(order="C"))
        metadata["training_data_hash"] = h.hexdigest()
    except Exception:
        logger.debug("Could not compute training_data_hash", exc_info=True)
