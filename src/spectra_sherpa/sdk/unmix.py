"""Unmixing namespace for the public SDK."""

from __future__ import annotations

from ._errors import planned


def mcr_als(*args, **kwargs):
    raise planned("ss.unmix.mcr_als")


__all__ = ["mcr_als"]
