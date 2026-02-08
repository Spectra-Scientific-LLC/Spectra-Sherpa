"""
Preprocessing nodes for spectral data.

These nodes implement various preprocessing techniques like baseline correction,
smoothing, normalization, and derivatives.

All nodes:
- Accept NDDataset as input
- Return NDDataset as output
- Record processing history in dataset.meta["processing_history"]
"""

from __future__ import annotations

from typing import Any, Optional, List, Dict
import numpy as np
import spectrochempy as scp
from spectrochempy import NDDataset

from ..node_base import Node, NodeMetadata, NodeParameter, InputPort, PortMetadata, register_node
from ..meta_helpers import add_processing_step, copy_processing_history, safe_get_coord
from app.lib.preprocessing import remove_cosmic_rays


@register_node
class BaselineALSNode(Node):
    """
    Asymmetric Least Squares (ALS) baseline correction node.

    Removes baseline drift from spectral data using the ALS algorithm.
    """

    metadata = NodeMetadata(
        node_type="baseline.als",
        category="preprocessing",
        label="Baseline (ALS)",
        description="Asymmetric Least Squares baseline correction",
        parameters=[
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
                description="Asymmetry parameter (smaller = more asymmetry)",
                required=False,
                category="basic",
            ),
        ],
        input_types=["NDDataset"],
        output_type="NDDataset",
    )

    async def execute(self, input_data: NDDataset) -> NDDataset:
        """Execute baseline correction using ALS."""
        lam = self.parameters.get("lam", 1e5)
        p = self.parameters.get("p", 0.001)

        result = input_data.copy()
        result.basc(lamb=lam, asymmetry=p)
        add_processing_step(result, "baseline.als", {"lam": lam, "p": p}, node_id=self.node_id)

        return result


@register_node
class BaselineRubberbandNode(Node):
    """
    Rubberband baseline correction node.

    Removes baseline by fitting a convex hull baseline.
    """

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
    )

    async def execute(self, input_data: NDDataset) -> NDDataset:
        """Execute rubberband baseline correction."""
        result = input_data.copy()
        result.basc(method="rubberband")
        add_processing_step(result, "baseline.rubberband", {"method": "rubberband"}, node_id=self.node_id)

        return result


@register_node
class SmoothSavitzkyGolayNode(Node):
    """
    Savitzky-Golay smoothing node.

    Applies polynomial smoothing to reduce noise.
    """

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

    async def execute(self, input_data: NDDataset) -> NDDataset:
        """Execute Savitzky-Golay smoothing."""
        size = self.parameters.get("size", 11)
        order = self.parameters.get("order", 2)

        result = input_data.copy()
        result.smooth(size=size, order=order)
        add_processing_step(result, "smooth.savitzky_golay", {"size": size, "order": order}, node_id=self.node_id)

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
    )

    async def execute(self, input_data: NDDataset) -> NDDataset:
        """Execute SNV normalization."""
        data = np.array(input_data.data, dtype=np.float64)

        if data.ndim == 1:
            mean_val = np.mean(data)
            std_val = np.std(data)
            if std_val == 0:
                std_val = 1.0
            normalized_data = (data - mean_val) / std_val
        else:
            mean_vals = np.mean(data, axis=1, keepdims=True)
            std_vals = np.std(data, axis=1, keepdims=True)
            std_vals[std_vals == 0] = 1.0
            normalized_data = (data - mean_vals) / std_vals

        result = scp.NDDataset(normalized_data)
        x_coord = safe_get_coord(input_data, 'x')
        if x_coord is not None:
            result.x = x_coord.copy()
        y_coord = safe_get_coord(input_data, 'y')
        if y_coord is not None:
            result.y = y_coord.copy()
        if hasattr(input_data, 'title'):
            result.title = input_data.title
        result.units = "dimensionless"

        copy_processing_history(input_data, result)
        add_processing_step(result, "normalize.snv", {}, node_id=self.node_id)

        return result


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

    async def execute(self, input_data: NDDataset) -> NDDataset:
        """Execute scale normalization."""
        method = self.parameters.get("method", "max")
        data = np.array(input_data.data, dtype=np.float64)

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

        result = scp.NDDataset(data)
        x_coord = safe_get_coord(input_data, 'x')
        if x_coord is not None:
            result.x = x_coord.copy()
        y_coord = safe_get_coord(input_data, 'y')
        if y_coord is not None:
            result.y = y_coord.copy()
        if hasattr(input_data, 'title'):
            result.title = input_data.title
        result.units = "normalized"

        copy_processing_history(input_data, result)
        add_processing_step(result, "normalize.scale", {"method": method}, node_id=self.node_id)

        return result


