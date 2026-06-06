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

import logging
import os
import tempfile
import zipfile
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import numpy as np
import pandas as pd

from spectra_sherpa.app.lib.domain_flags import infer_is_spectra

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Data directories.
#
# Eigenvector Research datasets are cataloged here, but raw upstream data is
# not redistributed in the AGPL package. If enabled, missing datasets are
# downloaded at runtime into the user-local app data directory.
# ---------------------------------------------------------------------------

EIGENVECTOR_DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "eigenvector"
EIGENVECTOR_UPSTREAM_PAGE = "https://eigenvector.com/resources/data-sets/"
EIGENVECTOR_RUNTIME_DOWNLOAD_ENV = "SPECTRASHERPA_EIGENVECTOR_DOWNLOADS"

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
    if axis is None or len(axis) < 2:
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
        "description": (
            "Near-infrared spectra of diesel fuels from Southwest Research Institute "
            "(U.S. Army sponsored). Reference properties include BP50 (boiling point), "
            "CN (cetane number), D4052 (density), FLASH (flash point), FREEZE (freezing "
            "temperature), TOTAL (total aromatics), and VISC (viscosity). Widely used "
            "for NIR calibration benchmarking and PLS regression development."
        ),
    },
    # --- Corn instrument standardization ---
    "corn_m5": {
        "label": "Corn M5 NIR (80 samples, 700 channels)",
        "featured": True,
        "format": "mat",
        "archive_url": "https://eigenvector.com/wp-content/uploads/2019/06/corn.mat_.zip",
        "mat_file": "corn_mat/corn.mat",
        "spec_key": "m5spec",
        "prop_key": "propvals",
        "prop_names": ["Moisture", "Oil", "Protein", "Starch"],
        "technique": "NIR",
        "x_title": "Channel",
        "x_units": None,
        "description": (
            "80 samples of corn measured on the Infratec M5 NIR spectrometer. "
            "Wavelength range 1100-2498 nm at 2 nm intervals (700 channels). "
            "Reference properties: moisture, oil, protein, and starch. Data "
            "originally from Cargill, commonly used for instrument standardization "
            "and transfer benchmarking."
        ),
    },
    "corn_mp5": {
        "label": "Corn MP5 NIR (80 samples, 700 channels)",
        "format": "mat",
        "archive_url": "https://eigenvector.com/wp-content/uploads/2019/06/corn.mat_.zip",
        "mat_file": "corn_mat/corn.mat",
        "spec_key": "mp5spec",
        "prop_key": "propvals",
        "prop_names": ["Moisture", "Oil", "Protein", "Starch"],
        "technique": "NIR",
        "x_title": "Channel",
        "x_units": None,
        "description": (
            "80 samples of corn measured on the Infratec MP5 NIR spectrometer. "
            "Wavelength range 1100-2498 nm at 2 nm intervals (700 channels). "
            "Reference properties: moisture, oil, protein, and starch. Data "
            "originally from Cargill, commonly used for instrument standardization "
            "and transfer benchmarking."
        ),
    },
    "corn_mp6": {
        "label": "Corn MP6 NIR (80 samples, 700 channels)",
        "format": "mat",
        "archive_url": "https://eigenvector.com/wp-content/uploads/2019/06/corn.mat_.zip",
        "mat_file": "corn_mat/corn.mat",
        "spec_key": "mp6spec",
        "prop_key": "propvals",
        "prop_names": ["Moisture", "Oil", "Protein", "Starch"],
        "technique": "NIR",
        "x_title": "Channel",
        "x_units": None,
        "description": (
            "80 samples of corn measured on the Infratec MP6 NIR spectrometer. "
            "Wavelength range 1100-2498 nm at 2 nm intervals (700 channels). "
            "Reference properties: moisture, oil, protein, and starch. Data "
            "originally from Cargill, commonly used for instrument standardization "
            "and transfer benchmarking."
        ),
    },
    # --- CGL grain protein NIR ---
    "cgl_nir": {
        "label": "CGL NIR (231 samples, 117 wavelengths, 1104-2496 nm)",
        "format": "mat",
        "archive_url": "https://eigenvector.com/wp-content/uploads/2021/04/CGL_nir.mat_.zip",
        "mat_file": "cgl_nir_mat/CGL_nir.mat",
        "spec_key": "Spectra",
        "prop_key": "PropVals",
        "prop_names": ["Dry Gluten", "Moisture", "Protein", "Wet Gluten"],
        "technique": "NIR",
        "x_title": "Wavelength",
        "x_units": "nm",
        "description": (
            "Full three-component mixture design DOE for prediction of casein, "
            "glucose, lactate and moisture (wt%) from NIR. 231 samples, 117 "
            "wavelengths (1104-2496 nm). Data from Tormod Naes and Tomas Isaksson. "
            "Reference properties: dry gluten, moisture, protein, wet gluten."
        ),
    },
    # --- NIR Shootout 2002 (pharmaceutical tablets) ---
    "nir_shootout_cal1": {
        "label": "NIR Shootout 2002 Cal Inst.1 (155 samples, 650 wl, 600-1898 nm)",
        "featured": True,
        "format": "mat",
        "archive_url": "https://eigenvector.com/wp-content/uploads/2019/06/nir_shootout_2002.mat_.zip",
        "mat_file": "nir_shootout_mat/nir_shootout_2002.mat",
        "spec_key": "calibrate_1",
        "prop_key": "calibrate_Y",
        "prop_names": ["Active", "Hardness", "Weight"],
        "technique": "NIR",
        "x_title": "Wavelength",
        "x_units": "nm",
        "description": (
            "2002 International Diffuse Reflectance Conference (IDRC) Shootout "
            "data set — calibration set, instrument 1. 654 pharmaceutical tablets "
            "from two spectrometers divided into calibration, validation, and test "
            "sets. Reference properties: active ingredient concentration, hardness, "
            "and tablet weight."
        ),
    },
    "nir_shootout_cal2": {
        "label": "NIR Shootout 2002 Cal Inst.2 (155 samples, 650 wl, 600-1898 nm)",
        "format": "mat",
        "archive_url": "https://eigenvector.com/wp-content/uploads/2019/06/nir_shootout_2002.mat_.zip",
        "mat_file": "nir_shootout_mat/nir_shootout_2002.mat",
        "spec_key": "calibrate_2",
        "prop_key": "calibrate_Y",
        "prop_names": ["Active", "Hardness", "Weight"],
        "technique": "NIR",
        "x_title": "Wavelength",
        "x_units": "nm",
        "description": (
            "2002 International Diffuse Reflectance Conference (IDRC) Shootout "
            "data set — calibration set, instrument 2. 654 pharmaceutical tablets "
            "from two spectrometers divided into calibration, validation, and test "
            "sets. Reference properties: active ingredient concentration, hardness, "
            "and tablet weight."
        ),
    },
    "nir_shootout_test1": {
        "label": "NIR Shootout 2002 Test Inst.1 (460 samples, 650 wl, 600-1898 nm)",
        "featured": True,
        "format": "mat",
        "archive_url": "https://eigenvector.com/wp-content/uploads/2019/06/nir_shootout_2002.mat_.zip",
        "mat_file": "nir_shootout_mat/nir_shootout_2002.mat",
        "spec_key": "test_1",
        "prop_key": "test_Y",
        "prop_names": ["Active", "Hardness", "Weight"],
        "technique": "NIR",
        "x_title": "Wavelength",
        "x_units": "nm",
        "description": (
            "2002 International Diffuse Reflectance Conference (IDRC) Shootout "
            "data set — test set, instrument 1. 654 pharmaceutical tablets "
            "from two spectrometers divided into calibration, validation, and test "
            "sets. Reference properties: active ingredient concentration, hardness, "
            "and tablet weight."
        ),
    },
    "nir_shootout_test2": {
        "label": "NIR Shootout 2002 Test Inst.2 (460 samples, 650 wl, 600-1898 nm)",
        "format": "mat",
        "archive_url": "https://eigenvector.com/wp-content/uploads/2019/06/nir_shootout_2002.mat_.zip",
        "mat_file": "nir_shootout_mat/nir_shootout_2002.mat",
        "spec_key": "test_2",
        "prop_key": "test_Y",
        "prop_names": ["Active", "Hardness", "Weight"],
        "technique": "NIR",
        "x_title": "Wavelength",
        "x_units": "nm",
        "description": (
            "2002 International Diffuse Reflectance Conference (IDRC) Shootout "
            "data set — test set, instrument 2. 654 pharmaceutical tablets "
            "from two spectrometers divided into calibration, validation, and test "
            "sets. Reference properties: active ingredient concentration, hardness, "
            "and tablet weight."
        ),
    },
    # --- Metal Etch process monitoring ---
    "metal_etch_oes": {
        "label": "Metal Etch OES (126 wafers, 129 wavelengths, 250-792 nm)",
        "featured": True,
        "format": "metal_etch",
        "archive_url": "https://eigenvector.com/wp-content/uploads/2019/06/OES_DATA.mat_.zip",
        "mat_file": "metal_etch/OES_DATA.mat",
        "struct_key": "OESDATA",
        "axis_key": "wave_axis",
        "technique": "OES",
        "x_title": "Wavelength",
        "x_units": "nm",
        "description": (
            "Optical Emission Spectroscopy data from a LAM 9600 Metal Etcher. "
            "Integrated peak areas at 43 wavelengths measured at 3 different "
            "positions perpendicular to gas flow (129 total features). 126 wafers "
            "(106 normal from 3 experiments + 20 with intentionally induced faults). "
            "Per-wafer time-averaged. Originally from Texas Instruments as part of "
            "the SEMATECH J-88 project. See: Wise et al., J. Chemometrics, 13, "
            "379-396 (1999)."
        ),
    },
    "metal_etch_machine": {
        "label": "Metal Etch Machine (129 wafers, 21 sensor variables)",
        "format": "metal_etch",
        "archive_url": "https://eigenvector.com/wp-content/uploads/2019/06/MACHINE_Data.mat_.zip",
        "mat_file": "metal_etch/MACHINE_Data.mat",
        "struct_key": "LAMDATA",
        "axis_key": "variables",
        "technique": "Process Sensors",
        "x_title": "Variable",
        "x_units": None,
        "description": (
            "Engineering sensor data from a LAM 9600 Metal Etcher. "
            "21 process variables (BCl3/Cl2 flow, RF power, pressure, TCP tuner, "
            "vat valve, etc.). 129 wafers (108 normal + 21 fault) from 3 experiments "
            "run several weeks apart. Per-wafer time-averaged. Originally from Texas "
            "Instruments as part of the SEMATECH J-88 project. See: Wise et al., "
            "J. Chemometrics, 13, 379-396 (1999)."
        ),
    },
    "metal_etch_rfm": {
        "label": "Metal Etch RFM (126 wafers, 19 RF variables)",
        "format": "metal_etch",
        "archive_url": "https://eigenvector.com/wp-content/uploads/2019/06/RFM_DATA.mat_.zip",
        "mat_file": "metal_etch/RFM_DATA.mat",
        "struct_key": "RFMDATA",
        "axis_key": "variables",
        "technique": "RF Monitor",
        "x_title": "Variable",
        "x_units": None,
        "description": (
            "RF Monitor data from a LAM 9600 Metal Etcher. "
            "71 RF variables (voltages, currents, phases across sensor stages). "
            "126 wafers (106 normal + 20 fault) from 3 experiments run several "
            "weeks apart. Per-wafer time-averaged. Originally from Texas Instruments "
            "as part of the SEMATECH J-88 project. See: Wise et al., "
            "J. Chemometrics, 13, 379-396 (1999)."
        ),
    },
}


