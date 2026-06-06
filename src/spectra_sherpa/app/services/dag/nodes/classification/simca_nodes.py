"""
SIMCA classification nodes.
"""

from __future__ import annotations

import logging
from textwrap import dedent
from typing import Any

import numpy as np

from spectra_sherpa.app.lib.adapters.scp_extractors import SIMCAExtract
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

SIMCA_REJECT_LABEL = "unassigned"


def _simca_q_limit_from_residuals(residual_q: np.ndarray, confidence_level: float) -> float:
    """Return a positive Q limit from calibration residuals using moment matching."""
    from scipy.stats import chi2

    q = np.asarray(residual_q, dtype=np.float64)
    q = q[np.isfinite(q)]
    if q.size == 0:
        return 1e-10
    mean_q = float(np.mean(q))
    var_q = float(np.var(q, ddof=1)) if q.size > 1 else 0.0
    if mean_q <= 0 or var_q <= 0:
        return max(float(np.max(q)) if q.size else 0.0, 1e-10)
    dof = 2.0 * mean_q * mean_q / var_q
    scale = var_q / (2.0 * mean_q)
    return max(float(scale * chi2.ppf(confidence_level, dof)), 1e-10)


def _fit_simca_class_models(
    X_data: np.ndarray,
    y_array: np.ndarray,
    classes: np.ndarray,
    *,
    n_components: int,
    confidence_level: float,
    critical_limits_method: str,
) -> tuple[dict[Any, dict[str, Any]], dict[Any, float], dict[Any, float], dict[str, dict[str, float]]]:
    """Fit one PCA model per class and return SIMCA limits for classification."""
    from scipy.stats import f
    from sklearn.decomposition import PCA as SklearnPCA
    from sklearn.preprocessing import StandardScaler

    class_models: dict[Any, dict[str, Any]] = {}
    T2_limits: dict[Any, float] = {}
    Q_limits: dict[Any, float] = {}
    dd_limit_diagnostics: dict[str, dict[str, float]] = {}

    for cls in classes:
        class_mask = y_array == cls
        X_class = X_data[class_mask]
        n_class_samples = X_class.shape[0]

        if n_class_samples <= n_components:
            raise ValueError(
                f"Class {cls} has {n_class_samples} samples but needs at least {n_components + 1} for SIMCA"
            )
        if X_class.shape[1] < n_components:
            raise ValueError(
                f"SIMCA requested {n_components} components but input has only {X_class.shape[1]} features"
            )

        scaler = StandardScaler()
        X_class_scaled = scaler.fit_transform(X_class)

        pca = SklearnPCA(n_components=n_components)
        pca.fit(X_class_scaled)

        scores_data = pca.transform(X_class_scaled).astype(np.float64)
        loadings_data = pca.components_.astype(np.float64)
        class_mean = np.mean(X_class, axis=0)
        eigenvalues = np.maximum(pca.explained_variance_[:n_components], 1e-10)

        t2_class_cal = np.sum((scores_data**2) / eigenvalues, axis=1)
        recon_class = scores_data @ loadings_data
        q_class_cal = np.sum((X_class_scaled - recon_class) ** 2, axis=1)

        if critical_limits_method == "ddmoments":
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
            alpha = 1 - confidence_level
            df2 = n_class_samples - n_components
            if df2 <= 0:
                df2 = 1
            F_crit = f.ppf(1 - alpha, n_components, df2)
            T2_limit = (n_components * (n_class_samples - 1) * (n_class_samples + 1)) / (n_class_samples * df2) * F_crit

            Q_limit = _simca_q_limit_from_residuals(q_class_cal, confidence_level)

        if not np.isfinite(T2_limit) or T2_limit <= 0:
            T2_limit = 1e-10
        if not np.isfinite(Q_limit) or Q_limit <= 0:
            Q_limit = 1e-10

        class_models[cls] = {
            "pca": pca,
            "scaler": scaler,
            "scores": scores_data,
            "loadings": loadings_data,
            "eigenvalues": eigenvalues,
            "class_mean": class_mean,
            "x_mean": scaler.mean_.astype(np.float64),
            "x_scale": scaler.scale_.astype(np.float64),
            "pca_mean": pca.mean_.astype(np.float64),
            "n_samples": n_class_samples,
        }
        T2_limits[cls] = float(T2_limit)
        Q_limits[cls] = float(Q_limit)

    return class_models, T2_limits, Q_limits, dd_limit_diagnostics


