"""Canonical sample-local normalization node.

SNV and per-spectrum scaling derive every statistic from the spectrum being
transformed, so they are genuinely stateless.  Cohort-fitted multiplicative
scatter correction lives under ``preprocess.msc``; keeping it out of this
operation prevents a stateless contract from hiding training-row state.
"""

from __future__ import annotations

from typing import Any

import numpy as np

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
    EFFECT_NORMALIZED,
    EFFECT_SCALED,
    EFFECT_SCATTER_CORRECTED,
    Node,
    NodeMetadata,
    NodeParameter,
    NodeResult,
    PortMetadata,
    add_processing_step,
    build_dataset_like,
    coerce_to_sherpa,
    header_line,
    register_node,
    to_numpy_2d,
)


def _snv_transform(data: np.ndarray, *, ddof: int = 0) -> np.ndarray:
    mean_values = np.mean(data, axis=1, keepdims=True)
    std_values = np.std(data, axis=1, keepdims=True, ddof=ddof)
    std_values[(std_values == 0) | ~np.isfinite(std_values)] = 1.0
    return (data - mean_values) / std_values


def _sample_scale_transform(data: np.ndarray, *, method: str) -> np.ndarray:
    if method == "max":
        divisor = np.max(np.abs(data), axis=-1, keepdims=True)
        divisor[divisor == 0] = 1.0
        return data / divisor
    if method == "area":
        divisor = np.sum(np.abs(data), axis=-1, keepdims=True)
        divisor[divisor == 0] = 1.0
        return data / divisor
    if method == "minmax":
        minimum = np.min(data, axis=-1, keepdims=True)
        divisor = np.max(data, axis=-1, keepdims=True) - minimum
        divisor[divisor == 0] = 1.0
        return (data - minimum) / divisor
    raise ValueError("sample-wise scale method is not admitted")


def _normalize_dispatch(
    data: np.ndarray,
    method: str = "snv",
    scale_method: str = "max",
    std_ddof: int = 0,
) -> np.ndarray:
    projected = _canonical_normalize_parameters(
        {
            "method": method,
            "scale_method": scale_method,
            "std_ddof": std_ddof,
        }
    )
    matrix = np.asarray(data, dtype=np.float64)
    if matrix.ndim != 2 or matrix.shape[0] == 0 or matrix.shape[1] == 0:
        raise ValueError("preprocess.normalize requires a non-empty two-dimensional sample-by-feature matrix")
    if not np.isfinite(matrix).all():
        raise ValueError(
            "preprocess.normalize requires finite input values; remove an explicitly blanked region "
            "with preprocess.clip_range before normalization"
        )
    if projected["method"] == "snv":
        return _snv_transform(matrix, ddof=int(projected["std_ddof"]))
    if projected["method"] == "scale":
        return _sample_scale_transform(matrix, method=str(projected["scale_method"]))
    raise AssertionError("closed normalization grammar returned an unknown method")


def _normalize_transform_state(data: np.ndarray, params: dict[str, Any]) -> dict[str, Any]:
    """Return the closed sample-local replay record."""

    del data
    method = str(params["method"])
    if method == "snv":
        return {"method": "snv", "std_ddof": int(params["std_ddof"]), "replay": "sample_local"}
    if method == "scale":
        return {"method": "scale", "scale_method": params["scale_method"], "replay": "sample_local"}
    raise ValueError(f"Unknown normalization method: {method}")


def _canonical_normalize_parameters(parameters: dict[str, object]) -> dict[str, object]:
    """Reject irrelevant settings so one computation has one representation."""

    method = parameters["method"]
    if not isinstance(method, str) or method not in {"snv", "scale"}:
        raise ValueError("normalization method is not admitted")
    std_ddof = parameters["std_ddof"]
    if isinstance(std_ddof, bool) or not isinstance(std_ddof, int) or std_ddof not in {0, 1}:
        raise ValueError("SNV std_ddof must be exactly 0 or 1")
    scale_method = parameters["scale_method"]
    if not isinstance(scale_method, str) or scale_method not in {"max", "area", "minmax"}:
        raise ValueError("sample-wise scale method is not admitted")
    if method == "snv":
        if parameters["scale_method"] != "max":
            raise ValueError("SNV may not carry scale-only settings")
    elif method == "scale":
        if parameters["std_ddof"] != 0:
            raise ValueError("sample-wise scale may not carry SNV-only settings")
    return parameters


def _managed_normalize_parameters(parameters: dict[str, object]) -> dict[str, object]:
    """Admit only the finite sample-local normalization grammar."""

    return _canonical_normalize_parameters(parameters)


