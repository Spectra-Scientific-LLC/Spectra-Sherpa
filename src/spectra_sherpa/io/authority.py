"""Canonical native-reader authority projections.

The full ingestion authority retained on a :class:`SherpaDataset` includes
source member names for human inspection.  Executable exports need a narrower
relocatable form: parser identity and every scientific warning stay exact,
while an independently obtained source may be renamed without changing its
authority.  Member size and SHA-256, in parser order, remain binding.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

if TYPE_CHECKING:
    from spectra_sherpa.app.lib.sherpa_dataset import SherpaDataset

INGESTION_AUTHORITY_SCHEMA = "spectrasherpa.ingestion-authority/1"
PORTABLE_INGESTION_AUTHORITY_SCHEMA = "spectrasherpa.portable-ingestion-authority/1"


class PortableSourceMember(BaseModel):
    """One relocatable member identity in parser-returned order."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    size_bytes: int = Field(ge=0)
    sha256: str = Field(min_length=64, max_length=64)

    @field_validator("sha256")
    @classmethod
    def _sha256_is_canonical(cls, value: str) -> str:
        if any(character not in "0123456789abcdef" for character in value):
            raise ValueError("portable ingestion authority SHA-256 must be lowercase hexadecimal")
        return value


class PortableIngestionAuthority(BaseModel):
    """Path-free parser authority persisted by executable exports."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal["spectrasherpa.portable-ingestion-authority/1"] = PORTABLE_INGESTION_AUTHORITY_SCHEMA
    format_id: str = Field(min_length=1, max_length=255)
    variant: str | None = Field(default=None, max_length=255)
    parser_id: str = Field(min_length=1, max_length=255)
    parser_version: str = Field(min_length=1, max_length=255)
    asset_id: str = Field(min_length=1, max_length=1024)
    source_members: tuple[PortableSourceMember, ...] = Field(min_length=1)
    warnings: tuple[str, ...] = ()
    invariants: tuple[str, ...] = Field(min_length=1)

    def canonical_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json")


def project_portable_ingestion_authority(dataset: SherpaDataset) -> PortableIngestionAuthority:
    """Project a dataset's complete registry authority without path/name custody."""

    raw = dataset.get_extra("ingestion.authority")
    if not isinstance(raw, Mapping) or raw.get("schema") != INGESTION_AUTHORITY_SCHEMA:
        raise ValueError("dataset is missing its canonical native ingestion authority")
    source_members = raw.get("source_members")
    if (
        not isinstance(source_members, list)
        or not source_members
        or any(not isinstance(member, Mapping) for member in source_members)
    ):
        raise ValueError("dataset native ingestion authority has no source members")
    return PortableIngestionAuthority.model_validate(
        {
            "schema_version": PORTABLE_INGESTION_AUTHORITY_SCHEMA,
            "format_id": raw.get("format_id"),
            "variant": raw.get("variant"),
            "parser_id": raw.get("parser_id"),
            "parser_version": raw.get("parser_version"),
            "asset_id": raw.get("asset_id"),
            "source_members": [
                {
                    "size_bytes": member.get("size_bytes"),
                    "sha256": member.get("sha256"),
                }
                for member in source_members
            ],
            "warnings": raw.get("warnings"),
            "invariants": raw.get("invariants"),
        }
    )


def admit_portable_ingestion_authority(value: object) -> PortableIngestionAuthority:
    """Admit only the closed portable authority object."""

    if isinstance(value, PortableIngestionAuthority):
        return value
    if not isinstance(value, Mapping):
        raise ValueError("expected_ingestion_authority must be one closed object")
    return PortableIngestionAuthority.model_validate(dict(value))


def verify_portable_ingestion_authority(dataset: SherpaDataset, expected: object) -> None:
    """Fail closed when current parsing differs from the exported authority."""

    admitted = admit_portable_ingestion_authority(expected)
    observed = project_portable_ingestion_authority(dataset)
    if observed != admitted:
        raise ValueError(
            "workflow source native ingestion authority changed; use the Sherpa version that created the export "
            "or review and export the source again"
        )


__all__ = [
    "INGESTION_AUTHORITY_SCHEMA",
    "PORTABLE_INGESTION_AUTHORITY_SCHEMA",
    "PortableIngestionAuthority",
    "PortableSourceMember",
    "admit_portable_ingestion_authority",
    "project_portable_ingestion_authority",
    "verify_portable_ingestion_authority",
]
