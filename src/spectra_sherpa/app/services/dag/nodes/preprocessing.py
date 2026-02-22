"""
Preprocessing nodes for spectral data.

These nodes implement various preprocessing techniques like baseline correction,
smoothing, normalization, and derivatives.

All nodes:
- Accept SherpaDataset (or legacy NDDataset via coercion) as input
- Return SherpaDataset as output
- Record processing history via provenance
"""

from __future__ import annotations

from typing import Any, Dict

import numpy as np

from spectra_sherpa.app.lib.sherpa_dataset import (
    EFFECT_BASELINE_CORRECTED,
    EFFECT_DERIVATIVE,
    EFFECT_NORMALIZED,
    EFFECT_SCALED,
    EFFECT_SCATTER_CORRECTED,
    EFFECT_SMOOTHED,
    SherpaDataset,
)
from spectra_sherpa.app.lib.preprocessing import (
    baseline_penalized_ls,
    gaussian_smooth,
    norris_williams,
    remove_cosmic_rays,
    whittaker_smooth,
)
from spectra_sherpa.app.lib.adapters.scp_adapter import scp_roundtrip
from spectra_sherpa.app.lib.scp_compat import HAS_SCP, NDDataset, from_nddataset, scp, to_nddataset

from ..export_helpers import (
    extract_data_lines,
    header_line,
)
from ..export_helpers import (
    wrap_result_lines as _wrap_result_lines,
)
from ..io_contracts import (
    bind_X,
    bind_y,
    build_dataset_like,
    coerce_to_sherpa,
    resolve_legacy_input,
    to_numpy_1d,
    to_numpy_2d,
)
from ..meta_helpers import add_processing_step, copy_processing_history
from ..node_base import (
    Node,
    NodeMetadata,
    NodeParameter,
    NodePolicy,
    NodeResult,
    PortMetadata,
    _format_value,
    register_node,
)
from ..spec_nodes import TransformSpec, TransformSpecNode


@register_node
class BaselinePenalizedLSNode(Node):
    """
    Penalized Least Squares baseline correction node.

    Supports three algorithms via method selector:
    - ALS:    Asymmetric Least Squares (Eilers 2005)
    - ArPLS:  Asymmetrically Reweighted PLS (Baek et al. 2015)
    - AirPLS: Adaptive Iteratively Reweighted PLS (Zhang et al. 2010)
    """

    metadata = NodeMetadata(
        node_type="baseline.penalized_ls",
        category="preprocessing",
        label="Baseline (Penalized LS)",
        description="Penalized Least Squares baseline correction (ALS / ArPLS / AirPLS)",
        parameters=[
            NodeParameter(
                name="method",
                label="Algorithm",
                param_type="select",
                default="als",
                options=["als", "arpls", "airpls"],
                description="ALS: classic asymmetric; ArPLS: adaptive reweighted; AirPLS: iterative reweighted",
                required=True,
                category="basic",
            ),
            NodeParameter(
                name="lam",
                label="Lambda (Smoothness)",
                param_type="number",
                default=1e5,
                min_value=1e2,
                max_value=1e9,
                description="Smoothness parameter (larger = smoother baseline)",
                required=False,
                category="basic",
            ),
            NodeParameter(
                name="p",
                label="Asymmetry (p)",
                param_type="number",
                default=0.001,
                min_value=0.0001,
                max_value=0.1,
                step=0.0001,
                description="Asymmetry parameter (ALS only; smaller = more asymmetric)",
                required=False,
                category="basic",
            ),
            NodeParameter(
                name="max_iter",
                label="Max Iterations",
                param_type="number",
                default=50,
                min_value=5,
                max_value=500,
                step=5,
                description="Maximum number of iterations",
                required=False,
                category="advanced",
            ),
            NodeParameter(
                name="tol",
                label="Convergence Tolerance",
                param_type="number",
                default=1e-6,
                min_value=1e-10,
                max_value=1e-2,
                description="Convergence tolerance on weight change",
                required=False,
                category="advanced",
            ),
        ],
        input_types=["NDDataset"],
        output_type="NDDataset",
    )

    python_extra_imports = [
        "import numpy as np",
        "from scipy import sparse",
    ]

    def generate_python(self, inputs, indent="    ", use_scp=True):
        inp = next(iter(inputs.values())) if inputs else "input_data"
        params = self._resolve_params()
        method = params.get("method", "als")
        lam = params.get("lam", 1e5)
        p = params.get("p", 0.001)
        max_iter = params.get("max_iter", 50)
        tol = params.get("tol", 1e-6)
        lines = [
            f"{indent}# --- Baseline Penalized LS ({self.node_id}) ---",
            f"{indent}from spectra_sherpa.app.lib.preprocessing import baseline_penalized_ls",
            f"{indent}_data = np.array({inp}.data, dtype=np.float64)",
            f"{indent}_corrected = baseline_penalized_ls("
            f"_data, method='{method}', lam={_format_value(lam)}, "
            f"p={_format_value(p)}, max_iter={max_iter}, "
            f"tol={_format_value(tol)})",
        ]
        lines += _wrap_result_lines(self.node_id, "_corrected", inp, indent, use_scp)
        return lines

    async def execute(self, input_data: Any) -> SherpaDataset:
        """Execute penalized LS baseline correction."""
        input_ds = coerce_to_sherpa(input_data, input_name="input_data")
        method = self.parameters.get("method", "als")
        lam = self.parameters.get("lam", 1e5)
        p = self.parameters.get("p", 0.001)
        max_iter = self.parameters.get("max_iter", 50)
        tol = self.parameters.get("tol", 1e-6)

        data = to_numpy_2d(input_ds, name="input_data", dtype=np.float64)
        corrected = baseline_penalized_ls(
            data,
            method=method,
            lam=lam,
            p=p,
            max_iter=max_iter,
            tol=tol,
        )

        result = build_dataset_like(corrected, input_ds)
        add_processing_step(
            result,
            "baseline.penalized_ls",
            {"method": method, "lam": lam, "p": p, "max_iter": max_iter, "tol": tol},
            node_id=self.node_id,
            state_effects=[EFFECT_BASELINE_CORRECTED],
        )

        return result


@register_node
class BaselineRubberbandNode(Node):
    """
    Rubberband baseline correction node.

    Removes baseline by fitting a convex hull baseline.
    """

    scp_method = "basc"
    scp_extra_kwargs = {"method": "rubberband"}

    metadata = NodeMetadata(
        node_type="baseline.rubberband",
        category="preprocessing",
        label="Baseline (Rubberband)",
        description="Rubberband (convex hull) baseline correction",
        parameters=[
            NodeParameter(
                name="ranges",
                label="Spectral Ranges",
                param_type="text",
                default="",
                description="Optional: spectral ranges for baseline points (e.g., '4000:3800, 1800:1700')",
                required=False,
            ),
        ],
        input_types=["NDDataset"],
        output_type="NDDataset",
        requires_scp=True,
    )

    async def execute(self, input_data) -> SherpaDataset:
        """Execute rubberband baseline correction."""
        input_ds = coerce_to_sherpa(input_data, input_name="input_data")
        ranges_str = self.parameters.get("ranges", "").strip()

        basc_kwargs: Dict[str, Any] = {"method": "rubberband"}
        if ranges_str:
            parsed = []
            for part in ranges_str.split(","):
                part = part.strip()
                if ":" in part:
                    lo, hi = part.split(":", 1)
                    parsed.append((float(lo.strip()), float(hi.strip())))
            if parsed:
                basc_kwargs["ranges"] = parsed

        return scp_roundtrip(
            input_ds,
            lambda ndd: ndd.basc(**basc_kwargs),
            op_id="baseline.rubberband",
            parameters={"method": "rubberband", "ranges": ranges_str or None},
            state_effects=[EFFECT_BASELINE_CORRECTED],
            node_id=self.node_id,
        )


