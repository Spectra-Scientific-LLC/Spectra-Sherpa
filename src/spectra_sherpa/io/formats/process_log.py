"""Canonical MATLAB process-log decoding for wafer/time/feature arrays."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

import numpy as np

from spectra_sherpa.app.lib.axes import FeatureAxis, SampleAxis, SpectralAxis, TimeAxis
from spectra_sherpa.app.lib.sherpa_dataset import (
    DatasetDescriptiveContext,
    DatasetLayoutContext,
    DatasetSourceIdentity,
    DomainContext,
    Provenance,
    SherpaDataset,
)
from spectra_sherpa.ingestion_errors import UnreadableSpectrumError
from spectra_sherpa.io.base import BoundedSource

PROCESS_LOG_SCHEMA = "spectrasherpa-matlab-process-log/1"
_REQUIRED_FIELDS = frozenset(
    {
        "calibration",
        "calib_names",
        "test",
        "test_names",
        "fault_names",
    }
)
_AXIS_FIELDS = frozenset({"wave_axis", "variables"})


@dataclass(frozen=True, slots=True)
class ProcessLogFootprint:
    """Bounded decoded footprint known after scipy inventories the struct."""

    elements: int
    decoded_bytes: int
    metadata_bytes: int
    blocks: int


@dataclass(frozen=True, slots=True)
class _DecodedProcessLog:
    calibration: tuple[np.ndarray, ...]
    test: tuple[np.ndarray, ...]
    calibration_names: tuple[str, ...]
    test_names: tuple[str, ...]
    fault_names: tuple[str, ...]
    feature_values: np.ndarray | None
    feature_labels: tuple[str, ...] | None
    feature_units: tuple[str, ...] | None
    information: tuple[str, ...]

    @property
    def wafers(self) -> tuple[np.ndarray, ...]:
        return self.calibration + self.test

    @property
    def n_features(self) -> int:
        return int(self.wafers[0].shape[1])

    @property
    def max_time_points(self) -> int:
        return max(int(wafer.shape[0]) for wafer in self.wafers)


def _fail(detail: str) -> UnreadableSpectrumError:
    return UnreadableSpectrumError(format_id="matlab", detail=f"MATLAB process log {detail}")


def _unwrap_singleton(value: Any) -> Any:
    current = value
    for _ in range(12):
        if isinstance(current, np.ndarray) and current.dtype == object and current.size == 1:
            current = current.reshape(-1, order="F")[0]
            continue
        break
    return current


def _text(value: Any, *, field: str, allow_empty: bool = False) -> str:
    current = _unwrap_singleton(value)
    if isinstance(current, bytes):
        try:
            result = current.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise _fail(f"field {field!r} is not UTF-8 text") from exc
    elif isinstance(current, str):
        result = current
    elif isinstance(current, np.ndarray) and current.dtype.kind in "US":
        flattened = current.reshape(-1, order="F").tolist()
        result = (
            "".join(str(item) for item in flattened)
            if all(len(str(item)) <= 1 for item in flattened)
            else str(flattened[0])
        )
    else:
        raise _fail(f"field {field!r} must contain text")
    result = result.strip()
    if (not result and not allow_empty) or len(result) > 4096:
        raise _fail(f"field {field!r} contains invalid bounded text")
    return result


def _text_vector(
    value: Any,
    *,
    field: str,
    required_length: int | None = None,
    allow_empty: bool = False,
) -> tuple[str, ...]:
    current = _unwrap_singleton(value)
    array = np.asarray(current, dtype=object)
    if array.ndim > 2 or array.size > 65_536:
        raise _fail(f"field {field!r} must be one bounded text vector")
    result = tuple(
        _text(item, field=f"{field}[{index}]", allow_empty=allow_empty)
        for index, item in enumerate(array.reshape(-1, order="F"))
    )
    if required_length is not None and len(result) != required_length:
        raise _fail(f"field {field!r} length does not match its wafer collection")
    return result


def _wafer_collection(value: Any, *, field: str) -> tuple[np.ndarray, ...]:
    # ``scipy_struct_fields`` has already removed the scalar struct wrapper.
    # Retain a 1×1 object array here because it is a valid one-wafer cell
    # collection; recursively unwrapping it would incorrectly expose every
    # numeric element of that wafer as a separate cell.
    cells = np.asarray(value, dtype=object)
    if cells.ndim not in {1, 2} or cells.size == 0 or cells.size > 65_536:
        raise _fail(f"field {field!r} must be one non-empty bounded cell vector")
    wafers: list[np.ndarray] = []
    n_features: int | None = None
    for index, item in enumerate(cells.reshape(-1, order="F")):
        wafer = np.asarray(_unwrap_singleton(item))
        if wafer.ndim != 2 or wafer.shape[0] == 0 or wafer.shape[1] == 0:
            raise _fail(f"field {field!r} wafer {index} must be one non-empty time-by-feature matrix")
        if not np.issubdtype(wafer.dtype, np.number) or np.issubdtype(wafer.dtype, np.complexfloating):
            raise _fail(f"field {field!r} wafer {index} must contain real numeric values")
        if n_features is None:
            n_features = int(wafer.shape[1])
        elif wafer.shape[1] != n_features:
            raise _fail(f"field {field!r} wafer feature counts differ")
        wafers.append(np.asarray(wafer, dtype=np.float64))
    return tuple(wafers)


def is_process_log_field_set(fields: tuple[str, ...]) -> bool:
    """Return whether a struct declares the closed process-log signature."""

    names = frozenset(str(field).lower() for field in fields)
    return _REQUIRED_FIELDS <= names and len(names & _AXIS_FIELDS) == 1


def _decode(fields: Mapping[str, Any]) -> _DecodedProcessLog:
    normalized = {str(key).lower(): value for key, value in fields.items()}
    if not is_process_log_field_set(tuple(normalized)):
        raise _fail("does not declare the required calibration, test, name, fault, and feature fields")
    calibration = _wafer_collection(normalized["calibration"], field="calibration")
    test = _wafer_collection(normalized["test"], field="test")
    wafers = calibration + test
    n_features = int(wafers[0].shape[1])
    if any(wafer.shape[1] != n_features for wafer in wafers):
        raise _fail("calibration and test feature counts differ")

    calibration_names = _text_vector(normalized["calib_names"], field="calib_names", required_length=len(calibration))
    test_names = _text_vector(normalized["test_names"], field="test_names", required_length=len(test))
    fault_names = _text_vector(normalized["fault_names"], field="fault_names", required_length=len(test))

    feature_values: np.ndarray | None = None
    feature_labels: tuple[str, ...] | None = None
    if "wave_axis" in normalized:
        raw_axis = np.asarray(_unwrap_singleton(normalized["wave_axis"]))
        if not np.issubdtype(raw_axis.dtype, np.number) or np.issubdtype(raw_axis.dtype, np.complexfloating):
            raise _fail("field 'wave_axis' must contain real numeric values")
        feature_values = np.asarray(raw_axis, dtype=np.float64).reshape(-1, order="F")
        if feature_values.size != n_features or not np.isfinite(feature_values).all():
            raise _fail("field 'wave_axis' does not match the process-log feature count")
    else:
        feature_labels = _text_vector(normalized["variables"], field="variables", required_length=n_features)

    feature_units = None
    if "units" in normalized:
        feature_units = _text_vector(normalized["units"], field="units", required_length=n_features)
    information = (
        _text_vector(normalized["information"], field="INFORMATION", allow_empty=True)
        if "information" in normalized
        else ()
    )
    return _DecodedProcessLog(
        calibration=calibration,
        test=test,
        calibration_names=calibration_names,
        test_names=test_names,
        fault_names=fault_names,
        feature_values=feature_values,
        feature_labels=feature_labels,
        feature_units=feature_units,
        information=information,
    )


def process_log_footprint(fields: Mapping[str, Any]) -> ProcessLogFootprint:
    """Measure nested source values and the retained padded float64 cube."""

    decoded = _decode(fields)
    source_elements = sum(int(wafer.size) for wafer in decoded.wafers)
    output_elements = len(decoded.wafers) * decoded.max_time_points * decoded.n_features
    feature_axis_elements = int(decoded.feature_values.size) if decoded.feature_values is not None else 0
    numeric_elements = source_elements + output_elements + feature_axis_elements
    text_values = (
        *decoded.calibration_names,
        *decoded.test_names,
        *decoded.fault_names,
        *(decoded.feature_labels or ()),
        *(decoded.feature_units or ()),
        *decoded.information,
    )
    return ProcessLogFootprint(
        elements=numeric_elements,
        decoded_bytes=numeric_elements * np.dtype(np.float64).itemsize,
        metadata_bytes=sum(len(value.encode("utf-8")) for value in text_values),
        blocks=len(decoded.wafers) + len(text_values) + (1 if decoded.feature_values is not None else 0),
    )


def map_process_log(
    *,
    name: str,
    fields: Mapping[str, Any],
    storage_version: str,
    source: BoundedSource,
    parser_version: str,
) -> SherpaDataset:
    """Decode one source struct without hiding its time dimension."""

    decoded = _decode(fields)
    wafers = decoded.wafers
    counts = [int(wafer.shape[0]) for wafer in wafers]
    cube = np.full(
        (len(wafers), decoded.max_time_points, decoded.n_features),
        np.nan,
        dtype=np.float64,
    )
    for index, wafer in enumerate(wafers):
        cube[index, : wafer.shape[0], :] = wafer

    labels = list(decoded.calibration_names + decoded.test_names)
    partitions = ["calibration"] * len(decoded.calibration) + ["test"] * len(decoded.test)
    faults = ["normal"] * len(decoded.calibration) + list(decoded.fault_names)
    if decoded.feature_values is not None:
        feature_axis = SpectralAxis(values=decoded.feature_values, title="Wavelength", units=None)
        data_role = "X_spectra"
        feature_role = "spectral_feature"
    else:
        feature_axis = FeatureAxis(labels=list(decoded.feature_labels or ()), title="Variable")
        data_role = "X_features"
        feature_role = "feature"

    provenance = Provenance.from_list(
        [
            {
                "op_id": "import.matlab_process_log",
                "op_version": "1.0",
                "parameters": {
                    "schema_version": PROCESS_LOG_SCHEMA,
                    "parser_version": parser_version,
                    "source_sha256": source.member().sha256,
                    "source_size_bytes": source.size_bytes,
                    "storage_version": storage_version,
                    "variable": name,
                },
                "timestamp": "",
                "input_shape": list(cube.shape),
                "output_shape": list(cube.shape),
                "state_effects": ["time_resolved_process_log_admitted"],
            }
        ]
    )
    return SherpaDataset(
        X=cube,
        feature_axis=feature_axis,
        sample_axis=SampleAxis(
            labels=labels,
            title="Wafer",
            sample_table={
                "sample_id": labels,
                "source_partition": partitions,
                "fault_name": faults,
                "time_point_count": counts,
            },
        ),
        axes={1: TimeAxis(values=np.arange(decoded.max_time_points, dtype=np.float64), title="Process time point")},
        domain=DomainContext(),
        descriptive=DatasetDescriptiveContext(
            description=" ".join(value for value in decoded.information if value) or None
        ),
        source_identity=DatasetSourceIdentity(
            source_format="matlab-process-log",
            storage_version=storage_version,
            object_name=name,
            source_variable=name,
        ),
        layout=DatasetLayoutContext(
            kind="batch",
            source_type="matlab-process-log",
            source_dtype=cube.dtype.str,
            source_shape=tuple(cube.shape),
            mode_roles=("sample", "time_point", feature_role),
        ),
        provenance=provenance,
        title=f"{source.path.stem}:{name}",
        extra={
            "source_file": source.path.name,
            "source_type": "mat",
            "matlab.variable": name,
            "process_log.schema_version": PROCESS_LOG_SCHEMA,
            **({"process_log.feature_units": list(decoded.feature_units)} if decoded.feature_units is not None else {}),
        },
        is_time_series=True,
        data_role=data_role,
    )


__all__ = [
    "PROCESS_LOG_SCHEMA",
    "ProcessLogFootprint",
    "is_process_log_field_set",
    "map_process_log",
    "process_log_footprint",
]
