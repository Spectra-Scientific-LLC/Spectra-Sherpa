"""
SIMCA classification nodes.
"""

from __future__ import annotations

import logging
from typing import Any

import numpy as np

from spectra_sherpa.app.lib.scp_compat import scp
from spectra_sherpa.app.services.dag.meta_helpers import add_processing_step, copy_processing_history

from ...io_contracts import (
    bind_X,
    bind_y,
    resolve_legacy_input,
    to_numpy_1d,
    to_numpy_2d,
)
from ...node_base import Node, NodeMetadata, NodeParameter, PortMetadata, register_node
from ..modeling import create_spectral_dataset
from ..visualization import generate_confusion_matrix_heatmap
from .core_utils import (
    make_labeled_coord as _make_labeled_coord,
)
from .core_utils import (
    prepare_class_labels as _prepare_class_labels,
)

logger = logging.getLogger(__name__)



@register_node
class SIMCANode(Node):
    """
    SIMCA (Soft Independent Modeling of Class Analogy) classification node.

    Builds separate PCA model for each class and classifies based on distance to class models.
    Uses Hotelling T² and Q residuals to assess class membership.

    Well-suited for one-class classification and when classes have different structures.
    Widely used in quality control and authentication applications.

    Reference: Wold & Sjöström (1977), Chemometrics: Theory and Application
    """

    metadata = NodeMetadata(
        node_type="classification.simca",
        category="classification",
        label="SIMCA",
        description="SIMCA classification using class-specific PCA models",
        parameters=[
            NodeParameter(
                name="n_components",
                label="Number of Components per Class",
                param_type="number",
                default=3,
                min_value=1,
                max_value=20,
                step=1,
                description="Number of PCs for each class model",
                required=True,
            ),
            NodeParameter(
                name="confidence_level",
                label="Confidence Level",
                param_type="number",
                default=0.95,
                min_value=0.80,
                max_value=0.99,
                step=0.01,
                description="Confidence level for class boundaries",
                required=False,
            ),
        ],
        input_types=["NDDataset", "array"],
        output_type="SIMCAModel",
        input_ports=[
            PortMetadata(
                name="X",
                type_ref="spectrasherpa://types/SpectralDataset/1.0",
                required=True,
                label="Features (X)",
                description="Feature matrix (spectral data or scores)",
            ),
            PortMetadata(
                name="y",
                type_ref="spectrasherpa://types/Categorical/1.0",
                required=False,
                label="Class Labels (y)",
                description="Class labels for each sample (auto-extracted from X if not provided)",
            ),
        ],
        output_ports=[
            PortMetadata(
                name="class_models",
                type_ref="spectrasherpa://types/ClassificationModel/1.0",
                required=True,
                label="Class Models",
                description="Dictionary of PCA models (one per class)",
            ),
            PortMetadata(
                name="predictions",
                type_ref="spectrasherpa://types/Categorical/1.0",
                required=True,
                label="Predictions",
                description="Predicted class labels for training data",
            ),
            PortMetadata(
                name="distances",
                type_ref="spectrasherpa://types/Array1D/1.0",
                required=True,
                label="Class Distances",
                description="Distance metrics to each class model (combined T² and Q)",
            ),
            PortMetadata(
                name="train_accuracy",
                type_ref="spectrasherpa://types/Scalar/1.0",
                required=False,
                label="Training Accuracy",
                description="Classification accuracy on training set",
            ),
            PortMetadata(
                name="confusion_matrix",
                type_ref="spectrasherpa://types/ConfusionMatrix/1.0",
                required=False,
                label="Confusion Matrix",
                description="Classification confusion matrix",
            ),
            PortMetadata(
                name="plots",
                type_ref="spectrasherpa://types/Visualization/1.0",
                required=False,
                label="Plots",
                description="Visualization plots (Confusion Matrix, etc.)",
            ),
        ],
        requires_scp=True,
        help_url="https://www.spectrochempy.fr/reference/generated/spectrochempy.PCA.html",
    )

    async def execute(self, X: Any = None, y: Any = None, **kwargs) -> Any:
        """
        Execute SIMCA classification.

        Args:
            X: NDDataset containing feature data
            y: Class labels

        Returns:
            SIMCA model with classification results
        """
        from scipy.stats import f

        X_ds = bind_X(
            X,
            kwargs,
            missing_message="Missing required input: X (features)",
            dataset_error_message="X must be an dataset object",
            allow_array=False,
        )
        y = bind_y(
            y,
            kwargs,
            X=X_ds,
            required=True,
            infer_from_X=True,
            missing_message=(
                "Missing required input: y (class labels)\n"
                "Either provide labels via the 'y' input port, or use a dataset with labels in X.y"
            ),
            dataset_missing_message=(
                "Dataset passed to y port has no embedded labels. " "Use the y-axis coordinate to store class labels."
            ),
        )

        # Convert to numpy arrays
        X_data = to_numpy_2d(X_ds, name="X", dtype=np.float64)
        y_array = _prepare_class_labels(y, X_data.shape[0])

        # Get parameters
        n_components = self.parameters.get("n_components", 3)
        confidence_level = self.parameters.get("confidence_level", 0.95)

        # Get unique classes
        classes = np.unique(y_array)
        n_classes = len(classes)

        if n_classes < 2:
            raise ValueError(f"Need at least 2 classes, got {n_classes}")

        # Build separate PCA model for each class
        class_models = {}
        T2_limits = {}
        Q_limits = {}

        for cls in classes:
            # Get samples for this class
            class_mask = y_array == cls
            X_class = X_data[class_mask]
            n_class_samples = X_class.shape[0]

            # Need at least n_components + 1 samples for valid F-distribution (df2 > 0)
            if n_class_samples <= n_components:
                raise ValueError(
                    f"Class {cls} has {n_class_samples} samples but needs at least {n_components + 1} for SIMCA"
                )

            # Build PCA model for this class
            X_class_dataset = scp.NDDataset(X_class)
            pca = scp.PCA(n_components=n_components, standardized=False, scaled=True)
            pca.fit(X_class_dataset)

            # Get scores and loadings
            scores = pca.transform()
            scores_data = to_numpy_2d(scores, name="scores", dtype=np.float64)
            loadings_data = to_numpy_2d(pca.components, name="components", dtype=np.float64)

            # Get class mean for proper projection of new samples
            # CRITICAL: PCA centers data, so we need the mean to project new samples correctly
            class_mean = np.mean(X_class, axis=0)

            # Calculate T² limit using CORRECT eigenvalues from PCA model
            # CRITICAL: Use pca.explained_variance (eigenvalues), NOT score variance
            # Reference: Nomikos & MacGregor (1995), Technometrics
            explained_var = to_numpy_1d(pca.explained_variance, name="explained_variance", dtype=np.float64)
            eigenvalues = np.maximum(explained_var[:n_components], 1e-10)

            alpha = 1 - confidence_level
            df2 = n_class_samples - n_components
            # Ensure df2 > 0 (should be guaranteed by check above, but defensive)
            if df2 <= 0:
                df2 = 1
            F_crit = f.ppf(1 - alpha, n_components, df2)
            T2_limit = (n_components * (n_class_samples - 1) * (n_class_samples + 1)) / (n_class_samples * df2) * F_crit

            # Calculate Q limit using chi-squared distribution
            # Reference: Jackson & Mudholkar (1979), Technometrics
            # Q follows approximately chi-squared distribution
            total_var = np.sum(explained_var)
            # Estimate total variance from class data
            data_var = np.var(X_class)
            remaining_var = max(0, data_var - total_var)
            # Estimate degrees of freedom for residual space
            n_residual_dims = max(1, X_class.shape[1] - n_components)
            from scipy.stats import chi2

            Q_limit = max(remaining_var * chi2.ppf(confidence_level, n_residual_dims) / n_residual_dims, 1e-10)

            # Ensure limits are valid (not zero, not NaN, not inf)
            if not np.isfinite(T2_limit) or T2_limit <= 0:
                T2_limit = 1e-10
            if not np.isfinite(Q_limit) or Q_limit <= 0:
                Q_limit = 1e-10

            class_models[cls] = {
                "pca": pca,  # Keep for prediction during execution, removed from result
                "scores": scores_data,
                "loadings": loadings_data,
                "eigenvalues": eigenvalues,
                "class_mean": class_mean,  # CRITICAL: Required for projecting new samples
                "n_samples": n_class_samples,
            }
            T2_limits[cls] = T2_limit
            Q_limits[cls] = Q_limit

        # Classify all samples
        predictions = []
        distances = []  # Distance to each class

        for i in range(len(X_data)):
            sample = X_data[i].reshape(1, -1)
            sample_distances = {}

            for cls in classes:
                model = class_models[cls]
                pca = model["pca"]
                loadings = model["loadings"]
                eigenvalues = model["eigenvalues"]

                # Project sample onto class model
                # scores = (sample - mean) @ loadings
                sample_dataset = scp.NDDataset(sample)
                sample_scores = pca.transform(sample_dataset)
                t = to_numpy_1d(sample_scores, name="sample_scores", dtype=np.float64)

                # Calculate T² distance
                T2 = np.sum((t**2) / eigenvalues)

                # Calculate Q distance (simplified)
                reconstructed = t @ loadings.T
                Q = np.sum((sample.flatten() - reconstructed.flatten()) ** 2)

                # Combined distance (normalized by limits)
                distance = (T2 / T2_limits[cls]) + (Q / Q_limits[cls])
                sample_distances[cls] = distance

            # Classify to closest class (minimum distance)
            closest_class = min(sample_distances, key=sample_distances.get)
            predictions.append(closest_class)
            distances.append(sample_distances)

        predictions = np.array(predictions)

        # Calculate metrics
        from sklearn.metrics import accuracy_score, classification_report, confusion_matrix

        train_accuracy = accuracy_score(y_array, predictions)
        cm = confusion_matrix(y_array, predictions, labels=classes)
        class_report = classification_report(
            y_array, predictions, target_names=[str(c) for c in classes], output_dict=True
        )

        # For visualization: project all samples into first class model's PC space
        # This provides a meaningful reduced-dimension view of the data
        first_class = classes[0]
        first_model = class_models[first_class]
        first_pca = first_model["pca"]

        # Project all samples into first class PC space for visualization
        viz_scores = first_pca.transform(scp.NDDataset(X_data))
        viz_scores_data = to_numpy_2d(viz_scores, name="viz_scores", dtype=np.float64)

        logger.debug("Visualization: projecting all samples into class '%s' PC space", first_class)

        # Create serializable version of class models (exclude PCA objects)
        # CRITICAL: Include class_mean for projecting new samples in SIMCAPredictNode
        serializable_models = {
            str(cls): {
                "scores": model["scores"].tolist() if hasattr(model["scores"], "tolist") else model["scores"],
                "loadings": model["loadings"].tolist() if hasattr(model["loadings"], "tolist") else model["loadings"],
                "eigenvalues": (
                    model["eigenvalues"].tolist() if hasattr(model["eigenvalues"], "tolist") else model["eigenvalues"]
                ),
                "class_mean": (
                    model["class_mean"].tolist() if hasattr(model["class_mean"], "tolist") else model["class_mean"]
                ),
                "n_samples": model["n_samples"],
            }
            for cls, model in class_models.items()
        }

        # Get unique categories from the classes already computed
        label_categories = [str(c) for c in classes]

        # Get input coordinates for NDDataset creation
        _y_coord = X_ds.sample_axis

        # Generate plots
        plots = {}
        plots["confusion_matrix"] = generate_confusion_matrix_heatmap(cm, classes, "Confusion Matrix (Training Set)")

        # =====================================================================
        # Create NDDataset output with proper coordinate coupling
        # =====================================================================

        # Build PC labels for the visualization scores (projected into first class PC space)
        pc_labels = [f"PC{i+1} (Class {first_class})" for i in range(n_components)]

        # Scores NDDataset: shape (n_samples, n_components) — projected into first class PC space
        scores_dataset = create_spectral_dataset(
            data=viz_scores_data,
            x_coord=_make_labeled_coord(pc_labels, title="Principal Component"),
            y_coord=_y_coord,  # Preserve sample labels from input
            units="score",
            title="SIMCA Scores",
        )

        # Add processing history
        copy_processing_history(X_ds, scores_dataset)
        add_processing_step(
            scores_dataset,
            "classification.simca.scores",
            {"n_components": n_components},
            node_id=self.node_id,
        )

        # Store ONLY scientific metadata that coordinates can't carry
        scores_dataset.meta.update(
            {
                "n_components": n_components,
                "label_categories": label_categories,
                "pc_labels": pc_labels,
                "accuracy": train_accuracy,
                "confusion_matrix": cm.tolist(),
                "classification_report": class_report,
                "confidence_level": confidence_level,
                "acceptance_stats": {
                    "T2_limits": {str(k): float(v) for k, v in T2_limits.items()},
                    "Q_limits": {str(k): float(v) for k, v in Q_limits.items()},
                },
            }
        )

        logger.debug("Train accuracy: %.3f with %d PCs per class", train_accuracy, n_components)

        # NDDataset-only return: one serialization boundary at API layer
        return {
            "default": scores_dataset,  # NDDataset: viz scores + sample labels (y) + PC coords (x)
            "model": serializable_models,  # Model port: class models dict for SIMCA Predict
            "plots": plots,  # Pre-built Plotly traces (legitimate visualization output)
        }




