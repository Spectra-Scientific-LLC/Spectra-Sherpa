"""Apply one canonical fitted PLS state from local or imported custody."""

from __future__ import annotations

import hashlib
from typing import Any, Mapping, cast

import numpy as np

from spectra_sherpa.app.services.dag.io_contracts import coerce_to_sherpa
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
from spectra_sherpa.core.node_identity import node_contract_digest_is_compatible
from spectra_sherpa.execution_contract_vocabulary import (
    LifecycleKind,
    ManagedOptimizationEligibility,
    RuntimeFamily,
    WorkerCapability,
)
from spectra_sherpa.sdk import prediction_uncertainty

from . import fitted_pls_node, pls_applicability
from .fitted_pls_node import (
    FittedPLSV2Node,
    make_fitted_pls_state_envelope,
    verify_fitted_pls_state_envelope,
)

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
_SOURCE_CONTRACT = FittedPLSV2Node.metadata.resolved_execution_contract()
assert _SOURCE_CONTRACT is not None  # The source node owns a required execution contract.
_SOURCE_CONTRACT_DIGEST = _SOURCE_CONTRACT.digest
_SOURCE_SERIALIZER = _SOURCE_CONTRACT.payload["fitted_state_serializer"]
assert isinstance(_SOURCE_SERIALIZER, str)


def _canonical_application_parameters(parameters: dict[str, object]) -> dict[str, object]:
    """Admit either no artifact binding or one complete closed binding."""

    present = frozenset(name for name, value in parameters.items() if value is not None)
    if present not in {frozenset(), _BINDING_FIELDS}:
        raise ValueError("canonical fitted-PLS artifact binding must be either absent or complete")
    return parameters


