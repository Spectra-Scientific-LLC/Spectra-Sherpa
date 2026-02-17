"""
Classification nodes for chemometrics analysis.

These nodes implement various classification techniques like PLS-DA, KNN, etc.
"""

from __future__ import annotations

from typing import Any, Optional
import re
import numpy as np
from spectra_sherpa.app.lib.scp_compat import scp, NDDataset
from spectra_sherpa.app.lib.analysis_dataset import AnalysisDataset, AxisInfo

import logging

from spectra_sherpa.app.services.dag.meta_helpers import add_processing_step, copy_processing_history, safe_get_coord

from ..node_base import Node, NodeMetadata, NodeParameter, InputPort, PortMetadata, register_node
from .visualization import generate_confusion_matrix_heatmap
from .modeling import _create_spectral_dataset

logger = logging.getLogger(__name__)


def _make_labeled_coord(labels: Any, title: str) -> AxisInfo:
    """
    Create an AxisInfo with string labels and a numeric index axis.

    This replaces the former SpectroChemPy Coord helper so that
    classification nodes work without SCP installed.
    """
    labels_list = [str(v) for v in (labels or [])]
    return AxisInfo(
        values=np.arange(len(labels_list), dtype=float),
        labels=labels_list,
        title=title,
    )


def _coerce_numeric_array(values: Any) -> np.ndarray:
    """
    Best-effort conversion to float ndarray.

    SpectroChemPy objects can occasionally surface object/string dtypes in `.data`
    payloads. This helper converts numeric-like values to float and maps
    non-convertible entries to NaN so downstream code can handle them safely.
    """
    arr = np.asarray(values)
    if np.issubdtype(arr.dtype, np.number):
        return arr.astype(float, copy=False)

    flat = []
    for item in arr.reshape(-1):
        try:
            if isinstance(item, np.generic):
                item = item.item()
            flat.append(float(item))
        except Exception:
            flat.append(np.nan)

    return np.array(flat, dtype=float).reshape(arr.shape)


def _normalize_class_label_value(value: Any) -> str:
    """Normalize one raw class label into a stable, human-readable string."""
    if isinstance(value, np.generic):
        value = value.item()

    if value is None:
        return ""

    if isinstance(value, np.ndarray):
        return _normalize_class_label_value(value.tolist())

    if isinstance(value, (list, tuple)):
        # Common case for SpectroChemPy labels:
        # [datetime(...), "ClassName"] -> use the readable trailing string.
        for item in reversed(value):
            if isinstance(item, str) and item.strip():
                return item.strip()
        normalized_parts = [_normalize_class_label_value(item) for item in value]
        normalized_parts = [part for part in normalized_parts if part]
        if len(normalized_parts) == 1:
            return normalized_parts[0]
        if normalized_parts:
            return " | ".join(normalized_parts)
        return ""

    if isinstance(value, dict):
        for key in ("label", "name"):
            candidate = value.get(key)
            if isinstance(candidate, str) and candidate.strip():
                return candidate.strip()
        return str(value)

    if isinstance(value, str):
        trimmed = value.strip()
        if trimmed.startswith("[") or trimmed.startswith("("):
            quoted = re.findall(r"'([^']+)'|\"([^\"]+)\"", trimmed)
            if quoted:
                return quoted[-1][0] or quoted[-1][1]
        return trimmed

    return str(value)


def _normalize_class_label_vector(raw_labels: Any, n_samples: int) -> np.ndarray:
    """
    Normalize class labels while preserving one label per sample.

    This specifically guards against nested label structures like
    ``[[datetime, "ClassA"], [datetime, "ClassB"], ...]`` where a naive
    ``flatten()`` would incorrectly produce 2× the sample count.
    """
    labels_obj = np.asarray(raw_labels, dtype=object)

    if labels_obj.ndim == 0:
        labels = [_normalize_class_label_value(labels_obj.item())]
    elif labels_obj.ndim == 1:
        if n_samples > 0 and labels_obj.size == n_samples:
            labels = [_normalize_class_label_value(item) for item in labels_obj.tolist()]
        elif n_samples > 0 and labels_obj.size % n_samples == 0:
            reshaped = labels_obj.reshape(n_samples, -1)
            labels = [_normalize_class_label_value(row.tolist()) for row in reshaped]
        else:
            labels = [_normalize_class_label_value(item) for item in labels_obj.tolist()]
    else:
        if n_samples > 0 and labels_obj.shape[0] == n_samples:
            labels = [_normalize_class_label_value(row.tolist()) for row in labels_obj]
        elif n_samples > 0 and labels_obj.size == n_samples:
            labels = [_normalize_class_label_value(item) for item in labels_obj.reshape(-1).tolist()]
        else:
            labels = [_normalize_class_label_value(item) for item in labels_obj.reshape(-1).tolist()]

    return np.asarray(labels, dtype=object)


