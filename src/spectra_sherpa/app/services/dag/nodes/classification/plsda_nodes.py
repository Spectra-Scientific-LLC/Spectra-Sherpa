"""Canonical PLS2 discriminant-analysis node."""

from __future__ import annotations

from typing import Any, Mapping

import numpy as np
from sklearn.metrics import confusion_matrix

from spectra_sherpa.app.lib.sherpa_dataset import SherpaDataset
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

from ...io_contracts import bind_X, bind_y, to_numpy_2d
from ...node_base import Node, NodeMetadata, NodeParameter, NodePolicy, NodeResult, PortMetadata, register_node
from ...presentation_contract import NodePresentationContract, ScientificPresentation
from ...stable_execution_contract import bind_stable_execution_contract
from .. import visualization
from ..modeling import _artifact_builder, create_spectral_dataset, pls_core
from ..modeling import core_utils as modeling_core_utils
from ..selection import _vip
from ..visualization import generate_confusion_matrix_heatmap
from . import core_utils, plsda_state
from .core_utils import classification_metrics_contract, classification_scalar_metrics, make_labeled_coord
from .plsda_state import SherpaPLSDAArtifact

_PLSDA_MAX_COMPONENTS = 20
PLSDA_FITTED_STATE_SERIALIZER = plsda_state.FITTED_STATE_SERIALIZER


def _canonical_plsda_parameters(parameters: dict[str, object]) -> dict[str, object]:
    """Return the closed, reference-faithful PLS-DA parameter record."""

    expected = {"n_components", "scale"}
    if set(parameters) != expected:
        raise ValueError(f"PLS-DA parameters must contain exactly {', '.join(sorted(expected))}")
    values: dict[str, object] = {}
    for name, lower, upper in (("n_components", 1, _PLSDA_MAX_COMPONENTS),):
        value = parameters[name]
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not np.isfinite(value)
            or int(value) != value
        ):
            raise ValueError(f"PLS-DA {name} must be an exact integer")
        integer = int(value)
        if not lower <= integer <= upper:
            raise ValueError(f"PLS-DA {name} must be between {lower} and {upper}")
        values[name] = integer
    if not isinstance(parameters["scale"], bool):
        raise ValueError("PLS-DA scale must be a strict boolean")
    values["scale"] = parameters["scale"]
    return values


def _plsda_inputs(X: Any, y: Any) -> tuple[Any, np.ndarray, np.ndarray, np.ndarray]:
    dataset = bind_X(
        X,
        missing_message="Missing required input: X (spectra)",
        dataset_error_message="X must be a dataset object",
        allow_array=True,
    )
    target = bind_y(
        y,
        X=dataset,
        required=True,
        infer_from_X=True,
        target_type="categorical",
        missing_message="Missing required input: y (class labels)",
    )
    matrix = to_numpy_2d(dataset, name="X", dtype=np.float64)
    labels = core_utils.prepare_class_labels(target, matrix.shape[0])
    if matrix.shape[0] < 4 or matrix.shape[1] < 1 or not np.isfinite(matrix).all():
        raise ValueError("PLS-DA requires a finite two-dimensional calibration matrix")
    classes = np.unique(labels)
    if classes.size < 2:
        raise ValueError("PLS-DA requires at least two classes")
    return dataset, matrix, labels, classes


def _dummy_response(labels: np.ndarray, classes: np.ndarray) -> np.ndarray:
    class_indices = {value: index for index, value in enumerate(classes.tolist())}
    return np.eye(len(classes), dtype=np.float64)[[class_indices[value] for value in labels.tolist()]]


def _native_plsda_fit(
    matrix: np.ndarray,
    dummy: np.ndarray,
    classes: np.ndarray,
    *,
    n_components: int,
    scale: bool,
    feature_source: object | None = None,
) -> tuple[pls_core.PLSFit, SherpaPLSDAArtifact]:
    """Fit the private SIMPLS authority and bind its PLS-DA state contract."""

    fit = pls_core.fit_simpls(
        matrix,
        dummy,
        n_components=n_components,
        scale=scale,
    )
    return fit, SherpaPLSDAArtifact.from_fit(fit, classes, feature_source)


