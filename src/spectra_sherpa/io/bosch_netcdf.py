"""Bounded BOSCH dictionary-encoded NetCDF4 ingestion (Zenodo 17122442).

The native reader inventories wafer groups without decoding matrices, then
uses netCDF4 to decode the selected wafer with a checksum-pinned dictionary.
The explicit SDK entry point also accepts a companion dictionary.
"""

from __future__ import annotations

import hashlib
import json
import re
import threading
from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from importlib.resources import files
from pathlib import Path

import h5py
import netCDF4
import numpy as np

from spectra_sherpa.app.lib.axes import FeatureAxis, SampleAxis, SpectralAxis
from spectra_sherpa.app.lib.sherpa_dataset import (
    DatasetLayoutContext,
    DatasetSourceIdentity,
    DomainContext,
    SherpaDataset,
)
from spectra_sherpa.ingestion_errors import IngestionError, UnreadableSpectrumError, UnsupportedFormatVariantError
from spectra_sherpa.io.base import BoundedSource
from spectra_sherpa.io.formats._helpers import dataset_asset, derive_data_role, ingestion_result
from spectra_sherpa.io.types import IngestionInventory, IngestionResult, ParserLimits, ProbeConfidence, ProbeResult

# netCDF-C is not thread safe; web previews execute in worker threads.
_NETCDF_LOCK = threading.RLock()

_FORMAT = "bosch-netcdf"
_GROUP = re.compile(r"(?:Day_\d{4}_\d{2}_\d{2}_)?Wafer_\d+")
_TIME_UNITS = "seconds since 1970-01-01 00:00:00 UTC"


def _fail(detail: str) -> UnreadableSpectrumError:
    return UnreadableSpectrumError(format_id=_FORMAT, detail=detail)


def _text(value: object) -> str:
    if isinstance(value, bytes):
        return value.decode("utf-8")
    if isinstance(value, str):
        return value
    raise _fail("Expected UTF-8 metadata text")


def _hard_object(group: h5py.Group, name: str) -> h5py.Group | h5py.Dataset:
    if not isinstance(group.get(name, getlink=True), h5py.HardLink):
        raise _fail(f"Required object {name!r} must be a local hard link")
    value = group[name]
    if isinstance(value, h5py.Dataset):
        if value.is_virtual or value.id.get_create_plist().get_external_count():
            raise _fail("Virtual datasets and external storage are not supported")
    return value


def _array(group: h5py.Group, name: str, *, ndim: int, kinds: str) -> h5py.Dataset:
    value = _hard_object(group, name)
    if not isinstance(value, h5py.Dataset) or value.ndim != ndim or value.dtype.kind not in kinds:
        raise _fail(f"{name!r} has an unsupported shape or dtype")
    return value


def _netcdf(file: h5py.File) -> None:
    if "netcdf=" not in _text(file.attrs.get("_NCProperties", "")):
        raise _fail("Expected a NetCDF4 container with _NCProperties")


def _preflight_links(file: h5py.File, source: BoundedSource) -> None:
    """Reject indirect/external storage before netCDF-C opens the container."""
    seen: set[int] = set()
    objects = 0

    def walk(group: h5py.Group, depth: int) -> None:
        nonlocal objects
        if depth > 32:
            raise _fail("NetCDF group nesting exceeds the supported schema")
        address = int(h5py.h5o.get_info(group.id).addr)
        if address in seen:
            raise _fail("Repeated or cyclic NetCDF groups are not supported")
        seen.add(address)
        for name in group:
            objects += 1
            source.require_blocks(objects, format_id=_FORMAT)
            child = _hard_object(group, name)
            if isinstance(child, h5py.Group):
                walk(child, depth + 1)

    walk(file, 0)


