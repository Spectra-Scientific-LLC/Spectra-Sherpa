"""Canonical, explicit operations for constructing bilinear spectral mixtures.

The three nodes in this module deliberately expose each scientific decision in
the DAG.  ``synthesis.species`` assigns one identity to one pure response,
``synthesis.merge`` forms the pure-response matrix, and ``synthesis.blend``
evaluates the standard bilinear model ``D = C @ S``.  Curve generation, noise,
non-linear response, alignment, and path-length calibration are separate nodes;
none is hidden inside the mixture operation.
"""

from __future__ import annotations

import math
from copy import deepcopy
from typing import Any, Mapping

import numpy as np

from spectra_sherpa.app.lib import sherpa_dataset as sherpa_dataset_contract
from spectra_sherpa.app.lib.axes import SampleAxis
from spectra_sherpa.app.lib.sherpa_dataset import TargetContext
from spectra_sherpa.app.services.dag import io_contracts as dag_io_contracts
from spectra_sherpa.app.services.dag import meta_helpers as dag_meta_helpers
from spectra_sherpa.app.services.dag.io_contracts import build_dataset_like, coerce_to_sherpa, to_numpy_2d
from spectra_sherpa.app.services.dag.meta_helpers import add_processing_step
from spectra_sherpa.app.services.dag.node_base import (
    Node,
    NodeMetadata,
    NodeParameter,
    NodePolicy,
    NodeResult,
    PortMetadata,
    register_node,
)
from spectra_sherpa.app.services.dag.stable_execution_contract import bind_stable_execution_contract
from spectra_sherpa.core import spectra_meta as spectra_meta_contract
from spectra_sherpa.core.spectra_meta import (
    DataProvenance,
    PhysicalState,
    SourceType,
    SpeciesInfo,
    SpectraMeta,
)
from spectra_sherpa.execution_contract_vocabulary import (
    LifecycleKind,
    ManagedOptimizationEligibility,
    RuntimeFamily,
    WorkerCapability,
)

_SPECTRA_META_FIELDS = frozenset(SpectraMeta.model_fields)
_BILINEAR_REFERENCE = (
    "de Juan, A.; Tauler, R. Multivariate Curve Resolution (MCR) from 2000: "
    "Progress in Concepts and Applications. Critical Reviews in Analytical Chemistry "
    "2006, 36, 163-176. https://doi.org/10.1080/10408340600970005"
)
_BEER_LAMBERT_REFERENCE = "IUPAC Gold Book, Beer-Lambert law, doi:10.1351/goldbook.B00626"
_HITRAN_REFERENCE = (
    "Gordon et al., The HITRAN2020 molecular spectroscopic database, Journal of Quantitative "
    "Spectroscopy and Radiative Transfer 2022, doi:10.1016/j.jqsrt.2021.107949"
)
_NIST_QUANT_IR_REFERENCE = "NIST Chemistry WebBook, Quantitative Infrared Database, https://webbook.nist.gov/"
_PPM_REFERENCE = (
    "IUPAC Green Book, Quantities, Units and Symbols in Physical Chemistry, 3rd ed., " "doi:10.1039/9781847557889"
)
_BOLTZMANN_J_PER_K = 1.380649e-23
_ATM_PA = 101325.0


def _canonical_species_parameters(parameters: Mapping[str, object]) -> dict[str, object]:
    """Return one closed chemical-identity annotation."""

    if set(parameters) != {"species_name", "molar_absorptivity"}:
        raise ValueError("species parameters must contain exactly species_name and molar_absorptivity")
    name = parameters["species_name"]
    if not isinstance(name, str) or not name or name != name.strip():
        raise ValueError("species_name must be non-empty text without surrounding whitespace")
    molar_absorptivity = parameters["molar_absorptivity"]
    if molar_absorptivity is not None:
        if (
            isinstance(molar_absorptivity, bool)
            or not isinstance(molar_absorptivity, (int, float))
            or not math.isfinite(molar_absorptivity)
            or molar_absorptivity <= 0
        ):
            raise ValueError("molar_absorptivity must be null or a finite positive number")
        molar_absorptivity = float(molar_absorptivity)
    return {"species_name": name, "molar_absorptivity": molar_absorptivity}


def _canonical_no_parameters(parameters: Mapping[str, object]) -> dict[str, object]:
    """Reject every hidden scientific switch for merge and blend."""

    if parameters:
        names = ", ".join(sorted(str(name) for name in parameters))
        raise ValueError(f"this canonical operation has no parameters; received: {names}")
    return {}


def _finite_positive_parameter(parameters: Mapping[str, object], name: str) -> float:
    value = parameters[name]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be a finite positive number")
    normalized = float(value)
    if not math.isfinite(normalized) or normalized <= 0.0:
        raise ValueError(f"{name} must be a finite positive number")
    return normalized


