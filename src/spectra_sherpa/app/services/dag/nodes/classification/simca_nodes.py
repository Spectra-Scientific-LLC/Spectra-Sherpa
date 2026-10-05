"""
SIMCA classification nodes.
"""

from __future__ import annotations

import logging
from typing import Any

import numpy as np

from spectra_sherpa.app.lib import fitted_state
from spectra_sherpa.app.lib.fitted_state import SIMCAExtract
from spectra_sherpa.app.services.dag import io_contracts as dag_io_contracts
from spectra_sherpa.app.services.dag import meta_helpers
from spectra_sherpa.app.services.dag.classification_application import CLASSIFICATION_REJECT_LABEL
from spectra_sherpa.app.services.dag.meta_helpers import (
    add_processing_step,
    copy_processing_history,
    inherit_origin_flags,
    inherit_sample_flags,
)
from spectra_sherpa.execution_contract_vocabulary import (
    LifecycleKind,
    ManagedOptimizationEligibility,
    RuntimeFamily,
    TargetAccess,
    WorkerCapability,
)

from ...io_contracts import (
    bind_X,
    bind_y,
    to_numpy_2d,
)
from ...node_base import Node, NodeMetadata, NodeParameter, NodePolicy, NodeResult, PortMetadata, register_node
from ...presentation_contract import NodePresentationContract, ScientificPresentation
from ...stable_execution_contract import bind_stable_execution_contract
from .. import _chemometric_diagnostics, visualization
from .._chemometric_diagnostics import pomerantsev_dd_limit
from ..modeling import _artifact_builder, create_spectral_dataset
from ..modeling import core_utils as modeling_core_utils
from ..visualization import generate_confusion_matrix_heatmap
from . import core_utils
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

SIMCA_REJECT_LABEL = CLASSIFICATION_REJECT_LABEL
SIMCA_FITTED_STATE_SERIALIZER = "spectrasherpa.model-artifact.simca/1"
_SIMCA_MAX_COMPONENTS = 50


def _simca_calibration_confusion(
    target: np.ndarray,
    predictions: np.ndarray,
    classes: np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    """Return a complete calibration matrix, retaining rejected decisions."""

    from sklearn.metrics import confusion_matrix

    target = np.asarray(target, dtype=object).reshape(-1)
    predictions = np.asarray(predictions, dtype=object).reshape(-1)
    labels = np.asarray(classes, dtype=object).reshape(-1)
    if target.shape != predictions.shape:
        raise ValueError("SIMCA calibration predictions must align with class labels")
    if np.any(predictions == SIMCA_REJECT_LABEL):
        labels = np.concatenate([labels, np.asarray([SIMCA_REJECT_LABEL], dtype=object)])
    matrix = confusion_matrix(target, predictions, labels=labels)
    if int(matrix.sum()) != int(target.size):
        raise RuntimeError("SIMCA calibration confusion matrix does not account for every sample")
    return matrix, labels


def _sample_labels_or_indices(dataset: Any, n_samples: int) -> list[str]:
    """Return optional sample labels, falling back to stable row indices."""

    sample_axis = getattr(dataset, "sample_axis", None)
    labels = getattr(sample_axis, "labels", None) if sample_axis is not None else None
    return [str(value) for value in (range(n_samples) if labels is None else labels)]


def _canonical_simca_parameters(parameters: dict[str, object]) -> dict[str, object]:
    """Return the sole closed parameter contract for canonical SIMCA."""

    expected = {"n_components", "confidence_level", "critical_limits_method"}
    if set(parameters) != expected:
        raise ValueError(
            "SIMCA parameters must contain exactly n_components, confidence_level, and critical_limits_method"
        )
    n_components = parameters["n_components"]
    confidence_level = parameters["confidence_level"]
    method = parameters["critical_limits_method"]
    if type(n_components) is not int or not 1 <= n_components <= _SIMCA_MAX_COMPONENTS:
        raise ValueError(f"SIMCA n_components must be an integer in [1, {_SIMCA_MAX_COMPONENTS}]")
    if (
        isinstance(confidence_level, bool)
        or not isinstance(confidence_level, (int, float))
        or not np.isfinite(confidence_level)
        or not 0.8 <= float(confidence_level) < 1.0
    ):
        raise ValueError("SIMCA confidence_level must be finite and in [0.8, 1.0)")
    if method not in {"ddmoments", "classical"}:
        raise ValueError("SIMCA critical_limits_method must be ddmoments or classical")
    return {
        "n_components": n_components,
        "confidence_level": float(confidence_level),
        "critical_limits_method": method,
    }


def _require_positive_limit(value: object, *, name: str, class_label: object) -> float:
    """Reject a statistically undefined class boundary instead of inventing one."""

    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"SIMCA {name} limit for class {class_label!r} is not numeric")
    limit = float(value)
    if not np.isfinite(limit) or limit <= 0.0:
        raise ValueError(f"SIMCA {name} limit for class {class_label!r} must be finite and positive")
    return limit


def _simca_fitted_state_from_extract(extract: SIMCAExtract) -> dict[str, object]:
    """Project one fitted SIMCA extract into its explicit artifact schema."""

    metadata, arrays = extract.to_artifact()
    return {
        "serializer": SIMCA_FITTED_STATE_SERIALIZER,
        "metadata": metadata,
        "arrays": {name: np.asarray(value).tolist() for name, value in arrays.items()},
    }


