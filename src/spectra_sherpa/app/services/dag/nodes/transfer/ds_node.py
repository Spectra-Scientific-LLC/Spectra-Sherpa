"""Canonical Direct Standardization (DS)."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import numpy as np

from spectra_sherpa.app.services.dag.meta_helpers import add_processing_step
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

from . import _core, _fitted_state

DS_STATE_SERIALIZER = "spectrasherpa.transfer.ds-state/1"
_STATE_FIELDS = {
    "serializer",
    "method",
    "reference_samples",
    "primary_features",
    "secondary_features",
    "paired_sample_identity_sha256",
    "primary_axis",
    "secondary_axis",
    "primary_signal_units",
    "secondary_signal_units",
    "transfer_matrix",
    "matrix_rank",
}


@register_node
class DSNode(_fitted_state.TransferFittedStateEnvelopeAuthority, Node):
    """Fit the published global Moore-Penrose secondary-to-primary map."""

    fitted_state_serializer = DS_STATE_SERIALIZER

    metadata = NodeMetadata(
        node_type="transfer.ds",
        category="preprocessing",
        label="Direct Standardization",
        description=(
            "Fit the global least-squares map X_primary = X_secondary @ F from exactly paired standards. "
            "The admitted Moore-Penrose solution has no hidden ridge or intercept branch; apply the emitted "
            "state with transfer.apply_fitted."
        ),
        parameters=[],
        input_ports=[
            PortMetadata(
                name="X_primary",
                type_ref="spectrasherpa://types/SpectralDataset/1.0",
                required=True,
                label="Primary Transfer Standards",
                accepted_data_roles=["X_spectra"],
            ),
            PortMetadata(
                name="X_secondary",
                type_ref="spectrasherpa://types/SpectralDataset/1.0",
                required=True,
                label="Secondary Transfer Standards",
                accepted_data_roles=["X_spectra"],
            ),
        ],
        output_ports=[
            PortMetadata(
                name="X_standardized",
                type_ref="spectrasherpa://types/SpectralDataset/1.0",
                required=True,
                label="Primary-Space Spectra",
                accepted_data_roles=["X_spectra"],
            ),
            PortMetadata(
                name="fitted_state",
                type_ref="spectrasherpa://types/SpectralTransferModel/1.0",
                required=True,
                label="Fitted DS State",
            ),
            PortMetadata(
                name="transfer_error",
                type_ref="spectrasherpa://types/ValidationResult/1.0",
                required=True,
                label="Paired-Standard Diagnostics",
            ),
        ],
        input_types=["SherpaDataset"],
        output_type="dict",
        diagnostics=["rmse_transfer", "max_error", "matrix_rank"],
        policy=NodePolicy(
            safe_for_auto_apply=False,
            requires_human_review=True,
            data_egress_risk="none",
            offload_to_pool=True,
            required_worker_capabilities=[],
        ),
    )

    def fit_fitted_state(self, X_primary: Any, X_secondary: Any) -> dict[str, object]:
        _, _, primary, secondary, binding = _core.admit_paired_spectra(
            X_primary,
            X_secondary,
            require_common_axis=False,
        )
        rank = int(np.linalg.matrix_rank(secondary))
        if rank < 1:
            raise ValueError("DS requires a non-zero secondary transfer-standard matrix")
        transfer_matrix = np.linalg.pinv(secondary) @ primary
        if not np.isfinite(transfer_matrix).all():
            raise ValueError("DS produced a non-finite transfer matrix")
        return {
            "serializer": DS_STATE_SERIALIZER,
            "method": "ds",
            **binding,
            "transfer_matrix": transfer_matrix.tolist(),
            "matrix_rank": rank,
        }

    def validate_fitted_state(self, state: object) -> dict[str, object]:
        if not isinstance(state, Mapping) or set(state) != _STATE_FIELDS or state["serializer"] != DS_STATE_SERIALIZER:
            raise ValueError("DS state does not use the closed serializer schema")
        common = _core.normalize_common_state(state, method="ds")
        secondary_features = int(common["secondary_features"])
        primary_features = int(common["primary_features"])
        transfer_matrix = _core.finite_matrix(
            state["transfer_matrix"],
            name="DS transfer_matrix",
            rows=secondary_features,
            columns=primary_features,
        )
        rank = _core.positive_int(state["matrix_rank"], name="matrix_rank")
        if rank > min(int(common["reference_samples"]), secondary_features):
            raise ValueError("DS state declares an impossible transfer-standard rank")
        return {
            "serializer": DS_STATE_SERIALIZER,
            **common,
            "transfer_matrix": transfer_matrix.tolist(),
            "matrix_rank": rank,
        }

    def apply_fitted_state(self, input_data: Any, state: Mapping[str, object]):
        normalized = self.validate_fitted_state(state)
        source, matrix = _core.apply_input(input_data, normalized)
        transform = np.asarray(normalized["transfer_matrix"], dtype=np.float64)
        result = _core.build_primary_output(matrix @ transform, source, normalized)
        add_processing_step(
            result,
            "transfer.ds",
            {"state_serializer": DS_STATE_SERIALIZER, "matrix_rank": normalized["matrix_rank"]},
            self.node_id,
        )
        return result

    def _execute_sync(self, X_primary: Any, X_secondary: Any) -> NodeResult:
        _, _, primary, _, _ = _core.admit_paired_spectra(X_primary, X_secondary, require_common_axis=False)
        state = self.fit_fitted_state(X_primary, X_secondary)
        fitted_secondary = np.asarray(self.apply_fitted_state(X_secondary, state).X, dtype=np.float64)
        diagnostics = _core.transfer_diagnostics(primary, fitted_secondary)
        diagnostics["matrix_rank"] = state["matrix_rank"]
        return NodeResult(
            outputs={
                "X_standardized": self.apply_fitted_state(X_secondary, state),
                "fitted_state": self.make_fitted_state_envelope(state),
                "transfer_error": diagnostics,
            },
            diagnostics=dict(diagnostics),
        )

    async def execute(self, X_primary: Any = None, X_secondary: Any = None, **kwargs: Any) -> NodeResult:
        del kwargs
        return self._execute_sync(X_primary, X_secondary)

    def generate_python(self, inputs: dict[str, str], indent: str = "    ", use_scp: bool = True) -> list[str]:
        del use_scp
        return [
            f"{indent}from spectra_sherpa.app.services.dag.nodes.transfer.ds_node import execute_ds",
            f"{indent}results[{self.node_id!r}] = execute_ds(",
            f"{indent}    {inputs.get('X_primary', 'X_primary')},",
            f"{indent}    {inputs.get('X_secondary', 'X_secondary')}, node_id={self.node_id!r},",
            f"{indent}).outputs",
        ]


def execute_ds(X_primary: Any, X_secondary: Any, *, node_id: str) -> NodeResult:
    return DSNode(node_id, {})._execute_sync(X_primary, X_secondary)


bind_stable_execution_contract(
    DSNode,
    runtime_family=RuntimeFamily.SHERPA_NATIVE,
    lifecycle_kind=LifecycleKind.FITTED_TRANSFORM,
    implementation_id="spectrasherpa.transfer.ds",
    implementation_version="1.0.1",
    required_worker_capabilities=(WorkerCapability.READ_DATASET,),
    managed_optimization_eligibility=(ManagedOptimizationEligibility.LOCAL,),
    sample_effect="preserves_samples",
    feature_effect="transforms_features",
    axis_effect="changes_axis",
    unit_effect="requires_compatible_units",
    resource_hints={"timeout_seconds": 30, "cpu_seconds": 30, "memory_bytes": 1_073_741_824},
    license_id="Apache-2.0",
    help_reference="docs/nodes/preprocessing.md",
    implementation_modules=(_core, _fitted_state, _core.supervision_binding),
    implementation_distributions=("numpy",),
    runtime_requirements=(("numpy", "1.26.4"),),
    citations=("Wang, Veltkamp, and Kowalski, Analytical Chemistry 63 (1991) 2750-2756, doi:10.1021/ac00023a016",),
    fitted_state_serializer=DS_STATE_SERIALIZER,
)


__all__ = ["DSNode", "DS_STATE_SERIALIZER", "execute_ds"]
