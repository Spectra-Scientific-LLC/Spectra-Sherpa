"""
SIMCA classification nodes.
"""

from __future__ import annotations

import logging
from typing import Any

import numpy as np

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
from .._chemometric_diagnostics import pomerantsev_dd_limit
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
            NodeParameter(
                name="critical_limits_method",
                label="Critical-Limits Method",
                param_type="select",
                default="ddmoments",
                options=["ddmoments", "classical"],
                description=(
                    "How T² and Q critical limits are computed for class membership. "
                    "'ddmoments' (default in v0.4.3+): Pomerantsev data-driven moments "
                    "(J. Chemom. 2008) — estimates effective degrees of freedom from the "
                    "calibration distribution; more robust on heavy-tailed Q and small classes. "
                    "'classical': F-distribution T² + χ² Q (Nomikos & MacGregor 1995, "
                    "Jackson & Mudholkar 1979) — the pre-v0.4.3 behaviour, kept for "
                    "reproducibility with legacy reports."
                ),
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
                name="model",
                type_ref="spectrasherpa://types/ClassificationModel/1.0",
                required=True,
                label="SIMCA Model",
                description="Serialized SIMCA classification model for downstream prediction",
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

    def generate_python(
        self,
        inputs: dict[str, str],
        indent: str = "    ",
        use_scp: bool = True,
    ) -> list[str]:
        """Generate Python export code for SIMCA classification."""
        if not use_scp:
            return [
                f"{indent}# --- SIMCA ({self.node_id}) ---",
                f"{indent}# SIMCA requires SpectroChemPy (pip install spectra-sherpa[scp])",
                f"{indent}raise ImportError('SIMCA requires spectrochempy')",
            ]

        params = self._resolve_params()
        n_components = params.get("n_components", 3)
        confidence_level = params.get("confidence_level", 0.95)

        X_expr = inputs.get("X", inputs.get("default", "input_data"))
        y_expr = inputs.get("y")

        lines: list[str] = []
        lines.append(f"{indent}# --- SIMCA ({self.node_id}) ---")

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

        # Build per-class PCA models via SCP
        lines.append(f"{indent}_classes = np.unique(_y_labels)")
        lines.append(f"{indent}_class_models = {{}}")
        lines.append(f"{indent}for _cls in _classes:")
        lines.append(f"{indent}    _mask = _y_labels == _cls")
        lines.append(f"{indent}    _X_cls = _X_data[_mask]")
        lines.append(f"{indent}    _ndd = scp.NDDataset(_X_cls)")
        lines.append(f"{indent}    _pca = scp.PCA(n_components={n_components}, standardized=False, scaled=True)")
        lines.append(f"{indent}    _pca.fit(_ndd)")
        lines.append(f"{indent}    _scores = np.asarray(_pca.transform().data, dtype=np.float64)")
        lines.append(f"{indent}    _loadings = np.asarray(_pca.components.data, dtype=np.float64)")
        lines.append(
            f"{indent}    _class_models[_cls] = {{"
            f"'pca': _pca, 'scores': _scores,"
            f" 'loadings': _loadings, 'mean': np.mean(_X_cls, axis=0)}}"
        )

        # Classify all samples
        lines.append(f"{indent}_predictions = []")
        lines.append(f"{indent}_distances = []")
        lines.append(f"{indent}for _i in range(len(_X_data)):")
        lines.append(f"{indent}    _sample = _X_data[_i]")
        lines.append(f"{indent}    _best_cls, _best_dist = None, float('inf')")
        lines.append(f"{indent}    _sample_distances = {{}}")
        lines.append(f"{indent}    for _cls in _classes:")
        lines.append(f"{indent}        _m = _class_models[_cls]")
        lines.append(f"{indent}        _centered = _sample - _m['mean']")
        lines.append(f"{indent}        _t = _centered @ _m['loadings'].T")
        lines.append(f"{indent}        _recon = _t @ _m['loadings']")
        lines.append(f"{indent}        _dist = np.sum((_centered - _recon) ** 2)")
        lines.append(f"{indent}        _sample_distances[str(_cls)] = float(_dist)")
        lines.append(f"{indent}        if _dist < _best_dist:")
        lines.append(f"{indent}            _best_cls, _best_dist = _cls, _dist")
        lines.append(f"{indent}    _predictions.append(_best_cls)")
        lines.append(f"{indent}    _distances.append(_sample_distances)")
        lines.append(f"{indent}_predictions = np.array(_predictions)")
        lines.append(f"{indent}_accuracy = np.mean(_predictions == _y_labels)")
        lines.append(
            f'{indent}print(f"  SIMCA ({n_components} PCs,'
            f" conf={confidence_level}):"
            f' accuracy={{_accuracy:.4f}} ({{len(_classes)}} classes)")'
        )

        # Store result — compute T²/Q limits for export (simplified)
        lines.append(f"{indent}_T2_limits = {{}}")
        lines.append(f"{indent}_Q_limits = {{}}")
        lines.append(f"{indent}for _cls in _classes:")
        lines.append(f"{indent}    _m = _class_models[_cls]")
        lines.append(f"{indent}    _n = _m['scores'].shape[0]")
        lines.append(f"{indent}    _eigvals = np.var(_m['scores'], axis=0) * _n")
        lines.append(f"{indent}    _T2_limits[str(_cls)] = float(np.sum(_eigvals) * 3.0)")
        lines.append(f"{indent}    _resid = _X_data[_y_labels == _cls] - np.mean(_X_data[_y_labels == _cls], axis=0)")
        lines.append(f"{indent}    _recon = (_resid @ _m['loadings'].T) @ _m['loadings']")
        lines.append(f"{indent}    _Q_limits[str(_cls)] = float(np.mean(np.sum((_resid - _recon) ** 2, axis=1)) * 3.0)")
        lines.append(f"{indent}results['{self.node_id}'] = {{")
        lines.append(f"{indent}    'model': {{")
        # Build class_models dict comprehension across multiple lines
        lines.append(f"{indent}        'class_models': {{")
        lines.append(f"{indent}            str(c): {{")
        lines.append(f"{indent}                'loadings': _class_models[c]['loadings'],")
        lines.append(
            f"{indent}                'eigenvalues': np.var(_class_models[c]['scores'], axis=0)"
            f" * _class_models[c]['scores'].shape[0],"
        )
        lines.append(f"{indent}                'class_mean': _class_models[c]['mean'],")
        lines.append(f"{indent}                'n_samples': _class_models[c]['scores'].shape[0],")
        lines.append(f"{indent}            }} for c in _classes")
        lines.append(f"{indent}        }},")
        lines.append(f"{indent}        'classes': [str(c) for c in _classes],")
        lines.append(f"{indent}        'T2_limits': _T2_limits,")
        lines.append(f"{indent}        'Q_limits': _Q_limits,")
        lines.append(f"{indent}        'type': 'simca',")
        lines.append(f"{indent}    }},")
        lines.append(f"{indent}    'predictions': _predictions,")
        lines.append(f"{indent}    'distances': _distances,")
        lines.append(f"{indent}    'train_accuracy': float(_accuracy),")
        lines.append(f"{indent}    'confusion_matrix': None,")
        lines.append(f"{indent}    'plots': {{}},")
        lines.append(f"{indent}}}")

        return lines

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
            missing_message="Missing required input: X (features)",
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

        # Convert to numpy arrays
        X_data = to_numpy_2d(X_ds, name="X", dtype=np.float64)
        y_array = _prepare_class_labels(y, X_data.shape[0])

        # Get parameters
        n_components = self.parameters.get("n_components", 3)
        confidence_level = self.parameters.get("confidence_level", 0.95)
        critical_limits_method = self.parameters.get("critical_limits_method", "ddmoments")
        if critical_limits_method not in ("ddmoments", "classical"):
            logger.warning(
                "[SIMCA Node] Unknown critical_limits_method=%r; falling back to 'ddmoments'",
                critical_limits_method,
            )
            critical_limits_method = "ddmoments"

        # Per-class DoF/h captured for the audit trail when DD moments is active.
        dd_limit_diagnostics: dict[str, dict[str, float]] = {}

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

            # Build PCA model for this class using sklearn
            # (SCP 0.8.x NDDataset auto-dims bug breaks scp.PCA here)
            from sklearn.decomposition import PCA as SklearnPCA
            from sklearn.preprocessing import StandardScaler

            scaler = StandardScaler()
            X_class_scaled = scaler.fit_transform(X_class)

            pca = SklearnPCA(n_components=n_components)
            pca.fit(X_class_scaled)

            scores_data = pca.transform(X_class_scaled).astype(np.float64)
            loadings_data = pca.components_.astype(np.float64)

            # Get class mean for proper projection of new samples
            class_mean = np.mean(X_class, axis=0)

            # Calculate T² limit using CORRECT eigenvalues from PCA model
            # Reference: Nomikos & MacGregor (1995), Technometrics
            eigenvalues = np.maximum(pca.explained_variance_[:n_components], 1e-10)

            # Per-sample T² and Q on the class's own calibration data —
            # used both for the data-driven (DD moments) critical limits and
            # left around for downstream audit even when the classical
            # method is selected.
            t2_class_cal = np.sum((scores_data**2) / eigenvalues, axis=1)
            recon_class = scores_data @ loadings_data
            q_class_cal = np.sum((X_class_scaled - recon_class) ** 2, axis=1)

            if critical_limits_method == "ddmoments":
                # Pomerantsev (J. Chemom. 2008) data-driven moments. More
                # robust than F/χ²-with-fixed-DoF for heavy-tailed Q and
                # small classes.
                T2_limit, t2_dof, t2_h = pomerantsev_dd_limit(t2_class_cal, confidence_level)
                Q_limit, q_dof, q_h = pomerantsev_dd_limit(q_class_cal, confidence_level)
                dd_limit_diagnostics[str(cls)] = {
                    "t2_limit": float(T2_limit),
                    "q_limit": float(Q_limit),
                    "t2_dof": float(t2_dof) if np.isfinite(t2_dof) else float("nan"),
                    "q_dof": float(q_dof) if np.isfinite(q_dof) else float("nan"),
                    "t2_h": float(t2_h) if np.isfinite(t2_h) else float("nan"),
                    "q_h": float(q_h) if np.isfinite(q_h) else float("nan"),
                }
            else:
                # Classical limits — preserved for legacy reproducibility.
                alpha = 1 - confidence_level
                df2 = n_class_samples - n_components
                if df2 <= 0:
                    df2 = 1
                F_crit = f.ppf(1 - alpha, n_components, df2)
                T2_limit = (
                    (n_components * (n_class_samples - 1) * (n_class_samples + 1)) / (n_class_samples * df2) * F_crit
                )

                total_var = np.sum(pca.explained_variance_)
                data_var = np.var(X_class_scaled)
                remaining_var = max(0, data_var - total_var)
                n_residual_dims = max(1, X_class.shape[1] - n_components)
                from scipy.stats import chi2

                Q_limit = max(
                    remaining_var * chi2.ppf(confidence_level, n_residual_dims) / n_residual_dims,
                    1e-10,
                )

            # Ensure limits are valid (not zero, not NaN, not inf)
            if not np.isfinite(T2_limit) or T2_limit <= 0:
                T2_limit = 1e-10
            if not np.isfinite(Q_limit) or Q_limit <= 0:
                Q_limit = 1e-10

            class_models[cls] = {
                "pca": pca,  # sklearn PCA — kept for prediction during execution
                "scaler": scaler,  # StandardScaler — needed for projecting new samples
                "scores": scores_data,
                "loadings": loadings_data,
                "eigenvalues": eigenvalues,
                "class_mean": class_mean,  # CRITICAL: Required for projecting new samples
                "x_mean": scaler.mean_.astype(np.float64),
                "x_scale": scaler.scale_.astype(np.float64),
                "pca_mean": pca.mean_.astype(np.float64),
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
                scaler = model["scaler"]
                loadings = model["loadings"]
                eigenvalues = model["eigenvalues"]

                # Project sample onto class model using sklearn
                sample_scaled = scaler.transform(sample)
                t = pca.transform(sample_scaled).flatten().astype(np.float64)

                # Calculate T² distance
                T2 = np.sum((t**2) / eigenvalues)

                # Calculate Q distance (simplified) — in scaled space
                reconstructed = t @ loadings
                Q = np.sum((sample_scaled.flatten() - reconstructed.flatten()) ** 2)

                # Combined distance (normalized by limits)
                distance = (T2 / T2_limits[cls]) + (Q / Q_limits[cls])
                sample_distances[cls] = distance

            # Classify to closest class (minimum distance)
            closest_class = min(sample_distances, key=lambda k: sample_distances[k])
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
        first_scaler = first_model["scaler"]
        viz_scores_data = first_pca.transform(first_scaler.transform(X_data)).astype(np.float64)

        logger.debug("Visualization: projecting all samples into class '%s' PC space", first_class)

        # Create serializable version of class models (exclude PCA objects)
        # CRITICAL: Include class_mean for projecting new samples in prediction
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
                "x_mean": model["x_mean"].tolist() if hasattr(model["x_mean"], "tolist") else model["x_mean"],
                "x_scale": model["x_scale"].tolist() if hasattr(model["x_scale"], "tolist") else model["x_scale"],
                "pca_mean": model["pca_mean"].tolist() if hasattr(model["pca_mean"], "tolist") else model["pca_mean"],
                "n_samples": model["n_samples"],
            }
            for cls, model in class_models.items()
        }

        # Get unique categories from the classes already computed
        label_categories = [str(c) for c in classes]

        # Get input coordinates for dataset creation
        _y_coord = X_ds.sample_axis

        # Generate plots
        plots = {}
        plots["confusion_matrix"] = generate_confusion_matrix_heatmap(cm, classes, "Confusion Matrix (Training Set)")

        # =====================================================================
        # Create SherpaDataset output with proper coordinate coupling
        # =====================================================================

        # Build PC labels for the visualization scores (projected into first class PC space)
        pc_labels = [f"PC{i+1} (Class {first_class})" for i in range(n_components)]

        # Scores: shape (n_samples, n_components) — projected into first class PC space
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

        # Propagate dataset-level flags. SIMCA viz scores project all
        # samples into the first class's PC space, so rows are samples
        # (sample-axis preserved). Origin tags survive on every output.
        inherit_sample_flags(X_ds, scores_dataset)
        inherit_origin_flags(X_ds, scores_dataset)

        # Store ONLY scientific metadata that coordinates can't carry
        scores_dataset.meta.update(
            {
                "type": "SIMCA",
                "n_components": n_components,
                "label_categories": label_categories,
                "pc_labels": pc_labels,
                "accuracy": train_accuracy,
                "confusion_matrix": cm.tolist(),
                "classification_report": class_report,
                "y_true": y_array.tolist(),
                "y_pred": predictions.tolist(),
                "confidence_level": confidence_level,
                "acceptance_stats": {
                    "T2_limits": {str(k): float(v) for k, v in T2_limits.items()},
                    "Q_limits": {str(k): float(v) for k, v in Q_limits.items()},
                    "critical_limits_method": critical_limits_method,
                    "dd_diagnostics": dd_limit_diagnostics,
                },
                "quality_summary": {
                    "accuracy": float(train_accuracy),
                    "n_components": int(n_components),
                    "n_classes": int(len(classes)),
                    "confidence_level": float(confidence_level),
                    "critical_limits_method": critical_limits_method,
                },
            }
        )

        logger.debug("Train accuracy: %.3f with %d PCs per class", train_accuracy, n_components)

        # SherpaDataset-only return: one serialization boundary at API layer
        return NodeResult(
            outputs={
                "default": scores_dataset,  # SherpaDataset: viz scores (n_samples, n_components)
                "model": {  # Wrapped model dict for ClassifierPredictNode
                    "class_models": serializable_models,
                    "classes": [str(c) for c in classes],
                    "T2_limits": {str(k): float(v) for k, v in T2_limits.items()},
                    "Q_limits": {str(k): float(v) for k, v in Q_limits.items()},
                    "type": "simca",
                },
                "predictions": predictions.tolist(),
                "distances": distances,
                "train_accuracy": float(train_accuracy),
                "confusion_matrix": cm.tolist(),
                "plots": plots,  # Pre-built Plotly traces (legitimate visualization output)
            },
            diagnostics={
                "accuracy": float(train_accuracy),
                "n_classes": len(classes),
                "critical_limits_method": critical_limits_method,
            },
        )
