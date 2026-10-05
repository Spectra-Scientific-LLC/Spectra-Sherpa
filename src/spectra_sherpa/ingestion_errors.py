"""Neutral error authority for bounded native spectral ingestion.

This module intentionally lives outside :mod:`spectra_sherpa.io`. Low-level
scientific parsers may import these types without initializing the registry and
its built-in plugin graph.
"""

from __future__ import annotations


class IngestionError(ValueError):
    """Base class for failures at the native ingestion boundary."""


class UnsupportedFormatError(IngestionError):
    """No registered parser can identify the source."""


class UnsupportedFormatVariantError(UnsupportedFormatError):
    """The source format is valid but its structural variant is not supported."""


class FormatUnavailableError(UnsupportedFormatError):
    """A known source family has no qualified reader in this installation."""


class FormatIdentityError(IngestionError):
    """Filename, structural probe, and parser identities contradict one another."""


class AmbiguousFormatError(IngestionError):
    """More than one parser makes the same strongest structural claim."""


class ParserLimitError(IngestionError):
    """A source or declared output exceeds an inspectable parser limit."""

    def __init__(
        self,
        detail: str,
        *,
        remediation: str = (
            "Use a smaller source, split the data into scientifically coherent parts, "
            "or convert a dense numeric text table to NPY/NPZ."
        ),
    ) -> None:
        self.detail = detail
        self.remediation = remediation
        super().__init__(f"{detail} {remediation}")


class UnreadableSpectrumError(IngestionError):
    """A named format is corrupt, truncated, or scientifically incomplete."""

    def __init__(
        self,
        *,
        format_id: str,
        detail: str,
        offset: int | None = None,
        remediation: str = ("Export the source again, or re-import it if the deployment's stored copy is missing."),
    ) -> None:
        self.format_id = format_id
        self.offset = offset
        self.detail = detail
        self.remediation = remediation
        where = f" at byte offset {offset}" if offset is not None else ""
        super().__init__(f"Unreadable {format_id} spectrum{where}: {detail} {remediation}")
