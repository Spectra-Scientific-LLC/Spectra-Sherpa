"""
K-Nearest Neighbors classification nodes.
"""

from __future__ import annotations

import logging
from typing import Any

import numpy as np

from spectra_sherpa.app.lib.adapters.scp_extractors import KNNExtract
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
    classification_metrics_contract as _classification_metrics_contract,
)
from .core_utils import (
    classification_scalar_metrics as _classification_scalar_metrics,
)
from .core_utils import (
    make_labeled_coord as _make_labeled_coord,
)
from .core_utils import (
    prepare_class_labels as _prepare_class_labels,
)

logger = logging.getLogger(__name__)


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
        label="Train KNN Classifier",
        description="Train a K-Nearest Neighbors classifier",
        parameters=[
            NodeParameter(
                name="n_neighbors",
                label="Number of Neighbors (k)",
                param_type="number",
                default=5,
                min_value=1,
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
                name="scale",
                label="Autoscale Features",
                param_type="boolean",
                default=True,
                description=(
                    "Standardize variables before distance calculations. Disable only when upstream scores "
                    "or features are already on the intended scale."
                ),
                required=False,
            ),
            NodeParameter(
                name="cv_folds",
                label="Cross-Validation Folds",
                param_type="number",
                default=5,
                min_value=2,
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
                type_ref="spectrasherpa://types/Array2D/1.0",
                required=True,
                label="Features (X)",
                description="Feature matrix (spectral data or scores)",
                accepted_data_roles=["X_spectra", "X_features"],
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
                name="default",
                type_ref="spectrasherpa://types/ScoreMatrix/1.0",
                required=True,
                label="Sample Coordinates",
                description="Original feature coordinates or PCA-reduced sample coordinates for plotting",
            ),
            PortMetadata(
                name="model",
                type_ref="spectrasherpa://types/ClassificationModel/1.0",
                required=True,
                label="Fitted KNN Classifier",
                description="Fitted K-Nearest Neighbors classifier produced by this training node",
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
                name="class_probabilities",
                type_ref="spectrasherpa://types/Array2D/1.0",
                required=True,
                label="Class Probabilities",
                description="Alias of probabilities for direct model comparison",
            ),
            PortMetadata(
                name="metrics",
                type_ref="spectrasherpa://types/Any/1.0",
                required=False,
                label="Classification Metrics",
                description="Canonical train/CV/test classification metrics for run history, comparison, and guidance",
            ),
            PortMetadata(
                name="distances",
                type_ref="spectrasherpa://types/Array2D/1.0",
                required=True,
                label="Neighbor Distances",
                description="Nearest-neighbor distances for each training sample",
            ),
            PortMetadata(
                name="neighbor_indices",
                type_ref="spectrasherpa://types/Array2D/1.0",
                required=True,
                label="Neighbor Indices",
                description="Nearest-neighbor sample indices for each training sample",
            ),
            PortMetadata(
                name="train_accuracy",
                type_ref="spectrasherpa://types/Scalar/1.0",
                required=False,
                label="Training Accuracy",
                description="Classification accuracy on the training set",
            ),
            PortMetadata(
                name="cv_accuracy",
                type_ref="spectrasherpa://types/Scalar/1.0",
                required=False,
                label="CV Accuracy",
                description="Mean cross-validation accuracy",
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

    def generate_python(
        self,
        inputs: dict[str, str],
        indent: str = "    ",
        use_scp: bool = True,
    ) -> list[str]:
        """Generate Python export code for KNN classification."""
        params = self._resolve_params()
        n_neighbors = params.get("n_neighbors", 5)
        weights = params.get("weights", "uniform")
        metric = params.get("metric", "euclidean")
        scale = bool(params.get("scale", True))
        cv_folds = params.get("cv_folds", 5)

        X_expr = inputs.get("X", inputs.get("default", "input_data"))
        y_expr = inputs.get("y")

        lines: list[str] = []
        lines.append(f"{indent}# --- KNN Classifier ({self.node_id}) ---")

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

        # KNN uses sklearn regardless of use_scp
        lines.append(f"{indent}from sklearn.metrics import confusion_matrix")
        lines.append(f"{indent}from sklearn.model_selection import StratifiedKFold, cross_val_predict, cross_val_score")
        lines.append(f"{indent}from sklearn.neighbors import KNeighborsClassifier")
        lines.append(f"{indent}from sklearn.pipeline import Pipeline")
        lines.append(f"{indent}from sklearn.preprocessing import StandardScaler")
        lines.append(f"{indent}from spectra_sherpa.app.services.dag.nodes.classification.core_utils import (")
        lines.append(f"{indent}    classification_metrics_contract,")
        lines.append(f"{indent}    classification_scalar_metrics,")
        lines.append(f"{indent})")
        lines.append(
            f"{indent}_knn_estimator = KNeighborsClassifier("
            f"n_neighbors={n_neighbors}, weights='{weights}', metric='{metric}')"
        )
        if scale:
            lines.append(f"{indent}_knn = Pipeline([('scale', StandardScaler()), ('knn', _knn_estimator)])")
        else:
            lines.append(f"{indent}_knn = _knn_estimator")
        lines.append(f"{indent}_knn.fit(_X_data, _y_labels)")
        lines.append(f"{indent}_pred = _knn.predict(_X_data)")
        lines.append(f"{indent}_probs = _knn.predict_proba(_X_data)")
        if scale:
            lines.append(f"{indent}_knn_query = _knn.named_steps['scale'].transform(_X_data)")
            lines.append(
                f"{indent}_distances, _neighbor_indices = "
                "_knn.named_steps['knn'].kneighbors(_knn_query, return_distance=True)"
            )
        else:
            lines.append(f"{indent}_distances, _neighbor_indices = _knn.kneighbors(_X_data, return_distance=True)")
        lines.append(f"{indent}_sample_coordinates = _X_data")
        lines.append(f"{indent}_accuracy = np.mean(_pred == _y_labels)")
        if scale:
            lines.append(f"{indent}_classes = list(_knn.named_steps['knn'].classes_)")
        else:
            lines.append(f"{indent}_classes = list(_knn.classes_)")
        lines.append(f"{indent}_class_counts = np.array([np.sum(_y_labels == _cls) for _cls in _classes])")
        lines.append(f"{indent}_cv_folds = int({cv_folds})")
        lines.append(f"{indent}if _cv_folds > int(_class_counts.min()):")
        lines.append(
            f"{indent}    raise ValueError(f'cv_folds must be <= smallest class count "
            f"({{int(_class_counts.min())}}). Got {{_cv_folds}}.')"
        )
        lines.append(f"{indent}_cv = StratifiedKFold(n_splits=_cv_folds, shuffle=True, random_state=42)")
        lines.append(f"{indent}_y_pred_cv = cross_val_predict(_knn, _X_data, _y_labels, cv=_cv)")
        lines.append(
            f"{indent}_y_prob_cv = cross_val_predict(" "_knn, _X_data, _y_labels, cv=_cv, method='predict_proba')"
        )
        lines.append(f"{indent}_cv_scores = cross_val_score(_knn, _X_data, _y_labels, cv=_cv)")
        lines.append(
            f"{indent}_train_metrics = classification_scalar_metrics(_y_labels, _pred, _classes, prefix='train_')"
        )
        lines.append(
            f"{indent}_cv_metrics = classification_scalar_metrics(_y_labels, _y_pred_cv, _classes, prefix='cv_')"
        )
        lines.append(f"{indent}_cv_metrics['cv_accuracy'] = float(_cv_scores.mean())")
        lines.append(f"{indent}_cm_train = confusion_matrix(_y_labels, _pred, labels=_classes)")
        lines.append(f"{indent}_cm_cv = confusion_matrix(_y_labels, _y_pred_cv, labels=_classes)")
        lines.append(f"{indent}_classification_metrics = classification_metrics_contract(")
        lines.append(f"{indent}    classes=_classes,")
        lines.append(f"{indent}    train_metrics=_train_metrics,")
        lines.append(f"{indent}    cv_metrics=_cv_metrics,")
        lines.append(f"{indent}    primary_split='cv',")
        lines.append(f"{indent}    method='knn',")
        lines.append(f"{indent}    confusion_matrices={{'train': _cm_train.tolist(), 'cv': _cm_cv.tolist()}},")
        lines.append(f"{indent})")
        lines.append(f"{indent}_cm_labels = [str(c) for c in _classes]")
        lines.append(f"{indent}_cm_train_plot = {{")
        lines.append(
            f"{indent}    'data': [{{'type': 'heatmap', 'z': _cm_train.tolist(), " "'x': _cm_labels, 'y': _cm_labels}],"
        )
        lines.append(f"{indent}    'layout': {{'title': 'Confusion Matrix (Training)'}},")
        lines.append(f"{indent}}}")
        lines.append(f"{indent}_cm_cv_plot = {{")
        lines.append(
            f"{indent}    'data': [{{'type': 'heatmap', 'z': _cm_cv.tolist(), " "'x': _cm_labels, 'y': _cm_labels}],"
        )
        lines.append(f"{indent}    'layout': {{'title': 'Confusion Matrix (Cross-Validation)'}},")
        lines.append(f"{indent}}}")
        lines.append(f'{indent}print(f"  KNN (k={n_neighbors}, weights={weights}): accuracy={{_accuracy:.4f}}")')

        # Store result
        lines.append(f"{indent}results['{self.node_id}'] = {{")
        lines.append(f"{indent}    'default': _sample_coordinates,")
        lines.append(f"{indent}    'model': {{'model': _knn, 'type': 'knn'}},")
        lines.append(f"{indent}    'predictions': _pred,")
        lines.append(f"{indent}    'probabilities': _probs,")
        lines.append(f"{indent}    'class_probabilities': _probs,")
        lines.append(f"{indent}    'y_prob': _y_prob_cv,")
        lines.append(f"{indent}    'distances': _distances,")
        lines.append(f"{indent}    'neighbor_indices': _neighbor_indices,")
        lines.append(f"{indent}    'train_accuracy': float(_accuracy),")
        lines.append(f"{indent}    'cv_accuracy': float(_cv_scores.mean()),")
        lines.append(f"{indent}    'confusion_matrix': _cm_cv,")
        lines.append(f"{indent}    'confusion_matrix_train': _cm_train,")
        lines.append(f"{indent}    'confusion_matrix_cv': _cm_cv,")
        lines.append(f"{indent}    'metrics': {{")
        lines.append(f"{indent}        **_train_metrics,")
        lines.append(f"{indent}        **_cv_metrics,")
        lines.append(f"{indent}        'classification_metrics': _classification_metrics,")
        lines.append(f"{indent}    }},")
        lines.append(
            f"{indent}    'metadata': {{'y_true': _y_labels.tolist(), 'y_pred': _pred.tolist(), "
            f"'y_pred_cv': _y_pred_cv.tolist(), 'label_categories': [str(c) for c in _classes]}},"
        )
        lines.append(
            f"{indent}    'plots': {{'confusion_matrix_train': _cm_train_plot, "
            f"'confusion_matrix_cv': _cm_cv_plot}},"
        )
        lines.append(f"{indent}}}")

        return lines

    async def execute(self, X: Any = None, y: Any = None, **kwargs) -> Any:
        """
        Execute KNN classification.

        Args:
            X: NDDataset containing feature data
            y: Class labels

        Returns:
            KNN model with classification results
        """
        from sklearn.metrics import classification_report, confusion_matrix
        from sklearn.model_selection import cross_val_predict, cross_val_score
        from sklearn.neighbors import KNeighborsClassifier
        from sklearn.pipeline import Pipeline
        from sklearn.preprocessing import StandardScaler

        X = bind_X(
            X,
            missing_message="Missing required input: X (features)",
            dataset_error_message="X must be an dataset object",
            allow_array=False,
        )
        y = bind_y(
            y,
            X=X,
            required=True,
            infer_from_X=True,
            target_type="categorical",
            missing_message=(
                "Missing required input: y (class labels)\n"
                "Either provide labels via the 'y' input port, or use an NDDataset with labels in X.y"
            ),
            dataset_missing_message=(
                "NDDataset passed to y port has no embedded labels. " "Use the y-axis coordinate to store class labels."
            ),
        )

        # Convert to numpy arrays
        X_data = to_numpy_2d(X, name="X", dtype=np.float64)
        y_array = _prepare_class_labels(y, X_data.shape[0])

        # Get parameters
        n_neighbors = self.parameters.get("n_neighbors", 5)
        weights = self.parameters.get("weights", "uniform")
        metric = self.parameters.get("metric", "euclidean")
        scale = bool(self.parameters.get("scale", True))
        cv_folds = self.parameters.get("cv_folds", 5)

        # Get unique classes
        classes = np.unique(y_array)
        n_classes = len(classes)

        if n_classes < 2:
            raise ValueError(f"Need at least 2 classes, got {n_classes}")

        # Fit KNN model
        knn_estimator = KNeighborsClassifier(n_neighbors=n_neighbors, weights=weights, metric=metric, algorithm="auto")
        knn = Pipeline([("scale", StandardScaler()), ("knn", knn_estimator)]) if scale else knn_estimator
        knn.fit(X_data, y_array)

        # Make predictions on training data
        y_pred_train = knn.predict(X_data)
        _y_pred_prob_train = knn.predict_proba(X_data)
        if scale:
            X_model_space = knn.named_steps["scale"].transform(X_data)
            neighbor_distances, neighbor_indices = knn.named_steps["knn"].kneighbors(
                X_model_space, n_neighbors=n_neighbors, return_distance=True
            )
        else:
            X_model_space = X_data
            neighbor_distances, neighbor_indices = knn.kneighbors(X_data, n_neighbors=n_neighbors, return_distance=True)

        # Cross-validation predictions with stratified folds
        from sklearn.model_selection import StratifiedKFold

        cv_splitter = StratifiedKFold(n_splits=cv_folds, shuffle=True, random_state=42)
        y_pred_cv = cross_val_predict(knn, X_data, y_array, cv=cv_splitter)
        # Get CV probabilities using method='predict_proba'
        _y_pred_prob_cv = cross_val_predict(knn, X_data, y_array, cv=cv_splitter, method="predict_proba")
        cv_scores = cross_val_score(knn, X_data, y_array, cv=cv_splitter)

        # Calculate metrics
        train_metrics = _classification_scalar_metrics(y_array, y_pred_train, classes, prefix="train_")
        cv_metrics = _classification_scalar_metrics(y_array, y_pred_cv, classes, prefix="cv_")
        train_accuracy = train_metrics["train_accuracy"]
        cv_accuracy = float(cv_scores.mean())
        cv_metrics["cv_accuracy"] = cv_accuracy

        # Confusion matrices
        cm_train = confusion_matrix(y_array, y_pred_train, labels=classes)
        cm_cv = confusion_matrix(y_array, y_pred_cv, labels=classes)
        classification_metrics = _classification_metrics_contract(
            classes=classes,
            train_metrics=train_metrics,
            cv_metrics=cv_metrics,
            primary_split="cv",
            method="knn",
            confusion_matrices={
                "train": cm_train.tolist(),
                "cv": cm_cv.tolist(),
            },
            extra={
                "cv_method": f"stratified-k-fold (k={cv_folds})",
                "n_neighbors": int(n_neighbors),
                "distance_metric": str(metric),
                "weights": str(weights),
                "scale": bool(scale),
            },
        )

        # Classification report
        class_report = classification_report(
            y_array, y_pred_cv, target_names=[str(c) for c in classes], output_dict=True
        )

        # Get unique categories from the classes already computed
        label_categories = [str(c) for c in classes]

        # Get input coordinates for NDDataset creation
        _x_coord = X.feature_axis
        _y_coord = X.sample_axis

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

            logger.debug(
                "High-dimensional data (%d features) - computed PCA for visualization (%d PCs)",
                n_features,
                n_viz_components,
            )
        else:
            # Low-dimensional data, use as-is
            viz_labels = [f"Feature {i+1}" for i in range(n_features)]
            logger.debug("Low-dimensional data (%d features) - using original features for visualization", n_features)

        # --- K-Value Optimization ---
        # Run a quick search for optimal K to guide the user
        k_tuning_results = self._optimize_k(X_data, y_array, max_k=20, folds=cv_folds, scale=scale)

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
                weights=weights,
            )
        except Exception as e:
            logger.warning("Failed to generate decision boundary plot: %s", e)

        # =====================================================================
        # Create NDDataset output with proper coordinate coupling
        # =====================================================================

        # KNN doesn't have scores/loadings — use viz_data (PCA-reduced or original features)
        # as the primary output for the "default" port
        scores_dataset = create_spectral_dataset(
            data=viz_data,
            x_coord=_make_labeled_coord(viz_labels, title="Feature"),
            y_coord=_y_coord,  # Preserve sample labels from input
            units="score",
            title="KNN Sample Coordinates",
            data_role="X_features",
        )

        # Add processing history
        copy_processing_history(X, scores_dataset)
        add_processing_step(
            scores_dataset,
            "classification.knn.scores",
            {"n_neighbors": n_neighbors},
            node_id=self.node_id,
        )

        # Propagate dataset-level flags. Visualization scores rows are
        # samples (one per input row), so sample-axis flags carry through.
        # Origin tags survive on every output.
        inherit_sample_flags(X, scores_dataset)
        inherit_origin_flags(X, scores_dataset)

        # Store ONLY scientific metadata that coordinates can't carry
        scores_dataset.meta.update(
            {
                "type": "KNN",
                "n_neighbors": n_neighbors,
                "label_categories": label_categories,
                "pc_labels": viz_labels,
                "train_accuracy": train_accuracy,
                "cv_accuracy": cv_accuracy,
                "train_balanced_accuracy": train_metrics["train_balanced_accuracy"],
                "cv_balanced_accuracy": cv_metrics["cv_balanced_accuracy"],
                "train_f1_macro": train_metrics["train_f1_macro"],
                "cv_f1_macro": cv_metrics["cv_f1_macro"],
                "train_precision_macro": train_metrics["train_precision_macro"],
                "cv_precision_macro": cv_metrics["cv_precision_macro"],
                "train_recall_macro": train_metrics["train_recall_macro"],
                "cv_recall_macro": cv_metrics["cv_recall_macro"],
                "train_sensitivity_macro": train_metrics["train_sensitivity_macro"],
                "cv_sensitivity_macro": cv_metrics["cv_sensitivity_macro"],
                "train_specificity_macro": train_metrics["train_specificity_macro"],
                "cv_specificity_macro": cv_metrics["cv_specificity_macro"],
                "confusion_matrix_train": cm_train.tolist(),
                "confusion_matrix_cv": cm_cv.tolist(),
                "metrics": classification_metrics,
                "classification_report": class_report,
                "y_true": y_array.tolist(),
                "y_pred": y_pred_train.tolist(),
                "y_pred_cv": y_pred_cv.tolist(),
                "optimal_k": k_tuning_results.get("best_k") if k_tuning_results else None,
                "quality_summary": {
                    "train_accuracy": float(train_accuracy),
                    "cv_accuracy": float(cv_accuracy),
                    "cv_balanced_accuracy": float(cv_metrics["cv_balanced_accuracy"]),
                    "cv_f1_macro": float(cv_metrics["cv_f1_macro"]),
                    "cv_precision_macro": float(cv_metrics["cv_precision_macro"]),
                    "cv_recall_macro": float(cv_metrics["cv_recall_macro"]),
                    "cv_sensitivity_macro": float(cv_metrics["cv_sensitivity_macro"]),
                    "cv_specificity_macro": float(cv_metrics["cv_specificity_macro"]),
                    "n_neighbors": int(n_neighbors),
                    "metric": str(metric),
                    "scale": bool(scale),
                },
            }
        )

        logger.debug("Train accuracy: %.3f, CV accuracy: %.3f", train_accuracy, cv_accuracy)

        class_to_index = {cls: i for i, cls in enumerate(classes)}
        y_train_encoded = np.asarray([class_to_index[label] for label in y_array], dtype=np.int64)

        from ..modeling._artifact_builder import build_model_artifact

        artifact = build_model_artifact(
            KNNExtract(
                X_train=X_model_space,
                y_train_encoded=y_train_encoded,
                classes=label_categories,
                k=int(n_neighbors),
                metric=str(metric),
                weights=str(weights),
                x_mean=(
                    np.asarray(knn.named_steps["scale"].mean_, dtype=np.float64)
                    if scale
                    else np.zeros(X_data.shape[1], dtype=np.float64)
                ),
                x_scale=(
                    np.asarray(knn.named_steps["scale"].scale_, dtype=np.float64)
                    if scale
                    else np.ones(X_data.shape[1], dtype=np.float64)
                ),
            ),
            X,
            node_id=self.node_id,
            metrics={
                "train_accuracy": float(train_accuracy),
                "cv_accuracy": float(cv_accuracy),
                "train_balanced_accuracy": float(train_metrics["train_balanced_accuracy"]),
                "cv_balanced_accuracy": float(cv_metrics["cv_balanced_accuracy"]),
                "train_f1_macro": float(train_metrics["train_f1_macro"]),
                "cv_f1_macro": float(cv_metrics["cv_f1_macro"]),
                "train_precision_macro": float(train_metrics["train_precision_macro"]),
                "cv_precision_macro": float(cv_metrics["cv_precision_macro"]),
                "train_recall_macro": float(train_metrics["train_recall_macro"]),
                "cv_recall_macro": float(cv_metrics["cv_recall_macro"]),
                "train_sensitivity_macro": float(train_metrics["train_sensitivity_macro"]),
                "cv_sensitivity_macro": float(cv_metrics["cv_sensitivity_macro"]),
                "train_specificity_macro": float(train_metrics["train_specificity_macro"]),
                "cv_specificity_macro": float(cv_metrics["cv_specificity_macro"]),
                "classification_metrics": classification_metrics,
                "n_neighbors": int(n_neighbors),
                "metric": str(metric),
                "weights": str(weights),
                "scale": bool(scale),
            },
        )

        # NDDataset-only return: one serialization boundary at API layer
        return NodeResult(
            outputs={
                "default": scores_dataset,  # NDDataset: viz scores + sample labels (y) + feature coords (x)
                "model": {  # Wrapped model dict for ClassifierPredictNode
                    "model": knn,
                    "type": "knn",
                },
                "predictions": y_pred_cv.tolist(),
                "probabilities": _y_pred_prob_cv.tolist(),
                "class_probabilities": _y_pred_prob_cv.tolist(),
                "distances": neighbor_distances.tolist(),
                "neighbor_indices": neighbor_indices.tolist(),
                "metrics": classification_metrics,
                "train_accuracy": float(train_accuracy),
                "cv_accuracy": float(cv_accuracy),
                "cv_balanced_accuracy": float(cv_metrics["cv_balanced_accuracy"]),
                "cv_f1_macro": float(cv_metrics["cv_f1_macro"]),
                "cv_precision_macro": float(cv_metrics["cv_precision_macro"]),
                "cv_recall_macro": float(cv_metrics["cv_recall_macro"]),
                "cv_sensitivity_macro": float(cv_metrics["cv_sensitivity_macro"]),
                "cv_specificity_macro": float(cv_metrics["cv_specificity_macro"]),
                "plots": plots,  # Pre-built Plotly traces (legitimate visualization output)
                "_model_artifact": artifact,
            },
            diagnostics={
                "train_accuracy": train_accuracy,
                "cv_accuracy": cv_accuracy,
                "cv_balanced_accuracy": cv_metrics["cv_balanced_accuracy"],
                "cv_f1_macro": cv_metrics["cv_f1_macro"],
                "cv_precision_macro": cv_metrics["cv_precision_macro"],
                "cv_recall_macro": cv_metrics["cv_recall_macro"],
                "cv_sensitivity_macro": cv_metrics["cv_sensitivity_macro"],
                "cv_specificity_macro": cv_metrics["cv_specificity_macro"],
                "metrics": classification_metrics,
                "optimal_k": k_tuning_results.get("best_k") if k_tuning_results else None,
                "n_classes": len(classes),
            },
        )

    def _optimize_k(self, X, y, max_k=20, folds=5, scale: bool = True) -> dict:
        """
        Search for optimal K value using cross-validation.
        """
        from sklearn.model_selection import StratifiedKFold, cross_val_score
        from sklearn.neighbors import KNeighborsClassifier
        from sklearn.pipeline import Pipeline
        from sklearn.preprocessing import StandardScaler

        n_samples = len(y)
        limit_k = min(max_k, int(n_samples * 0.8) - 1, 50)  # Ensure K isn't too large for dataset
        if limit_k < 2:
            return {}

        results: dict[str, Any] = {"k": [], "accuracy": [], "std": []}

        # Use stratified folds
        cv = StratifiedKFold(n_splits=min(folds, n_samples // 2), shuffle=True, random_state=42)

        best_k = 1
        best_score = -1.0

        for k in range(1, limit_k + 1):
            estimator = KNeighborsClassifier(n_neighbors=k)
            knn = Pipeline([("scale", StandardScaler()), ("knn", estimator)]) if scale else estimator
            scores = cross_val_score(knn, X, y, cv=cv, scoring="accuracy")
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
                        "opacity": 0.3,
                    },
                },
                # Highlight Best K
                {
                    "x": [results["best_k"]],
                    "y": [results["best_accuracy"]],
                    "mode": "markers",
                    "name": f"Best K ({results['best_k']})",
                    "marker": {"size": 12, "color": "red", "symbol": "star"},
                },
            ],
            "layout": {
                "title": "K-Value Parameter Tuning",
                "xaxis": {"title": "Number of Neighbors (k)"},
                "yaxis": {"title": "Cross-Validation Accuracy"},
                "hovermode": "closest",
            },
        }

    def _generate_decision_boundary_plot(self, X_2d, y, classes, n_neighbors=5, weights="uniform"):
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
        h = max((x_max - x_min) / 100, (y_max - y_min) / 100)  # Resolution

        xx, yy = np.meshgrid(np.arange(x_min, x_max, h), np.arange(y_min, y_max, h))

        # Predict mesh points
        Z = clf.predict(np.c_[xx.ravel(), yy.ravel()])

        # Convert class labels to integers for contour plot
        # Create map from class label to integer
        unique_classes = np.unique(y)
        class_to_int = {c: i for i, c in enumerate(unique_classes)}

        Z_int = np.array([class_to_int[z] for z in Z])
        Z_int = Z_int.reshape(xx.shape)
        _y_int = np.array([class_to_int[label] for label in y])

        # Create Plotly traces
        data = []

        # 1. Decision Regions (Contour)
        data.append(
            {
                "type": "contour",
                "x": np.arange(x_min, x_max, h).tolist(),
                "y": np.arange(y_min, y_max, h).tolist(),
                "z": Z_int.tolist(),
                "showscale": False,
                "opacity": 0.4,
                "colorscale": "Viridis",
                "hoverinfo": "none",
                "contours": {"coloring": "heatmap"},
            }
        )

        # 2. Scatter Points (Actual Data)
        for i, cls in enumerate(unique_classes):
            mask = y == cls
            data.append(
                {
                    "type": "scatter",
                    "x": X_2d[mask, 0].tolist(),
                    "y": X_2d[mask, 1].tolist(),
                    "mode": "markers",
                    "name": str(cls),
                    "marker": {"size": 8, "line": {"width": 1, "color": "white"}},
                }
            )

        return {
            "data": data,
            "layout": {
                "title": f"Decision Boundary (k={n_neighbors})",
                "xaxis": {"title": "Component 1"},
                "yaxis": {"title": "Component 2"},
                "legend": {"title": {"text": "Classes"}},
            },
        }
