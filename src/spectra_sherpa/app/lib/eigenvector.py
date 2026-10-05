"""
Eigenvector Research public dataset parser and catalog.

Handles the Eigenvector DataSet CSV and .mat export formats used by
the public benchmark datasets at https://eigenvector.com/resources/data-sets/

Usage::

    from spectra_sherpa.app.lib.eigenvector import load_eigenvector_dataset, DATASET_CATALOG

    result = load_eigenvector_dataset("diesel_nir")
    spectra = result["spectra"]       # (784, 401) numpy array
    props   = result["properties"]    # (784, 7) numpy array (with NaN)
    wl      = result["wavelengths"]   # (401,) numpy array [750..1550 nm]
"""

from __future__ import annotations

import hashlib
import logging
import os
import tempfile
import zipfile
from pathlib import Path
from typing import TYPE_CHECKING, Any

import numpy as np
import pandas as pd

from spectra_sherpa.app.lib.domain_flags import infer_is_spectra

if TYPE_CHECKING:
    from spectra_sherpa.app.lib.sherpa_dataset import SherpaDataset

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Data directories.
#
# Eigenvector Research datasets are cataloged here, but raw upstream data is
# not redistributed in the AGPL package and is never downloaded. Users obtain
# it from the upstream page and place it locally.
# ---------------------------------------------------------------------------

EIGENVECTOR_DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "eigenvector"
EIGENVECTOR_UPSTREAM_PAGE = "https://eigenvector.com/resources/data-sets/"
EIGENVECTOR_MAX_ARCHIVE_BYTES = 512 * 1024 * 1024
EIGENVECTOR_MAX_MEMBER_BYTES = 512 * 1024 * 1024

# ---------------------------------------------------------------------------
# Dataset catalog
# ---------------------------------------------------------------------------

FEATURED_DATASETS = {"diesel_nir", "corn_m5", "nir_shootout_cal1", "nir_shootout_test1", "metal_etch_oes"}

# Max traces sent in catalog `preview_spectra`. Mirrors the cap the upload
# path applies in `get_file_info` so the Inspect chart looks identical
# whether the user explores a reference catalog entry or a file they
# uploaded.
CATALOG_PREVIEW_MAX_TRACES = 20


def build_catalog_preview(
    spectra: np.ndarray,
    wavelengths: np.ndarray | None,
    *,
    max_traces: int = CATALOG_PREVIEW_MAX_TRACES,
) -> dict[str, Any] | None:
    """Build a JSON-safe `{spectra, wavelengths}` preview from a 2D array.

    Returns None when there is nothing meaningful to plot — caller can
    just skip setting the field on the info dict.

    Complex-valued arrays (e.g. raw NMR FIDs) are rejected rather than
    coerced; `complex` is not JSON-serialisable and silently shipping
    the real part would mis-render the spectrum.
    """
    if spectra is None or spectra.ndim != 2 or spectra.shape[0] == 0 or spectra.shape[1] == 0:
        return None
    if np.issubdtype(spectra.dtype, np.complexfloating):
        return None
    preview = spectra[:max_traces]
    safe = np.where(np.isfinite(preview), preview, None).tolist()
    payload: dict[str, Any] = {"spectra": safe}
    if wavelengths is not None and len(wavelengths) == spectra.shape[1]:
        payload["wavelengths"] = np.asarray(wavelengths, dtype=float).tolist()
    return payload


# ---------------------------------------------------------------------------
# Axis validation
# ---------------------------------------------------------------------------


def _validate_axis_monotonic(axis: np.ndarray, source: str = "") -> None:
    """Raise ValueError if axis values are not strictly monotonic.

    Spectral axes must be monotonically increasing or decreasing for
    interpolation and peak-finding to behave correctly.  Reversed axes
    (e.g. some JCAMP-DX exports) and axes with duplicate values both
    cause silent errors downstream.

    Args:
        axis: 1-D array of axis values.
        source: Descriptor used in the error message (file path, key, etc.)
    """
    if axis is None:
        return
    if not np.isfinite(axis).all():
        raise ValueError(f"Axis values in {source or 'selected source'} must be finite")
    if len(axis) < 2:
        return
    diffs = np.diff(axis)
    if np.all(diffs > 0) or np.all(diffs < 0):
        return  # strictly monotonic — OK
    src_label = f" in {source}" if source else ""
    if np.any(diffs == 0):
        raise ValueError(
            f"Axis values{src_label} contain duplicate entries "
            f"(first duplicate near index {int(np.argmax(diffs == 0))}). "
            "Each axis point must be unique for reliable interpolation."
        )
    raise ValueError(
        f"Axis values{src_label} are not monotonic (neither strictly increasing nor decreasing). "
        f"Non-monotonic axes cause incorrect interpolation and peak assignments. "
        f"First sign change near index {int(np.argmax(diffs[:-1] * diffs[1:] < 0))}."
    )


def _validate_selected_spectra_and_properties(
    spectra: np.ndarray,
    properties: np.ndarray | None,
) -> None:
    """Apply finite-X and missing-Y policy after the two source roles are known."""

    if spectra.ndim != 2 or not np.isfinite(spectra).all():
        raise ValueError("Selected Eigenvector spectral X must be a finite two-dimensional matrix")
    if properties is not None:
        if properties.ndim != 2 or properties.shape[0] != spectra.shape[0]:
            raise ValueError("Eigenvector property Y must align with the selected spectral rows")
        if np.isinf(properties).any():
            raise ValueError("Eigenvector property Y may contain missing NaN values, not infinity")


