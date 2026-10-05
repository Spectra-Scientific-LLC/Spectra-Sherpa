"""Apply canonical fitted preprocessing states from imported artifact custody.

Each registered operation is bound to exactly one producer contract and one
state serializer.  The small shared base owns only artifact-custody mechanics;
the source node remains the sole numerical application authority.
"""

from __future__ import annotations

from typing import Any, ClassVar

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

from . import emsc_node, msc_node, osc_node
from .emsc_node import EMSCNode
from .msc_node import MSCNode
from .osc_node import OSCNode

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


def _binding_parameters() -> list[NodeParameter]:
    return [
        NodeParameter(
            name=field,
            label=field.replace("_", " ").title(),
            param_type="text",
            required=True,
            category="internal",
        )
        for field in sorted(_BINDING_FIELDS)
    ]


def _input_ports() -> list[PortMetadata]:
    return [
        PortMetadata(
            name="default",
            type_ref="spectrasherpa://types/SpectralDataset/1.0",
            required=True,
            label="Application Spectra",
            accepted_data_roles=["X_spectra"],
        )
    ]


def _output_ports(label: str) -> list[PortMetadata]:
    return [
        PortMetadata(
            name="default",
            type_ref="spectrasherpa://types/SpectralDataset/1.0",
            required=True,
            label=label,
            accepted_data_roles=["X_spectra"],
        )
    ]


class _ApplyFittedPreprocessingNode(Node):
    """Shared custody adapter for one exactly bound fitted transform."""

    source_node_class: ClassVar[type[Node]]
    source_contract_digest: ClassVar[str]
    source_serializer: ClassVar[str]

    def _binding(self) -> dict[str, object]:
        if set(self.parameters) != _BINDING_FIELDS:
            raise ValueError("canonical fitted-preprocessing application parameters are closed")
        return dict(self.parameters)

    async def execute(self, input_data: Any = None, **kwargs: Any) -> NodeResult:
        del kwargs
        binding = self._binding()
        state = (
            self.require_execution_runtime()
            .require_canonical_artifact_reader()
            .load_bound_state(
                binding,
                expected_source_contract_digest=self.source_contract_digest,
                expected_serializer=self.source_serializer,
            )
        )
        source_node = self.source_node_class(self.node_id, {})
        output = source_node.apply_fitted_state(input_data, state)  # type: ignore[attr-defined]
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


def _source_identity(node_class: type[Node]) -> tuple[str, str]:
    contract = node_class.metadata.resolved_execution_contract() if node_class.metadata is not None else None
    assert contract is not None
    serializer = contract.payload["fitted_state_serializer"]
    assert isinstance(serializer, str)
    return contract.digest, serializer


_MSC_CONTRACT_DIGEST, _MSC_SERIALIZER = _source_identity(MSCNode)
_EMSC_CONTRACT_DIGEST, _EMSC_SERIALIZER = _source_identity(EMSCNode)
_OSC_CONTRACT_DIGEST, _OSC_SERIALIZER = _source_identity(OSCNode)


@register_node
class ApplyFittedMSCNode(_ApplyFittedPreprocessingNode):
    """Apply one imported MSC reference without refitting it."""

    source_node_class = MSCNode
    source_contract_digest = _MSC_CONTRACT_DIGEST
    source_serializer = _MSC_SERIALIZER
    metadata = NodeMetadata(
        node_type="preprocess.apply_fitted_msc",
        category="preprocessing",
        label="Apply Reference MSC (Imported)",
        description="Apply the exact MSC reference state from an imported canonical artifact without refitting.",
        parameters=_binding_parameters(),
        input_types=["SherpaDataset"],
        input_ports=_input_ports(),
        output_ports=_output_ports("Imported-MSC Spectra"),
        output_type="SherpaDataset",
        policy=NodePolicy(),
    )


@register_node
class ApplyFittedEMSCNode(_ApplyFittedPreprocessingNode):
    """Apply one imported EMSC reference and nuisance basis without refitting."""

    source_node_class = EMSCNode
    source_contract_digest = _EMSC_CONTRACT_DIGEST
    source_serializer = _EMSC_SERIALIZER
    metadata = NodeMetadata(
        node_type="preprocess.apply_fitted_emsc",
        category="preprocessing",
        label="Apply Reference EMSC (Imported)",
        description="Apply the exact EMSC fitted state from an imported canonical artifact without refitting.",
        parameters=_binding_parameters(),
        input_types=["SherpaDataset"],
        input_ports=_input_ports(),
        output_ports=_output_ports("Imported-EMSC Spectra"),
        output_type="SherpaDataset",
        policy=NodePolicy(),
    )


@register_node
class ApplyFittedOSCNode(_ApplyFittedPreprocessingNode):
    """Apply one imported target-orthogonal projection without target access."""

    source_node_class = OSCNode
    source_contract_digest = _OSC_CONTRACT_DIGEST
    source_serializer = _OSC_SERIALIZER
    metadata = NodeMetadata(
        node_type="preprocess.apply_fitted_osc",
        category="preprocessing",
        label="Apply Reference OSC (Imported)",
        description="Apply the exact OSC projection from an imported canonical artifact without targets or refitting.",
        parameters=_binding_parameters(),
        input_types=["SherpaDataset"],
        input_ports=_input_ports(),
        output_ports=_output_ports("Imported-OSC Spectra"),
        output_type="SherpaDataset",
        policy=NodePolicy(),
    )


def _bind_application_contract(
    node_class: type[Node],
    *,
    implementation_id: str,
    source_module,
    serializer: str,
    unit_effect: str,
) -> None:
    bind_stable_execution_contract(
        node_class,
        runtime_family=RuntimeFamily.SHERPA_NATIVE,
        lifecycle_kind=LifecycleKind.ARTIFACT_APPLICATION,
        implementation_id=implementation_id,
        implementation_version="1",
        required_worker_capabilities=(WorkerCapability.READ_CANONICAL_FITTED_ARTIFACT,),
        managed_optimization_eligibility=(ManagedOptimizationEligibility.LOCAL,),
        sample_effect="preserves_samples",
        feature_effect="preserves_features",
        axis_effect="preserves_axis",
        unit_effect=unit_effect,
        resource_hints={"timeout_seconds": 30, "cpu_seconds": 30, "memory_bytes": 1_073_741_824},
        license_id="Apache-2.0",
        help_reference="docs/nodes/preprocessing.md",
        implementation_modules=(execution_runtime_contract, source_module),
        implementation_distributions=("numpy",),
        runtime_requirements=(("numpy", "1.26.4"),),
        fitted_state_serializer=serializer,
    )


_bind_application_contract(
    ApplyFittedMSCNode,
    implementation_id="spectrasherpa.preprocess.apply_fitted_msc",
    source_module=msc_node,
    serializer=_MSC_SERIALIZER,
    unit_effect="changes_units",
)
_bind_application_contract(
    ApplyFittedEMSCNode,
    implementation_id="spectrasherpa.preprocess.apply_fitted_emsc",
    source_module=emsc_node,
    serializer=_EMSC_SERIALIZER,
    unit_effect="preserves_units",
)
_bind_application_contract(
    ApplyFittedOSCNode,
    implementation_id="spectrasherpa.preprocess.apply_fitted_osc",
    source_module=osc_node,
    serializer=_OSC_SERIALIZER,
    unit_effect="preserves_units",
)


__all__ = ["ApplyFittedEMSCNode", "ApplyFittedMSCNode", "ApplyFittedOSCNode"]