def _prepare_class_labels(raw_labels: Any, n_samples: int) -> np.ndarray:
    """Build validated class-label vector aligned to X sample count."""
    y_array = _normalize_class_label_vector(raw_labels, n_samples)

    if y_array.shape[0] != n_samples:
        raise ValueError(
            f"X and y must have the same number of samples (X={n_samples}, y={y_array.shape[0]}). "
            "If labels came from dataset coordinates, ensure one class label exists per sample."
        )

    if any(str(label).strip() == "" for label in y_array):
        raise ValueError(
            "Class labels contain empty values. "
            "Please provide one non-empty class label per sample."
        )

    return y_array


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
        description="Partial Least Squares Discriminant Analysis for classification",
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
            ),
            NodeParameter(
                name="scale",
                label="Scale Data",
                param_type="boolean",
                default=True,
                description="Apply mean centering and scaling",
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
                description="Number of folds for cross-validation",
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
    )

    async def execute(self, X: NDDataset = None, y: Any = None, **kwargs) -> Any:
        """
        Execute PLS-DA classification.

        Args:
            X: NDDataset containing spectral data (predictors)
            y: Class labels

        Returns:
            PLS-DA model with classification results
        """
        from spectra_sherpa.app.lib.scp_compat import scp
        from sklearn.model_selection import cross_val_score, cross_val_predict
        from sklearn.metrics import confusion_matrix, classification_report, accuracy_score, balanced_accuracy_score, f1_score

        # Handle both positional and keyword arguments for backward compatibility
        if X is None and "input_0" in kwargs:
            X = kwargs["input_0"]
        if y is None and "input_1" in kwargs:
            y = kwargs["input_1"]

        if X is None:
            raise ValueError("Missing required input: X (spectra)")
        if not isinstance(X, (NDDataset, AnalysisDataset)):
            raise ValueError("X must be an NDDataset or AnalysisDataset object")

        # Auto-extract labels from dataset
        # Case 1: y is None - extract from X
        # Case 2: y is dataset - extract embedded labels from y
        # Case 3: y is array/list - use directly
        if y is None:
            # First: check for explicit target attribute (sklearn datasets store
            # class labels in AnalysisDataset.target, separate from the y-axis)
            _target = getattr(X, "target", None)
            if _target is not None:
                _tarr = np.asarray(_target)
                if _tarr.size > 0:
                    y = _tarr

            # Second: fall back to y-axis coordinate
            if y is None:
                y_coord = safe_get_coord(X, 'y')
                if y_coord is not None:
                    # Extract labels from X's y-axis (prefer labels over data)
                    if hasattr(y_coord, 'labels') and y_coord.labels is not None:
                        y = y_coord.labels
                    elif hasattr(y_coord, 'data') and y_coord.data is not None and np.array(y_coord.data).size > 0:
                        y = y_coord.data
                    else:
                        raise ValueError(
                            "Dataset has y-axis but no labels or data found. "
                            "Please provide class labels explicitly via the 'y' input port."
                        )
                else:
                    raise ValueError(
                        "Missing required input: y (class labels)\n"
                        "Either provide labels via the 'y' input port, or use a dataset with labels in X.y"
                    )
        elif isinstance(y, (NDDataset, AnalysisDataset)):
            # If y IS a dataset, extract embedded labels (don't use the dataset itself)
            y_coord = safe_get_coord(y, 'y')
            if y_coord is not None:
                # Extract from y's own y-axis
                if hasattr(y_coord, 'labels') and y_coord.labels is not None:
                    y = y_coord.labels
                elif hasattr(y_coord, 'data') and y_coord.data is not None and np.array(y_coord.data).size > 0:
                    y = y_coord.data
                else:
                    raise ValueError(
                        "Dataset passed to y port has no embedded labels. "
                        "Use the y-axis coordinate to store class labels."
                    )
            else:
                raise ValueError(
                    "Dataset passed to y port has no y-axis coordinate. "
                    "Cannot extract class labels."
                )

        n_components = self.parameters.get("n_components", 2)
        scale = self.parameters.get("scale", True)
        cv_folds = self.parameters.get("cv_folds", 5)

        # Convert inputs to numpy arrays
        X_data = np.array(X.data)
        y_array = _prepare_class_labels(y, X_data.shape[0])

        max_components = min(X_data.shape[0] - 1, X_data.shape[1])
        if n_components > max_components:
            raise ValueError(
                f"n_components must be <= min(n_samples - 1, n_features). Got {n_components} with max {max_components}."
            )

        # Get unique classes
        classes = np.unique(y_array)
        n_classes = len(classes)

        if n_classes < 2:
            raise ValueError(f"Need at least 2 classes, got {n_classes}")

        # For PLS-DA, max components is further constrained by number of classes
        # The Y matrix has n_classes columns (one-hot encoded), so max rank is n_classes
        max_components_plsda = min(max_components, n_classes)
        if n_components > max_components_plsda:
            n_components = max_components_plsda

        class_counts = np.array([(y_array == cls).sum() for cls in classes])
        min_class_count = int(class_counts.min()) if class_counts.size else 0
        if cv_folds > min_class_count:
            raise ValueError(
                f"cv_folds must be <= smallest class count ({min_class_count}). Got {cv_folds}."
            )

        # One-hot encode class labels
        Y_dummy = np.zeros((len(y_array), n_classes))
        for i, cls in enumerate(classes):
            Y_dummy[y_array == cls, i] = 1

        # Prepare data as NDDatasets for SpectroChemPy.
        # X may be AnalysisDataset (sklearn path) so wrap X_data explicitly.
        X_ndd = scp.NDDataset(X_data) if not isinstance(X, NDDataset) else X
        Y_dummy_dataset = scp.NDDataset(Y_dummy)

        # Fit PLS-DA model using SpectroChemPy
        pls = scp.PLSRegression(n_components=n_components, scale=scale)
        pls.fit(X_ndd, Y_dummy_dataset)

        # Make predictions on training data
        Y_pred_raw = pls.predict(X_ndd)
        # Extract numpy array from result (these are raw PLS regression outputs, NOT probabilities)
        Y_pred_raw_np = np.array(Y_pred_raw.data) if hasattr(Y_pred_raw, "data") else np.array(Y_pred_raw)

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
        y_pred_cv, Y_pred_cv_prob = self._cross_val_predict_plsda(X, y_array, classes, n_components, scale, cv_folds)

        # Calculate metrics
        train_accuracy = accuracy_score(y_array, y_pred_train)
        cv_accuracy = accuracy_score(y_array, y_pred_cv)

        # Confusion matrices
        cm_train = confusion_matrix(y_array, y_pred_train, labels=classes)
        cm_cv = confusion_matrix(y_array, y_pred_cv, labels=classes)

        # Classification report
        class_report = classification_report(y_array, y_pred_cv, target_names=[str(c) for c in classes], output_dict=True)

        # Classification-appropriate metrics
        cv_balanced_accuracy = balanced_accuracy_score(y_array, y_pred_cv)
        cv_f1_macro = f1_score(y_array, y_pred_cv, average="macro")

        # Get PLS scores for visualization (extract numpy arrays from SpectroChemPy model)
        X_scores = _coerce_numeric_array(pls.x_scores.data) if hasattr(pls.x_scores, "data") else _coerce_numeric_array(pls.x_scores)
        X_loadings = _coerce_numeric_array(pls.x_loadings.data) if hasattr(pls.x_loadings, "data") else _coerce_numeric_array(pls.x_loadings)

        # Calculate VIP scores (Variable Importance in Projection)
        vip_error = None
        try:
            vip_scores = self._calculate_vip(pls, X_data, Y_dummy)
        except Exception as e:
            logger.warning("VIP calculation failed: %s", e, exc_info=True)
            vip_scores = np.zeros(X_data.shape[1], dtype=float)
            vip_error = f"{type(e).__name__}: {e}"

        # Extract wavenumbers and feature_names from input coordinates for plot generation
        _x_coord = safe_get_coord(X, 'x')
        _y_coord = safe_get_coord(X, 'y')
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
                X_scores, X_loadings, vip_scores, y_array, classes,
                n_components, wavenumbers, feature_names
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

        # Build LV labels for scores NDDataset x-axis
        lv_labels = [f"LV{i+1}" for i in range(n_components)]

        # =====================================================================
        # Create NDDataset outputs with proper coordinate coupling
        # =====================================================================

        # Scores NDDataset: shape (n_samples, n_components)
        scores_dataset = _create_spectral_dataset(
            data=X_scores,
            x_coord=_make_labeled_coord(lv_labels, title="Latent Variable"),
            y_coord=_y_coord,  # Preserve sample labels from input
            units="score",
            title="PLS-DA Scores",
        )

        # Loadings NDDataset: shape (n_components, n_features)
        loadings_dataset = _create_spectral_dataset(
            data=X_loadings,
            x_coord=_x_coord,  # Preserve wavenumber/feature axis from input
            y_coord=_make_labeled_coord(lv_labels, title="Latent Variable"),
            units="loading",
            title="PLS-DA Loadings",
        )

        # Add processing history
        copy_processing_history(X, scores_dataset)
        add_processing_step(
            scores_dataset,
            "classification.plsda.scores",
            {"n_components": n_components},
            node_id=self.node_id,
        )

        copy_processing_history(X, loadings_dataset)
        add_processing_step(
            loadings_dataset,
            "classification.plsda.loadings",
            {"n_components": n_components},
            node_id=self.node_id,
        )

        # Store ONLY scientific metadata that coordinates can't carry
        scores_dataset.meta.update({
            "n_components": n_components,
            "label_categories": label_categories,
            "lv_labels": lv_labels,
            "accuracy": cv_accuracy,
            "train_accuracy": train_accuracy,
            "cv_balanced_accuracy": cv_balanced_accuracy,
            "f1_score": cv_f1_macro,
            "confusion_matrix_train": cm_train.tolist(),
            "confusion_matrix_cv": cm_cv.tolist(),
            "classification_report": class_report,
            "vip_scores": vip_scores.tolist(),
            "vip_error": vip_error,
            "plot_error": plot_error,
        })

        # NDDataset-only return: one serialization boundary at API layer
        return {
            "default": scores_dataset,      # NDDataset: scores + sample labels (y) + LV coords (x)
            "loadings": loadings_dataset,    # NDDataset: loadings + wavenumbers (x) + LV coords (y)
            "model": pls,                    # Model port for Apply PLS-DA Model
            "plots": plots,                  # Pre-built Plotly traces (legitimate visualization output)
        }

    def _cross_val_predict_plsda(self, X, y, classes, n_components, scale, cv_folds):
        """
        Perform cross-validated predictions for PLS-DA using SpectroChemPy.

        Returns:
            y_pred: Predicted class labels
            Y_pred_prob: Prediction probabilities
        """
        from spectra_sherpa.app.lib.scp_compat import scp
        from sklearn.model_selection import StratifiedKFold

        # Get numpy array from NDDataset
        X_data = np.array(X.data)

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
            Y_test_pred_raw_np = np.array(Y_test_pred_raw.data) if hasattr(Y_test_pred_raw, "data") else np.array(Y_test_pred_raw)

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

    def _get_cv_probabilities(self, X, y, Y_dummy, n_components, scale, cv_folds):
        """
        Get cross-validated probability predictions using SpectroChemPy.

        Note: This method is currently unused but maintained for consistency.
        """
        from spectra_sherpa.app.lib.scp_compat import scp
        from sklearn.model_selection import StratifiedKFold

        # Extract numpy array if X is NDDataset
        X_data = np.array(X.data) if hasattr(X, "data") else np.array(X)

        Y_pred_cv = np.zeros_like(Y_dummy)
        kf = StratifiedKFold(n_splits=cv_folds, shuffle=True, random_state=42)

        for train_idx, test_idx in kf.split(X_data, y):
            X_train_data, X_test_data = X_data[train_idx], X_data[test_idx]
            Y_train = Y_dummy[train_idx]

            # Create NDDatasets for SpectroChemPy
            X_train = scp.NDDataset(X_train_data)
            X_test = scp.NDDataset(X_test_data)
            Y_train_dataset = scp.NDDataset(Y_train)

            pls = scp.PLSRegression(n_components=n_components, scale=scale)
            pls.fit(X_train, Y_train_dataset)

            Y_pred_raw = pls.predict(X_test)
            # Extract numpy array
            Y_pred_cv[test_idx] = np.array(Y_pred_raw.data) if hasattr(Y_pred_raw, "data") else np.array(Y_pred_raw)

        return Y_pred_cv

    def _calculate_vip(self, pls_model, X, Y):
        """
        Calculate Variable Importance in Projection (VIP) scores.

        VIP scores indicate the importance of each variable in the PLS model.
        VIP > 1 indicates important variables.
        """
        # Extract numeric arrays from SpectroChemPy model
        t = _coerce_numeric_array(pls_model.x_scores.data) if hasattr(pls_model.x_scores, "data") else _coerce_numeric_array(pls_model.x_scores)
        # SpectroChemPy returns x_weights as (n_components, n_features), but VIP calculation expects (n_features, n_components)
        w_raw = _coerce_numeric_array(pls_model.x_weights.data) if hasattr(pls_model.x_weights, "data") else _coerce_numeric_array(pls_model.x_weights)
        w = w_raw.T  # Transpose to (n_features, n_components)
        q = _coerce_numeric_array(pls_model.y_loadings.data) if hasattr(pls_model.y_loadings, "data") else _coerce_numeric_array(pls_model.y_loadings)

        # Guard against malformed arrays
        if t.ndim != 2 or w.ndim != 2 or q.ndim < 1:
            return np.zeros(X.shape[1], dtype=float)

        n_features = X.shape[1]
        n_components = t.shape[1]

        # Calculate explained variance for each component
        s = np.diag(t.T @ t @ q.T @ q).reshape(n_components, -1)
        s = np.nan_to_num(s, nan=0.0, posinf=0.0, neginf=0.0)
        total_s = float(np.sum(s))
        if total_s <= 1e-12:
            return np.zeros(n_features, dtype=float)

        # VIP formula
        vip = np.zeros(n_features)
        for i in range(n_features):
            weights = []
            for j in range(n_components):
                norm = float(np.linalg.norm(np.nan_to_num(w[:, j], nan=0.0)))
                if norm <= 1e-12:
                    weights.append(0.0)
                else:
                    weights.append((w[i, j] / norm) ** 2)
            weight = np.array(weights, dtype=float)
            vip[i] = np.sqrt(n_features * np.sum(s.flatten() * weight) / total_s)

        return np.nan_to_num(vip, nan=0.0, posinf=0.0, neginf=0.0)



    def _generate_plsda_plots(self, scores, loadings, vip_scores, y_array, classes, n_components, wavenumbers, feature_names=None):
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
        from scipy import stats

        plots = {}

        # 1. Scores Plot (LV1 vs LV2) with confidence ellipses
        if n_components >= 2:
            traces = []

            # Standard Plotly color palette (same as frontend)
            PLOTLY_COLORS = [
                "#636EFA", "#EF553B", "#00CC96", "#AB63FA", "#FFA15A",
                "#19D3F3", "#FF6692", "#B6E880", "#FF97FF", "#FECB52"
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
                        class_scores[:, 0], class_scores[:, 1],
                        confidence=0.95, name=f"{cls} (95%)", color=color
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
                }
            }

        # 2A. Loadings Line Plot (like PCA) - shows each LV as a line across features
        if len(loadings) > 0:
            # loadings shape: (n_components, n_features)
            n_features = loadings.shape[1]

            # Priority: feature_names > wavenumbers > feature indices
            x_values = None
            x_title = "Feature Index"
            x_reversed = False

            if feature_names is not None and isinstance(feature_names, (list, tuple, np.ndarray)) and len(feature_names) == n_features:
                x_values = feature_names
                x_title = "Feature"
            elif wavenumbers is not None and isinstance(wavenumbers, (list, tuple, np.ndarray)) and len(wavenumbers) == n_features:
                x_values = wavenumbers
                x_title = "Wavenumber (cm⁻¹)"
                x_reversed = True

            if x_values is None:
                x_values = list(range(n_features))

            # Create line traces for each LV
            traces = []
            for i in range(n_components):
                traces.append({
                    "type": "scatter",
                    "mode": "lines",
                    "x": x_values,
                    "y": loadings[i, :].tolist(),  # LV i's loadings across all features
                    "name": f"LV{i+1}",
                    "line": {"width": 2},
                })

            plots["loadings_lines"] = {
                "data": traces,
                "layout": {
                    "title": "PLS-DA Loadings (Component Patterns)",
                    "xaxis": {"title": x_title, "autorange": "reversed" if x_reversed else True},
                    "yaxis": {"title": "Loading"},
                    "showlegend": True,
                }
            }

        # 2B. Loadings Biplot (LV1 vs LV2) - shows how features relate to latent variables
        # This is the correct chemometric biplot visualization: arrows showing feature relationships
        if len(loadings) > 0 and n_components >= 2:
            # Create labels for each feature with safety checks
            # loadings shape: (n_components, n_features), we need labels for n_features (columns)
            n_features = loadings.shape[1]

            labels = None
            if feature_names is not None and isinstance(feature_names, (list, tuple, np.ndarray)) and len(feature_names) == n_features:
                labels = feature_names
            elif wavenumbers is not None and isinstance(wavenumbers, (list, tuple, np.ndarray)) and len(wavenumbers) == n_features:
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
                annotations.append({
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
                })

                # Text label at 1.15x the arrow length
                annotations.append({
                    "x": lv1 * 1.15,
                    "y": lv2 * 1.15,
                    "text": labels[i],
                    "xref": "x",
                    "yref": "y",
                    "showarrow": False,
                    "font": {"size": 10, "color": "black"},
                    "xanchor": "center",
                    "yanchor": "middle",
                })

            plots["loadings_biplot"] = {
                "data": [{
                    # Dummy invisible trace needed for Plotly to render annotations
                    "x": [0],
                    "y": [0],
                    "type": "scatter",
                    "mode": "markers",
                    "marker": {"size": 0.1, "opacity": 0},
                    "showlegend": False,
                    "hoverinfo": "skip",
                }],
                "layout": {
                    "title": "PLS-DA Loadings Biplot (Feature Correlations)",
                    "xaxis": {"title": "Loading on LV1", "zeroline": True, "zerolinecolor": "gray", "zerolinewidth": 1},
                    "yaxis": {"title": "Loading on LV2", "zeroline": True, "zerolinecolor": "gray", "zerolinewidth": 1},
                    "showlegend": False,
                    "annotations": annotations,
                    "hovermode": "closest",
                }
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
            if feature_names is not None and isinstance(feature_names, (list, tuple, np.ndarray)) and len(feature_names) == len(vip_scores):
                x_values = [feature_names[i] for i in top_indices]
                x_title = "Feature"
                x_reversed = False
            elif wavenumbers is not None and isinstance(wavenumbers, (list, tuple, np.ndarray)) and len(wavenumbers) == len(vip_scores):
                x_values = [wavenumbers[i] for i in top_indices]
                x_title = "Wavenumber (cm⁻¹)"
                x_reversed = True
            else:
                x_values = [i for i in top_indices]
                x_title = "Feature Index"
                x_reversed = False

            plots["vip"] = {
                "data": [{
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
                }],
                "layout": {
                    "title": f"Top {top_n} VIP Scores (VIP > 1 indicates importance)",
                    "xaxis": {"title": x_title, "autorange": "reversed" if x_reversed else True},
                    "yaxis": {"title": "VIP Score"},
                    "shapes": [{
                        "type": "line",
                        "x0": 0,  # Start from first bar position
                        "x1": len(x_values) - 1,  # End at last bar position
                        "y0": 1,
                        "y1": 1,
                        "line": {"color": "red", "width": 2, "dash": "dash"},
                    }],
                }
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
        ellipse = np.column_stack([
            width/2 * np.cos(t),
            height/2 * np.sin(t)
        ])

        # Rotate ellipse
        rotation_matrix = np.array([
            [np.cos(angle), -np.sin(angle)],
            [np.sin(angle), np.cos(angle)]
        ])
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


@register_node
class KNNNode(Node):
    """
    K-Nearest Neighbors (KNN) classification node.

    Performs classification based on the k nearest neighbors in the feature space.
    Non-parametric method using distance-based similarity for class assignment.

    Uses sklearn's KNeighborsClassifier implementation.
    """

    metadata = NodeMetadata(
        node_type="classification.knn",
        category="classification",
        label="KNN Classifier",
        description="K-Nearest Neighbors classification",
        parameters=[
            NodeParameter(
                name="n_neighbors",
                label="Number of Neighbors (k)",
                param_type="number",
                default=5,
                min_value=1,
                max_value=50,
                step=1,
                description="Number of neighbors to consider",
                required=True,
            ),
            NodeParameter(
                name="weights",
                label="Weight Function",
                param_type="select",
                default="uniform",
                options=["uniform", "distance"],
                description="Weight function: uniform (all equal) or distance (closer = more weight)",
                required=False,
            ),
            NodeParameter(
                name="metric",
                label="Distance Metric",
                param_type="select",
                default="euclidean",
                options=["euclidean", "manhattan", "chebyshev", "minkowski"],
                description="Distance metric for nearest neighbor calculation",
                required=False,
            ),
            NodeParameter(
                name="cv_folds",
                label="Cross-Validation Folds",
                param_type="number",
                default=5,
                min_value=2,
                max_value=20,
                step=1,
                description="Number of folds for cross-validation",
                required=False,
            ),
        ],
        input_types=["NDDataset", "array"],
        output_type="dict",
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
                name="model",
                type_ref="spectrasherpa://types/ClassificationModel/1.0",
                required=True,
                label="KNN Model",
                description="Trained K-Nearest Neighbors classifier",
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
                description="Class probabilities (if weights=distance)",
            ),
            PortMetadata(
                name="plots",
                type_ref="spectrasherpa://types/Visualization/1.0",
                required=False,
                label="Plots",
                description="Visualization plots (K-tuning, Confusion Matrix, Decision Boundary)",
            ),
        ],
    )

    async def execute(self, X: NDDataset = None, y: Any = None, **kwargs) -> Any:
        """
        Execute KNN classification.

        Args:
            X: NDDataset containing feature data
            y: Class labels

        Returns:
            KNN model with classification results
        """
        from sklearn.neighbors import KNeighborsClassifier
        from sklearn.model_selection import cross_val_score, cross_val_predict
        from sklearn.metrics import confusion_matrix, classification_report, accuracy_score

        # Handle both positional and keyword arguments for backward compatibility
        if X is None and "input_0" in kwargs:
            X = kwargs["input_0"]
        if y is None and "input_1" in kwargs:
            y = kwargs["input_1"]

        if X is None:
            raise ValueError("Missing required input: X (features)")
        if not isinstance(X, (NDDataset, AnalysisDataset)):
            raise ValueError("X must be an NDDataset or AnalysisDataset object")

        # Auto-extract labels from NDDataset/AnalysisDataset
        # Case 1: y is None - extract from X
        # Case 2: y is NDDataset/AnalysisDataset - extract embedded labels from y (don't use raw dataset)
        # Case 3: y is array/list - use directly
        if y is None:
            logger.debug("No y input provided - extracting labels from X")
            # First: check for explicit target attribute (sklearn datasets store
            # class labels in AnalysisDataset.target, separate from the y-axis)
            _target = getattr(X, "target", None)
            if _target is not None:
                _tarr = np.asarray(_target)
                if _tarr.size > 0:
                    y = _tarr
                    logger.debug("Auto-extracted class labels from X.target")

            if y is None:
                y_coord = safe_get_coord(X, 'y') if isinstance(X, (NDDataset, AnalysisDataset)) else None
                if y_coord is not None:
                    # Extract labels from X's y-axis (prefer labels over data)
                    if hasattr(y_coord, 'labels') and y_coord.labels is not None:
                        y = y_coord.labels
                        logger.debug("Auto-extracted class labels from X.y.labels")
                    elif hasattr(y_coord, 'data') and y_coord.data is not None and np.array(y_coord.data).size > 0:
                        y = y_coord.data
                        logger.debug("Auto-extracted class labels from X.y.data")
                    else:
                        raise ValueError(
                            "NDDataset has y-axis but no labels or data found. "
                            "Please provide class labels explicitly via the 'y' input port."
                        )
                else:
                    raise ValueError(
                        "Missing required input: y (class labels)\n"
                        "Either provide labels via the 'y' input port, or use an NDDataset with labels in X.y"
                    )
        elif isinstance(y, (NDDataset, AnalysisDataset)):
            # If y IS an NDDataset/AnalysisDataset, extract embedded labels (don't use the dataset itself)
            logger.debug("y is NDDataset/AnalysisDataset - extracting embedded labels")
            y_coord = safe_get_coord(y, 'y')
            if y_coord is not None:
                # Extract from y's own y-axis
                if hasattr(y_coord, 'labels') and y_coord.labels is not None:
                    y = y_coord.labels
                    logger.debug("Extracted labels from y.y.labels")
                elif hasattr(y_coord, 'data') and y_coord.data is not None and np.array(y_coord.data).size > 0:
                    y = y_coord.data
                    logger.debug("Extracted labels from y.y.data")
                else:
                    raise ValueError(
                        "NDDataset passed to y port has no embedded labels. "
                        "Use the y-axis coordinate to store class labels."
                    )
            else:
                raise ValueError(
                    "NDDataset passed to y port has no y-axis coordinate. "
                    "Cannot extract class labels."
                )

        # Convert to numpy arrays - X is NDDataset or AnalysisDataset
        X_data = np.array(X.data)
        y_array = _prepare_class_labels(y, X_data.shape[0])

        # Get parameters
        n_neighbors = self.parameters.get("n_neighbors", 5)
        weights = self.parameters.get("weights", "uniform")
        metric = self.parameters.get("metric", "euclidean")
        cv_folds = self.parameters.get("cv_folds", 5)

        # Get unique classes
        classes = np.unique(y_array)
        n_classes = len(classes)

        if n_classes < 2:
            raise ValueError(f"Need at least 2 classes, got {n_classes}")

        # Fit KNN model
        knn = KNeighborsClassifier(
            n_neighbors=n_neighbors,
            weights=weights,
            metric=metric,
            algorithm='auto'
        )
        knn.fit(X_data, y_array)

        # Make predictions on training data
        y_pred_train = knn.predict(X_data)
        y_pred_prob_train = knn.predict_proba(X_data)

        # Cross-validation predictions with stratified folds
        from sklearn.model_selection import StratifiedKFold
        cv_splitter = StratifiedKFold(n_splits=cv_folds, shuffle=True, random_state=42)
        y_pred_cv = cross_val_predict(knn, X_data, y_array, cv=cv_splitter)
        # Get CV probabilities using method='predict_proba'
        y_pred_prob_cv = cross_val_predict(knn, X_data, y_array, cv=cv_splitter, method='predict_proba')
        cv_scores = cross_val_score(knn, X_data, y_array, cv=cv_splitter)

        # Calculate metrics
        train_accuracy = accuracy_score(y_array, y_pred_train)
        cv_accuracy = cv_scores.mean()

        # Confusion matrices
        cm_train = confusion_matrix(y_array, y_pred_train, labels=classes)
        cm_cv = confusion_matrix(y_array, y_pred_cv, labels=classes)

        # Classification report
        class_report = classification_report(
            y_array, y_pred_cv,
            target_names=[str(c) for c in classes],
            output_dict=True
        )

        # Get unique categories from the classes already computed
        label_categories = [str(c) for c in classes]

        # Get input coordinates for NDDataset creation
        _x_coord = safe_get_coord(X, 'x')
        _y_coord = safe_get_coord(X, 'y')

        # For visualization: if feature space is high-dimensional (>10 features),
        # compute PCA internally for meaningful 2D/3D visualization
        n_features = X_data.shape[1]
        viz_data = X_data
        viz_labels = None

        if n_features > 10:
            # Compute PCA for visualization only (doesn't affect KNN model)
            # Use sklearn PCA (portable, no SCP dependency)
            from sklearn.decomposition import PCA as SklearnPCA
            n_viz_components = min(5, n_features, X_data.shape[0])

            pca_viz = SklearnPCA(n_components=n_viz_components)
            viz_data = pca_viz.fit_transform(X_data)

            # Get explained variance for labels
            explained_var = pca_viz.explained_variance_ratio_
            viz_labels = [f"PC{i+1} ({explained_var[i]*100:.1f}%)" for i in range(n_viz_components)]

            logger.debug("High-dimensional data (%d features) - computed PCA for visualization (%d PCs)", n_features, n_viz_components)
        else:
            # Low-dimensional data, use as-is
            viz_labels = [f"Feature {i+1}" for i in range(n_features)]
            logger.debug("Low-dimensional data (%d features) - using original features for visualization", n_features)

        # --- K-Value Optimization ---
        # Run a quick search for optimal K to guide the user
        k_tuning_results = self._optimize_k(X_data, y_array, max_k=20, folds=cv_folds)

        # --- Generate Plots ---
        plots = {}

        # 1. K-Tuning Plot
        if k_tuning_results:
            plots["k_optimization"] = self._generate_k_plot(k_tuning_results)

        # 2. Confusion Matrices
        plots["confusion_matrix_train"] = generate_confusion_matrix_heatmap(
            cm_train, classes, "Confusion Matrix (Training Set)"
        )
        plots["confusion_matrix_cv"] = generate_confusion_matrix_heatmap(
            cm_cv, classes, "Confusion Matrix (Cross-Validation)"
        )

        # 3. Decision Boundary (PCA-reduced 2D)
        # We already have PCA computed for high-dim data (viz_data)
        # If low-dim, we use the first 2 features.
        try:
            plots["decision_boundary"] = self._generate_decision_boundary_plot(
                viz_data[:, :2],  # Use first 2 dims (PCs or features)
                y_array,
                classes,
                n_neighbors=n_neighbors,
                weights=weights
            )
        except Exception as e:
            logger.warning("Failed to generate decision boundary plot: %s", e)

        # =====================================================================
        # Create NDDataset output with proper coordinate coupling
        # =====================================================================

        # KNN doesn't have scores/loadings — use viz_data (PCA-reduced or original features)
        # as the primary output for the "default" port
        scores_dataset = _create_spectral_dataset(
            data=viz_data,
            x_coord=_make_labeled_coord(viz_labels, title="Feature"),
            y_coord=_y_coord,  # Preserve sample labels from input
            units="score",
            title="KNN Visualization Scores",
        )

        # Add processing history
        copy_processing_history(X, scores_dataset)
        add_processing_step(
            scores_dataset,
            "classification.knn.scores",
            {"n_neighbors": n_neighbors},
            node_id=self.node_id,
        )

        # Store ONLY scientific metadata that coordinates can't carry
        scores_dataset.meta.update({
            "n_neighbors": n_neighbors,
            "label_categories": label_categories,
            "pc_labels": viz_labels,
            "accuracy": cv_accuracy,
            "train_accuracy": train_accuracy,
            "confusion_matrix_train": cm_train.tolist(),
            "confusion_matrix_cv": cm_cv.tolist(),
            "classification_report": class_report,
            "optimal_k": k_tuning_results.get("best_k") if k_tuning_results else None,
        })

        logger.debug("Train accuracy: %.3f, CV accuracy: %.3f", train_accuracy, cv_accuracy)

        # NDDataset-only return: one serialization boundary at API layer
        return {
            "default": scores_dataset,      # NDDataset: viz scores + sample labels (y) + feature coords (x)
            "model": knn,                    # Model port for Apply KNN Model
            "plots": plots,                  # Pre-built Plotly traces (legitimate visualization output)
        }

    def _optimize_k(self, X, y, max_k=20, folds=5) -> dict:
        """
        Search for optimal K value using cross-validation.
        """
        from sklearn.neighbors import KNeighborsClassifier
        from sklearn.model_selection import cross_val_score, StratifiedKFold
        
        n_samples = len(y)
        limit_k = min(max_k, int(n_samples * 0.8) - 1, 50) # Ensure K isn't too large for dataset
        if limit_k < 2:
            return {}

        results = {"k": [], "accuracy": [], "std": []}
        
        # Use stratified folds
        cv = StratifiedKFold(n_splits=min(folds, n_samples // 2), shuffle=True, random_state=42)
        
        best_k = 1
        best_score = -1.0
        
        for k in range(1, limit_k + 1):
            knn = KNeighborsClassifier(n_neighbors=k)
            scores = cross_val_score(knn, X, y, cv=cv, scoring='accuracy')
            mean_score = scores.mean()
            
            results["k"].append(k)
            results["accuracy"].append(mean_score)
            results["std"].append(scores.std())
            
            if mean_score > best_score:
                best_score = mean_score
                best_k = k
                
        results["best_k"] = best_k
        results["best_accuracy"] = best_score
        return results

    def _generate_k_plot(self, results: dict) -> dict:
        """Generate Plotly chart for K-value optimization."""
        if not results:
            return {}
            
        return {
            "data": [
                {
                    "x": results["k"],
                    "y": results["accuracy"],
                    "type": "scatter",
                    "mode": "lines+markers",
                    "name": "CV Accuracy",
                    "line": {"color": "#1f77b4"},
                    "error_y": {
                        "type": "data",
                        "array": results["std"],
                        "visible": True,
                        "color": "#1f77b4",
                        "opacity": 0.3
                    }
                },
                # Highlight Best K
                {
                    "x": [results["best_k"]],
                    "y": [results["best_accuracy"]],
                    "mode": "markers",
                    "name": f"Best K ({results['best_k']})",
                    "marker": {"size": 12, "color": "red", "symbol": "star"}
                }
            ],
            "layout": {
                "title": "K-Value Parameter Tuning",
                "xaxis": {"title": "Number of Neighbors (k)"},
                "yaxis": {"title": "Cross-Validation Accuracy"},
                "hovermode": "closest"
            }
        }


    
    def _generate_decision_boundary_plot(self, X_2d, y, classes, n_neighbors=5, weights='uniform'):
        """
        Generate decision boundary visualization for 2D data (or PCA-reduced).
        """
        from sklearn.neighbors import KNeighborsClassifier
        
        # Train shadow model on just these 2 dimensions
        clf = KNeighborsClassifier(n_neighbors=n_neighbors, weights=weights)
        clf.fit(X_2d, y)
        
        # Create meshgrid
        x_min, x_max = X_2d[:, 0].min() - 1, X_2d[:, 0].max() + 1
        y_min, y_max = X_2d[:, 1].min() - 1, X_2d[:, 1].max() + 1
        h = max((x_max - x_min) / 100, (y_max - y_min) / 100) # Resolution
        
        xx, yy = np.meshgrid(np.arange(x_min, x_max, h),
                             np.arange(y_min, y_max, h))
        
        # Predict mesh points
        Z = clf.predict(np.c_[xx.ravel(), yy.ravel()])
        
        # Convert class labels to integers for contour plot
        # Create map from class label to integer
        unique_classes = np.unique(y)
        class_to_int = {c: i for i, c in enumerate(unique_classes)}
        
        Z_int = np.array([class_to_int[z] for z in Z])
        Z_int = Z_int.reshape(xx.shape)
        y_int = np.array([class_to_int[label] for label in y])

        # Create Plotly traces
        data = []
        
        # 1. Decision Regions (Contour)
        data.append({
            "type": "contour",
            "x": np.arange(x_min, x_max, h).tolist(),
            "y": np.arange(y_min, y_max, h).tolist(),
            "z": Z_int.tolist(),
            "showscale": False,
            "opacity": 0.4,
            "colorscale": "Viridis",
            "hoverinfo": "none",
            "contours": {"coloring": "heatmap"}
        })
        
        # 2. Scatter Points (Actual Data)
        for i, cls in enumerate(unique_classes):
             mask = (y == cls)
             data.append({
                 "type": "scatter",
                 "x": X_2d[mask, 0].tolist(),
                 "y": X_2d[mask, 1].tolist(),
                 "mode": "markers",
                 "name": str(cls),
                 "marker": {
                     "size": 8,
                     "line": {"width": 1, "color": "white"}
                 }
             })
             
        return {
            "data": data,
            "layout": {
                "title": f"Decision Boundary (k={n_neighbors})",
                "xaxis": {"title": "Component 1"},
                "yaxis": {"title": "Component 2"},
                "legend": {"title": {"text": "Classes"}}
            }
        }


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
    )

    async def execute(self, X: NDDataset = None, y: Any = None, **kwargs) -> Any:
        """
        Execute SIMCA classification.

        Args:
            X: NDDataset containing feature data
            y: Class labels

        Returns:
            SIMCA model with classification results
        """
        from spectra_sherpa.app.lib.scp_compat import scp
        from scipy.stats import f

        # Handle both positional and keyword arguments
        if X is None and "input_0" in kwargs:
            X = kwargs["input_0"]
        if y is None and "input_1" in kwargs:
            y = kwargs["input_1"]

        if X is None:
            raise ValueError("Missing required input: X (features)")
        if not isinstance(X, (NDDataset, AnalysisDataset)):
            raise ValueError("X must be an NDDataset or AnalysisDataset object")

        # Auto-extract labels from dataset
        # Case 1: y is None - extract from X
        # Case 2: y is dataset - extract embedded labels from y
        # Case 3: y is array/list - use directly
        if y is None:
            logger.debug("No y input provided - extracting labels from X")
            # First: check for explicit target attribute (sklearn datasets store
            # class labels in AnalysisDataset.target, separate from the y-axis)
            _target = getattr(X, "target", None)
            if _target is not None:
                _tarr = np.asarray(_target)
                if _tarr.size > 0:
                    y = _tarr
                    logger.debug("Auto-extracted class labels from X.target")

            if y is None:
                y_coord = safe_get_coord(X, 'y')
                if y_coord is not None:
                    # Extract labels from X's y-axis (prefer labels over data)
                    if hasattr(y_coord, 'labels') and y_coord.labels is not None:
                        y = y_coord.labels
                        logger.debug("Auto-extracted class labels from X.y.labels")
                    elif hasattr(y_coord, 'data') and y_coord.data is not None and np.array(y_coord.data).size > 0:
                        y = y_coord.data
                        logger.debug("Auto-extracted class labels from X.y.data")
                    else:
                        raise ValueError(
                            "Dataset has y-axis but no labels or data found. "
                            "Please provide class labels explicitly via the 'y' input port."
                        )
                else:
                    raise ValueError(
                        "Missing required input: y (class labels)\n"
                        "Either provide labels via the 'y' input port, or use a dataset with labels in X.y"
                    )
        elif isinstance(y, (NDDataset, AnalysisDataset)):
            # If y IS a dataset, extract embedded labels (don't use the dataset itself)
            logger.debug("y is dataset - extracting embedded labels")
            y_coord = safe_get_coord(y, 'y')
            if y_coord is not None:
                # Extract from y's own y-axis
                if hasattr(y_coord, 'labels') and y_coord.labels is not None:
                    y = y_coord.labels
                    logger.debug("Extracted labels from y.y.labels")
                elif hasattr(y_coord, 'data') and y_coord.data is not None and np.array(y_coord.data).size > 0:
                    y = y_coord.data
                    logger.debug("Extracted labels from y.y.data")
                else:
                    raise ValueError(
                        "Dataset passed to y port has no embedded labels. "
                        "Use the y-axis coordinate to store class labels."
                    )
            else:
                raise ValueError(
                    "Dataset passed to y port has no y-axis coordinate. "
                    "Cannot extract class labels."
                )

        # Convert to numpy arrays
        X_data = np.array(X.data)
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
                raise ValueError(f"Class {cls} has {n_class_samples} samples but needs at least {n_components + 1} for SIMCA")

            # Build PCA model for this class
            X_class_dataset = scp.NDDataset(X_class)
            pca = scp.PCA(n_components=n_components, standardized=False, scaled=True)
            pca.fit(X_class_dataset)

            # Get scores and loadings
            scores = pca.transform()
            scores_data = np.array(scores.data) if hasattr(scores, "data") else np.array(scores)
            loadings_data = np.array(pca.components.data) if hasattr(pca.components, "data") else np.array(pca.components)

            # Get class mean for proper projection of new samples
            # CRITICAL: PCA centers data, so we need the mean to project new samples correctly
            class_mean = np.mean(X_class, axis=0)

            # Calculate T² limit using CORRECT eigenvalues from PCA model
            # CRITICAL: Use pca.explained_variance (eigenvalues), NOT score variance
            # Reference: Nomikos & MacGregor (1995), Technometrics
            explained_var = np.array(pca.explained_variance.data) if hasattr(pca.explained_variance, "data") else np.array(pca.explained_variance)
            eigenvalues = np.maximum(explained_var.flatten()[:n_components], 1e-10)

            alpha = 1 - confidence_level
            df2 = n_class_samples - n_components
            # Ensure df2 > 0 (should be guaranteed by check above, but defensive)
            if df2 <= 0:
                df2 = 1
            F_crit = f.ppf(1 - alpha, n_components, df2)
            T2_limit = (n_components * (n_class_samples - 1) * (n_class_samples + 1)) / \
                       (n_class_samples * df2) * F_crit

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
                t = np.array(sample_scores.data).flatten() if hasattr(sample_scores, "data") else np.array(sample_scores).flatten()

                # Calculate T² distance
                T2 = np.sum((t ** 2) / eigenvalues)

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
        from sklearn.metrics import confusion_matrix, classification_report, accuracy_score

        train_accuracy = accuracy_score(y_array, predictions)
        cm = confusion_matrix(y_array, predictions, labels=classes)
        class_report = classification_report(y_array, predictions, target_names=[str(c) for c in classes], output_dict=True)

        # For visualization: project all samples into first class model's PC space
        # This provides a meaningful reduced-dimension view of the data
        first_class = classes[0]
        first_model = class_models[first_class]
        first_pca = first_model["pca"]

        # Project all samples into first class PC space for visualization
        viz_scores = first_pca.transform(scp.NDDataset(X_data))
        viz_scores_data = np.array(viz_scores.data) if hasattr(viz_scores, "data") else np.array(viz_scores)

        logger.debug("Visualization: projecting all samples into class '%s' PC space", first_class)

        # Create serializable version of class models (exclude PCA objects)
        # CRITICAL: Include class_mean for projecting new samples in SIMCAPredictNode
        serializable_models = {
            str(cls): {
                "scores": model["scores"].tolist() if hasattr(model["scores"], "tolist") else model["scores"],
                "loadings": model["loadings"].tolist() if hasattr(model["loadings"], "tolist") else model["loadings"],
                "eigenvalues": model["eigenvalues"].tolist() if hasattr(model["eigenvalues"], "tolist") else model["eigenvalues"],
                "class_mean": model["class_mean"].tolist() if hasattr(model["class_mean"], "tolist") else model["class_mean"],
                "n_samples": model["n_samples"],
            }
            for cls, model in class_models.items()
        }

        # Get unique categories from the classes already computed
        label_categories = [str(c) for c in classes]

        # Get input coordinates for NDDataset creation
        _y_coord = safe_get_coord(X, 'y')

        # Generate plots
        plots = {}
        plots["confusion_matrix"] = generate_confusion_matrix_heatmap(
            cm, classes, "Confusion Matrix (Training Set)"
        )

        # =====================================================================
        # Create NDDataset output with proper coordinate coupling
        # =====================================================================

        # Build PC labels for the visualization scores (projected into first class PC space)
        pc_labels = [f"PC{i+1} (Class {first_class})" for i in range(n_components)]

        # Scores NDDataset: shape (n_samples, n_components) — projected into first class PC space
        scores_dataset = _create_spectral_dataset(
            data=viz_scores_data,
            x_coord=_make_labeled_coord(pc_labels, title="Principal Component"),
            y_coord=_y_coord,  # Preserve sample labels from input
            units="score",
            title="SIMCA Scores",
        )

        # Add processing history
        copy_processing_history(X, scores_dataset)
        add_processing_step(
            scores_dataset,
            "classification.simca.scores",
            {"n_components": n_components},
            node_id=self.node_id,
        )

        # Store ONLY scientific metadata that coordinates can't carry
        scores_dataset.meta.update({
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
        })

        logger.debug("Train accuracy: %.3f with %d PCs per class", train_accuracy, n_components)

        # NDDataset-only return: one serialization boundary at API layer
        return {
            "default": scores_dataset,          # NDDataset: viz scores + sample labels (y) + PC coords (x)
            "model": serializable_models,        # Model port: class models dict for SIMCA Predict
            "plots": plots,                      # Pre-built Plotly traces (legitimate visualization output)
        }


@register_node
class PLSDAPredictNode(Node):
    """
    Apply trained PLS-DA model to predict class labels for new samples.
    
    Takes new spectral data and a trained PLS-DA model, returns predicted
    class labels and probabilities. Enables train/test workflows and
    production inference.
    """
    
    metadata = NodeMetadata(
        node_type="classification.plsda_predict",
        category="classification",
        label="Apply PLS-DA Model",
        description="Apply trained PLS-DA model to classify new spectra",
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
                label="PLS-DA Model",
                description="Trained PLS-DA model from training node",
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
                label="Class Probabilities",
                description="Predicted class probabilities",
            ),
        ],
        input_types=["NDDataset", "dict"],
        output_type="dict",
        requires_scp=True,
    )

    async def execute(self, X_new: Any = None, model: Any = None, **kwargs: Any) -> dict[str, Any]:
        """
        Apply PLS-DA model to new data.

        Args:
            X_new: New spectral data (NDDataset or array)
            model: Trained PLS-DA model dict from training node

        Returns:
            Dict with predicted classes and probabilities
        """
        if X_new is None:
            raise ValueError("Missing required input: X_new (new spectra)")
        if model is None:
            raise ValueError("Missing required input: model (trained PLS-DA model)")

        # Extract model components from result dict
        if isinstance(model, dict):
            pls_model = model.get("model")
            classes = np.array(model.get("classes", []))
            n_classes = model.get("n_classes", 2)
        else:
            raise ValueError("Model must be a dict containing PLS-DA model and metadata")

        if pls_model is None:
            raise ValueError("Model dict does not contain 'model' key with trained PLS-DA model")

        # X_new can be NDDataset or AnalysisDataset
        X_array = np.array(X_new.data)

        # Make predictions
        # PLS-DA returns continuous predictions for each class (dummy variables)
        # SpectroChemPy PLS model requires NDDataset input
        from spectra_sherpa.app.lib.scp_compat import scp
        from scipy.special import softmax
        X_dataset = scp.NDDataset(X_array)
        Y_pred_raw = pls_model.predict(X_dataset)
        Y_pred_raw_np = np.array(Y_pred_raw.data) if hasattr(Y_pred_raw, "data") else np.array(Y_pred_raw)

        # Validate prediction shape before argmax
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

        # CRITICAL: Apply softmax to convert raw PLS outputs to proper probabilities
        Y_pred_prob = softmax(Y_pred_raw_np, axis=1)

        # Convert to class labels (argmax of probabilities)
        y_pred = classes[np.argmax(Y_pred_prob, axis=1)]

        return {
            "y_pred": y_pred.tolist(),
            "y_prob": Y_pred_prob.tolist(),
        }


