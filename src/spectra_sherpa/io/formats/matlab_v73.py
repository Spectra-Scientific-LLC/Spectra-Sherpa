"""Bounded MATLAB v7.3/HDF5 storage decoder.

The decoder owns no DSO scientific semantics. It admits the HDF5 object graph
and projects MATLAB arrays, cells, chars, logicals, and scalar structs into
ordinary Python/NumPy values consumed by the storage-neutral DSO mapper.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import h5py  # type: ignore[import-untyped]
import numpy as np

from spectra_sherpa.ingestion_errors import ParserLimitError, UnreadableSpectrumError, UnsupportedFormatVariantError
from spectra_sherpa.io.base import BoundedSource

_FORMAT_ID = "matlab"
_MAX_HDF5_DEPTH = 32
_REFERENCE_ITEM_BYTES = 16


def _fail(detail: str) -> UnreadableSpectrumError:
    return UnreadableSpectrumError(format_id=_FORMAT_ID, detail=f"invalid MATLAB v7.3/HDF5: {detail}")


def _attribute_text(value: Any, *, field: str) -> str | None:
    if value is None:
        return None
    if isinstance(value, bytes):
        try:
            return value.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise _fail(f"{field} is not UTF-8 text") from exc
    if isinstance(value, str):
        return value
    if isinstance(value, np.ndarray) and value.size == 1:
        return _attribute_text(value.reshape(-1)[0], field=field)
    raise _fail(f"{field} must be scalar text")


def _object_address(value: h5py.Group | h5py.Dataset) -> int:
    return int(h5py.h5o.get_info(value.id).addr)


def _matlab_order(array: np.ndarray) -> np.ndarray:
    """Reverse HDF5 dimensions into MATLAB's declared dimension order."""

    if array.ndim <= 1:
        return array
    return array.transpose(tuple(reversed(range(array.ndim))))


def _attribute_footprint(attributes: h5py.AttributeManager) -> int:
    """Measure stored attribute bytes without materializing attribute values."""

    total = 0
    for name in attributes:
        total += len(str(name).encode("utf-8"))
        total += int(attributes.get_id(name).get_storage_size())
    return total


def _dataset_decoded_bytes(dataset: h5py.Dataset) -> int:
    dtype = dataset.dtype
    if h5py.check_dtype(ref=dtype) is not None:
        return int(dataset.size) * _REFERENCE_ITEM_BYTES
    if h5py.check_dtype(vlen=dtype) is not None:
        raise UnsupportedFormatVariantError("MATLAB v7.3 variable-length HDF5 datasets are not supported")
    if dtype.kind not in "biufcS":
        raise UnsupportedFormatVariantError(f"MATLAB v7.3 HDF5 dtype {dtype.str!r} is not supported")
    return int(dataset.size) * int(dtype.itemsize)


def _preflight_hdf5(file: h5py.File, *, source: BoundedSource) -> None:
    """Census the complete hard-linked object graph before dataset reads."""

    elements = 0
    decoded_bytes = 0
    metadata_bytes = _attribute_footprint(file.attrs)
    blocks = 1
    seen: set[int] = {_object_address(file)}
    source.require_blocks(blocks, format_id=_FORMAT_ID)
    source.require_metadata_bytes(metadata_bytes, format_id=_FORMAT_ID)

    def walk(group: h5py.Group, *, depth: int) -> None:
        nonlocal elements, decoded_bytes, metadata_bytes, blocks
        if depth > _MAX_HDF5_DEPTH:
            raise _fail("object graph exceeds the nesting-depth limit")
        for name in group:
            metadata_bytes += len(name.encode("utf-8"))
            link = group.get(name, getlink=True)
            if isinstance(link, (h5py.SoftLink, h5py.ExternalLink)):
                raise UnsupportedFormatVariantError("MATLAB v7.3 soft and external HDF5 links are not supported")
            child = group.get(name, getlink=False)
            if not isinstance(child, (h5py.Group, h5py.Dataset)):
                raise _fail(f"object {name!r} is neither a group nor dataset")
            blocks += 1
            source.require_blocks(blocks, format_id=_FORMAT_ID)
            metadata_bytes += _attribute_footprint(child.attrs)
            source.require_metadata_bytes(metadata_bytes, format_id=_FORMAT_ID)
            address = _object_address(child)
            if address in seen:
                continue
            seen.add(address)
            if isinstance(child, h5py.Group):
                walk(child, depth=depth + 1)
                continue
            if child.id.get_create_plist().get_external_count():
                raise UnsupportedFormatVariantError("MATLAB v7.3 external HDF5 dataset storage is not supported")
            elements += int(child.size)
            decoded_bytes += _dataset_decoded_bytes(child)
            source.require_elements(elements, format_id=_FORMAT_ID)
            source.require_decoded_bytes(decoded_bytes, format_id=_FORMAT_ID)

    walk(file, depth=0)


