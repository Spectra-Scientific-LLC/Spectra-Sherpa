"""One fitted scale state, applied to calibration and application branches.

This separate operation leaves the historical ``preprocess.scale`` contract
untouched. All fitting and state application use that node's canonical ABI.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from typing import Any

from spectra_sherpa.app.services.dag.node_base import NodeResult, PortMetadata, register_node
from spectra_sherpa.app.services.dag.stable_execution_contract import bind_stable_execution_contract
from spectra_sherpa.execution_contract_vocabulary import (
    LifecycleKind,
    ManagedOptimizationEligibility,
    RuntimeFamily,
    WorkerCapability,
)

from . import scale_node
from .scale_node import ScaleNode

_metadata = replace(
    ScaleNode.metadata,
    node_type="preprocess.shared_reference_scale",
    label="Shared Reference Scale",
    description=(
        "Fit one scale state on calibration reference rows and apply it to both "
        "those rows and a separate application branch."
    ),
    parameters=deepcopy(ScaleNode.metadata.parameters),
    input_ports=deepcopy(ScaleNode.metadata.input_ports),
    output_ports=deepcopy(ScaleNode.metadata.output_ports),
    execution_contract=None,
    presentation_contract=None,
)
_metadata.input_ports[1].required = True
_metadata.output_ports.append(
    PortMetadata(
        name="reference_scaled",
        type_ref="spectrasherpa://types/SpectralDataset/1.0",
        required=True,
        label="Scaled Calibration Reference",
        description="Calibration rows transformed by the exact state used for application rows.",
        accepted_data_roles=["X_spectra", "X_features"],
    )
)


@register_node
class SharedReferenceScaleNode(ScaleNode):
    """Expose two outputs from one canonical calibration fit."""

    metadata = _metadata

    async def execute(self, default: Any = None, input_data: Any = None, reference: Any = None, **kwargs: Any):
        del kwargs
        if reference is None:
            raise ValueError("Shared reference scaling requires calibration reference rows.")
        application = input_data if input_data is not None else default
        state = self.fit_fitted_state(reference)
        return NodeResult(
            outputs={
                "default": self.apply_fitted_state(application, state),
                "reference_scaled": self.apply_fitted_state(reference, state),
            },
            diagnostics={
                "method": state["method"],
                "center": state["center"],
                "fitted_state_serializer": state["serializer"],
            },
        )

    def generate_python(self, inputs, indent="    ", use_scp=True):
        application = inputs.get("default") if inputs else None
        if application is None:
            raise ValueError("Shared reference scaling export requires application rows.")
        reference = inputs.get("reference") if inputs else None
        if reference is None:
            raise ValueError("Shared reference scaling export requires calibration reference rows.")
        params = self._resolve_params()
        return [
            f"{indent}from spectra_sherpa.app.services.dag.nodes.preprocessing.scale_node import ScaleNode",
            f"{indent}_transform = ScaleNode({self.node_id!r}, {params!r})",
            f"{indent}_state = _transform.fit_fitted_state({reference})",
            f"{indent}results[{self.node_id!r}] = {{'default': _transform.apply_fitted_state({application}, _state), "
            f"'reference_scaled': _transform.apply_fitted_state({reference}, _state)}}",
        ]


bind_stable_execution_contract(
    SharedReferenceScaleNode,
    runtime_family=RuntimeFamily.SHERPA_NATIVE,
    lifecycle_kind=LifecycleKind.FITTED_TRANSFORM,
    implementation_id="spectrasherpa.preprocess.shared_reference_scale",
    implementation_version="1.0.0",
    required_worker_capabilities=(WorkerCapability.READ_DATASET,),
    managed_optimization_eligibility=(ManagedOptimizationEligibility.LOCAL,),
    sample_effect="preserves_samples",
    feature_effect="preserves_features",
    axis_effect="preserves_axis",
    unit_effect="changes_units",
    resource_hints={"timeout_seconds": 30, "cpu_seconds": 30, "memory_bytes": 1_073_741_824},
    license_id="Apache-2.0",
    help_reference="docs/nodes/preprocessing.md",
    implementation_modules=(scale_node,),
    implementation_distributions=("numpy",),
    runtime_requirements=(("numpy", "1.26.4"),),
    fitted_state_serializer="spectra.scale-reference-json.v2",
)
