"""
Rate Limit Middleware

Enforces rate limiting for HYBRID and ENTERPRISE mode deployments:
1. Auth endpoint rate limiting per IP (login, register)
2. Execution rate limiting per user/IP (sliding window)

Rate limiting uses the persistent file-backed RateLimiter so state survives
restarts and is consistent across Gunicorn workers.

Enterprise-specific enforcement (password gating, session expiry, CORS
validation) lives in spectra-server and is injected via create_app() hooks.
"""

import json
from typing import Any

from fastapi import Request, Response, status
from starlette.middleware.base import BaseHTTPMiddleware

from spectra_sherpa.app.core.app_paths import get_app_data_paths
from spectra_sherpa.app.core.config import app_config, settings
from spectra_sherpa.app.core.demo_limits import check_demo_execution, demo_limit_error_detail
from spectra_sherpa.app.core.mode_policy import has_rate_limits
from spectra_sherpa.app.core.security import decode_access_token, get_client_host
from spectra_sherpa.app.services.rate_limiter import RateLimiter


class RateLimitMiddleware(BaseHTTPMiddleware):
    """
    Rate limiting for Hybrid and Enterprise modes:
    1. Auth endpoint rate limiting per IP (login, register)
    2. Execution rate limiting per user/IP (sliding window)
    """

    # Paths that bypass rate limiting
    PUBLIC_PATHS = {
        "/",
        "/api/v1/health",
        "/api/v1/config",
        "/api/v1/config/demo/quota",
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
        # Use file-backed rate limiter: survives restarts, shared across workers
        limit = app_config.rate_limit_executions or 100
        app_paths = get_app_data_paths(settings.data_dir)
        self._rate_limiter = RateLimiter(
            max_calls=limit,
            period_sec=3600,
            state_path=app_paths.execution_rate_limits_state,
        )
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

        # === DEMO EXECUTION LIMIT (tighter per-session cap) ===
        # Only actual execution endpoints consume demo quota — not workflow
        # creation, version restore, or other management POSTs.
        if request.method == "POST" and self._is_execution_path(path):
            user_id = self._get_user_id(request)
            allowed, remaining = check_demo_execution(user_id)
            if not allowed:
                return self._error_response(
                    status.HTTP_429_TOO_MANY_REQUESTS,
                    "Demo execution limit reached",
                    demo_limit_error_detail("execution", remaining),
                )

        # === EXECUTION RATE LIMITING (Hybrid + Enterprise) ===
        if app_config.rate_limit_executions:
            # Only rate limit actual execution POSTs — not workflow CRUD,
            # version restore, or other management operations.
            if request.method == "POST" and self._is_execution_path(path):
                client_id = self._get_client_id(request)
                if not self._rate_limiter.allow(client_id):
                    return self._error_response(
                        status.HTTP_429_TOO_MANY_REQUESTS,
                        "Rate limit exceeded",
                        {
                            "limit": app_config.rate_limit_executions,
                            "window": "1 hour",
                            "retry_after": "Try again later",
                        },
                    )
                # Add rate limit headers to response
                remaining = self._rate_limiter.remaining(client_id)
                response = await call_next(request)
                response.headers["X-RateLimit-Limit"] = str(app_config.rate_limit_executions)
                response.headers["X-RateLimit-Remaining"] = str(remaining)
                return response  # type: ignore[no-any-return]

        return await call_next(request)  # type: ignore[no-any-return]

    # Paths where a POST actually triggers compute.
    # Both demo quota and general rate limiting use _is_execution_path().
    EXECUTION_PATHS = [
        "/api/v1/workflows/trial/execute",
        "/api/v1/jobs",
        "/api/v1/compute",
        "/api/v1/deploy",
    ]
    EXECUTION_SUFFIXES = ["/execute", "/predict"]

    def _is_execution_path(self, path: str) -> bool:
        """Return True only for POST paths that represent real compute work."""
        for ep in self.EXECUTION_PATHS:
            if path.startswith(ep):
                return True
        # Match POST /api/v1/workflows/{id}/execute
        for suffix in self.EXECUTION_SUFFIXES:
            if path.endswith(suffix):
                return True
        return False

    def _get_user_id(self, request: Request) -> int | None:
        """Extract the numeric user ID from the Bearer token, or None."""
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            payload = decode_access_token(auth_header[7:])
            if payload and payload.get("sub"):
                try:
                    return int(payload["sub"])
                except (ValueError, TypeError):
                    pass
        return None

    def _get_client_id(self, request: Request) -> str:
        """Get client identifier for rate limiting (prefer user ID over IP)."""
        user_id = self._get_user_id(request)
        if user_id is not None:
            return f"user:{user_id}"

        # Fall back to IP (respects TRUST_PROXY for real client IP behind proxy)
        client_ip = get_client_host(request) or "unknown"
        return f"ip:{client_ip}"

    def _error_response(self, status_code: int, message: str, details: dict[str, object] | None = None) -> Response:
        """Create a JSON error response."""
        body: dict[str, Any] = {"detail": message}
        if details:
            body.update(details)  # type: ignore[arg-type]
        return Response(content=json.dumps(body), status_code=status_code, media_type="application/json")