@register_node
class SmoothSavitzkyGolayNode(Node):
    """
    Savitzky-Golay smoothing node.

    Applies polynomial smoothing to reduce noise.
    """

    scp_method = "smooth"

    metadata = NodeMetadata(
        node_type="smooth.savitzky_golay",
        category="preprocessing",
        label="Smooth (Savitzky-Golay)",
        description="Savitzky-Golay polynomial smoothing filter",
        parameters=[
            NodeParameter(
                name="size",
                label="Window Size",
                param_type="number",
                default=11,
                min_value=3,
                max_value=51,
                step=2,
                description="Window size (must be odd number)",
                required=True,
                category="basic",
            ),
            NodeParameter(
                name="order",
                label="Polynomial Order",
                param_type="number",
                default=2,
                min_value=1,
                max_value=5,
                step=1,
                description="Order of polynomial fit",
                required=True,
                category="basic",
            ),
        ],
        input_types=["NDDataset"],
        output_type="NDDataset",
    )

    python_extra_imports = ["from scipy.signal import savgol_filter"]

    def generate_python(self, inputs, indent="    ", use_scp=True):
        inp = next(iter(inputs.values())) if inputs else "input_data"
        params = self._resolve_params()
        size = params.get("size", 11)
        order = params.get("order", 2)
        if use_scp:
            return [
                f"{indent}# --- Smooth (Savitzky-Golay) ({self.node_id}) ---",
                f"{indent}data = {inp}.copy()",
                f"{indent}data.smooth(size={size}, order={order})",
                f"{indent}results['{self.node_id}'] = data",
            ]
        return [
            f"{indent}# --- Smooth (Savitzky-Golay) ({self.node_id}) ---",
            f"{indent}_data = np.array({inp}.data, dtype=np.float64)",
            f"{indent}if _data.ndim >= 2:",
            f"{indent}    _data = np.apply_along_axis("
            f"savgol_filter, -1, _data, window_length={size}, polyorder={order})",
            f"{indent}else:",
            f"{indent}    _data = savgol_filter(" f"_data, window_length={size}, polyorder={order})",
        ] + _wrap_result_lines(self.node_id, "_data", inp, indent, use_scp)

    async def execute(self, input_data: Any) -> Any:
        """Execute Savitzky-Golay smoothing."""
        size = self.parameters.get("size", 11)
        order = self.parameters.get("order", 2)

        input_ds = coerce_to_sherpa(input_data, input_name="input_data")
        from scipy.signal import savgol_filter

        raw = np.asarray(input_ds.data, dtype=np.float64)
        smoothed = (
            np.apply_along_axis(savgol_filter, -1, raw, window_length=int(size), polyorder=int(order))
            if raw.ndim >= 2
            else savgol_filter(raw, window_length=int(size), polyorder=int(order))
        )
        result = build_dataset_like(smoothed, input_ds)
        add_processing_step(
            result,
            "smooth.savitzky_golay",
            {"size": size, "order": order},
            node_id=self.node_id,
            state_effects=[EFFECT_SMOOTHED],
        )

        return result


@register_node
class NormalizeSNVNode(Node):
    """
    Standard Normal Variate (SNV) normalization node.

    Normalizes each spectrum to zero mean and unit variance.
    """

    metadata = NodeMetadata(
        node_type="normalize.snv",
        category="preprocessing",
        label="Normalize (SNV)",
        description="Standard Normal Variate normalization",
        parameters=[],
        input_types=["NDDataset"],
        output_type="NDDataset",
        input_ports=[
            PortMetadata(
                name="default",
                type_ref="spectrasherpa://types/SpectralDataset/1.0",
                required=True,
                label="Input Spectra",
                description="Input spectral dataset",
            )
        ],
        output_ports=[
            PortMetadata(
                name="default",
                type_ref="spectrasherpa://types/SpectralDataset/1.0",
                required=True,
                label="SNV Spectra",
                description="SNV-normalized spectral dataset",
            )
        ],
        diagnostics=[
            "snr_before",
            "snr_after",
            "mean_spectrum_shift",
            "max_absolute_change",
        ],
        policy=NodePolicy(
            safe_for_auto_apply=True,
            requires_human_review=False,
            data_egress_risk="none",
        ),
    )

    python_extra_imports = ["import numpy as np"]

    def generate_python(self, inputs, indent="    ", use_scp=True):
        inp = next(iter(inputs.values())) if inputs else "input_data"
        return [
            f"{indent}# --- SNV Normalization ({self.node_id}) ---",
            f"{indent}_data = np.array({inp}.data, dtype=np.float64)",
            f"{indent}if _data.ndim == 1:",
            f"{indent}    _mean = np.mean(_data)",
            f"{indent}    _std = np.std(_data)",
            f"{indent}    if _std == 0: _std = 1.0",
            f"{indent}    _data = (_data - _mean) / _std",
            f"{indent}else:",
            f"{indent}    _mean = np.mean(_data, axis=1, keepdims=True)",
            f"{indent}    _std = np.std(_data, axis=1, keepdims=True)",
            f"{indent}    _std[_std == 0] = 1.0",
            f"{indent}    _data = (_data - _mean) / _std",
        ] + _wrap_result_lines(self.node_id, "_data", inp, indent, use_scp)

    async def execute(self, input_data: Any) -> NodeResult:
        """Execute SNV normalization."""
        input_ds = coerce_to_sherpa(input_data, input_name="input_data")
        data = to_numpy_2d(input_ds, name="input_data", dtype=np.float64)
        before = data.copy()

        mean_vals = np.mean(data, axis=1, keepdims=True)
        std_vals = np.std(data, axis=1, keepdims=True)
        std_vals[std_vals == 0] = 1.0
        normalized_data = (data - mean_vals) / std_vals

        result = build_dataset_like(
            normalized_data,
            input_ds,
            units="dimensionless",
        )
        add_processing_step(
            result,
            "normalize.snv",
            {},
            node_id=self.node_id,
            state_effects=[EFFECT_NORMALIZED, EFFECT_SCATTER_CORRECTED],
        )

        eps = 1e-12
        snr_before = float(np.mean(np.abs(before)) / (np.std(before) + eps))
        snr_after = float(np.mean(np.abs(normalized_data)) / (np.std(normalized_data) + eps))
        mean_spectrum_shift = float(np.mean(normalized_data) - np.mean(before))
        max_absolute_change = float(np.max(np.abs(normalized_data - before)))

        return NodeResult(
            outputs={"default": result},
            diagnostics={
                "snr_before": snr_before,
                "snr_after": snr_after,
                "mean_spectrum_shift": mean_spectrum_shift,
                "max_absolute_change": max_absolute_change,
            },
        )


@register_node
class NormalizeScaleNode(Node):
    """
    Scale normalization node.

    Normalizes spectra by scaling to a specified method (max, area, range).
    """

    metadata = NodeMetadata(
        node_type="normalize.scale",
        category="preprocessing",
        label="Normalize (Scale)",
        description="Scale normalization (to max, area, or range)",
        parameters=[
            NodeParameter(
                name="method",
                label="Scaling Method",
                param_type="select",
                default="max",
                options=["max", "area", "minmax"],
                description="Scaling method: max (unit max), area (unit area), minmax (0-1 range)",
                required=False,
            ),
        ],
        input_types=["NDDataset"],
        output_type="NDDataset",
    )

    python_extra_imports = ["import numpy as np"]

    def generate_python(self, inputs, indent="    ", use_scp=True):
        inp = next(iter(inputs.values())) if inputs else "input_data"
        method = self._resolve_params().get("method", "max")
        lines = [
            f"{indent}# --- Scale Normalization ({self.node_id}) ---",
            f"{indent}_data = np.array({inp}.data, dtype=np.float64)",
        ]
        if method == "max":
            lines += [
                f"{indent}_max = np.abs(_data).max(axis=-1, keepdims=True)",
                f"{indent}_max[_max == 0] = 1",
                f"{indent}_data = _data / _max",
            ]
        elif method == "area":
            lines += [
                f"{indent}_area = np.abs(_data).sum(axis=-1, keepdims=True)",
                f"{indent}_area[_area == 0] = 1",
                f"{indent}_data = _data / _area",
            ]
        elif method == "minmax":
            lines += [
                f"{indent}_min = _data.min(axis=-1, keepdims=True)",
                f"{indent}_max = _data.max(axis=-1, keepdims=True)",
                f"{indent}_range = _max - _min",
                f"{indent}_range[_range == 0] = 1",
                f"{indent}_data = (_data - _min) / _range",
            ]
        lines += _wrap_result_lines(self.node_id, "_data", inp, indent, use_scp)
        return lines

    async def execute(self, input_data: Any) -> SherpaDataset:
        """Execute scale normalization."""
        input_ds = coerce_to_sherpa(input_data, input_name="input_data")
        method = self.parameters.get("method", "max")
        data = to_numpy_2d(input_ds, name="input_data", dtype=np.float64)

        if method == "max":
            max_vals = np.abs(data).max(axis=-1, keepdims=True)
            max_vals[max_vals == 0] = 1
            data = data / max_vals
        elif method == "area":
            areas = np.abs(data).sum(axis=-1, keepdims=True)
            areas[areas == 0] = 1
            data = data / areas
        elif method == "minmax":
            min_vals = data.min(axis=-1, keepdims=True)
            max_vals = data.max(axis=-1, keepdims=True)
            range_vals = max_vals - min_vals
            range_vals[range_vals == 0] = 1
            data = (data - min_vals) / range_vals

        result = build_dataset_like(data, input_ds, units="normalized")
        add_processing_step(
            result,
            "normalize.scale",
            {"method": method},
            node_id=self.node_id,
            state_effects=[EFFECT_SCALED],
        )

        return result


