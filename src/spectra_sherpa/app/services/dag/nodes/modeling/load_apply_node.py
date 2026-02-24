"""
Load & Apply Model node — generic model loading and inference.

Loads a persisted model artifact (manifest + arrays) and applies it to new data.
Works with all model types: PCA, PLS, MCR, SIMPLISMA, PLSDA, KNN, SIMCA.
"""

from __future__ import annotations

import logging
from typing import Any

import numpy as np

from spectra_sherpa.app.lib.adapters.scp_extractors import EXTRACT_REGISTRY
from spectra_sherpa.app.lib.sherpa_dataset import SherpaDataset
from spectra_sherpa.app.services.model_store import get_model_store

from ...node_base import (
    Node,
    NodeMetadata,
    NodeParameter,
    PortMetadata,
    register_node,
)

logger = logging.getLogger(__name__)

# Model types that support prediction (classification/regression)
_PREDICT_TYPES = {"pls", "plsda", "knn", "simca"}
# Model types that support transform (decomposition)
_TRANSFORM_TYPES = {"pca", "mcr", "simplisma"}
# Model types that are diagnostic only (no prediction/transform on new data)
_DIAGNOSTIC_TYPES = {"efa"}

# Map model types to their output category
_OUTPUT_TYPE_MAP = {
    "pca": "decomposition",
    "pls": "regression",
    "mcr": "decomposition",
    "simplisma": "decomposition",
    "plsda": "classification",
    "knn": "classification",
    "simca": "classification",
}


@register_node
class LoadApplyModelNode(Node):
    """
    Load a saved model artifact and apply it to new data.

    Resolves the model_id from either:
    1. The ``model_ref`` input port (from a training node's output) — takes priority
    2. The ``model_id`` parameter (user selection from saved models)

    For decomposition models (PCA, MCR, SIMPLISMA): calls ``transform(X)``.
    For regression models (PLS): calls ``predict(X)``.
    For classification models (PLSDA, KNN, SIMCA): calls ``predict(X)`` → labels + probabilities.
    EFA is diagnostic-only and raises an error.
    """

    metadata = NodeMetadata(
        node_type="model.load_apply",
        category="modeling",
        label="Load & Apply Model",
        description="Load a saved model artifact and apply it to new data",
        parameters=[
            NodeParameter(
                name="model_id",
                label="Model",
                param_type="model_select",
                description="Saved model to load and apply",
                required=False,
            ),
        ],
        input_ports=[
            PortMetadata(
                name="X_new",
                type_ref="spectrasherpa://types/SpectralDataset/1.0",
                required=True,
                label="New Data",
                description="Spectral data to apply the model to",
            ),
            PortMetadata(
                name="model_ref",
                type_ref="spectrasherpa://types/ModelReference/1.0",
                required=False,
                label="Model Reference",
                description="Model ID from training node (overrides parameter)",
            ),
        ],
        output_ports=[
            PortMetadata(
                name="result",
                type_ref="spectrasherpa://types/SpectralDataset/1.0",
                required=True,
                label="Result",
                description="Transformed or predicted output",
            ),
            PortMetadata(
                name="labels",
                type_ref="spectrasherpa://types/SpectralDataset/1.0",
                required=False,
                label="Labels",
                description="Predicted class labels (classification models only)",
            ),
            PortMetadata(
                name="model_id",
                type_ref="spectrasherpa://types/ModelReference/1.0",
                required=True,
                label="Model ID",
                description="Artifact UID of the loaded model (for provenance tracing)",
            ),
        ],
        input_types=["SpectralDataset"],
        output_type="varies",
    )

    async def execute(self, X_new: Any = None, model_ref: Any = None, **kwargs: Any) -> dict[str, Any]:
        # --- Resolve model_id ---
        model_id = self._resolve_model_id(model_ref)

        # --- Load artifact ---
        store = get_model_store()
        try:
            manifest, arrays = store.load(model_id)
        except FileNotFoundError:
            raise ValueError(f"Model artifact '{model_id}' not found")

        model_type = manifest.get("model_type", "")

        # --- Reject diagnostic-only models ---
        if model_type in _DIAGNOSTIC_TYPES:
            raise ValueError(
                f"{model_type.upper()} is diagnostic only — it cannot be applied to new data"
            )

        # --- Get extract class ---
        extract_cls = EXTRACT_REGISTRY.get(model_type)
        if extract_cls is None:
            raise ValueError(f"Unsupported model type: '{model_type}'")

        # --- Extract X_new as 2D float64 array ---
        if isinstance(X_new, SherpaDataset):
            X_data = np.asarray(X_new.data, dtype=np.float64)
        elif isinstance(X_new, np.ndarray):
            X_data = np.asarray(X_new, dtype=np.float64)
        elif hasattr(X_new, "data"):
            X_data = np.asarray(X_new.data, dtype=np.float64)
        else:
            raise ValueError("X_new must be a SherpaDataset or numpy array")

        if X_data.ndim == 1:
            X_data = X_data.reshape(1, -1)

        # --- Validate feature count ---
        n_features = manifest.get("n_features")
        if n_features is not None and X_data.shape[1] != n_features:
            raise ValueError(
                f"Feature count mismatch: model expects {n_features} features, "
                f"got {X_data.shape[1]}"
            )

        # --- Reconstruct extract and apply ---
        extract = extract_cls.from_artifact(manifest, arrays)

        result: dict[str, Any] = {"model_id": model_id}
        meta: dict[str, Any] = {
            "type": model_type.upper(),
            "output_type": _OUTPUT_TYPE_MAP.get(model_type, "unknown"),
        }

        if model_type in _TRANSFORM_TYPES:
            transformed = extract.transform(X_data)
            result["result"] = transformed

        elif model_type == "pls":
            predicted = extract.predict(X_data)
            result["result"] = predicted
            result["y_pred"] = predicted

        elif model_type in _PREDICT_TYPES:
            # Classification: predict returns (labels, probabilities)
            labels, probs = extract.predict(X_data)
            result["result"] = probs
            result["labels"] = list(labels)
            meta["classes"] = list(extract.classes)

        result["metadata"] = meta
        return result

    def _resolve_model_id(self, model_ref: Any) -> str:
        """Resolve model_id from port value or parameter, port takes priority."""
        # Port value takes priority
        if model_ref is not None:
            if isinstance(model_ref, str) and model_ref:
                return model_ref
            if isinstance(model_ref, dict) and model_ref.get("model_id"):
                return model_ref["model_id"]

        # Fall back to parameter
        param_id = self.parameters.get("model_id", "")
        if param_id:
            return param_id

        raise ValueError("No model specified — provide a model_id parameter or connect a model_ref input")