def _validate_paired_sample_ids(spectral_ids: list[str], property_ids: list[str]) -> None:
    """Require a one-to-one, ordered specimen join when paired source IDs exist."""

    for label, ids in (("spectra", spectral_ids), ("properties", property_ids)):
        if any(not str(sample_id).strip() for sample_id in ids) or len(set(ids)) != len(ids):
            raise ValueError(f"Eigenvector {label} specimen IDs must be nonempty and unique")
    if spectral_ids != property_ids:
        raise ValueError("Eigenvector spectra and properties have different specimen IDs")


DATASET_CATALOG: dict[str, dict[str, Any]] = {
    # --- SWRI Diesel NIR (CSV format) ---
    "diesel_nir": {
        "label": "Diesel NIR (784 samples, 401 wavelengths, 750-1550 nm)",
        "featured": True,
        "format": "csv",
        "archive_url": "https://eigenvector.com/wp-content/uploads/2019/06/SWRI_Diesel_NIR_CSV.zip",
        "spec_file": "diesel_csv/diesel_spec.csv",
        "prop_file": "diesel_csv/diesel_prop.csv",
        "spec_has_axisscale": True,
        "prop_names": ["BP50", "CN", "D4052", "FLASH", "FREEZE", "TOTAL", "VISC"],
        "technique": "NIR",
        "x_title": "Wavelength",
        "x_units": "nm",
        "source_scope": "complete_raw_corpus",
        "source_contract": "paired_dataset_csv",
        "related_registered_family": "prepared_d4052_gatest",
        "description": (
            "Near-infrared spectra of diesel fuels from Southwest Research Institute "
            "(U.S. Army sponsored). Reference properties include BP50 (boiling point), "
            "CN (cetane number), D4052 (density), FLASH (flash point), FREEZE (freezing "
            "temperature), TOTAL (total aromatics), and VISC (viscosity). Widely used "
            "for NIR calibration benchmarking and PLS regression development."
        ),
    },
    # --- SWRI Diesel NIR (.mat format) ---
    "diesel_nir_mat": {
        "label": "Diesel NIR .mat (784 samples, 401 wavelengths, 750-1550 nm)",
        "format": "mat",
        "archive_url": "https://eigenvector.com/wp-content/uploads/2019/06/SWRI_Diesel_NIR.zip",
        "mat_file": "diesel_nir_mat/SWRI_Diesel_NIR.mat",
        "spec_key": "diesel_spec",
        "prop_key": "diesel_prop",
        "prop_names": ["BP50", "CN", "D4052", "FLASH", "FREEZE", "TOTAL", "VISC"],
        "technique": "NIR",
        "x_title": "Wavelength",
        "x_units": "nm",
        "source_scope": "complete_raw_corpus",
        "source_contract": "single_dataset_mat_workspace",
        "related_registered_family": "prepared_d4052_gatest",
        "description": (
            "Near-infrared spectra of diesel fuels from Southwest Research Institute "
            "(U.S. Army sponsored). Reference properties include BP50 (boiling point), "
            "CN (cetane number), D4052 (density), FLASH (flash point), FREEZE (freezing "
            "temperature), TOTAL (total aromatics), and VISC (viscosity). Widely used "
            "for NIR calibration benchmarking and PLS regression development."
        ),
    },
}


_REGISTERED_DATASET_LOADERS: dict[str, dict[str, Any]] = {
    "corn_m5": {
        "projection_id": "public-corn-m5-moisture-v1",
        "format": "mat",
        "mat_file": "corn_mat/corn.mat",
        "featured": True,
    },
    "corn_mp5": {
        "projection_id": "public-corn-mp5-moisture-v1",
        "format": "mat",
        "mat_file": "corn_mat/corn.mat",
    },
    "corn_mp6": {
        "projection_id": "public-corn-mp6-moisture-v1",
        "format": "mat",
        "mat_file": "corn_mat/corn.mat",
    },
    "cgl_nir": {
        "projection_id": "public-cgl-nir-lactate-v1",
        "format": "mat",
        "mat_file": "cgl_nir_mat/CGL_nir.mat",
    },
    "nir_shootout_cal1": {
        "projection_id": "public-nir-shootout-cal1-assay-v1",
        "format": "mat",
        "mat_file": "nir_shootout_mat/nir_shootout_2002.mat",
        "featured": True,
    },
    "nir_shootout_cal2": {
        "projection_id": "public-nir-shootout-cal2-assay-v1",
        "format": "mat",
        "mat_file": "nir_shootout_mat/nir_shootout_2002.mat",
    },
    "nir_shootout_test1": {
        "projection_id": "public-nir-shootout-test1-assay-v1",
        "format": "mat",
        "mat_file": "nir_shootout_mat/nir_shootout_2002.mat",
        "featured": True,
    },
    "nir_shootout_test2": {
        "projection_id": "public-nir-shootout-test2-assay-v1",
        "format": "mat",
        "mat_file": "nir_shootout_mat/nir_shootout_2002.mat",
    },
    "metal_etch_oes": {
        "projection_id": "public-metal-etch-oes-v1",
        "format": "matlab_process_log",
        "mat_file": "metal_etch/OES_DATA.mat",
        "struct_key": "OESDATA",
        "axis_key": "wave_axis",
        "featured": True,
        "processing_disclosure": "Displayed observations are per-wafer time averages of the source measurements.",
    },
    "metal_etch_machine": {
        "projection_id": "public-metal-etch-machine-v1",
        "format": "matlab_process_log",
        "mat_file": "metal_etch/MACHINE_Data.mat",
        "struct_key": "LAMDATA",
        "axis_key": "variables",
        "processing_disclosure": "Displayed observations are per-wafer time averages of the source measurements.",
    },
    "metal_etch_rfm": {
        "projection_id": "public-metal-etch-rfm-v1",
        "format": "matlab_process_log",
        "mat_file": "metal_etch/RFM_DATA.mat",
        "struct_key": "RFMDATA",
        "axis_key": "variables",
        "processing_disclosure": "Displayed observations are per-wafer time averages of the source measurements.",
    },
}


