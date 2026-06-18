"""Dataset construction and lightweight readers for the public SDK."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Sequence

import numpy as np

from spectra_sherpa.app.lib.axes import FeatureAxis, SampleAxis, SpectralAxis
from spectra_sherpa.app.lib.sherpa_dataset import DomainContext, SherpaDataset, TargetContext
from spectra_sherpa.app.services.dag.io_contracts import build_dataset_like, coerce_to_sherpa


def _feature_axis_from_x(
    x: Any,
    *,
    n_features: int,
    units: str | None,
    title: str | None,
) -> FeatureAxis | None:
    if x is None:
        return None
    if isinstance(x, FeatureAxis):
        return x

    if isinstance(x, str):
        return SpectralAxis(labels=[str(i) for i in range(n_features)], units=units, title=x)

    values = np.asarray(x)
    if values.ndim != 1:
        raise ValueError(f"x must be a 1D feature axis, got {values.ndim}D")
    if values.shape[0] != n_features:
        raise ValueError(f"x must have {n_features} values, got {values.shape[0]}")
    if np.issubdtype(values.dtype, np.number):
        return SpectralAxis(values=values.astype(np.float64), units=units, title=title)
    return SpectralAxis(labels=[str(v) for v in values.tolist()], units=units, title=title)


def _sample_axis_from_samples(samples: Any, *, n_samples: int) -> SampleAxis | None:
    if samples is None:
        return None
    if isinstance(samples, SampleAxis):
        return samples

    values = np.asarray(samples)
    if values.ndim != 1:
        raise ValueError(f"samples must be a 1D sample axis, got {values.ndim}D")
    if values.shape[0] != n_samples:
        raise ValueError(f"samples must have {n_samples} entries, got {values.shape[0]}")
    if np.issubdtype(values.dtype, np.number):
        return SampleAxis(values=values.astype(np.float64), title="Sample")
    return SampleAxis(labels=[str(v) for v in values.tolist()], title="Sample")


def _target_context_for(
    y: Any,
    *,
    y_name: str | Sequence[str] | None,
    target_type: str | None,
    target_units: str | None,
) -> TargetContext | None:
    if y is None and y_name is None and target_type is None and target_units is None:
        return None
    if y_name is None:
        target_name = None
        target_names = None
    elif isinstance(y_name, str):
        target_name = y_name
        target_names = [y_name]
    else:
        target_names = [str(name) for name in y_name]
        target_name = target_names[0] if len(target_names) == 1 else None

    return TargetContext(
        target_type=target_type,
        target_name=target_name,
        target_names=target_names,
        target_units=target_units,
    )


def from_array(
    X: Any,
    *,
    x: Any = None,
    samples: Any = None,
    y: Any = None,
    y_name: str | Sequence[str] | None = None,
    target_type: str | None = None,
    target_units: str | None = None,
    technique: str | None = None,
    units: str | None = None,
    title: str | None = None,
    data_units: str | None = None,
    feature_axis: FeatureAxis | None = None,
    sample_axis: SampleAxis | None = None,
    extra: dict[str, Any] | None = None,
    data_role: str | None = None,
) -> SherpaDataset:
    """Create a :class:`SherpaDataset` from array-like data.

    ``X`` is interpreted as ``n_samples x n_features``. The ``x`` argument can
    be a feature-axis object, a 1D coordinate vector, a 1D label vector, or a
    string used as the feature-axis title. ``samples`` can be a sample-axis
    object, numeric sample coordinates, or sample labels.
    """
    arr = np.asarray(X, dtype=np.float64)
    if arr.ndim == 0:
        raise ValueError("X must be at least 1-dimensional, got scalar")
    if arr.ndim == 1:
        arr = arr.reshape(1, -1)

    resolved_feature_axis = feature_axis or _feature_axis_from_x(
        x,
        n_features=arr.shape[-1],
        units=units,
        title=None,
    )
    resolved_sample_axis = sample_axis or _sample_axis_from_samples(samples, n_samples=arr.shape[0])
    target_context = _target_context_for(
        y,
        y_name=y_name,
        target_type=target_type,
        target_units=target_units,
    )

    return SherpaDataset(
        X=arr,
        feature_axis=resolved_feature_axis,
        sample_axis=resolved_sample_axis,
        target=y,
        target_context=target_context,
        domain=DomainContext(technique=technique),
        backend="numpy",
        title=title,
        units=data_units,
        extra=extra,
        data_role=data_role,
    )


def like(source: Any, data: Any, *, units: str | None = None, title: str | None = None) -> SherpaDataset:
    """Create a dataset like ``source`` with replaced numeric data."""
    return build_dataset_like(data, source, units=units, title=title)


def to_numpy(dataset: Any, *, copy: bool = True) -> np.ndarray:
    """Return a numpy array from a dataset or array-like object."""
    ds = coerce_to_sherpa(dataset, input_name="dataset", allow_array=True)
    arr = np.asarray(ds.data)
    return arr.copy() if copy else arr


def read_csv(
    path: str | Path,
    *,
    x: str | None = None,
    y: str | None = None,
    target_type: str | None = None,
    data_role: str | None = None,
) -> SherpaDataset:
    """Read a CSV through the same loader used by GUI data-source nodes.

    ``x`` is accepted as a caller-facing axis hint for the two-tier SDK API.
    Current behavior delegates axis inference to the central CSV loader so SDK
    and GUI imports stay aligned.
    """
    from spectra_sherpa.app.lib.io import load_csv_as_sherpa

    ds = load_csv_as_sherpa(path, data_role=data_role, target_column=y, target_type=target_type)
    if y and ds.target is None:
        props = ds.get_extra("properties")
        if isinstance(props, dict) and y in props:
            target = np.asarray(props[y])
            # SherpaDataset target metadata is mutable by design; mirror GUI loader post-processing here.
            ds.target = target
            ds.target_context = TargetContext(
                target_type=target_type or ("categorical" if target.dtype.kind in ("O", "S", "U") else "continuous"),
                target_name=y,
                target_names=[y],
            )
            ds.meta["csv.target_column"] = y
            ds.meta["csv.target_type"] = ds.target_context.target_type
    if x and ds.feature_axis is not None and not ds.feature_axis.title:
        axis = ds.feature_axis
        axis.title = x
        ds.feature_axis = axis
    return ds


def read_spc(path: str | Path) -> SherpaDataset:
    """SPC reader placeholder for the public SDK."""
    raise NotImplementedError("ss.data.read_spc is not implemented yet; use the GUI/data-source loader for SPC files.")


def read_opus(path: str | Path) -> SherpaDataset:
    """OPUS reader placeholder for the public SDK."""
    raise NotImplementedError(
        "ss.data.read_opus is not implemented yet; use the GUI/data-source loader for OPUS files."
    )


__all__ = [
    "from_array",
    "like",
    "to_numpy",
    "read_csv",
    "read_spc",
    "read_opus",
]
