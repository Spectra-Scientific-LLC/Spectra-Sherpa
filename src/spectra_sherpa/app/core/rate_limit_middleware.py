"""
Rate Limit Middleware

Enforces conservative auth endpoint throttling for HYBRID and ENTERPRISE mode
deployments.  User-facing paid usage is governed separately by the Sherpa/LLM
rate limiter.  Demo-profile execution quotas are enforced by the commercial server's
``EnterpriseEnforcementMiddleware``.

Rate limiting uses the persistent file-backed RateLimiter so state survives
restarts and is consistent across Gunicorn workers.

Enterprise-specific enforcement (password gating, session expiry, CORS
validation) lives in the commercial server and is injected via create_app() hooks.
"""

import json
from typing import Any

from fastapi import Request, Response, status
from starlette.middleware.base import BaseHTTPMiddleware

from spectra_sherpa.app.core.app_paths import get_app_data_paths
from spectra_sherpa.app.core.config import settings
from spectra_sherpa.app.core.mode_policy import has_rate_limits
from spectra_sherpa.app.core.security import get_client_host
from spectra_sherpa.app.services.rate_limiter import RateLimiter


class RateLimitMiddleware(BaseHTTPMiddleware):
    """
    Rate limiting for Hybrid and Enterprise modes:
    1. Auth endpoint rate limiting per IP (login, register)
    """

    # Paths that bypass rate limiting
    PUBLIC_PATHS = {
        "/",
        "/api/v1/health",
        "/api/v1/config",
        "/api/v1/auth/login",
        "/docs",
        "/openapi.json",
        "/api/openapi.json",
    }

    # Auth endpoints get stricter per-IP rate limiting
    AUTH_RATE_LIMITS = {
        "/api/v1/auth/login": (10, 900),  # 10 attempts per 15 minutes
        "/api/v1/auth/register": (5, 3600),  # 5 registrations per hour
    }

    def __init__(self, app):
        super().__init__(app)
        app_paths = get_app_data_paths(settings.data_dir)
        # Separate rate limiters for auth endpoints (per-IP, tighter)
        self._auth_limiters = {
            path: RateLimiter(
                max_calls=max_calls,
                period_sec=period,
                state_path=app_paths.auth_rate_limit_state(path.rsplit("/", 1)[-1]),
            )
            for path, (max_calls, period) in self.AUTH_RATE_LIMITS.items()
        }

    async def dispatch(self, request: Request, call_next) -> Response:
        # Only active in multi-user modes (Hybrid and Enterprise)
        if not has_rate_limits():
            return await call_next(request)  # type: ignore[no-any-return]

        path = request.url.path

        # === AUTH RATE LIMITING (both Hybrid and Enterprise) ===
        # Run before public-path bypass so login/register limits are enforced.
        if request.method == "POST" and path in self._auth_limiters:
            client_ip = get_client_host(request) or "unknown"
            limiter = self._auth_limiters[path]
            if not limiter.allow(f"ip:{client_ip}"):
                return self._error_response(
                    status.HTTP_429_TOO_MANY_REQUESTS,
                    "Too many attempts. Please try again later.",
                    {"retry_after": "15 minutes" if "login" in path else "1 hour"},
                )

        # Skip public paths after auth limiter checks
        if path in self.PUBLIC_PATHS or path.startswith("/docs"):
            return await call_next(request)  # type: ignore[no-any-return]

        return await call_next(request)  # type: ignore[no-any-return]

    def _error_response(self, status_code: int, message: str, details: dict[str, object] | None = None) -> Response:
        """Create a JSON error response."""
        body: dict[str, Any] = {"detail": message}
        if details:
            body.update(details)  # type: ignore[arg-type]
        return Response(content=json.dumps(body), status_code=status_code, media_type="application/json")