@register_node
class NormalizeMSCNode(Node):
    """
    Multiplicative Scatter Correction (MSC) node.

    Corrects for light scattering effects in spectral data.
    """

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
    )

    async def execute(self, input_data: NDDataset) -> NDDataset:
        """Execute MSC normalization."""
        reference = self.parameters.get("reference", "mean")

        result = input_data.copy()
        result.msc(reference=reference)
        result.units = "dimensionless"

        add_processing_step(result, "normalize.msc", {"reference": reference}, node_id=self.node_id)

        return result


@register_node
class DerivativeFirstNode(Node):
    """
    First derivative node.

    Computes the first derivative of spectral data.
    """

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
        ],
        input_types=["NDDataset"],
        output_type="NDDataset",
    )

    async def execute(self, input_data: NDDataset) -> NDDataset:
        """Execute first derivative calculation."""
        size = self.parameters.get("size", 11)
        order = self.parameters.get("order", 2)

        result = input_data.copy()
        result.deriv(size=size, order=order, deriv=1)

        # Update units
        original_units = str(input_data.units) if hasattr(input_data, 'units') and input_data.units else None
        x_coord = safe_get_coord(input_data, 'x')
        x_units = str(x_coord.units) if x_coord is not None and x_coord and hasattr(x_coord, 'units') else None

        if original_units and x_units and original_units != "dimensionless":
            result.units = f"d({original_units})/d({x_units})"
        elif original_units and original_units != "dimensionless":
            result.units = f"d({original_units})/dx"
        else:
            result.units = "d/dx"

        add_processing_step(result, "derivative.first", {"size": size, "order": order}, node_id=self.node_id)

        return result


@register_node
class DerivativeSecondNode(Node):
    """
    Second derivative node.

    Computes the second derivative of spectral data.
    """

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
                required=True,
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
                required=True,
            ),
        ],
        input_types=["NDDataset"],
        output_type="NDDataset",
    )

    async def execute(self, input_data: NDDataset) -> NDDataset:
        """Execute second derivative calculation."""
        size = self.parameters.get("size", 11)
        order = self.parameters.get("order", 2)

        result = input_data.copy()
        result.deriv(size=size, order=order, deriv=2)

        # Update units
        original_units = str(input_data.units) if hasattr(input_data, 'units') and input_data.units else None
        x_coord = safe_get_coord(input_data, 'x')
        x_units = str(x_coord.units) if x_coord is not None and x_coord and hasattr(x_coord, 'units') else None

        if original_units and x_units and original_units != "dimensionless":
            result.units = f"d²({original_units})/d({x_units})²"
        elif original_units and original_units != "dimensionless":
            result.units = f"d²({original_units})/dx²"
        else:
            result.units = "d²/dx²"

        add_processing_step(result, "derivative.second", {"size": size, "order": order}, node_id=self.node_id)

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

    async def execute(self, input_data: NDDataset) -> NDDataset:
        """Execute cosmic ray removal."""
        window = self.parameters.get("window", 7)
        zscore = self.parameters.get("zscore", 3.0)

        if window % 2 == 0:
            window += 1

        data = np.array(input_data.data)

        if data.ndim == 1:
            data = remove_cosmic_rays(data, window=window, zscore_threshold=zscore)
        else:
            for i in range(data.shape[0]):
                data[i] = remove_cosmic_rays(data[i], window=window, zscore_threshold=zscore)

        result = scp.NDDataset(data)
        x_coord = safe_get_coord(input_data, 'x')
        if x_coord is not None:
            result.x = x_coord.copy()
        y_coord = safe_get_coord(input_data, 'y')
        if y_coord is not None:
            result.y = y_coord.copy()
        if hasattr(input_data, 'title'):
            result.title = input_data.title
        if hasattr(input_data, 'units'):
            result.units = input_data.units

        copy_processing_history(input_data, result)
        add_processing_step(result, "preprocess.cosmic_ray", {"window": window, "zscore": zscore}, node_id=self.node_id)

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

    async def execute(self, input_data: NDDataset) -> NDDataset:
        """Execute wavenumber range clipping."""
        min_wn = self.parameters.get("min_wavenumber")
        max_wn = self.parameters.get("max_wavenumber")

        result = input_data.copy()
        input_shape = input_data.shape

        # Apply range limit using SpectroChemPy slicing
        if min_wn is not None and max_wn is not None:
            if min_wn > max_wn:
                min_wn, max_wn = max_wn, min_wn
            result = result[:, min_wn:max_wn]
        elif min_wn is not None:
            result = result[:, min_wn:]
        elif max_wn is not None:
            result = result[:, :max_wn]

        copy_processing_history(input_data, result)
        add_processing_step(
            result, "preprocess.clip_range",
            {"min_wavenumber": min_wn, "max_wavenumber": max_wn},
            node_id=self.node_id,
            input_shape=input_shape
        )

        return result


