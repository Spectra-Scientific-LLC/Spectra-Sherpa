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

from typing import Any

from spectra_sherpa.app.lib import curves as curves_contract
from spectra_sherpa.app.lib import golden_grid as golden_grid_contract
from spectra_sherpa.app.lib import saturation_response as saturation_response_contract
from spectra_sherpa.app.lib import sherpa_dataset as sherpa_dataset_contract
from spectra_sherpa.app.services.dag import io_contracts as dag_io_contracts
from spectra_sherpa.app.services.dag import meta_helpers as dag_meta_helpers
from spectra_sherpa.app.services.dag.stable_execution_contract import bind_stable_execution_contract
from spectra_sherpa.execution_contract_vocabulary import (
    LifecycleKind,
    ManagedOptimizationEligibility,
    RuntimeFamily,
    WorkerCapability,
)

from ..node_base import Node, NodeMetadata, NodeParameter, NodePolicy, NodeResult, PortMetadata, register_node
from . import custom_contracts
from .custom_contracts import (
    build_catmull_rom_curve_result,
    build_concentration_curve_result,
    build_golden_grid_alignment_result,
    build_hybrid_selector_result,
    build_linear_calibration_result,
    build_noise_injection_result,
    build_saturation_model_result,
    build_system_saturation_result,
    canonical_catmull_rom_curve_parameters,
    canonical_concentration_curve_parameters,
    canonical_golden_grid_parameters,
    canonical_hybrid_selector_parameters,
    canonical_linear_calibration_parameters,
    canonical_noise_injection_parameters,
    canonical_saturation_model_parameters,
    canonical_system_saturation_parameters,
)
from .preprocessing import wavenumber_align_node as wavenumber_align_contract

# ═══════════════════════════════════════════════════════════════════════════════
# CUSTOM NODE SET #1: BLENDING NODES
# ═══════════════════════════════════════════════════════════════════════════════


@register_node
class LinearCalibrationNode(Node):
    """
    Linear Calibration Model

    Evaluates an explicitly supplied affine Beer--Lambert calibration:
    A = slope * C + intercept.

    Part of Custom Node Set #1 (Blending).
    """

    metadata = NodeMetadata(
        policy=NodePolicy(),
        node_type="custom.linear_calibration",
        category="custom",
        label="Linear Calibration",
        description="Apply an explicit affine Beer-Lambert calibration without inferred coefficients",
        parameters=[
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
                description="Unit of the input concentrations; must exactly match calibration metadata",
                required=True,
            ),
        ],
        input_types=["SpectralDataset", "TargetMatrix"],
        input_ports=[
            PortMetadata(
                name="spectrum",
                type_ref="spectrasherpa://types/SpectralDataset/1.0",
                required=True,
                label="Spectrum",
                description="Pure component spectrum with calibration metadata",
            ),
            PortMetadata(
                name="concentrations",
                type_ref="spectrasherpa://types/TargetMatrix/1.0",
                required=True,
                label="Concentrations",
                description="Finite non-negative concentrations in the declared calibration unit",
            ),
        ],
        output_type="SpectralDataset",
        output_ports=[
            PortMetadata(
                name="default",
                type_ref="spectrasherpa://types/SpectralDataset/1.0",
                required=True,
                label="Calibrated Spectra",
                description="Affine calibrated absorbance for every supplied concentration",
            )
        ],
        canonical_parameter_validator=canonical_linear_calibration_parameters,
    )

    async def execute(
        self,
        spectrum: Any,
        concentrations: Any,
        **kwargs,
    ) -> NodeResult:
        result, diagnostics = build_linear_calibration_result(
            spectrum,
            concentrations,
            self.metadata.canonicalize_parameters(self.parameters),
            node_id=self.node_id,
        )
        return NodeResult(outputs={"default": result}, diagnostics=diagnostics)

    def supports_python_export(self) -> bool:
        return True

    def generate_python(self, inputs, indent="    ", use_scp=True):
        del use_scp
        spectrum = inputs.get("spectrum", "spectrum")
        concentrations = inputs.get("concentrations", "concentrations")
        parameters = self.metadata.canonicalize_parameters(self.parameters)
        return [
            f"{indent}from spectra_sherpa.app.services.dag.nodes.custom_contracts "
            "import build_linear_calibration_result",
            f"{indent}_linear_result, _linear_diagnostics = build_linear_calibration_result(",
            f"{indent}    {spectrum}, {concentrations}, {parameters!r}, node_id={self.node_id!r}",
            f"{indent})",
            f"{indent}results[{self.node_id!r}] = _linear_result",
        ]