def _canonical_nist_response_parameters(parameters: Mapping[str, object]) -> dict[str, object]:
    if set(parameters) != {"pathlength_cm"}:
        raise ValueError("NIST response parameters must contain exactly pathlength_cm")
    return {"pathlength_cm": _finite_positive_parameter(parameters, "pathlength_cm")}


def _canonical_hitran_response_parameters(parameters: Mapping[str, object]) -> dict[str, object]:
    expected = {"pathlength_cm", "pressure_atm", "temperature_k"}
    if set(parameters) != expected:
        raise ValueError(
            "HITRAN response parameters must contain exactly pathlength_cm, pressure_atm, and temperature_k"
        )
    return {name: _finite_positive_parameter(parameters, name) for name in sorted(expected)}


def _strict_spectra_meta(dataset: Any, *, context: str, required: bool) -> SpectraMeta | None:
    """Read the closed structured metadata rather than silently repairing it."""

    payload = dataset.meta.get("spectra")
    if payload is None:
        if required:
            raise ValueError(f"{context} requires structured spectra metadata")
        return None
    if not isinstance(payload, dict) or not payload:
        raise ValueError(f"{context} spectra metadata must be a non-empty mapping")
    extra = set(payload) - _SPECTRA_META_FIELDS
    if extra:
        rendered = ", ".join(sorted(extra))
        raise ValueError(f"{context} spectra metadata contains unknown fields: {rendered}")
    try:
        return SpectraMeta.model_validate(payload)
    except Exception as exc:
        raise ValueError(f"{context} spectra metadata is malformed: {exc}") from exc


def _feature_axis_signature(dataset: Any, *, context: str) -> tuple[np.ndarray, str | None, str | None]:
    axis = dataset.feature_axis
    if axis is None or axis.values is None:
        raise ValueError(f"{context} requires an explicit numeric feature axis")
    if not isinstance(axis.title, str) or not axis.title.strip():
        raise ValueError(f"{context} requires an explicit feature-axis title")
    if not isinstance(axis.units, str) or not axis.units.strip():
        raise ValueError(f"{context} requires explicit feature-axis units")
    values = np.asarray(axis.values, dtype=np.float64)
    if values.ndim != 1 or values.shape[0] != dataset.shape[-1] or not np.isfinite(values).all():
        raise ValueError(f"{context} feature axis must be finite, one-dimensional, and match the data")
    return values, axis.title, axis.units


def _require_finite_matrix(value: Any, *, context: str) -> np.ndarray:
    matrix = to_numpy_2d(value, name=context)
    if matrix.shape[0] < 1 or matrix.shape[1] < 1:
        raise ValueError(f"{context} must be a non-empty matrix")
    if not np.isfinite(matrix).all():
        raise ValueError(f"{context} must contain only finite values")
    return matrix


def build_species_result(
    input_data: Any,
    parameters: Mapping[str, object],
    *,
    node_id: str,
) -> tuple[Any, dict[str, object]]:
    """Assign one explicit species identity to one pure-response spectrum."""

    canonical = _canonical_species_parameters(parameters)
    source = coerce_to_sherpa(input_data, input_name="input_data")
    matrix = _require_finite_matrix(source, context="species input")
    if matrix.shape[0] != 1:
        raise ValueError("synthesis.species requires exactly one pure-response spectrum")
    _feature_axis_signature(source, context="species input")
    if not isinstance(source.units, str) or not source.units.strip():
        raise ValueError("species input requires explicit spectral value units")
    if source.target is not None:
        raise ValueError("synthesis.species does not accept embedded response targets")

    existing = _strict_spectra_meta(source, context="species input", required=False)
    if existing is None:
        metadata = SpectraMeta(provenance=DataProvenance(source_type=SourceType.EXPERIMENT))
    else:
        metadata = existing.model_copy(deep=True)
    species = SpeciesInfo(
        name=str(canonical["species_name"]),
        molar_absorptivity=canonical["molar_absorptivity"],
        state=PhysicalState.UNKNOWN,
    )
    metadata.species = [species]
    metadata.processing_steps = [*metadata.processing_steps, "species_annotation"]

    result = source.copy()
    result.title = species.name
    result.meta.pop("species_name", None)
    result.meta.pop("molar_absorptivity", None)
    result.meta["spectra"] = metadata.model_dump(exclude_none=True)
    add_processing_step(result, "synthesis.species", dict(canonical), node_id=node_id)
    diagnostics = {
        "species_name": species.name,
        "molar_absorptivity_declared": species.molar_absorptivity is not None,
        "pure_response_count": 1,
    }
    return result, diagnostics


