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

import logging
from typing import Any, Dict

import numpy as np

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Technology-aware baseline lambda defaults
# ---------------------------------------------------------------------------
# The ALS/ArPLS/AirPLS smoothness penalty λ is scale-dependent.  The table
# below gives recommended starting values by spectroscopic technique.
# Rationale:
#   NIR (broad, gentle baselines; 700 channels, A≈0–3):      λ = 1e6
#   Raman (fluorescence backdrop, sharp peaks; counts/AU):    λ = 1e5
#   FTIR (many points, slow baselines; A≈0–3):               λ = 1e7
#   OES (emission, minimal baseline; counts):                 λ = 1e4
#   Generic/unrecognised:                                     λ = 1e5
_BASELINE_LAMBDA_DEFAULT = 1e5  # node metadata default — "no technique set"

_LAMBDA_BY_TECHNIQUE: dict[str, float] = {
    "NIR": 1e6,
    "NEAR_INFRARED": 1e6,
    "RAMAN": 1e5,
    "FTIR": 1e7,
    "IR": 1e7,
    "MIR": 1e7,
    "OES": 1e4,
    "OPTICAL_EMISSION": 1e4,
}

from spectra_sherpa.app.lib.adapters.scp_adapter import scp_roundtrip
from spectra_sherpa.app.lib.preprocessing import (
    baseline_penalized_ls,
    gaussian_smooth,
    norris_williams,
    remove_cosmic_rays,
    whittaker_smooth,
)
from spectra_sherpa.app.lib.scp_compat import HAS_SCP, NDDataset, scp
from spectra_sherpa.app.lib.sherpa_dataset import (
    EFFECT_BASELINE_CORRECTED,
    EFFECT_DERIVATIVE,
    EFFECT_NORMALIZED,
    EFFECT_SCALED,
    EFFECT_SCATTER_CORRECTED,
    EFFECT_SMOOTHED,
    SherpaDataset,
)

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


def _baseline_pls_export(params, inp, node_id, indent, use_scp):
    method = params.get("method", "als")
    lam = params.get("lam", 1e5)
    p = params.get("p", 0.001)
    max_iter = params.get("max_iter", 50)
    tol = params.get("tol", 1e-6)
    lines = [
        f"{indent}# --- Baseline Penalized LS ({node_id}) ---",
        f"{indent}from spectra_sherpa.app.lib.preprocessing import baseline_penalized_ls",
    ]
    lines += extract_data_lines(inp, indent)
    lines.append(
        f"{indent}_corrected = baseline_penalized_ls("
        f"_data, method='{method}', lam={_format_value(lam)}, "
        f"p={_format_value(p)}, max_iter={max_iter}, "
        f"tol={_format_value(tol)})"
    )
    lines += _wrap_result_lines(node_id, "_corrected", inp, indent, use_scp)
    return lines