def _plsda_scientific_core(
    X: Any,
    y: Any,
    *,
    parameters: dict[str, object],
) -> dict[str, Any]:
    """Fit one PLS2 classifier through the private Sherpa SIMPLS authority."""

    params = _canonical_plsda_parameters(parameters)
    dataset, matrix, labels, classes = _plsda_inputs(X, y)
    component_limit = min(matrix.shape[1], matrix.shape[0] - 1)
    if int(params["n_components"]) > component_limit:
        raise ValueError(f"PLS-DA n_components must not exceed the calibration rank bound ({component_limit})")

    dummy = _dummy_response(labels, classes)
    fit, artifact = _native_plsda_fit(
        matrix,
        dummy,
        classes,
        n_components=int(params["n_components"]),
        scale=bool(params["scale"]),
        feature_source=dataset,
    )
    train_predictions, train_scores = artifact._predict_matrix(matrix)
    train_metrics = classification_scalar_metrics(labels, train_predictions, classes, prefix="train_")
    train_confusion = confusion_matrix(labels, train_predictions, labels=classes)
    metrics = classification_metrics_contract(
        classes=classes,
        train_metrics=train_metrics,
        primary_split="train",
        method="plsda",
        confusion_matrices={"train": train_confusion.tolist()},
        extra={
            "requested_n_components": int(params["n_components"]),
            "effective_n_components": fit.n_components,
            "scale": bool(params["scale"]),
            "algorithm_id": fit.algorithm_id,
            "algorithm_version": fit.algorithm_version,
            "decision_rule": plsda_state.DECISION_RULE,
            "numeric_output_semantics": plsda_state.OUTPUT_SEMANTICS,
            "evidence_scope": "calibration_fit_diagnostics_not_validation_evidence",
        },
    )
    return {
        "dataset": dataset,
        "matrix": matrix,
        "labels": labels,
        "classes": classes,
        "parameters": params,
        "fit": fit,
        "artifact": artifact,
        "x_scores": np.asarray(fit.x_scores, dtype=np.float64),
        "x_loadings": np.asarray(fit.x_loadings.T, dtype=np.float64),
        "explained_variance": np.column_stack(
            (
                np.asarray(fit.x_explained_variance, dtype=np.float64),
                np.asarray(fit.y_explained_variance, dtype=np.float64),
            )
        ),
        "class_coefficients": np.asarray(fit.coefficients, dtype=np.float64),
        "vip_scores": _vip.calculate_vip(fit.x_scores, fit.x_weights, fit.y_loadings, matrix.shape[1]),
        "train_predictions": train_predictions,
        "train_class_scores": train_scores,
        "metrics": metrics,
        "train_confusion": train_confusion,
    }


def _plsda_export_outputs(X: Any, y: Any, *, parameters: dict[str, object]) -> dict[str, Any]:
    """Project the Sherpa-native PLS-DA operation into generated-Python values."""

    core = _plsda_scientific_core(X, y, parameters=parameters)
    return {
        "default": np.asarray(core["x_scores"], dtype=np.float64),
        "X_scores": np.asarray(core["x_scores"], dtype=np.float64),
        "X_loadings": np.asarray(core["x_loadings"], dtype=np.float64),
        "loadings": np.asarray(core["x_loadings"], dtype=np.float64),
        "explained_variance": np.asarray(core["explained_variance"], dtype=np.float64),
        "class_coefficients": np.asarray(core["class_coefficients"], dtype=np.float64),
        "fitted_state": core["artifact"].to_fitted_state(),
        "predictions": core["train_predictions"].tolist(),
        "class_scores": core["train_class_scores"].tolist(),
        "vip_scores": np.asarray(core["vip_scores"], dtype=np.float64),
        "confusion_matrix_train": core["train_confusion"],
        "metrics": core["metrics"],
        "plots": _plsda_visualizations(core, core["dataset"]),
        "metadata": {
            "y_true": core["labels"].tolist(),
            "y_pred": core["train_predictions"].tolist(),
            "label_categories": core["classes"].tolist(),
            "target_names": core["classes"].tolist(),
            "decision_rule": plsda_state.DECISION_RULE,
            "numeric_output_semantics": plsda_state.OUTPUT_SEMANTICS,
            "evidence_scope": "calibration_fit_diagnostics_not_validation_evidence",
        },
    }