@register_node
class NormalizeNode(Node):
    """Apply one closed sample-local normalization operation."""

    metadata = NodeMetadata(
        node_type="preprocess.normalize",
        category="preprocessing",
        label="Normalize",
        description="Normalize each spectrum with SNV or an explicit sample-wise scale.",
        parameters=[
            NodeParameter(
                name="method",
                label="Method",
                param_type="select",
                default="snv",
                options=[
                    {"label": "SNV", "value": "snv"},
                    {"label": "Scale", "value": "scale"},
                ],
                description="Normalization method",
                required=True,
                category="basic",
            ),
            NodeParameter(
                name="std_ddof",
                label="SNV standard-deviation convention",
                param_type="select",
                default=0,
                options=[
                    {"label": "Population (ddof=0)", "value": 0},
                    {"label": "Sample (ddof=1)", "value": 1},
                ],
                description="Standard-deviation convention used by SNV",
                required=False,
                category="advanced",
                visible_when={"method": ["snv"]},
            ),
            NodeParameter(
                name="scale_method",
                label="Scale Method",
                param_type="select",
                default="max",
                options=["max", "area", "minmax"],
                description="Sample-wise scaling method",
                required=False,
                category="basic",
                visible_when={"method": ["scale"]},
            ),
        ],
        input_types=["SherpaDataset"],
        input_ports=[
            PortMetadata(
                name="default",
                type_ref="spectrasherpa://types/SpectralDataset/1.0",
                required=True,
                label="Input Spectra",
                description="Spectral rows to normalize sample-wise while preserving their feature axis.",
                accepted_data_roles=["X_spectra"],
            )
        ],
        output_ports=[
            PortMetadata(
                name="default",
                type_ref="spectrasherpa://types/SpectralDataset/1.0",
                required=True,
                label="Normalized Spectra",
                description="Spectra transformed sample-wise with their feature axis preserved.",
                accepted_data_roles=["X_spectra"],
            )
        ],
        output_type="SherpaDataset",
        policy=NodePolicy(safe_for_auto_apply=True, requires_human_review=False, data_egress_risk="none"),
        canonical_parameter_validator=_canonical_normalize_parameters,
        managed_parameter_validator=_managed_normalize_parameters,
    )

    async def execute(self, input_data: Any = None, **kwargs: Any) -> NodeResult:
        del kwargs
        return self.transform_dataset(input_data)

    def transform_dataset(self, input_data: Any) -> NodeResult:
        """One finalization path for live execution and Python export."""
        input_ds = coerce_to_sherpa(input_data, input_name="input_data")
        params = self._resolve_params()
        data = to_numpy_2d(input_ds, name="input_data", dtype=np.float64)
        normalized = _normalize_dispatch(data, **params)
        result = build_dataset_like(normalized, input_ds)

        method = str(params["method"])
        if method == "snv":
            effects = [EFFECT_NORMALIZED, EFFECT_SCATTER_CORRECTED]
            result.units = "dimensionless"
        else:
            effects = [EFFECT_SCALED]
            result.units = "normalized"

        step_params = dict(params)
        step_params["transform_state"] = _normalize_transform_state(data, step_params)
        add_processing_step(
            result,
            "preprocess.normalize",
            step_params,
            node_id=self.node_id,
            state_effects=effects,
        )

        after = np.asarray(result.data, dtype=np.float64)
        eps = 1e-12
        diagnostics = {
            "method": method,
            "snr_before": float(np.mean(np.abs(data)) / (np.std(data) + eps)),
            "snr_after": float(np.mean(np.abs(after)) / (np.std(after) + eps)),
            "mean_spectrum_shift": float(np.mean(after) - np.mean(data)),
            "max_absolute_change": float(np.max(np.abs(after - data))),
        }
        supervision_binding.rebind_sample_preserving_supervision(input_ds, result)
        return NodeResult(outputs={"default": result}, diagnostics=diagnostics)

    def supports_python_export(self) -> bool:
        return True

    def generate_python(self, inputs, indent="    ", use_scp=True):
        inp = next(iter(inputs.values())) if inputs else "input_data"
        params = self._resolve_params()
        return [
            header_line("Canonical Normalization", self.node_id, indent),
            f"{indent}from spectra_sherpa.app.services.dag.nodes.preprocessing.normalize_node " "import NormalizeNode",
            f"{indent}_transform = NormalizeNode({self.node_id!r}, {params!r})",
            f"{indent}results[{self.node_id!r}] = _transform.transform_dataset({inp}).outputs['default']",
        ]


bind_stable_execution_contract(
    NormalizeNode,
    runtime_family=RuntimeFamily.SHERPA_NATIVE,
    lifecycle_kind=LifecycleKind.STATELESS_TRANSFORM,
    implementation_id="spectrasherpa.preprocess.normalize",
    implementation_version="1.0.1",
    required_worker_capabilities=(WorkerCapability.READ_DATASET,),
    managed_optimization_eligibility=(
        ManagedOptimizationEligibility.LOCAL,
        ManagedOptimizationEligibility.DEVELOPMENT,
        ManagedOptimizationEligibility.FULL_REFIT,
    ),
    sample_effect="preserves_samples",
    feature_effect="preserves_features",
    axis_effect="preserves_axis",
    unit_effect="changes_units",
    resource_hints={"timeout_seconds": 30, "cpu_seconds": 30, "memory_bytes": 1_073_741_824},
    license_id="Apache-2.0",
    help_reference="docs/nodes/preprocessing.md",
    implementation_modules=(_shared, supervision_binding),
    implementation_distributions=("numpy",),
    runtime_requirements=(("numpy", "1.26.4"),),
    managed_optimization_profiles=("first_party_pls",),
    citations=(
        "Barnes, Dhanoa & Lister, Standard Normal Variate Transformation and De-trending of "
        "Near-Infrared Diffuse Reflectance Spectra, Applied Spectroscopy 43 (1989) 772-777",
        "mdatools R package, row-wise spectral normalization methods",
    ),
)


__all__ = ["NormalizeNode"]
