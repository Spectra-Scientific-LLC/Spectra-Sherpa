"""
SpectroChemPy (NDDataset) adapter for SherpaDataset.

Converts NDDataset ↔ SherpaDataset at system boundaries.
Imports from scp_compat — no direct ``import spectrochempy`` here.
"""

from __future__ import annotations

from typing import Any

import numpy as np

from spectra_sherpa.app.lib.sherpa_dataset import (
    DomainContext,
    InferredDomain,
    SampleAxis,
    SherpaDataset,
    SpectralAxis,
)
from spectra_sherpa.app.lib.scp_compat import Coord, require_scp, scp


def from_nddataset(ds: Any) -> SherpaDataset:
    """Lossless conversion from SCP NDDataset to SherpaDataset.

    Safe to call regardless of HAS_SCP — if you have an NDDataset in hand
    SCP must already be installed.
    """
    spectral_axis = _extract_spectral_axis(ds)
    sample_axis = _extract_sample_axis(ds)
    domain = _infer_domain_from_nddataset(ds, spectral_axis)

    # Extract provenance from meta
    meta = dict(ds.meta) if hasattr(ds, "meta") and ds.meta else {}
    provenance_raw = meta.pop("processing_history", [])

    # Build extra from remaining meta
    extra = {}
    for k, v in meta.items():
        extra[f"scp.{k}"] = v

    from spectra_sherpa.app.lib.sherpa_dataset import Provenance

    provenance = Provenance.from_list(provenance_raw) if provenance_raw else Provenance()

    return SherpaDataset(
        X=np.asarray(ds.data),
        spectral_axis=spectral_axis,
        sample_axis=sample_axis,
        domain=domain,
        provenance=provenance,
        backend="scp",
        title=str(ds.title) if hasattr(ds, "title") and ds.title else None,
        units=str(ds.units) if hasattr(ds, "units") and ds.units else None,
        extra=extra if extra else None,
    )


def to_nddataset(sherpa_ds: SherpaDataset) -> Any:
    """Convert SherpaDataset back to NDDataset.

    Raises:
        ImportError: If SpectroChemPy is not installed.
    """
    require_scp("to_nddataset()")

    ds = scp.NDDataset(sherpa_ds.X)  # type: ignore[union-attr]

    sa = sherpa_ds.spectral_axis
    if sa and sa.values is not None:
        ds.x = Coord(sa.values, title=sa.title or "")
        if sa.units:
            try:
                ds.x.units = sa.units
            except Exception:
                pass
        if sa.labels is not None:
            try:
                ds.x.labels = sa.labels
            except Exception:
                pass

    sam = sherpa_ds.sample_axis
    if sam and sam.values is not None:
        ds.y = Coord(sam.values, title=sam.title or "")
        if sam.units:
            try:
                ds.y.units = sam.units
            except Exception:
                pass
        if sam.labels is not None:
            try:
                ds.y.labels = sam.labels
            except Exception:
                pass

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


# ── Internal Helpers ──────────────────────────────────────────────


def _extract_spectral_axis(ds: Any) -> SpectralAxis | None:
    """Extract x coord as SpectralAxis."""
    try:
        xc = ds.x
        if xc is None:
            return None
        labels = _extract_labels(xc)
        return SpectralAxis(
            values=np.asarray(xc.data) if xc.data is not None else None,
            units=str(xc.units) if hasattr(xc, "units") and xc.units else None,
            title=str(xc.title) if hasattr(xc, "title") and xc.title else None,
            labels=labels,
        )
    except (KeyError, AttributeError):
        return None


def _extract_sample_axis(ds: Any) -> SampleAxis | None:
    """Extract y coord as SampleAxis."""
    try:
        yc = ds.y
        if yc is None:
            return None
        labels = _extract_labels(yc)
        return SampleAxis(
            values=np.asarray(yc.data) if yc.data is not None else None,
            units=str(yc.units) if hasattr(yc, "units") and yc.units else None,
            title=str(yc.title) if hasattr(yc, "title") and yc.title else None,
            labels=labels,
        )
    except (KeyError, AttributeError):
        return None


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
