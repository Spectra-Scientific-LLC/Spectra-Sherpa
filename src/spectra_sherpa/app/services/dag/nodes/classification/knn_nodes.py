"""
K-Nearest Neighbors classification nodes.
"""

from __future__ import annotations

import logging
from typing import Any

import numpy as np

from spectra_sherpa.app.lib import fitted_state
from spectra_sherpa.app.lib.fitted_state import KNNExtract
from spectra_sherpa.app.services.dag import io_contracts as dag_io_contracts
from spectra_sherpa.app.services.dag import meta_helpers
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
from .. import visualization
from ..modeling import _artifact_builder, create_spectral_dataset
from ..modeling import core_utils as modeling_core_utils
from ..visualization import generate_confusion_matrix_heatmap
from . import core_utils, knn_core
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

_KNN_RANDOM_SEED = 42
_KNN_MAX_NEIGHBORS = 50
KNN_FITTED_STATE_SERIALIZER = "spectrasherpa.model-artifact.knn/1"
_KNN_CLASS_COLORS = ("#2563eb", "#dc2626", "#16a34a", "#d97706", "#7c3aed", "#0891b2")


def _knn_display_projection(matrix: np.ndarray) -> tuple[np.ndarray, list[str]]:
    """Return deterministic display coordinates that never feed the classifier."""

    if matrix.shape[1] <= 10:
        return (
            np.array(matrix, dtype=np.float64, copy=True),
            [f"Feature {index + 1}" for index in range(matrix.shape[1])],
        )

    from sklearn.decomposition import PCA

    component_count = min(5, matrix.shape[0], matrix.shape[1])
    # ``auto`` selects randomized SVD for common large spectral matrices. A
    # fixed seed makes this display-only projection exactly reproducible while
    # retaining the bounded cost of the randomized solver.
    display_model = PCA(
        n_components=component_count,
        svd_solver="randomized",
        random_state=_KNN_RANDOM_SEED,
    )
    display_matrix = np.asarray(display_model.fit_transform(matrix), dtype=np.float64)
    explained = np.asarray(display_model.explained_variance_ratio_, dtype=np.float64)
    labels = [f"PC{index + 1} ({explained[index] * 100:.1f}%)" for index in range(component_count)]
    return display_matrix, labels


def _knn_calibration_map(
    matrix: np.ndarray,
    labels: list[str],
    target: np.ndarray,
    classes: np.ndarray,
    sample_labels: list[str],
) -> dict[str, Any]:
    """Render class identity in a display-only projection of KNN model space."""

    if matrix.shape[1] == 1:
        coordinates = np.column_stack((matrix[:, 0], np.zeros(matrix.shape[0])))
        axis_labels = (labels[0], "Zero reference")
    else:
        coordinates = matrix[:, :2]
        axis_labels = (labels[0], labels[1])
    traces: list[dict[str, Any]] = []
    for index, cls in enumerate(classes):
        mask = target == cls
        traces.append(
            {
                "type": "scatter",
                "mode": "markers",
                "name": str(cls),
                "x": coordinates[mask, 0].tolist(),
                "y": coordinates[mask, 1].tolist(),
                "text": [sample_labels[row] for row in np.flatnonzero(mask)],
                "marker": {
                    "color": _KNN_CLASS_COLORS[index % len(_KNN_CLASS_COLORS)],
                    "size": 9,
                    "opacity": 0.8,
                },
                "hovertemplate": "%{text}<br>%{x:.4g}, %{y:.4g}<extra>%{fullData.name}</extra>",
            }
        )
    return {
        "data": traces,
        "layout": {
            "title": {
                "text": (
                    "KNN calibration-space map"
                    "<br><sup>Projection is for inspection; neighbor search used all model-space variables.</sup>"
                ),
                "x": 0.02,
                "xanchor": "left",
            },
            "margin": {"t": 88},
            "xaxis": {"title": {"text": axis_labels[0]}},
            "yaxis": {"title": {"text": axis_labels[1]}},
            "legend": {"title": {"text": "Known class"}},
        },
        "metadata": {
            "projection_scope": "display_only",
            "distance_space": "autoscaled" if labels[0].startswith("PC") else "model_space",
            "n_samples": int(matrix.shape[0]),
            "n_classes": int(classes.size),
        },
    }