@register_node
class NormalizeMSCNode(Node):
    """
    Multiplicative Scatter Correction (MSC) node.

    Corrects for light scattering effects in spectral data.
    """

    scp_method = "msc"

    metadata = NodeMetadata(
        node_type="normalize.msc",
        category="preprocessing",
        label="Normalize (MSC)",
        description="Multiplicative Scatter Correction",
        parameters=[
            NodeParameter(
                name="reference",
                label="Reference Spectrum",
                param_type="select",
                default="mean",
                options=["mean", "median", "first"],
                description="Reference spectrum for MSC",
                required=False,
            ),
        ],
        input_types=["NDDataset"],
        output_type="NDDataset",
        requires_scp=True,
    )

    async def execute(self, input_data) -> SherpaDataset:
        """Execute MSC normalization."""
        input_ds = coerce_to_sherpa(input_data, input_name="input_data")
        reference = self.parameters.get("reference", "mean")

        def _msc(ndd):
            ndd.msc(reference=reference)
            ndd.units = "dimensionless"
            # return None — in-place mutation; scp_roundtrip handles this

        return scp_roundtrip(
            input_ds,
            _msc,
            op_id="normalize.msc",
            parameters={"reference": reference},
            state_effects=[EFFECT_SCATTER_CORRECTED],
            node_id=self.node_id,
        )


@register_node
class DerivativeFirstNode(Node):
    """
    First derivative node.

    Computes the first derivative of spectral data.
    """

    scp_method = "deriv"
    scp_extra_kwargs = {"deriv": 1}

    metadata = NodeMetadata(
        node_type="derivative.first",
        category="preprocessing",
        label="1st Derivative",
        description="First derivative using Savitzky-Golay",
        parameters=[
            NodeParameter(
                name="size",
                label="Window Size",
                param_type="number",
                default=11,
                min_value=3,
                max_value=51,
                step=2,
                description="Window size for derivative calculation",
                required=False,
            ),
            NodeParameter(
                name="order",
                label="Polynomial Order",
                param_type="number",
                default=2,
                min_value=1,
                max_value=5,
                step=1,
                description="Order of polynomial fit",
                required=False,
            ),
        ],
        input_types=["NDDataset"],
        output_type="NDDataset",
    )

    python_extra_imports = ["from scipy.signal import savgol_filter"]

    def generate_python(self, inputs, indent="    ", use_scp=True):
        inp = next(iter(inputs.values())) if inputs else "input_data"
        params = self._resolve_params()
        size = params.get("size", 11)
        order = params.get("order", 2)
        if use_scp:
            return [
                f"{indent}# --- 1st Derivative ({self.node_id}) ---",
                f"{indent}data = {inp}.copy()",
                f"{indent}data.savgol(size={size}, order={order}, deriv=1)",
                f"{indent}results['{self.node_id}'] = data",
            ]
        return [
            f"{indent}# --- 1st Derivative ({self.node_id}) ---",
            f"{indent}_data = np.array({inp}.data, dtype=np.float64)",
            f"{indent}if _data.ndim >= 2:",
            f"{indent}    _data = np.apply_along_axis("
            f"savgol_filter, -1, _data, window_length={size}, polyorder={order}, deriv=1)",
            f"{indent}else:",
            f"{indent}    _data = savgol_filter(" f"_data, window_length={size}, polyorder={order}, deriv=1)",
        ] + _wrap_result_lines(self.node_id, "_data", inp, indent, use_scp)

    async def execute(self, input_data: Any) -> Any:
        """Execute first derivative calculation."""
        size = self.parameters.get("size", 11)
        order = self.parameters.get("order", 2)

        input_ds = coerce_to_sherpa(input_data, input_name="input_data")
        from scipy.signal import savgol_filter

        raw = np.asarray(input_ds.data, dtype=np.float64)
        derived = (
            np.apply_along_axis(savgol_filter, -1, raw, window_length=int(size), polyorder=int(order), deriv=1)
            if raw.ndim >= 2
            else savgol_filter(raw, window_length=int(size), polyorder=int(order), deriv=1)
        )
        result = build_dataset_like(derived, input_ds)

        # Update units — only when meaningful units exist on both axes
        try:
            original_units = str(input_ds.units) if getattr(input_ds, "units", None) else None
            x_units = input_ds.spectral_axis.units if input_ds.spectral_axis is not None else None

            if original_units and x_units and original_units != "dimensionless":
                result.units = f"d({original_units})/d({x_units})"
            elif original_units and original_units != "dimensionless":
                result.units = f"d({original_units})/dx"
        except Exception:
            pass  # leave units unchanged if assignment fails

        add_processing_step(
            result,
            "derivative.first",
            {"size": size, "order": order},
            node_id=self.node_id,
            state_effects=[EFFECT_DERIVATIVE],
        )

        return result


@register_node
class DerivativeSecondNode(Node):
    """
    Second derivative node.

    Computes the second derivative of spectral data.
    """

    scp_method = "deriv"
    scp_extra_kwargs = {"deriv": 2}

    metadata = NodeMetadata(
        node_type="derivative.second",
        category="preprocessing",
        label="2nd Derivative",
        description="Second derivative using Savitzky-Golay",
        parameters=[
            NodeParameter(
                name="size",
                label="Window Size",
                param_type="number",
                default=11,
                min_value=3,
                max_value=51,
                step=2,
                description="Window size for derivative calculation",
                required=False,
            ),
            NodeParameter(
                name="order",
                label="Polynomial Order",
                param_type="number",
                default=2,
                min_value=2,
                max_value=5,
                step=1,
                description="Order of polynomial fit",
                required=False,
            ),
        ],
        input_types=["NDDataset"],
        output_type="NDDataset",
    )

    python_extra_imports = ["from scipy.signal import savgol_filter"]

    def generate_python(self, inputs, indent="    ", use_scp=True):
        inp = next(iter(inputs.values())) if inputs else "input_data"
        params = self._resolve_params()
        size = params.get("size", 11)
        order = params.get("order", 2)
        if use_scp:
            return [
                f"{indent}# --- 2nd Derivative ({self.node_id}) ---",
                f"{indent}data = {inp}.copy()",
                f"{indent}data.savgol(size={size}, order={order}, deriv=2)",
                f"{indent}results['{self.node_id}'] = data",
            ]
        return [
            f"{indent}# --- 2nd Derivative ({self.node_id}) ---",
            f"{indent}_data = np.array({inp}.data, dtype=np.float64)",
            f"{indent}if _data.ndim >= 2:",
            f"{indent}    _data = np.apply_along_axis("
            f"savgol_filter, -1, _data, window_length={size}, polyorder={order}, deriv=2)",
            f"{indent}else:",
            f"{indent}    _data = savgol_filter(" f"_data, window_length={size}, polyorder={order}, deriv=2)",
        ] + _wrap_result_lines(self.node_id, "_data", inp, indent, use_scp)

    async def execute(self, input_data: Any) -> Any:
        """Execute second derivative calculation."""
        size = self.parameters.get("size", 11)
        order = self.parameters.get("order", 2)

        input_ds = coerce_to_sherpa(input_data, input_name="input_data")
        from scipy.signal import savgol_filter

        raw = np.asarray(input_ds.data, dtype=np.float64)
        derived = (
            np.apply_along_axis(savgol_filter, -1, raw, window_length=int(size), polyorder=int(order), deriv=2)
            if raw.ndim >= 2
            else savgol_filter(raw, window_length=int(size), polyorder=int(order), deriv=2)
        )
        result = build_dataset_like(derived, input_ds)

        # Update units — only when meaningful units exist on both axes
        try:
            original_units = str(input_ds.units) if getattr(input_ds, "units", None) else None
            x_units = input_ds.spectral_axis.units if input_ds.spectral_axis is not None else None

            if original_units and x_units and original_units != "dimensionless":
                result.units = f"d²({original_units})/d({x_units})²"
            elif original_units and original_units != "dimensionless":
                result.units = f"d²({original_units})/dx²"
        except Exception:
            pass  # leave units unchanged if assignment fails

        add_processing_step(
            result,
            "derivative.second",
            {"size": size, "order": order},
            node_id=self.node_id,
            state_effects=[EFFECT_DERIVATIVE],
        )

        return result


# ============================================================================
# ATOMIC PREPROCESSING NODES
# ============================================================================