def _bind_registered_artifacts(catalog: dict[str, dict[str, Any]]) -> None:
    """Build legacy loader adapters from the artifact and package authorities."""

    from spectra_sherpa.app.lib.reference_artifacts import (
        load_reference_artifact_registry,
        registered_artifact_acquisition,
    )
    from spectra_sherpa.app.lib.reference_dataset_packages import (
        load_reference_dataset_package_registry,
        package_view_projection,
    )

    registry = load_reference_artifact_registry()
    packages = load_reference_dataset_package_registry(artifact_registry=registry)
    for name, loader in _REGISTERED_DATASET_LOADERS.items():
        projection = registry.projection(str(loader["projection_id"])).as_dict()
        package_view = package_view_projection(str(loader["projection_id"]), registry=packages)
        if package_view is None:
            raise ValueError(f"Eigenvector loader {name!r} has no registered package view")
        acquisition = registered_artifact_acquisition(
            str(projection["artifact_id"]), str(projection["member_path"]), registry=registry
        )
        annotation = package_view["annotation_table"]
        entry = {key: value for key, value in loader.items() if key != "projection_id"}
        description = package_view["package_description"]
        if disclosure := loader.get("processing_disclosure"):
            description = f"{description} {disclosure}"
        entry.update(
            {
                "artifact_id": projection["artifact_id"],
                "artifact_projection_id": projection["projection_id"],
                "label": f'{package_view["package_title"]} — {package_view["view_label"]}',
                "spec_key": projection["object_name"],
                "prop_key": projection["target_object_name"],
                "prop_names": [field["name"] for field in annotation["fields"]] if annotation else None,
                "technique": projection["analysis"]["technique"],
                "n_samples": projection["n_samples"],
                "n_features": projection["n_features"],
                "x_title": projection["feature_axis_title"],
                "x_units": projection["feature_axis_units"],
                "description": description,
                "archive_url": acquisition["download_url"],
                "archive_expected_size_bytes": acquisition["archive_expected_size_bytes"],
                "archive_sha256": acquisition["archive_sha256"],
                "source_file_expected_size_bytes": acquisition["member_expected_size_bytes"],
                "source_file_sha256": acquisition["member_sha256"],
                "source_scope": (
                    "prepared_d4052_gatest_projection"
                    if str(projection["projection_id"]).startswith("public-diesel-")
                    else "registered_projection"
                ),
                "source_contract": "exact_registered_archive_member",
            }
        )
        catalog[name] = entry


_bind_registered_artifacts(DATASET_CATALOG)


# ---------------------------------------------------------------------------
# User-supplied runtime data cache
# ---------------------------------------------------------------------------


def _required_catalog_files(catalog: dict[str, Any]) -> list[str]:
    files: list[str] = []
    for key in ("spec_file", "prop_file", "mat_file"):
        value = catalog.get(key)
        if isinstance(value, str) and value:
            files.append(value)
    return files


def _missing_catalog_files(base_dir: Path, catalog: dict[str, Any]) -> list[str]:
    return [rel for rel in _required_catalog_files(catalog) if not (base_dir / rel).exists()]


def _missing_data_error(name: str, catalog: dict[str, Any], base_dir: Path, reason: str) -> FileNotFoundError:
    files = ", ".join(_required_catalog_files(catalog))
    archive = catalog.get("archive_url")
    archive_hint = (
        f" or its registered archive {_archive_cache_path(str(archive), base_dir).name} under {base_dir / '_archives'}"
        if archive
        else ""
    )
    return FileNotFoundError(
        "Eigenvector Research example data is no longer bundled with SpectraSherpa, and SpectraSherpa never "
        f"downloads it. Dataset {name!r} requires these upstream files: {files}. Obtain them yourself from "
        f"{EIGENVECTOR_UPSTREAM_PAGE} and place them under {base_dir}{archive_hint}. Detail: {reason}"
    )


def _archive_cache_path(url: str, base_dir: Path) -> Path:
    safe = "".join(ch if ch.isalnum() or ch in {".", "-", "_"} else "_" for ch in Path(url).name)
    if not safe.lower().endswith(".zip"):
        safe = f"{safe}.zip"
    return base_dir / "_archives" / safe


def _replace_if_missing(tmp_path: Path, destination: Path) -> None:
    if destination.exists():
        tmp_path.unlink(missing_ok=True)
        return
    try:
        tmp_path.replace(destination)
    except PermissionError:
        if destination.exists():
            tmp_path.unlink(missing_ok=True)
            return
        raise


