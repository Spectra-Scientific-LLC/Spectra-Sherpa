"""Plotting namespace for the public SDK."""

from __future__ import annotations

from ._errors import planned


def scores(*args, **kwargs):
    raise planned("ss.plot.scores")


def loadings(*args, **kwargs):
    raise planned("ss.plot.loadings")


__all__ = ["scores", "loadings"]
