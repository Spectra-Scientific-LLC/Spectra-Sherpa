"""
Consolidated classifier prediction node.

Auto-detects model type (PLS-DA, KNN, SIMCA) from the model dict
and dispatches to the appropriate prediction logic.
"""

from __future__ import annotations

import logging
from typing import Any

import numpy as np

from spectra_sherpa.app.lib.scp_compat import scp
from spectra_sherpa.app.services.dag.io_contracts import (
    bind_X,
    to_numpy_2d,
)
from spectra_sherpa.app.services.dag.node_base import (
    Node,
    NodeMetadata,
    PortMetadata,
    register_node,
)

logger = logging.getLogger(__name__)


@register_node
class ClassifierPredictNode(Node):
    """
    Apply a trained classification model to predict class labels for new samples.

    Auto-detects the model type from the input dict:
    - SIMCA: identified by ``class_models`` key (per-class PCA models)
    - KNN: identified by sklearn model with ``predict_proba`` method
    - PLS-DA: SpectroChemPy PLS model (fallback)

    Consolidated classifier prediction node. Auto-detects the classifier type
    from the model and dispatches accordingly.
    """

    metadata = NodeMetadata(
        node_type="classification.predict",
        category="classification",
        label="Apply Classifier",
        description="Apply a trained classification model (PLS-DA, KNN, or SIMCA) to new data",
        parameters=[],
        input_ports=[
            PortMetadata(
                name="X_new",
                type_ref="spectrasherpa://types/SpectralDataset/1.0",
                required=True,
                label="New Spectra",
                description="New spectral data to classify",
            ),
            PortMetadata(
                name="model",
                type_ref="spectrasherpa://types/ClassificationModel/1.0",
                required=True,
                label="Trained Model",
                description="Trained classification model from a training node",
            ),
        ],
        output_ports=[
            PortMetadata(
                name="y_pred",
                type_ref="spectrasherpa://types/Categorical/1.0",
                required=True,
                label="Predicted Classes",
                description="Predicted class labels",
            ),
            PortMetadata(
                name="y_prob",
                type_ref="spectrasherpa://types/Array2D/1.0",
                required=True,
                label="Class Probabilities / Distances",
                description="Predicted class probabilities (PLS-DA/KNN) or distances (SIMCA)",
            ),
        ],
        input_types=["NDDataset", "dict"],
        output_type="dict",
    )

    async def execute(self, X_new: Any = None, model: Any = None, **kwargs: Any) -> dict[str, Any]:
        if X_new is None:
            raise ValueError("Missing required input: X_new (new spectra)")
        if model is None:
            raise ValueError("Missing required input: model (trained classification model)")

        if not isinstance(model, dict):
            raise ValueError("Model must be a dict containing trained model and metadata")

        X_new_ds = bind_X(
            X_new,
            missing_message="Missing required input: X_new (new spectra)",
            dataset_error_message="X_new must be a dataset object",
            allow_array=True,
        )
        X_array = to_numpy_2d(X_new_ds, name="X_new", dtype=np.float64)

        # Auto-detect model type and dispatch
        if "class_models" in model:
            return self._predict_simca(X_array, model)
        elif hasattr(model.get("model"), "predict_proba"):
            return self._predict_knn(X_array, model)
        else:
            return self._predict_plsda(X_array, model)

    # ------------------------------------------------------------------
    # PLS-DA prediction
    # ------------------------------------------------------------------
    def _predict_plsda(self, X_array: np.ndarray, model: dict) -> dict[str, Any]:
        from spectra_sherpa.app.lib.scp_compat import HAS_SCP

        if not HAS_SCP:
            raise ImportError(
                "PLS-DA prediction requires SpectroChemPy. " "Install with: pip install spectra-sherpa[scp]"
            )

        from scipy.special import softmax

        pls_model = model.get("model")
        classes = np.array(model.get("classes", []))

        if pls_model is None:
            raise ValueError("Model dict does not contain 'model' key with trained PLS-DA model")

        X_dataset = scp.NDDataset(X_array)
        Y_pred_raw = pls_model.predict(X_dataset)
        Y_pred_raw_np = to_numpy_2d(Y_pred_raw, name="Y_pred_raw", dtype=np.float64)

        n_classes = len(classes)
        if Y_pred_raw_np.ndim != 2:
            raise ValueError(
                f"PLS-DA predict returned unexpected shape: {Y_pred_raw_np.shape}. "
                f"Expected 2D array with shape (n_samples, n_classes)."
            )
        if Y_pred_raw_np.shape[1] != n_classes:
            raise ValueError(
                f"PLS-DA predict returned {Y_pred_raw_np.shape[1]} columns but expected {n_classes} classes. "
                f"Model may be incompatible with the provided class labels."
            )

        Y_pred_prob = softmax(Y_pred_raw_np, axis=1)
        y_pred = classes[np.argmax(Y_pred_prob, axis=1)]

        return {
            "y_pred": y_pred.tolist(),
            "y_prob": Y_pred_prob.tolist(),
        }

    # ------------------------------------------------------------------
    # KNN prediction
    # ------------------------------------------------------------------
    def _predict_knn(self, X_array: np.ndarray, model: dict) -> dict[str, Any]:
        knn_model = model.get("model")

        if knn_model is None:
            raise ValueError("Model dict does not contain 'model' key with trained KNN model")

        y_pred = knn_model.predict(X_array)
        y_prob = knn_model.predict_proba(X_array)

        return {
            "y_pred": y_pred.tolist(),
            "y_prob": y_prob.tolist(),
        }

    # ------------------------------------------------------------------
    # SIMCA prediction
    # ------------------------------------------------------------------
    def _predict_simca(self, X_array: np.ndarray, model: dict) -> dict[str, Any]:
        class_models = model.get("class_models")
        classes = model.get("classes", [])
        T2_limits = model.get("T2_limits", {})
        Q_limits = model.get("Q_limits", {})

        if class_models is None:
            raise ValueError("Model dict does not contain 'class_models' key")
        if not classes:
            raise ValueError("Model dict does not contain 'classes' list")

        n_samples = X_array.shape[0]
        predictions = []
        all_distances = []

        for i in range(n_samples):
            sample = X_array[i]
            sample_distances = {}

            for cls in classes:
                cls_str = str(cls)
                class_model = class_models.get(cls_str)

                if class_model is None:
                    raise ValueError(f"Missing model for class '{cls}'")

                loadings = np.array(class_model["loadings"])
                eigenvalues = np.array(class_model["eigenvalues"])

                class_mean = class_model.get("class_mean")
                if class_mean is None:
                    raise ValueError(
                        f"Class model for '{cls}' is missing 'class_mean'. "
                        f"The SIMCA model may have been trained with an older version. "
                        f"Please retrain the model."
                    )
                class_mean = np.array(class_mean)

                T2_limit = T2_limits.get(cls_str, T2_limits.get(cls, 1.0))
                Q_limit = Q_limits.get(cls_str, Q_limits.get(cls, 1.0))
                T2_limit = max(float(T2_limit), 1e-10)
                Q_limit = max(float(Q_limit), 1e-10)

                centered_sample = sample - class_mean

                if loadings.ndim == 1:
                    loadings = loadings.reshape(1, -1)
                scores = centered_sample @ loadings.T

                n_components = loadings.shape[0]
                eigenvalues = np.maximum(eigenvalues[:n_components], 1e-10)

                T2 = np.sum((scores**2) / eigenvalues)

                reconstructed = scores @ loadings
                residual = centered_sample - reconstructed
                Q = np.sum(residual**2)

                distance = (T2 / T2_limit) + (Q / Q_limit)
                sample_distances[cls_str] = distance

            closest_class = min(sample_distances, key=sample_distances.get)
            predictions.append(closest_class)
            all_distances.append(sample_distances)

        try:
            if all(isinstance(c, (int, np.integer)) for c in classes):
                predictions = [int(p) for p in predictions]
        except (ValueError, TypeError):
            pass

        logger.debug("Classified %d samples into %d classes", n_samples, len(set(predictions)))

        return {
            "y_pred": predictions,
            "y_prob": all_distances,
        }
