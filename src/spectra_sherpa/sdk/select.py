"""Variable-selection namespace for the public SDK."""

from __future__ import annotations

from ._errors import planned


def vip(*args, **kwargs):
    raise planned("ss.select.vip")


__all__ = ["vip"]
