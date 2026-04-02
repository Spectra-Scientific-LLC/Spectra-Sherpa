"""
Shared mode policy for local / hybrid / enterprise runtime behavior.

This module captures cross-cutting, request-time policy decisions used in
multiple places (HTTP auth, WebSocket auth, client config gating). One-shot
startup validation can still read ``app_config`` directly.

Mode summary for developers:

- **local** — Single user on localhost. No auth. BYOK LLM only. No Sherpa
  advisor (``DisabledAIProvider``). Egress gates never reached because the
  advisor stub returns before any network call.

- **hybrid** — Local user + optional cloud features. The local spectra-sherpa
  instance calls the cloud spectrasherpa-server via ``DeploymentAIProvider``
  (HTTP with ``X-Deployment-Key``). Loopback browser connections need no auth;
  non-loopback connections (defense-in-depth if bound to 0.0.0.0) require
  first-message WebSocket auth. Egress permission
  ``allow_spectrasherpa_sync`` gates whether workflow data is sent to the
  cloud — must be True in the user's ``UserEgressDefaults`` row.

- **enterprise** — Cloud-hosted multi-user deployment. All connections require
  first-message WebSocket auth with a valid JWT. Sherpa advisor runs
  in-process via ``ServerAIProvider`` (injected by spectra-server).
  Subscriptions gate individual features via entitlements.
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
    """True when running in enterprise / SaaS mode (JWT auth, rate-limits)."""
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
    return app_config.mode in ("hybrid", "enterprise")
