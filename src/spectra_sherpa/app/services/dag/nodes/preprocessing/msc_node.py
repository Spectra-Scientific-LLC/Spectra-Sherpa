"""Canonical fitted multiplicative scatter correction (MSC).

MSC learns one reference spectrum from a declared reference cohort, then
regresses each application spectrum against that frozen reference.  The
workbench, Python export, SDK, and saved-model replay all use the fit/apply
functions in this module. Managed-campaign eligibility remains a separate,
explicit admission decision.
"""

from __future__ import annotations

from collections.abc import Mapping
from types import SimpleNamespace
from typing import Any, TypeAlias, cast

import numpy as np
from numpy.typing import NDArray

from spectra_sherpa.app.lib.sherpa_dataset import EFFECT_SCATTER_CORRECTED, SherpaDataset
from spectra_sherpa.app.services.dag import supervision_binding
from spectra_sherpa.app.services.dag.export_helpers import header_line
from spectra_sherpa.app.services.dag.fitted_input_identity import (
    fitted_input_identity,
    require_fitted_input_identity,
    validate_fitted_input_identity,
)
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

_STATE_SERIALIZER = "spectra.msc-reference-json.v2"
_REFERENCE_METHODS = frozenset({"mean", "median", "first"})
_MAX_DESIGN_CONDITION = 1.0e12
_MIN_RELATIVE_SLOPE = 1.0e-12


def _canonical_msc_parameters(parameters: dict[str, object]) -> dict[str, object]:
    """Return the sole scientist-facing MSC parameter record."""

    reference_method = parameters["reference_method"]
    if not isinstance(reference_method, str) or reference_method not in _REFERENCE_METHODS:
        raise ValueError("MSC reference_method must be mean, median, or first")
    return {"reference_method": reference_method}


def _managed_msc_parameters(parameters: dict[str, object]) -> dict[str, object]:
    """Restrict managed fitting to order-invariant reference estimators."""

    if parameters["reference_method"] == "first":
        raise ValueError("managed MSC does not admit the order-sensitive first-row reference")
    return parameters


def _finite_matrix(value: object, *, name: str) -> FloatArray:
    matrix = np.asarray(value, dtype=np.float64)
    if matrix.ndim == 1:
        matrix = matrix.reshape(1, -1)
    if matrix.ndim != 2 or matrix.shape[0] == 0 or matrix.shape[1] < 2:
        raise ValueError(f"MSC {name} must be a non-empty two-dimensional matrix with at least two features")
    if not np.isfinite(matrix).all():
        raise ValueError(f"MSC {name} must contain only finite values")
    return np.array(matrix, dtype=np.float64, copy=True)


def _feature_axis(value: Any, *, features: int) -> tuple[FloatArray | None, str | None]:
    if isinstance(value, SherpaDataset):
        axis = value.get_feature_axis()
    else:
        axis = getattr(value, "feature_axis", None)
    if axis is None:
        return None, None
    raw = getattr(axis, "values", None)
    if raw is None:
        raw = getattr(axis, "data", None)
    if raw is None:
        return None, None
    values = np.asarray(raw, dtype=np.float64)
    if values.ndim != 1 or values.shape[0] != features or not np.isfinite(values).all():
        raise ValueError("MSC feature axis must be a finite vector matching the feature count")
    units = getattr(axis, "units", None)
    if units is not None and (not isinstance(units, str) or not units.strip() or units != units.strip()):
        raise ValueError("MSC feature-axis units must be a non-empty trimmed string when present")
    return np.array(values, dtype=np.float64, copy=True), units


def _dataset_view(value: Any, *, name: str) -> tuple[FloatArray, FloatArray | None, str | None]:
    dataset = coerce_to_sherpa(value, input_name=name)
    matrix = to_numpy_2d(dataset, name=name, dtype=np.float64)
    matrix = _finite_matrix(matrix, name=name)
    axis_values, axis_units = _feature_axis(dataset, features=matrix.shape[1])
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
        raise ValueError(f"MSC {name} feature axis must match the fitted reference")
    if left_values is not None and right_values is not None and not np.array_equal(left_values, right_values):
        raise ValueError(f"MSC {name} feature axis must match the fitted reference")
    if left_units != right_units:
        raise ValueError(f"MSC {name} feature-axis units must match the fitted reference")