def _predict_simca(
    X_data: np.ndarray,
    classes: np.ndarray,
    class_models: dict[Any, dict[str, Any]],
    T2_limits: dict[Any, float],
    Q_limits: dict[Any, float],
) -> tuple[np.ndarray, list[dict[str, float]], np.ndarray, list[list[str]], np.ndarray]:
    """Predict SIMCA membership using per-class T² and Q limits."""
    predictions: list[Any] = []
    distances: list[dict[str, float]] = []
    accepted_classes: list[list[str]] = []
    memberships: list[list[bool]] = []

    for i in range(len(X_data)):
        sample = X_data[i].reshape(1, -1)
        sample_distances: dict[str, float] = {}
        sample_accepts: list[str] = []
        sample_membership: list[bool] = []

        for cls in classes:
            model = class_models[cls]
            pca = model["pca"]
            scaler = model["scaler"]
            loadings = model["loadings"]
            eigenvalues = model["eigenvalues"]

            sample_scaled = scaler.transform(sample)
            t = pca.transform(sample_scaled).flatten().astype(np.float64)
            T2 = np.sum((t**2) / eigenvalues)
            reconstructed = t @ loadings
            Q = np.sum((sample_scaled.flatten() - reconstructed.flatten()) ** 2)
            accepted = bool(T2 <= T2_limits[cls] and Q <= Q_limits[cls])
            cls_label = str(cls)
            sample_distances[cls_label] = float((T2 / T2_limits[cls]) + (Q / Q_limits[cls]))
            sample_membership.append(accepted)
            if accepted:
                sample_accepts.append(cls_label)

        if sample_accepts:
            predictions.append(min(sample_accepts, key=lambda cls: sample_distances[str(cls)]))
        else:
            predictions.append(SIMCA_REJECT_LABEL)
        distances.append(sample_distances)
        accepted_classes.append(sample_accepts)
        memberships.append(sample_membership)

    prediction_array = np.asarray(predictions, dtype=object)
    class_distance_matrix = np.asarray(
        [[float(sample_distances[str(cls)]) for cls in classes] for sample_distances in distances],
        dtype=np.float64,
    )
    membership_matrix = np.asarray(memberships, dtype=bool)
    return prediction_array, distances, class_distance_matrix, accepted_classes, membership_matrix


