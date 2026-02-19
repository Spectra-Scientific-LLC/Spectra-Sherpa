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

from .registry import TypeDef, TypeRegistry, parse_type_ref

# Singleton — populated by app.main lifespan handler via type_registry.load()
type_registry = TypeRegistry()

__all__ = [
    "type_registry",
    "TypeRegistry",
    "TypeDef",
    "parse_type_ref",
]
