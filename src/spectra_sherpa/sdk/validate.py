"""Validation namespace for the public SDK."""

from __future__ import annotations

from ._errors import planned


def cross_validate(*args, **kwargs):
    raise planned("ss.validate.cross_validate")


def metrics(*args, **kwargs):
    raise planned("ss.validate.metrics")


__all__ = ["cross_validate", "metrics"]
