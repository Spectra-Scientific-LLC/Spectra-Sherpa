"""
Custom atomic nodes for spectral blending and synthetic data generation.

These nodes expose the core numerical algorithms as composable DAG components,
replacing the monolithic project0/project1 implementations.

Node Sets:
- Custom #1 (Blending): LinearCalibrationNode, SaturationModelNode,
                        SystemSaturationNode, CatmullRomCurveNode
- Custom #2 (Synthetic): HybridSelectorNode, ConcentrationCurveNode,
                         GoldenGridAlignNode, NoiseInjectionNode

The SaturationModelNode is shared between both sets.
"""

from __future__ import annotations

from typing import Any, List

import numpy as np

from spectra_sherpa.app.lib.analysis_dataset import AxisInfo
from spectra_sherpa.app.lib.scp_compat import NDDataset
from spectra_sherpa.app.services.dag.meta_helpers import add_processing_step, copy_processing_history, safe_get_coord

from ..io_contracts import (
    bind_X,
    bind_y,
    build_dataset_like,
    coerce_dataset,
    resolve_legacy_input,
    to_numpy_1d,
    to_numpy_2d,
)
from ..node_base import Node, NodeMetadata, NodeParameter, register_node

# ═══════════════════════════════════════════════════════════════════════════════
# CUSTOM NODE SET #1: BLENDING NODES
# ═══════════════════════════════════════════════════════════════════════════════