@register_node
class BaselinePenalizedLSNode(TransformSpecNode):
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
        description=(
            "Estimates and subtracts a smooth baseline using Asymmetric Least Squares (ALS), "
            "Asymmetrically Reweighted PLS (ArPLS), or Adaptive Iteratively Reweighted PLS (AirPLS). "
            "Lambda is auto-selected by spectroscopic technique when left at default: "
            "NIR → 1×10⁶, FTIR/IR → 1×10⁷, Raman → 1×10⁵, OES → 1×10⁴. "
            "ArPLS and AirPLS are more robust than ALS for spectra with many or broad peaks."
        ),
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
                description=(
                    "Smoothness penalty — larger values produce a smoother (flatter) baseline. "
                    "When left at the default (1×10⁵), the value is auto-selected by technique "
                    "(NIR: 1×10⁶, FTIR/IR: 1×10⁷, Raman: 1×10⁵, OES: 1×10⁴). "
                    "Set explicitly to override the auto-selected value."
                ),
                required=False,
                category="basic",
                hint=(
                    "If the corrected baseline still curves under peaks, increase λ. "
                    "If signal peaks are suppressed or flattened, decrease λ. "
                    "A factor of 10× change is a good starting step."
                ),
            ),
            NodeParameter(
                name="p",
                label="Asymmetry (p)",
                param_type="number",
                default=0.001,
                min_value=0.0001,
                max_value=0.1,
                step=0.0001,
                description="Asymmetry parameter (smaller = more asymmetric)",
                required=False,
                category="basic",
                visible_when={"method": ["als"]},
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

    spec = TransformSpec(
        transform_fn=baseline_penalized_ls,
        export_lines_fn=_baseline_pls_export,
        extra_imports=["import numpy as np", "from scipy import sparse"],
        state_effects=[EFFECT_BASELINE_CORRECTED],
    )

    async def execute(self, input_data: Any = None, **kwargs: Any) -> Any:
        """Override TransformSpecNode to apply technology-aware lambda defaults.

        When the user has not explicitly overridden the lambda parameter (i.e.
        it still equals the node's built-in default of 1e5), we substitute a
        technique-specific starting value read from ``_LAMBDA_BY_TECHNIQUE``.
        An explicit user value — even if it happens to equal a table entry —
        always takes precedence over the auto-selected value.
        """
        input_ds = coerce_to_sherpa(input_data, input_name="input_data")
        data = to_numpy_2d(input_ds, name="input_data", dtype=np.float64)

        params = self._resolve_params()
        user_lam = params.get("lam", _BASELINE_LAMBDA_DEFAULT)

        # Auto-select lambda when the user hasn't changed it from the node default
        effective_lam = user_lam
        technique_used: str | None = None
        if user_lam == _BASELINE_LAMBDA_DEFAULT:
            technique = None
            if isinstance(input_ds, SherpaDataset) and input_ds.domain is not None:
                technique = input_ds.domain.technique
            if technique:
                lookup = _LAMBDA_BY_TECHNIQUE.get(technique.upper().replace(" ", "_"))
                if lookup is not None:
                    effective_lam = lookup
                    technique_used = technique
                    logger.info(
                        "[Baseline] Auto-selected λ=%g for technique '%s'. "
                        "Set the Lambda parameter explicitly to override.",
                        effective_lam,
                        technique,
                    )

        result_data = baseline_penalized_ls(
            data,
            method=params.get("method", "als"),
            lam=effective_lam,
            p=params.get("p", 0.001),
            max_iter=params.get("max_iter", 50),
            tol=params.get("tol", 1e-6),
        )

        result = build_dataset_like(result_data, input_ds, units=None)
        recorded_params = dict(params)
        recorded_params["lam"] = effective_lam
        if technique_used:
            recorded_params["_lam_auto_technique"] = technique_used
        add_processing_step(
            result,
            self.metadata.node_type,
            recorded_params,
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
        requires_scp=True,
        help_url="https://www.spectrochempy.fr/reference/generated/spectrochempy.basc.html",
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


def _savgol_smooth(data: np.ndarray, size: int = 11, order: int = 2) -> np.ndarray:
    from scipy.signal import savgol_filter

    n_features = data.shape[-1]
    wl = min(int(size), n_features)
    if wl % 2 == 0:
        wl -= 1
    wl = max(wl, int(order) + 1)
    if wl % 2 == 0:
        wl += 1
    return np.apply_along_axis(savgol_filter, -1, data, window_length=wl, polyorder=int(order))


def _savgol_smooth_export(params, inp, node_id, indent, use_scp):
    size = params.get("size", 11)
    order = params.get("order", 2)
    if use_scp:
        return [
            f"{indent}# --- Smooth (Savitzky-Golay) ({node_id}) ---",
            f"{indent}data = {inp}.copy()",
            f"{indent}data.smooth(size={size}, order={order})",
            f"{indent}results['{node_id}'] = data",
        ]
    lines = [header_line("Smooth (Savitzky-Golay)", node_id, indent)]
    lines += extract_data_lines(inp, indent)
    lines += [
        f"{indent}if _data.ndim >= 2:",
        f"{indent}    _data = np.apply_along_axis("
        f"savgol_filter, -1, _data, window_length={size}, polyorder={order})",
        f"{indent}else:",
        f"{indent}    _data = savgol_filter(" f"_data, window_length={size}, polyorder={order})",
    ]
    lines += _wrap_result_lines(node_id, "_data", inp, indent, use_scp)
    return lines


def _snv_transform(data: np.ndarray) -> np.ndarray:
    mean_vals = np.mean(data, axis=1, keepdims=True)
    std_vals = np.std(data, axis=1, keepdims=True)
    std_vals[std_vals == 0] = 1.0
    return (data - mean_vals) / std_vals


def _snv_export(params, inp, node_id, indent, use_scp):
    lines = [header_line("SNV Normalization", node_id, indent)]
    lines += extract_data_lines(inp, indent)
    lines += [
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
    ]
    lines += _wrap_result_lines(node_id, "_data", inp, indent, use_scp)
    return lines


def _normalize_scale(data: np.ndarray, method: str = "max") -> np.ndarray:
    if method == "max":
        max_vals = np.abs(data).max(axis=-1, keepdims=True)
        max_vals[max_vals == 0] = 1
        return data / max_vals
    elif method == "area":
        areas = np.abs(data).sum(axis=-1, keepdims=True)
        areas[areas == 0] = 1
        return data / areas
    elif method == "minmax":
        min_vals = data.min(axis=-1, keepdims=True)
        max_vals = data.max(axis=-1, keepdims=True)
        range_vals = max_vals - min_vals
        range_vals[range_vals == 0] = 1
        return (data - min_vals) / range_vals
    return data


def _normalize_scale_export(params, inp, node_id, indent, use_scp):
    method = params.get("method", "max")
    lines = [header_line("Scale Normalization", node_id, indent)]
    lines += extract_data_lines(inp, indent)
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
    lines += _wrap_result_lines(node_id, "_data", inp, indent, use_scp)
    return lines


def _msc_transform(data: np.ndarray, reference: str = "mean") -> np.ndarray:
    if reference == "mean":
        ref_spectrum = np.mean(data, axis=0)
    elif reference == "median":
        ref_spectrum = np.median(data, axis=0)
    else:
        ref_spectrum = data[0]

    # Design matrix: [reference | ones] for linear regression
    A = np.vstack([ref_spectrum, np.ones(data.shape[1])]).T

    corrected = np.zeros_like(data)
    for i in range(data.shape[0]):
        m, c = np.linalg.lstsq(A, data[i], rcond=None)[0]
        if abs(m) > 1e-10:
            corrected[i] = (data[i] - c) / m
        else:
            corrected[i] = data[i]
    return corrected


def _msc_export(params, inp, node_id, indent, use_scp):
    ref = params.get("reference", "mean")
    lines = [header_line("MSC", node_id, indent)]
    lines += extract_data_lines(inp, indent)
    if ref == "mean":
        lines.append(f"{indent}_ref = np.mean(_data, axis=0)")
    elif ref == "median":
        lines.append(f"{indent}_ref = np.median(_data, axis=0)")
    else:
        lines.append(f"{indent}_ref = _data[0]")
    lines += [
        f"{indent}_A = np.vstack([_ref, np.ones(len(_ref))]).T",
        f"{indent}_corrected = np.zeros_like(_data)",
        f"{indent}for _i in range(_data.shape[0]):",
        f"{indent}    _m, _c = np.linalg.lstsq(_A, _data[_i], rcond=None)[0]",
        f"{indent}    _corrected[_i] = (_data[_i] - _c) / _m if abs(_m) > 1e-10 else _data[_i]",
    ]
    lines += _wrap_result_lines(node_id, "_corrected", inp, indent, use_scp)
    return lines


def _savgol_deriv(data: np.ndarray, size: int = 11, order: int = 2, deriv: int = 1) -> np.ndarray:
    from scipy.signal import savgol_filter

    return np.apply_along_axis(savgol_filter, -1, data, window_length=int(size), polyorder=int(order), deriv=int(deriv))


def _deriv_export(label, deriv_order, params, inp, node_id, indent, use_scp):
    size = params.get("size", 11)
    order = params.get("order", 2)
    if use_scp:
        return [
            f"{indent}# --- {label} ({node_id}) ---",
            f"{indent}data = {inp}.copy()",
            f"{indent}data.savgol(size={size}, order={order}, deriv={deriv_order})",
            f"{indent}results['{node_id}'] = data",
        ]
    lines = [header_line(label, node_id, indent)]
    lines += extract_data_lines(inp, indent)
    lines += [
        f"{indent}if _data.ndim >= 2:",
        f"{indent}    _data = np.apply_along_axis("
        f"savgol_filter, -1, _data, window_length={size}, polyorder={order}, deriv={deriv_order})",
        f"{indent}else:",
        f"{indent}    _data = savgol_filter(" f"_data, window_length={size}, polyorder={order}, deriv={deriv_order})",
    ]
    lines += _wrap_result_lines(node_id, "_data", inp, indent, use_scp)
    return lines


def _update_derivative_units(result, input_ds, deriv_order: int):
    """Update output units for derivative results."""
    try:
        original_units = str(input_ds.units) if getattr(input_ds, "units", None) else None
        x_units = input_ds.feature_axis.units if input_ds.feature_axis is not None else None

        if deriv_order == 1:
            if original_units and x_units and original_units != "dimensionless":
                result.units = f"d({original_units})/d({x_units})"
            elif original_units and original_units != "dimensionless":
                result.units = f"d({original_units})/dx"
        elif deriv_order == 2:
            if original_units and x_units and original_units != "dimensionless":
                result.units = f"d²({original_units})/d({x_units})²"
            elif original_units and original_units != "dimensionless":
                result.units = f"d²({original_units})/dx²"
    except Exception:
        pass  # leave units unchanged if assignment fails


# ============================================================================
# ATOMIC PREPROCESSING NODES
# ============================================================================


def _cosmic_ray_transform(data: np.ndarray, window: int = 7, zscore: float = 3.0) -> np.ndarray:
    window = int(window)
    if window % 2 == 0:
        window += 1
    half_window = window // 2
    result = data.copy()
    n_samples, n_points = result.shape
    for i in range(n_samples):
        spectrum = result[i].copy()
        for j in range(n_points):
            start = max(0, j - half_window)
            end = min(n_points, j + half_window + 1)
            win = spectrum[start:end]
            median_val = float(np.median(win))
            mad = float(np.median(np.abs(win - median_val)))
            if mad < 1e-10:
                continue
            z = (spectrum[j] - median_val) / (mad * 1.4826)
            if abs(z) > zscore:
                result[i, j] = median_val
    return result


def _cosmic_ray_export(params, inp, node_id, indent, use_scp):
    window = params.get("window", 7)
    zscore = params.get("zscore", 3.0)
    return [
        f"{indent}# --- Cosmic Ray Removal ({node_id}) ---",
        f"{indent}from scipy.ndimage import median_filter",
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
    ] + _wrap_result_lines(node_id, "_data", inp, indent, use_scp)


@register_node
class CosmicRayRemovalNode(TransformSpecNode):
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

    spec = TransformSpec(
        transform_fn=_cosmic_ray_transform,
        export_lines_fn=_cosmic_ray_export,
        extra_imports=["import numpy as np", "from scipy.ndimage import median_filter"],
    )


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
            if use_scp:
                lines.append(f"{indent}    results['{self.node_id}'] = scp.NDDataset(_new_data)")
                lines.append(f"{indent}    if hasattr({inp}, 'x') and {inp}.x is not None:")
                lines.append(f"{indent}        results['{self.node_id}'].x = {inp}.x[_mask]")
            else:
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
            if use_scp:
                lines.append(f"{indent}    results['{self.node_id}'] = scp.NDDataset(_new_data)")
            else:
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
        if hasattr(ds, "feature_axis"):
            feature_axis = ds.feature_axis
            x_vals = feature_axis.values if feature_axis is not None else None

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

        return result  # type: ignore[no-any-return]


def _scale_max_transform(data: np.ndarray, target_max: float = 1.0) -> np.ndarray:
    row_max = np.abs(data).max(axis=1, keepdims=True)
    row_max[row_max == 0] = 1.0
    return data * (target_max / row_max)


def _scale_max_export(params, inp, node_id, indent, use_scp):
    target = params.get("target_max", 1.0)
    return [
        f"{indent}# --- Scale to Max ({node_id}) ---",
        f"{indent}_data = np.array({inp}.data, dtype=np.float64)",
        f"{indent}if _data.ndim == 1:",
        f"{indent}    _cmax = np.abs(_data).max()",
        f"{indent}    if _cmax > 0: _data = _data * ({_format_value(target)} / _cmax)",
        f"{indent}else:",
        f"{indent}    _rmax = np.abs(_data).max(axis=1, keepdims=True)",
        f"{indent}    _rmax[_rmax == 0] = 1.0",
        f"{indent}    _data = _data * ({_format_value(target)} / _rmax)",
    ] + _wrap_result_lines(node_id, "_data", inp, indent, use_scp)


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
                type_ref="spectrasherpa://types/TargetMatrix/1.0",
                required=False,
                label="Target (y)",
                description="Target values — optional if dataset has embedded target",
            ),
        ],
        requires_scp=True,
        help_url="https://www.spectrochempy.fr/reference/generated/spectrochempy.PLSRegression.html",
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
            missing_message="Missing required input: X (spectra)",
            dataset_error_message="X must be a dataset object",
            allow_array=True,
        )
        y_value = bind_y(
            y,
            X=X_ds,
            required=True,
            infer_from_X=True,
            dataset_as_data=True,
            missing_message=(
                "No target values found. Either:\n"
                "  1. Use a data source with embedded targets (e.g., Corn M5, sklearn)\n"
                "  2. Connect target values to the 'y' input port\n"
                "  3. Use 'Attach Target' node to add targets to your dataset"
            ),
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


def _sg_deriv_transform(data: np.ndarray, size: int = 11, order: int = 2, deriv: str = "1") -> np.ndarray:
    size = int(size)
    if size % 2 == 0:
        size += 1
    return _savgol_deriv(data, size=size, order=int(order), deriv=int(deriv))


def _sg_deriv_export(params, inp, node_id, indent, use_scp):
    deriv_order = int(params.get("deriv", "1"))
    return _deriv_export("SG Derivative", deriv_order, params, inp, node_id, indent, use_scp)


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
        # Design matrix: [poly_terms (incl. constant) | reference | constituents]
        lines += [
            f"{indent}_x = np.arange(_p, dtype=np.float64)",
            f"{indent}_xn = (_x - _x.mean()) / _x.std() if _p > 1 else _x",
            f"{indent}_design = [_xn ** _d for _d in range({poly} + 1)]",
            f"{indent}_ref_col = len(_design)",
            f"{indent}_design.append(_ref)",
        ]
        if const_inp:
            lines += [
                f"{indent}_const = np.array({const_inp}.data, dtype=np.float64)",
                f"{indent}if _const.ndim == 1: _const = _const.reshape(1, -1)",
                f"{indent}for _k in range(_const.shape[0]):",
                f"{indent}    _design.append(_const[_k])",
            ]
        lines += [
            f"{indent}_design = np.column_stack(_design)",
            f"{indent}_bl_cols = [_j for _j in range(_design.shape[1]) if _j != _ref_col]",
            f"{indent}_corrected = np.zeros_like(_data)",
            f"{indent}for _i in range(_n):",
            f"{indent}    _c, _, _, _ = np.linalg.lstsq(_design, _data[_i], rcond=None)",
            f"{indent}    _bl = _design[:, _bl_cols] @ _c[_bl_cols] if _bl_cols else 0",
            f"{indent}    _corrected[_i] = (_data[_i] - _bl) / _c[_ref_col] if abs(_c[_ref_col]) > 1e-8 else _data[_i]",
        ]
        lines += _wrap_result_lines(self.node_id, "_corrected", inp, indent, use_scp)
        return lines

    async def execute(self, input_data=None, constituents=None, **kwargs) -> SherpaDataset:
        """Execute EMSC correction with optional constituent spectra."""
        input_ds = bind_X(
            input_data,
            missing_message="Missing required input: input_data (spectra)",
            dataset_error_message="input_data must be a dataset object",
            allow_array=True,
        )
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

        # Build design matrix: [poly_terms (incl. constant) | reference | constituents]
        # Column order: [1, x, x^2, ..., x^d, reference, constituent_1, ...]
        # The reference coefficient is at index poly_order+1 (last non-constituent).
        X_design: list[np.ndarray] = []
        x_axis = np.arange(n_features, dtype=np.float64)
        x_norm = (x_axis - x_axis.mean()) / x_axis.std() if n_features > 1 else x_axis
        for deg in range(poly_order + 1):
            X_design.append(x_norm**deg)
        ref_col_idx = len(X_design)  # index of the reference column
        X_design.append(reference)

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

        X_design_arr: np.ndarray = np.column_stack(X_design)
        corrected_data = np.zeros_like(data)
        EMSC_COEF_THRESHOLD = 1e-8

        # Mask for non-reference columns (polynomial + constituent terms = baseline)
        n_cols = X_design_arr.shape[1]
        baseline_cols = [j for j in range(n_cols) if j != ref_col_idx]

        for i in range(n_samples):
            spectrum = data[i]
            coef, _, _, _ = np.linalg.lstsq(X_design_arr, spectrum, rcond=None)

            # Baseline = polynomial + constituent contributions (everything except reference)
            if baseline_cols:
                baseline = X_design_arr[:, baseline_cols] @ coef[baseline_cols]
                if np.abs(coef[ref_col_idx]) > EMSC_COEF_THRESHOLD:
                    corrected_data[i] = (spectrum - baseline) / coef[ref_col_idx]
                else:
                    corrected_data[i] = spectrum
            else:
                if np.abs(coef[ref_col_idx]) > EMSC_COEF_THRESHOLD:
                    corrected_data[i] = spectrum / coef[ref_col_idx]
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


# ──────────────────────────────────────────────────────────────────────
# Consolidated preprocessing nodes
# ──────────────────────────────────────────────────────────────────────


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
                max_value=51,
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
                max_value=5,
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
        smoothed = _smooth_dispatch(data, **params)
        result = build_dataset_like(smoothed, input_ds)
        add_processing_step(
            result,
            "preprocess.smooth",
            params,
            node_id=self.node_id,
            state_effects=[EFFECT_SMOOTHED],
        )
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
                type_ref="spectrasherpa://types/SpectralDataset/1.0",
                required=True,
                label="Input Spectra",
                description="Spectral data to process",
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

        add_processing_step(
            result,
            "preprocess.normalize",
            params,
            node_id=self.node_id,
            state_effects=effects,
        )

        # SNV diagnostics
        if method == "snv":
            after = np.asarray(result.data, dtype=np.float64)
            eps = 1e-12
            snr_before = float(np.mean(np.abs(data)) / (np.std(data) + eps))
            snr_after = float(np.mean(np.abs(after)) / (np.std(after) + eps))
            return NodeResult(
                outputs={"default": result},
                diagnostics={
                    "snr_before": snr_before,
                    "snr_after": snr_after,
                    "mean_spectrum_shift": float(np.mean(after) - np.mean(data)),
                    "max_absolute_change": float(np.max(np.abs(after - data))),
                },
            )
        return result

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
) -> np.ndarray:
    if method == "mean_center":
        return data - np.mean(data, axis=0)
    elif method == "autoscale":
        return _autoscale(data, center=center)
    elif method == "pareto":
        return _pareto_scale(data, center=center)
    elif method == "scale_max":
        return _scale_max_transform(data, target_max=target_max)
    raise ValueError(f"Unknown scaling method: {method}")


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
                max_value=100.0,
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
        scaled = _scale_dispatch(data, **params)
        result = build_dataset_like(scaled, input_ds)

        method = params.get("method", "mean_center")
        if method in ("autoscale", "pareto"):
            result.units = "dimensionless"
        elif method == "scale_max":
            result.units = "normalized"

        effects = [EFFECT_SCALED] if method != "mean_center" else []
        add_processing_step(
            result,
            "preprocess.scale",
            params,
            node_id=self.node_id,
            state_effects=effects,
        )
        return result

    def supports_python_export(self) -> bool:
        return True

    def generate_python(self, inputs, indent="    ", use_scp=True):
        inp = next(iter(inputs.values())) if inputs else "input_data"
        params = self._resolve_params()
        method = params.get("method", "mean_center")
        if method == "mean_center":
            return _center_mean_export(params, inp, self.node_id, indent, use_scp)
        elif method == "autoscale":
            return _autoscale_export(params, inp, self.node_id, indent, use_scp)
        elif method == "pareto":
            return _pareto_export(params, inp, self.node_id, indent, use_scp)
        elif method == "scale_max":
            return _scale_max_export(params, inp, self.node_id, indent, use_scp)
        return [f"{indent}# TODO: scale method '{method}' export not implemented"]
