"""Storage-neutral Eigenvector DataSet Object admission.

This module owns the scientific mapping.  MATLAB v5 and v7.3 readers may
decode different storage representations, but both must produce the same
``DecodedDSO`` before a :class:`SherpaDataset` is constructed here.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

import numpy as np

from spectra_sherpa.app.lib.axes import (
    AxisClassLevel,
    AxisClassSet,
    AxisInfo,
    AxisLabelSet,
    AxisScaleSet,
    AxisTitleSet,
    FeatureAxis,
    SampleAxis,
    SpatialAxis,
    SpectralAxis,
)
from spectra_sherpa.app.lib.scientific_values import LosslessScalar, lossless_json_scalar, lossless_scalar_identity
from spectra_sherpa.app.lib.sherpa_dataset import (
    DatasetDescriptiveContext,
    DatasetLayoutContext,
    DatasetSourceHistory,
    DatasetSourceIdentity,
    DomainContext,
    Provenance,
    ProvenanceEntry,
    SherpaDataset,
)
from spectra_sherpa.ingestion_errors import UnreadableSpectrumError, UnsupportedFormatVariantError
from spectra_sherpa.io.base import BoundedSource
from spectra_sherpa.io.formats._helpers import derive_data_role

DSO_SIGNATURE_FIELDS = frozenset(
    {
        "name",
        "type",
        "author",
        "date",
        "moddate",
        "description",
        "axisscale",
        "axisscalename",
        "axisscaletype",
        "axistype",
        "label",
        "labelname",
        "class",
        "classname",
        "classlookup",
        "title",
        "titlename",
        "include",
        "includ",
        "history",
        "userdata",
        "uniqueid",
        "datasetversion",
        "version",
        "imagemode",
        "imagesize",
        "imagedata",
        "imageinclude",
        "imageaxisscale",
        "imageaxisscalename",
        "imageaxisscaletype",
        "imageaxistype",
    }
)
_MAX_MODES = 16
_MAX_SETS_PER_MODE = 64
_MAX_TEXT_CHARS = 65_536


@dataclass(frozen=True, slots=True)
class DecodedDSO:
    """One decoded DSO record independent of its MAT storage family."""

    variable_name: str
    fields: Mapping[str, Any]
    storage_version: str


@dataclass(frozen=True, slots=True)
class DecodedDSOFootprint:
    elements: int
    decoded_bytes: int
    metadata_bytes: int
    blocks: int


def decoded_dso_footprint(fields: Mapping[str, Any]) -> DecodedDSOFootprint:
    """Measure one already-decoded record with identity deduplication."""

    elements = 0
    decoded_bytes = 0
    metadata_bytes = 0
    blocks = 0
    seen: set[int] = set()

    def visit(value: Any) -> None:
        nonlocal elements, decoded_bytes, metadata_bytes, blocks
        if isinstance(value, (np.ndarray, Mapping, list, tuple)):
            identity = id(value)
            if identity in seen:
                return
            seen.add(identity)
        blocks += 1
        if isinstance(value, np.ndarray):
            if value.dtype.names:
                decoded_bytes += int(value.size) * 8
                for field in value.dtype.names:
                    for item in value[field].reshape(-1, order="F"):
                        visit(item)
                return
            if value.dtype == object:
                decoded_bytes += int(value.size) * 8
                for item in value.reshape(-1, order="F"):
                    visit(item)
                return
            elements += int(value.size)
            decoded_bytes += int(value.nbytes)
            if value.dtype.kind in "US":
                metadata_bytes += sum(len(str(item).encode("utf-8")) for item in value.reshape(-1, order="F"))
            return
        if isinstance(value, Mapping):
            for key, item in value.items():
                metadata_bytes += len(str(key).encode("utf-8"))
                visit(item)
            return
        if isinstance(value, (list, tuple)):
            for item in value:
                visit(item)
            return
        if isinstance(value, bytes):
            metadata_bytes += len(value)
        elif isinstance(value, str):
            metadata_bytes += len(value.encode("utf-8"))
        elif isinstance(value, (bool, int, float, np.generic)):
            elements += 1
            decoded_bytes += 8
        elif value is not None:
            raise _fail(f"decoded field contains unsupported object {type(value).__name__}")

    visit(fields)
    return DecodedDSOFootprint(elements, decoded_bytes, metadata_bytes, blocks)


def dso_float64_output_bytes(fields: Mapping[str, Any]) -> int:
    """Conservatively project the canonical float64 matrix allocation."""

    value = _unwrap(fields.get("data"))
    array = np.asarray(value)
    return int(array.size) * np.dtype(np.float64).itemsize


def is_dso_field_set(fields: Sequence[str]) -> bool:
    """Return whether a MATLAB struct makes a closed DSO scientific claim."""

    names = {str(field).lower() for field in fields}
    return "data" in names and len(names & DSO_SIGNATURE_FIELDS) >= 2


def _fail(detail: str) -> UnreadableSpectrumError:
    return UnreadableSpectrumError(format_id="matlab", detail=f"invalid Eigenvector DSO: {detail}")


def _unwrap(value: Any) -> Any:
    """Remove MATLAB singleton wrappers without squeezing scientific arrays."""

    current = value
    for _ in range(12):
        if isinstance(current, np.ndarray) and current.dtype == object and current.size == 1:
            current = current.reshape(-1, order="F")[0]
            continue
        break
    return current


def _text(value: Any, *, field: str, required: bool = False) -> str | None:
    value = _unwrap(value)
    if value is None or (isinstance(value, np.ndarray) and value.size == 0):
        if required:
            raise _fail(f"{field} is required")
        return None
    if isinstance(value, bytes):
        try:
            result = value.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise _fail(f"{field} is not UTF-8 text") from exc
    elif isinstance(value, str):
        result = value
    elif isinstance(value, np.ndarray) and value.dtype.kind in "US":
        flat = value.reshape(-1, order="F").tolist()
        result = "".join(str(item) for item in flat) if all(len(str(item)) <= 1 for item in flat) else str(flat[0])
    elif isinstance(value, np.ndarray) and value.size == 1:
        return _text(value.reshape(-1, order="F")[0], field=field, required=required)
    else:
        raise _fail(f"{field} must be text")
    result = result.strip()
    if not result and required:
        raise _fail(f"{field} is required")
    if not result:
        return None
    if len(result) > _MAX_TEXT_CHARS:
        raise _fail(f"{field} exceeds the text limit")
    return result


def _scalar(value: Any, *, field: str) -> LosslessScalar:
    value = _unwrap(value)
    if isinstance(value, np.ndarray) and value.size == 1:
        value = value.reshape(-1, order="F")[0]
    if isinstance(value, np.generic):
        value = value.item()
    try:
        return lossless_json_scalar(value, max_text_chars=4096, field_name=f"DSO {field}")
    except ValueError as exc:
        raise _fail(f"{field} contains a non-lossless scalar") from exc


def _authors(value: Any) -> tuple[str, ...]:
    """Admit either one MATLAB char vector or a bounded cell list of authors."""

    value = _unwrap(value)
    if value is None or (isinstance(value, np.ndarray) and value.size == 0):
        return ()
    if isinstance(value, (str, bytes)) or (isinstance(value, np.ndarray) and value.dtype.kind in "US"):
        author = _text(value, field="author")
        return (author,) if author is not None else ()
    array = np.asarray(value, dtype=object)
    if array.size > 256:
        raise _fail("author exceeds the entry-count limit")
    authors: list[str] = []
    for index, item in enumerate(array.reshape(-1, order="F")):
        author = _text(item, field=f"author[{index}]")
        if author is not None:
            authors.append(author)
    return tuple(authors)


def _iso_datetime(value: str | None) -> datetime | None:
    """Promote only unambiguous ISO-8601 source dates; retain every raw value."""

    if value is None:
        return None
    candidate = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        return datetime.fromisoformat(candidate)
    except ValueError:
        return None


def _date_text(value: Any, *, field: str) -> str | None:
    """Admit documented text or six-number MATLAB date vectors losslessly."""

    value = _unwrap(value)
    if value is None or (isinstance(value, np.ndarray) and value.size == 0):
        return None
    array = np.asarray(value)
    if array.dtype.kind not in "biuf" or array.size != 6:
        return _text(value, field=field)
    numbers = np.asarray(array, dtype=np.float64).reshape(-1, order="F")
    if not np.isfinite(numbers).all():
        raise _fail(f"{field} date vector contains non-finite values")
    calendar = numbers[:5]
    if not np.equal(calendar, np.floor(calendar)).all():
        raise _fail(f"{field} date vector calendar fields must be integers")
    second = float(numbers[5])
    if not 0.0 <= second < 60.0:
        raise _fail(f"{field} date vector seconds must be in [0, 60)")
    try:
        base = datetime(*(int(item) for item in calendar))
    except ValueError as exc:
        raise _fail(f"{field} date vector is not a valid calendar value") from exc
    return (base + timedelta(seconds=second)).isoformat()


def _cells(value: Any) -> np.ndarray:
    value = _unwrap(value)
    if value is None:
        return np.empty((0, 0), dtype=object)
    array = np.asarray(value, dtype=object)
    if array.size == 0:
        return np.empty((0, 0), dtype=object)
    if array.ndim == 0:
        return array.reshape(1, 1)
    if array.ndim == 1:
        return array.reshape(array.shape[0], 1)
    if array.ndim != 2:
        raise _fail("metadata cell arrays must be at most two-dimensional")
    return array


def _present(value: Any) -> bool:
    if value is None:
        return False
    try:
        return np.asarray(_unwrap(value)).size > 0
    except Exception:
        return True


def _declares_text(value: Any, *, field: str) -> bool:
    if value is None:
        return False
    try:
        return any(_text(item, field=field) is not None for item in _cells(value).reshape(-1, order="F"))
    except UnreadableSpectrumError:
        return True


def _mode_cells(value: Any, *, mode_count: int, field: str) -> list[list[Any]]:
    cells = _cells(value)
    if cells.size == 0:
        return [[] for _ in range(mode_count)]
    if cells.shape[0] != mode_count:
        if mode_count == 1 and cells.shape[1] == 1:
            cells = cells.reshape(1, cells.shape[0], order="F")
        else:
            raise _fail(f"{field} has {cells.shape[0]} modes; data has {mode_count}")
    if cells.shape[1] > _MAX_SETS_PER_MODE:
        raise _fail(f"{field} exceeds the set-count limit")
    return [[cells[mode, index] for index in range(cells.shape[1])] for mode in range(mode_count)]


def _name_grid(value: Any, *, mode_count: int, field: str, widths: Sequence[int]) -> list[list[str | None]]:
    if value is None:
        return [[None] * width for width in widths]
    rows = _mode_cells(value, mode_count=mode_count, field=field)
    result: list[list[str | None]] = []
    for mode, width in enumerate(widths):
        if len(rows[mode]) not in {0, width}:
            raise _fail(f"{field} set count does not match its values")
        result.append(
            [_text(item, field=f"{field}[{mode},{index}]") for index, item in enumerate(rows[mode])]
            if rows[mode]
            else [None] * width
        )
    return result


def _unpack_legacy_value_names(
    rows: list[list[Any]],
    *,
    explicit_names: Any,
    field: str,
) -> tuple[list[list[Any]], list[list[str | None]] | None]:
    """Split legacy ``{values, set name}`` rows when no name field exists."""

    if _declares_text(explicit_names, field=f"{field}name") or not all(len(row) == 2 for row in rows):
        return rows, None
    names: list[list[str | None]] = []
    for mode_index, row in enumerate(rows):
        try:
            name = _text(row[1], field=f"{field}[{mode_index + 1},2]")
        except UnreadableSpectrumError:
            return rows, None
        packed_name = np.asarray(_unwrap(row[1]))
        if np.asarray(_unwrap(row[0])).size and name is None and packed_name.dtype.kind not in "US":
            return rows, None
        names.append([name])
    return [row[:1] for row in rows], names


def _numeric_data(value: Any, *, source: BoundedSource) -> tuple[np.ndarray, str, tuple[int, ...]]:
    value = _unwrap(value)
    array = np.asarray(value)
    if array.ndim == 0:
        raise _fail("data must not be scalar")
    if array.dtype.kind not in "biuf":
        if array.dtype.kind == "c":
            raise UnsupportedFormatVariantError("Eigenvector DSO complex data is not supported")
        raise UnsupportedFormatVariantError("Eigenvector DSO data must be dense numeric or logical")
    source.require_elements(int(array.size), format_id="matlab")
    source.require_decoded_bytes(int(array.nbytes), format_id="matlab")
    # NaN is a governed missing-value marker in Eigenvector property DSOs.
    # Preserve it so a finite spectra object in the same MATLAB workspace can
    # still be selected and targets can be filtered explicitly.  Infinity is
    # never an admissible missing-value representation.
    if np.any(np.isinf(array)):
        raise _fail("data contains infinite values")
    if array.dtype.kind in "iu" and array.size:
        maximum = int(np.max(np.abs(array.astype(object))))
        if maximum > 2**53 - 1:
            raise _fail("integer data cannot be represented losslessly as float64")
    source_dtype = np.dtype(array.dtype).str
    source_shape = tuple(int(item) for item in array.shape)
    return np.asarray(array, dtype=np.float64, order="C"), source_dtype, source_shape


def _aligned_numeric(value: Any, *, length: int, field: str, source: BoundedSource) -> np.ndarray:
    array = np.asarray(_unwrap(value))
    if array.dtype.kind not in "iuf" or array.size != length:
        raise _fail(f"{field} must contain {length} aligned numeric values")
    array = np.asarray(array, dtype=np.float64).reshape(-1, order="F")
    if not np.all(np.isfinite(array)):
        raise _fail(f"{field} contains non-finite values")
    source.require_elements(int(array.size), format_id="matlab")
    return array


def _aligned_labels(value: Any, *, length: int, field: str) -> tuple[str, ...]:
    value = _unwrap(value)
    array = np.asarray(value, dtype=object)
    if array.size != length:
        raise _fail(f"{field} must contain {length} aligned labels")
    labels: list[str] = []
    for index, item in enumerate(array.reshape(-1, order="F")):
        label = _text(item, field=f"{field}[{index}]", required=True)
        assert label is not None
        labels.append(label)
    return tuple(labels)


def _aligned_classes(value: Any, *, length: int, field: str) -> tuple[LosslessScalar, ...]:
    value = _unwrap(value)
    array = np.asarray(value, dtype=object)
    if array.size != length:
        raise _fail(f"{field} must contain {length} aligned class values")
    return tuple(_scalar(item, field=f"{field}[{index}]") for index, item in enumerate(array.reshape(-1, order="F")))


def _include_mask(value: Any, *, length: int, field: str) -> np.ndarray:
    value = _unwrap(value)
    array = np.asarray(value)
    flat = array.reshape(-1, order="F")
    if flat.dtype.kind == "b" and flat.size == length:
        return flat.astype(bool, copy=True)
    if flat.dtype.kind not in "iuf" or not np.all(np.isfinite(flat)):
        raise _fail(f"{field} must be a logical mask or one-based integer indices")
    if not np.all(flat == np.floor(flat)):
        raise _fail(f"{field} contains non-integral indices")
    indices = flat.astype(np.int64)
    if np.any(indices < 1) or np.any(indices > length) or len(set(indices.tolist())) != indices.size:
        raise _fail(f"{field} contains invalid or duplicate one-based indices")
    mask = np.zeros(length, dtype=bool)
    mask[indices - 1] = True
    return mask


def _include_rows(fields: Mapping[str, Any], *, mode_lengths: Sequence[int]) -> list[np.ndarray | None]:
    include = fields.get("include")
    legacy = fields.get("includ")
    if include is None and legacy is None:
        return [None] * len(mode_lengths)

    def decode(raw: Any, name: str) -> list[np.ndarray | None]:
        rows = _mode_cells(raw, mode_count=len(mode_lengths), field=name)
        result: list[np.ndarray | None] = []
        for mode, length in enumerate(mode_lengths):
            nonempty = [item for item in rows[mode] if np.asarray(_unwrap(item)).size]
            if len(nonempty) > 1:
                raise _fail(f"{name} declares multiple masks for mode {mode + 1}")
            result.append(_include_mask(nonempty[0], length=length, field=f"{name}[{mode + 1}]") if nonempty else None)
        return result

    current = decode(include, "include") if include is not None else None
    old = decode(legacy, "includ") if legacy is not None else None
    if current is not None and old is not None:
        for left, right in zip(current, old, strict=True):
            if (left is None) != (right is None):
                raise _fail("include and legacy includ authorities contradict")
            if left is not None:
                assert right is not None
                if np.array_equal(left, right):
                    continue
                raise _fail("include and legacy includ authorities contradict")
    return current if current is not None else old or [None] * len(mode_lengths)


def _levels(values: Sequence[LosslessScalar]) -> tuple[AxisClassLevel, ...]:
    unique: list[LosslessScalar] = []
    identities: set[tuple[str, LosslessScalar]] = set()
    for value in values:
        if value is None:
            continue
        identity = lossless_scalar_identity(value)
        if identity not in identities:
            identities.add(identity)
            unique.append(value)
    return tuple(AxisClassLevel(code=value, label=str(value)) for value in unique)


def _lookup_levels(value: Any, *, values: Sequence[LosslessScalar], field: str) -> tuple[AxisClassLevel, ...]:
    value = _unwrap(value)
    if value is None or (isinstance(value, np.ndarray) and value.size == 0):
        return _levels(values)
    array = np.asarray(value, dtype=object)
    distinct = _levels(values)
    if array.ndim == 2 and array.shape[1] == 2:
        admitted_levels: list[AxisClassLevel] = []
        for row in range(array.shape[0]):
            label = _text(array[row, 1], field=f"{field}[{row},label]", required=True)
            assert label is not None
            admitted_levels.append(
                AxisClassLevel(code=_scalar(array[row, 0], field=f"{field}[{row},code]"), label=label)
            )
        levels = tuple(admitted_levels)
    elif array.size == len(distinct):
        labels = array.reshape(-1, order="F")
        admitted_levels = []
        for index, level in enumerate(distinct):
            label = _text(labels[index], field=f"{field}[{index}]", required=True)
            assert label is not None
            admitted_levels.append(AxisClassLevel(code=level.code, label=label))
        levels = tuple(admitted_levels)
    else:
        raise _fail(f"{field} must be a code/label table or one label per typed class level")
    admitted = {lossless_scalar_identity(level.code) for level in levels}
    required = {lossless_scalar_identity(value) for value in values if value is not None}
    if required - admitted:
        raise _fail(f"{field} does not name every class value")
    return levels


def _axis_for_mode(
    *,
    mode: int,
    length: int,
    mode_count: int,
    fields: Mapping[str, Any],
    includes: Sequence[np.ndarray | None],
    source: BoundedSource,
) -> AxisInfo:
    scale_rows = _mode_cells(fields.get("axisscale"), mode_count=mode_count, field="axisscale")
    label_rows = _mode_cells(fields.get("label"), mode_count=mode_count, field="label")
    title_rows = _mode_cells(fields.get("title"), mode_count=mode_count, field="title")
    class_rows = _mode_cells(fields.get("class"), mode_count=mode_count, field="class")
    scale_rows, packed_scale_names = _unpack_legacy_value_names(
        scale_rows,
        explicit_names=fields.get("axisscalename"),
        field="axisscale",
    )
    label_rows, packed_label_names = _unpack_legacy_value_names(
        label_rows,
        explicit_names=fields.get("labelname"),
        field="label",
    )
    class_rows, packed_class_names = _unpack_legacy_value_names(
        class_rows,
        explicit_names=fields.get("classname"),
        field="class",
    )
    scale_names = packed_scale_names or _name_grid(
        fields.get("axisscalename"),
        mode_count=mode_count,
        field="axisscalename",
        widths=[len(row) for row in scale_rows],
    )
    scale_types = _name_grid(
        fields.get("axisscaletype"),
        mode_count=mode_count,
        field="axisscaletype",
        widths=[len(row) for row in scale_rows],
    )
    label_names = packed_label_names or _name_grid(
        fields.get("labelname"),
        mode_count=mode_count,
        field="labelname",
        widths=[len(row) for row in label_rows],
    )
    title_names = _name_grid(
        fields.get("titlename"),
        mode_count=mode_count,
        field="titlename",
        widths=[len(row) for row in title_rows],
    )
    class_names = packed_class_names or _name_grid(
        fields.get("classname"),
        mode_count=mode_count,
        field="classname",
        widths=[len(row) for row in class_rows],
    )
    class_lookup_rows = _mode_cells(fields.get("classlookup"), mode_count=mode_count, field="classlookup")
    if any(class_lookup_rows):
        for mode_index, row in enumerate(class_lookup_rows):
            if len(row) != len(class_rows[mode_index]):
                raise _fail("classlookup set count does not match class")

    scales: list[tuple[str, np.ndarray, str | None]] = []
    for index, item in enumerate(scale_rows[mode]):
        if np.asarray(_unwrap(item)).size == 0:
            continue
        name = scale_names[mode][index] or f"scale {index + 1}"
        scales.append(
            (
                name,
                _aligned_numeric(item, length=length, field=f"axisscale[{mode + 1},{index + 1}]", source=source),
                scale_types[mode][index],
            )
        )
    labels: list[tuple[str, tuple[str, ...]]] = []
    for index, item in enumerate(label_rows[mode]):
        if np.asarray(_unwrap(item)).size == 0:
            continue
        name = label_names[mode][index] or f"labels {index + 1}"
        labels.append((name, _aligned_labels(item, length=length, field=f"label[{mode + 1},{index + 1}]")))
    titles: list[tuple[str, str]] = []
    for index, item in enumerate(title_rows[mode]):
        title = _text(item, field=f"title[{mode + 1},{index + 1}]")
        if title is not None:
            titles.append((title_names[mode][index] or f"title {index + 1}", title))
    classes: list[AxisClassSet] = []
    for index, item in enumerate(class_rows[mode]):
        if np.asarray(_unwrap(item)).size == 0:
            continue
        values = _aligned_classes(item, length=length, field=f"class[{mode + 1},{index + 1}]")
        classes.append(
            AxisClassSet(
                name=class_names[mode][index] or f"class {index + 1}",
                values=values,
                levels=(
                    _lookup_levels(
                        class_lookup_rows[mode][index],
                        values=values,
                        field=f"classlookup[{mode + 1},{index + 1}]",
                    )
                    if class_lookup_rows[mode]
                    else _levels(values)
                ),
                source_set_index=index,
            )
        )

    primary_scale = scales[0] if scales else None
    primary_labels = labels[0] if labels else None
    primary_title = titles[0] if titles else None
    kwargs: dict[str, Any] = {
        "values": primary_scale[1] if primary_scale else None,
        "labels": list(primary_labels[1]) if primary_labels else None,
        "title": primary_title[1] if primary_title else None,
        "include_mask": includes[mode],
        "primary_scale_name": primary_scale[0] if primary_scale else None,
        "alternate_scales": tuple(
            AxisScaleSet(name=name, values=values, axis_type=axis_type, source_set_index=index)
            for index, (name, values, axis_type) in enumerate(scales[1:], start=1)
        ),
        "primary_label_name": primary_labels[0] if primary_labels else None,
        "alternate_label_sets": tuple(
            AxisLabelSet(name=name, values=values, source_set_index=index)
            for index, (name, values) in enumerate(labels[1:], start=1)
        ),
        "primary_title_name": primary_title[0] if primary_title else None,
        "alternate_title_sets": tuple(
            AxisTitleSet(name=name, title=title, source_set_index=index)
            for index, (name, title) in enumerate(titles[1:], start=1)
        ),
        "class_sets": tuple(classes),
        "primary_class_set_name": classes[0].name if classes and mode == 0 else None,
    }
    if mode == 0 and mode_count > 1:
        return SampleAxis(**kwargs)
    if mode == mode_count - 1:
        evidence = " ".join(
            str(value or "")
            for value in (
                primary_scale[0] if primary_scale else None,
                primary_scale[2] if primary_scale else None,
                primary_title[1] if primary_title else None,
            )
        ).lower()
        if any(token in evidence for token in ("wave", "wavenumber", "spectral", "frequency")):
            return SpectralAxis(**kwargs)
        return FeatureAxis(**kwargs)
    evidence = " ".join(str(value or "") for value in (primary_scale, primary_title)).lower()
    if any(token in evidence for token in ("pixel", "spatial", "position", "row", "column")):
        return SpatialAxis(**kwargs)
    return AxisInfo(**kwargs)


def _history(value: Any) -> DatasetSourceHistory:
    if value is None:
        return DatasetSourceHistory()
    cells = _cells(value)
    entries: list[str] = []
    for index, item in enumerate(cells.reshape(-1, order="F")):
        text = _text(item, field=f"history[{index}]")
        if text is not None:
            entries.append(text)
    if not entries:
        return DatasetSourceHistory()
    return DatasetSourceHistory(
        entries=tuple(entries),
        source_shape=(len(entries),),
        storage_order="column-major",
    )


def _userdata(value: Any, *, depth: int = 0) -> object:
    if depth > 8:
        raise _fail("userdata exceeds the nesting-depth limit")
    value = _unwrap(value)
    if isinstance(value, Mapping):
        if len(value) > 1024:
            raise _fail("userdata mapping exceeds the entry limit")
        return {str(key): _userdata(item, depth=depth + 1) for key, item in value.items()}
    if isinstance(value, np.ndarray):
        if value.dtype.names:
            if value.size != 1:
                raise _fail("userdata struct arrays are unsupported")
            record = value.reshape(-1, order="F")[0]
            return {name: _userdata(record[name], depth=depth + 1) for name in value.dtype.names}
        if value.size == 1:
            return _userdata(value.reshape(-1, order="F")[0], depth=depth + 1)
        if value.size > 65_536:
            raise _fail("userdata array exceeds the element limit")
        return [_userdata(item, depth=depth + 1) for item in value.reshape(-1, order="F")]
    if isinstance(value, (list, tuple)):
        if len(value) > 65_536:
            raise _fail("userdata sequence exceeds the element limit")
        return [_userdata(item, depth=depth + 1) for item in value]
    return _scalar(value, field="userdata")


def _exact_integer(value: Any, *, field: str, minimum: int = 0) -> int:
    scalar = _unwrap(value)
    if isinstance(scalar, np.ndarray) and scalar.size == 1:
        scalar = scalar.reshape(-1, order="F")[0]
    if isinstance(scalar, np.generic):
        scalar = scalar.item()
    if isinstance(scalar, bool) or not isinstance(scalar, (int, float)) or not np.isfinite(scalar):
        raise _fail(f"{field} must be an exact integer")
    integer = int(scalar)
    if integer != scalar or integer < minimum:
        raise _fail(f"{field} must be an exact integer >= {minimum}")
    return integer


def _exact_shape(value: Any, *, field: str) -> tuple[int, ...]:
    array = np.asarray(_unwrap(value))
    if array.ndim > 2 or array.size == 0 or array.size > _MAX_MODES:
        raise _fail(f"{field} must be a bounded positive-integer vector")
    return tuple(
        _exact_integer(item, field=f"{field}[{index}]", minimum=1)
        for index, item in enumerate(array.reshape(-1, order="F"))
    )


def _refold_image(data: np.ndarray, *, image_mode: int, image_size: tuple[int, ...]) -> np.ndarray:
    """Replace one unfolded MATLAB mode using column-major pixel order."""

    pixel_count = int(np.prod(image_size, dtype=np.int64))
    if data.shape[image_mode] != pixel_count:
        raise _fail("imagesize product does not match the unfolded image mode")
    other_indices = [index for index in range(data.ndim) if index != image_mode]
    moved = np.moveaxis(data, image_mode, -1)
    temporary = moved.reshape((*moved.shape[:-1], *reversed(image_size)), order="C")
    temporary_labels = [("original", index) for index in other_indices]
    temporary_labels.extend(("spatial", index) for index in reversed(range(len(image_size))))
    desired_labels: list[tuple[str, int]] = []
    for original in range(data.ndim):
        if original == image_mode:
            desired_labels.extend(("spatial", index) for index in range(len(image_size)))
        else:
            desired_labels.append(("original", original))
    permutation = [temporary_labels.index(label) for label in desired_labels]
    return np.asarray(temporary.transpose(permutation), dtype=np.float64, order="C")


def _image_include(
    value: Any,
    *,
    image_size: tuple[int, ...],
) -> tuple[tuple[np.ndarray | None, ...], tuple[bool, ...] | None]:
    if value is None:
        return tuple(None for _ in image_size), None
    raw = np.asarray(value, dtype=object)
    if raw.dtype == object and raw.size == len(image_size):
        masks = tuple(
            _include_mask(item, length=image_size[index], field=f"imageinclude[{index + 1}]")
            for index, item in enumerate(raw.reshape(-1, order="F"))
        )
        grid = np.ones(image_size, dtype=bool)
        for axis, mask in enumerate(masks):
            broadcast = [1] * len(image_size)
            broadcast[axis] = image_size[axis]
            grid &= mask.reshape(broadcast)
        return masks, tuple(bool(item) for item in grid.reshape(-1, order="F"))
    mask = _include_mask(value, length=int(np.prod(image_size)), field="imageinclude")
    return tuple(None for _ in image_size), tuple(bool(item) for item in mask)


def _image_axes(
    fields: Mapping[str, Any],
    *,
    image_size: tuple[int, ...],
    includes: Sequence[np.ndarray | None],
    source: BoundedSource,
) -> tuple[SpatialAxis, ...]:
    axis_fields = {
        "axisscale": fields.get("imageaxisscale"),
        "axisscalename": fields.get("imageaxisscalename"),
        "axisscaletype": fields.get("imageaxisscaletype"),
    }
    axes: list[SpatialAxis] = []
    for mode, length in enumerate(image_size):
        axis = _axis_for_mode(
            mode=mode,
            length=length,
            mode_count=len(image_size),
            fields=axis_fields,
            includes=includes,
            source=source,
        )
        projection = axis.model_dump(mode="python")
        if projection.get("title") is None:
            projection["title"] = f"Image dimension {mode + 1}"
        axes.append(SpatialAxis.model_validate(projection))
    return tuple(axes)


def map_decoded_dso(
    record: DecodedDSO,
    *,
    source: BoundedSource,
    parser_version: str,
    image_view: str = "unfolded-pixels",
) -> SherpaDataset:
    """Admit one neutral DSO record into the canonical n-D dataset model."""

    if image_view not in {"unfolded-pixels", "image-cube"}:
        raise ValueError("Eigenvector DSO image_view must be 'unfolded-pixels' or 'image-cube'")

    fields = {str(key).lower(): value for key, value in record.fields.items()}
    unknown = set(fields) - (DSO_SIGNATURE_FIELDS | {"data"})
    if unknown:
        raise UnsupportedFormatVariantError(
            "Eigenvector DSO contains unsupported field(s): " + ", ".join(sorted(unknown))
        )
    data, source_dtype, original_shape = _numeric_data(fields.get("data"), source=source)
    source_type = (_text(fields.get("type"), field="type") or "data").lower()
    if source_type == "batch":
        raise UnsupportedFormatVariantError(
            "Eigenvector batch DSO contains ragged observations; export a rectangular data DSO"
        )
    if source_type not in {"data", "image"}:
        raise UnsupportedFormatVariantError(f"Eigenvector DSO type {source_type!r} is not supported")
    if source_type != "image" and image_view != "unfolded-pixels":
        raise UnsupportedFormatVariantError("Eigenvector image-cube view requires an image DSO")
    if _present(fields.get("imagedata")):
        raise UnsupportedFormatVariantError(
            "Eigenvector DSO imagedata payloads are not supported; export an image "
            "DSO whose data field contains the unfolded image"
        )
    active_image_fields = {
        "imagemode",
        "imagesize",
        "imageinclude",
    }
    if source_type != "image" and any(_present(fields.get(field)) for field in active_image_fields):
        raise _fail("image metadata is present while type is not image")
    mode_lengths: tuple[int, ...]
    mode_roles: tuple[str, ...]
    if data.ndim == 1:
        normalized = data.reshape(1, -1)
        mode_lengths = (data.shape[0],)
        mode_count = 1
        mode_roles = ("feature",)
    else:
        if data.ndim > _MAX_MODES:
            raise _fail("data exceeds the mode-count limit")
        normalized = data
        mode_lengths = tuple(int(item) for item in data.shape)
        mode_count = data.ndim
        mode_roles = tuple(
            "sample" if index == 0 else "feature" if index == data.ndim - 1 else "inner" for index in range(data.ndim)
        )
    includes = _include_rows(fields, mode_lengths=mode_lengths)
    source_axes = [
        _axis_for_mode(
            mode=mode,
            length=length,
            mode_count=mode_count,
            fields=fields,
            includes=includes,
            source=source,
        )
        for mode, length in enumerate(mode_lengths)
    ]
    image_size: tuple[int, ...] | None = None
    image_mode_number: int | None = None
    image_mask_projection: tuple[bool, ...] | None = None
    if source_type == "image":
        if data.ndim < 2:
            raise UnsupportedFormatVariantError(
                "Eigenvector image DSO must have an unfolded image mode and a feature mode"
            )
        image_mode_number = _exact_integer(fields.get("imagemode"), field="imagemode", minimum=1)
        image_mode = image_mode_number - 1
        if image_mode < 0 or image_mode >= data.ndim - 1:
            raise UnsupportedFormatVariantError(
                "Eigenvector image DSO imagemode must identify an unfolded non-feature mode"
            )
        image_size = _exact_shape(fields.get("imagesize"), field="imagesize")
        spatial_includes, image_mask_projection = _image_include(fields.get("imageinclude"), image_size=image_size)
        if image_view == "image-cube" and image_mask_projection is None and data.ndim == 2:
            unfolded_include = source_axes[image_mode].include_mask
            if unfolded_include is not None:
                if len(unfolded_include) != int(np.prod(image_size, dtype=np.int64)):
                    raise _fail("unfolded image include mask does not match imagesize")
                image_mask_projection = tuple(bool(item) for item in unfolded_include)
        spatial_axes = _image_axes(fields, image_size=image_size, includes=spatial_includes, source=source)
        if data.ndim == 2 and image_mode == 0 and image_view == "unfolded-pixels":
            # Real PLS_Toolbox image DSOs commonly store pixels-by-features and
            # identify the first mode as an unfolded image.  Retaining that
            # matrix makes every pixel an ordinary modeling observation while
            # ``layout.image_size`` preserves the exact spatial refolding
            # authority for image-aware views.
            if data.shape[0] != int(np.prod(image_size, dtype=np.int64)):
                raise _fail("imagesize product does not match the unfolded image mode")
            axes = source_axes
            mode_roles = ("sample", "feature")
        else:
            if image_view == "image-cube" and not (data.ndim == 2 and image_mode == 0):
                raise UnsupportedFormatVariantError(
                    "Eigenvector image-cube view requires a two-dimensional pixels-by-features DSO"
                )
            normalized = _refold_image(data, image_mode=image_mode, image_size=image_size)
            mode_roles_list: list[str] = []
            output_axes: list[AxisInfo] = []
            for mode, axis in enumerate(source_axes):
                if mode == image_mode:
                    output_axes.extend(spatial_axes)
                    mode_roles_list.extend("spatial_coordinate" for _axis in spatial_axes)
                else:
                    output_axes.append(axis)
                    mode_roles_list.append("sample" if mode == 0 else "feature" if mode == data.ndim - 1 else "inner")
            axes = output_axes
            mode_roles = tuple(mode_roles_list)
    else:
        axes = source_axes

    if data.ndim == 1:
        sample_axis = SampleAxis.model_validate({"labels": ["1"], "title": "Sample"})
        feature_candidate = axes[0]
        inner_axes: dict[int, AxisInfo] = {}
    else:
        sample_candidate = axes[0]
        sample_axis = (
            sample_candidate
            if isinstance(sample_candidate, SampleAxis)
            else SampleAxis.model_validate(sample_candidate.model_dump(mode="python"))
        )
        feature_candidate = axes[-1]
        inner_axes = {index: axis for index, axis in enumerate(axes[1:-1], start=1)}
    feature_axis = (
        feature_candidate
        if isinstance(feature_candidate, FeatureAxis)
        else FeatureAxis.model_validate(feature_candidate.model_dump(mode="python"))
    )

    name = _text(fields.get("name"), field="name") or record.variable_name
    authors = _authors(fields.get("author"))
    description = _text(fields.get("description"), field="description")
    raw_dates = {
        key: text for key in ("date", "moddate") if (text := _date_text(fields.get(key), field=key)) is not None
    }
    object_unique_id = _text(fields.get("uniqueid"), field="uniqueid")
    dataset_version = _text(fields.get("datasetversion"), field="datasetversion")
    legacy_dataset_version = _text(fields.get("version"), field="version")
    if dataset_version is not None and legacy_dataset_version is not None:
        if dataset_version != legacy_dataset_version:
            raise _fail("datasetversion and legacy version authorities contradict")
    dataset_version = dataset_version if dataset_version is not None else legacy_dataset_version
    source_history = _history(fields.get("history"))
    extra: dict[str, Any] = {
        "source_file": source.path.name,
        "source_type": "mat",
        "matlab.variable": record.variable_name,
    }
    if "userdata" in fields:
        extra["dso.userdata"] = _userdata(fields["userdata"])
    for field in ("axistype", "imageaxistype"):
        if field in fields and _present(fields[field]):
            extra[f"dso.{field}"] = _userdata(fields[field])

    provenance = Provenance(
        [
            ProvenanceEntry(
                op_id="import.matlab_dso",
                op_version="1.0",
                parameters={
                    "parser_id": "spectrasherpa.matlab",
                    "parser_version": parser_version,
                    "source_sha256": source.member().sha256,
                    "source_size_bytes": source.member().size_bytes,
                    "asset_id": record.variable_name,
                    "storage_version": record.storage_version,
                    "source_variable": record.variable_name,
                    "source_dtype": source_dtype,
                    "source_shape": original_shape,
                    **({"image_view": image_view} if image_view == "image-cube" else {}),
                },
                timestamp="",
                input_shape=original_shape,
                output_shape=tuple(int(item) for item in normalized.shape),
            )
        ]
    )
    dataset = SherpaDataset(
        X=normalized,
        sample_axis=sample_axis,
        feature_axis=feature_axis,
        axes=inner_axes,
        domain=DomainContext(),
        title=name,
        descriptive=DatasetDescriptiveContext(
            authors=authors,
            description=description,
            created_at=_iso_datetime(raw_dates.get("date")),
            modified_at=_iso_datetime(raw_dates.get("moddate")),
            raw_date_fields=raw_dates,
        ),
        source_identity=DatasetSourceIdentity(
            source_format="eigenvector-dso",
            storage_version=record.storage_version,
            object_name=name,
            object_unique_id=object_unique_id,
            dataset_version=dataset_version,
            source_variable=record.variable_name,
        ),
        source_history=source_history,
        layout=DatasetLayoutContext(
            kind="image" if source_type == "image" else "generic",
            source_type=source_type,
            source_dtype=source_dtype,
            source_shape=tuple(int(item) for item in normalized.shape),
            mode_roles=mode_roles if data.ndim > 1 else ("sample", "feature"),
            image_size=image_size,
            image_mode=image_mode_number,
            image_include=image_mask_projection,
            original_unfolded_shape=original_shape if source_type == "image" or data.ndim == 1 else None,
        ),
        provenance=provenance,
        extra=extra,
        data_role=derive_data_role(feature_axis),
    )
    return dataset


def dso_image_cube_output_bytes(fields: Mapping[str, Any]) -> int:
    """Return retained float64 bytes for an additional unfolded-image cube view."""

    normalized = {str(key).lower(): value for key, value in fields.items()}
    if (_text(normalized.get("type"), field="type") or "data").lower() != "image":
        return 0
    data = np.asarray(_unwrap(normalized.get("data")))
    imagemode = _exact_integer(normalized.get("imagemode"), field="imagemode", minimum=1)
    if data.ndim != 2 or imagemode != 1:
        return 0
    return int(data.size) * np.dtype(np.float64).itemsize


def scipy_struct_fields(value: np.ndarray) -> Mapping[str, Any]:
    """Project one scipy v5 structured scalar into the neutral DSO mapping."""

    if not isinstance(value, np.ndarray) or not value.dtype.names or value.size != 1:
        raise _fail("DSO MATLAB variable must be one scalar struct")
    record = value.reshape(-1, order="F")[0]
    return {name: record[name] for name in value.dtype.names}


__all__ = [
    "DecodedDSO",
    "DecodedDSOFootprint",
    "decoded_dso_footprint",
    "dso_image_cube_output_bytes",
    "dso_float64_output_bytes",
    "is_dso_field_set",
    "map_decoded_dso",
    "scipy_struct_fields",
]