@register_node
class KNNPredictNode(Node):
    """
    Apply trained KNN model to predict class labels for new samples.
    
    Takes new feature data and a trained KNN model, returns predicted
    class labels and probabilities. Useful for test set evaluation and
    production inference.
    """
    
    metadata = NodeMetadata(
        node_type="classification.knn_predict",
        category="classification",
        label="Apply KNN Model",
        description="Apply trained KNN model to classify new data",
        parameters=[],
        input_ports=[
            PortMetadata(
                name="X_new",
                type_ref="spectrasherpa://types/SpectralDataset/1.0",
                required=True,
                label="New Features",
                description="New feature data to classify (spectra or scores)",
            ),
            PortMetadata(
                name="model",
                type_ref="spectrasherpa://types/ClassificationModel/1.0",
                required=True,
                label="KNN Model",
                description="Trained KNN model from training node",
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
                label="Class Probabilities",
                description="Predicted class probabilities",
            ),
        ],
        input_types=["NDDataset", "dict"],
        output_type="dict",
    )
    
    async def execute(self, X_new: Any = None, model: Any = None, **kwargs: Any) -> dict[str, Any]:
        """
        Apply KNN model to new data.
        
        Args:
            X_new: New feature data (NDDataset or array)
            model: Trained KNN model dict from training node
            
        Returns:
            Dict with predicted classes and probabilities
        """
        if X_new is None:
            raise ValueError("Missing required input: X_new (new features)")
        if model is None:
            raise ValueError("Missing required input: model (trained KNN model)")
        
        # Extract model from result dict
        if isinstance(model, dict):
            knn_model = model.get("model")
            classes = np.array(model.get("classes", []))
        else:
            raise ValueError("Model must be a dict containing KNN model and metadata")
        
        if knn_model is None:
            raise ValueError("Model dict does not contain 'model' key with trained KNN model")

        # X_new is NDDataset or AnalysisDataset directly
        if not isinstance(X_new, (NDDataset, AnalysisDataset)):
            raise ValueError("X_new must be an NDDataset or AnalysisDataset object")
        X_array = np.array(X_new.data)

        # Make predictions
        y_pred = knn_model.predict(X_array)
        y_prob = knn_model.predict_proba(X_array)

        return {
            "y_pred": y_pred.tolist(),
            "y_prob": y_prob.tolist(),
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

        # X_new is NDDataset or AnalysisDataset directly
        if not isinstance(X_new, (NDDataset, AnalysisDataset)):
            raise ValueError("X_new must be an NDDataset or AnalysisDataset object")
        X_array = np.array(X_new.data)

        # Ensure 2D
        if X_array.ndim == 1:
            X_array = X_array.reshape(1, -1)

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
                T2 = np.sum((scores ** 2) / eigenvalues)

                # Calculate Q (SPE - Squared Prediction Error)
                reconstructed = scores @ loadings  # shape: (n_features,)
                residual = centered_sample - reconstructed
                Q = np.sum(residual ** 2)

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