def _canonical_knn_parameters(parameters: dict[str, object]) -> dict[str, object]:
    """Return the closed scientist-facing KNN parameter record."""

    expected = {"n_neighbors", "weights", "metric", "scale"}
    if set(parameters) != expected:
        raise ValueError(f"KNN parameters must contain exactly {', '.join(sorted(expected))}")

    integers: dict[str, int] = {}
    for name, lower, upper in (("n_neighbors", 1, _KNN_MAX_NEIGHBORS),):
        value = parameters[name]
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not np.isfinite(value)
            or int(value) != value
        ):
            raise ValueError(f"KNN {name} must be an exact integer")
        integers[name] = int(value)
        if not lower <= integers[name] <= upper:
            raise ValueError(f"KNN {name} must be between {lower} and {upper}")

    weights = parameters["weights"]
    if weights not in {"uniform", "distance"}:
        raise ValueError("KNN weights must be uniform or distance")
    metric = parameters["metric"]
    if metric not in {"euclidean", "manhattan", "chebyshev", "minkowski"}:
        raise ValueError("KNN metric must be euclidean, manhattan, chebyshev, or minkowski")
    scale = parameters["scale"]
    if not isinstance(scale, bool):
        raise ValueError("KNN scale must be boolean")
    return {
        "n_neighbors": integers["n_neighbors"],
        "weights": weights,
        "metric": metric,
        "scale": scale,
    }


def _knn_inputs(X: Any, y: Any) -> tuple[Any, np.ndarray, np.ndarray]:
    """Bind finite predictors and one non-empty categorical label per row."""

    dataset = bind_X(
        X,
        missing_message="Train KNN Classifier: missing required input X",
        dataset_error_message="KNN X must be a dataset or two-dimensional numeric array",
        allow_array=True,
    )
    labels = bind_y(
        y,
        X=dataset,
        required=True,
        infer_from_X=True,
        target_type="categorical",
        missing_message=("Train KNN Classifier requires one class label per sample through y or the dataset target"),
        dataset_missing_message="The KNN y dataset does not contain one class label per sample",
    )
    matrix = to_numpy_2d(dataset, name="X", dtype=np.float64)
    if matrix.shape[0] < 4 or matrix.shape[1] < 1 or not np.isfinite(matrix).all():
        raise ValueError("KNN X must contain at least four finite samples and one feature")
    target = _prepare_class_labels(labels, matrix.shape[0])
    return dataset, np.array(matrix, dtype=np.float64, copy=True), target


def _knn_estimator(parameters: dict[str, object]):
    """Build the sole deterministic KNN estimator used for fit and replay."""

    return knn_core.build_knn_estimator(
        n_neighbors=int(parameters["n_neighbors"]),
        weights=str(parameters["weights"]),
        metric=str(parameters["metric"]),
        scale=bool(parameters["scale"]),
    )