@register_node
class CosmicRayRemovalNode(Node):
    """
    Cosmic ray removal node.

    Removes spike-like outliers (cosmic rays) from spectral data.
    """

    metadata = NodeMetadata(
        node_type="preprocess.cosmic_ray",
        category="preprocessing",
        label="Cosmic Ray Removal",
        description="Remove spike outliers using local median and MAD statistics",
        parameters=[
            NodeParameter(
                name="window",
                label="Window Size",
                param_type="number",
                default=7,
                min_value=3,
                max_value=31,
                step=2,
                description="Window size for local statistics (must be odd)",
                required=True,
            ),
            NodeParameter(
                name="zscore",
                label="Z-Score Threshold",
                param_type="number",
                default=3.0,
                min_value=1.5,
                max_value=10.0,
                step=0.5,
                description="Z-score threshold for spike detection",
                required=True,
            ),
        ],
        input_types=["NDDataset"],
        output_type="NDDataset",
    )

    python_extra_imports = [
        "import numpy as np",
        "from scipy.ndimage import median_filter",
    ]

    def generate_python(self, inputs, indent="    ", use_scp=True):
        inp = next(iter(inputs.values())) if inputs else "input_data"
        params = self._resolve_params()
        window = params.get("window", 7)
        zscore = params.get("zscore", 3.0)
        return [
            f"{indent}# --- Cosmic Ray Removal ({self.node_id}) ---",
            f"{indent}def _remove_cosmic_rays(spectrum, window={window}, zscore={zscore}):",
            f"{indent}    med = median_filter(spectrum, size=window)",
            f"{indent}    diff = np.abs(spectrum - med)",
            f"{indent}    mad = np.median(diff)",
            f"{indent}    threshold = zscore * mad / 0.6745 if mad > 0 else np.inf",
            f"{indent}    cleaned = spectrum.copy()",
            f"{indent}    cleaned[diff > threshold] = med[diff > threshold]",
            f"{indent}    return cleaned",
            f"{indent}_data = np.array({inp}.data)",
            f"{indent}if _data.ndim == 1:",
            f"{indent}    _data = _remove_cosmic_rays(_data)",
            f"{indent}else:",
            f"{indent}    for _i in range(_data.shape[0]):",
            f"{indent}        _data[_i] = _remove_cosmic_rays(_data[_i])",
        ] + _wrap_result_lines(self.node_id, "_data", inp, indent, use_scp)

    async def execute(self, input_data: Any) -> SherpaDataset:
        """Execute cosmic ray removal."""
        input_ds = coerce_to_sherpa(input_data, input_name="input_data")
        window = self.parameters.get("window", 7)
        zscore = self.parameters.get("zscore", 3.0)

        if window % 2 == 0:
            window += 1

        data = to_numpy_2d(input_ds, name="input_data", dtype=np.float64)

        if data.ndim == 1:
            data = remove_cosmic_rays(data, window=window, zscore_threshold=zscore)
        else:
            for i in range(data.shape[0]):
                data[i] = remove_cosmic_rays(data[i], window=window, zscore_threshold=zscore)

        result = build_dataset_like(data, input_ds)
        add_processing_step(
            result,
            "preprocess.cosmic_ray",
            {"window": window, "zscore": zscore},
            node_id=self.node_id,
        )

        return result


@register_node
class ClipRangeNode(Node):
    """
    Wavenumber range clipping node.

    Crops the spectral data to a specified wavenumber range.
    """

    metadata = NodeMetadata(
        node_type="preprocess.clip_range",
        category="preprocessing",
        label="Clip Range",
        description="Crop spectrum to a specified wavenumber range",
        parameters=[
            NodeParameter(
                name="min_wavenumber",
                label="Min Wavenumber (cm⁻¹)",
                param_type="number",
                default=400,
                min_value=0,
                max_value=10000,
                description="Minimum wavenumber to keep (lower bound)",
                required=False,
            ),
            NodeParameter(
                name="max_wavenumber",
                label="Max Wavenumber (cm⁻¹)",
                param_type="number",
                default=4000,
                min_value=0,
                max_value=10000,
                description="Maximum wavenumber to keep (upper bound)",
                required=False,
            ),
        ],
        input_types=["NDDataset"],
        output_type="NDDataset",
    )

    python_extra_imports = ["import numpy as np"]

    def generate_python(self, inputs, indent="    ", use_scp=True):
        inp = next(iter(inputs.values())) if inputs else "input_data"
        params = self._resolve_params()
        min_wn = params.get("min_wavenumber")
        max_wn = params.get("max_wavenumber")
        lines = [f"{indent}# --- Clip Range ({self.node_id}) ---"]
        if use_scp:
            # SCP coordinate-aware slicing
            lines.append(f"{indent}_clipped = {inp}.copy()")
            if min_wn is not None and max_wn is not None:
                lines.append(f"{indent}_clipped = _clipped[:, {min_wn}:{max_wn}]")
            elif min_wn is not None:
                lines.append(f"{indent}_clipped = _clipped[:, {min_wn}:]")
            elif max_wn is not None:
                lines.append(f"{indent}_clipped = _clipped[:, :{max_wn}]")
            lines.append(f"{indent}results['{self.node_id}'] = _clipped")
        else:
            # numpy path: find column indices from x-axis values
            lines.append(f"{indent}_x = getattr({inp}, 'x', None)")
            lines.append(f"{indent}_x_vals = np.asarray(_x.data) if _x is not None and _x.data is not None else None")
            lines.append(f"{indent}if _x_vals is not None:")
            lines.append(f"{indent}    _mask = np.ones(len(_x_vals), dtype=bool)")
            if min_wn is not None:
                lines.append(f"{indent}    _mask &= _x_vals >= {min_wn}")
            if max_wn is not None:
                lines.append(f"{indent}    _mask &= _x_vals <= {max_wn}")
            lines.append(f"{indent}    _new_data = np.array({inp}.data)[:, _mask]")
            lines.append(
                f"{indent}    results['{self.node_id}'] = _Result("
                f"_new_data, x=type('Ax', (), {{'data': _x_vals[_mask]}}))"
            )
            lines.append(f"{indent}else:")
            # No axis info — integer column slicing fallback
            lo = int(min_wn) if min_wn is not None else 0
            hi = int(max_wn) if max_wn is not None else None
            hi_str = str(hi) if hi is not None else ""
            lines.append(f"{indent}    _new_data = np.array({inp}.data)[:, {lo}:{hi_str}]")
            lines.append(f"{indent}    results['{self.node_id}'] = _Result(_new_data)")
        return lines

    async def execute(self, input_data: Any) -> Any:
        """Execute wavenumber range clipping."""
        input_ds = coerce_to_sherpa(input_data, input_name="input_data")

        min_wn = self.parameters.get("min_wavenumber")
        max_wn = self.parameters.get("max_wavenumber")

        input_shape = input_ds.shape

        if min_wn is not None and max_wn is not None and min_wn > max_wn:
            min_wn, max_wn = max_wn, min_wn

        # Clip by x_axis values (wavenumber range)
        result = self._clip_by_index(input_ds, min_wn, max_wn)
        add_processing_step(
            result,
            "preprocess.clip_range",
            {"min_wavenumber": min_wn, "max_wavenumber": max_wn},
            node_id=self.node_id,
            input_shape=input_shape,
        )

        return result

    @staticmethod
    def _clip_by_index(ds: Any, min_wn, max_wn) -> Any:
        """Clip columns by x-axis values (wavenumber range) when available."""
        # SherpaDataset path (canonical)
        if hasattr(ds, "spectral_axis"):
            spectral_axis = ds.spectral_axis
            x_vals = spectral_axis.values if spectral_axis is not None else None

            if x_vals is None:
                lo = int(min_wn) if min_wn is not None else 0
                hi = int(max_wn) if max_wn is not None else ds.shape[1]
                return ds[:, lo:hi]

            mask = np.ones(len(x_vals), dtype=bool)
            if min_wn is not None:
                mask &= x_vals >= min_wn
            if max_wn is not None:
                mask &= x_vals <= max_wn
            return ds[:, mask]

        # Index-based fallback
        x_vals = None
        if hasattr(ds, "x") and ds.x is not None:
            x_vals = ds.x.data

        if x_vals is None:
            lo = int(min_wn) if min_wn is not None else 0
            hi = int(max_wn) if max_wn is not None else ds.shape[1]
            return ds[:, lo:hi]

        mask = np.ones(len(x_vals), dtype=bool)
        if min_wn is not None:
            mask &= x_vals >= min_wn
        if max_wn is not None:
            mask &= x_vals <= max_wn

        return ds[:, mask]


@register_node
class ClipFloorNode(TransformSpecNode):
    """
    Floor clipping node.

    Clips all values below a specified floor value.
    """

    metadata = NodeMetadata(
        node_type="preprocess.clip_floor",
        category="preprocessing",
        label="Clip Floor",
        description="Clip values below a specified floor (e.g., remove negative values)",
        parameters=[
            NodeParameter(
                name="floor",
                label="Floor Value",
                param_type="number",
                default=0.0,
                min_value=-10.0,
                max_value=10.0,
                step=0.001,
                description="Minimum value; all values below will be set to this",
                required=True,
            ),
        ],
        input_types=["NDDataset"],
        output_type="NDDataset",
    )

    spec = TransformSpec(
        transform_fn=lambda data, floor: np.maximum(data, floor),
        numpy_expr="np.maximum(_data, {floor})",
        extra_imports=["import numpy as np"],
    )


