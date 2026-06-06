"""
Normalize and scale nodes: NormalizeNode, ScaleNode.
"""

from __future__ import annotations

from typing import Any

import numpy as np

from ._shared import (
    EFFECT_NORMALIZED,
    EFFECT_SCALED,
    EFFECT_SCATTER_CORRECTED,
    Node,
    NodeMetadata,
    NodeParameter,
    NodePolicy,
    NodeResult,
    PortMetadata,
    add_processing_step,
    build_dataset_like,
    coerce_to_sherpa,
    register_node,
    to_numpy_2d,
)
from ._transforms import (
    _autoscale_export,
    _center_mean_export,
    _msc_export,
    _msc_transform,
    _normalize_scale,
    _normalize_scale_export,
    _pareto_export,
    _scale_max_export,
    _scale_max_transform,
    _snv_export,
    _snv_transform,
)


def _normalize_dispatch(
    data: np.ndarray,
    method: str = "snv",
    reference: str = "mean",
    scale_method: str = "max",
) -> np.ndarray:
    if method == "snv":
        return _snv_transform(data)
    elif method == "msc":
        return _msc_transform(data, reference=reference)
    elif method == "scale":
        return _normalize_scale(data, method=scale_method)
    raise ValueError(f"Unknown normalization method: {method}")


def _msc_reference_spectrum(data: np.ndarray, reference: str = "mean") -> np.ndarray:
    if reference == "mean":
        return np.mean(data, axis=0)
    if reference == "median":
        return np.median(data, axis=0)
    return data[0]


def _normalize_transform_state(data: np.ndarray, params: dict[str, Any]) -> dict[str, Any] | None:
    """Return replayable normalization state for model-application provenance."""
    method = params.get("method", "snv")
    if method in ("max", "area", "minmax"):
        method = "scale"
    if method == "msc":
        reference = params.get("reference", "mean")
        return {
            "method": "msc",
            "reference": reference,
            "reference_spectrum": _msc_reference_spectrum(np.asarray(data, dtype=np.float64), reference).tolist(),
        }
    if method == "snv":
        return {"method": "snv", "replay": "sample_local"}
    if method == "scale":
        return {
            "method": "scale",
            "scale_method": params.get("scale_method", "max"),
            "replay": "sample_local",
        }
    return None