@register_node
class SaturationModelNode(Node):
    """
    Saturation Calibration Model (SHARED)

    Evaluates the published saturation transition for non-linear absorbance:
    A = s * [tanh((c*C/s)^p)]^(1/p)

    SHARED between Custom Node Set #1 (Blending) and #2 (Synthetic).
    """

    metadata = NodeMetadata(
        policy=NodePolicy(),
        node_type="custom.saturation_model",
        category="custom",
        label="Saturation Model",
        description="Evaluate an explicit feature-wise nonlinear saturation calibration",
        parameters=[
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
                description="Unit shared by sensitivity coefficients, concentrations, and calibration bounds",
                required=True,
            ),
        ],
        input_types=["SpectralDataset", "Array1D", "Array1D", "TargetMatrix", "Scalar", "Scalar"],
        input_ports=[
            PortMetadata(
                name="sensitivity",
                type_ref="spectrasherpa://types/SpectralDataset/1.0",
                required=True,
                label="Sensitivity Spectrum",
                description="Exactly one non-negative sensitivity value c per feature",
            ),
            PortMetadata(
                name="saturation_levels",
                type_ref="spectrasherpa://types/Array1D/1.0",
                required=True,
                label="Saturation Levels",
                description="One strictly positive saturation plateau s per feature",
            ),
            PortMetadata(
                name="shape_exponents",
                type_ref="spectrasherpa://types/Array1D/1.0",
                required=True,
                label="Shape Exponents",
                description="One strictly positive transition exponent p per feature",
            ),
            PortMetadata(
                name="concentrations",
                type_ref="spectrasherpa://types/TargetMatrix/1.0",
                required=True,
                label="Concentrations",
                description="Finite non-negative concentrations inside the declared calibration range",
            ),
            PortMetadata(
                name="calibration_minimum",
                type_ref="spectrasherpa://types/Scalar/1.0",
                required=True,
                label="Calibration Minimum",
                description="Inclusive lower concentration bound validated by the calibration",
            ),
            PortMetadata(
                name="calibration_maximum",
                type_ref="spectrasherpa://types/Scalar/1.0",
                required=True,
                label="Calibration Maximum",
                description="Inclusive upper concentration bound validated by the calibration",
            ),
        ],
        output_type="SpectralDataset",
        output_ports=[
            PortMetadata(
                name="default",
                type_ref="spectrasherpa://types/SpectralDataset/1.0",
                required=True,
                label="Saturated Spectra",
                description="Published nonlinear response for every admitted concentration",
            )
        ],
        canonical_parameter_validator=canonical_saturation_model_parameters,
    )

    async def execute(
        self,
        sensitivity: Any,
        saturation_levels: Any,
        shape_exponents: Any,
        concentrations: Any,
        calibration_minimum: Any,
        calibration_maximum: Any,
        **kwargs,
    ) -> NodeResult:
        result, diagnostics = build_saturation_model_result(
            sensitivity,
            saturation_levels,
            shape_exponents,
            concentrations,
            calibration_minimum,
            calibration_maximum,
            self.metadata.canonicalize_parameters(self.parameters),
            node_id=self.node_id,
        )
        return NodeResult(outputs={"default": result}, diagnostics=diagnostics)

    def supports_python_export(self) -> bool:
        return True

    def generate_python(self, inputs, indent="    ", use_scp=True):
        del use_scp
        parameters = self.metadata.canonicalize_parameters(self.parameters)
        return [
            f"{indent}from spectra_sherpa.app.services.dag.nodes.custom_contracts import build_saturation_model_result",
            f"{indent}_saturation_result, _saturation_diagnostics = build_saturation_model_result(",
            f"{indent}    {inputs.get('sensitivity', 'sensitivity')},",
            f"{indent}    {inputs.get('saturation_levels', 'saturation_levels')},",
            f"{indent}    {inputs.get('shape_exponents', 'shape_exponents')},",
            f"{indent}    {inputs.get('concentrations', 'concentrations')},",
            f"{indent}    {inputs.get('calibration_minimum', 'calibration_minimum')},",
            f"{indent}    {inputs.get('calibration_maximum', 'calibration_maximum')},",
            f"{indent}    {parameters!r}, node_id={self.node_id!r},",
            f"{indent})",
            f"{indent}results[{self.node_id!r}] = _saturation_result",
        ]


