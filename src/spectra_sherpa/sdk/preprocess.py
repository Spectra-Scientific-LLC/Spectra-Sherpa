"""Preprocessing conveniences backed by the canonical typed DAG executor."""

from __future__ import annotations

from typing import Any

from .runtime import execute_operation


def _output(node_type: str, dataset: Any, parameters: dict[str, Any], *, reference: Any = None) -> Any:
    inputs = {"default": dataset}
    if reference is not None:
        inputs["reference"] = reference
    return execute_operation(node_type, parameters=parameters, inputs=inputs).output()


def snv(ds: Any) -> Any:
    """Standard normal variate normalization."""

    return _output("preprocess.normalize", ds, {"method": "snv"})


def msc(ds: Any, *, reference: str = "mean") -> Any:
    """Fit and apply canonical multiplicative scatter correction."""

    return _output("preprocess.msc", ds, {"reference_method": reference})


def savgol(ds: Any, *, window: int = 11, polyorder: int = 2, deriv: int = 0) -> Any:
    """Savitzky-Golay smoothing or derivative."""

    if isinstance(deriv, bool) or not isinstance(deriv, int) or deriv not in {0, 1, 2}:
        raise ValueError("Savitzky-Golay derivative order must be exactly 0, 1, or 2")
    if deriv == 0:
        return _output(
            "preprocess.smooth",
            ds,
            {"method": "savitzky_golay", "size": window, "order": polyorder},
        )
    return _output(
        "preprocess.derivative",
        ds,
        {
            "method": "savitzky_golay",
            "size": window,
            "order": polyorder,
            "deriv": str(deriv),
        },
    )


def baseline_als(
    ds: Any,
    *,
    lam: float = 1e5,
    p: float = 0.001,
    max_iter: int = 50,
    tol: float = 1e-6,
) -> Any:
    """Asymmetric least-squares baseline correction."""

    return _output(
        "baseline.penalized_ls",
        ds,
        {"method": "als", "lam": lam, "p": p, "max_iter": max_iter, "tol": tol},
    )


def mean_center(ds: Any, *, reference: Any = None) -> Any:
    """Mean-center data using either itself or a reference dataset."""

    return _output("preprocess.scale", ds, {"method": "mean_center"}, reference=reference)


def autoscale(ds: Any, *, center: bool = True, reference: Any = None) -> Any:
    """Autoscale data using either itself or a reference dataset."""

    return _output(
        "preprocess.scale",
        ds,
        {"method": "autoscale", "center": bool(center)},
        reference=reference,
    )


__all__ = [
    "snv",
    "msc",
    "savgol",
    "baseline_als",
    "mean_center",
    "autoscale",
]