def build_merge_result(input_data: Any, *, node_id: str) -> tuple[Any, dict[str, object]]:
    """Stack compatible, species-labelled pure responses without alignment."""

    if not isinstance(input_data, (list, tuple)) or not input_data:
        raise ValueError("synthesis.merge requires one or more variadic species inputs")
    datasets = [coerce_to_sherpa(value, input_name=f"input_data[{index}]") for index, value in enumerate(input_data)]
    reference_axis: tuple[np.ndarray, str | None, str | None] | None = None
    reference_units: str | None = None
    reference_role: object = None
    matrices: list[np.ndarray] = []
    species: list[SpeciesInfo] = []
    for index, dataset in enumerate(datasets):
        context = f"merge input {index}"
        matrix = _require_finite_matrix(dataset, context=context)
        if matrix.shape[0] != 1:
            raise ValueError(f"{context} must contain exactly one species response")
        if dataset.target is not None:
            raise ValueError(f"{context} must not carry embedded response targets")
        axis = _feature_axis_signature(dataset, context=context)
        if reference_axis is None:
            reference_axis = axis
            reference_units = dataset.units
            reference_role = dataset.data_role
        else:
            if not np.array_equal(axis[0], reference_axis[0]) or axis[1:] != reference_axis[1:]:
                raise ValueError("synthesis.merge requires identical feature-axis values, title, and units")
            if dataset.units != reference_units:
                raise ValueError("synthesis.merge requires identical spectral value units")
            if dataset.data_role != reference_role:
                raise ValueError("synthesis.merge requires identical input data roles")
        metadata = _strict_spectra_meta(dataset, context=context, required=True)
        assert metadata is not None
        if len(metadata.species) != 1:
            raise ValueError(f"{context} must declare exactly one species")
        matrices.append(matrix)
        species.append(metadata.species[0].model_copy(deep=True))

    species_names = [entry.name for entry in species]
    if len(species_names) != len(set(species_names)):
        raise ValueError("synthesis.merge requires unique species identities")

    stacked = np.vstack(matrices)
    result = build_dataset_like(
        stacked,
        datasets[0],
        units=reference_units,
        title="Pure-component response matrix",
        backend="numpy",
        copy_history=False,
    )
    result.target = None
    result.sample_axis = SampleAxis(labels=species_names, title="Species")
    result.meta["spectra"] = SpectraMeta(
        species=species,
        provenance=DataProvenance(source_type=SourceType.SYNTHETIC, node_id=node_id),
        processing_steps=["species_merge"],
    ).model_dump(exclude_none=True)
    add_processing_step(
        result,
        "synthesis.merge",
        {},
        node_id=node_id,
    )
    diagnostics = {
        "input_count": len(datasets),
        "species_count": len(species),
        "feature_count": stacked.shape[1],
        "alignment_performed": False,
    }
    return result, diagnostics


def build_bilinear_blend_result(
    pure_spectra: Any,
    concentrations: Any,
    *,
    node_id: str,
) -> tuple[Any, dict[str, object]]:
    """Evaluate the explicit non-negative bilinear mixture ``D = C @ S``."""

    source = coerce_to_sherpa(pure_spectra, input_name="pure_spectra")
    S = _require_finite_matrix(source, context="pure_spectra")
    _feature_axis_signature(source, context="pure_spectra")
    metadata = _strict_spectra_meta(source, context="pure_spectra", required=True)
    assert metadata is not None
    if len(metadata.species) != S.shape[0]:
        raise ValueError("pure_spectra must declare exactly one species for every response row")

    C = _require_finite_matrix(concentrations, context="concentrations")
    if C.shape[1] != S.shape[0]:
        raise ValueError("concentration columns must equal the number of pure species")
    if np.any(C < 0):
        raise ValueError("concentration coefficients must be non-negative")
    concentration_units = getattr(concentrations, "units", None)
    if concentration_units not in (None, "", "1", "fraction", "dimensionless"):
        raise ValueError("concentrations must be dimensionless coefficients for D = C @ S")

    D = C @ S
    if not np.isfinite(D).all():
        raise ValueError("bilinear mixture is not finitely representable")
    result = build_dataset_like(
        D,
        source,
        units=source.units,
        title="Bilinear synthetic mixture",
        backend="numpy",
        copy_history=False,
    )
    result.target = deepcopy(C)
    result.target_context = TargetContext(
        target_type="continuous",
        target_names=[entry.name for entry in metadata.species],
        target_units="dimensionless",
    )
    result.sample_axis = SampleAxis(values=np.arange(C.shape[0], dtype=np.float64), title="Mixture")
    result.meta["spectra"] = SpectraMeta(
        species=[entry.model_copy(deep=True) for entry in metadata.species],
        concentration_matrix=C.tolist(),
        pure_spectra_matrix=S.tolist(),
        provenance=DataProvenance(source_type=SourceType.BLEND, node_id=node_id),
        is_ground_truth=True,
        processing_steps=["bilinear_mixture"],
        custom={
            "mixture_model": {
                "schema_version": "spectrasherpa-bilinear-mixture/1",
                "equation": "D=C@S",
                "coefficient_semantics": "dimensionless_nonnegative",
            }
        },
    ).model_dump(exclude_none=True)
    add_processing_step(
        result,
        "synthesis.blend",
        {},
        node_id=node_id,
    )
    diagnostics = {
        "equation": "D=C@S",
        "mixture_count": C.shape[0],
        "species_count": S.shape[0],
        "feature_count": S.shape[1],
        "noise_added": False,
        "alignment_performed": False,
    }
    return result, diagnostics


