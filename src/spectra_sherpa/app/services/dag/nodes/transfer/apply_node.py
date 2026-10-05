"""Apply one locally fitted canonical spectral-transfer state."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from spectra_sherpa.app.services.dag.node_base import (
    Node,
    NodeMetadata,
    NodePolicy,
    NodeResult,
    PortMetadata,
    register_node,
)
from spectra_sherpa.app.services.dag.stable_execution_contract import bind_stable_execution_contract
from spectra_sherpa.execution_contract_vocabulary import (
    LifecycleKind,
    ManagedOptimizationEligibility,
    RuntimeFamily,
    WorkerCapability,
)

from . import _core, ds_node, pds_node, sws_node

SPECTRAL_TRANSFER_ENVELOPE_SERIALIZER = "spectrasherpa.model-artifact.spectral-transfer-envelope/1"
_PRODUCERS = {
    "transfer.ds": ds_node.DSNode,
    "transfer.pds": pds_node.PDSNode,
    "transfer.sws": sws_node.SWSNode,
}


def _producer(value: object):
    if not isinstance(value, Mapping):
        raise ValueError("spectral transfer application requires a fitted-state envelope")
    operation_id = value.get("source_operation_id")
    producer_class = _PRODUCERS.get(operation_id)
    if producer_class is None:
        raise ValueError(f"unsupported spectral transfer producer: {operation_id!r}")
    return producer_class


@register_node
class ApplySpectralTransferNode(Node):
    """Apply a verified PDS, DS, or SWS state without fitting standards."""

    metadata = NodeMetadata(
        node_type="transfer.apply_fitted",
        category="preprocessing",
        label="Apply Fitted Spectral Transfer",
        description=(
            "Apply an upstream digest-bound PDS, DS, or SWS state to secondary-instrument spectra. "
            "This operation cannot fit or modify a transfer relation."
        ),
        parameters=[],
        input_ports=[
            PortMetadata(
                name="default",
                type_ref="spectrasherpa://types/SpectralDataset/1.0",
                required=True,
                label="Secondary Spectra",
                accepted_data_roles=["X_spectra"],
            ),
            PortMetadata(
                name="fitted_state",
                type_ref="spectrasherpa://types/SpectralTransferModel/1.0",
                required=True,
                label="Fitted Spectral Transfer",
            ),
        ],
        output_ports=[
            PortMetadata(
                name="default",
                type_ref="spectrasherpa://types/SpectralDataset/1.0",
                required=True,
                label="Primary-Space Spectra",
                accepted_data_roles=["X_spectra"],
            )
        ],
        input_types=["SherpaDataset"],
        output_type="SherpaDataset",
        policy=NodePolicy(
            safe_for_auto_apply=False,
            requires_human_review=True,
            data_egress_risk="none",
            offload_to_pool=True,
            required_worker_capabilities=[],
        ),
    )

    def _execute_sync(self, input_data: Any, fitted_state: Mapping[str, object]) -> NodeResult:
        producer_class = _producer(fitted_state)
        producer = producer_class(f"{self.node_id}:source", {})
        state = producer.verify_fitted_state_envelope(fitted_state)
        output = producer.apply_fitted_state(input_data, state)
        return NodeResult(
            outputs={"default": output},
            diagnostics={
                "source_operation_id": fitted_state["source_operation_id"],
                "state_content_digest": fitted_state["state_content_digest"],
            },
        )

    async def execute(
        self,
        default: Any = None,
        input_data: Any = None,
        fitted_state: Mapping[str, object] | None = None,
        **kwargs: Any,
    ) -> NodeResult:
        del kwargs
        if fitted_state is None:
            raise ValueError("spectral transfer application requires fitted_state")
        return self._execute_sync(input_data if input_data is not None else default, fitted_state)

    def generate_python(self, inputs: dict[str, str], indent: str = "    ", use_scp: bool = True) -> list[str]:
        del use_scp
        input_expression = inputs.get("default", next(iter(inputs.values()), "input_data"))
        return [
            f"{indent}from spectra_sherpa.app.services.dag.nodes.transfer.apply_node import apply_spectral_transfer",
            f"{indent}results[{self.node_id!r}] = apply_spectral_transfer(",
            f"{indent}    {input_expression}, {inputs.get('fitted_state', 'fitted_state')},",
            f"{indent}    node_id={self.node_id!r},",
            f"{indent}).outputs",
        ]


def apply_spectral_transfer(
    input_data: Any,
    fitted_state: Mapping[str, object],
    *,
    node_id: str,
) -> NodeResult:
    return ApplySpectralTransferNode(node_id, {})._execute_sync(input_data, fitted_state)


bind_stable_execution_contract(
    ApplySpectralTransferNode,
    runtime_family=RuntimeFamily.SHERPA_NATIVE,
    lifecycle_kind=LifecycleKind.ARTIFACT_APPLICATION,
    implementation_id="spectrasherpa.transfer.apply_fitted",
    implementation_version="1.0.0",
    required_worker_capabilities=(WorkerCapability.READ_DATASET,),
    managed_optimization_eligibility=(ManagedOptimizationEligibility.LOCAL,),
    sample_effect="preserves_samples",
    feature_effect="transforms_features",
    axis_effect="changes_axis",
    unit_effect="requires_compatible_units",
    resource_hints={"timeout_seconds": 30, "cpu_seconds": 30, "memory_bytes": 1_073_741_824},
    license_id="Apache-2.0",
    help_reference="docs/nodes/preprocessing.md",
    implementation_modules=(_core, ds_node, pds_node, sws_node),
    # The application equations use only NumPy, but producer dispatch imports
    # the PDS module so its closed state schema can be verified. Declare the
    # actual import-time dependency instead of presenting a narrower runtime
    # than the executable boundary has.
    implementation_distributions=("numpy", "scikit-learn"),
    runtime_requirements=(("numpy", "1.26.4"), ("scikit-learn", "1.9.0")),
    fitted_state_serializer=SPECTRAL_TRANSFER_ENVELOPE_SERIALIZER,
)


__all__ = ["ApplySpectralTransferNode", "apply_spectral_transfer"]