@register_node
class LinearCalibrationNode(Node):
    """
    Linear Calibration Model

    Evaluates Beer-Lambert linear model with optional saturation capping:
    A = clip(slope * C + intercept, 0, s_max)

    Part of Custom Node Set #1 (Blending).
    """

    metadata = NodeMetadata(
        node_type="custom.linear_calibration",
        category="custom",
        label="Linear Calibration",
        description="Beer-Lambert linear model with saturation capping",
        parameters=[
            NodeParameter(
                name="s_max",
                label="Saturation Cap",
                param_type="number",
                default=1.8,
                min_value=0.1,
                max_value=10.0,
                description="Maximum absorbance cap (prevents unphysical extrapolation)",
            ),
            NodeParameter(
                name="concentration_unit",
                label="Concentration Unit",
                param_type="select",
                options=[
                    {"value": "ppm", "label": "ppm (parts per million)"},
                    {"value": "ppmv", "label": "ppmv (by volume, gas)"},
                    {"value": "mol/L", "label": "mol/L (molar)"},
                    {"value": "mg/L", "label": "mg/L"},
                    {"value": "wt%", "label": "wt% (weight percent)"},
                    {"value": "vol%", "label": "vol% (volume percent)"},
                ],
                default="ppm",
                description="Unit of input concentrations (must match calibration)",
                category="advanced",
            ),
            NodeParameter(
                name="reference_confirmed",
                label="Reference Applied",
                param_type="boolean",
                default=False,
                description="Confirm that reference spectrum (I0) was applied to input data",
                category="advanced",
            ),
        ],
        input_types=["NDDataset", "array"],  # spectrum, concentrations
        output_type="NDDataset",
    )

    async def execute(
        self,
        spectrum: Any,
        concentrations: Any,
        **kwargs,
    ) -> NDDataset:
        """
        Apply linear calibration model to generate absorbance spectra.

        Parameters
        ----------
        spectrum : NDDataset
            Pure component spectrum with calibration in meta["calibration"]
        concentrations : array-like
            Concentration values for each timepoint

        Returns
        -------
        NDDataset
            Absorbance spectra for each concentration
        """
        import warnings

        from spectra_sherpa.app.lib.blending import SAFE_MIN_THRESHOLD, eval_linear_model

        spectrum_ds = bind_X(
            spectrum,
            kwargs,
            missing_message="Missing required input: spectrum",
            dataset_error_message="spectrum must be an NDDataset or AnalysisDataset object",
        )
        concentrations_bound = bind_y(
            concentrations,
            kwargs,
            infer_from_X=False,
            required=True,
            dataset_as_data=True,
            missing_message="Missing required input: concentrations",
        )
        s_max = self.parameters.get("s_max", SAFE_MIN_THRESHOLD)
        conc_unit = self.parameters.get("concentration_unit", "ppm")
        ref_confirmed = self.parameters.get("reference_confirmed", False)
        concentrations_array = to_numpy_1d(
            concentrations_bound,
            name="concentrations",
            dtype=np.float64,
        )

        # Get calibration from metadata
        calib = spectrum_ds.meta.get("calibration", {})
        n_wn = spectrum_ds.shape[-1]

        # Validate unit compatibility
        calib_unit = calib.get("concentration_unit")
        if calib_unit and calib_unit != conc_unit:
            warnings.warn(
                f"Concentration unit mismatch: calibration uses '{calib_unit}' but node "
                f"configured for '{conc_unit}'. Results may be incorrect by orders of magnitude.",
                UserWarning,
            )

        # Warn about reference status
        if not ref_confirmed:
            meta = spectrum_ds.meta if hasattr(spectrum_ds, "meta") else {}
            ref_applied = meta.get(
                "reference_applied", meta.get("chemometrics", {}).get("reference", {}).get("applied", False)
            )
            if not ref_applied:
                warnings.warn(
                    "Reference spectrum status not confirmed. If input data is not "
                    "ratio'd to reference (I/I0), absorbance values will be incorrect.",
                    UserWarning,
                )

        slope = np.array(calib.get("slope", np.ones(n_wn)))
        intercept = np.array(calib.get("intercept", np.zeros(n_wn)))

        # Build saturation cap array
        s_cap = np.full(n_wn, s_max)

        # Evaluate linear model
        absorbance = eval_linear_model(concentrations_array, slope, intercept, s=s_cap)

        # Create output dataset (n_wn, n_times) -> (n_times, n_wn)
        spec_x_coord = safe_get_coord(spectrum_ds, "x")
        if spec_x_coord is None:
            raise ValueError("Input spectrum must have an x coordinate (wavenumber axis)")
        result = build_dataset_like(
            absorbance.T,
            spectrum_ds,
            units="absorbance",
            title=f"{spectrum_ds.title}_linear",
        )
        result.x = spec_x_coord.copy()
        result.y = AxisInfo(values=np.arange(len(concentrations_array)), title="Sample Index")

        result.meta["calibration_model"] = "linear"
        result.meta["concentrations"] = concentrations_array.tolist()
        result.meta["concentration_unit"] = conc_unit
        result.meta["reference_confirmed"] = ref_confirmed

        add_processing_step(
            result,
            "custom.linear_calibration",
            {
                "s_max": s_max,
                "concentration_unit": conc_unit,
                "reference_confirmed": ref_confirmed,
            },
            node_id=self.node_id,
        )
        return result


