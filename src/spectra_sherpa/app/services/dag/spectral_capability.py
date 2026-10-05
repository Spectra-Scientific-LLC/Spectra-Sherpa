"""Bounded, local-only spectral-data capability for canonical DAG execution.

This is deliberately not a general serializer.  It carries only the typed
arrays and scientific context that an admitted DAG node may need, rejects
pickle/object payloads and location-bearing metadata, and exposes a
non-disclosing evidence summary instead of raw sample values.

The capability is the canonical *local* transport boundary.  It does not
authorize an egress channel; callers that need evidence must use
``evidence_summary()`` rather than its array-bearing wire form.
"""

from __future__ import annotations

import base64
import hashlib
import json
import math
import re
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Mapping

import numpy as np

from spectra_sherpa.app.lib.axes import (
    AxisInfo,
    FeatureAxis,
    FrequencyAxis,
    MZAxis,
    PotentialAxis,
    SampleAxis,
    SpatialAxis,
    SpectralAxis,
    TimeAxis,
)
from spectra_sherpa.app.lib.registered_reference_collection_identity import (
    validate_registered_reference_collection_identity,
    validate_registered_reference_source_identity,
)
from spectra_sherpa.app.lib.scientific_values import JSON_SAFE_INTEGER_MAX
from spectra_sherpa.app.lib.sherpa_dataset import (
    DatasetDescriptiveContext,
    DatasetLayoutContext,
    DatasetSourceHistory,
    DatasetSourceIdentity,
    DomainContext,
    Provenance,
    SherpaDataset,
    TargetContext,
)
from spectra_sherpa.app.services.dag.supervision_binding import validate_bound_sample_table_supervision
from spectra_sherpa.execution_contract_vocabulary import is_portable_identifier

SPECTRAL_CAPABILITY_SCHEMA_VERSION = "spectra-spectral-capability/2"
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_LOCATION_RE = re.compile(r"(?:^|\s)(?:/|~[\\/]|[A-Za-z]:[\\/])|file:", re.IGNORECASE)
_AXIS_TYPES: Mapping[str, type[AxisInfo]] = {
    "AxisInfo": AxisInfo,
    "FeatureAxis": FeatureAxis,
    "SpectralAxis": SpectralAxis,
    "TimeAxis": TimeAxis,
    "MZAxis": MZAxis,
    "PotentialAxis": PotentialAxis,
    "FrequencyAxis": FrequencyAxis,
    "SpatialAxis": SpatialAxis,
    "SampleAxis": SampleAxis,
}
_AXIS_ARRAY_FIELDS = frozenset({"values", "include_mask", "selection_scores", "classes"})
_PRIMARY_ARRAY_NAMES = frozenset({"X", "target", "groups", "sample_mask", "feature_mask"})
_AXIS_KEY_RE = re.compile(r"^(?:sample|feature|inner\.(?:0|[1-9][0-9]*))$")
_AXIS_ARRAY_KEY_RE = re.compile(
    r"^axis\.(?:sample|feature|inner\.(?:0|[1-9][0-9]*))\."
    r"(?:values|include_mask|selection_scores|classes|alternate_scales\.(?:0|[1-9][0-9]*)\.values)$"
)
_BASE_AXIS_FIELDS = frozenset(
    {
        "values",
        "labels",
        "units",
        "display_units",
        "quantity",
        "title",
        "include_mask",
        "primary_scale_name",
        "alternate_scales",
        "primary_label_name",
        "alternate_label_sets",
        "primary_title_name",
        "alternate_title_sets",
        "class_sets",
        "primary_class_set_name",
    }
)
_FEATURE_AXIS_FIELDS = _BASE_AXIS_FIELDS | frozenset({"include_mask", "selection_scores", "selection_method"})
_SAMPLE_AXIS_FIELDS = _BASE_AXIS_FIELDS | frozenset({"classes", "include_mask", "exclusion_reasons"})
_DATASET_METADATA_FIELDS = frozenset(
    {
        "title",
        "units",
        "descriptive",
        "source_identity",
        "source_history",
        "layout",
        "dso_userdata",
        "collection_member_science",
        "scientific_digest",
        "execution_scientific_projection",
        "execution_scientific_digest",
    }
)


class SpectralCapabilityError(ValueError):
    """A capability is malformed, too large, or unsafe for local execution."""


@dataclass(frozen=True)
class SpectralCapabilityBounds:
    """Hard local limits before a dataset enters isolated execution."""

    max_samples: int = 100_000
    max_features: int = 100_000
    max_dimensions: int = 4
    max_cells: int = 20_000_000
    max_array_bytes: int = 512 * 1024 * 1024
    max_metadata_bytes: int = 256 * 1024
    max_sample_identity_bytes: int = 8 * 1024 * 1024
    max_spatial_mask_entries: int = 1_000_000
    max_spatial_mask_bytes: int = 8 * 1024 * 1024
    max_metadata_depth: int = 12
    max_string_bytes: int = 4096
    max_provenance_entries: int = 256


DEFAULT_SPECTRAL_CAPABILITY_BOUNDS = SpectralCapabilityBounds()