def _extract_required_files(archive_path: Path, base_dir: Path, catalog: dict[str, Any]) -> None:
    required = _required_catalog_files(catalog)
    base_dir.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive_path) as archive:
        names = [name for name in archive.namelist() if not name.endswith("/") and "__MACOSX/" not in name]
        for rel in required:
            basename = Path(rel).name
            candidates = [name for name in names if Path(name).name == basename]
            if not candidates:
                raise FileNotFoundError(f"Archive {archive_path.name} does not contain {basename}")
            if len(candidates) != 1:
                raise ValueError(f"Archive {archive_path.name} contains ambiguous members named {basename}")
            info = archive.getinfo(candidates[0])
            maximum_bytes = EIGENVECTOR_MAX_MEMBER_BYTES
            if rel == required[0] and catalog.get("source_file_expected_size_bytes"):
                maximum_bytes = int(catalog["source_file_expected_size_bytes"])
            if info.file_size > maximum_bytes:
                raise ValueError(f"Archive member {basename} exceeds its admitted byte limit")
            target = base_dir / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            fd, tmp_name = tempfile.mkstemp(dir=target.parent, prefix=f".{target.name}.")
            tmp_path = Path(tmp_name)
            try:
                stored_bytes = 0
                with archive.open(candidates[0]) as source, os.fdopen(fd, "wb") as tmp:
                    while True:
                        chunk = source.read(1024 * 1024)
                        if not chunk:
                            break
                        stored_bytes += len(chunk)
                        if stored_bytes > maximum_bytes:
                            raise ValueError(f"Archive member {basename} exceeds its admitted byte limit")
                        tmp.write(chunk)
                if rel == required[0]:
                    _verify_registered_member_path(tmp_path, catalog)
                _replace_if_missing(tmp_path, target)
            except Exception:
                tmp_path.unlink(missing_ok=True)
                raise


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _verify_registered_member_path(member_path: Path, catalog: dict[str, Any]) -> None:
    if not catalog.get("source_file_sha256"):
        return
    if member_path.stat().st_size != catalog["source_file_expected_size_bytes"]:
        raise ValueError("extracted source size does not match its registered artifact member")
    if _file_sha256(member_path) != catalog["source_file_sha256"]:
        raise ValueError("extracted source digest does not match its registered artifact member")


def _verify_registered_member(base_dir: Path, catalog: dict[str, Any]) -> None:
    _verify_registered_member_path(base_dir / _required_catalog_files(catalog)[0], catalog)


def _verify_registered_archive(archive_path: Path, catalog: dict[str, Any]) -> None:
    """Verify governed archive bytes before opening the ZIP."""

    archive_sha256 = catalog.get("archive_sha256")
    if not archive_sha256:
        if archive_path.stat().st_size > EIGENVECTOR_MAX_ARCHIVE_BYTES:
            raise ValueError("archive exceeds its admitted byte limit")
        return
    if archive_path.stat().st_size != catalog["archive_expected_size_bytes"]:
        raise ValueError("archive size does not match its registered artifact")
    if _file_sha256(archive_path) != archive_sha256:
        raise ValueError("archive digest does not match its registered artifact")


def _ensure_runtime_data(name: str, catalog: dict[str, Any], base_dir: Path) -> None:
    """Admit user-supplied files, or extract a user-supplied registered archive.

    SpectraSherpa never downloads Eigenvector data. Users obtain it from the
    upstream page and place either the files or the registered archive locally.
    """
    missing = _missing_catalog_files(base_dir, catalog)
    if not missing:
        _verify_registered_member(base_dir, catalog)
        return
    url = str(catalog.get("archive_url") or "")
    archive_path = _archive_cache_path(url, base_dir) if url else None
    if archive_path is None or not archive_path.exists():
        raise _missing_data_error(name, catalog, base_dir, f"missing: {', '.join(missing)}")
    try:
        _verify_registered_archive(archive_path, catalog)
        _extract_required_files(archive_path, base_dir, catalog)
        _verify_registered_member(base_dir, catalog)
    except (zipfile.BadZipFile, OSError, FileNotFoundError, ValueError) as exc:
        raise _missing_data_error(name, catalog, base_dir, str(exc)) from exc

    still_missing = _missing_catalog_files(base_dir, catalog)
    if still_missing:
        raise _missing_data_error(name, catalog, base_dir, f"missing after extraction: {', '.join(still_missing)}")


def _resolve_dataset_dir(
    name: str,
    catalog: dict[str, Any],
    data_dir: Path | None,
    *,
    runtime_data_dir: Path | None,
) -> Path:
    if data_dir is not None:
        return data_dir
    if not _missing_catalog_files(EIGENVECTOR_DATA_DIR, catalog):
        return EIGENVECTOR_DATA_DIR
    if runtime_data_dir is None:
        raise _missing_data_error(name, catalog, EIGENVECTOR_DATA_DIR, "no application runtime cache was supplied")
    _ensure_runtime_data(name, catalog, runtime_data_dir)
    return runtime_data_dir


# ---------------------------------------------------------------------------
# CSV metadata extraction
# ---------------------------------------------------------------------------


def extract_csv_metadata(path: Path) -> dict[str, str]:
    """Extract metadata from Eigenvector CSV header rows (first 5 lines).

    Eigenvector CSV format stores metadata in fixed rows:
      Row 0: Name
      Row 1: Author
      Row 2: Date
      Row 3: Modification Date
      Row 4: Description
    """
    raw = pd.read_csv(path, header=None, dtype=str, na_filter=False, nrows=5)
    field_map = {0: "name", 1: "author", 2: "date", 3: "modification_date", 4: "description"}
    meta: dict[str, str] = {}
    for idx, key in field_map.items():
        if idx < len(raw) and raw.shape[1] > 1:
            val = str(raw.iloc[idx, 1]).strip().strip('"')
            if val:
                meta[key] = val
    return meta


# ---------------------------------------------------------------------------
# CSV parser
# ---------------------------------------------------------------------------


