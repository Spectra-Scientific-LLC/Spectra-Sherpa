"""Public native spectral-ingestion boundary."""

from spectra_sherpa.ingestion_errors import (
    AmbiguousFormatError,
    FormatIdentityError,
    FormatUnavailableError,
    IngestionError,
    ParserLimitError,
    UnreadableSpectrumError,
    UnsupportedFormatError,
    UnsupportedFormatVariantError,
)
from spectra_sherpa.io.invariants import INGESTION_INVARIANTS, IngestionInvariant
from spectra_sherpa.io.registry import builtin_registry, ingest
from spectra_sherpa.io.selection import select_asset
from spectra_sherpa.io.types import (
    IngestionResult,
    ParserLimits,
    ProbeConfidence,
    ProbeResult,
    SourceMember,
    SpectralAsset,
)

__all__ = [
    "AmbiguousFormatError",
    "FormatIdentityError",
    "FormatUnavailableError",
    "IngestionError",
    "IngestionResult",
    "IngestionInvariant",
    "INGESTION_INVARIANTS",
    "ParserLimitError",
    "ParserLimits",
    "ProbeConfidence",
    "ProbeResult",
    "SourceMember",
    "SpectralAsset",
    "UnreadableSpectrumError",
    "UnsupportedFormatError",
    "UnsupportedFormatVariantError",
    "builtin_registry",
    "ingest",
    "select_asset",
]
