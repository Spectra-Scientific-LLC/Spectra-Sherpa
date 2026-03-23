"""
Demo Mode Rate Limiting

Enforces per-session execution and Sherpa interaction limits for demo site profile.
This module is used by spectra-server in hybrid/enterprise mode when site_profile="demo".

In OSS mode (site_profile=None), all checks return (True, max_limit) allowing unlimited access.

State is persisted to disk so limits survive restarts and are shared across Gunicorn workers.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Tuple, TypedDict, cast

from spectra_sherpa.app.core.app_paths import get_app_data_paths
from spectra_sherpa.app.core.config import app_config, settings


class _DemoCounterState(TypedDict):
    executions: int
    sherpa_interactions: int
    last_activity: str


class DemoLimitTracker:
    """
    Tracks demo usage quotas with file-backed persistence.

    Stores per-user counters for:
    - Workflow executions
    - Sherpa AI interactions
    """

    def __init__(self, state_path: Path):
        self.state_path = state_path
        try:
            self.state_path.parent.mkdir(parents=True, exist_ok=True)
        except OSError:
            pass  # directory may already exist or be read-only in test/CI
        self._state = self._load_state()

    def _load_state(self) -> dict[str, _DemoCounterState]:
        """Load state from disk or initialize empty."""
        if self.state_path.exists():
            try:
                with open(self.state_path, "r") as f:
                    data = cast(dict[str, dict[str, Any]], json.load(f))
                # Clean expired sessions (older than session_expiry_hours)
                cutoff = datetime.now() - timedelta(hours=app_config.demo_contract.session_expiry_hours)
                cleaned: dict[str, _DemoCounterState] = {
                    uid: counters  # type: ignore[misc]
                    for uid, counters in data.items()
                    if isinstance(counters, dict)
                    and datetime.fromisoformat(str(counters.get("last_activity", "1970-01-01"))) > cutoff
                }
                return cleaned
            except (json.JSONDecodeError, OSError):
                return {}
        return {}

    def _save_state(self):
        """Persist state to disk."""
        try:
            with open(self.state_path, "w") as f:
                json.dump(self._state, f, indent=2)
        except OSError:
            # Fail silently in case of permission issues
            pass

    def _get_user_key(self, user_id: int | None) -> str:
        """Get storage key for user (IP-based fallback for anonymous)."""
        if user_id is not None:
            return f"user:{user_id}"
        # For anonymous users, use a shared key
        # (In production, spectra-server uses IP-based tracking)
        return "anon:shared"

    def _get_counters(self, user_id: int | None) -> _DemoCounterState:
        """Get current counters for user, initializing if needed."""
        key = self._get_user_key(user_id)
        if key not in self._state:
            self._state[key] = {
                "executions": 0,
                "sherpa_interactions": 0,
                "last_activity": datetime.now().isoformat(),
            }
        return self._state[key]

    def check_execution(self, user_id: int | None) -> Tuple[bool, int]:
        """
        Check if user can execute a workflow.

        Returns:
            (allowed: bool, remaining: int)
        """
        # OSS mode: unlimited
        if app_config.site_profile != "demo":
            return (True, 999999)

        counters = self._get_counters(user_id)
        limit = app_config.demo_contract.max_executions_per_session
        current = counters["executions"]
        remaining = max(0, limit - current)

        return (current < limit, remaining)

    def consume_execution(self, user_id: int | None):
        """Record an execution (call after successful check)."""
        if app_config.site_profile != "demo":
            return

        counters = self._get_counters(user_id)
        counters["executions"] += 1
        counters["last_activity"] = datetime.now().isoformat()
        self._save_state()

    def check_sherpa(self, user_id: int | None) -> Tuple[bool, int]:
        """
        Check if user can make a Sherpa AI interaction.

        Returns:
            (allowed: bool, remaining: int)
        """
        # OSS mode: unlimited
        if app_config.site_profile != "demo":
            return (True, 999999)

        counters = self._get_counters(user_id)
        limit = app_config.demo_contract.max_sherpa_interactions
        current = counters["sherpa_interactions"]
        remaining = max(0, limit - current)

        return (current < limit, remaining)

    def consume_sherpa(self, user_id: int | None):
        """Record a Sherpa interaction (call after successful check)."""
        if app_config.site_profile != "demo":
            return

        counters = self._get_counters(user_id)
        counters["sherpa_interactions"] += 1
        counters["last_activity"] = datetime.now().isoformat()
        self._save_state()

    def execution_remaining(self, user_id: int | None) -> int:
        """Get remaining execution quota."""
        if app_config.site_profile != "demo":
            return 999999

        counters = self._get_counters(user_id)
        limit = app_config.demo_contract.max_executions_per_session
        return max(0, limit - counters["executions"])

    def sherpa_remaining(self, user_id: int | None) -> int:
        """Get remaining Sherpa interaction quota."""
        if app_config.site_profile != "demo":
            return 999999

        counters = self._get_counters(user_id)
        limit = app_config.demo_contract.max_sherpa_interactions
        return max(0, limit - counters["sherpa_interactions"])

    def reset(self, user_id: int | None = None):
        """Reset counters (for testing or admin reset)."""
        if user_id is None:
            # Reset all
            self._state = {}
        else:
            key = self._get_user_key(user_id)
            if key in self._state:
                del self._state[key]
        self._save_state()


# Global tracker instance
_tracker = DemoLimitTracker(get_app_data_paths(settings.data_dir).demo_limits_state)


def check_demo_execution(user_id: int | None) -> Tuple[bool, int]:
    """
    Check if user can execute a workflow.

    Returns:
        (allowed: bool, remaining: int after consumption)
    """
    allowed, _ = _tracker.check_execution(user_id)
    if allowed:
        # Consume quota immediately to prevent race conditions
        _tracker.consume_execution(user_id)
        remaining_after = _tracker.execution_remaining(user_id)
        return (True, remaining_after)
    return (False, 0)


def check_demo_sherpa(user_id: int | None) -> Tuple[bool, int]:
    """
    Check if user can make a Sherpa AI interaction.

    Returns:
        (allowed: bool, remaining: int after consumption)
    """
    allowed, _ = _tracker.check_sherpa(user_id)
    if allowed:
        # Consume quota immediately to prevent race conditions
        _tracker.consume_sherpa(user_id)
        remaining_after = _tracker.sherpa_remaining(user_id)
        return (True, remaining_after)
    return (False, 0)


def check_demo_sherpa_available(user_id: int | None) -> Tuple[bool, int]:
    """Check quota without consuming.  Call :func:`consume_demo_sherpa` on success."""
    allowed, remaining = _tracker.check_sherpa(user_id)
    return (allowed, remaining)


def consume_demo_sherpa(user_id: int | None) -> int:
    """Consume one Sherpa interaction quota.  Return remaining count."""
    _tracker.consume_sherpa(user_id)
    return _tracker.sherpa_remaining(user_id)


def demo_execution_remaining(user_id: int | None) -> int:
    """Get remaining execution quota without consuming."""
    return _tracker.execution_remaining(user_id)


def demo_sherpa_remaining(user_id: int | None) -> int:
    """Get remaining Sherpa interaction quota without consuming."""
    return _tracker.sherpa_remaining(user_id)


def demo_limit_error_detail(limit_type: str, remaining: int) -> dict:
    """
    Generate standardized error detail for demo limit exceeded.

    Args:
        limit_type: "execution" or "sherpa"
        remaining: Remaining quota (should be 0 if limit exceeded)

    Returns:
        Dict with error details and upgrade URL
    """
    contract = app_config.demo_contract

    if limit_type == "execution":
        limit = contract.max_executions_per_session
        message = f"Demo execution limit reached ({limit} executions per session)"
    elif limit_type == "sherpa":
        limit = contract.max_sherpa_interactions
        message = f"Demo Sherpa interaction limit reached ({limit} interactions per session)"
    else:
        limit = 0
        message = "Demo limit reached"

    return {
        "limit_type": limit_type,
        "limit": limit,
        "remaining": remaining,
        "message": message,
        "upgrade_url": contract.upgrade_url or "",
        "session_expiry_hours": contract.session_expiry_hours,
    }


def reset_demo_limits(user_id: int | None = None):
    """
    Reset demo limits for a user (or all users if user_id=None).

    For testing and admin operations.
    """
    _tracker.reset(user_id)
