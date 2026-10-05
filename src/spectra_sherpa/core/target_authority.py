"""Closed target-selection authority shared by UI, admission, and execution.

Descriptive target metadata may advertise several possible response columns.
Once a scientist selects one response, however, its column identity, scientific
type, units, and exact source identity form one inseparable authority.  This
module is deliberately independent of the Workbench and DAG layers so every
consumer validates the same value object.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

TARGET_AUTHORITY_SCHEMA_VERSION = "spectrasherpa-target-authority/1"
TargetAuthorityType = Literal["continuous", "categorical"]


def _bounded_text(value: Any, *, field: str, optional: bool = False) -> str | None:
    if value is None and optional:
        return None
    if not isinstance(value, str) or not value or value != value.strip() or len(value) > 255:
        raise ValueError(f"target authority {field} must be bounded, non-empty, canonical text")
    return value


class TargetAuthority(BaseModel):
    """One exact selected response bound to one immutable dataset source."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal["spectrasherpa-target-authority/1"] = TARGET_AUTHORITY_SCHEMA_VERSION
    column: str = Field(min_length=1, max_length=255)
    target_type: TargetAuthorityType
    units: str | None = Field(default=None, max_length=255)
    source_digest: str = Field(min_length=64, max_length=64)

    @field_validator("column")
    @classmethod
    def _column_is_canonical(cls, value: str) -> str:
        result = _bounded_text(value, field="column")
        assert result is not None
        return result

    @field_validator("units")
    @classmethod
    def _units_are_canonical(cls, value: str | None) -> str | None:
        return _bounded_text(value, field="units", optional=True)

    @field_validator("source_digest")
    @classmethod
    def _source_digest_is_sha256(cls, value: str) -> str:
        if any(ch not in "0123456789abcdef" for ch in value):
            raise ValueError("target authority source_digest must be lowercase SHA-256 hex")
        return value

    def canonical_dict(self) -> dict[str, str | None]:
        """Return the exact wire and persisted-DAG projection."""

        return self.model_dump(mode="json")


def admit_target_authority(value: object, *, optional: bool = True) -> TargetAuthority | None:
    """Validate a wire/persisted authority without accepting loose aliases."""

    if value is None and optional:
        return None
    if isinstance(value, TargetAuthority):
        return value
    if not isinstance(value, Mapping):
        raise ValueError("target_authority must be one closed object")
    return TargetAuthority.model_validate(dict(value))


__all__ = [
    "TARGET_AUTHORITY_SCHEMA_VERSION",
    "TargetAuthority",
    "TargetAuthorityType",
    "admit_target_authority",
]
