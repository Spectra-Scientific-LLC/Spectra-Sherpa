"""
Shared mode policy for local / hybrid / enterprise runtime behavior.

This module captures cross-cutting, request-time policy decisions used in
multiple places (HTTP auth, WebSocket auth, client config gating). One-shot
startup validation can still read ``app_config`` directly.
"""

from __future__ import annotations

from spectra_sherpa.app.core.config import app_config


def is_loopback(host: str | None) -> bool:
    """Check if a client address is a loopback address.

    Returns ``False`` for ``None`` (fail closed — unknown client is not
    considered loopback).
    """
    if not host:
        return False
    return host in ("127.0.0.1", "::1") or host.startswith("::ffff:127.")


# ── Identity shortcuts ───────────────────────────────────────────


def is_local() -> bool:
    """True when running in single-user desktop mode."""
    return app_config.mode == "local"


def is_hybrid() -> bool:
    """True when running in hybrid (local + optional cloud) mode."""
    return app_config.mode == "hybrid"


def is_enterprise() -> bool:
    """True when running in enterprise / SaaS mode (JWT auth, rate-limits, PostgreSQL required)."""
    return app_config.mode == "enterprise"


def is_multi_user() -> bool:
    """True when the mode requires user management (hybrid or enterprise)."""
    return app_config.mode != "local"


def allows_admin() -> bool:
    """Whether admin routes are enabled.

    Backward-compatible helper used by spectra-server admin routes.
    Admin capabilities are only meaningful in multi-user modes.
    """
    return is_multi_user()


# ── Authentication ───────────────────────────────────────────────


def requires_http_auth(client_host: str | None) -> bool:
    """Whether an HTTP request from *client_host* must carry credentials.

    - Local mode: never requires auth.
    - Hybrid mode: loopback clients are exempt; remote clients need auth.
    - Enterprise mode: all clients need auth.
    """
    if app_config.mode == "local":
        return False
    if app_config.mode == "hybrid":
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

    Registration is only surfaced when:
    - mode is multi-user (hybrid/enterprise), and
    - server auth routes are available in this distribution.
    """
    if not is_multi_user():
        return False
    try:
        from spectrasherpa_server.routes import auth as _auth_mod  # noqa: F401
    except ImportError:
        return False
    return hasattr(_auth_mod, "router")


def allows_custom_code_execution() -> bool:
    """Whether user-authored custom algo code (ualgo.*) is allowed.

    Controlled by ``CUSTOM_CODE_EXECUTION_ENABLED`` and forced off in demo
    site profile unless explicitly overridden.
    """
    if not app_config.custom_code_execution_enabled:
        return False
    if app_config.site_profile == "demo":
        return False
    return True


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
    """In local mode, all CORS origins are permitted (desktop convenience)."""
    return app_config.mode == "local"


# ── Limits ───────────────────────────────────────────────────────


def has_rate_limits() -> bool:
    """True when rate limiting / session expiry enforcement is active."""
    return app_config.mode in ("hybrid", "enterprise")