def parse_eigenvector_csv(
    path: Path,
    has_axisscale: bool = False,
    n_columns: int | None = None,
) -> tuple[np.ndarray, list[str], np.ndarray | None]:
    """Parse Eigenvector DataSet CSV export format.

    Eigenvector CSVs have:
      - Lines 1-5: metadata (Name, Author, Date, Modification Date, Description)
      - Lines 6-7: blank
      - Line 8: "Label" header
      - Line 9: column labels (for properties: BP50, CN, D4052, etc.)
      - Line 10 (optional): "Axisscale" row with numeric axis values
      - Lines 11+: data rows with sample IDs in column 2
      - Trailing commas create empty columns that must be stripped

    Args:
        path: Path to the Eigenvector CSV file.
        has_axisscale: Whether the file has an Axisscale row (True for spectra).
        n_columns: Override number of data columns to keep. If None, inferred
            from axisscale length or column header count.

    Returns:
        (data, sample_ids, axis_values)
        - data: 2D numpy float array (n_samples x n_features)
        - sample_ids: list of sample ID strings
        - axis_values: 1D numpy array of axis scale values, or None
    """
    raw = pd.read_csv(path, header=None, dtype=str, na_filter=False)

    axis_values = None
    data_start_row = 9

    if has_axisscale:
        axisscale_row = raw.iloc[9]
        if axisscale_row.iloc[0].strip('"') != "Axisscale":
            raise ValueError(f"Expected 'Axisscale' in row 9, got: {axisscale_row.iloc[0]!r}")
        axis_vals = []
        for v in axisscale_row.iloc[2:]:
            v = str(v).strip().rstrip(",")
            if v:
                axis_vals.append(float(v))
        axis_values = np.array(axis_vals)
        _validate_axis_monotonic(axis_values, source=str(path))
        if n_columns is None:
            n_columns = len(axis_vals)
        data_start_row = 10
    else:
        if n_columns is None:
            header_row = raw.iloc[8]
            headers = []
            for v in header_row.iloc[2:]:
                v = str(v).strip().strip('"').rstrip(",")
                if v:
                    headers.append(v)
            n_columns = len(headers)
        data_start_row = 9

    sample_ids: list[str] = []
    data_rows: list[list[float]] = []
    for idx in range(data_start_row, len(raw)):
        row = raw.iloc[idx]
        sample_id = str(row.iloc[1]).strip().strip('"')
        sample_ids.append(sample_id)

        vals: list[float] = []
        for v in row.iloc[2 : 2 + n_columns]:
            v = str(v).strip().rstrip(",")
            if v == "" or v.lower() == "nan":
                vals.append(np.nan)
            else:
                vals.append(float(v))
        data_rows.append(vals)

    data = np.array(data_rows)
    return data, sample_ids, axis_values


def load_eigenvector_csv_pair_as_sherpa(spec_path: Path, prop_path: Path) -> "SherpaDataset":
    """Join the native SWRI DataSet CSV pair without losing source semantics."""
    from spectra_sherpa.app.lib.axes import SampleAxis, SpectralAxis
    from spectra_sherpa.app.lib.sherpa_dataset import DomainContext, SherpaDataset, TargetContext

    spectra, specimen_ids, wavelengths = parse_eigenvector_csv(spec_path, has_axisscale=True)
    properties, property_ids, _ = parse_eigenvector_csv(prop_path, has_axisscale=False)
    _validate_selected_spectra_and_properties(spectra, properties)
    if wavelengths is None:
        raise ValueError("SWRI Diesel spectral CSV has no wavelength axis")
    _validate_paired_sample_ids(specimen_ids, property_ids)
    names = ["BP50", "CN", "D4052", "FLASH", "FREEZE", "TOTAL", "VISC"]
    if properties.shape[1] != len(names):
        raise ValueError("SWRI Diesel property CSV does not contain the governed seven-property schema")
    sample_table = {"sample_id": specimen_ids}
    sample_table.update(
        {
            name: [None if np.isnan(value) else float(value) for value in properties[:, index]]
            for index, name in enumerate(names)
        }
    )
    return SherpaDataset(
        X=spectra,
        feature_axis=SpectralAxis(values=wavelengths, title="Wavelength", units="nm"),
        sample_axis=SampleAxis(labels=specimen_ids, title="Specimen", sample_table=sample_table),
        target=properties,
        target_context=TargetContext(target_type="continuous", target_names=names),
        domain=DomainContext(technique="NIR"),
        title="SWRI Diesel NIR",
        data_role="X_spectra",
    )


