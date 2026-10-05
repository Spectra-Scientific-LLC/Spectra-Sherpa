"""Sherpa-native MATLAB v4/v5 workspace ingestion."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import numpy as np
from scipy.io import loadmat, whosmat

from spectra_sherpa.app.lib.axes import FeatureAxis, SampleAxis, SpectralAxis
from spectra_sherpa.app.lib.sherpa_dataset import DomainContext, SherpaDataset
from spectra_sherpa.ingestion_errors import UnreadableSpectrumError, UnsupportedFormatVariantError
from spectra_sherpa.io.base import BoundedSource
from spectra_sherpa.io.formats._helpers import dataset_asset, ingestion_result
from spectra_sherpa.io.formats.dso import (
    DecodedDSO,
    decoded_dso_footprint,
    dso_float64_output_bytes,
    dso_image_cube_output_bytes,
    is_dso_field_set,
    map_decoded_dso,
    scipy_struct_fields,
)
from spectra_sherpa.io.formats.matlab_v73 import decode_matlab_v73
from spectra_sherpa.io.formats.process_log import (
    is_process_log_field_set,
    map_process_log,
    process_log_footprint,
)
from spectra_sherpa.io.types import IngestionResult, ParserLimits, ProbeConfidence, ProbeResult

_AXIS_NAMES = ("wavenumber", "wavenumbers", "wavelength", "wavelengths", "wn", "freq", "frequency", "x")
_DATA_NAMES = ("absorbance", "abs", "spectra", "spectrum", "intensity", "signal", "data", "matrix", "D", "X")
_MATLAB_V73_HEADER = b"MATLAB 7.3 MAT-file"
_HDF5_SIGNATURE = b"\x89HDF\r\n\x1a\n"
_MATLAB_HDF5_SIGNATURE_OFFSET = 512
_MATLAB_REAL_ITEMSIZE = {
    "double": 8,
    "single": 4,
    "int8": 1,
    "uint8": 1,
    "int16": 2,
    "uint16": 2,
    "int32": 4,
    "uint32": 4,
    "int64": 8,
    "uint64": 8,
    "logical": 1,
}


def _decoded_dso_assets(
    *,
    name: str,
    fields: Mapping[str, Any],
    storage_version: str,
    source: BoundedSource,
    parser_version: str,
) -> list[Any]:
    """Expose both pixel-table and cube views for an unfolded image DSO."""

    record = DecodedDSO(variable_name=name, fields=fields, storage_version=storage_version)
    dataset = map_decoded_dso(record, source=source, parser_version=parser_version)

    def asset(value: SherpaDataset, *, asset_id: str, object_type: str) -> Any:
        return dataset_asset(
            value,
            asset_id=asset_id,
            raw_metadata={
                "matlab.variable": name,
                "matlab.shape": list(value.layout.source_shape or value.shape),
                "matlab.object_type": object_type,
                "dataset_scientific_digest": value.scientific_digest,
            },
        )

    assets = [asset(dataset, asset_id=name, object_type="eigenvector-dso")]
    if dataset.layout.kind == "image" and dataset.ndim == 2:
        cube = map_decoded_dso(
            record,
            source=source,
            parser_version=parser_version,
            image_view="image-cube",
        )
        assets.append(
            asset(
                cube,
                asset_id=f"{name}:image-cube",
                object_type="eigenvector-dso-image-cube",
            )
        )
    return assets


def _element_count(shape: tuple[int, ...]) -> int:
    count = 1
    for dimension in shape:
        if dimension < 0:
            raise ValueError("negative MATLAB array dimension")
        count *= dimension
    return count


def _declared_workspace_bytes(*, name: str, shape: tuple[int, ...], kind: str) -> int:
    count = _element_count(shape)
    if kind in _MATLAB_REAL_ITEMSIZE:
        # whosmat does not expose the MATLAB complex flag.  Reserve twice the
        # real width before loadmat, then reject complex science explicitly.
        return count * max(8, 2 * _MATLAB_REAL_ITEMSIZE[kind])
    if kind == "char":
        return count * 4
    if kind in {"struct", "object"}:
        # whosmat cannot see nested struct payloads. The outer inventory is
        # still charged here; every decoded DSO array and metadata cell is
        # re-admitted against the same ParserLimits before dataset creation.
        return count * 64
    raise UnreadableSpectrumError(
        format_id="matlab",
        detail=f"variable {name!r} has unsupported MATLAB class {kind!r}",
    )


def _numeric_arrays(payload: dict[str, Any]) -> dict[str, np.ndarray]:
    arrays: dict[str, np.ndarray] = {}
    for name, value in payload.items():
        if name.startswith("__"):
            continue
        array = np.asarray(value)
        if np.issubdtype(array.dtype, np.number) and 1 <= array.ndim <= 2:
            if np.issubdtype(array.dtype, np.complexfloating):
                raise UnreadableSpectrumError(
                    format_id="matlab",
                    detail=(
                        f"variable {name!r} contains complex values; export magnitude, phase, "
                        "real, or imaginary values explicitly"
                    ),
                )
            arrays[name] = array.astype(np.float64, copy=False)
    return arrays


def _first_named(arrays: dict[str, np.ndarray], names: tuple[str, ...]) -> tuple[str, np.ndarray] | None:
    for name in names:
        if name in arrays:
            return name, arrays[name]
    lowered = {name.lower(): name for name in arrays}
    for candidate in names:
        resolved = lowered.get(candidate.lower())
        if resolved is not None:
            return resolved, arrays[resolved]
    return None


def _first_axis(arrays: dict[str, np.ndarray], *, excluded_name: str | None) -> tuple[str, np.ndarray] | None:
    """Resolve a one-dimensional spectral axis without stealing uppercase X data."""
    for name in _AXIS_NAMES:
        array = arrays.get(name)
        if name != excluded_name and array is not None and array.ndim == 1:
            return name, array
    lowered = {name.lower(): name for name in arrays if name != excluded_name}
    for candidate in _AXIS_NAMES:
        if candidate == "x":
            continue
        resolved = lowered.get(candidate.lower())
        if resolved is not None and arrays[resolved].ndim == 1:
            return resolved, arrays[resolved]
    return None


def _matlab_v73_identity(source: BoundedSource) -> tuple[bool, bool]:
    """Return declared-v7.3 and correctly placed HDF5-signature evidence."""
    header = source.read_at(0, min(source.size_bytes, 128), format_id="matlab")
    declared = _MATLAB_V73_HEADER in header[:116]
    has_hdf5 = False
    if source.size_bytes >= _MATLAB_HDF5_SIGNATURE_OFFSET + len(_HDF5_SIGNATURE):
        has_hdf5 = (
            source.read_at(
                _MATLAB_HDF5_SIGNATURE_OFFSET,
                len(_HDF5_SIGNATURE),
                format_id="matlab",
            )
            == _HDF5_SIGNATURE
        )
    return declared, has_hdf5


class MatlabPlugin:
    format_id = "matlab"
    display_name = "MATLAB"
    description = "MATLAB numeric arrays"
    extensions = (".mat",)
    parser_id = "spectrasherpa.matlab"
    parser_version = "6"

    def probe(self, source: BoundedSource) -> ProbeResult:
        prefix = source.read_at(0, min(source.size_bytes, 128), format_id=self.format_id)
        declared_v73, has_v73_hdf5 = _matlab_v73_identity(source)
        if declared_v73 and has_v73_hdf5:
            return ProbeResult(
                self.format_id,
                "mat-v7.3-hdf5",
                ProbeConfidence.EXACT,
                ("MATLAB 7.3 header and HDF5 signature at byte 512",),
                len(prefix) + len(_HDF5_SIGNATURE),
            )
        if declared_v73:
            return ProbeResult(
                self.format_id,
                "mat-v7.3-hdf5-invalid",
                ProbeConfidence.EXACT,
                ("MATLAB 7.3 header without the required HDF5 signature at byte 512",),
                len(prefix),
            )
        if prefix.startswith(b"MATLAB 5.0 MAT-file"):
            return ProbeResult(self.format_id, "mat-v5", ProbeConfidence.EXACT, ("MATLAB 5 header",), len(prefix))
        if source.extension == ".mat":
            return ProbeResult(
                self.format_id,
                "mat-v4-or-v5",
                ProbeConfidence.COMPATIBLE,
                ("MAT extension; structure revalidated by scipy.io.loadmat",),
                len(prefix),
            )
        return ProbeResult(self.format_id, None, ProbeConfidence.NO_MATCH, bytes_inspected=len(prefix))

    def _dataset(
        self,
        *,
        name: str,
        array: np.ndarray,
        axis: np.ndarray | None,
        source: BoundedSource,
    ) -> SherpaDataset:
        if array.ndim == 1:
            matrix = array.reshape(1, -1)
        else:
            matrix = array
        if axis is not None:
            flattened_axis = np.asarray(axis, dtype=np.float64).reshape(-1)
            if matrix.shape[-1] != flattened_axis.size and matrix.shape[0] == flattened_axis.size:
                matrix = matrix.T
            if matrix.shape[-1] != flattened_axis.size:
                raise UnreadableSpectrumError(
                    format_id=self.format_id,
                    detail=(
                        f"variable {name!r} shape {matrix.shape} does not align with "
                        f"{flattened_axis.size}-point spectral axis"
                    ),
                )
            feature_axis = SpectralAxis(values=flattened_axis, title=None, units=None)
            role = "X_spectra"
        else:
            feature_axis = FeatureAxis(labels=[str(index) for index in range(matrix.shape[-1])], title="Feature")
            role = "X_features"
        return SherpaDataset(
            X=np.asarray(matrix, dtype=np.float64),
            feature_axis=feature_axis,
            sample_axis=SampleAxis(labels=[str(index) for index in range(matrix.shape[0])], title="Sample"),
            domain=DomainContext(),
            title=f"{source.path.stem}:{name}",
            extra={"source_file": source.path.name, "source_type": "mat", "matlab.variable": name},
            data_role=role,
        )

    def read(
        self,
        source: BoundedSource,
        *,
        limits: ParserLimits,
        parser_options: Mapping[str, str] | None = None,
    ) -> IngestionResult:
        if parser_options:
            raise UnsupportedFormatVariantError("MATLAB does not admit parser options")
        del limits
        declared_v73, has_v73_hdf5 = _matlab_v73_identity(source)
        if declared_v73 and has_v73_hdf5:
            return self._read_v73(source)
        if declared_v73:
            raise UnreadableSpectrumError(
                format_id=self.format_id,
                detail="MATLAB v7.3 header is missing its HDF5 signature at byte offset 512",
                remediation="Re-export the workspace as MATLAB v5 from the original MATLAB session.",
            )
        try:
            inventory = whosmat(str(source.snapshot_path))
        except Exception as exc:
            raise UnreadableSpectrumError(format_id=self.format_id, detail=source.exception_detail(exc)) from exc
        source.require_blocks(len(inventory), format_id=self.format_id)
        source.require_metadata_bytes(
            sum(len(name.encode("utf-8")) for name, _shape, _kind in inventory),
            format_id=self.format_id,
        )
        declared_elements = sum(
            _element_count(tuple(int(value) for value in shape)) for _name, shape, _kind in inventory
        )
        source.require_elements(declared_elements, format_id=self.format_id)
        declared_bytes = sum(
            _declared_workspace_bytes(
                name=name,
                shape=tuple(int(value) for value in shape),
                kind=str(kind),
            )
            for name, shape, kind in inventory
        )
        source.require_decoded_bytes(declared_bytes, format_id=self.format_id)
        try:
            payload = loadmat(str(source.snapshot_path), squeeze_me=True, struct_as_record=False)
        except Exception as exc:
            raise UnreadableSpectrumError(format_id=self.format_id, detail=source.exception_detail(exc)) from exc
        dso_payload: dict[str, Any] = {}
        if any(str(kind) in {"struct", "object"} for _name, _shape, kind in inventory):
            try:
                dso_payload = loadmat(str(source.snapshot_path), squeeze_me=False, struct_as_record=True)
            except Exception as exc:
                raise UnreadableSpectrumError(format_id=self.format_id, detail=source.exception_detail(exc)) from exc
        arrays = _numeric_arrays(payload)
        dso_assets = []
        process_log_assets = []
        claimed_structs: set[str] = set()
        claimed_process_logs: set[str] = set()
        decoded_structs: list[tuple[str, Mapping[str, Any]]] = []
        decoded_process_logs: list[tuple[str, Mapping[str, Any]]] = []
        for name in sorted(dso_payload):
            if name.startswith("__"):
                continue
            value = dso_payload[name]
            if not isinstance(value, np.ndarray) or value.dtype.names is None:
                continue
            field_names = tuple(str(field).lower() for field in value.dtype.names)
            fields = scipy_struct_fields(value)
            if is_dso_field_set(field_names):
                claimed_structs.add(name)
                decoded_structs.append((name, fields))
            elif is_process_log_field_set(field_names):
                claimed_process_logs.add(name)
                decoded_process_logs.append((name, fields))
        footprints = [decoded_dso_footprint(fields) for _name, fields in decoded_structs]
        process_footprints = [process_log_footprint(fields) for _name, fields in decoded_process_logs]
        cube_output_bytes = sum(dso_image_cube_output_bytes(fields) for _name, fields in decoded_structs)
        source.require_elements(
            declared_elements
            + sum(item.elements for item in footprints)
            + sum(item.elements for item in process_footprints)
            + cube_output_bytes // np.dtype(np.float64).itemsize,
            format_id=self.format_id,
        )
        source.require_decoded_bytes(
            source.size_bytes
            + declared_bytes
            + sum(item.decoded_bytes for item in footprints)
            + sum(item.decoded_bytes for item in process_footprints)
            + sum(dso_float64_output_bytes(fields) for _name, fields in decoded_structs)
            + cube_output_bytes,
            format_id=self.format_id,
        )
        source.require_metadata_bytes(
            sum(len(name.encode("utf-8")) for name, _shape, _kind in inventory)
            + sum(item.metadata_bytes for item in footprints)
            + sum(item.metadata_bytes for item in process_footprints),
            format_id=self.format_id,
        )
        source.require_blocks(
            len(inventory) + sum(item.blocks for item in footprints) + sum(item.blocks for item in process_footprints),
            format_id=self.format_id,
        )
        for name, dso_fields in decoded_structs:
            dso_assets.extend(
                _decoded_dso_assets(
                    name=name,
                    fields=dso_fields,
                    storage_version="matlab-v5",
                    source=source,
                    parser_version=self.parser_version,
                )
            )
        for name, process_fields in decoded_process_logs:
            dataset = map_process_log(
                name=name,
                fields=process_fields,
                storage_version="matlab-v5",
                source=source,
                parser_version=self.parser_version,
            )
            process_log_assets.append(
                dataset_asset(
                    dataset,
                    asset_id=name,
                    raw_metadata={
                        "matlab.variable": name,
                        "matlab.shape": list(dataset.shape),
                        "matlab.object_type": "process-log",
                        "dataset_scientific_digest": dataset.scientific_digest,
                    },
                )
            )
        if not arrays and not dso_assets and not process_log_assets:
            raise UnreadableSpectrumError(
                format_id=self.format_id,
                detail="workspace contains no supported numeric arrays, Eigenvector DataSet Objects, or process logs",
            )
        data_entry = _first_named(arrays, _DATA_NAMES)
        data_name = data_entry[0] if data_entry is not None else None
        axis_entry = _first_axis(arrays, excluded_name=data_name)
        axis_name = axis_entry[0] if axis_entry is not None else None
        axis = axis_entry[1] if axis_entry is not None else None
        candidate_names = [name for name in sorted(arrays) if name != axis_name]
        if data_entry is not None and data_entry[0] in candidate_names:
            # Conventional data names establish a deterministic primary asset;
            # they must never cause other numeric workspace assets to disappear.
            candidate_names.remove(data_entry[0])
            candidate_names.insert(0, data_entry[0])
        if not candidate_names and not dso_assets and not process_log_assets:
            raise UnreadableSpectrumError(
                format_id=self.format_id, detail="workspace contains an axis but no data array"
            )

        assets = [*dso_assets, *process_log_assets]
        for name in candidate_names:
            array = arrays[name]
            source.require_elements(int(array.size), format_id=self.format_id)
            asset_axis = None
            if axis is not None and (array.shape[-1] == axis.size or (array.ndim == 2 and array.shape[0] == axis.size)):
                asset_axis = axis
            dataset = self._dataset(name=name, array=array, axis=asset_axis, source=source)
            assets.append(
                dataset_asset(
                    dataset,
                    asset_id=name,
                    raw_metadata={"matlab.variable": name, "matlab.shape": list(array.shape)},
                )
            )
        variant = "mat-v5" if source.probe_prefix().startswith(b"MATLAB 5.0 MAT-file") else "mat-v4-or-v5"
        result_metadata: dict[str, Any] = {
            "matlab.variables": sorted(name for name in payload if not name.startswith("__")),
        }
        if claimed_structs:
            result_metadata["matlab.dso_variables"] = sorted(claimed_structs)
        if claimed_process_logs:
            result_metadata["matlab.process_log_variables"] = sorted(claimed_process_logs)
        return ingestion_result(
            source=source,
            format_id=self.format_id,
            variant=variant,
            parser_id=self.parser_id,
            parser_version=self.parser_version,
            assets=tuple(assets),
            raw_metadata=result_metadata,
        )

    def _read_v73(self, source: BoundedSource) -> IngestionResult:
        payload = dict(decode_matlab_v73(source))
        dso_records: list[tuple[str, Mapping[str, Any]]] = []
        unimported_structs: list[str] = []
        for name in sorted(payload):
            value = payload[name]
            if isinstance(value, Mapping):
                if is_dso_field_set(tuple(str(field).lower() for field in value)):
                    dso_records.append((name, value))
                else:
                    unimported_structs.append(name)
        footprints = [decoded_dso_footprint(fields) for _name, fields in dso_records]
        cube_output_bytes = sum(dso_image_cube_output_bytes(fields) for _name, fields in dso_records)
        source.require_elements(
            sum(item.elements for item in footprints) + cube_output_bytes // np.dtype(np.float64).itemsize,
            format_id=self.format_id,
        )
        raw_numeric_bytes = sum(
            int(np.asarray(value).nbytes) for value in payload.values() if not isinstance(value, Mapping)
        )
        source.require_decoded_bytes(
            source.size_bytes
            + sum(item.decoded_bytes for item in footprints)
            + raw_numeric_bytes
            + sum(dso_float64_output_bytes(fields) for _name, fields in dso_records)
            + cube_output_bytes,
            format_id=self.format_id,
        )
        source.require_metadata_bytes(sum(item.metadata_bytes for item in footprints), format_id=self.format_id)
        source.require_blocks(sum(item.blocks for item in footprints), format_id=self.format_id)

        assets = []
        for name, fields in dso_records:
            assets.extend(
                _decoded_dso_assets(
                    name=name,
                    fields=fields,
                    storage_version="matlab-v7.3",
                    source=source,
                    parser_version=self.parser_version,
                )
            )

        arrays = _numeric_arrays({name: value for name, value in payload.items() if not isinstance(value, Mapping)})
        source.require_decoded_bytes(
            source.size_bytes
            + sum(item.decoded_bytes for item in footprints)
            + raw_numeric_bytes
            + sum(array.nbytes for array in arrays.values())
            + sum(dso_float64_output_bytes(fields) for _name, fields in dso_records)
            + cube_output_bytes,
            format_id=self.format_id,
        )
        data_entry = _first_named(arrays, _DATA_NAMES)
        data_name = data_entry[0] if data_entry is not None else None
        axis_entry = _first_axis(arrays, excluded_name=data_name)
        axis_name = axis_entry[0] if axis_entry is not None else None
        axis = axis_entry[1] if axis_entry is not None else None
        candidate_names = [name for name in sorted(arrays) if name != axis_name]
        if data_entry is not None and data_entry[0] in candidate_names:
            candidate_names.remove(data_entry[0])
            candidate_names.insert(0, data_entry[0])
        for name in candidate_names:
            array = arrays[name]
            source.require_elements(int(array.size), format_id=self.format_id)
            asset_axis = None
            if axis is not None and (array.shape[-1] == axis.size or (array.ndim == 2 and array.shape[0] == axis.size)):
                asset_axis = axis
            dataset = self._dataset(name=name, array=array, axis=asset_axis, source=source)
            assets.append(
                dataset_asset(
                    dataset,
                    asset_id=name,
                    raw_metadata={"matlab.variable": name, "matlab.shape": list(array.shape)},
                )
            )
        if not assets:
            raise UnreadableSpectrumError(
                format_id=self.format_id,
                detail="MATLAB v7.3 workspace contains no supported numeric arrays or Eigenvector DataSet Objects",
            )
        metadata: dict[str, Any] = {"matlab.variables": sorted(payload)}
        if dso_records:
            metadata["matlab.dso_variables"] = [name for name, _fields in dso_records]
        if unimported_structs:
            metadata["matlab.unimported_struct_variables"] = unimported_structs
        return ingestion_result(
            source=source,
            format_id=self.format_id,
            variant="mat-v7.3-hdf5",
            parser_id=self.parser_id,
            parser_version=self.parser_version,
            assets=tuple(assets),
            raw_metadata=metadata,
            warnings=(
                (
                    "Unsupported non-DSO MATLAB struct variable(s) were inventoried but not imported: "
                    + ", ".join(unimported_structs),
                )
                if unimported_structs
                else ()
            ),
        )


PLUGIN = MatlabPlugin()
