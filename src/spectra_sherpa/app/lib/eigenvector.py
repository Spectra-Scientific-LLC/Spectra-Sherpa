"""
Eigenvector Research public dataset parser and catalog.

Handles the Eigenvector DataSet CSV and .mat export formats used by
the public benchmark datasets at https://eigenvector.com/resources/data-sets/

Usage::

    from app.lib.eigenvector import load_eigenvector_dataset, DATASET_CATALOG

    result = load_eigenvector_dataset("diesel_nir")
    spectra = result["spectra"]       # (784, 401) numpy array
    props   = result["properties"]    # (784, 7) numpy array (with NaN)
    wl      = result["wavelengths"]   # (401,) numpy array [750..1550 nm]
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Data directory (bundled with the package)
# ---------------------------------------------------------------------------

EIGENVECTOR_DATA_DIR = (
    Path(__file__).resolve().parent.parent.parent / "data" / "eigenvector"
)

# ---------------------------------------------------------------------------
# Dataset catalog
# ---------------------------------------------------------------------------

DATASET_CATALOG: dict[str, dict[str, Any]] = {
    "diesel_nir": {
        "label": "Diesel NIR (784 samples, 401 wavelengths, 750-1550 nm)",
        "format": "csv",
        "spec_file": "diesel_csv/diesel_spec.csv",
        "prop_file": "diesel_csv/diesel_prop.csv",
        "spec_has_axisscale": True,
        "prop_names": ["BP50", "CN", "D4052", "FLASH", "FREEZE", "TOTAL", "VISC"],
        "technique": "NIR",
        "x_title": "Wavelength",
        "x_units": "nm",
        "description": "SWRI Diesel fuels — NIR spectra with 7 reference properties",
    },
    "corn_m5": {
        "label": "Corn M5 NIR (80 samples, 700 channels)",
        "format": "mat",
        "mat_file": "corn_mat/corn.mat",
        "spec_key": "m5spec",
        "prop_key": "propvals",
        "prop_names": ["Moisture", "Oil", "Protein", "Starch"],
        "technique": "NIR",
        "x_title": "Channel",
        "x_units": None,
        "description": "Corn NIR (Infratec M5) — moisture, oil, protein, starch",
    },
    "corn_mp5": {
        "label": "Corn MP5 NIR (80 samples, 700 channels)",
        "format": "mat",
        "mat_file": "corn_mat/corn.mat",
        "spec_key": "mp5spec",
        "prop_key": "propvals",
        "prop_names": ["Moisture", "Oil", "Protein", "Starch"],
        "technique": "NIR",
        "x_title": "Channel",
        "x_units": None,
        "description": "Corn NIR (Infratec MP5) — moisture, oil, protein, starch",
    },
    "corn_mp6": {
        "label": "Corn MP6 NIR (80 samples, 700 channels)",
        "format": "mat",
        "mat_file": "corn_mat/corn.mat",
        "spec_key": "mp6spec",
        "prop_key": "propvals",
        "prop_names": ["Moisture", "Oil", "Protein", "Starch"],
        "technique": "NIR",
        "x_title": "Channel",
        "x_units": None,
        "description": "Corn NIR (Infratec MP6) — moisture, oil, protein, starch",
    },
}


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
            raise ValueError(
                f"Expected 'Axisscale' in row 9, got: {axisscale_row.iloc[0]!r}"
            )
        axis_vals = []
        for v in axisscale_row.iloc[2:]:
            v = str(v).strip().rstrip(",")
            if v:
                axis_vals.append(float(v))
        axis_values = np.array(axis_vals)
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
        raise ValueError(
            f"Key '{spec_key}' not found in {path.name}. "
            f"Available keys: {available}"
        )

    ds = mat[spec_key]
    spec_data = ds["data"][0, 0]

    # Extract metadata from the structured array
    file_metadata = extract_mat_metadata(ds)

    # Try to extract axis scale (wavelength/channel values)
    axis_values = None
    try:
        axisscale = ds["axisscale"][0, 0]
        if axisscale.size > 0 and axisscale.ndim >= 2 and axisscale.shape[1] > 1:
            col_axis = axisscale[0, 1].flatten()
            if col_axis.size == spec_data.shape[1]:
                axis_values = col_axis
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
# Main loader
# ---------------------------------------------------------------------------


def load_eigenvector_dataset(
    name: str,
    data_dir: Path | None = None,
) -> dict[str, Any]:
    """Load an Eigenvector Research public dataset by name.

    Args:
        name: Dataset name from DATASET_CATALOG.
        data_dir: Override data directory (for testing). Defaults to
            the bundled data directory.

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
            f"Unsupported Eigenvector dataset: {name!r}\n"
            f"Supported datasets: {', '.join(DATASET_CATALOG)}"
        )

    catalog = DATASET_CATALOG[name]
    base_dir = data_dir or EIGENVECTOR_DATA_DIR

    if catalog["format"] == "csv":
        spec_path = base_dir / catalog["spec_file"]
        if not spec_path.exists():
            raise FileNotFoundError(
                f"Eigenvector data file not found: {spec_path}\n"
                f"Expected bundled data at: {base_dir}"
            )

        spectra, sample_ids, wavelengths = parse_eigenvector_csv(
            spec_path, has_axisscale=catalog.get("spec_has_axisscale", False)
        )

        file_metadata = extract_csv_metadata(spec_path)

        properties = None
        if "prop_file" in catalog:
            prop_path = base_dir / catalog["prop_file"]
            if prop_path.exists():
                properties, _, _ = parse_eigenvector_csv(
                    prop_path, has_axisscale=False
                )

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
                f"Expected bundled data at: {base_dir}"
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
            prop_stats.append({
                "name": pname,
                "min": float(np.nanmin(col)) if col.size > nan_count else None,
                "max": float(np.nanmax(col)) if col.size > nan_count else None,
                "mean": float(np.nanmean(col)) if col.size > nan_count else None,
                "nan_count": nan_count,
                "nan_pct": round(100 * nan_count / len(col), 1) if len(col) > 0 else 0,
            })
        info["property_stats"] = prop_stats

    return info