@register_node
class WavenumberAlignNode(Node):
    """
    Wavenumber alignment node.

    Aligns multiple spectra to a common wavenumber grid using interpolation.
    """

    metadata = NodeMetadata(
        node_type="preprocess.wavenumber_align",
        category="preprocessing",
        label="Wavenumber Align",
        description="Align spectra to a common wavenumber grid via interpolation",
        parameters=[
            NodeParameter(
                name="method",
                label="Interpolation Method",
                param_type="select",
                default="pchip",
                options=["pchip", "linear", "sinc"],
                description="Interpolation method (pchip: smooth, linear: fast, sinc: spectral)",
                required=True,
            ),
            NodeParameter(
                name="merge_tolerance",
                label="Merge Tolerance (cm⁻¹)",
                param_type="number",
                default=0.5,
                min_value=0.01,
                max_value=10.0,
                step=0.1,
                description="Tolerance for merging near-duplicate grid points",
                required=False,
            ),
        ],
        input_types=["NDDataset"],
        output_type="NDDataset",
    )

    python_extra_imports = [
        "import numpy as np",
        "from spectra_sherpa.app.lib.preprocessing import build_golden_grid, interpolate_to_grid",
    ]

    def generate_python(self, inputs, indent="    ", use_scp=True):
        inp = next(iter(inputs.values())) if inputs else "input_data"
        params = self._resolve_params()
        method = params.get("method", "pchip")
        merge_tol = params.get("merge_tolerance", 0.5)
        lines = [
            f"{indent}# --- Wavenumber Align ({self.node_id}) ---",
            f"{indent}_grid = build_golden_grid([{inp}], merge_tolerance={_format_value(merge_tol)})",
            f"{indent}results['{self.node_id}'] = interpolate_to_grid({inp}, _grid, method='{method}')",
        ]
        return lines

    async def execute(self, input_data: Any) -> SherpaDataset:
        """Execute wavenumber alignment via interpolation to a uniform grid."""
        from spectra_sherpa.app.lib.preprocessing import build_golden_grid, interpolate_to_grid

        method = self.parameters.get("method", "pchip")
        merge_tolerance = self.parameters.get("merge_tolerance", 0.5)

        # Build a clean uniform grid from the dataset's own x-axis
        target_grid = build_golden_grid([input_data], merge_tolerance=merge_tolerance)
        result = interpolate_to_grid(input_data, target_grid, method=method)

        copy_processing_history(input_data, result)
        add_processing_step(
            result,
            "preprocess.wavenumber_align",
            {"method": method, "merge_tolerance": merge_tolerance, "n_points": len(target_grid)},
            node_id=self.node_id,
        )

        return result


@register_node
class ScaleMaxNode(Node):
    """
    Scale to maximum node.

    Normalizes each spectrum so that its maximum value equals a target value.
    """

    metadata = NodeMetadata(
        node_type="preprocess.scale_max",
        category="preprocessing",
        label="Scale to Max",
        description="Normalize each spectrum to a target maximum value",
        parameters=[
            NodeParameter(
                name="target_max",
                label="Target Maximum",
                param_type="number",
                default=1.0,
                min_value=0.01,
                max_value=100.0,
                step=0.1,
                description="Target maximum absorbance value",
                required=True,
            ),
        ],
        input_types=["NDDataset"],
        output_type="NDDataset",
    )

    python_extra_imports = ["import numpy as np"]

    def generate_python(self, inputs, indent="    ", use_scp=True):
        inp = next(iter(inputs.values())) if inputs else "input_data"
        target = self._resolve_params().get("target_max", 1.0)
        return [
            f"{indent}# --- Scale to Max ({self.node_id}) ---",
            f"{indent}_data = np.array({inp}.data, dtype=np.float64)",
            f"{indent}if _data.ndim == 1:",
            f"{indent}    _cmax = np.abs(_data).max()",
            f"{indent}    if _cmax > 0: _data = _data * ({_format_value(target)} / _cmax)",
            f"{indent}else:",
            f"{indent}    _rmax = np.abs(_data).max(axis=1, keepdims=True)",
            f"{indent}    _rmax[_rmax == 0] = 1.0",
            f"{indent}    _data = _data * ({_format_value(target)} / _rmax)",
        ] + _wrap_result_lines(self.node_id, "_data", inp, indent, use_scp)

    async def execute(self, input_data: Any) -> SherpaDataset:
        """Execute scale to maximum normalization."""
        input_ds = coerce_to_sherpa(input_data, input_name="input_data")
        target_max = self.parameters.get("target_max", 1.0)

        data = to_numpy_2d(input_ds, name="input_data", dtype=np.float64)

        if data.ndim == 1:
            current_max = np.abs(data).max()
            if current_max > 0:
                data = data * (target_max / current_max)
        else:
            row_max = np.abs(data).max(axis=1, keepdims=True)
            row_max[row_max == 0] = 1.0
            data = data * (target_max / row_max)

        result = build_dataset_like(data, input_ds, units="normalized")
        add_processing_step(
            result,
            "preprocess.scale_max",
            {"target_max": target_max},
            node_id=self.node_id,
            state_effects=[EFFECT_SCALED],
        )

        return result


def _center_mean_export(params, inp, node_id, indent, use_scp):
    lines = [header_line("Mean Center", node_id, indent)]
    lines += extract_data_lines(inp, indent)
    lines += [
        f"{indent}if _data.ndim == 1:",
        f"{indent}    _data = _data - np.mean(_data)",
        f"{indent}else:",
        f"{indent}    _data = _data - np.mean(_data, axis=0)",
    ]
    lines += _wrap_result_lines(node_id, "_data", inp, indent, use_scp)
    return lines


@register_node
class CenterMeanNode(TransformSpecNode):
    """
    Mean centering node.

    Subtracts the mean spectrum from all spectra.
    """

    metadata = NodeMetadata(
        node_type="preprocess.center_mean",
        category="preprocessing",
        label="Mean Center",
        description="Subtract the mean spectrum from all spectra",
        parameters=[],
        input_types=["NDDataset"],
        output_type="NDDataset",
    )

    spec = TransformSpec(
        transform_fn=lambda data: data - np.mean(data, axis=0),
        export_lines_fn=_center_mean_export,
        extra_imports=["import numpy as np"],
    )


def _pareto_scale(data: np.ndarray, center: bool = True) -> np.ndarray:
    if center:
        data = data - np.mean(data, axis=0, keepdims=True)
    std = np.std(data, axis=0, keepdims=True)
    sf = np.sqrt(std)
    sf[sf == 0] = 1.0
    return data / sf


def _pareto_export(params, inp, node_id, indent, use_scp):
    center = params.get("center", True)
    lines = [header_line("Pareto Scaling", node_id, indent)]
    lines += extract_data_lines(inp, indent)
    if center:
        lines.append(f"{indent}_data = _data - np.mean(_data, axis=0, keepdims=True)")
    lines += [
        f"{indent}_std = np.std(np.array({inp}.data, dtype=np.float64), axis=0, keepdims=True)",
        f"{indent}_sf = np.sqrt(_std)",
        f"{indent}_sf[_sf == 0] = 1.0",
        f"{indent}_data = _data / _sf",
    ]
    lines += _wrap_result_lines(node_id, "_data", inp, indent, use_scp)
    return lines


@register_node
class ParetoScalingNode(TransformSpecNode):
    """
    Pareto Scaling node.

    Scales each variable by the square root of its standard deviation.
    """

    metadata = NodeMetadata(
        node_type="preprocess.pareto_scaling",
        category="preprocessing",
        label="Pareto Scaling",
        description="Scale by square root of standard deviation (chemometrics standard)",
        parameters=[
            NodeParameter(
                name="center",
                label="Mean Center",
                param_type="boolean",
                default=True,
                description="Subtract mean before scaling",
                required=False,
            ),
        ],
        input_types=["NDDataset"],
        output_type="NDDataset",
    )

    spec = TransformSpec(
        transform_fn=_pareto_scale,
        output_units="dimensionless",
        export_lines_fn=_pareto_export,
        extra_imports=["import numpy as np"],
    )


