"""Tests for per-user demo execution and Sherpa interaction limits."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from spectra_sherpa.app.core.config import DemoContract
from spectra_sherpa.app.core.demo_limits import (
    check_demo_execution,
    check_demo_sherpa,
    demo_execution_remaining,
    demo_limit_error_detail,
    is_demo_limited,
    reset_limiters,
)


@pytest.fixture(autouse=True)
def _reset(monkeypatch, tmp_path):
    """Reset limiters before each test and point state files at tmp_path."""
    reset_limiters()
    monkeypatch.setattr(
        "spectra_sherpa.app.core.demo_limits.settings",
        SimpleNamespace(data_dir=tmp_path),
    )
    yield
    reset_limiters()


def _set_demo(monkeypatch, *, max_executions=3, max_sherpa=2, session_hours=24):
    contract = DemoContract(
        max_executions_per_session=max_executions,
        max_sherpa_interactions=max_sherpa,
    )
    monkeypatch.setattr(
        "spectra_sherpa.app.core.demo_limits.app_config",
        SimpleNamespace(
            site_profile="demo",
            session_expiry_hours=session_hours,
            demo_contract=contract,
        ),
    )


def _set_production(monkeypatch):
    monkeypatch.setattr(
        "spectra_sherpa.app.core.demo_limits.app_config",
        SimpleNamespace(
            site_profile="production",
            session_expiry_hours=None,
            demo_contract=DemoContract(),
        ),
    )


# ===========================================================================
# is_demo_limited
# ===========================================================================


class TestIsDemoLimited:
    def test_true_for_demo_profile(self, monkeypatch):
        _set_demo(monkeypatch)
        assert is_demo_limited() is True

    def test_false_for_production_profile(self, monkeypatch):
        _set_production(monkeypatch)
        assert is_demo_limited() is False


# ===========================================================================
# Execution limits
# ===========================================================================


class TestDemoExecutionLimits:
    def test_allows_up_to_limit(self, monkeypatch):
        _set_demo(monkeypatch, max_executions=3)

        for _ in range(3):
            allowed, remaining = check_demo_execution(user_id=1)
            assert allowed is True

        allowed, remaining = check_demo_execution(user_id=1)
        assert allowed is False
        assert remaining == 0

    def test_different_users_have_separate_quotas(self, monkeypatch):
        _set_demo(monkeypatch, max_executions=2)

        # User 1 exhausts quota
        check_demo_execution(user_id=1)
        check_demo_execution(user_id=1)
        allowed, _ = check_demo_execution(user_id=1)
        assert allowed is False

        # User 2 still has quota
        allowed, _ = check_demo_execution(user_id=2)
        assert allowed is True

    def test_non_demo_always_allows(self, monkeypatch):
        _set_production(monkeypatch)

        for _ in range(100):
            allowed, remaining = check_demo_execution(user_id=1)
            assert allowed is True
            assert remaining == -1

    def test_remaining_read_only(self, monkeypatch):
        _set_demo(monkeypatch, max_executions=3)

        # Reading remaining doesn't consume quota
        assert demo_execution_remaining(user_id=1) == 3
        assert demo_execution_remaining(user_id=1) == 3

        # Consuming one
        check_demo_execution(user_id=1)
        assert demo_execution_remaining(user_id=1) == 2


# ===========================================================================
# Sherpa interaction limits
# ===========================================================================


class TestDemoSherpaLimits:
    def test_allows_up_to_limit(self, monkeypatch):
        _set_demo(monkeypatch, max_sherpa=2)

        allowed, _ = check_demo_sherpa(user_id=1)
        assert allowed is True

        allowed, _ = check_demo_sherpa(user_id=1)
        assert allowed is True

        allowed, remaining = check_demo_sherpa(user_id=1)
        assert allowed is False
        assert remaining == 0

    def test_different_users_have_separate_quotas(self, monkeypatch):
        _set_demo(monkeypatch, max_sherpa=1)

        check_demo_sherpa(user_id=1)
        allowed, _ = check_demo_sherpa(user_id=1)
        assert allowed is False

        allowed, _ = check_demo_sherpa(user_id=2)
        assert allowed is True

    def test_non_demo_always_allows(self, monkeypatch):
        _set_production(monkeypatch)

        for _ in range(100):
            allowed, remaining = check_demo_sherpa(user_id=1)
            assert allowed is True
            assert remaining == -1


# ===========================================================================
# Error detail
# ===========================================================================


class TestDemoLimitErrorDetail:
    def test_execution_error_detail(self, monkeypatch):
        _set_demo(monkeypatch, max_executions=25)

        detail = demo_limit_error_detail("execution", 0)
        assert "25 per session" in detail["message"]
        assert detail["upgrade_url"] == ""
        assert detail["available_plans"] == []
        assert detail["limit"] == 25
        assert detail["remaining"] == 0

    def test_sherpa_error_detail(self, monkeypatch):
        _set_demo(monkeypatch, max_sherpa=20)

        detail = demo_limit_error_detail("sherpa", 0)
        assert "20 per session" in detail["message"]
        assert detail["upgrade_url"] == ""


# ===========================================================================
# Anonymous user
# ===========================================================================


class TestAnonymousUser:
    def test_anonymous_tracked_separately(self, monkeypatch):
        _set_demo(monkeypatch, max_executions=2)

        check_demo_execution(user_id=None)
        check_demo_execution(user_id=None)
        allowed, _ = check_demo_execution(user_id=None)
        assert allowed is False

        # Named user still has quota
        allowed, _ = check_demo_execution(user_id=1)
        assert allowed is True
