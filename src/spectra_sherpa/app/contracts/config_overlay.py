"""Optional hook for server-injected config overlay.

OSS returns base configuration with all Sherpa capabilities disabled.
The server can inject a ``ConfigOverlayProvider`` to merge subscription
entitlements, demo metadata, and rate limits into the client config.

Usage (in spectra-server startup)::

    from spectra_sherpa.app.contracts import set_config_overlay_provider

    async def server_overlay(deployment_key: str | None) -> dict[str, Any] | None:
        # fetch subscription entitlements, merge demo config, etc.
        ...

    set_config_overlay_provider(server_overlay)
"""

from __future__ import annotations

import logging
from typing import Any, Awaitable, Callable

logger = logging.getLogger(__name__)

# Protocol: async (deployment_key: str | None) -> overlay dict or None
ConfigOverlayProvider = Callable[[str | None], Awaitable[dict[str, Any] | None]]

_config_overlay_provider: ConfigOverlayProvider | None = None


def get_config_overlay_provider() -> ConfigOverlayProvider | None:
    """Return the injected config overlay provider, or None if not set."""
    return _config_overlay_provider


def set_config_overlay_provider(provider: ConfigOverlayProvider) -> None:
    """Inject a server-provided config overlay provider.

    Called by spectra-server during startup to add subscription
    entitlements, demo metadata, and rate limits to client config.
    """
    global _config_overlay_provider
    _config_overlay_provider = provider
    logger.info("ConfigOverlayProvider: custom implementation injected")