@register_node
class OSCNode(Node):
    """
    Orthogonal Signal Correction (OSC) node.

    Removes systematic variation in X that is orthogonal to Y.
    """

    metadata = NodeMetadata(
        node_type="preprocess.osc",
        category="preprocessing",
        label="OSC Filter",
        description="Orthogonal Signal Correction - remove variation uncorrelated with Y",
        parameters=[
            NodeParameter(
                name="n_components",
                label="Number of OSC Components",
                param_type="number",
                default=1,
                min_value=1,
                max_value=10,
                step=1,
                description="Number of orthogonal components to remove",
                required=True,
                category="basic",
            ),
            NodeParameter(
                name="tol",
                label="Convergence Tolerance",
                param_type="number",
                default=1e-6,
                min_value=1e-10,
                max_value=1e-3,
                step=1e-7,
                description="Tolerance for convergence",
                required=False,
                category="basic",
            ),
            NodeParameter(
                name="max_iter",
                label="Maximum Iterations",
                param_type="number",
                default=100,
                min_value=10,
                max_value=1000,
                step=10,
                description="Maximum iterations per component",
                required=False,
                category="advanced",
            ),
        ],
        input_types=["NDDataset", "array"],
        output_type="NDDataset",
        input_ports=[
            PortMetadata(
                name="X",
                type_ref="spectrasherpa://types/SpectralDataset/1.0",
                required=True,
                label="Spectra (X)",
                description="Spectral data matrix to correct",
            ),
            PortMetadata(
                name="y",
                type_ref="spectrasherpa://types/Array1D/1.0",
                required=True,
                label="Target (y)",
                description="Target values (concentrations, class labels, etc.)",
            ),
        ],
        requires_scp=True,
    )

    python_extra_imports = [
        "import numpy as np",
        "import spectrochempy as scp",
    ]

    def generate_python(self, inputs, indent="    ", use_scp=True):
        x_expr = inputs.get("X", "X")
        y_expr = inputs.get("y", "y")
        params = self._resolve_params()
        n_comp = params.get("n_components", 1)
        tol = params.get("tol", 1e-6)
        max_iter = params.get("max_iter", 100)
        return [
            f"{indent}# --- OSC Filter ({self.node_id}) ---",
            f"{indent}_X = np.array({x_expr}.data)",
            f"{indent}_y = np.array({y_expr}).reshape(-1, 1) if np.array({y_expr}).ndim == 1 else np.array({y_expr})",
            f"{indent}_X_osc = _X.copy()",
            f"{indent}for _comp in range({n_comp}):",
            f"{indent}    _Xd = scp.NDDataset(_X_osc)",
            f"{indent}    _yd = scp.NDDataset(_y)",
            f"{indent}    _pls = scp.PLSRegression(n_components=1, scale=False)",
            f"{indent}    _pls.fit(_Xd, _yd)",
            f"{indent}    _t = np.array(_pls.x_scores_)",
            f"{indent}    _w = np.array(_pls.x_weights_)",
            f"{indent}    for _ in range({max_iter}):",
            f"{indent}        _wosc = _X_osc.T @ (_X_osc @ _t.flatten())",
            f"{indent}        _wosc = _wosc.reshape(-1, 1)",
            f"{indent}        _wosc = _wosc - (_wosc.T @ _w) * _w",
            f"{indent}        _n = np.linalg.norm(_wosc)",
            f"{indent}        if _n < 1e-10: break",
            f"{indent}        _wosc = _wosc / _n",
            f"{indent}        _t_new = _X_osc @ _wosc",
            f"{indent}        if np.linalg.norm(_t_new - _t) < {_format_value(tol)}: break",
            f"{indent}        _t = _t_new",
            f"{indent}    _p = (_X_osc.T @ _t) / (_t.T @ _t)",
            f"{indent}    _X_osc = _X_osc - _t @ _p.T",
            f"{indent}results['{self.node_id}'] = scp.NDDataset(_X_osc)",
            f"{indent}if hasattr({x_expr}, 'x') and {x_expr}.x is not None:",
            f"{indent}    results['{self.node_id}'].x = {x_expr}.x.copy()",
        ]

    async def execute(self, X=None, y=None, **kwargs) -> SherpaDataset:
        """Execute OSC filtering."""
        X_ds = bind_X(
            X,
            kwargs,
            missing_message="Missing required input: X (spectra)",
            dataset_error_message="X must be a dataset object",
            allow_array=True,
        )
        y_value = bind_y(
            y,
            kwargs,
            X=X_ds,
            required=True,
            infer_from_X=False,
            dataset_as_data=True,
            missing_message="Missing required input: y (target)",
        )

        n_components = self.parameters.get("n_components", 1)
        tol = self.parameters.get("tol", 1e-6)
        max_iter = self.parameters.get("max_iter", 100)

        X_data = to_numpy_2d(X_ds, name="X", dtype=np.float64)
        y_data = to_numpy_1d(
            y_value,
            name="y",
            expected_length=X_data.shape[0],
            dtype=np.float64,
        ).reshape(-1, 1)
        y_dataset = scp.NDDataset(y_data)

        X_osc = X_data.copy()
        variance_removed_per_comp = []
        OSC_NORM_THRESHOLD = 1e-10

        for comp in range(n_components):
            X_osc_dataset = scp.NDDataset(X_osc)
            pls = scp.PLSRegression(n_components=1, scale=False)
            pls.fit(X_osc_dataset, y_dataset)

            t_pred = np.array(pls.x_scores_)
            x_weights = np.array(pls.x_weights_)

            t_osc_old = None

            for iteration in range(max_iter):
                w_osc = X_osc.T @ (X_osc @ t_pred.flatten())
                w_osc = w_osc.reshape(-1, 1)

                w_osc_initial_norm = np.linalg.norm(w_osc)
                if w_osc_initial_norm < OSC_NORM_THRESHOLD:
                    break

                x_weights_norm = np.linalg.norm(x_weights)
                if x_weights_norm > OSC_NORM_THRESHOLD:
                    projection = (w_osc.T @ x_weights) * x_weights
                    w_osc = w_osc - projection

                w_osc_norm = np.linalg.norm(w_osc)
                if w_osc_norm < OSC_NORM_THRESHOLD:
                    break
                w_osc = w_osc / w_osc_norm

                t_osc = X_osc @ w_osc

                if t_osc_old is not None and np.linalg.norm(t_osc - t_osc_old) < tol:
                    break
                t_osc_old = t_osc.copy()

            t_osc_norm_sq = t_osc.T @ t_osc
            if t_osc_norm_sq < OSC_NORM_THRESHOLD:
                continue
            p_osc = (X_osc.T @ t_osc) / t_osc_norm_sq

            var_before = np.var(X_osc)
            X_osc = X_osc - t_osc @ p_osc.T
            var_after = np.var(X_osc)
            var_removed = 100 * (1 - var_after / var_before) if var_before > 0 else 0
            variance_removed_per_comp.append(var_removed)

        total_var_original = np.var(X_data)
        total_var_corrected = np.var(X_osc)
        total_variance_removed = 100 * (1 - total_var_corrected / total_var_original) if total_var_original > 0 else 0

        result = build_dataset_like(X_osc, X_ds)
        add_processing_step(
            result,
            "preprocess.osc",
            {
                "n_components": n_components,
                "tol": tol,
                "max_iter": max_iter,
                "variance_removed_percent": total_variance_removed,
            },
            node_id=self.node_id,
            state_effects=[EFFECT_SCATTER_CORRECTED],
        )

        return result


def _autoscale(data: np.ndarray, center: bool = True) -> np.ndarray:
    if center:
        data = data - np.mean(data, axis=0, keepdims=True)
    std = np.std(data, axis=0, keepdims=True)
    std[std == 0] = 1.0
    return data / std


def _autoscale_export(params, inp, node_id, indent, use_scp):
    center = params.get("center", True)
    lines = [header_line("Autoscaling", node_id, indent)]
    lines += extract_data_lines(inp, indent)
    if center:
        lines.append(f"{indent}_data = _data - np.mean(_data, axis=0, keepdims=True)")
    lines += [
        f"{indent}_std = np.std(np.array({inp}.data, dtype=np.float64), axis=0, keepdims=True)",
        f"{indent}_std[_std == 0] = 1.0",
        f"{indent}_data = _data / _std",
    ]
    lines += _wrap_result_lines(node_id, "_data", inp, indent, use_scp)
    return lines


@register_node
class AutoscalingNode(TransformSpecNode):
    """
    Autoscaling (Unit Variance Scaling) node.

    Scales each variable to unit variance after mean centering.
    """

    metadata = NodeMetadata(
        node_type="preprocess.autoscaling",
        category="preprocessing",
        label="Autoscaling",
        description="Scale to unit variance (mean centering + standardization)",
        parameters=[
            NodeParameter(
                name="center",
                label="Mean Center",
                param_type="boolean",
                default=True,
                description="Subtract mean before scaling",
                required=False,
            ),
        ],
        input_types=["NDDataset"],
        output_type="NDDataset",
    )

    spec = TransformSpec(
        transform_fn=_autoscale,
        output_units="dimensionless",
        export_lines_fn=_autoscale_export,
        extra_imports=["import numpy as np"],
    )