def _knn_scientific_core(
    X: Any,
    y: Any,
    *,
    parameters: dict[str, object],
) -> dict[str, Any]:
    """Fit KNN once and report calibration diagnostics only.

    Validation is deliberately absent from this training operation. Held-out
    or grouped evidence belongs to the shared fold executor or to an explicit
    split/apply/evaluator graph, where the partition is visible and reusable.
    """

    from sklearn.metrics import confusion_matrix

    params = _canonical_knn_parameters(parameters)
    dataset, matrix, target = _knn_inputs(X, y)
    classes = np.unique(target)
    if classes.size < 2:
        raise ValueError("KNN requires at least two classes")
    if int(params["n_neighbors"]) > matrix.shape[0]:
        raise ValueError("KNN n_neighbors must not exceed the number of training rows")

    model = _knn_estimator(params)
    model.fit(matrix, target)
    train_predictions = np.asarray(model.predict(matrix), dtype=object)
    train_probabilities = np.asarray(model.predict_proba(matrix), dtype=np.float64)
    if bool(params["scale"]):
        model_matrix = np.asarray(model.named_steps["scale"].transform(matrix), dtype=np.float64)
        neighbor_model = model.named_steps["knn"]
    else:
        model_matrix = matrix
        neighbor_model = model
    distances, neighbor_indices = neighbor_model.kneighbors(
        model_matrix,
        n_neighbors=int(params["n_neighbors"]),
        return_distance=True,
    )

    # This projection is a display coordinate system only; it never feeds the
    # classifier. Keep it in the shared operation so live and exported DAGs do
    # not silently disagree about the node's declared ``default`` output.
    display_matrix, display_labels = _knn_display_projection(model_matrix)

    train_metrics = _classification_scalar_metrics(target, train_predictions, classes, prefix="train_")
    train_confusion = confusion_matrix(target, train_predictions, labels=classes)
    metrics = _classification_metrics_contract(
        classes=classes,
        train_metrics=train_metrics,
        primary_split="train",
        method="knn",
        confusion_matrices={"train": train_confusion.tolist()},
        extra={
            "n_neighbors": int(params["n_neighbors"]),
            "distance_metric": str(params["metric"]),
            "weights": str(params["weights"]),
            "scale": bool(params["scale"]),
            "evidence_scope": "calibration_fit_diagnostics_not_validation_evidence",
        },
    )
    for value in (train_probabilities, distances):
        if not np.isfinite(value).all():
            raise RuntimeError("KNN produced non-finite numeric output")
    return {
        "dataset": dataset,
        "matrix": matrix,
        "target": target,
        "classes": classes,
        "model": model,
        "model_matrix": model_matrix,
        "display_matrix": display_matrix,
        "display_labels": display_labels,
        "train_predictions": train_predictions,
        "train_probabilities": train_probabilities,
        "distances": np.asarray(distances, dtype=np.float64),
        "neighbor_indices": np.asarray(neighbor_indices, dtype=np.int64),
        "train_metrics": train_metrics,
        "train_confusion": train_confusion,
        "metrics": metrics,
        "parameters": params,
    }


def _knn_export_outputs(X: Any, y: Any, *, parameters: dict[str, object]) -> dict[str, Any]:
    """Project the shared KNN computation into portable generated-Python outputs."""

    core = _knn_scientific_core(X, y, parameters=parameters)
    train_metrics = core["train_metrics"]
    confusion_visualization = generate_confusion_matrix_heatmap(
        core["train_confusion"], core["classes"], "KNN Training Confusion Matrix"
    )
    sample_axis = getattr(core["dataset"], "sample_axis", None)
    raw_labels = getattr(sample_axis, "labels", None)
    sample_labels = (
        [str(value) for value in raw_labels]
        if raw_labels is not None
        else [f"Sample {index + 1}" for index in range(core["matrix"].shape[0])]
    )
    calibration_map = _knn_calibration_map(
        core["display_matrix"],
        core["display_labels"],
        core["target"],
        core["classes"],
        sample_labels,
    )
    plots = {"confusion_matrix_train": confusion_visualization, "calibration_map": calibration_map}
    return {
        "default": core["display_matrix"],
        "fitted_state": _knn_fitted_state_from_core(core),
        "predictions": core["train_predictions"],
        "probabilities": core["train_probabilities"],
        "class_probabilities": core["train_probabilities"],
        "distances": core["distances"],
        "neighbor_indices": core["neighbor_indices"],
        "train_accuracy": float(train_metrics["train_accuracy"]),
        "confusion_matrix": core["train_confusion"],
        "confusion_matrix_train": core["train_confusion"],
        "plots": plots,
        "metrics": core["metrics"],
        "visualization": calibration_map,
        "confusion_visualization": confusion_visualization,
        "metadata": {
            "y_true": core["target"].tolist(),
            "y_pred": core["train_predictions"].tolist(),
            "label_categories": [str(value) for value in core["classes"]],
            "evidence_scope": "calibration_fit_diagnostics_not_validation_evidence",
        },
    }