def _simca_extract_from_state(state: Any) -> SIMCAExtract:
    """Decode exact SIMCA identity, class limits, and per-class arrays."""

    if not isinstance(state, dict) or set(state) != {"serializer", "metadata", "arrays"}:
        raise ValueError("SIMCA fitted state must contain exact serializer, metadata, and arrays")
    if state["serializer"] != SIMCA_FITTED_STATE_SERIALIZER:
        raise ValueError("SIMCA fitted state has an unsupported serializer")
    metadata = state["metadata"]
    arrays = state["arrays"]
    expected_metadata = {"model_type", "n_components", "classes", "T2_limits", "Q_limits"}
    if (
        not isinstance(metadata, dict)
        or not expected_metadata.issubset(metadata)
        or set(metadata) - (expected_metadata | {"applicability"})
    ):
        raise ValueError("SIMCA fitted-state metadata is not closed")
    n_components = metadata["n_components"]
    if metadata["model_type"] != "simca" or type(n_components) is not int or n_components < 1:
        raise ValueError("SIMCA fitted state has invalid model identity or component count")
    classes = metadata["classes"]
    if (
        not isinstance(classes, list)
        or len(classes) < 2
        or len(set(classes)) != len(classes)
        or any(not isinstance(label, str) or not label for label in classes)
    ):
        raise ValueError("SIMCA fitted state has invalid class identity")
    for name in ("T2_limits", "Q_limits"):
        limits = metadata[name]
        if not isinstance(limits, dict) or set(limits) != set(classes):
            raise ValueError(f"SIMCA fitted state has incomplete {name}")
        if any(
            isinstance(value, bool) or not isinstance(value, (int, float)) or not np.isfinite(value) or value <= 0.0
            for value in limits.values()
        ):
            raise ValueError(f"SIMCA fitted state has invalid {name}")
    applicability = metadata.get("applicability")
    if applicability is not None:
        if not isinstance(applicability, dict) or set(applicability) != set(classes):
            raise ValueError("SIMCA fitted state has incomplete applicability evidence")
        from spectra_sherpa.sdk.canonical_applicability import validate_applicability_evidence

        try:
            for evidence in applicability.values():
                validate_applicability_evidence(evidence)
        except (TypeError, ValueError) as exc:
            raise ValueError("SIMCA fitted state has invalid applicability evidence") from exc
    if not isinstance(arrays, dict):
        raise ValueError("SIMCA fitted-state arrays must be a mapping")
    expected_arrays = {
        f"class_{index}_{suffix}"
        for index in range(len(classes))
        for suffix in ("loadings", "eigenvalues", "mean", "scale", "pca_mean")
    }
    if set(arrays) != expected_arrays:
        raise ValueError("SIMCA fitted-state arrays are not complete and closed")

    numeric_arrays: dict[str, np.ndarray] = {}
    feature_count: int | None = None
    for index, label in enumerate(classes):
        prefix = f"class_{index}_"
        loadings = np.asarray(arrays[f"{prefix}loadings"], dtype=np.float64)
        eigenvalues = np.asarray(arrays[f"{prefix}eigenvalues"], dtype=np.float64)
        mean = np.asarray(arrays[f"{prefix}mean"], dtype=np.float64)
        scale = np.asarray(arrays[f"{prefix}scale"], dtype=np.float64)
        pca_mean = np.asarray(arrays[f"{prefix}pca_mean"], dtype=np.float64)
        if loadings.ndim != 2 or loadings.shape[0] != n_components or loadings.shape[1] < 1:
            raise ValueError(f"SIMCA fitted state has invalid loadings for class {label!r}")
        if feature_count is None:
            feature_count = loadings.shape[1]
        if loadings.shape[1] != feature_count:
            raise ValueError("SIMCA fitted state has inconsistent feature dimensions")
        if eigenvalues.shape != (n_components,) or np.any(eigenvalues <= 0.0):
            raise ValueError(f"SIMCA fitted state has invalid eigenvalues for class {label!r}")
        if any(value.shape != (feature_count,) for value in (mean, scale, pca_mean)):
            raise ValueError(f"SIMCA fitted state has invalid centering or scaling shape for class {label!r}")
        if np.any(scale <= 0.0):
            raise ValueError(f"SIMCA fitted state has non-positive scaling for class {label!r}")
        if not all(np.isfinite(value).all() for value in (loadings, eigenvalues, mean, scale, pca_mean)):
            raise ValueError(f"SIMCA fitted state has non-finite arrays for class {label!r}")
        numeric_arrays.update(
            {
                f"{prefix}loadings": loadings,
                f"{prefix}eigenvalues": eigenvalues,
                f"{prefix}mean": mean,
                f"{prefix}scale": scale,
                f"{prefix}pca_mean": pca_mean,
            }
        )
    return SIMCAExtract.from_artifact(metadata, numeric_arrays)


