"""Pluggable public-path provider for gateway auth bypass.

OSS owns the core list of paths that must be reachable without
authentication (health endpoints, client config; the SPA catchall is
handled separately). Extension packages (e.g. ``spectra-server``) can
append additional paths at startup — for example ``/api/v1/auth/login``
and ``/api/v1/auth/register`` — by calling :func:`register_public_paths`.

Paths registered via :func:`register_public_paths` are appended (deduped)
rather than replaced so multiple extensions can coexist without
clobbering each other.

Usage (in spectra-server startup)::

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
from typing import Iterable

logger = logging.getLogger(__name__)

# Core paths the OSS gateway always treats as public. Keep this list in
# sync with the gateway's own expectations in
# ``spectra_sherpa.app.core.security.api_key_middleware``.
OSS_PUBLIC_PATHS: tuple[str, ...] = (
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
)

_extra_paths: list[str] = []
_combined_paths: frozenset[str] = frozenset(OSS_PUBLIC_PATHS)


def register_public_paths(paths: Iterable[str]) -> None:
    """Append ``paths`` to the gateway bypass list.

    Existing entries are preserved; duplicate paths are ignored so that
    multiple registrars can coexist. Paths must start with ``/``.
    """
    global _combined_paths
    added = 0
    for raw in paths:
        path = raw.strip()
        if not path:
            continue
        if not path.startswith("/"):
            raise ValueError(
                f"register_public_paths: paths must start with '/'; got {raw!r}"
            )
        if path in _combined_paths:
            continue
        _extra_paths.append(path)
        added += 1
    if added:
        _combined_paths = frozenset(OSS_PUBLIC_PATHS) | frozenset(_extra_paths)
        logger.info(
            "public_path_provider: %d new path(s) registered (%d extras total)",
            added,
            len(_extra_paths),
        )


def get_public_paths() -> frozenset[str]:
    """Return the full public-path set (core + extensions).

    Returns an immutable ``frozenset`` so the gateway middleware can do
    O(1) membership checks per request without rebuilding the set.
    """
    return _combined_paths


def _reset_for_tests() -> None:
    """Clear registered extra paths. Tests only."""
    global _extra_paths, _combined_paths
    _extra_paths = []
    _combined_paths = frozenset(OSS_PUBLIC_PATHS)
