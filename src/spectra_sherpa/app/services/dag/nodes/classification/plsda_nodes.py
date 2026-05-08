"""
PLS-DA training and prediction nodes.
"""

from __future__ import annotations

import logging
from typing import Any

import numpy as np

from spectra_sherpa.app.lib.adapters.scp_extractors import _safe_getattr
from spectra_sherpa.app.lib.scp_compat import scp
from spectra_sherpa.app.services.dag.meta_helpers import (
    add_processing_step,
    copy_processing_history,
    inherit_origin_flags,
    inherit_sample_flags,
)

from ...io_contracts import (
    bind_X,
    bind_y,
    to_numpy_2d,
)
from ...node_base import Node, NodeMetadata, NodeParameter, NodeResult, PortMetadata, register_node
from ..modeling import create_spectral_dataset
from ..visualization import generate_confusion_matrix_heatmap
from .core_utils import (
    coerce_numeric_array as _coerce_numeric_array,
)
from .core_utils import (
    make_labeled_coord as _make_labeled_coord,
)
from .core_utils import (
    prepare_class_labels as _prepare_class_labels,
)

logger = logging.getLogger(__name__)


@register_node
class PLSDANode(Node):
    """
    Partial Least Squares Discriminant Analysis (PLS-DA) node.

    Performs supervised classification using PLS regression on categorical data.
    PLS-DA extends PLS by encoding class labels as dummy variables (one-hot encoding)
    and using PLS regression to find discriminant directions.

    Common in chemometrics for spectroscopic classification tasks.
    """

    metadata = NodeMetadata(
        node_type="classification.plsda",
        category="classification",
        label="PLS-DA",
        description=(
            "Partial Least Squares Discriminant Analysis for classification. "
            "⚠ Class probabilities are derived via softmax on raw PLS regression outputs "
            "and are NOT calibrated — they indicate relative confidence only. "
            "For reliable probability estimates apply Platt scaling or isotonic regression "
            "to the CV predictions after training."
        ),
        parameters=[
            NodeParameter(
                name="n_components",
                label="Number of Components",
                param_type="number",
                default=2,
                min_value=1,
                max_value=20,
                step=1,
                description="Number of PLS components (latent variables)",
                required=True,
                category="basic",
                hint=(
                    "Must be ≤ min(n_samples − 1, n_features, n_classes). "
                    "Typical chemometrics range: 2–10 LVs. "
                    "Use cross-validation to select the optimal number — the model node reports CV accuracy per LV."
                ),
            ),
            NodeParameter(
                name="scale",
                label="Mean Center + Unit Variance",
                param_type="boolean",
                default=True,
                description=(
                    "Apply mean centering and unit-variance scaling before PLS-DA. "
                    "Recommended for spectral data — leave enabled unless spectra are already pre-scaled."
                ),
                required=False,
                category="basic",
            ),
            NodeParameter(
                name="cv_folds",
                label="Cross-Validation Folds",
                param_type="number",
                default=5,
                min_value=2,
                max_value=20,
                step=1,
                description="Number of folds for cross-validation (must be ≤ smallest class count)",
                required=False,
                category="advanced",
                hint=(
                    "For datasets with n < 50 samples, consider using LOOCV (n folds) via the "
                    "Cross-Validation node. "
                    "Minimum: cv_folds ≤ smallest class count — an error is raised if this is violated."
                ),
            ),
            NodeParameter(
                name="calibrate_probabilities",
                label="Calibrate Probabilities (Platt Scaling)",
                param_type="boolean",
                default=False,
                description=(
                    "Apply Platt scaling (sigmoid calibration) to cross-validated predictions "
                    "to produce statistically calibrated posterior probabilities. "
                    "Reference: Platt (1999). Recommended when probability estimates are used "
                    "for downstream decision-making."
                ),
                required=False,
                category="advanced",
            ),
        ],
        input_types=["NDDataset", "array"],
        output_type="dict",
        input_ports=[
            PortMetadata(
                name="X",
                type_ref="spectrasherpa://types/SpectralDataset/1.0",
                required=True,
                label="Spectra (X)",
                description="Spectral data matrix (n_samples × n_wavenumbers)",
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
                name="model",
                type_ref="spectrasherpa://types/ClassificationModel/1.0",
                required=True,
                label="PLS-DA Model",
                description="Trained PLS-DA classifier",
            ),
            PortMetadata(
                name="predictions",
                type_ref="spectrasherpa://types/Categorical/1.0",
                required=True,
                label="CV Predictions",
                description="Cross-validated class predictions",
            ),
            PortMetadata(
                name="probabilities",
                type_ref="spectrasherpa://types/Array2D/1.0",
                required=True,
                label="Class Probabilities",
                description="Cross-validated class probabilities",
            ),
        ],
        requires_scp=True,
        help_url="https://www.spectrochempy.fr/reference/generated/spectrochempy.PLSRegression.html",
    )

    def generate_python(
        self,
        inputs: dict[str, str],
        indent: str = "    ",
        use_scp: bool = True,
    ) -> list[str]:
        """Generate Python export code for PLS-DA classification."""
        if not use_scp:
            return [
                f"{indent}# --- PLS-DA ({self.node_id}) ---",
                f"{indent}# PLS-DA requires SpectroChemPy (pip install spectra-sherpa[scp])",
                f"{indent}raise ImportError('PLS-DA requires spectrochempy')",
            ]

        params = self._resolve_params()
        n_components = params.get("n_components", 2)
        scale = params.get("scale", True)

        X_expr = inputs.get("X", inputs.get("default", "input_data"))
        y_expr = inputs.get("y")

        lines: list[str] = []
        lines.append(f"{indent}# --- PLS-DA ({self.node_id}) ---")

        # Extract X
        lines.append(f"{indent}_X_input = {X_expr}")
        lines.append(f"{indent}_X_data = np.array(")
        lines.append(f"{indent}    _X_input.data if hasattr(_X_input, 'data') else _X_input,")
        lines.append(f"{indent}    dtype=np.float64,")
        lines.append(f"{indent})")

        # Extract y (class labels)
        if y_expr:
            lines.append(f"{indent}_y_raw = {y_expr}")
            lines.append(f"{indent}_y_labels = np.asarray(_y_raw.data if hasattr(_y_raw, 'data') else _y_raw).ravel()")
        else:
            lines.append(f"{indent}_y_labels = np.asarray(")
            lines.append(f"{indent}    _X_input.target if hasattr(_X_input, 'target') and _X_input.target is not None")
            lines.append(f"{indent}    else _X_input.meta.get('target'),")
            lines.append(f"{indent}).ravel()")

        # One-hot encode → PLS → classify
        scale_str = "True" if scale else "False"
        lines.append(f"{indent}_classes = sorted(set(_y_labels.tolist()))")
        lines.append(f"{indent}_class_map = {{c: i for i, c in enumerate(_classes)}}")
        lines.append(f"{indent}_y_idx = np.array([_class_map[c] for c in _y_labels.tolist()])")
        lines.append(f"{indent}_Y_dummy = np.eye(len(_classes))[_y_idx]")
        lines.append(f"{indent}_X_ndd = scp.NDDataset(_X_data)")
        lines.append(f"{indent}_Y_ndd = scp.NDDataset(_Y_dummy)")
        lines.append(f"{indent}_pls = scp.PLSRegression(n_components={n_components}, scale={scale_str})")
        lines.append(f"{indent}_pls.fit(_X_ndd, _Y_ndd)")
        lines.append(f"{indent}_y_pred_raw = np.asarray(_pls.predict(_X_ndd).data, dtype=np.float64)")
        lines.append(f"{indent}if _y_pred_raw.ndim == 1:")
        lines.append(f"{indent}    _y_pred_raw = _y_pred_raw.reshape(-1, len(_classes))")
        lines.append(f"{indent}# Softmax to probabilities")
        lines.append(f"{indent}_exp = np.exp(_y_pred_raw - _y_pred_raw.max(axis=1, keepdims=True))")
        lines.append(f"{indent}_probs = _exp / _exp.sum(axis=1, keepdims=True)")
        lines.append(f"{indent}_pred_idx = np.argmax(_probs, axis=1)")
        lines.append(f"{indent}_pred_labels = np.array([_classes[i] for i in _pred_idx])")
        lines.append(f"{indent}_accuracy = np.mean(_pred_labels == _y_labels)")
        lines.append(
            f'{indent}print(f"  PLS-DA ({n_components} LVs): accuracy={{_accuracy:.4f}} ({{len(_classes)}} classes)")'
        )

        # Store result
        lines.append(f"{indent}results['{self.node_id}'] = {{")
        lines.append(f"{indent}    'model': {{'model': _pls, 'classes': _classes, 'type': 'plsda'}},")
        lines.append(f"{indent}    'predictions': _pred_labels,")
        lines.append(f"{indent}    'probabilities': _probs,")
        lines.append(f"{indent}}}")

        return lines

    async def execute(self, X: Any = None, y: Any = None, **kwargs) -> Any:
        """
        Execute PLS-DA classification.

        Args:
            X: NDDataset containing spectral data (predictors)
            y: Class labels

        Returns:
            PLS-DA model with classification results
        """
        from sklearn.metrics import (
            accuracy_score,
            balanced_accuracy_score,
            classification_report,
            confusion_matrix,
            f1_score,
        )

        X_ds = bind_X(
            X,
            missing_message="Missing required input: X (spectra)",
            dataset_error_message="X must be an dataset object",
            allow_array=False,
        )
        y = bind_y(
            y,
            X=X_ds,
            required=True,
            infer_from_X=True,
            target_type="categorical",
            missing_message=(
                "Missing required input: y (class labels)\n"
                "Either provide labels via the 'y' input port, or use a dataset with labels in X.y"
            ),
            dataset_missing_message=(
                "Dataset passed to y port has no embedded labels. " "Use the y-axis coordinate to store class labels."
            ),
        )

        n_components = self.parameters.get("n_components", 2)
        requested_n_components = int(n_components)
        component_limit_reason = None
        scale = self.parameters.get("scale", True)
        cv_folds = self.parameters.get("cv_folds", 5)

        # Convert inputs to numpy arrays
        X_data = to_numpy_2d(X_ds, name="X", dtype=np.float64)
        y_array = _prepare_class_labels(y, X_data.shape[0])

        max_components = min(X_data.shape[0] - 1, X_data.shape[1])
        if n_components > max_components:
            logger.warning(
                "[PLS-DA] n_components=%d exceeds max allowed (%d = min(n_samples-1=%d, n_features=%d)). "
                "Clamping to %d. Consider reducing n_components in the node parameters.",
                n_components,
                max_components,
                X_data.shape[0] - 1,
                X_data.shape[1],
                max_components,
            )
            n_components = max_components
            component_limit_reason = (
                f"Requested {requested_n_components} components, but PLS-DA is limited to "
                f"min(n_samples - 1, n_features) = {max_components} for this dataset."
            )

        # Get unique classes
        classes = np.unique(y_array)
        n_classes = len(classes)

        if n_classes < 2:
            raise ValueError(f"Need at least 2 classes, got {n_classes}")

        # PLS-DA uses class labels to construct Y, but its latent variables are
        # still PLS components of X. Do not cap components by n_classes; binary
        # PLS-DA can legitimately fit more than two LVs when X has enough rank.

        class_counts = np.array([(y_array == cls).sum() for cls in classes])
        min_class_count = int(class_counts.min()) if class_counts.size else 0
        if cv_folds > min_class_count:
            raise ValueError(f"cv_folds must be <= smallest class count ({min_class_count}). Got {cv_folds}.")

        # One-hot encode class labels
        Y_dummy = np.zeros((len(y_array), n_classes))
        for i, cls in enumerate(classes):
            Y_dummy[y_array == cls, i] = 1

        # Prepare data as NDDatasets for SpectroChemPy.
        # X may be SherpaDataset (sklearn path) so wrap X_data explicitly.
        X_ndd = scp.NDDataset(X_data)
        Y_dummy_dataset = scp.NDDataset(Y_dummy)

        # Fit PLS-DA model using SpectroChemPy
        pls = scp.PLSRegression(n_components=n_components, scale=scale)
        pls.fit(X_ndd, Y_dummy_dataset)

        # Make predictions on training data
        Y_pred_raw = pls.predict(X_ndd)
        # Extract numpy array from result (these are raw PLS regression outputs, NOT probabilities)
        Y_pred_raw_np = to_numpy_2d(Y_pred_raw, name="Y_pred_raw", dtype=np.float64)

        # Validate prediction shape before processing
        if Y_pred_raw_np.ndim != 2:
            raise ValueError(
                f"PLS-DA predict returned unexpected shape: {Y_pred_raw_np.shape}. "
                f"Expected 2D array with shape (n_samples, n_classes)."
            )
        if Y_pred_raw_np.shape[1] != n_classes:
            raise ValueError(
                f"PLS-DA predict returned {Y_pred_raw_np.shape[1]} columns but expected {n_classes} classes. "
                f"Model may be corrupted or incompatible."
            )

        # CRITICAL: Convert raw PLS predictions to proper probabilities using softmax
        # PLS regression outputs are unbounded continuous values (-∞ to +∞), NOT probabilities!
        # Softmax converts them to valid probabilities (0-1 range, sum to 1)
        from scipy.special import softmax

        Y_pred_prob = softmax(Y_pred_raw_np, axis=1)

        y_pred_train = classes[np.argmax(Y_pred_prob, axis=1)]

        # Cross-validation predictions (also returns softmax-normalized probabilities)
        y_pred_cv, Y_pred_cv_prob = self._cross_val_predict_plsda(X_ds, y_array, classes, n_components, scale, cv_folds)

        # Optional: Platt scaling for calibrated posterior probabilities (Platt 1999)
        calibrate = self.parameters.get("calibrate_probabilities", False)
        if calibrate:
            try:
                from sklearn.base import BaseEstimator, ClassifierMixin
                from sklearn.calibration import CalibratedClassifierCV

                class _PLSDAWrapper(BaseEstimator, ClassifierMixin):
                    """Thin wrapper so CalibratedClassifierCV can calibrate PLS-DA."""

                    def __init__(self, pls_model, classes, scale_flag):
                        self.pls_model = pls_model
                        self.classes_ = classes
                        self.scale_flag = scale_flag

                    def fit(self, X, y):
                        return self  # Already fitted

                    def predict(self, X):
                        Y_raw = np.asarray(self.pls_model.predict(X))
                        return self.classes_[np.argmax(softmax(Y_raw, axis=1), axis=1)]

                    def decision_function(self, X):
                        return np.asarray(self.pls_model.predict(X))

                X_np = to_numpy_2d(X_ds, name="X_ds", dtype=np.float64)
                wrapper = _PLSDAWrapper(pls, classes, scale)
                cal = CalibratedClassifierCV(wrapper, method="sigmoid", cv="prefit")
                # Encode y as integers for calibration
                y_int = np.searchsorted(classes, y_array)
                cal.fit(X_np, y_int)
                Y_pred_prob = cal.predict_proba(X_np)
                calibrate = True  # confirmed success
                logger.info("Platt scaling applied — probabilities are now calibrated")
            except Exception as exc:
                logger.warning("Platt scaling failed, falling back to softmax: %s", exc)
                calibrate = False

        # Calculate metrics
        train_accuracy = accuracy_score(y_array, y_pred_train)
        cv_accuracy = accuracy_score(y_array, y_pred_cv)

        # Confusion matrices
        cm_train = confusion_matrix(y_array, y_pred_train, labels=classes)
        cm_cv = confusion_matrix(y_array, y_pred_cv, labels=classes)

        # Classification report
        class_report = classification_report(
            y_array, y_pred_cv, target_names=[str(c) for c in classes], output_dict=True
        )

        # Classification-appropriate metrics
        cv_balanced_accuracy = balanced_accuracy_score(y_array, y_pred_cv)
        cv_f1_macro = f1_score(y_array, y_pred_cv, average="macro")

        # Get PLS scores for visualization (extract numpy arrays from SpectroChemPy model)
        # Use _safe_getattr for version-resilient attribute access (SCP 0.8.1+)
        raw_scores = _safe_getattr(pls, ("x_scores", "_x_scores", "x_scores_"))
        if raw_scores is None:
            raw_scores = pls.transform(X_ndd)
        X_scores = _coerce_numeric_array(raw_scores)

        raw_loadings = _safe_getattr(pls, ("x_loadings", "_x_loadings", "x_loadings_"))
        if raw_loadings is None:
            raise RuntimeError("Could not extract x_loadings from PLS-DA model")
        X_loadings = _coerce_numeric_array(raw_loadings)

        # Calculate VIP scores (Variable Importance in Projection)
        vip_error = None
        try:
            vip_scores = self._calculate_vip(pls, X_data, Y_dummy)
        except Exception as e:
            logger.warning("VIP calculation failed: %s", e, exc_info=True)
            vip_scores = np.zeros(X_data.shape[1], dtype=float)
            vip_error = f"{type(e).__name__}: {e}"

        # Extract wavenumbers and feature_names from input coordinates for plot generation
        _x_coord = X_ds.feature_axis
        _y_coord = X_ds.sample_axis
        wavenumbers = None
        feature_names = None

        if _x_coord is not None:
            try:
                x_data = _x_coord.data
                if x_data is not None:
                    wavenumbers = np.array(x_data).tolist()
            except Exception:
                pass
            if hasattr(_x_coord, "labels") and _x_coord.labels is not None:
                try:
                    labels = _x_coord.labels
                    feature_names = labels.tolist() if hasattr(labels, "tolist") else list(labels)
                except Exception:
                    pass

        # Generate plots for visualization
        plot_error = None

        try:
            plots = self._generate_plsda_plots(
                X_scores, X_loadings, vip_scores, y_array, classes, n_components, wavenumbers, feature_names
            )

            # Add confusion matrix heatmaps (using shared utility)
            plots["confusion_matrix_train"] = generate_confusion_matrix_heatmap(
                cm_train, classes, "Confusion Matrix (Training Set)"
            )
            plots["confusion_matrix_cv"] = generate_confusion_matrix_heatmap(
                cm_cv, classes, "Confusion Matrix (Cross-Validation)"
            )

        except Exception as e:
            error_msg = f"Plot generation failed: {str(e)}"
            logger.warning("Plot generation failed: %s", e, exc_info=True)
            # Return partial plots with error info instead of silently failing
            plots = {
                "_error": error_msg,
                "_error_type": type(e).__name__,
            }
            plot_error = error_msg

        # Get unique categories from the classes already computed
        label_categories = [str(c) for c in classes]

        # Build LV labels for scores dataset x-axis
        lv_labels = [f"LV{i+1}" for i in range(n_components)]

        # =====================================================================
        # Create SherpaDataset outputs with proper coordinate coupling
        # =====================================================================

        # Scores: shape (n_samples, n_components)
        scores_dataset = create_spectral_dataset(
            data=X_scores,
            x_coord=_make_labeled_coord(lv_labels, title="Latent Variable"),
            y_coord=_y_coord,  # Preserve sample labels from input
            units="score",
            title="PLS-DA Scores",
        )

        # Loadings: shape (n_components, n_features)
        loadings_dataset = create_spectral_dataset(
            data=X_loadings,
            x_coord=_x_coord,  # Preserve wavenumber/feature axis from input
            y_coord=_make_labeled_coord(lv_labels, title="Latent Variable"),
            units="loading",
            title="PLS-DA Loadings",
        )

        # Add processing history
        copy_processing_history(X_ds, scores_dataset)
        add_processing_step(
            scores_dataset,
            "classification.plsda.scores",
            {"n_components": n_components},
            node_id=self.node_id,
        )

        copy_processing_history(X_ds, loadings_dataset)
        add_processing_step(
            loadings_dataset,
            "classification.plsda.loadings",
            {"n_components": n_components},
            node_id=self.node_id,
        )

        # Propagate dataset-level flags. Scores rows are samples;
        # loadings rows are latent variables — origin tags only.
        inherit_sample_flags(X_ds, scores_dataset)
        inherit_origin_flags(X_ds, scores_dataset)
        inherit_origin_flags(X_ds, loadings_dataset)

        # Store ONLY scientific metadata that coordinates can't carry
        scores_dataset.meta.update(
            {
                "type": "PLS_DA",
                "n_components": n_components,
                "requested_n_components": requested_n_components,
                "effective_n_components": int(n_components),
                "component_limit_warning": component_limit_reason,
                "probabilities_calibrated": calibrate,
                "probabilities_warning": (
                    "Class probabilities are softmax-transformed raw PLS regression outputs. "
                    "They are NOT statistically calibrated — do not interpret as true posterior "
                    "probabilities. Apply Platt scaling or isotonic regression on the CV "
                    "predictions for calibrated confidence estimates (Platt 1999)."
                ),
                "label_categories": label_categories,
                "lv_labels": lv_labels,
                "accuracy": cv_accuracy,
                "train_accuracy": train_accuracy,
                "cv_balanced_accuracy": cv_balanced_accuracy,
                "f1_score": cv_f1_macro,
                "confusion_matrix_train": cm_train.tolist(),
                "confusion_matrix_cv": cm_cv.tolist(),
                "classification_report": class_report,
                "y_true": y_array.tolist(),
                "y_pred": y_pred_train.tolist(),
                "y_pred_cv": y_pred_cv.tolist(),
                "vip_scores": vip_scores.tolist(),
                "vip_error": vip_error,
                "plot_error": plot_error,
                "quality_summary": {
                    "accuracy": float(cv_accuracy),
                    "n_components": int(n_components),
                    "requested_n_components": requested_n_components,
                    "effective_n_components": int(n_components),
                    "n_classes": int(len(classes)),
                    "cv_method": f"k-fold (k={cv_folds})",
                    "f1": float(cv_f1_macro),
                    "train_accuracy": float(train_accuracy),
                    "balanced_accuracy": float(cv_balanced_accuracy),
                },
            }
        )

        # SherpaDataset-only return: one serialization boundary at API layer
        return NodeResult(
            outputs={
                "default": scores_dataset,  # SherpaDataset: scores (n_samples, n_components)
                "loadings": loadings_dataset,  # SherpaDataset: loadings (n_components, n_features)
                "model": {  # Wrapped model dict for ClassifierPredictNode
                    "model": pls,
                    "classes": classes.tolist(),
                    "type": "plsda",
                },
                "plots": plots,  # Pre-built Plotly traces (legitimate visualization output)
            },
            diagnostics={
                "accuracy": cv_accuracy,
                "train_accuracy": train_accuracy,
                "cv_balanced_accuracy": cv_balanced_accuracy,
                "f1_score": cv_f1_macro,
                "n_components": n_components,
                "requested_n_components": requested_n_components,
                "effective_n_components": int(n_components),
                "component_limit_warning": component_limit_reason,
                "n_classes": len(classes),
                "confusion_matrix_cv": cm_cv.tolist(),
            },
        )

    def _cross_val_predict_plsda(self, X, y, classes, n_components, scale, cv_folds):
        """
        Perform cross-validated predictions for PLS-DA using SpectroChemPy.

        Returns:
            y_pred: Predicted class labels
            Y_pred_prob: Prediction probabilities
        """
        from sklearn.model_selection import StratifiedKFold

        X_data = to_numpy_2d(X, name="X", dtype=np.float64)

        y_pred = np.zeros_like(y)
        Y_pred_prob = np.zeros((len(y), len(classes)))
        kf = StratifiedKFold(n_splits=cv_folds, shuffle=True, random_state=42)

        for train_idx, test_idx in kf.split(X_data, y):
            X_train_data, X_test_data = X_data[train_idx], X_data[test_idx]
            y_train = y[train_idx]

            # One-hot encode training labels
            Y_train_dummy = np.zeros((len(y_train), len(classes)))
            for i, cls in enumerate(classes):
                Y_train_dummy[y_train == cls, i] = 1

            # Create NDDatasets for SpectroChemPy
            X_train = scp.NDDataset(X_train_data)
            X_test = scp.NDDataset(X_test_data)
            Y_train_dummy_dataset = scp.NDDataset(Y_train_dummy)

            # Fit PLS model on training fold using SpectroChemPy
            pls = scp.PLSRegression(n_components=n_components, scale=scale)
            pls.fit(X_train, Y_train_dummy_dataset)

            # Predict on test fold
            Y_test_pred_raw = pls.predict(X_test)
            # Extract numpy array (raw PLS regression outputs, NOT probabilities)
            Y_test_pred_raw_np = to_numpy_2d(Y_test_pred_raw, name="Y_test_pred_raw", dtype=np.float64)

            # Validate prediction shape before argmax
            if Y_test_pred_raw_np.ndim != 2 or Y_test_pred_raw_np.shape[1] != len(classes):
                raise ValueError(
                    f"CV fold prediction has unexpected shape {Y_test_pred_raw_np.shape}. "
                    f"Expected (n_test_samples, {len(classes)})."
                )

            # CRITICAL: Apply softmax to convert raw PLS outputs to proper probabilities
            from scipy.special import softmax

            Y_test_pred_prob = softmax(Y_test_pred_raw_np, axis=1)

            y_pred[test_idx] = classes[np.argmax(Y_test_pred_prob, axis=1)]
            Y_pred_prob[test_idx] = Y_test_pred_prob

        return y_pred, Y_pred_prob

    def _calculate_vip(self, pls_model, X, Y):
        """
        Calculate Variable Importance in Projection (VIP) scores.

        VIP scores indicate the importance of each variable in the PLS model.
        VIP > 1 indicates important variables.

        Delegates to the shared VIP utility in the selection package.
        """
        from ..selection._vip import extract_vip_from_pls_model

        return extract_vip_from_pls_model(pls_model, X.shape[1])

    def _generate_plsda_plots(
        self, scores, loadings, vip_scores, y_array, classes, n_components, wavenumbers, feature_names=None
    ):
        """
        Generate plots for PLS-DA visualization.

        Args:
            scores: PLS scores array
            loadings: PLS loadings array
            vip_scores: VIP scores array
            y_array: Class labels array
            classes: Unique class labels
            n_components: Number of components
            wavenumbers: Wavenumber values (optional)
            feature_names: Feature names (e.g., ["Sepal Length", "Sepal Width"] for iris) (optional)

        Returns:
            Dict with plot specifications for Quick Plot
        """

        plots = {}

        # 1. Scores Plot (LV1 vs LV2) with confidence ellipses
        if n_components >= 2:
            traces = []

            # Standard Plotly color palette (same as frontend)
            PLOTLY_COLORS = [
                "#636EFA",
                "#EF553B",
                "#00CC96",
                "#AB63FA",
                "#FFA15A",
                "#19D3F3",
                "#FF6692",
                "#B6E880",
                "#FF97FF",
                "#FECB52",
            ]

            # Create scatter traces for each class with confidence ellipses
            for idx, cls in enumerate(classes):
                mask = y_array == cls
                class_scores = scores[mask]

                # Assign color from palette
                color = PLOTLY_COLORS[idx % len(PLOTLY_COLORS)]

                # Scatter trace for this class
                trace = {
                    "x": class_scores[:, 0].tolist(),
                    "y": class_scores[:, 1].tolist(),
                    "type": "scatter",
                    "mode": "markers",
                    "name": str(cls),
                    "marker": {"size": 8, "color": color},
                }
                traces.append(trace)

                # Calculate 95% confidence ellipse
                if len(class_scores) >= 3:  # Need at least 3 points for ellipse
                    ellipse_trace = self._calculate_confidence_ellipse(
                        class_scores[:, 0], class_scores[:, 1], confidence=0.95, name=f"{cls} (95%)", color=color
                    )
                    # Only add ellipse if successfully calculated (not degenerate)
                    if ellipse_trace is not None:
                        traces.append(ellipse_trace)

            plots["scores"] = {
                "data": traces,
                "layout": {
                    "title": "PLS-DA Scores Plot",
                    "xaxis": {"title": "LV1"},
                    "yaxis": {"title": "LV2"},
                    "showlegend": True,
                },
            }

        # 2A. Loadings Line Plot (like PCA) - shows each LV as a line across features
        if len(loadings) > 0:
            # loadings shape: (n_components, n_features)
            n_features = loadings.shape[1]

            # Priority: feature_names > wavenumbers > feature indices
            x_values = None
            x_title = "Feature Index"
            x_reversed = False

            if (
                feature_names is not None
                and isinstance(feature_names, (list, tuple, np.ndarray))
                and len(feature_names) == n_features
            ):
                x_values = feature_names
                x_title = "Feature"
            elif (
                wavenumbers is not None
                and isinstance(wavenumbers, (list, tuple, np.ndarray))
                and len(wavenumbers) == n_features
            ):
                x_values = wavenumbers
                x_title = "Wavenumber (cm⁻¹)"
                x_reversed = True

            if x_values is None:
                x_values = list(range(n_features))

            # Create line traces for each LV
            traces = []
            for i in range(n_components):
                traces.append(
                    {
                        "type": "scatter",
                        "mode": "lines",
                        "x": x_values,
                        "y": loadings[i, :].tolist(),  # LV i's loadings across all features
                        "name": f"LV{i+1}",
                        "line": {"width": 2},
                    }
                )

            plots["loadings_lines"] = {
                "data": traces,
                "layout": {
                    "title": "PLS-DA Loadings (Component Patterns)",
                    "xaxis": {"title": x_title, "autorange": "reversed" if x_reversed else True},
                    "yaxis": {"title": "Loading"},
                    "showlegend": True,
                },
            }

        # 2B. Loadings Biplot (LV1 vs LV2) - shows how features relate to latent variables
        # This is the correct chemometric biplot visualization: arrows showing feature relationships
        if len(loadings) > 0 and n_components >= 2:
            # Create labels for each feature with safety checks
            # loadings shape: (n_components, n_features), we need labels for n_features (columns)
            n_features = loadings.shape[1]

            labels = None
            if (
                feature_names is not None
                and isinstance(feature_names, (list, tuple, np.ndarray))
                and len(feature_names) == n_features
            ):
                labels = feature_names
            elif (
                wavenumbers is not None
                and isinstance(wavenumbers, (list, tuple, np.ndarray))
                and len(wavenumbers) == n_features
            ):
                # For spectral data, use wavenumber values as labels (limit to prevent overcrowding)
                if len(wavenumbers) <= 50:
                    labels = [f"{w:.0f}" for w in wavenumbers]
                else:
                    # For many features, only label every Nth feature
                    step = len(wavenumbers) // 20
                    labels = [f"{wavenumbers[i]:.0f}" if i % step == 0 else "" for i in range(len(wavenumbers))]

            if labels is None:
                labels = [f"F{i}" for i in range(n_features)]

            # Quiver plot: arrows from origin to each feature's loading position
            # Create annotations for arrows (Plotly arrows are annotations)
            # loadings shape: (n_components, n_features) where rows are LVs and columns are features
            annotations = []
            for i in range(n_features):  # Iterate over features (columns)
                lv1 = float(loadings[0, i])  # Loading of feature i on LV1 (component 0)
                lv2 = float(loadings[1, i])  # Loading of feature i on LV2 (component 1)

                # Arrow annotation from (0,0) to (lv1, lv2)
                annotations.append(
                    {
                        "x": lv1,
                        "y": lv2,
                        "ax": 0,  # Arrow starts at origin x
                        "ay": 0,  # Arrow starts at origin y
                        "xref": "x",
                        "yref": "y",
                        "axref": "x",
                        "ayref": "y",
                        "showarrow": True,
                        "arrowhead": 2,
                        "arrowsize": 1,
                        "arrowwidth": 2,
                        "arrowcolor": "steelblue",
                    }
                )

                # Text label at 1.15x the arrow length
                annotations.append(
                    {
                        "x": lv1 * 1.15,
                        "y": lv2 * 1.15,
                        "text": labels[i],
                        "xref": "x",
                        "yref": "y",
                        "showarrow": False,
                        "font": {"size": 10, "color": "black"},
                        "xanchor": "center",
                        "yanchor": "middle",
                    }
                )

            plots["loadings_biplot"] = {
                "data": [
                    {
                        # Dummy invisible trace needed for Plotly to render annotations
                        "x": [0],
                        "y": [0],
                        "type": "scatter",
                        "mode": "markers",
                        "marker": {"size": 0.1, "opacity": 0},
                        "showlegend": False,
                        "hoverinfo": "skip",
                    }
                ],
                "layout": {
                    "title": "PLS-DA Loadings Biplot (Feature Correlations)",
                    "xaxis": {"title": "Loading on LV1", "zeroline": True, "zerolinecolor": "gray", "zerolinewidth": 1},
                    "yaxis": {"title": "Loading on LV2", "zeroline": True, "zerolinecolor": "gray", "zerolinewidth": 1},
                    "showlegend": False,
                    "annotations": annotations,
                    "hovermode": "closest",
                },
            }

        # Set default "loadings" to line plot for consistency with PCA
        if "loadings_lines" in plots:
            plots["loadings"] = plots["loadings_lines"]

        # 3. VIP Scores Bar Plot
        if len(vip_scores) > 0:
            # Show only top N VIP scores for clarity
            top_n = min(50, len(vip_scores))
            top_indices = np.argsort(vip_scores)[-top_n:][::-1]

            # Priority: feature_names > wavenumbers > feature indices (with safety checks)
            if (
                feature_names is not None
                and isinstance(feature_names, (list, tuple, np.ndarray))
                and len(feature_names) == len(vip_scores)
            ):
                x_values = [feature_names[i] for i in top_indices]
                x_title = "Feature"
                x_reversed = False
            elif (
                wavenumbers is not None
                and isinstance(wavenumbers, (list, tuple, np.ndarray))
                and len(wavenumbers) == len(vip_scores)
            ):
                x_values = [wavenumbers[i] for i in top_indices]
                x_title = "Wavenumber (cm⁻¹)"
                x_reversed = True
            else:
                x_values = [i for i in top_indices]
                x_title = "Feature Index"
                x_reversed = False

            plots["vip"] = {
                "data": [
                    {
                        "x": x_values,
                        "y": vip_scores[top_indices].tolist(),
                        "type": "bar",
                        "name": "VIP Scores",
                        "marker": {
                            "color": vip_scores[top_indices].tolist(),
                            "colorscale": "Viridis",
                            "showscale": True,
                            "colorbar": {"title": "VIP"},
                        },
                    }
                ],
                "layout": {
                    "title": f"Top {top_n} VIP Scores (VIP > 1 indicates importance)",
                    "xaxis": {"title": x_title, "autorange": "reversed" if x_reversed else True},
                    "yaxis": {"title": "VIP Score"},
                    "shapes": [
                        {
                            "type": "line",
                            "x0": 0,  # Start from first bar position
                            "x1": len(x_values) - 1,  # End at last bar position
                            "y0": 1,
                            "y1": 1,
                            "line": {"color": "red", "width": 2, "dash": "dash"},
                        }
                    ],
                },
            }

        return plots

    def _calculate_confidence_ellipse(self, x, y, confidence=0.95, name="Ellipse", color=None):
        """
        Calculate confidence ellipse for 2D data.

        Args:
            x: X coordinates
            y: Y coordinates
            confidence: Confidence level (default 0.95 for 95%)
            name: Name for the trace
            color: Line color (optional, uses default if not provided)

        Returns:
            Plotly trace dict for the ellipse, or None if data is degenerate
        """
        from scipy import stats

        # Calculate covariance
        data = np.column_stack([x, y])
        mean = np.mean(data, axis=0)
        cov = np.cov(data.T)

        # Eigenvalues and eigenvectors
        eigenvalues, eigenvectors = np.linalg.eig(cov)

        # Handle degenerate cases (collinear points, zero variance, numerical errors)
        # Ensure eigenvalues are non-negative (they should be, but numerical errors can occur)
        eigenvalues = np.maximum(eigenvalues.real, 0)

        # Skip ellipse if data is essentially degenerate (all points nearly identical)
        if np.max(eigenvalues) < 1e-10:
            return None

        # Ensure both eigenvalues are positive (minimum threshold for numerical stability)
        eigenvalues = np.maximum(eigenvalues, 1e-10)

        # Chi-squared value for confidence level (2 degrees of freedom)
        chi2_val = stats.chi2.ppf(confidence, 2)

        # Calculate ellipse parameters
        angle = np.arctan2(eigenvectors[1, 0], eigenvectors[0, 0])
        width = 2 * np.sqrt(chi2_val * eigenvalues[0])
        height = 2 * np.sqrt(chi2_val * eigenvalues[1])

        # Generate ellipse points
        t = np.linspace(0, 2 * np.pi, 100)
        ellipse = np.column_stack([width / 2 * np.cos(t), height / 2 * np.sin(t)])

        # Rotate ellipse
        rotation_matrix = np.array([[np.cos(angle), -np.sin(angle)], [np.sin(angle), np.cos(angle)]])
        ellipse_rotated = ellipse @ rotation_matrix.T

        # Translate to mean
        ellipse_final = ellipse_rotated + mean

        line_style = {"dash": "dash", "width": 2}
        if color:
            line_style["color"] = color

        return {
            "x": ellipse_final[:, 0].tolist(),
            "y": ellipse_final[:, 1].tolist(),
            "type": "scatter",
            "mode": "lines",
            "name": name,
            "line": line_style,
            "showlegend": False,
        }