def apply_simca_fitted_state(input_data: Any, state: Any) -> tuple[np.ndarray, np.ndarray]:
    """Apply a closed SIMCA state without guessing or defaulting class limits."""

    extract = _simca_extract_from_state(state)
    matrix = to_numpy_2d(bind_X(input_data, allow_array=True), name="input_data", dtype=np.float64)
    labels, affinity = extract.predict(matrix)
    return np.asarray(labels, dtype=object), np.asarray(affinity, dtype=np.float64)


def simca_acceptance_membership(input_data: Any, state: Any) -> tuple[tuple[str, ...], np.ndarray]:
    """Return exact per-class acceptance decisions from one closed fitted state."""

    extract = _simca_extract_from_state(state)
    matrix = to_numpy_2d(bind_X(input_data, allow_array=True), name="input_data", dtype=np.float64)
    membership = np.zeros((matrix.shape[0], len(extract.classes)), dtype=bool)
    for column, label in enumerate(extract.classes):
        loadings = extract.class_loadings[label]
        eigenvalues = np.maximum(extract.class_eigenvalues[label], 1e-12)
        class_mean = extract.class_means[label]
        class_scale = extract.class_scales.get(label) if extract.class_scales else None
        pca_mean = extract.pca_means.get(label) if extract.pca_means else None
        if class_scale is not None:
            working = (matrix - class_mean) / np.maximum(class_scale, 1e-12)
            pca_center = pca_mean if pca_mean is not None else np.zeros_like(class_mean)
            centered = working - pca_center
            reconstructed = centered @ loadings.T @ loadings + pca_center
            residual = working - reconstructed
        else:
            centered = matrix - class_mean
            reconstructed = centered @ loadings.T @ loadings
            residual = centered - reconstructed
        scores = centered @ loadings.T
        t2 = np.sum((scores**2) / eigenvalues, axis=1)
        q = np.sum(residual**2, axis=1)
        membership[:, column] = (t2 <= float(extract.T2_limits[label])) & (q <= float(extract.Q_limits[label]))
    return tuple(extract.classes), membership


def _simca_fitted_state_from_models(
    classes: Any,
    class_models: dict[Any, dict[str, Any]],
    t2_limits: dict[Any, float],
    q_limits: dict[Any, float],
    *,
    n_components: int,
) -> dict[str, object]:
    """Build the common state from live or generated per-class fit results."""

    # Keep the scientific leaf SDK import lazy.  Importing ``spectra_sherpa.sdk.data``
    # loads the built-in node registry, and must not initialize evidence-only
    # namespaces as a side effect.
    from spectra_sherpa.sdk.canonical_applicability import build_applicability_evidence

    class_values = list(classes)
    extract = SIMCAExtract(
        class_loadings={str(cls): np.asarray(class_models[cls]["loadings"], dtype=np.float64) for cls in class_values},
        class_eigenvalues={
            str(cls): np.asarray(class_models[cls]["eigenvalues"], dtype=np.float64) for cls in class_values
        },
        class_means={str(cls): np.asarray(class_models[cls]["x_mean"], dtype=np.float64) for cls in class_values},
        class_scales={str(cls): np.asarray(class_models[cls]["x_scale"], dtype=np.float64) for cls in class_values},
        pca_means={str(cls): np.asarray(class_models[cls]["pca_mean"], dtype=np.float64) for cls in class_values},
        applicability={
            str(cls): build_applicability_evidence(
                class_models[cls]["scores"],
                class_models[cls]["t2_calibration"],
                class_models[cls]["q_calibration"],
                t2_limit=float(t2_limits[cls]),
                q_limit=float(q_limits[cls]),
                method="simca_calibration_limits",
            )
            for cls in class_values
        },
        classes=[str(cls) for cls in class_values],
        T2_limits={str(key): float(value) for key, value in t2_limits.items()},
        Q_limits={str(key): float(value) for key, value in q_limits.items()},
        n_components=int(n_components),
    )
    return _simca_fitted_state_from_extract(extract)


