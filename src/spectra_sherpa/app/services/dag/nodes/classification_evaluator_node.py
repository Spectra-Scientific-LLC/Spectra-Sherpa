"""Closed held-out classification evaluation for the canonical workbench."""

from __future__ import annotations

from typing import Any

import numpy as np
import sklearn.metrics as sklearn_metrics

from spectra_sherpa.app.services.dag.classification_comparison import build_classification_comparison
from spectra_sherpa.app.services.dag.node_base import (
    Node,
    NodeMetadata,
    NodePolicy,
    NodeResult,
    PortMetadata,
    register_node,
)
from spectra_sherpa.app.services.dag.presentation_contract import NodePresentationContract, ScientificPresentation
from spectra_sherpa.app.services.dag.stable_execution_contract import bind_stable_execution_contract
from spectra_sherpa.execution_contract_vocabulary import (
    LifecycleKind,
    ManagedOptimizationEligibility,
    RuntimeFamily,
    WorkerCapability,
)
from spectra_sherpa.sdk.validate import (
    ClassificationMetricAccumulator,
    ClassificationMetricSet,
    classification_metric_set,
)

_REJECTION_LABEL = "unassigned"


def _label_vector(value: object, *, name: str) -> np.ndarray:
    """Return one non-empty raw class-label vector without coercing mixed predictions."""

    array = np.asarray(value, dtype=object)
    if array.ndim == 2 and array.shape[1] == 1:
        array = array[:, 0]
    if array.ndim != 1 or array.size < 1:
        raise ValueError(f"{name} must be a non-empty one-dimensional class-label vector")
    return array


def _observed_domain(values: np.ndarray) -> str:
    raw = values.tolist()
    if all(isinstance(item, (bool, np.bool_)) for item in raw):
        return "boolean"
    if all(
        isinstance(item, (int, float, np.integer, np.floating)) and not isinstance(item, (bool, np.bool_))
        for item in raw
    ):
        numeric = np.asarray(raw, dtype=np.float64)
        if np.isfinite(numeric).all():
            return "numeric"
    if all(isinstance(item, str) and item for item in raw):
        if _REJECTION_LABEL in raw:
            raise ValueError(
                f"held_out_target reserves {_REJECTION_LABEL!r} for rejected predictions; "
                "rename that observed class before evaluation"
            )
        return "text"
    raise ValueError("held_out_target class labels must share one numeric, boolean, or non-empty text domain")


def _tokenize_label(value: object, *, domain: str, prediction: bool) -> tuple[str, object]:
    """Produce one comparison-safe token while preserving its scientist-facing label."""

    if prediction and value == _REJECTION_LABEL:
        return "rejection:unassigned", _REJECTION_LABEL
    if domain == "boolean" and isinstance(value, (bool, np.bool_)):
        plain = bool(value)
        return f"boolean:{int(plain)}", plain
    if (
        domain == "numeric"
        and isinstance(value, (int, float, np.integer, np.floating))
        and not isinstance(value, (bool, np.bool_))
    ):
        plain = float(value)
        if np.isfinite(plain):
            return f"numeric:{plain.hex()}", plain
    if domain == "text" and isinstance(value, str) and value:
        return f"text:{value}", value
    label_role = "predictions" if prediction else "held_out_target"
    raise ValueError(
        f"{label_role} must use the observed {domain} class-label domain; "
        f"only the closed prediction label {_REJECTION_LABEL!r} may fall outside it"
    )


def _tokenize_vector(
    values: np.ndarray,
    *,
    domain: str,
    prediction: bool,
) -> tuple[np.ndarray, dict[str, object]]:
    tokens: list[str] = []
    display: dict[str, object] = {}
    for value in values.tolist():
        token, plain = _tokenize_label(value, domain=domain, prediction=prediction)
        tokens.append(token)
        display[token] = plain
    return np.asarray(tokens, dtype=str), display


def _ordered_tokens(tokens: np.ndarray, *, display: dict[str, object], domain: str) -> list[str]:
    """Order scientist-facing classes by domain and keep rejections last."""

    unique = set(tokens.tolist())

    def key(token: str) -> tuple[int, object]:
        if token.startswith("rejection:"):
            return 1, str(display[token])
        value = display[token]
        if domain == "numeric":
            return 0, float(value)
        if domain == "boolean":
            return 0, int(bool(value))
        return 0, str(value)

    return sorted(unique, key=key)


