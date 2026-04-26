"""Pluggable auth-policy flags owned by the commercial server.

OSS cannot authoritatively decide whether user self-registration is
enabled or whether an access-code (``ENTERPRISE_PASSWORD``) gate is
active — those are server concerns. Before this contract existed, OSS
relied on an import-probe heuristic against the server implementation,
which silently returned ``True`` under a monorepo layout where the
server package is always importable even when its routes are not
actively mounted.

This contract replaces the heuristic with explicit startup registration:
A server extension calls :func:`set_registration_enabled` and
:func:`set_registration_requires_code` from its startup hooks based on
its own configuration. OSS reads the flags via
:func:`registration_enabled` and :func:`registration_requires_code`,
both of which default to ``False`` in OSS-only installs.

Typical usage (in server extension startup)::

    from spectra_sherpa.app.contracts.auth_policy import (
        set_registration_enabled,
        set_registration_requires_code,
    )

    set_registration_enabled(enterprise_registration_is_open)
    set_registration_requires_code(bool(os.getenv("ENTERPRISE_PASSWORD")))
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

_registration_enabled: bool = False
_registration_requires_code: bool = False


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


def set_registration_requires_code(flag: bool) -> None:
    """Declare whether self-registration requires an access code.

    Enterprise deployments use ``ENTERPRISE_PASSWORD`` to gate who can
    create an account; the server translates that into this flag at
    startup. OSS does not read the env var directly.
    """
    global _registration_requires_code
    _registration_requires_code = bool(flag)
    logger.info("auth_policy: registration_requires_code=%s", _registration_requires_code)


def registration_requires_code() -> bool:
    """Return the current server-declared access-code gate flag."""
    return _registration_requires_code


def _reset_for_tests() -> None:
    """Reset flags to defaults. Tests only."""
    global _registration_enabled, _registration_requires_code
    _registration_enabled = False
    _registration_requires_code = False
