"""Frozen built-in ingestion registry and sole structural dispatcher."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from importlib import import_module
from pathlib import Path
from types import ModuleType
from typing import Any

from spectra_sherpa.app.lib.axes import canonicalize_feature_axis
from spectra_sherpa.ingestion_errors import (
    AmbiguousFormatError,
    FormatIdentityError,
    FormatUnavailableError,
    UnsupportedFormatError,
)
from spectra_sherpa.ingestion_formats import matches_filename, pending_format_for
from spectra_sherpa.io.base import BoundedSource, FormatPlugin
from spectra_sherpa.io.invariants import (
    INGESTION_AUTHORITY_SCHEMA,
    INGESTION_INVARIANTS,
    assert_ingestion_invariants,
)
from spectra_sherpa.io.types import IngestionResult, ParserLimits, ProbeConfidence, ProbeResult


def _attach_ingestion_authority(result: IngestionResult) -> None:
    """Bind one complete parser authority to every returned dataset.

    This lives at the registry boundary so preview, workflow loading, SDK use,
    and future consumers cannot obtain different provenance from the same
    parser result.  Asset warnings are kept with their asset while result-level
    warnings remain visible on every asset produced by the source.
    """

    source_members = [
        {
            "name": member.name,
            "sha256": member.sha256,
            "size_bytes": member.size_bytes,
        }
        for member in result.source_members
    ]
    for asset in result.assets:
        warnings = list(dict.fromkeys((*result.warnings, *asset.warnings)))
        asset.dataset.set_extra(
            "ingestion.authority",
            {
                "schema": INGESTION_AUTHORITY_SCHEMA,
                "format_id": result.format_id,
                "variant": result.variant,
                "parser_id": result.parser_id,
                "parser_version": result.parser_version,
                "asset_id": asset.asset_id,
                # Each asset owns an independent serializable projection.  A
                # consumer may legitimately annotate one dataset without
                # mutating siblings produced from the same source container.
                "source_members": [dict(member) for member in source_members],
                "warnings": warnings,
                "invariants": [invariant.value for invariant in INGESTION_INVARIANTS],
            },
        )


class FormatRegistry:
    """Deterministic registry of audited built-ins; immutable after construction."""

    def __init__(self, plugins: Iterable[FormatPlugin]) -> None:
        ordered = tuple(sorted(plugins, key=lambda plugin: plugin.format_id))
        identities = [plugin.format_id for plugin in ordered]
        if len(identities) != len(set(identities)):
            raise ValueError("Format plugin IDs must be unique")
        parser_ids = [plugin.parser_id for plugin in ordered]
        if len(parser_ids) != len(set(parser_ids)):
            raise ValueError("Format parser IDs must be unique")
        self._plugins = ordered

    @property
    def plugins(self) -> tuple[FormatPlugin, ...]:
        return self._plugins

    def probes(self, source: BoundedSource) -> tuple[ProbeResult, ...]:
        return tuple(plugin.probe(source) for plugin in self._plugins)

    def accepts_filename(self, filename: str | Path) -> bool:
        """Return whether one installed parser admits the filename family."""
        return any(
            matches_filename(
                filename,
                extensions=plugin.extensions,
                filename_patterns=tuple(getattr(plugin, "filename_patterns", ())),
            )
            for plugin in self._plugins
        )

    def select(self, source: BoundedSource) -> tuple[FormatPlugin, ProbeResult]:
        # A recognized pending container family owns its filename before generic
        # structural probes run.  In particular, real Thermo .srsx containers
        # are ZIP-based and must not be claimed as NumPy NPZ merely because they
        # begin with PK magic.
        pending = pending_format_for(source.path.name)
        if pending is not None:
            raise FormatUnavailableError(pending.unsupported_reason)

        claimed: list[tuple[FormatPlugin, ProbeResult]] = []
        for plugin in self._plugins:
            result = plugin.probe(source)
            if result.format_id != plugin.format_id:
                raise FormatIdentityError(f"Plugin {plugin.format_id} returned probe identity {result.format_id}")
            if result.confidence is not ProbeConfidence.NO_MATCH:
                claimed.append((plugin, result))
        if not claimed:
            raise UnsupportedFormatError(
                f"No registered parser structurally recognizes {source.path.name!r}; "
                "export to a supported open format or install a release that supports this instrument format"
            )
        strongest = max(result.confidence for _plugin, result in claimed)
        winners = [(plugin, result) for plugin, result in claimed if result.confidence is strongest]
        if len(winners) != 1:
            names = ", ".join(sorted(plugin.format_id for plugin, _result in winners))
            raise AmbiguousFormatError(
                f"Source {source.path.name!r} has ambiguous {strongest.name.lower()} structural matches: {names}"
            )
        return winners[0]

    def ingest(
        self,
        path: str | Path,
        *,
        limits: ParserLimits | None = None,
        parser_options: Mapping[str, str] | None = None,
    ) -> IngestionResult:
        active_limits = limits or ParserLimits()
        with BoundedSource(path, limits=active_limits) as source:
            plugin, probe = self.select(source)
            if parser_options is None:
                result = plugin.read(source, limits=active_limits)
            else:
                result = plugin.read(source, limits=active_limits, parser_options=parser_options)
            source.verify_unchanged()
        if result.format_id != plugin.format_id:
            raise FormatIdentityError(f"Parser {plugin.parser_id} returned format identity {result.format_id}")
        if probe.variant is not None and result.variant != probe.variant:
            raise FormatIdentityError(
                f"Parser {plugin.parser_id} changed variant identity from {probe.variant!r} to {result.variant!r}"
            )
        # Parser output crosses the reader boundary only after physical axis
        # meaning and units are put into the shared canonical vocabulary.  The
        # original source spelling remains available as display_units.
        for asset in result.assets:
            feature_axis = asset.dataset.feature_axis
            if feature_axis is not None:
                canonical_axis = canonicalize_feature_axis(feature_axis)
                asset.dataset.feature_axis = canonical_axis
                asset.dataset.domain = asset.dataset.domain.model_copy(update={"expected_units": canonical_axis.units})
        _attach_ingestion_authority(result)
        assert_ingestion_invariants(
            result,
            expected_format_id=plugin.format_id,
            expected_parser_id=plugin.parser_id,
            expected_parser_version=plugin.parser_version,
        )
        return result

    def capability_report(self) -> dict[str, Any]:
        """Project the formats that the native registry can execute now."""

        formats = []
        accepted: set[str] = set()
        accepted_patterns: set[str] = set()
        for plugin in self._plugins:
            extensions = list(plugin.extensions)
            filename_patterns = list(getattr(plugin, "filename_patterns", ()))
            extension_examples = list(getattr(plugin, "extension_examples", ()))
            accepted.update(extensions)
            accepted.update(extension_examples)
            accepted_patterns.update(filename_patterns)
            formats.append(
                {
                    "key": plugin.format_id,
                    "name": plugin.display_name,
                    "extensions": extensions,
                    "description": plugin.description,
                    "available": True,
                    "parserId": plugin.parser_id,
                    "parserVersion": plugin.parser_version,
                    "filenamePatterns": filename_patterns,
                    "extensionExamples": extension_examples,
                }
            )
        return {
            "acceptedExtensions": sorted(accepted),
            "acceptedFilenamePatterns": sorted(accepted_patterns),
            "formats": formats,
        }


def _builtins() -> tuple[FormatPlugin, ...]:
    from spectra_sherpa.io.formats.csv import PLUGIN as csv
    from spectra_sherpa.io.formats.jcamp import PLUGIN as jcamp
    from spectra_sherpa.io.formats.matlab import PLUGIN as matlab
    from spectra_sherpa.io.formats.numpy import PLUGIN as numpy
    from spectra_sherpa.io.formats.omnic import PLUGIN as omnic
    from spectra_sherpa.io.formats.opus import PLUGIN as opus
    from spectra_sherpa.io.formats.renishaw_text import PLUGIN as renishaw_text
    from spectra_sherpa.io.formats.sherpa_json import PLUGIN as sherpa_json
    from spectra_sherpa.io.formats.spc import PLUGIN as spc
    from spectra_sherpa.io.formats.wdf import PLUGIN as wdf

    return (csv, jcamp, matlab, numpy, omnic, opus, renishaw_text, sherpa_json, spc, wdf)


builtin_registry = FormatRegistry(_builtins())


# This is source-identity authority, not an import convenience. Every in-tree
# module executed by the native reader and its CSV projection adapter is named
# so a change to axis normalization, data-role derivation, parser invariants,
# or any format body changes every consuming node/qualification digest. Keep
# the list explicit and let the AST closure test fail when a new module-level
# first-party dependency is introduced.
_NATIVE_IMPLEMENTATION_MODULE_NAMES = (
    "spectra_sherpa.app.core.path_security",
    "spectra_sherpa.app.lib.axes",
    "spectra_sherpa.app.lib.data_roles",
    "spectra_sherpa.app.lib.domain_flags",
    "spectra_sherpa.app.lib.io",
    "spectra_sherpa.app.lib.jcamp_reader",
    "spectra_sherpa.app.lib.portable_csv",
    "spectra_sherpa.app.lib.portable_json",
    "spectra_sherpa.app.lib.scientific_values",
    "spectra_sherpa.app.lib.sherpa_dataset",
    "spectra_sherpa.app.lib.synthetic_npz",
    "spectra_sherpa.core.axis_semantics",
    "spectra_sherpa.core.dimension_roles",
    "spectra_sherpa.core.prepared_data",
    "spectra_sherpa.core.target_authority",
    "spectra_sherpa.ingestion_errors",
    "spectra_sherpa.ingestion_formats",
    "spectra_sherpa.io.authority",
    "spectra_sherpa.io.base",
    "spectra_sherpa.io.formats._helpers",
    "spectra_sherpa.io.formats._text_limits",
    "spectra_sherpa.io.formats.csv",
    "spectra_sherpa.io.formats.dso",
    "spectra_sherpa.io.formats.jcamp",
    "spectra_sherpa.io.formats.matlab",
    "spectra_sherpa.io.formats.matlab_v73",
    "spectra_sherpa.io.formats.numpy",
    "spectra_sherpa.io.formats.omnic",
    "spectra_sherpa.io.formats.opus",
    "spectra_sherpa.io.formats.process_log",
    "spectra_sherpa.io.formats.renishaw_text",
    "spectra_sherpa.io.formats.sherpa_json",
    "spectra_sherpa.io.formats.spc",
    "spectra_sherpa.io.formats.wdf",
    "spectra_sherpa.io.invariants",
    "spectra_sherpa.io.selection",
    "spectra_sherpa.io.types",
)

_JCAMP_IMPLEMENTATION_MODULE_NAMES = (
    "spectra_sherpa.app.core.path_security",
    "spectra_sherpa.app.lib.axes",
    "spectra_sherpa.app.lib.data_roles",
    "spectra_sherpa.app.lib.domain_flags",
    "spectra_sherpa.app.lib.jcamp_reader",
    "spectra_sherpa.app.lib.scientific_values",
    "spectra_sherpa.app.lib.sherpa_dataset",
    "spectra_sherpa.core.axis_semantics",
    "spectra_sherpa.core.dimension_roles",
    "spectra_sherpa.core.target_authority",
    "spectra_sherpa.ingestion_errors",
    "spectra_sherpa.ingestion_formats",
    "spectra_sherpa.io.base",
    "spectra_sherpa.io.formats._helpers",
    "spectra_sherpa.io.formats._text_limits",
    "spectra_sherpa.io.formats.jcamp",
    "spectra_sherpa.io.types",
)


def ingest(
    path: str | Path,
    *,
    limits: ParserLimits | None = None,
    parser_options: Mapping[str, str] | None = None,
) -> IngestionResult:
    """Read one source through the frozen built-in registry."""

    return builtin_registry.ingest(path, limits=limits, parser_options=parser_options)


def native_implementation_modules() -> tuple[ModuleType, ...]:
    """Return the closed in-tree implementation closure for native ingestion."""

    return tuple(import_module(name) for name in _NATIVE_IMPLEMENTATION_MODULE_NAMES)


def jcamp_implementation_modules() -> tuple[ModuleType, ...]:
    """Return the exact delegated closure used by the native JCAMP parser."""

    return tuple(import_module(name) for name in _JCAMP_IMPLEMENTATION_MODULE_NAMES)


__all__ = [
    "FormatRegistry",
    "builtin_registry",
    "ingest",
    "jcamp_implementation_modules",
    "native_implementation_modules",
]
