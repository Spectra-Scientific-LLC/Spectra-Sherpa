"""
Pure numpy transform functions and their export helpers for preprocessing nodes.
"""

from __future__ import annotations

import numpy as np

from ._shared import (
    _format_value,
    _wrap_result_lines,
    extract_data_lines,
    header_line,
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
    std_vals[(std_vals == 0) | ~np.isfinite(std_vals)] = 1.0
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
                result.units = f"d\u00b2({original_units})/d({x_units})\u00b2"
            elif original_units and original_units != "dimensionless":
                result.units = f"d\u00b2({original_units})/dx\u00b2"
    except Exception:
        pass  # leave units unchanged if assignment fails


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


def _center_mean_export(params, inp, node_id, indent, use_scp, reference_expr=None):
    lines = [header_line("Mean Center", node_id, indent)]
    lines += extract_data_lines(inp, indent)
    ref_expr = reference_expr or inp
    lines += [
        f"{indent}_center_ref = {ref_expr}",
        f"{indent}_center_ref_data = np.asarray(",
        f"{indent}    _center_ref.data if hasattr(_center_ref, 'data') else _center_ref,",
        f"{indent}    dtype=np.float64,",
        f"{indent})",
    ]
    lines += [
        f"{indent}if _data.ndim == 1:",
        f"{indent}    _data = _data - np.mean(_center_ref_data)",
        f"{indent}else:",
        f"{indent}    _data = _data - np.mean(_center_ref_data, axis=0)",
    ]
    lines += _wrap_result_lines(node_id, "_data", inp, indent, use_scp)
    return lines


def _pareto_scale(data: np.ndarray, center: bool = True) -> np.ndarray:
    if center:
        data = data - np.mean(data, axis=0, keepdims=True)
    std = np.std(data, axis=0, keepdims=True)
    sf = np.sqrt(np.maximum(std, 0))
    sf[(sf == 0) | ~np.isfinite(sf)] = 1.0
    return data / sf


def _pareto_export(params, inp, node_id, indent, use_scp, reference_expr=None):
    center = params.get("center", True)
    lines = [header_line("Pareto Scaling", node_id, indent)]
    lines += extract_data_lines(inp, indent)
    ref_expr = reference_expr or inp
    lines += [
        f"{indent}_pareto_ref = {ref_expr}",
        f"{indent}_pareto_ref_data = np.asarray(",
        f"{indent}    _pareto_ref.data if hasattr(_pareto_ref, 'data') else _pareto_ref,",
        f"{indent}    dtype=np.float64,",
        f"{indent})",
    ]
    if center:
        lines.append(f"{indent}_data = _data - np.mean(_pareto_ref_data, axis=0, keepdims=True)")
    lines += [
        f"{indent}_std = np.std(_pareto_ref_data, axis=0, keepdims=True)",
        f"{indent}_sf = np.sqrt(_std)",
        f"{indent}_sf[_sf == 0] = 1.0",
        f"{indent}_data = _data / _sf",
    ]
    lines += _wrap_result_lines(node_id, "_data", inp, indent, use_scp)
    return lines


def _autoscale(data: np.ndarray, center: bool = True) -> np.ndarray:
    if center:
        data = data - np.mean(data, axis=0, keepdims=True)
    std = np.std(data, axis=0, keepdims=True)
    std[(std == 0) | ~np.isfinite(std)] = 1.0
    return data / std


def _autoscale_export(params, inp, node_id, indent, use_scp, reference_expr=None):
    center = params.get("center", True)
    lines = [header_line("Autoscaling", node_id, indent)]
    lines += extract_data_lines(inp, indent)
    ref_expr = reference_expr or inp
    lines += [
        f"{indent}_scale_ref = {ref_expr}",
        f"{indent}_scale_ref_data = np.asarray(",
        f"{indent}    _scale_ref.data if hasattr(_scale_ref, 'data') else _scale_ref,",
        f"{indent}    dtype=np.float64,",
        f"{indent})",
    ]
    if center:
        lines.append(f"{indent}_data = _data - np.mean(_scale_ref_data, axis=0, keepdims=True)")
    lines += [
        f"{indent}_std = np.std(_scale_ref_data, axis=0, keepdims=True)",
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