def load_eigenvector_mat_pair_as_sherpa(
    path: Path,
    *,
    spec_key: str,
    prop_key: str,
    prop_names: list[str],
    x_title: str,
    x_units: str,
    technique: str,
) -> "SherpaDataset":
    """Join native spectral/property DSO assets while preserving missing targets."""
    from spectra_sherpa.app.lib.axes import SampleAxis, SpectralAxis
    from spectra_sherpa.app.lib.sherpa_dataset import DomainContext, TargetContext
    from spectra_sherpa.io import ingest

    result = ingest(path)
    assets = {asset.asset_id: asset.dataset for asset in result.assets}
    if spec_key not in assets or prop_key not in assets:
        raise ValueError(f"SWRI Diesel MAT must contain {spec_key!r} and {prop_key!r}")
    spectra = assets[spec_key]
    properties = assets[prop_key]
    if spectra.ndim != 2 or properties.ndim != 2 or spectra.n_samples != properties.n_samples:
        raise ValueError("SWRI Diesel spectra and property MAT objects do not have aligned two-dimensional rows")
    if properties.n_features != len(prop_names):
        raise ValueError("SWRI Diesel property MAT object does not contain the governed seven-property schema")
    if not np.isfinite(spectra.X).all():
        raise ValueError("SWRI Diesel spectral MAT object contains non-finite values")
    if np.isinf(properties.X).any():
        raise ValueError("SWRI Diesel property MAT object contains infinite values")

    spectral_samples = spectra.sample_axis
    property_samples = properties.sample_axis
    spectral_labels = list(spectral_samples.labels or []) if spectral_samples is not None else []
    property_labels = list(property_samples.labels or []) if property_samples is not None else []
    if spectral_labels and property_labels and spectral_labels != property_labels:
        raise ValueError("SWRI Diesel spectra and property MAT objects do not have identical specimen custody")
    labels = spectral_labels or property_labels or [str(index + 1) for index in range(spectra.n_samples)]

    source_axis = spectra.feature_axis
    if source_axis is None or source_axis.values is None:
        raise ValueError("SWRI Diesel spectral MAT object has no wavelength scale")
    axis_payload = source_axis.model_dump(mode="python")
    axis_payload.update(title=x_title, units=x_units, quantity="wavelength")
    feature_axis = SpectralAxis.model_validate(axis_payload)

    sample_payload = spectral_samples.model_dump(mode="python") if spectral_samples is not None else {}
    sample_table = dict(sample_payload.get("sample_table") or {})
    sample_table["sample_id"] = labels
    sample_table.update(
        {
            name: [None if np.isnan(value) else float(value) for value in properties.X[:, index]]
            for index, name in enumerate(prop_names)
        }
    )
    sample_payload.update(labels=labels, title="Specimen", sample_table=sample_table)

    dataset = spectra.copy()
    dataset.feature_axis = feature_axis
    dataset.sample_axis = SampleAxis.model_validate(sample_payload)
    dataset.target = properties.X.copy()
    dataset.target_context = TargetContext(target_type="continuous", target_names=prop_names)
    dataset.domain = DomainContext(technique=technique)
    dataset.title = "SWRI Diesel NIR"
    dataset.data_role = "X_spectra"
    return dataset


# ---------------------------------------------------------------------------
# .mat parser
# ---------------------------------------------------------------------------


def extract_mat_metadata(ds: Any) -> dict[str, str]:
    """Extract metadata fields from an Eigenvector .mat structured array.

    Eigenvector .mat DataSet objects store metadata in fields:
    name, author, date, description (all as nested arrays of strings).
    """
    meta: dict[str, str] = {}
    for field in ("name", "author", "date", "description"):
        try:
            raw = ds[field][0, 0]
            if raw.size > 0:
                val = str(raw.flat[0]).strip()
                if val:
                    meta[field] = val
        except (IndexError, KeyError, ValueError):
            pass
    return meta


def parse_eigenvector_mat(
    path: Path,
    spec_key: str,
    prop_key: str | None = None,
) -> tuple[np.ndarray, np.ndarray | None, np.ndarray | None, dict[str, str]]:
    """Parse Eigenvector DataSet .mat export format.

    Eigenvector .mat files contain structured arrays with fields:
    name, type, author, date, data, label, axisscale, title, etc.

    Args:
        path: Path to the .mat file.
        spec_key: Key for the spectral data (e.g., "m5spec").
        prop_key: Key for the properties data (e.g., "propvals"), or None.

    Returns:
        (spec_data, axis_values, prop_data, file_metadata)
        - spec_data: 2D numpy array (n_samples x n_features)
        - axis_values: 1D numpy array of axis scale, or None
        - prop_data: 2D numpy array of properties, or None
        - file_metadata: dict with name, author, date, description from .mat
    """
    # Catalogue compatibility delegates to the registered native MATLAB/DSO
    # reader. This function must not remain a second scientific parser.
    from spectra_sherpa.io import ingest

    result = ingest(path)
    assets = {asset.asset_id: asset for asset in result.assets}
    if spec_key not in assets:
        raise ValueError(f"Key '{spec_key}' not found in {path.name}. Available keys: {sorted(assets)}")
    if prop_key is not None and prop_key not in assets:
        raise ValueError(f"Key '{prop_key}' not found in {path.name}. Available keys: {sorted(assets)}")

    dataset = assets[spec_key].dataset
    spec_data = np.asarray(dataset.X)
    axis_values = (
        np.asarray(dataset.feature_axis.values, dtype=float)
        if dataset.feature_axis is not None and dataset.feature_axis.values is not None
        else None
    )
    if axis_values is not None:
        _validate_axis_monotonic(axis_values, source=f"{path.name}[{spec_key}]")
    prop_dataset = assets[prop_key].dataset if prop_key is not None else None
    prop_data = np.asarray(prop_dataset.X) if prop_dataset is not None else None
    _validate_selected_spectra_and_properties(spec_data, prop_data)
    if prop_dataset is not None:
        spectral_labels = None if dataset.sample_axis is None else dataset.sample_axis.labels
        property_labels = None if prop_dataset.sample_axis is None else prop_dataset.sample_axis.labels
        if (spectral_labels is None) != (property_labels is None):
            raise ValueError("Eigenvector MAT spectra and properties have unequal specimen label custody")
        if spectral_labels is not None and property_labels is not None:
            _validate_paired_sample_ids(list(spectral_labels), list(property_labels))
    file_metadata = {
        key: value
        for key, value in {
            "name": dataset.source_identity.object_name or dataset.title,
            "author": dataset.descriptive.authors[0] if dataset.descriptive.authors else None,
            "date": dataset.descriptive.raw_date_fields.get("date"),
            "description": dataset.descriptive.description,
        }.items()
        if value is not None
    }
    return spec_data, axis_values, prop_data, file_metadata


