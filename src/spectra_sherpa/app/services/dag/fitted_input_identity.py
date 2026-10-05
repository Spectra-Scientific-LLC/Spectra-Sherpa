"""Closed input authority retained by fitted scientific operations.

Spelling normalization is not a unit conversion. Missing authority stays
explicit and must match: newly supplied metadata cannot qualify an anonymous
fit, and absent metadata cannot silently satisfy an identified fit.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .feature_axis_identity import feature_axis_identity, validated_axis_quantity

_SCHEMA = "spectrasherpa.fitted-input-identity/1"
_FIELDS = frozenset({"schema_version", "features", "axis", "signal_units", "signal_quantity", "measurement_mode"})
_UNIT_SPELLINGS = {
    "abs": "absorbance",
    "absorbance": "absorbance",
    "%t": "%T",
    "percent transmittance": "%T",
    "transmittance": "transmittance",
    "dimensionless": "dimensionless",
    "counts": "counts",
    "count": "counts",
}


def _text(value: object, *, name: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        raise ValueError(f"fitted input {name} must be non-empty canonical text or unavailable")
    return value


def canonical_signal_units(value: object) -> str | None:
    units = _text(value, name="signal units")
    return _UNIT_SPELLINGS.get(units.casefold(), units) if units else None


def fitted_input_identity(dataset: Any, *, features: int) -> dict[str, object]:
    axis = feature_axis_identity(dataset, features=features, context="fitted input")
    units = canonical_signal_units(getattr(dataset, "units", None))
    domain = getattr(dataset, "domain", None)
    quantity = _text(getattr(domain, "data_quantity", None), name="signal quantity")
    mode = _text(getattr(domain, "measurement_mode", None), name="measurement mode")
    return validate_fitted_input_identity(
        {
            "schema_version": _SCHEMA,
            "features": features,
            "axis": list(axis),
            "signal_units": units,
            "signal_quantity": quantity.casefold() if quantity else None,
            "measurement_mode": mode.casefold() if mode else None,
        }
    )


def validate_fitted_input_identity(value: object) -> dict[str, object]:
    if not isinstance(value, Mapping) or set(value) != _FIELDS or value["schema_version"] != _SCHEMA:
        raise ValueError("fitted input identity uses an unsupported schema; rebuild the fitted state")
    features = value["features"]
    if isinstance(features, bool) or not isinstance(features, int) or features < 1:
        raise ValueError("fitted input identity requires a positive feature count")
    axis = value["axis"]
    if not isinstance(axis, (list, tuple)) or len(axis) != 4:
        raise ValueError("fitted input identity has invalid axis authority")
    for digest in axis[:2]:
        if digest is not None and (
            not isinstance(digest, str) or len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest)
        ):
            raise ValueError("fitted input identity has invalid axis digest")
    _text(axis[2], name="axis units")
    validated_axis_quantity(axis[3], context="fitted input")
    for name in ("signal_units", "signal_quantity", "measurement_mode"):
        _text(value[name], name=name)
    return {**dict(value), "axis": list(axis)}


def require_fitted_input_identity(dataset: Any, value: object, *, features: int) -> None:
    expected = validate_fitted_input_identity(value)
    actual = fitted_input_identity(dataset, features=features)
    different = [
        key
        for key in ("features", "axis", "signal_units", "signal_quantity", "measurement_mode")
        if actual[key] != expected[key]
    ]
    if different:
        raise ValueError(
            "application input differs from fitted input authority: "
            + ", ".join(different)
            + "; use an explicit conversion or refit with the correct metadata"
        )