def apply_plsda_fitted_state(input_data: Any, state: Any) -> tuple[np.ndarray, np.ndarray]:
    """Apply a state inside the trusted fitted-model lifecycle."""

    artifact = SherpaPLSDAArtifact.from_fitted_state(state)
    dataset = bind_X(input_data, allow_array=True)
    allow_same_lifecycle_positional = (
        isinstance(state, Mapping) and state.get("serializer") == plsda_state.FITTED_STATE_SERIALIZER
    )
    labels, responses = artifact.predict(
        dataset,
        allow_unverified_positional=allow_same_lifecycle_positional,
    )
    return np.asarray(labels, dtype=object), np.asarray(responses, dtype=np.float64)


def _plsda_visualizations(core: dict[str, Any], dataset: SherpaDataset) -> dict[str, Any]:
    """Build scientist-facing views from the already-computed canonical result."""

    artifact = core.get("artifact")
    components = (
        int(artifact.effective_n_components)
        if isinstance(artifact, SherpaPLSDAArtifact)
        else int(core["parameters"]["n_components"])
    )
    classes = np.asarray(core["classes"], dtype=object)
    scores = np.asarray(core["x_scores"], dtype=np.float64)
    loadings = np.asarray(core["x_loadings"], dtype=np.float64)
    feature_axis = getattr(dataset.feature_axis, "values", None)
    feature_values = (
        np.arange(loadings.shape[1], dtype=np.float64)
        if feature_axis is None
        else np.asarray(feature_axis, dtype=np.float64)
    )
    plots: dict[str, Any] = {}
    if components >= 2:
        plots["scores"] = {
            "data": [
                {
                    "type": "scatter",
                    "mode": "markers",
                    "name": str(label),
                    "x": scores[core["labels"] == label, 0].tolist(),
                    "y": scores[core["labels"] == label, 1].tolist(),
                }
                for label in classes
            ],
            "layout": {"title": "PLS-DA Scores", "xaxis": {"title": "LV1"}, "yaxis": {"title": "LV2"}},
        }
    loading_plot = {
        "data": [
            {
                "type": "scatter",
                "mode": "lines",
                "name": f"LV{index + 1}",
                "x": feature_values.tolist(),
                "y": loadings[index].tolist(),
            }
            for index in range(components)
        ],
        "layout": {
            "title": "PLS-DA Loadings (Component Patterns)",
            "xaxis": {"title": "Feature"},
            "yaxis": {"title": "Loading"},
        },
    }
    plots["loadings_lines"] = loading_plot
    plots["loadings"] = loading_plot
    plots["vip"] = {
        "data": [
            {
                "type": "bar",
                "name": "VIP",
                "x": feature_values.tolist(),
                "y": np.asarray(core["vip_scores"], dtype=np.float64).tolist(),
            }
        ],
        "layout": {"title": "PLS-DA Variable Importance", "xaxis": {"title": "Feature"}, "yaxis": {"title": "VIP"}},
    }
    plots["confusion_matrix_train"] = generate_confusion_matrix_heatmap(
        core["train_confusion"], classes, "PLS-DA Training Confusion Matrix"
    )
    return plots


