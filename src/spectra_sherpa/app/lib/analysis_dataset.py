"""
Canonical runtime dataset for DAG execution.

AnalysisDataset is the DAG's native data container. NDDataset (SpectroChemPy)
and sklearn Bunches are converted to/from this type at system boundaries via
adapters.  All portable DAG nodes operate on AnalysisDataset directly.

Wire-format contract: ``to_dict()`` emits ``type: "NDDataset"`` and
``x_axis.data`` (not ``x_axis.values``) so that the existing frontend
(nodeOutput.ts, NodeDetailView.vue) works without changes.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Dict, List, Optional, Union

import numpy as np


# ---------------------------------------------------------------------------
# JSON safety helper
# ---------------------------------------------------------------------------

def _json_safe(obj: Any) -> Any:
    """Recursively convert values to JSON-serializable types."""
    if obj is None or isinstance(obj, (bool, int, float, str)):
        return obj
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    if isinstance(obj, np.integer):
        return int(obj)
    if isinstance(obj, np.floating):
        return float(obj)
    if isinstance(obj, np.ndarray):
        return obj.tolist()
    if isinstance(obj, dict):
        return {k: _json_safe(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_json_safe(v) for v in obj]
    return str(obj)


# ---------------------------------------------------------------------------
# AxisInfo — lightweight coordinate axis
# ---------------------------------------------------------------------------

@dataclass
class AxisInfo:
    """Axis metadata for one dimension of AnalysisDataset.

    Provides Coord-compatible interface (``.data``, ``.units``, ``.title``,
    ``.labels``, ``.copy()``, ``len()``) so existing node code that accesses
    coordinates through these attributes works unchanged.
    """

    values: Optional[np.ndarray] = None
    labels: Optional[List[str]] = None
    units: Optional[str] = None
    title: Optional[str] = None

    # -- Coord compatibility -------------------------------------------------

    @property
    def data(self) -> Optional[np.ndarray]:
        """Alias for *values* — matches ``Coord.data``."""
        return self.values

    @property
    def shape(self) -> tuple:
        return self.values.shape if self.values is not None else ()

    def __len__(self) -> int:
        if self.values is not None:
            return len(self.values)
        if self.labels is not None:
            return len(self.labels)
        return 0

    def copy(self) -> AxisInfo:
        """Deep copy."""
        return AxisInfo(
            values=self.values.copy() if self.values is not None else None,
            labels=list(self.labels) if self.labels is not None else None,
            units=self.units,
            title=self.title,
        )


# ---------------------------------------------------------------------------
# AnalysisDataset — canonical DAG container
# ---------------------------------------------------------------------------

class AnalysisDataset:
    """Canonical runtime dataset for DAG execution.

    Attributes:
        X:          2-D numeric array  (n_samples, n_features)
        x_axis:     Feature / spectral axis (AxisInfo or None)
        y_axis:     Sample axis (AxisInfo or None)
        target:     Optional target values / labels for supervised learning
        meta:       Arbitrary metadata dict
        provenance: Processing-history list (kept in sync with
                    ``meta["processing_history"]``)
        backend:    Origin tag — ``"numpy"``, ``"scp"``, ``"sklearn"``
        title:      Dataset title / name
        units:      Data-value units (e.g. ``"absorbance"``)
    """

    def __init__(
        self,
        X: Any,
        x_axis: Optional[AxisInfo] = None,
        y_axis: Optional[AxisInfo] = None,
        target: Optional[Any] = None,
        meta: Optional[Dict[str, Any]] = None,
        provenance: Optional[List[Dict[str, Any]]] = None,
        backend: str = "numpy",
        title: Optional[str] = None,
        units: Optional[str] = None,
    ) -> None:
        self.X = np.atleast_2d(np.asarray(X, dtype=np.float64))
        self.x_axis = x_axis
        self.y_axis = y_axis
        self.target = target
        self.meta: Dict[str, Any] = meta if meta is not None else {}
        self.provenance: List[Dict[str, Any]] = provenance if provenance is not None else []
        self.backend = backend
        self.title = title
        self.units = units

        # Keep meta["processing_history"] in sync with self.provenance
        self.meta.setdefault("processing_history", self.provenance)

    # -- NDDataset compatibility properties ----------------------------------

    @property
    def data(self) -> np.ndarray:
        """Alias for ``X`` — matches ``NDDataset.data``."""
        return self.X

    @property
    def shape(self) -> tuple:
        return self.X.shape

    @property
    def ndim(self) -> int:
        return self.X.ndim

    @property
    def x(self) -> Optional[AxisInfo]:
        return self.x_axis

    @x.setter
    def x(self, value: Any) -> None:
        if value is None:
            self.x_axis = None
        elif isinstance(value, AxisInfo):
            self.x_axis = value
        elif hasattr(value, "data"):
            # Coord-like object — adapt to AxisInfo
            self.x_axis = _coord_to_axis_info(value)
        else:
            raise TypeError(f"Cannot assign {type(value)} to x axis")

    @property
    def y(self) -> Optional[AxisInfo]:
        return self.y_axis

    @y.setter
    def y(self, value: Any) -> None:
        if value is None:
            self.y_axis = None
        elif isinstance(value, AxisInfo):
            self.y_axis = value
        elif hasattr(value, "data"):
            self.y_axis = _coord_to_axis_info(value)
        else:
            raise TypeError(f"Cannot assign {type(value)} to y axis")

    # -- Copy ----------------------------------------------------------------

    def copy(self) -> AnalysisDataset:
        """Deep copy with all axes, meta, provenance."""
        new_provenance = copy.deepcopy(self.provenance)
        new_meta = copy.deepcopy(self.meta)
        # Re-link so that meta["processing_history"] IS new_provenance
        new_meta["processing_history"] = new_provenance
        return AnalysisDataset(
            X=self.X.copy(),
            x_axis=self.x_axis.copy() if self.x_axis is not None else None,
            y_axis=self.y_axis.copy() if self.y_axis is not None else None,
            target=(
                self.target.copy()
                if isinstance(self.target, np.ndarray)
                else list(self.target) if self.target is not None else None
            ),
            meta=new_meta,
            provenance=new_provenance,
            backend=self.backend,
            title=self.title,
            units=self.units,
        )

    # -- Indexing / slicing --------------------------------------------------

    def __getitem__(self, key: Any) -> AnalysisDataset:
        """Support boolean masking and tuple slicing.

        - ``ds[bool_mask]``  — row selection (samples)
        - ``ds[i]``          — single row → still 2-D (1, n_features)
        - ``ds[:, a:b]``     — column slice (features)
        - ``ds[row, col]``   — combined
        """
        if isinstance(key, np.ndarray) and key.dtype == bool:
            # Boolean mask on rows
            new_X = self.X[key]
            new_y = _slice_axis(self.y_axis, key)
            new_target = (
                self.target[key]
                if self.target is not None and hasattr(self.target, "__getitem__")
                else self.target
            )
            return AnalysisDataset(
                X=new_X,
                x_axis=self.x_axis.copy() if self.x_axis else None,
                y_axis=new_y,
                target=new_target,
                meta=copy.deepcopy(self.meta),
                provenance=copy.deepcopy(self.provenance),
                backend=self.backend,
                title=self.title,
                units=self.units,
            )

        if isinstance(key, (int, np.integer)):
            # Single row → keep 2-D
            new_X = self.X[key : key + 1]
            new_y = _slice_axis(self.y_axis, slice(key, key + 1))
            return AnalysisDataset(
                X=new_X,
                x_axis=self.x_axis.copy() if self.x_axis else None,
                y_axis=new_y,
                meta=copy.deepcopy(self.meta),
                provenance=copy.deepcopy(self.provenance),
                backend=self.backend,
                title=self.title,
                units=self.units,
            )

        if isinstance(key, tuple) and len(key) == 2:
            row_key, col_key = key
            new_X = self.X[row_key, col_key] if not isinstance(col_key, slice) else self.X[row_key][:, col_key] if isinstance(row_key, slice) else self.X[key]
            # Ensure 2-D
            new_X = np.atleast_2d(new_X)
            new_y = _slice_axis(self.y_axis, row_key) if not isinstance(row_key, type(None)) else self.y_axis
            new_x = _slice_axis(self.x_axis, col_key) if not isinstance(col_key, type(None)) else self.x_axis
            return AnalysisDataset(
                X=new_X,
                x_axis=new_x,
                y_axis=new_y,
                meta=copy.deepcopy(self.meta),
                provenance=copy.deepcopy(self.provenance),
                backend=self.backend,
                title=self.title,
                units=self.units,
            )

        # Fallback: let numpy handle it
        new_X = np.atleast_2d(self.X[key])
        return AnalysisDataset(
            X=new_X,
            x_axis=self.x_axis.copy() if self.x_axis else None,
            y_axis=self.y_axis.copy() if self.y_axis else None,
            meta=copy.deepcopy(self.meta),
            provenance=copy.deepcopy(self.provenance),
            backend=self.backend,
            title=self.title,
            units=self.units,
        )

    # -- Batch coordinate assignment -----------------------------------------

    def set_coordset(self, **kwargs: Any) -> None:
        """Batch coordinate assignment (NDDataset compat)."""
        if "x" in kwargs:
            self.x = kwargs["x"]
        if "y" in kwargs:
            self.y = kwargs["y"]

    # -- Serialization -------------------------------------------------------

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to JSON-safe dict for API responses.

        Wire format matches existing NDDataset serialization:
        - ``type: "NDDataset"`` (frontend checks ``value.type === "NDDataset"``)
        - ``x_axis.data`` (frontend accesses ``raw.x_axis.data.length``)
        """
        # Sanitize NaN/Inf → None for JSON safety (matches NDDataset path)
        safe_data = np.where(np.isfinite(self.X), self.X, None).tolist()

        result: Dict[str, Any] = {
            "type": "NDDataset",
            "shape": list(self.shape),
            "data": safe_data,
            "n_samples": self.shape[0] if self.ndim > 1 else 1,
            "n_features": self.shape[-1] if len(self.shape) > 0 else 0,
            "title": self.title or ("Data"),
            "units": self.units,
            "backend": self.backend,
            "metadata": {},
        }
        if self.x_axis:
            result["x_axis"] = {
                "data": self.x_axis.values.tolist() if self.x_axis.values is not None else None,
                "labels": self.x_axis.labels,
                "units": self.x_axis.units,
                "title": self.x_axis.title,
            }
        if self.y_axis:
            result["y_axis"] = {
                "data": self.y_axis.values.tolist() if self.y_axis.values is not None else None,
                "labels": self.y_axis.labels,
                "units": self.y_axis.units,
                "title": self.y_axis.title,
            }
        if self.target is not None:
            result["target"] = (
                self.target.tolist()
                if isinstance(self.target, np.ndarray)
                else list(self.target)
            )
        result["metadata"]["processing_history"] = _json_safe(self.provenance)
        result["metadata"]["data_type"] = "generic"
        result["metadata"]["is_spectra"] = False
        for k, v in self.meta.items():
            if k != "processing_history":
                result["metadata"][k] = _json_safe(v)
        return result

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> AnalysisDataset:
        """Reconstruct from serialized dict."""
        x_axis = None
        if d.get("x_axis"):
            ax = d["x_axis"]
            x_axis = AxisInfo(
                values=np.asarray(ax["data"]) if ax.get("data") is not None else None,
                labels=ax.get("labels"),
                units=ax.get("units"),
                title=ax.get("title"),
            )
        y_axis = None
        if d.get("y_axis"):
            ax = d["y_axis"]
            y_axis = AxisInfo(
                values=np.asarray(ax["data"]) if ax.get("data") is not None else None,
                labels=ax.get("labels"),
                units=ax.get("units"),
                title=ax.get("title"),
            )
        metadata = d.get("metadata", {})
        provenance = metadata.pop("processing_history", [])
        target = None
        if d.get("target") is not None:
            target = np.asarray(d["target"])
        return cls(
            X=np.asarray(d["data"]),
            x_axis=x_axis,
            y_axis=y_axis,
            target=target,
            meta=metadata,
            provenance=provenance,
            backend=d.get("backend", "numpy"),
            title=d.get("title"),
            units=d.get("units"),
        )

    def __repr__(self) -> str:
        return (
            f"AnalysisDataset(shape={self.shape}, backend={self.backend!r}, "
            f"title={self.title!r})"
        )