@register_node
class SystemSaturationNode(Node):
    """
    System-Level Saturation

    Applies detector saturation after Beer's Law superposition:
    A_measured = s_sys * [tanh((A_total/s_sys)^p_sys)]^(1/p_sys)

    Part of Custom Node Set #1 (Blending).
    """

    metadata = NodeMetadata(
        policy=NodePolicy(),
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
                description="Maximum absorbance the detector can measure",
            ),
            NodeParameter(
                name="p_system",
                label="Saturation Exponent",
                param_type="number",
                default=1.0,
                min_value=0.1,
                description="Shape exponent controlling transition sharpness",
            ),
        ],
        input_types=["SherpaDataset"],
        input_ports=[
            PortMetadata(
                name="default",
                type_ref="spectrasherpa://types/SpectralDataset/1.0",
                required=True,
                label="Input Spectra",
                description="Blended absorbance spectra to saturate",
            ),
        ],
        output_type="SpectralDataset",
        output_ports=[
            PortMetadata(
                name="default",
                type_ref="spectrasherpa://types/SpectralDataset/1.0",
                required=True,
                label="Saturated Spectra",
                description="Detector-limited spectra with the input axes and units preserved",
            )
        ],
        canonical_parameter_validator=canonical_system_saturation_parameters,
    )

    async def execute(self, input_data: Any, **kwargs) -> NodeResult:
        """
        Apply system-level saturation to absorbance spectra.

        Parameters
        ----------
        input_data : SherpaDataset
            Blended absorbance spectra (potentially exceeding detector range)

        Returns
        -------
        SherpaDataset
            Saturated spectra (bounded by detector limits)
        """
        del kwargs
        result, diagnostics = build_system_saturation_result(
            input_data,
            self.metadata.canonicalize_parameters(self.parameters),
            node_id=self.node_id,
        )
        return NodeResult(outputs={"default": result}, diagnostics=diagnostics)

    def supports_python_export(self) -> bool:
        return True

    def generate_python(self, inputs, indent="    ", use_scp=True):
        del use_scp
        source = next(iter(inputs.values())) if inputs else "input_data"
        parameters = self.metadata.canonicalize_parameters(self.parameters)
        return [
            f"{indent}from spectra_sherpa.app.services.dag.nodes.custom_contracts "
            "import build_system_saturation_result",
            f"{indent}_system_result, _system_diagnostics = build_system_saturation_result(",
            f"{indent}    {source}, {parameters!r}, node_id={self.node_id!r}",
            f"{indent})",
            f"{indent}results[{self.node_id!r}] = _system_result",
        ]


@register_node
class CatmullRomCurveNode(Node):
    """
    Catmull-Rom Spline Curve Generator

    Generates smooth concentration curves from control points using
    Catmull-Rom spline interpolation.

    Part of Custom Node Set #1 (Blending).
    """

    metadata = NodeMetadata(
        policy=NodePolicy(),
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
                max_value=100000,
                max_value_reason="Bounds interactive curve evaluation and serialized output size.",
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
        input_ports=[],
        output_type="Array1D",
        output_ports=[
            PortMetadata(
                name="default",
                type_ref="spectrasherpa://types/Array1D/1.0",
                required=True,
                label="Concentration Curve",
                description="Catmull-Rom concentration values sampled on the normalized 0-100 axis",
            )
        ],
        canonical_parameter_validator=canonical_catmull_rom_curve_parameters,
    )

    async def execute(self, **kwargs) -> NodeResult:
        """
        Generate a Catmull-Rom spline curve from control points.

        Returns
        -------
        np.ndarray
            Concentration curve with n_points values
        """
        del kwargs
        curve, diagnostics = build_catmull_rom_curve_result(self.metadata.canonicalize_parameters(self.parameters))
        return NodeResult(outputs={"default": curve}, diagnostics=diagnostics)

    def supports_python_export(self) -> bool:
        return True

    def generate_python(self, inputs, indent="    ", use_scp=True):
        del inputs, use_scp
        parameters = self.metadata.canonicalize_parameters(self.parameters)
        return [
            f"{indent}from spectra_sherpa.app.services.dag.nodes.custom_contracts "
            "import build_catmull_rom_curve_result",
            f"{indent}_curve_result, _curve_diagnostics = build_catmull_rom_curve_result({parameters!r})",
            f"{indent}results[{self.node_id!r}] = _curve_result",
        ]


# ═══════════════════════════════════════════════════════════════════════════════
# CUSTOM NODE SET #2: SYNTHETIC DATA BUILDER NODES
# ═══════════════════════════════════════════════════════════════════════════════


