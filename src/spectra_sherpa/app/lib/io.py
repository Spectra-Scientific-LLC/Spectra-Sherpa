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
from typing import Dict, Iterable, List, Optional, Tuple, Union

import numpy as np

logger = logging.getLogger(__name__)
import pandas as pd

try:
    from scipy.io import loadmat

    HAS_SCIPY = True
except ImportError:
    HAS_SCIPY = False
    loadmat = None

from spectra_sherpa.app.lib.scp_compat import scp, NDDataset, HAS_SCP, require_scp


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
    clean_segment = (
        segment.rstrip("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ)")
        .replace("-", ".")
        .strip()
    )

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
    from .spectral.dataset import create_spectral_dataset, SpectralUnit

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
    from .spectral.dataset import create_spectral_dataset, SpectralUnit

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

    from .spectral.dataset import create_spectral_dataset, SpectralUnit

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
        raise ValueError(
            f"No wavenumber axis found in {filepath}. "
            "Provide a wavenumber array or a 2-column matrix."
        )

    if wavenumber is None or absorbance is None:
        raise ValueError(
            f"Could not find spectral data in {filepath}. "
            "Expected variables like 'wavenumber'/'absorbance'."
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
                f"Wavenumber/absorbance length mismatch in {filepath}: "
                f"{len(wavenumber)} vs {len(absorbance)}"
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


def read_parquet_spectrum(filepath: Path) -> "NDDataset":
    """
    Read a spectrum from Parquet format with metadata sidecar.

    Expects:
    - {path}.parquet - Data matrix
    - {path}.meta.json - Coordinates and metadata

    Parameters
    ----------
    filepath : Path
        Path to .parquet file or base path

    Returns
    -------
    NDDataset
        Loaded spectrum with coordinates and metadata
    """
    from .spectral.serialization import load_dataset_parquet

    # Handle both .parquet and base path
    base_path = filepath.with_suffix("") if filepath.suffix == ".parquet" else filepath
    return load_dataset_parquet(base_path)


def load_spectrum(filepath: Union[str, Path]) -> "NDDataset":
    """
    Load a spectrum from any supported format.

    Automatically detects format based on file extension.

    Supported formats:
    - .csv - Two-column wavenumber/absorbance
    - .json - Calibration signature files
    - .mat - MATLAB files
    - .parquet - Parquet with .meta.json sidecar
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
    elif ext == ".parquet":
        return read_parquet_spectrum(filepath)
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

    from .spectral.dataset import create_spectral_dataset, SpectralUnit

    result = create_spectral_dataset(
        data=data,
        wavenumbers=ref_wn,
        sample_labels=labels,
        units=SpectralUnit.ABSORBANCE,
        title="Stacked Spectra",
    )

    return result


__all__ = [
    "read_csv_spectrum",
    "read_csv_directory",
    "read_json_signature",
    "read_mat_file",
    "read_spectral_file",
    "read_parquet_spectrum",
    "load_spectrum",
    "stack_datasets",
    "extract_concentration",
    "extract_pathlength",
]
