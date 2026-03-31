"""Minimal identity protocol for OSS code.

The OSS codebase should type-annotate user parameters as ``CurrentActor``
rather than importing the full ``User`` ORM model.  This keeps the
contract narrow: OSS only needs ``id``, ``username``, and ``is_active``.

The concrete ``User`` SQLAlchemy model satisfies this protocol (it has
all three attributes), so enterprise code can pass ``User`` objects
directly without adapters.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class CurrentActor(Protocol):
    """Minimal identity contract consumed by OSS platform code.

    Local mode: a lightweight workspace owner created at first startup.
    Hybrid/Enterprise mode: the full ``User`` ORM satisfies this protocol.

    Enterprise-only attributes (``is_superuser``, ``password_hash``,
    ``login_count``, etc.) are intentionally excluded.  OSS code that
    needs to check optional capabilities should use
    ``getattr(actor, "is_superuser", False)`` instead of assuming the
    attribute exists.
    """

    id: int
    username: str
    is_active: bool
