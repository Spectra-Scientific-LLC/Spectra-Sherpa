"""
Smoothing and derivative nodes: SmoothNode, DerivativeNode.
"""

from __future__ import annotations

from typing import Any

import numpy as np

from ._shared import (
    EFFECT_DERIVATIVE,
    EFFECT_SMOOTHED,
    Node,
    NodeMetadata,
    NodeParameter,
    PortMetadata,
    _format_value,
    _wrap_result_lines,
    add_processing_step,
    build_dataset_like,
    coerce_to_sherpa,
    estimate_snr,
    gaussian_smooth,
    norris_williams,
    register_node,
    to_numpy_2d,
    whittaker_smooth,
)
from ._transforms import (
    _savgol_deriv,
    _savgol_smooth,
    _savgol_smooth_export,
    _sg_deriv_export,
    _update_derivative_units,
)


def _smooth_dispatch(
    data: np.ndarray,
    method: str = "savitzky_golay",
    size: int = 11,
    order: int = 2,
    lam: float = 1e2,
    d: str = "2",
    sigma: float = 2.0,
) -> np.ndarray:
    if method == "savitzky_golay":
        return _savgol_smooth(data, size=int(size), order=int(order))
    elif method == "whittaker":
        return whittaker_smooth(data, lam=float(lam), d=int(d))
    elif method == "gaussian":
        return gaussian_smooth(data, sigma=float(sigma))
    raise ValueError(f"Unknown smoothing method: {method}")


@register_node
class SmoothNode(Node):
    """Unified smoothing node with method selection."""

    metadata = NodeMetadata(
        node_type="preprocess.smooth",
        category="preprocessing",
        label="Smooth",
        description="Smooth spectra (Savitzky-Golay, Whittaker, or Gaussian)",
        parameters=[
            NodeParameter(
                name="method",
                label="Method",
                param_type="select",
                default="savitzky_golay",
                options=[
                    {"label": "Savitzky-Golay", "value": "savitzky_golay"},
                    {"label": "Whittaker", "value": "whittaker"},
                    {"label": "Gaussian", "value": "gaussian"},
                ],
                description="Smoothing algorithm",
                required=True,
                category="basic",
            ),
            # Savitzky-Golay params
            NodeParameter(
                name="size",
                label="Window Size",
                param_type="number",
                default=11,
                min_value=3,
                max_value=21,
                step=2,
                description="Window size (must be odd)",
                required=False,
                category="basic",
                visible_when={"method": ["savitzky_golay"]},
            ),
            NodeParameter(
                name="order",
                label="Polynomial Order",
                param_type="number",
                default=2,
                min_value=1,
                max_value=6,
                step=1,
                description="Polynomial order",
                required=False,
                category="basic",
                visible_when={"method": ["savitzky_golay"]},
            ),
            # Whittaker params
            NodeParameter(
                name="lam",
                label="Lambda",
                param_type="number",
                default=1e2,
                min_value=1,
                max_value=1e8,
                description="Smoothness penalty",
                required=False,
                category="basic",
                visible_when={"method": ["whittaker"]},
            ),
            NodeParameter(
                name="d",
                label="Difference Order",
                param_type="select",
                default="2",
                options=["1", "2", "3"],
                description="Difference order",
                required=False,
                category="advanced",
                visible_when={"method": ["whittaker"]},
            ),
            # Gaussian params
            NodeParameter(
                name="sigma",
                label="Sigma",
                param_type="number",
                default=2.0,
                min_value=0.1,
                max_value=50.0,
                step=0.1,
                description="Gaussian kernel width",
                required=False,
                category="basic",
                visible_when={"method": ["gaussian"]},
            ),
        ],
        input_types=["NDDataset"],
        input_ports=[
            PortMetadata(
                name="default",
                type_ref="spectrasherpa://types/SpectralDataset/1.0",
                required=True,
                label="Input Spectra",
                description="Spectral data to process",
            ),
        ],
        output_type="NDDataset",
    )

    async def execute(self, input_data: Any = None, **kwargs: Any) -> Any:
        input_ds = coerce_to_sherpa(
            input_data,
            input_name="input_data",
        )
        params = self._resolve_params()
        data = to_numpy_2d(input_ds, name="input_data", dtype=np.float64)
        snr_before = estimate_snr(data)
        smoothed = _smooth_dispatch(data, **params)
        snr_after = estimate_snr(smoothed)
        result = build_dataset_like(smoothed, input_ds)
        add_processing_step(
            result,
            "preprocess.smooth",
            params,
            node_id=self.node_id,
            state_effects=[EFFECT_SMOOTHED],
        )
        result.meta["snr_before_db"] = snr_before
        result.meta["snr_after_db"] = snr_after
        result.meta["snr_improvement_db"] = snr_after - snr_before
        return result

    def supports_python_export(self) -> bool:
        return True

    def generate_python(self, inputs, indent="    ", use_scp=True):
        inp = next(iter(inputs.values())) if inputs else "input_data"
        params = self._resolve_params()
        method = params.get("method", "savitzky_golay")
        if method == "savitzky_golay":
            return _savgol_smooth_export(params, inp, self.node_id, indent, use_scp)
        elif method == "whittaker":
            lam = params.get("lam", 1e2)
            d = int(params.get("d", "2"))
            lines = [
                f"{indent}# --- Whittaker Smoother ({self.node_id}) ---",
                f"{indent}_data = np.array({inp}.data, dtype=np.float64)",
                f"{indent}_smoothed = whittaker_smooth(_data, lam={_format_value(lam)}, d={d})",
            ]
            lines += _wrap_result_lines(self.node_id, "_smoothed", inp, indent, use_scp)
            return lines
        elif method == "gaussian":
            sigma = params.get("sigma", 2.0)
            lines = [
                f"{indent}# --- Gaussian Smoothing ({self.node_id}) ---",
                f"{indent}_data = np.array({inp}.data, dtype=np.float64)",
                f"{indent}if _data.ndim == 1:",
                f"{indent}    _smoothed = gaussian_filter1d(_data, sigma={_format_value(sigma)})",
                f"{indent}else:",
                f"{indent}    _smoothed = np.apply_along_axis("
                f"gaussian_filter1d, -1, _data, sigma={_format_value(sigma)})",
            ]
            lines += _wrap_result_lines(self.node_id, "_smoothed", inp, indent, use_scp)
            return lines
        return [f"{indent}# TODO: smooth method '{method}' export not implemented"]


