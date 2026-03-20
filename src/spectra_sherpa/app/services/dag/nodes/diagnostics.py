"""
Diagnostics nodes for model validation and quality control.

These nodes provide statistical diagnostics, outlier detection,
and cross-validation metrics for chemometrics models.
"""

from __future__ import annotations

import logging
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)
from spectra_sherpa.app.lib.sherpa_dataset import EvaluationResult, SherpaDataset

from ..io_contracts import to_numpy_1d, to_numpy_2d
from ..node_base import Node, NodeMetadata, NodeParameter, PortMetadata, register_node


def _unwrap_data(value: Any) -> Any:
    """Return raw numeric data for dataset-like inputs, otherwise passthrough."""
    if isinstance(value, SherpaDataset):
        return value.data
    # Avoid ndarray.data memoryview by checking ndarray first.
    if not isinstance(value, np.ndarray) and hasattr(value, "data"):
        try:
            return value.data
        except Exception:
            return value
    return value


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
        category="validation",
        label="Outlier Detection",
        description=(
            "Identifies samples that deviate from the PCA model using Hotelling T² (distance within "
            "model space) and Q/SPE residuals (distance to model). "
            "Connect directly to a PCA node output — eigenvalues from the PCA model are required to "
            "compute correct T² control limits (Nomikos & MacGregor 1995). "
            "Samples flagged by either statistic at the chosen confidence level are marked as outliers."
        ),
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
        input_ports=[
            PortMetadata(
                name="default",
                type_ref="spectrasherpa://types/Any/1.0",
                required=True,
                label="Input Data",
                description="Input data to process",
            ),
        ],
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

    def generate_python(
        self,
        inputs: dict[str, str],
        indent: str = "    ",
        use_scp: bool = True,
    ) -> list[str]:
        """Generate Python export code for outlier detection.

        Emits code that computes Hotelling T² and Q residuals from a PCA
        model dict (scores + eigenvalues).  Both SCP and pure-numpy modes
        use the same numpy-only path since the computation is independent of
        the PCA backend.
        """
        params = self._resolve_params()
        confidence_level = params.get("confidence_level", 0.95)

        input_expr = inputs.get("default", "input_data")

        lines: list[str] = []
        lines.append(f"{indent}# --- Outlier Detection ({self.node_id}) ---")

        # Extract scores and eigenvalues from PCA model dict
        lines.append(f"{indent}_input = {input_expr}")
        lines.append(f"{indent}_scores = _input.get('scores', _input.get('default'))")
        lines.append(f"{indent}_scores = np.asarray(")
        lines.append(f"{indent}    _scores.data if hasattr(_scores, 'data') else _scores,")
        lines.append(f"{indent}    dtype=np.float64,")
        lines.append(f"{indent})")
        lines.append(f"{indent}_evr = _input.get('explained_variance', np.ones(_scores.shape[1]))")
        lines.append(f"{indent}_evr = np.asarray(_evr, dtype=np.float64)")

        # Hotelling T²
        lines.append(f"{indent}# Hotelling T²")
        lines.append(f"{indent}_eigenvalues = np.maximum(_evr, 1e-12)")
        lines.append(f"{indent}_t2 = np.sum((_scores ** 2) / _eigenvalues, axis=1)")
        lines.append(f"{indent}_t2_limit = np.percentile(_t2, {confidence_level * 100})")

        # Q residuals placeholder (requires reconstruction which is model-dependent)
        lines.append(f"{indent}# Q residuals require model reconstruction — not available in export")
        lines.append(f"{indent}_flags = _t2 > _t2_limit")

        # Print summary
        lines.append(
            f'{indent}print(f"  Outliers: {{np.sum(_flags)}} of {{len(_flags)}} flagged (T² > {{_t2_limit:.4f}})")'
        )

        # Store multi-port output
        lines.append(f"{indent}results['{self.node_id}'] = {{")
        lines.append(f"{indent}    'flags': _flags,")
        lines.append(f"{indent}    'T2': _t2,")
        lines.append(f"{indent}    'Q': None,")
        lines.append(f"{indent}    'model': _input,")
        lines.append(f"{indent}}}")

        return lines

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

        scores = to_numpy_2d(_unwrap_data(pca_model["scores"]), name="scores", dtype=np.float64)

        # Calculate Hotelling T² statistic
        # CRITICAL: T² = t' * Λ⁻¹ * t, where Λ are the eigenvalues from PCA (explained_variance)
        # NOT the variances of the scores! Using score variance is a common error.
        # Reference: Nomikos & MacGregor (1995), Technometrics
        eigenvalues = None

        # Try to get eigenvalues from PCA model's explained_variance (NDDataset)
        if "explained_variance" in pca_model:
            ev = pca_model["explained_variance"]
            try:
                eigenvalues = to_numpy_1d(_unwrap_data(ev), name="explained_variance", dtype=np.float64)
            except Exception:
                if isinstance(ev, (list, np.ndarray)):
                    eigenvalues = np.array(ev, dtype=np.float64).flatten()

        # Try model object if not found in dict
        if eigenvalues is None and hasattr(model, "explained_variance"):
            ev = model.explained_variance
            eigenvalues = to_numpy_1d(_unwrap_data(ev), name="explained_variance", dtype=np.float64)

        # No fallback: using score variance instead of true eigenvalues is a known
        # error (Nomikos & MacGregor 1995).  The upstream PCA node always populates
        # explained_variance, so a missing value indicates a broken workflow connection.
        if eigenvalues is None:
            raise ValueError(
                "PCA eigenvalues (explained_variance) not found in the upstream PCA model output. "
                "Ensure the Outlier Detection node is connected directly to a PCA node output. "
                "Using score variance as a substitute produces incorrect T² control limits "
                "(see Nomikos & MacGregor, Technometrics 1995)."
            )

        # Ensure eigenvalues are positive and match component count
        eigenvalues = np.maximum(eigenvalues[:n_components], 1e-10)

        T2 = np.sum((scores**2) / eigenvalues, axis=1)

        # T² control limit (F-distribution)
        from scipy.stats import f

        alpha = 1 - confidence_level
        F_crit = f.ppf(1 - alpha, n_components, n_observations - n_components)
        T2_limit = (
            (n_components * (n_observations - 1) * (n_observations + 1))
            / (n_observations * (n_observations - n_components))
            * F_crit
        )

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

        reconstructed_data = to_numpy_2d(_unwrap_data(reconstructed), name="reconstructed", dtype=np.float64)
        input_matrix = to_numpy_2d(_unwrap_data(input_data), name="input_data", dtype=np.float64)

        if reconstructed_data.shape != input_matrix.shape:
            raise RuntimeError("Reconstructed data shape does not match input data")

        residuals = input_matrix - reconstructed_data
        Q = np.sum(residuals**2, axis=1)
        Q_limit = float(np.quantile(Q, confidence_level)) if Q.size else 0.0

        # Identify outliers
        T2_outliers = T2 > T2_limit
        Q_outliers = Q > Q_limit
        combined_outliers = T2_outliers | Q_outliers

        n_outliers = np.sum(combined_outliers)

        import uuid

        evaluation = EvaluationResult(
            evaluation_id=str(uuid.uuid4()),
            model_type="PCA",
            outlier_indices=np.where(combined_outliers)[0].tolist(),
            outlier_percentage=float(100 * n_outliers / n_observations),
            hotelling_t2=T2.tolist(),
            q_residuals=Q.tolist(),
            t2_limit=T2_limit,
            q_limit=Q_limit,
        )

        # Evaluation is returned in the result dict — consumers attach it
        # to the appropriate dataset. We do NOT mutate the input dataset
        # here, as that creates non-deterministic side-effects in the DAG.

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
            "evaluation": evaluation,
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

        logger.debug(
            f"[Outlier Detection] Found {n_outliers} outliers "
            f"({100*n_outliers/n_observations:.1f}%) at {confidence_level*100}% confidence"
        )

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
        category="validation",
        label="Cross-Validation",
        description=(
            "Computes RMSECV, Q², R², SEP, RER, and bias from cross-validated predictions. "
            "For NIR calibration reporting: SEP (bias-corrected RMSECV) and RER ≥ 10 are the key "
            "acceptance criteria (ASTM E1655). "
            "'Auto' CV method applies LOOCV when n ≤ 50 (chemometrics standard for small datasets) "
            "and k-fold otherwise."
        ),
        parameters=[
            NodeParameter(
                name="cv_folds",
                label="CV Folds",
                param_type="number",
                default=5,
                min_value=2,
                max_value=20,
                step=1,
                description="Number of cross-validation folds (ignored when cv_method is 'loocv' or 'auto')",
                required=True,
            ),
            NodeParameter(
                name="cv_method",
                label="CV Method",
                param_type="select",
                default="auto",
                options=["auto", "k_fold", "loocv"],
                description=(
                    "Cross-validation strategy: 'auto' uses LOOCV when n ≤ 50 "
                    "(chemometrics standard for small datasets) and k-fold otherwise; "
                    "'loocv' forces Leave-One-Out CV; 'k_fold' uses the CV Folds setting."
                ),
                required=False,
            ),
            NodeParameter(
                name="task_type",
                label="Task Type",
                param_type="select",
                default="regression",
                options=["regression", "classification"],
                description="Scoring mode. Set explicitly to avoid ambiguous regression/classification heuristics.",
                required=False,
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

    def generate_python(
        self,
        inputs: dict[str, str],
        indent: str = "    ",
        use_scp: bool = True,
    ) -> list[str]:
        """Generate Python export code for cross-validation metrics.

        Emits code that computes R², RMSE, and related metrics from
        y_true / y_pred arrays.  Both SCP and pure-numpy modes use the
        same numpy-only path since no SCP dependency is needed.
        """
        params = self._resolve_params()
        cv_folds = params.get("cv_folds", 5)
        task_type = params.get("task_type", "regression")

        y_true_expr = inputs.get("y_true", "y_true")
        y_pred_expr = inputs.get("y_pred", "y_pred")

        lines: list[str] = []
        lines.append(f"{indent}# --- Cross-Validation Metrics ({self.node_id}) ---")

        # Extract y_true / y_pred — dtype preserved so classification
        # string labels are not silently converted to NaN.
        lines.append(f"{indent}_y_true_raw = {y_true_expr}")
        lines.append(f"{indent}_y_true = np.asarray(")
        lines.append(f"{indent}    _y_true_raw.data if hasattr(_y_true_raw, 'data') else _y_true_raw,")
        lines.append(f"{indent}).ravel()")
        lines.append(f"{indent}_y_pred_raw = {y_pred_expr}")
        lines.append(f"{indent}_y_pred = np.asarray(")
        lines.append(f"{indent}    _y_pred_raw.data if hasattr(_y_pred_raw, 'data') else _y_pred_raw,")
        lines.append(f"{indent}).ravel()")

        # Coerce to matching types (int vs string mismatch guard)
        lines.append(f"{indent}if _y_true.dtype != _y_pred.dtype:")
        lines.append(f"{indent}    _y_true = np.array([str(v) for v in _y_true], dtype=object)")
        lines.append(f"{indent}    _y_pred = np.array([str(v) for v in _y_pred], dtype=object)")

        lines.append(f"{indent}if {task_type!r} == 'classification':")
        lines.append(f"{indent}    from sklearn.metrics import accuracy_score, confusion_matrix")
        lines.append(f"{indent}    _unique = np.unique(np.concatenate([_y_true, _y_pred]))")
        lines.append(f"{indent}    _acc = accuracy_score(_y_true, _y_pred)")
        lines.append(f'{indent}    print(f"  Classification: accuracy={{_acc:.4f}}, {{len(_unique)}} classes")')
        lines.append(f"{indent}    results['{self.node_id}'] = {{")
        lines.append(f"{indent}        'model': None,")
        lines.append(
            f"{indent}        'cv_metrics': {{'accuracy': _acc, 'n_classes': len(_unique), "
            f"'n_samples': len(_y_true), 'task_type': 'classification'}},"
        )
        lines.append(f"{indent}        'predictions': _y_pred,")
        lines.append(f"{indent}        'plots': {{'confusion_matrix': confusion_matrix(_y_true, _y_pred).tolist()}},")
        lines.append(f"{indent}    }}")
        lines.append(f"{indent}else:")
        lines.append(f"{indent}    _y_true = _y_true.astype(np.float64)")
        lines.append(f"{indent}    _y_pred = _y_pred.astype(np.float64)")
        lines.append(f"{indent}    _ss_res = np.sum((_y_true - _y_pred) ** 2)")
        lines.append(f"{indent}    _ss_tot = np.sum((_y_true - np.mean(_y_true)) ** 2)")
        lines.append(f"{indent}    _r2 = 1.0 - (_ss_res / _ss_tot) if _ss_tot > 0 else np.nan")
        lines.append(f"{indent}    _rmse = np.sqrt(np.mean((_y_true - _y_pred) ** 2))")
        lines.append(f'{indent}    print(f"  CV Metrics (folds={cv_folds}): R²={{_r2:.6f}}  RMSE={{_rmse:.6f}}")')
        lines.append(f"{indent}    results['{self.node_id}'] = {{")
        lines.append(f"{indent}        'model': None,")
        lines.append(f"{indent}        'cv_metrics': {{'r2': _r2, 'rmse': _rmse, 'n_samples': len(_y_true)}},")
        lines.append(f"{indent}        'predictions': _y_pred,")
        lines.append(f"{indent}        'plots': {{'true_vs_pred': list(zip(_y_true.tolist(), _y_pred.tolist()))}},")
        lines.append(f"{indent}    }}")

        return lines

    async def execute(self, y_true: Any = None, y_pred: Any = None, **kwargs) -> Any:
        """
        Execute cross-validation metrics calculation.

        Args:
            y_true: True target values
            y_pred: Predicted values from cross-validation

        Returns:
            Dict containing CV metrics
        """
        from sklearn.metrics import (
            accuracy_score,
            classification_report,
            confusion_matrix,
            mean_absolute_error,
            mean_squared_error,
            r2_score,
        )

        if y_true is None or y_pred is None:
            raise ValueError("Missing required inputs: y_true and y_pred")

        y_true = to_numpy_1d(_unwrap_data(y_true), name="y_true")
        y_pred = to_numpy_1d(_unwrap_data(y_pred), name="y_pred", expected_length=y_true.shape[0])

        # Coerce y_true and y_pred to matching types so that label
        # comparison works correctly (e.g. int 0 vs string "0").
        # Classification nodes normalise labels to strings via
        # ``prepare_class_labels`` while ``sample_partition`` preserves
        # the original dtype, causing a type mismatch.
        if y_true.dtype != y_pred.dtype:
            # If either side is non-numeric (object/str), cast both to str
            _either_str = y_true.dtype.kind in ("U", "S", "O") or y_pred.dtype.kind in ("U", "S", "O")
            if _either_str:
                y_true = np.array([str(v) for v in y_true], dtype=object)
                y_pred = np.array([str(v) for v in y_pred], dtype=object)
            else:
                # Both numeric but different precision — promote to float64
                y_true = y_true.astype(np.float64)
                y_pred = y_pred.astype(np.float64)

        n_samples = len(y_true)
        cv_folds = self.parameters.get("cv_folds", 5)
        cv_method = self.parameters.get("cv_method", "auto")
        task_type = self.parameters.get("task_type", "regression")

        # Resolve effective CV method: LOOCV is the chemometrics standard for n ≤ 50
        if cv_method == "auto":
            effective_cv = "loocv" if n_samples <= 50 else "k_fold"
        else:
            effective_cv = cv_method  # "loocv" or "k_fold"

        effective_folds = n_samples if effective_cv == "loocv" else int(cv_folds)

        is_classification = task_type == "classification"

        result: dict = {
            "n_samples": n_samples,
            "is_classification": is_classification,
            "cv_method": effective_cv,
            "cv_folds_used": effective_folds,
        }

        if is_classification:
            # Classification metrics
            accuracy = accuracy_score(y_true, y_pred)
            cm = confusion_matrix(y_true, y_pred)
            unique_classes = np.unique(np.concatenate([y_true, y_pred]))

            class_report = classification_report(
                y_true,
                y_pred,
                target_names=[str(c) for c in unique_classes],
                output_dict=True,
                zero_division=0,
            )

            result.update(
                {
                    "accuracy": accuracy,
                    "confusion_matrix": cm.tolist(),
                    "classification_report": class_report,
                    "n_classes": len(unique_classes),
                    "classes": unique_classes.tolist(),
                    "task_type": "classification",
                    "metadata": {
                        "type": "ClassificationCV",
                        "accuracy": accuracy,
                        "n_classes": len(unique_classes),
                    },
                }
            )

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

            # SEP (Standard Error of Prediction) = RMSECV when bias-corrected
            # Bias = mean(y_true - y_pred)
            bias = float(np.mean(y_true - y_pred))
            # SEP = sqrt(RMSECV² - bias²)  (Ref: ASTM E1655, ISO 12099)
            sep_sq = max(0.0, rmse**2 - bias**2)
            sep = float(np.sqrt(sep_sq))

            # RER (Range/Error Ratio) = (y_max - y_min) / RMSECV
            # RER ≥ 10 considered acceptable for screening; ≥ 25 for QC (NIR conventions)
            y_range = float(np.ptp(y_true))  # max - min
            rer = float(y_range / rmse) if rmse > 1e-12 else float("inf")

            result.update(
                {
                    "RMSE": rmse,
                    "RMSECV": rmse,  # Same as RMSE for CV predictions
                    "MAE": mae,
                    "R2": r2,
                    "Q2": Q2,
                    "PRESS": PRESS,
                    "bias": bias,
                    "SEP": sep,
                    "RER": rer,
                    "residuals": (y_true - y_pred).tolist(),
                    "task_type": "regression",
                    "metadata": {
                        "type": "RegressionCV",
                        "RMSECV": rmse,
                        "SEP": sep,
                        "RER": rer,
                        "bias": bias,
                        "Q2": Q2,
                        "R2": r2,
                    },
                }
            )

            logger.debug(
                f"[Cross-Validation] RMSECV: {rmse:.4f}, SEP: {sep:.4f}, "
                f"RER: {rer:.1f}, bias: {bias:.4f}, Q²: {Q2:.4f}, R²: {r2:.4f}"
            )

        # Build scoped EvaluationResult
        import uuid

        eval_kwargs: dict[str, Any] = {
            "evaluation_id": str(uuid.uuid4()),
        }
        if is_classification:
            eval_kwargs["accuracy"] = result["accuracy"]
            eval_kwargs["confusion_matrix"] = result["confusion_matrix"]
        else:
            eval_kwargs["r2"] = result["R2"]
            eval_kwargs["rmse"] = result["RMSE"]
            eval_kwargs["mae"] = result["MAE"]
        result["evaluation"] = EvaluationResult(**eval_kwargs)

        # Add visualization data
        result["data"] = [[y_true[i], y_pred[i]] for i in range(len(y_true))]

        # Ensure explicit ports are populated
        result["model"] = None
        result["cv_metrics"] = {
            k: v
            for k, v in result.items()
            if k not in ["model", "predictions", "plots", "data", "metadata", "residuals", "evaluation"]
        }
        result["predictions"] = y_pred.tolist()
        if is_classification:
            result["plots"] = {"confusion_matrix": result["confusion_matrix"]}
        else:
            result["plots"] = {"true_vs_pred": result["data"]}

        return result


@register_node
class HoldoutEvaluationNode(Node):
    """Evaluate model predictions against a held-out test set.

    Unlike cross-validation, this node reports independent test-set metrics:
    RMSEP/R² for regression, accuracy/confusion matrix for classification.
    The ``task_type`` parameter explicitly selects the metric family so that
    discretised assays are not mis-scored as classification and vice versa.
    """

    metadata = NodeMetadata(
        node_type="diagnostics.holdout_evaluation",
        category="validation",
        label="Holdout Evaluation",
        description=(
            "Compute test-set performance metrics from held-out predictions. "
            "Regression mode reports RMSEP, R², MAE, bias, SEP, and RER. "
            "Classification mode reports accuracy, confusion matrix, and "
            "per-class precision/recall/F1."
        ),
        parameters=[
            NodeParameter(
                name="task_type",
                label="Task Type",
                param_type="select",
                options=["regression", "classification"],
                default="regression",
                description="Metric family — set explicitly to avoid mis-scoring",
                required=True,
            ),
        ],
        input_ports=[
            PortMetadata(
                name="y_true",
                type_ref="spectrasherpa://types/Array1D/1.0",
                required=True,
                label="True Values",
                description="Ground-truth target values from the test set",
            ),
            PortMetadata(
                name="y_pred",
                type_ref="spectrasherpa://types/Array1D/1.0",
                required=True,
                label="Predicted Values",
                description="Model predictions on the test set",
            ),
        ],
        output_ports=[
            PortMetadata(
                name="metrics",
                type_ref="spectrasherpa://types/ValidationResult/1.0",
                required=True,
                label="Test Metrics",
                description="Performance metrics dict (RMSEP/R² or accuracy/confusion matrix)",
            ),
            PortMetadata(
                name="predictions",
                type_ref="spectrasherpa://types/Array1D/1.0",
                required=True,
                label="Predictions",
                description="Predicted values (pass-through for downstream use)",
            ),
            PortMetadata(
                name="visualization",
                type_ref="spectrasherpa://types/Visualization/1.0",
                required=False,
                label="Visualization Data",
                description="Plot-ready data (predicted-vs-actual or confusion matrix)",
            ),
        ],
        input_types=["array", "array"],
        output_type="dict",
    )

    def generate_python(
        self,
        inputs: dict[str, str],
        indent: str = "    ",
        use_scp: bool = True,
    ) -> list[str]:
        """Generate Python export code for holdout evaluation."""
        params = self._resolve_params()
        task_type = params.get("task_type", "regression")
        y_true_expr = inputs.get("y_true", "y_true")
        y_pred_expr = inputs.get("y_pred", "y_pred")

        lines: list[str] = []
        lines.append(f"{indent}# --- Holdout Evaluation ({self.node_id}) ---")

        # Extract arrays — preserve dtype for classification labels
        lines.append(f"{indent}_y_true_raw = {y_true_expr}")
        lines.append(
            f"{indent}_y_true = np.asarray("
            f"_y_true_raw.data if hasattr(_y_true_raw, 'data') else _y_true_raw"
            f").ravel()"
        )
        lines.append(f"{indent}_y_pred_raw = {y_pred_expr}")
        lines.append(
            f"{indent}_y_pred = np.asarray("
            f"_y_pred_raw.data if hasattr(_y_pred_raw, 'data') else _y_pred_raw"
            f").ravel()"
        )

        # Type coercion
        lines.append(f"{indent}if _y_true.dtype != _y_pred.dtype:")
        lines.append(f"{indent}    _y_true = np.array([str(v) for v in _y_true], dtype=object)")
        lines.append(f"{indent}    _y_pred = np.array([str(v) for v in _y_pred], dtype=object)")

        if task_type == "classification":
            lines.append(f"{indent}from sklearn.metrics import accuracy_score, classification_report, confusion_matrix")
            lines.append(f"{indent}_classes = np.unique(np.concatenate([_y_true, _y_pred]))")
            lines.append(f"{indent}_acc = accuracy_score(_y_true, _y_pred)")
            lines.append(f"{indent}_cm = confusion_matrix(_y_true, _y_pred)")
            lines.append(
                f"{indent}_class_report = classification_report("
                f"_y_true, _y_pred, target_names=[str(c) for c in _classes], output_dict=True, zero_division=0)"
            )
            lines.append(f'{indent}print(f"  Test accuracy: {{_acc:.4f}}")')
            lines.append(f"{indent}results['{self.node_id}'] = {{")
            lines.append(
                f"{indent}    'metrics': {{"
                f"'accuracy': _acc, 'n_classes': len(_classes), 'classes': _classes.tolist(), "
                f"'n_samples': len(_y_true), 'task_type': 'classification', "
                f"'classification_report': _class_report"
                f"}},"
            )
            lines.append(f"{indent}    'predictions': _y_pred,")
            lines.append(
                f"{indent}    'visualization': {{"
                f"'data': _cm.tolist(), 'type': 'confusion_matrix', "
                f"'metadata': {{"
                f"'type': 'ClassificationTest', 'accuracy': _acc, 'n_classes': len(_classes), "
                f"'classes': _classes.tolist(), 'n_samples': len(_y_true), 'task_type': 'classification'"
                f"}}"
                f"}},"
            )
            lines.append(f"{indent}}}")
        else:
            lines.append(f"{indent}_y_true = _y_true.astype(np.float64)")
            lines.append(f"{indent}_y_pred = _y_pred.astype(np.float64)")
            lines.append(f"{indent}_finite_mask = np.isfinite(_y_true) & np.isfinite(_y_pred)")
            lines.append(f"{indent}_n_invalid = int(len(_y_true) - np.count_nonzero(_finite_mask))")
            lines.append(f"{indent}_y_true_valid = _y_true[_finite_mask]")
            lines.append(f"{indent}_y_pred_valid = _y_pred[_finite_mask]")
            lines.append(f"{indent}_status = 'ok'")
            lines.append(f"{indent}if _n_invalid > 0:")
            lines.append(f"{indent}    _status = 'contains_non_finite_predictions'")
            lines.append(
                f'{indent}    print(f"  Holdout evaluation warning: dropping {{_n_invalid}} non-finite prediction(s)")'
            )
            lines.append(f"{indent}if len(_y_true_valid) == 0:")
            lines.append(f"{indent}    _rmsep = np.nan")
            lines.append(f"{indent}    _r2 = np.nan")
            lines.append(f"{indent}    _mae = np.nan")
            lines.append(f"{indent}    _bias = np.nan")
            lines.append(f"{indent}    _sep = np.nan")
            lines.append(f"{indent}    _rer = np.nan")
            lines.append(f"{indent}    _status = 'invalid_predictions'")
            lines.append(f"{indent}else:")
            lines.append(f"{indent}    _resid = _y_true_valid - _y_pred_valid")
            lines.append(f"{indent}    _rmsep = np.sqrt(np.mean(_resid ** 2))")
            lines.append(f"{indent}    _mae = np.mean(np.abs(_resid))")
            lines.append(f"{indent}    _bias = np.mean(_resid)")
            lines.append(f"{indent}    _sep_sq = max(0.0, float(_rmsep**2 - _bias**2))")
            lines.append(f"{indent}    _sep = np.sqrt(_sep_sq)")
            lines.append(f"{indent}    _range = np.ptp(_y_true_valid)")
            lines.append(f"{indent}    _rer = (_range / _rmsep) if _rmsep > 1e-12 else np.inf")
            lines.append(f"{indent}    if len(_y_true_valid) > 1:")
            lines.append(f"{indent}        _ss_res = np.sum(_resid ** 2)")
            lines.append(f"{indent}        _ss_tot = np.sum((_y_true_valid - np.mean(_y_true_valid)) ** 2)")
            lines.append(f"{indent}        _r2 = 1.0 - (_ss_res / _ss_tot) if _ss_tot > 0 else np.nan")
            lines.append(f"{indent}    else:")
            lines.append(f"{indent}        _r2 = np.nan")
            lines.append(f'{indent}print(f"  Test RMSEP: {{_rmsep:.6f}}  R²: {{_r2:.6f}}")')
            lines.append(f"{indent}results['{self.node_id}'] = {{")
            lines.append(
                f"{indent}    'metrics': {{"
                f"'RMSEP': _rmsep, 'R2': _r2, 'MAE': _mae, 'bias': _bias, 'SEP': _sep, 'RER': _rer, "
                f"'n_samples': len(_y_true), 'n_valid_samples': len(_y_true_valid), "
                f"'n_invalid_predictions': _n_invalid, 'status': _status, 'task_type': 'regression'"
                f"}},"
            )
            lines.append(f"{indent}    'predictions': _y_pred,")
            lines.append(
                f"{indent}    'visualization': {{"
                f"'data': list(zip(_y_true_valid.tolist(), _y_pred_valid.tolist())), "
                f"'type': 'predicted_vs_actual', "
                f"'metadata': {{"
                f"'type': 'RegressionTest', 'RMSEP': _rmsep, 'R2': _r2, 'MAE': _mae, 'bias': _bias, "
                f"'SEP': _sep, 'RER': _rer, 'n_samples': len(_y_true), 'n_valid_samples': len(_y_true_valid), "
                f"'n_invalid_predictions': _n_invalid, 'status': _status, 'task_type': 'regression'"
                f"}}"
                f"}},"
            )
            lines.append(f"{indent}}}")

        return lines

    async def execute(self, y_true: Any = None, y_pred: Any = None, **kwargs: Any) -> Any:
        """Compute held-out test-set metrics."""
        if y_true is None or y_pred is None:
            raise ValueError("Missing required inputs: y_true and y_pred")

        y_true = to_numpy_1d(_unwrap_data(y_true), name="y_true")
        y_pred = to_numpy_1d(_unwrap_data(y_pred), name="y_pred", expected_length=y_true.shape[0])

        # Coerce to matching types (int vs string mismatch guard)
        if y_true.dtype != y_pred.dtype:
            _either_str = y_true.dtype.kind in ("U", "S", "O") or y_pred.dtype.kind in ("U", "S", "O")
            if _either_str:
                y_true = np.array([str(v) for v in y_true], dtype=object)
                y_pred = np.array([str(v) for v in y_pred], dtype=object)
            else:
                y_true = y_true.astype(np.float64)
                y_pred = y_pred.astype(np.float64)

        task_type = self.parameters.get("task_type", "regression")
        n_samples = len(y_true)

        import uuid

        if task_type == "classification":
            return self._evaluate_classification(y_true, y_pred, n_samples, uuid)
        else:
            return self._evaluate_regression(y_true, y_pred, n_samples, uuid)

    def _evaluate_regression(
        self,
        y_true: np.ndarray,
        y_pred: np.ndarray,
        n_samples: int,
        uuid: Any,
    ) -> dict[str, Any]:
        from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score

        y_true = y_true.astype(np.float64)
        y_pred = y_pred.astype(np.float64)
        total_samples = int(n_samples)

        finite_mask = np.isfinite(y_true) & np.isfinite(y_pred)
        n_valid = int(np.count_nonzero(finite_mask))
        n_invalid = int(total_samples - n_valid)

        if n_invalid:
            logger.warning(
                "Holdout evaluation (regression): dropping %d non-finite prediction(s) before scoring",
                n_invalid,
            )

        y_true_valid = y_true[finite_mask]
        y_pred_valid = y_pred[finite_mask]

        rmsep = float("nan")
        mae = float("nan")
        r2 = float("nan")
        bias = float("nan")
        sep = float("nan")
        rer = float("nan")
        status = "ok"

        if n_invalid:
            status = "contains_non_finite_predictions"

        if n_valid > 0:
            mse = mean_squared_error(y_true_valid, y_pred_valid)
            rmsep = float(np.sqrt(mse))
            mae = float(mean_absolute_error(y_true_valid, y_pred_valid))
            if n_valid > 1:
                r2 = float(r2_score(y_true_valid, y_pred_valid))
            bias = float(np.mean(y_true_valid - y_pred_valid))
            sep_sq = max(0.0, rmsep**2 - bias**2)
            sep = float(np.sqrt(sep_sq))
            y_range = float(np.ptp(y_true_valid))
            rer = float(y_range / rmsep) if rmsep > 1e-12 else float("inf")
        else:
            status = "invalid_predictions"

        metrics = {
            "RMSEP": rmsep,
            "R2": r2,
            "MAE": mae,
            "bias": bias,
            "SEP": sep,
            "RER": rer,
            "n_samples": total_samples,
            "n_valid_samples": n_valid,
            "n_invalid_predictions": n_invalid,
            "status": status,
            "task_type": "regression",
        }

        evaluation = EvaluationResult(
            evaluation_id=str(uuid.uuid4()),
            r2=None if np.isnan(r2) else r2,
            rmse=None if np.isnan(rmsep) else rmsep,
            mae=None if np.isnan(mae) else mae,
        )

        viz_data = [[float(y_true_valid[i]), float(y_pred_valid[i])] for i in range(n_valid)]

        if n_valid > 0:
            logger.info(
                "Holdout evaluation (regression): RMSEP=%.4f, R²=%.4f, SEP=%.4f, RER=%.1f",
                rmsep,
                r2,
                sep,
                rer,
            )
        else:
            logger.warning("Holdout evaluation (regression): all predictions were non-finite; metrics undefined")

        return {
            "metrics": metrics,
            "predictions": y_pred.tolist(),
            "visualization": {
                "data": viz_data,
                "type": "predicted_vs_actual",
                "metadata": {"type": "RegressionTest", **metrics},
            },
            "evaluation": evaluation,
        }

    def _evaluate_classification(
        self,
        y_true: np.ndarray,
        y_pred: np.ndarray,
        n_samples: int,
        uuid: Any,
    ) -> dict[str, Any]:
        from sklearn.metrics import (
            accuracy_score,
            classification_report,
            confusion_matrix,
        )

        accuracy = float(accuracy_score(y_true, y_pred))
        cm = confusion_matrix(y_true, y_pred)
        unique_classes = np.unique(np.concatenate([y_true, y_pred]))

        class_report = classification_report(
            y_true,
            y_pred,
            target_names=[str(c) for c in unique_classes],
            output_dict=True,
            zero_division=0,
        )

        metrics = {
            "accuracy": accuracy,
            "n_classes": len(unique_classes),
            "classes": unique_classes.tolist(),
            "n_samples": n_samples,
            "task_type": "classification",
            "classification_report": class_report,
        }

        evaluation = EvaluationResult(
            evaluation_id=str(uuid.uuid4()),
            accuracy=accuracy,
            confusion_matrix=cm.tolist(),
        )

        logger.info(
            "Holdout evaluation (classification): accuracy=%.4f, %d classes",
            accuracy,
            len(unique_classes),
        )

        return {
            "metrics": metrics,
            "predictions": y_pred.tolist() if hasattr(y_pred, "tolist") else list(y_pred),
            "visualization": {
                "data": cm.tolist(),
                "type": "confusion_matrix",
                "metadata": {
                    "type": "ClassificationTest",
                    **{k: v for k, v in metrics.items() if k != "classification_report"},
                },
            },
            "confusion_matrix": cm.tolist(),
            "evaluation": evaluation,
        }