@register_node
class SaturationModelNode(Node):
    """
    Saturation Calibration Model (SHARED)

    Evaluates tanh-based saturation model for non-linear Beer-Lambert behavior:
    A = s * [tanh((c*C/s)^p)]^(1/p)

    SHARED between Custom Node Set #1 (Blending) and #2 (Synthetic).
    """

    metadata = NodeMetadata(
        node_type="custom.saturation_model",
        category="custom",
        label="Saturation Model",
        description="Hyperbolic tangent saturation model for high concentrations",
        parameters=[
            NodeParameter(
                name="validate_params",
                label="Validate Parameters",
                param_type="boolean",
                default=True,
                description="Raise error if s, p, c parameters are invalid",
            ),
            NodeParameter(
                name="concentration_unit",
                label="Concentration Unit",
                param_type="select",
                options=[
                    {"value": "ppm", "label": "ppm (parts per million)"},
                    {"value": "ppmv", "label": "ppmv (by volume, gas)"},
                    {"value": "mol/L", "label": "mol/L (molar)"},
                    {"value": "mg/L", "label": "mg/L"},
                    {"value": "wt%", "label": "wt% (weight percent)"},
                    {"value": "vol%", "label": "vol% (volume percent)"},
                ],
                default="ppm",
                description="Unit of input concentrations (must match calibration)",
                category="advanced",
            ),
            NodeParameter(
                name="warn_extrapolation",
                label="Warn on Extrapolation",
                param_type="boolean",
                default=True,
                description="Warn if concentration exceeds calibration range",
                category="advanced",
            ),
        ],
        input_types=["NDDataset", "array"],  # spectrum, concentrations
        output_type="NDDataset",
    )

    async def execute(
        self,
        spectrum: Any,
        concentrations: Any,
        **kwargs,
    ) -> NDDataset:
        """
        Apply saturation calibration model to generate absorbance spectra.

        Parameters
        ----------
        spectrum : NDDataset
            Pure component spectrum with calibration in meta["calibration"]
            Required keys: s, p, c arrays
        concentrations : array-like
            Concentration values for each timepoint

        Returns
        -------
        NDDataset
            Absorbance spectra for each concentration
        """
        import warnings

        from spectra_sherpa.app.lib.blending import eval_saturation_model

        spectrum_ds = bind_X(
            spectrum,
            kwargs,
            missing_message="Missing required input: spectrum",
            dataset_error_message="spectrum must be an NDDataset or AnalysisDataset object",
        )
        concentrations_bound = bind_y(
            concentrations,
            kwargs,
            infer_from_X=False,
            required=True,
            dataset_as_data=True,
            missing_message="Missing required input: concentrations",
        )
        conc_unit = self.parameters.get("concentration_unit", "ppm")
        warn_extrap = self.parameters.get("warn_extrapolation", True)
        concentrations_array = to_numpy_1d(
            concentrations_bound,
            name="concentrations",
            dtype=np.float64,
        )

        # Get calibration from metadata
        calib = spectrum_ds.meta.get("calibration", {})
        meta = spectrum_ds.meta if hasattr(spectrum_ds, "meta") else {}
        n_wn = spectrum_ds.shape[-1]

        # Validate unit compatibility
        calib_unit = calib.get("concentration_unit")
        if calib_unit and calib_unit != conc_unit:
            warnings.warn(
                f"Concentration unit mismatch: calibration uses '{calib_unit}' but node "
                f"configured for '{conc_unit}'. Results may be incorrect by orders of magnitude.",
                UserWarning,
            )

        # Check calibration range for extrapolation warnings
        if warn_extrap:
            calib_range = meta.get("chemometrics", {}).get("calibration_range", {})
            if not calib_range:
                calib_range = calib.get("calibration_range", {})

            if calib_range:
                min_c = calib_range.get("min_concentration")
                max_c = calib_range.get("max_concentration")
                if min_c is not None and max_c is not None:
                    if np.any(concentrations_array < min_c) or np.any(concentrations_array > max_c):
                        c_min = concentrations_array.min()
                        c_max = concentrations_array.max()
                        warnings.warn(
                            f"Concentration values [{c_min:.2f}, {c_max:.2f}] "
                            f"extend beyond calibration range [{min_c}, {max_c}]. "
                            f"Saturation model extrapolation may be unreliable.",
                            UserWarning,
                        )

        s = np.array(calib.get("s", np.ones(n_wn)))
        p = np.array(calib.get("p", np.ones(n_wn)))
        c = np.array(calib.get("c", np.ones(n_wn)))

        # Validate and filter valid parameters
        valid = (s > 0) & (p > 0) & (c > 0)

        if not np.any(valid):
            raise ValueError("No valid saturation parameters (s, p, c must be > 0)")

        # Evaluate saturation model
        absorbance = np.zeros((n_wn, len(concentrations_array)))
        absorbance[valid] = eval_saturation_model(concentrations_array, s[valid], p[valid], c[valid])

        # Create output dataset
        spec_x_coord = safe_get_coord(spectrum_ds, "x")
        if spec_x_coord is None:
            raise ValueError("Input spectrum must have an x coordinate (wavenumber axis)")
        result = build_dataset_like(
            absorbance.T,
            spectrum_ds,
            units="absorbance",
            title=f"{spectrum_ds.title}_saturation",
        )
        result.x = spec_x_coord.copy()
        result.y = AxisInfo(values=np.arange(len(concentrations_array)), title="Sample Index")

        result.meta["calibration_model"] = "saturation"
        result.meta["concentrations"] = concentrations_array.tolist()
        result.meta["concentration_unit"] = conc_unit

        add_processing_step(
            result,
            "custom.saturation_model",
            {
                "concentration_unit": conc_unit,
                "warn_extrapolation": warn_extrap,
            },
            node_id=self.node_id,
        )
        return result


