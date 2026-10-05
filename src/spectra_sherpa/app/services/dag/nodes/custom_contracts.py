"""Closed numerical authorities for first-party custom simulation nodes.

These operations are deliberately local-only.  They help a scientist build
explicit simulation and stress-test DAGs; they are not an alternate managed
optimization vocabulary and they never infer missing calibration science.
"""

from __future__ import annotations

import hashlib
import json
import math
from typing import Any

import numpy as np

from spectra_sherpa.app.lib.axes import SampleAxis, SpectralAxis
from spectra_sherpa.app.lib.curves import evaluate_catmull_rom, generate_concentration_curve, initial_curve_points
from spectra_sherpa.app.lib.golden_grid import build_common_overlap_grid
from spectra_sherpa.app.lib.saturation_response import apply_saturation_transition
from spectra_sherpa.app.lib.sherpa_dataset import Provenance, SherpaDataset
from spectra_sherpa.app.services.dag.io_contracts import (
    bind_X,
    bind_y,
    build_dataset_like,
    coerce_to_sherpa,
    to_numpy_1d,
    to_numpy_2d,
)
from spectra_sherpa.app.services.dag.meta_helpers import add_processing_step
from spectra_sherpa.app.services.dag.nodes.preprocessing.wavenumber_align_node import (
    _require_wavenumber_axis,
    _wavenumber_align_dataset_dispatch,
)

_CONCENTRATION_UNITS = frozenset({"ppm", "ppmv", "mol/L", "mg/L", "wt%", "vol%"})
_CONCENTRATION_CURVE_TYPES = frozenset({"sigmoid", "gaussian", "linear", "exponential", "step", "constant"})


def _closed_parameters(parameters: dict[str, object], expected: set[str], *, operation: str) -> None:
    if set(parameters) != expected:
        raise ValueError(f"{operation} parameters must contain exactly {', '.join(sorted(expected))}")


def canonical_linear_calibration_parameters(parameters: dict[str, object]) -> dict[str, object]:
    """Admit one explicit affine Beer--Lambert calibration grammar."""

    _closed_parameters(parameters, {"concentration_unit"}, operation="linear-calibration")
    unit = parameters["concentration_unit"]
    if unit not in _CONCENTRATION_UNITS:
        raise ValueError("linear-calibration concentration_unit is not admitted")
    return {"concentration_unit": str(unit)}


def canonical_noise_injection_parameters(parameters: dict[str, object]) -> dict[str, object]:
    """Admit reproducible independent zero-mean Gaussian perturbation."""

    _closed_parameters(parameters, {"noise_level", "noise_type", "seed"}, operation="noise-injection")
    noise_level = parameters["noise_level"]
    seed = parameters["seed"]
    if isinstance(noise_level, bool) or not isinstance(noise_level, (int, float)):
        raise ValueError("noise_level must be a finite non-negative number")
    if not math.isfinite(float(noise_level)) or float(noise_level) < 0.0:
        raise ValueError("noise_level must be a finite non-negative number")
    if parameters["noise_type"] not in {"absolute", "relative_rms"}:
        raise ValueError("noise_type must be absolute or relative_rms")
    if isinstance(seed, bool) or not isinstance(seed, (int, float)) or not math.isfinite(float(seed)):
        raise ValueError("seed must be an integer from 0 through 4294967295")
    integer_seed = int(seed)
    if float(seed) != float(integer_seed) or not 0 <= integer_seed <= 4_294_967_295:
        raise ValueError("seed must be an integer from 0 through 4294967295")
    return {
        "noise_level": float(noise_level),
        "noise_type": str(parameters["noise_type"]),
        "seed": integer_seed,
    }


def canonical_saturation_model_parameters(parameters: dict[str, object]) -> dict[str, object]:
    """Admit the published nonlinear absorbance-transition grammar."""

    _closed_parameters(parameters, {"concentration_unit"}, operation="saturation-model")
    unit = parameters["concentration_unit"]
    if unit not in _CONCENTRATION_UNITS:
        raise ValueError("saturation-model concentration_unit is not admitted")
    return {"concentration_unit": str(unit)}