@register_node
class HybridSelectorNode(Node):
    """
    Hybrid Model Selector

    Applies an upstream per-feature decision between linear and saturation
    results.  This node never decides which model is scientifically valid.

    Part of Custom Node Set #2 (Synthetic Builder).
    """

    metadata = NodeMetadata(
        policy=NodePolicy(),
        node_type="custom.hybrid_selector",
        category="custom",
        label="Explicit Hybrid Composition",
        description="Apply an explicit per-feature mask to linear and saturation results",
        parameters=[],
        input_types=["SpectralDataset", "SpectralDataset", "Array1D"],
        input_ports=[
            PortMetadata(
                name="linear_result",
                type_ref="spectrasherpa://types/SpectralDataset/1.0",
                required=True,
                label="Linear Result",
                description="Output from LinearCalibrationNode",
            ),
            PortMetadata(
                name="saturation_result",
                type_ref="spectrasherpa://types/SpectralDataset/1.0",
                required=True,
                label="Saturation Result",
                description="Output from SaturationModelNode",
            ),
            PortMetadata(
                name="model_mask",
                type_ref="spectrasherpa://types/Array1D/1.0",
                required=True,
                label="Model Mask",
                description="One explicit decision per feature: zero selects linear, one selects saturation",
            ),
        ],
        output_type="SpectralDataset",
        output_ports=[
            PortMetadata(
                name="default",
                type_ref="spectrasherpa://types/SpectralDataset/1.0",
                required=True,
                label="Selected Spectra",
                description="Feature-wise composition selected by the supplied mask",
            )
        ],
        canonical_parameter_validator=canonical_hybrid_selector_parameters,
    )

    async def execute(
        self,
        linear_result: Any,
        saturation_result: Any,
        model_mask: Any,
        **kwargs,
    ) -> NodeResult:
        result, diagnostics = build_hybrid_selector_result(
            linear_result,
            saturation_result,
            model_mask,
            self.metadata.canonicalize_parameters(self.parameters),
            node_id=self.node_id,
        )
        return NodeResult(outputs={"default": result}, diagnostics=diagnostics)

    def supports_python_export(self) -> bool:
        return True

    def generate_python(self, inputs, indent="    ", use_scp=True):
        del use_scp
        return [
            f"{indent}from spectra_sherpa.app.services.dag.nodes.custom_contracts import build_hybrid_selector_result",
            f"{indent}_hybrid_result, _hybrid_diagnostics = build_hybrid_selector_result(",
            f"{indent}    {inputs.get('linear_result', 'linear_result')},",
            f"{indent}    {inputs.get('saturation_result', 'saturation_result')},",
            f"{indent}    {inputs.get('model_mask', 'model_mask')},",
            f"{indent}    {{}}, node_id={self.node_id!r},",
            f"{indent})",
            f"{indent}results[{self.node_id!r}] = _hybrid_result",
        ]


@register_node
class ConcentrationCurveNode(Node):
    """
    Concentration Curve Generator

    Generates concentration profiles for synthetic data:
    sigmoid, gaussian, linear, exponential, step, or constant.

    Part of Custom Node Set #2 (Synthetic Builder).
    """

    metadata = NodeMetadata(
        policy=NodePolicy(),
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
                max_value=100000,
                max_value_reason="Bounds interactive curve evaluation and serialized output size.",
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
                max_value_reason="The center is expressed on the normalized zero-to-one time axis.",
                description="Center position for sigmoid/gaussian (0-1)",
            ),
            NodeParameter(
                name="width",
                label="Width",
                param_type="number",
                default=0.1,
                min_value=0.01,
                max_value=1.0,
                max_value_reason="The width is expressed as a fraction of the normalized time span.",
                description="Width parameter for sigmoid/gaussian",
            ),
        ],
        input_types=[],  # No inputs - this is a generator
        input_ports=[],
        output_type="Array1D",
        output_ports=[
            PortMetadata(
                name="default",
                type_ref="spectrasherpa://types/Array1D/1.0",
                required=True,
                label="Concentration Curve",
                description="Concentration values sampled on the normalized 0-1 time axis",
            )
        ],
        canonical_parameter_validator=canonical_concentration_curve_parameters,
    )

    async def execute(self, **kwargs) -> NodeResult:
        """
        Generate a concentration curve.

        Returns
        -------
        np.ndarray
            Concentration values at each time point
        """
        del kwargs
        curve, diagnostics = build_concentration_curve_result(self.metadata.canonicalize_parameters(self.parameters))
        return NodeResult(outputs={"default": curve}, diagnostics=diagnostics)

    def supports_python_export(self) -> bool:
        return True

    def generate_python(self, inputs, indent="    ", use_scp=True):
        del inputs, use_scp
        parameters = self.metadata.canonicalize_parameters(self.parameters)
        return [
            f"{indent}from spectra_sherpa.app.services.dag.nodes.custom_contracts "
            "import build_concentration_curve_result",
            f"{indent}_curve_result, _curve_diagnostics = build_concentration_curve_result({parameters!r})",
            f"{indent}results[{self.node_id!r}] = _curve_result",
        ]


