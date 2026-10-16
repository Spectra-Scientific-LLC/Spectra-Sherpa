"""Explicit, model-bound PLS-DA random-response validation operation."""

from __future__ import annotations

import asyncio
import hashlib
import json
import threading
from collections.abc import Mapping, Sequence
from typing import Any

from spectra_sherpa.app.services.dag.node_base import (
    Node,
    NodeMetadata,
    NodeParameter,
    NodePolicy,
    NodeResult,
    PortMetadata,
    register_node,
)
from spectra_sherpa.app.services.dag.nodes.modeling import component_validation
from spectra_sherpa.app.services.dag.presentation_contract import NodePresentationContract, ScientificPresentation
from spectra_sherpa.app.services.dag.stable_execution_contract import bind_stable_execution_contract
from spectra_sherpa.app.services.dag.supervision_binding import admit_attached_sample_table_supervision
from spectra_sherpa.execution_contract_vocabulary import (
    LifecycleKind,
    ManagedOptimizationEligibility,
    RuntimeFamily,
    WorkerCapability,
)

from . import plsda_nodes, plsda_permutation, plsda_state


def _parameters(values: dict[str, object]) -> dict[str, object]:
    defaults: dict[str, object] = {
        "permutations": 19,
        "folds": 3,
        "maximum_components": 5,
        "seed": 42,
        "block_column": "",
    }
    if set(values) - set(defaults):
        raise ValueError("PLS-DA permutation settings contain an unknown parameter")
    result = {**defaults, **values}
    for key, lower, upper in (
        ("permutations", 19, 199),
        ("folds", 2, 5),
        ("maximum_components", 1, 10),
        ("seed", 0, 2**32 - 1),
    ):
        value = result[key]
        if type(value) is not int or not lower <= value <= upper:
            raise ValueError(f"PLS-DA permutation {key} must be an integer between {lower} and {upper}")
    column = result["block_column"]
    if not isinstance(column, str) or len(column) > 128 or column != column.strip():
        raise ValueError("PLS-DA permutation block_column must be an exact column name or empty")
    return result