# ---------------------------------------------------------------------------
# Adapter: from_sklearn_bunch
# ---------------------------------------------------------------------------

def from_sklearn_bunch(bunch: Any, name: str = "") -> AnalysisDataset:
    """Convert an sklearn Bunch to AnalysisDataset.

    Args:
        bunch: sklearn.utils.Bunch (e.g. from ``load_iris()``)
        name: Optional dataset name for metadata

    Returns:
        AnalysisDataset with X, feature-axis labels, target, and metadata.
    """
    feature_names = list(getattr(bunch, "feature_names", []))
    target_names = list(getattr(bunch, "target_names", []))
    return AnalysisDataset(
        X=bunch.data,
        x_axis=AxisInfo(
            values=np.arange(bunch.data.shape[1]),
            labels=feature_names or None,
            title="features",
        ),
        y_axis=AxisInfo(
            values=np.arange(bunch.data.shape[0]),
            title="samples",
        ),
        target=bunch.target if hasattr(bunch, "target") else None,
        meta={"target_names": target_names, "dataset_name": name},
        backend="sklearn",
    )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _coord_to_axis_info(coord: Any) -> AxisInfo:
    """Convert a Coord-like object to AxisInfo."""
    return AxisInfo(
        values=np.asarray(coord.data) if coord.data is not None else None,
        units=str(coord.units) if hasattr(coord, "units") and coord.units else None,
        title=str(coord.title) if hasattr(coord, "title") and coord.title else None,
        labels=(
            list(coord.labels)
            if hasattr(coord, "labels") and coord.labels is not None
            else None
        ),
    )


def _slice_axis(
    axis: Optional[AxisInfo], key: Any
) -> Optional[AxisInfo]:
    """Slice an AxisInfo along its primary dimension."""
    if axis is None:
        return None
    new_values = axis.values[key] if axis.values is not None else None
    new_labels = None
    if axis.labels is not None:
        if isinstance(key, np.ndarray) and key.dtype == bool:
            new_labels = [l for l, m in zip(axis.labels, key) if m]
        elif isinstance(key, slice):
            new_labels = axis.labels[key]
        elif isinstance(key, (int, np.integer)):
            new_labels = [axis.labels[key]]
    return AxisInfo(
        values=new_values,
        labels=new_labels,
        units=axis.units,
        title=axis.title,
    )
