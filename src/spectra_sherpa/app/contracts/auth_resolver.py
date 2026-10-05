"""Optional hook for server-injected managed API-key authentication.

OSS does not own managed password/API-key identity. When the proprietary
server is mounted, it can inject an ``ExtraUserAPIKeyAuthenticator`` that
maps a presented gateway API key to a user id.

Usage (in server extension startup)::

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


# ---------------------------------------------------------------------------
# Bearer-token subject resolver (server-owned JWT decode)
# ---------------------------------------------------------------------------
#
# OSS deleted its JWT primitives in v0.4.1 Phase 2. For HTTP requests,
# the server's EnterpriseEnforcementMiddleware runs before the OSS
# gateway and writes the decoded ``sub`` claim to
# ``request.state.authenticated_subject``; OSS reads that and loads the
# user (see ``deps._resolve_user``). WebSocket auth does not go through
# that middleware, so OSS exposes this contract as an alternative: the
# server registers a resolver that returns the user-id for a raw JWT.
# OSS default: no resolver (WS JWT auth returns None). Server populates
# with real decode.

BearerTokenSubjectResolver = Callable[[str], Awaitable[int | None]]

_extra_bearer_token_resolver: BearerTokenSubjectResolver | None = None


def get_extra_bearer_token_resolver() -> BearerTokenSubjectResolver | None:
    """Return the injected JWT-subject resolver, if configured."""
    return _extra_bearer_token_resolver


def set_extra_bearer_token_resolver(resolver: BearerTokenSubjectResolver) -> None:
    """Inject a server-provided resolver that maps a JWT to a user id."""
    global _extra_bearer_token_resolver
    _extra_bearer_token_resolver = resolver
    logger.info("ExtraBearerTokenResolver: custom implementation injected")


def clear_extra_bearer_token_resolver() -> None:
    """Reset the injected JWT-subject resolver."""
    global _extra_bearer_token_resolver
    _extra_bearer_token_resolver = None


# ---------------------------------------------------------------------------
# Bearer-token validator (server-owned session policy enforcement for WS)
# ---------------------------------------------------------------------------
#
# HTTP requests pass through the server's EnterpriseEnforcementMiddleware,
# which stamps request.state only after enforcing session expiry, revocation
# and active-account policy. WebSocket connections do not traverse that
# middleware, so OSS exposes this validator: the server decodes a raw JWT
# and returns the payload only if it passes the same policy checks. The
# WebSocket loop stores the payload and revalidates it before each protected
# action. OSS default: no validator (WS JWT auth returns None).

BearerTokenValidator = Callable[[str], Awaitable[dict | None]]

_extra_bearer_token_validator: BearerTokenValidator | None = None


def get_extra_bearer_token_validator() -> BearerTokenValidator | None:
    """Return the injected JWT validator, if configured."""
    return _extra_bearer_token_validator


def set_extra_bearer_token_validator(validator: BearerTokenValidator) -> None:
    """Inject a server-provided validator that returns a decoded payload or None."""
    global _extra_bearer_token_validator
    _extra_bearer_token_validator = validator
    logger.info("ExtraBearerTokenValidator: custom implementation injected")


def clear_extra_bearer_token_validator() -> None:
    """Reset the injected JWT validator."""
    global _extra_bearer_token_validator
    _extra_bearer_token_validator = None


# ---------------------------------------------------------------------------
# Admin-capability resolver (server-owned superuser lookup)
# ---------------------------------------------------------------------------
#
# After v0.4.1 Trim A, OSS's ``User`` model no longer carries
# ``is_superuser`` — that flag lives on ``ManagedUserAccount`` in the
# server package. Any OSS code path that previously gated admin-only
# behavior via ``getattr(user, "is_superuser", False)`` will silently
# return False for a real server superuser (WebSocket admin-jobs
# channel, tool scope check, ws rate-limit bypass).
#
# This contract lets OSS ask "is this user an admin?" without
# importing server internals. The server registers an async resolver
# that joins to ``ManagedUserAccount``; OSS default returns False
# (local mode has no superuser concept). Callers should use the
# convenience helper ``is_admin_user(user)`` below so the contract
# plumbing stays private.

AdminResolver = Callable[[int], Awaitable[bool]]

_extra_admin_resolver: AdminResolver | None = None


def get_extra_admin_resolver() -> AdminResolver | None:
    """Return the injected admin resolver, if configured."""
    return _extra_admin_resolver


def set_extra_admin_resolver(resolver: AdminResolver) -> None:
    """Inject a server-provided resolver mapping user-id -> admin bool."""
    global _extra_admin_resolver
    _extra_admin_resolver = resolver
    logger.info("ExtraAdminResolver: custom implementation injected")


def clear_extra_admin_resolver() -> None:
    """Reset the injected admin resolver."""
    global _extra_admin_resolver
    _extra_admin_resolver = None


async def is_admin_user(user: Any) -> bool:
    """Return True when ``user`` resolves to a server-side superuser.

    Safe convenience helper for OSS admin gates: returns False for
    None, for users missing an id, and when no admin resolver is
    registered. In local mode (no server) there are no superusers,
    so the default False is the correct answer.
    """
    if user is None:
        return False
    user_id = getattr(user, "id", None)
    if user_id is None:
        return False
    resolver = get_extra_admin_resolver()
    if resolver is None:
        return False
    return bool(await resolver(int(user_id)))


# ---------------------------------------------------------------------------
# Managed-compute access resolver (server-owned trial/subscription lifecycle)
# ---------------------------------------------------------------------------

UserComputeAccessResolver = Callable[[int], Awaitable[bool]]

_user_compute_access_resolver: UserComputeAccessResolver | None = None


def set_user_compute_access_resolver(resolver: UserComputeAccessResolver) -> None:
    """Inject the managed server's per-user compute lifecycle decision."""

    global _user_compute_access_resolver
    _user_compute_access_resolver = resolver
    logger.info("UserComputeAccessResolver: custom implementation injected")


def clear_user_compute_access_resolver() -> None:
    """Restore the OSS/local default, which has no managed lifecycle."""

    global _user_compute_access_resolver
    _user_compute_access_resolver = None


async def user_allows_compute(user: Any) -> bool:
    """Return whether an authenticated user may invoke managed compute.

    With no proprietary resolver installed, OSS/local execution remains
    available. Once a server installs the resolver, missing user identity and
    provider errors fail closed at the caller.
    """

    resolver = _user_compute_access_resolver
    if resolver is None:
        return True
    user_id = getattr(user, "id", None)
    if user_id is None:
        return False
    return bool(await resolver(int(user_id)))