def _knn_extract_from_state(state: Any) -> KNNExtract:
    """Decode only the closed, dimension-checked KNN fitted-state schema."""

    from collections.abc import Mapping

    required = {
        "serializer",
        "n_neighbors",
        "weights",
        "metric",
        "scale",
        "feature_count",
        "classes",
        "X_train",
        "y_train_encoded",
        "x_mean",
        "x_scale",
    }
    if not isinstance(state, Mapping) or set(state) != required:
        raise ValueError("KNN fitted state does not use the closed serializer schema")
    if state["serializer"] != KNN_FITTED_STATE_SERIALIZER:
        raise ValueError("KNN fitted state has an unsupported serializer")
    params = _canonical_knn_parameters(
        {
            "n_neighbors": state["n_neighbors"],
            "weights": state["weights"],
            "metric": state["metric"],
            "scale": state["scale"],
        }
    )
    feature_count = state["feature_count"]
    if type(feature_count) is not int or feature_count < 1:
        raise ValueError("KNN fitted state has an invalid feature count")
    classes = state["classes"]
    if (
        not isinstance(classes, list)
        or len(classes) < 2
        or any(not isinstance(label, str) or not label for label in classes)
        or len(set(classes)) != len(classes)
    ):
        raise ValueError("KNN fitted state has invalid class labels")
    X_train = np.asarray(state["X_train"], dtype=np.float64)
    encoded = np.asarray(state["y_train_encoded"])
    x_mean = np.asarray(state["x_mean"], dtype=np.float64)
    x_scale = np.asarray(state["x_scale"], dtype=np.float64)
    if X_train.ndim != 2 or X_train.shape[0] < 2 or X_train.shape[1] != feature_count or not np.isfinite(X_train).all():
        raise ValueError("KNN fitted state has an invalid training matrix")
    if encoded.ndim != 1 or encoded.shape[0] != X_train.shape[0]:
        raise ValueError("KNN fitted state labels do not match the training rows")
    if not np.issubdtype(encoded.dtype, np.integer):
        raise ValueError("KNN fitted state labels must be integer class indices")
    encoded = encoded.astype(np.int64, copy=False)
    if np.any(encoded < 0) or np.any(encoded >= len(classes)):
        raise ValueError("KNN fitted state contains an out-of-range class index")
    if int(params["n_neighbors"]) > X_train.shape[0]:
        raise ValueError("KNN fitted state has more neighbors than training rows")
    if (
        x_mean.shape != (feature_count,)
        or x_scale.shape != (feature_count,)
        or not np.isfinite(x_mean).all()
        or not np.isfinite(x_scale).all()
        or np.any(x_scale <= 0.0)
    ):
        raise ValueError("KNN fitted state has invalid scaling vectors")
    return KNNExtract(
        X_train=np.array(X_train, dtype=np.float64, copy=True),
        y_train_encoded=np.array(encoded, dtype=np.int64, copy=True),
        classes=list(classes),
        k=int(params["n_neighbors"]),
        metric=str(params["metric"]),
        weights=str(params["weights"]),
        scale=bool(params["scale"]),
        x_mean=np.array(x_mean, dtype=np.float64, copy=True),
        x_scale=np.array(x_scale, dtype=np.float64, copy=True),
    )


def _knn_fitted_state_from_core(core: dict[str, Any]) -> dict[str, object]:
    """Project one completed fit into the sole closed KNN state schema."""

    classes = [str(value) for value in core["classes"]]
    class_to_index = {label: index for index, label in enumerate(classes)}
    encoded = np.asarray([class_to_index[str(value)] for value in core["target"]], dtype=np.int64)
    model = core["model"]
    scale = bool(core["parameters"]["scale"])
    feature_count = int(core["matrix"].shape[1])
    return {
        "serializer": KNN_FITTED_STATE_SERIALIZER,
        "n_neighbors": int(core["parameters"]["n_neighbors"]),
        "weights": str(core["parameters"]["weights"]),
        "metric": str(core["parameters"]["metric"]),
        "scale": scale,
        "feature_count": feature_count,
        "classes": classes,
        "X_train": np.asarray(core["model_matrix"], dtype=np.float64).tolist(),
        "y_train_encoded": encoded.tolist(),
        "x_mean": (
            np.asarray(model.named_steps["scale"].mean_, dtype=np.float64).tolist()
            if scale
            else np.zeros(feature_count, dtype=np.float64).tolist()
        ),
        "x_scale": (
            np.asarray(model.named_steps["scale"].scale_, dtype=np.float64).tolist()
            if scale
            else np.ones(feature_count, dtype=np.float64).tolist()
        ),
    }


