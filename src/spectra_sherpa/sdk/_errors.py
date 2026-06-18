"""SDK error helpers."""

from __future__ import annotations


class SDKNotImplementedError(NotImplementedError):
    """Raised when a planned SDK namespace is present but not implemented yet."""


def planned(feature: str, *, phase: str | None = None) -> SDKNotImplementedError:
    suffix = f" Planned for {phase}." if phase else ""
    return SDKNotImplementedError(f"{feature} is not implemented in the public SDK yet.{suffix}")