def _derivative_dispatch(
    data: np.ndarray,
    method: str = "savitzky_golay",
    deriv: str = "1",
    size: int = 11,
    order: int = 2,
    gap: int = 5,
    segment: int = 5,
) -> np.ndarray:
    deriv_order = int(deriv)
    if method == "savitzky_golay":
        sz = int(size)
        if sz % 2 == 0:
            sz += 1
        return _savgol_deriv(data, size=sz, order=int(order), deriv=deriv_order)
    elif method == "norris_williams":
        return norris_williams(data, gap=int(gap), segment=int(segment), deriv=deriv_order)
    raise ValueError(f"Unknown derivative method: {method}")


@register_node
class DerivativeNode(Node):
    """Unified derivative node with method selection."""

    metadata = NodeMetadata(
        node_type="preprocess.derivative",
        category="preprocessing",
        label="Derivative",
        description="Compute spectral derivatives (Savitzky-Golay or Norris-Williams)",
        parameters=[
            NodeParameter(
                name="method",
                label="Method",
                param_type="select",
                default="savitzky_golay",
                options=[
                    {"label": "Savitzky-Golay", "value": "savitzky_golay"},
                    {"label": "Norris-Williams", "value": "norris_williams"},
                ],
                description="Derivative algorithm",
                required=True,
                category="basic",
            ),
            NodeParameter(
                name="deriv",
                label="Derivative Order",
                param_type="select",
                default="1",
                options=["0", "1", "2"],
                description="Derivative order: 0 (smooth only), 1 (first), 2 (second)",
                required=True,
                category="basic",
            ),
            # Savitzky-Golay params
            NodeParameter(
                name="size",
                label="Window Size",
                param_type="number",
                default=11,
                min_value=3,
                max_value=51,
                step=2,
                description="Window size",
                required=False,
                category="basic",
                visible_when={"method": ["savitzky_golay"]},
            ),
            NodeParameter(
                name="order",
                label="Polynomial Order",
                param_type="number",
                default=2,
                min_value=1,
                max_value=5,
                step=1,
                description="Polynomial order",
                required=False,
                category="basic",
                visible_when={"method": ["savitzky_golay"]},
            ),
            # Norris-Williams params
            NodeParameter(
                name="gap",
                label="Gap",
                param_type="number",
                default=5,
                min_value=1,
                max_value=50,
                step=1,
                description="Gap size",
                required=False,
                category="basic",
                visible_when={"method": ["norris_williams"]},
            ),
            NodeParameter(
                name="segment",
                label="Segment",
                param_type="number",
                default=5,
                min_value=1,
                max_value=50,
                step=1,
                description="Segment size",
                required=False,
                category="basic",
                visible_when={"method": ["norris_williams"]},
            ),
        ],
        input_types=["NDDataset"],
        input_ports=[
            PortMetadata(
                name="default",
                type_ref="spectrasherpa://types/SpectralDataset/1.0",
                required=True,
                label="Input Spectra",
                description="Spectral data to process",
            ),
        ],
        output_type="NDDataset",
    )

    async def execute(self, input_data: Any = None, **kwargs: Any) -> Any:
        input_ds = coerce_to_sherpa(
            input_data,
            input_name="input_data",
        )
        params = self._resolve_params()
        data = to_numpy_2d(input_ds, name="input_data", dtype=np.float64)
        transformed = _derivative_dispatch(data, **params)
        result = build_dataset_like(transformed, input_ds)

        deriv_order = int(params.get("deriv", "1"))
        if deriv_order > 0:
            _update_derivative_units(result, input_ds, deriv_order)
            if not getattr(result, "units", None):
                result.units = "d/dx" if deriv_order == 1 else "d\u00b2/dx\u00b2"

        add_processing_step(
            result,
            "preprocess.derivative",
            params,
            node_id=self.node_id,
            state_effects=[EFFECT_DERIVATIVE, EFFECT_SMOOTHED],
        )
        return result

    def supports_python_export(self) -> bool:
        return True

    def generate_python(self, inputs, indent="    ", use_scp=True):
        inp = next(iter(inputs.values())) if inputs else "input_data"
        params = self._resolve_params()
        method = params.get("method", "savitzky_golay")
        deriv_order = int(params.get("deriv", "1"))
        if method == "savitzky_golay":
            return _sg_deriv_export(params, inp, self.node_id, indent, use_scp)
        elif method == "norris_williams":
            gap = params.get("gap", 5)
            segment = params.get("segment", 5)
            lines = [
                f"{indent}# --- Norris-Williams Derivative ({self.node_id}) ---",
                f"{indent}_data = np.array({inp}.data, dtype=np.float64)",
                f"{indent}_derived = norris_williams(_data, gap={gap}, segment={segment}, deriv={deriv_order})",
            ]
            lines += _wrap_result_lines(self.node_id, "_derived", inp, indent, use_scp)
            return lines
        return [f"{indent}# TODO: derivative method '{method}' export not implemented"]
