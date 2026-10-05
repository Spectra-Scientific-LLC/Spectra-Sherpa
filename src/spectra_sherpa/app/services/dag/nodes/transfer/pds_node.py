"""Canonical Piecewise Direct Standardization (PDS)."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import numpy as np

from spectra_sherpa.app.services.dag.meta_helpers import add_processing_step
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
from spectra_sherpa.execution_contract_vocabulary import (
    LifecycleKind,
    ManagedOptimizationEligibility,
    RuntimeFamily,
    WorkerCapability,
)

from ..modeling import pls_core
from . import _core, _fitted_state

PDS_STATE_SERIALIZER = "spectrasherpa.transfer.pds-state/2"
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
    "half_window",
    "n_components",
    "windows",
}


def _whole_number(value: object, *, name: str, minimum: int) -> int:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not np.isfinite(value)
        or int(value) != value
        or int(value) < minimum
    ):
        raise ValueError(f"{name} must be a whole number >= {minimum}")
    return int(value)


def _canonical_parameters(parameters: dict[str, object]) -> dict[str, object]:
    return {
        "half_window": _whole_number(parameters["half_window"], name="half_window", minimum=0),
        "n_components": _whole_number(parameters["n_components"], name="n_components", minimum=1),
    }


def _window_bounds(index: int, features: int, half_window: int) -> tuple[int, int]:
    return max(0, index - half_window), min(features, index + half_window + 1)


def _fit_local_pls(
    X_window: np.ndarray,
    y_primary: np.ndarray,
    *,
    n_components: int,
) -> tuple[np.ndarray, float]:
    """Return one public-predict affine map for the published local PLS step."""

    model = pls_core.fit_simpls_exact(
        X_window,
        y_primary,
        n_components=n_components,
        scale=False,
    )
    coefficients = np.asarray(model.coefficients, dtype=np.float64).reshape(-1)
    intercept = float(model.prediction_offset[0] - model.x_offset @ coefficients)
    if not np.isfinite(coefficients).all() or not np.isfinite(intercept):
        raise ValueError("PDS local PLS produced non-finite coefficients")
    return coefficients, intercept


@register_node
class PDSNode(_fitted_state.TransferFittedStateEnvelopeAuthority, Node):
    """Fit local PLS maps on paired standards and emit a reusable state."""

    fitted_state_serializer = PDS_STATE_SERIALIZER

    metadata = NodeMetadata(
        node_type="transfer.pds",
        category="preprocessing",
        label="Piecewise Direct Standardization",
        description=(
            "Fit one local PLS relation per primary wavelength from explicitly paired primary/secondary "
            "transfer standards. The fitted state can be applied to new spectra by transfer.apply_fitted."
        ),
        parameters=[
            NodeParameter(
                name="half_window",
                label="Half Window",
                param_type="number",
                default=3,
                min_value=0,
                step=1,
                required=True,
                description="Secondary channels on either side of each primary wavelength.",
            ),
            NodeParameter(
                name="n_components",
                label="Local PLS Components",
                param_type="number",
                default=2,
                min_value=1,
                step=1,
                required=True,
                description="Exact local PLS rank; unsupported ranks are rejected rather than truncated.",
            ),
        ],
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
                label="Fitted PDS State",
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
        diagnostics=["rmse_transfer", "max_error", "half_window", "n_components"],
        policy=NodePolicy(
            safe_for_auto_apply=False,
            requires_human_review=True,
            data_egress_risk="none",
            offload_to_pool=True,
            required_worker_capabilities=[],
        ),
        canonical_parameter_validator=_canonical_parameters,
    )

    def fit_fitted_state(self, X_primary: Any, X_secondary: Any) -> dict[str, object]:
        _, _, primary, secondary, binding = _core.admit_paired_spectra(
            X_primary,
            X_secondary,
            require_common_axis=True,
        )
        params = self._resolve_params()
        half_window = int(params["half_window"])
        n_components = int(params["n_components"])
        local_windows = [_window_bounds(index, secondary.shape[1], half_window) for index in range(primary.shape[1])]
        maximum_rank = min(
            int(np.linalg.matrix_rank(secondary[:, lo:hi] - np.mean(secondary[:, lo:hi], axis=0, dtype=np.float64)))
            for lo, hi in local_windows
        )
        if n_components > maximum_rank:
            raise ValueError(
                f"PDS n_components={n_components} exceeds the admitted local rank {maximum_rank}; "
                "choose an explicit supported rank"
            )
        windows: list[dict[str, object]] = []
        for index, (lo, hi) in enumerate(local_windows):
            coefficients, intercept = _fit_local_pls(
                secondary[:, lo:hi],
                primary[:, index],
                n_components=n_components,
            )
            windows.append(
                {
                    "lo": lo,
                    "hi": hi,
                    "coefficients": coefficients.tolist(),
                    "intercept": intercept,
                }
            )
        return {
            "serializer": PDS_STATE_SERIALIZER,
            "method": "pds",
            **binding,
            "half_window": half_window,
            "n_components": n_components,
            "windows": windows,
        }

    def validate_fitted_state(self, state: object) -> dict[str, object]:
        if not isinstance(state, Mapping) or set(state) != _STATE_FIELDS or state["serializer"] != PDS_STATE_SERIALIZER:
            raise ValueError("PDS state does not use the closed serializer schema")
        common = _core.normalize_common_state(state, method="pds")
        half_window = _whole_number(state["half_window"], name="half_window", minimum=0)
        n_components = _whole_number(state["n_components"], name="n_components", minimum=1)
        windows = state["windows"]
        primary_features = int(common["primary_features"])
        secondary_features = int(common["secondary_features"])
        if not isinstance(windows, list) or len(windows) != primary_features:
            raise ValueError("PDS state must contain one local relation per primary feature")
        normalized_windows: list[dict[str, object]] = []
        minimum_window = secondary_features
        for index, window in enumerate(windows):
            if not isinstance(window, Mapping) or set(window) != {"lo", "hi", "coefficients", "intercept"}:
                raise ValueError("PDS state contains an invalid local relation")
            lo = window["lo"]
            hi = window["hi"]
            expected_lo, expected_hi = _window_bounds(index, secondary_features, half_window)
            if lo != expected_lo or hi != expected_hi:
                raise ValueError("PDS state local-window identity does not match its declared half_window")
            width = expected_hi - expected_lo
            minimum_window = min(minimum_window, width)
            coefficients = _core.finite_vector(window["coefficients"], name="PDS coefficients", size=width)
            intercept = window["intercept"]
            if isinstance(intercept, bool) or not isinstance(intercept, (int, float)) or not np.isfinite(intercept):
                raise ValueError("PDS state contains an invalid intercept")
            normalized_windows.append(
                {
                    "lo": expected_lo,
                    "hi": expected_hi,
                    "coefficients": coefficients.tolist(),
                    "intercept": float(intercept),
                }
            )
        maximum_rank = min(int(common["reference_samples"]) - 1, minimum_window)
        if n_components > maximum_rank:
            raise ValueError("PDS state declares a rank unsupported by its transfer standards and local windows")
        return {
            "serializer": PDS_STATE_SERIALIZER,
            **common,
            "half_window": half_window,
            "n_components": n_components,
            "windows": normalized_windows,
        }

    def apply_fitted_state(self, input_data: Any, state: Mapping[str, object]):
        normalized = self.validate_fitted_state(state)
        source, matrix = _core.apply_input(input_data, normalized)
        output = np.empty((matrix.shape[0], int(normalized["primary_features"])), dtype=np.float64)
        for index, window in enumerate(normalized["windows"]):
            assert isinstance(window, Mapping)
            lo = int(window["lo"])
            hi = int(window["hi"])
            coefficients = np.asarray(window["coefficients"], dtype=np.float64)
            output[:, index] = matrix[:, lo:hi] @ coefficients + float(window["intercept"])
        result = _core.build_primary_output(output, source, normalized)
        add_processing_step(
            result,
            "transfer.pds",
            {
                "half_window": normalized["half_window"],
                "n_components": normalized["n_components"],
                "state_serializer": PDS_STATE_SERIALIZER,
            },
            self.node_id,
        )
        return result

    def _execute_sync(self, X_primary: Any, X_secondary: Any) -> NodeResult:
        _, _, primary_matrix, _, _ = _core.admit_paired_spectra(
            X_primary,
            X_secondary,
            require_common_axis=True,
        )
        state = self.fit_fitted_state(X_primary, X_secondary)
        fitted_secondary = np.asarray(self.apply_fitted_state(X_secondary, state).X, dtype=np.float64)
        diagnostics = _core.transfer_diagnostics(primary_matrix, fitted_secondary)
        diagnostics.update({"half_window": state["half_window"], "n_components": state["n_components"]})
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
            f"{indent}from spectra_sherpa.app.services.dag.nodes.transfer.pds_node import execute_pds",
            f"{indent}results[{self.node_id!r}] = execute_pds(",
            f"{indent}    {inputs.get('X_primary', 'X_primary')},",
            f"{indent}    {inputs.get('X_secondary', 'X_secondary')},",
            f"{indent}    node_id={self.node_id!r}, parameters={self._resolve_params()!r},",
            f"{indent}).outputs",
        ]


def execute_pds(
    X_primary: Any,
    X_secondary: Any,
    *,
    node_id: str,
    parameters: dict[str, object],
) -> NodeResult:
    return PDSNode(node_id, parameters)._execute_sync(X_primary, X_secondary)


bind_stable_execution_contract(
    PDSNode,
    runtime_family=RuntimeFamily.SHERPA_NATIVE,
    lifecycle_kind=LifecycleKind.FITTED_TRANSFORM,
    implementation_id="spectrasherpa.transfer.pds",
    implementation_version="1.1.1",
    required_worker_capabilities=(WorkerCapability.READ_DATASET,),
    managed_optimization_eligibility=(ManagedOptimizationEligibility.LOCAL,),
    sample_effect="preserves_samples",
    feature_effect="transforms_features",
    axis_effect="changes_axis",
    unit_effect="requires_compatible_units",
    resource_hints={"timeout_seconds": 60, "cpu_seconds": 60, "memory_bytes": 1_073_741_824},
    license_id="Apache-2.0",
    help_reference="docs/nodes/preprocessing.md",
    implementation_modules=(_core, _fitted_state, pls_core, _core.supervision_binding),
    implementation_distributions=("numpy",),
    runtime_requirements=(("numpy", "1.26.4"),),
    citations=(
        "Wang, Veltkamp, and Kowalski, Analytical Chemistry 63 (1991) 2750-2756, doi:10.1021/ac00023a016",
        "Bouveresse and Massart, Chemometrics and Intelligent Laboratory Systems "
        "32 (1996) 201-213, doi:10.1016/0169-7439(95)00074-7",
        pls_core.CITATION,
    ),
    fitted_state_serializer=PDS_STATE_SERIALIZER,
)


__all__ = ["PDSNode", "PDS_STATE_SERIALIZER", "execute_pds"]
