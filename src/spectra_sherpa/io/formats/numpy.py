"""Bounded NumPy NPY/NPZ format plugin."""

from __future__ import annotations

import io
import json
import zipfile
from collections.abc import Mapping
from pathlib import Path
from typing import BinaryIO

import numpy as np
from numpy.lib import format as npformat

from spectra_sherpa.app.lib.axes import FeatureAxis, SampleAxis, SpectralAxis
from spectra_sherpa.app.lib.sherpa_dataset import DomainContext, SherpaDataset, TargetContext
from spectra_sherpa.ingestion_errors import FormatIdentityError, UnreadableSpectrumError, UnsupportedFormatVariantError
from spectra_sherpa.io.base import BoundedSource
from spectra_sherpa.io.formats._helpers import dataset_asset, derive_data_role, ingestion_result
from spectra_sherpa.io.types import IngestionResult, ParserLimits, ProbeConfidence, ProbeResult

_NPZ_AXIS_KEYS = {"x", "wavenumber", "wavenumbers", "wavelength", "wavelengths"}
_NPZ_METADATA_KEYS = _NPZ_AXIS_KEYS | {"sample_labels"}
_NPZ_AUXILIARY_KEYS = {"C", "S"}
_NPZ_TEXT_METADATA_KEYS = {
    "sample_labels",
    "spectra_sherpa_synthetic",
    "feature_units",
    "units",
    "concentration_units",
    "recipe_json",
    "ground_truth_json",
    "metadata_json",
}