def build_ppm_fraction_result(source: Any, *, node_id: str) -> tuple[np.ndarray, dict[str, object]]:
    """Convert an explicit parts-per-million matrix to dimensionless fraction."""

    dataset = coerce_to_sherpa(source, input_name="ppm_concentrations", allow_array=True)
    matrix = _require_finite_matrix(dataset, context="ppm_concentrations")
    if np.any(matrix < 0.0):
        raise ValueError("ppm concentrations must be non-negative")
    fraction = matrix * 1e-6
    return fraction, {
        "input_units": "ppm",
        "output_units": "dimensionless",
        "scale_factor": 1e-6,
        "node_id": node_id,
    }


def build_nist_quant_ir_response_result(
    source: Any,
    parameters: Mapping[str, object],
    *,
    node_id: str,
) -> tuple[Any, dict[str, object]]:
    """Project one NIST decadic ppm coefficient onto a unit mole-fraction response."""

    dataset = coerce_to_sherpa(source, input_name="nist_quant_ir_response")
    matrix = _require_finite_matrix(dataset, context="nist_quant_ir_response")
    _feature_axis_signature(dataset, context="nist_quant_ir_response")
    if matrix.shape[0] != 1:
        raise ValueError("NIST quantitative IR response must contain exactly one pure response")
    if dataset.units != "ppm^-1 m^-1":
        raise ValueError("NIST quantitative IR response must declare units='ppm^-1 m^-1'")
    canonical = _canonical_nist_response_parameters(parameters)
    # The source coefficient is per ppm and per metre.  Multiplication by
    # 1e6 makes the response compatible with dimensionless mole fraction;
    # pathlength_cm / 100 converts the declared optical path to metres.
    factor = float(canonical["pathlength_cm"]) / 100.0 * 1e6
    response = matrix * factor
    result = build_dataset_like(response, dataset, units="absorbance", copy_history=False)
    add_processing_step(result, "synthesis.nist_quant_ir_response", canonical, node_id=node_id)
    return result, {
        "equation": "A10=a_ppm_per_m*(C_ppm*1e-6)*(pathlength_cm/100)*1e6",
        "pathlength_cm": canonical["pathlength_cm"],
        "response_scale": factor,
        "source_units": "ppm^-1 m^-1",
    }


def build_hitran_response_result(
    source: Any,
    parameters: Mapping[str, object],
    *,
    node_id: str,
) -> tuple[Any, dict[str, object]]:
    """Project one HITRAN cross section onto a unit mole-fraction response."""

    dataset = coerce_to_sherpa(source, input_name="hitran_response")
    matrix = _require_finite_matrix(dataset, context="hitran_response")
    _feature_axis_signature(dataset, context="hitran_response")
    if matrix.shape[0] != 1:
        raise ValueError("HITRAN response must contain exactly one pure response")
    if dataset.units != "cm^2 molecule^-1":
        raise ValueError("HITRAN response must declare units='cm^2 molecule^-1'")
    canonical = _canonical_hitran_response_parameters(parameters)
    molecules_per_cm3 = (
        float(canonical["pressure_atm"]) * _ATM_PA / (_BOLTZMANN_J_PER_K * float(canonical["temperature_k"])) / 1e6
    )
    factor = molecules_per_cm3 * float(canonical["pathlength_cm"]) / math.log(10.0)
    response = matrix * factor
    result = build_dataset_like(response, dataset, units="absorbance", copy_history=False)
    add_processing_step(result, "synthesis.hitran_response", canonical, node_id=node_id)
    return result, {
        "equation": "A10=x_HITRAN*mole_fraction*(P/(k_B*T)/1e6)*pathlength_cm/ln(10)",
        "pathlength_cm": canonical["pathlength_cm"],
        "pressure_atm": canonical["pressure_atm"],
        "temperature_k": canonical["temperature_k"],
        "response_scale": factor,
        "source_units": "cm^2 molecule^-1",
    }