@register_node
class ClipFloorNode(Node):
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

    async def execute(self, input_data: NDDataset) -> NDDataset:
        """Execute floor clipping."""
        floor = self.parameters.get("floor", 0.0)

        data = np.array(input_data.data, dtype=np.float64)
        data = np.maximum(data, floor)

        result = scp.NDDataset(data)
        x_coord = safe_get_coord(input_data, 'x')
        if x_coord is not None:
            result.x = x_coord.copy()
        y_coord = safe_get_coord(input_data, 'y')
        if y_coord is not None:
            result.y = y_coord.copy()
        if hasattr(input_data, 'title'):
            result.title = input_data.title
        if hasattr(input_data, 'units'):
            result.units = input_data.units

        copy_processing_history(input_data, result)
        add_processing_step(result, "preprocess.clip_floor", {"floor": floor}, node_id=self.node_id)

        return result


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

    async def execute(self, input_data: NDDataset) -> NDDataset:
        """Execute wavenumber alignment."""
        method = self.parameters.get("method", "pchip")
        merge_tolerance = self.parameters.get("merge_tolerance", 0.5)

        result = input_data.copy()
        add_processing_step(result, "preprocess.wavenumber_align", {"method": method, "merge_tolerance": merge_tolerance}, node_id=self.node_id)

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

    async def execute(self, input_data: NDDataset) -> NDDataset:
        """Execute scale to maximum normalization."""
        target_max = self.parameters.get("target_max", 1.0)

        data = np.array(input_data.data, dtype=np.float64)

        if data.ndim == 1:
            current_max = np.abs(data).max()
            if current_max > 0:
                data = data * (target_max / current_max)
        else:
            for i in range(data.shape[0]):
                current_max = np.abs(data[i]).max()
                if current_max > 0:
                    data[i] = data[i] * (target_max / current_max)

        result = scp.NDDataset(data)
        x_coord = safe_get_coord(input_data, 'x')
        if x_coord is not None:
            result.x = x_coord.copy()
        y_coord = safe_get_coord(input_data, 'y')
        if y_coord is not None:
            result.y = y_coord.copy()
        if hasattr(input_data, 'title'):
            result.title = input_data.title
        result.units = "normalized"

        copy_processing_history(input_data, result)
        add_processing_step(result, "preprocess.scale_max", {"target_max": target_max}, node_id=self.node_id)

        return result