def _plain_json(value: Any) -> Any:
    """Turn immutable internal metadata back into ordinary JSON values."""

    if isinstance(value, Mapping):
        return {str(key): _plain_json(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_plain_json(item) for item in value]
    return value


def _freeze_json(value: Any) -> Any:
    """Recursively freeze admitted metadata so callers cannot alter its digest."""

    if isinstance(value, Mapping):
        return MappingProxyType({str(key): _freeze_json(item) for key, item in value.items()})
    if isinstance(value, list):
        return tuple(_freeze_json(item) for item in value)
    return value


def _canonical_json(value: Any) -> bytes:
    return json.dumps(
        _plain_json(value), sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False
    ).encode("utf-8")


def _digest_bytes(parts: list[bytes]) -> str:
    digest = hashlib.sha256()
    for part in parts:
        digest.update(len(part).to_bytes(8, "big"))
        digest.update(part)
    return digest.hexdigest()


def _safe_json(value: Any, *, bounds: SpectralCapabilityBounds, depth: int = 0) -> Any:
    """Normalize bounded JSON and reject values that could disclose a location."""

    if depth > bounds.max_metadata_depth:
        raise SpectralCapabilityError("capability metadata exceeds the maximum nesting depth")
    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, int) and not isinstance(value, bool):
        if abs(value) > JSON_SAFE_INTEGER_MAX:
            raise SpectralCapabilityError("capability metadata integer exceeds the lossless JSON range")
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise SpectralCapabilityError("capability metadata may not contain non-finite numbers")
        return value
    if isinstance(value, str):
        if len(value.encode("utf-8")) > bounds.max_string_bytes:
            raise SpectralCapabilityError("capability metadata string exceeds the maximum size")
        if _LOCATION_RE.search(value) or "\\" in value:
            raise SpectralCapabilityError("capability metadata may not contain filesystem locations")
        return value
    if isinstance(value, np.generic):
        return _safe_json(value.item(), bounds=bounds, depth=depth)
    if isinstance(value, (list, tuple)):
        return [_safe_json(item, bounds=bounds, depth=depth + 1) for item in value]
    if isinstance(value, Mapping):
        normalized: dict[str, Any] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise SpectralCapabilityError("capability metadata keys must be strings")
            _safe_json(key, bounds=bounds, depth=depth + 1)
            normalized[key] = _safe_json(item, bounds=bounds, depth=depth + 1)
        return normalized
    raise SpectralCapabilityError(f"capability metadata does not admit {type(value).__name__}")


def _normalize_array(name: str, value: Any, *, bounds: SpectralCapabilityBounds, role: str) -> np.ndarray:
    array = np.asarray(value)
    if array.dtype.kind == "O" or array.dtype.fields:
        raise SpectralCapabilityError(f"{name} may not use object or structured dtype")
    if array.ndim == 0 or array.ndim > bounds.max_dimensions:
        raise SpectralCapabilityError(f"{name} has unsupported dimensionality")
    if array.size == 0:
        raise SpectralCapabilityError(f"{name} may not be empty")
    if array.size > bounds.max_cells or array.nbytes > bounds.max_array_bytes:
        raise SpectralCapabilityError(f"{name} exceeds capability bounds")
    if array.dtype.kind in "fc" and not np.isfinite(array).all():
        raise SpectralCapabilityError(f"{name} may not contain non-finite values")
    if role == "matrix":
        if array.dtype.kind not in "fiu":
            raise SpectralCapabilityError(f"{name} must be numeric")
        array = np.array(array, dtype="<f8", order="C", copy=True)
    elif role == "mask":
        if array.dtype.kind != "b":
            raise SpectralCapabilityError(f"{name} must be boolean")
        array = np.array(array, dtype=np.bool_, order="C", copy=True)
    elif array.dtype.kind in "iu":
        array = np.array(array, dtype="<i8", order="C", copy=True)
    elif array.dtype.kind == "b":
        array = np.array(array, dtype=np.bool_, order="C", copy=True)
    elif array.dtype.kind == "f":
        array = np.array(array, dtype="<f8", order="C", copy=True)
    elif array.dtype.kind in "US":
        # Canonical unicode avoids platform-width ambiguity.  String values
        # remain bounded and are allowed only for local target/group context.
        array = np.array(array, dtype="<U", order="C", copy=True)
        for item in array.ravel():
            _safe_json(str(item), bounds=bounds)
    else:
        raise SpectralCapabilityError(f"{name} uses an unsupported dtype")
    array.setflags(write=False)
    return array


def _array_digest(name: str, array: np.ndarray) -> bytes:
    header = _canonical_json({"name": name, "dtype": array.dtype.str, "shape": list(array.shape)})
    if array.dtype.kind == "U":
        payload = _canonical_json({"values": array.tolist()})
    else:
        payload = array.tobytes(order="C")
    return header + payload


def _array_wire(array: np.ndarray) -> Mapping[str, Any]:
    if array.dtype.kind == "U":
        return {"dtype": array.dtype.str, "shape": list(array.shape), "values": array.tolist()}
    return {
        "dtype": array.dtype.str,
        "shape": list(array.shape),
        "base64": base64.b64encode(array.tobytes(order="C")).decode("ascii"),
    }


