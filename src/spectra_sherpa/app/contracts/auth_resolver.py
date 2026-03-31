"""Optional hook for server-injected managed API-key authentication.

OSS does not own managed password/API-key identity. When the proprietary
server is mounted, it can inject an ``ExtraUserAPIKeyAuthenticator`` that
maps a presented gateway API key to a user id.

Usage (in spectra-server startup)::

    from spectra_sherpa.app.contracts import set_extra_user_api_key_authenticator

    async def authenticate_user_api_key(api_key: str, session: Any) -> int | None:
        ...

    set_extra_user_api_key_authenticator(authenticate_user_api_key)
"""

from __future__ import annotations

import logging
from typing import Any, Awaitable, Callable

logger = logging.getLogger(__name__)

ExtraUserAPIKeyAuthenticator = Callable[[str, Any], Awaitable[int | None]]

_extra_user_api_key_authenticator: ExtraUserAPIKeyAuthenticator | None = None


def get_extra_user_api_key_authenticator() -> ExtraUserAPIKeyAuthenticator | None:
    """Return the injected managed API-key authenticator, if configured."""
    return _extra_user_api_key_authenticator


def set_extra_user_api_key_authenticator(authenticator: ExtraUserAPIKeyAuthenticator) -> None:
    """Inject a server-provided authenticator for managed user API keys."""
    global _extra_user_api_key_authenticator
    _extra_user_api_key_authenticator = authenticator
    logger.info("ExtraUserAPIKeyAuthenticator: custom implementation injected")


def clear_extra_user_api_key_authenticator() -> None:
    """Reset the injected managed API-key authenticator."""
    global _extra_user_api_key_authenticator
    _extra_user_api_key_authenticator = None
