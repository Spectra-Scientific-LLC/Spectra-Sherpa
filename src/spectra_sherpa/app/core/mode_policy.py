"""Shared core policy with explicitly installed product runtime overrides."""

from __future__ import annotations

import os

from spectra_sherpa.app.contracts.runtime_mode import runtime_mode_policy
from spectra_sherpa.app.core.config import app_config


def is_loopback(host: str | None) -> bool:
    """Check if a client address is a loopback address.

    Returns ``False`` for ``None`` (fail closed — unknown client is not
    considered loopback).
    """
    if not host:
        return False
    return host in ("127.0.0.1", "::1") or host.startswith("::ffff:127.")


def _env_truthy(*names: str) -> bool:
    for name in names:
        value = os.getenv(name, "").strip().lower()
        if value in {"1", "true", "yes", "on"}:
            return True
    return False


def local_network_access_allowed() -> bool:
    """Whether local mode may accept non-loopback clients.

    Local mode intentionally has no login barrier and grants the implicit
    desktop user to callers. That is safe only for loopback access. Operators
    who deliberately run local mode behind another trusted access-control layer
    can opt in explicitly with either env spelling.
    """

    return _env_truthy("SPECTRA_SHERPA_ALLOW_LOCAL_NETWORK", "SPECTRASHERPA_ALLOW_LOCAL_NETWORK")


def blocks_local_network_client(client_host: str | None) -> bool:
    """Return True when a local-mode request must be rejected at the edge."""

    return app_config.mode == "local" and not is_loopback(client_host) and not local_network_access_allowed()


# ── Identity shortcuts ───────────────────────────────────────────


def is_local() -> bool:
    """True when running in single-user desktop mode."""
    return app_config.mode == "local"


def allows_implicit_loopback_identity() -> bool:
    """An installed product may request local identity for loopback only."""
    policy = runtime_mode_policy(app_config.mode)
    return policy is not None and policy.implicit_loopback_identity


def is_enterprise() -> bool:
    """True when running in enterprise / SaaS mode (JWT auth, rate-limits)."""
    return app_config.mode == "enterprise"


def is_multi_user() -> bool:
    """True when the mode requires user management (managed)."""
    return app_config.mode != "local"


def allows_admin() -> bool:
    """Whether admin routes are enabled.

    Backward-compatible helper used by server admin routes.
    Admin capabilities are only meaningful in multi-user modes.
    """
    return is_multi_user()


# ── Authentication ───────────────────────────────────────────────


def requires_http_auth(client_host: str | None) -> bool:
    """Whether an HTTP request from *client_host* must carry credentials.

    - Local mode: never requires auth.
    - Installed product policy: may exempt positively identified loopback clients.
    - Enterprise mode: all clients need auth.
    """
    if app_config.mode == "local":
        return False
    if allows_implicit_loopback_identity():
        return not is_loopback(client_host)
    # enterprise (and any future mode): always require auth
    return True


def requires_ws_auth(client_host: str | None) -> bool:
    """Whether a WebSocket connection from *client_host* must carry credentials.

    Same rules as HTTP auth.
    """
    return requires_http_auth(client_host)


def allows_registration() -> bool:
    """Whether user self-registration is open.

    This is a thin wrapper over the ``auth_policy`` contract: the
    server extension startup registers a flag declaring whether
    registration is active; OSS reads it here. The earlier heuristic
    of probing the server implementation package is unsafe under a monorepo
    layout (where the package can be importable even when its routes are not
    actively mounted), so it has been removed.

    Returns ``True`` only when:
    - the runtime mode is multi-user (managed), AND
    - the server has called ``auth_policy.set_registration_enabled(True)``
      at startup.

    When no server has registered (OSS-only installs) this returns
    ``False``, which is the correct default — OSS does not ship the
    ``/auth/register`` route.
    """
    if not is_multi_user():
        return False

    from spectra_sherpa.app.contracts.auth_policy import registration_enabled

    return registration_enabled()


# ── API key validation ───────────────────────────────────────────


def api_key_always_valid() -> bool:
    """In local mode, all API keys are accepted without database check."""
    return app_config.mode == "local"


def system_api_key_always_accepted() -> bool:
    """In local mode, the system API key is always accepted."""
    return app_config.mode == "local"


# ── Egress & exports ────────────────────────────────────────────


def export_always_allowed() -> bool:
    """In local mode, data exports are always permitted (single-user)."""
    return app_config.mode == "local"


def cors_allow_all() -> bool:
    """Whether to allow all CORS origins.

    Always returns False — even in local mode, CORS is restricted to
    localhost origins to prevent cross-origin data exfiltration from
    malicious websites targeting the local server.
    """
    return False


# ── Limits ───────────────────────────────────────────────────────


def has_rate_limits() -> bool:
    """True when rate limiting / session expiry enforcement is active."""
    policy = runtime_mode_policy(app_config.mode)
    return policy.rate_limits if policy is not None else app_config.mode == "enterprise"
