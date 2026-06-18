"""Classification namespace for the public SDK."""

from __future__ import annotations

from ._errors import planned


def simca(*args, **kwargs):
    raise planned("ss.classify.simca")


__all__ = ["simca"]