@register_node
class GoldenGridAlignNode(Node):
    """
    Golden Grid Wavenumber Alignment

    Aligns multiple spectra to a common wavenumber grid using
    the "golden grid" approach.

    Part of Custom Node Set #2 (Synthetic Builder).
    """

    metadata = NodeMetadata(
        policy=NodePolicy(),
        node_type="custom.golden_grid_align",
        category="custom",
        label="Golden Grid Align",
        description=(
            "Align and stack spectra on measured coordinates within their common cm-1 coverage. "
            "The node never extrapolates and never represents interpolation as added resolution."
        ),
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
                description="Tolerance for merging near-duplicate wavenumbers",
                required=True,
            ),
            NodeParameter(
                name="coverage_policy",
                label="Coverage Policy",
                param_type="select",
                options=["common_overlap"],
                default="common_overlap",
                description="Use only the spectral interval measured by every connected input.",
                required=True,
            ),
            NodeParameter(
                name="extrapolation",
                label="Extrapolation Policy",
                param_type="select",
                options=["reject"],
                default="reject",
                description="Reject any operation that would fabricate signal outside measured coverage.",
                required=True,
            ),
            NodeParameter(
                name="max_upsampling_factor",
                label="Maximum Upsampling Factor",
                param_type="number",
                default=1.0,
                min_value=1.0,
                description=(
                    "Largest explicitly admitted interpolation-density increase relative to any input. "
                    "Increasing it does not add measured spectral resolution."
                ),
                required=True,
            ),
        ],
        input_types=["SherpaDataset"],  # Variable number of inputs
        input_ports=[
            PortMetadata(
                name="default",
                type_ref="spectrasherpa://types/SpectralDataset/1.0",
                required=True,
                label="Input Spectra",
                description="Spectra to align (multiple edges accepted)",
                variadic=True,
                accepted_data_roles=["X_spectra"],
            ),
        ],
        output_type="SpectralDataset",
        output_ports=[
            PortMetadata(
                name="default",
                type_ref="spectrasherpa://types/SpectralDataset/1.0",
                required=True,
                label="Aligned and Stacked Spectra",
                description="All input samples stacked on one common measured cm-1 grid.",
                accepted_data_roles=["X_spectra"],
            )
        ],
        canonical_parameter_validator=canonical_golden_grid_parameters,
    )

    async def execute(self, input_data: Any = None, default: Any = None, **kwargs: Any) -> NodeResult:
        del kwargs
        spectra = input_data if input_data is not None else default
        result, diagnostics = build_golden_grid_alignment_result(
            spectra,
            self.metadata.canonicalize_parameters(self.parameters),
            node_id=self.node_id,
        )
        return NodeResult(outputs={"default": result}, diagnostics=diagnostics)

    def supports_python_export(self) -> bool:
        return True

    def generate_python(self, inputs, indent="    ", use_scp=True):
        del use_scp
        spectra = inputs.get("default", "input_data")
        if isinstance(spectra, list):
            spectra = "[" + ", ".join(spectra) + "]"
        parameters = self.metadata.canonicalize_parameters(self.parameters)
        return [
            f"{indent}from spectra_sherpa.app.services.dag.nodes.custom_contracts "
            "import build_golden_grid_alignment_result",
            f"{indent}_golden_result, _golden_diagnostics = build_golden_grid_alignment_result(",
            f"{indent}    {spectra}, {parameters!r}, node_id={self.node_id!r}",
            f"{indent})",
            f"{indent}results[{self.node_id!r}] = _golden_result",
        ]