def _finite_nonnegative_number(value: object, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be a finite non-negative number")
    result = float(value)
    if not math.isfinite(result) or result < 0.0:
        raise ValueError(f"{name} must be a finite non-negative number")
    return result


def _bounded_integer(value: object, name: str, *, minimum: int, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
        raise ValueError(f"{name} must be an integer from {minimum} through {maximum}")
    integer = int(value)
    if float(value) != float(integer) or not minimum <= integer <= maximum:
        raise ValueError(f"{name} must be an integer from {minimum} through {maximum}")
    return integer


def canonical_system_saturation_parameters(parameters: dict[str, object]) -> dict[str, object]:
    """Admit one explicit detector-level saturation transition."""

    _closed_parameters(parameters, {"p_system", "s_system"}, operation="system-saturation")
    return {
        "p_system": _finite_positive_number(parameters["p_system"], "p_system"),
        "s_system": _finite_positive_number(parameters["s_system"], "s_system"),
    }


def canonical_catmull_rom_curve_parameters(parameters: dict[str, object]) -> dict[str, object]:
    """Close the normalized Catmull--Rom control-point and output grammar."""

    _closed_parameters(
        parameters,
        {"control_points", "max_concentration", "n_points"},
        operation="catmull-rom-curve",
    )
    n_points = _bounded_integer(parameters["n_points"], "n_points", minimum=10, maximum=100_000)
    maximum = _finite_nonnegative_number(parameters["max_concentration"], "max_concentration")
    raw_points = parameters["control_points"]
    if raw_points == []:
        raw_points = initial_curve_points(11)
    if not isinstance(raw_points, list) or not 2 <= len(raw_points) <= 1_000:
        raise ValueError("control_points must contain from 2 through 1000 points")
    points: list[dict[str, float]] = []
    for index, point in enumerate(raw_points):
        if not isinstance(point, dict) or set(point) != {"x", "y"}:
            raise ValueError(f"control_points[{index}] must contain exactly x and y")
        x_value = _finite_nonnegative_number(point["x"], f"control_points[{index}].x")
        y_value = _finite_nonnegative_number(point["y"], f"control_points[{index}].y")
        if x_value > 100.0 or y_value > 1.0:
            raise ValueError("control point x must be in [0, 100] and y must be in [0, 1]")
        if points and x_value <= points[-1]["x"]:
            raise ValueError("control point x values must be strictly increasing")
        points.append({"x": x_value, "y": y_value})
    return {"control_points": points, "max_concentration": maximum, "n_points": n_points}


def canonical_concentration_curve_parameters(parameters: dict[str, object]) -> dict[str, object]:
    """Admit one normalized concentration profile without ignored settings."""

    _closed_parameters(
        parameters,
        {"center", "curve_type", "max_concentration", "n_points", "width"},
        operation="concentration-curve",
    )
    curve_type = parameters["curve_type"]
    if curve_type not in _CONCENTRATION_CURVE_TYPES:
        raise ValueError("concentration curve_type is not admitted")
    n_points = _bounded_integer(parameters["n_points"], "n_points", minimum=10, maximum=100_000)
    maximum = _finite_nonnegative_number(parameters["max_concentration"], "max_concentration")
    center = _finite_nonnegative_number(parameters["center"], "center")
    width = _finite_positive_number(parameters["width"], "width")
    if center > 1.0 or width > 1.0:
        raise ValueError("center and width must be in the normalized interval (0, 1], with center allowing zero")
    if curve_type in {"linear", "constant"} and (center != 0.5 or width != 0.1):
        raise ValueError(f"{curve_type} concentration curves require the declared default center and width")
    if curve_type == "exponential" and center != 0.5:
        raise ValueError("exponential concentration curves require the declared default center")
    if curve_type == "step" and width != 0.1:
        raise ValueError("step concentration curves require the declared default width")
    return {
        "center": center,
        "curve_type": str(curve_type),
        "max_concentration": maximum,
        "n_points": n_points,
        "width": width,
    }


def canonical_hybrid_selector_parameters(parameters: dict[str, object]) -> dict[str, object]:
    """The selector applies an upstream decision and owns no heuristic settings."""

    _closed_parameters(parameters, set(), operation="hybrid-selector")
    return {}


def canonical_golden_grid_parameters(parameters: dict[str, object]) -> dict[str, object]:
    """Admit one measured-overlap grid and explicit resolution policy."""

    expected = {"coverage_policy", "extrapolation", "max_upsampling_factor", "merge_tolerance", "method"}
    _closed_parameters(parameters, expected, operation="golden-grid-align")
    method = parameters["method"]
    if method not in {"linear", "pchip", "sinc"}:
        raise ValueError("golden-grid-align method must be linear, pchip, or sinc")
    if parameters["coverage_policy"] != "common_overlap":
        raise ValueError("golden-grid-align coverage_policy must be common_overlap")
    if parameters["extrapolation"] != "reject":
        raise ValueError("golden-grid-align extrapolation must be reject")
    tolerance = _finite_positive_number(parameters["merge_tolerance"], "merge_tolerance")
    maximum = _finite_positive_number(parameters["max_upsampling_factor"], "max_upsampling_factor")
    if maximum < 1.0:
        raise ValueError("max_upsampling_factor must be at least 1")
    return {
        "coverage_policy": "common_overlap",
        "extrapolation": "reject",
        "max_upsampling_factor": maximum,
        "merge_tolerance": tolerance,
        "method": str(method),
    }


def _finite_positive_number(value: object, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be a finite positive number")
    result = float(value)
    if not math.isfinite(result) or result <= 0.0:
        raise ValueError(f"{name} must be a finite positive number")
    return result


def _dataset_binding_digest(dataset: SherpaDataset) -> str:
    return dataset.scientific_digest


def _combined_sample_axis(datasets: list[SherpaDataset]) -> SampleAxis:
    labels: list[str] = []
    classes: list[object] = []
    include_mask: list[bool] = []
    exclusion_reasons: list[str | None] = []
    table_rows: list[dict[str, object]] = []
    have_classes = [dataset.sample_axis is not None and dataset.sample_axis.classes is not None for dataset in datasets]
    have_masks = [
        dataset.sample_axis is not None and dataset.sample_axis.include_mask is not None for dataset in datasets
    ]
    have_reasons = [
        dataset.sample_axis is not None and dataset.sample_axis.exclusion_reasons is not None for dataset in datasets
    ]
    for present, name in (
        (have_classes, "classes"),
        (have_masks, "include masks"),
        (have_reasons, "exclusion reasons"),
    ):
        if any(present) and not all(present):
            raise ValueError(f"golden-grid inputs must either all provide {name} or all omit them")

    for source_index, dataset in enumerate(datasets):
        axis = dataset.sample_axis
        source_labels = axis.labels if axis is not None and axis.labels is not None else None
        source_table = axis.sample_table if axis is not None and axis.sample_table is not None else {}
        for sample_index in range(dataset.n_samples):
            labels.append(
                str(source_labels[sample_index])
                if source_labels is not None
                else f"source-{source_index + 1}:sample-{sample_index + 1}"
            )
            row = {key: values[sample_index] for key, values in source_table.items()}
            row["golden_grid_source_index"] = source_index
            row["golden_grid_source_sample_index"] = sample_index
            table_rows.append(row)
        if all(have_classes):
            classes.extend(np.asarray(axis.classes).tolist())  # type: ignore[union-attr]
        if all(have_masks):
            include_mask.extend(np.asarray(axis.include_mask, dtype=bool).tolist())  # type: ignore[union-attr]
        if all(have_reasons):
            exclusion_reasons.extend(axis.exclusion_reasons or [])  # type: ignore[union-attr]

    columns = sorted({key for row in table_rows for key in row})
    sample_table = {key: [row.get(key) for row in table_rows] for key in columns}
    return SampleAxis(
        values=np.arange(len(labels), dtype=np.float64),
        labels=labels,
        title="Golden-grid observation",
        classes=np.asarray(classes) if all(have_classes) else None,
        include_mask=np.asarray(include_mask, dtype=bool) if all(have_masks) else None,
        exclusion_reasons=exclusion_reasons if all(have_reasons) else None,
        sample_table=sample_table,
    )


def build_golden_grid_alignment_result(
    spectra: Any,
    parameters: dict[str, object],
    *,
    node_id: str,
) -> tuple[SherpaDataset, dict[str, object]]:
    """Align and stack every input on one common measured wavenumber grid."""

    canonical = canonical_golden_grid_parameters(parameters)
    if not isinstance(spectra, (list, tuple)) or not spectra:
        raise ValueError("golden-grid alignment requires a non-empty list of spectra")
    datasets = [coerce_to_sherpa(value, input_name=f"spectra[{index}]") for index, value in enumerate(spectra)]
    first = datasets[0]
    if not isinstance(first.units, str) or not first.units.strip():
        raise ValueError("golden-grid inputs require explicit signal units")
    if str(first.data_role) != "X_spectra":
        raise ValueError("golden-grid inputs must have the X_spectra data role")
    axes: list[np.ndarray] = []
    for index, dataset in enumerate(datasets):
        axis, _ = _require_wavenumber_axis(dataset, name=f"golden-grid input {index}")
        axes.append(np.asarray(axis.values, dtype=np.float64))
        if dataset.units != first.units:
            raise ValueError("golden-grid inputs must have exactly compatible signal units")
        if dataset.data_role != first.data_role:
            raise ValueError("golden-grid inputs must have exactly compatible data roles")
        if dataset.domain != first.domain:
            raise ValueError("golden-grid inputs must have exactly compatible scientific domains")
        if dataset.target_context != first.target_context:
            raise ValueError("golden-grid inputs must have exactly compatible target contexts")
        if dataset.is_time_series != first.is_time_series:
            raise ValueError("golden-grid inputs must agree on time-series semantics")

    target_presence = [dataset.target is not None for dataset in datasets]
    if any(target_presence) and not all(target_presence):
        raise ValueError("golden-grid inputs must either all provide targets or all omit them")

    grid = build_common_overlap_grid(axes, merge_tolerance=float(canonical["merge_tolerance"]))
    reference = SherpaDataset(
        X=np.zeros((1, grid.size), dtype=np.float64),
        feature_axis=SpectralAxis(values=grid, units="cm-1", title="Golden-grid wavenumber"),
        units=first.units,
        data_role=first.data_role,
    )
    aligned: list[np.ndarray] = []
    per_source: list[dict[str, object]] = []
    maximum = float(canonical["max_upsampling_factor"])
    for index, dataset in enumerate(datasets):
        values, diagnostics = _wavenumber_align_dataset_dispatch(
            dataset,
            reference,
            method=str(canonical["method"]),
            extrapolation="reject",
        )
        factor = float(diagnostics["upsampling_factor"])
        if factor > maximum and not math.isclose(factor, maximum, rel_tol=1e-12, abs_tol=1e-12):
            raise ValueError(
                f"golden-grid input {index} requires upsampling factor {factor:.12g}, "
                f"above the admitted maximum {maximum:.12g}"
            )
        aligned.append(values)
        per_source.append({"source_index": index, **diagnostics})

    matrix = np.vstack(aligned)
    target = (
        np.concatenate([np.asarray(dataset.target) for dataset in datasets], axis=0) if all(target_presence) else None
    )
    source_digests = [_dataset_binding_digest(dataset) for dataset in datasets]
    impact: dict[str, object] = {
        "schema_version": "spectrasherpa-golden-grid-align-impact/1",
        "adds_measured_resolution": False,
        "common_overlap_maximum": float(grid.max()),
        "common_overlap_minimum": float(grid.min()),
        "input_count": len(datasets),
        "input_dataset_digests": source_digests,
        "input_sample_counts": [dataset.n_samples for dataset in datasets],
        "output_feature_count": int(grid.size),
        "output_sample_count": int(matrix.shape[0]),
        "per_source_alignment": per_source,
        "reference_grid_sha256": _array_digest(grid),
        "resolution_note": "Interpolation onto a finer grid does not add measured spectral resolution.",
    }
    result = SherpaDataset(
        X=matrix,
        feature_axis=reference.feature_axis,
        sample_axis=_combined_sample_axis(datasets),
        target=target,
        target_context=first.target_context.model_copy(deep=True),
        domain=first.domain.model_copy(deep=True),
        provenance=Provenance(),
        title="Golden-grid aligned spectra",
        units=first.units,
        is_time_series=first.is_time_series,
        data_role=first.data_role,
    )
    add_processing_step(
        result,
        "custom.golden_grid_align",
        canonical,
        node_id=node_id,
        input_shape=(sum(dataset.n_samples for dataset in datasets), max(dataset.n_features for dataset in datasets)),
        impact=impact,
    )
    result.meta["golden_grid_alignment"] = impact
    return result, impact


def _finite_vector(calibration: dict[str, Any], name: str, *, features: int) -> np.ndarray:
    if name not in calibration:
        raise ValueError(f"linear calibration metadata requires {name}")
    value = np.asarray(calibration[name], dtype=np.float64)
    if value.ndim != 1 or value.shape != (features,):
        raise ValueError(f"linear calibration {name} must contain exactly one value per feature")
    if not np.isfinite(value).all():
        raise ValueError(f"linear calibration {name} must contain only finite values")
    return value


def _reference_is_applied(metadata: dict[str, Any]) -> bool:
    if metadata.get("reference_applied") is True:
        return True
    chemometrics = metadata.get("chemometrics")
    if not isinstance(chemometrics, dict):
        return False
    reference = chemometrics.get("reference")
    return isinstance(reference, dict) and reference.get("applied") is True


def _calibration_digest(*, slope: np.ndarray, intercept: np.ndarray, concentration_unit: str) -> str:
    payload = {
        "concentration_unit": concentration_unit,
        "intercept_sha256": hashlib.sha256(np.asarray(intercept, dtype="<f8").tobytes()).hexdigest(),
        "slope_sha256": hashlib.sha256(np.asarray(slope, dtype="<f8").tobytes()).hexdigest(),
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    ).hexdigest()


def _array_digest(value: np.ndarray) -> str:
    return hashlib.sha256(np.asarray(value, dtype="<f8").tobytes(order="C")).hexdigest()


def _finite_input_vector(value: Any, name: str, *, features: int | None = None) -> np.ndarray:
    vector = to_numpy_1d(value, name=name, dtype=np.float64)
    if vector.size == 0 or not np.isfinite(vector).all():
        raise ValueError(f"{name} must be a non-empty finite vector")
    if features is not None and vector.shape != (features,):
        raise ValueError(f"{name} must contain exactly one value per feature")
    return vector


def _finite_scalar(value: Any, name: str) -> float:
    array = np.asarray(value, dtype=np.float64)
    if array.size != 1:
        raise ValueError(f"{name} must be one finite scalar")
    scalar = float(array.reshape(-1)[0])
    if not math.isfinite(scalar):
        raise ValueError(f"{name} must be one finite scalar")
    return scalar


def build_saturation_model_result(
    sensitivity: Any,
    saturation_levels: Any,
    shape_exponents: Any,
    concentrations: Any,
    calibration_minimum: Any,
    calibration_maximum: Any,
    parameters: dict[str, object],
    *,
    node_id: str,
) -> tuple[Any, dict[str, object]]:
    """Evaluate a complete, explicit nonlinear concentration response."""

    canonical = canonical_saturation_model_parameters(parameters)
    source = bind_X(
        sensitivity,
        missing_message="saturation model requires a sensitivity spectrum",
        dataset_error_message="saturation sensitivity must be a dataset",
    )
    if source.shape[0] != 1:
        raise ValueError("saturation model requires exactly one sensitivity spectrum")
    if source.feature_axis is None:
        raise ValueError("saturation sensitivity requires an explicit feature axis")
    expected_sensitivity_unit = f"absorbance/{canonical['concentration_unit']}"
    if str(source.units) != expected_sensitivity_unit:
        raise ValueError(
            "saturation sensitivity units must exactly match "
            f"{expected_sensitivity_unit!r} for the declared concentration unit"
        )
    sensitivity_values = to_numpy_2d(source, name="sensitivity spectrum", dtype=np.float64)[0]
    if not np.isfinite(sensitivity_values).all() or np.any(sensitivity_values < 0.0):
        raise ValueError("saturation sensitivity must be finite and non-negative at every feature")
    features = int(sensitivity_values.size)
    levels = _finite_input_vector(saturation_levels, "saturation_levels", features=features)
    exponents = _finite_input_vector(shape_exponents, "shape_exponents", features=features)
    if np.any(levels <= 0.0):
        raise ValueError("saturation_levels must be strictly positive at every feature")
    if np.any(exponents <= 0.0):
        raise ValueError("shape_exponents must be strictly positive at every feature")
    concentration_input = bind_y(
        concentrations,
        infer_from_X=False,
        required=True,
        dataset_as_data=True,
        missing_message="saturation model requires concentrations",
    )
    concentration_values = _finite_input_vector(concentration_input, "concentrations")
    if np.any(concentration_values < 0.0):
        raise ValueError("saturation model concentrations must be non-negative")
    minimum = _finite_scalar(calibration_minimum, "calibration_minimum")
    maximum = _finite_scalar(calibration_maximum, "calibration_maximum")
    if minimum < 0.0 or maximum <= minimum:
        raise ValueError("saturation calibration range must satisfy 0 <= minimum < maximum")
    if np.any(concentration_values < minimum) or np.any(concentration_values > maximum):
        raise ValueError("saturation model concentrations fall outside the declared calibration range")

    ideal = concentration_values[:, np.newaxis] * sensitivity_values[np.newaxis, :]
    absorbance = apply_saturation_transition(
        ideal,
        levels[np.newaxis, :],
        exponents[np.newaxis, :],
    )
    state_payload = {
        "calibration_maximum": maximum,
        "calibration_minimum": minimum,
        "concentration_unit": canonical["concentration_unit"],
        "sensitivity_unit": expected_sensitivity_unit,
        "saturation_levels_sha256": _array_digest(levels),
        "sensitivity_sha256": _array_digest(sensitivity_values),
        "shape_exponents_sha256": _array_digest(exponents),
    }
    state_digest = hashlib.sha256(
        json.dumps(state_payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    ).hexdigest()
    result = build_dataset_like(
        absorbance,
        source,
        units="absorbance",
        title=f"{source.title or 'Sensitivity'} saturation response",
    )
    result.sample_axis = SampleAxis(values=np.arange(concentration_values.size), title="Concentration observation")
    result.meta["calibration_model"] = "rodionova_pomerantsev_saturation"
    result.meta["calibration_state_digest"] = state_digest
    result.meta["concentration_unit"] = canonical["concentration_unit"]
    impact: dict[str, object] = {
        "schema_version": "spectrasherpa-saturation-model-impact/1",
        "calibration_state_digest": state_digest,
        "calibration_minimum": minimum,
        "calibration_maximum": maximum,
        "concentration_count": int(concentration_values.size),
        "feature_count": features,
        "sensitivity_unit": expected_sensitivity_unit,
        "output_minimum": float(absorbance.min()),
        "output_maximum": float(absorbance.max()),
    }
    add_processing_step(
        result,
        "custom.saturation_model",
        canonical,
        node_id=node_id,
        input_shape=source.shape,
        impact=impact,
    )
    return result, impact


def _axis_signature(axis: Any) -> tuple[object, object, object]:
    if axis is None:
        return (None, None, None)
    values = np.asarray(getattr(axis, "values", []))
    raw_labels = getattr(axis, "labels", None)
    labels = () if raw_labels is None else tuple(str(item) for item in raw_labels)
    return (_array_digest(values), str(getattr(axis, "units", None)), labels)


def build_hybrid_selector_result(
    linear_result: Any,
    saturation_result: Any,
    model_mask: Any,
    parameters: dict[str, object],
    *,
    node_id: str,
) -> tuple[Any, dict[str, object]]:
    """Apply a declared per-feature model decision without choosing it."""

    canonical_hybrid_selector_parameters(parameters)
    linear = bind_X(
        linear_result,
        missing_message="hybrid selector requires a linear result",
        dataset_error_message="hybrid linear result must be a dataset",
    )
    saturation = bind_X(
        saturation_result,
        missing_message="hybrid selector requires a saturation result",
        dataset_error_message="hybrid saturation result must be a dataset",
    )
    linear_data = to_numpy_2d(linear, name="linear_result", dtype=np.float64)
    saturation_data = to_numpy_2d(saturation, name="saturation_result", dtype=np.float64)
    if not np.isfinite(linear_data).all() or not np.isfinite(saturation_data).all():
        raise ValueError("hybrid selector inputs must contain only finite values")
    if linear_data.shape != saturation_data.shape:
        raise ValueError("hybrid selector inputs must have identical shapes")
    if linear.units != saturation.units:
        raise ValueError("hybrid selector inputs must have identical units")
    if _axis_signature(linear.feature_axis) != _axis_signature(saturation.feature_axis):
        raise ValueError("hybrid selector inputs must have identical feature axes")
    if _axis_signature(linear.sample_axis) != _axis_signature(saturation.sample_axis):
        raise ValueError("hybrid selector inputs must have identical sample axes")
    mask_values = _finite_input_vector(model_mask, "model_mask", features=linear_data.shape[1])
    if not np.all(np.logical_or(mask_values == 0.0, mask_values == 1.0)):
        raise ValueError("model_mask must contain exactly zero or one for every feature")
    mask = mask_values.astype(bool)
    selected = np.where(mask[np.newaxis, :], saturation_data, linear_data)
    mask_digest = _array_digest(mask_values)
    result = build_dataset_like(selected, linear)
    result.meta["hybrid_model_mask_sha256"] = mask_digest
    impact: dict[str, object] = {
        "schema_version": "spectrasherpa-explicit-hybrid-selection-impact/1",
        "model_mask_sha256": mask_digest,
        "feature_count": int(mask.size),
        "linear_feature_count": int((~mask).sum()),
        "saturation_feature_count": int(mask.sum()),
        "selection_authority": "upstream_explicit_mask",
    }
    add_processing_step(
        result,
        "custom.hybrid_selector",
        {},
        node_id=node_id,
        input_shape=linear.shape,
        impact=impact,
    )
    return result, impact


def build_system_saturation_result(
    input_data: Any,
    parameters: dict[str, object],
    *,
    node_id: str,
) -> tuple[SherpaDataset, dict[str, object]]:
    """Apply the published transition once to a complete blended dataset."""

    canonical = canonical_system_saturation_parameters(parameters)
    source = bind_X(
        input_data,
        missing_message="system saturation requires input spectra",
        dataset_error_message="system saturation input must be a dataset",
    )
    matrix = to_numpy_2d(source, name="input_data", dtype=np.float64)
    if not np.isfinite(matrix).all() or np.any(matrix < 0.0):
        raise ValueError("system saturation requires finite non-negative absorbance")
    saturated = apply_saturation_transition(
        matrix,
        float(canonical["s_system"]),
        float(canonical["p_system"]),
    )
    result = build_dataset_like(saturated, source)
    impact: dict[str, object] = {
        "schema_version": "spectrasherpa-system-saturation-impact/1",
        "input_maximum": float(matrix.max()),
        "output_maximum": float(saturated.max()),
        "p_system": canonical["p_system"],
        "s_system": canonical["s_system"],
    }
    add_processing_step(
        result,
        "custom.system_saturation",
        canonical,
        node_id=node_id,
        input_shape=source.shape,
        impact=impact,
    )
    result.meta["system_saturation"] = impact
    return result, impact


def build_catmull_rom_curve_result(
    parameters: dict[str, object],
) -> tuple[np.ndarray, dict[str, object]]:
    """Evaluate the one normalized Catmull--Rom curve authority."""

    canonical = canonical_catmull_rom_curve_parameters(parameters)
    curve = float(canonical["max_concentration"]) * evaluate_catmull_rom(
        canonical["control_points"],  # type: ignore[arg-type]
        int(canonical["n_points"]),
    )
    if curve.shape != (int(canonical["n_points"]),) or not np.isfinite(curve).all():
        raise ValueError("Catmull-Rom evaluation produced an invalid curve")
    diagnostics: dict[str, object] = {
        "control_point_count": len(canonical["control_points"]),  # type: ignore[arg-type]
        "maximum": float(curve.max()),
        "minimum": float(curve.min()),
        "n_points": int(curve.size),
        "normalized_axis": [0.0, 100.0],
    }
    return curve, diagnostics


def build_concentration_curve_result(
    parameters: dict[str, object],
) -> tuple[np.ndarray, dict[str, object]]:
    """Evaluate one explicit normalized concentration-profile family."""

    canonical = canonical_concentration_curve_parameters(parameters)
    curve = generate_concentration_curve(
        curve_type=str(canonical["curve_type"]),
        n_points=int(canonical["n_points"]),
        max_concentration=float(canonical["max_concentration"]),
        center=float(canonical["center"]),
        width=float(canonical["width"]),
    )
    curve = np.asarray(curve, dtype=np.float64)
    if curve.shape != (int(canonical["n_points"]),) or not np.isfinite(curve).all() or np.any(curve < 0.0):
        raise ValueError("concentration-curve evaluation produced an invalid curve")
    diagnostics: dict[str, object] = {
        "curve_type": canonical["curve_type"],
        "maximum": float(curve.max()),
        "minimum": float(curve.min()),
        "n_points": int(curve.size),
        "normalized_time_axis": [0.0, 1.0],
    }
    return curve, diagnostics


def build_linear_calibration_result(
    spectrum: Any,
    concentrations: Any,
    parameters: dict[str, object],
    *,
    node_id: str,
) -> tuple[Any, dict[str, object]]:
    """Apply one complete affine calibration without inferred coefficients."""

    parameters = canonical_linear_calibration_parameters(parameters)
    source = bind_X(
        spectrum,
        missing_message="linear calibration requires a spectrum",
        dataset_error_message="linear calibration spectrum must be a dataset",
    )
    concentration_input = bind_y(
        concentrations,
        infer_from_X=False,
        required=True,
        dataset_as_data=True,
        missing_message="linear calibration requires concentrations",
    )
    values = to_numpy_1d(concentration_input, name="concentrations", dtype=np.float64)
    if values.size == 0 or not np.isfinite(values).all():
        raise ValueError("linear calibration concentrations must be non-empty and finite")
    if np.any(values < 0.0):
        raise ValueError("linear calibration concentrations must be non-negative")
    if source.shape[0] != 1:
        raise ValueError("linear calibration requires exactly one reference spectrum")
    if source.feature_axis is None:
        raise ValueError("linear calibration spectrum requires an explicit feature axis")
    metadata = source.meta
    calibration = metadata.get("calibration")
    if not isinstance(calibration, dict):
        raise ValueError("linear calibration requires explicit calibration metadata")
    unit = parameters["concentration_unit"]
    if calibration.get("concentration_unit") != unit:
        raise ValueError("linear calibration concentration unit does not match calibration metadata")
    if not _reference_is_applied(metadata):
        raise ValueError("linear calibration requires an explicitly applied reference spectrum")
    features = int(source.shape[-1])
    slope = _finite_vector(calibration, "slope", features=features)
    intercept = _finite_vector(calibration, "intercept", features=features)
    if np.any(slope < 0.0):
        raise ValueError("linear calibration slope must be non-negative at every feature")
    with np.errstate(over="raise", invalid="raise"):
        absorbance = values[:, np.newaxis] * slope[np.newaxis, :] + intercept[np.newaxis, :]
    if not np.isfinite(absorbance).all():
        raise ValueError("linear calibration produced a non-finite result")

    calibration_digest = _calibration_digest(
        slope=slope,
        intercept=intercept,
        concentration_unit=str(unit),
    )
    result = build_dataset_like(
        absorbance,
        source,
        units="absorbance",
        title=f"{source.title or 'Spectrum'} linear calibration",
    )
    result.sample_axis = SampleAxis(values=np.arange(values.size), title="Concentration observation")
    result.meta["calibration_model"] = "affine_beer_lambert"
    result.meta["calibration_digest"] = calibration_digest
    result.meta["concentration_unit"] = unit
    impact = {
        "schema_version": "spectrasherpa-linear-calibration-impact/1",
        "calibration_digest": calibration_digest,
        "concentration_count": int(values.size),
        "concentration_minimum": float(values.min()),
        "concentration_maximum": float(values.max()),
        "feature_count": features,
        "output_minimum": float(absorbance.min()),
        "output_maximum": float(absorbance.max()),
        "reference_applied": True,
    }
    add_processing_step(
        result,
        "custom.linear_calibration",
        parameters,
        node_id=node_id,
        input_shape=source.shape,
        impact=impact,
    )
    return result, impact


def inject_gaussian_noise(
    data: np.ndarray,
    parameters: dict[str, object],
) -> tuple[np.ndarray, dict[str, object]]:
    """Add independent Gaussian deviates through one invocation-local RNG."""

    parameters = canonical_noise_injection_parameters(parameters)
    matrix = np.asarray(data, dtype=np.float64)
    if matrix.ndim != 2 or matrix.shape[0] < 1 or matrix.shape[1] < 1:
        raise ValueError("noise injection requires a non-empty two-dimensional matrix")
    if not np.isfinite(matrix).all():
        raise ValueError("noise injection input must contain only finite values")
    level = float(parameters["noise_level"])
    if parameters["noise_type"] == "relative_rms":
        maximum = float(np.max(np.abs(matrix)))
        reference_scale = 0.0 if maximum == 0.0 else maximum * float(np.sqrt(np.mean(np.square(matrix / maximum))))
        standard_deviation = level * reference_scale
    else:
        reference_scale = 1.0
        standard_deviation = level
    if not math.isfinite(standard_deviation):
        raise ValueError("noise injection standard deviation must be finite")
    rng = np.random.default_rng(int(parameters["seed"]))
    perturbation = rng.normal(0.0, standard_deviation, size=matrix.shape)
    result = matrix + perturbation
    if not np.isfinite(result).all():
        raise ValueError("noise injection produced a non-finite result")
    diagnostics: dict[str, object] = {
        "schema_version": "spectrasherpa-gaussian-noise-impact/1",
        "noise_type": parameters["noise_type"],
        "noise_level": level,
        "reference_scale": reference_scale,
        "standard_deviation": standard_deviation,
        "seed": parameters["seed"],
        "sample_count": int(matrix.shape[0]),
        "feature_count": int(matrix.shape[1]),
    }
    return result, diagnostics


def build_noise_injection_result(
    source: Any,
    parameters: dict[str, object],
    *,
    node_id: str,
) -> tuple[Any, dict[str, object]]:
    """Return the typed live/export result from the shared Gaussian core."""

    dataset = bind_X(
        source,
        missing_message="noise injection requires input spectra",
        dataset_error_message="noise injection input must be a dataset",
    )
    canonical = canonical_noise_injection_parameters(parameters)
    perturbed, diagnostics = inject_gaussian_noise(
        to_numpy_2d(dataset, name="input spectra", dtype=np.float64),
        canonical,
    )
    result = build_dataset_like(perturbed, dataset)
    add_processing_step(
        result,
        "custom.noise_injection",
        canonical,
        node_id=node_id,
        input_shape=dataset.shape,
        impact=diagnostics,
    )
    result.meta["noise_injection_diagnostics"] = diagnostics
    return result, diagnostics


__all__ = [
    "apply_saturation_transition",
    "build_hybrid_selector_result",
    "build_linear_calibration_result",
    "build_noise_injection_result",
    "build_saturation_model_result",
    "canonical_hybrid_selector_parameters",
    "canonical_linear_calibration_parameters",
    "canonical_noise_injection_parameters",
    "canonical_saturation_model_parameters",
    "inject_gaussian_noise",
]