@register_node
class PPMFractionNode(Node):
    """Convert declared ppm coefficients to dimensionless mole fractions."""

    metadata = NodeMetadata(
        node_type="synthesis.ppm_fraction",
        category="synthesis",
        label="PPM to Fraction",
        description="Convert non-negative ppm coefficients to dimensionless fractions by the exact 10^-6 scale",
        parameters=[],
        input_types=["TargetMatrix"],
        input_ports=[
            PortMetadata(
                name="default",
                type_ref="spectrasherpa://types/TargetMatrix/1.0",
                label="Concentrations (ppm)",
            )
        ],
        output_type="TargetMatrix",
        output_ports=[
            PortMetadata(
                name="default",
                type_ref="spectrasherpa://types/TargetMatrix/1.0",
                label="Dimensionless Fractions",
            )
        ],
        policy=NodePolicy(),
        canonical_parameter_validator=_canonical_no_parameters,
    )

    async def execute(self, input_data: Any = None, default: Any = None, **kwargs: Any) -> NodeResult:
        del kwargs
        source = input_data if input_data is not None else default
        result, diagnostics = build_ppm_fraction_result(source, node_id=self.node_id)
        return NodeResult(outputs={"default": result}, diagnostics=diagnostics)


@register_node
class NISTQuantIRResponseNode(Node):
    """Scale a NIST Quantitative IR coefficient by one declared pathlength."""

    metadata = NodeMetadata(
        node_type="synthesis.nist_quant_ir_response",
        category="synthesis",
        label="NIST Quant IR Response",
        description="Form the decadic unit-fraction response from a NIST ppm^-1 m^-1 coefficient",
        parameters=[
            NodeParameter(
                name="pathlength_cm",
                label="Pathlength (cm)",
                param_type="number",
                default=1.0,
                min_value=0.0,
                description="Strictly positive optical pathlength in centimetres",
                required=True,
            )
        ],
        input_types=["SpectralDataset"],
        input_ports=[
            PortMetadata(
                name="default",
                type_ref="spectrasherpa://types/SpectralDataset/1.0",
                label="NIST Quantitative IR Coefficient",
                accepted_data_roles=["X_spectra"],
            )
        ],
        output_type="SpectralDataset",
        output_ports=[
            PortMetadata(
                name="default",
                type_ref="spectrasherpa://types/SpectralDataset/1.0",
                label="Unit-fraction Decadic Response",
                accepted_data_roles=["X_spectra"],
            )
        ],
        policy=NodePolicy(),
        canonical_parameter_validator=_canonical_nist_response_parameters,
    )

    async def execute(self, input_data: Any = None, default: Any = None, **kwargs: Any) -> NodeResult:
        del kwargs
        source = input_data if input_data is not None else default
        result, diagnostics = build_nist_quant_ir_response_result(
            source,
            self.metadata.canonicalize_parameters(self.parameters),
            node_id=self.node_id,
        )
        return NodeResult(outputs={"default": result}, diagnostics=diagnostics)


@register_node
class HITRANResponseNode(Node):
    """Scale a HITRAN cross section by one declared gas state and pathlength."""

    metadata = NodeMetadata(
        node_type="synthesis.hitran_response",
        category="synthesis",
        label="HITRAN Cross-section Response",
        description="Form the decadic unit-fraction response using Beer-Lambert and ideal-gas number density",
        parameters=[
            NodeParameter(
                name="pathlength_cm",
                label="Pathlength (cm)",
                param_type="number",
                default=1.0,
                min_value=0.0,
                description="Strictly positive optical pathlength in centimetres",
                required=True,
            ),
            NodeParameter(
                name="temperature_k",
                label="Temperature (K)",
                param_type="number",
                default=293.0,
                min_value=0.0,
                description="Strictly positive absolute temperature",
                required=True,
            ),
            NodeParameter(
                name="pressure_atm",
                label="Pressure (atm)",
                param_type="number",
                default=1.0,
                min_value=0.0,
                description="Strictly positive absolute pressure",
                required=True,
            ),
        ],
        input_types=["SpectralDataset"],
        input_ports=[
            PortMetadata(
                name="default",
                type_ref="spectrasherpa://types/SpectralDataset/1.0",
                label="HITRAN Cross Section",
                accepted_data_roles=["X_spectra"],
            )
        ],
        output_type="SpectralDataset",
        output_ports=[
            PortMetadata(
                name="default",
                type_ref="spectrasherpa://types/SpectralDataset/1.0",
                label="Unit-fraction Decadic Response",
                accepted_data_roles=["X_spectra"],
            )
        ],
        policy=NodePolicy(),
        canonical_parameter_validator=_canonical_hitran_response_parameters,
    )

    async def execute(self, input_data: Any = None, default: Any = None, **kwargs: Any) -> NodeResult:
        del kwargs
        source = input_data if input_data is not None else default
        result, diagnostics = build_hitran_response_result(
            source,
            self.metadata.canonicalize_parameters(self.parameters),
            node_id=self.node_id,
        )
        return NodeResult(outputs={"default": result}, diagnostics=diagnostics)


