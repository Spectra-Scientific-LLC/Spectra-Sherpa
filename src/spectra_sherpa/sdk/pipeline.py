"""Pipeline namespace for the public SDK."""

from __future__ import annotations

from ._errors import planned


class Method:
    def __init__(self, *args, **kwargs):
        raise planned("ss.pipeline.Method")


__all__ = ["Method"]