@register_node
class SGDerivativeNode(Node):
    """
    Savitzky-Golay Derivative node.

    Combines smoothing and derivative calculation in a single operation.
    """

    metadata = NodeMetadata(
        node_type="preprocess.sg_derivative",
        category="preprocessing",
        label="SG Derivative",
        description="Savitzky-Golay smoothing + derivative (combined operation)",
        parameters=[
            NodeParameter(
                name="size",
                label="Window Size",
                param_type="number",
                default=11,
                min_value=3,
                max_value=51,
                step=2,
                description="Window size (must be odd number)",
                required=True,
            ),
            NodeParameter(
                name="order",
                label="Polynomial Order",
                param_type="number",
                default=2,
                min_value=1,
                max_value=5,
                step=1,
                description="Order of polynomial fit",
                required=True,
            ),
            NodeParameter(
                name="deriv",
                label="Derivative Order",
                param_type="select",
                default="1",
                options=["0", "1", "2"],
                description="Derivative order: 0 (smooth only), 1 (first), 2 (second)",
                required=True,
            ),
        ],
        input_types=["NDDataset"],
        output_type="NDDataset",
    )

    scp_method = "deriv"

    python_extra_imports = ["from scipy.signal import savgol_filter"]

    def generate_python(self, inputs, indent="    ", use_scp=True):
        inp = next(iter(inputs.values())) if inputs else "input_data"
        params = self._resolve_params()
        size = params.get("size", 11)
        order = params.get("order", 2)
        deriv_order = int(params.get("deriv", "1"))
        if use_scp:
            return [
                f"{indent}# --- SG Derivative ({self.node_id}) ---",
                f"{indent}data = {inp}.copy()",
                f"{indent}data.savgol(size={size}, order={order}, deriv={deriv_order})",
                f"{indent}results['{self.node_id}'] = data",
            ]
        return [
            f"{indent}# --- SG Derivative ({self.node_id}) ---",
            f"{indent}_data = np.array({inp}.data, dtype=np.float64)",
            f"{indent}if _data.ndim >= 2:",
            f"{indent}    _data = np.apply_along_axis("
            f"savgol_filter, -1, _data, window_length={size}, polyorder={order}, deriv={deriv_order})",
            f"{indent}else:",
            f"{indent}    _data = savgol_filter("
            f"_data, window_length={size}, polyorder={order}, deriv={deriv_order})",
        ] + _wrap_result_lines(self.node_id, "_data", inp, indent, use_scp)

    async def execute(self, input_data: Any) -> Any:
        """Execute Savitzky-Golay derivative."""
        size = self.parameters.get("size", 11)
        order = self.parameters.get("order", 2)
        deriv_order = int(self.parameters.get("deriv", "1"))

        if size % 2 == 0:
            size += 1

        input_ds = coerce_to_sherpa(input_data, input_name="input_data")
        from scipy.signal import savgol_filter

        raw = np.asarray(input_ds.data, dtype=np.float64)
        derived = (
            np.apply_along_axis(
                savgol_filter, -1, raw, window_length=int(size), polyorder=int(order), deriv=int(deriv_order)
            )
            if raw.ndim >= 2
            else savgol_filter(raw, window_length=int(size), polyorder=int(order), deriv=int(deriv_order))
        )
        result = build_dataset_like(derived, input_ds)

        # Update units
        if deriv_order > 0:
            original_units = str(input_ds.units) if getattr(input_ds, "units", None) else None
            x_units = input_ds.spectral_axis.units if input_ds.spectral_axis is not None else None

            if deriv_order == 1:
                if original_units and x_units and original_units != "dimensionless":
                    result.units = f"d({original_units})/d({x_units})"
                elif original_units and original_units != "dimensionless":
                    result.units = f"d({original_units})/dx"
                else:
                    result.units = "d/dx"
            elif deriv_order == 2:
                if original_units and x_units and original_units != "dimensionless":
                    result.units = f"d²({original_units})/d({x_units})²"
                elif original_units and original_units != "dimensionless":
                    result.units = f"d²({original_units})/dx²"
                else:
                    result.units = "d²/dx²"

        add_processing_step(
            result,
            "preprocess.sg_derivative",
            {"size": size, "order": order, "deriv": deriv_order},
            node_id=self.node_id,
            state_effects=[EFFECT_DERIVATIVE, EFFECT_SMOOTHED],
        )

        return result


@register_node
class EMSCNode(Node):
    """
    Extended Multiplicative Signal Correction (EMSC) node.

    Extends MSC by adding polynomial baseline correction and optional
    constituent spectra (interferents) to the design matrix.

    Design matrix: [reference | poly_1 .. poly_d | constituent_1 .. constituent_k]
    """

    metadata = NodeMetadata(
        node_type="preprocess.emsc",
        category="preprocessing",
        label="EMSC",
        description="Extended MSC with polynomial baseline and optional constituent spectra",
        parameters=[
            NodeParameter(
                name="reference",
                label="Reference Spectrum",
                param_type="select",
                default="mean",
                options=["mean", "median", "first"],
                description="Reference spectrum for EMSC",
                required=False,
            ),
            NodeParameter(
                name="poly_order",
                label="Polynomial Order",
                param_type="number",
                default=2,
                min_value=0,
                max_value=5,
                step=1,
                description="Order of polynomial baseline (0=no baseline correction)",
                required=False,
            ),
        ],
        input_types=["NDDataset"],
        output_type="NDDataset",
        input_ports=[
            PortMetadata(
                name="default",
                type_ref="spectrasherpa://types/SpectralDataset/1.0",
                required=True,
                label="Input Spectra",
                description="Spectral data to correct",
            ),
            PortMetadata(
                name="constituents",
                type_ref="spectrasherpa://types/SpectralDataset/1.0",
                required=False,
                label="Constituent Spectra",
                description="Known interferent/constituent spectra (rows = constituents, cols = wavenumbers)",
            ),
        ],
    )

    python_extra_imports = ["import numpy as np"]

    def generate_python(self, inputs, indent="    ", use_scp=True):
        inp = inputs.get("default", next(iter(inputs.values()))) if inputs else "input_data"
        const_inp = inputs.get("constituents")
        params = self._resolve_params()
        ref = params.get("reference", "mean")
        poly = params.get("poly_order", 2)
        lines = [
            f"{indent}# --- EMSC ({self.node_id}) ---",
            f"{indent}_data = np.array({inp}.data, dtype=np.float64)",
            f"{indent}_n, _p = _data.shape",
        ]
        if ref == "mean":
            lines.append(f"{indent}_ref = np.mean(_data, axis=0)")
        elif ref == "median":
            lines.append(f"{indent}_ref = np.median(_data, axis=0)")
        else:
            lines.append(f"{indent}_ref = _data[0]")
        lines.append(f"{indent}_design = [_ref]")
        if poly > 0:
            lines += [
                f"{indent}_x = np.arange(_p)",
                f"{indent}_xn = (_x - _x.mean()) / _x.std()",
            ]
            for deg in range(1, poly + 1):
                lines.append(f"{indent}_design.append(_xn ** {deg})")
        if const_inp:
            lines += [
                f"{indent}_const = np.array({const_inp}.data, dtype=np.float64)",
                f"{indent}if _const.ndim == 1: _const = _const.reshape(1, -1)",
                f"{indent}for _k in range(_const.shape[0]):",
                f"{indent}    _design.append(_const[_k])",
            ]
        lines += [
            f"{indent}_design = np.column_stack(_design)",
            f"{indent}_corrected = np.zeros_like(_data)",
            f"{indent}for _i in range(_n):",
            f"{indent}    _c, _, _, _ = np.linalg.lstsq(_design, _data[_i], rcond=None)",
            f"{indent}    _bl = _design[:, 1:] @ _c[1:] if _design.shape[1] > 1 else 0",
            f"{indent}    _corrected[_i] = (_data[_i] - _bl) / _c[0] if abs(_c[0]) > 1e-8 else _data[_i]",
        ]
        lines += _wrap_result_lines(self.node_id, "_corrected", inp, indent, use_scp)
        return lines

    async def execute(self, input_data=None, constituents=None, **kwargs) -> SherpaDataset:
        """Execute EMSC correction with optional constituent spectra."""
        input_data = resolve_legacy_input(input_data, kwargs, "default")
        input_ds = bind_X(
            input_data,
            kwargs,
            missing_message="Missing required input: input_data (spectra)",
            dataset_error_message="input_data must be a dataset object",
            allow_array=True,
        )
        constituents = resolve_legacy_input(constituents, kwargs, "input_1")

        reference_type = self.parameters.get("reference", "mean")
        poly_order = self.parameters.get("poly_order", 2)

        data = to_numpy_2d(input_ds, name="input_data", dtype=np.float64)
        n_samples, n_features = data.shape

        if reference_type == "mean":
            reference = np.mean(data, axis=0)
        elif reference_type == "median":
            reference = np.median(data, axis=0)
        elif reference_type == "first":
            reference = data[0]
        else:
            reference = np.mean(data, axis=0)

        # Build design matrix: [reference | poly_terms | constituents]
        X_design = [reference]
        if poly_order > 0:
            x_axis = np.arange(n_features)
            x_norm = (x_axis - x_axis.mean()) / x_axis.std()
            for deg in range(1, poly_order + 1):
                X_design.append(x_norm**deg)

        n_constituents = 0
        if constituents is not None:
            if isinstance(constituents, SherpaDataset):
                const_data = np.asarray(constituents.data, dtype=np.float64)
            elif HAS_SCP and isinstance(constituents, NDDataset):
                const_data = np.asarray(constituents.data, dtype=np.float64)
            else:
                const_data = np.asarray(constituents, dtype=np.float64)
            if const_data.ndim == 1:
                const_data = const_data.reshape(1, -1)
            elif const_data.ndim != 2:
                raise ValueError("constituents must be 1D or 2D array-like")
            n_constituents = const_data.shape[0]
            for k in range(n_constituents):
                X_design.append(const_data[k])

        X_design = np.column_stack(X_design)
        corrected_data = np.zeros_like(data)
        EMSC_COEF_THRESHOLD = 1e-8

        for i in range(n_samples):
            spectrum = data[i]
            coef, _, _, _ = np.linalg.lstsq(X_design, spectrum, rcond=None)

            # Baseline = everything except the reference coefficient
            if X_design.shape[1] > 1:
                baseline = X_design[:, 1:] @ coef[1:]
                if np.abs(coef[0]) > EMSC_COEF_THRESHOLD:
                    corrected_data[i] = (spectrum - baseline) / coef[0]
                else:
                    corrected_data[i] = spectrum
            else:
                if np.abs(coef[0]) > EMSC_COEF_THRESHOLD:
                    corrected_data[i] = spectrum / coef[0]
                else:
                    corrected_data[i] = spectrum

        result = build_dataset_like(corrected_data, input_ds)
        add_processing_step(
            result,
            "preprocess.emsc",
            {"reference": reference_type, "poly_order": poly_order, "n_constituents": n_constituents},
            node_id=self.node_id,
            state_effects=[EFFECT_SCATTER_CORRECTED],
        )

        return result