def _array_from_wire(name: str, value: Any, *, bounds: SpectralCapabilityBounds, role: str) -> np.ndarray:
    if not isinstance(value, Mapping) or set(value) - {"dtype", "shape", "base64", "values"}:
        raise SpectralCapabilityError(f"{name} wire payload is malformed")
    dtype = value.get("dtype")
    shape = value.get("shape")
    valid_shape = isinstance(shape, list) and all(isinstance(item, int) and item > 0 for item in shape)
    if not isinstance(dtype, str) or not valid_shape:
        raise SpectralCapabilityError(f"{name} wire dtype or shape is malformed")
    try:
        parsed_dtype = np.dtype(dtype)
    except TypeError as exc:
        raise SpectralCapabilityError(f"{name} wire dtype is unsupported") from exc
    if parsed_dtype.kind == "O" or parsed_dtype.fields or parsed_dtype.kind not in "biufUS":
        raise SpectralCapabilityError(f"{name} wire dtype is unsupported")
    if len(shape) > bounds.max_dimensions:
        raise SpectralCapabilityError(f"{name} wire dimensionality exceeds capability bounds")
    cells = math.prod(shape)
    expected_bytes = cells * parsed_dtype.itemsize
    if cells > bounds.max_cells or expected_bytes > bounds.max_array_bytes:
        raise SpectralCapabilityError(f"{name} wire array exceeds capability bounds")
    if "values" in value:
        if "base64" in value:
            raise SpectralCapabilityError(f"{name} wire payload is ambiguous")
        if not isinstance(value["values"], list):
            raise SpectralCapabilityError(f"{name} wire values are malformed")
        raw = np.asarray(value["values"], dtype=parsed_dtype).reshape(tuple(shape))
    else:
        encoded = value.get("base64")
        if not isinstance(encoded, str):
            raise SpectralCapabilityError(f"{name} wire payload is missing bytes")
        max_base64_bytes = 4 * ((expected_bytes + 2) // 3)
        if len(encoded) > max_base64_bytes:
            raise SpectralCapabilityError(f"{name} wire bytes exceed capability bounds")
        try:
            raw_bytes = base64.b64decode(encoded, validate=True)
            if len(raw_bytes) != expected_bytes:
                raise ValueError("wire byte count differs from declared array shape")
            raw = np.frombuffer(raw_bytes, dtype=parsed_dtype).reshape(tuple(shape))
        except (ValueError, TypeError) as exc:
            raise SpectralCapabilityError(f"{name} wire bytes are malformed") from exc
    return _normalize_array(name, raw, bounds=bounds, role=role)


def _axis_metadata(
    axis: AxisInfo,
    name: str,
    arrays: dict[str, np.ndarray],
    *,
    bounds: SpectralCapabilityBounds,
    admit_bound_sample_table: bool = False,
) -> Mapping[str, Any]:
    _preflight_axis_metadata(
        axis,
        bounds=bounds,
        admit_bound_sample_table=admit_bound_sample_table,
    )
    # A supervision-bound sample table has already been admitted against the
    # dataset reference and is deliberately absent from this local execution
    # envelope. Exclude it before Pydantic constructs a second full table.
    excluded = {"sample_table"} if isinstance(axis, SampleAxis) and admit_bound_sample_table else None
    raw = axis.model_dump(mode="python", exclude=excluded)
    metadata: dict[str, Any] = {"axis_type": axis.__class__.__name__}
    for field, value in raw.items():
        if field in _AXIS_ARRAY_FIELDS and value is not None:
            array_name = f"axis.{name}.{field}"
            role = "mask" if field == "include_mask" else "context"
            arrays[array_name] = _normalize_array(array_name, value, bounds=bounds, role=role)
            metadata[field] = {"array": array_name}
        elif field == "alternate_scales":
            scales = []
            for index, item in enumerate(value):
                array_name = f"axis.{name}.alternate_scales.{index}.values"
                arrays[array_name] = _normalize_array(
                    array_name,
                    item["values"],
                    bounds=bounds,
                    role="context",
                )
                scales.append({**item, "values": {"array": array_name}})
            metadata[field] = scales
        elif value is not None:
            metadata[field] = value
    return _safe_json(metadata, bounds=bounds)


def _preflight_axis_metadata(
    axis: AxisInfo,
    *,
    bounds: SpectralCapabilityBounds,
    admit_bound_sample_table: bool,
) -> None:
    """Refuse obviously over-budget JSON metadata before materializing it."""

    if isinstance(axis, SampleAxis) and axis.sample_table and not admit_bound_sample_table:
        raise SpectralCapabilityError("sample_table is not admitted by the spectral capability")

    scalar_count = 0
    text_bytes = 0

    def charge(value: object) -> None:
        nonlocal scalar_count, text_bytes
        scalar_count += 1
        if isinstance(value, str):
            text_bytes += len(value.encode("utf-8"))

    for value in (
        axis.units,
        axis.title,
        axis.primary_scale_name,
        axis.primary_label_name,
        axis.primary_title_name,
        axis.primary_class_set_name,
    ):
        if value is not None:
            charge(value)
    identity_bytes = 0
    for value in axis.labels or ():
        if isinstance(axis, SampleAxis):
            identity_bytes += len(str(value).encode("utf-8")) + 3
        else:
            charge(value)
    for scale in axis.alternate_scales:
        for value in (scale.name, scale.title, scale.units, scale.axis_type):
            if value is not None:
                charge(value)
    for label_set in axis.alternate_label_sets:
        charge(label_set.name)
        for value in label_set.values:
            charge(value)
    for title_set in axis.alternate_title_sets:
        charge(title_set.name)
        charge(title_set.title)
    for class_set in axis.class_sets:
        charge(class_set.name)
        for value in class_set.values:
            charge(value)
        for level in class_set.levels:
            charge(level.code)
            charge(level.label)
    if isinstance(axis, SampleAxis):
        for value in axis.exclusion_reasons or ():
            charge(value)

    # Every JSON scalar costs at least one payload byte and, except for the
    # final item, one separator. String bytes are additional to that minimum.
    minimum_json_bytes = max(0, scalar_count * 2 - 1) + text_bytes
    if minimum_json_bytes > bounds.max_metadata_bytes:
        raise SpectralCapabilityError("axis metadata exceeds the capability metadata budget")
    if identity_bytes > bounds.max_sample_identity_bytes:
        raise SpectralCapabilityError("sample identity exceeds the capability identity budget")


def _axis_from_metadata(metadata: Mapping[str, Any], arrays: Mapping[str, np.ndarray]) -> AxisInfo:
    axis_type = metadata.get("axis_type")
    if not isinstance(axis_type, str) or axis_type not in _AXIS_TYPES:
        raise SpectralCapabilityError("capability names an unsupported axis type")
    values: dict[str, Any] = {}
    for key, value in metadata.items():
        if key == "axis_type":
            continue
        if isinstance(value, Mapping) and set(value) == {"array"}:
            array_name = value["array"]
            if not isinstance(array_name, str) or array_name not in arrays:
                raise SpectralCapabilityError("axis metadata references a missing array")
            values[key] = arrays[array_name].copy()
        elif key == "alternate_scales":
            decoded_scales = []
            for item in value:
                if not isinstance(item, Mapping):
                    raise SpectralCapabilityError("axis alternate scale metadata is malformed")
                reference = item.get("values")
                if not isinstance(reference, Mapping) or set(reference) != {"array"}:
                    raise SpectralCapabilityError("axis alternate scale array reference is malformed")
                array_name = reference["array"]
                if not isinstance(array_name, str) or array_name not in arrays:
                    raise SpectralCapabilityError("axis alternate scale references a missing array")
                decoded_scales.append({**item, "values": arrays[array_name].copy()})
            values[key] = decoded_scales
        else:
            values[key] = value
    return _AXIS_TYPES[axis_type](**values)


def _validate_array_roles(value: object) -> None:
    if not isinstance(value, Mapping) or "X" not in value or set(value.values()) - {"matrix", "context", "mask"}:
        raise SpectralCapabilityError("capability array_roles must be closed and include X")
    for name, role in value.items():
        if not isinstance(name, str) or not isinstance(role, str):
            raise SpectralCapabilityError("capability array_roles must contain string names and roles")
        if name not in _PRIMARY_ARRAY_NAMES and not _AXIS_ARRAY_KEY_RE.fullmatch(name):
            raise SpectralCapabilityError("capability array name is not admitted by the closed schema")
        if name == "X" and role != "matrix":
            raise SpectralCapabilityError("X must use the matrix capability role")
        if name in {"sample_mask", "feature_mask"} or name.endswith(".include_mask"):
            if role != "mask":
                raise SpectralCapabilityError("mask arrays must use the mask capability role")
        elif name != "X" and role != "context":
            raise SpectralCapabilityError("context arrays must use the context capability role")


def _validate_axis_metadata(value: object) -> None:
    if not isinstance(value, Mapping):
        raise SpectralCapabilityError("capability axes are malformed")
    for axis_name, axis_metadata in value.items():
        if not isinstance(axis_name, str) or not _AXIS_KEY_RE.fullmatch(axis_name):
            raise SpectralCapabilityError("capability axis name is not admitted by the closed schema")
        if not isinstance(axis_metadata, Mapping):
            raise SpectralCapabilityError("capability axis metadata is malformed")
        axis_type = axis_metadata.get("axis_type")
        if axis_type not in _AXIS_TYPES:
            raise SpectralCapabilityError("capability names an unsupported axis type")
        allowed_fields = _SAMPLE_AXIS_FIELDS if axis_type == "SampleAxis" else _FEATURE_AXIS_FIELDS
        if axis_type == "AxisInfo":
            allowed_fields = _BASE_AXIS_FIELDS
        if set(axis_metadata) - ({"axis_type"} | allowed_fields):
            raise SpectralCapabilityError("capability axis metadata must use the closed schema")
        for field in _AXIS_ARRAY_FIELDS & set(axis_metadata):
            reference = axis_metadata[field]
            expected = f"axis.{axis_name}.{field}"
            if not isinstance(reference, Mapping) or set(reference) != {"array"} or reference["array"] != expected:
                raise SpectralCapabilityError("capability axis array reference is not admitted by the closed schema")
        alternate_scales = axis_metadata.get("alternate_scales", [])
        if not isinstance(alternate_scales, list):
            raise SpectralCapabilityError("capability alternate axis scales are malformed")
        for index, item in enumerate(alternate_scales):
            expected = f"axis.{axis_name}.alternate_scales.{index}.values"
            if not isinstance(item, Mapping):
                raise SpectralCapabilityError("capability alternate axis scale is malformed")
            reference = item.get("values")
            if not isinstance(reference, Mapping) or set(reference) != {"array"} or reference["array"] != expected:
                raise SpectralCapabilityError("capability alternate axis scale array reference is malformed")


def _validate_scientific_metadata(metadata: Mapping[str, Any]) -> None:
    if not isinstance(metadata["domain"], Mapping) or not isinstance(metadata["target_context"], Mapping):
        raise SpectralCapabilityError("capability domain and target_context must be objects")
    if not isinstance(metadata["descriptive"], Mapping):
        raise SpectralCapabilityError("capability descriptive context must be an object")
    if (
        not isinstance(metadata["source_identity"], Mapping)
        or not isinstance(metadata["source_history"], Mapping)
        or not isinstance(metadata["layout"], Mapping)
    ):
        raise SpectralCapabilityError("capability source identity, history, and layout must be objects")
    execution_projection = metadata["execution_scientific_projection"]
    if not isinstance(execution_projection, Mapping):
        raise SpectralCapabilityError("capability execution scientific projection must be an object")
    for field in ("scientific_digest", "execution_scientific_digest"):
        digest = metadata[field]
        if not isinstance(digest, str) or not _SHA256_RE.fullmatch(digest):
            raise SpectralCapabilityError(f"capability {field} must be a SHA-256 digest")
    if hashlib.sha256(_canonical_json(execution_projection)).hexdigest() != metadata["execution_scientific_digest"]:
        raise SpectralCapabilityError("capability execution scientific projection digest does not match")
    member_science = metadata["collection_member_science"]
    if member_science is not None:
        if not isinstance(member_science, Mapping) or set(member_science) != {"nodes", "text_bytes", "sha256"}:
            raise SpectralCapabilityError("capability collection member scientific projection is malformed")
        nodes = member_science["nodes"]
        text_bytes = member_science["text_bytes"]
        digest = member_science["sha256"]
        if (
            type(nodes) is not int
            or nodes < 1
            or nodes > 1_000_000
            or type(text_bytes) is not int
            or text_bytes < 0
            or text_bytes > 4 * 1024 * 1024
            or not isinstance(digest, str)
            or not _SHA256_RE.fullmatch(digest)
        ):
            raise SpectralCapabilityError("capability collection member scientific projection is malformed")


def _spatial_mask_budget(metadata: Mapping[str, Any], bounds: SpectralCapabilityBounds) -> int:
    """Charge only an exact, spatially aligned image mask to its own budget."""

    layout = metadata["layout"]
    mask = layout.get("image_include")
    if mask is None:
        return 0
    image_size = layout.get("image_size")
    if (
        layout.get("kind") != "image"
        or not isinstance(image_size, list)
        or not image_size
        or any(type(length) is not int or length < 1 for length in image_size)
        or not isinstance(mask, list)
        or any(type(item) is not bool for item in mask)
        or len(mask) != math.prod(image_size)
    ):
        raise SpectralCapabilityError("capability image include mask is not aligned to its spatial shape")
    if len(mask) > bounds.max_spatial_mask_entries:
        raise SpectralCapabilityError("capability image include mask exceeds its entry budget")
    projection_layout = metadata["execution_scientific_projection"].get("layout")
    if not isinstance(projection_layout, Mapping) or projection_layout != layout:
        raise SpectralCapabilityError("capability image layout differs from its scientific projection")
    mask_bytes = len(_canonical_json(mask))
    if mask_bytes > bounds.max_spatial_mask_bytes:
        raise SpectralCapabilityError("capability image include mask exceeds its dedicated budget")
    # The same validated mask occurs once in layout and once in the exact
    # scientific projection. Both copies are protected by the projection
    # digest and the envelope digest; all other metadata retains its limit.
    return 2 * mask_bytes


class SpectralDatasetCapability:
    """Validated immutable local execution input with non-disclosing evidence."""

    def __init__(
        self,
        *,
        arrays: Mapping[str, Any],
        metadata: Mapping[str, Any],
        bounds: SpectralCapabilityBounds = DEFAULT_SPECTRAL_CAPABILITY_BOUNDS,
    ) -> None:
        if not isinstance(arrays, Mapping) or not isinstance(metadata, Mapping):
            raise SpectralCapabilityError("capability requires arrays and metadata objects")
        self._assert_metadata_keys(metadata)
        if set(arrays) - set(metadata.get("array_roles", {})):
            raise SpectralCapabilityError("every capability array requires a declared role")
        normalized_metadata = _safe_json(metadata, bounds=bounds)
        self._validate_metadata(normalized_metadata, bounds=bounds)
        roles = normalized_metadata["array_roles"]
        normalized_arrays = {
            name: _normalize_array(name, value, bounds=bounds, role=roles[name]) for name, value in arrays.items()
        }
        self._validate_arrays(normalized_arrays, normalized_metadata, bounds=bounds)
        self._arrays = MappingProxyType(normalized_arrays)
        self._metadata = _freeze_json(normalized_metadata)
        self._content_digest = self._digest(include_custody=False)
        self._envelope_digest = self._digest(include_custody=True)

    @staticmethod
    def _assert_metadata_keys(metadata: Mapping[str, Any]) -> None:
        """Reject schema drift before inspecting untrusted metadata values."""

        required = {
            "schema_version",
            "dataset_role",
            "custody_id",
            "dataset_ref_digest",
            "split_plan_digest",
            "array_roles",
            "domain",
            "target_context",
            "provenance",
            "axes",
            "is_time_series",
            *_DATASET_METADATA_FIELDS,
        }
        unknown, missing = set(metadata) - required, required - set(metadata)
        if unknown or missing:
            raise SpectralCapabilityError("capability metadata must use the closed schema")

    @staticmethod
    def _validate_metadata(metadata: Mapping[str, Any], *, bounds: SpectralCapabilityBounds) -> None:
        if metadata["schema_version"] != SPECTRAL_CAPABILITY_SCHEMA_VERSION:
            raise SpectralCapabilityError("unsupported spectral capability schema version")
        for field in ("dataset_role", "custody_id"):
            if not is_portable_identifier(metadata[field]):
                raise SpectralCapabilityError(f"{field} must be a portable identifier")
        split = metadata["split_plan_digest"]
        if split is not None and (not isinstance(split, str) or not _SHA256_RE.fullmatch(split)):
            raise SpectralCapabilityError("split_plan_digest must be a SHA-256 digest or null")
        dataset_ref = metadata["dataset_ref_digest"]
        if dataset_ref is not None and (not isinstance(dataset_ref, str) or not _SHA256_RE.fullmatch(dataset_ref)):
            raise SpectralCapabilityError("dataset_ref_digest must be a SHA-256 digest or null")
        _validate_array_roles(metadata["array_roles"])
        _validate_scientific_metadata(metadata)
        if not isinstance(metadata["provenance"], list) or len(metadata["provenance"]) > bounds.max_provenance_entries:
            raise SpectralCapabilityError("capability provenance exceeds the bounded list contract")
        if not isinstance(metadata["is_time_series"], bool):
            raise SpectralCapabilityError("capability time-series marker is malformed")
        _validate_axis_metadata(metadata["axes"])
        sample_labels = metadata.get("axes", {}).get("sample", {}).get("labels") or []
        identity_bytes = len(_canonical_json(sample_labels))
        if identity_bytes > bounds.max_sample_identity_bytes:
            raise SpectralCapabilityError("sample identity exceeds the capability identity budget")
        # The closed envelope repeats sample identity in its axis and exact
        # scientific projection/digest inputs. Charge those bounded copies to
        # the dedicated identity budget, not the unrelated metadata budget.
        spatial_mask_bytes = _spatial_mask_budget(metadata, bounds)
        if len(_canonical_json(metadata)) > bounds.max_metadata_bytes + 4 * identity_bytes + spatial_mask_bytes:
            raise SpectralCapabilityError("capability metadata exceeds the maximum size")

    @staticmethod
    def _validate_arrays(
        arrays: Mapping[str, np.ndarray],
        metadata: Mapping[str, Any],
        *,
        bounds: SpectralCapabilityBounds,
    ) -> None:
        x = arrays.get("X")
        if x is None or x.ndim < 2:
            raise SpectralCapabilityError("X must be a samples-by-features matrix")
        if x.shape[0] > bounds.max_samples or x.shape[-1] > bounds.max_features:
            raise SpectralCapabilityError("X exceeds sample or feature bounds")
        layout = metadata["layout"]
        if layout.get("image_include") is not None:
            image_size = tuple(layout["image_size"])
            source_shape = layout.get("source_shape")
            if (
                (source_shape is not None and tuple(source_shape) != x.shape)
                or (x.ndim == 2 and math.prod(image_size) != x.shape[0])
                or (
                    x.ndim > 2
                    and (len(image_size) > x.ndim - 1 or tuple(x.shape[-len(image_size) - 1 : -1]) != image_size)
                )
            ):
                raise SpectralCapabilityError("capability image include mask does not align to X spatial dimensions")
        roles = metadata["array_roles"]
        if set(arrays) != set(roles):
            raise SpectralCapabilityError("capability arrays and roles must have identical keys")
        for name in ("target", "groups", "sample_mask"):
            if name in arrays and arrays[name].shape[0] != x.shape[0]:
                raise SpectralCapabilityError(f"{name} must align to X samples")
        if "feature_mask" in arrays and arrays["feature_mask"].shape != (x.shape[-1],):
            raise SpectralCapabilityError("feature_mask must align to X features")
        for name, array in arrays.items():
            if not name.startswith("axis."):
                continue
            if name.startswith("axis.sample."):
                expected = x.shape[0]
            elif name.startswith("axis.feature."):
                expected = x.shape[-1]
            else:
                match = re.match(r"^axis\.inner\.(\d+)\.", name)
                if match is None:
                    raise SpectralCapabilityError("axis array name is malformed")
                dimension = int(match.group(1))
                if dimension <= 0 or dimension >= x.ndim - 1:
                    raise SpectralCapabilityError("axis array dimension is outside X")
                expected = x.shape[dimension]
            if array.shape != (expected,):
                raise SpectralCapabilityError("axis array does not align to its X dimension")

    @classmethod
    def from_dataset(
        cls,
        dataset: SherpaDataset,
        *,
        custody_id: str,
        dataset_ref_digest: str | None = None,
        split_plan_digest: str | None = None,
        groups: Any | None = None,
        bounds: SpectralCapabilityBounds = DEFAULT_SPECTRAL_CAPABILITY_BOUNDS,
    ) -> "SpectralDatasetCapability":
        """Capture a SherpaDataset without inheriting arbitrary ``extra`` data."""

        arrays: dict[str, np.ndarray] = {"X": dataset.X}
        roles: dict[str, str] = {"X": "matrix"}
        if dataset.target is not None:
            arrays["target"] = dataset.target
            roles["target"] = "context"
        if groups is not None:
            arrays["groups"] = groups
            roles["groups"] = "context"
        sample_axis = dataset.sample_axis
        if sample_axis and sample_axis.include_mask is not None:
            arrays["sample_mask"] = sample_axis.include_mask
            roles["sample_mask"] = "mask"
        feature_axis = dataset.get_feature_axis()
        if feature_axis and feature_axis.include_mask is not None:
            arrays["feature_mask"] = feature_axis.include_mask
            roles["feature_mask"] = "mask"
        axes: dict[str, Any] = {}
        if sample_axis is not None:
            supervision = dataset.meta.get("supervision_binding")
            admit_bound_sample_table = False
            if sample_axis.sample_table:
                try:
                    registered_reference = isinstance(dataset.get_extra("reference.projection_id"), str)
                    if registered_reference:
                        validate_registered_reference_source_identity(
                            dataset.meta.get("source_collection"),
                            dataset,
                        )
                    if isinstance(supervision, Mapping):
                        validate_bound_sample_table_supervision(
                            dataset,
                            binding_record=supervision,
                            dataset_ref_digest=dataset_ref_digest,
                            groups=groups,
                        )
                    else:
                        if not registered_reference:
                            raise SpectralCapabilityError("sample_table is not admitted by the spectral capability")
                        validate_registered_reference_collection_identity(
                            dataset.meta.get("source_collection"),
                            dataset,
                        )
                except ValueError as exc:
                    raise SpectralCapabilityError(str(exc)) from exc
                admit_bound_sample_table = True
            axes["sample"] = _axis_metadata(
                sample_axis,
                "sample",
                arrays,
                bounds=bounds,
                admit_bound_sample_table=admit_bound_sample_table,
            )
        if feature_axis is not None:
            axes["feature"] = _axis_metadata(feature_axis, "feature", arrays, bounds=bounds)
        for dim, axis in dataset.inner_axes.items():
            axes[f"inner.{dim}"] = _axis_metadata(axis, f"inner.{dim}", arrays, bounds=bounds)
        # Axis payloads are added by the adapter after the primary dataset
        # fields above.  Their role is structural context except for explicit
        # selection masks, which must remain boolean mask arrays.
        for name in arrays:
            if name not in roles:
                roles[name] = "mask" if name.endswith(".include_mask") else "context"
        execution_projection = dataset.scientific_projection(include_sample_table=False)
        metadata = {
            "schema_version": SPECTRAL_CAPABILITY_SCHEMA_VERSION,
            "dataset_role": str(dataset.data_role),
            "custody_id": custody_id,
            "dataset_ref_digest": dataset_ref_digest,
            "split_plan_digest": split_plan_digest,
            "array_roles": roles,
            "domain": dataset.domain.model_dump(mode="json", exclude_none=True),
            "target_context": dataset.target_context.model_dump(mode="json", exclude_none=True),
            "provenance": dataset.provenance.to_list(),
            "axes": axes,
            "is_time_series": dataset.is_time_series,
            "title": dataset.title,
            "units": dataset.units,
            "descriptive": dataset.descriptive.model_dump(mode="json", exclude_none=True),
            "source_identity": dataset.source_identity.model_dump(mode="json", exclude_none=True),
            "source_history": dataset.source_history.model_dump(mode="json", exclude_none=True),
            "layout": dataset.layout.model_dump(mode="json", exclude_none=True),
            "dso_userdata": dataset.extra.get("dso.userdata"),
            "collection_member_science": execution_projection["collection_member_science"],
            "scientific_digest": dataset.scientific_digest,
            # Bound sample tables are admitted before issue but deliberately
            # omitted from this local execution envelope. Keep the full source
            # digest above and separately bind the exact rehydratable science.
            "execution_scientific_projection": execution_projection,
            "execution_scientific_digest": hashlib.sha256(_canonical_json(execution_projection)).hexdigest(),
        }
        return cls(arrays=arrays, metadata=metadata, bounds=bounds)

    @property
    def arrays(self) -> Mapping[str, np.ndarray]:
        return self._arrays

    @property
    def metadata(self) -> Mapping[str, Any]:
        return self._metadata

    @property
    def content_digest(self) -> str:
        """Digest of scientific content; excludes custody/split enrollment."""

        return self._content_digest

    @property
    def envelope_digest(self) -> str:
        """Digest of complete local admission identity, including custody/split."""

        return self._envelope_digest

    def _digest(self, *, include_custody: bool) -> str:
        metadata = _plain_json(self._metadata)
        if not include_custody:
            metadata.pop("custody_id")
            metadata.pop("dataset_ref_digest")
            metadata.pop("split_plan_digest")
        parts = [_canonical_json(metadata)]
        parts.extend(_array_digest(name, array) for name, array in sorted(self._arrays.items()))
        return _digest_bytes(parts)

    def to_wire(self) -> Mapping[str, Any]:
        """Return canonical local-transfer data; callers must not publish it."""

        return {
            "schema_version": SPECTRAL_CAPABILITY_SCHEMA_VERSION,
            "metadata": json.loads(_canonical_json(self._metadata)),
            "arrays": {name: _array_wire(array) for name, array in sorted(self._arrays.items())},
            "content_digest": self.content_digest,
            "envelope_digest": self.envelope_digest,
        }

    @classmethod
    def from_wire(
        cls,
        value: Mapping[str, Any],
        *,
        bounds: SpectralCapabilityBounds = DEFAULT_SPECTRAL_CAPABILITY_BOUNDS,
    ) -> "SpectralDatasetCapability":
        if not isinstance(value, Mapping) or set(value) != {
            "schema_version",
            "metadata",
            "arrays",
            "content_digest",
            "envelope_digest",
        }:
            raise SpectralCapabilityError("spectral capability wire payload must use the closed schema")
        if value["schema_version"] != SPECTRAL_CAPABILITY_SCHEMA_VERSION:
            raise SpectralCapabilityError("unsupported spectral capability wire version")
        metadata, wire_arrays = value["metadata"], value["arrays"]
        if not isinstance(metadata, Mapping) or not isinstance(wire_arrays, Mapping):
            raise SpectralCapabilityError("spectral capability wire payload is malformed")
        roles = metadata.get("array_roles")
        if not isinstance(roles, Mapping) or set(wire_arrays) != set(roles):
            raise SpectralCapabilityError("spectral capability wire arrays do not match roles")
        arrays = {
            name: _array_from_wire(name, array, bounds=bounds, role=roles[name]) for name, array in wire_arrays.items()
        }
        capability = cls(arrays=arrays, metadata=metadata, bounds=bounds)
        if (
            value["content_digest"] != capability.content_digest
            or value["envelope_digest"] != capability.envelope_digest
        ):
            raise SpectralCapabilityError("spectral capability digest verification failed")
        return capability

    def _rehydrate_dataset(self) -> SherpaDataset:
        """Rehydrate the SherpaDataset portion of the local execution input."""

        axes = self._metadata["axes"]
        sample = _axis_from_metadata(axes["sample"], self._arrays) if "sample" in axes else None
        feature = _axis_from_metadata(axes["feature"], self._arrays) if "feature" in axes else None
        inner = {
            int(name.split(".", 1)[1]): _axis_from_metadata(metadata, self._arrays)
            for name, metadata in axes.items()
            if name.startswith("inner.")
        }
        dataset = SherpaDataset(
            X=self._arrays["X"].copy(),
            feature_axis=feature if isinstance(feature, FeatureAxis) else None,
            sample_axis=sample if isinstance(sample, SampleAxis) else None,
            axes=inner or None,
            target=self._arrays["target"].copy() if "target" in self._arrays else None,
            target_context=TargetContext.model_validate(self._metadata["target_context"]),
            domain=DomainContext.model_validate(self._metadata["domain"]),
            descriptive=DatasetDescriptiveContext.model_validate(self._metadata["descriptive"]),
            source_identity=DatasetSourceIdentity.model_validate(self._metadata["source_identity"]),
            source_history=DatasetSourceHistory.model_validate(self._metadata["source_history"]),
            layout=DatasetLayoutContext.model_validate(self._metadata["layout"]),
            provenance=Provenance.from_list(self._metadata["provenance"]),
            title=self._metadata["title"],
            units=self._metadata["units"],
            extra={
                **(
                    {"dso.userdata": _plain_json(self._metadata["dso_userdata"])}
                    if self._metadata["dso_userdata"] is not None
                    else {}
                ),
                **(
                    {
                        "sherpa.source_member_scientific_projection": _plain_json(
                            self._metadata["collection_member_science"]
                        )
                    }
                    if self._metadata["collection_member_science"] is not None
                    else {}
                ),
            }
            or None,
            data_role=self._metadata["dataset_role"],
            is_time_series=self._metadata["is_time_series"],
        )
        execution_projection = dataset.scientific_projection(include_sample_table=False)
        expected_projection = _plain_json(self._metadata["execution_scientific_projection"])
        if execution_projection != expected_projection:
            changed_sections = sorted(
                key
                for key in set(execution_projection) | set(expected_projection)
                if execution_projection.get(key) != expected_projection.get(key)
            )
            if "axes" in changed_sections:
                actual_axes = {item["dimension"]: item["projection"] for item in execution_projection["axes"]}
                expected_axes = {item["dimension"]: item["projection"] for item in expected_projection["axes"]}
                changed_sections.extend(
                    f"axis[{dimension}].{field}"
                    for dimension in sorted(set(actual_axes) | set(expected_axes))
                    for field in sorted(set(actual_axes.get(dimension, {})) | set(expected_axes.get(dimension, {})))
                    if actual_axes.get(dimension, {}).get(field) != expected_axes.get(dimension, {}).get(field)
                )
            raise SpectralCapabilityError(
                "rehydrated dataset does not match its scientific projection sections: " + ", ".join(changed_sections)
            )
        execution_digest = hashlib.sha256(_canonical_json(execution_projection)).hexdigest()
        if execution_digest != self._metadata["execution_scientific_digest"]:
            raise SpectralCapabilityError("rehydrated dataset does not match its scientific digest")
        return dataset

    def to_dataset_and_groups(self) -> tuple[SherpaDataset, np.ndarray | None]:
        """Rehydrate data and the separately typed grouped-validation context.

        Group assignments are not a generic ``SherpaDataset`` field.  A
        grouped capability therefore requires callers to explicitly obtain
        them from this method instead of silently dropping them while crossing
        into validation or isolated execution.
        """

        groups = self._arrays["groups"].copy() if "groups" in self._arrays else None
        return self._rehydrate_dataset(), groups

    def to_dataset(self) -> SherpaDataset:
        """Rehydrate an ungrouped typed SherpaDataset inside the local boundary."""

        if "groups" in self._arrays:
            raise SpectralCapabilityError("grouped capability requires to_dataset_and_groups()")
        return self._rehydrate_dataset()

    def evidence_summary(self) -> Mapping[str, Any]:
        """Return safe evidence: identities and shapes, never raw arrays/labels."""

        return {
            "schema_version": SPECTRAL_CAPABILITY_SCHEMA_VERSION,
            "content_digest": self.content_digest,
            "envelope_digest": self.envelope_digest,
            "dataset_role": self._metadata["dataset_role"],
            "custody_id": self._metadata["custody_id"],
            "dataset_ref_digest": self._metadata["dataset_ref_digest"],
            "split_plan_digest": self._metadata["split_plan_digest"],
            "sample_identity_digest": self._identity_digest(
                ("groups", "sample_mask", "axis.sample.values", "axis.sample.classes")
            ),
            "feature_identity_digest": self._identity_digest(
                ("feature_mask", "axis.feature.values", "axis.feature.include_mask")
            ),
            "array_shapes": {name: list(array.shape) for name, array in sorted(self._arrays.items())},
            "array_dtypes": {name: array.dtype.str for name, array in sorted(self._arrays.items())},
            "axis_kinds": {name: axis["axis_type"] for name, axis in self._metadata["axes"].items()},
        }

    def local_conversion_event(self, *, direction: str) -> Mapping[str, Any]:
        """Record a bounded, non-disclosing local adapter conversion event.

        The event is evidence for a local execution record.  It deliberately
        contains neither the wire payload nor any sample-level value and is
        not an authorization to export the capability.
        """

        if direction not in {"dataset_to_capability", "capability_to_dataset"}:
            raise SpectralCapabilityError("conversion direction is not admitted by the closed capability contract")
        return {
            "event_type": "spectral_capability_conversion",
            "schema_version": SPECTRAL_CAPABILITY_SCHEMA_VERSION,
            "direction": direction,
            "content_digest": self.content_digest,
            "envelope_digest": self.envelope_digest,
            "array_count": len(self._arrays),
        }

    def _identity_digest(self, names: tuple[str, ...]) -> str | None:
        """Return a non-disclosing digest of stable sample or feature identity."""

        present = [name for name in names if name in self._arrays]
        if not present:
            return None
        return _digest_bytes([_array_digest(name, self._arrays[name]) for name in present])


__all__ = [
    "DEFAULT_SPECTRAL_CAPABILITY_BOUNDS",
    "SPECTRAL_CAPABILITY_SCHEMA_VERSION",
    "SpectralCapabilityBounds",
    "SpectralCapabilityError",
    "SpectralDatasetCapability",
]
