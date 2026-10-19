"""Resolve retained response units without borrowing from another response.

Resolvers consume already source-scoped evidence. Missing and conflicting units
remain explicit; neither values nor model coefficients can establish a unit.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Sequence


@dataclass(frozen=True)
class TargetUnits:
    state: Literal["recorded", "missing", "ambiguous"]
    value: str | None = None

    def as_dict(self) -> dict[str, str | None]:
        return {"state": self.state, "value": self.value}


def resolve_target_units(values: Sequence[object]) -> TargetUnits:
    """Resolve agreement among all retained authorities for one response."""
    recorded = {value.strip() for value in values if isinstance(value, str) and value.strip()}
    if len(recorded) > 1:
        return TargetUnits("ambiguous")
    if not values or any(not isinstance(value, str) or not value.strip() for value in values):
        return TargetUnits("missing")
    return TargetUnits("recorded", next(iter(recorded)))


def resolve_response_units(names: object, units: object, response: str | int | None) -> TargetUnits:
    """Select by exact response name or index, with no positional/name guessing."""
    if not isinstance(names, (list, tuple)) or not isinstance(units, (list, tuple)) or len(names) != len(units):
        return TargetUnits("missing")
    if any(not isinstance(name, str) or not name for name in names) or len(set(names)) != len(names):
        return TargetUnits("ambiguous")
    if response is None:
        return resolve_target_units(units)
    if isinstance(response, str):
        if response not in names:
            return TargetUnits("missing")
        index = names.index(response)
    elif type(response) is int and 0 <= response < len(names):
        index = response
    else:
        return TargetUnits("missing")
    return resolve_target_units([units[index]])