@register_node
class NoiseInjectionNode(Node):
    """
    Gaussian Noise Injection

    Adds realistic Gaussian noise to synthetic spectra for
    training data augmentation and algorithm testing.

    Part of Custom Node Set #2 (Synthetic Builder).
    """

    metadata = NodeMetadata(
        policy=NodePolicy(),
        node_type="custom.noise_injection",
        category="custom",
        label="Noise Injection",
        description="Add reproducible independent zero-mean Gaussian perturbations to spectra",
        parameters=[
            NodeParameter(
                name="noise_level",
                label="Noise Level",
                param_type="number",
                default=0.01,
                min_value=0.0,
                step=0.001,
                description="Absolute standard deviation or a fraction of the input RMS",
                required=True,
            ),
            NodeParameter(
                name="noise_type",
                label="Noise Type",
                param_type="select",
                options=["absolute", "relative_rms"],
                default="relative_rms",
                description="Interpret noise_level as an absolute standard deviation or as a fraction of RMS",
                required=True,
            ),
            NodeParameter(
                name="seed",
                label="Random Seed",
                param_type="number",
                default=42,
                min_value=0,
                max_value=4_294_967_295,
                max_value_reason="NumPy Generator seeds are bounded to the portable unsigned 32-bit domain.",
                description="Required invocation-local random seed",
                required=True,
            ),
        ],
        input_types=["SpectralDataset"],
        input_ports=[
            PortMetadata(
                name="default",
                type_ref="spectrasherpa://types/SpectralDataset/1.0",
                required=True,
                label="Input Spectra",
                description="Spectral data to process",
            ),
        ],
        output_ports=[
            PortMetadata(
                name="default",
                type_ref="spectrasherpa://types/SpectralDataset/1.0",
                required=True,
                label="Perturbed Spectra",
                description="Input spectra plus the declared seeded Gaussian perturbation",
                accepted_data_roles=["X_spectra"],
            )
        ],
        output_type="SpectralDataset",
        canonical_parameter_validator=canonical_noise_injection_parameters,
    )

    async def execute(self, input_data: Any = None, default: Any = None, **kwargs: Any) -> NodeResult:
        del kwargs
        source = input_data if input_data is not None else default
        result, diagnostics = build_noise_injection_result(
            source,
            self.metadata.canonicalize_parameters(self.parameters),
            node_id=self.node_id,
        )
        return NodeResult(outputs={"default": result}, diagnostics=diagnostics)

    def supports_python_export(self) -> bool:
        return True

    def generate_python(self, inputs, indent="    ", use_scp=True):
        del use_scp
        source = next(iter(inputs.values())) if inputs else "input_data"
        parameters = self.metadata.canonicalize_parameters(self.parameters)
        return [
            f"{indent}from spectra_sherpa.app.services.dag.nodes.custom_contracts import build_noise_injection_result",
            f"{indent}_noise_result, _noise_diagnostics = build_noise_injection_result(",
            f"{indent}    {source}, {parameters!r}, node_id={self.node_id!r}",
            f"{indent})",
            f"{indent}results[{self.node_id!r}] = _noise_result",
        ]


bind_stable_execution_contract(
    LinearCalibrationNode,
    runtime_family=RuntimeFamily.SHERPA_NATIVE,
    lifecycle_kind=LifecycleKind.STATELESS_TRANSFORM,
    implementation_id="spectrasherpa.custom.linear_calibration",
    implementation_version="1.0.0",
    required_worker_capabilities=(WorkerCapability.READ_DATASET,),
    managed_optimization_eligibility=(ManagedOptimizationEligibility.LOCAL,),
    sample_effect="generates_samples",
    feature_effect="preserves_features",
    axis_effect="preserves_axis",
    unit_effect="changes_units",
    resource_hints={"timeout_seconds": 10, "cpu_seconds": 10, "memory_bytes": 536_870_912},
    license_id="Apache-2.0",
    help_reference="docs/nodes/data.md",
    implementation_modules=(
        custom_contracts,
        dag_io_contracts,
        dag_meta_helpers,
        sherpa_dataset_contract,
    ),
    implementation_distributions=("numpy",),
    runtime_requirements=(("numpy", "1.26.4"),),
    citations=(
        "IUPAC Gold Book, Beer-Lambert law, doi:10.1351/goldbook.B00626",
        "Mayerhoefer et al., ChemPhysChem 2020, doi:10.1002/cphc.202000464",
    ),
)