def _simca_q_limit_from_residuals(residual_q: np.ndarray, confidence_level: float) -> float:
    """Return the classical moment-matched Q limit or reject undefined data."""
    from scipy.stats import chi2

    q = np.asarray(residual_q, dtype=np.float64)
    q = q[np.isfinite(q)]
    if q.size < 2:
        raise ValueError("classical SIMCA Q limits require at least two finite calibration residuals")
    mean_q = float(np.mean(q))
    var_q = float(np.var(q, ddof=1))
    if not np.isfinite(mean_q) or not np.isfinite(var_q) or mean_q <= 0.0 or var_q <= 0.0:
        raise ValueError("classical SIMCA Q limits require positive finite residual mean and variance")
    dof = 2.0 * mean_q * mean_q / var_q
    scale = var_q / (2.0 * mean_q)
    return _require_positive_limit(
        float(scale * chi2.ppf(confidence_level, dof)),
        name="Q",
        class_label="calibration",
    )


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

    if critical_limits_method not in {"ddmoments", "classical"}:
        raise ValueError("SIMCA critical_limits_method must be ddmoments or classical")

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
        eigenvalues = np.asarray(pca.explained_variance_[:n_components], dtype=np.float64)
        if not np.isfinite(eigenvalues).all() or np.any(eigenvalues <= 0.0):
            raise ValueError(f"SIMCA class {cls!r} has a non-positive or non-finite retained PCA variance")

        t2_class_cal = np.sum((scores_data**2) / eigenvalues, axis=1)
        recon_class = scores_data @ loadings_data + pca.mean_
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
        elif critical_limits_method == "classical":
            alpha = 1 - confidence_level
            df2 = n_class_samples - n_components
            if df2 <= 0:
                raise ValueError(f"SIMCA class {cls!r} does not have positive residual degrees of freedom")
            F_crit = f.ppf(1 - alpha, n_components, df2)
            T2_limit = (n_components * (n_class_samples - 1) * (n_class_samples + 1)) / (n_class_samples * df2) * F_crit

            Q_limit = _simca_q_limit_from_residuals(q_class_cal, confidence_level)

        T2_limit = _require_positive_limit(T2_limit, name="T2", class_label=cls)
        Q_limit = _require_positive_limit(Q_limit, name="Q", class_label=cls)

        class_models[cls] = {
            "pca": pca,
            "scaler": scaler,
            "scores": scores_data,
            "t2_calibration": t2_class_cal,
            "q_calibration": q_class_cal,
            "loadings": loadings_data,
            "eigenvalues": eigenvalues,
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
            reconstructed = t @ loadings + pca.mean_
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
        reconstructed = scores @ loadings + pca.mean_
        t2[:, j] = np.sum((scores**2) / eigenvalues, axis=1)
        q[:, j] = np.sum((scaled - reconstructed) ** 2, axis=1)

    t2_limits = np.asarray(
        [_require_positive_limit(T2_limits[cls], name="T2", class_label=cls) for cls in classes],
        dtype=np.float64,
    )
    q_limits = np.asarray(
        [_require_positive_limit(Q_limits[cls], name="Q", class_label=cls) for cls in classes],
        dtype=np.float64,
    )
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
    sample_labels: list[str],
) -> dict[str, Any]:
    """Build a Q-vs-T² acceptance plot in each sample's nearest class space."""
    x_vals: list[float] = []
    y_vals: list[float] = []
    text: list[str] = []
    symbols: list[str] = []
    nearest_labels: list[str] = []

    for i, class_idx in enumerate(nearest_class_idx.tolist()):
        cls = classes[class_idx]
        x_norm = float(t2[i, class_idx] / _require_positive_limit(T2_limits[cls], name="T2", class_label=cls))
        y_norm = float(q[i, class_idx] / _require_positive_limit(Q_limits[cls], name="Q", class_label=cls))
        x_vals.append(x_norm)
        y_vals.append(y_norm)
        pred = str(predicted_labels[i])
        truth = str(true_labels[i])
        nearest = str(cls)
        text.append(
            f"{sample_labels[i]}<br>True: {truth}<br>Predicted: {pred}<br>"
            f"Nearest class model: {nearest}<br>T²/limit: {x_norm:.3g}<br>Q/limit: {y_norm:.3g}"
        )
        symbols.append("x" if pred == SIMCA_REJECT_LABEL else "circle")
        nearest_labels.append(nearest)

    class_colors = ("#2563eb", "#dc2626", "#16a34a", "#d97706", "#7c3aed", "#0891b2")
    sample_traces: list[dict[str, Any]] = []
    for class_index, cls in enumerate(classes):
        indices = [index for index, nearest in enumerate(nearest_labels) if nearest == str(cls)]
        sample_traces.append(
            {
                "x": [x_vals[index] for index in indices],
                "y": [y_vals[index] for index in indices],
                "type": "scatter",
                "mode": "markers",
                "marker": {
                    "size": 9,
                    "color": class_colors[class_index % len(class_colors)],
                    "symbol": [symbols[index] for index in indices],
                },
                "text": [text[index] for index in indices],
                "hovertemplate": "%{text}<extra></extra>",
                "name": f"Nearest: {cls}",
            }
        )

    return {
        "plot_type": "scatter",
        "data": [
            *sample_traces,
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
            "title": {
                "text": (
                    "SIMCA acceptance diagnostics"
                    "<br><sup>Each sample is shown in its nearest class model; acceptance requires both limits.</sup>"
                ),
                "x": 0.02,
                "xanchor": "left",
            },
            "margin": {"t": 88},
            "xaxis": {"title": "Hotelling T² / class limit"},
            "yaxis": {"title": "Q residual / class limit"},
            "legend": {"title": {"text": "Nearest class model"}},
        },
        "metadata": {
            "type": "simca_acceptance",
            "class_labels": [str(c) for c in classes],
            "boundary": "accepted when T²/limit <= 1 and Q/limit <= 1",
        },
    }


def _simca_inputs(X: Any, y: Any) -> tuple[Any, np.ndarray, np.ndarray]:
    """Bind one finite feature matrix and one categorical target vector."""

    dataset = bind_X(
        X,
        missing_message="Missing required input: X (features)",
        dataset_error_message="X must be a dataset or two-dimensional array",
        allow_array=True,
    )
    labels = bind_y(
        y,
        X=dataset,
        required=True,
        infer_from_X=True,
        target_type="categorical",
        missing_message=(
            "Missing required input: y (class labels)\n"
            "Either provide labels via the y input port, or use a dataset with labels in X.y"
        ),
        dataset_missing_message="Dataset passed to y has no embedded class labels",
    )
    matrix = to_numpy_2d(dataset, name="X", dtype=np.float64)
    if matrix.shape[0] < 4 or matrix.shape[1] < 1 or not np.isfinite(matrix).all():
        raise ValueError("SIMCA X must contain at least four finite samples and one feature")
    target = _prepare_class_labels(labels, matrix.shape[0])
    if np.any(target == SIMCA_REJECT_LABEL):
        raise ValueError(f"SIMCA reserves {SIMCA_REJECT_LABEL!r} for rejected predictions")
    return dataset, np.array(matrix, dtype=np.float64, copy=True), target