# ---------------------------------------------------------------------------
# Runtime data download/cache
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


def _runtime_data_dir() -> Path:
    from spectra_sherpa.app.core.config import settings

    return settings.data_dir / "reference_cache" / "eigenvector"


def _runtime_downloads_enabled() -> bool:
    value = os.getenv(EIGENVECTOR_RUNTIME_DOWNLOAD_ENV)
    if value is not None:
        return value.strip().lower() in {"1", "true", "yes", "y", "on"}

    from spectra_sherpa.app.core.config import app_config

    return bool(app_config.egress_enabled)


def _download_error(name: str, catalog: dict[str, Any], base_dir: Path, reason: str) -> FileNotFoundError:
    files = ", ".join(_required_catalog_files(catalog))
    return FileNotFoundError(
        "Eigenvector Research example data is no longer bundled with SpectraSherpa. "
        f"Dataset {name!r} requires these upstream files: {files}. "
        f"Place them under {base_dir} or enable runtime download with "
        f"EGRESS_ENABLED=true or {EIGENVECTOR_RUNTIME_DOWNLOAD_ENV}=true. "
        f"Source page: {EIGENVECTOR_UPSTREAM_PAGE}. Detail: {reason}"
    )


def _archive_cache_path(url: str) -> Path:
    safe = "".join(ch if ch.isalnum() or ch in {".", "-", "_"} else "_" for ch in Path(url).name)
    if not safe.lower().endswith(".zip"):
        safe = f"{safe}.zip"
    return _runtime_data_dir() / "_archives" / safe


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