@register_node
class SystemSaturationNode(Node):
    """
    System-Level Saturation

    Applies detector saturation after Beer's Law superposition:
    A_measured = s_sys * [tanh((A_total/s_sys)^p_sys)]^(1/p_sys)

    Part of Custom Node Set #1 (Blending).
    """

    metadata = NodeMetadata(
        node_type="custom.system_saturation",
        category="custom",
        label="System Saturation",
        description="Apply detector-level saturation to blended spectra",
        parameters=[
            NodeParameter(
                name="s_system",
                label="System Saturation Level",
                param_type="number",
                default=2.0,
                min_value=0.1,
                max_value=10.0,
                description="Maximum absorbance the detector can measure",
            ),
            NodeParameter(
                name="p_system",
                label="Saturation Exponent",
                param_type="number",
                default=1.0,
                min_value=0.1,
                max_value=5.0,
                description="Shape exponent controlling transition sharpness",
            ),
        ],
        input_types=["NDDataset"],
        output_type="NDDataset",
    )

    async def execute(self, input_data: Any, **kwargs) -> NDDataset:
        """
        Apply system-level saturation to absorbance spectra.

        Parameters
        ----------
        input_data : NDDataset
            Blended absorbance spectra (potentially exceeding detector range)

        Returns
        -------
        NDDataset
            Saturated spectra (bounded by detector limits)
        """
        from spectra_sherpa.app.lib.blending import apply_system_saturation

        input_data = resolve_legacy_input(input_data, kwargs, "default")
        input_ds = bind_X(
            input_data,
            kwargs,
            missing_message="Missing required input: input_data",
            dataset_error_message="input_data must be an NDDataset or AnalysisDataset object",
        )
        s_system = self.parameters.get("s_system", 2.0)
        p_system = self.parameters.get("p_system", 1.0)

        # Apply saturation
        data = to_numpy_2d(input_ds, name="input_data")

        saturated = apply_system_saturation(data.T, s_system, p_system).T

        result = build_dataset_like(saturated, input_ds)
        add_processing_step(
            result,
            "custom.system_saturation",
            {"s_system": s_system, "p_system": p_system},
            node_id=self.node_id,
        )
        return result


@register_node
class CatmullRomCurveNode(Node):
    """
    Catmull-Rom Spline Curve Generator

    Generates smooth concentration curves from control points using
    Catmull-Rom spline interpolation.

    Part of Custom Node Set #1 (Blending).
    """

    metadata = NodeMetadata(
        node_type="custom.catmull_rom_curve",
        category="custom",
        label="Catmull-Rom Curve",
        description="Generate smooth concentration curves from control points",
        parameters=[
            NodeParameter(
                name="n_points",
                label="Number of Output Points",
                param_type="number",
                default=100,
                min_value=10,
                max_value=1000,
                description="Number of points in the output curve",
            ),
            NodeParameter(
                name="max_concentration",
                label="Maximum Concentration",
                param_type="number",
                default=1.0,
                min_value=0.0,
                description="Scale factor for output concentrations",
            ),
            NodeParameter(
                name="control_points",
                label="Control Points",
                param_type="json",
                default=[],
                description="List of {x, y} control points (x: 0-100, y: 0-1)",
            ),
        ],
        input_types=[],  # No inputs - this is a generator
        output_type="array",
    )

    async def execute(self, **kwargs) -> np.ndarray:
        """
        Generate a Catmull-Rom spline curve from control points.

        Returns
        -------
        np.ndarray
            Concentration curve with n_points values
        """
        from spectra_sherpa.app.lib.curves import evaluate_catmull_rom, initial_curve_points

        n_points = int(self.parameters.get("n_points", 100))
        max_conc = self.parameters.get("max_concentration", 1.0)
        control_points = self.parameters.get("control_points", [])

        # Use default control points if none provided
        if not control_points:
            control_points = initial_curve_points(11)

        # Evaluate spline
        curve = evaluate_catmull_rom(control_points, n_points)

        return curve * max_conc


