"""
Diagnostics nodes for model validation and quality control.

These nodes provide statistical diagnostics, outlier detection,
and cross-validation metrics for chemometrics models.
"""

from __future__ import annotations

import logging
from typing import Any, Optional
import numpy as np

logger = logging.getLogger(__name__)
from app.lib.scp_compat import NDDataset

from ..node_base import Node, NodeMetadata, NodeParameter, InputPort, PortMetadata, register_node


@register_node
class OutlierDetectionNode(Node):
    """
    Outlier Detection node using Hotelling T² and Q statistics.

    Identifies outlier samples based on PCA model diagnostics.
    Uses Hotelling T² (distance in model space) and Q residuals (distance to model).

    Critical for quality control in pharmaceutical and process industries.

    Reference: Nomikos & MacGregor (1995), Technometrics
    """

    metadata = NodeMetadata(
        node_type="diagnostics.outliers",
        category="modeling",
        label="Outlier Detection",
        description="Hotelling T² and Q statistics for outlier detection",
        parameters=[
            NodeParameter(
                name="confidence_level",
                label="Confidence Level",
                param_type="number",
                default=0.95,
                min_value=0.80,
                max_value=0.99,
                step=0.01,
                description="Confidence level for control limits (e.g., 0.95 = 95%)",
                required=True,
            ),
        ],
        input_types=["PCAModel"],
        output_type="dict",
        output_ports=[
            PortMetadata(
                name="model",
                type_ref="spectrasherpa://types/DecompositionResult/1.0",
                required=True,
                label="PCA Model",
                description="Original model with outlier flags",
            ),
            PortMetadata(
                name="flags",
                type_ref="spectrasherpa://types/Array1D/1.0",
                required=True,
                label="Outlier Flags",
                description="Boolean mask (True=Outlier)",
            ),
            PortMetadata(
                name="T2",
                type_ref="spectrasherpa://types/Array1D/1.0",
                required=True,
                label="Hotelling T²",
                description="T² statistics for each sample",
            ),
            PortMetadata(
                name="Q",
                type_ref="spectrasherpa://types/Array1D/1.0",
                required=True,
                label="Q Residuals",
                description="Q (SPE) statistics for each sample",
            ),
        ],
    )

    async def execute(self, pca_model: Any) -> Any:
        """
        Execute outlier detection on PCA model.

        Args:
            pca_model: PCA model output from PCANode

        Returns:
            Dict containing outlier flags and statistics
        """
        if not isinstance(pca_model, dict) or "model" not in pca_model:
            raise ValueError("Input must be a PCA model output")

        confidence_level = self.parameters.get("confidence_level", 0.95)

        # Extract PCA model components
        model = pca_model["model"]
        n_components = pca_model["n_components"]
        n_observations = pca_model["n_observations"]

        # Get scores (T) and loadings (P) - NDDataset directly
        scores = np.array(pca_model["scores"].data)
        loadings = np.array(pca_model["loadings"].data)

        # Calculate Hotelling T² statistic
        # CRITICAL: T² = t' * Λ⁻¹ * t, where Λ are the eigenvalues from PCA (explained_variance)
        # NOT the variances of the scores! Using score variance is a common error.
        # Reference: Nomikos & MacGregor (1995), Technometrics
        eigenvalues = None

        # Try to get eigenvalues from PCA model's explained_variance (NDDataset)
        if "explained_variance" in pca_model:
            ev = pca_model["explained_variance"]
            if hasattr(ev, "data"):
                eigenvalues = np.array(ev.data).flatten()
            elif isinstance(ev, (list, np.ndarray)):
                eigenvalues = np.array(ev).flatten()

        # Try model object if not found in dict
        if eigenvalues is None and hasattr(model, "explained_variance"):
            ev = model.explained_variance
            if hasattr(ev, "data"):
                eigenvalues = np.array(ev.data).flatten()
            else:
                eigenvalues = np.array(ev).flatten()

        # Fallback to score variance (less accurate but functional)
        if eigenvalues is None:
            logger.warning(
                "PCA eigenvalues not available, falling back to score variance for T² calculation. "
                "This may give slightly different results than using true eigenvalues."
            )
            eigenvalues = np.var(scores, axis=0)

        # Ensure eigenvalues are positive and match component count
        eigenvalues = np.maximum(eigenvalues[:n_components], 1e-10)

        T2 = np.sum((scores ** 2) / eigenvalues, axis=1)

        # T² control limit (F-distribution)
        from scipy.stats import f
        alpha = 1 - confidence_level
        F_crit = f.ppf(1 - alpha, n_components, n_observations - n_components)
        T2_limit = (n_components * (n_observations - 1) * (n_observations + 1)) / (n_observations * (n_observations - n_components)) * F_crit

        # Calculate Q statistic (SPE) from reconstruction residuals
        internal = pca_model.get("_internal", {})
        input_data = internal.get("input_data")
        if input_data is None:
            raise ValueError("Missing PCA input data required for SPE calculation")
        # input_data is NDDataset directly

        # Scores are NDDataset for model operations
        scores_for_reconstruct = pca_model["scores"]
        reconstructed = None
        if hasattr(model, "inverse_transform"):
            try:
                reconstructed = model.inverse_transform(scores_for_reconstruct)
            except Exception:
                reconstructed = None
        if reconstructed is None and hasattr(model, "reconstruct"):
            try:
                reconstructed = model.reconstruct(scores_for_reconstruct)
            except Exception:
                reconstructed = None

        if reconstructed is None:
            raise RuntimeError("PCA model does not support reconstruction for SPE calculation")

        reconstructed_data = np.array(reconstructed.data) if hasattr(reconstructed, "data") else np.array(reconstructed)
        input_matrix = np.array(input_data.data) if hasattr(input_data, "data") else np.array(input_data)

        if reconstructed_data.shape != input_matrix.shape:
            raise RuntimeError("Reconstructed data shape does not match input data")

        residuals = input_matrix - reconstructed_data
        Q = np.sum(residuals ** 2, axis=1)
        Q_limit = float(np.quantile(Q, confidence_level)) if Q.size else 0.0

        # Identify outliers
        T2_outliers = T2 > T2_limit
        Q_outliers = Q > Q_limit
        combined_outliers = T2_outliers | Q_outliers

        n_outliers = np.sum(combined_outliers)

        result = {
            "model": model,  # Pass through original model
            "flags": combined_outliers.tolist(),
            "T2": T2.tolist(),
            "Q": Q.tolist(),
            "T2_limit": T2_limit,
            "Q_limit": Q_limit,
            "outliers": combined_outliers.tolist(),
            "outlier_indices": np.where(combined_outliers)[0].tolist(),
            "n_outliers": int(n_outliers),
            "confidence_level": confidence_level,
            "data": T2.tolist(),  # For visualization
            "metadata": {
                "type": "OutlierDetection",
                "output_type": "diagnostics",
                "n_outliers": int(n_outliers),
                "outlier_percentage": float(100 * n_outliers / n_observations),
                "T2_limit": T2_limit,
                "Q_limit": Q_limit,
                "Q_mean": float(np.mean(Q)) if Q.size else 0.0,
            },
        }

        logger.debug(f"[Outlier Detection] Found {n_outliers} outliers ({100*n_outliers/n_observations:.1f}%) at {confidence_level*100}% confidence")

        return result