def _simca_scientific_core(X: Any, y: Any, *, parameters: dict[str, object]) -> dict[str, Any]:
    """Fit class-wise PCA models once and report calibration diagnostics."""

    params = _canonical_simca_parameters(parameters)
    dataset, matrix, target = _simca_inputs(X, y)
    classes, class_counts = np.unique(target, return_counts=True)
    if classes.size < 2:
        raise ValueError(f"SIMCA requires at least two classes, got {classes.size}")
    if int(params["n_components"]) >= int(class_counts.min()):
        raise ValueError("SIMCA n_components must be smaller than every class sample count")
    if int(params["n_components"]) > matrix.shape[1]:
        raise ValueError("SIMCA n_components must not exceed the feature count")

    class_models, t2_limits, q_limits, limit_diagnostics = _fit_simca_class_models(
        matrix,
        target,
        classes,
        n_components=int(params["n_components"]),
        confidence_level=float(params["confidence_level"]),
        critical_limits_method=str(params["critical_limits_method"]),
    )
    predictions, distances, class_distance_matrix, accepted_classes, membership_matrix = _predict_simca(
        matrix,
        classes,
        class_models,
        t2_limits,
        q_limits,
    )
    t2_matrix, q_matrix, nearest_class_idx, combined_distance = _simca_t2_q_diagnostics(
        matrix,
        classes,
        class_models,
        t2_limits,
        q_limits,
    )

    train_metrics = _classification_scalar_metrics(target, predictions, classes, prefix="train_")
    train_confusion, train_confusion_labels = _simca_calibration_confusion(target, predictions, classes)
    n_rejected = int(np.sum(predictions == SIMCA_REJECT_LABEL))
    metrics = _classification_metrics_contract(
        classes=classes,
        train_metrics=train_metrics,
        primary_split="train",
        method="simca",
        confusion_matrices={"train": train_confusion.tolist()},
        extra={
            "n_components": int(params["n_components"]),
            "confidence_level": float(params["confidence_level"]),
            "critical_limits_method": str(params["critical_limits_method"]),
            "evidence_scope": "calibration_fit_diagnostics_not_validation_evidence",
            "n_samples": int(target.size),
            "n_rejected": n_rejected,
            "rejection_rate": float(n_rejected / target.size),
            "confusion_matrix_labels": {"train": [str(value) for value in train_confusion_labels]},
        },
    )
    first_class = classes[0]
    first_model = class_models[first_class]
    display_scores = first_model["pca"].transform(first_model["scaler"].transform(matrix)).astype(np.float64)
    for value in (class_distance_matrix, t2_matrix, q_matrix, combined_distance, display_scores):
        if not np.isfinite(value).all():
            raise RuntimeError("SIMCA produced non-finite numeric output")
    return {
        "dataset": dataset,
        "matrix": matrix,
        "target": target,
        "classes": classes,
        "class_models": class_models,
        "T2_limits": t2_limits,
        "Q_limits": q_limits,
        "limit_diagnostics": limit_diagnostics,
        "predictions": predictions,
        "distances": distances,
        "class_distance_matrix": class_distance_matrix,
        "accepted_classes": accepted_classes,
        "membership_matrix": membership_matrix,
        "t2_matrix": t2_matrix,
        "q_matrix": q_matrix,
        "nearest_class_idx": nearest_class_idx,
        "train_metrics": train_metrics,
        "train_confusion": train_confusion,
        "train_confusion_labels": train_confusion_labels,
        "metrics": metrics,
        "display_scores": display_scores,
        "parameters": params,
        "fitted_state": _simca_fitted_state_from_models(
            classes,
            class_models,
            t2_limits,
            q_limits,
            n_components=int(params["n_components"]),
        ),
    }


