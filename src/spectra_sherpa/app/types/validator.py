"""
Connection validator using the type registry.

Provides :func:`can_connect` which checks whether a source port's
``type_ref`` is compatible with a target port's ``type_ref`` using
subtype and version rules from the type registry.
"""

from __future__ import annotations


def can_connect(source_type_ref: str, target_type_ref: str) -> tuple[bool, str]:
    """Check whether *source_type_ref* can connect to *target_type_ref*.

    Uses the singleton :data:`app.types.type_registry` for resolution
    and compatibility checks.

    Args:
        source_type_ref: URI of the producing port.
        target_type_ref: URI of the consuming port.

    Returns:
        ``(True, "")`` when compatible, ``(False, reason)`` otherwise.
    """
    from spectra_sherpa.app.types import type_registry

    compatible, reason = type_registry.is_compatible(source_type_ref, target_type_ref)
    return compatible, reason
