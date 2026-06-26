"""Optional active hot-storage quota hook injected by server deployments."""

from __future__ import annotations

from collections.abc import Awaitable, Callable

HotStorageChecker = Callable[..., Awaitable[None]]

_checker: HotStorageChecker | None = None


def set_hot_storage_checker(checker: HotStorageChecker | None) -> None:
    global _checker
    _checker = checker


def get_hot_storage_checker() -> HotStorageChecker | None:
    return _checker
