"""
File I/O utilities for spectral data.

NDDataset-native file reading and writing, supporting:
- CSV files (wavenumber, absorbance columns)
- JSON signature files (calibration models)
- MATLAB .mat files
- SpectroChemPy native formats (.jdx, .dx, .spc, .spa)

MIGRATED FROM: project0/io.py, project1/plot_ftir_spectra.py
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import TYPE_CHECKING, Any, List, Optional, Union

if TYPE_CHECKING:
    from spectra_sherpa.app.lib.sherpa_dataset import SherpaDataset

import numpy as np

logger = logging.getLogger(__name__)
import pandas as pd

try:
    from scipy.io import loadmat

    HAS_SCIPY = True
except ImportError:
    HAS_SCIPY = False
    loadmat = None

from spectra_sherpa.app.lib.scp_compat import NDDataset, require_scp, scp

# Filename pattern for extracting species labels
# The previous form ``^[A-Z0-9]+[\s_-]?.*\.CSV$`` flagged as polynomial-redos
# because ``[A-Z0-9]+`` and ``.*`` could both consume alphanumeric chars,
# leaving the engine to retry many partitionings on non-matching inputs.
# Folding the separator into the optional tail group eliminates the
# overlap: either the filename is just ``LABEL.CSV`` or the label is
# followed by exactly one separator and then arbitrary content.
FILENAME_PATTERN = re.compile(
    r"^(?P<label>[A-Z0-9]+)(?:[\s_-].*)?\.CSV$",
    re.IGNORECASE,
)
CONC_PATTERN = re.compile(r"\(([^()]*?)ppm", re.IGNORECASE)
_CSV_AXIS_UNITS_PATTERN = re.compile(r"\((?P<units>[^)]*)\)")


def _spectral_axis_info_from_header(header: str) -> tuple[str, str | None] | None:
    """Return spectral axis title/units for scientist-style CSV axis columns."""
    cleaned = str(header).strip()
    lower = cleaned.lower()
    if "raman" in lower and "shift" in lower:
        title = "Raman Shift"
    elif "wavenumber" in lower or "wave number" in lower:
        title = "Wavenumber"
    elif "wavelength" in lower or "wave length" in lower:
        title = "Wavelength"
    elif "chemical shift" in lower:
        title = "Chemical Shift"
    elif lower in {"m/z", "mz"} or "mass-to-charge" in lower or "mass to charge" in lower:
        title = "m/z"
    else:
        return None

    units_match = _CSV_AXIS_UNITS_PATTERN.search(cleaned)
    units = units_match.group("units").strip() if units_match else None
    if units in {"cm^-1", "cm⁻¹"}:
        units = "cm-1"
    return title, units or None


def _normalize_axis_units(units: str | None) -> str | None:
    if units is None:
        return None
    cleaned = str(units).strip()
    if not cleaned:
        return None
    if cleaned in {"cm^-1", "cm⁻¹"}:
        return "cm-1"
    return cleaned


def _infer_numeric_spectral_axis(
    filepath: Union[str, Path],
    x_values: np.ndarray,
    overrides: Any | None,
) -> tuple[str, str | None]:
    """Infer metadata for matrix-style spectral CSVs with numeric column headers.

    Numeric headers alone cannot prove whether the axis is wavenumber, Raman
    shift, wavelength, or an arbitrary feature coordinate. Prefer explicit
    prepared-data metadata, then weak file-name hints, and otherwise keep the
    title generic instead of laundering unknown axes into wavenumber.
    """
    if overrides is not None:
        override_title = getattr(overrides, "x_title", None)
        override_units = _normalize_axis_units(getattr(overrides, "x_units", None))
        if override_title or override_units:
            return override_title or "Spectral Axis", override_units

    stem = Path(filepath).stem.lower()
    if "raman" in stem or "shift" in stem:
        return "Raman Shift", "cm-1"
    if "wavenumber" in stem or "wave_number" in stem or "ftir" in stem:
        return "Wavenumber", "cm-1"
    if "wavelength" in stem or "wave_length" in stem:
        return "Wavelength", "nm"
    if "nir" in stem or "near_ir" in stem or "near-infrared" in stem:
        return "Wavelength", "nm"
    if x_values.size and np.nanmin(x_values) >= 4000 and np.nanmax(x_values) <= 12000:
        return "Wavenumber", "cm-1"
    return "Spectral Axis", None


def _load_axis_column_spectral_csv(
    df: pd.DataFrame,
    filepath: Union[str, Path],
    *,
    data_role: str | None = None,
) -> "SherpaDataset | None":
    """Load wide CSVs with one shared spectral axis column and condition columns.

    Example:
        Wavenumber (cm-1),Condition A,Condition B
        200,2139,9549
        201,2159,9538

    The scientist intent is two spectra sharing the same x-axis, not 1801
    samples with three generic features.
    """
    if len(df.columns) < 2:
        return None

    axis_col = df.columns[0]
    axis_info = _spectral_axis_info_from_header(str(axis_col))
    if axis_info is None:
        return None

    x_values = pd.to_numeric(df[axis_col], errors="coerce")
    if x_values.isna().any() or len(x_values) < 2:
        return None

    x_array = x_values.to_numpy(dtype=np.float64)
    diffs = np.diff(x_array)
    if not (bool(np.all(diffs > 0)) or bool(np.all(diffs < 0))):
        return None

    condition_cols = list(df.columns[1:])
    intensity_df = df[condition_cols].apply(pd.to_numeric, errors="coerce")
    if intensity_df.isna().any().any():
        return None

    from spectra_sherpa.app.lib.axes import SampleAxis, SpectralAxis
    from spectra_sherpa.app.lib.sherpa_dataset import DomainContext, SherpaDataset

    axis_title, units = axis_info
    path = Path(filepath)
    technique = "raman" if "raman" in path.stem.lower() or "raman" in str(axis_col).lower() else None

    return SherpaDataset(
        X=intensity_df.to_numpy(dtype=np.float64).T,
        feature_axis=SpectralAxis(values=x_array, title=axis_title, units=units),
        sample_axis=SampleAxis(labels=[str(col) for col in condition_cols], title="Condition"),
        domain=DomainContext(
            technique=technique,
            sample_type=path.stem,
            expected_units=units,
            data_quantity="Intensity",
        ),
        extra={
            "csv.layout": "axis_column_conditions",
            "csv.axis_column": str(axis_col),
            "csv.condition_columns": [str(col) for col in condition_cols],
        },
        title=path.stem,
        data_role="X_spectra",
    )


def _normalise_label(value: str) -> str:
    """Normalize a species label."""
    cleaned = re.sub(r"[_\s]+", " ", value).strip()
    return cleaned.upper() if cleaned else value.upper()


def _extract_label_from_filename(filename: str) -> str:
    """Extract species label from filename."""
    stem = Path(filename).stem

    # Try pattern: PREFIX_SPECIES_SUFFIX_SUFFIX.csv
    first_sep = stem.find("_")
    second_last_sep = stem.rfind("_", 0, stem.rfind("_")) if stem.count("_") >= 2 else -1
    if first_sep != -1 and second_last_sep != -1 and second_last_sep > first_sep:
        candidate = stem[first_sep + 1 : second_last_sep]
        if candidate:
            return _normalise_label(candidate)

    parts = stem.split("_")
    if len(parts) >= 4:
        candidate_parts = parts[1:-2]
        candidate = " ".join(candidate_parts).strip()
        if candidate:
            return _normalise_label(candidate)

    match = FILENAME_PATTERN.match(filename)
    if match:
        return _normalise_label(match.group("label"))

    fallback = re.sub(r"[_\s]+", " ", stem).strip()
    return fallback.upper() if fallback else stem.upper()


def extract_concentration(filepath: Path) -> Optional[float]:
    """
    Extract concentration value from filename pattern like "(XXXppm)".

    Returns None if no pattern found.
    """
    match = CONC_PATTERN.search(filepath.name)
    if not match:
        return None
    try:
        raw_value = match.group(1).strip().replace("-", ".")
        return float(raw_value)
    except ValueError:
        return None


def extract_pathlength(filepath: Path) -> Optional[float]:
    """
    Extract pathlength from filename (second-to-last underscore segment).

    Returns pathlength in meters, or None if not found.
    """
    stem = filepath.stem
    parts = stem.split("_")
    if len(parts) < 2:
        return None

    segment = parts[-2]

    # Detect unit suffix
    unit_suffix = None
    if segment.endswith("cm") or segment.endswith("CM"):
        unit_suffix = "cm"
    elif segment.endswith("m") or segment.endswith("M"):
        unit_suffix = "m"

    # Strip letters and convert hyphen to decimal
    clean_segment = segment.rstrip("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ)").replace("-", ".").strip()

    try:
        value = float(clean_segment)
    except ValueError:
        return None

    # Convert to meters
    if unit_suffix == "cm":
        value = value / 100.0

    return value


# ─────────────────────────────────────────────────────────────────────────────
# CSV READING
# ─────────────────────────────────────────────────────────────────────────────


def read_csv_spectrum(filepath: Path) -> "NDDataset":
    """
    Read a single CSV spectrum file.

    Expected format: two columns (wavenumber, absorbance), no header.

    Parameters
    ----------
    filepath : Path
        Path to CSV file

    Returns
    -------
    NDDataset
        Spectrum with x-coordinate (wavenumber) and metadata
    """
    from .spectral.dataset import SpectralUnit, create_spectral_dataset

    df = pd.read_csv(
        filepath,
        header=None,
        names=["wavenumber", "absorbance"],
    ).sort_values("wavenumber", ascending=True)

    if df.empty:
        raise ValueError(f"Empty CSV file: {filepath}")

    wavenumber = df["wavenumber"].astype(float).to_numpy()
    absorbance = df["absorbance"].astype(float).to_numpy()

    label = _extract_label_from_filename(filepath.name)
    concentration = extract_concentration(filepath)
    pathlength = extract_pathlength(filepath)

    dataset = create_spectral_dataset(
        data=absorbance,
        wavenumbers=wavenumber,
        units=SpectralUnit.ABSORBANCE,
        title=label,
    )

    # Add metadata
    dataset.meta["source_file"] = str(filepath)
    dataset.meta["source_type"] = "csv"
    if concentration is not None:
        dataset.meta["concentration"] = concentration
    if pathlength is not None:
        dataset.meta["pathlength_m"] = pathlength

    return dataset


def read_csv_directory(
    directory: Path,
    pattern: str = "*.csv",
) -> List["NDDataset"]:
    """
    Read all CSV spectra from a directory.

    Parameters
    ----------
    directory : Path
        Directory containing CSV files
    pattern : str
        Glob pattern for files

    Returns
    -------
    list[NDDataset]
        List of spectra
    """
    datasets = []
    for filepath in sorted(directory.glob(pattern)):
        if filepath.is_file():
            try:
                ds = read_csv_spectrum(filepath)
                datasets.append(ds)
            except Exception as e:
                logger.warning(f"Could not read {filepath}: {e}")
    return datasets


# ─────────────────────────────────────────────────────────────────────────────
# JSON SIGNATURE READING
# ─────────────────────────────────────────────────────────────────────────────


def read_json_signature(filepath: Path) -> "NDDataset":
    """
    Read a JSON calibration signature file.

    JSON format should contain:
    - wavenumber: array of wavenumber values
    - model_type: "linear", "saturation", or "hybrid"
    - Calibration parameters (slope, intercept, s, p, c)

    Parameters
    ----------
    filepath : Path
        Path to JSON file

    Returns
    -------
    NDDataset
        Spectrum with calibration in meta["calibration"]
    """
    from .spectral.dataset import SpectralUnit, create_spectral_dataset

    with open(filepath) as f:
        data = json.load(f)

    wavenumber = np.array(data.get("wavenumber", data.get("wavenumbers", [])), dtype=float)
    if len(wavenumber) == 0:
        raise ValueError(f"No wavenumber data in {filepath}")

    # Get absorbance (may be computed from model)
    absorbance = data.get("absorbance")
    if absorbance is not None:
        absorbance = np.array(absorbance, dtype=float)
    else:
        # Compute reference absorbance at reference concentration
        ref_conc = data.get("reference_concentration", 1.0)
        model_type = data.get("model_type", "linear")

        if model_type == "linear":
            slope = np.array(data.get("slope", np.zeros(len(wavenumber))), dtype=float)
            intercept = np.array(data.get("intercept", np.zeros(len(wavenumber))), dtype=float)
            absorbance = slope * ref_conc + intercept
        elif model_type == "saturation":
            from .blending import eval_saturation_model

            s = np.array(data.get("s", np.ones(len(wavenumber))), dtype=float)
            p = np.array(data.get("p", np.ones(len(wavenumber))), dtype=float)
            c = np.array(data.get("c", np.ones(len(wavenumber))), dtype=float)
            absorbance = eval_saturation_model(np.array([ref_conc]), s, p, c)[:, 0]
        else:
            absorbance = np.zeros(len(wavenumber))

    label = data.get("label", _extract_label_from_filename(filepath.name))

    dataset = create_spectral_dataset(
        data=absorbance,
        wavenumbers=wavenumber,
        units=SpectralUnit.ABSORBANCE,
        title=label,
    )

    # Store calibration in metadata
    calibration = {
        "model_type": data.get("model_type", "linear"),
        "concentration_mode": data.get("concentration_mode", "product"),
    }

    # Add model parameters
    for key in ["slope", "intercept", "s", "p", "c", "model_at_wavenumber"]:
        if key in data and data[key] is not None:
            calibration[key] = data[key]

    if "reference_concentration" in data:
        calibration["reference_concentration"] = data["reference_concentration"]

    dataset.meta["calibration"] = calibration
    dataset.meta["source_file"] = str(filepath)
    dataset.meta["source_type"] = "json"

    return dataset


# ─────────────────────────────────────────────────────────────────────────────
# MATLAB .MAT READING
# ─────────────────────────────────────────────────────────────────────────────


def read_mat_file(filepath: Path) -> List["NDDataset"]:
    """
    Read a MATLAB .mat file.

    Supports common spectral data formats stored in .mat files.

    Parameters
    ----------
    filepath : Path
        Path to .mat file

    Returns
    -------
    list[NDDataset]
        One or more spectra from the file
    """
    if not HAS_SCIPY:
        raise ImportError("scipy is required to read .mat files")

    from .spectral.dataset import SpectralUnit, create_spectral_dataset

    mat_data = loadmat(str(filepath), squeeze_me=True, struct_as_record=False)
    label = _extract_label_from_filename(filepath.name)
    uses_generic_feature_index = False

    # Look for wavenumber data
    wavenumber = None
    for key in ["wavenumber", "wavenumbers", "x", "X", "wn", "freq", "frequency", "wavelength"]:
        if key in mat_data and isinstance(mat_data[key], np.ndarray):
            wavenumber = np.asarray(mat_data[key], dtype=float).flatten()
            break

    # Look for absorbance/intensity data
    absorbance = None
    for key in [
        "absorbance",
        "abs",
        "y",
        "Y",
        "data",
        "spectra",
        "spectrum",
        "intensity",
        "signal",
        "MATRIX",
        "matrix",
        "D",
    ]:
        if key in mat_data and isinstance(mat_data[key], np.ndarray):
            absorbance = np.asarray(mat_data[key], dtype=float)
            break

    # Try finding 2D array if named variables not found
    if wavenumber is None or absorbance is None:
        for key, value in mat_data.items():
            if key.startswith("_"):
                continue
            if isinstance(value, np.ndarray) and value.ndim == 2:
                if value.shape[1] == 2:
                    wavenumber = value[:, 0].astype(float)
                    absorbance = value[:, 1].astype(float)
                    break
                elif value.shape[0] == 2:
                    wavenumber = value[0, :].astype(float)
                    absorbance = value[1, :].astype(float)
                    break

    if absorbance is not None and wavenumber is None:
        feature_count = absorbance.shape[1] if absorbance.ndim == 2 else absorbance.size
        wavenumber = np.arange(feature_count, dtype=float)
        uses_generic_feature_index = True

    if wavenumber is None or absorbance is None:
        raise ValueError(
            f"Could not find spectral data in {filepath}. " "Expected variables like 'wavenumber'/'absorbance'."
        )

    datasets = []

    def _build_dataset(data: np.ndarray, title: str) -> "NDDataset":
        if not uses_generic_feature_index:
            ds = create_spectral_dataset(
                data=data,
                wavenumbers=wavenumber,
                units=SpectralUnit.ABSORBANCE,
                title=title,
            )
        else:
            require_scp("MATLAB dataset fallback")
            ds = scp.NDDataset(np.asarray(data, dtype=float), title=title)
            ds.x = scp.Coord(np.asarray(wavenumber, dtype=float), title="Index")
            ds.units = SpectralUnit.DIMENSIONLESS.value
            ds.meta["x_label"] = "Index"
            ds.meta["x_unit"] = ""
            ds.meta["data_type"] = "generic"

        ds.meta["source_file"] = str(filepath)
        ds.meta["source_type"] = "mat"
        return ds

    # Handle 2D absorbance (multiple spectra)
    if absorbance.ndim == 2:
        if absorbance.shape[1] == len(wavenumber):
            # Rows are spectra
            for i in range(absorbance.shape[0]):
                ds = _build_dataset(
                    data=absorbance[i, :],
                    title=f"{label}_{i + 1}" if absorbance.shape[0] > 1 else label,
                )
                datasets.append(ds)
        elif absorbance.shape[0] == len(wavenumber):
            # Columns are spectra
            for i in range(absorbance.shape[1]):
                ds = _build_dataset(
                    data=absorbance[:, i],
                    title=f"{label}_{i + 1}" if absorbance.shape[1] > 1 else label,
                )
                datasets.append(ds)
    else:
        # Single spectrum
        absorbance = absorbance.flatten()
        if len(wavenumber) != len(absorbance):
            raise ValueError(
                f"Wavenumber/absorbance length mismatch in {filepath}: " f"{len(wavenumber)} vs {len(absorbance)}"
            )
        ds = _build_dataset(data=absorbance, title=label)
        datasets.append(ds)

    return datasets


# ─────────────────────────────────────────────────────────────────────────────
# SPECTROCHEMPY FORMAT READING
# ─────────────────────────────────────────────────────────────────────────────


def read_spectral_file(filepath: Path) -> "NDDataset":
    """
    Read spectral files using SpectroChemPy.

    Supports: .spc, .spa, .spg, .opus

    Parameters
    ----------
    filepath : Path
        Path to spectral file

    Returns
    -------
    NDDataset
        Spectrum data
    """
    require_scp("Spectral file reading")

    ext = filepath.suffix.lower()
    label = _extract_label_from_filename(filepath.name)

    if ext == ".spc":
        dataset = scp.read_spc(str(filepath))
    elif ext in [".spa", ".spg", ".srs"]:
        dataset = scp.read_omnic(str(filepath))
    elif ext == ".opus":
        dataset = scp.read_opus(str(filepath))
    else:
        raise ValueError(f"Unsupported spectral format: {ext}")

    if dataset.title in [None, "", "<untitled>"]:
        dataset.title = label

    dataset.meta["source_file"] = str(filepath)
    dataset.meta["source_type"] = ext.lstrip(".")

    return dataset


def _axis_title_from_jcamp_units(units: str | None) -> str:
    text = (units or "").lower()
    if "nm" in text or "micrometer" in text or "um" in text or "µm" in text:
        return "Wavelength"
    if "raman" in text:
        return "Raman Shift"
    return "Wavenumber"


def _intensity_title_from_units(units: str | None) -> str:
    text = (units or "").lower()
    if "transmit" in text:
        return "Transmittance"
    if "absorb" in text:
        return "Absorbance"
    return units or "Intensity"


def load_jcamp_as_sherpa(filepath: Union[str, Path]) -> "SherpaDataset":
    """Load JCAMP-DX with the dependency-free bundled reader."""
    from spectra_sherpa.app.lib.axes import SampleAxis, SpectralAxis
    from spectra_sherpa.app.lib.jcamp_reader import read_jcamp
    from spectra_sherpa.app.lib.sherpa_dataset import DomainContext, SherpaDataset

    path = Path(filepath)
    jcamp = read_jcamp(path)
    y = np.asarray(jcamp.y, dtype=np.float64)
    x = np.asarray(jcamp.x, dtype=np.float64)
    if x.ndim != 1 or y.ndim != 1:
        raise ValueError(f"JCAMP file must contain one-dimensional x/y arrays: {path.name}")
    if len(x) != len(y):
        raise ValueError(f"JCAMP x/y length mismatch in {path.name}: {len(x)} vs {len(y)}")

    axis_units = _normalize_axis_units(jcamp.xunits) or None
    y_title = _intensity_title_from_units(jcamp.yunits)
    title = jcamp.title or path.stem
    return SherpaDataset(
        X=y.reshape(1, -1),
        feature_axis=SpectralAxis(
            values=x,
            title=_axis_title_from_jcamp_units(axis_units),
            units=axis_units,
        ),
        sample_axis=SampleAxis(labels=[title], title="Samples"),
        domain=DomainContext(expected_units=axis_units, data_quantity=y_title),
        title=title,
        units=jcamp.yunits or None,
        extra={
            "source_file": str(path),
            "source_type": path.suffix.lower().lstrip("."),
            "jcamp.data_type": jcamp.data_type,
            "jcamp.headers": dict(jcamp.headers),
        },
        data_role="X_spectra",
    )


def _numeric_array(name: str, value: Any) -> np.ndarray:
    arr = np.asarray(value)
    if not np.issubdtype(arr.dtype, np.number):
        raise ValueError(f"NumPy array {name!r} must be numeric, got {arr.dtype}")
    if arr.ndim == 0 or arr.ndim > 2:
        raise ValueError(f"NumPy array {name!r} must be one- or two-dimensional, got {arr.ndim}D")
    return arr.astype(np.float64, copy=False)


def _load_npz_arrays(path: Path) -> tuple[np.ndarray, np.ndarray | None, list[str] | None, str]:
    with np.load(path, allow_pickle=False) as payload:
        keys = list(payload.files)
        if not keys:
            raise ValueError(f"Empty NumPy archive: {path.name}")

        data_key: str | None = None
        for candidate in ("X", "data", "spectra", "y", "intensity", "absorbance"):
            if candidate in payload:
                data_key = candidate
                break
        if data_key is None:
            numeric_keys: list[str] = []
            for key in keys:
                try:
                    arr = np.asarray(payload[key])
                except ValueError:
                    continue
                if np.issubdtype(arr.dtype, np.number) and 1 <= arr.ndim <= 2:
                    numeric_keys.append(key)
            if len(numeric_keys) != 1:
                raise ValueError("NumPy .npz files must contain an X array or exactly one numeric data array")
            data_key = numeric_keys[0]

        X = _numeric_array(data_key, payload[data_key])
        feature_values = None
        for axis_key in ("x", "wavenumber", "wavenumbers", "wavelength", "wavelengths"):
            if axis_key in payload:
                axis = np.asarray(payload[axis_key], dtype=np.float64)
                if axis.ndim == 1 and len(axis) == (X.shape[-1] if X.ndim > 1 else X.shape[0]):
                    feature_values = axis
                    break

        labels = None
        if "sample_labels" in payload:
            raw_labels = np.asarray(payload["sample_labels"])
            if raw_labels.ndim == 1:
                labels = [str(label) for label in raw_labels.tolist()]
        return X, feature_values, labels, data_key


def load_numpy_as_sherpa(filepath: Union[str, Path]) -> "SherpaDataset":
    """Load simple numeric .npy/.npz payloads without SpectroChemPy."""
    from spectra_sherpa.app.lib.axes import FeatureAxis, SampleAxis, SpectralAxis
    from spectra_sherpa.app.lib.sherpa_dataset import DomainContext, SherpaDataset

    path = Path(filepath)
    if path.suffix.lower() == ".npy":
        X = _numeric_array("array", np.load(path, allow_pickle=False))
        feature_values = None
        labels = None
        data_key = "array"
    else:
        X, feature_values, labels, data_key = _load_npz_arrays(path)

    if X.ndim == 1:
        X = X.reshape(1, -1)
    n_samples, n_features = X.shape[0], X.shape[-1]
    if labels is not None and len(labels) != n_samples:
        labels = None

    feature_axis = (
        SpectralAxis(values=feature_values, title="Spectral Axis", units=None)
        if feature_values is not None
        else FeatureAxis(labels=[str(i) for i in range(n_features)], title="Features")
    )
    return SherpaDataset(
        X=X,
        feature_axis=feature_axis,
        sample_axis=SampleAxis(labels=labels, title="Samples") if labels else None,
        domain=DomainContext(data_quantity="Intensity"),
        title=path.stem,
        extra={
            "source_file": str(path),
            "source_type": path.suffix.lower().lstrip("."),
            "numpy.data_key": data_key,
        },
        data_role="X_spectra" if feature_values is not None else "X_features",
    )


def load_open_spectral_file_as_sherpa(filepath: Union[str, Path]) -> "SherpaDataset | None":
    """Load base-install formats that do not require SpectroChemPy."""
    path = Path(filepath)
    ext = path.suffix.lower()
    if ext in {".jdx", ".dx"}:
        return load_jcamp_as_sherpa(path)
    if ext in {".npy", ".npz"}:
        return load_numpy_as_sherpa(path)
    return None


# ─────────────────────────────────────────────────────────────────────────────
# UNIFIED LOADER
# ─────────────────────────────────────────────────────────────────────────────


def load_spectrum(filepath: Union[str, Path]) -> "NDDataset":
    """
    Load a spectrum from any supported format.

    Automatically detects format based on file extension.

    Supported formats:
    - .csv - Two-column wavenumber/absorbance
    - .json - Calibration signature files
    - .mat - MATLAB files
    - .jdx, .dx - JCAMP-DX via bundled reader
    - .npy, .npz - NumPy numeric arrays
    - .spc, .spa, .spg, .srs, .opus - SpectroChemPy native formats

    Parameters
    ----------
    filepath : str or Path
        Path to spectrum file

    Returns
    -------
    NDDataset
        Loaded spectrum
    """
    filepath = Path(filepath)
    ext = filepath.suffix.lower()

    if ext == ".csv":
        return read_csv_spectrum(filepath)
    elif ext == ".json":
        return read_json_signature(filepath)
    elif ext == ".mat":
        datasets = read_mat_file(filepath)
        if len(datasets) == 1:
            return datasets[0]
        # Stack multiple spectra
        return stack_datasets(datasets)
    elif ext in [".jdx", ".dx", ".npy", ".npz"]:
        return load_open_spectral_file_as_sherpa(filepath)
    elif ext in [".spc", ".spa", ".spg", ".srs", ".opus"]:
        return read_spectral_file(filepath)
    else:
        raise ValueError(f"Unsupported file format: {ext}")


def stack_datasets(datasets: List["NDDataset"]) -> "NDDataset":
    """
    Stack multiple 1D spectra into a 2D dataset.

    Parameters
    ----------
    datasets : list[NDDataset]
        List of 1D spectra (must have same wavenumber grid)

    Returns
    -------
    NDDataset
        Stacked 2D dataset
    """
    if not datasets:
        raise ValueError("No datasets to stack")

    if len(datasets) == 1:
        return datasets[0]

    # Check feature-axis alignment
    ref_coord = datasets[0].x
    ref_wn = ref_coord.data
    for ds in datasets[1:]:
        if not np.allclose(ds.x.data, ref_wn, atol=1e-6):
            raise ValueError("Datasets must have aligned wavenumber grids to stack")

    # Stack data
    data = np.vstack([ds.data.reshape(1, -1) for ds in datasets])
    labels = [ds.title for ds in datasets]

    from .spectral.dataset import SpectralUnit, create_spectral_dataset

    ref_title = str(ref_coord.title) if getattr(ref_coord, "title", None) else None
    ref_units = str(ref_coord.units) if getattr(ref_coord, "units", None) else ""
    is_generic_axis = not ref_units or ref_units == "dimensionless" or (ref_title or "").strip().lower() == "index"

    if is_generic_axis:
        require_scp("Dataset stacking")
        result = scp.NDDataset(data, title="Stacked Data")
        result.x = scp.Coord(
            np.asarray(ref_wn, dtype=float),
            title=ref_title or "Index",
            units=ref_units or None,
        )
        result.y = scp.Coord(
            np.arange(len(labels), dtype=float),
            title="Samples",
            labels=[str(label) for label in labels],
        )
        result.units = SpectralUnit.DIMENSIONLESS.value
        result.meta["x_label"] = ref_title or "Index"
        result.meta["x_unit"] = ref_units or ""
        result.meta["data_type"] = "generic"
    else:
        result = create_spectral_dataset(
            data=data,
            wavenumbers=ref_wn,
            sample_labels=labels,
            units=SpectralUnit.ABSORBANCE,
            title="Stacked Spectra",
        )

    return result


# ─────────────────────────────────────────────────────────────────────────────
# CSV → SherpaDataset (handles matrix spectra + properties/tabular CSVs)
# ─────────────────────────────────────────────────────────────────────────────


def load_csv_as_sherpa(
    filepath: Union[str, Path],
    *,
    data_role: str | None = None,
    target_column: str | None = None,
    target_type: str | None = None,
) -> "SherpaDataset":
    """Read any CSV into a SherpaDataset.

    Handles two layouts:
    1. **Spectral matrix** — float-parseable column headers are x-axis values
       (wavelengths/wavenumbers), rows are samples.  String-named columns
       (e.g. ``sample_id``) become sample labels.
    2. **Tabular / properties** — all column headers are strings.  Numeric
       columns become features with string labels on the feature axis.

    Parameters
    ----------
    filepath : str or Path
        Path to CSV file.

    Returns
    -------
    SherpaDataset
    """
    from spectra_sherpa.app.lib.axes import FeatureAxis, SampleAxis, SpectralAxis
    from spectra_sherpa.app.lib.sherpa_dataset import DomainContext, SherpaDataset, TargetContext

    filepath = Path(filepath)
    df = pd.read_csv(filepath)
    overrides = None
    try:
        from spectra_sherpa.app.services.prepared_data import load_prepared_data_overrides

        overrides = load_prepared_data_overrides(file_path=str(filepath.resolve()))
        data_role = data_role or overrides.data_role
        target_column = target_column or overrides.target_column
        target_type = target_type or overrides.target_type
    except Exception:
        # CSV loading is used in lightweight contexts where the application
        # settings module may not be fully initialised. Explicit arguments
        # still work in those contexts.
        pass

    if df.empty:
        raise ValueError(f"Empty CSV file: {filepath}")

    axis_column_dataset = _load_axis_column_spectral_csv(df, filepath, data_role=data_role)
    if axis_column_dataset is not None:
        if overrides is not None:
            from spectra_sherpa.app.services.prepared_data import apply_dataset_prepared_data_overrides

            axis_column_dataset = apply_dataset_prepared_data_overrides(axis_column_dataset, overrides)
        return axis_column_dataset

    # Partition columns: float-parseable headers vs string headers.
    # Pandas mangles duplicate column names by appending ".N" suffixes
    # (e.g. "250.0" → "250.0", "250.0.1", "250.0.2").  Strip the
    # trailing ".N" before the float test so mangled duplicates are
    # still recognised as spectral columns.
    spectral_cols: list[str] = []
    x_vals: list[float] = []
    label_cols: list[str] = []

    _MANGLED_SUFFIX = re.compile(r"\.\d+$")

    for col in df.columns:
        try:
            x_vals.append(float(col))
            spectral_cols.append(col)
        except (ValueError, TypeError):
            # Check for pandas-mangled duplicate: strip trailing ".N"
            stripped = _MANGLED_SUFFIX.sub("", col)
            try:
                x_vals.append(float(stripped))
                spectral_cols.append(col)
            except (ValueError, TypeError):
                label_cols.append(col)

    if data_role == "X_features":
        spectral_cols = []
        x_vals = []
        label_cols = list(df.columns)

    # Extract sample labels from the first string column (if any)
    sample_labels: list[str] | None = None
    if label_cols:
        sample_labels = df[label_cols[0]].astype(str).tolist()

    title = filepath.stem

    if spectral_cols:
        # ── Spectral matrix path ──
        data = df[spectral_cols].values.astype(np.float64)
        wavelengths = np.array(x_vals, dtype=np.float64)
        axis_title, axis_units = _infer_numeric_spectral_axis(filepath, wavelengths, overrides)

        # Detect string-named numeric columns as reference properties
        extra: dict[str, Any] | None = None
        prop_label_cols = label_cols[1:] if sample_labels else label_cols
        if prop_label_cols:
            prop_cols = [c for c in prop_label_cols if pd.api.types.is_numeric_dtype(df[c])]
            if prop_cols:
                extra = {
                    "prop_names": prop_cols,
                    "properties": {col: df[col].tolist() for col in prop_cols},
                }

        # Ensure wavelengths are strictly monotonic for charting.
        # Datasets like Metal Etch OES have 43 wavelengths repeated at
        # 3 spatial positions (129 total).  Duplicate x-values cause
        # Plotly to draw diagonal jump lines.  Make them monotonic by
        # adding a cumulative offset that preserves the original values
        # at position 1 and shifts subsequent repeats just past the
        # previous group's maximum.
        if len(wavelengths) > 1 and not (
            bool(np.all(np.diff(wavelengths) > 0)) or bool(np.all(np.diff(wavelengths) < 0))
        ):
            mono = np.empty_like(wavelengths)
            offset = 0.0
            prev = wavelengths[0] - 1  # force first value to be "increasing"
            for i, v in enumerate(wavelengths):
                if v <= prev:
                    # New group detected — shift past the previous maximum
                    offset = mono[i - 1] + 1.0 if i > 0 else 0.0
                mono[i] = v + offset
                prev = v
            wavelengths = mono

        return SherpaDataset(
            X=data,
            feature_axis=SpectralAxis(values=wavelengths, title=axis_title, units=axis_units),
            sample_axis=SampleAxis(labels=sample_labels) if sample_labels else None,
            domain=DomainContext(expected_units=axis_units, data_quantity="Intensity"),
            extra=extra,
            title=title,
            data_role="X_spectra",
        )

    # ── Tabular / properties path ──
    # Named-column tables are generic multivariate data, not spectra.
    # Preserve numeric columns as features and keep a single non-numeric
    # column as an embedded categorical target when present.
    target_col = target_column if target_column in df.columns else None
    numeric_cols = [c for c in df.columns if pd.api.types.is_numeric_dtype(df[c]) and c != target_col]
    numeric_df = df[numeric_cols]
    if numeric_df.empty:
        raise ValueError(f"No numeric columns in {filepath.name}")

    data = numeric_df.values.astype(np.float64)
    col_names = list(numeric_df.columns)
    non_numeric_cols = [c for c in df.columns if not pd.api.types.is_numeric_dtype(df[c]) and c != target_col]

    target = None
    target_context = None
    extra2: dict[str, Any] = {
        "csv.feature_names": col_names,
    }

    inferred_target_col = target_col or (non_numeric_cols[0] if len(non_numeric_cols) == 1 else None)
    if inferred_target_col is not None:
        target = df[inferred_target_col].to_numpy()
        target_is_categorical = (
            target_type == "categorical"
            or target.dtype.kind in ("O", "S", "U")
            or (target_type is None and np.issubdtype(target.dtype, np.integer) and len(np.unique(target)) <= 30)
        )
        target_context = TargetContext(
            target_type="categorical" if target_is_categorical else "continuous",
            target_name=inferred_target_col,
            n_classes=len(np.unique(target)) if target_is_categorical else None,
            class_names=sorted({str(label) for label in target}) if target_is_categorical else None,
        )
        extra2["csv.target_column"] = inferred_target_col
        extra2["csv.target_type"] = "categorical" if target_is_categorical else "continuous"

    return SherpaDataset(
        X=data,
        feature_axis=FeatureAxis(labels=col_names, title="Property"),
        sample_axis=SampleAxis(values=np.arange(data.shape[0], dtype=np.float64), title="Sample"),
        target=target,
        target_context=target_context,
        domain=DomainContext(
            technique="generic",
            sample_type=title,
        ),
        extra=extra2,
        backend="pandas",
        title=title,
        data_role="X_features",
    )


__all__ = [
    "read_csv_spectrum",
    "read_csv_directory",
    "read_json_signature",
    "read_mat_file",
    "read_spectral_file",
    "load_spectrum",
    "load_csv_as_sherpa",
    "stack_datasets",
    "extract_concentration",
    "extract_pathlength",
]