def _download_archive(url: str, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    request = Request(url, headers={"User-Agent": "SpectraSherpa OSS runtime dataset downloader"})
    fd, tmp_name = tempfile.mkstemp(dir=destination.parent, prefix=f".{destination.name}.")
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "wb") as tmp:
            with urlopen(request, timeout=60) as response:  # noqa: S310 - fixed upstream HTTPS catalog URLs.
                while True:
                    chunk = response.read(1024 * 1024)
                    if not chunk:
                        break
                    tmp.write(chunk)
        _replace_if_missing(tmp_path, destination)
    except Exception:
        tmp_path.unlink(missing_ok=True)
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
            target = base_dir / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            fd, tmp_name = tempfile.mkstemp(dir=target.parent, prefix=f".{target.name}.")
            tmp_path = Path(tmp_name)
            try:
                with archive.open(candidates[0]) as source, os.fdopen(fd, "wb") as tmp:
                    while True:
                        chunk = source.read(1024 * 1024)
                        if not chunk:
                            break
                        tmp.write(chunk)
                _replace_if_missing(tmp_path, target)
            except Exception:
                tmp_path.unlink(missing_ok=True)
                raise


def _ensure_runtime_data(name: str, catalog: dict[str, Any], base_dir: Path) -> None:
    missing = _missing_catalog_files(base_dir, catalog)
    if not missing:
        return
    url = str(catalog.get("archive_url") or "")
    if not url:
        raise _download_error(name, catalog, base_dir, "no upstream archive is configured")
    if not _runtime_downloads_enabled():
        raise _download_error(name, catalog, base_dir, "runtime downloads are disabled")

    archive_path = _archive_cache_path(url)
    try:
        if not archive_path.exists():
            _download_archive(url, archive_path)
        _extract_required_files(archive_path, base_dir, catalog)
    except (HTTPError, URLError, TimeoutError, zipfile.BadZipFile, OSError, FileNotFoundError) as exc:
        raise _download_error(name, catalog, base_dir, str(exc)) from exc

    still_missing = _missing_catalog_files(base_dir, catalog)
    if still_missing:
        raise _download_error(name, catalog, base_dir, f"missing after extraction: {', '.join(still_missing)}")