@register_node
class SpeciesSelectorNode(Node):
    """Assign one species identity to one pure spectral response."""

    metadata = NodeMetadata(
        node_type="synthesis.species",
        category="synthesis",
        label="Species",
        description="Assign a closed species identity to exactly one pure-response spectrum",
        parameters=[
            NodeParameter(
                name="species_name",
                label="Species Name",
                param_type="text",
                default="Species",
                description="Non-empty chemical or component identity",
                required=True,
            ),
            NodeParameter(
                name="molar_absorptivity",
                label="Molar Absorptivity (L mol⁻¹ cm⁻¹)",
                param_type="number",
                default=None,
                min_value=0.0,
                description="Optional finite positive reference molar absorptivity",
                required=False,
            ),
        ],
        input_types=["SpectralDataset"],
        input_ports=[
            PortMetadata(
                name="default",
                type_ref="spectrasherpa://types/SpectralDataset/1.0",
                label="Pure Response",
                description="Exactly one finite pure-component response on an explicit spectral axis",
                accepted_data_roles=["X_spectra"],
            )
        ],
        output_type="SpectralDataset",
        output_ports=[
            PortMetadata(
                name="default",
                type_ref="spectrasherpa://types/SpectralDataset/1.0",
                label="Labelled Pure Response",
                description="The unchanged response with one validated structured species identity",
                accepted_data_roles=["X_spectra"],
            )
        ],
        policy=NodePolicy(),
        canonical_parameter_validator=_canonical_species_parameters,
    )

    async def execute(self, input_data: Any = None, default: Any = None, **kwargs: Any) -> NodeResult:
        del kwargs
        source = input_data if input_data is not None else default
        result, diagnostics = build_species_result(source, self._resolve_params(), node_id=self.node_id)
        return NodeResult(outputs={"default": result}, diagnostics=diagnostics)

    def supports_python_export(self) -> bool:
        return True

    def generate_python(self, inputs, indent="    ", use_scp=True):
        del use_scp
        source = next(iter(inputs.values())) if inputs else "input_data"
        parameters = self.metadata.canonicalize_parameters(self._resolve_params())
        return [
            f"{indent}from spectra_sherpa.app.services.dag.nodes.blend import build_species_result",
            f"{indent}_species_result, _species_diagnostics = build_species_result(",
            f"{indent}    {source}, {parameters!r}, node_id={self.node_id!r}",
            f"{indent})",
            f"{indent}results[{self.node_id!r}] = _species_result",
        ]


@register_node
class MergeSpectraNode(Node):
    """Stack compatible, labelled pure responses into one S matrix."""

    metadata = NodeMetadata(
        node_type="synthesis.merge",
        category="synthesis",
        label="Merge Pure Responses",
        description="Stack species-labelled pure responses; alignment must be an explicit upstream node",
        parameters=[],
        input_types=["SpectralDataset"],
        input_ports=[
            PortMetadata(
                name="default",
                type_ref="spectrasherpa://types/SpectralDataset/1.0",
                label="Labelled Pure Responses",
                description="One or more exactly aligned outputs from synthesis.species",
                variadic=True,
                accepted_data_roles=["X_spectra"],
            )
        ],
        output_type="SpectralDataset",
        output_ports=[
            PortMetadata(
                name="default",
                type_ref="spectrasherpa://types/SpectralDataset/1.0",
                label="Pure-response Matrix (S)",
                description="One row per species on the unchanged common spectral axis",
                accepted_data_roles=["X_spectra"],
            )
        ],
        policy=NodePolicy(),
        canonical_parameter_validator=_canonical_no_parameters,
    )

    async def execute(self, input_data: Any = None, default: Any = None, **kwargs: Any) -> NodeResult:
        del kwargs
        source = input_data if input_data is not None else default
        result, diagnostics = build_merge_result(source, node_id=self.node_id)
        return NodeResult(outputs={"default": result}, diagnostics=diagnostics)

    def supports_python_export(self) -> bool:
        return True

    def generate_python(self, inputs, indent="    ", use_scp=True):
        del use_scp
        source = inputs.get("default", "input_data")
        if isinstance(source, list):
            source = f"[{', '.join(source)}]"
        return [
            f"{indent}from spectra_sherpa.app.services.dag.nodes.blend import build_merge_result",
            f"{indent}_merge_result, _merge_diagnostics = build_merge_result({source}, node_id={self.node_id!r})",
            f"{indent}results[{self.node_id!r}] = _merge_result",
        ]