@register_node
class CenterMeanNode(Node):
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

    async def execute(self, input_data: NDDataset) -> NDDataset:
        """Execute mean centering."""
        data = np.array(input_data.data, dtype=np.float64)

        if data.ndim == 1:
            data = data - np.mean(data)
        else:
            mean_spectrum = np.mean(data, axis=0)
            data = data - mean_spectrum

        result = scp.NDDataset(data)
        x_coord = safe_get_coord(input_data, 'x')
        if x_coord is not None:
            result.x = x_coord.copy()
        y_coord = safe_get_coord(input_data, 'y')
        if y_coord is not None:
            result.y = y_coord.copy()
        if hasattr(input_data, 'title'):
            result.title = input_data.title
        if hasattr(input_data, 'units'):
            result.units = input_data.units

        copy_processing_history(input_data, result)
        add_processing_step(result, "preprocess.center_mean", {}, node_id=self.node_id)

        return result


@register_node
class ParetoScalingNode(Node):
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

    async def execute(self, input_data: NDDataset) -> NDDataset:
        """Execute Pareto scaling."""
        center = self.parameters.get("center", True)

        data = np.array(input_data.data, dtype=np.float64)

        if center:
            mean = np.mean(data, axis=0, keepdims=True)
            data_centered = data - mean
        else:
            data_centered = data

        std = np.std(data, axis=0, keepdims=True)
        scaling_factor = np.sqrt(std)
        scaling_factor[scaling_factor == 0] = 1.0

        data_scaled = data_centered / scaling_factor

        result = scp.NDDataset(data_scaled)
        x_coord = safe_get_coord(input_data, 'x')
        if x_coord is not None:
            result.x = x_coord.copy()
        y_coord = safe_get_coord(input_data, 'y')
        if y_coord is not None:
            result.y = y_coord.copy()
        if hasattr(input_data, 'title'):
            result.title = input_data.title
        result.units = "dimensionless"

        copy_processing_history(input_data, result)
        add_processing_step(result, "preprocess.pareto_scaling", {"center": center}, node_id=self.node_id)

        return result


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
                port_type="dataset",
                required=True,
                label="Spectra (X)",
                description="Spectral data matrix to correct",
            ),
            PortMetadata(
                name="y",
                port_type="target",
                required=True,
                label="Target (y)",
                description="Target values (concentrations, class labels, etc.)",
            ),
        ],
    )

    async def execute(self, X=None, y=None, **kwargs) -> NDDataset:
        """Execute OSC filtering."""
        if X is None and "input_0" in kwargs:
            X = kwargs["input_0"]
        if y is None and "input_1" in kwargs:
            y = kwargs["input_1"]

        if X is None:
            raise ValueError("Missing required input: X (spectra)")
        if y is None:
            raise ValueError("Missing required input: y (target)")

        n_components = self.parameters.get("n_components", 1)
        tol = self.parameters.get("tol", 1e-6)
        max_iter = self.parameters.get("max_iter", 100)

        X_data = np.array(X.data)
        y_data = np.array(y).reshape(-1, 1) if len(np.array(y).shape) == 1 else np.array(y)
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
            converged = False

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
                    converged = True
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

        result = scp.NDDataset(X_osc)
        x_coord = safe_get_coord(X, 'x')
        if x_coord is not None:
            result.x = x_coord.copy()
        y_coord = safe_get_coord(X, 'y')
        if y_coord is not None:
            result.y = y_coord.copy()
        if hasattr(X, 'title'):
            result.title = X.title
        if hasattr(X, 'units'):
            result.units = X.units

        copy_processing_history(X, result)
        add_processing_step(result, "preprocess.osc", {
            "n_components": n_components,
            "tol": tol,
            "max_iter": max_iter,
            "variance_removed_percent": total_variance_removed,
        }, node_id=self.node_id)

        return result