@register_node
class NormalizeNode(Node):
    """Unified normalization node with method selection."""

    metadata = NodeMetadata(
        node_type="preprocess.normalize",
        category="preprocessing",
        label="Normalize",
        description="Normalize spectra (SNV, MSC, or Scale)",
        parameters=[
            NodeParameter(
                name="method",
                label="Method",
                param_type="select",
                default="snv",
                options=[
                    {"label": "SNV", "value": "snv"},
                    {"label": "MSC", "value": "msc"},
                    {"label": "Scale", "value": "scale"},
                ],
                description="Normalization method",
                required=True,
                category="basic",
            ),
            # MSC params
            NodeParameter(
                name="reference",
                label="Reference",
                param_type="select",
                default="mean",
                options=["mean", "median", "first"],
                description="Reference spectrum",
                required=False,
                category="basic",
                visible_when={"method": ["msc"]},
            ),
            # Scale params
            NodeParameter(
                name="scale_method",
                label="Scale Method",
                param_type="select",
                default="max",
                options=["max", "area", "minmax"],
                description="Scaling method",
                required=False,
                category="basic",
                visible_when={"method": ["scale"]},
            ),
        ],
        input_types=["NDDataset"],
        input_ports=[
            PortMetadata(
                name="default",
                type_ref="spectrasherpa://types/Array2D/1.0",
                required=True,
                label="Input Data Matrix",
                description=(
                    "Spectral data or feature table. SNV/MSC require spectra; "
                    "scale methods also support feature tables."
                ),
                accepted_data_roles=["X_spectra", "X_features"],
            ),
        ],
        output_type="NDDataset",
        policy=NodePolicy(
            safe_for_auto_apply=True,
            requires_human_review=False,
            data_egress_risk="none",
        ),
    )

    async def execute(self, input_data: Any = None, **kwargs: Any) -> Any:
        input_ds = coerce_to_sherpa(
            input_data,
            input_name="input_data",
        )
        params = self._resolve_params()

        # Convert scale sub-method shortcuts to canonical form
        method = params.get("method", "snv")
        if method in ("max", "area", "minmax"):
            params["scale_method"] = method
            params["method"] = "scale"
            method = "scale"

        data = to_numpy_2d(input_ds, name="input_data", dtype=np.float64)
        normalized = _normalize_dispatch(data, **params)
        result = build_dataset_like(normalized, input_ds)

        effects = []
        if method == "snv":
            effects = [EFFECT_NORMALIZED, EFFECT_SCATTER_CORRECTED]
            result.units = "dimensionless"
        elif method == "msc":
            effects = [EFFECT_SCATTER_CORRECTED]
            result.units = "dimensionless"
        elif method == "scale":
            effects = [EFFECT_SCALED]
            result.units = "normalized"

        step_params = dict(params)
        transform_state = _normalize_transform_state(data, step_params)
        if transform_state is not None:
            step_params["transform_state"] = transform_state

        add_processing_step(
            result,
            "preprocess.normalize",
            step_params,
            node_id=self.node_id,
            state_effects=effects,
        )

        after = np.asarray(result.data, dtype=np.float64)
        eps = 1e-12
        diagnostics: dict[str, Any] = {"method": method}
        try:
            snr_before = float(np.mean(np.abs(data)) / (np.std(data) + eps))
            snr_after = float(np.mean(np.abs(after)) / (np.std(after) + eps))
            diagnostics["snr_before"] = snr_before
            diagnostics["snr_after"] = snr_after
            diagnostics["mean_spectrum_shift"] = float(np.mean(after) - np.mean(data))
            diagnostics["max_absolute_change"] = float(np.max(np.abs(after - data)))
        except Exception:
            # If diagnostics computation fails, still return NodeResult with method
            pass
        return NodeResult(outputs={"default": result}, diagnostics=diagnostics)

    def supports_python_export(self) -> bool:
        return True

    def generate_python(self, inputs, indent="    ", use_scp=True):
        inp = next(iter(inputs.values())) if inputs else "input_data"
        params = self._resolve_params()
        method = params.get("method", "snv")
        # Convert scale sub-method shortcuts to canonical form
        if method in ("max", "area", "minmax"):
            scale_params = {"method": method}
            return _normalize_scale_export(scale_params, inp, self.node_id, indent, use_scp)
        if method == "snv":
            return _snv_export(params, inp, self.node_id, indent, use_scp)
        elif method == "msc":
            return _msc_export(params, inp, self.node_id, indent, use_scp)
        elif method == "scale":
            scale_params = {"method": params.get("scale_method", "max")}
            return _normalize_scale_export(scale_params, inp, self.node_id, indent, use_scp)
        return [f"{indent}# TODO: normalize method '{method}' export not implemented"]


def _scale_dispatch(
    data: np.ndarray,
    method: str = "mean_center",
    center: bool = True,
    target_max: float = 1.0,
    reference_data: np.ndarray | None = None,
) -> np.ndarray:
    ref = data if reference_data is None else reference_data
    if method == "mean_center":
        return data - np.mean(ref, axis=0)
    elif method == "autoscale":
        if center:
            data = data - np.mean(ref, axis=0, keepdims=True)
        std = np.std(ref, axis=0, keepdims=True)
        std[(std == 0) | ~np.isfinite(std)] = 1.0
        return data / std
    elif method == "pareto":
        if center:
            data = data - np.mean(ref, axis=0, keepdims=True)
        std = np.std(ref, axis=0, keepdims=True)
        sf = np.sqrt(np.maximum(std, 0))
        sf[(sf == 0) | ~np.isfinite(sf)] = 1.0
        return data / sf
    elif method == "scale_max":
        return _scale_max_transform(data, target_max=target_max)
    raise ValueError(f"Unknown scaling method: {method}")


def _scale_transform_state(
    data: np.ndarray,
    *,
    method: str,
    center: bool = True,
    target_max: float = 1.0,
) -> dict[str, Any] | None:
    """Return replayable scale state for model-application provenance."""
    ref = np.asarray(data, dtype=np.float64)
    if method == "mean_center":
        return {
            "method": method,
            "mean": np.mean(ref, axis=0).astype(np.float64).tolist(),
        }
    if method == "autoscale":
        std = np.std(ref, axis=0)
        std[(std == 0) | ~np.isfinite(std)] = 1.0
        return {
            "method": method,
            "center": bool(center),
            "mean": np.mean(ref, axis=0).astype(np.float64).tolist() if center else None,
            "scale": std.astype(np.float64).tolist(),
        }
    if method == "pareto":
        std = np.std(ref, axis=0)
        sf = np.sqrt(np.maximum(std, 0))
        sf[(sf == 0) | ~np.isfinite(sf)] = 1.0
        return {
            "method": method,
            "center": bool(center),
            "mean": np.mean(ref, axis=0).astype(np.float64).tolist() if center else None,
            "scale": sf.astype(np.float64).tolist(),
        }
    if method == "scale_max":
        return {
            "method": method,
            "target_max": float(target_max),
            "replay": "sample_local",
        }
    return None