@register_node
class PLSDANode(Node):
    """PLS2 discriminant analysis with validation owned by the fold executor."""

    metadata = NodeMetadata(
        node_type="classification.plsda",
        category="classification",
        label="Train PLS-DA Classifier",
        description=(
            "Fit PLS2 to a 0/1 dummy class table and assign each sample to the "
            "largest predicted class response. Numeric class responses are scores, not probabilities."
        ),
        parameters=[
            NodeParameter(
                name="n_components",
                label="Number of Components",
                param_type="number",
                default=2,
                min_value=1,
                max_value=_PLSDA_MAX_COMPONENTS,
                max_value_reason=(
                    "Bounds latent-variable fitting and artifact size; runtime further limits components "
                    "to the smallest fold-local calibration rank."
                ),
                step=1,
                required=True,
                description="Number of PLS2 latent variables",
            ),
            NodeParameter(
                name="scale",
                label="Autoscale X and Dummy Y",
                param_type="boolean",
                default=False,
                required=False,
                description="Fit scaling inside every calibration or validation fold",
            ),
        ],
        input_types=["SherpaDataset", "array"],
        output_type="dict",
        input_ports=[
            PortMetadata(
                name="X",
                type_ref="spectrasherpa://types/Array2D/1.0",
                required=True,
                label="Data Matrix (X)",
                accepted_data_roles=["X_spectra", "X_features"],
            ),
            PortMetadata(
                name="y",
                type_ref="spectrasherpa://types/TargetMatrix/1.0",
                required=False,
                label="Class Labels (y)",
            ),
        ],
        output_ports=[
            PortMetadata(
                name="default",
                type_ref="spectrasherpa://types/ScoreMatrix/1.0",
                required=True,
                label="X Scores",
            ),
            PortMetadata(
                name="X_scores",
                type_ref="spectrasherpa://types/ScoreMatrix/1.0",
                required=True,
                label="X Scores",
            ),
            PortMetadata(
                name="X_loadings",
                type_ref="spectrasherpa://types/LoadingMatrix/1.0",
                required=True,
                label="X Loadings",
            ),
            PortMetadata(
                name="loadings",
                type_ref="spectrasherpa://types/LoadingMatrix/1.0",
                required=True,
                label="X Loadings",
            ),
            PortMetadata(
                name="explained_variance",
                type_ref="spectrasherpa://types/ExplainedVarianceMatrix/1.0",
                required=True,
                label="Explained Variance",
                description="Component-wise explained X and dummy-response variance fractions.",
            ),
            PortMetadata(
                name="class_coefficients",
                type_ref="spectrasherpa://types/RegressionCoefficientMatrix/1.0",
                required=True,
                label="Class-Response Coefficients",
                description=(
                    "One fitted coefficient per input variable and encoded class response; these are not "
                    "posterior-probability coefficients."
                ),
            ),
            PortMetadata(
                name="fitted_state",
                type_ref="spectrasherpa://types/ClassificationModel/1.0",
                required=True,
                label="Fitted PLS-DA State",
                description="Closed PLS2 coefficients, centering, class identity, and decision rule",
            ),
            PortMetadata(
                name="predictions",
                type_ref="spectrasherpa://types/Categorical/1.0",
                required=True,
                label="Calibration Classes",
            ),
            PortMetadata(
                name="class_scores",
                type_ref="spectrasherpa://types/Array2D/1.0",
                required=True,
                label="Calibration Class-Response Scores",
                description="Predicted dummy responses; these are not posterior probabilities",
            ),
            PortMetadata(
                name="vip_scores",
                type_ref="spectrasherpa://types/VariableImportance/1.0",
                required=True,
                label="VIP Scores",
                description="Combined VIP scores from the fitted PLS-DA latent-variable model",
            ),
            PortMetadata(
                name="confusion_matrix_train",
                type_ref="spectrasherpa://types/ConfusionMatrix/1.0",
                required=True,
                label="Calibration Confusion Matrix",
                description="Calibration decisions only; this is not held-out validation evidence",
            ),
            PortMetadata(
                name="metrics",
                type_ref="spectrasherpa://types/StatisticsSummary/1.0",
                required=True,
                label="Classification Metrics",
                description="Calibration-fit metrics; use an explicit evaluator for validation evidence",
            ),
            PortMetadata(
                name="plots",
                type_ref="spectrasherpa://types/Visualization/1.0",
                required=False,
                label="Confusion Matrices",
            ),
        ],
        help_url="https://search.r-project.org/CRAN/refmans/mdatools/help/plsda.html",
        policy=NodePolicy(),
        presentation_contract=NodePresentationContract(
            default_presentation="scores",
            presentations=(
                ScientificPresentation(
                    "scores",
                    "PLS-DA Scores",
                    "plsda_scores",
                    ("X_scores",),
                    ("plot", "table"),
                    "Calibration samples in latent-variable space, grouped by known class.",
                ),
                ScientificPresentation(
                    "loadings",
                    "PLS-DA X Loadings",
                    "plsda_loadings",
                    ("X_loadings",),
                    ("plot", "table"),
                    "Spectral-variable contributions for each fitted latent variable.",
                ),
                ScientificPresentation(
                    "vip",
                    "PLS-DA VIP Scores",
                    "variable_profile",
                    ("vip_scores",),
                    ("plot", "table"),
                    "Combined variable importance in projection for class discrimination.",
                ),
                ScientificPresentation(
                    "explained_variance",
                    "Explained Variance",
                    "pls_explained_variance",
                    ("explained_variance",),
                    ("plot", "table"),
                    "Component-wise X and encoded-class response variance captured by the PLS2 fit.",
                ),
                ScientificPresentation(
                    "coefficients",
                    "PLS-DA Class-Response Coefficients",
                    "regression_coefficients",
                    ("class_coefficients",),
                    ("plot", "table"),
                    "Variable coefficients for each encoded class response; these are not probabilities.",
                ),
                ScientificPresentation(
                    "calibration_confusion",
                    "Calibration Confusion Matrix",
                    "confusion_matrix",
                    ("confusion_matrix_train",),
                    ("plot", "table"),
                    "Training-fit decisions only; use an evaluator for held-out evidence.",
                ),
                ScientificPresentation(
                    "class_responses",
                    "Calibration Class Responses",
                    "classification_responses",
                    ("class_scores",),
                    ("plot", "table"),
                    "Dummy-response scores by sample and class; these are not probabilities.",
                ),
                ScientificPresentation(
                    "metrics",
                    "Calibration Classification Metrics",
                    "statistics_summary",
                    ("metrics",),
                    ("record", "table"),
                    "Training-fit metrics only; use an evaluator for held-out evidence.",
                ),
                ScientificPresentation(
                    "model",
                    "Fitted PLS-DA Model",
                    "classification_model",
                    ("fitted_state",),
                    ("model_summary",),
                ),
            ),
        ),
        canonical_parameter_validator=_canonical_plsda_parameters,
    )

    def generate_python(
        self,
        inputs: dict[str, str],
        indent: str = "    ",
        use_scp: bool = True,
    ) -> list[str]:
        del use_scp
        X_expression = inputs.get("X", inputs.get("default", "input_data"))
        return [
            f"{indent}# --- Canonical PLS-DA ({self.node_id}) ---",
            f"{indent}from spectra_sherpa.app.services.dag.nodes.classification.plsda_nodes import "
            "_plsda_export_outputs",
            f"{indent}results[{self.node_id!r}] = _plsda_export_outputs(",
            f"{indent}    {X_expression},",
            f"{indent}    {inputs.get('y', 'None')},",
            f"{indent}    parameters={self._resolve_params()!r},",
            f"{indent})",
        ]

    async def execute(self, X: Any = None, y: Any = None, **kwargs: Any) -> NodeResult:
        del kwargs
        core = _plsda_scientific_core(X, y, parameters=self._resolve_params())
        dataset = core["dataset"]
        params = core["parameters"]
        effective_components = int(core["artifact"].effective_n_components)
        lv_labels = [f"LV{index + 1}" for index in range(effective_components)]
        score_dataset = create_spectral_dataset(
            data=core["x_scores"],
            x_coord=make_labeled_coord(lv_labels, title="Latent Variable"),
            y_coord=dataset.sample_axis,
            units="score",
            title="PLS-DA Scores",
            data_role="X_features",
        )
        loading_dataset = create_spectral_dataset(
            data=core["x_loadings"],
            x_coord=dataset.feature_axis,
            y_coord=make_labeled_coord(lv_labels, title="Latent Variable"),
            units="loading",
            title="PLS-DA Loadings",
        )
        for output, operation in (
            (score_dataset, "classification.plsda.scores"),
            (loading_dataset, "classification.plsda.loadings"),
        ):
            copy_processing_history(dataset, output)
            add_processing_step(output, operation, params, node_id=self.node_id)
            inherit_origin_flags(dataset, output)
        inherit_sample_flags(dataset, score_dataset)
        score_dataset.meta.update(
            {
                "type": "PLS_DA",
                "classes": [str(value) for value in core["classes"].tolist()],
                "decision_rule": "maximum_predicted_dummy_response",
                "numeric_output_semantics": "class_response_scores_not_probabilities",
                "metrics": core["metrics"],
                "calibration_predictions": core["train_predictions"].tolist(),
                "calibration_class_scores": core["train_class_scores"].tolist(),
                "vip_scores": core["vip_scores"].tolist(),
                "sample_classes": [str(value) for value in core["labels"].tolist()],
                "label_categories": [str(value) for value in core["classes"].tolist()],
            }
        )
        plots = _plsda_visualizations(core, dataset)
        feature_names = None
        if dataset.feature_axis is not None and dataset.feature_axis.labels is not None:
            feature_names = [str(value) for value in list(dataset.feature_axis.labels)]
        sample_labels = None
        if dataset.sample_axis is not None and dataset.sample_axis.labels is not None:
            sample_labels = [str(value) for value in list(dataset.sample_axis.labels)]
        artifact = _artifact_builder.build_model_artifact(
            core["artifact"],
            dataset,
            node_id=self.node_id,
            metrics=core["metrics"],
        )
        return NodeResult(
            outputs={
                "default": score_dataset,
                "X_scores": score_dataset,
                "X_loadings": loading_dataset,
                "loadings": loading_dataset,
                "explained_variance": np.asarray(core["explained_variance"], dtype=np.float64),
                "class_coefficients": np.asarray(core["class_coefficients"], dtype=np.float64),
                "fitted_state": core["artifact"].to_fitted_state(),
                "predictions": core["train_predictions"].tolist(),
                "class_scores": core["train_class_scores"].tolist(),
                "vip_scores": np.asarray(core["vip_scores"], dtype=np.float64),
                "confusion_matrix_train": core["train_confusion"],
                "metrics": core["metrics"],
                "plots": plots,
                "_model_artifact": artifact,
            },
            diagnostics={
                "metrics": core["metrics"],
                "train_accuracy": float(core["metrics"]["splits"]["train"]["accuracy"]),
                "train_f1_macro": float(core["metrics"]["splits"]["train"]["f1_macro"]),
                "decision_rule": "maximum_predicted_dummy_response",
                "numeric_output_semantics": "class_response_scores_not_probabilities",
                "requested_n_components": int(params["n_components"]),
                "effective_n_components": effective_components,
                "x_explained_variance": core["fit"].x_explained_variance.tolist(),
                "y_explained_variance": core["fit"].y_explained_variance.tolist(),
                "n_classes": int(len(core["classes"])),
                "classes": [str(value) for value in core["classes"].tolist()],
                "label_categories": [str(value) for value in core["classes"].tolist()],
                "sample_classes": [str(value) for value in core["labels"].tolist()],
                "sample_labels": sample_labels,
                "feature_names": feature_names,
                "evidence_scope": "calibration_fit_diagnostics_not_validation_evidence",
            },
        )

    def fit_fitted_state(self, input_data: Any, target: Any) -> dict[str, object]:
        core = _plsda_scientific_core(input_data, target, parameters=self._resolve_params())
        return core["artifact"].to_fitted_state()

    def apply_fitted_state(self, input_data: Any, state: Any) -> np.ndarray:
        _labels, responses = apply_plsda_fitted_state(input_data, state)
        return responses

    def predict_fitted_labels(self, input_data: Any, state: Any) -> np.ndarray:
        """Return the class decisions used by the managed evaluator path."""

        labels, _responses = apply_plsda_fitted_state(input_data, state)
        return labels

    def predict_fitted_classification(
        self,
        input_data: Any,
        state: Any,
    ) -> tuple[np.ndarray, np.ndarray, np.ndarray, str]:
        """Return decisions and the exact raw responses from one application."""

        artifact = SherpaPLSDAArtifact.from_fitted_state(state)
        labels, responses = apply_plsda_fitted_state(input_data, state)
        return (
            labels,
            responses,
            np.asarray(artifact.classes, dtype=object),
            plsda_state.OUTPUT_SEMANTICS,
        )


