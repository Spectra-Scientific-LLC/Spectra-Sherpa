"""Custom node authoring namespace for the public SDK."""

from __future__ import annotations

from ._errors import planned


def define(*args, **kwargs):
    raise planned("ss.node.define")


__all__ = ["define"]
