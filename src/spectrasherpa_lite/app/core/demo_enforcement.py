"""
Mode Enforcement Middleware

Enforces restrictions for HYBRID and DEMO mode deployments:
1. Rate limiting per user/IP (sliding window) - applies in HYBRID and DEMO modes
2. Global password protection (optional) - DEMO mode only
3. Session expiry enforcement - DEMO mode only

Rate limiting uses the persistent file-backed RateLimiter so state survives
restarts and is consistent across Gunicorn workers.
"""
from datetime import datetime, timedelta, timezone
from typing import Optional
import json

from fastapi import Request, Response, status
from starlette.middleware.base import BaseHTTPMiddleware

from app.core.config import app_config, settings
from app.core.security import decode_access_token
from app.services.rate_limiter import RateLimiter


class DemoEnforcementMiddleware(BaseHTTPMiddleware):
    """
    Enforces restrictions for Hybrid and Demo modes:
    1. Rate limiting per user/IP (sliding window) - HYBRID and DEMO modes
    2. Global password protection (if configured) - DEMO mode only
    3. Session expiry enforcement - DEMO mode only
    """

    # Paths that bypass demo restrictions
    PUBLIC_PATHS = {
        "/",
        "/api/v1/health",
        "/api/v1/config",
        "/api/v1/auth/login",
        "/docs",
        "/openapi.json",
        "/api/openapi.json",
    }

    # Paths that count toward rate limit (POST requests only)
    RATE_LIMITED_PATHS = [
        "/api/v1/jobs",
        "/api/v1/workflows",
        "/api/v1/compute",
        "/api/v1/process",
    ]

    def __init__(self, app):
        super().__init__(app)
        # Use file-backed rate limiter: survives restarts, shared across workers
        limit = app_config.rate_limit_executions or 100
        self._rate_limiter = RateLimiter(
            max_calls=limit,
            period_sec=3600,
            state_path=settings.data_dir / "execution_rate_limits.json",
        )

    async def dispatch(self, request: Request, call_next) -> Response:
        # Only active in Hybrid and Demo modes
        if app_config.mode not in ("hybrid", "demo"):
            return await call_next(request)

        path = request.url.path

        # Skip public paths
        if path in self.PUBLIC_PATHS or path.startswith("/docs"):
            return await call_next(request)

        # === DEMO-ONLY FEATURES ===
        if app_config.mode == "demo":
            # 1. Demo Password Protection
            if app_config.demo_password:
                # Enforce on registration and initial access
                if path == "/api/v1/auth/register":
                    demo_pass = request.headers.get("X-Demo-Password")
                    if demo_pass != app_config.demo_password:
                        return self._error_response(
                            status.HTTP_401_UNAUTHORIZED,
                            "Demo password required for registration",
                            {"header": "X-Demo-Password"}
                        )

            # 2. Session Expiry Check
            if app_config.session_expiry_hours:
                auth_header = request.headers.get("Authorization", "")
                if auth_header.startswith("Bearer "):
                    token = auth_header[7:]
                    expiry_error = self._check_session_expiry(token)
                    if expiry_error:
                        return expiry_error

        # === HYBRID + DEMO FEATURES ===
        # 3. Rate Limiting (applies in both Hybrid and Demo modes)
        if app_config.rate_limit_executions:
            # Only rate limit execution-related POST requests
            if request.method == "POST":
                for rate_path in self.RATE_LIMITED_PATHS:
                    if path.startswith(rate_path):
                        client_id = self._get_client_id(request)
                        if not self._rate_limiter.allow(client_id):
                            return self._error_response(
                                status.HTTP_429_TOO_MANY_REQUESTS,
                                "Rate limit exceeded",
                                {
                                    "limit": app_config.rate_limit_executions,
                                    "window": "1 hour",
                                    "retry_after": "Try again later"
                                }
                            )
                        # Add rate limit headers to response
                        remaining = self._rate_limiter.remaining(client_id)
                        response = await call_next(request)
                        response.headers["X-RateLimit-Limit"] = str(app_config.rate_limit_executions)
                        response.headers["X-RateLimit-Remaining"] = str(remaining)
                        return response

        return await call_next(request)

    def _get_client_id(self, request: Request) -> str:
        """Get client identifier for rate limiting (prefer user ID over IP)."""
        # Try to get user ID from token
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            token = auth_header[7:]
            payload = decode_access_token(token)
            if payload and payload.get("sub"):
                return f"user:{payload['sub']}"

        # Fall back to IP
        client_ip = request.client.host if request.client else "unknown"
        return f"ip:{client_ip}"

    def _check_session_expiry(self, token: str) -> Optional[Response]:
        """Check if session has expired based on demo expiry settings."""
        payload = decode_access_token(token)
        if not payload:
            return None  # Let normal auth handle invalid tokens

        # Check if token was issued too long ago
        iat = payload.get("iat")
        if iat:
            issued_at = datetime.fromtimestamp(iat, tz=timezone.utc)
            max_age = timedelta(hours=app_config.session_expiry_hours)
            if datetime.now(timezone.utc) - issued_at > max_age:
                return self._error_response(
                    status.HTTP_401_UNAUTHORIZED,
                    "Demo session expired",
                    {
                        "max_session_hours": app_config.session_expiry_hours,
                        "action": "Please log in again"
                    }
                )

        return None

    def _error_response(self, status_code: int, message: str, details: dict = None) -> Response:
        """Create a JSON error response."""
        body = {"detail": message}
        if details:
            body.update(details)
        return Response(
            content=json.dumps(body),
            status_code=status_code,
            media_type="application/json"
        )
