"""
Parquet serialization for NDDataset with metadata sidecar.

Provides efficient storage of spectral datasets using Apache Parquet
for the data matrix and a JSON sidecar for coordinates, units, and metadata.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict

import numpy as np
import pandas as pd

if TYPE_CHECKING:
    from app.lib.scp_compat import NDDataset


def _serialize_meta(meta: Dict[str, Any]) -> Dict[str, Any]:
    """Convert metadata to JSON-serializable format."""
    result = {}
    for key, value in meta.items():
        if isinstance(value, np.ndarray):
            result[key] = value.tolist()
        elif isinstance(value, (np.integer, np.floating)):
            result[key] = value.item()
        elif isinstance(value, dict):
            result[key] = _serialize_meta(value)
        elif isinstance(value, list):
            result[key] = [
                _serialize_meta(v) if isinstance(v, dict) else v for v in value
            ]
        else:
            result[key] = value
    return result


def save_dataset_parquet(dataset: "NDDataset", path: Path) -> None:
    """
    Save NDDataset to Parquet with JSON metadata sidecar.

    Files created:
    - {path}.parquet - Data matrix
    - {path}.meta.json - Coordinates, units, provenance

    Parameters
    ----------
    dataset : NDDataset
        Dataset to save
    path : Path
        Base path (without extension)
    """
    path = Path(path)

    # Save data as parquet
    data = dataset.data
    if data.ndim == 1:
        data = data.reshape(1, -1)

    df = pd.DataFrame(
        data, columns=[f"wn_{i}" for i in range(data.shape[-1])]
    )
    df.to_parquet(path.with_suffix(".parquet"), engine="pyarrow")

    # Build metadata sidecar
    meta = {
        "shape": list(dataset.shape),
        "units": str(dataset.units) if dataset.units else None,
        "title": dataset.title if dataset.title else None,
    }

    # X coordinate (wavenumbers)
    if hasattr(dataset, "x") and dataset.x is not None:
        meta["x_coord"] = (
            dataset.x.data.tolist()
            if hasattr(dataset.x, "data")
            else list(dataset.x)
        )
        meta["x_units"] = str(dataset.x.units) if hasattr(dataset.x, "units") else None
        meta["x_title"] = dataset.x.title if hasattr(dataset.x, "title") else None

    # Y coordinate (samples)
    if hasattr(dataset, "y") and dataset.y is not None:
        y_data = dataset.y.data if hasattr(dataset.y, "data") else dataset.y
        # Handle string labels vs numeric indices
        if hasattr(y_data, "tolist"):
            meta["y_coord"] = y_data.tolist()
        else:
            meta["y_coord"] = list(y_data)
        meta["y_units"] = str(dataset.y.units) if hasattr(dataset.y, "units") else None
        meta["y_title"] = dataset.y.title if hasattr(dataset.y, "title") else None

    # Custom metadata
    if hasattr(dataset, "meta") and dataset.meta:
        meta["meta"] = _serialize_meta(dict(dataset.meta))

    # Write sidecar
    with open(path.with_suffix(".meta.json"), "w") as f:
        json.dump(meta, f, indent=2, default=str)


def load_dataset_parquet(path: Path) -> "NDDataset":
    """
    Load NDDataset from Parquet + metadata sidecar.

    Parameters
    ----------
    path : Path
        Base path (with or without extension)

    Returns
    -------
    NDDataset
        Loaded dataset with coordinates and metadata
    """
    from app.lib.scp_compat import scp

    path = Path(path)

    # Handle path with or without extension
    parquet_path = path.with_suffix(".parquet")
    meta_path = path.with_suffix(".meta.json")

    # Load data
    df = pd.read_parquet(parquet_path)
    data = df.values

    # Load metadata
    with open(meta_path) as f:
        meta = json.load(f)

    # Create dataset
    dataset = scp.NDDataset(data)

    # Restore X coordinate
    if meta.get("x_coord"):
        dataset.x = scp.Coord(
            meta["x_coord"],
            units=meta.get("x_units", "cm^-1"),
            title=meta.get("x_title", "Wavenumber"),
        )

    # Restore Y coordinate
    if meta.get("y_coord"):
        dataset.y = scp.Coord(
            meta["y_coord"],
            units=meta.get("y_units"),
            title=meta.get("y_title", "Sample"),
        )

    # Restore units and title
    if meta.get("units"):
        dataset.units = meta["units"]
    if meta.get("title"):
        dataset.title = meta["title"]

    # Restore custom metadata
    if meta.get("meta"):
        dataset.meta.update(meta["meta"])

    return dataset