@register_node
class ScaleNode(Node):
    """Unified scaling/centering node with method selection."""

    metadata = NodeMetadata(
        node_type="preprocess.scale",
        category="preprocessing",
        label="Scale / Center",
        description="Scale or center spectra (Mean Center, Autoscale, Pareto, Max)",
        parameters=[
            NodeParameter(
                name="method",
                label="Method",
                param_type="select",
                default="mean_center",
                options=[
                    {"label": "Mean Center", "value": "mean_center"},
                    {"label": "Autoscale", "value": "autoscale"},
                    {"label": "Pareto", "value": "pareto"},
                    {"label": "Scale to Max", "value": "scale_max"},
                ],
                description="Scaling method",
                required=True,
                category="basic",
            ),
            NodeParameter(
                name="center",
                label="Mean Center First",
                param_type="boolean",
                default=True,
                description="Subtract mean before scaling",
                required=False,
                category="basic",
                visible_when={"method": ["autoscale", "pareto"]},
            ),
            NodeParameter(
                name="target_max",
                label="Target Maximum",
                param_type="number",
                default=1.0,
                min_value=0.01,
                step=0.1,
                description="Target max value",
                required=False,
                category="basic",
                visible_when={"method": ["scale_max"]},
            ),
        ],
        input_types=["NDDataset"],
        input_ports=[
            PortMetadata(
                name="default",
                type_ref="spectrasherpa://types/Array2D/1.0",
                required=True,
                label="Input Data Matrix",
                description="Spectral data or multivariate feature table to scale or center",
                accepted_data_roles=["X_spectra", "X_features"],
            ),
            PortMetadata(
                name="reference",
                type_ref="spectrasherpa://types/Array2D/1.0",
                required=False,
                label="Reference Data",
                description="Optional spectral or feature-table dataset used to fit centering/scaling parameters",
                accepted_data_roles=["X_spectra", "X_features"],
            ),
        ],
        output_type="NDDataset",
    )

    async def execute(
        self,
        default: Any = None,
        input_data: Any = None,
        reference: Any = None,
        **kwargs: Any,
    ) -> Any:
        source = input_data if input_data is not None else default
        input_ds = coerce_to_sherpa(
            source,
            input_name="input_data",
        )
        params = self._resolve_params()
        data = to_numpy_2d(input_ds, name="input_data", dtype=np.float64)
        ref_data = None
        if reference is not None:
            reference_ds = coerce_to_sherpa(reference, input_name="reference")
            ref_data = to_numpy_2d(reference_ds, name="reference", dtype=np.float64)
        scaled = _scale_dispatch(data, reference_data=ref_data, **params)
        result = build_dataset_like(scaled, input_ds)

        method = params.get("method", "mean_center")
        if method in ("autoscale", "pareto"):
            result.units = "dimensionless"
        elif method == "scale_max":
            result.units = "normalized"

        effects = [EFFECT_SCALED] if method != "mean_center" else []
        step_params = dict(params)
        transform_state = _scale_transform_state(
            ref_data if ref_data is not None else data,
            method=method,
            center=bool(params.get("center", True)),
            target_max=float(params.get("target_max", 1.0)),
        )
        if transform_state is not None:
            step_params["transform_state"] = transform_state
            step_params["state_scope"] = "reference" if ref_data is not None else "input"

        add_processing_step(
            result,
            "preprocess.scale",
            step_params,
            node_id=self.node_id,
            state_effects=effects,
        )
        return result

    def supports_python_export(self) -> bool:
        return True

    def generate_python(self, inputs, indent="    ", use_scp=True):
        inp = inputs.get("default") if inputs else None
        if inp is None:
            inp = next(iter(inputs.values())) if inputs else "input_data"
        reference_expr = inputs.get("reference")
        params = self._resolve_params()
        method = params.get("method", "mean_center")
        if method == "mean_center":
            return _center_mean_export(params, inp, self.node_id, indent, use_scp, reference_expr)
        elif method == "autoscale":
            return _autoscale_export(params, inp, self.node_id, indent, use_scp, reference_expr)
        elif method == "pareto":
            return _pareto_export(params, inp, self.node_id, indent, use_scp, reference_expr)
        elif method == "scale_max":
            return _scale_max_export(params, inp, self.node_id, indent, use_scp)
        return [f"{indent}# TODO: scale method '{method}' export not implemented"]