class _Decoder:
    def __init__(self, file: h5py.File) -> None:
        self.file = file
        self.cache: dict[int, Any] = {}
        self.active: set[int] = set()

    def decode(self, value: h5py.Group | h5py.Dataset, *, depth: int = 0) -> Any:
        if depth > _MAX_HDF5_DEPTH:
            raise _fail("decoded reference graph exceeds the nesting-depth limit")
        address = _object_address(value)
        if address in self.cache:
            return self.cache[address]
        if address in self.active:
            raise UnsupportedFormatVariantError("MATLAB v7.3 cyclic HDF5 references are not supported")
        self.active.add(address)
        try:
            decoded = (
                self._decode_group(value, depth=depth)
                if isinstance(value, h5py.Group)
                else self._decode_dataset(value, depth=depth)
            )
            self.cache[address] = decoded
            return decoded
        finally:
            self.active.remove(address)

    def _decode_group(self, group: h5py.Group, *, depth: int) -> Mapping[str, Any]:
        matlab_class = _attribute_text(group.attrs.get("MATLAB_class"), field="MATLAB_class")
        matlab_class = matlab_class.lower() if matlab_class is not None else None
        if matlab_class not in {None, "struct", "object", "dataset", "dataset_object", "datasetobject"}:
            raise UnsupportedFormatVariantError(f"MATLAB v7.3 group class {matlab_class!r} is not supported")
        return {name: self.decode(group[name], depth=depth + 1) for name in group if name != "#refs#"}

    def _decode_reference(self, reference: h5py.Reference, *, depth: int) -> Any:
        if not reference:
            return np.empty((0, 0))
        target = self.file[reference]
        if not isinstance(target, (h5py.Group, h5py.Dataset)):
            raise _fail("object reference does not resolve to a group or dataset")
        return self.decode(target, depth=depth + 1)

    def _decode_dataset(self, dataset: h5py.Dataset, *, depth: int) -> Any:
        matlab_class = _attribute_text(dataset.attrs.get("MATLAB_class"), field="MATLAB_class")
        matlab_class = matlab_class.lower() if matlab_class is not None else None
        matlab_empty = dataset.attrs.get("MATLAB_empty")
        if matlab_empty is not None and bool(np.asarray(matlab_empty).reshape(-1)[0]):
            dimensions = np.asarray(dataset[()]).reshape(-1, order="F")
            if dimensions.size > 16 or dimensions.dtype.kind not in "iuf":
                raise _fail("MATLAB empty-array dimensions are malformed")
            if not np.all(np.isfinite(dimensions)) or not np.all(dimensions == np.floor(dimensions)):
                raise _fail("MATLAB empty-array dimensions must be finite exact integers")
            shape = tuple(int(item) for item in dimensions)
            if any(item < 0 for item in shape):
                raise _fail("MATLAB empty-array dimensions must be non-negative")
            return np.empty(shape, dtype=np.float64)
        references = h5py.check_dtype(ref=dataset.dtype)
        if references is not None:
            raw = _matlab_order(np.asarray(dataset[()]))
            decoded = np.empty(raw.shape, dtype=object)
            for index in np.ndindex(raw.shape):
                decoded[index] = self._decode_reference(raw[index], depth=depth)
            if matlab_class not in {None, "cell", "struct", "object"}:
                raise UnsupportedFormatVariantError(
                    f"MATLAB v7.3 reference dataset class {matlab_class!r} is not supported"
                )
            return decoded

        raw = _matlab_order(np.asarray(dataset[()]))
        if matlab_class == "char":
            if raw.dtype.kind not in "iu":
                raise _fail("MATLAB char dataset must use an integer code-unit dtype")
            try:
                return "".join(chr(int(item)) for item in raw.reshape(-1, order="F") if int(item) != 0)
            except ValueError as exc:
                raise _fail("MATLAB char dataset contains an invalid Unicode code point") from exc
        if matlab_class == "logical":
            if raw.dtype.kind not in "biu":
                raise _fail("MATLAB logical dataset must use a logical/integer dtype")
            return raw.astype(bool)
        if matlab_class not in {
            None,
            "double",
            "single",
            "int8",
            "uint8",
            "int16",
            "uint16",
            "int32",
            "uint32",
            "int64",
            "uint64",
        }:
            raise UnsupportedFormatVariantError(f"MATLAB v7.3 dataset class {matlab_class!r} is not supported")
        return raw


def decode_matlab_v73(source: BoundedSource) -> Mapping[str, Any]:
    """Decode one immutable MATLAB v7.3 snapshot after aggregate preflight."""

    try:
        with h5py.File(source.snapshot_path, "r") as file:
            _preflight_hdf5(file, source=source)
            decoder = _Decoder(file)
            return {name: decoder.decode(file[name]) for name in sorted(file) if name != "#refs#"}
    except (ParserLimitError, UnreadableSpectrumError, UnsupportedFormatVariantError):
        raise
    except (OSError, RuntimeError, ValueError, TypeError, KeyError) as exc:
        raise UnreadableSpectrumError(format_id=_FORMAT_ID, detail=source.exception_detail(exc)) from exc


__all__ = ["decode_matlab_v73"]