def _simca_export_outputs(X: Any, y: Any, *, parameters: dict[str, object]) -> dict[str, Any]:
    """Project shared SIMCA computation into portable generated-Python outputs."""

    core_result = _simca_scientific_core(X, y, parameters=parameters)
    plots = {
        "confusion_matrix_train": generate_confusion_matrix_heatmap(
            core_result["train_confusion"],
            core_result["train_confusion_labels"],
            "Confusion Matrix (Training Set)",
        ),
        "simca_acceptance": _generate_simca_acceptance_plot(
            t2=core_result["t2_matrix"],
            q=core_result["q_matrix"],
            nearest_class_idx=core_result["nearest_class_idx"],
            classes=core_result["classes"],
            T2_limits=core_result["T2_limits"],
            Q_limits=core_result["Q_limits"],
            true_labels=core_result["target"],
            predicted_labels=core_result["predictions"],
            sample_labels=_sample_labels_or_indices(core_result["dataset"], core_result["matrix"].shape[0]),
        ),
    }
    acceptance_visualization = plots["simca_acceptance"]
    confusion_visualization = plots["confusion_matrix_train"]
    return {
        "default": core_result["display_scores"],
        "fitted_state": core_result["fitted_state"],
        "predictions": core_result["predictions"],
        "class_assignment": core_result["predictions"],
        "distances": core_result["distances"],
        "class_distance_matrix": core_result["class_distance_matrix"],
        "accepted_classes": core_result["accepted_classes"],
        "membership_matrix": core_result["membership_matrix"],
        "t2_matrix": core_result["t2_matrix"],
        "q_matrix": core_result["q_matrix"],
        "n_rejected": int(core_result["metrics"]["n_rejected"]),
        "rejection_rate": float(core_result["metrics"]["rejection_rate"]),
        "metrics": core_result["metrics"],
        "train_accuracy": float(core_result["train_metrics"]["train_accuracy"]),
        "confusion_matrix": core_result["train_confusion"],
        "confusion_matrix_train": core_result["train_confusion"],
        "plots": plots,
        "acceptance_visualization": acceptance_visualization,
        "confusion_visualization": confusion_visualization,
        "metadata": {
            "y_true": core_result["target"].tolist(),
            "y_pred": core_result["predictions"].tolist(),
            "label_categories": [str(value) for value in core_result["classes"]],
            "sample_classes": [str(value) for value in core_result["target"]],
            "evidence_scope": "calibration_fit_diagnostics_not_validation_evidence",
        },
    }


