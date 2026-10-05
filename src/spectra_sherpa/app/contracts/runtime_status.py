"""Optional runtime connectivity policy supplied by an explicit product composition.

This policy can only further restrict the core's egress checks. It cannot grant
consent, credentials, project access, or permission to transmit scientific data.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

RuntimeStatusProvider = Callable[[], dict[str, Any]]
_provider: RuntimeStatusProvider | None = None


def set_runtime_status_provider(provider: RuntimeStatusProvider | None) -> RuntimeStatusProvider | None:
    global _provider
    previous = _provider
    _provider = provider
    return previous


def external_services_available() -> bool:
    if _provider is None:
        return True
    try:
        return _provider().get("is_degraded") is False
    except Exception:
        return False


def runtime_status(mode: str) -> dict[str, Any]:
    if _provider is None:
        return {"mode": mode, "effective_mode": mode, "is_online": True, "is_degraded": False, "network_state": {}}
    try:
        state = _provider()
        if (
            not isinstance(state, dict)
            or not isinstance(state.get("effective_mode"), str)
            or type(state.get("is_online")) is not bool
            or type(state.get("is_degraded")) is not bool
            or not isinstance(state.get("network_state"), dict)
        ):
            raise ValueError("Invalid runtime status from extension")
        return {**state, "mode": mode}
    except Exception:
        return {"mode": mode, "effective_mode": mode, "is_online": False, "is_degraded": True, "network_state": {}}