@register_node
class BlendNode(Node):
    """Evaluate the explicit standard bilinear mixture D = C @ S."""

    metadata = NodeMetadata(
        node_type="synthesis.blend",
        category="synthesis",
        label="Bilinear Mixture",
        description="Compute D = C @ S from explicit non-negative coefficients and labelled pure responses",
        parameters=[],
        input_types=["SpectralDataset", "TargetMatrix"],
        input_ports=[
            PortMetadata(
                name="pure_spectra",
                type_ref="spectrasherpa://types/SpectralDataset/1.0",
                label="Pure-response Matrix (S)",
                description="One finite labelled pure-response row per species",
                accepted_data_roles=["X_spectra"],
            ),
            PortMetadata(
                name="concentrations",
                type_ref="spectrasherpa://types/TargetMatrix/1.0",
                label="Coefficient Matrix (C)",
                description="Finite non-negative dimensionless mixture coefficients",
            ),
        ],
        output_type="SpectralDataset",
        output_ports=[
            PortMetadata(
                name="default",
                type_ref="spectrasherpa://types/SpectralDataset/1.0",
                label="Synthetic Mixtures (D)",
                description="Exact bilinear mixtures with C and S retained as known simulation factors",
                accepted_data_roles=["X_spectra"],
            )
        ],
        policy=NodePolicy(),
        canonical_parameter_validator=_canonical_no_parameters,
    )

    async def execute(self, pure_spectra: Any, concentrations: Any, **kwargs: Any) -> NodeResult:
        del kwargs
        result, diagnostics = build_bilinear_blend_result(
            pure_spectra,
            concentrations,
            node_id=self.node_id,
        )
        return NodeResult(outputs={"default": result}, diagnostics=diagnostics)

    def supports_python_export(self) -> bool:
        return True

    def generate_python(self, inputs, indent="    ", use_scp=True):
        del use_scp
        pure_spectra = inputs.get("pure_spectra", "pure_spectra")
        concentrations = inputs.get("concentrations", "concentrations")
        return [
            f"{indent}from spectra_sherpa.app.services.dag.nodes.blend import build_bilinear_blend_result",
            f"{indent}_blend_result, _blend_diagnostics = build_bilinear_blend_result(",
            f"{indent}    {pure_spectra}, {concentrations}, node_id={self.node_id!r}",
            f"{indent})",
            f"{indent}results[{self.node_id!r}] = _blend_result",
        ]


bind_stable_execution_contract(
    PPMFractionNode,
    runtime_family=RuntimeFamily.SHERPA_NATIVE,
    lifecycle_kind=LifecycleKind.STATELESS_TRANSFORM,
    implementation_id="spectrasherpa.synthesis.ppm_fraction",
    implementation_version="1.0.0",
    required_worker_capabilities=(WorkerCapability.READ_DATASET,),
    managed_optimization_eligibility=(ManagedOptimizationEligibility.LOCAL,),
    sample_effect="preserves_samples",
    feature_effect="preserves_features",
    axis_effect="preserves_axis",
    unit_effect="changes_units",
    target_access="required",
    resource_hints={"timeout_seconds": 10, "cpu_seconds": 10, "memory_bytes": 268_435_456},
    license_id="Apache-2.0",
    help_reference="docs/nodes/data.md",
    implementation_modules=(dag_io_contracts, dag_meta_helpers, sherpa_dataset_contract),
    implementation_distributions=("numpy",),
    runtime_requirements=(("numpy", "1.26.4"),),
    citations=(_PPM_REFERENCE,),
)

bind_stable_execution_contract(
    NISTQuantIRResponseNode,
    runtime_family=RuntimeFamily.SHERPA_NATIVE,
    lifecycle_kind=LifecycleKind.STATELESS_TRANSFORM,
    implementation_id="spectrasherpa.synthesis.nist_quant_ir_response",
    implementation_version="1.0.0",
    required_worker_capabilities=(WorkerCapability.READ_DATASET,),
    managed_optimization_eligibility=(ManagedOptimizationEligibility.LOCAL,),
    sample_effect="preserves_samples",
    feature_effect="preserves_features",
    axis_effect="preserves_axis",
    unit_effect="changes_units",
    target_access="none",
    resource_hints={"timeout_seconds": 10, "cpu_seconds": 10, "memory_bytes": 268_435_456},
    license_id="Apache-2.0",
    help_reference="docs/nodes/data.md",
    implementation_modules=(dag_io_contracts, dag_meta_helpers, sherpa_dataset_contract),
    implementation_distributions=("numpy",),
    runtime_requirements=(("numpy", "1.26.4"),),
    citations=(_BEER_LAMBERT_REFERENCE, _NIST_QUANT_IR_REFERENCE, _PPM_REFERENCE),
)

