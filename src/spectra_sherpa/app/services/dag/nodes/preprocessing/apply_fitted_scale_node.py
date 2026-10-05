"""Apply one canonical fitted-scale artifact state without fitting anything."""

from __future__ import annotations

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
from spectra_sherpa.app.services.dag.stable_execution_contract import bind_stable_execution_contract
from spectra_sherpa.core import execution_runtime as execution_runtime_contract
from spectra_sherpa.execution_contract_vocabulary import (
    LifecycleKind,
    ManagedOptimizationEligibility,
    RuntimeFamily,
    WorkerCapability,
)

from . import scale_node
from .scale_node import ScaleNode

_BINDING_FIELDS = frozenset(
    {
        "artifact_digest",
        "state_node_id",
        "state_digest",
        "state_content_digest",
        "serializer",
        "source_contract_digest",
    }
)
_SOURCE_CONTRACT = ScaleNode.metadata.resolved_execution_contract()
assert _SOURCE_CONTRACT is not None  # The source node owns a required execution contract.
_SOURCE_CONTRACT_DIGEST = _SOURCE_CONTRACT.digest
_SOURCE_SERIALIZER = _SOURCE_CONTRACT.payload["fitted_state_serializer"]
assert isinstance(_SOURCE_SERIALIZER, str)


@register_node
class ApplyScaleNode(Node):
    """Apply a verified scale state from a canonical fitted artifact.

    This is an application-only operation.  It deliberately has no fit method
    and no managed scoring contract, so it cannot re-enter candidate
    validation as a second lifecycle identity.
    """

    metadata = NodeMetadata(
        node_type="preprocess.apply_fitted_scale",
        category="preprocessing",
        label="Apply Reference Scale (Imported)",
        description=(
            "Apply the exact reference-scale state from an imported canonical artifact. "
            "It cannot recompute centering or scaling statistics."
        ),
        parameters=[
            NodeParameter(
                name=field,
                label=field.replace("_", " ").title(),
                param_type="text",
                required=True,
                category="internal",
            )
            for field in sorted(_BINDING_FIELDS)
        ],
        input_types=["SherpaDataset"],
        input_ports=[
            PortMetadata(
                name="default",
                type_ref="spectrasherpa://types/SpectralDataset/1.0",
                required=True,
                label="Input Spectra",
            )
        ],
        output_ports=[
            PortMetadata(
                name="default",
                type_ref="spectrasherpa://types/SpectralDataset/1.0",
                required=True,
                label="Imported-Scale Spectra",
            )
        ],
        output_type="SherpaDataset",
        policy=NodePolicy(),
    )

    def _binding(self) -> dict[str, object]:
        if set(self.parameters) != _BINDING_FIELDS:
            raise ValueError("canonical fitted-scale application parameters are closed")
        return dict(self.parameters)

    async def execute(self, input_data: Any = None, **kwargs: Any) -> NodeResult:
        """Read the exact state and apply it through the source node ABI."""

        del kwargs
        binding = self._binding()
        state = (
            self.require_execution_runtime()
            .require_canonical_artifact_reader()
            .load_bound_state(
                binding,
                expected_source_contract_digest=_SOURCE_CONTRACT_DIGEST,
                expected_serializer=_SOURCE_SERIALIZER,
            )
        )
        # Reuse the source node's public state-application ABI.  It performs
        # no fitting and enforces the source serializer's closed state schema.
        output = ScaleNode(self.node_id, {}).apply_fitted_state(input_data, state)
        return NodeResult(
            outputs={"default": output},
            diagnostics={
                "canonical_artifact": {
                    "artifact_digest": binding["artifact_digest"],
                    "state_node_id": binding["state_node_id"],
                    "state_digest": binding["state_digest"],
                    "state_content_digest": binding["state_content_digest"],
                }
            },
        )


bind_stable_execution_contract(
    ApplyScaleNode,
    runtime_family=RuntimeFamily.SHERPA_NATIVE,
    lifecycle_kind=LifecycleKind.ARTIFACT_APPLICATION,
    implementation_id="spectrasherpa.preprocess.apply_fitted_scale",
    implementation_version="1",
    required_worker_capabilities=(WorkerCapability.READ_CANONICAL_FITTED_ARTIFACT,),
    managed_optimization_eligibility=(ManagedOptimizationEligibility.LOCAL,),
    sample_effect="preserves_samples",
    feature_effect="preserves_features",
    axis_effect="preserves_axis",
    unit_effect="changes_units",
    resource_hints={"timeout_seconds": 30, "cpu_seconds": 30, "memory_bytes": 1_073_741_824},
    license_id="Apache-2.0",
    help_reference="docs/nodes/preprocessing.md",
    implementation_modules=(execution_runtime_contract, scale_node),
    implementation_distributions=("numpy",),
    runtime_requirements=(("numpy", "1.26.4"),),
    fitted_state_serializer=_SOURCE_SERIALIZER,
)


__all__ = ["ApplyScaleNode"]
