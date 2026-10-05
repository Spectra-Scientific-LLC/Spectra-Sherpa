"""Immutable public values returned by the native ingestion boundary."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import IntEnum
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, Mapping

from spectra_sherpa.core.dimension_roles import DimensionRole, canonical_dimension_roles

if TYPE_CHECKING:
    from spectra_sherpa.app.lib.sherpa_dataset import SherpaDataset


def _closed_mapping(value: Mapping[str, Any] | None) -> Mapping[str, Any]:
    return MappingProxyType(dict(value or {}))


class ProbeConfidence(IntEnum):
    """Categorical structural confidence; never an arbitrary score."""

    NO_MATCH = 0
    COMPATIBLE = 1
    EXACT = 2


@dataclass(frozen=True, slots=True)
class ProbeResult:
    """One parser's bounded structural claim about a source."""

    format_id: str
    variant: str | None
    confidence: ProbeConfidence
    evidence: tuple[str, ...] = ()
    bytes_inspected: int = 0

    def __post_init__(self) -> None:
        if not self.format_id or self.format_id.strip() != self.format_id:
            raise ValueError("ProbeResult.format_id must be a non-empty canonical identifier")
        if self.bytes_inspected < 0:
            raise ValueError("ProbeResult.bytes_inspected cannot be negative")
        if self.confidence is ProbeConfidence.NO_MATCH and self.variant is not None:
            raise ValueError("A no-match probe cannot declare a variant")


@dataclass(frozen=True, slots=True)
class ParserLimits:
    """Visible resource bounds applied before parser-controlled allocation."""

    max_source_bytes: int = 200 * 1024 * 1024
    max_decoded_elements: int = 64_000_000
    max_decoded_bytes: int = 512 * 1024 * 1024
    max_blocks: int = 65_536
    max_metadata_bytes: int = 8 * 1024 * 1024
    max_probe_bytes: int = 64 * 1024

    def __post_init__(self) -> None:
        for name in (
            "max_source_bytes",
            "max_decoded_elements",
            "max_decoded_bytes",
            "max_blocks",
            "max_metadata_bytes",
            "max_probe_bytes",
        ):
            if getattr(self, name) <= 0:
                raise ValueError(f"ParserLimits.{name} must be positive")
        if self.max_probe_bytes > self.max_source_bytes:
            raise ValueError("ParserLimits.max_probe_bytes cannot exceed max_source_bytes")


@dataclass(frozen=True, slots=True)
class SourceMember:
    """Digest-bound member consumed by one ingestion result."""

    name: str
    sha256: str
    size_bytes: int

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("SourceMember.name must be non-empty")
        if len(self.sha256) != 64 or any(ch not in "0123456789abcdef" for ch in self.sha256):
            raise ValueError("SourceMember.sha256 must be lowercase SHA-256 hex")
        if self.size_bytes < 0:
            raise ValueError("SourceMember.size_bytes cannot be negative")


@dataclass(frozen=True, slots=True)
class SpectralAsset:
    """A scientist-selectable asset; parsers never silently flatten collections."""

    asset_id: str
    dataset: SherpaDataset
    dimension_roles: tuple[DimensionRole, ...]
    raw_metadata: Mapping[str, Any] = field(default_factory=dict)
    warnings: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.asset_id:
            raise ValueError("SpectralAsset.asset_id must be non-empty")
        if len(self.dimension_roles) != len(self.dataset.shape):
            raise ValueError("SpectralAsset.dimension_roles must describe every dataset dimension")
        object.__setattr__(self, "dimension_roles", canonical_dimension_roles(self.dimension_roles))
        object.__setattr__(self, "raw_metadata", _closed_mapping(self.raw_metadata))


@dataclass(frozen=True, slots=True)
class IngestionResult:
    """Complete, typed output of one registered parser."""

    format_id: str
    variant: str
    parser_id: str
    parser_version: str
    source_members: tuple[SourceMember, ...]
    assets: tuple[SpectralAsset, ...]
    raw_metadata: Mapping[str, Any] = field(default_factory=dict)
    warnings: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not all((self.format_id, self.variant, self.parser_id, self.parser_version)):
            raise ValueError("Ingestion identity fields must be non-empty")
        if not self.source_members:
            raise ValueError("IngestionResult requires at least one source member")
        if not self.assets:
            raise ValueError("IngestionResult requires at least one spectral asset")
        asset_ids = [asset.asset_id for asset in self.assets]
        if len(asset_ids) != len(set(asset_ids)):
            raise ValueError("IngestionResult asset IDs must be unique")
        object.__setattr__(self, "raw_metadata", _closed_mapping(self.raw_metadata))
