"""Canonical Sherpa-native rubberband baseline correction."""

from __future__ import annotations

from typing import Any

import numpy as np

from spectra_sherpa.app.lib import rubberband as rubberband_authority
from spectra_sherpa.app.lib import sherpa_dataset as sherpa_dataset_contract
from spectra_sherpa.app.lib.axes import SpectralAxis
from spectra_sherpa.app.lib.rubberband import RubberbandResult, rubberband_correct
from spectra_sherpa.app.services.dag import meta_helpers as dag_meta_helpers
from spectra_sherpa.app.services.dag import supervision_binding
from spectra_sherpa.app.services.dag.node_base import NodePolicy
from spectra_sherpa.app.services.dag.stable_execution_contract import bind_stable_execution_contract
from spectra_sherpa.execution_contract_vocabulary import (
    LifecycleKind,
    ManagedOptimizationEligibility,
    RuntimeFamily,
    WorkerCapability,
)

from . import _shared
from ._shared import (
    EFFECT_BASELINE_CORRECTED,
    Node,
    NodeMetadata,
    NodeResult,
    PortMetadata,
    SherpaDataset,
    add_processing_step,
    build_dataset_like,
    coerce_to_sherpa,
    register_node,
    to_numpy_2d,
)


def _build_rubberband_result(
    source: SherpaDataset,
    numerical: RubberbandResult,
    *,
    node_id: str,
) -> SherpaDataset:
    result = build_dataset_like(numerical.corrected, source)
    add_processing_step(
        result,
        "baseline.rubberband",
        {"method": "lower_convex_envelope"},
        node_id=node_id,
        state_effects=[EFFECT_BASELINE_CORRECTED],
    )
    supervision_binding.rebind_sample_preserving_supervision(source, result)
    return result


def _execute_rubberband(source: SherpaDataset, *, node_id: str) -> tuple[SherpaDataset, dict[str, Any]]:
    feature_axis = source.feature_axis
    if not isinstance(feature_axis, SpectralAxis):
        raise ValueError(
            "baseline.rubberband requires a SpectralAxis; load spectral data "
            "with ordered feature coordinates "
            "before applying a rubberband baseline."
        )
    matrix = to_numpy_2d(source, name="input_data", dtype=np.float64)
    if not np.isfinite(matrix).all():
        raise ValueError(
            "baseline.rubberband requires finite input values; remove an explicitly blanked region "
            "with preprocess.clip_range before baseline correction"
        )
    numerical = rubberband_correct(matrix, feature_axis.values)
    anchor_counts = [len(indices) for indices in numerical.anchor_indices]
    diagnostics: dict[str, Any] = {
        "method": "lower_convex_envelope",
        "anchor_count_min": min(anchor_counts),
        "anchor_count_max": max(anchor_counts),
        "max_baseline_magnitude": float(abs(numerical.baseline).max()),
        "max_absolute_correction": float(abs(numerical.corrected).max()),
    }
    return _build_rubberband_result(source, numerical, node_id=node_id), diagnostics


@register_node
class BaselineRubberbandNode(Node):
    """Subtract each spectrum's lower convex-envelope baseline."""

    metadata = NodeMetadata(
        node_type="baseline.rubberband",
        category="preprocessing",
        label="Baseline (Rubberband)",
        description=(
            "Subtract the piecewise-linear lower convex envelope of every spectrum. "
            "Select a fitting interval explicitly with Clip Range upstream."
        ),
        parameters=[],
        input_types=["SpectralDataset"],
        input_ports=[
            PortMetadata(
                name="default",
                type_ref="spectrasherpa://types/SpectralDataset/1.0",
                required=True,
                label="Input Spectra",
                description="Spectral data to process",
            ),
        ],
        output_ports=[
            PortMetadata(
                name="default",
                type_ref="spectrasherpa://types/SpectralDataset/1.0",
                required=True,
                label="Baseline-corrected Spectra",
                description="Spectra after subtraction of the lower convex-envelope baseline",
            ),
        ],
        output_type="SpectralDataset",
        policy=NodePolicy(),
        help_url="docs/nodes/preprocessing.md#rubberband-baseline",
    )

    async def execute(self, input_data: Any = None, **kwargs: Any) -> NodeResult:
        del kwargs
        input_ds = coerce_to_sherpa(input_data, input_name="input_data")
        result, diagnostics = _execute_rubberband(input_ds, node_id=self.node_id)
        return NodeResult(outputs={"default": result}, diagnostics=diagnostics)

    def supports_python_export(self) -> bool:
        return True

    def generate_python(self, inputs, indent="    ", use_scp=True):
        del use_scp
        source = next(iter(inputs.values())) if inputs else "input_data"
        return [
            f"{indent}# --- Canonical Rubberband Baseline ({self.node_id}) ---",
            f"{indent}from spectra_sherpa.app.services.dag.nodes.preprocessing.baseline_nodes "
            "import _execute_rubberband",
            f"{indent}results[{self.node_id!r}], _rubberband_diagnostics = "
            f"_execute_rubberband({source}, node_id={self.node_id!r})",
        ]


bind_stable_execution_contract(
    BaselineRubberbandNode,
    runtime_family=RuntimeFamily.SHERPA_NATIVE,
    lifecycle_kind=LifecycleKind.STATELESS_TRANSFORM,
    implementation_id="spectrasherpa.baseline.rubberband",
    implementation_version="2.0.1",
    required_worker_capabilities=(WorkerCapability.READ_DATASET,),
    managed_optimization_eligibility=(ManagedOptimizationEligibility.LOCAL,),
    sample_effect="preserves_samples",
    feature_effect="preserves_features",
    axis_effect="preserves_axis",
    unit_effect="preserves_units",
    resource_hints={"timeout_seconds": 30, "cpu_seconds": 30, "memory_bytes": 1_073_741_824},
    license_id="Apache-2.0",
    help_reference="docs/nodes/preprocessing.md",
    implementation_modules=(
        supervision_binding,
        _shared,
        rubberband_authority,
        dag_meta_helpers,
        sherpa_dataset_contract,
    ),
    implementation_distributions=("numpy",),
    runtime_requirements=(("numpy", "1.26.4"),),
    citations=(
        "Butler et al., Using Raman spectroscopy to characterize biological materials, "
        "Analyst 143 (2018), DOI 10.1039/C8AN01384E",
        "Andrew, Another efficient algorithm for convex hulls in two dimensions, "
        "Information Processing Letters 9 (1979) 216-219, DOI 10.1016/0020-0190(79)90072-3",
    ),
)


__all__ = ["BaselineRubberbandNode"]
