"""
Apply Saved Model Artifact node — generic model-artifact loading and inference.

Loads a persisted model artifact (manifest + arrays) and applies it to inference data.
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
_PREDICT_TYPES = {"pls", "pcr", "linear_regression", "svr", "plsda", "knn", "simca"}
# Model types that support transform (decomposition)
_TRANSFORM_TYPES = {"pca", "mcr", "simplisma", "nmf", "fastica"}
# Model types that are diagnostic only (no prediction/transform on new data)
_DIAGNOSTIC_TYPES = {"efa"}

# Map model types to their output category
_OUTPUT_TYPE_MAP = {
    "pca": "decomposition",
    "pls": "regression",
    "pcr": "regression",
    "linear_regression": "regression",
    "svr": "regression",
    "mcr": "decomposition",
    "nmf": "decomposition",
    "fastica": "decomposition",
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
        label="Apply Saved Model Artifact",
        description="Load a saved model artifact and apply it to inference data",
        parameters=[
            NodeParameter(
                name="model_id",
                label="Artifact",
                param_type="model_select",
                description="Saved model artifact to load and apply",
                required=False,
            ),
        ],
        input_ports=[
            PortMetadata(
                name="X_new",
                type_ref="spectrasherpa://types/SpectralDataset/1.0",
                required=True,
                label="Inference Data",
                description="Spectral data to apply the saved artifact to",
            ),
            PortMetadata(
                name="model_ref",
                type_ref="spectrasherpa://types/ModelReference/1.0",
                required=False,
                label="Artifact Reference",
                description="Artifact ID from a training node or saved model artifact (overrides parameter)",
            ),
        ],
        output_ports=[
            PortMetadata(
                name="result",
                type_ref="spectrasherpa://types/SpectralDataset/1.0",
                required=True,
                label="Predictions",
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
                label="Artifact ID",
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
        lines.append(f"{indent}# --- Apply Saved Model Artifact ({self.node_id}) ---")
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
        lines.append(f"{indent}from spectra_sherpa.app.services.model_application import (")
        lines.append(f"{indent}    _apply_feature_mask as _sherpa_apply_feature_mask,")
        lines.append(f"{indent}    _applicability_diagnostics as _sherpa_applicability_diagnostics,")
        lines.append(f"{indent}    _prepare_X_for_artifact as _sherpa_prepare_X_for_artifact,")
        lines.append(f"{indent}    validate_feature_contract as _sherpa_validate_feature_contract,")
        lines.append(f"{indent}    validate_prepared_feature_contract as _sherpa_validate_prepared_feature_contract,")
        lines.append(f"{indent})")
        lines.append(f"{indent}_sherpa_validate_feature_contract(_X_data, _X_input, _manifest)")
        lines.append(
            f"{indent}_X_data, _, _, _sherpa_replay_warnings = "
            f"_sherpa_prepare_X_for_artifact(_X_data, None, _manifest, scope='all')"
        )
        lines.append(
            f"{indent}_X_data, _sherpa_feature_warnings = " f"_sherpa_apply_feature_mask(_X_data, _X_input, _manifest)"
        )
        lines.append(f"{indent}for _warning in _sherpa_replay_warnings + _sherpa_feature_warnings:")
        lines.append(f"{indent}    print(f'  Load & Apply warning: {{_warning}}')")
        lines.append(f"{indent}_sherpa_validate_prepared_feature_contract(_X_data, _manifest)")

        # Dispatch by model type using Extract classes
        lines.append(f"{indent}_labels = None  # Only set for classification models")
        lines.append(f"{indent}_applicability = None")
        lines.append(f"{indent}if _model_type == 'pca':")
        lines.append(f"{indent}    _loadings = _arrays['loadings']")
        lines.append(f"{indent}    _mean = _arrays.get('mean')")
        lines.append(f"{indent}    _scale = _arrays.get('scale')")
        lines.append(f"{indent}    _centered = _X_data - _mean if _mean is not None else _X_data")
        lines.append(f"{indent}    if _scale is not None:")
        lines.append(f"{indent}        _scale = np.where(np.abs(_scale) > 1e-12, _scale, 1.0)")
        lines.append(f"{indent}        _centered = _centered / _scale")
        lines.append(f"{indent}    _result = _centered @ _loadings.T")
        lines.append(f"{indent}elif _model_type == 'pls':")
        lines.append(f"{indent}    from spectra_sherpa.app.lib.adapters.scp_extractors import (")
        lines.append(f"{indent}        PLSExtract as _PLSExtract,")
        lines.append(f"{indent}    )")
        lines.append(f"{indent}    _extract = _PLSExtract.from_artifact(_manifest, _arrays)")
        lines.append(f"{indent}    _result = _extract.predict(_X_data)")
        lines.append(f"{indent}    _applicability = _sherpa_applicability_diagnostics(_extract, _X_data)")
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
        lines.append(f"{indent}    'applicability': _applicability,")
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
            # wrong arrays to new data.
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

        # Replay stored preprocessing and feature-selection state. This keeps
        # workflow Load & Apply aligned with the Models API and the persisted
        # My Dataset comparison path.
        from spectra_sherpa.app.services.model_application import (
            _applicability_diagnostics,
            _apply_feature_mask,
            _prepare_X_for_artifact,
            validate_feature_contract,
            validate_prepared_feature_contract,
        )

        # Feature-axis validation lives in the shared Models API helper. For
        # artifacts trained after non-contiguous variable selection, it compares
        # the selected wavelength coordinates as actual_wn[mask], not a prefix.
        validate_feature_contract(X_data, X_new, manifest)
        X_data, _, _, replay_warnings = _prepare_X_for_artifact(X_data, None, manifest, scope="all")
        # Applied saved feature mask before final feature-count validation.
        X_data, feature_warnings = _apply_feature_mask(X_data, X_new, manifest)
        for warning in replay_warnings + feature_warnings:
            logger.warning("Load & Apply %s: %s", model_id, warning)

        # Feature count mismatch is checked after preprocessing and selection replay.
        validate_prepared_feature_contract(X_data, manifest)

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
            result["transformed"] = transformed

        elif model_type in {"pls", "pcr", "linear_regression", "svr"}:
            predicted = extract.predict(X_data)
            result["result"] = predicted
            result["y_pred"] = predicted
            result["predictions"] = predicted
            applicability = _applicability_diagnostics(extract, X_data)
            if applicability is not None:
                result["applicability"] = applicability
                n_out = int(applicability.get("n_out_of_domain", 0) or 0)
                if n_out:
                    meta["applicability_warning"] = (
                        f"{n_out} sample{'s' if n_out != 1 else ''} outside saved model applicability domain"
                    )

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
