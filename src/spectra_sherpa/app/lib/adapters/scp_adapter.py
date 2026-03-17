"""
SpectroChemPy (NDDataset) adapter for SherpaDataset.

Converts NDDataset ↔ SherpaDataset at system boundaries.
Imports from scp_compat — no direct ``import spectrochempy`` here.
"""

from __future__ import annotations

import copy
import logging
from collections.abc import Callable
from typing import Any

import numpy as np

from spectra_sherpa.app.lib.scp_compat import Coord, require_scp, scp
from spectra_sherpa.app.lib.sherpa_dataset import (
    AxisInfo,
    DomainContext,
    InferredDomain,
    MZAxis,
    Provenance,
    SampleAxis,
    SherpaDataset,
    SpatialAxis,
    SpectralAxis,
    TimeAxis,
)

logger = logging.getLogger(__name__)


def _to_plain_dict(obj: Any) -> Any:
    """Recursively convert any dict-like objects (including ReadOnlyDict) to plain dicts.

    SpectroChemPy wraps metadata in ReadOnlyDict instances whose ``_readonly``
    attribute is not preserved during pickling, causing unpickle failures in
    process pools.  This helper ensures all nested dict-likes become plain dicts.
    """
    if isinstance(obj, dict):
        return {k: _to_plain_dict(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        converted = [_to_plain_dict(item) for item in obj]
        return type(obj)(converted)
    return obj


def _extract_title(ds: Any) -> str | None:
    """Get a meaningful title from NDDataset, falling back to .name.

    NDDataset has separate ``.title`` and ``.name`` attributes.
    Programmatically constructed datasets (e.g. Eigenvector loader) often
    set ``.name`` while ``.title`` stays ``'<untitled>'``.
    """
    if hasattr(ds, "title") and ds.title and str(ds.title) != "<untitled>":
        return str(ds.title)
    if hasattr(ds, "name") and ds.name:
        return str(ds.name)
    return None


def from_nddataset(ds: Any) -> SherpaDataset:
    """Lossless conversion from SCP NDDataset to SherpaDataset.

    Supports nD NDDatasets: extracts inner-dimension coordinates from the
    coordset when ndim > 2.

    Safe to call regardless of HAS_SCP — if you have an NDDataset in hand
    SCP must already be installed.
    """
    data = np.asarray(ds.data)
    ndim = data.ndim
    dim_names = _get_dim_names(ds)

    spectral_axis = _extract_spectral_axis(ds, ndim=ndim, dim_names=dim_names)
    sample_axis = _extract_sample_axis(ds, dim_names=dim_names)
    domain = _infer_domain_from_nddataset(ds, spectral_axis)

    # Extract inner-dimension axes for 3D+ data
    inner_axes = _extract_inner_axes(ds, ndim, dim_names=dim_names) if ndim > 2 else None

    # Extract provenance from meta
    meta = _to_plain_dict(dict(ds.meta)) if hasattr(ds, "meta") and ds.meta else {}
    provenance_raw = meta.pop("processing_history", [])

    # Build extra from remaining meta
    extra = {}
    for k, v in meta.items():
        extra[f"scp.{k}"] = v

    provenance = Provenance.from_list(provenance_raw) if provenance_raw else Provenance()

    return SherpaDataset(
        X=data,
        feature_axis=spectral_axis,
        sample_axis=sample_axis,
        axes=inner_axes if inner_axes else None,
        domain=domain,
        provenance=provenance,
        backend="scp",
        title=_extract_title(ds),
        units=str(ds.units) if hasattr(ds, "units") and ds.units else None,
        extra=extra if extra else None,
    )


def to_nddataset(sherpa_ds: SherpaDataset) -> Any:
    """Convert SherpaDataset back to NDDataset.

    Supports nD SherpaDatasets: sets inner-dimension coordinates on the
    NDDataset coordset when ndim > 2.

    Raises:
        ImportError: If SpectroChemPy is not installed.
    """
    require_scp("to_nddataset()")

    ds = scp.NDDataset(sherpa_ds.X)  # type: ignore[union-attr]

    ndim = sherpa_ds.ndim
    dim_names = _get_dim_names(ds)

    # Feature axis -> coord on last data dimension.
    fa = sherpa_ds.get_feature_axis()
    if fa and fa.values is not None:
        feature_coord = _axis_to_coord(fa)
        _set_coord_for_dim(ds, dim=ndim - 1, coord=feature_coord, dim_names=dim_names)

    # Sample axis -> coord on first data dimension.
    sam = sherpa_ds.sample_axis
    if sam and sam.values is not None:
        sample_coord = _axis_to_coord(sam)
        _set_coord_for_dim(ds, dim=0, coord=sample_coord, dim_names=dim_names)

    # Inner axes -> coords on dimensions 1..ndim-2 for nD data.
    inner_axes = sherpa_ds.inner_axes
    for dim, ax in sorted(inner_axes.items()):
        if dim < 1 or dim >= ndim - 1:
            logger.debug("Skipping inner axis for invalid dim=%d with ndim=%d", dim, ndim)
            continue
        if ax.values is not None:
            coord = _axis_to_coord(ax)
            _set_coord_for_dim(ds, dim=dim, coord=coord, dim_names=dim_names)

    # Pack provenance + extra into meta
    ds.meta = {}
    ds.meta["processing_history"] = sherpa_ds.provenance.to_list()
    for k, v in sherpa_ds.extra.items():
        if k.startswith("scp."):
            ds.meta[k[4:]] = v  # strip "scp." prefix

    if sherpa_ds.title:
        ds.title = sherpa_ds.title
    if sherpa_ds.units:
        try:
            ds.units = sherpa_ds.units
        except Exception:
            ds.meta["value_units_label"] = sherpa_ds.units

    return ds


# ── Envelope: round-trip with metadata preservation ───────────────


def scp_roundtrip(
    ds: SherpaDataset,
    fn: Callable[[Any], Any],
    *,
    op_id: str,
    parameters: dict[str, Any] | None = None,
    state_effects: list[str] | None = None,
    node_id: str | None = None,
) -> SherpaDataset:
    """Execute an SCP operation while preserving all SherpaDataset context.

    Handles the full round-trip: SherpaDataset → NDDataset → SCP op → SherpaDataset,
    automatically restoring fields that NDDataset cannot carry (target, quality,
    sample_axis extras, provenance, domain, extra metadata, dataset_id).

    Safe because all SCP preprocessing operations are row-preserving — they never
    reorder, filter, or change the number of samples.

    Args:
        ds: Input SherpaDataset.
        fn: Callable that receives an NDDataset and either mutates it in-place
            (returning None) or returns a new NDDataset.
        op_id: Provenance operation identifier (e.g., "baseline.rubberband").
        parameters: Operation parameters to record in provenance.
        state_effects: Effect tags (e.g., ["baseline_corrected"]).
        node_id: DAG node ID for provenance tracing.

    Returns:
        New SherpaDataset with SCP-transformed data and all metadata preserved.

    Example::

        result = scp_roundtrip(
            input_ds,
            lambda ndd: ndd.basc(method="rubberband"),
            op_id="baseline.rubberband",
            parameters={"method": "rubberband"},
            state_effects=["baseline_corrected"],
            node_id=self.node_id,
        )
    """
    require_scp("scp_roundtrip()")

    # ── 1. Snapshot fields NDDataset cannot carry ──────────────────
    input_shape = tuple(ds.shape)
    provenance = ds.provenance.copy()
    target = ds.target.copy() if ds.target is not None else None
    target_context = ds.target_context.model_copy(deep=True)
    quality = ds.quality.model_copy(deep=True)
    domain = ds.domain.model_copy(deep=True)
    extra = _to_plain_dict(copy.deepcopy(ds.extra))
    sample_axis_snapshot = ds.sample_axis  # .copy() already happens in the property getter
    inner_axes_snapshot = ds.inner_axes  # .copy() already happens in the property getter
    backend = ds.backend
    title_snapshot = ds.title
    units_snapshot = ds.units
    is_time_series_snapshot = ds.is_time_series

    # ── 2. Convert → call SCP → convert back ──────────────────────
    ndd = to_nddataset(ds)
    result_ndd = fn(ndd)

    # SCP methods may return a new NDDataset or None (in-place mutation).
    # SCP 0.8.1: basc() returns a new NDDataset; older versions returned None.
    if result_ndd is None:
        result_ndd = ndd

    result = from_nddataset(result_ndd)

    # ── 3. Restore everything from snapshot ────────────────────────
    result.provenance = provenance
    if target is not None:
        result.target = target
    result.target_context = target_context
    result.quality = quality
    result.domain = domain
    result._extra.update(extra)
    if backend != "scp":
        result.backend = backend
    if title_snapshot is not None:
        result.title = title_snapshot
    if units_snapshot is not None:
        result.units = units_snapshot
    result.is_time_series = is_time_series_snapshot

    # Restore inner axes that NDDataset may not carry fully
    for dim, ax in inner_axes_snapshot.items():
        result._axes[dim] = ax

    # Restore sample_axis extras that NDDataset cannot carry
    if sample_axis_snapshot is not None:
        current_sample = result.sample_axis
        if current_sample is not None:
            # Merge extras from snapshot into the axis that from_nddataset produced
            if sample_axis_snapshot.classes is not None:
                current_sample.classes = sample_axis_snapshot.classes.copy()
            if sample_axis_snapshot.include_mask is not None:
                current_sample.include_mask = sample_axis_snapshot.include_mask.copy()
            if sample_axis_snapshot.exclusion_reasons is not None:
                current_sample.exclusion_reasons = list(sample_axis_snapshot.exclusion_reasons)
            if sample_axis_snapshot.sample_table is not None:
                current_sample.sample_table = copy.deepcopy(sample_axis_snapshot.sample_table)
            result.sample_axis = current_sample
        else:
            # from_nddataset didn't produce a sample_axis — restore the whole thing
            result.sample_axis = sample_axis_snapshot

    # ── 4. Record the new processing step ──────────────────────────
    result.provenance.append(
        op_id=op_id,
        parameters=parameters or {},
        node_id=node_id,
        input_shape=input_shape,
        output_shape=tuple(result.shape),
        state_effects=state_effects or [],
    )

    return result


# ── Internal Helpers ──────────────────────────────────────────────


def _extract_spectral_axis(ds: Any, *, ndim: int, dim_names: list[str] | None) -> SpectralAxis | None:
    """Extract feature-axis coord (last dimension) as SpectralAxis."""
    coord = _get_coord_for_dim(ds, dim=ndim - 1, dim_names=dim_names)
    if coord is None:
        return None
    labels = _extract_labels(coord)
    return SpectralAxis(
        values=np.asarray(coord.data) if coord.data is not None else None,
        units=str(coord.units) if hasattr(coord, "units") and coord.units else None,
        title=str(coord.title) if hasattr(coord, "title") and coord.title else None,
        labels=labels,
    )


def _extract_sample_axis(ds: Any, *, dim_names: list[str] | None) -> SampleAxis | None:
    """Extract sample-axis coord (first dimension) as SampleAxis."""
    coord = _get_coord_for_dim(ds, dim=0, dim_names=dim_names)
    if coord is None:
        return None
    labels = _extract_labels(coord)
    return SampleAxis(
        values=np.asarray(coord.data) if coord.data is not None else None,
        units=str(coord.units) if hasattr(coord, "units") and coord.units else None,
        title=str(coord.title) if hasattr(coord, "title") and coord.title else None,
        labels=labels,
    )


def _extract_labels(coord: Any) -> list[str] | None:
    """Safely extract labels from a Coord-like object."""
    raw_labels = getattr(coord, "labels", None)
    if raw_labels is None:
        return None
    try:
        if hasattr(raw_labels, "tolist"):
            flat = raw_labels.tolist()
        else:
            flat = list(raw_labels)
        if isinstance(flat, list):
            return [str(v) for v in flat]
        return [str(flat)]
    except Exception:
        return None


def _infer_domain_from_nddataset(ds: Any, spectral_axis: SpectralAxis | None) -> DomainContext:
    """Infer domain context from NDDataset attributes and spectral axis."""
    domain = DomainContext()

    if spectral_axis and spectral_axis.range:
        lo, hi = spectral_axis.range
        axis_type = spectral_axis.axis_type

        technique = None
        confidence = 0.0
        reasoning = ""

        if axis_type == "wavenumber":
            if lo >= 350 and hi <= 4500:
                technique = "IR"
                confidence = 0.8
                reasoning = f"Wavenumber range [{lo:.0f}, {hi:.0f}] cm-1 suggests mid-IR"
            elif lo >= 4000 and hi <= 15000:
                technique = "NIR"
                confidence = 0.7
                reasoning = f"Wavenumber range [{lo:.0f}, {hi:.0f}] cm-1 suggests NIR"
            elif lo >= 100 and hi <= 4000:
                technique = "Raman"
                confidence = 0.5
                reasoning = f"Wavenumber range [{lo:.0f}, {hi:.0f}] cm-1 could be Raman"
        elif axis_type == "wavelength_nm":
            if lo >= 700 and hi <= 2500:
                technique = "NIR"
                confidence = 0.7
                reasoning = f"Wavelength range [{lo:.0f}, {hi:.0f}] nm suggests NIR"
            elif lo >= 200 and hi <= 800:
                technique = "UV-Vis"
                confidence = 0.7
                reasoning = f"Wavelength range [{lo:.0f}, {hi:.0f}] nm suggests UV-Vis"

        if technique:
            domain = DomainContext(
                technique=technique if confidence >= 0.7 else None,
                inferred=InferredDomain(
                    technique=technique,
                    confidence=confidence,
                    source="axis_range",
                    reasoning=reasoning,
                ),
            )

    return domain


# Unit sets for axis type inference (matching axes.py conventions)
_TIME_UNITS = frozenset(
    {
        "min",
        "minute",
        "minutes",
        "s",
        "sec",
        "second",
        "seconds",
        "ms",
        "millisecond",
        "milliseconds",
        "h",
        "hour",
        "hours",
    }
)
_MZ_UNITS = frozenset({"m/z", "mz", "da", "dalton", "amu"})
_SPATIAL_UNITS = frozenset(
    {
        "um",
        "µm",
        "\u03bcm",
        "micron",
        "microns",
        "micrometer",
        "mm",
        "millimeter",
        "millimeters",
        "cm",
        "centimeter",
        "px",
        "pixel",
        "pixels",
    }
)


def _extract_inner_axes(ds: Any, ndim: int, *, dim_names: list[str] | None) -> dict[int, AxisInfo]:
    """Extract inner-dimension coordinates for dimensions 1..ndim-2."""
    inner: dict[int, AxisInfo] = {}
    for dim in range(1, ndim - 1):
        coord = _get_coord_for_dim(ds, dim=dim, dim_names=dim_names)
        if coord is None:
            continue
        ax = _coord_to_axis(coord)
        if ax is not None:
            inner[dim] = ax
    return inner


def _get_dim_names(ds: Any) -> list[str] | None:
    """Return SCP dimension names ordered by data axis index (0..ndim-1)."""
    dims = getattr(ds, "dims", None)
    if dims is None:
        return None
    try:
        return [str(name) for name in dims]
    except TypeError:
        return None


def _get_coord_for_dim(ds: Any, *, dim: int, dim_names: list[str] | None) -> Any | None:
    """Get coordinate object for a given data-axis index."""
    if dim_names is not None and 0 <= dim < len(dim_names):
        try:
            coord = getattr(ds, dim_names[dim])
            if coord is not None:
                return coord
        except (AttributeError, KeyError):
            pass

    # Compatibility fallback for older/partial dimension metadata.
    ndim = int(getattr(ds, "ndim", 0) or 0)
    if dim == 0:
        fallback_name = "y"
    elif ndim > 0 and dim == ndim - 1:
        fallback_name = "x"
    else:
        return None
    try:
        return getattr(ds, fallback_name)
    except (AttributeError, KeyError):
        return None


def _axis_to_coord(axis: AxisInfo) -> Any:
    """Convert a Sherpa axis object to SCP Coord."""
    coord = Coord(axis.values, title=axis.title or "")
    if axis.units:
        try:
            coord.units = axis.units
        except Exception:
            pass
    if axis.labels is not None:
        try:
            coord.labels = axis.labels
        except Exception:
            pass
    return coord


def _set_coord_for_dim(ds: Any, *, dim: int, coord: Any, dim_names: list[str] | None) -> None:
    """Set an SCP coord on a specific data-axis index."""
    if dim_names is not None and 0 <= dim < len(dim_names):
        coord_name = dim_names[dim]
        try:
            setattr(ds, coord_name, coord)
            return
        except Exception:
            logger.debug("Could not set SCP coord %s for dim %d", coord_name, dim)

    # Compatibility fallback for older/partial dimension metadata.
    ndim = int(getattr(ds, "ndim", 0) or 0)
    if dim == 0:
        fallback_name = "y"
    elif ndim > 0 and dim == ndim - 1:
        fallback_name = "x"
    else:
        logger.debug("Could not resolve coord name for dim %d", dim)
        return
    try:
        setattr(ds, fallback_name, coord)
    except Exception:
        logger.debug("Could not set fallback SCP coord %s for dim %d", fallback_name, dim)


def _coord_to_axis(coord: Any) -> AxisInfo | None:
    """Convert an SCP Coord to the appropriate Sherpa axis type."""
    values = np.asarray(coord.data) if getattr(coord, "data", None) is not None else None
    units = str(coord.units) if hasattr(coord, "units") and coord.units else None
    title = str(coord.title) if hasattr(coord, "title") and coord.title else None
    labels = _extract_labels(coord)

    # Infer axis type from units
    if units:
        u = units.lower().strip()
        if u in _TIME_UNITS:
            return TimeAxis(values=values, units=units, title=title, labels=labels)
        if u in _MZ_UNITS:
            return MZAxis(values=values, units=units, title=title, labels=labels)
        if u in _SPATIAL_UNITS:
            return SpatialAxis(values=values, units=units, title=title, labels=labels)

    # Default: generic AxisInfo for unknown inner dimensions
    return AxisInfo(values=values, units=units, title=title, labels=labels)