def _resolve_dataset_dir(name: str, catalog: dict[str, Any], data_dir: Path | None) -> Path:
    if data_dir is not None:
        return data_dir
    if not _missing_catalog_files(EIGENVECTOR_DATA_DIR, catalog):
        return EIGENVECTOR_DATA_DIR
    runtime_dir = _runtime_data_dir()
    _ensure_runtime_data(name, catalog, runtime_dir)
    return runtime_dir


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
    from scipy.io import loadmat

    mat = loadmat(str(path), squeeze_me=False)

    if spec_key not in mat:
        available = [k for k in mat.keys() if not k.startswith("_")]
        raise ValueError(f"Key '{spec_key}' not found in {path.name}. " f"Available keys: {available}")

    ds = mat[spec_key]
    spec_data = ds["data"][0, 0]

    # Extract metadata from the structured array
    file_metadata = extract_mat_metadata(ds)

    # Try to extract axis scale (wavelength/channel values)
    # Eigenvector DataSet axisscale is a 2x2 cell array:
    #   [0,0] = row (sample) axis values,  [0,1] = row axis label
    #   [1,0] = column (variable) axis values,  [1,1] = column axis label
    axis_values = None
    try:
        axisscale = ds["axisscale"][0, 0]
        if axisscale.size > 0 and axisscale.ndim >= 2 and axisscale.shape[0] > 1:
            col_axis = axisscale[1, 0].flatten()
            if col_axis.size == spec_data.shape[1] and col_axis.dtype.kind in ("f", "i", "u"):
                axis_values = col_axis.astype(float)
                _validate_axis_monotonic(axis_values, source=f"{path.name}[{spec_key}]")
    except (IndexError, KeyError, ValueError):
        pass

    # Extract properties if requested
    prop_data = None
    if prop_key and prop_key in mat:
        try:
            prop_data = mat[prop_key]["data"][0, 0]
        except (IndexError, KeyError):
            logger.warning("Could not extract properties from '%s'", prop_key)

    return spec_data, axis_values, prop_data, file_metadata


