"""Bounded workbench evaluation with explicit held-out source labels.

Kept separate from the frozen managed evaluator to preserve its replay identity.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace
from typing import Any

import numpy as np

import spectra_sherpa.app.lib.axes as axes
import spectra_sherpa.app.lib.sherpa_dataset as sherpa_dataset
import spectra_sherpa.app.services.dag.nodes.regression_evaluator_node as canonical_evaluator
import spectra_sherpa.app.services.dag.presentation_limits as presentation_limits
import spectra_sherpa.app.services.dag.regression_comparison as regression_comparison
import spectra_sherpa.sdk.validate as sdk_validate
from spectra_sherpa.app.services.dag.node_base import NodeResult, PortMetadata, register_node
from spectra_sherpa.app.services.dag.stable_execution_contract import bind_stable_execution_contract
from spectra_sherpa.execution_contract_vocabulary import (
    LifecycleKind,
    ManagedOptimizationEligibility,
    RuntimeFamily,
    WorkerCapability,
)


@register_node
class LabeledRegressionEvaluatorNode(canonical_evaluator.RegressionEvaluatorV2Node):
    metadata = replace(
        canonical_evaluator.RegressionEvaluatorV2Node.metadata,
        node_type="diagnostics.labeled_regression_evaluator",
        label="Held-out Regression with Source Labels",
        description=(
            "Scores explicit held-out predictions against reference values, preserving sample labels "
            "from the matching held-out dataset. Refuses inconsistent targets or missing labels. "
            "Before comparison expansion, admits at most 500,000 counted values and 2 MiB text, "
            "including repeated labels and response names; select a smaller explicit cohort if exceeded."
        ),
        input_ports=[
            *[
                replace(port, required=True)
                for port in canonical_evaluator.RegressionEvaluatorV2Node.metadata.input_ports
            ],
            PortMetadata(
                name="sample_context",
                type_ref="spectrasherpa://types/SpectralDataset/1.0",
                required=True,
                label="Held-out Sample Context",
                description="Held-out dataset whose labels and bound targets match the reference edge in row order.",
            ),
        ],
        execution_contract=None,
    )

    async def execute(
        self, input_data: Any = None, y_true: Any = None, sample_context: Any = None, **kwargs: Any
    ) -> NodeResult:
        return evaluate_labeled_regression(
            input_data,
            y_true,
            sample_context=sample_context,
            node_id=self.node_id,
            target_names=self._configured_target_names(),
        )

    def generate_python(self, inputs: dict[str, str], indent: str = "    ", use_scp: bool = True) -> list[str]:
        return [
            f"{indent}from spectra_sherpa.app.services.dag.nodes.labeled_regression_evaluator_node import "
            "evaluate_labeled_regression",
            f"{indent}results[{self.node_id!r}] = evaluate_labeled_regression(",
            f"{indent}    {inputs.get('default', 'None')}, {inputs.get('y_true', 'None')},",
            f"{indent}    sample_context={inputs.get('sample_context', 'None')},",
            f"{indent}    node_id={self.node_id!r}, target_names={self._configured_target_names()!r},",
            f"{indent}).outputs",
        ]


def evaluate_labeled_regression(
    predictions: object,
    held_out_target: object,
    *,
    sample_context: Any,
    node_id: str = "labeled-regression-evaluator",
    target_names: Sequence[str] | None = None,
) -> NodeResult:
    # Include comparison dictionary fields/keys before the shared evaluator creates rows.
    presentation_limits.require_bounded_presentation(
        [predictions, held_out_target],
        surface="Held-out regression comparison",
        multiplier=10,
        max_values=500_000,
    )
    predicted = canonical_evaluator._target_matrix(predictions, name="predictions")
    observed = canonical_evaluator._target_matrix(held_out_target, name="held_out_target")
    if predicted.shape != observed.shape:
        raise ValueError("predictions and held_out_target must have the same response-matrix shape")
    if not isinstance(sample_context, sherpa_dataset.SherpaDataset) or sample_context.n_samples != observed.shape[0]:
        raise ValueError("held-out sample context must match the evaluated population")
    bound_target = canonical_evaluator._target_matrix(sample_context.target, name="sample-context target")
    if bound_target.shape != observed.shape or not np.array_equal(bound_target, observed):
        raise ValueError("held-out sample context targets must exactly match the reference edge in row order")
    context_names = list(sample_context.target_context.target_names or [])
    if not context_names and sample_context.target_context.target_name:
        context_names = [sample_context.target_context.target_name]
    if len(context_names) != observed.shape[1]:
        raise ValueError("held-out sample context requires one explicit response name per target")
    names = canonical_evaluator._target_names(observed.shape[1], target_names or context_names)
    if names != context_names:
        raise ValueError("held-out sample context response names must match the evaluated targets")
    axis = sample_context.get_observation_axis()
    labels = getattr(axis, "labels", None)
    if (
        labels is None
        or len(labels) != observed.shape[0]
        or any(not isinstance(label, str) or not label.strip() for label in labels)
    ):
        raise ValueError("held-out sample context requires one explicit sample label per observation")
    # Long-form output repeats each sample label per target and each name per sample.
    for values, repetitions in ((labels, observed.shape[1]), (names, observed.shape[0])):
        presentation_limits.require_bounded_presentation(
            values,
            surface="Held-out regression comparison",
            multiplier=repetitions,
            max_values=500_000,
        )
    result = canonical_evaluator.evaluate_regression_v2(predicted, observed, node_id=node_id, target_names=names)
    comparison = result.outputs["comparison"]
    for index, row in enumerate(comparison["data"]):
        row["sample"] = labels[index // observed.shape[1]]
    comparison["metadata"]["sample_identity_mode"] = "source_label"
    return result


bind_stable_execution_contract(
    LabeledRegressionEvaluatorNode,
    runtime_family=RuntimeFamily.SHERPA_NATIVE,
    lifecycle_kind=LifecycleKind.EVALUATOR,
    implementation_id="spectrasherpa.labeled_regression_evaluator",
    implementation_version="1.0.0",
    required_worker_capabilities=(WorkerCapability.READ_DATASET,),
    managed_optimization_eligibility=(ManagedOptimizationEligibility.LOCAL,),
    sample_effect="aggregates_samples",
    feature_effect="preserves_features",
    axis_effect="preserves_axis",
    unit_effect="preserves_units",
    resource_hints={"timeout_seconds": 30, "cpu_seconds": 30, "memory_bytes": 1_073_741_824},
    license_id="BSD-3-Clause",
    help_reference="docs/nodes/selection-validation.md",
    implementation_modules=(
        canonical_evaluator,
        regression_comparison,
        sdk_validate,
        sherpa_dataset,
        axes,
        presentation_limits,
    ),
    implementation_distributions=("numpy", "scikit-learn"),
    runtime_requirements=(("numpy", "1.26.4"), ("scikit-learn", "1.9.0"), ("scipy", "1.17.1")),
    target_access="required",
    supervised_task="regression",
)