def _canonical_float_vector(value: object, *, name: str, length: int) -> FloatArray:
    if not isinstance(value, (list, tuple)) or len(value) != length:
        raise ValueError(f"fitted MSC state has an invalid {name}")
    if any(type(item) is not float or not np.isfinite(item) for item in value):
        raise ValueError(f"fitted MSC state has an invalid {name}")
    return np.asarray(value, dtype=np.float64)


def _identity_view(source_dataset: Any, axis_values: Any, axis_units: str | None) -> Any:
    if source_dataset is not None:
        return source_dataset
    return SimpleNamespace(feature_axis=SimpleNamespace(values=axis_values, units=axis_units))


def _validated_msc_state(
    state: Mapping[str, object],
) -> tuple[FloatArray, FloatArray | None, str | None]:
    required = {
        "serializer",
        "reference_method",
        "feature_count",
        "feature_axis_values",
        "feature_axis_units",
        "reference_spectrum",
        "input_identity",
    }
    if not isinstance(state, Mapping) or set(state) != required or state["serializer"] != _STATE_SERIALIZER:
        raise ValueError("fitted MSC state does not use the closed serializer schema")
    projected = _canonical_msc_parameters({"reference_method": state["reference_method"]})
    if state["reference_method"] != projected["reference_method"]:
        raise ValueError("fitted MSC state has an invalid reference method")
    feature_count = state["feature_count"]
    if type(feature_count) is not int or feature_count < 2:
        raise ValueError("fitted MSC state has an invalid feature count")
    identity = validate_fitted_input_identity(state["input_identity"])
    if identity["features"] != feature_count:
        raise ValueError("fitted MSC state input identity contradicts feature count")
    units = state["feature_axis_units"]
    if units is not None and (not isinstance(units, str) or not units.strip() or units != units.strip()):
        raise ValueError("fitted MSC state has invalid feature-axis units")
    axis_raw = state["feature_axis_values"]
    axis_values: FloatArray | None
    if axis_raw is None:
        if units is not None:
            raise ValueError("fitted MSC state cannot declare units without feature coordinates")
        axis_values = None
    else:
        axis_values = _canonical_float_vector(axis_raw, name="feature axis", length=feature_count)
    duplicated_axis = cast(
        list[str | None],
        fitted_input_identity(_identity_view(None, axis_values, units), features=feature_count)["axis"],
    )
    retained_axis = cast(list[str | None], identity["axis"])
    if retained_axis[0] != duplicated_axis[0] or retained_axis[2] != duplicated_axis[2]:
        raise ValueError("fitted MSC state axis authority contradicts retained coordinates or units")
    reference = _canonical_float_vector(state["reference_spectrum"], name="reference spectrum", length=feature_count)
    design = np.column_stack((reference, np.ones(feature_count, dtype=np.float64)))
    if np.linalg.matrix_rank(design) != 2:
        raise ValueError("fitted MSC reference is constant and cannot identify slope plus intercept")
    condition = float(np.linalg.cond(design))
    if not np.isfinite(condition) or condition > _MAX_DESIGN_CONDITION:
        raise ValueError("fitted MSC reference design is numerically ill-conditioned")
    return np.array(reference, dtype=np.float64, copy=True), axis_values, units


def _fit_msc_state(
    data: FloatArray,
    *,
    reference_method: str,
    feature_axis_values: FloatArray | None,
    feature_axis_units: str | None,
    source_dataset: Any = None,
) -> dict[str, object]:
    """Fit one reference spectrum from training/reference rows only."""

    projected = _canonical_msc_parameters({"reference_method": reference_method})
    matrix = _finite_matrix(data, name="fit input")
    axis = None if feature_axis_values is None else np.asarray(feature_axis_values, dtype=np.float64)
    if axis is not None and (axis.ndim != 1 or axis.shape[0] != matrix.shape[1] or not np.isfinite(axis).all()):
        raise ValueError("MSC fit feature axis does not match the training matrix")
    if axis is None and feature_axis_units is not None:
        raise ValueError("MSC fit cannot declare feature-axis units without coordinates")
    if projected["reference_method"] == "mean":
        reference = np.mean(matrix, axis=0, dtype=np.float64)
    elif projected["reference_method"] == "median":
        reference = np.median(matrix, axis=0)
    else:
        reference = matrix[0]
    state: dict[str, object] = {
        "serializer": _STATE_SERIALIZER,
        "reference_method": projected["reference_method"],
        "feature_count": int(matrix.shape[1]),
        "feature_axis_values": None if axis is None else axis.tolist(),
        "feature_axis_units": feature_axis_units,
        "reference_spectrum": np.asarray(reference, dtype=np.float64).tolist(),
        "input_identity": fitted_input_identity(
            _identity_view(source_dataset, axis, feature_axis_units), features=matrix.shape[1]
        ),
    }
    _validated_msc_state(state)
    return state