@register_node
class AutoscalingNode(Node):
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

    async def execute(self, input_data: NDDataset) -> NDDataset:
        """Execute autoscaling."""
        center = self.parameters.get("center", True)

        data = np.array(input_data.data, dtype=np.float64)

        if center:
            mean = np.mean(data, axis=0, keepdims=True)
            data_centered = data - mean
        else:
            data_centered = data

        std = np.std(data, axis=0, keepdims=True)
        std[std == 0] = 1.0

        data_scaled = data_centered / std

        result = scp.NDDataset(data_scaled)
        x_coord = safe_get_coord(input_data, 'x')
        if x_coord is not None:
            result.x = x_coord.copy()
        y_coord = safe_get_coord(input_data, 'y')
        if y_coord is not None:
            result.y = y_coord.copy()
        if hasattr(input_data, 'title'):
            result.title = input_data.title
        result.units = "dimensionless"

        copy_processing_history(input_data, result)
        add_processing_step(result, "preprocess.autoscaling", {"center": center}, node_id=self.node_id)

        return result


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

    async def execute(self, input_data: NDDataset) -> NDDataset:
        """Execute Savitzky-Golay derivative."""
        size = self.parameters.get("size", 11)
        order = self.parameters.get("order", 2)
        deriv_order = int(self.parameters.get("deriv", "1"))

        if size % 2 == 0:
            size += 1

        result = input_data.copy()
        result.deriv(size=size, order=order, deriv=deriv_order)

        # Update units
        if deriv_order > 0:
            original_units = str(input_data.units) if hasattr(input_data, 'units') and input_data.units else None
            x_coord = safe_get_coord(input_data, 'x')
            x_units = str(x_coord.units) if x_coord is not None and x_coord and hasattr(x_coord, 'units') else None

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

        add_processing_step(result, "preprocess.sg_derivative", {"size": size, "order": order, "deriv": deriv_order}, node_id=self.node_id)

        return result


@register_node
class EMSCNode(Node):
    """
    Extended Multiplicative Signal Correction (EMSC) node.

    Extends MSC by adding polynomial baseline correction.
    """

    metadata = NodeMetadata(
        node_type="preprocess.emsc",
        category="preprocessing",
        label="EMSC",
        description="Extended MSC with polynomial baseline correction",
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
    )

    async def execute(self, input_data: NDDataset) -> NDDataset:
        """Execute EMSC correction."""
        reference_type = self.parameters.get("reference", "mean")
        poly_order = self.parameters.get("poly_order", 2)

        data = np.array(input_data.data, dtype=np.float64)
        n_samples, n_features = data.shape

        if reference_type == "mean":
            reference = np.mean(data, axis=0)
        elif reference_type == "median":
            reference = np.median(data, axis=0)
        elif reference_type == "first":
            reference = data[0]
        else:
            reference = np.mean(data, axis=0)

        X_design = [reference]
        if poly_order > 0:
            x_axis = np.arange(n_features)
            x_norm = (x_axis - x_axis.mean()) / x_axis.std()
            for deg in range(1, poly_order + 1):
                X_design.append(x_norm ** deg)

        X_design = np.column_stack(X_design)
        corrected_data = np.zeros_like(data)
        EMSC_COEF_THRESHOLD = 1e-8

        for i in range(n_samples):
            spectrum = data[i]
            coef, _, _, _ = np.linalg.lstsq(X_design, spectrum, rcond=None)

            if poly_order > 0:
                polynomial_baseline = X_design[:, 1:] @ coef[1:]
                if np.abs(coef[0]) > EMSC_COEF_THRESHOLD:
                    corrected_spectrum = (spectrum - polynomial_baseline) / coef[0]
                else:
                    corrected_spectrum = spectrum
            else:
                if np.abs(coef[0]) > EMSC_COEF_THRESHOLD:
                    corrected_spectrum = spectrum / coef[0]
                else:
                    corrected_spectrum = spectrum

            corrected_data[i] = corrected_spectrum

        result = scp.NDDataset(corrected_data)
        x_coord = safe_get_coord(input_data, 'x')
        if x_coord is not None:
            result.x = x_coord.copy()
        y_coord = safe_get_coord(input_data, 'y')
        if y_coord is not None:
            result.y = y_coord.copy()
        if hasattr(input_data, 'title'):
            result.title = input_data.title
        if hasattr(input_data, 'units'):
            result.units = input_data.units

        copy_processing_history(input_data, result)
        add_processing_step(result, "preprocess.emsc", {"reference": reference_type, "poly_order": poly_order}, node_id=self.node_id)

        return result