# ═══════════════════════════════════════════════════════════════════════════════
# CUSTOM NODE SET #2: SYNTHETIC DATA BUILDER NODES
# ═══════════════════════════════════════════════════════════════════════════════


@register_node
class HybridSelectorNode(Node):
    """
    Hybrid Model Selector

    Per-wavenumber selection between linear and saturation models
    based on a mask or automatic threshold detection.

    Part of Custom Node Set #2 (Synthetic Builder).
    """

    metadata = NodeMetadata(
        node_type="custom.hybrid_selector",
        category="custom",
        label="Hybrid Model Selector",
        description="Select linear or saturation model per wavenumber",
        parameters=[
            NodeParameter(
                name="auto_select",
                label="Auto-Select Model",
                param_type="boolean",
                default=True,
                description="Automatically choose model based on parameter quality",
            ),
            NodeParameter(
                name="saturation_threshold",
                label="Saturation Threshold",
                param_type="number",
                default=0.5,
                min_value=0.0,
                max_value=2.0,
                description="Absorbance threshold above which to use saturation model",
            ),
        ],
        input_types=["NDDataset", "NDDataset", "array"],  # linear, saturation, concentrations
        output_type="NDDataset",
    )

    async def execute(
        self,
        linear_result: Any,
        saturation_result: Any,
        concentrations: Any,
        **kwargs,
    ) -> NDDataset:
        """
        Select between linear and saturation model outputs per wavenumber.

        Parameters
        ----------
        linear_result : NDDataset
            Output from LinearCalibrationNode
        saturation_result : NDDataset
            Output from SaturationModelNode
        concentrations : array-like
            Original concentration values

        Returns
        -------
        NDDataset
            Hybrid-selected absorbance spectra
        """

        linear_result = resolve_legacy_input(linear_result, kwargs, "input_0")
        saturation_result = resolve_legacy_input(saturation_result, kwargs, "input_1")
        linear_ds = coerce_dataset(
            linear_result,
            input_name="linear_result",
            dataset_error_message=("linear_result must be an NDDataset or AnalysisDataset object"),
        )
        saturation_ds = coerce_dataset(
            saturation_result,
            input_name="saturation_result",
            dataset_error_message=("saturation_result must be an NDDataset or AnalysisDataset object"),
        )
        auto_select = self.parameters.get("auto_select", True)
        threshold = self.parameters.get("saturation_threshold", 0.5)

        linear_data = to_numpy_2d(linear_ds, name="linear_result")
        sat_data = to_numpy_2d(saturation_ds, name="saturation_result")

        n_times, n_wn = linear_data.shape

        # Determine selection mask
        if auto_select:
            # Use saturation model where it gives higher absorbance (non-linear regime)
            sat_mask = np.max(sat_data, axis=0) > threshold
        else:
            # Use saturation model everywhere saturation parameters exist
            calib = saturation_ds.meta.get("calibration", {})
            s = np.array(calib.get("s", np.zeros(n_wn)))
            sat_mask = s > 0

        # Select per wavenumber
        hybrid_data = np.where(sat_mask, sat_data, linear_data)

        result = build_dataset_like(
            hybrid_data,
            linear_ds,
            units="absorbance",
            title="Hybrid Model Output",
        )

        result.meta["hybrid_mask"] = sat_mask.tolist()
        result.meta["n_saturation"] = int(np.sum(sat_mask))
        result.meta["n_linear"] = int(n_wn - np.sum(sat_mask))

        add_processing_step(
            result,
            "custom.hybrid_selector",
            {"auto_select": auto_select, "threshold": threshold},
            node_id=self.node_id,
        )
        return result