def evaluate_classification_v2(
    predictions: object,
    held_out_target: object,
    *,
    node_id: str = "classification-evaluator-v2",
) -> NodeResult:
    """Evaluate all held-out samples, including rejected or novel predictions."""

    observed_raw = _label_vector(held_out_target, name="held_out_target")
    predicted_raw = _label_vector(predictions, name="predictions")
    observed_domain = _observed_domain(observed_raw)
    observed, observed_display = _tokenize_vector(observed_raw, domain=observed_domain, prediction=False)
    predicted, predicted_display = _tokenize_vector(predicted_raw, domain=observed_domain, prediction=True)
    if observed.shape != predicted.shape:
        raise ValueError("predictions and held_out_target must contain the same number of samples")

    display = {**observed_display, **predicted_display}
    observed_labels = _ordered_tokens(observed, display=display, domain=observed_domain)
    if len(observed_labels) < 2:
        raise ValueError("classification evaluation requires at least two observed classes")
    labels = _ordered_tokens(np.concatenate([observed, predicted]), display=display, domain=observed_domain)
    matrix = sklearn_metrics.confusion_matrix(observed, predicted, labels=labels)
    if int(matrix.sum()) != int(observed.size):
        raise RuntimeError("classification confusion matrix does not account for every held-out sample")
    precision, recall, f1, support = sklearn_metrics.precision_recall_fscore_support(
        observed,
        predicted,
        labels=labels,
        zero_division=0,
    )
    predicted_counts = np.asarray([(predicted == label).sum() for label in labels], dtype=np.int64)
    observed_set = set(observed_labels)
    predicted_only = [display[label] for label in labels if label not in observed_set]
    per_class = [
        {
            "label": display[label],
            "support": int(support[index]),
            "predicted_count": int(predicted_counts[index]),
            "precision": float(precision[index]),
            "recall": float(recall[index]),
            "specificity": float(
                (matrix.sum() - matrix[index, :].sum() - matrix[:, index].sum() + matrix[index, index])
                / max(1, matrix.sum() - matrix[index, :].sum())
            ),
            "f1": float(f1[index]),
        }
        for index, label in enumerate(labels)
    ]
    metrics = {
        "schema_version": "spectrasherpa.classification-evaluation/1",
        "task_type": "classification",
        "n_samples": int(observed.size),
        "label_domain": observed_domain,
        "labels": [display[label] for label in labels],
        "observed_labels": [display[label] for label in observed_labels],
        "predicted_only_labels": predicted_only,
        "accuracy": float(sklearn_metrics.accuracy_score(observed, predicted)),
        "balanced_accuracy": float(sklearn_metrics.balanced_accuracy_score(observed, predicted)),
        "macro_precision": float(np.mean(precision)),
        "macro_recall": float(np.mean(recall)),
        "macro_specificity": float(np.mean([row["specificity"] for row in per_class])),
        "macro_f1": float(np.mean(f1)),
        "confusion_matrix": matrix.tolist(),
        "per_class": per_class,
    }
    visualization = {
        "type": "confusion_matrix",
        "data": matrix.tolist(),
        "metadata": {
            "type": "ClassificationTest",
            "labels": metrics["labels"],
            "n_samples": metrics["n_samples"],
            "accuracy": metrics["accuracy"],
            "predicted_only_labels": predicted_only,
        },
    }
    comparison = build_classification_comparison(
        observed_raw.tolist(),
        predicted_raw.tolist(),
        role="unqualified_evaluation",
    )
    return NodeResult(
        outputs={"default": metrics, "comparison": comparison, "visualization": visualization},
        diagnostics={
            "node_id": node_id,
            "accounted_samples": int(matrix.sum()),
            "predicted_only_label_count": len(predicted_only),
        },
    )