@register_node
class SIMCANode(Node):
    """
    SIMCA (Soft Independent Modeling of Class Analogy) classification node.

    Builds separate PCA model for each class and classifies based on distance to class models.
    Uses Hotelling T² and Q residuals to assess class membership.

    Fits one independent PCA acceptance model per supplied class and compares
    samples against every class boundary. This training node reports only
    calibration diagnostics; validation requires an explicit held-out or
    grouped fold plan.

    Reference: Wold & Sjöström (1977), Chemometrics: Theory and Application
    """

    metadata = NodeMetadata(
        policy=NodePolicy(),
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
                max_value=_SIMCA_MAX_COMPONENTS,
                max_value_reason="Bounds per-class PCA fit and cross-validation cost in the interactive runtime.",
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
        ],
        input_types=["SherpaDataset", "array"],
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
                type_ref="spectrasherpa://types/TargetMatrix/1.0",
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
                name="fitted_state",
                type_ref="spectrasherpa://types/ClassificationModel/1.0",
                required=True,
                label="Fitted SIMCA State",
                description="Explicit class PCA state and complete T2/Q limits produced by this training node",
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
                type_ref="spectrasherpa://types/StatisticsSummary/1.0",
                required=False,
                label="Classification Metrics",
                description="Calibration-fit diagnostics; use an explicit evaluator for validation metrics",
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
            PortMetadata(
                name="acceptance_visualization",
                type_ref="spectrasherpa://types/Visualization/1.0",
                required=True,
                label="SIMCA Acceptance Diagnostics",
                description="Nearest-class normalized T2 and Q diagnostics with acceptance limits",
            ),
            PortMetadata(
                name="confusion_visualization",
                type_ref="spectrasherpa://types/Visualization/1.0",
                required=True,
                label="Calibration Confusion Matrix",
                description="Calibration-fit confusion counts; not held-out validation evidence",
            ),
        ],
        # The canonical implementation is NumPy/scikit-learn class-wise PCA.
        # The canonical SherpaDataset is projected into the finite ndarray used
        # by the NumPy/scikit-learn implementation before fitting.
        help_url="docs/nodes/classification/simca",
        canonical_parameter_validator=_canonical_simca_parameters,
        presentation_contract=NodePresentationContract(
            default_presentation="acceptance",
            presentations=(
                ScientificPresentation(
                    "acceptance",
                    "SIMCA Acceptance Diagnostics",
                    "visualization",
                    ("acceptance_visualization",),
                    ("plot", "table"),
                    "Nearest class-model T2 and Q values normalized by their acceptance limits.",
                ),
                ScientificPresentation(
                    "class_distances",
                    "Class Distance Matrix",
                    "numeric_matrix",
                    ("class_distance_matrix",),
                    ("table",),
                    "Per-sample combined normalized distance to every class model.",
                ),
                ScientificPresentation(
                    "metrics",
                    "Calibration-Fit Metrics",
                    "metric_record",
                    ("metrics",),
                    ("record", "table"),
                    "Training-fit diagnostics; use the held-out evaluator for performance claims.",
                ),
                ScientificPresentation(
                    "calibration_confusion",
                    "Calibration Confusion Matrix",
                    "visualization",
                    ("confusion_visualization",),
                    ("plot", "table"),
                    "Training-fit class confusion; not held-out validation evidence.",
                ),
                ScientificPresentation(
                    "first_class_projection",
                    "First-Class Projection Coordinates",
                    "score_matrix",
                    ("default",),
                    ("table",),
                    "All samples projected into the first class PCA model for numeric inspection only.",
                ),
            ),
        ),
    )

    def generate_python(
        self,
        inputs: dict[str, str],
        indent: str = "    ",
        use_scp: bool = True,
    ) -> list[str]:
        """Generate Python that calls the same scientific operation as the DAG."""

        del use_scp
        X_expression = inputs.get("X", inputs.get("default", "input_data"))
        return [
            f"{indent}# --- Canonical SIMCA Classifier ({self.node_id}) ---",
            f"{indent}from spectra_sherpa.app.services.dag.nodes.classification.simca_nodes import "
            "_simca_export_outputs",
            f"{indent}results[{self.node_id!r}] = _simca_export_outputs(",
            f"{indent}    {X_expression}, {inputs.get('y', 'None')}, parameters={self._resolve_params()!r},",
            f"{indent})",
        ]

    async def execute(self, X: Any = None, y: Any = None, **kwargs) -> Any:
        """
        Execute SIMCA classification.

        Args:
            X: SherpaDataset containing feature data
            y: Class labels

        Returns:
            SIMCA model with classification results
        """
        del kwargs
        from sklearn.metrics import classification_report

        core_result = _simca_scientific_core(X, y, parameters=self._resolve_params())
        X_ds = core_result["dataset"]
        if not hasattr(X_ds, "sample_axis"):
            raise ValueError("Interactive SIMCA execution requires a dataset with a sample axis")
        y_array = core_result["target"]
        classes = core_result["classes"]
        T2_limits = core_result["T2_limits"]
        Q_limits = core_result["Q_limits"]
        dd_limit_diagnostics = core_result["limit_diagnostics"]
        predictions = core_result["predictions"]
        distances = core_result["distances"]
        class_distance_matrix = core_result["class_distance_matrix"]
        accepted_classes = core_result["accepted_classes"]
        membership_matrix = core_result["membership_matrix"]
        t2_matrix = core_result["t2_matrix"]
        q_matrix = core_result["q_matrix"]
        nearest_class_idx = core_result["nearest_class_idx"]
        train_metrics = core_result["train_metrics"]
        cm_train = core_result["train_confusion"]
        classification_metrics = core_result["metrics"]
        viz_scores_data = core_result["display_scores"]
        fitted_state = core_result["fitted_state"]
        params = core_result["parameters"]
        n_components = int(params["n_components"])
        confidence_level = float(params["confidence_level"])
        critical_limits_method = str(params["critical_limits_method"])
        train_accuracy = float(train_metrics["train_accuracy"])
        class_report = classification_report(
            y_array,
            predictions,
            labels=classes,
            target_names=[str(value) for value in classes],
            output_dict=True,
            zero_division=0,
        )
        first_class = classes[0]
        label_categories = [str(value) for value in classes]

        # Get input coordinates for dataset creation
        _y_coord = X_ds.sample_axis

        # Generate plots
        plots = {}
        plots["confusion_matrix_train"] = generate_confusion_matrix_heatmap(
            cm_train, core_result["train_confusion_labels"], "Confusion Matrix (Training Set)"
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
            sample_labels=_sample_labels_or_indices(X_ds, len(y_array)),
        )
        acceptance_visualization = plots["simca_acceptance"]
        confusion_visualization = plots["confusion_matrix_train"]

        # =====================================================================
        # Create SherpaDataset output with proper coordinate coupling
        # =====================================================================

        # Build PC labels for the visualization scores (projected into first class PC space)
        pc_labels = [f"PC{i + 1} (Class {first_class})" for i in range(n_components)]

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
                "confusion_matrix": cm_train.tolist(),
                "confusion_matrix_train": cm_train.tolist(),
                "metrics": classification_metrics,
                "classification_report": class_report,
                "y_true": y_array.tolist(),
                "y_pred": predictions.tolist(),
                "accepted_classes": accepted_classes,
                "membership_matrix": membership_matrix.tolist(),
                "t2_matrix": t2_matrix.tolist(),
                "q_matrix": q_matrix.tolist(),
                "n_rejected": int(np.sum(predictions == SIMCA_REJECT_LABEL)),
                "rejection_rate": float(np.mean(predictions == SIMCA_REJECT_LABEL)),
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
                    "n_components": int(n_components),
                    "n_classes": int(len(classes)),
                    "n_rejected": int(np.sum(predictions == SIMCA_REJECT_LABEL)),
                    "rejection_rate": float(np.mean(predictions == SIMCA_REJECT_LABEL)),
                    "confidence_level": float(confidence_level),
                    "critical_limits_method": critical_limits_method,
                    "scope": "calibration_fit_diagnostics_not_validation_evidence",
                },
            }
        )

        logger.debug("Train accuracy: %.3f with %d PCs per class", train_accuracy, n_components)

        simca_extract = _simca_extract_from_state(fitted_state)
        artifact = _artifact_builder.build_model_artifact(
            simca_extract,
            X_ds,
            node_id=self.node_id,
            metrics={
                "train_accuracy": float(train_accuracy),
                "train_balanced_accuracy": float(train_metrics["train_balanced_accuracy"]),
                "train_f1_macro": float(train_metrics["train_f1_macro"]),
                "train_precision_macro": float(train_metrics["train_precision_macro"]),
                "train_recall_macro": float(train_metrics["train_recall_macro"]),
                "train_sensitivity_macro": float(train_metrics["train_sensitivity_macro"]),
                "train_specificity_macro": float(train_metrics["train_specificity_macro"]),
                "classification_metrics": classification_metrics,
                "scope": "calibration_fit_diagnostics_not_validation_evidence",
                "n_classes": int(len(classes)),
                "critical_limits_method": critical_limits_method,
            },
        )

        # SherpaDataset-only return: one serialization boundary at API layer
        return NodeResult(
            outputs={
                "default": scores_dataset,  # SherpaDataset: viz scores (n_samples, n_components)
                "fitted_state": fitted_state,
                "predictions": predictions.tolist(),
                "class_assignment": predictions.tolist(),
                "distances": distances,
                "class_distance_matrix": class_distance_matrix.tolist(),
                "accepted_classes": accepted_classes,
                "membership_matrix": membership_matrix.tolist(),
                "t2_matrix": t2_matrix.tolist(),
                "q_matrix": q_matrix.tolist(),
                "n_rejected": int(np.sum(predictions == SIMCA_REJECT_LABEL)),
                "rejection_rate": float(np.mean(predictions == SIMCA_REJECT_LABEL)),
                "metrics": classification_metrics,
                "train_accuracy": float(train_accuracy),
                "train_balanced_accuracy": float(train_metrics["train_balanced_accuracy"]),
                "train_f1_macro": float(train_metrics["train_f1_macro"]),
                "train_precision_macro": float(train_metrics["train_precision_macro"]),
                "train_recall_macro": float(train_metrics["train_recall_macro"]),
                "train_sensitivity_macro": float(train_metrics["train_sensitivity_macro"]),
                "train_specificity_macro": float(train_metrics["train_specificity_macro"]),
                "confusion_matrix": cm_train.tolist(),
                "confusion_matrix_train": cm_train.tolist(),
                "plots": plots,  # Pre-built Plotly traces (legitimate visualization output)
                "acceptance_visualization": acceptance_visualization,
                "confusion_visualization": confusion_visualization,
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
                "metrics": classification_metrics,
                "n_classes": len(classes),
                "n_rejected": int(np.sum(predictions == SIMCA_REJECT_LABEL)),
                "rejection_rate": float(np.mean(predictions == SIMCA_REJECT_LABEL)),
                "critical_limits_method": critical_limits_method,
                "evidence_scope": "calibration_fit_diagnostics_not_validation_evidence",
            },
        )

    def fit_fitted_state(self, input_data: Any, target: Any) -> dict[str, object]:
        """Fit the same closed state used by interactive and generated execution."""

        core_result = _simca_scientific_core(input_data, target, parameters=self._resolve_params())
        return core_result["fitted_state"]

    def apply_fitted_state(self, input_data: Any, state: Any) -> np.ndarray:
        """Apply the canonical SIMCA state and return class-distance features."""

        _labels, distances = apply_simca_fitted_state(input_data, state)
        return distances

    def predict_fitted_labels(self, input_data: Any, state: Any) -> np.ndarray:
        """Return SIMCA decisions for the shared held-out fold executor."""

        labels, _distances = apply_simca_fitted_state(input_data, state)
        return labels