@register_node
class ConcentrationCurveNode(Node):
    """
    Concentration Curve Generator

    Generates concentration profiles for synthetic data:
    sigmoid, gaussian, linear, exponential, step, or constant.

    Part of Custom Node Set #2 (Synthetic Builder).
    """

    metadata = NodeMetadata(
        node_type="custom.concentration_curve",
        category="custom",
        label="Concentration Curve",
        description="Generate concentration time-series curves",
        parameters=[
            NodeParameter(
                name="curve_type",
                label="Curve Type",
                param_type="select",
                options=["sigmoid", "gaussian", "linear", "exponential", "step", "constant"],
                default="sigmoid",
                description="Type of concentration profile",
            ),
            NodeParameter(
                name="n_points",
                label="Number of Points",
                param_type="number",
                default=100,
                min_value=10,
                max_value=1000,
                description="Number of time points",
            ),
            NodeParameter(
                name="max_concentration",
                label="Maximum Concentration",
                param_type="number",
                default=1.0,
                min_value=0.0,
                description="Maximum concentration value",
            ),
            NodeParameter(
                name="center",
                label="Center Position",
                param_type="number",
                default=0.5,
                min_value=0.0,
                max_value=1.0,
                description="Center position for sigmoid/gaussian (0-1)",
            ),
            NodeParameter(
                name="width",
                label="Width",
                param_type="number",
                default=0.1,
                min_value=0.01,
                max_value=1.0,
                description="Width parameter for sigmoid/gaussian",
            ),
        ],
        input_types=[],  # No inputs - this is a generator
        output_type="array",
    )

    async def execute(self, **kwargs) -> np.ndarray:
        """
        Generate a concentration curve.

        Returns
        -------
        np.ndarray
            Concentration values at each time point
        """
        from spectra_sherpa.app.lib.curves import generate_concentration_curve

        curve_type = self.parameters.get("curve_type", "sigmoid")
        n_points = int(self.parameters.get("n_points", 100))
        max_conc = self.parameters.get("max_concentration", 1.0)
        center = self.parameters.get("center", 0.5)
        width = self.parameters.get("width", 0.1)

        return generate_concentration_curve(
            curve_type=curve_type,
            n_points=n_points,
            max_concentration=max_conc,
            center=center,
            width=width,
        )


@register_node
class GoldenGridAlignNode(Node):
    """
    Golden Grid Wavenumber Alignment

    Aligns multiple spectra to a common wavenumber grid using
    the "golden grid" approach.

    Part of Custom Node Set #2 (Synthetic Builder).
    """

    metadata = NodeMetadata(
        node_type="custom.golden_grid_align",
        category="custom",
        label="Golden Grid Align",
        description="Align spectra to common wavenumber grid",
        parameters=[
            NodeParameter(
                name="method",
                label="Interpolation Method",
                param_type="select",
                options=["pchip", "linear", "sinc"],
                default="pchip",
                description="Interpolation method for resampling",
            ),
            NodeParameter(
                name="merge_tolerance",
                label="Merge Tolerance (cm-1)",
                param_type="number",
                default=0.05,
                min_value=0.001,
                max_value=1.0,
                description="Tolerance for merging near-duplicate wavenumbers",
            ),
        ],
        input_types=["NDDataset"],  # Variable number of inputs
        output_type="NDDataset",
    )

    async def execute(self, *input_data: Any, **kwargs) -> List[NDDataset]:
        """
        Align multiple spectra to a common golden grid.

        Parameters
        ----------
        *input_data : NDDataset
            Variable number of input spectra

        Returns
        -------
        list[NDDataset]
            Aligned spectra on common wavenumber grid
        """
        from spectra_sherpa.app.lib.preprocessing import build_golden_grid, interpolate_to_grid

        method = self.parameters.get("method", "pchip")
        tolerance = self.parameters.get("merge_tolerance", 0.05)

        if len(input_data) == 0:
            raise ValueError("At least one input spectrum required")

        datasets = [
            coerce_dataset(
                ds,
                input_name=f"input_data[{idx}]",
                dataset_error_message="Each input must be an NDDataset or AnalysisDataset object",
            )
            for idx, ds in enumerate(input_data)
        ]

        # Build golden grid
        golden_grid = build_golden_grid(datasets, merge_tolerance=tolerance)

        # Interpolate all spectra to golden grid
        aligned = [interpolate_to_grid(ds, golden_grid, method=method) for ds in datasets]

        # Add processing step to each aligned NDDataset
        for i, ds in enumerate(aligned):
            copy_processing_history(datasets[i], ds)
            add_processing_step(
                ds,
                "custom.golden_grid_align",
                {"method": method, "merge_tolerance": tolerance},
                node_id=self.node_id,
            )

        return aligned


