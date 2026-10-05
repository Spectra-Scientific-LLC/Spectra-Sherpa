"""Canonical fitted Extended Multiplicative Signal Correction (EMSC).

The workbench, fold executor, Python export, and model-artifact replay all use
the fit/apply functions in this module.  The fitted reference and nuisance
basis are immutable JSON state; application never estimates them again.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeAlias

import numpy as np
from numpy.typing import NDArray

from spectra_sherpa.app.lib.sherpa_dataset import EFFECT_SCATTER_CORRECTED, SherpaDataset
from spectra_sherpa.app.services.dag import supervision_binding
from spectra_sherpa.app.services.dag.export_helpers import header_line
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
from spectra_sherpa.execution_contract_vocabulary import (
    LifecycleKind,
    ManagedOptimizationEligibility,
    RuntimeFamily,
    WorkerCapability,
)

from . import _shared

FloatArray: TypeAlias = NDArray[np.float64]

_STATE_SERIALIZER = "spectra.emsc-reference-json.v1"
_REFERENCE_METHODS = frozenset({"mean", "median", "first"})
_MAX_POLYNOMIAL_ORDER = 5
_MAX_DESIGN_CONDITION = 1.0e12
_MIN_RELATIVE_REFERENCE_COEFFICIENT = 1.0e-12


def _canonical_emsc_parameters(parameters: dict[str, object]) -> dict[str, object]:
    """Return the one admitted scientist-facing EMSC parameter record."""

    reference_method = parameters["reference_method"]
    poly_order = parameters["poly_order"]
    if not isinstance(reference_method, str) or reference_method not in _REFERENCE_METHODS:
        raise ValueError("EMSC reference_method must be mean, median, or first")
    if isinstance(poly_order, bool) or not isinstance(poly_order, (int, float)) or int(poly_order) != poly_order:
        raise ValueError("EMSC poly_order must be an exact integer")
    order = int(poly_order)
    if order < 0 or order > _MAX_POLYNOMIAL_ORDER:
        raise ValueError(f"EMSC poly_order must be between 0 and {_MAX_POLYNOMIAL_ORDER}")
    return {"reference_method": reference_method, "poly_order": order}


def _managed_emsc_parameters(parameters: dict[str, object]) -> dict[str, object]:
    """Bound the initial managed EMSC recipe to stable, intrinsic fits."""

    if parameters["reference_method"] == "first":
        raise ValueError("managed EMSC does not admit the order-sensitive first-row reference")
    if int(parameters["poly_order"]) > 2:
        raise ValueError("managed EMSC poly_order must be between 0 and 2")
    return parameters


def _finite_matrix(value: object, *, name: str, allow_empty: bool = False) -> FloatArray:
    matrix = np.asarray(value, dtype=np.float64)
    if matrix.ndim == 1:
        matrix = matrix.reshape(1, -1)
    if matrix.ndim != 2 or matrix.shape[1] == 0 or (matrix.shape[0] == 0 and not allow_empty):
        raise ValueError(f"EMSC {name} must be a non-empty two-dimensional matrix")
    if not np.isfinite(matrix).all():
        raise ValueError(f"EMSC {name} must contain only finite values")
    return np.array(matrix, dtype=np.float64, copy=True)


def _axis_record(value: Any, *, features: int) -> tuple[FloatArray | None, str | None]:
    """Extract the exact numeric feature axis used to form polynomial terms."""

    if isinstance(value, SherpaDataset):
        axis = value.get_feature_axis()
    else:
        axis = getattr(value, "feature_axis", None)
        if axis is None:
            axis = getattr(value, "x", None)
    if axis is None:
        return None, None
    raw_values = getattr(axis, "values", None)
    if raw_values is None:
        raw_values = getattr(axis, "data", None)
    if raw_values is None:
        return None, None
    values = np.asarray(raw_values, dtype=np.float64)
    if values.ndim != 1 or values.shape[0] != features or not np.isfinite(values).all():
        raise ValueError("EMSC feature axis must be a finite vector matching the feature count")
    if features > 1 and float(np.ptp(values)) == 0.0:
        raise ValueError("EMSC feature axis must span more than one coordinate")
    units_raw = getattr(axis, "units", None)
    if units_raw is not None and (not isinstance(units_raw, str) or not units_raw.strip()):
        raise ValueError("EMSC feature-axis units must be a non-empty string when present")
    return np.array(values, dtype=np.float64, copy=True), units_raw.strip() if units_raw is not None else None


def _normalized_coordinates(axis_values: FloatArray | None, *, features: int) -> FloatArray:
    coordinates = np.arange(features, dtype=np.float64) if axis_values is None else axis_values
    center = float(np.mean(coordinates, dtype=np.float64))
    scale = float(np.std(coordinates, dtype=np.float64))
    if not np.isfinite(center) or not np.isfinite(scale) or scale <= 0.0:
        raise ValueError("EMSC requires a finite, non-constant feature coordinate basis")
    normalized = (coordinates - center) / scale
    if not np.isfinite(normalized).all():
        raise ValueError("EMSC normalized feature coordinate basis is not finite")
    return normalized


def _build_design(
    *,
    reference: FloatArray,
    poly_order: int,
    axis_values: FloatArray | None,
    constituents: FloatArray,
) -> tuple[FloatArray, int]:
    features = int(reference.shape[0])
    coordinates = _normalized_coordinates(axis_values, features=features)
    columns = [coordinates**degree for degree in range(poly_order + 1)]
    reference_column = len(columns)
    columns.append(reference)
    columns.extend(constituents[index] for index in range(constituents.shape[0]))
    design = np.column_stack(columns)
    rank = int(np.linalg.matrix_rank(design))
    if rank != design.shape[1]:
        raise ValueError("EMSC fitted design is rank-deficient; reduce polynomial order or constituents")
    condition = float(np.linalg.cond(design))
    if not np.isfinite(condition) or condition > _MAX_DESIGN_CONDITION:
        raise ValueError("EMSC fitted design is numerically ill-conditioned")
    return design, reference_column


def _canonical_float_vector(value: object, *, name: str, length: int) -> FloatArray:
    """Decode the sole JSON-native representation admitted by fitted state."""

    if not isinstance(value, list) or len(value) != length:
        raise ValueError(f"fitted EMSC state has an invalid {name}")
    if any(type(item) is not float or not np.isfinite(item) for item in value):
        raise ValueError(f"fitted EMSC state has an invalid {name}")
    return np.asarray(value, dtype=np.float64)


def _validated_emsc_state(
    state: Mapping[str, object],
) -> tuple[FloatArray, FloatArray, FloatArray | None, int]:
    required = {
        "serializer",
        "reference_method",
        "poly_order",
        "feature_count",
        "feature_axis_values",
        "feature_axis_units",
        "reference_spectrum",
        "constituent_spectra",
    }
    if not isinstance(state, Mapping) or set(state) != required or state["serializer"] != _STATE_SERIALIZER:
        raise ValueError("fitted EMSC state does not use the closed serializer schema")
    if type(state["poly_order"]) is not int:
        raise ValueError("fitted EMSC state has an invalid polynomial order")
    projected = _canonical_emsc_parameters(
        {"reference_method": state["reference_method"], "poly_order": state["poly_order"]}
    )
    feature_count = state["feature_count"]
    if type(feature_count) is not int or feature_count < 2:
        raise ValueError("fitted EMSC state has an invalid feature count")
    axis_raw = state["feature_axis_values"]
    units = state["feature_axis_units"]
    if units is not None and (not isinstance(units, str) or not units.strip() or units != units.strip()):
        raise ValueError("fitted EMSC state has invalid feature-axis units")
    axis_values: FloatArray | None
    if axis_raw is None:
        if units is not None:
            raise ValueError("fitted EMSC state cannot declare units without numeric feature coordinates")
        axis_values = None
    else:
        axis_values = _canonical_float_vector(axis_raw, name="feature axis", length=feature_count)
    reference = _canonical_float_vector(
        state["reference_spectrum"],
        name="reference spectrum",
        length=feature_count,
    )
    constituents_raw = state["constituent_spectra"]
    if not isinstance(constituents_raw, list):
        raise ValueError("fitted EMSC state has invalid constituent spectra")
    if not constituents_raw:
        constituents = np.empty((0, feature_count), dtype=np.float64)
    else:
        rows = [
            _canonical_float_vector(row, name="constituent spectra", length=feature_count) for row in constituents_raw
        ]
        constituents = np.vstack(rows)
    poly_order = projected["poly_order"]
    if not isinstance(poly_order, int):
        raise ValueError("fitted EMSC state has an invalid polynomial order")
    design, reference_column = _build_design(
        reference=np.array(reference, dtype=np.float64, copy=True),
        poly_order=poly_order,
        axis_values=axis_values,
        constituents=np.array(constituents, dtype=np.float64, copy=True),
    )
    return design, np.array(reference, dtype=np.float64, copy=True), axis_values, reference_column


def _fit_emsc_state(
    data: FloatArray,
    *,
    reference_method: str,
    poly_order: int,
    feature_axis_values: FloatArray | None,
    feature_axis_units: str | None,
    constituents: FloatArray | None = None,
) -> dict[str, object]:
    """Fit one finite reference and nuisance basis from training rows only."""

    projected = _canonical_emsc_parameters({"reference_method": reference_method, "poly_order": poly_order})
    matrix = _finite_matrix(data, name="fit input")
    axis_values = None if feature_axis_values is None else np.asarray(feature_axis_values, dtype=np.float64)
    if axis_values is not None and (
        axis_values.ndim != 1 or axis_values.shape[0] != matrix.shape[1] or not np.isfinite(axis_values).all()
    ):
        raise ValueError("EMSC fit feature axis does not match the training matrix")
    if axis_values is None and feature_axis_units is not None:
        raise ValueError("EMSC fit cannot declare feature-axis units without coordinates")
    if feature_axis_units is not None and (
        not isinstance(feature_axis_units, str)
        or not feature_axis_units.strip()
        or feature_axis_units != feature_axis_units.strip()
    ):
        raise ValueError("EMSC fit feature-axis units are invalid")
    if projected["reference_method"] == "mean":
        reference = np.mean(matrix, axis=0, dtype=np.float64)
    elif projected["reference_method"] == "median":
        reference = np.median(matrix, axis=0)
    else:
        reference = matrix[0]
    if constituents is None:
        constituent_matrix = np.empty((0, matrix.shape[1]), dtype=np.float64)
    else:
        constituent_matrix = _finite_matrix(constituents, name="constituents")
        if constituent_matrix.shape[1] != matrix.shape[1]:
            raise ValueError("EMSC constituents must match the fitted feature count")
    state: dict[str, object] = {
        "serializer": _STATE_SERIALIZER,
        "reference_method": projected["reference_method"],
        "poly_order": projected["poly_order"],
        "feature_count": int(matrix.shape[1]),
        "feature_axis_values": None if axis_values is None else axis_values.tolist(),
        "feature_axis_units": feature_axis_units,
        "reference_spectrum": np.asarray(reference, dtype=np.float64).tolist(),
        "constituent_spectra": constituent_matrix.tolist(),
    }
    _validated_emsc_state(state)
    return state


def _apply_emsc_state(
    data: FloatArray,
    state: Mapping[str, object],
    *,
    feature_axis_values: FloatArray | None,
    feature_axis_units: str | None,
) -> FloatArray:
    """Apply a closed fitted state while requiring explicit axis identity."""

    matrix = _finite_matrix(data, name="apply input")
    design, _reference, fitted_axis, reference_column = _validated_emsc_state(state)
    if matrix.shape[1] != design.shape[0]:
        raise ValueError("fitted EMSC state does not match the supplied feature count")
    supplied_axis = None if feature_axis_values is None else np.asarray(feature_axis_values, dtype=np.float64)
    if fitted_axis is None:
        if supplied_axis is not None:
            raise ValueError("EMSC apply feature axis differs from the fitted axis")
    elif (
        supplied_axis is None
        or supplied_axis.shape != fitted_axis.shape
        or not np.array_equal(supplied_axis, fitted_axis)
    ):
        raise ValueError("EMSC apply feature axis differs from the fitted axis")
    if feature_axis_units != state["feature_axis_units"]:
        raise ValueError("EMSC apply feature-axis units differ from the fitted units")
    nuisance_columns = [index for index in range(design.shape[1]) if index != reference_column]
    # The design is identical for every sample. Solve all right-hand sides in
    # one decomposition rather than repeating the same SVD for each row.
    coefficients, _, _, _ = np.linalg.lstsq(design, matrix.T, rcond=None)
    reference_coefficients = coefficients[reference_column]
    coefficient_scales = np.maximum(1.0, np.max(np.abs(coefficients), axis=0))
    unresolved = (
        ~np.isfinite(reference_coefficients)
        | ~np.isfinite(coefficient_scales)
        | (np.abs(reference_coefficients) <= _MIN_RELATIVE_REFERENCE_COEFFICIENT * coefficient_scales)
    )
    if np.any(unresolved):
        row_index = int(np.flatnonzero(unresolved)[0])
        raise ValueError(f"EMSC reference coefficient is unresolved for sample {row_index}")
    nuisance = design[:, nuisance_columns] @ coefficients[nuisance_columns]
    corrected = ((matrix.T - nuisance) / reference_coefficients).T
    if not np.isfinite(corrected).all():
        raise ValueError("EMSC correction produced non-finite output")
    return corrected


def _dataset_view(value: Any, *, name: str) -> tuple[FloatArray, FloatArray | None, str | None]:
    raw: object
    if isinstance(value, SherpaDataset):
        raw = value.X
    elif isinstance(value, (np.ndarray, list, tuple)):
        raw = value
    else:
        raw = getattr(value, "data", value)
    matrix = _finite_matrix(raw, name=name)
    axis_values, axis_units = _axis_record(value, features=matrix.shape[1])
    return matrix, axis_values, axis_units


def _require_same_axis(
    left: tuple[FloatArray | None, str | None],
    right: tuple[FloatArray | None, str | None],
    *,
    name: str,
) -> None:
    left_values, left_units = left
    right_values, right_units = right
    if (left_values is None) != (right_values is None):
        raise ValueError(f"EMSC {name} feature axis must match the fit reference")
    if left_values is not None and right_values is not None and not np.array_equal(left_values, right_values):
        raise ValueError(f"EMSC {name} feature axis must match the fit reference")
    if left_units != right_units:
        raise ValueError(f"EMSC {name} feature-axis units must match the fit reference")


def _emsc_dispatch(
    input_data: Any,
    *,
    reference_method: str = "mean",
    poly_order: int = 2,
    reference_data: Any = None,
    constituents_data: Any = None,
) -> FloatArray:
    """One-shot workbench/export dispatcher over the sole fitted EMSC ABI."""

    matrix, source_axis, source_units = _dataset_view(input_data, name="input")
    fit_value = input_data if reference_data is None else reference_data
    fit_matrix, fit_axis, fit_units = _dataset_view(fit_value, name="fit reference")
    _require_same_axis((source_axis, source_units), (fit_axis, fit_units), name="input")
    constituents: FloatArray | None = None
    if constituents_data is not None:
        constituents, constituent_axis, constituent_units = _dataset_view(constituents_data, name="constituents")
        _require_same_axis(
            (constituent_axis, constituent_units),
            (fit_axis, fit_units),
            name="constituent",
        )
    state = _fit_emsc_state(
        fit_matrix,
        reference_method=reference_method,
        poly_order=poly_order,
        feature_axis_values=fit_axis,
        feature_axis_units=fit_units,
        constituents=constituents,
    )
    return _apply_emsc_state(
        matrix,
        state,
        feature_axis_values=source_axis,
        feature_axis_units=source_units,
    )


@register_node
class EMSCNode(Node):
    """Fit EMSC reference/nuisance terms once and apply the frozen state."""

    metadata = NodeMetadata(
        node_type="preprocess.emsc",
        category="preprocessing",
        label="EMSC",
        description=(
            "Fit a reference spectrum, polynomial baseline, and optional interferent spectra, then apply "
            "the frozen correction without refitting application rows."
        ),
        parameters=[
            NodeParameter(
                name="reference_method",
                label="Reference Spectrum",
                param_type="select",
                default="mean",
                options=[
                    {"label": "Mean of reference rows", "value": "mean"},
                    {"label": "Median of reference rows", "value": "median"},
                    {"label": "First reference row (order-sensitive)", "value": "first"},
                ],
                description=(
                    "Rule used to fit the reference spectrum. 'First' means the first row of the "
                    "ordered reference input and therefore changes if those rows are reordered; "
                    "prefer an explicit one-row reference input when that spectrum is intentional."
                ),
                required=True,
            ),
            NodeParameter(
                name="poly_order",
                label="Polynomial Order",
                param_type="number",
                default=2,
                min_value=0,
                max_value=_MAX_POLYNOMIAL_ORDER,
                max_value_reason="Higher orders are unstable and confound spectral structure with baseline shape.",
                step=1,
                description="Polynomial nuisance order, including the constant term.",
                required=True,
            ),
        ],
        input_types=["SherpaDataset"],
        input_ports=[
            PortMetadata(
                name="default",
                type_ref="spectrasherpa://types/SpectralDataset/1.0",
                required=True,
                label="Input Spectra",
                description="Spectra to correct using the fitted EMSC state.",
                accepted_data_roles=["X_spectra"],
            ),
            PortMetadata(
                name="reference",
                type_ref="spectrasherpa://types/SpectralDataset/1.0",
                required=False,
                label="Fit Reference",
                description="Optional training rows used to fit the EMSC reference instead of input rows.",
                accepted_data_roles=["X_spectra"],
            ),
            PortMetadata(
                name="constituents",
                type_ref="spectrasherpa://types/SpectralDataset/1.0",
                required=False,
                label="Known Interferents",
                description="Optional known constituent spectra included as frozen nuisance terms.",
                accepted_data_roles=["X_spectra"],
            ),
        ],
        output_ports=[
            PortMetadata(
                name="default",
                type_ref="spectrasherpa://types/SpectralDataset/1.0",
                required=True,
                label="EMSC-Corrected Spectra",
                description="Spectra corrected through the frozen fitted state.",
                accepted_data_roles=["X_spectra"],
            )
        ],
        output_type="SherpaDataset",
        policy=NodePolicy(),
        canonical_parameter_validator=_canonical_emsc_parameters,
        managed_parameter_validator=_managed_emsc_parameters,
    )

    def fit_fitted_state(self, input_data: Any, constituents: Any = None) -> dict[str, object]:
        fit_dataset = coerce_to_sherpa(input_data, input_name="input_data")
        fit_matrix = to_numpy_2d(fit_dataset, name="input_data", dtype=np.float64)
        axis_values, axis_units = _axis_record(fit_dataset, features=fit_matrix.shape[1])
        constituent_matrix: FloatArray | None = None
        if constituents is not None:
            constituent_dataset = coerce_to_sherpa(constituents, input_name="constituents")
            constituent_matrix = to_numpy_2d(constituent_dataset, name="constituents", dtype=np.float64)
            constituent_axis = _axis_record(constituent_dataset, features=constituent_matrix.shape[1])
            _require_same_axis(constituent_axis, (axis_values, axis_units), name="constituent")
        parameters = self._resolve_params()
        return _fit_emsc_state(
            fit_matrix,
            reference_method=str(parameters["reference_method"]),
            poly_order=int(parameters["poly_order"]),
            feature_axis_values=axis_values,
            feature_axis_units=axis_units,
            constituents=constituent_matrix,
        )

    def apply_fitted_state(self, input_data: Any, state: Mapping[str, object]) -> SherpaDataset:
        dataset = coerce_to_sherpa(input_data, input_name="input_data")
        matrix = to_numpy_2d(dataset, name="input_data", dtype=np.float64)
        axis_values, axis_units = _axis_record(dataset, features=matrix.shape[1])
        corrected = _apply_emsc_state(
            matrix,
            state,
            feature_axis_values=axis_values,
            feature_axis_units=axis_units,
        )
        result = build_dataset_like(corrected, dataset)
        add_processing_step(
            result,
            "preprocess.emsc",
            {
                "reference_method": state["reference_method"],
                "poly_order": state["poly_order"],
                "state_serializer": _STATE_SERIALIZER,
                "transform_state": dict(state),
            },
            node_id=self.node_id,
            state_effects=[EFFECT_SCATTER_CORRECTED],
        )
        supervision_binding.rebind_sample_preserving_supervision(dataset, result)
        return result

    async def execute(
        self,
        default: Any = None,
        input_data: Any = None,
        reference: Any = None,
        constituents: Any = None,
        **kwargs: Any,
    ) -> NodeResult:
        del kwargs
        source = input_data if input_data is not None else default
        fit_source = reference if reference is not None else source
        state = self.fit_fitted_state(fit_source, constituents)
        output = self.apply_fitted_state(source, state)
        constituent_state = state["constituent_spectra"]
        if not isinstance(constituent_state, list):
            raise ValueError("fitted EMSC state has invalid constituent spectra")
        return NodeResult(
            outputs={"default": output},
            diagnostics={
                "reference_method": state["reference_method"],
                "poly_order": state["poly_order"],
                "n_constituents": len(constituent_state),
                "fitted_state_serializer": _STATE_SERIALIZER,
            },
        )

    def supports_python_export(self) -> bool:
        return True

    def generate_python(
        self,
        inputs: Mapping[str, str],
        indent: str = "    ",
        use_scp: bool = True,
    ) -> list[str]:
        source = inputs.get("default") if inputs else None
        if source is None:
            source = next(iter(inputs.values())) if inputs else "input_data"
        reference = inputs.get("reference") if inputs else None
        constituents = inputs.get("constituents") if inputs else None
        parameters = self._resolve_params()
        fit_source = reference if reference is not None else source
        return [
            header_line("Canonical fitted EMSC", self.node_id, indent),
            f"{indent}from spectra_sherpa.app.services.dag.nodes.preprocessing.emsc_node import EMSCNode",
            f"{indent}_transform = EMSCNode({self.node_id!r}, {parameters!r})",
            f"{indent}_state = _transform.fit_fitted_state({fit_source}, {constituents or 'None'})",
            f"{indent}results[{self.node_id!r}] = _transform.apply_fitted_state({source}, _state)",
        ]


bind_stable_execution_contract(
    EMSCNode,
    runtime_family=RuntimeFamily.SHERPA_NATIVE,
    lifecycle_kind=LifecycleKind.FITTED_TRANSFORM,
    implementation_id="spectrasherpa.preprocess.emsc",
    implementation_version="1.0.1",
    required_worker_capabilities=(WorkerCapability.READ_DATASET,),
    managed_optimization_eligibility=(
        ManagedOptimizationEligibility.LOCAL,
        ManagedOptimizationEligibility.DEVELOPMENT,
        ManagedOptimizationEligibility.FULL_REFIT,
    ),
    sample_effect="preserves_samples",
    feature_effect="preserves_features",
    axis_effect="preserves_axis",
    unit_effect="preserves_units",
    resource_hints={"timeout_seconds": 30, "cpu_seconds": 30, "memory_bytes": 1_073_741_824},
    license_id="Apache-2.0",
    help_reference="docs/nodes/preprocessing.md",
    implementation_modules=(_shared, supervision_binding),
    implementation_distributions=("numpy",),
    runtime_requirements=(("numpy", "1.26.4"),),
    managed_optimization_profiles=("first_party_pls",),
    fitted_state_serializer=_STATE_SERIALIZER,
    citations=(
        "Martens and Stark, Journal of Pharmaceutical and Biomedical Analysis 9 (1991) 625-635, "
        "DOI 10.1016/0731-7085(91)80188-F",
    ),
)


__all__ = [
    "EMSCNode",
    "_apply_emsc_state",
    "_emsc_dispatch",
    "_fit_emsc_state",
]
