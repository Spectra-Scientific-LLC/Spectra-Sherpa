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
from spectra_sherpa.app.services.model_store import ModelArtifactIntegrityError, get_model_store

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
        category="regression",
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

    def generate_python(
        self,
        inputs: dict[str, str],
        indent: str = "    ",
        use_scp: bool = True,
    ) -> list[str]:
        """Generate Python export code for loading and applying a saved model.

        Emits code that loads a model artifact from disk and applies it.
        The user must provide the model artifact path.
        """
        X_expr = inputs.get("X_new", inputs.get("default", "input_data"))
        model_id = self.parameters.get("model_id", "")

        lines: list[str] = []
        lines.append(f"{indent}# --- Load & Apply Model ({self.node_id}) ---")
        lines.append(f"{indent}# >>> EDIT: provide path to model artifact directory <<<")
        lines.append(f"{indent}# Original model_id: {model_id!r}")
        lines.append(f"{indent}import json")
        lines.append(f"{indent}_model_dir = 'path/to/model/artifact'  # EDIT THIS")
        lines.append(f"{indent}from pathlib import Path as _Path")
        lines.append(f"{indent}_mdir = _Path(_model_dir)")
        lines.append(f"{indent}with open(_mdir / 'manifest.json') as _f:")
        lines.append(f"{indent}    _manifest = json.load(_f)")
        lines.append(f"{indent}_arrays = dict(np.load(_mdir / 'arrays.npz'))")
        lines.append(f"{indent}_model_type = _manifest.get('model_type', '')")

        # Extract X
        lines.append(f"{indent}_X_input = {X_expr}")
        lines.append(f"{indent}_X_data = np.array(")
        lines.append(f"{indent}    _X_input.data if hasattr(_X_input, 'data') else _X_input,")
        lines.append(f"{indent}    dtype=np.float64,")
        lines.append(f"{indent})")
        lines.append(f"{indent}if _X_data.ndim == 1:")
        lines.append(f"{indent}    _X_data = _X_data.reshape(1, -1)")

        # Dispatch by model type using Extract classes
        lines.append(f"{indent}_labels = None  # Only set for classification models")
        lines.append(f"{indent}if _model_type == 'pca':")
        lines.append(f"{indent}    _loadings = _arrays['loadings']")
        lines.append(f"{indent}    _mean = _arrays.get('mean')")
        lines.append(f"{indent}    _centered = _X_data - _mean if _mean is not None else _X_data")
        lines.append(f"{indent}    _result = _centered @ _loadings.T")
        lines.append(f"{indent}elif _model_type == 'pls':")
        lines.append(f"{indent}    _coef = _arrays['coef']")
        lines.append(f"{indent}    _x_mean = _arrays.get('x_mean', np.zeros(_X_data.shape[1]))")
        lines.append(f"{indent}    _y_mean = _arrays.get('y_mean', np.zeros(_coef.shape[1]))")
        lines.append(f"{indent}    _result = (_X_data - _x_mean) @ _coef + _y_mean")
        lines.append(f"{indent}elif _model_type in ('mcr', 'simplisma'):")
        lines.append(f"{indent}    _St = _arrays['St']")
        lines.append(f"{indent}    _result = _X_data @ np.linalg.pinv(_St)")
        lines.append(f"{indent}elif _model_type in ('plsda', 'knn', 'simca'):")
        lines.append(f"{indent}    # Classification: reconstruct extract and predict")
        lines.append(f"{indent}    from spectra_sherpa.app.lib.adapters.scp_extractors import (")
        lines.append(f"{indent}        EXTRACT_REGISTRY as _EXTRACT_REGISTRY,")
        lines.append(f"{indent}    )")
        lines.append(f"{indent}    _extract_cls = _EXTRACT_REGISTRY.get(_model_type)")
        lines.append(f"{indent}    if _extract_cls is None:")
        lines.append(f"{indent}        raise ValueError(f'No extract class for {{_model_type}}')")
        lines.append(f"{indent}    _extract = _extract_cls.from_artifact(_manifest, _arrays)")
        lines.append(f"{indent}    _labels, _probs = _extract.predict(_X_data)")
        lines.append(f"{indent}    _result = _probs")
        lines.append(f"{indent}else:")
        lines.append(f"{indent}    raise ValueError(f'Unsupported model type: {{_model_type}}')")

        lines.append(
            f'{indent}print(f"  Load & Apply ({{_model_type}}):'
            f" result={{_result.shape if hasattr(_result, 'shape')"
            f' else type(_result).__name__}}")'
        )
        lines.append(f"{indent}results['{self.node_id}'] = {{")
        lines.append(f"{indent}    'result': _result,")
        lines.append(f"{indent}    'labels': _labels,")
        lines.append(f"{indent}    'model_id': {model_id!r},")
        lines.append(f"{indent}}}")

        return lines

    async def execute(self, X_new: Any = None, model_ref: Any = None, **kwargs: Any) -> dict[str, Any]:
        # --- Resolve model_id ---
        model_id = self._resolve_model_id(model_ref)

        # --- Load artifact ---
        store = get_model_store()
        try:
            # verify=True (default): a corrupt/truncated npz raises
            # ModelArtifactIntegrityError rather than silently applying
            # wrong arrays to new data (audit DATA-3).
            manifest, arrays = store.load(model_id)
        except FileNotFoundError:
            raise ValueError(f"Model artifact '{model_id}' not found")
        except ModelArtifactIntegrityError as exc:
            raise ValueError(
                f"Model artifact '{model_id}' is corrupt and cannot be applied: {exc}. "
                "Re-train or re-import the model."
            ) from exc

        model_type = manifest.get("model_type", "")

        # --- Reject diagnostic-only models ---
        if model_type in _DIAGNOSTIC_TYPES:
            raise ValueError(f"{model_type.upper()} is diagnostic only — it cannot be applied to new data")

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

        # --- Apply feature mask before validating feature count ---
        # When a model was trained on selected features, it stores:
        #   - feature_mask: boolean mask over the full spectrum
        #   - selected_features: the actual axis values of selected features
        #   - n_features: count of *selected* features the model expects
        # We must apply the mask FIRST so n_features validation passes.
        selected_features = manifest.get("selected_features")
        feature_mask = manifest.get("feature_mask")
        if feature_mask is not None and isinstance(X_new, SherpaDataset):
            mask = np.asarray(feature_mask, dtype=bool)
            fa = getattr(X_new, "feature_axis", None)
            if fa is not None and fa.values is not None:
                actual_wn = np.asarray(fa.values, dtype=np.float64)
                # Apply mask only when new data is full-spectrum
                if len(mask) == len(actual_wn) and X_data.shape[1] == len(actual_wn):
                    X_data = X_data[:, mask]
                    logger.info(f"Applied saved feature mask: {len(actual_wn)} -> {X_data.shape[1]} features")

        # --- Validate feature count ---
        n_features = manifest.get("n_features")
        if n_features is not None and X_data.shape[1] != n_features:
            raise ValueError(f"Feature count mismatch: model expects {n_features} features, " f"got {X_data.shape[1]}")

        # --- Validate axis identity when selection was applied ---
        if selected_features is not None and isinstance(X_new, SherpaDataset):
            expected_wn = np.asarray(selected_features, dtype=np.float64)
            fa = getattr(X_new, "feature_axis", None)
            if fa is not None and fa.values is not None:
                actual_wn = np.asarray(fa.values, dtype=np.float64)
                # Compare masked axis values for non-contiguous selections
                if X_data.shape[1] == len(expected_wn):
                    if feature_mask is not None:
                        mask = np.asarray(feature_mask, dtype=bool)
                        if len(mask) == len(actual_wn):
                            compare_wn = actual_wn[mask]
                        else:
                            compare_wn = actual_wn[: len(expected_wn)]
                    else:
                        compare_wn = actual_wn[: len(expected_wn)]
                    if not np.allclose(compare_wn, expected_wn, atol=0.5):
                        logger.warning(
                            "Feature axis values differ from model training axis. "
                            f"Expected range [{expected_wn[0]:.1f}, {expected_wn[-1]:.1f}], "
                            f"got [{compare_wn[0]:.1f}, {compare_wn[-1]:.1f}]. "
                            "Predictions may be unreliable."
                        )

        # --- Reconstruct extract and apply ---
        extract = extract_cls.from_artifact(manifest, arrays)  # type: ignore[attr-defined]

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
                return str(model_ref["model_id"])

        # Fall back to parameter
        param_id = self.parameters.get("model_id", "")
        if param_id:
            return str(param_id)

        raise ValueError("No model specified — provide a model_id parameter or connect a model_ref input")