@register_node
class NoiseInjectionNode(Node):
    """
    Gaussian Noise Injection

    Adds realistic Gaussian noise to synthetic spectra for
    training data augmentation and algorithm testing.

    Part of Custom Node Set #2 (Synthetic Builder).
    """

    metadata = NodeMetadata(
        node_type="custom.noise_injection",
        category="custom",
        label="Noise Injection",
        description="Add Gaussian noise to spectra",
        parameters=[
            NodeParameter(
                name="noise_level",
                label="Noise Level",
                param_type="number",
                default=0.01,
                min_value=0.0,
                max_value=0.5,
                step=0.001,
                description="Noise as fraction of signal (0.01 = 1%)",
            ),
            NodeParameter(
                name="noise_type",
                label="Noise Type",
                param_type="select",
                options=["absolute", "relative"],
                default="relative",
                description="Absolute noise or relative to signal",
            ),
            NodeParameter(
                name="seed",
                label="Random Seed",
                param_type="number",
                default=-1,
                description="Random seed (-1 for random)",
            ),
        ],
        input_types=["NDDataset"],
        output_type="NDDataset",
    )

    async def execute(self, input_data: Any, **kwargs) -> NDDataset:
        """
        Add Gaussian noise to spectra.

        Parameters
        ----------
        input_data : NDDataset
            Clean spectra

        Returns
        -------
        NDDataset
            Noisy spectra
        """

        input_data = resolve_legacy_input(input_data, kwargs, "default")
        input_ds = bind_X(
            input_data,
            kwargs,
            missing_message="Missing required input: input_data",
            dataset_error_message="input_data must be an NDDataset or AnalysisDataset object",
        )
        noise_level = self.parameters.get("noise_level", 0.01)
        noise_type = self.parameters.get("noise_type", "relative")
        seed = int(self.parameters.get("seed", -1))

        if seed >= 0:
            np.random.seed(seed)

        data = to_numpy_2d(input_ds, name="input_data").copy()

        if noise_type == "relative":
            # Noise proportional to signal magnitude
            noise_std = noise_level * np.abs(data).mean()
        else:
            # Absolute noise level
            noise_std = noise_level

        noise = np.random.randn(*data.shape) * noise_std
        noisy_data = data + noise

        result = build_dataset_like(noisy_data, input_ds)
        add_processing_step(
            result,
            "custom.noise_injection",
            {"noise_level": noise_level, "noise_type": noise_type, "seed": seed},
            node_id=self.node_id,
        )
        return result


__all__ = [
    # Custom Node Set #1 (Blending)
    "LinearCalibrationNode",
    "SaturationModelNode",  # SHARED
    "SystemSaturationNode",
    "CatmullRomCurveNode",
    # Custom Node Set #2 (Synthetic Builder)
    "HybridSelectorNode",
    "ConcentrationCurveNode",
    "GoldenGridAlignNode",
    "NoiseInjectionNode",
]