@register_node
class NorrisWilliamsDerivativeNode(Node):
    """
    Norris-Williams gap-segment derivative node.

    Computes derivatives using the gap-segment method, which is more robust
    to noise than point-wise finite differences. Widely used in NIR
    spectroscopy (Norris & Williams 1984).
    """

    metadata = NodeMetadata(
        node_type="preprocess.norris_williams",
        category="preprocessing",
        label="Norris-Williams Derivative",
        description="Gap-segment derivative (robust to noise, standard in NIR)",
        parameters=[
            NodeParameter(
                name="gap",
                label="Gap Size",
                param_type="number",
                default=5,
                min_value=1,
                max_value=50,
                step=1,
                description="Number of points between averaging segments",
                required=True,
                category="basic",
            ),
            NodeParameter(
                name="segment",
                label="Segment Size",
                param_type="number",
                default=5,
                min_value=1,
                max_value=50,
                step=1,
                description="Number of points to average in each segment",
                required=True,
                category="basic",
            ),
            NodeParameter(
                name="deriv",
                label="Derivative Order",
                param_type="select",
                default="1",
                options=["1", "2"],
                description="Derivative order: 1 (first) or 2 (second)",
                required=True,
            ),
        ],
        input_types=["NDDataset"],
        output_type="NDDataset",
    )

    python_extra_imports = [
        "import numpy as np",
        "from spectra_sherpa.app.lib.preprocessing import norris_williams",
    ]

    def generate_python(self, inputs, indent="    ", use_scp=True):
        inp = next(iter(inputs.values())) if inputs else "input_data"
        params = self._resolve_params()
        gap = params.get("gap", 5)
        segment = params.get("segment", 5)
        deriv = int(params.get("deriv", "1"))
        lines = [
            f"{indent}# --- Norris-Williams Derivative ({self.node_id}) ---",
            f"{indent}_data = np.array({inp}.data, dtype=np.float64)",
            f"{indent}_derived = norris_williams(_data, gap={gap}, segment={segment}, deriv={deriv})",
        ]
        lines += _wrap_result_lines(self.node_id, "_derived", inp, indent, use_scp)
        return lines

    async def execute(self, input_data: Any) -> SherpaDataset:
        """Execute Norris-Williams gap-segment derivative."""
        input_ds = coerce_to_sherpa(input_data, input_name="input_data")
        gap = self.parameters.get("gap", 5)
        segment = self.parameters.get("segment", 5)
        deriv_order = int(self.parameters.get("deriv", "1"))

        data = to_numpy_2d(input_ds, name="input_data", dtype=np.float64)
        derived = norris_williams(data, gap=gap, segment=segment, deriv=deriv_order)

        result = build_dataset_like(derived, input_ds)
        spectral = input_ds.spectral_axis

        # Update units for derivative
        try:
            original_units = str(input_ds.units) if hasattr(input_ds, "units") and input_ds.units else None
            x_units = spectral.units if spectral is not None else None
            if deriv_order == 1:
                if original_units and x_units and original_units != "dimensionless":
                    result.units = f"d({original_units})/d({x_units})"
                else:
                    result.units = "d/dx"
            elif deriv_order == 2:
                if original_units and x_units and original_units != "dimensionless":
                    result.units = f"d²({original_units})/d({x_units})²"
                else:
                    result.units = "d²/dx²"
        except Exception:
            pass

        add_processing_step(
            result,
            "preprocess.norris_williams",
            {"gap": gap, "segment": segment, "deriv": deriv_order},
            node_id=self.node_id,
            state_effects=[EFFECT_DERIVATIVE, EFFECT_SMOOTHED],
        )

        return result


@register_node
class SmoothWhittakerNode(Node):
    """
    Whittaker smoother node.

    Penalized least squares smoother (Eilers 2003). Minimises
    ||y - z||² + λ ||D^d z||². More flexible than Savitzky-Golay for
    unevenly spaced data and avoids window-size selection.
    """

    metadata = NodeMetadata(
        node_type="smooth.whittaker",
        category="preprocessing",
        label="Smooth (Whittaker)",
        description="Whittaker penalized least squares smoother",
        parameters=[
            NodeParameter(
                name="lam",
                label="Lambda (Smoothness)",
                param_type="number",
                default=1e2,
                min_value=1,
                max_value=1e8,
                description="Smoothness penalty (larger = smoother)",
                required=True,
                category="basic",
            ),
            NodeParameter(
                name="d",
                label="Difference Order",
                param_type="select",
                default="2",
                options=["1", "2", "3"],
                description="Order of the difference penalty (2 is standard)",
                required=False,
                category="advanced",
            ),
        ],
        input_types=["NDDataset"],
        output_type="NDDataset",
    )

    python_extra_imports = [
        "import numpy as np",
        "from spectra_sherpa.app.lib.preprocessing import whittaker_smooth",
    ]

    def generate_python(self, inputs, indent="    ", use_scp=True):
        inp = next(iter(inputs.values())) if inputs else "input_data"
        params = self._resolve_params()
        lam = params.get("lam", 1e2)
        d = int(params.get("d", "2"))
        lines = [
            f"{indent}# --- Whittaker Smoother ({self.node_id}) ---",
            f"{indent}_data = np.array({inp}.data, dtype=np.float64)",
            f"{indent}_smoothed = whittaker_smooth(_data, lam={_format_value(lam)}, d={d})",
        ]
        lines += _wrap_result_lines(self.node_id, "_smoothed", inp, indent, use_scp)
        return lines

    async def execute(self, input_data: Any) -> SherpaDataset:
        """Execute Whittaker smoothing."""
        input_ds = coerce_to_sherpa(input_data, input_name="input_data")
        lam = self.parameters.get("lam", 1e2)
        d = int(self.parameters.get("d", "2"))

        data = to_numpy_2d(input_ds, name="input_data", dtype=np.float64)
        smoothed = whittaker_smooth(data, lam=lam, d=d)

        result = build_dataset_like(smoothed, input_ds)
        add_processing_step(
            result,
            "smooth.whittaker",
            {"lam": lam, "d": d},
            node_id=self.node_id,
            state_effects=[EFFECT_SMOOTHED],
        )

        return result


@register_node
class SmoothGaussianNode(Node):
    """
    Gaussian smoothing node.

    Convolves the spectrum with a Gaussian kernel. Unlike Savitzky-Golay,
    Gaussian smoothing has no polynomial fitting and is parameterised by a
    single σ (standard deviation in data points).
    """

    metadata = NodeMetadata(
        node_type="smooth.gaussian",
        category="preprocessing",
        label="Smooth (Gaussian)",
        description="Gaussian kernel smoothing",
        parameters=[
            NodeParameter(
                name="sigma",
                label="Sigma (std dev)",
                param_type="number",
                default=2.0,
                min_value=0.1,
                max_value=50.0,
                step=0.1,
                description="Standard deviation of Gaussian kernel (in data points)",
                required=True,
                category="basic",
            ),
        ],
        input_types=["NDDataset"],
        output_type="NDDataset",
    )

    python_extra_imports = [
        "import numpy as np",
        "from scipy.ndimage import gaussian_filter1d",
    ]

    def generate_python(self, inputs, indent="    ", use_scp=True):
        inp = next(iter(inputs.values())) if inputs else "input_data"
        sigma = self._resolve_params().get("sigma", 2.0)
        lines = [
            f"{indent}# --- Gaussian Smoothing ({self.node_id}) ---",
            f"{indent}_data = np.array({inp}.data, dtype=np.float64)",
            f"{indent}if _data.ndim == 1:",
            f"{indent}    _smoothed = gaussian_filter1d(_data, sigma={_format_value(sigma)})",
            f"{indent}else:",
            f"{indent}    _smoothed = np.apply_along_axis(gaussian_filter1d, -1, _data, sigma={_format_value(sigma)})",
        ]
        lines += _wrap_result_lines(self.node_id, "_smoothed", inp, indent, use_scp)
        return lines

    async def execute(self, input_data: Any) -> SherpaDataset:
        """Execute Gaussian smoothing."""
        input_ds = coerce_to_sherpa(input_data, input_name="input_data")
        sigma = self.parameters.get("sigma", 2.0)

        data = to_numpy_2d(input_ds, name="input_data", dtype=np.float64)
        smoothed = gaussian_smooth(data, sigma=sigma)

        result = build_dataset_like(smoothed, input_ds)
        add_processing_step(
            result,
            "smooth.gaussian",
            {"sigma": sigma},
            node_id=self.node_id,
            state_effects=[EFFECT_SMOOTHED],
        )

        return result
