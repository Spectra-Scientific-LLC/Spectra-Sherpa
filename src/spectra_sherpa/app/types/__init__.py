"""
SpectraSherpa Type Registry.

Provides a singleton :data:`type_registry` loaded at application startup.
All type resolution, compatibility checks, and subtype queries go through
this registry.

Usage::

    from spectra_sherpa.app.types import type_registry

    td = type_registry.resolve("spectrasherpa://types/SpectralDataset/1.0")
    ok, reason = type_registry.is_compatible(source_ref, target_ref)
"""

from pathlib import Path

from .registry import TypeDef, TypeRegistry, parse_type_ref

# Singleton — populated by app.main lifespan handler via type_registry.load()
type_registry = TypeRegistry()


def ensure_type_registry_loaded() -> None:
    """Load the packaged semantic vocabulary for an explicit offline consumer.

    Application startup owns normal server initialization.  This narrow helper
    exists for direct SDK/support-tool use, where no ASGI lifespan is present;
    callers opt in before requesting semantic analysis.  Admission endpoints
    deliberately do not call it and therefore still fail closed if startup did
    not establish the registry.
    """
    if not type_registry.is_loaded:
        type_registry.load(Path(__file__).resolve().parent)


__all__ = [
    "type_registry",
    "TypeRegistry",
    "TypeDef",
    "parse_type_ref",
    "ensure_type_registry_loaded",
]