@register_node
class SIMCAPredictNode(Node):
    """
    Apply trained SIMCA model to classify new samples.

    Takes new spectral data and a trained SIMCA model, returns predicted
    class labels and distances. SIMCA classification is based on:
    1. Projecting new samples onto each class's PCA model (after centering with class mean)
    2. Calculating T² (distance in model space) and Q (residual distance) for each class
    3. Classifying to the class with minimum normalized distance

    CRITICAL: Requires class_mean from training for proper projection of new samples.
    """

    metadata = NodeMetadata(
        node_type="classification.simca_predict",
        category="classification",
        label="Apply SIMCA Model",
        description="Apply trained SIMCA model to classify new data",
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
                label="SIMCA Model",
                description="Trained SIMCA model from training node",
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
                name="distances",
                type_ref="spectrasherpa://types/Array1D/1.0",
                required=True,
                label="Class Distances",
                description="Normalized distances to each class (T²/T²_lim + Q/Q_lim)",
            ),
        ],
        input_types=["NDDataset", "dict"],
        output_type="dict",
    )

    async def execute(self, X_new: Any = None, model: Any = None, **kwargs: Any) -> dict[str, Any]:
        """
        Apply SIMCA model to new data.

        Args:
            X_new: New spectral data (NDDataset or array)
            model: Trained SIMCA model dict from training node

        Returns:
            Dict with predicted classes and distances to each class
        """
        X_new = resolve_legacy_input(X_new, kwargs, "input_0")
        model = resolve_legacy_input(model, kwargs, "input_1")

        if X_new is None:
            raise ValueError("Missing required input: X_new (new spectra)")
        if model is None:
            raise ValueError("Missing required input: model (trained SIMCA model)")

        # Extract model components from result dict
        if not isinstance(model, dict):
            raise ValueError("Model must be a dict containing SIMCA model components")

        class_models = model.get("class_models")
        classes = model.get("classes", [])
        T2_limits = model.get("T2_limits", {})
        Q_limits = model.get("Q_limits", {})

        if class_models is None:
            raise ValueError("Model dict does not contain 'class_models' key")
        if not classes:
            raise ValueError("Model dict does not contain 'classes' list")

        X_new_ds = bind_X(
            X_new,
            kwargs,
            missing_message="Missing required input: X_new (new spectra)",
            dataset_error_message="X_new must be an dataset object",
            allow_array=True,
        )
        X_array = to_numpy_2d(X_new_ds, name="X_new", dtype=np.float64)

        n_samples = X_array.shape[0]
        predictions = []
        all_distances = []

        # Classify each sample
        for i in range(n_samples):
            sample = X_array[i]
            sample_distances = {}

            for cls in classes:
                cls_str = str(cls)
                class_model = class_models.get(cls_str)

                if class_model is None:
                    raise ValueError(f"Missing model for class '{cls}'")

                # Get model components
                loadings = np.array(class_model["loadings"])
                eigenvalues = np.array(class_model["eigenvalues"])

                # CRITICAL: Get class mean for proper centering
                class_mean = class_model.get("class_mean")
                if class_mean is None:
                    raise ValueError(
                        f"Class model for '{cls}' is missing 'class_mean'. "
                        f"The SIMCA model may have been trained with an older version. "
                        f"Please retrain the model."
                    )
                class_mean = np.array(class_mean)

                # Get limits (convert string keys if needed)
                T2_limit = T2_limits.get(cls_str, T2_limits.get(cls, 1.0))
                Q_limit = Q_limits.get(cls_str, Q_limits.get(cls, 1.0))

                # Ensure limits are positive
                T2_limit = max(float(T2_limit), 1e-10)
                Q_limit = max(float(Q_limit), 1e-10)

                # Center sample using class mean
                centered_sample = sample - class_mean

                # Project onto class model: scores = centered_sample @ loadings.T
                # loadings shape: (n_components, n_features)
                if loadings.ndim == 1:
                    loadings = loadings.reshape(1, -1)
                scores = centered_sample @ loadings.T  # shape: (n_components,)

                # Ensure eigenvalues match component count
                n_components = loadings.shape[0]
                eigenvalues = np.maximum(eigenvalues[:n_components], 1e-10)

                # Calculate T² (Hotelling's T²)
                T2 = np.sum((scores**2) / eigenvalues)

                # Calculate Q (SPE - Squared Prediction Error)
                reconstructed = scores @ loadings  # shape: (n_features,)
                residual = centered_sample - reconstructed
                Q = np.sum(residual**2)

                # Combined normalized distance
                distance = (T2 / T2_limit) + (Q / Q_limit)
                sample_distances[cls_str] = distance

            # Classify to closest class (minimum distance)
            closest_class = min(sample_distances, key=sample_distances.get)
            predictions.append(closest_class)
            all_distances.append(sample_distances)

        # Convert predictions to match original class type if possible
        try:
            if all(isinstance(c, (int, np.integer)) for c in classes):
                predictions = [int(p) for p in predictions]
        except (ValueError, TypeError):
            pass

        logger.debug("Classified %d samples into %d classes", n_samples, len(set(predictions)))

        return {
            "y_pred": predictions,
            "distances": all_distances,
        }