# ---------------------------------------------------------------------------
# Main loader
# ---------------------------------------------------------------------------


def load_eigenvector_dataset(
    name: str,
    data_dir: Path | None = None,
    *,
    runtime_data_dir: Path | None = None,
) -> dict[str, Any]:
    """Load an Eigenvector Research public dataset by name.

    Args:
        name: Dataset name from DATASET_CATALOG.
        data_dir: Override data directory (for testing or locally supplied
            upstream data). Defaults to the package data directory when present,
            otherwise the package data directory when present.
        runtime_data_dir: Application-owned cache of user-supplied files. Nothing
            is ever downloaded into it.

    Returns:
        Dict with keys:
        - spectra: 2D numpy float array (n_samples x n_features)
        - properties: 2D numpy float array or None
        - wavelengths: 1D numpy array or None
        - sample_ids: list of strings or None
        - prop_names: list of property column names or None
        - catalog_entry: the catalog dict for this dataset

    Raises:
        ValueError: If name is not in DATASET_CATALOG.
        FileNotFoundError: If data files are not found.
    """
    if name not in DATASET_CATALOG:
        raise ValueError(
            f"Unsupported Eigenvector dataset: {name!r}\n" f"Supported datasets: {', '.join(DATASET_CATALOG)}"
        )

    catalog = DATASET_CATALOG[name]
    base_dir = _resolve_dataset_dir(
        name,
        catalog,
        data_dir,
        runtime_data_dir=runtime_data_dir,
    )

    # Registered aliases must materialize through the same projection
    # authority used by uploaded reference packages.  Reconstructing a bare
    # X matrix here discarded targets, specimen identity, and sample roles.
    projection_id = catalog.get("artifact_projection_id")
    if isinstance(projection_id, str) and data_dir is None:
        from spectra_sherpa.app.lib.reference_materialization import materialize_reference_member

        member_path = base_dir / str(catalog["mat_file"])
        materialized = materialize_reference_member(member_path, projection_id)
        dataset = materialized.dataset
        axis = dataset.get_feature_axis()
        sample_axis = dataset.sample_axis
        return {
            "spectra": np.asarray(dataset.X),
            "properties": None if dataset.target is None else np.asarray(dataset.target),
            "wavelengths": None if axis is None or axis.values is None else np.asarray(axis.values),
            "sample_ids": None if sample_axis is None else list(sample_axis.labels or []),
            "sample_table": None if sample_axis is None else sample_axis.sample_table,
            "prop_names": dataset.target_context.target_names,
            "catalog_entry": catalog,
            "file_metadata": {
                "name": dataset.source_identity.object_name or dataset.title,
                "description": dataset.descriptive.description,
            },
            "dataset": dataset,
        }

    if catalog["format"] == "csv":
        spec_path = base_dir / catalog["spec_file"]
        if not spec_path.exists():
            raise FileNotFoundError(
                f"Eigenvector data file not found: {spec_path}\n"
                f"Download the dataset from {EIGENVECTOR_UPSTREAM_PAGE} and place it under {base_dir}."
            )

        spectra, sample_ids, wavelengths = parse_eigenvector_csv(
            spec_path, has_axisscale=catalog.get("spec_has_axisscale", False)
        )

        file_metadata = extract_csv_metadata(spec_path)

        properties = None
        dataset = None
        if "prop_file" in catalog:
            prop_path = base_dir / catalog["prop_file"]
            if not prop_path.exists():
                raise FileNotFoundError(f"Declared Eigenvector property data file not found: {prop_path}")
            properties, property_ids, _ = parse_eigenvector_csv(prop_path, has_axisscale=False)
            _validate_paired_sample_ids(sample_ids, property_ids)
            if name == "diesel_nir":
                dataset = load_eigenvector_csv_pair_as_sherpa(spec_path, prop_path)

        _validate_selected_spectra_and_properties(spectra, properties)

        return {
            "spectra": spectra,
            "properties": properties,
            "wavelengths": wavelengths,
            "sample_ids": sample_ids,
            "prop_names": catalog.get("prop_names"),
            "catalog_entry": catalog,
            "file_metadata": file_metadata,
            "dataset": dataset,
        }

    elif catalog["format"] == "mat":
        mat_path = base_dir / catalog["mat_file"]
        if not mat_path.exists():
            raise FileNotFoundError(
                f"Eigenvector data file not found: {mat_path}\n"
                f"Download the dataset from {EIGENVECTOR_UPSTREAM_PAGE} and place it under {base_dir}."
            )

        dataset = None
        sample_ids = None
        prop_key = catalog.get("prop_key")
        if name == "diesel_nir_mat" and isinstance(prop_key, str):
            dataset = load_eigenvector_mat_pair_as_sherpa(
                mat_path,
                spec_key=catalog["spec_key"],
                prop_key=prop_key,
                prop_names=list(catalog["prop_names"]),
                x_title=str(catalog["x_title"]),
                x_units=str(catalog["x_units"]),
                technique=str(catalog["technique"]),
            )
            spectra = dataset.X.copy()
            feature_axis = dataset.feature_axis
            wavelengths = None if feature_axis is None or feature_axis.values is None else feature_axis.values.copy()
            properties = None if dataset.target is None else dataset.target.copy()
            sample_axis = dataset.sample_axis
            sample_ids = None if sample_axis is None or sample_axis.labels is None else list(sample_axis.labels)
            file_metadata = {
                key: value
                for key, value in {
                    "name": dataset.source_identity.object_name or dataset.title,
                    "author": dataset.descriptive.authors[0] if dataset.descriptive.authors else None,
                    "date": dataset.descriptive.raw_date_fields.get("date"),
                    "description": dataset.descriptive.description,
                }.items()
                if value is not None
            }
        else:
            spectra, wavelengths, properties, file_metadata = parse_eigenvector_mat(
                mat_path,
                spec_key=catalog["spec_key"],
                prop_key=prop_key,
            )

        return {
            "spectra": spectra,
            "properties": properties,
            "wavelengths": wavelengths,
            "sample_ids": sample_ids,
            "prop_names": catalog.get("prop_names"),
            "catalog_entry": catalog,
            "file_metadata": file_metadata,
            "dataset": dataset,
        }

    elif catalog["format"] == "matlab_process_log":
        mat_path = base_dir / catalog["mat_file"]
        if not mat_path.exists():
            raise FileNotFoundError(
                f"Eigenvector data file not found: {mat_path}\n"
                f"Download the dataset from {EIGENVECTOR_UPSTREAM_PAGE} and place it under {base_dir}."
            )

        from spectra_sherpa.app.lib.process_log import wafer_time_average
        from spectra_sherpa.io import ingest

        result = ingest(mat_path)
        assets = {asset.asset_id: asset.dataset for asset in result.assets}
        struct_key = str(catalog["struct_key"])
        if struct_key not in assets:
            raise ValueError(f"MATLAB process log does not expose governed object {struct_key!r}")
        dataset = wafer_time_average(assets[struct_key])
        feature_axis = dataset.get_feature_axis()
        wavelengths = None if feature_axis is None or feature_axis.values is None else feature_axis.values.copy()
        sample_table = dataset.sample_axis.sample_table if dataset.sample_axis is not None else None
        fault_labels = None if sample_table is None else list(sample_table.get("fault_name", []))
        info_meta = (
            {"description": dataset.descriptive.description} if dataset.descriptive.description is not None else {}
        )

        return {
            "spectra": dataset.X.copy(),
            "properties": None,
            "wavelengths": wavelengths,
            "sample_ids": fault_labels,
            "prop_names": None,
            "catalog_entry": catalog,
            "file_metadata": info_meta,
        }

    else:
        raise ValueError(f"Unknown format: {catalog['format']}")


