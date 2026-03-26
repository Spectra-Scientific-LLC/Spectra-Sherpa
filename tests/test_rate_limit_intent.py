"""Intent-level tests for execution vs management rate limiting semantics."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from starlette.requests import Request
from starlette.responses import Response

from spectra_sherpa.app.core.config import DemoContract, app_config
from spectra_sherpa.app.core.demo_limits import demo_execution_remaining, reset_demo_limits
from spectra_sherpa.app.core.rate_limit_middleware import RateLimitMiddleware


class TestRateLimitIntent:
    @pytest.fixture
    def middleware(self) -> RateLimitMiddleware:
        return RateLimitMiddleware(MagicMock())

    @pytest.mark.parametrize(
        "path",
        [
            "/api/v1/workflows/42/execute",
            "/api/v1/workflows/trial/execute",
            "/api/v1/jobs",
            "/api/v1/compute/execute",
            "/api/v1/deploy",
            "/api/v1/workflows/99/predict",
        ],
    )
    def test_execution_posts_are_rate_limited(self, middleware: RateLimitMiddleware, path: str) -> None:
        assert middleware._is_execution_path(path) is True

    @pytest.mark.parametrize(
        "path",
        [
            "/api/v1/workflows",
            "/api/v1/workflows/7",
            "/api/v1/workflows/7/versions/2/restore",
            "/api/v1/workflows/7/nodes",
            "/api/v1/auth/login",
            "/api/v1/config",
        ],
    )
    def test_management_posts_are_not_rate_limited(self, middleware: RateLimitMiddleware, path: str) -> None:
        assert middleware._is_execution_path(path) is False

    @pytest.mark.asyncio
    async def test_demo_execution_limit_is_bypassed_for_admin(self, middleware: RateLimitMiddleware) -> None:
        original_mode = app_config.mode
        original_profile = app_config.site_profile
        original_contract = app_config.demo_contract
        app_config.mode = "enterprise"
        app_config.site_profile = "demo"
        app_config.demo_contract = DemoContract(
            max_executions_per_session=1,
            max_sherpa_interactions=1,
            session_expiry_hours=24,
            upgrade_url="https://example.com/upgrade",
        )
        reset_demo_limits()

        scope = {
            "type": "http",
            "method": "POST",
            "path": "/api/v1/workflows/42/execute",
            "headers": [],
            "query_string": b"",
            "client": ("127.0.0.1", 12345),
        }
        request = Request(scope)
        middleware._get_authenticated_user = AsyncMock(  # type: ignore[method-assign]
            return_value=SimpleNamespace(id=99, is_superuser=True)
        )

        async def call_next(_request: Request) -> Response:
            return Response("ok", status_code=200)

        try:
            response = await middleware.dispatch(request, call_next)
            assert response.status_code == 200
            assert demo_execution_remaining(99) == 1
        finally:
            app_config.mode = original_mode
            app_config.site_profile = original_profile
            app_config.demo_contract = original_contract
            reset_demo_limits()