def _optional_text(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _numeric_array(name: str, value: object) -> np.ndarray:
    array = np.asarray(value)
    if not np.issubdtype(array.dtype, np.number):
        raise ValueError(f"NumPy array {name!r} must be numeric, got {array.dtype}")
    if array.ndim == 0 or array.ndim > 2:
        raise ValueError(f"NumPy array {name!r} must be one- or two-dimensional, got {array.ndim}D")
    return array.astype(np.float64, copy=False)


def _load_npz_arrays(path: Path) -> tuple[np.ndarray, np.ndarray | None, list[str] | None, str]:
    with np.load(path, allow_pickle=False) as payload:
        keys = list(payload.files)
        if not keys:
            raise ValueError(f"Empty NumPy archive: {path.name}")

        data_key = next(
            (
                candidate
                for candidate in ("X", "data", "spectra", "y", "intensity", "absorbance")
                if candidate in payload
            ),
            None,
        )
        if data_key is None:
            numeric_keys = []
            for key in keys:
                try:
                    array = np.asarray(payload[key])
                except ValueError:
                    continue
                if np.issubdtype(array.dtype, np.number) and 1 <= array.ndim <= 2:
                    numeric_keys.append(key)
            if len(numeric_keys) != 1:
                raise ValueError("NumPy .npz files must contain an X array or exactly one numeric data array")
            data_key = numeric_keys[0]

        data = _numeric_array(data_key, payload[data_key])
        feature_values = None
        for axis_key in ("x", "wavenumber", "wavenumbers", "wavelength", "wavelengths"):
            if axis_key in payload:
                axis = np.asarray(payload[axis_key], dtype=np.float64)
                if axis.ndim == 1 and len(axis) == (data.shape[-1] if data.ndim > 1 else data.shape[0]):
                    feature_values = axis
                    break

        labels = None
        if "sample_labels" in payload:
            raw_labels = np.asarray(payload["sample_labels"])
            if raw_labels.ndim == 1:
                labels = [str(label) for label in raw_labels.tolist()]
        return data, feature_values, labels, data_key


def _load_numpy_dataset(path: Path) -> SherpaDataset:
    """Project one structurally admitted NPY/NPZ snapshot into SherpaDataset."""

    synthetic_payload: dict[str, object] | None = None
    if path.suffix.lower() == ".npz":
        from spectra_sherpa.app.lib.synthetic_npz import is_synthetic_npz, load_synthetic_npz

        if is_synthetic_npz(path):
            synthetic_payload = load_synthetic_npz(path)
    if synthetic_payload is not None:
        data = _numeric_array("X", synthetic_payload["X"])
        feature_values = np.asarray(synthetic_payload["wavenumber"], dtype=np.float64)
        labels = [str(value) for value in synthetic_payload.get("sample_labels") or []]
        data_key = "X"
    elif path.suffix.lower() == ".npy":
        data = _numeric_array("array", np.load(path, allow_pickle=False))
        feature_values = None
        labels = None
        data_key = "array"
    else:
        data, feature_values, labels, data_key = _load_npz_arrays(path)

    if data.ndim == 1:
        data = data.reshape(1, -1)
    n_samples, n_features = data.shape[0], data.shape[-1]
    if labels is not None and len(labels) != n_samples:
        labels = None

    embedded_metadata = (
        synthetic_payload.get("metadata")
        if synthetic_payload is not None and isinstance(synthetic_payload.get("metadata"), dict)
        else {}
    )
    assert isinstance(embedded_metadata, dict)
    embedded_technique = _optional_text(embedded_metadata.get("technique"))
    if (
        embedded_technique is None
        and embedded_metadata.get("source") == "synthetic_reference"
        and embedded_metadata.get("synthesis_source") == "hitran"
    ):
        embedded_technique = "FTIR"
    feature_axis = (
        SpectralAxis(
            values=feature_values,
            title=_optional_text(embedded_metadata.get("x_title")),
            units=(
                _optional_text(embedded_metadata.get("x_units"))
                or (_optional_text(synthetic_payload.get("feature_units")) if synthetic_payload is not None else None)
            ),
        )
        if feature_values is not None
        else FeatureAxis(labels=[str(index) for index in range(n_features)], title="Features")
    )
    target = None
    target_context = None
    extra: dict[str, object] = {
        "source_file": str(path),
        "source_type": path.suffix.lower().lstrip("."),
        "numpy.data_key": data_key,
    }
    if synthetic_payload is not None:
        target = np.asarray(synthetic_payload["C"], dtype=np.float64)
        ground_truth_spectra = np.asarray(synthetic_payload["S"], dtype=np.float64)
        ground_truth_axis = None if feature_values is None else np.asarray(feature_values, dtype=np.float64)
        try:
            ground_truth = json.loads(str(synthetic_payload.get("ground_truth_json") or "{}"))
        except (TypeError, ValueError):
            ground_truth = {}
        try:
            recipe = json.loads(str(synthetic_payload.get("recipe_json") or "{}"))
        except (TypeError, ValueError):
            recipe = {}
        names = ground_truth.get("component_names") if isinstance(ground_truth, dict) else None
        target_columns = target.shape[1] if target.ndim == 2 else 1
        if not isinstance(names, list) or len(names) != target_columns:
            names = [f"component_{index + 1}" for index in range(target_columns)]
        target_context = TargetContext(
            target_type="continuous",
            target_name="synthetic concentration",
            target_names=[str(name) for name in names],
            target_units=_optional_text(synthetic_payload.get("concentration_units")),
        )
        extra.update(
            {
                "synthetic.metadata": dict(embedded_metadata),
                "recipe": recipe,
                "ground_truth": ground_truth,
                "ground_truth.spectra": ground_truth_spectra,
                "ground_truth.spectra_names": [str(name) for name in names],
                "ground_truth.spectra_units": ground_truth.get("S_units"),
                "ground_truth.spectra_x": ground_truth_axis,
                "ground_truth.spectra_x_title": _optional_text(embedded_metadata.get("x_title")),
                "ground_truth.spectra_x_units": (
                    _optional_text(embedded_metadata.get("x_units"))
                    or _optional_text(synthetic_payload.get("feature_units"))
                ),
                "ground_truth.component_ids": ground_truth.get("component_ids"),
                "value_units_label": _optional_text(embedded_metadata.get("value_units"))
                or _optional_text(synthetic_payload.get("units")),
            }
        )

    return SherpaDataset(
        X=data,
        feature_axis=feature_axis,
        sample_axis=(
            SampleAxis(labels=labels, title=_optional_text(embedded_metadata.get("y_title")) or "Samples")
            if labels
            else None
        ),
        target=target,
        target_context=target_context,
        domain=DomainContext(
            technique=embedded_technique,
            data_quantity=_optional_text(embedded_metadata.get("data_quantity")),
        ),
        title=_optional_text(embedded_metadata.get("title")) or path.stem,
        units=(
            _optional_text(embedded_metadata.get("value_units"))
            or (_optional_text(synthetic_payload.get("units")) if synthetic_payload is not None else None)
        ),
        extra=extra,
        data_role=_optional_text(embedded_metadata.get("data_role")) or derive_data_role(feature_axis),
        is_time_series=bool(embedded_metadata.get("is_time_series", False)),
    )


def _array_header(stream: BinaryIO, *, format_id: str) -> tuple[tuple[int, ...], np.dtype]:
    try:
        version = npformat.read_magic(stream)
        if version == (1, 0):
            shape, _fortran, dtype = npformat.read_array_header_1_0(stream)
        elif version in {(2, 0), (3, 0)}:
            shape, _fortran, dtype = npformat.read_array_header_2_0(stream)
        else:
            raise ValueError(f"unsupported NPY version {version}")
    except Exception as exc:
        raise UnreadableSpectrumError(format_id=format_id, detail=f"invalid NPY header: {exc}") from exc
    if dtype.hasobject:
        raise UnreadableSpectrumError(format_id=format_id, detail="object arrays are not permitted")
    return tuple(int(value) for value in shape), dtype


def _element_count(shape: tuple[int, ...]) -> int:
    count = 1
    for dimension in shape:
        if dimension < 0:
            raise ValueError("negative array dimension")
        count *= dimension
    return count


def _declared_array_bytes(*, name: str, shape: tuple[int, ...], dtype: np.dtype) -> int:
    """Return the bounded decoded footprint for one admitted NumPy member."""

    if dtype.hasobject or dtype.fields is not None or dtype.subdtype is not None:
        raise UnreadableSpectrumError(format_id="numpy", detail=f"array {name!r} has unsupported dtype {dtype}")
    if np.issubdtype(dtype, np.complexfloating):
        raise UnreadableSpectrumError(
            format_id="numpy",
            detail=f"array {name!r} is complex; project magnitude, phase, real, or imaginary values explicitly",
        )
    numeric = np.issubdtype(dtype, np.number) and not np.issubdtype(dtype, np.bool_)
    text_metadata = name in _NPZ_TEXT_METADATA_KEYS and dtype.kind in {"S", "U"}
    if not numeric and not text_metadata:
        raise UnreadableSpectrumError(format_id="numpy", detail=f"array {name!r} has unsupported dtype {dtype}")
    itemsize = int(dtype.itemsize)
    if numeric:
        # Numeric payloads are projected to float64 by the canonical loader.
        itemsize = max(itemsize, np.dtype(np.float64).itemsize)
    return _element_count(shape) * itemsize


class NumpyPlugin:
    format_id = "numpy"
    display_name = "NumPy"
    description = "Numeric arrays and explicit X payloads"
    extensions = (".npy", ".npz")
    parser_id = "spectrasherpa.numpy"
    parser_version = "2"

    def probe(self, source: BoundedSource) -> ProbeResult:
        prefix = source.read_at(0, min(source.size_bytes, 8), format_id=self.format_id)
        if prefix.startswith(b"\x93NUMPY"):
            return ProbeResult(self.format_id, "npy", ProbeConfidence.EXACT, ("NPY magic",), len(prefix))
        if prefix.startswith(b"PK\x03\x04"):
            return ProbeResult(self.format_id, "npz", ProbeConfidence.EXACT, ("ZIP local header",), len(prefix))
        return ProbeResult(self.format_id, None, ProbeConfidence.NO_MATCH, bytes_inspected=len(prefix))

    def _variant(self, source: BoundedSource) -> str:
        prefix = source.read_at(0, min(source.size_bytes, 8), format_id=self.format_id)
        if prefix.startswith(b"\x93NUMPY"):
            variant = "npy"
            expected_extension = ".npy"
        elif prefix.startswith(b"PK\x03\x04"):
            variant = "npz"
            expected_extension = ".npz"
        else:  # pragma: no cover - registry selection already proves this identity
            raise FormatIdentityError("NumPy parser received bytes without NPY or NPZ structural identity")
        if source.extension != expected_extension:
            raise FormatIdentityError(
                f"NumPy {variant.upper()} bytes contradict filename extension {source.extension or '<none>'}; "
                f"rename the file to {expected_extension} without changing its contents"
            )
        return variant

    def _validate_declared_arrays(self, source: BoundedSource, variant: str) -> None:
        if variant == "npy":
            with source.snapshot_path.open("rb") as stream:
                shape, dtype = _array_header(stream, format_id=self.format_id)
            count = _element_count(shape)
            source.require_elements(count, format_id=self.format_id)
            source.require_decoded_bytes(
                _declared_array_bytes(name="array", shape=shape, dtype=dtype),
                format_id=self.format_id,
            )
            return
        try:
            with zipfile.ZipFile(source.snapshot_path) as archive:
                infos = archive.infolist()
                source.require_blocks(len(infos), format_id=self.format_id)
                source.require_metadata_bytes(
                    sum(len(info.filename.encode("utf-8")) for info in infos), format_id=self.format_id
                )
                npy_infos = [info for info in infos if info.filename.endswith(".npy")]
                if not npy_infos:
                    raise UnreadableSpectrumError(
                        format_id=self.format_id, detail="NPZ archive contains no NPY members"
                    )
                declared_elements = 0
                declared_bytes = 0
                for info in npy_infos:
                    if info.flag_bits & 0x1:
                        raise UnreadableSpectrumError(
                            format_id=self.format_id, detail="encrypted NPZ members are not permitted"
                        )
                    with archive.open(info) as member:
                        header = io.BytesIO(member.read(min(info.file_size, 64 * 1024)))
                    shape, dtype = _array_header(header, format_id=self.format_id)
                    declared_elements += _element_count(shape)
                    member_name = info.filename.rsplit("/", 1)[-1].removesuffix(".npy")
                    declared_bytes += _declared_array_bytes(name=member_name, shape=shape, dtype=dtype)
                source.require_elements(declared_elements, format_id=self.format_id)
                source.require_decoded_bytes(declared_bytes, format_id=self.format_id)
        except zipfile.BadZipFile as exc:
            raise UnreadableSpectrumError(format_id=self.format_id, detail="invalid NPZ ZIP structure") from exc

    def _classify_npz_assets(self, source: BoundedSource) -> tuple[str, ...]:
        """Enforce the current single-asset NPZ schema without silent selection."""
        try:
            with np.load(source.snapshot_path, allow_pickle=False) as payload:
                data_key = next(
                    (
                        candidate
                        for candidate in ("X", "data", "spectra", "y", "intensity", "absorbance")
                        if candidate in payload
                    ),
                    None,
                )
                numeric_keys = []
                for key in payload.files:
                    array = np.asarray(payload[key])
                    if np.issubdtype(array.dtype, np.number) and 1 <= array.ndim <= 2:
                        numeric_keys.append(key)
                if data_key is None and len(numeric_keys) == 1:
                    data_key = numeric_keys[0]
                auxiliary = tuple(sorted(key for key in numeric_keys if key != data_key and key in _NPZ_AUXILIARY_KEYS))
                extras = sorted(
                    key
                    for key in numeric_keys
                    if key != data_key and key not in _NPZ_METADATA_KEYS and key not in _NPZ_AUXILIARY_KEYS
                )
                if extras:
                    raise UnreadableSpectrumError(
                        format_id=self.format_id,
                        detail=(
                            "NPZ contains additional numeric assets that cannot be silently "
                            f"selected or flattened: {', '.join(extras)}"
                        ),
                    )
                return auxiliary
        except UnreadableSpectrumError:
            raise
        except Exception as exc:
            raise UnreadableSpectrumError(format_id=self.format_id, detail=source.exception_detail(exc)) from exc

    def read(
        self,
        source: BoundedSource,
        *,
        limits: ParserLimits,
        parser_options: Mapping[str, str] | None = None,
    ) -> IngestionResult:
        if parser_options:
            raise UnsupportedFormatVariantError("NumPy does not admit parser options")
        del limits
        variant = self._variant(source)
        self._validate_declared_arrays(source, variant)
        auxiliary_arrays = self._classify_npz_assets(source) if variant == "npz" else ()
        try:
            dataset = _load_numpy_dataset(source.snapshot_path)
        except Exception as exc:
            raise UnreadableSpectrumError(format_id=self.format_id, detail=source.exception_detail(exc)) from exc
        source.require_elements(int(dataset.X.size), format_id=self.format_id)
        dataset.meta["source_file"] = source.path.name
        return ingestion_result(
            source=source,
            format_id=self.format_id,
            variant=variant,
            parser_id=self.parser_id,
            parser_version=self.parser_version,
            assets=(dataset_asset(dataset, asset_id="array"),),
            raw_metadata={"numpy.auxiliary_arrays": list(auxiliary_arrays)},
        )


PLUGIN = NumpyPlugin()