bind_stable_execution_contract(
    PLSDANode,
    runtime_family=RuntimeFamily.SHERPA_NATIVE,
    lifecycle_kind=LifecycleKind.FITTED_MODEL,
    implementation_id="spectrasherpa.classification.plsda",
    implementation_version="4.0.0",
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
    implementation_distributions=("numpy", "scikit-learn"),
    runtime_requirements=(("numpy", "1.26.4"), ("scikit-learn", "1.9.0")),
    managed_optimization_profiles=("first_party_pls",),
    citations=(
        pls_core.CITATION,
        "Barker & Rayens, Partial least squares for discrimination, Journal of Chemometrics 17 (2003) "
        "166-173, DOI 10.1002/cem.785",
        "Kucheryavskiy, mdatools PLS-DA documentation; rchemo::plsrda maximum dummy-response rule",
    ),
    implementation_modules=(
        dag_io_contracts,
        meta_helpers,
        modeling_core_utils,
        visualization,
        core_utils,
        pls_core,
        plsda_state,
        _vip,
        _artifact_builder,
    ),
    fitted_state_serializer=PLSDA_FITTED_STATE_SERIALIZER,
    deterministic=True,
    target_access=TargetAccess.FIT_ONLY,
    group_access="none",
    supervised_task="classification",
)
