"""
Integration tests for demo limits enforcement.

Tests that demo mode quotas are properly enforced in hybrid/enterprise mode
and gracefully handle OSS mode (unlimited access).
"""

from __future__ import annotations

import pytest

from spectra_sherpa.app.api.v1.routes.config import get_demo_quota
from spectra_sherpa.app.core.config import DemoContract, app_config
from spectra_sherpa.app.core.demo_limits import (
    check_demo_execution,
    check_demo_sherpa,
    demo_execution_remaining,
    demo_limit_error_detail,
    demo_sherpa_remaining,
    reset_demo_limits,
)


@pytest.fixture(autouse=True)
def reset_limits_after_test():
    """Reset demo limits after each test."""
    yield
    reset_demo_limits()


@pytest.fixture
def demo_mode():
    """Activate demo mode for testing."""
    original_profile = app_config.site_profile
    original_contract = app_config.demo_contract

    # Activate demo mode with tight limits
    app_config.site_profile = "demo"
    app_config.demo_contract = DemoContract(
        max_executions_per_session=3,
        max_sherpa_interactions=5,
        session_expiry_hours=24,
        upgrade_url="https://example.com/upgrade",
    )

    yield

    # Restore original config
    app_config.site_profile = original_profile
    app_config.demo_contract = original_contract
    reset_demo_limits()


def test_oss_mode_unlimited_executions():
    """Test that OSS mode allows unlimited executions."""
    # OSS mode (site_profile=None)
    assert app_config.site_profile is None

    # Should allow unlimited executions
    for _ in range(100):
        allowed, remaining = check_demo_execution(user_id=123)
        assert allowed is True
        assert remaining == 999999


def test_oss_mode_unlimited_sherpa():
    """Test that OSS mode allows unlimited Sherpa interactions."""
    # OSS mode (site_profile=None)
    assert app_config.site_profile is None

    # Should allow unlimited Sherpa interactions
    for _ in range(100):
        allowed, remaining = check_demo_sherpa(user_id=123)
        assert allowed is True
        assert remaining == 999999


def test_demo_mode_execution_limit(demo_mode):
    """Test that demo mode enforces execution limits."""
    user_id = 456

    # First 3 executions should succeed
    for i in range(3):
        allowed, remaining = check_demo_execution(user_id)
        assert allowed is True
        assert remaining == 3 - i - 1  # Counts down

    # 4th execution should fail
    allowed, remaining = check_demo_execution(user_id)
    assert allowed is False
    assert remaining == 0


def test_demo_mode_sherpa_limit(demo_mode):
    """Test that demo mode enforces Sherpa interaction limits."""
    user_id = 789

    # First 5 interactions should succeed
    for i in range(5):
        allowed, remaining = check_demo_sherpa(user_id)
        assert allowed is True
        assert remaining == 5 - i - 1

    # 6th interaction should fail
    allowed, remaining = check_demo_sherpa(user_id)
    assert allowed is False
    assert remaining == 0


def test_demo_mode_separate_users(demo_mode):
    """Test that demo limits are tracked separately per user."""
    user_a = 100
    user_b = 200

    # User A uses 2 executions
    check_demo_execution(user_a)
    check_demo_execution(user_a)

    # User B should still have full quota
    allowed, remaining = check_demo_execution(user_b)
    assert allowed is True
    assert remaining == 2  # 3 - 1 (just consumed)

    # User A should have 1 remaining
    assert demo_execution_remaining(user_a) == 1
    assert demo_execution_remaining(user_b) == 2


def test_demo_limit_error_detail_execution(demo_mode):
    """Test error detail formatting for execution limits."""
    detail = demo_limit_error_detail("execution", 0)

    assert detail["limit_type"] == "execution"
    assert detail["limit"] == 3
    assert detail["remaining"] == 0
    assert "Demo execution limit reached" in detail["message"]
    assert detail["upgrade_url"] == "https://example.com/upgrade"
    assert detail["session_expiry_hours"] == 24