# ---------------------------------------------------------------------------
# Metal Etch parser (LAM 9600 — OES, MACHINE, RFM)
# ---------------------------------------------------------------------------


def parse_metal_etch_mat(
    path: Path,
    struct_key: str,
    axis_key: str,
) -> tuple[np.ndarray, np.ndarray | None, list[str], dict[str, str]]:
    """Parse Metal Etch .mat files (OES_DATA, MACHINE_Data, RFM_DATA).

    These files use a different structure from the standard DataSet objects.
    Each wafer's data is stored as a cell array element with time-resolved
    measurements. We compute the per-wafer time-average to produce a 2D
    matrix (n_wafers x n_features) suitable for spectral analysis.

    Args:
        path: Path to the .mat file.
        struct_key: Top-level struct key (e.g., "OESDATA").
        axis_key: Key for the axis values ("wave_axis" or "variables").

    Returns:
        (data, axis_values, fault_labels, info_metadata)
        - data: 2D numpy array (n_wafers x n_features), time-averaged
        - axis_values: 1D numpy array of axis values, or None
        - fault_labels: list of fault/normal labels per wafer
        - info_metadata: dict with INFORMATION text
    """
    from scipy.io import loadmat

    mat = loadmat(str(path), squeeze_me=False)
    ds = mat[struct_key]

    # Extract per-wafer data by time-averaging each cell
    cal_cells = ds["calibration"][0, 0]
    test_cells = ds["test"][0, 0]

    def _stack_wafers(cells: np.ndarray) -> np.ndarray:
        rows = []
        for i in range(cells.shape[0]):
            w = cells[i, 0]
            if w.ndim == 2 and w.shape[0] > 0:
                rows.append(np.mean(w, axis=0))
        return np.array(rows)

    cal_data = _stack_wafers(cal_cells)
    test_data = _stack_wafers(test_cells)
    data = np.vstack([cal_data, test_data])

    # Build fault labels: "normal" for calibration, fault name for test
    fault_labels = ["normal"] * cal_data.shape[0]
    try:
        fnames = ds["fault_names"][0, 0]
        for i in range(test_data.shape[0]):
            if i < fnames.shape[0]:
                fault_labels.append(str(fnames[i].flat[0]).strip())
            else:
                fault_labels.append("fault")
    except (IndexError, KeyError):
        fault_labels.extend(["fault"] * test_data.shape[0])

    # Extract axis values
    axis_values = None
    try:
        ax_raw = ds[axis_key][0, 0]
        if ax_raw.dtype.kind in ("f", "i", "u"):
            axis_values = ax_raw.flatten().astype(float)
            _validate_axis_monotonic(axis_values, source=f"{path.name}[{axis_key}]")
        # For "variables" key, values are strings — not a numeric axis
    except (IndexError, KeyError, ValueError):
        pass

    # Extract INFORMATION text
    info_metadata: dict[str, str] = {}
    try:
        info_arr = ds["INFORMATION"][0, 0]
        lines = [str(x.flat[0]).strip() for x in info_arr.flatten()]
        info_metadata["description"] = " ".join(lines)
    except (IndexError, KeyError, ValueError):
        pass

    return data, axis_values, fault_labels, info_metadata


