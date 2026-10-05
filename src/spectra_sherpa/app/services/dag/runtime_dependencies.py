"""Dependency readiness derived from execution-contract distributions."""

from __future__ import annotations

import importlib.metadata


def distribution_is_installed(distribution: str) -> bool:
    """Return whether one declared runtime distribution is installed."""

    try:
        importlib.metadata.version(distribution)
    except importlib.metadata.PackageNotFoundError:
        return False
    return True


__all__ = ("distribution_is_installed",)