@register_node
class CrossValidationNode(Node):
    """
    Cross-Validation Metrics node.

    Calculates cross-validation performance metrics for regression and classification models.
    Provides RMSECV, Q², confusion matrices, and classification accuracy.

    Essential for model validation and comparison.
    """

    metadata = NodeMetadata(
        node_type="diagnostics.cross_validation",
        category="modeling",
        label="Cross-Validation",
        description="Calculate cross-validation metrics for model assessment",
        parameters=[
            NodeParameter(
                name="cv_folds",
                label="CV Folds",
                param_type="number",
                default=5,
                min_value=2,
                max_value=20,
                step=1,
                description="Number of cross-validation folds",
                required=True,
            ),
        ],
        input_types=["array", "array"],
        output_type="dict",
        input_ports=[
            PortMetadata(
                name="y_true",
                type_ref="spectrasherpa://types/Array1D/1.0",
                required=True,
                label="True Values (y)",
                description="True target values",
            ),
            PortMetadata(
                name="y_pred",
                type_ref="spectrasherpa://types/Array1D/1.0",
                required=True,
                label="Predicted Values (ŷ)",
                description="Predicted target values (from CV)",
            ),
        ],
        output_ports=[
            PortMetadata(
                name="model",
                type_ref="spectrasherpa://types/FittedModel/1.0",
                required=False,
                label="CV Model",
                description="CV Model (optional)",
            ),
            PortMetadata(
                name="cv_metrics",
                type_ref="spectrasherpa://types/ValidationResult/1.0",
                required=True,
                label="CV Metrics",
                description="Performance metrics (RMSE, R², etc.)",
            ),
            PortMetadata(
                name="predictions",
                type_ref="spectrasherpa://types/Array1D/1.0",
                required=True,
                label="Predictions",
                description="CV Predicted values",
            ),
            PortMetadata(
                name="plots",
                type_ref="spectrasherpa://types/Visualization/1.0",
                required=False,
                label="Plots",
                description="Plot plotting plotting data",
            ),
        ],
    )

    async def execute(self, y_true: Any = None, y_pred: Any = None, **kwargs) -> Any:
        """
        Execute cross-validation metrics calculation.

        Args:
            y_true: True target values
            y_pred: Predicted values from cross-validation

        Returns:
            Dict containing CV metrics
        """
        from sklearn.metrics import mean_squared_error, r2_score, mean_absolute_error
        from sklearn.metrics import accuracy_score, confusion_matrix, classification_report

        # Handle both positional and keyword arguments
        if y_true is None and "input_0" in kwargs:
            y_true = kwargs["input_0"]
        if y_pred is None and "input_1" in kwargs:
            y_pred = kwargs["input_1"]

        if y_true is None or y_pred is None:
            raise ValueError("Missing required inputs: y_true and y_pred")

        y_true = np.array(y_true).flatten()
        y_pred = np.array(y_pred).flatten()

        if len(y_true) != len(y_pred):
            raise ValueError(f"Length mismatch: y_true ({len(y_true)}) vs y_pred ({len(y_pred)})")

        # Determine if regression or classification
        unique_true = np.unique(y_true)
        is_classification = len(unique_true) < min(20, len(y_true) * 0.1)  # Heuristic

        result = {
            "n_samples": len(y_true),
            "is_classification": is_classification,
        }

        if is_classification:
            # Classification metrics
            accuracy = accuracy_score(y_true, y_pred)
            cm = confusion_matrix(y_true, y_pred)

            class_report = classification_report(
                y_true, y_pred,
                target_names=[str(c) for c in unique_true],
                output_dict=True
            )

            result.update({
                "accuracy": accuracy,
                "confusion_matrix": cm.tolist(),
                "classification_report": class_report,
                "n_classes": len(unique_true),
                "classes": unique_true.tolist(),
                "metadata": {
                    "type": "ClassificationCV",
                    "accuracy": accuracy,
                    "n_classes": len(unique_true),
                },
            })

            logger.debug(f"[Cross-Validation] Classification accuracy: {accuracy:.3f}")

        else:
            # Regression metrics
            mse = mean_squared_error(y_true, y_pred)
            rmse = np.sqrt(mse)
            mae = mean_absolute_error(y_true, y_pred)
            r2 = r2_score(y_true, y_pred)

            # Q² (cross-validated R²) - same as R² for CV predictions
            TSS = np.sum((y_true - np.mean(y_true)) ** 2)
            PRESS = np.sum((y_true - y_pred) ** 2)
            Q2 = 1 - (PRESS / TSS) if TSS > 0 else 0

            result.update({
                "RMSE": rmse,
                "RMSECV": rmse,  # Same as RMSE for CV predictions
                "MAE": mae,
                "R2": r2,
                "Q2": Q2,
                "PRESS": PRESS,
                "residuals": (y_true - y_pred).tolist(),
                "metadata": {
                    "type": "RegressionCV",
                    "RMSECV": rmse,
                    "Q2": Q2,
                    "R2": r2,
                },
            })

            logger.debug(f"[Cross-Validation] RMSECV: {rmse:.4f}, Q²: {Q2:.4f}, R²: {r2:.4f}")

        # Add visualization data
        result["data"] = [[y_true[i], y_pred[i]] for i in range(len(y_true))]

        # Ensure explicit ports are populated
        result["model"] = None
        result["cv_metrics"] = {k: v for k, v in result.items() if k not in ["model", "predictions", "plots", "data", "metadata"]}
        result["predictions"] = y_pred.tolist()
        result["plots"] = {"true_vs_pred": result["data"]}

        return result