@register_node
class ClassificationEvaluatorV2Node(Node):
    """Score one explicit held-out class-label vector without dropping rows."""

    metadata = NodeMetadata(
        node_type="diagnostics.classification_evaluator",
        category="diagnostics",
        label="Reference Classification Evaluator (v2)",
        description=(
            "Compute accuracy, a complete confusion matrix, and per-class precision, recall, and F1. "
            "Held-out scope requires executor-verified training and evaluation lineage. "
            "Predicted-only rejection or unknown labels remain visible and count against accuracy."
        ),
        input_ports=[
            PortMetadata(
                name="default",
                type_ref="spectrasherpa://types/Categorical/1.0",
                required=True,
                label="Predictions",
            ),
            PortMetadata(
                name="y_true",
                type_ref="spectrasherpa://types/TargetMatrix/1.0",
                required=False,
                label="Reference Labels",
                description=(
                    "Explicit reference labels for local workbench evaluation. Managed validation supplies "
                    "them only through the fold-lifecycle target authority."
                ),
            ),
        ],
        output_ports=[
            PortMetadata(
                name="default",
                type_ref="spectrasherpa://types/ValidationResult/1.0",
                required=True,
                label="Evaluation Metrics",
            ),
            PortMetadata(
                name="comparison",
                type_ref="spectrasherpa://types/ClassificationComparison/1.0",
                required=False,
                label="Reference vs Predicted Classes",
                description="One reference class, predicted class, and correctness decision per held-out sample.",
            ),
            PortMetadata(
                name="visualization",
                type_ref="spectrasherpa://types/Visualization/1.0",
                required=False,
                label="Confusion Matrix",
            ),
        ],
        input_types=["array", "array"],
        output_type="dict",
        policy=NodePolicy(),
        presentation_contract=NodePresentationContract(
            default_presentation="sample_comparison",
            presentations=(
                ScientificPresentation(
                    "sample_comparison",
                    "Predicted vs Reference",
                    "classification_comparison",
                    ("comparison",),
                    ("table",),
                    "One explicit reference class and predicted class for every held-out sample.",
                ),
                ScientificPresentation(
                    "metrics",
                    "Classification Evaluation Metrics",
                    "metric_record",
                    ("default",),
                    ("record", "table"),
                    "Accuracy, balanced accuracy, macro metrics, and per-class held-out performance.",
                ),
                ScientificPresentation(
                    "confusion",
                    "Confusion Matrix",
                    "confusion_matrix",
                    ("visualization",),
                    ("plot", "table"),
                    "Counts and row-normalized rates for every observed and predicted class.",
                ),
            ),
        ),
    )

    async def execute(self, input_data: Any = None, y_true: Any = None, **kwargs: Any) -> NodeResult:
        del kwargs
        if y_true is None:
            raise ValueError("classification evaluation requires an explicit y_true edge")
        return evaluate_classification_v2(input_data, y_true, node_id=self.node_id)

    def score_held_out_predictions(
        self,
        predictions: object,
        held_out_target: object,
        *,
        accumulator: ClassificationMetricAccumulator | None = None,
        simca_membership: object = None,
        simca_labels: object = None,
    ) -> ClassificationMetricSet:
        """Score one fold and optionally merge it into the campaign pool."""

        predicted = _label_vector(predictions, name="predictions")
        observed = _label_vector(held_out_target, name="held_out_target")
        labels = None if accumulator is None else accumulator.labels
        metric_record = classification_metric_set(
            observed,
            predicted,
            labels=labels,
            simca_membership=simca_membership,
            simca_labels=simca_labels,
        )
        if accumulator is not None:
            accumulator.add(observed, predicted)
            if simca_membership is not None:
                accumulator.add_simca_acceptance(observed, simca_membership, labels=simca_labels)
        return metric_record

    def generate_python(
        self,
        inputs: dict[str, str],
        indent: str = "    ",
        use_scp: bool = True,
    ) -> list[str]:
        del use_scp
        predictions = inputs.get("default", inputs.get("y_pred", "None"))
        observed = inputs.get("y_true", "None")
        return [
            f"{indent}from spectra_sherpa.app.services.dag.nodes.classification_evaluator_node import "
            "evaluate_classification_v2",
            f"{indent}results[{self.node_id!r}] = evaluate_classification_v2(",
            f"{indent}    {predictions}, {observed}, node_id={self.node_id!r},",
            f"{indent}).outputs",
        ]

    def exported_output_ports(self) -> set[str]:
        return {"default", "comparison", "visualization"}


bind_stable_execution_contract(
    ClassificationEvaluatorV2Node,
    runtime_family=RuntimeFamily.SHERPA_NATIVE,
    lifecycle_kind=LifecycleKind.EVALUATOR,
    implementation_id="spectrasherpa.classification_evaluator",
    implementation_version="4.0.0",
    required_worker_capabilities=(WorkerCapability.READ_DATASET,),
    managed_optimization_eligibility=(ManagedOptimizationEligibility.LOCAL, ManagedOptimizationEligibility.DEVELOPMENT),
    sample_effect="aggregates_samples",
    feature_effect="preserves_features",
    axis_effect="preserves_axis",
    unit_effect="preserves_units",
    resource_hints={"timeout_seconds": 30, "cpu_seconds": 30, "memory_bytes": 536_870_912},
    license_id="BSD-3-Clause",
    help_reference="docs/nodes/selection-validation.md",
    implementation_distributions=("numpy", "scikit-learn"),
    runtime_requirements=(("numpy", "1.26.4"), ("scikit-learn", "1.9.0")),
    managed_optimization_profiles=("first_party_pls",),
    citations=(
        "Powers, D.M.W. (2011). Evaluation: From Precision, Recall and F-Measure to ROC, "
        "Informedness, Markedness and Correlation. Journal of Machine Learning Technologies 2(1), 37-63.",
    ),
    deterministic=True,
    target_access="required",
    group_access="none",
    supervised_task="classification",
)


__all__ = ["ClassificationEvaluatorV2Node", "evaluate_classification_v2"]