bind_stable_execution_contract(
    GoldenGridAlignNode,
    runtime_family=RuntimeFamily.SHERPA_NATIVE,
    lifecycle_kind=LifecycleKind.STATELESS_TRANSFORM,
    implementation_id="spectrasherpa.custom.golden_grid_align",
    implementation_version="1.0.0",
    required_worker_capabilities=(WorkerCapability.READ_DATASET,),
    managed_optimization_eligibility=(ManagedOptimizationEligibility.LOCAL,),
    sample_effect="generates_samples",
    feature_effect="transforms_features",
    axis_effect="changes_axis",
    unit_effect="requires_compatible_units",
    resource_hints={"timeout_seconds": 60, "cpu_seconds": 60, "memory_bytes": 1_073_741_824},
    license_id="Apache-2.0",
    help_reference="docs/nodes/data.md",
    implementation_modules=(
        custom_contracts,
        dag_io_contracts,
        dag_meta_helpers,
        golden_grid_contract,
        sherpa_dataset_contract,
        wavenumber_align_contract,
    ),
    implementation_distributions=("numpy", "scipy"),
    runtime_requirements=(("numpy", "1.26.4"), ("scipy", "1.17.1")),
    citations=(
        "Fritsch and Butland, SIAM Journal on Scientific and Statistical Computing 1984, doi:10.1137/0905021",
        "Shannon, Proceedings of the IRE 1949, doi:10.1109/JRPROC.1949.232969",
    ),
)


bind_stable_execution_contract(
    SaturationModelNode,
    runtime_family=RuntimeFamily.SHERPA_NATIVE,
    lifecycle_kind=LifecycleKind.STATELESS_TRANSFORM,
    implementation_id="spectrasherpa.custom.saturation_model",
    implementation_version="1.0.0",
    required_worker_capabilities=(WorkerCapability.READ_DATASET,),
    managed_optimization_eligibility=(ManagedOptimizationEligibility.LOCAL,),
    sample_effect="generates_samples",
    feature_effect="preserves_features",
    axis_effect="preserves_axis",
    unit_effect="changes_units",
    resource_hints={"timeout_seconds": 10, "cpu_seconds": 10, "memory_bytes": 536_870_912},
    license_id="Apache-2.0",
    help_reference="docs/nodes/data.md",
    implementation_modules=(
        custom_contracts,
        dag_io_contracts,
        dag_meta_helpers,
        saturation_response_contract,
        sherpa_dataset_contract,
    ),
    implementation_distributions=("numpy",),
    runtime_requirements=(("numpy", "1.26.4"),),
    citations=("Rodionova and Pomerantsev, Analytical Methods 2016, doi:10.1039/C5AY02393A, equation 13",),
)


bind_stable_execution_contract(
    HybridSelectorNode,
    runtime_family=RuntimeFamily.SHERPA_NATIVE,
    lifecycle_kind=LifecycleKind.STATELESS_TRANSFORM,
    implementation_id="spectrasherpa.custom.hybrid_selector",
    implementation_version="1.0.0",
    required_worker_capabilities=(WorkerCapability.READ_DATASET,),
    managed_optimization_eligibility=(ManagedOptimizationEligibility.LOCAL,),
    sample_effect="preserves_samples",
    feature_effect="preserves_features",
    axis_effect="preserves_axis",
    unit_effect="preserves_units",
    resource_hints={"timeout_seconds": 10, "cpu_seconds": 10, "memory_bytes": 536_870_912},
    license_id="Apache-2.0",
    help_reference="docs/nodes/data.md",
    implementation_modules=(
        custom_contracts,
        dag_io_contracts,
        dag_meta_helpers,
        sherpa_dataset_contract,
    ),
    implementation_distributions=("numpy",),
    runtime_requirements=(("numpy", "1.26.4"),),
    citations=(
        "IUPAC Gold Book, Beer-Lambert law, doi:10.1351/goldbook.B00626",
        "Rodionova and Pomerantsev, Analytical Methods 2016, doi:10.1039/C5AY02393A",
    ),
)


bind_stable_execution_contract(
    NoiseInjectionNode,
    runtime_family=RuntimeFamily.SHERPA_NATIVE,
    lifecycle_kind=LifecycleKind.STATELESS_TRANSFORM,
    implementation_id="spectrasherpa.custom.noise_injection",
    implementation_version="1.0.0",
    required_worker_capabilities=(WorkerCapability.READ_DATASET,),
    managed_optimization_eligibility=(ManagedOptimizationEligibility.LOCAL,),
    sample_effect="preserves_samples",
    feature_effect="preserves_features",
    axis_effect="preserves_axis",
    unit_effect="preserves_units",
    resource_hints={"timeout_seconds": 10, "cpu_seconds": 10, "memory_bytes": 536_870_912},
    license_id="Apache-2.0",
    help_reference="docs/nodes/data.md",
    implementation_modules=(
        custom_contracts,
        dag_io_contracts,
        dag_meta_helpers,
        sherpa_dataset_contract,
    ),
    implementation_distributions=("numpy",),
    runtime_requirements=(("numpy", "1.26.4"),),
    citations=("CRAN tdaunif::add_noise, independent multivariate Gaussian perturbation",),
    deterministic=False,
    seed_parameter="seed",
)


