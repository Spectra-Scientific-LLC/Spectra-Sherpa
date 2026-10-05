"""Compatibility import for the canonical multi-well format contract."""

from spectra_sherpa.core.plate_formats import (
    DEFAULT_PLATE_FORMAT_ID,
    PLATE_FORMAT_REGISTRY_SCHEMA,
    PLATE_FORMATS,
    PlateFormat,
    get_plate_format,
    infer_legacy_plate_format,
)

__all__ = [
    "DEFAULT_PLATE_FORMAT_ID",
    "PLATE_FORMAT_REGISTRY_SCHEMA",
    "PLATE_FORMATS",
    "PlateFormat",
    "get_plate_format",
    "infer_legacy_plate_format",
]