# ---------------------------------------------------------------------------
# Main loader
# ---------------------------------------------------------------------------


def load_eigenvector_dataset(
    name: str,
    data_dir: Path | None = None,
) -> dict[str, Any]:
    """Load an Eigenvector Research public dataset by name.

    Args:
        name: Dataset name from DATASET_CATALOG.
        data_dir: Override data directory (for testing or locally supplied
            upstream data). Defaults to the package data directory when present,
            otherwise the user-local runtime cache.

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
    base_dir = _resolve_dataset_dir(name, catalog, data_dir)

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
        if "prop_file" in catalog:
            prop_path = base_dir / catalog["prop_file"]
            if prop_path.exists():
                properties, _, _ = parse_eigenvector_csv(prop_path, has_axisscale=False)

        return {
            "spectra": spectra,
            "properties": properties,
            "wavelengths": wavelengths,
            "sample_ids": sample_ids,
            "prop_names": catalog.get("prop_names"),
            "catalog_entry": catalog,
            "file_metadata": file_metadata,
        }

    elif catalog["format"] == "mat":
        mat_path = base_dir / catalog["mat_file"]
        if not mat_path.exists():
            raise FileNotFoundError(
                f"Eigenvector data file not found: {mat_path}\n"
                f"Download the dataset from {EIGENVECTOR_UPSTREAM_PAGE} and place it under {base_dir}."
            )

        spectra, wavelengths, properties, file_metadata = parse_eigenvector_mat(
            mat_path,
            spec_key=catalog["spec_key"],
            prop_key=catalog.get("prop_key"),
        )

        return {
            "spectra": spectra,
            "properties": properties,
            "wavelengths": wavelengths,
            "sample_ids": None,
            "prop_names": catalog.get("prop_names"),
            "catalog_entry": catalog,
            "file_metadata": file_metadata,
        }

    elif catalog["format"] == "metal_etch":
        mat_path = base_dir / catalog["mat_file"]
        if not mat_path.exists():
            raise FileNotFoundError(
                f"Eigenvector data file not found: {mat_path}\n"
                f"Download the dataset from {EIGENVECTOR_UPSTREAM_PAGE} and place it under {base_dir}."
            )

        spectra, wavelengths, fault_labels, info_meta = parse_metal_etch_mat(
            mat_path,
            struct_key=catalog["struct_key"],
            axis_key=catalog["axis_key"],
        )

        return {
            "spectra": spectra,
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
) -> dict[str, Any]:
    """Get full metadata + computed statistics for a dataset.

    Combines catalog fields, file metadata, and computed statistics
    into a single info dict suitable for display in the Explore tab.
    """
    result = load_eigenvector_dataset(name, data_dir=data_dir)
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