bind_stable_execution_contract(
    SystemSaturationNode,
    runtime_family=RuntimeFamily.SHERPA_NATIVE,
    lifecycle_kind=LifecycleKind.STATELESS_TRANSFORM,
    implementation_id="spectrasherpa.custom.system_saturation",
    implementation_version="1.0.0",
    required_worker_capabilities=(WorkerCapability.READ_DATASET,),
    managed_optimization_eligibility=(ManagedOptimizationEligibility.LOCAL,),
    sample_effect="preserves_samples",
    feature_effect="preserves_features",
    axis_effect="preserves_axis",
    unit_effect="preserves_units",
    resource_hints={"timeout_seconds": 10, "cpu_seconds": 10, "memory_bytes": 536_870_912},
    license_id="Apache-2.0",
    help_reference="docs/nodes/data.md",
    implementation_modules=(
        custom_contracts,
        dag_io_contracts,
        dag_meta_helpers,
        saturation_response_contract,
        sherpa_dataset_contract,
    ),
    implementation_distributions=("numpy",),
    runtime_requirements=(("numpy", "1.26.4"),),
    citations=("Rodionova and Pomerantsev, Analytical Methods 2016, doi:10.1039/C5AY02393A, equation 13",),
)


bind_stable_execution_contract(
    CatmullRomCurveNode,
    runtime_family=RuntimeFamily.SHERPA_NATIVE,
    lifecycle_kind=LifecycleKind.DATA_SOURCE,
    implementation_id="spectrasherpa.custom.catmull_rom_curve",
    implementation_version="1.0.0",
    required_worker_capabilities=(),
    managed_optimization_eligibility=(ManagedOptimizationEligibility.LOCAL,),
    sample_effect="generates_samples",
    feature_effect="generates_features",
    axis_effect="changes_axis",
    unit_effect="changes_units",
    resource_hints={"timeout_seconds": 10, "cpu_seconds": 10, "memory_bytes": 536_870_912},
    license_id="Apache-2.0",
    help_reference="docs/nodes/data.md",
    implementation_modules=(custom_contracts, curves_contract),
    implementation_distributions=("numpy",),
    runtime_requirements=(("numpy", "1.26.4"),),
    citations=(
        "Catmull and Rom, A Class of Local Interpolating Splines, Computer Aided Geometric Design 1974, "
        "doi:10.1016/B978-0-12-079050-0.50020-5",
    ),
)


bind_stable_execution_contract(
    ConcentrationCurveNode,
    runtime_family=RuntimeFamily.SHERPA_NATIVE,
    lifecycle_kind=LifecycleKind.DATA_SOURCE,
    implementation_id="spectrasherpa.custom.concentration_curve",
    implementation_version="1.0.0",
    required_worker_capabilities=(),
    managed_optimization_eligibility=(ManagedOptimizationEligibility.LOCAL,),
    sample_effect="generates_samples",
    feature_effect="generates_features",
    axis_effect="changes_axis",
    unit_effect="changes_units",
    resource_hints={"timeout_seconds": 10, "cpu_seconds": 10, "memory_bytes": 536_870_912},
    license_id="Apache-2.0",
    help_reference="docs/nodes/data.md",
    implementation_modules=(custom_contracts, curves_contract),
    implementation_distributions=("numpy",),
    runtime_requirements=(("numpy", "1.26.4"),),
    citations=(
        "NIST/SEMATECH e-Handbook of Statistical Methods, Normal Distribution, "
        "https://www.itl.nist.gov/div898/handbook/eda/section3/eda3661.htm",
        "NIST Dataplot Reference Manual, Logistic CDF, "
        "https://www.itl.nist.gov/div898/software/dataplot/refman2/ch8/logcdf.pdf",
        "NIST/SEMATECH e-Handbook of Statistical Methods, Exponential Distribution, "
        "https://www.itl.nist.gov/div898/handbook/eda/section3/eda3667.htm",
    ),
)


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