def _simca_t2_q_diagnostics(
    X_data: np.ndarray,
    classes: np.ndarray,
    class_models: dict[Any, dict[str, Any]],
    T2_limits: dict[Any, float],
    Q_limits: dict[Any, float],
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Return per-sample, per-class T²/Q and the nearest accepted-distance class index."""
    n_samples = X_data.shape[0]
    n_classes = len(classes)
    t2 = np.zeros((n_samples, n_classes), dtype=np.float64)
    q = np.zeros((n_samples, n_classes), dtype=np.float64)

    for j, cls in enumerate(classes):
        model = class_models[cls]
        pca = model["pca"]
        scaler = model["scaler"]
        loadings = model["loadings"]
        eigenvalues = model["eigenvalues"]
        scaled = scaler.transform(X_data)
        scores = pca.transform(scaled).astype(np.float64)
        reconstructed = scores @ loadings
        t2[:, j] = np.sum((scores**2) / eigenvalues, axis=1)
        q[:, j] = np.sum((scaled - reconstructed) ** 2, axis=1)

    t2_limits = np.asarray([max(float(T2_limits[cls]), 1e-12) for cls in classes], dtype=np.float64)
    q_limits = np.asarray([max(float(Q_limits[cls]), 1e-12) for cls in classes], dtype=np.float64)
    combined = (t2 / t2_limits.reshape(1, -1)) + (q / q_limits.reshape(1, -1))
    nearest = np.argmin(combined, axis=1)
    return t2, q, nearest, combined


def _generate_simca_acceptance_plot(
    *,
    t2: np.ndarray,
    q: np.ndarray,
    nearest_class_idx: np.ndarray,
    classes: np.ndarray,
    T2_limits: dict[Any, float],
    Q_limits: dict[Any, float],
    true_labels: np.ndarray,
    predicted_labels: np.ndarray,
) -> dict[str, Any]:
    """Build a Q-vs-T² acceptance plot in each sample's nearest class space."""
    x_vals: list[float] = []
    y_vals: list[float] = []
    text: list[str] = []
    colors: list[str] = []
    symbols: list[str] = []

    for i, class_idx in enumerate(nearest_class_idx.tolist()):
        cls = classes[class_idx]
        x_norm = float(t2[i, class_idx] / max(float(T2_limits[cls]), 1e-12))
        y_norm = float(q[i, class_idx] / max(float(Q_limits[cls]), 1e-12))
        x_vals.append(x_norm)
        y_vals.append(y_norm)
        pred = str(predicted_labels[i])
        truth = str(true_labels[i])
        nearest = str(cls)
        text.append(
            f"Sample {i + 1}<br>True: {truth}<br>Predicted: {pred}<br>"
            f"Nearest class model: {nearest}<br>T²/limit: {x_norm:.3g}<br>Q/limit: {y_norm:.3g}"
        )
        colors.append("#ef4444" if pred == SIMCA_REJECT_LABEL else "#2563eb")
        symbols.append("x" if pred == SIMCA_REJECT_LABEL else "circle")

    return {
        "plot_type": "scatter",
        "data": [
            {
                "x": x_vals,
                "y": y_vals,
                "type": "scatter",
                "mode": "markers",
                "marker": {"size": 9, "color": colors, "symbol": symbols},
                "text": text,
                "hovertemplate": "%{text}<extra></extra>",
                "name": "Samples",
            },
            {
                "x": [1.0, 1.0],
                "y": [0.0, max([1.2, *y_vals])],
                "type": "scatter",
                "mode": "lines",
                "line": {"color": "#ef4444", "dash": "dash"},
                "name": "T² limit",
            },
            {
                "x": [0.0, max([1.2, *x_vals])],
                "y": [1.0, 1.0],
                "type": "scatter",
                "mode": "lines",
                "line": {"color": "#f97316", "dash": "dash"},
                "name": "Q limit",
            },
        ],
        "layout": {
            "title": "SIMCA Acceptance Diagnostics",
            "xaxis": {"title": "Hotelling T² / class limit"},
            "yaxis": {"title": "Q residual / class limit"},
        },
        "metadata": {
            "type": "simca_acceptance",
            "class_labels": [str(c) for c in classes],
            "boundary": "accepted when T²/limit <= 1 and Q/limit <= 1",
        },
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
        label="Train SIMCA Classifier",
        description="Train a SIMCA classifier using class-specific PCA models",
        parameters=[
            NodeParameter(
                name="n_components",
                label="Number of Components per Class",
                param_type="number",
                default=3,
                min_value=1,
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
            NodeParameter(
                name="cv_folds",
                label="Cross-Validation Folds",
                param_type="number",
                default=5,
                min_value=2,
                step=1,
                description="Number of stratified folds for comparable SIMCA validation metrics",
                required=False,
            ),
        ],
        input_types=["NDDataset", "array"],
        output_type="SIMCAModel",
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
                label="SIMCA Scores",
                description="Sample scores projected into the first class PCA space",
            ),
            PortMetadata(
                name="model",
                type_ref="spectrasherpa://types/ClassificationModel/1.0",
                required=True,
                label="Fitted SIMCA Classifier",
                description="Fitted SIMCA classification model produced by this training node",
            ),
            PortMetadata(
                name="predictions",
                type_ref="spectrasherpa://types/Categorical/1.0",
                required=True,
                label="Predictions",
                description="Predicted class labels for training data",
            ),
            PortMetadata(
                name="class_assignment",
                type_ref="spectrasherpa://types/Categorical/1.0",
                required=True,
                label="Class Assignment",
                description="Alias of predictions for downstream comparison",
            ),
            PortMetadata(
                name="distances",
                type_ref="spectrasherpa://types/Any/1.0",
                required=True,
                label="Class Distances",
                description="Per-sample distance mapping to each class model (combined T² and Q)",
            ),
            PortMetadata(
                name="class_distance_matrix",
                type_ref="spectrasherpa://types/Array2D/1.0",
                required=True,
                label="Class Distance Matrix",
                description="Distance matrix with rows=samples and columns=classes",
            ),
            PortMetadata(
                name="metrics",
                type_ref="spectrasherpa://types/Any/1.0",
                required=False,
                label="Classification Metrics",
                description="Canonical train/CV/test classification metrics for run history, comparison, and guidance",
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
        critical_limits_method = params.get("critical_limits_method", "ddmoments")
        if critical_limits_method not in ("ddmoments", "classical"):
            critical_limits_method = "ddmoments"
        cv_folds = params.get("cv_folds", 5)

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

        # Build per-class PCA models with export-local helpers that mirror the runtime implementation.
        # The generated script should not depend on private node-module helper imports.
        helper_block = dedent("""
            from scipy.stats import chi2, f
            from sklearn.decomposition import PCA as SklearnPCA
            from sklearn.preprocessing import StandardScaler

            def _simca_dd_limit(stat_values, confidence_level):
                vals = np.asarray(stat_values, dtype=np.float64)
                vals = vals[np.isfinite(vals)]
                if vals.size < 2:
                    crit = float(np.quantile(vals, confidence_level)) if vals.size else 0.0
                    return crit, float('nan'), float('nan')
                mean_v = float(np.mean(vals))
                var_v = float(np.var(vals, ddof=1))
                if mean_v <= 0.0 or var_v <= 0.0:
                    crit = float(np.quantile(vals, confidence_level))
                    return crit, float('nan'), float('nan')
                dof = max(2.0 * mean_v * mean_v / var_v, 1.0)
                h = mean_v / dof
                crit = float(h * chi2.ppf(confidence_level, dof))
                return crit, float(dof), float(h)

            def _simca_q_limit_from_residuals(residual_q, confidence_level):
                vals = np.asarray(residual_q, dtype=np.float64)
                vals = vals[np.isfinite(vals)]
                if vals.size == 0:
                    return 1e-10
                mean_v = float(np.mean(vals))
                var_v = float(np.var(vals, ddof=1)) if vals.size > 1 else 0.0
                if mean_v <= 0.0 or var_v <= 0.0:
                    return max(float(np.max(vals)) if vals.size else 0.0, 1e-10)
                dof = 2.0 * mean_v * mean_v / var_v
                scale = var_v / (2.0 * mean_v)
                return max(float(scale * chi2.ppf(confidence_level, dof)), 1e-10)

            def _fit_simca_export_models(
                X_data, y_array, classes, n_components, confidence_level, critical_limits_method
            ):
                class_models = {}
                T2_limits = {}
                Q_limits = {}
                dd_limit_diagnostics = {}
                for cls in classes:
                    class_mask = y_array == cls
                    X_class = X_data[class_mask]
                    n_class_samples = X_class.shape[0]
                    if n_class_samples <= n_components:
                        raise ValueError(
                            f"Class {cls} has {n_class_samples} samples but needs at least {n_components + 1} for SIMCA"
                        )
                    if X_class.shape[1] < n_components:
                        raise ValueError(
                            f"SIMCA requested {n_components} components but input has only {X_class.shape[1]} features"
                        )
                    scaler = StandardScaler()
                    X_class_scaled = scaler.fit_transform(X_class)
                    pca = SklearnPCA(n_components=n_components)
                    pca.fit(X_class_scaled)
                    scores_data = pca.transform(X_class_scaled).astype(np.float64)
                    loadings_data = pca.components_.astype(np.float64)
                    class_mean = np.mean(X_class, axis=0)
                    eigenvalues = np.maximum(pca.explained_variance_[:n_components], 1e-10)
                    t2_class_cal = np.sum((scores_data**2) / eigenvalues, axis=1)
                    recon_class = scores_data @ loadings_data
                    q_class_cal = np.sum((X_class_scaled - recon_class) ** 2, axis=1)
                    if critical_limits_method == "ddmoments":
                        T2_limit, t2_dof, t2_h = _simca_dd_limit(t2_class_cal, confidence_level)
                        Q_limit, q_dof, q_h = _simca_dd_limit(q_class_cal, confidence_level)
                        dd_limit_diagnostics[str(cls)] = {
                            "t2_limit": float(T2_limit),
                            "q_limit": float(Q_limit),
                            "t2_dof": float(t2_dof) if np.isfinite(t2_dof) else float("nan"),
                            "q_dof": float(q_dof) if np.isfinite(q_dof) else float("nan"),
                            "t2_h": float(t2_h) if np.isfinite(t2_h) else float("nan"),
                            "q_h": float(q_h) if np.isfinite(q_h) else float("nan"),
                        }
                    else:
                        alpha = 1 - confidence_level
                        df2 = max(1, n_class_samples - n_components)
                        F_crit = f.ppf(1 - alpha, n_components, df2)
                        T2_limit = (
                            (n_components * (n_class_samples - 1) * (n_class_samples + 1))
                            / (n_class_samples * df2)
                            * F_crit
                        )
                        Q_limit = _simca_q_limit_from_residuals(q_class_cal, confidence_level)
                    if not np.isfinite(T2_limit) or T2_limit <= 0:
                        T2_limit = 1e-10
                    if not np.isfinite(Q_limit) or Q_limit <= 0:
                        Q_limit = 1e-10
                    class_models[cls] = {
                        "pca": pca,
                        "scaler": scaler,
                        "scores": scores_data,
                        "loadings": loadings_data,
                        "eigenvalues": eigenvalues,
                        "class_mean": class_mean,
                        "x_mean": scaler.mean_.astype(np.float64),
                        "x_scale": scaler.scale_.astype(np.float64),
                        "pca_mean": pca.mean_.astype(np.float64),
                        "n_samples": n_class_samples,
                    }
                    T2_limits[cls] = float(T2_limit)
                    Q_limits[cls] = float(Q_limit)
                return class_models, T2_limits, Q_limits, dd_limit_diagnostics

            def _predict_simca_export(X_data, classes, class_models, T2_limits, Q_limits):
                predictions = []
                distances = []
                accepted_classes = []
                memberships = []
                for i in range(len(X_data)):
                    sample = X_data[i].reshape(1, -1)
                    sample_distances = {}
                    sample_accepts = []
                    sample_membership = []
                    for cls in classes:
                        model = class_models[cls]
                        sample_scaled = model["scaler"].transform(sample)
                        t = model["pca"].transform(sample_scaled).flatten().astype(np.float64)
                        T2 = np.sum((t**2) / model["eigenvalues"])
                        reconstructed = t @ model["loadings"]
                        Q = np.sum((sample_scaled.flatten() - reconstructed.flatten()) ** 2)
                        accepted = bool(T2 <= T2_limits[cls] and Q <= Q_limits[cls])
                        sample_distances[str(cls)] = float((T2 / T2_limits[cls]) + (Q / Q_limits[cls]))
                        sample_membership.append(accepted)
                        if accepted:
                            sample_accepts.append(str(cls))
                    predictions.append(
                        min(sample_accepts, key=lambda cls: sample_distances[str(cls)])
                        if sample_accepts
                        else "unassigned"
                    )
                    distances.append(sample_distances)
                    accepted_classes.append(sample_accepts)
                    memberships.append(sample_membership)
                prediction_array = np.asarray(predictions, dtype=object)
                class_distance_matrix = np.asarray(
                    [[float(sample_distances[str(cls)]) for cls in classes] for sample_distances in distances],
                    dtype=np.float64,
                )
                membership_matrix = np.asarray(memberships, dtype=bool)
                return prediction_array, distances, class_distance_matrix, accepted_classes, membership_matrix
            """).strip()
        lines.extend(f"{indent}{line}" if line else "" for line in helper_block.splitlines())
        lines.append(f"{indent}from sklearn.metrics import confusion_matrix")
        lines.append(f"{indent}from sklearn.model_selection import StratifiedKFold")
        lines.append(f"{indent}from spectra_sherpa.app.services.dag.nodes.classification.core_utils import (")
        lines.append(f"{indent}    classification_metrics_contract,")
        lines.append(f"{indent}    classification_scalar_metrics,")
        lines.append(f"{indent})")
        lines.append(f"{indent}_classes = np.unique(_y_labels)")
        lines.append(f"{indent}_class_counts = np.array([np.sum(_y_labels == _cls) for _cls in _classes])")
        lines.append(f"{indent}_cv_folds = int({cv_folds})")
        lines.append(f"{indent}if _cv_folds > int(_class_counts.min()):")
        lines.append(
            f"{indent}    raise ValueError(f'cv_folds must be <= smallest class count "
            f"({{int(_class_counts.min())}}). Got {{_cv_folds}}.')"
        )
        lines.append(f"{indent}_class_models, _T2_limits, _Q_limits, _dd_limit_diagnostics = _fit_simca_export_models(")
        lines.append(f"{indent}    _X_data,")
        lines.append(f"{indent}    _y_labels,")
        lines.append(f"{indent}    _classes,")
        lines.append(f"{indent}    int({n_components}),")
        lines.append(f"{indent}    float({confidence_level}),")
        lines.append(f"{indent}    {critical_limits_method!r},")
        lines.append(f"{indent})")

        # Classify all samples
        lines.append(
            f"{indent}_predictions, _distances, _class_distance_matrix, _accepted_classes, "
            f"_membership_matrix = _predict_simca_export("
        )
        lines.append(f"{indent}    _X_data,")
        lines.append(f"{indent}    _classes,")
        lines.append(f"{indent}    _class_models,")
        lines.append(f"{indent}    _T2_limits,")
        lines.append(f"{indent}    _Q_limits,")
        lines.append(f"{indent})")
        lines.append(f"{indent}_T2_limits = {{str(k): float(v) for k, v in _T2_limits.items()}}")
        lines.append(f"{indent}_Q_limits = {{str(k): float(v) for k, v in _Q_limits.items()}}")
        lines.append(f"{indent}_dd_limit_diagnostics = " f"{{str(k): v for k, v in _dd_limit_diagnostics.items()}}")
        lines.append(f"{indent}_y_pred_cv = np.empty(_y_labels.shape, dtype=object)")
        lines.append(f"{indent}_cv = StratifiedKFold(n_splits=_cv_folds, shuffle=True, random_state=42)")
        lines.append(f"{indent}_cv_effective_components = int({n_components})")
        lines.append(f"{indent}for _train_idx, _test_idx in _cv.split(_X_data, _y_labels):")
        lines.append(f"{indent}    _y_train_fold = _y_labels[_train_idx]")
        lines.append(f"{indent}    _, _fold_counts = np.unique(_y_train_fold, return_counts=True)")
        lines.append(
            f"{indent}    _fold_components = min("
            f"int({n_components}), int(_fold_counts.min()) - 1, _X_data.shape[1])"
        )
        lines.append(f"{indent}    if _fold_components < 1:")
        lines.append(
            f"{indent}        raise ValueError("
            f"'SIMCA cross-validation needs at least two training samples per class in every fold.')"
        )
        lines.append(f"{indent}    _cv_effective_components = min(_cv_effective_components, _fold_components)")
        lines.append(f"{indent}    _fold_models, _fold_T2_limits, _fold_Q_limits, _ = _fit_simca_export_models(")
        lines.append(f"{indent}        _X_data[_train_idx],")
        lines.append(f"{indent}        _y_train_fold,")
        lines.append(f"{indent}        _classes,")
        lines.append(f"{indent}        _fold_components,")
        lines.append(f"{indent}        float({confidence_level}),")
        lines.append(f"{indent}        {critical_limits_method!r},")
        lines.append(f"{indent}    )")
        lines.append(f"{indent}    _y_pred_cv[_test_idx], _, _, _, _ = _predict_simca_export(")
        lines.append(f"{indent}        _X_data[_test_idx],")
        lines.append(f"{indent}        _classes,")
        lines.append(f"{indent}        _fold_models,")
        lines.append(f"{indent}        _fold_T2_limits,")
        lines.append(f"{indent}        _fold_Q_limits,")
        lines.append(f"{indent}    )")
        lines.append(
            f"{indent}_train_metrics = classification_scalar_metrics("
            "_y_labels, _predictions, _classes, prefix='train_')"
        )
        lines.append(
            f"{indent}_cv_metrics = classification_scalar_metrics(_y_labels, _y_pred_cv, _classes, prefix='cv_')"
        )
        lines.append(f"{indent}_cm_train = confusion_matrix(_y_labels, _predictions, labels=_classes)")
        lines.append(f"{indent}_cm_cv = confusion_matrix(_y_labels, _y_pred_cv, labels=_classes)")
        lines.append(f"{indent}_classification_metrics = classification_metrics_contract(")
        lines.append(f"{indent}    classes=_classes,")
        lines.append(f"{indent}    train_metrics=_train_metrics,")
        lines.append(f"{indent}    cv_metrics=_cv_metrics,")
        lines.append(f"{indent}    primary_split='cv',")
        lines.append(f"{indent}    method='simca',")
        lines.append(f"{indent}    confusion_matrices={{'train': _cm_train.tolist(), 'cv': _cm_cv.tolist()}},")
        lines.append(
            f"{indent}    extra={{'cv_method': f'stratified-k-fold (k={{_cv_folds}})', "
            f"'n_components': int({n_components}), "
            f"'cv_effective_n_components': int(_cv_effective_components), "
            f"'confidence_level': float({confidence_level}), "
            f"'critical_limits_method': {critical_limits_method!r}}},"
        )
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
        lines.append(f"{indent}_first_class = _classes[0]")
        lines.append(f"{indent}_first_model = _class_models[_first_class]")
        lines.append(
            f"{indent}_default_scores = _first_model['pca'].transform("
            f"_first_model['scaler'].transform(_X_data)).astype(np.float64)"
        )
        lines.append(f"{indent}_accuracy = np.mean(_predictions == _y_labels)")
        lines.append(
            f'{indent}print(f"  SIMCA ({n_components} PCs,'
            f" conf={confidence_level}):"
            f' accuracy={{_accuracy:.4f}} ({{len(_classes)}} classes)")'
        )

        lines.append(f"{indent}results['{self.node_id}'] = {{")
        lines.append(f"{indent}    'model': {{")
        # Build class_models dict comprehension across multiple lines
        lines.append(f"{indent}        'class_models': {{")
        lines.append(f"{indent}            str(c): {{")
        lines.append(f"{indent}                'scores': _class_models[c]['scores'],")
        lines.append(f"{indent}                'loadings': _class_models[c]['loadings'],")
        lines.append(f"{indent}                'eigenvalues': _class_models[c]['eigenvalues'],")
        lines.append(f"{indent}                'class_mean': _class_models[c]['class_mean'],")
        lines.append(f"{indent}                'x_mean': _class_models[c]['x_mean'],")
        lines.append(f"{indent}                'x_scale': _class_models[c]['x_scale'],")
        lines.append(f"{indent}                'n_samples': _class_models[c]['scores'].shape[0],")
        lines.append(f"{indent}            }} for c in _classes")
        lines.append(f"{indent}        }},")
        lines.append(f"{indent}        'classes': [str(c) for c in _classes],")
        lines.append(f"{indent}        'T2_limits': _T2_limits,")
        lines.append(f"{indent}        'Q_limits': _Q_limits,")
        lines.append(f"{indent}        'dd_limit_diagnostics': _dd_limit_diagnostics,")
        lines.append(f"{indent}        'type': 'simca',")
        lines.append(f"{indent}    }},")
        lines.append(f"{indent}    'default': _default_scores,")
        lines.append(f"{indent}    'predictions': _predictions,")
        lines.append(f"{indent}    'class_assignment': _predictions,")
        lines.append(f"{indent}    'distances': _distances,")
        lines.append(f"{indent}    'class_distance_matrix': _class_distance_matrix,")
        lines.append(f"{indent}    'accepted_classes': _accepted_classes,")
        lines.append(f"{indent}    'membership_matrix': _membership_matrix,")
        lines.append(f"{indent}    'train_accuracy': float(_accuracy),")
        lines.append(f"{indent}    'cv_accuracy': float(")
        lines.append(f"{indent}        _cv_metrics.get('cv_accuracy', np.mean(_y_pred_cv == _y_labels))")
        lines.append(f"{indent}    ),")
        lines.append(f"{indent}    'confusion_matrix': _cm_cv,")
        lines.append(f"{indent}    'confusion_matrix_train': _cm_train,")
        lines.append(f"{indent}    'confusion_matrix_cv': _cm_cv,")
        lines.append(f"{indent}    'metrics': {{")
        lines.append(f"{indent}        **_train_metrics,")
        lines.append(f"{indent}        **_cv_metrics,")
        lines.append(f"{indent}        'classification_metrics': _classification_metrics,")
        lines.append(f"{indent}    }},")
        lines.append(
            f"{indent}    'metadata': {{'y_true': _y_labels.tolist(), 'y_pred': _predictions.tolist(), "
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
        Execute SIMCA classification.

        Args:
            X: NDDataset containing feature data
            y: Class labels

        Returns:
            SIMCA model with classification results
        """
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
        cv_folds = int(self.parameters.get("cv_folds", 5))
        if critical_limits_method not in ("ddmoments", "classical"):
            logger.warning(
                "[SIMCA Node] Unknown critical_limits_method=%r; falling back to 'ddmoments'",
                critical_limits_method,
            )
            critical_limits_method = "ddmoments"

        # Get unique classes
        classes = np.unique(y_array)
        n_classes = len(classes)

        if n_classes < 2:
            raise ValueError(f"Need at least 2 classes, got {n_classes}")

        _, class_counts = np.unique(y_array, return_counts=True)
        min_class_count = int(class_counts.min())
        if cv_folds > min_class_count:
            raise ValueError(f"cv_folds must be <= smallest class count ({min_class_count}). Got {cv_folds}.")

        class_models, T2_limits, Q_limits, dd_limit_diagnostics = _fit_simca_class_models(
            X_data,
            y_array,
            classes,
            n_components=int(n_components),
            confidence_level=float(confidence_level),
            critical_limits_method=str(critical_limits_method),
        )
        predictions, distances, class_distance_matrix, accepted_classes, membership_matrix = _predict_simca(
            X_data,
            classes,
            class_models,
            T2_limits,
            Q_limits,
        )
        t2_matrix, q_matrix, nearest_class_idx, _combined_distance = _simca_t2_q_diagnostics(
            X_data,
            classes,
            class_models,
            T2_limits,
            Q_limits,
        )

        # Calculate metrics
        from sklearn.metrics import classification_report, confusion_matrix

        train_metrics = _classification_scalar_metrics(y_array, predictions, classes, prefix="train_")
        train_accuracy = train_metrics["train_accuracy"]
        cm_train = confusion_matrix(y_array, predictions, labels=classes)

        from sklearn.model_selection import StratifiedKFold

        y_pred_cv = np.empty(y_array.shape, dtype=object)
        cv_splitter = StratifiedKFold(n_splits=cv_folds, shuffle=True, random_state=42)
        cv_effective_components = int(n_components)
        for train_idx, test_idx in cv_splitter.split(X_data, y_array):
            y_train_fold = y_array[train_idx]
            _, fold_class_counts = np.unique(y_train_fold, return_counts=True)
            fold_components = min(int(n_components), int(fold_class_counts.min()) - 1, X_data.shape[1])
            if fold_components < 1:
                raise ValueError("SIMCA cross-validation needs at least two training samples per class in every fold.")
            cv_effective_components = min(cv_effective_components, fold_components)
            fold_models, fold_T2_limits, fold_Q_limits, _ = _fit_simca_class_models(
                X_data[train_idx],
                y_train_fold,
                classes,
                n_components=fold_components,
                confidence_level=float(confidence_level),
                critical_limits_method=str(critical_limits_method),
            )
            y_pred_cv[test_idx], _, _, _, _ = _predict_simca(
                X_data[test_idx],
                classes,
                fold_models,
                fold_T2_limits,
                fold_Q_limits,
            )

        cv_metrics = _classification_scalar_metrics(y_array, y_pred_cv, classes, prefix="cv_")
        cm_cv = confusion_matrix(y_array, y_pred_cv, labels=classes)
        classification_metrics = _classification_metrics_contract(
            classes=classes,
            train_metrics=train_metrics,
            cv_metrics=cv_metrics,
            primary_split="cv",
            method="simca",
            confusion_matrices={
                "train": cm_train.tolist(),
                "cv": cm_cv.tolist(),
            },
            extra={
                "cv_method": f"stratified-k-fold (k={cv_folds})",
                "n_components": int(n_components),
                "cv_effective_n_components": int(cv_effective_components),
                "confidence_level": float(confidence_level),
                "critical_limits_method": str(critical_limits_method),
            },
        )
        class_report = classification_report(
            y_array,
            y_pred_cv,
            labels=classes,
            target_names=[str(c) for c in classes],
            output_dict=True,
            zero_division=0,
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
        plots["confusion_matrix_train"] = generate_confusion_matrix_heatmap(
            cm_train, classes, "Confusion Matrix (Training Set)"
        )
        plots["confusion_matrix_cv"] = generate_confusion_matrix_heatmap(
            cm_cv, classes, "Confusion Matrix (Cross-Validation)"
        )
        plots["simca_acceptance"] = _generate_simca_acceptance_plot(
            t2=t2_matrix,
            q=q_matrix,
            nearest_class_idx=nearest_class_idx,
            classes=classes,
            T2_limits=T2_limits,
            Q_limits=Q_limits,
            true_labels=y_array,
            predicted_labels=predictions,
        )

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
            data_role="X_features",
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
                "train_accuracy": train_accuracy,
                "train_balanced_accuracy": train_metrics["train_balanced_accuracy"],
                "train_f1_macro": train_metrics["train_f1_macro"],
                "train_precision_macro": train_metrics["train_precision_macro"],
                "train_recall_macro": train_metrics["train_recall_macro"],
                "train_sensitivity_macro": train_metrics["train_sensitivity_macro"],
                "train_specificity_macro": train_metrics["train_specificity_macro"],
                "cv_accuracy": cv_metrics["cv_accuracy"],
                "cv_balanced_accuracy": cv_metrics["cv_balanced_accuracy"],
                "cv_f1_macro": cv_metrics["cv_f1_macro"],
                "cv_precision_macro": cv_metrics["cv_precision_macro"],
                "cv_recall_macro": cv_metrics["cv_recall_macro"],
                "cv_sensitivity_macro": cv_metrics["cv_sensitivity_macro"],
                "cv_specificity_macro": cv_metrics["cv_specificity_macro"],
                "confusion_matrix": cm_train.tolist(),
                "confusion_matrix_train": cm_train.tolist(),
                "confusion_matrix_cv": cm_cv.tolist(),
                "metrics": classification_metrics,
                "classification_report": class_report,
                "y_true": y_array.tolist(),
                "y_pred": predictions.tolist(),
                "y_pred_cv": y_pred_cv.tolist(),
                "accepted_classes": accepted_classes,
                "membership_matrix": membership_matrix.tolist(),
                "t2_matrix": t2_matrix.tolist(),
                "q_matrix": q_matrix.tolist(),
                "n_rejected": int(np.sum(predictions == SIMCA_REJECT_LABEL)),
                "confidence_level": confidence_level,
                "acceptance_stats": {
                    "T2_limits": {str(k): float(v) for k, v in T2_limits.items()},
                    "Q_limits": {str(k): float(v) for k, v in Q_limits.items()},
                    "critical_limits_method": critical_limits_method,
                    "dd_diagnostics": dd_limit_diagnostics,
                },
                "quality_summary": {
                    "train_accuracy": float(train_accuracy),
                    "train_balanced_accuracy": float(train_metrics["train_balanced_accuracy"]),
                    "train_f1_macro": float(train_metrics["train_f1_macro"]),
                    "train_precision_macro": float(train_metrics["train_precision_macro"]),
                    "train_recall_macro": float(train_metrics["train_recall_macro"]),
                    "train_sensitivity_macro": float(train_metrics["train_sensitivity_macro"]),
                    "train_specificity_macro": float(train_metrics["train_specificity_macro"]),
                    "cv_accuracy": float(cv_metrics["cv_accuracy"]),
                    "cv_balanced_accuracy": float(cv_metrics["cv_balanced_accuracy"]),
                    "cv_f1_macro": float(cv_metrics["cv_f1_macro"]),
                    "cv_precision_macro": float(cv_metrics["cv_precision_macro"]),
                    "cv_recall_macro": float(cv_metrics["cv_recall_macro"]),
                    "cv_sensitivity_macro": float(cv_metrics["cv_sensitivity_macro"]),
                    "cv_specificity_macro": float(cv_metrics["cv_specificity_macro"]),
                    "n_components": int(n_components),
                    "cv_effective_n_components": int(cv_effective_components),
                    "n_classes": int(len(classes)),
                    "n_rejected": int(np.sum(predictions == SIMCA_REJECT_LABEL)),
                    "confidence_level": float(confidence_level),
                    "critical_limits_method": critical_limits_method,
                },
            }
        )

        logger.debug("Train accuracy: %.3f with %d PCs per class", train_accuracy, n_components)

        from ..modeling._artifact_builder import build_model_artifact

        simca_extract = SIMCAExtract(
            class_loadings={str(cls): np.asarray(class_models[cls]["loadings"], dtype=np.float64) for cls in classes},
            class_eigenvalues={
                str(cls): np.asarray(class_models[cls]["eigenvalues"], dtype=np.float64) for cls in classes
            },
            class_means={str(cls): np.asarray(class_models[cls]["x_mean"], dtype=np.float64) for cls in classes},
            class_scales={str(cls): np.asarray(class_models[cls]["x_scale"], dtype=np.float64) for cls in classes},
            pca_means={str(cls): np.asarray(class_models[cls]["pca_mean"], dtype=np.float64) for cls in classes},
            classes=[str(cls) for cls in classes],
            T2_limits={str(k): float(v) for k, v in T2_limits.items()},
            Q_limits={str(k): float(v) for k, v in Q_limits.items()},
            n_components=int(n_components),
        )
        artifact = build_model_artifact(
            simca_extract,
            X_ds,
            node_id=self.node_id,
            metrics={
                "train_accuracy": float(train_accuracy),
                "cv_accuracy": float(cv_metrics["cv_accuracy"]),
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
                "n_classes": int(len(classes)),
                "critical_limits_method": critical_limits_method,
            },
        )

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
                "class_assignment": predictions.tolist(),
                "distances": distances,
                "class_distance_matrix": class_distance_matrix.tolist(),
                "accepted_classes": accepted_classes,
                "membership_matrix": membership_matrix.tolist(),
                "t2_matrix": t2_matrix.tolist(),
                "q_matrix": q_matrix.tolist(),
                "n_rejected": int(np.sum(predictions == SIMCA_REJECT_LABEL)),
                "metrics": classification_metrics,
                "train_accuracy": float(train_accuracy),
                "train_balanced_accuracy": float(train_metrics["train_balanced_accuracy"]),
                "train_f1_macro": float(train_metrics["train_f1_macro"]),
                "train_precision_macro": float(train_metrics["train_precision_macro"]),
                "train_recall_macro": float(train_metrics["train_recall_macro"]),
                "train_sensitivity_macro": float(train_metrics["train_sensitivity_macro"]),
                "train_specificity_macro": float(train_metrics["train_specificity_macro"]),
                "cv_accuracy": float(cv_metrics["cv_accuracy"]),
                "cv_balanced_accuracy": float(cv_metrics["cv_balanced_accuracy"]),
                "cv_f1_macro": float(cv_metrics["cv_f1_macro"]),
                "cv_precision_macro": float(cv_metrics["cv_precision_macro"]),
                "cv_recall_macro": float(cv_metrics["cv_recall_macro"]),
                "cv_sensitivity_macro": float(cv_metrics["cv_sensitivity_macro"]),
                "cv_specificity_macro": float(cv_metrics["cv_specificity_macro"]),
                "confusion_matrix": cm_train.tolist(),
                "confusion_matrix_train": cm_train.tolist(),
                "confusion_matrix_cv": cm_cv.tolist(),
                "plots": plots,  # Pre-built Plotly traces (legitimate visualization output)
                "_model_artifact": artifact,
            },
            diagnostics={
                "train_accuracy": float(train_accuracy),
                "train_balanced_accuracy": train_metrics["train_balanced_accuracy"],
                "train_f1_macro": train_metrics["train_f1_macro"],
                "train_precision_macro": train_metrics["train_precision_macro"],
                "train_recall_macro": train_metrics["train_recall_macro"],
                "train_sensitivity_macro": train_metrics["train_sensitivity_macro"],
                "train_specificity_macro": train_metrics["train_specificity_macro"],
                "cv_accuracy": float(cv_metrics["cv_accuracy"]),
                "cv_balanced_accuracy": cv_metrics["cv_balanced_accuracy"],
                "cv_f1_macro": cv_metrics["cv_f1_macro"],
                "cv_precision_macro": cv_metrics["cv_precision_macro"],
                "cv_recall_macro": cv_metrics["cv_recall_macro"],
                "cv_sensitivity_macro": cv_metrics["cv_sensitivity_macro"],
                "cv_specificity_macro": cv_metrics["cv_specificity_macro"],
                "metrics": classification_metrics,
                "n_classes": len(classes),
                "n_rejected": int(np.sum(predictions == SIMCA_REJECT_LABEL)),
                "critical_limits_method": critical_limits_method,
            },
        )