@register_node
class ApplyFittedPLSV2Node(Node):
    """Apply verified PLS-v2 state through one numerical implementation."""

    metadata = NodeMetadata(
        node_type="model.apply_fitted_pls",
        category="modeling",
        label="Apply Sherpa PLS Regression",
        description=(
            "Apply exact PLS-v2 state supplied by the local fitted-state edge or by an imported canonical "
            "artifact binding. Both custody paths converge before numerical application."
        ),
        parameters=[
            NodeParameter(
                name=field,
                label=field.replace("_", " ").title(),
                param_type="text",
                default=None,
                required=False,
                category="internal",
                description="Canonical artifact-custody binding populated by import; not a scientist-set parameter.",
            )
            for field in sorted(_BINDING_FIELDS)
        ],
        input_types=["SherpaDataset"],
        input_ports=[
            PortMetadata(
                name="default",
                type_ref="spectrasherpa://types/SpectralDataset/1.0",
                required=True,
                label="Application Spectra",
            ),
            PortMetadata(
                name="fitted_state",
                type_ref="spectrasherpa://types/RegressionModel/1.0",
                required=False,
                label="Local Fitted PLS State",
                description="Typed state emitted by model.fitted_pls; omit for imported-artifact application.",
            ),
        ],
        output_ports=[
            PortMetadata(
                name="default",
                type_ref="spectrasherpa://types/TargetMatrix/1.0",
                required=True,
                label="Predicted Targets",
            ),
            PortMetadata(
                name="prediction_intervals",
                type_ref="spectrasherpa://types/PredictionIntervals/1.0",
                required=True,
                label="Prediction Intervals",
            ),
            PortMetadata(
                name="applicability",
                type_ref="spectrasherpa://types/ApplicabilityScreening/1.0",
                required=True,
                label="Provisional Applicability Screening",
            ),
            PortMetadata(
                name="prediction_identity",
                type_ref="spectrasherpa://types/PredictionIdentity/1.0",
                required=True,
                label="Prediction Identity",
            ),
        ],
        output_type="array",
        policy=NodePolicy(),
        canonical_parameter_validator=_canonical_application_parameters,
    )

    def _binding(self) -> dict[str, object] | None:
        present = {name for name, value in self.parameters.items() if value is not None}
        if not present:
            return None
        if present != _BINDING_FIELDS:
            raise ValueError("canonical fitted-PLS artifact binding must be complete")
        return {name: self.parameters[name] for name in sorted(_BINDING_FIELDS)}

    def requires_worker_capability_at_runtime(self, capability: str) -> bool:
        """Narrow artifact authority when a verified local state edge is used."""

        if capability == WorkerCapability.READ_CANONICAL_FITTED_ARTIFACT.value:
            return self._binding() is not None
        return super().requires_worker_capability_at_runtime(capability)

    def _execute_sync(
        self,
        input_data: Any = None,
        fitted_state: Mapping[str, object] | None = None,
    ) -> NodeResult:
        """Verify one custody mode and apply through the source node ABI."""

        binding = self._binding()
        if (binding is None) == (fitted_state is None):
            raise ValueError("fitted PLS application requires exactly one local-state or artifact-binding source")
        custody: dict[str, object]
        if binding is None:
            assert fitted_state is not None
            state = verify_fitted_pls_state_envelope(fitted_state)
            custody = {"mode": "local_fitted_state", "state_content_digest": fitted_state["state_content_digest"]}
        else:
            binding_source_digest = binding["source_contract_digest"]
            if not node_contract_digest_is_compatible(
                "model.fitted_pls",
                binding_source_digest,
                _SOURCE_CONTRACT_DIGEST,
            ):
                raise ValueError("canonical fitted-PLS artifact producer contract is not compatible")
            assert isinstance(binding_source_digest, str)
            loaded = (
                self.require_execution_runtime()
                .require_canonical_artifact_reader()
                .load_bound_state(
                    binding,
                    expected_source_contract_digest=binding_source_digest,
                    expected_serializer=_SOURCE_SERIALIZER,
                )
            )
            # Imported and local custody converge on the same verified envelope
            # before the sole numerical application implementation is called.
            state = verify_fitted_pls_state_envelope(make_fitted_pls_state_envelope(loaded))
            custody = {
                "mode": "canonical_artifact",
                "artifact_digest": binding["artifact_digest"],
                "state_node_id": binding["state_node_id"],
                "state_digest": binding["state_digest"],
                "state_content_digest": binding["state_content_digest"],
            }
        predictions = FittedPLSV2Node(self.node_id, {}).apply_fitted_state(input_data, state)
        dataset = coerce_to_sherpa(input_data, input_name="input_data")
        axis = dataset.sample_axis
        receipt = {
            "schema_version": "spectrasherpa.prediction-identity/1",
            "output_port": "default",
            "shape": list(predictions.shape),
            "response_identity": state["response_identity"],
            "sample_labels": list(axis.labels) if axis is not None and axis.labels is not None else None,
            "sample_values": axis.values.tolist() if axis is not None and axis.values is not None else None,
            "fitted_state_custody": custody,
            "prediction_sha256": hashlib.sha256(np.asarray(predictions, dtype="<f8").tobytes(order="C")).hexdigest(),
            "prediction_digest_encoding": "row-major little-endian float64",
        }
        input_identity = cast(Mapping[str, Any], state["input_identity"])
        requested_components = cast(int, state["n_components"])
        effective_components = cast(int, state["effective_n_components"])
        screening = pls_applicability.apply_screening(
            np.asarray(dataset.X, dtype=float),
            state["feature_offset"],
            cast(Mapping[str, Any], state["diagnostic_state"]),
        )
        screening.update(
            {
                "prediction_identity": receipt,
                "requested_components": state["n_components"],
                "effective_components": state["effective_n_components"],
                "rank_qualification": (
                    "reduced_effective_rank" if effective_components < requested_components else "requested_rank_fitted"
                ),
                "t2_units": "dimensionless",
                "q_units": (
                    "standardized squared residual"
                    if state["scale"]
                    else (None if input_identity["signal_units"] is None else f"({input_identity['signal_units']})^2")
                ),
            }
        )
        provider = self._execution_runtime.prediction_uncertainty if self._execution_runtime is not None else None
        intervals = (
            {
                "schema_version": "spectrasherpa.prediction-uncertainty/1",
                "status": "point_only",
                "unavailable_reason": "no_selected_pipeline_calibration_record",
                "prediction_identity": receipt,
            }
            if provider is None
            else provider.apply(predictions, receipt, screening)
        )
        return NodeResult(
            outputs={
                "default": predictions,
                "prediction_identity": receipt,
                "applicability": screening,
                "prediction_intervals": intervals,
            },
            diagnostics={
                "fitted_state_custody": custody,
                "response_identity": state["response_identity"],
                **({"canonical_artifact": custody} if binding else {}),
            },
        )

    async def execute(
        self,
        input_data: Any = None,
        fitted_state: Mapping[str, object] | None = None,
        **kwargs: Any,
    ) -> NodeResult:
        del kwargs
        return self._execute_sync(input_data, fitted_state)

    def generate_python(
        self,
        inputs: dict[str, str],
        indent: str = "    ",
        use_scp: bool = True,
    ) -> list[str]:
        """Generate the local-state path through the same application core."""

        del use_scp
        if self._binding() is not None:
            raise ValueError("imported fitted artifacts must be exported through the canonical project package")
        input_expression = inputs.get("default", next(iter(inputs.values()), "input_data"))
        return [
            f"{indent}from spectra_sherpa.app.services.dag.nodes.modeling.apply_fitted_pls_node import "
            "apply_fitted_pls_v2",
            f"{indent}results[{self.node_id!r}] = apply_fitted_pls_v2(",
            f"{indent}    {input_expression}, {inputs.get('fitted_state', 'None')},",
            f"{indent}    node_id={self.node_id!r},",
            f"{indent}).outputs",
        ]

    def exported_output_ports(self) -> set[str]:
        """Declare both numerical output and its portable identity receipt."""

        return {"default", "prediction_identity", "applicability", "prediction_intervals"}


def apply_fitted_pls_v2(
    input_data: Any,
    fitted_state: Mapping[str, object] | None,
    *,
    node_id: str,
) -> NodeResult:
    """Execute the live and generated local application through one core."""

    return ApplyFittedPLSV2Node(node_id, {})._execute_sync(input_data, fitted_state)


bind_stable_execution_contract(
    ApplyFittedPLSV2Node,
    runtime_family=RuntimeFamily.SHERPA_NATIVE,
    lifecycle_kind=LifecycleKind.ARTIFACT_APPLICATION,
    implementation_id="spectrasherpa.model.apply_fitted_pls",
    implementation_version="5",
    required_worker_capabilities=(WorkerCapability.READ_CANONICAL_FITTED_ARTIFACT,),
    managed_optimization_eligibility=(ManagedOptimizationEligibility.LOCAL,),
    sample_effect="preserves_samples",
    feature_effect="generates_features",
    axis_effect="changes_axis",
    unit_effect="changes_units",
    resource_hints={"timeout_seconds": 30, "cpu_seconds": 30, "memory_bytes": 1_073_741_824},
    license_id="BSD-3-Clause",
    help_reference="docs/nodes/regression.md",
    implementation_modules=(execution_runtime_contract, fitted_pls_node, pls_applicability, prediction_uncertainty),
    implementation_distributions=("numpy",),
    runtime_requirements=(("numpy", "1.26.4"),),
    fitted_state_serializer=_SOURCE_SERIALIZER,
    citations=tuple(_SOURCE_CONTRACT.payload["citations"]),
)


__all__ = ["ApplyFittedPLSV2Node", "apply_fitted_pls_v2"]