def _experiment_context(source: BoundedSource, group: str) -> dict:
    resource = files("spectra_sherpa").joinpath("data", "bosch_netcdf", "experiment_context.json")
    raw = resource.read_bytes()
    if hashlib.sha256(raw).hexdigest() != "af9de7f59b8bf29cbe4939f1a6a9bf99c15d2df587e8a07bcf6cd21cf6ad3ca6":
        raise _fail("Bundled experiment metadata failed its source checksum")
    catalog = json.loads(raw)
    # A filename or timestamp alone cannot establish a published lot identity.
    candidates = [item for item in catalog["published_sources"] if item["size_bytes"] == source.size_bytes]
    published = None
    if candidates:
        with source.snapshot_path.open("rb") as stream:
            digest = hashlib.file_digest(stream, "md5").hexdigest()
        published = next((item for item in candidates if item["md5"] == digest), None)
    selected_lot = None
    if published is not None:
        name = published["name"] if published["name"].startswith("Day_") else group
        date_match = re.match(r"Day_(\d{4})_(\d{2})_(\d{2})", name)
        if date_match:
            date = "-".join(date_match.groups())
            lot = catalog["lots_by_date"].get(date)
            if lot is not None:
                selected_lot = {
                    **lot,
                    "experiment_date": date,
                    "wafer_number": int(group.rsplit("_", 1)[1]),
                    "source_file": published["name"],
                    "source_md5": published["md5"],
                }
    return {
        "schema_version": "spectrasherpa.bosch-experiment-context/1",
        "source": catalog["source"],
        "initial_chamber_preparation": catalog["initial_chamber_preparation"],
        "conditioning_experiment": catalog["conditioning_experiment"],
        "production_lot": catalog["production_lot"],
        "selected_lot": selected_lot,
    }


