"""The closed first-wedge held-out regression evaluator.

The canonical fold executor remains the managed target authority and obtains
the response through :class:`FoldLifecycleContext`, after the fitted model has
produced held-out predictions.  Local workbench DAGs must instead provide an
explicit typed ``y_true`` edge.  Both paths use the same metric registry, while
the separation makes it impossible for a managed model implementation to
grade itself by quietly reading held-out targets.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import numpy as np

import spectra_sherpa.app.services.dag.regression_comparison as regression_comparison
import spectra_sherpa.sdk.validate as sdk_validate
from spectra_sherpa.app.services.dag.node_base import (
    Node,
    NodeMetadata,
    NodeParameter,
    NodePolicy,
    NodeResult,
    PortMetadata,
    register_node,
)
from spectra_sherpa.app.services.dag.presentation_contract import (
    NodePresentationContract,
    ScientificPresentation,
)
from spectra_sherpa.app.services.dag.stable_execution_contract import bind_stable_execution_contract
from spectra_sherpa.execution_contract_vocabulary import (
    LifecycleKind,
    ManagedOptimizationEligibility,
    RuntimeFamily,
    WorkerCapability,
)
from spectra_sherpa.sdk.validate import RegressionMetricAccumulator, RegressionMetrics


def _target_matrix(value: object, *, name: str) -> np.ndarray:
    """Return a finite target matrix without flattening response columns."""
    try:
        array = np.asarray(value, dtype=np.float64)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be a finite prediction or target matrix") from exc
    if array.ndim == 1:
        array = array.reshape(-1, 1)
    if array.ndim != 2 or array.shape[0] < 1 or array.shape[1] < 1 or not np.isfinite(array).all():
        raise ValueError(f"{name} must be a finite prediction or target matrix")
    return np.array(array, copy=True)


def _one_target_column(value: object, *, name: str) -> np.ndarray:
    """Return the one selected response required by managed campaigns."""

    array = _target_matrix(value, name=name)
    if array.shape[1] != 1:
        raise ValueError(f"{name} must contain one selected target for managed validation")
    return np.array(array[:, 0], copy=True)


def _target_names(count: int, supplied: Sequence[str] | None) -> list[str]:
    names = list(supplied or [f"Target {index + 1}" for index in range(count)])
    if len(names) != count or any(not isinstance(name, str) or not name.strip() for name in names):
        raise ValueError("target_names must contain one non-empty label per response")
    return [name.strip() for name in names]


@register_node
class RegressionEvaluatorV2Node(Node):
    """Score quantitative predictions under the SDK metric registry."""

    metadata = NodeMetadata(
        node_type="diagnostics.regression_evaluator",
        category="diagnostics",
        label="Reference Regression Evaluator (v2)",
        description=(
            "Scores quantitative targets using the versioned regression metric registry. "
            "Held-out scope requires executor-verified training and evaluation lineage. "
            "PLS2 responses are reported per target without scale-blending aggregation. "
            "Local DAGs require an explicit reference-value edge; managed validation receives targets "
            "only from the canonical fold authority."
        ),
        parameters=[
            NodeParameter(
                name="target_names",
                label="Response Labels",
                param_type="string_list",
                default=[],
                description="Exact response labels inherited from the selected dataset target.",
                required=False,
                category="internal",
            )
        ],
        input_ports=[
            PortMetadata(
                name="default",
                type_ref="spectrasherpa://types/TargetMatrix/1.0",
                required=True,
                label="Predictions",
                description="One or more predicted quantitative targets per held-out sample.",
            ),
            PortMetadata(
                name="y_true",
                type_ref="spectrasherpa://types/TargetMatrix/1.0",
                required=False,
                label="Reference Values",
                description=(
                    "Explicit reference values for a local workbench evaluation. Managed validation "
                    "receives them only from the fold lifecycle instead."
                ),
            ),
        ],
        output_ports=[
            PortMetadata(
                name="default",
                type_ref="spectrasherpa://types/ValidationResult/1.0",
                required=True,
                label="Evaluation Metrics",
                description=(
                    "Bounded versioned metrics. Managed evidence retains only this aggregate; "
                    "the local workbench may also render the optional visualization output."
                ),
            ),
            PortMetadata(
                name="comparison",
                type_ref="spectrasherpa://types/RegressionComparison/1.0",
                required=False,
                label="Predicted vs Actual",
                description="Held-out references, predictions, and residuals from this exact evaluation.",
            ),
        ],
        input_types=["array"],
        output_type="dict",
        policy=NodePolicy(),
        presentation_contract=NodePresentationContract(
            default_presentation="held_out_comparison",
            presentations=(
                ScientificPresentation(
                    "held_out_comparison",
                    "Predicted vs Reference",
                    "regression_comparison",
                    ("comparison",),
                    ("plot", "table"),
                ),
                ScientificPresentation(
                    "metrics",
                    "Evaluation Metrics",
                    "metric_record",
                    ("default",),
                    ("record",),
                ),
            ),
        ),
    )

    def score_held_out_predictions(
        self,
        predictions: object,
        held_out_target: object,
        *,
        accumulator: RegressionMetricAccumulator | None = None,
    ) -> RegressionMetrics:
        """Return the selected-target managed result without retaining row-level data.

        Managed optimization selects one response before fold execution. Local
        Workbench execution uses :func:`evaluate_regression_v2` for PLS2.
        """

        predicted = _one_target_column(predictions, name="predictions")
        observed = _one_target_column(held_out_target, name="held_out_target")
        if predicted.shape != observed.shape:
            raise ValueError("predictions and held_out_target must have the same one-column shape")
        if accumulator is not None:
            accumulator.add(observed, predicted)
        return sdk_validate.metrics(observed, predicted)

    def _configured_target_names(self) -> list[str] | None:
        raw_names = self.parameters.get("target_names")
        if raw_names is None or raw_names == []:
            return None
        if not isinstance(raw_names, list):
            raise ValueError("target_names must be a list of non-empty response labels")
        if any(not isinstance(name, str) or not name.strip() for name in raw_names):
            raise ValueError("target_names must be a list of non-empty response labels")
        return [name.strip() for name in raw_names]

    async def execute(
        self,
        input_data: Any = None,
        y_true: Any = None,
        **kwargs: Any,
    ) -> NodeResult:
        """Evaluate explicit local truth; managed folds use the custody method above."""

        del kwargs
        if y_true is None:
            raise RuntimeError(
                "local regression evaluation requires an explicit y_true edge; "
                "managed evaluation requires canonical fold lifecycle authority"
            )
        return evaluate_regression_v2(
            input_data,
            y_true,
            node_id=self.node_id,
            target_names=self._configured_target_names(),
        )

    def generate_python(
        self,
        inputs: dict[str, str],
        indent: str = "    ",
        use_scp: bool = True,
    ) -> list[str]:
        """Project local evaluation through the same metric authority."""

        del use_scp
        predictions = inputs.get("default", inputs.get("y_pred", "None"))
        observed = inputs.get("y_true", "None")
        target_names = self._configured_target_names()
        return [
            f"{indent}from spectra_sherpa.app.services.dag.nodes.regression_evaluator_node import "
            "evaluate_regression_v2",
            f"{indent}results[{self.node_id!r}] = evaluate_regression_v2(",
            f"{indent}    {predictions}, {observed}, node_id={self.node_id!r}, target_names={target_names!r},",
            f"{indent}).outputs",
        ]

    def exported_output_ports(self) -> set[str]:
        return {"default", "comparison"}


def evaluate_regression_v2(
    predictions: object,
    held_out_target: object,
    *,
    node_id: str = "regression-evaluator-v2",
    target_names: Sequence[str] | None = None,
) -> NodeResult:
    """Return one metric record per response using the shared registry.

    Multi-response metrics are deliberately not averaged: RMSE, SEP, and RER
    carry each response's units and scale, so a blended scalar would be
    scientifically ambiguous.
    """

    predicted = _target_matrix(predictions, name="predictions")
    observed = _target_matrix(held_out_target, name="held_out_target")
    if predicted.shape != observed.shape:
        raise ValueError("predictions and held_out_target must have the same response-matrix shape")
    names = _target_names(observed.shape[1], target_names)
    comparison = regression_comparison.build_regression_comparison(
        observed,
        predicted,
        role="unqualified_evaluation",
        target_names=names,
    )
    records = [record["metrics"] for record in comparison["statistics"]["targets"]]
    if len(records) == 1:
        metric_output: dict[str, object] = {"task_type": "regression", **records[0]}
    else:
        metric_output = {
            "schema_version": "spectrasherpa-regression-metric-set/1",
            "task_type": "regression",
            "registry_version": sdk_validate.REGRESSION_METRIC_REGISTRY_VERSION,
            "n_samples": int(observed.shape[0]),
            "n_targets": len(records),
            "aggregation": "none",
            "targets": [{"target": name, "metrics": record} for name, record in zip(names, records, strict=True)],
        }
    diagnostics: dict[str, object] = {
        "metric_registry": sdk_validate.REGRESSION_METRIC_REGISTRY_VERSION,
        "node_id": node_id,
        "n_targets": len(records),
        "aggregation": "none",
        "target_names": names,
    }
    if len(records) == 1:
        diagnostics.update(records[0])
    return NodeResult(
        outputs={"default": metric_output, "comparison": comparison},
        diagnostics=diagnostics,
    )


bind_stable_execution_contract(
    RegressionEvaluatorV2Node,
    runtime_family=RuntimeFamily.SHERPA_NATIVE,
    lifecycle_kind=LifecycleKind.EVALUATOR,
    implementation_id="spectrasherpa.regression_evaluator",
    implementation_version="5.0.0",
    required_worker_capabilities=(WorkerCapability.READ_DATASET,),
    managed_optimization_eligibility=(ManagedOptimizationEligibility.LOCAL, ManagedOptimizationEligibility.DEVELOPMENT),
    sample_effect="aggregates_samples",
    feature_effect="preserves_features",
    axis_effect="preserves_axis",
    unit_effect="preserves_units",
    resource_hints={"timeout_seconds": 30, "cpu_seconds": 30, "memory_bytes": 1_073_741_824},
    license_id="BSD-3-Clause",
    help_reference="docs/nodes/selection-validation.md",
    implementation_modules=(sdk_validate, regression_comparison),
    implementation_distributions=("numpy", "scikit-learn"),
    runtime_requirements=(("numpy", "1.26.4"), ("scikit-learn", "1.9.0"), ("scipy", "1.17.1")),
    managed_optimization_profiles=("first_party_pls",),
    citations=(
        "Kucheryavskiy, mdatools regression-results reference (RMSE, R2, slope, and bias), "
        "https://search.r-project.org/CRAN/refmans/mdatools/html/regres.html",
    ),
    target_access="required",
    supervised_task="regression",
)


__all__ = ["RegressionEvaluatorV2Node", "evaluate_regression_v2"]