def test_demo_limit_error_detail_sherpa(demo_mode):
    """Test error detail formatting for Sherpa limits."""
    detail = demo_limit_error_detail("sherpa", 0)

    assert detail["limit_type"] == "sherpa"
    assert detail["limit"] == 5
    assert detail["remaining"] == 0
    assert "Demo Sherpa interaction limit reached" in detail["message"]


def test_demo_execution_remaining_query(demo_mode):
    """Test querying remaining quota without consuming."""
    user_id = 300

    # Initially should have full quota
    assert demo_execution_remaining(user_id) == 3

    # Consume one
    check_demo_execution(user_id)

    # Should show 2 remaining
    assert demo_execution_remaining(user_id) == 2


def test_demo_sherpa_remaining_query(demo_mode):
    """Test querying remaining Sherpa quota without consuming."""
    user_id = 400

    # Initially should have full quota
    assert demo_sherpa_remaining(user_id) == 5

    # Consume two
    check_demo_sherpa(user_id)
    check_demo_sherpa(user_id)

    # Should show 3 remaining
    assert demo_sherpa_remaining(user_id) == 3


def test_reset_demo_limits_specific_user(demo_mode):
    """Test resetting limits for a specific user."""
    user_id = 500

    # Consume all executions
    for _ in range(3):
        check_demo_execution(user_id)

    assert demo_execution_remaining(user_id) == 0

    # Reset
    reset_demo_limits(user_id)

    # Should have full quota again
    assert demo_execution_remaining(user_id) == 3


def test_reset_demo_limits_all_users(demo_mode):
    """Test resetting limits for all users."""
    user_a = 600
    user_b = 700

    # Both users consume quota
    check_demo_execution(user_a)
    check_demo_execution(user_b)

    # Reset all
    reset_demo_limits()

    # Both should have full quota
    assert demo_execution_remaining(user_a) == 3
    assert demo_execution_remaining(user_b) == 3


def test_anonymous_user_tracking(demo_mode):
    """Test that anonymous users (None user_id) are tracked."""
    # Anonymous users use a shared key
    allowed, remaining = check_demo_execution(None)
    assert allowed is True
    assert remaining == 2  # 3 - 1

    # Second anonymous execution
    allowed, remaining = check_demo_execution(None)
    assert allowed is True
    assert remaining == 1


def test_demo_mode_toggles_enforcement(demo_mode):
    """Test that toggling site_profile changes enforcement."""
    user_id = 800

    # In demo mode, enforce limits
    check_demo_execution(user_id)
    assert demo_execution_remaining(user_id) == 2

    # Switch to OSS mode
    app_config.site_profile = None

    # Should now be unlimited
    allowed, remaining = check_demo_execution(user_id)
    assert allowed is True
    assert remaining == 999999

    # Switch back to demo mode
    app_config.site_profile = "demo"

    # Should return to previous count (state persists)
    # Note: After the check in OSS mode, the counter wasn't incremented
    assert demo_execution_remaining(user_id) == 2


@pytest.mark.asyncio
async def test_demo_quota_reports_admin_bypass(demo_mode):
    quota = await get_demo_quota(current_user=type("Admin", (), {"id": 42, "is_superuser": True})())

    assert quota["demo"] is True
    assert quota["adminBypass"] is True
    assert quota["executions"]["remaining"] == quota["executions"]["limit"] == 3
    assert quota["sherpa"]["remaining"] == quota["sherpa"]["limit"] == 5


def test_rate_limit_executions_config_field():
    """Test that rate_limit_executions field exists in AppConfig."""
    # This field is used by RateLimitMiddleware
    assert hasattr(app_config, "rate_limit_executions")

    # Should be settable by spectra-server
    original = app_config.rate_limit_executions
    app_config.rate_limit_executions = 100
    assert app_config.rate_limit_executions == 100

    # Cleanup
    app_config.rate_limit_executions = original
