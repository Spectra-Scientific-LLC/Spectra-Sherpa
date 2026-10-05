"""Canonical Single-Wavelength Standardization (SWS)."""

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

SWS_STATE_SERIALIZER = "spectrasherpa.transfer.sws-state/1"
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
    "slope",
    "bias",
}


@register_node
class SWSNode(_fitted_state.TransferFittedStateEnvelopeAuthority, Node):
    """Fit one affine secondary-to-primary relation at each wavelength."""

    fitted_state_serializer = SWS_STATE_SERIALIZER

    metadata = NodeMetadata(
        node_type="transfer.sws",
        category="preprocessing",
        label="Single-Wavelength Standardization",
        description=(
            "Fit one slope and intercept per measured wavelength from exactly paired instrument standards. "
            "Use only when both instruments share the same spectral axis; apply the emitted state with "
            "transfer.apply_fitted."
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
                label="Fitted SWS State",
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
        diagnostics=["rmse_transfer", "max_error"],
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
            require_common_axis=True,
        )
        secondary_centered = secondary - np.mean(secondary, axis=0, dtype=np.float64)
        primary_centered = primary - np.mean(primary, axis=0, dtype=np.float64)
        denominator = np.sum(secondary_centered**2, axis=0, dtype=np.float64)
        centered_scale = secondary.shape[0] * np.max(np.abs(secondary_centered), axis=0) ** 2
        unidentified = (centered_scale == 0.0) | (denominator <= np.finfo(np.float64).eps * centered_scale)
        if np.any(unidentified):
            indices = np.flatnonzero(unidentified).tolist()
            raise ValueError(f"SWS cannot identify slope for constant secondary channels: {indices}")
        slope = np.sum(secondary_centered * primary_centered, axis=0, dtype=np.float64) / denominator
        bias = np.mean(primary, axis=0, dtype=np.float64) - slope * np.mean(
            secondary,
            axis=0,
            dtype=np.float64,
        )
        if not np.isfinite(slope).all() or not np.isfinite(bias).all():
            raise ValueError("SWS produced non-finite coefficients")
        return {
            "serializer": SWS_STATE_SERIALIZER,
            "method": "sws",
            **binding,
            "slope": slope.tolist(),
            "bias": bias.tolist(),
        }

    def validate_fitted_state(self, state: object) -> dict[str, object]:
        if not isinstance(state, Mapping) or set(state) != _STATE_FIELDS or state["serializer"] != SWS_STATE_SERIALIZER:
            raise ValueError("SWS state does not use the closed serializer schema")
        common = _core.normalize_common_state(state, method="sws")
        features = int(common["primary_features"])
        if int(common["secondary_features"]) != features or common["primary_axis"] != common["secondary_axis"]:
            raise ValueError("SWS state requires one shared primary/secondary spectral axis")
        slope = _core.finite_vector(state["slope"], name="SWS slope", size=features)
        bias = _core.finite_vector(state["bias"], name="SWS bias", size=features)
        return {
            "serializer": SWS_STATE_SERIALIZER,
            **common,
            "slope": slope.tolist(),
            "bias": bias.tolist(),
        }

    def apply_fitted_state(self, input_data: Any, state: Mapping[str, object]):
        normalized = self.validate_fitted_state(state)
        source, matrix = _core.apply_input(input_data, normalized)
        features = int(normalized["primary_features"])
        slope = _core.finite_vector(normalized["slope"], name="SWS slope", size=features)
        bias = _core.finite_vector(normalized["bias"], name="SWS bias", size=features)
        result = _core.build_primary_output(matrix * slope + bias, source, normalized)
        add_processing_step(
            result,
            "transfer.sws",
            {"state_serializer": SWS_STATE_SERIALIZER},
            self.node_id,
        )
        return result

    def _execute_sync(self, X_primary: Any, X_secondary: Any) -> NodeResult:
        _, _, primary, _, _ = _core.admit_paired_spectra(X_primary, X_secondary, require_common_axis=True)
        state = self.fit_fitted_state(X_primary, X_secondary)
        fitted_secondary = np.asarray(self.apply_fitted_state(X_secondary, state).X, dtype=np.float64)
        diagnostics = _core.transfer_diagnostics(primary, fitted_secondary)
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
            f"{indent}from spectra_sherpa.app.services.dag.nodes.transfer.sws_node import execute_sws",
            f"{indent}results[{self.node_id!r}] = execute_sws(",
            f"{indent}    {inputs.get('X_primary', 'X_primary')},",
            f"{indent}    {inputs.get('X_secondary', 'X_secondary')}, node_id={self.node_id!r},",
            f"{indent}).outputs",
        ]


def execute_sws(X_primary: Any, X_secondary: Any, *, node_id: str) -> NodeResult:
    return SWSNode(node_id, {})._execute_sync(X_primary, X_secondary)


bind_stable_execution_contract(
    SWSNode,
    runtime_family=RuntimeFamily.SHERPA_NATIVE,
    lifecycle_kind=LifecycleKind.FITTED_TRANSFORM,
    implementation_id="spectrasherpa.transfer.sws",
    implementation_version="1.0.1",
    required_worker_capabilities=(WorkerCapability.READ_DATASET,),
    managed_optimization_eligibility=(ManagedOptimizationEligibility.LOCAL,),
    sample_effect="preserves_samples",
    feature_effect="transforms_features",
    axis_effect="preserves_axis",
    unit_effect="requires_compatible_units",
    resource_hints={"timeout_seconds": 30, "cpu_seconds": 30, "memory_bytes": 536_870_912},
    license_id="Apache-2.0",
    help_reference="docs/nodes/preprocessing.md",
    implementation_modules=(_core, _fitted_state, _core.supervision_binding),
    implementation_distributions=("numpy",),
    runtime_requirements=(("numpy", "1.26.4"),),
    citations=(
        "Bouveresse and Massart, Vibrational Spectroscopy 11 (1996) 3-15, doi:10.1016/0924-2031(95)00055-0",
        "Shenk and Westerhaus, Crop Science 31 (1991) 1548-1555, doi:10.2135/cropsci1991.0011183X003100060064x",
    ),
    fitted_state_serializer=SWS_STATE_SERIALIZER,
)


__all__ = ["SWSNode", "SWS_STATE_SERIALIZER", "execute_sws"]
