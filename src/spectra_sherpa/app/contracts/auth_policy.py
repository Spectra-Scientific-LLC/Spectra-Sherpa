"""Pluggable registration-availability policy owned by the commercial server.

OSS cannot authoritatively decide whether user self-registration is enabled.
Before this contract existed, OSS relied on an import-probe heuristic against
the server implementation, which silently returned ``True`` under a monorepo
layout where the server package is always importable even when its routes are
not actively mounted.

This contract replaces the heuristic with explicit startup registration:
A server extension calls :func:`set_registration_enabled` from its startup
hooks. OSS reads the flag via :func:`registration_enabled`, which defaults to
``False`` in OSS-only installs. Email verification is a managed-server route
contract and is deliberately not represented as a shared-secret UI flag.

Typical usage (in server extension startup)::

    from spectra_sherpa.app.contracts.auth_policy import set_registration_enabled

    set_registration_enabled(enterprise_registration_is_open)
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

_registration_enabled: bool = False


def set_registration_enabled(flag: bool) -> None:
    """Declare whether user self-registration is currently available.

    Intended to be called once at server startup. Subsequent calls
    update the flag; the OSS gateway and config shape read the current
    value on every request.
    """
    global _registration_enabled
    _registration_enabled = bool(flag)
    logger.info("auth_policy: registration_enabled=%s", _registration_enabled)


def registration_enabled() -> bool:
    """Return the current server-declared registration flag.

    Defaults to ``False`` when no server has registered a value — the
    correct answer for OSS-only installs, which do not ship the
    ``/auth/register`` route.
    """
    return _registration_enabled


def _reset_for_tests() -> None:
    """Reset flags to defaults. Tests only."""
    global _registration_enabled
    _registration_enabled = False
