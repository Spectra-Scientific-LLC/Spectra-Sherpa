"""Intent-level tests for execution vs management rate limiting semantics."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

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
