"""
Catmull-Rom curve utilities for concentration profile generation.

PRESERVED FROM project0/curves.py

These utilities support the interactive curve designer for creating
smooth concentration profiles in synthetic data generation.
"""

from __future__ import annotations

from typing import Dict, List, Optional

import numpy as np


def initial_curve_points(count: int = 11) -> List[Dict[str, float]]:
    """
    Return evenly spaced Catmull-Rom control points spanning 0-100.

    Parameters
    ----------
    count : int
        Number of control points (minimum 4)

    Returns
    -------
    list[dict]
        Control points with 'x' and 'y' keys
    """
    count = max(4, int(count))
    x_vals = np.linspace(0.0, 100.0, count)
    y_vals = 0.5 + 0.35 * np.sin((x_vals / 100.0) * np.pi - np.pi / 2)
    y_vals = np.clip(y_vals, 0.0, 1.0)
    return [{"x": float(x), "y": float(y)} for x, y in zip(x_vals, y_vals)]


def catmull_rom_coefficients(p0: float, p1: float, p2: float, p3: float) -> List[float]:
    """
    Return cubic coefficients for a Catmull-Rom segment.

    The Catmull-Rom spline passes through control points p1 and p2,
    using p0 and p3 to determine tangent directions.

    Parameters
    ----------
    p0, p1, p2, p3 : float
        Four consecutive control point values

    Returns
    -------
    list[float]
        Coefficients [a, b, c, d] for a + b*t + c*t² + d*t³
    """
    return [
        0.5 * (2 * p1),
        0.5 * (-p0 + p2),
        0.5 * (2 * p0 - 5 * p1 + 4 * p2 - p3),
        0.5 * (-p0 + 3 * p1 - 3 * p2 + p3),
    ]


def curve_segments(points: List[Dict[str, float]]) -> List[Dict[str, object]]:
    """
    Convert control points to Catmull-Rom spline segment coefficients.

    Parameters
    ----------
    points : list[dict]
        Control points with 'x' and 'y' keys

    Returns
    -------
    list[dict]
        Segment definitions with startX, endX, xCoeffs, yCoeffs
    """
    if len(points) < 2:
        return []

    segments: List[Dict[str, object]] = []
    for idx in range(len(points) - 1):
        p0 = points[max(0, idx - 1)]
        p1 = points[idx]
        p2 = points[idx + 1]
        p3 = points[min(len(points) - 1, idx + 2)]
        segments.append(
            {
                "startX": p1["x"],
                "endX": p2["x"],
                "xCoeffs": catmull_rom_coefficients(p0["x"], p1["x"], p2["x"], p3["x"]),
                "yCoeffs": catmull_rom_coefficients(p0["y"], p1["y"], p2["y"], p3["y"]),
            }
        )
    return segments


def evaluate_catmull_rom(
    points: List[Dict[str, float]],
    n_samples: int = 100,
) -> np.ndarray:
    """
    Evaluate Catmull-Rom spline at evenly spaced points.

    Parameters
    ----------
    points : list[dict]
        Control points with 'x' and 'y' keys (x in range 0-100)
    n_samples : int
        Number of output samples

    Returns
    -------
    np.ndarray
        Interpolated y values, shape: (n_samples,)
    """
    if len(points) < 2:
        return np.zeros(n_samples)

    segments = curve_segments(points)
    x_out = np.linspace(0, 100, n_samples)
    y_out = np.zeros(n_samples)

    for i, x in enumerate(x_out):
        # Find containing segment
        for seg in segments:
            if seg["startX"] <= x <= seg["endX"]:
                # Compute parameter t in [0, 1]
                t = (x - seg["startX"]) / (seg["endX"] - seg["startX"] + 1e-10)
                # Evaluate cubic polynomial
                coeffs = seg["yCoeffs"]
                y_out[i] = coeffs[0] + coeffs[1] * t + coeffs[2] * t**2 + coeffs[3] * t**3
                break
        else:
            # Extrapolate from nearest endpoint
            if x < segments[0]["startX"]:
                y_out[i] = points[0]["y"]
            else:
                y_out[i] = points[-1]["y"]

    return np.clip(y_out, 0.0, 1.0)


def generate_concentration_curve(
    curve_type: str,
    n_points: int,
    max_concentration: float = 1.0,
    center: float = 0.5,
    width: float = 0.1,
    control_points: Optional[List[Dict[str, float]]] = None,
) -> np.ndarray:
    """
    Generate a concentration profile curve.

    Parameters
    ----------
    curve_type : str
        Type of curve: sigmoid, gaussian, linear, step, constant, or catmull_rom
    n_points : int
        Number of time points
    max_concentration : float
        Maximum concentration value
    center : float
        Center position for sigmoid/gaussian (0-1)
    width : float
        Width parameter for sigmoid/gaussian
    control_points : list[dict], optional
        Control points for catmull_rom type

    Returns
    -------
    np.ndarray
        1D array of concentration values
    """
    t = np.linspace(0, 1, n_points)

    if curve_type == "sigmoid":
        return max_concentration / (1 + np.exp(-(t - center) / width))
    elif curve_type == "gaussian":
        return max_concentration * np.exp(-((t - center) ** 2) / (2 * width**2))
    elif curve_type == "linear":
        return max_concentration * t
    elif curve_type == "exponential":
        return max_concentration * (1 - np.exp(-t / width))
    elif curve_type == "step":
        return np.where(t >= center, max_concentration, 0.0)
    elif curve_type == "catmull_rom" and control_points:
        return max_concentration * evaluate_catmull_rom(control_points, n_points)
    else:  # constant
        return np.ones(n_points) * max_concentration


__all__ = [
    "initial_curve_points",
    "catmull_rom_coefficients",
    "curve_segments",
    "evaluate_catmull_rom",
    "generate_concentration_curve",
]
