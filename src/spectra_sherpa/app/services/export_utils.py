"""Shared utilities for exported workflow scripts.

This module is imported by generated Python scripts and notebooks.
It provides artifact serialization, JSON helpers, and a Plotly fallback
so that generated code stays concise and focused on the workflow logic.
"""

from __future__ import annotations

import json
import os
import zipfile
from datetime import datetime
from typing import Any

import numpy as np

# ── JSON helpers ──────────────────────────────────────────────────


def json_default(value: Any) -> Any:
    """JSON encoder fallback for numpy types."""
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, (list, tuple, set)):
        return list(value)
    return repr(value)


def to_jsonable(value: Any) -> Any:
    """Recursively convert a value to JSON-serializable form."""
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, dict):
        return {str(k): to_jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [to_jsonable(v) for v in value]
    if hasattr(value, "to_plotly_json"):
        return value.to_plotly_json()
    if hasattr(value, "data"):
        return {"type": type(value).__name__, "shape": list(np.asarray(value.data).shape)}
    return repr(value)


def save_json(path: str, value: Any) -> None:
    """Write *value* as indented JSON to *path*."""
    with open(path, "w") as f:
        json.dump(value, f, indent=2, default=json_default)


# ── Array I/O ─────────────────────────────────────────────────────


def write_array_artifact(path_stem: str, value: Any) -> None:
    """Save a numpy array to CSV (or JSON fallback)."""
    arr = np.asarray(value)
    if arr.ndim == 0:
        arr = arr.reshape(1, 1)
    elif arr.ndim == 1:
        arr = arr.reshape(-1, 1)
    try:
        if np.issubdtype(arr.dtype, np.number) or np.issubdtype(arr.dtype, np.bool_):
            np.savetxt(f"{path_stem}.csv", arr, delimiter=",")
        else:
            np.savetxt(f"{path_stem}.csv", arr.astype(str), delimiter=",", fmt="%s")
    except Exception:
        save_json(f"{path_stem}.json", arr.tolist())


# ── Artifact export ───────────────────────────────────────────────


def export_artifacts(results: dict, workflow_name: str = "workflow") -> str:
    """Save all workflow results to individual files and create a zip archive.

    Handles SherpaDataset objects, numpy arrays, Plotly figures,
    scikit-learn-style model objects, and plain dicts/scalars.

    Returns the path to the created zip file.
    """
    import pickle

    from spectra_sherpa.app.lib.sherpa_dataset import SherpaDataset

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = f"{workflow_name}_{timestamp}"
    os.makedirs(out_dir, exist_ok=True)
    print(f"\nExporting artifacts to {out_dir}/")

    for key, value in results.items():
        if isinstance(value, SherpaDataset):
            write_array_artifact(os.path.join(out_dir, f"{key}_data"), value.data)
            meta = {"shape": list(np.asarray(value.data).shape)}
            if value.feature_axis is not None:
                meta["feature_axis"] = np.asarray(value.feature_axis.data).tolist()
            if value.target is not None:
                write_array_artifact(os.path.join(out_dir, f"{key}_target"), value.target)
            save_json(os.path.join(out_dir, f"{key}_meta.json"), meta)

        elif isinstance(value, dict):
            summary: dict[str, Any] = {}
            for sub_key, sub_val in value.items():
                fname = f"{key}_{sub_key}"
                if isinstance(sub_val, SherpaDataset):
                    write_array_artifact(os.path.join(out_dir, fname), sub_val.data)
                elif isinstance(sub_val, np.ndarray):
                    write_array_artifact(os.path.join(out_dir, fname), sub_val)
                elif hasattr(sub_val, "to_plotly_json"):
                    sub_val.write_html(os.path.join(out_dir, f"{fname}.html"))
                    save_json(os.path.join(out_dir, f"{fname}.json"), sub_val.to_plotly_json())
                elif hasattr(sub_val, "predict"):  # model object
                    with open(os.path.join(out_dir, f"{fname}.pkl"), "wb") as f:
                        pickle.dump(sub_val, f)
                else:
                    summary[sub_key] = to_jsonable(sub_val)
            if summary:
                save_json(os.path.join(out_dir, f"{key}_summary.json"), summary)

        elif isinstance(value, np.ndarray):
            write_array_artifact(os.path.join(out_dir, key), value)
        else:
            save_json(os.path.join(out_dir, f"{key}.json"), to_jsonable(value))

    # Save top-level Plotly or matplotlib figures
    for key, value in results.items():
        if hasattr(value, "to_plotly_json"):
            value.write_html(os.path.join(out_dir, f"{key}.html"))
            save_json(os.path.join(out_dir, f"{key}.json"), value.to_plotly_json())
    try:
        import matplotlib.pyplot as _plt

        for i, fig in enumerate(_plt.get_fignums()):
            _plt.figure(fig).savefig(
                os.path.join(out_dir, f"figure_{i + 1}.png"),
                dpi=150,
                bbox_inches="tight",
            )
    except Exception:
        pass

    # Zip everything
    zip_name = f"{out_dir}.zip"
    with zipfile.ZipFile(zip_name, "w", zipfile.ZIP_DEFLATED) as zf:
        for root, _dirs, files in os.walk(out_dir):
            for file in files:
                fpath = os.path.join(root, file)
                zf.write(fpath, os.path.relpath(fpath, os.path.dirname(out_dir)))
    print(f"  Artifacts zipped to {zip_name}")
    return zip_name
