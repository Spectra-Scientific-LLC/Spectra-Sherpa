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
FILENAME_PATTERN = re.compile(r"^(?P<label>[A-Z0-9]+)[\s_-]?.*\.CSV$", re.IGNORECASE)
CONC_PATTERN = re.compile(r"\(([^()]*?)ppm", re.IGNORECASE)


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
        raise ValueError(f"No wavenumber axis found in {filepath}. " "Provide a wavenumber array or a 2-column matrix.")

    if wavenumber is None or absorbance is None:
        raise ValueError(
            f"Could not find spectral data in {filepath}. " "Expected variables like 'wavenumber'/'absorbance'."
        )

    datasets = []

    # Handle 2D absorbance (multiple spectra)
    if absorbance.ndim == 2:
        if absorbance.shape[1] == len(wavenumber):
            # Rows are spectra
            for i in range(absorbance.shape[0]):
                ds = create_spectral_dataset(
                    data=absorbance[i, :],
                    wavenumbers=wavenumber,
                    units=SpectralUnit.ABSORBANCE,
                    title=f"{label}_{i + 1}" if absorbance.shape[0] > 1 else label,
                )
                ds.meta["source_file"] = str(filepath)
                ds.meta["source_type"] = "mat"
                datasets.append(ds)
        elif absorbance.shape[0] == len(wavenumber):
            # Columns are spectra
            for i in range(absorbance.shape[1]):
                ds = create_spectral_dataset(
                    data=absorbance[:, i],
                    wavenumbers=wavenumber,
                    units=SpectralUnit.ABSORBANCE,
                    title=f"{label}_{i + 1}" if absorbance.shape[1] > 1 else label,
                )
                ds.meta["source_file"] = str(filepath)
                ds.meta["source_type"] = "mat"
                datasets.append(ds)
    else:
        # Single spectrum
        absorbance = absorbance.flatten()
        if len(wavenumber) != len(absorbance):
            raise ValueError(
                f"Wavenumber/absorbance length mismatch in {filepath}: " f"{len(wavenumber)} vs {len(absorbance)}"
            )
        ds = create_spectral_dataset(
            data=absorbance,
            wavenumbers=wavenumber,
            units=SpectralUnit.ABSORBANCE,
            title=label,
        )
        ds.meta["source_file"] = str(filepath)
        ds.meta["source_type"] = "mat"
        datasets.append(ds)

    return datasets


# ─────────────────────────────────────────────────────────────────────────────
# SPECTROCHEMPY FORMAT READING
# ─────────────────────────────────────────────────────────────────────────────


def read_spectral_file(filepath: Path) -> "NDDataset":
    """
    Read spectral files using SpectroChemPy.

    Supports: .jdx, .dx, .spc, .spa, .spg, .opus

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

    if ext in [".jdx", ".dx"]:
        dataset = scp.read_jcamp(str(filepath))
    elif ext == ".spc":
        dataset = scp.read_spc(str(filepath))
    elif ext == ".spa":
        dataset = scp.read_omnic(str(filepath))
    elif ext == ".spg":
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
    - .jdx, .dx, .spc, .spa, .spg, .opus - SpectroChemPy native formats

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
    elif ext in [".jdx", ".dx", ".spc", ".spa", ".spg", ".opus"]:
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

    # Check wavenumber alignment
    ref_wn = datasets[0].x.data
    for ds in datasets[1:]:
        if not np.allclose(ds.x.data, ref_wn, atol=1e-6):
            raise ValueError("Datasets must have aligned wavenumber grids to stack")

    # Stack data
    data = np.vstack([ds.data.reshape(1, -1) for ds in datasets])
    labels = [ds.title for ds in datasets]

    from .spectral.dataset import SpectralUnit, create_spectral_dataset

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


def load_csv_as_sherpa(filepath: Union[str, Path]) -> "SherpaDataset":
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
    from spectra_sherpa.app.lib.sherpa_dataset import SherpaDataset

    filepath = Path(filepath)
    df = pd.read_csv(filepath)

    if df.empty:
        raise ValueError(f"Empty CSV file: {filepath}")

    # Partition columns: float-parseable headers vs string headers
    spectral_cols: list[str] = []
    x_vals: list[float] = []
    label_cols: list[str] = []

    for col in df.columns:
        try:
            x_vals.append(float(col))
            spectral_cols.append(col)
        except (ValueError, TypeError):
            label_cols.append(col)

    # Extract sample labels from the first string column (if any)
    sample_labels: list[str] | None = None
    if label_cols:
        sample_labels = df[label_cols[0]].astype(str).tolist()

    title = filepath.stem

    if spectral_cols:
        # ── Spectral matrix path ──
        data = df[spectral_cols].values.astype(np.float64)
        wavelengths = np.array(x_vals, dtype=np.float64)

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

        return SherpaDataset(
            X=data,
            feature_axis=SpectralAxis(values=wavelengths, title="Wavenumber"),
            sample_axis=SampleAxis(labels=sample_labels) if sample_labels else None,
            extra=extra,
            title=title,
        )

    # ── Tabular / properties path ──
    # The first label column was used for sample labels — exclude it from features.
    # Remaining columns with numeric data are the property features.
    id_cols = [label_cols[0]] if label_cols else []
    feature_df = df.drop(columns=id_cols, errors="ignore")
    numeric_df = feature_df.select_dtypes(include="number")
    if numeric_df.empty:
        raise ValueError(f"No numeric columns in {filepath.name}")

    data = numeric_df.values.astype(np.float64)
    col_names = list(numeric_df.columns)

    return SherpaDataset(
        X=data,
        feature_axis=FeatureAxis(labels=col_names, title="Property"),
        sample_axis=SampleAxis(labels=sample_labels) if sample_labels else None,
        title=title,
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