def _permutation_outputs(
    X: Any,
    y: Any,
    fitted_state: Any,
    *,
    parameters: dict[str, object],
    cancelled: Any = lambda: False,
) -> dict[str, object]:
    settings = _parameters(parameters)
    if not isinstance(fitted_state, dict):
        raise ValueError("Response permutation requires a connected fitted PLS-DA state")
    saved = plsda_state.SherpaPLSDAArtifact.from_fitted_state(fitted_state)
    dataset, matrix, labels, classes = plsda_nodes._plsda_inputs(X, y)
    reason = component_validation.cv_unavailable_reason(dataset)
    if reason is not None:
        raise ValueError(f"Response permutation cannot establish fold-local preprocessing: {reason}")
    maximum = int(settings["maximum_components"])
    if maximum < saved.effective_n_components:
        raise ValueError("Component search cannot end before the saved model's effective component count")
    if maximum > min(matrix.shape[1], matrix.shape[0] - 1):
        raise ValueError("Component search exceeds the calibration rank bound")
    # Recompute the connected state from this exact cohort and class vector.
    # Width, class names, or an unrelated saved model alone are not sufficient.
    core = plsda_nodes._plsda_scientific_core(
        dataset,
        labels,
        parameters={"n_components": saved.requested_n_components, "scale": saved.scale},
    )
    reconstructed = core["artifact"].to_fitted_state()
    if reconstructed != fitted_state:
        raise ValueError("The connected PLS-DA state was not fitted from this exact calibration cohort")
    attached = admit_attached_sample_table_supervision(dataset)
    groups = None if attached is None else attached.groups
    blocks = None
    block_column = str(settings["block_column"])
    if block_column:
        if attached is None or dataset.sample_axis is None:
            raise ValueError("Exchangeability blocks require a verified attached sample table")
        table = dataset.sample_axis.sample_table
        if not isinstance(table, Mapping):
            raise ValueError("Exchangeability blocks require a verified attached sample table")
        values = table.get(block_column)
        if not isinstance(values, Sequence) or isinstance(values, (str, bytes)) or len(values) != len(labels):
            raise ValueError("Exchangeability block column is absent or not aligned to the verified sample table")
        blocks = values
    state_digest = hashlib.sha256(
        json.dumps(fitted_state, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()
    evidence = plsda_permutation.response_permutation_evidence(
        matrix,
        labels,
        groups=groups,
        blocks=blocks,
        model_state_sha256=state_digest,
        saved_components=saved.effective_n_components,
        components=maximum,
        folds=int(settings["folds"]),
        permutations=int(settings["permutations"]),
        seed=int(settings["seed"]),
        scale=saved.scale,
        fit_model=lambda x, d, domain, count, scaling: plsda_nodes._native_plsda_fit(
            x, d, domain, n_components=count, scale=scaling
        )[0],
        cancelled=cancelled,
    )
    evidence["upstream_preprocessing"] = (
        "caller_declared_raw_array_no_recorded_preprocessing"
        if not getattr(dataset, "provenance", None)
        else "recorded_sample_local_or_partition_only_steps"
    )
    evidence["exchangeability_block_column"] = block_column or None
    return evidence


@register_node
class PLSDAPermutationNode(Node):
    """Refit the complete PLS-DA component search under exchangeable labels."""

    metadata = NodeMetadata(
        node_type="diagnostics.plsda_permutation",
        category="validation",
        label="PLS-DA Response Permutation",
        description=(
            "Compare the selected PLS-DA cross-validation score with a seeded Monte Carlo random-label null. "
            "Connect the same calibration X, class labels, and fitted PLS-DA state; test samples remain excluded."
        ),
        parameters=[
            NodeParameter(
                name="permutations",
                label="Response permutations",
                param_type="number",
                default=19,
                min_value=19,
                max_value=199,
                max_value_reason="Bounds repeated fold-local model fits.",
                step=1,
            ),
            NodeParameter(
                name="folds",
                label="Stratified folds",
                param_type="number",
                default=3,
                min_value=2,
                max_value=5,
                max_value_reason="Preserves classes in bounded grouped folds.",
                step=1,
            ),
            NodeParameter(
                name="maximum_components",
                label="Maximum latent variables",
                param_type="number",
                default=5,
                min_value=1,
                max_value=10,
                max_value_reason="Bounds full component search per shuffle.",
                step=1,
            ),
            NodeParameter(
                name="seed",
                label="Random seed",
                param_type="number",
                default=42,
                min_value=0,
                max_value=2**32 - 1,
                max_value_reason="Uses an exact unsigned 32-bit reproducibility seed.",
                step=1,
            ),
            NodeParameter(
                name="block_column",
                label="Exchangeability block column",
                param_type="text",
                default="",
                required=False,
                description="Optional column from the verified attached sample table; never a free-standing vector.",
            ),
        ],
        input_types=["SherpaDataset", "array"],
        output_type="dict",
        input_ports=[
            PortMetadata(name="X", type_ref="spectrasherpa://types/Array2D/1.0", required=True, label="Calibration X"),
            PortMetadata(
                name="y", type_ref="spectrasherpa://types/TargetMatrix/1.0", required=False, label="Class labels"
            ),
            PortMetadata(
                name="fitted_state",
                type_ref="spectrasherpa://types/ClassificationModel/1.0",
                required=True,
                label="Fitted PLS-DA state",
            ),
        ],
        output_ports=[
            PortMetadata(
                name="default",
                type_ref="spectrasherpa://types/ValidationResult/1.0",
                required=True,
                label="Response-permutation evidence",
            ),
        ],
        policy=NodePolicy(),
        presentation_contract=NodePresentationContract(
            default_presentation="permutation",
            presentations=(
                ScientificPresentation(
                    "permutation",
                    "PLS-DA Random-Response Check",
                    "validation_result",
                    ("default",),
                    ("record",),
                    "Observed balanced accuracy, null scores, and finite-sample p-value; development evidence only.",
                ),
            ),
        ),
        canonical_parameter_validator=_parameters,
    )

    async def execute(self, X: Any = None, y: Any = None, fitted_state: Any = None, **kwargs: Any) -> NodeResult:
        del kwargs
        stop = threading.Event()
        worker = asyncio.create_task(
            asyncio.to_thread(
                _permutation_outputs,
                X,
                y,
                fitted_state,
                parameters=self._resolve_params(),
                cancelled=stop.is_set,
            )
        )
        try:
            evidence = await asyncio.shield(worker)
        except asyncio.CancelledError:
            stop.set()
            try:
                await asyncio.shield(worker)
            except InterruptedError:
                pass
            raise
        return NodeResult(outputs={"default": evidence}, diagnostics={"permutation_status": "complete"})

    def generate_python(self, inputs: dict[str, str], indent: str = "    ", use_scp: bool = True) -> list[str]:
        del use_scp
        return [
            f"{indent}from spectra_sherpa.app.services.dag.nodes.classification.plsda_permutation_node "
            "import _permutation_outputs",
            f"{indent}results[{self.node_id!r}] = {{'default': _permutation_outputs(",
            f"{indent}    {inputs.get('X', 'None')}, {inputs.get('y', 'None')},",
            f"{indent}    {inputs.get('fitted_state', 'None')},",
            f"{indent}    parameters={self._resolve_params()!r},",
            f"{indent})}}",
        ]

    def exported_output_ports(self) -> set[str]:
        return {"default"}


bind_stable_execution_contract(
    PLSDAPermutationNode,
    runtime_family=RuntimeFamily.SHERPA_NATIVE,
    lifecycle_kind=LifecycleKind.EVALUATOR,
    implementation_id="spectrasherpa.diagnostics.plsda_permutation",
    implementation_version="1.0.0",
    required_worker_capabilities=(WorkerCapability.READ_DATASET,),
    managed_optimization_eligibility=(ManagedOptimizationEligibility.LOCAL,),
    sample_effect="aggregates_samples",
    feature_effect="preserves_features",
    axis_effect="preserves_axis",
    unit_effect="preserves_units",
    resource_hints={"timeout_seconds": 180, "cpu_seconds": 180, "memory_bytes": 1_073_741_824},
    license_id="BSD-3-Clause",
    help_reference="docs/nodes/classification.md",
    implementation_distributions=("numpy", "scipy", "scikit-learn"),
    runtime_requirements=(("numpy", "1.26.4"), ("scipy", "1.17.1"), ("scikit-learn", "1.9.0")),
    managed_optimization_profiles=(),
    citations=("Ojala and Garriga, Permutation Tests for Studying Classifier Performance, JMLR 11 (2010) 1833-1863.",),
    implementation_modules=(plsda_nodes, plsda_permutation, component_validation),
    deterministic=True,
    target_access="required",
    group_access="optional",
    supervised_task="classification",
)


__all__ = ["PLSDAPermutationNode", "_permutation_outputs"]