def apply_knn_fitted_state(input_data: Any, state: Any) -> tuple[np.ndarray, np.ndarray]:
    """Apply the closed KNN state through sklearn's exact voting semantics."""

    extract = _knn_extract_from_state(state)
    matrix = to_numpy_2d(bind_X(input_data, allow_array=True), name="input_data", dtype=np.float64)
    if matrix.shape[1] != int(state["feature_count"]) or not np.isfinite(matrix).all():
        raise ValueError("KNN apply input does not match the fitted feature contract")
    labels, probabilities = extract.predict(matrix)
    return np.asarray(labels, dtype=object), np.asarray(probabilities, dtype=np.float64)


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
                max_value=_KNN_MAX_NEIGHBORS,
                max_value_reason=(
                    "Caps per-sample vote cardinality and returned neighbor-output width; the scientific "
                    "fit also requires k not to exceed the supplied training rows."
                ),
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
        ],
        input_types=["SherpaDataset", "array"],
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
                label="Sample Coordinates",
                description="Original feature coordinates or PCA-reduced sample coordinates for plotting",
            ),
            PortMetadata(
                name="fitted_state",
                type_ref="spectrasherpa://types/ClassificationModel/1.0",
                required=True,
                label="Fitted KNN State",
                description="Closed KNN reference-set, scaling, distance, and voting state",
            ),
            PortMetadata(
                name="predictions",
                type_ref="spectrasherpa://types/Categorical/1.0",
                required=True,
                label="Training Predictions",
                description="Calibration-fit class predictions; not validation evidence",
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
                type_ref="spectrasherpa://types/StatisticsSummary/1.0",
                required=False,
                label="Classification Metrics",
                description="Calibration-fit diagnostics; use an explicit evaluator for validation metrics",
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
                name="plots",
                type_ref="spectrasherpa://types/Visualization/1.0",
                required=False,
                label="Plots",
                description="Calibration-fit confusion visualization",
            ),
            PortMetadata(
                name="visualization",
                type_ref="spectrasherpa://types/Visualization/1.0",
                required=True,
                label="Calibration-Space Map",
                description="Class-colored display projection of the complete KNN model space",
            ),
            PortMetadata(
                name="confusion_visualization",
                type_ref="spectrasherpa://types/Visualization/1.0",
                required=True,
                label="Calibration Confusion Matrix",
                description="Calibration-fit confusion counts; not held-out validation evidence",
            ),
        ],
        policy=NodePolicy(),
        canonical_parameter_validator=_canonical_knn_parameters,
        presentation_contract=NodePresentationContract(
            default_presentation="calibration_map",
            presentations=(
                ScientificPresentation(
                    "calibration_map",
                    "KNN Calibration-Space Map",
                    "visualization",
                    ("visualization",),
                    ("plot", "table"),
                    "Known classes in a display-only projection of the scaled distance space.",
                ),
                ScientificPresentation(
                    "coordinates",
                    "Projection Coordinates",
                    "score_matrix",
                    ("default",),
                    ("table",),
                    "Numeric coordinates behind the display-only calibration map.",
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
            f"{indent}# --- Canonical KNN Classifier ({self.node_id}) ---",
            f"{indent}from spectra_sherpa.app.services.dag.nodes.classification.knn_nodes import _knn_export_outputs",
            f"{indent}results[{self.node_id!r}] = _knn_export_outputs(",
            f"{indent}    {X_expression}, {inputs.get('y', 'None')}, parameters={self._resolve_params()!r},",
            f"{indent})",
        ]

    async def execute(self, X: Any = None, y: Any = None, **kwargs) -> Any:
        """
        Execute KNN classification.

        Args:
            X: SherpaDataset containing feature data
            y: Class labels

        Returns:
            KNN model with classification results
        """
        del kwargs
        from sklearn.metrics import classification_report

        core = _knn_scientific_core(X, y, parameters=self._resolve_params())
        X = core["dataset"]
        X_data = core["matrix"]
        y_array = core["target"]
        classes = core["classes"]
        knn = core["model"]
        X_model_space = core["model_matrix"]
        y_pred_train = core["train_predictions"]
        _y_pred_prob_train = core["train_probabilities"]
        neighbor_distances = core["distances"]
        neighbor_indices = core["neighbor_indices"]
        train_metrics = core["train_metrics"]
        train_accuracy = float(train_metrics["train_accuracy"])
        cm_train = core["train_confusion"]
        classification_metrics = core["metrics"]
        params = core["parameters"]
        n_neighbors = int(params["n_neighbors"])
        weights = str(params["weights"])
        metric = str(params["metric"])
        scale = bool(params["scale"])

        # Classification report
        class_report = classification_report(
            y_array, y_pred_train, target_names=[str(c) for c in classes], output_dict=True
        )

        # Get unique categories from the classes already computed
        label_categories = [str(c) for c in classes]

        # Get input coordinates for SherpaDataset creation
        _y_coord = X.sample_axis
        viz_data = core["display_matrix"]
        viz_labels = core["display_labels"]

        plots = {
            "confusion_matrix_train": generate_confusion_matrix_heatmap(
                cm_train, classes, "KNN Training Confusion Matrix"
            )
        }
        raw_sample_labels = getattr(_y_coord, "labels", None)
        sample_labels = (
            [str(value) for value in raw_sample_labels]
            if raw_sample_labels is not None
            else [f"Sample {index + 1}" for index in range(X_data.shape[0])]
        )
        calibration_map = _knn_calibration_map(viz_data, viz_labels, y_array, classes, sample_labels)
        confusion_visualization = plots["confusion_matrix_train"]
        plots["calibration_map"] = calibration_map

        # =====================================================================
        # Create SherpaDataset output with proper coordinate coupling
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
                "sample_classes": [str(value) for value in y_array],
                "pc_labels": viz_labels,
                "train_accuracy": train_accuracy,
                "train_balanced_accuracy": train_metrics["train_balanced_accuracy"],
                "train_f1_macro": train_metrics["train_f1_macro"],
                "train_precision_macro": train_metrics["train_precision_macro"],
                "train_recall_macro": train_metrics["train_recall_macro"],
                "train_sensitivity_macro": train_metrics["train_sensitivity_macro"],
                "train_specificity_macro": train_metrics["train_specificity_macro"],
                "confusion_matrix_train": cm_train.tolist(),
                "metrics": classification_metrics,
                "classification_report": class_report,
                "y_true": y_array.tolist(),
                "y_pred": y_pred_train.tolist(),
                "quality_summary": {
                    "train_accuracy": float(train_accuracy),
                    "scope": "calibration_fit_diagnostics_not_validation_evidence",
                    "n_neighbors": int(n_neighbors),
                    "metric": str(metric),
                    "scale": bool(scale),
                },
            }
        )

        logger.debug("Calibration-fit accuracy: %.3f", train_accuracy)

        class_to_index = {cls: i for i, cls in enumerate(classes)}
        y_train_encoded = np.asarray([class_to_index[label] for label in y_array], dtype=np.int64)

        artifact = _artifact_builder.build_model_artifact(
            KNNExtract(
                X_train=X_model_space,
                y_train_encoded=y_train_encoded,
                classes=label_categories,
                k=int(n_neighbors),
                metric=str(metric),
                weights=str(weights),
                scale=bool(scale),
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
                "train_balanced_accuracy": float(train_metrics["train_balanced_accuracy"]),
                "train_f1_macro": float(train_metrics["train_f1_macro"]),
                "train_precision_macro": float(train_metrics["train_precision_macro"]),
                "train_recall_macro": float(train_metrics["train_recall_macro"]),
                "train_sensitivity_macro": float(train_metrics["train_sensitivity_macro"]),
                "train_specificity_macro": float(train_metrics["train_specificity_macro"]),
                "classification_metrics": classification_metrics,
                "scope": "calibration_fit_diagnostics_not_validation_evidence",
                "n_neighbors": int(n_neighbors),
                "metric": str(metric),
                "weights": str(weights),
                "scale": bool(scale),
            },
        )
        artifact["metadata"]["fitted_parameters"] = {
            "n_neighbors": int(n_neighbors),
            "weights": str(weights),
            "metric": str(metric),
            "scale": bool(scale),
        }
        artifact["metadata"]["metrics_scope"] = "calibration_fit_diagnostics_not_validation_evidence"

        # SherpaDataset-only return: one serialization boundary at API layer
        return NodeResult(
            outputs={
                "default": scores_dataset,  # SherpaDataset: viz scores + sample labels (y) + feature coords (x)
                "fitted_state": _knn_fitted_state_from_core(core),
                "predictions": y_pred_train.tolist(),
                "probabilities": _y_pred_prob_train.tolist(),
                "class_probabilities": _y_pred_prob_train.tolist(),
                "distances": neighbor_distances.tolist(),
                "neighbor_indices": neighbor_indices.tolist(),
                "metrics": classification_metrics,
                "train_accuracy": float(train_accuracy),
                "plots": plots,  # Pre-built Plotly traces (legitimate visualization output)
                "visualization": calibration_map,
                "confusion_visualization": confusion_visualization,
                "_model_artifact": artifact,
            },
            diagnostics={
                "train_accuracy": train_accuracy,
                "metrics": classification_metrics,
                "n_classes": len(classes),
                "evidence_scope": "calibration_fit_diagnostics_not_validation_evidence",
            },
        )

    def fit_fitted_state(self, input_data: Any, target: Any) -> dict[str, object]:
        """Fit and serialize the exact KNN reference set and distance rule."""

        core = _knn_scientific_core(input_data, target, parameters=self._resolve_params())
        return _knn_fitted_state_from_core(core)

    def apply_fitted_state(self, input_data: Any, state: Any) -> np.ndarray:
        """Apply a closed KNN fitted state without target access or refitting."""

        _labels, probabilities = apply_knn_fitted_state(input_data, state)
        return probabilities

    def predict_fitted_labels(self, input_data: Any, state: Any) -> np.ndarray:
        """Return KNN decisions for the shared held-out fold executor."""

        labels, _probabilities = apply_knn_fitted_state(input_data, state)
        return labels