def _apply_msc_state(
    data: FloatArray,
    state: Mapping[str, object],
    *,
    feature_axis_values: FloatArray | None,
    feature_axis_units: str | None,
    source_dataset: Any = None,
) -> FloatArray:
    """Apply one fitted MSC reference without learning from application rows."""

    matrix = _finite_matrix(data, name="apply input")
    reference, fitted_axis, fitted_units = _validated_msc_state(state)
    if matrix.shape[1] != reference.shape[0]:
        raise ValueError("fitted MSC state does not match the supplied feature count")
    supplied_axis = None if feature_axis_values is None else np.asarray(feature_axis_values, dtype=np.float64)
    if fitted_axis is None:
        if supplied_axis is not None:
            raise ValueError("MSC apply feature axis differs from the fitted axis")
    elif (
        supplied_axis is None
        or supplied_axis.shape != fitted_axis.shape
        or not np.array_equal(supplied_axis, fitted_axis)
    ):
        raise ValueError("MSC apply feature axis differs from the fitted axis")
    if feature_axis_units != fitted_units:
        raise ValueError("MSC apply feature-axis units differ from the fitted units")
    require_fitted_input_identity(
        _identity_view(source_dataset, supplied_axis, feature_axis_units),
        state["input_identity"],
        features=matrix.shape[1],
    )
    design = np.column_stack((reference, np.ones(reference.shape[0], dtype=np.float64)))
    coefficients, _, _, _ = np.linalg.lstsq(design, matrix.T, rcond=None)
    slopes = coefficients[0]
    intercepts = coefficients[1]
    coefficient_scales = np.maximum(1.0, np.max(np.abs(coefficients), axis=0))
    unresolved = ~np.isfinite(slopes) | (np.abs(slopes) <= _MIN_RELATIVE_SLOPE * coefficient_scales)
    if np.any(unresolved):
        row_index = int(np.flatnonzero(unresolved)[0])
        raise ValueError(f"MSC multiplicative coefficient is unresolved for sample {row_index}")
    corrected = ((matrix.T - intercepts) / slopes).T
    if not np.isfinite(corrected).all():
        raise ValueError("MSC correction produced non-finite output")
    return corrected


def _msc_dispatch(
    input_data: Any,
    *,
    reference_method: str = "mean",
    reference_data: Any = None,
) -> FloatArray:
    """One-shot workbench/export dispatcher over the sole fitted MSC ABI."""

    matrix, source_axis, source_units = _dataset_view(input_data, name="input")
    fit_value = input_data if reference_data is None else reference_data
    fit_matrix, fit_axis, fit_units = _dataset_view(fit_value, name="fit reference")
    _require_same_axis((source_axis, source_units), (fit_axis, fit_units), name="input")
    state = _fit_msc_state(
        fit_matrix,
        reference_method=reference_method,
        feature_axis_values=fit_axis,
        feature_axis_units=fit_units,
        source_dataset=fit_value,
    )
    return _apply_msc_state(
        matrix,
        state,
        feature_axis_values=source_axis,
        feature_axis_units=source_units,
        source_dataset=input_data,
    )