bind_stable_execution_contract(
    HITRANResponseNode,
    runtime_family=RuntimeFamily.SHERPA_NATIVE,
    lifecycle_kind=LifecycleKind.STATELESS_TRANSFORM,
    implementation_id="spectrasherpa.synthesis.hitran_response",
    implementation_version="1.0.0",
    required_worker_capabilities=(WorkerCapability.READ_DATASET,),
    managed_optimization_eligibility=(ManagedOptimizationEligibility.LOCAL,),
    sample_effect="preserves_samples",
    feature_effect="preserves_features",
    axis_effect="preserves_axis",
    unit_effect="changes_units",
    target_access="none",
    resource_hints={"timeout_seconds": 10, "cpu_seconds": 10, "memory_bytes": 268_435_456},
    license_id="Apache-2.0",
    help_reference="docs/nodes/data.md",
    implementation_modules=(dag_io_contracts, dag_meta_helpers, sherpa_dataset_contract),
    implementation_distributions=("numpy",),
    runtime_requirements=(("numpy", "1.26.4"),),
    citations=(_BEER_LAMBERT_REFERENCE, _HITRAN_REFERENCE, _PPM_REFERENCE),
)

bind_stable_execution_contract(
    SpeciesSelectorNode,
    runtime_family=RuntimeFamily.SHERPA_NATIVE,
    lifecycle_kind=LifecycleKind.STATELESS_TRANSFORM,
    implementation_id="spectrasherpa.synthesis.species",
    implementation_version="1.0.0",
    required_worker_capabilities=(WorkerCapability.READ_DATASET,),
    managed_optimization_eligibility=(ManagedOptimizationEligibility.LOCAL,),
    sample_effect="preserves_samples",
    feature_effect="preserves_features",
    axis_effect="preserves_axis",
    unit_effect="preserves_units",
    target_access="none",
    resource_hints={"timeout_seconds": 10, "cpu_seconds": 10, "memory_bytes": 268_435_456},
    license_id="Apache-2.0",
    help_reference="docs/nodes/data.md",
    implementation_modules=(spectra_meta_contract, dag_io_contracts, dag_meta_helpers, sherpa_dataset_contract),
    implementation_distributions=("numpy",),
    runtime_requirements=(("numpy", "1.26.4"),),
)

bind_stable_execution_contract(
    MergeSpectraNode,
    runtime_family=RuntimeFamily.SHERPA_NATIVE,
    lifecycle_kind=LifecycleKind.STATELESS_TRANSFORM,
    implementation_id="spectrasherpa.synthesis.merge",
    implementation_version="1.0.0",
    required_worker_capabilities=(WorkerCapability.READ_DATASET,),
    managed_optimization_eligibility=(ManagedOptimizationEligibility.LOCAL,),
    sample_effect="aggregates_samples",
    feature_effect="preserves_features",
    axis_effect="preserves_axis",
    unit_effect="requires_compatible_units",
    target_access="none",
    resource_hints={"timeout_seconds": 30, "cpu_seconds": 30, "memory_bytes": 1_073_741_824},
    license_id="Apache-2.0",
    help_reference="docs/nodes/data.md",
    implementation_modules=(spectra_meta_contract, dag_io_contracts, dag_meta_helpers, sherpa_dataset_contract),
    implementation_distributions=("numpy",),
    runtime_requirements=(("numpy", "1.26.4"),),
)

bind_stable_execution_contract(
    BlendNode,
    runtime_family=RuntimeFamily.SHERPA_NATIVE,
    lifecycle_kind=LifecycleKind.STATELESS_TRANSFORM,
    implementation_id="spectrasherpa.synthesis.bilinear_blend",
    implementation_version="1.0.0",
    required_worker_capabilities=(WorkerCapability.READ_DATASET,),
    managed_optimization_eligibility=(ManagedOptimizationEligibility.LOCAL,),
    sample_effect="generates_samples",
    feature_effect="preserves_features",
    axis_effect="preserves_axis",
    unit_effect="preserves_units",
    target_access="required",
    resource_hints={"timeout_seconds": 30, "cpu_seconds": 30, "memory_bytes": 1_073_741_824},
    license_id="Apache-2.0",
    help_reference="docs/nodes/data.md",
    implementation_modules=(spectra_meta_contract, dag_io_contracts, dag_meta_helpers, sherpa_dataset_contract),
    implementation_distributions=("numpy",),
    runtime_requirements=(("numpy", "1.26.4"),),
    citations=(_BILINEAR_REFERENCE,),
)


__all__ = [
    "BlendNode",
    "HITRANResponseNode",
    "MergeSpectraNode",
    "NISTQuantIRResponseNode",
    "PPMFractionNode",
    "SpeciesSelectorNode",
    "build_bilinear_blend_result",
    "build_hitran_response_result",
    "build_merge_result",
    "build_nist_quant_ir_response_result",
    "build_ppm_fraction_result",
    "build_species_result",
]