# ---------------------------------------------------------------------------
# Dataset info (metadata + computed statistics)
# ---------------------------------------------------------------------------


def get_dataset_info(
    name: str,
    data_dir: Path | None = None,
    *,
    runtime_data_dir: Path | None = None,
) -> dict[str, Any]:
    """Get full metadata + computed statistics for a dataset.

    Combines catalog fields, file metadata, and computed statistics
    into a single info dict suitable for display in the Explore tab.
    """
    result = load_eigenvector_dataset(
        name,
        data_dir=data_dir,
        runtime_data_dir=runtime_data_dir,
    )
    catalog = result["catalog_entry"]
    spectra = result["spectra"]
    properties = result["properties"]
    wavelengths = result["wavelengths"]

    info: dict[str, Any] = {
        "name": name,
        "source": "eigenvector",
        "label": catalog["label"],
        "technique": catalog["technique"],
        "is_spectra": infer_is_spectra(technique=catalog.get("technique"), x_units=catalog.get("x_units")),
        "description": catalog["description"],
        "x_title": catalog.get("x_title"),
        "x_units": catalog.get("x_units"),
        "source_scope": catalog.get("source_scope"),
        "source_contract": catalog.get("source_contract"),
        "related_registered_family": catalog.get("related_registered_family"),
        # File metadata (Name, Author, Date from CSV/MAT headers)
        "file_metadata": result.get("file_metadata", {}),
        # Computed statistics
        "n_samples": int(spectra.shape[0]),
        "n_features": int(spectra.shape[1]),
        "spectra_min": float(np.nanmin(spectra)),
        "spectra_max": float(np.nanmax(spectra)),
        "spectra_mean": float(np.nanmean(spectra)),
    }

    if wavelengths is not None and len(wavelengths) > 0:
        info["wavelength_min"] = float(wavelengths[0])
        info["wavelength_max"] = float(wavelengths[-1])
        if len(wavelengths) > 1:
            info["wavelength_step"] = float(wavelengths[1] - wavelengths[0])

    if properties is not None and result.get("prop_names"):
        prop_stats = []
        for i, pname in enumerate(result["prop_names"]):
            col = properties[:, i] if i < properties.shape[1] else np.array([])
            nan_count = int(np.isnan(col).sum())
            prop_stats.append(
                {
                    "name": pname,
                    "min": float(np.nanmin(col)) if col.size > nan_count else None,
                    "max": float(np.nanmax(col)) if col.size > nan_count else None,
                    "mean": float(np.nanmean(col)) if col.size > nan_count else None,
                    "nan_count": nan_count,
                    "nan_pct": round(100 * nan_count / len(col), 1) if len(col) > 0 else 0,
                }
            )
        info["property_stats"] = prop_stats

    preview = build_catalog_preview(spectra, wavelengths)
    if preview is not None:
        info["preview_spectra"] = preview["spectra"]
        if "wavelengths" in preview:
            info["wavelengths"] = preview["wavelengths"]

    return info