@dataclass(frozen=True)
class _BoschPlugin:
    dictionary_path: Path
    group: str
    rows: slice
    format_id = _FORMAT
    parser_id = "spectrasherpa.bosch_netcdf"
    parser_version = "1.0.0"
    extensions = (".nc",)
    display_name = "BOSCH NetCDF4 (explicit companion dictionary)"
    description = "OES or process acquisitions from Zenodo 17122442"

    def probe(self, source: BoundedSource) -> ProbeResult:
        prefix = source.read_at(0, min(source.size_bytes, 8))
        matches = prefix == b"\x89HDF\r\n\x1a\n" and source.extension == ".nc"
        return ProbeResult(
            self.format_id,
            "dictionary-netcdf4" if matches else None,
            ProbeConfidence.EXACT if matches else ProbeConfidence.NO_MATCH,
            bytes_inspected=len(prefix),
        )

    def read(
        self, source: BoundedSource, *, limits: ParserLimits, parser_options: Mapping[str, str] | None = None
    ) -> IngestionResult:
        if parser_options:
            raise UnsupportedFormatVariantError("BOSCH reader options are explicit function arguments")
        with BoundedSource(self.dictionary_path, limits=limits) as dictionary:
            try:
                with h5py.File(dictionary.snapshot_path, "r") as lookup, h5py.File(source.snapshot_path, "r") as file:
                    _netcdf(lookup)
                    _netcdf(file)
                    _preflight_links(lookup, source)
                    _preflight_links(file, source)
                    source.require_blocks(len(file) + 8, format_id=_FORMAT)
                    table = _array(lookup, "data", ndim=1, kinds="f")
                    if not 1 <= table.size <= 65_536:
                        raise _fail("Dictionary must contain 1..65536 real entries")
                    source.require_decoded_bytes(int(table.size) * 8, format_id=_FORMAT)
                    # Disable NetCDF masking/scaling: these are dictionary indices,
                    # including valid zero and uint16 values, not intensities.
                    with (
                        _NETCDF_LOCK,
                        netCDF4.Dataset(dictionary.snapshot_path) as nc_lookup,
                        netCDF4.Dataset(source.snapshot_path) as nc_file,
                    ):
                        nc_lookup.set_auto_maskandscale(False)
                        nc_file.set_auto_maskandscale(False)
                        decoder = np.asarray(nc_lookup.variables["data"][:], dtype=np.float64)
                        dataset = self._decode(file, decoder, source, dictionary, nc_file)
                dataset.set_extra("bosch.experiment_context", _experiment_context(source, self.group))
                dictionary.verify_unchanged()
            except (OSError, ValueError, KeyError, UnicodeError, RuntimeError, OverflowError) as exc:
                # Preserve typed resource/schema errors; redact filesystem paths.
                if isinstance(exc, IngestionError):
                    raise
                raise _fail(source.exception_detail(exc)) from exc
            result = ingestion_result(
                source=source,
                format_id=self.format_id,
                variant="dictionary-netcdf4",
                parser_id=self.parser_id,
                parser_version=self.parser_version,
                assets=(
                    dataset_asset(
                        dataset, asset_id=self.group, warnings=tuple(dataset.get_extra("bosch.time_warnings") or ())
                    ),
                ),
            )
            return replace(result, source_members=(source.member(), dictionary.member()))

    def _decode(
        self,
        file: h5py.File,
        decoder: np.ndarray,
        source: BoundedSource,
        dictionary: BoundedSource,
        nc_file: netCDF4.Dataset,
    ) -> SherpaDataset:
        if not _GROUP.fullmatch(self.group):
            raise _fail("Select an explicit Wafer_NN or Day_YYYY_MM_DD_Wafer_NN group")
        group = _hard_object(file, self.group)
        if not isinstance(group, h5py.Group):
            raise _fail("Selected wafer must be a NetCDF group")
        encoded = _array(group, "data", ndim=2, kinds="u")
        times = _array(group, "times", ndim=1, kinds="f")
        if encoded.dtype.itemsize != 2 or 0 in encoded.shape or times.shape != (encoded.shape[0],):
            raise _fail("Expected uint16 time-by-feature codes and one timestamp per acquisition")
        if _text(times.attrs.get("units", "")) != _TIME_UNITS:
            raise _fail("Unsupported timestamp origin/units; timestamps cannot be silently reinterpreted")
        if _text(times.attrs.get("calendar", "standard")) not in {"standard", "gregorian"}:
            raise _fail("Unsupported timestamp calendar")
        start, stop, step = self.rows.indices(encoded.shape[0])
        indices = range(start, stop, step)
        count, features = len(indices), encoded.shape[1]
        source.require_blocks(features + 8, format_id=_FORMAT)
        if not count:
            raise _fail("Row selection is empty")
        source.require_elements(count * features + count + decoder.size + features, format_id=_FORMAT)
        chunk_rows = max(1, min(count, 1_000_000 // features))
        footprint = (count * features + count + decoder.size + features) * 8 + chunk_rows * features * 10
        source.require_decoded_bytes(footprint, format_id=_FORMAT)
        source.require_metadata_bytes(count * 200 + features * 64, format_id=_FORMAT)
        wavelengths = group.get("wavelengths", getlink=True)
        if wavelengths is not None:
            axis_data = _array(group, "wavelengths", ndim=1, kinds="f")
            if axis_data.shape != (features,):
                raise _fail("Wavelength count does not match encoded channels")
            values = np.asarray(nc_file.groups[self.group].variables["wavelengths"][:], dtype=np.float64)
            if not np.isfinite(values).all() or not np.all(np.diff(values) > 0):
                raise _fail("OES wavelengths must be finite and strictly increasing")
            feature_axis = SpectralAxis(values=values, units="nm", title="Wavelength")
            domain = DomainContext(technique="OES", data_quantity="Intensity")
            roles = ("sample", "spectral_feature")
        else:
            labels = _array(group, "feature", ndim=1, kinds="OSU")
            if labels.shape != (features,):
                raise _fail("Process feature names do not match encoded channels")
            names = []
            metadata_bytes = count * 200
            for index in range(features):
                name = _text(nc_file.groups[self.group].variables["feature"][index])
                metadata_bytes += len(name.encode("utf-8"))
                source.require_metadata_bytes(metadata_bytes, format_id=_FORMAT)
                if not name or len(name.encode("utf-8")) > 4096:
                    raise _fail("Process feature names must be bounded non-empty strings")
                names.append(name)
            if len(set(names)) != features:
                raise _fail("Process feature names must be unique")
            feature_axis = FeatureAxis(labels=names, title="Process parameter")
            domain = DomainContext(data_quantity="Process value")
            roles = ("sample", "feature")
        nc_group = nc_file.groups[self.group]
        X = np.empty((count, features), dtype=np.float64)
        for offset in range(0, count, chunk_rows):
            end = min(offset + chunk_rows, count)
            codes = np.asarray(
                nc_group.variables["data"][start + offset * step : min(start + end * step, stop) : step, :]
            )
            if codes.size and int(codes.max()) >= decoder.size:
                raise _fail("Encoded value exceeds the supplied dictionary; no clipping or wrapping is permitted")
            X[offset:end] = decoder[codes]
        timestamps = np.asarray(nc_group.variables["times"][start:stop:step], dtype=np.float64)
        if not np.isfinite(timestamps).all():
            raise _fail("Acquisition timestamps must be finite")
        time_warnings = []
        absolute_time = True
        date_match = re.match(r"Day_(\d{4})_(\d{2})_(\d{2})", self.group)
        if date_match:
            expected_date = "-".join(date_match.groups())
            absolute_time = (
                datetime.fromtimestamp(float(timestamps[0]), timezone.utc).date().isoformat() == expected_date
            )
            if not absolute_time:
                time_warnings.append(
                    "Process time values conflict with the declared Unix epoch and wafer date. "
                    "Raw source seconds are preserved; an absolute clock or OES alignment is not established."
                )
        identity = f"{source.member().sha256}:{dictionary.member().sha256}:{self.group}"
        return SherpaDataset(
            X=X,
            feature_axis=feature_axis,
            sample_axis=SampleAxis(
                values=timestamps,
                units="s",
                title="Acquisition time (Unix UTC seconds)" if absolute_time else "Source time (s; origin unverified)",
                labels=[
                    f"{self.group}:{row} · "
                    + (
                        datetime.fromtimestamp(float(t), timezone.utc).isoformat(timespec="microseconds")
                        if absolute_time
                        else f"source time {float(t):.6f} s"
                    )
                    for row, t in zip(indices, timestamps)
                ],
                sample_table={
                    "sample_id": [f"{identity}:{row}" for row in indices],
                },
            ),
            domain=domain,
            data_role=derive_data_role(feature_axis),
            source_identity=DatasetSourceIdentity(source_format=_FORMAT, object_name=self.group),
            layout=DatasetLayoutContext(source_type=_FORMAT, source_shape=tuple(X.shape), mode_roles=roles),
            title=f"{source.path.name}:{self.group}",
            is_time_series=True,
            extra={
                "bosch.timestamp_units": _TIME_UNITS,
                "bosch.time_warnings": time_warnings,
                "bosch.timestamp_calendar": "standard",
                "bosch.original_shape": list(encoded.shape),
                "bosch.source_row_slice": [start, stop, step],
            },
        )


def read_bosch_netcdf(
    path: str | Path,
    *,
    dictionary_path: str | Path,
    group: str,
    rows: slice | None = None,
    limits: ParserLimits | None = None,
) -> SherpaDataset:
    """Decode one wafer, retaining acquisition order, timestamps and provenance.

    Use Dictionary_OES.nc for Day_*.nc, Dictionary_process.nc for Process_data.nc.
    ``rows`` is an explicit positive-stride source-row slice, never an inferred
    process-phase filter. Values are dictionary-decoded without averaging.
    Large day files require an explicit ``ParserLimits(max_source_bytes=...)``;
    allocation bounds still apply to the selected decoded wafer or row slice.
    Process channels retain their source names; undocumented intensity/process
    units are not invented. Classic NetCDF3 and other schemas are unsupported.
    """
    selected = rows if rows is not None else slice(None)
    if not isinstance(selected, slice) or any(
        value is not None and (type(value) is not int) for value in (selected.start, selected.stop, selected.step)
    ):
        raise ValueError("rows must be a slice of exact integer indices")
    if selected.step is not None and selected.step <= 0:
        raise ValueError("rows must have a positive step")
    from spectra_sherpa.io.registry import FormatRegistry

    plugin = _BoschPlugin(Path(dictionary_path), group, selected)
    result = FormatRegistry((plugin,)).ingest(path, limits=limits)
    return result.assets[0].dataset


__all__ = ["read_bosch_netcdf"]


class _BuiltinBoschPlugin:
    format_id = _FORMAT
    parser_id = "spectrasherpa.bosch_netcdf.builtin"
    parser_version = "1.0.0"
    extensions = (".nc",)
    display_name = "BOSCH NetCDF4"
    description = "Dictionary-decoded OES/process wafers with acquisition times (Zenodo 17122442)"
    max_source_bytes = 512 * 1024**2
    selective_assets = True

    def probe(self, source: BoundedSource) -> ProbeResult:
        return _BoschPlugin(Path(), "", slice(None)).probe(source)

    def inspect(
        self, source: BoundedSource, *, limits: ParserLimits, parser_options: Mapping[str, str] | None = None
    ) -> IngestionInventory:
        try:
            return self._inspect(source, limits=limits, parser_options=parser_options)
        except IngestionError:
            raise
        except (OSError, ValueError, KeyError, UnicodeError, RuntimeError) as exc:
            raise _fail(source.exception_detail(exc)) from exc

    def _inspect(
        self, source: BoundedSource, *, limits: ParserLimits, parser_options: Mapping[str, str] | None = None
    ) -> IngestionInventory:
        if parser_options:
            raise UnsupportedFormatVariantError("BOSCH inventory does not admit parser options")
        assets = []
        with h5py.File(source.snapshot_path, "r") as file:
            _netcdf(file)
            _preflight_links(file, source)
            source.require_blocks(len(file) * 8, format_id=_FORMAT)
            for name in sorted(file):
                if not _GROUP.fullmatch(name):
                    raise _fail("Expected only wafer acquisition groups in the NetCDF source")
                group = _hard_object(file, name)
                if not isinstance(group, h5py.Group):
                    raise _fail("Wafer must be a group")
                data = _array(group, "data", ndim=2, kinds="u")
                times = _array(group, "times", ndim=1, kinds="f")
                if data.dtype.itemsize != 2 or times.shape != (data.shape[0],) or 0 in data.shape:
                    raise _fail("Malformed wafer codes/timestamps")
                oes = "wavelengths" in group
                coordinate = _array(group, "wavelengths" if oes else "feature", ndim=1, kinds="f" if oes else "OSU")
                if coordinate.shape != (data.shape[1],):
                    raise _fail("Channel coordinates do not match the wafer matrix")
                assets.append(
                    {
                        "asset_id": name,
                        "title": f"{name} · acquisition times",
                        "shape": list(data.shape),
                        "dimension_roles": ["sample", "spectral_feature" if oes else "feature"],
                        "data_role": "X_spectra" if oes else "X_features",
                        "x_title": "Wavelength" if oes else "Process parameter",
                        "x_units": "nm" if oes else None,
                        "data_quantity": None,
                        "value_units": None,
                        "warnings": [],
                    }
                )
        if not assets:
            raise _fail("No wafer acquisition groups were found")
        return IngestionInventory(
            self.format_id, "dictionary-netcdf4", self.parser_id, self.parser_version, (source.member(),), tuple(assets)
        )

    def read(
        self, source: BoundedSource, *, limits: ParserLimits, parser_options: Mapping[str, str] | None = None
    ) -> IngestionResult:
        return self.read_asset(source, limits=limits, parser_options=parser_options, asset_id=None)

    def read_asset(
        self,
        source: BoundedSource,
        *,
        limits: ParserLimits,
        parser_options: Mapping[str, str] | None = None,
        asset_id: str | None = None,
    ) -> IngestionResult:
        import hashlib
        from importlib.resources import files

        inventory = self.inspect(source, limits=limits, parser_options=parser_options)
        if asset_id is None:
            if len(inventory.assets) != 1:
                raise _fail("This file contains multiple wafers; select a wafer asset explicitly")
            asset_id = inventory.assets[0]["asset_id"]
        if asset_id not in {asset["asset_id"] for asset in inventory.assets}:
            raise _fail("Selected wafer is not present in the NetCDF file")
        oes = next(asset["data_role"] == "X_spectra" for asset in inventory.assets if asset["asset_id"] == asset_id)
        name = "Dictionary_OES.nc" if oes else "Dictionary_process.nc"
        expected = {
            "Dictionary_OES.nc": "238b8a9a76f4c3ffd0355864e0415c94aca6ec8d36a7b84e13f1240d3784f2bd",
            "Dictionary_process.nc": "51c9bebfad14f0a0558bf8e5831579b6a3308a2ff5b330ae5b8f8f32bc4b4302",
        }[name]
        dictionary = files("spectra_sherpa").joinpath("data", "bosch_netcdf", name)
        if hashlib.sha256(dictionary.read_bytes()).hexdigest() != expected:
            raise _fail("Bundled BOSCH dictionary failed its source checksum")
        from importlib.resources import as_file

        with as_file(dictionary) as dictionary_path:
            result = _BoschPlugin(dictionary_path, asset_id, slice(None)).read(source, limits=limits)
        for asset in result.assets:
            asset.dataset.set_extra("bosch.dictionary_sha256", expected)
        return replace(
            result, parser_id=self.parser_id, parser_version=self.parser_version, source_members=(source.member(),)
        )


PLUGIN = _BuiltinBoschPlugin()