bind_stable_execution_contract(
    SIMCANode,
    runtime_family=RuntimeFamily.SHERPA_NATIVE,
    lifecycle_kind=LifecycleKind.FITTED_MODEL,
    implementation_id="spectrasherpa.classification.simca",
    implementation_version="2.1.0",
    required_worker_capabilities=(WorkerCapability.READ_DATASET,),
    managed_optimization_eligibility=(
        ManagedOptimizationEligibility.LOCAL,
        ManagedOptimizationEligibility.DEVELOPMENT,
        ManagedOptimizationEligibility.FULL_REFIT,
    ),
    sample_effect="preserves_samples",
    feature_effect="generates_features",
    axis_effect="changes_axis",
    unit_effect="changes_units",
    resource_hints={"timeout_seconds": 60, "cpu_seconds": 60, "memory_bytes": 1_073_741_824},
    license_id="BSD-3-Clause",
    help_reference="docs/nodes/classification.md",
    implementation_distributions=("numpy", "scipy", "scikit-learn"),
    runtime_requirements=(
        ("numpy", "1.26.4"),
        ("scipy", "1.17.1"),
        ("scikit-learn", "1.9.0"),
    ),
    managed_optimization_profiles=("first_party_pls",),
    citations=(
        "Wold & Sjostrom, SIMCA: A method for analyzing chemical data in terms of similarity and analogy, "
        "Chemometrics: Theory and Application (1977) 243-282",
        "Pomerantsev, Acceptance areas for multivariate classification derived by projection methods, "
        "Journal of Chemometrics 22 (2008) 601-609",
        "Kucheryavskiy, mdatools SIMCA documentation and class-model distance conventions",
    ),
    implementation_modules=(
        fitted_state,
        dag_io_contracts,
        meta_helpers,
        modeling_core_utils,
        visualization,
        core_utils,
        _chemometric_diagnostics,
        _artifact_builder,
    ),
    fitted_state_serializer=SIMCA_FITTED_STATE_SERIALIZER,
    deterministic=True,
    target_access=TargetAccess.FIT_ONLY,
    group_access="none",
    supervised_task="classification",
)
