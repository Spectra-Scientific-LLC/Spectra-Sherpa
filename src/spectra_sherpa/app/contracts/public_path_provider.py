"""Pluggable public-path provider for gateway auth bypass.

OSS owns the core list of paths that must be reachable without
authentication (health endpoints, client config, the SPA catchall is
handled separately). Server extension packages can
append additional paths at startup — for example ``/api/v1/auth/login``
and ``/api/v1/auth/register`` — by calling :func:`register_public_paths`.

Call ``register_public_paths`` at most once per logical registrar; paths
are appended (deduped) rather than replaced so multiple extensions can
coexist without clobbering each other.

Usage (in server extension startup)::

    from spectra_sherpa.app.contracts.public_path_provider import (
        register_public_paths,
    )

    register_public_paths([
        "/api/v1/auth/login",
        "/api/v1/auth/register",
    ])
"""

from __future__ import annotations

import logging
from typing import Iterable, List

logger = logging.getLogger(__name__)

# Core paths the OSS gateway always treats as public. Keep this list in
# sync with the gateway's own expectations in
# ``spectra_sherpa.app.core.security.api_key_middleware``.
OSS_PUBLIC_PATHS: List[str] = [
    "/",
    "/health",
    "/api/health",
    "/api/ready",
    "/api/v1/health",
    "/api/v1/config",
    "/docs",
    "/redoc",
    "/openapi.json",
    "/api/openapi.json",
]

_extra_paths: List[str] = []


def register_public_paths(paths: Iterable[str]) -> None:
    """Append ``paths`` to the gateway bypass list.

    Existing entries are preserved; duplicate paths are ignored so that
    multiple registrars can coexist. Paths must start with ``/``.
    """
    for raw in paths:
        path = raw.strip()
        if not path:
            continue
        if not path.startswith("/"):
            raise ValueError(f"register_public_paths: paths must start with '/'; got {raw!r}")
        if path in OSS_PUBLIC_PATHS or path in _extra_paths:
            continue
        _extra_paths.append(path)
    logger.info(
        "public_path_provider: %d extra path(s) registered",
        len(_extra_paths),
    )


def get_public_paths() -> List[str]:
    """Return the full public-path list (core + extensions).

    The gateway middleware in ``security.py`` consumes this on every
    request; returning a fresh list keeps callers from mutating the
    module state by accident.
    """
    return list(OSS_PUBLIC_PATHS) + list(_extra_paths)


def _reset_for_tests() -> None:
    """Clear registered extra paths. Tests only."""
    global _extra_paths
    _extra_paths = []
