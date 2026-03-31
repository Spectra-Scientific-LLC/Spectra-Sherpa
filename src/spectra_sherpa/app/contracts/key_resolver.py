"""Optional hook for server-injected API key resolution.

OSS resolves LLM API keys from environment variables and per-user BYOK
keys only.  The server can inject an ``ExtraKeyResolver`` to add
system-wide admin-managed keys as a final fallback.

Usage (in spectra-server startup)::

    from spectra_sherpa.app.contracts import set_extra_key_resolver

    async def server_key_resolver(provider: str, session: Any) -> str | None:
        # query system keys from the shared api_key table
        ...

    set_extra_key_resolver(server_key_resolver)
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Awaitable

logger = logging.getLogger(__name__)

# Protocol: async (provider: str, session: AsyncSession) -> str | None
ExtraKeyResolver = Callable[[str, Any], Awaitable[str | None]]

_extra_key_resolver: ExtraKeyResolver | None = None


def get_extra_key_resolver() -> ExtraKeyResolver | None:
    """Return the injected key resolver, or None if not set."""
    return _extra_key_resolver


def set_extra_key_resolver(resolver: ExtraKeyResolver) -> None:
    """Inject a server-provided key resolver for system-wide API keys.

    Called by spectra-server during startup to add system key lookup
    as a fallback after environment variables and per-user BYOK keys.
    """
    global _extra_key_resolver
    _extra_key_resolver = resolver
    logger.info("ExtraKeyResolver: custom implementation injected")
