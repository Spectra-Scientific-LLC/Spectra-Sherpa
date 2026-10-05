"""Closed scientific vocabulary for array-dimension meaning.

Dimension roles are scientific identities, not display labels. Readers may
encounter historical or vendor spellings, but durable dataset and type
contracts carry only the canonical values declared here.
"""

from __future__ import annotations

import re
from enum import StrEnum
from typing import Iterable


class DimensionRole(StrEnum):
    """Canonical meaning of one numeric-array dimension."""

    SAMPLE = "sample"
    FEATURE = "feature"
    SPECTRAL_FEATURE = "spectral_feature"
    SPECTRAL_VARIABLE = "spectral_variable"
    INNER = "inner"
    SPATIAL_COORDINATE = "spatial_coordinate"
    SPATIAL_X = "spatial_x"
    SPATIAL_Y = "spatial_y"
    SPATIAL_Z = "spatial_z"
    TIME_POINT = "time_point"
    EXCITATION = "excitation"
    EMISSION = "emission"
    MASS_TO_CHARGE = "mass_to_charge"
    POTENTIAL = "potential"
    COMPONENT = "component"
    TARGET = "target"
    ENTRY = "entry"
    ROW = "row"
    COLUMN = "column"
    OBSERVATION = "observation"
    COMPARISON_FIELD = "comparison_field"
    VARIANCE_DOMAIN = "variance_domain"
    DETECTED_PEAK = "detected_peak"
    SELECTED_VARIABLE = "selected_variable"
    ACTUAL_CLASS = "actual_class"
    PREDICTED_CLASS = "predicted_class"


_ALIASES: dict[str, DimensionRole] = {
    "samples": DimensionRole.SAMPLE,
    "features": DimensionRole.FEATURE,
    "spatial-1": DimensionRole.SPATIAL_COORDINATE,
    "spatial-2": DimensionRole.SPATIAL_COORDINATE,
    "spatial-3": DimensionRole.SPATIAL_COORDINATE,
    "spatial-x": DimensionRole.SPATIAL_X,
    "spatial-y": DimensionRole.SPATIAL_Y,
    "spatial-z": DimensionRole.SPATIAL_Z,
    "image-column": DimensionRole.SPATIAL_X,
    "image-row": DimensionRole.SPATIAL_Y,
}
_GENERIC_MODE_RE = re.compile(r"^(?:mode|inner)-(?:0|[1-9][0-9]*)$")


def canonical_dimension_role(value: object) -> DimensionRole:
    """Return one canonical role, refusing open-ended or malformed values."""

    if isinstance(value, DimensionRole):
        return value
    if not isinstance(value, str) or not value or value != value.strip():
        raise ValueError("dimension role must be a non-empty canonical string")
    alias = _ALIASES.get(value)
    if alias is not None:
        return alias
    if _GENERIC_MODE_RE.fullmatch(value):
        return DimensionRole.INNER
    try:
        return DimensionRole(value)
    except ValueError as exc:
        raise ValueError(f"unsupported dimension role: {value!r}") from exc


def canonical_dimension_roles(values: Iterable[object], *, max_roles: int = 16) -> tuple[DimensionRole, ...]:
    """Canonicalize one bounded role sequence."""

    roles = tuple(canonical_dimension_role(value) for value in values)
    if len(roles) > max_roles:
        raise ValueError("dimension-role sequence exceeds the rank limit")
    return roles


__all__ = ["DimensionRole", "canonical_dimension_role", "canonical_dimension_roles"]