bind_stable_execution_contract(
    KNNNode,
    runtime_family=RuntimeFamily.SHERPA_NATIVE,
    lifecycle_kind=LifecycleKind.FITTED_MODEL,
    implementation_id="spectrasherpa.classification.knn",
    implementation_version="2.0.0",
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
    resource_hints={"timeout_seconds": 30, "cpu_seconds": 30, "memory_bytes": 1_073_741_824},
    license_id="BSD-3-Clause",
    help_reference="docs/nodes/classification.md",
    implementation_distributions=("numpy", "scipy", "scikit-learn"),
    runtime_requirements=(("numpy", "1.26.4"), ("scipy", "1.17.1"), ("scikit-learn", "1.9.0")),
    managed_optimization_profiles=("first_party_pls",),
    citations=(
        "Cover & Hart, Nearest Neighbor Pattern Classification, IEEE Transactions on Information Theory "
        "13 (1967) 21-27, DOI 10.1109/TIT.1967.1053964",
    ),
    implementation_modules=(
        core_utils,
        fitted_state,
        knn_core,
        dag_io_contracts,
        meta_helpers,
        modeling_core_utils,
        visualization,
        _artifact_builder,
    ),
    fitted_state_serializer=KNN_FITTED_STATE_SERIALIZER,
    deterministic=True,
    target_access=TargetAccess.FIT_ONLY,
    group_access="none",
    supervised_task="classification",
)
