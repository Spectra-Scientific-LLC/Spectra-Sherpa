"""Python-callable preprocessing wrappers aligned with GUI DAG nodes."""

from __future__ import annotations

from typing import Any

import numpy as np

from spectra_sherpa.app.lib.sherpa_dataset import (
    EFFECT_BASELINE_CORRECTED,
    EFFECT_DERIVATIVE,
    EFFECT_MEAN_CENTERED,
    EFFECT_NORMALIZED,
    EFFECT_SCALED,
    EFFECT_SCATTER_CORRECTED,
    EFFECT_SMOOTHED,
    SherpaDataset,
)
from spectra_sherpa.app.services.dag.io_contracts import build_dataset_like, coerce_to_sherpa, to_numpy_2d
from spectra_sherpa.app.services.dag.meta_helpers import add_processing_step


def _dataset(value: Any) -> SherpaDataset:
    return coerce_to_sherpa(value, input_name="dataset", allow_array=True)


def _wrap(
    source: SherpaDataset,
    result: np.ndarray,
    *,
    op_id: str,
    params: dict[str, Any],
    effects: list[str],
    units: str | None = None,
) -> SherpaDataset:
    out = build_dataset_like(result, source, units=units)
    add_processing_step(out, op_id, params, input_shape=tuple(source.shape), state_effects=effects)
    return out


def snv(ds: Any) -> SherpaDataset:
    """Standard normal variate normalization."""
    from spectra_sherpa.app.services.dag.nodes.preprocessing.normalize_scale_nodes import _normalize_dispatch

    source = _dataset(ds)
    data = to_numpy_2d(source, name="dataset")
    params = {"method": "snv"}
    result = _normalize_dispatch(data, **params)
    return _wrap(
        source,
        result,
        op_id="preprocess.normalize",
        params=params,
        effects=[EFFECT_NORMALIZED, EFFECT_SCATTER_CORRECTED],
        units="dimensionless",
    )


def msc(ds: Any, *, reference: str = "mean") -> SherpaDataset:
    """Multiplicative scatter correction."""
    from spectra_sherpa.app.services.dag.nodes.preprocessing.normalize_scale_nodes import _normalize_dispatch

    source = _dataset(ds)
    data = to_numpy_2d(source, name="dataset")
    params = {"method": "msc", "reference": reference}
    result = _normalize_dispatch(data, **params)
    return _wrap(
        source,
        result,
        op_id="preprocess.normalize",
        params=params,
        effects=[EFFECT_NORMALIZED, EFFECT_SCATTER_CORRECTED],
        units=source.units,
    )


def savgol(ds: Any, *, window: int = 15, polyorder: int = 2, deriv: int = 0) -> SherpaDataset:
    """Savitzky-Golay smoothing or derivative."""
    from spectra_sherpa.app.services.dag.nodes.preprocessing.smooth_deriv_nodes import (
        _derivative_dispatch,
        _smooth_dispatch,
    )

    source = _dataset(ds)
    data = to_numpy_2d(source, name="dataset")
    base_params = {"method": "savitzky_golay", "size": int(window), "order": int(polyorder)}
    if int(deriv) == 0:
        result = _smooth_dispatch(data, **base_params)
        return _wrap(
            source,
            result,
            op_id="preprocess.smooth",
            params=base_params,
            effects=[EFFECT_SMOOTHED],
            units=source.units,
        )

    params = {**base_params, "deriv": str(int(deriv))}
    result = _derivative_dispatch(data, **params)
    return _wrap(
        source,
        result,
        op_id="preprocess.derivative",
        params=params,
        effects=[EFFECT_DERIVATIVE],
        units=source.units,
    )


def baseline_als(
    ds: Any,
    *,
    lam: float = 1e5,
    p: float = 0.01,
    max_iter: int = 50,
    tol: float = 1e-6,
) -> SherpaDataset:
    """Asymmetric least-squares baseline correction."""
    from spectra_sherpa.app.lib.preprocessing import baseline_penalized_ls

    source = _dataset(ds)
    data = to_numpy_2d(source, name="dataset")
    params = {"method": "als", "lam": float(lam), "p": float(p), "max_iter": int(max_iter), "tol": float(tol)}
    result = baseline_penalized_ls(data, **params)
    return _wrap(
        source,
        result,
        op_id="baseline.penalized_ls",
        params=params,
        effects=[EFFECT_BASELINE_CORRECTED],
        units=source.units,
    )


def mean_center(ds: Any, *, reference: Any = None) -> SherpaDataset:
    """Mean-center data using either itself or a reference dataset."""
    from spectra_sherpa.app.services.dag.nodes.preprocessing.normalize_scale_nodes import _scale_dispatch

    source = _dataset(ds)
    ref = _dataset(reference) if reference is not None else None
    data = to_numpy_2d(source, name="dataset")
    ref_data = to_numpy_2d(ref, name="reference") if ref is not None else None
    params = {"method": "mean_center"}
    result = _scale_dispatch(data, reference_data=ref_data, **params)
    return _wrap(
        source,
        result,
        op_id="preprocess.scale",
        params=params,
        effects=[EFFECT_MEAN_CENTERED],
        units=source.units,
    )


def autoscale(ds: Any, *, center: bool = True, reference: Any = None) -> SherpaDataset:
    """Autoscale data using either itself or a reference dataset."""
    from spectra_sherpa.app.services.dag.nodes.preprocessing.normalize_scale_nodes import _scale_dispatch

    source = _dataset(ds)
    ref = _dataset(reference) if reference is not None else None
    data = to_numpy_2d(source, name="dataset")
    ref_data = to_numpy_2d(ref, name="reference") if ref is not None else None
    params = {"method": "autoscale", "center": bool(center)}
    result = _scale_dispatch(data, reference_data=ref_data, **params)
    effects = [EFFECT_SCALED]
    if center:
        effects.append(EFFECT_MEAN_CENTERED)
    return _wrap(
        source,
        result,
        op_id="preprocess.scale",
        params=params,
        effects=effects,
        units=source.units,
    )


__all__ = [
    "snv",
    "msc",
    "savgol",
    "baseline_als",
    "mean_center",
    "autoscale",
]