@register_node
class MSCNode(Node):
    """Fit one MSC reference and apply the frozen slope/intercept correction."""

    metadata = NodeMetadata(
        node_type="preprocess.msc",
        category="preprocessing",
        label="Multiplicative Scatter Correction (MSC)",
        description=(
            "Fit one reference spectrum from declared reference rows, then apply its multiplicative "
            "and additive scatter correction without refitting application rows."
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
                    "Rule used to fit the reference spectrum. 'First' is row-order sensitive; "
                    "connect an explicit one-row reference when that spectrum is intentional. "
                    "Hosted managed execution admits mean or median only; use mean with an "
                    "explicit one-row reference to apply that exact spectrum."
                ),
                required=True,
            )
        ],
        input_types=["SherpaDataset"],
        input_ports=[
            PortMetadata(
                name="default",
                type_ref="spectrasherpa://types/SpectralDataset/1.0",
                required=True,
                label="Input Spectra",
                description="Spectra to correct using the frozen fitted MSC reference.",
                accepted_data_roles=["X_spectra"],
            ),
            PortMetadata(
                name="reference",
                type_ref="spectrasherpa://types/SpectralDataset/1.0",
                required=False,
                label="Fit Reference",
                description="Optional training/reference rows used to fit MSC instead of the input rows.",
                accepted_data_roles=["X_spectra"],
            ),
        ],
        output_ports=[
            PortMetadata(
                name="default",
                type_ref="spectrasherpa://types/SpectralDataset/1.0",
                required=True,
                label="MSC-Corrected Spectra",
                description="Spectra corrected with the frozen fitted reference.",
                accepted_data_roles=["X_spectra"],
            )
        ],
        output_type="SherpaDataset",
        policy=NodePolicy(),
        canonical_parameter_validator=_canonical_msc_parameters,
        managed_parameter_validator=_managed_msc_parameters,
    )

    def fit_fitted_state(self, input_data: Any) -> dict[str, object]:
        matrix, axis_values, axis_units = _dataset_view(input_data, name="input_data")
        parameters = self._resolve_params()
        return _fit_msc_state(
            matrix,
            reference_method=str(parameters["reference_method"]),
            feature_axis_values=axis_values,
            feature_axis_units=axis_units,
            source_dataset=input_data,
        )

    def apply_fitted_state(self, input_data: Any, state: Mapping[str, object]) -> SherpaDataset:
        dataset = coerce_to_sherpa(input_data, input_name="input_data")
        matrix = to_numpy_2d(dataset, name="input_data", dtype=np.float64)
        axis_values, axis_units = _feature_axis(dataset, features=matrix.shape[1])
        corrected = _apply_msc_state(
            matrix,
            state,
            feature_axis_values=axis_values,
            feature_axis_units=axis_units,
            source_dataset=dataset,
        )
        result = build_dataset_like(corrected, dataset)
        identity = validate_fitted_input_identity(state["input_identity"])
        result.units = cast(str | None, identity["signal_units"])
        add_processing_step(
            result,
            "preprocess.msc",
            {
                "reference_method": state["reference_method"],
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
        **kwargs: Any,
    ) -> NodeResult:
        del kwargs
        source = input_data if input_data is not None else default
        fit_source = reference if reference is not None else source
        state = self.fit_fitted_state(fit_source)
        output = self.apply_fitted_state(source, state)
        return NodeResult(
            outputs={"default": output},
            diagnostics={
                "reference_method": state["reference_method"],
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
        parameters = self._resolve_params()
        return [
            header_line("Canonical fitted MSC", self.node_id, indent),
            f"{indent}from spectra_sherpa.app.services.dag.nodes.preprocessing.msc_node import MSCNode",
            f"{indent}_transform = MSCNode({self.node_id!r}, {parameters!r})",
            f"{indent}_state = _transform.fit_fitted_state({reference if reference is not None else source})",
            f"{indent}results[{self.node_id!r}] = _transform.apply_fitted_state({source}, _state)",
        ]


bind_stable_execution_contract(
    MSCNode,
    runtime_family=RuntimeFamily.SHERPA_NATIVE,
    lifecycle_kind=LifecycleKind.FITTED_TRANSFORM,
    implementation_id="spectrasherpa.preprocess.msc",
    implementation_version="2.0.0",
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
        "Geladi, MacDougall & Martens, Linearization and Scatter-Correction for Near-Infrared "
        "Reflectance Spectra of Meat, Applied Spectroscopy 39 (1985) 491-500",
        "mdatools R package, msc preprocessing method",
    ),
)


__all__ = ["MSCNode", "_apply_msc_state", "_fit_msc_state", "_msc_dispatch"]
